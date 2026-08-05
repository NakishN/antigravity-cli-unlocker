"""
Tests for Discovery Engine scanning capabilities.
"""

import os
import unittest
import tempfile
import platform

from antigravity_unlock.discovery import find_agy_binaries, get_editor_extension_dirs, inspect_discovery

class TestDiscoveryEngine(unittest.TestCase):
    def test_find_agy_binaries_type(self):
        binaries = find_agy_binaries()
        self.assertIsInstance(binaries, list)

    def test_editor_extension_dirs(self):
        dirs = get_editor_extension_dirs()
        self.assertIsInstance(dirs, list)

    def test_inspect_discovery(self):
        info = inspect_discovery()
        self.assertIsInstance(info, list)

    def test_mock_binary_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            binary_name = "agy.exe" if platform.system() == "Windows" else "agy"
            fake_bin = os.path.join(tmpdir, binary_name)
            with open(fake_bin, "w") as f:
                f.write("#!/bin/sh\necho mock agy")
            os.chmod(fake_bin, 0o755)

            # Temporarily add tmpdir to PATH
            orig_path = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = tmpdir + os.pathsep + orig_path
                discovered = find_agy_binaries()
                self.assertIn(os.path.abspath(fake_bin), discovered)
            finally:
                os.environ["PATH"] = orig_path

if __name__ == "__main__":
    unittest.main()
