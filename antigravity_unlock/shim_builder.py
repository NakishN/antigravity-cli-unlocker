"""
Builds the DNS shim shared library (dns_shim.so) from the bundled C source.
Compiled once on first run and cached in the app data directory.
"""

import os
import subprocess
import logging
import shutil

from .config import get_app_dir

logger = logging.getLogger("antigravity_shim")

SHIM_SOURCE = os.path.join(os.path.dirname(__file__), "dns_shim.c")
SHIM_BINARY_NAME = "dns_shim.so"


def get_shim_path() -> str:
    """Returns the path where the compiled .so should live."""
    return os.path.join(get_app_dir(), SHIM_BINARY_NAME)


def is_shim_built() -> bool:
    """True if a compiled shim exists and is newer than the source."""
    shim_path = get_shim_path()
    if not os.path.exists(shim_path):
        return False
    # Rebuild if source is newer than binary
    if os.path.exists(SHIM_SOURCE):
        if os.path.getmtime(SHIM_SOURCE) > os.path.getmtime(shim_path):
            return False
    return True


def build_shim() -> str:
    """Compiles dns_shim.c into a shared library. Returns the .so path."""
    shim_path = get_shim_path()
    os.makedirs(os.path.dirname(shim_path), exist_ok=True)

    if not os.path.exists(SHIM_SOURCE):
        raise FileNotFoundError(f"DNS shim source not found: {SHIM_SOURCE}")

    # Check for gcc
    cc = shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise RuntimeError("gcc/cc not found — install build-essential to compile the DNS shim")

    cmd = [cc, "-shared", "-fPIC", "-O2", "-o", shim_path, SHIM_SOURCE, "-ldl"]
    logger.info(f"Building DNS shim: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to compile DNS shim:\n{result.stderr}")

    logger.info(f"DNS shim compiled: {shim_path}")
    return shim_path


def ensure_shim() -> str:
    """Returns the path to a ready-to-use shim, building if necessary."""
    if not is_shim_built():
        return build_shim()
    return get_shim_path()
