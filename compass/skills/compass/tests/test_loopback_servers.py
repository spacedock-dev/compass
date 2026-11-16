"""Test servers bind without a reverse DNS lookup.

`http.server.HTTPServer.server_bind` calls `socket.getfqdn()` on the bind
address. On the hosted macOS runner that lookup has no answer for 127.0.0.1 and
waits it out, so every test that stood up a stock server paid a fixed stall: 35 s
per test in the `--slowest` report of the macOS dashboard leg, against well
under a second of work. `support.LoopbackHTTPServer` binds the way
`http_api.CompassHTTPServer` does, and this module holds every test to it.
"""

from __future__ import annotations

import ast
import http.server
import socket
import socketserver
import unittest
from pathlib import Path
from unittest import mock

from . import support

TESTS = Path(__file__).resolve().parent
STOCK = frozenset({"HTTPServer", "ThreadingHTTPServer"})


def _stock_server_uses(source: str) -> list[int]:
    """Lines that construct or subclass a stock `http.server` server."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            targets, line = [node.func], node.lineno
        elif isinstance(node, ast.ClassDef):
            targets, line = list(node.bases), node.lineno
        else:
            continue
        for target in targets:
            name = (
                target.attr
                if isinstance(target, ast.Attribute)
                else target.id
                if isinstance(target, ast.Name)
                else None
            )
            if name in STOCK:
                lines.append(line)
    return sorted(lines)


class ATestServerBindsWithoutAReverseLookupTest(unittest.TestCase):
    def test_a_loopback_server_never_asks_the_resolver_for_its_own_name(self) -> None:
        for server_class in (support.LoopbackHTTPServer, support.ThreadingLoopbackHTTPServer):
            with (
                self.subTest(server_class=server_class.__name__),
                mock.patch.object(
                    socket, "getfqdn", side_effect=AssertionError("bind reverse-resolved")
                ) as getfqdn,
                server_class(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler) as httpd,
            ):
                self.assertEqual(0, getfqdn.call_count)
                self.assertEqual("127.0.0.1", httpd.server_name)
                self.assertNotEqual(0, httpd.server_port)
                self.assertEqual(httpd.socket.getsockname()[1], httpd.server_port)

    def test_the_threading_server_keeps_the_stock_threading_behaviour(self) -> None:
        self.assertTrue(support.ThreadingLoopbackHTTPServer.daemon_threads)
        for base in (socketserver.ThreadingMixIn, http.server.HTTPServer):
            self.assertTrue(issubclass(support.ThreadingLoopbackHTTPServer, base))

    def test_no_test_module_stands_up_a_stock_http_server(self) -> None:
        offenders = [
            f"{path.name}:{line}"
            for path in sorted(TESTS.glob("*.py"))
            if path.name != "support.py"
            for line in _stock_server_uses(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(
            [],
            offenders,
            "use support.LoopbackHTTPServer or support.ThreadingLoopbackHTTPServer: a stock "
            "http.server server reverse-resolves its bind address and stalls on the macOS runner",
        )

    def test_the_scan_finds_a_stock_server_however_it_is_named(self) -> None:
        source = (
            "import http.server\n"
            "from http.server import HTTPServer, ThreadingHTTPServer\n"
            "a = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)\n"
            "b = HTTPServer(('127.0.0.1', 0), H)\n"
            "class C(ThreadingHTTPServer): pass\n"
            "d = support.ThreadingLoopbackHTTPServer(('127.0.0.1', 0), H)\n"
        )
        self.assertEqual([3, 4, 5], _stock_server_uses(source))


if __name__ == "__main__":
    unittest.main()
