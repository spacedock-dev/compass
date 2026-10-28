"""What a Claude Code reader sees of the checks a session ran and the files it wrote.

DEC-23 (docs/design-reading-a-session.md) is the ruling. Every fixture below is
built from the field SHAPES in
`docs/captures/claude/transcript-tool-shapes-2.1.281-macos.jsonl`: an assistant
record holding a `tool_use` block (`id`, `name`, `input`), and a user record
holding the `tool_result` block that points back at it (`tool_use_id`,
`content`, and `is_error` on a shell result only). No text here came from a real
transcript.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import re
import shlex
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import levels, observer, project_context, reading, semantic_history
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

SID = "4a1c9e7d-0000-4000-8000-000000000001"
SHORT = SID[:8]
START = dt.datetime(2026, 9, 24, 3, 0, 0, tzinfo=dt.UTC)
# Synthetic, and deliberately obvious: a real prefix followed by a run of one letter.
FAKE_KEY = "sk-ant-api03-" + "Q" * 95
# A value only a named form marks as secret, which redaction alone would not see.
PLACEHOLDER = "EXAMPLEpw1234"
# Node's summary glyph and failure glyph, written as escapes so review can read them.
INFO = "\u2139"
CROSS = "\u2716"


class Transcript:
    """A Claude Code transcript in the recorded shapes, one call at a time."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = str(cwd)
        self.rows: list[dict[str, Any]] = []
        self.seconds = 0
        self.calls = 0

    def _stamp(self) -> str:
        self.seconds += 5
        return (START + dt.timedelta(seconds=self.seconds)).isoformat().replace("+00:00", "Z")

    def _entry(self, kind: str, content: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "type": kind,
            "uuid": f"u{len(self.rows)}",
            "parentUuid": f"u{len(self.rows) - 1}" if self.rows else None,
            "isSidechain": False,
            "cwd": self.cwd,
            "sessionId": SID,
            "timestamp": self._stamp(),
            "message": {"role": kind, "content": content},
        }
        row.update(extra)
        self.rows.append(row)
        return row

    def prompt(self, text: str) -> None:
        self._entry("user", [{"type": "text", "text": text}])

    def call(self, name: str, tool_input: dict[str, Any], *, sidechain: bool = False) -> str:
        self.calls += 1
        call_id = f"toolu_{self.calls:03d}"
        self._entry(
            "assistant",
            [
                {
                    "type": "tool_use",
                    "id": call_id,
                    "name": name,
                    "input": tool_input,
                    "caller": {"type": "direct"},
                }
            ],
            isSidechain=sidechain,
        )
        return call_id

    def result(self, call_id: str, content: Any, **block: Any) -> None:
        tool_use_result = block.pop("tool_use_result", {})
        self._entry(
            "user",
            [{"type": "tool_result", "tool_use_id": call_id, "content": content, **block}],
            toolUseResult=tool_use_result,
        )

    def bash(self, command: str, output: str = "", *, is_error: Any = False, **extra: Any) -> str:
        """A call that ran. A failing one opens with `Exit code N`, as Claude Code
        records a command that exited nonzero; a call that never ran is built
        with `call` and `result` instead."""
        call_id = self.call("Bash", {"command": command, **extra})
        if is_error is True and not output.startswith("Exit code "):
            output = "Exit code 1\n" + output
        self.result(call_id, output, is_error=is_error)
        return call_id

    def hook_rewrite(
        self, call_id: str, stdout: str, *, hook: str = "PreToolUse:Bash", sidechain: bool = False
    ) -> None:
        """The record Claude Code writes when a PreToolUse hook answers a Bash call."""
        self.rows.append(
            {
                "type": "attachment",
                "isSidechain": sidechain,
                "cwd": self.cwd,
                "sessionId": SID,
                "timestamp": self._stamp(),
                "attachment": {
                    "type": "hook_success",
                    "hookName": hook,
                    "hookEvent": hook.split(":", 1)[0],
                    "toolUseID": call_id,
                    "stdout": stdout,
                    "exitCode": 0,
                },
            }
        )

    def write(self, path: str, content: str = "print('hello')\n") -> None:
        call_id = self.call("Write", {"file_path": path, "content": content})
        self.result(call_id, f"File created successfully at: {path}")

    def edit(self, path: str, old: str = "a", new: str = "b") -> None:
        call_id = self.call("Edit", {"file_path": path, "old_string": old, "new_string": new})
        self.result(call_id, f"The file {path} has been updated successfully.")

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8")


def hook_stdout(command: str) -> str:
    """What an output-rewriting hook prints: the call, with its command replaced."""
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "auto-rewrite",
                "updatedInput": {"command": command},
            }
        }
    )


class ClaudeChecksTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "work" / "billing"
        self.cwd.mkdir(parents=True)
        self.path = self.root / "claude" / "projects" / "-work-billing" / f"{SID}.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"claude.projects": str(self.root / "claude" / "projects")},
        )
        self.session = Transcript(self.cwd)
        self.session.prompt("Add retry with backoff to the webhook handler.")

    def file(self, name: str) -> str:
        return str(self.cwd / name)

    def read(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.session.save(self.path)
        return project_context.claude_tool_reports(self.config, str(self.path), SHORT)

    def checks(self) -> list[dict[str, Any]]:
        return [event for event in self.read()[0] if event["subject"] == "check"]

    def only_check(self) -> dict[str, Any]:
        found = self.checks()
        self.assertEqual(1, len(found), found)
        return found[0]


class WindowedWrittenPathCount(ClaudeChecksTestCase):
    def read_window(self, cutoff: float | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.session.save(self.path)
        return project_context.claude_tool_reports(
            self.config, str(self.path), SHORT, window_start=cutoff
        )

    def cutoff(self) -> float:
        last = self.session.rows[-1]["timestamp"]
        return dt.datetime.fromisoformat(last).timestamp() + 0.5

    def test_explicit_unknown_window_keeps_the_default_replay_scan_unchanged(self) -> None:
        self.session.write(self.file("src/one.py"))
        self.session.write(self.file("src/two.py"))

        _entries, replay_scan = self.read()
        _entries, result_scan = self.read_window(None)

        self.assertNotIn("window_written_paths", replay_scan)
        self.assertIsNone(result_scan["window_start"])
        self.assertEqual(2, result_scan["window_written_paths"])

    def test_pre_window_and_untallied_rows_do_not_enter_the_result_count(self) -> None:
        self.session.write(self.file("old/one.py"))
        self.session.write(self.file("old/two.py"))
        cutoff = self.cutoff()
        self.session.write(self.file("new/one.py"))
        self.session.write(self.file("new/two.py"))
        # Failed checks take the twelve listing slots, but the scan still
        # knows both in-window paths and excludes the old pair.
        for index in range(13):
            self.session.bash(f"pytest tests/test_{index}.py", "1 failed", is_error=True)

        entries, scan = self.read_window(cutoff)

        self.assertFalse([row for row in entries if row["subject"] == "write"])
        self.assertEqual(4, scan["written_paths"])
        self.assertEqual(cutoff, scan["window_start"])
        self.assertEqual(2, scan["window_written_paths"])

    def test_latest_write_of_a_path_sets_its_window_membership_once(self) -> None:
        self.session.write(self.file("shared.py"))
        cutoff = self.cutoff()
        self.session.edit(self.file("shared.py"))
        self.session.write(self.file("new.py"))

        entries, scan = self.read_window(cutoff)

        self.assertEqual(2, scan["written_paths"])
        self.assertEqual(2, scan["window_written_paths"])
        self.assertEqual(2, len([row for row in entries if row["subject"] == "write"]))


class WhatAReaderSeesOfTheChecksASessionRan(ClaudeChecksTestCase):
    def test_a_fixed_check_reads_as_passed_with_its_earlier_failure_noted_once(self) -> None:
        self.session.write(self.file("src/retry.py"))
        self.session.bash("python3 -m pytest tests", "1 failed, 4 passed in 0.31s", is_error=True)
        self.session.bash("python3 -m pytest tests", "5 passed in 0.29s", is_error=False)

        events, scan = self.read()

        checks = [event for event in events if event["subject"] == "check"]
        writes = [event for event in events if event["subject"] == "write"]
        self.assertEqual(1, len(checks))
        self.assertEqual("passed", checks[0]["result"])
        self.assertEqual("flag", checks[0]["result_source"])
        self.assertIs(True, checks[0]["earlier_failed"])
        self.assertEqual("python3 -m pytest tests", checks[0]["title"])
        self.assertEqual(["src/retry.py"], [event["title"] for event in writes])
        self.assertEqual(2, scan["check_runs"])
        self.assertEqual(1, scan["distinct_checks"])
        self.assertEqual(1, scan["written_paths"])

    def test_a_check_publishes_an_identity_that_a_directory_changes(self) -> None:
        # The page pairs a failed run with a later pass by this identity. The command line is the
        # same in both directories, so only the identity can keep a pass in one from hiding a
        # failure in the other.
        self.session.bash("cd api && pytest -q", "1 failed in 0.1s", is_error=True)
        self.session.bash("cd web && pytest -q", "1 passed in 0.1s", is_error=False)
        self.session.bash("cd api && pytest -q", "1 failed in 0.1s", is_error=True)

        checks = self.checks()

        self.assertEqual(2, len(checks), checks)
        self.assertEqual({"pytest -q"}, {check["title"] for check in checks})
        identities = {check["check_id"] for check in checks}
        self.assertEqual(2, len(identities))
        self.assertTrue(all(identity.startswith("check:") for identity in identities))

    def test_a_written_path_carries_no_check_identity(self) -> None:
        self.session.write(self.file("src/retry.py"))
        self.session.bash("pytest -q", "1 passed in 0.1s", is_error=False)

        events, _scan = self.read()

        self.assertNotIn("check_id", next(event for event in events if event["subject"] == "write"))

    def test_a_piped_run_whose_tail_says_two_failed_is_a_failure_whatever_the_flag(self) -> None:
        self.session.bash(
            "pytest -q 2>&1 | tail -3",
            "FAILED tests/test_retry.py::test_backoff\n2 failed, 3 passed",
        )
        check = self.only_check()
        self.assertEqual("failed", check["result"])
        self.assertEqual("summary", check["result_source"])

    def test_a_piped_node_run_that_kept_only_an_assertion_marker_is_a_failure(self) -> None:
        tail = (
            "  code: 'ERR_ASSERTION',\n  actual: 2,\n  expected: 3,\n  operator: 'strictEqual'\n}"
        )
        self.session.bash("node --test 2>&1 | tail -20", tail, is_error=False)
        check = self.only_check()
        self.assertEqual("failed", check["result"])
        self.assertEqual("marker", check["result_source"])

    def test_a_piped_run_that_left_no_summary_or_marker_is_never_a_pass(self) -> None:
        self.session.bash("pytest -q 2>&1 | tail -2", "collected 5 items\n.....", is_error=False)
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertNotIn("result_source", check)

    def test_a_pass_never_rests_on_a_missing_or_malformed_error_flag(self) -> None:
        flags: tuple[Any, ...] = (None, "false", 0, [], {})
        for flag in flags:
            with self.subTest(flag=flag):
                self.setUp()
                call_id = self.session.call("Bash", {"command": "pytest"})
                block = {} if flag is None else {"is_error": flag}
                self.session.result(call_id, "", **block)
                check = self.only_check()
                self.assertEqual("not-recorded", check["result"])
                self.assertEqual(1, self.read()[1]["unknown_flags"])

    def test_node_prints_its_counts_one_per_line_and_fail_zero_is_a_pass(self) -> None:
        passing = f"{INFO} tests 5\n{INFO} suites 0\n{INFO} pass 5\n{INFO} fail 0\n{INFO} cancelled 0\n{INFO} duration_ms 52"
        failing = f"{INFO} tests 5\n{INFO} suites 0\n{INFO} pass 3\n{INFO} fail 2\n{INFO} cancelled 0\n{INFO} duration_ms 55"
        for output, expected in ((passing, "passed"), (failing, "failed")):
            with self.subTest(expected=expected):
                self.setUp()
                self.session.bash("node --test 2>&1 | tail -8", output, is_error=False)
                check = self.only_check()
                self.assertEqual(expected, check["result"])
                self.assertEqual("summary", check["result_source"])

    def test_a_node_pass_count_alone_is_not_a_pass(self) -> None:
        self.session.bash(
            "node --test 2>&1 | head -3", f"{INFO} tests 5\n{INFO} pass 5", is_error=False
        )
        self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_check_after_cd_is_listed_and_its_flag_is_read(self) -> None:
        self.session.bash("cd services/billing && python3 -m unittest", "", is_error=True)
        check = self.only_check()
        self.assertEqual("python3 -m unittest", check["title"])
        self.assertEqual("failed", check["result"])
        self.assertEqual("flag", check["result_source"])

    def test_a_flag_is_read_through_and_and_never_through_a_semicolon_or_pipe(self) -> None:
        for command, expected in (
            ("pytest && echo done", "passed"),
            ("pytest; echo done", "not-recorded"),
            ("pytest | tee out.log", "not-recorded"),
            ("pytest || true", "not-recorded"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(expected, self.only_check()["result"])

    def test_wrappers_and_assignments_are_stripped_before_the_runner_is_matched(self) -> None:
        for command, title in (
            ("CI=1 uv run pytest -q", "pytest -q"),
            ("timeout 60 npx jest --ci", "jest --ci"),
            ("poetry run mypy src", "mypy src"),
            ("time cargo test", "cargo test"),
            ("python3 scripts/run_tests.py -j 4", "python3 scripts/run_tests.py -j 4"),
            ("./test.sh", "./test.sh"),
            ("ruff format --check .", "ruff format --check ."),
            ("tsc --noEmit", "tsc --noEmit"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(title, self.only_check()["title"])

    def test_pnpm_shorthand_for_a_closed_runner_is_a_check_and_other_words_are_not(self) -> None:
        for words, is_check in (
            (["pnpm", "vitest", "run", "x.test.tsx"], True),
            (["pnpm", "tsc", "--noEmit"], True),
            (["pnpm", "eslint", "."], True),
            (["pnpm", "playwright", "install"], False),
            (["pnpm", "install"], False),
            (["pnpm", "dev"], False),
        ):
            with self.subTest(words=words):
                self.assertIs(is_check, project_context._is_check(words))

    def test_a_lone_pnpm_shorthand_call_reads_its_summary_like_the_exec_form(self) -> None:
        output = "Test Files  1 failed (1)\n     Tests  2 failed | 5 passed (7)"
        for command in (
            "pnpm vitest run x.test.tsx 2>&1 | tail -40",
            "pnpm exec vitest run x.test.tsx 2>&1 | tail -40",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                check = self.only_check()
                self.assertEqual("failed", check["result"])
                self.assertEqual("summary", check["result_source"])

    def test_a_check_line_is_its_own_segment_and_never_the_rest_of_the_shell_line(self) -> None:
        self.session.bash("cd api && pytest -q 2>&1 | tail -3 ; echo done", "3 passed")
        title = self.only_check()["title"]
        # A redirection is not an argument, so it is not published (review, 2026-09-27).
        self.assertEqual("pytest -q", title)

    def test_a_program_file_is_a_check_only_when_test_stands_alone_in_its_name(self) -> None:
        for command, is_check in (
            ("python3 scripts/run_tests.py", True),
            ("./test.sh", True),
            ("bash ci/unit-tests.sh", True),
            ("python3 runtests.py", False),
            ("python3 fetch_latest_creds.py", False),
            ("./contest.sh", False),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(is_check, bool(self.checks()))

    def test_a_pass_summary_beside_any_record_of_failure_is_a_failure(self) -> None:
        for output, source in (
            ("1 failed, 9 passed in 0.4s", "summary"),
            ("AssertionError: retries\n9 passed", "marker"),
        ):
            with self.subTest(output=output):
                self.setUp()
                self.session.bash("pytest 2>&1 | tail -4", output, is_error=False)
                check = self.only_check()
                self.assertEqual("failed", check["result"])
                self.assertEqual(source, check["result_source"])

    def test_go_and_unittest_passes_need_the_flag_or_the_whole_summary_line(self) -> None:
        for command, output, expected in (
            ("go test ./... | tail -2", "ok  \texample.com/retry\t0.2s", "not-recorded"),
            ("go test ./...", "ok  \texample.com/retry\t0.2s", "passed"),
            ("python3 -m unittest 2>&1 | tail -1", "OK (skipped=1)", "passed"),
            ("python3 -m unittest 2>&1 | tail -1", "Ran 4 tests in 0.01s\n\nOK", "passed"),
        ):
            with self.subTest(command=command, output=output):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                self.assertEqual(expected, self.only_check()["result"])

    def test_commands_that_only_read_are_told_apart_from_ones_that_may_change_things(
        self,
    ) -> None:
        self.session.bash("git status && git diff --stat", "", is_error=False)
        self.session.bash("cd src && ls | wc -l", "", is_error=False)
        self.session.bash("find . -name '*.py' | head", "", is_error=False)
        self.session.bash("echo ready > status.txt", "", is_error=False)
        self.session.bash("find . -name '*.pyc' -delete", "", is_error=False)
        self.session.bash("pip install requests", "", is_error=False)
        events, scan = self.read()
        # The two that may change things are tier 3 commands, listed apart from any check; a
        # redirect of `echo` and the reads are not.
        self.assertEqual({"command"}, {event["subject"] for event in events})
        self.assertCountEqual(
            ["pip install requests", "find . -name *.pyc -delete"],
            [event["title"] for event in events],
        )
        self.assertEqual(6, scan["other_commands"])
        self.assertEqual(3, scan["read_only_commands"])
        self.assertIsNotNone(scan["last_changing_command_at"])

    def test_a_session_that_only_read_records_no_changing_command(self) -> None:
        self.session.bash("git log --oneline -5", "", is_error=False)
        self.assertIsNone(self.read()[1]["last_changing_command_at"])

    def test_a_check_on_a_later_line_of_a_multiline_command_is_found(self) -> None:
        self.session.bash("cd services/api\npytest -q", "", is_error=True)
        check = self.only_check()
        self.assertEqual("pytest -q", check["title"])
        self.assertEqual("failed", check["result"])
        self.assertEqual("flag", check["result_source"])

    def test_only_and_may_follow_a_runner_whose_flag_is_read(self) -> None:
        for command in ("pytest\necho done", "pytest ; echo", "pytest | cat", "pytest || true"):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual("not-recorded", self.only_check()["result"])

    def test_pytest_errors_are_failures_by_summary_and_by_marker(self) -> None:
        for output, source in (
            ("1 error in 0.20s", "summary"),
            ("3 passed, 2 errors in 0.4s", "summary"),
            ("ERROR tests/test_retry.py - ImportError: no module", "marker"),
        ):
            with self.subTest(output=output):
                self.setUp()
                self.session.bash("pytest 2>&1 | tail -3", output, is_error=False)
                check = self.only_check()
                self.assertEqual("failed", check["result"])
                self.assertEqual(source, check["result_source"])

    def test_a_pass_that_ran_nothing_is_not_a_pass(self) -> None:
        for command, output in (
            ("node --test 2>&1 | tail -3", f"{INFO} tests 0\n{INFO} pass 0\n{INFO} fail 0"),
            ("pytest 2>&1 | tail -1", "0 passed in 0.01s"),
            ("python3 -m unittest 2>&1 | tail -3", "Ran 0 tests in 0.000s\n\nOK"),
            ("go test ./...", "ok  \texample.com/retry\t0.2s [no tests to run]"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_changing_segment_is_timed_even_inside_a_check_command(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("pip install requests && pytest", "5 passed", is_error=False)
        events, scan = self.read()
        check = next(event for event in events if event["subject"] == "check")
        self.assertEqual(check["at"], scan["last_changing_command_at"])
        self.assertEqual(0, scan["other_commands"])

    def test_a_changing_command_after_a_pass_is_timed_after_it(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("git commit -am wip", "", is_error=False)
        events, scan = self.read()
        check = next(event for event in events if event["subject"] == "check")
        self.assertGreater(scan["last_changing_command_at"], check["at"])
        self.assertNotIn("git commit", json.dumps(scan))

    def test_a_changing_command_launched_in_the_background_is_still_timed(self) -> None:
        call_id = self.session.call("Bash", {"command": "npm run dev", "run_in_background": True})
        self.session.result(call_id, "Command running in background with ID: b2.")
        scan = self.read()[1]
        self.assertEqual(1, scan["background"])
        self.assertIsNotNone(scan["last_changing_command_at"])

    def test_commands_off_the_closed_list_are_counted_and_listed_only_as_commands(self) -> None:
        self.session.bash("grep -rn retry_after src", "", is_error=True)
        self.session.bash("ls docs/missing.md", "ls: docs/missing.md: No such file", is_error=True)
        self.session.bash("test -f setup.cfg && echo yes", "", is_error=True)
        self.session.bash("[ -d build ] || mkdir build", "", is_error=False)
        self.session.bash("ruff format .", "3 files reformatted", is_error=False)
        events, scan = self.read()
        # Only the two that may change files are commands: the reads are on the read-only list.
        self.assertEqual(
            [("mkdir build", "not-recorded"), ("ruff format .", "passed")],
            sorted((event["title"], event["result"]) for event in events),
        )
        self.assertEqual({"command"}, {event["subject"] for event in events})
        self.assertEqual(5, scan["shell_calls"])
        self.assertEqual(5, scan["other_commands"])
        self.assertEqual(0, scan["check_runs"])

    def test_a_background_test_launch_is_counted_and_never_listed_or_read_as_a_result(
        self,
    ) -> None:
        call_id = self.session.call("Bash", {"command": "node --test", "run_in_background": True})
        self.session.result(
            call_id,
            "Command running in background with ID: b1. You will be notified.",
            is_error=False,
            tool_use_result={"backgroundTaskId": "b1", "stdout": "", "stderr": ""},
        )
        self.session.bash("pytest &", "", is_error=False)
        events, scan = self.read()
        self.assertEqual(["background_launch"] * 2, [row["kind"] for row in events])
        self.assertEqual(2, scan["background"])
        self.assertEqual(0, scan["check_runs"])

    def test_a_pass_followed_by_a_write_is_marked_before_the_last_change(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.edit(self.file("src/retry.py"))
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["before_last_change"])

    def test_a_pass_after_the_last_write_is_not_marked(self) -> None:
        self.session.edit(self.file("src/retry.py"))
        self.session.bash("pytest", "5 passed", is_error=False)
        self.assertIs(False, self.only_check()["before_last_change"])

    def test_one_check_piped_differently_each_time_is_still_one_check(self) -> None:
        self.session.bash("node --test 2>&1 | tail -20", f"{CROSS} retries\nERR_ASSERTION")
        self.session.bash("node --test 2>&1 | tail -5", f"{INFO} pass 5\n{INFO} fail 0")
        self.session.bash("node --test 2>&1 | grep -E 'pass|fail'", f"{INFO} pass 5\n{INFO} fail 0")
        self.session.bash("node --test", "", is_error=False)
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["earlier_failed"])
        self.assertEqual("node --test", check["title"])

    def test_a_run_still_in_flight_has_no_result_yet(self) -> None:
        self.session.call("Bash", {"command": "pytest"})
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertIn("no result recorded yet", check["source"])

    def test_a_sidechain_record_inside_the_parents_own_file_is_not_read(self) -> None:
        # A subagent is read from its own transcript (test_subagent_checks);
        # none of 300 sampled parent transcripts holds a sidechain record.
        call_id = self.session.call("Bash", {"command": "pytest"}, sidechain=True)
        self.session.result(call_id, "", is_error=True)
        events, scan = self.read()
        self.assertEqual([], events)
        self.assertEqual(0, scan["shell_calls"])


class WhatAReaderSeesOfTheFilesASessionWrote(ClaudeChecksTestCase):
    def test_a_written_path_reads_relative_to_the_working_directory(self) -> None:
        self.session.write(self.file("src/retry.py"))
        self.session.edit(self.file("src/retry.py"))
        self.session.edit(self.file("tests/test_retry.py"))
        events, scan = self.read()
        self.assertEqual(
            ["src/retry.py", "tests/test_retry.py"], sorted(event["title"] for event in events)
        )
        self.assertEqual(2, scan["written_paths"])

    def test_a_path_outside_the_working_directory_is_counted_and_not_listed(self) -> None:
        self.session.write(str(self.root / "elsewhere" / "notes.md"))
        events, scan = self.read()
        self.assertEqual([], events)
        self.assertEqual(1, scan["outside_paths"])

    def enter(self, folder: str) -> str:
        """The agent ran `cd`: every later record carries the folder as its cwd,
        while the first record still names the folder the session began in."""
        moved = self.cwd / folder
        moved.mkdir(parents=True, exist_ok=True)
        self.session.cwd = str(moved)
        return str(moved)

    def test_a_write_after_a_cd_reads_relative_to_the_session_directory(self) -> None:
        self.session.bash("true", "", is_error=False)
        moved = self.enter("web/src")
        self.session.edit(self.file("web/src/Panel.tsx"))
        self.session.edit(str(Path(moved) / "Panel.test.tsx"))
        events, scan = self.read()
        self.assertEqual(
            ["web/src/Panel.test.tsx", "web/src/Panel.tsx"],
            sorted(event["title"] for event in events),
        )
        self.assertEqual(2, scan["written_paths"])
        self.assertEqual(0, scan["outside_paths"])

    def test_a_relative_write_after_a_cd_is_placed_where_the_tool_ran_it(self) -> None:
        self.enter("web/src")
        call_id = self.session.call("Edit", {"file_path": "Panel.tsx", "old_string": "a"})
        self.session.result(call_id, "updated")
        events, _scan = self.read()
        self.assertEqual(["web/src/Panel.tsx"], [event["title"] for event in events])

    def test_a_redirect_after_a_cd_reads_relative_to_the_session_directory(self) -> None:
        self.enter("web")
        self.session.bash("pytest > out.txt", "", is_error=False)
        events, scan = self.read()
        self.assertEqual(["web/out.txt"], [e["title"] for e in events if e["subject"] == "write"])
        self.assertEqual(0, scan["outside_paths"])

    def test_a_clipped_read_that_starts_after_the_cd_still_reads_from_the_head(self) -> None:
        # The scan reads newest-first, so its first record can already carry the moved cwd.
        self.session.bash("true", "x" * 4000, is_error=False)
        moved = self.enter("web/src")
        self.session.edit(str(Path(moved) / "Panel.tsx"))
        self.session.save(self.path)
        tail = sum(len(line) + 1 for line in self.path.read_bytes().splitlines()[-2:])
        events, scan = project_context.claude_tool_reports(
            self.config, str(self.path), SHORT, max_bytes=tail + 8
        )
        self.assertEqual(["web/src/Panel.tsx"], [event["title"] for event in events])
        self.assertEqual(0, scan["shell_calls"])

    def test_a_head_with_no_directory_falls_back_to_the_first_record_read(self) -> None:
        self.config = dataclasses.replace(self.config, claude_cwd_scan_lines=0)
        self.enter("web")
        self.session.edit(self.file("web/Panel.tsx"))
        events, _scan = self.read()
        self.assertEqual(["web/Panel.tsx"], [event["title"] for event in events])

    def test_a_write_outside_the_session_directory_after_a_cd_is_counted_not_listed(self) -> None:
        self.enter("web/src")
        self.session.write(str(self.root / "elsewhere" / "notes.md"))
        self.session.write("../../../../elsewhere.md")
        events, scan = self.read()
        self.assertEqual([], events)
        self.assertEqual(2, scan["outside_paths"])
        self.assertEqual(0, scan["written_paths"])

    def test_a_cd_above_the_session_directory_does_not_publish_a_parent_relative_path(self) -> None:
        self.session.cwd = str(self.root / "work")
        self.session.write(str(self.root / "work" / "other" / "x.py"))
        events, scan = self.read()
        self.assertEqual([], events)
        self.assertEqual(1, scan["outside_paths"])

    def test_a_reader_never_sees_what_a_file_said(self) -> None:
        self.session.write(self.file("src/retry.py"), content="WRITTEN_BODY_SENTINEL")
        self.session.edit(self.file("src/retry.py"), old="OLD_SENTINEL", new="NEW_SENTINEL")
        published = json.dumps(self.read())
        for sentinel in ("WRITTEN_BODY_SENTINEL", "OLD_SENTINEL", "NEW_SENTINEL", "updated"):
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel, published)

    def test_an_edit_the_harness_refused_wrote_nothing(self) -> None:
        call_id = self.session.call("Edit", {"file_path": self.file("a.py")})
        self.session.result(call_id, "File has not been read yet.", is_error=True)
        events, scan = self.read()
        self.assertEqual([], events)
        self.assertEqual(0, scan["written_paths"])


class WhatAReaderIsNeverShownOfACommandLine(ClaudeChecksTestCase):
    def test_a_key_across_the_line_clip_never_reaches_the_page(self) -> None:
        for lead in range(100, 125):
            with self.subTest(lead=lead):
                self.setUp()
                padding = "k" * max(0, lead - len("pytest --token="))
                self.session.bash(f"pytest --token={padding}{FAKE_KEY}", "", is_error=False)
                title = self.only_check()["title"]
                self.assertNotIn(FAKE_KEY[:20], title)
                self.assertNotIn("Q" * 12, title)

    def test_a_password_in_any_form_redaction_cannot_see_is_masked(self) -> None:
        value = "hunter2x"
        for command in (
            f"PGPASSWORD={value} pytest tests/db",
            f"pytest --password {value}",
            f"pytest --password={value}",
            f"pytest --dsn postgres://app:{value}@localhost/test",
        ):
            with self.subTest(command=command.split()[0]):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                published = json.dumps(self.read())
                self.assertNotIn(value, published)


class WhichChecksAReaderIsShownFirst(ClaudeChecksTestCase):
    def test_failures_are_kept_before_passes_and_the_rest_are_counted(self) -> None:
        for n in range(10):
            self.session.bash(f"pytest tests/test_pass_{n}.py", "1 passed", is_error=False)
        for n in range(3):
            self.session.bash(f"pytest tests/test_fail_{n}.py", "1 failed", is_error=True)
        self.session.write(self.file("src/a.py"))
        self.session.write(self.file("src/b.py"))
        events, scan = self.read()
        self.assertEqual(12, len(events))
        self.assertEqual(3, sum(event.get("result") == "failed" for event in events))
        self.assertEqual(0, sum(event["subject"] == "write" for event in events))
        self.assertEqual(3, scan["more"])
        self.assertEqual(12, scan["listed"])
        self.assertEqual(13, scan["distinct_checks"])
        self.assertEqual(2, scan["written_paths"])
        self.assertEqual(3, scan["failed"])
        self.assertEqual(10, scan["passed"])


class WhereTheChecksGoOnceCollected(ClaudeChecksTestCase):
    NOW = START.timestamp() + 3600

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def collect(self, harness: str = "claude") -> dict[str, Any]:
        self.session.save(self.path)
        state = build_runtime_state(self.config, started=self.NOW)
        rows = [
            {
                "project": "billing",
                "harness": harness,
                "sid": SHORT,
                "last_activity": self.NOW,
                "active": True,
            }
        ]
        return project_context.collect(
            self.config, state, rows, "billing", now=self.NOW, focus=(harness, SHORT)
        )

    def test_the_observed_record_shows_the_checks_and_writes_as_their_own_type(self) -> None:
        self.session.write(self.file("src/retry.py"))
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.bash("pytest", "5 passed", is_error=False)
        context = self.collect()
        facts = [f for f in context["semantic"]["facts"] if f.get("type") == "tool_report"]
        self.assertEqual({"check", "write"}, {fact["subject"] for fact in facts})
        check = next(fact for fact in facts if fact["subject"] == "check")
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["earlier_failed"])
        self.assertEqual({"harness": "claude", "sid": SHORT}, check["source_session"])
        scans = context["sources"]["work"]["tool_reports"]
        self.assertEqual([("claude", SHORT)], [(row["harness"], row["sid"]) for row in scans])
        self.assertEqual(2, scans[0]["check_runs"])
        self.assertEqual(2, context["sources"]["work"]["live"])

    def test_the_result_source_and_later_write_reach_the_published_fact(self) -> None:  # T2
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.write(self.file("src/retry.py"))
        self.session.bash("mypy src | tail -1", "Found 2 errors in 1 file", is_error=False)
        facts = [f for f in self.collect()["semantic"]["facts"] if f.get("subject") == "check"]
        found = {fact["summary"]: fact for fact in facts}
        self.assertEqual("flag", found["pytest"]["result_source"])
        self.assertIs(True, found["pytest"]["before_last_change"])
        self.assertEqual("summary", found["mypy src"]["result_source"])

    def test_a_reader_who_restarts_finds_none_of_them_in_session_history(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.write(self.file("src/retry.py"))
        self.collect()
        stored = Path(semantic_history.store_path(self.config))
        text = stored.read_text(encoding="utf-8") if stored.exists() else ""
        self.assertIn("Add retry with backoff", text)
        self.assertNotIn("tool_report", text)
        self.assertNotIn("src/retry.py", text)

    def test_the_history_source_never_reads_the_checks_at_all(self) -> None:
        # The first wall. `semantic_history._FACT_EVENT_TYPES` is the second,
        # and with it alone the store test above would stay green.
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.write(self.file("src/retry.py"))
        self.session.save(self.path)
        events = project_context._semantic_history_source_events(
            self.config, str(self.path), "claude", SHORT, since=0.0, max_bytes=1 << 20
        )
        self.assertTrue(events)
        self.assertEqual(set(), {e["kind"] for e in events} & {"check_run", "path_written"})

    def test_a_session_on_another_harness_gains_nothing(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            context = self.collect(harness="pi")
        self.assertEqual([], context["sources"]["work"]["tool_reports"])
        self.assertFalse(
            [f for f in context["semantic"]["facts"] if f.get("type") == "tool_report"]
        )


class WhatAReadingMayCarryOfACheckAtThePress(WhereTheChecksGoOnceCollected):
    """Owner ruling on DRC-4677, Q1: the model sees each check's redacted
    output tail. It is read again at the press, keyed by the call, and never
    put on the published fact, so the page and history never hold it."""

    def test_each_latest_check_run_carries_its_redacted_tail_keyed_by_its_call(self) -> None:
        self.session.bash("pytest", "1 failed", is_error=True)
        last = self.session.bash(
            "pytest", "x" * 400 + f" token={FAKE_KEY} 5 passed", is_error=False
        )
        self.session.write(self.file("src/retry.py"))
        self.session.save(self.path)
        tails = project_context.claude_check_tails(self.config, str(self.path))
        self.assertEqual([last], list(tails))
        self.assertLessEqual(len(tails[last]), project_context.TOOL_REPORT_TAIL_CHARS)
        self.assertTrue(tails[last].endswith("5 passed"))
        self.assertNotIn(FAKE_KEY, tails[last])

    def test_the_tail_joins_the_published_fact_by_its_record_id(self) -> None:
        call = self.session.bash("pytest", "5 passed", is_error=False)
        facts = [f for f in self.collect()["semantic"]["facts"] if f.get("subject") == "check"]
        self.assertEqual([call], [fact["branch"]["record_id"] for fact in facts])
        self.assertIn(call, project_context.claude_check_tails(self.config, str(self.path)))

    def test_the_output_never_reaches_the_published_record(self) -> None:
        self.session.bash("pytest", "UNIQUE_OUTPUT_MARKER 5 passed", is_error=False)
        self.assertNotIn("UNIQUE_OUTPUT_MARKER", json.dumps(self.collect()))

    def test_a_background_run_has_no_tail_to_carry(self) -> None:
        self.session.bash(
            "pytest", "Command running in background with ID: b1", run_in_background=True
        )
        self.session.save(self.path)
        self.assertEqual({}, project_context.claude_check_tails(self.config, str(self.path)))


class WhichPassesALaterCommandMayHaveChanged(ClaudeChecksTestCase):
    """K3 of the DRC-4677 review: a pass followed by a command that may change
    files, later in the same call or in a later call, is read at the press as
    changed after, in command order. Layer 1's published fact is unchanged."""

    def changed(self) -> frozenset[tuple[str, str]]:
        self.session.save(self.path)
        return project_context.claude_check_press(self.config, str(self.path)).changed_after

    def test_a_touch_after_the_pass_in_the_same_call_changes_it(self) -> None:
        call = self.session.bash("pytest && touch changed.py", "5 passed", is_error=False)
        self.assertEqual(frozenset({(call, "pytest")}), self.changed())

    def test_a_touch_in_a_later_call_changes_it(self) -> None:
        call = self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("touch changed.py", "", is_error=False)
        self.assertEqual(frozenset({(call, "pytest")}), self.changed())

    def test_a_command_before_the_pass_or_a_read_after_it_does_not(self) -> None:
        self.session.bash("touch changed.py && pytest", "5 passed", is_error=False)
        self.session.bash("git status", "clean", is_error=False)
        self.assertEqual(frozenset(), self.changed())

    def test_a_call_that_never_ran_changes_nothing(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        call = self.session.call("Bash", {"command": "touch changed.py"})
        self.session.result(call, "The user rejected this tool use", is_error=True)
        self.assertEqual(frozenset(), self.changed())

    def test_the_press_carries_the_tails_it_always_did(self) -> None:
        call = self.session.bash("pytest", "5 passed", is_error=False)
        self.session.save(self.path)
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual({call: "5 passed"}, press.tails)


def results_by_title(events: list[dict[str, Any]]) -> dict[str, str]:
    return {e["title"]: e["result"] for e in events if e["subject"] == "check"}


class WhichCheckAShellCallsResultBelongsTo(ClaudeChecksTestCase):
    """The correction round's R1 to R5: the flag is the whole call's status.

    Every rule here moves a check toward "ran, result not recorded" or toward
    a failure, never toward a pass.
    """

    def test_every_check_in_a_call_is_its_own_run(self) -> None:  # R1, T8
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash(
            "pytest; ruff check .", "1 failed, 4 passed in 1s\nAll checks passed!", is_error=False
        )
        events, scan = self.read()
        found = results_by_title(events)
        self.assertEqual({"pytest", "ruff check ."}, set(found))
        self.assertNotEqual("passed", found["pytest"])
        # Ruff's own last line speaks for ruff, the last check; pytest's failure text above it does not.
        self.assertEqual("passed", found["ruff check ."])
        self.assertEqual(3, scan["check_runs"])

    def test_a_passing_flag_through_and_alone_passes_every_check(self) -> None:  # R2, T1, T8
        self.session.bash("pytest && mypy src && echo ok", "", is_error=False)
        self.assertEqual(
            {"pytest": "passed", "mypy src": "passed"}, results_by_title(self.read()[0])
        )

    def test_a_failing_flag_is_not_given_to_any_check_of_a_longer_call(self) -> None:  # R2, V6
        # V6 narrowed R2: any stage of a longer call may be the one that failed.
        for command, expected in (
            ("pytest && mypy src", {"pytest": "not-recorded", "mypy src": "not-recorded"}),
            ("pytest && false", {"pytest": "not-recorded"}),
            ("ruff check . && pytest", {"ruff check .": "not-recorded", "pytest": "not-recorded"}),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=True)
                self.assertEqual(expected, results_by_title(self.read()[0]))

    def test_the_flag_says_nothing_after_a_later_semicolon_or_pipe(self) -> None:  # R2, T1
        for command in (
            "pytest && echo x; true",
            "pytest && echo x | cat",
            "pytest; mypy src; true",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                for title, result in results_by_title(self.read()[0]).items():
                    self.assertEqual("not-recorded", result, title)

    def test_a_check_after_or_may_not_have_run(self) -> None:  # R2
        for command in ("pytest || mypy src", "make lint || pytest"):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "5 passed", is_error=False)
                for title, result in results_by_title(self.read()[0]).items():
                    self.assertEqual("not-recorded", result, title)

    def test_output_belongs_to_a_check_only_when_the_call_holds_one(self) -> None:  # R3
        # mypy is the last check and its own runner's summary is the last line, so it speaks for
        # mypy alone; pytest, which is not last, stays unrecorded.
        self.session.bash(
            "pytest -q; mypy src | tail -1", "Found 2 errors in 1 file", is_error=False
        )
        self.assertEqual(
            {"pytest -q": "not-recorded", "mypy src": "failed"},
            results_by_title(self.read()[0]),
        )

    def test_a_server_sent_to_the_background_leaves_the_check_after_it_in_front(self) -> None:  # R4
        # The foreground check is a run that supersedes the earlier pass; V6
        # and V8 keep a two-segment call's failure and output unattributed.
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("python3 -m http.server 8000 & pytest", "1 failed", is_error=True)
        _events, scan = self.read()
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertNotIn("background", check["source"])
        self.assertEqual(1, scan["background"])
        self.setUp()
        self.session.bash("python3 -m http.server 8000 & pytest", "", is_error=False)
        self.assertEqual("passed", self.only_check()["result"])

    def test_a_background_rerun_leaves_the_check_without_a_recorded_result(self) -> None:  # R5
        self.session.bash("pytest", "5 passed", is_error=False)
        call_id = self.session.call("Bash", {"command": "pytest", "run_in_background": True})
        self.session.result(call_id, "Command running in background with ID: b3.", is_error=False)
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertIn("background", check["source"])


class WhatAResultMayRestOn(ClaudeChecksTestCase):
    """R6 to R8, and the negative directions of item 4's two notes (T4)."""

    def test_failure_in_the_output_outranks_a_passing_flag(self) -> None:  # R6
        for command, output, source in (
            ("npm test", "Tests: 1 failed, 4 passed, 5 total", "summary"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                check = self.only_check()
                self.assertEqual(("failed", source), (check["result"], check["result_source"]))
        # V4: a failure marker alone beside a passing flag only withholds it.
        self.setUp()
        self.session.bash("./run_tests.sh", "FAILED tests/test_a.py::test_x - AssertionError")
        self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_node_run_with_a_cancelled_test_failed(self) -> None:  # R7
        output = f"{INFO} tests 1\n{INFO} pass 1\n{INFO} fail 0\n{INFO} cancelled 1"
        # A marker records the failure where the flag cannot be read; beside a
        # passing flag it withholds the pass (V4).
        for command, expected in (
            ("node --test 2>&1 | grep pass", "failed"),
            ("node --test", "not-recorded"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                self.assertEqual(expected, self.only_check()["result"])

    def test_a_go_run_with_no_test_files_ran_nothing(self) -> None:  # R8
        self.session.bash("go test ./...", "?   \texample.com/a\t[no test files]", is_error=False)
        self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_lone_failure_does_not_claim_an_earlier_one(self) -> None:  # T4
        self.session.bash("pytest", "1 failed", is_error=True)
        self.assertIs(False, self.only_check()["earlier_failed"])

    def test_a_failure_before_a_write_is_marked_before_the_last_change(self) -> None:  # T4
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.edit(self.file("src/retry.py"))
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_the_result_is_read_from_the_last_180_characters_only(self) -> None:  # T11
        # Item 5's window: a failure scrolled out of the tail is not read.
        output = "3 failed, 2 passed\n" + "." * 300 + "\nAll checks passed!"
        self.session.bash("ruff check . | tail -1", output, is_error=False)
        check = self.only_check()
        self.assertEqual(("passed", "summary"), (check["result"], check["result_source"]))

    def test_go_fail_and_tsc_errors_are_failures(self) -> None:  # T7
        for command, output, source in (
            ("go test ./... | tail -2", "FAIL\texample.com/retry\t0.2s", "summary"),
            ("tsc --noEmit | tail -1", "src/a.ts(3,1): error TS2322: bad type", "marker"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                check = self.only_check()
                self.assertEqual(("failed", source), (check["result"], check["result_source"]))


class WhatCountsAsAWrite(ClaudeChecksTestCase):
    """R9 to R11."""

    def test_a_write_with_no_result_yet_is_an_attempt_and_ages_nothing(self) -> None:  # R9
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.call("Write", {"file_path": self.file("a.py"), "content": "x"})
        call_id = self.session.call("Edit", {"file_path": self.file("b.py")})
        self.session.result(call_id, "String not found", is_error=True)
        events, scan = self.read()
        self.assertEqual([], [e for e in events if e["subject"] == "write"])
        self.assertEqual(0, scan["written_paths"])
        self.assertEqual(2, scan["write_attempts"])
        self.assertIs(False, self.only_check()["before_last_change"])

    def test_a_write_outside_the_working_directory_still_ages_a_pass(self) -> None:  # R10
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.write(str(self.root / "shared" / "lib.py"))
        _events, scan = self.read()
        self.assertEqual(1, scan["outside_paths"])
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_notebook_and_multi_edits_are_writes(self) -> None:  # R11
        self.session.bash("pytest", "5 passed", is_error=False)
        call_id = self.session.call("MultiEdit", {"file_path": self.file("a.py"), "edits": []})
        self.session.result(call_id, "Applied 2 edits")
        call_id = self.session.call("NotebookEdit", {"notebook_path": self.file("n.ipynb")})
        self.session.result(call_id, "Updated cell")
        events, _scan = self.read()
        writes = sorted(e["title"] for e in events if e["subject"] == "write")
        self.assertEqual(["a.py", "n.ipynb"], writes)
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_a_lint_fix_is_a_check_and_a_change(self) -> None:  # R11
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("ruff check --fix .", "All checks passed!", is_error=False)
        events, scan = self.read()
        found = {e["title"]: e for e in events if e["subject"] == "check"}
        self.assertIs(True, found["pytest"]["before_last_change"])
        self.assertIs(True, found["ruff check --fix ."]["before_last_change"])
        self.assertIsNotNone(scan["last_changing_command_at"])


class WhichFormsAreStripped(ClaudeChecksTestCase):
    """R12 to R15."""

    def test_an_rtk_check_reads_its_result_from_the_flag_alone(self) -> None:  # R12
        for command, output, flag, expected in (
            ("rtk pytest", "", True, "failed"),
            ("rtk pytest 2>&1 | tail -2", "5 passed", False, "not-recorded"),
            ("rtk pytest", "1 failed", False, "not-recorded"),
        ):
            with self.subTest(command=command, output=output):
                self.setUp()
                self.session.bash(command, output, is_error=flag)
                check = self.only_check()
                self.assertTrue(check["title"].startswith("pytest"))
                self.assertEqual(expected, check["result"])

    def test_rtk_proxy_reads_the_runners_own_output(self) -> None:
        # `rtk proxy` is RTK's unfiltered mode, so its output is the runner's own.
        for output, flag, expected in (
            ("14 passed in 1.0s", False, "passed"),
            ("1 failed, 3 passed", False, "failed"),
            ("1 failed, 3 passed", True, "failed"),
            ("14 passed in 1.0s", True, "failed"),  # the error flag still fails it
        ):
            with self.subTest(output=output, flag=flag):
                self.setUp()
                self.session.bash("rtk proxy python -m pytest -q", output, is_error=flag)
                check = self.only_check()
                self.assertEqual("python -m pytest -q", check["title"])
                self.assertEqual(expected, check["result"])

    def test_rtk_bypass_reads_the_runners_own_output(self) -> None:
        # rtk 1.1.0 renamed `rtk proxy` to `rtk bypass`; it behaves identically.
        for output, flag, expected in (
            ("14 passed in 1.0s", False, "passed"),
            ("1 failed, 3 passed", False, "failed"),
            ("14 passed in 1.0s", True, "failed"),
        ):
            with self.subTest(output=output, flag=flag):
                self.setUp()
                self.session.bash("rtk bypass python -m pytest -q", output, is_error=flag)
                check = self.only_check()
                self.assertEqual("python -m pytest -q", check["title"])
                self.assertEqual(expected, check["result"])

    def test_a_hook_rewritten_rtk_bypass_reads_the_same_way(self) -> None:
        call_id = self.session.call("Bash", {"command": "python -m pytest -q"})
        self.session.hook_rewrite(call_id, hook_stdout("rtk bypass python -m pytest -q"))
        self.session.result(call_id, "14 passed in 1.0s", is_error=False)
        self.assertEqual("passed", self.only_check()["result"])

    def test_a_command_a_hook_rewrote_is_the_command_that_ran(self) -> None:  # R12
        """The agent typed `pytest`; the hook ran `rtk pytest`, whose output no rule may read."""
        call_id = self.session.call("Bash", {"command": "pytest"})
        self.session.hook_rewrite(call_id, hook_stdout("rtk pytest"))
        self.session.result(call_id, "1 failed", is_error=False)
        check = self.only_check()
        self.assertTrue(check["title"].startswith("pytest"))
        self.assertEqual("not-recorded", check["result"])

    def test_a_rewritten_check_reads_its_result_from_the_flag_alone(self) -> None:  # R12
        """Typed `ruff check x` ran as `rtk ruff check x`: failure text with no flag is withheld."""
        call_id = self.session.call("Bash", {"command": "ruff check x"})
        self.session.hook_rewrite(call_id, hook_stdout("rtk ruff check x"))
        self.session.result(call_id, "x.py:1 1 failed", is_error=False)
        self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_rewritten_check_with_a_failing_flag_fails_on_the_flag(self) -> None:  # R12
        call_id = self.session.call("Bash", {"command": "ruff check x"})
        self.session.hook_rewrite(call_id, hook_stdout("rtk ruff check x"))
        self.session.result(call_id, "Exit code 1\nRuff: 2 issues", is_error=True)
        self.assertEqual("failed", self.only_check()["result"])

    def test_rtk_lint_is_the_eslint_check(self) -> None:  # R12
        """rtk prints `rtk lint .` for `npx eslint .`; the check and its read-only status survive."""
        call_id = self.session.call("Bash", {"command": "npx eslint ."})
        self.session.hook_rewrite(call_id, hook_stdout("rtk lint ."))
        self.session.result(call_id, "", is_error=False)
        events, scan = self.read()
        checks = [e for e in events if e["subject"] == "check"]
        self.assertEqual(1, len(checks), checks)
        self.assertTrue(checks[0]["title"].startswith(("eslint", "lint")))
        self.assertEqual("passed", checks[0]["result"])
        self.assertIsNone(scan["last_changing_command_at"])

    def test_rtk_lint_with_fix_is_a_check_and_a_change(self) -> None:  # R12
        call_id = self.session.call("Bash", {"command": "eslint . --fix"})
        self.session.hook_rewrite(call_id, hook_stdout("rtk lint . --fix"))
        self.session.result(call_id, "", is_error=False)
        events, scan = self.read()
        self.assertEqual(1, len([e for e in events if e["subject"] == "check"]))
        self.assertIsNotNone(scan["last_changing_command_at"])

    def test_lint_alone_is_not_a_runner(self) -> None:  # R12
        self.session.bash("lint .", "", is_error=False)
        self.assertEqual([], self.checks())

    def test_a_rewrite_that_does_not_read_as_a_command_leaves_the_typed_one(self) -> None:  # R12
        for stdout in (
            "{not json",
            "[]",
            json.dumps({"hookSpecificOutput": {"updatedInput": "rtk pytest"}}),
            json.dumps({"hookSpecificOutput": {"updatedInput": {"command": ["rtk", "pytest"]}}}),
            json.dumps({"hookSpecificOutput": {"updatedInput": {"command": ""}}}),
            json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}),
            hook_stdout("rtk pytest " + "x" * 70000),
        ):
            with self.subTest(stdout=stdout[:60]):
                self.setUp()
                call_id = self.session.call("Bash", {"command": "pytest"})
                self.session.hook_rewrite(call_id, stdout)
                self.session.result(call_id, "1 failed", is_error=False)
                self.assertEqual("failed", self.only_check()["result"])

    def test_only_a_pre_tool_use_bash_hook_rewrites_a_command(self) -> None:  # R12
        for hook in ("PreToolUse:Edit", "PostToolUse:Bash", "PreToolUse"):
            with self.subTest(hook=hook):
                self.setUp()
                call_id = self.session.call("Bash", {"command": "pytest"})
                self.session.hook_rewrite(call_id, hook_stdout("rtk pytest"), hook=hook)
                self.session.result(call_id, "1 failed", is_error=False)
                self.assertEqual("failed", self.only_check()["result"])

    def test_a_subagent_transcripts_rewrite_is_read_the_same_way(self) -> None:  # R12
        self.session.bash("true", "", is_error=False)
        child = Transcript(self.root)
        child.calls = 10  # call ids are shared across streams, so the child's must not repeat
        call_id = child.call("Bash", {"command": "pytest"}, sidechain=True)
        child.hook_rewrite(call_id, hook_stdout("rtk pytest"), sidechain=True)
        child.result(call_id, "1 failed", is_error=False)
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_rewrite_of_another_call_does_not_reach_this_one(self) -> None:  # R12
        other = self.session.call("Bash", {"command": "ls"})
        self.session.hook_rewrite(other, hook_stdout("rtk ls"))
        self.session.result(other, "a", is_error=False)
        call_id = self.session.bash("pytest", "1 failed", is_error=False)
        self.assertTrue(call_id)
        self.assertEqual("failed", self.only_check()["result"])

    def test_a_pytest_plugin_flag_is_shown_and_a_bare_word_stays_masked(self) -> None:
        for command, title in (
            ("pytest -p no:cacheprovider -q", "pytest -p no:cacheprovider -q"),
            ("uv run pytest -p no:randomly", "pytest -p no:randomly"),
            ("python3 -m pytest tests/x.py -q -pno:cacheprovider", None),
            ("pytest -p myplugin", "pytest -p \u2026REDACTED"),
            ("py.test -p no:randomly", "py.test -p no:randomly"),
            ("pytest -P no:x", "pytest -P \u2026REDACTED"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                shown = self.only_check()["title"]
                if title is None:
                    self.assertIn("-pno:cacheprovider", shown)
                else:
                    self.assertEqual(title, shown)

    def test_paths_options_and_subshells_are_stripped(self) -> None:  # R13
        for command, title in (
            (".venv/bin/python -m pytest -q", ".venv/bin/python -m pytest -q"),
            ("uv run --with pytest-cov pytest -q", "pytest -q"),
            ("(cd api && pytest)", "pytest"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(title, self.only_check()["title"])

    def test_a_heredoc_body_is_not_a_command(self) -> None:  # R13
        self.session.bash("cat > run.sh <<'EOF'\npytest\nEOF", "", is_error=False)
        self.assertEqual([], self.checks())

    def test_the_same_runner_in_two_directories_is_two_checks(self) -> None:  # R14
        self.session.bash("cd frontend && npm test", "", is_error=True)
        self.session.bash("cd backend && npm test", "", is_error=False)
        events = self.read()[0]
        results = sorted(e["result"] for e in events if e["subject"] == "check")
        self.assertEqual(["failed", "passed"], results)

    def test_a_find_with_an_or_is_still_read_only(self) -> None:  # R15
        self.session.bash("find . -name '*.py' -o -name '*.js' | head", "", is_error=False)
        scan = self.read()[1]
        self.assertEqual(1, scan["read_only_commands"])
        self.assertIsNone(scan["last_changing_command_at"])

    def test_substitution_redirects_and_tree_output_are_not_read_only(self) -> None:  # R15
        for command in (
            "echo $(rm -rf build)",
            "echo `touch x`",
            "tree -o out.txt",
            "ls > f.txt",
            "find . -fprint0 list.txt",
            "find . -fprintf list.txt %p",
            "git show --output=x.patch",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                scan = self.read()[1]
                self.assertEqual(0, scan["read_only_commands"])
                self.assertIsNotNone(scan["last_changing_command_at"])


class WhichFilesAShellCallRemoved(ClaudeChecksTestCase):
    """Deletions and moves, read for the press alone: the record the goal verdict is tested against."""

    def removals(self) -> tuple[tuple[str, float, str], ...]:
        self.session.save(self.path)
        return project_context.claude_check_press(self.config, str(self.path)).removals

    def test_rm_records_the_file_it_deleted(self) -> None:
        self.session.bash(
            "ls docs/e2e && rm docs/e2e/notes.md && rmdir docs/e2e", "", is_error=False
        )
        found = self.removals()
        self.assertEqual(
            [("docs/e2e", "deleted"), ("docs/e2e/notes.md", "deleted")],
            sorted((p, k) for p, _at, k in found),
        )
        self.assertGreater(found[0][1], 0)

    def test_a_call_that_errored_after_the_rm_still_records_it(self) -> None:
        # The last command (`ls` of the removed folder) set the exit status, not the rm.
        self.session.bash(
            "rm docs/e2e/notes.md && ls docs/e2e", "ls: docs/e2e: No such file", is_error=True
        )
        self.assertEqual(["docs/e2e/notes.md"], [p for p, _at, _k in self.removals()])

    def test_an_rm_that_reported_its_own_failure_is_no_removal(self) -> None:
        self.session.bash(
            "rm docs/notes.md", "rm: docs/notes.md: Operation not permitted", is_error=True
        )
        self.assertEqual((), self.removals())

    def test_mv_records_its_source_as_moved_and_not_its_destination(self) -> None:
        self.session.bash("mv docs/notes.md docs/old/notes.md", "", is_error=False)
        self.assertEqual([("docs/notes.md", "moved")], [(p, k) for p, _at, k in self.removals()])

    def test_unlink_counts_and_flags_are_not_files(self) -> None:
        self.session.bash("unlink b.md && rm -rf -- c.md", "", is_error=False)
        self.assertEqual(
            [("b.md", "deleted"), ("c.md", "deleted")],
            sorted((p, k) for p, _at, k in self.removals()),
        )

    def test_a_target_outside_the_session_or_a_glob_is_not_published(self) -> None:
        self.session.bash("rm /etc/hosts ../elsewhere.md docs/*.md", "", is_error=False)
        self.assertEqual((), self.removals())

    def test_a_read_only_command_removes_nothing(self) -> None:
        self.session.bash("cat docs/notes.md && ls docs", "", is_error=False)
        self.assertEqual((), self.removals())


class WhichOrderTheEntriesAreKeptIn(ClaudeChecksTestCase):
    def left_out(self, events: list[dict[str, Any]]) -> tuple[float, ...]:
        """What the reading counts as not carried, when the prompt carried every listed event."""
        self.session.save(self.path)
        press = project_context.claude_check_press(self.config, str(self.path))
        facts = [
            {"fact_id": f"f{i}", "summary": e["title"], "branch": {"record_id": e["record_id"]}}
            for i, e in enumerate(events)
        ]
        carried = cast("list[reading.LedgerEntry]", [{"id": f["fact_id"]} for f in facts])
        output = reading.ToolOutput(
            destination="d", label="l", passes_and_writes=press.passes_and_writes
        )
        return reading._left_out(output, facts, carried, 0.0)

    def test_a_sibling_pass_in_a_listed_call_is_not_read_as_carried(self) -> None:
        # Verification 2: one call, two passing checks, one record id; one is listed.
        self.session.bash("ruff check . && mypy", "ok", is_error=False)
        for n in range(11):
            self.session.bash(f"pytest tests/f{n}.py", "1 failed", is_error=True)
        events, scan = self.read()
        self.assertEqual(1, scan["more"])
        self.assertEqual(1, len(self.left_out(events)))

    def test_a_shell_calls_write_is_not_read_as_carried_with_its_check(self) -> None:
        # The check is listed and its own redirect's write, under the same record id, is not.
        self.session.bash("pytest > out.txt", "", is_error=False)
        for n in range(11):
            self.session.bash(f"pytest tests/f{n}.py", "1 failed", is_error=True)
        events, scan = self.read()
        self.assertEqual(1, scan["more"])
        listed = [e for e in events if e["subject"] == "check" and e.get("result") == "passed"]
        self.assertEqual(1, len(listed))
        self.session.save(self.path)
        press = project_context.claude_check_press(self.config, str(self.path))
        write = [p for p in press.passes_and_writes if p[0] == listed[0]["record_id"]]
        self.assertEqual(2, len(write))
        self.assertEqual(1, len(self.left_out(events)))

    def test_item_four_keeps_failures_then_passes_then_unrecorded(self) -> None:  # T5
        # DEC-23 item 4 as amended on 2026-10-04.
        for n in range(3):
            self.session.bash(f"pytest tests/f{n}.py", "1 failed", is_error=True)
        for n in range(8):
            self.session.bash(f"pytest tests/p{n}.py", "1 passed", is_error=False)
        for n in range(4):
            self.session.bash(f"pytest tests/u{n}.py | tail -1", "....", is_error=False)
        events, scan = self.read()
        titles = [e["title"] for e in events]
        self.assertEqual(12, len(events))
        self.assertEqual(
            ["pytest tests/f2.py", "pytest tests/f1.py", "pytest tests/f0.py"], titles[:3]
        )
        self.assertEqual([f"pytest tests/p{n}.py" for n in range(7, -1, -1)], titles[3:11])
        self.assertEqual(["pytest tests/u3.py"], titles[11:])
        self.assertEqual(3, scan["more"])

    def test_runs_with_no_recorded_result_never_hide_a_pass_or_a_write(self) -> None:
        self.session.bash("pytest tests/p.py", "1 passed", is_error=False)
        self.session.write(self.file("app.py"))
        for n in range(14):
            self.session.bash(f"pytest tests/u{n}.py | tail -1", "....", is_error=False)
        events, scan = self.read()
        kept = [(e["subject"], e.get("result")) for e in events]
        self.assertEqual(("check", "passed"), kept[0])
        self.assertEqual(("write", None), kept[1])
        self.assertEqual(10, sum(1 for e in events if e.get("result") == "not-recorded"))
        self.assertEqual(4, scan["more"])
        # Nothing the press counts as left out: the cap only dropped runs with no result.
        self.assertEqual((), self.left_out(events))

    def test_a_run_with_no_result_after_a_failure_is_kept_with_the_failures(self) -> None:
        # Review C1: its only recorded result is the failure, so writes never push it out.
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.bash("pytest 2>&1 | tail -3", "....", is_error=False)
        for n in range(12):
            self.session.write(self.file(f"m{n}.py"))
        events, scan = self.read()
        checks = [e for e in events if e["subject"] == "check"]
        self.assertEqual(1, len(checks), scan)
        self.assertEqual(("not-recorded", True), (checks[0]["result"], checks[0]["earlier_failed"]))
        self.assertEqual(1, scan["more"])

    def test_the_press_knows_when_each_left_out_pass_or_write_arrived(self) -> None:
        for n in range(13):
            self.session.bash(f"pytest tests/p{n}.py", "1 passed", is_error=False)
        self.session.write(self.file("app.py"))
        self.session.bash("pytest tests/u.py | tail -1", "....", is_error=False)
        events, scan = self.read()
        self.assertEqual(3, scan["more"])
        unlisted = self.left_out(events)
        # The oldest pass and the write are past the cap; the unrecorded run is not counted.
        self.assertEqual(2, len(unlisted))
        listed = sorted(float(e.get("result_at") or e["at"]) for e in events)
        self.assertTrue(all(at not in listed for at in unlisted))


class WhatAReaderIsNeverShownOfACommandLineEither(ClaudeChecksTestCase):
    """R19 to R21 and T10."""

    VALUE = "zzsecvalue9"

    def published(self, command: str) -> str:
        self.setUp()
        self.session.bash(command, "", is_error=False)
        return json.dumps(self.read())

    def test_a_masked_form_inside_quotes_is_still_masked(self) -> None:  # R19
        for command in (
            f'pytest "--password={self.VALUE} two"',
            f'pytest --env "TOKEN={self.VALUE} two"',
            f'pytest "-p{self.VALUE} two"',
        ):
            with self.subTest(command=command.split()[1][:8]):
                published = self.published(command)
                self.assertNotIn(self.VALUE, published)
                self.assertNotIn("two", published)

    def test_other_credential_flags_and_headers_are_masked(self) -> None:  # R20
        for command in (
            f"pytest --token {self.VALUE}",
            f"pytest --token={self.VALUE}",
            f"pytest --api-key {self.VALUE}",
            f"pytest --secret={self.VALUE}",
            f"pytest --auth {self.VALUE}",
            f"mypy -P {self.VALUE}",
            f'pytest -H "Authorization: Bearer {self.VALUE}"',
            f'pytest -H "X-Api-Key: {self.VALUE}"',
            f"pytest --db app:{self.VALUE}/x@localhost",
            f"pytest --db app:{self.VALUE}@x@localhost",
        ):
            with self.subTest(n=command.split()[1]):
                self.assertNotIn(self.VALUE, self.published(command))

    def test_a_non_leading_password_assignment_is_masked(self) -> None:  # T10
        published = self.published(f"pytest --env PGPASSWORD={self.VALUE} tests/db")
        self.assertNotIn(self.VALUE, published)
        self.assertIn("PGPASSWORD=", published)

    def test_substituted_commands_and_comments_are_not_published(self) -> None:  # R21
        for command, title in (
            (f"pytest $(curl -u user:{self.VALUE} http://x)", "pytest $(…)"),
            (f"pytest `cat {self.VALUE}.txt`", "pytest $(…)"),
            (f"pytest -q # {self.VALUE}", "pytest -q"),
        ):
            with self.subTest(title=title):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(title, self.only_check()["title"])


class TheClosedListIsTheDocumentsList(ClaudeChecksTestCase):
    """T7: every runner the ruling names, parsed from the ruling, is a check."""

    DOC = Path(__file__).resolve().parents[4] / "docs" / "design-reading-a-session.md"

    def runners(self) -> list[str]:
        text = self.DOC.read_text(encoding="utf-8")
        section = text.split("### The closed lists", 1)[1].split("Read-only commands", 1)[0]
        body = section.split("Runners, matched", 1)[1]
        names = re.findall(r"`([^`]+)`", body)
        skip = {
            "test",
            "tests",
            "[",
            "_",
            "-",
            ".",
            "runtests.py",
            "fetch_latest_creds.py",
            "--noEmit",
        }
        return [name for name in names if name not in skip]

    def test_every_runner_the_ruling_names_is_a_check(self) -> None:
        runners = self.runners()
        self.assertGreater(len(runners), 60)
        for runner in runners:
            with self.subTest(runner=runner):
                words = project_context._strip_runner_prefix(runner.split())
                self.assertTrue(project_context._is_check(words), runner)

    def closed_lists(self) -> str:
        text = self.DOC.read_text(encoding="utf-8")
        return text.split("### The closed lists", 1)[1].split("Runners, matched", 1)[0]

    def wrappers(self) -> list[str]:
        """The wrappers the ruling's stripping sentence names, parsed from it."""
        sentence = self.closed_lists().split("and the wrappers", 1)[1].split("The list is", 1)[0]
        return re.findall(r"`([^`]+)`", sentence)

    def shell_wrappers(self) -> list[str]:
        sentence = self.closed_lists().split("The shell wrappers are", 1)[1].split(":", 1)[0]
        return re.findall(r"`([^`]+)`", sentence)

    def test_every_wrapper_the_ruling_names_is_stripped(self) -> None:
        wrappers = self.wrappers()
        self.assertGreaterEqual(len(wrappers), 10, wrappers)
        self.assertIn("env NAME=value", wrappers)
        for wrapper in [*wrappers, "rtk proxy"]:
            with self.subTest(wrapper=wrapper):
                words = [*re.sub(r"\bN\b", "60", wrapper).split(), "pytest", "-q"]
                self.assertEqual(["pytest", "-q"], project_context._strip_runner_prefix(words))

    def shell_options(self) -> tuple[list[str], list[str]]:
        """The closed option set, parsed from amendment item 3: its letters and
        its long options."""
        text = self.DOC.read_text(encoding="utf-8")
        amendment = text.split("### Amended 2026-09-25", 1)[1]
        sentence = amendment.split("The option set is closed:", 1)[1].split(", with", 1)[0]
        named = re.findall(r"`([^`]+)`", sentence)
        return [n for n in named if len(n) == 1], [n for n in named if n.startswith("-")]

    def test_every_shell_option_the_ruling_names_is_accepted_and_no_other(self) -> None:
        letters, longs = self.shell_options()
        self.assertIn("c", letters)
        self.assertNotIn("x", letters)
        self.assertIn("--login", longs)
        accepted = [f"bash -{letter}c" for letter in letters if letter != "c"]
        accepted += [f"bash {option} -c" for option in longs]
        for wrapper in accepted:
            with self.subTest(wrapper=wrapper):
                self.setUp()
                self.session.bash(f"{wrapper} 'pytest -q'", "", is_error=False)
                self.assertEqual("pytest -q", self.only_check()["title"])
        for letter in sorted(set("abefhikmnprstuvxBCEHPT") - set(letters)):
            with self.subTest(refused=letter):
                self.setUp()
                self.session.bash(f"bash -{letter}c 'pytest -q'", "", is_error=False)
                self.assertEqual([], self.checks())

    def test_every_shell_wrapper_the_ruling_names_stands_for_its_inner_line(self) -> None:
        shells = self.shell_wrappers()
        self.assertEqual(4, len(shells), shells)
        for shell in shells:
            with self.subTest(shell=shell):
                self.setUp()
                self.session.bash(f"{shell} 'cd sub && pytest -q'", "", is_error=False)
                self.assertEqual("pytest -q", self.only_check()["title"])


class WhatTheVerifierFoundAfterTheFirstRound(ClaudeChecksTestCase):
    """The second correction round, V1 to V8. Every rule withholds."""

    def test_a_call_claude_code_moved_to_the_background_has_no_result(self) -> None:  # V1
        for text in (
            (
                "Command did not complete within its 120s timeout and was moved to the"
                " background with ID: b9."
            ),
            "Command running in background with ID: b9.",
        ):
            with self.subTest(text=text[:20]):
                self.setUp()
                self.session.bash("pytest", "1 failed", is_error=True)
                self.session.bash("pytest", text, is_error=False)
                _events, scan = self.read()
                check = self.only_check()
                self.assertEqual("not-recorded", check["result"])
                self.assertIs(True, check["earlier_failed"])
                self.assertEqual(1, scan["background"])

    def test_an_ampersand_backgrounds_the_whole_chain_before_it(self) -> None:  # V2
        self.session.bash("pytest", "1 failed", is_error=True)
        self.session.bash("pytest && echo started &", "", is_error=False)
        self.assertEqual("not-recorded", self.only_check()["result"])
        self.setUp()
        self.session.bash("npm run build && node server.js &", "", is_error=False)
        self.assertEqual([], self.checks())

    def test_a_call_that_never_ran_is_not_a_run(self) -> None:  # V3
        for text in (
            "The user doesn't want to proceed with this tool use.",
            "<tool_use_error>Cancelled: parallel tool call errored</tool_use_error>",
            "Sibling tool call errored",
            "PreToolUse:Bash hook error: blocked",
        ):
            with self.subTest(text=text[:20]):
                self.setUp()
                self.session.bash("pytest", "5 passed", is_error=False)
                call_id = self.session.call("Bash", {"command": "pytest"})
                self.session.result(call_id, text, is_error=True)
                call_id = self.session.call("Bash", {"command": "mypy src"})
                self.session.result(call_id, text, is_error=True)
                events, scan = self.read()
                self.assertEqual({"pytest": "passed"}, results_by_title(events))
                self.assertEqual(1, scan["check_runs"])

    def test_a_nonzero_exit_is_a_failure(self) -> None:  # V3
        call_id = self.session.call("Bash", {"command": "pytest"})
        self.session.result(call_id, "Exit code 2\nerror: no tests", is_error=True)
        self.assertEqual("failed", self.only_check()["result"])

    def test_only_a_failure_summary_overrides_a_passing_flag(self) -> None:  # V4
        for command, output, expected in (
            ("pytest -q", "1 failed, 4 passed in 1s", "failed"),
            ("eslint .", "✖ 3 problems (0 errors, 3 warnings)", "not-recorded"),
            ("pytest -q", "tests/a.py::test_raises_AssertionError PASSED", "not-recorded"),
            ("ruff check --fix .", "Found 1 error (1 fixed, 0 remaining).", "passed"),
        ):
            with self.subTest(command=command, output=output[:12]):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                self.assertEqual(expected, self.only_check()["result"])

    def test_an_rtk_pass_beside_failure_text_is_not_a_pass(self) -> None:  # V5
        for output in ("Tests: 1 failed, 4 passed, 5 total", "AssertionError: boom"):
            with self.subTest(output=output[:10]):
                self.setUp()
                self.session.bash("rtk npm test", output, is_error=False)
                self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_failing_flag_needs_a_call_of_one_segment(self) -> None:  # V6
        for command, expected in (
            ("ruff check . && pytest", {"ruff check .": "not-recorded", "pytest": "not-recorded"}),
            ("pytest && echo done", {"pytest": "not-recorded"}),
            ("cd api && CI=1 uv run pytest", {"pytest": "failed"}),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=True)
                self.assertEqual(expected, results_by_title(self.read()[0]))

    def test_formatters_and_fixers_age_a_pass(self) -> None:  # V7
        for later in ("black .", "ruff format .", "prettier --write .", "eslint --fix ."):
            with self.subTest(later=later):
                self.setUp()
                self.session.bash("pytest", "5 passed", is_error=False)
                self.session.bash(later, "", is_error=False)
                check = next(e for e in self.checks() if e["title"] == "pytest")
                self.assertIs(True, check["before_last_change"])

    def test_a_fixer_later_in_the_same_call_ages_the_pass(self) -> None:  # V7
        self.session.bash("pytest && ruff check --fix .", "", is_error=False)
        found = {e["title"]: e for e in self.checks()}
        self.assertIs(True, found["pytest"]["before_last_change"])

    def test_a_format_check_ages_nothing(self) -> None:  # V7
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("ruff format --check .", "", is_error=False)
        found = {e["title"]: e for e in self.checks()}
        self.assertIs(False, found["pytest"]["before_last_change"])

    def test_output_is_not_attributed_across_other_commands(self) -> None:  # V8
        for command, output in (
            ("pytest & npm test; echo done", "12 passed"),
            ("pytest; npx playwright test", "12 passed"),
            ("pytest; python3 manage.py test", "Ran 12 tests in 1s\n\nOK"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, output, is_error=False)
                for title, result in results_by_title(self.read()[0]).items():
                    self.assertNotEqual("passed", result, title)


class ThePressCarriesTheValuesACallMasked(ClaudeChecksTestCase):
    """The press reads every masked value of the session, check or not."""

    def press(self) -> project_context.PressChecks:
        self.session.save(self.path)
        return project_context.claude_check_press(self.config, str(self.path))

    def test_a_curl_password_and_a_cookie_reach_the_press(self) -> None:
        self.session.bash(
            "curl -u alice:FakePass99 -H 'Cookie: sid=FakeSid99' https://x.example", "ok"
        )
        self.session.bash("pytest -q", "3 passed in 0.1s")
        masked = self.press().masked_values
        self.assertIn("FakePass99", masked)
        self.assertTrue(any("FakeSid99" in value for value in masked))

    def test_a_command_behind_the_rtk_prefix_is_masked_like_the_bare_command(self) -> None:
        self.session.bash("rtk vault login hvs.FakeFake99", "ok")
        self.session.bash("pytest -q", "3 passed in 0.1s")
        self.assertIn("hvs.FakeFake99", self.press().masked_values)

    def test_a_flag_that_only_looks_like_a_password_masks_nothing(self) -> None:
        self.session.bash("docker run --rm -u 1000:1000 img pytest -q", "1000 passed in 2s")
        self.session.bash("git push origin -u HEAD:main", "ok")
        self.assertEqual(frozenset(), self.press().masked_values)

    def test_a_session_that_masked_nothing_carries_nothing(self) -> None:
        self.session.bash("pytest -q", "3 passed in 0.1s")
        self.assertEqual(frozenset(), self.press().masked_values)


if __name__ == "__main__":
    unittest.main()


class AChangeAfterAPassIsPublishedPerCheck(ClaudeChecksTestCase):
    """DRC-4692 L1: the live level reads, per check, whether a command that may change files
    followed its latest run, in the same call or a later one, from the same order the press uses.
    """

    def test_a_changing_segment_later_in_the_same_call_marks_the_pass(self) -> None:
        self.session.bash("pytest tests && rm -rf src", "5 passed", is_error=False)
        self.assertIs(True, self.only_check()["changed_after"])

    def test_a_changing_command_in_a_later_call_marks_the_pass(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("python migrate.py", "done", is_error=False)
        self.assertIs(True, self.only_check()["changed_after"])

    def test_a_read_only_command_after_it_does_not(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("git status", "clean", is_error=False)
        self.assertIs(False, self.only_check()["changed_after"])

    def test_a_change_before_the_pass_does_not(self) -> None:
        self.session.bash("python migrate.py", "done", is_error=False)
        self.session.bash("pytest", "5 passed", is_error=False)
        self.assertIs(False, self.only_check()["changed_after"])

    def test_the_flag_reaches_the_published_fact(self) -> None:
        self.session.bash("pytest tests && rm -rf src", "5 passed", is_error=False)
        entry = self.only_check()
        fact = project_context._semantic_fact_from_event(entry, entry["kind"], "tool_report", "")
        self.assertIs(True, fact["changed_after"])


class ACheckFrozenAtAMomentIsTheCheckAsItStoodThen(ClaudeChecksTestCase):
    """DRC-4666: the abstention packet replays a Claude Code case offline.

    The latest run, an earlier failure and a later change are computed over
    the whole transcript, so filtering today's facts to those before the
    capture keeps a pass a later run overturned. The freeze re-derives them
    from the transcript as it stood at the capture instead.
    """

    def freeze(self, seconds: int) -> tuple[list[dict[str, Any]], project_context.PressChecks]:
        self.session.save(self.path)
        until = (START + dt.timedelta(seconds=seconds)).timestamp()
        return project_context.frozen_claude_checks(self.config, str(self.path), SID, until=until)

    def test_a_later_run_does_not_reach_back_into_the_frozen_moment(self) -> None:
        passed = self.session.bash("pytest", "5 passed", is_error=False)  # 10 s, result 15 s
        self.session.bash("touch changed.py", "", is_error=False)  # 20 s, result 25 s
        failed = self.session.bash("pytest", "1 failed, 4 passed", is_error=True)  # 30 s

        facts, press = self.freeze(27)
        checks = [fact for fact in facts if fact.get("subject") == "check"]
        self.assertEqual(1, len(checks))
        self.assertEqual("tool_report", checks[0]["type"])
        self.assertEqual("passed", checks[0]["result"])
        self.assertIs(False, checks[0]["earlier_failed"])
        self.assertEqual(passed, checks[0]["branch"]["record_id"])
        self.assertEqual({"harness": "claude", "sid": SID}, checks[0]["source_session"])
        self.assertEqual({passed: "5 passed"}, press.tails)
        self.assertEqual(frozenset({(passed, "pytest")}), press.changed_after)
        self.assertTrue(all(fact["at"] <= START.timestamp() + 27 for fact in facts))

        facts, press = self.freeze(60)
        checks = [fact for fact in facts if fact.get("subject") == "check"]
        self.assertEqual("failed", checks[0]["result"])
        self.assertEqual(failed, checks[0]["branch"]["record_id"])
        self.assertEqual(frozenset(), press.changed_after)

    def test_a_write_after_a_cd_is_frozen_under_the_folder_the_session_began_in(self) -> None:
        moved = self.cwd / "web" / "src"
        moved.mkdir(parents=True)
        self.session.cwd = str(moved)
        self.session.edit(str(moved / "Panel.tsx"))  # 10 s, result 15 s

        facts, _press = self.freeze(60)
        self.assertEqual(
            ["web/src/Panel.tsx"], [f["summary"] for f in facts if f.get("subject") == "write"]
        )

    def test_a_run_whose_result_came_after_the_moment_had_no_result_then(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)  # call 10 s, result 15 s
        facts, press = self.freeze(12)
        checks = [fact for fact in facts if fact.get("subject") == "check"]
        self.assertEqual("not-recorded", checks[0]["result"])
        self.assertEqual({}, press.tails)


class ACheckWritesTheFileItsOutputIsRedirectedInto(ClaudeChecksTestCase):
    """DRC-4709: a file redirect on a check segment is a write by that call. Owner,
    2026-09-27: a target inside the working directory is published as a written
    path, and one outside it counts only as outside."""

    def facts(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        events, scan = self.read()
        return [
            project_context._semantic_fact_from_event(e, e["kind"], "tool_report", "")
            for e in events
        ], scan

    def writes(self) -> list[str]:
        return sorted(e["title"] for e in self.read()[0] if e["subject"] == "write")

    def test_a_target_inside_the_working_directory_is_a_written_path(self) -> None:
        self.session.bash("pytest > src/out.txt", "", is_error=False)
        events, scan = self.read()
        write = next(e for e in events if e["subject"] == "write")
        self.assertEqual("src/out.txt", write["title"])
        self.assertEqual("Claude Bash call", write["source"])
        self.assertEqual(1, scan["written_paths"])
        facts, scan = self.facts()
        (self.cwd / "web").mkdir()
        level = levels.live_level(
            levels.Evidence(tuple(facts), scan, 0, str(self.cwd)),
            levels.Intent(saved=True, goal="Fix it", lines=("only touch web/",)),
        )
        self.assertIn(level.level, (levels.MEDIUM, levels.HIGH, levels.EXTREME))
        self.assertNotIn(levels.REASON_FLOOR_MET, level.reasons)

    def test_the_target_is_read_from_the_directory_the_check_ran_in(self) -> None:
        self.session.bash("cd src && pytest >> logs/run.txt", "", is_error=False)
        self.session.bash("(cd web && pytest > a.txt); pytest 2> b.txt", "", is_error=False)
        self.assertEqual(["b.txt", "src/logs/run.txt", "web/a.txt"], self.writes())

    def test_a_target_outside_it_or_unplaceable_is_counted_as_outside(self) -> None:
        for command in (
            "pytest > /tmp/out.txt",
            "pytest > ../elsewhere.txt",
            'pytest > "$OUT"',
            "pytest > $(mktemp)",
            "pytest > ~/out.txt",
            "pytest &> `mktemp`",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                _events, scan = self.read()
                self.assertEqual([], self.writes())
                self.assertEqual(0, scan["written_paths"])
                self.assertEqual(1, scan["outside_paths"])

    def test_a_redirect_to_nothing_or_a_descriptor_writes_nothing(self) -> None:
        for command in (
            "pytest > /dev/null",
            "pytest 2>&1",
            "pytest < in.txt",
            "pytest >&-",
            "pytest >>/dev/null",
            "pytest &>>/dev/null",
            "pytest 2>/dev/stderr",
            "pytest >/dev/stdout",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                _events, scan = self.read()
                self.assertEqual(0, scan["written_paths"] + scan["outside_paths"])

    def test_a_checks_own_redirect_does_not_age_its_own_pass(self) -> None:
        self.session.bash("pytest > src/out.txt", "", is_error=False)
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        self.assertIs(False, check["before_last_change"])
        self.assertIs(False, check["changed_after"])
        self.assertIsNone(self.read()[1]["last_changing_command_at"])

    def test_it_ages_an_earlier_check_in_the_same_call_and_not_a_later_one(self) -> None:
        self.session.bash("ruff check . && pytest > out.txt", "", is_error=False)
        found = {e["title"]: e for e in self.checks()}
        self.assertIs(True, found["ruff check ."]["changed_after"])
        self.assertIs(False, found["pytest"]["changed_after"])
        self.setUp()
        self.session.bash("pytest > out.txt && ruff check .", "", is_error=False)
        found = {e["title"]: e for e in self.checks()}
        self.assertIs(False, found["pytest"]["changed_after"])
        self.assertIs(False, found["ruff check ."]["changed_after"])

    def test_a_harmless_device_redirect_later_ages_no_pass(self) -> None:
        # Review W5.
        for later in ("mypy . >>/dev/null", "mypy . &>>/dev/null", "mypy . 2>/dev/stderr"):
            with self.subTest(later=later):
                self.setUp()
                self.session.bash("pytest", "5 passed", is_error=False)
                self.session.bash(later, "", is_error=False)
                found = {e["title"]: e for e in self.checks()}
                self.assertIs(False, found["pytest"]["before_last_change"])
                self.assertEqual(0, self.read()[1]["outside_paths"])

    def test_a_later_write_in_the_same_call_ages_the_earlier_pass(self) -> None:
        # Review W6 and Codex 2: `before_last_change` agrees with `changed_after`, so the
        # server and the page read the same pass as aged.
        self.session.bash("pytest && mypy . > src/x.py", "", is_error=False)
        found = {e["title"]: e for e in self.checks()}
        self.assertIs(True, found["pytest"]["before_last_change"])
        self.assertIs(True, found["pytest"]["changed_after"])
        self.assertIs(False, found["mypy ."]["before_last_change"])

    def test_it_ages_a_pass_from_an_earlier_call(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("mypy . > report.txt", "", is_error=False)
        found = {e["title"]: e for e in self.checks()}
        self.assertIs(True, found["pytest"]["before_last_change"])
        self.assertIs(False, found["mypy ."]["before_last_change"])

    def test_the_published_path_is_redacted_like_any_written_path(self) -> None:
        self.session.bash(f"pytest > logs/{FAKE_KEY}.txt", "", is_error=False)
        published = json.dumps(self.read())
        self.assertNotIn(FAKE_KEY, published)
        self.assertNotIn(FAKE_KEY[20:60], published)

    def test_a_target_holding_a_value_the_line_masks_is_never_published(self) -> None:
        # Review W1: the check line masks the value, so the path beside it must not show it.
        for command in (
            f"pytest --password {PLACEHOLDER} > {PLACEHOLDER}.log",
            f"TOKEN={PLACEHOLDER} pytest > out-{PLACEHOLDER}.log",
            f'pytest > "password={PLACEHOLDER}.log"',
            f"bash -c 'pytest --token {PLACEHOLDER}' > logs/{PLACEHOLDER}.txt",
        ):
            with self.subTest(command=command[:24]):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                events, scan = self.read()
                self.assertNotIn(PLACEHOLDER, json.dumps(events))
                self.assertEqual([], self.writes())
                self.assertEqual(1, scan["outside_paths"])

    def test_a_target_after_a_cd_the_shell_decides_is_counted_as_outside(self) -> None:
        # Review W2 and Codex 1: the directory is unknown until a literal `cd` places it again.
        for command in (
            "cd ~/other && pytest > t1",
            "cd $HOME && pytest > t2",
            'cd "$OUTSIDE" && pytest > t3',
            'cd "$(git rev-parse --show-toplevel)" && pytest > t4',
            "cd && pytest > t5",
            "cd - && pytest > t6",
            "pushd sub && pytest > t7",
            "cd sub && popd && pytest > t8",
            "cd $HOME && cd src && pytest > t9",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                _events, scan = self.read()
                self.assertEqual([], self.writes())
                self.assertEqual(1, scan["outside_paths"])

    def test_cd_options_are_read_as_options_and_a_literal_cd_places_it_again(self) -> None:
        for command, expected in (
            ("cd -P sub && pytest > t1", ["sub/t1"]),
            ("cd -L sub && pytest > t2", ["sub/t2"]),
            ("cd -- sub && pytest > t3", ["sub/t3"]),
            ("cd $HOME && cd {cwd}/src && pytest > t4", ["src/t4"]),
            ("(cd $HOME && pytest); pytest > t5", ["t5"]),
            ("cd $HOME && pytest > {cwd}/abs.txt", ["abs.txt"]),
        ):
            with self.subTest(command=command):
                self.setUp()
                # Quoted as a shell needs it: unquoted, a Windows path's backslashes are
                # escapes, and the shell, like the parser, would read a drive-relative path.
                self.session.bash(
                    command.format(cwd=shlex.quote(str(self.cwd))), "", is_error=False
                )
                self.assertEqual(expected, self.writes())

    def test_a_groups_own_redirect_is_read_where_the_group_started(self) -> None:
        # Review W3: the outer shell opens it before the group's `cd` runs.
        for command, inside in (
            ("(cd sub && pytest) > o1", ["o1"]),
            ("(cd sub && pytest) > ../x", []),
            ("bash -c 'cd sub && pytest' > o2", ["o2"]),
            ("bash -c 'cd sub && pytest' > ../y", []),
            ("cd web && (cd sub && pytest) > o3", ["web/o3"]),
            ("(cd a && (cd b && pytest) > o4)", ["a/o4"]),
            ("(cd sub && pytest > in.txt) > o5", ["o5", "sub/in.txt"]),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                _events, scan = self.read()
                self.assertEqual(inside, self.writes())
                self.assertEqual(0 if inside else 1, scan["outside_paths"])


class AWriteAtTheSameTimeAsAPassAgesIt(ClaudeChecksTestCase):
    """DRC-4709's tie item: a write or fixer from another call, recorded at the
    same time as a pass, ages it. The pass's own call is ordered by its
    segments instead, so `black . && pytest` keeps its pass current."""

    def same_time_as(self, call_row: int) -> None:
        """Stamp the last call with the time of an earlier call's record."""
        self.session.rows[-2]["timestamp"] = self.session.rows[call_row]["timestamp"]

    def test_an_edit_recorded_at_the_time_of_the_pass_ages_it(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        pass_row = len(self.session.rows) - 2
        self.session.edit(self.file("web/x.js"))
        self.same_time_as(pass_row)
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_a_fixer_recorded_at_the_time_of_the_pass_ages_it(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        pass_row = len(self.session.rows) - 2
        self.session.bash("black .", "", is_error=False)
        self.same_time_as(pass_row)
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_a_fixer_before_the_check_in_the_same_call_keeps_the_pass_current(self) -> None:
        for command in ("black . && pytest", "ruff format . && ruff check --fix . && pytest"):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                found = {e["title"]: e for e in self.checks()}
                self.assertEqual("passed", found["pytest"]["result"])
                self.assertIs(False, found["pytest"]["before_last_change"])


class ACheckCarriesTheTimeItsResultArrived(ClaudeChecksTestCase):
    """DRC-4702: a check's result can land after the words it is read against,
    so the published entry carries when its result arrived beside when its call
    began. Each record in these fixtures is five seconds after the last."""

    def test_a_recorded_run_publishes_the_time_of_the_record_that_holds_its_result(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        check = self.only_check()
        self.assertEqual(check["at"] + 5, check["result_at"])
        fact = project_context._semantic_fact_from_event(check, check["kind"], "tool_report", "")
        self.assertEqual(check["result_at"], fact["result_at"])

    def test_the_fact_id_does_not_move_when_the_result_arrives(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        check = self.only_check()
        unrecorded = {k: v for k, v in check.items() if k != "result_at"}
        self.assertEqual(
            project_context._semantic_fact_from_event(unrecorded, "check_run", "tool_report", "")[
                "fact_id"
            ],
            project_context._semantic_fact_from_event(check, "check_run", "tool_report", "")[
                "fact_id"
            ],
        )

    def test_a_run_with_no_result_or_in_the_background_has_no_result_time(self) -> None:
        self.session.call("Bash", {"command": "pytest"})
        self.assertNotIn("result_at", self.only_check())
        self.setUp()
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("pytest &", "", is_error=False)
        self.assertNotIn("result_at", self.only_check())

    def test_the_run_whose_result_arrived_last_is_the_latest(self) -> None:
        first = self.session.call("Bash", {"command": "pytest"})
        second = self.session.call("Bash", {"command": "pytest"})
        self.session.result(second, "5 passed", is_error=False)
        self.session.result(first, "Exit code 1\n1 failed", is_error=True)
        check = self.only_check()
        self.assertEqual("failed", check["result"])
        self.assertEqual(first, check["record_id"])
        self.assertIs(False, check["earlier_failed"])

    def out_of_order(self, first_output: str, first_failed: bool, second_output: str,
                     second_failed: bool) -> tuple[str, str]:  # fmt: skip
        """Two runs of one check called in order, the second's result landing first."""
        first = self.session.call("Bash", {"command": "pytest"})
        second = self.session.call("Bash", {"command": "pytest"})
        self.session.result(second, second_output, is_error=second_failed)
        self.session.result(first, first_output, is_error=first_failed)
        return first, second

    def test_a_later_called_failure_is_an_earlier_failure_of_the_latest(self) -> None:
        # Window lens, M13.
        first, _second = self.out_of_order("5 passed", False, "Exit code 1\n1 failed", True)
        check = self.only_check()
        self.assertEqual(first, check["record_id"])
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["earlier_failed"])

    def test_the_press_tail_belongs_to_the_published_run(self) -> None:
        # Window lens, M17.
        first, _second = self.out_of_order("5 passed", False, "Exit code 1\n1 failed", True)
        check = self.only_check()
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual(first, check["record_id"])
        self.assertEqual({check["record_id"]}, set(press.tails))

    def test_changed_after_names_the_published_run(self) -> None:
        # Window lens, M18.
        first = self.session.call("Bash", {"command": "pytest"})
        second = self.session.call("Bash", {"command": "pytest"})
        self.session.result(second, "Exit code 1\n1 failed", is_error=True)
        self.session.bash("touch changed.py", "", is_error=False)
        self.session.result(first, "5 passed", is_error=False)
        check = self.only_check()
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual(first, check["record_id"])
        self.assertIn((first, "pytest"), press.changed_after)

    def test_equal_result_times_pick_the_later_call(self) -> None:
        # Window lens, M11.
        first = self.session.call("Bash", {"command": "pytest"})
        second = self.session.call("Bash", {"command": "pytest"})
        self.session.result(second, "5 passed", is_error=False)
        self.session.result(first, "Exit code 1\n1 failed", is_error=True)
        self.session.rows[-1]["timestamp"] = self.session.rows[-2]["timestamp"]
        self.assertEqual(second, self.only_check()["record_id"])

    def test_a_result_after_a_frozen_moment_leaves_no_result_time(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)  # call 10 s, result 15 s
        self.session.save(self.path)
        until = (START + dt.timedelta(seconds=12)).timestamp()
        facts, _press = project_context.frozen_claude_checks(
            self.config, str(self.path), SID, until=until
        )
        self.assertNotIn("result_at", facts[0])
        until = (START + dt.timedelta(seconds=16)).timestamp()
        facts, _press = project_context.frozen_claude_checks(
            self.config, str(self.path), SID, until=until
        )
        self.assertEqual(START.timestamp() + 15, facts[0]["result_at"])


class WhyACheckHasNoRecordedResult(ClaudeChecksTestCase):
    """A withheld result names the rule that withheld it, as a closed token on the entry (DRC-4890)."""

    def unflagged_bash(self, command: str, output: str) -> None:
        # No error flag at all: the output alone would have to speak, so attribution decides.
        self.session.result(self.session.call("Bash", {"command": command}), output)

    def test_several_checks_in_one_call_publish_that_reason(self) -> None:
        self.unflagged_bash("pytest -q && ruff check .", "2 failed, 3 passed")
        checks = self.checks()
        self.assertEqual(["pytest -q", "ruff check ."], [check["title"] for check in checks])
        for check in checks:
            self.assertEqual("not-recorded", check["result"])
            self.assertEqual("several_checks", check["result_reason"])

    def test_a_directory_the_shell_places_at_run_time_publishes_that_reason(self) -> None:
        self.unflagged_bash('cd "$REPO" && pytest -q', "2 failed, 3 passed")
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertEqual("directory_not_placeable", check["result_reason"])

    def test_a_pipe_beside_another_printing_command_publishes_that_reason(self) -> None:
        self.unflagged_bash(
            "echo start && pytest -q 2>&1 | tail -3",
            "FAILED tests/test_retry.py::test_backoff\n2 failed, 3 passed",
        )
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertEqual("piped_beside_other_commands", check["result_reason"])

    def test_a_result_the_flag_decides_publishes_no_reason(self) -> None:
        self.session.bash("pytest -q 2>&1 | tail -3", "2 failed, 3 passed", is_error=True)
        check = self.only_check()
        self.assertEqual("failed", check["result"])
        self.assertNotIn("result_reason", check)

    def test_output_that_records_nothing_is_not_blamed_on_a_rule(self) -> None:
        # Attribution lifted, this still reads "ran, result not recorded": no rule withholds it.
        self.unflagged_bash("pytest -q && ruff check .", "collected 5 items\n.....")
        for check in self.checks():
            self.assertEqual("not-recorded", check["result"])
            self.assertNotIn("result_reason", check)

    def test_the_pi_collector_publishes_the_same_reason(self) -> None:
        runs = project_context._pi_check_runs(
            "echo start && pytest -q 2>&1 | tail -3",
            call_key="pi-call-1",
            at=1.0,
            result={
                "status": "exited",
                "at": 2.0,
                "tail": "FAILED tests/test_retry.py::test_backoff\n2 failed, 3 passed",
            },
            harness="pi",
            sid=SHORT,
        )
        self.assertEqual(1, len(runs))
        run = runs[0][1]
        self.assertEqual("not-recorded", run["result"])
        self.assertEqual("piped_beside_other_commands", run["result_reason"])

    def test_the_pi_collector_reads_the_last_line_and_the_error_flag(self) -> None:
        for result, tail, expected in (
            ({"status": "", "is_error": False}, "x\n3 passed in 1s", "passed"),
            ({"status": "", "is_error": False}, "x\n3 failed in 1s", "failed"),
            ({"status": "exited", "is_error": True}, "x\n3 passed in 1s", "not-recorded"),
            ({"status": "exited", "is_error": True}, "x\n3 failed in 1s", "failed"),
        ):
            with self.subTest(result=result, tail=tail):
                runs = project_context._pi_check_runs(
                    "echo a; pytest -q | tail -3",
                    call_key="pi-call-1",
                    at=1.0,
                    result={**result, "at": 2.0, "tail": tail},
                    harness="pi",
                    sid=SHORT,
                )
                self.assertEqual(expected, runs[0][1]["result"])


class WhatTheLastLineOfACheckSaysWhenOtherCommandsPrintToo(ClaudeChecksTestCase):
    """The runner's own summary on the last line speaks for the last check (DEC-29)."""

    def unflagged_bash(self, command: str, output: str) -> list[dict[str, Any]]:
        self.session.result(self.session.call("Bash", {"command": command}), output)
        return self.checks()

    def results_of(self, command: str, output: str) -> dict[str, str]:
        return {c["title"]: str(c["result"]) for c in self.unflagged_bash(command, output)}

    def result_of(self, command: str, output: str) -> str:
        # The entries come ranked by result, so the last check of the call is named, not indexed.
        return list(self.results_of(command, output).values())[-1]

    def test_a_setup_command_before_the_check_does_not_hide_its_summary(self) -> None:
        self.assertEqual(
            "passed",
            self.result_of(
                "source .venv/bin/activate && which python; pytest -q | tail -20",
                "/x/.venv/bin/python\n.............\n14 passed in 1.97s",
            ),
        )

    def test_a_failing_ruff_is_not_read_as_the_mypy_that_never_ran(self) -> None:
        self.assertEqual(
            {"ruff check .": "not-recorded", "mypy .": "not-recorded"},
            self.results_of("ruff check . && mypy .", "Found 2 errors."),
        )

    def test_a_silent_runner_never_takes_another_commands_line(self) -> None:
        self.assertEqual(
            "not-recorded",
            self.result_of("vitest run && tsc --noEmit | tail -5", "      Tests  5 passed (5)"),
        )

    def test_an_earlier_failure_in_the_window_does_not_fail_the_last_check(self) -> None:
        self.assertEqual(
            {"mypy .": "not-recorded", "ruff check .": "passed"},
            self.results_of(
                "echo go; mypy . 2>&1 | tail -5; ruff check . | tail -5",
                "src/a.py:1: error: Missing return\nFound 1 error in 1 file\nAll checks passed!",
            ),
        )

    def test_only_the_last_of_several_checks_is_recorded(self) -> None:
        self.assertEqual(
            {"mypy .": "not-recorded", "pytest -q": "passed"},
            self.results_of("mypy . ; pytest -q | tail -3", "x\n3 passed in 0.10s"),
        )

    def test_a_summary_followed_by_another_command_is_not_the_checks(self) -> None:
        self.assertEqual("not-recorded", self.result_of("pytest -q; echo done", "3 passed in 1s"))

    def test_each_runner_reads_its_own_table(self) -> None:
        for command, output, expected in (
            ("echo a; mypy .", "Success: no issues found in 3 source files", "passed"),
            ("echo a; mypy .", "Found 2 errors in 1 file (checked 3 source files)", "failed"),
            ("echo a; ruff check .", "All checks passed!", "passed"),
            ("echo a; ruff check .", "Found 2 errors.", "failed"),
            ("echo a; ruff check .", "[*] 1 fixable with the `--fix` option.", "failed"),
            ("echo a; vitest run", "      Tests  1 failed | 4 passed (5)", "failed"),
            ("echo a; vitest run", "      Tests  5 passed (5)", "passed"),
            (
                "echo a; vitest run | tail -5",
                (
                    " Test Files  1 passed (1)\n      Tests  5 passed (5)\n"
                    "   Start at  10:00:00\n   Duration  500ms"
                ),
                "passed",
            ),
            (
                "echo a; vitest run | tail -5",
                (
                    " Test Files  1 failed (1)\n      Tests  2 failed | 3 passed (5)\n"
                    "   Start at  10:00:00\n   Duration  500ms"
                ),
                "failed",
            ),
            ("echo a; python3 -m unittest", "Ran 4 tests in 0.01s\n\nOK", "passed"),
            ("echo a; python3 -m unittest", "Ran 0 tests in 0.000s\n\nOK", "not-recorded"),
            (
                "echo a; python3 -m unittest 2>&1 | tail -3",
                "Ran 0 tests in 0.000s\n\nOK",
                "not-recorded",
            ),
            (
                "echo a; python3 -m unittest",
                "Ran 4 tests in 0.01s\n\nFAILED (failures=1)",
                "failed",
            ),
            ("echo a; node --test", "\u2139 fail 0", "passed"),
            ("echo a; node --test", "\u2139 fail 2", "failed"),
            (
                "echo a; node --test 2>&1 | tail -9",
                (
                    "\u2139 tests 3\n\u2139 suites 0\n\u2139 pass 3\n\u2139 fail 0\n\u2139 cancelled 0\n"
                    "\u2139 skipped 0\n\u2139 todo 0\n\u2139 duration_ms 52"
                ),
                "passed",
            ),
            (
                "echo a; node --test 2>&1 | tail -9",
                (
                    "\u2139 tests 3\n\u2139 pass 1\n\u2139 fail 2\n\u2139 cancelled 0\n"
                    "\u2139 skipped 0\n\u2139 todo 0\n\u2139 duration_ms 52"
                ),
                "failed",
            ),
            ("echo a; pytest", "1 failed, 13 passed in 1.97s", "failed"),
            ("echo a; pytest", "no tests ran in 0.01s", "not-recorded"),
            ("echo a; pytest", "0 passed in 0.01s", "not-recorded"),
            ("echo a; mypy .", "14 passed in 1.97s", "not-recorded"),
            ("echo a; pytest", "Found 2 errors in 1 file", "not-recorded"),
        ):
            with self.subTest(command=command, output=output):
                self.setUp()
                self.assertEqual(expected, self.result_of(command, output))

    def test_biome_and_gradle_read_their_own_last_line(self) -> None:
        biome_ok = "Checked 12 files in 8ms. No fixes applied."
        biome_fail = "Checked 12 files in 8ms. No fixes applied.\nFound 2 errors."
        biome_closing = "Found 2 errors.\ncheck \u2501\u2501\u2501\n\n  \u2716 Some errors were emitted while running checks.\n  "
        gradle_ok = "> Task :test\n\nBUILD SUCCESSFUL in 4s\n3 actionable tasks: 3 executed"
        gradle_fail = "FAILURE: Build failed with an exception.\n\nBUILD FAILED in 1m 3s\n2 actionable tasks: 2 executed"
        for command, output, expected in (
            ("echo a; biome check .", biome_ok, "passed"),
            ("echo a; biome ci .", biome_ok, "passed"),
            ("echo a; pnpm exec biome check .", biome_ok, "passed"),
            ("echo a; biome check .", biome_fail, "failed"),
            ("echo a; biome check .", biome_closing, "failed"),
            # A pass line printed last after a failure above it is never a pass.
            ("echo a; biome check .", "Found 2 errors.\n" + biome_ok, "not-recorded"),
            ("echo a; biome check .", "Checked 0 files in 1ms. No fixes applied.", "not-recorded"),
            ("echo a; pytest", biome_ok, "not-recorded"),
            ("echo a; ./gradlew check", gradle_ok, "passed"),
            ("echo a; gradle test", gradle_ok, "passed"),
            ("echo a; ./gradlew check", gradle_fail, "failed"),
            ("echo a; gradle check", "BUILD FAILED in 2s", "failed"),
            ("echo a; gradle check", "BUILD SUCCESSFUL", "not-recorded"),
            ("echo a; ./gradlew check", "> Task :check UP-TO-DATE", "not-recorded"),
        ):
            with self.subTest(command=command, output=output):
                self.setUp()
                self.assertEqual(expected, self.result_of(command, output))

    def test_a_storybook_runner_has_no_summary_row_and_reads_the_flag_alone(self) -> None:
        for command in ("storybook test", "test-storybook", "pnpm test:stories"):
            with self.subTest(command=command):
                self.assertEqual("", project_context._summary_runner(command.split()))
                self.setUp()
                self.assertEqual(
                    "not-recorded", self.result_of(f"echo a; {command}", "Tests  5 passed (5)")
                )

    def test_an_error_flag_is_not_outvoted_by_a_passing_summary(self) -> None:
        # The failure may be the setup command, so the check is withheld, not passed.
        for command in (
            "echo a; pytest -q",
            "echo a; pytest -q --cov --cov-fail-under=90",
            "source .venv/bin/activate && which python; pytest -q | tail -20",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "14 passed in 1.97s", is_error=True)
                self.assertEqual("not-recorded", list(self.checks())[-1]["result"])

    def test_an_error_flag_beside_a_failing_summary_is_a_failure(self) -> None:
        self.session.bash("echo a; pytest -q", "2 failed in 1.97s", is_error=True)
        self.assertEqual("failed", list(self.checks())[-1]["result"])

    def test_a_clean_unpiped_flag_yields_to_a_failing_summary(self) -> None:
        for command in ("touch x; pytest -q", "make setup && pytest -q", "echo a; pytest -q"):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "3 failed in 1s", is_error=False)
                self.assertEqual("failed", list(self.checks())[-1]["result"])

    def test_a_clean_flag_still_yields_to_a_failing_summary(self) -> None:
        self.session.bash("echo a; pytest -q | tail -3", "3 failed in 1s", is_error=False)
        self.assertEqual("failed", list(self.checks())[-1]["result"])

    def test_a_substitution_before_the_check_withholds_its_summary(self) -> None:
        self.assertEqual(
            "not-recorded", self.result_of("echo $(touch marker); pytest -q", "3 passed in 1s")
        )

    def test_a_pipe_that_is_not_a_filter_withholds_the_summary(self) -> None:
        for command in ("echo a; pytest -q | sort", "echo a; pytest -q | tee out.log"):
            with self.subTest(command=command):
                self.setUp()
                self.assertEqual("not-recorded", self.result_of(command, "3 passed in 1s"))

    def test_a_second_check_of_the_same_runner_is_never_read_from_the_last_line(self) -> None:
        for command, output in (
            ("pytest a {} pytest b", "1 failed in 0.1s"),
            ("python3 -m unittest a {} python3 -m unittest b", "FAILED (failures=1)"),
            ("ruff check . {} ruff check x", "Found 2 errors."),
        ):
            for joiner in ("&&", "||", ";"):
                with self.subTest(command=command, joiner=joiner):
                    self.setUp()
                    results = self.results_of(command.format(joiner), output)
                    self.assertNotIn("failed", results.values())

    def test_a_line_of_repeated_counts_is_read_in_bounded_time(self) -> None:
        line = "      Tests  " + "1 a1 " * 3000
        self.assertEqual("", project_context._last_line_summary(["vitest", "run"], line))

    def test_a_cancelled_node_test_after_fail_zero_is_never_a_pass(self) -> None:
        info = project_context._INFO
        for cancelled, expected in (("1", ""), ("0", "passed")):
            text = (
                f"{info} pass 4\n{info} fail 0\n{info} cancelled {cancelled}\n{info} duration_ms 12"
            )
            with self.subTest(cancelled=cancelled):
                self.assertEqual(
                    expected, project_context._last_line_summary(["node", "--test"], text)
                )

    def test_an_rtk_wrapped_check_stays_flag_only(self) -> None:
        self.assertEqual("not-recorded", self.result_of("echo a; rtk pytest -q", "3 passed in 1s"))


class WhatClaudeCodeAppendsToACommandsOutput(ClaudeChecksTestCase):
    """Claude Code's own trailer lines are not the runner's output (DEC-29)."""

    def result_of(self, command: str, output: str) -> str:
        self.session.result(self.session.call("Bash", {"command": command}), output)
        return str(self.only_check()["result"])

    def test_a_cwd_reset_line_does_not_hide_the_summary(self) -> None:
        self.assertEqual(
            "passed", self.result_of("pytest -q", "14 passed in 1.97s\nShell cwd was reset to /x")
        )

    def test_a_modified_files_notice_does_not_hide_the_summary(self) -> None:
        notice = (
            "[This command modified 2 files you've previously read: a/b.py, c.py. "
            "Call Read before editing.]"
        )
        self.assertEqual(
            "passed",
            self.result_of("pytest -q", f"14 passed in 1.97s\n{notice}\nShell cwd was reset to /x"),
        )

    def test_a_trailer_shaped_line_in_the_middle_of_the_output_is_kept(self) -> None:
        self.assertEqual(
            "failed", self.result_of("pytest -q", "Shell cwd was reset to /x\n1 failed in 0.1s\n")
        )

    def test_the_trailer_is_not_published_in_the_press_tail(self) -> None:
        self.session.result(
            self.session.call("Bash", {"command": "pytest -q"}),
            "14 passed in 1.97s\nShell cwd was reset to /x",
        )
        self.session.save(self.path)
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual(["14 passed in 1.97s"], list(press.tails.values()))

    def test_unittest_ok_with_a_count_is_a_pass_and_failed_with_counts_a_failure(self) -> None:
        for output, expected in (
            ("OK (skipped=4)", "passed"),
            ("OK (expected failures=1)", "passed"),
            ("OK (skipped=2, expected failures=1)", "passed"),
            ("FAILED (failures=1, skipped=2)", "failed"),
        ):
            with self.subTest(output=output):
                self.setUp()
                self.assertEqual(
                    expected,
                    self.result_of(
                        "python3 -m unittest 2>&1 | tail -3", f"Ran 9 tests in 0.1s\n\n{output}"
                    ),
                )


class EveryWithheldResultNamesItsReason(ClaudeChecksTestCase):
    """No check shows "no token": each shape a rule withholds publishes a closed token (DEC-29)."""

    def test_every_shape_the_attribution_rules_withhold_carries_a_reason(self) -> None:
        for command, output in (
            ("pytest -q && ruff check .", "2 failed, 3 passed in 1.2s"),
            ("pytest a && pytest b", "2 failed, 3 passed in 1.2s"),
            ('cd "$REPO" && pytest -q', "2 failed, 3 passed"),
            ("echo start && pytest -q 2>&1 | tail -3", "2 failed, 3 passed"),
            ("source .venv/bin/activate; pytest -q", "2 failed, 3 passed"),
            ("git status; pytest -q", "2 failed, 3 passed"),
            ("pytest -q; echo done", "2 failed, 3 passed"),
            ("(echo a; pytest -q)", "2 failed, 3 passed"),
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.result(self.session.call("Bash", {"command": command}), output)
                for check in self.checks():
                    self.assertEqual("not-recorded", check["result"])
                    self.assertIn(
                        check["result_reason"], project_context.CHECK_NOT_RECORDED_REASONS
                    )


class TheBiomeStorybookAndGradleRunnersAreChecks(ClaudeChecksTestCase):
    """DEC-23 item 3's closed list names these, and their fixer spellings are not checks' passes."""

    CHECKS = (
        "biome check .",
        "biome ci .",
        "pnpm exec biome check src",
        "pnpm biome check src",
        "storybook test",
        "pnpm exec storybook test",
        "test-storybook --ci",
        "pnpm test:stories",
        "pnpm run test:stories",
        "npm run test:stories",
        "yarn test:stories",
        "./gradlew check",
        "gradle check",
        "gradle test",
        "./gradlew test",
    )

    def test_each_is_a_check_with_its_command_as_the_title(self) -> None:
        for command in self.CHECKS:
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual(1, len(self.checks()))
                self.assertEqual("passed", self.only_check()["result"])

    def test_a_non_runner_beside_them_is_not_a_check(self) -> None:
        for command in (
            "biome format .",
            "biome lint",
            "pnpm biome",
            "storybook dev",
            "pnpm storybook",
        ):
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=False)
                self.assertEqual([], self.checks())

    def test_a_failing_flag_fails_each(self) -> None:
        for command in self.CHECKS:
            with self.subTest(command=command):
                self.setUp()
                self.session.bash(command, "", is_error=True)
                self.assertEqual("failed", self.only_check()["result"])

    def test_the_fixer_spellings_are_fixers(self) -> None:
        for command in (
            "biome check --write .",
            "biome check --fix .",
            "biome check --apply .",
            "biome check --unsafe .",
            "biome check --write --unsafe .",
            "biome ci --apply-unsafe .",
            "biome format --write .",
            "pnpm exec biome check --write",
            "storybook test -u",
            "storybook test --updateSnapshot",
            "test-storybook -u",
            "test-storybook --updateSnapshot",
        ):
            with self.subTest(command=command):
                self.assertTrue(project_context._is_fixer(command.split()))

    def test_the_read_only_spellings_are_not_fixers(self) -> None:
        for command in (
            "biome check .",
            "biome ci --error-on-warnings .",
            "storybook test --ci",
            "storybook dev -u",
            "curl -u me host",
        ):
            with self.subTest(command=command):
                self.assertFalse(project_context._is_fixer(command.split()))

    def test_a_fixer_run_ages_an_earlier_pass(self) -> None:
        for later in ("biome check --write .", "biome format --write .", "storybook test -u"):
            with self.subTest(later=later):
                self.setUp()
                self.session.bash("pytest", "5 passed", is_error=False)
                self.session.bash(later, "", is_error=False)
                check = next(e for e in self.checks() if e["title"] == "pytest")
                self.assertIs(True, check["before_last_change"])

    def test_a_clean_run_ages_nothing(self) -> None:
        self.session.bash("pytest", "5 passed", is_error=False)
        self.session.bash("biome check .", "", is_error=False)
        found = {e["title"]: e for e in self.checks()}
        self.assertIs(False, found["pytest"]["before_last_change"])
