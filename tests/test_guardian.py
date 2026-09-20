"""
Tests for the background guardian's change detection.

The behaviour that matters: the guardian must notice when agy replaces itself
(which reverts the patch) and must NOT report its own patch write as an external
change.  The second half is the regression - a false "self-update" warning on
every tick buries the real one.
"""

import logging
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from antigravity_unlock import guardian, patcher


STOCK = b"#!/bin/sh\necho agy version 9.9.9\npad ineligible pad name=ineligible\n"


class TestGuardianChangeDetection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.agy = os.path.join(self.tmp, "agy")
        with open(self.agy, "wb") as f:
            f.write(STOCK)
        os.chmod(self.agy, 0o755)

        # Keep backups inside the throwaway dir instead of the real app dir.
        for target in ("antigravity_unlock.patcher.get_app_dir",
                       "antigravity_unlock.pinner.get_app_dir",
                       "antigravity_unlock.config.get_app_dir",
                       "antigravity_unlock.logging_utils.get_app_dir"):
            p = patch(target, return_value=self.tmp)
            p.start()
            self.addCleanup(p.stop)

        guardian._last_fingerprint = None
        self.records = []

        class _Capture(logging.Handler):
            def emit(inner, record):
                self.records.append(record.getMessage())

        handler = _Capture()
        logger = logging.getLogger("antigravity_unlocker")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        self.addCleanup(logger.removeHandler, handler)

    def _messages(self):
        return "\n".join(self.records)

    def test_patches_an_unpatched_binary(self):
        guardian._run_check("startup", strategy="in_place", agy_path=self.agy)
        state, _ = patcher.classify_binary(self.agy)
        self.assertEqual(state, patcher.STATE_PATCHED)

    def test_own_patch_write_is_not_reported_as_a_self_update(self):
        guardian._run_check("startup", strategy="in_place", agy_path=self.agy)
        self.records.clear()

        # Several idle ticks: nothing external happens, so nothing should be
        # claimed.  The pre-fix code warned here because it had stored the
        # fingerprint from before its own write.
        for _ in range(3):
            guardian._run_check("interval", strategy="in_place", agy_path=self.agy)

        self.assertNotIn("changed on disk", self._messages())
        self.assertNotIn("self-update", self._messages())
        state, _ = patcher.classify_binary(self.agy)
        self.assertEqual(state, patcher.STATE_PATCHED)

    def test_real_self_update_is_detected_and_repatched(self):
        guardian._run_check("startup", strategy="in_place", agy_path=self.agy)
        self.records.clear()

        # agy replaces itself with stock bytes; mtime must actually move.
        os.utime(self.agy, ns=(1, 1))
        with open(self.agy, "wb") as f:
            f.write(STOCK)

        guardian._run_check("interval", strategy="in_place", agy_path=self.agy)

        self.assertIn("changed on disk", self._messages())
        self.assertIn("self-update", self._messages())
        state, _ = patcher.classify_binary(self.agy)
        self.assertEqual(state, patcher.STATE_PATCHED)

    def test_missing_binary_does_not_raise(self):
        gone = os.path.join(self.tmp, "nope")
        self.assertIsNone(guardian._fingerprint(gone))
        guardian._run_check("interval", strategy="in_place", agy_path=gone)

    def test_fingerprint_is_cheap_stat_not_a_hash(self):
        # Guards the design choice: hashing 220 MB every tick is what makes a
        # resident guardian expensive.
        fp = guardian._fingerprint(self.agy)
        self.assertEqual(len(fp), 2)
        self.assertEqual(fp[0], os.path.getsize(self.agy))
        self.assertEqual(fp[1], os.stat(self.agy).st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
