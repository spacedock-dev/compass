"""A Claude Code `/goal` is read as the session's goal, from the record Claude Code writes for it.

The fixtures are hand-written in the shapes recorded in
`docs/captures/claude/goal-2.1.308-macos.jsonl`, with placeholder prose only. Four things are
measured there and rest on this module: the set record is a `goal_status` attachment with
`sentinel: true` that carries the condition, the evaluator's verdict is a second `goal_status`
with `met: true` and no sentinel, the `system` `local_command` record names the command and its
printed answer, and a goal the evaluator met has already cleared itself, so a later `/goal clear`
prints `No goal set`. `goal-clear-replace-verdicts-2.1.309-macos.jsonl` adds a clear of an active
goal (the sentinel with `met: true`, then `Goal cleared:`), a replacement, the not-met verdict
and the impossible one (`failed: true`), and a resume of an active goal that writes nothing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar

from compass_runtime import annotations as annotation_store
from compass_runtime import claude_data, history, project_context, reading, records
from compass_runtime import sessions as runtime_sessions

from .fixtures import _iso, _jsonl
from .support import HarnessContractTestCase, make_runtime

CONDITION = "the placeholder parser handles every token type and its tests pass"
LATER_CONDITION = "the placeholder lexer is split into modules under 300 lines"
T0 = 1_780_000_000.0


def set_goal(when: float, condition: str = CONDITION, **extra: Any) -> list[dict[str, Any]]:
    """What setting a goal writes: the sentinel attachment, then the printed answer."""
    return [
        {
            "type": "attachment",
            "timestamp": _iso(when),
            "attachment": {
                "type": "goal_status",
                "met": False,
                "sentinel": True,
                "condition": condition,
            },
            **extra,
        },
        {
            "type": "system",
            "subtype": "local_command",
            "timestamp": _iso(when),
            "commandRun": {"command": "goal", "args": condition},
            "content": f"<local-command-stdout>Goal set: {condition}</local-command-stdout>",
            **extra,
        },
    ]


REASON = "placeholder reason"
MET = {"met": True, "at": T0 + 30, "reason": REASON}


def verdict(
    when: float, condition: str = CONDITION, *, met: bool = True, reason: Any = REASON
) -> dict[str, Any]:
    return {
        "type": "attachment",
        "timestamp": _iso(when),
        "attachment": {
            "type": "goal_status",
            "met": met,
            "condition": condition,
            "reason": reason,
            "iterations": 1,
            "durationMs": 1000,
            "tokens": 10,
        },
    }


def clear_sentinel(when: float, condition: str = CONDITION) -> dict[str, Any]:
    """Measured (2.1.309): clearing an active goal writes this before `Goal cleared:` prints."""
    return {
        "type": "attachment",
        "timestamp": _iso(when),
        "attachment": {
            "type": "goal_status",
            "met": True,
            "sentinel": True,
            "condition": condition,
        },
    }


def impossible(when: float, condition: str = CONDITION) -> dict[str, Any]:
    """Measured (2.1.309): a goal the evaluator gave up on is `met: false` with `failed: true`."""
    record = verdict(when, condition, met=False)
    record["attachment"]["failed"] = True
    return record


def command_answer(when: float, args: str, printed: str) -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "local_command",
        "timestamp": _iso(when),
        "commandRun": {"command": "goal", "args": args},
        "content": f"<local-command-stdout>{printed}</local-command-stdout>",
    }


def prompt(when: float, text: str = "Add a placeholder parser.") -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": _iso(when),
        "message": {"role": "user", "content": text},
    }


def read_goal(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    with tempfile.TemporaryDirectory() as home:
        config, state = make_runtime()
        path = Path(home, "claude.jsonl")
        _jsonl(path, records, T0)
        return claude_data.session_goal(config, state, str(path))


class TheGoalReadFromTheRecordTest(unittest.TestCase):
    def test_one_goal_publishes_its_condition_and_the_moment_it_was_set(self) -> None:
        goal = read_goal([prompt(T0), *set_goal(T0 + 5)])
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, goal)

    def test_a_session_with_no_goal_publishes_none(self) -> None:
        self.assertIsNone(read_goal([prompt(T0)]))

    def test_a_replaced_goal_publishes_the_later_one(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), *set_goal(T0 + 50, LATER_CONDITION)])
        self.assertEqual(
            {"text": LATER_CONDITION, "at": T0 + 50, "earlier": {"how": "replaced", "at": T0 + 50}},
            goal,
        )

    def test_a_cleared_goal_publishes_none(self) -> None:
        # The wording is the documented one; the uncaptured shape is on the capture's list.
        cleared = command_answer(T0 + 20, "clear", f"Goal cleared: {CONDITION}")
        self.assertIsNone(read_goal([*set_goal(T0 + 5), cleared]))

    def test_the_clear_marker_alone_clears_without_reading_as_a_met_goal(self) -> None:
        # Measured: the sentinel with `met: true` is the clear, not the evaluator's verdict.
        self.assertIsNone(read_goal([*set_goal(T0 + 5), clear_sentinel(T0 + 20)]))

    def test_a_sentinel_without_a_measured_met_value_neither_sets_nor_clears(self) -> None:
        # Only `met: false` (set) and `met: true` (clear) were measured; anything else is ignored.
        for odd in ({}, {"met": None}, {"met": "false"}, {"met": 0}):
            with self.subTest(odd=odd):
                record = clear_sentinel(T0 + 20)
                record["attachment"].pop("met")
                record["attachment"].update(odd)
                self.assertEqual(
                    {"text": CONDITION, "at": T0 + 5}, read_goal([*set_goal(T0 + 5), record])
                )
                self.assertIsNone(read_goal([record]))

    def test_a_goal_cleared_in_the_measured_order_publishes_none(self) -> None:
        cleared = command_answer(T0 + 20, "clear", f"Goal cleared: {CONDITION}")
        self.assertIsNone(read_goal([*set_goal(T0 + 5), clear_sentinel(T0 + 20), cleared]))

    def test_an_interactive_session_writes_only_the_sentinels_and_is_still_read(self) -> None:
        # Measured (2.1.309, tmux): no `local_command` record for the set or the clear.
        interactive_set = set_goal(T0 + 5)[:1]
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, read_goal(interactive_set))
        self.assertIsNone(read_goal([*interactive_set, clear_sentinel(T0 + 20)]))

    def test_a_refused_over_limit_command_leaves_the_goal_as_it_was(self) -> None:
        # Measured: 4001 characters print the limit and write no sentinel.
        refused = command_answer(
            T0 + 20, "x" * 4001, "Goal condition is limited to 4000 characters (got 4001)"
        )
        goal = read_goal([*set_goal(T0 + 5), refused])
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, goal)

    def test_a_goal_set_after_the_measured_clear_is_published(self) -> None:
        goal = read_goal(
            [*set_goal(T0 + 5), clear_sentinel(T0 + 20), *set_goal(T0 + 40, LATER_CONDITION)]
        )
        self.assertEqual({"text": LATER_CONDITION, "at": T0 + 40}, goal)

    def test_an_impossible_verdict_ends_the_goal_and_is_not_a_met_one(self) -> None:
        # Measured (2.1.309): after `failed: true` the goal is ended, so it is not held.
        self.assertIsNone(read_goal([*set_goal(T0 + 5), impossible(T0 + 30)]))

    def test_a_replaced_goal_met_later_carries_the_verdict_for_the_second_only(self) -> None:
        goal = read_goal(
            [
                *set_goal(T0 + 5),
                verdict(T0 + 10, met=False),
                *set_goal(T0 + 50, LATER_CONDITION),
                verdict(T0 + 90, LATER_CONDITION),
            ]
        )
        assert goal is not None
        self.assertEqual(LATER_CONDITION, goal["text"])
        self.assertEqual(T0 + 90, goal["verdict"]["at"])
        self.assertEqual({"how": "replaced", "at": T0 + 50}, goal["earlier"])

    def test_every_documented_alias_of_clear_clears(self) -> None:
        for alias in ("stop", "off", "reset", "none", "cancel"):
            with self.subTest(alias=alias):
                cleared = command_answer(T0 + 20, alias, f"Goal cleared: {CONDITION}")
                self.assertIsNone(read_goal([*set_goal(T0 + 5), cleared]))

    def test_a_goal_set_after_a_clear_is_published(self) -> None:
        cleared = command_answer(T0 + 20, "clear", f"Goal cleared: {CONDITION}")
        goal = read_goal([*set_goal(T0 + 5), cleared, *set_goal(T0 + 40, LATER_CONDITION)])
        self.assertEqual({"text": LATER_CONDITION, "at": T0 + 40}, goal)

    def test_a_met_goal_keeps_its_condition_and_its_set_time(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30)])
        self.assertEqual({"text": CONDITION, "at": T0 + 5, "verdict": MET}, goal)

    def test_clearing_after_a_met_goal_changes_nothing(self) -> None:
        # Measured: a met goal had cleared itself, so the later command printed `No goal set`.
        nothing = command_answer(T0 + 60, "clear", "No goal set")
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30), nothing])
        self.assertEqual({"text": CONDITION, "at": T0 + 5, "verdict": MET}, goal)

    def test_a_status_check_changes_nothing(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), command_answer(T0 + 9, "", "placeholder status")])
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, goal)

    def test_a_verdict_with_no_set_record_publishes_none_rather_than_a_guessed_time(self) -> None:
        self.assertIsNone(read_goal([prompt(T0), verdict(T0 + 30)]))

    def test_a_verdict_for_another_condition_is_not_this_goals_set_time(self) -> None:
        self.assertIsNone(read_goal([*set_goal(T0 + 5), verdict(T0 + 30, LATER_CONDITION)]))

    def test_a_not_met_verdict_leaves_the_goal_as_it_was(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30, met=False)])
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, goal)

    def test_a_goal_with_no_verdict_publishes_no_verdict_key(self) -> None:
        # A key every goal carried would say nothing about this one.
        goal = read_goal([*set_goal(T0 + 5)])
        assert goal is not None
        self.assertNotIn("verdict", goal)

    def test_a_later_goal_does_not_inherit_the_earlier_ones_verdict(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30), *set_goal(T0 + 50, LATER_CONDITION)])
        self.assertEqual(
            {"text": LATER_CONDITION, "at": T0 + 50, "earlier": {"how": "met", "at": T0 + 30}},
            goal,
        )

    def test_the_verdict_carries_the_evaluators_reason_as_one_masked_line(self) -> None:
        reason = "wrote notes.md and ran deploy with key AKIAIOSFODNN7EXAMPLE\n\nthen   checked"
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30, reason=reason)])
        assert goal is not None
        text = goal["verdict"]["reason"]
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", text)
        self.assertNotIn("\n", text)
        self.assertTrue(text.startswith("wrote notes.md and ran deploy with key"))

    def test_a_reason_over_the_bound_is_cut_and_says_so(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30, reason="word " * 400)])
        assert goal is not None
        self.assertLessEqual(
            len(goal["verdict"]["reason"]), claude_data.VERDICT_REASON_CAP_CHARS + 1
        )
        self.assertTrue(goal["verdict"]["reason"].endswith("…"))

    def test_a_reason_that_is_not_text_is_an_empty_one_and_the_verdict_stands(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30, reason=["not", "text"])])
        assert goal is not None
        self.assertEqual({"met": True, "at": T0 + 30, "reason": ""}, goal["verdict"])

    def test_the_latest_verdict_wins(self) -> None:
        goal = read_goal([*set_goal(T0 + 5), verdict(T0 + 30), verdict(T0 + 40, reason="again")])
        assert goal is not None
        self.assertEqual({"met": True, "at": T0 + 40, "reason": "again"}, goal["verdict"])

    def test_a_condition_at_the_documented_limit_is_published_whole(self) -> None:
        goal = read_goal(set_goal(T0 + 5, "x" * 4000))
        assert goal is not None
        self.assertEqual("x" * 4000, goal["text"])
        self.assertTrue(goal["cut"])
        self.assertLessEqual(len(goal["offered"]), 240)

    def test_a_condition_over_the_documented_limit_publishes_none(self) -> None:
        self.assertIsNone(read_goal(set_goal(T0 + 5, "x" * 4001)))

    def test_a_condition_that_is_not_text_publishes_none(self) -> None:
        records = set_goal(T0 + 5)
        records[0]["attachment"]["condition"] = ["not", "text"]
        self.assertIsNone(read_goal(records))

    def test_a_subagents_goal_record_is_not_the_sessions(self) -> None:
        self.assertIsNone(read_goal(set_goal(T0 + 5, isSidechain=True)))

    def test_a_credential_in_the_condition_is_masked(self) -> None:
        goal = read_goal(set_goal(T0 + 5, "deploy with key AKIAIOSFODNN7EXAMPLE and verify"))
        assert goal is not None
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", goal["text"])

    def test_a_multi_line_condition_is_one_line(self) -> None:
        goal = read_goal(set_goal(T0 + 5, "first line\n\nsecond   line"))
        assert goal is not None
        self.assertEqual("first line second line", goal["text"])

    def test_an_unparseable_or_untimed_set_record_publishes_none(self) -> None:
        records = set_goal(T0 + 5)
        records[0]["timestamp"] = "not a time"
        self.assertIsNone(read_goal(records))


class AGoalOverTheGoalLimitIsOfferedCutTest(unittest.TestCase):
    """The Goal field holds 240 characters. A longer `/goal` is offered as an excerpt marked cut."""

    LONG = "the placeholder parser handles every token type and " * 8

    def test_a_goal_within_the_limit_publishes_no_excerpt(self) -> None:
        goal = read_goal([*set_goal(T0 + 5)])
        assert goal is not None
        self.assertNotIn("cut", goal)
        self.assertNotIn("offered", goal)

    def test_a_longer_goal_publishes_the_whole_words_and_an_excerpt_marked_cut(self) -> None:
        goal = read_goal([*set_goal(T0 + 5, self.LONG)])
        assert goal is not None
        self.assertEqual(" ".join(self.LONG.split()), goal["text"])
        self.assertTrue(goal["cut"])
        self.assertLessEqual(len(goal["offered"]), 240)
        self.assertTrue(goal["text"].startswith(goal["offered"]))

    def test_the_server_resolves_the_excerpt_and_never_the_whole_words_for_adoption(self) -> None:
        goal = read_goal([*set_goal(T0 + 5, self.LONG)])
        row = {"harness": "claude", "session_goal": goal}
        text, at = annotation_store.prompt_candidate(row, "session-goal")
        assert goal is not None
        self.assertEqual((goal["offered"], T0 + 5), (text, at))

    def test_an_adoption_naming_the_excerpt_stores_exactly_it(self) -> None:
        goal = read_goal([*set_goal(T0 + 5, self.LONG)])
        assert goal is not None
        row = {"harness": "claude", "session_goal": goal}
        adopted = annotation_store._adoption(row, "session-goal", goal["offered"], T0 + 5, T0 + 9)
        assert adopted is not None
        self.assertEqual(goal["offered"], adopted["goal"])
        self.assertEqual(goal["offered"], records.safe_text(adopted["goal"], 240))
        # Naming the whole words is a stale or forged adoption: refused, never clipped to fit.
        self.assertIsNone(
            annotation_store._adoption(row, "session-goal", goal["text"], T0 + 5, T0 + 9)
        )


class TheGoalIsReadOnAppendTest(unittest.TestCase):
    def test_a_goal_appended_after_a_read_is_read_without_a_rescan_from_the_top(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "claude.jsonl")
            _jsonl(path, [prompt(T0), *set_goal(T0 + 5)], T0)
            self.assertEqual(
                CONDITION, (claude_data.session_goal(config, state, str(path)) or {})["text"]
            )
            with path.open("a", encoding="utf-8") as handle:
                for record in set_goal(T0 + 50, LATER_CONDITION):
                    handle.write(json.dumps(record) + "\n")
            goal = claude_data.session_goal(config, state, str(path))
        self.assertEqual(
            {"text": LATER_CONDITION, "at": T0 + 50, "earlier": {"how": "replaced", "at": T0 + 50}},
            goal,
        )

    def test_a_verdict_appended_later_still_finds_the_set_time_read_earlier(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "claude.jsonl")
            _jsonl(path, set_goal(T0 + 5), T0)
            claude_data.session_goal(config, state, str(path))
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(verdict(T0 + 30)) + "\n")
            goal = claude_data.session_goal(config, state, str(path))
        self.assertEqual({"text": CONDITION, "at": T0 + 5, "verdict": MET}, goal)

    def test_a_half_written_last_line_is_read_once_it_completes(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "claude.jsonl")
            whole = json.dumps(set_goal(T0 + 5)[0])
            path.write_text(whole[:40], encoding="utf-8")
            self.assertIsNone(claude_data.session_goal(config, state, str(path)))
            path.write_text(whole + "\n", encoding="utf-8")
            goal = claude_data.session_goal(config, state, str(path))
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, goal)

    def test_a_replaced_file_is_read_afresh(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "claude.jsonl")
            _jsonl(path, [prompt(T0), prompt(T0 + 1), *set_goal(T0 + 5)], T0)
            claude_data.session_goal(config, state, str(path))
            _jsonl(path, [prompt(T0)], T0 + 1)
            self.assertIsNone(claude_data.session_goal(config, state, str(path)))

    def test_a_missing_file_publishes_none(self) -> None:
        config, state = make_runtime()
        self.assertIsNone(claude_data.session_goal(config, state, "/nonexistent/claude.jsonl"))


def _store(records: list[dict[str, Any]]) -> Any:
    def build(root: Path, when: float, sid: str, _title: str) -> dict[str, str]:
        projects = root / "projects"
        _jsonl(projects / "-w-proj" / f"{sid}.jsonl", records, when)
        return {"PROJECTS_DIR": str(projects), "TASKS_DIR": str(root / "tasks")}

    return build


class TheCollectorPublishesTheGoalTest(HarnessContractTestCase):
    def row(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        (row,) = self.sessions_for(self.collect(_store(records), when=self.NOW), "claude")
        return row

    def test_a_session_with_a_goal_publishes_it_on_its_row(self) -> None:
        when = self.NOW - 100
        row = self.row([prompt(when), *set_goal(when + 5), prompt(when + 10, "keep going")])
        self.assertEqual({"text": CONDITION, "at": when + 5}, row["session_goal"])

    def test_a_met_goal_publishes_the_verdict_with_it(self) -> None:
        when = self.NOW - 100
        row = self.row([prompt(when), *set_goal(when + 5), verdict(when + 30)])
        self.assertEqual(
            {"met": True, "at": when + 30, "reason": REASON}, row["session_goal"]["verdict"]
        )

    def test_a_session_with_no_goal_publishes_none_and_nothing_else_moves(self) -> None:
        when = self.NOW - 100
        row = self.row([prompt(when), prompt(when + 10, "keep going")])
        self.assertIsNone(row["session_goal"])
        self.assertEqual("Add a placeholder parser.", row["first_prompt"])

    def test_the_absent_value_is_none(self) -> None:
        self.assertIsNone(runtime_sessions.base_session("claude", "s", "p")["session_goal"])


class AGoalSessionIsNamedByTheGoalItHoldsTest(HarnessContractTestCase):
    """The name every surface shows is `title`; a `/goal` opener must not name a goal no longer held."""

    def title(self, records: list[dict[str, Any]]) -> str | None:
        (row,) = self.sessions_for(self.collect(_store(records), when=self.NOW), "claude")
        title: str | None = row["title"]
        return title

    def test_a_replaced_goal_names_the_session_by_the_goal_held_now(self) -> None:
        when = self.NOW - 100
        opener = prompt(when, f"/goal {CONDITION}")
        title = self.title([opener, *set_goal(when + 1), *set_goal(when + 50, LATER_CONDITION)])
        self.assertEqual(LATER_CONDITION, title)

    def test_a_cleared_goal_does_not_name_the_session(self) -> None:
        when = self.NOW - 100
        opener = prompt(when, f"/goal {CONDITION}")
        title = self.title([opener, *set_goal(when + 1), clear_sentinel(when + 20)])
        self.assertFalse((title or "").startswith("/goal"))
        self.assertNotIn(CONDITION[:20], title or "")

    def test_a_cleared_goal_session_is_named_by_its_next_real_prompt(self) -> None:
        when = self.NOW - 100
        records = [
            prompt(when, f"/goal {CONDITION}"),
            *set_goal(when + 1),
            clear_sentinel(when + 20),
            prompt(when + 30, "Tidy the placeholder module"),
        ]
        self.assertEqual("Tidy the placeholder module", self.title(records))

    def test_a_goal_cleared_inside_a_window_shorter_than_the_file_does_not_name_the_session(
        self,
    ) -> None:
        # The set sits before the window and the clear inside it: a clear seen is evidence the
        # goal is not held, which an empty read of the window is not.
        when = T0
        records = [prompt(when, f"/goal {CONDITION}"), *set_goal(when + 1)]
        records += [prompt(when + 2 + n, "x" * 400) for n in range(40)]
        records += [
            clear_sentinel(when + 100),
            command_answer(when + 101, "clear", "Goal cleared: x"),
        ]
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(turn_scan_max_bytes=4096)
            path = Path(home, "claude.jsonl")
            _jsonl(path, records, T0)
            self.assertGreater(path.stat().st_size, config.turn_scan_max_bytes)
            self.assertIsNone(claude_data.session_goal(config, state, str(path)))
            title = claude_data.session_title(config, state, str(path))
        self.assertFalse((title or "").startswith("/goal"))

    def test_a_goal_set_outside_the_cold_read_window_still_names_the_session(self) -> None:
        # The read starts at most `turn_scan_max_bytes` from the end, so a goal set before that
        # is not seen and its absence proves nothing: the opener stays as the last-resort name.
        when = T0
        records = [prompt(when, f"/goal {CONDITION}"), *set_goal(when + 1)]
        records += [prompt(when + 2 + n, "x" * 400) for n in range(40)]
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(turn_scan_max_bytes=4096)
            path = Path(home, "claude.jsonl")
            _jsonl(path, records, T0)
            self.assertGreater(path.stat().st_size, config.turn_scan_max_bytes)
            self.assertIsNone(claude_data.session_goal(config, state, str(path)))
            title = claude_data.session_title(config, state, str(path))
        self.assertTrue((title or "").startswith("/goal"))

    def test_a_generated_title_keeps_the_session_name(self) -> None:
        when = self.NOW - 100
        ai = {"type": "ai-title", "aiTitle": "Generated name", "timestamp": _iso(when + 2)}
        records = [prompt(when, f"/goal {CONDITION}"), *set_goal(when + 1), ai]
        self.assertEqual("Generated name", self.title(records))


def read_all(
    records: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    """The goal, the clear and the give-up one read of these records publishes."""
    with tempfile.TemporaryDirectory() as home:
        config, state = make_runtime()
        path = Path(home, "claude.jsonl")
        _jsonl(path, records, T0)
        goal = claude_data.session_goal(config, state, str(path))
        return (
            goal,
            claude_data.session_goal_cleared(state, str(path)),
            claude_data.session_goal_gave_up(state, str(path)),
        )


class AGoalThatEndedIsSaidToHaveEndedTest(unittest.TestCase):
    """DRC-4956: a give-up, a clear and a replacement are published beside the goal, never as it."""

    def test_a_give_up_ends_the_goal_and_publishes_its_time_and_masked_reason(self) -> None:
        record = impossible(T0 + 30)
        record["attachment"]["reason"] = "no such path\n\nkey AKIAIOSFODNN7EXAMPLE"
        goal, cleared, gave_up = read_all([*set_goal(T0 + 5), record])
        self.assertIsNone(goal)
        self.assertIsNone(cleared)
        assert gave_up is not None
        self.assertEqual({"at", "reason"}, set(gave_up))
        self.assertEqual(T0 + 30, gave_up["at"])
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", gave_up["reason"])
        self.assertNotIn("\n", gave_up["reason"])

    def test_a_give_up_publishes_no_iterations_tokens_or_duration(self) -> None:
        _goal, _cleared, gave_up = read_all([*set_goal(T0 + 5), impossible(T0 + 30)])
        assert gave_up is not None
        self.assertEqual({"at", "reason"}, set(gave_up))

    def test_a_give_up_is_never_a_verdict_or_a_met_goal(self) -> None:
        goal, _cleared, gave_up = read_all([*set_goal(T0 + 5), impossible(T0 + 30)])
        self.assertIsNone(goal)
        assert gave_up is not None
        self.assertNotIn("met", gave_up)
        self.assertNotIn("verdict", gave_up)

    def test_a_give_up_reason_is_cut_at_the_bound(self) -> None:
        record = impossible(T0 + 30)
        record["attachment"]["reason"] = "word " * 400
        _goal, _cleared, gave_up = read_all([*set_goal(T0 + 5), record])
        assert gave_up is not None
        self.assertLessEqual(len(gave_up["reason"]), claude_data.VERDICT_REASON_CAP_CHARS + 1)
        self.assertTrue(gave_up["reason"].endswith("…"))

    def test_a_reason_that_is_not_text_is_an_empty_one_and_the_give_up_stands(self) -> None:
        record = impossible(T0 + 30)
        record["attachment"]["reason"] = ["not", "text"]
        _goal, _cleared, gave_up = read_all([*set_goal(T0 + 5), record])
        self.assertEqual({"at": T0 + 30, "reason": ""}, gave_up)

    def test_a_give_up_for_a_goal_not_held_is_not_published(self) -> None:
        # No set record in the bytes read, or another condition: absent means unknown.
        self.assertEqual((None, None, None), read_all([prompt(T0), impossible(T0 + 30)]))
        other = impossible(T0 + 30, LATER_CONDITION)
        self.assertEqual((None, None, None), read_all([*set_goal(T0 + 5), other]))

    def test_a_goal_set_after_a_give_up_says_the_earlier_one_was_given_up(self) -> None:
        goal, cleared, gave_up = read_all(
            [*set_goal(T0 + 5), impossible(T0 + 30), *set_goal(T0 + 60, LATER_CONDITION)]
        )
        self.assertEqual(
            {"text": LATER_CONDITION, "at": T0 + 60, "earlier": {"how": "gave-up", "at": T0 + 30}},
            goal,
        )
        self.assertIsNone(cleared)
        self.assertIsNone(gave_up)

    def test_a_clear_publishes_its_time_and_leaves_no_goal(self) -> None:
        goal, cleared, gave_up = read_all([*set_goal(T0 + 5), clear_sentinel(T0 + 20)])
        self.assertIsNone(goal)
        self.assertEqual({"at": T0 + 20}, cleared)
        self.assertIsNone(gave_up)

    def test_the_first_of_two_clear_signals_wins(self) -> None:
        printed = command_answer(T0 + 21, "clear", f"Goal cleared: {CONDITION}")
        _goal, cleared, _gave_up = read_all([*set_goal(T0 + 5), clear_sentinel(T0 + 20), printed])
        self.assertEqual({"at": T0 + 20}, cleared)

    def test_the_printed_clear_alone_publishes_its_time(self) -> None:
        printed = command_answer(T0 + 21, "clear", f"Goal cleared: {CONDITION}")
        _goal, cleared, _gave_up = read_all([*set_goal(T0 + 5), printed])
        self.assertEqual({"at": T0 + 21}, cleared)

    def test_a_goal_set_after_a_clear_is_held_and_the_clear_is_no_longer_published(self) -> None:
        goal, cleared, _gave_up = read_all(
            [*set_goal(T0 + 5), clear_sentinel(T0 + 20), *set_goal(T0 + 40, LATER_CONDITION)]
        )
        self.assertEqual({"text": LATER_CONDITION, "at": T0 + 40}, goal)
        self.assertIsNone(cleared)

    def test_a_clear_that_leaves_a_goal_is_none_for_a_session_with_no_goal_events(self) -> None:
        self.assertEqual((None, None, None), read_all([prompt(T0)]))

    def test_a_status_check_or_a_no_goal_answer_is_not_a_clear(self) -> None:
        nothing = command_answer(T0 + 40, "clear", "No goal set")
        goal, cleared, gave_up = read_all([*set_goal(T0 + 5), impossible(T0 + 30), nothing])
        self.assertIsNone(goal)
        self.assertIsNone(cleared)
        assert gave_up is not None

    def test_a_replacement_while_the_goal_was_active_names_the_moment_of_the_replacement(
        self,
    ) -> None:
        goal, _cleared, _gave_up = read_all(
            [*set_goal(T0 + 5), verdict(T0 + 10, met=False), *set_goal(T0 + 50, LATER_CONDITION)]
        )
        assert goal is not None
        self.assertEqual({"how": "replaced", "at": T0 + 50}, goal["earlier"])

    def test_the_earlier_goals_words_are_never_published(self) -> None:
        goal, _cleared, _gave_up = read_all(
            [*set_goal(T0 + 5), *set_goal(T0 + 50, LATER_CONDITION)]
        )
        assert goal is not None
        self.assertEqual({"how", "at"}, set(goal["earlier"]))
        self.assertNotIn(CONDITION[:20], json.dumps(goal))

    def test_a_same_moment_re_set_of_the_same_words_is_not_a_replacement(self) -> None:
        goal, _cleared, _gave_up = read_all([*set_goal(T0 + 5), *set_goal(T0 + 5)])
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, goal)

    def test_the_same_words_set_again_later_is_a_replacement(self) -> None:
        goal, _cleared, _gave_up = read_all([*set_goal(T0 + 5), *set_goal(T0 + 50)])
        assert goal is not None
        self.assertEqual({"how": "replaced", "at": T0 + 50}, goal["earlier"])

    def test_a_goal_with_no_earlier_one_publishes_no_earlier_key(self) -> None:
        goal, _cleared, _gave_up = read_all([*set_goal(T0 + 5)])
        assert goal is not None
        self.assertNotIn("earlier", goal)

    def test_a_set_after_a_give_up_then_a_clear_publishes_no_earlier_key(self) -> None:
        # Measured: the clear after a give-up prints `No goal set` and writes nothing, so the
        # give-up stands as the earlier goal's end.
        nothing = command_answer(T0 + 40, "clear", "No goal set")
        goal, _cleared, _gave_up = read_all(
            [
                *set_goal(T0 + 5),
                impossible(T0 + 30),
                nothing,
                *set_goal(T0 + 60, LATER_CONDITION),
            ]
        )
        assert goal is not None
        self.assertEqual({"how": "gave-up", "at": T0 + 30}, goal["earlier"])

    def test_every_new_note_survives_an_append_without_a_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime()
            path = Path(home, "claude.jsonl")
            _jsonl(path, [*set_goal(T0 + 5), impossible(T0 + 30)], T0)
            claude_data.session_goal(config, state, str(path))
            with path.open("a", encoding="utf-8") as handle:
                for record in set_goal(T0 + 60, LATER_CONDITION):
                    handle.write(json.dumps(record) + "\n")
            goal = claude_data.session_goal(config, state, str(path))
            gave_up = claude_data.session_goal_gave_up(state, str(path))
        assert goal is not None
        self.assertEqual({"how": "gave-up", "at": T0 + 30}, goal["earlier"])
        self.assertIsNone(gave_up)

    def test_a_cold_read_that_starts_mid_file_publishes_none_of_it(self) -> None:
        # The set and the give-up sit before the window; absent means unknown.
        records = [*set_goal(T0 + 1), impossible(T0 + 2)]
        records += [prompt(T0 + 3 + n, "x" * 400) for n in range(40)]
        with tempfile.TemporaryDirectory() as home:
            config, state = make_runtime(turn_scan_max_bytes=4096)
            path = Path(home, "claude.jsonl")
            _jsonl(path, records, T0)
            self.assertGreater(path.stat().st_size, config.turn_scan_max_bytes)
            self.assertIsNone(claude_data.session_goal(config, state, str(path)))
            self.assertIsNone(claude_data.session_goal_cleared(state, str(path)))
            self.assertIsNone(claude_data.session_goal_gave_up(state, str(path)))

    def test_a_subagents_give_up_or_clear_is_not_the_sessions(self) -> None:
        sub = impossible(T0 + 30)
        sub["isSidechain"] = True
        self.assertEqual((None, None, None), read_all([sub]))
        goal, cleared, gave_up = read_all(
            [*set_goal(T0 + 5), {**clear_sentinel(T0 + 9), "isSidechain": True}]
        )
        assert goal is not None
        self.assertIsNone(cleared)
        self.assertIsNone(gave_up)

    def test_a_met_goal_is_not_a_give_up(self) -> None:
        goal, cleared, gave_up = read_all([*set_goal(T0 + 5), verdict(T0 + 30)])
        assert goal is not None
        self.assertIsNone(cleared)
        self.assertIsNone(gave_up)


class TheCollectorPublishesTheEndingsTest(HarnessContractTestCase):
    def row(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        (row,) = self.sessions_for(self.collect(_store(records), when=self.NOW), "claude")
        return row

    def test_a_give_up_is_on_the_row_beside_a_goal_that_is_none(self) -> None:
        when = self.NOW - 100
        row = self.row([prompt(when), *set_goal(when + 5), impossible(when + 30)])
        self.assertIsNone(row["session_goal"])
        self.assertEqual({"at": when + 30, "reason": REASON}, row["session_goal_gave_up"])
        self.assertIsNone(row["session_goal_cleared"])

    def test_a_clear_is_on_the_row_and_the_goal_does_not_name_the_session(self) -> None:
        when = self.NOW - 100
        row = self.row(
            [prompt(when, f"/goal {CONDITION}"), *set_goal(when + 1), clear_sentinel(when + 20)]
        )
        self.assertIsNone(row["session_goal"])
        self.assertEqual({"at": when + 20}, row["session_goal_cleared"])
        self.assertIsNone(row["session_goal_gave_up"])
        self.assertNotIn(CONDITION[:20], row["title"] or "")

    def test_a_given_up_goal_does_not_name_the_session(self) -> None:
        when = self.NOW - 100
        row = self.row(
            [prompt(when, f"/goal {CONDITION}"), *set_goal(when + 1), impossible(when + 20)]
        )
        self.assertFalse((row["title"] or "").startswith("/goal"))
        self.assertNotIn(CONDITION[:20], row["title"] or "")

    def test_a_session_with_neither_publishes_none_for_both(self) -> None:
        row = self.row([prompt(self.NOW - 100)])
        self.assertIsNone(row["session_goal_cleared"])
        self.assertIsNone(row["session_goal_gave_up"])

    def test_the_absent_values_are_none(self) -> None:
        base = runtime_sessions.base_session("claude", "s", "p")
        self.assertIsNone(base["session_goal_cleared"])
        self.assertIsNone(base["session_goal_gave_up"])


class TheSourceIsInTheClosedVocabularyTest(unittest.TestCase):
    def test_the_producer_names_it_among_the_prompt_sources(self) -> None:
        self.assertEqual("session-goal", reading.SESSION_GOAL)
        self.assertIn(reading.SESSION_GOAL, reading.PROMPT_SOURCES)
        self.assertEqual(len(set(reading.PROMPT_SOURCES)), len(reading.PROMPT_SOURCES))

    def test_a_stored_goal_from_it_reads_back(self) -> None:
        value = {"goal_source": "session-goal", "goal_source_at": 10.0, "at": 20.0}
        self.assertEqual(
            {"goal_source": "session-goal", "goal_source_at": 10.0},
            annotation_store._provenance(value),
        )

    def test_history_and_the_reading_window_accept_it(self) -> None:
        self.assertEqual("session-goal", history._goal_source("session-goal"))

    def test_the_project_context_window_starts_at_the_goal_not_the_read(self) -> None:
        session = {
            "annotation_assessment": {
                "goal_source": "session-goal",
                "goal_source_at": 10.0,
                "revision_read_at": 99.0,
            }
        }
        self.assertEqual(10.0, project_context._assessment_window_start(session))


class TheGoalIsAdoptableTest(unittest.TestCase):
    ROW: ClassVar[dict[str, Any]] = {
        "harness": "claude",
        "session_goal": {"text": CONDITION, "at": 10.0},
    }

    def test_the_server_resolves_the_goal_from_its_own_row(self) -> None:
        self.assertEqual(
            (CONDITION, 10.0), annotation_store.prompt_candidate(self.ROW, "session-goal")
        )

    def test_no_goal_on_the_row_resolves_to_nothing(self) -> None:
        row = {"harness": "claude", "session_goal": None}
        self.assertEqual(("", None), annotation_store.prompt_candidate(row, "session-goal"))

    def test_another_harness_never_resolves_one(self) -> None:
        row = {**self.ROW, "harness": "codex"}
        self.assertEqual(("", None), annotation_store.prompt_candidate(row, "session-goal"))

    def test_a_malformed_row_value_resolves_to_nothing(self) -> None:
        for bad in (
            "text",
            {"text": 3, "at": 1.0},
            {"text": CONDITION, "at": "x"},
            {"text": CONDITION},
        ):
            with self.subTest(bad=bad):
                row = {"harness": "claude", "session_goal": bad}
                text, at = annotation_store.prompt_candidate(row, "session-goal")
                # An adoption refuses a candidate with no moment, as for every other source.
                self.assertTrue(not text or at is None)


if __name__ == "__main__":
    unittest.main()
