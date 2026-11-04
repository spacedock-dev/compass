"""Cancellation at registered charge commit rolls back receipts and spend together."""

from __future__ import annotations

import concurrent.futures
import contextlib
import inspect
import threading
import unittest
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_policy as policy
from compass_runtime import supervise

from . import test_reading_long_markers as marker_tests


class LongCancelCommitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = marker_tests.LongMarkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.owner = self.fixture.begin()
        self.cancelled = threading.Event()
        self.checks = 0

    def check(self) -> bool:
        self.checks += 1
        return self.cancelled.is_set()

    def reserve(self) -> Any:
        self.assertIn("cancelled", inspect.signature(markers.reserve).parameters)
        return markers.reserve(
            self.config,
            self.owner,
            request=self.fixture.request(self.owner),
            now=100,
            cancelled=self.check,
        )

    def assert_unspent(self, result: Any) -> None:
        self.assertEqual("cancelled", result.reason)
        self.assertFalse(result.launch)
        self.assertFalse(result.fresh_charge)
        self.assertIsNot(result.charged, True)
        self.assertEqual(1, self.checks)
        self.assertEqual(0, self.fixture.spends())
        slot = self.fixture.loaded(self.owner)["passes"][0]
        self.assertEqual("pending", slot["state"])
        self.assertIsNone(slot["charged"])
        proof = inspection.inspect(self.config, self.owner.live.prepared.job_id, now=100)
        self.assertEqual(inspection.Totals(0, 0, 0), proof.exact)
        self.assertTrue(proof.unsettled)

    def test_already_cancelled_rolls_back_prospective_receipt_and_spend(self) -> None:
        self.cancelled.set()
        self.assert_unspent(self.reserve())

    def test_cancellation_after_real_sqlite_lock_wait_is_unspent(self) -> None:
        assert runtime_io.sqlite_module is not None
        entered = threading.Event()
        original = policy._connect

        def connecting(*args: Any, **kwargs: Any) -> Any:
            db = original(*args, **kwargs)
            db.set_trace_callback(lambda sql: entered.set() if sql == "BEGIN IMMEDIATE" else None)
            return db

        # Check the new seam before starting a worker that must reach SQLite.
        self.assertIn("cancelled", inspect.signature(markers.reserve).parameters)
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config), isolation_level=None)
        ) as writer:
            writer.execute("BEGIN IMMEDIATE")
            with (
                concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool,
                mock.patch.object(policy, "_connect", side_effect=connecting),
            ):
                pending = pool.submit(self.reserve)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(0, self.checks)
                    self.cancelled.set()
                finally:
                    writer.execute("COMMIT")
                result = pending.result(timeout=5)
        self.assert_unspent(result)

    def test_cancellation_after_real_supervision_lock_wait_is_unspent(self) -> None:
        entered = threading.Event()
        original = supervise.admitting

        @contextlib.contextmanager
        def admitting() -> Any:
            entered.set()
            with original() as opened:
                yield opened

        self.assertIn("cancelled", inspect.signature(markers.reserve).parameters)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with mock.patch.object(supervise, "admitting", admitting), supervise._LOCK:
                pending = pool.submit(self.reserve)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(0, self.checks)
                    self.cancelled.set()
                finally:
                    entered.set()
            result = pending.result(timeout=5)
        self.assert_unspent(result)

    def test_fresh_success_checks_once_and_replay_cannot_check_or_charge_again(self) -> None:
        result = self.reserve()
        self.assertTrue(result.launch)
        self.assertTrue(result.fresh_charge)
        self.assertIs(result.charged, True)
        self.assertEqual(1, self.checks)
        self.assertEqual(1, self.fixture.spends())
        self.assertIn("cancelled", inspect.signature(policy.reserve_registered_pass).parameters)
        replay = policy.reserve_registered_pass(
            self.config,
            permission=self.owner.permission,
            job=self.owner.live,
            request=self.fixture.request(self.owner),
            now=100,
            cancelled=self.check,
        )
        self.assertEqual("already-reserved", replay.outcome)
        self.assertFalse(replay.launch)
        self.assertIs(replay.charged, True)
        self.assertEqual(1, self.checks)
        self.assertEqual(1, self.fixture.spends())

    def test_cancel_after_committed_charge_does_not_refund(self) -> None:
        original = markers._write

        def writing(path: Any, marker: Any) -> None:
            if marker["passes"][-1]["state"] == "charged":
                self.assertEqual(1, self.fixture.spends())
                self.cancelled.set()
            original(path, marker)

        with mock.patch.object(markers, "_write", side_effect=writing):
            result = self.reserve()
        self.assertTrue(self.cancelled.is_set())
        self.assertTrue(result.fresh_charge)
        self.assertIs(result.charged, True)
        self.assertEqual(1, self.checks)
        self.assertEqual(1, self.fixture.spends())
        proof = inspection.inspect(self.config, self.owner.live.prepared.job_id, now=100)
        assert proof.exact is not None
        self.assertEqual(1, proof.exact.calls)

    def test_explicit_none_preserves_default_registered_reservation(self) -> None:
        self.assertIn("cancelled", inspect.signature(markers.reserve).parameters)
        result = markers.reserve(
            self.config,
            self.owner,
            request=self.fixture.request(self.owner),
            now=100,
            cancelled=None,
        )
        self.assertTrue(result.launch)
        self.assertTrue(result.fresh_charge)
        self.assertEqual(0, self.checks)
        self.assertEqual(1, self.fixture.spends())
