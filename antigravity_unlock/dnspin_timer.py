"""
Root timer that keeps the dnspin ``/etc/hosts`` pin fresh.

The pin is the only dnspin mode that makes a *bare* ``agy`` use the relays, and
it needs root once.  Its weakness is that the public unblock-DNS providers
rotate their relay addresses: the pin that worked last week points at a dead
host today, and the user has to notice and run ``sudo ... dnspin pin-hosts``
again.  This module installs a root-level timer that runs
``antigravity-unlock dnspin sync-hosts`` periodically, so the pin repairs itself.

Platforms:

* Linux - a pair of system units in ``/etc/systemd/system``
  (``antigravity-unlocker-dnspin.service`` + ``.timer``);
* macOS - a launchd daemon in ``/Library/LaunchDaemons``;
* Windows - a Task Scheduler task running as SYSTEM.

All three need elevation: ``sudo`` on POSIX, an administrator shell on Windows.
Nothing here runs as the user, so a package self-update cannot silently stop the
refresh.
"""

import os
import platform
import shutil
import subprocess
import sys
from types import SimpleNamespace
from xml.sax.saxutils import escape

SERVICE_NAME = "antigravity-unlocker-dnspin"
TIMER_NAME = SERVICE_NAME + ".timer"
LAUNCH_DAEMON_LABEL = "com.antigravity.unlocker.dnspin"
TASK_NAME = "AntigravityUnlockerDnspin"

DEFAULT_INTERVAL_SECONDS = 900
MIN_INTERVAL_SECONDS = 300

SYNC_ARGS = ("dnspin", "sync-hosts")


def _run_command(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as e:
        # A missing systemctl/launchctl/schtasks must produce a readable error
        # instead of a traceback from the CLI.
        return SimpleNamespace(returncode=127, stdout="", stderr=str(e))


def _format_exec_command(command):
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def _is_temporary_path(path):
    """True for paths that do not survive the command that produced them.

    An AppImage is mounted under ``/tmp/.mount_<random>`` and a PyInstaller
    onefile unpacks itself under ``/tmp/_MEI<random>``.  A systemd unit pointing
    there is a time bomb: it works until the next reboot.
    """
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith("/tmp/.mount_")
        or "/_MEI" in normalized
        or normalized.startswith("/tmp/_MEI")
    )


def resolve_cli_command(argv0=None):
    """Return a stable command that runs ``dnspin sync-hosts``, or None.

    The timer runs outside the user's shell with a minimal PATH and no
    ``~/.local/bin``, which is why the hint in ``pin-hosts`` has to spell out the
    full path.  The same applies here, so the path is resolved *before* the unit
    is written and never through the root's PATH when a stable one is known.
    """
    appimage = os.environ.get("APPIMAGE")
    if appimage and os.path.isfile(appimage) and not _is_temporary_path(appimage):
        return [os.path.abspath(appimage), *SYNC_ARGS]

    if getattr(sys, "frozen", False):
        executable = os.path.abspath(sys.executable)
        if _is_temporary_path(executable):
            return None
        return [executable, *SYNC_ARGS]

    argv0 = sys.argv[0] if argv0 is None else argv0
    candidate = ""
    if argv0:
        candidate = argv0 if os.path.isabs(argv0) else (shutil.which(argv0) or "")
        candidate = os.path.abspath(candidate) if candidate else ""
    if (
        candidate
        and os.path.isfile(candidate)
        and not candidate.endswith(".py")
        and os.access(candidate, os.X_OK)
        and not _is_temporary_path(candidate)
    ):
        return [candidate, *SYNC_ARGS]

    found = shutil.which("antigravity-unlock")
    if found:
        found = os.path.abspath(found)
        if not _is_temporary_path(found):
            return [found, *SYNC_ARGS]

    return [sys.executable, "-m", "antigravity_unlock", *SYNC_ARGS]


def _systemd_dir():
    return "/etc/systemd/system"


def _systemd_service_path():
    return os.path.join(_systemd_dir(), f"{SERVICE_NAME}.service")


def _systemd_timer_path():
    return os.path.join(_systemd_dir(), TIMER_NAME)


def _launch_daemon_path():
    return os.path.join("/Library/LaunchDaemons", f"{LAUNCH_DAEMON_LABEL}.plist")


def clamp_interval(interval):
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, interval)


def render_systemd_service(command):
    return f"""[Unit]
Description=Antigravity Unlocker dnspin hosts pin refresh
Documentation=https://github.com/NakishN/antigravity-cli-unlocker
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
NoNewPrivileges=true
PrivateTmp=true
ExecStart={_format_exec_command(command)}
"""


def render_systemd_timer(interval):
    interval = clamp_interval(interval)
    return f"""[Unit]
Description=Refresh the Antigravity Unlocker dnspin hosts pin

[Timer]
OnBootSec=60s
OnUnitActiveSec={interval}s
RandomizedDelaySec=30s
Persistent=true

[Install]
WantedBy=timers.target
"""


def parse_systemd_interval(content):
    """Read ``OnUnitActiveSec`` back out of a timer unit, for ``status``."""
    import re

    match = re.search(r"^OnUnitActiveSec=(\d+)s\s*$", content or "", re.MULTILINE)
    return int(match.group(1)) if match else None


def render_launch_daemon_plist(command, interval):
    interval = clamp_interval(interval)
    args_xml = "\n".join(
        f"        <string>{escape(part)}</string>" for part in command
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_DAEMON_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>ProcessType</key>
    <string>Background</string>
    <key>StandardOutPath</key>
    <string>/Library/Logs/antigravity-unlocker-dnspin.log</string>
    <key>StandardErrorPath</key>
    <string>/Library/Logs/antigravity-unlocker-dnspin.err.log</string>
</dict>
</plist>
"""


def parse_launch_daemon_interval(content):
    import re

    match = re.search(
        r"<key>StartInterval</key>\s*<integer>(\d+)</integer>", content or ""
    )
    return int(match.group(1)) if match else None


def _windows_task_command(command):
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def _root_problem(action):
    if platform.system() == "Windows":
        # schtasks itself reports the real "access denied" when not elevated.
        return None
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return (
            "need root to manage the system-level refresh timer; run: "
            f"sudo antigravity-unlock dnspin autopin {action}"
        )
    return None


def install_autopin(interval=DEFAULT_INTERVAL_SECONDS, command=None):
    """Install and start the refresh timer.  Returns ``(ok, message)``."""
    interval = clamp_interval(interval)
    problem = _root_problem("install")
    if problem:
        return False, problem

    command = command or resolve_cli_command()
    if not command:
        return False, (
            "cannot determine a stable path to antigravity-unlock: the current "
            "executable lives under a temporary mount (AppImage/PyInstaller). "
            "Re-run with '--cli /path/to/antigravity-unlock' or use the installed "
            "console script."
        )

    system = platform.system()

    if system == "Linux":
        service_path = _systemd_service_path()
        timer_path = _systemd_timer_path()
        os.makedirs(os.path.dirname(service_path), exist_ok=True)
        with open(service_path, "w", encoding="utf-8") as f:
            f.write(render_systemd_service(command))
        with open(timer_path, "w", encoding="utf-8") as f:
            f.write(render_systemd_timer(interval))

        reload = _run_command(["systemctl", "daemon-reload"])
        if reload.returncode != 0:
            return False, reload.stderr.strip() or reload.stdout.strip()

        enable = _run_command(["systemctl", "enable", "--now", TIMER_NAME])
        if enable.returncode != 0:
            return False, enable.stderr.strip() or enable.stdout.strip()

        # Run once now so the pin is repaired immediately; the timer's first
        # OnBootSec/OnUnitActiveSec tick is minutes away.  A failure here is not
        # fatal: the timer retries, and a temporary provider outage must not make
        # the installation look broken.
        first = _run_command(["systemctl", "start", f"{SERVICE_NAME}.service"])
        first_note = ""
        if first.returncode != 0:
            detail = (first.stderr or first.stdout or "").strip()
            first_note = (
                f"\nThe first refresh failed ({detail or 'no output'}); the timer "
                f"will retry every {interval}s."
            )

        active = _run_command(["systemctl", "is-active", TIMER_NAME])
        if active.returncode != 0:
            detail = (active.stdout or active.stderr or "").strip()
            return False, (
                f"installed {timer_path}, but the timer is not active: {detail}. "
                f"Check 'systemctl status {TIMER_NAME}' and "
                f"'journalctl -u {SERVICE_NAME}.service -n 30'."
            )

        return True, (
            f"Installed systemd timer {timer_path} (every {interval}s); "
            f"first refresh {'ok' if not first_note else 'failed'}."
            f"{first_note}"
        )

    if system == "Darwin":
        plist_path = _launch_daemon_path()
        os.makedirs(os.path.dirname(plist_path), exist_ok=True)
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(render_launch_daemon_plist(command, interval))

        _run_command(["launchctl", "bootout", f"system/{LAUNCH_DAEMON_LABEL}"])
        load = _run_command(["launchctl", "bootstrap", "system", plist_path])
        if load.returncode != 0:
            return False, load.stderr.strip() or load.stdout.strip()

        kick = _run_command(
            ["launchctl", "kickstart", "-k", f"system/{LAUNCH_DAEMON_LABEL}"]
        )
        note = ""
        if kick.returncode != 0:
            detail = (kick.stderr or kick.stdout or "").strip()
            note = f"\nThe first refresh failed ({detail or 'no output'}); it will retry."

        active = _run_command(
            ["launchctl", "print", f"system/{LAUNCH_DAEMON_LABEL}"]
        )
        if active.returncode != 0:
            return False, (
                f"installed {plist_path}, but launchd does not report the daemon. "
                f"Check 'launchctl print system/{LAUNCH_DAEMON_LABEL}'."
            )
        return True, f"Installed launchd daemon {plist_path} (every {interval}s).{note}"

    if system == "Windows":
        minutes = max(1, interval // 60)
        create = _run_command([
            "schtasks",
            "/Create",
            "/F",
            "/TN",
            TASK_NAME,
            "/SC",
            "MINUTE",
            "/MO",
            str(minutes),
            "/RU",
            "SYSTEM",
            "/RL",
            "HIGHEST",
            "/TR",
            _windows_task_command(command),
        ])
        if create.returncode != 0:
            detail = create.stderr.strip() or create.stdout.strip()
            return False, (
                f"{detail}\nRun this command from an Administrator PowerShell/cmd."
            )
        _run_command(["schtasks", "/Run", "/TN", TASK_NAME])
        return True, (
            f"Installed scheduled task {TASK_NAME} running as SYSTEM every "
            f"{minutes} minute(s)."
        )

    return False, f"Unsupported platform: {system}"


def remove_autopin():
    """Disable and delete the refresh timer.  Returns ``(ok, message)``."""
    problem = _root_problem("remove")
    if problem:
        return False, problem

    system = platform.system()

    if system == "Linux":
        _run_command(["systemctl", "disable", "--now", TIMER_NAME])
        removed = []
        for path in (_systemd_service_path(), _systemd_timer_path()):
            if os.path.exists(path):
                os.remove(path)
                removed.append(path)
        _run_command(["systemctl", "daemon-reload"])
        if not removed:
            return True, "no refresh timer was installed"
        return True, f"Removed {', '.join(removed)}"

    if system == "Darwin":
        _run_command(["launchctl", "bootout", f"system/{LAUNCH_DAEMON_LABEL}"])
        path = _launch_daemon_path()
        if os.path.exists(path):
            os.remove(path)
            return True, f"Removed {path}"
        return True, "no refresh daemon was installed"

    if system == "Windows":
        result = _run_command(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
        if result.returncode != 0 and "cannot find" not in (result.stderr or "").lower():
            return False, result.stderr.strip() or result.stdout.strip()
        return True, f"Removed scheduled task {TASK_NAME}"

    return False, f"Unsupported platform: {system}"


def autopin_status():
    """Describe the refresh timer without requiring root."""
    system = platform.system()

    if system == "Linux":
        service_path = _systemd_service_path()
        timer_path = _systemd_timer_path()
        installed = os.path.exists(service_path) and os.path.exists(timer_path)
        interval = None
        if os.path.exists(timer_path):
            try:
                with open(timer_path, "r", encoding="utf-8", errors="replace") as f:
                    interval = parse_systemd_interval(f.read())
            except OSError:
                pass
        active = False
        detail = "not installed"
        if installed:
            result = _run_command(["systemctl", "is-active", TIMER_NAME])
            active = result.returncode == 0
            detail = (result.stdout or result.stderr or "").strip()
        return {
            "platform": system,
            "installed": installed,
            "active": active,
            "path": timer_path,
            "interval": interval,
            "detail": detail,
        }

    if system == "Darwin":
        path = _launch_daemon_path()
        installed = os.path.exists(path)
        interval = None
        if installed:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    interval = parse_launch_daemon_interval(f.read())
            except OSError:
                pass
        active = False
        detail = "not installed"
        if installed:
            result = _run_command(["launchctl", "print", f"system/{LAUNCH_DAEMON_LABEL}"])
            active = result.returncode == 0
            detail = "daemon loaded" if active else "daemon not loaded"
        return {
            "platform": system,
            "installed": installed,
            "active": active,
            "path": path,
            "interval": interval,
            "detail": detail,
        }

    if system == "Windows":
        result = _run_command(["schtasks", "/Query", "/TN", TASK_NAME])
        installed = result.returncode == 0
        return {
            "platform": system,
            "installed": installed,
            "active": installed,
            "path": TASK_NAME,
            "interval": None,
            "detail": (result.stdout or result.stderr or "").strip(),
        }

    return {
        "platform": system,
        "installed": False,
        "active": False,
        "path": "",
        "interval": None,
        "detail": "unsupported platform",
    }
