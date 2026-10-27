"""
CloudCode endpoint override for Antigravity IDE and CLI.

**The two endpoints are NOT interchangeable, and this module previously said the
opposite.**  The old claim rested on an unauthenticated probe from 2026-09-20
where both hosts returned an identical 401 ``CREDENTIALS_MISSING`` - and this
project's own 1.5.0 notes already said such a probe cannot distinguish them,
because Google checks credentials before geography.  The probe proved nothing
here.

Upstream evidence, all reproduced independently (see
``google-antigravity/antigravity-cli`` issue #1016, still open):

- On the default ``daily-cloudcode-pa`` host, ``gemini-*`` returns
  ``FAILED_PRECONDITION (400) User location is not supported for the API use.``
- On the same account, same session, same network, ``claude-sonnet-4-6``
  returns 200 with real generated text.  Issue #1155 proves this server-side,
  with the account's own OAuth token and no client involved.
- Setting ``CLOUD_CODE_URL=https://cloudcode-pa.googleapis.com`` makes the
  location error **disappear** for Gemini, replaced by
  ``RESOURCE_EXHAUSTED (429)``.
- So the gate is applied by the backend per host, not by the client binary.

Measured here on 2026-10-07 (Estonia egress, quota available): the production
host returned 429 for ``gemini-3.8-flash-high``, ``claude-sonnet-4-6`` and
``gpt-oss-120b-medium`` alike - the location gate is genuinely gone there, but
this consumer account has zero quota on that project.  For this account the two
hosts are each unusable in a different way, so the override is still applied
only when explicitly requested via ``antigravity-unlock endpoint apply``.  It is
a diagnostic and an escape hatch, not a fix; it used to be written
automatically on every patch, on the theory that unblock DNS providers
substituted the ``daily-`` host but not the production one.  That theory died
with the Smart-DNS layer in 1.5.0, and silently editing a user's
``settings.json`` for no measured benefit is not a trade worth making.

Each surface already has a supported configuration knob:

- **CLI** reads ``CLOUD_CODE_URL``.
- **IDE** reads ``jetski.cloudCodeUrl`` from its user settings JSON.

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
