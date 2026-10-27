"""
Tests for the foreign-egress layer.

The classification tests below use agy output captured verbatim from real runs
rather than strings invented for the test, because the interesting case is a
near-miss: when the proxy is unreachable agy prints

    error: Eligibility check failed: Post "...loadCodeAssist": proxyconnect tcp:
    dial tcp 127.0.0.1:9: connect: connection refused

which contains "Eligibility check failed" - the marker for an *unpatched*
binary.  Reporting a stopped daemon as "your patch is gone" sends the user to
re-patch a binary that is fine, so the proxy markers must be tested before the
gate markers, and that ordering needs a regression test with the real text.

The SOCKS5 tests run a throwaway server on 127.0.0.1 and a real echo target
behind it.  The handshake is hand-rolled (the project has no dependencies), so
it is the part most likely to be subtly wrong, and mocking it would prove
nothing.
"""

import os
import socket
import struct
import tempfile
import time
import threading
import unittest
from unittest.mock import patch

from antigravity_unlock import egress


# agy 1.2.11, patched binary, direct RU egress 95.26.85.26.
REAL_REGION_400 = (
    'error: FAILED_PRECONDITION (code 400): User location is not supported for '
    'the API use.\n'
    'AGY_ERROR: {"short_error":"FAILED_PRECONDITION (code 400): User location is '
    'not supported for the API use.","status":"INVALID_ARGUMENT","error_code":400,'
    '"code_kind":"http","retryable":false,'
    '"error_id":"0955b529-2d44-491b-bdb0-c44a388391e5-1"}'
)

# agy 1.2.11, patched binary, https_proxy pointed at a closed port.
REAL_DEAD_PROXY = (
    'error: Eligibility check failed: Post '
    '"https://daily-cloudcode-pa.googleapis.com/v1internal:loadCodeAssist": '
    'proxyconnect tcp: dial tcp 127.0.0.1:9: connect: connection refused'
)

# agy 1.2.11 through a SOCKS5 exit in Amsterdam.
REAL_SUCCESS = "PONG"

# agy 1.3.1, patched binary, direct egress via a Clash TUN, 2026-10-07.  The
# avatar fetch died mid-TLS and agy filed it under the same heading as a
# regional verdict.  The next run answered DOCTOR_OK unchanged, so calling this
# an unpatched binary was wrong twice over: wrong about the cause, and wrong
# about the install.
REAL_TRANSIENT_EOF = (
    'error: Eligibility check failed: failed to get profile picture: Get '
    '"https://lh3.googleusercontent.com/a/ACg8ocIhRZzKytihTtRr-fZYTe0cYSyrkGEST'
    'JTTHRXNgvXZ5TajEVE=s96-c": EOF'
)


def _read_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def _start_echo_server():
    """A TCP server that echoes one message.  Returns (port, closer)."""
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

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return port, srv


def _start_socks_server(mode, target_port):
    """A one-connection SOCKS5 server.  Returns (port, srv_socket)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve():
        try:
            conn, _ = srv.accept()
            header = _read_exact(conn, 2)
            if len(header) < 2 or header[0] != 0x05:
                conn.close()
                return
            methods = _read_exact(conn, header[1])

            if mode == "userpass":
                if 0x02 not in methods:
                    conn.sendall(b"\x05\xff")
                    conn.close()
                    return
                conn.sendall(b"\x05\x02")
                # RFC 1929 subnegotiation opens with its own version byte; it is
                # not the username length.  Skipping it silently desynchronises
                # the stream and looks like a client bug.
                if _read_exact(conn, 1) != b"\x01":
                    conn.close()
                    return
                ulen = _read_exact(conn, 1)[0]
                user = _read_exact(conn, ulen).decode()
                plen = _read_exact(conn, 1)[0]
                password = _read_exact(conn, plen).decode()
                if (user, password) != ("tester", "secret"):
                    conn.sendall(b"\x01\x01")
                    conn.close()
                    return
                conn.sendall(b"\x01\x00")
            elif mode == "reject-auth":
                conn.sendall(b"\x05\xff")
                conn.close()
                return
            else:
                if 0x00 not in methods:
                    conn.sendall(b"\x05\xff")
                    conn.close()
                    return
                conn.sendall(b"\x05\x00")

            request = _read_exact(conn, 4)
            atyp = request[3]
            if atyp == 0x03:
                length = _read_exact(conn, 1)[0]
                host = _read_exact(conn, length).decode("idna")
            elif atyp == 0x01:
                host = socket.inet_ntoa(_read_exact(conn, 4))
            else:
                host = None
            _read_exact(conn, 2)  # port; the echo target is fixed

            if mode == "host-unreachable":
                conn.sendall(b"\x05\x04\x00\x01" + b"\x00" * 4 + b"\x00\x00")
                conn.close()
                return
            if host is None:
                conn.sendall(b"\x05\x08\x00\x01" + b"\x00" * 4 + b"\x00\x00")
                conn.close()
                return

            upstream = socket.create_connection((host, target_port), 5)
            conn.sendall(
                b"\x05\x00\x00\x01"
                + socket.inet_aton("127.0.0.1")
                + struct.pack("!H", target_port)
            )
            payload = conn.recv(4096)
            upstream.sendall(payload)
            conn.sendall(upstream.recv(4096))
            upstream.close()
            conn.close()
        except OSError:
            pass

    threading.Thread(target=serve, daemon=True).start()
    return port, srv


class TestParseRoute(unittest.TestCase):
    def test_socks5h_keeps_remote_dns_flag(self):
        route, err = egress.parse_route("socks5h://127.0.0.1:40000")
        self.assertIsNone(err)
        self.assertEqual(route["scheme"], "socks5h")
        self.assertEqual(route["port"], 40000)
        self.assertTrue(route["remote_dns"])

    def test_socks5_resolves_locally(self):
        route, _ = egress.parse_route("socks5://127.0.0.1:1080")
        self.assertFalse(route["remote_dns"])

    def test_default_ports(self):
        for url, port in (("socks5://h", 1080), ("http://h", 80), ("https://h", 443)):
            route, err = egress.parse_route(url)
            self.assertIsNone(err, url)
            self.assertEqual(route["port"], port, url)

    def test_credentials_are_parsed_and_unquoted(self):
        route, err = egress.parse_route("https://user%40x:p%40ss@host:8443")
        self.assertIsNone(err)
        self.assertEqual(route["user"], "user@x")
        self.assertEqual(route["password"], "p@ss")

    def test_rejects_unknown_scheme(self):
        route, err = egress.parse_route("gopher://host:1080")
        self.assertIsNone(route)
        self.assertIn("unsupported proxy scheme", err)

    def test_rejects_missing_host(self):
        route, err = egress.parse_route("socks5://:1080")
        self.assertIsNone(route)
        self.assertIn("no host", err)

    def test_password_is_masked_in_description(self):
        route, _ = egress.parse_route("https://user:hunter2@host:8443")
        text = egress.describe_route(route)
        self.assertNotIn("hunter2", text)
        self.assertIn("***", text)


class TestResolveSpec(unittest.TestCase):
    def test_preset_name(self):
        url, label = egress.resolve_spec("warp")
        self.assertEqual(url, egress.PRESETS["warp"]["url"])
        self.assertEqual(label, "warp")

    def test_preset_is_case_insensitive(self):
        self.assertEqual(egress.resolve_spec("WARP")[0], egress.PRESETS["warp"]["url"])

    def test_bare_url_uses_url_as_label(self):
        url, label = egress.resolve_spec("socks5://10.0.0.1:1080")
        self.assertEqual(label, "socks5://10.0.0.1:1080")

    def test_dict_with_label(self):
        url, label = egress.resolve_spec({"preset": "warp", "label": "cloudflare"})
        self.assertEqual(label, "cloudflare")
        self.assertEqual(url, egress.PRESETS["warp"]["url"])

    def test_dict_with_url(self):
        url, label = egress.resolve_spec({"url": "socks5://h:1080", "label": "home"})
        self.assertEqual((url, label), ("socks5://h:1080", "home"))

    def test_empty_dict_raises(self):
        with self.assertRaises(ValueError):
            egress.resolve_spec({})

    def test_unknown_preset_is_treated_as_url_and_then_rejected(self):
        # Not a preset, so it is read as a URL - and fails scheme validation
        # later in parse_route rather than here.
        url, _ = egress.resolve_spec("nosuchpreset")
        route, err = egress.parse_route(url)
        self.assertIsNone(route)
        self.assertIn("unsupported proxy scheme", err)


class TestRoutesFromConfig(unittest.TestCase):
    def test_malformed_entries_are_skipped_not_fatal(self):
        # One typo must not stop the wrapper from launching agy at all.
        cfg = {"egress_routes": [
            {"label": "good", "url": "socks5h://127.0.0.1:40000"},
            {"label": "bad"},
            "gopher://nope",
            "warp",
        ]}
        routes = egress.routes_from_config(cfg)
        self.assertEqual([r["label"] for r in routes], ["good", "warp"])

    def test_missing_key_is_empty(self):
        self.assertEqual(egress.routes_from_config({}), [])


class TestActiveRoute(unittest.TestCase):
    CFG_ROUTES = [
        {"label": "a", "url": "socks5h://127.0.0.1:1080"},
        {"label": "b", "url": "socks5h://127.0.0.1:2080"},
    ]

    def test_disabled_returns_none_even_with_routes(self):
        cfg = {"egress_enabled": False, "egress_routes": self.CFG_ROUTES, "egress_active": "a"}
        self.assertIsNone(egress.active_route(cfg))

    def test_enabled_with_no_routes(self):
        self.assertIsNone(egress.active_route({"egress_enabled": True, "egress_routes": []}))

    def test_selected_by_label(self):
        cfg = {"egress_enabled": True, "egress_routes": self.CFG_ROUTES, "egress_active": "b"}
        self.assertEqual(egress.active_route(cfg)["label"], "b")

    def test_stale_selection_falls_back_to_first(self):
        # Failing closed here would mean a guaranteed region 400; a wrong but
        # working exit is the better outcome.
        cfg = {"egress_enabled": True, "egress_routes": self.CFG_ROUTES, "egress_active": "gone"}
        self.assertEqual(egress.active_route(cfg)["label"], "a")

    def test_no_selection_uses_first(self):
        cfg = {"egress_enabled": True, "egress_routes": self.CFG_ROUTES, "egress_active": ""}
        self.assertEqual(egress.active_route(cfg)["label"], "a")


class TestClassifyAgy(unittest.TestCase):
    """Real captured output, not invented fixtures."""

    def test_region_400_is_region_blocked(self):
        status, _ = egress.classify_agy(REAL_REGION_400, 1)
        self.assertEqual(status, egress.STATUS_REGION_BLOCKED)

    def test_dead_proxy_is_not_reported_as_an_unpatched_binary(self):
        # The regression this file exists for: the message says "Eligibility
        # check failed", but the cause is a stopped daemon.
        status, _ = egress.classify_agy(REAL_DEAD_PROXY, 1)
        self.assertEqual(status, egress.STATUS_PROXY_UNREACHABLE)
        self.assertNotEqual(status, egress.STATUS_GATE)

    def test_success(self):
        status, _ = egress.classify_agy(REAL_SUCCESS, 0)
        self.assertEqual(status, egress.STATUS_OK)

    def test_bare_eligibility_failure_is_the_gate(self):
        status, _ = egress.classify_agy("error: not eligible for Antigravity", 1)
        self.assertEqual(status, egress.STATUS_GATE)

    def test_dropped_connection_is_not_reported_as_an_unpatched_binary(self):
        # Second instance of the same near-miss the dead-proxy case covers: the
        # heading says eligibility, the cause is a socket.
        status, _ = egress.classify_agy(REAL_TRANSIENT_EOF, 1)
        self.assertEqual(status, egress.STATUS_TRANSIENT)
        self.assertNotEqual(status, egress.STATUS_GATE)

    def test_real_region_verdict_still_beats_the_transport_markers(self):
        # The transport tier sits above the gate tier, so it must not swallow a
        # genuine refusal.  This text is the unpatched-binary message.
        status, _ = egress.classify_agy(
            "Eligibility check failed: Your current account is not eligible for "
            "Antigravity, because it is not currently available in your location.",
            1,
        )
        self.assertEqual(status, egress.STATUS_GATE)

    def test_region_400_still_wins_over_a_transport_word(self):
        # Guard against the ordering being "fixed" the wrong way round: a real
        # 400 must not be softened into "retry" because the body happened to
        # contain a connection-ish word.
        mixed = REAL_REGION_400 + "\nerror: connection reset by peer"
        status, _ = egress.classify_agy(mixed, 1)
        self.assertEqual(status, egress.STATUS_REGION_BLOCKED)

    def test_dead_proxy_still_beats_the_transport_tier(self):
        # REAL_DEAD_PROXY contains "connect: connection refused", which is also a
        # transport marker.  Proxy markers are checked first, so it must stay
        # PROXY_UNREACHABLE - otherwise the fix above would have broken the case
        # this file was written for.
        status, _ = egress.classify_agy(REAL_DEAD_PROXY, 1)
        self.assertEqual(status, egress.STATUS_PROXY_UNREACHABLE)

    def test_missing_credentials_proves_the_route(self):
        status, _ = egress.classify_agy("401 CREDENTIALS_MISSING", 1)
        self.assertEqual(status, egress.STATUS_CREDENTIALS)

    def test_proxy_auth_demand(self):
        status, _ = egress.classify_agy(
            "error: 407 Proxy Authentication Required", 1
        )
        self.assertEqual(status, egress.STATUS_PROXY_AUTH)

    def test_empty_output_with_failure(self):
        status, _ = egress.classify_agy("", 1)
        self.assertEqual(status, egress.STATUS_UNKNOWN)

    def test_unrecognised_failure(self):
        status, _ = egress.classify_agy("something else entirely", 3)
        self.assertEqual(status, egress.STATUS_UNKNOWN)


class TestBuildChildEnv(unittest.TestCase):
    def setUp(self):
        self.route, _ = egress.parse_route("socks5h://127.0.0.1:40000", label="warp")
        egress._PROXY_VAR_CACHE.clear()
        self.addCleanup(egress._PROXY_VAR_CACHE.clear)

    def test_ambient_proxy_vars_are_removed(self):
        # Go consults the upper-case spelling first, so leaving an ambient
        # HTTPS_PROXY in place would let it win over the route we were asked to
        # use - the wrapper would silently not wrap.
        base = {
            "PATH": "/usr/bin",
            "https_proxy": "http://other:3128",
            "HTTPS_PROXY": "http://other:3128",
            "all_proxy": "socks5://other:1080",
        }
        env = egress.build_child_env(self.route, base=base)
        self.assertEqual(env["PATH"], "/usr/bin")
        self.assertEqual(env["https_proxy"], self.route["url"])
        self.assertEqual(env["HTTPS_PROXY"], self.route["url"])
        self.assertNotIn("all_proxy", env)

    def test_isolated_binary_uses_private_variable(self):
        with patch.object(egress, "proxy_var_is_isolated", return_value=True):
            env = egress.build_child_env(self.route, base={"PATH": "/usr/bin"})
        self.assertEqual(env["AG_LS_PROXY"], self.route["url"])
        self.assertNotIn("https_proxy", env)
        self.assertNotIn("HTTPS_PROXY", env)

    def test_unpatched_binary_ignores_private_variable(self):
        with patch.object(egress, "proxy_var_is_isolated", return_value=False):
            env = egress.build_child_env(self.route, base={"PATH": "/usr/bin"})
        self.assertNotIn("AG_LS_PROXY", env)
        self.assertEqual(env["https_proxy"], self.route["url"])


class TestProxyVarIsolation(unittest.TestCase):
    def setUp(self):
        egress._PROXY_VAR_CACHE.clear()
        self.addCleanup(egress._PROXY_VAR_CACHE.clear)
        self.tmp = tempfile.mkdtemp()

    def _binary(self, name, blob):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as handle:
            handle.write(blob)
        return path

    def test_detects_the_renamed_literal(self):
        path = self._binary("isolated", b"x" * 64 + b"AG_LS_PROXY" + b"y" * 64)
        self.assertTrue(egress.proxy_var_is_isolated(path))

    def test_detects_a_stock_binary(self):
        path = self._binary("stock", b"x" * 64 + b"https_proxy" + b"y" * 64)
        self.assertFalse(egress.proxy_var_is_isolated(path))

    def test_empty_file_does_not_raise(self):
        # mmap refuses a zero-length mapping; a fresh download must not crash us.
        path = self._binary("empty", b"")
        self.assertFalse(egress.proxy_var_is_isolated(path))

    def test_missing_path_is_false(self):
        self.assertFalse(egress.proxy_var_is_isolated(os.path.join(self.tmp, "nope")))

    def test_none_path_is_false(self):
        self.assertFalse(egress.proxy_var_is_isolated(None))


class TestSocks5Tunnel(unittest.TestCase):
    """End-to-end against a real socket server: no mocks."""

    def _route(self, port, user=None, password=None):
        url = "socks5h://127.0.0.1:%d" % port
        if user:
            url = "socks5h://%s:%s@127.0.0.1:%d" % (user, password, port)
        route, err = egress.parse_route(url, label="test")
        self.assertIsNone(err)
        return route

    def test_noauth_connect_reaches_the_target(self):
        echo_port, echo_srv = _start_echo_server()
        socks_port, socks_srv = _start_socks_server("noauth", echo_port)
        self.addCleanup(echo_srv.close)
        self.addCleanup(socks_srv.close)

        sock = egress.socks5_tunnel(self._route(socks_port), "127.0.0.1", echo_port, timeout=5)
        try:
            sock.sendall(b"ping")
            self.assertEqual(sock.recv(4096), b"echo:ping")
        finally:
            sock.close()

    def test_username_password_auth(self):
        echo_port, echo_srv = _start_echo_server()
        socks_port, socks_srv = _start_socks_server("userpass", echo_port)
        self.addCleanup(echo_srv.close)
        self.addCleanup(socks_srv.close)

        route = self._route(socks_port, user="tester", password="secret")
        sock = egress.socks5_tunnel(route, "127.0.0.1", echo_port, timeout=5)
        try:
            sock.sendall(b"hi")
            self.assertEqual(sock.recv(4096), b"echo:hi")
        finally:
            sock.close()

    def test_wrong_password_is_reported(self):
        echo_port, echo_srv = _start_echo_server()
        socks_port, socks_srv = _start_socks_server("userpass", echo_port)
        self.addCleanup(echo_srv.close)
        self.addCleanup(socks_srv.close)

        route = self._route(socks_port, user="tester", password="wrong")
        with self.assertRaises(egress.EgressError) as ctx:
            egress.socks5_tunnel(route, "127.0.0.1", echo_port, timeout=5)
        self.assertIn("refused", str(ctx.exception))

    def test_auth_required_but_not_configured(self):
        echo_port, echo_srv = _start_echo_server()
        socks_port, socks_srv = _start_socks_server("userpass", echo_port)
        self.addCleanup(echo_srv.close)
        self.addCleanup(socks_srv.close)

        # We offer NO AUTH only, so the server answers 0xFF.  The message has to
        # say "credentials": "protocol failure" would send the user looking for
        # a bug in the handshake instead of a missing password.
        with self.assertRaises(egress.EgressError) as ctx:
            egress.socks5_tunnel(self._route(socks_port), "127.0.0.1", echo_port, timeout=5)
        self.assertIn("credentials", str(ctx.exception))

    def test_all_methods_rejected(self):
        echo_port, echo_srv = _start_echo_server()
        socks_port, socks_srv = _start_socks_server("reject-auth", echo_port)
        self.addCleanup(echo_srv.close)
        self.addCleanup(socks_srv.close)

        # Credentials supplied, so both NO AUTH and USERNAME/PASSWORD are
        # offered and the 0xFF really does mean "none of your methods".
        route = self._route(socks_port, user="tester", password="secret")
        with self.assertRaises(egress.EgressError) as ctx:
            egress.socks5_tunnel(route, "127.0.0.1", echo_port, timeout=5)
        self.assertIn("rejected every authentication method", str(ctx.exception))

    def test_connect_refusal_names_the_reply_code(self):
        echo_port, echo_srv = _start_echo_server()
        socks_port, socks_srv = _start_socks_server("host-unreachable", echo_port)
        self.addCleanup(echo_srv.close)
        self.addCleanup(socks_srv.close)

        with self.assertRaises(egress.EgressError) as ctx:
            egress.socks5_tunnel(self._route(socks_port), "127.0.0.1", echo_port, timeout=5)
        message = str(ctx.exception)
        self.assertIn("host unreachable", message)
        self.assertIn("0x04", message)

    def test_not_a_socks_server(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        self.addCleanup(srv.close)

        def serve():
            try:
                conn, _ = srv.accept()
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                # Windows turns an immediate close after send into a reset
                # (WinError 10053) before the client can read the first two
                # bytes, so the error is "connection aborted" instead of the
                # intended "not a SOCKS5 proxy".  Give the bytes a moment to
                # arrive; this is a test-server timing issue, not client logic.
                time.sleep(0.2)
                conn.close()
            except OSError:
                pass

        threading.Thread(target=serve, daemon=True).start()

        with self.assertRaises(egress.EgressError) as ctx:
            egress.socks5_tunnel(self._route(port), "127.0.0.1", 80, timeout=5)
        self.assertIn("not a SOCKS5 proxy", str(ctx.exception))

    def test_nothing_listening(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        with self.assertRaises(OSError):
            egress.socks5_tunnel(self._route(port), "127.0.0.1", 80, timeout=2)


class TestDechunk(unittest.TestCase):
    def test_chunked_body(self):
        body = b"5\r\nhello\r\n6\r\n world\r\n0\r\n\r\n"
        self.assertEqual(egress._dechunk(body), b"hello world")

    def test_non_chunked_body_is_untouched(self):
        self.assertEqual(egress._dechunk(b'{"country":"NL"}'), b'{"country":"NL"}')

    def test_malformed_size_falls_back_to_raw(self):
        self.assertEqual(egress._dechunk(b"zz\r\nabc"), b"zz\r\nabc")


class TestTcpReachable(unittest.TestCase):
    def test_listening_port_is_reachable(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.addCleanup(srv.close)
        route, _ = egress.parse_route("socks5h://127.0.0.1:%d" % srv.getsockname()[1])
        self.assertTrue(egress.tcp_reachable(route, timeout=2))

    def test_closed_port_is_not(self):
        closed = socket.socket()
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
        closed.close()
        route, _ = egress.parse_route("socks5h://127.0.0.1:%d" % port)
        self.assertFalse(egress.tcp_reachable(route, timeout=2))


class TestSelectRoute(unittest.TestCase):
    """Route choice rules, with the probes stubbed out."""

    def _routes(self, *labels):
        out = []
        for index, label in enumerate(labels):
            route, err = egress.parse_route(
                "socks5h://127.0.0.1:%d" % (20000 + index), label=label
            )
            self.assertIsNone(err)
            out.append(route)
        return out

    def test_first_working_route_wins_and_stops_the_search(self):
        routes = self._routes("dead", "good", "unused")
        calls = []

        def fake_probe(agy_path, route, timeout=None, model=None):
            calls.append(route["label"])
            status = egress.STATUS_OK if route["label"] == "good" else egress.STATUS_REGION_BLOCKED
            return {"route": route, "status": status, "detail": status}

        with patch.object(egress, "tcp_reachable", return_value=True), \
             patch.object(egress, "live_probe", side_effect=fake_probe):
            winner, results = egress.select_route("/bin/true", routes)

        self.assertEqual(winner["label"], "good")
        self.assertEqual(calls, ["dead", "good"])
        self.assertEqual(len(results), 2)

    def test_unreachable_route_never_costs_a_model_call(self):
        routes = self._routes("down", "good")
        calls = []

        def fake_probe(agy_path, route, timeout=None, model=None):
            calls.append(route["label"])
            return {"route": route, "status": egress.STATUS_OK, "detail": "ok"}

        with patch.object(egress, "tcp_reachable", side_effect=lambda r, timeout=None: r["label"] != "down"), \
             patch.object(egress, "live_probe", side_effect=fake_probe):
            winner, results = egress.select_route("/bin/true", routes)

        self.assertEqual(winner["label"], "good")
        self.assertEqual(calls, ["good"])
        self.assertEqual(results[0]["status"], egress.STATUS_PROXY_UNREACHABLE)

    def test_credentials_missing_still_selects_the_route(self):
        # 401 proves the request reached Google's API, which is the question.
        routes = self._routes("only")
        with patch.object(egress, "tcp_reachable", return_value=True), \
             patch.object(egress, "live_probe", return_value={
                 "route": routes[0], "status": egress.STATUS_CREDENTIALS, "detail": "401"}):
            winner, _ = egress.select_route("/bin/true", routes)
        self.assertEqual(winner["label"], "only")

    def test_a_timeout_does_not_select_anything(self):
        # Shelving a working exit because one call was slow is worse than
        # reporting "inconclusive".
        routes = self._routes("slow")
        with patch.object(egress, "tcp_reachable", return_value=True), \
             patch.object(egress, "live_probe", return_value={
                 "route": routes[0], "status": egress.STATUS_TIMEOUT, "detail": "slow"}):
            winner, results = egress.select_route("/bin/true", routes)
        self.assertIsNone(winner)
        self.assertEqual(len(results), 1)

    def test_preflight_can_be_skipped(self):
        routes = self._routes("only")
        with patch.object(egress, "tcp_reachable", return_value=False) as reachable, \
             patch.object(egress, "live_probe", return_value={
                 "route": routes[0], "status": egress.STATUS_OK, "detail": "ok"}):
            winner, _ = egress.select_route("/bin/true", routes, preflight=False)
        reachable.assert_not_called()
        self.assertEqual(winner["label"], "only")

    def test_missing_binary_is_inconclusive(self):
        routes = self._routes("only")
        result = egress.live_probe(None, routes[0])
        self.assertEqual(result["status"], egress.STATUS_UNKNOWN)


class TestFormatResults(unittest.TestCase):
    def test_password_never_reaches_the_report(self):
        route, _ = egress.parse_route("https://user:hunter2@host:8443", label="paid")
        text = egress.format_results([
            {"route": route, "status": egress.STATUS_OK, "detail": "fine"}
        ])
        self.assertNotIn("hunter2", text)
        self.assertIn("paid", text)
        self.assertIn("works", text)


class TestPresetIntegrity(unittest.TestCase):
    def test_every_preset_url_parses(self):
        for name, entry in egress.PRESETS.items():
            route, err = egress.parse_route(entry["url"], label=name)
            self.assertIsNone(err, "%s: %s" % (name, err))
            self.assertIsNotNone(route)

    def test_warp_preset_uses_remote_dns(self):
        # A Clash/mihomo TUN in fake-ip mode answers every A query with a
        # synthetic 198.18.0.0/16 address.  With plain socks5, Go resolves that
        # itself and hands the fake address to the proxy; socks5h makes the
        # proxy resolve it, on the far side, where DNS is honest.
        route, err = egress.parse_route(egress.PRESETS["warp"]["url"], label="warp")
        self.assertIsNone(err)
        self.assertTrue(route["remote_dns"])


class TestConfigDefaults(unittest.TestCase):
    def test_egress_is_off_by_default(self):
        from antigravity_unlock import config as cfgmod
        self.assertFalse(cfgmod.DEFAULT_CONFIG["egress_enabled"])
        self.assertEqual(cfgmod.DEFAULT_CONFIG["egress_routes"], [])
        self.assertEqual(cfgmod.DEFAULT_CONFIG["egress_active"], "")


if __name__ == "__main__":
    unittest.main()
