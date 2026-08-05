"""
Discovery Engine for Antigravity CLI (agy) and IDE plugins.
Scans PATH, standard system directories, and IDE extension folders (VS Code, Cursor, Antigravity IDE).
"""

import os
import sys
import glob
import shutil
import platform

def get_editor_extension_dirs():
    """Returns candidate extension directories for VS Code, Cursor, Windsurf, and Antigravity IDE."""
    home = os.path.expanduser("~")
    dirs = [
        os.path.join(home, ".vscode", "extensions"),
        os.path.join(home, ".vscode-server", "extensions"),
        os.path.join(home, ".cursor", "extensions"),
        os.path.join(home, ".cursor-server", "extensions"),
        os.path.join(home, ".antigravity", "extensions"),
        os.path.join(home, ".vscode-oss", "extensions"),
        os.path.join(home, ".windsurf", "extensions"),
    ]

    # Windows AppData paths
    app_data = os.environ.get("APPDATA", "")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if app_data:
        dirs.append(os.path.join(app_data, "Code", "User", "globalStorage"))
    if local_app_data:
        dirs.append(os.path.join(local_app_data, "Programs", "Antigravity", "extensions"))

    return [d for d in dirs if d and os.path.isdir(d)]

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

    # 1. Check PATH via shutil.which and PATH entries
    which_path = shutil.which(binary_name)
    if which_path:
        candidates.append(os.path.abspath(which_path))

    path_env = os.environ.get("PATH", "")
    for p in path_env.split(os.pathsep):
        if p and os.path.isdir(p):
            target = os.path.join(p, binary_name)
            if os.path.isfile(target):
                candidates.append(os.path.abspath(target))

    # 2. Standard user & system bin directories
    if is_win:
        app_data = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
        local_app = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
        prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")

        candidates.extend([
            os.path.join(home, ".antigravity", "bin", binary_name),
            os.path.join(local_app, "Programs", "Antigravity", "bin", binary_name),
            os.path.join(local_app, "Antigravity", "bin", binary_name),
            os.path.join(app_data, "Antigravity", "bin", binary_name),
            os.path.join(prog_files, "Antigravity", "bin", binary_name),
            os.path.join(prog_files_x86, "Antigravity", "bin", binary_name),
        ])
    elif is_mac:
        candidates.extend([
            os.path.join(home, "Library", "Application Support", "Antigravity", "bin", binary_name),
            os.path.join(home, ".local", "bin", binary_name),
            os.path.join(home, ".antigravity", "bin", binary_name),
            f"/usr/local/bin/{binary_name}",
            f"/opt/homebrew/bin/{binary_name}",
            f"/Applications/Antigravity.app/Contents/Resources/bin/{binary_name}",
        ])
    else:  # Linux
        candidates.extend([
            os.path.join(home, ".local", "bin", binary_name),
            os.path.join(home, ".antigravity", "bin", binary_name),
            f"/usr/local/bin/{binary_name}",
            f"/usr/bin/{binary_name}",
            f"/opt/antigravity/bin/{binary_name}",
            f"/snap/bin/{binary_name}",
        ])

    # 3. Scan VS Code, Cursor, Windsurf, and Antigravity IDE extension directories
    for ext_dir in get_editor_extension_dirs():
        pattern = os.path.join(ext_dir, "*antigravity*", "**", binary_name)
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

def inspect_discovery():
    """Returns detailed summary of discovered binaries and their source categories."""
    binaries = find_agy_binaries()
    results = []
    home = os.path.expanduser("~")

    for b in binaries:
        category = "System PATH / Other"
        if ".vscode" in b or ".cursor" in b or "extensions" in b:
            category = "IDE Extension (VS Code / Cursor)"
        elif home in b:
            category = "User Home Directory (~/.local or ~/.antigravity)"
        elif "/usr/" in b or "Program Files" in b:
            category = "System Directory (/usr/bin or Program Files)"

        results.append({"path": b, "category": category})

    return results
