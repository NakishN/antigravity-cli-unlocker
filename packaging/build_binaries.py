"""
Standalone Binary Builder script using PyInstaller.
Builds standalone executables for Linux, Windows, and macOS without requiring Python.
"""

import sys
import os
import shutil
import subprocess

def build():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    entrypoint = os.path.join(root_dir, "antigravity_unlock", "__main__.py")
    versions_json = os.path.join(root_dir, "antigravity_unlock", "versions.json")

    dist_dir = os.path.join(root_dir, "dist")
    build_dir = os.path.join(root_dir, "build")

    sep = ";" if sys.platform == "win32" else ":"
    add_data = f"{versions_json}{sep}antigravity_unlock"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "antigravity-unlock",
        "--add-data", add_data,
        "--clean",
        entrypoint
    ]

    print(f"Building binary with PyInstaller: {' '.join(cmd)}")
    res = subprocess.run(cmd, cwd=root_dir)
    if res.returncode != 0:
        print("PyInstaller build failed!", file=sys.stderr)
        sys.exit(res.returncode)

    print(f"Build completed successfully. Binary located in: {dist_dir}")

if __name__ == "__main__":
    build()
