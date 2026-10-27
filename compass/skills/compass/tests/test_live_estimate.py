"""The live drift estimate the session page shows when the reader turns it on (DRC-4696).

Items 2 to 6 of
[DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn):
the live level is `levels.live_level` over the saved intent, computed without a model after every
call that can move it, published on the focused session's project context and nowhere else, and
never stored. "Rose from <level> at #<n>" is recomputed from the same replay every time.

Every transcript here is built from the recorded field shapes (`test_claude_checks.Transcript`).
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.client
import json
import socket
import statistics
import subprocess
import sys
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    http_api,
    levels,
    live_estimate,
    observer,
    project_context,
    reading,
    supervise,
)

from .support import make_server, serve_until_closed
from .test_claude_checks import SHORT, START
from .test_copied_corrections import _App
from .test_subagent_checks import Subagent

if TYPE_CHECKING:
    from collections.abc import Callable

GOAL = "Ship the placeholder parser"
LINE = "The parser tests pass"


def saved_row(**extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "harness": "claude",
        "sid": SHORT,
        "annotation_goal": GOAL,
        "annotation_line_1": LINE,
        "annotation_revision": 1,
        "annotation_settled_through": None,
    }
    row.update(extra)
    return row


class RoseFromTest(unittest.TestCase):
    """`levels.rose_from`: where the latest level was reached from a lower one on the scale."""

    def test_a_rise_names_the_level_before_and_the_step_that_reached_it(self) -> None:
        steps = [levels.NOT_ENOUGH, levels.MEDIUM, levels.MEDIUM, levels.HIGH, levels.HIGH]
        self.assertEqual((levels.MEDIUM, 3), levels.rose_from(steps))

    def test_the_latest_rise_counts_when_the_level_rose_twice(self) -> None:
        steps = [levels.MEDIUM, levels.HIGH, levels.MEDIUM, levels.HIGH]
        self.assertEqual((levels.MEDIUM, 3), levels.rose_from(steps))

    def test_nothing_rose_when_it_fell_held_or_came_from_off_the_scale(self) -> None:
        for steps in (
            [],
            [levels.HIGH],
            [levels.HIGH, levels.MEDIUM],
            [levels.MEDIUM, levels.MEDIUM],
            [levels.NOT_ENOUGH, levels.HIGH],
            [levels.NO_LIVE_LEVEL, levels.HIGH],
            [levels.MEDIUM, levels.NOT_ENOUGH],
        ):
            with self.subTest(steps=steps):
                self.assertIsNone(levels.rose_from(steps))

    def test_extreme_rises_from_high_and_none_or_low_rises_to_medium(self) -> None:
        self.assertEqual((levels.HIGH, 1), levels.rose_from([levels.HIGH, levels.EXTREME]))
        self.assertEqual(
            (levels.NONE_OR_LOW, 1), levels.rose_from([levels.NONE_OR_LOW, levels.MEDIUM])
        )


class _Replay(_App):
    """A saved intent and a transcript, replayed as the route replays it."""

    def facts_now(self) -> list[dict[str, Any]]:
        self.session.save(self.path)
        rows, _scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        return [
            project_context._semantic_fact_from_event(row, row["kind"], "tool_report", "")
            for row in rows
        ]

    def estimate(self, row: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        self.session.save(self.path)
        return live_estimate.for_session(
            self.config,
            row or saved_row(),
            str(self.path),
            kwargs.get("facts", []),
            floor=kwargs.get("floor"),
            now=12345.0,
        )


class TheLiveEstimateTest(_Replay):
    def test_it_changes_when_a_check_fails_and_names_where_it_rose(self) -> None:
        # setUp ran `pytest` and it passed; a write after that pass is Medium.
        self.session.write(self.session.cwd + "/src/a.py")
        medium = self.estimate()
        self.assertEqual(levels.MEDIUM, medium["level"])
        self.session.bash("pytest", "1 failed, 4 passed", is_error=True)
        high = self.estimate()
        self.assertEqual(levels.HIGH, high["level"])
        failing = [f for f in self.facts_now() if f.get("result") == "failed"]
        self.assertEqual(1, len(failing))
        self.assertEqual(levels.MEDIUM, high["rose_from"])
        self.assertEqual(failing[0]["fact_id"], high["rose_at"])
        self.assertIn(levels.REASON_FAILED_CHECK, high["reasons"])

    def test_a_session_that_changed_folder_reads_its_writes_from_where_it_began(self) -> None:
        # The record's cwd follows a `cd`, so a write read from it was a bare `a.py`, under
        # none of the folders the intent names (DRC-4884).
        began = self.root / "work" / "billing"
        (began / "src").mkdir()
        self.session.cwd = str(began / "src")
        self.session.write(self.session.cwd + "/a.py")
        seen: list[levels.Evidence] = []
        live_level = levels.live_level

        def spy(evidence: levels.Evidence, intent: levels.Intent) -> levels.Level:
            seen.append(evidence)
            return live_level(evidence, intent)

        with mock.patch.object(levels, "live_level", spy):
            self.estimate()
        self.assertTrue(seen)
        for evidence in seen:
            self.assertEqual(str(began), evidence.cwd)
        self.assertEqual(
            ["src/a.py"], [f["summary"] for f in seen[-1].facts if f.get("subject") == "write"]
        )

    def test_the_second_estimate_of_a_session_that_then_changed_folder_keeps_its_directory(
        self,
    ) -> None:
        # The second estimate resumes from a checkpoint of the first tally, which is built
        # without the scan: it has to carry the session directory itself.
        self.session.write(self.session.cwd + "/src/b.py")
        self.estimate()
        began = self.root / "work" / "billing"
        (began / "src").mkdir(exist_ok=True)
        self.session.cwd = str(began / "src")
        self.session.write(self.session.cwd + "/a.py")
        seen: list[levels.Evidence] = []
        live_level = levels.live_level

        def spy(evidence: levels.Evidence, intent: levels.Intent) -> levels.Level:
            seen.append(evidence)
            return live_level(evidence, intent)

        with mock.patch.object(levels, "live_level", spy):
            self.estimate()
        self.assertEqual(
            ["src/a.py", "src/b.py"],
            sorted(f["summary"] for f in seen[-1].facts if f.get("subject") == "write"),
        )

    def test_it_reads_not_enough_recorded_yet_with_too_little_recorded(self) -> None:
        # Only a prompt and a write: no check whose latest run passed.
        self.session.rows = self.session.rows[:1]
        self.session.write(self.session.cwd + "/a.py")
        answer = self.estimate()
        self.assertEqual(levels.NOT_ENOUGH, answer["level"])
        self.assertIn(levels.REASON_NO_PASSING_CHECK, answer["reasons"])
        self.assertIsNone(answer["rose_from"])
        self.assertIsNone(answer["rose_at"])

    def test_with_no_saved_revision_there_is_no_live_level(self) -> None:
        self.session.bash("pytest", "1 failed", is_error=True)
        for row in (
            saved_row(annotation_revision=0),
            saved_row(annotation_revision=None, annotation_goal="", annotation_line_1=""),
            saved_row(annotation_goal="", annotation_line_1=""),
        ):
            with (
                self.subTest(row=row),
                # Over a draft nothing is read at all, not merely no level drawn.
                mock.patch.object(
                    project_context, "_live_check_scan", side_effect=AssertionError("read")
                ),
                mock.patch.object(
                    live_estimate, "_live_signature", side_effect=AssertionError("stat")
                ),
            ):
                answer = self.estimate(row)
                self.assertEqual(levels.NO_LIVE_LEVEL, answer["level"])
                self.assertIsNone(answer["rose_from"])

    def test_a_missing_child_recomputes_an_empty_moving_call_window(self) -> None:
        self.session.rows = self.session.rows[:1]
        self.estimate()
        agent = self.session.call("Agent", {"prompt": "Run checks"})
        self.session.result(agent, "Done", tool_use_result={"agentId": "a1b2c3d4"})
        with mock.patch.object(levels, "live_level", wraps=levels.live_level) as level:
            self.assertEqual(levels.NOT_ENOUGH, self.estimate()["level"])
        self.assertGreater(level.call_count, 0)

    def test_a_level_that_fell_says_nothing_rose(self) -> None:
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.bash("pytest", "5 passed")
        answer = self.estimate()
        self.assertNotEqual(levels.HIGH, answer["level"])
        self.assertIsNone(answer["rose_from"])

    def test_it_carries_the_time_it_was_computed_and_the_revision_it_read(self) -> None:
        answer = self.estimate(saved_row(annotation_revision=3))
        self.assertEqual(12345.0, answer["computed_at"])
        self.assertEqual(3, answer["revision"])
        self.assertEqual(
            {"harness": "claude", "sid": SHORT},
            {"harness": answer["harness"], "sid": answer["sid"]},
        )

    def test_an_unsettled_later_direction_blocks_none_or_low_and_is_never_drift(self) -> None:
        later = {
            "fact_id": "d-1",
            "type": "user_message",
            "at": 50.0,
            "summary": "Also do the lexer",
            "source_session": {"harness": "claude", "sid": SHORT},
            "evidence": {"source": "root transcript", "confidence": "exact"},
        }
        quiet = self.estimate()
        blocked = self.estimate(facts=[later], floor=10.0)
        settled = self.estimate(
            saved_row(annotation_settled_through=60.0), facts=[later], floor=10.0
        )
        self.assertNotIn(levels.REASON_LATER_DIRECTION, quiet["reasons"])
        self.assertEqual(levels.NOT_ENOUGH, blocked["level"])
        self.assertIn(levels.REASON_LATER_DIRECTION, blocked["reasons"])
        self.assertNotIn(levels.REASON_LATER_DIRECTION, settled["reasons"])

    def test_no_model_is_launched_and_nothing_is_written(self) -> None:
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.save(self.path)
        before = sorted(p.name for p in self.root.rglob("*"))
        real_popen = subprocess.Popen

        def only_a_committed_file_read(argv: Any, *args: Any, **kwargs: Any) -> Any:
            # The one process the live estimate may start: git reading a project's declaring
            # files as a commit held them, so a declared script counts as a check here as it does
            # in the published facts. `subprocess.run` starts its child through `Popen`.
            words = [str(word) for word in argv] if isinstance(argv, (list, tuple)) else []
            reads = {"rev-parse", "rev-list", "ls-tree", "cat-file"}
            if not words or Path(words[0]).name != "git" or not reads & set(words):
                raise AssertionError("a process")
            return real_popen(argv, *args, **kwargs)

        with (
            mock.patch.object(subprocess, "Popen", side_effect=only_a_committed_file_read),
            mock.patch.object(socket, "create_connection", side_effect=AssertionError("a socket")),
            # Every model class the runtime can start: the goal summary and both reading
            # producers. Only the first was patched, so a Claude reading started from the
            # live path would have passed here while Popen was the sole guard.
            mock.patch.object(
                observer.CodexGoalModel, "__call__", side_effect=AssertionError("a model")
            ),
            mock.patch.object(
                reading.CodexReadingModel, "__call__", side_effect=AssertionError("a model")
            ),
            mock.patch.object(
                reading.ClaudeReadingModel, "__call__", side_effect=AssertionError("a model")
            ),
            # The two functions every CLI launch passes through. Without them the Claude class
            # above passes on a machine with no `claude` on PATH, where its lookup returns
            # before anything is started.
            mock.patch.object(observer, "claude_exec", side_effect=AssertionError("a model")),
            mock.patch.object(supervise, "run", side_effect=AssertionError("a process")),
        ):
            answer = live_estimate.for_session(
                self.config, saved_row(), str(self.path), [], floor=None, now=1.0
            )
        self.assertEqual(levels.HIGH, answer["level"])
        self.assertEqual(before, sorted(p.name for p in self.root.rglob("*")))

    def test_the_level_now_is_the_one_the_published_facts_give(self) -> None:
        # The replay's last step and `levels.live_level` over the published record agree.
        self.session.write(self.session.cwd + "/b.py")
        self.session.save(self.path)
        rows, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        facts = [
            project_context._semantic_fact_from_event(row, row["kind"], "tool_report", "")
            for row in rows
        ]
        direct = levels.live_level(
            levels.Evidence(tuple(facts), scan, 0, str(self.session.cwd)),
            levels.Intent(saved=True, goal=GOAL, lines=(LINE,)),
        )
        self.assertEqual(direct.level, self.estimate()["level"])


class TheReplayIsBoundedTest(_Replay):
    """The level is asked for over the last `LIVE_REPLAY_STEPS` moving calls only, and a
    request that finds the transcript and the words unchanged replays nothing."""

    def many_calls(self, n: int) -> None:
        # Distinct targeted checks beside writes: the shape that made each evaluation
        # cost more as the transcript grew (review of d2854fc1, F1).
        for i in range(n):
            if i % 2:
                self.session.bash(f"pytest tests/test_mod.py::test_case_{i}", "1 passed in 0.1s")
            else:
                self.session.write(f"{self.session.cwd}/src/f{i % 50}.py")

    def test_the_level_is_evaluated_at_most_once_per_step_of_the_window(self) -> None:
        self.many_calls(500)
        with mock.patch.object(levels, "live_level", wraps=levels.live_level) as spy:
            self.estimate()
        self.assertLessEqual(spy.call_count, live_estimate.LIVE_REPLAY_STEPS + 2)

    def test_a_rise_older_than_the_window_is_withheld_and_one_inside_it_is_named(self) -> None:
        self.session.write(self.session.cwd + "/src/a.py")
        self.session.bash("pytest", "1 failed, 4 passed", is_error=True)
        # Read-only shell calls step the replay without moving the level.
        for _ in range(live_estimate.LIVE_REPLAY_STEPS - 2):
            self.session.bash("ls", "a b")
        inside = self.estimate()
        self.assertEqual((levels.HIGH, levels.MEDIUM), (inside["level"], inside["rose_from"]))
        for _ in range(3):
            self.session.bash("ls", "a b")
        outside = self.estimate()
        self.assertEqual(levels.HIGH, outside["level"])
        self.assertIsNone(outside["rose_from"])
        self.assertIsNone(outside["rose_at"])

    def test_an_unchanged_transcript_and_unchanged_words_replay_nothing(self) -> None:
        self.session.bash("pytest", "1 failed", is_error=True)
        first = self.estimate()
        with mock.patch.object(
            project_context, "_live_check_scan", side_effect=AssertionError("replayed")
        ):
            again = live_estimate.for_session(
                self.config, saved_row(), str(self.path), [], floor=None, now=99999.0
            )
        self.assertEqual(first, again)

    def test_new_words_a_new_call_or_a_settled_direction_replay_again(self) -> None:
        later = {
            "fact_id": "d-1",
            "type": "user_message",
            "at": 50.0,
            "summary": "Also do the lexer",
            "source_session": {"harness": "claude", "sid": SHORT},
            "evidence": {"source": "root transcript", "confidence": "exact"},
        }
        self.estimate()
        with mock.patch.object(
            project_context, "_live_check_scan", wraps=project_context._live_check_scan
        ) as reads:
            self.assertEqual(2, self.estimate(saved_row(annotation_revision=2))["revision"])
            self.assertEqual(levels.NOT_ENOUGH, self.estimate(facts=[later], floor=10.0)["level"])
            self.session.bash("pytest", "1 failed", is_error=True)
            self.assertEqual(levels.HIGH, self.estimate()["level"])
        self.assertEqual(3, reads.call_count)

    def test_a_turn_that_adds_one_call_asks_for_one_new_level(self) -> None:
        # A live session grows between two generations; the steps it already had
        # stand, so a new call costs one ask rather than the whole window again.
        self.many_calls(500)
        self.estimate()
        self.session.write(self.session.cwd + "/src/new.py")
        with mock.patch.object(levels, "live_level", wraps=levels.live_level) as spy:
            self.estimate()
        self.assertEqual(1, spy.call_count)

    def test_a_shifted_window_replays_the_current_tail_instead_of_all_old_checks(self) -> None:
        self.session.rows = self.session.rows[:1]
        for i in range(160):
            self.session.bash(
                f"pytest tests/test_mod.py::test_case_{i}", "1 passed\n" + "x" * 60_000
            )
        self.session.save(self.path)
        self.assertGreater(self.path.stat().st_size, 8 * 1024 * 1024)
        self.estimate()
        self.session.bash("pytest tests/test_mod.py::test_case_160", "1 passed\n" + "x" * 60_000)
        real_add = project_context._ToolReportTally.add
        added = 0

        def counted(tally: Any, *args: Any) -> None:
            nonlocal added
            added += 1
            real_add(tally, *args)

        with mock.patch.object(project_context._ToolReportTally, "add", counted):
            shifted = self.estimate()
        self.assertLessEqual(added, live_estimate.LIVE_REPLAY_STEPS + 3)
        live_estimate._cache.clear()
        fresh = self.estimate()
        self.assertEqual(
            {k: v for k, v in shifted.items() if k != "computed_at"},
            {k: v for k, v in fresh.items() if k != "computed_at"},
        )

    def test_mixed_checks_and_writes_match_a_fresh_scan_as_the_window_shifts(self) -> None:
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=40_000)
        self.session.rows = self.session.rows[:1]
        for i in range(120):
            if i % 5 == 0:
                self.session.write(f"{self.session.cwd}/src/f{i}.py")
            else:
                self.session.bash(
                    f"pytest tests/test_mod.py::test_case_{i}", "1 passed\n" + "x" * 100
                )
        self.session.save(self.path)
        self.assertGreater(self.path.stat().st_size, self.config.turn_scan_max_bytes)
        self.estimate()
        actions: tuple[Callable[[], Any], ...] = (
            lambda: self.session.write(self.session.cwd + "/docs/outside.md"),
            lambda: self.session.bash(
                "pytest tests/test_mod.py::test_case_121", "1 failed", is_error=True
            ),
            lambda: self.session.bash("pytest tests/test_mod.py::test_case_122", "1 passed"),
            lambda: self.session.write(self.session.cwd + "/src/f0.py"),
        )
        for step, action in enumerate(actions):
            action()
            grown = self.estimate()
            live_estimate._cache.clear()
            fresh = self.estimate()
            with self.subTest(step=step):
                self.assertEqual(
                    {k: v for k, v in fresh.items() if k != "computed_at"},
                    {k: v for k, v in grown.items() if k != "computed_at"},
                )

    def test_an_evicted_redirected_check_does_not_keep_its_write(self) -> None:
        self.session.rows = self.session.rows[:1]
        self.session.bash("pytest > docs/outside.txt", "1 passed")
        for i in range(69):
            self.session.bash(f"pytest tests/test_mod.py::test_case_{i}", "1 passed")
        self.session.save(self.path)
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=self.path.stat().st_size)
        intent = saved_row(annotation_goal="Only touch src/", annotation_line_1="Only touch src/")
        self.estimate(intent)
        self.session.bash("pytest tests/test_mod.py::test_case_70", "1 passed")
        grown = self.estimate(intent)
        live_estimate._cache.clear()
        fresh = self.estimate(intent)
        self.assertEqual(
            {k: v for k, v in fresh.items() if k != "computed_at"},
            {k: v for k, v in grown.items() if k != "computed_at"},
        )

    def test_a_turn_over_eight_megabytes_is_faster_than_a_fresh_replay(self) -> None:
        if sys.gettrace() is not None or "coverage" in sys.modules:
            self.skipTest("timed without a tracer only")
        self.session.rows = self.session.rows[:1]
        for i in range(5000):
            self.session.bash(f"pytest tests/test_mod.py::test_case_{i}", "1 passed\n" + "x" * 1100)
        self.session.save(self.path)
        self.assertGreater(self.path.stat().st_size, 8 * 1024 * 1024)
        self.estimate()
        warm_times: list[float] = []
        fresh_times: list[float] = []
        for i in range(3):
            self.session.bash(
                f"pytest tests/test_mod.py::test_case_{5000 + i}",
                "1 passed\n" + "x" * 4000,
            )
            self.session.save(self.path)
            started = time.perf_counter()
            warm = live_estimate.for_session(
                self.config, saved_row(), str(self.path), (), floor=None, now=12345.0
            )
            warm_times.append(time.perf_counter() - started)
            live_estimate._cache.clear()
            started = time.perf_counter()
            fresh = live_estimate.for_session(
                self.config, saved_row(), str(self.path), (), floor=None, now=12345.0
            )
            fresh_times.append(time.perf_counter() - started)
            self.assertEqual(warm, fresh)
        warm_median, fresh_median = statistics.median(warm_times), statistics.median(fresh_times)
        # A coarse cross-platform performance guard, alongside the bounded-work checks above. Both paths
        # took about four seconds on a hosted Python 3.11 runner, and a bound of 95% of the fresh replay failed
        # there on noise alone (4.26 s against 4.23 s). The guard is for a warm read that costs MORE than a
        # fresh one, which the exact-work checks above do not measure, so it allows twice the fresh replay.
        self.assertLess(warm_median, 2.0 * fresh_median + 0.5, (warm_times, fresh_times))

    def test_a_growing_transcript_reads_what_a_fresh_replay_reads(self) -> None:
        cwd = self.session.cwd
        t = self.session
        late = ""

        def call_whose_result_comes_later() -> None:
            nonlocal late
            late = t.call("Bash", {"command": "pytest tests"})

        steps: list[Callable[[], object]] = [
            lambda: t.write(cwd + "/src/a.py"),
            call_whose_result_comes_later,
            lambda: t.write(cwd + "/src/b.py"),
            lambda: t.result(late, "Exit code 1\n1 failed", is_error=True),
            lambda: t.prompt("Also the lexer"),
            lambda: t.bash("pytest tests", "5 passed"),
            lambda: t.write("/elsewhere/c.py"),
            lambda: t.write(cwd + "/src/a.py"),
            lambda: t.bash("pytest tests", "1 failed", is_error=True),
        ]
        for n, step in enumerate(steps):
            step()
            grown = self.estimate()
            live_estimate._cache.clear()
            fresh = self.estimate()
            with self.subTest(step=n):
                self.assertEqual(
                    {k: v for k, v in fresh.items() if k != "computed_at"},
                    {k: v for k, v in grown.items() if k != "computed_at"},
                )

    def test_a_call_id_seen_before_with_other_content_is_read_afresh(self) -> None:
        # Ids alone do not identify a call: a transcript rewritten at the same path
        # can reuse one, and the steps it had then are about another call.
        self.session.write("/elsewhere/y.py")
        self.estimate()
        self.session.rows = self.session.rows[:3]
        self.session.calls = 1
        self.session.bash("pytest", "1 failed", is_error=True)
        grown = self.estimate()
        live_estimate._cache.clear()
        self.assertEqual(self.estimate(), grown)

    def tail_that_raises_the_level(self, n: int) -> None:
        # The shape from the review of the replay cache (V1): passing checks and
        # writes inside the words, then a tail of failures and writes outside them,
        # so each call near the end moves the level.
        cwd = self.session.cwd
        for i in range(n):
            if i < n - 8:
                if i % 2:
                    self.session.bash("pytest tests", "5 passed in 0.1s")
                else:
                    self.session.edit(f"{cwd}/src/f{i}.py")
            elif i % 2:
                self.session.write(f"{cwd}/docs/out{i}.md")
            else:
                self.session.bash("pytest tests", "Exit code 1\n1 failed", is_error=True)

    def assert_reads_the_last_call(self, case: str) -> None:
        cached = self.estimate()
        facts = tuple(self.facts_now())
        _rows, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        intent = live_estimate.saved_intent(saved_row())
        evidence = levels.Evidence(facts, scan, 0, str(self.session.cwd))
        frozen = levels.live_level(evidence, intent).level
        live_estimate._cache.clear()
        fresh = self.estimate()
        with self.subTest(case=case):
            self.assertEqual(frozen, cached["level"])
            self.assertEqual(
                {k: v for k, v in fresh.items() if k != "computed_at"},
                {k: v for k, v in cached.items() if k != "computed_at"},
            )

    def truncated(self, n: int, drop: int) -> None:
        # A rewind or a replaced file can shorten a transcript at its tail. The step the
        # cache holds for the call now last was right, but the level published must be
        # asked at that call, not at the last step the replay happened to recompute.
        self.tail_that_raises_the_level(n)
        self.estimate()
        del self.session.rows[-2 * drop :]
        self.assert_reads_the_last_call(f"{n} calls, last {drop} dropped")

    def test_seventy_calls_that_lose_three_read_the_call_now_last(self) -> None:
        self.truncated(70, 3)

    def test_seventy_calls_that_lose_six_read_the_call_now_last(self) -> None:
        self.truncated(70, 6)

    def test_two_hundred_calls_that_lose_five_read_the_call_now_last(self) -> None:
        self.truncated(200, 5)

    def test_a_truncated_transcript_that_grows_again_reads_the_call_now_last(self) -> None:
        self.tail_that_raises_the_level(70)
        self.estimate()
        dropped = self.session.rows[-12:]
        # Six calls gone, three of them back before the next read: still a prefix.
        del self.session.rows[-12:]
        self.session.rows.extend(dropped[:6])
        self.assert_reads_the_last_call("70 calls, 6 dropped, 3 back")
        # Then new calls after a read of the truncated file.
        del self.session.rows[-6:]
        self.estimate()
        self.session.calls = 200
        self.session.bash("pytest tests", "5 passed in 0.1s")
        self.session.write(self.session.cwd + "/src/new.py")
        self.assert_reads_the_last_call("70 calls, 6 dropped, 2 new")

    def test_a_long_transcript_costs_about_what_the_record_itself_costs(self) -> None:
        if sys.gettrace() is not None or "coverage" in sys.modules:
            # Measured: tracing slowed the replay's many small calls about 22 times and the
            # record's about 6 times, so a ratio under a tracer measures the tracer.
            self.skipTest("timed without a tracer only")
        self.many_calls(3000)
        self.session.save(self.path)
        started = time.perf_counter()
        project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        record = time.perf_counter() - started
        started = time.perf_counter()
        self.estimate()
        live = time.perf_counter() - started
        # The unbounded replay took about 150 times the record's cost on this transcript.
        # The bounded one measured about 11 times on macOS and 23 times on the Windows
        # runner (PR #429), so the bound catches the regression without timing the runner.
        self.assertLess(live, 1.0 + 50 * record, (live, record))


class TheReplayMatchesTheRecordTest(_Replay):
    """Every step's level is `levels.live_level` over the record as it stood after that
    call, and the last step reads the very facts and scan the record publishes."""

    INTENTS = (
        levels.Intent(saved=True, goal=GOAL, lines=(LINE,)),
        levels.Intent(saved=True, goal=GOAL, lines=("Only touch src/", LINE)),
    )

    def actions(self) -> dict[str, Any]:
        cwd = self.session.cwd
        t = self.session
        return {
            "pass": lambda: t.bash("pytest tests", "5 passed in 0.1s"),
            "fail": lambda: t.bash("pytest tests", "1 failed, 4 passed", is_error=True),
            "zero": lambda: t.bash("pytest tests", "0 passed in 0.01s"),
            "noresult": lambda: t.call("Bash", {"command": "pytest tests"}),
            "bg": lambda: t.bash("pytest tests &", ""),
            "fixer": lambda: t.bash("black .", "reformatted 1 file"),
            "w_in": lambda: t.write(cwd + "/src/a.py"),
            "w_out": lambda: t.write(cwd + "/docs/x.md"),
            "w_far": lambda: t.write("/elsewhere/y.py"),
            "redir": lambda: t.bash("echo x > src/gen.py", ""),
            "redir_out": lambda: t.bash("echo x > /tmp/gen.py", ""),
            "passfix": lambda: t.bash("pytest tests && black .", "5 passed\nreformatted"),
        }

    def row_for(self, intent: levels.Intent) -> dict[str, Any]:
        row = saved_row(annotation_line_1="")
        for k, line in enumerate(intent.lines, 1):
            row[f"annotation_line_{k}"] = line
        return row

    def published(self) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
        self.session.save(self.path)
        rows, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        facts = tuple(
            project_context._semantic_fact_from_event(r, r["kind"], "tool_report", "") for r in rows
        )
        return facts, scan

    def replayed(self, sequence: list[str], intent: levels.Intent) -> None:
        self.session.rows = self.session.rows[:1]
        acts = self.actions()
        facts, scan = self.published()
        cwd = str(self.session.cwd)
        expected = [levels.live_level(levels.Evidence(facts, scan, 0, cwd), intent).level]
        for name in sequence:
            acts[name]()
            facts, scan = self.published()
            expected.append(levels.live_level(levels.Evidence(facts, scan, 0, cwd), intent).level)
        steps: list[list[str]] = []
        read: list[levels.Evidence] = []
        rose_from, live_level = levels.rose_from, levels.live_level

        def spy_steps(found: Any) -> Any:
            steps.append(list(found))
            return rose_from(found)

        def spy_level(evidence: levels.Evidence, words: levels.Intent) -> levels.Level:
            read.append(evidence)
            return live_level(evidence, words)

        with (
            mock.patch.object(levels, "rose_from", spy_steps),
            mock.patch.object(levels, "live_level", spy_level),
        ):
            answer = self.estimate(self.row_for(intent))
        self.assertEqual(expected, steps[-1])
        self.assertEqual(expected[-1], answer["level"])
        self.assertEqual((facts, scan), (read[-1].facts, read[-1].scan))

    def test_each_step_and_the_last_read_agree_with_the_record(self) -> None:
        for sequence in (
            # The review's fuzz state where a lost `passed` restore read not_enough.
            ["passfix", "redir_out", "fail", "fail", "redir_out", "redir", "redir_out",
             "redir_out", "pass"],
            ["pass", "w_in", "fail", "noresult", "bg", "fixer", "zero", "pass", "w_out",
             "w_far", "redir", "pass", "w_in", "w_out", "w_out"],
            ["zero", "pass", "pass", "fail", "pass", "fixer", "passfix", "w_far", "redir_out"],
        ):  # fmt: skip
            for intent in self.INTENTS:
                with self.subTest(sequence=sequence, lines=intent.lines):
                    self.replayed(sequence, intent)


class WhereItRoseTest(_Replay):
    def test_a_rise_whose_entry_a_later_call_replaced_names_no_entry(self) -> None:
        # setUp's pass, then a write (Medium, risen at the write), then the same path
        # written again: the rising call's entry is gone from the record.
        self.session.write(self.session.cwd + "/src/a.py")
        risen = self.estimate()
        self.assertIsNotNone(risen["rose_at"])
        self.session.write(self.session.cwd + "/src/a.py")
        answer = self.estimate()
        self.assertEqual(levels.MEDIUM, answer["level"])
        self.assertIsNone(answer["rose_from"])
        self.assertIsNone(answer["rose_at"])

    def test_a_call_that_left_a_write_and_a_check_names_the_check(self) -> None:
        # A check's own redirect is a write by the same call (DRC-4709).
        self.session.bash("pytest > src/out.txt", "", is_error=True)
        facts = self.facts_now()
        self.assertEqual(
            {"check", "write"},
            {f["subject"] for f in facts if f["branch"]["record_id"] == "toolu_002"},
        )
        answer = self.estimate()
        self.assertEqual(
            (levels.MEDIUM, levels.NONE_OR_LOW), (answer["level"], answer["rose_from"])
        )
        failing = [f["fact_id"] for f in facts if f.get("result") == "failed"]
        self.assertEqual(failing, [answer["rose_at"]])


class TheRouteTest(_Replay):
    """Published on the focused project context only, over a real socket."""

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

    def save_goal(self) -> None:
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

    def test_failed_check_citations_reach_only_the_focused_route_and_resolve_to_native_facts(
        self,
    ) -> None:
        self.save_goal()
        self.session.bash("pytest tests/parser", "1 failed", is_error=True)
        self.session.save(self.path)
        with self.serving() as port:
            focused = self.get(port, f"/api/project-context?project=billing&session=claude:{SHORT}")
            project = self.get(port, "/api/project-context?project=billing")
            board = self.get(port, "/api/data")
        found = focused["sources"]["work"]["live_levels"][0]
        failed = [f for f in focused["semantic"]["facts"] if f.get("result") == "failed"]
        self.assertIn("cites", found)
        self.assertEqual([f["fact_id"] for f in failed], found["cites"])
        self.assertNotEqual(failed[0]["at"], failed[0]["result_at"])
        self.assertNotIn("live_levels", project["sources"]["work"])
        self.assertNotIn("live_levels", json.dumps(board))

    def test_all_computed_signal_citations_survive_not_just_the_rise_entry(self) -> None:
        self.save_goal()
        self.session.write(self.session.cwd + "/src/synthetic.py")
        self.session.bash("pytest tests/parser", "1 failed", is_error=True)
        self.session.save(self.path)
        with self.serving() as port:
            focused = self.get(port, f"/api/project-context?project=billing&session=claude:{SHORT}")
        found = focused["sources"]["work"]["live_levels"][0]
        facts = focused["semantic"]["facts"]
        # pass-then-write cites the preceding passing check; the later write is counted
        # by the replay, rather than added to that signal's existing citation contract.
        relevant = [f for f in facts if f.get("subject") == "check"]
        self.assertEqual({f["fact_id"] for f in relevant}, set(found["cites"]))
        self.assertEqual(2, len(found["cites"]))

    def test_the_focused_context_publishes_the_live_level_and_nothing_else_does(self) -> None:
        self.save_goal()
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.save(self.path)
        with self.serving() as port:
            focused = self.get(port, f"/api/project-context?project=billing&session=claude:{SHORT}")
            project = self.get(port, "/api/project-context?project=billing")
            board = self.get(port, "/api/data")
        live = focused["sources"]["work"]["live_levels"]
        self.assertEqual(1, len(live))
        self.assertEqual(
            ("claude", SHORT, levels.HIGH), (live[0]["harness"], live[0]["sid"], live[0]["level"])
        )
        self.assertNotIn("live_levels", project["sources"]["work"])
        # Never on a Sessions row: the board's rows carry no level of any kind.
        self.assertNotIn("live_level", json.dumps(board))
        self.assertNotIn('"level"', json.dumps(board["sessions"]))

    def test_a_delegated_failure_raises_the_focused_level_beside_its_recorded_check(self) -> None:
        self.save_goal()
        agent = self.session.call("Agent", {"description": "Run tests", "prompt": "Run tests."})
        child = Subagent(self.session, "a1b2c3d4e5f60718")
        child.prompt("Run tests.")
        child.bash("pytest tests/test_sub.py", "1 failed", is_error=True)
        self.session.result(
            agent,
            [{"type": "text", "text": "Done."}],
            tool_use_result={"agentId": child.agent_id, "status": "completed"},
        )
        self.session.save(self.path)
        child.save(self.path.with_suffix("") / "subagents" / f"agent-{child.agent_id}.jsonl")
        with self.serving() as port:
            focused = self.get(port, f"/api/project-context?project=billing&session=claude:{SHORT}")
        live = focused["sources"]["work"]["live_levels"][0]
        failures = [
            fact
            for fact in focused["semantic"]["facts"]
            if fact.get("result") == "failed" and fact.get("worker_kind") == "subagent"
        ]
        self.assertEqual(1, len(failures))
        self.assertEqual(levels.HIGH, live["level"])
        self.assertEqual(failures[0]["fact_id"], live["rose_at"])
        self.assertIn(failures[0]["fact_id"], live["cites"])

    def test_the_entry_it_rose_at_is_one_the_page_holds(self) -> None:
        self.save_goal()
        self.session.write(self.session.cwd + "/src/a.py")
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.save(self.path)
        with self.serving() as port:
            focused = self.get(port, f"/api/project-context?project=billing&session=claude:{SHORT}")
        live = focused["sources"]["work"]["live_levels"][0]
        self.assertEqual(levels.MEDIUM, live["rose_from"])
        failing = [
            f["fact_id"] for f in focused["semantic"]["facts"] if f.get("result") == "failed"
        ]
        self.assertEqual(failing, [live["rose_at"]])

    def test_the_reading_routes_own_context_carries_no_live_level(self) -> None:
        self.save_goal()
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.save(self.path)
        app = self.app()
        _rev, body = app.collect_json(show_all=True)
        row = json.loads(body)["sessions"][0]
        context = http_api._session_context(app, row)
        self.assertNotIn("live_levels", json.dumps(context))

    def test_a_later_direction_reaches_the_level_and_keep_settles_it(self) -> None:
        # A prompt before the save is under the saved goal's floor and is no later direction.
        self.session.prompt("Before the goal was saved")
        self.save_goal()
        self.session.save(self.path)
        path = f"/api/project-context?project=billing&session=claude:{SHORT}"
        with self.serving() as port:
            quiet = self.get(port, path)["sources"]["work"]["live_levels"][0]
            self.session.prompt("Also do the lexer")
            self.session.save(self.path)
            later = self.get(port, path)["sources"]["work"]["live_levels"][0]
            # Keep, as the page sends it with no reader.
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                conn.request(
                    "POST",
                    "/api/annotate",
                    body=json.dumps(
                        {"harness": "claude", "sid": SHORT, "settle_through": self.now}
                    ).encode(),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(200, conn.getresponse().status)
            finally:
                conn.close()
            kept = self.get(port, path)["sources"]["work"]["live_levels"][0]
        self.assertNotIn(levels.REASON_LATER_DIRECTION, quiet["reasons"])
        self.assertEqual(levels.NOT_ENOUGH, later["level"])
        self.assertIn(levels.REASON_LATER_DIRECTION, later["reasons"])
        self.assertNotIn(levels.REASON_LATER_DIRECTION, kept["reasons"])

    def test_a_request_under_another_project_gets_no_level(self) -> None:
        self.save_goal()
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.save(self.path)
        with self.serving() as port:
            elsewhere = self.get(
                port, f"/api/project-context?project=elsewhere&session=claude:{SHORT}"
            )
        self.assertNotIn("live_levels", json.dumps(elsewhere))

    def test_with_annotations_off_nothing_is_published(self) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=False)
        with self.serving() as port:
            focused = self.get(port, f"/api/project-context?project=billing&session=claude:{SHORT}")
        self.assertNotIn("live_levels", focused["sources"]["work"])


class TheWorktreeSubagentWriteTest(_Replay):
    """Ruled 2026-10-21 (owner, DRC-4891): a write in an isolation worktree counts against the
    folder inside its checkout. The published path keeps the checkout prefix."""

    def setUp(self) -> None:
        super().setUp()
        self.session_dir = Path(self.session.cwd)
        (self.session_dir / "src").mkdir()

    def delegated_write(self, relative: str, agent_id: str = "a1b2c3d4e5f60718") -> str:
        """A subagent whose own records are in `.claude/worktrees/agent-a1`, writing `relative`."""
        worktree = self.session_dir / ".claude" / "worktrees" / "agent-a1"
        call = self.session.call("Agent", {"description": "Edit", "prompt": "Edit."})
        sub = Subagent(self.session, agent_id)
        sub.cwd = str(worktree)
        sub.prompt("Edit.")
        sub.edit(str(worktree / relative))
        sub.save(self.path.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl")
        self.session.result(
            call,
            [{"type": "text", "text": "Done."}],
            tool_use_result={"agentId": agent_id, "status": "completed"},
        )
        return agent_id

    def live(self) -> levels.Level:
        """The live level of the one estimate the test runs, read from the spy's return."""
        seen: list[levels.Level] = []
        live_level = levels.live_level

        def spy(evidence: levels.Evidence, intent: levels.Intent) -> levels.Level:
            got = live_level(evidence, intent)
            seen.append(got)
            return got

        with mock.patch.object(levels, "live_level", spy):
            self.estimate(saved_row(annotation_goal="Only edit src/ for the parser"))
        self.assertTrue(seen)
        return seen[-1]

    def published_writes(self) -> list[str]:
        return [f["summary"] for f in self.facts_now() if f.get("subject") == "write"]

    @unittest.expectedFailure  # DRC-4891: the ruling is recorded here; levels.inside changes in its own PR.
    def test_a_worktree_write_to_the_named_folder_counts_inside_it(self) -> None:
        self.delegated_write("src/m.py")
        self.assertEqual([".claude/worktrees/agent-a1/src/m.py"], self.published_writes())
        got = self.live()
        self.assertEqual(1, got.writes_total)
        self.assertEqual(0, got.writes_outside)
        self.assertNotIn(levels.REASON_SOME_OUTSIDE, got.reasons)

    def test_a_worktree_write_outside_the_named_folder_still_counts_outside(self) -> None:
        self.delegated_write("web/m.py")
        self.assertEqual([".claude/worktrees/agent-a1/web/m.py"], self.published_writes())
        got = self.live()
        self.assertEqual(1, got.writes_total)
        self.assertEqual(1, got.writes_outside)


if __name__ == "__main__":
    unittest.main()
