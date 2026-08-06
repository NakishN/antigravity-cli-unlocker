"""
MITM TLS Split-Tunnel Proxy for Antigravity CLI.

Architecture:
  - DIRECT domains (accounts.google.com, oauth2.googleapis.com) → plain TCP tunnel (no TLS interception)
  - INTERCEPT domains (*.googleapis.com) → MITM TLS: decrypt, rewrite eligibility response, re-encrypt
  - All other domains → plain TCP tunnel

Eligibility bypass:
  Intercepts POST /v1internal:loadCodeAssist response and rewrites the JSON/proto
  body to remove NOT_ELIGIBLE_REGION_OUT_OF_SCOPE errors.
"""

import sys
import os
import re
import gzip
import zlib
import time
import json
import random
import struct
import socket
import asyncio
import logging
import ssl
import tempfile

from urllib.parse import urlparse

from antigravity_unlock.ca_manager import get_or_create_ca, generate_leaf_cert

logger = logging.getLogger("antigravity_proxy")

# ─── Domain routing ──────────────────────────────────────────────────────────

# These domains are NEVER intercepted — pass through as plain TCP tunnel
DIRECT_DOMAINS = {
    "accounts.google.com",
    "oauth2.googleapis.com",
    "ssl.gstatic.com",
    "www.gstatic.com",
    "lh3.googleusercontent.com",
    "openidconnect.googleapis.com",
}

# These domains will have TLS intercepted (MITM)
INTERCEPT_SUFFIXES = (
    "googleapis.com",
    "google.com",
)

# Upstream Smart DNS servers
SMART_DNS_PRIMARY = "111.88.96.50"
SMART_DNS_SECONDARY = "111.88.96.51"

# ─── DNS resolution ──────────────────────────────────────────────────────────

DNS_CACHE = {}
CACHE_TTL = 300


def query_dns_server(hostname, dns_ip, timeout=1.5):
    """Pure-Python UDP DNS A-record query."""
    try:
        tx_id = random.randint(0, 65535)
        header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
        qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in hostname.split(".")) + b"\x00"
        question = qname + struct.pack(">HH", 1, 1)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        try:
            sock.sendto(header + question, (dns_ip, 53))
            data, _ = sock.recvfrom(1024)
        finally:
            sock.close()

        idx = 12 + len(question)
        if len(data) < idx:
            return None
        ancount = struct.unpack(">H", data[6:8])[0]
        for _ in range(ancount):
            if idx >= len(data):
                break
            if data[idx] >= 192:
                idx += 2
            else:
                while idx < len(data) and data[idx] != 0:
                    idx += 1 + data[idx]
                idx += 1
            if idx + 10 > len(data):
                break
            rtype, _, _, rdlength = struct.unpack(">HHIH", data[idx:idx + 10])
            idx += 10
            if rtype == 1 and rdlength == 4 and idx + 4 <= len(data):
                return socket.inet_ntoa(data[idx:idx + 4])
            idx += rdlength
    except Exception as e:
        logger.debug(f"DNS query error for {hostname} via {dns_ip}: {e}")
    return None


def resolve_smart_dns(hostname, primary=SMART_DNS_PRIMARY, secondary=SMART_DNS_SECONDARY):
    """Resolves hostname via Smart DNS with TTL caching."""
    norm = hostname.strip().lower().rstrip(".")
    if any(norm == d or norm.endswith("." + d) for d in DIRECT_DOMAINS):
        return hostname

    now = time.time()
    if norm in DNS_CACHE:
        ip, expiry = DNS_CACHE[norm]
        if now < expiry:
            return ip

    ip = query_dns_server(norm, primary) or query_dns_server(norm, secondary)
    if ip:
        DNS_CACHE[norm] = (ip, now + CACHE_TTL)
        logger.debug(f"Smart DNS: {hostname} → {ip}")
        return ip
    return hostname


# ─── Eligibility response rewriter ──────────────────────────────────────────

# Patterns in the JSON response body that indicate ineligibility
_INELIGIBILITY_PATTERNS = [
    # JSON string fields
    (re.compile(rb'"NOT_ELIGIBLE[^"]*"'), b'"ELIGIBLE"'),
    (re.compile(rb'"eligibilityStatus"\s*:\s*"[^"]*INELIGIBLE[^"]*"'), b'"eligibilityStatus": "ELIGIBLE"'),
    (re.compile(rb'"eligibilityStatus"\s*:\s*"[^"]*NOT_ELIGIBLE[^"]*"'), b'"eligibilityStatus": "ELIGIBLE"'),
    # Proto text format
    (re.compile(rb'NOT_ELIGIBLE_REGION_OUT_OF_SCOPE'), b'ELIGIBLE\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'),
]

# Error message strings from server that indicate eligibility failure
_INELIGIBILITY_MSG_PATTERNS = [
    re.compile(rb'not eligible for Antigravity'),
    re.compile(rb'not currently available in your location'),
    re.compile(rb'Eligibility check failed'),
]


def _decompress_body(body, encoding):
    """Decompresses response body based on Content-Encoding."""
    encoding = (encoding or "").lower().strip()
    try:
        if encoding == "gzip":
            return gzip.decompress(body)
        elif encoding in ("deflate", "zlib"):
            return zlib.decompress(body)
        elif encoding == "br":
            try:
                import brotli
                return brotli.decompress(body)
            except ImportError:
                return body
    except Exception:
        pass
    return body


def _compress_body(body, encoding):
    """Re-compresses response body."""
    encoding = (encoding or "").lower().strip()
    try:
        if encoding == "gzip":
            return gzip.compress(body)
        elif encoding in ("deflate", "zlib"):
            return zlib.compress(body)
    except Exception:
        pass
    return body


def _rewrite_eligibility(body_bytes):
    """
    Rewrites eligibility status in response body.
    Handles JSON and proto binary formats.
    Returns (modified_bytes, was_modified).
    """
    modified = body_bytes
    changed = False

    # Try JSON rewrite first
    try:
        obj = json.loads(modified)
        text = json.dumps(obj)
        if any(kw in text for kw in ["NOT_ELIGIBLE", "INELIGIBLE", "not eligible", "not currently available"]):
            obj = _rewrite_json_obj(obj)
            new_text = json.dumps(obj)
            if new_text != text:
                modified = new_text.encode("utf-8")
                changed = True
                logger.info("Eligibility: rewrote JSON response → ELIGIBLE")
    except (json.JSONDecodeError, ValueError):
        pass

    # Regex-based rewrite for proto/mixed formats
    for pattern, replacement in _INELIGIBILITY_PATTERNS:
        new_bytes = pattern.sub(replacement, modified)
        if new_bytes != modified:
            modified = new_bytes
            changed = True
            logger.info(f"Eligibility: rewrote binary/proto pattern → ELIGIBLE")

    return modified, changed


def _rewrite_json_obj(obj):
    """Recursively rewrites eligibility status fields in a JSON object."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k in ("eligibilityStatus", "eligibility_status", "status"):
                if isinstance(v, str) and ("NOT_ELIGIBLE" in v or "INELIGIBLE" in v):
                    result[k] = "ELIGIBLE"
                    continue
            if k in ("message", "description", "reason"):
                if isinstance(v, str) and any(
                    p in v for p in ["not eligible", "not currently available", "Eligibility check failed"]
                ):
                    result[k] = ""
                    continue
            result[k] = _rewrite_json_obj(v)
        return result
    elif isinstance(obj, list):
        return [_rewrite_json_obj(item) for item in obj]
    return obj


def _should_intercept_url(path):
    """Returns True if this URL path needs eligibility rewriting."""
    intercept_paths = [
        "loadCodeAssist",
        "LoadCodeAssist",
        "checkEligibility",
        "getEligibility",
        "v1internal",
    ]
    return any(p in path for p in intercept_paths)


# ─── Pipe helper ─────────────────────────────────────────────────────────────

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


# ─── Leaf cert cache ─────────────────────────────────────────────────────────

_LEAF_CERT_CACHE = {}  # hostname → (key_pem, cert_pem)


def _get_leaf_cert(hostname, ca_key, ca_cert):
    """Gets or generates a leaf cert for the given hostname."""
    base = ".".join(hostname.split(".")[-2:]) if hostname.count(".") >= 2 else hostname
    if base not in _LEAF_CERT_CACHE:
        _LEAF_CERT_CACHE[base] = generate_leaf_cert(base, ca_key, ca_cert)
    return _LEAF_CERT_CACHE[base]


# ─── MITM connection handler ─────────────────────────────────────────────────

async def _mitm_handle(client_reader, client_writer, host, port, target_ip, ca_key, ca_cert):
    """
    Performs MITM TLS interception for a CONNECT tunnel using asyncio loop.start_tls.
    """
    # Send connection established to client
    client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await client_writer.drain()

    # Get or generate leaf cert for this hostname
    key_pem, cert_pem = _get_leaf_cert(host, ca_key, ca_cert)

    tmp_dir = tempfile.mkdtemp(prefix="agy_mitm_")
    key_file = os.path.join(tmp_dir, "leaf.key")
    cert_file = os.path.join(tmp_dir, "leaf.crt")
    try:
        with open(key_file, "wb") as f:
            f.write(key_pem)
        with open(cert_file, "wb") as f:
            f.write(cert_pem)

        client_ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        client_ssl_ctx.load_cert_chain(cert_file, key_file)

        loop = asyncio.get_running_loop()

        # Upgrade client stream to SSL using loop.start_tls
        try:
            transport = client_writer.transport
            protocol = transport.get_protocol()

            # Upgrade server-side (client connection)
            new_transport = await loop.start_tls(
                transport, protocol, client_ssl_ctx, server_side=True
            )

            client_ssl_reader = asyncio.StreamReader()
            client_ssl_protocol = asyncio.StreamReaderProtocol(client_ssl_reader)
            new_transport.set_protocol(client_ssl_protocol)
            client_ssl_writer = asyncio.StreamWriter(new_transport, client_ssl_protocol, client_ssl_reader, loop)
        except Exception as e:
            logger.debug(f"MITM client TLS upgrade failed for {host}: {e}")
            return

        # Connect to real upstream server with TLS
        server_ssl_ctx = ssl.create_default_context()
        try:
            server_reader, server_writer = await asyncio.open_connection(
                target_ip, port,
                ssl=server_ssl_ctx,
                server_hostname=host,
            )
        except Exception as e:
            logger.warning(f"MITM upstream connect failed to {host} ({target_ip}:{port}): {e}")
            client_ssl_writer.close()
            return

        # Proxy HTTP requests and rewrite eligibility responses
        try:
            await _proxy_http_with_rewrite(client_ssl_reader, client_ssl_writer, server_reader, server_writer, host)
        finally:
            try:
                server_writer.close()
                await server_writer.wait_closed()
            except Exception:
                pass
            try:
                client_ssl_writer.close()
                await client_ssl_writer.wait_closed()
            except Exception:
                pass

    finally:
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


async def _proxy_http_with_rewrite(client_reader, client_writer, server_reader, server_writer, host):
    """
    Proxies HTTP/1.1 traffic between client and server.
    Intercepts responses to eligibility endpoints and rewrites them.
    """
    try:
        while True:
            # Read request line from client
            req_line_bytes = await asyncio.wait_for(client_reader.readline(), timeout=30)
            if not req_line_bytes:
                break
            req_line = req_line_bytes.decode("latin1", errors="ignore").strip()
            if not req_line:
                continue

            parts = req_line.split()
            if len(parts) < 2:
                break
            method = parts[0]
            path = parts[1]

            # Read request headers
            req_headers_raw = []
            content_length = 0
            while True:
                line = await asyncio.wait_for(client_reader.readline(), timeout=10)
                req_headers_raw.append(line)
                stripped = line.strip().decode("latin1", errors="ignore")
                if stripped == "":
                    break
                if stripped.lower().startswith("content-length:"):
                    try:
                        content_length = int(stripped.split(":", 1)[1].strip())
                    except ValueError:
                        pass

            # Read request body
            req_body = b""
            if content_length > 0:
                req_body = await asyncio.wait_for(
                    client_reader.readexactly(content_length), timeout=30
                )

            # Forward request to server
            server_writer.write(req_line_bytes)
            for h in req_headers_raw:
                server_writer.write(h)
            if req_body:
                server_writer.write(req_body)
            await server_writer.drain()

            # Read server response status line
            resp_status = await asyncio.wait_for(server_reader.readline(), timeout=60)
            if not resp_status:
                break

            # Read response headers
            resp_headers_raw = []
            resp_headers = {}
            while True:
                line = await asyncio.wait_for(server_reader.readline(), timeout=10)
                resp_headers_raw.append(line)
                stripped = line.strip().decode("latin1", errors="ignore")
                if stripped == "":
                    break
                if ":" in stripped:
                    k, v = stripped.split(":", 1)
                    resp_headers[k.strip().lower()] = v.strip()

            # Decide if we need to intercept this response
            needs_rewrite = _should_intercept_url(path)
            transfer_encoding = resp_headers.get("transfer-encoding", "").lower()
            content_encoding = resp_headers.get("content-encoding", "")
            resp_content_length = int(resp_headers.get("content-length", -1))
            is_chunked = "chunked" in transfer_encoding

            if needs_rewrite and (resp_content_length > 0 or is_chunked):
                # Read full response body for rewriting
                if is_chunked:
                    resp_body = await _read_chunked(server_reader)
                elif resp_content_length > 0:
                    resp_body = await asyncio.wait_for(
                        server_reader.readexactly(resp_content_length), timeout=60
                    )
                else:
                    resp_body = b""

                # Decompress, rewrite, recompress
                raw = _decompress_body(resp_body, content_encoding)
                rewritten, changed = _rewrite_eligibility(raw)
                if changed:
                    resp_body = _compress_body(rewritten, content_encoding)
                    new_len = len(resp_body)

                    # Rebuild headers with updated Content-Length
                    client_writer.write(resp_status)
                    for h in resp_headers_raw[:-1]:  # exclude empty terminator
                        h_str = h.decode("latin1", errors="ignore").strip()
                        if h_str.lower().startswith("content-length:"):
                            client_writer.write(f"Content-Length: {new_len}\r\n".encode())
                        elif h_str.lower().startswith("transfer-encoding:"):
                            client_writer.write(f"Content-Length: {new_len}\r\n".encode())
                        else:
                            client_writer.write(h)
                    client_writer.write(b"\r\n")
                    client_writer.write(resp_body)
                    await client_writer.drain()
                    continue  # Next request

                # No rewrite needed — forward as-is
                client_writer.write(resp_status)
                for h in resp_headers_raw:
                    client_writer.write(h)
                client_writer.write(resp_body)
                await client_writer.drain()

            else:
                # Forward response headers as-is
                client_writer.write(resp_status)
                for h in resp_headers_raw:
                    client_writer.write(h)
                await client_writer.drain()

                # Stream response body
                if is_chunked:
                    await _forward_chunked(server_reader, client_writer)
                elif resp_content_length > 0:
                    remaining = resp_content_length
                    while remaining > 0:
                        chunk = await asyncio.wait_for(
                            server_reader.read(min(65536, remaining)), timeout=30
                        )
                        if not chunk:
                            break
                        client_writer.write(chunk)
                        await client_writer.drain()
                        remaining -= len(chunk)
                elif resp_content_length == -1:
                    # Unknown length — stream until connection closes
                    while True:
                        chunk = await asyncio.wait_for(server_reader.read(65536), timeout=30)
                        if not chunk:
                            break
                        client_writer.write(chunk)
                        await client_writer.drain()

    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionResetError,
            BrokenPipeError, OSError, ssl.SSLError):
        pass
    except Exception as e:
        logger.debug(f"HTTP proxy error for {host}: {e}")


async def _read_chunked(reader):
    """Reads chunked HTTP response body and returns raw decoded bytes."""
    body = b""
    while True:
        size_line = await asyncio.wait_for(reader.readline(), timeout=10)
        size_str = size_line.strip().split(b";")[0]
        chunk_size = int(size_str, 16)
        if chunk_size == 0:
            await reader.readline()  # trailing CRLF
            break
        chunk = await asyncio.wait_for(reader.readexactly(chunk_size), timeout=30)
        body += chunk
        await reader.readline()  # CRLF after chunk
    return body


async def _forward_chunked(reader, writer):
    """Forwards chunked response body from reader to writer."""
    while True:
        size_line = await asyncio.wait_for(reader.readline(), timeout=10)
        writer.write(size_line)
        size_str = size_line.strip().split(b";")[0]
        chunk_size = int(size_str, 16)
        if chunk_size == 0:
            crlf = await reader.readline()
            writer.write(crlf)
            await writer.drain()
            break
        chunk = await asyncio.wait_for(reader.readexactly(chunk_size), timeout=30)
        writer.write(chunk)
        crlf = await reader.readline()
        writer.write(crlf)
        await writer.drain()


# ─── Main proxy class ────────────────────────────────────────────────────────

class SplitTunnelProxy:
    def __init__(self, host="127.0.0.1", port=18888):
        self.host = host
        self.port = port
        self.smart_ip = SMART_DNS_PRIMARY
        self.server = None
        self.ca_key, self.ca_cert, self.ca_cert_path = get_or_create_ca()
        logger.info(f"MITM CA loaded: {self.ca_cert_path}")

    def _is_direct(self, hostname):
        norm = hostname.strip().lower().rstrip(".")
        return any(norm == d or norm.endswith("." + d) for d in DIRECT_DOMAINS)

    def _should_mitm(self, hostname):
        norm = hostname.strip().lower().rstrip(".")
        if self._is_direct(norm):
            return False
        return any(norm.endswith(s) for s in INTERCEPT_SUFFIXES)

    async def resolve_smart(self, hostname):
        """Resolves hostname via Smart DNS."""
        return resolve_smart_dns(hostname, primary=self.smart_ip, secondary=SMART_DNS_SECONDARY)

    async def handle_client(self, client_reader, client_writer):
        """Routes incoming proxy connections."""
        try:
            req_line = await asyncio.wait_for(client_reader.readline(), timeout=15)
            if not req_line:
                return

            req_str = req_line.decode("latin1", errors="ignore")
            parts = req_str.strip().split()
            if len(parts) < 2:
                return

            method, url = parts[0], parts[1]

            if method == "CONNECT":
                host, port_str = (url.split(":", 1) if ":" in url else (url, "443"))
                port = int(port_str)

                # Drain remaining headers
                while True:
                    line = await client_reader.readline()
                    if line in (b"\r\n", b"\n", b""):
                        break

                target_ip = await self.resolve_smart(host)

                if self._should_mitm(host):
                    # MITM interception
                    await _mitm_handle(
                        client_reader, client_writer,
                        host, port, target_ip,
                        self.ca_key, self.ca_cert,
                    )
                else:
                    # Plain TCP tunnel
                    try:
                        target_reader, target_writer = await asyncio.open_connection(target_ip, port)
                    except Exception as e:
                        logger.warning(f"TCP tunnel failed to {host}:{port}: {e}")
                        client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                        await client_writer.drain()
                        return

                    client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    await client_writer.drain()

                    await asyncio.gather(
                        pipe_streams(client_reader, target_writer),
                        pipe_streams(target_reader, client_writer),
                        return_exceptions=True,
                    )

            else:
                # Plain HTTP GET/POST
                parsed = urlparse(url)
                host = parsed.hostname or ""
                port = parsed.port or 80
                target_ip = await self.resolve_smart(host)

                try:
                    target_reader, target_writer = await asyncio.open_connection(target_ip, port)
                except Exception:
                    client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                    await client_writer.drain()
                    return

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
                    return_exceptions=True,
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
        self.server = await asyncio.start_server(self.handle_client, self.host, self.port)
        logger.info(f"Split-Tunnel MITM Proxy on http://{self.host}:{self.port}")

    async def stop(self):
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
    run_proxy_server()
