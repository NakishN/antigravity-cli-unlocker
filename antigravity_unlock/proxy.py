"""
Split-Tunnel Local Proxy Server for Antigravity CLI.
Routes accounts.google.com DIRECTLY and generativelanguage.googleapis.com via Smart Endpoint.
"""

import sys
import asyncio
import logging
import socket
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
}

# Upstream Smart DNS server for AI endpoints
SMART_DNS_PRIMARY = "111.88.96.50"
SMART_DNS_SECONDARY = "111.88.96.51"

async def pipe_streams(reader, writer):
    """Pipes bytes continuously between reader and writer."""
    try:
        while not reader.at_eof():
            data = await reader.read(8192)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (asyncio.CancelledError, ConnectionResetError, OSError):
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

    async def resolve_smart(self, hostname):
        """Resolves hostname using Smart DNS IP if needed, or falls back to system DNS."""
        if any(hostname == d or hostname.endswith("." + d) for d in DIRECT_DOMAINS):
            # Direct system DNS resolution
            return hostname
        # For googleapis.com, send through Smart DNS endpoint / IP
        return self.smart_ip if hostname.endswith("googleapis.com") else hostname

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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
    run_proxy_server()
