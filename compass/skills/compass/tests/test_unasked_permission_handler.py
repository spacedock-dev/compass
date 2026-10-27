"""The real reading handler, exercised without requiring a listening socket."""

from __future__ import annotations

import contextlib
import io
import json
from email.message import Message
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import http_api, reading_policy

from . import test_unasked_permission_api as socket_tests


class UnaskedGrantHandlerTest(socket_tests.UnaskedGrantHTTPTest):
    @contextlib.contextmanager
    def _serving(self, application: Any) -> Any:
        yield application

    def _post(self, port: Any, payload: Any, **kwargs: Any) -> tuple[int, bytes]:
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = SimpleNamespace(
            application=port, server_port=49100, bound_host="127.0.0.1"
        )
        handler.client_address = (kwargs.get("peer", "127.0.0.1"), 12345)
        raw = json.dumps(payload).encode()
        handler.headers = Message()
        for name, value in {
            "Host": "127.0.0.1:49100",
            "Content-Length": str(len(raw)),
            **kwargs.get("headers", {}),
        }.items():
            handler.headers[name] = value
        handler.rfile = io.BytesIO(raw)
        handler._body_consumed = 0
        sent: list[tuple[int, bytes]] = []
        handler._send = mock.Mock(
            side_effect=lambda body, _ctype, code=200: sent.append((code, body))
        )
        handler._reject = mock.Mock(side_effect=lambda code: sent.append((code, b"")))
        handler._reading()
        self.assertEqual(1, len(sent))
        return sent[0]

    def test_a_nonloopback_peer_cannot_grant_even_with_a_loopback_host(self) -> None:
        config, state = self._runtime(unasked_enabled=True)
        reading_policy.store_path(config).unlink()
        app = self._app(config, state, "codex")
        status, _body = self._post(app, self._body(), peer="192.0.2.1")
        self.assertEqual(403, status)
        self.assertFalse(reading_policy.status(config, now=100.0)["words"]["codex"])
