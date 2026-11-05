"""Synthetic multi-page sources exercise the summary collection boundary."""

from __future__ import annotations

import builtins
import dataclasses
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import project_scripts, session_source, summary_source
from compass_runtime.config import build_runtime_config

from .test_claude_checks import Transcript, hook_stdout
from .test_project_script_checks import git, package


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

    def declaration_fixture(self, *, script: str = "tsc --noEmit") -> None:
        project_scripts.reset()
        self.addCleanup(project_scripts.reset)
        git(self.root, "init", "-q")
        (self.root / "package.json").write_text(package(typecheck=script, test=script))
        git(self.root, "add", "package.json")
        git(self.root, "commit", "-qm", "Owned declaration")
        self.config = dataclasses.replace(
            self.config, git_probe_enabled=True, session_source_page_max_bytes=4_000
        )

    def declaration_transcript(
        self, *, write: bool = True, command: str = "pnpm typecheck"
    ) -> None:
        self.transcript.prompt("Owned summary declaration regression")
        self.transcript.bash(f"{command}; pytest tests/direct.py", "1 passed")
        for index in range(10):
            self.transcript.prompt(f"Before write {index}: " + "padding " * 100)
        if write:
            self.transcript.write(str(self.root / "package.json"))
        for index in range(10):
            self.transcript.prompt(f"After write {index}: " + "padding " * 100)
        self.transcript.bash(command, "1 passed")
        self.transcript.save(self.path)

    def assert_complete_oracle(self) -> session_source.SourcePage:
        whole = session_source.read(
            self.config, str(self.path), "claude", "root", max_bytes=100_000
        )
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertTrue(page.coverage.complete)
        self.assertGreater(len(self.pages), 2)
        self.assertEqual(whole.entries, page.entries)
        return whole

    def test_later_declaration_write_reconciles_complete_collection(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript()
        whole = self.assert_complete_oracle()
        self.assertEqual(
            ["pytest tests/direct.py"], [e.title for e in whole.entries if e.kind == "check"]
        )

    def test_no_write_keeps_declared_checks(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript(write=False)
        whole = self.assert_complete_oracle()
        self.assertEqual(3, len([e for e in whole.entries if e.kind == "check"]))

    def test_withdrawal_restores_previously_unemitted_closed_list_check(self) -> None:
        self.declaration_fixture(script="echo skipped")
        self.declaration_transcript(command="pnpm test")
        whole = self.assert_complete_oracle()
        self.assertEqual(
            ["pnpm test", "pytest tests/direct.py", "pnpm test"],
            [e.title for e in whole.entries if e.kind == "check"],
        )
        self.assertNotIn("pnpm test", [e.title for e in self.pages[0].entries])

    def test_child_write_reconciles_parent_and_sibling_checks(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript(write=False)
        for name, writes in (("agent-ab12", False), ("agent-cd34", True)):
            child = Transcript(self.root)
            child.bash("pnpm typecheck; pytest tests/child.py", "1 passed")
            for index in range(8):
                child.prompt(f"Child padding {index}: " + "padding " * 100)
            if writes:
                child.write(str(self.root / "package.json"))
            child.write(str(self.root / f"{name}.py"))
            for row in child.rows:
                row["isSidechain"] = True
            child.save(self.path.with_suffix("") / "subagents" / f"{name}.jsonl")
        whole = self.assert_complete_oracle()
        self.assertEqual(3, len([e for e in whole.entries if e.kind == "check"]))
        self.assertEqual(3, len([e for e in whole.entries if e.kind == "file"]))
        self.assertTrue(
            all(e.title.startswith("pytest") for e in whole.entries if e.kind == "check")
        )

    def test_single_page_withdrawal_needs_no_replay(self) -> None:
        self.declaration_fixture()
        self.transcript.prompt("Owned one-page source")
        self.transcript.bash("pnpm typecheck", "1 passed")
        self.transcript.write(str(self.root / "package.json"))
        self.transcript.save(self.path)
        size = self.path.stat().st_size + len(self.path.read_bytes().splitlines(keepends=True)[0])
        self.config = dataclasses.replace(self.config, session_summary_source_max_bytes=size)
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertTrue(page.coverage.complete)
        self.assertEqual(size, page.bytes_read)

    def test_actual_file_reads_include_metadata_and_reconciliation_in_one_allowance(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript()
        child = Transcript(self.root)
        child.bash("pnpm typecheck; pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        original = builtins.open
        original_fdopen = os.fdopen
        reads = [0]

        def metered(handle: Any) -> Any:
            proxy = mock.MagicMock(wraps=handle)
            proxy.__enter__.return_value = proxy
            proxy.__exit__.side_effect = handle.__exit__

            def count(method: Any, size: int = -1) -> bytes:
                raw: bytes = method(size)
                reads[0] += len(raw)
                return raw

            proxy.read.side_effect = lambda size=-1: count(handle.read, size)
            proxy.readline.side_effect = lambda size=-1: count(handle.readline, size)
            return proxy

        def opened(file: Any, *args: Any, **kwargs: Any) -> Any:
            handle = original(file, *args, **kwargs)
            if str(file) != str(self.path) or "b" not in str(
                args[0] if args else kwargs.get("mode")
            ):
                return handle
            return metered(handle)

        with (
            mock.patch("builtins.open", side_effect=opened),
            mock.patch(
                "os.fdopen", side_effect=lambda *a, **kw: metered(original_fdopen(*a, **kw))
            ),
        ):
            page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertEqual(reads[0], page.bytes_read)
        self.assertGreater(page.bytes_read, self.path.stat().st_size)
        self.assertLessEqual(page.bytes_read, self.config.session_summary_source_max_bytes)

    def test_reconciliation_stops_with_no_obsolete_prefix_on_cancel_time_or_byte_cap(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript()
        original = session_source.read
        observed_write = [False]
        used = len(self.path.read_bytes().splitlines(keepends=True)[0])
        at_write = 0

        def read(*args: Any, **kwargs: Any) -> session_source.SourcePage:
            nonlocal used, at_write
            prior = set(kwargs["observed_writes"])
            page = original(*args, **kwargs)
            used += page.bytes_read
            if prior != kwargs["observed_writes"]:
                observed_write[0] = True
                at_write = used
            return page

        for stop in ("cancelled", "source_time"):
            with self.subTest(stop=stop):
                observed_write[0] = False
                used = len(self.path.read_bytes().splitlines(keepends=True)[0])
                with mock.patch.object(session_source, "read", side_effect=read):
                    page, reason = self.collect(
                        check=lambda stop=stop: (
                            "cancelled" if observed_write[0] and stop == "cancelled" else ""
                        ),
                        clock=lambda stop=stop: (
                            time.monotonic()
                            + (100 if observed_write[0] and stop == "source_time" else 0)
                        ),
                    )
                self.assertTrue(observed_write[0])
                self.assertEqual(stop, reason)
                self.assertFalse(page.coverage.complete)
                self.assertEqual((), page.entries)
        self.config = dataclasses.replace(self.config, session_summary_source_max_bytes=at_write)
        page, reason = self.collect()
        self.assertEqual("source_bytes", reason)
        self.assertFalse(page.coverage.complete)
        self.assertEqual((), page.entries)
        self.assertEqual(at_write, page.bytes_read)

    def test_rewind_keeps_source_version_guard(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript()
        original = session_source.read
        changed = False

        def read(*args: Any, **kwargs: Any) -> session_source.SourcePage:
            nonlocal changed
            prior = set(kwargs["observed_writes"])
            page = original(*args, **kwargs)
            if not changed and prior != kwargs["observed_writes"]:
                changed = True
                self.path.write_text(
                    self.path.read_text().replace("Owned summary", "Other summary")
                )
            return page

        with mock.patch.object(session_source, "read", side_effect=read):
            page, reason = self.collect()
        self.assertTrue(changed)
        self.assertEqual("source_changed", reason)
        self.assertFalse(page.coverage.complete)
        self.assertEqual((), page.entries)

    def test_clipped_head_metadata_cannot_certify_a_complete_collection(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript()
        self.config = dataclasses.replace(self.config, session_summary_source_max_bytes=30)
        page, reason = self.collect()
        self.assertEqual("source_bytes", reason)
        self.assertFalse(page.coverage.complete)
        self.assertEqual(30, page.bytes_read)
        self.assertEqual((), page.entries)

    def test_missing_head_time_uses_the_canonical_first_stamped_body_fallback(self) -> None:
        self.declaration_fixture()
        self.declaration_transcript(write=False)
        self.transcript.rows[0].pop("timestamp")
        self.transcript.save(self.path)
        self.config = dataclasses.replace(self.config, claude_cwd_scan_lines=1)
        self.assert_complete_oracle()

    def test_missing_head_fields_keep_anonymous_person_sources_complete(self) -> None:
        for index in range(8):
            self.transcript.prompt(f"Anonymous request {index}")
        for row in self.transcript.rows:
            row.pop("cwd", None)
            row.pop("timestamp", None)
        self.transcript.save(self.path)
        whole = session_source.read(
            self.config, str(self.path), "claude", "root", max_bytes=100_000
        )
        page, reason = self.collect()
        self.assertEqual("", reason)
        self.assertTrue(page.coverage.complete)
        self.assertEqual(whole.entries, page.entries)

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
