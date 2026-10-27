"""
Tests for the generic VPS egress bootstrap.

The script runs on a VPS, but its dry-run mode is the part that can be tested
everywhere: it must produce the microsocks launcher/unit and the exact local
`egress add` command without touching the system or requiring root.

Why microsocks and not tinyproxy: measured 2026-10-27, agy's model-list fetch
times out through an HTTP proxy with Basic auth, while a SOCKS5 proxy with
RFC 1929 username/password works for both the model list and a real model
call.  The script is built around that result, so these tests also pin the
`socks5h://` scheme in the printed command.
"""

import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "setup_proxy_vps.sh")


def run(*args):
    return subprocess.run(
        ["bash", SCRIPT, *args],
        capture_output=True, text=True, timeout=60, check=False,
    )


@unittest.skipIf(os.name == "nt", "bash script; not applicable on Windows")
class TestSetupProxyVpsDryRun(unittest.TestCase):
    def test_dry_run_renders_config_and_client_command(self):
        proc = run(
            "--dry-run", "--port", "18888", "--user", "tester",
            "--password", "s3cr3t@pass", "--allow", "203.0.113.7/32",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("PORT='18888'", out)
        self.assertIn("PROXY_USER='tester'", out)
        self.assertIn("PROXY_PASSWORD='s3cr3t@pass'", out)
        self.assertIn("microsocks -i 0.0.0.0", out)
        self.assertIn("antigravity-egress.service", out)
        # The password must be percent-encoded in the printed URL, while the
        # env file keeps the raw value.
        self.assertIn(
            "socks5h://tester:s3cr3t%40pass@<VPS_PUBLIC_IP>:18888", out
        )
        self.assertIn("egress add", out)
        self.assertIn("egress test", out)
        self.assertIn("203.0.113.7/32", out)

    def test_dry_run_makes_no_changes(self):
        proc = run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY RUN", proc.stdout)
        self.assertNotIn("installing microsocks", proc.stdout)

    def test_help(self):
        proc = run("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("--dry-run", proc.stdout)

    def test_port_below_1024_is_rejected(self):
        # microsocks runs as an unprivileged service user, so a privileged
        # port would fail at startup after the script had already claimed
        # success.
        for port in ("0", "80"):
            proc = run("--dry-run", "--port", port)
            self.assertNotEqual(proc.returncode, 0, port)
            self.assertIn("between 1024 and 65535", proc.stderr)

    def test_invalid_user_is_rejected(self):
        proc = run("--dry-run", "--user", "bad user")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("user may contain", proc.stderr)

    def test_invalid_allow_is_rejected(self):
        proc = run("--dry-run", "--allow", "not-an-ip")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("allow must be", proc.stderr)

    def test_password_with_shell_metacharacters_is_rejected(self):
        # The launcher sources the env file, so quotes/backslashes would break
        # out of it; whitespace would split the argument.
        for bad in ("pa#ss", "pa ss", 'pa"ss', "pa'ss", "pa$ss", "pa\\ss"):
            proc = run("--dry-run", "--password", bad)
            self.assertNotEqual(proc.returncode, 0, bad)
            self.assertIn("password may contain", proc.stderr)

    def test_generated_password_when_not_given(self):
        proc = run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # A 32-hex-char password is generated and embedded in the env file.
        self.assertRegex(proc.stdout, r"PROXY_PASSWORD='[0-9a-f]{32}'")


if __name__ == "__main__":
    unittest.main()
