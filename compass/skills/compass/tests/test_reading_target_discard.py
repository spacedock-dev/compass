"""Explicit retirement needs positively superseded intent, held through deletion."""

from __future__ import annotations

import concurrent.futures
import contextlib
import json
import threading
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import reading
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_recovery as recovery
from compass_runtime import reading_policy as policy

from . import test_reading_recovered_publication as recovery_tests
from .test_reading_long_finalize import Crash


class TargetDiscardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = recovery_tests.RecoveredPublicationTest()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.config, self.state = self.base.config, self.base.state
        self.fixture = self.base.fixture
        self.path, self.job_id = self.base.path, self.base.job_id

    def edit(self) -> None:
        self.assertEqual(
            store.OUTCOME_STORED,
            store.annotate(
                self.config, self.state, "claude", self.fixture.sid, goal="New words", now=103
            ),
        )

    def discard(self, **changes: Any) -> Any:
        function: Any = getattr(recovery, "discard_terminal", None)
        self.assertTrue(callable(function), "discard needs explicit held target invalidation proof")
        return function(
            self.config,
            self.state,
            **{
                "job_id": self.job_id,
                "now": 104,
                "alive": lambda _: False,
                "process_exists": lambda _: False,
                **changes,
            },
        )

    def test_current_target_is_not_discard_and_newer_revision_retires_without_mutation(
        self,
    ) -> None:
        self.base.die()
        self.assertFalse(self.discard().retired)
        self.edit()
        before = self.fixture.fixture.path.read_bytes()
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(store, "capture_long_target", side_effect=AssertionError),
            mock.patch.object(store, "record_withheld", side_effect=AssertionError),
        ):
            outcome = self.discard()
        self.assertTrue(outcome.acknowledged and outcome.retired and outcome.receipt_released)
        self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        self.assertFalse(self.discard().retired)

    def test_spent_invalidated_job_is_not_counted_against_new_intent(self) -> None:
        self.fixture.reserve()
        self.base.die()
        self.edit()
        before = store.published(self.fixture.entry())
        self.assertTrue(self.discard().retired)
        self.assertEqual(before, store.published(self.fixture.entry()))
        self.assertNotIn("readings", self.fixture.entry())

    def test_clear_and_unidentified_recreation_are_unknown_until_new_identity_is_proved(
        self,
    ) -> None:
        self.base.die()
        store.clear(self.config, self.state, "claude", self.fixture.sid)
        self.assertFalse(self.discard().retired)
        store.annotate(
            self.config, self.state, "claude", self.fixture.sid, goal="Recreated", now=103
        )
        self.assertFalse(self.discard().retired)
        newer = store.capture_long_target(self.config, self.state, "claude", self.fixture.sid)
        assert newer is not None and self.fixture.target is not None
        self.assertNotEqual(self.fixture.target.incarnation, newer.incarnation)
        before = self.fixture.fixture.path.read_bytes()
        outcome = self.discard()
        self.assertTrue(outcome.acknowledged and outcome.retired)
        self.assertFalse(outcome.receipt_released)  # Cleanup never touches the new incarnation.
        self.assertEqual(before, self.fixture.fixture.path.read_bytes())

    def test_missing_unreadable_malformed_and_rolled_back_identity_never_prove_discard(
        self,
    ) -> None:
        self.base.die()
        path = self.fixture.fixture.path
        saved = path.read_bytes()
        path.unlink()
        self.assertFalse(self.discard().retired)
        for content in ("{broken", "{}"):
            path.write_text(content)
            self.assertFalse(self.discard().retired)
        raw = json.loads(saved)
        entry = next(row for row in raw["entries"] if row["sid"] == self.fixture.sid)
        entry["long_incarnation"] = None
        path.write_text(json.dumps(raw))
        self.assertFalse(self.discard().retired)
        path.write_bytes(saved)
        self.assertFalse(self.discard().retired)
        self.assertTrue(self.path.exists())

    def test_annotation_proof_lock_is_held_through_exact_marker_retirement(self) -> None:
        self.base.die()
        self.edit()
        locks = store._store_locks
        retire = inspection._retire_locked
        waiting = threading.Event()
        futures = []

        @contextlib.contextmanager
        def traced(*args: Any, **kwargs: Any) -> Any:
            waiting.set()
            with locks(*args, **kwargs) as held:
                yield held

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:

            def held(*args: Any, **kwargs: Any) -> bool:
                with mock.patch.object(store, "_store_locks", traced):
                    future = pool.submit(
                        store.annotate,
                        self.config,
                        self.state,
                        "claude",
                        self.fixture.sid,
                        goal="Later edit",
                        now=105,
                    )
                    futures.append(future)
                    self.assertTrue(waiting.wait(2))
                    self.assertFalse(future.done())
                    return retire(*args, **kwargs)

            with mock.patch.object(inspection, "_retire_locked", side_effect=held):
                self.assertTrue(self.discard().retired)
            self.assertEqual(store.OUTCOME_STORED, futures[0].result(timeout=5))

    def test_owner_snapshot_and_accounting_constraints_still_apply(self) -> None:
        self.edit()
        self.assertFalse(self.discard().retired)  # Active and current process.
        self.base.die()
        self.assertFalse(self.discard(alive=lambda _: True).retired)
        self.assertFalse(self.discard(process_exists=mock.Mock(side_effect=OSError)).retired)
        reading.start_job(
            self.config,
            self.fixture.key,
            provider="claude",
            label="Claude",
            now=103,
            prepared_job_id=self.job_id,
        )
        self.assertFalse(self.discard().retired)
        reading.end_job(self.config, self.fixture.key)
        policy.store_path(self.config).unlink()
        self.assertFalse(self.discard().retired)
        self.assertTrue(self.path.exists())

    def test_crash_before_retirement_and_marker_write_failure_preserve_retry(self) -> None:
        self.base.die()
        self.edit()
        before = self.fixture.fixture.path.read_bytes()
        with (
            mock.patch.object(inspection, "_retire_locked", side_effect=Crash),
            self.assertRaises(Crash),
        ):
            self.discard()
        with mock.patch.object(inspection, "_retire_locked", side_effect=OSError):
            self.assertFalse(self.discard().retired)
        self.assertTrue(self.path.exists())
        self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        self.assertTrue(self.discard().retired)

    def test_real_receipt_release_occurs_only_after_actual_retirement(self) -> None:
        self.base.die()
        with (
            mock.patch.object(inspection, "_retire_locked", side_effect=Crash),
            self.assertRaises(Crash),
        ):
            self.base.publish()
        self.assertIn(self.job_id, self.fixture.entry()["long_receipts"])
        self.edit()
        before = store.published(self.fixture.entry())
        release = store.release_long_receipt

        def absent(*args: Any, **kwargs: Any) -> str:
            self.assertFalse(self.path.exists())
            return release(*args, **kwargs)

        with mock.patch.object(store, "release_long_receipt", side_effect=absent):
            result = self.discard()
        self.assertTrue(result.receipt_released)
        self.assertNotIn(self.job_id, self.fixture.entry()["long_receipts"])
        self.assertEqual(before, store.published(self.fixture.entry()))
