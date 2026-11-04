"""Startup recovery proves owner death, preserves unknown accounting, and never resumes."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import importlib
import importlib.util
import json
import os
import unittest
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import reading
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_policy as policy

from . import test_reading_long_inspection as inspection_tests

if TYPE_CHECKING:
    from pathlib import Path


class LongRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_recovery"))
        self.module = importlib.import_module("compass_runtime.reading_long_recovery")
        self.fixture = inspection_tests.LongInspectionTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.path = self.fixture.path
        self.pid(424242)

    def pid(self, pid: int) -> None:
        value = json.loads(self.path.read_text())
        value["pid"] = pid
        markers._write(self.path, value)

    def recover(self, **changes: Any) -> Any:
        return self.module.recover(
            self.config,
            **{
                "now": 101,
                "alive": lambda _pid: False,
                "process_exists": lambda _pid: False,
                **changes,
            },
        )

    def item(self, **changes: Any) -> Any:
        result = self.recover(**changes)
        self.assertFalse(result.incomplete)
        self.assertEqual(1, len(result.items))
        return result.items[0]

    def test_verified_dead_owner_is_durably_interrupted_without_execution_authority(self) -> None:
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(policy, "reserve_registered_pass", side_effect=AssertionError),
            mock.patch.object(markers, "begin", side_effect=AssertionError),
        ):
            item = self.item()
        self.assertEqual("dead", item.owner)
        self.assertEqual("interrupted", item.outcome)
        self.assertTrue(item.changed)
        self.assertEqual(inspection.Totals(0, 0, 0), item.inspected.exact)
        stored = markers.load(self.config, self.fixture.job_id)
        assert stored is not None
        self.assertEqual("interrupted", stored["state"])
        self.assertEqual(101, stored["terminal_at"])
        before = self.path.read_bytes()
        self.assertFalse(self.item().changed)
        self.assertEqual(before, self.path.read_bytes())

    def test_live_reused_uncertain_and_error_probes_never_interrupt(self) -> None:
        before = self.path.read_bytes()
        for alive, exists in (
            (True, False),
            (False, True),
            (None, False),
            (False, None),
            (False, 0),
        ):
            with self.subTest(alive=alive, exists=exists):
                result = self.item(
                    alive=lambda _pid, value=alive: value,
                    process_exists=lambda _pid, value=exists: value,
                )
                self.assertIsNone(result.outcome)
                self.assertFalse(result.changed)
        self.assertIsNone(self.item(alive=mock.Mock(side_effect=OSError)).outcome)
        self.assertIsNone(self.item(process_exists=mock.Mock(side_effect=RuntimeError)).outcome)
        self.assertEqual(before, self.path.read_bytes())

    def test_current_pid_requires_explicit_startup_and_matching_active_slot_always_wins(
        self,
    ) -> None:
        self.pid(os.getpid())
        self.assertEqual("unknown", self.item().owner)
        key = "claude:recover"
        job = reading.start_job(
            self.config,
            key,
            provider="claude",
            label="Claude",
            now=100,
            prepared_job_id=self.fixture.job_id,
        )
        self.addCleanup(reading.end_job, self.config, key)
        self.assertIsNotNone(job)
        self.assertEqual("current", self.item(startup_before_jobs=True).owner)
        reading.end_job(self.config, key)
        self.assertEqual("interrupted", self.item(startup_before_jobs=True).outcome)

    def test_job_that_appears_during_liveness_probe_wins_before_write(self) -> None:
        key = "claude:new"
        self.addCleanup(reading.end_job, self.config, key)

        def alive(_pid: int) -> bool:
            reading.start_job(
                self.config,
                key,
                provider="claude",
                label="Claude",
                now=100,
                prepared_job_id=self.fixture.job_id,
            )
            return False

        before = self.path.read_bytes()
        self.assertEqual("current", self.item(alive=alive).owner)
        self.assertEqual(before, self.path.read_bytes())

    def test_two_recoverers_write_one_terminal_transition(self) -> None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.recover(), range(2)))
        self.assertEqual(1, sum(item.changed for result in results for item in result.items))
        stored = markers.load(self.config, self.fixture.job_id)
        assert stored is not None
        self.assertEqual("interrupted", stored["state"])
        self.assertEqual(0, self.item().inspected.exact.calls)

    def test_before_charge_crash_recovers_exact_zero_from_ledger(self) -> None:
        self.pid(os.getpid())
        with (
            mock.patch.object(
                policy, "reserve_registered_pass", side_effect=inspection_tests.Crash
            ),
            self.assertRaises(inspection_tests.Crash),
        ):
            self.fixture.reserve()
        self.pid(424242)
        item = self.item()
        self.assertEqual(0, item.inspected.exact.calls)
        self.assertTrue(item.inspected.unsettled)
        self.assertEqual("interrupted", item.outcome)

    def test_after_charge_crash_uses_receipt_not_pending_marker_hint(self) -> None:
        self.pid(os.getpid())
        original = markers._write

        def write(path: Path, marker: Any) -> None:
            if marker["passes"][-1]["state"] == "charged":
                raise inspection_tests.Crash
            original(path, marker)

        with (
            mock.patch.object(markers, "_write", side_effect=write),
            self.assertRaises(inspection_tests.Crash),
        ):
            self.fixture.reserve()
        self.pid(424242)
        stored = markers.load(self.config, self.fixture.job_id)
        assert stored is not None
        self.assertIsNone(stored["passes"][0]["charged"])
        policy.set_consent(self.config, False, now=100)
        item = self.item()
        self.assertEqual(1, item.inspected.exact.calls)
        self.assertEqual("interrupted", item.outcome)

    def test_missing_recreated_and_pruned_ledger_never_fabricate_zero(self) -> None:
        policy.store_path(self.config).unlink()
        item = self.item()
        self.assertEqual("unknown", item.inspected.accounting)
        self.assertIsNone(item.inspected.exact)
        self.assertTrue(self.path.exists())
        policy.capture_long_permission(self.config, now=102)
        self.assertEqual("unknown", self.item().inspected.accounting)

    def test_deleted_receipt_keeps_minimum_instead_of_exact_count(self) -> None:
        self.pid(os.getpid())
        self.fixture.reserve()
        self.fixture.settle()
        self.fixture.reserve(2)
        self.fixture.sql("DELETE FROM long_pass_reservations WHERE ordinal=2")
        self.pid(424242)
        item = self.item()
        self.assertIsNone(item.inspected.exact)
        self.assertEqual(1, item.inspected.minimum.calls)
        self.assertTrue(self.path.exists())

    def test_malformed_symlink_unwritable_markers_are_preserved(self) -> None:
        before = self.path.read_bytes()
        with mock.patch.object(markers, "_write", side_effect=OSError):
            item = self.item()
        self.assertFalse(item.changed)
        self.assertIsNone(item.outcome)
        self.assertEqual(before, self.path.read_bytes())
        self.path.write_text("malformed canary")
        self.assertIsNone(self.item().outcome)
        self.assertEqual("malformed canary", self.path.read_text())
        target = self.path.with_suffix(".saved")
        target.write_bytes(before)
        self.path.unlink()
        self.path.symlink_to(target)
        self.assertIsNone(self.item().outcome)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(before, target.read_bytes())

    def test_terminal_cancelled_stays_cancelled_and_completed_is_not_reconstructed(self) -> None:
        self.pid(os.getpid())
        self.fixture.seal("cancelled")
        self.pid(424242)
        before = self.path.read_bytes()
        item = self.item()
        self.assertEqual("cancelled", item.outcome)
        self.assertFalse(item.changed)
        self.assertEqual(before, self.path.read_bytes())

    def test_bounded_discovery_does_not_read_unlimited_unknown_files_or_create_missing_home(
        self,
    ) -> None:
        absent = self.config.state_dir / "missing-home"
        result = self.module.recover(
            dataclasses.replace(self.config, state_dir=absent),
            now=101,
            alive=lambda _: False,
            process_exists=lambda _: False,
        )
        self.assertEqual((), result.items)
        self.assertFalse(absent.exists())
        for index in range(markers.MAX_MARKERS + 1):
            (self.path.parent / f"unknown-{index}").touch()
        with mock.patch.object(markers, "load", wraps=markers.load) as load:
            result = self.recover()
        self.assertTrue(result.incomplete)
        self.assertLessEqual(load.call_count, markers.MAX_MARKERS * 4)

    def test_snapshot_is_reread_under_publication_barrier(self) -> None:
        original = markers.publication_lock

        @contextlib.contextmanager
        def changed(config: Any) -> Any:
            with original(config) as directory:
                value = json.loads(self.path.read_text())
                value["owner"] = "f" * 32
                markers._write(self.path, value)
                yield directory

        with mock.patch.object(markers, "publication_lock", changed):
            item = self.item()
        self.assertFalse(item.changed)
        self.assertIsNone(item.outcome)
        stored = markers.load(self.config, self.fixture.job_id)
        assert stored is not None
        self.assertEqual("active", stored["state"])
