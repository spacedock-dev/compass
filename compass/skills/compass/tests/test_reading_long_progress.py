"""Closed public progress carries counts, never source material or authority."""

from __future__ import annotations

import concurrent.futures
import copy
import dataclasses
import json
import sqlite3
import threading
import unittest
from contextlib import closing
from typing import Any
from unittest import mock

from compass_runtime import reading
from compass_runtime import reading_long_control as control
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_jobs as jobs
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_long_progress as progress
from compass_runtime import reading_policy as policy

from . import test_reading_long_control as control_tests
from .test_reading_long_jobs import binding
from .test_reading_pass_types import plan


class ProgressShapeTest(unittest.TestCase):
    def test_initial_unknown_source_and_accounting_are_independent_copies(self) -> None:
        declared = plan()
        value = progress.initial(declared)
        self.assertEqual("source", value["stage"])
        self.assertEqual(
            {
                "streams_total": None,
                "streams_verified": None,
                "bytes_read": None,
                "pages_read": None,
            },
            value["source"],
        )
        self.assertEqual({"planned": None, "ended": 0, "current": None}, value["evidence"])
        self.assertEqual({"ordinal": 17, "state": "not-started"}, value["reconciliation"])
        self.assertEqual({"state": "unknown", "totals": None}, value["accounting"])
        checked = progress.validate(value, plan=declared)
        self.assertEqual(value, checked)
        assert checked is not None
        checked["source"]["bytes_read"] = 0
        self.assertIsNone(value["source"]["bytes_read"])

    def test_seven_maps_plus_reserved_final_position_are_eight_receipt_calls(self) -> None:
        declared = plan()
        value = progress.initial(declared)
        value.update(
            stage="publication",
            evidence={"planned": 7, "ended": 7, "current": None},
            reconciliation={"ordinal": 17, "state": "ended"},
            accounting={
                "state": "exact",
                "totals": {
                    "calls": 8,
                    "prompt_bytes": 800,
                    "reply_bytes": 8 * declared["limits"]["reply_bytes"],
                },
            },
        )
        self.assertEqual(value, progress.validate(value, plan=declared))
        value["accounting"]["state"] = "minimum"
        self.assertEqual(value, progress.validate(value, plan=declared))
        value["accounting"] = {"state": "unknown", "totals": None}
        self.assertEqual(value, progress.validate(value, plan=declared))

    def test_closed_bounds_reject_words_booleans_nan_and_impossible_counts(self) -> None:
        declared = plan()
        base = progress.initial(declared)
        invalid: list[dict[str, Any]] = [
            {**base, "path": "/private/session"},
            {**base, "stage": "PRIVATE REPLY"},
            {**base, "version": True},
            {**base, "source": {**base["source"], "bytes_read": float("nan")}},
            {**base, "source": {**base["source"], "streams_total": 513}},
            {**base, "source": {**base["source"], "streams_total": 2, "streams_verified": 3}},
            {**base, "evidence": {"planned": 17, "ended": 0, "current": None}},
            {**base, "evidence": {"planned": None, "ended": 1, "current": None}},
            {**base, "stage": "evidence", "evidence": {"planned": 7, "ended": 8, "current": None}},
            {**base, "stage": "evidence", "evidence": {"planned": 7, "ended": 0, "current": 8}},
            {**base, "reconciliation": {"ordinal": 8, "state": "not-started"}},
            {**base, "reconciliation": {"ordinal": 17, "state": "running"}},
            {
                **base,
                "accounting": {
                    "state": "unknown",
                    "totals": {"calls": 0, "prompt_bytes": 0, "reply_bytes": 0},
                },
            },
            {
                **base,
                "accounting": {
                    "state": "exact",
                    "totals": {"calls": 1, "prompt_bytes": 1, "reply_bytes": 1},
                },
            },
        ]
        for value in invalid:
            with self.subTest(value=value):
                self.assertIsNone(progress.validate(value, plan=declared))
        for counter in (True, -1, 2**53, float("inf")):
            value = copy.deepcopy(base)
            value["source"]["pages_read"] = counter
            self.assertIsNone(progress.validate(value, plan=declared))

    def test_current_evidence_position_cannot_skip_unended_passes(self) -> None:
        declared = plan()
        value = progress.initial(declared)
        value.update(stage="evidence", evidence={"planned": 7, "ended": 0, "current": 5})
        self.assertIsNone(progress.validate(value, plan=declared))

    def test_known_zero_requires_explicit_accounting_and_no_plan_mutation(self) -> None:
        declared = plan()
        before = copy.deepcopy(declared)
        value = progress.initial(declared)
        value["accounting"] = {
            "state": "exact",
            "totals": {"calls": 0, "prompt_bytes": 0, "reply_bytes": 0},
        }
        self.assertEqual(value, progress.validate(value, plan=declared))
        self.assertEqual(before, declared)
        self.assertIsNone(progress.validate(value, plan={**declared, "extra": "words"}))


class ProgressRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = control_tests.RegisteredShellTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.key = self.fixture.config, self.fixture.key

    def admit(self) -> control.Active:
        assert self.fixture.prepared is not None and self.fixture.permission is not None
        active = control.admit(
            self.config,
            self.key,
            provider="claude",
            label="Claude Code",
            job=self.fixture.prepared,
            permission=self.fixture.permission,
            now=100,
        )
        assert active is not None
        return active

    def shown(self) -> dict[str, Any]:
        return reading.published_jobs(self.config)[self.key]

    def test_ordinary_json_is_unchanged_even_with_a_prepared_identity(self) -> None:
        job = reading.start_job(
            self.config,
            self.key,
            provider="claude",
            label="Claude Code",
            now=100,
            prepared_job_id="a" * 32,
        )
        assert job is not None
        self.assertEqual(
            {"id", "phase", "phase_at", "started_at", "provider", "cancelling", "steps"},
            set(self.shown()),
        )
        self.assertFalse(
            reading.update_long_progress(
                self.config, self.key, job, progress.initial(plan()), job_id=job.id, plan=plan()
            )
        )
        self.assertNotIn("mode", self.shown())

    def test_long_mode_and_copied_immutable_plan_exist_at_first_publication(self) -> None:
        original = markers.begin
        snapshots: list[dict[str, Any]] = []

        def begin(*args: Any, **kwargs: Any) -> markers.MarkerOwner | None:
            snapshots.append(self.shown())
            return original(*args, **kwargs)

        with mock.patch.object(markers, "begin", side_effect=begin):
            active = self.admit()
        header = jobs.header(active.owner.live.prepared)
        assert header is not None
        self.assertEqual("long", snapshots[0]["mode"])
        self.assertEqual(header["plan"], snapshots[0]["plan"])
        self.assertEqual(progress.initial(header["plan"]), snapshots[0]["progress"])
        snapshots[0]["plan"]["limits"]["prompt_bytes"] = 1
        snapshots[0]["progress"]["source"]["bytes_read"] = 999
        self.assertEqual(header["plan"], self.shown()["plan"])
        self.assertIsNone(self.shown()["progress"]["source"]["bytes_read"])
        self.assertEqual(0, self.fixture.fixture.spends())

    def test_actual_plan_before_factory_and_receipts_are_separate_from_final_ordinal(self) -> None:
        active = self.admit()
        declared = self.shown()["plan"]
        value = progress.initial(declared)
        value.update(stage="evidence", evidence={"planned": 2, "ended": 0, "current": None})
        known_zero = inspection.inspect(self.config, active.job.id, now=100)
        self.assertTrue(control.publish_progress(self.config, active, value, inspected=known_zero))
        self.assertEqual(2, self.shown()["progress"]["evidence"]["planned"])
        self.assertEqual(0, self.shown()["progress"]["accounting"]["totals"]["calls"])
        self.assertEqual("preparing", self.shown()["phase"])
        self.assertTrue(reading.advance_job(self.config, self.key, "waiting", now=101))
        for ordinal in (1, 2, declared["max_calls"]):
            request = self.fixture.fixture.request(active.owner, ordinal)
            permit = markers.reserve(self.config, active.owner, request=request, now=100)
            self.assertTrue(permit.launch)
            self.assertTrue(
                markers.settle(
                    self.config,
                    active.owner,
                    observation={
                        "version": 1,
                        "ordinal": ordinal,
                        "kind": request["kind"],
                        "diagnostic": None,
                    },
                    now=100,
                )
            )
        value.update(
            stage="reconciliation",
            evidence={"planned": 2, "ended": 2, "current": None},
            reconciliation={"ordinal": declared["max_calls"], "state": "ended"},
        )
        actual = inspection.inspect(self.config, active.job.id, now=100)
        self.assertTrue(control.publish_progress(self.config, active, value, inspected=actual))
        self.assertEqual(3, self.shown()["progress"]["accounting"]["totals"]["calls"])
        self.assertEqual(4, self.shown()["progress"]["reconciliation"]["ordinal"])
        self.assertEqual("waiting", self.shown()["phase"])
        self.assertFalse(reading.advance_job(self.config, self.key, "preparing", now=102))
        self.assertTrue(reading.advance_job(self.config, self.key, "checking", now=103))
        self.assertFalse(reading.advance_job(self.config, self.key, "waiting", now=104))

    def test_accounting_is_receipt_bound_and_unknown_never_reuses_exact_zero(self) -> None:
        active = self.admit()
        value = self.shown()["progress"]
        exact = inspection.inspect(self.config, active.job.id, now=100)
        self.assertTrue(control.publish_progress(self.config, active, value, inspected=exact))
        self.assertFalse(
            control.publish_progress(
                self.config, active, value, inspected=dataclasses.replace(exact, job_id="f" * 32)
            )
        )
        value["accounting"] = {
            "state": "exact",
            "totals": {"calls": 0, "prompt_bytes": 0, "reply_bytes": 0},
        }
        self.assertTrue(control.publish_progress(self.config, active, value))
        self.assertEqual(
            {"state": "unknown", "totals": None}, self.shown()["progress"]["accounting"]
        )
        unknown = dataclasses.replace(exact, exact=None, minimum=inspection.Totals(0, 0, 0))
        self.assertTrue(control.publish_progress(self.config, active, value, inspected=unknown))
        self.assertEqual("minimum", self.shown()["progress"]["accounting"]["state"])
        impossible = dataclasses.replace(exact, exact=inspection.Totals(1, 1, 1))
        self.assertFalse(control.publish_progress(self.config, active, value, inspected=impossible))

    def test_known_receipts_reject_foreign_relabelled_or_missing_snapshot(self) -> None:
        active = self.admit()
        value = self.shown()["progress"]
        assert self.fixture.permission is not None
        prepared = policy.prepare_long_job(
            permission=self.fixture.permission,
            binding=binding(),
            call_timeout_ms=200,
            clock=lambda: 0.0,
        )
        assert prepared is not None
        other = control.admit(
            self.config,
            "claude:foreign",
            provider="claude",
            label="Claude Code",
            job=prepared,
            permission=self.fixture.permission,
            now=100,
        )
        assert other is not None
        self.addCleanup(reading.end_job, self.config, "claude:foreign")
        foreign = inspection.inspect(self.config, other.job.id, now=100)
        assert foreign.exact is not None
        forged = dataclasses.replace(foreign, job_id=active.job.id)
        self.assertFalse(control.publish_progress(self.config, active, value, inspected=forged))
        actual = inspection.inspect(self.config, active.job.id, now=100)
        for snapshot in (None, "malformed"):
            with self.subTest(snapshot=snapshot):
                self.assertFalse(
                    control.publish_progress(
                        self.config,
                        active,
                        value,
                        inspected=dataclasses.replace(actual, snapshot=snapshot),
                    )
                )

    def test_actual_minimum_retains_header_binding_and_recreated_ledger_stays_unknown(self) -> None:
        active = self.admit()
        header = jobs.header(active.owner.live.prepared)
        assert header is not None
        request = self.fixture.fixture.request(active.owner, 1)
        self.assertTrue(markers.reserve(self.config, active.owner, request=request, now=100).launch)
        with closing(sqlite3.connect(policy.store_path(self.config))) as db:
            db.execute("UPDATE long_permission SET pass_ledger_since=100 WHERE id=1")
            db.commit()
        minimum = inspection.inspect(self.config, active.job.id, now=100)
        self.assertIsNone(minimum.exact)
        assert minimum.minimum is not None
        self.assertEqual(1, minimum.minimum.calls)
        self.assertIsNone(minimum.snapshot)
        self.assertEqual(jobs.digest(header), minimum.header_sha256)
        value = self.shown()["progress"]
        self.assertTrue(control.publish_progress(self.config, active, value, inspected=minimum))
        self.assertEqual("minimum", self.shown()["progress"]["accounting"]["state"])
        self.assertFalse(
            control.publish_progress(
                self.config,
                active,
                value,
                inspected=dataclasses.replace(minimum, header_sha256=None),
            )
        )
        policy.store_path(self.config).unlink()
        policy.set_consent(self.config, False, now=101)
        policy.resume(self.config, now=101)
        recreated = inspection.inspect(self.config, active.job.id, now=101)
        self.assertIsNone(recreated.exact)
        self.assertIsNone(recreated.minimum)
        self.assertTrue(control.publish_progress(self.config, active, value, inspected=recreated))
        self.assertEqual(
            {"state": "unknown", "totals": None}, self.shown()["progress"]["accounting"]
        )
        self.assertEqual(1, minimum.minimum.calls)

    def test_updates_copy_and_refuse_changed_plan_backward_stage_or_changed_evidence_plan(
        self,
    ) -> None:
        active = self.admit()
        value = self.shown()["progress"]
        value.update(stage="evidence", evidence={"planned": 2, "ended": 0, "current": 1})
        self.assertTrue(control.publish_progress(self.config, active, value))
        value["evidence"]["current"] = 2
        self.assertEqual(1, self.shown()["progress"]["evidence"]["current"])
        self.assertFalse(
            control.publish_progress(self.config, active, progress.initial(self.shown()["plan"]))
        )
        value["evidence"]["planned"] = 3
        self.assertFalse(control.publish_progress(self.config, active, value))
        altered = dataclasses.replace(active.owner.live.prepared, binding="{}")
        foreign = dataclasses.replace(
            active,
            owner=dataclasses.replace(
                active.owner, live=dataclasses.replace(active.owner.live, prepared=altered)
            ),
        )
        self.assertFalse(control.publish_progress(self.config, foreign, self.shown()["progress"]))

    def test_cancel_seal_replacement_and_copied_job_cannot_update(self) -> None:
        active = self.admit()
        value = self.shown()["progress"]
        self.assertFalse(
            reading.update_long_progress(
                self.config,
                self.key,
                dataclasses.replace(active.job),
                value,
                job_id=active.job.id,
                plan=self.shown()["plan"],
            )
        )
        reading.cancel_job(self.config, self.key, active.job.id, now=101)
        before = self.shown()
        self.assertFalse(control.publish_progress(self.config, active, value))
        self.assertEqual(before, self.shown())
        reading.end_job(self.config, self.key)
        replacement = self.fixture.ordinary()
        self.assertFalse(control.publish_progress(self.config, active, value))
        self.assertIs(replacement, reading.job(self.config, self.key))
        assert replacement is not None
        reading.seal_job(replacement)
        self.assertFalse(
            reading.update_long_progress(
                self.config, self.key, replacement, value, job_id=replacement.id, plan=plan()
            )
        )

    def test_update_waits_for_slot_lock_then_observes_cancel_or_seal(self) -> None:
        for seal in (False, True):
            with self.subTest(seal=seal):
                reading.end_job(self.config, self.key)
                # A fresh durable identity is required for another shell, not a replay.
                assert self.fixture.permission is not None
                prepared = policy.prepare_long_job(
                    permission=self.fixture.permission,
                    binding=binding(),
                    call_timeout_ms=200,
                    clock=lambda: 0.0,
                )
                assert prepared is not None
                active = control.admit(
                    self.config,
                    self.key,
                    provider="claude",
                    label="Claude Code",
                    job=prepared,
                    permission=self.fixture.permission,
                    now=100,
                )
                assert active is not None
                value = self.shown()["progress"]
                entered = threading.Event()

                def update(
                    owner: control.Active, snapshot: dict[str, Any], signal: threading.Event
                ) -> bool:
                    signal.set()
                    return control.publish_progress(self.config, owner, snapshot)

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    with reading._FLIGHT_LOCK:
                        future = pool.submit(update, active, value, entered)
                        self.assertTrue(entered.wait(2))
                        if seal:
                            active.job.sealed = True
                        else:
                            active.job.cancelled_at = 101
                    self.assertFalse(future.result(timeout=2))

    def test_public_reads_are_closed_copies_without_io_or_permission_work(self) -> None:
        active = self.admit()
        before = self.fixture.fixture.path(active.owner).read_bytes()
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "reserve_registered_pass", side_effect=AssertionError),
            mock.patch.object(inspection, "inspect", side_effect=AssertionError),
            mock.patch.object(markers, "load", side_effect=AssertionError),
        ):
            shown = self.shown()
            self.assertTrue(control.publish_progress(self.config, active, shown["progress"]))
            encoded = json.dumps(self.shown())
        for secret in ("nonce", "lineage", "sha256", "snapshot", "hypothesis", "/private/"):
            self.assertNotIn(secret, encoded)
        bad = {**shown["progress"], "cursor": "PRIVATE WORDS"}
        self.assertFalse(control.publish_progress(self.config, active, bad))
        self.assertEqual(before, self.fixture.fixture.path(active.owner).read_bytes())
