"""
Layered diagnostics for an Antigravity install.

Antigravity failing to unlock has several independent causes - an unpatched
binary, a stale hosts pin overriding a good route, an egress IP in an
unsupported region, no guardian to re-patch after a self-update - and the error
Antigravity shows is the same in every case.  This module checks each layer and
reports which one is actually broken, with the command that fixes it.

Every probe is read-only and time-bounded; nothing here modifies the system.
"""

import json
import os
import platform
import socket
import ssl
import subprocess
import http.client
import ipaddress
import urllib.error
import urllib.parse
import urllib.request

from antigravity_unlock.config import load_config
from antigravity_unlock.discovery import find_agy_binaries, get_primary_agy
from antigravity_unlock.egress import (
    BLOCKED_COUNTRIES,
    GEO_URLS,
    STATUS_CREDENTIALS,
    STATUS_GATE,
    STATUS_OK,
    STATUS_PROXY_UNREACHABLE,
    STATUS_REGION_BLOCKED,
    STATUS_TRANSIENT,
    active_route,
    build_child_env,
    classify_agy,
    describe_route,
    geo_country,
    route_egress_geo,
    routes_from_config,
    tcp_reachable,
)
from antigravity_unlock.model import (
    ModelSettingsError,
    default_model,
    get_settings_path as get_agy_settings_path,
    is_gemini_model,
)
from antigravity_unlock.dnspin import (
    parse_hosts_pin,
    pin_ips,
    start_proxy as start_dnspin_proxy,
)
from antigravity_unlock.patcher import (
    STATE_FOREIGN,
    STATE_PATCHED,
    classify_binary,
    get_backup_info,
)
from antigravity_unlock.pinner import get_agy_version, get_pinned_backup_path

# Layer verdicts, ordered so the worst one in a layer wins.
OK = "ok"
WARN = "warn"
FAIL = "fail"

_RANK = {OK: 0, WARN: 1, FAIL: 2}

# BLOCKED_COUNTRIES and GEO_URLS live in egress.py so that the doctor's
# inference and the routing that acts on it can never disagree about which
# regions are blocked.  See that module for why a client-side patch cannot clear
# the server-side source-IP gate.

# Clash/mihomo fake-ip range.  A local resolver answer from here means a VPN/TUN
# is doing its own DNS, which is expected and healthy - not a stale hosts pin.
FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/16")

CLOUDCODE_HOST = "cloudcode-pa.googleapis.com"
CLOUDCODE_PROBE_PATH = "/v1internal:loadCodeAssist"

DEFAULT_TIMEOUT = 10.0



def _check(name, verdict, summary, fix=None):
    return {"name": name, "verdict": verdict, "summary": summary, "fix": fix}


# --------------------------------------------------------------------------
# Layer 1: the binary and its patch state
# --------------------------------------------------------------------------

def check_binary(timeout=20.0):
    binaries = find_agy_binaries()
    if not binaries:
        return [_check("binary", FAIL, "no agy binary found on this system",
                       "install Antigravity CLI, then re-run doctor")]

    checks = []
    for path in binaries:
        version = get_agy_version(path) or "unknown"
        try:
            state, detail = classify_binary(path)
        except OSError as e:
            checks.append(_check(f"binary {path}", FAIL, f"cannot read: {e}"))
            continue

        if state == STATE_PATCHED:
            checks.append(_check(f"binary {path}", OK, f"agy {version} - patched ({detail})"))
        elif state == STATE_FOREIGN:
            checks.append(_check(
                f"binary {path}", FAIL,
                f"agy {version} - NOT RECOGNISED ({detail}). The eligibility literal "
                f"this tool renames is absent, so this is either not agy or a build "
                f"with a new gate.",
                "update antigravity-cli-unlocker; if it is already current, the patch "
                "needs a new signature for this build",
            ))
        else:
            checks.append(_check(
                f"binary {path}", FAIL, f"agy {version} - UNPATCHED ({detail})",
                "antigravity-unlock patch",
            ))

        info = get_backup_info(path)
        if not info["exists"]:
            if state == STATE_PATCHED:
                checks.append(_check(
                    f"backup {path}", WARN,
                    "no pristine backup exists and the installed agy is already patched, "
                    "so 'restore' cannot revert it. 'unpatch' still can - it reverses the "
                    "renames in place without needing a backup.",
                    "antigravity-unlock unpatch",
                ))
            else:
                checks.append(_check(
                    f"backup {path}", WARN,
                    "no pre-patch backup; 'restore' will not be able to revert",
                    "antigravity-unlock patch  (creates the backup on first patch)",
                ))
        elif info["stale"]:
            checks.append(_check(
                f"backup {path}", FAIL,
                f"the stored backup is {info['backup_size']} bytes but the installed agy "
                f"is {info['installed_size']} - it belongs to an older build, so "
                f"'restore' would silently DOWNGRADE agy. Use 'unpatch' instead, which "
                f"reverses the renames in place.",
                "antigravity-unlock unpatch   (then 'patch' refreshes the backup)",
            ))
    return checks


# --------------------------------------------------------------------------
# Layer 2: configuration / strategy
# --------------------------------------------------------------------------

def check_config(installed_version=None):
    cfg = load_config()
    strategy = cfg.get("strategy")
    checks = []

    if strategy == "pin":
        pinned = cfg.get("pinned_version") or "?"
        if installed_version and pinned != "unknown" and _older(pinned, installed_version):
            checks.append(_check(
                "strategy", FAIL,
                f"strategy=pin would replace installed agy {installed_version} with the "
                f"older pinned {pinned}",
                "antigravity-unlock pin strategy in_place",
            ))
        else:
            checks.append(_check(
                "strategy", WARN,
                f"strategy=pin ({pinned}) fights agy's self-updater; every update has to "
                f"be rolled back",
                "antigravity-unlock pin strategy in_place",
            ))
    else:
        checks.append(_check("strategy", OK, f"strategy={strategy}"))

    if cfg.get("allow_pin_fallback"):
        checks.append(_check(
            "pin fallback", WARN,
            "allow_pin_fallback=true: an unpatchable new build will be downgraded to the "
            "pinned binary",
        ))

    guardian_wanted = bool(cfg.get("auto_patch", True))
    if guardian_wanted:
        running = _guardian_running()
        unit = _guardian_unit_problem()
        if unit:
            # A unit that exists but cannot start is worse than no unit: it looks
            # installed, so it is the one failure a check that only asks "is it
            # enabled?" reports as healthy.  On this machine the guardian was
            # crash-looping on `No module named antigravity_unlock` every 15s
            # while the binary underneath it had been re-patched by hand.
            checks.append(_check(
                "guardian", FAIL,
                f"guardian is installed but fails to start: {unit}. The patch will be "
                f"wiped by the next agy self-update and nothing will put it back",
                "antigravity-unlock autostart remove && antigravity-unlock autostart install",
            ))
        elif not running and not _autostart_installed():
            checks.append(_check(
                "guardian", WARN,
                "agy self-updates and wipes the patch (this is what broke the install on "
                "2026-09-20); no guardian is running and none is set to autostart",
                "antigravity-unlock autostart install",
            ))
        elif not running:
            checks.append(_check(
                "guardian", WARN,
                "guardian is set to autostart but is not running now; the patch will not "
                "be re-applied until next login",
                "antigravity-unlock guardian   (or log out and back in)",
            ))
        else:
            checks.append(_check("guardian", OK, "guardian running"))
    return checks


def _in_fake_ip_range(addr):
    """True if *addr* is a Clash/mihomo fake-ip (198.18.0.0/16 by default)."""
    try:
        return ipaddress.ip_address(addr) in FAKE_IP_NETWORK
    except ValueError:
        return False


def _older(a, b):
    """True only when both versions parse and *a* is provably older than *b*.

    An unparseable version yields False rather than being treated as 0: claiming
    a downgrade we cannot actually establish would push the user into changing a
    working strategy.
    """
    def t(v):
        try:
            parts = str(v).split(".")
            return tuple(int(x) for x in parts) if parts and all(p.isdigit() for p in parts) else None
        except (ValueError, AttributeError):
            return None
    ta, tb = t(a), t(b)
    if ta is None or tb is None:
        return False
    return ta < tb


def _guardian_running():
    if platform.system() == "Windows":
        return False
    try:
        out = subprocess.run(
            ["pgrep", "-af", "antigravity_unlock.*guardian|antigravity-unlock guardian"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except Exception:
        return False
    me = str(os.getpid())
    return any(line.strip() and not line.startswith(me) for line in out.splitlines())


def _autostart_installed():
    """True when a guardian autostart entry exists.

    The paths come from ``autostart`` rather than being spelled out here.  They
    used to be hardcoded as ``antigravity-unlocker.service`` /
    ``com.antigravity.unlocker.plist`` while ``autostart`` installs
    ``antigravity-unlocker-guardian.service`` / ``com.antigravity.unlocker.guardian.plist``,
    so this function answered False on a machine with the guardian installed -
    and the layer above then told the user to install something already
    installed.
    """
    from antigravity_unlock import autostart

    candidates = [
        autostart._systemd_unit_path(),
        autostart._launch_agent_path(),
        os.path.join(
            os.path.expanduser("~"), ".config", "autostart",
            "antigravity-unlocker.desktop",
        ),
    ]
    if platform.system() == "Windows":
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", autostart.TASK_NAME],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.returncode == 0
    return any(os.path.exists(p) for p in candidates)


def _guardian_unit_problem():
    """Why an installed guardian cannot run, or None.

    Delegates to ``autostart`` so that ``doctor`` and ``install_autostart`` can
    never disagree about whether the unit is healthy - the disagreement is what
    let this report "none is set to autostart" while the unit was crash-looping
    15s away in the background.
    """
    from antigravity_unlock.autostart import guardian_unit_problem

    return guardian_unit_problem()


# --------------------------------------------------------------------------
# Layer 3: leftover /etc/hosts pins
# --------------------------------------------------------------------------

def check_hosts():
    """Report CloudCode entries in /etc/hosts.

    Two different things can be there:

    * the intentional ``dnspin`` block (``dnspin pin-hosts``), which is a live
      pin to public relays and is what makes a bare ``agy`` work with no
      wrapper;
    * leftovers from versions <= 1.4.x, which point at a dead SNI endpoint and
      must be removed.

    Treating both as "stale pin" would tell the user to delete the one thing
    that is currently making Gemini work, so they are separated.
    """
    if platform.system() == "Windows":
        return [_check("hosts pin", OK, "not applicable on Windows")]

    from antigravity_unlock.hosts_cleanup import find_pins
    from antigravity_unlock.dnspin import (
        HOSTS_MARKER_BEGIN,
        HOSTS_MARKER_END,
        parse_hosts_pin,
        probe_relay,
    )

    try:
        pins = find_pins(exclude_blocks=((HOSTS_MARKER_BEGIN, HOSTS_MARKER_END),))
    except Exception as e:
        return [_check("hosts pin", WARN, f"could not read /etc/hosts: {e}")]

    checks = []
    dnspin_pin = parse_hosts_pin()
    if dnspin_pin:
        dead = []
        for host, ips in dnspin_pin.items():
            if not any(probe_relay(host, ip, timeout=3.0) is not None for ip in ips[:2]):
                dead.append(host)
        if dead:
            checks.append(_check(
                "hosts pin", WARN,
                f"the dnspin /etc/hosts pin has dead relay(s): {', '.join(dead)}. "
                f"A bare agy will fail until the pin is refreshed.",
                "sudo antigravity-unlock dnspin pin-hosts",
            ))
        else:
            summary = ", ".join(f"{h.split('.')[0]}={ips[0]}" for h, ips in dnspin_pin.items() if ips)
            checks.append(_check(
                "hosts pin", OK,
                f"dnspin /etc/hosts pin is live: {summary}. This is what makes a "
                f"bare agy use the relays.",
            ))

    if pins:
        listing = "; ".join(line for _, line, _ in pins[:3])
        unmarked = sum(1 for _, _, marked in pins if not marked)
        detail = f" ({unmarked} unmarked, written by an older release)" if unmarked else ""
        checks.append(_check(
            "hosts pin", FAIL,
            f"{len(pins)} old CloudCode pin line(s) left in /etc/hosts{detail}: {listing}. "
            f"These point at the removed SNI endpoint and override the real egress route.",
            "sudo antigravity-unlock setup remove",
        ))

    if not checks:
        checks.append(_check("hosts pin", OK, "no CloudCode pin - agy resolves it normally"))
    return checks



# --------------------------------------------------------------------------
# Layer 4: egress region
# --------------------------------------------------------------------------

def check_egress(timeout=DEFAULT_TIMEOUT):
    geo = _fetch_geo(timeout=timeout)
    if geo is None:
        return [_check(
            "egress", WARN,
            "could not determine the public egress IP (no network, or the geo services "
            "are unreachable)",
        ), ], None

    country = (geo.get("country") or geo.get("countryCode") or "??").upper()
    ip = geo.get("ip") or geo.get("query") or "?"
    org = geo.get("org") or geo.get("isp") or ""
    label = f"egress {ip} ({country}{', ' + org if org else ''})"

    if country in BLOCKED_COUNTRIES:
        return [_check(
            "egress", FAIL,
            f"{label} - Antigravity requires an exit from {country}. There are TWO "
            f"independent gates and the binary patch clears only the first: "
            f"(1) the account-level client gate over the server's 'ineligible' "
            f"protobuf field - removed by the patch; and (2) a server-side check on "
            f"the request's source IP, answering 'FAILED_PRECONDITION (400): User "
            f"location is not supported for the API use'. No client-side patch can "
            f"change the source IP Google observes, so gate (2) needs an exit "
            f"outside " + ", ".join(sorted(BLOCKED_COUNTRIES)) + ". Gate (2) was "
            f"measured on the Gemini family only: claude-* and gpt-oss-* answered "
            f"from a Russian IP with no exit at all.",
            "for Gemini: route agy through a VPN/TUN/proxy exit in a supported "
            "region, then re-run doctor. For everything else the cheaper fix is "
            "'antigravity-unlock model ru', which switches agy's default away from "
            "Gemini and needs no exit",
        )], geo
    return [_check("egress", OK, f"{label} - supported region")], geo


def _fetch_geo(timeout=DEFAULT_TIMEOUT):
    for url in GEO_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            if isinstance(data, dict) and (data.get("country") or data.get("countryCode")):
                return data
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------
# Layer 4b: configured exits
# --------------------------------------------------------------------------

def check_egress_routes(cfg=None, timeout=DEFAULT_TIMEOUT, direct_geo=None):
    """Report the configured exits, and whether one is needed at all.

    Deliberately cheap: reachability for every route, and an exit-country lookup
    for the selected one only.  The authoritative "does a model answer" test is
    the functional layer, and paying for it more than once per run would be
    waste.

    The interesting failure this catches is an exit that is up and reachable but
    still in a blocked country - a VPN whose nearest node is home, or WARP
    landing on a regional PoP.  Everything looks green until the first request.
    """
    cfg = cfg if cfg is not None else load_config()
    routes = routes_from_config(cfg)
    active = active_route(cfg)
    checks = []

    if not routes:
        country = geo_country(direct_geo)
        if country and country in BLOCKED_COUNTRIES:
            checks.append(_check(
                "exit", FAIL,
                f"direct egress is in {country} and no exit is configured, so every "
                f"Gemini call will be refused server-side however well the binary is "
                f"patched.  Non-Gemini models (claude-*, gpt-oss-*) were measured "
                f"answering from the same kind of egress with no exit at all",
                "no exit needed for Claude/GPT-OSS: antigravity-unlock model ru.  "
                "For Gemini: antigravity-unlock egress add warp   (then: egress test)",
            ))
        else:
            checks.append(_check(
                "exit", OK,
                "no exit configured" + (f", and none needed (direct egress is {country})"
                                       if country else ""),
            ))
        return checks

    if not cfg.get("egress_enabled"):
        checks.append(_check(
            "exit", WARN,
            f"{len(routes)} route(s) configured but egress routing is disabled, so agy "
            f"is still going out direct",
            "antigravity-unlock egress enable",
        ))

    for route in routes:
        is_active = active is not None and route["label"] == active["label"]
        tag = " (selected)" if is_active else ""
        if not tcp_reachable(route, timeout=timeout):
            checks.append(_check(
                f"exit {route['label']}", FAIL if is_active else WARN,
                f"{describe_route(route)}{tag} - nothing is listening on "
                f"{route['host']}:{route['port']}",
                "start the proxy/VPN, or drop the route: "
                f"antigravity-unlock egress remove {route['label']}",
            ))
            continue

        if not is_active:
            checks.append(_check(
                f"exit {route['label']}", OK,
                f"{describe_route(route)} - reachable, not measured "
                f"(only the selected route is geo-probed)",
            ))
            continue

        geo = route_egress_geo(route, timeout=timeout)
        country = geo_country(geo)
        if country is None:
            checks.append(_check(
                f"exit {route['label']}", WARN,
                f"{describe_route(route)}{tag} - reachable, but the geo services did not "
                f"answer through it, so the exit country is unknown",
            ))
        elif country in BLOCKED_COUNTRIES:
            checks.append(_check(
                f"exit {route['label']}", FAIL,
                f"{describe_route(route)}{tag} - reachable, but it exits in {country}, "
                f"which is blocked. A proxy that is up is not a proxy that helps.",
                "use an exit in a supported region, then: antigravity-unlock egress test",
            ))
        else:
            where = geo.get("city") or geo.get("region") or ""
            checks.append(_check(
                f"exit {route['label']}", OK,
                f"{describe_route(route)}{tag} - exits in {country}"
                + (f" ({where})" if where else "") + ", a supported region",
            ))

    if cfg.get("egress_enabled") and active is None:
        checks.append(_check(
            "exit", WARN,
            "routing is enabled and routes exist, but none is selected; the wrapper "
            "falls back to the first one and to direct if that is unusable",
            "antigravity-unlock egress test",
        ))
    return checks


# --------------------------------------------------------------------------
# Layer 5: CloudCode reachability
# --------------------------------------------------------------------------

class _SniPinnedConnection(http.client.HTTPSConnection):
    """HTTPS connection to a chosen IP while presenting the real hostname as SNI.

    ``urllib`` has no equivalent of ``curl --resolve``, and this probe must reach
    Google's real address rather than whatever ``/etc/hosts`` says, so the
    socket is built by hand.  Certificate validation stays on and is checked
    against ``host``, not the IP.
    """

    def __init__(self, host, ip, timeout=DEFAULT_TIMEOUT, **kwargs):
        super().__init__(host, timeout=timeout, **kwargs)
        self._pinned_ip = ip

    def connect(self):
        sock = socket.create_connection((self._pinned_ip, self.port or 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise


DOH_RESOLVERS = (
    ("https://dns.google/resolve", "google"),
    ("https://cloudflare-dns.com/dns-query", "cloudflare"),
)


def resolve_public(name, rtype="A", timeout=DEFAULT_TIMEOUT):
    """Resolve *name* over DoH, bypassing /etc/hosts and any local stub resolver.

    Returns a list of address strings, possibly empty.
    """
    for base, provider in DOH_RESOLVERS:
        url = f"{base}?name={urllib.parse.quote(name)}&type={rtype}"
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/dns-json",
                "User-Agent": "antigravity-unlocker-doctor/1.0",
            })
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            answers = [a.get("data") for a in data.get("Answer", []) if a.get("data")]
            if rtype == "A":
                answers = [a for a in answers if ":" not in a]
            if answers:
                return answers
        except Exception:
            continue
    return []


def check_endpoint(timeout=DEFAULT_TIMEOUT):
    """POST to CloudCode unauthenticated and read *why* it refused.

    The probe deliberately targets Google's **real** address, resolved over DoH,
    rather than the name as ``/etc/hosts`` defines it.  The question this layer
    answers is "does Google accept requests from our egress region", and a local
    pin answers a different question (that is the hosts layer's job).  Probing
    through a dead pin produced a false FAIL on machines where agy itself worked,
    because agy's traffic was leaving via a VPN/TUN whose DNS overrides
    ``/etc/hosts`` entirely.

    The status code then distinguishes the two failure modes that look identical
    in the CLI: ``401 CREDENTIALS_MISSING`` means the route is accepted and only
    auth is missing (expected - we send no token), while a 400/403 carrying a
    location or eligibility reason means Google is refusing the request's origin.
    """
    checks = []

    try:
        local_ip = socket.gethostbyname(CLOUDCODE_HOST)
    except OSError:
        local_ip = None

    real_ips = resolve_public(CLOUDCODE_HOST, timeout=timeout)
    if not real_ips:
        return [_check(
            "endpoint", WARN,
            f"could not resolve {CLOUDCODE_HOST} over DoH - cannot tell whether Google "
            f"accepts this egress region",
            "check outbound DNS/HTTPS, then re-run doctor",
        )]

    if local_ip and local_ip not in real_ips:
        dnspin_pin = parse_hosts_pin().get(CLOUDCODE_HOST) or []
        if local_ip in dnspin_pin:
            checks.append(_check(
                "endpoint routing", OK,
                f"the local resolver returns {local_ip} for {CLOUDCODE_HOST} because of "
                f"the intentional dnspin /etc/hosts pin. The unauthenticated probe below "
                f"still targets Google's real address ({', '.join(real_ips[:2])}), so it "
                f"measures the egress region rather than the pin. Expected and healthy.",
            ))
        elif _in_fake_ip_range(local_ip):
            checks.append(_check(
                "endpoint routing", OK,
                f"the local resolver returns {local_ip} for {CLOUDCODE_HOST} - that is a "
                f"Clash/mihomo fake-ip, so a VPN/TUN is doing its own DNS and will route "
                f"the connection to the real Google address ({', '.join(real_ips[:2])}) "
                f"through its tunnel. Expected and healthy.",
            ))
        else:
            checks.append(_check(
                "endpoint routing", FAIL,
                f"the system resolver returns {local_ip} for {CLOUDCODE_HOST} while "
                f"Google's real addresses are {', '.join(real_ips[:3])}. Anything that "
                f"honours /etc/hosts is being sent to {local_ip} instead of Google.",
                "sudo antigravity-unlock setup remove",
            ))

    target = real_ips[0]
    url_path = CLOUDCODE_PROBE_PATH
    body = json.dumps({}).encode()

    try:
        conn = _SniPinnedConnection(CLOUDCODE_HOST, target, timeout=timeout)
        conn.request("POST", url_path, body=body, headers={
            "Content-Type": "application/json",
            "User-Agent": "antigravity-unlocker-doctor/1.0",
        })
        resp = conn.getresponse()
        status = resp.status
        payload = resp.read().decode("utf-8", "replace")
        conn.close()
    except ssl.SSLError as e:
        return checks + [_check(
            "endpoint", FAIL,
            f"TLS to the real {CLOUDCODE_HOST} ({target}) failed: {e.reason or e}",
            "check the egress route / VPN, then re-run doctor",
        )]
    except Exception as e:
        return checks + [_check(
            "endpoint", FAIL,
            f"the real {CLOUDCODE_HOST} ({target}) is unreachable: {e}",
            "check the egress route / VPN, then re-run doctor",
        )]

    lowered = payload.lower()
    geo_markers = ("location", "region", "not available in your", "failed_precondition")

    if status == 401 and "credentials_missing" in lowered:
        checks.append(_check(
            "endpoint", OK,
            f"the real {CLOUDCODE_HOST} ({target}) is reachable and answered 401 "
            f"CREDENTIALS_MISSING. Note this proves reachability only, not that the "
            f"egress region is accepted - Google validates credentials before geography, "
            f"so an unauthenticated probe cannot get far enough to be geo-rejected.",
        ))
    elif status in (400, 403) and any(m in lowered for m in geo_markers):
        checks.append(_check(
            "endpoint", FAIL,
            f"Google rejected the request on location grounds (HTTP {status}): "
            f"{payload[:200]}",
            "route through a supported-region exit; see the egress layer above",
        ))
    elif status in (401, 403):
        checks.append(_check(
            "endpoint", OK,
            f"the real {CLOUDCODE_HOST} ({target}) is reachable - HTTP {status} auth "
            f"refusal, so the network path is fine",
        ))
    else:
        checks.append(_check(
            "endpoint", WARN,
            f"the real {CLOUDCODE_HOST} ({target}) answered HTTP {status}: {payload[:200]}",
        ))
    return checks


# --------------------------------------------------------------------------
# Layer 5b: the model agy starts on
# --------------------------------------------------------------------------

def check_default_model(country, dnspin=False):
    """Report whether agy's default model can answer from *country*.

    The binary patch and the egress route are not the only moving parts.  The
    TUI starts on agy's saved default, and the server-side region gate is
    attached to the Gemini family: measured 2026-10-27 from a Russian IP with
    no VPN, Gemini answered ``400 User location is not supported`` while
    ``claude-sonnet-4-6`` and ``gpt-oss-120b-medium`` answered normally.  A
    fully patched, correctly routed install that starts on Gemini therefore
    still fails every request, and the error looks like a broken unlock rather
    than a model choice.

    This layer names that cause and the one command that fixes it.  It is
    read-only, like every other doctor check.
    """
    path = get_agy_settings_path()
    try:
        current = default_model(path)
    except ModelSettingsError as e:
        return [_check(
            "model", WARN,
            f"cannot read agy's default model: {e}",
            "start agy once (for example 'agy models'), then re-run doctor",
        )]

    if not current:
        return [_check(
            "model", WARN,
            f"agy has no saved default model in {path}, so its built-in default "
            f"(Gemini on current builds) applies",
            "antigravity-unlock model ru",
        )]

    if dnspin:
        return [_check(
            "model", OK,
            f"agy starts on {current!r}.  Gemini-family calls go through the no-VPN "
            f"DNS-pin relays, so the direct {country or 'blocked'} egress is not the "
            f"path these requests take; the functional layer proves it end-to-end.",
        )]

    if country in BLOCKED_COUNTRIES:
        if is_gemini_model(current):
            return [_check(
                "model", FAIL,
                f"agy starts on {current!r}, and the server-side region gate is "
                f"attached to the Gemini family.  From {country} Google refuses it "
                f"with 'User location is not supported' no matter how well the binary "
                f"is patched or how the traffic is routed.",
                "antigravity-unlock model ru   (switches the default to a non-Gemini "
                "model that was measured answering from a Russian IP with no VPN)",
            )]
        return [_check(
            "model", OK,
            f"agy starts on {current!r}, a non-Gemini model.  Measured 2026-10-27 from "
            f"a Russian IP with no VPN: claude-* and gpt-oss-* answered while Gemini "
            f"was refused.",
        )]

    if country is None:
        return [_check(
            "model", OK,
            f"agy starts on {current!r}.  The egress country could not be determined, "
            f"so no claim is made about whether Gemini would be accepted; if requests "
            f"fail with 'User location is not supported', run 'antigravity-unlock model ru'.",
        )]

    return [_check(
        "model", OK,
        f"agy starts on {current!r}; the egress is {country}, a supported region.",
    )]


# --------------------------------------------------------------------------
# Layer 5c: no-VPN DNS pin
# --------------------------------------------------------------------------

def check_dnspin(proxy):
    """Report whether the public unblock-DNS relays are live.

    The pin is the lightest exit: no VPN, no VPS, no root.  It is also the
    most fragile, because the relays are third-party and rotate.  This layer
    says what was actually chosen, so a failure is diagnosed as "the provider
    is down" rather than "the patch is broken".
    """
    chosen = pin_ips(proxy.status) if proxy.status else dict(proxy.pinned)
    live = {host: ips for host, ips in chosen.items() if ips}
    if live:
        summary = ", ".join(f"{host.split('.')[0]}={ips[0]}" for host, ips in live.items())
        return [_check(
            "dnspin", OK,
            f"no-VPN DNS pin is live via public unblock-DNS relays: {summary}. "
            f"Only the three Google API hosts use the relays; account login and "
            f"everything else stay direct.",
        )]
    return [_check(
        "dnspin", FAIL,
        "dnspin is enabled but no public relay answered a real TLS probe.",
        "antigravity-unlock dnspin status   (providers may be down); or fall back to "
        "'antigravity-unlock model ru' / a VPS route",
    )]


# --------------------------------------------------------------------------
# Layer 6: does agy actually work
# --------------------------------------------------------------------------

FUNCTIONAL_PROMPT = "Reply with exactly: DOCTOR_OK"
FUNCTIONAL_TIMEOUT = 120.0


def check_functional(agy_path=None, timeout=FUNCTIONAL_TIMEOUT, route=None):
    """Run agy end-to-end and report what actually happened.

    Every other layer is inference: this one is the ground truth.  A real
    completion proves the client-side gate is bypassed *and* the model API
    accepts the request from this egress, which no unauthenticated probe can
    establish.  It costs one model call, so ``run_doctor`` can skip it.

    *route* is the configured exit, when there is one.  Testing without it would
    report a healthy install as broken: from a blocked region the direct path
    always gets a server-side 400 no matter how well the binary is patched, so
    the probe has to travel the same way agy really will.
    """
    agy_path = agy_path or get_primary_agy()
    if not agy_path:
        return [_check("functional", WARN, "no agy binary to test")]

    cmd = [agy_path, "-p", FUNCTIONAL_PROMPT, "--print-timeout", f"{int(timeout)}s"]
    env = build_child_env(route, agy_path=agy_path) if route else None
    via = f" via {route['label']}" if route else " direct"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, env=env, timeout=timeout + 30, check=False,
        )
    except subprocess.TimeoutExpired:
        return [_check(
            "functional", WARN,
            f"agy did not answer within {int(timeout)}s{via} (first call after a patch can "
            f"be slow; the network path may also be stalling)",
            "re-run doctor, and if it still hangs check the egress route",
        )]
    except Exception as e:
        return [_check("functional", FAIL, f"could not run agy: {e}")]

    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    status, _detail = classify_agy(out, proc.returncode)
    snippet = " / ".join(out.splitlines()[-2:])[:120]

    if status == STATUS_OK:
        return [_check(
            "functional", OK,
            f"agy completed a real prompt end-to-end{via} (exit 0): {snippet!r}",
        )]

    if status == STATUS_REGION_BLOCKED:
        return [_check(
            "functional", FAIL,
            f"Google rejected the request's source IP{via}: {out[:200]!r}. This is the "
            f"server-side gate, not the eligibility gate - the binary patch is doing "
            f"its job and cannot help here, because the refusal is about the address "
            f"the connection arrives from. Measured 2026-09-27: the gate was observed "
            f"on Gemini models only - claude-* and gpt-oss-* from the same Russian IP "
            f"reached the quota system instead of being geo-refused.",
            "cheapest first: antigravity-unlock model ru   (switches agy's default to "
            "claude-sonnet-4-6, measured answering from a Russian IP with no VPN). "
            "If you specifically need Gemini, add an exit that really leaves the "
            "country: antigravity-unlock egress add socks5h://host:1080   - note that "
            "free Cloudflare WARP was measured exiting at a Russian Cloudflare edge "
            "and does not help",
        )]

    if status == STATUS_TRANSIENT:
        return [_check(
            "functional", WARN,
            f"a single request was dropped in transit{via}, so this run proves nothing "
            f"either way: {snippet!r}. agy reports these under the same 'Eligibility "
            f"check failed' heading as a real regional verdict, which is why this is "
            f"not reported as an unpatched binary",
            "just re-run 'antigravity-unlock doctor'; if it keeps happening, the exit "
            "or the tunnel is dropping connections",
        )]

    if status == STATUS_GATE:
        return [_check(
            "functional", FAIL,
            f"agy is still hitting the client-side eligibility gate{via}: {out[:300]!r}",
            "antigravity-unlock patch   (and check which agy binary is first on PATH)",
        )]

    if status == STATUS_PROXY_UNREACHABLE:
        return [_check(
            "functional", FAIL,
            f"agy could not reach the configured exit{via}: {out[:300]!r}",
            "start the proxy, or clear it: antigravity-unlock egress disable",
        )]

    if status == STATUS_CREDENTIALS:
        return [_check(
            "functional", WARN,
            f"the network path{via} is fine but agy is not signed in "
            f"(401 CREDENTIALS_MISSING): {snippet!r}",
            "run agy once interactively and sign in",
        )]

    return [_check(
        "functional", FAIL,
        f"agy exited {proc.returncode}{via}: {out[:300] or '(no output)'!r}",
        "inspect the message above; run 'antigravity-unlock doctor' again after fixing it",
    )]



# --------------------------------------------------------------------------

def run_doctor(timeout=DEFAULT_TIMEOUT, skip_network=False, skip_functional=False):
    """Run every layer and return ``(overall, layers, meta)``.

    *layers* is a flat list of check dicts; ``overall`` is the worst verdict.
    """
    agy_path = get_primary_agy()
    installed_version = get_agy_version(agy_path) if agy_path else None
    cfg = load_config()

    layers = []
    layers += check_binary(timeout=timeout)
    layers += check_config(installed_version=installed_version)
    layers += check_hosts()

    # No-VPN DNS pin.  Starting it here is what makes the functional probe
    # travel the same path agy will: through the local pin proxy.
    dnspin_proxy = None
    if cfg.get("dnspin_enabled") and not skip_network:
        try:
            dnspin_proxy = start_dnspin_proxy(
                refresh_seconds=int(cfg.get("dnspin_refresh_seconds", 300) or 300)
            )
            layers += check_dnspin(dnspin_proxy)
        except Exception as e:  # noqa: BLE001 - report, do not crash doctor
            layers.append(_check(
                "dnspin", FAIL, f"dnspin is enabled but could not start: {e}",
                "antigravity-unlock dnspin status",
            ))

    dnspin_live = (
        dnspin_proxy is not None
        and any(pin_ips(dnspin_proxy.status).values() if dnspin_proxy.status
                else dnspin_proxy.pinned.values())
    )

    if skip_network:
        layers.append(_check("network", WARN, "skipped (--no-network)"))
        geo = None
        layers += check_egress_routes(cfg=cfg, timeout=timeout)
    elif dnspin_live:
        # The three API hosts do not take the direct path while the pin is up,
        # so a direct-RU warning would describe a route agy is not using.  The
        # dnspin layer already reported the relays; endpoint reachability is
        # still worth checking.
        layers.append(_check(
            "egress", OK,
            "dnspin routes daily-cloudcode-pa, generativelanguage and cloudcode-pa "
            "through public relays; the direct egress is not used for them.",
        ))
        geo = None
        layers += check_endpoint(timeout=timeout)
    else:
        egress_checks, geo = check_egress(timeout=timeout)
        layers += egress_checks
        layers += check_egress_routes(cfg=cfg, timeout=timeout, direct_geo=geo)
        layers += check_endpoint(timeout=timeout)

    # The functional probe must travel the way agy really will.  From a blocked
    # region the direct path is always refused server-side, so testing it while a
    # working exit is configured would report a healthy install as broken.
    route = active_route(cfg, agy_path=agy_path)
    if dnspin_proxy is not None:
        route = {"label": "dnspin", "url": f"http://127.0.0.1:{dnspin_proxy.port}"}

    # Which country will Google see?  With a configured exit that is the exit's
    # country, not the direct one.  The model layer needs this value, and the
    # route geo lookup already happened in check_egress_routes; repeating it
    # once here is cheaper than threading a return value through that API.
    # With dnspin the country is "whatever the public relay exits in", which is
    # not the direct geo; the functional layer is the proof, so do not let the
    # direct RU geo fail the model layer.
    if dnspin_proxy is not None:
        layers += check_default_model(None, dnspin=True)
    else:
        effective_geo = geo
        if route is not None and not skip_network:
            effective_geo = route_egress_geo(route, timeout=timeout) or geo
        layers += check_default_model(geo_country(effective_geo))

    if skip_functional:
        layers.append(_check("functional", WARN, "skipped (--no-functional)"))
        functional_ok = None
        if dnspin_proxy is not None:
            dnspin_proxy.stop()
    else:
        try:
            functional = check_functional(agy_path=agy_path, route=route)
            layers += functional
            functional_ok = functional[0]["verdict"] == OK
        finally:
            if dnspin_proxy is not None:
                dnspin_proxy.stop()

    overall = max((c["verdict"] for c in layers), key=lambda v: _RANK.get(v, 0), default=OK)

    # The functional layer is the only one that observes agy actually working;
    # everything else is inference.  When a real completion succeeded, an
    # inferred FAIL must not be allowed to declare the install broken - it is
    # downgraded to a warning and reported as such.  The converse does not hold:
    # a failing agy stays FAIL whatever the other layers say.  This is also what
    # keeps the direct-egress and direct-endpoint layers honest once an exit is
    # configured: they describe a path agy no longer takes.
    overridden = []
    if functional_ok and overall == FAIL:
        overridden = [c["name"] for c in layers if c["verdict"] == FAIL]
        for c in layers:
            if c["verdict"] == FAIL:
                c["verdict"] = WARN
                c["summary"] = (
                    "agy works despite this, so it is a latent problem rather than the "
                    "current cause - worth fixing before it becomes the cause. "
                    + c["summary"]
                )
        overall = WARN

    return overall, layers, {
        "agy_path": agy_path,
        "installed_version": installed_version,
        "geo": geo,
        "functional_ok": functional_ok,
        "dnspin": dnspin_proxy is not None,
        "downgraded_from_fail": overridden,
        "pinned_backup": get_pinned_backup_path(agy_path) if agy_path else None,
        "egress_route": route["label"] if route else None,
    }


def format_report(overall, layers, meta):
    """Render a doctor run as text."""
    icons = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}
    lines = []
    lines.append(f"agy: {meta.get('agy_path') or 'not found'}"
                 f"   version: {meta.get('installed_version') or '?'}")
    if meta.get("geo"):
        g = meta["geo"]
        lines.append(f"egress: {g.get('ip') or g.get('query')} "
                     f"({(g.get('country') or g.get('countryCode') or '??')}, "
                     f"{g.get('org') or g.get('isp') or '?'})")
    lines.append("")

    for c in layers:
        lines.append(f"{icons.get(c['verdict'], '[ ? ]')} {c['name']}")
        lines.append(f"        {c['summary']}")
        if c.get("fix"):
            lines.append(f"        -> {c['fix']}")

    lines.append("")
    if overall == OK:
        lines.append("Overall: agy works end-to-end, every layer healthy.")
    elif meta.get("functional_ok") and overall != FAIL:
        lines.append("Overall: agy works end-to-end. The items above are latent problems,")
        lines.append("           not the current cause - fix them before they become it.")
    else:
        verdict_text = {
            WARN: "Working, with warnings worth addressing.",
            FAIL: "Broken - see the [FAIL] layers above.",
        }[overall]
        lines.append(f"Overall: {verdict_text}")
    return "\n".join(lines)
