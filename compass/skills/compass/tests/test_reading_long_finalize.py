"""Terminal withheld publication consumes exact receipts and cannot replay after cleanup."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import importlib.util
import json
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import io as runtime_io
from compass_runtime import (
    reading,
    reading_long_cleanup,
    reading_long_control,
    reading_long_inspection,
    reading_long_jobs,
    reading_long_markers,
)
from compass_runtime import reading_policy as policy

from . import test_annotations_long_target as target_tests
from .test_reading_long_jobs import binding
from .test_reading_long_reservation import request


class Crash(BaseException):
    pass


class WithheldFinalizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = target_tests.LongTargetTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state
        self.sid, self.key = "abc123ab", "claude:abc123ab"
        store.annotate(self.config, self.state, "claude", self.sid, goal="Retain words", now=100)
        self.target = store.capture_long_target(self.config, self.state, "claude", self.sid)
        assert self.target is not None
        self.permission = policy.capture_long_permission(self.config, now=100)
        assert self.permission is not None
        association = {
            "harness": "claude",
            "sid": self.sid,
            "incarnation": self.target.incarnation,
            "revision": self.target.revision,
        }
        prepared = policy.prepare_long_job(
            permission=self.permission,
            binding=binding(
                publication=association,
                target_sha256=reading_long_jobs.publication_digest(association),
            ),
            call_timeout_ms=200,
            clock=lambda: 0.0,
        )
        assert prepared is not None
        active = reading_long_control.admit(
            self.config,
            self.key,
            provider="claude",
            label="Claude Code",
            job=prepared,
            permission=self.permission,
            now=100,
        )
        assert active is not None
        self.active = active
        self.addCleanup(reading.end_job, self.config, self.key)
        self.path = reading_long_markers.marker_path(self.config, active.job.id)

    def entry(self) -> Any:
        return store.find(store.load(self.config), "claude", self.sid)

    def module(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_finalize"))
        return importlib.import_module("compass_runtime.reading_long_finalize")

    def finalize(self, **changes: Any) -> Any:
        return self.module().withheld(
            self.config,
            self.state,
            **{
                "active": self.active,
                "reason": reading.WITHHELD_MODEL_FAILED,
                "now": 100,
                **changes,
            },
        )

    def reserve(self, ordinal: int = 1) -> None:
        header = reading_long_jobs.header(self.active.owner.live.prepared)
        assert header is not None
        req = request(
            job_id=self.active.job.id,
            ordinal=ordinal,
            max_evidence_passes=3,
            plan_sha256=reading_long_jobs.digest(header["plan"]),
            prompt_bytes=10,
            destination_sha256=header["destination_sha256"],
        )
        self.assertTrue(
            reading_long_markers.reserve(
                self.config, self.active.owner, request=req, now=100
            ).launch
        )
        self.assertTrue(
            reading_long_markers.settle(
                self.config,
                self.active.owner,
                observation={
                    "version": 1,
                    "ordinal": ordinal,
                    "kind": "evidence",
                    "diagnostic": None,
                },
                now=100,
            )
        )

    def seal(self) -> None:
        self.assertTrue(
            reading_long_markers.seal(self.config, self.active.owner, state="failed", now=100)
        )

    def test_zero_charges_acknowledges_retires_and_releases_without_count_or_slot_release(
        self,
    ) -> None:
        self.seal()
        result = self.finalize()
        self.assertTrue(result.acknowledged)
        self.assertTrue(result.retired)
        self.assertTrue(result.receipt_released)
        self.assertFalse(self.path.exists())
        self.assertNotIn("readings", self.entry())
        self.assertEqual([], self.entry()["long_receipts"])
        self.assertIs(self.active.job, reading.job(self.config, self.key))
        before = self.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(before, self.fixture.path.read_bytes())

    def test_two_actual_charges_count_one_job_even_after_pause(self) -> None:
        self.reserve(1)
        self.reserve(2)
        self.seal()
        policy.set_consent(self.config, False, now=100)
        inspected = reading_long_inspection.inspect(self.config, self.active.job.id, now=100)
        assert inspected.exact is not None
        self.assertEqual(2, inspected.exact.calls)
        result = self.finalize()
        self.assertTrue(result.receipt_released)
        self.assertEqual(1, self.entry()["readings"])
        self.assertEqual(1, store.published(self.entry())["reading_count"])
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(1, self.entry()["readings"])

    def test_active_and_pending_markers_never_publish_or_infer_owner_death(self) -> None:
        before = self.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        with (
            mock.patch.object(policy, "reserve_registered_pass", side_effect=Crash),
            self.assertRaises(Crash),
        ):
            self.reserve()
        marker = reading_long_markers.load(self.config, self.active.job.id)
        assert marker is not None
        self.assertEqual("pending", marker["passes"][0]["state"])
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertTrue(self.path.exists())

    def test_unknown_authoritative_accounting_leaves_terminal_marker_unresolved(self) -> None:
        self.reserve()
        self.seal()
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            db.execute("DELETE FROM long_pass_reservations")
            db.commit()
        before = self.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertTrue(self.path.exists())

    def test_unwritable_annotation_then_retry_counts_the_job_once(self) -> None:
        self.reserve()
        self.seal()
        with mock.patch.object(store, "save", return_value=False):
            result = self.finalize()
        self.assertFalse(result.acknowledged)
        self.assertFalse(result.retired)
        self.assertTrue(self.path.exists())
        self.assertNotIn("readings", self.entry())
        self.assertTrue(self.finalize().receipt_released)
        self.assertEqual(1, self.entry()["readings"])

    def test_ack_retirement_and_cleanup_failures_remain_distinct(self) -> None:
        self.seal()
        with mock.patch.object(reading_long_inspection, "_retire_locked", return_value=False):
            result = self.finalize()
        self.assertTrue(result.acknowledged)
        self.assertFalse(result.retired)
        self.assertFalse(result.receipt_released)
        self.assertTrue(self.path.exists())
        with mock.patch.object(
            reading_long_cleanup, "release_receipt", return_value=store.OUTCOME_UNWRITABLE
        ):
            result = self.finalize()
        self.assertTrue(result.acknowledged)
        self.assertTrue(result.retired)
        self.assertFalse(result.receipt_released)
        self.assertFalse(self.path.exists())
        self.assertEqual([self.active.job.id], self.entry()["long_receipts"])
        before = self.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(before, self.fixture.path.read_bytes())

    def test_crash_after_atomic_ack_retry_retires_without_counting_twice(self) -> None:
        self.module()
        self.reserve()
        self.seal()
        with (
            mock.patch.object(reading_long_inspection, "_retire_locked", side_effect=Crash),
            self.assertRaises(Crash),
        ):
            self.finalize()
        self.assertTrue(self.path.exists())
        self.assertEqual([self.active.job.id], self.entry()["long_receipts"])
        self.assertEqual(1, self.entry()["readings"])
        self.assertTrue(self.finalize().receipt_released)
        self.assertEqual(1, self.entry()["readings"])

    def test_foreign_owner_changed_target_and_unknown_reason_leave_marker_unresolved(self) -> None:
        self.seal()
        for active in (
            None,
            dataclasses.replace(
                self.active, owner=dataclasses.replace(self.active.owner, owner="f" * 32)
            ),
            dataclasses.replace(
                self.active, owner=dataclasses.replace(self.active.owner, process=object())
            ),
            dataclasses.replace(
                self.active, job=dataclasses.replace(self.active.job, sid="ffffffff")
            ),
        ):
            with self.subTest(active=active):
                self.assertFalse(self.finalize(active=active).acknowledged)
        self.assertFalse(self.finalize(reason="private prose").acknowledged)
        store.annotate(self.config, self.state, "claude", self.sid, goal="Changed", now=101)
        before = self.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertTrue(self.path.exists())

    def test_malformed_annotation_receipt_leaves_terminal_marker_unresolved(self) -> None:
        self.seal()
        raw = json.loads(self.fixture.path.read_text())
        next(item for item in raw["entries"] if item["sid"] == self.sid)["long_receipts"] = None
        self.fixture.path.write_text(json.dumps(raw))
        before = self.fixture.path.read_bytes()
        self.assertFalse(self.finalize().acknowledged)
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertTrue(self.path.exists())

    def test_unattributed_terminal_owner_has_no_annotation_destination(self) -> None:
        assert self.permission is not None
        prepared = policy.prepare_long_job(
            permission=self.permission, binding=binding(), call_timeout_ms=200, clock=lambda: 0.0
        )
        assert prepared is not None
        reading.end_job(self.config, self.key)
        active = reading_long_control.admit(
            self.config,
            self.key,
            provider="claude",
            label="Claude Code",
            job=prepared,
            permission=self.permission,
            now=100,
        )
        assert active is not None
        self.assertTrue(
            reading_long_markers.seal(self.config, active.owner, state="failed", now=100)
        )
        before = self.fixture.path.read_bytes()
        self.assertFalse(self.finalize(active=active).acknowledged)
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertIsNotNone(reading_long_markers.load(self.config, active.job.id))
