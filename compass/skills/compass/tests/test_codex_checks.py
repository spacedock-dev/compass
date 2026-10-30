"""What a Codex reader sees of the commands a session ran and the files it patched.

DEC-23 as applied to Codex (docs/design-reading-a-session.md, the 2026-10-30 amendment) is the
ruling. Every fixture is built from the field SHAPES in
`docs/captures/codex/tool-calls-0.149-0.164-macos.jsonl`: a `session_meta` head, and
`event_msg` rows of type `item_completed` whose `item` is a `CommandExecution` (`command`,
`cwd` as a `file://` URI, `exit_code`, `aggregated_output`), a `FileChange` (`changes` keyed by
absolute path), an `McpToolCall` (`tool`, `readOnlyHint`) or a `SubAgentActivity`. No text here
came from a real rollout.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    ci_read,
    git_status,
    observer,
    project_context,
    reading,
    reading_route,
    semantic_history,
)
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

SID = "019a2b3c-0000-7000-8000-000000000001"
SHORT = SID[:8]
START = dt.datetime(2026, 10, 30, 3, 0, 0, tzinfo=dt.UTC)
REMOTE = ("github.com", "acme/widgets")
BOUND_GOAL = "https://github.com/acme/widgets/pull/7"
# Text a patch carried. It must never reach anything Compass publishes.
PATCH_BODY = "def handler():  # PATCHBODYMARKER"
PATCH_DIFF = "@@ -1 +1 @@\n-old\n+DIFFBODYMARKER"


class Rollout:
    """A Codex rollout in the recorded shapes, one item at a time."""

    def __init__(self, cwd: Path, *, version: str = "0.164.0") -> None:
        self.cwd = str(cwd)
        self.ms = int(START.timestamp() * 1000)
        self.items = 0
        self.rows: list[dict[str, Any]] = [
            {
                "timestamp": self._iso(),
                "type": "session_meta",
                "payload": {
                    "id": SID,
                    "timestamp": self._iso(),
                    "cwd": self.cwd,
                    "originator": "codex_cli_rs",
                    "cli_version": version,
                },
            }
        ]

    def _iso(self) -> str:
        return (
            dt.datetime.fromtimestamp(self.ms / 1000, tz=dt.UTC).isoformat().replace("+00:00", "Z")
        )

    def _tick(self) -> int:
        self.ms += 5000
        return self.ms

    def prompt(self, text: str) -> None:
        self._tick()
        self.rows.append(
            {
                "timestamp": self._iso(),
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )

    def item(self, item: dict[str, Any], *, took_ms: int = 1000) -> str:
        self.items += 1
        item_id = f"item_{self.items:03d}"
        started = self._tick()
        completed = started + took_ms
        self.ms = completed
        self.rows.append(
            {
                "timestamp": self._iso(),
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "thread_id": SID,
                    "turn_id": "turn-1",
                    "started_at_ms": started,
                    "completed_at_ms": completed,
                    "item": {"id": item_id, **item},
                },
            }
        )
        return item_id

    def item_at(self, item: dict[str, Any], started: int, completed: int) -> str:
        """An item whose start and end are given, for calls that overlap."""
        self.items += 1
        item_id = f"item_{self.items:03d}"
        self.ms = max(self.ms, completed)
        self.rows.append(
            {
                "timestamp": dt.datetime.fromtimestamp(completed / 1000, tz=dt.UTC)
                .isoformat()
                .replace("+00:00", "Z"),
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "thread_id": SID,
                    "turn_id": "turn-1",
                    "started_at_ms": started,
                    "completed_at_ms": completed,
                    "item": {"id": item_id, **item},
                },
            }
        )
        return item_id

    @staticmethod
    def command_item(script: str, output: str, cwd: str, exit_code: Any = 0) -> dict[str, Any]:
        return {
            "type": "CommandExecution",
            "command": ["/bin/bash", "-lc", script],
            "cwd": cwd,
            "exit_code": exit_code,
            "status": "completed" if exit_code == 0 else "failed",
            "aggregated_output": output,
        }

    def command(
        self,
        script: str,
        output: str = "",
        *,
        exit_code: int = 0,
        flag: str = "-lc",
        shell: str = "/bin/bash",
        cwd: str | None = None,
    ) -> str:
        return self.item(
            {
                "type": "CommandExecution",
                "command": [shell, flag, script],
                "cwd": cwd if cwd is not None else "file://" + self.cwd,
                "exit_code": exit_code,
                "status": "completed" if exit_code == 0 else "failed",
                "aggregated_output": output,
                "stdout": output,
                "stderr": "",
                "formatted_output": output,
                "parsed_cmd": [],
                "duration": {"secs": 1, "nanos": 0},
                "process_id": "1",
                "source": "agent",
            }
        )

    def patch(self, changes: dict[str, dict[str, Any]]) -> str:
        return self.item(
            {
                "type": "FileChange",
                "changes": changes,
                "status": "completed",
                "stdout": "",
                "stderr": "",
            }
        )

    def mcp(self, tool: str, *, read_only: Any = True) -> str:
        item: dict[str, Any] = {
            "type": "McpToolCall",
            "server": "node_repl",
            "tool": tool,
            "arguments": {"code": "require('fs').writeFileSync('x', 'y')"},
            "status": "completed",
            "result": {"content": [], "isError": False},
        }
        if read_only is not None:
            item["readOnlyHint"] = read_only
        return self.item(item)

    def subagent(self) -> str:
        return self.item(
            {
                "type": "SubAgentActivity",
                "agent_thread_id": "019a2b3c-0000-7000-8000-0000000000ff",
                "agent_path": "worker",
                "kind": "started",
                "model": None,
                "reasoning_effort": None,
            }
        )

    def function_call(self, name: str, arguments: dict[str, Any] | str) -> None:
        self._tick()
        self.rows.append(
            {
                "timestamp": self._iso(),
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": name,
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                    "call_id": f"call_{len(self.rows)}",
                },
            }
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8")


class CodexChecksTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "work" / "billing"
        self.cwd.mkdir(parents=True)
        self.path = self.root / "codex" / "sessions" / "2026" / "10" / "30" / f"rollout-{SID}.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.rollout = Rollout(self.cwd)
        self.rollout.prompt("Add retry with backoff to the webhook handler.")
        self.goal_texts: tuple[str, ...] = (BOUND_GOAL,)
        patcher = mock.patch.object(ci_read, "probe_session", side_effect=self._identity)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _identity(
        _config: Any, _folder: str = "", *_args: Any, **_kwargs: Any
    ) -> git_status.GitIdentity:
        return git_status.GitIdentity("a" * 40, *REMOTE)

    def file(self, name: str) -> str:
        return str(self.cwd / name)

    def read(self) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.rollout.save(self.path)
        return project_context.codex_tool_reports(
            self.config, str(self.path), SHORT, goal_texts=self.goal_texts
        )

    def of(self, subject: str) -> list[dict[str, Any]]:
        return [row for row in self.read()[0] if row["subject"] == subject]

    def only_check(self) -> dict[str, Any]:
        found = self.of("check")
        self.assertEqual(1, len(found), found)
        return found[0]


class AFailingTestIsShownAsAFailedCheck(CodexChecksTestCase):
    def test_a_nonzero_exit_is_a_failed_check_from_the_exit_status(self) -> None:
        self.rollout.command(
            "pytest -q",
            "F.\nFAILED tests/test_retry.py::test_backoff\n1 failed, 1 passed in 0.2s",
            exit_code=1,
        )
        check = self.only_check()
        self.assertEqual("failed", check["result"])
        self.assertEqual("flag", check["result_source"])
        self.assertEqual("pytest -q", check["title"])
        self.assertEqual("codex", check["harness"])
        self.assertEqual(SHORT, check["sid"])
        self.assertEqual("Codex command and its exit status", check["source"])
        # The call's time is when the command started; the result's is when it ended.
        self.assertLess(check["at"], check["result_at"])

    def test_a_zero_exit_is_a_passed_check(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=0)
        self.assertEqual("passed", self.only_check()["result"])

    def test_a_negative_exit_is_ran_with_no_result(self) -> None:
        # A process Codex killed or timed out: never a pass and never a failure (DEC-23 item 1),
        # whatever its last line says.
        self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=-1)
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertNotIn("result_source", check)


class AnUnknownExitStatusRecordsNoResult(CodexChecksTestCase):
    """A negative, missing or non-integer exit code is an unknown status: the summary line a
    killed process printed is never read as its result."""

    def results(self) -> list[str]:
        return [row["result"] for row in self.of("check")]

    def test_a_killed_pass_summary_is_no_result(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=-9)
        self.assertEqual(["not-recorded"], self.results())

    def test_a_killed_failure_summary_is_no_result(self) -> None:
        self.rollout.command("pytest -q", "1 failed in 0.2s", exit_code=-15)
        self.assertEqual(["not-recorded"], self.results())

    def test_a_missing_exit_code_is_no_result(self) -> None:
        item = Rollout.command_item("pytest -q", "3 passed in 0.1s", "file://" + str(self.cwd))
        del item["exit_code"]
        self.rollout.item(item)
        self.assertEqual(["not-recorded"], self.results())

    def test_a_null_exit_code_in_a_chain_is_no_result_for_either_check(self) -> None:
        self.rollout.item(
            Rollout.command_item(
                "ruff check . && pytest -q",
                "All checks passed!\n3 passed in 0.1s",
                "file://" + str(self.cwd),
                exit_code=None,
            )
        )
        self.assertEqual(["not-recorded", "not-recorded"], self.results())

    def test_a_failure_line_with_exit_zero_is_never_a_pass(self) -> None:
        self.rollout.command("pytest -q | tail -1", "1 failed in 0.2s", exit_code=0)
        self.assertNotEqual("passed", self.only_check()["result"])

    def test_a_secret_on_the_line_is_masked_and_the_output_is_not_published(self) -> None:
        self.rollout.command(
            "API_TOKEN=hunter2abc pytest -q", "OUTPUTMARKER\n1 failed in 0.2s", exit_code=1
        )
        entries, scan = self.read()
        text = json.dumps([entries, scan])
        self.assertNotIn("hunter2abc", text)
        self.assertNotIn("OUTPUTMARKER", text)

    def test_the_scan_counts_what_was_read(self) -> None:
        self.rollout.command("pytest -q", "1 failed in 0.2s", exit_code=1)
        self.rollout.command("ls -la", "total 0")
        self.rollout.command("python scripts/migrate.py", "", exit_code=0)
        _entries, scan = self.read()
        self.assertEqual(3, scan["shell_calls"])
        self.assertEqual(1, scan["check_runs"])
        self.assertEqual(1, scan["failed"])
        self.assertEqual(2, scan["other_commands"])
        self.assertNotIn("commands_unreadable", scan)


class PatchesAreWrittenFiles(CodexChecksTestCase):
    def test_added_and_updated_paths_are_written_relative_to_the_session_folder(self) -> None:
        self.rollout.patch(
            {
                self.file("src/retry.py"): {"type": "add", "content": PATCH_BODY},
                self.file("src/app.py"): {
                    "type": "update",
                    "unified_diff": PATCH_DIFF,
                    "move_path": None,
                },
            }
        )
        writes = self.of("write")
        self.assertEqual({"src/retry.py", "src/app.py"}, {row["title"] for row in writes})
        self.assertEqual({"Codex apply_patch call"}, {row["source"] for row in writes})
        self.assertEqual({"codex"}, {row["harness"] for row in writes})

    def test_a_deleted_or_moved_away_path_is_not_written(self) -> None:
        self.rollout.patch(
            {
                self.file("src/old.py"): {"type": "delete", "content": PATCH_BODY},
                self.file("src/a.py"): {
                    "type": "update",
                    "unified_diff": PATCH_DIFF,
                    "move_path": self.file("src/b.py"),
                },
            }
        )
        self.assertEqual({"src/b.py"}, {row["title"] for row in self.of("write")})

    def test_a_patch_body_never_reaches_the_published_payload(self) -> None:
        self.rollout.patch(
            {
                self.file("src/retry.py"): {"type": "add", "content": PATCH_BODY},
                self.file("src/app.py"): {"type": "update", "unified_diff": PATCH_DIFF},
            }
        )
        entries, scan = self.read()
        text = json.dumps([entries, scan])
        self.assertNotIn("PATCHBODYMARKER", text)
        self.assertNotIn("DIFFBODYMARKER", text)

    def test_a_path_outside_the_session_folder_is_counted_not_published(self) -> None:
        self.rollout.patch({str(self.root / "elsewhere.py"): {"type": "add", "content": "x"}})
        entries, scan = self.read()
        self.assertFalse([row for row in entries if row["subject"] == "write"])
        self.assertEqual(1, scan["outside_paths"])

    def test_a_pass_followed_by_a_patch_is_before_the_last_change(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.rollout.patch({self.file("src/app.py"): {"type": "update", "unified_diff": "x"}})
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_a_pass_followed_by_a_deletion_is_before_the_last_change(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.rollout.patch({self.file("src/app.py"): {"type": "delete", "content": "x"}})
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_a_pass_after_the_patch_is_current(self) -> None:
        self.rollout.patch({self.file("src/app.py"): {"type": "update", "unified_diff": "x"}})
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(False, self.only_check()["before_last_change"])


class ToolsCompassCannotReadAgeAPass(CodexChecksTestCase):
    """DEC-23's Pi rule, applied to Codex: guessing that an unknown tool only reads is what would
    produce a false `consistent`."""

    def pass_then(self, act: Any) -> dict[str, Any]:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        act()
        return self.only_check()

    def test_the_js_tool_ages_a_pass_whatever_its_hint_says(self) -> None:
        check = self.pass_then(lambda: self.rollout.mcp("js", read_only=True))
        self.assertIs(True, check["before_last_change"])
        self.assertIs(True, check["changed_after"])

    def test_a_tool_not_marked_read_only_ages_a_pass(self) -> None:
        self.assertIs(
            True,
            self.pass_then(lambda: self.rollout.mcp("create_issue", read_only=False))[
                "before_last_change"
            ],
        )

    def test_a_tool_with_no_hint_ages_a_pass(self) -> None:
        self.assertIs(
            True,
            self.pass_then(lambda: self.rollout.mcp("create_issue", read_only=None))[
                "before_last_change"
            ],
        )

    def test_a_tool_marked_read_only_does_not(self) -> None:
        self.assertIs(
            False,
            self.pass_then(lambda: self.rollout.mcp("search_issues", read_only=True))[
                "before_last_change"
            ],
        )

    def test_a_command_in_a_shape_compass_does_not_read_ages_a_pass(self) -> None:
        def odd() -> None:
            self.rollout.item(
                {
                    "type": "CommandExecution",
                    "command": ["/usr/bin/python3", "-c", "open('x','w')"],
                    "cwd": "file://" + str(self.cwd),
                    "exit_code": 0,
                    "status": "completed",
                    "aggregated_output": "",
                }
            )

        check = self.pass_then(odd)
        self.assertIs(True, check["before_last_change"])
        self.assertEqual(1, self.read()[1]["unread_calls"])


class AChangeThatOverlapsAPassAgesIt(CodexChecksTestCase):
    """A change is dated by its end and a check by its start, so a change still running when a
    pass began ages it: dating both by their starts read a pass as current while a `sed -i` begun
    a second earlier went on rewriting the file for twenty seconds after it."""

    def setUp(self) -> None:
        super().setUp()
        self.base = self.rollout.ms
        self.uri = "file://" + str(self.cwd)

    def at(self, item: dict[str, Any], started: int, completed: int) -> str:
        return self.rollout.item_at(item, self.base + started, self.base + completed)

    def a_pass(self, started: int = 2000, completed: int = 10000) -> str:
        return self.at(
            Rollout.command_item("pytest -q", "3 passed in 0.1s", self.uri), started, completed
        )

    def assert_aged(self, call: str) -> None:
        check = self.only_check()
        self.assertIs(True, check["before_last_change"])
        self.assertIs(True, check["changed_after"])
        press = project_context.codex_check_press(
            self.config, str(self.path), goal_texts=self.goal_texts
        )
        self.assertIn((call, "pytest -q"), press.changed_after)

    def assert_current(self) -> None:
        check = self.only_check()
        self.assertIs(False, check["before_last_change"])
        self.assertIs(False, check["changed_after"])

    def test_a_command_begun_before_a_pass_and_ended_after_it_ages_it(self) -> None:
        call = self.a_pass()
        self.at(Rollout.command_item("sed -i s/a/b/ src/x.py", "", self.uri), 1000, 30000)
        self.assert_aged(call)

    def test_a_patch_begun_before_a_pass_and_ended_after_it_ages_it(self) -> None:
        call = self.a_pass()
        self.at(
            {
                "type": "FileChange",
                "changes": {self.file("src/x.py"): {"type": "update", "unified_diff": "x"}},
                "status": "completed",
            },
            1000,
            30000,
        )
        self.assert_aged(call)

    def test_a_shell_open_across_a_pass_ages_it(self) -> None:
        call = self.a_pass(5000, 6000)
        self.at(Rollout.command_item("bash", "", self.uri), 1000, 60000)
        self.assert_aged(call)

    def test_a_change_inside_the_pass_still_ages_it(self) -> None:
        call = self.a_pass()
        self.at(Rollout.command_item("sed -i s/a/b/ src/x.py", "", self.uri), 5000, 6000)
        self.assert_aged(call)

    def test_a_change_ended_before_the_pass_began_does_not(self) -> None:
        self.at(Rollout.command_item("sed -i s/a/b/ src/x.py", "", self.uri), 500, 1500)
        self.a_pass()
        self.assert_current()


class InputToARunningShellAgesAPass(CodexChecksTestCase):
    """Text written into a running process may change files, and Compass does not read what it
    did: it ages every earlier pass, as a tool whose effect is not read does."""

    def test_input_written_after_a_pass_ages_it(self) -> None:
        self.rollout.function_call("exec_command", {"cmd": "bash", "tty": True})
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.rollout.function_call("write_stdin", {"session_id": 1, "chars": "sed -i s/a/b/ x\n"})
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_arguments_that_do_not_parse_age_it(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.rollout.function_call("write_stdin", "{not json")
        self.assertIs(True, self.only_check()["before_last_change"])

    def test_an_empty_poll_does_not(self) -> None:
        self.rollout.function_call("exec_command", {"cmd": "npm test", "yield_time_ms": 1000})
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.rollout.function_call("write_stdin", {"session_id": 1, "chars": ""})
        check = self.only_check()
        self.assertIs(False, check["before_last_change"])
        self.assertEqual(0, self.read()[1]["unread_calls"])


class SubagentsAreNotRead(CodexChecksTestCase):
    def test_a_pass_in_a_session_that_ran_a_subagent_is_read_incomplete(self) -> None:
        self.rollout.subagent()
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(True, self.only_check()["read_incomplete"])

    def test_a_spawn_call_alone_marks_it_too(self) -> None:
        self.rollout.function_call("spawn_agent", {"message": "go"})
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(True, self.only_check()["read_incomplete"])

    def test_any_subagent_call_in_a_clipped_read_marks_it(self) -> None:
        # The spawn is outside the window read; a later call to the same child is inside it.
        for name in (
            "wait_agent",
            "send_message",
            "followup_task",
            "interrupt_agent",
            "close_agent",
        ):
            with self.subTest(name=name):
                self.setUp()
                self.rollout.function_call("spawn_agent", {"message": "go"})
                for i in range(60):
                    self.rollout.command(f"ls -la dir{i}", "x" * 400)
                self.rollout.command("pytest -q", "3 passed in 0.1s")
                self.rollout.function_call(name, {"target": "worker"})
                self.rollout.save(self.path)
                entries, scan = project_context.codex_tool_reports(
                    self.config, str(self.path), SHORT, max_bytes=16 * 1024
                )
                self.assertIsNotNone(scan.get("reads_from"))
                (check,) = [row for row in entries if row["subject"] == "check"]
                self.assertIs(True, check["read_incomplete"])

    def test_a_failure_stays_a_failure(self) -> None:
        self.rollout.subagent()
        self.rollout.command("pytest -q", "1 failed in 0.2s", exit_code=1)
        check = self.only_check()
        self.assertEqual("failed", check["result"])
        self.assertIs(False, check["read_incomplete"])

    def test_without_a_subagent_a_pass_is_complete(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(False, self.only_check()["read_incomplete"])


class ARolloutWithNoExitStatusIsNotRead(CodexChecksTestCase):
    def test_a_rollout_before_0_149_publishes_no_entries_and_no_counts(self) -> None:
        self.rollout = Rollout(self.cwd, version="0.146.0")
        self.rollout.function_call("exec_command", {"cmd": "pytest -q"})
        entries, scan = self.read()
        self.assertEqual([], entries)
        self.assertEqual({"commands_unreadable": True}, scan)

    def test_an_unknown_version_with_shell_calls_and_no_items_is_not_read(self) -> None:
        self.rollout.rows[0]["payload"].pop("cli_version")
        self.rollout.function_call("shell_command", {"command": "pytest -q"})
        self.assertEqual({"commands_unreadable": True}, self.read()[1])

    def test_an_unknown_version_with_items_is_read(self) -> None:
        self.rollout.rows[0]["payload"].pop("cli_version")
        self.rollout.command("pytest -q", "1 failed in 0.2s", exit_code=1)
        self.assertEqual("failed", self.only_check()["result"])


class TheFolderIsReadOnlyFromAPlainFileUri(CodexChecksTestCase):
    def written_by(self, cwd: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.rollout.command("pytest -q > report.txt", "", cwd=cwd)
        entries, scan = self.read()
        return [row for row in entries if row["subject"] == "write"], scan

    def test_a_plain_file_uri_places_a_redirect(self) -> None:
        writes, _scan = self.written_by("file://" + str(self.cwd))
        self.assertEqual(["report.txt"], [row["title"] for row in writes])

    def test_a_host_another_scheme_an_encoding_or_a_relative_uri_places_nothing(self) -> None:
        for cwd in (
            "file://host" + str(self.cwd),
            "ssh://" + str(self.cwd),
            "file://" + str(self.cwd).replace("work", "w%6Frk"),
            "file:relative/dir",
            str(self.cwd),
        ):
            with self.subTest(cwd=cwd):
                self.setUp()
                writes, scan = self.written_by(cwd)
                self.assertEqual([], writes)
                self.assertEqual(1, scan["outside_paths"])


class ACiReadUsesTheStructuredExitCode(CodexChecksTestCase):
    ROWS = "build\tfail\t1m\thttps://example.invalid/1\n"

    def ci(self, exit_code: int, output: str) -> dict[str, Any]:
        self.rollout.command("gh pr checks 7", output, exit_code=exit_code)
        found = self.of("ci_command")
        self.assertEqual(1, len(found), found)
        return found[0]

    def test_exit_1_with_checks_reported_is_a_failure(self) -> None:
        self.assertEqual("failed", self.ci(1, self.ROWS)["result"])

    def test_exit_8_pending_is_no_result(self) -> None:
        self.assertEqual("not-recorded", self.ci(8, self.ROWS)["result"])

    def test_exit_4_no_login_is_no_result(self) -> None:
        self.assertEqual(
            "not-recorded",
            self.ci(4, "To get started with GitHub CLI, please run:  gh auth login")["result"],
        )

    def test_no_compass_words_are_added_to_the_tail(self) -> None:
        self.rollout.command("gh pr checks 7", self.ROWS, exit_code=1)
        self.rollout.save(self.path)
        press = project_context.codex_check_press(
            self.config, str(self.path), goal_texts=self.goal_texts
        )
        self.assertTrue(press.tails)
        self.assertFalse(any("Exit code" in tail for tail in press.tails.values()))


class ATimeIsReadOnlyWhenFinite(CodexChecksTestCase):
    """A time a browser could not parse never reaches the published payload."""

    def test_a_time_that_is_not_a_finite_millisecond_count_is_not_read(self) -> None:
        for value in (float("inf"), float("nan"), 1e300, 2**53, 0, -5):
            with self.subTest(value=value):
                self.assertIsNone(project_context._codex_ms(value))
        self.assertEqual(1.5, project_context._codex_ms(1500))

    def test_the_record_timestamp_stands_in(self) -> None:
        for value in (float("inf"), float("nan"), 1e300):
            with self.subTest(value=value):
                self.setUp()
                self.rollout.command("pytest -q", "1 failed in 0.2s", exit_code=1)
                row = self.rollout.rows[-1]
                row["payload"]["started_at_ms"] = value
                row["payload"]["completed_at_ms"] = value
                entries, scan = self.read()
                check = next(row for row in entries if row["subject"] == "check")
                self.assertEqual(
                    dt.datetime.fromisoformat(row["timestamp"]).timestamp(), check["at"]
                )
                json.dumps([entries, scan], allow_nan=False)


class NoClaudeCodeTrailerIsStripped(unittest.TestCase):
    def test_the_last_line_summary_reads_a_codex_trailer_shaped_line_as_the_programs(self) -> None:
        text = "1 failed in 0.2s\n(Bash completed with no output)"
        self.assertEqual("failed", project_context._last_line_summary(["pytest"], text))
        self.assertEqual("", project_context._last_line_summary(["pytest"], text, trailers=False))


class ThePressCarriesCodexTails(CodexChecksTestCase):
    def test_press_checks_reads_a_codex_rollout(self) -> None:
        call = self.rollout.command("pytest -q", "E   assert 1 == 2\n1 failed in 0.2s", exit_code=1)
        self.rollout.save(self.path)
        state = build_runtime_state(self.config, started=START.timestamp())
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            press = project_context.press_checks(self.config, state, "codex", SHORT)
        self.assertIn(call, press.tails)
        self.assertIn("1 failed", press.tails[call])

    def test_another_vendor_gets_no_tail_of_a_call_that_held_a_tier_3_command(self) -> None:
        call = self.rollout.command(
            "python scripts/seed.py && pytest -q", "seeded\n1 failed in 0.2s", exit_code=1
        )
        self.rollout.save(self.path)
        press = project_context.codex_check_press(self.config, str(self.path))
        self.assertIn(call, press.tier3_calls)
        self.assertNotIn(
            call, reading_route.tails_for("claude", "codex", press.tails, press.tier3_calls)
        )
        self.assertIn(
            call, reading_route.tails_for("codex", "codex", press.tails, press.tier3_calls)
        )


class WhereCodexChecksGoOnceCollected(CodexChecksTestCase):
    NOW = START.timestamp() + 3600

    def setUp(self) -> None:
        super().setUp()
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def collect(self) -> dict[str, Any]:
        self.rollout.save(self.path)
        state = build_runtime_state(self.config, started=self.NOW)
        rows = [
            {
                "project": "billing",
                "harness": "codex",
                "sid": SHORT,
                "last_activity": self.NOW,
                "active": True,
                "cwd": str(self.cwd),
            }
        ]
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            return project_context.collect(
                self.config, state, rows, "billing", now=self.NOW, focus=("codex", SHORT)
            )

    def test_the_observed_record_shows_a_codex_failed_check(self) -> None:
        self.rollout.command("pytest -q", "1 failed in 0.2s", exit_code=1)
        context = self.collect()
        facts = [f for f in context["semantic"]["facts"] if f.get("type") == "tool_report"]
        self.assertEqual(["failed"], [f["result"] for f in facts if f["subject"] == "check"])
        self.assertEqual({"harness": "codex", "sid": SHORT}, facts[0]["source_session"])
        scans = context["sources"]["work"]["tool_reports"]
        self.assertEqual([("codex", SHORT)], [(row["harness"], row["sid"]) for row in scans])

    def test_no_codex_check_reaches_session_history(self) -> None:
        self.rollout.command("pytest -q", "1 failed in 0.2s", exit_code=1)
        self.rollout.patch({self.file("src/retry.py"): {"type": "add", "content": "x"}})
        self.collect()
        stored = Path(semantic_history.store_path(self.config))
        text = stored.read_text(encoding="utf-8") if stored.exists() else ""
        self.assertNotIn("tool_report", text)
        self.assertNotIn("src/retry.py", text)
        self.assertNotIn("pytest", text)


class TheGatesAdmitCodex(unittest.TestCase):
    def test_a_codex_check_is_work(self) -> None:
        self.assertEqual(frozenset({"tool_report"}), reading.WORK_EVIDENCE_BY_HARNESS["codex"])
        self.assertIn("codex", reading_route.OUTCOME_HARNESSES)

    def test_a_codex_route_names_tool_output(self) -> None:
        self.assertIn("codex", reading_route.TOOL_OUTPUT_HARNESSES)

    def route(self, provider: str, harness: str) -> reading_route.Route:
        return {  # type: ignore[typeddict-item]
            "harness": harness,
            "provider": provider,
            "destination": "Anthropic",
        }

    def test_the_unasked_lane_sends_no_codex_failure(self) -> None:
        self.assertTrue(reading_route.unasked_sends_failures(self.route("claude", "claude")))
        self.assertFalse(reading_route.unasked_sends_failures(self.route("claude", "codex")))

    def test_both_vendor_sentences_name_codex_tool_output(self) -> None:
        own = reading_route._tool_output_sentence("codex", "codex", "OpenAI")
        other = reading_route._tool_output_sentence("claude", "codex", "Anthropic")
        self.assertIn("Other commands go too, with their output", own)
        self.assertIn("Other commands go with their exit status and no output", other)

    def test_no_codex_sentence_names_what_codex_does_not_record(self) -> None:
        # Codex sends no agent messages, and its record names no pull request or skill.
        for provider, where in (("codex", "OpenAI"), ("claude", "Anthropic"), ("codex", "")):
            with self.subTest(provider=provider, where=where):
                sentence = reading_route._tool_output_sentence(provider, "codex", where)
                self.assertTrue(sentence)
                for word in ("pull request", "skill", "agent messages", "agent's messages"):
                    self.assertNotIn(word, sentence)

    def test_claude_code_sentences_still_name_them(self) -> None:
        sentence = reading_route._tool_output_sentence("claude", "claude", "Anthropic")
        for word in ("pull request", "skills", "agent messages may quote it"):
            self.assertIn(word, sentence)
        self.assertIn(
            "agent's messages may quote it",
            reading_route._tool_output_sentence("claude", "claude", ""),
        )


if __name__ == "__main__":
    unittest.main()
