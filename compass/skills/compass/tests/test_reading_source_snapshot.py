"""Private frozen-prefix revalidation consumes the original collection allowance."""

from __future__ import annotations

import hashlib
import math
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_stream as raw_source

from . import test_reading_source_collect as collection_tests


class SourceSnapshotTest(unittest.TestCase):
    setUp = collection_tests.BoundedReadingCollectionTest.setUp
    module = collection_tests.BoundedReadingCollectionTest.module
    inventory = collection_tests.BoundedReadingCollectionTest.inventory
    collect = collection_tests.BoundedReadingCollectionTest.collect

    def snapshot(self, **options: Any) -> Any:
        result = self.collect(clock=lambda: 0.0, **options)
        self.assertEqual("", result.reason)
        self.assertIsNotNone(getattr(result, "snapshot", None), "verified handles are missing")
        return result

    def append(self, path: Any = None) -> None:
        with (path or self.path).open("ab") as source:
            source.write(b'{"type":"progress"}\n')

    def test_measured_handles_and_unchanged_stamps_need_no_content_io(self) -> None:
        result = self.snapshot()
        handles = result.snapshot.streams
        self.assertEqual(2, len(handles))
        for handle in handles:
            with open(handle.frozen.path, "rb") as data:
                self.assertEqual(hashlib.sha256(data.read()).hexdigest(), handle.baseline_digest)
            self.assertEqual(raw_source._stamp(os.stat(handle.frozen.path)), handle.stamp)
        with mock.patch.object(raw_source, "read", side_effect=AssertionError("unchanged reread")):
            checked = collector.revalidate(result.snapshot, clock=lambda: 0.0)
        self.assertEqual("", checked.reason)
        self.assertIsNotNone(checked.snapshot)
        self.assertEqual(result.usage.source_bytes, checked.usage.source_bytes)
        self.assertEqual(result.usage.source_pages, checked.usage.source_pages)
        self.assertTrue(checked.final_valid)
        size, units = collector._measure(result.snapshot, collector.Limits())
        self.assertLess(size, result.usage.retained_bytes)
        self.assertLess(units, result.usage.retained_units)

    def test_append_checks_only_old_prefix_once_and_invalidates_final(self) -> None:
        result = self.snapshot()
        previous = result.snapshot.streams[0]
        self.append()
        real_read = raw_source.read
        phases = []

        def read(cursor: Any, **options: Any) -> Any:
            phases.append(cursor.phase)
            return real_read(cursor, **options)

        with mock.patch.object(raw_source, "read", side_effect=read):
            checked = collector.revalidate(result.snapshot, clock=lambda: 0.0)
        self.assertEqual("", checked.reason)
        self.assertFalse(checked.final_valid)
        self.assertEqual({"verify"}, set(phases))
        self.assertEqual(
            previous.frozen.end_offset, checked.usage.source_bytes - result.usage.source_bytes
        )
        self.assertEqual(math.ceil(previous.frozen.end_offset / 127), len(phases))
        self.assertEqual(previous.frozen, checked.snapshot.streams[0].frozen)
        self.assertEqual(previous.baseline_digest, checked.snapshot.streams[0].baseline_digest)
        self.assertNotEqual(previous.stamp, checked.snapshot.streams[0].stamp)
        # Updated unchanged handles are free, and never restore old strict-final authority.
        again = collector.revalidate(checked.snapshot, clock=lambda: 0.0)
        self.assertEqual(checked.usage.source_bytes, again.usage.source_bytes)
        self.assertFalse(again.final_valid)

    def test_rewrite_replace_truncate_and_child_symlink_refuse(self) -> None:
        for movement in ("rewrite", "append_rewrite", "replace", "truncate", "child_symlink"):
            with self.subTest(movement=movement):
                # Fresh temporary native fixture for each destructive case.
                self.setUp()
                result = self.snapshot()
                if movement == "child_symlink":
                    target = self.child_path.with_suffix(".copy")
                    target.write_bytes(self.child_path.read_bytes())
                    self.child_path.unlink()
                    self.child_path.symlink_to(target)
                elif movement == "replace":
                    replacement = self.path.with_suffix(".copy")
                    replacement.write_bytes(self.path.read_bytes())
                    replacement.replace(self.path)
                elif movement == "truncate":
                    self.path.write_bytes(b"{}\n")
                else:
                    before = self.path.stat()
                    data = self.path.read_bytes()
                    self.path.write_bytes(data.replace(b"Check the parent", b"Other the parent", 1))
                    os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
                    if movement == "append_rewrite":
                        self.append()
                checked = collector.revalidate(result.snapshot, clock=lambda: 0.0)
                self.assertEqual("source_changed", checked.reason)
                self.assertIsNone(checked.snapshot)
                self.assertFalse(checked.final_valid)
                if movement in ("replace", "truncate", "child_symlink"):
                    self.assertEqual(result.usage.source_bytes, checked.usage.source_bytes)

    def test_extra_prefix_must_fit_original_bytes_and_pages_before_io(self) -> None:
        frozen = self.inventory()
        total = sum(s.cursor.frozen.end_offset for s in frozen.streams)
        original_pages = sum(
            3 * math.ceil(s.cursor.frozen.end_offset / 127) for s in frozen.streams
        )
        for limits, reason in (
            (replace(collector.Limits(), source_bytes=3 * total), "source_bytes"),
            (replace(collector.Limits(), source_pages=original_pages), "source_pages"),
        ):
            with self.subTest(reason=reason):
                result = self.snapshot(limits=limits)
                self.append()
                with mock.patch.object(
                    raw_source, "read", side_effect=AssertionError("unreserved")
                ):
                    checked = collector.revalidate(result.snapshot, clock=lambda: 0.0)
                self.assertEqual(reason, checked.reason)
                self.assertIsNone(checked.snapshot)
                self.assertEqual(result.usage.source_bytes, checked.usage.source_bytes)
                self.setUp()

    def test_cancelled_piece_is_charged_even_when_old_handle_is_reused(self) -> None:
        result = self.snapshot()
        self.append()
        stopped = False
        real_read = raw_source.read

        def read(cursor: Any, **options: Any) -> Any:
            nonlocal stopped
            page = real_read(cursor, **options)
            stopped = True
            return page

        with mock.patch.object(raw_source, "read", side_effect=read):
            checked = collector.revalidate(
                result.snapshot, clock=lambda: 0.0, cancelled=lambda: stopped
            )
        self.assertEqual("cancelled", checked.reason)
        self.assertIsNone(checked.snapshot)
        self.assertEqual(result.usage.source_bytes + 127, checked.usage.source_bytes)
        again = collector.revalidate(result.snapshot, clock=lambda: 0.0)
        self.assertEqual("", again.reason)
        self.assertEqual(
            checked.usage.source_bytes + result.snapshot.streams[0].frozen.end_offset,
            again.usage.source_bytes,
        )

    def test_preparation_time_accumulates_and_no_progress_does_not_retry(self) -> None:
        result = self.snapshot(limits=replace(collector.Limits(), prepare_ms=10))
        self.append()
        now = 0.0
        real_read = raw_source.read

        def read(cursor: Any, **options: Any) -> Any:
            nonlocal now
            page = real_read(cursor, **options)
            now = 0.011
            return page

        with mock.patch.object(raw_source, "read", side_effect=read):
            checked = collector.revalidate(result.snapshot, clock=lambda: now)
        self.assertEqual("time", checked.reason)
        self.assertGreaterEqual(checked.usage.prepare_ms, 11)
        with mock.patch.object(raw_source, "read", side_effect=AssertionError("fresh budget")):
            again = collector.revalidate(result.snapshot, clock=lambda: now)
        self.assertEqual("time", again.reason)
        self.setUp()
        result = self.snapshot()
        self.append()
        with mock.patch.object(
            raw_source, "read", return_value=raw_source.Page("limited", "verify")
        ) as read:
            checked = collector.revalidate(result.snapshot, clock=lambda: 0.0)
        self.assertEqual("no_progress", checked.reason)
        self.assertEqual(1, read.call_count)

    def test_gapped_or_unavailable_collection_has_no_snapshot(self) -> None:
        with self.path.open("ab") as source:
            source.write(b'{"unfinished":')
        result = self.collect()
        self.assertEqual("source_gap", result.reason)
        self.assertIsNone(getattr(result, "snapshot", None))
        with self.assertRaises(ValueError):
            collector.revalidate(None)

    def test_child_append_keeps_parent_final_version_but_late_parent_movement_refuses(self) -> None:
        result = self.snapshot()
        self.append(self.child_path)
        checked = collector.revalidate(result.snapshot, clock=lambda: 0.0)
        self.assertEqual("", checked.reason)
        self.assertTrue(checked.final_valid)
        self.assertEqual(
            result.usage.source_bytes + result.snapshot.streams[1].frozen.end_offset,
            checked.usage.source_bytes,
        )
        self.append(self.child_path)
        real_read = raw_source.read
        moved = False

        def read(cursor: Any, **options: Any) -> Any:
            nonlocal moved
            page = real_read(cursor, **options)
            if not moved:
                self.append()
                moved = True
            return page

        with mock.patch.object(raw_source, "read", side_effect=read):
            refused = collector.revalidate(checked.snapshot, clock=lambda: 0.0)
        self.assertEqual("source_changed", refused.reason)
        self.assertIsNone(refused.snapshot)
        self.assertFalse(refused.final_valid)

    def test_snapshot_and_validation_graph_still_obey_retained_limit(self) -> None:
        full = self.snapshot()
        # Enough for the same collection, but not its original high-water
        # reservation plus the measured validation graph held beside it.
        limits = replace(collector.Limits(), retained_bytes=full.usage.retained_bytes + 1024)
        result = self.snapshot(limits=limits)
        with mock.patch.object(raw_source, "read", side_effect=AssertionError("retained refusal")):
            checked = collector.revalidate(result.snapshot, clock=lambda: 0.0)
        self.assertEqual("retained_bytes", checked.reason)
        self.assertIsNone(checked.snapshot)
        self.assertLessEqual(checked.usage.retained_bytes, limits.retained_bytes)

    def test_concurrent_and_reentrant_calls_refuse_without_spending_shared_budget(self) -> None:
        result = self.snapshot()
        self.append()
        entered = threading.Event()
        release = threading.Event()
        real_read = raw_source.read

        def read(cursor: Any, **options: Any) -> Any:
            if not entered.is_set():
                with self.assertRaisesRegex(ValueError, "already active"):
                    collector.revalidate(result.snapshot, clock=lambda: 0.0)
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("test did not release the active verifier")
            return real_read(cursor, **options)

        with (
            ThreadPoolExecutor(max_workers=1) as pool,
            mock.patch.object(raw_source, "read", side_effect=read),
        ):
            pending = pool.submit(collector.revalidate, result.snapshot, clock=lambda: 0.0)
            try:
                self.assertTrue(entered.wait(timeout=5))
                with self.assertRaisesRegex(ValueError, "already active"):
                    collector.revalidate(result.snapshot, clock=lambda: 0.0)
            finally:
                release.set()
            checked = pending.result(timeout=5)
        self.assertEqual("", checked.reason)
        self.assertEqual(
            result.usage.source_bytes + result.snapshot.streams[0].frozen.end_offset,
            checked.usage.source_bytes,
        )
        # Entry is released after success, and the successor shares the account.
        again = collector.revalidate(checked.snapshot, clock=lambda: 0.0)
        self.assertEqual("", again.reason)
        self.assertEqual(checked.usage.source_bytes, again.usage.source_bytes)
