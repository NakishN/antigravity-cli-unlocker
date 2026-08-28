"""
IPv4 priority management.

On many ISPs in blocked regions, IPv6 is either broken or significantly
slower than IPv4 (timeouts, black-holed routes).  Prioritising IPv4 over
IPv6 avoids these issues when the machine has no usable global IPv6
address.

The check and apply functions are safe to call repeatedly: they detect
the current state and skip the write when nothing needs to change.
"""

import os
import platform
import socket
import subprocess


def has_global_ipv6():
    """True if this machine has at least one global (non-link-local) IPv6 address."""
    if platform.system() != "Linux":
        return False
    try:
        result = subprocess.run(
            ["ip", "-6", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _read_sysctl(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def ipv4_preferred():
    """True if the system currently prefers IPv4 over IPv6."""
    system = platform.system()
    if system == "Linux":
        val = _read_sysctl("/proc/sys/net/ipv6/conf/all/disable_ipv6")
        if val == "1":
            return True
        # gai.conf precedence: higher value = higher priority.
        # Default is 35 for ::ffff:0:0/96; 46 would put IPv4 above native v6.
        try:
            with open("/etc/gai.conf") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("label") and "::ffff:0:0/96" in line:
                        parts = line.split()
                        if len(parts) >= 4:
                            return int(parts[3]) > 35
        except OSError:
            pass
        return False
    return False


def apply_ipv4_priority():
    """Ensure IPv4 is preferred when no global IPv6 is available.

    Returns ``(applied: bool, message: str)``.
    """
    system = platform.system()

    if system != "Linux":
        return False, f"IPv4 priority not implemented for {system}"

    if has_global_ipv6():
        return False, "Global IPv6 detected — leaving default priority"

    if ipv4_preferred():
        return True, "IPv4 already preferred"

    # Write a gai.conf rule that raises IPv4-mapped prefix precedence.
    gai_conf = "/etc/gai.conf"
    marker = "# antigravity-unlocker: prefer IPv4"
    rule = "label  ::ffff:0:0/96   2"
    precedence = "precedence  ::ffff:0:0/96  46"

    try:
        existing = ""
        if os.path.isfile(gai_conf):
            with open(gai_conf) as f:
                existing = f.read()

        if marker in existing:
            return True, "IPv4 priority already configured in gai.conf"

        with open(gai_conf, "a") as f:
            f.write(f"\n{marker}\n{precedence}\n{rule}\n")

        return True, "IPv4 priority applied to /etc/gai.conf"
    except PermissionError:
        return False, "Permission denied — run with sudo to apply IPv4 priority"
    except Exception as e:
        return False, f"Failed to write {gai_conf}: {e}"


def remove_ipv4_priority():
    """Remove the IPv4 priority rule added by this tool.

    Returns ``(removed: bool, message: str)``.
    """
    system = platform.system()
    if system != "Linux":
        return False, f"Not applicable on {system}"

    gai_conf = "/etc/gai.conf"
    marker = "# antigravity-unlocker: prefer IPv4"

    try:
        if not os.path.isfile(gai_conf):
            return False, f"{gai_conf} does not exist"

        with open(gai_conf) as f:
            lines = f.readlines()

        new_lines = []
        skip_next = 0
        changed = False
        for line in lines:
            if skip_next > 0:
                skip_next -= 1
                changed = True
                continue
            if marker in line:
                skip_next = 2  # skip the two rule lines after the marker
                changed = True
                continue
            new_lines.append(line)

        if not changed:
            return False, "No IPv4 priority rule found"

        with open(gai_conf, "w") as f:
            f.writelines(new_lines)

        return True, "IPv4 priority rule removed from /etc/gai.conf"
    except PermissionError:
        return False, "Permission denied — run with sudo"
    except Exception as e:
        return False, f"Failed: {e}"
