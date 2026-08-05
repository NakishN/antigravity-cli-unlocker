#!/usr/bin/env python3
"""
Antigravity CLI Unlocker Core Launcher v3.0.0
Delegates to the modular antigravity_unlock package.
"""

import sys
import os

# Ensure package directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from antigravity_unlock.cli import main

if __name__ == "__main__":
    main()
