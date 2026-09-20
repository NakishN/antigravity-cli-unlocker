"""
Run-Wrapped Process Manager.

Ensures the patch is in place, then hands the terminal straight to agy.

This used to also start a local split-tunnel proxy, LD_PRELOAD a DNS shim and
force ``GODEBUG=http2client=0`` so that model calls would reach Google through an
SNI proxy.  That whole layer is gone: the proxy route died (the SNI front end
stopped completing TLS handshakes), and it turned out never to have been the
thing that unlocked Antigravity.  The eligibility gate is a client-side check over
a server-supplied protobuf field, and renaming that field is sufficient -
verified end to end on agy 1.2.7 with a plain Russian egress IP and no proxy of
any kind.  What was left was a MITM in the request path, an HTTP/1.1 downgrade
and a hard dependency on a third-party IP that could vanish at any time.

agy is a full-screen TUI, so on POSIX we ``exec`` it rather than spawning a
child: the wrapper process disappears, and signals, terminal size changes and
the controlling TTY go to agy directly instead of being relayed.
"""

import os
import sys
import subprocess

from antigravity_unlock.discovery import get_primary_agy
from antigravity_unlock.logging_utils import get_logger
from antigravity_unlock.pinner import enforce_strategy

logger = get_logger("antigravity_runner")


def run_wrapped_command(cmd_args, agy_path=None, auto_patch=True, strategy=None,
                        include_optional=False):
    """Patch agy if needed, then run it with *cmd_args*.

    Returns the child's exit code (or never returns at all on POSIX, where the
    process image is replaced).
    """
    if not agy_path:
        agy_path = get_primary_agy()

    if not agy_path or not os.path.exists(agy_path):
        print("Error: Antigravity CLI (agy) binary not found on system.", file=sys.stderr)
        return 1

    if auto_patch:
        ok, msg, changed = enforce_strategy(
            agy_path=agy_path, strategy=strategy, include_optional=include_optional
        )
        if changed:
            logger.info("Pre-run patch: %s", msg)
        elif not ok:
            # Not fatal: agy may still work, and refusing to launch would leave
            # the user with nothing to look at.  Say why, then run it.
            print(f"Warning: {msg}", file=sys.stderr)

    full_cmd = [agy_path] + list(cmd_args)

    if os.name == "posix":
        try:
            os.execv(agy_path, full_cmd)
        except OSError as e:
            print(f"Execution error: {e}", file=sys.stderr)
            return 1
        return 1  # unreachable: execv does not return on success

    try:
        return subprocess.run(full_cmd).returncode
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Execution error: {e}", file=sys.stderr)
        return 1
