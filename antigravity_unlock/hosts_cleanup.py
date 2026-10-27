"""
Removal-only cleanup for /etc/hosts pins left behind by versions <= 1.4.x.

The SNI-proxy layer is gone in 1.5.0: pinning CloudCode to a third-party IP was
never what unlocked Antigravity, the front end it pointed at stopped completing
TLS handshakes, and a pin silently overrides whatever egress route the machine
already has.  This module exists only so that upgrading does not strand anyone
with entries they can no longer remove - it can read and delete pins, and it
cannot create one.

Two kinds of leftover are handled:

* the marked block written by ``setup apply``;
* bare, unmarked lines written by even older releases, which the old
  ``unpin()`` could not see and which therefore outlived the tool.
"""

import logging
import re

logger = logging.getLogger("antigravity_hosts_cleanup")

HOSTS_PATH = "/etc/hosts"
MARKER_BEGIN = "# === antigravity-unlocker SNI proxy pin ==="
MARKER_END = "# === end antigravity-unlocker SNI proxy pin ==="

# Domains the old pinner redirected.  Hardcoded here rather than derived from a
# proxy table, because the table no longer exists and these strings must keep
# matching whatever is already on disk.
PINNED_DOMAINS = (
    "cloudcode-pa.googleapis.com",
    "daily-cloudcode-pa.googleapis.com",
    "generativelanguage.googleapis.com",
)


def _read_hosts(path=HOSTS_PATH):
    try:
        with open(path, "r") as f:
            return f.read()
    except PermissionError:
        raise PermissionError(f"Need root to read {path}. Run with sudo.")


def _write_hosts(content, path=HOSTS_PATH):
    try:
        with open(path, "w") as f:
            f.write(content)
    except PermissionError:
        raise PermissionError(f"Need root to write {path}. Run with sudo.")


def find_pins(content=None, path=HOSTS_PATH, exclude_blocks=()):
    """Return every pin line, marked or not, as ``(lineno, line, marked)``.

    *exclude_blocks* is a sequence of ``(begin_marker, end_marker)`` pairs whose
    contents must be ignored.  ``doctor`` uses it for the intentional dnspin
    block: those entries are a current, working pin, not a 1.4.x leftover.
    """
    if content is None:
        try:
            content = _read_hosts(path)
        except Exception:
            return []

    marked_span = None
    m = re.search(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END),
        content,
        re.DOTALL,
    )
    if m:
        marked_span = m.span()

    excluded_spans = []
    for begin, end in exclude_blocks:
        match = re.search(re.escape(begin) + r".*?" + re.escape(end), content, re.DOTALL)
        if match:
            excluded_spans.append(match.span())

    found = []
    offset = 0
    for lineno, line in enumerate(content.splitlines(), 1):
        line_start = offset
        offset += len(line) + 1

        stripped = line.strip()
        inside_marked = bool(marked_span and marked_span[0] <= line_start < marked_span[1])
        if any(span[0] <= line_start < span[1] for span in excluded_spans):
            continue
        if not stripped or stripped.startswith("#"):
            continue
        fields = stripped.split()
        if len(fields) >= 2 and any(d in fields[1:] for d in PINNED_DOMAINS):
            found.append((lineno, stripped, inside_marked))
    return found


def is_pinned(path=HOSTS_PATH):
    """True if any pin line is present."""
    return bool(find_pins(path=path))


def remove_block(content):
    """Strip the marked block, leaving everything else byte-for-byte intact."""
    pattern = re.compile(
        re.escape(MARKER_BEGIN) + r".*?" + re.escape(MARKER_END) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


def unpin(path=HOSTS_PATH):
    """Remove every pin line - marked block and unmarked leftovers alike.

    Returns ``(removed_count, message)``.
    """
    content = _read_hosts(path)
    pins = find_pins(content, path=path)
    had_block = MARKER_BEGIN in content

    if not pins and not had_block:
        return 0, f"No pin entries found in {path}"

    drop = {line for _, line, _ in pins}
    cleaned = remove_block(content)
    cleaned = "".join(l for l in cleaned.splitlines(True) if l.strip() not in drop)

    if cleaned == content:
        return 0, f"No pin entries found in {path}"

    _write_hosts(cleaned, path)
    logger.info("Removed %d /etc/hosts pin line(s) left by <=1.4.x", len(pins))
    return len(pins), (
        f"Removed {len(pins)} pin line(s) from {path}"
        + (" (including the marked block)" if had_block else "")
    )
