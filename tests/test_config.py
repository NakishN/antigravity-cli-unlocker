"""
Tests for config defaults and the pre-1.5 migration.

The migration exists because of a real incident: agy self-updated to 1.2.7 while
the config still read ``strategy: pin`` / ``pinned_version: 1.1.27``, so the next
guardian tick would have replaced a working binary with a months-old one.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from antigravity_unlock import config as cfgmod


class TestConfigDefaults(unittest.TestCase):
    def test_default_strategy_does_not_downgrade(self):
        self.assertEqual(cfgmod.DEFAULT_STRATEGY, cfgmod.STRATEGY_IN_PLACE)

    def test_pin_fallback_is_opt_in(self):
        self.assertFalse(cfgmod.DEFAULT_CONFIG["allow_pin_fallback"])

    def test_optional_patterns_are_opt_in(self):
        self.assertFalse(cfgmod.DEFAULT_CONFIG["include_optional"])


class TestMigrateConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        patcher = patch.object(cfgmod, "get_app_dir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_config(self, data):
        with open(os.path.join(self.tmp, "config.json"), "w") as f:
            json.dump(data, f)

    def _read_config(self):
        with open(os.path.join(self.tmp, "config.json")) as f:
            return json.load(f)

    def test_pin_older_than_installed_is_cleared(self):
        self._write_config({"strategy": "pin", "pinned_version": "1.1.27"})
        changed, cfg, notes = cfgmod.migrate_config(installed_version="1.2.7")
        self.assertTrue(changed)
        self.assertEqual(cfg["strategy"], "in_place")
        self.assertTrue(any("downgrade" in n for n in notes), notes)

    def test_pin_newer_than_installed_is_preserved(self):
        # A deliberate forward pin is the user's choice, not a footgun.
        self._write_config({"strategy": "pin", "pinned_version": "1.3.0"})
        changed, cfg, notes = cfgmod.migrate_config(installed_version="1.2.7")
        self.assertEqual(cfg["strategy"], "pin")

    def test_pin_preserved_when_installed_version_unknown(self):
        self._write_config({"strategy": "pin", "pinned_version": "1.1.27"})
        _, cfg, _ = cfgmod.migrate_config(installed_version=None)
        self.assertEqual(cfg["strategy"], "pin")

    def test_unparseable_pinned_version_is_preserved(self):
        # Cannot prove a downgrade => must not touch the user's strategy.
        self._write_config({"strategy": "pin", "pinned_version": "nightly"})
        _, cfg, _ = cfgmod.migrate_config(installed_version="1.2.7")
        self.assertEqual(cfg["strategy"], "pin")

    def test_unparseable_installed_version_is_preserved(self):
        self._write_config({"strategy": "pin", "pinned_version": "1.1.27"})
        _, cfg, _ = cfgmod.migrate_config(installed_version="unknown")
        self.assertEqual(cfg["strategy"], "pin")

    def test_missing_keys_are_filled_and_persisted(self):
        self._write_config({"strategy": "in_place"})
        changed, cfg, notes = cfgmod.migrate_config(installed_version="1.2.7")
        self.assertTrue(changed)
        for key in ("allow_pin_fallback", "include_optional", "auto_patch",
                    "check_interval_seconds"):
            self.assertIn(key, cfg)
        # Persisted, not just merged in memory, so the user can see and edit them.
        self.assertIn("allow_pin_fallback", self._read_config())

    def test_idempotent(self):
        self._write_config({"strategy": "pin", "pinned_version": "1.1.27"})
        cfgmod.migrate_config(installed_version="1.2.7")
        changed_again, cfg, notes = cfgmod.migrate_config(installed_version="1.2.7")
        self.assertFalse(changed_again, f"second run should be a no-op, got {notes}")
        self.assertEqual(cfg["strategy"], "in_place")

    def test_explicitly_set_options_survive_migration(self):
        self._write_config({
            "strategy": "in_place",
            "allow_pin_fallback": True,
            "include_optional": True,
        })
        _, cfg, _ = cfgmod.migrate_config(installed_version="1.2.7")
        self.assertTrue(cfg["allow_pin_fallback"])
        self.assertTrue(cfg["include_optional"])

    def test_no_config_file_yields_defaults(self):
        changed, cfg, notes = cfgmod.migrate_config(installed_version="1.2.7")
        self.assertEqual(cfg["strategy"], cfgmod.DEFAULT_STRATEGY)


if __name__ == "__main__":
    unittest.main()
