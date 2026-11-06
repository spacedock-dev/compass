from __future__ import annotations

import contextlib
import http.client
import io
import os
import socket
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

from compass_runtime import cli, lifecycle
from compass_runtime.web import page as frontend_page

from .support import make_server, serve_until_closed

PAGE = b"<html>the page</html>"


class PageRoutingTest(unittest.TestCase):
    @staticmethod
    def _get(port: int, path: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_supported_root_queries_serve_the_one_canonical_page(self) -> None:
        httpd = make_server(page_bytes=PAGE)
        thread = serve_until_closed(httpd)
        try:
            for path in (
                "/",
                "/?all=1",
                "/?nextish=true",
            ):
                with self.subTest(path=path):
                    self.assertEqual((200, PAGE), self._get(httpd.server_port, path))
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    def test_retired_next_query_is_not_a_page_alias(self) -> None:
        httpd = make_server(page_bytes=PAGE)
        thread = serve_until_closed(httpd)
        try:
            for path in ("/?next=true", "/?next=false", "/?next=", "/?all=1&next=true"):
                with self.subTest(path=path):
                    status, body = self._get(httpd.server_port, path)
                    self.assertEqual(404, status)
                    self.assertNotEqual(PAGE, body)
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    def test_shared_server_factory_serves_the_installed_page(self) -> None:
        httpd = make_server()
        thread = serve_until_closed(httpd)
        try:
            expected = (200, frontend_page.load_frontend_page())
            self.assertEqual(expected, self._get(httpd.server_port, "/"))
        finally:
            httpd.shutdown()
            thread.join(timeout=5)


class PageCliBoundaryTest(unittest.TestCase):
    @staticmethod
    def _run_with_loader(page_loader: object) -> tuple[int, str, list[bytes]]:
        observed: list[bytes] = []

        def close_server(_config: object, server: Any, _port: int, **_kwargs: object) -> None:
            observed.append(server.page_bytes)
            server.server_close()

        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
            mock.patch.object(sys, "argv", ["server.py", "--port", str(port), "--no-events"]),
            mock.patch.object(frontend_page, "load_frontend_page", side_effect=page_loader),
            mock.patch.object(lifecycle, "serve", side_effect=close_server),
            contextlib.redirect_stderr(io.StringIO()) as stderr,
        ):
            code = cli.main()
        return code, stderr.getvalue(), observed

    def test_the_loaded_page_is_the_page_the_server_holds(self) -> None:
        code, stderr, observed = self._run_with_loader(lambda: PAGE)

        self.assertEqual(0, code)
        self.assertEqual([PAGE], observed)
        self.assertEqual("", stderr)

    def test_a_broken_page_prevents_binding(self) -> None:
        code, stderr, observed = self._run_with_loader(RuntimeError("broken bundle"))

        self.assertEqual(1, code)
        self.assertEqual([], observed)
        self.assertIn("cannot load frontend assets", stderr)
        self.assertIn("broken bundle", stderr)


if __name__ == "__main__":
    unittest.main()
