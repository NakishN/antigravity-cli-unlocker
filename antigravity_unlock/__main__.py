import sys
import os

# Support running as a standalone PyInstaller entrypoint or script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from antigravity_unlock.cli import main

if __name__ == "__main__":
    main()
