"""
Tests for Split-Tunnel Proxy domain filtering rules.
"""

import unittest
import asyncio
from antigravity_unlock.proxy import SplitTunnelProxy, SMART_DNS_PRIMARY

class TestProxy(unittest.TestCase):
    def test_proxy_domain_routing(self):
        proxy = SplitTunnelProxy()
        
        async def run_checks():
            # Accounts domains must resolve directly
            self.assertEqual(await proxy.resolve_smart("accounts.google.com"), "accounts.google.com")
            self.assertEqual(await proxy.resolve_smart("oauth2.googleapis.com"), "oauth2.googleapis.com")

            # Generative AI domains must resolve via Smart DNS endpoint
            self.assertEqual(await proxy.resolve_smart("generativelanguage.googleapis.com"), SMART_DNS_PRIMARY)

        asyncio.run(run_checks())

if __name__ == "__main__":
    unittest.main()
