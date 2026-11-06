from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import http.client
import io
import json
import os
import select
import socket
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import cli, http_api
from compass_runtime import interaction_prototype as interaction

from .support import PAGE_BYTES, build_app, make_server, poll_fast

# The registration lease renews on a real timer.
REAL_TIME_TESTS = True


class FakeTmuxAdapter:
    """Exercise the registry over HTTP without requiring tmux on every runner."""

    def __init__(self) -> None:
        self.connected_value = False
        self.prepare_count = 0
        self.capture_count = 0
        self.stream_frame_count = 0
        self.registration_token = ""
        self.compass_session_id = ""
        self.origin: interaction.TmuxOrigin | None = None
        self.inspected_origin: interaction.TmuxOrigin | None = None
        self.on_output: Any = None
        self.on_disconnect: Any = None
        self.renewal_stop = threading.Event()
        self.renewal_thread: threading.Thread | None = None

    def prepare(self) -> interaction.TmuxOrigin:
        self.prepare_count += 1
        self.connected_value = True
        self.renewal_stop = threading.Event()
        suffix = str(self.prepare_count)
        return interaction.TmuxOrigin(
            server_socket=f"/tmp/disposable-{suffix}.sock",
            server_pid=f"10{suffix}",
            session_id=f"${suffix}",
            session_name=f"disposable-{suffix}",
            window_id=f"@{suffix}",
            window_index="0",
            window_name="registered-origin",
            pane_id=f"%{suffix}",
            pane_index="0",
            pane_tty=f"/dev/pts/{suffix}",
            pane_cols="202",
            pane_rows="58",
        )

    def start_client(
        self,
        port: int,
        registration_token: str,
        compass_session_id: str,
        lease_sec: float,
        origin: interaction.TmuxOrigin,
    ) -> None:
        self.registration_token = registration_token
        self.compass_session_id = compass_session_id
        self.origin = origin

        def register_and_renew() -> None:
            status, registered = interaction.request(
                port,
                "POST",
                "/api/interaction/register",
                {
                    "registration_token": registration_token,
                    "compass_session_id": compass_session_id,
                    "origin": origin.as_dict(),
                },
            )
            if status != 200 or registered.get("state") != "registered":
                return
            origin_id = registered["origin_id"]
            lease_token = registered["lease_token"]
            interval = max(0.01, lease_sec / 3)
            while not self.renewal_stop.wait(interval):
                try:
                    _status, result = interaction.request(
                        port,
                        "POST",
                        "/api/interaction/renew",
                        {"origin_id": origin_id, "lease_token": lease_token},
                    )
                except OSError:
                    return
                if result.get("state") != "renewed":
                    return

        self.renewal_thread = threading.Thread(target=register_and_renew, daemon=True)
        self.renewal_thread.start()

    def bind_origin(self, origin: interaction.TmuxOrigin) -> None:
        if self.origin is not None and origin != self.origin:
            raise interaction.OriginUnavailableError("fake external origin changed")
        self.origin = origin

    def start_read_only_stream(
        self,
        origin: interaction.TmuxOrigin,
        on_output: Any,
        on_disconnect: Any,
    ) -> None:
        self.on_output = on_output
        self.on_disconnect = on_disconnect
        self.emit_frame(origin)

    def stop_read_only_stream(self) -> None:
        callback = self.on_disconnect
        self.on_disconnect = None
        if callback is not None:
            callback()

    def emit_frame(self, origin: interaction.TmuxOrigin | None = None) -> None:
        active_origin = origin or self.origin
        if active_origin is None or self.on_output is None:
            return
        self.stream_frame_count += 1
        self.on_output(active_origin.pane_id, f"stream frame {self.stream_frame_count}\n")

    def inspect(self, origin: interaction.TmuxOrigin) -> interaction.TmuxOrigin:
        if not self.connected_value:
            raise interaction.OriginUnavailableError("fake tmux disconnected")
        return self.inspected_origin or origin

    def capture(self, origin: interaction.TmuxOrigin) -> str:
        self.inspect(origin)
        self.capture_count += 1
        return f"Compass skill-shaped origin client\nframe {self.capture_count}\n"

    def connected(self, _origin: interaction.TmuxOrigin) -> bool:
        return self.connected_value

    def stop(self) -> None:
        self.stop_read_only_stream()
        self.connected_value = False
        self.renewal_stop.set()
        if self.renewal_thread is not None:
            self.renewal_thread.join(1.0)
            self.renewal_thread = None


class InteractionPrototypeHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = FakeTmuxAdapter()
        self.prototype = interaction.InteractionPrototype(self.adapter, lease_sec=0.3)
        self.httpd = http_api.CompassHTTPServer(
            ("127.0.0.1", 0),
            build_app(),
            PAGE_BYTES,
            interaction_prototype=self.prototype,
        )
        self.thread = threading.Thread(target=poll_fast(self.httpd), daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(2.0)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.httpd.server_port,
            timeout=30,
        )
        raw = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if raw is not None else {}
        try:
            connection.request(method, path, body=raw, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            try:
                result = json.loads(response_body or b"{}")
            except ValueError:
                result = {}
            return response.status, result if isinstance(result, dict) else {}
        finally:
            connection.close()

    def _open_stream(self) -> socket.socket:
        client = socket.create_connection(("127.0.0.1", self.httpd.server_port), timeout=30)
        request = (
            "GET /api/interaction/stream HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.httpd.server_port}\r\n"
            f"Origin: http://127.0.0.1:{self.httpd.server_port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
        )
        client.sendall(request.encode("ascii"))
        headers = bytearray()
        while not headers.endswith(b"\r\n\r\n"):
            headers.extend(client.recv(1))
        self.assertIn(b" 101 ", headers)
        return client

    @staticmethod
    def _read_stream_frame(client: socket.socket) -> tuple[int, bytes]:
        header = client.recv(2)
        if len(header) != 2:
            raise AssertionError("incomplete WebSocket frame header")
        length = header[1] & 0x7F
        if length == 126:
            length = int.from_bytes(client.recv(2), "big")
        elif length == 127:
            length = int.from_bytes(client.recv(8), "big")
        payload = bytearray()
        while len(payload) < length:
            payload.extend(client.recv(length - len(payload)))
        return header[0] & 0x0F, bytes(payload)

    def test_vendored_assets_require_feature_and_same_origin(self) -> None:
        vendor = Path(interaction.__file__).parent / "web" / "vendor"
        for name, content_type in (("xterm.js", "text/javascript"), ("xterm.css", "text/css")):
            for headers, expected in (
                ({}, 200),
                ({"Origin": "https://evil.example"}, 403),
                ({"Sec-Fetch-Site": "cross-site"}, 403),
                ({"Sec-Fetch-Site": "same-site"}, 403),
            ):
                with self.subTest(name=name, headers=headers):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", self.httpd.server_port, timeout=30
                    )
                    try:
                        connection.request("GET", "/assets/" + name, headers=headers)
                        response = connection.getresponse()
                        body = response.read()
                        self.assertEqual(expected, response.status)
                        if expected == 200:
                            self.assertEqual(content_type, response.getheader("Content-Type"))
                            self.assertEqual(
                                hashlib.sha256((vendor / name).read_bytes()).digest(),
                                hashlib.sha256(body).digest(),
                            )
                    finally:
                        connection.close()
        self.assertEqual(0, self.adapter.prepare_count)
        prototype = self.httpd.interaction_prototype
        self.httpd.interaction_prototype = None
        try:
            for path in ("/assets/xterm.js", "/assets/xterm.css", "/assets/../observer.py"):
                connection = http.client.HTTPConnection(
                    "127.0.0.1", self.httpd.server_port, timeout=30
                )
                try:
                    connection.request("GET", path)
                    response = connection.getresponse()
                    response.read()
                    self.assertEqual(404, response.status)
                finally:
                    connection.close()
        finally:
            self.httpd.interaction_prototype = prototype

    def test_asset_refuses_a_nonloopback_peer_even_with_local_host_header(self) -> None:
        # Given: a nonloopback peer passes the mocked local-host check.
        handler = object.__new__(http_api._RequestHandler)
        handler.client_address = ("192.0.2.1", 3000)
        handler.headers = http.client.HTTPMessage()
        with (
            mock.patch.object(handler, "_local_ok", return_value=True),
            mock.patch.object(handler, "send_error") as error,
            mock.patch.object(handler, "_send") as send,
        ):
            # When: request the vendored terminal asset.
            handler._interaction_asset("/assets/xterm.js")

        # Then
        error.assert_called_once_with(403)
        send.assert_not_called()

    def test_stream_backlog_is_bounded_in_bytes_and_oversized_frame_disconnects(self) -> None:
        self._request("GET", "/api/interaction/state")
        assert self.adapter.origin is not None
        for _index in range(50):
            self.prototype._on_stream_output(self.adapter.origin.pane_id, "界" * 1000)
        frame = self.prototype.wait_stream(self.httpd.server_port, 1, 0)
        self.assertLessEqual(len(frame["data"].encode("utf-8")), 65536)
        self.assertLessEqual(
            sum(len(row[1].encode("utf-8")) for row in self.prototype._stream_frames), 65536
        )
        self.prototype._on_stream_output(self.adapter.origin.pane_id, "界" * 65536)
        self.assertFalse(self.prototype._stream_connected)

    def test_exact_tmux_origin_renews_and_attaches_read_only(self) -> None:
        status, initial = self._request("GET", "/api/interaction/state")
        self.assertEqual(200, status)
        self.assertEqual("registered", initial["origin_state"])
        self.assertEqual("codex:disposable-tmux-origin:1", initial["compass_session_id"])
        self.assertEqual("read-only-control-stream", initial["terminal_power"])
        self.assertEqual("not-exposed", initial["keyboard_input"])
        self.assertEqual(
            {
                "server_socket",
                "server_pid",
                "session_id",
                "session_name",
                "window_id",
                "window_index",
                "window_name",
                "pane_id",
                "pane_index",
                "pane_tty",
                "pane_cols",
                "pane_rows",
            },
            set(initial["origin"]),
        )

        _status, first_view = self._request("GET", "/api/interaction/view")
        self.adapter.emit_frame()
        assert self.adapter.on_output is not None
        self.adapter.on_output("%altered", "must-not-select\n")
        _status, reconnected_view = self._request("GET", "/api/interaction/view")
        self.assertEqual("viewed", first_view["state"])
        self.assertEqual(first_view["origin_id_hint"], reconnected_view["origin_id_hint"])
        self.assertEqual("tmux-control-mode-read-only", first_view["bridge"])
        self.assertEqual("output-only-WebSocket", first_view["browser_transport"])
        self.assertTrue(first_view["terminal_attachment"])
        self.assertFalse(first_view["browser_pty"])
        self.assertEqual("not-exposed", first_view["keyboard_input"])
        self.assertEqual(1, first_view["capture_sequence"])
        self.assertEqual(2, reconnected_view["capture_sequence"])
        self.assertNotEqual(first_view["text"], reconnected_view["text"])
        self.assertNotIn("must-not-select", reconnected_view["text"])
        self.assertEqual(0, self.adapter.capture_count)

        # Hosted macOS runners can schedule the renewal after the old 120 ms sleep, and a loaded one
        # after two seconds. The renewal is waited for, so the bound only ends a test that failed.
        deadline = time.monotonic() + 30.0
        while True:
            _status, renewed = self._request("GET", "/api/interaction/state")
            if renewed["renewal_count"] >= 1 or time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        self.assertGreaterEqual(renewed["renewal_count"], 1)
        self.assertEqual("registered", renewed["origin_state"])

    def test_stale_unregistered_spoofed_and_keyboard_paths_are_refused(self) -> None:
        self._request("GET", "/api/interaction/state")
        _status, unregistered = self._request(
            "POST",
            "/api/interaction/probe-unregistered",
            {},
        )
        self.assertEqual(
            {"state": "refused", "reason": "unregistered-origin"},
            unregistered,
        )
        assert self.adapter.origin is not None
        _status, repeated = self._request(
            "POST",
            "/api/interaction/register",
            {
                "registration_token": self.adapter.registration_token,
                "compass_session_id": self.adapter.compass_session_id,
                "origin": self.adapter.origin.as_dict(),
            },
        )
        self.assertEqual(
            {"state": "refused", "reason": "registration-token-consumed"},
            repeated,
        )
        _status, altered_session = self._request(
            "POST",
            "/api/interaction/register",
            {
                "registration_token": self.adapter.registration_token,
                "compass_session_id": "codex:altered-session",
                "origin": self.adapter.origin.as_dict(),
            },
        )
        self.assertEqual(
            {"state": "refused", "reason": "session-mismatch"},
            altered_session,
        )
        _status, spoofed = self._request("POST", "/api/interaction/probe-spoofed", {})
        self.assertEqual({"state": "refused", "reason": "origin-mismatch"}, spoofed)

        input_status, input_refusal = self._request(
            "POST",
            "/api/interaction/input",
            {"text": "must not reach tmux"},
        )
        self.assertEqual(200, input_status)
        self.assertEqual(
            {"state": "refused", "reason": "read-only-capability"},
            input_refusal,
        )
        _status, control = self._request(
            "POST",
            "/api/interaction/control",
            {"t": "cmd", "argv": ["send-keys", "-t", "%1", "must-not-arrive"]},
        )
        self.assertEqual({"state": "refused", "reason": "read-only-capability"}, control)
        self.assertEqual(0, self.adapter.capture_count)
        _status, unchanged = self._request("GET", "/api/interaction/view")
        self.assertNotIn("must not reach tmux", unchanged["text"])
        self.assertNotIn("must-not-arrive", unchanged["text"])

        _status, expired = self._request("POST", "/api/interaction/expire", {})
        self.assertEqual("stale", expired["origin_state"])
        _status, stale_view = self._request("GET", "/api/interaction/view")
        self.assertEqual({"state": "refused", "reason": "stale-registration"}, stale_view)
        time.sleep(0.12)
        _status, still_stale = self._request("GET", "/api/interaction/state")
        self.assertEqual("stale", still_stale["origin_state"])

    def test_browser_cannot_name_origin_and_disconnect_is_not_success(self) -> None:
        _status, initial = self._request("GET", "/api/interaction/state")
        target_status, _body = self._request(
            "GET",
            "/api/interaction/view?pane_id=%25arbitrary&server_socket=%2Ftmp%2Fother",
        )
        self.assertEqual(400, target_status)

        _status, disconnected = self._request("POST", "/api/interaction/disconnect", {})
        self.assertTrue(disconnected["connected"])
        self.assertFalse(disconnected["stream_connected"])
        _status, unknown = self._request("GET", "/api/interaction/view")
        self.assertEqual({"state": "unknown", "reason": "control-mode-disconnected"}, unknown)

        _status, reconnected = self._request("POST", "/api/interaction/reconnect", {})
        self.assertEqual("reconnected", reconnected["state"])
        assert self.adapter.origin is not None
        self.assertEqual(initial["origin"]["pane_id"], self.adapter.origin.pane_id)
        _status, same_origin = self._request("GET", "/api/interaction/view")
        self.assertEqual("viewed", same_origin["state"])
        self.assertEqual(reconnected["origin_id_hint"], same_origin["origin_id_hint"])

        _status, reset = self._request("POST", "/api/interaction/reset", {})
        self.assertGreater(reset["generation"], initial["generation"])
        self.assertNotEqual(reset["origin"]["server_socket"], initial["origin"]["server_socket"])
        _status, restored = self._request("GET", "/api/interaction/view")
        self.assertEqual("viewed", restored["state"])

    def test_output_websocket_streams_and_rejects_every_client_frame(self) -> None:
        self._request("GET", "/api/interaction/state")
        client = self._open_stream()
        try:
            opcode, payload = self._read_stream_frame(client)
            frame = json.loads(payload)
            self.assertEqual(1, opcode)
            self.assertEqual("streamed", frame["state"])
            self.assertTrue(frame["reset"])
            self.assertIn("stream frame 1", frame["data"])
            self.assertEqual((202, 58), (frame["cols"], frame["rows"]))
            self.assertEqual(
                [{"sequence": 1, "data": "stream frame 1\n", "cols": 202, "rows": 58}],
                frame["chunks"],
            )

            origin = self.adapter.origin
            assert origin is not None
            self.adapter.inspected_origin = dataclasses.replace(
                origin,
                pane_cols="210",
                pane_rows="60",
            )
            self.adapter.emit_frame()
            opcode, payload = self._read_stream_frame(client)
            delta = json.loads(payload)
            self.assertEqual(1, opcode)
            self.assertFalse(delta["reset"])
            self.assertEqual((210, 60), (delta["cols"], delta["rows"]))
            self.assertEqual(
                [{"sequence": 2, "data": "stream frame 2\n", "cols": 210, "rows": 60}],
                delta["chunks"],
            )

            mask = b"deny"
            text = b"send-keys"
            masked = bytes(value ^ mask[index % 4] for index, value in enumerate(text))
            client.sendall(bytes((0x81, 0x80 | len(text))) + mask + masked)
            opcode, payload = self._read_stream_frame(client)
            self.assertEqual(8, opcode)
            self.assertEqual(1008, int.from_bytes(payload[:2], "big"))
            self.assertEqual(b"read-only-capability", payload[2:])
        finally:
            client.close()


class InteractionPrototypeDisabledTest(unittest.TestCase):
    def test_normal_dashboard_has_no_prototype_routes(self) -> None:
        # Given: the normal dashboard server has no interaction prototype.
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=30)

            # When: request the interaction-state route.
            connection.request("GET", "/api/interaction/state")
            response = connection.getresponse()

            # Then
            self.assertEqual(404, response.status)
            response.read()
            connection.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(2.0)


class SessionEnvironmentTest(unittest.TestCase):
    def test_only_exact_known_harness_session_environment_matches(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "CODEX_THREAD_ID": "exact-codex",
                "CLAUDE_CODE_SESSION_ID": "exact-claude",
            },
            clear=True,
        ):
            self.assertTrue(interaction._session_environment_matches("codex:exact-codex"))
            self.assertTrue(interaction._session_environment_matches("claude:exact-claude"))
            self.assertFalse(interaction._session_environment_matches("codex:altered"))
            self.assertFalse(interaction._session_environment_matches("unknown:exact-codex"))


class CollectedSessionCliBoundaryTest(unittest.TestCase):
    def test_interaction_flags_are_an_exact_pair(self) -> None:
        parser = cli.build_parser()
        for argv in (
            ["--interaction-origin-session", "codex:exact"],
            ["--interaction-origin-registration-file", "/tmp/exact-origin.json"],
        ):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                cli.validate_interaction_args(parser, parser.parse_args(argv))

    def test_only_prelisten_collected_session_ids_enter_registration_boundary(self) -> None:
        application = mock.Mock()
        application.collect_json.return_value = (
            (1, 1),
            json.dumps(
                {
                    "sessions": [
                        {"harness": "codex", "sid": "exact"},
                        {"harness": "codex", "sid": 7},
                        {"harness": "pi"},
                    ]
                }
            ),
        )
        self.assertEqual(frozenset({"codex:exact"}), cli.collected_session_ids(application))
        application.collect_json.assert_called_once_with(show_all=True)


class CollectedSessionOriginHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.registration_file = Path(self.temporary.name) / "origin.json"
        self.session_id = "codex:01a035ee-2a7b-76f0-873f-eaddc97860c3"
        self.adapter = FakeTmuxAdapter()
        self.origin = self.adapter.prepare()
        self.adapter.origin = self.origin
        self.prototype = interaction.InteractionPrototype(
            self.adapter,
            lease_sec=0.3,
            collected_session_id=self.session_id,
            session_exists=lambda value: value == self.session_id,
            registration_file=self.registration_file,
        )
        self.httpd = http_api.CompassHTTPServer(
            ("127.0.0.1", 0),
            build_app(),
            PAGE_BYTES,
            interaction_prototype=self.prototype,
        )
        self.thread = threading.Thread(target=poll_fast(self.httpd), daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(2.0)
        self.temporary.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        connection = http.client.HTTPConnection(
            "127.0.0.1",
            self.httpd.server_port,
            timeout=30,
        )
        raw = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if raw is not None else {}
        try:
            connection.request(method, path, body=raw, headers=headers)
            response = connection.getresponse()
            raw_response = response.read()
            value = json.loads(raw_response or b"{}")
            return response.status, value if isinstance(value, dict) else {}
        finally:
            connection.close()

    def test_new_server_generation_atomically_supersedes_old_bootstrap(self) -> None:
        adapter_a = FakeTmuxAdapter()
        adapter_b = FakeTmuxAdapter()
        adapter_a.prepare()
        origin_b = adapter_b.prepare()
        prototype_a = interaction.InteractionPrototype(
            adapter_a,
            collected_session_id=self.session_id,
            session_exists=lambda value: value == self.session_id,
            registration_file=self.registration_file,
        )
        prototype_b = interaction.InteractionPrototype(
            adapter_b,
            collected_session_id=self.session_id,
            session_exists=lambda value: value == self.session_id,
            registration_file=self.registration_file,
        )
        prototype_a.start(8766)
        bootstrap_a = json.loads(self.registration_file.read_text(encoding="utf-8"))
        prototype_b.start(8766)
        bootstrap_b = json.loads(self.registration_file.read_text(encoding="utf-8"))

        self.assertNotEqual(bootstrap_a["registration_token"], bootstrap_b["registration_token"])
        self.assertNotEqual(bootstrap_a["server_generation"], bootstrap_b["server_generation"])
        prototype_a.stop()
        self.assertEqual(
            bootstrap_b,
            json.loads(self.registration_file.read_text(encoding="utf-8")),
        )
        self.assertEqual(
            {"state": "refused", "reason": "invalid-registration-token"},
            prototype_b.register(
                bootstrap_a["registration_token"],
                self.session_id,
                origin_b.as_dict(),
                now=1.0,
            ),
        )
        registered = prototype_b.register(
            bootstrap_b["registration_token"],
            self.session_id,
            origin_b.as_dict(),
            now=1.0,
        )
        self.assertEqual("registered", registered["state"])
        self.assertEqual(
            {"state": "refused", "reason": "registration-token-consumed"},
            prototype_b.register(
                bootstrap_b["registration_token"],
                self.session_id,
                origin_b.as_dict(),
                now=1.0,
            ),
        )
        prototype_b.stop()
        self.assertFalse(self.registration_file.exists())

    def test_collected_session_bootstrap_resolves_only_exact_live_origin(self) -> None:
        _status, waiting = self._request("GET", "/api/interaction/state")
        self.assertEqual("unregistered", waiting["origin_state"])
        self.assertEqual("awaiting-session-registration", waiting["reason"])
        self.assertEqual(self.session_id, waiting["compass_session_id"])
        # Windows ignores POSIX permission bits; keep the registration checks there.
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(self.registration_file.stat().st_mode))
        bootstrap = json.loads(self.registration_file.read_text(encoding="utf-8"))

        _status, registered = self._request(
            "POST",
            "/api/interaction/register",
            {
                "registration_token": bootstrap["registration_token"],
                "compass_session_id": self.session_id,
                "origin": self.origin.as_dict(),
            },
        )
        self.assertEqual("registered", registered["state"])
        harness, sid = self.session_id.split(":", 1)
        _status, resolved = self._request(
            "GET",
            f"/api/interaction/origin?harness={harness}&sid={sid}",
        )
        self.assertEqual("registered", resolved["state"])
        self.assertEqual(self.origin.as_dict(), resolved["origin"])
        self.assertEqual("read-only-control-stream", resolved["terminal_power"])

        renamed = dataclasses.replace(
            self.origin,
            session_name="renamed-session",
            window_index="9",
            window_name="automatic-rename",
            pane_index="4",
            pane_cols="210",
            pane_rows="60",
        )
        self.adapter.inspected_origin = renamed
        _status, renewed = self._request(
            "POST",
            "/api/interaction/renew",
            {
                "origin_id": registered["origin_id"],
                "lease_token": registered["lease_token"],
            },
        )
        self.assertEqual("renewed", renewed["state"])
        _status, renamed_result = self._request(
            "GET",
            f"/api/interaction/origin?harness={harness}&sid={sid}",
        )
        self.assertEqual("registered", renamed_result["state"])
        self.assertEqual(renamed.as_dict(), renamed_result["origin"])
        _status, renamed_state = self._request("GET", "/api/interaction/state")
        self.assertEqual(renamed.as_dict(), renamed_state["origin"])
        self.adapter.inspected_origin = None

        _status, wrong_session = self._request(
            "GET",
            "/api/interaction/origin?harness=codex&sid=altered",
        )
        self.assertEqual(
            {"state": "refused", "reason": "session-mismatch"},
            wrong_session,
        )
        altered = dataclasses.replace(self.origin, pane_id="%altered")
        _status, wrong_origin = self._request(
            "POST",
            "/api/interaction/register",
            {
                "registration_token": bootstrap["registration_token"],
                "compass_session_id": self.session_id,
                "origin": altered.as_dict(),
            },
        )
        self.assertEqual({"state": "refused", "reason": "origin-mismatch"}, wrong_origin)

    def test_expired_disconnected_replaced_and_input_paths_refuse(self) -> None:
        self._request("GET", "/api/interaction/state")
        bootstrap = json.loads(self.registration_file.read_text(encoding="utf-8"))
        body = {
            "registration_token": bootstrap["registration_token"],
            "compass_session_id": self.session_id,
            "origin": self.origin.as_dict(),
        }
        self._request("POST", "/api/interaction/register", body)
        harness, sid = self.session_id.split(":", 1)
        route = f"/api/interaction/origin?harness={harness}&sid={sid}"

        self.adapter.inspected_origin = dataclasses.replace(
            self.origin,
            server_pid="replacement-server-pid",
        )
        _status, replaced_server = self._request("GET", route)
        self.assertEqual(
            {"state": "unknown", "reason": "origin-changed"},
            replaced_server,
        )

        self.adapter.inspected_origin = dataclasses.replace(
            self.origin,
            pane_tty="/dev/pts/replaced",
        )
        _status, replaced = self._request("GET", route)
        self.assertEqual({"state": "unknown", "reason": "origin-changed"}, replaced)
        self.adapter.inspected_origin = None
        self.adapter.connected_value = False
        _status, disconnected = self._request("GET", route)
        self.assertEqual({"state": "unknown", "reason": "origin-disconnected"}, disconnected)
        self.adapter.connected_value = True

        _status, input_result = self._request(
            "POST",
            "/api/interaction/input",
            {"text": "must-not-arrive"},
        )
        self.assertEqual(
            {"state": "refused", "reason": "read-only-capability"},
            input_result,
        )
        self._request("POST", "/api/interaction/expire", {})
        _status, expired = self._request("GET", route)
        self.assertEqual({"state": "refused", "reason": "stale-registration"}, expired)


class ControlModeParsingTest(unittest.TestCase):
    def test_output_parser_decodes_tmux_octal_bytes_and_names_exact_pane(self) -> None:
        self.assertEqual(
            ("%7", "hello\r\nλ"),
            interaction._control_mode_output(b"%output %7 hello\\015\\012\xce\xbb"),
        )
        self.assertIsNone(interaction._control_mode_output(b"%session-changed $0 disposable"))


class RegistrationFileCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "registration.json"
        self.prototype = interaction.InteractionPrototype(
            FakeTmuxAdapter(),
            collected_session_id="codex:one",
            registration_file=self.path,
        )
        self.prototype.start(4553)
        self.bootstrap = self.path.read_bytes()
        platform_os = SimpleNamespace(
            **{key: value for key, value in vars(os).items() if key not in {"getuid", "O_NOFOLLOW"}}
        )
        patcher = mock.patch.object(interaction, "os", platform_os)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stop_removes_own_file_without_posix_ownership_checks(self) -> None:
        # Given: the registration file exists and POSIX ownership reads are unsupported.
        with self.assertRaisesRegex(ValueError, "POSIX ownership checks"):
            interaction._read_registration_file(self.path)

        # When: stop the prototype.
        self.prototype.stop()

        # Then
        self.assertFalse(self.path.exists())

    def test_stop_preserves_newer_generation_without_posix_ownership_checks(self) -> None:
        newer = interaction.InteractionPrototype(
            FakeTmuxAdapter(),
            collected_session_id="codex:one",
            registration_file=self.path,
        )
        newer.start(4554)
        newer_bootstrap = self.path.read_bytes()
        self.prototype.stop()
        self.assertEqual(newer_bootstrap, self.path.read_bytes())
        newer.stop()
        self.assertFalse(self.path.exists())

    def test_stop_preserves_oversized_and_malformed_files(self) -> None:
        # Given: the registration path contains each oversized or malformed payload.
        for payload in (self.bootstrap + b" " * 16384, b"{", b"[]"):
            with self.subTest(payload_size=len(payload)):
                self.path.write_bytes(payload)

                # When: stop the prototype.
                self.prototype.stop()

                # Then
                self.assertEqual(payload, self.path.read_bytes())

    def test_stop_preserves_nonregular_file(self) -> None:
        # Given: the registration path has been replaced by a directory.
        self.path.unlink()
        self.path.mkdir()

        # When: stop the prototype.
        self.prototype.stop()

        # Then
        self.assertTrue(self.path.is_dir())

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires symlink support")
    def test_stop_preserves_symlink_without_posix_ownership_checks(self) -> None:
        # Given: the registration path is a symlink to the original bootstrap.
        target = self.path.with_name("target.json")
        self.path.rename(target)
        self.path.symlink_to(target)

        # When: stop the prototype.
        self.prototype.stop()

        # Then
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(self.bootstrap, target.read_bytes())

    def test_waiting_client_explains_unavailable_posix_checks(self) -> None:
        # Given: POSIX registration checks are unavailable and stdout is captured.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            # When: run the waiting terminal client.
            result = interaction._run_waiting_tmux_client(self.path)

        # Then
        self.assertEqual(1, result)
        self.assertIn("terminal registration unsupported", output.getvalue())
        self.assertIn("POSIX ownership checks", output.getvalue())


@unittest.skipUnless(
    hasattr(os, "O_NOFOLLOW") and hasattr(os, "getuid"), "requires POSIX file ownership"
)
class RegistrationFileSecurityTest(unittest.TestCase):
    def test_read_checks_actual_permissions_ownership_symlink_and_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registration.json"
            path.write_text('{"port":4553}', encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual({"port": 4553}, interaction._read_registration_file(path))
            for mode in (0o644, 0o660, 0o606, 0o400):
                path.chmod(mode)
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    interaction._read_registration_file(path)
            path.chmod(0o600)
            with (
                mock.patch.object(os, "getuid", return_value=os.getuid() + 1),
                self.assertRaises(ValueError),
            ):
                interaction._read_registration_file(path)
            target = path.with_name("target.json")
            path.rename(target)
            path.symlink_to(target)
            self.assertTrue(path.is_symlink())
            with self.assertRaises((OSError, ValueError)):
                interaction._read_registration_file(path)
            path.unlink()
            target.rename(path)
            path.write_text('{"large":"' + "x" * 16384 + '"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                interaction._read_registration_file(path)

    def test_disposable_client_writer_produces_a_private_readable_file(self) -> None:
        # Given: the adapter has an exact origin and a temporary client-config path.
        with tempfile.TemporaryDirectory() as tmp:
            adapter = interaction.TmuxAdapter()
            adapter._client_config = Path(tmp) / "client.json"
            origin = FakeTmuxAdapter().prepare()
            adapter._origin = origin

            # When: start the disposable client.
            adapter.start_client(4553, "token", "codex:one", 15, origin)

            # Then
            self.assertEqual(0o600, stat.S_IMODE(adapter._client_config.stat().st_mode))
            self.assertEqual(
                "token",
                interaction._read_registration_file(adapter._client_config)["registration_token"],
            )

    def test_waiting_client_cannot_use_a_public_registration_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registration.json"
            path.write_text(
                json.dumps(
                    {
                        "port": 4553,
                        "registration_token": "secret",
                        "compass_session_id": "codex:one",
                        "lease_sec": 10,
                        "require_session_environment": False,
                    }
                ),
                encoding="utf-8",
            )
            path.chmod(0o644)
            with mock.patch.object(interaction, "_run_tmux_client", return_value=0) as run:
                self.assertEqual(1, interaction._run_waiting_tmux_client(path))
            run.assert_not_called()


class ControlModeBufferSecurityTest(unittest.TestCase):
    def test_unterminated_control_line_is_bounded_before_next_read(self) -> None:
        # Given: control output fills the line limit without a terminator.
        adapter = interaction.TmuxAdapter()
        output, disconnected = mock.Mock(), mock.Mock()
        with (
            mock.patch.object(select, "select", return_value=([1], [], [])),
            mock.patch.object(
                os,
                "read",
                side_effect=[b"x" * 65536, b"y", AssertionError("unbounded pending line")],
            ),
        ):
            # When: read the control-mode stream.
            adapter._read_control_mode(1, output, disconnected)

        # Then
        output.assert_not_called()
        disconnected.assert_called_once()


if __name__ == "__main__":
    unittest.main()
