"""Availability bounds at the standalone hook, MCP, and correction edges."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

import mcp_server
import notify_hook
from compass_runtime import correction, loopback_transport, records

from .test_mcp_server import _call, _Harness, _Stdout

# Measures real trickling sockets and the correction formatter's elapsed work.
REAL_TIME_TESTS = True


class EdgeDeadlineTest(unittest.TestCase):
    def test_sendall_uses_remaining_exchange_budget(self) -> None:
        for edge in ("hook", "mcp"):
            with self.subTest(edge=edge):
                self.stalled_write(edge)

    def stalled_write(self, edge: str) -> None:
        budget = 1.0
        socket_type = notify_hook._Socket if edge == "hook" else loopback_transport._Socket
        connect = socket_type.connect
        accepted = threading.Event()
        stopped = threading.Event()

        def slow_connect(sock: socket.socket, address: tuple[str, int]) -> None:
            # Spend most of the exchange before the real write. Buffer limits alone
            # still accept a 64 KiB body on macOS, so the body must exceed that reserve.
            time.sleep(0.65)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
            connect(sock, address)

        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(3)

            def serve() -> None:
                with contextlib.suppress(OSError), listener.accept()[0]:
                    accepted.set()
                    stopped.wait(3)

            worker = threading.Thread(target=serve)
            worker.start()
            url = f"http://127.0.0.1:{listener.getsockname()[1]}/api/notify"
            payload = b"x" * (2 * 1024 * 1024)
            try:
                with (
                    mock.patch.object(socket_type, "connect", slow_connect),
                    mock.patch.object(notify_hook, "TIMEOUT_SEC", budget),
                ):
                    started = time.monotonic()
                    if edge == "hook":
                        self.assertFalse(notify_hook.forward(url, payload))
                    else:
                        self.assertIsNone(mcp_server._request(url, data=payload, timeout=budget))
                    elapsed = time.monotonic() - started
                self.assertTrue(accepted.is_set())
                self.assertLess(elapsed, budget + 0.4)
            finally:
                stopped.set()
                worker.join(4)
                self.assertFalse(worker.is_alive())

    def test_explicit_zero_port_never_connects(self) -> None:
        for port in ("0", "-1", "65536", "invalid"):
            url = f"http://127.0.0.1:{port}/api/notify"
            with (
                self.subTest(port=port),
                mock.patch.object(socket.socket, "connect", side_effect=OSError) as connect,
            ):
                self.assertFalse(notify_hook.forward(url, b"{}"))
                self.assertIsNone(mcp_server._request(url, data=None, timeout=0.1))
                connect.assert_not_called()
                self.assertFalse(notify_hook.is_loopback_url(url))
        for authority, expected in (
            ("127.0.0.1", 80),
            ("127.0.0.1:1", 1),
            ("127.0.0.1:65535", 65535),
        ):
            url = f"http://{authority}/api/notify"
            with self.subTest(authority=authority):
                self.assertTrue(notify_hook.is_loopback_url(url))
                with mock.patch.object(socket.socket, "connect", side_effect=OSError) as connect:
                    self.assertFalse(notify_hook.forward(url, b"{}"))
                    connect.assert_called_once_with(("127.0.0.1", expected))
                    connect.reset_mock()
                    self.assertIsNone(mcp_server._request(url, data=None, timeout=0.1))
                    connect.assert_called_once_with(("127.0.0.1", expected))

    def test_dripping_headers_and_bodies_end_at_the_exchange_deadline(self) -> None:
        for edge in ("hook", "mcp"):
            for phase in ("headers", "body", "chunks"):
                with self.subTest(edge=edge, phase=phase):
                    self.drip(edge, phase)

    def drip(self, edge: str, phase: str) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(2)
            stopped = threading.Event()

            def serve() -> None:
                with contextlib.suppress(OSError), listener.accept()[0] as peer:
                    peer.recv(8192)
                    if phase == "headers":
                        peer.sendall(b"HTTP/1.1 200 OK\r\nX-Slow: ")
                    elif phase == "body":
                        peer.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 80\r\n\r\n")
                    else:
                        peer.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n50\r\n")
                    for _ in range(80):
                        if stopped.wait(0.02):
                            return
                        peer.sendall(b"x")
                    peer.sendall(b"\r\n0\r\n\r\n" if phase == "chunks" else b"\r\n\r\n")

            worker = threading.Thread(target=serve)
            worker.start()
            url = f"http://127.0.0.1:{listener.getsockname()[1]}/api/notify"
            started = time.monotonic()
            try:
                if edge == "hook":
                    with mock.patch.object(notify_hook, "TIMEOUT_SEC", 0.15):
                        self.assertFalse(notify_hook.forward(url, b"{}"))
                else:
                    self.assertIsNone(mcp_server._request(url, data=b"{}", timeout=0.15))
                self.assertLess(time.monotonic() - started, 0.7)
            finally:
                stopped.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())

    def test_only_literal_ipv4_targets_are_admitted(self) -> None:
        for url in ("http://localhost:4553/x", "http://[::1]:4553/x"):
            with self.subTest(url=url), mock.patch.object(socket.socket, "connect") as connect:
                self.assertFalse(notify_hook.is_loopback_url(url))
                self.assertFalse(notify_hook.forward(url, b"{}"))
                self.assertIsNone(mcp_server._request(url, data=None, timeout=0.1))
                connect.assert_not_called()

    def test_mcp_returns_statuses_and_ignores_redirects_and_ambient_proxies(self) -> None:
        for status, extra, body, expected in (
            (200, b"", b"ok", 200),
            (307, b"Location: https://evil.example/collect\r\n", b"", 307),
            (503, b"Retry-After: 1\r\n", b"busy", mcp_server.BUSY),
            (503, b"", b"disabled", 503),
        ):
            with self.subTest(status=status, extra=extra):
                answer, request = self.reply(status, extra, body)
                self.assertEqual((expected, body), answer)
                self.assertTrue(request.startswith(b"POST /api/x?a=1 HTTP/1.1"))

    def reply(
        self, status: int, extra: bytes, body: bytes
    ) -> tuple[tuple[int, bytes] | None, bytes]:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(2)
            requests: list[bytes] = []

            def serve() -> None:
                with listener.accept()[0] as peer:
                    requests.append(peer.recv(8192))
                    peer.sendall(
                        f"HTTP/1.1 {status} Reply\r\nContent-Length: {len(body)}\r\n".encode()
                        + extra
                        + b"\r\n"
                        + body
                    )

            worker = threading.Thread(target=serve)
            worker.start()
            try:
                with mock.patch.dict(
                    os.environ, {"http_proxy": "http://127.0.0.1:1", "no_proxy": ""}
                ):
                    answer = mcp_server._request(
                        f"http://127.0.0.1:{listener.getsockname()[1]}/api/x?a=1",
                        data=b"{}",
                        timeout=1,
                    )
            finally:
                worker.join(3)
                self.assertFalse(worker.is_alive())
            return answer, requests[0]


class McpAdmissionTest(unittest.TestCase):
    def test_a_flood_backpressures_the_reader_at_64_frames(self) -> None:
        server = mcp_server.AskServer(
            stdin=io.BytesIO(b"{}\n" * 100), stdout=io.BytesIO(), ports=()
        )
        reader = threading.Thread(target=server._read)
        reader.start()
        try:
            for _ in range(100):
                if server._frames.qsize() >= 64:
                    break
                time.sleep(0.001)
            self.assertEqual(64, server._frames.qsize())
            self.assertTrue(reader.is_alive())
        finally:
            while reader.is_alive():
                with contextlib.suppress(Exception):
                    server._frames.get(timeout=0.1)
                reader.join(0.01)

    def test_only_eight_calls_can_run_and_a_freed_slot_can_be_reused(self) -> None:
        output = _Stdout()
        server = mcp_server.AskServer(stdin=io.BytesIO(), stdout=output, ports=())
        entered = threading.Semaphore(0)

        def hold(_arguments: object, abort: threading.Event) -> tuple[str, bool]:
            entered.release()
            abort.wait(3)
            return "done", False

        with mock.patch.object(server, "_ask", hold):
            try:
                for request_id in range(8):
                    server._start_call(request_id, _call(request_id, "Proceed?", ["yes", "no"]))
                    self.assertTrue(entered.acquire(timeout=1))
                server._start_call(8, _call(8, "Proceed?", ["yes", "no"]))
                frames = output.frames()
                self.assertEqual(1, len(frames))
                self.assertIn("busy", frames[0]["error"]["message"].lower())
                server._cancel(0)
                server._workers[0].join(1)
                server._start_call(9, _call(9, "Proceed?", ["yes", "no"]))
                self.assertTrue(entered.acquire(timeout=1))
            finally:
                server._abort_all()
                for worker in server._workers:
                    worker.join(4)

    def test_a_duplicate_id_does_not_replace_the_original_cancellation(self) -> None:
        output = _Stdout()
        server = mcp_server.AskServer(stdin=io.BytesIO(), stdout=output, ports=())
        entered = threading.Event()
        cancelled = threading.Event()

        def hold(_arguments: object, abort: threading.Event) -> tuple[str, bool]:
            entered.set()
            if abort.wait(2):
                cancelled.set()
            return "done", False

        with mock.patch.object(server, "_ask", hold):
            try:
                call = _call(1, "Proceed?", ["yes", "no"])
                server._start_call(1, call)
                self.assertTrue(entered.wait(1))
                server._start_call(1, call)
                frames = output.frames()
                self.assertEqual(1, len(frames))
                self.assertIn("duplicate", frames[0]["error"]["message"].lower())
                server._cancel(1)
                self.assertTrue(cancelled.wait(1))
            finally:
                server._abort_all()
                for worker in server._workers:
                    worker.join(3)

    def test_a_worker_start_failure_answers_and_keeps_the_dispatch_loop_alive(self) -> None:
        original = threading.Thread.start

        def start(thread: threading.Thread) -> None:
            if thread.name == "compass-mcp-ask":
                raise RuntimeError("thread resources exhausted")
            original(thread)

        with mock.patch.object(threading.Thread, "start", start), _Harness() as harness:
            harness.push(_call(1, "Proceed?", ["yes", "no"]))
            harness.push({"id": 2, "method": "ping"})
            frames = harness.wait_for_frames(2, timeout=1)
            self.assertEqual(2, len(frames))
            self.assertIn("error", frames[0])
            self.assertEqual(2, frames[1]["id"])
            self.assertFalse(harness.server._aborts)

    def test_an_inflight_id_cannot_be_reused_for_a_different_method(self) -> None:
        output = _Stdout()
        server = mcp_server.AskServer(stdin=io.BytesIO(), stdout=output, ports=())
        entered = threading.Event()

        def hold(_arguments: object, abort: threading.Event) -> tuple[str, bool]:
            entered.set()
            abort.wait(3)
            return "done", False

        with mock.patch.object(server, "_ask", hold):
            try:
                server._start_call(1, _call(1, "Proceed?", ["yes", "no"]))
                self.assertTrue(entered.wait(1))
                server._handle(1, "ping", {"id": 1, "method": "ping"})
                self.assertIn("duplicate", output.frames()[0].get("error", {}).get("message", ""))
            finally:
                server._abort_all()
                for worker in server._workers:
                    worker.join(4)

    def test_oversized_attribution_is_refused_before_secret_scanning(self) -> None:
        with (
            mock.patch.object(mcp_server, "attribution", return_value={"project": "x" * 40_000}),
            mock.patch.object(records, "cut_text", side_effect=AssertionError("scanned")),
        ):
            result = mcp_server._arguments({"question": "Proceed?", "options": ["yes", "no"]})
        self.assertEqual(mcp_server.DECLINE_TOO_LARGE_ATTRIBUTION, result)

    def test_an_oversized_question_or_options_is_refused_before_secret_scanning(self) -> None:
        for arguments in (
            {"question": "x" * 40_000, "options": ["yes", "no"]},
            {"question": "Proceed?", "options": ["x" * 40_000, "no"]},
            {"question": "x" * 17_000, "options": ["y" * 17_000, "no"]},
            {"question": "🐈" * 9_000, "options": ["yes", "no"]},
        ):
            with self.subTest(arguments_size=len(json.dumps(arguments))):
                with mock.patch.object(records, "cut_text", side_effect=AssertionError("scanned")):
                    result = mcp_server._arguments(arguments)
                self.assertIsInstance(result, str)
                self.assertIn("32,768", str(result))


class CorrectionBoundTest(unittest.TestCase):
    def test_separator_heavy_under_limit_input_is_fast(self) -> None:
        for tail in ("key", "sk-ant-" + "1" * 3):
            with self.subTest(tail=tail):
                started = time.monotonic()
                text = correction.neutralised("a-" * 2040 + tail, 240)
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertTrue(text)
                self.assertLessEqual(len(text), 241)

    def test_a_megabyte_of_separators_is_processed_within_a_small_budget(self) -> None:
        script = (
            "from compass_runtime.correction import neutralised; neutralised('a-_' * 349526, 240)"
        )
        try:
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=pathlib.Path(mcp_server.__file__).parent,
                capture_output=True,
                timeout=4,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("neutralising one MiB exceeded four seconds")
        self.assertEqual(0, result.returncode, result.stderr.decode())

    def test_bounding_keeps_redaction_and_does_not_reveal_a_key_across_the_cut(self) -> None:
        secret = "ghp_" + "Z" * 36
        raw = "Useful detail " + secret + " " * 4030 + secret + " tail"
        kept = correction.neutralised(raw, 240)
        self.assertNotIn("Z" * 4, kept)
        self.assertEqual("", kept)
        self.assertIn("REDACTED", correction.neutralised("Useful detail " + secret, 240))
