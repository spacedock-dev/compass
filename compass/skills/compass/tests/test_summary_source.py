"""Synthetic multi-page sources exercise the summary collection boundary."""

from __future__ import annotations

import dataclasses
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import session_source, summary_source
from compass_runtime.config import build_runtime_config

from .test_claude_checks import Transcript, hook_stdout


class SummarySourceTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "session.jsonl"
        self.config = dataclasses.replace(
            build_runtime_config(
                environ={"HOME": str(self.root)},
                launcher_path=self.root / "server.py",
                platform_name="linux",
                os_name="posix",
            ),
            session_source_page_max_bytes=800,
        )
        self.transcript = Transcript(self.root)
        self.pages: list[session_source.SourcePage] = []

    def collect(self, **kwargs: Any) -> tuple[Any, str]:
        return summary_source.collect(
            self.config,
            str(self.path),
            "claude",
            "root",
            deadline=time.monotonic() + 60,
            check=kwargs.pop("check", lambda: ""),
            progress=kwargs.pop("progress", lambda page, _: self.pages.append(page)),
            **kwargs,
        )

    def test_pending_result_and_child_merge_match_one_read_without_duplicates(self) -> None:
        self.config = dataclasses.replace(self.config, session_source_page_max_bytes=1_400)
        self.transcript.prompt("First request")
        self.transcript.bash("pytest tests/test_parent.py", "1 passed")
        self.transcript.prompt("Later correction")
        self.transcript.save(self.path)
        child = Transcript(self.root)
        child.bash("pytest tests/test_child.py", "1 failed", is_error=True)
        child.write(str(self.root / "child.py"))
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertGreater(len(self.pages), 1)
        self.assertEqual(
            ["person", "check", "check", "file", "person"], [e.kind for e in page.entries]
        )
        self.assertEqual(
            ["failed", "passed"], [e.result for e in page.entries if e.kind == "check"]
        )
        whole = session_source.read(
            self.config, str(self.path), "claude", "root", max_bytes=100_000
        )
        self.assertEqual(whole.entries, page.entries)
        self.assertEqual(len(page.entries), len({e.fact_id for e in page.entries}))
        self.assertTrue(page.coverage.complete)
        self.assertEqual((), page.coverage.unread)

    def test_rewritten_call_retires_typed_fact_across_pages(self) -> None:
        call = self.transcript.call("Bash", {"command": "python3 -m pytest tests"})
        self.transcript.hook_rewrite(call, hook_stdout("rtk pytest tests"))
        self.transcript.result(call, "1 passed", is_error=False)
        self.transcript.save(self.path)
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertEqual(["pytest tests"], [e.title for e in page.entries])
        self.assertEqual(1, len(page.snapshot.entries))

    def test_carried_call_without_initial_fact_keeps_its_physical_position(self) -> None:
        for tool in ("Write", "Bash"):
            with self.subTest(tool=tool):
                transcript = Transcript(self.root)
                call = transcript.call(
                    tool,
                    {"file_path": str(self.root / "foo.py"), "content": "a"}
                    if tool == "Write"
                    else {"command": "echo hi"},
                )
                transcript.prompt("Intervening person message")
                # Physical order must win even when the later message's clock goes backwards.
                transcript.rows[-1]["timestamp"] = "2026-09-24T02:00:00Z"
                if tool == "Bash":
                    transcript.hook_rewrite(call, hook_stdout("rtk pytest tests"))
                transcript.result(
                    call,
                    "File created successfully" if tool == "Write" else "1 passed",
                    is_error=False,
                )
                transcript.save(self.path)
                self.pages.clear()
                page, reason = self.collect()
                self.assertEqual("", reason)
                self.assertTrue(page.coverage.complete)
                self.assertGreater(len(self.pages), 1)
                self.assertEqual(
                    ["file" if tool == "Write" else "check", "person"],
                    [entry.kind for entry in page.entries],
                )
                whole = session_source.read(
                    self.config, str(self.path), "claude", "root", max_bytes=100_000
                )
                self.assertEqual(whole.entries, page.entries)

    def test_hook_only_continuation_replaces_or_retracts_a_pending_check(self) -> None:
        for command, titles in (("rtk pytest tests", ["pytest tests"]), ("echo hi", [])):
            with self.subTest(command=command):
                transcript = Transcript(self.root)
                call = transcript.call("Bash", {"command": "python3 -m pytest tests"})
                transcript.hook_rewrite(call, hook_stdout(command))
                transcript.save(self.path)
                self.pages.clear()
                page, reason = self.collect()
                self.assertEqual("", reason)
                self.assertTrue(page.coverage.complete)
                self.assertGreater(len(self.pages), 1)
                self.assertEqual(titles, [entry.title for entry in page.entries])
                whole = session_source.read(
                    self.config, str(self.path), "claude", "root", max_bytes=100_000
                )
                self.assertEqual(whole.entries, page.entries)

    def test_refused_pending_call_retracts_unknown_check(self) -> None:
        call = self.transcript.call("Bash", {"command": "pytest tests"})
        self.transcript.result(
            call, "The user doesn't want to proceed with this tool use.", is_error=True
        )
        self.transcript.prompt("Do something else")
        self.transcript.save(self.path)
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertEqual(["person"], [e.kind for e in page.entries])

    def test_a_later_page_cannot_clear_an_oversized_or_unreadable_line(self) -> None:
        self.transcript.prompt("x" * 2_000)
        for n in range(8):
            self.transcript.prompt(f"Later request {n}")
        self.transcript.save(self.path)
        with self.path.open("ab") as file:
            file.write(b"not json\n")
        self.config = dataclasses.replace(
            self.config, session_source_line_max_bytes=1_000, session_source_page_max_bytes=3_000
        )
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertEqual(8, len(page.entries))
        self.assertFalse(page.coverage.complete)
        self.assertEqual(
            {"oversized_line", "unreadable_record"},
            {region.reason for region in page.coverage.unread},
        )

    def test_append_continues_and_rewrite_or_truncation_stops(self) -> None:
        for operation in ("append", "rewrite", "truncate"):
            with self.subTest(operation=operation):
                self.transcript = Transcript(self.root)
                for n in range(6):
                    self.transcript.prompt(f"Original request {n}")
                self.transcript.save(self.path)
                changed = False

                def progress(
                    _page: session_source.SourcePage, _used: int, operation: str = operation
                ) -> None:
                    nonlocal changed
                    if changed:
                        return
                    changed = True
                    if operation == "append":
                        self.transcript.prompt("Appended request")
                        self.transcript.save(self.path)
                    elif operation == "rewrite":
                        self.path.write_text(self.path.read_text().replace("Original", "Replaced"))
                    else:
                        self.path.write_bytes(b"")

                page, reason = self.collect(progress=progress)
                if operation == "append":
                    self.assertEqual("", reason)
                    self.assertEqual(7, len(page.entries))
                else:
                    self.assertEqual("source_changed", reason)
                    self.assertFalse(page.coverage.complete)

    def test_byte_memory_and_time_limits_keep_explicit_unread_coverage(self) -> None:
        for n in range(8):
            self.transcript.prompt(f"Request {n}")
        self.transcript.save(self.path)
        for setting, value, expected in (
            ("session_summary_source_max_bytes", 1_000, "source_bytes"),
            ("session_summary_source_max_memory_bytes", 1, "source_memory"),
            ("session_summary_source_max_seconds", 0, "source_time"),
        ):
            with self.subTest(setting=setting):
                config = self.config
                bounds: dict[str, Any] = {setting: value}
                self.config = dataclasses.replace(config, **bounds)
                page, reason = self.collect()
                self.config = config
                self.assertEqual(expected, reason)
                self.assertIsNotNone(page.coverage)
                self.assertFalse(page.coverage.complete)
                self.assertIn(expected, {region.reason for region in page.coverage.unread})

    def test_boundary_verification_cannot_spin_when_one_line_consumes_the_page(self) -> None:
        self.transcript.prompt("x" * 200)
        self.transcript.prompt("Later request")
        self.transcript.save(self.path)
        first_line = self.path.read_bytes().splitlines(keepends=True)[0]
        self.config = dataclasses.replace(
            self.config, session_source_page_max_bytes=len(first_line)
        )
        page, reason = self.collect()
        self.assertEqual("source_stalled", reason)
        self.assertEqual(1, len(page.entries))
        self.assertFalse(page.coverage.complete)

    def test_memory_exhaustion_retains_the_accepted_prefix(self) -> None:
        for n in range(30):
            self.transcript.prompt(f"Request {n}: " + "x" * 100)
        self.transcript.save(self.path)
        self.config = dataclasses.replace(
            self.config,
            session_summary_source_max_memory_bytes=20_000,
            session_source_page_max_bytes=1_024,
        )
        page, reason = self.collect()
        self.assertEqual("source_memory", reason)
        self.assertGreater(len(page.entries), 0)
        self.assertLess(len(page.entries), 30)
        self.assertTrue(page.entries[0].words.startswith("Request 0:"))
        self.assertFalse(page.coverage.complete)

    def test_partial_final_line_ends_collection_without_waiting_for_append(self) -> None:
        self.transcript.prompt("First request")
        self.transcript.save(self.path)
        with self.path.open("ab") as file:
            file.write(b'{"type":"user"')
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertEqual(1, len(page.entries))
        self.assertIsNone(page.next)

    def test_earlier_pages_keep_result_resolution_and_boundary_comparison_metadata(self) -> None:
        call = self.transcript.call("Bash", {"command": "pytest tests"})
        self.transcript.save(self.path)
        previous = session_source.read(self.config, str(self.path), "claude", "root")
        assert previous.snapshot is not None
        self.transcript.result(call, "No recorded result", is_error=False)
        for n in range(8):
            self.transcript.prompt(f"Later request {n}")
        self.transcript.save(self.path)
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertIn(("parent", call), page.snapshot.result_calls)
        self.assertIn(previous.snapshot.end_offset, dict(page.snapshot.boundaries))
        change = session_source.compare(previous.snapshot, page)
        self.assertEqual("changed_earlier", change.kind)
        self.assertIn((previous.entries[0].fact_id, "check_result"), change.changed)

    def test_backward_timestamps_preserve_parent_physical_order_across_pages(self) -> None:
        for n in range(8):
            self.transcript.prompt(f"Request {n}")
        self.transcript.rows[-1]["timestamp"] = self.transcript.rows[0]["timestamp"]
        self.transcript.save(self.path)
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertEqual(
            [f"Request {n}" for n in range(8)], [entry.words for entry in page.entries]
        )
        self.assertGreater(page.bytes_read, self.path.stat().st_size)
