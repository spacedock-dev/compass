"""The real-session smoke helper: what it refuses, what it prints, and that it leaves nothing running.

Claude and the board are injected, so no test here starts either. The runner tests at the bottom
use real `sh` children, because killing what a command leaves behind is the runner's whole job.
"""

from __future__ import annotations

import io
import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import session_smoke

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "0b8c2f4e-7d1a-4c55-9e3b-5a6f7d8e9f01"

# The shape `claude -p --output-format stream-json --verbose` writes for one typed skill action,
# reduced to the four event types the helper reads. Field names follow a captured run; the text is
# synthetic, because a real `sessions` answer prints other sessions' own words.
SESSIONS_STREAM = "\n".join(
    json.dumps(event)
    for event in (
        {"type": "system", "subtype": "init", "session_id": SESSION_ID, "tools": ["Bash"]},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_01",
                        "name": "Bash",
                        "input": {
                            "command": 'python3 "/t/launch.py" "/t/server.py" --sessions',
                            "description": "List sessions",
                        },
                    }
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_01",
                        "content": "2 sessions are active now.",
                        "is_error": False,
                    }
                ]
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "```\n2 sessions are active now.\n```",
            "permission_denials": [],
            "total_cost_usd": 0.01,
            "session_id": SESSION_ID,
        },
    )
)


def stream_with_denial() -> str:
    lines = SESSIONS_STREAM.splitlines()
    result = json.loads(lines[-1])
    result["permission_denials"] = [
        {
            "tool_name": "Bash",
            "tool_use_id": "toolu_01",
            "tool_input": {"command": 'python3 "/t/launch.py" "/t/server.py" --sessions'},
        }
    ]
    return "\n".join([*lines[:-1], json.dumps(result)])


class FakeWorld:
    """The board and Claude as the helper sees them: commands in, replies out, nothing started."""

    def __init__(self, *, port: int = 4795) -> None:
        self.port = port
        self.calls: list[list[str]] = []
        self.cwds: list[Path | None] = []
        self.answering: set[int] = set()
        self.newest_port: int | None = port
        self.first_prompt = session_smoke.Completed(0, json.dumps({"session_id": SESSION_ID}), "")
        self.stream = SESSIONS_STREAM
        self.action_error: BaseException | None = None
        self.out = io.StringIO()
        self.err = io.StringIO()

    def run(self, argv: Sequence[str], cwd: Path | None, timeout: float) -> session_smoke.Completed:
        del timeout
        self.calls.append(list(argv))
        self.cwds.append(cwd)
        if "--daemon" in argv:
            self.answering.add(self.port)
            return session_smoke.Completed(0, f"Compass running on {self.port}", "")
        if "--stop" in argv:
            self.answering.discard(self.port)
            return session_smoke.Completed(0, "stopped", "")
        if "--resume" in argv:
            if self.action_error is not None:
                raise self.action_error
            return session_smoke.Completed(0, self.stream, "")
        return self.first_prompt

    def deps(self) -> session_smoke.Deps:
        return session_smoke.Deps(
            run=self.run,
            probe=lambda port: port in self.answering,
            newest=lambda _tree: self.newest_port,
            sleep=lambda _seconds: None,
            out=self.out,
            err=self.err,
        )

    def claude_calls(self) -> list[list[str]]:
        return [call for call in self.calls if call and call[0] == "claude"]

    def board_calls(self, flag: str) -> list[list[str]]:
        return [call for call in self.calls if flag in call]


def smoke(world: FakeWorld, *argv: str) -> int:
    return session_smoke.main(["--tree", str(ROOT), *argv], world.deps())


class RefusalTest(unittest.TestCase):
    def test_the_owners_dashboard_port_is_refused_before_anything_starts(self) -> None:
        world = FakeWorld(port=4553)
        code = smoke(world, "--port", "4553", "sessions")
        self.assertEqual(code, 2)
        self.assertEqual(world.calls, [])
        self.assertIn("4553", world.err.getvalue())

    def test_drift_again_is_refused_without_the_spend_flag(self) -> None:
        world = FakeWorld()
        code = smoke(world, "drift again")
        self.assertEqual(code, 2)
        self.assertEqual(world.calls, [])
        self.assertIn("--allow-spend", world.err.getvalue())

    def test_plain_drift_is_refused_too_because_a_fresh_session_has_no_stored_reading(self) -> None:
        world = FakeWorld()
        code = smoke(world, "sessions", "drift")
        self.assertEqual(code, 2)
        self.assertEqual(world.calls, [], "a refusal of one action must stop the whole run")
        self.assertIn("drift", world.err.getvalue())

    def test_an_action_the_skill_does_not_list_is_refused_because_it_would_open_the_dashboard(
        self,
    ) -> None:
        world = FakeWorld()
        code = smoke(world, "--allow-spend", "open")
        self.assertEqual(code, 2)
        self.assertEqual(world.calls, [])
        self.assertIn("open", world.err.getvalue())

    def test_a_board_already_answering_on_the_port_is_left_alone(self) -> None:
        world = FakeWorld()
        world.answering.add(world.port)
        code = smoke(world, "sessions")
        self.assertEqual(code, 2)
        self.assertEqual(world.calls, [], "the helper stops only a board it started")


class SpendClassificationTest(unittest.TestCase):
    def test_the_shipped_table_lists_two_free_actions_and_two_that_spend(self) -> None:
        text = (ROOT / "compass/skills/compass/SKILL.md").read_text(encoding="utf-8")
        table = session_smoke.parse_actions(text)
        self.assertEqual(
            {action: session_smoke.spends(command) for action, command in table.items()},
            {"sessions": False, "sessions waiting": False, "drift": True, "drift again": True},
        )

    def test_a_command_with_any_flag_the_helper_does_not_know_counts_as_spending(self) -> None:
        self.assertTrue(session_smoke.spends('python3 "x/launch.py" "x/server.py" --brand-new'))


class RunTest(unittest.TestCase):
    def test_sessions_prints_the_denials_the_command_and_its_result(self) -> None:
        world = FakeWorld()
        code = smoke(world, "sessions")
        self.assertEqual(code, 0, world.err.getvalue())
        printed = world.out.getvalue()
        self.assertIn("permission_denials: none", printed)
        self.assertIn('Bash: python3 "/t/launch.py" "/t/server.py" --sessions', printed)
        self.assertIn("2 sessions are active now.", printed)
        self.assertIn(SESSION_ID, printed)

    def test_a_denied_command_is_printed_as_a_denial(self) -> None:
        world = FakeWorld()
        world.stream = stream_with_denial()
        code = smoke(world, "sessions")
        self.assertEqual(code, 1, "a denial is the failure this helper exists to show")
        self.assertIn("permission_denials: 1", world.out.getvalue())
        self.assertIn("denied Bash:", world.out.getvalue())

    def test_the_session_is_real_and_the_action_is_typed_into_it(self) -> None:
        world = FakeWorld()
        smoke(world, "--task", "Summarise the README.", "sessions")
        first, action = world.claude_calls()
        plugin = str(ROOT / "compass")
        for call in (first, action):
            self.assertEqual(call[call.index("--plugin-dir") + 1], plugin)
            self.assertEqual(call[call.index("--setting-sources") + 1], "local")
        self.assertEqual(first[first.index("-p") + 1], "Summarise the README.")
        self.assertEqual(first[first.index("--output-format") + 1], "json")
        self.assertEqual(action[action.index("-p") + 1], "/compass:compass sessions")
        self.assertEqual(action[action.index("--resume") + 1], SESSION_ID)
        self.assertEqual(action[action.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", action)
        first_cwd, action_cwd = (
            cwd for call, cwd in zip(world.calls, world.cwds, strict=True) if call[0] == "claude"
        )
        self.assertEqual(first_cwd, action_cwd, "--resume finds a session by its project")

    def test_the_board_is_started_from_the_tree_on_the_spare_port(self) -> None:
        world = FakeWorld()
        smoke(world, "sessions")
        (start,) = world.board_calls("--daemon")
        self.assertEqual(start[1], str(ROOT / "compass/skills/compass/launch.py"))
        self.assertEqual(start[2], str(ROOT / "compass/skills/compass/server.py"))
        self.assertEqual(start[start.index("--port") + 1], "4795")

    def test_spending_actions_run_with_the_flag(self) -> None:
        world = FakeWorld()
        code = smoke(world, "--allow-spend", "drift")
        self.assertEqual(code, 0, world.err.getvalue())
        self.assertEqual(world.claude_calls()[-1][2], "/compass:compass drift")


class CleanupTest(unittest.TestCase):
    def assert_board_stopped(self, world: FakeWorld) -> None:
        (stop,) = world.board_calls("--stop")
        self.assertEqual(stop[stop.index("--port") + 1], str(world.port))

    def test_the_board_is_stopped_after_a_clean_run(self) -> None:
        world = FakeWorld()
        smoke(world, "sessions")
        self.assert_board_stopped(world)

    def test_the_board_is_stopped_when_the_session_cannot_be_created(self) -> None:
        world = FakeWorld()
        world.first_prompt = session_smoke.Completed(1, "", "not logged in")
        code = smoke(world, "sessions")
        self.assertEqual(code, 1)
        self.assertEqual(len(world.claude_calls()), 1)
        self.assert_board_stopped(world)
        self.assertIn("not logged in", world.err.getvalue())

    def test_the_board_is_stopped_when_an_action_times_out(self) -> None:
        world = FakeWorld()
        world.action_error = TimeoutError("claude ran past 300 s")
        code = smoke(world, "sessions")
        self.assertEqual(code, 1)
        self.assert_board_stopped(world)

    def test_the_board_is_stopped_on_an_interrupt(self) -> None:
        world = FakeWorld()
        world.action_error = KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            smoke(world, "sessions")
        self.assert_board_stopped(world)

    def test_a_newer_board_elsewhere_stops_the_run_because_the_client_would_ask_it(self) -> None:
        world = FakeWorld()
        world.newest_port = 4600
        code = smoke(world, "sessions")
        self.assertEqual(code, 1)
        self.assertEqual(world.claude_calls(), [])
        self.assertIn("4600", world.err.getvalue())
        self.assert_board_stopped(world)

    def test_a_board_that_never_answers_is_still_stopped(self) -> None:
        world = FakeWorld()
        deps = world.deps()
        deps = session_smoke.Deps(
            run=deps.run,
            probe=lambda _port: False,
            newest=deps.newest,
            sleep=deps.sleep,
            out=deps.out,
            err=deps.err,
        )
        code = session_smoke.main(["--tree", str(ROOT), "sessions"], deps)
        self.assertEqual(code, 1)
        self.assertEqual(world.claude_calls(), [])
        self.assert_board_stopped(world)


@unittest.skipIf(os.name == "nt", "process groups are POSIX")
class RunnerTest(unittest.TestCase):
    def wait_gone(self, pid: int) -> bool:
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.05)
        return False

    def test_the_runner_kills_what_a_command_left_behind(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            pid_file = Path(scratch) / "pid"
            done = session_smoke.run_command(
                ["sh", "-c", f"sleep 30 & echo $! > {pid_file}; echo ran"], None, 10.0
            )
            self.assertEqual(done.stdout.strip(), "ran")
            pid = int(pid_file.read_text(encoding="utf-8"))
        if not self.wait_gone(pid):
            os.kill(pid, signal.SIGKILL)
            self.fail("a child the command left behind outlived the run")

    def test_the_runner_kills_a_command_that_runs_past_its_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            pid_file = Path(scratch) / "pid"
            with self.assertRaises(TimeoutError):
                session_smoke.run_command(
                    ["sh", "-c", f"echo $$ > {pid_file}; sleep 30"], None, 0.5
                )
            pid = int(pid_file.read_text(encoding="utf-8"))
        if not self.wait_gone(pid):
            os.kill(pid, signal.SIGKILL)
            self.fail("a command past its timeout was left running")

    def test_the_runner_closes_standard_input(self) -> None:
        done = session_smoke.run_command(["sh", "-c", "cat; echo end"], None, 5.0)
        self.assertEqual(done.stdout.strip(), "end", "a child reading stdin must see it closed")


if __name__ == "__main__":
    unittest.main()
