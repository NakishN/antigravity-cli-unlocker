"""
Tests for Split-Tunnel MITM Proxy domain filtering and eligibility rewriting.
"""

import unittest
import asyncio

from antigravity_unlock.proxy import (
    SplitTunnelProxy,
    SMART_DNS_PRIMARY,
    DIRECT_DOMAINS,
    _rewrite_eligibility,
    _should_intercept_url,
    resolve_smart_dns,
)


class TestProxy(unittest.TestCase):

    def test_proxy_domain_routing(self):
        """Accounts/OAuth domains route directly; generative AI domains resolve via Smart DNS."""
        proxy = SplitTunnelProxy()

        async def run_checks():
            # Direct domains must return hostname unchanged (pass-through TCP tunnel)
            for direct in ["accounts.google.com", "oauth2.googleapis.com"]:
                result = await proxy.resolve_smart(direct)
                self.assertEqual(result, direct, f"{direct} should be direct, got {result!r}")

            # AI domains must resolve to an IP (not the hostname itself)
            ai_result = await proxy.resolve_smart("generativelanguage.googleapis.com")
            self.assertNotEqual(ai_result, "generativelanguage.googleapis.com",
                                "AI domain should resolve to an IP, not return hostname")

        asyncio.run(run_checks())

    def test_direct_domain_detection(self):
        """_is_direct correctly identifies accounts domains."""
        proxy = SplitTunnelProxy()
        self.assertTrue(proxy._is_direct("accounts.google.com"))
        self.assertTrue(proxy._is_direct("oauth2.googleapis.com"))
        self.assertFalse(proxy._is_direct("daily-cloudcode-pa.googleapis.com"))
        self.assertFalse(proxy._is_direct("generativelanguage.googleapis.com"))

    def test_mitm_domain_detection(self):
        """_should_mitm correctly identifies domains needing TLS interception."""
        proxy = SplitTunnelProxy()
        self.assertTrue(proxy._should_mitm("daily-cloudcode-pa.googleapis.com"))
        self.assertTrue(proxy._should_mitm("generativelanguage.googleapis.com"))
        # Direct domains should NOT be MITM'd
        self.assertFalse(proxy._should_mitm("accounts.google.com"))
        self.assertFalse(proxy._should_mitm("oauth2.googleapis.com"))

    def test_eligibility_url_detection(self):
        """_should_intercept_url identifies eligibility API paths."""
        self.assertTrue(_should_intercept_url("/v1internal:loadCodeAssist"))
        self.assertTrue(_should_intercept_url("/v1internal:checkEligibility"))
        self.assertFalse(_should_intercept_url("/v1/models"))
        self.assertFalse(_should_intercept_url("/auth/token"))

    def test_eligibility_json_rewrite(self):
        """_rewrite_eligibility rewrites NOT_ELIGIBLE JSON responses."""
        import json

        ineligible_response = json.dumps({
            "eligibilityStatus": "NOT_ELIGIBLE_REGION_OUT_OF_SCOPE",
            "message": "not eligible for Antigravity",
        }).encode("utf-8")

        rewritten, changed = _rewrite_eligibility(ineligible_response)
        self.assertTrue(changed, "Should have rewritten the eligibility response")

        obj = json.loads(rewritten)
        self.assertEqual(obj["eligibilityStatus"], "ELIGIBLE")

    def test_eligible_response_unchanged(self):
        """_rewrite_eligibility does not modify already-eligible responses."""
        import json

        eligible_response = json.dumps({
            "eligibilityStatus": "ELIGIBLE",
            "tier": "PRO",
        }).encode("utf-8")

        rewritten, changed = _rewrite_eligibility(eligible_response)
        self.assertFalse(changed, "Should NOT modify an already-eligible response")

    def test_binary_pattern_rewrite(self):
        """_rewrite_eligibility handles raw binary NOT_ELIGIBLE patterns."""
        raw = b'{"status": "' + b'NOT_ELIGIBLE_REGION_OUT_OF_SCOPE' + b'"}'
        rewritten, changed = _rewrite_eligibility(raw)
        self.assertTrue(changed)
        self.assertNotIn(b"NOT_ELIGIBLE", rewritten)


if __name__ == "__main__":
    unittest.main()
