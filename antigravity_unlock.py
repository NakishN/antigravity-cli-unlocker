#!/usr/bin/env python3
"""
🚀 Antigravity CLI Unlocker v2.1 (Cross-Platform Python Edition)
Works seamlessly on Linux (Ubuntu / Debian / Arch) and Windows (10 / 11).
"""

import sys
import os
import re
import shutil
import platform
import subprocess

DNS_PRIMARY = "111.88.96.50"
DNS_SECONDARY = "111.88.96.51"

def print_banner():
    print("""
╔══════════════════════════════════════════════════════════════════╗
║        🚀  Antigravity CLI Unlocker v2.1 (Cross-Platform)        ║
║   Google Antigravity CLI (agy) without VPN for RU / BY region    ║
╚══════════════════════════════════════════════════════════════════╝
""")

def find_agy_binary():
    is_win = platform.system() == "Windows"
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
        if path and os.path.isfile(path) and os.access(path, os.X_OK | os.R_OK):
            return path
    return None

def patch_binary(agy_path):
    print(f"[*] Inspecting binary: {agy_path}")
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
            print("  [✓] Binary is already patched.")
        else:
            print("  [⚠] No gate signatures matched.")
        return True

    tmp_path = agy_path + ".tmp_patch"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        orig_mode = os.stat(agy_path).st_mode
        os.chmod(tmp_path, orig_mode)
        os.replace(tmp_path, agy_path)
        for app in applied:
            print(f"  [✓] Machine-code patch applied: {app}")
        return True
    except Exception as e:
        if os.path.exists(tmp_path):
            try: os.unlink(tmp_path)
            except Exception: pass
        print(f"  [✗] Failed to write binary patch: {e}")
        return False

def backup_binary(agy_path):
    is_win = platform.system() == "Windows"
    backup_dir = os.path.join(os.environ.get("LOCALAPPDATA" if is_win else "HOME", "~"), ".local", "share", "antigravity-unlocker")
    os.makedirs(backup_dir, exist_ok=True)
    backup_file = os.path.join(backup_dir, "agy.exe.original.bak" if is_win else "agy.original.bak")

    if not os.path.exists(backup_file):
        shutil.copy2(agy_path, backup_file)
        print(f"  [✓] Backup created at: {backup_file}")
    else:
        print(f"  [✓] Backup exists at: {backup_file}")
    return backup_file

def main():
    print_banner()
    agy_path = find_agy_binary()
    if not agy_path:
        print("[✗] Error: Antigravity CLI (agy) binary not found on this system!")
        print("Please install Antigravity CLI or add it to PATH.")
        sys.exit(1)

    backup_binary(agy_path)
    patch_binary(agy_path)
    print("\n[✓] Antigravity CLI binary successfully patched!")

if __name__ == "__main__":
    main()
