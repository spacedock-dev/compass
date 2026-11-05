"""Latest long metrics and durable acknowledgments share the annotation transaction."""

from __future__ import annotations

import copy
import inspect
import json
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import (
    reading,
    reading_long_diagnostics,
    reading_long_inspection,
    reading_policy,
)

from . import test_annotations_long_receipts as receipt_tests
from . import test_reading_long_finalize as final_tests
from .test_reading_pass_types import observation, plan


def measured(calls: int, *, declared: Any = None) -> dict[str, Any]:
    declared = plan() if declared is None else declared
    return reading_long_diagnostics.derive(
        plan=declared,
        inspected=reading_long_inspection.Inspection(
            "a" * 32,
            exact=reading_long_inspection.Totals(
                calls, calls * 10, calls * declared["limits"]["reply_bytes"]
            ),
        ),
        outcome="withheld",
    )


class LongDiagnosticStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = receipt_tests.LongPublicationReceiptTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state

    def publish(self, value: Any, **changes: Any) -> str:
        self.assertIn("long_diagnostic", inspect.signature(store.record_withheld).parameters)
        return self.fixture.publish(long_diagnostic=value, **changes)

    def entry(self) -> Any:
        return self.fixture.fixture.entry()

    def test_three_calls_count_one_job_and_withheld_keeps_older_assessment(self) -> None:
        self.assertEqual(
            store.OUTCOME_STORED,
            self.fixture.fixture.publish("reading", self.fixture.token, job_id="old"),
        )
        standing = self.entry()["assessment"]
        value = measured(3)
        # The last individual attempt is uncharged; whole-job spending must not
        # be passed into the nested single-invocation diagnostic validator.
        slot = observation()
        slot["diagnostic"]["input"].update(
            outcome="refused", attempt_reserved=False, model_invoked=False
        )
        slot["diagnostic"]["capacity"] = None
        value["observations"] = [{"observation": slot, "ended": True}]
        self.assertEqual(store.OUTCOME_STORED, self.publish(value))
        reopened = self.entry()
        self.assertEqual(2, reopened["readings"])
        self.assertEqual(standing, reopened["assessment"])
        self.assertEqual(value, reopened["long_diagnostic"])
        public = store.published(reopened)
        self.assertEqual(3, public["long_diagnostic"]["accounting"]["totals"]["calls"])
        public["long_diagnostic"]["plan"]["limits"]["prompt_bytes"] = 1
        self.assertEqual(value, self.entry()["long_diagnostic"])

    def test_zero_is_acknowledged_unknown_and_minimum_are_refused_atomically(self) -> None:
        self.assertEqual(store.OUTCOME_STORED, self.publish(measured(0), spent=False))
        self.assertNotIn("readings", self.entry())
        unknown = reading_long_diagnostics.derive(plan=plan(), outcome="withheld")
        minimum = measured(1)
        minimum["accounting"]["state"] = "minimum"
        for value, spent in (
            (unknown, False),
            (minimum, True),
            (measured(1), False),
            (measured(0), True),
        ):
            before = self.fixture.fixture.path.read_bytes()
            self.assertEqual(
                store.OUTCOME_REFUSED, self.publish(value, spent=spent, job_id="b" * 32)
            )
            self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        self.assertEqual([self.fixture.job_id], self.entry()["long_receipts"])

    def test_long_metadata_requires_target_receipt_path_and_invalid_payload_changes_nothing(
        self,
    ) -> None:
        for changes in ({"long_publication": False}, {"long_target": None}, {"job_id": "old"}):
            before = self.fixture.fixture.path.read_bytes()
            self.assertEqual(store.OUTCOME_REFUSED, self.publish(measured(1), **changes))
            self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        for value in (
            {},
            {**measured(1), "path": "PRIVATE PATH"},
            {**measured(1), "observations": [{"words": "PRIVATE REPLY"}]},
        ):
            before = self.fixture.fixture.path.read_bytes()
            self.assertEqual(store.OUTCOME_REFUSED, self.publish(value))
            self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        self.assertNotIn("long_receipts", self.entry())
        self.assertNotIn("readings", self.entry())

    def test_edits_carry_metrics_ordinary_attempt_clears_and_late_reading_keeps_them(self) -> None:
        value = measured(1)
        self.assertEqual(store.OUTCOME_STORED, self.publish(value, kind="reading"))
        self.assertEqual(
            store.OUTCOME_STORED,
            store.record_reading(
                self.config,
                self.state,
                "claude",
                "s1",
                assessment=self.fixture.fixture.assessment(at=150),
                job_id="late",
            ),
        )
        self.assertEqual(value, self.entry()["long_diagnostic"])
        self.fixture.fixture.seed("Revised words")
        self.assertEqual(value, self.entry()["long_diagnostic"])
        self.assertEqual(
            store.OUTCOME_STORED,
            store.settle(self.config, self.state, "claude", "s1", through=150, now=300),
        )
        self.assertEqual(value, self.entry()["long_diagnostic"])
        self.assertEqual(
            store.OUTCOME_STORED,
            store.record_withheld(
                self.config,
                self.state,
                "claude",
                "s1",
                reason=reading.WITHHELD_MODEL_FAILED,
                spent=False,
            ),
        )
        self.assertNotIn("long_diagnostic", self.entry())

    def test_replay_after_thirty_three_ordinary_jobs_does_not_restore_old_metrics(self) -> None:
        value = measured(3)
        self.assertEqual(store.OUTCOME_STORED, self.publish(value))
        for ordinal in range(33):
            self.assertEqual(
                store.OUTCOME_STORED,
                store.record_withheld(
                    self.config,
                    self.state,
                    "claude",
                    "s1",
                    reason=reading.WITHHELD_MODEL_FAILED,
                    spent=True,
                    job_id=f"{ordinal:016x}",
                ),
            )
        before = self.fixture.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish(value))
        self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        self.assertEqual(34, self.entry()["readings"])
        self.assertNotIn("long_diagnostic", self.entry())

    def test_load_carry_serialize_and_publish_each_drop_malformed_metadata(self) -> None:
        self.assertEqual(store.OUTCOME_STORED, self.publish(measured(1)))
        bad = {**measured(1), "private": "PRIVATE CONFIG /secret/path"}
        raw = json.loads(self.fixture.fixture.path.read_text())
        raw["entries"][0]["long_diagnostic"] = bad
        self.fixture.fixture.path.write_text(json.dumps(raw))
        self.assertNotIn("long_diagnostic", self.entry())
        entry = self.entry()
        entry["long_diagnostic"] = bad
        self.assertNotIn("long_diagnostic", store.published(entry))
        self.assertNotIn("long_diagnostic", store._on_disk(entry))
        updated: store.Annotation = {
            "harness": "claude",
            "sid": "s1",
            "revisions": entry["revisions"],
        }
        self.assertIsNone(store._carried(entry, updated).get("long_diagnostic"))
        self.fixture.fixture.seed("Preserve reader words")
        self.assertNotIn("PRIVATE", self.fixture.fixture.path.read_text())

    def test_clear_recreate_and_unwritable_retry_preserve_count_and_receipt_atomicity(self) -> None:
        with mock.patch.object(store, "save", return_value=False):
            self.assertEqual(store.OUTCOME_UNWRITABLE, self.publish(measured(1)))
        self.assertNotIn("long_diagnostic", self.entry())
        self.assertNotIn("long_receipts", self.entry())
        self.assertEqual(store.OUTCOME_STORED, self.publish(measured(1)))
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish(measured(1)))
        self.assertEqual(1, self.entry()["readings"])
        self.assertEqual(store.OUTCOME_STORED, store.clear(self.config, self.state, "claude", "s1"))
        self.fixture.fixture.seed()
        before = self.fixture.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_REFUSED, self.publish(measured(1)))
        self.assertEqual(before, self.fixture.fixture.path.read_bytes())


class MeasuredWithheldFinalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = final_tests.WithheldFinalizationTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def diagnostic(self) -> dict[str, Any]:
        marker = self.fixture.active.owner.live.prepared
        from compass_runtime import reading_long_jobs  # noqa: PLC0415

        header = reading_long_jobs.header(marker)
        assert header is not None
        inspected = reading_long_inspection.inspect(
            self.fixture.config, self.fixture.active.job.id, now=100
        )
        return reading_long_diagnostics.derive(
            plan=header["plan"], inspected=inspected, outcome="withheld"
        )

    def finalize(self, value: Any) -> Any:
        function: Any = getattr(self.fixture.module(), "withheld_measured", None)
        self.assertTrue(
            callable(function), "measured finalization must require durable long metrics"
        )
        return function(
            self.fixture.config,
            self.fixture.state,
            active=self.fixture.active,
            reason=reading.WITHHELD_MODEL_FAILED,
            now=100,
            long_diagnostic=value,
        )

    def test_paused_history_is_stored_before_marker_retirement(self) -> None:
        self.fixture.reserve(1)
        self.fixture.reserve(2)
        self.fixture.reserve(3)
        self.fixture.seal()
        reading_policy.set_consent(self.fixture.config, False, now=100)
        value = self.diagnostic()
        original = reading_long_inspection._retire_locked

        def retire(*args: Any, **kwargs: Any) -> bool:
            self.assertEqual(value, self.fixture.entry()["long_diagnostic"])
            self.assertEqual(1, self.fixture.entry()["readings"])
            return original(*args, **kwargs)

        with mock.patch.object(reading_long_inspection, "_retire_locked", side_effect=retire):
            result = self.finalize(value)
        self.assertTrue(result.receipt_released)
        self.assertFalse(self.fixture.path.exists())
        self.assertFalse(self.finalize(value).acknowledged)

    def test_missing_malformed_plan_or_receipt_mismatch_retains_marker(self) -> None:
        self.fixture.seal()
        value = self.diagnostic()
        wrong_plan = copy.deepcopy(value)
        wrong_plan["plan"]["limits"]["source_pages"] += 1
        wrong_count = measured(1, declared=value["plan"])
        for bad in (
            None,
            {},
            {**value, "path": "PRIVATE"},
            wrong_plan,
            wrong_count,
            {**value, "outcome": "pending", "complete": None},
        ):
            before = self.fixture.fixture.path.read_bytes()
            self.assertFalse(self.finalize(bad).acknowledged)
            self.assertTrue(self.fixture.path.exists())
            self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        self.assertTrue(self.finalize(value).receipt_released)
        self.assertNotIn("readings", self.fixture.entry())

    def test_failed_write_and_crash_after_ack_retry_keep_one_count_and_metrics(self) -> None:
        self.fixture.reserve()
        self.fixture.seal()
        value = self.diagnostic()
        with mock.patch.object(store, "save", return_value=False):
            self.assertFalse(self.finalize(value).acknowledged)
        self.assertTrue(self.fixture.path.exists())
        with (
            mock.patch.object(
                reading_long_inspection, "_retire_locked", side_effect=final_tests.Crash
            ),
            self.assertRaises(final_tests.Crash),
        ):
            self.finalize(value)
        self.assertEqual(value, self.fixture.entry()["long_diagnostic"])
        self.assertTrue(self.fixture.path.exists())
        self.assertTrue(self.finalize(value).receipt_released)
        self.assertEqual(1, self.fixture.entry()["readings"])
