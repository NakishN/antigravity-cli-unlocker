"""
Run-Wrapped Process Manager.
Launches agy with:
  - Binary patches applied
  - Local Split-Tunnel proxy for Smart DNS
  - LD_PRELOAD DNS shim for SNI proxy fallback (geohide.ru)
"""

import sys
import os
import time
import socket
import threading
import subprocess
import logging

from antigravity_unlock.discovery import get_primary_agy
from antigravity_unlock.pinner import enforce_strategy
from antigravity_unlock.proxy import run_proxy_server
from antigravity_unlock.shim_builder import ensure_shim

logger = logging.getLogger("antigravity_runner")


def find_free_port():
    """Finds an available local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run_wrapped_command(cmd_args, agy_path=None, auto_patch=True, strategy=None):
    """
    Spawns local proxy, sets environment variables, runs child process, and cleans up.

    Three layers of region bypass:
      1. Binary patches (client-side eligibility checks)
      2. Split-tunnel proxy (Smart DNS for supported providers)
      3. LD_PRELOAD DNS shim (SNI proxy fallback for model calls that bypass HTTPS_PROXY)
    """
    if not agy_path:
        agy_path = get_primary_agy()

    if not agy_path or not os.path.exists(agy_path):
        print("Error: Antigravity CLI (agy) binary not found on system.", file=sys.stderr)
        return 1

    if auto_patch:
        enforce_strategy(agy_path=agy_path, strategy=strategy)

    port = find_free_port()

    # Start proxy in background daemon thread
    proxy_thread = threading.Thread(
        target=run_proxy_server,
        kwargs={"host": "127.0.0.1", "port": port},
        daemon=True
    )
    proxy_thread.start()
    time.sleep(0.3)  # Allow server to bind

    proxy_url = f"http://127.0.0.1:{port}"

    daily_endpoint = "https://daily-cloudcode-pa.googleapis.com"

    # Copy environment and inject vars ONLY for child process
    env = os.environ.copy()
    env["HTTP_PROXY"] = proxy_url
    env["HTTPS_PROXY"] = proxy_url
    env["http_proxy"] = proxy_url
    env["https_proxy"] = proxy_url
    env["CLOUD_CODE_URL"] = daily_endpoint

    # Force HTTP/1.1: the geohide SNI proxy (45.155.204.190) does not support
    # HTTP/2 ALPN negotiation.  Go's HTTP client defaults to HTTP/2 and hangs
    # waiting for the ALPN handshake.  This flag forces HTTP/1.1, which the
    # SNI proxy handles correctly.
    existing_godebug = env.get("GODEBUG", "")
    if "http2client=0" not in existing_godebug:
        env["GODEBUG"] = f"{existing_godebug},http2client=0" if existing_godebug else "http2client=0"

    # DNS shim: LD_PRELOAD redirects Google API DNS to geohide SNI proxy.
    # This is a secondary mechanism for hosts pinning.  The primary mechanism
    # is /etc/hosts entries added by `unlocker setup`.  The shim provides
    # the same redirection without root privileges.
    try:
        shim_path = ensure_shim()
        existing_preload = env.get("LD_PRELOAD", "")
        if existing_preload:
            env["LD_PRELOAD"] = f"{shim_path}:{existing_preload}"
        else:
            env["LD_PRELOAD"] = shim_path
        if "netdns=cgo" not in env.get("GODEBUG", ""):
            env["GODEBUG"] = env.get("GODEBUG", "") + ",netdns=cgo"
        logger.info(f"DNS shim loaded: {shim_path}")
    except Exception as e:
        logger.debug(f"DNS shim not available: {e}")

    full_cmd = [agy_path] + cmd_args

    try:
        proc = subprocess.run(full_cmd, env=env)
        return proc.returncode
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Execution error: {e}", file=sys.stderr)
        return 1
