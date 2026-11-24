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
import http.client
import io
import json
import os
import threading
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from compass_runtime import aggregate, history, http_api, levels, semantic_history, terminal_drift
from compass_runtime import annotations as annotation_store
from compass_runtime import io as runtime_io
from compass_runtime import reading as runtime_reading
from compass_runtime import sessions as runtime_sessions
from compass_runtime.state import build_runtime_state

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
                self.assertNotIn("stored_progress", session)
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

    def cold(self, **row: Any) -> aggregate.Application:
        """A fresh process: its own state, so no memo, no cache and no replay carries over."""
        self.state = build_runtime_state(self.config, started=self.now)
        return self.app(**row)

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
        return {
            "shown": shown,
            "pill": pill["level"] if pill else None,
            "analysis": levels_now[0]["level"] if levels_now else None,
            "stale": (view.get("stale") or {}).get("kind"),
            "unsettled": view.get("unsettled_count"),
            "terminal": terminal_drift.adapt(view).level,
        }

    def long_gap(self) -> None:
        for _ in range(64):
            self.session._entry("assistant", [{"type": "text", "text": "x" * 8192}])

    def direction_and_departure(self) -> None:
        """The reader's direction sits beyond the tail and the newest page: only history holds it."""
        self.save_goal(lines=())
        self.session.prompt(self.DIRECTION)
        self.long_gap()
        self.record(self.departure())

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

    @unittest.expectedFailure  # LEAK: unreadable or lost history reads as "never had a direction"
    def test_lost_history_after_compaction_shows_no_level(self) -> None:
        def unlink(path: Path) -> None:
            path.unlink()

        def emptied(path: Path) -> None:
            path.write_text('{"projects": {}}', encoding="utf-8")

        def corrupt(path: Path) -> None:
            path.write_text("{", encoding="utf-8")

        def oversize(path: Path) -> None:
            path.write_bytes(b" " * (self.config.state_read_cap_bytes + 1))

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

    @unittest.expectedFailure  # LEAK: the 24 h history floor forgets a direction the page needed
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

    @unittest.expectedFailure  # LEAK: out of date, then back to Medium once the later work is gone
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
        self.direction_and_departure()
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

    @unittest.expectedFailure  # LEAK: history is keyed by project, so a new key forgets the direction
    def test_a_rekeyed_project_with_the_direction_only_in_old_history_shows_no_level(self) -> None:
        before = runtime_sessions.project_identity(self.config, self.session.cwd)["key"]
        self.direction_and_departure()
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

    @unittest.expectedFailure  # MISMATCH: the served pill and the terminal's level ignore a withheld latest check
    def test_the_served_view_withholds_what_the_page_withholds_after_a_peers_refusal(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        self.peer_withholds()
        with self.serving(self.cold()) as port:
            seen = self.seen(port)
        self.assertIsNone(seen["shown"])
        self.assertIsNone(seen["pill"], seen)
        self.assertIsNone(seen["terminal"], seen)


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

    @staticmethod
    def hit(port: int, _i: int) -> tuple[int, dict[str, Any]]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            conn.request("GET", FOCUSED)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()
