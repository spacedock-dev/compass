from __future__ import annotations

import contextlib
import dataclasses
import email.message
import errno
import http.client
import http.server
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar, cast
from unittest import mock
from urllib.parse import urlparse

from compass_runtime import (
    aggregate,
    cli,
    departures,
    http_api,
    lifecycle,
    notifications,
    reading_policy,
    session_source,
    session_summary,
    summary_jobs,
    summary_store,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import asks as runtime_asks
from compass_runtime import ci_read as runtime_ci_read
from compass_runtime import git_status as runtime_git_status
from compass_runtime import io as runtime_io
from compass_runtime import observation as observation_module
from compass_runtime import observer as runtime_observer
from compass_runtime import project_context as runtime_project_context
from compass_runtime import reading as runtime_reading
from compass_runtime import reading_jobs as runtime_reading_jobs
from compass_runtime import reading_route as runtime_reading_route
from compass_runtime import sessions as runtime_sessions
from compass_runtime import supervise as runtime_supervise
from compass_runtime.config import COMPASS_HOME_ENV
from compass_runtime.web import page as frontend_page

from . import fixtures
from .support import (
    PAGE_BYTES,
    SERVER_STARTED,
    STORE_KEYS,
    RuntimeTestCase,
    build_app,
    collect,
    collect_json,
    make_runtime,
    make_server,
    poll_fast,
    serve_until_closed,
    short_circuit_native_notifications,
    state_of,
    store_patch,
    without_focus_meta,
)
from .test_ci_read import GOAL_URL, StubGh
from .test_claude_checks import Transcript
from .test_session_summary import Replies
from .test_summary_jobs import wait_job


def _application(os_name: str) -> Any:
    """An application whose config claims `os_name`, whatever the host is.

    The port-sharing tests below turn on a config that *disagrees* with the
    host, which is the only way to tell a config read from an ambient one.
    """
    config, state = make_runtime(os_name=os_name)
    return aggregate.Application(
        config,
        state,
        (),
        native_notifier=lambda _platform: "",
        popup_notifier=lambda _title, _message: None,
        diagnostic_sink=lambda _line: None,
    )


class CompassServerTest(RuntimeTestCase):
    def test_notify_endpoint_accepts_valid_non_object_and_deep_json(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        bodies = [
            json.dumps({"session_id": "12345678", "message": "before\u0000after"}).encode(),
            b"[1,2,3]",
            b"null",
            b'"text"',
            (b"[" * 1200) + b"0" + (b"]" * 1200),
        ]
        try:
            with mock.patch.object(notifications, "notify_mac") as notify:
                for body in bodies:
                    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
                    conn.request(
                        "POST",
                        "/api/notify",
                        body=body,
                        headers={"Content-Type": "application/json"},
                    )
                    response = conn.getresponse()
                    self.assertEqual(200, response.status)
                    self.assertEqual(b'{"ok":true}', response.read())
                    conn.close()
            self.assertNotIn("\x00", notify.call_args.args[1])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_cross_site_fetch_metadata_is_rejected(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            conn.request("GET", "/api/data", headers={"Sec-Fetch-Site": "cross-site"})
            response = conn.getresponse()
            self.assertEqual(403, response.status)
            response.read()
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_cross_site_request_boundary(self) -> None:
        # Chrome labels *any* navigation whose initiator was another origin
        # "cross-site" — including a user clicking a link to the dashboard.
        # Rejecting those returned 403 for an ordinary way to open the page
        # (found by loading it in a real browser). Serving a top-level
        # document navigation is safe: the initiator cannot read a
        # cross-origin document. Everything that *can* read stays blocked.
        navigation = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
        cases = [
            # (method, path, headers, expected status, why)
            ("GET", "/", {"Sec-Fetch-Site": "cross-site", **navigation}, 200, "link to page"),
            (
                "GET",
                "/api/data",
                {"Sec-Fetch-Site": "cross-site", **navigation},
                200,
                "link to api",
            ),
            ("GET", "/", {"Sec-Fetch-Site": "none", **navigation}, 200, "typed/bookmarked"),
            ("GET", "/api/data", {"Sec-Fetch-Site": "same-origin"}, 200, "the page's own poll"),
            # Readable by the initiator — must stay blocked.
            (
                "GET",
                "/api/data",
                {
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Dest": "empty",
                },
                403,
                "cross-site fetch",
            ),
            (
                "GET",
                "/",
                {
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "iframe",
                },
                403,
                "framed by another site",
            ),
            # Served, and that is the hole the `frame-ancestors` header covers
            # rather than this gate: every port on this machine is the *same
            # site*, so a page on another local port frames the board with a
            # `same-site` label that never reaches the cross-site branch, and a
            # frame navigation carries no `Origin` for the check below it. The
            # request is answered; the browser is what refuses to render it.
            (
                "GET",
                "/",
                {
                    "Sec-Fetch-Site": "same-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "iframe",
                },
                200,
                "framed from another local port",
            ),
            # The two routes that hold a socket open refuse the same framed
            # request `/` above is answered on, and the resource being defended
            # is the BROWSER's connection pool rather than this server's budget.
            # Measured 2026-09-07 in Chrome: eight frames on `/api/stream` took
            # six sockets, not eight, because a browser caps HTTP/1.1
            # connections per origin at six -- so the eight-slot stream budget
            # was never drained and a seventh client still got a 200. What those
            # six frames did drain was Chrome's own pool, and the real board then
            # would not load at all until they were removed.
            (
                "GET",
                "/api/stream",
                {
                    "Sec-Fetch-Site": "same-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "iframe",
                },
                403,
                "a frame may not hold a stream socket",
            ),
            (
                "GET",
                "/api/ask/nothing-here",
                {
                    "Sec-Fetch-Site": "same-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "iframe",
                },
                403,
                "a frame may not hold the ask long poll",
            ),
            (
                "GET",
                "/api/data",
                {"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example", **navigation},
                403,
                "cross-origin Origin header",
            ),
            # A cross-site form submission is also a "navigation", so POST
            # must never take the relaxed path.
            (
                "POST",
                "/api/notify",
                {"Sec-Fetch-Site": "cross-site", **navigation},
                403,
                "cross-site form POST",
            ),
            ("GET", "/", {"Host": "evil.example"}, 403, "DNS rebinding"),
        ]
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            for method, path, headers, expected, why in cases:
                with self.subTest(why=why):
                    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
                    body = b'{"session_id":"x"}' if method == "POST" else None
                    conn.request(method, path, body=body, headers=headers)
                    response = conn.getresponse()
                    self.assertEqual(expected, response.status)
                    response.read()
                    conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_every_sent_response_forbids_being_framed(self) -> None:
        # The request gate cannot close this: the case above is answered 200,
        # and the served document carries the focus capability, so a framed
        # board is one lured click from raising a terminal. The header is the
        # whole defense, and it has to be a header — CSP ignores
        # `frame-ancestors` delivered in a `<meta http-equiv>`, and no version
        # of `X-Frame-Options` was ever honoured in one.
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            # A POST among them, and that is the case this loop was missing.
            # The header is unconditional today, but wrapping the `send_header`
            # in `if self.command == "GET":` was applied in a scratch copy and
            # the whole suite stayed green while every POST reply -- answer,
            # notify, ask, focus, events, shutdown -- lost it over the socket.
            for method, path, body in (
                ("GET", "/", None),
                ("GET", "/api/data", None),
                ("POST", "/api/notify", b"{}"),
            ):
                with self.subTest(path=path, method=method):
                    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
                    conn.request(method, path, body=body, headers={"Sec-Fetch-Site": "same-origin"})
                    response = conn.getresponse()
                    self.assertEqual(200, response.status)
                    # Equality, not a substring: `frame-ancestors` has no
                    # fallback to `default-src`, so it is the one directive that
                    # can ride here without restricting anything else. A second
                    # one added to this policy blanks the page, and this is what
                    # says so before it ships.
                    self.assertEqual(
                        "frame-ancestors 'none'",
                        response.getheader("Content-Security-Policy"),
                    )
                    response.read()
                    conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_collect_json_single_flights_concurrent_cold_requests(self) -> None:
        calls: list[tuple[float, bool]] = []
        calls_lock = threading.Lock()

        # Read the window off the application under test, so a collect_json that
        # ignored its window argument is visible here rather than silent.
        def fake_collect(app: aggregate.Application, *, show_all: bool) -> dict[str, Any]:
            with calls_lock:
                calls.append((app.config.window_hours, show_all))
            time.sleep(0.02)
            return {"window_hours": app.config.window_hours, "show_all": show_all}

        with mock.patch.object(aggregate.Application, "collect", fake_collect):
            with ThreadPoolExecutor(max_workers=12) as pool:
                bodies = list(pool.map(lambda _: collect_json(24, False), range(24)))
            alternate = collect_json(24, True)

        self.assertEqual(1, calls.count((24, False)))
        self.assertEqual(1, calls.count((24, True)))
        self.assertEqual(1, len(set(bodies)))
        self.assertNotEqual(bodies[0], alternate)
        # Both variants are published, separately, into the runtime's snapshot.
        snap = state_of().snapshot
        self.assertIsNotNone(snap.current((24, False)))
        self.assertIsNotNone(snap.current((24, True)))

    @staticmethod
    def _get_headers(port: int, path: str) -> tuple[int, email.message.Message, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def test_api_data_names_the_revision_it_served(self) -> None:
        """A client cannot hold a cursor it cannot see.

        The revision rides in a header, not the body, so the documented JSON
        contract and every curl caller are untouched.
        """
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            port = httpd.server_port
            _code, headers, body = self._get_headers(port, "/api/data")
            first = headers["X-Compass-Revision"]
            self.assertRegex(first, r"^\d+\.\d+$")
            # The body still parses and still carries its documented keys.
            payload = json.loads(body)
            self.assertIn("sessions", payload)
            self.assertIn("generated", payload)
            # A warm re-read serves the same revision.
            _code, headers, _body = self._get_headers(port, "/api/data")
            self.assertEqual(first, headers["X-Compass-Revision"])
            # A stale read mints a higher counter against the same start stamp.
            state_of().snapshot.clear()
            _code, headers, _body = self._get_headers(port, "/api/data")
            second = headers["X-Compass-Revision"]
            self.assertEqual(first.split(".")[0], second.split(".")[0])
            self.assertGreater(int(second.split(".")[1]), int(first.split(".")[1]))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_only_api_data_carries_a_revision(self) -> None:
        """A page load or a liveness probe must not look like a cursor."""
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            for path in ("/", "/api/health"):
                with self.subTest(path=path):
                    _code, headers, _body = self._get_headers(httpd.server_port, path)
                    self.assertIsNone(headers.get("X-Compass-Revision"))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_a_requested_window_reaches_the_collection_and_its_memo_key(self) -> None:
        # The window is a request-time argument: /api/data must collect and
        # report the window it was asked for, not the configured default.
        # Mutation-checked: dropping build_app()'s window override, so every
        # request silently used the configured window, passed the suite.
        with mock.patch.object(aggregate, "default_harnesses", lambda **_kw: ()):
            requested = json.loads(collect_json(6, False))
            default = json.loads(collect_json(24, False))

            self.assertEqual(6, requested["window_hours"])
            self.assertEqual(24, default["window_hours"])
            snap = state_of().snapshot
            self.assertIsNotNone(snap.current((6, False)))
            self.assertIsNotNone(snap.current((24, False)))

    def test_collector_failure_is_exposed_in_harness_status(self) -> None:
        def fail(*_args: object) -> list[dict[str, Any]]:
            raise RuntimeError("broken store")

        harnesses = (aggregate.HarnessSpec("test", "Test", lambda _config, _state: True, fail),)
        with (
            mock.patch.object(aggregate, "default_harnesses", lambda **_kw: harnesses),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = collect(24, False)

        self.assertTrue(result["harnesses"][0]["discovered"])
        self.assertEqual("RuntimeError: broken store", result["harnesses"][0]["error"])

    def test_health_reports_identity_without_scanning_any_store(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            # The readiness wait and --status poll this in a loop. If it ever
            # reaches collect(), a liveness check costs a full multi-harness
            # filesystem scan.
            with mock.patch.object(aggregate.Application, "collect") as collect:
                conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
                conn.request("GET", "/api/health")
                response = conn.getresponse()
                status = response.status
                payload = json.loads(response.read())
                conn.close()
            collect.assert_not_called()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
        self.assertEqual(200, status)
        self.assertTrue(payload["ok"])
        self.assertEqual(os.getpid(), payload["pid"])
        self.assertEqual(httpd.server_port, payload["port"])
        self.assertIsInstance(payload["started"], (int, float))

    def test_health_is_refused_from_a_non_local_host_header(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            conn.putrequest("GET", "/api/health", skip_host=True)
            conn.putheader("Host", "evil.example")
            conn.endheaders()
            response = conn.getresponse()
            self.assertEqual(403, response.status)
            response.read()
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


class OverlayLedgerEndpointTest(RuntimeTestCase):
    """`/api/overlays`: the reducer's inputs, for a row `/api/data` cannot explain."""

    @staticmethod
    @contextlib.contextmanager
    def _serving(observation: Any) -> Any:
        httpd = make_server(observation=observation)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    @staticmethod
    def _get(port: int, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/overlays", headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_the_ledger_is_served_as_json(self) -> None:
        coordinator = observation_module.Observation(
            _application(os.name), diagnostic_sink=lambda _message: None
        )
        coordinator.submit(
            "claude",
            {
                "v": 1,
                "event": "input_requested",
                "session_id": "abcdef12-3456-7890-abcd-ef1234567890",
            },
        )
        with self._serving(coordinator) as port:
            code, body = self._get(port)
        self.assertEqual(200, code)
        report = json.loads(body)
        self.assertEqual(["needs_input"], [row["kind"] for row in report["overlays"]])
        self.assertEqual("abcdef12", report["overlays"][0]["sid"])

    def test_recorded_disputes_are_served_beside_the_ledger(self) -> None:
        # One request, not two: a dispute is read against the ledger that
        # produced it, and two requests would be two instants.
        coordinator = observation_module.Observation(
            _application(os.name), diagnostic_sink=lambda _message: None
        )
        state = state_of()
        state.dispute_total = 3
        state.disputes.append({"sid": "abcdef12", "collector_state": "needs_input"})
        with self._serving(coordinator) as port:
            code, body = self._get(port)
        self.assertEqual(200, code)
        report = json.loads(body)
        self.assertEqual(3, report["dispute_total"], "the total outlives the ring")
        self.assertEqual(["abcdef12"], [row["sid"] for row in report["disputes"]])
        self.assertIn("overlays", report, "the ledger still rides in the same response")

    def test_no_coordinator_answers_503_rather_than_404(self) -> None:
        # Under `--no-events` the route exists and the ledger does not. A 404
        # would read as a build too old to have the route, which is the wrong
        # thing to conclude while debugging a missing overlay.
        with self._serving(None) as port:
            code, _body = self._get(port)
        self.assertEqual(503, code)

    def test_a_cross_site_navigation_is_refused_unlike_api_data(self) -> None:
        # `do_GET` relaxes its check so a link to the dashboard works. Nothing
        # renders this route, so the relaxation has no reason to reach it.
        with self._serving(None) as port:
            code, _body = self._get(
                port,
                {
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                },
            )
        self.assertEqual(403, code)


class UsageReceiptOptOutTest(RuntimeTestCase):
    """POST /api/usage honours the server-side usage opt-out.

    `test_quota.PushedReceiptOptOutTest` covers the gate itself. This covers the
    wiring, which is the half a refactor drops without any unit test noticing:
    the handler has to hand its application's config to the shaping call.
    """

    def _post(self, port: int, body: bytes) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST", "/api/usage", body=body, headers={"Content-Type": "application/json"}
            )
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_pushed_quota_is_discarded_when_usage_is_disabled(self) -> None:
        config, state = make_runtime(usage_fetch_enabled=False)
        application = cli.build_application(config, state, clock=time.time)
        httpd = make_server(application=application)
        thread = serve_until_closed(httpd)
        try:
            status, body = self._post(
                httpd.server_port,
                json.dumps({"quota": {"gemini-5h": {"remaining_fraction": 0.3}}}).encode(),
            )
        finally:
            httpd.shutdown()
            thread.join(timeout=5)
        # 200 on purpose: a status-line command must never see an error.
        self.assertEqual(200, status)
        self.assertEqual(b'{"ok":true,"usage":0}', body)
        self.assertEqual([], state.usage_receipts["antigravity"]["entries"])


class DismissEndpointTest(RuntimeTestCase):
    """The reveal routes over a real socket, and the writes beside them.

    `POST /api/dismiss` with `GET /api/cleared`, and `GET /api/annotations`,
    which is the annotation store's reveal and is here rather than beside
    `/api/annotate` because it is the same shape of route as `/api/cleared`:
    strictly same-origin, 503 behind its own switch, and serving a store rather
    than the live board. The class keeps its name because renaming it moves
    every reference for no behavioural gain.

    `test_dismissals` covers the store and the subtraction. This covers the
    wiring, which is the half that breaks silently: the request has to reach the
    store this application's config names, and the published bodies have to be
    dropped or the next GET serves the row for another two and a half seconds.
    """

    def _runtime(self, **changes: Any) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        return make_runtime(state_home=home, state_dir=Path(home), **changes)

    @contextlib.contextmanager
    def _serving(self, application: Any) -> Any:
        httpd = make_server(application=application)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def _post(port: int, body: bytes, *, declared: str | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            if declared is None:
                conn.request(
                    "POST", "/api/dismiss", body=body, headers={"Content-Type": "text/plain"}
                )
            else:
                conn.putrequest("POST", "/api/dismiss")
                conn.putheader("Content-Length", declared)
                conn.endheaders()
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    @staticmethod
    def _get(port: int, path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_a_mark_reaches_the_store_and_the_next_read_reflects_it(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=time.time)
        with self._serving(application) as port:
            # Warm the published body first: without `snapshot.clear()` in the
            # handler, this is exactly the response the GET below would reuse.
            first, _ = self._get(port, "/api/data")
            status, body = self._post(
                port, json.dumps({"harness": "claude", "sid": "abcd1234"}).encode()
            )
            listed_status, listed = self._get(port, "/api/cleared")
        self.assertEqual((200, 200, 200), (first, status, listed_status))
        answer = json.loads(body)
        self.assertIs(True, answer["persisted"])
        self.assertNotIn("cleared", answer)
        self.assertEqual(
            [{"harness": "claude", "sid": "abcd1234"}],
            [{k: v for k, v in row.items() if k != "at"} for row in json.loads(listed)["cleared"]],
        )
        self.assertIsNone(
            state.snapshot.current((config.window_hours, False)),
            "the published body survived the dismissal and would be served again",
        )

    def test_an_oversized_declared_length_is_refused_before_any_read(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _body = self._post(port, b"", declared="200000")
        self.assertEqual(413, status)

    def test_a_body_that_names_nothing_is_a_no_op(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            for body in (b"[]", b"not json", b"{}", b'{"harness": "claude"}'):
                with self.subTest(body=body):
                    status, answer = self._post(port, body)
                    self.assertEqual(200, status)
                    self.assertNotIn("cleared", json.loads(answer))

    def test_an_unmatchable_key_returns_persisted_false_and_does_not_persist(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, body = self._post(
                port,
                json.dumps(
                    {
                        "harness": "claude",
                        "sid": "12345678-1234-1234-1234-123456789abc",
                    }
                ).encode(),
            )
            listed_status, listed = self._get(port, "/api/cleared")
        self.assertEqual(200, status)
        self.assertEqual(200, listed_status)
        answer = json.loads(body)
        self.assertIs(False, answer["persisted"])
        self.assertNotIn("cleared", answer)
        self.assertEqual([], json.loads(listed)["cleared"])

    def test_the_rollback_switch_answers_503_on_both_routes(self) -> None:
        # 503, not 404: under `--no-dismiss` the route exists and the store does
        # not, and a 404 would read as a build too old to have the feature.
        config, state = self._runtime(dismissals_enabled=False)
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            post_status, _ = self._post(port, b'{"harness":"claude","sid":"abcd1234"}')
            get_status, _ = self._get(port, "/api/cleared")
        self.assertEqual((503, 503), (post_status, get_status))

    def test_intent_revision_identifies_the_captured_reveal_rows(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=lambda: 1_800_000_000.0)
        application.harnesses = ()
        annotation_store.annotate(config, state, "pi", "departed", goal="Before discard")
        baseline = application.collect(show_all=False)
        original = departures.published

        def discard_after_capture(*args: Any, **kwargs: Any) -> Any:
            annotation_store.clear(config, state, "pi", "departed")
            return original(*args, **kwargs)

        with self._serving(application) as port:
            with mock.patch.object(departures, "published", side_effect=discard_after_capture):
                status, body = self._get(port, "/api/annotations")
            next_status, next_body = self._get(port, "/api/annotations")
        self.assertEqual((200, 200), (status, next_status))
        captured, current = json.loads(body), json.loads(next_body)
        self.assertIn("intent_revision", captured)
        self.assertEqual(baseline["intent_revision"], captured["intent_revision"])
        self.assertEqual("Before discard", captured["annotations"][0]["goal"])
        self.assertEqual("", current["annotations"][0]["goal"])
        self.assertNotEqual(captured["intent_revision"], current["intent_revision"])
        self.assertEqual(
            application.collect(show_all=False)["intent_revision"], current["intent_revision"]
        )

    def test_the_annotation_reveal_serves_the_store_including_departed_sessions(self) -> None:
        """`GET /api/annotations`, the Intent log's source.

        The store's rows and only the store's: session history keeps a copy of
        the same two fields for fourteen days, and serving the log from there
        would republish words a reader withdrew, because `clear` removes the
        entry while a history observation is never retro-deleted.
        """
        config, state = self._runtime()
        annotation_store.annotate(config, state, "pi", "departed", goal="Prove it landed")
        annotation_store.annotate(config, state, "claude", "abcd1234", goal="Ship the cockpit")
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, body = self._get(port, "/api/annotations")

        self.assertEqual(200, status)
        rows = json.loads(body)["annotations"]
        by_key = {f"{row['harness']}:{row['sid']}": row for row in rows}
        # Neither session is on the board in this runtime; both are served,
        # which is the whole point of the surface.
        self.assertEqual({"pi:departed", "claude:abcd1234"}, set(by_key))
        self.assertEqual("Prove it landed", by_key["pi:departed"]["goal"])
        # The published shape, so the page's existing revision helper reads it
        # without a second wording of the same fact.
        self.assertEqual(1, by_key["pi:departed"]["revision"])
        self.assertEqual(1, by_key["pi:departed"]["revision_count"])

    def test_the_reveal_carries_the_binding_caveat_rather_than_claiming_exact(self) -> None:
        """`published`'s default is BINDING_EXACT, which is a claim.

        Measured by walking the board: every Intent log row served an empty
        `binding_why`, so a list of Claude sessions asserted exact binding on
        identities that are eight published characters. Length alone here,
        because a departed session has no live row to read `resume_id` off and
        those are exactly the rows this route exists to serve.
        """
        config, state = self._runtime()
        annotation_store.annotate(config, state, "claude", "abcd1234", goal="Short id")
        annotation_store.annotate(config, state, "codex", "a-much-longer-identity", goal="Whole id")
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, body = self._get(port, "/api/annotations")

        self.assertEqual(200, status)
        by_sid = {row["sid"]: row for row in json.loads(body)["annotations"]}
        self.assertEqual(annotation_store.BINDING_BY_PREFIX, by_sid["abcd1234"]["binding_why"])
        # And not on an identity long enough to be whole, or the caveat is
        # noise on every row and stops being read.
        self.assertEqual("", by_sid["a-much-longer-identity"]["binding_why"])

    def test_the_reveal_carries_what_was_raised_against_each_row(self) -> None:
        """DRC-4514. The one surface a retained assessment survives on.

        Departures ride the same request as the words rather than the polled
        payload, because the payload only holds sessions still on the board and
        the rows this route exists for have left it. It also keeps a row and its
        raises consistent with each other: they are read in one pass.
        """
        config, state = self._runtime()
        annotation_store.annotate(config, state, "pi", "departed", goal="Prove it landed")
        annotation_store.annotate(config, state, "claude", "abcd1234", goal="Ship the cockpit")
        departures.record(
            config,
            [
                {
                    "harness": "pi",
                    "sid": "departed",
                    "at": 1_000.0,
                    "constraint": "TYPED GOAL",
                    "clause": "Prove it landed",
                    "reading": "The work moved to the installer.",
                    "evidence": "turn transcript",
                    "revision": 1,
                    "cutoff": 1_000.0,
                    "cutoff_text": "",
                    "withdrawn": False,
                }
            ],
        )
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, body = self._get(port, "/api/annotations")

        self.assertEqual(200, status)
        by_key = {f"{r['harness']}:{r['sid']}": r for r in json.loads(body)["annotations"]}
        raised = by_key["pi:departed"]
        self.assertEqual(1, len(raised["departures"]))
        self.assertEqual("TYPED GOAL", raised["departures"][0]["constraint"])
        # A raise carries no absence sentence beside it.
        self.assertEqual("", raised["departure_why"])
        # And a session the lane never reached says that, rather than reading
        # as one that was checked and found clean.
        quiet = by_key["claude:abcd1234"]
        self.assertEqual([], quiet["departures"])
        self.assertEqual(departures.NEVER_CHECKED, quiet["departure_why"])

    def test_the_reveal_will_not_say_a_blanked_entry_was_checked_against_words(self) -> None:
        """DRC-4560. The route holds an entry for every row, so a hard-coded
        True here would look right and keep the defect.

        The entry standing with nothing typed in it is what the board's `clear`
        plus the save after it leaves behind, and the Intent log is a surface
        that outlives the session, so the wrong sentence outlives it too.
        """
        config, state = self._runtime()
        annotation_store.annotate(config, state, "pi", "blanked", goal="Prove it landed")
        annotation_store.annotate(config, state, "pi", "blanked", goal="")
        departures.record(
            config,
            [
                {
                    "harness": "pi",
                    "sid": "blanked",
                    "at": 1_000.0,
                    "constraint": "",
                    "clause": "",
                    "reading": "",
                    "evidence": "",
                    "revision": 1,
                    "cutoff": 1_000.0,
                    "cutoff_text": "",
                    "withdrawn": False,
                }
            ],
        )
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, body = self._get(port, "/api/annotations")

        self.assertEqual(200, status)
        row = json.loads(body)["annotations"][0]
        self.assertEqual(departures.NEVER_CHECKED, row["departure_why"])
        self.assertNotEqual(departures.NOTHING_DEPARTED, row["departure_why"])

    def test_the_reveal_never_serves_a_raise_under_the_never_checked_sentence(self) -> None:
        """DRC-4560. Both halves of the row are derived here, so they can disagree.

        The route serves `departures` and `departure_why` from one store read,
        and the page prints the second directly under the first. The blank save
        leaves the entry standing with nothing in it while the raise made
        against the earlier revision stays, so the sentence claiming nothing
        was read here would go out over the wire beside the quotation of what
        was read.
        """
        config, state = self._runtime()
        annotation_store.annotate(
            config, state, "pi", "blanked", goal="do not change the board while capturing"
        )
        annotation_store.annotate(config, state, "pi", "blanked", goal="")
        departures.record(
            config,
            [
                {
                    "harness": "pi",
                    "sid": "blanked",
                    "at": 1_000.0,
                    "constraint": "TYPED GOAL",
                    "clause": "do not change the board while capturing",
                    "reading": "Two turns edited the running board between captures.",
                    "evidence": "turn transcript",
                    "revision": 1,
                    "cutoff": 1_000.0,
                    "cutoff_text": "",
                    "withdrawn": False,
                }
            ],
        )
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, body = self._get(port, "/api/annotations")

        self.assertEqual(200, status)
        row = json.loads(body)["annotations"][0]
        self.assertEqual(1, len(row["departures"]))
        self.assertEqual("", row["departure_why"])

    def test_a_withdrawn_annotation_leaves_the_reveal(self) -> None:
        """The WORDS leave; a text-free record of the act stays (DRC-4565).

        The route used to serve nothing at all here, which is what made a
        discard erase the session from the one surface built to outlive it.
        What it serves now is a row carrying no goal, no expected output and
        no reading -- and saying so in sentences a session nobody typed
        against would never get.
        """
        config, state = self._runtime()
        annotation_store.annotate(config, state, "pi", "s1", goal="withdraw me")
        annotation_store.clear(config, state, "pi", "s1")
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, body = self._get(port, "/api/annotations")

        self.assertEqual(200, status)
        rows = json.loads(body)["annotations"]
        self.assertEqual(1, len(rows))
        self.assertNotIn("withdraw me", body.decode())
        self.assertEqual("", rows[0]["goal"])
        self.assertEqual("", rows[0]["line_1"])
        self.assertEqual(annotation_store.DISCARDED_LINES, rows[0]["lines_why"])
        self.assertIsNone(rows[0]["assessment"])
        self.assertIsNotNone(rows[0]["discarded_at"])
        self.assertEqual(annotation_store.DISCARDED_GOAL, rows[0]["goal_why"])

    def test_the_annotation_reveal_is_503_under_the_off_switch(self) -> None:
        config, state = self._runtime(annotations_enabled=False)
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _ = self._get(port, "/api/annotations")

        # The route exists and the store does not, which a 404 would read as a
        # build too old to have it.
        self.assertEqual(503, status)

    def test_the_annotation_reveal_refuses_a_cross_site_navigation(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _ = self._get(
                port,
                "/api/annotations",
                {
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                },
            )
        self.assertEqual(403, status)

    def test_the_reveal_refuses_a_cross_site_navigation_unlike_api_data(self) -> None:
        # Same reasoning as `/api/overlays`: nothing navigates here, so `do_GET`'s
        # relaxation for document navigations has no reason to reach it.
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _ = self._get(
                port,
                "/api/cleared",
                {
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                },
            )
        self.assertEqual(403, status)


class AskEndpointTest(RuntimeTestCase):
    """The four ask routes over a real socket.

    `test_asks` covers the registry. This covers the ingress, which is the half
    that breaks silently: the untrusted question and options are bounded here
    and nowhere else, because `asks` imports nothing and so cannot reach
    `records.safe_text` itself.
    """

    # A bidi mark, which `records.safe_text` strips: the same character class
    # that could make a question read as something it does not say. Spelled as
    # an escape rather than the literal, which ruff's PLE2502 rejects on sight.
    BIDI = "\u200f"

    def _runtime(self, **changes: Any) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        # A short hold by default: every test that wants a 204 would otherwise
        # wait out the ten-second production poll.
        changes.setdefault("ask_poll_timeout_sec", 0.2)
        return make_runtime(state_home=home, state_dir=Path(home), **changes)

    @contextlib.contextmanager
    def _serving(self, application: Any, observation: Any = None) -> Any:
        # None is what `--no-events` builds, and what every test here but the
        # wake-seam one wants.
        httpd = make_server(application=application, observation=observation)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def _post(
        port: int, path: str, body: bytes, *, declared: str | None = None
    ) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            if declared is None:
                conn.request("POST", path, body=body, headers={"Content-Type": "text/plain"})
            else:
                conn.putrequest("POST", path)
                conn.putheader("Content-Length", declared)
                conn.endheaders()
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    @staticmethod
    def _get(port: int, path: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request("GET", path, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def _register(self, port: int, **fields: Any) -> str:
        body: dict[str, Any] = {
            "harness": "claude",
            "session_id": "aaa1bbb2",
            "project": "repo/proj",
            "question": "Ship the migration now?",
            "options": ["Ship it", "Wait for review"],
        }
        body.update(fields)
        status, answer = self._post(port, "/api/ask", json.dumps(body).encode())
        self.assertEqual(200, status, answer)
        payload = json.loads(answer)
        self.assertIs(True, payload["ok"])
        return str(payload["id"])

    def test_a_question_is_registered_answered_once_and_then_gone(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            ask_id = self._register(port)
            self.assertEqual(1, state.asks.count)
            pending_status, pending_body = self._get(port, f"/api/ask/{ask_id}")
            answered_status, answered = self._post(
                port, "/api/answer", json.dumps({"id": ask_id, "index": 1}).encode()
            )
            delivered_status, delivered = self._get(port, f"/api/ask/{ask_id}")
            # Delivered exactly once: the poll releases the ask, so a second
            # poll finds nothing rather than replaying the answer.
            gone_status, _ = self._get(port, f"/api/ask/{ask_id}")
        self.assertEqual((204, b""), (pending_status, pending_body))
        self.assertEqual(
            (200, {"ok": True, "answered": True}), (answered_status, json.loads(answered))
        )
        self.assertEqual(
            (200, {"state": "answered", "index": 1}), (delivered_status, json.loads(delivered))
        )
        self.assertEqual(404, gone_status)
        self.assertEqual(0, state.asks.count)

    def test_a_whole_claude_session_id_is_keyed_on_the_rows_sid(self) -> None:
        # The stdio server sends CLAUDE_CODE_SESSION_ID whole; rows key on its
        # first eight characters, and the page matches the two exactly. Every ask
        # test before this one sent the short form, which is how a real ask came
        # to attach to no session.
        config, state = self._runtime()
        whole = "a5a5a5a5-4444-4555-8666-777788889999"
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            claude_id = self._register(port, session_id=whole)
            other_id = self._register(port, harness="codex", session_id=whole)
            unmapped_id = self._register(port, harness="unknown", session_id=whole)
            claude = state.asks.get(claude_id)
            other = state.asks.get(other_id)
            unmapped = state.asks.get(unmapped_id)
        assert claude is not None and other is not None and unmapped is not None
        self.assertEqual("a5a5a5a5", claude.session_id)
        self.assertEqual(whole, other.session_id, "Codex keys on the whole id")
        self.assertEqual(whole, unmapped.session_id, "an unmapped id is kept as sent")

    def test_registering_and_answering_both_drop_the_published_body(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            first, _ = self._get(port, "/api/data")
            ask_id = self._register(port)
            after_register = state.snapshot.current((config.window_hours, False))
            self._get(port, "/api/data")
            self._post(port, "/api/answer", json.dumps({"id": ask_id, "index": 0}).encode())
            after_answer = state.snapshot.current((config.window_hours, False))
        self.assertEqual(200, first)
        self.assertIsNone(after_register, "the published body survived the registration")
        self.assertIsNone(after_answer, "the published body survived the answer")

    def test_the_rollback_flag_reaches_configuration(self) -> None:
        # The four routes below key off `ask_enabled`, so the flag that sets it
        # is the half of the rollback switch a 503 test cannot see.
        parser = cli.build_parser()
        default, _ = cli.build_runtime(parser.parse_args([]), started=1.0)
        opted_out, _ = cli.build_runtime(parser.parse_args(["--no-ask"]), started=1.0)
        self.assertIs(True, default.ask_enabled)
        self.assertIs(False, opted_out.ask_enabled)

    def test_the_rollback_switch_answers_503_on_all_four_routes(self) -> None:
        # 503, not 404, for the reason `--no-dismiss` gives: under `--no-ask` the
        # routes exist and the registry is never filled, and a 404 would read as
        # a build too old to have the feature.
        config, state = self._runtime(ask_enabled=False)
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            register, _ = self._post(port, "/api/ask", b'{"question":"q","options":["a","b"]}')
            answer, _ = self._post(port, "/api/answer", b'{"id":"x","index":0}')
            withdraw, _ = self._post(port, "/api/ask/withdraw", b'{"id":"x"}')
            poll, _ = self._get(port, "/api/ask/anything")
        self.assertEqual((503, 503, 503, 503), (register, answer, withdraw, poll))

    def test_a_refusal_says_whether_the_lane_is_off_or_merely_busy(self) -> None:
        """A bare 503 read as "no dashboard here", so the peer walked to another.

        Measured: the stdio server treated any non-200 as a port that would not
        take the question, tried the next candidate, and registered on a second
        dashboard that had the lane switched on, which is exactly what `--no-ask`
        exists to prevent. Both cases stay 503 because both are honest "not right
        now" answers; the reason is what separates a permanent refusal from one
        that clears on its own.
        """
        body = json.dumps({"question": "q", "options": ["a", "b"]}).encode()
        off_config, off_state = self._runtime(ask_enabled=False)
        with self._serving(cli.build_application(off_config, off_state, clock=time.time)) as port:
            disabled_status, disabled_body = self._post(port, "/api/ask", body)
            withdraw_status, withdraw_body = self._post(port, "/api/ask/withdraw", b'{"id":"x"}')
        full_config, full_state = self._runtime(ask_max_pending=1)
        with self._serving(cli.build_application(full_config, full_state, clock=time.time)) as port:
            self._register(port)
            busy_status, busy_body = self._post(port, "/api/ask", body)
        self.assertEqual(503, disabled_status)
        self.assertEqual({"ok": False, "reason": "disabled"}, json.loads(disabled_body))
        self.assertEqual(503, withdraw_status)
        self.assertEqual({"ok": False, "reason": "disabled"}, json.loads(withdraw_body))
        self.assertEqual(503, busy_status)
        self.assertEqual({"ok": False, "reason": "busy"}, json.loads(busy_body))

    def test_a_withdrawal_clears_the_card_and_declines_the_peer(self) -> None:
        """An abandoned question has to leave the board, not sit out its deadline.

        Without this route a card whose asking session has already given up stays
        clickable for the rest of the deadline, and the click is accepted and
        thrown away: the reader is told nothing, and answered a question nobody
        is listening to.
        """
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            ask_id = self._register(port)
            ask = state.asks.get(ask_id)
            # Republished first, so the drop below is this route's doing rather
            # than the registration's.
            self._get(port, "/api/data")
            status, body = self._post(
                port, "/api/ask/withdraw", json.dumps({"id": ask_id}).encode()
            )
            after = state.snapshot.current((config.window_hours, False))
            poll_status, _ = self._get(port, f"/api/ask/{ask_id}")
        assert ask is not None
        self.assertEqual(200, status)
        self.assertEqual({"ok": True, "withdrawn": True}, json.loads(body))
        self.assertEqual(("declined", None), ask.outcome)
        self.assertEqual(0, state.asks.count)
        self.assertIsNone(after, "the published body survived the withdrawal")
        self.assertEqual(404, poll_status)

    def test_withdrawing_what_nobody_registered_is_a_200_no_op(self) -> None:
        # A 404 for an unknown id would make this an oracle for which asks
        # exist, exactly as it would on `/api/answer`, so the caller reads
        # `withdrawn` rather than the status line.
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            # A live ask on the board throughout, so the count below can tell a
            # no-op from a withdrawal that hit the wrong row.
            self._register(port)
            bodies: list[dict[str, Any]] = [{"id": "nosuchask"}, {"id": 7}, {}]
            for payload in bodies:
                with self.subTest(payload=payload):
                    status, body = self._post(
                        port, "/api/ask/withdraw", json.dumps(payload).encode()
                    )
                    self.assertEqual(200, status)
                    self.assertEqual({"ok": True, "withdrawn": False}, json.loads(body))
            malformed, malformed_body = self._post(port, "/api/ask/withdraw", b"not json")
            oversized, _ = self._post(port, "/api/ask/withdraw", b"", declared="8192")
        self.assertEqual(200, malformed)
        self.assertEqual({"ok": True, "withdrawn": False}, json.loads(malformed_body))
        self.assertEqual(413, oversized)
        self.assertEqual(
            1, state.asks.count, "an unusable withdrawal took a live ask off the board"
        )

    def test_a_non_string_question_or_option_is_refused_not_stringified(self) -> None:
        """`safe_text` calls `str(value or "")`, so a non-string publishes a repr.

        Measured on the shipped route: a question of `{"a": 1}` registered and
        the card read `{'a': 1}`; options `[{"a": 1}, {"b": 2}]` rendered as
        `{'a': 1}` and `{'b': 2}`; and `[1, 2]` was accepted while `[0, 1]` was
        refused, because falsiness rather than type decided. The answer is an
        index into these options, so a stringified one is a choice the asking
        session never offered.
        """
        config, state = self._runtime()
        bodies: dict[str, dict[str, Any]] = {
            "an integer question": {"question": 42, "options": ["a", "b"]},
            "an object question": {"question": {"a": 1}, "options": ["a", "b"]},
            "a list question": {"question": ["a", "b"], "options": ["a", "b"]},
            "a boolean question": {"question": True, "options": ["a", "b"]},
            "object options": {"question": "q", "options": [{"a": 1}, {"b": 2}]},
            "list options": {"question": "q", "options": [["x", "y"], ["z"]]},
            "integer options": {"question": "q", "options": [1, 2]},
            "integer options including zero": {"question": "q", "options": [0, 1]},
            "boolean options": {"question": "q", "options": [True, False]},
            "one non-string option": {"question": "q", "options": ["a", 2]},
            "a null option": {"question": "q", "options": ["a", None]},
        }
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            for label, fields in bodies.items():
                with self.subTest(label=label):
                    body = {"harness": "claude", "session_id": "aaa1", "project": "p", **fields}
                    status, _ = self._post(port, "/api/ask", json.dumps(body).encode())
                    self.assertEqual(400, status)
        self.assertEqual(0, state.asks.count)

    def test_a_registration_wakes_the_coordinator_with_no_registry_lock_held(self) -> None:
        """The card is drawn by a collection, and a registration has to force one.

        The lock order is the other half of the contract: `Observation._due`
        takes the registry lock while holding `_lock`, and `note_ask` takes
        `_lock`, so calling it while still holding a registry lock is the one
        edge that would close the cycle.
        """
        config, state = self._runtime(ask_max_pending=1)
        application = cli.build_application(config, state, clock=time.time)
        coordinator = observation_module.Observation(
            application, diagnostic_sink=lambda _line: None
        )
        application.overlays = coordinator
        free: list[bool] = []
        original = coordinator.note_ask

        def note_ask() -> None:
            acquired = state.asks._lock.acquire(blocking=False)
            free.append(acquired)
            if acquired:
                state.asks._lock.release()
            original()

        with (
            mock.patch.object(coordinator, "note_ask", note_ask),
            self._serving(application, observation=coordinator) as port,
        ):
            self._register(port)
            refused, _ = self._post(
                port, "/api/ask", json.dumps({"question": "q", "options": ["a", "b"]}).encode()
            )
        self.assertEqual(503, refused)
        # Once, for the accepted registration only: a refused one woke a
        # coordinator that has nothing new to draw.
        self.assertEqual([True], free)
        self.assertEqual(1, coordinator._dirty.get(observation_module.ASK_GENERATION))

    def test_a_registration_works_on_a_server_with_no_coordinator(self) -> None:
        # `--no-events` builds a server with no coordinator at all, so the wake
        # seam has to be optional rather than assumed.
        config, state = self._runtime()
        httpd = make_server(application=cli.build_application(config, state, clock=time.time))
        thread = serve_until_closed(httpd)
        try:
            self.assertIsNone(httpd.observation)
            ask_id = self._register(httpd.server_port)
        finally:
            httpd.shutdown()
            thread.join(timeout=5)
        self.assertIsNotNone(state.asks.get(ask_id))

    def test_an_oversized_declared_length_is_refused_before_any_read(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            register, _ = self._post(port, "/api/ask", b"", declared="200000")
            # The answer body carries an id and an integer, so its cap sits far
            # below the register cap and a register-sized body is refused here.
            answer, _ = self._post(port, "/api/answer", b"", declared="8192")
        self.assertEqual((413, 413), (register, answer))

    def test_a_question_or_option_list_too_thin_to_answer_is_refused(self) -> None:
        config, state = self._runtime()
        bodies: dict[str, dict[str, Any]] = {
            "no question": {"question": "", "options": ["a", "b"]},
            "control characters only": {"question": " " + self.BIDI, "options": ["a", "b"]},
            "one option": {"question": "q", "options": ["only"]},
            "no options": {"question": "q", "options": []},
            "options not a list": {"question": "q", "options": "ab"},
            "an option that bounds to empty": {"question": "q", "options": ["a", " "]},
        }
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            for label, fields in bodies.items():
                with self.subTest(label=label):
                    body = {"harness": "claude", "session_id": "aaa1", "project": "p", **fields}
                    status, _ = self._post(port, "/api/ask", json.dumps(body).encode())
                    self.assertEqual(400, status)
        self.assertEqual(0, state.asks.count)

    def test_a_malformed_body_is_refused_rather_than_registered(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            for body in (b"not json", b"[]", b"null", b""):
                with self.subTest(body=body):
                    status, _ = self._post(port, "/api/ask", body)
                    self.assertEqual(400, status)
        self.assertEqual(0, state.asks.count)

    def test_agent_written_text_is_bounded_and_stripped_at_the_ingress(self) -> None:
        config, state = self._runtime(ask_question_cap_chars=10, ask_option_cap_chars=4)
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            ask_id = self._register(
                port,
                question="a" * 40 + " tail",
                options=["b" * 40, f"c{self.BIDI}d", *[f"opt{n}" for n in range(20)]],
            )
        ask = state.asks.get(ask_id)
        self.assertIsNotNone(ask)
        assert ask is not None
        self.assertEqual("a" * 10, ask.question)
        self.assertEqual(config.ask_max_options, len(ask.options))
        self.assertEqual(("bbbb", "c d"), ask.options[:2])

    def test_an_over_long_project_keeps_its_tail_and_marks_the_cut(self) -> None:
        """A path's identity is its end, so bounding it from the front is a lie.

        Found end to end rather than by reading: a 122-character cwd against the
        old 120-character label cap published `.../e2e/adop` for a directory
        named `adopt2`, so the card attributed the question to somewhere that
        does not exist.
        """
        config, state = self._runtime(ask_project_cap_chars=40)
        deep = "/private/tmp/" + "nesting/" * 12 + "the-real-dir"
        self.assertGreater(len(deep), config.ask_project_cap_chars)
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            ask_id = self._register(port, project=deep)
        ask = state.asks.get(ask_id)
        assert ask is not None
        self.assertEqual(config.ask_project_cap_chars, len(ask.project))
        self.assertTrue(ask.project.endswith("the-real-dir"), ask.project)
        self.assertTrue(ask.project.startswith("…"), ask.project)

    def test_a_project_inside_the_cap_is_published_whole(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            ask_id = self._register(port, project="/repo/proj")
        ask = state.asks.get(ask_id)
        assert ask is not None
        self.assertEqual("/repo/proj", ask.project)

    def test_the_budget_refuses_past_the_cap(self) -> None:
        config, state = self._runtime(ask_max_pending=2)
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            self._register(port)
            self._register(port)
            status, _ = self._post(
                port,
                "/api/ask",
                json.dumps({"question": "q", "options": ["a", "b"]}).encode(),
            )
        self.assertEqual(503, status)
        self.assertEqual(2, state.asks.count)

    def test_an_answer_naming_nothing_is_a_200_no_op_not_an_oracle(self) -> None:
        # A 404 for an unknown id would tell a caller which asks exist, so every
        # unusable answer body gets the same 200 an unknown id gets.
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            ask_id = self._register(port)
            bodies: list[dict[str, Any]] = [
                {"id": "nosuchask", "index": 0},
                {"id": ask_id, "index": 7},
                {"id": ask_id, "index": -1},
                {"id": ask_id, "index": "1"},
                # True is an int in Python, and would silently answer option 1.
                {"id": ask_id, "index": True},
                {"id": ask_id},
                {},
            ]
            for body in bodies:
                with self.subTest(body=body):
                    status, answer = self._post(port, "/api/answer", json.dumps(body).encode())
                    self.assertEqual(200, status)
                    self.assertEqual({"ok": True, "answered": False}, json.loads(answer))
            ask = state.asks.get(ask_id)
        self.assertIsNotNone(ask)
        assert ask is not None
        self.assertIsNone(ask.outcome, "an unusable answer body resolved the ask anyway")

    def test_a_poll_refuses_a_cross_site_navigation_unlike_api_data(self) -> None:
        # Same reasoning as `/api/cleared`: nothing navigates here, so `do_GET`'s
        # relaxation for document navigations has no reason to reach it.
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            ask_id = self._register(port)
            status, _ = self._get(
                port,
                f"/api/ask/{ask_id}",
                {
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                },
            )
        self.assertEqual(403, status)

    @staticmethod
    def _settle_popups(notify: Any, expected: int, *, timeout: float = 5.0) -> None:
        """Wait for the ask popup, which happens after the reply is on the wire.

        `_ask` sends its reply and only then notifies, deliberately: osascript
        runs on the handler thread with a 5s timeout against the stdio client's
        3s register POST. So the client returns BEFORE the popup, nothing joins
        the handler thread, and `_serving` shuts the server down on the way out.

        That makes an immediate assertion a race in both directions, and the
        second one is the dangerous half. A `== 1` can miss a call that was about
        to happen, which is a flake. A `== 0` can PASS because the thread has not
        got there yet, which would hide a real double fire and look like a green
        test forever. So a zero expectation waits out a grace period rather than
        returning at once.
        """
        deadline = time.monotonic() + timeout
        while notify.call_count < expected and time.monotonic() < deadline:
            time.sleep(0.02)
        if expected == 0:
            time.sleep(0.5)

    def test_a_registered_question_pops_only_where_the_server_owns_the_popup(self) -> None:
        # Exactly one layer notifies (design decision D-3), and the split is read
        # off the same expression `/api/data` publishes as `native_notify`. The
        # platform comes from config, never from the host, so both halves run on
        # every runner (D-4).
        config, state = self._runtime(platform_name="darwin")
        with (
            self._serving(cli.build_application(config, state, clock=time.time)) as port,
            mock.patch.object(notifications, "notify_mac") as notify,
        ):
            ask_id = self._register(port)
            self._settle_popups(notify, 1)
        self.assertEqual(1, notify.call_count)
        self.assertEqual("Claude is asking you", notify.call_args[0][1])
        self.assertEqual("Ship the migration now? · repo/proj", notify.call_args[0][2])
        self.assertTrue(ask_id)

        config, state = self._runtime()
        with (
            self._serving(cli.build_application(config, state, clock=time.time)) as port,
            mock.patch.object(notifications, "notify_mac") as notify,
        ):
            self._register(port)
            self._settle_popups(notify, 0)
        self.assertEqual(0, notify.call_count, "the page owns this one")

        # The rollback switch: `_ask` answers 503 before the body is read, so the
        # notifier cannot be reached however the call site later moves.
        config, state = self._runtime(ask_enabled=False)
        with (
            self._serving(cli.build_application(config, state, clock=time.time)) as port,
            mock.patch.object(notifications, "notify_mac") as notify,
        ):
            status, _ = self._post(
                port, "/api/ask", json.dumps({"question": "q", "options": ["a", "b"]}).encode()
            )
            self._settle_popups(notify, 0)
        self.assertEqual(503, status)
        self.assertEqual(0, notify.call_count)

    def test_an_unattributable_question_never_names_a_harness(self) -> None:
        # `unknown` is the shipped default for every client but Claude Code, so
        # this is the common case rather than an edge. A raw fallback would title
        # it "unknown is asking you", and a 120-character value would reach
        # `safe_text(title, 60)`, which truncates from the FRONT and so deletes
        # the words " is asking you".
        for harness in ("unknown", "", "x" * 120):
            with self.subTest(harness=harness):
                # Its own runtime per case: the ask floor is shared across a
                # process, so a second registration inside 15s raises nothing.
                config, state = self._runtime(platform_name="darwin")
                with (
                    self._serving(cli.build_application(config, state, clock=time.time)) as port,
                    mock.patch.object(notifications, "notify_mac") as notify,
                ):
                    self._register(port, harness=harness, session_id="")
                    self._settle_popups(notify, 1)
                self.assertEqual(1, notify.call_count)
                title = notify.call_args[0][1]
                self.assertEqual("An agent is asking you", title)
                self.assertNotIn("unknown", title)
                self.assertNotIn("Claude", title)

    def test_the_popup_fires_after_the_reply_is_on_the_wire(self) -> None:
        # osascript runs with a 5s timeout on the handler thread, and the stdio
        # client's register POST times out at 3s. A lost reply is not a retry:
        # `_register` walks to the next candidate port and registers the question
        # on a second dashboard, while the first keeps a card that cannot be
        # withdrawn because its id was in the lost reply.
        #
        # So the client's reply arrives BEFORE the notifier runs, and nothing joins
        # the handler thread: asserting as soon as the POST returns raced the
        # thread, and lost on a slow macOS runner (DRC-4707). Wait on the notifier
        # itself, inside the server's lifetime, and on `handle_error` too so its
        # patch is still in place when the raised traceback reaches it.
        config, state = self._runtime(platform_name="darwin")
        calls: list[tuple[str, str]] = []
        notified = threading.Event()
        handled = threading.Event()

        def boom(title: str, message: str) -> None:
            calls.append((title, message))
            notified.set()
            raise RuntimeError("osascript exploded after the reply")

        application = aggregate.Application(
            config,
            state,
            aggregate.default_harnesses(),
            native_notifier=notifications.native_notifier,
            popup_notifier=boom,
            diagnostic_sink=lambda _line: None,
            clock=lambda: 1000.0,
        )
        with (
            # The traceback is the point of the test, not a surprise: keep it out
            # of the run's output.
            mock.patch.object(
                http_api.CompassHTTPServer, "handle_error", lambda *_a: handled.set()
            ),
            self._serving(application) as port,
        ):
            status, body = self._post(
                port,
                "/api/ask",
                json.dumps(
                    {
                        "harness": "claude",
                        "project": "repo/proj",
                        "question": "Ship it?",
                        "options": ["yes", "no"],
                    }
                ).encode(),
            )
            self.assertTrue(notified.wait(5), "the notifier never ran")
            handled.wait(5)
        self.assertEqual(200, status)
        payload = json.loads(body)
        self.assertIs(True, payload["ok"])
        self.assertTrue(payload["id"])
        self.assertEqual(1, len(calls), "the notifier ran more than once")


class AskShutdownTest(RuntimeTestCase):
    """A held poll has to be declined, not dropped.

    Handler threads are daemons that nothing joins, so `server.shutdown()` never
    reaches a poll parked in `wait()`. Measured with the decline removed, the
    poll returns nothing at all inside these windows and would go on holding
    until the process exited under it, which the asking session reads as a
    transport failure rather than as the answer the contract promises it.
    """

    def _runtime(self, **changes: Any) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        # Far longer than the assertion window, so a pass cannot be the poll
        # timing out on its own rather than the shutdown declining it.
        changes.setdefault("ask_poll_timeout_sec", 30.0)
        # `serve` really runs here, and its shutdown closes the model runner
        # for the life of the process: this test's own, so no later test in
        # the worker inherits a closed one.
        patcher = mock.patch.object(runtime_supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        return make_runtime(state_home=home, state_dir=Path(home), **changes)

    def _register(self, state: Any, config: Any) -> str:
        ask = runtime_asks.PendingAsk(
            harness="claude",
            session_id="aaa1bbb2",
            project="repo/proj",
            question="Ship the migration now?",
            options=("Ship it", "Wait for review"),
            created=time.time(),
        )
        self.assertTrue(
            state.asks.register(
                ask,
                limit=config.ask_max_pending,
                deadline=config.ask_deadline_sec,
                retention=config.ask_retention_sec,
            )
        )
        return ask.id

    @staticmethod
    def _park_poll(port: int, ask_id: str, out: dict[str, Any]) -> threading.Thread:
        def poll() -> None:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
            try:
                conn.request("GET", f"/api/ask/{ask_id}")
                response = conn.getresponse()
                out["status"] = response.status
                out["body"] = response.read()
            except (OSError, http.client.HTTPException) as exc:
                # A dropped connection rather than a decline is the whole bug,
                # so it is recorded and asserted on rather than raised here.
                out["error"] = repr(exc)
            finally:
                conn.close()

        thread = threading.Thread(target=poll, daemon=True)
        thread.start()
        return thread

    @staticmethod
    def _settle() -> None:
        """Let the parked poll reach `wait()` before the shutdown lands.

        There is no observable "is parked" signal to poll on. A settle is enough
        because arriving early does not weaken the assertion: the decline is
        recorded on the ask either way, and the poll then returns it.
        """
        time.sleep(0.3)

    def test_the_shutdown_endpoint_declines_a_parked_poll(self) -> None:
        config, state = self._runtime()
        httpd = make_server(application=cli.build_application(config, state, clock=time.time))
        thread = serve_until_closed(httpd)
        out: dict[str, Any] = {}
        try:
            ask_id = self._register(state, config)
            poller = self._park_poll(httpd.server_port, ask_id, out)
            self._settle()
            stop = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            stop.request("POST", "/api/shutdown", body=b"")
            stop.getresponse().read()
            stop.close()
            poller.join(timeout=10)
        finally:
            with contextlib.suppress(Exception):
                httpd.server_close()
            thread.join(timeout=5)
        self.assertNotIn("error", out, "the poll lost its connection, not an answer")
        self.assertEqual(200, out.get("status"))
        self.assertEqual({"state": "declined"}, json.loads(out["body"]))

    def test_serve_cleanup_declines_every_outstanding_ask(self) -> None:
        # The endpoint is not the only way out: a signal, an exception and a
        # `--stop` all leave through `serve`'s finally, so the decline lives
        # there too rather than only on the route that happens to be polite.
        config, state = self._runtime()
        httpd = make_server(application=cli.build_application(config, state, clock=time.time))
        ask_id = self._register(state, config)
        ask = state.asks.get(ask_id)
        self.assertIsNotNone(ask)
        assert ask is not None
        thread = threading.Thread(
            target=lifecycle.serve,
            args=(config, httpd, httpd.server_port),
            kwargs={"started": time.time(), "diagnostic_sink": lambda _line: None},
            daemon=True,
        )
        thread.start()
        try:
            self._wait_until_serving(httpd)
        finally:
            httpd.shutdown()
            thread.join(timeout=10)
        self.assertEqual(("declined", None), ask.outcome)

    @staticmethod
    def _wait_until_serving(httpd: Any) -> None:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            try:
                conn.request("GET", "/api/health")
                if conn.getresponse().status == 200:
                    return
            except OSError:
                time.sleep(0.05)
            finally:
                conn.close()
        raise AssertionError("the serve loop never came up")


class HostAndSocketTest(unittest.TestCase):
    def test_a_bind_never_reverse_resolves_the_address(self) -> None:
        """`HTTPServer.server_bind` calls `socket.getfqdn()`; this one must not.

        It is a reverse DNS lookup on the startup path for a value nothing
        reads, and a resolver with no answer for 127.0.0.1 waits rather than
        failing fast. Measured on the macOS CI runner at ~17.5s per bind — seven
        tests that bind, or spawn something that binds, were 285s of that leg's
        316s, while the other 1936 finished in 31s.

        Asserted by patching the lookup rather than by timing it: on a machine
        with a working resolver the call is instant, so a duration assertion
        here would be a test that cannot fail.
        """
        with mock.patch.object(
            socket, "getfqdn", side_effect=AssertionError("bind reverse-resolved the address")
        ) as getfqdn:
            httpd = make_server()
            try:
                self.assertEqual(0, getfqdn.call_count)
                # Still set, because the base class promises them, and the port
                # is the one the OS actually handed out rather than the 0 asked
                # for.
                self.assertEqual("127.0.0.1", httpd.server_name)
                self.assertEqual(httpd.socket.getsockname()[1], httpd.server_port)
                self.assertNotEqual(0, httpd.server_port)
            finally:
                httpd.server_close()

    def test_host_header_forms_that_are_all_loopback(self) -> None:
        # rsplit(":", 1) mangled the bracketed IPv6 form into "[:" and never
        # folded case, so both were rejected as non-local.
        for value in (
            "127.0.0.1",
            "127.0.0.1:4553",
            "localhost",
            "LOCALHOST",
            "LocalHost:4553",
            "[::1]",
            "[::1]:4553",
            "::1",
        ):
            with self.subTest(host=value):
                self.assertIn(http_api.normalize_host(value), http_api._RequestHandler.LOCAL_HOSTS)

    def test_host_header_forms_that_are_not_loopback(self) -> None:
        for value in (
            "",
            "evil.example",
            "evil.example:4553",
            "127.0.0.1.evil.example",
            "[",
            "[]",
            "192.168.1.5",
            # Only a port may follow a bracketed literal. Ignoring the rest
            # made "[::1]evil.example" reduce to "::1" and pass as loopback.
            "[::1]evil.example",
            "[::1]xyz:99",
            "[::1].",
            "[::1]:notaport",
            # Unbracketed authorities need the same port validation, or
            # "localhost:evil.example" reduces to "localhost".
            "localhost:evil.example",
            "127.0.0.1:evil.example",
            "localhost:",
        ):
            with self.subTest(host=value):
                self.assertNotIn(
                    http_api.normalize_host(value), http_api._RequestHandler.LOCAL_HOSTS
                )

    def test_reuse_address_is_off_only_on_windows(self) -> None:
        # POSIX: SO_REUSEADDR just bypasses TIME_WAIT, so restarts work.
        # Windows: it lets a second process bind an already-bound port.
        self.assertTrue(http_api.reuse_address_allowed("posix"))
        self.assertFalse(http_api.reuse_address_allowed("nt"))

    def test_bind_errors_explain_themselves(self) -> None:
        in_use = OSError(errno.EADDRINUSE, "Address already in use")
        self.assertIn("already in use", http_api.bind_error_message(in_use, 4553))
        self.assertIn("4553", http_api.bind_error_message(in_use, 4553))
        denied = OSError(errno.EACCES, "Permission denied")
        self.assertIn("not permitted", http_api.bind_error_message(denied, 4553))
        other = OSError(errno.EINVAL, "Invalid argument")
        self.assertIn("cannot bind", http_api.bind_error_message(other, 4553))

    def test_windows_error_codes_are_recognized(self) -> None:
        # winerror, not errno, is what Windows populates. 10013 is also what an
        # in-use port reports once SO_EXCLUSIVEADDRUSE is set.
        for winerror, expected in ((10048, "already in use"), (10013, "not permitted")):
            with self.subTest(winerror=winerror):
                exc = OSError()
                exc.winerror = winerror  # type: ignore[attr-defined]
                self.assertIn(expected, http_api.bind_error_message(exc, 4553))

    def test_server_binds_and_serves(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            conn.request("GET", "/api/data")
            response = conn.getresponse()
            self.assertEqual(200, response.status)
            response.read()
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_local_ok_admits_non_loopback_host_on_wildcard_bind(self) -> None:
        # AC-2: a remote request to a 0.0.0.0-bound server is served, not 403.
        # Reverting the _host_admitted relaxation makes _local_ok return False
        # and the handler sends 403.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "192.168.0.2:4553"
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)
        self.assertTrue(handler._local_ok())

    def test_local_ok_rejects_non_loopback_host_on_default_bind(self) -> None:
        # AC-3: the default loopback bind still rejects non-loopback Host
        # headers (DNS-rebinding defense preserved). Removing the
        # bind-conditionality so the relaxation always applies makes this fail.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "192.168.1.5"
        handler.server = mock.Mock(bound_host="127.0.0.1", server_port=4553)
        self.assertFalse(handler._local_ok())

    def test_local_ok_admits_explicit_non_loopback_bind_host_only(self) -> None:
        # An explicit --host 10.0.0.2 bind admits that one address but not
        # another non-loopback address — the operator chose one interface.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.server = mock.Mock(bound_host="10.0.0.2", server_port=4553)

        handler.headers["Host"] = "10.0.0.2:4553"
        self.assertTrue(handler._local_ok())

        handler.headers.replace_header("Host", "10.0.0.3:4553")
        self.assertFalse(handler._local_ok())

    def test_local_ok_wildcard_still_admits_loopback(self) -> None:
        # A 0.0.0.0 bind still accepts loopback Host headers — loopback
        # remains one of its interfaces.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "127.0.0.1:4553"
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)
        self.assertTrue(handler._local_ok())

    def test_local_ok_wildcard_rejects_empty_and_unspecified(self) -> None:
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)

        handler.headers["Host"] = "0.0.0.0:4553"
        self.assertFalse(handler._local_ok())

        handler.headers.replace_header("Host", "")
        self.assertFalse(handler._local_ok())

    def test_wildcard_bind_origin_check_admits_non_loopback(self) -> None:
        # The Origin/Sec-Fetch-Site cross-site checks stay in both modes, but
        # the Origin hostname gate must admit the non-loopback address a
        # remote browser would send as same-origin.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "192.168.0.2:4553"
        handler.headers["Origin"] = "http://192.168.0.2:4553"
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)
        self.assertTrue(handler._local_ok())

    def test_wildcard_bind_refuses_a_dns_name_host(self) -> None:
        # The rebinding defense, which the bind relaxation must not spend. A
        # page on http://evil.example:4553 whose DNS points at this machine
        # sends that name as its Host, and `Sec-Fetch-Site` is `none` on the
        # navigation and `same-origin` on its own fetches, so neither of the
        # cross-site checks fires. Only the address gate stops it. Restoring the
        # `bool(host) and host != "0.0.0.0"` form makes this pass a name and
        # hands that page /api/data plus every POST route.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)
        handler.headers["Host"] = "evil.example:4553"

        for name in ("evil.example:4553", "compass.attacker.io", "dashboard.local:4553"):
            with self.subTest(host=name):
                handler.headers.replace_header("Host", name)
                self.assertFalse(handler._local_ok())

    def test_explicit_bind_refuses_a_dns_name_host(self) -> None:
        # Same gate on an explicit --host: the operator named an address, so a
        # name resolving to it is still refused.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "evil.example:4553"
        handler.server = mock.Mock(bound_host="10.0.0.2", server_port=4553)
        self.assertFalse(handler._local_ok())

    def test_wildcard_bind_refuses_a_dns_name_origin(self) -> None:
        # The Origin arm of the same gate. A Host the operator could have typed
        # with an attacker's Origin is the shape a rebinding fetch takes once
        # the page has the address, and `_is_local_origin` shares the check.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "192.168.0.2:4553"
        handler.headers["Origin"] = "http://evil.example:4553"
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)
        self.assertFalse(handler._local_ok())

    def test_wildcard_bind_refuses_multicast_and_unspecified(self) -> None:
        # Neither is an address a client can arrive on, so neither is the
        # operator's opt-in.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)
        handler.headers["Host"] = "224.0.0.1:4553"
        self.assertFalse(handler._local_ok())
        handler.headers.replace_header("Host", "0.0.0.0:4553")
        self.assertFalse(handler._local_ok())

    def test_wildcard_bind_origin_check_rejects_cross_site(self) -> None:
        # A drive-by web page still cannot POST to a remotely-bound dashboard:
        # the Sec-Fetch-Site check stays in both modes.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "192.168.0.2:4553"
        handler.headers["Sec-Fetch-Site"] = "cross-site"
        handler.server = mock.Mock(bound_host="0.0.0.0", server_port=4553)
        self.assertFalse(handler._local_ok(allow_cross_site_navigation=True))

    @staticmethod
    def _non_loopback_ip() -> str | None:
        """The machine's primary non-loopback IPv4, or None if there is none."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            with contextlib.suppress(OSError):
                s.connect(("8.8.8.8", 80))
            ip = str(s.getsockname()[0])
            s.close()
            if ip not in ("127.0.0.1", "0.0.0.0"):
                return ip
        except OSError:
            pass
        return None

    def test_wildcard_bind_admits_a_remote_host_header_over_a_socket(self) -> None:
        # The Host gate end to end over a real socket, reached on loopback. A
        # 0.0.0.0 bind is listening on loopback too, so this needs no route back
        # to the machine and runs identically on all three CI platforms — the
        # sibling below covers the half only a real remote address can.
        # Reverting `_host_admitted` makes this 403. It says nothing about
        # whether `--host` reaches the bind tuple: this constructs the server
        # itself, and the launcher's own wiring is pinned in
        # `test_host_origin_dns_rebinding_and_request_limits_are_preserved`.
        with tempfile.TemporaryDirectory() as tmp:
            with store_patch(**dict.fromkeys(STORE_KEYS, tmp)):
                httpd = make_server(host="0.0.0.0")
            thread = threading.Thread(target=poll_fast(httpd), daemon=True)
            thread.start()
            try:
                port = httpd.server_port
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                conn.putrequest("GET", "/", skip_host=True)
                conn.putheader("Host", f"192.168.0.2:{port}")
                conn.endheaders()
                response = conn.getresponse()
                self.assertEqual(200, response.status)
                response.read()
                conn.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_wildcard_bind_serves_a_remote_host_header(self) -> None:
        # AC-1/AC-2: a server bound 0.0.0.0 accepts a connection to the
        # machine's non-loopback address and serves the page (200, not 403).
        # Constructing it on 127.0.0.1 instead makes the connection refused —
        # the launcher line that supplies the address is pinned in
        # `test_host_origin_dns_rebinding_and_request_limits_are_preserved`.
        #
        # The stores are redirected at an empty directory first, and not for
        # hygiene: without it this binds the developer's own dashboard, over
        # their real session stores, to every interface for the length of the
        # test.
        #
        # Two environment gates, both skips rather than failures, because each
        # is a property of the machine and not of the code: an address may not
        # exist at all, and the one that does may not be reachable back from
        # here — a host firewall, or a VPN whose address does not accept a
        # loopback-side connection. The hermetic sibling above still runs, so a
        # skip here does not leave the Host gate unexercised.
        ip = self._non_loopback_ip()
        if ip is None:
            self.skipTest("no non-loopback IPv4 address available")
        with tempfile.TemporaryDirectory() as tmp:
            with store_patch(**dict.fromkeys(STORE_KEYS, tmp)):
                httpd = make_server(host="0.0.0.0")
            thread = threading.Thread(target=poll_fast(httpd), daemon=True)
            thread.start()
            try:
                port = httpd.server_port
                try:
                    conn = http.client.HTTPConnection(ip, port, timeout=5)
                    conn.putrequest("GET", "/", skip_host=True)
                    conn.putheader("Host", f"{ip}:{port}")
                    conn.endheaders()
                    response = conn.getresponse()
                except OSError as exc:
                    self.skipTest(f"{ip}:{port} is not reachable from this host: {exc}")
                self.assertEqual(200, response.status)
                response.read()
                conn.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)

    def test_loopback_bind_refuses_a_non_loopback_connection(self) -> None:
        # AC-1: the default (no --host) refuses a connection to the machine's
        # non-loopback address (connection refused). Reverting the bind tuple
        # to ("0.0.0.0", args.port) makes this fail (connection succeeds).
        ip = self._non_loopback_ip()
        if ip is None:
            self.skipTest("no non-loopback IPv4 address available")
        httpd = make_server()  # default host 127.0.0.1
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            port = httpd.server_port
            refused = False
            try:
                conn = http.client.HTTPConnection(ip, port, timeout=2)
                conn.request("GET", "/")
                conn.getresponse()
                conn.close()
            except OSError:
                refused = True
            self.assertTrue(refused, "a loopback bind must refuse non-loopback connections")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


class ReviewFixTest(RuntimeTestCase):
    """Regressions found by the adversarial review passes on PR #7.

    `RuntimeTestCase` rather than a bare `TestCase`, because the origin cases
    below POST to `/api/notify`, whose accepted requests run the real notifier:
    the one that passed sent an audible banner to the machine running the suite
    (DRC-4431).
    """

    NOW = 1_700_000_000.0

    def test_a_page_on_another_local_port_cannot_post(self) -> None:
        # Every port on this machine is the same *site*, so Sec-Fetch-Site says
        # "same-site" for a page served from another local port. A hostname-only
        # Origin check trusted it, and text/plain is CORS-safelisted so no
        # preflight would have stopped the request.
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        port = httpd.server_port
        cases = [
            (f"http://127.0.0.1:{port}", 200, "the dashboard's own page"),
            (f"http://localhost:{port}", 200, "same port, other spelling"),
            ("http://localhost:9999", 403, "another local dev server"),
            ("http://127.0.0.1:9999", 403, "another local port"),
            ("http://localhost", 403, "port 80"),
            ("https://evil.example", 403, "remote origin"),
        ]
        try:
            for origin, expected, why in cases:
                with self.subTest(why=why):
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    conn.request(
                        "POST",
                        "/api/notify",
                        body=b'{"session_id":"aaaaaaaa"}',
                        headers={"Origin": origin, "Content-Type": "text/plain"},
                    )
                    response = conn.getresponse()
                    self.assertEqual(expected, response.status)
                    response.read()
                    conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def _options_requested(self, os_name: str, exclusive_option: int) -> list[int]:
        """Socket options the listener asks for under a given configured OS."""
        options: list[int] = []
        real_setsockopt = socket.socket.setsockopt

        def traced_setsockopt(sock: Any, level: int, option: int, value: Any) -> Any:
            options.append(option)
            return real_setsockopt(sock, level, option, value)

        with (
            mock.patch.object(socket.socket, "setsockopt", traced_setsockopt),
            mock.patch.object(socket, "SO_EXCLUSIVEADDRUSE", exclusive_option, create=True),
            # The fake option number is rejected by the OS, so that path warns;
            # silence it here.
            mock.patch.object(runtime_io, "diag"),
        ):
            httpd = make_server(application=_application(os_name))
            httpd.server_close()
        return options

    def test_reuse_and_exclusive_options_are_never_both_requested(self) -> None:
        # Winsock rejects SO_REUSEADDR on a socket that already carries
        # SO_EXCLUSIVEADDRUSE (WSAEINVAL 10022), so these are complements of one
        # decision, not independent switches. Taking reuse from the config while
        # taking exclusivity from the host's socket module set BOTH on a Windows
        # host running a posix-configured application, and every bind there died
        # — including the two-server and health-stamp contracts below, which say
        # nothing about ports and were failing on Windows for this reason alone.
        exclusive = 0xFFFB
        posix = self._options_requested("posix", exclusive)
        windows = self._options_requested("nt", exclusive)

        self.assertIn(socket.SO_REUSEADDR, posix)
        self.assertNotIn(exclusive, posix)

        self.assertIn(exclusive, windows)
        self.assertNotIn(socket.SO_REUSEADDR, windows)

    def test_exclusive_port_option_is_requested_before_bind(self) -> None:
        # Clearing SO_REUSEADDR stops Compass hijacking someone else's port;
        # SO_EXCLUSIVEADDRUSE is what stops anyone hijacking Compass's. Only
        # meaningful if it is applied before bind(). The config has to say "nt"
        # for the option to be in play at all, so the assertion holds on every
        # host rather than only on Windows runners.
        order: list[str] = []
        real_setsockopt = socket.socket.setsockopt
        real_bind = socket.socket.bind

        def traced_setsockopt(self: Any, level: int, option: int, value: Any) -> Any:
            order.append(f"setsockopt:{option}")
            return real_setsockopt(self, level, option, value)

        def traced_bind(self: Any, address: Any) -> Any:
            order.append("bind")
            return real_bind(self, address)

        with (
            mock.patch.object(socket.socket, "setsockopt", traced_setsockopt),
            mock.patch.object(socket.socket, "bind", traced_bind),
            mock.patch.object(socket, "SO_EXCLUSIVEADDRUSE", 0xFFFB, create=True),
            # The fake option number is rejected by the OS, so that path warns;
            # silence it here.
            mock.patch.object(runtime_io, "diag"),
        ):
            httpd = make_server(application=_application("nt"))
            httpd.server_close()

        self.assertIn("setsockopt:65531", order)
        self.assertEqual("bind", order[-1], "options must be set before bind()")
        self.assertLess(order.index("setsockopt:65531"), order.index("bind"))

    def test_shutdown_endpoint_answers_before_it_stops_the_server(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
            conn.request("POST", "/api/shutdown", body=b"", headers={"Content-Length": "0"})
            response = conn.getresponse()
            # This proves the client gets a 200 and that the server actually
            # stops (via the join/is_alive check below) — it does not pin how
            # shutdown is implemented, e.g. that it must run on its own thread.
            self.assertEqual(200, response.status)
            self.assertEqual(b'{"ok":true,"stopping":true}', response.read())
            conn.close()
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive(), "serve_forever did not return")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_shutdown_still_runs_when_the_client_drops_during_the_reply(self) -> None:
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = mock.Mock()
        handler.wfile = mock.Mock()
        stopped = threading.Event()
        handler.server.shutdown.side_effect = stopped.set
        with mock.patch.object(handler, "_send", side_effect=BrokenPipeError):
            handler._shutdown()
        self.assertTrue(stopped.wait(timeout=2), "the failed reply cancelled the shutdown")
        handler.server.shutdown.assert_called_once_with()

    def test_shutdown_endpoint_refuses_a_cross_site_post(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            conn.request(
                "POST",
                "/api/shutdown",
                body=b"",
                headers={"Content-Length": "0", "Sec-Fetch-Site": "cross-site"},
            )
            response = conn.getresponse()
            self.assertEqual(403, response.status)
            response.read()
            conn.close()
            # Still serving: a refused stop must not stop anything.
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=2)
            conn.request("GET", "/api/health")
            self.assertEqual(200, conn.getresponse().status)
            conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


class VerificationFixTest(unittest.TestCase):
    """Regressions found by the adversarial pass that tried to refute the fixes."""

    NOW = 1_700_000_000.0

    FUTURE = NOW + 86_400

    def test_origin_with_an_implicit_default_port(self) -> None:
        # Browsers omit the port when it is the scheme default, so
        # "http://localhost" is legitimate for a server on port 80.
        handler = http_api._RequestHandler.__new__(http_api._RequestHandler)
        handler.headers = email.message.Message()
        handler.headers["Host"] = "localhost"
        handler.headers["Origin"] = "http://localhost"
        handler.server = mock.Mock(server_port=80)
        self.assertTrue(handler._local_ok())
        handler.server = mock.Mock(server_port=4553)
        self.assertFalse(handler._local_ok())


class RejectedPostDrainTest(unittest.TestCase):
    """A refused POST has its body read before the refusal is written.

    Closing a socket that still holds unread inbound data makes the OS send RST
    rather than FIN, and an RST can discard the reply already written, so the
    client sees ECONNRESET (WSAECONNABORTED on Windows) instead of the 413 it was
    told to expect. That is what failed on the macOS and Windows runners.

    Asserted at the handler rather than through a socket, deliberately. A
    socket-level version of this passes on this machine whether or not the drain
    is there, because the race needs buffer and scheduling conditions a local run
    does not reproduce: it would be a test that cannot fail. Reading the body
    before answering is the behaviour being added, so that is what is pinned.
    """

    class _Handler(http_api._RequestHandler):
        def __init__(self, declared: str, available: bytes) -> None:
            # Headers is an email.message.Message on the real handler; a dict
            # answers the only call the drain makes of it.
            self.headers = email.message.Message()
            self.headers["Content-Length"] = declared
            self.rfile = io.BytesIO(available)
            self.sent: list[int] = []

        def send_error(
            self, code: int, message: str | None = None, explain: str | None = None
        ) -> None:
            # Records the order: the drain has to have happened by now.
            del message, explain
            self.sent.append(code)

    def _reject(self, declared: str, available: bytes) -> tuple[list[int], int]:
        handler = self._Handler(declared, available)
        handler._reject(413)
        return handler.sent, handler.rfile.tell()

    def test_the_declared_body_is_consumed_before_the_error_is_sent(self) -> None:
        sent, consumed = self._reject("2048", b"a" * 2048)
        self.assertEqual([413], sent)
        self.assertEqual(2048, consumed, "the body must be read, or the close sends RST")

    def test_an_oversized_declared_length_is_drained_only_to_the_bound(self) -> None:
        """Bounded: a refusal must not become an unbounded read."""
        cap = http_api._RequestHandler.REJECT_DRAIN_CAP_BYTES
        sent, consumed = self._reject(str(cap * 4), b"b" * (cap + 100))
        self.assertEqual([413], sent)
        self.assertEqual(cap, consumed, "never more than the bound, whatever is declared")

    def test_a_body_shorter_than_declared_does_not_hang(self) -> None:
        """A peer that declares more than it sends must not block the handler.

        BytesIO reports end of stream immediately; a real socket blocks instead,
        which is why the drain is also bounded by a deadline. The socket case is
        covered by test_a_declared_body_never_sent_does_not_stall below.
        """
        sent, consumed = self._reject("100000", b"c" * 10)
        self.assertEqual([413], sent)
        self.assertEqual(10, consumed)

    def test_a_missing_or_unparseable_length_reads_nothing(self) -> None:
        for declared in ("", "not-a-number"):
            with self.subTest(declared=declared):
                sent, consumed = self._reject(declared, b"d" * 50)
                self.assertEqual([413], sent)
                self.assertEqual(0, consumed)

    def test_a_declared_body_never_sent_does_not_stall(self) -> None:
        """The bug my first fix introduced, over a real socket.

        A peer that declares a length and sends nothing made the drain block on
        read1 until the connection timeout, which turned a refusal into a
        five-second hang. A request-limit test sends exactly that shape on
        purpose, so this is a real caller and not a hypothetical one.
        """
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            started = time.monotonic()
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            try:
                # Declare a body, send none: putrequest/endheaders without a send.
                conn.putrequest("POST", "/api/notify")
                # Above notification_body_cap_bytes, so this takes the rejection
                # path. A declared length UNDER the cap is a different case: the
                # accept path reads it and blocks, which is pre-existing
                # behaviour and not what this test is about.
                conn.putheader("Content-Length", "200000")
                conn.putheader("Content-Type", "application/json")
                conn.endheaders()
                response = conn.getresponse()
                self.assertEqual(413, response.status)
                response.read()
            finally:
                conn.close()
            elapsed = time.monotonic() - started
            self.assertLess(
                elapsed,
                3.0,
                f"a refusal must not wait out the connection timeout, took {elapsed:.1f}s",
            )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_a_body_already_read_is_not_drained_a_second_time(self) -> None:
        """The drain is for a peer still mid-write, not for one already read.

        Every validation refusal reads the whole body first and only then decides
        to reject. Re-reading Content-Length bytes that are already gone leaves
        `read1` blocking on a peer with nothing left to send, so the refusal
        waits out REJECT_DRAIN_SECONDS.
        """
        handler = self._Handler("2048", b"a" * 2048)
        self.assertEqual(2048, len(handler._read_body(2048)))
        # The attempt is what matters, not the result. BytesIO answers a read
        # past the end immediately; a socket blocks there until the deadline,
        # which is the whole cost. Counting calls catches it either way.
        reads = 0
        original = handler.rfile.read1

        def counting_read1(size: int = -1) -> bytes:
            nonlocal reads
            reads += 1
            return original(size)

        handler.rfile.read1 = counting_read1  # type: ignore[method-assign]
        handler._reject(400)
        self.assertEqual([400], handler.sent)
        self.assertEqual(0, reads, "the drain went back to a body already consumed")

    def test_a_validation_refusal_answers_without_waiting_out_the_drain(self) -> None:
        """The same thing over a real socket, where the cost was measured.

        A POST whose body is fully sent and fully read, then refused on its
        contents, took the whole 250ms drain deadline on the shipped /api/ask
        route — per request, on the handler thread.
        """
        # The shipped 250 ms drain was also the bound, so a healthy request had to
        # finish its whole loopback round trip inside it, on a Windows runner
        # measured at 0.47 s per loopback request (DRC-4648). A re-drain costs at
        # least the drain, so a 3 s drain with half of it as the bound leaves 3x
        # that round trip and 1.5 s between a healthy refusal and the defect.
        drain = mock.patch.object(http_api._RequestHandler, "REJECT_DRAIN_SECONDS", 3.0)
        drain.start()
        self.addCleanup(drain.stop)
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            port = httpd.server_port
            # A non-string question: read in full, then refused as unusable.
            body = json.dumps(
                {"harness": "claude", "session_id": "aaa1", "project": "p", "question": 42}
            ).encode()
            started = time.monotonic()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                conn.request("POST", "/api/ask", body=body, headers={"Content-Type": "text/plain"})
                response = conn.getresponse()
                self.assertEqual(400, response.status)
                response.read()
            finally:
                conn.close()
            elapsed = time.monotonic() - started
            self.assertLess(
                elapsed,
                http_api._RequestHandler.REJECT_DRAIN_SECONDS / 2,
                f"the refusal waited out the drain deadline, took {elapsed:.3f}s",
            )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_every_post_rejection_path_drains(self) -> None:
        """The whole class of bug, not the one instance that was reported."""
        source = Path(http_api.__file__).read_text(encoding="utf-8")
        post_region = source[source.index("    def _usage_receipt") :]
        self.assertNotIn(
            "self.send_error(",
            post_region,
            "a POST path answering with send_error instead of _reject will strand its peer",
        )


class StreamEndpointTest(RuntimeTestCase):
    """The SSE contract: immediate state, then one event per revision.

    Every socket read carries a timeout. A blocking read with no deadline turns
    a Windows CI failure into a hang, which reads as infrastructure trouble
    rather than as the bug it is.
    """

    @staticmethod
    def _open(port: int, headers: dict[str, str] | None = None) -> Any:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/stream", headers=headers or {})
        return conn, conn.getresponse()

    @staticmethod
    def _read_event(response: Any, *, limit: int = 4096) -> str:
        """Read until a blank line terminates one SSE frame, or the peer ends."""
        chunks: list[bytes] = []
        while len(b"".join(chunks)) < limit:
            byte = response.read(1)
            if not byte:
                break
            chunks.append(byte)
            if b"".join(chunks).endswith(b"\n\n"):
                break
        return b"".join(chunks).decode()

    def test_the_stream_opens_as_an_event_stream(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn, response = self._open(httpd.server_port)
            try:
                self.assertEqual(200, response.status)
                self.assertEqual("text/event-stream", response.headers["Content-Type"])
                self.assertEqual("no-store", response.headers["Cache-Control"])
            finally:
                conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_the_current_revision_arrives_immediately(self) -> None:
        """A client must not wait for the next change to learn where it is."""
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            # Publish something first, so there is a current revision to send.
            httpd.application.collect_json(show_all=False)
            conn, response = self._open(httpd.server_port)
            try:
                frame = self._read_event(response)
                self.assertIn("event: revision", frame)
                self.assertRegex(frame, r"data: \d+\.\d+")
            finally:
                conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_a_new_revision_is_delivered_to_an_open_stream(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            httpd.application.collect_json(show_all=False)
            conn, response = self._open(httpd.server_port)
            try:
                first = self._read_event(response)
                # Force a genuinely new revision, then read the next frame.
                state_of().snapshot.clear()
                httpd.application.collect_json(show_all=False)
                second = self._read_event(response)
                self.assertIn("event: revision", second)
                self.assertNotEqual(first, second)
            finally:
                conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_a_cross_site_request_is_refused_unlike_api_data(self) -> None:
        """A long-lived data stream is not a document navigation.

        do_GET relaxes its origin check so a link to the dashboard works. This
        route must re-check with the strict form, or that relaxation leaks onto
        a stream any site could open.
        """
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn, response = self._open(
                httpd.server_port,
                {
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                },
            )
            try:
                self.assertEqual(403, response.status)
                response.read()
            finally:
                conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_the_budget_refuses_past_the_cap(self) -> None:
        """A refusal, not a queue: every stream costs a thread and a socket."""
        httpd = make_server()
        httpd.application.config = dataclasses.replace(
            httpd.application.config, stream_max_clients=1
        )
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            first_conn, first = self._open(httpd.server_port)
            try:
                self.assertEqual(200, first.status)
                second_conn, second = self._open(httpd.server_port)
                try:
                    self.assertEqual(503, second.status)
                    second.read()
                finally:
                    second_conn.close()
            finally:
                first_conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


class StreamShutdownTest(RuntimeTestCase):
    """A stream asleep in wait() has to be woken, or shutdown looks like a hang.

    server.shutdown() stops the accept loop and never touches handler threads,
    and daemon_threads means nothing joins them, so nothing else would tell a
    sleeping stream to stop.
    """

    def test_shutdown_closes_an_open_stream_promptly(self) -> None:
        httpd = make_server()
        # A heartbeat far longer than the assertion window, so a pass cannot be
        # the heartbeat firing rather than the close.
        httpd.application.config = dataclasses.replace(
            httpd.application.config, stream_heartbeat_sec=60.0
        )
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            conn.request("GET", "/api/stream")
            response = conn.getresponse()
            self.assertEqual(200, response.status)
            ended = threading.Event()

            def drain() -> None:
                while response.read(1):
                    pass
                ended.set()

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            httpd.application.state.streams.close_all()
            self.assertTrue(
                ended.wait(timeout=5.0),
                "an open stream must end when the registry closes it",
            )
            conn.close()
            reader.join(timeout=2)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_the_shutdown_endpoint_closes_streams_before_stopping(self) -> None:
        httpd = make_server()
        httpd.application.config = dataclasses.replace(
            httpd.application.config, stream_heartbeat_sec=60.0
        )
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            stream_conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            stream_conn.request("GET", "/api/stream")
            stream_response = stream_conn.getresponse()
            self.assertEqual(200, stream_response.status)
            ended = threading.Event()

            def drain() -> None:
                while stream_response.read(1):
                    pass
                ended.set()

            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            stop_conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            stop_conn.request("POST", "/api/shutdown", body=b"")
            stop_conn.getresponse().read()
            stop_conn.close()
            self.assertTrue(
                ended.wait(timeout=5.0),
                "POST /api/shutdown must wake open streams, not leave them asleep",
            )
            stream_conn.close()
            reader.join(timeout=2)
        finally:
            with contextlib.suppress(Exception):
                httpd.server_close()
            thread.join(timeout=2)


class InstalledContractCharacterizationTest(unittest.TestCase):
    """The installed executable contract that extraction must preserve."""

    def setUp(self) -> None:
        with state_of().hook_lock:
            state_of().hook_notifications.clear()
            state_of().last_popup.clear()
            state_of().last_popup_message.clear()
            state_of().last_session_state.clear()
            state_of().hook_generation.clear()
        with state_of().collect_memo_lock:
            state_of().snapshot.clear()
        # Route-shape tests exercise successful /api/notify requests, but do
        # not assert native delivery. Execute the notification code while
        # keeping its osascript process off the host.
        short_circuit_native_notifications(self)

    def tearDown(self) -> None:
        with state_of().collect_memo_lock:
            state_of().snapshot.clear()

    @staticmethod
    def _response(
        port: int,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, email.message.Message, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def test_http_routes_pin_status_content_type_and_response_shapes(self) -> None:
        httpd = make_server()
        thread = serve_until_closed(httpd)
        # Patched on the application, which is what the handler collects through.
        with mock.patch.object(
            aggregate.Application,
            "collect_json",
            # (revision, body): the handler names the revision it served in a
            # header, so the stub has to carry one too.
            return_value=(
                (1.0, 1),
                json.dumps({"generated": 1.0, "sessions": [], "harnesses": []}).encode(),
            ),
        ):
            try:
                cases = (
                    ("GET", "/", None, 200, "text/html; charset=utf-8", None),
                    (
                        "GET",
                        "/api/data",
                        None,
                        200,
                        "application/json",
                        {"generated", "sessions", "harnesses"},
                    ),
                    (
                        "GET",
                        "/api/health",
                        None,
                        200,
                        "application/json",
                        {"ok", "pid", "port", "started"},
                    ),
                    (
                        "POST",
                        "/api/notify",
                        b'{"session_id":"12345678"}',
                        200,
                        "application/json",
                        {"ok"},
                    ),
                    ("GET", "/missing", None, 404, "text/html;charset=utf-8", None),
                    (
                        "GET",
                        "/fonts/space-grotesk-v22-latin.woff2",
                        None,
                        404,
                        "text/html;charset=utf-8",
                        None,
                    ),
                )
                for method, path, body, status, ctype, keys in cases:
                    with self.subTest(path=path):
                        code, headers, received = self._response(
                            httpd.server_port, method, path, body
                        )
                        self.assertEqual(status, code)
                        self.assertEqual(ctype, headers["Content-Type"])
                        if status == 404:
                            self.assertIsNone(headers.get("Cache-Control"))
                        else:
                            self.assertEqual("no-store", headers["Cache-Control"])
                        if path == "/":
                            self.assertEqual(PAGE_BYTES, received)
                        if keys is not None:
                            self.assertEqual(keys, set(json.loads(received)))
                code, headers, received = self._response(
                    httpd.server_port, "POST", "/api/shutdown", b""
                )
                self.assertEqual(200, code)
                self.assertEqual("application/json", headers["Content-Type"])
                self.assertEqual("no-store", headers["Cache-Control"])
                self.assertEqual({"ok", "stopping"}, set(json.loads(received)))
            finally:
                httpd.shutdown()
                thread.join(timeout=5)

    def test_host_origin_dns_rebinding_and_request_limits_are_preserved(self) -> None:
        captured_addresses: list[tuple[str, int]] = []
        captured_pages: list[bytes] = []

        class StopServingError(Exception):
            pass

        class CapturingServer:
            def __init__(
                self,
                address: tuple[str, int],
                _application: Any,
                page_bytes: bytes,
                _observation: Any = None,
                *,
                interaction_prototype: Any = None,
            ) -> None:
                # The coordinator and optional page ride along with the address
                # and required page. Accepted and ignored here: this test
                # characterizes the bind address and the required page bytes,
                # and a double that refused either would fail for an unrelated
                # reason.
                del interaction_prototype
                captured_addresses.append(address)
                captured_pages.append(page_bytes)

            def serve_forever(self) -> None:
                raise StopServingError

            def server_close(self) -> None:
                pass

        def serve(*argv: str) -> None:
            with (
                mock.patch.object(sys, "argv", ["server.py", *argv]),
                mock.patch.object(http_api, "CompassHTTPServer", CapturingServer),
                mock.patch.object(lifecycle, "write_state"),
                mock.patch.object(lifecycle, "remove_state"),
                # The real one closes this worker's runner for every later test.
                mock.patch.object(runtime_supervise, "kill_all"),
                mock.patch.object(runtime_io, "diag"),
                self.assertRaises(StopServingError),
            ):
                cli.main()

        # The shipped launcher, rather than this test's fixture, owns the
        # required bind address. Capture the constructor call from main() so a
        # regression to 0.0.0.0 cannot pass merely because this test chose 127.
        serve("--port", "4553")
        self.assertEqual([("127.0.0.1", 4553)], captured_addresses)
        # The verified page plus this run's focus capability, which `cli.main`
        # injects between `load_frontend_page()` and this constructor. Compared
        # against the loaded page rather than against a pinned byte count, so the
        # subject stays the bind address and the page identity: `react.integrity.json`
        # owns the digest, and a second pin here would red this module on any
        # frontend edit.
        default_page = frontend_page.load_frontend_page()
        self.assertEqual(1, len(captured_pages))
        served = captured_pages[0]
        self.assertEqual(default_page, without_focus_meta(served))
        self.assertIn(b'<meta name="compass-focus" content="', served)

        # And the other direction, through the same launcher: `--host` has to
        # reach the bind tuple. Nothing pinned that, so reverting cli.py's
        # `(args.host, args.port)` to the literal left every --host test green —
        # they all construct the server themselves and never go through main().
        captured_addresses.clear()
        captured_pages.clear()
        serve("--port", "4553", "--host", "0.0.0.0")
        self.assertEqual([("0.0.0.0", 4553)], captured_addresses)

        # And with the feature off there is no secret in the served bytes at all,
        # which is the whole of "the control does not render".
        captured_addresses.clear()
        captured_pages.clear()
        serve("--port", "4553", "--no-focus")
        self.assertEqual([default_page], captured_pages)
        captured_addresses.clear()
        captured_pages.clear()
        serve("--port", "4553", "--no-events")
        self.assertEqual([default_page], captured_pages)

        httpd = make_server()
        thread = serve_until_closed(httpd)
        try:
            port = httpd.server_port
            code, _, _ = self._response(
                port, "GET", "/api/health", headers={"Host": "evil.example"}
            )
            self.assertEqual(403, code)
            code, _, _ = self._response(
                port,
                "POST",
                "/api/notify",
                b"{}",
                {"Origin": "https://evil.example", "Content-Type": "application/json"},
            )
            self.assertEqual(403, code)
            code, _, _ = self._response(
                port,
                "POST",
                "/api/notify",
                b"{}",
                {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json"},
            )
            self.assertEqual(200, code)
            code, _, _ = self._response(
                port, "POST", "/api/notify", b"x", {"Content-Length": "65537"}
            )
            self.assertEqual(413, code)
            code, _, _ = self._response(
                port, "POST", "/api/notify", b"x", {"Content-Length": "not-a-number"}
            )
            self.assertEqual(413, code)
            code, _, _ = self._response(
                port,
                "GET",
                "/",
                headers={
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Dest": "document",
                },
            )
            self.assertEqual(200, code)
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    def test_health_performs_no_harness_store_reads(self) -> None:
        httpd = make_server()
        thread = serve_until_closed(httpd)
        try:
            # These are the store-access primitives used by collectors. Health
            # must remain a pure liveness response even if somebody bypasses
            # collect() and later reaches into a harness store directly.
            with (
                mock.patch.object(aggregate.Application, "collect") as collect,
                mock.patch("builtins.open", side_effect=AssertionError("health read a file")),
                mock.patch.object(
                    os,
                    "scandir",
                    side_effect=AssertionError("health scanned a directory"),
                ),
                mock.patch(
                    "compass_runtime.io.glob.glob",
                    side_effect=AssertionError("health globbed a store"),
                ),
                mock.patch.object(
                    runtime_io.sqlite_module,
                    "connect",
                    side_effect=AssertionError("health opened SQLite"),
                ),
            ):
                code, _, body = self._response(httpd.server_port, "GET", "/api/health")
            self.assertEqual(200, code)
            self.assertTrue(json.loads(body)["ok"])
            collect.assert_not_called()
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    def test_collection_memo_holds_its_lock_across_one_scan(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        second_done = threading.Event()
        bodies: list[bytes] = []

        def scan(*_: Any, **__: Any) -> dict[str, Any]:
            entered.set()
            self.assertTrue(release.wait(timeout=5), "test did not release the scan")
            return {"generated": 1.0, "sessions": [], "harnesses": []}

        def second_request() -> None:
            bodies.append(collect_json(24, False))
            second_done.set()

        with mock.patch.object(aggregate.Application, "collect", side_effect=scan) as collect:
            first = threading.Thread(target=lambda: bodies.append(collect_json(24, False)))
            second = threading.Thread(target=second_request)
            first.start()
            self.assertTrue(entered.wait(timeout=5), "first scan did not begin")
            second.start()
            self.assertFalse(second_done.wait(timeout=0.2), "second request scanned concurrently")
            release.set()
            first.join(timeout=5)
            second.join(timeout=5)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(1, collect.call_count)
        self.assertEqual(2, len(bodies))
        self.assertEqual(bodies[0], bodies[1])

    def test_collection_memo_releases_its_lock_after_failure(self) -> None:
        good = {"generated": 1.0, "sessions": [], "harnesses": []}
        with mock.patch.object(
            aggregate.Application, "collect", side_effect=(RuntimeError("broken store"), good)
        ):
            with self.assertRaisesRegex(RuntimeError, "broken store"):
                collect_json(24, False)
            self.assertEqual(good, json.loads(collect_json(24, False)))


class ReadingRouteTest(unittest.TestCase):
    """POST /api/reading over a real socket, and what it refuses to spend.

    Its own class rather than a home in `AnnotateRouteTest`: that one builds
    an annotations-only application with no observer model, so a reading test
    placed there would answer 503 forever and read as a pass.

    Every refusal asserts the status AND that the model was never invoked.
    The second half is the load-bearing one. A gate that answers 503 after
    spending the reader's own capacity has not held, and a status code alone
    cannot tell those apart.
    """

    def _runtime(self, **changes: Any) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        # An open runner: a `serve` run earlier in this worker closes it.
        patcher = mock.patch.object(runtime_supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        changes.setdefault("annotations_enabled", True)
        changes.setdefault("observer_model_enabled", True)
        config, state = make_runtime(state_home=home, state_dir=Path(home), **changes)
        reading_policy.set_consent(config, True, now=1_700_000_100.0)
        return config, state

    def test_fresh_press_runs_with_notice_then_off_blocks_until_resume(self) -> None:
        config, state = self._runtime()
        reading_policy.store_path(config).unlink()
        application = self._app(config, state)
        with self._counting_model() as calls, self._serving(application) as port:
            _, board = application.collect_json(show_all=False)
            self.assertTrue(json.loads(board)["reading_routes"]["pi"]["notice_due"])
            status, body = self._post(port, self._press())
            self.assertEqual(202, status, body)
            answer = json.loads(body)
            self.assertEqual("reading", answer["notice"]["kind"])
            self.assertEqual("codex", answer["notice"]["provider"])
            self.assertEqual(answer["notice"], answer["job"]["notice"])
            _, board = application.collect_json(show_all=False)
            self.assertFalse(json.loads(board)["reading_routes"]["pi"]["notice_due"])
            self.assertEqual(
                answer["notice"], json.loads(board)["reading"]["notices"]["reading"]["codex"]
            )
            status, body = self._post(port, self._press())
            self.assertEqual(202, status, body)
            self.assertNotIn("notice", json.loads(body))
            self._post(port, {"consent": "off", "press": True, "observer_model": 1})
            status, body = self._post(port, self._press())
            self.assertEqual(403, status, body)
            self.assertEqual("model-calls-paused", json.loads(body)["reading"]["reason"])
            self.assertFalse(json.loads(body)["reading"]["consent"])
            self.assertEqual(2, len(calls))
            # An Allow from an older page or a local client lifts nothing: only Resume model
            # calls does, and neither grants the unasked lane (owner, 2026-10-19).
            status, body = self._post(port, self._press(allow=True, words_destination=""))
            self.assertEqual(403, status, body)
            self.assertEqual("model-calls-paused", json.loads(body)["reading"]["reason"])
            self.assertEqual(2, len(calls))
            self.assertEqual(
                {"codex": False, "claude": False},
                reading_policy.status(config, now=1_700_000_100.0)["providers"],
            )
            status, _ = self._post(port, {"consent": "on", "press": True, "observer_model": 1})
            self.assertEqual(200, status)
            status, body = self._post(port, self._press(allow=True, words_destination=""))
            self.assertEqual(202, status, body)
            self.assertIn("notice", json.loads(body))
            self.assertEqual(3, len(calls))
            self.assertEqual(
                {"codex": False, "claude": False},
                reading_policy.status(config, now=1_700_000_100.0)["providers"],
            )

    def test_stored_off_requires_resume_then_checks_without_startup_opt_in(self) -> None:
        config, state = self._runtime(observer_model_enabled=False)
        reading_policy.set_consent(config, False, now=1_700_000_100.0)
        with self._counting_model() as calls, self._serving(self._app(config, state)) as port:
            status, _ = self._post(port, self._press())
            self.assertEqual(403, status)
            self.assertEqual([], calls)
            status, _ = self._post(port, self._press(allow=True, words_destination=""))
            self.assertEqual(403, status)
            self.assertEqual([], calls)
            status, _ = self._post(port, {"consent": "on", "press": True, "observer_model": 1})
            self.assertEqual(200, status)
            status, _ = self._post(port, self._press())
            self.assertEqual(202, status)
            self.assertEqual(1, len(calls))
            status, _ = self._post(port, self._press())
            self.assertEqual(202, status)
            self.assertEqual(2, len(calls))
            status, _ = self._post(port, {"consent": "off", "press": True, "observer_model": 1})
            self.assertEqual(200, status)
            status, _ = self._post(port, self._press())
            self.assertEqual(403, status)
            self.assertEqual(2, len(calls))

    def test_lured_requests_cannot_change_remembered_permission(self) -> None:
        config, state = self._runtime()
        resume = {"consent": "on", "press": True, "observer_model": 1}
        for granted, body in (
            (False, self._press(allow=True, words_destination="")),
            (False, resume),
            (True, {"consent": "off", "press": True, "observer_model": 1}),
        ):
            reading_policy.set_consent(config, granted, now=1_700_000_100.0)
            with self._counting_model() as calls, self._serving(self._app(config, state)) as port:
                for headers in (
                    {"Sec-Fetch-Site": "same-site"},
                    {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                ):
                    status, _ = self._post(port, body, headers=headers)
                    self.assertEqual(403, status)
                    stored = reading_policy.status(config, now=1_700_000_100.0)
                    self.assertEqual(granted, stored["consent"])
                    self.assertEqual(not granted, stored["off"])
                self.assertEqual([], calls)

    def test_daily_limit_refuses_before_call_and_reports_the_release_time(self) -> None:
        config, state = self._runtime()
        with self._counting_model() as calls, self._serving(self._app(config, state)) as port:
            for _ in range(reading_policy.DAILY_CAP):
                status, _ = self._post(port, self._press(allow=True, words_destination=""))
                self.assertEqual(202, status)
            status, body = self._post(port, self._press(allow=True, words_destination=""))
        self.assertEqual(429, status)
        self.assertEqual(reading_policy.DAILY_CAP, len(calls))
        self.assertEqual(1_700_086_500.0, json.loads(body)["reading"]["retry_at"])

    @staticmethod
    def _one_session_harness(harness: str = "pi", *, aged: bool = False, **row_over: Any) -> Any:
        """A harness publishing exactly the row the route looks for.

        Without it the application collects nothing, `_send_reading` returns at
        its no-rows arm BEFORE it claims the slot or reaches the model, and
        every "the model was never invoked" assertion in this class passes no
        matter what the gate does. That is how the first version of this class
        certified a safety property it could not observe.
        """

        def collect(
            config: Any, state: Any, now: float, window_hours: float, show_all: bool
        ) -> list[dict[str, Any]]:
            # Positional, because `Application.collect` calls it positionally.
            # A keyword-only signature raises inside the failure boundary,
            # which swallows it and yields no rows -- and no rows is exactly
            # the state that made this class unfalsifiable.
            del config, state, now, window_hours
            # An aged session is outside the normal window, as Claude's
            # collector leaves one out unless the reader asked for all.
            if aged and not show_all:
                return []
            row = runtime_sessions.base_session(harness, "s1", "proj")
            row.update({"state": "working", "active": True, "last_activity": 1_700_000_000.0})
            row.update(row_over)
            return [row]

        return aggregate.HarnessSpec(
            key=harness, label=harness.title(), discover=lambda *_: True, collect=collect
        )

    def _app(
        self,
        config: Any,
        state: Any,
        harness: str = "pi",
        row: dict[str, Any] | None = None,
        *,
        aged: bool = False,
    ) -> Any:
        """An application over that one session, with an annotation on it."""
        annotation_store.annotate(
            config, state, harness, "s1", goal="ship the parser", output="", now=10.0
        )
        return aggregate.Application(
            config,
            state,
            (self._one_session_harness(harness, aged=aged, **(row or {})),),
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _b: None,
            diagnostic_sink=lambda _m: None,
            clock=lambda: 1_700_000_100.0,
        )

    @contextlib.contextmanager
    def _serving(self, application: Any) -> Any:
        """The route over a socket, with every outcome a job writes recorded."""
        self.outcomes: list[dict[str, Any]] = []
        record_reading = annotation_store.record_reading
        record_withheld = annotation_store.record_withheld

        def reading_written(*args: Any, **kwargs: Any) -> Any:
            self.outcomes.append({"produced": True, "reason": ""})
            return record_reading(*args, **kwargs)

        def withheld_written(*args: Any, **kwargs: Any) -> Any:
            self.outcomes.append(
                {"produced": False, "reason": kwargs["reason"], "spent": kwargs["spent"]}
            )
            return record_withheld(*args, **kwargs)

        httpd = make_server(application=application)
        thread = serve_until_closed(httpd)
        try:
            with (
                mock.patch.object(annotation_store, "record_reading", reading_written),
                mock.patch.object(annotation_store, "record_withheld", withheld_written),
            ):
                yield httpd.server_port
                self._settle()
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    def _post(
        self,
        port: int,
        payload: Any,
        *,
        settle: bool = True,
        headers: dict[str, str] | None = None,
        path: str = "/api/reading",
    ) -> tuple[int, bytes]:
        """One press. A press that started a job is waited out unless told not to.

        The reading runs after the reply now (DRC-4686), so a test asserting
        what the press did must wait for the job, and `self.outcomes` holds
        what each finished job wrote.
        """
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST",
                path,
                body=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            response = conn.getresponse()
            status, body = response.status, response.read()
        finally:
            conn.close()
        if settle and status == 202:
            self._settle()
        return status, body

    # One entry naming the fixture session, so the ledger is never the reason
    # the model is not reached. Without it `produce` returns `ledger-empty`
    # ahead of the subprocess on EVERY path, and "the model was never invoked"
    # is true whatever the gate does -- the second way this class was
    # unfalsifiable, after the no-rows arm.
    FACT: ClassVar[dict[str, Any]] = {
        "fact_id": "f1",
        "type": "user_message",
        "by": "",
        "summary": "ship the parser please",
        "at": 1_700_000_000.0,
        "evidence": {"source": "root transcript", "confidence": "exact"},
        "source_session": {"harness": "pi", "sid": "s1"},
    }

    @contextlib.contextmanager
    def _counting_model(
        self,
        installed: tuple[str, ...] = ("codex",),
        *,
        status: str = "ok",
        launch_finds: tuple[str, ...] | None = None,
        harness: str = "pi",
        destination: str = "",
        extra_facts: tuple[dict[str, Any], ...] = (),
        tails: dict[str, str] | None = None,
        on_collect: Any = None,
    ) -> Any:
        """A model per provider that records every invocation and runs no subprocess.

        Also supplies the observed record, because a gate is only proven by a
        non-invocation when an invocation was otherwise going to happen, and
        the machine: `installed` is what the route resolver finds on PATH, and
        `launch_finds` what each model finds at launch (the same, by default).
        Every call lands in `calls`; `self.providers` says whose each one was.

        `destination` is what the route names for tool output on this machine,
        "" (cannot be named) unless a test says otherwise, so no real
        environment or managed setting decides a test. `extra_facts` and
        `tails` are the session's checks and what the press reads of them.
        """
        calls: list[str] = []
        self.providers: list[str] = []
        found = installed if launch_finds is None else launch_finds

        def model(provider: str) -> Any:
            class _Model:
                def __init__(self, _config: Any, **_kw: Any) -> None:
                    pass

                def __call__(self, prompt: str, **_kw: Any) -> tuple[str, str]:
                    calls.append(prompt)
                    outer.providers.append(provider)
                    return "{}", status

                def available(self) -> bool:
                    return provider in found

                unavailable_reason = (
                    runtime_reading.WITHHELD_CLAUDE_UNAVAILABLE
                    if provider == "claude"
                    else runtime_reading.WITHHELD_MODEL_UNAVAILABLE
                )

            return _Model

        outer = self
        with (
            mock.patch.object(runtime_reading, "CodexReadingModel", model("codex")),
            mock.patch.object(runtime_reading, "ClaudeReadingModel", model("claude")),
            mock.patch.object(
                shutil,
                "which",
                lambda name: f"/usr/local/bin/{name}" if name in installed else None,
            ),
            mock.patch.object(
                runtime_project_context,
                "collect",
                lambda *_a, **_k: (
                    (on_collect() if on_collect else None)
                    or {
                        "semantic": {
                            "facts": [
                                {**self.FACT, "source_session": {"harness": harness, "sid": "s1"}},
                                *extra_facts,
                            ]
                        }
                    }
                ),
            ),
            mock.patch.object(runtime_reading_route, "destination", lambda *_a, **_k: destination),
            mock.patch.object(
                runtime_project_context,
                "press_checks",
                lambda *_a, **_k: runtime_project_context.PressChecks(
                    dict(tails or {}), frozenset()
                ),
            ),
        ):
            yield calls

    def _press(self, **over: Any) -> dict[str, Any]:
        body = {
            "harness": "pi",
            "sid": "s1",
            "press": True,
            "observer_model": 1,
            "provider": "codex",
        }
        body.update(over)
        if body["provider"] == "claude":
            body.setdefault("model", runtime_observer.CLAUDE_READING_MODEL)
        return body

    def test_a_reader_pressing_while_the_check_has_not_run_spends_nothing(self) -> None:
        """The condition on enabling, asserted where a curl would try it."""
        config, state = self._runtime()
        with (
            mock.patch.object(annotation_store, "ABSTENTION_CHECK", "not-run"),
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, _ = self._post(port, self._press())
        self.assertEqual(503, status)
        self.assertEqual([], calls, "the model ran behind a closed gate")

    def test_a_press_reads_every_outcome_line_the_reader_typed(self) -> None:
        """DRC-4685: the reading route is the one caller that reads the lines.

        `produce` defaults to the goal alone, which is the unasked lane's guard,
        so the route's own `read_lines=True` is the half that must be bound here.
        """
        config, state = self._runtime()
        application = self._app(config, state)
        annotation_store.annotate(
            config,
            state,
            "pi",
            "s1",
            lines=["the parser rejects bad input", "a regression test covers it"],
            expected_revision=1,
            now=11.0,
        )
        work = {
            **self.FACT,
            "fact_id": "w1",
            "type": "work_result",
            "summary": "wrote the parser",
            "by": "agent",
        }
        with (
            self._counting_model(extra_facts=(work,)) as calls,
            self._serving(application) as port,
        ):
            status, _ = self._post(port, self._press())
        self.assertEqual(202, status)
        self.assertEqual(1, len(calls))
        self.assertIn('<outcome_line n="1">', calls[0])
        self.assertIn('<outcome_line n="2">', calls[0])
        entry = annotation_store.find(annotation_store.load(config), "pi", "s1")
        assert entry is not None
        self.assertEqual({"goal", "line_1", "line_2"}, set(entry["assessment"]["criteria"]))

    def test_the_accepted_case_review_allows_one_explicit_reading(self) -> None:
        self.assertEqual("accepted", annotation_store.ABSTENTION_CHECK)
        config, state = self._runtime()
        with (
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, _ = self._post(port, self._press())
        self.assertEqual(202, status)
        self.assertEqual(1, len(calls))

    def test_every_closed_gate_refuses_before_the_model_is_reached(self) -> None:
        cases: tuple[tuple[str, dict[str, Any], dict[str, Any], int], ...] = (
            ("annotations off", {"annotations_enabled": False}, {}, 503),
            ("model off", {"model_calls_disabled": True}, {}, 503),
            ("no disclosure echo", {}, {"observer_model": 0}, 400),
            ("no press", {}, {"press": False}, 400),
            ("press absent", {}, {"press": None}, 400),
            ("no harness", {}, {"harness": ""}, 400),
            ("no sid", {}, {"sid": ""}, 400),
            ("harness not a string", {}, {"harness": 7}, 400),
        )
        for label, runtime_changes, body_changes, expected in cases:
            with self.subTest(gate=label):
                config, state = self._runtime(**runtime_changes)
                with (
                    mock.patch.object(
                        annotation_store,
                        "ABSTENTION_CHECK",
                        annotation_store.ABSTENTION_CHECK_PASSED,
                    ),
                    self._counting_model() as calls,
                    self._serving(self._app(config, state)) as port,
                ):
                    status, _ = self._post(port, self._press(**body_changes))
                self.assertEqual(expected, status, label)
                self.assertEqual([], calls, f"{label}: the model ran behind a closed gate")

    def test_a_discarded_session_is_refused_by_name_and_not_as_nothing_typed(self) -> None:
        """DRC-4565. Two empty states, and the route answered with the wider one.

        A discard record has no revisions, so `_readable`'s `not revisions`
        arm caught it and the reader was told nothing had ever been typed
        against a session they had typed against and then deleted. The
        distinction is not cosmetic here: it is the only place the route can
        say what became of the words.
        """
        config, state = self._runtime()
        application = self._app(config, state)
        annotation_store.clear(
            config, state, "pi", "s1", now=1_700_000_050.0, diagnostic_sink=lambda _m: None
        )
        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(application) as port,
        ):
            status, _body = self._post(port, self._press())

        self.assertEqual(202, status)
        answer = self.outcomes[-1]
        self.assertFalse(answer["produced"])
        self.assertEqual(runtime_reading.WITHHELD_DISCARDED, answer["reason"])
        self.assertNotEqual(runtime_reading.WITHHELD_NOTHING_TYPED, answer["reason"])
        # Refused before the subprocess, like every other gate in this class.
        self.assertEqual([], calls, "the model ran against a discarded session")
        # And nothing was written onto the record: it stays text-free.
        entry = annotation_store.find(annotation_store.load(config), "pi", "s1")
        assert entry is not None
        self.assertNotIn("withheld", entry)
        self.assertNotIn("readings", entry)

    def test_a_session_nobody_typed_against_still_answers_nothing_typed(self) -> None:
        """The other side of the pair, so the mutation binds in both
        directions. Swapping the two sentences would leave the test above
        green on its own."""
        config, state = self._runtime()
        application = self._app(config, state)
        annotation_store.annotate(config, state, "pi", "s1", goal="", output="", now=20.0)
        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(application) as port,
        ):
            _status, _body = self._post(port, self._press())

        self.assertEqual(runtime_reading.WITHHELD_NOTHING_TYPED, self.outcomes[-1]["reason"])
        self.assertEqual([], calls)

    def test_a_lured_request_cannot_spend_a_readers_capacity(self) -> None:
        """Each shape this route refuses that `_local_ok` alone would admit.

        `do_POST` already refuses `cross-site`, so asserting only that proves
        nothing about this route's own gate: measured, deleting the gate's
        navigation clause left a cross-site-only test green. `same-site` and a
        same-origin document navigation are the two shapes `_local_ok` admits
        and `_loopback_resource_ok` does not, and they are what this asserts.
        """
        cases = (
            ("same-site fetch", {"Sec-Fetch-Site": "same-site"}),
            (
                "same-origin navigation",
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
            ),
            ("cross-site navigation", {"Sec-Fetch-Site": "cross-site"}),
        )
        for label, headers in cases:
            with self.subTest(shape=label):
                config, state = self._runtime()
                with (
                    mock.patch.object(
                        annotation_store,
                        "ABSTENTION_CHECK",
                        annotation_store.ABSTENTION_CHECK_PASSED,
                    ),
                    self._counting_model() as calls,
                    self._serving(self._app(config, state)) as port,
                ):
                    status, _ = self._post(port, self._press(), headers=headers)
                self.assertEqual(403, status, label)
                self.assertEqual([], calls, label)

    def test_an_open_gate_really_does_reach_the_model(self) -> None:
        """The positive control, and without it this whole class proves nothing.

        Every other test here asserts the model was NOT invoked. That is only
        evidence if an invocation is observable in the first place. The first
        version of this class had no session and no annotation, so
        `_send_reading` returned at its no-rows arm ahead of the model on every
        path -- and deleting the entire gate left all five assertions green.

        This is the test that makes the other five mean something.
        """
        config, state = self._runtime()
        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press())
        self.assertEqual(202, status)
        self.assertEqual(1, len(calls), "the open gate did not reach the model")
        self.assertIn("ship the parser", calls[0], "the reader's goal was not sent")
        self.assertTrue(json.loads(body)["ok"])

    @contextlib.contextmanager
    def _github(self, config: Any, state: Any) -> Any:
        """The route over one session whose goal names a pull request, with a stub `gh`.

        `gh` resolves to the stub and its calls land in the stub's log, so what the press
        started is read off a file and no real login or network is involved.
        """
        stub = StubGh(self)
        # The floor is the process's, and the clock here never moves, so a read an earlier test made
        # would answer this one.
        runtime_ci_read.FLOOR.clear()
        application = self._app(config, state)
        annotation_store.annotate(
            config, state, "pi", "s1", goal=f"Make CI green on {GOAL_URL}", output="", now=11.0
        )
        which = lambda name, _env: str(stub.bin / "gh") if name == "gh" else None  # noqa: E731
        with (
            mock.patch.object(runtime_git_status, "executable", which),
            mock.patch.dict(os.environ, {"CI_STUB_DIR": str(stub.folder)}),
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(application) as port,
        ):
            self.stub, self.model_calls = stub, calls
            yield port

    def test_a_press_reads_the_goals_pull_request_and_stores_what_it_read(self) -> None:
        config, state = self._runtime()
        with self._github(config, state) as port:
            status, _ = self._post(port, self._press())
        self.assertEqual(202, status)
        # A view, two listings and a second view of the one pull request, and one model call.
        self.assertEqual(4, len(self.stub.calls))
        self.assertEqual(1, len(self.model_calls))
        self.assertIn("passed on the pull request", self.model_calls[0])
        entry = annotation_store.find(annotation_store.load(config), "pi", "s1")
        assert entry is not None
        stored = entry["assessment"]["ci"]
        self.assertEqual(("acme/widgets", 12), (stored["repository"], stored["number"]))
        # A Pi session records no folder, so there is no commit to match and nothing settles.
        self.assertFalse(stored["head_matches"])

    def test_the_page_switch_turns_the_read_off_and_back_on(self) -> None:
        config, state = self._runtime()
        with self._github(config, state) as port:
            for answer, expected in (("off", "off"), ("on", "on")):
                status, body = self._post(
                    port, {"ci_read": answer, "press": True, "observer_model": 1}
                )
                self.assertEqual((200, expected), (status, json.loads(body)["ci_read"]))
                before = len(self.stub.calls)
                self._post(port, self._press())
                self.assertEqual(expected == "on", len(self.stub.calls) > before, answer)

    def test_the_notice_names_the_read_only_while_it_is_on(self) -> None:
        config, _state = self._runtime()

        # A route names its parts only when a model CLI is found; CI runners have none.
        def found(name: str) -> str:
            return f"/usr/local/bin/{name}"

        on = runtime_reading_route.resolve("pi", config=config, binary_resolver=found)
        self.assertEqual("on", on["ci_read"])
        self.assertIn(runtime_reading_route.CI_READ_PART, on["disclosure_parts"])
        self.assertTrue(runtime_ci_read.set_setting(config, on=False))
        off = runtime_reading_route.resolve("pi", config=config, binary_resolver=found)
        self.assertEqual("off", off["ci_read"])
        self.assertNotIn(runtime_reading_route.CI_READ_PART, off["disclosure_parts"])
        # The unasked lane is never `on`: no network call happens without a press.
        self.assertTrue(runtime_ci_read.set_setting(config, on=True))
        unasked = runtime_reading_route.resolve(
            "pi", config=config, unasked=True, binary_resolver=found
        )
        self.assertNotEqual("on", unasked["ci_read"])

    def test_the_flag_holds_the_read_off_and_the_page_cannot_lift_it(self) -> None:
        config, state = self._runtime(ci_read_enabled=False)
        with self._github(config, state) as port:
            status, body = self._post(port, {"ci_read": "on", "press": True, "observer_model": 1})
            self.assertEqual((200, "flag-off"), (status, json.loads(body)["ci_read"]))
            self._post(port, self._press())
        self.assertEqual([], self.stub.calls)
        self.assertEqual(1, len(self.model_calls))

    def test_a_paused_press_reads_nothing_from_github(self) -> None:
        config, state = self._runtime()
        with self._github(config, state) as port:
            self._post(port, {"consent": "off", "press": True, "observer_model": 1})
            status, _ = self._post(port, self._press())
        self.assertEqual(403, status)
        self.assertEqual([], self.stub.calls)

    def test_no_observer_model_reads_nothing_from_github(self) -> None:
        config, state = self._runtime(model_calls_disabled=True)
        with self._github(config, state) as port:
            status, _ = self._post(port, self._press())
        self.assertEqual(503, status)
        self.assertEqual([], self.stub.calls)

    def test_a_spent_day_reads_nothing_from_github(self) -> None:
        config, state = self._runtime()
        for index in range(reading_policy.DAILY_CAP):
            reading_policy.reserve(config, now=1_700_000_000.0 + index, provider="codex")
        with self._github(config, state) as port:
            status, _ = self._post(port, self._press())
        self.assertEqual(429, status)
        self.assertEqual([], self.stub.calls)

    # DRC-4686: the press starts a job the server owns, and the page learns of
    # it only from the payload, so a reload is indistinguishable from staying.

    @staticmethod
    def _data(port: int) -> dict[str, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/data")
            return dict(json.loads(conn.getresponse().read()))
        finally:
            conn.close()

    @contextlib.contextmanager
    def _delayed_provider(self, config: Any, state: Any, harness: str) -> Any:
        """A provider that stops at each phase boundary until the test lets it on.

        `prepare` holds the job while it reads the session's record, `spawn`
        before the CLI exists, `reply` before the CLI answers. `published`
        is the job's phase at every revision any stream was sent.
        """
        gates = {name: threading.Event() for name in ("prepare", "spawn", "reply")}
        reached = {name: threading.Event() for name in ("prepare", "model")}
        calls: list[str] = []
        published: list[str | None] = []
        key = f"{harness}:s1"

        class _Delayed:
            unavailable_reason = runtime_reading.WITHHELD_MODEL_UNAVAILABLE

            def __init__(self, _config: Any, *, on_spawn: Any = None, **_kw: Any) -> None:
                self.on_spawn = on_spawn

            @staticmethod
            def available() -> bool:
                return True

            def __call__(self, prompt: str, **_kw: Any) -> tuple[str, str]:
                calls.append(prompt)
                reached["model"].set()
                gates["spawn"].wait(5)
                self.on_spawn(object())
                gates["reply"].wait(5)
                return "{}", "ok"

        def facts(*_a: Any, **_k: Any) -> dict[str, Any]:
            if threading.current_thread().name.startswith(runtime_reading_jobs.THREAD_PREFIX):
                reached["prepare"].set()
                gates["prepare"].wait(5)
            return {
                "semantic": {
                    "facts": [{**self.FACT, "source_session": {"harness": harness, "sid": "s1"}}]
                }
            }

        publish = state.streams.publish

        def recorded(revision: Any) -> None:
            job = runtime_reading.published_jobs(config).get(key)
            published.append(job["phase"] if job else None)
            publish(revision)

        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._open_claude(),
            mock.patch.object(runtime_reading, "CodexReadingModel", _Delayed),
            mock.patch.object(runtime_reading, "ClaudeReadingModel", _Delayed),
            mock.patch.object(shutil, "which", lambda n: f"/usr/local/bin/{n}"),
            mock.patch.object(runtime_project_context, "collect", facts),
            mock.patch.object(runtime_reading_route, "destination", lambda *_a, **_k: ""),
            mock.patch.object(state.streams, "publish", recorded),
        ):
            try:
                yield gates, reached, calls, published
            finally:
                for gate in gates.values():
                    gate.set()
                self._settle()

    def _job_presses(self) -> Any:
        """The Codex route and the Claude Code route, each pressed as the page would."""
        return (
            ("pi", self._press()),
            ("claude", self._claude_press(provider="claude")),
        )

    def test_a_press_answers_at_once_with_its_job_and_a_reload_shows_the_same_job(self) -> None:
        for harness, press in self._job_presses():
            with self.subTest(harness=harness):
                config, state = self._runtime()
                reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
                with (
                    self._delayed_provider(config, state, harness) as (gates, reached, calls, _),
                    self._serving(self._app(config, state, harness)) as port,
                ):
                    status, body = self._post(port, press, settle=False)
                    self.assertEqual(202, status, body)
                    job = json.loads(body)["job"]
                    self.assertEqual("preparing", job["phase"])
                    self.assertEqual([], calls, "the press waited on the model")
                    self.assertTrue(reached["prepare"].wait(5))
                    reload = self._data(port)["reading_jobs"][f"{harness}:s1"]
                    self.assertEqual((job["id"], "preparing"), (reload["id"], reload["phase"]))
                    gates["prepare"].set()
                    self.assertTrue(reached["model"].wait(5))
                    gates["spawn"].set()
                    self.assertTrue(
                        self._until(lambda c=config, h=harness: self._phase(c, h) == "waiting")
                    )
                    reload = self._data(port)["reading_jobs"][f"{harness}:s1"]
                    self.assertEqual((job["id"], "waiting"), (reload["id"], reload["phase"]))
                    label = "Claude Code" if harness == "claude" else "Codex"
                    self.assertEqual(
                        ["Preparing what is sent", f"Waiting for {label}", "Checking the reply"],
                        [step["text"] for step in reload["steps"]],
                    )
                    self.assertNotIn("group", reload)
                    gates["reply"].set()
                    self._settle()
                    self.assertNotIn(f"{harness}:s1", self._data(port)["reading_jobs"])
                entry = annotation_store.find(annotation_store.load(config), harness, "s1")
                assert entry is not None
                self.assertIn("assessment", entry)

    def test_the_phases_published_are_the_three_real_ones_in_order(self) -> None:
        for harness, press in self._job_presses():
            with self.subTest(harness=harness):
                config, state = self._runtime()
                reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
                with (
                    self._delayed_provider(config, state, harness) as (
                        gates,
                        reached,
                        _calls,
                        published,
                    ),
                    self._serving(self._app(config, state, harness)) as port,
                ):
                    self._post(port, press, settle=False)
                    self.assertTrue(reached["prepare"].wait(5))
                    gates["prepare"].set()
                    self.assertTrue(reached["model"].wait(5))
                    gates["spawn"].set()
                    self.assertTrue(
                        self._until(lambda c=config, h=harness: self._phase(c, h) == "waiting")
                    )
                    gates["reply"].set()
                    self._settle()
                # Each phase in its own revision, and once: consecutive repeats
                # are other collections of an unchanged state.
                # The press's own collection comes first, before any job existed.
                runs = [p for i, p in enumerate(published) if i == 0 or published[i - 1] != p]
                self.assertEqual(
                    ["preparing", "waiting", "checking", None], runs[runs.index("preparing") :]
                )

    def test_a_second_press_during_an_analysis_starts_no_second_call(self) -> None:
        for harness, press in self._job_presses():
            with self.subTest(harness=harness):
                config, state = self._runtime()
                reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
                with (
                    self._delayed_provider(config, state, harness) as (gates, reached, calls, _),
                    self._serving(self._app(config, state, harness)) as port,
                ):
                    _, body = self._post(port, press, settle=False)
                    job = json.loads(body)["job"]
                    self.assertTrue(reached["prepare"].wait(5))
                    status, again = self._post(port, press, settle=False)
                    self.assertEqual(409, status)
                    self.assertEqual(job["id"], json.loads(again)["job"]["id"])
                    self.assertEqual("in-flight", json.loads(again)["reason"])
                    gates["prepare"].set()
                    self.assertTrue(reached["model"].wait(5))
                    gates["spawn"].set()
                    self.assertTrue(
                        self._until(lambda c=config, h=harness: self._phase(c, h) == "waiting")
                    )
                    status, again = self._post(port, press, settle=False)
                    self.assertEqual(409, status)
                    answer = json.loads(again)
                    self.assertEqual(
                        (job["id"], "waiting"), (answer["job"]["id"], answer["job"]["phase"])
                    )
                    gates["reply"].set()
                    self._settle()
                self.assertEqual(1, len(calls), "a second press started a second call")

    def test_a_press_while_the_unasked_lane_reads_the_session_invents_no_job(self) -> None:
        config, state = self._runtime()
        self.assertTrue(runtime_reading.claim(config, "pi:s1"))
        self.addCleanup(runtime_reading.release, config, "pi:s1")
        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press())
            payload = self._data(port)
        self.assertEqual(409, status)
        answer = json.loads(body)
        self.assertEqual("in-flight", answer["reason"])
        self.assertNotIn("job", answer)
        self.assertEqual({}, payload["reading_jobs"])
        self.assertEqual([], calls)

    def test_a_refusal_at_the_model_seam_writes_nothing_and_ends_the_job(self) -> None:
        """Another tab spent the last reading after this press was admitted."""
        config, state = self._runtime()

        def exhaust() -> None:
            for _ in range(reading_policy.DAILY_CAP):
                reading_policy.reserve(config, now=1_700_000_100.0)

        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model(on_collect=exhaust) as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, _ = self._post(port, self._press())
            payload = self._data(port)
        self.assertEqual(202, status)
        self.assertEqual([], calls)
        self.assertEqual([], self.outcomes, "a refused press wrote an outcome")
        self.assertEqual({}, payload["reading_jobs"])
        self.assertEqual("daily-cap", payload["reading"]["reason"])

    def test_a_job_whose_thread_cannot_start_answers_503_and_frees_the_session(self) -> None:
        """Review F8: without this, every later press answered in-flight until a restart."""
        config, state = self._runtime()
        real_start = threading.Thread.start
        failing = [True]

        def start(thread: threading.Thread) -> None:
            if failing[0] and thread.name.startswith(runtime_reading_jobs.THREAD_PREFIX):
                raise RuntimeError("can't start new thread")
            real_start(thread)

        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
            mock.patch.object(threading.Thread, "start", start),
        ):
            status, _ = self._post(port, self._press())
            self.assertEqual(503, status)
            self.assertIsNone(runtime_reading.job(config, "pi:s1"))
            failing[0] = False
            status, _ = self._post(port, self._press())
        self.assertEqual(202, status)
        self.assertEqual(1, len(calls))

    def test_a_press_whose_thread_cannot_start_leaves_the_notice_for_the_next(self) -> None:
        config, state = self._runtime()
        reading_policy.store_path(config).unlink()
        real_start = threading.Thread.start
        failing = [True]

        def start(thread: threading.Thread) -> None:
            if failing[0] and thread.name.startswith(runtime_reading_jobs.THREAD_PREFIX):
                raise RuntimeError("can't start new thread")
            real_start(thread)

        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
            mock.patch.object(threading.Thread, "start", start),
        ):
            status, _ = self._post(port, self._press())
            self.assertEqual(503, status)
            self.assertEqual({}, reading_policy.status(config, now=1_700_000_100.0)["notices"])
            failing[0] = False
            status, body = self._post(port, self._press())
        self.assertEqual(202, status, body)
        self.assertEqual("reading", json.loads(body)["notice"]["kind"])
        self.assertEqual(1, len(calls))

    def test_turning_readings_off_is_accepted_where_analyze_is_unavailable(self) -> None:
        # Goal summaries need neither the annotation store nor a qualified
        # reading provider, so their off switch must not depend on them.
        cases: tuple[tuple[str, dict[str, Any], bool], ...] = (
            ("annotations off", {"annotations_enabled": False}, True),
            ("reading gates closed", {}, False),
            ("model calls refused for the run", {"model_calls_disabled": True}, True),
        )
        for label, runtime_changes, any_enabled in cases:
            with self.subTest(gate=label):
                config, state = self._runtime(**runtime_changes)
                with (
                    mock.patch.object(
                        annotation_store, "any_reading_enabled", return_value=any_enabled
                    ),
                    self._serving(self._app(config, state)) as port,
                ):
                    status, body = self._post(
                        port, {"consent": "off", "press": True, "observer_model": 1}
                    )
                    lured, _ = self._post(
                        port,
                        {"consent": "off", "press": True, "observer_model": 1},
                        headers={"Sec-Fetch-Site": "same-site"},
                    )
                self.assertEqual(200, status, body)
                self.assertEqual(403, lured)
                stored = dataclasses.replace(config, model_calls_disabled=False)
                self.assertTrue(reading_policy.status(stored, now=1_700_000_100.0)["off"])

    def test_readings_turned_off_mid_press_and_left_off_send_nothing(self) -> None:
        config, state = self._runtime()

        def turn_off() -> None:
            reading_policy.set_consent(config, False, now=1_700_000_100.0)

        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model(on_collect=turn_off) as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, _ = self._post(port, self._press())
            payload = self._data(port)
        self.assertEqual(202, status)
        self.assertEqual([], calls)
        self.assertEqual([], self.outcomes, "a refused press wrote an outcome")
        self.assertEqual({}, payload["reading_jobs"])
        self.assertEqual("model-calls-paused", payload["reading"]["reason"])
        self.assertFalse(payload["reading"]["consent"])

    def _phase(self, config: Any, harness: str) -> str | None:
        job = runtime_reading.job(config, f"{harness}:s1")
        return job.phase if job else None

    @staticmethod
    def _until(predicate: Any, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return bool(predicate())

    def _settle(self) -> None:
        """Wait out every reading job this test started, and fail if one hangs."""
        prefix = runtime_reading_jobs.THREAD_PREFIX
        for thread in [t for t in threading.enumerate() if t.name.startswith(prefix)]:
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive(), f"reading job {thread.name} never finished")

    def test_a_session_nobody_annotated_is_not_confirmed_to_exist(self) -> None:
        """200 and never 404: a harness name is public and a session id is not."""
        config, state = self._runtime()
        with (
            mock.patch.object(
                annotation_store, "ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
            ),
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press(sid="no-such-session"))
        self.assertEqual(200, status)
        answer = json.loads(body)
        self.assertFalse(answer["produced"])
        self.assertEqual([], calls)

    # DRC-4650: which provider reads a session, and what a press may spend.

    def _claude_press(self, **over: Any) -> dict[str, Any]:
        return self._press(harness="claude", **over)

    def _consents(self, config: Any) -> dict[str, bool]:
        return reading_policy.status(config, now=1_700_000_100.0)["providers"]

    def _stamp(self, config: Any, harness: str) -> str:
        entry = annotation_store.find(annotation_store.load(config), harness, "s1")
        assert entry is not None
        return str(entry.get("assessment", {}).get("stamp", ""))

    def test_a_claude_reading_notices_its_wider_content_without_renewing_allow(self) -> None:
        config, state = self._runtime()
        # A Codex Allow an earlier build stored under the narrower, words-only disclosure.
        reading_policy.set_consent(config, False, now=1_700_000_100.0)
        reading_policy.set_consent(
            config,
            True,
            now=1_700_000_100.0,
            provider="codex",
            content=reading_policy.WORDS_CONTENT_VERSION,
        )
        with self._counting_model(harness="pi") as calls:
            with self._serving(self._app(config, state, "pi")) as port:
                status, body = self._post(
                    port,
                    self._press(
                        allow=True,
                        words_destination="",
                        content=999,
                        content_version=999,
                    ),
                )
                self.assertEqual(202, status, body)
            self.assertEqual(1, len(calls))
            route = runtime_reading_route.resolve("pi", config=config)
            self.assertNotIn("the agent's messages", route["disclosure"])
            self.assertNotIn("newest final reply", route["disclosure"])

        _, state = make_runtime(state_home=config.state_home, state_dir=config.state_dir)
        with (
            self._counting_model(harness="claude") as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(port, self._claude_press())
            self.assertEqual(202, status, body)
            answer = json.loads(body)
            self.assertEqual(reading_policy.CONTENT_VERSION, answer["notice"]["content"])
            self.assertEqual(
                reading_policy.CONTENT_CHANGED,
                reading_policy.status(config, now=1_700_000_100.0)["rebind"]["codex"],
            )
            self.assertIn(
                "the agent's messages",
                runtime_reading_route.resolve("claude", config=config)["disclosure"],
            )
            self.assertIn(
                "newest final reply",
                runtime_reading_route.resolve("claude", config=config)["disclosure"],
            )
            self.assertEqual(1, len(calls))
            self.assertEqual(2, reading_policy.status(config, now=1_700_000_100.0)["used"])
            status, body = self._post(
                port,
                self._claude_press(allow=True, words_destination=""),
            )
            self.assertEqual(202, status, body)
            self.assertEqual(2, len(calls))
            status, body = self._post(port, self._claude_press())
            self.assertEqual(202, status, body)
            self.assertEqual(3, len(calls))

    def test_prior_claude_content_versions_run_with_a_notice(self) -> None:
        for version in (2, 3):
            with self.subTest(version=version):
                config, state = self._runtime()
                reading_policy.set_consent(
                    config,
                    True,
                    now=1_700_000_100.0,
                    provider="codex",
                    destination="OpenAI",
                    tool_output="OpenAI",
                )
                assert runtime_io.sqlite_module is not None
                with contextlib.closing(
                    runtime_io.sqlite_module.connect(reading_policy.store_path(config))
                ) as db:
                    db.execute("UPDATE permission_disclosure SET version = ?", (version,))
                    db.commit()
                with (
                    self._counting_model(harness="claude", destination="OpenAI") as calls,
                    self._serving(self._app(config, state, "claude")) as port,
                ):
                    status, body = self._post(port, self._claude_press())
                    self.assertEqual(202, status, body)
                    self.assertEqual(
                        reading_policy.CONTENT_VERSION, json.loads(body)["notice"]["content"]
                    )
                    self.assertEqual(
                        reading_policy.CONTENT_CHANGED,
                        reading_policy.status(
                            config, now=1_700_000_100.0, destinations={"codex": "OpenAI"}
                        )["rebind"]["codex"],
                    )
                    self.assertEqual(1, reading_policy.status(config, now=1_700_000_100.0)["used"])
                    self.assertEqual(1, len(calls))
                    status, body = self._post(
                        port,
                        self._claude_press(
                            allow=True, words_destination="OpenAI", tool_output="OpenAI"
                        ),
                    )
                    self.assertEqual(202, status, body)
                    self.assertEqual(2, len(calls))
                    status, body = self._post(port, self._claude_press())
                    self.assertEqual(202, status, body)
                    self.assertEqual(3, len(calls))

    def test_a_claude_code_session_on_this_build_is_read_by_claude_code_when_it_is_installed(
        self,
    ) -> None:
        """The owner's acceptance of 2026-10-02, with no gate patched: `claude` on PATH."""
        config, state = self._runtime()
        with (
            self._counting_model(("codex", "claude"), harness="claude") as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(
                port, self._claude_press(provider="claude", allow=True, words_destination="")
            )
        self.assertEqual(202, status, body)
        self.assertEqual(1, len(calls))
        self.assertEqual(["claude"], self.providers)
        self.assertIn(runtime_observer.CLAUDE_READING_MODEL, self._stamp(config, "claude"))

    def test_a_claude_code_session_without_claude_on_path_is_read_by_codex(self) -> None:
        config, state = self._runtime()
        with (
            self._counting_model(("codex",), harness="claude") as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(port, self._claude_press())
        self.assertEqual(202, status, body)
        self.assertEqual(1, len(calls))
        self.assertEqual(["codex"], self.providers)
        self.assertIn(runtime_observer.OBSERVER_MODEL, self._stamp(config, "claude"))

    def test_a_forged_claude_press_on_a_codex_route_spends_nothing_and_saves_nothing(
        self,
    ) -> None:
        config, state = self._runtime()
        before = self._consents(config)
        with (
            self._counting_model(("codex",), harness="claude") as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(
                port, self._claude_press(provider="claude", allow=True, words_destination="")
            )
        self.assertEqual(409, status)
        answer = json.loads(body)
        self.assertEqual("provider-changed", answer["reason"])
        self.assertFalse(answer["produced"])
        self.assertEqual("codex", answer["route"]["provider"])
        self.assertEqual([], calls)
        self.assertEqual(before, self._consents(config))
        self.assertEqual(0, reading_policy.status(config, now=1_700_000_100.0)["used"])

    def test_a_press_that_names_no_provider_is_not_taken_as_consent_to_one(self) -> None:
        config, state = self._runtime()
        with (
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            body = self._press()
            del body["provider"]
            status, _ = self._post(port, body)
        self.assertEqual(409, status)
        self.assertEqual([], calls)

    def test_with_no_reader_for_this_harness_a_press_is_refused_before_anything(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(config, False, now=1_700_000_100.0)
        for provider in ("", "codex", "claude"):
            with (
                self.subTest(provider=provider),
                self._closed_claude(),
                self._counting_model(("claude",), harness="claude") as calls,
                self._serving(self._app(config, state, "claude")) as port,
            ):
                status, body = self._post(port, self._claude_press(provider=provider, allow=True))
                self.assertEqual(503, status)
                answer = json.loads(body)
                self.assertEqual(
                    runtime_reading_route.REASON_UNQUALIFIED_OTHER_MISSING, answer["reason"]
                )
                self.assertEqual("", answer["route"]["provider"])
                self.assertEqual([], calls)
                self.assertEqual({"codex": False, "claude": False}, self._consents(config))
                self.assertEqual(0, reading_policy.status(config, now=1_700_000_100.0)["used"])

    # DRC-4679: a session waiting at its prompt, and where typed words start reading work.

    WAITING: ClassVar[dict[str, Any]] = {
        "state": "idle",
        "active": False,
        "finished_at": 1_700_000_050.0,
        "acquisition": "event",
    }

    def test_a_claude_code_reader_pressing_on_a_session_waiting_at_its_prompt_gets_its_last_turn(
        self,
    ) -> None:
        config, state = self._runtime()
        with (
            self._counting_model(("codex",), harness="claude") as calls,
            self._serving(self._app(config, state, "claude", row=self.WAITING)) as port,
        ):
            status, body = self._post(port, self._claude_press())
        self.assertEqual(202, status, body)
        self.assertTrue(self.outcomes[-1]["produced"], body)
        self.assertEqual(1, len(calls))
        entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
        assert entry is not None
        self.assertEqual(runtime_reading.SCOPE_LAST_TURN, entry["assessment"]["scope"])

    def test_a_codex_session_waiting_at_its_prompt_is_still_withheld_and_spends_nothing(
        self,
    ) -> None:
        config, state = self._runtime()
        with (
            self._counting_model(harness="codex") as calls,
            self._serving(self._app(config, state, "codex", row=self.WAITING)) as port,
        ):
            status, body = self._post(port, self._press(harness="codex"))
        # Answered at the press since DRC-4758 slice A2: 200, no job, nothing
        # recorded, where it used to be a 202 whose job then withheld.
        self.assertEqual(200, status, body)
        answer = json.loads(body)
        self.assertEqual("withheld", answer["reason"])
        self.assertEqual(runtime_reading.WITHHELD_TURN_STOP, answer["withheld"])
        self.assertEqual(
            runtime_reading.withheld_sentence(answer["withheld"], {"harness": "codex"}),
            answer["sentence"],
        )
        self.assertFalse(answer["produced"])
        self.assertEqual([], self.outcomes, "a job ran for a press the board refused")
        self.assertEqual([], calls)

    IDLE_UNKNOWN: ClassVar[dict[str, Any]] = {
        "state": "idle",
        "active": False,
        "acquisition": "event",
    }

    def test_a_saved_claude_goal_with_no_recorded_turn_stop_is_read_up_to_its_last_entry(
        self,
    ) -> None:
        # Owner, 2026-10-20: an idle session whose last turn has no recorded finish is read the
        # way a running one is, at the mid-flight scope, and says it was idle.
        config, state = self._runtime()
        with (
            self._counting_model(("codex",), harness="claude") as calls,
            self._serving(self._app(config, state, "claude", row=self.IDLE_UNKNOWN)) as port,
        ):
            before = self._published_row(port, "claude")
            status, body = self._post(port, self._claude_press())
        self.assertEqual("ship the parser", before["annotation_goal"])
        self.assertEqual(
            {"ok": True, "reason": None, "until": None, "sentence": None},
            before["reading_eligibility"],
        )
        self.assertEqual(202, status, body)
        self.assertTrue(self.outcomes[-1]["produced"], body)
        self.assertEqual(1, len(calls))
        entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
        assert entry is not None
        self.assertEqual(runtime_reading.SCOPE_MID_FLIGHT, entry["assessment"]["scope"])
        self.assertEqual(
            runtime_reading.SCOPE_TEXT_MID_FLIGHT_IDLE, entry["assessment"]["scope_text"]
        )

    def test_a_press_the_board_says_cannot_read_starts_no_job_and_counts_no_attempt(
        self,
    ) -> None:
        config, state = self._runtime()
        # Paused, then resumed: model calls on, and no provider holds an Allow.
        reading_policy.set_consent(config, False, now=1_700_000_100.0)
        reading_policy.resume(config, now=1_700_000_100.0)
        started: list[str] = []
        start_job = runtime_reading.start_job

        def counted(*args: Any, **kwargs: Any) -> Any:
            started.append(str(args[1]))
            return start_job(*args, **kwargs)

        with (
            mock.patch.object(runtime_reading, "start_job", counted),
            self._counting_model(harness="codex") as calls,
            self._serving(self._app(config, state, "codex", row=self.IDLE_UNKNOWN)) as port,
        ):
            status, body = self._post(
                port, self._press(harness="codex", allow=True, words_destination="")
            )
            published = self._published_row(port, "codex")
        self.assertEqual(200, status, body)
        answer = json.loads(body)
        self.assertEqual(runtime_reading.WITHHELD_IDLE_UNKNOWN, answer["withheld"])
        self.assertIsNone(answer["until"])
        # The same answer the board published before the press.
        self.assertEqual(
            {
                "ok": False,
                "reason": runtime_reading.WITHHELD_IDLE_UNKNOWN,
                "until": None,
                "sentence": answer["sentence"],
            },
            published["reading_eligibility"],
        )
        self.assertEqual([], started, "a reading job was registered")
        self.assertEqual({}, runtime_reading.published_jobs(config))
        self.assertEqual([], calls)
        self.assertEqual([], self.outcomes)
        entry = annotation_store.find(annotation_store.load(config), "codex", "s1")
        assert entry is not None
        self.assertEqual(0, entry.get("readings", 0), "an attempt was counted")
        self.assertEqual(0, reading_policy.status(config, now=1_700_000_100.0)["used"])
        # The legacy Allow the press carried records nothing, narrow or wide.
        self.assertFalse(reading_policy.status(config, now=1_700_000_100.0)["words"]["codex"])
        self.assertFalse(self._consents(config)["codex"], "a press granted the unasked lane")

    def _published_row(self, port: int, harness: str) -> dict[str, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/data")
            rows = json.loads(conn.getresponse().read())["sessions"]
        finally:
            conn.close()
        row: dict[str, Any] = next(r for r in rows if r["harness"] == harness)
        return row

    @staticmethod
    def _save(port: int, payload: dict[str, Any]) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST",
                "/api/annotate",
                body=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def _saved_revision(self, config: Any) -> Any:
        entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
        assert entry is not None
        return entry["revisions"][-1]

    def test_typed_words_read_work_from_your_latest_message_before_you_saved(self) -> None:
        config, state = self._runtime()
        later = {
            **self.FACT,
            "fact_id": "f2",
            "at": 1_700_000_040.0,
            "source_session": {"harness": "claude", "sid": "s1"},
        }
        after = {**later, "fact_id": "f3", "at": 1_700_000_200.0}
        with (
            self._counting_model(harness="claude", extra_facts=(later, after)),
            self._serving(self._app(config, state, "claude", row=self.WAITING)) as port,
        ):
            status, body = self._save(
                port,
                {
                    "harness": "claude",
                    "sid": "s1",
                    "goal": "add retry to the webhook",
                    "read_from_now": True,
                },
            )
        self.assertEqual(200, status, body)
        revision = self._saved_revision(config)
        self.assertEqual(1_700_000_100.0, revision["at"])
        self.assertEqual(1_700_000_040.0, revision["window_start"])

    def _two_saves(self, first: dict[str, Any], second: dict[str, Any]) -> Any:
        """Save `first` with one message of the reader's on record, then `second` with two.

        One server for both, so the second save meets the first's revision on a
        clock that does not step back, as it would not in life.
        """
        config, state = self._runtime()
        facts: list[dict[str, Any]] = []

        def message(index: int, moment: float) -> dict[str, Any]:
            return {
                **self.FACT,
                "fact_id": f"f{index}",
                "at": moment,
                "source_session": {"harness": "claude", "sid": "s1"},
            }

        with (
            self._counting_model(harness="claude", extra_facts=cast("Any", facts)),
            self._serving(self._app(config, state, "claude", row=self.WAITING)) as port,
        ):
            facts.append(message(2, 1_700_000_040.0))
            status, body = self._save(port, {"harness": "claude", "sid": "s1", **first})
            self.assertEqual(200, status, body)
            opened = self._saved_revision(config)["window_start"]
            facts.append(message(3, 1_700_000_090.0))
            status, body = self._save(port, {"harness": "claude", "sid": "s1", **second})
            self.assertEqual(200, status, body)
        return opened, self._saved_revision(config)

    def test_editing_the_goal_keeps_the_original_reading_start(self) -> None:
        opened, revision = self._two_saves(
            {"goal": "add retry to the webhook", "read_from_now": True},
            {"goal": "add retry to the webhook and record the ruling"},
        )
        self.assertEqual(1_700_000_040.0, opened)
        self.assertEqual("add retry to the webhook and record the ruling", revision["goal"])
        self.assertEqual(1_700_000_040.0, revision["window_start"])

    def test_read_from_now_moves_the_reading_start_to_the_latest_message(self) -> None:
        _, revision = self._two_saves(
            {"goal": "add retry to the webhook", "read_from_now": True},
            {"goal": "add retry to the webhook and record the ruling", "read_from_now": True},
        )
        self.assertEqual(1_700_000_090.0, revision["window_start"])

    def test_read_from_now_must_be_a_boolean(self) -> None:
        config, state = self._runtime()
        with self._serving(self._app(config, state, "claude", row=self.WAITING)) as port:
            status, _ = self._save(
                port,
                {"harness": "claude", "sid": "s1", "goal": "add retry", "read_from_now": "yes"},
            )
        self.assertEqual(400, status)

    def test_words_typed_from_the_all_sessions_view_read_from_your_latest_message(self) -> None:
        config, state = self._runtime()
        later = {
            **self.FACT,
            "fact_id": "f2",
            "at": 1_700_000_040.0,
            "source_session": {"harness": "claude", "sid": "s1"},
        }
        with (
            self._counting_model(harness="claude", extra_facts=(later,)),
            self._serving(self._app(config, state, "claude", row=self.WAITING, aged=True)) as port,
        ):
            status, body = self._save(
                port,
                {
                    "harness": "claude",
                    "sid": "s1",
                    "goal": "add retry to the webhook",
                    "read_from_now": True,
                },
            )
        self.assertEqual(200, status, body)
        self.assertEqual(1_700_000_040.0, self._saved_revision(config)["window_start"])

    def test_a_readers_typed_save_does_not_collect_every_session_when_the_board_already_holds_the_row(
        self,
    ) -> None:
        """Owner, 2026-10-02: a save took about 900 ms, a full all-sessions collection of it."""
        config, state = self._runtime()
        later = {
            **self.FACT,
            "fact_id": "f2",
            "at": 1_700_000_040.0,
            "source_session": {"harness": "claude", "sid": "s1"},
        }
        application = self._app(config, state, "claude", row=self.WAITING)
        variants: list[bool] = []
        collections: list[bool] = []
        original = application.collect_json
        collect = application.collect

        def counted(*, show_all: bool) -> Any:
            variants.append(show_all)
            return original(show_all=show_all)

        def collected(*, show_all: bool) -> Any:
            collections.append(show_all)
            return collect(show_all=show_all)

        with (
            self._counting_model(harness="claude", extra_facts=(later,)),
            mock.patch.object(application, "collect_json", counted),
            mock.patch.object(application, "collect", collected),
            self._serving(application) as port,
        ):
            self._published_row(port, "claude")
            before, collected_before = len(variants), len(collections)
            status, body = self._save(
                port,
                {
                    "harness": "claude",
                    "sid": "s1",
                    "goal": "add retry to the webhook",
                    "read_from_now": True,
                },
            )
        self.assertEqual(200, status, body)
        self.assertNotIn(True, variants[before:], "the save collected every session")
        # The board's row is warm, so the save itself collects nothing: no clear forces one.
        self.assertEqual([], collections[collected_before:])
        # The row the board already held still opens the window at the latest message.
        self.assertEqual(1_700_000_040.0, self._saved_revision(config)["window_start"])

    def test_a_save_whose_record_cannot_be_read_still_saves_and_reads_from_the_save(
        self,
    ) -> None:
        config, state = self._runtime()

        def broken() -> Any:
            message = "the record could not be read"
            raise OSError(message)

        with (
            self._counting_model(harness="claude", on_collect=broken),
            self._serving(self._app(config, state, "claude", row=self.WAITING)) as port,
        ):
            status, body = self._save(
                port,
                {
                    "harness": "claude",
                    "sid": "s1",
                    "goal": "add retry to the webhook",
                    "read_from_now": True,
                },
            )
        self.assertEqual(200, status, body)
        self.assertEqual("stored", json.loads(body)["outcome"])
        revision = self._saved_revision(config)
        self.assertEqual(1_700_000_100.0, revision["window_start"])

    def _open_claude(self) -> Any:
        return mock.patch.object(
            annotation_store, "CLAUDE_ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_PASSED
        )

    def _closed_claude(self) -> Any:
        return mock.patch.object(
            annotation_store, "CLAUDE_ABSTENTION_CHECK", annotation_store.ABSTENTION_CHECK_NOT_RUN
        )

    def test_claude_readings_need_no_second_provider_allow(self) -> None:
        config, state = self._runtime()
        self.assertEqual({"codex": True, "claude": False}, self._consents(config))
        with (
            self._open_claude(),
            self._counting_model(("codex", "claude"), harness="claude") as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(port, self._claude_press(provider="claude"))
            self.assertEqual(202, status, body)
            self.assertEqual("claude", json.loads(body)["notice"]["provider"])
            self.assertEqual(1, len(calls))
            status, _ = self._post(
                port, self._claude_press(provider="claude", allow=True, words_destination="")
            )
        self.assertEqual(202, status)
        self.assertEqual(["claude", "claude"], self.providers)
        # The legacy `allow` field is a plain press: it records no Claude Code Allow.
        self.assertEqual({"codex": True, "claude": False}, self._consents(config))
        self.assertIn(runtime_observer.CLAUDE_READING_MODEL, self._stamp(config, "claude"))

    def test_a_claude_code_allow_covers_a_pi_session_that_falls_back_to_it(self) -> None:
        """Per provider, not per harness (owner, 2026-10-02).

        On a machine with `claude` and no `codex`, a Pi session is read by
        Claude Code. An Allow given for Claude Code covers that press with no
        second consent step, and a Codex Allow alone does not.
        """
        config, state = self._runtime()
        with (
            self._open_claude(),
            self._counting_model(("claude",)) as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press(provider="claude"))
            self.assertEqual(202, status, body)
            self.assertEqual("claude", json.loads(body)["notice"]["provider"])
            self.assertEqual(1, len(calls))
            reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
            status, body = self._post(port, self._press(provider="claude"))
        self.assertEqual(202, status, body)
        self.assertEqual(["claude", "claude"], self.providers)

    def test_changed_claude_destination_runs_and_preserves_legacy_coverage(
        self,
    ) -> None:
        """Owner, 2026-10-02: the Allow for the words is bound to their destination.

        A Pi session read by Claude Code, so no tool-output grant is involved
        and the words' own binding is the only thing that can refuse.
        """
        config, state = self._runtime()
        # An Allow an earlier build stored; no press writes one now.
        reading_policy.set_consent(
            config, True, now=1_700_000_100.0, provider="claude", destination="Anthropic"
        )
        with (
            self._open_claude(),
            self._counting_model(("claude",), destination="Anthropic") as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press(provider="claude"))
        self.assertEqual(202, status, body)
        self.assertEqual(1, len(calls))
        for moved in ("gw.corp.example", "Amazon Bedrock"):
            with (
                self.subTest(moved=moved),
                self._open_claude(),
                self._counting_model(("claude",), destination=moved) as calls,
                self._serving(self._app(config, state)) as port,
            ):
                status, body = self._post(port, self._press(provider="claude"))
                self.assertEqual(202, status, body)
                answer = reading_policy.status(
                    config, now=1_700_000_100.0, destinations={"claude": moved}
                )
                self.assertEqual(moved, json.loads(body)["notice"]["destination"])
                self.assertFalse(answer["providers"]["claude"])
                self.assertEqual(reading_policy.DESTINATION_CHANGED, answer["rebind"]["claude"])
                self.assertEqual(1, len(calls))

    def test_a_destination_that_moves_after_the_press_refuses_the_job_unspent(self) -> None:
        """Consent F4 (ui5): the job re-resolves the destination at its
        reservation. A managed drop-in or `remote-settings.json` can change
        while the job collects the record, which takes seconds for a large
        one; the reservation is refused `destination-changed` and nothing is
        spent or sent, and the board then says the Allow no longer covers."""
        config, state = self._runtime()
        # An Allow an earlier build stored; no press writes one now.
        reading_policy.set_consent(
            config, True, now=1_700_000_100.0, provider="claude", destination="Anthropic"
        )
        with (
            self._open_claude(),
            self._counting_model(("claude",), destination="Anthropic") as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press(provider="claude"))
        self.assertEqual(202, status, body)
        self.assertEqual(1, len(calls))
        used = reading_policy.status(config, now=1_700_000_100.0, provider="claude")["used"]
        where = ["Anthropic"]

        def moves() -> None:
            where[0] = "gw.corp.example"

        with (
            self._open_claude(),
            self._counting_model(("claude",), on_collect=moves) as calls,
            mock.patch.object(runtime_reading_route, "destination", lambda *_a, **_k: where[0]),
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press(provider="claude"))
            payload = self._data(port)
        self.assertEqual(202, status, body)
        self.assertEqual([], calls, "the words went to a destination the Allow never named")
        after = reading_policy.status(
            config, now=1_700_000_100.0, provider="claude", destinations={"claude": where[0]}
        )
        self.assertEqual(used, after["used"], "a refused reservation was charged")
        self.assertEqual({}, payload["reading_jobs"])
        self.assertFalse(payload["reading"]["providers"]["claude"])
        self.assertEqual(reading_policy.DESTINATION_CHANGED, payload["reading"]["rebind"]["claude"])

    def test_an_allow_whose_disclosure_named_where_the_words_no_longer_go_records_nothing(
        self,
    ) -> None:
        config, state = self._runtime()
        before = reading_policy.status(config, now=1_700_000_100.0, provider="claude")
        with (
            self._open_claude(),
            self._counting_model(("claude",), destination="gw.corp.example") as calls,
            self._serving(self._app(config, state)) as port,
        ):
            # A body with no `words_destination` at all is an older page's,
            # answered by the test below rather than as this refusal.
            for named in ({"words_destination": "Anthropic"}, {"words_destination": ""}):
                with self.subTest(named=named):
                    status, body = self._post(
                        port, self._press(provider="claude", allow=True, **named)
                    )
                    self.assertEqual(409, status)
                    answer = json.loads(body)
                    self.assertEqual("destination-changed", answer["reason"])
                    self.assertEqual("gw.corp.example", answer["route"]["words_destination"])
        self.assertEqual([], calls)
        self.assertEqual(
            before, reading_policy.status(config, now=1_700_000_100.0, provider="claude")
        )

    def test_an_allow_from_a_page_older_than_the_binding_is_told_to_reload(self) -> None:
        """Regressions major 1 (ui5). A tab left open across the upgrade sends
        an Allow with no `words_destination`, which binds nothing and is
        refused. The 79bcedae page answers a 409 by drawing the consent card
        again with a line about tool output, forever; rendered against the new
        server, the one reply field it shows verbatim is a route with no
        provider, whose `note` it draws in the button's place. So the refusal
        is a 400 whose route says to reload, and nothing is recorded or sent."""
        for where in ("Anthropic", ""):
            for harness in ("pi", "claude"):
                with self.subTest(where=where, harness=harness):
                    config, state = self._runtime()
                    before = reading_policy.status(config, now=1_700_000_100.0, provider="claude")
                    with (
                        self._open_claude(),
                        self._counting_model(("claude",), destination=where) as calls,
                        self._serving(self._app(config, state)) as port,
                    ):
                        status, body = self._post(
                            port,
                            self._press(
                                harness=harness,
                                provider="claude",
                                allow=True,
                                **({"tool_output": where} if harness == "claude" and where else {}),
                            ),
                        )
                    self.assertEqual(400, status)
                    answer = json.loads(body)
                    self.assertEqual("page-outdated", answer["reason"])
                    self.assertEqual("", answer["route"]["provider"])
                    self.assertEqual(http_api.PAGE_OUTDATED, answer["route"]["note"])
                    self.assertEqual([], answer["route"]["disclosure_parts"])
                    self.assertEqual([], calls)
                    self.assertEqual(
                        before,
                        reading_policy.status(config, now=1_700_000_100.0, provider="claude"),
                    )

    def test_a_reader_who_allowed_only_claude_code_is_charged_against_that_answer(self) -> None:
        """The reservation reads the route's provider, not Codex's answer."""
        config, state = self._runtime()
        reading_policy.set_consent(config, False, now=1_700_000_100.0)
        reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
        with (
            self._open_claude(),
            self._counting_model(("codex", "claude"), harness="claude") as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(port, self._claude_press(provider="claude"))
        self.assertEqual(202, status, body)
        self.assertEqual(1, len(calls))
        self.assertEqual(["claude"], self.providers)
        self.assertEqual({"codex": False, "claude": True}, self._consents(config))

    def test_a_reader_shown_codex_whose_route_became_claude_must_press_again(self) -> None:
        config, state = self._runtime()
        with (
            self._open_claude(),
            # Named, so the route's `To:` item names the vendor (verifier ui4 C1).
            self._counting_model(
                ("codex", "claude"), harness="claude", destination="Anthropic"
            ) as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(port, self._claude_press(provider="codex", allow=True))
        self.assertEqual(409, status)
        answer = json.loads(body)
        self.assertEqual("provider-changed", answer["reason"])
        self.assertEqual("claude", answer["route"]["provider"])
        self.assertIn("Anthropic", answer["route"]["disclosure"])
        self.assertEqual([], calls)
        self.assertEqual({"codex": True, "claude": False}, self._consents(config))

    def test_a_claude_code_cli_gone_at_launch_is_unavailable_and_nothing_else_runs(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
        with (
            self._open_claude(),
            self._counting_model(
                ("codex", "claude"), launch_finds=("codex",), harness="claude"
            ) as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, _body = self._post(port, self._claude_press(provider="claude"))
        self.assertEqual(202, status)
        answer = self.outcomes[-1]
        self.assertFalse(answer["produced"])
        self.assertEqual(runtime_reading.WITHHELD_CLAUDE_UNAVAILABLE, answer["reason"])
        self.assertEqual([], calls, "a second provider was asked after the first was missing")
        self.assertEqual(0, reading_policy.status(config, now=1_700_000_100.0)["used"])

    def test_a_failed_claude_code_reading_is_not_retried_on_codex(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
        with (
            self._open_claude(),
            self._counting_model(("codex", "claude"), status="failed", harness="claude") as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, _body = self._post(port, self._claude_press(provider="claude"))
        self.assertEqual(202, status)
        self.assertEqual(runtime_reading.WITHHELD_MODEL_FAILED, self.outcomes[-1]["reason"])
        self.assertEqual(1, len(calls))
        self.assertEqual(["claude"], self.providers)
        self.assertEqual(1, reading_policy.status(config, now=1_700_000_100.0)["used"])

    def test_turning_readings_off_revokes_claude_code_too(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(config, True, now=1_700_000_100.0, provider="claude")
        with (
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, _ = self._post(port, {"consent": "off", "press": True, "observer_model": 1})
        self.assertEqual(200, status)
        self.assertEqual({"codex": False, "claude": False}, self._consents(config))
        self.assertEqual([], calls)

    CHECKS: ClassVar[tuple[dict[str, Any], ...]] = tuple(
        {
            "fact_id": f"check-{index}",
            "type": "tool_report",
            "subject": "check",
            "result": result,
            "result_source": "flag",
            "summary": f"python3 -m pytest tests/test_{name}.py",
            "at": 1_700_000_050.0 + index,
            "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
            "source_session": {"harness": "claude", "sid": "s1"},
            "branch": {"harness": "claude", "sid": "s1", "record_id": f"call-{index}"},
        }
        for index, (name, result) in enumerate((("retry", "failed"), ("parser", "passed")))
    )
    TAILS: ClassVar[dict[str, str]] = {
        "call-0": "FAILED tests/test_retry.py::test_backoff",
        "call-1": "5 passed in 0.2s",
    }

    def _checks_press(
        self,
        config: Any,
        state: Any,
        payload: dict[str, Any],
        installed: tuple[str, ...] = ("codex",),
        **model: Any,
    ) -> Any:
        model.setdefault("destination", "OpenAI")
        # By default Codex reads this Claude Code session, because `claude` is not on PATH.
        with (
            self._counting_model(
                installed,
                harness="claude",
                extra_facts=self.CHECKS,
                tails=self.TAILS,
                **model,
            ) as calls,
            self._serving(self._app(config, state, "claude")) as port,
        ):
            status, body = self._post(port, payload)
        return status, json.loads(body), calls

    @staticmethod
    def _checks_sent(prompt: str) -> int:
        return prompt.count("python3 -m pytest tests/test_")

    def test_a_fresh_claude_reading_includes_tool_output_without_a_grant(self) -> None:
        config, state = self._runtime()
        reading_policy.store_path(config).unlink()
        status, answer, calls = self._checks_press(config, state, self._claude_press())
        self.assertEqual(202, status, answer)
        self.assertEqual(2, self._checks_sent(calls[0]))
        self.assertEqual("OpenAI", answer["notice"]["tool_output"])
        self.assertEqual("OpenAI", answer["notice"]["destination"])
        self.assertEqual({}, reading_policy.status(config, now=1_700_000_100.0)["tool_output"])
        self.assertEqual(1, reading_policy.status(config, now=1_700_000_100.0)["used"])

    def test_an_allow_naming_where_the_checks_go_sends_them_and_records_nothing(self) -> None:
        config, state = self._runtime()
        status, answer, calls = self._checks_press(
            config,
            state,
            self._claude_press(allow=True, tool_output="OpenAI", words_destination="OpenAI"),
        )
        self.assertEqual(202, status, answer)
        self.assertEqual(["codex"], self.providers)
        self.assertEqual(2, self._checks_sent(calls[0]))
        self.assertIn(json.dumps(self.TAILS["call-0"]), calls[0])
        # A press writes no Allow, so no grant is recorded; none is needed to send them.
        granted = reading_policy.status(config, now=1_700_000_100.0, provider="codex")
        self.assertFalse(reading_policy.tool_output_allowed(granted, "codex", "OpenAI"))
        status, _answer, calls = self._checks_press(config, state, self._claude_press())
        self.assertEqual(202, status)
        self.assertEqual(2, self._checks_sent(calls[0]))

    def test_an_allow_for_a_destination_that_has_moved_is_refused_before_anything(self) -> None:
        config, state = self._runtime()
        before = reading_policy.status(config, now=1_700_000_100.0, provider="codex")
        status, answer, calls = self._checks_press(
            config,
            state,
            self._claude_press(
                allow=True, tool_output="OpenAI", words_destination="gw.corp.example"
            ),
            destination="gw.corp.example",
        )
        self.assertEqual(409, status)
        self.assertEqual("destination-changed", answer["reason"])
        self.assertEqual("gw.corp.example", answer["route"]["destination"])
        self.assertEqual([], calls)
        self.assertEqual(
            before, reading_policy.status(config, now=1_700_000_100.0, provider="codex")
        )

    def test_a_changed_destination_runs_with_a_new_notice(self) -> None:
        config, state = self._runtime()
        status, answer, calls = self._checks_press(
            config, state, self._claude_press(), destination="OpenAI"
        )
        self.assertEqual(202, status, answer)
        self.assertEqual("OpenAI", answer["notice"]["destination"])
        self.assertEqual(1, len(calls))
        status, answer, calls = self._checks_press(
            config, state, self._claude_press(), destination="gw.corp.example"
        )
        self.assertEqual(202, status, answer)
        self.assertEqual("gw.corp.example", answer["notice"]["destination"])
        self.assertEqual("gw.corp.example", answer["notice"]["tool_output"])
        self.assertEqual(2, self._checks_sent(calls[0]))

    def test_where_the_destination_cannot_be_named_the_codex_prompt_holds_no_check(
        self,
    ) -> None:
        config, state = self._runtime()
        status, answer, calls = self._checks_press(
            config, state, self._claude_press(), destination=""
        )
        self.assertEqual(202, status, answer)
        self.assertEqual(0, self._checks_sent(calls[0]))
        self.assertNotIn("FAILED tests/test_retry.py", calls[0])
        entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
        assert entry is not None
        # Whole, as stored: the store once clipped the cutoff at 240 characters,
        # which cut this clause off after "were not sent".
        self.assertIn(
            "were not sent, because Compass cannot name where Codex would send them.",
            entry["assessment"]["cutoff"],
        )

    def test_turning_readings_back_on_repeats_the_tool_output_notice(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(
            config,
            True,
            now=1_700_000_100.0,
            provider="codex",
            tool_output="OpenAI",
            destination="OpenAI",
        )
        reading_policy.set_consent(config, False, now=1_700_000_100.0)
        reading_policy.set_consent(
            config, True, now=1_700_000_100.0, provider="codex", destination="OpenAI"
        )
        status, answer, calls = self._checks_press(config, state, self._claude_press())
        self.assertEqual(202, status, answer)
        self.assertEqual("OpenAI", answer["notice"]["tool_output"])
        self.assertEqual(2, self._checks_sent(calls[0]))

    def test_turning_readings_off_then_on_mid_press_still_includes_checks(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(
            config,
            True,
            now=1_700_000_100.0,
            provider="codex",
            tool_output="OpenAI",
            destination="OpenAI",
        )

        def withdraw() -> None:
            # Another tab pauses model calls and allows the words alone again.
            reading_policy.set_consent(config, False, now=1_700_000_100.0)
            reading_policy.set_consent(
                config, True, now=1_700_000_100.0, provider="codex", destination="OpenAI"
            )

        status, answer, calls = self._checks_press(
            config, state, self._claude_press(), on_collect=withdraw
        )
        self.assertEqual(202, status, answer)
        self.assertEqual(2, self._checks_sent(calls[0]))
        entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
        assert entry is not None
        self.assertNotIn("tool output was not allowed", entry["assessment"]["cutoff"])

    def test_the_press_hands_the_reading_the_passes_a_later_command_may_have_changed(
        self,
    ) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(
            config,
            True,
            now=1_700_000_100.0,
            provider="codex",
            tool_output="OpenAI",
            destination="OpenAI",
        )
        changed = frozenset({("call-1", "python3 -m pytest tests/test_parser.py")})
        seen: list[Any] = []
        real = runtime_reading.produce

        def produce(*args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("tool_output"))
            return real(*args, **kwargs)

        with (
            mock.patch.object(runtime_reading, "produce", produce),
            self._counting_model(("codex",), harness="claude", destination="OpenAI"),
            self._serving(self._app(config, state, "claude")) as port,
            # After `_counting_model`, so this press reads a changed pass.
            mock.patch.object(
                runtime_project_context,
                "press_checks",
                lambda *_a, **_k: runtime_project_context.PressChecks({}, changed),
            ),
        ):
            status, _body = self._post(port, self._claude_press())
        self.assertEqual(202, status)
        self.assertEqual(changed, seen[0].changed_after)

    def _masked_values_seen_by_produce(self, config: Any, state: Any) -> frozenset[str]:
        seen: list[Any] = []
        real = runtime_reading.produce

        def produce(*args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("tool_output"))
            return real(*args, **kwargs)

        with (
            mock.patch.object(runtime_reading, "produce", produce),
            self._counting_model(("codex",), harness="claude", destination="OpenAI"),
            self._serving(self._app(config, state, "claude")) as port,
            mock.patch.object(
                runtime_project_context,
                "press_checks",
                lambda *_a, **_k: runtime_project_context.PressChecks(
                    {}, frozenset(), masked_values=frozenset({"FakePass99"})
                ),
            ),
        ):
            status, _body = self._post(port, self._claude_press())
        self.assertEqual(202, status)
        return frozenset(seen[0].masked_values)

    def test_the_press_hands_the_reading_the_values_a_command_masked(self) -> None:
        config, state = self._runtime()
        # Without a grant the press still carries them, and so it does with one.
        self.assertEqual(
            frozenset({"FakePass99"}), self._masked_values_seen_by_produce(config, state)
        )
        reading_policy.set_consent(
            config,
            True,
            now=1_700_000_100.0,
            provider="codex",
            tool_output="OpenAI",
            destination="OpenAI",
        )
        self.assertEqual(
            frozenset({"FakePass99"}), self._masked_values_seen_by_produce(config, state)
        )

    def test_on_the_claude_code_route_the_checks_go_only_after_the_same_allow(self) -> None:
        config, state = self._runtime()
        both = ("codex", "claude")
        status, answer, calls = self._checks_press(
            config,
            state,
            self._claude_press(provider="claude", allow=True, words_destination="Anthropic"),
            both,
            destination="Anthropic",
        )
        self.assertEqual(409, status)
        self.assertEqual("destination-changed", answer["reason"])
        self.assertEqual([], calls)
        status, answer, calls = self._checks_press(
            config,
            state,
            self._claude_press(
                provider="claude",
                allow=True,
                tool_output="Anthropic",
                words_destination="Anthropic",
            ),
            both,
            destination="Anthropic",
        )
        self.assertEqual(202, status, answer)
        self.assertEqual(["claude"], self.providers)
        self.assertEqual(2, self._checks_sent(calls[0]))

    def test_a_session_on_another_harness_is_never_asked_about_tool_output(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(
            config, True, now=1_700_000_100.0, provider="codex", destination="OpenAI"
        )
        with (
            self._counting_model(destination="OpenAI") as calls,
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press())
        self.assertEqual(202, status, body)
        self.assertEqual(1, len(calls))

    def test_an_oversized_body_is_refused_before_it_is_read(self) -> None:
        config, state = self._runtime()
        with (
            self._counting_model() as calls,
            self._serving(self._app(config, state)) as port,
        ):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            try:
                conn.putrequest("POST", "/api/reading")
                conn.putheader("Content-Length", "999999")
                conn.endheaders()
                status = conn.getresponse().status
            finally:
                conn.close()
        self.assertEqual(413, status)
        self.assertEqual([], calls)

    # DRC-4693: Cancel on a running analysis, over the socket.

    @contextlib.contextmanager
    def _held_model(self, *, at_seam: bool = False) -> Any:
        """A Codex model that holds its call until released, so a job stays running.

        `at_seam` holds it at the availability check instead, which is before
        anything is reserved.
        """
        release, entered = threading.Event(), threading.Event()
        calls: list[str] = []

        class _Held:
            unavailable_reason = runtime_reading.WITHHELD_MODEL_UNAVAILABLE

            def __init__(self, _config: Any, **_kw: Any) -> None:
                pass

            def __call__(self, prompt: str, **_kw: Any) -> tuple[str, str]:
                calls.append(prompt)
                entered.set()
                release.wait(10)
                return "{}", "ok"

            @staticmethod
            def available() -> bool:
                if at_seam:
                    entered.set()
                    release.wait(10)
                return True

        with (
            self._counting_model(),
            mock.patch.object(runtime_reading, "CodexReadingModel", _Held),
        ):
            try:
                yield release, entered, calls
            finally:
                release.set()

    def _cancel(
        self, port: int, job_id: str, *, headers: dict[str, str] | None = None, **over: Any
    ) -> tuple[int, bytes]:
        return self._post(
            port,
            {**self._press(), "job": job_id, **over},
            settle=False,
            headers=headers,
            path="/api/reading/cancel",
        )

    def _board_job(self, port: int) -> Any:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/data", headers={"Sec-Fetch-Site": "same-origin"})
            board = json.loads(conn.getresponse().read())
        finally:
            conn.close()
        return (board.get("reading_jobs") or {}).get("pi:s1")

    def test_a_reader_who_cancels_sees_the_board_say_cancelling_until_the_job_ends(
        self,
    ) -> None:
        config, state = self._runtime()
        with (
            self._held_model() as (release, entered, calls),
            self._serving(self._app(config, state)) as port,
        ):
            status, body = self._post(port, self._press(), settle=False)
            self.assertEqual(202, status, body)
            job_id = json.loads(body)["job"]["id"]
            self.assertTrue(entered.wait(10))
            self.assertIs(False, self._board_job(port)["cancelling"])
            status, body = self._cancel(port, job_id)
            self.assertEqual(202, status, body)
            self.assertEqual({"ok": True, "cancelling": True}, json.loads(body))
            # A reload while the cancel is finishing draws the same box.
            self.assertIs(True, self._board_job(port)["cancelling"])
            release.set()
            self._settle()
            self.assertIsNone(self._board_job(port))
        self.assertEqual(1, len(calls))
        self.assertEqual(
            [{"produced": False, "reason": runtime_reading.WITHHELD_CANCELLED, "spent": True}],
            self.outcomes,
        )

    def test_a_cancel_before_anything_is_reserved_spends_nothing(self) -> None:
        config, state = self._runtime()
        with (
            self._held_model(at_seam=True) as (release, entered, calls),
            self._serving(self._app(config, state)) as port,
        ):
            _status, body = self._post(port, self._press(), settle=False)
            job_id = json.loads(body)["job"]["id"]
            self.assertTrue(entered.wait(10))
            status, _ = self._cancel(port, job_id)
            self.assertEqual(202, status)
            release.set()
            self._settle()
        self.assertEqual([], calls)
        self.assertEqual(0, reading_policy.status(config, now=1_700_000_100.0)["used"])
        self.assertEqual(
            [
                {
                    "produced": False,
                    "reason": runtime_reading.WITHHELD_CANCELLED_UNSENT,
                    "spent": False,
                }
            ],
            self.outcomes,
        )

    def test_a_forged_cross_site_cancel_is_refused_and_the_analysis_keeps_running(
        self,
    ) -> None:
        config, state = self._runtime()
        with (
            self._held_model() as (release, entered, _calls),
            self._serving(self._app(config, state)) as port,
        ):
            _status, body = self._post(port, self._press(), settle=False)
            job_id = json.loads(body)["job"]["id"]
            self.assertTrue(entered.wait(10))
            for headers in (
                {"Sec-Fetch-Site": "cross-site"},
                {"Sec-Fetch-Site": "same-site"},
                {"Origin": f"http://127.0.0.1:{port + 1}"},
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
            ):
                with self.subTest(headers=headers):
                    status, _ = self._cancel(port, job_id, headers=headers)
                    self.assertEqual(403, status)
                    self.assertIs(False, self._board_job(port)["cancelling"])
            release.set()
            self._settle()
        self.assertEqual([{"produced": True, "reason": ""}], self.outcomes)

    def test_a_cancel_naming_another_job_or_no_session_answers_the_same_not_running(
        self,
    ) -> None:
        config, state = self._runtime()
        with (
            self._held_model() as (release, entered, _calls),
            self._serving(self._app(config, state)) as port,
        ):
            idle, idle_body = self._cancel(port, "0123456789abcdef")
            _status, body = self._post(port, self._press(), settle=False)
            job_id = json.loads(body)["job"]["id"]
            self.assertTrue(entered.wait(10))
            stale, stale_body = self._cancel(port, "0123456789abcdef")
            unknown, unknown_body = self._cancel(port, job_id, sid="no-such-session")
            self.assertIs(False, self._board_job(port)["cancelling"])
            release.set()
            self._settle()
        self.assertEqual([409, 409, 409], [idle, stale, unknown])
        # One body for all three, so a guessed session id learns nothing.
        self.assertEqual({"ok": False, "reason": "not-running"}, json.loads(stale_body))
        self.assertEqual(stale_body, unknown_body)
        self.assertEqual(stale_body, idle_body)
        self.assertEqual([{"produced": True, "reason": ""}], self.outcomes)

    def test_a_cancel_without_the_press_marks_or_a_job_id_is_refused(self) -> None:
        config, state = self._runtime()
        with self._held_model(), self._serving(self._app(config, state)) as port:
            for over in ({"press": False}, {"observer_model": 0}, {"job": 7}, {"sid": ""}):
                with self.subTest(over=over):
                    status, _ = self._cancel(port, "0123456789abcdef", **over)
                    self.assertEqual(400, status)

    def test_an_oversized_cancel_is_refused_before_it_is_read(self) -> None:
        config, state = self._runtime()
        with self._held_model(), self._serving(self._app(config, state)) as port:
            status, _ = self._cancel(
                port, "0123456789abcdef", pad="x" * (config.annotation_body_cap_bytes + 16)
            )
        self.assertEqual(413, status)

    def test_the_board_never_shows_the_job_gone_before_its_outcome_is_counted(self) -> None:
        """The walk's W1: a collection that began before the write must not stand after it.

        A collection holds the collect lock while the job records, ends and
        publishes. Without the fix it read the store before the write and the
        job registry after the end, and its body then stood as the fresh
        snapshot: no box, the previous sentence, the previous count.
        """
        config, state = self._runtime()
        application = self._app(config, state)
        paused, resume = threading.Event(), threading.Event()
        real = application._collect_harnesses
        collector: dict[str, Any] = {}

        def held(*args: Any, **kwargs: Any) -> Any:
            if threading.current_thread() is collector.get("thread"):
                paused.set()
                resume.wait(10)
            return real(*args, **kwargs)

        def board() -> dict[str, Any]:
            _revision, body = application.collect_json(show_all=False)
            answer: dict[str, Any] = json.loads(body)
            return answer

        with (
            self._held_model() as (release, entered, _calls),
            self._serving(application) as port,
            mock.patch.object(application, "_collect_harnesses", held),
        ):
            _status, body = self._post(port, self._press(), settle=False)
            job_id = json.loads(body)["job"]["id"]
            self.assertTrue(entered.wait(10))

            def collect() -> None:
                application.state.snapshot.clear()
                collector["body"] = json.loads(application.collect_json(show_all=False)[1])

            collector["thread"] = threading.Thread(target=collect, daemon=True)
            collector["thread"].start()
            self.assertTrue(paused.wait(10))
            canceller = threading.Thread(
                target=runtime_reading_jobs.cancel,
                args=(application, "pi:s1", job_id),
                daemon=True,
            )
            canceller.start()
            release.set()
            self.assertTrue(
                self._until(lambda: not runtime_reading.published_jobs(config)),
                "the job never ended",
            )
            resume.set()
            collector["thread"].join(10)
            canceller.join(10)
            self._settle()
            published = board()
        # The collection that straddled the end shows the job or its outcome,
        # never neither: it samples the registry before it reads the store.
        straddled = collector["body"]
        first = next(r for r in straddled["sessions"] if r.get("sid") == "s1")
        self.assertTrue(
            straddled["reading_jobs"] or first["annotation_reading_count"] == 1,
            "a collection published the job gone beside the previous count",
        )
        row = next(r for r in published["sessions"] if r.get("sid") == "s1")
        self.assertEqual({}, published["reading_jobs"])
        self.assertEqual(1, row["annotation_reading_count"])
        self.assertEqual(
            runtime_reading.WITHHELD[runtime_reading.WITHHELD_CANCELLED],
            row["annotation_reading_withheld"],
        )

    def test_a_cancel_writes_no_consent_and_reserves_nothing(self) -> None:
        config, state = self._runtime()
        reading_policy.set_consent(config, False, now=1_700_000_100.0)
        with (
            self._held_model(),
            self._serving(self._app(config, state)) as port,
        ):
            status, _ = self._cancel(port, "0123456789abcdef", allow=True)
        self.assertEqual(409, status)
        answer = reading_policy.status(config, now=1_700_000_100.0)
        self.assertFalse(answer["consent"])
        self.assertEqual(0, answer["used"])


class AnnotateRouteTest(unittest.TestCase):
    """POST /api/annotate over a real socket.

    `test_annotations` covers the store. This covers the wiring, and one thing
    the store cannot: a body field that is not a string. `records.safe_text`
    does `str(value or "")`, so a dict reaching it publishes its Python repr,
    which is why `/api/ask` type-checks before redacting and this does too.
    """

    def _runtime(self, **changes: Any) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        return make_runtime(state_home=home, state_dir=Path(home), **changes)

    @contextlib.contextmanager
    def _serving(self, application: Any) -> Any:
        httpd = make_server(application=application)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def _post(port: int, body: bytes, *, declared: str | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            if declared is None:
                conn.request(
                    "POST", "/api/annotate", body=body, headers={"Content-Type": "text/plain"}
                )
            else:
                conn.putrequest("POST", "/api/annotate")
                conn.putheader("Content-Length", declared)
                conn.endheaders()
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    @staticmethod
    def _get_data(port: int) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/data")
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    @staticmethod
    def _get_annotations(port: int) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/api/annotations")
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_settling_a_later_direction_is_a_third_arm_on_this_route(self) -> None:
        """DRC-4508's baseline-conflict block writes its answer here.

        A third arm rather than a route of its own: the subject is the same
        session's annotation and the reply shape is the same, so the POST
        inventory's width is unchanged.
        """
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=time.time)
        with self._serving(application) as port:
            typed, _ = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "goal": "Ship the cockpit"}
                ).encode(),
            )
            settled, body = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "settle_through": 1.0}
                ).encode(),
            )

        self.assertEqual((200, 200), (typed, settled))
        self.assertIs(True, json.loads(body)["persisted"])
        entry = annotation_store.find(annotation_store.load(config), "claude", "abcd1234")
        assert entry is not None
        mark = entry.get("settled")
        assert mark is not None
        self.assertEqual(1.0, mark["through"])
        self.assertEqual(1, mark["revision"])

    def test_settling_a_session_nobody_annotated_answers_persisted_false(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=time.time)
        with self._serving(application) as port:
            status, body = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "settle_through": 1.0}
                ).encode(),
            )

        self.assertEqual(200, status)
        # There is no baseline to answer about, so nothing is written and the
        # reply says so rather than minting an empty annotation to hang a mark on.
        self.assertIs(False, json.loads(body)["persisted"])
        self.assertEqual((), annotation_store.load(config))

    def test_an_unwritable_store_answers_ok_with_persisted_false(self) -> None:
        """DRC-4533: the reply the page's `unpersisted` cue is written against.

        Both existing assertions on this key are `True`. The endpoint answers
        `persisted` honestly and the page treats a false as "held for this run
        and about to go", so the false arm is the one carrying a promise to a
        reader, and it was the untested one.
        """
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        # The server keeps a usable state_dir; only the annotation store's home
        # is a file, so `save()`'s makedirs fails while everything else serves.
        blocked = Path(home) / "annotation-home"
        blocked.write_text("not a directory", encoding="utf-8")
        config, state = make_runtime(state_home=str(blocked), state_dir=Path(home))
        application = cli.build_application(config, state, clock=time.time)
        with self._serving(application) as port:
            status, body = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "goal": "Ship the cockpit"}
                ).encode(),
            )

        self.assertEqual(200, status)
        answer = json.loads(body)
        # `ok` is not a claim the write landed, and the page reads them apart.
        self.assertIs(True, answer["ok"])
        self.assertIs(False, answer["persisted"])
        # The revision is still minted and served, because this process holds it.
        self.assertEqual(1, answer["revision"])
        # And nothing reached disk, which is what makes the cue's wording true.
        self.assertEqual((), annotation_store.load(config))

    def test_the_reply_names_the_outcome_beside_persisted(self) -> None:
        """DRC-4543: `persisted` is one bit and the page has four sentences.

        `persisted` keeps its meaning (true whenever the words are on disk,
        which an unchanged save's are), and `outcome` says which branch the
        store took, so the page can tell a refusal from a failed write and a
        minted revision from a repeat of the last one.
        """
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=time.time)
        with self._serving(application) as port:
            _, stored = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "goal": "Ship the cockpit"}
                ).encode(),
            )
            _, unchanged = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "goal": "Ship the cockpit"}
                ).encode(),
            )
            _, refused = self._post(
                port,
                json.dumps({"harness": "claude", "sid": "nobody", "settle_through": 1.0}).encode(),
            )

        blocked = Path(tempfile.mkdtemp()) / "annotation-home"
        self.addCleanup(shutil.rmtree, blocked.parent, True)
        blocked.write_text("not a directory", encoding="utf-8")
        config, state = make_runtime(state_home=str(blocked), state_dir=blocked.parent)
        application = cli.build_application(config, state, clock=time.time)
        with self._serving(application) as port:
            _, unwritable = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "goal": "Ship the cockpit"}
                ).encode(),
            )

        answers = {
            name: json.loads(body)
            for name, body in (
                ("stored", stored),
                ("unchanged", unchanged),
                ("refused", refused),
                ("unwritable", unwritable),
            )
        }
        self.assertEqual(
            {
                "stored": (True, "stored"),
                "unchanged": (True, "unchanged"),
                "refused": (False, "refused"),
                "unwritable": (False, "unwritable"),
            },
            {name: (a["persisted"], a.get("outcome")) for name, a in answers.items()},
        )
        # The unchanged save minted nothing, and the reply itself says so.
        self.assertEqual(1, answers["stored"]["revision_count"])
        self.assertEqual(1, answers["unchanged"]["revision_count"])

    def test_a_typed_goal_reaches_the_store_and_drops_the_published_body(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=time.time)
        with self._serving(application) as port:
            # Warm the published body: without `snapshot.clear()` in the handler
            # this is the response the next GET would reuse.
            first = self._get_data(port)
            status, body = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "abcd1234", "goal": "Ship the cockpit"}
                ).encode(),
            )
        self.assertEqual((200, 200), (first, status))
        answer = json.loads(body)
        self.assertIs(True, answer["persisted"])
        self.assertEqual(1, answer["revision"])
        entry = annotation_store.find(annotation_store.load(config), "claude", "abcd1234")
        assert entry is not None
        self.assertEqual("Ship the cockpit", entry["revisions"][-1]["goal"])
        self.assertIsNone(
            state.snapshot.current((config.window_hours, False)),
            "the published body survived the save and would be served again",
        )

    def test_a_field_that_is_not_a_string_is_refused_rather_than_stringified(self) -> None:
        """`safe_text` would publish a dict's repr. 400 rather than a quiet 200.

        The same hazard `/api/ask` type-checks for, and the reason it checks
        before redacting rather than after.
        """
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _ = self._post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "s", "goal": {"k": "AKIAQQQQQQQQQQQQQQQQ"}}
                ).encode(),
            )
        self.assertEqual(400, status)
        self.assertEqual((), annotation_store.load(config))

    def test_a_non_string_identity_is_refused_too(self) -> None:
        """`harness` and `sid` reach `safe_text` by the same path the text does.

        An earlier version checked only the two text fields, which let a dict
        harness land a store entry keyed on its Python repr.
        """
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _ = self._post(
                port, json.dumps({"harness": {"k": "v"}, "sid": ["a"], "goal": "x"}).encode()
            )
        self.assertEqual(400, status)
        self.assertEqual((), annotation_store.load(config))

    def test_clearing_removes_what_was_typed(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "goal": "G"}).encode())
            status, body = self._post(
                port, json.dumps({"harness": "pi", "sid": "s", "clear": True}).encode()
            )
        self.assertEqual(200, status)
        self.assertIsNone(json.loads(body)["revision"])
        # What was typed is gone; what stands in its place is a record with no
        # revisions and no text (DRC-4565).
        stored = annotation_store.load(config)
        self.assertEqual(1, len(stored))
        self.assertEqual((), stored[0]["revisions"])
        self.assertNotIn("G", json.dumps(stored[0]))

    def test_the_reply_says_a_discard_landed_only_where_one_did(self) -> None:
        """DRC-4565. Discarding nothing answered exactly like discarding words.

        Measured on the walk: a clear against a session that never existed and
        a clear against one holding two revisions came back byte-identical.
        The reply now carries the record's own moment, which is None where no
        record was made, so the wire says which of the two happened.
        """
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "goal": "G"}).encode())
            _s, real = self._post(
                port, json.dumps({"harness": "pi", "sid": "s", "clear": True}).encode()
            )
            _s2, empty = self._post(
                port, json.dumps({"harness": "pi", "sid": "never", "clear": True}).encode()
            )

        landed, nothing = json.loads(real), json.loads(empty)
        self.assertNotEqual(nothing, landed)
        self.assertIsNotNone(landed["discarded"])
        self.assertIsNone(nothing["discarded"])

    def test_a_save_over_a_discard_reports_the_entry_live_and_the_record_gone(self) -> None:
        """The reborn entry does not describe itself as the first thing ever
        typed here: two revisions went, so the next is 3."""
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "goal": "one"}).encode())
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "goal": "two"}).encode())
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "clear": True}).encode())
            _status, body = self._post(
                port, json.dumps({"harness": "pi", "sid": "s", "goal": "three"}).encode()
            )

        answer = json.loads(body)
        self.assertEqual(annotation_store.OUTCOME_STORED, answer["outcome"])
        self.assertEqual(3, answer["revision"])
        self.assertEqual(1, answer["revision_count"])
        self.assertIsNone(answer["discarded"])

    def test_clearing_withdraws_what_was_raised_against_the_cleared_words(self) -> None:
        """DRC-4514. `SECURITY.md` says a clear takes the words off this route.

        `annotations.clear` deletes every revision and reaches no other store,
        and `/api/annotations` began serving the departure store on the same
        branch, so the invariant went false: measured end to end, a goal cleared
        and replaced served the withdrawn clause verbatim under a model's
        sentence about it. The ROW survives, because it is what bounds the
        lane's spend, and only its quotations go.
        """
        config, state = self._runtime()
        departures.record(
            config,
            [
                {
                    "harness": "pi",
                    "sid": "s",
                    "at": 1_000.0,
                    "constraint": "TYPED GOAL",
                    "clause": "never touch production credentials in this run",
                    "reading": "It reached for the deploy key.",
                    "evidence": "turn transcript",
                    "revision": 1,
                    "cutoff": 1_000.0,
                    "cutoff_text": "Read 4 of the 4 entries after your words.",
                    "withdrawn": False,
                }
            ],
        )
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            self._post(
                port,
                json.dumps(
                    {
                        "harness": "pi",
                        "sid": "s",
                        "goal": "never touch production credentials in this run",
                    }
                ).encode(),
            )
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "clear": True}).encode())
            self._post(
                port,
                json.dumps({"harness": "pi", "sid": "s", "goal": "ship the cockpit"}).encode(),
            )
            status, body = self._get_annotations(port)

        self.assertEqual(200, status)
        rows = json.loads(body)["annotations"]
        self.assertEqual(1, len(rows))
        self.assertEqual([], rows[0]["departures"])
        self.assertNotIn("production credentials", body.decode())
        self.assertNotIn("It reached for the deploy key.", body.decode())
        # The row itself stays: a withdrawal is not a refund of the subprocess
        # those checks spent.
        stored = departures.load(config)
        self.assertEqual(1, len(stored))
        self.assertIs(True, stored[0]["withdrawn"])
        self.assertEqual("", stored[0]["clause"])

    def test_the_reply_to_a_clear_carries_the_token_the_control_reads(self) -> None:
        """DRC-4561. The discard control picks its sentence from `outcome`.

        A clear answers one of three of the four tokens — it never mints and
        never repeats a revision, so `unchanged` is unreachable from it — and
        `revision_count` is 0 because there is no entry left to publish one.
        The page's three discard sentences rest on exactly that.
        """
        config, state = self._runtime()
        annotation_store.annotate(config, state, "pi", "s", goal="Ship the cockpit")
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            _status, body = self._post(
                port, json.dumps({"harness": "pi", "sid": "s", "clear": True}).encode()
            )

        answer = json.loads(body)
        self.assertIs(True, answer["ok"])
        self.assertEqual(annotation_store.OUTCOME_STORED, answer["outcome"])
        self.assertIn(
            answer["outcome"],
            (
                annotation_store.OUTCOME_STORED,
                annotation_store.OUTCOME_REFUSED,
                annotation_store.OUTCOME_UNWRITABLE,
            ),
        )
        self.assertIsNone(answer["revision"])
        self.assertEqual(0, answer["revision_count"])
        self.assertIs(True, answer["withdrew"])

    def test_a_clear_says_when_the_quotations_did_not_go_with_the_words(self) -> None:
        """DRC-4561. A discard is one act over two stores, and one can fail.

        The entry is gone by then and cannot be put back, so this is not a
        failed clear: it is a landed one with an effect missing. The route
        threw `departures.withdraw`'s answer away, so the reply said `stored`
        and the board printed "nothing raised against those words quotes them
        any more" over rows it was about to redraw with those words in them.
        """
        config, state = self._runtime()
        annotation_store.annotate(config, state, "pi", "s", goal="do not touch the board")
        departures.record(
            config,
            [
                {
                    "harness": "pi",
                    "sid": "s",
                    "at": 1_000.0,
                    "constraint": "TYPED GOAL",
                    "clause": "do not touch the board",
                    "reading": "It edited the running board.",
                    "evidence": "turn transcript",
                    "revision": 1,
                    "cutoff": 1_000.0,
                    "cutoff_text": "",
                    "withdrawn": False,
                }
            ],
        )
        # What an unwritable departure store looks like from the route: its own
        # except branch answers False and the row stays as it was.
        with (
            mock.patch.object(departures, "save", return_value=False),
            self._serving(cli.build_application(config, state, clock=time.time)) as port,
        ):
            _status, body = self._post(
                port, json.dumps({"harness": "pi", "sid": "s", "clear": True}).encode()
            )

        answer = json.loads(body)
        self.assertEqual(annotation_store.OUTCOME_STORED, answer["outcome"])
        self.assertIs(False, answer["withdrew"])
        # And the reply is honest about both halves at once: the words the
        # reader typed are gone, and the quotation of them is not.
        entry = annotation_store.find(annotation_store.load(config), "pi", "s")
        assert entry is not None
        self.assertEqual((), entry["revisions"])
        self.assertNotIn("do not touch the board", json.dumps(entry))
        self.assertEqual("do not touch the board", departures.load(config)[0]["clause"])
        # The durable record of the act stands beside the standing quotation,
        # which is the state DRC-4565 must not let the surfaces describe as
        # both gone and quoted (AC6). The record says only that the words went.
        self.assertIsNotNone(answer["discarded"])

    def test_emptying_both_fields_is_not_the_clear_that_withdraws_a_raise(self) -> None:
        """DRC-4514, walked on the board, and the reason `SECURITY.md` says which.

        The `clear` control beside each field empties the box; the save that
        follows is a revision with an empty string, and every earlier revision
        stays on disk. `clear: true` is a different act -- it deletes them all
        -- and it is the only one that withdraws a raise. Walked end to end:
        pressing `clear` and `save` on both fields left `/api/annotations`
        serving the departure clause verbatim, which is correct, because the
        words themselves are still in the store two revisions up.
        """
        config, state = self._runtime()
        departures.record(
            config,
            [
                {
                    "harness": "pi",
                    "sid": "s",
                    "at": 1_000.0,
                    "constraint": "TYPED GOAL",
                    "clause": "never touch production credentials in this run",
                    "reading": "It reached for the deploy key.",
                    "evidence": "turn transcript",
                    "revision": 1,
                    "cutoff": 1_000.0,
                    "cutoff_text": "Read 4 of the 4 entries after your words.",
                    "withdrawn": False,
                }
            ],
        )
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            self._post(
                port,
                json.dumps(
                    {
                        "harness": "pi",
                        "sid": "s",
                        "goal": "never touch production credentials in this run",
                    }
                ).encode(),
            )
            # What the two controls on the board actually send.
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "goal": ""}).encode())
            self._post(port, json.dumps({"harness": "pi", "sid": "s", "output": ""}).encode())
            status, body = self._get_annotations(port)

        self.assertEqual(200, status)
        rows = json.loads(body)["annotations"]
        self.assertEqual(1, len(rows))
        self.assertEqual(1, len(rows[0]["departures"]))
        self.assertIn("production credentials", body.decode())
        stored = departures.load(config)
        self.assertIs(False, stored[0]["withdrawn"])

    def test_the_off_switch_answers_503_rather_than_404(self) -> None:
        """503 for `/api/dismiss`'s reason: under the off switch the route
        exists and the store does not, and 404 would read as a build too old."""
        config, state = self._runtime(annotations_enabled=False)
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _ = self._post(port, json.dumps({"harness": "pi", "sid": "s"}).encode())
        self.assertEqual(503, status)

    def test_an_oversized_declared_length_is_refused_before_any_read(self) -> None:
        config, state = self._runtime()
        with self._serving(cli.build_application(config, state, clock=time.time)) as port:
            status, _body = self._post(port, b"", declared="200000")
        self.assertEqual(413, status)


class LaneRouteTest(unittest.TestCase):
    """POST /api/lane over a real socket.

    The route DEC-19 opened, and the whole of what makes it safe is what it
    refuses. It carries lane availability and may never carry a delivery, so a
    body naming a session is rejected outright rather than having its session
    quietly dropped: a client that smuggles one and gets a 200 has been told
    its per-raise claim was accepted.
    """

    def _runtime(self, **changes: Any) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        return make_runtime(state_home=home, state_dir=Path(home), **changes)

    @contextlib.contextmanager
    def _serving(self, application: Any) -> Any:
        httpd = make_server(application=application)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def _post(port: int, body: bytes, *, declared: str | None = None) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            if declared is None:
                conn.request("POST", "/api/lane", body=body, headers={"Content-Type": "text/plain"})
            else:
                conn.putrequest("POST", "/api/lane")
                conn.putheader("Content-Length", declared)
                conn.endheaders()
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_a_granted_lane_is_recorded_with_the_servers_own_clock(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=lambda: 4_242.0)
        with self._serving(application) as port:
            status, body = self._post(
                port, json.dumps({"supported": True, "permission": "granted"}).encode()
            )

        self.assertEqual(200, status)
        self.assertIs(True, json.loads(body)["reported"])
        self.assertEqual(4_242.0, state.lane_reported_at)

    def test_a_body_naming_a_session_is_refused_on_the_response(self) -> None:
        # AC6. Asserted on the response and not only on the store: a 200 with
        # the session dropped tells the client its claim was accepted.
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=lambda: 4_242.0)
        for field in ("sid", "session", "session_id", "harness", "resume_id"):
            with self.subTest(field=field):
                with self._serving(application) as port:
                    status, body = self._post(
                        port,
                        json.dumps(
                            {"supported": True, "permission": "granted", field: "s-1"}
                        ).encode(),
                    )

                self.assertEqual(400, status)
                self.assertIn(b"names a session", body)
                self.assertEqual(0.0, state.lane_reported_at)

    def test_a_tab_without_a_lane_neither_records_nor_clears(self) -> None:
        # Several tabs can be open, so one tab reporting that IT has no lane
        # says nothing about another that has one. Only a working lane is a
        # report; the absence of one is the sentence's own subject.
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=lambda: 4_242.0)
        with self._serving(application) as port:
            self._post(port, json.dumps({"supported": True, "permission": "granted"}).encode())
            status, body = self._post(
                port, json.dumps({"supported": True, "permission": "denied"}).encode()
            )

        self.assertEqual(200, status)
        self.assertIs(False, json.loads(body)["reported"])
        self.assertEqual(4_242.0, state.lane_reported_at)

    def test_the_response_echoes_nothing_a_client_sent(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=lambda: 4_242.0)
        with self._serving(application) as port:
            _status, body = self._post(
                port,
                json.dumps({"supported": True, "permission": "granted", "note": "abc123"}).encode(),
            )

        self.assertNotIn(b"abc123", body)
        self.assertEqual({"ok", "reported"}, set(json.loads(body)))

    def test_a_malformed_body_is_refused_rather_than_read_as_a_report(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=lambda: 4_242.0)
        with self._serving(application) as port:
            status, _body = self._post(port, b"[]")

        self.assertEqual(400, status)
        self.assertEqual(0.0, state.lane_reported_at)

    def test_an_oversized_declared_length_is_refused_before_any_read(self) -> None:
        config, state = self._runtime()
        application = cli.build_application(config, state, clock=lambda: 4_242.0)
        with self._serving(application) as port:
            status, _body = self._post(port, b"", declared="200000")

        self.assertEqual(413, status)
        self.assertEqual(0.0, state.lane_reported_at)


class ASaveDuringACollectionTest(RuntimeTestCase):
    """DRC-4760 through the real route: the saving page's refresh carries what it saved.

    A collection reads the annotation store near its start and publishes when its
    harness scan ends. Here one starts (a poll, say) between the handler's window
    read and its write, and is held inside its scan until the save has answered and
    the page's refresh is queued behind it. Before the snapshot carried a
    generation, the held collection published the pre-save words over the save's
    clear and the refresh was served them.
    """

    @staticmethod
    def _request(port: int, method: str, body: dict[str, Any] | None = None) -> Any:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            path = "/api/annotate" if body is not None else "/api/data"
            payload = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "text/plain"} if payload else {}
            conn.request(method, path, body=payload, headers=headers)
            return json.loads(conn.getresponse().read())
        finally:
            conn.close()

    def test_a_reader_whose_save_lands_mid_collection_gets_the_saved_words_on_refresh(
        self,
    ) -> None:
        pinned = SERVER_STARTED + 300.0
        answers: dict[str, Any] = {}
        inside, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as tmp:
            seeded = fixtures.build_claude(
                Path(tmp), pinned - 120.0, "5eeded00-1111-2222-3333-444444444444", "seeded"
            )
            home = Path(tmp) / "home"
            home.mkdir()
            with (
                store_patch(**seeded),
                mock.patch.dict(os.environ, {COMPASS_HOME_ENV: str(home)}),
            ):
                application = build_app()
                # Pinned, so a kept body never ages past the floor on its own.
                application.clock = lambda: pinned
                httpd = make_server(application=application)
                thread = serve_until_closed(httpd)
                port = httpd.server_port
                try:
                    row = self._request(port, "GET")["sessions"][0]
                    who = {"harness": row["harness"], "sid": row["sid"]}
                    first = self._request(port, "POST", {**who, "goal": "First words"})
                    self._request(port, "GET")
                    held = {"armed": False}
                    scan = application._collect_harnesses
                    write = annotation_store.annotate

                    def held_scan(*args: Any) -> Any:
                        if held["armed"]:
                            held["armed"] = False
                            inside.set()
                            release.wait(10)
                        return scan(*args)

                    def poll_then_write(*args: Any, **kwargs: Any) -> Any:
                        # The published body has aged past the floor, so the
                        # poll collects rather than reusing it.
                        application.snapshot.clear()
                        held["armed"] = True
                        poll = threading.Thread(
                            target=lambda: answers.__setitem__("poll", self._request(port, "GET"))
                        )
                        poll.start()
                        answers["poll_thread"] = poll
                        self.assertTrue(inside.wait(10), "the poll never reached its scan")
                        return write(*args, **kwargs)

                    with (
                        mock.patch.object(application, "_collect_harnesses", side_effect=held_scan),
                        mock.patch.object(
                            annotation_store, "annotate", side_effect=poll_then_write
                        ),
                    ):
                        saved = self._request(
                            port,
                            "POST",
                            {**who, "goal": "Second words", "expected_revision": first["revision"]},
                        )
                        refresh = threading.Thread(
                            target=lambda: answers.__setitem__(
                                "refresh", self._request(port, "GET")
                            )
                        )
                        refresh.start()
                        release.set()
                        answers["poll_thread"].join(10)
                        refresh.join(10)
                finally:
                    release.set()
                    httpd.shutdown()
                    thread.join(timeout=5)

        self.assertEqual("stored", saved["outcome"])
        after = answers["refresh"]["sessions"][0]
        self.assertEqual("Second words", after["annotation_goal"])
        self.assertEqual(saved["revision"], after["annotation_revision"])


class ConsentNoticeHandlerTest(unittest.TestCase):
    """Exercise real press admission and jobs without binding a listening socket."""

    def _exercise(self, name: str) -> None:
        fixture = ReadingRouteTest(name)
        self.addCleanup(fixture.doCleanups)
        application: Any = None

        @contextlib.contextmanager
        def serving(app: Any) -> Any:
            nonlocal application
            application = app
            fixture.outcomes = []
            record_reading = annotation_store.record_reading
            record_withheld = annotation_store.record_withheld

            def written(*args: Any, **kwargs: Any) -> Any:
                fixture.outcomes.append({"produced": True, "reason": ""})
                return record_reading(*args, **kwargs)

            def withheld(*args: Any, **kwargs: Any) -> Any:
                fixture.outcomes.append(
                    {"produced": False, "reason": kwargs["reason"], "spent": kwargs["spent"]}
                )
                return record_withheld(*args, **kwargs)

            with (
                mock.patch.object(annotation_store, "record_reading", written),
                mock.patch.object(annotation_store, "record_withheld", withheld),
            ):
                yield 4601
                fixture._settle()

        def post(
            port: int, payload: Any, *, settle: bool = True, **kwargs: Any
        ) -> tuple[int, bytes]:
            handler: Any = object.__new__(http_api._RequestHandler)
            handler.server = SimpleNamespace(application=application, server_port=port)
            handler.client_address = ("127.0.0.1", port)
            handler.headers = email.message.Message()
            body = json.dumps(payload).encode()
            handler.headers["Host"] = f"127.0.0.1:{port}"
            handler.headers["Content-Length"] = str(len(body))
            for key, value in kwargs.get("headers", {}).items():
                handler.headers[key] = value
            handler.rfile = io.BytesIO(body)
            responses: list[tuple[int, bytes]] = []
            with mock.patch.object(
                handler,
                "_send",
                side_effect=lambda body, _type, code=200: responses.append((code, body)),
            ):
                handler._reading()
            if settle and responses[0][0] == 202:
                fixture._settle()
            return responses[0]

        with (
            mock.patch.object(fixture, "_serving", serving),
            mock.patch.object(fixture, "_post", post),
            mock.patch.object(
                fixture,
                "_data",
                lambda _port: json.loads(application.collect_json(show_all=False)[1]),
            ),
        ):
            getattr(fixture, name)()

    def test_fresh_press_notice_off_and_turn_on(self) -> None:
        self._exercise("test_fresh_press_runs_with_notice_then_off_blocks_until_resume")

    def test_pause_during_analyze_admission_sends_nothing(self) -> None:
        self._exercise("test_readings_turned_off_mid_press_and_left_off_send_nothing")

    def test_claude_tool_output_defaults_on(self) -> None:
        self._exercise("test_a_fresh_claude_reading_includes_tool_output_without_a_grant")

    def test_changed_destination_runs_with_new_notice(self) -> None:
        self._exercise("test_a_changed_destination_runs_with_a_new_notice")

    def test_content_tier_migration_runs_with_a_notice(self) -> None:
        self._exercise("test_prior_claude_content_versions_run_with_a_notice")


class SummaryStoreHTTPTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store = summary_store
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config, self.state = make_runtime(
            state_home=self.temp.name,
            state_dir=Path(self.temp.name),
            model_calls_disabled=True,
            annotations_enabled=False,
        )
        self.path = Path(self.temp.name) / "session.jsonl"
        transcript = Transcript(Path(self.temp.name))
        transcript.prompt("Inspect the parser")
        transcript.save(self.path)
        page = session_source.read(self.config, str(self.path), "claude", "root")
        assert page.coverage is not None and page.snapshot is not None
        summary = session_summary.summarize(
            page.entries,
            page.coverage,
            "claude",
            config=self.config,
            model=Replies(),
            clock=lambda: 0.0,
        )
        self.assertEqual(
            "stored",
            summary_store.put(
                self.config,
                "claude",
                "root",
                summary,
                page.snapshot,
                made_at=100.0,
                model_stamp="synthetic-model",
            ),
        )
        self.application: Any = aggregate.Application(
            self.config,
            self.state,
            (),
            native_notifier=lambda _: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _: None,
        )
        self.row = {"harness": "claude", "sid": "root", "project": "synthetic", "ended_at": 90.0}
        patcher = mock.patch.object(
            self.application,
            "collect_json",
            return_value=(
                (1.0, 1),
                json.dumps({"sessions": [self.row]}).encode(),
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @contextlib.contextmanager
    def serving(self) -> Any:
        try:
            server = make_server(application=self.application)
        except PermissionError:
            self.skipTest("sandbox denies loopback socket binding")
        thread = threading.Thread(target=poll_fast(server), daemon=True)
        thread.start()
        try:
            yield server.server_port
        finally:
            server.shutdown()
            thread.join(3)
            server.server_close()

    @staticmethod
    def request(
        port: int,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            raw = response.read()
            return response.status, json.loads(raw) if response.status == 200 else raw
        finally:
            conn.close()

    def test_focused_reopen_serves_a_stored_summary_without_a_model_call(self) -> None:
        """Serving only: generating on first open and its summary ledger belong to the job lane.

        Models are off and the summary is saved before the first open, so this cannot catch an
        open that starts a summary job; the ledger asserted is the Analyze reading ledger.
        """
        with (
            self.serving() as port,
            mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(runtime_observer, "prepare_claude_exec") as claude,
            mock.patch.object(runtime_observer, "codex_exec") as codex,
            mock.patch.object(session_summary, "summarize") as model_seam,
        ):
            for _ in range(2):
                status, answer = self.request(
                    port, "GET", "/api/project-context?project=synthetic&session=claude:root"
                )
                self.assertEqual(200, status)
                summary = answer["sources"]["summary"]
                self.assertTrue(summary["exists"])
                self.assertEqual("synthetic-model", summary["model_stamp"])
                self.assertEqual("unchanged", summary["out_of_date"]["kind"])
                self.assertEqual(1, len(summary["blocks"]))
            self.assertEqual(0, claude.call_count + codex.call_count + model_seam.call_count)
            status, answer = self.request(port, "GET", "/api/project-context?project=synthetic")
            self.assertNotIn("summary", answer["sources"])
        self.assertEqual(0, reading_policy.status(self.config, now=time.time())["used"])

    def test_delete_route_works_with_annotations_and_models_off(self) -> None:
        with self.serving() as port:
            status, answer = self.request(
                port, "POST", "/api/summary/delete", b'{"harness":"claude","sid":"root"}'
            )
        self.assertEqual(200, status)
        self.assertEqual("deleted", answer["outcome"])
        self.assertIsNone(self.store.get(self.config, "claude", "root"))

    def test_delete_refuses_navigation_cross_site_and_host_before_store_or_body(self) -> None:
        with self.serving() as port, mock.patch.object(self.store, "delete") as delete:
            for headers in (
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                {"Sec-Fetch-Site": "cross-site"},
                {"Sec-Fetch-Site": "same-site"},
                {"Host": "example.com"},
                {"Origin": "https://example.com"},
            ):
                with self.subTest(headers=headers):
                    status, _answer = self.request(
                        port, "POST", "/api/summary/delete", b"invalid JSON", headers
                    )
                    self.assertEqual(403, status)
            delete.assert_not_called()
        self.assertIsNotNone(self.store.get(self.config, "claude", "root"))

    def handler(
        self, path: str = "/api/summary/delete", body: bytes = b'{"harness":"claude","sid":"root"}'
    ) -> Any:
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = SimpleNamespace(application=self.application, server_port=12345)
        handler.path = path
        handler.headers = {"Content-Length": str(len(body)), "Host": "127.0.0.1:12345"}
        handler.client_address = ("127.0.0.1", 10000)
        handler.rfile = io.BytesIO(body)
        handler._send = mock.Mock()
        handler._reject = mock.Mock()
        handler.send_error = mock.Mock()
        return handler

    def test_focused_handler_serves_second_open_without_a_model(self) -> None:
        handler = self.handler()
        with (
            mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(runtime_observer, "prepare_claude_exec") as claude,
            mock.patch.object(runtime_observer, "codex_exec") as codex,
            mock.patch.object(session_summary, "summarize") as model_seam,
        ):
            for _ in range(2):
                handler._project_context(
                    urlparse("/api/project-context?project=synthetic&session=claude:root")
                )
                answer = json.loads(handler._send.call_args.args[0])
                self.assertEqual("unchanged", answer["sources"]["summary"]["out_of_date"]["kind"])
                self.assertEqual("synthetic-model", answer["sources"]["summary"]["model_stamp"])
                self.assertIsNone(answer["sources"]["summary"]["plan"])
            self.assertEqual(0, claude.call_count + codex.call_count + model_seam.call_count)
        self.assertEqual(0, reading_policy.status(self.config, now=time.time())["used"])

    def test_delete_handler_removes_only_the_summary(self) -> None:
        handler = self.handler()
        handler.do_POST()
        handler._reject.assert_not_called()
        self.assertEqual("deleted", json.loads(handler._send.call_args.args[0])["outcome"])
        self.assertIsNone(self.store.get(self.config, "claude", "root"))

    def test_delete_handler_guards_run_before_reading_body_or_store(self) -> None:
        for headers in (
            {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Sec-Fetch-Site": "same-site"},
            {"Host": "example.com"},
            {"Origin": "https://example.com"},
        ):
            with self.subTest(headers=headers):
                handler = self.handler(body=b"invalid JSON")
                handler.headers.update(headers)
                with mock.patch.object(self.store, "delete") as delete:
                    handler.do_POST()
                    handler._reject.assert_called_once_with(403)
                    delete.assert_not_called()
                    self.assertEqual(0, handler.rfile.tell())


class SummaryJobHTTPTest(unittest.TestCase):
    temp: Any
    config: Any
    state: Any
    store: Any
    path: Path
    application: Any
    row: dict[str, Any]

    def handler(self, path: str = "/api/summary", body: bytes = b"{}") -> Any:
        factory: Any = SummaryStoreHTTPTest.handler
        return factory(self, path, body)

    def setUp(self) -> None:
        setup: Any = SummaryStoreHTTPTest.setUp
        setup(self)
        self.jobs = summary_jobs
        self.config = dataclasses.replace(self.config, model_calls_disabled=False)
        self.application.config = self.config
        row_patcher = mock.patch.object(
            http_api._RequestHandler, "_published_row", return_value=self.row
        )
        row_patcher.start()
        self.addCleanup(row_patcher.stop)
        self.store.delete(self.config, "claude", "root")
        patcher = mock.patch.object(runtime_supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def request_summary(self, **changes: Any) -> Any:
        body = json.dumps(
            {"harness": "claude", "sid": "root", "action": "start", "origin": "open", **changes}
        ).encode()
        handler = self.handler("/api/summary", body)
        handler.do_POST()
        return handler

    def test_second_open_with_models_enabled_makes_no_call_and_no_summary_charge(self) -> None:
        model = Replies()
        with (
            mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.jobs, "ClaudeSummaryModel", return_value=model),
        ):
            first = self.request_summary()
            self.assertEqual(202, first._send.call_args.args[2])
            wait_job(self.application, "claude", "root", timeout=5)
            calls = len(model.prompts)
            used = reading_policy.summary_status(self.config, now=self.application.clock())["used"]
            second = self.request_summary()
            self.assertEqual("summary-exists", json.loads(second._send.call_args.args[0])["reason"])
            focused = self.handler()
            focused._project_context(
                urlparse("/api/project-context?project=synthetic&session=claude:root")
            )
            saved = json.loads(focused._send.call_args.args[0])["sources"]["summary"]
            self.assertTrue(saved["exists"])
            self.assertEqual("unchanged", saved["out_of_date"]["kind"])
            self.assertEqual(1, len(saved["blocks"]))
            self.assertEqual(calls, len(model.prompts))
            self.assertEqual(
                used,
                reading_policy.summary_status(self.config, now=self.application.clock())["used"],
            )
            self.assertEqual(2, used)

    def test_open_refuses_running_session_and_stored_summary(self) -> None:
        self.row["ended_at"] = None
        self.assertEqual(
            "session-running", json.loads(self.request_summary()._send.call_args.args[0])["reason"]
        )

    def test_plan_refusal_reports_largest_read_before_first_call(self) -> None:
        self.application.config = dataclasses.replace(self.config, session_summary_max_calls=1)
        with mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(self.path)):
            answer = json.loads(self.request_summary()._send.call_args.args[0])
        self.assertEqual("planned_calls", answer["reason"])
        self.assertEqual(1, answer["largest_read"]["calls"])
        self.assertEqual(
            0, reading_policy.summary_status(self.config, now=self.application.clock())["used"]
        )

    def test_summary_routes_refuse_before_reading_body_or_store(self) -> None:
        for path in ("/api/summary", "/api/summary/cancel", "/api/summary/delete"):
            for headers in (
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                {"Sec-Fetch-Site": "cross-site"},
                {"Origin": "https://evil.example"},
                {"Host": "evil.example"},
            ):
                handler = self.handler(path, b"invalid")
                handler.headers.update(headers)
                with (
                    mock.patch.object(
                        handler, "_read_body", side_effect=AssertionError("body read")
                    ),
                    mock.patch.object(self.store, "load", side_effect=AssertionError("store read")),
                ):
                    handler.do_POST()
                handler._reject.assert_called_once_with(403)
            handler = self.handler(path)
            handler.client_address = ("192.0.2.1", 9999)
            with mock.patch.object(handler, "_read_body", side_effect=AssertionError("body read")):
                handler.do_POST()
            handler._reject.assert_called_once_with(403)

    def discard(self) -> dict[str, Any]:
        handler = self.handler("/api/annotate", b'{"harness":"claude","sid":"root","clear":true}')
        handler.do_POST()
        answer: dict[str, Any] = json.loads(handler._send.call_args.args[0])
        return answer

    def summarize_to_the_end(self) -> None:
        with (
            mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.jobs, "ClaudeSummaryModel", return_value=Replies()),
        ):
            self.request_summary()
            wait_job(self.application, "claude", "root", timeout=5)
        self.assertIsNotNone(self.store.get(self.config, "claude", "root"))

    def test_discard_everything_stops_a_running_summary_and_deletes_the_store_entry(self) -> None:
        # The owner's ruling of 2026-10-21 reverses the earlier rule that the summary survives:
        # a discard stops the job as Delete summary does, then removes the saved summary, so the
        # reply returning from the model cannot bring the text back.
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Inspect parser", output="", now=100.0
        )
        entered, release = threading.Event(), threading.Event()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            entered.set()
            self.assertTrue(release.wait(5))
            return Replies()(prompt, output_cap_bytes=output_cap_bytes)

        with (
            mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.jobs, "ClaudeSummaryModel", return_value=model),
        ):
            self.request_summary()
            self.assertTrue(entered.wait(5))
            try:
                answer = self.discard()
            finally:
                release.set()
            wait_job(self.application, "claude", "root", timeout=5)
        # Nothing was stored and a job was: the reply says the job was stopped, which `absent` cannot.
        self.assertEqual("stopped", answer["summary"])
        self.assertIsNone(self.store.get(self.config, "claude", "root"))
        self.assertEqual("discarded", self.state.summary_jobs["claude:root"].reason)
        self.assertEqual("cancelled", self.state.summary_jobs["claude:root"].state)

    def test_discard_everything_deletes_a_saved_summary_and_says_so(self) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Inspect parser", output="", now=100.0
        )
        self.summarize_to_the_end()
        answer = self.discard()
        self.assertEqual("deleted", answer["summary"])
        self.assertIsNone(self.store.get(self.config, "claude", "root"))

    def test_a_discard_that_removed_no_words_leaves_the_summary_alone(self) -> None:
        # Nothing typed means nothing was discarded, and a summary does not depend on saved intent,
        # so a hand-made request must not take it.
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        self.summarize_to_the_end()
        answer = self.discard()
        self.assertEqual("untouched", answer["summary"])
        self.assertIsNotNone(self.store.get(self.config, "claude", "root"))

    def test_a_discard_names_how_many_revisions_it_took_and_no_more(self) -> None:
        # DRC-4939. The count is the store's, read under its lock, and null where the arm is not
        # a discard, so a figure of zero is a discard that found nothing.
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="First", output="", now=100.0
        )
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Second", output="", now=101.0
        )
        self.assertEqual(2, self.discard()["removed"])
        self.assertEqual(0, self.discard()["removed"])

    def test_a_second_discard_over_a_discarded_session_says_a_record_stands(self) -> None:
        # A repeat press removes nothing, as a press over words never typed does, but a discard
        # record exists. The reply carries the stamp that tells the page which zero it is, and the
        # server owns a sentence that is true of it rather than "nothing was typed".
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        never = self.discard()
        self.assertEqual(0, never["removed"])
        self.assertIsNone(never["discarded"])
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Words", output="", now=100.0
        )
        first = self.discard()
        again = self.discard()
        self.assertEqual(1, first["removed"])
        self.assertEqual(0, again["removed"])
        self.assertIsNotNone(again["discarded"])
        said = annotation_store.DISCARD_SENTENCES
        self.assertIn("already", said)
        self.assertNotIn("Nothing was typed", said["already"])
        self.assertNotIn("no record", said["already"])
        self.assertIn("earlier", said["already"])

    def test_a_discard_without_a_stored_summary_says_none_existed(self) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Inspect parser", output="", now=100.0
        )
        answer = self.discard()
        self.assertEqual("absent", answer["summary"])
        self.assertEqual(1, answer["removed"])

    def test_a_discard_takes_the_summary_when_this_dashboards_copy_is_stale(self) -> None:
        # DRC-4939. The words were saved from another tab after this dashboard last read the
        # store, so its cached copy holds nothing. The summary was left standing under words that
        # had gone, because the route decided on that copy.
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Inspect parser", output="", now=100.0
        )
        self.summarize_to_the_end()
        self.state.annotations = ()
        self.assertIsNone(
            annotation_store.find(
                annotation_store.active(self.config, self.state), "claude", "root"
            )
        )
        answer = self.discard()
        self.assertEqual("deleted", answer["summary"])
        self.assertEqual(1, answer["removed"])
        self.assertIsNone(self.store.get(self.config, "claude", "root"))

    def test_a_discard_says_the_summary_store_was_unavailable_and_does_not_claim_it_gone(
        self,
    ) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Inspect parser", output="", now=100.0
        )
        Path(self.store.store_path(self.config)).write_text("not json", encoding="utf-8")
        answer = self.discard()
        self.assertEqual("unavailable", answer["summary"])
        self.assertEqual(1, answer["removed"])

    def test_the_discard_sentences_say_only_what_happened_to_the_summary(self) -> None:
        said = annotation_store.DISCARD_SENTENCES
        # A summary that went, one that never existed, one that is still stored, and one the
        # store could not be read to tell: four sentences, each claiming only its own case.
        self.assertIn("its summary", said["stored"])
        self.assertIn("no stored summary", said["stored_no_summary"])
        self.assertIn("still stored", said["summary_kept"])
        self.assertNotIn("still stored", said["summary_unavailable"])
        self.assertNotIn("Delete summary removes it", said["summary_unavailable"])
        # A job stopped with nothing stored, and a token this build does not know, each say only that.
        self.assertIn("was stopped", said["summary_stopped"])
        self.assertNotIn("still stored", said["summary_stopped"])
        self.assertIn("may still be stored", said["summary_unknown"])
        self.assertNotIn(
            "its summary", said["summary_unknown"].replace("this session's summary", "")
        )
        # Reopening writes a new summary unless summaries are off: said wherever the store was
        # read and no summary stands, and not where one may still stand or the store is unreadable.
        for name in ("stored", "stored_no_summary", "summary_stopped"):
            with self.subTest(name=name):
                self.assertIn("unless summaries are turned off", said[name])
        for name in ("summary_kept", "summary_unavailable", "summary_unknown"):
            with self.subTest(name=name):
                self.assertNotIn("unless summaries are turned off", said[name])

    def test_the_armed_discard_derives_its_lapse_from_the_cue_window(self) -> None:
        self.assertIn(
            f"lapses in {annotation_store.CUE_WINDOW_SECONDS} seconds",
            annotation_store.DISCARD_ARMED,
        )

    def test_a_discard_keeps_the_record_that_a_check_ran(self) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.application.config = self.config
        annotation_store.annotate(
            self.config, self.state, "claude", "root", goal="Inspect parser", output="", now=100.0
        )
        answer = self.discard()
        self.assertIsNotNone(answer["discarded"])
        entry = annotation_store.find(
            annotation_store.active(self.config, self.state), "claude", "root"
        )
        self.assertTrue(annotation_store.is_discarded(entry))

    def test_consent_route_does_not_touch_reading_or_goal_and_off_survives_restart(self) -> None:
        reading_policy.note(
            self.config,
            kind="goal",
            provider="codex",
            destination="OpenAI",
            content=4,
            tool_output="",
            now=100.0,
        )
        before = reading_policy.status(self.config, now=100.0)
        for consent in ("off", "on", "off"):
            handler = self.handler("/api/summary", json.dumps({"consent": consent}).encode())
            handler.do_POST()
            self.assertEqual(200, handler._send.call_args.args[2])
            self.assertEqual(before, reading_policy.status(self.config, now=100.0))
        config, _ = make_runtime(state_home=self.temp.name, state_dir=Path(self.temp.name))
        self.assertEqual(
            "summaries-off", reading_policy.summary_status(config, now=100.0)["reason"]
        )

    def test_pause_and_resume_leave_the_summary_switch_exactly_as_stored(self) -> None:
        for allowed in (False, True):
            reading_policy.set_consent(self.config, True, now=100.0)
            original = reading_policy.set_summary_consent(self.config, allowed, now=100.0)
            pause = self.handler(
                "/api/reading",
                b'{"consent":"off","press":true,"observer_model":1}',
            )
            pause.do_POST()
            self.assertEqual(200, pause._send.call_args.args[2])
            for consent in ("off", "on"):
                switch = self.handler("/api/summary", json.dumps({"consent": consent}).encode())
                switch.do_POST()
                self.assertEqual(403, switch._send.call_args.args[2])
                self.assertEqual(
                    "model-calls-paused",
                    json.loads(switch._send.call_args.args[0])["reason"],
                )
            for origin in ("open", "press"):
                refused = self.request_summary(origin=origin)
                self.assertEqual(403, refused._send.call_args.args[2])
                self.assertEqual(
                    "model-calls-paused",
                    json.loads(refused._send.call_args.args[0])["reason"],
                )
            resume = self.handler(
                "/api/reading",
                b'{"consent":"on","press":true,"observer_model":1}',
            )
            resume.do_POST()
            self.assertEqual(200, resume._send.call_args.args[2])
            self.assertEqual({}, self.state.summary_jobs)
            self.assertEqual(original, reading_policy.summary_status(self.config, now=100.0))

    def test_malformed_summary_values_are_refused_without_model_work(self) -> None:
        payload: dict[str, Any]
        for payload in (
            {"consent": []},
            {"consent": {}},
            {"consent": True},
            {"harness": "claude", "sid": "root", "action": [], "origin": "press"},
        ):
            handler = self.handler("/api/summary", json.dumps(payload).encode())
            handler.do_POST()
            handler._reject.assert_called_once_with(400)

    def test_summary_mutations_report_publication_lock_failure(self) -> None:
        for path, payload in (
            ("/api/summary", {"consent": "off"}),
            ("/api/summary/cancel", {"harness": "claude", "sid": "root"}),
            ("/api/summary/delete", {"harness": "claude", "sid": "root"}),
        ):
            handler = self.handler(path, json.dumps(payload).encode())
            with mock.patch.object(
                summary_jobs, "_locked", side_effect=OSError("lock unavailable")
            ):
                handler.do_POST()
            reply = json.loads(handler._send.call_args.args[0])
            self.assertIn(
                reply.get("reason") or reply.get("outcome"), ("store-unavailable", "unwritable")
            )

    def test_turn_off_readings_refuses_and_stops_session_summaries(self) -> None:
        # After Pause model calls no session summary call is made until Resume model calls.
        entered, release = threading.Event(), threading.Event()
        replies = Replies()

        def model(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            entered.set()
            self.assertTrue(release.wait(5))
            return replies(prompt, output_cap_bytes=output_cap_bytes)

        off = json.dumps({"consent": "off", "press": True, "observer_model": 1}).encode()
        with (
            mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.jobs, "ClaudeSummaryModel", return_value=model),
        ):
            self.request_summary(origin="press")
            self.assertTrue(entered.wait(5))
            try:
                self.handler("/api/reading", off).do_POST()
            finally:
                release.set()
            wait_job(self.application, "claude", "root", timeout=5)
            self.assertEqual("model-calls-paused", self.state.summary_jobs["claude:root"].reason)
            self.assertEqual(1, len(replies.prompts))
            self.assertIsNone(self.store.get(self.config, "claude", "root"))
            refused = self.request_summary(origin="press")
            self.assertEqual(403, refused._send.call_args.args[2])
            answer = json.loads(refused._send.call_args.args[0])
            self.assertEqual("model-calls-paused", answer["reason"])
            self.assertFalse(answer["summaries"]["consent"])
            self.assertEqual(1, len(replies.prompts))
