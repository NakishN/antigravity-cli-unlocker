#!/usr/bin/env python3
"""
Antigravity CLI Unlocker Core Module v2.2
Cross-Platform Regional Access & Binary Patcher (Linux / macOS / Windows)
"""

import sys
import os
import re
import shutil
import hashlib
import platform
import argparse
import datetime

DNS_PRIMARY = "111.88.96.50"
DNS_SECONDARY = "111.88.96.51"

def get_app_dir():
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    app_dir = os.path.join(base, "antigravity-unlocker")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

LOG_FILE = os.path.join(get_app_dir(), "unlocker.log")

def log(msg, level="INFO"):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {msg}"
    print(formatted)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except Exception:
        pass

def compute_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

def find_agy_binary():
    is_win = platform.system() == "Windows"
    is_mac = platform.system() == "Darwin"
    binary_name = "agy.exe" if is_win else "agy"

    home = os.path.expanduser("~")
    candidates = []

    if is_win:
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", "")
        candidates.extend([
            os.path.join(home, ".antigravity", "bin", binary_name),
            os.path.join(local_app, "Programs", "Antigravity", "bin", binary_name),
            os.path.join(prog_files, "Antigravity", "bin", binary_name),
        ])
    elif is_mac:
        candidates.extend([
            os.path.join(home, "Library", "Application Support", "Antigravity", "bin", binary_name),
            os.path.join(home, ".local", "bin", binary_name),
            f"/usr/local/bin/{binary_name}",
        ])
    else:
        candidates.extend([
            os.path.join(home, ".local", "bin", binary_name),
            f"/usr/local/bin/{binary_name}",
            f"/usr/bin/{binary_name}",
        ])

    cmd_path = shutil.which(binary_name)
    if cmd_path:
        candidates.append(cmd_path)

    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.R_OK):
            return path
    return None

def patch_binary(agy_path, dry_run=False, force=False):
    sha_orig = compute_sha256(agy_path)
    log(f"Inspecting binary: {agy_path} (SHA256: {sha_orig[:16]}...)")

    with open(agy_path, "rb") as f:
        data = bytearray(f.read())

    gates = [
        (
            "x64 eligibility gate",
            re.compile(rb'\x48\x85\xc0\x0f\x84....\x80\x78\x08\x00\x0f\x85....', re.S),
            re.compile(rb'\x48\x85\xc0\x0f\x84....\x48\x85\xc0\x90\x0f\x85....', re.S),
            b'\x48\x85\xc0\x90',
            9,
        ),
        (
            "arm64 eligibility gate",
            re.compile(rb'...\xb5...\xb4\x01\x20\x40\x39...\x37', re.S),
            re.compile(rb'...\xb5...\xb4\x21\x00\x80\x52...\x37', re.S),
            b'\x21\x00\x80\x52',
            8,
        ),
    ]

    applied = []
    already = []

    for label, sig, patched, fix, offset in gates:
        if list(patched.finditer(data)):
            already.append(label)
            continue
        hits = [m.start() + offset for m in sig.finditer(data)]
        if hits:
            for off in hits:
                data[off:off + len(fix)] = fix
            applied.append(f"{label} ({len(hits)}x)")

    if not applied:
        if already:
            log("Binary is already patched.", "OK")
        else:
            log("No gate signatures matched in binary.", "WARN" if not force else "INFO")
        return True

    if dry_run:
        log(f"[DRY-RUN] Would apply patch to {agy_path} ({', '.join(applied)})", "INFO")
        return True

    tmp_path = agy_path + ".tmp_patch"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        orig_mode = os.stat(agy_path).st_mode
        os.chmod(tmp_path, orig_mode)
        os.replace(tmp_path, agy_path)
        sha_patched = compute_sha256(agy_path)
        log(f"Patch applied successfully: {', '.join(applied)} (New SHA256: {sha_patched[:16]}...)", "OK")
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except Exception: pass
        log(f"Failed writing binary patch: {e}", "ERROR")
        return False

def backup_binary(agy_path, dry_run=False):
    app_dir = get_app_dir()
    is_win = platform.system() == "Windows"
    backup_file = os.path.join(app_dir, "agy.exe.original.bak" if is_win else "agy.original.bak")

    if not os.path.exists(backup_file):
        if not dry_run:
            shutil.copy2(agy_path, backup_file)
            log(f"Backup created: {backup_file}", "OK")
        else:
            log(f"[DRY-RUN] Would create backup at {backup_file}", "INFO")
    else:
        log(f"Backup verified: {backup_file}", "OK")
    return backup_file

def restore_binary():
    app_dir = get_app_dir()
    is_win = platform.system() == "Windows"
    backup_file = os.path.join(app_dir, "agy.exe.original.bak" if is_win else "agy.original.bak")
    agy_path = find_agy_binary() or (os.path.join(os.path.expanduser("~"), ".antigravity", "bin", "agy.exe" if is_win else "agy"))

    if os.path.exists(backup_file):
        shutil.copy2(backup_file, agy_path)
        log(f"Original binary restored from backup: {agy_path}", "OK")
        return True
    else:
        log(f"Backup file not found: {backup_file}", "WARN")
        return False

def main():
    parser = argparse.ArgumentParser(description="Antigravity CLI Unlocker Core Module")
    parser.add_argument("--dry-run", action="store_true", help="Perform verification without writing changes")
    parser.add_argument("--force", action="store_true", help="Force patch attempt regardless of signature warnings")
    parser.add_argument("--restore", action="store_true", help="Restore original binary from backup")

    args = parser.parse_args()

    if args.restore:
        restore_binary()
        return

    agy_path = find_agy_binary()
    if not agy_path:
        log("Antigravity CLI (agy) binary not found on this system.", "ERROR")
        sys.exit(1)

    backup_binary(agy_path, dry_run=args.dry_run)
    patch_binary(agy_path, dry_run=args.dry_run, force=args.force)

if __name__ == "__main__":
    main()
