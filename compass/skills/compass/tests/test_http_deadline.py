"""Whole-exchange deadlines, including a listener that keeps making slow progress."""

from __future__ import annotations

import contextlib
import socket
import threading
import time
import unittest

from compass_runtime import lifecycle, terminal_client

# Measures wall-clock bounds while a peer drips headers and response bodies.
REAL_TIME_TESTS = True


class DeadlineTest(unittest.TestCase):
    def test_a_person_is_not_kept_waiting_by_dripping_headers_or_bodies(self) -> None:
        replies = (
            b"HTTP/1.1 200 OK\r\nX-Slow: " + b"x" * 80 + b"\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length: 80\r\n\r\n" + b"x" * 80,
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n50\r\n"
            + b"x" * 80
            + b"\r\n0\r\n\r\n",
        )
        for operation in ("probe", "request", "lifecycle"):
            for reply in replies:
                with self.subTest(operation=operation, reply=reply[:50]):
                    self.drip(operation, reply)

    def drip(self, operation: str, reply: bytes) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            listener.settimeout(2)
            port = listener.getsockname()[1]
            stopped = threading.Event()

            def serve() -> None:
                with contextlib.suppress(OSError), listener.accept()[0] as peer:
                    peer.recv(8192)
                    # Only the status/header arm drips from byte zero.
                    at = 0 if b"X-Slow" in reply else reply.index(b"\r\n\r\n") + 4
                    peer.sendall(reply[:at])
                    for byte in reply[at:]:
                        if stopped.wait(0.02):
                            break
                        peer.sendall(bytes([byte]))

            worker = threading.Thread(target=serve)
            worker.start()
            began = time.monotonic()
            try:
                if operation == "probe":
                    self.assertIsNone(terminal_client.probe(port, timeout=0.15))
                elif operation == "lifecycle":
                    self.assertEqual(("closed", None), lifecycle.probe_port(port, timeout=0.15))
                else:
                    with self.assertRaises(terminal_client.DashboardUnreachable):
                        terminal_client.request("GET", port, "/api/x", timeout=0.15)
                self.assertLess(time.monotonic() - began, 0.7)
            finally:
                stopped.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())
