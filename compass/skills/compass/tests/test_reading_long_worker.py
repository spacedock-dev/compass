"""Actual native source, CI owner, registered Guard and staged evidence worker."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import unittest
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    git_status,
    observer,
    reading,
    reading_ci_acquire,
    reading_long_context,
    reading_long_control,
    reading_long_execution,
    reading_long_inspection,
    reading_long_jobs,
    reading_long_markers,
    reading_long_plan,
    reading_long_worker,
    reading_native,
    reading_policy,
    reading_preparation,
    reading_route,
    reading_source_collect,
    settings,
    supervise,
)

from . import test_reading_long_context as context_tests
from . import test_reading_source_final as source_tests
from .test_claude_checks import SHORT
from .test_reading_long_jobs import binding

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from types import TracebackType


class GuardedNativeWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = context_tests.ActiveContextTest()
        self.env.setUp()
        self.addCleanup(self.env.doCleanups)
        self.source = source_tests.RetainedStrictFinalTest()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.config = replace(self.env.config, claude_reading_model="claude-sonnet-5")
        self.goal = "Keep the retry safe. Review https://github.com/acme/widgets/pull/12"
        self.calls: list[str] = []
        self.ci_calls: list[tuple[str, ...]] = []
        self.after_call: Callable[[], None] = lambda: None
        self.bad_reply_at = 0
        self.progress: list[dict[str, Any]] = []
        patcher = mock.patch.object(
            observer, "reading_workdir_root", return_value=str(self.config.state_dir)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(git_status, "_executable", return_value="/owned/git")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(
            git_status, "executable", side_effect=lambda name, _env: f"/owned/{name}"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_case(
        self, *, large: bool = False, model: str = "claude-sonnet-5", ci_state: str = "ready"
    ) -> None:
        self.config = replace(self.config, claude_reading_model=model)
        self.source.parent.prompt("Do not push to main.")
        for index in range(28 if large else 1):
            self.source.say(
                f"Original ordinary {index}. " + "x" * (114000 if large else 80), "tool_use"
            )
            if index == (14 if large else 0):
                self.source.parent.bash("pytest tests/retry.py", "Exit code 1\n1 failed")
        self.source.say("The retry check still fails.")
        self.inventory = self.source.freeze()

        def probe(command: tuple[str, ...], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            output = b"a" * 40 if command[-1] == "HEAD" else b"https://github.com/acme/widgets"
            return subprocess.CompletedProcess(command, 0, stdout=output)

        self.collection = reading_source_collect.collect(
            self.config,
            self.inventory,
            current_ci_goals=(self.goal,),
            ci_probe_runner=probe,
        )
        self.assertEqual("", self.collection.reason)
        assert self.collection.evidence is not None
        assert self.collection.current_ci is not None
        self.assertEqual(ci_state, self.collection.current_ci.state)
        facts = self.collection.evidence.facts
        self.now = max(f["at"] for f in facts) + 120
        self.row: dict[str, Any] = {
            "harness": "claude",
            "sid": SHORT,
            "state": "idle",
            "ended_at": max(f["at"] for f in facts) + 10,
            "annotation_assessment": {"detail": "STORED_READING_CANARY"},
        }
        annotation_store.annotate(
            self.config,
            self.env.state,
            "claude",
            SHORT,
            goal=self.goal,
            output="The tests pass",
            now=100,
        )
        entry = annotation_store.find(annotation_store.load(self.config), "claude", SHORT)
        assert entry is not None
        self.revisions = entry["revisions"]
        target = annotation_store.capture_long_target(self.config, self.env.state, "claude", SHORT)
        assert target is not None
        resolved = reading_route.resolve("claude", config=self.config)
        plan = reading_long_plan.build(resolved, settings.load(self.config))
        assert plan is not None
        self.plan = plan
        route = reading_long_context.describe(self.config, "claude")
        assert route is not None
        self.assertEqual("on", route.ci_read)
        association = {
            "harness": "claude",
            "sid": SHORT,
            "incarnation": target.incarnation,
            "revision": target.revision,
        }
        declared = binding(
            started_at=self.now,
            plan=plan,
            publication=association,
            target_sha256=reading_long_jobs.publication_digest(association),
            scope_sha256=reading_long_context.scope_digest(route, self.env.scope),
            destination_sha256=reading_long_context.destination_digest(route),
        )
        prepared = reading_policy.prepare_long_job(
            permission=self.env.permission,
            binding=declared,
            call_timeout_ms=route.call_timeout_ms,
            clock=lambda: self.env.clock[0],
        )
        assert prepared is not None
        active = reading_long_control.admit(
            self.config,
            f"claude:{SHORT}",
            provider=route.provider,
            label="Claude Code",
            job=prepared,
            permission=self.env.permission,
            now=self.now,
        )
        assert active is not None
        self.active = active
        self.context = reading_long_context.Context(active, route, self.env.scope)
        self.addCleanup(reading.end_job, self.config, f"claude:{SHORT}")

    def ci_runner(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        self.ci_calls.append(tuple(command))
        self.assertIn("output_limits", kwargs)
        value: Any = (
            {"headRefOid": "a" * 40, "number": 12, "state": "OPEN", "mergeCommit": None}
            if "view" in command
            else [
                {
                    "name": "retry-ci",
                    "state": "FAILURE",
                    "bucket": "fail",
                    "completedAt": "2026-10-27T10:00:00Z",
                }
            ]
        )
        kwargs["stdout"].write(json.dumps(value).encode())
        return subprocess.CompletedProcess(command, 0)

    def cli_runner(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        prompt = kwargs["input"]
        self.assertIsInstance(prompt, str)
        assert self.collection.snapshot is not None
        self.assertFalse(self.collection.snapshot.account.lock.locked())
        self.calls.append(prompt)
        progress = reading.published_jobs(self.config)[f"claude:{SHORT}"]["progress"]
        self.progress.append(dict(progress))
        self.assertIsNotNone(progress["evidence"]["planned"])
        self.assertNotIn("STORED_READING_CANARY", prompt)
        group = mock.Mock()
        kwargs["on_spawn"](group)
        found = re.search(r"^\[(\d+)\] tool_report.*pytest tests/retry.py", prompt, re.MULTILINE)
        candidates = (
            []
            if found is None
            else [
                {
                    "clause": "line_1",
                    "kind": "departs",
                    "cites": [int(found[1])],
                    "detail": "The original retry check failed.",
                }
            ]
        )
        reply = {"version": 1, "candidates": candidates}
        if len(self.calls) == self.bad_reply_at:
            reply = {"version": 1, "foreign_fact_id": "injected", "candidates": []}
        kwargs["stdout"].write(json.dumps(reply).encode())
        self.after_call()
        return subprocess.CompletedProcess(command, 0)

    def run_worker(self) -> reading_long_worker.Mapped:
        return reading_long_worker.run_maps(
            self.config,
            self.context,
            self.inventory,
            self.collection,
            row=self.row,
            revisions=self.revisions,
            clock=lambda: self.now,
            runner=self.cli_runner,
            ci_runner=self.ci_runner,
            binary_resolver=lambda name: f"/owned/{name}",
            environ={},
        )

    def test_real_three_megabyte_route_plan_ci_join_and_guarded_maps(self) -> None:
        self.make_case(large=True)
        self.assertGreater(self.source.path.stat().st_size, 3 * 1024 * 1024)
        self.assertEqual(512 * 1024, self.plan["limits"]["prompt_bytes"])
        result = self.run_worker()
        self.assertEqual("mapped", result.state)
        assert result.series is not None and result.prepared is not None and result.ci is not None
        self.assertGreater(len(result.series.passes), 1)
        self.assertEqual(len(result.series.plan.packets), len(self.calls))
        self.assertEqual([4], [item.ordinal for item in result.series.index.entries])
        cited = result.series.index.entries[0].candidate.cites[0].span.fact_id
        self.assertTrue(
            any(
                row["id"] == cited and "pytest tests/retry.py" in row["summary"]
                for row in result.prepared.floor.entries
            )
        )
        self.assertEqual(4, len(self.ci_calls))
        self.assertEqual("complete", result.ci.state)
        self.assertEqual("ci:12:0", result.prepared.originals[-1].row["id"])
        self.assertTrue(result.prepared.originals[-1].row["ci_counts"])
        self.assertTrue(
            any(
                row["id"] == "ci:12:0"
                for packet in result.series.plan.packets
                for row in packet.selection.entries
            )
        )
        self.assertEqual("waiting", self.active.job.phase)
        self.assertFalse(self.active.job.sealed)
        marker = reading_long_markers.load(self.config, self.active.job.id)
        assert marker is not None
        self.assertEqual("active", marker["state"])
        self.assertTrue(all(slot["state"] == "settled" for slot in marker["passes"]))
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=self.now)
        assert inspected.exact is not None
        self.assertEqual(len(self.calls), inspected.exact.calls)
        self.assertEqual(self.plan["max_calls"], result.progress["reconciliation"]["ordinal"])
        self.assertEqual("not-started", result.progress["reconciliation"]["state"])
        self.assertEqual(len(self.calls), result.progress["evidence"]["ended"])
        self.assertTrue(result.source_current())
        self.assertGreater(result.usage.prepare_ms, self.collection.usage.prepare_ms)

    def test_sent_maps_repeat_original_context_across_correction_boundaries(self) -> None:
        say = self.source.say
        correction = "Correction: the retry test still fails despite the earlier success claim."

        def with_correction(words: str, *args: Any, **kwargs: Any) -> Any:
            if words.startswith("Original ordinary 4. "):
                words = words[:64710] + correction + words[64710 + len(correction) :]
            return say(words, *args, **kwargs)

        with mock.patch.object(self.source, "say", side_effect=with_correction):
            self.make_case(large=True)
        result = self.run_worker()
        self.assertEqual("mapped", result.state)
        assert result.series is not None and result.prepared is not None
        packets = result.series.plan.packets
        originals = {item.row["id"]: item for item in result.prepared.originals}
        self.assertEqual(7, len(self.calls))
        self.assertTrue(any(correction in prompt for prompt in self.calls))
        for index, packet in enumerate(packets):
            self.assertEqual(packet.prompt, self.calls[index])
            self.assertLessEqual(len(packet.prompt.encode("utf-8")), 512 * 1024)
            first, last = packet.primary[0], packet.primary[-1]
            if first.start:
                self.assertTrue(
                    any(
                        span.fact_id == first.fact_id
                        and span.start is not None
                        and span.start < first.start
                        and span.end == first.start
                        for span in packet.context
                    ),
                    "a continuation must carry the original words before its cut",
                )
            if last.end is not None:
                assert last.total is not None
                if last.end < last.total:
                    self.assertTrue(
                        any(
                            span.fact_id == last.fact_id
                            and span.start == last.end
                            and span.end is not None
                            and span.end > last.end
                            for span in packet.context
                        ),
                        "a split must carry the original words after its cut",
                    )
            for span in packet.context:
                original = originals[span.fact_id]
                if span.start is not None:
                    assert original.words is not None
                    self.assertIn(
                        json.dumps(original.words[span.start : span.end], ensure_ascii=False)[1:-1],
                        packet.prompt,
                    )
        self.assertEqual((), result.series.plan.uncovered_primary)

    def test_three_fragment_unicode_message_maps_with_both_context_edges(self) -> None:
        say = self.source.say

        def unicode_message(words: str, *args: Any, **kwargs: Any) -> Any:
            return say(
                "🙂" * 260000 if words.startswith("Original ordinary 0.") else words,
                *args,
                **kwargs,
            )

        def save_utf8(path: Path) -> None:
            path.write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False) + "\n" for row in self.source.parent.rows
                ),
                encoding="utf-8",
            )

        with (
            mock.patch.object(self.source, "say", side_effect=unicode_message),
            mock.patch.object(self.source.parent, "save", side_effect=save_utf8),
        ):
            self.make_case()
        self.assertLess(max(map(len, self.source.path.read_bytes().splitlines())), 1024 * 1024)
        real_popen = subprocess.Popen
        children: list[subprocess.Popen[Any]] = []
        calls: list[object] = []

        def popen(command: Any, **options: Any) -> Any:
            if command[0] == "/owned/claude":
                calls.append(command)
                command = [
                    sys.executable,
                    "-c",
                    'import sys; sys.stdin.read(); print(\'{"version":1,"candidates":[]}\')',
                ]
            child = real_popen(command, **options)
            children.append(child)
            return child

        try:
            with mock.patch.object(subprocess, "Popen", side_effect=popen):
                result = reading_long_worker.run_maps(
                    self.config,
                    self.context,
                    self.inventory,
                    self.collection,
                    row=self.row,
                    revisions=self.revisions,
                    clock=lambda: self.now,
                    runner=supervise.run,
                    ci_runner=self.ci_runner,
                    binary_resolver=lambda name: f"/owned/{name}",
                    environ={},
                )
            assert result.series is not None and result.prepared is not None
            inspected = reading_long_inspection.inspect(
                self.config, self.active.job.id, now=self.now
            )
            assert inspected.exact is not None
            self.assertEqual(3, len(calls))
            self.assertEqual(3, inspected.exact.calls)
            group = self.active.job.group
            assert group is not None
            self.assertTrue(group.cleanup_complete())
            self.assertIsNotNone(group._limit)
            self.assertEqual(1, len(group._limits))
            self.assertTrue(all(child.poll() is not None for child in children))
            self.assertEqual(["ok", "ok", "ok"], [passed.reason for passed in result.series.passes])
            self.assertEqual("mapped", result.state)
            self.assertEqual((), result.series.failed_primary)
            self.assertEqual((), result.series.plan.uncovered_primary)
            packets = result.series.plan.packets
            middle = packets[1]
            self.assertEqual(1, len(middle.primary))
            self.assertEqual(2, len(middle.context))
            self.assertEqual({middle.primary[0].fact_id}, {span.fact_id for span in middle.context})
            ranges = [
                span
                for packet in packets
                for span in packet.primary
                if span.fact_id == middle.primary[0].fact_id
            ]
            self.assertEqual(
                [(0, ranges[0].end), (ranges[0].end, ranges[1].end), (ranges[1].end, 260000)],
                [(span.start, span.end) for span in ranges],
            )
            self.assertTrue(all(len(packet.prompt.encode("utf-8")) <= 524288 for packet in packets))
            self.assertLessEqual(
                result.series.plan.transmitted_bytes, self.plan["limits"]["input_bytes"]
            )
            assert result.prepared.final is not None
            self.assertEqual("whole", result.prepared.final["outcome"])
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.wait()

    def test_unknown_small_route_known_uncovered_plan_costs_zero(self) -> None:
        self.env.controls = replace(self.env.controls, window_limits=(180000,))
        self.make_case(large=True, model="claude-sonnet-6")
        result = self.run_worker()
        self.assertEqual("withheld", result.state)
        assert result.series is not None
        self.assertTrue(result.series.plan.uncovered_primary)
        self.assertEqual(result.series.plan.reason, result.reason)
        self.assertEqual([], self.calls)
        self.assertEqual(len(result.series.plan.packets), result.progress["evidence"]["planned"])
        self.assertEqual(0, result.progress["evidence"]["ended"])
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=self.now)
        assert inspected.exact is not None
        self.assertEqual(0, inspected.exact.calls)

    def test_parent_version_move_after_first_map_invalidates_strict_final(self) -> None:
        self.make_case(large=True)

        def change() -> None:
            self.source.say("A later correction changes the final source.")
            self.source.parent.save(self.source.path)

        self.after_call = change
        result = self.run_worker()
        self.assertEqual("withheld", result.state)
        self.assertEqual("source-final-changed", result.reason)
        self.assertEqual(1, len(self.calls))
        assert result.series is not None
        self.assertTrue(result.series.unassigned_primary)
        self.assertFalse(result.source_current())

    def test_failed_settlement_keeps_real_charge_and_stops_later_maps(self) -> None:
        self.make_case(large=True)
        with mock.patch.object(reading_long_markers, "settle", return_value=False):
            result = self.run_worker()
        self.assertEqual("withheld", result.state)
        self.assertEqual("persistence-unresolved", result.reason)
        self.assertEqual(1, len(self.calls))
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=self.now)
        assert inspected.exact is not None
        self.assertEqual(1, inspected.exact.calls)
        self.assertTrue(inspected.unsettled)

    def test_post_charge_observation_failure_keeps_charge_without_transport_or_settlement(
        self,
    ) -> None:
        self.make_case()
        with mock.patch.object(reading_long_markers, "observe", return_value=False):
            result = self.run_worker()
        self.assertEqual("persistence-unresolved", result.reason)
        self.assertEqual([], self.calls)
        assert result.series is not None
        self.assertEqual(1, len(result.series.passes))
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=self.now)
        assert inspected.exact is not None
        self.assertEqual(1, inspected.exact.calls)
        self.assertTrue(inspected.unsettled)

    def test_known_missing_current_ci_proof_refuses_before_any_transport(self) -> None:
        self.make_case()
        self.collection = replace(self.collection, current_ci=None)
        result = self.run_worker()
        self.assertEqual("ci-context-unavailable", result.reason)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.ci_calls)

    def test_pause_after_reservation_retains_charge_and_no_adapter(self) -> None:
        self.make_case()
        observe = reading_long_markers.observe

        def pause(*args: Any, **kwargs: Any) -> bool:
            accepted = observe(*args, **kwargs)
            reading_policy.set_consent(self.config, False, now=self.now)
            return accepted

        with mock.patch.object(reading_long_markers, "observe", side_effect=pause):
            result = self.run_worker()
        self.assertEqual("withheld", result.state)
        self.assertEqual([], self.calls)
        assert result.series is not None
        self.assertTrue(result.series.failed_primary)
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=self.now)
        assert inspected.exact is not None
        self.assertEqual(1, inspected.exact.calls)

    def test_exhausted_shared_preparation_before_start_returns_refusal(self) -> None:
        self.make_case()
        assert self.collection.snapshot is not None
        account = self.collection.snapshot.account
        account.usage = replace(account.usage, prepare_ms=account.limits.prepare_ms)
        result = self.run_worker()
        self.assertEqual("prepare-time", result.reason)
        self.assertEqual(account.usage, result.usage)
        self.assertEqual([], self.calls)

    def test_post_call_budget_exhaustion_preserves_actual_pass_and_charge(self) -> None:
        self.make_case()
        original_stage = reading_preparation.Budget.stage

        def exhausted_stage(budget: reading_preparation.Budget) -> Any:
            if self.calls:
                budget.account.usage = replace(
                    budget.account.usage, prepare_ms=budget.account.limits.prepare_ms
                )
            return original_stage(budget)

        with mock.patch.object(reading_preparation.Budget, "stage", exhausted_stage):
            result = self.run_worker()
        self.assertEqual("prepare-time", result.reason)
        assert result.series is not None
        self.assertEqual(1, len(result.series.passes))
        self.assertTrue(result.series.passes[0].snapshots[-1]["input"]["attempt_reserved"])
        self.assertEqual(1, len(self.calls))

    def test_corrupt_middle_reply_retains_later_original_hypothesis_but_withholds(self) -> None:
        self.make_case(large=True)
        self.bad_reply_at = 2
        result = self.run_worker()
        self.assertEqual("unresolved", result.reason)
        assert result.series is not None
        self.assertEqual(len(result.series.plan.packets), len(self.calls))
        self.assertEqual((2,), result.series.index.unresolved_ordinals)
        self.assertEqual([4], [item.ordinal for item in result.series.index.entries])

    def test_ci_result_detached_from_collection_inputs_cannot_reach_maps(self) -> None:
        self.make_case()
        acquire = reading_ci_acquire.acquire

        def detached(*args: Any, **kwargs: Any) -> reading_ci_acquire.Result:
            result = acquire(*args, **kwargs)
            assert result.inputs is not None
            return replace(result, inputs=replace(result.inputs))

        with mock.patch.object(reading_ci_acquire, "acquire", side_effect=detached):
            result = self.run_worker()
        self.assertEqual("ci-context-unavailable", result.reason)
        self.assertEqual([], self.calls)

    def test_cancel_between_maps_keeps_first_charge_and_never_invoked_ranges(self) -> None:
        self.make_case(large=True)

        def cancel() -> None:
            reading.cancel_job(self.config, f"claude:{SHORT}", self.active.job.id, now=self.now)

        self.after_call = cancel
        result = self.run_worker()
        self.assertEqual("cancelled", result.reason)
        self.assertEqual(1, len(self.calls))
        assert result.series is not None
        self.assertTrue(result.series.unassigned_primary)

    def test_whole_job_deadline_between_maps_keeps_first_charge(self) -> None:
        self.make_case(large=True)

        def expire() -> None:
            self.env.clock[0] = self.plan["limits"]["job_ms"] / 1000

        self.after_call = expire
        result = self.run_worker()
        self.assertEqual("job-deadline", result.reason)
        self.assertEqual(1, len(self.calls))
        assert result.series is not None
        self.assertTrue(result.series.unassigned_primary)

    def test_deadline_exhausted_waiting_for_spawn_keeps_charge_without_launch(self) -> None:
        self.goal = "Keep the retry safe."
        self.make_case(ci_state="unbound")
        self.env.clock[0] = 1619
        reserved, proceed, entering = threading.Event(), threading.Event(), threading.Event()
        real_lock, real_popen = supervise._LOCK, subprocess.Popen
        launched: list[float] = []
        outcomes: list[Any] = []

        def on_reserved() -> None:
            reserved.set()
            self.assertTrue(proceed.wait(5))

        class ObservedLock:
            def __enter__(self) -> bool:
                if (
                    threading.current_thread() is thread
                    and sys._getframe(1).f_code is supervise.run.__code__
                ):
                    entering.set()
                return real_lock.__enter__()

            def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc_value: BaseException | None,
                traceback: TracebackType | None,
            ) -> None:
                real_lock.__exit__(exc_type, exc_value, traceback)

        def popen(command: Any, **options: Any) -> Any:
            if command[0] == "/owned/claude":
                launched.append(self.env.clock[0])
                command = [sys.executable, "-c", "import sys; sys.stdin.read(); print('received')"]
            return real_popen(command, **options)

        source = reading_long_worker._Source(self.config, self.context, self.collection)
        model = reading_long_execution.guard(
            self.config,
            self.context,
            1,
            clock=lambda: self.now,
            runner=supervise.run,
            binary_resolver=lambda name: f"/owned/{name}",
            on_reserved=on_reserved,
            source_current=lambda: not source.current(),
        )

        def invoke() -> None:
            try:
                outcomes.append(model("Owned synthetic prompt", output_cap_bytes=8192))
            except reading_policy.RefusedError as error:
                outcomes.append(error)

        thread = threading.Thread(target=invoke)
        with (
            mock.patch.object(subprocess, "Popen", side_effect=popen),
            mock.patch.object(supervise, "_LOCK", ObservedLock()),
        ):
            thread.start()
            try:
                self.assertTrue(reserved.wait(5))
                with real_lock:
                    proceed.set()
                    self.assertTrue(entering.wait(5))
                    self.env.clock[0] = 1621
            finally:
                proceed.set()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], launched, "expired full-call budget must prevent the actual spawn")
        self.assertEqual(1, len(outcomes))
        self.assertIsInstance(outcomes[0], reading_policy.RefusedError)
        measured = reading_long_inspection.inspect(self.config, self.active.job.id, now=self.now)
        assert measured.exact is not None
        self.assertEqual(1, measured.exact.calls)
        self.assertIsNone(self.active.job.group)

    def test_model_wait_is_excluded_from_shared_preparation_clock(self) -> None:
        self.make_case(large=True)
        budget_type = reading_preparation.Budget
        clock = [0.0]

        def budget(
            snapshot: reading_source_collect.Snapshot, plan: dict[str, Any]
        ) -> reading_preparation.Budget:
            return budget_type(snapshot, plan, clock=lambda: clock[0])

        def wait() -> None:
            clock[0] += 1000

        self.after_call = wait
        with mock.patch.object(reading_preparation, "Budget", side_effect=budget):
            result = self.run_worker()
        self.assertEqual("mapped", result.state)
        self.assertGreater(clock[0], 1000)
        self.assertLess(result.usage.prepare_ms - self.collection.usage.prepare_ms, 1000)

    def test_uncharged_invocation_refusal_ends_pass_without_inventing_charge(self) -> None:
        self.make_case()
        with mock.patch.object(reading_policy, "DAILY_CAP", 0):
            result = self.run_worker()
        self.assertEqual("withheld", result.state)
        self.assertEqual([], self.calls)
        assert result.series is not None
        self.assertEqual(1, len(result.series.passes))
        self.assertEqual(1, result.progress["evidence"]["ended"])
        self.assertIsNone(result.progress["evidence"]["current"])
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=self.now)
        assert inspected.exact is not None
        self.assertEqual(0, inspected.exact.calls)

    def test_known_mandatory_person_floor_unfit_refuses_before_maps(self) -> None:
        self.env.controls = replace(self.env.controls, window_limits=(168000,))
        self.source.parent.prompt("Mandatory original direction. " + "p" * 80000)
        self.make_case()
        result = self.run_worker()
        self.assertEqual("prompt-unfit", result.reason)
        self.assertIsNone(result.series)
        self.assertEqual([], self.calls)

    def test_ci_on_without_any_pr_binding_maps_without_claiming_a_ci_read(self) -> None:
        self.goal = "Keep the retry safe."
        self.make_case(ci_state="unbound")
        assert self.collection.current_ci is not None
        self.assertIsNone(self.collection.current_ci.binding)
        result = self.run_worker()
        self.assertEqual("mapped", result.state)
        self.assertTrue(self.calls)
        self.assertEqual([], self.ci_calls)
        assert result.ci is not None and result.prepared is not None
        self.assertEqual("unavailable", result.ci.state)
        self.assertEqual("input-unavailable", result.ci.reason)
        self.assertIsNone(result.ci.value())
        self.assertEqual("on", result.prepared.ci_read)
        self.assertTrue(result.prepared.ci_unbound)
        self.assertIsNone(result.prepared.ci_record)
        self.assertEqual([], result.prepared.context.value()["safety"]["gaps"])
        self.assertFalse(
            any(row["type"] == reading.CI_CHECK_TYPE for row in result.prepared.floor.entries)
        )

    def test_missing_ci_context_is_not_the_same_as_a_proved_absent_binding(self) -> None:
        self.goal = "Keep the retry safe."
        self.make_case(ci_state="unbound")
        inputs = self.collection.current_ci
        assert inputs is not None
        for unavailable in (
            replace(inputs, state="unknown"),
            replace(inputs, state="no-folder"),
            replace(inputs, state="no-commit"),
            replace(inputs, state="disabled"),
        ):
            with self.subTest(state=unavailable.state):
                self.collection = replace(self.collection, current_ci=unavailable)
                result = self.run_worker()
                self.assertEqual("withheld", result.state)
                self.assertEqual("input-unavailable", result.reason)
                self.assertEqual([], self.calls)
                self.assertEqual([], self.ci_calls)

    def test_ci_read_error_with_a_real_binding_still_refuses_all_maps(self) -> None:
        self.make_case()
        with mock.patch.object(self, "ci_runner", return_value=subprocess.CompletedProcess([], 1)):
            result = self.run_worker()
        self.assertEqual("withheld", result.state)
        self.assertEqual("ci-read", result.reason)
        self.assertEqual([], self.calls)

    def _tool_destination(self, destination: str) -> None:
        resolve = reading_route.resolve
        prepare = reading_native.prepare
        prepared: list[reading_native.Preparation] = []

        def capture(*args: Any, **kwargs: Any) -> reading_native.Preparation:
            value = prepare(*args, **kwargs)
            prepared.append(value)
            return value

        def route(*args: Any, **kwargs: Any) -> reading_route.Route:
            result = resolve(*args, **kwargs)
            result["destination"] = destination
            return result

        with (
            mock.patch.object(reading_route, "resolve", side_effect=route),
            mock.patch.object(reading_native, "prepare", side_effect=capture),
        ):
            self.make_case()
            result = self.run_worker()
        self.assertEqual("mapped" if destination else "withheld", result.state)
        actual = prepared[0].prepared
        assert actual is not None and actual.inputs.tool_output is not None
        self.assertEqual("Anthropic", self.context.route.destination)
        self.assertEqual(destination, self.context.route.tool_destination)
        self.assertEqual(destination, actual.inputs.tool_output.destination)
        if not destination:
            self.assertEqual({}, actual.inputs.tool_output.tails)
            self.assertEqual("scope-checks-unread", result.reason)
            self.assertEqual([], self.calls)

    def test_tool_output_uses_its_distinct_frozen_destination(self) -> None:
        self._tool_destination("Tool proxy")

    def test_empty_tool_destination_does_not_send_tails_via_words_destination(self) -> None:
        self._tool_destination("")

    def test_revalidation_poll_detects_pause_and_preserves_its_real_cause(self) -> None:
        self.make_case()
        revalidate = reading_source_collect.revalidate

        def pause(
            snapshot: reading_source_collect.Snapshot, **kwargs: Any
        ) -> reading_source_collect.Revalidation:
            reading_policy.set_consent(self.config, False, now=self.now)
            self.env.clock[0] += 0.3
            self.assertTrue(kwargs["cancelled"]())
            return revalidate(snapshot, **kwargs)

        with mock.patch.object(reading_source_collect, "revalidate", side_effect=pause):
            result = self.run_worker()
        self.assertEqual("permission-changed", result.reason)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.ci_calls)
        self.assertFalse(reading.job_cancelled(self.active.job))
