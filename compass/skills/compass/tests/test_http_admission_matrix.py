"""All dispatch routes meet the same admission classes over the shared socket harness."""

from __future__ import annotations

import ast
import dataclasses
import http.client
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import events, http_api, interaction_prototype, observation

from .support import RuntimeTestCase, build_app, make_server, poll_fast, saturated_server
from .test_interaction_prototype import FakeTmuxAdapter

REAL_TIME_TESTS = True
GET = {
    "/",
    "/assets/xterm.js",
    "/assets/xterm.css",
    "/api/data",
    "/api/session",
    "/api/summary",
    "/api/sessions",
    "/api/observe",
    "/api/project-context",
    "/api/session-record",
    "/api/reading-long-plan",
    "/api/reading-long-history",
    "/api/overlays",
    "/api/cleared",
    "/api/annotations",
    "/api/settings",
    "/api/stream",
    "/api/health",
    "/api/ask/MATRIX",
    "/api/interaction/origin",
    "/api/interaction/state",
    "/api/interaction/view",
    "/api/interaction/stream",
}
POST = {
    "/api/shutdown",
    "/api/usage",
    "/api/dismiss",
    "/api/tripwire",
    "/api/annotate",
    "/api/direction",
    "/api/correction",
    "/api/correction/copied",
    "/api/reading",
    "/api/reading/cancel",
    "/api/reading-long-discard",
    "/api/goal/find",
    "/api/live-monitor",
    "/api/summary",
    "/api/summary/cancel",
    "/api/summary/delete",
    "/api/focus",
    "/api/ask",
    "/api/ask/withdraw",
    "/api/answer",
    "/api/notify",
    "/api/lane",
    "/api/settings",
    *{
        f"/api/interaction/{operation}"
        for operation in (
            "register",
            "renew",
            "probe-unregistered",
            "probe-spoofed",
            "control",
            "input",
            "expire",
            "disconnect",
            "reconnect",
            "reset",
        )
    },
    *{
        f"/api/events/{harness}"
        for harness in ("claude", "codex", "antigravity", "gemini", "opencode", "pi", "droid")
    },
}
ROWS = [
    (method, path) for method, paths in (("GET", GET), ("POST", POST)) for path in sorted(paths)
]
# Only these document reads deliberately inherit do_GET's navigation relaxation.
NAVIGATION_READS = {"/", "/api/data", "/api/health"}
# The operator explicitly exposes these board reads with --host/--allow-host.
REMOTE_READS = {
    "/",
    "/api/data",
    "/api/health",
    "/api/overlays",
    "/api/cleared",
    "/api/annotations",
    "/api/settings",
    "/api/project-context",
    "/api/session-record",
    "/api/stream",
}

REMOTE_RESULTS = {
    ("GET", "/api/ask/MATRIX"): 404,  # No question with this id, not an admission failure.
    ("POST", "/api/annotate"): 400,
    ("POST", "/api/answer"): 200,
    ("POST", "/api/ask"): 400,
    ("POST", "/api/ask/withdraw"): 200,
    ("POST", "/api/dismiss"): 200,
    ("POST", "/api/focus"): 403,  # Capability remains required on a remote board.
    ("POST", "/api/lane"): 400,
    ("POST", "/api/notify"): 200,
    ("POST", "/api/reading-long-discard"): 400,
    ("POST", "/api/shutdown"): 200,
    ("POST", "/api/tripwire"): 400,
    ("POST", "/api/usage"): 200,
    **{("POST", f"/api/events/{harness}"): 403 for harness in events.IDENTITY_NORMALIZERS},
}


def interaction_suffixes(operation: ast.FunctionDef) -> set[str]:
    suffixes: set[str] = set()
    for item in ast.walk(operation):
        if isinstance(item, ast.Dict):
            suffixes.update(
                key.value
                for key in item.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
        if (
            isinstance(item, ast.Compare)
            and isinstance(item.left, ast.Name)
            and item.left.id == "route"
        ):
            suffixes.update(
                value.value
                for value in item.comparators
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
    return suffixes


def dispatched_routes(source: str) -> set[tuple[str, str]]:
    tree = ast.parse(source)
    methods = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    routes: set[tuple[str, str]] = set()
    for name, verb in (("do_GET", "GET"), ("_get_api", "GET"), ("do_POST", "POST")):
        for node in ast.walk(methods[name]):
            if isinstance(node, ast.Dict):
                routes.update(
                    (verb, key.value)
                    for key in node.keys
                    if isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key.value.startswith("/")
                )
            if isinstance(node, ast.Compare):
                routes.update(
                    (verb, value.value)
                    for value in node.comparators
                    if isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                    and value.value.startswith("/")
                )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "startswith"
            ):
                prefix = ast.literal_eval(node.args[0])
                if prefix == "/assets/":
                    asset = methods["_interaction_asset"]
                    routes.update(
                        (verb, key.value)
                        for item in ast.walk(asset)
                        if isinstance(item, ast.Dict)
                        for key in item.keys
                        if isinstance(key, ast.Constant) and isinstance(key.value, str)
                    )
                elif prefix == "/api/events/":
                    routes.update(
                        (verb, prefix + harness) for harness in events.IDENTITY_NORMALIZERS
                    )
                elif prefix == "/api/interaction/":
                    operation = methods[
                        "_interaction_get" if verb == "GET" else "_interaction_post"
                    ]
                    routes.update(
                        (verb, prefix + suffix) for suffix in interaction_suffixes(operation)
                    )
                else:
                    routes.add((verb, prefix + "MATRIX"))
    return routes


class AdmissionInventoryTest(unittest.TestCase):
    def test_every_dispatch_arm_has_a_matrix_row(self) -> None:
        self.assertEqual(set(ROWS), dispatched_routes(Path(http_api.__file__).read_text()))

    def test_a_new_route_or_prefix_operation_requires_a_row(self) -> None:
        source = Path(http_api.__file__).read_text()
        for old, new, route in (
            ('"/api/data": self._data', '"/api/forgotten": self._data', ("GET", "/api/forgotten")),
            ('startswith("/api/ask/")', 'startswith("/api/new/")', ("GET", "/api/new/MATRIX")),
            (
                '"register": self._interaction_register',
                '"forgotten": self._interaction_register',
                ("POST", "/api/interaction/forgotten"),
            ),
            ('route == "origin"', 'route == "forgotten"', ("GET", "/api/interaction/forgotten")),
        ):
            with self.subTest(route=route):
                self.assertIn(route, dispatched_routes(source.replace(old, new)))


class HttpAdmissionMatrixTest(RuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        app = build_app()
        app.config = dataclasses.replace(app.config, allowed_hosts=("board.example",))
        self.coordinator = observation.Observation(app)
        self.httpd = make_server(application=app, observation=self.coordinator)
        self.httpd.bound_host = "0.0.0.0"
        self.httpd.interaction_prototype = interaction_prototype.InteractionPrototype(
            FakeTmuxAdapter()
        )
        self.thread = threading.Thread(target=poll_fast(self.httpd), daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self) -> None:
        self.httpd.application.state.streams.close_all()
        self.coordinator.stop()
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(2)

    def request(self, method: str, path: str, kind: str) -> int:
        port = self.httpd.server_port
        headers = [("Host", f"127.0.0.1:{port}")]
        extra = {
            "navigation": [
                ("Sec-Fetch-Site", "cross-site"),
                ("Sec-Fetch-Mode", "navigate"),
                ("Sec-Fetch-Dest", "document"),
            ],
            "cross-port": [
                ("Sec-Fetch-Site", "same-site"),
                ("Sec-Fetch-Mode", "cors"),
                ("Sec-Fetch-Dest", "empty"),
            ],
            "duplicate": [("Host", f"127.0.0.1:{port}")],
            "proxy": [("Forwarded", "for=192.0.2.10")],
            "transfer": [("Transfer-Encoding", "chunked")],
            "malformed": [("Bad ", "value")],
        }
        headers += extra.get(kind, [])
        if kind.startswith("duplicate-"):
            name = kind.removeprefix("duplicate-")
            value = {
                "Origin": f"http://127.0.0.1:{port}",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            }[name]
            headers += [(name, value), (name, value)]
        if kind == "cross-port" and method == "POST":
            # A form/fetch POST carries Origin; script/image subresources need not.
            headers += [("Origin", f"http://127.0.0.1:{1 if port == 65535 else port + 1}")]
        if kind == "lan":
            headers = [("Host", "board.example"), ("Origin", "https://board.example")]
        if path == "/api/interaction/stream":
            headers += [
                ("Upgrade", "websocket"),
                ("Connection", "Upgrade"),
                ("Sec-WebSocket-Key", "dGhlIHNhbXBsZSBub25jZQ=="),
                ("Sec-WebSocket-Version", "13"),
            ]
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        original = http_api._RequestHandler.__init__

        def handler(instance: Any, request: Any, address: Any, server: Any) -> None:
            original(
                instance, request, ("192.0.2.10", address[1]) if kind == "lan" else address, server
            )

        # Peer injection changes only the address the real socket handler sees; binding stays
        # loopback. Empty payloads and a blocked shutdown prevent authorized board mutations.
        try:
            with (
                mock.patch.object(http_api._RequestHandler, "__init__", handler),
                mock.patch.object(self.httpd, "shutdown"),
            ):
                conn.putrequest(method, path, skip_host=True)
                for name, value in headers:
                    conn.putheader(name, value)
                conn.putheader("Content-Length", "2" if method == "POST" else "0")
                conn.endheaders(b"[]" if method == "POST" else None)
                response = conn.getresponse()
                if path != "/api/stream":
                    response.read()
                return response.status
        finally:
            conn.close()

    def check_class(self, kind: str) -> None:
        differences = []
        for method, path in ROWS:
            expected = 403
            if kind == "navigation" and method == "GET" and path in NAVIGATION_READS:
                expected = 200
            if kind in {"lan", "cross-port"} and method == "GET" and path in REMOTE_READS:
                expected = {
                    "/api/overlays": 200,
                    "/api/project-context": 400,
                    "/api/session-record": 400,
                }.get(path, 200)
            if kind == "cross-port" and (method, path) == ("GET", "/api/ask/MATRIX"):
                expected = 404
            if kind == "lan":
                # SECURITY.md explicitly accepts remote board writes under an operator's
                # nondefault bind. Empty invalid bodies prove admission without changing data.
                expected = REMOTE_RESULTS.get((method, path), expected)
            status = self.request(method, path, kind)
            if status != expected:
                differences.append(f"{kind} {method} {path}: expected {expected}, got {status}")
        self.assertEqual([], differences, "\n".join(differences))

    def test_cross_site_top_level_navigation(self) -> None:
        self.check_class("navigation")

    def test_same_site_cross_port_subresource(self) -> None:
        self.check_class("cross-port")

    # A duplicate admission header is refused by the admission gate (403, as SECURITY.md says),
    # not by the header parser; only a defective header block is a 400.
    def test_duplicate_host_is_refused_on_every_route(self) -> None:
        self.check_class("duplicate")

    def test_lan_peer_under_explicit_host_allowlist(self) -> None:
        self.check_class("lan")

    def test_other_duplicate_admission_headers_also_refuse_every_route(self) -> None:
        for header in ("Origin", "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest"):
            for method, path in ROWS:
                with self.subTest(header=header, method=method, path=path):
                    self.assertEqual(403, self.request(method, path, "duplicate-" + header))

    def test_malformed_header_blocks_are_bad_requests_on_every_route(self) -> None:
        for method, path in ROWS:
            with self.subTest(method=method, path=path):
                self.assertEqual(400, self.request(method, path, "malformed"))

    def test_forwarding_headers_cannot_reach_loopback_only_routes(self) -> None:
        protected = [("GET", path) for path in GET - REMOTE_READS - {"/api/ask/MATRIX"}]
        protected += [("POST", path) for path in POST if path.startswith("/api/interaction/")]
        protected += [
            ("POST", "/api/direction"),
            ("POST", "/api/correction"),
            ("POST", "/api/settings"),
        ]
        for method, path in protected:
            with self.subTest(method=method, path=path):
                self.assertEqual(403, self.request(method, path, "proxy"))

    def test_transfer_encoding_is_refused_before_every_post_route(self) -> None:
        for path in sorted(POST):
            with self.subTest(path=path):
                self.assertEqual(501, self.request("POST", path, "transfer"))

    def test_connection_cap_is_64_and_overflow_carries_retry_after(self) -> None:
        self.assertEqual(64, http_api.CompassHTTPServer.CONNECTION_LIMIT)
        with saturated_server() as (httpd, _release):
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            try:
                conn.request("GET", "/api/health")
                response = conn.getresponse()
                self.assertEqual(503, response.status)
                self.assertEqual("1", response.getheader("Retry-After"))
                self.assertEqual("close", response.getheader("Connection"))
            finally:
                conn.close()
