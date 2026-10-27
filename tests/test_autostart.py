"""
Tests for Autostart module (autostart.py).
"""

import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from antigravity_unlock import autostart
from antigravity_unlock.autostart import (
    render_systemd_unit,
    render_launch_agent_plist,
    resolve_guardian_command,
    autostart_status,
    ensure_runtime,
    runtime_dir,
    _package_importable,
    _verify_command,
    SERVICE_NAME,
    LAUNCH_AGENT_LABEL,
)


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _install_with(unit_problem, tmp=None):
    """Drive install_autostart() on a faked Linux with a stubbed systemd."""
    import tempfile as _tf
    tmp = tmp or _tf.mkdtemp()
    unit_file = os.path.join(tmp, "u.service")

    def fake_run(command, check=False):
        return _FakeCompleted(0, "", "")

    with patch.object(autostart.platform, "system", return_value="Linux"), \
         patch.object(autostart, "_systemd_unit_path", return_value=unit_file), \
         patch.object(autostart, "resolve_guardian_command",
                      return_value=["/py", "-m", "antigravity_unlock", "guardian"]), \
         patch.object(autostart, "ensure_runtime", return_value=("/py", "")), \
         patch.object(autostart, "guardian_unit_problem", return_value=unit_problem), \
         patch.object(autostart, "_verify_command", return_value=None), \
         patch.object(autostart, "_run_command", side_effect=fake_run):
        return autostart.install_autostart()


class TestAutostart(unittest.TestCase):

    def test_render_systemd_unit(self):
        cmd = ["/usr/bin/python3", "-m", "antigravity_unlock", "guardian"]
        unit = render_systemd_unit(cmd)
        self.assertIn("[Unit]", unit)
        self.assertIn("[Service]", unit)
        self.assertIn("ExecStart=/usr/bin/python3 -m antigravity_unlock guardian", unit)
        self.assertIn("Restart=always", unit)

    def test_systemd_unit_bounds_the_restart_loop(self):
        # An unimportable package makes ExecStart fail instantly.  Unbounded
        # Restart=alone turned that into 137 silent retries while the install
        # still looked protected.
        unit = render_systemd_unit(["/usr/bin/python3", "-m", "antigravity_unlock", "guardian"])
        self.assertIn("StartLimitBurst=5", unit)
        self.assertIn("StartLimitIntervalSec=300", unit)

    def test_package_importable_reports_a_missing_package(self):
        # /bin/false is a real interpreter stand-in that exits non-zero, which is
        # what an interpreter without the package looks like from the outside.
        ok, reason = _package_importable("/bin/false")
        self.assertFalse(ok)
        self.assertTrue(reason)

    def test_package_importable_ignores_the_callers_cwd(self):
        # The probe must not inherit the caller's directory.  Run from the
        # checkout, `sys.executable -c "import antigravity_unlock"` succeeds and
        # the guard reports the unit is fine - but systemd runs the unit with
        # cwd=$HOME, where the import fails and the unit crash-loops.  That is the
        # exact 137-restart failure, and it slipped past the first version of this
        # check for that reason.
        #
        # In CI the package is pip-installed, so the import succeeds from every
        # directory; asserting on the real result would test the runner, not the
        # code.  Assert the cwd passed to the subprocess instead.
        with patch.object(autostart.subprocess, "run",
                          return_value=_FakeCompleted(1, "", "No module named antigravity_unlock")) as run:
            ok, _reason = _package_importable(sys.executable)
        self.assertFalse(ok)
        self.assertEqual(run.call_args.kwargs.get("cwd"), tempfile.gettempdir())

    def test_verify_command_warns_when_the_module_is_missing(self):
        # The -m form depends on importability; pin the probe rather than the
        # runner's environment (CI installs the package, a checkout may not).
        with patch.object(autostart, "_package_importable",
                          return_value=(False, "No module named antigravity_unlock")):
            warning = _verify_command([sys.executable, "-m", "antigravity_unlock", "guardian"])
        self.assertIsNotNone(warning)
        self.assertIn("restart-loop", warning)

    def test_verify_command_accepts_an_installed_interpreter(self):
        # A PYTHONPATH that reaches the checkout stands in for a real install,
        # and must not be warned about.
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        env_path = os.pathsep.join([root, os.environ.get("PYTHONPATH", "")])
        with patch.dict(os.environ, {"PYTHONPATH": env_path}):
            self.assertIsNone(_verify_command([sys.executable, "-m", "antigravity_unlock", "guardian"]))

    def test_runtime_lives_in_the_app_dir_not_in_tmp(self):
        # A guardian pointing into the user's temp files has silently stopped
        # existing after a reboot, which is indistinguishable from a guardian that
        # never ran.  Asserted against get_app_dir() rather than ~ because
        # conftest redirects the app dir to a temp dir, which is exactly the
        # property being tested.
        from antigravity_unlock.patcher import get_app_dir

        app_dir = get_app_dir()
        self.assertTrue(runtime_dir().startswith(app_dir), runtime_dir())
        self.assertTrue(runtime_dir().endswith("runtime"), runtime_dir())

    def test_resolve_prefers_the_runtime_over_the_calling_interpreter(self):
        # shutil.which() must be pinned: on a developer machine an
        # `antigravity-unlock` wrapper on PATH would win before the runtime, and
        # the test would pass or fail depending on the machine rather than the
        # code.  The same applies to the fallback test below.
        with patch.object(autostart.shutil, "which", return_value=None), \
             patch.object(autostart, "runtime_python",
                          return_value="/home/u/.local/share/antigravity-unlocker/runtime/bin/python"):
            command = resolve_guardian_command()
        self.assertEqual(command[1:], ["-m", "antigravity_unlock", "guardian"])
        self.assertEqual(command[0], "/home/u/.local/share/antigravity-unlocker/runtime/bin/python")

    def test_resolve_falls_back_to_sys_executable_without_a_runtime(self):
        with patch.object(autostart.shutil, "which", return_value=None), \
             patch.object(autostart, "runtime_python", return_value=None):
            command = resolve_guardian_command()
        self.assertEqual(command[0], sys.executable)

    def test_ensure_runtime_creates_an_importable_environment(self):
        # The end-to-end contract of the 1.6.0 fix: whatever interpreter the unit
        # ends up pointing at can import this package from an unrelated cwd, so the
        # unit does not crash-loop.
        path, _note = ensure_runtime()
        self.assertIsNotNone(path, "runtime was not created")
        self.assertTrue(os.path.exists(path))
        proc = subprocess.run(
            [path, "-c", "import antigravity_unlock.cli"],
            capture_output=True, text=True, timeout=60, check=False, cwd=tempfile.gettempdir(),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_ensure_runtime_is_idempotent(self):
        first, _ = ensure_runtime()
        second, note = ensure_runtime()
        self.assertEqual(first, second)
        self.assertEqual(note, "", "a second call should have nothing left to do")

    def test_install_resets_a_burned_out_start_limit(self):
        # Once StartLimitBurst is exhausted, systemd refuses to start the unit
        # even after it has been rewritten correctly.  Without a reset, a
        # reinstall leaves a dead unit that `enable --now` still calls a
        # success.
        commands = []

        def fake_run(command, check=False):
            commands.append(list(command))
            return _FakeCompleted(0, "", "")

        import tempfile as _tf
        unit_file = os.path.join(_tf.mkdtemp(), "u.service")
        with patch.object(autostart.platform, "system", return_value="Linux"), \
             patch.object(autostart, "_systemd_unit_path", return_value=unit_file), \
             patch.object(autostart, "resolve_guardian_command",
                          return_value=["/py", "-m", "antigravity_unlock", "guardian"]), \
             patch.object(autostart, "ensure_runtime", return_value=("/py", "")), \
             patch.object(autostart, "guardian_unit_problem", return_value=None), \
             patch.object(autostart, "_verify_command", return_value=None), \
             patch.object(autostart, "_run_command", side_effect=fake_run):
            ok, msg = autostart.install_autostart()

        self.assertTrue(ok, msg)
        self.assertIn(
            ["systemctl", "--user", "reset-failed",
             f"{autostart.SERVICE_NAME}.service"], commands
        )

    def test_install_fails_loudly_when_the_unit_cannot_start(self):
        # `systemctl enable --now` exits 0 even when the unit dies immediately -
        # measured on this machine - so trusting its status reported a successful
        # install for a guardian that had never run.
        ok, msg = _install_with(unit_problem="systemd reports 'failed' for x.service")
        self.assertFalse(ok)
        self.assertIn("not running", msg)
        self.assertIn("journalctl", msg)

    def test_install_succeeds_when_the_unit_really_is_running(self):
        ok, msg = _install_with(unit_problem=None)
        self.assertTrue(ok, msg)
        self.assertIn("Installed systemd user service", msg)

    def test_verify_command_ignores_console_script_commands(self):
        # Only the `-m` form depends on importability, so a console-script
        # ExecStart must not be second-guessed.
        self.assertIsNone(_verify_command(["/opt/app/antigravity-unlock", "guardian"]))

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
