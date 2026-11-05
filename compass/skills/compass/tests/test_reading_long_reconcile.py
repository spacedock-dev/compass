"""Real guarded map-to-final pipeline with native source and fake CLI transports."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unittest
from dataclasses import replace
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import (
    reading,
    reading_final_call,
    reading_long_execution,
    reading_long_inspection,
    reading_long_markers,
    reading_long_reconcile,
    reading_policy,
    reading_preparation,
)

from . import test_reading_long_worker as worker_tests

if TYPE_CHECKING:
    from collections.abc import Callable


class GuardedFinalWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.f = worker_tests.GuardedNativeWorkerTest()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.prompts: list[str] = []
        self.after_reply: Callable[[], None] = lambda: None
        self.bad_reply = False

    def maps(self, *, large: bool = False, no_pr: bool = False, bad_middle: bool = False) -> None:
        if no_pr:
            self.f.goal = "Keep the retry safe."
        self.f.make_case(large=large, ci_state="unbound" if no_pr else "ready")
        self.f.bad_reply_at = 2 if bad_middle else 0
        self.mapped = self.f.run_worker()

    def runner(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        prompt = str(kwargs["input"])
        self.prompts.append(prompt)
        assert self.mapped.snapshot is not None
        self.assertFalse(self.mapped.snapshot.account.lock.locked())
        progress = reading.published_jobs(self.f.config)[f"claude:{self.f.row['sid']}"]["progress"]
        self.assertEqual("reconciliation", progress["stage"])
        self.assertEqual({"ordinal": 17, "state": "running"}, progress["reconciliation"])
        self.assertEqual("waiting", self.f.active.job.phase)
        self.assertNotIn("STORED_READING_CANARY", prompt)
        kwargs["on_spawn"](mock.Mock())
        match = re.search(r"^\[(\d+)\] tool_report.*pytest tests/retry.py", prompt, re.MULTILINE)
        self.assertIsNotNone(match)
        assert match is not None
        reply = json.dumps(
            {
                "goal": {"result": "consistent", "cites": [int(match[1])], "detail": ""},
                "line_1": {
                    "result": "departure",
                    "cites": [int(match[1])],
                    "detail": "The retry check failed.",
                },
            }
        )
        kwargs["stdout"].write(("not valid JSON" if self.bad_reply else reply).encode())
        self.after_reply()
        return subprocess.CompletedProcess(command, 0)

    def finish(self) -> reading_long_reconcile.Finished:
        return reading_long_reconcile.finish(
            self.f.config,
            self.f.context,
            self.f.inventory,
            self.f.collection,
            self.mapped,
            clock=lambda: self.f.now,
            stamp_text="Controlled model",
            runner=self.runner,
            binary_resolver=lambda name: f"/owned/{name}",
        )

    def test_real_seven_maps_then_reserved_final_produces_original_supported_partial(self) -> None:
        self.maps(large=True)
        self.assertEqual(7, len(self.f.calls))
        result = self.finish()
        self.assertEqual("partial", result.state)
        self.assertEqual("final-context-limited", result.diagnostic["stop_reason"])
        assert result.assessment is not None and result.result is not None
        assert result.result.packet is not None and self.mapped.series is not None
        criterion = result.assessment["criteria"]["line_1"]
        self.assertEqual(reading.RESULT_DEPARTURE, criterion["result"])
        self.assertEqual(
            (self.mapped.series.index.entries[0].candidate.cites[0].span.fact_id,),
            criterion["cites"],
        )
        self.assertEqual(
            reading.RESULT_UNVERIFIABLE, result.assessment["criteria"]["goal"]["result"]
        )
        self.assertIn("ci", result.assessment)
        self.assertNotIn("CI was not read", result.assessment["cutoff"])
        self.assertEqual("checking", self.f.active.job.phase)
        self.assertEqual(hashlib.sha256(self.prompts[0].encode()).hexdigest(), result.prompt_sha256)
        self.assertEqual(len(self.prompts[0].encode()), result.prompt_bytes)
        self.assertEqual(8, result.diagnostic["accounting"]["totals"]["calls"])
        self.assertEqual(7, len(result.diagnostic["observations"]) - 1)
        self.assertEqual(
            "reconciliation", result.diagnostic["observations"][-1]["observation"]["kind"]
        )
        self.assertEqual(
            self.mapped.series.plan.transmitted_bytes,
            result.diagnostic["maps"]["observed_prompt_bytes"],
        )
        marker = reading_long_markers.load(self.f.config, self.f.active.job.id)
        assert marker is not None
        self.assertEqual(17, marker["passes"][-1]["request"]["ordinal"])
        self.assertEqual("settled", marker["passes"][-1]["state"])
        self.assertEqual("active", marker["state"])
        self.assertFalse(self.f.active.job.sealed)
        self.assertTrue(result.source_current())
        self.assertGreater(result.usage.prepare_ms, self.mapped.usage.prepare_ms)

    def test_ci_on_no_pr_still_produces_qualified_assessment_without_ci_claim(self) -> None:
        self.maps(no_pr=True)
        result = self.finish()
        assert result.assessment is not None
        self.assertEqual("partial", result.state)
        self.assertEqual("final-context-limited", result.diagnostic["stop_reason"])
        self.assertNotIn("ci", result.assessment)
        self.assertIn("no applicable pull-request binding", result.assessment["cutoff"])
        self.assertEqual([], self.f.ci_calls)

    def test_failed_middle_map_never_gets_a_final_call_or_assessment(self) -> None:
        self.maps(large=True, bad_middle=True)
        result = self.finish()
        self.assertEqual("withheld", result.state)
        self.assertIsNone(result.assessment)
        self.assertEqual([], self.prompts)
        self.assertEqual(7, result.diagnostic["accounting"]["totals"]["calls"])

    def test_changed_parent_after_maps_refuses_final_without_another_charge(self) -> None:
        self.maps()
        self.f.source.say("A later retraction.")
        self.f.source.parent.save(self.f.source.path)
        result = self.finish()
        self.assertEqual("source-final-changed", result.reason)
        self.assertEqual("source-changed", result.diagnostic["stop_reason"])
        self.assertEqual([], self.prompts)
        self.assertIsNone(result.assessment)

    def test_final_reply_parse_failure_keeps_real_prompt_and_charge(self) -> None:
        self.maps()
        self.bad_reply = True
        result = self.finish()
        self.assertEqual("invalid-reply", result.reason)
        self.assertIsNone(result.assessment)
        self.assertIsNotNone(result.prompt_sha256)
        self.assertEqual(2, result.diagnostic["accounting"]["totals"]["calls"])

    def test_post_charge_final_marker_failure_keeps_charge_without_transport(self) -> None:
        self.maps()
        with mock.patch.object(reading_long_markers, "observe", return_value=False):
            result = self.finish()
        self.assertIsNone(result.assessment)
        self.assertEqual([], self.prompts)
        self.assertEqual("persistence-unresolved", result.reason)
        inspected = reading_long_inspection.inspect(
            self.f.config, self.f.active.job.id, now=self.f.now
        )
        assert inspected.exact is not None
        self.assertEqual(2, inspected.exact.calls)
        self.assertTrue(inspected.unsettled)

    def test_pause_before_final_does_not_create_another_charge(self) -> None:
        self.maps()
        reading_policy.set_consent(self.f.config, False, now=self.f.now)
        result = self.finish()
        self.assertIsNone(result.assessment)
        self.assertEqual([], self.prompts)
        self.assertEqual(1, result.diagnostic["accounting"]["totals"]["calls"])

    def test_changed_source_during_final_withholds_successful_transport(self) -> None:
        self.maps()

        def change() -> None:
            self.f.source.say("The agent retracts this result.")
            self.f.source.parent.save(self.f.source.path)

        self.after_reply = change
        result = self.finish()
        self.assertEqual("source-final-changed", result.reason)
        self.assertIsNone(result.assessment)
        self.assertEqual(1, len(self.prompts))

    def test_final_preparation_limit_keeps_prompt_and_maps_without_final_charge(self) -> None:
        self.maps()
        original = reading_preparation._Stage._retain

        def exhaust(stage: reading_preparation._Stage) -> None:
            original(stage)
            if any(isinstance(root, reading_final_call.Preparation) for root in stage.budget.roots):
                account = stage.budget.account
                account.usage = replace(account.usage, prepare_ms=account.limits.prepare_ms)

        with mock.patch.object(reading_preparation._Stage, "_retain", exhaust):
            result = self.finish()
        self.assertEqual("prepare-time", result.reason)
        self.assertEqual("resource-limit", result.diagnostic["stop_reason"])
        self.assertTrue(result.diagnostic["source"]["source_verified"])
        self.assertEqual("passes-ended", result.diagnostic["maps"]["reason"])
        self.assertIsNone(result.assessment)
        self.assertEqual([], self.prompts)
        self.assertIsNotNone(result.result)
        self.assertIsNotNone(result.prompt_sha256)
        self.assertEqual(1, result.diagnostic["accounting"]["totals"]["calls"])
        self.assertFalse(result.snapshot.account.lock.locked())

    def test_final_response_budget_failure_keeps_receipt_packet_and_observation(self) -> None:
        self.maps()

        def exhaust() -> None:
            account = self.mapped.snapshot.account
            account.usage = replace(account.usage, prepare_ms=account.limits.prepare_ms)

        self.after_reply = exhaust
        result = self.finish()
        self.assertEqual("prepare-time", result.reason)
        self.assertIsNone(result.assessment)
        self.assertEqual(1, len(self.prompts))
        self.assertIsNotNone(result.result)
        self.assertIsNotNone(result.prompt_sha256)
        self.assertEqual(2, result.diagnostic["accounting"]["totals"]["calls"])
        self.assertFalse(result.snapshot.account.lock.locked())

    def test_cancel_during_final_keeps_charge_without_assessment(self) -> None:
        self.maps()

        def cancel() -> None:
            reading.cancel_job(
                self.f.config, f"claude:{self.f.row['sid']}", self.f.active.job.id, now=self.f.now
            )

        self.after_reply = cancel
        result = self.finish()
        self.assertEqual("cancelled", result.reason)
        self.assertEqual("cancelled", result.diagnostic["stop_reason"])
        self.assertIsNone(result.assessment)
        self.assertEqual(2, result.diagnostic["accounting"]["totals"]["calls"])

    def test_final_model_wait_is_excluded_from_shared_preparation(self) -> None:
        self.maps()
        assert self.mapped.budget is not None
        elapsed = [0.0]
        self.mapped.budget.clock = lambda: elapsed[0]

        def wait() -> None:
            elapsed[0] += 1000

        self.after_reply = wait
        result = self.finish()
        self.assertIsNotNone(result.assessment)
        self.assertLess(result.usage.prepare_ms - self.mapped.usage.prepare_ms, 1000)

    def test_final_reply_with_positive_remaining_job_time_does_not_need_another_timeout(
        self,
    ) -> None:
        self.maps()
        self.f.env.clock[0] = self.f.plan["limits"]["job_ms"] / 1000 - 190

        def reply() -> None:
            self.f.env.clock[0] += 150

        self.after_reply = reply
        result = self.finish()
        self.assertEqual("partial", result.state)
        self.assertIsNotNone(result.assessment)
        self.assertEqual("final-context-partial", result.reason)
        self.assertEqual(1, len(self.prompts))
        self.assertEqual("final-context-limited", result.diagnostic["stop_reason"])

    def test_final_reply_beyond_whole_job_deadline_is_still_withheld(self) -> None:
        self.maps()
        self.f.env.clock[0] = self.f.plan["limits"]["job_ms"] / 1000 - 190

        def reply() -> None:
            self.f.env.clock[0] += 191

        self.after_reply = reply
        result = self.finish()
        self.assertEqual("withheld", result.state)
        self.assertIsNone(result.assessment)
        self.assertEqual("job-deadline", result.reason)
        self.assertEqual("job-deadline", result.diagnostic["stop_reason"])
        self.assertEqual(1, len(self.prompts))

    def test_wrong_final_menu_reference_cannot_become_local_departure(self) -> None:
        self.maps(large=True)

        def foreign(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            self.prompts.append(str(kwargs["input"]))
            kwargs["stdout"].write(
                json.dumps(
                    {"line_1": {"result": "departure", "cites": [999], "detail": "unsupported"}}
                ).encode()
            )
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(self, "runner", side_effect=foreign):
            result = self.finish()
        assert result.assessment is not None
        criterion = result.assessment["criteria"]["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, criterion["result"])
        self.assertEqual((), criterion["cites"])

    def test_final_factory_exception_preserves_maps_and_prepared_packet(self) -> None:
        self.maps()
        with mock.patch.object(
            reading_long_execution, "guard", side_effect=OSError("private constructor")
        ):
            result = self.finish()
        self.assertEqual("factory-failed", result.reason)
        self.assertEqual("final-call-failed", result.diagnostic["stop_reason"])
        self.assertIsNone(result.assessment)
        self.assertIsNotNone(result.prompt_sha256)
        self.assertEqual([], self.prompts)
        self.assertEqual(1, result.diagnostic["accounting"]["totals"]["calls"])
        self.assertNotIn("private constructor", repr(result))

    def test_map_factory_exception_is_not_reported_as_a_final_failure(self) -> None:
        with mock.patch.object(
            reading_long_execution, "guard", side_effect=OSError("private map constructor")
        ):
            self.maps()
        self.assertEqual("factory-failed", self.mapped.reason)
        result = self.finish()
        self.assertEqual("factory-failed", result.reason)
        self.assertEqual("evidence-pass-failed", result.diagnostic["stop_reason"])
        self.assertIsNone(result.assessment)
        self.assertIsNone(result.result)
        self.assertIsNone(result.prompt_sha256)
        self.assertEqual([], self.prompts)
        self.assertEqual([], self.f.calls)
        self.assertNotIn("private map constructor", repr(result))

    def test_final_quota_refusal_has_no_extra_charge_or_retry(self) -> None:
        self.maps()
        with mock.patch.object(reading_policy, "DAILY_CAP", 1):
            result = self.finish()
        self.assertEqual("refused", result.reason)
        self.assertIsNone(result.assessment)
        self.assertEqual([], self.prompts)
        self.assertEqual(1, result.diagnostic["accounting"]["totals"]["calls"])
        self.assertIsNotNone(result.prompt_sha256)

    def test_final_settlement_failure_keeps_actual_reply_charge_unresolved(self) -> None:
        self.maps()
        with mock.patch.object(reading_long_markers, "settle", return_value=False):
            result = self.finish()
        self.assertEqual("persistence-unresolved", result.reason)
        self.assertIsNone(result.assessment)
        self.assertEqual(1, len(self.prompts))
        self.assertEqual(2, result.diagnostic["accounting"]["totals"]["calls"])
        self.assertFalse(result.diagnostic["observations"][-1]["ended"])

    def test_repaired_check_followed_by_write_cannot_retain_stale_departure(self) -> None:
        say = self.f.source.say

        def repaired(words: str, stop: str = "end_turn") -> None:
            if words == "The retry check still fails.":
                self.f.source.parent.bash("pytest tests/retry.py", "1 passed")
                self.f.source.parent.write(str(self.f.source.root / "retry.py"))
            say(words, stop)

        with mock.patch.object(self.f.source, "say", side_effect=repaired):
            self.maps(large=True)
        result = self.finish()
        assert result.assessment is not None
        criterion = result.assessment["criteria"]["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, criterion["result"])
        self.assertEqual((), criterion["cites"])

    def test_agent_hypothesis_requiring_unfit_counterproof_never_launches_final(self) -> None:
        self.f.make_case(large=True)

        def agent(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
            prompt = str(kwargs["input"])
            self.f.calls.append(prompt)
            match = re.search(r"^\[(\d+)\] agent_message", prompt, re.MULTILINE)
            candidates = (
                [
                    {
                        "clause": "line_1",
                        "kind": "departs",
                        "cites": [int(match[1])],
                        "detail": "Untrusted prose.",
                    }
                ]
                if match
                else []
            )
            kwargs["stdout"].write(json.dumps({"version": 1, "candidates": candidates}).encode())
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(self.f, "cli_runner", side_effect=agent):
            self.mapped = self.f.run_worker()
        self.assertEqual("mapped", self.mapped.state)
        result = self.finish()
        self.assertEqual("prompt-unfit", result.reason)
        self.assertIsNone(result.assessment)
        self.assertEqual([], self.prompts)
        self.assertIsNotNone(result.result)
        self.assertFalse(result.snapshot.account.lock.locked())
