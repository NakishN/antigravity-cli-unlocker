"""
Tests for the removal-only /etc/hosts cleanup.

The point of this module is that upgrading to 1.5.0 must not strand anyone with
pin entries they can no longer remove - including the unmarked lines written by
releases old enough that ``unpin()`` could not see them.
"""

import os
import tempfile
import unittest

from antigravity_unlock import hosts_cleanup as hc


CLEAN_HOSTS = """127.0.0.1 localhost
127.0.1.1 kanawaka

# The following lines are desirable for IPv6 capable hosts
::1     ip6-localhost ip6-loopback
fe00::0 ip6-localnet

0.0.0.0 log-upload-os.hoyoverse.com
"""

# The exact state found on a real machine on 2026-09-20: four unmarked lines,
# duplicated, pointing at a front end that no longer completes a TLS handshake.
ORPHAN_HOSTS = CLEAN_HOSTS + """
45.155.204.190 daily-cloudcode-pa.googleapis.com
45.155.204.190 cloudcode-pa.googleapis.com
45.155.204.190 daily-cloudcode-pa.googleapis.com
45.155.204.190 cloudcode-pa.googleapis.com
"""

MARKED_HOSTS = CLEAN_HOSTS + """# === antigravity-unlocker SNI proxy pin ===
45.155.204.190 daily-cloudcode-pa.googleapis.com
45.155.204.190 cloudcode-pa.googleapis.com
45.155.204.190 generativelanguage.googleapis.com
# === end antigravity-unlocker SNI proxy pin ===
"""


class _HostsFileMixin:
    def setUp(self):
        f = tempfile.NamedTemporaryFile("w", delete=False, suffix=".hosts")
        f.write(CLEAN_HOSTS)
        f.close()
        self.path = f.name
        self.addCleanup(os.unlink, self.path)

    def _read(self):
        with open(self.path) as f:
            return f.read()

    def _write(self, content):
        with open(self.path, "w") as f:
            f.write(content)


class TestFindPins(_HostsFileMixin, unittest.TestCase):
    def test_clean_file_has_no_pins(self):
        self.assertEqual(hc.find_pins(CLEAN_HOSTS, path=self.path), [])
        self.assertFalse(hc.is_pinned(path=self.path))

    def test_detects_unmarked_orphans(self):
        pins = hc.find_pins(ORPHAN_HOSTS, path=self.path)
        self.assertEqual(len(pins), 4)
        self.assertTrue(all(marked is False for _, _, marked in pins))

    def test_detects_marked_block_and_flags_it_as_marked(self):
        pins = hc.find_pins(MARKED_HOSTS, path=self.path)
        self.assertEqual(len(pins), 3)
        self.assertTrue(all(marked for _, _, marked in pins))

    def test_ignores_unrelated_entries(self):
        pins = hc.find_pins(ORPHAN_HOSTS, path=self.path)
        for _, line, _ in pins:
            self.assertNotIn("hoyoverse", line)
            self.assertNotIn("localhost", line)

    def test_commented_out_pin_is_not_a_pin(self):
        content = CLEAN_HOSTS + "# 45.155.204.190 cloudcode-pa.googleapis.com\n"
        self.assertEqual(hc.find_pins(content, path=self.path), [])


class TestUnpin(_HostsFileMixin, unittest.TestCase):
    def test_removes_orphans(self):
        self._write(ORPHAN_HOSTS)
        removed, msg = hc.unpin(path=self.path)
        self.assertEqual(removed, 4)
        self.assertNotIn("45.155.204.190", self._read())

    def test_removes_marked_block_including_markers(self):
        self._write(MARKED_HOSTS)
        removed, msg = hc.unpin(path=self.path)
        self.assertEqual(removed, 3)
        content = self._read()
        self.assertNotIn(hc.MARKER_BEGIN, content)
        self.assertNotIn(hc.MARKER_END, content)
        self.assertNotIn("45.155.204.190", content)
        self.assertIn("marked block", msg)

    def test_preserves_unrelated_lines_exactly(self):
        self._write(ORPHAN_HOSTS)
        hc.unpin(path=self.path)
        content = self._read()
        for keep in ("127.0.0.1 localhost", "127.0.1.1 kanawaka",
                     "::1     ip6-localhost ip6-loopback", "fe00::0 ip6-localnet",
                     "0.0.0.0 log-upload-os.hoyoverse.com",
                     "# The following lines are desirable for IPv6 capable hosts"):
            self.assertIn(keep, content, f"unrelated line was dropped: {keep!r}")

    def test_noop_on_clean_file(self):
        self._write(CLEAN_HOSTS)
        before = self._read()
        removed, msg = hc.unpin(path=self.path)
        self.assertEqual(removed, 0)
        self.assertIn("No pin entries", msg)
        self.assertEqual(self._read(), before)

    def test_idempotent(self):
        self._write(ORPHAN_HOSTS)
        hc.unpin(path=self.path)
        removed, _ = hc.unpin(path=self.path)
        self.assertEqual(removed, 0)

    def test_handles_orphans_and_marked_block_together(self):
        # A machine that ran both an old unmarked release and a later marked one.
        self._write(ORPHAN_HOSTS + "\n" + MARKED_HOSTS[len(CLEAN_HOSTS):])
        removed, _ = hc.unpin(path=self.path)
        self.assertGreaterEqual(removed, 7)
        self.assertNotIn("45.155.204.190", self._read())
        self.assertNotIn(hc.MARKER_BEGIN, self._read())


class TestModuleCannotCreatePins(unittest.TestCase):
    """The layer was removed, not just disabled - there must be no way back."""

    def test_no_write_or_pin_entrypoint(self):
        for forbidden in ("pin", "PROXY_IPS", "probe_endpoint", "_build_block"):
            self.assertFalse(
                hasattr(hc, forbidden),
                f"hosts_cleanup must not expose {forbidden!r}; it is removal-only",
            )

    def test_only_known_public_names(self):
        public = {n for n in dir(hc) if not n.startswith("_")}
        self.assertTrue({"find_pins", "unpin", "is_pinned", "remove_block"} <= public)


if __name__ == "__main__":
    unittest.main()
