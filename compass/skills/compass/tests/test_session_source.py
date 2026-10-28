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
from .test_claude_checks import Transcript, hook_stdout


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
