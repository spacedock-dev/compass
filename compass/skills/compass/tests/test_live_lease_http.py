"""`POST /api/live-monitor` over a real socket and a real transcript.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check):
the lease state is published on the focused context's `sources.work` and on no session row, the
route is guarded like the reading presses, and Pause and shutdown end every lease.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.client
import io
import json
import unittest
from typing import Any, ClassVar
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    http_api,
    live_lease,
    reading,
    reading_jobs,
    reading_policy,
    reading_route,
    terminal_client,
)

from .support import make_server, serve_until_closed
from .test_claude_checks import SHORT, START
from .test_compass_skill_action import CompassSession
from .test_copied_corrections import STORED
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


class ATerminalReaderStartsWithTheirIntent(LeaseRoute):
    def setUp(self) -> None:
        _Replay.setUp(self)
        patch = mock.patch.object(reading_route, "destination", return_value="api.anthropic.com")
        patch.start()
        self.addCleanup(patch.stop)
        self.session.save(self.path)

    def saved(self) -> Any:
        return annotation_store.find(annotation_store.load(self.config), "claude", SHORT)

    def test_a_person_s_stated_goal_takes_priority_over_their_opening_prompt(self) -> None:
        goal = {"text": "Ship the parser", "at": START.timestamp() + 10}
        with self.serving(self.app(session_goal=goal)) as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertEqual("session-goal", answer["terminal"]["goal"]["source"])
        self.assertEqual(goal["text"], self.saved()["revisions"][-1]["goal"])

    def test_a_person_s_latest_prompt_is_used_when_the_first_has_no_source_time(self) -> None:
        asked = {"label": "asked", "text": "Ship the lexer", "at": START.timestamp() + 10}
        with self.serving(self.app(first_prompt_at=None, instruction=asked)) as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertEqual("latest-prompt", answer["terminal"]["goal"]["source"])
        self.assertEqual(asked["at"], self.saved()["revisions"][-1]["goal_source_at"])

    def test_a_person_s_control_prompt_does_not_become_a_goal(self) -> None:
        asked = {"label": "asked", "text": "Ship the lexer", "at": START.timestamp() + 10}
        with self.serving(self.app(first_prompt_control=True, instruction=asked)) as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertEqual("missing", answer["terminal"]["goal_status"])
        self.assertIsNone(self.saved())

    def test_a_person_s_copied_correction_is_not_adopted(self) -> None:
        at, _ = self.pasted()
        with self.serving(self.app(first_prompt=STORED, first_prompt_at=at)) as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertEqual("missing", answer["terminal"]["goal_status"])
        self.assertIsNone(self.saved())

    def test_a_person_sees_the_saved_excerpt_rather_than_the_uncut_draft(self) -> None:
        words = "Ship the parser. " * 1000
        with self.serving(self.app(first_prompt=words)) as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
        saved = self.saved()["revisions"][-1]["goal"]
        self.assertNotEqual(words, saved)
        self.assertEqual(saved, answer["terminal"]["goal"]["text"])

    def test_a_person_s_discarded_intent_stays_discarded(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", SHORT, goal=GOAL, now=NOW)
        annotation_store.clear(self.config, self.state, "claude", SHORT, now=NOW + 1)
        with self.serving() as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertEqual("missing", answer["terminal"]["goal_status"])
        self.assertTrue(annotation_store.is_discarded(self.saved()))

    def test_a_model_started_command_saves_no_goal_records_no_notice_and_starts_no_lease(
        self,
    ) -> None:
        session = CompassSession(self.root / "work")
        session.prompt("Ship the parser")
        session.model_started_compass("Keep going.")
        session.save(self.path)
        with self.serving() as port:
            _, answer = self.lease(port, "start", holder_kind="terminal", typed_action="monitor on")
            self.assertEqual("typed-command-required", answer["reason"])
            self.assertIsNone(self.application.live_leases)
        self.assertIsNone(self.saved())
        self.assertEqual({}, reading_policy.status(self.config, now=NOW)["notices"])

    def test_a_person_can_retry_their_typed_command_after_adoption_fails(self) -> None:
        session = CompassSession(self.root / "work")
        session.prompt("Ship the parser")
        session.compass("monitor on", stop=False)
        session.save(self.path)
        with self.serving() as port:
            with mock.patch.object(
                annotation_store, "adopt", return_value=annotation_store.OUTCOME_REFUSED
            ):
                _, refused = self.lease(
                    port, "start", holder_kind="terminal", typed_action="monitor on"
                )
            self.assertFalse(refused["ok"])
            self.assertFalse(refused["state"]["on"])
            _, retried = self.lease(
                port, "start", holder_kind="terminal", typed_action="monitor on"
            )
            self.assertTrue(retried["ok"])

    def test_a_person_s_concurrent_outcome_line_wins_over_a_drafted_goal(self) -> None:
        adopt = annotation_store.adopt

        def racing(*args: Any, **kwargs: Any) -> str:
            annotation_store.annotate(
                self.config, self.state, "claude", SHORT, goal="", lines=[LINE], now=NOW
            )
            return adopt(*args, **kwargs)

        with (
            self.serving() as port,
            mock.patch.object(annotation_store, "adopt", side_effect=racing),
        ):
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertTrue(answer["ok"])
        self.assertEqual("existing", answer["terminal"]["goal_status"])
        self.assertNotIn("goal", answer["terminal"])
        self.assertEqual("", self.saved()["revisions"][-1]["goal"])

    def test_a_person_who_discards_their_empty_intent_during_a_terminal_start_keeps_it_discarded(
        self,
    ) -> None:
        annotation_store.annotate(self.config, self.state, "claude", SHORT, goal="", now=NOW)
        adopt = annotation_store.adopt
        discarded = []

        def racing(*args: Any, **kwargs: Any) -> str:
            annotation_store.clear(self.config, self.state, "claude", SHORT, now=NOW + 1)
            discarded.append(self.saved())
            return adopt(*args, **kwargs)

        with (
            self.serving() as port,
            mock.patch.object(annotation_store, "adopt", side_effect=racing),
        ):
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertFalse(answer["ok"])
        self.assertFalse(answer["state"]["on"])
        self.assertNotIn("terminal", answer)
        self.assertTrue(annotation_store.is_discarded(self.saved()))
        self.assertEqual(discarded[0], self.saved())

    def test_a_person_whose_start_is_refused_after_preparation_still_sees_the_disclosure_next_time(
        self,
    ) -> None:
        with self.serving() as port:
            with mock.patch.object(
                live_lease.Leases, "_start_refusal", side_effect=["", "unavailable"]
            ):
                _, refused = self.lease(port, "start", holder_kind="terminal")
            self.assertFalse(refused["ok"])
            self.assertFalse(refused["state"]["on"])
            self.assertNotIn("terminal", refused)
            self.assertEqual({}, reading_policy.status(self.config, now=NOW)["notices"])
            _, accepted = self.lease(port, "start", holder_kind="terminal")
            self.assertTrue(accepted["ok"])
            self.assertTrue(accepted["terminal"]["notice_due"])

    def test_a_person_sees_the_disclosure_even_when_its_notice_cannot_be_recorded(self) -> None:
        with (
            self.serving() as port,
            mock.patch.object(
                reading_policy,
                "note",
                side_effect=reading_policy.RefusedError(
                    {
                        **reading_policy.status(self.config, now=NOW),
                        "reason": "store-unavailable",
                    }
                ),
            ),
        ):
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertTrue(answer["ok"])
        self.assertTrue(answer["terminal"]["notice_due"])
        self.assertIn("Sends to api.anthropic.com", answer["terminal"]["disclosure"])
        self.assertEqual({}, reading_policy.status(self.config, now=NOW)["notices"])

    def test_a_person_reads_when_terminal_checks_run_and_how_to_stop_them(self) -> None:
        with self.serving() as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
        text = answer["terminal"]["disclosure"]
        self.assertIn("checks after new work in this session, at most about once a minute", text)
        self.assertIn("spacedock-compass --monitor --off from a shell", text)
        self.assertIn("/compass:compass monitor off in the session", text)
        self.assertIn("Pause model calls stops it.", text)
        self.assertNotIn("terminal holder", text)
        self.assertNotIn("heartbeats", text)
        self.assertNotIn("no confirmation question", text)

    def test_a_person_s_page_draft_is_saved_before_the_ticker_can_start(self) -> None:
        seen = []

        def ticker(_leases: Any) -> None:
            seen.append(self.saved())
            row = http_api._lease_row(self.application, "claude", SHORT)
            assert row is not None
            self.assertEqual(self.saved()["revisions"][-1]["goal"], row["annotation_goal"])

        with (
            self.serving() as port,
            mock.patch.object(live_lease.Leases, "_ensure_ticker_locked", ticker),
        ):
            _, answer = self.lease(port, "start", holder_kind="terminal")
        saved = self.saved()["revisions"][-1]
        self.assertEqual("Add retry with backoff to the webhook handler.", saved["goal"])
        self.assertEqual("first-prompt", saved["goal_source"])
        self.assertEqual(START.timestamp() + 5, saved["goal_source_at"])
        self.assertTrue(seen[0])
        self.assertEqual("adopted", answer["terminal"]["goal_status"])
        self.assertEqual(saved["n"], answer["terminal"]["goal"]["saved_revision"])
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW)["used"])

    def test_a_person_sees_the_notice_once_then_again_for_a_new_destination_or_wider_tier(
        self,
    ) -> None:
        with self.serving() as port:
            _, first = self.lease(port, "start", holder_kind="terminal")
            published = self.focused(port)["sources"]["work"]["live_monitor"]
            self.assertFalse(published["notice_due"])
            _, repeat = self.lease(port, "start", holder_kind="terminal")
            self.assertTrue(first["terminal"]["notice_due"])
            self.assertFalse(repeat["terminal"]["notice_due"])
            with mock.patch.object(reading_route, "destination", return_value="other.example"):
                _, changed = self.lease(port, "start", holder_kind="terminal")
                self.assertTrue(changed["terminal"]["notice_due"])
                with mock.patch.object(reading_policy, "WORDS_CONTENT_VERSION", 999):
                    _, wider = self.lease(port, "start", holder_kind="terminal")
                    self.assertTrue(wider["terminal"]["notice_due"])
        self.assertIn("--monitor --off", first["state"]["disclosure"])
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW)["used"])

    def test_a_person_without_a_draft_has_an_on_monitor_and_no_charge(self) -> None:
        with (
            self.serving(self.app(first_prompt=None, first_prompt_at=None)) as port,
            mock.patch.object(live_lease.Leases, "_ensure_ticker_locked"),
        ):
            _, answer = self.lease(port, "start", holder_kind="terminal")
            self.assertTrue(answer["state"]["on"])
            self.assertEqual("missing", answer["terminal"]["goal_status"])
            self.assertIn(f"/#n=session:billing:claude:{SHORT}", answer["terminal"]["page_url"])
            self.assertIsNone(self.saved())
            with mock.patch.object(self.application.live_leases, "_runner") as model:
                self.application.live_leases.step()
                model.assert_not_called()
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW)["used"])

    def test_a_person_who_pauses_and_resumes_gets_the_disclosure_again(self) -> None:
        with self.serving() as port:
            _, first = self.lease(port, "start", holder_kind="terminal")
            self.assertTrue(first["terminal"]["notice_due"])
            reading_policy.set_consent(self.config, False, now=NOW)
            reading_policy.set_consent(self.config, True, now=NOW + 1)
            _, resumed = self.lease(port, "start", holder_kind="terminal")
            self.assertTrue(resumed["terminal"]["notice_due"])

    def test_a_person_refused_by_the_ordinary_switches_saves_nothing(self) -> None:
        for disabled in (False, True):
            with self.subTest(disabled=disabled):
                self.config = dataclasses.replace(self.config, model_calls_disabled=disabled)
                reading_policy.set_consent(self.config, False, now=NOW)
                with self.serving() as port:
                    _, answer = self.lease(port, "start", holder_kind="terminal")
                self.assertFalse(answer["ok"])
                self.assertFalse(answer["state"]["on"])
                self.assertIsNone(self.saved())
                self.assertEqual({}, reading_policy.status(self.config, now=NOW)["notices"])

    def test_a_person_s_saved_outcome_lines_are_not_given_an_adopted_goal(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="", lines=[LINE], now=NOW
        )
        with self.serving() as port:
            _, answer = self.lease(port, "start", holder_kind="terminal")
            self.lease(port, "start", tab_id="browser")
            row = http_api._lease_row(self.application, "claude", SHORT)
            assert row is not None
            inputs = http_api._lease_inputs(self.application, "claude", SHORT, row)
        self.assertEqual("existing", answer["terminal"]["goal_status"])
        self.assertEqual("", self.saved()["revisions"][-1]["goal"])
        assert inputs is not None
        self.assertIn(LINE, inputs.intent)

    def test_another_person_s_concurrent_saved_goal_wins_without_a_stale_receipt(self) -> None:
        adopt = annotation_store.adopt

        def racing(*args: Any, **kwargs: Any) -> str:
            annotation_store.annotate(
                self.config, self.state, "claude", SHORT, goal=GOAL, lines=[LINE], now=NOW
            )
            return adopt(*args, **kwargs)

        with (
            self.serving() as port,
            mock.patch.object(annotation_store, "adopt", side_effect=racing),
        ):
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertTrue(answer["ok"])
        self.assertEqual("existing", answer["terminal"]["goal_status"])
        self.assertNotIn("goal", answer["terminal"])
        self.assertEqual(GOAL, self.saved()["revisions"][-1]["goal"])

    def test_a_person_whose_goal_cannot_be_saved_gets_no_lease_or_notice(self) -> None:
        with (
            self.serving() as port,
            mock.patch.object(
                annotation_store, "adopt", return_value=annotation_store.OUTCOME_REFUSED
            ),
        ):
            _, answer = self.lease(port, "start", holder_kind="terminal")
        self.assertFalse(answer["ok"])
        self.assertFalse(answer["state"]["on"])
        self.assertTrue(
            reading_policy.notice_due(
                reading_policy.monitor_status(self.config, now=NOW),
                kind="monitor",
                provider="claude",
                destination="api.anthropic.com",
                content=reading_policy.WORDS_CONTENT_VERSION,
                tool_output="api.anthropic.com",
            )
        )


class AReaderChoosesTheHolderKind(LeaseRoute):
    def test_a_browser_reader_is_not_given_terminal_notice_metadata(self) -> None:
        with self.serving() as port:
            _, browser = self.lease(port, "start")
            self.assertNotIn("notice_due", browser["state"])
            _, terminal = self.lease(port, "start", tab_id="terminal", holder_kind="terminal")
            self.assertIn("notice_due", terminal["state"])
            self.lease(port, "stop", tab_id="terminal")
            self.assertNotIn("notice_due", self.focused(port)["sources"]["work"]["live_monitor"])

    def test_a_terminal_reader_gets_no_browser_clock_and_an_older_caller_gets_one(self) -> None:
        with self.serving() as port:
            status, terminal = self.lease(port, "start", holder_kind="terminal")
            self.assertEqual((200, True), (status, terminal["ok"]))
            self.assertIsNone(terminal["state"]["deadline"])
            _, beat = self.lease(port, "beat", holder_kind="browser")
            self.assertIsNone(beat["state"]["deadline"])
            self.lease(port, "stop")
            _, browser = self.lease(port, "start")
            self.assertIsNotNone(browser["state"]["deadline"])

    def test_a_reader_sending_a_malformed_kind_is_refused_before_collection_or_a_lease(
        self,
    ) -> None:
        with self.serving() as port, mock.patch.object(http_api, "_lease_row") as collect:
            kinds: tuple[Any, ...] = (None, "", "Terminal", "other", 1, True, [], {})
            for kind in kinds:
                with self.subTest(kind=kind):
                    status, _ = self.lease(port, "start", holder_kind=kind)
                    self.assertEqual(400, status)
                    self.assertIsNone(self.application.live_leases)
                    collect.assert_not_called()


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
    def test_a_person_can_pause_from_either_side_and_see_the_board_stop_ordinary_jobs(self) -> None:
        for source in ("page", "terminal"):
            with self.subTest(source=source), self.serving() as port:
                reading_policy.set_consent(self.config, True, now=self.application.clock())
                self.lease(port, "start")
                job = reading_jobs.start_job(
                    self.config, "codex:ordinary", provider="codex", label="Codex", now=NOW
                )
                assert job is not None
                group = mock.Mock()
                reading.hand_over(job, group)
                try:
                    if source == "page":
                        status, _ = self.call(
                            port,
                            "POST",
                            "/api/reading",
                            {"consent": "off", "press": True, "observer_model": 1},
                        )
                        self.assertEqual(200, status)
                    else:
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(0, terminal_client.run_pause_model_calls(port=port))
                    self.assertTrue(reading.job_cancelled(job))
                    group.cancel.assert_called_once()
                    context = self.focused(port)
                    lease = context["sources"]["work"]["live_monitor"]
                    self.assertEqual((False, "paused"), (lease["on"], lease["last_end"]["reason"]))
                    _, board = self.call(port, "GET", "/api/data")
                    self.assertIs(board["reading"]["off"], True)
                finally:
                    reading.end_job(self.config, "codex:ordinary")

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


class SessionLookupTest(unittest.TestCase):
    row: ClassVar[dict[str, str]] = {
        "harness": "claude",
        "sid": "abcdefab",
        "resume_id": "abcdefab-1111-4111-8111-111111111111",
    }

    @contextlib.contextmanager
    def serving(self, default: list[Any], all_rows: list[Any]) -> Any:
        httpd = make_server()

        def collect(*, show_all: bool) -> tuple[int, bytes]:
            return 1, json.dumps({"sessions": all_rows if show_all else default}).encode()

        with mock.patch.object(httpd.application, "collect_json", side_effect=collect):
            thread = serve_until_closed(httpd)
            try:
                yield httpd.server_port
            finally:
                httpd.shutdown()
                thread.join(timeout=5)

    def test_a_person_whose_session_has_been_idle_for_a_day_can_still_monitor_it(self) -> None:
        with self.serving([], [self.row]) as port:
            status, body = LeaseRoute.call(
                port, "GET", "/api/session?harness=claude&sid=" + self.row["resume_id"]
            )
        self.assertEqual(200, status)
        self.assertEqual({"session": self.row}, body)

    def test_a_person_can_find_one_session_without_getting_someone_elses_same_prefix_session(
        self,
    ) -> None:
        other = {**self.row, "resume_id": "abcdefab-2222-4222-8222-222222222222"}
        for sid, rows, status, body in (
            ("abcdefab", [self.row], 200, {"session": self.row}),
            (self.row["resume_id"], [self.row, other], 200, {"session": self.row}),
            ("abcdefab", [self.row, other], 409, {"reason": "ambiguous"}),
            (self.row["resume_id"], [other], 404, {"reason": "not-found"}),
            ("missing", [], 404, {"reason": "not-found"}),
        ):
            with self.subTest(sid=sid, status=status), self.serving(rows, rows) as port:
                self.assertEqual(
                    (status, body),
                    LeaseRoute.call(port, "GET", "/api/session?harness=claude&sid=" + sid),
                )

    def test_a_persons_whole_message_words_never_leave_the_single_session_route(self) -> None:
        row = {
            **self.row,
            "reader_words": "private reader sentence",
            "nested": [{"agent_words": "private agent sentence"}],
        }
        with self.serving([row], [row]) as port:
            status, body = LeaseRoute.call(port, "GET", "/api/session?harness=claude&sid=abcdefab")
        self.assertEqual(200, status)
        self.assertEqual({"session": {**self.row, "nested": [{}]}}, body)

    def test_a_persons_session_row_is_refused_to_navigation_and_nonlocal_callers(self) -> None:
        for headers in (
            {"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Host": "evil.example"},
            {"Origin": "https://evil.example"},
        ):
            with self.subTest(headers=headers), self.serving([self.row], [self.row]) as port:
                status, _ = LeaseRoute.call(
                    port, "GET", "/api/session?harness=claude&sid=abcdefab", headers=headers
                )
                self.assertEqual(403, status)
