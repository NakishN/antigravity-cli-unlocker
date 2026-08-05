"""
Tests for Binary Patcher and SHA-256 validation.
"""

import os
import unittest
import tempfile

from antigravity_unlock.patcher import patch_binary, restore_binary, compute_sha256, get_backup_path

class TestPatcher(unittest.TestCase):
    def test_compute_sha256(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            tmp_path = f.name
        try:
            sha = compute_sha256(tmp_path)
            self.assertEqual(sha, "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
        finally:
            os.unlink(tmp_path)

    def test_patch_and_restore_wildcard(self):
        content = b"header_data_0123_eligibility check failed_footer_data"
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            tmp_path = f.name

        try:
            orig_size = len(content)
            success, msg, sha = patch_binary(tmp_path)
            self.assertTrue(success)

            with open(tmp_path, "rb") as f:
                patched_content = f.read()

            self.assertEqual(len(patched_content), orig_size)
            self.assertIn(b"eligibility check bypass", patched_content)
            self.assertNotIn(b"eligibility check failed", patched_content)

            rec_ok, rec_msg = restore_binary(tmp_path)
            self.assertTrue(rec_ok)
            with open(tmp_path, "rb") as f:
                restored_content = f.read()
            self.assertEqual(restored_content, content)
        finally:
            os.unlink(tmp_path)
            bak = get_backup_path(tmp_path)
            if os.path.exists(bak):
                os.unlink(bak)

if __name__ == "__main__":
    unittest.main()
