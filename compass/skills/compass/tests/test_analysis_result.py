"""The analysis result's server half: the level recomputed on render, and Not accurate (DRC-4695).

Items 6, 10 and 14 of
[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
and items 1 and 2 of
[DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn).
The analysis-derived level is `levels.analysis_level` over the stored reading and the current
record. The focused context carries the calculation. The board publishes a checked result after
revalidating the reading's freshness and citations. The reader's Not accurate mark is a token stored with the annotation entry and nothing
else: removed with the entry, untouched by `--forget`, never sent and never counted.
"""

from __future__ import annotations

import contextlib
import http.client
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from compass_runtime import annotations as annotation_store
from compass_runtime import events, focused_reading, history, http_api, levels, semantic_history
from compass_runtime import reading as runtime_reading

from .support import make_server, serve_until_closed
from .test_claude_checks import SHORT, START
from .test_live_estimate import GOAL, LINE, _Replay

FOCUSED = f"/api/project-context?project=billing&session=claude:{SHORT}"


def _reading(criteria: dict[str, Any], **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "revision_read": 1,
        "stamp": "",
        "cutoff": "",
        "scope": runtime_reading.SCOPE_MID_FLIGHT,
        "scope_text": runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_MID_FLIGHT],
        "ended_at_read": None,
        "read_at": START.timestamp() + 500,
        "criteria": criteria,
    }
    base.update(over)
    return base


def _unverifiable(why: str = runtime_reading.WHY_UNCITED) -> dict[str, Any]:
    return {"result": runtime_reading.RESULT_UNVERIFIABLE, "cites": [], "why": why}


class _Result(_Replay):
    def setUp(self) -> None:
        super().setUp()
        self.entries_saved: list[tuple[str, ...]] = []

    def save_goal(self, *, lines: tuple[str, ...] = (LINE,)) -> None:
        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            goal=GOAL,
            lines=list(lines),
            expected_revision=len(self.entries_saved) or None,
            now=START.timestamp() + self.session.seconds + 1 + len(self.entries_saved),
        )
        self.entries_saved.append(lines)
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)

    def record(self, assessment: dict[str, Any]) -> None:
        outcome = annotation_store.record_reading(
            self.config, self.state, "claude", SHORT, assessment=cast("Any", assessment)
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)

    def entry(self) -> annotation_store.Annotation:
        found = annotation_store.find(annotation_store.load(self.config), "claude", SHORT)
        assert found is not None
        return found

    def raw_entry(self) -> dict[str, Any]:
        with open(annotation_store.store_path(self.config), encoding="utf-8") as handle:
            stored = json.load(handle)
        (entry,) = [e for e in stored["entries"] if e.get("sid") == SHORT]
        assert isinstance(entry, dict)
        return entry

    def mark(self, *, on: bool = True, read_at: Any = None) -> str:
        return annotation_store.mark_not_accurate(
            self.config,
            self.state,
            "claude",
            SHORT,
            read_at=START.timestamp() + 500 if read_at is None else read_at,
            on=on,
        )

    @contextlib.contextmanager
    def serving(self) -> Any:
        httpd = make_server(application=self.app())
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def get(port: int, path: str) -> dict[str, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", path)
            body = conn.getresponse().read()
        finally:
            conn.close()
        answer = json.loads(body)
        assert isinstance(answer, dict)
        return answer

    @staticmethod
    def post(port: int, path: str, body: Any) -> tuple[int, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request(
                "POST",
                path,
                body=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            raw = response.read()
            try:
                return response.status, json.loads(raw)
            except ValueError:
                return response.status, None
        finally:
            conn.close()

    def passing_check(self) -> str:
        checks = [
            f["fact_id"]
            for f in self.facts_now()
            if f.get("subject") == "check" and f.get("result") == "passed"
        ]
        self.assertEqual(1, len(checks))
        return str(checks[0])


class NotAccurateIsATokenAndNothingElseTest(_Result):
    def setUp(self) -> None:
        super().setUp()
        self.save_goal()
        self.record(_reading({"goal": _unverifiable(), "line_1": _unverifiable()}))

    def test_the_mark_stores_only_its_token(self) -> None:
        before, raw_before = dict(self.entry()), self.raw_entry()
        self.assertEqual(annotation_store.OUTCOME_STORED, self.mark())
        after, raw_after = dict(self.entry()), self.raw_entry()
        self.assertEqual({"not_accurate"}, set(raw_after) - set(raw_before))
        self.assertIs(True, raw_after["not_accurate"])
        # Nothing else about the entry moved but when it was written.
        self.assertEqual({"not_accurate"}, set(after) - set(before))
        for name in set(before) - {"written"}:
            self.assertEqual(before[name], after[name], name)
        self.assertIs(True, annotation_store.published(self.entry())["not_accurate"])

    def test_unmarking_removes_the_token(self) -> None:
        self.mark()
        self.assertEqual(annotation_store.OUTCOME_STORED, self.mark(on=False))
        self.assertNotIn("not_accurate", self.raw_entry())
        self.assertIs(False, annotation_store.published(self.entry())["not_accurate"])

    def test_a_mark_lands_only_on_the_reading_the_reader_was_shown(self) -> None:
        for read_at in (START.timestamp() + 499, True, "500", float("nan")):
            with self.subTest(read_at=read_at):
                self.assertEqual(annotation_store.OUTCOME_REFUSED, self.mark(read_at=read_at))
                self.assertNotIn("not_accurate", self.raw_entry())

    def test_a_session_with_no_reading_takes_no_mark(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", "other", goal="Something", now=10.0
        )
        outcome = annotation_store.mark_not_accurate(
            self.config, self.state, "claude", "other", read_at=10.0, on=True
        )
        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "other")
        assert entry is not None
        self.assertNotIn("not_accurate", entry)

    def test_a_new_reading_clears_it_and_a_save_or_a_withheld_press_keeps_it(self) -> None:
        self.mark()
        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            SHORT,
            reason=next(iter(runtime_reading.WITHHELD)),
            spent=False,
        )
        self.assertIs(True, self.raw_entry().get("not_accurate"))
        self.save_goal(lines=(LINE, "The lexer is untouched"))
        self.assertIs(True, self.raw_entry().get("not_accurate"))
        self.record(
            _reading(
                {"goal": _unverifiable(), "line_1": _unverifiable()},
                read_at=START.timestamp() + 900,
            )
        )
        self.assertNotIn("not_accurate", self.raw_entry())

    def test_it_is_removed_with_the_entry_and_forget_does_not_reach_it(self) -> None:
        self.mark()
        annotation_store.forget(self.config)
        self.assertIs(True, self.raw_entry().get("not_accurate"))
        annotation_store.clear(self.config, self.state, "claude", SHORT)
        self.assertNotIn("not_accurate", self.raw_entry())
        self.assertIs(False, annotation_store.published(self.entry())["not_accurate"])

    def test_it_is_never_counted_and_never_enters_history(self) -> None:
        readings = self.entry().get("readings")
        self.mark()
        self.assertEqual(readings, self.entry().get("readings"))
        self.assertNotIn("annotation_not_accurate", history.OBSERVATION_FIELDS)

    def test_the_reading_routes_context_does_not_carry_it(self) -> None:
        self.mark()
        app = self.app()
        _rev, body = app.collect_json(show_all=True)
        row = json.loads(body)["sessions"][0]
        self.assertIs(True, row["annotation_not_accurate"])
        context = http_api._session_context(app, row)
        self.assertNotIn("not_accurate", json.dumps(context))

    def test_a_planted_token_that_is_not_the_token_reads_back_as_none(self) -> None:
        path = annotation_store.store_path(self.config)
        for planted in ("yes", 1, {"why": "the model was wrong"}):
            with self.subTest(planted=planted):
                with open(path, encoding="utf-8") as handle:
                    stored = json.load(handle)
                for entry in stored["entries"]:
                    entry["not_accurate"] = planted
                with open(path, "w", encoding="utf-8") as handle:
                    json.dump(stored, handle)
                self.state.annotations = None
                self.assertNotIn("not_accurate", self.entry())


class NotAccurateRouteTest(_Result):
    def setUp(self) -> None:
        super().setUp()
        self.save_goal()
        self.record(_reading({"goal": _unverifiable(), "line_1": _unverifiable()}))

    def test_the_page_marks_through_the_annotate_route_and_the_row_says_so(self) -> None:
        read_at = START.timestamp() + 500
        with self.serving() as port:
            status, answer = self.post(
                port,
                "/api/annotate",
                {"harness": "claude", "sid": SHORT, "not_accurate": True, "read_at": read_at},
            )
            board = self.get(port, "/api/data")
        self.assertEqual(200, status)
        self.assertEqual(annotation_store.OUTCOME_STORED, answer["outcome"])
        (row,) = [r for r in board["sessions"] if r["sid"] == SHORT]
        self.assertIs(True, row["annotation_not_accurate"])

    def test_a_body_of_the_wrong_shape_is_refused(self) -> None:
        with self.serving() as port:
            for body in (
                {"harness": "claude", "sid": SHORT, "not_accurate": "yes", "read_at": 1.0},
                {"harness": "claude", "sid": SHORT, "not_accurate": True, "read_at": "1"},
                {"harness": "claude", "sid": SHORT, "not_accurate": True},
            ):
                with self.subTest(body=body):
                    status, _answer = self.post(port, "/api/annotate", body)
                    self.assertEqual(400, status)
        self.assertNotIn("not_accurate", self.raw_entry())


class WrittenPathWindowCountOnFocusedContextTest(_Result):
    def test_stored_analysis_cutoff_counts_only_distinct_later_paths(self) -> None:
        self.session.write(str(Path(self.session.cwd) / "old.py"))
        cutoff = START.timestamp() + self.session.seconds + 1
        self.save_goal()
        self.session.write(str(Path(self.session.cwd) / "later.py"))
        self.session.edit(str(Path(self.session.cwd) / "later.py"))
        self.session.save(self.path)
        self.record(
            _reading(
                {"goal": _unverifiable(), "line_1": _unverifiable()},
                revision_read_at=cutoff,
                window_start=cutoff,
            )
        )

        with self.serving() as port:
            focused = self.get(port, FOCUSED)
        (scan,) = [row for row in focused["sources"]["work"]["tool_reports"] if row["sid"] == SHORT]
        self.assertEqual(2, scan["written_paths"])
        self.assertEqual(cutoff, scan["window_start"])
        self.assertEqual(1, scan["window_written_paths"])


class TheAnalysisLevelIsRecomputedOnRenderTest(_Result):
    """Published on the focused project context, from the stored reading, never stored."""

    def consistent_reading(self) -> dict[str, Any]:
        check = self.passing_check()
        return _reading(
            {
                "goal": _unverifiable(),
                "line_1": {
                    "result": runtime_reading.RESULT_CONSISTENT,
                    "cites": [check],
                    "why": runtime_reading.WHY_STANDS,
                },
            },
            window_start=None,
        )

    def test_the_focused_context_publishes_the_function_over_the_reading(self) -> None:
        self.save_goal()
        assessment = self.consistent_reading()
        self.record(assessment)
        with self.serving() as port:
            focused = self.get(port, FOCUSED)
            project = self.get(port, "/api/project-context?project=billing")
            board = self.get(port, "/api/data")
        (row,) = focused["sources"]["work"]["analysis_levels"]
        stored = self.entry()["assessment"]
        facts = tuple(
            f
            for f in focused["semantic"]["facts"]
            if f.get("type") == "tool_report" and f["source_session"]["sid"] == SHORT
        )
        (scan,) = [s for s in focused["sources"]["work"]["tool_reports"] if s["sid"] == SHORT]
        expected = levels.analysis_level(stored, levels.Evidence(facts, scan, 0), outcome_lines=1)
        self.assertEqual(
            ("claude", SHORT, expected.level, list(expected.reasons)),
            (row["harness"], row["sid"], row["level"], row["reasons"]),
        )
        self.assertEqual(stored["read_at"], row["read_at"])
        self.assertEqual(1, row["revision_read"])
        self.assertNotIn("analysis_levels", project["sources"]["work"])
        self.assertEqual("cant_tell", self.board_progress(board))
        self.assertNotIn("analysis_levels", json.dumps(board))
        self.assertNotIn('"level"', json.dumps(board["sessions"]))

    def board_progress(self, board: dict[str, Any]) -> str | None:
        (row,) = [row for row in board["sessions"] if row["sid"] == SHORT]
        return cast("str | None", row["stored_progress"])

    def departure(self) -> dict[str, Any]:
        self.session.write(str(Path(self.session.cwd) / "unrelated.py"))
        cite = next(f["fact_id"] for f in self.facts_now() if f["subject"] == "write")
        through = START.timestamp() + self.session.seconds
        return _reading(
            {
                "goal": {
                    "result": runtime_reading.RESULT_DEPARTURE,
                    "cites": [cite],
                    "why": runtime_reading.WHY_RECORDED_WRITE,
                }
            },
            window_start=START.timestamp(),
            revision_read_at=START.timestamp(),
            read_at=through + 1,
            evidence_through=through,
        )

    def test_cold_board_withholds_departure_when_focus_recovers_an_unsettled_direction(
        self,
    ) -> None:
        self.save_goal(lines=())
        self.session.prompt("Actually make the unrelated change first.")
        for _ in range(64):
            self.session._entry("assistant", [{"type": "text", "text": "x" * 8192}])
        self.record(self.departure())
        with self.serving() as port:
            cold = self.board_progress(self.get(port, "/api/data"))
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.now += self.config.collect_memo_sec + 1
            warm = self.board_progress(self.get(port, "/api/data"))
        self.assertEqual(1, view["unsettled_count"])
        self.assertIsNone(view["pill"])
        self.assertIsNone(view["stale"])
        self.assertEqual("withheld", cold)
        self.assertEqual(cold, warm)

    def test_the_board_revalidates_without_a_network_call_or_a_store_write(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.app()
        store = Path(annotation_store.store_path(self.config))
        before = store.read_bytes()
        semantic_store = Path(semantic_history.store_path(self.config))
        self.assertFalse(semantic_store.exists())
        with (
            patch("socket.socket.connect") as connect,
            patch("socket.socket.connect_ex") as connect_ex,
            patch("socket.getaddrinfo") as resolve,
            patch("subprocess.Popen") as process,
        ):
            board = json.loads(app.collect_json(show_all=True)[1])
        self.assertEqual(levels.MEDIUM, self.board_progress(board))
        for call in (connect, connect_ex, resolve, process):
            call.assert_not_called()
        self.assertEqual(before, store.read_bytes())
        self.assertFalse(semantic_store.exists())
        self.assertNotIn("stored_progress", events.PATCHABLE)
        self.assertNotIn("stored_progress", history.OBSERVATION_FIELDS)
        self.assertNotIn(
            "stored_progress", json.dumps(http_api._session_context(app, board["sessions"][0]))
        )

    def test_the_board_distinguishes_a_saved_goal_without_a_reading(self) -> None:
        self.save_goal()
        with self.serving() as port:
            self.assertIsNone(self.board_progress(self.get(port, "/api/data")))

    def test_board_distinguishes_stale_withheld_and_checked_without_departure(self) -> None:
        self.save_goal(lines=())
        check = self.passing_check()
        assessment = _reading(
            {"goal": {"result": runtime_reading.RESULT_CONSISTENT, "cites": [check]}},
            window_start=START.timestamp(),
            revision_read_at=START.timestamp(),
        )
        self.record(assessment)
        with self.serving() as port:
            self.assertEqual("checked", self.board_progress(self.get(port, "/api/data")))
            self.mark()
            self.now += self.config.collect_memo_sec + 1
            self.assertEqual("withheld", self.board_progress(self.get(port, "/api/data")))
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertIsNone(view["analysis"])
            self.assertIsNone(view["stale"])
            self.mark(on=False)
            self.save_goal()
            self.now += self.config.collect_memo_sec + 1
            self.assertEqual("out_of_date", self.board_progress(self.get(port, "/api/data")))

    def test_board_progress_admission_and_absence_reasons(self) -> None:
        self.save_goal(lines=())
        check = self.passing_check()
        self.record(
            _reading({"goal": {"result": runtime_reading.RESULT_CONSISTENT, "cites": [check]}})
        )
        app = self.app()
        board = app.collect(show_all=True)
        (row,) = board["sessions"]
        raw = row["annotation_assessment"]
        for label, changes, expected in (
            ("Codex", {"harness": "codex"}, None),
            ("withdrawn", {"annotation_assessment": {**raw, "scope": "withdrawn"}}, "out_of_date"),
            ("marked inaccurate", {"annotation_not_accurate": True}, "withheld"),
            ("superseded", {"annotation_revision": 2}, "out_of_date"),
            (
                "schema refused",
                {
                    "annotation_assessment": None,
                    "annotation_reading_refused": True,
                },
                "withheld",
            ),
        ):
            with (
                self.subTest(label=label),
                patch.object(annotation_store, "active") as open_store,
            ):
                self.assertEqual(
                    expected,
                    focused_reading.published(app, board, {**row, **changes})["stored_progress"],
                )
                open_store.assert_not_called()

        for label, report, complete, expected in (
            (
                "vague goal",
                {"result": runtime_reading.RESULT_GOAL_UNCLEAR, "cites": []},
                True,
                "goal_unclear",
            ),
            (
                "incomplete scan",
                {"result": runtime_reading.RESULT_CONSISTENT, "cites": [check]},
                False,
                "not_enough",
            ),
        ):
            with (
                self.subTest(label=label),
                patch.object(levels, "scan_complete", return_value=complete),
            ):
                self.record(_reading({"goal": report}))
                self.now += self.config.collect_memo_sec + 1
                self.assertEqual(
                    expected, self.board_progress(json.loads(app.collect_json(show_all=True)[1]))
                )

    def test_board_withholds_when_the_record_cannot_be_read(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.app()
        for page in (OSError("read failed"), {"state": "unavailable", "entries": []}):
            self.now += self.config.collect_memo_sec + 1
            with (
                self.subTest(page=page),
                patch.object(focused_reading, "record_page") as read,
            ):
                if isinstance(page, Exception):
                    read.side_effect = page
                else:
                    read.return_value = page
                self.assertEqual(
                    "withheld", self.board_progress(json.loads(app.collect_json(show_all=True)[1]))
                )
        board = app.collect(show_all=True)
        (row,) = board["sessions"]
        self.path.unlink()
        self.assertEqual("withheld", focused_reading.published(app, board, row)["stored_progress"])

    def test_board_abstains_if_transcript_changes_after_record_page(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        read = focused_reading.record_page

        def append_after_read(*args: Any, **kwargs: Any) -> dict[str, Any]:
            page = read(*args, **kwargs)
            self.session.prompt("Actually change the goal.")
            self.session.save(self.path)
            return page

        with patch.object(focused_reading, "record_page", side_effect=append_after_read):
            board = json.loads(self.app().collect_json(show_all=True)[1])
        self.assertEqual("withheld", self.board_progress(board))

    def test_the_board_withholds_if_focused_scope_needs_more_than_its_local_read(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.app()
        board = app.collect(show_all=False)
        (row,) = board["sessions"]
        self.assertEqual(
            levels.MEDIUM, focused_reading.published(app, board, row)["stored_progress"]
        )
        for label, fields in (
            ("active project peer", {"active": True}),
            ("ambiguous project label", {"active": False, "project_key": "another-location"}),
        ):
            peer = {**row, "sid": "peer", "harness": "codex", **fields}
            with self.subTest(label=label), patch.object(focused_reading, "record_page") as read:
                scoped = {**board, "sessions": [row, peer]}
                self.assertEqual(
                    "withheld", focused_reading.published(app, scoped, row)["stored_progress"]
                )
                read.assert_not_called()
        with (
            patch.object(focused_reading, "BOARD_TRANSCRIPT_MAX_BYTES", 0),
            patch.object(focused_reading, "record_page") as read,
        ):
            self.assertEqual(
                "withheld", focused_reading.published(app, board, row)["stored_progress"]
            )
            read.assert_not_called()
        older = {**row, "active": False}
        with patch.object(focused_reading, "record_page") as read:
            older_board = {**board, "sessions": [older], "show_all": True}
            self.assertEqual(
                "withheld", focused_reading.published(app, older_board, older)["stored_progress"]
            )
            read.assert_not_called()

    def test_the_board_revalidates_a_stored_departure_before_the_session_opens(self) -> None:
        self.save_goal(lines=())
        self.session.write(str(Path(self.session.cwd) / "unrelated.py"))
        cite = next(f["fact_id"] for f in self.facts_now() if f["subject"] == "write")
        self.record(
            _reading(
                {
                    "goal": {
                        "result": runtime_reading.RESULT_DEPARTURE,
                        "cites": [cite],
                        "why": runtime_reading.WHY_RECORDED_WRITE,
                    }
                },
                window_start=START.timestamp(),
                revision_read_at=START.timestamp(),
            )
        )
        with self.serving() as port:
            self.assertEqual(levels.MEDIUM, self.board_progress(self.get(port, "/api/data")))
            (focused,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertEqual(levels.MEDIUM, focused["pill"]["level"])
            self.assertEqual("analysis", focused["pill"]["source"])

    def test_the_board_names_off_course_when_a_departure_has_a_current_failed_check(self) -> None:
        self.save_goal(lines=())
        self.session.bash("pytest -k lexer", "1 failed", is_error=True)
        cite = next(f["fact_id"] for f in self.facts_now() if f["result"] == "failed")
        self.record(
            _reading(
                {"goal": {"result": runtime_reading.RESULT_DEPARTURE, "cites": [cite]}},
                window_start=START.timestamp(),
                revision_read_at=START.timestamp(),
                evidence_through=START.timestamp() + self.session.seconds,
            )
        )
        with self.serving() as port:
            self.assertEqual(levels.HIGH, self.board_progress(self.get(port, "/api/data")))
        self.session.write(str(Path(self.session.cwd) / "later.py"))
        self.session.save(self.path)
        self.now += self.config.collect_memo_sec + 1
        with self.serving() as port:
            self.assertEqual("out_of_date", self.board_progress(self.get(port, "/api/data")))

    def test_the_board_withholds_a_departure_if_its_citation_is_unreadable(self) -> None:
        self.save_goal(lines=())
        self.record(
            _reading(
                {"goal": {"result": runtime_reading.RESULT_DEPARTURE, "cites": ["unavailable"]}},
                window_start=START.timestamp(),
                revision_read_at=START.timestamp(),
            )
        )
        with self.serving() as port:
            self.assertEqual("withheld", self.board_progress(self.get(port, "/api/data")))

    def test_it_follows_the_record_and_is_never_written(self) -> None:
        self.save_goal()
        self.record(self.consistent_reading())
        path = annotation_store.store_path(self.config)
        with open(path, "rb") as handle:
            before = handle.read()
        with self.serving() as port:
            first = self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"][0]
            self.session.bash("pytest -k lexer", "1 failed", is_error=True)
            self.session.save(self.path)
            later = self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"][0]
        with open(path, "rb") as handle:
            self.assertEqual(before, handle.read())
        self.assertNotEqual(levels.HIGH, first["level"])
        self.assertEqual(levels.HIGH, later["level"])
        self.assertIn(levels.REASON_FAILED_CHECK, later["reasons"])
        self.assertNotIn("level", json.dumps(self.entry()))

    def test_a_reading_where_every_line_cannot_tell_never_reads_none_or_low(self) -> None:
        self.save_goal(lines=(LINE, "The lexer is untouched"))
        self.record(
            _reading(
                {"goal": _unverifiable(), "line_1": _unverifiable(), "line_2": _unverifiable()}
            )
        )
        with self.serving() as port:
            (row,) = self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"]
        self.assertEqual(levels.NOT_ENOUGH, row["level"])

    def test_the_intent_it_read_decides_how_many_lines_it_must_answer(self) -> None:
        # The reading answered one line of a revision that held one; the reader then saved a
        # second line. The level is the reading's, of the words it read.
        self.save_goal()
        self.record(self.consistent_reading())
        self.save_goal(lines=(LINE, "The lexer is untouched"))
        with self.serving() as port:
            (row,) = self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"]
        self.assertNotIn(levels.REASON_READING_MALFORMED, row["reasons"])
        self.assertEqual(1, row["revision_read"])

    def test_an_unsettled_later_direction_reaches_the_level(self) -> None:
        self.save_goal()
        self.record(self.consistent_reading())
        with self.serving() as port:
            quiet = self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"][0]
            self.session.prompt("Also do the lexer")
            self.session.save(self.path)
            later = self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"][0]
        self.assertNotIn(levels.REASON_LATER_DIRECTION, quiet["reasons"])
        self.assertIn(levels.REASON_LATER_DIRECTION, later["reasons"])
        self.assertEqual(levels.NOT_ENOUGH, later["level"])

    def test_no_reading_publishes_no_analysis_level(self) -> None:
        self.save_goal()
        with self.serving() as port:
            focused = self.get(port, FOCUSED)
        self.assertEqual([], focused["sources"]["work"].get("analysis_levels", []))

    def test_the_reading_routes_own_context_carries_no_analysis_level(self) -> None:
        self.save_goal()
        self.record(self.consistent_reading())
        app = self.app()
        _rev, body = app.collect_json(show_all=True)
        row = json.loads(body)["sessions"][0]
        self.assertNotIn("analysis_levels", json.dumps(http_api._session_context(app, row)))
