"""`POST /api/live-monitor` over a real socket and a real transcript.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check):
the lease state is published on the focused context's `sources.work` and on no session row, the
route is guarded like the reading presses, and Pause and shutdown end every lease.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.client
import json
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import http_api, live_lease, reading_policy, reading_route

from .support import make_server, serve_until_closed
from .test_claude_checks import SHORT, START
from .test_live_estimate import GOAL, LINE, _Replay

NOW = 1_700_000_000.0


class _EndedSource:
    """A coordinator that saw this session end: the overlay pass writes its `ended_at`."""

    def __init__(self, *, ended: bool) -> None:
        self.ended = ended

    def overlays_for(self, harness: str, sid: str) -> list[Any]:
        del harness, sid
        return []

    def finished_at(self, harness: str, sid: str) -> float:
        del harness, sid
        return 0.0

    def ended_at(self, harness: str, sid: str) -> float:
        return NOW - 10 if self.ended and (harness, sid) == ("claude", SHORT) else 0.0

    def git_for(self, harness: str, sid: str) -> None:
        del harness, sid

    def focusable(self, harness: str, sid: str) -> bool:
        del harness, sid
        return False

    def note_rows(self, keys: set[tuple[str, str]]) -> None:
        pass

    def command_reports(self) -> list[dict[str, Any]]:
        return []

    def drop_counters(self) -> dict[str, int]:
        return {}


class LeaseRoute(_Replay):
    def setUp(self) -> None:
        super().setUp()
        patch = mock.patch.object(reading_route, "destination", return_value="api.anthropic.com")
        patch.start()
        self.addCleanup(patch.stop)
        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            goal=GOAL,
            lines=[LINE],
            now=START.timestamp() + self.session.seconds + 1,
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.session.save(self.path)

    @contextlib.contextmanager
    def serving(self, application: Any = None) -> Any:
        self.application = application or self.app()
        httpd = make_server(application=self.application)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def call(
        port: int,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            conn.request(
                method,
                path,
                body=raw if method == "POST" else None,
                headers={"Content-Type": "application/json", **(headers or {})},
            )
            response = conn.getresponse()
            data = response.read()
        finally:
            conn.close()
        try:
            return response.status, json.loads(data)
        except ValueError:
            return response.status, data

    def lease(self, port: int, action: str, **extra: Any) -> tuple[int, Any]:
        body = {
            "harness": "claude",
            "sid": SHORT,
            "action": action,
            "tab_id": "tab-a",
            "observer_model": 1,
            **extra,
        }
        return self.call(port, "POST", "/api/live-monitor", body)

    def focused(self, port: int) -> dict[str, Any]:
        status, answer = self.call(
            port, "GET", f"/api/project-context?project=billing&session=claude:{SHORT}"
        )
        self.assertEqual(200, status)
        assert isinstance(answer, dict)
        return answer


class TheRoundTrip(LeaseRoute):
    def test_start_beat_confirm_and_stop(self) -> None:
        with self.serving() as port:
            status, started = self.lease(port, "start")
            self.assertEqual((200, True, True), (status, started["ok"], started["state"]["on"]))
            status, beaten = self.lease(port, "beat", visible=True)
            self.assertEqual((200, True), (status, beaten["ok"]))
            status, hidden = self.lease(port, "beat", visible=False)
            self.assertEqual((200, True, False), (status, hidden["ok"], hidden["state"]["visible"]))
            status, quiet = self.lease(port, "confirm", answer="yes")
            self.assertEqual((200, True), (status, quiet["ok"]))
            status, stopped = self.lease(port, "stop")
            self.assertEqual(
                (False, "stopped"), (stopped["state"]["on"], stopped["state"]["last_end"]["reason"])
            )


class AHiddenTabStartsWithoutTicks(LeaseRoute):
    def test_a_start_that_says_the_tab_is_hidden_holds_the_lease_and_is_not_visible(self) -> None:
        with self.serving() as port:
            _status, started = self.lease(port, "start", visible=False)
            self.assertEqual((True, False), (started["ok"], started["state"]["visible"]))
            status, _again = self.lease(port, "start", visible="no")
        self.assertEqual(400, status)


class AServerThatClosedBuildsNoTicker(LeaseRoute):
    def test_a_table_made_after_the_server_closed_runs_no_thread(self) -> None:
        application = self.app()
        with self.serving(application):
            pass
        self.assertTrue(application.live_leases_closed)
        leases = http_api._live_leases(application)
        leases.start("claude", SHORT, "tab-a")
        self.assertFalse(leases.running())
        leases.close()


class ATwiceListedSessionIsAmbiguousNotGone(LeaseRoute):
    def test_the_lease_row_marks_two_rows_and_a_missing_one_is_none(self) -> None:
        application = self.app()
        row = {"harness": "claude", "sid": SHORT}
        body = json.dumps({"sessions": [row, dict(row)]}).encode()
        application.collect_json = lambda **_: (1, body)  # type: ignore[method-assign,assignment]
        found = http_api._lease_row(application, "claude", SHORT)
        self.assertEqual(True, (found or {}).get("ambiguous"))
        self.assertIsNone(http_api._lease_row(application, "claude", "nobody"))


class TheRouteIsGuardedLikeAPress(LeaseRoute):
    def test_the_refusals_before_anything_is_read(self) -> None:
        with self.serving() as port:
            for headers in (
                {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"},
                {"Sec-Fetch-Site": "cross-site"},
            ):
                status, _ = self.call(
                    port,
                    "POST",
                    "/api/live-monitor",
                    {"harness": "claude", "sid": SHORT, "action": "start", "tab_id": "t"},
                    headers,
                )
                self.assertEqual(403, status)
            for body in (
                b"not json",
                json.dumps([1]).encode(),
                json.dumps({"harness": "claude", "sid": SHORT, "action": "start"}).encode(),
                json.dumps(
                    {"harness": "claude", "sid": SHORT, "action": "dance", "tab_id": "t"}
                ).encode(),
                json.dumps(
                    {"harness": "claude", "sid": "", "action": "start", "tab_id": "t"}
                ).encode(),
                json.dumps(
                    {"harness": "claude", "sid": SHORT, "action": "start", "tab_id": "x" * 500}
                ).encode(),
            ):
                status, _ = self.call(port, "POST", "/api/live-monitor", body)
                self.assertEqual(400, status, body[:40])
            # Nothing above reached the table: a refusal is answered before a lease exists.
            self.assertIsNone(self.application.live_leases)

    def test_a_body_that_is_too_large_is_refused(self) -> None:
        with self.serving() as port:
            status, _ = self.call(port, "POST", "/api/live-monitor", b"{" + b" " * 70_000 + b"}")
            self.assertEqual(413, status)

    def test_a_get_is_not_a_route(self) -> None:
        with self.serving() as port:
            status, _ = self.call(port, "GET", "/api/live-monitor")
            self.assertEqual(404, status)


class StartIsRefused(LeaseRoute):
    def reasons(self, **body: Any) -> str:
        with self.serving() as port:
            status, answer = self.lease(port, "start", **body)
        self.assertEqual(200, status)
        self.assertFalse(answer["ok"])
        return str(answer["reason"])

    def test_for_an_ended_session_read_after_the_overlay_pass(self) -> None:
        application = self.app()
        application.overlays = _EndedSource(ended=True)
        with self.serving(application) as port:
            _status, answer = self.lease(port, "start")
        self.assertEqual((False, "unavailable"), (answer["ok"], answer["reason"]))

    def test_for_a_harness_that_is_not_claude_code(self) -> None:
        self.assertEqual("unsupported-harness", self.reasons(harness="codex"))

    def test_for_the_sample_session(self) -> None:
        self.assertEqual("sample", self.reasons(sid="sample"))

    def test_for_a_session_the_board_does_not_hold(self) -> None:
        self.assertEqual("unavailable", self.reasons(sid="nobody"))

    def test_while_model_calls_are_paused(self) -> None:
        reading_policy.set_consent(self.config, False, now=NOW)
        self.assertEqual("paused", self.reasons())

    def test_under_no_observer_model(self) -> None:
        self.config = dataclasses.replace(self.config, model_calls_disabled=True)
        self.assertEqual("no-observer-model", self.reasons())


class TheStateIsPublishedOnTheFocusedContextOnly(LeaseRoute):
    def test_the_lease_is_on_sources_work_and_on_no_row(self) -> None:
        with self.serving() as port:
            self.lease(port, "start")
            focused = self.focused(port)
            _status, project = self.call(port, "GET", "/api/project-context?project=billing")
            _status, board = self.call(port, "GET", "/api/data")
        published = focused["sources"]["work"]["live_monitor"]
        self.assertEqual((True, "Live monitor · Haiku"), (published["on"], published["label"]))
        self.assertNotIn("live_monitor", project["sources"]["work"])
        dump = json.dumps(board)
        for field in ("live_monitor", "confirm_by", "banner_due_at", "last_end"):
            self.assertNotIn(field, dump)
        for row in board["sessions"]:
            self.assertFalse({"live_monitor", "confirm_by", "banner_due_at"} & set(row))

    def test_a_session_that_has_ended_shows_it_ended_on_the_context(self) -> None:
        application = self.app()
        source = _EndedSource(ended=False)
        application.overlays = source
        with self.serving(application) as port:
            self.lease(port, "start")
            source.ended = True
            application.snapshot.clear()
            application.state.collect_memo_sec = 0  # type: ignore[attr-defined]
            published = self.focused(port)["sources"]["work"]["live_monitor"]
        self.assertEqual((False, "ended"), (published["on"], published["last_end"]["reason"]))


class TheTickerEndsWhatHasEnded(LeaseRoute):
    def test_a_lease_ends_ended_when_the_row_after_the_overlay_pass_gains_an_end(self) -> None:
        application = self.app()
        source = _EndedSource(ended=False)
        application.overlays = source
        with self.serving(application) as port:
            self.lease(port, "start")
            leases = application.live_leases
            source.ended = True
            application.snapshot.clear()
            leases.step()
            self.assertEqual("ended", leases.state("claude", SHORT)["last_end"]["reason"])
            self.assertFalse(leases.state("claude", SHORT)["on"])


class PauseAndShutdown(LeaseRoute):
    def test_pause_ends_every_lease_paused(self) -> None:
        with self.serving() as port:
            self.lease(port, "start")
            status, _ = self.call(
                port, "POST", "/api/reading", {"consent": "off", "press": True, "observer_model": 1}
            )
            self.assertEqual(200, status)
            published = self.focused(port)["sources"]["work"]["live_monitor"]
        self.assertEqual((False, "paused"), (published["on"], published["last_end"]["reason"]))

    def test_shutting_the_server_stops_the_ticker_and_the_leases(self) -> None:
        application = self.app()
        with self.serving(application) as port:
            self.lease(port, "start")
            leases = application.live_leases
            self.assertTrue(leases.running())
        self.assertFalse(leases.running())
        self.assertFalse(leases.state("claude", SHORT)["on"])

    def test_a_restarted_server_has_no_lease_and_makes_no_check(self) -> None:
        with self.serving() as port:
            self.lease(port, "start")
        fresh = self.app()
        with self.serving(fresh) as port:
            published = self.focused(port)["sources"]["work"]["live_monitor"]
            self.assertFalse(published["on"])
            self.assertIsNone(published["last_end"])
        # A read of the focused context made the table, and made no ticker.
        self.assertIsInstance(fresh.live_leases, live_lease.Leases)
        self.assertFalse(fresh.live_leases.running())


if __name__ == "__main__":
    unittest.main()
