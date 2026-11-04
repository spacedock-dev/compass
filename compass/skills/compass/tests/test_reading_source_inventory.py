"""Bounded discovery freezes only native admitted parent/child streams."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import project_context as context
from compass_runtime import reading_source_stream as raw_source


class FrozenSourceInventoryTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.parent = self.root / "session.jsonl"
        self.parent.write_bytes(b'{"id":"parent"}\n')
        self.subagents = self.parent.with_suffix("") / "subagents"

    def module(self) -> Any:
        self.assertIsNotNone(
            importlib.util.find_spec("compass_runtime.reading_source_inventory"),
            "bounded native child inventory is not implemented",
        )
        return importlib.import_module("compass_runtime.reading_source_inventory")

    def child(self, relative: str, *, at: int = 10) -> Path:
        path = self.subagents / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": relative}) + "\n")
        os.utime(path, (at, at))
        return path

    def freeze(self, **options: Any) -> Any:
        return self.module().freeze(
            str(self.parent),
            "claude",
            "parent",
            max_entries=options.pop("max_entries", 100),
            max_streams=options.pop("max_streams", 10),
            max_seconds=options.pop("max_seconds", 1),
            **options,
        )

    @staticmethod
    def read_all(cursor: raw_source.Cursor) -> tuple[list[dict[str, Any]], raw_source.Page]:
        rows = []
        for _ in range(200):
            page = raw_source.read(cursor, max_bytes=31, max_seconds=1)
            rows.extend(record.value for record in page.records)
            if page.next is None:
                return rows, page
            cursor = page.next
        raise AssertionError("frozen stream failed to finish")

    def test_native_inventory_matches_canonical_order_and_freeze_reads_no_content(self) -> None:
        self.child("agent-aa.jsonl", at=10)
        self.child("workflows/work-b/agent-aa.jsonl", at=20)
        self.child("agent-bb.jsonl", at=20)
        expected = context._admitted_subagent_paths(str(self.parent), None)
        expected.sort(
            key=lambda path: (
                -os.stat(path).st_mtime,
                os.path.relpath(path, self.parent.with_suffix("")),
            )
        )
        self.module()
        with (
            mock.patch.object(
                runtime_io,
                "_open_scan_binary",
                side_effect=AssertionError("freeze must not read content"),
            ),
            mock.patch("builtins.open", side_effect=AssertionError("freeze must not read content")),
        ):
            inventory = self.freeze()
        self.assertTrue(inventory.complete)
        self.assertEqual((), inventory.gaps)
        self.assertEqual(
            [str(self.parent), *expected],
            [stream.cursor.frozen.path for stream in inventory.streams],
        )
        self.assertEqual(
            ["parent", "agent-bb", "workflows/work-b/agent-aa", "agent-aa"],
            [stream.name for stream in inventory.streams],
        )
        self.assertEqual(
            3, len({stream.cursor.frozen.identity for stream in inventory.streams[1:]})
        )
        for stream in inventory.streams:
            self.assertEqual(("baseline", 0), (stream.cursor.phase, stream.cursor.offset))
            rows, page = self.read_all(stream.cursor)
            self.assertEqual(1, len(rows))
            self.assertEqual("verified", page.state)

    def test_aside_compaction_links_and_outside_paths_are_not_admitted(self) -> None:
        allowed = self.child("agent-ab12.jsonl")
        self.child("agent-acompact-12.jsonl")
        self.child("agent-aside-12.jsonl")
        self.child("agent-psuggest-12.jsonl")
        self.child("nested/agent-ff.jsonl")
        outside = self.root / "outside" / "agent-cc.jsonl"
        outside.parent.mkdir()
        outside.write_bytes(b'{"id":"outside"}\n')
        (self.subagents / "agent-cc.jsonl").symlink_to(outside)
        workflows = self.subagents / "workflows"
        workflows.mkdir()
        (workflows / "outside").symlink_to(outside.parent, target_is_directory=True)
        inventory = self.freeze()
        self.assertTrue(inventory.complete)
        self.assertEqual(
            [str(self.parent), str(allowed)],
            [stream.cursor.frozen.path for stream in inventory.streams],
        )
        with self.assertRaises(ValueError):
            raw_source.freeze_child(inventory.streams[0].cursor, str(outside))

    def test_child_swapped_to_a_link_to_the_same_inode_is_not_read(self) -> None:
        child = self.child("agent-ab12.jsonl")
        inventory = self.freeze()
        frozen_child = inventory.streams[1].cursor
        target = self.root / "moved.jsonl"
        child.rename(target)
        child.symlink_to(target)
        with mock.patch.object(
            runtime_io,
            "_open_scan_binary",
            side_effect=AssertionError("link must refuse before open"),
        ):
            page = raw_source.read(frozen_child, max_bytes=100, max_seconds=1)
        self.assertEqual("stale", page.state)
        self.assertEqual(0, page.bytes_read)
        self.assertEqual((), page.records)

    def test_later_children_and_appended_child_records_do_not_expand_inventory(self) -> None:
        child = self.child("agent-ab12.jsonl")
        inventory = self.freeze()
        self.child("workflows/later/agent-cc.jsonl", at=100)
        with child.open("ab") as source:
            source.write(b'{"id":"appended"}\n')
        self.assertEqual(["parent", "agent-ab12"], [stream.name for stream in inventory.streams])
        rows, page = self.read_all(inventory.streams[1].cursor)
        self.assertEqual([{"id": "agent-ab12.jsonl"}], rows)
        self.assertTrue(page.source_complete)

    def test_entry_limit_counts_ignored_hostile_entries_and_returns_unknown_gap(self) -> None:
        for number in range(20):
            self.child(f"ignored-{number}.txt")
        inventory = self.freeze(max_entries=3)
        self.assertEqual(3, inventory.entries_examined)
        self.assertEqual(["parent"], [stream.name for stream in inventory.streams])
        self.assertFalse(inventory.complete)
        self.assertEqual(["entries"], [gap.reason for gap in inventory.gaps])

    def test_stream_limit_bounds_retention_and_does_not_claim_complete_inventory(self) -> None:
        for number in range(5):
            self.child(f"agent-{number:x}.jsonl")
        inventory = self.freeze(max_streams=2)
        self.assertEqual(2, len(inventory.streams))
        self.assertFalse(inventory.complete)
        self.assertEqual(["streams"], [gap.reason for gap in inventory.gaps])

    def test_clock_limit_keeps_parent_and_reports_unknown_discovery(self) -> None:
        self.child("agent-aa.jsonl")
        inventory = self.freeze(max_seconds=0)
        self.assertEqual(0, inventory.entries_examined)
        self.assertEqual(["parent"], [stream.name for stream in inventory.streams])
        self.assertFalse(inventory.complete)
        self.assertEqual(["time"], [gap.reason for gap in inventory.gaps])

    def test_unreadable_directory_is_unknown_but_missing_directory_is_empty(self) -> None:
        missing = self.freeze()
        self.assertTrue(missing.complete)
        self.child("agent-aa.jsonl")
        original = os.scandir

        def unreadable(path: Any) -> Any:
            if os.fspath(path) == str(self.subagents):
                raise PermissionError("synthetic unreadable directory")
            return original(path)

        with mock.patch("os.scandir", side_effect=unreadable):
            inventory = self.freeze()
        self.assertFalse(inventory.complete)
        self.assertEqual(["unreadable"], [gap.reason for gap in inventory.gaps])
        self.assertEqual(["parent"], [stream.name for stream in inventory.streams])

    def test_elapsed_clock_stops_after_measured_entry_without_reading_it(self) -> None:
        self.child("agent-aa.jsonl")
        clock = mock.Mock(side_effect=[0, 0, 0, 0, 0, 2])
        inventory = self.freeze(clock=clock)
        self.assertEqual(1, inventory.entries_examined)
        self.assertEqual(["parent"], [stream.name for stream in inventory.streams])
        self.assertEqual(["time"], [gap.reason for gap in inventory.gaps])

    def test_replaced_child_identity_refuses_before_content_open(self) -> None:
        child = self.child("agent-aa.jsonl")
        inventory = self.freeze()
        replacement = self.root / "replacement"
        replacement.write_bytes(child.read_bytes())
        replacement.replace(child)
        with mock.patch.object(
            runtime_io, "_open_scan_binary", side_effect=AssertionError("replacement must refuse")
        ):
            page = raw_source.read(inventory.streams[1].cursor, max_bytes=100, max_seconds=1)
        self.assertEqual(("stale", 0, ()), (page.state, page.bytes_read, page.records))
