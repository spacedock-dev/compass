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
import contextlib
import dataclasses
import http.client
import io
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch
from urllib.parse import urlencode

from compass_runtime import (
    aggregate,
    ci_read,
    copied_corrections,
    drift_view,
    ends,
    history,
    http_api,
    levels,
    observation,
    observer,
    project_context,
    reader_checks,
    record_pages,
    semantic_history,
    session_progress,
    snapshot,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import io as runtime_io
from compass_runtime import reading as runtime_reading
from compass_runtime.state import build_runtime_state

from .support import make_server, serve_until_closed
from .test_claude_checks import SHORT, START, Transcript
from .test_copied_corrections import OWN, _paste, _row
from .test_live_estimate import GOAL, LINE, _Replay
from .test_reading_jobs import independent_worker
from .test_subagent_checks import Subagent

FOCUSED = f"/api/project-context?project=billing&session=claude:{SHORT}"


def _progress_path(revision: str, *rows: tuple[str, str, str]) -> str:
    pairs = [("revision", revision), *(("row", json.dumps(row)) for row in rows)]
    return "/api/session-progress?" + urlencode(pairs)


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

    def fresh_app(self, **row: Any) -> aggregate.Application:
        old = self.state
        self.state = build_runtime_state(self.config, started=self.now)
        try:
            return self.app(**row)
        finally:
            self.state = old

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
        self.assertNotIn("analysis_levels", json.dumps(board))
        self.assertNotIn('"level"', json.dumps(board["sessions"]))

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

    def progress(self, port: int) -> dict[str, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("GET", "/api/data")
            snapshot = conn.getresponse()
            revision = snapshot.getheader("X-Compass-Revision")
            row = next(
                row for row in json.loads(snapshot.read())["sessions"] if row["sid"] == SHORT
            )
            self.assertIsNone(row["stored_progress"])
        finally:
            conn.close()
        assert revision is not None
        answer = self.get(port, _progress_path(revision, ("claude", SHORT, "billing")))
        self.assertEqual({"revision", "rows"}, set(answer))
        self.assertEqual(revision, answer["revision"])
        (progress,) = answer["rows"]
        self.assertEqual({"harness", "sid", "project", "stored_progress"}, set(progress))
        self.assertEqual(
            ("claude", SHORT, "billing"),
            tuple(progress[k] for k in ("harness", "sid", "project")),
        )
        return answer

    def test_retained_direction_loss_cannot_promote_a_stored_departure(self) -> None:
        self.save_goal(lines=())
        self.session.prompt("Actually make the unrelated change first.")
        direction = self.session.rows[-1]
        # A real Claude compaction boundary can sit between the removed user
        # message and the next user or assistant record.
        self.session._entry("system", [])
        self.record(self.departure())
        app = self.app()
        project_context.collect(
            self.config,
            self.state,
            app.collect(show_all=False)["sessions"],
            "billing",
            now=self.now,
            focus=("claude", SHORT),
        )
        path = Path(semantic_history.store_path(self.config))
        retained = path.read_bytes()
        self.assertIn(b"unrelated change first", retained)
        self.session.rows.remove(direction)
        self.session.save(self.path)
        cap = self.config.state_read_cap_bytes

        def assert_withheld() -> None:
            with self.serving(self.fresh_app()) as port:
                answer = self.progress(port)
                (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertIsNone(answer["rows"][0]["stored_progress"])
            self.assertIsNone(view["pill"])

        for content in (retained.ljust(cap), retained.ljust(cap + 1), b'{"projects":{}}', b"{"):
            with self.subTest(size=len(content)):
                path.write_bytes(content)
                assert_withheld()
        if os.name != "nt" and os.geteuid() != 0:
            path.write_bytes(retained)
            path.chmod(0)
            try:
                with self.assertRaises(PermissionError):
                    path.read_bytes()
                assert_withheld()
            finally:
                path.chmod(0o600)
        path.unlink(missing_ok=True)
        assert_withheld()

    def test_missing_branch_cannot_promote_after_history_is_lost(self) -> None:
        self.save_goal(lines=())
        parent = self.session.rows[-1]["uuid"]
        self.session.prompt("Actually make the unrelated change first.")
        direction = self.session.rows[-1]
        self.session._entry("assistant", [], parentUuid=parent)
        self.record(self.departure())
        with self.serving(self.fresh_app()) as port:
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

        self.session.rows.remove(direction)
        self.session.save(self.path)
        path = Path(semantic_history.store_path(self.config))
        for content in (None, b'{"projects":{}}'):
            for focus_first in (False, True):
                with self.subTest(content=content, focus_first=focus_first):
                    if content is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.write_bytes(content)
                    with self.serving(self.fresh_app()) as port:
                        if focus_first:
                            self.assertIsNone(
                                self.get(port, FOCUSED)["sources"]["work"]["drift_views"][0]["pill"]
                            )
                        self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
                        self.assertIsNone(
                            self.get(port, FOCUSED)["sources"]["work"]["drift_views"][0]["pill"]
                        )
                        self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_focus_preserves_the_unreadable_history_veto(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        path = Path(semantic_history.store_path(self.config))
        for contents in (
            b"{",
            b'{"projects":{"billing":{"events":null}}}',
            b"x" * (self.config.state_read_cap_bytes + 1),
        ):
            with self.subTest(size=len(contents)):
                path.write_bytes(contents)
                with self.serving(self.fresh_app()) as port:
                    self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
                    (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
                    self.assertIsNone(view["pill"])
                    self.assertEqual(contents, path.read_bytes())
                    self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_removed_later_work_stays_stale_when_history_remembers_it(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        original = self.path.read_bytes()
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            self.session.prompt("Actually work on something else now.")
            self.session.save(self.path)
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertEqual("work", view["stale"]["kind"])
        self.path.write_bytes(original)
        with self.serving(self.fresh_app()) as port:
            mark = self.progress(port)["rows"][0]["stored_progress"]
            self.assertIn(mark, (None, "out-of-date"))

    def test_warm_progress_withholds_when_the_state_home_cannot_be_opened(self) -> None:
        if os.name == "nt" or os.geteuid() == 0:
            self.skipTest("requires POSIX directory access checks")
        self.save_goal(lines=())
        self.record(self.departure())
        home = Path(self.config.state_home)
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            mode = home.stat().st_mode & 0o777
            home.chmod(0o111)
            try:
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
                with self.serving(self.fresh_app()) as cold:
                    self.assertIsNone(self.progress(cold)["rows"][0]["stored_progress"])
            finally:
                home.chmod(mode)

    def test_evicted_copy_cannot_authorize_warm_progress(self) -> None:
        self.save_goal(lines=())
        self.register(OWN, now=START.timestamp() + self.session.seconds + 1)
        _paste(self.session, OWN)
        self.record(self.departure())
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            Path(copied_corrections.store_path(self.config)).unlink()
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_owned_transcript_and_reader_check_links_preserve_progress(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        target = self.root / "native-source"
        self.path.rename(target)
        self.path.symlink_to(target)
        checks = self.root / "reader-checks"
        checks.write_text('{"projects": {}}', encoding="utf-8")
        Path(reader_checks.store_path(self.config)).symlink_to(checks)
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])

    def test_refused_declaration_does_not_withhold_unrelated_evidence(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        workspace = Path(self.session.cwd)
        workspace.mkdir(exist_ok=True)
        (workspace / ".git").mkdir()
        makefile = workspace / "Makefile"
        for is_link in (True, False):
            with self.subTest(is_link=is_link):
                if is_link:
                    makefile.symlink_to(self.path)
                else:
                    makefile.mkdir()
                with self.serving(self.fresh_app()) as port:
                    self.assertEqual(
                        levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"]
                    )
                if is_link:
                    makefile.unlink()
                else:
                    makefile.rmdir()

    def test_no_cwd_does_not_probe_the_server_checkout(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        for record in self.session.rows:
            record.pop("cwd", None)
        self.session.save(self.path)
        self.record(assessment)
        with (
            self.serving(self.fresh_app()) as port,
            patch.object(
                session_progress, "_git_markers", wraps=session_progress._git_markers
            ) as markers,
        ):
            self.progress(port)
        markers.assert_not_called()

    def test_peer_worker_withholds_the_old_departure_while_pending_and_after_refusal(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        self.record(assessment)
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            with independent_worker(self.config, SHORT, None, launch=False):
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            with independent_worker(self.config, SHORT, assessment):
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
                with independent_worker(self.config, SHORT, None):
                    pass
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_new_goal_does_not_inherit_an_empty_ledger_attempt(self) -> None:
        self.save_goal(lines=())
        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            SHORT,
            reason=runtime_reading.WITHHELD_LEDGER_EMPTY,
            spent=False,
        )
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("too-early", self.progress(port)["rows"][0]["stored_progress"])
            self.session.prompt("Ship a different change.")
            self.session.save(self.path)
            self.save_goal(lines=("A new outcome line",))
            self.assertEqual("unchecked", self.progress(port)["rows"][0]["stored_progress"])

    def test_first_save_and_replacement_use_one_focus_generation(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("unchecked", self.progress(port)["rows"][0]["stored_progress"])
            self.record(assessment)
            for revision in (1, 2):
                with self.subTest(revision=revision):
                    mark = self.progress(port)["rows"][0]["stored_progress"]
                    work = self.get(port, FOCUSED)["sources"]["work"]
                    (view,) = work["drift_views"]
                    self.assertEqual(levels.MEDIUM, mark)
                    self.assertEqual(mark, view["stored_progress"])
                    self.assertTrue(view["reading"])
                    self.assertEqual(revision, view["revision"])
                    self.assertEqual(["goal"], view["departures"])
                    self.assertEqual(revision, work["analysis_levels"][0]["revision_read"])
                if revision == 1:
                    at = START.timestamp() + self.session.seconds + 1
                    self.assertEqual(
                        annotation_store.OUTCOME_STORED,
                        annotation_store.annotate(
                            self.config,
                            self.state,
                            "claude",
                            SHORT,
                            goal="Ship the newer parser",
                            lines=[],
                            expected_revision=1,
                            now=at,
                        ),
                    )
                    newer = self.departure()
                    self.record({**newer, "revision_read": 2, "revision_read_at": at})

    def test_focus_drops_the_overruled_low_analysis_on_a_warm_snapshot(self) -> None:
        self.save_goal()
        assessment = self.consistent_reading()
        self.record(assessment)
        with self.serving(self.fresh_app()) as port:
            self.progress(port)
            work = self.get(port, FOCUSED)["sources"]["work"]
            self.assertEqual(levels.NONE_OR_LOW, work["analysis_levels"][0]["level"])
            self.assertEqual(
                annotation_store.OUTCOME_STORED, self.mark(read_at=assessment["read_at"])
            )
            with patch.object(session_progress._Batch, "_derive", autospec=True) as derive:
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
                derive.assert_not_called()
            work = self.get(port, FOCUSED)["sources"]["work"]
            (view,) = work["drift_views"]
            self.assertIsNone(view["stored_progress"])
            self.assertIsNone(view["analysis"])
            self.assertEqual([], work["analysis_levels"])

    def test_focus_keeps_the_technical_analysis_of_a_stale_departure(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            self.session.prompt("Actually work on something else now.")
            self.session.save(self.path)
            work = self.get(port, FOCUSED)["sources"]["work"]
            (view,) = work["drift_views"]
            self.assertEqual("out-of-date", view["stored_progress"])
            self.assertEqual("work", view["stale"]["kind"])
            self.assertEqual(levels.MEDIUM, work["analysis_levels"][0]["level"])

    def test_early_citation_is_available_to_the_focused_page(self) -> None:
        self.save_goal(lines=())
        self.session._entry(
            "assistant", [{"type": "text", "text": "I will change the unrelated module instead."}]
        )
        self.session.save(self.path)
        with self.serving(self.fresh_app()) as port:
            (citation,) = [
                fact["fact_id"]
                for fact in self.get(port, FOCUSED)["semantic"]["facts"]
                if fact.get("type") == "agent_message"
            ]
        assessment = _reading(
            {"goal": {"result": runtime_reading.RESULT_DEPARTURE, "cites": [citation]}},
            revision_read_at=START.timestamp(),
            window_start=START.timestamp(),
        )
        Path(semantic_history.store_path(self.config)).unlink(missing_ok=True)
        for _ in range(141):
            self.session._entry("assistant", [{"type": "text", "text": "x" * 8192}])
        self.session.save(self.path)
        through = START.timestamp() + self.session.seconds
        self.record({**assessment, "read_at": through + 1, "evidence_through": through})
        with self.serving(self.fresh_app()) as port:
            mark = self.progress(port)["rows"][0]["stored_progress"]
            context = self.get(port, FOCUSED)
            (view,) = context["sources"]["work"]["drift_views"]
            self.assertEqual(levels.MEDIUM, mark)
            self.assertEqual(mark, view["stored_progress"])
            self.assertEqual(["goal"], view["departures"])
            self.assertTrue(
                set(assessment["criteria"]["goal"]["cites"])
                <= {fact["fact_id"] for fact in context["semantic"]["facts"]}
            )

    def test_progress_and_focus_agree_on_first_and_warm_loads(self) -> None:
        self.save_goal(lines=())
        for _ in range(141):
            self.session._entry("assistant", [{"type": "text", "text": "x" * 8192}])
        self.record(self.departure())
        self.assertGreater(self.path.stat().st_size, 1024**2)
        for focus_first in (False, True):
            with self.subTest(focus_first=focus_first), self.serving(self.fresh_app()) as port:
                if focus_first:
                    self.get(port, FOCUSED)
                for _ in range(2):
                    mark = self.progress(port)["rows"][0]["stored_progress"]
                    (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
                    self.assertEqual(levels.MEDIUM, mark)
                    self.assertEqual(mark, view["pill"]["level"])

    def test_a_second_dashboard_overrule_withdraws_a_warm_result(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        self.record(assessment)
        with self.serving(self.fresh_app()) as port, self.serving(self.fresh_app()) as other:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            status, answer = self.post(
                other,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "not_accurate": True,
                    "read_at": assessment["read_at"],
                },
            )
            self.assertEqual((200, annotation_store.OUTCOME_STORED), (status, answer["outcome"]))
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertIsNone(view["pill"])

    def test_overrule_during_derivation_withdraws_the_answer_before_reply(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        self.record(assessment)
        derive = session_progress._verdict
        with self.serving(self.fresh_app()) as port, self.serving(self.fresh_app()) as other:

            def after_derivation(*args: Any) -> Any:
                verdict = derive(*args)
                self.assertEqual(levels.MEDIUM, verdict.value)
                status, answer = self.post(
                    other,
                    "/api/annotate",
                    {
                        "harness": "claude",
                        "sid": SHORT,
                        "not_accurate": True,
                        "read_at": assessment["read_at"],
                    },
                )
                self.assertEqual(
                    (200, annotation_store.OUTCOME_STORED), (status, answer["outcome"])
                )
                return verdict

            with patch.object(session_progress, "_verdict", side_effect=after_derivation):
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_a_delegated_recheck_during_the_read_cannot_publish_the_failed_level(self) -> None:
        self.save_goal(lines=())
        child = Subagent(self.session, "a1b2c3d4")
        dispatched = self.session.call("Agent", {"prompt": "Run the tests."})
        child.prompt("Run the tests.")
        child.bash("pytest", "1 failed", is_error=True)
        self.session.result(dispatched, "Started.", tool_use_result={"agentId": child.agent_id})
        path = self.path.with_suffix("") / "subagents" / f"agent-{child.agent_id}.jsonl"
        child.save(path)
        cite = next(fact["fact_id"] for fact in self.facts_now() if fact.get("result") == "failed")
        through = START.timestamp() + self.session.seconds
        self.record(
            _reading(
                {"goal": {"result": runtime_reading.RESULT_DEPARTURE, "cites": [cite]}},
                window_start=START.timestamp(),
                revision_read_at=START.timestamp(),
                read_at=through + 1,
                evidence_through=through,
            )
        )
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.HIGH, self.progress(port)["rows"][0]["stored_progress"])
        before = self.path.stat().st_mtime_ns
        derive = session_progress._verdict

        def after_derivation(*args: Any) -> Any:
            verdict = derive(*args)
            self.assertEqual(levels.HIGH, verdict.value)
            child.bash("pytest", "7 passed")
            child.save(path)
            return verdict

        with self.serving(self.fresh_app()) as port:
            with patch.object(session_progress, "_verdict", side_effect=after_derivation):
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            self.assertEqual(before, self.path.stat().st_mtime_ns)
            self.assertNotIn(
                self.progress(port)["rows"][0]["stored_progress"], session_progress.DEPARTURES
            )
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertIsNone(view["pill"])

    def test_missing_record_page_withholds_both_surfaces(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with (
            self.serving(self.fresh_app()) as port,
            patch.object(
                record_pages,
                "read",
                return_value=record_pages.empty("claude", SHORT, "unavailable"),
            ),
        ):
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertIsNone(view["pill"])

    def test_recent_ended_session_with_a_project_peer_uses_the_focused_verdict(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        ended = assessment["read_at"]
        assessment.update(
            scope=runtime_reading.SCOPE_FINAL,
            scope_text=runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_FINAL],
            ended_at_read=ended,
        )
        self.record(assessment)
        app = self.fresh_app()
        parent = _row(state="idle", active=False, ended_at=ended)
        peer = _row(sid="deadbeef", session="deadbeef")
        app.harnesses = (
            dataclasses.replace(app.harnesses[0], collect=lambda *_: [dict(parent), dict(peer)]),
        )
        with self.serving(app) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertEqual(levels.MEDIUM, view["pill"]["level"])
            self.assertEqual(["goal"], view["departures"])
            terminal = self.get(port, "/api/sessions")
        row = next(row for row in terminal["sessions"] if row["sid"] == SHORT)
        self.assertEqual(levels.MEDIUM, row["stored_progress"])

    def test_goal_and_recorded_attempts_have_distinct_absences(self) -> None:
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("no-goal", self.progress(port)["rows"][0]["stored_progress"])
            self.save_goal(lines=())
            self.assertEqual("unchecked", self.progress(port)["rows"][0]["stored_progress"])
            reading, why, spent = self.produce_attempt(None)
            self.assertIsNone(reading)
            self.assertEqual(runtime_reading.WITHHELD_LEDGER_EMPTY, why)
            self.assertFalse(spent)
            annotation_store.record_withheld(
                self.config,
                self.state,
                "claude",
                SHORT,
                reason=why,
                spent=spent,
            )
            self.assertEqual("too-early", self.progress(port)["rows"][0]["stored_progress"])

    def test_progress_warm_hits_do_not_read_evidence_content_or_collect(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.fresh_app()
        with self.serving(app) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            revision, _ = app.collect_json(show_all=False)
            path = _progress_path(f"{revision[0]:.0f}.{revision[1]}", ("claude", SHORT, "billing"))
            with (
                patch.object(app, "collect_json", side_effect=AssertionError("board collection")),
                patch.object(
                    project_context, "stored_evidence", side_effect=AssertionError("native content")
                ),
                patch.object(
                    semantic_history, "read_only", side_effect=AssertionError("retained content")
                ),
                patch.object(
                    annotation_store,
                    "progress_entries",
                    side_effect=AssertionError("annotation content"),
                ),
            ):
                self.assertEqual(levels.MEDIUM, self.get(port, path)["rows"][0]["stored_progress"])

    def test_cold_progress_only_reads_and_refuses_a_busy_annotation_store(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.fresh_app()
        revision, _ = app.collect_json(show_all=False)
        token = snapshot.format_revision(revision)
        endpoint = _progress_path(token, ("claude", SHORT, "billing"))
        home = Path(self.config.state_home)
        before = {file.name: file.read_bytes() for file in home.iterdir() if file.is_file()}
        transcript = self.path.read_bytes()
        with (
            self.serving(app) as port,
            patch.object(app, "collect_json", side_effect=AssertionError("board collection")),
            patch.object(ci_read, "read", side_effect=AssertionError("CI fetch")),
            patch.object(observer.CodexGoalModel, "__call__", side_effect=AssertionError("model")),
        ):
            with annotation_store.progress_read(self.config) as locked:
                self.assertTrue(locked)
                self.assertIsNone(self.get(port, endpoint)["rows"][0]["stored_progress"])
            self.assertEqual(levels.MEDIUM, self.get(port, endpoint)["rows"][0]["stored_progress"])
        self.assertEqual(
            before, {file.name: file.read_bytes() for file in home.iterdir() if file.is_file()}
        )
        self.assertEqual(transcript, self.path.read_bytes())

    def test_new_attempt_replacement_revision_and_clear_invalidate_the_warm_verdict(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        self.record(assessment)
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            annotation_store.record_withheld(
                self.config,
                self.state,
                "claude",
                SHORT,
                reason=runtime_reading.WITHHELD_CONTEXT_LIMIT,
                spent=False,
            )
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            self.record({**assessment, "read_at": assessment["read_at"] + 1})
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            self.save_goal(lines=("The lexer is untouched",))
            self.assertEqual("out-of-date", self.progress(port)["rows"][0]["stored_progress"])
            annotation_store.clear(self.config, self.state, "claude", SHORT)
            self.assertNotIn(
                self.progress(port)["rows"][0]["stored_progress"], session_progress.DEPARTURES
            )

    def test_native_gemini_sid_does_not_reject_a_claude_peer(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        os.utime(self.path, (self.now, self.now))
        gemini = self.root / "gemini"
        sid = "session-2026-04-01T12:00:00.000Z-abc"
        transcript = gemini / "billing" / "chats" / f"{sid}.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text('{"type":"user","content":"Shipping review"}\n', encoding="utf-8")
        os.utime(transcript, (self.now, self.now))
        self.config = dataclasses.replace(
            self.config, store_roots={**self.config.store_roots, "gemini.tmp": (str(gemini),)}
        )
        app = self.fresh_app()
        app.harnesses = tuple(
            spec
            for spec in aggregate.default_harnesses(usage_fetch_enabled=False)
            if spec.key in {"claude", "gemini"}
        )
        revision, body = app.collect_json(show_all=False)
        identities = sorted(session_progress.identity(row) for row in json.loads(body)["sessions"])
        self.assertEqual([("claude", SHORT), ("gemini", sid)], [key[:2] for key in identities])
        with self.serving(app) as port:
            result = self.get(port, _progress_path(snapshot.format_revision(revision), *identities))
        self.assertEqual([levels.MEDIUM, None], [row["stored_progress"] for row in result["rows"]])

    def test_focus_shapes_carry_a_nullable_progress_field(self) -> None:
        with self.serving(self.fresh_app(harness="codex")) as port:
            available = self.get(
                port, f"/api/project-context?project=billing&session=codex:{SHORT}"
            )["sources"]["work"]["drift_views"][0]
            unavailable = self.get(port, FOCUSED)["sources"]["work"]["drift_views"][0]
        self.assertIsNone(available["stored_progress"])
        self.assertFalse(available["reading"])
        self.assertEqual(
            {
                "harness": "claude",
                "sid": SHORT,
                "state": "unavailable",
                "reason": "identity-not-unique",
                "stored_progress": None,
            },
            unavailable,
        )

    def test_a_proven_check_and_an_unverifiable_read_have_distinct_wire_tokens(self) -> None:
        self.save_goal()
        check = self.passing_check()
        consistent = {
            "result": runtime_reading.RESULT_CONSISTENT,
            "cites": [check],
            "why": runtime_reading.WHY_STANDS,
        }
        self.record(_reading({"goal": consistent, "line_1": consistent}, window_start=None))
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("checked", self.progress(port)["rows"][0]["stored_progress"])
        self.save_goal(lines=())
        assessment, why, spent = self.produce_attempt("consistent")
        self.assertEqual(("", True), (why, spent))
        assert assessment is not None
        self.record(dict(assessment))
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("cant-tell", self.progress(port)["rows"][0]["stored_progress"])
            view = self.get(port, FOCUSED)["sources"]["work"]["drift_views"][0]
            self.assertEqual("cant-tell", view["stored_progress"])

    def test_requested_identity_has_to_be_visible_and_use_the_canonical_project(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.fresh_app()
        visible = _row()
        hidden = _row(sid="deafbeef", session="deafbeef")
        app.harnesses = (
            dataclasses.replace(
                app.harnesses[0],
                collect=lambda _config, _state, _now, _hours, show_all: (
                    [dict(visible), dict(hidden)] if show_all else [dict(visible)]
                ),
            ),
        )
        token = snapshot.format_revision
        revision, _ = app.collect_json(show_all=False)
        expanded_revision, _ = app.collect_json(show_all=True)
        with self.serving(app) as port:
            wrong = ("claude", SHORT, "a different project")
            not_visible = ("claude", "deafbeef", "billing")
            codex = ("codex", SHORT, "billing")
            rows = self.get(port, _progress_path(token(revision), wrong, not_visible, codex))[
                "rows"
            ]
            self.assertEqual([None, None, None], [row["stored_progress"] for row in rows])
            self.assertEqual(
                [], self.get(port, _progress_path(token(expanded_revision), not_visible))["rows"]
            )

    def test_explicit_goal_unclear_is_published_on_both_surfaces(self) -> None:
        self.save_goal(lines=())
        assessment, why, spent = self.produce_attempt("goal_unclear")
        self.assertEqual(("", True), (why, spent))
        assert assessment is not None
        self.assertEqual(
            runtime_reading.RESULT_GOAL_UNCLEAR, assessment["criteria"]["goal"]["result"]
        )
        self.record(dict(assessment))
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("goal-unclear", self.progress(port)["rows"][0]["stored_progress"])
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertEqual("goal-unclear", view["stored_progress"])
            self.assertIsNone(view["pill"])

    def test_a_produced_unfinished_outcome_is_too_early_on_both_surfaces(self) -> None:
        self.save_goal(lines=())
        assessment, why, spent = self.produce_attempt("not_reached")
        self.assertEqual(("", True), (why, spent))
        assert assessment is not None
        self.assertEqual(
            runtime_reading.RESULT_NOT_REACHED, assessment["criteria"]["goal"]["result"]
        )
        self.record(dict(assessment))
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("too-early", self.progress(port)["rows"][0]["stored_progress"])
            (view,) = self.get(port, FOCUSED)["sources"]["work"]["drift_views"]
            self.assertEqual("too-early", view["stored_progress"])
            self.assertIsNone(view["pill"])

    def produce_attempt(
        self, result: str | None
    ) -> tuple[runtime_reading.Assessment | None, str, bool]:
        if result is not None:
            self.session._entry(
                "assistant", [{"type": "text", "text": "I am still wiring the parser."}]
            )
            self.session.save(self.path)
        app = self.app()
        (row,) = app.collect(show_all=False)["sessions"]
        facts = (
            http_api._facts_of(http_api._session_context(app, row)) if result is not None else []
        )

        def model(_prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            self.assertIsNotNone(result, "an empty ledger must stop before the model")
            self.assertGreater(output_cap_bytes, 0)
            return json.dumps(
                {
                    "goal": {"result": result, "cites": [1], "detail": "Still working."},
                }
            ), "ok"

        return runtime_reading.produce(
            self.config,
            row,
            self.entry()["revisions"],
            facts,
            now=self.now,
            stamp_text="offline fixture",
            model=model,
            read_agent_words=True,
        )

    def test_a_child_appearing_after_derivation_invalidates_publication(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        child = Subagent(self.session, "a1b2c3d4")
        path = self.path.with_suffix("") / "subagents" / f"agent-{child.agent_id}.jsonl"
        before = self.path.stat().st_mtime_ns
        finish = session_progress._Batch.finish

        def before_reply(batch: Any, results: Any) -> Any:
            self.assertEqual(levels.MEDIUM, next(iter(results.values())).value)
            child.bash("pytest", "1 failed", is_error=True)
            child.save(path)
            return finish(batch, results)

        with (
            self.serving(self.fresh_app()) as port,
            patch.object(session_progress._Batch, "finish", before_reply),
        ):
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
        self.assertEqual(before, self.path.stat().st_mtime_ns)

    def _peer_with_reading(self, sid: str, *, saved: bool = True) -> None:
        cwd = Path(self.session.cwd)
        transcript = Transcript(cwd)
        transcript.prompt(GOAL)
        transcript.write(str(cwd / f"unrelated-{sid}.py"))
        path = self.path.with_name(f"{sid}-full.jsonl")
        for row in transcript.rows:
            row["sessionId"] = f"{sid}-full"
        transcript.save(path)
        os.utime(path, (self.now, self.now))
        if not saved:
            return
        events, _ = project_context.claude_tool_reports(self.config, str(path), sid)
        (cite,) = [
            project_context._semantic_fact_from_event(event, event["kind"], "tool_report", "")[
                "fact_id"
            ]
            for event in events
            if event.get("subject") == "write"
        ]
        through = START.timestamp() + transcript.seconds
        annotation_store.annotate(
            self.config, self.state, "claude", sid, goal=GOAL, now=START.timestamp() + 6
        )
        outcome = annotation_store.record_reading(
            self.config,
            self.state,
            "claude",
            sid,
            assessment=cast(
                "Any",
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
                    read_at=through + 1,
                    evidence_through=through,
                ),
            ),
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)

    def test_oversized_transcript_cannot_starve_a_healthy_neighbour(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        self._peer_with_reading("abc01234")
        maximum = self.config.turn_scan_max_bytes
        with self.path.open("ab") as transcript:
            transcript.truncate(maximum + 1)
        os.utime(self.path, (self.now, self.now))
        app = self.fresh_app()
        app.harnesses = tuple(
            spec
            for spec in aggregate.default_harnesses(usage_fetch_enabled=False)
            if spec.key == "claude"
        )
        rev, body = app.collect_json(show_all=False)
        found = {row["sid"]: session_progress.identity(row) for row in json.loads(body)["sessions"]}
        with (
            self.serving(app) as port,
            patch.object(session_progress, "MAX_BATCH_BYTES", maximum + 1024),
        ):
            answer = self.get(
                port,
                _progress_path(
                    snapshot.format_revision(rev),
                    found[SHORT],
                    found["abc01234"],
                ),
            )
        self.assertEqual([None, levels.MEDIUM], [row["stored_progress"] for row in answer["rows"]])

    def test_cold_annotation_decode_does_not_hold_the_board_lock(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.fresh_app()
        revision, body = app.collect_json(show_all=False)
        endpoint = _progress_path(
            snapshot.format_revision(revision),
            session_progress.identity(json.loads(body)["sessions"][0]),
        )
        entered, release = threading.Event(), threading.Event()
        original = annotation_store.progress_entries
        answer = []

        def read(config: Any) -> Any:
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("annotation decode was not released")
            return original(config)

        with self.serving(app) as port, patch.object(annotation_store, "progress_entries", read):
            worker = threading.Thread(target=lambda: answer.append(self.get(port, endpoint)))
            worker.start()
            try:
                self.assertTrue(entered.wait(timeout=3))
                with annotation_store.progress_read(self.config) as held:
                    self.assertTrue(held, "progress held the writer lock while decoding")
            finally:
                release.set()
                worker.join(timeout=5)
        self.assertEqual(levels.MEDIUM, answer[0]["rows"][0]["stored_progress"])

    def test_unchanged_broken_native_evidence_is_reused_on_refresh(self) -> None:
        self.save_goal(lines=())
        self.session.prompt("Actually do something else.")
        direction = self.session.rows[-1]
        self.record(self.departure())
        self.session.rows.remove(direction)
        self.session.save(self.path)
        with self.serving(self.fresh_app()) as port:
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            with (
                patch.object(
                    project_context, "stored_evidence", wraps=project_context.stored_evidence
                ) as evidence,
                patch.object(
                    semantic_history, "read_only", wraps=semantic_history.read_only
                ) as retained,
            ):
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
            evidence.assert_not_called()
            retained.assert_not_called()

    def test_an_off_board_annotation_edit_does_not_reopen_visible_evidence(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            annotation_store.annotate(
                self.config, self.state, "claude", "offboard", goal=GOAL, now=self.now
            )
            with patch.object(
                project_context, "stored_evidence", wraps=project_context.stored_evidence
            ) as evidence:
                self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            evidence.assert_not_called()

    def test_raw_snapshots_never_project_progress_for_a_24_session_board(self) -> None:
        self.path.unlink()
        for index in range(24):
            self._peer_with_reading(f"{index + 1:08x}", saved=index < 12)
        original = self.config
        counts = []
        for annotate in (False, True):
            self.config = dataclasses.replace(original, annotations_enabled=annotate)
            app = self.fresh_app()
            app.harnesses = tuple(
                spec
                for spec in aggregate.default_harnesses(usage_fetch_enabled=False)
                if spec.key == "claude"
            )
            with (
                patch.object(
                    session_progress, "evaluate", side_effect=AssertionError("progress evaluation")
                ),
                patch.object(
                    semantic_history, "read_only", side_effect=AssertionError("history content")
                ),
                patch.object(runtime_io, "open_harness", wraps=runtime_io.open_harness) as opened,
            ):
                expected_readings = 12 if annotate else 0
                opens = []
                for action in ("cold", "memo", "expired"):
                    if action == "expired":
                        self.now += self.config.collect_memo_sec + 1
                    opened.reset_mock()
                    board = json.loads(app.collect_json(show_all=False)[1])
                    self.assertEqual(24, len(board["sessions"]))
                    self.assertEqual(
                        expected_readings,
                        sum(bool(row["annotation_assessment"]) for row in board["sessions"]),
                    )
                    self.assertTrue(
                        all(row["stored_progress"] is None for row in board["sessions"])
                    )
                    opens.append(
                        sum(str(call.args[0]).endswith(".jsonl") for call in opened.call_args_list)
                    )
                counts.append(opens)
        self.assertTrue(all(annotated <= plain for plain, annotated in zip(*counts, strict=True)))
        cold, memo, expired = counts[1]
        self.assertGreaterEqual(cold, 24)
        self.assertEqual(0, memo)
        self.assertGreaterEqual(expired, 24)

    def test_concurrent_cold_progress_coalesces_and_both_get_the_departure(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.fresh_app()
        rev, body = app.collect_json(show_all=False)
        endpoint = _progress_path(
            snapshot.format_revision(rev),
            session_progress.identity(json.loads(body)["sessions"][0]),
        )
        started, release = threading.Event(), threading.Event()
        answers = []
        original = project_context.stored_evidence

        def read(*args: Any, **kwargs: Any) -> Any:
            started.set()
            if not release.wait(timeout=5):
                raise AssertionError("the cold reader was not released")
            return original(*args, **kwargs)

        with self.serving(app) as port, patch.object(project_context, "stored_evidence", read):

            def get() -> None:
                answers.append(self.get(port, endpoint)["rows"][0]["stored_progress"])

            first, second = threading.Thread(target=get), threading.Thread(target=get)
            first.start()
            try:
                self.assertTrue(started.wait(timeout=3))
                second.start()
                second.join(timeout=1.4)
                self.assertTrue(second.is_alive(), "an admitted caller lost the in-flight proof")
            finally:
                release.set()
                first.join(timeout=5)
                second.join(timeout=5)
        self.assertEqual([levels.MEDIUM, levels.MEDIUM], answers)

    def test_recorded_milestone_replays_on_both_routes_cold_and_warm(self) -> None:
        root = Path(__file__).resolve().parents[4]
        sample = root / "sample-session" / "milestone-session.jsonl"
        fixture = root / "frontend" / "src" / "sample" / "session.fixture.json"
        (recorded,) = json.loads(fixture.read_bytes())["board"]["sessions"]
        assessment = recorded["annotation_assessment"]
        first = json.loads(sample.read_bytes().splitlines()[0])
        sid = first["sessionId"][:8]
        source = self.path.with_name(f"{first['sessionId']}.jsonl")
        self.path.unlink()
        shutil.copyfile(sample, source)
        os.utime(source, (assessment["evidence_through"],) * 2)
        self.now = assessment["read_at"] + 60
        binding = self.config, self.state, "claude", sid
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.annotate(
                *binding,
                goal=recorded["annotation_goal"],
                lines=[],
                now=recorded["annotation_at"],
                window_start=assessment["window_start"],
            ),
        )
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.record_reading(
                *binding,
                assessment=assessment,
            ),
        )
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.settle(
                *binding,
                through=recorded["annotation_settled_through"],
                now=recorded["annotation_settled_at"],
            ),
        )
        self.assertTrue(
            ends.record(self.config, harness="claude", sid=sid, at=assessment["ended_at_read"])
        )
        self.assertEqual(sample.read_bytes(), source.read_bytes())
        for first_route in ("batch", "focus"):
            with self.subTest(first_route=first_route):
                app = self.fresh_app()
                app.harnesses = tuple(
                    spec
                    for spec in aggregate.default_harnesses(usage_fetch_enabled=False)
                    if spec.key == "claude"
                )
                app.overlays = observation.Observation(
                    app, clock=app.clock, load_parent_claims=False
                )
                rev, body = app.collect_json(show_all=False)
                (row,) = json.loads(body)["sessions"]
                key = session_progress.identity(row)
                self.assertEqual(sid, key[1])
                batch_path = _progress_path(snapshot.format_revision(rev), key)
                focus_path = "/api/project-context?" + urlencode(
                    {"project": key[2], "session": f"claude:{sid}"}
                )
                checks = {
                    "batch": (batch_path, ("rows", 0)),
                    "focus": (focus_path, ("sources", "work", "drift_views", 0)),
                }
                other_route = "focus" if first_route == "batch" else "batch"
                with self.serving(app) as port:
                    for _ in range(2):
                        for route in (first_route, other_route):
                            path, fields = checks[route]
                            answer: Any = self.get(port, path)
                            for field in fields:
                                answer = answer[field]
                            self.assertEqual(levels.MEDIUM, answer["stored_progress"])
                            if route == "focus":
                                self.assertEqual(["goal"], answer["departures"])
                                self.assertEqual(levels.MEDIUM, answer["pill"]["level"])

    def test_disconnected_native_record_never_covers_a_valid_citation(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        self.session.rows[1]["parentUuid"] = "missing-native-parent"
        self.session.save(self.path)
        self.record(assessment)
        with self.serving(self.fresh_app()) as port:
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_retained_direction_before_the_read_vetoes_an_intact_native_graph(self) -> None:
        self.save_goal(lines=())
        parent = self.session.rows[-1]["uuid"]
        self.session.prompt("Actually make the unrelated change first.")
        direction = self.session.rows[-1]
        self.session._entry("assistant", [], parentUuid=parent)
        assessment = self.departure()
        app = self.fresh_app()
        with self.serving(app) as port:
            self.get(port, FOCUSED)
        self.assertIn(
            b"unrelated change first", Path(semantic_history.store_path(self.config)).read_bytes()
        )
        self.session.rows.remove(direction)
        self.session.save(self.path)
        self.record(assessment)
        with self.serving(self.fresh_app()) as port:
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
        Path(semantic_history.store_path(self.config)).unlink()
        with self.serving(self.fresh_app()) as port:
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_native_read_must_cover_the_opening_and_the_evidence_cutoff(self) -> None:
        self.save_goal(lines=())
        assessment = self.departure()
        self.record(assessment)
        with self.serving(self.fresh_app(first_prompt_at=START.timestamp() - 1)) as port:
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
        self.record({**assessment, "evidence_through": assessment["read_at"] + 10})
        with self.serving(self.fresh_app()) as port:
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_live_only_and_existing_but_missing_intent_do_not_publish_absence(self) -> None:
        app = self.fresh_app()
        with (
            self.serving(app) as port,
            patch.object(session_progress._Batch, "_live_only", return_value=True),
        ):
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])
        self.save_goal(lines=())
        with self.serving(self.fresh_app()) as port:
            self.assertEqual("unchecked", self.progress(port)["rows"][0]["stored_progress"])
            Path(annotation_store.store_path(self.config)).unlink()
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_duplicate_admission_and_a_second_native_prefix_are_refused(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        row = _row()
        self.assertEqual(
            {session_progress.identity(row): row}, session_progress.admitted_rows([row])
        )
        self.assertEqual({}, session_progress.admitted_rows([row, {**row, "project": "peer"}]))
        with self.serving(self.fresh_app()) as port:
            self.assertEqual(levels.MEDIUM, self.progress(port)["rows"][0]["stored_progress"])
            shutil.copyfile(self.path, self.path.with_name(f"{SHORT}-shadow.jsonl"))
            self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_reducer_refusal_reasons_cannot_produce_a_token(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        original = drift_view.derive

        def altered(state: str) -> Any:
            def derive(*args: Any) -> Any:
                view = original(*args)
                self.assertEqual(["goal"], view["departures"])
                if state == "malformed":
                    return {**view, "malformed": "invalid"}
                if state == "withheld":
                    return {**view, "analysis": {**view["analysis"], "withheld": True}}
                return {
                    **view,
                    "analysis": {
                        "level": levels.NONE_OR_LOW,
                        "withheld": False,
                        "reasons": [levels.REASON_FAILED_CHECK],
                    },
                }

            return derive

        for state in ("malformed", "withheld", "failed-check"):
            with (
                self.subTest(state=state),
                self.serving(self.fresh_app()) as port,
                patch.object(drift_view, "derive", altered(state)),
            ):
                self.assertIsNone(self.progress(port)["rows"][0]["stored_progress"])

    def test_snapshot_turnover_during_evaluation_withholds_batch_and_lean(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        for route in ("batch", "lean"):
            app = self.fresh_app()
            rev, body = app.collect_json(show_all=False)
            (row,) = json.loads(body)["sessions"]
            original = session_progress.evaluate

            def evaluate(
                *args: Any, source: Any = original, serving: Any = app, **kwargs: Any
            ) -> Any:
                answer = source(*args, **kwargs)
                self.assertEqual(levels.MEDIUM, next(iter(answer.values())).value)
                serving.snapshot.clear()
                return answer

            with self.serving(app) as port, patch.object(session_progress, "evaluate", evaluate):
                if route == "batch":
                    path = _progress_path(
                        snapshot.format_revision(rev), session_progress.identity(row)
                    )
                    self.assertEqual([], self.get(port, path)["rows"])
                else:
                    self.assertIsNone(
                        self.get(port, "/api/sessions")["sessions"][0]["stored_progress"]
                    )

    def test_workspace_identity_must_match_the_admitted_native_source(self) -> None:
        self.save_goal(lines=())
        self.record(self.departure())
        app = self.fresh_app(
            project_key="path:contradiction", project_identity_source="working directory path"
        )
        rev, body = app.collect_json(show_all=False)
        (row,) = json.loads(body)["sessions"]
        self.assertEqual("path:contradiction", row["project_key"])
        with self.serving(app) as port:
            path = _progress_path(snapshot.format_revision(rev), session_progress.identity(row))
            self.assertIsNone(self.get(port, path)["rows"][0]["stored_progress"])

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
