"""
Discovery Engine for Antigravity CLI (agy) and IDE plugins.
Finds executable locations across Linux, macOS, and Windows.
"""

import os
import sys
import glob
import shutil
import platform

def find_agy_binaries():
    """
    Scans system environment and standard installation directories for agy / agy.exe.
    Returns a list of unique existing executable paths.
    """
    is_win = platform.system() == "Windows"
    is_mac = platform.system() == "Darwin"
    binary_name = "agy.exe" if is_win else "agy"

    home = os.path.expanduser("~")
    candidates = []

    # 1. Check PATH via shutil.which
    which_path = shutil.which(binary_name)
    if which_path:
        candidates.append(os.path.abspath(which_path))

    # 2. Standard user & system bin directories
    if is_win:
        local_app = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        candidates.extend([
            os.path.join(home, ".antigravity", "bin", binary_name),
            os.path.join(local_app, "Programs", "Antigravity", "bin", binary_name),
            os.path.join(local_app, "Antigravity", "bin", binary_name),
            os.path.join(prog_files, "Antigravity", "bin", binary_name),
        ])
    elif is_mac:
        candidates.extend([
            os.path.join(home, "Library", "Application Support", "Antigravity", "bin", binary_name),
            os.path.join(home, ".local", "bin", binary_name),
            os.path.join(home, ".antigravity", "bin", binary_name),
            f"/usr/local/bin/{binary_name}",
            f"/opt/homebrew/bin/{binary_name}",
        ])
    else:  # Linux
        candidates.extend([
            os.path.join(home, ".local", "bin", binary_name),
            os.path.join(home, ".antigravity", "bin", binary_name),
            f"/usr/local/bin/{binary_name}",
            f"/usr/bin/{binary_name}",
            f"/opt/antigravity/bin/{binary_name}",
        ])

    # 3. Scan VS Code, Cursor, and Antigravity IDE plugin directories
    editor_dirs = [
        os.path.join(home, ".vscode", "extensions"),
        os.path.join(home, ".cursor", "extensions"),
        os.path.join(home, ".antigravity", "extensions"),
    ]

    for editor_dir in editor_dirs:
        if os.path.isdir(editor_dir):
            pattern = os.path.join(editor_dir, "*antigravity*", "**", binary_name)
            for found in glob.glob(pattern, recursive=True):
                candidates.append(found)

    # Filter valid executables and preserve order while deduplicating
    valid_paths = []
    seen = set()

    for path in candidates:
        abs_p = os.path.abspath(path)
        if abs_p not in seen and os.path.isfile(abs_p) and os.access(abs_p, os.R_OK):
            valid_paths.append(abs_p)
            seen.add(abs_p)

    return valid_paths

def get_primary_agy():
    """Returns the primary agy binary path or None if not found."""
    found = find_agy_binaries()
    return found[0] if found else None
