"""
Tests for the layered doctor.

The behavioural contract worth pinning down: no layer may claim the install is
broken on inference alone.  A blocked egress region is a WARN, not a FAIL,
because the client-side patch has been observed to leave the model API usable
from there - only the live agy run gets to decide that.
"""

import subprocess
import unittest
from unittest.mock import patch

from antigravity_unlock import doctor


class TestVersionCompare(unittest.TestCase):
    def test_older(self):
        self.assertTrue(doctor._older("1.1.27", "1.2.7"))
        self.assertTrue(doctor._older("1.1.9", "1.1.27"))
        self.assertFalse(doctor._older("1.2.7", "1.1.27"))
        self.assertFalse(doctor._older("1.2.7", "1.2.7"))

    def test_garbage_versions_do_not_raise(self):
        self.assertFalse(doctor._older("unknown", "1.2.7"))
        self.assertFalse(doctor._older(None, "1.2.7"))


class TestEgressLayer(unittest.TestCase):
    def _run(self, geo):
        with patch.object(doctor, "_fetch_geo", return_value=geo):
            return doctor.check_egress(timeout=1)

    def test_blocked_region_is_a_warning_not_a_failure(self):
        checks, _ = self._run({"ip": "95.26.82.199", "country": "RU", "org": "Vimpelcom"})
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["verdict"], doctor.WARN)
        self.assertIn("RU", checks[0]["summary"])
        # The summary must point at the functional check as the authority.
        self.assertIn("functional", checks[0]["summary"])

    def test_supported_region_is_ok(self):
        checks, geo = self._run({"ip": "45.83.180.242", "country": "EE", "org": "BlueVPS"})
        self.assertEqual(checks[0]["verdict"], doctor.OK)
        self.assertEqual(geo["country"], "EE")

    def test_unknown_geo_is_a_warning(self):
        checks, geo = self._run(None)
        self.assertIsNone(geo)
        self.assertEqual(checks[0]["verdict"], doctor.WARN)

    def test_ip_api_field_names_also_work(self):
        # ip-api.com uses countryCode/query instead of country/ip.
        checks, geo = self._run({"query": "1.2.3.4", "countryCode": "BY", "isp": "x"})
        self.assertEqual(checks[0]["verdict"], doctor.WARN)
        self.assertIn("BY", checks[0]["summary"])


class TestFunctionalLayer(unittest.TestCase):
    """The only layer allowed to declare the unlock working or broken."""

    def _run(self, returncode, stdout="", stderr=""):
        proc = subprocess.CompletedProcess(args=["agy"], returncode=returncode,
                                           stdout=stdout, stderr=stderr)
        with patch.object(doctor.subprocess, "run", return_value=proc):
            return doctor.check_functional(agy_path="/fake/agy", timeout=5)

    def test_real_completion_is_ok(self):
        checks = self._run(0, stdout="DOCTOR_OK\n")
        self.assertEqual(checks[0]["verdict"], doctor.OK)
        self.assertIn("DOCTOR_OK", checks[0]["summary"])

    def test_eligibility_gate_is_a_failure(self):
        checks = self._run(1, stdout=(
            "Eligibility check failed: Your current account is not eligible for "
            "Antigravity, because it is not currently available in your location."
        ))
        self.assertEqual(checks[0]["verdict"], doctor.FAIL)
        self.assertIn("eligibility gate", checks[0]["summary"])
        self.assertIn("antigravity-unlock patch", checks[0]["fix"])

    def test_gate_detected_even_with_zero_exit(self):
        # A zero exit code must not be trusted over the gate text.
        checks = self._run(0, stdout="Account ineligible: region\n")
        self.assertEqual(checks[0]["verdict"], doctor.FAIL)

    def test_other_failure_reports_the_output(self):
        checks = self._run(2, stderr="token is nil\n")
        self.assertEqual(checks[0]["verdict"], doctor.FAIL)
        self.assertIn("token is nil", checks[0]["summary"])

    def test_timeout_is_a_warning_not_a_failure(self):
        with patch.object(doctor.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired(cmd="agy", timeout=5)):
            checks = doctor.check_functional(agy_path="/fake/agy", timeout=5)
        self.assertEqual(checks[0]["verdict"], doctor.WARN)

    def test_missing_binary_is_a_warning(self):
        with patch.object(doctor, "get_primary_agy", return_value=None):
            checks = doctor.check_functional(agy_path=None)
        self.assertEqual(checks[0]["verdict"], doctor.WARN)


class TestReportFormatting(unittest.TestCase):
    def test_report_shows_every_layer_and_its_fix(self):
        layers = [
            {"name": "binary", "verdict": doctor.OK, "summary": "patched", "fix": None},
            {"name": "hosts pin", "verdict": doctor.FAIL, "summary": "dead pin",
             "fix": "sudo antigravity-unlock setup remove"},
        ]
        meta = {"agy_path": "/home/u/.local/bin/agy", "installed_version": "1.2.7",
                "geo": {"ip": "95.26.82.199", "country": "RU", "org": "Vimpelcom"}}
        text = doctor.format_report(doctor.FAIL, layers, meta)
        self.assertIn("[ ok ] binary", text)
        self.assertIn("[FAIL] hosts pin", text)
        self.assertIn("sudo antigravity-unlock setup remove", text)
        self.assertIn("1.2.7", text)
        self.assertIn("95.26.82.199", text)
        self.assertIn("Broken", text)

    def test_overall_is_the_worst_verdict(self):
        self.assertGreater(doctor._RANK[doctor.FAIL], doctor._RANK[doctor.WARN])
        self.assertGreater(doctor._RANK[doctor.WARN], doctor._RANK[doctor.OK])
        worst = max([doctor.OK, doctor.FAIL, doctor.WARN], key=lambda v: doctor._RANK[v])
        self.assertEqual(worst, doctor.FAIL)


class TestRunDoctorSkips(unittest.TestCase):
    def test_skip_flags_are_reported_rather_than_silently_omitted(self):
        with patch.object(doctor, "check_binary", return_value=[]), \
             patch.object(doctor, "check_config", return_value=[]), \
             patch.object(doctor, "check_hosts", return_value=[]):
            overall, layers, meta = doctor.run_doctor(
                timeout=1, skip_network=True, skip_functional=True,
            )
        names = {c["name"]: c for c in layers}
        self.assertIn("network", names)
        self.assertIn("functional", names)
        self.assertEqual(names["network"]["verdict"], doctor.WARN)
        self.assertEqual(names["functional"]["verdict"], doctor.WARN)
        self.assertEqual(overall, doctor.WARN)
        self.assertIsNone(meta["functional_ok"], "skipped is not the same as passed")


def _stub_layers(fail_layer=True, functional_verdict=doctor.OK):
    """Patch every layer so run_doctor can be exercised deterministically."""
    binary = [{"name": "binary", "verdict": doctor.OK, "summary": "patched", "fix": None}]
    hosts = [{
        "name": "hosts pin",
        "verdict": doctor.FAIL if fail_layer else doctor.OK,
        "summary": "dead pin", "fix": "sudo antigravity-unlock setup remove",
    }]
    functional = [{
        "name": "functional", "verdict": functional_verdict,
        "summary": "agy answered", "fix": None,
    }]
    return (
        patch.object(doctor, "check_binary", return_value=binary),
        patch.object(doctor, "check_config", return_value=[]),
        patch.object(doctor, "check_hosts", return_value=hosts),
        patch.object(doctor, "check_functional", return_value=functional),
    )


class TestFunctionalLayerIsAuthoritative(unittest.TestCase):
    """A working agy outranks an inferred FAIL; a broken agy outranks all-OK."""

    def _run(self, fail_layer, functional_verdict):
        p1, p2, p3, p4 = _stub_layers(fail_layer, functional_verdict)
        with p1, p2, p3, p4:
            return doctor.run_doctor(timeout=1, skip_network=True)

    def test_working_agy_downgrades_an_inferred_fail(self):
        overall, layers, meta = self._run(True, doctor.OK)
        self.assertEqual(overall, doctor.WARN)
        self.assertTrue(meta["functional_ok"])
        self.assertEqual(meta["downgraded_from_fail"], ["hosts pin"])
        hosts = next(c for c in layers if c["name"] == "hosts pin")
        self.assertEqual(hosts["verdict"], doctor.WARN)
        self.assertIn("latent problem", hosts["summary"])
        # The actionable command must survive the rewording.
        self.assertEqual(hosts["fix"], "sudo antigravity-unlock setup remove")

    def test_broken_agy_stays_fail_even_with_clean_layers(self):
        overall, layers, meta = self._run(False, doctor.FAIL)
        self.assertEqual(overall, doctor.FAIL)
        self.assertFalse(meta["functional_ok"])
        self.assertEqual(meta["downgraded_from_fail"], [])

    def test_broken_agy_with_dirty_layers_is_still_fail(self):
        overall, _, meta = self._run(True, doctor.FAIL)
        self.assertEqual(overall, doctor.FAIL)
        self.assertFalse(meta["functional_ok"])

    def test_no_override_when_functional_was_skipped(self):
        p1, p2, p3, _ = _stub_layers(True, doctor.OK)
        with p1, p2, p3:
            overall, layers, meta = doctor.run_doctor(
                timeout=1, skip_network=True, skip_functional=True,
            )
        self.assertEqual(overall, doctor.FAIL)
        self.assertIsNone(meta["functional_ok"])

    def test_report_wording_follows_the_override(self):
        overall, layers, meta = self._run(True, doctor.OK)
        text = doctor.format_report(overall, layers, meta)
        self.assertIn("agy works end-to-end", text)
        self.assertNotIn("Broken", text)

    def test_report_wording_when_broken(self):
        overall, layers, meta = self._run(True, doctor.FAIL)
        text = doctor.format_report(overall, layers, meta)
        self.assertIn("Broken", text)
        self.assertNotIn("agy works end-to-end", text)


if __name__ == "__main__":
    unittest.main()
