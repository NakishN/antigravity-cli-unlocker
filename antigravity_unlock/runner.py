"""
Run-Wrapped Process Manager.

Ensures the patch is in place, points agy at a working foreign exit when one is
configured, then hands the terminal straight to agy.

The MITM that used to live here is still gone, and should stay gone.  Before
1.5.0 this module started a local split-tunnel proxy, LD_PRELOADed a DNS shim
and forced ``GODEBUG=http2client=0`` so that model calls would reach Google
through a third-party SNI proxy.  That front end stopped completing TLS
handshakes, and it was never what unlocked Antigravity: the eligibility gate is
a client-side check over a server-supplied protobuf field, and renaming that
field is sufficient for it.

What was missing is the *other* gate.  Google also checks the source IP of the
request server-side and answers ``FAILED_PRECONDITION (400): User location is
not supported for the API use`` from a blocked region - a string that occurs
nowhere in the binary, so no patch can remove it.  Measured 2026-09-27 on one
patched binary and one account: RU egress -> 400 every call; the same binary
through a SOCKS5 exit in Amsterdam -> a real completion.  So an exit in a
supported region is required, and ``egress`` supplies one.

The difference from the deleted layer is that nothing here sits in the request
path.  There is no local listener, no TLS termination and no substituted DNS:
agy is handed a proxy URL in its environment and talks to Google's real address
itself.  The environment is built per-process, so git, curl and package
managers in the same shell are untouched.

agy is a full-screen TUI, so on POSIX we ``exec`` it rather than spawning a
child: the wrapper process disappears, and signals, terminal size changes and
the controlling TTY go to agy directly instead of being relayed.
"""

import os
import sys
import subprocess

from antigravity_unlock.config import load_config
from antigravity_unlock.discovery import get_primary_agy
from antigravity_unlock.dnspin import pin_ips, start_proxy as start_dnspin_proxy
from antigravity_unlock.egress import active_route, build_child_env
from antigravity_unlock.logging_utils import get_logger
from antigravity_unlock.pinner import enforce_strategy

logger = get_logger("antigravity_runner")


def _egress_env(agy_path):
    """Resolve the exit for this launch.

    Returns ``(env, route, warning)``.  ``env`` is None to inherit ours
    unchanged, ``route`` is the route dict actually selected, and ``warning`` is
    a line for stderr explaining why we are running direct when the user asked
    us not to.  Being silently unproxied is exactly the kind of thing that
    should never be silent: from a blocked region it looks identical to a
    working install right up to the first 400.
    """
    cfg = load_config()
    route = active_route(cfg, agy_path=agy_path)
    if route is not None:
        return build_child_env(route, agy_path=agy_path), route, None

    if cfg.get("egress_enabled"):
        if not cfg.get("egress_routes"):
            return None, None, (
                "egress routing is enabled but no routes are configured; running "
                "direct. Add one with: antigravity-unlock egress add warp"
            )
        return None, None, (
            "egress routing is enabled but no route is selected; running direct. "
            "Measure them with: antigravity-unlock egress test"
        )
    return None, None, None


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

    env, route, warning = None, None, None
    dnspin_proxy = None
    cfg = load_config()

    # DNS pin is the lightest no-VPN exit: it needs no route URL and no user
    # setup beyond one command.  It wins over configured egress routes because
    # enabling it is an explicit choice; if it cannot find a live relay we fall
    # back to the normal egress logic rather than running blind.
    if cfg.get("dnspin_enabled"):
        print("dnspin: resolving public unblock-DNS relays...", file=sys.stderr)
        try:
            dnspin_proxy = start_dnspin_proxy(
                refresh_seconds=int(cfg.get("dnspin_refresh_seconds", 300) or 300)
            )
        except Exception as e:  # noqa: BLE001 - a failed pin must not block agy
            print(f"Warning: dnspin could not start: {e}", file=sys.stderr)
            dnspin_proxy = None
        if dnspin_proxy is not None:
            chosen = pin_ips(dnspin_proxy.status) if dnspin_proxy.status else dict(dnspin_proxy.pinned)
            if any(chosen.values()):
                route = {"label": "dnspin", "url": f"http://127.0.0.1:{dnspin_proxy.port}"}
                env = build_child_env(route, agy_path=agy_path)
                summary = ", ".join(
                    f"{host.split('.')[0]}={ips[0]}" for host, ips in chosen.items() if ips
                )
                print(f"Egress: dnspin -> {summary}", file=sys.stderr)
            else:
                print("Warning: dnspin found no live relay; falling back to the normal path.",
                      file=sys.stderr)
                dnspin_proxy.stop()
                dnspin_proxy = None

    if dnspin_proxy is None:
        env, route, warning = _egress_env(agy_path)
        if route is not None:
            logger.info("Egress route: %s", route["label"])
            print(f"Egress: {route['label']} -> {route['url']}", file=sys.stderr)
        elif warning:
            print(f"Warning: {warning}", file=sys.stderr)

    full_cmd = [agy_path] + list(cmd_args)

    if dnspin_proxy is not None:
        # A thread-local proxy cannot survive execve; keep the wrapper alive for
        # the duration of agy and stop the proxy afterwards.
        try:
            return subprocess.run(full_cmd, env=env).returncode
        except KeyboardInterrupt:
            return 130
        except Exception as e:
            print(f"Execution error: {e}", file=sys.stderr)
            return 1
        finally:
            dnspin_proxy.stop()

    if os.name == "posix":
        try:
            if env is None:
                os.execv(agy_path, full_cmd)
            os.execve(agy_path, full_cmd, env)
        except OSError as e:
            print(f"Execution error: {e}", file=sys.stderr)
            return 1
        return 1  # unreachable: execv does not return on success

    try:
        return subprocess.run(full_cmd, env=env).returncode
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"Execution error: {e}", file=sys.stderr)
        return 1

