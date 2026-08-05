"""
Run-Wrapped Process Manager.
Launches a local Split-Tunnel proxy and executes agy in a sandboxed proxy environment.
"""

import sys
import os
import time
import socket
import threading
import subprocess

from .discovery import get_primary_agy
from .patcher import patch_binary
from .proxy import SplitTunnelProxy, run_proxy_server

def find_free_port():
    """Finds an available local port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def run_wrapped_command(cmd_args, agy_path=None, auto_patch=True):
    """
    Spawns local proxy, sets environment variables, runs child process, and cleans up.
    """
    if not agy_path:
        agy_path = get_primary_agy()

    if not agy_path or not os.path.exists(agy_path):
        print("Error: Antigravity CLI (agy) binary not found on system.", file=sys.stderr)
        return 1

    if auto_patch:
        patch_binary(agy_path, dry_run=False)

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

    # Copy environment and inject local proxy vars ONLY for child process
    env = os.environ.copy()
    env["HTTP_PROXY"] = proxy_url
    env["HTTPS_PROXY"] = proxy_url
    env["http_proxy"] = proxy_url
    env["https_proxy"] = proxy_url

    full_cmd = [agy_path] + cmd_args

    try:
        proc = subprocess.run(full_cmd, env=env)
        return proc.returncode
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Execution error: {e}", file=sys.stderr)
        return 1
