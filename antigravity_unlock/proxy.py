"""
Split-Tunnel Local Proxy Server for Antigravity CLI.
Routes accounts.google.com DIRECTLY and generativelanguage.googleapis.com / daily-cloudcode-pa via Smart DNS.
Supports full gRPC / HTTP/2 pass-through without breaking TLS/ALPN state.
"""

import sys
import os
import time
import random
import struct
import socket
import asyncio
import logging
from urllib.parse import urlparse

# Configure default logging
logger = logging.getLogger("antigravity_proxy")

# Domains to route DIRECTLY (no proxying / no smart DNS)
DIRECT_DOMAINS = {
    "accounts.google.com",
    "oauth2.googleapis.com",
    "ssl.gstatic.com",
    "www.gstatic.com",
    "lh3.googleusercontent.com",
    "openidconnect.googleapis.com",
}

# Upstream Smart DNS servers for AI endpoints
SMART_DNS_PRIMARY = "111.88.96.50"
SMART_DNS_SECONDARY = "111.88.96.51"

# Memory cache for resolved DNS entries: {hostname: (ip, expiry_timestamp)}
DNS_CACHE = {}
CACHE_TTL = 300  # seconds

def query_dns_server(hostname, dns_ip, timeout=1.5):
    """
    Sends a pure-Python UDP DNS query for A-record to a specific DNS server IP.
    Returns resolved IPv4 string or None on failure/timeout.
    """
    try:
        tx_id = random.randint(0, 65535)
        header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
        qname = b"".join(bytes([len(part)]) + part.encode("ascii") for part in hostname.split(".")) + b"\x00"
        question = qname + struct.pack(">HH", 1, 1)  # Type A (1), Class IN (1)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(header + question, (dns_ip, 53))
            data, _ = sock.recvfrom(1024)
        finally:
            sock.close()

        # Parse DNS response packet
        idx = 12 + len(question)
        if len(data) < idx:
            return None

        ancount = struct.unpack(">H", data[6:8])[0]
        for _ in range(ancount):
            if idx >= len(data):
                break
            # Skip domain name (handle compressed pointer 0xC0 or standard label)
            if data[idx] >= 192:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    idx += 1 + data[idx]
                idx += 1
            if idx + 10 > len(data):
                break

            rtype, rclass, ttl, rdlength = struct.unpack(">HHIH", data[idx:idx + 10])
            idx += 10
            if rtype == 1 and rdlength == 4 and idx + 4 <= len(data):  # IPv4 A record
                return socket.inet_ntoa(data[idx:idx + 4])
            idx += rdlength
    except Exception as e:
        logger.debug(f"DNS UDP query error for {hostname} via {dns_ip}: {e}")
    return None

def resolve_smart_dns(hostname, primary=SMART_DNS_PRIMARY, secondary=SMART_DNS_SECONDARY):
    """
    Resolves hostname via Smart DNS with memory caching and fallback.
    Returns resolved IP address string or original hostname on failure.
    """
    norm_host = hostname.strip().lower().rstrip(".")
    # Direct domains use system DNS
    if any(norm_host == d or norm_host.endswith("." + d) for d in DIRECT_DOMAINS):
        return hostname

    now = time.time()
    if norm_host in DNS_CACHE:
        ip, expiry = DNS_CACHE[norm_host]
        if now < expiry:
            return ip

    # Query Smart DNS primary & secondary
    resolved_ip = query_dns_server(norm_host, primary)
    if not resolved_ip and secondary:
        resolved_ip = query_dns_server(norm_host, secondary)

    if resolved_ip:
        DNS_CACHE[norm_host] = (resolved_ip, now + CACHE_TTL)
        logger.debug(f"Smart DNS resolved {hostname} -> {resolved_ip}")
        return resolved_ip

    return hostname

async def pipe_streams(reader, writer):
    """Pipes bytes continuously between reader and writer."""
    try:
        while not reader.at_eof():
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError, OSError):
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

class SplitTunnelProxy:
    def __init__(self, host="127.0.0.1", port=18888, smart_ip=SMART_DNS_PRIMARY):
        self.host = host
        self.port = port
        self.smart_ip = smart_ip
        self.server = None

    def _is_direct(self, hostname):
        norm = hostname.strip().lower().rstrip(".")
        return any(norm == d or norm.endswith("." + d) for d in DIRECT_DOMAINS)

    def _should_mitm(self, hostname):
        norm = hostname.strip().lower().rstrip(".")
        if self._is_direct(norm):
            return False
        return any(d in norm for d in ["generativelanguage", "daily-cloudcode-pa"])

    async def resolve_smart(self, hostname):
        """Resolves hostname using Smart DNS IP lookup if needed, or falls back to system DNS."""
        return resolve_smart_dns(hostname, primary=self.smart_ip, secondary=SMART_DNS_SECONDARY)

    async def handle_client(self, client_reader, client_writer):
        """Handles incoming client proxy connection (HTTP CONNECT / GET / POST)."""
        try:
            req_line = await client_reader.readline()
            if not req_line:
                client_writer.close()
                return

            req_str = req_line.decode("latin1", errors="ignore")
            parts = req_str.strip().split()
            if len(parts) < 2:
                client_writer.close()
                return

            method, url = parts[0], parts[1]

            if method == "CONNECT":
                # HTTPS Tunneling
                if ":" in url:
                    host, port_str = url.split(":", 1)
                    port = int(port_str)
                else:
                    host, port = url, 443

                # Read remaining HTTP headers until empty line
                while True:
                    line = await client_reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break

                target_host = await self.resolve_smart(host)

                try:
                    target_reader, target_writer = await asyncio.open_connection(target_host, port)
                except Exception as e:
                    logger.warning(f"Failed to connect to {host}:{port} ({target_host}): {e}")
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await client_writer.drain()
                    client_writer.close()
                    return

                # Send 200 Connection Established
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()

                # Bi-directional forwarding
                await asyncio.gather(
                    pipe_streams(client_reader, target_writer),
                    pipe_streams(target_reader, client_writer),
                    return_exceptions=True
                )
            else:
                # HTTP GET / POST / etc.
                parsed = urlparse(url)
                host = parsed.hostname or ""
                port = parsed.port or 80

                target_host = await self.resolve_smart(host)

                try:
                    target_reader, target_writer = await asyncio.open_connection(target_host, port)
                except Exception as e:
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await client_writer.drain()
                    client_writer.close()
                    return

                # Forward original request line & headers
                target_writer.write(req_line)
                while True:
                    line = await client_reader.readline()
                    target_writer.write(line)
                    if line in (b"\r\n", b"\n", b""):
                        break
                await target_writer.drain()

                await asyncio.gather(
                    pipe_streams(client_reader, target_writer),
                    pipe_streams(target_reader, client_writer),
                    return_exceptions=True
                )

        except Exception as e:
            logger.debug(f"Proxy connection error: {e}")
        finally:
            try:
                client_writer.close()
                await client_writer.wait_closed()
            except Exception:
                pass

    async def start(self):
        """Starts the proxy server."""
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info(f"Split-Tunnel Proxy running on http://{self.host}:{self.port}")

    async def stop(self):
        """Stops the proxy server."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()

def run_proxy_server(host="127.0.0.1", port=18888):
    """Synchronous entry point to run proxy server."""
    proxy = SplitTunnelProxy(host=host, port=port)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(proxy.start())
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(proxy.stop())
        loop.close()

def _should_intercept_url(url_path):
    """Returns True if the URL path corresponds to an eligibility check endpoint."""
    return any(p in url_path for p in ("/v1internal:loadCodeAssist", "/v1internal:checkEligibility"))

def _rewrite_eligibility(data):
    """Rewrites region ineligibility responses to ELIGIBLE."""
    if not isinstance(data, (bytes, bytearray)):
        return data, False
    changed = False
    new_data = data
    if b"NOT_ELIGIBLE_REGION_OUT_OF_SCOPE" in new_data or b"NOT_ELIGIBLE" in new_data:
        new_data = new_data.replace(b"NOT_ELIGIBLE_REGION_OUT_OF_SCOPE", b"ELIGIBLE")
        new_data = new_data.replace(b"NOT_ELIGIBLE", b"ELIGIBLE")
        changed = True
    return new_data, changed

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
    run_proxy_server()
