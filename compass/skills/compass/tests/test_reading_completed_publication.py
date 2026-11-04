"""Completed results publish behind both fences; durable replay only retires receipts."""

from __future__ import annotations

import concurrent.futures
import contextlib
import copy
import dataclasses
import json
import threading
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import (
    reading,
    reading_long_context,
    reading_long_control,
    reading_long_diagnostics,
    reading_long_finalize,
    reading_long_inspection,
    reading_long_jobs,
    reading_long_markers,
)
from compass_runtime import reading_policy as policy

from . import test_reading_final_call as call_tests
from . import test_reading_long_context as context_tests
from . import test_reading_long_finalize as final_tests
from .test_reading_long_jobs import binding


class CompletedPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = context_tests.ActiveContextTest()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.config, self.state = self.base.config, self.base.state
        call_fixture: Any = call_tests.FinalCallTest
        self.call = call_fixture()
        self.call.setUp()
        self.addCleanup(self.call.doCleanups)
        self.sid, self.key = self.base.sid, self.base.key
        reading.end_job(self.config, self.key)
        self.call.row["sid"] = self.sid
        for fact in self.call.facts:
            fact["source_session"]["sid"] = self.sid
            if "branch" in fact:
                fact["branch"]["sid"] = self.sid
        self.assertEqual(
            store.OUTCOME_STORED,
            store.annotate(
                self.config,
                self.state,
                "claude",
                self.sid,
                goal=self.call.revision["goal"],
                lines=[line["text"] for line in self.call.revision["lines"]],
                expected_revision=1,
                now=101,
            ),
        )
        entry = self.entry()
        self.call.revision = copy.deepcopy(entry["revisions"][-1])
        target = store.capture_long_target(self.config, self.state, "claude", self.sid)
        assert target is not None and self.base.permission is not None
        self.target, self.permission = target, self.base.permission
        self.plan = self.call.fixture.declared
        self.plan["limits"]["job_ms"] = 200000
        publication = {
            "harness": "claude",
            "sid": self.sid,
            "incarnation": target.incarnation,
            "revision": target.revision,
        }
        self.prepared = policy.prepare_long_job(
            permission=self.permission,
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
        assert self.prepared is not None
        active = reading_long_control.admit(
            self.config,
            self.key,
            provider="claude",
            label="Claude",
            job=self.prepared,
            permission=self.permission,
            now=100,
        )
        assert active is not None
        self.active = active
        self.addCleanup(reading.end_job, self.config, self.key)
        self.context = reading_long_context.Context(self.active, self.base.route, self.base.scope)
        self.call.fixture.fixture.config = self.config
        self.call.fixture.fixture.permission = self.permission
        self.call.fixture.owner = self.active.owner
        self.call.prepare()
        self.result = self.call.invoke()
        self.assertEqual("resolved", self.result.state)
        self.frozen = self.result.packet.frozen_context
        self.assertTrue(
            reading_long_markers.seal(self.config, self.active.owner, state="completed", now=201)
        )
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=201)
        self.diagnostic = reading_long_diagnostics.derive(
            plan=self.plan,
            series=self.call.series,
            reconciliation_observations=[self.result.observations[-1]],
            inspected=inspected,
            outcome="completed",
            binding=reading_long_diagnostics.bind_context(self.frozen, started_at=100),
        )
        window = self.frozen.value()["window"]
        self.assessment: Any = {
            "revision_read": target.revision,
            "revision_read_at": self.call.revision["at"],
            "window_start": window["start"],
            "read_at": 201.0,
            "stamp": "read now",
            "cutoff": "Read original evidence",
            "scope": window["scope"],
            "scope_text": reading.SCOPE_TEXT[window["scope"]],
            "ended_at_read": window["end"],
            "evidence_through": 200.0,
            "criteria": self.result.criteria,
        }
        self.source_current = True
        self.path = reading_long_markers.marker_path(self.config, self.active.job.id)

    def entry(self) -> Any:
        return store.find(store.load(self.config), "claude", self.sid)

    def finalize(self, **changes: Any) -> Any:
        function: Any = getattr(reading_long_finalize, "completed", None)
        self.assertTrue(callable(function), "completed publication must use the held fences")
        if not self.active.job.sealed:
            reading.seal_job(self.active.job)
        options = {
            "context": self.context,
            "result": self.result,
            "assessment": self.assessment,
            "frozen": self.frozen,
            "long_diagnostic": self.diagnostic,
            "source_current": lambda: self.source_current,
            "now": 201,
        }
        return function(self.config, self.state, **{**options, **changes})

    def test_actual_resolved_result_is_saved_before_retirement_and_counts_one_job(self) -> None:
        original = reading_long_inspection._retire_locked

        def retire(*args: Any, **kwargs: Any) -> bool:
            self.assertEqual(self.result.criteria, self.entry()["assessment"]["criteria"])
            self.assertEqual(self.diagnostic, self.entry()["long_diagnostic"])
            self.assertEqual(1, self.entry()["readings"])
            return original(*args, **kwargs)

        with mock.patch.object(reading_long_inspection, "_retire_locked", side_effect=retire):
            outcome = self.finalize()
        self.assertTrue(outcome.acknowledged and outcome.retired and outcome.receipt_released)
        self.assertEqual(2, self.diagnostic["accounting"]["totals"]["calls"])
        self.assertFalse(self.path.exists())
        self.assertFalse(self.finalize().acknowledged)

    def seed_departure(self) -> None:
        previous = copy.deepcopy(self.assessment)
        previous["read_at"] = 150.0
        previous["criteria"]["line_1"].update(
            result=reading.RESULT_DEPARTURE, detail="The earlier check failed."
        )
        self.assertEqual(
            store.OUTCOME_STORED,
            store.record_reading(self.config, self.state, "claude", self.sid, assessment=previous),
        )

    def test_owner_computed_passing_check_clears_prior_departure(self) -> None:
        self.seed_departure()
        checked = reading.lines_on_a_check(self.assessment, self.call.facts)
        self.assertEqual(frozenset({"line_1"}), checked)
        self.assertTrue(self.finalize(on_a_check=checked).acknowledged)
        self.assertFalse(self.entry().get("prior_departures"))

    def test_default_empty_check_ids_preserve_prior_departure(self) -> None:
        self.seed_departure()
        self.assertTrue(self.finalize().acknowledged)
        self.assertEqual(["line_1"], [row["key"] for row in self.entry()["prior_departures"]])

    def test_foreign_check_ids_refuse_without_new_write(self) -> None:
        before = self.base.fixture.path.read_bytes()
        self.assertFalse(self.finalize(on_a_check={"foreign"}).acknowledged)
        self.assertTrue(self.path.exists())
        self.assertEqual(before, self.base.fixture.path.read_bytes())

    def test_invalid_result_assessment_binding_or_observations_changes_nothing(self) -> None:
        wrong_binding = copy.deepcopy(self.diagnostic)
        wrong_binding["binding"]["job_started_at"] += 1
        wrong_observations = copy.deepcopy(self.diagnostic)
        wrong_observations["observations"] = []
        cases = (
            {
                "result": dataclasses.replace(
                    self.result,
                    packet=dataclasses.replace(
                        self.result.packet, prompt="foreign assembled prompt"
                    ),
                )
            },
            {"result": dataclasses.replace(self.result, state="unresolved")},
            {"result": dataclasses.replace(self.result, criteria=None)},
            {"result": dataclasses.replace(self.result, unresolved=("source",))},
            {"assessment": {**self.assessment, "criteria": {}}},
            {"assessment": {**self.assessment, "revision_read": 999}},
            {"assessment": {**self.assessment, "window_start": 1}},
            {"long_diagnostic": wrong_binding},
            {"long_diagnostic": wrong_observations},
            {"frozen": None},
            {"context": None},
            {"source_current": None},
        )
        for changes in cases:
            before = self.base.fixture.path.read_bytes()
            outcome = self.finalize(**changes)
            self.assertFalse(outcome.acknowledged)
            self.assertTrue(outcome.reason)
            self.assertTrue(self.path.exists())
            self.assertEqual(before, self.base.fixture.path.read_bytes())

    def test_pause_then_resume_blocks_new_prose_without_refunding_charges(self) -> None:
        policy.set_consent(self.config, False, now=201)
        self.assertEqual("permission-changed", self.finalize().reason)
        policy.resume(self.config, now=201)
        self.assertFalse(self.finalize().acknowledged)
        self.assertNotIn("readings", self.entry())
        totals = reading_long_inspection.inspect(self.config, self.active.job.id, now=201).exact
        assert totals is not None
        self.assertEqual(2, totals.calls)

    def test_source_changes_refuse_new_prose(self) -> None:
        for source in (lambda: False, lambda: None, lambda: 1):
            self.assertFalse(self.finalize(source_current=source).acknowledged)

    def test_accepted_cancel_before_seal_refuses_new_prose(self) -> None:
        self.assertTrue(reading.cancel_job(self.config, self.key, self.active.job.id, now=201)[0])
        self.assertEqual("cancelled", self.finalize().reason)
        self.assertNotIn("readings", self.entry())

    def test_target_edit_or_clear_recreate_never_publishes_old_result(self) -> None:
        store.annotate(self.config, self.state, "claude", self.sid, goal="New goal", now=202)
        self.assertFalse(self.finalize().acknowledged)
        store.clear(self.config, self.state, "claude", self.sid)
        store.annotate(
            self.config, self.state, "claude", self.sid, goal=self.call.revision["goal"], now=101
        )
        before = self.base.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(before, self.base.fixture.path.read_bytes())

    def test_unwritable_then_retry_keeps_exact_one_job_count(self) -> None:
        with mock.patch.object(store, "save", return_value=False):
            self.assertFalse(self.finalize().acknowledged)
        self.assertTrue(self.path.exists())
        self.assertNotIn("readings", self.entry())
        self.assertTrue(self.finalize().receipt_released)
        self.assertEqual(1, self.entry()["readings"])

    def test_crash_ack_replay_after_pause_edit_source_change_and_33_jobs_only_cleans_up(
        self,
    ) -> None:
        with (
            mock.patch.object(
                reading_long_inspection, "_retire_locked", side_effect=final_tests.Crash
            ),
            self.assertRaises(final_tests.Crash),
        ):
            self.finalize()
        self.assertEqual([self.active.job.id], self.entry()["long_receipts"])
        for n in range(33):
            store.record_withheld(
                self.config,
                self.state,
                "claude",
                self.sid,
                reason=reading.WITHHELD_MODEL_FAILED,
                spent=True,
                job_id=f"{n:016x}",
            )
        store.annotate(self.config, self.state, "claude", self.sid, goal="New goal", now=202)
        policy.set_consent(self.config, False, now=202)
        self.base.clock[0] = 999
        before = store.published(self.entry())
        with (
            mock.patch.object(policy, "long_publication_permission", side_effect=AssertionError),
            mock.patch.object(store, "record_reading", side_effect=AssertionError),
        ):
            result = self.finalize(source_current=lambda: False)
        self.assertTrue(result.acknowledged and result.retired and result.receipt_released)
        self.assertEqual(before, store.published(self.entry()))
        self.assertEqual(34, self.entry()["readings"])
        self.assertNotIn("long_diagnostic", self.entry())

    def test_missing_or_malformed_acknowledgment_never_permits_cleanup(self) -> None:
        with (
            mock.patch.object(
                reading_long_inspection, "_retire_locked", side_effect=final_tests.Crash
            ),
            self.assertRaises(final_tests.Crash),
        ):
            self.finalize()
        raw = json.loads(self.base.fixture.path.read_text())
        next(item for item in raw["entries"] if item["sid"] == self.sid)["long_receipts"] = None
        self.base.fixture.path.write_text(json.dumps(raw))
        before = self.base.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertTrue(self.path.exists())
        self.assertEqual(before, self.base.fixture.path.read_bytes())
        self.base.fixture.path.unlink()
        store.annotate(self.config, self.state, "claude", self.sid, goal="Recreated", now=101)
        before = self.base.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertTrue(self.path.exists())
        self.assertEqual(before, self.base.fixture.path.read_bytes())

    def test_annotation_lock_wait_rechecks_elapsed_and_source(self) -> None:
        original = store._store_locks
        for changed in ("deadline", "source"):
            entered = threading.Event()

            @contextlib.contextmanager
            def waiting(*args: Any, entered: threading.Event = entered, **kwargs: Any) -> Any:
                entered.set()
                with original(*args, **kwargs) as held:
                    yield held

            self.base.clock[0], self.source_current = 0.0, True
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                with (
                    original(self.config, self.state, wait=2, make_home=False),
                    mock.patch.object(store, "_store_locks", waiting),
                    mock.patch.object(store, "long_receipt_acknowledged", return_value=False),
                ):
                    future = pool.submit(self.finalize)
                    self.assertTrue(entered.wait(2))
                    self.assertFalse(future.done())
                    if changed == "deadline":
                        self.base.clock[0] = 201
                    else:
                        self.source_current = False
                self.assertFalse(future.result(timeout=5).acknowledged)
            self.assertTrue(self.path.exists())
            self.assertNotIn("readings", self.entry())

    def test_pause_inside_publication_waits_for_prior_annotation_commit(self) -> None:
        entered, release, pause_wait = threading.Event(), threading.Event(), threading.Event()

        def source() -> bool:
            entered.set()
            self.assertTrue(release.wait(5))
            return True

        connect = policy._connect

        def traced(*args: Any, **kwargs: Any) -> Any:
            db = connect(*args, **kwargs)
            db.set_trace_callback(
                lambda sql: pause_wait.set() if sql == "BEGIN IMMEDIATE" else None
            )
            return db

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            published = pool.submit(self.finalize, source_current=source)
            try:
                self.assertTrue(entered.wait(2))
                with mock.patch.object(policy, "_connect", side_effect=traced):
                    paused = pool.submit(policy.set_consent, self.config, False, now=201)
                    self.assertTrue(pause_wait.wait(2))
                    self.assertFalse(paused.done())
                    release.set()
                    self.assertTrue(published.result(timeout=5).acknowledged)
                    self.assertTrue(paused.result(timeout=5)["off"])
            finally:
                release.set()
        self.assertEqual(1, self.entry()["readings"])
