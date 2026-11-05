"""Only actual original-supported partial reconciliation may publish a partial reading."""

from __future__ import annotations

import copy
import dataclasses
import unittest
from typing import Any

from compass_runtime import annotations as store
from compass_runtime import (
    reading,
    reading_final_call,
    reading_long_context,
    reading_long_control,
    reading_long_jobs,
    reading_long_markers,
    reading_policy,
)
from compass_runtime import reading_long_diagnostics as diagnostics
from compass_runtime import reading_long_finalize as finalize
from compass_runtime import reading_long_inspection as inspection

from . import test_reading_long_context as context_tests
from . import test_reading_useful_long as useful_tests
from .test_reading_long_jobs import binding


class PartialPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = context_tests.ActiveContextTest()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.config, self.state = self.base.config, self.base.state
        factory: Any = useful_tests.UsefulLongReconciliationTest
        self.producer = factory()
        self.producer.setUp()
        self.addCleanup(self.producer.doCleanups)
        self.producer.collect_large()
        self.sid = self.producer.inputs.row["sid"]
        self.key = "claude:" + self.sid
        reading.end_job(self.config, self.base.key)
        revision = self.producer.inputs.revision
        self.assertEqual(
            store.OUTCOME_STORED,
            store.annotate(
                self.config,
                self.state,
                "claude",
                self.sid,
                goal=revision["goal"],
                lines=[line["text"] for line in revision["lines"]],
                now=revision["at"],
            ),
        )
        current = store.find(store.load(self.config), "claude", self.sid)
        assert current is not None
        self.producer.inputs = dataclasses.replace(
            self.producer.inputs, revision=current["revisions"][-1]
        )
        self.producer.context = reading_final_call.freeze_context(
            self.producer.inputs,
            self.producer.floor,
            scope=reading.SCOPE_FINAL,
            source_complete=True,
        )
        target = store.capture_long_target(self.config, self.state, "claude", self.sid)
        assert target is not None and self.base.permission is not None
        publication = {
            "harness": "claude",
            "sid": self.sid,
            "incarnation": target.incarnation,
            "revision": target.revision,
        }
        self.plan = self.producer.marker.declared
        self.plan["limits"]["job_ms"] = 200000
        prepared = reading_policy.prepare_long_job(
            permission=self.base.permission,
            binding=binding(
                plan=self.plan,
                publication=publication,
                target_sha256=reading_long_jobs.publication_digest(publication),
                scope_sha256=reading_long_context.scope_digest(self.base.route, self.base.scope),
                destination_sha256=reading_long_context.destination_digest(self.base.route),
            ),
            call_timeout_ms=180000,
            clock=lambda: self.base.clock[0],
        )
        assert prepared is not None
        active = reading_long_control.admit(
            self.config,
            self.key,
            provider="claude",
            label="Claude",
            job=prepared,
            permission=self.base.permission,
            now=100,
        )
        assert active is not None
        self.active = active
        self.addCleanup(reading.end_job, self.config, self.key)
        self.context = reading_long_context.Context(active, self.base.route, self.base.scope)
        self.producer.marker.fixture.config = self.config
        self.producer.marker.fixture.permission = self.base.permission
        self.producer.marker.owner = active.owner
        self.series = self.producer.run_maps()
        self.result = self.producer.invoke(self.series)
        self.assertEqual("partial", self.result.state)
        self.frozen = self.result.packet.frozen_context
        self.assertTrue(
            reading_long_markers.seal(self.config, active.owner, state="completed", now=201)
        )
        reading.seal_job(active.job)
        self.inspected = inspection.inspect(self.config, active.job.id, now=201)
        window = self.frozen.value()["window"]
        self.assessment: Any = {
            "revision_read": target.revision,
            "revision_read_at": revision["at"],
            "window_start": window["start"],
            "read_at": 201.0,
            "stamp": "read now",
            "cutoff": "Original-supported local findings",
            "scope": window["scope"],
            "scope_text": reading.SCOPE_TEXT[window["scope"]],
            "ended_at_read": window["end"],
            "evidence_through": window["end"],
            "criteria": self.result.criteria,
        }

    def diagnostic(self) -> Any:
        return diagnostics.derive(
            plan=self.plan,
            series=self.series,
            reconciliation_observations=[self.result.observations[-1]],
            inspected=self.inspected,
            outcome="partial",
            binding=diagnostics.bind_context(self.frozen, started_at=100),
        )

    def publish(self, **changes: Any) -> Any:
        options = {
            "context": self.context,
            "result": self.result,
            "assessment": self.assessment,
            "frozen": self.frozen,
            "long_diagnostic": self.diagnostic(),
            "source_current": lambda: True,
            "now": 201,
            "on_a_check": reading.lines_on_a_check(self.assessment, self.producer.inputs.facts),
        }
        return finalize.completed(self.config, self.state, **{**options, **changes})

    def test_actual_multi_map_partial_publishes_local_departure_and_counts_one_job(self) -> None:
        self.assertFalse(reading.lines_on_a_check(self.assessment, self.producer.inputs.facts))
        outcome = self.publish()
        self.assertTrue(outcome.acknowledged and outcome.retired and outcome.receipt_released)
        entry = store.find(store.load(self.config), "claude", self.sid)
        assert entry is not None
        self.assertEqual(1, entry["readings"])
        diagnostic = entry["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual(8, diagnostic["accounting"]["totals"]["calls"])
        self.assertIs(diagnostic["complete"], False)
        self.assertEqual("partial", diagnostic["outcome"])
        self.assertEqual(self.result.criteria, entry["assessment"]["criteria"])
        for key in ("goal", "claims", "line_2"):
            self.assertEqual(
                reading.WHY_LONG_RECONCILIATION_COVERAGE,
                entry["assessment"]["criteria"][key]["why"],
            )

    def test_closed_partial_diagnostic_requires_binding_and_false_completeness(self) -> None:
        checked = self.diagnostic()
        self.assertIsNotNone(diagnostics.validate(checked))
        for changes in (
            {"binding": None},
            {"complete": None},
            {"complete": True},
            {"outcome": "soft-partial"},
        ):
            self.assertIsNone(diagnostics.validate({**checked, **changes}))
        copied = diagnostics.validate(checked)
        assert copied is not None
        copied["plan"]["limits"]["reply_bytes"] = 1
        self.assertNotEqual(copied["plan"], checked["plan"])

    def test_other_gaps_foreign_criteria_and_global_reassurance_refuse(self) -> None:
        invalid = [
            dataclasses.replace(self.result, unresolved=()),
            dataclasses.replace(self.result, unresolved=("agent-words-partial", "source-gap")),
            dataclasses.replace(self.result, reason="coverage-incomplete"),
            dataclasses.replace(self.result, state="resolved", reason="ok"),
        ]
        for key, result in (
            ("goal", reading.RESULT_CONSISTENT),
            ("claims", reading.RESULT_DEPARTURE),
            ("line_2", reading.RESULT_CONSISTENT),
        ):
            criteria = copy.deepcopy(self.result.criteria)
            criteria[key].update(result=result, cites=(self.producer.middle,))
            invalid.append(dataclasses.replace(self.result, criteria=criteria))
        criteria = copy.deepcopy(self.result.criteria)
        criteria["line_1"]["cites"] = ("foreign-original",)
        invalid.append(dataclasses.replace(self.result, criteria=criteria))
        for result in invalid:
            with self.subTest(
                result=result.state, reason=result.reason, unresolved=result.unresolved
            ):
                self.assertFalse(
                    self.publish(
                        result=result, assessment={**self.assessment, "criteria": result.criteria}
                    ).acknowledged
                )
        self.assertTrue(reading_long_markers.marker_path(self.config, self.active.job.id).exists())

    def test_partial_cannot_hide_hard_map_gap_or_clear_uncertain_prior_concerns(self) -> None:
        diagnostic = self.diagnostic()
        diagnostic["maps"]["reason"] = "unresolved"
        self.assertFalse(self.publish(long_diagnostic=diagnostic).acknowledged)
        self.assertFalse(self.publish(on_a_check={"line_2"}).acknowledged)

    def test_partial_obeys_permission_source_and_locked_target_gates(self) -> None:
        self.assertFalse(self.publish(source_current=lambda: False).acknowledged)
        reading_policy.set_consent(self.config, False, now=201)
        self.assertFalse(self.publish().acknowledged)
        reading_policy.resume(self.config, now=201)
        self.assertFalse(self.publish().acknowledged)
        self.assertTrue(reading_long_markers.marker_path(self.config, self.active.job.id).exists())
