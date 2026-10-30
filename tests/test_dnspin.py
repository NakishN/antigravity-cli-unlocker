"""
Tests for the no-VPN DNS-pin egress.

The live behaviour was measured 2026-10-27 from a Russian ISP: agy answered
Gemini through the public geohide/comss relays with no VPN and no proxy.  These
tests pin the parts that do not need the public internet: DNS wire parsing,
baseline/candidate separation, and the local CONNECT proxy's host mapping.
"""

import os
import socket
import struct
import threading
import unittest
from unittest.mock import patch

from antigravity_unlock import dnspin
from antigravity_unlock.config import DEFAULT_CONFIG


def _dns_response(host, ip):
    tid = 0x1234
    header = struct.pack(">HHHHHH", tid, 0x8180, 1, 1, 0, 0)
    qname = b"".join(bytes([len(p)]) + p.encode() for p in host.split(".")) + b"\x00"
    question = qname + struct.pack(">HH", 1, 1)
    answer = (b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4)
              + socket.inet_aton(ip))
    return header + question + answer


class TestDnsWire(unittest.TestCase):
    def test_parse_a_response(self):
        data = _dns_response("daily-cloudcode-pa.googleapis.com", "159.194.200.33")
        self.assertEqual(dnspin.parse_a_response(data), ["159.194.200.33"])

    def test_parse_empty(self):
        self.assertEqual(dnspin.parse_a_response(b""), [])
        self.assertEqual(dnspin.parse_a_response(b"\x00" * 11), [])

    def test_compress_pointer_is_followed(self):
        # The answer uses a 0xc00c pointer back to the question; a parser that
        # skipped a fixed number of bytes would read the IP as a name and fail.
        data = _dns_response("generativelanguage.googleapis.com", "142.251.153.2")
        self.assertEqual(dnspin.parse_a_response(data), ["142.251.153.2"])


class TestCandidates(unittest.TestCase):
    def test_baseline_addresses_are_excluded_and_duplicates_collapsed(self):
        with patch.object(dnspin, "baseline_ips", return_value={"172.217.1.1"}), \
             patch.object(dnspin, "query_udp", return_value=["172.217.1.1", "159.1.1.1"]), \
             patch.object(dnspin, "query_doh", return_value=["159.1.1.1", "193.2.2.2"]):
            found, baseline = dnspin.collect_candidates("x", timeout=0.1)
        self.assertEqual(found, ["159.1.1.1", "193.2.2.2"])
        self.assertEqual(baseline, {"172.217.1.1"})

    def test_no_substitution_means_no_candidates(self):
        with patch.object(dnspin, "baseline_ips", return_value={"172.217.1.1"}), \
             patch.object(dnspin, "query_udp", return_value=["172.217.1.1"]), \
             patch.object(dnspin, "query_doh", return_value=[]):
            found, _ = dnspin.collect_candidates("x", timeout=0.1)
        self.assertEqual(found, [])

    def test_pin_ips_only_returns_chosen(self):
        status = {
            "a": {"chosen": [{"ip": "1.1.1.1", "latency": 0.1}]},
            "b": {"chosen": []},
        }
        self.assertEqual(dnspin.pin_ips(status), {"a": ["1.1.1.1"], "b": []})

    def test_format_status_names_a_missing_pin(self):
        text = dnspin.format_status({"a": {"baseline": [], "candidates": [], "chosen": []}})
        self.assertIn("NONE", text)


class TestPinProxy(unittest.TestCase):
    """The proxy must map a pinned host and tunnel bytes without touching TLS."""

    def _echo_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]

        def serve():
            try:
                conn, _ = srv.accept()
                data = conn.recv(4096)
                conn.sendall(b"echo:" + data)
                conn.close()
            except OSError:
                pass

        threading.Thread(target=serve, daemon=True).start()
        return port, srv

    def test_pinned_host_is_tunneled_to_the_mapped_ip(self):
        echo_port, echo_srv = self._echo_server()
        self.addCleanup(echo_srv.close)
        proxy = dnspin.DnsPinProxy(
            port=0, pinned={"echo.test": ["127.0.0.1"]}, auto_resolve=False
        ).start()
        self.addCleanup(proxy.stop)
        self.assertGreater(proxy.port, 0)

        client = socket.create_connection(("127.0.0.1", proxy.port), timeout=5)
        try:
            client.sendall(
                f"CONNECT echo.test:{echo_port} HTTP/1.1\r\n"
                f"Host: echo.test\r\n\r\n".encode()
            )
            head = client.recv(1024)
            self.assertIn(b"200 Connection Established", head)
            client.sendall(b"ping")
            self.assertEqual(client.recv(4096), b"echo:ping")
        finally:
            client.close()


class TestHostsPin(unittest.TestCase):
    def test_render_adds_block_and_preserves_existing_lines(self):
        original = "127.0.0.1 localhost\n"
        rendered = dnspin.render_hosts_pin(
            original, {"daily-cloudcode-pa.googleapis.com": ["159.194.200.33"]}
        )
        self.assertIn("127.0.0.1 localhost", rendered)
        self.assertIn(dnspin.HOSTS_MARKER_BEGIN, rendered)
        self.assertIn("159.194.200.33\tdaily-cloudcode-pa.googleapis.com", rendered)
        self.assertIn(dnspin.HOSTS_MARKER_END, rendered)

    def test_render_is_idempotent(self):
        first = dnspin.render_hosts_pin(
            "", {"daily-cloudcode-pa.googleapis.com": ["1.1.1.1"]}
        )
        second = dnspin.render_hosts_pin(
            first, {"daily-cloudcode-pa.googleapis.com": ["2.2.2.2"]}
        )
        self.assertEqual(second.count(dnspin.HOSTS_MARKER_BEGIN), 1)
        self.assertNotIn("1.1.1.1", second)
        self.assertIn("2.2.2.2", second)

    def test_parse_reads_the_block(self):
        rendered = dnspin.render_hosts_pin(
            "127.0.0.1 localhost\n",
            {
                "daily-cloudcode-pa.googleapis.com": ["159.194.200.33"],
                "generativelanguage.googleapis.com": ["142.251.153.2"],
            },
        )
        pin = dnspin.parse_hosts_pin(rendered)
        self.assertEqual(pin["daily-cloudcode-pa.googleapis.com"], ["159.194.200.33"])
        self.assertEqual(pin["generativelanguage.googleapis.com"], ["142.251.153.2"])

    def test_parse_without_block_is_empty(self):
        self.assertEqual(dnspin.parse_hosts_pin("127.0.0.1 localhost\n"), {})

    def test_dnspin_block_is_not_reported_as_a_legacy_pin(self):
        from antigravity_unlock import hosts_cleanup
        rendered = dnspin.render_hosts_pin(
            "", {"daily-cloudcode-pa.googleapis.com": ["159.194.200.33"]}
        )
        pins = hosts_cleanup.find_pins(
            rendered, exclude_blocks=((dnspin.HOSTS_MARKER_BEGIN, dnspin.HOSTS_MARKER_END),)
        )
        self.assertEqual(pins, [])

    @unittest.skipIf(os.name == "nt", "POSIX root check; Windows uses a different path")
    def test_write_requires_root_without_touching_the_file(self):
        # The test runs unprivileged; the function must refuse before opening
        # the target, so a temp path is safe to pass.
        ok, msg = dnspin.write_hosts_pin(
            {"daily-cloudcode-pa.googleapis.com": ["159.194.200.33"]},
            path="/tmp/does-not-matter-hosts",
        )
        if os.geteuid() != 0:
            self.assertFalse(ok)
            self.assertIn("sudo", msg)


class TestSyncHostsPin(unittest.TestCase):
    """The autopin timer's core: refresh only what actually changed."""

    def _write(self, tmp, pinned):
        path = os.path.join(tmp, "hosts")
        with open(path, "w", encoding="utf-8") as f:
            f.write(dnspin.render_hosts_pin("127.0.0.1 localhost\n", pinned))
        return path

    def test_no_relay_keeps_the_previous_pin(self):
        import tempfile

        daily = "daily-cloudcode-pa.googleapis.com"
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {daily: ["1.1.1.1"]})
            with open(path, encoding="utf-8") as f:
                before = f.read()
            code, message = dnspin.sync_hosts_pin(
                path=path, resolve=lambda: {daily: {"chosen": []}}
            )
            with open(path, encoding="utf-8") as f:
                after = f.read()
        self.assertEqual(code, 0)
        self.assertIn("keeping the previous pin", message)
        self.assertEqual(before, after)

    def test_no_relay_and_no_pin_is_an_error(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hosts")
            with open(path, "w", encoding="utf-8") as f:
                f.write("127.0.0.1 localhost\n")
            code, message = dnspin.sync_hosts_pin(
                path=path, resolve=lambda: {"daily-cloudcode-pa.googleapis.com": {"chosen": []}}
            )
        self.assertEqual(code, 2)
        self.assertIn("nothing to write", message)

    def test_resolver_failure_is_not_a_crash(self):
        def boom():
            raise OSError("network down")

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            code, message = dnspin.sync_hosts_pin(
                path=os.path.join(tmp, "hosts"), resolve=boom
            )
        self.assertEqual(code, 1)
        self.assertIn("network down", message)

    def test_changed_relay_is_written_and_missing_hosts_keep_old_ips(self):
        import tempfile

        daily = "daily-cloudcode-pa.googleapis.com"
        cloud = "cloudcode-pa.googleapis.com"
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {daily: ["1.1.1.1"], cloud: ["2.2.2.2"]})
            status = {
                daily: {"chosen": [{"ip": "9.9.9.9", "latency": 0.1}]},
                cloud: {"chosen": []},
            }
            with patch.object(dnspin.os, "geteuid", return_value=0, create=True):
                code, message = dnspin.sync_hosts_pin(path=path, resolve=lambda: status)
            pin = dnspin.parse_hosts_pin(path=path)
        self.assertEqual(code, 0, message)
        self.assertEqual(pin[daily], ["9.9.9.9"])
        self.assertEqual(pin[cloud], ["2.2.2.2"])

    def test_unchanged_pin_does_not_rewrite_the_file(self):
        import tempfile

        daily = "daily-cloudcode-pa.googleapis.com"
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, {daily: ["1.1.1.1"]})
            status = {daily: {"chosen": [{"ip": "1.1.1.1", "latency": 0.1}]}}
            with patch.object(dnspin, "write_hosts_pin") as write:
                code, message = dnspin.sync_hosts_pin(path=path, resolve=lambda: status)
        self.assertEqual(code, 0)
        self.assertIn("already current", message)
        write.assert_not_called()


class TestConfig(unittest.TestCase):
    def test_dnspin_is_off_by_default(self):
        self.assertFalse(DEFAULT_CONFIG["dnspin_enabled"])
        self.assertIn("dnspin_refresh_seconds", DEFAULT_CONFIG)


if __name__ == "__main__":
    unittest.main()
