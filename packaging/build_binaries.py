"""
Standalone Binary Builder script using PyInstaller.
Builds standalone executables for Linux, Windows, and macOS with OS-specific asset names.
"""

import sys
import os
import shutil
import subprocess

def get_binary_name():
    """Returns OS-specific executable name to avoid release collisions."""
    if sys.platform == "win32":
        return "antigravity-unlock-windows-x64"
    elif sys.platform == "darwin":
        return "antigravity-unlock-macos-universal"
    else:
        return "antigravity-unlock-linux-x86_64"

def build():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entrypoint = os.path.join(root_dir, "antigravity_unlock", "__main__.py")
    versions_json = os.path.join(root_dir, "antigravity_unlock", "versions.json")

    dist_dir = os.path.join(root_dir, "dist")
    bin_name = get_binary_name()

    sep = ";" if sys.platform == "win32" else ":"
    add_data = f"{versions_json}{sep}antigravity_unlock"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", bin_name,
        "--add-data", add_data,
        "--collect-all", "cryptography",
        "--clean",
        entrypoint
    ]

    print(f"Building binary with PyInstaller: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=root_dir)
    if res.returncode != 0:
        print("PyInstaller build failed!", file=sys.stderr)
        sys.exit(res.returncode)

    print(f"Build completed successfully. Binary located in: {dist_dir}/{bin_name}")

if __name__ == "__main__":
    build()
