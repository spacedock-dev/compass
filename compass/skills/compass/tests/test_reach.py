"""Unit tests for the off-machine reach nudge module (DRC-4034, DEC-4)."""

from __future__ import annotations

import contextlib
import http.client
import http.server
import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import cli, reach
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .support import LoopbackHTTPServer, poll_fast


def make_config(**overrides: Any) -> Any:
    state_dir = overrides.pop("state_dir", None) or tempfile.mkdtemp()
    environ = {**overrides.pop("environ", {}), "COMPASS_HOME": state_dir}
    return build_runtime_config(
        environ=environ,
        platform_name="darwin",
        os_name="posix",
        launcher_path=Path("/path/to/server.py"),
        **overrides,
    )


class MockReachServer(LoopbackHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _MockReachHandler)
        self.received_requests: list[dict[str, Any]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()


class _MockReachHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        server: MockReachServer = self.server  # type: ignore[assignment]
        server.received_requests.append(
            {
                "path": self.path,
                "headers": dict(self.headers),
                "body": body,
                "json": json.loads(body.decode("utf-8")),
            }
        )
        server.started.set()
        server.release.wait(30)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')


class ReachNudgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = MockReachServer()
        self.server_thread = threading.Thread(target=poll_fast(self.server), daemon=True)
        self.server_thread.start()
        self.url = f"https://127.0.0.1:{self.server.server_address[1]}/webhook"

        # Keep the real HTTPS opener and HTTP parser; replace only TLS setup for the local stub.
        def connect(connection: http.client.HTTPSConnection) -> None:
            connection.sock = socket.create_connection(
                (connection.host, connection.port), timeout=connection.timeout
            )

        patch = mock.patch.object(http.client.HTTPSConnection, "connect", connect)
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self) -> None:
        self.server.release.set()
        self.server.shutdown()
        self.server.server_close()

    def wait_worker(self, state: Any) -> None:
        worker = getattr(state, "reach_worker", None)
        if worker is not None:
            worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_blocked_webhook_does_not_hold_up_collection_or_spawn_more_workers(self) -> None:
        cfg = make_config(reach_url=self.url, reach_cooldown_sec=0)
        state = build_runtime_state(cfg, started=100.0)
        sessions = [{"active": True, "state": "needs_input"}]
        self.server.release.clear()
        collector_done = threading.Event()

        def collect() -> None:
            with state.collect_memo_lock:
                reach.maybe_reach_nudge(cfg, state, sessions, now=100.0)
            collector_done.set()

        collector = threading.Thread(target=collect, daemon=True)
        collector.start()
        try:
            self.assertTrue(self.server.started.wait(5), "no webhook request arrived")
            self.assertTrue(collector_done.wait(1), "webhook blocked the collector")
            self.assertTrue(state.collect_memo_lock.acquire(timeout=1))
            state.collect_memo_lock.release()
            first = state.reach_worker
            for index in range(1, 20):
                self.assertFalse(
                    reach.maybe_reach_nudge(cfg, state, sessions * (index + 1), now=100.0 + index)
                )
                self.assertIs(first, state.reach_worker)
        finally:
            self.server.release.set()
            collector.join(5)
            self.wait_worker(state)
        self.assertEqual(1, len(self.server.received_requests))
        self.assertTrue(reach.maybe_reach_nudge(cfg, state, sessions * 2, now=200.0))
        self.wait_worker(state)
        self.assertEqual(2, len(self.server.received_requests))

    def test_zero_during_delivery_rearms_matching_episode(self) -> None:
        resolving = threading.Event()
        resolution_release = threading.Event()
        resolve_url = reach.resolve_reach_url

        def resolve(config: Any) -> str | None:
            resolving.set()
            resolution_release.wait(5)
            return resolve_url(config)

        for blocked_phase in ("delivery", "url_resolution"):
            with self.subTest(blocked_phase=blocked_phase), tempfile.TemporaryDirectory() as td:
                cfg = make_config(state_dir=td, reach_url=self.url, reach_cooldown_sec=0)
                state = build_runtime_state(cfg, started=100.0)
                sessions = [{"active": True, "state": "needs_input"}]
                initial_requests = len(self.server.received_requests)
                resolving.clear()
                resolution_release.clear()
                if blocked_phase == "delivery":
                    resolution_release.set()

                self.server.started.clear()
                self.server.release.clear()
                with mock.patch.object(reach, "resolve_reach_url", side_effect=resolve):
                    try:
                        self.assertTrue(reach.maybe_reach_nudge(cfg, state, sessions, now=100.0))
                        if blocked_phase == "delivery":
                            self.assertTrue(
                                self.server.started.wait(5), "no webhook request arrived"
                            )
                        else:
                            self.assertTrue(resolving.wait(5), "URL resolution never started")
                        self.assertFalse(reach.maybe_reach_nudge(cfg, state, [], now=101.0))
                    finally:
                        resolution_release.set()
                        self.server.release.set()
                        self.wait_worker(state)

                    self.assertEqual(initial_requests + 1, len(self.server.received_requests))
                    try:
                        self.assertTrue(reach.maybe_reach_nudge(cfg, state, sessions, now=102.0))
                    finally:
                        self.wait_worker(state)
                    self.assertEqual(initial_requests + 2, len(self.server.received_requests))
                    self.assertEqual(
                        {"needs_input": 1, "finished_unread": 0},
                        self.server.received_requests[-1]["json"],
                    )

    def test_payload_contains_strictly_counts_and_no_other_fields(self) -> None:
        payload_bytes = reach.format_reach_payload(needs_input=3, finished_unread=2)
        parsed = json.loads(payload_bytes.decode("utf-8"))
        self.assertEqual(parsed, {"needs_input": 3, "finished_unread": 2})
        self.assertEqual(set(parsed.keys()), {"needs_input", "finished_unread"})

    def test_opener_disables_proxies_and_refuses_redirects(self) -> None:
        with mock.patch("urllib.request.build_opener") as mock_build:
            reach.build_reach_opener()
            mock_build.assert_called_once()
            args = mock_build.call_args[0]
            proxies = [h for h in args if isinstance(h, urllib.request.ProxyHandler)]
            self.assertEqual(len(proxies), 1)
            self.assertEqual(getattr(proxies[0], "proxies", None), {})
            self.assertIn(reach._NoRedirects, args)
            no_redirect = reach._NoRedirects()
            req = mock.MagicMock()
            self.assertIsNone(no_redirect.redirect_request(req, None, 302, "Found", {}, "http://x"))

    def test_resolve_reach_url_from_config(self) -> None:
        cfg = make_config(reach_url=self.url)
        self.assertEqual(reach.resolve_reach_url(cfg), self.url)

    def test_resolve_reach_url_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(state_dir=td)
            url_file = os.path.join(td, "reach_url")
            with open(url_file, "w", encoding="utf-8") as f:
                f.write(f"  {self.url}\n")
            self.assertEqual(reach.resolve_reach_url(cfg), self.url)

    def test_no_reach_switch_disables_url_resolution(self) -> None:
        cfg = make_config(reach_url=self.url, reach_enabled=False)
        self.assertIsNone(reach.resolve_reach_url(cfg))

    def test_nudge_delivered_when_active_session_enters_needs_input(self) -> None:
        cfg = make_config(reach_url=self.url)
        state = build_runtime_state(cfg, started=100.0)
        sessions = [
            {"sid": "s1", "harness": "claude", "active": True, "state": "needs_input"},
            {"sid": "s2", "harness": "claude", "active": True, "state": "working"},
        ]
        sent = reach.maybe_reach_nudge(cfg, state, sessions, now=100.0)
        self.assertTrue(sent)
        self.wait_worker(state)
        self.assertEqual(len(self.server.received_requests), 1)
        req = self.server.received_requests[0]
        self.assertEqual(req["json"], {"needs_input": 1, "finished_unread": 0})
        self.assertEqual(req["headers"]["Content-Type"], "application/json")

    def test_nudge_throttled_by_cooldown_interval(self) -> None:
        cfg = make_config(reach_url=self.url, reach_cooldown_sec=60.0)
        state = build_runtime_state(cfg, started=100.0)
        sessions1 = [
            {"sid": "s1", "harness": "claude", "active": True, "state": "needs_input"},
        ]
        self.assertTrue(reach.maybe_reach_nudge(cfg, state, sessions1, now=100.0))
        self.wait_worker(state)
        self.assertEqual(len(self.server.received_requests), 1)

        # Same counts within cooldown -> no post
        self.assertFalse(reach.maybe_reach_nudge(cfg, state, sessions1, now=110.0))
        self.assertEqual(len(self.server.received_requests), 1)

        # Different counts within cooldown -> throttled, no post yet
        sessions2 = [
            {"sid": "s1", "harness": "claude", "active": True, "state": "needs_input"},
            {"sid": "s2", "harness": "codex", "active": True, "state": "needs_input"},
        ]
        self.assertFalse(reach.maybe_reach_nudge(cfg, state, sessions2, now=120.0))
        self.assertEqual(len(self.server.received_requests), 1)

        # Cooldown elapsed -> post sent with updated counts
        self.assertTrue(reach.maybe_reach_nudge(cfg, state, sessions2, now=165.0))
        self.wait_worker(state)
        self.assertEqual(len(self.server.received_requests), 2)
        self.assertEqual(
            self.server.received_requests[1]["json"], {"needs_input": 2, "finished_unread": 0}
        )

    def test_no_reach_flag_never_attempts_post(self) -> None:
        cfg = make_config(reach_url=self.url, reach_enabled=False)
        state = build_runtime_state(cfg, started=100.0)
        sessions = [
            {"sid": "s1", "harness": "claude", "active": True, "state": "needs_input"},
        ]
        sent = reach.maybe_reach_nudge(cfg, state, sessions, now=100.0)
        self.assertFalse(sent)
        self.assertEqual(len(self.server.received_requests), 0)

    def test_diagnostics_sink_never_leaks_credential_url(self) -> None:
        diagnostics: list[str] = []
        cfg = make_config(reach_url="http://127.0.0.1:1/invalid_secret_token_12345")
        sent = reach.send_reach_nudge(cfg, cfg.reach_url, 1, 0, diagnostic_sink=diagnostics.append)
        self.assertFalse(sent)
        combined_logs = " ".join(diagnostics)
        self.assertNotIn("invalid_secret_token_12345", combined_logs)


class ReachHTTPSSettingTest(unittest.TestCase):
    def test_a_plain_http_setting_is_refused_from_every_configuration_source(self) -> None:
        url = "http://example.test/private-webhook"
        with tempfile.TemporaryDirectory() as td:
            for source in ("argument", "environment", "file"):
                with self.subTest(source=source):
                    overrides: dict[str, Any] = {"state_dir": td}
                    if source == "argument":
                        overrides["reach_url"] = url
                    elif source == "environment":
                        overrides["environ"] = {"COMPASS_REACH_URL": url}
                    else:
                        (Path(td) / "reach_url").write_text(url)
                    self.assertIsNone(reach.resolve_reach_url(make_config(**overrides)))

    def test_a_plain_http_nudge_is_refused_before_opening_a_connection(self) -> None:
        diagnostics: list[str] = []
        with mock.patch.object(urllib.request.OpenerDirector, "open") as opened:
            self.assertFalse(
                reach.send_reach_nudge(
                    make_config(),
                    "http://example.test/private-webhook",
                    1,
                    0,
                    diagnostic_sink=diagnostics.append,
                )
            )
        opened.assert_not_called()
        self.assertIn("HTTPS", " ".join(diagnostics))
        self.assertNotIn("private-webhook", " ".join(diagnostics))

    def test_the_command_refuses_http_and_explains_https_in_the_setting_help(self) -> None:
        parser = cli.build_parser()
        self.assertIn("HTTPS", parser.format_help())
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            parser.parse_args(["--reach-url", "http://example.test/private-webhook"])
        self.assertEqual(2, raised.exception.code)
        self.assertIn("HTTPS", errors.getvalue())
        self.assertNotIn("private-webhook", errors.getvalue())
        self.assertEqual(
            "https://example.test/webhook",
            parser.parse_args(["--reach-url", "https://example.test/webhook"]).reach_url,
        )


class ReachDeadlineTest(unittest.TestCase):
    # Measures abandonment of a continuously dripping webhook against elapsed time.
    REAL_TIME_TESTS = True

    def test_a_webhook_dripping_headers_is_abandoned_within_the_exchange_deadline(self) -> None:
        client, server = socket.socketpair()
        stop = threading.Event()
        received = threading.Event()

        def drip() -> None:
            try:
                server.recv(4096)
                received.set()
                server.sendall(b"HTTP/1.1 200 OK\r\nX-Drip: ")
                for _ in range(50):
                    if stop.wait(0.02):
                        return
                    server.sendall(b" ")
                server.sendall(b"\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass

        worker = threading.Thread(target=drip, daemon=True)
        worker.start()
        diagnostics: list[str] = []
        began = time.monotonic()
        try:
            with (
                mock.patch.object(
                    http.client.HTTPSConnection,
                    "connect",
                    lambda connection: setattr(connection, "sock", client),
                ),
                mock.patch.object(reach, "REACH_TIMEOUT_SEC", 0.1),
            ):
                sent = reach.send_reach_nudge(
                    make_config(),
                    "https://example.test/webhook",
                    1,
                    0,
                    diagnostic_sink=diagnostics.append,
                )
            self.assertTrue(received.is_set(), "the webhook received no POST")
            self.assertFalse(sent)
            self.assertLess(time.monotonic() - began, 0.7)
            self.assertTrue(diagnostics)
        finally:
            stop.set()
            client.close()
            server.close()
            worker.join(2)
            self.assertFalse(worker.is_alive())


class ReachURLFileTest(unittest.TestCase):
    def test_environment_is_captured_in_config_not_read_from_the_process(self) -> None:
        env = {"COMPASS_REACH_URL": "https://configured.example/webhook"}
        cfg = make_config(environ=env)
        env["COMPASS_REACH_URL"] = "https://changed.example/webhook"
        with mock.patch.dict(os.environ, {"COMPASS_REACH_URL": "https://ambient.example/webhook"}):
            self.assertEqual("https://configured.example/webhook", reach.resolve_reach_url(cfg))
            self.assertIsNone(reach.resolve_reach_url(make_config()))

    def test_stored_url_symlink_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.write_text("https://example.test/webhook")
            (Path(td) / "reach_url").symlink_to(target)
            self.assertIsNone(reach.resolve_reach_url(make_config(state_dir=td)))

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "requires no-follow opens")
    def test_a_symlink_substituted_after_the_file_check_is_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reach_url"
            path.write_text("https://example.test/webhook")
            target = Path(td) / "target"
            original = os.lstat

            def replace_with_link(name: str) -> os.stat_result:
                before = original(name)
                path.rename(target)
                path.symlink_to(target)
                return before

            with mock.patch.object(os, "lstat", side_effect=replace_with_link):
                self.assertIsNone(reach.resolve_reach_url(make_config(state_dir=td)))

    def test_symlink_is_refused_even_without_a_native_no_follow_open(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "target"
            target.write_text("https://example.test/webhook")
            (Path(td) / "reach_url").symlink_to(target)
            with mock.patch.object(os, "O_NOFOLLOW", 0, create=True):
                self.assertIsNone(reach.resolve_reach_url(make_config(state_dir=td)))

    def test_nonregular_oversized_and_invalid_utf8_stores_abstain(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(state_dir=td)
            path = Path(td) / "reach_url"
            path.mkdir()
            self.assertIsNone(reach.resolve_reach_url(cfg))
            path.rmdir()
            for content in (b"https://example.test/" + b"x" * 2048, b"https://example.test/\xff"):
                with self.subTest(content=content[:24]):
                    path.write_bytes(content)
                    self.assertIsNone(reach.resolve_reach_url(cfg))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires FIFO support")
    def test_fifo_replacing_a_checked_regular_file_is_refused_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = make_config(state_dir=td)
            path = Path(td) / "reach_url"
            path.touch()
            done = threading.Event()
            results: list[str | None] = []

            original = os.lstat

            def replaced(name: str) -> os.stat_result:
                before = original(name)
                path.unlink()
                os.mkfifo(path)
                return before

            def resolve() -> None:
                results.append(reach.resolve_reach_url(cfg))
                done.set()

            with mock.patch.object(os, "lstat", side_effect=replaced):
                reader = threading.Thread(target=resolve, daemon=True)
                reader.start()
                prompt = done.wait(1)
                if not prompt:
                    fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
                    os.write(fd, b"https://example.test/webhook")
                    os.close(fd)
                reader.join(5)
            self.assertTrue(prompt, "opening a replaced FIFO blocked")
            self.assertEqual([None], results)
