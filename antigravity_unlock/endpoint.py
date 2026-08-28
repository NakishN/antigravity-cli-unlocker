"""
CloudCode endpoint override for Antigravity IDE and CLI.

The region gate lives on the CloudCode API.  ``cloudcode-pa.googleapis.com`` is
no longer substituted by any unblock DNS provider, while
``daily-cloudcode-pa.googleapis.com`` is the *same service* and is still
substituted.  The fix is to point every client surface at the daily host.

Each surface already has a supported configuration knob:

- **CLI** reads ``CLOUD_CODE_URL`` (handled in ``runner.py``).
- **IDE** reads ``jetski.cloudCodeUrl`` from its user settings JSON.
- **Desktop** already ships pointing at the daily host in ``app.asar``.

Being configuration rather than a binary patch means an app update cannot
silently undo it, and a revert is a key removal rather than a byte-level
restore.
"""

import json
import os
import platform
import re


DAILY_ENDPOINT = "https://daily-cloudcode-pa.googleapis.com"
IDE_SETTING = "jetski.cloudCodeUrl"


def _ide_settings_path(install_dir):
    """Locate the IDE user settings JSON from *install_dir*.

    The folder name under the config directory is derived from ``nameShort``
    in ``product.json``, so a rebranded build still resolves correctly.
    """
    product_json = os.path.join(install_dir, "resources", "app", "product.json")
    if not os.path.isfile(product_json):
        return None

    try:
        with open(product_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        match = re.search(r'"nameShort"\s*:\s*"([^"]+)"', open(product_json, "r").read())
        if match:
            data = {"nameShort": match.group(1)}
        else:
            return None

    name = data.get("nameShort")
    if not name:
        return None

    system = platform.system()
    home = os.path.expanduser("~")

    if system == "Windows":
        base = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    elif system == "Darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.path.join(home, ".config")

    return os.path.join(base, name, "User", "settings.json")


def _ide_build_reads_setting(install_dir):
    """True when this IDE build actually reads the override key."""
    main_js = os.path.join(install_dir, "resources", "app", "out", "main.js")
    if not os.path.isfile(main_js):
        return False
    try:
        with open(main_js, "r", encoding="utf-8", errors="ignore") as f:
            return IDE_SETTING in f.read()
    except Exception:
        return False


def _upsert_jsonc_key(text, key, value):
    """Insert or update *key* in a JSONC (JSON with comments) text.

    Preserves comments, trailing commas, and key order — the settings file
    belongs to the user, not to us.
    """
    pattern = re.compile(
        r'("' + re.escape(key) + r'"\s*:\s*")[^"]*(")'
    )
    entry_value = f'"{key}": "{value}"'

    if pattern.search(text):
        return pattern.sub(lambda m: m.group(1) + value + m.group(2), text)

    # Key not present — append before the last closing brace.
    idx = text.rfind("}")
    if idx < 0:
        return None

    prefix = text[:idx].rstrip()
    suffix = text[idx:]

    if prefix and not prefix.rstrip().endswith(","):
        prefix += ","
    prefix += f'\n    "{key}": "{value}"\n'
    return prefix + suffix


def apply_ide_endpoint(install_dir):
    """Write the daily endpoint override into the IDE settings.

    Returns ``(applied: bool, message: str)``.
    """
    if not _ide_build_reads_setting(install_dir):
        return False, "IDE build does not read jetski.cloudCodeUrl"

    settings_path = _ide_settings_path(install_dir)
    if not settings_path:
        return False, "Could not locate IDE settings path"

    if not os.path.isfile(settings_path):
        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        text = "{}"
    else:
        with open(settings_path, "r", encoding="utf-8") as f:
            text = f.read()

    # Already correct?
    current = re.search(
        r'"' + re.escape(IDE_SETTING) + r'"\s*:\s*"([^"]*)"', text
    )
    if current and current.group(1) == DAILY_ENDPOINT:
        return True, "IDE endpoint already set"

    new_text = _upsert_jsonc_key(text, IDE_SETTING, DAILY_ENDPOINT)
    if new_text is None:
        return False, "Failed to parse settings file"

    with open(settings_path, "w", encoding="utf-8") as f:
        f.write(new_text)

    return True, f"IDE endpoint set to {DAILY_ENDPOINT}"


def remove_ide_endpoint(install_dir):
    """Remove the endpoint override from IDE settings.

    Returns ``(removed: bool, message: str)``.
    """
    settings_path = _ide_settings_path(install_dir)
    if not settings_path or not os.path.isfile(settings_path):
        return False, "Settings file not found"

    with open(settings_path, "r", encoding="utf-8") as f:
        text = f.read()

    pattern = re.compile(
        r',?\s*"' + re.escape(IDE_SETTING) + r'"\s*:\s*"[^"]*"\s*,?',
    )
    new_text = pattern.sub("", text, count=1)
    if new_text == text:
        return False, "Setting not present"

    with open(settings_path, "w", encoding="utf-8") as f:
        f.write(new_text)

    return True, "IDE endpoint override removed"
