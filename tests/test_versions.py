"""
Tests for the versions.json registry.

These are pure-metadata checks (no agy binary required), guarding against
regressions where a version entry references a wildcard pattern that does not
exist, or where verified-version support is accidentally dropped.
"""

import unittest

from antigravity_unlock.patcher import load_versions_db


class TestVersionsRegistry(unittest.TestCase):
    def setUp(self):
        self.vdb = load_versions_db()

    def test_registry_loads(self):
        self.assertIn("versions", self.vdb)
        self.assertIn("wildcard_patterns", self.vdb)
        self.assertTrue(self.vdb["wildcard_patterns"], "top-level wildcard_patterns is empty")

    def test_1_1_19_supported(self):
        versions = self.vdb["versions"]
        self.assertIn("1.1.19", versions, "1.1.19 must be a registered/verified version")
        patterns = versions["1.1.19"].get("wildcard_patterns", [])
        # The two machine-code gates are the real unlock; both must be referenced.
        self.assertIn("eligibility_error_gate", patterns)
        self.assertIn("ineligibility_from_result_gate", patterns)

    def test_1_1_22_and_1_1_27_supported(self):
        versions = self.vdb["versions"]
        for ver in ("1.1.22", "1.1.27"):
            self.assertIn(ver, versions, f"{ver} must be a registered/verified version")
            patterns = versions[ver].get("wildcard_patterns", [])
            self.assertIn("eligibility_error_gate", patterns)
            self.assertIn("ineligibility_from_result_gate", patterns)

    def test_version_pattern_references_resolve(self):
        """Every pattern name referenced by a version must be defined at top level."""
        defined = {wp["name"] for wp in self.vdb["wildcard_patterns"]}
        for vname, vinfo in self.vdb["versions"].items():
            for pname in vinfo.get("wildcard_patterns", []):
                self.assertIn(
                    pname,
                    defined,
                    f"version {vname} references undefined pattern '{pname}'",
                )

    def test_wildcard_patterns_are_size_preserving(self):
        """Wildcard replacements must preserve binary size (equal hex length)."""
        for wp in self.vdb["wildcard_patterns"]:
            self.assertEqual(
                len(wp["pattern"]),
                len(wp["replacement"]),
                f"pattern '{wp['name']}' changes binary size",
            )
            # valid hex on both sides
            bytes.fromhex(wp["pattern"])
            bytes.fromhex(wp["replacement"])


if __name__ == "__main__":
    unittest.main()
