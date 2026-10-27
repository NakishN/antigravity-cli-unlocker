"""
Cross-platform autostart helpers for the Antigravity guardian service.
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

SERVICE_NAME = "antigravity-unlocker-guardian"
TASK_NAME = "AntigravityUnlockerGuardian"
LAUNCH_AGENT_LABEL = "com.antigravity.unlocker.guardian"


def guardian_unit_problem():
    """Describe why an installed guardian cannot run, or None when it can.

    Distinguishes three states that look identical from the outside - the unit
    file exists, agy is patched right now, and no guardian process is running:
    the unit is crash-looping.  ``systemctl is-active`` answers ``activating`` or
    ``auto-restart`` for a unit that keeps dying, which no "is it enabled?"
    check can see.

    Lives here rather than in ``doctor`` because ``install_autostart`` needs the
    same answer in order to stop reporting a successful install for a unit that
    never started.
    """
    if platform.system() != "Linux":
        return None

    unit = f"{SERVICE_NAME}.service"
    try:
        result = _run_command(
            ["systemctl", "--user", "is-active", unit], check=False
        )
    except Exception:
        return None

    state = (result.stdout or result.stderr or "").strip()
    if state in ("active", ""):
        return None

    # An uninstalled unit is not a problem here; callers have their own
    # "nothing configured" branch.
    try:
        listed = _run_command(
            ["systemctl", "--user", "list-unit-files", unit], check=False
        ).stdout
    except Exception:
        listed = ""
    if unit not in (listed or ""):
        return None

    return f"systemd reports '{state}' for {unit}"


def runtime_dir():
    """The dedicated, stable Python environment the guardian is meant to run in.

    Kept inside the app dir rather than in the user's temporary files: a guardian
    that points at /tmp has silently stopped existing after a reboot or a cache
    sweep, which looks exactly like the guardian not running at all.
    """
    from antigravity_unlock.patcher import get_app_dir

    return os.path.join(get_app_dir(), "runtime")


def _venv_python(target):
    """The interpreter path inside a venv, on POSIX and Windows."""
    if sys.platform.startswith("win"):
        return os.path.join(target, "Scripts", "python.exe")
    return os.path.join(target, "bin", "python")


def runtime_python():
    """Path to the runtime interpreter, or None when it is not set up."""
    target = runtime_dir()
    if sys.platform.startswith("win"):
        candidate = _venv_python(target)
        return candidate if os.path.exists(candidate) else None
    for name in ("python", "python3"):
        candidate = os.path.join(target, "bin", name)
        if os.path.exists(candidate):
            return candidate
    return None


def resolve_guardian_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "guardian"]

    unlock_bin = shutil.which("antigravity-unlock")
    if unlock_bin:
        return [unlock_bin, "guardian"]

    # Prefer the dedicated runtime over whatever interpreter invoked this
    # command.  Falling back to sys.executable is the trap that produced a
    # 137-restart crash loop: an interactive shell inside the source checkout
    # can import the package, while the same command run by systemd with
    # cwd=$HOME cannot.
    runtime = runtime_python()
    if runtime:
        return [runtime, "-m", "antigravity_unlock", "guardian"]

    return [sys.executable, "-m", "antigravity_unlock", "guardian"]


def _format_exec_command(command):
    return " ".join(f'"{part}"' if " " in part else part for part in command)


def _systemd_unit_path():
    return os.path.join(
        os.path.expanduser("~"),
        ".config",
        "systemd",
        "user",
        f"{SERVICE_NAME}.service",
    )


def _launch_agent_path():
    return os.path.join(
        os.path.expanduser("~"),
        "Library",
        "LaunchAgents",
        f"{LAUNCH_AGENT_LABEL}.plist",
    )


def render_systemd_unit(command):
    exec_start = _format_exec_command(command)
    return f"""[Unit]
Description=Antigravity CLI Version Guardian
After=network-online.target
# An unimportable package makes ExecStart fail instantly.  With a plain
# Restart=always that becomes a 15s loop forever - observed here at 137 restarts
# - and the install looks healthy the whole time because the unit is present and
# enabled.  Bounding it turns the silent failure into a stopped unit, which
# `doctor` reports.
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStart={exec_start}
Restart=always
RestartSec=15

[Install]
WantedBy=default.target
"""


def render_launch_agent_plist(command):
    args_xml = "\n".join(
        f"        <string>{escape(part)}</string>" for part in command
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCH_AGENT_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{escape(os.path.join(os.path.expanduser('~'), '.local', 'share', 'antigravity-unlocker', 'guardian.stdout.log'))}</string>
    <key>StandardErrorPath</key>
    <string>{escape(os.path.join(os.path.expanduser('~'), '.local', 'share', 'antigravity-unlocker', 'guardian.stderr.log'))}</string>
</dict>
</plist>
"""


def ensure_runtime():
    """Make sure the dedicated runtime exists and can import this package.

    Creates the venv and drops a `.pth` pointing at this source tree into it.
    Deliberately does not pip-install the project: the package is pure stdlib,
    and installing it would need setuptools on the machine, a writable
    site-packages (PEP 668 blocks that on Debian/Ubuntu by default), or network
    access for pip.  The `.pth` achieves the same import from any cwd with
    none of those.

    Returns ``(path, note)``; *note* is a human-readable line to show when
    something had to be created or is still wrong.
    """
    target = runtime_dir()
    note = ""

    python = _venv_python(target)
    if not os.path.exists(python):
        os.makedirs(target, exist_ok=True)
        created = _create_venv(target)
        if not created:
            return None, (
                f"could not create a runtime in {target}. Install the package "
                f"system-wide instead, or the guardian unit will not start."
            )
        note = f"created guardian runtime: {target}"

    # Locate site-packages for whatever base interpreter the venv was built on.
    try:
        proc = subprocess.run(
            [python, "-c",
             "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        purelib = (proc.stdout or "").strip()
    except Exception:
        purelib = ""
    if not purelib:
        return python, note

    source_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pth = os.path.join(purelib, "antigravity_unlock.pth")
    try:
        os.makedirs(purelib, exist_ok=True)
        current = ""
        if os.path.exists(pth):
            with open(pth, encoding="utf-8") as f:
                current = f.read().strip()
        if current != source_root:
            with open(pth, "w", encoding="utf-8") as f:
                f.write(source_root + "\n")
            if current:
                note = (note + "\n" if note else "") + f"updated import path in {pth}"
    except OSError as e:
        return python, (note + "\n" if note else "") + f"could not write {pth}: {e}"

    return python, note


def _create_venv(target):
    """Create a virtualenv at *target*, preferring whatever interpreter works."""
    candidates = []
    if shutil.which("uv"):
        candidates.append([shutil.which("uv"), "venv", target])
    base = sys.executable
    if base:
        candidates.append([base, "-m", "venv", target])

    for command in candidates:
        try:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=180, check=False,
            )
        except Exception:
            continue
        if proc.returncode == 0 and os.path.exists(_venv_python(target)):
            return True
    return False


def _package_importable(python=None):
    """True when *python* can ``import antigravity_unlock``.

    The guardian unit runs unattended under ``Restart=always``.  If the ExecStart
    command cannot import the package it dies instantly and systemd retries
    every 15s forever, which is what happened here: the unit said
    ``ExecStart=/usr/bin/python3 -m antigravity_unlock guardian`` while the
    package lived only in a source checkout on ``sys.path`` for interactive use.
    The symptom is an install that *looks* protected - the unit is present and
    enabled - while nothing is actually watching agy, and the crash loop buries
    the real error in ``journalctl``.

    Returns ``(ok, reason)``; *reason* is the interpreter's own message, because
    that is what tells the user which python is missing the package.
    """
    interpreter = python or sys.executable
    # Run the probe from a directory that is not the checkout.  Inheriting the
    # caller's cwd made this return True whenever the user happened to be inside
    # the source tree - which is exactly the case where the systemd unit still
    # fails, because systemd runs the unit with cwd=$HOME.  A probe that is easy
    # to pass by accident is worse than none.
    probe_dir = tempfile.gettempdir()
    try:
        proc = subprocess.run(
            [interpreter, "-c", "import antigravity_unlock"],
            capture_output=True, text=True, timeout=15, check=False, cwd=probe_dir,
        )
    except Exception as e:  # noqa: BLE001 - any failure means "cannot verify"
        return False, str(e)
    if proc.returncode == 0:
        return True, ""
    output = (proc.stderr or proc.stdout or "").strip()
    reason = output.splitlines()[-1] if output else "import failed"
    return False, reason


def _verify_command(command):
    """Best-effort check that *command* actually runs.

    A guard only, never a blocker: the caller still reports what it installed,
    and a false negative here would be worse than the bug it prevents.  Only
    the ``-m`` form is verified, because that is the one that depends on the
    interpreter being able to import the package.
    """
    if "-m" not in command:
        return None
    ok, reason = _package_importable(command[0])
    if ok:
        return None
    return (
        f"warning: {command[0]} cannot import antigravity_unlock ({reason}). "
        f"The guardian unit would restart-loop without ever protecting agy. "
        f"Install the package for that interpreter "
        f"(python3 -m pip install --user .) or remove the autostart entry."
    )


def _run_command(command, check=False):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())
    return result


def install_autostart():
    command = resolve_guardian_command()
    system = platform.system()

    if system == "Linux":
        runtime, note = ensure_runtime()
        messages = [m for m in (note, _verify_command(command)) if m]

        # Re-resolve only if the runtime was created just now; an existing one
        # was already preferred by resolve_guardian_command().
        if runtime and "-m" in command and command[0] != runtime:
            command = [runtime, "-m", "antigravity_unlock", "guardian"]
            messages.append(_verify_command(command))

        unit_path = _systemd_unit_path()
        os.makedirs(os.path.dirname(unit_path), exist_ok=True)
        with open(unit_path, "w", encoding="utf-8") as f:
            f.write(render_systemd_unit(command))

        _run_command(["systemctl", "--user", "daemon-reload"])

        # A unit that has already burned through its start limit refuses to start
        # until the counter is cleared, so reinstalling over a broken unit without
        # this leaves it dead.  Measured 2026-10-07: the unit was rewritten
        # correctly and still would not come up.
        _run_command(["systemctl", "--user", "reset-failed", f"{SERVICE_NAME}.service"])

        enable = _run_command(["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.service"])
        if enable.returncode != 0:
            return False, enable.stderr.strip() or enable.stdout.strip()

        message = f"Installed systemd user service: {unit_path}"

        # `systemctl enable --now` exits 0 even when the unit fails immediately, so
        # its exit status cannot be trusted to mean "running".  Verified on this
        # machine: the command printed a job failure and returned 0, which made
        # install report success for a unit that had never run.  Ask systemd
        # directly instead.
        problem = guardian_unit_problem()
        if problem:
            detail = (
                f"but the unit is not running: {problem}. The patch will be wiped by "
                f"the next agy self-update and nothing will put it back. Check "
                f"'journalctl --user -u {SERVICE_NAME}.service -n 30'."
            )
            return False, "\n".join([message, *messages, detail])

        return True, "\n".join([message, *messages]) if messages else message

    if system == "Darwin":
        plist_path = _launch_agent_path()
        os.makedirs(os.path.dirname(plist_path), exist_ok=True)
        with open(plist_path, "w", encoding="utf-8") as f:
            f.write(render_launch_agent_plist(command))

        uid = os.getuid()
        _run_command(["launchctl", "bootout", f"gui/{uid}", plist_path])
        load = _run_command(["launchctl", "bootstrap", f"gui/{uid}", plist_path])
        if load.returncode != 0:
            return False, load.stderr.strip() or load.stdout.strip()
        return True, f"Installed launchd agent: {plist_path}"

    if system == "Windows":
        exe, arg = command[0], " ".join(command[1:])
        create = [
            "schtasks",
            "/Create",
            "/F",
            "/TN",
            TASK_NAME,
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/TR",
            f"\"{exe}\" {arg}",
        ]
        result = _run_command(create)
        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip()
        _run_command(["schtasks", "/Run", "/TN", TASK_NAME])
        return True, f"Installed scheduled task: {TASK_NAME}"

    return False, f"Unsupported platform: {system}"


def remove_autostart():
    system = platform.system()

    if system == "Linux":
        unit_path = _systemd_unit_path()
        _run_command(["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.service"])
        if os.path.exists(unit_path):
            os.remove(unit_path)
        _run_command(["systemctl", "--user", "daemon-reload"])
        return True, "Removed systemd user service"

    if system == "Darwin":
        plist_path = _launch_agent_path()
        uid = os.getuid()
        _run_command(["launchctl", "bootout", f"gui/{uid}", plist_path])
        if os.path.exists(plist_path):
            os.remove(plist_path)
        return True, "Removed launchd agent"

    if system == "Windows":
        result = _run_command(["schtasks", "/Delete", "/F", "/TN", TASK_NAME])
        if result.returncode != 0 and "cannot find" not in (result.stderr or "").lower():
            return False, result.stderr.strip() or result.stdout.strip()
        return True, "Removed scheduled task"

    return False, f"Unsupported platform: {system}"


def autostart_status():
    system = platform.system()
    command = resolve_guardian_command()

    if system == "Linux":
        unit_path = _systemd_unit_path()
        installed = os.path.exists(unit_path)
        active = False
        detail = ""
        if installed:
            result = _run_command(["systemctl", "--user", "is-active", f"{SERVICE_NAME}.service"])
            active = result.returncode == 0
            detail = (result.stdout or result.stderr or "").strip()
        return {
            "platform": system,
            "installed": installed,
            "active": active,
            "path": unit_path,
            "command": command,
            "detail": detail,
        }

    if system == "Darwin":
        plist_path = _launch_agent_path()
        installed = os.path.exists(plist_path)
        return {
            "platform": system,
            "installed": installed,
            "active": installed,
            "path": plist_path,
            "command": command,
            "detail": "launchd agent file present" if installed else "not installed",
        }

    if system == "Windows":
        result = _run_command(["schtasks", "/Query", "/TN", TASK_NAME])
        installed = result.returncode == 0
        return {
            "platform": system,
            "installed": installed,
            "active": installed,
            "path": TASK_NAME,
            "command": command,
            "detail": (result.stdout or result.stderr or "").strip(),
        }

    return {
        "platform": system,
        "installed": False,
        "active": False,
        "path": "",
        "command": command,
        "detail": "unsupported platform",
    }
