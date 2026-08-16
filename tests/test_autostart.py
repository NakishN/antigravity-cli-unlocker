"""
Tests for Autostart module (autostart.py).
"""

import unittest
from antigravity_unlock.autostart import (
    render_systemd_unit,
    render_launch_agent_plist,
    resolve_guardian_command,
    autostart_status,
    SERVICE_NAME,
    LAUNCH_AGENT_LABEL,
)


class TestAutostart(unittest.TestCase):

    def test_render_systemd_unit(self):
        cmd = ["/usr/bin/python3", "-m", "antigravity_unlock", "guardian"]
        unit = render_systemd_unit(cmd)
        self.assertIn("[Unit]", unit)
        self.assertIn("[Service]", unit)
        self.assertIn("ExecStart=/usr/bin/python3 -m antigravity_unlock guardian", unit)
        self.assertIn("Restart=always", unit)

    def test_render_launch_agent_plist(self):
        cmd = ["/usr/bin/python3", "-m", "antigravity_unlock", "guardian"]
        plist = render_launch_agent_plist(cmd)
        self.assertIn("<plist version=\"1.0\">", plist)
        self.assertIn(LAUNCH_AGENT_LABEL, plist)
        self.assertIn("<string>/usr/bin/python3</string>", plist)
        self.assertIn("<key>KeepAlive</key>", plist)

    def test_resolve_guardian_command(self):
        cmd = resolve_guardian_command()
        self.assertIsInstance(cmd, list)
        self.assertGreaterEqual(len(cmd), 2)
        self.assertEqual(cmd[-1], "guardian")

    def test_autostart_status(self):
        status = autostart_status()
        self.assertIn("platform", status)
        self.assertIn("installed", status)
        self.assertIn("active", status)
        self.assertIn("command", status)


if __name__ == "__main__":
    unittest.main()
