"""Registered long jobs bind every slot and admit conservative allocations under one lock."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading_policy as policy
from compass_runtime import supervise

from .support import make_runtime
from .test_reading_pass_types import plan


def binding(**changes: Any) -> dict[str, Any]:
    declared = plan()
    declared.update(max_evidence_passes=3, max_calls=4)
    declared["limits"].update(
        prompt_bytes=100, input_bytes=300, reply_bytes=10, output_bytes=40, job_ms=1000
    )
    return {
        "started_at": 100.0,
        "plan": declared,
        "scope_sha256": "a" * 64,
        "target_sha256": "b" * 64,
        "destination_sha256": "c" * 64,
        "provider": "claude",
        "content": 6,
        **changes,
    }


class RegisteredLongJobTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(home.name), state_home=home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.permission = policy.capture_long_permission(self.config, now=100)
        self.clock = [0.0]
        self.live: dict[str, Any] = {}

    def prepare(self, supplied: Any = None, *, timeout: int = 200) -> Any:
        prepare: Any = getattr(policy, "prepare_long_job", None)
        self.assertTrue(callable(prepare), "prepare_long_job must exist")
        return prepare(
            permission=self.permission,
            binding=binding() if supplied is None else supplied,
            call_timeout_ms=timeout,
            clock=lambda: self.clock[0],
        )

    def register(self, job: Any, *, now: float = 100, permission: Any = None) -> Any:
        register: Any = getattr(policy, "register_long_job", None)
        self.assertTrue(callable(register))
        result = register(
            self.config,
            permission=self.permission if permission is None else permission,
            job=job,
            now=now,
        )
        if result.live is not None:
            self.live[job.job_id] = result.live
        return result

    def request(self, job: Any, ordinal: int = 1, **changes: Any) -> dict[str, Any]:
        header = json.loads(job.binding)
        declared = header["plan"]
        return {
            "version": 1,
            "job_id": job.job_id,
            "started_at": header["started_at"],
            "ordinal": ordinal,
            "kind": "reconciliation" if ordinal == declared["max_calls"] else "evidence",
            "max_evidence_passes": declared["max_evidence_passes"],
            "plan_sha256": hashlib.sha256(
                json.dumps(declared, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "prompt_sha256": "d" * 64,
            "prompt_bytes": 100,
            "destination_sha256": header["destination_sha256"],
            "provider": header["provider"],
            "content": header["content"],
            **changes,
        }

    def reserve(
        self, job: Any, ordinal: int = 1, *, now: float = 100, use: Any = None, **changes: Any
    ) -> Any:
        reserve: Any = getattr(policy, "reserve_registered_pass", None)
        self.assertTrue(callable(reserve))
        return reserve(
            self.config,
            permission=self.permission,
            job=self.live.get(job.job_id, job) if use is None else use,
            request=self.request(job, ordinal, **changes),
            now=now,
        )

    def sql(self, statement: str, parameters: tuple[Any, ...] = ()) -> list[Any]:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            result = db.execute(statement, parameters).fetchall()
            db.commit()
        return list(result)

    def blocked(self, result: Any, reason: str) -> None:
        self.assertFalse(result.launch)
        self.assertEqual(reason, result.status["reason"])

    def test_new_registration_and_replay_never_authorize_execution_or_reset_live_time(self) -> None:
        supplied = binding()
        job = self.prepare(supplied)
        original = job.binding
        supplied["plan"]["limits"]["input_bytes"] = 9999
        self.assertEqual(original, job.binding)
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest()[:32], job.job_id)
        fresh = self.register(job)
        self.assertEqual("registered", fresh.outcome)
        self.assertFalse(fresh.launch)
        self.clock[0] = 0.9
        replay = self.register(job)
        self.assertEqual("already-registered", replay.outcome)
        self.assertFalse(replay.launch)
        self.assertIsNone(replay.live)
        prepared_again = dataclasses.replace(job, started_monotonic=0.9)
        self.assertEqual("already-registered", self.register(prepared_again).outcome)
        self.blocked(self.reserve(job, use=prepared_again), "invalid-live-job")
        self.blocked(self.reserve(job), "job-deadline")
        self.assertEqual(0.0, job.started_monotonic)
        stored = self.sql("SELECT binding FROM long_job_registrations")[0][0]
        self.assertEqual(original, stored)
        self.assertNotIn("monotonic", stored)
        self.assertNotIn("timeout", stored)
        self.assertEqual([(0,)], self.sql("SELECT count(*) FROM spends"))

    def test_all_header_changes_with_old_id_are_refused_before_and_after_row_loss(self) -> None:
        job = self.prepare()
        self.register(job)
        changes = {
            "started_at": 101.0,
            "scope_sha256": "e" * 64,
            "target_sha256": "e" * 64,
            "destination_sha256": "e" * 64,
            "provider": "codex",
            "content": 5,
            "epoch": 9,
            "lineage": "e" * 32,
            "nonce": "e" * 32,
        }
        for lost in (False, True):
            if lost:
                self.sql("DELETE FROM long_job_registrations")
            for field, value in changes.items():
                with self.subTest(lost=lost, field=field):
                    header = json.loads(job.binding)
                    header[field] = value
                    altered = dataclasses.replace(
                        job, binding=json.dumps(header, sort_keys=True, separators=(",", ":"))
                    )
                    self.assertFalse(self.register(altered, now=101).launch)
                    self.assertNotIn(
                        self.register(altered, now=101).outcome,
                        ("registered", "already-registered"),
                    )
            if lost:
                self.blocked(self.register(job), "job-ledger-unknown")
        self.assertEqual([(0,)], self.sql("SELECT count(*) FROM spends"))

    def test_request_must_match_the_registered_plan_start_and_route_across_slots(self) -> None:
        job = self.prepare()
        self.blocked(self.reserve(job), "invalid-live-job")
        self.register(job)
        self.assertTrue(self.reserve(job).launch)
        for field, value in (
            ("started_at", 99.0),
            ("plan_sha256", "e" * 64),
            ("destination_sha256", "e" * 64),
            ("provider", "codex"),
            ("content", 5),
            ("max_evidence_passes", 2),
        ):
            with self.subTest(field=field):
                changes: dict[str, Any] = {field: value}
                self.blocked(self.reserve(job, 2, **changes), "job-binding-changed")
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))

    def test_prompt_and_aggregate_input_keep_reconciliation_allocation_and_count_repetition(
        self,
    ) -> None:
        job = self.prepare()
        self.register(job)
        self.blocked(self.reserve(job, prompt_bytes=101), "job-prompt-cap")
        self.assertTrue(self.reserve(job).launch)
        self.assertTrue(self.reserve(job, 2).launch)
        self.blocked(self.reserve(job, 3), "job-input-cap")
        self.assertTrue(self.reserve(job, 4, prompt_bytes=100).launch)
        self.assertEqual([(3,)], self.sql("SELECT count(*) FROM spends"))
        self.blocked(self.reserve(job), "already-reserved")
        self.blocked(self.reserve(job, prompt_bytes=99), "reservation-conflict")
        self.blocked(self.reserve(job, 3), "job-input-cap")

    def test_captured_reply_allocations_keep_one_for_reconciliation(self) -> None:
        supplied = binding()
        supplied["plan"]["limits"].update(input_bytes=1000, output_bytes=20)
        job = self.prepare(supplied)
        self.register(job)
        self.assertTrue(self.reserve(job).launch)
        self.blocked(self.reserve(job, 2), "job-output-cap")
        self.assertTrue(self.reserve(job, 4).launch)
        self.blocked(self.reserve(job, 2), "job-output-cap")

    def test_all_sixteen_evidence_slots_plus_one_reconciliation_have_exactly_seventeen_charges(
        self,
    ) -> None:
        supplied = binding(plan=plan())
        job = self.prepare(supplied)
        self.register(job)
        for ordinal in range(1, 18):
            self.assertTrue(self.reserve(job, ordinal).launch)
        self.blocked(self.reserve(job, 18), "invalid-long-request")
        self.blocked(self.reserve(job, 17), "already-reserved")
        self.assertEqual([(17,)], self.sql("SELECT count(*) FROM spends"))

    def test_concurrent_slots_race_for_last_job_allowance_in_same_sqlite_transaction(self) -> None:
        job = self.prepare()
        self.register(job)
        self.assertTrue(self.reserve(job).launch)
        barrier = threading.Barrier(2)

        def reserve(ordinal: int) -> Any:
            barrier.wait(timeout=30)
            return self.reserve(job, ordinal)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            answers = list(pool.map(reserve, (2, 3)))
        self.assertEqual(1, sum(answer.launch for answer in answers))
        self.assertEqual(
            ["", "job-input-cap"], sorted(answer.status["reason"] for answer in answers)
        )
        self.assertEqual([(2,)], self.sql("SELECT count(*) FROM spends"))

    def test_deleted_pass_receipt_never_produces_fabricated_remaining_allowance(self) -> None:
        job = self.prepare()
        self.register(job)
        self.reserve(job)
        self.sql("DELETE FROM long_pass_reservations")
        self.blocked(self.reserve(job, 2), "pass-ledger-unknown")
        self.blocked(self.register(job), "pass-ledger-unknown")
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))

    def test_pruned_or_missing_registration_cannot_reuse_immutable_identity(self) -> None:
        job = self.prepare()
        self.register(job)
        later = 100 + policy.JOB_LEDGER_SEC
        self.blocked(self.register(job, now=later), "job-ledger-unknown")
        self.assertEqual([], self.sql("SELECT * FROM long_job_registrations"))
        header = json.loads(job.binding)
        header["started_at"] = later + 1
        changed = dataclasses.replace(
            job, binding=json.dumps(header, sort_keys=True, separators=(",", ":"))
        )
        self.blocked(self.register(changed, now=later + 1), "invalid-long-job")
        self.blocked(self.register(job), "job-ledger-unknown")
        self.sql("DROP TABLE long_job_registrations")
        self.blocked(self.register(job), "store-unavailable")

    def test_pause_and_store_recreation_cannot_rebind_old_job_to_fresh_permission(self) -> None:
        job = self.prepare()
        self.register(job)
        policy.set_consent(self.config, False, now=100)
        policy.resume(self.config, now=100)
        self.blocked(self.reserve(job), "permission-changed")
        self.permission = policy.capture_long_permission(self.config, now=100)
        self.blocked(self.register(job), "job-binding-changed")
        policy.store_path(self.config).unlink()
        self.blocked(self.reserve(job), "permission-changed")

    def test_live_clock_requires_full_timeout_fit_and_refuses_backwards_or_recreated_context(
        self,
    ) -> None:
        job = self.prepare()
        self.register(job)
        self.clock[0] = -1
        self.blocked(self.reserve(job), "job-clock-invalid")
        self.clock[0] = 0.8
        self.assertTrue(self.reserve(job).launch)
        self.clock[0] = 0.801
        self.blocked(self.reserve(job, 2), "job-deadline")
        self.blocked(
            self.reserve(job, 2, use=dataclasses.replace(self.live[job.job_id], process=object())),
            "invalid-live-job",
        )

    def test_deadline_is_rechecked_after_supervision_lock_wait(self) -> None:
        job = self.prepare()
        self.register(job)
        entered = threading.Event()
        original = supervise.admitting

        @contextlib.contextmanager
        def admitting() -> Any:
            entered.set()
            with original() as opened:
                yield opened

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with mock.patch.object(supervise, "admitting", admitting), supervise._LOCK:
                pending = pool.submit(self.reserve, job)
                self.assertTrue(entered.wait(30))
                self.clock[0] = 0.9
            self.blocked(pending.result(timeout=30), "job-deadline")
        self.assertEqual([(0,)], self.sql("SELECT count(*) FROM spends"))
        self.assertEqual([], self.sql("SELECT * FROM long_pass_reservations"))

    def test_deadline_is_rechecked_after_real_sqlite_wait_before_any_charge(self) -> None:
        job = self.prepare()
        self.register(job)
        assert runtime_io.sqlite_module is not None
        entered = threading.Event()
        original = policy._connect

        def connecting(*args: Any, **kwargs: Any) -> Any:
            db = original(*args, **kwargs)
            db.set_trace_callback(lambda sql: entered.set() if sql == "BEGIN IMMEDIATE" else None)
            return db

        with contextlib.closing(
            runtime_io.sqlite_module.connect(
                policy.store_path(self.config),
                isolation_level=None,
            )
        ) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
                mock.patch.object(policy, "_connect", side_effect=connecting),
            ):
                pending = pool.submit(self.reserve, job)
                try:
                    self.assertTrue(entered.wait(30))
                    self.clock[0] = 0.9
                finally:
                    writer.execute("COMMIT")
                self.blocked(pending.result(timeout=30), "job-deadline")
        self.assertEqual([(0,)], self.sql("SELECT count(*) FROM spends"))
        self.assertEqual([], self.sql("SELECT * FROM long_pass_reservations"))

    def test_declared_source_limits_are_bound_but_not_claimed_as_enforced_usage(self) -> None:
        supplied = binding()
        supplied["plan"]["limits"].update(
            source_bytes=1, retained_bytes=1, source_pages=1, retained_units=1, prepare_ms=1
        )
        job = self.prepare(supplied)
        self.assertEqual("registered", self.register(job).outcome)
        self.assertTrue(self.reserve(job).launch)
        for invalid in ({}, {**binding(), "source_text": "private words"}):
            self.assertIsNone(self.prepare(invalid))
        self.assertIsNone(self.prepare(timeout=True))
