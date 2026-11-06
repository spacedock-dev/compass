"""Composite pass receipts authorize one launch and never infer a refund from absence."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
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

# How long a test waits for a step that happens at once on an idle runner: a busy runner
# is slower, not red.
WAIT_SEC = 30.0


def request(**changes: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "job_id": "a" * 32,
        "started_at": 100.0,
        "ordinal": 1,
        "kind": "evidence",
        "max_evidence_passes": 16,
        "plan_sha256": "b" * 64,
        "prompt_sha256": "c" * 64,
        "prompt_bytes": 123,
        "destination_sha256": "d" * 64,
        "provider": "claude",
        "content": 6,
        **changes,
    }


class LongReservationTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(home.name), state_home=home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.permission = policy.capture_long_permission(self.config, now=100.0)
        self.assertIsNotNone(self.permission)

    def reserve(self, value: Any = None, *, now: float = 100.0, **kwargs: Any) -> Any:
        reserve: Any = getattr(policy, "reserve_long_pass", None)
        self.assertTrue(callable(reserve), "reserve_long_pass must exist")
        return reserve(
            self.config,
            permission=kwargs.pop("permission", self.permission),
            request=request() if value is None else value,
            now=now,
            **kwargs,
        )

    def sql(self, statement: str, values: tuple[Any, ...] = ()) -> list[Any]:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            result = db.execute(statement, values).fetchall()
            db.commit()
        return list(result)

    def assert_blocked(self, result: Any, reason: str, *, charged: Any = None) -> None:
        self.assertFalse(result.launch)
        self.assertNotEqual("reserved", result.outcome)
        self.assertEqual(reason, result.status["reason"])
        self.assertIs(charged, result.charged)

    def test_fresh_and_identical_replay_are_distinct_with_one_durable_charge(self) -> None:
        supplied = request()
        fresh = self.reserve(supplied)
        self.assertEqual("reserved", fresh.outcome)
        self.assertTrue(fresh.launch)
        self.assertIs(True, fresh.charged)
        self.assertEqual("", fresh.status["reason"])
        self.assertEqual(1, fresh.status["used"])
        supplied["prompt_bytes"] = 999
        replay = self.reserve()
        self.assertEqual("already-reserved", replay.outcome)
        self.assert_blocked(replay, "already-reserved", charged=True)
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM long_pass_reservations"))
        stored = self.sql("SELECT binding FROM long_pass_reservations")[0][0]
        self.assertEqual(request(), json.loads(stored))
        self.assertEqual(set(policy.status(self.config, now=100)), set(fresh.status))
        # No single-job receipt may misrepresent this composite pass ledger.
        self.assertEqual([], self.sql("SELECT * FROM spend_jobs"))

    def test_concurrent_sqlite_connections_authorize_exactly_one_launch(self) -> None:
        self.assertTrue(callable(getattr(policy, "reserve_long_pass", None)))
        barrier = threading.Barrier(8)

        def reserve_once(_: int) -> Any:
            barrier.wait(WAIT_SEC)
            return self.reserve()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(reserve_once, range(8)))
        self.assertEqual(1, sum(result.launch for result in results))
        self.assertEqual(7, sum(result.outcome == "already-reserved" for result in results))
        self.assertTrue(all(result.charged is True for result in results))
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))

    def test_any_binding_conflict_refuses_same_key_without_a_second_charge(self) -> None:
        self.reserve()
        for field, value in (
            ("started_at", 99.0),
            ("prompt_bytes", 124),
            ("prompt_sha256", "e" * 64),
            ("destination_sha256", "e" * 64),
            ("plan_sha256", "e" * 64),
            ("provider", "codex"),
            ("content", 5),
            ("max_evidence_passes", 15),
        ):
            with self.subTest(field=field):
                result = self.reserve(request(**{field: value}))
                self.assertEqual("conflict", result.outcome)
                self.assert_blocked(result, "reservation-conflict", charged=True)
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))

    def test_planned_reconciliation_slot_is_not_actual_call_count(self) -> None:
        self.assertTrue(self.reserve().launch)
        reconciled = self.reserve(request(ordinal=17, kind="reconciliation"))
        self.assertTrue(reconciled.launch)
        self.assertEqual(2, reconciled.status["used"])
        self.assert_blocked(
            self.reserve(request(ordinal=2, kind="reconciliation")), "invalid-long-request"
        )
        self.assert_blocked(self.reserve(request(ordinal=17)), "invalid-long-request")
        self.assertTrue(
            self.reserve(
                request(job_id="e" * 32, max_evidence_passes=1, ordinal=2, kind="reconciliation")
            ).launch
        )

    def test_closed_wordfree_request_and_mandatory_permission_fail_closed(self) -> None:
        invalid: Any
        changes = (
            ("job_id", "user words"),
            ("job_id", "a" * 33),
            ("ordinal", True),
            ("ordinal", 0),
            ("ordinal", 18),
            ("max_evidence_passes", 17),
            ("max_evidence_passes", False),
            ("kind", "retry"),
            ("version", True),
            ("prompt_bytes", 0),
            ("prompt_bytes", True),
            ("prompt_bytes", 2**53),
            ("prompt_sha256", "user words"),
            ("plan_sha256", "B" * 64),
            ("destination_sha256", None),
            ("started_at", True),
            ("started_at", float("nan")),
            ("started_at", 101.0),
            ("content", True),
            ("content", 2),
            ("provider", "other"),
        )
        for field, invalid in changes:
            with self.subTest(field=field, invalid=invalid):
                self.assert_blocked(
                    self.reserve(request(**{field: invalid})), "invalid-long-request"
                )
        for invalid in ({}, [], {**request(), "prompt": "private text"}):
            self.assert_blocked(self.reserve(invalid), "invalid-long-request")
        for field in request():
            value = request()
            del value[field]
            self.assert_blocked(self.reserve(value), "invalid-long-request")
        self.assert_blocked(self.reserve(permission=None), "permission-changed")
        self.assertEqual(0, policy.status(self.config, now=100)["used"])

    def test_pause_resume_and_recreated_store_refuse_old_permission_without_refunding(self) -> None:
        self.reserve()
        policy.set_consent(self.config, False, now=100)
        self.assert_blocked(self.reserve(), "model-calls-paused")
        policy.resume(self.config, now=100)
        self.assert_blocked(self.reserve(), "permission-changed")
        self.assertEqual(1, policy.status(self.config, now=100)["used"])
        policy.store_path(self.config).unlink()
        self.assert_blocked(self.reserve(), "permission-changed")
        self.assertEqual(0, policy.status(self.config, now=100)["used"])

    def test_same_global_cap_and_shutdown_barrier_apply_to_fresh_pass_only(self) -> None:
        for _ in range(99):
            policy.reserve(self.config, now=100)
        self.assertTrue(self.reserve().launch)
        self.assert_blocked(self.reserve(), "already-reserved", charged=True)
        self.assert_blocked(self.reserve(request(ordinal=2)), "daily-cap")
        self.assertEqual([(100,)], self.sql("SELECT count(*) FROM spends"))
        self.sql("DELETE FROM spends")
        supervise._SHUTDOWN.set()
        self.assert_blocked(self.reserve(request(ordinal=2)), "stopping")
        self.assertEqual([(0,)], self.sql("SELECT count(*) FROM spends"))
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM long_pass_reservations"))

    def test_legacy_permission_and_spend_writes_and_permission_only_api_keep_working(self) -> None:
        policy.store_path(self.config).unlink()
        self.sql("CREATE TABLE permission (id INTEGER PRIMARY KEY, allowed INTEGER)")
        self.sql("CREATE TABLE spends (at REAL NOT NULL)")
        self.sql("INSERT INTO spends VALUES (100.0)")
        self.permission = policy.capture_long_permission(self.config, now=100)
        self.assertTrue(self.reserve().launch)
        self.sql("INSERT INTO spends VALUES (100.0)")
        self.sql("INSERT OR REPLACE INTO permission VALUES (1, 0)")
        self.sql("INSERT OR REPLACE INTO permission VALUES (1, 1)")
        self.assert_blocked(self.reserve(request(ordinal=2)), "permission-changed")
        fresh = policy.capture_long_permission(self.config, now=100)
        assert fresh is not None
        self.assertEqual("", policy.reserve_long(self.config, permission=fresh, now=100)["reason"])
        self.assertEqual(4, policy.status(self.config, now=100)["used"])

    def test_deleted_receipt_at_equal_timestamp_is_unknown_and_cannot_authorize_again(self) -> None:
        self.reserve()
        self.sql("DELETE FROM long_pass_reservations")
        self.assertEqual([(100.0,)], self.sql("SELECT pass_ledger_since FROM long_permission"))
        self.assert_blocked(self.reserve(), "pass-ledger-unknown")
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))
        # A distinct later job may start; an old job must not change its start to evade this fence.
        self.assertTrue(self.reserve(request(job_id="e" * 32, started_at=101.0), now=101).launch)

    def test_retention_prune_and_backwards_clock_never_reauthorize_old_keys(self) -> None:
        self.reserve()
        later = 100 + policy.JOB_LEDGER_SEC
        self.assert_blocked(self.reserve(now=later), "pass-ledger-unknown")
        self.assertEqual([], self.sql("SELECT * FROM long_pass_reservations"))
        self.assert_blocked(self.reserve(now=100), "pass-ledger-unknown")
        self.assertEqual([], self.sql("SELECT * FROM spends"))

    def test_missing_table_or_corrupt_watermark_never_recreates_an_empty_ledger(self) -> None:
        self.reserve()
        self.sql("DROP TABLE long_pass_reservations")
        self.assert_blocked(self.reserve(), "store-unavailable")
        self.assertEqual(
            [], self.sql("SELECT name FROM sqlite_master WHERE name='long_pass_reservations'")
        )
        self.sql("UPDATE long_permission SET pass_ledger_since='not a timestamp'")
        self.assert_blocked(self.reserve(), "store-unavailable")
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))

    def test_permission_is_checked_after_real_lock_wait_and_no_receipt_escapes_rollback(
        self,
    ) -> None:
        self.assertTrue(callable(getattr(policy, "reserve_long_pass", None)))
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
                pending = pool.submit(self.reserve)
                try:
                    self.assertTrue(entered.wait(WAIT_SEC))
                    writer.execute("INSERT OR REPLACE INTO permission VALUES (1, 0)")
                    writer.execute("DELETE FROM permission WHERE allowed=0")
                    writer.execute("DELETE FROM provider_permission WHERE allowed=0")
                finally:
                    writer.execute("COMMIT")
                self.assert_blocked(pending.result(timeout=WAIT_SEC), "permission-changed")
        self.assertEqual([(0,)], self.sql("SELECT count(*) FROM spends"))

    def test_disabled_or_corrupt_store_is_unknown_not_a_zero_charge(self) -> None:
        self.config = dataclasses.replace(self.config, model_calls_disabled=True)
        self.assert_blocked(self.reserve(), "run-disabled")
        self.config = dataclasses.replace(self.config, model_calls_disabled=False)
        policy.store_path(self.config).write_bytes(b"not SQLite")
        self.assert_blocked(self.reserve(), "store-unavailable")
