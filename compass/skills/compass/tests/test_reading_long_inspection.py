"""Read-only accounting inspection and explicit acknowledged retirement."""

from __future__ import annotations

import concurrent.futures
import contextlib
import importlib
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading_long_jobs, supervise
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_policy as policy

from .support import make_runtime
from .test_reading_long_jobs import binding
from .test_reading_long_reservation import request


class Crash(BaseException):
    pass


class LongInspectionTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(home.name), state_home=home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        permission = policy.capture_long_permission(self.config, now=100)
        assert permission is not None
        self.permission = permission
        prepared = policy.prepare_long_job(
            permission=permission, binding=binding(), call_timeout_ms=200, clock=lambda: 0.0
        )
        assert prepared is not None
        self.owner = markers.begin(self.config, permission=permission, job=prepared, now=100)
        assert self.owner is not None
        self.job_id = prepared.job_id
        self.path = markers.marker_path(self.config, self.job_id)

    def module(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_inspection"))
        return importlib.import_module("compass_runtime.reading_long_inspection")

    def inspect(self, *, now: float = 100) -> Any:
        return self.module().inspect(self.config, self.job_id, now=now)

    def request(self, ordinal: int = 1) -> dict[str, Any]:
        assert self.owner is not None
        header = json.loads(self.owner.live.prepared.binding)
        return request(
            job_id=self.job_id,
            ordinal=ordinal,
            kind="reconciliation" if ordinal == 4 else "evidence",
            max_evidence_passes=3,
            plan_sha256=reading_long_jobs.digest(header["plan"]),
            prompt_bytes=10,
            destination_sha256=header["destination_sha256"],
        )

    def reserve(self, ordinal: int = 1) -> Any:
        assert self.owner is not None
        return markers.reserve(self.config, self.owner, request=self.request(ordinal), now=100)

    def settle(self, ordinal: int = 1) -> None:
        assert self.owner is not None
        self.assertTrue(
            markers.settle(
                self.config,
                self.owner,
                observation={
                    "version": 1,
                    "ordinal": ordinal,
                    "kind": "evidence",
                    "diagnostic": None,
                },
                now=100,
            )
        )

    def seal(self, state: str = "completed") -> None:
        assert self.owner is not None
        self.assertTrue(markers.seal(self.config, self.owner, state=state, now=100))

    def sql(self, statement: str, values: tuple[Any, ...] = ()) -> list[Any]:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            result = db.execute(statement, values).fetchall()
            db.commit()
        return list(result)

    def tree(self) -> dict[str, bytes]:
        return {
            path.name: path.read_bytes()
            for path in self.config.state_dir.rglob("*")
            if path.is_file()
        }

    def test_healthy_active_job_has_proven_zero_as_of_snapshot_but_is_unsettled(self) -> None:
        result = self.inspect()
        self.assertEqual("exact", result.accounting)
        self.assertEqual(
            (0, 0, 0), (result.exact.calls, result.exact.prompt_bytes, result.exact.reply_bytes)
        )
        self.assertEqual(result.exact, result.minimum)
        self.assertEqual("active", result.marker_state)
        self.assertTrue(result.unsettled)
        self.assertFalse(self.module().retire(self.config, result, acknowledged=True, now=100))
        self.assertTrue(self.path.exists())

    def test_pending_crash_before_charge_is_exact_zero_without_interruption_or_launch(self) -> None:
        self.module()
        with (
            mock.patch.object(policy, "reserve_registered_pass", side_effect=Crash),
            self.assertRaises(Crash),
        ):
            self.reserve()
        result = self.inspect()
        self.assertEqual(0, result.exact.calls)
        self.assertTrue(result.unsettled)
        self.assertEqual("active", result.marker_state)
        marker = markers.load(self.config, self.job_id)
        assert marker is not None
        self.assertEqual("pending", marker["passes"][0]["state"])

    def test_pending_crash_after_commit_counts_receipt_not_marker_flag_or_ordinal(self) -> None:
        self.module()
        original = policy.reserve_registered_pass

        def committed(*args: Any, **kwargs: Any) -> Any:
            original(*args, **kwargs)
            raise Crash

        with (
            mock.patch.object(policy, "reserve_registered_pass", side_effect=committed),
            self.assertRaises(Crash),
        ):
            self.reserve(4)
        result = self.inspect()
        self.assertEqual(
            (1, 10, 10), (result.exact.calls, result.exact.prompt_bytes, result.exact.reply_bytes)
        )
        marker = markers.load(self.config, self.job_id)
        assert marker is not None
        self.assertIsNone(marker["passes"][0]["charged"])
        self.assertEqual(4, marker["passes"][0]["request"]["ordinal"])
        self.assertTrue(result.unsettled)

    def test_pause_revokes_authority_without_erasing_known_historical_charge(self) -> None:
        self.module()
        self.reserve()
        policy.set_consent(self.config, False, now=100)
        result = self.inspect()
        self.assertEqual(1, result.exact.calls)
        self.assertEqual("exact", result.accounting)
        self.assertFalse(self.reserve(2).launch)

    def test_deleted_receipt_leaves_only_authoritative_minimum_and_never_zero_exact(self) -> None:
        self.module()
        self.reserve()
        self.settle()
        self.reserve(2)
        self.sql("DELETE FROM long_pass_reservations WHERE ordinal=1")
        result = self.inspect()
        self.assertIsNone(result.exact)
        self.assertEqual("minimum", result.accounting)
        self.assertEqual(
            (1, 10, 10),
            (result.minimum.calls, result.minimum.prompt_bytes, result.minimum.reply_bytes),
        )
        self.sql("DELETE FROM long_pass_reservations")
        missing = self.inspect()
        self.assertIsNone(missing.exact)
        self.assertIsNone(missing.minimum)

    def test_old_then_pruned_registration_and_receipts_remain_unknown_without_read_pruning(
        self,
    ) -> None:
        self.module()
        self.reserve()
        later = 100 + policy.JOB_LEDGER_SEC
        before = self.tree()
        old = self.inspect(now=later)
        self.assertIsNone(old.exact)
        self.assertEqual(1, old.minimum.calls)
        self.assertEqual(before, self.tree())
        prepared = policy.prepare_long_job(
            permission=self.permission,
            binding=binding(started_at=later + 1),
            call_timeout_ms=200,
            clock=lambda: 0.0,
        )
        policy.register_long_job(
            self.config, permission=self.permission, job=prepared, now=later + 1
        )
        self.assertEqual([], self.sql("SELECT * FROM long_pass_reservations"))
        result = self.inspect(now=later + 1)
        self.assertIsNone(result.exact)
        self.assertIsNone(result.minimum)

    def test_missing_recreated_and_corrupt_database_never_turn_marker_charge_into_zero(
        self,
    ) -> None:
        self.module()
        self.reserve()
        path = policy.store_path(self.config)
        path.unlink()
        self.assertIsNone(self.inspect().exact)
        self.assertFalse(path.exists())
        policy.capture_long_permission(self.config, now=100)
        recreated = self.inspect()
        self.assertIsNone(recreated.exact)
        self.assertIsNone(recreated.minimum)
        path.write_bytes(b"corrupt database")
        self.assertEqual("unknown", self.inspect().accounting)
        self.assertEqual(b"corrupt database", path.read_bytes())

    def test_inconsistent_registration_or_receipt_binding_never_claims_complete_totals(
        self,
    ) -> None:
        self.module()
        self.reserve()
        original = self.sql("SELECT binding FROM long_pass_reservations")[0][0]
        value = json.loads(original)
        value["plan_sha256"] = "e" * 64
        self.sql("UPDATE long_pass_reservations SET binding=?", (json.dumps(value),))
        self.assertIsNone(self.inspect().exact)
        self.sql("UPDATE long_pass_reservations SET binding=?", (original,))
        self.sql("UPDATE long_job_registrations SET binding='{}'")
        self.assertIsNone(self.inspect().exact)
        self.assertIsNone(self.inspect().minimum)

    def test_reads_create_write_prune_and_authorize_nothing(self) -> None:
        module = self.module()
        self.reserve()
        before = self.tree()
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(policy, "reserve_registered_pass", side_effect=AssertionError),
            mock.patch.object(reading_long_jobs, "prepare", side_effect=AssertionError),
            mock.patch.object(reading_long_jobs, "activate", side_effect=AssertionError),
            mock.patch.object(markers, "_write", side_effect=AssertionError),
        ):
            first = self.inspect()
            second = self.inspect()
            absent = module.inspect(self.config, "e" * 32, now=100)
        self.assertEqual(first, second)
        self.assertIsNone(absent.exact)
        self.assertEqual(before, self.tree())

    def test_one_readonly_sqlite_snapshot_cannot_mix_concurrent_committed_rows(self) -> None:
        module = self.module()
        self.sql("PRAGMA journal_mode=WAL")
        entered, release = threading.Event(), threading.Event()
        original = module._connect

        def connect(*args: Any, **kwargs: Any) -> Any:
            db = original(*args, **kwargs)

            def trace(sql: str) -> None:
                if "FROM long_job_registrations" in sql:
                    entered.set()
                    release.wait(30)

            db.set_trace_callback(trace)
            return db

        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as writer:
            # Keep a genuine WAL writer/sidecars open. Read-only inspection
            # must not create missing WAL support files itself.
            writer.execute("SELECT count(*) FROM long_permission").fetchone()
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
                mock.patch.object(module, "_connect", side_effect=connect),
            ):
                pending = pool.submit(self.inspect)
                try:
                    self.assertTrue(entered.wait(30))
                    writer.execute(
                        "INSERT INTO long_pass_reservations VALUES (?, ?, ?, ?)",
                        (self.job_id, 1, json.dumps(self.request()), 100.0),
                    )
                    writer.execute("INSERT INTO spends VALUES (100.0)")
                    writer.commit()
                finally:
                    release.set()
                self.assertEqual(0, pending.result(timeout=30).exact.calls)
            self.assertEqual(1, self.inspect().exact.calls)

    def test_retirement_requires_explicit_ack_terminal_state_and_complete_accounting(self) -> None:
        module = self.module()
        self.reserve()
        self.settle()
        self.seal()
        result = self.inspect()
        self.assertFalse(module.retire(self.config, result, acknowledged=False, now=100))
        self.assertFalse(module.retire(self.config, result, acknowledged=1, now=100))
        self.assertTrue(self.path.exists())
        self.assertTrue(module.retire(self.config, result, acknowledged=True, now=100))
        self.assertFalse(self.path.exists())
        self.assertEqual([(1,)], self.sql("SELECT count(*) FROM spends"))
        self.assertIsNone(self.inspect().exact)

    def test_known_zero_terminal_outcome_can_retire_without_marker_charged_true(self) -> None:
        module = self.module()
        with (
            mock.patch.object(policy, "reserve_registered_pass", side_effect=Crash),
            self.assertRaises(Crash),
        ):
            self.reserve()
        self.settle()
        self.seal("cancelled")
        marker = markers.load(self.config, self.job_id)
        assert marker is not None
        self.assertIsNone(marker["passes"][0]["charged"])
        result = self.inspect()
        self.assertEqual(0, result.exact.calls)
        next_job = policy.prepare_long_job(
            permission=self.permission, binding=binding(), call_timeout_ms=200, clock=lambda: 0.0
        )
        assert next_job is not None
        with mock.patch.object(markers, "MAX_MARKERS", 1):
            self.assertIsNone(
                markers.begin(self.config, permission=self.permission, job=next_job, now=100)
            )
            self.assertTrue(module.retire(self.config, result, acknowledged=True, now=100))
            self.assertIsNotNone(
                markers.begin(self.config, permission=self.permission, job=next_job, now=100)
            )

    def test_retirement_rechecks_unchanged_marker_and_ledger_under_lock(self) -> None:
        module = self.module()
        self.reserve()
        self.settle()
        self.seal()
        before = self.inspect()
        marker = json.loads(self.path.read_text())
        marker["updated_at"] = 101
        self.path.write_text(json.dumps(marker))
        self.assertFalse(module.retire(self.config, before, acknowledged=True, now=101))
        updated = self.inspect(now=101)
        self.sql("UPDATE long_pass_reservations SET at=101")
        self.assertFalse(module.retire(self.config, updated, acknowledged=True, now=101))
        self.sql("DELETE FROM long_pass_reservations")
        unknown = self.inspect(now=101)
        self.assertIsNone(unknown.exact)
        self.assertFalse(module.retire(self.config, unknown, acknowledged=True, now=101))
        self.assertTrue(self.path.exists())
