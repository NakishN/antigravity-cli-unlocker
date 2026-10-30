"""
Tests for the root-level dnspin autopin timer.

The timer writes system units/launchd plists/scheduled tasks, so these tests
never touch the real system: platform and the command runner are mocked, and the
unit directories are redirected to tmp paths. The thing worth testing is the
rendered content and the install/verify logic, not systemd itself.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from antigravity_unlock import cli, dnspin_timer


def _ok(stdout="", stderr=""):
    return SimpleNamespace(returncode=0, stdout=stdout, stderr=stderr)


def _fail(stderr="failed"):
    return SimpleNamespace(returncode=1, stdout="", stderr=stderr)


class TestRendering(unittest.TestCase):
    def test_systemd_service_contains_the_sync_command(self):
        unit = dnspin_timer.render_systemd_service(
            ["/home/u/.local/bin/antigravity-unlock", "dnspin", "sync-hosts"]
        )
        self.assertIn("Type=oneshot", unit)
        self.assertIn(
            "ExecStart=/home/u/.local/bin/antigravity-unlock dnspin sync-hosts", unit
        )

    def test_systemd_service_quotes_paths_with_spaces(self):
        unit = dnspin_timer.render_systemd_service(
            ["/opt/my tools/antigravity-unlock", "dnspin", "sync-hosts"]
        )
        self.assertIn('"/opt/my tools/antigravity-unlock"', unit)

    def test_systemd_timer_uses_the_interval_and_clamps_it(self):
        unit = dnspin_timer.render_systemd_timer(1200)
        self.assertIn("OnUnitActiveSec=1200s", unit)
        clamped = dnspin_timer.render_systemd_timer(5)
        self.assertIn(f"OnUnitActiveSec={dnspin_timer.MIN_INTERVAL_SECONDS}s", clamped)

    def test_parse_systemd_interval_round_trips(self):
        unit = dnspin_timer.render_systemd_timer(777)
        self.assertEqual(dnspin_timer.parse_systemd_interval(unit), 777)
        self.assertIsNone(dnspin_timer.parse_systemd_interval(""))

    def test_launch_daemon_plist_escapes_arguments(self):
        plist = dnspin_timer.render_launch_daemon_plist(
            ["/opt/a&b/antigravity-unlock", "dnspin", "sync-hosts"], 900
        )
        self.assertIn("com.antigravity.unlocker.dnspin", plist)
        self.assertIn("&amp;", plist)
        self.assertIn("<key>StartInterval</key>", plist)
        self.assertIn("<integer>900</integer>", plist)
        self.assertIn("<key>RunAtLoad</key>", plist)

    def test_parse_launch_daemon_interval(self):
        plist = dnspin_timer.render_launch_daemon_plist(["/x/antigravity-unlock"], 600)
        self.assertEqual(dnspin_timer.parse_launch_daemon_interval(plist), 600)
        self.assertIsNone(dnspin_timer.parse_launch_daemon_interval(""))

    def test_clamp_interval_rejects_garbage(self):
        self.assertEqual(
            dnspin_timer.clamp_interval("nope"), dnspin_timer.DEFAULT_INTERVAL_SECONDS
        )
        self.assertEqual(
            dnspin_timer.clamp_interval(10), dnspin_timer.MIN_INTERVAL_SECONDS
        )


class TestResolveCommand(unittest.TestCase):
    def test_absolute_executable_is_used_as_is(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "antigravity-unlock")
            with open(exe, "w", encoding="utf-8") as f:
                f.write("#!/bin/sh\n")
            os.chmod(exe, 0o755)
            command = dnspin_timer.resolve_cli_command(argv0=exe)
        self.assertEqual(command, [exe, "dnspin", "sync-hosts"])

    def test_python_module_falls_back_to_dash_m(self):
        with patch.object(dnspin_timer.shutil, "which", return_value=None):
            command = dnspin_timer.resolve_cli_command(argv0="/x/__main__.py")
        self.assertEqual(
            command, [sys.executable, "-m", "antigravity_unlock", "dnspin", "sync-hosts"]
        )

    def test_appimage_environment_wins(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            image = os.path.join(tmp, "App.AppImage")
            with open(image, "w", encoding="utf-8") as f:
                f.write("")
            with patch.dict(os.environ, {"APPIMAGE": image}):
                command = dnspin_timer.resolve_cli_command(argv0="/x/__main__.py")
        self.assertEqual(command, [image, "dnspin", "sync-hosts"])

    def test_temporary_mount_is_rejected(self):
        self.assertTrue(dnspin_timer._is_temporary_path("/tmp/.mount_abc/AppRun"))
        self.assertTrue(dnspin_timer._is_temporary_path("/tmp/_MEI123/antigravity"))
        self.assertFalse(dnspin_timer._is_temporary_path("/home/u/.local/bin/agy"))


class TestRunCommand(unittest.TestCase):
    def test_missing_tool_is_reported_not_raised(self):
        with patch.object(dnspin_timer.subprocess, "run", side_effect=FileNotFoundError("systemctl")):
            result = dnspin_timer._run_command(["systemctl", "daemon-reload"])
        self.assertEqual(result.returncode, 127)
        self.assertIn("systemctl", result.stderr)


class TestInstallLinux(unittest.TestCase):
    def _install(self, tmp, runner, interval=900, command=None):
        with patch.object(dnspin_timer.platform, "system", return_value="Linux"), \
             patch.object(dnspin_timer.os, "geteuid", return_value=0, create=True), \
             patch.object(dnspin_timer, "_systemd_dir", return_value=tmp), \
             patch.object(dnspin_timer, "_run_command", side_effect=runner):
            return dnspin_timer.install_autopin(interval, command=command)

    def test_install_writes_units_and_starts_the_timer(self):
        import tempfile

        calls = []

        def runner(command):
            calls.append(command)
            return _ok(stdout="active")

        with tempfile.TemporaryDirectory() as tmp:
            ok, message = self._install(
                tmp, runner,
                command=["/home/u/.local/bin/antigravity-unlock", "dnspin", "sync-hosts"],
            )
            service = os.path.join(tmp, dnspin_timer.SERVICE_NAME + ".service")
            timer = os.path.join(tmp, dnspin_timer.TIMER_NAME)
            self.assertTrue(ok, message)
            self.assertTrue(os.path.exists(service))
            self.assertTrue(os.path.exists(timer))
            with open(timer, encoding="utf-8") as f:
                self.assertIn("OnUnitActiveSec=900s", f.read())

        self.assertIn(["systemctl", "daemon-reload"], calls)
        self.assertIn(["systemctl", "enable", "--now", dnspin_timer.TIMER_NAME], calls)
        self.assertIn(
            ["systemctl", "start", dnspin_timer.SERVICE_NAME + ".service"], calls
        )
        self.assertIn(["systemctl", "is-active", dnspin_timer.TIMER_NAME], calls)

    def test_install_refuses_without_root(self):
        with patch.object(dnspin_timer.platform, "system", return_value="Linux"), \
             patch.object(dnspin_timer.os, "geteuid", return_value=1000, create=True):
            ok, message = dnspin_timer.install_autopin(900, command=["/x/antigravity-unlock"])
        self.assertFalse(ok)
        self.assertIn("sudo", message)

    @unittest.skipUnless(hasattr(os, "geteuid"), "POSIX root guard")
    def test_install_reports_a_dead_timer(self):
        import tempfile

        def runner(command):
            if command[-1] == dnspin_timer.TIMER_NAME and command[1] == "is-active":
                return _fail(stderr="inactive")
            return _ok()

        with tempfile.TemporaryDirectory() as tmp:
            ok, message = self._install(
                tmp, runner, command=["/x/antigravity-unlock", "dnspin", "sync-hosts"]
            )
        self.assertFalse(ok)
        self.assertIn("not active", message)

    def test_install_without_a_stable_command_is_refused(self):
        with patch.object(dnspin_timer.platform, "system", return_value="Linux"), \
             patch.object(dnspin_timer.os, "geteuid", return_value=0, create=True), \
             patch.object(dnspin_timer, "resolve_cli_command", return_value=None):
            ok, message = dnspin_timer.install_autopin(900)
        self.assertFalse(ok)
        self.assertIn("--cli", message)

    def test_remove_deletes_the_units(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(dnspin_timer.platform, "system", return_value="Linux"), \
                 patch.object(dnspin_timer.os, "geteuid", return_value=0, create=True), \
                 patch.object(dnspin_timer, "_systemd_dir", return_value=tmp), \
                 patch.object(dnspin_timer, "_run_command", return_value=_ok()):
                service = os.path.join(tmp, dnspin_timer.SERVICE_NAME + ".service")
                timer = os.path.join(tmp, dnspin_timer.TIMER_NAME)
                for path in (service, timer):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write("x")
                ok, message = dnspin_timer.remove_autopin()
            self.assertTrue(ok, message)
            self.assertFalse(os.path.exists(service))
            self.assertFalse(os.path.exists(timer))


class TestStatus(unittest.TestCase):
    def test_not_installed_does_not_shell_out(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(dnspin_timer.platform, "system", return_value="Linux"), \
                 patch.object(dnspin_timer, "_systemd_dir", return_value=tmp), \
                 patch.object(dnspin_timer, "_run_command") as run:
                status = dnspin_timer.autopin_status()
        self.assertFalse(status["installed"])
        self.assertFalse(status["active"])
        run.assert_not_called()

    def test_installed_and_active_reads_the_interval(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            service = os.path.join(tmp, dnspin_timer.SERVICE_NAME + ".service")
            timer = os.path.join(tmp, dnspin_timer.TIMER_NAME)
            with open(service, "w", encoding="utf-8") as f:
                f.write("x")
            with open(timer, "w", encoding="utf-8") as f:
                f.write(dnspin_timer.render_systemd_timer(600))
            with patch.object(dnspin_timer.platform, "system", return_value="Linux"), \
                 patch.object(dnspin_timer, "_systemd_dir", return_value=tmp), \
                 patch.object(dnspin_timer, "_run_command", return_value=_ok("active")):
                status = dnspin_timer.autopin_status()
        self.assertTrue(status["installed"])
        self.assertTrue(status["active"])
        self.assertEqual(status["interval"], 600)


class TestPlatforms(unittest.TestCase):
    def test_windows_install_uses_a_system_task(self):
        calls = []

        def runner(command):
            calls.append(command)
            return _ok()

        with patch.object(dnspin_timer.platform, "system", return_value="Windows"), \
             patch.object(dnspin_timer, "_run_command", side_effect=runner):
            ok, message = dnspin_timer.install_autopin(
                900, command=["C:\\Tools\\antigravity-unlock.exe", "dnspin", "sync-hosts"]
            )
        self.assertTrue(ok, message)
        create = calls[0]
        self.assertEqual(create[:4], ["schtasks", "/Create", "/F", "/TN"])
        self.assertIn("/RU", create)
        self.assertEqual(create[create.index("/RU") + 1], "SYSTEM")
        self.assertEqual(create[create.index("/MO") + 1], "15")
        self.assertIn("dnspin sync-hosts", create[-1])

    def test_darwin_install_writes_a_launch_daemon(self):
        import tempfile

        calls = []

        def runner(command):
            calls.append(command)
            return _ok()

        with tempfile.TemporaryDirectory() as tmp:
            plist = os.path.join(tmp, "com.antigravity.unlocker.dnspin.plist")
            with patch.object(dnspin_timer.platform, "system", return_value="Darwin"), \
                 patch.object(dnspin_timer.os, "geteuid", return_value=0, create=True), \
                 patch.object(dnspin_timer, "_launch_daemon_path", return_value=plist), \
                 patch.object(dnspin_timer, "_run_command", side_effect=runner):
                ok, message = dnspin_timer.install_autopin(
                    900, command=["/usr/local/bin/antigravity-unlock", "dnspin", "sync-hosts"]
                )
            self.assertTrue(ok, message)
            with open(plist, encoding="utf-8") as f:
                content = f.read()
        self.assertIn("com.antigravity.unlocker.dnspin", content)
        self.assertIn(["launchctl", "bootstrap", "system", plist], calls)


class TestCliDispatch(unittest.TestCase):
    def test_autopin_install_passes_interval_and_cli_path(self):
        captured = {}

        def fake_install(interval, command=None):
            captured["interval"] = interval
            captured["command"] = command
            return True, "installed"

        argv = [
            "antigravity-unlock", "dnspin", "autopin", "install",
            "--interval", "600", "--cli", "/opt/antigravity-unlock",
        ]
        with patch.object(sys, "argv", argv), \
             patch.object(cli, "install_autopin", side_effect=fake_install):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)
        self.assertEqual(captured["interval"], 600)
        self.assertEqual(
            captured["command"],
            [os.path.abspath("/opt/antigravity-unlock"), "dnspin", "sync-hosts"],
        )

    def test_sync_hosts_exit_code_follows_the_sync_result(self):
        argv = ["antigravity-unlock", "dnspin", "sync-hosts"]
        with patch.object(sys, "argv", argv), \
             patch.object(cli, "sync_hosts_pin", return_value=(0, "pin is current")):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 0)

        with patch.object(sys, "argv", argv), \
             patch.object(cli, "sync_hosts_pin", return_value=(2, "no relay")):
            with self.assertRaises(SystemExit) as raised:
                cli.main()
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
