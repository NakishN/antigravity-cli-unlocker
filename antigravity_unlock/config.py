"""
Persistent configuration for Antigravity CLI Unlocker.
"""

import json
import os

from antigravity_unlock.patcher import get_app_dir

STRATEGY_AUTO = "auto"
STRATEGY_IN_PLACE = "in_place"
STRATEGY_PIN = "pin"

# in_place is the default because agy self-updates: patching whatever is
# installed survives an update, 'pin' fights the updater forever, and 'auto' can
# replace a new build with a stale pinned one.
DEFAULT_STRATEGY = STRATEGY_IN_PLACE
DEFAULT_PINNED_VERSION = "1.1.9"
DEFAULT_CHECK_INTERVAL = 30

DEFAULT_CONFIG = {
    "strategy": DEFAULT_STRATEGY,
    "pinned_version": DEFAULT_PINNED_VERSION,
    "pinned_sha256": "",
    "pinned_size": 0,
    "check_interval_seconds": DEFAULT_CHECK_INTERVAL,
    "auto_patch": True,
    # Opt-in.  When False, a build this tool cannot patch is left alone instead
    # of being replaced by the older pinned binary.
    "allow_pin_fallback": False,
    # Opt-in.  Applies the `optional`-tier patterns (build-specific machine-code
    # gates, and the https_proxy -> AG_LS_PROXY rename).
    "include_optional": False,
}


def get_config_path():
    return os.path.join(get_app_dir(), "config.json")


def load_config():
    path = get_config_path()
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                config.update(data)
        except Exception:
            pass
    return config


def save_config(config):
    path = get_config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def _version_tuple(v):
    """Parse a dotted version, or None when it is not one.

    None (not zero) for unparseable input, so ``migrate_config`` only clears a
    pin it can *prove* is a downgrade.
    """
    try:
        parts = str(v).split(".")
    except (ValueError, AttributeError):
        return None
    if not parts or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(x) for x in parts)


def migrate_config(installed_version=None):
    """Move a pre-1.5 config forward.  Returns ``(changed, config, notes)``.

    Two things need migrating:

    1. New keys are filled in from ``DEFAULT_CONFIG`` (already handled by
       ``load_config``, but a persisted file missing them is rewritten so the
       user can see and edit them).
    2. ``strategy: pin`` is downgraded to ``in_place`` when the pinned build is
       *older* than the installed agy.  This was a live footgun: agy had
       self-updated to 1.2.7 while the config still pinned 1.1.27, so the next
       guardian tick would have replaced a working binary with a stale one.
       Pinning stays available - it is only auto-cleared when it is provably a
       downgrade, and the reason is returned so the caller can report it.
    """
    config = load_config()
    notes = []
    changed = False

    persisted = {}
    path = get_config_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                persisted = json.load(f) or {}
        except Exception:
            persisted = {}
    else:
        # No file yet: start from the defaults so the first write is complete.
        persisted = dict(config)

    for key, value in DEFAULT_CONFIG.items():
        if key not in persisted:
            persisted[key] = value
            changed = True
            notes.append(f"added {key}={value!r}")

    if persisted.get("strategy") == STRATEGY_PIN:
        pinned = persisted.get("pinned_version") or DEFAULT_PINNED_VERSION
        pinned_t = _version_tuple(pinned)
        installed_t = _version_tuple(installed_version) if installed_version else None
        if pinned_t is not None and installed_t is not None and pinned_t < installed_t:
            persisted["strategy"] = STRATEGY_IN_PLACE
            changed = True
            notes.append(
                f"strategy pin({pinned}) -> in_place: pinned build is older than "
                f"installed agy {installed_version}; keeping pin would downgrade it"
            )

    if changed:
        save_config(persisted)
    return changed, persisted, notes

