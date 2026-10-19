"""Synthetic records exercise the caller-held forward source contract."""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import project_context, record_pages
from compass_runtime.config import build_runtime_config

from . import test_record_pages
from .test_claude_checks import Transcript


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
        self.assertEqual(2, len(self.read(after=page.next).entries))

    def test_unavailable_comparison_cannot_claim_unchanged(self) -> None:
        self.session.prompt("Read the synthetic source.")
        self.save()
        previous = self.read()
        self.path.unlink()
        with self.assertRaises(ValueError):
            self.source.compare(previous.snapshot, self.read())
