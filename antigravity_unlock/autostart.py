"""
Cross-platform autostart helpers for the Antigravity guardian service.
"""

import os
import platform
import shutil
import subprocess
import sys
from xml.sax.saxutils import escape

SERVICE_NAME = "antigravity-unlocker-guardian"
TASK_NAME = "AntigravityUnlockerGuardian"
LAUNCH_AGENT_LABEL = "com.antigravity.unlocker.guardian"


def resolve_guardian_command():
    if getattr(sys, "frozen", False):
        return [sys.executable, "guardian"]

    unlock_bin = shutil.which("antigravity-unlock")
    if unlock_bin:
        return [unlock_bin, "guardian"]

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


def _run_command(command, check=False):
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())
    return result


def install_autostart():
    command = resolve_guardian_command()
    system = platform.system()

    if system == "Linux":
        unit_path = _systemd_unit_path()
        os.makedirs(os.path.dirname(unit_path), exist_ok=True)
        with open(unit_path, "w", encoding="utf-8") as f:
            f.write(render_systemd_unit(command))

        _run_command(["systemctl", "--user", "daemon-reload"])
        enable = _run_command(["systemctl", "--user", "enable", "--now", f"{SERVICE_NAME}.service"])
        if enable.returncode != 0:
            return False, enable.stderr.strip() or enable.stdout.strip()
        return True, f"Installed systemd user service: {unit_path}"

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
