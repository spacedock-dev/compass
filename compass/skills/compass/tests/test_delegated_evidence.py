"""The check scan's actual binary-byte allowance and missing delegated work."""

from __future__ import annotations

import builtins
import dataclasses
import datetime as dt
import io
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, Self
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import project_context

from .test_claude_checks import SHORT, SID, START
from .test_subagent_checks import SubagentChecksTestCase

if TYPE_CHECKING:
    from types import TracebackType


class _CountedFile:
    def __init__(self, source: BinaryIO, path: str, reads: list[tuple[str, int]]) -> None:
        self.source = source
        self.path = path
        self.reads = reads

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.source.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.source, name)

    def read(self, size: int = -1) -> bytes:
        raw = self.source.read(size)
        self.reads.append((self.path, len(raw)))
        return raw

    def readline(self, size: int = -1) -> bytes:
        raw = self.source.readline(size)
        self.reads.append((self.path, len(raw)))
        return raw


class DelegatedEvidenceBudget(SubagentChecksTestCase):
    def _trace(self, reads: list[tuple[str, int]]) -> Any:
        real_open = runtime_io._open_scan_binary

        def traced(path: str, *, follow_links: bool) -> _CountedFile:
            source = real_open(path, follow_links=follow_links)
            self.assertIsInstance(source, io.FileIO)
            return _CountedFile(source, path, reads)

        return mock.patch.object(runtime_io, "_open_scan_binary", side_effect=traced)

    def test_parent_and_children_spend_one_actual_binary_allowance(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        first = self.delegate("aaaaaaaaaaaaaaaa")
        first.bash("ruff check .", "All checks passed!", is_error=False)
        self.returns(first)
        second = self.delegate("bbbbbbbbbbbbbbbb")
        second.bash("npm test", "Tests: 1 failed", is_error=True)
        self.returns(second)
        self.save_all()
        first_path, second_path = (path for _sub, path in self.subagents)
        # Windows can stamp both children with the same mtime after save_all.
        # Make the intended newest-child ordering explicit for this budget test.
        second_stat = second_path.stat()
        os.utime(
            second_path,
            ns=(second_stat.st_atime_ns, first_path.stat().st_mtime_ns + 2_000_000_000),
        )
        cap = self.path.stat().st_size + second_path.stat().st_size // 2
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=cap)
        reads: list[tuple[str, int]] = []
        with self._trace(reads):
            _events, scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        self.assertEqual(cap, sum(count for _path, count in reads))
        self.assertEqual(str(self.path), reads[0][0])
        self.assertEqual(
            self.path.stat().st_size, sum(n for path, n in reads if path == str(self.path))
        )
        self.assertNotIn(str(first_path), {path for path, _n in reads})
        self.assertEqual(1, scan["subagent_transcripts_unread"])

    def test_exact_zero_override_opens_no_content_and_does_not_reborrow(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("ruff check .", "All checks passed!", is_error=False)
        self.returns(sub)
        self.save_all()
        reads: list[tuple[str, int]] = []
        with self._trace(reads):
            events, scan = project_context.claude_tool_reports(
                self.config, str(self.path), SHORT, max_bytes=0
            )
        self.assertEqual([], reads)
        self.assertEqual([], events)
        self.assertEqual(1, scan["subagent_transcripts_unread"])

    def test_failed_parent_read_cannot_clear_a_child_pass(self) -> None:
        sub = self.delegate()
        sub.bash("pytest", "5 passed", is_error=False)
        self.returns(sub)
        self.save_all()
        real_open = runtime_io._open_scan_binary

        def refuse_parent(path: str, *, follow_links: bool) -> Any:
            if path == str(self.path):
                raise PermissionError("synthetic parent refusal")
            return real_open(path, follow_links=follow_links)

        with mock.patch.object(runtime_io, "_open_scan_binary", side_effect=refuse_parent):
            events, _scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        check = next(e for e in events if e["subject"] == "check")
        self.assertEqual("passed", check["result"])
        self.assertTrue(check["read_incomplete"])

    def test_explicit_override_cannot_enlarge_the_configured_allowance(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("ruff check .", "All checks passed!", is_error=False)
        self.returns(sub)
        self.save_all()
        cap = self.path.stat().st_size
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=cap)
        reads: list[tuple[str, int]] = []
        with self._trace(reads):
            _events, scan = project_context.claude_tool_reports(
                self.config, str(self.path), SHORT, max_bytes=cap * 2
            )
        self.assertEqual(cap, sum(n for _path, n in reads))
        self.assertEqual(1, scan["subagent_transcripts_unread"])

    def test_frozen_parent_cutoff_spends_but_refuses_when_unreachable(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.save_all()
        cap = self.path.stat().st_size - 1
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=cap)
        reads: list[tuple[str, int]] = []
        with (
            self._trace(reads),
            self.assertRaises(project_context.FrozenCheckCutoffUnreachableError),
        ):
            project_context.frozen_claude_checks(
                self.config, str(self.path), SID, until=START.timestamp() + 3600
            )
        self.assertEqual(cap, sum(n for _path, n in reads))
        self.assertEqual({str(self.path)}, {path for path, _n in reads})

    def test_frozen_stable_relative_path_survives_mtime_reversal(self) -> None:
        first = self.delegate("aaaaaaaaaaaaaaaa")
        first.bash("pytest", "5 passed", is_error=False)
        self.returns(first)
        second = self.delegate("bbbbbbbbbbbbbbbb")
        second.bash("npm test", "Tests: 1 failed", is_error=True)
        self.returns(second)
        self.save_all()
        a_path, b_path = (path for _sub, path in self.subagents)
        # Parent plus exactly one complete child. The lower path wins even if
        # its mtime is older; current mtime cannot rank a historical replay.
        cap = self.path.stat().st_size + a_path.stat().st_size
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=cap)
        stamp = START.timestamp()
        os.utime(a_path, (stamp, stamp))
        os.utime(b_path, (stamp + 100, stamp + 100))
        reads: list[tuple[str, int]] = []
        with self._trace(reads):
            facts, _press = project_context.frozen_claude_checks(
                self.config, str(self.path), SID, until=START.timestamp() + 3600
            )
        self.assertIn(str(a_path), {path for path, _n in reads})
        self.assertNotIn(str(b_path), {path for path, _n in reads})
        self.assertEqual(cap, sum(n for _path, n in reads))
        self.assertEqual(["pytest"], [f["summary"] for f in facts if f.get("subject") == "check"])

    def test_unreachable_child_cutoff_is_unread_and_withholds_a_parent_pass(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.edit(self.file("src/retry.py"))
        self.returns(sub)
        self.save_all()
        child_path = self.subagents[0][1]
        cap = self.path.stat().st_size + child_path.stat().st_size // 2
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=cap)
        reads: list[tuple[str, int]] = []
        with self._trace(reads):
            facts, press = project_context.frozen_claude_checks(
                self.config, str(self.path), SID, until=START.timestamp() + 3600
            )
        check = next(f for f in facts if f.get("subject") == "check")
        self.assertTrue(check["read_incomplete"])
        self.assertEqual(1, len(press.read_incomplete))
        self.assertEqual(cap, sum(n for _path, n in reads))

    def test_first_future_record_is_charged_but_excluded(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        frozen_at = self.session.rows[-1]["timestamp"]
        self.session.bash("npm test", "Tests: 1 failed", is_error=True)
        self.save_all()
        until = dt.datetime.fromisoformat(frozen_at).timestamp()
        lines = self.path.read_bytes().splitlines(keepends=True)
        future_line = next(
            i for i, raw in enumerate(lines) if json.loads(raw)["timestamp"] > frozen_at
        )
        cap = sum(map(len, lines[: future_line + 1]))
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=cap)
        reads: list[tuple[str, int]] = []
        with self._trace(reads):
            facts, _press = project_context.frozen_claude_checks(
                self.config, str(self.path), SID, until=until
            )
        checks = [f for f in facts if f.get("subject") == "check"]
        self.assertEqual(["pytest"], [f["summary"] for f in checks])
        self.assertEqual(cap, sum(n for _path, n in reads))


class BinaryAccounting(SubagentChecksTestCase):
    def test_discarded_partial_and_malformed_bytes_are_charged(self) -> None:
        path = Path(self.root / "binary.jsonl")
        path.write_bytes(b"partial" + b"x" * 20 + b"\nnot-json\n{}\n")
        budget = runtime_io.ReadBudget(15)
        read = runtime_io.scan_reverse_lines(self.config, str(path), budget)
        self.assertEqual(15, read.consumed)
        self.assertEqual(15, budget.spent)
        self.assertFalse(read.complete)

    def test_short_read_charges_only_returned_bytes_and_leaves_a_real_remainder(self) -> None:
        first = Path(self.root / "short.jsonl")
        second = Path(self.root / "second.jsonl")
        first.write_bytes(b"{}\n" * 10)
        second.write_bytes(b"{}\n" * 10)
        real_open = runtime_io._open_scan_binary

        class ShortFile(_CountedFile):
            def read(self, size: int = -1) -> bytes:
                return super().read(max(1, size // 2))

        def short_first(path: str, *, follow_links: bool) -> Any:
            source = real_open(path, follow_links=follow_links)
            return ShortFile(source, path, []) if path == str(first) else source

        budget = runtime_io.ReadBudget(10)
        with mock.patch.object(runtime_io, "_open_scan_binary", side_effect=short_first):
            first_read = runtime_io.scan_reverse_lines(self.config, str(first), budget)
            second_read = runtime_io.scan_reverse_lines(self.config, str(second), budget)
        self.assertEqual(5, first_read.consumed)
        self.assertFalse(first_read.complete)
        self.assertEqual(5, second_read.consumed)
        self.assertEqual(10, budget.spent)

    def test_error_after_a_chunk_keeps_its_charge_and_incomplete_state(self) -> None:
        path = Path(self.root / "error.jsonl")
        path.write_bytes(b"{}\n" * 10)
        config = dataclasses.replace(self.config, reverse_chunk_bytes=5)
        real_open = runtime_io._open_scan_binary

        class ErrorAfterFirst(_CountedFile):
            calls = 0

            def read(self, size: int = -1) -> bytes:
                self.calls += 1
                if self.calls > 1:
                    raise OSError("synthetic read error")
                return super().read(size)

        def failing(path_str: str, *, follow_links: bool) -> ErrorAfterFirst:
            return ErrorAfterFirst(real_open(path_str, follow_links=follow_links), path_str, [])

        budget = runtime_io.ReadBudget(20)
        with mock.patch.object(runtime_io, "_open_scan_binary", side_effect=failing):
            read = runtime_io.scan_reverse_lines(config, str(path), budget)
        self.assertEqual(5, read.consumed)
        self.assertEqual(5, budget.spent)
        self.assertFalse(read.complete)

    def test_frozen_lookup_stops_at_the_held_extent_during_an_append(self) -> None:
        path = Path(self.root / "growing.jsonl")
        original = b'{"timestamp":"2026-09-24T03:00:00Z"}'
        path.write_bytes(original)
        actual_stat = os.fstat
        actual_open = runtime_io._open_scan_binary
        held_fd: int | None = None
        appended = False

        def hold_source(path_str: str, *, follow_links: bool) -> BinaryIO:
            nonlocal held_fd
            source = actual_open(path_str, follow_links=follow_links)
            held_fd = source.fileno()
            return source

        def grow_after_stat(fd: int) -> Any:
            nonlocal appended
            found = actual_stat(fd)
            # Directory and file-admission stats precede the scan's held extent.
            if fd == held_fd and not appended:
                appended = True
                with path.open("ab") as handle:
                    handle.write(b'\n{"timestamp":"2026-09-24T04:00:00Z"}\n')
            return found

        budget = runtime_io.ReadBudget(len(original) * 4)
        with (
            mock.patch.object(runtime_io, "_open_scan_binary", side_effect=hold_source),
            mock.patch.object(os, "fstat", side_effect=grow_after_stat),
        ):
            read = runtime_io.scan_stood_lines(str(path), budget, lambda _raw: False)
        self.assertTrue(appended)
        self.assertEqual(len(original), read.consumed)
        self.assertEqual(len(original), budget.spent)
        self.assertEqual((original,), read.lines)


class SeparateFrozenReadClasses(SubagentChecksTestCase):
    def _measure_transcript_reads(self, call: Any) -> int:
        actual_open = builtins.open
        actual_fdopen = os.fdopen
        counted = [0]

        class CountedRaw(io.FileIO):
            def read(self, size: int | None = -1) -> bytes:
                raw = super().read(size)
                counted[0] += len(raw)
                return raw

            def readinto(self, buffer: Any) -> int:
                count = super().readinto(buffer)
                counted[0] += count
                return count

        def counted_stream(file: Any, mode: str, kwargs: dict[str, Any]) -> Any:
            binary = io.BufferedReader(CountedRaw(file, "rb"))
            if "b" in mode:
                return binary
            return io.TextIOWrapper(
                binary,
                encoding=kwargs.get("encoding") or "utf-8",
                errors=kwargs.get("errors") or "strict",
            )

        def counted_open(path: Any, mode: str = "r", **kwargs: Any) -> Any:
            if str(path) != str(self.path):
                return actual_open(path, mode, **kwargs)
            return counted_stream(path, mode, kwargs)

        def counted_fdopen(fd: int, mode: str = "r", **kwargs: Any) -> Any:
            if os.fstat(fd).st_ino != self.path.stat().st_ino:
                return actual_fdopen(fd, mode, **kwargs)
            return counted_stream(fd, mode, kwargs)

        with (
            mock.patch("builtins.open", side_effect=counted_open),
            mock.patch.object(os, "fdopen", side_effect=counted_fdopen),
        ):
            call()
        return counted[0]

    def test_a_check_cap_is_not_a_whole_freeze_read_cap(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        sub = self.delegate()
        sub.bash("ruff check .", "All checks passed!", is_error=False)
        self.returns(sub)
        self.save_all()
        parent_size = self.path.stat().st_size
        child_size = self.subagents[0][1].stat().st_size
        scan = project_context._frozen_check_scan(
            self.config, str(self.path), START.timestamp() + 3600
        )
        check_bytes = scan.budget.spent
        self.assertEqual(parent_size + child_size, check_bytes)

        scripts = str(Path(__file__).parents[4] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import mark_abstention  # noqa: PLC0415 - the qualifier is only measured here

        identity = self._measure_transcript_reads(
            lambda: mark_abstention._transcript_is_the_session(str(self.path), SID)
        )
        activity = self._measure_transcript_reads(
            lambda: project_context.claude_activity_between(
                str(self.path), START.timestamp() + 7200, START.timestamp() + 7300
            )
        )
        messages = self._measure_transcript_reads(
            lambda: project_context.frozen_claude_user_messages(
                self.config,
                str(self.path),
                SID,
                until=START.timestamp() + 3600,
                size=parent_size,
            )
        )
        self.assertEqual(parent_size, identity)
        self.assertEqual(parent_size, activity)
        self.assertEqual(parent_size * 2, messages)
        self.assertEqual(
            check_bytes + 4 * parent_size, check_bytes + identity + activity + messages
        )
