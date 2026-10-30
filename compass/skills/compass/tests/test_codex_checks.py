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
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    ci_read,
    entry_numbers,
    git_status,
    observer,
    project_context,
    reading,
    reading_route,
    semantic_history,
)
from compass_runtime import io as runtime_io
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

SID = "019a2b3c-0000-7000-8000-000000000001"
SHORT = SID[:8]
# A child thread the root spawned, by its own id.
CHILD = "019a2b3c-0000-7000-8000-0000000000ff"
GRANDCHILD = "019a2b3c-0000-7000-8000-0000000000fe"
START = dt.datetime(2026, 10, 30, 3, 0, 0, tzinfo=dt.UTC)
REMOTE = ("github.com", "acme/widgets")
BOUND_GOAL = "https://github.com/acme/widgets/pull/7"
# Text a patch carried. It must never reach anything Compass publishes.
PATCH_BODY = "def handler():  # PATCHBODYMARKER"
PATCH_DIFF = "@@ -1 +1 @@\n-old\n+DIFFBODYMARKER"


class Rollout:
    """A Codex rollout in the recorded shapes, one item at a time."""

    def __init__(
        self,
        cwd: Path,
        *,
        version: str = "0.164.0",
        thread: str = SID,
        parent: str | None = None,
        start_ms: int | None = None,
    ) -> None:
        self.cwd = str(cwd)
        self.thread = thread
        self.ms = int(START.timestamp() * 1000) if start_ms is None else start_ms
        self.items = 0
        meta: dict[str, Any] = {
            "id": thread,
            "session_id": SID,
            "timestamp": self._iso(),
            "cwd": self.cwd,
            "originator": "codex_cli_rs",
            "cli_version": version,
        }
        if parent is not None:
            # A child thread's head, as `transcripts.codex_meta` reads it: the root's id as its
            # `session_id`, and the thread that spawned it.
            meta["thread_source"] = "subagent"
            meta["source"] = {
                "subagent": {"thread_spawn": {"parent_thread_id": parent, "agent_path": "worker"}}
            }
        self.rows: list[dict[str, Any]] = [
            {"timestamp": self._iso(), "type": "session_meta", "payload": meta}
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

    def item(self, item: dict[str, Any], *, took_ms: int = 1000, item_id: str | None = None) -> str:
        self.items += 1
        item_id = item_id or f"item_{self.items:03d}"
        started = self._tick()
        completed = started + took_ms
        self.ms = completed
        self.rows.append(
            {
                "timestamp": self._iso(),
                "type": "event_msg",
                "payload": {
                    "type": "item_completed",
                    "thread_id": self.thread,
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
                    "thread_id": self.thread,
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
        item_id: str | None = None,
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
            },
            item_id=item_id,
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

    def subagent(self, thread: str = CHILD) -> str:
        return self.item(
            {
                "type": "SubAgentActivity",
                "agent_thread_id": thread,
                "agent_path": "worker",
                "kind": "started",
                "model": None,
                "reasoning_effort": None,
            }
        )

    def function_call(self, name: str, arguments: dict[str, Any] | str) -> str:
        self._tick()
        call_id = f"call_{len(self.rows)}"
        self.rows.append(
            {
                "timestamp": self._iso(),
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": name,
                    "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
                    "call_id": call_id,
                },
            }
        )
        return call_id

    def exec_script(self, script: str) -> str:
        """An `exec` custom tool call: a script that calls Codex's tools, as 58,345 local calls are."""
        self._tick()
        call_id = f"call_{len(self.rows)}"
        self.rows.append(
            {
                "timestamp": self._iso(),
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "input": script,
                    "call_id": call_id,
                    "status": "completed",
                },
            }
        )
        return call_id

    def output(self, call_id: str, output: Any, *, custom: bool = False) -> None:
        self._tick()
        self.rows.append(
            {
                "timestamp": self._iso(),
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output" if custom else "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            }
        )

    def yielded(self, script: str, session: int = 3) -> str:
        """An `exec_command` left running: Codex's own line says so, and no item is written yet."""
        call_id = self.function_call("exec_command", {"cmd": script, "yield_time_ms": 1000})
        self.output(
            call_id,
            "Chunk ID: 1a2b3c\nWall time: 1.0 seconds\n"
            f"Process running with session ID {session}\nOriginal token count: 0\nOutput:\n",
        )
        return call_id

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(row) for row in self.rows) + "\n", encoding="utf-8")
        # A rollout's file changes when its newest record is written, which is what an unread
        # child's horizon is read from.
        os.utime(path, (self.ms / 1000, self.ms / 1000))


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


class ASubagentNobodyLookedForIsUnread(CodexChecksTestCase):
    """A caller that passes no child rollouts did not look, so any subagent the read names is
    unread."""

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


class ASubagentsWorkIsReadFromItsOwnRollout(CodexChecksTestCase):
    """A child thread writes its commands into its own rollout. Each one the store holds for the
    session is read through the same adapter, labelled as a subagent's, and a pass is complete only
    when every child was read."""

    def setUp(self) -> None:
        super().setUp()
        self.children: list[Path] = []

    def child(self, thread: str = CHILD, parent: str = SID, **kwargs: Any) -> Rollout:
        kwargs.setdefault("start_ms", self.rollout.ms)
        return Rollout(self.cwd, thread=thread, parent=parent, **kwargs)

    def keep(self, child: Rollout) -> Path:
        path = self.path.parent / f"rollout-2026-10-30T03-00-00-{child.thread}.jsonl"
        child.save(path)
        self.children.append(path)
        return path

    def read(self, max_bytes: int | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.rollout.save(self.path)
        return project_context.codex_tool_reports(
            self.config,
            str(self.path),
            SHORT,
            goal_texts=self.goal_texts,
            max_bytes=max_bytes,
            child_paths=[str(path) for path in self.children],
        )

    def check(self, title: str) -> dict[str, Any]:
        found = [row for row in self.of("check") if row["title"] == title]
        self.assertEqual(1, len(found), self.of("check"))
        return found[0]

    def test_a_childs_failing_test_is_listed_as_subagent_work(self) -> None:
        self.rollout.subagent()
        child = self.child()
        child.command("pytest -q", "E   assert 1 == 2\n1 failed in 0.2s", exit_code=1)
        self.keep(child)
        check = self.only_check()
        self.assertEqual("failed", check["result"])
        self.assertEqual("subagent", check["worker_kind"])
        self.assertEqual("Codex subagent command and its exit status", check["source"])

    def test_a_childs_patch_is_a_written_file_labelled_as_its(self) -> None:
        self.rollout.subagent()
        child = self.child()
        child.patch({self.file("src/retry.py"): {"type": "add", "content": PATCH_BODY}})
        self.keep(child)
        (write,) = self.of("write")
        self.assertEqual("subagent", write["worker_kind"])
        self.assertEqual("Codex subagent apply_patch call", write["source"])

    def test_a_pass_is_complete_when_every_child_was_read(self) -> None:
        self.rollout.subagent()
        child = self.child()
        child.command("ls -la", "total 0")
        self.keep(child)
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(False, self.only_check()["read_incomplete"])
        scan = self.read()[1]
        self.assertEqual(1, scan["subagent_transcripts"])
        self.assertEqual(0, scan["subagent_transcripts_unread"])

    def test_a_named_child_with_no_rollout_still_marks_it(self) -> None:
        self.rollout.subagent()
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(True, self.only_check()["read_incomplete"])
        self.assertEqual(1, self.read()[1]["subagent_transcripts_unread"])

    def test_more_spawns_than_children_found_still_marks_it(self) -> None:
        self.rollout.function_call("spawn_agent", {"message": "a"})
        self.rollout.function_call("spawn_agent", {"message": "b"})
        child = self.child()
        child.command("ls -la", "total 0")
        self.keep(child)
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(True, self.only_check()["read_incomplete"])

    def test_a_child_on_a_version_with_no_exit_status_is_unread(self) -> None:
        self.rollout.subagent()
        child = self.child(version="0.148.0")
        child.command("sed -i s/a/b/ src/x.py", "")
        self.keep(child)
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(True, self.only_check()["read_incomplete"])
        self.assertEqual(1, self.read()[1]["subagent_transcripts_unread"])

    def test_a_grandchild_is_read_as_a_subagent_too(self) -> None:
        self.rollout.subagent()
        child = self.child()
        child.subagent(GRANDCHILD)
        self.keep(child)
        grandchild = self.child(thread=GRANDCHILD, parent=CHILD)
        grandchild.command("ruff check .", "src/x.py:1:1: F401 unused", exit_code=1)
        self.keep(grandchild)
        check = self.check("ruff check .")
        self.assertEqual("failed", check["result"])
        self.assertEqual("subagent", check["worker_kind"])

    def test_a_childs_write_after_a_root_pass_ages_it(self) -> None:
        self.rollout.subagent()
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        child = self.child()
        child.command("sed -i s/a/b/ src/retry.py", "")
        self.keep(child)
        check = self.only_check()
        self.assertIs(True, check["before_last_change"])
        self.assertIs(True, check["changed_after"])

    def test_the_same_item_id_in_two_rollouts_keeps_each_its_own_result(self) -> None:
        self.rollout.subagent()
        self.rollout.command("pytest -q", "3 passed in 0.1s", item_id="item_shared")
        child = self.child()
        child.command(
            "ruff check .", "F401 unused\nFound 1 error.", exit_code=1, item_id="item_shared"
        )
        self.keep(child)
        self.assertEqual("passed", self.check("pytest -q")["result"])
        self.assertEqual("failed", self.check("ruff check .")["result"])

    def test_a_child_spawned_before_a_clipped_root_window_is_still_counted(self) -> None:
        # The spawn and every call naming the child are outside the window read; the child is found
        # in the store all the same. Its rollout is not read in the spent budget, and it was still
        # writing after the pass, so the pass is incomplete (the 2026-10-30 arbiter's S3).
        self.rollout.subagent()
        for i in range(60):
            self.rollout.command(f"ls -la dir{i}", "x" * 400)
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        child = self.child()
        child.command("sed -i s/a/b/ src/retry.py", "")
        self.keep(child)
        entries, scan = self.read(max_bytes=16 * 1024)
        (check,) = [row for row in entries if row["subject"] == "check"]
        self.assertIs(True, check["read_incomplete"])
        self.assertEqual(1, scan["subagent_transcripts_unread"])

    def test_a_childs_unreturned_script_ages_a_later_root_pass(self) -> None:
        # The script sent input and never returned, so its end is the newest record read in the
        # root or any child, never the newest in the child alone (the 2026-10-30 arbiter's E1).
        self.rollout.subagent()
        child = self.child()
        child.exec_script('const r = await tools.write_stdin({session_id:3,chars:"y\\n"});\n')
        self.keep(child)
        self.rollout.ms = child.ms + 30000
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.assertIs(True, self.only_check()["changed_after"])

    def test_a_second_rollout_of_a_thread_already_read_is_unread(self) -> None:
        # Two files whose names end in one thread id, in different day folders: the newer is read,
        # and the older is counted unread rather than merged over it (the arbiter's S2, A2).
        self.rollout.subagent()
        newer = self.child()
        newer.command("pytest -q", "E   assert 1 == 2\n1 failed in 0.2s", exit_code=1)
        self.keep(newer)
        older = self.child(start_ms=self.rollout.ms - 86_400_000)
        older.command("cat notes.txt", "READONLYOUTPUTMARKER")
        path = self.path.parent.parent / "29" / f"rollout-2026-10-29T03-00-00-{CHILD}.jsonl"
        older.save(path)
        self.children.append(path)
        entries, scan = self.read()
        (check,) = [row for row in entries if row["subject"] == "check"]
        self.assertEqual(("pytest -q", "failed"), (check["title"], check["result"]))
        self.assertEqual(
            (1, 1), (scan["subagent_transcripts"], scan["subagent_transcripts_unread"])
        )
        press = project_context.codex_check_press(
            self.config, str(self.path), child_paths=[str(path) for path in self.children]
        )
        self.assertNotIn("READONLYOUTPUTMARKER", json.dumps([press.tails, entries]))

    def test_a_root_id_shaped_as_a_childs_keeps_the_roots_result(self) -> None:
        # A root item id written as `<child>/item_001` meets the child's prefixed `item_001`: the
        # first read is kept and the child's is an unread call (the arbiter's S2, B).
        self.rollout.subagent()
        self.rollout.command(
            "pytest -q",
            "E   assert 1 == 2\n1 failed in 0.2s",
            exit_code=1,
            item_id=f"{CHILD}/item_001",
        )
        child = self.child()
        child.command("cat notes.txt", "READONLYOUTPUTMARKER")
        self.keep(child)
        entries, scan = self.read()
        self.assertEqual("failed", self.check("pytest -q")["result"])
        self.assertEqual(1, scan["unread_calls"])
        press = project_context.codex_check_press(
            self.config, str(self.path), child_paths=[str(path) for path in self.children]
        )
        self.assertIn("1 failed", press.tails[f"{CHILD}/item_001"])
        self.assertNotIn("READONLYOUTPUTMARKER", json.dumps([press.tails, entries]))

    def test_the_press_carries_a_childs_tail(self) -> None:
        self.rollout.subagent()
        child = self.child()
        child.command("pytest -q", "E   assert 1 == 2\n1 failed in 0.2s", exit_code=1)
        child_path = self.keep(child)
        self.rollout.save(self.path)
        press = project_context.codex_check_press(
            self.config, str(self.path), child_paths=[str(child_path)]
        )
        self.assertTrue(any("1 failed" in tail for tail in press.tails.values()), press.tails)


class ACommandStillRunningAgesAPass(CodexChecksTestCase):
    """Codex writes a command's item only once it ends. Its own header saying a command is still
    running, with no item for it, is a change dated at that session's latest such header, as a
    Claude Code background launch is dated at its launch: it ages a pass that began at or before
    then, and none after. A printed copy of the line in a command's output adds nothing."""

    PRINTED = (
        "Chunk ID: 1a2b3c\nWall time: 0.1 seconds\nProcess exited with code 0\n"
        "Original token count: 5\nOutput:\n"
    )

    def test_a_pass_followed_by_a_command_left_running_is_changed_after(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        self.rollout.yielded("npm run build -- --watch")
        check = self.only_check()
        self.assertIs(True, check["changed_after"])
        self.assertIs(True, check["before_last_change"])

    def test_a_pass_after_the_last_header_is_not_aged_by_it(self) -> None:
        self.rollout.yielded("npm run dev")
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        check = self.only_check()
        self.assertIs(False, check["changed_after"])
        self.assertEqual(1, self.read()[1]["unread_calls"])

    def test_a_poll_that_reports_it_still_running_moves_the_one_call_later(self) -> None:
        self.rollout.yielded("npm run dev", session=3)
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        poll = self.rollout.function_call("write_stdin", {"session_id": 3, "chars": ""})
        self.rollout.output(
            poll,
            "Chunk ID: 4d5e6f\nWall time: 5.0 seconds\nProcess running with session ID 3\n"
            "Original token count: 0\nOutput:\n",
        )
        self.assertIs(True, self.only_check()["changed_after"])
        self.assertEqual(1, self.read()[1]["unread_calls"])

    def test_a_printed_copy_of_the_line_adds_nothing(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        call = self.rollout.function_call("exec_command", {"cmd": "cat build.log"})
        self.rollout.output(call, self.PRINTED + "Process running with session ID 7\n")
        found = project_context.codex_calls(self.rollout.rows)
        self.assertEqual([], [call for call in found.calls if call[2].startswith("running:")])
        self.assertIs(False, self.only_check()["changed_after"])
        self.assertEqual(0, self.read()[1]["unread_calls"])

    def test_twenty_thousand_printed_lines_are_read_in_linear_time(self) -> None:
        # Measured on the reviewed tip: 20,000 printed lines beside 8,000 commands took 16 s to read.
        call = self.rollout.function_call("exec_command", {"cmd": "cat build.log"})
        self.rollout.output(call, self.PRINTED + "Process running with session ID 7\n" * 20000)
        for i in range(2000):
            self.rollout.command(f"ls dir{i}", "x")
        began = time.perf_counter()
        found = project_context.codex_calls(self.rollout.rows)
        self.assertLess(time.perf_counter() - began, 1.0)
        self.assertEqual([], [call for call in found.calls if call[2].startswith("running:")])


class InputInsideAnExecScriptAgesAPass(CodexChecksTestCase):
    """An `exec` script calls Codex's tools itself. A `write_stdin` in it that sends input is the
    input a top-level call would send; one whose `chars` is an empty string only polls."""

    def script(self, call: str) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s")
        call_id = self.rollout.exec_script(f"const r = await tools.{call};\ntext(r.output);\n")
        self.rollout.output(call_id, [{"type": "input_text", "text": "done"}], custom=True)

    def test_input_sent_in_a_script_ages_a_pass(self) -> None:
        self.script('write_stdin({session_id:3,chars:"sed -i s/a/b/ x\\n",yield_time_ms:1000})')
        self.assertIs(True, self.only_check()["changed_after"])

    def test_input_from_a_variable_ages_it(self) -> None:
        self.script("write_stdin({session_id, chars: line, yield_time_ms: 1000})")
        self.assertIs(True, self.only_check()["changed_after"])

    def test_a_call_whose_arguments_are_not_an_object_literal_ages_it(self) -> None:
        self.script("write_stdin(args)")
        self.assertIs(True, self.only_check()["changed_after"])

    def test_a_poll_does_not(self) -> None:
        for call in (
            'write_stdin({session_id:3,chars:"",yield_time_ms:1000})',
            'write_stdin({"session_id":3,"chars":"","yield_time_ms":1000,"max_output_tokens":9})',
            "write_stdin({ session_id: 3, chars: '', yield_time_ms: 1000 })",
        ):
            with self.subTest(call=call):
                self.setUp()
                self.script(call)
                check = self.only_check()
                self.assertIs(False, check["changed_after"])
                self.assertEqual(0, self.read()[1]["unread_calls"])

    def test_one_input_among_polls_ages_it(self) -> None:
        self.script(
            'write_stdin({session_id:3,chars:""}); '
            'await tools.write_stdin({session_id:3,chars:"y\\n"})'
        )
        self.assertIs(True, self.only_check()["changed_after"])


class ADuplicatedItemIdIsRefused(CodexChecksTestCase):
    """A second item under an id already read never replaces the first's result: a read-only
    command's output would otherwise travel as a check's tail."""

    def test_a_later_item_under_a_checks_id_never_becomes_its_tail(self) -> None:
        self.rollout.command(
            "pytest -q", "E   assert 1 == 2\n1 failed in 0.2s", exit_code=1, item_id="dup"
        )
        self.rollout.command("cat notes.txt", "PRIVATEVALUEMARKER\nnothing failed", item_id="dup")
        self.rollout.save(self.path)
        press = project_context.codex_check_press(self.config, str(self.path))
        self.assertIn("dup", press.tails)
        self.assertIn("1 failed", press.tails["dup"])
        self.assertNotIn("PRIVATEVALUEMARKER", json.dumps([press.tails, self.read()]))
        self.assertEqual("failed", self.only_check()["result"])

    def test_the_refused_item_ages_every_earlier_pass(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s", item_id="dup")
        self.rollout.command("ls -la", "total 0", item_id="dup")
        check = self.only_check()
        self.assertIs(True, check["changed_after"])
        self.assertEqual(1, self.read()[1]["unread_calls"])


class ASubagentsCheckReachesThePageFromTheStore(CodexChecksTestCase):
    """The children are found as the collector finds them: every rollout in the Codex store whose
    head names the root's session, a grandchild included, and nothing else."""

    NOW = START.timestamp() + 3600

    def setUp(self) -> None:
        super().setUp()
        self.store = Path(self.config.store_roots["codex.sessions"][0]) / "2026" / "10" / "30"
        self.path = self.store / f"rollout-2026-10-30T03-00-00-{SID}.jsonl"
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def child(self, thread: str, parent: str = SID, folder: str = "30") -> Path:
        child = Rollout(self.cwd, thread=thread, parent=parent, start_ms=self.rollout.ms)
        child.command("pytest -q", "E   assert 1 == 2\n1 failed in 0.2s", exit_code=1)
        path = self.store.parent / folder / f"rollout-2026-10-30T03-00-00-{thread}.jsonl"
        child.save(path)
        return path

    def test_every_descendant_and_nothing_else_is_found(self) -> None:
        self.rollout.subagent()
        self.rollout.save(self.path)
        child = self.child(CHILD)
        grandchild = self.child(GRANDCHILD, parent=CHILD, folder="31")
        other = Rollout(self.cwd, thread="019a2b3c-0000-7000-8000-0000000000aa")
        other.rows[0]["payload"]["session_id"] = "019a2b3c-0000-7000-8000-0000000000aa"
        other.save(
            self.store / "rollout-2026-10-30T03-00-00-019a2b3c-0000-7000-8000-0000000000aa.jsonl"
        )
        state = build_runtime_state(self.config, started=self.NOW)
        found = observer.codex_child_rollouts(self.config, state, str(self.path))
        self.assertEqual(sorted([str(child), str(grandchild)]), sorted(found))

    def test_a_child_rollout_is_no_root_of_its_own(self) -> None:
        self.rollout.save(self.path)
        child = self.child(CHILD)
        state = build_runtime_state(self.config, started=self.NOW)
        self.assertEqual([], observer.codex_child_rollouts(self.config, state, str(child)))

    def test_the_observed_record_lists_a_subagents_failed_check(self) -> None:
        self.rollout.subagent()
        self.rollout.command("ls -la", "total 0")
        self.rollout.save(self.path)
        self.child(CHILD)
        state = build_runtime_state(self.config, started=self.NOW)
        rows = [
            {
                "project": "billing",
                "harness": "codex",
                "sid": SID,
                "last_activity": self.NOW,
                "active": True,
                "cwd": str(self.cwd),
            }
        ]
        context = project_context.collect(
            self.config, state, rows, "billing", now=self.NOW, focus=("codex", SID)
        )
        facts = [f for f in context["semantic"]["facts"] if f.get("type") == "tool_report"]
        (check,) = [f for f in facts if f["subject"] == "check"]
        self.assertEqual("failed", check["result"])
        self.assertEqual("subagent", check["worker_kind"])
        self.assertEqual("Codex subagent command and its exit status", check["evidence"]["source"])
        (scan,) = context["sources"]["work"]["tool_reports"]
        self.assertEqual(1, scan["subagent_transcripts"])
        self.assertEqual(0, scan["subagent_transcripts_unread"])

    def test_the_press_reads_the_childs_tail(self) -> None:
        self.rollout.subagent()
        self.rollout.save(self.path)
        self.child(CHILD)
        state = build_runtime_state(self.config, started=self.NOW)
        press = project_context.press_checks(self.config, state, "codex", SID)
        self.assertTrue(any("1 failed" in tail for tail in press.tails.values()), press.tails)


class TheCheckReadIsKeptWhileNothingItReadsMoves(CodexChecksTestCase):
    """A second collect over unchanged rollouts reads none of them; a changed size or mtime of the
    root or of any child, or the cache's age, makes the read again."""

    def setUp(self) -> None:
        super().setUp()
        self.store = Path(self.config.store_roots["codex.sessions"][0]) / "2026" / "10" / "30"
        self.path = self.store / f"rollout-2026-10-30T03-00-00-{SID}.jsonl"
        self.rollout.command("pytest -q", "1 passed in 0.1s")
        self.rollout.subagent()
        self.rollout.save(self.path)
        self.child_path = self.store / f"rollout-2026-10-30T03-00-00-{CHILD}.jsonl"
        child = Rollout(self.cwd, thread=CHILD, parent=SID, start_ms=self.rollout.ms)
        child.command("pytest -q", "E   assert 1 == 2\n1 failed in 0.2s", exit_code=1)
        child.save(self.child_path)
        self.state = build_runtime_state(self.config, started=START.timestamp())
        self.clock = [1000.0]
        patcher = mock.patch.object(time, "monotonic", lambda: self.clock[0])
        patcher.start()
        self.addCleanup(patcher.stop)

    def reports(self, **kwargs: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return project_context.codex_tool_reports(
            self.config,
            str(self.path),
            SHORT,
            goal_texts=self.goal_texts,
            child_paths=observer.codex_child_rollouts(self.config, self.state, str(self.path)),
            cache=self.state.codex_check_cache,
            **kwargs,
        )

    def counted(self, call: Any) -> int:
        with mock.patch.object(
            runtime_io,
            "scan_reverse_lines",
            wraps=runtime_io.scan_reverse_lines,
        ) as scans:
            call()
        return scans.call_count

    def test_a_second_read_of_unchanged_rollouts_reads_none_of_them(self) -> None:
        first = self.counted(self.reports)
        again = self.counted(self.reports)
        self.assertEqual(2, first)  # the root and its one child
        self.assertEqual(0, again)

    def test_the_kept_read_is_the_read(self) -> None:
        fresh = project_context.codex_tool_reports(
            self.config,
            str(self.path),
            SHORT,
            goal_texts=self.goal_texts,
            child_paths=[str(self.child_path)],
        )
        self.reports()
        self.assertEqual(fresh, self.reports())

    def test_a_cache_hit_does_not_carry_one_callers_window_to_the_next(self) -> None:
        self.reports()
        _rows, windowed = self.reports(window_start=0.0)
        _rows, plain = self.reports()
        self.assertIn("window_start", windowed)
        self.assertNotIn("window_start", plain)

    def test_a_cache_hit_takes_the_pages_current_message_index(self) -> None:
        self.reports()
        with mock.patch.object(entry_numbers, "tool_positions", return_value={}) as positions:
            self.reports(index_provider=lambda: "the index")
        self.assertEqual("the index", positions.call_args.args[0])

    def test_an_appended_root_is_read_again(self) -> None:
        self.reports()
        self.rollout.command("pytest -q tests/test_two.py", "2 passed")
        self.rollout.save(self.path)
        self.assertEqual(2, self.counted(self.reports))

    def test_a_child_whose_size_changed_is_read_again(self) -> None:
        self.reports()
        with self.child_path.open("a", encoding="utf-8") as handle:
            handle.write("\n")
        self.assertEqual(2, self.counted(self.reports))

    def test_a_child_whose_mtime_alone_changed_is_read_again(self) -> None:
        self.reports()
        stat = self.child_path.stat()
        os.utime(self.child_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
        self.assertEqual(2, self.counted(self.reports))

    def test_a_child_gained_is_read_again(self) -> None:
        self.reports()
        extra = "019a2b3c-0000-7000-8000-0000000000fd"
        child = Rollout(self.cwd, thread=extra, parent=SID, start_ms=self.rollout.ms)
        child.command("ruff check", "ok")
        child.save(self.store / f"rollout-2026-10-30T03-00-00-{extra}.jsonl")
        self.assertEqual(3, self.counted(self.reports))

    def test_a_read_older_than_the_window_is_made_again(self) -> None:
        self.reports()
        self.clock[0] += project_context.CODEX_CHECK_CACHE_SEC + 1
        self.assertEqual(2, self.counted(self.reports))

    def test_a_different_bound_is_a_different_read(self) -> None:
        self.reports()
        self.assertEqual(2, self.counted(lambda: self.reports(listed_cap=1)))

    def test_the_cache_is_bounded(self) -> None:
        for index in range(project_context.CODEX_CHECK_CACHE_ENTRIES + 10):
            project_context.codex_tool_reports(
                self.config,
                str(self.path),
                SHORT,
                goal_texts=(f"goal {index}",),
                cache=self.state.codex_check_cache,
            )
        self.assertEqual(
            project_context.CODEX_CHECK_CACHE_ENTRIES, len(self.state.codex_check_cache)
        )

    def test_no_cache_reads_every_time(self) -> None:
        def bare() -> Any:
            return project_context.codex_tool_reports(self.config, str(self.path), SHORT)

        self.assertEqual(1, self.counted(bare))
        self.assertEqual(1, self.counted(bare))

    def test_the_press_is_kept_the_same_way(self) -> None:
        def press() -> Any:
            return project_context.codex_check_press(
                self.config,
                str(self.path),
                child_paths=[str(self.child_path)],
                cache=self.state.codex_check_cache,
            )

        self.assertEqual(2, self.counted(press))
        self.assertEqual(0, self.counted(press))


class ChildDiscoveryListsNoStoreWhileTheStoreStandsStill(CodexChecksTestCase):
    """`observer.codex_child_rollouts` globs the store when a day folder is made or gains a file,
    not for every session on every collect."""

    def setUp(self) -> None:
        super().setUp()
        self.store = Path(self.config.store_roots["codex.sessions"][0]) / "2026" / "10" / "30"
        self.path = self.store / f"rollout-2026-10-30T03-00-00-{SID}.jsonl"
        self.rollout.save(self.path)
        self.state = build_runtime_state(self.config, started=START.timestamp())

    def child(self, thread: str, folder: str = "30") -> Path:
        child = Rollout(self.cwd, thread=thread, parent=SID, start_ms=self.rollout.ms)
        path = self.store.parent / folder / f"rollout-2026-10-30T03-00-00-{thread}.jsonl"
        child.save(path)
        return path

    def found(self) -> list[str]:
        return observer.codex_child_rollouts(self.config, self.state, str(self.path))

    def globs(self) -> int:
        with mock.patch.object(runtime_io, "glob_stores", wraps=runtime_io.glob_stores) as globbed:
            self.found()
        return globbed.call_count

    def test_an_unchanged_store_is_listed_once(self) -> None:
        kept = self.child(CHILD)
        self.assertEqual([str(kept)], self.found())
        self.assertEqual(0, self.globs())
        self.assertEqual([str(kept)], self.found())

    def test_a_child_added_to_a_known_day_is_found(self) -> None:
        self.found()
        grand = self.child(GRANDCHILD)
        self.assertEqual([str(grand)], self.found())

    def test_a_child_added_in_a_new_day_folder_is_found(self) -> None:
        self.found()
        grand = self.child(GRANDCHILD, folder="31")
        self.assertEqual([str(grand)], self.found())

    def test_a_child_removed_is_gone(self) -> None:
        gone = self.child(CHILD)
        self.assertEqual([str(gone)], self.found())
        gone.unlink()
        self.assertEqual([], self.found())

    def test_another_roots_child_is_not_ours(self) -> None:
        other = "019a2b3c-0000-7000-8000-0000000000aa"
        child = Rollout(self.cwd, thread=CHILD, parent=other, start_ms=self.rollout.ms)
        child.rows[0]["payload"]["session_id"] = other
        child.save(self.store / f"rollout-2026-10-30T03-00-00-{CHILD}.jsonl")
        self.assertEqual([], self.found())


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
