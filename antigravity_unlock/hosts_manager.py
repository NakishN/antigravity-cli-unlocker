"""
Manages /etc/hosts entries for SNI proxy pinning.
Pins Google API domains to geohide.ru SNI proxy IPs to bypass
server-side region checks (FAILED_PRECONDITION).
"""

import os
import logging
import re

logger = logging.getLogger("antigravity_hosts")

HOSTS_PATH = "/etc/hosts"
MARKER_BEGIN = "# === antigravity-unlocker SNI proxy pin ==="
MARKER_END = "# === end antigravity-unlocker SNI proxy pin ==="

# Geohide.ru SNI proxy IPs (verified TLS + HTTP, 2026-08-28)
PROXY_IPS = {
    "45.155.204.190": [
        "daily-cloudcode-pa.googleapis.com",
        "cloudcode-pa.googleapis.com",
        "generativelanguage.googleapis.com",
    ],
}


def _read_hosts() -> str:
    try:
        with open(HOSTS_PATH, "r") as f:
            return f.read()
    except PermissionError:
        raise PermissionError(f"Need root to read {HOSTS_PATH}. Run with sudo.")


def _write_hosts(content: str):
    try:
        with open(HOSTS_PATH, "w") as f:
            f.write(content)
    except PermissionError:
        raise PermissionError(f"Need root to write {HOSTS_PATH}. Run with sudo.")


def is_pinned() -> bool:
    """True if our hosts block is present."""
    try:
        return MARKER_BEGIN in _read_hosts()
    except Exception:
        return False


def _build_block() -> str:
    lines = [MARKER_BEGIN]
    for ip, domains in PROXY_IPS.items():
        for domain in domains:
            lines.append(f"{ip} {domain}")
    lines.append(MARKER_END)
    return "\n".join(lines) + "\n"


def _remove_block(content: str) -> str:
    pattern = re.compile(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


def pin():
    """Adds SNI proxy entries to /etc/hosts. Idempotent."""
    content = _read_hosts()
    content = _remove_block(content)  # remove stale block if any
    block = _build_block()
    if not content.endswith("\n"):
        content += "\n"
    content += block
    _write_hosts(content)
    logger.info("Hosts pinned: SNI proxy entries added")


def unpin():
    """Removes our entries from /etc/hosts."""
    content = _read_hosts()
    content = _remove_block(content)
    _write_hosts(content)
    logger.info("Hosts unpinned: SNI proxy entries removed")
