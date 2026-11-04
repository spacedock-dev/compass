"""A frozen parent is verified in bounded phases before its raw rows are trusted."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from .test_claude_checks import Transcript


class FrozenParentSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "session.jsonl"

    def module(self) -> Any:
        self.assertIsNotNone(
            importlib.util.find_spec("compass_runtime.reading_source_stream"),
            "the bounded frozen raw-stream reader is not implemented",
        )
        return importlib.import_module("compass_runtime.reading_source_stream")

    def start(self, data: bytes, *, line_max_bytes: int = 1024 * 1024) -> Any:
        self.path.write_bytes(data)
        return self.module().freeze(
            str(self.path), "claude", "parent", line_max_bytes=line_max_bytes
        )

    def advance(self, cursor: Any, *, max_bytes: int = 31, max_seconds: float = 1) -> Any:
        page = self.module().read(cursor, max_bytes=max_bytes, max_seconds=max_seconds)
        self.assertLessEqual(page.bytes_read, max_bytes)
        if page.next is not None:
            self.assertNotEqual((cursor.phase, cursor.offset), (page.next.phase, page.next.offset))
            self.assertLessEqual(len(page.next.fragment), cursor.frozen.line_max_bytes)
        return page

    def drain(self, cursor: Any, *, max_bytes: int = 31) -> list[Any]:
        pages = []
        for _ in range(2_000):
            page = self.advance(cursor, max_bytes=max_bytes)
            pages.append(page)
            if page.next is None:
                return pages
            cursor = page.next
        raise AssertionError("a bounded reader must not spin without finishing or refusing")

    def phase(self, cursor: Any, phase: str) -> tuple[Any, int]:
        spent = 0
        while cursor.phase != phase:
            page = self.advance(cursor)
            spent += page.bytes_read
            self.assertEqual("progress", page.state)
            self.assertIsNotNone(page.next)
            cursor = page.next
        return cursor, spent

    def test_tiny_pages_keep_native_call_result_and_physical_order_exactly_once(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("First request")
        call = transcript.call("Bash", {"command": "pytest tests/widget.py"})
        transcript.prompt("Middle request")
        transcript.rows[-1]["timestamp"] = "2026-09-24T01:00:00Z"
        transcript.result(call, "1 passed", is_error=False)
        raw = b"".join(json.dumps(row).encode() + b"\n" for row in transcript.rows)
        cursor = self.start(raw)
        identity = cursor.frozen.identity
        pages = self.drain(cursor)
        records = [record for page in pages for record in page.records]
        self.assertEqual(transcript.rows, [record.value for record in records])
        self.assertEqual(raw, b"".join(record.raw for record in records))
        self.assertEqual(len(raw) * 3, sum(page.bytes_read for page in pages))
        self.assertEqual(
            [0, *[record.end_offset for record in records[:-1]]],
            [record.start_offset for record in records],
        )
        self.assertEqual("verified", pages[-1].state)
        self.assertTrue(pages[-1].source_complete)
        self.assertTrue(all(not page.source_complete for page in pages[:-1]))
        self.assertTrue(all(page.next.frozen.identity == identity for page in pages if page.next))
        call_page = next(
            i
            for i, page in enumerate(pages)
            if any(record.value == transcript.rows[1] for record in page.records)
        )
        result_page = next(
            i
            for i, page in enumerate(pages)
            if any(record.value == transcript.rows[-1] for record in page.records)
        )
        self.assertLess(call_page, result_page)

    def test_append_after_freeze_is_outside_every_phase(self) -> None:
        raw = b'{"id":"first"}\n{"id":"second"}\n'
        cursor = self.start(raw)
        with self.path.open("ab") as source:
            source.write(b'{"id":"later"}\n')
        pages = self.drain(cursor, max_bytes=7)
        self.assertEqual(
            ["first", "second"], [record.value["id"] for page in pages for record in page.records]
        )
        self.assertTrue(pages[-1].source_complete)
        self.assertEqual(len(raw) * 3, sum(page.bytes_read for page in pages))

    def test_unfinished_frozen_line_stays_a_permanent_gap_after_append_completes_it(self) -> None:
        complete = b'{"id":"first"}\n'
        raw = complete + b'{"id":"unfinished"}'
        cursor = self.start(raw)
        with self.path.open("ab") as source:
            source.write(b'\n{"id":"later"}\n')
        pages = self.drain(cursor, max_bytes=7)
        gaps = [gap for page in pages for gap in page.gaps if gap.permanent]
        self.assertEqual(
            [(len(complete), len(raw), "unfinished_line")],
            [(gap.start_offset, gap.end_offset, gap.reason) for gap in gaps],
        )
        self.assertEqual(
            ["first"], [record.value["id"] for page in pages for record in page.records]
        )
        self.assertEqual("verified", pages[-1].state)
        self.assertFalse(pages[-1].source_complete)

    def test_truncation_or_inode_replacement_refuses_without_reading_other_bytes(self) -> None:
        for movement in ("truncate", "replace"):
            with self.subTest(movement=movement):
                cursor = self.start(b'{"id":"first"}\n{"id":"second"}\n')
                cursor, _ = self.phase(cursor, "records")
                if movement == "truncate":
                    self.path.write_bytes(b"{}\n")
                else:
                    other = self.root / "replacement.jsonl"
                    other.write_bytes(self.path.read_bytes())
                    other.replace(self.path)
                page = self.advance(cursor)
                self.assertEqual("stale", page.state)
                self.assertEqual(0, page.bytes_read)
                self.assertEqual((), page.records)
                self.assertIsNone(page.next)
                self.assertFalse(page.source_complete)

    def test_full_final_verification_detects_an_earlier_same_size_edit(self) -> None:
        raw = b'{"id":"first"}\n{"id":"second"}\n{"id":"third"}\n'
        cursor = self.start(raw)
        cursor, spent = self.phase(cursor, "verify")
        before = self.path.stat()
        with self.path.open("r+b") as source:
            source.write(raw.replace(b"first", b"FIRST"))
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        pages = self.drain(cursor, max_bytes=7)
        self.assertEqual("stale", pages[-1].state)
        self.assertFalse(any(page.source_complete for page in pages))
        self.assertEqual(len(raw) * 3, spent + sum(page.bytes_read for page in pages))
        self.assertEqual((), pages[-1].records)

    def test_oversized_and_malformed_lines_are_bounded_permanent_gaps(self) -> None:
        oversized = b'{"text":"' + b"x" * 80 + b'"}\n'
        malformed = b"not json\n"
        last = b'{"id":"kept"}\n'
        cursor = self.start(oversized + malformed + last, line_max_bytes=24)
        pages = self.drain(cursor, max_bytes=7)
        permanent = [gap for page in pages for gap in page.gaps if gap.permanent]
        self.assertEqual(
            [
                (0, len(oversized), "oversized_line"),
                (len(oversized), len(oversized + malformed), "unreadable_record"),
            ],
            [(gap.start_offset, gap.end_offset, gap.reason) for gap in permanent],
        )
        self.assertTrue(any(not gap.permanent for page in pages for gap in page.gaps))
        self.assertEqual(
            ["kept"], [record.value["id"] for page in pages for record in page.records]
        )
        self.assertEqual("verified", pages[-1].state)
        self.assertFalse(pages[-1].source_complete)

    def test_no_allowance_stops_without_a_spin_cursor_or_rows(self) -> None:
        cursor = self.start(b'{"id":"first"}\n')
        for max_bytes, max_seconds, reason in ((0, 1, "bytes"), (31, 0, "time")):
            with self.subTest(reason=reason):
                page = self.advance(cursor, max_bytes=max_bytes, max_seconds=max_seconds)
                self.assertEqual("limited", page.state)
                self.assertEqual(reason, page.reason)
                self.assertEqual(0, page.bytes_read)
                self.assertEqual((), page.records)
                self.assertIsNone(page.next)

    def test_claude_parent_keeps_existing_follow_link_policy(self) -> None:
        target = self.root / "target.jsonl"
        target.write_bytes(b'{"id":"parent"}\n')
        self.path.symlink_to(target)
        cursor = self.module().freeze(str(self.path), "claude", "parent")
        pages = self.drain(cursor, max_bytes=7)
        self.assertTrue(pages[-1].source_complete)
        self.assertEqual(
            ["parent"], [record.value["id"] for page in pages for record in page.records]
        )

    def test_edit_after_a_verification_slice_refuses_even_an_already_hashed_byte(self) -> None:
        raw = b'{"id":"first"}\n{"id":"second"}\n'
        cursor = self.start(raw)
        cursor, _ = self.phase(cursor, "verify")
        first = self.advance(cursor, max_bytes=7)
        self.assertIsNotNone(first.next)
        with self.path.open("r+b") as source:
            source.write(b"{ ")
        refused = self.advance(first.next, max_bytes=7)
        self.assertEqual("stale", refused.state)
        self.assertFalse(refused.source_complete)
        self.assertEqual(0, refused.bytes_read)

    def test_time_allowance_stops_between_bounded_digest_reads(self) -> None:
        cursor = self.start(b"x" * (128 * 1024))
        ticks = -0.6

        def clock() -> float:
            nonlocal ticks
            ticks += 0.6
            return ticks

        page = self.module().read(cursor, max_bytes=256 * 1024, max_seconds=1, clock=clock)
        self.assertEqual("progress", page.state)
        self.assertEqual("time", page.reason)
        self.assertEqual(64 * 1024, page.bytes_read)
        self.assertEqual(64 * 1024, page.next.offset)

    def test_append_between_native_pages_does_not_expand_the_frozen_endpoint(self) -> None:
        raw = b'{"id":"first"}\n{"id":"second"}\n'
        cursor = self.start(raw)
        cursor, spent = self.phase(cursor, "records")
        first = self.advance(cursor, max_bytes=7)
        self.assertIsNotNone(first.next)
        with self.path.open("ab") as source:
            source.write(b'{"id":"later"}\n')
        pages = [first, *self.drain(first.next, max_bytes=7)]
        self.assertEqual(
            ["first", "second"],
            [record.value["id"] for page in pages for record in page.records],
        )
        self.assertTrue(pages[-1].source_complete)
        self.assertEqual(len(raw) * 3, spent + sum(page.bytes_read for page in pages))
