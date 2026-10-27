"""A Codex `/goal` is read as the session's goal, from the records Codex writes into its rollout.

The fixtures are hand-written in the shapes recorded in
`docs/captures/codex/goal-0.164.0-macos.jsonl`, with placeholder prose only. Measured there: a
set, an edit, a pause, a resume and the new goal of a replace each write a `thread_goal_updated`
event carrying the objective and its `createdAt`, which an edit keeps; a clear writes only a
`user.goal` message saying `User cleared the goal.`, which Codex also writes for a clear with no
goal and before a goal set over a completed one; a goal the model creates writes no event; and an
objective over 4,000 characters is stored as a fixed sentence pointing at a file.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import claude_data, records

from .fixtures import _iso, _jsonl
from .support import HarnessContractTestCase, make_runtime

OBJECTIVE = "the placeholder parser handles every token type and its tests pass"
EDITED = "the placeholder parser handles every token type and its tests pass on CI"
LATER = "the placeholder lexer is split into modules under 300 lines"
T0 = 1_780_000_000.0


def goal_event(
    when: float, created: float, objective: str = OBJECTIVE, status: str = "active"
) -> dict[str, Any]:
    return {
        "type": "event_msg",
        "timestamp": _iso(when),
        "payload": {
            "type": "thread_goal_updated",
            "threadId": "thread",
            "goal": {
                "threadId": "thread",
                "objective": objective,
                "status": status,
                "tokensUsed": 0,
                "timeUsedSeconds": 0,
                "createdAt": int(created),
                "updatedAt": int(when),
            },
        },
    }


def goal_line(when: float, *lines: str) -> dict[str, Any]:
    body = "\n".join(lines)
    return {
        "type": "response_item",
        "timestamp": _iso(when),
        "payload": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": f'<codex_internal_context source="user_goal">\n{body}\n'
                    "</codex_internal_context>",
                }
            ],
            "internal_chat_message_metadata_passthrough": {"content_item_kinds": ["user.goal"]},
        },
    }


def set_goal(when: float, objective: str = OBJECTIVE) -> list[dict[str, Any]]:
    """What `/goal <objective>` writes: the restating message, then the event."""
    return [
        goal_line(when, f'User set the goal: "{objective}"', 'User set goal status: "active".'),
        goal_event(when, when, objective),
    ]


CLEARED = claude_data.CODEX_GOAL_CLEARED


def read(rollout: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    with tempfile.TemporaryDirectory() as home:
        config, state = make_runtime()
        path = Path(home, "rollout.jsonl")
        _jsonl(path, rollout, T0)
        goal = claude_data.session_goal(config, state, str(path), "codex")
        return goal, claude_data.session_goal_cleared(state, str(path))


class TheCodexGoalReadFromTheRolloutTest(unittest.TestCase):
    def test_a_set_publishes_the_objective_at_the_moment_it_was_set(self) -> None:
        self.assertEqual(({"text": OBJECTIVE, "at": T0 + 5}, None), read(set_goal(T0 + 5)))

    def test_a_pause_and_a_resume_keep_the_goal_as_it_was(self) -> None:
        goal, _ = read(
            [
                *set_goal(T0 + 5),
                goal_line(T0 + 20, 'User set goal status: "paused".'),
                goal_event(T0 + 20, T0 + 5, status="paused"),
                goal_event(T0 + 40, T0 + 5),
            ]
        )
        self.assertEqual({"text": OBJECTIVE, "at": T0 + 5}, goal)

    def test_an_edit_is_the_same_goal_in_new_words_not_a_replacement(self) -> None:
        goal, _ = read([*set_goal(T0 + 5), goal_event(T0 + 20, T0 + 5, EDITED)])
        self.assertEqual({"text": EDITED, "at": T0 + 5}, goal)

    def test_a_clear_ends_the_goal_and_is_published_beside_it(self) -> None:
        self.assertEqual(
            (None, {"at": T0 + 30}), read([*set_goal(T0 + 5), goal_line(T0 + 30, CLEARED)])
        )

    def test_a_clear_with_no_goal_held_is_not_a_clear(self) -> None:
        self.assertEqual((None, None), read([goal_line(T0 + 30, CLEARED)]))

    def test_a_replace_holds_the_new_goal(self) -> None:
        goal, cleared = read(
            [*set_goal(T0 + 5), goal_line(T0 + 30, CLEARED), *set_goal(T0 + 30, LATER)]
        )
        self.assertEqual({"text": LATER, "at": T0 + 30}, goal)
        self.assertIsNone(cleared)

    def test_a_goal_the_model_created_is_not_the_readers(self) -> None:
        created = {
            "type": "response_item",
            "timestamp": _iso(T0 + 5),
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "input": "await tools.create_goal({objective: 'a goal of the model's words'})",
            },
        }
        self.assertEqual((None, None), read([created]))

    def test_the_pointer_to_a_long_objective_is_not_a_goal(self) -> None:
        pointer = f"{claude_data.CODEX_GOAL_FILE_POINTER}/placeholder/goal-objective.md before continuing."
        goal, _ = read([goal_event(T0 + 5, T0 + 5, pointer)])
        self.assertIsNone(goal)

    def test_an_event_without_a_set_time_is_ignored(self) -> None:
        for created in (None, "x", True, 0):
            with self.subTest(created=created):
                event = goal_event(T0 + 5, T0 + 5)
                event["payload"]["goal"]["createdAt"] = created
                self.assertEqual((None, None), read([event]))


class TheGoalMessageIsCodexsOwnWrapperTest(unittest.TestCase):
    def test_no_goal_message_reads_as_words_the_reader_typed(self) -> None:
        for lines in (
            ('User set the goal: "x"', 'User set goal status: "active".'),
            (CLEARED,),
        ):
            with self.subTest(lines=lines):
                text = goal_line(T0, *lines)["payload"]["content"][0]["text"]
                self.assertTrue(records.injected_prompt(text, "codex"))


def _store(rollout: list[dict[str, Any]]) -> Any:
    def build(root: Path, when: float, sid: str, _title: str) -> dict[str, str]:
        _jsonl(
            root / "2024" / "01" / "02" / "rollout-1.jsonl",
            [
                {
                    "type": "session_meta",
                    "timestamp": _iso(when),
                    "payload": {"id": sid, "cwd": "/w/proj"},
                },
                {
                    "type": "event_msg",
                    "timestamp": _iso(when),
                    "payload": {"type": "task_started", "started_at": when},
                },
                *rollout,
            ],
            when,
        )
        return {"CODEX_SESSIONS_DIR": str(root)}

    return build


class TheCodexCollectorPublishesTheGoalTest(HarnessContractTestCase):
    def row(self, rollout: list[dict[str, Any]]) -> dict[str, Any]:
        (row,) = self.sessions_for(self.collect(_store(rollout), when=self.NOW), "codex")
        return row

    def test_a_goal_only_session_publishes_its_goal_and_is_named_by_it(self) -> None:
        when = self.NOW - 100
        row = self.row(set_goal(when + 5))
        self.assertEqual({"text": OBJECTIVE, "at": when + 5}, row["session_goal"])
        self.assertEqual(OBJECTIVE, row["title"])
        self.assertFalse(row.get("first_prompt"))

    def test_a_cleared_goal_publishes_the_clear(self) -> None:
        when = self.NOW - 100
        row = self.row([*set_goal(when + 5), goal_line(when + 30, CLEARED)])
        self.assertIsNone(row["session_goal"])
        self.assertEqual({"at": when + 30}, row["session_goal_cleared"])


if __name__ == "__main__":
    unittest.main()
