"""An Antigravity `/goal` is read as the session's goal, from the input the person typed.

The fixtures are hand-written in the shapes recorded in
`docs/captures/antigravity/goal-1.4.7-macos.jsonl`, with placeholder prose only. Measured there: agy
writes no goal record, the goal is a `USER_INPUT` from `USER_EXPLICIT` whose request opens `/goal `
and whose `<ADDITIONAL_METADATA>` carries the slash command's fixed paragraph, a replace writes only
another such input, `/edit_goal` is not a command, and `transcript.jsonl` keeps only the first and last
2,048 characters of a long input while `transcript_full.jsonl` keeps it whole.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import annotations as annotation_store
from compass_runtime import claude_data, transcripts

from .fixtures import _iso, _jsonl, build_antigravity
from .support import HarnessContractTestCase, make_runtime

CONDITION = "the placeholder parser handles every token type and its tests pass"
LATER = "the placeholder lexer is split into modules under 300 lines"
T0 = 1_780_000_000.0
METADATA = (
    "<ADDITIONAL_METADATA>\nThe current local time is: placeholder.\n\n"
    f"{claude_data.ANTIGRAVITY_GOAL_MARKER}:\nThe user has marked this task with /goal.\n"
    "</ADDITIONAL_METADATA>"
)


def direction(when: float, request: str, *, metadata: str = METADATA) -> dict[str, Any]:
    return {
        "step_index": 0,
        "type": "USER_INPUT",
        "source": "USER_EXPLICIT",
        "status": "DONE",
        "created_at": _iso(when).replace("+00:00", "Z")[:19] + "Z",
        "content": f"<USER_REQUEST>\n{request}\n</USER_REQUEST>\n{metadata}",
    }


def set_goal(when: float, condition: str = CONDITION) -> dict[str, Any]:
    return direction(when, f"/goal {condition}")


def read(lines: list[dict[str, Any]]) -> dict[str, Any] | None:
    with tempfile.TemporaryDirectory() as home:
        config, state = make_runtime()
        path = Path(home, "transcript_full.jsonl")
        _jsonl(path, lines, T0)
        return claude_data.session_goal(config, state, str(path), "antigravity")


class TheAntigravityGoalReadFromTheTranscriptTest(unittest.TestCase):
    def test_a_goal_publishes_its_condition_at_the_moment_it_was_typed(self) -> None:
        self.assertEqual({"text": CONDITION, "at": T0 + 5}, read([set_goal(T0 + 5)]))

    def test_a_later_goal_replaces_it_and_says_nothing_about_the_earlier_one(self) -> None:
        goal = read([set_goal(T0 + 5), direction(T0 + 10, "keep going"), set_goal(T0 + 30, LATER)])
        self.assertEqual({"text": LATER, "at": T0 + 30}, goal)

    def test_a_request_that_starts_with_the_word_is_not_a_goal(self) -> None:
        for lines in (
            [direction(T0 + 5, f"/goal {CONDITION}", metadata="")],
            [direction(T0 + 5, f"/goalpost {CONDITION}")],
            [direction(T0 + 5, f"/edit_goal {CONDITION}", metadata="")],
            [direction(T0 + 5, "/goal")],
        ):
            with self.subTest(lines=lines[0]["content"][:30]):
                self.assertIsNone(read(lines))

    def test_only_the_person_s_own_input_counts(self) -> None:
        planner = {**set_goal(T0 + 5), "type": "PLANNER_RESPONSE", "source": "MODEL"}
        system = {**set_goal(T0 + 5), "type": "SYSTEM_MESSAGE", "source": "SYSTEM"}
        self.assertIsNone(read([planner, system]))

    def test_a_goal_over_the_claude_bound_is_kept_up_to_its_own(self) -> None:
        longer = "x " * 3000  # 6,000 characters: over 4,000, which agy accepted in the capture
        goal = read([set_goal(T0 + 5, longer.strip())])
        assert goal is not None
        self.assertTrue(goal["cut"])
        too_long = "x" * (claude_data.ANTIGRAVITY_GOAL_CAP_CHARS + 1)
        self.assertIsNone(read([set_goal(T0 + 5, too_long)]))

    def test_a_long_condition_is_offered_as_its_excerpt(self) -> None:
        long = " ".join([CONDITION] * 30)
        goal = read([set_goal(T0 + 5, long)])
        assert goal is not None
        self.assertEqual(long, goal["text"])
        self.assertTrue(goal["cut"])


class TheFullTranscriptIsTheOneReadTest(unittest.TestCase):
    def test_the_locator_returns_the_whole_field_copy_beside_the_short_one(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            logs = Path(root, "brain", "conv", ".system_generated", "logs")
            logs.mkdir(parents=True)
            (logs / "transcript.jsonl").write_text("{}\n")
            self.assertIsNone(transcripts.antigravity_transcript(root, "conv", full=True))
            (logs / "transcript_full.jsonl").write_text("{}\n")
            self.assertEqual(
                str(logs / "transcript_full.jsonl"),
                transcripts.antigravity_transcript(root, "conv", full=True),
            )


class TheServerAdoptsAnAntigravityGoalAloneTest(unittest.TestCase):
    ROW: dict[str, Any] = {  # noqa: RUF012 - read-only fixture
        "harness": "antigravity",
        "session_goal": {"text": CONDITION, "at": 10.0},
        "first_prompt": "a prompt",
        "first_prompt_at": 5.0,
    }

    def test_the_goal_resolves(self) -> None:
        self.assertEqual(
            (CONDITION, 10.0), annotation_store.prompt_candidate(self.ROW, "session-goal")
        )

    def test_its_prompts_still_do_not(self) -> None:
        self.assertEqual(("", None), annotation_store.prompt_candidate(self.ROW, "first-prompt"))


class TheAntigravityCollectorPublishesTheGoalTest(HarnessContractTestCase):
    def row(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        def build(root: Path, when: float, sid: str, title: str) -> dict[str, str]:
            stores = build_antigravity(root, when, sid, title)
            logs = root / "brain" / sid / ".system_generated" / "logs"
            _jsonl(logs / "transcript_full.jsonl", lines, when)
            _jsonl(logs / "transcript.jsonl", lines, when)
            return stores

        (row,) = self.sessions_for(self.collect(build, when=self.NOW), "antigravity")
        return row

    def test_a_goal_in_the_transcript_is_published_on_the_row(self) -> None:
        when = self.NOW - 100
        row = self.row([set_goal(when + 5)])
        self.assertEqual({"text": CONDITION, "at": when + 5}, row["session_goal"])

    def test_a_session_with_no_goal_publishes_none(self) -> None:
        row = self.row([direction(self.NOW - 100, "keep going")])
        self.assertIsNone(row["session_goal"])


if __name__ == "__main__":
    unittest.main()
