"""
Tests for the shell-profile hook.

The block goes into a file the user owns and did not ask us to create, next to
lines we must not touch.  ``hosts_cleanup`` exists because 1.4.x wrote unmarked
lines into ``/etc/hosts`` that a later ``unpin()`` could no longer find; these
tests are here so the same mistake cannot be made twice in a dotfile.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from antigravity_unlock import shellhook

PROFILE = """\
# ~/.bashrc: executed by bash(1) for non-login shells.
export EDITOR=vim
alias ll='ls -la'

# my own proxy, unrelated
export EDITOR=nano
"""


class HookTestCase(unittest.TestCase):
    def setUp(self):
        # Not $HOME: a test that litters the developer's real home directory
        # gets "cleaned up" by deleting a file the user may have created.
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.path = os.path.join(self.tmp, "profile")

        # The hook refuses to write unless agy actually reads AG_LS_PROXY.
        isolated = patch.object(shellhook, "proxy_var_is_isolated", return_value=True)
        isolated.start()
        self.addCleanup(isolated.stop)

        # Hermetic: install() falls back to discovering agy itself, and these
        # tests must not depend on whether this machine happens to have one.
        finder = patch.object(shellhook, "get_primary_agy", return_value="/fake/agy")
        finder.start()
        self.addCleanup(finder.stop)

    def _write(self, text=PROFILE):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _read(self):
        with open(self.path, "r", encoding="utf-8") as handle:
            return handle.read()


class TestInstall(HookTestCase):
    def test_writes_a_marked_block(self):
        self._write()
        ok, msg = shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        self.assertTrue(ok, msg)
        text = self._read()
        self.assertIn(shellhook.HOOK_BEGIN, text)
        self.assertIn(shellhook.HOOK_END, text)
        self.assertIn('export AG_LS_PROXY="socks5h://127.0.0.1:40000"', text)

    def test_existing_lines_survive_untouched(self):
        self._write()
        shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        text = self._read()
        for line in PROFILE.strip().splitlines():
            self.assertIn(line, text)

    def test_reinstall_is_idempotent(self):
        self._write()
        shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        ok, msg = shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        self.assertTrue(ok)
        self.assertIn("already up to date", msg)
        self.assertEqual(self._read().count(shellhook.HOOK_BEGIN), 1)

    def test_changing_route_updates_in_place(self):
        # Two blocks would leave the last export winning by accident, and
        # 'remove' would only delete one of them.
        self._write()
        shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        shellhook.install("socks5h://10.0.0.5:1080", path=self.path)
        text = self._read()
        self.assertEqual(text.count(shellhook.HOOK_BEGIN), 1)
        self.assertIn("10.0.0.5:1080", text)
        self.assertNotIn("40000", text)

    def test_creates_a_missing_profile(self):
        ok, _ = shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        self.assertTrue(ok)
        self.assertTrue(os.path.isfile(self.path))

    def test_refuses_without_the_rename_patch(self):
        # Without proxy_var_isolation, agy does not read AG_LS_PROXY at all, and
        # the only variable it does read (https_proxy) would drag git, curl and
        # every other tool through the tunnel.
        self._write()
        with patch.object(shellhook, "proxy_var_is_isolated", return_value=False):
            ok, msg = shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        self.assertFalse(ok)
        self.assertIn("proxy_var_isolation", msg)
        self.assertNotIn(shellhook.HOOK_BEGIN, self._read())

    def test_refuses_when_no_agy_can_be_found(self):
        # Unverifiable means unwritable: a block nobody can confirm agy reads
        # would look installed and be silently ignored.
        self._write()
        with patch.object(shellhook, "get_primary_agy", return_value=None):
            ok, msg = shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        self.assertFalse(ok)
        self.assertIn("no agy binary", msg)
        self.assertNotIn(shellhook.HOOK_BEGIN, self._read())

    def test_empty_url_is_rejected(self):
        ok, msg = shellhook.install("", path=self.path)
        self.assertFalse(ok)
        self.assertIn("no route URL", msg)


class TestRemove(HookTestCase):
    def test_removes_only_the_block(self):
        self._write()
        shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        ok, msg = shellhook.remove(path=self.path)
        self.assertTrue(ok, msg)
        text = self._read()
        self.assertNotIn(shellhook.HOOK_BEGIN, text)
        self.assertNotIn("AG_LS_PROXY", text)
        for line in PROFILE.strip().splitlines():
            self.assertIn(line, text)

    def test_remove_is_safe_when_absent(self):
        self._write()
        ok, msg = shellhook.remove(path=self.path)
        self.assertTrue(ok)
        self.assertIn("nothing to remove", msg)
        self.assertEqual(self._read(), PROFILE)

    def test_remove_on_missing_file(self):
        ok, msg = shellhook.remove(path=os.path.join(os.path.dirname(self.path), "nope"))
        self.assertFalse(ok)
        self.assertIn("does not exist", msg)

    def test_install_remove_round_trip_leaves_no_residue(self):
        self._write()
        shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        shellhook.remove(path=self.path)
        shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        self.assertEqual(self._read().count(shellhook.HOOK_BEGIN), 1)


class TestReadBack(HookTestCase):
    def test_current_url_reads_the_value(self):
        self._write()
        shellhook.install("socks5h://127.0.0.1:40000", path=self.path)
        self.assertEqual(
            shellhook.current_url(self.path), "socks5h://127.0.0.1:40000"
        )

    def test_current_url_without_a_block(self):
        self._write()
        self.assertIsNone(shellhook.current_url(self.path))

    def test_current_url_on_missing_file(self):
        self.assertIsNone(shellhook.current_url(os.path.join(os.path.dirname(self.path), "nope")))

    def test_find_block_returns_none_without_markers(self):
        self.assertIsNone(shellhook.find_block("export FOO=bar\n"))

    def test_find_block_needs_both_markers(self):
        # A half-written block must not be treated as ours.
        self.assertIsNone(shellhook.find_block(shellhook.HOOK_BEGIN + "\nexport X=1\n"))

    def test_credentials_are_not_written_in_clear_when_already_redacted(self):
        self._write()
        shellhook.install("socks5h://user:pass@host:1080", path=self.path)
        self.assertIn("user:pass@host", self._read())


class TestProfilePath(unittest.TestCase):
    def test_bash(self):
        with patch.dict(os.environ, {"HOME": os.path.expanduser("~"), "SHELL": "/bin/bash"}):
            path = shellhook.profile_path("bash")
        self.assertTrue(path.endswith(".bashrc") or path.endswith(".profile"))

    def test_zsh(self):
        self.assertEqual(shellhook.profile_path("zsh"),
                         os.path.join(os.path.expanduser("~"), ".zshrc"))

    def test_fish_is_not_supported(self):
        # fish syntax is not POSIX export; writing one would produce a config
        # that fails to load.
        self.assertIsNone(shellhook.profile_path("fish"))

    def test_unknown_shell_is_not_supported(self):
        self.assertIsNone(shellhook.profile_path("tcsh"))


class TestAmbientConflict(unittest.TestCase):
    def test_reports_upper_case_proxy(self):
        # The rename covers the lower-case literal only, so an exported
        # HTTPS_PROXY still wins over AG_LS_PROXY and silently defeats the hook.
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://other:3128"}, clear=True):
            self.assertEqual(shellhook.ambient_proxy_conflict(),
                             ("HTTPS_PROXY", "http://other:3128"))

    def test_no_conflict_when_clean(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(shellhook.ambient_proxy_conflict())


if __name__ == "__main__":
    unittest.main()
