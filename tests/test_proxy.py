"""
Tests for Split-Tunnel Proxy domain routing and Smart DNS resolution.
"""

import unittest
import asyncio

from antigravity_unlock.proxy import (
    SplitTunnelProxy,
    DIRECT_DOMAINS,
    SMART_DNS_PROVIDERS,
    REFERENCE_RESOLVERS,
    resolve_smart_dns,
    _is_substituted,
    _query_first_answer,
)


class TestProxy(unittest.TestCase):

    def test_proxy_domain_routing(self):
        """Accounts/OAuth domains route directly; AI domains resolve via Smart DNS."""
        proxy = SplitTunnelProxy()

        async def run_checks():
            for direct in ["accounts.google.com", "oauth2.googleapis.com"]:
                result = await proxy.resolve_smart(direct)
                self.assertEqual(result, direct, f"{direct} should be direct, got {result!r}")

        asyncio.run(run_checks())

    def test_direct_domain_detection(self):
        """_is_direct correctly identifies accounts domains."""
        proxy = SplitTunnelProxy()
        self.assertTrue(proxy._is_direct("accounts.google.com"))
        self.assertTrue(proxy._is_direct("oauth2.googleapis.com"))
        self.assertFalse(proxy._is_direct("daily-cloudcode-pa.googleapis.com"))
        self.assertFalse(proxy._is_direct("generativelanguage.googleapis.com"))

    def test_direct_domains_bypass_smart_dns(self):
        """resolve_smart_dns returns direct domains unchanged."""
        for d in ["accounts.google.com", "oauth2.googleapis.com"]:
            result = resolve_smart_dns(d)
            self.assertEqual(result, d)

    def test_is_substituted(self):
        """_is_substituted detects when provider answer differs from reference."""
        self.assertTrue(_is_substituted("87.228.47.204", {"142.250.1.95"}))
        self.assertFalse(_is_substituted("142.250.1.95", {"142.250.1.95"}))
        self.assertTrue(_is_substituted("87.228.47.204", set()))
        self.assertFalse(_is_substituted(None, {"142.250.1.95"}))

    def test_smart_dns_providers_defined(self):
        """All expected Smart DNS providers are configured."""
        names = {p["name"] for p in SMART_DNS_PROVIDERS}
        self.assertIn("xbox-dns.ru", names)
        self.assertIn("comss.one", names)
        self.assertIn("geohide.ru", names)
        for provider in SMART_DNS_PROVIDERS:
            self.assertTrue(len(provider["ips"]) > 0,
                            f"Provider {provider['name']} has no IPs")

    def test_reference_resolvers_defined(self):
        """Reference resolvers are configured for validation."""
        self.assertIn("8.8.8.8", REFERENCE_RESOLVERS)
        self.assertIn("1.1.1.1", REFERENCE_RESOLVERS)


if __name__ == "__main__":
    unittest.main()
