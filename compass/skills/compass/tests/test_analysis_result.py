"""The analysis result's server half: the level recomputed on render, and Not accurate (DRC-4695).

Items 6, 10 and 14 of
[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
and items 1 and 2 of
[DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn).
The analysis-derived level is `levels.analysis_level` over the stored reading and the current
record. The focused context carries the calculation. The reader's Not accurate mark is a token
stored with the annotation entry and nothing else: removed with the entry, untouched by
`--forget`, never sent and never counted.
"""

from __future__ import annotations

import builtins
import concurrent.futures
import contextlib
import dataclasses
import datetime as dt
import http.client
import io
import json
import os
import stat
import threading
import types
from functools import partial
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from compass_runtime import (
    aggregate,
    footer_lines,
    history,
    http_api,
    levels,
    live_estimate,
    observer,
    project_context,
    reading_evidence,
    reading_jobs,
    reading_route,
    row_progress,
    semantic_history,
    terminal_client,
    terminal_drift,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import io as runtime_io
from compass_runtime import reading as runtime_reading
from compass_runtime import sessions as runtime_sessions
from compass_runtime.state import build_runtime_state

from .support import captured_evidence, make_server, serve_until_closed
from .test_claude_checks import SHORT, START, Transcript
from .test_copied_corrections import _row
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

    def record(self, assessment: dict[str, Any], *, evidence: bool = True, **row: Any) -> None:
        """Store a reading as a press does: with the record of what it read, captured over the
        press's own collect in a process of its own, unless `evidence` is False (a reading an
        older build stored). `row` is the board row the press read, as `app` takes it."""
        record = None
        if evidence:
            mine = self.state
            self.state = build_runtime_state(self.config, started=self.now)
            try:
                record = captured_evidence(self.app(**row), "claude", SHORT, assessment)
            finally:
                self.state = mine
            self.assertIsNotNone(record, "the press captured no record")
        outcome = annotation_store.record_reading(
            self.config,
            self.state,
            "claude",
            SHORT,
            assessment=cast("Any", assessment),
            evidence=record,
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

    def cold(self, **row: Any) -> aggregate.Application:
        """A fresh process: its own state, so no memo, no cache and no replay carries over."""
        self.state = build_runtime_state(self.config, started=self.now)
        return self.app(**row)

    @contextlib.contextmanager
    def serving(self, application: aggregate.Application | None = None) -> Any:
        httpd = make_server(application=application or self.app())
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
        self.assertNotIn("analysis_levels", json.dumps(board))
        self.assertNotIn('"level"', json.dumps(board["sessions"]))

    def test_board_polls_do_not_reopen_evidence_for_a_saved_departure(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.app()
        app.harnesses = tuple(
            spec
            for spec in aggregate.default_harnesses(usage_fetch_enabled=False)
            if spec.key == "claude"
        )
        app.state.annotations = None
        store_name = Path(annotation_store.store_path(self.config)).name
        # On POSIX the safe readers open a leaf relative to an admitted directory descriptor.
        # On Windows the regular opener uses a native file handle.
        descriptor_owner = runtime_io if os.name == "nt" else os
        descriptor_method = "open_regular" if os.name == "nt" else "open"
        # Claude's cold scan opens this transcript four times. With warm caches the collector
        # still reads the head for agent identity and Spacedock settings.
        for poll, expected_transcript_opens in (("cold", 4), ("expired", 2)):
            with (
                self.subTest(poll=poll),
                patch.object(
                    descriptor_owner,
                    descriptor_method,
                    wraps=getattr(descriptor_owner, descriptor_method),
                ) as descriptor_open,
                patch.object(builtins, "open", wraps=builtins.open) as file_open,
                patch.object(io, "open", wraps=io.open) as path_open,
            ):
                board = json.loads(app.collect_json(show_all=True)[1])
                (session,) = board["sessions"]
                self.assertIsNotNone(session["annotation_assessment"])
                self.assertIsNone(session["stored_progress"])
                paths = [
                    Path(call.args[0])
                    for opener in (descriptor_open, file_open, path_open)
                    for call in opener.call_args_list
                    if call.args and isinstance(call.args[0], (str, os.PathLike))
                ]
                self.assertEqual(
                    expected_transcript_opens,
                    sum(path.suffix == ".jsonl" for path in paths),
                    "transcript opens",
                )
                self.assertEqual(
                    1,
                    sum(path.name == store_name for path in paths),
                    "annotation store opens",
                )
            self.now += self.config.collect_memo_sec + 1

    def test_the_focused_page_shows_the_level_of_a_saved_departure(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving() as port:
            self.get(port, "/api/data")
            (focused,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
        self.assertEqual(levels.MEDIUM, focused["pill"]["level"])
        self.assertEqual("analysis", focused["pill"]["source"])

    def test_the_focused_page_withholds_a_departure_with_an_unsettled_direction(self) -> None:
        self.save_goal(lines=())
        self.session.prompt("Actually make the unrelated change first.")
        for _ in range(64):
            self.session._entry("assistant", [{"type": "text", "text": "x" * 8192}])
        self.record(self.departure())
        with self.serving() as port:
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
        self.assertEqual(1, view["unsettled_count"])
        self.assertIsNone(view["pill"])
        self.assertIsNone(view["stale"])

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


class _RowProgress(_Result):
    def poll(self, port: int) -> str | None:
        (row,) = self.get(port, "/api/data")["sessions"]
        return cast("str | None", row.get("stored_progress"))

    def wait_for_progress(self, port: int, token: str) -> None:
        for _ in range(100):
            if self.poll(port) == token:
                return
            threading.Event().wait(0.01)
        self.assertEqual(token, self.poll(port))

    def page(self, port: int) -> dict[str, Any]:
        (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
        return cast("dict[str, Any]", view)


class RowProgressFollowsThePageTest(_RowProgress):
    def test_a_reader_loses_the_final_pill_if_the_end_is_withdrawn(self) -> None:
        self.save_goal(lines=())
        reading = self.departure()
        end = reading["read_at"] - 0.1
        reading.update(
            scope=runtime_reading.SCOPE_FINAL,
            scope_text=runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_FINAL],
            ended_at_read=end,
        )
        self.record(reading, ended_at=end, acquisition="event")
        with self.serving(self.cold(acquisition="event")) as port:
            self.assertIn(self.poll(port), (None, "out-of-date"))
            self.wait_for_progress(port, "out-of-date")
            view = self.page(port)
            self.assertEqual("out-of-date", self.poll(port))
            self.assertIsNone(view["pill"])
            self.assertEqual({"kind": "withdrawn", "before": None}, view["stale"])
            self.assertEqual([], self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"])
            board = self.get(port, "/api/data")
            (row,) = board["sessions"]
            terminal = terminal_drift.render(
                row, board, terminal_drift.adapt(view), adopted=None, again_hint=""
            )
            self.assertIn("This check was withdrawn.", "\n".join(terminal))
            self.assertNotIn("Level:", "\n".join(terminal))

    def test_a_reader_loses_the_pill_when_the_transcript_directory_cannot_be_listed(self) -> None:
        if os.name != "posix":
            self.skipTest("the fixture uses POSIX read permissions")
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            parent = self.path.parent
            previous = stat.S_IMODE(parent.stat().st_mode)
            parent.chmod(0o111)
            try:
                if os.access(parent, os.R_OK):
                    self.skipTest("the test process can still list the directory")
                self.assertIsNone(self.poll(port))
                self.assertIsNone(self.page(port)["pill"])
                self.assertIsNone(self.poll(port))
            finally:
                parent.chmod(previous)

    def test_an_older_transcript_with_the_same_prefix_withdraws_the_pill(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            older = self.path.with_name(f"{SHORT}-older.jsonl")
            older.write_bytes(self.path.read_bytes())
            os.utime(older, (1, 1))
            self.assertIsNone(self.page(port)["pill"])
            self.now += self.config.collect_memo_sec + 1
            self.assertIsNone(self.poll(port))

    def test_a_poll_discounts_an_archived_prefix_collision_before_the_page_opens(self) -> None:
        self.save_goal(lines=())
        reading = self.departure()
        os.utime(self.path, (self.now, self.now))
        app = self.cold()
        app.harnesses = tuple(
            spec
            for spec in aggregate.default_harnesses(usage_fetch_enabled=False)
            if spec.key == "claude"
        )
        (row,) = app.collect(show_all=False)["sessions"]
        project = reading_evidence.project_key(row)
        evidence = captured_evidence(app, "claude", SHORT, reading)
        self.assertIsNotNone(evidence)
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.record_reading(
                self.config,
                app.state,
                "claude",
                SHORT,
                assessment=cast("Any", reading),
                evidence=evidence,
            ),
        )
        app.snapshot.clear()
        with self.serving(app) as port:
            app.warm_row_progress = None
            (view,) = self.get(port, FOCUSED.replace("billing", project))["sources"]["work"][
                "drift_views"
            ]
            self.assertEqual(levels.MEDIUM, view["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            older = self.path.with_name(f"{SHORT}-older.jsonl")
            older.write_bytes(self.path.read_bytes())
            os.utime(older, (1, 1))
            self.now += self.config.collect_memo_sec + 1
            self.assertIsNone(self.poll(port))

    def test_a_same_size_rewrite_with_the_old_mtime_withdraws_the_pill(self) -> None:
        if os.name != "posix":
            self.skipTest("the fixture relies on POSIX change time")
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            before = self.path.stat()
            passage = self.session.rows[0]
            passage["timestamp"] = (
                (START + dt.timedelta(seconds=self.session.seconds + 3))
                .isoformat()
                .replace("+00:00", "Z")
            )
            self.session.save(self.path)
            os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
            after = self.path.stat()
            self.assertEqual((before.st_size, before.st_ino), (after.st_size, after.st_ino))
            self.assertNotEqual(before.st_ctime_ns, after.st_ctime_ns)
            self.assertIsNone(self.poll(port))
            self.assertIsNone(self.page(port)["pill"])

    def test_an_idle_footer_stops_showing_a_departure_whose_proof_expires(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        lines = footer_lines.Lines(self.config.state_home)
        app.footer_lines = lines
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            session = terminal_client.Session("claude", SHORT, "fixture")
            home = self.config.state_home
            expires_at = self.now + row_progress.MAX_AGE_SEC
            self.now += row_progress.MAX_AGE_SEC / 2
            lines.touch(self.now)
            refreshed = terminal_client.read_line(home, session, self.now)
            self.assertIn(
                "Slightly off course", terminal_client.compose_footer(None, refreshed, self.now)
            )
            self.assertEqual(levels.MEDIUM, self.poll(port))
            self.now = expires_at
            lines.touch(self.now)
            last = terminal_client.read_line(home, session, self.now)
            self.assertIsNotNone(last)
            assert last is not None
            self.assertIsNone(last.stored_progress)
            self.assertNotIn(
                "Slightly off course", terminal_client.compose_footer(None, last, self.now)
            )
            self.assertIsNone(self.poll(port))

    def test_a_new_departure_warms_inside_the_retry_interval(self) -> None:
        self.save_goal(lines=())
        self.record(self.on_track_reading())
        app = self.cold()
        with make_server(application=app) as server:
            self.run_warmer(app, server)
            self.assertIsNone(self.progress_from(app))
            self.now += 5
            self.record({**self.departure(), "read_at": self.now})
            app.snapshot.clear()
            self.run_warmer(app, server)
            self.assertEqual(levels.MEDIUM, self.progress_from(app))

    def test_unchanged_on_track_rows_do_not_repeat_work_or_clear_the_board(self) -> None:
        rows = self.seed_projects(held=4, on_track=True)
        app = self.projects_app(rows)
        observed_levels = []
        assemble = http_api.assemble_project_drift

        def observe(*args: Any, **kwargs: Any) -> Any:
            context = assemble(*args, **kwargs)
            (view,) = context["sources"]["work"]["drift_views"]
            observed_levels.append(view["analysis"]["level"])
            return context

        with (
            make_server(application=app) as server,
            patch.object(http_api, "assemble_project_drift", side_effect=observe) as assembled,
            patch.object(app.snapshot, "clear", wraps=app.snapshot.clear) as clear,
            patch.object(live_estimate, "for_session", wraps=live_estimate.for_session) as estimate,
        ):
            for _ in range(5):
                self.run_warmer(app, server)
                self.now += 12
            self.assertEqual([levels.NONE_OR_LOW] * 4, observed_levels)
            self.assertEqual(
                (4, 0, 0), (assembled.call_count, clear.call_count, estimate.call_count)
            )

    def test_polling_unheld_projects_preserves_the_full_history_of_saved_departures(self) -> None:
        rows = self.seed_projects(held=20, legacy=4)
        app = self.projects_app(rows)
        history_path = Path(semantic_history.store_path(self.config))
        before = history_path.read_bytes()
        first = rows[0]
        owner = ("claude", first["sid"])
        with (
            make_server(application=app) as server,
            patch.object(http_api, "ROW_PROGRESS_PASS_SEC", 10),
            patch.object(
                http_api, "assemble_project_drift", wraps=http_api.assemble_project_drift
            ) as assemble,
        ):
            for _ in range(6):
                self.run_warmer(app, server)
                self.now += self.config.collect_memo_sec + 1
            evicted = (
                json.loads(before)["projects"].keys()
                - json.loads(history_path.read_bytes())["projects"].keys()
            )
            self.assertEqual(set(), evicted)
            self.assertEqual(before, history_path.read_bytes())
            warmed = {call.args[3][1] for call in assemble.call_args_list}
            self.assertEqual({row["sid"] for row in rows[:20]}, warmed)
            board = json.loads(app.collect_json(show_all=False)[1])
            (row,) = [row for row in board["sessions"] if row["sid"] == owner[1]]
            self.assertEqual(levels.MEDIUM, row["stored_progress"])
            page = http_api.assemble_project_drift(
                app, board, first["project"], owner, server.record_cursor_key
            )
            (view,) = page["sources"]["work"]["drift_views"]
            self.assertEqual(levels.MEDIUM, view["pill"]["level"])

    def projects_app(self, rows: list[dict[str, Any]]) -> aggregate.Application:
        app = self.cold()
        (spec,) = app.harnesses
        app.harnesses = (
            dataclasses.replace(spec, collect=lambda *_: [row.copy() for row in rows]),
        )
        return app

    def seed_projects(
        self, *, held: int, legacy: int = 0, on_track: bool = False
    ) -> list[dict[str, Any]]:
        rows = []
        for index in range(held + legacy):
            sid = f"{index:08d}"
            project = f"fixture-{index}"
            cwd = self.root / "work" / project
            cwd.mkdir()
            session = Transcript(cwd)
            if index >= held:
                session.seconds = 100
            session.prompt(GOAL)
            if on_track:
                session.bash("pytest", "5 passed")
            else:
                session.write(str(cwd / "unrelated.py"))
            path = self.path.with_name(f"{sid}-full.jsonl")
            session.save(path)
            row = _row(sid=sid, project=project)
            rows.append(row)
            through = START.timestamp() + session.seconds
            self.assertEqual(
                annotation_store.OUTCOME_STORED,
                annotation_store.annotate(
                    self.config, self.state, "claude", sid, goal=GOAL, lines=[], now=through - 6
                ),
            )
            facts, _ = project_context.claude_tool_reports(self.config, str(path), sid)
            (fact,) = facts
            reading = _reading(
                {
                    "goal": {
                        "result": runtime_reading.RESULT_CONSISTENT
                        if on_track
                        else runtime_reading.RESULT_DEPARTURE,
                        "cites": [
                            project_context._semantic_fact_from_event(
                                fact, fact["kind"], "tool_report", ""
                            )["fact_id"]
                        ],
                        "why": runtime_reading.WHY_STANDS
                        if on_track
                        else runtime_reading.WHY_RECORDED_WRITE,
                    }
                },
                read_at=through + 1,
                evidence_through=through,
            )
            evidence = None
            if index < held:
                evidence = captured_evidence(self.projects_app([row]), "claude", sid, reading)
                self.assertIsNotNone(evidence)
            self.assertEqual(
                annotation_store.OUTCOME_STORED,
                annotation_store.record_reading(
                    self.config,
                    self.state,
                    "claude",
                    sid,
                    assessment=cast("Any", reading),
                    evidence=evidence,
                ),
            )
        return rows

    def on_track_reading(self) -> dict[str, Any]:
        through = START.timestamp() + self.session.seconds
        return _reading(
            {
                "goal": {
                    "result": runtime_reading.RESULT_CONSISTENT,
                    "cites": [self.passing_check()],
                    "why": runtime_reading.WHY_STANDS,
                }
            },
            read_at=through + 1,
            evidence_through=through,
        )

    @staticmethod
    def progress_from(app: aggregate.Application) -> Any:
        (row,) = json.loads(app.collect_json(show_all=False)[1])["sessions"]
        return row["stored_progress"]

    def run_warmer(self, app: aggregate.Application, server: http_api.CompassHTTPServer) -> None:
        worker = server.warm_row_progress(app.collect(show_all=False))
        if worker is not None:
            worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_a_reader_sees_a_saved_departure_without_opening_the_session(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.cold()) as port:
            self.assertIsNone(self.poll(port))
            self.wait_for_progress(port, levels.MEDIUM)
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))

    def test_a_reader_loses_the_pill_when_history_disappears_inside_the_poll_floor(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.cold()) as port:
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            Path(semantic_history.store_path(self.config)).unlink()
            self.assertIsNone(self.poll(port))
            self.assertIsNone(self.page(port)["pill"])
            self.assertIsNone(self.poll(port))

    def test_a_reader_overrules_the_pill_on_the_next_poll(self) -> None:
        self.save_goal(lines=())
        reading = self.departure()
        self.record(reading)
        with self.serving(self.cold()) as port:
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            status, answer = self.post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "not_accurate": True,
                    "read_at": reading["read_at"],
                },
            )
            self.assertEqual(200, status, answer)
            self.assertIsNone(self.poll(port))

    def test_a_reader_sees_out_of_date_only_after_the_page_proves_later_work(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.cold()) as port:
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            self.session.write(str(Path(self.session.cwd) / "later.py"))
            self.session.save(self.path)
            self.assertIsNone(self.poll(port))
            self.assertEqual("work", self.page(port)["stale"]["kind"])
            self.assertEqual("out-of-date", self.poll(port))
            self.session.write(str(Path(self.session.cwd) / "later-again.py"))
            self.session.save(self.path)
            self.assertEqual("out-of-date", self.poll(port))


class RowProgressGuardsTest(_RowProgress):
    def test_a_reader_sees_the_page_answer_again_after_the_progress_memo_is_lost(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            app.state.row_progress.clear()
            app.snapshot.clear()
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))

    def test_a_reader_gets_no_old_pill_after_saving_different_words(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            self.save_goal(lines=(LINE,))
            self.assertIsNone(self.poll(port))
            self.assertEqual("intent", self.page(port)["stale"]["kind"])
            self.assertEqual("out-of-date", self.poll(port))

    def test_a_reader_gets_no_pill_from_an_expired_memo(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            self.now += 301
            self.assertIsNone(self.poll(port))

    def test_a_reader_gets_no_pill_when_the_history_mark_cannot_be_read(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            with patch.object(semantic_history, "mark_for", side_effect=PermissionError):
                self.assertIsNone(self.poll(port))

    def test_a_reader_loses_the_warm_pill_when_the_history_becomes_corrupt(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            Path(semantic_history.store_path(self.config)).write_text("{", encoding="utf-8")
            self.assertIsNone(self.poll(port))
            self.assertIsNone(self.page(port)["pill"])

    def test_a_reader_gets_no_pill_when_the_history_file_loses_read_permission(self) -> None:
        if os.name != "posix":
            self.skipTest("the fixture uses POSIX read permissions")
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            path = Path(semantic_history.store_path(self.config))
            path.chmod(0)
            try:
                if os.access(path, os.R_OK):
                    self.skipTest("the test process can still read a mode-zero file")
                self.assertIsNone(self.poll(port))
            finally:
                path.chmod(0o600)

    def test_a_reader_sees_the_vague_goal_word_the_page_proves(self) -> None:
        self.save_goal(lines=())
        self.record(
            _reading(
                {
                    "goal": {"result": runtime_reading.RESULT_GOAL_UNCLEAR, "cites": [], "why": ""},
                }
            )
        )
        with self.serving(self.cold()) as port:
            self.assertIsNone(self.poll(port))
            self.wait_for_progress(port, "goal-unclear")
            view = self.page(port)
            self.assertIsNone(view["pill"])
            self.assertIn("goal-unclear", view["analysis"]["reasons"])
            self.assertEqual("goal-unclear", self.poll(port))

    def test_a_reader_sees_the_high_departure_the_page_proves(self) -> None:
        self.save_goal(lines=())
        reading = self.departure()
        self.session.bash("pytest -k parser", "1 failed", is_error=True)
        self.session.save(self.path)
        reading["evidence_through"] = START.timestamp() + self.session.seconds
        reading["read_at"] = reading["evidence_through"] + 1
        self.record(reading)
        with self.serving(self.cold()) as port:
            self.assertIsNone(self.poll(port))
            self.wait_for_progress(port, levels.HIGH)
            self.assertEqual(levels.HIGH, self.page(port)["pill"]["level"])
            self.assertEqual(levels.HIGH, self.poll(port))

    def test_a_reader_never_gets_the_live_pill_on_a_row(self) -> None:
        view = {"pill": {"source": "live", "level": "high"}, "live_on": True}
        self.assertIsNone(row_progress.token(view))
        self.save_goal(lines=())
        with self.serving(self.cold()) as port:
            self.assertIsNone(self.poll(port))

    def test_a_codex_reader_never_gets_a_saved_progress_candidate(self) -> None:
        self.assertFalse(
            row_progress.eligible(
                {
                    "harness": "codex",
                    "sid": SHORT,
                    "annotation_assessment": self.departure(),
                }
            )
        )

    def test_a_reader_keeps_a_final_pill_after_the_end_reaches_the_board(self) -> None:
        self.save_goal(lines=())
        reading = self.departure()
        end = reading["read_at"] - 0.1
        reading.update(
            scope=runtime_reading.SCOPE_FINAL,
            scope_text=runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_FINAL],
            ended_at_read=end,
        )
        self.record(reading, ended_at=end, acquisition="event")
        app = self.cold(acquisition="event")
        app.overlays = types.SimpleNamespace(
            overlays_for=lambda *_: [],
            finished_at=lambda *_: end,
            ended_at=lambda *_: end,
            git_for=lambda *_: None,
            focusable=lambda *_: False,
            note_rows=lambda *_: None,
            drop_counters=dict,
            command_reports=list,
        )
        with self.serving(app) as port:
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))

    def test_a_reader_gets_the_saved_pill_without_a_model_lease_or_recursion(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        collect = app.collect

        def collect_on_poll(**kwargs: Any) -> Any:
            self.assertNotEqual("compass-row-progress", threading.current_thread().name)
            return collect(**kwargs)

        with (
            patch.object(app, "collect", side_effect=collect_on_poll),
            patch.object(observer, "analyze", side_effect=AssertionError("warmer refreshed")),
            patch.object(
                http_api, "_live_leases", side_effect=AssertionError("warmer took a lease")
            ),
            self.serving(app) as port,
        ):
            self.assertIsNone(self.poll(port))
            self.wait_for_progress(port, levels.MEDIUM)
            self.assertIsNone(app.live_leases)

    def test_a_reader_keeps_the_standing_pill_while_a_peer_check_is_pending(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            key = f"claude:{SHORT}"
            job = runtime_reading.start_job(
                self.config, key, provider="claude", label="Claude", now=self.now
            )
            self.assertIsNotNone(job)
            try:
                app.snapshot.clear()
                self.assertIn(key, self.get(port, "/api/data")["reading_jobs"])
                self.assertEqual(levels.MEDIUM, self.poll(port))
                self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            finally:
                runtime_reading.end_job(self.config, key)

    def test_a_reader_does_not_get_a_pill_from_a_warmer_racing_history_loss(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        entered = threading.Event()
        release = threading.Event()
        derive = http_api.assemble_project_drift

        def hold_warmer(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("with_lease") is False:
                answer = derive(*args, **kwargs)
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("the test did not release the warmer")
                return answer
            return derive(*args, **kwargs)

        with (
            patch.object(http_api, "assemble_project_drift", side_effect=hold_warmer),
            self.serving(app) as port,
            concurrent.futures.ThreadPoolExecutor(12) as pool,
        ):
            try:
                self.assertIsNone(self.poll(port))
                self.assertTrue(entered.wait(5))
                self.now += self.config.collect_memo_sec + 1
                self.assertEqual(levels.MEDIUM, self.poll(port))
                Path(semantic_history.store_path(self.config)).unlink()
                polls = [pool.submit(self.poll, port) for _ in range(12)]
                pages = [pool.submit(self.page, port) for _ in range(6)]
                release.set()
                self.assertEqual([None] * 12, [p.result(10) for p in polls])
                self.assertEqual([None] * 6, [p.result(10)["pill"] for p in pages])
                self.assertIsNone(self.poll(port))
            finally:
                release.set()


class StoredLevelNeedsCurrentEvidenceTest(_Result):
    """A session's page draws no level once the evidence that held it back is gone (DRC-5533).

    The page's own gates are `buildModel` in `frontend/src/drift/model.ts`: no pill while the
    reading is out of date, while the latest check was withheld, or while the store is unreadable.
    `shown_level` applies the same gates to the served answers, so a test reads what a reader
    sees. A departure whose own citation still resolves is not enough: a stale or withdrawn
    reading draws no current level
    ([the goal and progress cards](docs/design-reading-a-session.md#the-goal-and-progress-cards-2026-11-23)).
    """

    DIRECTION = "Actually make the unrelated change first."

    def warm_after(self, seconds: float | None = None) -> None:
        """Let the board's collection memo expire so the next request collects again."""
        self.now += self.config.collect_memo_sec + 1 if seconds is None else seconds

    def seen(self, port: int) -> dict[str, Any]:
        """What the Session page reads, and what it draws from it."""
        board = self.get(port, "/api/data")
        (row,) = [r for r in board["sessions"] if r["sid"] == SHORT]
        work = self.get(port, FOCUSED)["sources"]["work"]
        (view,) = work["drift_views"]
        levels_now = [x for x in work.get("analysis_levels", []) if x["sid"] == SHORT]
        pill = view.get("pill")
        (row_after_page,) = [
            r for r in self.get(port, "/api/data")["sessions"] if r["sid"] == SHORT
        ]
        raw = row.get("annotation_assessment") or {}
        withheld_at = row.get("annotation_reading_withheld_at")
        read_at = raw.get("read_at")
        withheld = bool(row.get("annotation_reading_withheld")) and (
            not raw
            or (
                isinstance(withheld_at, (int, float))
                and isinstance(read_at, (int, float))
                and withheld_at > read_at
            )
        )
        shown = pill["level"] if pill and not view.get("stale") and not withheld else None
        if row.get("annotate_unreadable"):
            shown = None
        if shown is None:
            for answer in (row, row_after_page):
                self.assertNotIn(answer.get("stored_progress"), ("medium", "high", "extreme"))
        return {
            "shown": shown,
            "pill": pill["level"] if pill else None,
            "analysis": levels_now[0]["level"] if levels_now else None,
            "reasons": levels_now[0]["reasons"] if levels_now else None,
            "part": levels_now[0].get("evidence") if levels_now else None,
            "stale": (view.get("stale") or {}).get("kind"),
            "unsettled": view.get("unsettled_count"),
            "terminal": terminal_drift.adapt(view).level,
            "goal": row.get("annotation_goal"),
            "unreadable": row.get("annotate_unreadable"),
        }

    def long_gap(self) -> None:
        for _ in range(64):
            self.session._entry("assistant", [{"type": "text", "text": "x" * 8192}])

    def direction_and_departure(self, **row: Any) -> None:
        """The reader's direction sits beyond the tail and the newest page: only history holds it."""
        self.save_goal(lines=())
        self.session.prompt(self.DIRECTION)
        self.long_gap()
        self.record(self.departure(), **row)

    def drop_direction(self) -> None:
        """A compaction rewrote the file without the direction."""
        self.session.rows = [
            r for r in self.session.rows if self.DIRECTION not in json.dumps(r.get("message"))
        ]
        self.session.save(self.path)

    def history_file(self) -> Path:
        return Path(semantic_history.store_path(self.config))

    def test_a_retained_direction_keeps_the_departure_withheld_after_compaction(self) -> None:
        self.direction_and_departure()
        with self.serving(self.cold()) as port:
            first = self.seen(port)
        self.assertIsNone(first["shown"])
        self.assertIn(self.DIRECTION, self.history_file().read_text(encoding="utf-8"))
        self.drop_direction()
        for poll in ("cold", "warm"):
            with self.subTest(poll=poll):
                if poll == "warm":
                    self.warm_after()
                with self.serving(self.cold() if poll == "cold" else None) as port:
                    self.assertIsNone(self.seen(port)["shown"])

    def served_after_history_is(self, damage: Any) -> list[tuple[str, dict[str, Any]]]:
        self.direction_and_departure()
        with self.serving(self.cold()) as port:
            self.assertIsNone(self.seen(port)["shown"])
        self.drop_direction()
        damage(self.history_file())
        out: list[tuple[str, dict[str, Any]]] = []
        app = self.cold()
        with self.serving(app) as port:
            out.append(("cold", self.seen(port)))
            self.warm_after()
            out.append(("warm", self.seen(port)))
        return out

    def test_lost_history_after_compaction_shows_no_level(self) -> None:
        def unlink(path: Path) -> None:
            path.unlink()

        def emptied(path: Path) -> None:
            path.write_text('{"projects": {}}', encoding="utf-8")

        def corrupt(path: Path) -> None:
            path.write_text("{", encoding="utf-8")

        def oversize(path: Path) -> None:
            # The history itself, intact, and only too big to read.
            path.write_bytes(path.read_bytes() + b" " * self.config.semantic_history_read_cap_bytes)

        for name, damage in (
            ("deleted", unlink),
            ("emptied", emptied),
            ("corrupt", corrupt),
            ("oversize", oversize),
        ):
            with self.subTest(history=name):
                self.setUp()
                for poll, seen in self.served_after_history_is(damage):
                    self.assertIsNone(seen["shown"], f"{name} {poll}: {seen}")

    def test_an_aged_out_direction_shows_no_level(self) -> None:
        self.direction_and_departure()
        with self.serving(self.cold()) as port:
            self.assertIsNone(self.seen(port)["shown"])
        self.now += 25 * 3600
        for poll in ("cold", "warm"):
            with self.subTest(poll=poll):
                if poll == "warm":
                    self.warm_after()
                with self.serving(self.cold() if poll == "cold" else None) as port:
                    self.assertIsNone(self.seen(port)["shown"])

    def test_truncated_later_work_stays_out_of_date_while_history_holds_it(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        original = self.path.read_bytes()
        with self.serving(self.cold()) as port:
            self.assertEqual(levels.MEDIUM, self.seen(port)["shown"])
            self.session.prompt("Actually work on something else now.")
            self.session.save(self.path)
            self.warm_after()
            later = self.seen(port)
            self.assertEqual("work", later["stale"])
            self.assertIsNone(later["shown"])
        self.path.write_bytes(original)
        for poll in ("cold", "warm"):
            with self.subTest(poll=poll):
                if poll == "warm":
                    self.warm_after()
                with self.serving(self.cold() if poll == "cold" else None) as port:
                    self.assertIsNone(self.seen(port)["shown"])

    def test_truncated_later_work_and_lost_history_show_no_level(self) -> None:
        for name in ("deleted", "emptied"):
            with self.subTest(history=name):
                self.setUp()
                self.save_goal(lines=())
                self.record(self.departure())
                original = self.path.read_bytes()
                with self.serving(self.cold()) as port:
                    self.seen(port)
                    self.session.prompt("Actually work on something else now.")
                    self.session.save(self.path)
                    self.warm_after()
                    self.assertIsNone(self.seen(port)["shown"])
                self.path.write_bytes(original)
                if name == "deleted":
                    self.history_file().unlink()
                else:
                    self.history_file().write_text('{"projects": {}}', encoding="utf-8")
                app = self.cold()
                with self.serving(app) as port:
                    self.assertIsNone(self.seen(port)["shown"], "cold")
                    self.warm_after()
                    self.assertIsNone(self.seen(port)["shown"], "warm")

    def test_a_departure_citing_only_a_message_held_by_history_raises_no_level(self) -> None:
        self.save_goal(lines=())
        through = START.timestamp() + self.session.seconds
        self.long_gap()
        self.session.save(self.path)
        with self.serving(self.cold()) as port:
            facts = self.get(port, FOCUSED)["semantic"]["facts"]
        (message,) = [f for f in facts if str(f.get("summary")).startswith("Add retry")]
        self.record(
            _reading(
                {
                    "goal": {
                        "result": runtime_reading.RESULT_DEPARTURE,
                        "cites": [message["fact_id"]],
                        "why": runtime_reading.WHY_RECORDED_WRITE,
                    }
                },
                window_start=START.timestamp(),
                revision_read_at=START.timestamp(),
                read_at=through + 1,
                evidence_through=through,
            )
        )
        with self.serving(self.cold()) as port:
            held = self.seen(port)
        self.assertNotEqual(levels.MEDIUM, held["analysis"], held)
        self.session.rows = self.session.rows[1:3]
        self.session.save(self.path)
        for poll in ("cold", "warm"):
            with self.subTest(poll=poll):
                if poll == "warm":
                    self.warm_after()
                with self.serving(self.cold() if poll == "cold" else None) as port:
                    seen = self.seen(port)
                self.assertIsNone(seen["shown"], seen)
                self.assertNotEqual(levels.MEDIUM, seen["analysis"], seen)

    def rekeyed(self) -> tuple[str, str]:
        before = runtime_sessions.project_identity(self.config, self.session.cwd)["key"]
        (Path(self.session.cwd) / ".git").mkdir()
        after = runtime_sessions.project_identity(self.config, self.session.cwd)["key"]
        self.assertNotEqual(before, after)
        return before, after

    def test_a_rekeyed_project_keeps_the_direction_it_can_still_read(self) -> None:
        before = runtime_sessions.project_identity(self.config, self.session.cwd)["key"]
        self.direction_and_departure(project_key=before)
        with self.serving(self.cold(project_key=before)) as port:
            self.assertIsNone(self.seen(port)["shown"])
        _before, after = self.rekeyed()
        for poll in ("cold", "warm"):
            with self.subTest(poll=poll):
                if poll == "warm":
                    self.warm_after()
                app = self.cold(project_key=after) if poll == "cold" else None
                with self.serving(app) as port:
                    self.assertIsNone(self.seen(port)["shown"])

    def test_a_rekeyed_project_with_the_direction_only_in_old_history_shows_no_level(self) -> None:
        before = runtime_sessions.project_identity(self.config, self.session.cwd)["key"]
        self.direction_and_departure(project_key=before)
        with self.serving(self.cold(project_key=before)) as port:
            self.assertIsNone(self.seen(port)["shown"])
        self.drop_direction()
        _before, after = self.rekeyed()
        self.assertIn(self.DIRECTION, self.history_file().read_text(encoding="utf-8"))
        for poll in ("cold", "warm"):
            with self.subTest(poll=poll):
                if poll == "warm":
                    self.warm_after()
                app = self.cold(project_key=after) if poll == "cold" else None
                with self.serving(app) as port:
                    self.assertIsNone(self.seen(port)["shown"])

    def test_a_peers_pending_check_leaves_the_standing_level(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.cold()) as port:
            self.assertEqual(levels.MEDIUM, self.seen(port)["shown"])
            self.warm_after()
            self.assertEqual(levels.MEDIUM, self.seen(port)["shown"])

    def peer_withholds(self) -> None:
        annotation_store.record_withheld(
            self.config,
            build_runtime_state(self.config, started=self.now),
            "claude",
            SHORT,
            reason=runtime_reading.WITHHELD_JOB_UNRECORDED,
            spent=False,
            job_id="a" * 32,
        )

    def test_a_peers_withheld_check_leaves_the_earlier_level_out(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.cold()) as port:
            self.assertEqual(levels.MEDIUM, self.seen(port)["shown"])
            self.peer_withholds()
            self.warm_after()
            self.assertIsNone(self.seen(port)["shown"], "after the memo")
        with self.serving(self.cold()) as port:
            self.assertIsNone(self.seen(port)["shown"], "cold")

    def test_the_served_view_withholds_what_the_page_withholds_after_a_peers_refusal(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        self.peer_withholds()
        with self.serving(self.cold()) as port:
            seen = self.seen(port)
        self.assertIsNone(seen["shown"])
        self.assertIsNone(seen["pill"], seen)
        self.assertIsNone(seen["terminal"], seen)

    # --- The record of what the check read (DRC-5543) -------------------------------------------

    def each_poll(self, **row: Any) -> list[tuple[str, dict[str, Any]]]:
        """What the page reads in a fresh process, then again once the board's memo has expired."""
        out: list[tuple[str, dict[str, Any]]] = []
        with self.serving(self.cold(**row)) as port:
            out.append(("cold", self.seen(port)))
            self.warm_after()
            out.append(("warm", self.seen(port)))
        return out

    def assert_withheld(
        self, seen: dict[str, Any], part: str, reason: str = levels.REASON_RECORD_CHANGED
    ) -> None:
        self.assertIsNone(seen["shown"], seen)
        self.assertIsNone(seen["terminal"], seen)
        self.assertEqual(levels.NOT_ENOUGH, seen["analysis"], seen)
        self.assertEqual([reason], seen["reasons"], seen)
        self.assertEqual(part, seen["part"], seen)

    def plant(self, change: Any) -> None:
        """Rewrite the stored record on disk, as another process or a hand edit could."""
        path = annotation_store.store_path(self.config)
        with open(path, encoding="utf-8") as handle:
            stored = json.load(handle)
        (entry,) = [e for e in stored["entries"] if e.get("sid") == SHORT]
        change(entry)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(stored, handle)

    def bucket(self, key: str = "billing") -> dict[str, Any]:
        stored = json.loads(self.history_file().read_text(encoding="utf-8"))
        found = stored["projects"].get(key)
        return found if isinstance(found, dict) else {}

    def test_a_reading_saved_before_this_build_shows_no_level_until_checked_again(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure(), evidence=False)
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll):
                self.assert_withheld(seen, reading_evidence.PART_MISSING)
                self.assertEqual(GOAL, seen["goal"])
        self.now += 60
        self.record(self.departure())
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll, after="a new check"):
                self.assertEqual(levels.MEDIUM, seen["shown"], seen)

    def test_a_record_this_build_cannot_read_withholds_only_the_level(self) -> None:
        def history(key: str, value: Any) -> Any:
            return lambda record: record["history"].__setitem__(key, value)

        damage: dict[str, Any] = {
            "not a record": lambda e: e.__setitem__("reading_evidence", "yes"),
            "an uppercase digest": lambda e: e["reading_evidence"].__setitem__(
                "project", e["reading_evidence"]["project"].upper()
            ),
            "a short lineage": lambda e: history("lineage", "ab")(e["reading_evidence"]),
            "an extra key": lambda e: e["reading_evidence"].__setitem__("why", "it read it"),
            "another version": lambda e: e["reading_evidence"].__setitem__("v", 2),
            "not a number": lambda e: e["reading_evidence"].__setitem__("read_at", float("nan")),
            "a bool for a count": lambda e: history("generation", True)(e["reading_evidence"]),
            "a bool for a size": lambda e: e["reading_evidence"].__setitem__(
                "transcript_bytes", False
            ),
            "a word for a time": lambda e: e["reading_evidence"].__setitem__("direction_at", "now"),
        }
        for name, change in damage.items():
            with self.subTest(record=name):
                self.setUp()
                self.save_goal(lines=())
                self.record(self.departure())
                self.plant(change)
                for poll, seen in self.each_poll():
                    self.assert_withheld(seen, reading_evidence.PART_UNREADABLE)
                    self.assertEqual(GOAL, seen["goal"], poll)
                    self.assertFalse(seen["unreadable"], poll)

    def test_a_record_of_another_reading_withholds_the_level(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        self.plant(
            lambda e: e["reading_evidence"].__setitem__(
                "read_at", e["reading_evidence"]["read_at"] + 1
            )
        )
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll):
                self.assert_withheld(seen, reading_evidence.PART_OTHER_READING)

    def test_a_rekeyed_project_withholds_the_level_with_no_direction_at_all(self) -> None:
        before = runtime_sessions.project_identity(self.config, self.session.cwd)["key"]
        self.save_goal(lines=())
        self.record(self.departure(), project_key=before)
        with self.serving(self.cold(project_key=before)) as port:
            self.assertEqual(levels.MEDIUM, self.seen(port)["shown"])
        _before, after = self.rekeyed()
        for poll, seen in self.each_poll(project_key=after):
            with self.subTest(poll=poll):
                self.assert_withheld(seen, reading_evidence.PART_PROJECT)

    def test_a_day_old_reading_with_no_open_direction_keeps_its_level(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.cold()) as port:
            self.assertEqual(levels.MEDIUM, self.seen(port)["shown"])
        lineage = self.bucket()["lineage"]
        self.now += 25 * 3600
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll):
                self.assertEqual(levels.MEDIUM, seen["shown"], seen)
                self.assertIsNone(seen["part"], seen)
        # The prune emptied the bucket and kept its lineage.
        self.assertEqual([], self.bucket()["events"])
        self.assertEqual(lineage, self.bucket()["lineage"])

    def test_a_keep_given_after_the_direction_aged_out_lets_the_level_stand(self) -> None:
        self.direction_and_departure()
        self.now += 25 * 3600
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll, keep="none"):
                self.assert_withheld(
                    seen, reading_evidence.PART_DIRECTION, levels.REASON_LATER_DIRECTION
                )
        direction_at = self.raw_entry()["reading_evidence"]["direction_at"]
        self.assertIsNotNone(direction_at)
        outcome = annotation_store.settle(
            self.config, self.state, "claude", SHORT, through=direction_at, now=self.now
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll, keep="through the direction"):
                self.assertEqual(levels.MEDIUM, seen["shown"], seen)

    def consistent_reading(self) -> dict[str, Any]:
        check = self.passing_check()
        consistent = {
            "result": runtime_reading.RESULT_CONSISTENT,
            "cites": [check],
            "why": runtime_reading.WHY_STANDS,
        }
        return _reading({"goal": dict(consistent), "line_1": dict(consistent)}, window_start=None)

    def test_a_transcript_cut_below_what_the_check_read_never_reads_on_track(self) -> None:
        # The saved check answered an outcome line, which the card can show with a
        # usable route. Supply its CLI lookup without depending on the test machine.
        self.enterContext(
            patch.object(
                reading_route,
                "resolve_all",
                side_effect=partial(
                    reading_route.resolve_all,
                    binary_resolver=lambda name: str(self.root / name),
                    environ={},
                    root=self.root,
                ),
            )
        )
        self.save_goal()
        self.session._entry("assistant", [{"type": "text", "text": "All done."}])
        self.session.save(self.path)
        self.record(self.consistent_reading())
        with self.serving(self.cold()) as port:
            before = self.seen(port)
            self.assertEqual(levels.NONE_OR_LOW, before["shown"], before)
        self.session.rows = self.session.rows[:-1]
        self.session.save(self.path)
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll):
                self.assert_withheld(seen, reading_evidence.PART_TRANSCRIPT)

    def test_a_history_bucket_other_projects_pushed_out_withholds_the_level(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        for k in range(semantic_history.MAX_PROJECTS):
            fact = {"fact_id": f"f{k}", "type": "user_message", "summary": "s", "at": self.now}
            semantic_history.update(
                self.config, self.state, f"other-{k}", {"facts": [fact]}, [], now=self.now
            )
        self.assertEqual({}, self.bucket())
        for poll, seen in self.each_poll():
            with self.subTest(poll=poll):
                self.assert_withheld(seen, reading_evidence.PART_HISTORY)

    def test_an_older_copy_of_history_put_back_withholds_the_level(self) -> None:
        self.save_goal(lines=())
        with self.serving(self.cold()) as port:
            self.get(port, FOCUSED)
        copy = self.history_file().read_bytes()
        with self.serving(self.cold()) as port:
            self.get(port, FOCUSED)
            self.get(port, FOCUSED)
        self.record(self.departure())
        self.history_file().write_bytes(copy)
        # Only the first poll after the restore is held: every focused poll raises the restored
        # copy's generation, and once it reaches the recorded one the level shows again. That
        # catch-up is an accepted gap, named in the design record's amendment of 2026-11-24.
        with self.serving(self.cold()) as port:
            self.assert_withheld(self.seen(port), reading_evidence.PART_HISTORY)

    def test_a_busy_project_still_shows_its_level(self) -> None:
        # A day of directions and writes files far more history than the old 64 KiB state cap held.
        for k in range(150):
            self.session.prompt(f"Please also tidy module number {k} " + "and its helpers " * 12)
            self.session.write(self.session.cwd + f"/src/m{k}.py")
        self.save_goal(lines=())
        self.record(self.departure())
        self.assertGreater(self.history_file().stat().st_size, 65_536)
        with self.serving(self.cold()) as port:
            first = self.seen(port)
            self.warm_after()
            second = self.seen(port)
        again = self.departure()
        again["read_at"] += 100
        self.record(again)
        with self.serving(self.cold()) as port:
            third = self.seen(port)
        for name, seen in (("cold", first), ("warm", second), ("checked again", third)):
            with self.subTest(poll=name):
                self.assertEqual(levels.MEDIUM, seen["shown"], seen)
                self.assertIsNone(seen["part"], seen)
        self.assertLessEqual(
            self.history_file().stat().st_size, self.config.semantic_history_read_cap_bytes
        )

    def test_a_label_two_projects_share_still_reads_this_projects_history(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure(), project_key="key-one")

        def shared() -> aggregate.Application:
            self.state = build_runtime_state(self.config, started=self.now)
            rows = [_row(project_key="key-one"), _row(sid="b" * 36, project_key="key-two")]
            spec = aggregate.HarnessSpec(
                key="claude", label="Claude", discover=lambda *_: True, collect=lambda *_a: rows
            )
            return aggregate.Application(
                self.config,
                self.state,
                (spec,),
                native_notifier=lambda _p: "",
                popup_notifier=lambda _t, _b: None,
                diagnostic_sink=lambda _m: None,
                clock=lambda: self.now,
            )

        with self.serving(shared()) as port:
            mark = self.get(port, FOCUSED)["semantic"]["history"]["mark"]
            self.assertEqual("billing", mark["key"])
            cold = self.seen(port)
            self.warm_after()
            warm = self.seen(port)
        for poll, seen in (("cold", cold), ("warm", warm)):
            with self.subTest(poll=poll):
                self.assertEqual(levels.MEDIUM, seen["shown"], seen)
                self.assertIsNone(seen["part"], seen)


class ConcurrentColdSessionPageTest(_Result):
    """Cold requests to the Session page's focused route, all at once."""

    REQUESTS = 24
    WORKERS = 12

    def test_concurrent_cold_requests_answer_completely(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        self.state = build_runtime_state(self.config, started=self.now)
        barrier = threading.Barrier(self.WORKERS)

        def one(i: int) -> tuple[int, dict[str, Any]]:
            if i < self.WORKERS:
                barrier.wait(timeout=10)
            return self.hit(port, i)

        with (
            self.serving() as port,
            concurrent.futures.ThreadPoolExecutor(self.WORKERS) as pool,
        ):
            answers = list(pool.map(one, range(self.REQUESTS)))
        self.assertEqual([200] * self.REQUESTS, [status for status, _ in answers])
        for _status, body in answers:
            work = body["sources"]["work"]
            (row,) = [x for x in work["analysis_levels"] if x["sid"] == SHORT]
            self.assertEqual(levels.MEDIUM, row["level"])
            (view,) = work["drift_views"]
            self.assertNotEqual("unavailable", view.get("state"))
            self.assertEqual(levels.MEDIUM, view["pill"]["level"])
            self.assertTrue(work["live_levels"])

    def test_history_lost_mid_burst_never_brings_a_withheld_level_back(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        self.state = build_runtime_state(self.config, started=self.now)
        recorded = self.raw_entry()["reading_evidence"]["history"]["lineage"]
        history_file = Path(semantic_history.store_path(self.config))
        barrier = threading.Barrier(self.WORKERS + 1)
        clock = threading.Lock()
        ticks = iter(range(10**6))

        def tick() -> int:
            with clock:
                return next(ticks)

        def one(i: int) -> tuple[int, int, int, dict[str, Any]]:
            barrier.wait(timeout=10)
            started = tick()
            status, body = self.hit(port, i)
            return started, tick(), status, body

        def delete() -> None:
            barrier.wait(timeout=10)
            history_file.unlink(missing_ok=True)

        with (
            self.serving() as port,
            concurrent.futures.ThreadPoolExecutor(self.WORKERS + 1) as pool,
        ):
            deleter = pool.submit(delete)
            burst = list(pool.map(one, range(self.WORKERS)))
            deleter.result(timeout=10)
            after = [self.hit(port, i) for i in range(self.WORKERS)]
        answers = [(a, b, status, body) for a, b, status, body in burst]
        self.assertEqual([200] * self.WORKERS, [status for _a, _b, status, _ in answers])

        def kind(body: dict[str, Any]) -> str:
            (row,) = [x for x in body["sources"]["work"]["analysis_levels"] if x["sid"] == SHORT]
            (view,) = body["sources"]["work"]["drift_views"]
            if row["level"] == levels.MEDIUM and "evidence" not in row:
                self.assertEqual(levels.MEDIUM, view["pill"]["level"])
                return "level"
            self.assertEqual(
                (levels.NOT_ENOUGH, reading_evidence.PART_HISTORY),
                (row["level"], row.get("evidence")),
            )
            self.assertIsNone(view["pill"])
            return "history"

        lost = [end for _start, end, _status, body in answers if kind(body) == "history"]
        for start, _end, _status, body in answers:
            if lost and start > min(lost):
                self.assertEqual("history", kind(body), "a level came back after it was lost")
        # Whatever the burst left on disk decides every later answer, all alike.
        expected = "level" if self.bucket_lineage(history_file) == recorded else "history"
        self.assertEqual([expected] * self.WORKERS, [kind(body) for _status, body in after])

    @staticmethod
    def bucket_lineage(path: Path) -> str | None:
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        bucket = stored.get("projects", {}).get("billing")
        return bucket.get("lineage") if isinstance(bucket, dict) else None

    @staticmethod
    def hit(port: int, _i: int) -> tuple[int, dict[str, Any]]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request("GET", FOCUSED)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()


class APressKeepsTheRecordOfWhatItReadTest(_Result):
    """The ordinary press stores the record beside its reading, in the one write (DRC-5543)."""

    def press(self, assessment: dict[str, Any], **patches: Any) -> None:
        app = self.app()
        _rev, body = app.collect_json(show_all=True)
        (row,) = [r for r in json.loads(body)["sessions"] if r["sid"] == SHORT]
        entry = self.entry()
        handler = types.SimpleNamespace(
            server=types.SimpleNamespace(application=app),
            _reading_arguments=lambda *_a, **_k: {},
        )
        job = reading_jobs.start_job(
            self.config, f"claude:{SHORT}", provider="claude", label="Claude Code", now=self.now
        )
        assert job is not None
        self.addCleanup(runtime_reading.end_job, self.config, f"claude:{SHORT}")

        def compose(hooks: reading_jobs.Hooks) -> Any:
            with contextlib.ExitStack() as stack:
                stack.enter_context(
                    patch.object(runtime_reading, "produce", return_value=(assessment, "", True))
                )
                for name, value in patches.items():
                    stack.enter_context(patch.object(http_api, name, value))
                compose_reading: Any = http_api._RequestHandler._compose_reading
                return compose_reading(handler, row, entry, types.SimpleNamespace(), hooks)

        thread = reading_jobs.launch(app, job, compose)
        thread.join(timeout=30)
        self.assertFalse(thread.is_alive())

    def test_a_press_stores_what_it_read_beside_the_reading(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        self.press(assessment)
        stored = self.raw_entry()
        record = reading_evidence.validate(stored.get("reading_evidence"))
        assert record is not None, stored.get("reading_evidence")
        bucket = json.loads(Path(semantic_history.store_path(self.config)).read_text())
        held = bucket["projects"]["billing"]
        self.assertEqual(
            (
                stored["assessment"]["read_at"],
                reading_evidence.project_digest("billing"),
                {"lineage": held["lineage"], "generation": held["generation"]},
                self.path.stat().st_size,
                None,
            ),
            (
                record["read_at"],
                record["project"],
                record["history"],
                record["transcript_bytes"],
                record["direction_at"],
            ),
        )
        self.assertNotIn("reading_evidence", json.dumps(annotation_store.published(self.entry())))
        with self.serving(self.cold()) as port:
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            board = self.get(port, "/api/data")
        self.assertEqual(levels.MEDIUM, view["pill"]["level"])
        self.assertNotIn("reading_evidence", json.dumps(board))
        self.assertNotIn(record["history"]["lineage"], json.dumps(board))

    def test_a_press_records_the_open_direction_it_read_by_its_time_alone(self) -> None:
        self.save_goal(lines=())
        self.session.prompt("Actually make the unrelated change first.")
        self.session.save(self.path)
        (direction,) = [
            f
            for f in http_api._facts_of(http_api._session_context(self.app(), _row()))
            if f.get("type") == "user_message" and "unrelated change" in str(f.get("summary"))
        ]
        self.press(self.departure())
        record = self.raw_entry()["reading_evidence"]
        self.assertEqual(direction["at"], record["direction_at"])
        self.assertNotIn("unrelated", json.dumps(record))

    def test_a_press_that_read_no_history_stores_no_record_and_draws_no_level(self) -> None:
        self.save_goal(lines=())
        self.press(self.departure(), _session_context=lambda *_a, **_k: {})
        stored = self.raw_entry()
        self.assertIn("assessment", stored)
        self.assertNotIn("reading_evidence", stored)
        with self.serving() as port:
            (row,) = self.get(port, FOCUSED)["sources"]["work"]["analysis_levels"]
        self.assertEqual(
            (levels.NOT_ENOUGH, reading_evidence.PART_MISSING), (row["level"], row["evidence"])
        )


class TheRecordStaysWithItsReadingTest(_Result):
    """Written with the reading, carried with it and removed with it, never alone."""

    def setUp(self) -> None:
        super().setUp()
        self.save_goal(lines=())
        self.record(self.departure())
        self.first = self.raw_entry()["reading_evidence"]

    def test_a_withheld_check_keeps_the_standing_reading_and_its_record(self) -> None:
        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            SHORT,
            reason=runtime_reading.WITHHELD_MODEL_FAILED,
            spent=True,
        )
        self.assertEqual(self.first, self.raw_entry()["reading_evidence"])

    def test_a_late_reading_that_is_not_kept_leaves_the_standing_record(self) -> None:
        late: dict[str, Any] = dict(self.entry()["assessment"])
        late["read_at"] = float(late["read_at"]) - 10
        record: Any = {**self.first, "read_at": late["read_at"]}
        outcome = annotation_store.record_reading(
            self.config, self.state, "claude", SHORT, assessment=cast("Any", late), evidence=record
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.assertEqual(self.first["read_at"], self.raw_entry()["assessment"]["read_at"])
        self.assertEqual(self.first, self.raw_entry()["reading_evidence"])

    def test_a_new_reading_never_inherits_the_record_of_the_one_it_replaces(self) -> None:
        self.now += 60
        self.record(self.departure(), evidence=False)
        self.assertNotIn("reading_evidence", self.raw_entry())

    def test_a_record_of_another_reading_is_never_stored_with_this_one(self) -> None:
        self.now += 60
        newer = self.departure()
        record: Any = {**self.first, "read_at": float(newer["read_at"]) + 1}
        annotation_store.record_reading(
            self.config, self.state, "claude", SHORT, assessment=cast("Any", newer), evidence=record
        )
        self.assertEqual(newer["read_at"], self.raw_entry()["assessment"]["read_at"])
        self.assertNotIn("reading_evidence", self.raw_entry())

    def test_a_goal_save_and_a_not_accurate_mark_carry_it(self) -> None:
        self.save_goal(lines=(LINE,))
        self.assertEqual(self.first, self.raw_entry()["reading_evidence"])
        self.mark(read_at=self.first["read_at"])
        self.assertEqual(self.first, self.raw_entry()["reading_evidence"])

    def test_clearing_the_session_removes_it_with_the_reading(self) -> None:
        annotation_store.forget(self.config)
        self.assertEqual(self.first, self.raw_entry()["reading_evidence"])
        annotation_store.clear(self.config, self.state, "claude", SHORT)
        self.assertNotIn("reading_evidence", self.raw_entry())
        self.assertNotIn("assessment", self.raw_entry())

    def test_it_holds_no_words_and_never_enters_history_or_a_row(self) -> None:
        self.assertEqual(
            {"v", "read_at", "project", "history", "transcript_bytes", "direction_at"},
            set(self.first),
        )
        self.assertNotIn("billing", json.dumps(self.first))
        self.assertFalse(
            [name for name in history.OBSERVATION_FIELDS if "evidence" in name or "lineage" in name]
        )
        _rev, body = self.app().collect_json(show_all=True)
        self.assertNotIn(self.first["project"], body.decode())


class TheRowGateReadsMetadataTest(_RowProgress):
    def test_a_readers_cached_row_checks_the_evidence_without_reopening_the_record(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.cold()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.assertEqual(levels.MEDIUM, self.page(port)["pill"]["level"])
            self.assertEqual(levels.MEDIUM, self.poll(port))
            boom = AssertionError("the poll tried to reopen the record")
            with (
                patch.object(reading_evidence, "held", wraps=reading_evidence.held) as held,
                patch.object(semantic_history, "mark_for", wraps=semantic_history.mark_for) as mark,
                patch.object(project_context, "transcript_stamp", side_effect=boom),
                patch.object(observer, "resolve_transcript", side_effect=boom),
                patch.object(builtins, "open", wraps=builtins.open) as opened,
            ):
                self.assertEqual(levels.MEDIUM, self.poll(port))
            self.assertEqual((1, 1), (held.call_count, mark.call_count))
            self.assertFalse(
                any(str(call.args[0]).endswith(".jsonl") for call in opened.call_args_list)
            )

    def test_a_gate_that_fails_withholds_the_level_and_keeps_the_page(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with (
            patch.object(reading_evidence, "held", side_effect=RuntimeError("boom")),
            self.serving(self.cold()) as port,
        ):
            status, focused = self.get_status(port, FOCUSED)
        self.assertEqual(200, status)
        (row,) = focused["sources"]["work"]["analysis_levels"]
        (view,) = focused["sources"]["work"]["drift_views"]
        self.assertEqual(
            (levels.NOT_ENOUGH, reading_evidence.PART_UNREADABLE, None),
            (row["level"], row["evidence"], view["pill"]),
        )

    @staticmethod
    def get_status(port: int, path: str) -> tuple[int, dict[str, Any]]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()
