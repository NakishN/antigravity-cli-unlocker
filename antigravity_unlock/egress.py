"""
Foreign-egress routing for agy.

Antigravity has TWO independent regional gates, and the binary patch clears only
the first one:

1. The account-level *client* gate over the server's ``ineligible`` protobuf
   field.  Renaming that literal is what ``patcher`` does.
2. A *server-side* check on the request's source IP, answered with
   ``FAILED_PRECONDITION (code 400): User location is not supported for the API
   use``.  That string occurs nowhere in the binary - it arrives in the response
   body - so no byte-level patch can remove it.

Gate 2 is only beaten by changing the source IP Google observes, i.e. by sending
agy's HTTPS traffic out through an exit in a supported region.  Measured
2026-09-27 on agy 1.2.11, patch applied, one account, nothing else changed:
direct RU egress ``95.26.85.26`` -> region 400 on every call; the same binary
through a SOCKS5 exit in Amsterdam -> a real completion (``PONG``).

agy needs no patching to be proxied.  It honours ``HTTPS_PROXY``/``https_proxy``
and understands ``socks5://`` and ``socks5h://`` natively - all three verified
by measurement rather than assumed: a dead ``http://`` proxy value produced
``proxyconnect tcp: dial tcp 127.0.0.1:9: connect: connection refused`` instead
of being ignored, and both SOCKS5 spellings produced a model completion.  There
is no ``--proxy`` flag and no proxy key in ``~/.gemini/config/config.json``, so
the process environment is the only lever, and this module owns setting it.

``socks5h`` (remote resolution) is the safer default wherever local DNS lies.
A Clash/mihomo TUN in fake-ip mode answers every A query with a synthetic
``198.18.0.0/16`` address; with plain ``socks5`` Go resolves that fake address
itself and hands it to the proxy, which then cannot reach it.  With ``socks5h``
the name is resolved by the proxy, on the far side, and the fake-ip problem
never arises.

Everything here is stdlib-only.  The project deliberately carries no runtime
dependencies (1.5.0 dropped ``cryptography`` along with the MITM proxy), so the
SOCKS5 handshake is implemented directly instead of pulling in PySocks.
"""

import json
import mmap
import os
import re
import socket
import ssl
import struct
import subprocess
import urllib.error
import urllib.parse
import urllib.request

# Regions where Antigravity is unavailable.  A request originating here is
# rejected by Google server-side, which is gate 2 above.
BLOCKED_COUNTRIES = {"RU", "BY", "IR", "CU", "KP", "SY", "CR"}

GEO_URLS = (
    "https://ipinfo.io/json",
    "http://ip-api.com/json/",
)

DEFAULT_TIMEOUT = 10.0

# A live probe is a real model call: slow, and it costs quota.  Keep it well
# under agy's own print timeout so the classification below is ours, not a
# truncation.
PROBE_PROMPT = "Reply with exactly: EGRESS_OK"
PROBE_TIMEOUT = 120.0

# Named routes a user can write instead of remembering an address.  Cloudflare
# WARP in proxy mode is offered because it needs no server of the user's own -
# but read the hint: measured from Russia it does not actually leave the country.
PRESETS = {
    "warp": {
        "url": "socks5h://127.0.0.1:40000",
        "hint": (
            "Cloudflare WARP, proxy mode - a local SOCKS5 listener, no TUN and no "
            "system DNS change. Only the daemon needs root; the socket is 0777, so "
            "warp-cli itself runs unprivileged. The registration subcommand is "
            "'registration new', NOT 'register':\n"
            "  sudo systemctl enable --now warp-svc\n"
            "  warp-cli registration show     # if empty: warp-cli registration new\n"
            "  warp-cli mode proxy\n"
            "  warp-cli proxy port 40000\n"
            "  warp-cli connect\n"
            "\n"
            "WARNING, measured 2026-09-27 from a Russian ISP: WARP exits at the "
            "nearest Cloudflare edge, which is still in Russia (104.28.232.201, "
            "AS13335, geolocated Samara), and Google answered the same region 400. "
            "'egress test' reports that as REGION-BLOCKED instead of guessing. A "
            "free WARP tunnel is not a guaranteed exit from a blocked country."
        ),
    },
}

SUPPORTED_SCHEMES = ("socks5", "socks5h", "http", "https")

DEFAULT_PORTS = {"socks5": 1080, "socks5h": 1080, "http": 80, "https": 443}

# What a live probe can conclude.  These are outcomes, not severities: the
# caller decides what to do with them.
STATUS_OK = "ok"
STATUS_REGION_BLOCKED = "region_blocked"
STATUS_PROXY_UNREACHABLE = "proxy_unreachable"
STATUS_PROXY_AUTH = "proxy_auth"
STATUS_GATE = "gate"
STATUS_CREDENTIALS = "credentials"
STATUS_TIMEOUT = "timeout"
# The request was fine, the *network* was not.  Distinct from STATUS_GATE
# because the two demand opposite advice: a gate means re-patch, this means
# just try again.
STATUS_TRANSIENT = "transient"
STATUS_UNKNOWN = "unknown"

# Substrings in agy's own output, matched case-insensitively.  Each one was
# observed in a real run rather than guessed at, and the comment records what
# produced it.
REGION_MARKERS = (
    # agy, RU egress, patched binary: the server-side geo refusal.
    "user location is not supported",
)
GATE_MARKERS = (
    # agy, unpatched binary: the client-side eligibility gate.
    "not eligible",
    "eligibility check failed",
    "account ineligible",
    "not currently available in your location",
)
PROXY_UNREACHABLE_MARKERS = (
    # Go's transport, proxy port closed.
    "proxyconnect",
    "proxy server rejected",
    "cannot connect to proxy",
)
PROXY_AUTH_MARKERS = (
    # An upstream that wants credentials we did not supply.  Observed as
    # `407 Proxy Authentication Required` with `Proxy-Authenticate: Basic`.
    "proxy authentication required",
    "407",
)
CREDENTIAL_MARKERS = (
    # agy, no OAuth token: proves the route is fine and only auth is missing.
    "credentials_missing",
)
# Transport-level failures.  These are tested *before* the gate markers,
# because agy reports a failed eligibility HTTP request under the same
# "Eligibility check failed" heading whether the server said "ineligible" or
# the socket died mid-flight.  Observed verbatim on 2026-10-07, patched agy
# 1.3.1 behind a Clash TUN:
#
#   error: Eligibility check failed: failed to get profile picture: Get
#   "https://lh3.googleusercontent.com/a/...": EOF
#
# That is one dropped TLS connection while fetching an avatar, not a
# regional verdict, and the very next run answered DOCTOR_OK.  Classifying it
# as STATUS_GATE told a fully-patched, working install that its patch had been
# reverted - the same mistake the proxy ordering above already had to be
# corrected for.
TRANSIENT_MARKERS = (
    ": eof",
    "unexpected eof",
    "connection reset by peer",
    "connection refused",
    "broken pipe",
    "i/o timeout",
    "tls handshake timeout",
    "context deadline exceeded",
    "no such host",
    "server misbehaving",
    "http2: server sent goaway",
    "network is unreachable",
)

_SOCKS5_REPLIES = {
    0x01: "general SOCKS server failure",
    0x02: "connection not allowed by ruleset",
    0x03: "network unreachable",
    0x04: "host unreachable",
    0x05: "connection refused",
    0x06: "TTL expired",
    0x07: "command not supported",
    0x08: "address type not supported",
}


class EgressError(Exception):
    """A route could not be used.  Carries a message meant for a human."""


# --------------------------------------------------------------------------
# Route specifications
# --------------------------------------------------------------------------

def resolve_spec(spec):
    """Turn one config entry into ``(url, label)``.

    Accepts a bare URL, a preset name, or a dict with ``url``/``preset`` plus an
    optional ``label``.  Presets exist so a user can write ``warp`` rather than
    remembering which port Cloudflare listens on.

    Raises ``ValueError`` with a message the CLI can print as-is.
    """
    label = None
    if isinstance(spec, dict):
        label = spec.get("label") or None
        url = spec.get("url")
        preset = spec.get("preset")
        if not url and preset:
            url = preset_url(preset)
        if not url:
            raise ValueError("route entry has neither 'url' nor 'preset'")
    else:
        url = spec
        if isinstance(url, str) and url.lower() in PRESETS:
            label = label or url.lower()
            url = preset_url(url)

    if not isinstance(url, str) or not url.strip():
        raise ValueError("route URL must be a non-empty string")

    url = url.strip()
    if not label:
        label = url
    return url, label


def preset_url(name):
    """The URL behind preset *name*, or None when there is no such preset."""
    entry = PRESETS.get(str(name).lower())
    return entry["url"] if entry else None


def preset_hint(name):
    """Setup help for preset *name*, or None."""
    entry = PRESETS.get(str(name).lower())
    return entry.get("hint") if entry else None


# scheme://user:password@host  ->  scheme://user:***@host
_CREDENTIAL_RE = re.compile(r"(://[^/?#@]*:)([^/?#]*)@")


def redact_url(url):
    """The URL with any password replaced by ``***``.

    Routes end up in labels, log lines and error messages, and a paid proxy's
    password in a bug report is a leaked credential.  Redaction happens at the
    boundary where text is produced rather than at each print site, so there is
    no path that has to remember to do it.
    """
    return _CREDENTIAL_RE.sub(r"\1***@", str(url))


def parse_route(url, label=None):
    """Validate a proxy URL and split it into its parts.

    Returns ``(route, None)`` on success or ``(None, message)`` on failure, the
    two-value convention the rest of this package uses.  Credentials in the URL
    are kept so an authenticated upstream works; the default *label* is the
    redacted URL, because the label is what gets printed.
    """
    if label is None:
        label = redact_url(url)
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError as e:
        return None, f"unparseable proxy URL {url!r}: {e}"

    scheme = (parts.scheme or "").lower()
    if scheme not in SUPPORTED_SCHEMES:
        return None, (
            f"unsupported proxy scheme {scheme or '(none)'!r} in {redact_url(url)!r}; "
            f"use one of {', '.join(SUPPORTED_SCHEMES)}"
        )

    host = parts.hostname
    if not host:
        return None, f"proxy URL {redact_url(url)!r} has no host"

    port = parts.port or DEFAULT_PORTS[scheme]
    if not 0 < port < 65536:
        return None, f"proxy URL {redact_url(url)!r} has an impossible port {port}"

    return {
        "label": label,
        "url": url,
        "scheme": scheme,
        "host": host,
        "port": port,
        "user": urllib.parse.unquote(parts.username) if parts.username else None,
        "password": urllib.parse.unquote(parts.password) if parts.password else None,
        # True when the proxy resolves the target name itself.  Only meaningful
        # for SOCKS5; for HTTP CONNECT the proxy always does.
        "remote_dns": scheme in ("socks5h", "http", "https"),
    }, None


def describe_route(route):
    """A route as text, safe to print."""
    return f"{route['label']} ({redact_url(route['url'])})"



def routes_from_config(cfg):
    """Every configured route, in order, skipping malformed entries.

    A bad entry is dropped rather than raising: one typo in ``config.json``
    should not stop the wrapper from launching agy at all.
    """
    routes = []
    for spec in cfg.get("egress_routes") or []:
        try:
            url, label = resolve_spec(spec)
        except ValueError:
            continue
        route, err = parse_route(url, label=label)
        if route is not None:
            routes.append(route)
    return routes


def active_route(cfg, agy_path=None):
    """The route the wrapper should use right now, or None.

    Deliberately does *not* probe: ``runner`` calls this on every launch and a
    live probe is a model round-trip.  Measurement happens in ``egress test``,
    which persists the winner here.
    """
    if not cfg.get("egress_enabled"):
        return None

    wanted = cfg.get("egress_active")
    routes = routes_from_config(cfg)
    if not routes:
        return None

    if wanted:
        for route in routes:
            if wanted in (route["label"], route["url"]):
                return route
        # The persisted winner is gone from the config.  Falling back to the
        # first route beats failing closed: a wrong-but-working exit is better
        # than a guaranteed region 400.

    return routes[0]


# --------------------------------------------------------------------------
# Minimal SOCKS5 client (stdlib only)
# --------------------------------------------------------------------------

def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EgressError("proxy closed the connection mid-handshake")
        buf += chunk
    return buf


def socks5_tunnel(route, target_host, target_port, timeout=DEFAULT_TIMEOUT):
    """Open a CONNECT to *target_host:target_port* through a SOCKS5 proxy.

    RFC 1928, CONNECT only, with RFC 1929 username/password when the proxy asks
    for it and credentials are configured.  The target is always sent as a
    domain name (ATYP 0x03) so the proxy resolves it - that is the ``socks5h``
    behaviour, and the one that survives a lying local resolver.

    Returns a connected socket the caller owns and must close.
    """
    sock = socket.create_connection((route["host"], route["port"]), timeout)
    sock.settimeout(timeout)
    try:
        user = route.get("user")
        password = route.get("password") or ""
        methods = b"\x00" + (b"\x02" if user else b"")
        sock.sendall(b"\x05" + bytes([len(methods)]) + methods)

        greeting = _recv_exact(sock, 2)
        if greeting[0] != 0x05:
            raise EgressError(
                f"{route['host']}:{route['port']} is not a SOCKS5 proxy "
                f"(version byte {greeting[0]:#04x})"
            )

        method = greeting[1]
        if method == 0xFF:
            if not user:
                # The common case: we offered NO AUTH only and the proxy wants
                # credentials.  Saying that beats reporting a protocol failure
                # the user cannot act on.
                raise EgressError(
                    "proxy refused the no-auth handshake - it wants credentials. "
                    "Put them in the URL as scheme://user:pass@host:port"
                )
            raise EgressError("proxy rejected every authentication method we offered")
        if method == 0x02:
            if not user:
                raise EgressError(
                    "proxy requires username/password authentication and none is "
                    "configured; put them in the URL as scheme://user:pass@host:port"
                )
            cred = b"\x01" + bytes([len(user)]) + user.encode("utf-8")
            cred += bytes([len(password)]) + password.encode("utf-8")
            sock.sendall(cred)
            reply = _recv_exact(sock, 2)
            if reply[1] != 0x00:
                raise EgressError("proxy refused the supplied username/password")
        elif method != 0x00:
            raise EgressError(f"unsupported SOCKS5 authentication method {method:#04x}")

        name = target_host.encode("idna")
        if len(name) > 255:
            raise EgressError(f"target hostname too long for SOCKS5: {target_host!r}")
        sock.sendall(
            b"\x05\x01\x00\x03" + bytes([len(name)]) + name + struct.pack("!H", target_port)
        )

        head = _recv_exact(sock, 4)
        code = head[1]
        if code != 0x00:
            raise EgressError(
                f"SOCKS5 CONNECT to {target_host}:{target_port} failed: "
                f"{_SOCKS5_REPLIES.get(code, 'unknown error')} (code {code:#04x})"
            )

        # Drain the bound address; we have no use for it but the stream must
        # stay aligned before the caller starts speaking TLS.
        atyp = head[3]
        if atyp == 0x01:
            _recv_exact(sock, 4)
        elif atyp == 0x03:
            _recv_exact(sock, _recv_exact(sock, 1)[0])
        elif atyp == 0x04:
            _recv_exact(sock, 16)
        else:
            raise EgressError(f"SOCKS5 reply carried an unknown address type {atyp:#04x}")
        _recv_exact(sock, 2)
        return sock
    except Exception:
        try:
            sock.close()
        except OSError:
            pass
        raise


def _dechunk(body):
    """Decode an HTTP/1.1 chunked body.  Returns it untouched if not chunked."""
    out = []
    rest = body
    while True:
        head, sep, rest = rest.partition(b"\r\n")
        if not sep:
            # No CRLF at all: this was never a chunked stream, so the caller
            # mis-detected the encoding.  Hand back what we were given rather
            # than an empty body.
            out.append(head)
            break
        try:
            size = int(head.split(b";")[0].strip() or b"0", 16)
        except ValueError:
            return body
        if size == 0:
            break
        out.append(rest[:size])
        rest = rest[size + 2:]
    return b"".join(out)


def _get_over_socket(sock, host, path, use_tls, timeout):
    """Speak one HTTP/1.1 GET over an already-established socket."""
    if use_tls:
        context = ssl.create_default_context()
        sock = context.wrap_socket(sock, server_hostname=host)
    request = (
        "GET {} HTTP/1.1\r\n"
        "Host: {}\r\n"
        "User-Agent: antigravity-unlocker-egress/1.0\r\n"
        "Accept: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).format(path, host)
    sock.sendall(request.encode("ascii"))

    chunks = []
    while True:
        try:
            block = sock.recv(65536)
        except (socket.timeout, ssl.SSLError, OSError):
            break
        if not block:
            break
        chunks.append(block)
    try:
        sock.close()
    except OSError:
        pass

    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    if b"transfer-encoding: chunked" in head.lower():
        body = _dechunk(body)
    return body.decode("utf-8", "replace")


def _fetch_json(route, url, timeout=DEFAULT_TIMEOUT):
    """GET *url* as JSON through *route*.

    HTTP(S) proxies go via urllib, which understands them.  SOCKS5 goes via the
    hand-rolled tunnel, because urllib does not speak SOCKS at all.
    """
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query

    if route["scheme"] in ("socks5", "socks5h"):
        port = parts.port or (443 if parts.scheme == "https" else 80)
        sock = socks5_tunnel(route, host, port, timeout=timeout)
        try:
            text = _get_over_socket(sock, host, path, parts.scheme == "https", timeout)
        finally:
            try:
                sock.close()
            except OSError:
                pass
    else:
        handler = urllib.request.ProxyHandler({
            "http": route["url"],
            "https": route["url"],
        })
        opener = urllib.request.build_opener(handler)
        request = urllib.request.Request(url, headers={
            "User-Agent": "antigravity-unlocker-egress/1.0",
            "Accept": "application/json",
        })
        with opener.open(request, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")

    data = json.loads(text)
    if not isinstance(data, dict):
        raise EgressError(f"{url} did not return a JSON object")
    return data


def tcp_reachable(route, timeout=DEFAULT_TIMEOUT):
    """True when something answers TCP on the proxy's own address.

    Cheap and weak: an open port says nothing about whether the far side can
    reach Google.  It exists only to fail fast on a daemon that is not running.
    """
    try:
        with socket.create_connection((route["host"], route["port"]), timeout):
            return True
    except OSError:
        return False


def route_egress_geo(route, timeout=DEFAULT_TIMEOUT):
    """The geo dict as seen from the far end of *route*, or None.

    Answers "which country will Google see".  None means we could not tell,
    which is not the same as "blocked" - callers must not treat it as a verdict.
    """
    for url in GEO_URLS:
        try:
            data = _fetch_json(route, url, timeout=timeout)
        except Exception:
            continue
        if data.get("country") or data.get("countryCode"):
            data["_probe_url"] = url
            return data
    return None


def geo_country(geo):
    """Two-letter country from a geo dict, upper-cased, or None."""
    if not geo:
        return None
    code = geo.get("country") or geo.get("countryCode")
    return str(code).upper() if code else None


# --------------------------------------------------------------------------
# Talking to agy
# --------------------------------------------------------------------------

_PROXY_VAR_CACHE = {}


def proxy_var_is_isolated(agy_path):
    """True when the opt-in ``proxy_var_isolation`` rename is applied.

    That pattern rewrites the lower-case ``https_proxy`` literal to
    ``AG_LS_PROXY``.  Whether it is present changes what the wrapper must set,
    and the two are not interchangeable: with the rename in place, exporting
    ``https_proxy`` does nothing at all.

    Scanning a ~220 MB binary is not free, so the answer is cached against the
    file's size and mtime - both of which change when agy self-updates.
    """
    if not agy_path:
        return False
    try:
        stat = os.stat(agy_path)
    except OSError:
        return False

    key = (agy_path, stat.st_size, stat.st_mtime)
    cached = _PROXY_VAR_CACHE.get(agy_path)
    if cached and cached[0] == key:
        return cached[1]

    isolated = False
    try:
        with open(agy_path, "rb") as handle:
            with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as region:
                isolated = region.find(b"AG_LS_PROXY") != -1
    except (OSError, ValueError):
        isolated = False

    _PROXY_VAR_CACHE[agy_path] = (key, isolated)
    return isolated


# Every proxy variable Go's transport may consult.  They are all removed before
# ours is set, because Go prefers the upper-case spellings: leaving an ambient
# HTTPS_PROXY in place would let it silently win over the route we were asked to
# use.  This also keeps the change process-local - nothing here touches the
# user's shell, and git, curl and package managers are unaffected.
_AMBIENT_PROXY_VARS = (
    "http_proxy", "HTTP_PROXY",
    "https_proxy", "HTTPS_PROXY",
    "all_proxy", "ALL_PROXY",
)


def build_child_env(route, base=None, agy_path=None):
    """Environment that makes agy use *route* and nothing else."""
    env = dict(os.environ if base is None else base)
    for name in _AMBIENT_PROXY_VARS:
        env.pop(name, None)

    if proxy_var_is_isolated(agy_path):
        env["AG_LS_PROXY"] = route["url"]
        env.pop("AG_LS_PROXY_DISABLED", None)
    else:
        env["https_proxy"] = route["url"]
        env["HTTPS_PROXY"] = route["url"]
    return env


def classify_agy(output, returncode):
    """Map agy's output onto one of the ``STATUS_*`` outcomes.

    Order matters and is not arbitrary, and the two nearest-miss cases are why.
    agy reports *any* failed eligibility HTTP request under the heading
    "Eligibility check failed", so the gate phrase alone cannot mean "the gate
    is active":

    * a proxy that cannot be reached gives
      ``Eligibility check failed: Post "...loadCodeAssist": proxyconnect tcp: dial
      tcp 127.0.0.1:9: connect: connection refused``;
    * a socket that dies mid-request gives
      ``Eligibility check failed: failed to get profile picture: Get
      "https://lh3.googleusercontent.com/...": EOF``.

    Both are transport problems, and both used to be reported as an unpatched
    binary - sending the user to re-patch an install that was already fine.  So
    the proxy markers are tested first, then the transport markers, and only
    what remains is the gate.
    """
    text = (output or "").strip()
    lowered = text.lower()

    if not text and returncode != 0:
        return STATUS_UNKNOWN, "agy produced no output"

    def _first(markers):
        for marker in markers:
            if marker in lowered:
                return marker
        return None

    if _first(PROXY_UNREACHABLE_MARKERS):
        return STATUS_PROXY_UNREACHABLE, "agy could not reach the proxy"
    if _first(PROXY_AUTH_MARKERS):
        return STATUS_PROXY_AUTH, "the proxy demanded credentials agy did not have"
    if _first(REGION_MARKERS):
        return STATUS_REGION_BLOCKED, "Google refused this exit's region (server-side gate)"
    if _first(TRANSIENT_MARKERS):
        return STATUS_TRANSIENT, "the request was dropped in transit; nothing was decided"
    if _first(GATE_MARKERS):
        return STATUS_GATE, "the client-side eligibility gate is still active"
    if _first(CREDENTIAL_MARKERS):
        return STATUS_CREDENTIALS, "route works; agy is not signed in"

    if returncode == 0 and text:
        return STATUS_OK, "agy completed a real prompt through this route"

    return STATUS_UNKNOWN, f"agy exited {returncode}"


def live_probe(agy_path, route, timeout=PROBE_TIMEOUT, model=None):
    """Run one real prompt through *route* and report what actually happened.

    This is the only trustworthy test.  Everything cheaper - an open port, a
    completed TLS handshake, an HTTP 200 from the proxy itself - was measured on
    this project's own 1.4.x SNI route to be fully compatible with CloudCode
    still being unreachable, which is why that layer was deleted in 1.5.0.  It
    costs one model call, so callers use it sparingly.
    """
    if not agy_path or not os.path.exists(agy_path):
        return {"route": route, "status": STATUS_UNKNOWN, "detail": "no agy binary to test"}

    cmd = [agy_path, "-p=" + PROBE_PROMPT, "--print-timeout", "%ds" % int(timeout)]
    if model:
        cmd += ["--model", model]

    env = build_child_env(route, agy_path=agy_path)
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env,
            timeout=timeout + 30, check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "route": route, "status": STATUS_TIMEOUT,
            "detail": "agy did not answer within %ds" % int(timeout),
        }
    except Exception as e:
        return {"route": route, "status": STATUS_UNKNOWN, "detail": "could not run agy: %s" % e}

    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    status, detail = classify_agy(output, proc.returncode)
    return {
        "route": route,
        "status": status,
        "detail": detail,
        "output": output[:400],
        "returncode": proc.returncode,
    }


def select_route(agy_path, routes, timeout=PROBE_TIMEOUT, model=None,
                 preflight=True, on_progress=None):
    """Measure *routes* in order and return ``(winner, results)``.

    Cheapest evidence first: an unreachable TCP port disqualifies a route
    without spending a model call on it.  Then one live probe each, stopping at
    the first route a model actually answered through.

    A region-blocked route is recorded and passed over rather than retried -
    the exit's country is a property of the route, not of the moment.  A route
    that times out is *not* treated as blocked: that would shelve a working exit
    on one slow call.
    """
    results = []
    winner = None

    for route in routes:
        if preflight and not tcp_reachable(route, timeout=min(timeout, DEFAULT_TIMEOUT)):
            results.append({
                "route": route, "status": STATUS_PROXY_UNREACHABLE,
                "detail": "nothing is listening on %s:%d" % (route["host"], route["port"]),
            })
            if on_progress:
                on_progress(route, STATUS_PROXY_UNREACHABLE, "not listening")
            continue

        result = live_probe(agy_path, route, timeout=timeout, model=model)
        results.append(result)
        if on_progress:
            on_progress(route, result["status"], result["detail"])

        if result["status"] == STATUS_OK:
            winner = route
            break
        # Not signed in still proves the route reached Google's API, which is
        # the question being asked.
        if result["status"] == STATUS_CREDENTIALS:
            winner = route
            break

    return winner, results


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

_STATUS_TEXT = {
    STATUS_OK: "works",
    STATUS_REGION_BLOCKED: "REGION-BLOCKED",
    STATUS_PROXY_UNREACHABLE: "unreachable",
    STATUS_PROXY_AUTH: "needs credentials",
    STATUS_GATE: "eligibility gate",
    STATUS_CREDENTIALS: "works (not signed in)",
    STATUS_TIMEOUT: "timed out",
    STATUS_TRANSIENT: "dropped in transit (retry)",
    STATUS_UNKNOWN: "inconclusive",
}


def status_text(status):
    return _STATUS_TEXT.get(status, status)


def format_results(results):
    """Render probe results as aligned text lines."""
    lines = []
    for result in results:
        route = result.get("route") or {}
        label = route.get("label", "?")
        url = redact_url(route.get("url", "?"))
        lines.append(
            "%-22s %-16s %s\n%s%s" % (
                label[:22], status_text(result.get("status")), url,
                " " * 24, result.get("detail", ""),
            )
        )
    return "\n".join(lines)
