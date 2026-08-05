"""
Binary Patcher Module.
Applies exact SHA-256 or wildcard byte-pattern modifications to agy executables safely.
"""

import os
import json
import shutil
import hashlib
import platform

def compute_sha256(filepath):
    """Computes SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def get_app_dir():
    """Returns application data directory for backups and logs."""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    app_dir = os.path.join(base, "antigravity-unlocker")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

def load_versions_db():
    """Loads versions.json registry from package directory."""
    pkg_dir = os.path.dirname(__file__)
    v_path = os.path.join(pkg_dir, "versions.json")
    if os.path.exists(v_path):
        try:
            with open(v_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"versions": {}, "wildcard_patterns": []}

def get_backup_path(agy_path):
    """Generates backup path for a target binary."""
    app_dir = get_app_dir()
    is_win = platform.system() == "Windows"
    filename = os.path.basename(agy_path) + ".original.bak"
    return os.path.join(app_dir, filename)

def backup_binary(agy_path, dry_run=False):
    """Creates a backup copy of the original agy binary if not already present."""
    backup_file = get_backup_path(agy_path)
    if not os.path.exists(backup_file):
        if not dry_run:
            shutil.copy2(agy_path, backup_file)
        return backup_file, True
    return backup_file, False

def restore_binary(agy_path):
    """Restores the original binary from backup."""
    backup_file = get_backup_path(agy_path)
    if os.path.exists(backup_file):
        shutil.copy2(backup_file, agy_path)
        return True, f"Restored {agy_path} from {backup_file}"
    return False, f"Backup file not found at {backup_file}"

def patch_binary(agy_path, dry_run=False, force=False):
    """
    Patches the agy binary.
    1. Check SHA-256 against versions.json
    2. Fallback to wildcard pattern byte matching if unknown
    3. Atomically write patched binary
    """
    sha_orig = compute_sha256(agy_path)
    vdb = load_versions_db()

    with open(agy_path, "rb") as f:
        data = bytearray(f.read())

    applied_details = []

    # Check exact SHA256 registry
    exact_match = None
    for vname, vinfo in vdb.get("versions", {}).items():
        if vinfo.get("sha256") == sha_orig:
            exact_match = vname
            for p in vinfo.get("patches", []):
                offset = p["offset"]
                orig_bytes = bytes.fromhex(p["original"])
                repl_bytes = bytes.fromhex(p["replacement"])
                if data[offset:offset+len(orig_bytes)] == orig_bytes:
                    data[offset:offset+len(orig_bytes)] = repl_bytes
                    applied_details.append(f"Exact offset {offset}: {vname}")
            break

    # If no exact SHA256 match, use wildcard patterns
    if not exact_match:
        for wp in vdb.get("wildcard_patterns", []):
            p_name = wp.get("name", "pattern")
            orig_bytes = bytes.fromhex(wp["pattern"])
            repl_bytes = bytes.fromhex(wp["replacement"])

            if len(orig_bytes) != len(repl_bytes):
                continue  # Must preserve binary size

            count = data.count(orig_bytes)
            if count > 0:
                data = bytearray(bytes(data).replace(orig_bytes, repl_bytes))
                applied_details.append(f"Wildcard '{p_name}' ({count}x)")

    if not applied_details:
        return True, "Binary is already patched or no matching signatures found.", sha_orig

    if dry_run:
        return True, f"[DRY-RUN] Would apply: {', '.join(applied_details)}", sha_orig

    # Backup original before modifying
    backup_binary(agy_path, dry_run=False)

    # Write atomically
    tmp_path = agy_path + ".tmp_patch"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        orig_mode = os.stat(agy_path).st_mode
        os.chmod(tmp_path, orig_mode)
        os.replace(tmp_path, agy_path)
        sha_patched = compute_sha256(agy_path)
        return True, f"Patched: {', '.join(applied_details)}", sha_patched
    except Exception as e:
        if os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except Exception: pass
        return False, f"Failed writing patch: {e}", sha_orig
