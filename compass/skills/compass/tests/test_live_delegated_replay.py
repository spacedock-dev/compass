"""The focused live estimate reads the same delegated check evidence as the session page."""

from __future__ import annotations

import concurrent.futures
import threading
import unittest
from typing import Any
from unittest import mock

from compass_runtime import levels, live_estimate, project_context

from .test_claude_checks import SHORT
from .test_live_estimate import saved_row
from .test_subagent_checks import SubagentChecksTestCase


class RiseFactResolutionTest(unittest.TestCase):
    def test_a_colliding_call_id_cites_the_rising_child_write(self) -> None:
        calls = [
            (2.0, "/repo", "same-id", "Bash", {"command": "pytest"}, ""),
            (2.0, "/repo", "same-id", "Write", {"file_path": "/repo/a.py"}, "subagent"),
        ]
        rows = [
            {"record_id": "same-id", "at": 2.0, "subject": "check"},
            {"record_id": "same-id", "at": 2.0, "subject": "write", "worker_kind": "subagent"},
        ]
        with mock.patch.object(
            live_estimate, "_fact", side_effect=lambda row: {"fact_id": row["subject"]}
        ):
            found = live_estimate._found_from_steps(
                levels.Level(levels.MEDIUM, "live", ()),
                {-1: levels.NONE_OR_LOW, 0: levels.NONE_OR_LOW, 1: levels.MEDIUM},
                rows,
                calls,
                0,
            )
        self.assertEqual("write", found["rose_at"])

    def test_a_shifted_head_repeated_later_requires_fresh_listing_order(self) -> None:
        tally = project_context._ToolReportTally({}, "/repo")
        tally.runs = {
            "A": [{"seq": 1}, {"seq": 3}],
            "B": [{"seq": 2}],
        }
        # The fresh retained order is B, A. Keeping A's dictionary slot
        # would change a tied top-twelve listing and its fact citations.
        self.assertFalse(live_estimate._drop_safe_head(tally, [("A", 1)]))

    def test_a_redirected_pass_is_not_a_removable_head(self) -> None:
        tally = project_context._ToolReportTally(
            {"one": project_context._Result({"content": "5 passed", "is_error": False}, 2.0)},
            "/repo",
        )
        before = live_estimate._head_state(tally)
        tally.add(2.0, "/repo", "one", "Bash", {"command": "pytest > src/log.txt"})
        self.assertEqual("passed", tally._last_added_runs[0][1]["result"])
        self.assertEqual(1, len(tally.write_calls))
        self.assertIsNone(live_estimate._safe_head_effect(tally, before, "Bash"))


class DelegatedLiveReplayTest(SubagentChecksTestCase):
    def estimate(self, *, now: float = 100.0) -> dict[str, object]:
        self.save_all()
        return live_estimate.for_session(
            self.config, saved_row(), str(self.path), (), floor=None, now=now
        )

    def test_a_delegated_failure_raises_the_focused_level_shown_beside_its_check(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("pytest tests/test_sub.py", "1 failed", is_error=True)
        self.returns(sub)

        collected = self.collect()
        checks = [f for f in collected["semantic"]["facts"] if f.get("subject") == "check"]
        self.assertEqual(["failed", "passed"], [f["result"] for f in checks])
        self.assertEqual(levels.HIGH, self.estimate()["level"])

    def test_a_child_only_append_invalidates_the_focused_level(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("pytest tests/test_sub.py", "1 failed", is_error=True)
        self.returns(sub)
        self.assertEqual(levels.HIGH, self.estimate()["level"])

        sub.bash("pytest tests/test_sub.py", "5 passed", is_error=False)
        changed = self.estimate(now=101.0)
        self.assertNotEqual(levels.HIGH, changed["level"])
        self.assertEqual(101.0, changed["computed_at"])

    def test_a_named_missing_child_withholds_reassurance_from_a_parent_pass(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        self.returns(sub)
        self.session.save(self.path)

        rows, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertTrue(next(r for r in rows if r["subject"] == "check")["read_incomplete"])
        self.assertEqual(1, scan["subagent_transcripts_unread"])
        live = live_estimate.for_session(
            self.config, saved_row(), str(self.path), (), floor=None, now=100.0
        )
        self.assertEqual(levels.NOT_ENOUGH, live["level"])

    def test_a_child_only_failure_uses_the_published_check_for_its_rise(self) -> None:
        self.session.write(self.session.cwd + "/src/a.py")
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("pytest tests/test_sub.py", "1 failed", is_error=True)
        self.returns(sub)

        rows, _scan = self.read()
        failure = next(r for r in rows if r.get("result") == "failed")
        fact = project_context._semantic_fact_from_event(
            failure, failure["kind"], "tool_report", ""
        )
        live = self.estimate()
        self.assertEqual(levels.HIGH, live["level"])
        self.assertEqual(fact["fact_id"], live["rose_at"])

    def test_a_restored_named_child_refreshes_a_withheld_parent_pass(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        self.returns(sub)
        self.session.save(self.path)
        before = live_estimate.for_session(
            self.config, saved_row(), str(self.path), (), floor=None, now=100.0
        )
        self.assertEqual(levels.NOT_ENOUGH, before["level"])

        sub.bash("ruff check .", "All checks passed!", is_error=False)
        after = self.estimate(now=101.0)
        self.assertEqual(levels.NONE_OR_LOW, after["level"])
        self.assertEqual(101.0, after["computed_at"])

    def test_a_removed_named_child_invalidates_a_previous_failure(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("pytest tests/test_sub.py", "1 failed", is_error=True)
        self.returns(sub)
        self.assertEqual(levels.HIGH, self.estimate()["level"])

        self.subagents[0][1].unlink()
        changed = live_estimate.for_session(
            self.config, saved_row(), str(self.path), (), floor=None, now=101.0
        )
        self.assertEqual(levels.NOT_ENOUGH, changed["level"])
        self.assertEqual(101.0, changed["computed_at"])

    def test_equal_time_parent_and_child_checks_use_the_collected_winner(self) -> None:
        parent_id = self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        child_id = sub.bash("pytest", "1 failed", is_error=True)
        self.returns(sub)
        parent_call = next(
            r
            for r in self.session.rows
            if r["type"] == "assistant" and r["message"]["content"][0].get("id") == parent_id
        )
        parent_result = next(
            r
            for r in self.session.rows
            if r["type"] == "user" and r["message"]["content"][0].get("tool_use_id") == parent_id
        )
        child_call = next(r for r in sub.rows if r["type"] == "assistant")
        child_result = next(
            r
            for r in sub.rows
            if r["type"] == "user" and r["message"]["content"][0].get("tool_use_id") == child_id
        )
        child_call["timestamp"] = parent_call["timestamp"]
        child_result["timestamp"] = parent_result["timestamp"]
        rows, _scan = self.read()
        check = next(row for row in rows if row["subject"] == "check")
        self.assertEqual(("failed", child_id), (check["result"], check["record_id"]))
        fact = project_context._semantic_fact_from_event(check, check["kind"], "tool_report", "")
        live = self.estimate()
        self.assertEqual(levels.HIGH, live["level"])
        self.assertEqual(fact["fact_id"], live["rose_at"])

    def test_two_readers_of_one_cold_session_share_its_computation(self) -> None:
        self.session.bash("pytest", "1 failed", is_error=True)
        self.save_all()
        live_estimate._cache.clear()
        entered = threading.Event()
        second_lookup = threading.Event()
        release = threading.Event()
        calls = 0
        real = project_context._live_check_scan

        class Flights(dict[object, object]):
            lookups = 0

            def get(self, key: object, default: object = None) -> object:
                self.lookups += 1
                if self.lookups == 2:
                    second_lookup.set()
                return super().get(key, default)

        def slow(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                if not release.wait(30):
                    raise AssertionError("the first replay did not finish")
            return real(*args, **kwargs)

        def request() -> dict[str, object]:
            return live_estimate.for_session(
                self.config, saved_row(), str(self.path), (), floor=None, now=100.0
            )

        try:
            with (
                mock.patch.object(live_estimate, "_flights", Flights()),
                mock.patch.object(project_context, "_live_check_scan", side_effect=slow),
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool,
            ):
                first = pool.submit(request)
                self.assertTrue(entered.wait(30))
                second = pool.submit(request)
                self.assertTrue(second_lookup.wait(30))
                release.set()
                self.assertEqual(first.result(timeout=30), second.result(timeout=30))
            self.assertEqual(1, calls)
        finally:
            release.set()

    def test_a_failed_leader_releases_a_waiter_to_retry(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.save_all()
        live_estimate._cache.clear()
        entered = threading.Event()
        second_lookup = threading.Event()
        release = threading.Event()
        calls = 0
        real = project_context._live_check_scan

        class Flights(dict[object, object]):
            lookups = 0

            def get(self, key: object, default: object = None) -> object:
                self.lookups += 1
                if self.lookups == 2:
                    second_lookup.set()
                return super().get(key, default)

        def first_fails(*args: Any, **kwargs: Any) -> Any:
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                if not release.wait(30):
                    raise AssertionError("the waiter did not reach the flight")
                raise OSError("transient scan failure")
            return real(*args, **kwargs)

        def request() -> dict[str, object]:
            return live_estimate.for_session(
                self.config, saved_row(), str(self.path), (), floor=None, now=100.0
            )

        try:
            with (
                mock.patch.object(live_estimate, "_flights", Flights()),
                mock.patch.object(project_context, "_live_check_scan", side_effect=first_fails),
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool,
            ):
                first = pool.submit(request)
                self.assertTrue(entered.wait(30))
                second = pool.submit(request)
                self.assertTrue(second_lookup.wait(30))
                release.set()
                with self.assertRaisesRegex(OSError, "transient scan failure"):
                    first.result(timeout=30)
                self.assertEqual(levels.NONE_OR_LOW, second.result(timeout=30)["level"])
            self.assertEqual(2, calls)
        finally:
            release.set()
