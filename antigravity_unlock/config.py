"""
Persistent configuration for Antigravity CLI Unlocker.
"""

import json
import os

from antigravity_unlock.patcher import get_app_dir

DEFAULT_PINNED_VERSION = "1.1.16"
DEFAULT_CHECK_INTERVAL = 30

DEFAULT_CONFIG = {
    "pinned_version": DEFAULT_PINNED_VERSION,
    "pinned_sha256": "",
    "pinned_size": 0,
    "check_interval_seconds": DEFAULT_CHECK_INTERVAL,
    "auto_patch": True,
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
