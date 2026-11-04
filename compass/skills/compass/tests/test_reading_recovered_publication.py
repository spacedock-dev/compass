"""Restart publication never reconstructs authority or guesses a charge count."""

from __future__ import annotations

import concurrent.futures
import json
import os
import sqlite3
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import reading
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_long_recovery as recovery
from compass_runtime import reading_policy as policy

from . import test_reading_long_finalize as fixtures


class RecoveredPublicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.WithheldFinalizationTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state
        self.job_id, self.path = self.fixture.active.job.id, self.fixture.path

    def die(self) -> None:
        reading.end_job(self.config, self.fixture.key)
        value = json.loads(self.path.read_text())
        value["pid"] = 424242
        markers._write(self.path, value)
        result = recovery.recover(
            self.config, now=101, alive=lambda _: False, process_exists=lambda _: False
        )
        self.assertEqual("dead", result.items[0].owner)
        self.assertEqual("interrupted", result.items[0].outcome)

    def publish(self, **changes: Any) -> Any:
        function: Any = getattr(recovery, "publish_terminal", None)
        self.assertTrue(
            callable(function), "restart publication needs a separate owner-proof boundary"
        )
        return function(
            self.config,
            self.state,
            **{
                "job_id": self.job_id,
                "now": 102,
                "alive": lambda _: False,
                "process_exists": lambda _: False,
                **changes,
            },
        )

    def test_zero_pending_crash_is_acknowledged_without_count_or_execution_authority(self) -> None:
        with (
            mock.patch.object(policy, "reserve_registered_pass", side_effect=fixtures.Crash),
            self.assertRaises(fixtures.Crash),
        ):
            self.fixture.reserve()
        self.die()
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(policy, "reserve_registered_pass", side_effect=AssertionError),
            mock.patch.object(markers, "begin", side_effect=AssertionError),
        ):
            result = self.publish()
        self.assertTrue(result.acknowledged and result.retired and result.receipt_released)
        entry = self.fixture.entry()
        self.assertEqual(0, entry.get("readings", 0))
        self.assertEqual(0, entry["long_diagnostic"]["accounting"]["totals"]["calls"])
        self.assertNotIn("attempt still counts", entry["withheld"])
        self.assertNotIn("Nothing was produced", entry["withheld"])
        self.assertFalse(self.path.exists())
        self.assertFalse(self.publish().acknowledged)

    def test_multiple_charges_after_pause_count_one_job(self) -> None:
        self.fixture.reserve(1)
        self.fixture.reserve(2)
        self.die()
        policy.set_consent(self.config, False, now=101)
        self.assertTrue(self.publish().receipt_released)
        entry = self.fixture.entry()
        self.assertEqual(1, entry["readings"])
        self.assertEqual(2, entry["long_diagnostic"]["accounting"]["totals"]["calls"])
        self.assertIsNone(entry["long_diagnostic"].get("binding"))
        self.assertIsNone(entry["long_diagnostic"]["source"])

    def test_after_sql_commit_crash_counts_receipt_not_pending_flag(self) -> None:
        write = markers._write

        def crash(path: Any, value: Any) -> None:
            if value["passes"] and value["passes"][-1]["state"] == "charged":
                raise fixtures.Crash
            write(path, value)

        with (
            mock.patch.object(markers, "_write", side_effect=crash),
            self.assertRaises(fixtures.Crash),
        ):
            self.fixture.reserve()
        self.die()
        self.assertTrue(self.publish().acknowledged)
        self.assertEqual(1, self.fixture.entry()["readings"])

    def test_live_reused_uncertain_or_exception_probe_and_current_slot_preserve_marker(
        self,
    ) -> None:
        self.die()
        before = self.path.read_bytes()
        for alive, exists in (
            (True, False),
            (False, True),
            (None, False),
            (False, None),
            (False, 0),
        ):
            self.assertFalse(
                self.publish(
                    alive=lambda _, value=alive: value, process_exists=lambda _, value=exists: value
                ).acknowledged
            )
        self.assertFalse(self.publish(process_exists=mock.Mock(side_effect=OSError)).acknowledged)
        self.assertEqual(before, self.path.read_bytes())

        def new_job(_: int) -> bool:
            reading.start_job(
                self.config,
                self.fixture.key,
                provider="claude",
                label="Claude",
                now=101,
                prepared_job_id=self.job_id,
            )
            return False

        self.assertFalse(self.publish(alive=new_job).acknowledged)
        self.assertEqual(before, self.path.read_bytes())

    def test_current_pid_requires_startup_and_current_job_always_wins(self) -> None:
        self.die()
        value = json.loads(self.path.read_text())
        value["pid"] = os.getpid()
        markers._write(self.path, value)
        self.assertFalse(self.publish().acknowledged)
        reading.start_job(
            self.config,
            self.fixture.key,
            provider="claude",
            label="Claude",
            now=101,
            prepared_job_id=self.job_id,
        )
        self.assertFalse(self.publish(startup_before_jobs=True).acknowledged)
        reading.end_job(self.config, self.fixture.key)
        self.assertTrue(self.publish(startup_before_jobs=True).acknowledged)

    def test_two_publishers_count_once_and_crash_ack_replay_survives_newer_jobs(self) -> None:
        self.fixture.reserve()
        self.die()
        with (
            mock.patch.object(inspection, "_retire_locked", side_effect=fixtures.Crash),
            self.assertRaises(fixtures.Crash),
        ):
            self.publish()
        for n in range(33):
            store.record_withheld(
                self.config,
                self.state,
                "claude",
                self.fixture.sid,
                reason=reading.WITHHELD_MODEL_FAILED,
                spent=True,
                job_id=f"{n:016x}",
            )
        store.annotate(self.config, self.state, "claude", self.fixture.sid, goal="Changed", now=103)
        policy.set_consent(self.config, False, now=103)
        before = store.published(self.fixture.entry())
        with (
            mock.patch.object(store, "record_withheld", side_effect=AssertionError),
            concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool,
        ):
            outcomes = list(pool.map(lambda _: self.publish(), range(2)))
        self.assertEqual(1, sum(outcome.retired for outcome in outcomes))
        self.assertEqual(before, store.published(self.fixture.entry()))
        self.assertEqual(34, self.fixture.entry()["readings"])

    def test_unknown_minimum_and_recreated_ledger_never_publish_counts(self) -> None:
        self.fixture.reserve(1)
        self.fixture.reserve(2)
        self.die()
        with sqlite3.connect(policy.store_path(self.config)) as db:
            db.execute("DELETE FROM long_pass_reservations WHERE ordinal=2")
        self.assertEqual(
            "minimum", inspection.inspect(self.config, self.job_id, now=102).accounting
        )
        self.assertFalse(self.publish().acknowledged)
        policy.store_path(self.config).unlink()
        self.assertFalse(self.publish().acknowledged)
        policy.capture_long_permission(self.config, now=103)
        self.assertFalse(self.publish().acknowledged)
        self.assertTrue(self.path.exists())
        self.assertNotIn("readings", self.fixture.entry())

    def test_unwritable_retry_and_recreated_annotation_are_not_acknowledgment(self) -> None:
        self.die()
        with mock.patch.object(store, "save", return_value=False):
            self.assertFalse(self.publish().acknowledged)
        self.assertTrue(self.path.exists())
        with (
            mock.patch.object(inspection, "_retire_locked", side_effect=fixtures.Crash),
            self.assertRaises(fixtures.Crash),
        ):
            self.publish()
        self.fixture.fixture.path.unlink()
        store.annotate(
            self.config, self.state, "claude", self.fixture.sid, goal="Recreated", now=100
        )
        before = self.fixture.fixture.path.read_bytes()
        self.assertFalse(self.publish().acknowledged)
        self.assertEqual(before, self.fixture.fixture.path.read_bytes())
        self.assertTrue(self.path.exists())

    def test_active_or_symlink_marker_never_publishes(self) -> None:
        self.assertFalse(self.publish().acknowledged)
        self.die()
        saved = self.path.with_suffix(".saved")
        self.path.rename(saved)
        self.path.symlink_to(saved)
        self.assertFalse(self.publish().acknowledged)
        self.assertTrue(self.path.is_symlink())
