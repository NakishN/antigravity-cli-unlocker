"""
No-VPN egress for the three Google API hosts, via public unblock-DNS relays.

The server-side gate is a check on the source IP.  A full VPN is one way to
change that IP; a *DNS substitution* is another, and it is much lighter: public
"unblock" DNS services answer the blocked Google hostnames with the addresses of
their own relays, which forward the TLS stream to Google from a supported
region.  Because the relay is a TCP forwarder and does not terminate TLS, the
certificate `agy` sees is still Google's and the OAuth token stays inside the
TLS stream - the relay sees metadata, not credentials.

Measured 2026-10-27 from a Russian ISP (95.26.84.28, AS8402 Vimpelcom), no VPN,
no proxy, patched agy 1.4.8:

    daily-cloudcode-pa.googleapis.com -> 159.194.200.33 (geohide)
    generativelanguage.googleapis.com -> 142.251.153.2  (comss)
    cloudcode-pa.googleapis.com       -> 206.223.251.18 (comss)

    agy -p "Say DNS_PIN_GEMINI_OK" --model gemini-3.8-flash-low
    -> DNS_PIN_GEMINI_OK

The mechanism is the one used by Asalio123/antigravity-unlocker (a readable port
of confeden/Antigravity) and by the original Windows unlocker: query geohide.ru,
comss.one and dns-ai.ru, compare their answers with a baseline resolver, and keep
only the substituted addresses.  This module implements it *without* /etc/hosts
and without root: it runs a local CONNECT proxy that maps only the three API
hosts to the relays, and leaves every other hostname (accounts.google.com,
lh3.googleusercontent.com, telemetry, ...) on the normal path.  The proxy does
not decrypt TLS.

Caveats, stated plainly: the relays are third-party free services, their
addresses rotate, and they can die (xbox-dns.ru did in October 2026).  Every
candidate is probed with a real TLS handshake and an HTTP request before it is
used; a failed refresh keeps the previous pin; `dnspin status` shows what is
live.  For a guaranteed exit, a user-owned VPS or VPN is still stronger.
"""

import base64
import concurrent.futures
import http.client
import logging
import os
import random
import re
import select
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.parse

logger = logging.getLogger("antigravity_unlocker.dnspin")

PIN_HOSTS = (
    "daily-cloudcode-pa.googleapis.com",
    "generativelanguage.googleapis.com",
    "cloudcode-pa.googleapis.com",
)

# Public unblock-DNS services.  UDP/53 is tried first because it is cheapest;
# DoH is the fallback for networks that hijack or block UDP/53.
UDP_PROVIDERS = (
    ("geohide", ("37.230.192.51", "45.155.204.190")),
    ("comss", ("83.220.169.155", "212.109.195.93", "195.133.25.16")),
)

# (name, hostname, hardcoded IPs).  The hardcoded IP protects the DoH bootstrap
# when the provider's own name is poisoned or the system resolver lies.
DOH_PROVIDERS = (
    ("geohide", "dns.geohide.ru", ("37.230.192.51", "45.155.204.190")),
    ("comss", "dns.comss.one", ("83.220.169.155", "212.109.195.93", "195.133.25.16")),
    ("dns-ai", "dns.dns-ai.ru", ("192.144.59.14", "186.246.49.127", "185.251.90.181")),
)

BASE_RESOLVERS = ("8.8.8.8", "1.1.1.1")

DEFAULT_DNS_TIMEOUT = 3.0
DEFAULT_PROBE_TIMEOUT = 6.0
DEFAULT_REFRESH_SECONDS = 300

# Markers for the optional /etc/hosts pin.  The pin is the only mode that makes
# a *bare* `agy` use the relays with no environment and no wrapper; it needs
# root once, so it is opt-in via `dnspin pin-hosts`.
HOSTS_MARKER_BEGIN = "# >>> antigravity-unlocker dnspin >>>"
HOSTS_MARKER_END = "# <<< antigravity-unlocker dnspin <<<"


# --------------------------------------------------------------------------
# DNS wire format
# --------------------------------------------------------------------------

def _build_query(host, txid=None):
    txid = random.randint(0, 65535) if txid is None else txid
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in host.split(".")) + b"\x00"
    return header + qname + struct.pack(">HH", 1, 1)


def _skip_name(data, idx):
    while idx < len(data):
        length = data[idx]
        if length >= 192:  # compression pointer
            return idx + 2
        if length == 0:
            return idx + 1
        idx += 1 + length
    return idx


def parse_a_response(data):
    """Return the IPv4 A records in a DNS response, in order."""
    if len(data) < 12:
        return []
    ancount = struct.unpack(">H", data[6:8])[0]
    idx = 12
    qdcount = struct.unpack(">H", data[4:6])[0]
    for _ in range(qdcount):
        idx = _skip_name(data, idx)
        idx += 4
    answers = []
    for _ in range(ancount):
        if idx >= len(data):
            break
        idx = _skip_name(data, idx)
        if idx + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", data[idx:idx + 10])
        idx += 10
        if rtype == 1 and rdlength == 4 and idx + 4 <= len(data):
            answers.append(socket.inet_ntoa(data[idx:idx + 4]))
        idx += rdlength
    return answers


def query_udp(host, server_ip, timeout=DEFAULT_DNS_TIMEOUT):
    """A-record query over UDP/53.  Returns [] on any failure."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(_build_query(host), (server_ip, 53))
        data, _ = sock.recvfrom(2048)
        return parse_a_response(data)
    except OSError as e:
        logger.debug("UDP DNS %s via %s failed: %s", host, server_ip, e)
        return []
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


class _DoHConnection(http.client.HTTPSConnection):
    """HTTPS connection to a DoH provider's IP, with the provider's SNI."""

    def __init__(self, host, ip, timeout=DEFAULT_DNS_TIMEOUT):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def query_doh(host, provider_host, provider_ips, timeout=DEFAULT_DNS_TIMEOUT):
    """A-record query over DoH (RFC 8484, wire format).  Returns [] on failure."""
    wire = _build_query(host)
    encoded = base64.urlsafe_b64encode(wire).rstrip(b"=").decode("ascii")
    path = "/dns-query?dns=" + encoded
    for ip in provider_ips:
        conn = None
        try:
            conn = _DoHConnection(provider_host, ip, timeout=timeout)
            conn.request("GET", path, headers={
                "accept": "application/dns-message",
                "user-agent": "antigravity-unlocker-dnspin/1.0",
            })
            resp = conn.getresponse()
            body = resp.read()
            if resp.status == 200:
                answers = parse_a_response(body)
                if answers:
                    return answers
        except (OSError, ssl.SSLError, http.client.HTTPException) as e:
            logger.debug("DoH %s via %s (%s) failed: %s", host, provider_host, ip, e)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return []


# --------------------------------------------------------------------------
# Candidate collection and probing
# --------------------------------------------------------------------------

def baseline_ips(host, timeout=DEFAULT_DNS_TIMEOUT):
    """The real Google addresses, used to tell a substitution from a real answer."""
    for server in BASE_RESOLVERS:
        answers = query_udp(host, server, timeout=timeout)
        if answers:
            return set(answers)
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        return {info[4][0] for info in infos}
    except OSError:
        return set()


def collect_candidates(host, timeout=DEFAULT_DNS_TIMEOUT, baseline=None):
    """Every provider answer that is not one of the baseline addresses."""
    baseline = baseline if baseline is not None else baseline_ips(host, timeout=timeout)
    found = []

    def add(answers):
        for ip in answers:
            if ip not in baseline and ip not in found:
                found.append(ip)

    for _name, ips in UDP_PROVIDERS:
        for ip in ips:
            add(query_udp(host, ip, timeout=timeout))
    for _name, provider_host, ips in DOH_PROVIDERS:
        add(query_doh(host, provider_host, ips, timeout=timeout))

    return found, baseline


def probe_relay(host, ip, timeout=DEFAULT_PROBE_TIMEOUT):
    """Real TLS handshake + HTTP request through *ip* for *host*.

    Returns latency in seconds, or None.  Certificate verification is left on:
    a relay that presents its own certificate instead of Google's is rejected,
    which is exactly what we want for an OAuth-bearing connection.
    """
    started = time.time()
    try:
        context = ssl.create_default_context()
        with socket.create_connection((ip, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                tls.sendall(
                    f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
                )
                data = tls.recv(64)
        if not data.startswith(b"HTTP/"):
            return None
        try:
            status = int(data.split(b" ", 2)[1])
        except (IndexError, ValueError):
            return None
        if 200 <= status < 500:
            return time.time() - started
    except (OSError, ssl.SSLError, ValueError) as e:
        logger.debug("relay probe %s via %s failed: %s", host, ip, e)
    return None


def resolve_pin(hosts=PIN_HOSTS, timeout=DEFAULT_DNS_TIMEOUT, probe_timeout=DEFAULT_PROBE_TIMEOUT):
    """Resolve and probe every host.  Returns a status dict per host.

    Shape::

        {host: {"baseline": [...], "candidates": [...],
                "chosen": [{"ip": ..., "latency": ...}, ...]}}
    """
    result = {}
    for host in hosts:
        candidates, baseline = collect_candidates(host, timeout=timeout)
        chosen = []
        if candidates:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
                futures = {pool.submit(probe_relay, host, ip, probe_timeout): ip for ip in candidates}
                measured = []
                for future in concurrent.futures.as_completed(futures):
                    ip = futures[future]
                    try:
                        latency = future.result()
                    except Exception:
                        latency = None
                    if latency is not None:
                        measured.append((latency, ip))
                measured.sort()
                chosen = [{"ip": ip, "latency": round(latency, 3)} for latency, ip in measured]
        result[host] = {
            "baseline": sorted(baseline),
            "candidates": candidates,
            "chosen": chosen,
        }
        logger.debug("dnspin %s: candidates=%s chosen=%s", host, candidates, chosen)
    return result


def pin_ips(status):
    """Only the chosen IPs, host -> [ip, ...]."""
    return {host: [entry["ip"] for entry in info.get("chosen", [])]
            for host, info in status.items()}


# --------------------------------------------------------------------------
# Optional /etc/hosts pin (makes a bare `agy` work, needs root once)
# --------------------------------------------------------------------------

def hosts_path():
    if sys.platform == "win32":
        return r"C:\Windows\System32\drivers\etc\hosts"
    return "/etc/hosts"


def _hosts_block_re():
    return (r"(?:" + re.escape(HOSTS_MARKER_BEGIN) + r".*?"
            + re.escape(HOSTS_MARKER_END) + r"\n?)")


def render_hosts_pin(content, pinned):
    """Return *content* with the dnspin block replaced by *pinned*.

    ``pinned`` is ``{host: [ip, ...]}``; the first IP of each host is used.
    Everything outside the markers is preserved byte-for-byte.
    """
    block_lines = [
        HOSTS_MARKER_BEGIN,
        "# Managed by antigravity-unlock dnspin. Refresh with:",
        "#   sudo antigravity-unlock dnspin pin-hosts",
        "# Keep it fresh automatically with:",
        "#   sudo antigravity-unlock dnspin autopin install",
        "# Remove with:",
        "#   sudo antigravity-unlock dnspin unpin-hosts",
    ]
    for host in PIN_HOSTS:
        ips = pinned.get(host) or []
        if ips:
            block_lines.append(f"{ips[0]}\t{host}")
    block_lines.append(HOSTS_MARKER_END)
    block = "\n".join(block_lines) + "\n"

    cleaned = re.sub(_hosts_block_re(), "", content, flags=re.DOTALL)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned + block


def parse_hosts_pin(content=None, path=None):
    """Return the IPs in the marked dnspin block as ``{host: [ip, ...]}``."""
    if content is None:
        try:
            with open(path or hosts_path(), "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError:
            return {}
    match = re.search(
        re.escape(HOSTS_MARKER_BEGIN) + r"(.*?)" + re.escape(HOSTS_MARKER_END),
        content, re.DOTALL,
    )
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            ip, names = fields[0], fields[1:]
            for name in names:
                result.setdefault(name, []).append(ip)
    return result


def _permission_hint(path, action):
    if sys.platform.startswith("win"):
        return (
            f"need Administrator rights to write {path}; run this command from an "
            f"elevated PowerShell/cmd: antigravity-unlock dnspin {action}"
        )
    return f"need root to write {path}; run: sudo antigravity-unlock dnspin {action}"


def write_hosts_pin(pinned, path=None):
    """Write the dnspin block to /etc/hosts.  Returns ``(ok, message)``."""
    path = path or hosts_path()
    entries = {host: ips for host, ips in pinned.items() if ips}
    if not entries:
        return False, "no live relay to pin"
    if not sys.platform.startswith("win") and hasattr(os, "geteuid") and os.geteuid() != 0:
        return False, _permission_hint(path, "pin-hosts")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        new_content = render_hosts_pin(content, entries)
        tmp = path + ".antigravity-unlock.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new_content)
        try:
            os.chmod(tmp, os.stat(path).st_mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except PermissionError:
        return False, _permission_hint(path, "pin-hosts")
    except OSError as e:
        return False, f"cannot write {path}: {e}"
    count = sum(len(ips) for ips in entries.values())
    return True, f"pinned {len(entries)} host(s) ({count} address(es)) in {path}"


def remove_hosts_pin(path=None):
    """Remove the dnspin block from /etc/hosts.  Returns ``(ok, message)``."""
    path = path or hosts_path()
    if not sys.platform.startswith("win") and hasattr(os, "geteuid") and os.geteuid() != 0:
        return False, _permission_hint(path, "unpin-hosts")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if HOSTS_MARKER_BEGIN not in content:
            return False, f"no dnspin block in {path}"
        cleaned = re.sub(_hosts_block_re(), "", content, flags=re.DOTALL)
        tmp = path + ".antigravity-unlock.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(cleaned)
        try:
            os.chmod(tmp, os.stat(path).st_mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except PermissionError:
        return False, _permission_hint(path, "unpin-hosts")
    except OSError as e:
        return False, f"cannot write {path}: {e}"
    return True, f"removed the dnspin block from {path}"


def sync_hosts_pin(path=None, resolve=None):
    # Refresh the marked hosts block from the currently live relays.
    #
    # Returns (code, message): 0 means the pin is usable (changed or already
    # current), 1 means it could not be written, 2 means there is no live relay
    # and no previous pin. Hosts with no live relay keep their previous address,
    # so one flaky provider does not take down the other two.
    path = path or hosts_path()
    current = parse_hosts_pin(path=path)
    resolve = resolve or resolve_pin
    try:
        status = resolve()
    except Exception as e:  # noqa: BLE001 - a network failure is not a crash
        return 1, f"relay resolution failed: {e}"

    chosen = pin_ips(status)
    merged = {}
    for host in PIN_HOSTS:
        current_ips = current.get(host) or []
        live_ips = chosen.get(host) or []
        if current_ips and current_ips[0] in live_ips:
            # Keep the address that is already pinned: the relay list is
            # ordered by latency, so blindly taking live_ips[0] rewrites the
            # file every tick even though the current pin is still healthy.
            merged[host] = current_ips
        elif live_ips:
            merged[host] = live_ips
        elif current_ips:
            merged[host] = current_ips

    if not merged:
        return 2, "no live relay and no previous pin; nothing to write"

    if not any(chosen.values()) and current:
        return 0, f"no live relay; keeping the previous pin in {path}"

    def first(mapping, host):
        return (mapping.get(host) or [None])[0]

    if all(first(current, host) == first(merged, host) for host in PIN_HOSTS):
        return 0, f"pin in {path} is already current"

    ok, msg = write_hosts_pin(merged, path=path)
    return (0 if ok else 1), msg


# --------------------------------------------------------------------------
# Local CONNECT proxy
# --------------------------------------------------------------------------

class DnsPinProxy:
    """A local HTTP CONNECT proxy that maps only PIN_HOSTS to the relays.

    Everything else is resolved normally and tunneled directly, so account
    login, avatars and telemetry never touch a third-party relay.
    """

    def __init__(self, host="127.0.0.1", port=0, pinned=None,
                 refresh_seconds=DEFAULT_REFRESH_SECONDS, auto_resolve=True):
        self.host = host
        self.port = port
        self.pinned = dict(pinned or {})
        self.refresh_seconds = max(30, int(refresh_seconds))
        self.auto_resolve = auto_resolve
        self._server = None
        self._thread = None
        self._refresh_thread = None
        self._stop = threading.Event()
        self.status = {}

    def start(self):
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(64)
        self.port = self._server.getsockname()[1]
        if self.auto_resolve:
            self.refresh()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        if self.auto_resolve:
            self._refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
            self._refresh_thread.start()
        logger.info("dnspin proxy on %s:%s", self.host, self.port)
        return self

    def refresh(self):
        try:
            status = resolve_pin()
        except Exception as e:  # noqa: BLE001 - keep the previous pin
            logger.warning("dnspin refresh failed: %s", e)
            return False
        new = pin_ips(status)
        if any(new.values()):
            self.status = status
            self.pinned = new
            return True
        logger.warning("dnspin refresh found no live relay; keeping the previous pin")
        return False

    def _refresh_loop(self):
        while not self._stop.wait(self.refresh_seconds):
            self.refresh()

    def _pinned_ip(self, host):
        for ip in self.pinned.get(host, []):
            yield ip

    def _connect(self, host, port):
        if host in self.pinned:
            for ip in self._pinned_ip(host):
                try:
                    return socket.create_connection((ip, port), timeout=15)
                except OSError as e:
                    logger.debug("pinned %s via %s failed: %s", host, ip, e)
            logger.warning("all pinned relays for %s failed; falling back to direct DNS", host)
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"no address for {host}")
        return socket.create_connection(infos[0][4], timeout=15)

    @staticmethod
    def _relay(a, b):
        try:
            while True:
                readable, _, _ = select.select([a, b], [], [], 120)
                if not readable:
                    return
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        return
                    (b if sock is a else a).sendall(data)
        except OSError:
            pass
        finally:
            for sock in (a, b):
                try:
                    sock.close()
                except OSError:
                    pass

    def _handle(self, client):
        upstream = None
        try:
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = client.recv(4096)
                if not chunk:
                    return
                buf += chunk
            head, _, rest = buf.partition(b"\r\n\r\n")
            first = head.split(b"\r\n")[0].decode("latin1", "replace")
            parts = first.split()
            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                return
            target = parts[1]
            host, _, port_s = target.rpartition(":")
            port = int(port_s) if port_s.isdigit() else 443
            upstream = self._connect(host, port)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if rest:
                upstream.sendall(rest)
            self._relay(client, upstream)
        except Exception as e:  # noqa: BLE001 - one connection must not kill the proxy
            logger.debug("dnspin connection error: %s", e)
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass


def start_proxy(port=0, refresh_seconds=DEFAULT_REFRESH_SECONDS):
    """Create and start a proxy; returns the object (use .port)."""
    return DnsPinProxy(port=port, refresh_seconds=refresh_seconds).start()


def format_status(status):
    """Human-readable status, used by the CLI and doctor."""
    lines = []
    for host in PIN_HOSTS:
        info = status.get(host, {})
        lines.append(host)
        lines.append(f"  baseline:  {', '.join(info.get('baseline') or ['?'])}")
        lines.append(f"  candidates:{' ' + ', '.join(info.get('candidates') or []) if info.get('candidates') else ' none'}")
        chosen = info.get("chosen") or []
        if chosen:
            lines.append("  chosen:    " + ", ".join(
                f"{c['ip']} ({c['latency']}s)" for c in chosen[:2]
            ))
        else:
            lines.append("  chosen:    NONE - direct path will be used")
    return "\n".join(lines)


def main(argv=None):
    """Standalone proxy entry point: python -m antigravity_unlock.dnspin [port]."""
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
    argv = list(sys.argv[1:] if argv is None else argv)
    port = int(argv[0]) if argv and argv[0].isdigit() else 0
    proxy = start_proxy(port=port)
    print(f"dnspin proxy: http://127.0.0.1:{proxy.port}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        proxy.stop()


if __name__ == "__main__":
    main()
