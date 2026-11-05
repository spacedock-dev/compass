"""Synthetic records exercise the caller-held forward source contract."""

from __future__ import annotations

import dataclasses
import hashlib
import heapq
import importlib
import json
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import (
    claude_data,
    project_context,
    project_scripts,
    reader_checks,
    record_pages,
)
from compass_runtime.config import build_runtime_config

from . import test_record_pages
from .test_claude_checks import Transcript, hook_stdout
from .test_project_script_checks import git, package

if TYPE_CHECKING:
    from collections.abc import Iterator


class SessionSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "session.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.session = Transcript(self.root)
        self.source = importlib.import_module("compass_runtime.session_source")

    def read(self, **kwargs: Any) -> Any:
        return self.source.read(self.config, str(self.path), "claude", "root", **kwargs)

    def save(self) -> None:
        self.session.save(self.path)

    @contextmanager
    def _meter_source_reads(self) -> Iterator[list[int]]:
        total = [0]
        open_binary = self.source.runtime_io._open_binary

        def counted_open(*args: Any, **kwargs: Any) -> Any:
            handle = open_binary(*args, **kwargs)
            proxy = mock.MagicMock(wraps=handle)
            proxy.__enter__.return_value = proxy
            proxy.__exit__.side_effect = handle.__exit__

            def count(method: Any, size: int = -1) -> bytes:
                raw: bytes = method(size)
                total[0] += len(raw)
                return raw

            proxy.readline.side_effect = lambda size=-1: count(handle.readline, size)
            proxy.read.side_effect = lambda size=-1: count(handle.read, size)
            return proxy

        with mock.patch.object(self.source.runtime_io, "_open_binary", side_effect=counted_open):
            yield total

    def changes(self, previous: Any, expected: str, reason: str | None = None) -> None:
        for page in (self.read(), self.read(after=previous.snapshot.cursor)):
            change = self.source.compare(previous.snapshot, page)
            self.assertEqual(expected, change.kind)
            if reason:
                self.assertIn((previous.entries[0].fact_id, reason), change.changed)

    def test_complete_source_exceeds_reading_retention_and_agrees_with_page_ids(self) -> None:
        count = project_context.MAX_PROJECT_EVENTS + project_context.PRESS_ANCHORS + 20
        rows = [test_record_pages.RecordPagesTest.record(i) for i in range(count)]
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        page = self.read()
        self.assertTrue(page.coverage.complete)
        self.assertEqual(count, len(page.entries))
        for row, entry in zip(rows, page.entries, strict=True):
            fact = record_pages._fact(self.config, json.dumps(row).encode(), "claude", "root")
            assert fact is not None
            self.assertEqual(
                fact["fact_id"],
                entry.fact_id,
            )
            self.assertNotIn("words", self.source.entry_for_page(entry))

    def test_tool_ids_match_published_context_facts(self) -> None:
        self.session.bash("pytest tests", "1 passed")
        self.session.write(str(self.root / "src/a.py"))
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/test_child.py", "1 failed", is_error=True)
        child.write(str(self.root / "src/child.py"))
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        events, _ = project_context.claude_tool_reports(self.config, str(self.path), "root")
        facts = [
            project_context._semantic_fact_from_event(event, event["kind"], "tool_report", "")
            for event in events
        ]
        entries = self.read().entries
        # The dict comparison would hide two entries under one id; uniqueness is asserted apart.
        self.assertEqual(len(entries), len({entry.fact_id for entry in entries}))
        self.assertEqual(
            {fact["summary"]: fact["fact_id"] for fact in facts},
            {entry.title: entry.fact_id for entry in entries},
        )

    def test_repeated_check_in_one_call_keeps_distinct_ids_and_latest_record_id(self) -> None:
        self.session.bash("pytest tests; pytest tests", "1 passed")
        self.save()
        entries = self.read().entries
        self.assertEqual(2, len(entries))
        self.assertNotEqual(entries[0].fact_id, entries[1].fact_id)
        events, _ = project_context.claude_tool_reports(self.config, str(self.path), "root")
        fact = project_context._semantic_fact_from_event(events[0], "check_run", "tool_report", "")
        self.assertEqual(fact["fact_id"], entries[-1].fact_id)

    def published_ids(self, kind: str) -> list[str]:
        events, _ = project_context.claude_tool_reports(self.config, str(self.path), "root")
        return [
            project_context._semantic_fact_from_event(event, event["kind"], "tool_report", "")[
                "fact_id"
            ]
            for event in events
            if event["kind"] == kind
        ]

    def test_same_titled_checks_in_two_directories_of_one_call_keep_unique_ids(self) -> None:
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        self.session.bash("cd a && pytest tests; cd ../b && pytest tests", "1 passed")
        self.save()
        first = self.read()
        ids = [entry.fact_id for entry in first.entries]
        self.assertEqual(2, len(ids))
        self.assertEqual(2, len(set(ids)))
        # Each directory's run is its own published entry, with an id apart from the other's.
        self.assertEqual(set(ids), set(self.published_ids("check_run")))
        self.assertEqual("unchanged", self.source.compare(first.snapshot, self.read()).kind)

    def test_foreground_check_followed_by_its_background_run_keeps_the_published_id(
        self,
    ) -> None:
        self.session.bash("pytest tests; pytest tests &", "1 passed")
        self.save()
        entries = self.read().entries
        self.assertEqual(1, len(entries))
        self.assertEqual([entries[0].fact_id], self.published_ids("check_run"))

    def test_redirects_whose_clipped_titles_match_keep_unique_ids(self) -> None:
        folder = "d" * (project_context.TOOL_REPORT_PATH_CHARS + 10)
        (self.root / folder).mkdir()
        # Only a check segment's redirect is a recorded write.
        self.session.bash(
            f"pytest tests > {folder}/one.txt; pytest tests/x > {folder}/two.txt", "1 passed"
        )
        self.save()
        entries = [entry for entry in self.read().entries if entry.kind == "file"]
        self.assertEqual(2, len(entries))
        self.assertEqual(entries[0].title, entries[1].title)
        self.assertNotEqual(entries[0].fact_id, entries[1].fact_id)
        # Published, both writes derive one id (the accepted collision); the first write holds it.
        self.assertEqual({entries[0].fact_id}, set(self.published_ids("path_written")))

    def test_newest_window_names_the_unread_prefix(self) -> None:
        self.path.write_text(
            "".join(
                json.dumps(test_record_pages.RecordPagesTest.record(i)) + "\n" for i in range(140)
            )
        )
        page = self.read(newest=True, max_bytes=2500)
        self.assertFalse(page.coverage.complete)
        self.assertEqual(page.entries[0].fact_id, page.coverage.starts_at)
        region = page.coverage.unread[0]
        self.assertEqual(
            (0, page.coverage.start_offset, "before_window"),
            (region.start_offset, region.end_offset, region.reason),
        )

    def test_forward_pages_return_every_message_once(self) -> None:
        rows = [test_record_pages.RecordPagesTest.record(i) for i in range(140)]
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        entries = []
        cursor = None
        for _ in range(100):
            page = self.read(after=cursor, max_bytes=2500)
            entries.extend(page.entries)
            cursor = page.next
            if cursor is None:
                break
        self.assertIsNone(cursor)
        self.assertEqual([e.fact_id for e in self.read().entries], [e.fact_id for e in entries])

    def test_append_only(self) -> None:
        self.session.prompt("Start the synthetic task.")
        self.save()
        previous = self.read()
        self.session.prompt("Continue with the next task.")
        self.save()
        self.changes(previous, "appended")

    def test_check_rerun_names_the_earlier_fact(self) -> None:
        self.session.bash("pytest tests", "1 passed")
        self.save()
        previous = self.read()
        self.session.bash("pytest tests", "1 failed", is_error=True)
        self.save()
        self.changes(previous, "changed_earlier", "check_result")

    def test_file_rewritten_names_the_earlier_fact(self) -> None:
        self.session.write(str(self.root / "src/a.py"))
        self.save()
        previous = self.read()
        self.session.edit(str(self.root / "src/a.py"))
        self.save()
        self.changes(previous, "changed_earlier", "file_rewritten")

    def test_pending_result_is_paired_across_pages(self) -> None:
        call = self.session.call("Bash", {"command": "pytest tests"})
        self.save()
        previous = self.read()
        self.assertEqual((call,), previous.snapshot.pending_calls)
        self.session.result(call, "1 passed", is_error=False)
        self.save()
        self.changes(previous, "changed_earlier", "check_result")
        self.assertEqual("passed", self.read(after=previous.snapshot.cursor).entries[0].result)

    def test_outline_checkpoint_rehydrates_only_the_touched_call_without_retaining_input(
        self,
    ) -> None:
        sentinel = "PRIVATE_INPUT_MUST_NOT_SURVIVE"
        untouched = self.session.call("Read", {"file_path": str(self.root / sentinel)})
        call = self.session.call("Bash", {"command": f"pytest tests # {sentinel}"})
        self.save()
        split = self.path.stat().st_size
        self.session.result(call, "1 passed", is_error=False)
        self.save()
        deadline = time.monotonic() + 30
        first_budget = self.source._Budget(split, deadline, deadline)
        first = self.source._read_stream(
            self.config,
            str(self.path),
            "parent",
            "claude",
            "root",
            first_budget,
            None,
            newest=False,
        )
        page = self.source._finish(
            self.config, str(self.path), "claude", "root", [first], [], None, first_budget
        )
        checkpoint = self.source._outline_checkpoint(
            str(self.path), "claude", "root", first, page.snapshot.cursor.pending
        )
        self.assertEqual({untouched, call}, {item.call_id for item in checkpoint.calls})
        retained = json.dumps(dataclasses.asdict(checkpoint))
        for prohibited in (sentinel, "input_json", "fragment", "words", "cwd", "command"):
            self.assertNotIn(prohibited, retained)
        self.assertFalse(any(isinstance(value, bytes) for value in dataclasses.astuple(checkpoint)))

        # The result scan, prior boundary verification, and input reread share this one budget.
        allowance = self.path.stat().st_size * 2
        budget = self.source._Budget(allowance, deadline, deadline)
        actual_bytes = 0
        open_binary = self.source.runtime_io._open_binary

        def counted_open(*args: Any, **kwargs: Any) -> Any:
            handle = open_binary(*args, **kwargs)
            proxy = mock.MagicMock(wraps=handle)
            proxy.__enter__.return_value = proxy
            proxy.__exit__.side_effect = handle.__exit__

            def count(method: Any, size: int = -1) -> bytes:
                nonlocal actual_bytes
                raw: bytes = method(size)
                actual_bytes += len(raw)
                return raw

            proxy.readline.side_effect = lambda size=-1: count(handle.readline, size)
            proxy.read.side_effect = lambda size=-1: count(handle.read, size)
            return proxy

        with mock.patch.object(self.source.runtime_io, "_open_binary", side_effect=counted_open):
            later = self.source._read_stream(
                self.config,
                str(self.path),
                "parent",
                "claude",
                "root",
                budget,
                first.cursor,
                newest=False,
            )
            pending = self.source._outline_pending(
                str(self.path), "claude", "root", checkpoint, later, budget
            )
        self.assertIsNotNone(pending)
        self.assertEqual((call,), tuple(item.call_id for item in pending))
        self.assertEqual(budget.used, actual_bytes)
        self.assertLessEqual(actual_bytes, allowance)
        self.assertGreater(actual_bytes, self.path.stat().st_size - split)
        resumed = self.source._finish(
            self.config,
            str(self.path),
            "claude",
            "root",
            [later],
            [],
            dataclasses.replace(page.snapshot.cursor, pending=pending),
            budget,
        )
        checks = [entry for entry in resumed.entries if entry.kind == "check"]
        self.assertEqual(["passed"], [entry.result for entry in checks])
        self.assertEqual(
            [entry.fact_id for entry in self.read().entries if entry.kind == "check"],
            [entry.fact_id for entry in checks],
        )
        self.assertEqual(page.positions, resumed.positions)
        self.assertEqual(
            (
                (
                    tuple(entry.fact_id for entry in page.entries),
                    tuple(entry.fact_id for entry in checks),
                ),
            ),
            resumed.replacements,
        )
        continued = self.source._outline_checkpoint(
            str(self.path), "claude", "root", later, resumed.snapshot.cursor.pending, checkpoint
        )
        self.assertEqual((untouched,), tuple(item.call_id for item in continued.calls))
        self.assertEqual((), continued.calls[0].fact_ids)

    def test_outline_checkpoint_defers_unfit_inputs_and_rejects_invalid_locators(self) -> None:
        call = self.session.call("Bash", {"command": "pytest tests"})
        self.save()
        split = self.path.stat().st_size
        self.session.result(call, "1 passed", is_error=False)
        self.save()
        deadline = time.monotonic() + 30
        first_budget = self.source._Budget(split, deadline, deadline)
        first = self.source._read_stream(
            self.config,
            str(self.path),
            "parent",
            "claude",
            "root",
            first_budget,
            None,
            newest=False,
        )
        page = self.source._finish(
            self.config, str(self.path), "claude", "root", [first], [], None, first_budget
        )
        checkpoint = self.source._outline_checkpoint(
            str(self.path), "claude", "root", first, page.snapshot.cursor.pending
        )
        retained = json.dumps(dataclasses.asdict(checkpoint))
        allowance = self.path.stat().st_size * 2
        budget = self.source._Budget(allowance, deadline, deadline)
        later = self.source._read_stream(
            self.config,
            str(self.path),
            "parent",
            "claude",
            "root",
            budget,
            first.cursor,
            newest=False,
        )
        # An exhausted poll defers rehydration without spending a new allowance or dropping input.
        needed = checkpoint.calls[0].line.end - checkpoint.calls[0].line.start
        short = self.source._Budget(needed - 1, deadline, deadline)
        self.assertIsNone(
            self.source._outline_pending(str(self.path), "claude", "root", checkpoint, later, short)
        )
        self.assertEqual(0, short.used)
        self.assertEqual(retained, json.dumps(dataclasses.asdict(checkpoint)))
        self.assertEqual(
            (),
            self.source._outline_pending(
                str(self.path),
                "claude",
                "root",
                checkpoint,
                first,
                self.source._Budget(0, deadline, deadline),
            ),
        )
        for limit in ("_OUTLINE_PENDING_LIMIT", "_OUTLINE_CHECKPOINT_BYTES"):
            with (
                mock.patch.object(self.source, limit, 0),
                self.assertRaisesRegex(ValueError, "outline_state_limit"),
            ):
                self.source._outline_checkpoint(
                    str(self.path), "claude", "root", first, page.snapshot.cursor.pending
                )
        with self.assertRaises(self.source._SourceChangedError):
            self.source._outline_pending(
                str(self.path), "claude", "other", checkpoint, later, budget
            )
        damaged = dataclasses.replace(
            checkpoint,
            calls=(
                dataclasses.replace(
                    checkpoint.calls[0],
                    line=dataclasses.replace(checkpoint.calls[0].line, digest="0" * 64),
                ),
            ),
        )
        with self.assertRaises(self.source._SourceChangedError):
            self.source._outline_pending(
                str(self.path),
                "claude",
                "root",
                damaged,
                later,
                self.source._Budget(allowance, deadline, deadline),
            )

    def test_outline_checkpoint_locates_latest_rewrite_for_a_later_result(self) -> None:
        call = self.session.call("Bash", {"command": "echo PRIVATE_ORIGINAL_INPUT"})
        self.session.hook_rewrite(call, hook_stdout("pytest tests"))
        self.session.hook_rewrite(call, hook_stdout("rtk pytest tests"))
        self.save()
        split = self.path.stat().st_size
        self.session.result(call, "1 failed", is_error=False)
        self.save()
        deadline = time.monotonic() + 30
        first_budget = self.source._Budget(split, deadline, deadline)
        first = self.source._read_stream(
            self.config,
            str(self.path),
            "parent",
            "claude",
            "root",
            first_budget,
            None,
            newest=False,
        )
        page = self.source._finish(
            self.config, str(self.path), "claude", "root", [first], [], None, first_budget
        )
        checkpoint = self.source._outline_checkpoint(
            str(self.path), "claude", "root", first, page.snapshot.cursor.pending
        )
        self.assertEqual(0, checkpoint.calls[0].line.start)
        self.assertEqual(first.row_cursors[2].line_start, checkpoint.calls[0].rewrite.start)
        self.assertEqual(
            first.row_cursors[2].line_start, dict(page.observations)[page.entries[0].fact_id]
        )
        self.assertNotIn("PRIVATE_ORIGINAL_INPUT", json.dumps(dataclasses.asdict(checkpoint)))
        budget = self.source._Budget(self.path.stat().st_size * 3, deadline, deadline)
        later = self.source._read_stream(
            self.config,
            str(self.path),
            "parent",
            "claude",
            "root",
            budget,
            first.cursor,
            newest=False,
        )
        pending = self.source._outline_pending(
            str(self.path), "claude", "root", checkpoint, later, budget
        )
        self.assertIsNotNone(pending)
        self.assertEqual("rtk pytest tests", json.loads(pending[0].input_json)["command"])
        resumed = self.source._finish(
            self.config,
            str(self.path),
            "claude",
            "root",
            [later],
            [],
            dataclasses.replace(page.snapshot.cursor, pending=pending),
            budget,
        )
        self.assertEqual(["not-recorded"], [entry.result for entry in resumed.entries])
        self.assertEqual(split, dict(resumed.observations)[resumed.entries[0].fact_id])
        self.assertEqual(self.read().entries, resumed.entries)
        self.assertEqual(page.positions, resumed.positions)
        finished = self.source._outline_checkpoint(
            str(self.path), "claude", "root", later, resumed.snapshot.cursor.pending, checkpoint
        )
        self.assertEqual((), finished.calls)

    def test_outline_parent_pages_resolve_a_later_rewrite_and_result_without_raw_state(
        self,
    ) -> None:
        call = self.session.call("Bash", {"command": "python3 -m pytest tests"})
        for number in range(3):
            self.session.prompt(f"Before rewrite {number}. " + "padding " * 100)
        self.session.hook_rewrite(call, hook_stdout("rtk pytest tests"))
        for number in range(3):
            self.session.prompt(f"Before result {number}. " + "padding " * 100)
        self.session.result(call, "1 failed", is_error=False)
        self.save()
        checkpoint = None
        facts: dict[str, Any] = {}
        positions: dict[str, Any] = {}
        held_rewrite = False
        held_unresolved = False
        transient_words = False
        for _poll in range(30):
            page, checkpoint = self.source._read_outline_parent(
                self.config,
                str(self.path),
                "claude",
                "root",
                after=checkpoint,
                max_bytes=3000,
                deadline=time.monotonic() + 30,
            )
            self.assertEqual("ok", page.state)
            self.assertLessEqual(page.bytes_read, 3000)
            self.assertIsNone(page.next)
            self.assertIsNone(page.snapshot)
            self.assertFalse(page.coverage.complete)  # Children have not been admitted yet.
            self.assertIsNotNone(checkpoint)
            retained = repr(checkpoint)
            for prohibited in (
                "SourceCursor",
                "SourceSnapshot",
                "input_json",
                "fragment=",
                "words=",
            ):
                self.assertNotIn(prohibited, retained)
            for old, _new in page.replacements:
                for fact_id in old:
                    facts.pop(fact_id, None)
                    positions.pop(fact_id, None)
            facts.update((entry.fact_id, entry) for entry in page.entries)
            positions.update(page.positions)
            transient_words |= any(entry.words for entry in page.entries)
            held_unresolved |= bool(checkpoint.calls)
            held_rewrite |= any(item.rewrite is not None for item in checkpoint.calls)
            if checkpoint.parent_complete:
                break
        assert checkpoint is not None
        self.assertTrue(checkpoint.parent_complete)
        self.assertTrue(held_unresolved)
        self.assertTrue(held_rewrite)
        self.assertTrue(transient_words)
        whole = self.read()
        self.assertEqual({entry.fact_id: entry for entry in whole.entries}, facts)
        self.assertEqual(dict(whole.positions), positions)
        self.assertEqual(
            ["not-recorded"], [entry.result for entry in facts.values() if entry.kind == "check"]
        )

    def test_outline_parent_whole_api_meters_bytes_and_never_rereads_head_for_git(self) -> None:
        self.session.prompt("Read the owned transcript.")
        self.session.bash("pytest tests", "1 passed")
        self.save()
        config = dataclasses.replace(self.config, git_probe_enabled=True)
        actual_bytes = 0
        open_binary = self.source.runtime_io._open_binary

        def counted_open(*args: Any, **kwargs: Any) -> Any:
            handle = open_binary(*args, **kwargs)
            proxy = mock.MagicMock(wraps=handle)
            proxy.__enter__.return_value = proxy
            proxy.__exit__.side_effect = handle.__exit__

            def count(method: Any, size: int = -1) -> bytes:
                nonlocal actual_bytes
                raw: bytes = method(size)
                actual_bytes += len(raw)
                return raw

            proxy.readline.side_effect = lambda size=-1: count(handle.readline, size)
            proxy.read.side_effect = lambda size=-1: count(handle.read, size)
            return proxy

        with (
            mock.patch.object(self.source.runtime_io, "_open_binary", side_effect=counted_open),
            mock.patch.object(
                claude_data,
                "head_cwd",
                side_effect=AssertionError("unmetered cwd read"),
            ),
            mock.patch.object(
                claude_data,
                "head_start",
                side_effect=AssertionError("unmetered timestamp read"),
            ),
            mock.patch.object(project_scripts, "load", return_value=None),
        ):
            page, checkpoint = self.source._read_outline_parent(
                config,
                str(self.path),
                "claude",
                "root",
                max_bytes=10000,
                deadline=time.monotonic() + 30,
            )
        self.assertEqual(self.path.stat().st_size, actual_bytes)
        self.assertEqual(actual_bytes, page.bytes_read)
        self.assertTrue(checkpoint.parent_complete)
        self.assertEqual(str(self.root), checkpoint.head[0])
        self.assertIsNotNone(checkpoint.head[1])
        self.assertEqual(
            ["passed"], [entry.result for entry in page.entries if entry.kind == "check"]
        )

    def test_outline_parent_keeps_admitted_head_metadata_before_a_later_gap(self) -> None:
        self.session.prompt("The known opening.")
        self.session.prompt("A later record after a gap.")
        self.save()
        lines = self.path.read_bytes().splitlines(keepends=True)
        self.path.write_bytes(lines[0] + b"{broken-record}\n" + lines[1])
        page, checkpoint = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=5000,
            deadline=time.monotonic() + 30,
        )
        self.assertEqual(str(self.root), checkpoint.head[0])
        self.assertEqual(
            self.source.records.parse_ts(self.session.rows[0]["timestamp"]), checkpoint.head[1]
        )
        self.assertIn("unreadable_record", [region.reason for region in page.coverage.unread])
        self.assertFalse(checkpoint.parent_complete)

    def test_outline_parent_verifies_the_prior_boundary_even_when_stamps_match(self) -> None:
        # Keep the serialized cwd variation real and owned, including Linux-sized temp paths.
        with tempfile.TemporaryDirectory(
            prefix="c", dir="/tmp" if os.name == "posix" else None
        ) as owned:
            short = Path(owned)
            long = short / ("long-cwd-" + "x" * 80)
            long.mkdir()
            for cwd in (short, long):
                with self.subTest(cwd_bytes=len(str(cwd).encode())):
                    self.session = Transcript(cwd)
                    self.session.prompt("The first owned record.")
                    self.session.prompt("A later owned record.")
                    self.save()
                    first_record_bytes = len(self.path.read_bytes().splitlines(keepends=True)[0])
                    _page, checkpoint = self.source._read_outline_parent(
                        self.config,
                        str(self.path),
                        "claude",
                        "root",
                        max_bytes=first_record_bytes,
                        deadline=time.monotonic() + 30,
                    )
                    self.assertGreater(checkpoint.frontier.end_offset, 0)
                    self.assertEqual(first_record_bytes, checkpoint.frontier.end_offset)
                    self.assertFalse(checkpoint.parent_complete)
                    wrong, wrong_checkpoint = self.source._read_outline_parent(
                        self.config,
                        str(self.path),
                        "claude",
                        "other",
                        after=checkpoint,
                        max_bytes=10000,
                        deadline=time.monotonic() + 30,
                    )
                    self.assertEqual("stale", wrong.state)
                    self.assertIsNone(wrong_checkpoint)
                    stamp = self.path.stat()
                    with self.path.open("r+b") as stream:
                        stream.seek(checkpoint.frontier.boundary_start)
                        stream.write(b"[")
                    os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
                    stale, stale_checkpoint = self.source._read_outline_parent(
                        self.config,
                        str(self.path),
                        "claude",
                        "root",
                        after=checkpoint,
                        max_bytes=10000,
                        deadline=time.monotonic() + 30,
                    )
                    self.assertEqual("stale", stale.state)
                    self.assertIsNone(stale_checkpoint)

    def test_outline_parent_retention_limit_refuses_without_publishing_the_checkpoint(self) -> None:
        self.session.prompt("Owned input with a tiny retained-state allowance.")
        self.save()
        with mock.patch.object(self.source, "_OUTLINE_CHECKPOINT_BYTES", 1):
            page, checkpoint = self.source._read_outline_parent(
                self.config,
                str(self.path),
                "claude",
                "root",
                max_bytes=10000,
                deadline=time.monotonic() + 30,
            )
        self.assertEqual("limited", page.state)
        self.assertIsNone(checkpoint)
        self.assertEqual((), page.entries)
        self.assertEqual(
            ["outline_state_limit"], [region.reason for region in page.coverage.unread]
        )

    def test_outline_parent_unfinished_eof_is_not_complete_or_retained_as_raw_bytes(self) -> None:
        self.session.prompt("PRIVATE_UNFINISHED_WORDS " * 10)
        self.save()
        self.path.write_bytes(self.path.read_bytes().rstrip(b"\n"))
        page, checkpoint = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=2000,
            deadline=time.monotonic() + 30,
        )
        self.assertEqual(self.path.stat().st_size, checkpoint.frontier.offset)
        self.assertEqual(0, checkpoint.frontier.end_offset)
        self.assertFalse(checkpoint.parent_complete)
        self.assertEqual((), page.entries)
        self.assertIn("partial_line", [region.reason for region in page.coverage.unread])
        self.assertNotIn("PRIVATE_UNFINISHED_WORDS", repr(checkpoint))
        again, continued = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=checkpoint,
            max_bytes=2000,
            deadline=time.monotonic() + 30,
        )
        self.assertFalse(continued.parent_complete)
        self.assertEqual(checkpoint.frontier.offset, continued.frontier.offset)
        self.assertIn("partial_line", [region.reason for region in again.coverage.unread])

    def test_outline_tail_outcome_authority_is_later_than_a_revisited_prefix_result(self) -> None:
        self.session.prompt("Run the owned check.")
        call = self.session.call("Bash", {"command": "pytest tests"})
        for number in range(4):
            self.session.prompt(f"Before first result {number}. " + "padding " * 50)
        earlier = len(self.session.rows)
        self.session.result(call, "1 passed", is_error=False)
        for number in range(8):
            self.session.prompt(f"Before latest result {number}. " + "padding " * 50)
        latest = len(self.session.rows)
        self.session.result(call, "Exit code 1\n1 failed", is_error=True)
        self.session.prompt("After the last result. " + "padding " * 130)
        self.save()
        lines = self.path.read_bytes().splitlines(keepends=True)
        earlier_offset = sum(map(len, lines[:earlier]))
        latest_offset = sum(map(len, lines[:latest]))
        page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=6000,
            opening_bytes=1800,
            deadline=time.monotonic() + 30,
        )
        checks = [entry for entry in page.entries if entry.kind == "check"]
        self.assertEqual(["failed"], [entry.result for entry in checks])
        fact_id = checks[0].fact_id
        self.assertEqual(latest_offset, dict(page.observations)[fact_id])
        self.assertEqual(len(lines[0]), dict(page.positions)[fact_id][0])
        for _poll in range(20):
            prefix, checkpoint = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                after=checkpoint,
                max_bytes=6000,
                opening_bytes=1800,
                deadline=time.monotonic() + 30,
            )
            if any(
                entry.fact_id == fact_id and entry.result == "passed" for entry in prefix.entries
            ):
                self.assertEqual(earlier_offset, dict(prefix.observations)[fact_id])
                self.assertIn(earlier_offset, prefix.replacement_observations)
                break
        else:
            self.fail("the forward prefix never revisited the earlier passed result")

    def test_refused_call_replacement_carries_the_result_observation_without_a_new_fact(
        self,
    ) -> None:
        call = self.session.call("Bash", {"command": "pytest tests"})
        self.save()
        previous = self.read()
        result_offset = self.path.stat().st_size
        self.session.result(call, "Permission denied by reader.", is_error=True)
        self.save()
        page = self.read(after=previous.snapshot.cursor)
        self.assertEqual((), page.entries)
        self.assertEqual(
            ((tuple(entry.fact_id for entry in previous.entries), ()),), page.replacements
        )
        self.assertEqual((result_offset,), page.replacement_observations)

    def test_outline_bootstrap_meters_first_latest_and_forward_middle_in_one_budget(self) -> None:
        for number in range(12):
            self.session.prompt(f"Owned phase {number}. " + "padding " * 30)
            self.session.bash(f"pytest tests/test_{number}.py", "1 passed")
            self.session.write(str(self.root / f"src/file_{number}.py"))
        self.save()
        whole = self.read()
        expected = {entry.fact_id: entry for entry in whole.entries}
        prompts = [entry.fact_id for entry in whole.entries if entry.kind == "person"]
        self.assertEqual(12, sum(entry.kind == "check" for entry in whole.entries))
        self.assertEqual(12, sum(entry.kind == "file" for entry in whole.entries))
        self.assertGreater(self.path.stat().st_size, 18000)
        checkpoint = None
        facts: dict[str, Any] = {}
        accepted: tuple[tuple[int, int], ...] = ()
        with self._meter_source_reads() as reads:
            for poll in range(100):
                before = reads[0]
                page, checkpoint = self.source._read_outline(
                    self.config,
                    str(self.path),
                    "claude",
                    "root",
                    after=checkpoint,
                    max_bytes=6000,
                    opening_bytes=1800,
                    deadline=time.monotonic() + 30,
                )
                self.assertEqual("ok", page.state)
                self.assertEqual(reads[0] - before, page.bytes_read)
                self.assertLessEqual(page.bytes_read, 6000)
                self.assertFalse(page.coverage.complete)
                self.assertTrue(
                    all(
                        any(
                            start <= old_start and old_end <= end
                            for start, end in checkpoint.accepted
                        )
                        for old_start, old_end in accepted
                    )
                )
                accepted = checkpoint.accepted
                for old, _new in page.replacements:
                    for fact_id in old:
                        facts.pop(fact_id, None)
                facts.update((entry.fact_id, entry) for entry in page.entries)
                if poll == 0:
                    self.assertTrue({prompts[0], prompts[-1]} <= facts.keys())
                    self.assertEqual(2, len(accepted))
                    self.assertEqual(0, accepted[0][0])
                    self.assertEqual(self.path.stat().st_size, accepted[-1][1])
                    self.assertLess(accepted[0][1], accepted[1][0])
                if checkpoint.parent_complete:
                    break
        assert checkpoint is not None
        self.assertTrue(checkpoint.parent_complete)
        self.assertEqual(((0, self.path.stat().st_size),), accepted)
        self.assertEqual(expected, facts)

    def test_outline_bootstrap_defers_a_fitting_tail_result_without_inventing_an_input_limit(
        self,
    ) -> None:
        call = self.session.call("Bash", {"command": "pytest tests # " + "x" * 200})
        for number in range(8):
            self.session.prompt(f"Owned middle {number}. " + "padding " * 50)
        self.session.result(call, "1 passed", is_error=False)
        self.save()
        page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=2000,
            opening_bytes=1400,
            deadline=time.monotonic() + 30,
        )
        self.assertNotIn("outline_input_limit", [gap.reason for gap in page.coverage.unread])
        self.assertEqual((), checkpoint.gaps)

    def test_outline_bootstrap_opening_slice_does_not_refuse_a_record_fitting_the_poll(
        self,
    ) -> None:
        self.session.prompt("The actual opening. " + "padding " * 100)
        for number in range(20):
            self.session.prompt(f"Owned later prompt {number}. " + "padding " * 30)
        self.save()
        page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=3000,
            opening_bytes=100,
            deadline=time.monotonic() + 30,
        )
        self.assertEqual(0, checkpoint.frontier.end_offset)
        self.assertEqual((), checkpoint.gaps)
        self.assertFalse(checkpoint.stopped)
        self.assertNotIn("outline_line_limit", [gap.reason for gap in page.coverage.unread])
        later, continued = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=checkpoint,
            max_bytes=3000,
            opening_bytes=100,
            deadline=time.monotonic() + 30,
        )
        self.assertGreater(continued.frontier.end_offset, 0)
        self.assertTrue(later.entries[0].title.startswith("The actual opening."))

    def test_outline_bootstrap_expired_shared_deadline_reports_time_without_source_bytes(
        self,
    ) -> None:
        self.session.prompt("An owned record after the deadline.")
        self.save()
        with self._meter_source_reads() as reads:
            page, checkpoint = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                max_bytes=6000,
                opening_bytes=1000,
                deadline=0,
            )
        self.assertEqual(0, reads[0])
        self.assertEqual(0, page.bytes_read)
        self.assertEqual((), page.entries)
        self.assertEqual((), checkpoint.accepted)
        self.assertEqual(["time"], [gap.reason for gap in page.coverage.unread])

    def test_outline_bootstrap_complete_transient_page_requires_an_empty_child_inventory(
        self,
    ) -> None:
        self.session.prompt("A complete small owned input with all its words.")
        self.session.bash("pytest tests", "1 passed")
        self.save()
        page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=10000,
            opening_bytes=1,
            deadline=time.monotonic() + 30,
        )
        self.assertTrue(page.coverage.complete)
        self.assertTrue(checkpoint.parent_complete)
        self.assertEqual(self.read().entries, page.entries)
        self.assertEqual("A complete small owned input with all its words.", page.entries[0].words)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 failed", is_error=True)
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        partial, parent = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=10000,
            opening_bytes=1,
            deadline=time.monotonic() + 30,
        )
        self.assertTrue(parent.parent_complete)
        self.assertFalse(partial.coverage.complete)
        self.assertIn("children_not_read", [gap.reason for gap in partial.coverage.unread])
        self.assertTrue(all(entry.stream == "parent" for entry in partial.entries))

    def save_outline_child(self, child: Transcript, name: str = "agent-ab12.jsonl") -> Path:
        path = self.path.with_suffix("") / "subagents" / name
        for row in child.rows:
            row["isSidechain"] = True
        child.save(path)
        return path

    def test_outline_children_progress_fairly_with_canonical_facts_and_one_budget(self) -> None:
        for number in range(10):
            self.session.prompt(f"Owned parent phase {number}. " + "padding " * 60)
            self.session.bash(f"pytest tests/parent_{number}.py", "1 passed")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child_first.py", "1 failed", is_error=True)
        call = child.call("Bash", {"command": "pytest tests/old.py"})
        for number in range(5):
            child.prompt(f"PRIVATE_CHILD_PADDING {number}. " + "private " * 100)
        child.hook_rewrite(call, hook_stdout("pytest tests/new.py"))
        for number in range(5):
            child.prompt(f"PRIVATE_CHILD_AFTER_REWRITE {number}. " + "private " * 100)
        child.result(call, "1 passed")
        child.bash("pytest tests/backward.py", "1 passed")
        child.rows[-2]["timestamp"] = child.rows[0]["timestamp"]
        self.save_outline_child(child)
        sibling = Transcript(self.root)
        sibling.bash("pytest tests/sibling.py", "1 passed")
        self.save_outline_child(sibling, "workflows/owned/agent-ab12.jsonl")
        whole = self.read()
        self.assertTrue(whole.coverage.complete)
        facts: dict[str, Any] = {}
        positions: dict[str, Any] = {}
        checkpoint = None
        progressed: set[str] = set()
        held_child = False
        with self._meter_source_reads() as reads:
            for poll in range(80):
                before = reads[0]
                page, checkpoint = self.source._read_outline(
                    self.config,
                    str(self.path),
                    "claude",
                    "root",
                    after=checkpoint,
                    max_bytes=2800,
                    opening_bytes=900,
                    deadline=time.monotonic() + 30,
                )
                self.assertIsNotNone(checkpoint)
                self.assertTrue(
                    hasattr(checkpoint, "children"), "sanitized child frontiers are missing"
                )
                self.assertEqual("ok", page.state)
                self.assertEqual(reads[0] - before, page.bytes_read)
                self.assertLessEqual(page.bytes_read, 2800)
                self.assert_outline_checkpoint_private(checkpoint)
                self.assertNotIn("PRIVATE_CHILD_PADDING", repr(checkpoint))
                progressed.update(entry.stream for entry in page.entries)
                held_child |= any(state.calls for _, state in checkpoint.children)
                for old, _new in page.replacements:
                    for fact_id in old:
                        facts.pop(fact_id, None)
                facts.update((entry.fact_id, entry) for entry in page.entries)
                positions.update(page.positions)
                if poll == 2:
                    self.assertEqual(
                        {"parent", "agent-ab12", "workflows/owned/agent-ab12"}, progressed
                    )
                if checkpoint.complete:
                    break
        assert checkpoint is not None
        self.assertTrue(checkpoint.complete)
        self.assertTrue(held_child)
        self.assertEqual({entry.fact_id: entry for entry in whole.entries}, facts)
        streams = ["parent", *sorted({entry.stream for entry in facts.values()} - {"parent"})]
        groups = [
            sorted(
                (entry for entry in facts.values() if entry.stream == stream),
                key=lambda entry: positions[entry.fact_id],
            )
            for stream in streams
        ]
        self.assertEqual(whole.entries, tuple(heapq.merge(*groups, key=lambda entry: entry.at)))
        self.assertEqual(self.source.source_stamps(str(self.path), "claude"), checkpoint.inventory)

    def test_outline_child_changes_and_inventory_changes_reject_the_generation(self) -> None:
        self.session.prompt("Owned parent request.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        child_path = self.save_outline_child(child)
        for change in ("append", "inventory"):
            with self.subTest(change=change):
                _page, checkpoint = self.source._read_outline(
                    self.config,
                    str(self.path),
                    "claude",
                    "root",
                    max_bytes=3000,
                )
                if change == "append":
                    child.bash("pytest tests/later.py", "1 passed")
                    self.save_outline_child(child)
                else:
                    self.save_outline_child(child, "agent-cd34.jsonl")
                page, refused = self.source._read_outline(
                    self.config,
                    str(self.path),
                    "claude",
                    "root",
                    after=checkpoint,
                    max_bytes=3000,
                )
                self.assertEqual("stale", page.state)
                self.assertIsNone(refused)
                self.assertEqual(0, page.bytes_read)
        self.assertTrue(child_path.is_file())

    def test_outline_child_inventory_refuses_links_and_has_a_finite_cap(self) -> None:
        self.session.prompt("Owned parent request.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        child_path = self.save_outline_child(child)
        link = child_path.with_name("agent-dead.jsonl")
        link.symlink_to(child_path)
        _page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=3000,
        )
        self.assertTrue(hasattr(checkpoint, "children"), "bounded child inventory is missing")
        self.assertEqual([str(child_path)], [path for path, _ in checkpoint.children])
        with mock.patch.object(self.source, "_OUTLINE_STREAM_LIMIT", 1):
            limited, refused = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                max_bytes=3000,
            )
        self.assertEqual("limited", limited.state)
        self.assertIsNone(refused)
        self.assertIn("outline_stream_limit", [gap.reason for gap in limited.coverage.unread])
        self.assertFalse(limited.coverage.complete)

    def test_outline_child_collection_shares_one_checkpoint_byte_cap(self) -> None:
        self.session.prompt("Owned short parent.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        with mock.patch.object(self.source, "_OUTLINE_CHECKPOINT_BYTES", 1800):
            allowed, checkpoint = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                max_bytes=3000,
            )
            self.assertEqual("ok", allowed.state)
            self.assertIsNotNone(checkpoint)
            for number in range(3):
                self.save_outline_child(child, f"agent-{number:080x}.jsonl")
            refused, checkpoint = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                max_bytes=3000,
            )
        self.assertEqual("limited", refused.state)
        self.assertIsNone(checkpoint)
        self.assertIn("outline_state_limit", [gap.reason for gap in refused.coverage.unread])

    def test_outline_inventory_change_during_read_refuses_candidate(self) -> None:
        self.session.prompt("Owned parent.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        read_page = self.source._outline_parent_page

        def changed(*args: Any, **kwargs: Any) -> Any:
            result = read_page(*args, **kwargs)
            self.save_outline_child(child)
            return result

        with mock.patch.object(self.source, "_outline_parent_page", side_effect=changed):
            page, checkpoint = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                max_bytes=3000,
            )
        self.assertEqual("stale", page.state)
        self.assertIsNone(checkpoint)

    def test_outline_inventory_does_not_enumerate_linked_directories(self) -> None:
        self.session.prompt("Owned parent.")
        self.save()
        directory = self.path.with_suffix("") / "subagents"
        directory.mkdir(parents=True)
        external = self.root / "owned-external"
        external.mkdir()
        (external / "agent-ab12.jsonl").write_text("PRIVATE_EXTERNAL_SENTINEL")
        scan = os.scandir
        visited: list[str] = []

        def recording(path: str) -> Any:
            visited.append(os.path.realpath(path))
            return scan(path)

        for target in (directory / "workflows", directory / "workflows" / "linked"):
            with self.subTest(target=target):
                target.parent.mkdir(exist_ok=True)
                target.symlink_to(external, target_is_directory=True)
                with mock.patch.object(self.source.os, "scandir", side_effect=recording):
                    stamps = self.source._outline_stamps(
                        str(self.path),
                        "claude",
                        deadline=time.monotonic() + 30,
                    )
                self.assertEqual(1, len(stamps))
                self.assertNotIn(str(external), visited)
                target.unlink()

    def test_outline_child_unfinished_eof_remains_explicit_and_does_not_spin(self) -> None:
        self.session.prompt("Owned parent.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        path = self.save_outline_child(child)
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        checkpoint = None
        for _ in range(3):
            page, checkpoint = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                after=checkpoint,
                max_bytes=3000,
            )
        assert checkpoint is not None
        self.assertFalse(checkpoint.complete)
        self.assertIn(
            ("agent-ab12", "partial_line"),
            [(gap.stream, gap.reason) for gap in page.coverage.unread],
        )
        self.assertEqual(0, page.bytes_read)

    def test_outline_child_link_swapped_after_admission_is_not_followed(self) -> None:
        self.session.prompt("Owned parent.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        path = self.save_outline_child(child)
        _page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=3000,
        )
        open_binary = self.source.runtime_io._open_binary

        def swapped(candidate: str, **kwargs: Any) -> Any:
            if candidate == str(path):
                saved = path.with_suffix(".saved")
                path.rename(saved)
                path.symlink_to(saved)
            return open_binary(candidate, **kwargs)

        with mock.patch.object(self.source.runtime_io, "_open_binary", side_effect=swapped):
            page, continued = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                after=checkpoint,
                max_bytes=3000,
            )
        self.assertEqual("stale", page.state)
        self.assertEqual(0, page.bytes_read)
        self.assertIsNone(continued)

    def prepare_outline_declarations(self) -> None:
        project_scripts.reset()
        self.addCleanup(project_scripts.reset)
        self.config = dataclasses.replace(self.config, git_probe_enabled=True)
        git(self.root, "init", "-q")
        (self.root / "package.json").write_text(package(typecheck="tsc --noEmit"))
        git(self.root, "add", "package.json")
        git(self.root, "commit", "-q", "-m", "owned base")

    def collect_outline_with_authority(
        self, budget: int = 4000
    ) -> tuple[dict[str, Any], list[Any]]:
        outline = importlib.import_module("compass_runtime.session_outline")
        facts: dict[str, Any] = {}
        authorities: dict[str, tuple[int, int]] = {}
        checkpoint = None
        pages = []
        with self._meter_source_reads() as reads:
            for _ in range(100):
                before = reads[0]
                page, checkpoint = self.source._read_outline(
                    self.config,
                    str(self.path),
                    "claude",
                    "root",
                    after=checkpoint,
                    max_bytes=budget,
                    opening_bytes=1400,
                    deadline=time.monotonic() + 30,
                )
                self.assertIsNotNone(checkpoint)
                self.assertEqual(reads[0] - before, page.bytes_read)
                self.assertLessEqual(page.bytes_read, budget)
                self.assert_outline_checkpoint_private(checkpoint)
                revision = getattr(page, "classification_revision", 0)
                self.assertIsNotNone(outline._measure_facts(checkpoint, outline._FactLimits()))
                if checkpoint.replay:
                    self.assertFalse(checkpoint.complete)
                    self.assertFalse(checkpoint.done)
                    self.assertIn(
                        "classification_pending", [gap.reason for gap in page.coverage.unread]
                    )
                for (old, new), offset in zip(
                    page.replacements, page.replacement_observations, strict=True
                ):
                    for fact_id in set(old) - set(new):
                        authority = (revision, offset)
                        if authority >= authorities.get(fact_id, (-1, -1)):
                            facts.pop(fact_id, None)
                            authorities[fact_id] = authority
                observed = dict(page.observations)
                for entry in page.entries:
                    authority = (revision, observed[entry.fact_id])
                    if authority >= authorities.get(entry.fact_id, (-1, -1)):
                        facts[entry.fact_id] = entry
                        authorities[entry.fact_id] = authority
                pages.append(page)
                if checkpoint.complete:
                    break
        assert checkpoint is not None
        self.assertTrue(
            checkpoint.complete, "classification replay must settle under bounded polls"
        )
        return facts, pages

    def test_outline_late_parent_cwd_replays_zero_fact_calls_and_file_identity(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned late cwd.")
        self.session.bash(f"cd {self.root} && pnpm typecheck", "1 passed")
        self.session.write(str(self.root / "src/early.py"))
        self.session.bash("pytest tests/direct.py", "1 passed")
        for number in range(55):
            self.session.prompt(f"Before cwd {number}. " + "padding " * 20)
        for row in self.session.rows:
            row.pop("cwd", None)
        self.session.prompt("First canonical cwd.")
        for number in range(8):
            self.session.prompt(f"After cwd {number}. " + "padding " * 20)
        self.save()
        whole = self.read()
        self.assertTrue(whole.coverage.complete)
        facts, pages = self.collect_outline_with_authority()
        self.assertFalse(any(entry.title == "pnpm typecheck" for entry in pages[0].entries))
        self.assertEqual({entry.fact_id: entry for entry in whole.entries}, facts)
        self.assertEqual(
            ["src/early.py"], [entry.path for entry in facts.values() if entry.kind == "file"]
        )
        self.assertTrue(any(page.classification_revision > 0 for page in pages))

    def test_outline_late_parent_first_timestamp_replays_earlier_child_calls(self) -> None:
        self.prepare_outline_declarations()
        for number in range(55):
            self.session.prompt(f"Before first stamp {number}. " + "padding " * 20)
        for row in self.session.rows:
            row.pop("timestamp", None)
        self.session.prompt("First canonical parent timestamp.")
        for number in range(8):
            self.session.prompt(f"After timestamp {number}. " + "padding " * 20)
        self.save()
        child = Transcript(self.root)
        child.bash("pnpm typecheck", "1 passed")
        child.write(str(self.root / "src/child.py"))
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        whole = self.read()
        self.assertTrue(whole.coverage.complete)
        self.assertEqual(
            ["pnpm typecheck"], [entry.title for entry in whole.entries if entry.kind == "check"]
        )
        facts, pages = self.collect_outline_with_authority()
        self.assertEqual({entry.fact_id: entry for entry in whole.entries}, facts)
        self.assertTrue(any(page.classification_revision > 0 for page in pages))

    def test_outline_permanently_unknown_head_keeps_canonical_result_without_replay(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned absent cwd.")
        self.session.bash(f"cd {self.root} && pnpm typecheck", "1 passed")
        self.session.bash("pytest tests/direct.py", "1 passed")
        for number in range(20):
            self.session.prompt(f"No metadata {number}. " + "padding " * 20)
        for row in self.session.rows:
            row.pop("cwd", None)
        self.save()
        facts, pages = self.collect_outline_with_authority()
        self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)
        self.assertTrue(all(page.classification_revision == 0 for page in pages))

    def test_outline_unknown_head_zero_fact_calls_obey_dependency_limit(self) -> None:
        self.prepare_outline_declarations()
        self.session.bash(f"cd {self.root} && pnpm typecheck", "1 passed")
        for row in self.session.rows:
            row.pop("cwd", None)
        self.save()
        with mock.patch.object(self.source, "_OUTLINE_DEPENDENCY_LIMIT", 0):
            page, checkpoint = self.source._read_outline(
                self.config, str(self.path), "claude", "root"
            )
        self.assertEqual("limited", page.state)
        self.assertTrue(checkpoint.dependency_limited)
        self.assertFalse(checkpoint.complete)
        self.assertTrue(checkpoint.done)
        self.assertIn("outline_dependency_limit", [gap.reason for gap in page.coverage.unread])

    def test_outline_known_head_direct_calls_need_no_context_dependency(self) -> None:
        self.session.prompt("Owned known metadata.")
        self.session.bash("pytest tests/direct.py", "1 passed")
        self.save()
        with mock.patch.object(self.source, "_OUTLINE_DEPENDENCY_LIMIT", 0):
            page, checkpoint = self.source._read_outline(
                self.config, str(self.path), "claude", "root"
            )
        self.assertEqual("ok", page.state)
        self.assertTrue(checkpoint.complete)
        self.assertEqual((), checkpoint.dependencies)
        self.assertEqual(self.read().entries, page.entries)

    def test_outline_declaring_file_write_reconciles_earlier_and_later_checks(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned declaration reconciliation.")
        self.session.bash("pnpm typecheck; pytest tests/direct.py", "1 passed")
        self.session.write(str(self.root / "src/keep.py"))
        for number in range(6):
            self.session.prompt(f"Before declaring write {number}. " + "padding " * 80)
        self.session.write(str(self.root / "package.json"))
        for number in range(6):
            self.session.prompt(f"After declaring write {number}. " + "padding " * 80)
        self.session.bash("pnpm typecheck", "1 passed")
        self.save()
        whole = self.read()
        facts, pages = self.collect_outline_with_authority()
        self.assertTrue(any(entry.title == "pnpm typecheck" for entry in pages[0].entries))
        self.assertEqual({entry.fact_id: entry for entry in whole.entries}, facts)
        self.assertEqual(
            ["pytest tests/direct.py"],
            [entry.title for entry in facts.values() if entry.kind == "check"],
        )
        self.assertTrue(any(entry.path == "src/keep.py" for entry in facts.values()))
        self.assertTrue(any(getattr(page, "classification_revision", 0) > 0 for page in pages))

    def test_outline_declared_check_without_write_matches_whole_source(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned unchanged declaration.")
        self.session.bash("pnpm typecheck", "1 passed")
        for number in range(12):
            self.session.prompt(f"Unchanged phase {number}. " + "padding " * 80)
        self.save()
        facts, _pages = self.collect_outline_with_authority()
        self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)
        self.assertEqual(
            ["pnpm typecheck"], [entry.title for entry in facts.values() if entry.kind == "check"]
        )

    def test_outline_child_write_withdraws_parent_and_sibling_declarations(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned parent check.")
        self.session.bash("pnpm typecheck; pytest tests/direct.py", "1 passed")
        self.save()
        sibling = Transcript(self.root)
        sibling.bash("pnpm typecheck", "1 passed")
        self.save_outline_child(sibling, "agent-ab12.jsonl")
        writer = Transcript(self.root)
        writer.write(str(self.root / "package.json"))
        self.save_outline_child(writer, "agent-cd34.jsonl")
        facts, pages = self.collect_outline_with_authority()
        self.assertTrue(any(entry.title == "pnpm typecheck" for entry in pages[0].entries))
        self.assertTrue(any(entry.title == "pnpm typecheck" for entry in pages[1].entries))
        self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)
        self.assertEqual(
            ["pytest tests/direct.py"],
            [entry.title for entry in facts.values() if entry.kind == "check"],
        )

    def test_outline_listed_script_and_listing_writes_reconcile_prior_checks(self) -> None:
        self.prepare_outline_declarations()
        store = Path(reader_checks.store_path(self.config))
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps({"projects": {str(self.root): ["./check.sh"]}}))
        for written in ("check.sh", reader_checks.FILENAME):
            with self.subTest(written=written):
                self.session = Transcript(self.root)
                self.session.prompt("Owned listed check.")
                self.session.bash("./check.sh; pytest tests/direct.py", "1 passed")
                for number in range(6):
                    self.session.prompt(f"Before listed write {number}. " + "padding " * 80)
                self.session.write(str(self.root / written))
                for number in range(6):
                    self.session.prompt(f"After listed write {number}. " + "padding " * 80)
                self.session.bash("./check.sh", "ok")
                self.save()
                facts, pages = self.collect_outline_with_authority()
                self.assertTrue(any(entry.title == "./check.sh" for entry in pages[0].entries))
                self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)

    def test_outline_withdrawal_does_not_promote_an_older_unaffected_pass(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned mixed authority.")
        direct = self.session.call("Bash", {"command": "pytest tests/direct.py"})
        self.session.bash("pnpm typecheck", "1 passed")
        for number in range(4):
            self.session.prompt(f"Before earlier result {number}. " + "padding " * 80)
        self.session.result(direct, "1 passed")
        self.session.write(str(self.root / "package.json"))
        for number in range(10):
            self.session.prompt(f"Before tail failure {number}. " + "padding " * 80)
        self.session.result(direct, "Exit code 1\n1 failed", is_error=True)
        self.session.prompt("After the latest direct result. " + "padding " * 130)
        self.save()
        facts, pages = self.collect_outline_with_authority(budget=6000)
        self.assertEqual(
            ["failed"],
            [entry.result for entry in pages[0].entries if entry.title == "pytest tests/direct.py"],
        )
        self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)
        for page in pages:
            if page.classification_revision:
                self.assertTrue(
                    all(entry.title != "pytest tests/direct.py" for entry in page.entries)
                )

    def test_outline_replayed_conditional_call_accepts_a_later_valid_result(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned future result.")
        call = self.session.call("Bash", {"command": "pnpm typecheck"})
        for number in range(6):
            self.session.prompt(f"Before unrelated withdrawal {number}. " + "padding " * 80)
        self.session.write(str(self.root / reader_checks.FILENAME))
        for number in range(10):
            self.session.prompt(f"Before later result {number}. " + "padding " * 80)
        self.session.result(call, "1 passed")
        for number in range(8):
            self.session.prompt(f"After later result {number}. " + "padding " * 80)
        self.save()
        facts, pages = self.collect_outline_with_authority()
        replayed = [
            (page.classification_revision, entry.result)
            for page in pages
            if page.classification_revision
            for entry in page.entries
            if entry.title == "pnpm typecheck"
        ]
        self.assertEqual(["not-recorded", "passed"], [result for _, result in replayed])
        self.assertLess(replayed[0][0], replayed[1][0])
        self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)

    def test_dependency_recovery_after_work_deadline_is_typed_and_validated(self) -> None:
        self.prepare_outline_declarations()
        self.session.bash("pnpm typecheck", "1 passed")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        directory = self.path.with_suffix("") / "subagents"
        child.save(directory / "agent-ab12.jsonl")
        added = directory / "agent-added.jsonl"
        for failure in ("none", "time", "outline_stream_limit", "os", "parent", "child"):
            now = [100.0]
            rejected = [False]
            streams, stamps = self.source._outline_streams, self.source._outline_stamps

            def reject(
                *args: Any,
                streams: Any = streams,
                rejected: list[bool] = rejected,
                now: list[float] = now,
                failure: str = failure,
                **kwargs: Any,
            ) -> Any:
                try:
                    return streams(*args, **kwargs)
                except ValueError as error:
                    self.assertEqual("outline_dependency_limit", str(error))
                    rejected[0] = True
                    now[0] = 101.0
                    if failure == "parent":
                        with self.path.open("a") as handle:
                            handle.write("\n")
                    elif failure == "child":
                        child.save(added)
                    raise

            def inventory(
                *args: Any,
                stamps: Any = stamps,
                rejected: list[bool] = rejected,
                failure: str = failure,
                **kwargs: Any,
            ) -> Any:
                errors = {
                    "time": ValueError("time"),
                    "outline_stream_limit": ValueError("outline_stream_limit"),
                    "os": OSError("owned recovery metadata unavailable"),
                }
                if rejected[0] and failure in errors:
                    raise errors[failure]
                return stamps(*args, **kwargs)

            with (
                self.subTest(failure=failure),
                mock.patch.object(self.source, "_OUTLINE_DEPENDENCY_LIMIT", 0),
                mock.patch.object(self.source, "_outline_streams", side_effect=reject),
                mock.patch.object(self.source, "_outline_stamps", side_effect=inventory),
                mock.patch.object(
                    self.source.time, "monotonic", side_effect=lambda now=now: now[0]
                ),
            ):
                page, checkpoint = self.source._read_outline(
                    self.config, str(self.path), "claude", "root", max_bytes=4000, deadline=100.25
                )
                self.assertTrue(rejected[0])
                self.assertLessEqual(page.bytes_read, 4000)
                self._assert_dependency_recovery(page, checkpoint, failure)
            if added.exists():
                added.unlink()

    def _assert_dependency_recovery(self, page: Any, checkpoint: Any, failure: str) -> None:
        if failure == "none":
            self.assertEqual("limited", page.state)
            self.assertTrue(checkpoint.dependency_limited)
            self.assertTrue(checkpoint.done)
            self.assertFalse(checkpoint.complete)
        else:
            self.assertIsNone(checkpoint)
            self.assertEqual(
                {
                    "time": "limited",
                    "outline_stream_limit": "limited",
                    "os": "unavailable",
                    "parent": "stale",
                    "child": "stale",
                }[failure],
                page.state,
            )
            if failure in {"time", "outline_stream_limit"}:
                self.assertEqual([failure], [gap.reason for gap in page.coverage.unread])

    def test_dependency_recovery_keeps_only_same_version_accepted_checkpoint(self) -> None:
        self.prepare_outline_declarations()
        self.session.bash("pnpm typecheck", "1 passed")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        _page, accepted = self.source._read_outline(self.config, str(self.path), "claude", "root")
        self.assertIsNotNone(accepted)
        for mutate in (False, True):
            now = [100.0]
            streams = self.source._outline_streams

            def reject(
                *args: Any,
                streams: Any = streams,
                now: list[float] = now,
                mutate: bool = mutate,
                **kwargs: Any,
            ) -> Any:
                try:
                    return streams(*args, **kwargs)
                except ValueError as error:
                    self.assertEqual("outline_dependency_limit", str(error))
                    now[0] = 101.0
                    if mutate:
                        with self.path.open("a") as handle:
                            handle.write("\n")
                    raise

            with (
                self.subTest(mutate=mutate),
                mock.patch.object(self.source, "_OUTLINE_DEPENDENCY_LIMIT", 0),
                mock.patch.object(self.source, "_outline_streams", side_effect=reject),
                mock.patch.object(
                    self.source.time, "monotonic", side_effect=lambda now=now: now[0]
                ),
            ):
                page, checkpoint = self.source._read_outline(
                    self.config,
                    str(self.path),
                    "claude",
                    "root",
                    after=accepted,
                    max_bytes=4000,
                    deadline=100.25,
                )
                if mutate:
                    self.assertEqual("stale", page.state)
                    self.assertIsNone(checkpoint)
                else:
                    self.assertEqual("limited", page.state)
                    self.assertTrue(checkpoint.dependency_limited)
                    self.assertEqual(accepted.inventory, checkpoint.inventory)
                    self.assertIs(accepted.frontier, checkpoint.frontier)
                    self.assertEqual(accepted.accepted, checkpoint.accepted)

    def test_outline_dependency_cap_is_explicit_and_sticky(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned limited declaration.")
        self.session.bash("pnpm typecheck", "1 passed")
        self.save()
        with mock.patch.object(self.source, "_OUTLINE_DEPENDENCY_LIMIT", 0):
            page, checkpoint = self.source._read_outline(
                self.config,
                str(self.path),
                "claude",
                "root",
                max_bytes=4000,
            )
        self.assertEqual("limited", page.state)
        self.assertIsNotNone(checkpoint)
        self.assertTrue(checkpoint.done)
        self.assertFalse(checkpoint.complete)
        self.assertIn("outline_dependency_limit", [gap.reason for gap in page.coverage.unread])
        again, continued = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=checkpoint,
            max_bytes=4000,
        )
        self.assertEqual("limited", again.state)
        self.assertEqual(0, again.bytes_read)
        self.assertEqual(checkpoint, continued)

    def test_outline_script_shell_withdrawal_is_carried_and_reconciled(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned script-shell withdrawal.")
        self.session.bash("pnpm typecheck; pytest tests/direct.py", "1 passed")
        for number in range(6):
            self.session.prompt(f"Before shell write {number}. " + "padding " * 80)
        self.session.write(str(self.root / "pnpm-workspace.yaml"), "scriptShell: /bin/sh")
        for number in range(6):
            self.session.prompt(f"After shell write {number}. " + "padding " * 80)
        self.session.bash("pnpm typecheck", "1 passed")
        self.save()
        facts, pages = self.collect_outline_with_authority()
        self.assertTrue(any(entry.title == "pnpm typecheck" for entry in pages[0].entries))
        self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)
        self.assertEqual(
            ["pytest tests/direct.py"],
            [entry.title for entry in facts.values() if entry.kind == "check"],
        )

    def test_outline_replay_rejects_another_harness_or_session_identity(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned replay identity.")
        self.session.bash("pnpm typecheck", "1 passed")
        self.save()
        _page, checkpoint = self.source._read_outline(
            self.config, str(self.path), "claude", "root", max_bytes=4000
        )
        checkpoint = dataclasses.replace(
            checkpoint,
            replay=(("parent", checkpoint.dependencies[0].call_id),),
            classification_revision=1,
        )
        for harness, sid in (("codex", "root"), ("claude", "other")):
            with self.subTest(harness=harness, sid=sid):
                page, refused = self.source._read_outline(
                    self.config, str(self.path), harness, sid, after=checkpoint, max_bytes=4000
                )
                self.assertEqual("stale", page.state)
                self.assertEqual((), page.entries)
                self.assertIsNone(refused)

    def test_outline_complete_cold_page_keeps_exact_plan_without_redundant_replay(self) -> None:
        self.prepare_outline_declarations()
        self.session.prompt("Owned complete classification.")
        self.session.bash("pnpm typecheck", "1 passed")
        self.session.write(str(self.root / reader_checks.FILENAME))
        self.save()
        page, checkpoint = self.source._read_outline(
            self.config, str(self.path), "claude", "root", max_bytes=4000
        )
        self.assertTrue(page.coverage.complete)
        self.assertTrue(checkpoint.complete)
        self.assertEqual((), checkpoint.replay)
        self.assertEqual(self.read().entries, page.entries)

    def test_outline_withdrawal_reconciles_a_previously_unemitted_closed_list_fallback(
        self,
    ) -> None:
        self.prepare_outline_declarations()
        (self.root / "package.json").write_text(package(test="echo skipped"))
        git(self.root, "add", "package.json")
        git(self.root, "commit", "-q", "-m", "owned ordinary script")
        project_scripts.reset()
        self.session.prompt("Owned closed-list fallback.")
        self.session.bash("pnpm test", "1 passed")
        for number in range(6):
            self.session.prompt(f"Before declaration removal {number}. " + "padding " * 80)
        self.session.write(str(self.root / "package.json"))
        for number in range(6):
            self.session.prompt(f"After declaration removal {number}. " + "padding " * 80)
        self.save()
        facts, pages = self.collect_outline_with_authority()
        self.assertFalse(any(entry.kind == "check" for entry in pages[0].entries))
        self.assertEqual({entry.fact_id: entry for entry in self.read().entries}, facts)
        self.assertEqual(
            ["pnpm test"], [entry.title for entry in facts.values() if entry.kind == "check"]
        )

    def test_outline_unreadable_child_keeps_an_explicit_terminal_gap(self) -> None:
        self.session.prompt("Owned parent.")
        self.save()
        directory = self.path.with_suffix("") / "subagents" / "agent-dead.jsonl"
        directory.mkdir(parents=True)
        _page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=3000,
        )
        page, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=checkpoint,
            max_bytes=3000,
        )
        self.assertIsNotNone(checkpoint, "unchanged unreadable child needs a retained gap")
        self.assertFalse(checkpoint.complete)
        self.assertTrue(checkpoint.children[0][1].stopped)
        self.assertIn(
            ("agent-dead", "unreadable_subagent"),
            [(gap.stream, gap.reason) for gap in page.coverage.unread],
        )

    def test_outline_parent_exact_boundary_allowance_refuses_instead_of_stalling(self) -> None:
        self.session.prompt("First owned prompt.")
        self.session.prompt("Second owned prompt.")
        self.save()
        lines = self.path.read_bytes().splitlines(keepends=True)
        boundary = len(lines[0])
        _page, checkpoint = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=boundary,
            deadline=time.monotonic() + 30,
        )
        self.assertEqual(boundary, checkpoint.frontier.end_offset)
        limited, stopped = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=checkpoint,
            max_bytes=boundary,
            deadline=time.monotonic() + 30,
        )
        self.assertEqual("limited", limited.state)
        self.assertTrue(stopped.stopped)
        self.assertFalse(stopped.parent_complete)
        self.assertEqual((), limited.entries)
        self.assertIn(
            "outline_boundary_limit", [region.reason for region in limited.coverage.unread]
        )

        # One additional byte permits bounded discard progress; a fitting next line is admitted.
        _page, advancing = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=checkpoint,
            max_bytes=boundary + 1,
            deadline=time.monotonic() + 30,
        )
        self.assertFalse(advancing.stopped)
        self.assertGreater(advancing.frontier.offset, boundary)
        complete, finished = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=checkpoint,
            max_bytes=boundary + len(lines[1]),
            deadline=time.monotonic() + 30,
        )
        self.assertTrue(finished.parent_complete)
        self.assertEqual(["Second owned prompt."], [entry.title for entry in complete.entries])

    def test_outline_parent_short_remainder_does_not_permanently_refuse_a_fitting_boundary(
        self,
    ) -> None:
        self.session.prompt("First owned prompt.")
        self.session.prompt("Second owned prompt.")
        self.save()
        boundary = len(self.path.read_bytes().splitlines(keepends=True)[0])
        _page, checkpoint = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=boundary,
            deadline=time.monotonic() + 30,
        )
        allowance = self.path.stat().st_size
        deadline = time.monotonic() + 30
        budget = self.source._Budget(allowance, deadline, deadline)
        # Another phase really spends bytes from the shared poll allowance first.
        with self.path.open("rb") as source:
            while budget.remaining > boundary - 1:
                budget.line(source, budget.remaining - (boundary - 1))
        deferred, continued = self.source._outline_parent_page(
            self.config, str(self.path), "root", checkpoint, budget
        )
        self.assertEqual("ok", deferred.state)
        self.assertFalse(continued.stopped)
        self.assertEqual(boundary, continued.frontier.offset)
        self.assertNotIn(
            "outline_boundary_limit", [region.reason for region in deferred.coverage.unread]
        )
        self.assertLessEqual(budget.used, allowance)
        _page, finished = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "claude",
            "root",
            after=continued,
            max_bytes=allowance,
            deadline=time.monotonic() + 30,
        )
        self.assertTrue(finished.parent_complete)

    def test_outline_parent_unfit_line_advances_without_retaining_its_fragment(self) -> None:
        self.session.prompt("PRIVATE_OVERSIZED_WORDS " * 400)
        self.session.prompt("A later small record.")
        self.save()
        checkpoint = None
        offsets = []
        for _poll in range(40):
            page, checkpoint = self.source._read_outline_parent(
                self.config,
                str(self.path),
                "claude",
                "root",
                after=checkpoint,
                max_bytes=1000,
                deadline=time.monotonic() + 30,
            )
            self.assertLessEqual(page.bytes_read, 1000)
            self.assertNotIn("PRIVATE_OVERSIZED_WORDS", repr(checkpoint))
            self.assertNotIn("fragment=", repr(checkpoint))
            offsets.append(checkpoint.frontier.offset)
            if page.state == "limited":
                break
        self.assertGreater(offsets[-1], 1000)
        self.assertEqual(sorted(offsets), offsets)
        self.assertEqual(sorted(set(offsets[:-1])), offsets[:-1])
        self.assertEqual("limited", page.state)
        assert checkpoint is not None
        self.assertFalse(checkpoint.parent_complete)
        self.assertIn("outline_line_limit", [region.reason for region in page.coverage.unread])
        self.assertIn("outline_boundary_limit", [region.reason for region in page.coverage.unread])

    def test_a_hook_rewrite_on_a_later_page_reads_as_the_whole_file_does(self) -> None:
        for split_result in (False, True):
            with self.subTest(split_result=split_result):
                self.setUp()
                call = self.session.call("Bash", {"command": "pytest"})
                self.save()
                previous = self.read()
                self.session.hook_rewrite(call, hook_stdout("rtk pytest"))
                if split_result:
                    self.save()
                    previous = self.read(after=previous.snapshot.cursor)
                self.session.result(call, "1 failed", is_error=False)
                self.save()
                incremental = self.read(after=previous.snapshot.cursor)
                whole = self.read()
                self.assertEqual(
                    [e.result for e in whole.entries if e.kind == "check"],
                    [e.result for e in incremental.entries if e.kind == "check"],
                )
                self.assertEqual(["not-recorded"], [e.result for e in whole.entries])

    def test_a_rewrite_that_renames_the_check_retires_the_typed_fact(self) -> None:
        # `python3 -m pytest tests` ran as `rtk pytest tests`, which titles the check `pytest tests`,
        # so the fact read from the typed command has an id the whole-file read never produces.
        call = self.session.call("Bash", {"command": "python3 -m pytest tests"})
        self.save()
        previous = self.read()
        self.assertEqual(["python3 -m pytest tests"], [e.title for e in previous.entries])
        self.session.hook_rewrite(call, hook_stdout("rtk pytest tests"))
        self.save()
        for page in (self.read(), self.read(after=previous.snapshot.cursor)):
            change = self.source.compare(previous.snapshot, page)
            self.assertEqual("changed_earlier", change.kind)
            self.assertIn((previous.entries[0].fact_id, "check_result"), change.changed)
        self.assertEqual(["pytest tests"], [e.title for e in self.read().entries])

    def test_late_message_keeps_file_order_and_reports_reordering(self) -> None:
        self.path.write_text(json.dumps(test_record_pages.RecordPagesTest.record(5)) + "\n")
        previous = self.read()
        with self.path.open("a") as output:
            output.write(json.dumps(test_record_pages.RecordPagesTest.record(2)) + "\n")
        for page in (self.read(), self.read(after=previous.snapshot.cursor)):
            change = self.source.compare(previous.snapshot, page)
            self.assertEqual("changed_earlier", change.kind)
            self.assertIn((page.entries[-1].fact_id, "reordered"), change.changed)
        self.assertGreater(self.read().entries[0].at, self.read().entries[1].at)

    def test_truncation(self) -> None:
        self.session.prompt("Read the synthetic record.")
        self.save()
        previous = self.read()
        self.path.write_bytes(b"")
        self.changes(previous, "truncated")

    def test_replacement_inode(self) -> None:
        self.session.prompt("Read the synthetic record.")
        self.save()
        previous = self.read()
        replacement = self.root / "replacement"
        replacement.write_bytes(self.path.read_bytes())
        replacement.replace(self.path)
        self.changes(previous, "replaced")

    def test_replacement_same_size_boundary(self) -> None:
        self.session.prompt("Read the synthetic record.")
        self.save()
        previous = self.read()
        self.path.write_bytes(self.path.read_bytes().replace(b"synthetic", b"different"))
        self.changes(previous, "replaced")

    def test_unchanged(self) -> None:
        self.session.prompt("Read the synthetic record.")
        self.save()
        self.changes(self.read(), "unchanged")

    def test_codex_admits_only_person_words(self) -> None:
        rows = [
            test_record_pages.RecordPagesTest.record(
                i, harness="codex", role="user" if i % 2 == 0 else "assistant"
            )
            for i in range(6)
        ]
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        page = self.source.read(self.config, str(self.path), "codex", "root")
        self.assertEqual(["person"] * 3, [e.kind for e in page.entries])
        self.assertEqual("not_read", page.coverage.agent_replies)
        self.assertEqual("not_admitted", page.coverage.checks_and_files)
        wrapped, checkpoint = self.source._read_outline(
            self.config,
            str(self.path),
            "codex",
            "root",
            max_bytes=10000,
            opening_bytes=1,
            deadline=time.monotonic() + 30,
        )
        self.assertIsNotNone(checkpoint)
        self.assertTrue(checkpoint.parent_complete)
        self.assertEqual(page.entries, wrapped.entries)
        self.assertTrue(wrapped.coverage.complete)
        self.assertEqual("not_read", wrapped.coverage.agent_replies)
        self.assertEqual("not_admitted", wrapped.coverage.checks_and_files)

    def assert_outline_checkpoint_private(self, checkpoint: Any) -> None:
        retained = [checkpoint]
        while retained:
            value = retained.pop()
            self.assertNotIsInstance(
                value,
                (
                    bytes,
                    self.source.SourcePage,
                    self.source.SourceCursor,
                    self.source.SourceSnapshot,
                    self.source.PendingCall,
                ),
            )
            if dataclasses.is_dataclass(value):
                for field in dataclasses.fields(value):
                    self.assertNotIn(field.name, {"words", "fragment", "input_json"})
                    retained.append(getattr(value, field.name))
            elif isinstance(value, tuple):
                retained.extend(value)

    def test_codex_outline_continues_person_only_with_first_latest_and_metered_bytes(self) -> None:
        outline = importlib.import_module("compass_runtime.session_outline")
        rows = []
        for number in range(12):
            rows.extend(
                [
                    test_record_pages.RecordPagesTest.record(
                        number * 3,
                        harness="codex",
                        text=f"Owned person phase {number}. PERSON_PRIVATE_SENTINEL "
                        + "padding " * 25,
                    ),
                    test_record_pages.RecordPagesTest.record(
                        number * 3 + 1,
                        harness="codex",
                        role="assistant",
                        text="ASSISTANT_PRIVATE_SENTINEL " * 8,
                    ),
                    {
                        "type": "response_item",
                        "timestamp": "2026-10-01T00:00:00Z",
                        "payload": {
                            "type": "function_call",
                            "name": "shell_command",
                            "call_id": f"call-{number}",
                            "arguments": '{"command":"TOOL_PRIVATE_SENTINEL pytest tests"}',
                        },
                    },
                ]
            )
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        size = self.path.stat().st_size
        self.assertGreater(size, 3 * 2400)
        whole = self.source.read(self.config, str(self.path), "codex", "root", max_bytes=size + 1)
        self.assertEqual(12, len(whole.entries))
        expected = [entry.fact_id for entry in whole.entries]
        facts: dict[str, Any] = {}
        positions: dict[str, tuple[int, int, int]] = {}
        checkpoint = None
        remaining = size
        frontier_offset = -1
        with (
            self._meter_source_reads() as reads,
            mock.patch.object(self.source, "_tools", side_effect=AssertionError("no Codex tools")),
            mock.patch.object(
                self.source, "_outline_pending", side_effect=AssertionError("no Codex inputs")
            ),
            mock.patch.object(
                self.source, "_rows_of", side_effect=AssertionError("no Codex classifier")
            ),
        ):
            for poll in range(50):
                before = reads[0]
                page, checkpoint = self.source._read_outline(
                    self.config,
                    str(self.path),
                    "codex",
                    "root",
                    after=checkpoint,
                    max_bytes=2400,
                    opening_bytes=700,
                    deadline=time.monotonic() + 30,
                )
                self.assertIsNotNone(checkpoint, "Codex must return a sanitized continuation")
                self.assertEqual("ok", page.state)
                self.assertEqual(reads[0] - before, page.bytes_read)
                self.assertLessEqual(page.bytes_read, 2400)
                self.assertEqual("not_read", page.coverage.agent_replies)
                self.assertEqual("not_admitted", page.coverage.checks_and_files)
                self.assertEqual(whole.coverage.notes, page.coverage.notes)
                self.assertTrue(all(entry.kind == "person" for entry in page.entries))
                self.assertIsNone(outline._plan(page, self.config))
                self.assertNotIn("ASSISTANT_PRIVATE_SENTINEL", repr(page.entries))
                self.assertNotIn("TOOL_PRIVATE_SENTINEL", repr(page.entries))
                self.assertIsNone(page.next)
                self.assertIsNone(page.snapshot)
                self.assertEqual(
                    ((), ("", None), ()),
                    (
                        checkpoint.calls,
                        checkpoint.head,
                        checkpoint.listing_writes,
                    ),
                )
                for sentinel in (
                    "PERSON_PRIVATE_SENTINEL",
                    "ASSISTANT_PRIVATE_SENTINEL",
                    "TOOL_PRIVATE_SENTINEL",
                ):
                    self.assertNotIn(sentinel, repr(checkpoint))
                self.assert_outline_checkpoint_private(checkpoint)
                facts.update((entry.fact_id, entry) for entry in page.entries)
                positions.update(page.positions)
                missing = size - sum(end - start for start, end in checkpoint.accepted)
                self.assertLessEqual(missing, remaining)
                self.assertGreater(checkpoint.frontier.offset, frontier_offset)
                frontier_offset = checkpoint.frontier.offset
                remaining = missing
                if poll == 0:
                    self.assertTrue({expected[0], expected[-1]} <= facts.keys())
                    self.assertGreater(missing, 0)
                if checkpoint.parent_complete:
                    break
        assert checkpoint is not None
        self.assertTrue(checkpoint.parent_complete)
        self.assertEqual(((0, size),), checkpoint.accepted)
        self.assertEqual(
            whole.entries, tuple(facts[key] for key in sorted(facts, key=positions.__getitem__))
        )

    def test_codex_outline_unfinished_line_retains_no_raw_fragment(self) -> None:
        record = test_record_pages.RecordPagesTest.record(
            1, harness="codex", text="UNFINISHED_PRIVATE_SENTINEL " * 8
        )
        self.path.write_text(json.dumps(record))
        page, checkpoint = self.source._read_outline_parent(
            self.config,
            str(self.path),
            "codex",
            "root",
            max_bytes=2000,
            deadline=time.monotonic() + 30,
        )
        self.assertIsNotNone(checkpoint)
        self.assertFalse(checkpoint.parent_complete)
        self.assertEqual((), page.entries)
        self.assertIn("partial_line", [gap.reason for gap in page.coverage.unread])
        self.assertNotIn("UNFINISHED_PRIVATE_SENTINEL", repr(checkpoint))

    def test_subagent_streams_keep_call_results_and_writes(self) -> None:
        self.session.bash("pytest tests", "1 passed")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests", "1 failed", is_error=True)
        child.write(str(self.root / "src/child.py"))
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        page = self.read()
        self.assertEqual(["parent", "subagent", "subagent"], [e.actor for e in page.entries])
        self.assertEqual(
            ["passed", "failed"], [e.result for e in page.entries if e.kind == "check"]
        )
        self.assertEqual("agent-ab12", page.entries[-1].stream)
        self.assertEqual("src/child.py", page.entries[-1].path)

    def test_partial_last_line_remains_for_a_later_read(self) -> None:
        first = json.dumps(test_record_pages.RecordPagesTest.record(1)).encode() + b"\n"
        second = json.dumps(test_record_pages.RecordPagesTest.record(2)).encode()
        self.path.write_bytes(first + second)
        previous = self.read()
        self.assertEqual(len(first), previous.coverage.end_offset)
        self.assertEqual(1, len(previous.entries))
        with self.path.open("ab") as output:
            output.write(b"\n")
        self.assertEqual(1, len(self.read(after=previous.snapshot.cursor).entries))

    def test_full_words_survive_the_reading_words_cap(self) -> None:
        text = "Synthetic words " * 1500 + "finaltoken"
        self.path.write_text(
            json.dumps(test_record_pages.RecordPagesTest.record(1, text=text)) + "\n"
        )
        self.assertTrue(self.read().entries[0].words.endswith("finaltoken"))

    def test_oversized_message_is_a_gap_before_masking(self) -> None:
        self.path.write_text(
            json.dumps(
                test_record_pages.RecordPagesTest.record(
                    1, text="x" * (project_context.PRESS_TEXT_MAX_CHARS + 1)
                )
            )
            + "\n"
        )
        with mock.patch.object(
            record_pages, "_fact", side_effect=AssertionError("must skip before masking")
        ):
            page = self.read()
        self.assertFalse(page.coverage.complete)
        self.assertEqual("oversized_line", page.coverage.unread[0].reason)

    def test_expired_deadline_reports_time(self) -> None:
        self.session.prompt("Read the synthetic record.")
        self.save()
        page = self.read(deadline=0)
        self.assertEqual((), page.entries)
        self.assertEqual("time", page.coverage.unread[-1].reason)

    def test_source_changed_during_read_is_stale(self) -> None:
        self.session.prompt("Read the synthetic record.")
        self.save()
        original = record_pages._fact

        def mutate(*args: Any, **kwargs: Any) -> Any:
            with self.path.open("ab") as output:
                output.write(b"{}\n")
            return original(*args, **kwargs)

        with mock.patch.object(record_pages, "_fact", side_effect=mutate):
            self.assertEqual("stale", self.read().state)

    def test_unsupported_and_missing_sources(self) -> None:
        self.assertEqual("unavailable", self.read().state)
        page = self.source.read(self.config, str(self.path), "pi", "root")
        self.assertEqual("unsupported", page.state)
        self.assertIn("no paged record for this harness", page.notes)

    def test_successive_snapshots_keep_earlier_subjects(self) -> None:
        self.session.bash("pytest tests", "1 passed")
        self.save()
        initial = self.read()
        self.session.prompt("Continue with synthetic work.")
        self.save()
        middle = self.read(after=initial.snapshot.cursor)
        self.session.bash("pytest tests", "1 failed", is_error=True)
        self.save()
        change = self.source.compare(middle.snapshot, self.read(after=middle.snapshot.cursor))
        self.assertIn((initial.entries[0].fact_id, "check_result"), change.changed)

    def test_oversized_line_is_skipped_and_hashed_across_pages(self) -> None:
        self.config = dataclasses.replace(self.config, session_source_line_max_bytes=512)
        raw = b'{"image":"' + b"x" * 3000 + b'"}\n'
        self.path.write_bytes(raw)
        cursor = None
        pages = []
        for _ in range(20):
            page = self.read(after=cursor, max_bytes=1000)
            pages.append(page)
            self.assertEqual("ok", page.state)
            cursor = page.next
            if cursor is None:
                break
        self.assertIsNone(cursor)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), pages[-1].snapshot.boundary_digest)
        self.assertEqual("oversized_line", pages[-1].coverage.unread[0].reason)
        self.assertEqual(
            "unchanged",
            self.source.compare(
                pages[-1].snapshot, self.read(after=pages[-1].snapshot.cursor)
            ).kind,
        )

    def test_unread_child_is_explicit_when_parent_uses_allowance(self) -> None:
        self.session.prompt("Read a synthetic parent.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        page = self.read(max_bytes=self.path.stat().st_size)
        self.assertTrue(
            any(
                r.stream == "agent-ab12" and r.reason == "unreadable_subagent"
                for r in page.coverage.unread
            )
        )

    def test_equal_timestamps_do_not_move_messages_ahead_of_calls(self) -> None:
        self.session.bash("pytest tests", "1 passed")
        self.session.prompt("Read the synthetic result.")
        for row in self.session.rows:
            row["timestamp"] = self.session.rows[0]["timestamp"]
        self.save()
        self.assertEqual(["check", "person"], [entry.kind for entry in self.read().entries])

    def test_changed_earlier_words_keep_identity_and_change_fingerprint(self) -> None:
        self.session.prompt("Read this synthetic title. Earlier private sentence.")
        self.session.prompt("Leave the boundary intact.")
        self.save()
        previous = self.read()
        self.session.rows[0]["message"]["content"][0]["text"] = (
            "Read this synthetic title. Changed private sentence."
        )
        self.save()
        change = self.source.compare(previous.snapshot, self.read())
        self.assertEqual("changed_earlier", change.kind)
        self.assertIn((previous.entries[0].fact_id, "content"), change.changed)

    def test_pending_result_with_unknown_outcome_still_changes_evidence(self) -> None:
        call = self.session.call("Bash", {"command": "pytest tests"})
        self.save()
        previous = self.read()
        self.session.result(call, "Output without a result flag or summary.")
        self.save()
        self.changes(previous, "changed_earlier", "check_result")

    def test_pending_call_refusal_retracts_the_earlier_unknown_run(self) -> None:
        call = self.session.call("Bash", {"command": "pytest tests"})
        self.save()
        previous = self.read()
        self.session.result(call, "Permission denied by reader.", is_error=True)
        self.save()
        self.changes(previous, "changed_earlier", "check_result")

    def test_newest_window_reaches_the_last_complete_message(self) -> None:
        self.path.write_text(
            "".join(
                json.dumps(test_record_pages.RecordPagesTest.record(i)) + "\n" for i in range(140)
            )
        )
        page = self.read(newest=True, max_bytes=2500)
        self.assertEqual(self.read().entries[-1].fact_id, page.entries[-1].fact_id)
        self.assertIsNone(page.next)

    def test_tool_classification_checks_the_same_deadline(self) -> None:
        self.session.bash("pytest tests/a.py", "1 passed")
        self.session.bash("pytest tests/b.py", "1 passed")
        self.save()
        now = [0.0]
        original = project_context._ToolReportTally.add

        def slow(tally: Any, *args: Any, **kwargs: Any) -> None:
            original(tally, *args, **kwargs)
            now[0] = 20.0

        with (
            mock.patch.object(self.source.time, "monotonic", side_effect=lambda: now[0]),
            mock.patch.object(project_context._ToolReportTally, "add", slow),
        ):
            page = self.read(deadline=10.0)
        self.assertFalse(page.coverage.complete)
        self.assertIn("time", [region.reason for region in page.coverage.unread])
        self.assertIsNotNone(page.next)
        # The classified call is kept and the frontier moves to the unclassified one's row.
        rest = self.read(after=page.next)
        self.assertEqual(1, len(page.entries))
        self.assertEqual(1, len(rest.entries))
        self.assertEqual(
            [e.fact_id for e in self.read().entries],
            [e.fact_id for e in (*page.entries, *rest.entries)],
        )

    def test_time_clipped_pages_with_calls_each_make_progress(self) -> None:
        for turn in range(40):
            self.session.prompt(f"Run synthetic check {turn}.")
            self.session.bash(f"pytest tests/test_{turn}.py", "1 passed")
        self.save()
        complete = self.read()
        self.config = dataclasses.replace(self.config, session_source_page_max_seconds=40.0)
        clock = [0.0]

        def tick() -> float:
            clock[0] += 1.0
            return clock[0]

        seen: dict[str, Any] = {}
        order: list[str] = []
        cursor = None
        offset = -1
        with mock.patch.object(self.source.time, "monotonic", side_effect=tick):
            for _ in range(200):
                page = self.read(after=cursor)
                self.assertEqual("ok", page.state)
                self.assertTrue(page.entries, "every page must return an entry")
                frontier = page.snapshot.cursor.streams[0].offset
                self.assertGreater(frontier, offset)
                offset = frontier
                for entry in page.entries:
                    if entry.fact_id in seen:
                        # Only a call read before its result may return, carrying the result.
                        self.assertEqual("not-recorded", seen[entry.fact_id].result)
                    else:
                        order.append(entry.fact_id)
                    seen[entry.fact_id] = entry
                cursor = page.next
                if cursor is None:
                    break
        self.assertIsNone(cursor)
        self.assertGreater(clock[0], 0)
        self.assertEqual([e.fact_id for e in complete.entries], order)
        self.assertEqual(
            [(e.fact_id, e.result) for e in complete.entries],
            [(fact_id, seen[fact_id].result) for fact_id in order],
        )

    def test_partial_last_line_ends_paging(self) -> None:
        whole = json.dumps(test_record_pages.RecordPagesTest.record(1)).encode() + b"\n"
        self.path.write_bytes(whole + b'{"type":"us')
        page = self.read()
        self.assertEqual(1, len(page.entries))
        self.assertIsNone(page.next)
        self.assertEqual(b'{"type":"us', page.snapshot.cursor.streams[0].fragment)

    def test_background_bash_is_not_a_check(self) -> None:
        self.session.bash(
            "pytest tests",
            "Command running in background with ID: abc",
            run_in_background=True,
        )
        self.session.bash("pytest tests/b.py", "1 passed")
        self.save()
        self.assertEqual(
            [("check", "pytest tests/b.py")],
            [(e.kind, e.title) for e in self.read().entries],
        )

    def test_workflow_child_with_a_shared_agent_id_has_its_own_stream(self) -> None:
        self.session.prompt("Delegate synthetic checks.")
        self.save()
        base = self.path.with_suffix("") / "subagents"
        for where, command in (
            (base / "agent-ab12.jsonl", "pytest tests/a.py"),
            (base / "workflows" / "wf1" / "agent-ab12.jsonl", "pytest tests/b.py"),
        ):
            child = Transcript(self.root)
            child.bash(command, "1 passed")
            for row in child.rows:
                row["isSidechain"] = True
            child.save(where)
        page = self.read()
        checks = [e for e in page.entries if e.kind == "check"]
        self.assertEqual({"agent-ab12", "workflows/wf1/agent-ab12"}, {e.stream for e in checks})
        self.assertEqual(2, len({e.fact_id for e in checks}))
        self.assertEqual("unchanged", self.source.compare(page.snapshot, self.read()).kind)

    def test_child_swapped_for_a_link_is_not_followed(self) -> None:
        self.session.prompt("Delegate synthetic checks.")
        self.save()
        child = Transcript(self.root)
        child.bash("pytest tests", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        target = self.root / "elsewhere.jsonl"
        child.save(target)
        link = self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        with mock.patch.object(
            project_context, "_admitted_subagent_paths", return_value=[str(link)]
        ):
            page = self.read()
        self.assertEqual(["person"], [e.kind for e in page.entries])
        self.assertIn(
            ("agent-ab12", "unreadable_subagent"),
            [(r.stream, r.reason) for r in page.coverage.unread],
        )

    def test_unavailable_comparison_cannot_claim_unchanged(self) -> None:
        self.session.prompt("Read the synthetic source.")
        self.save()
        previous = self.read()
        self.path.unlink()
        with self.assertRaises(ValueError):
            self.source.compare(previous.snapshot, self.read())
