"""All dispatch routes meet the same admission classes over the shared socket harness."""

from __future__ import annotations

import ast
import dataclasses
import http.client
import json
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import events, http_api, interaction_prototype, observation

from .support import RuntimeTestCase, build_app, make_server, poll_fast, saturated_server
from .test_interaction_prototype import FakeTmuxAdapter

GET = {
    "/",
    "/assets/xterm.js",
    "/assets/xterm.css",
    "/api/data",
    "/api/session",
    "/api/live-monitor",
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
    "/api/usage/claude",
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
    ("POST", "/api/shutdown"): 200,
    ("POST", "/api/tripwire"): 400,
    ("POST", "/api/usage"): 200,
    # Loopback only: the status line that forwards Claude's quota always runs on this machine.
    ("POST", "/api/usage/claude"): 403,
    **{("POST", f"/api/events/{harness}"): 403 for harness in events.IDENTITY_NORMALIZERS},
}
VALID_DISCARD = {
    "harness": "claude",
    "sid": "11111111-2222-3333-4444-555555555555",
    "job": "a" * 32,
    "press": True,
    "observer_model": 1,
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
        if isinstance(item, ast.Compare):
            suffixes.update(
                value.value
                for value in ast.walk(item)
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
                    for value in ast.walk(node)
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
    def test_membership_and_reversed_route_additions_require_matrix_rows(self) -> None:
        source = Path(http_api.__file__).read_text()
        for condition in (
            'url.path in ("/api/new-a", "/api/new-b")',
            'url.path in {"/api/new-a", "/api/new-b"}',
            '"/api/new-a" == url.path',
        ):
            with self.subTest(condition=condition):
                mutated = source.replace(
                    'if url.path.startswith("/api/ask/"):',
                    f"if {condition}:\n            self._health()\n            return True\n"
                    '        if url.path.startswith("/api/ask/"):',
                    1,
                )
                additions = dispatched_routes(mutated) - set(ROWS)
                expected = {("GET", "/api/new-a")}
                if " in " in condition:
                    expected.add(("GET", "/api/new-b"))
                self.assertEqual(expected, additions)
        for condition in (
            'route in ("new-a", "new-b")',
            'route in {"new-a", "new-b"}',
            '"new-a" == route',
        ):
            with self.subTest(condition=condition):
                mutated = source.replace('route == "origin"', condition, 1)
                additions = dispatched_routes(mutated) - set(ROWS)
                self.assertIn(("GET", "/api/interaction/new-a"), additions)
                if " in " in condition:
                    self.assertIn(("GET", "/api/interaction/new-b"), additions)

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

    @staticmethod
    def tunnel_headers(port: int, kind: str) -> list[tuple[str, str]]:
        local_port = 1 if port == 65535 else port + 1
        origin = f"http://127.0.0.1:{local_port}"
        extra = {
            "tunnel-proxy": [("Forwarded", "for=192.0.2.10")],
            "tunnel-duplicate": [("Origin", origin)],
        }.get(kind, [])
        return [("Host", f"127.0.0.1:{local_port}"), ("Origin", origin), *extra]

    def request(self, method: str, path: str, kind: str, payload: Any = None) -> int:
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
                ("Sec-Fetch-Mode", "no-cors" if method == "GET" else "cors"),
                ("Sec-Fetch-Dest", "empty"),
            ],
            "cross-port-cors": [
                ("Sec-Fetch-Site", "same-site"),
                ("Sec-Fetch-Mode", "cors"),
                ("Sec-Fetch-Dest", "empty"),
            ],
            "duplicate": [("Host", f"127.0.0.1:{port}")],
            "proxy": [("Forwarded", "for=192.0.2.10")],
            "transfer": [("Transfer-Encoding", "chunked")],
            "malformed": [("Bad ", "value")],
            "stale-capability": [("X-Compass-Capability", "old-process-capability")],
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
        if kind == "cross-port-cors" or (kind == "cross-port" and method == "POST"):
            # CORS requests carry Origin; no-cors script/image GETs need not.
            headers += [("Origin", f"http://127.0.0.1:{1 if port == 65535 else port + 1}")]
        if kind.startswith("tunnel"):
            headers = self.tunnel_headers(port, kind)
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

        body = json.dumps(VALID_DISCARD).encode() if path == "/api/reading-long-discard" else b"[]"
        if payload is not None:
            body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        # Peer injection changes only the address the real socket handler sees; binding stays
        # loopback; the request still crosses the real parser and dispatch gates.
        try:
            with (
                mock.patch.object(http_api._RequestHandler, "__init__", handler),
                mock.patch.object(self.httpd, "shutdown"),
            ):
                conn.putrequest(method, path, skip_host=True)
                for name, value in headers:
                    conn.putheader(name, value)
                conn.putheader("Content-Length", str(len(body)) if method == "POST" else "0")
                conn.endheaders(body if method == "POST" else None)
                response = conn.getresponse()
                if path != "/api/stream":
                    self.last_body = response.read()
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

    def test_same_site_cross_port_no_cors_get_and_cors_post(self) -> None:
        self.check_class("cross-port")

    def test_cross_port_cors_get_rejects_origin(self) -> None:
        for path in sorted(GET):
            with self.subTest(path=path):
                self.assertEqual(403, self.request("GET", path, "cross-port-cors"))

    def test_unadmitted_reading_posts_reveal_neither_body_validity_nor_availability(self) -> None:
        paths = (
            "/api/reading",
            "/api/reading/cancel",
            "/api/reading-long-discard",
            "/api/goal/find",
        )
        config = self.httpd.application.config
        for available in (True, False):
            self.httpd.application.config = dataclasses.replace(
                config, annotations_enabled=available, annotation_body_cap_bytes=512
            )
            with mock.patch.object(annotation_store, "any_reading_enabled", return_value=available):
                for path in paths:
                    for kind in ("lan", "proxy", "navigation"):
                        for body in (
                            b"{",
                            b"[]",
                            b"{}",
                            b"x" * 513,
                            VALID_DISCARD,
                            {"mode": "long"},
                            {"plan_binding": "bad"},
                            {"typed_action": "summary"},
                        ):
                            with self.subTest(path=path, kind=kind, body=body, available=available):
                                self.assertEqual(403, self.request("POST", path, kind, body))

    def test_an_observation_without_origin_or_fetch_metadata_is_refused(self) -> None:
        self.assertEqual(403, self.request("GET", "/api/observe", "local"))

    def test_a_different_port_tunnel_explains_why_every_action_is_refused(self) -> None:
        sentence = "For an ssh -L tunnel, the local port must match the Compass server's port."
        for path in sorted(POST):
            with self.subTest(path=path):
                self.assertEqual(403, self.request("POST", path, "tunnel"))
                self.assertIn(sentence.encode(), self.last_body)
                self.assertEqual(
                    {"ok": False, "reason": "tunnel-port-mismatch", "message": sentence},
                    json.loads(self.last_body),
                )
        for kind in ("tunnel-proxy", "tunnel-duplicate", "cross-port", "lan"):
            with self.subTest(kind=kind):
                # A different local service or a forwarding proxy earns no tunnel diagnosis.
                self.assertEqual(403, self.request("POST", "/api/reading", kind))
                self.assertNotIn(b"tunnel-port-mismatch", self.last_body)

    def test_a_refused_board_action_names_admission_instead_of_a_restart(self) -> None:
        for kind in ("duplicate", "cross-port", "lan", "proxy"):
            with self.subTest(kind=kind):
                self.assertEqual(403, self.request("POST", "/api/focus", kind))
                self.assertIn(b"admission-refused", self.last_body)
                body = json.loads(self.last_body)
                self.assertEqual("admission-refused", body["reason"])
                self.assertIn("direct loopback", body["message"])

    def test_an_old_focus_capability_asks_the_reader_to_reload(self) -> None:
        self.assertEqual(403, self.request("POST", "/api/focus", "stale-capability"))
        self.assertIn(b"stale-capability", self.last_body)
        body = json.loads(self.last_body)
        self.assertEqual("stale-capability", body["reason"])
        self.assertIn("Reload", body["message"])

    def test_valid_discard_rejects_lan_and_forwarding(self) -> None:
        self.assertTrue(http_api._RequestHandler._valid_long_discard(VALID_DISCARD))
        with mock.patch.object(
            http_api._RequestHandler, "_discard_long_marker", return_value=(200, True, "")
        ) as discard:
            # Positive control proves the same input can reach the eventual mutation.
            self.assertEqual(200, self.request("POST", "/api/reading-long-discard", "local"))
            discard.assert_called_once_with(VALID_DISCARD)
            discard.reset_mock()
            for kind in ("lan", "proxy"):
                with self.subTest(kind=kind):
                    self.assertEqual(403, self.request("POST", "/api/reading-long-discard", kind))
                    discard.assert_not_called()

    # A duplicate admission header is refused by the admission gate (403, as SECURITY.md says),
    # not by the header parser; only a defective header block is a 400.
    def test_group_write_uses_the_existing_annotation_admission_matrix(self) -> None:
        body = {"harness": "claude", "sid": "aaaaaaaa", "group": "Local team"}
        with mock.patch.object(annotation_store, "annotate", return_value="stored") as save:
            for kind in ("local", "lan", "navigation", "cross-port", "duplicate"):
                with self.subTest(kind=kind):
                    expected = 200 if kind in {"local", "lan"} else 403
                    self.assertEqual(expected, self.request("POST", "/api/annotate", kind, body))
                    if expected == 200:
                        self.assertEqual("Local team", save.call_args.kwargs["group"])
                    else:
                        save.assert_not_called()
                    save.reset_mock()

    def test_a_group_write_cannot_accompany_an_intent_control_action(self) -> None:
        for control in (
            {"clear": True},
            {"adopt": "latest-prompt"},
            {"add_direction": "f1"},
            {"not_accurate": True, "read_at": 100.0},
            {"settle_through": 100.0},
        ):
            with (
                self.subTest(control=control),
                mock.patch.object(annotation_store, "annotate") as save,
            ):
                self.assertFalse(http_api._annotation_body_refused(control))
                body = {"harness": "claude", "sid": "aaaaaaaa", "group": "Local team", **control}
                self.assertEqual(400, self.request("POST", "/api/annotate", "local", body))
                save.assert_not_called()

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
        for method, path in protected:
            with self.subTest(method=method, path=path):
                self.assertEqual(403, self.request(method, path, "proxy"))

    def test_every_loopback_post_rejects_forwarding(self) -> None:
        remote_posts = {
            path
            for (method, path), status in REMOTE_RESULTS.items()
            if method == "POST" and status != 403
        }
        for path in sorted(POST - remote_posts):
            with self.subTest(path=path):
                self.assertEqual(403, self.request("POST", path, "proxy"))

    def test_transfer_encoding_is_refused_before_every_post_route(self) -> None:
        # Each refusal drains the unframed body for REJECT_DRAIN_SECONDS before closing, and at
        # the shipped 0.25 s the forty routes spent 10 s waiting on a drain this test does not
        # measure. The body is already in the loopback buffer, so a shorter drain still reads it.
        with mock.patch.object(http_api._RequestHandler, "REJECT_DRAIN_SECONDS", 0.02):
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
