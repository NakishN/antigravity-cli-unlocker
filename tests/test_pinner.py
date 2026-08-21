"""
Tests for Version Pinning and Strategy module (pinner.py).
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from antigravity_unlock.pinner import (
    init_pin,
    ensure_pinned,
    enforce_strategy,
    set_strategy,
    _needs_restore,
    get_pinned_backup_path,
    get_agy_version,
)
from antigravity_unlock.config import (
    DEFAULT_PINNED_VERSION,
    STRATEGY_AUTO,
    STRATEGY_IN_PLACE,
    STRATEGY_PIN,
    load_config,
    save_config,
)


class TestPinner(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.agy_path = os.path.join(self.tmp_dir, "agy")
        self.pinned_bak = os.path.join(self.tmp_dir, "agy.pinned.bak")

        # Create dummy 1.1.9 binary content
        self.dummy_binary_content = b"#!/bin/sh\necho agy version 1.1.9\neligibility check failed\n"
        with open(self.agy_path, "wb") as f:
            f.write(self.dummy_binary_content)
        os.chmod(self.agy_path, 0o755)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("antigravity_unlock.pinner.get_pinned_backup_path")
    @patch("antigravity_unlock.pinner.get_app_dir")
    def test_init_pin(self, mock_app_dir, mock_pinned_bak):
        mock_app_dir.return_value = self.tmp_dir
        mock_pinned_bak.return_value = self.pinned_bak

        ok, msg = init_pin(agy_path=self.agy_path, pinned_version="1.1.9", source_path=self.agy_path)
        self.assertTrue(ok, f"init_pin failed: {msg}")
        self.assertTrue(os.path.exists(self.pinned_bak))

        with open(self.pinned_bak, "rb") as f:
            bak_content = f.read()
        self.assertEqual(bak_content, self.dummy_binary_content)

    @patch("antigravity_unlock.pinner.get_pinned_backup_path")
    @patch("antigravity_unlock.pinner.get_app_dir")
    def test_ensure_pinned_restores_on_modification(self, mock_app_dir, mock_pinned_bak):
        mock_app_dir.return_value = self.tmp_dir
        mock_pinned_bak.return_value = self.pinned_bak

        init_pin(agy_path=self.agy_path, pinned_version="1.1.9", source_path=self.agy_path)

        # Simulate auto-update modifying agy to version 1.1.13 with different size
        with open(self.agy_path, "wb") as f:
            f.write(b"#!/bin/sh\necho agy version 1.1.13 updated binary payload\n")

        ok, msg, changed = ensure_pinned(agy_path=self.agy_path)
        self.assertTrue(ok)
        self.assertTrue(changed)

        # Verify agy binary was restored back to 1.1.9 backup content (patched)
        with open(self.agy_path, "rb") as f:
            restored = f.read()
        self.assertIn(b"1.1.9", restored)
        self.assertNotIn(b"1.1.13", restored)

    @patch("antigravity_unlock.pinner.get_pinned_backup_path")
    @patch("antigravity_unlock.pinner.get_app_dir")
    def test_enforce_strategy_in_place(self, mock_app_dir, mock_pinned_bak):
        mock_app_dir.return_value = self.tmp_dir
        mock_pinned_bak.return_value = self.pinned_bak

        # Write fresh 1.1.17 dummy content with wildcard signature
        with open(self.agy_path, "wb") as f:
            f.write(b"#!/bin/sh\necho agy version 1.1.17\neligibility check failed\n")

        ok, msg, changed = enforce_strategy(agy_path=self.agy_path, strategy=STRATEGY_IN_PLACE)
        self.assertTrue(ok)
        self.assertTrue(changed)

        with open(self.agy_path, "rb") as f:
            content = f.read()
        self.assertIn(b"1.1.17", content)
        self.assertIn(b"eligibility check bypass", content)

        # Subsequent call detects already patched
        ok2, msg2, changed2 = enforce_strategy(agy_path=self.agy_path, strategy=STRATEGY_IN_PLACE)
        self.assertTrue(ok2)
        self.assertFalse(changed2)

    @patch("antigravity_unlock.pinner.get_pinned_backup_path")
    @patch("antigravity_unlock.pinner.get_app_dir")
    def test_enforce_strategy_auto(self, mock_app_dir, mock_pinned_bak):
        mock_app_dir.return_value = self.tmp_dir
        mock_pinned_bak.return_value = self.pinned_bak

        # 1. Successful in-place in auto mode
        with open(self.agy_path, "wb") as f:
            f.write(b"#!/bin/sh\necho agy version 1.1.17\neligibility check failed\n")

        ok, msg, changed = enforce_strategy(agy_path=self.agy_path, strategy=STRATEGY_AUTO)
        self.assertTrue(ok)
        self.assertTrue(changed)
        with open(self.agy_path, "rb") as f:
            content = f.read()
        self.assertIn(b"1.1.17", content)
        self.assertIn(b"eligibility check bypass", content)

        # 2. Unknown binary without patch signatures falls back to 1.1.9 pinned backup
        with open(self.agy_path, "wb") as f:
            f.write(self.dummy_binary_content)
        init_pin(agy_path=self.agy_path, pinned_version="1.1.9", source_path=self.agy_path)

        with open(self.agy_path, "wb") as f:
            f.write(b"#!/bin/sh\necho agy version 2.0.0 completely different binary without signatures\n")

        ok_fb, msg_fb, changed_fb = enforce_strategy(agy_path=self.agy_path, strategy=STRATEGY_AUTO)
        self.assertTrue(ok_fb)
        self.assertTrue(changed_fb)
        with open(self.agy_path, "rb") as f:
            restored = f.read()
        self.assertIn(b"1.1.9", restored)

    @patch("antigravity_unlock.pinner.get_app_dir")
    def test_set_strategy(self, mock_app_dir):
        mock_app_dir.return_value = self.tmp_dir
        ok, msg = set_strategy(STRATEGY_AUTO)
        self.assertTrue(ok)
        cfg = load_config()
        self.assertEqual(cfg.get("strategy"), STRATEGY_AUTO)

        ok_pin, _ = set_strategy(STRATEGY_PIN)
        self.assertTrue(ok_pin)
        cfg_pin = load_config()
        self.assertEqual(cfg_pin.get("strategy"), STRATEGY_PIN)

        bad_ok, _ = set_strategy("invalid_mode")
        self.assertFalse(bad_ok)


if __name__ == "__main__":
    unittest.main()
