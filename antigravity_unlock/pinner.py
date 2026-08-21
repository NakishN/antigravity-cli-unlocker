"""
Version pinning for Antigravity CLI (agy).
Keeps the primary agy binary on a pinned release and re-applies patches when needed.
"""

import os
import re
import shutil
import subprocess
import sys
import urllib.request

from antigravity_unlock.config import (
    DEFAULT_PINNED_VERSION,
    load_config,
    save_config,
)
from antigravity_unlock.discovery import get_primary_agy
from antigravity_unlock.logging_utils import get_logger
from antigravity_unlock.patcher import (
    compute_sha256,
    get_app_dir,
    get_backup_path,
    load_versions_db,
    patch_binary,
)

logger = get_logger()

VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


def get_pinned_backup_path(agy_path=None):
    agy_path = agy_path or get_primary_agy() or "agy"
    base = os.path.basename(agy_path)
    return os.path.join(get_app_dir(), f"{base}.pinned.bak")


def _find_source_for_pin(agy_path):
    """Prefer current binary if present, fallback to backup."""
    if agy_path and os.path.isfile(agy_path):
        return agy_path

    original_backup = get_backup_path(agy_path)
    if os.path.isfile(original_backup):
        return original_backup

    return None


def get_agy_version(agy_path):
    if not agy_path or not os.path.isfile(agy_path):
        return None

    try:
        result = subprocess.run(
            [agy_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = (result.stdout or "") + (result.stderr or "")
        match = VERSION_RE.search(output.strip())
        if match:
            return match.group(1)
    except Exception:
        pass

    try:
        with open(agy_path, "rb") as f:
            sample = f.read(1024 * 1024)
        matches = VERSION_RE.findall(sample.decode("latin1", errors="ignore"))
        if matches:
            return sorted(set(matches), key=lambda v: [int(x) for x in v.split(".")])[-1]
    except Exception:
        pass

    return None


def _is_patched_binary(agy_path):
    vdb = load_versions_db()
    try:
        with open(agy_path, "rb") as f:
            data = f.read()
    except OSError:
        return False

    for wp in vdb.get("wildcard_patterns", []):
        orig_bytes = bytes.fromhex(wp["pattern"])
        if orig_bytes in data:
            return False
    return True


def download_pinned_backup(agy_path=None, target_version=DEFAULT_PINNED_VERSION):
    agy_path = agy_path or get_primary_agy() or "agy"
    pinned_backup = get_pinned_backup_path(agy_path)

    if sys.platform == "win32":
        asset = f"agy-{target_version}-windows-x64.exe"
    elif sys.platform == "darwin":
        asset = f"agy-{target_version}-macos-universal"
    else:
        asset = f"agy-{target_version}-linux-x86_64"

    url = f"https://github.com/NakishN/antigravity-cli-unlocker/releases/download/v1.1.0/{asset}"
    logger.info("Downloading pinned agy %s binary from GitHub Releases: %s", target_version, url)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AntigravityUnlocker/1.1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(pinned_backup, "wb") as out:
            shutil.copyfileobj(resp, out)
        os.chmod(pinned_backup, 0o755)
        return True, f"Downloaded {target_version} backup to {pinned_backup}"
    except Exception as e:
        return False, f"Failed to download {target_version} backup ({e})"


def init_pin(agy_path=None, pinned_version=None, source_path=None):
    agy_path = agy_path or get_primary_agy()
    if not agy_path:
        return False, "agy binary not found."

    config = load_config()
    source = source_path or _find_source_for_pin(agy_path)
    source_version = get_agy_version(source) if source else None

    target_version = pinned_version or source_version or config.get("pinned_version") or DEFAULT_PINNED_VERSION
    pinned_backup = get_pinned_backup_path(agy_path)

    if not source or (source_version and source_version != target_version):
        # Try downloading pinned backup from GitHub release asset as fallback
        dl_ok, dl_msg = download_pinned_backup(agy_path=agy_path, target_version=target_version)
        if dl_ok:
            source = pinned_backup
        else:
            if source_version:
                return False, (
                    f"Current system binary version is {source_version}, but requested --version is {target_version}. "
                    f"To pin current installed version {source_version}, run without --version. "
                    f"To pin {target_version}, specify --source /path/to/agy_{target_version}."
                )
            return False, "No source binary found for pin init."

    if source != pinned_backup:
        shutil.copy2(source, pinned_backup)
        os.chmod(pinned_backup, 0o755)

    pinned_sha = compute_sha256(pinned_backup)
    pinned_size = os.path.getsize(pinned_backup)

    config.update(
        {
            "pinned_version": target_version,
            "pinned_sha256": pinned_sha,
            "pinned_size": pinned_size,
            "auto_patch": True,
        }
    )
    save_config(config)

    msg = (
        f"Pinned agy {target_version} saved to {pinned_backup} "
        f"(sha256={pinned_sha[:12]}..., size={pinned_size})"
    )
    logger.info(msg)
    return True, msg


def _needs_restore(agy_path, config):
    pinned_version = config.get("pinned_version") or DEFAULT_PINNED_VERSION
    pinned_sha = config.get("pinned_sha256", "")
    pinned_size = config.get("pinned_size", 0)

    if not os.path.isfile(agy_path):
        return True, "agy binary missing"

    current_size = os.path.getsize(agy_path)
    if pinned_size and current_size != pinned_size:
        return True, f"size mismatch ({current_size} != {pinned_size})"

    current_sha = compute_sha256(agy_path)
    if pinned_sha and current_sha == pinned_sha:
        return False, "binary matches pinned backup"

    current_version = get_agy_version(agy_path)
    if current_version and current_version != pinned_version:
        return True, f"version mismatch ({current_version} != {pinned_version})"

    if pinned_sha and current_sha != pinned_sha:
        return True, "sha256 mismatch"

    return False, "binary already pinned"


def ensure_pinned(agy_path=None, dry_run=False):
    agy_path = agy_path or get_primary_agy()
    if not agy_path:
        return False, "agy binary not found.", False

    config = load_config()
    pinned_backup = get_pinned_backup_path(agy_path)

    if not os.path.isfile(pinned_backup):
        ok, msg = init_pin(agy_path=agy_path)
        if not ok:
            return False, msg, False
        config = load_config()

    needs_restore, reason = _needs_restore(agy_path, config)
    if not needs_restore and _is_patched_binary(agy_path):
        msg = f"agy already pinned to {config.get('pinned_version', DEFAULT_PINNED_VERSION)}"
        logger.info(msg)
        return True, msg, False

    if not needs_restore and not _is_patched_binary(agy_path):
        reason = "binary matches pinned backup but patch signatures remain"
        needs_restore = True

    if dry_run:
        action = "restore and patch" if needs_restore else "patch only"
        return True, f"[DRY-RUN] Would {action}: {reason}", False

    if needs_restore:
        # Atomic replace to prevent OSError: Text file busy on Linux
        tmp_target = agy_path + ".tmp_restore"
        shutil.copy2(pinned_backup, tmp_target)
        os.chmod(tmp_target, 0o755)
        os.replace(tmp_target, agy_path)
        logger.info("Restored agy from pinned backup (%s): %s", reason, pinned_backup)

    if config.get("auto_patch", True):
        success, patch_msg, _ = patch_binary(agy_path)
        if not success:
            return False, patch_msg, True
        logger.info("Patch result: %s", patch_msg)
        return True, f"Restored and patched agy ({reason}): {patch_msg}", True

    return True, f"Restored agy ({reason}) without patching", True
