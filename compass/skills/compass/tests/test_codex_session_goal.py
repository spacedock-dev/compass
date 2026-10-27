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

import dataclasses
import sqlite3
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import MappingProxyType
from typing import Any

from compass_runtime import claude_data, records
from compass_runtime import io as runtime_io

from .fixtures import _iso, _jsonl, _sqlite
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


GOALS_SCHEMA = (
    "CREATE TABLE thread_goals (thread_id TEXT PRIMARY KEY NOT NULL, goal_id TEXT NOT NULL,"
    " objective TEXT NOT NULL, status TEXT NOT NULL, token_budget INTEGER,"
    " tokens_used INTEGER NOT NULL DEFAULT 0, time_used_seconds INTEGER NOT NULL DEFAULT 0,"
    " created_at_ms INTEGER NOT NULL, updated_at_ms INTEGER NOT NULL)"
)


def goals_file(
    codex_home: Path, rows: list[tuple[str, str, str, float, float]], when: float = T0
) -> None:
    """Codex's goal file as 0.164.0 writes it: `(thread, objective, status, set, updated)` in seconds."""
    _sqlite(
        codex_home / claude_data.CODEX_GOALS_DB,
        [
            (GOALS_SCHEMA, ()),
            *(
                (
                    (
                        "INSERT INTO thread_goals (thread_id, goal_id, objective, status,"
                        " created_at_ms, updated_at_ms) VALUES (?, 'g', ?, ?, ?, ?)"
                    ),
                    (thread, objective, status, int(created * 1000) + 412, int(updated * 1000)),
                )
                for thread, objective, status, created, updated in rows
            ),
        ],
        when,
    )


class TheCodexVerdictIsReadFromItsGoalFileTest(unittest.TestCase):
    GOAL: dict[str, Any] = {"text": OBJECTIVE, "at": T0 + 5}  # noqa: RUF012 - read-only fixture

    def verdict(
        self,
        rows: list[tuple[str, str, str, float, float]] | None,
        goal: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        with tempfile.TemporaryDirectory() as home:
            codex = Path(home)
            (codex / "sessions").mkdir()
            if rows is not None:
                goals_file(codex, rows)
            config, state = make_runtime()
            roots = {**config.store_roots, "codex.sessions": (str(codex / "sessions"),)}
            config = dataclasses.replace(config, store_roots=MappingProxyType(roots))
            return claude_data.codex_goal_verdict(
                config, state, "thread", self.GOAL if goal is None else goal
            )

    def test_a_completed_goal_is_the_harness_s_claim_at_the_moment_it_completed(self) -> None:
        self.assertEqual(
            {"met": True, "at": T0 + 40, "reason": ""},
            self.verdict([("thread", OBJECTIVE, "complete", T0 + 5, T0 + 40)]),
        )

    def test_nothing_else_is_a_verdict(self) -> None:
        for label, rows in (
            ("no file", None),
            ("still active", [("thread", OBJECTIVE, "active", T0 + 5, T0 + 40)]),
            ("blocked", [("thread", OBJECTIVE, "blocked", T0 + 5, T0 + 40)]),
            ("another thread", [("other", OBJECTIVE, "complete", T0 + 5, T0 + 40)]),
            ("other words", [("thread", LATER, "complete", T0 + 5, T0 + 40)]),
            ("another set time", [("thread", OBJECTIVE, "complete", T0 + 9, T0 + 40)]),
        ):
            with self.subTest(label):
                self.assertIsNone(self.verdict(rows))

    def test_a_row_with_no_goal_reads_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            self.assertIsNone(claude_data.codex_goal_verdict(config, state, "thread", None))
            self.assertFalse(Path(home, claude_data.CODEX_GOALS_DB).exists())

    def test_a_file_that_will_not_read_is_no_verdict_and_a_store_error(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            codex = Path(home)
            (codex / "sessions").mkdir()
            (codex / claude_data.CODEX_GOALS_DB).write_bytes(b"not a database")
            config, state = make_runtime()
            roots = {**config.store_roots, "codex.sessions": (str(codex / "sessions"),)}
            config = dataclasses.replace(config, store_roots=MappingProxyType(roots))
            self.assertIsNone(claude_data.codex_goal_verdict(config, state, "thread", self.GOAL))
            self.assertIn(str(codex / claude_data.CODEX_GOALS_DB), state.store_errors)


class TheCodexGoalFileIsReadAsCodexLeavesItTest(unittest.TestCase):
    """What the security review reproduced: Codex keeps the file in WAL mode, and a clean close of its
    last connection removes the `-wal` and `-shm` a `mode=ro` open needs."""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, ignore_errors=True))
        (self.home / "sessions").mkdir()
        self.config, self.state = make_runtime()
        roots = {**self.config.store_roots, "codex.sessions": (str(self.home / "sessions"),)}
        self.config = dataclasses.replace(self.config, store_roots=MappingProxyType(roots))

    def test_a_wal_file_closed_by_its_last_writer_still_gives_the_verdict(self) -> None:
        goals_file(self.home, [("thread", OBJECTIVE, "complete", T0 + 5, T0 + 40)])
        con = sqlite3.connect(str(self.home / claude_data.CODEX_GOALS_DB))
        con.execute("PRAGMA journal_mode=WAL")
        con.close()
        self.assertFalse((self.home / f"{claude_data.CODEX_GOALS_DB}-shm").exists())
        verdict = claude_data.codex_goal_verdict(
            self.config, self.state, "thread", {"text": OBJECTIVE, "at": T0 + 5}
        )
        self.assertEqual({"met": True, "at": T0 + 40, "reason": ""}, verdict)
        self.assertEqual({}, self.state.store_errors)

    def test_a_failed_read_is_tried_once_per_change_not_once_per_row(self) -> None:
        (self.home / claude_data.CODEX_GOALS_DB).write_bytes(b"not a database")
        opened: list[str] = []
        real = runtime_io.sqlite_module.connect

        def counting(database: str, **kw: Any) -> Any:
            opened.append(database)
            return real(database, **kw)

        with unittest.mock.patch.object(runtime_io.sqlite_module, "connect", counting):
            for _ in range(5):
                claude_data.codex_goal_verdict(
                    self.config, self.state, "thread", {"text": OBJECTIVE, "at": T0 + 5}
                )
        self.assertLessEqual(len(opened), 2)  # the read-only open and its immutable retry, once

    def test_an_objective_over_the_goal_bound_is_not_read(self) -> None:
        goals_file(self.home, [("thread", "x" * 4001, "complete", T0 + 5, T0 + 40)])
        self.assertEqual({}, dict(claude_data._codex_completed_goals(self.config, self.state)))


class TheCodexCollectorPublishesTheVerdictTest(HarnessContractTestCase):
    def test_a_completed_goal_carries_codex_s_verdict(self) -> None:
        when = self.NOW - 100

        def build(root: Path, at: float, sid: str, title: str) -> dict[str, str]:
            stores: dict[str, str] = _store(set_goal(when + 5))(root, at, sid, title)
            goals_file(root.parent, [(sid, OBJECTIVE, "complete", when + 5, when + 40)], at)
            return stores

        (row,) = self.sessions_for(self.collect(build, when=self.NOW), "codex")
        self.assertEqual(
            {"met": True, "at": when + 40, "reason": ""}, row["session_goal"]["verdict"]
        )


if __name__ == "__main__":
    unittest.main()
