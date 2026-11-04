"""Session history reads only bounded existing metadata, never recovery authority."""

from __future__ import annotations

import json
import os
import unittest
from typing import Any
from unittest import mock

from compass_runtime import reading_long_history as history
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_jobs as jobs
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_long_recovery as recovery
from compass_runtime import reading_policy as policy

from . import test_reading_long_inspection as fixtures
from .test_reading_long_jobs import binding

SID = "abcdef12"


class LongHistoryTest(unittest.TestCase):
    def setUp(self) -> None:
        publication = {"harness": "claude", "sid": SID, "incarnation": "e" * 32, "revision": 1}
        supplied = binding(
            publication=publication, target_sha256=jobs.publication_digest(publication)
        )
        self.fixture = fixtures.LongInspectionTest()
        with mock.patch.object(fixtures, "binding", return_value=supplied):
            self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.path = self.fixture.path

    def read(self, *, now: float = 100, sid: str = SID) -> history.History:
        return history.read(self.config, "claude", sid, now=now)

    def tree(self) -> dict[str, bytes | str | None]:
        return {
            str(path.relative_to(self.config.state_dir)): (
                str(path.readlink())
                if path.is_symlink()
                else path.read_bytes()
                if path.is_file()
                else None
            )
            for path in self.config.state_dir.rglob("*")
        }

    def test_repeated_exact_reads_preserve_every_file_and_reserved_allocations(self) -> None:
        self.fixture.reserve()
        before = self.tree()
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(markers, "_write", side_effect=AssertionError),
            mock.patch.object(recovery, "recover", side_effect=AssertionError),
            mock.patch.object(recovery, "discard_terminal", side_effect=AssertionError),
            mock.patch.object(inspection, "retire", side_effect=AssertionError),
        ):
            first = self.read()
            self.assertEqual(first, self.read())
        self.assertEqual(before, self.tree())
        self.assertEqual({"version", "items", "incomplete", "reason"}, set(first))
        self.assertFalse(first["incomplete"])
        self.assertEqual("", first["reason"])
        self.assertEqual(1, first["version"])
        item = first["items"][0]
        self.assertEqual(
            {
                "job_id",
                "state",
                "started_at",
                "updated_at",
                "terminal_at",
                "unsettled",
                "accounting",
                "exact",
                "minimum",
                "reason",
            },
            set(item),
        )
        self.assertEqual(self.fixture.job_id, item["job_id"])
        self.assertEqual(
            ("active", 100, 100, None, True),
            (
                item["state"],
                item["started_at"],
                item["updated_at"],
                item["terminal_at"],
                item["unsettled"],
            ),
        )
        self.assertEqual("exact", item["accounting"])
        self.assertEqual({"calls": 1, "prompt_bytes": 10, "reply_bytes": 10}, item["exact"])
        self.assertEqual(item["exact"], item["minimum"])
        serialized = json.dumps(first)
        for private in ("owner", "pid", "header", "binding", "sha256", str(self.path)):
            self.assertNotIn(private, serialized)

    def test_minimum_and_unknown_never_become_exact_zero(self) -> None:
        self.fixture.reserve()
        self.fixture.settle()
        self.fixture.reserve(2)
        self.fixture.sql("DELETE FROM long_pass_reservations WHERE ordinal=1")
        before = self.tree()
        minimum = self.read()
        item = minimum["items"][0]
        self.assertEqual("minimum", item["accounting"])
        self.assertIsNone(item["exact"])
        self.assertEqual({"calls": 1, "prompt_bytes": 10, "reply_bytes": 10}, item["minimum"])
        self.assertEqual("ledger-incomplete", item["reason"])
        self.assertTrue(minimum["incomplete"])
        self.assertEqual(before, self.tree())
        self.fixture.sql("DELETE FROM long_pass_reservations")
        unknown = self.read()["items"][0]
        self.assertEqual("unknown", unknown["accounting"])
        self.assertIsNone(unknown["exact"])
        self.assertIsNone(unknown["minimum"])

    def test_missing_corrupt_and_symlink_database_are_unknown_and_never_created(self) -> None:
        database = policy.store_path(self.config)
        database.unlink()
        for mode in ("missing", "corrupt", "symlink"):
            with self.subTest(mode=mode):
                if mode == "corrupt":
                    database.write_bytes(b"not a database")
                elif mode == "symlink":
                    database.unlink()
                    database.symlink_to(self.path)
                before = self.tree()
                result = self.read()
                self.assertEqual("unknown", result["items"][0]["accounting"])
                self.assertIsNone(result["items"][0]["exact"])
                self.assertIsNone(result["items"][0]["minimum"])
                self.assertEqual("accounting-unavailable", result["reason"])
                self.assertEqual(before, self.tree())

    def test_cold_missing_inventory_is_empty_without_creating_anything(self) -> None:
        self.path.unlink()
        self.path.parent.rmdir()
        policy.store_path(self.config).unlink()
        before = self.tree()
        self.assertEqual(
            {"version": 1, "items": [], "incomplete": False, "reason": ""}, self.read()
        )
        self.assertEqual(before, self.tree())

    def test_valid_foreign_session_and_invalid_requested_identity_never_leak(self) -> None:
        with mock.patch.object(inspection, "inspect", side_effect=AssertionError):
            self.assertEqual([], self.read(sid="12345678")["items"])
            invalid = self.read(sid="not a native session")
        self.assertEqual("invalid-session", invalid["reason"])
        self.assertTrue(invalid["incomplete"])

    def test_malformed_oversized_symlink_and_unattributed_records_are_incomplete(self) -> None:
        original = self.path.read_bytes()
        for raw in (b"{}", b"x" * (markers.MAX_MARKER_BYTES + 1)):
            self.path.write_bytes(raw)
            before = self.tree()
            result = self.read()
            self.assertEqual([], result["items"])
            self.assertEqual("marker-unavailable", result["reason"])
            self.assertEqual(before, self.tree())
        self.path.write_bytes(original)
        target = self.path.with_suffix(".outside")
        self.path.rename(target)
        self.path.symlink_to(target)
        self.assertEqual("marker-unavailable", self.read()["reason"])
        self.path.unlink()
        target.rename(self.path)
        value = json.loads(original)
        del value["header"]["publication"]
        value["job_id"] = jobs.digest(value["header"])[:32]
        self.path.unlink()
        legacy = markers.marker_path(self.config, value["job_id"])
        legacy.write_text(json.dumps(value))
        self.assertIsNotNone(markers.load(self.config, value["job_id"]))
        self.assertEqual("marker-unattributed", self.read()["reason"])

    def test_changed_marker_during_inspection_withholds_previously_attributed_item(self) -> None:
        original = inspection.inspect

        def moved(*args: Any, **kwargs: Any) -> inspection.Inspection:
            result = original(*args, **kwargs)
            self.path.unlink()
            return result

        with mock.patch.object(inspection, "inspect", side_effect=moved):
            result = self.read()
        self.assertEqual([], result["items"])
        self.assertEqual("marker-changed", result["reason"])

    def test_terminal_records_do_not_imply_owner_death_or_discard_authority(self) -> None:
        self.fixture.seal("failed")
        before = self.tree()
        item = self.read()["items"][0]
        self.assertEqual(
            ("failed", 100, False), (item["state"], item["terminal_at"], item["unsettled"])
        )
        self.assertEqual(before, self.tree())
        self.assertNotIn("discard", json.dumps(item))

    def test_inventory_bound_counts_unrelated_entries_and_unreadable_is_explicit(self) -> None:
        for number in range(markers.MAX_MARKERS + 1):
            (self.path.parent / f"noise-{number}").touch()
        self.assertEqual("inventory-bounded", self.read()["reason"])
        with mock.patch.object(os, "scandir", side_effect=PermissionError):
            result = self.read()
        self.assertEqual("inventory-unavailable", result["reason"])
        self.assertEqual([], result["items"])

    def test_invalid_clock_does_not_touch_inventory_or_claim_zero(self) -> None:
        with mock.patch.object(history, "_inventory", side_effect=AssertionError):
            for now in (float("nan"), float("inf"), -1.0):
                self.assertEqual("inspection-clock-invalid", self.read(now=now)["reason"])
