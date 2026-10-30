"""Two answers the record has to back before the model's word is believed.

A `not reached at this stop` on an outcome line is a judgment that work on the line is under way,
so it stands only where the record shows that work: a cited check or write that bears on the line,
a call still in flight after the cited words, or a check or write recorded after them that bears on
the line. Otherwise it reads as not verifiable, as any unknown applicability does
([the clarification](docs/design-reading-a-session.md#clarified-2026-10-07-known-applicability-and-an-actual-claim)).

The agent's explanation after a pasted correction cannot clear a line that a recorded write still
breaks: the write settles the line whatever the reply said
([the record settles a line](docs/design-reading-a-session.md#amended-2026-10-21-the-record-settles-a-line)).

Every fixture is a recorded field shape (`test_reading.check_fact` and the published message
facts); no text came from a real session.
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any, cast

from compass_runtime import reading

from . import test_reading as base
from .test_reading_record_guards import write_fact

PLAN = "The handler change is next; I will wire it and rerun the suite."


def said(at: float = 99.0, *, fact_id: str = "m1", words: str = PLAN) -> dict[str, Any]:
    """One top-level agent message, as `project_context` publishes it."""
    return {
        **base.AGENT_MESSAGE_FACT,
        "fact_id": fact_id,
        "summary": words,
        reading.AGENT_WORDS_FIELD: words,
        "at": at,
    }


def launch(at: float) -> dict[str, Any]:
    """A subagent dispatch, recorded as a `launch` tool report: what was started, not its work."""
    return base.check_fact(
        fact_id="launch-1",
        subject="launch",
        result="",
        result_source="",
        summary="Agent: review the handler",
        at=at,
    )


def later_write(path: str, at: float) -> dict[str, Any]:
    return write_fact(path, fact_id=f"w-{path}", at=at)


class ANotReachedLineNeedsWorkOnItUnderway(unittest.TestCase):
    """Measured on the ninth Claude Code qualification run: case `8b8c1a02` line_1, marked to
    abstain, was answered `not reached` in two of three repeats resting on messages alone at a
    finished turn, with nothing in flight and no work recorded after them. The shape here is that
    record's: the reader's message, a subagent dispatch, and the agent's messages after it."""

    def resolved(
        self,
        line: str,
        later: tuple[dict[str, Any], ...] = (),
        *,
        cite: tuple[str, ...] = ("m1",),
        scope: str = reading.SCOPE_LAST_TURN,
        name: str = "line_1",
        open_call_at: float | None = None,
    ) -> reading.Criterion:
        ledger = reading.build_ledger(
            [base.WORDS_FACT, said(), *later],
            "claude",
            "s1",
            tool_output={},
            read_agent_words=True,
        )
        _prompt, selection = reading.build_prompt(
            ledger, goal="Make the webhook retry.", lines=(line,), max_bytes=16_384
        )
        rows = selection.by_index()
        indices = [i for i, row in rows.items() if row["id"] in cite]
        self.assertEqual(len(cite), len(indices), "every cited fact is on the menu")
        answer = {"result": "not_reached", "cites": indices, "detail": "Waiting on the handler."}
        parsed = reading.parse_reply(
            json.dumps({name: answer}),
            reading.constraints_for(selection.lines, claims=selection.asked_claims),
        )
        return reading.resolve(
            parsed,
            selection,
            goal="Make the webhook retry.",
            lines=selection.lines,
            detail_cap_chars=200,
            scope=scope,
            open_call_at=open_call_at,
        )[name]

    def test_a_not_reached_resting_on_words_with_nothing_underway_is_not_verifiable(self) -> None:
        for scope in (reading.SCOPE_LAST_TURN, reading.SCOPE_MID_FLIGHT):
            with self.subTest(scope=scope):
                row = self.resolved("The retry handler is wired", scope=scope)
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
                self.assertEqual("", row["detail"])

    def test_the_recorded_shape_of_the_ninth_runs_failure_is_not_verifiable(self) -> None:
        # The reader's message and the agent's, with a dispatch between them: a dispatch says what
        # was started, not that work on this line is going on.
        reader = {**base.WORDS_FACT, "fact_id": "u2", "summary": "keep going", "at": 120.0}
        row = self.resolved(
            "Only the approved changes are applied",
            (launch(110.0), reader, said(130.0, fact_id="m2", words="Applied what I could.")),
            cite=("u2", "m2"),
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_later_work_that_does_not_bear_on_the_line_does_not_hold_it(self) -> None:
        row = self.resolved(
            "src/handler.py retries on a 503", (later_write("docs/notes.md", 120.0),)
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_work_before_the_cited_words_does_not_hold_it(self) -> None:
        # The write is the work the words already describe; nothing is going on after them.
        row = self.resolved(
            "src/handler.py retries on a 503",
            (later_write("src/handler.py", 95.0), said(130.0, fact_id="m2")),
            cite=("m2",),
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    # Controls: a not reached the record backs stands as the model gave it.

    def test_a_cited_write_to_the_path_the_line_names_holds_it(self) -> None:
        row = self.resolved(
            "src/handler.py retries on a 503",
            (later_write("src/handler.py", 120.0),),
            cite=("m1", "w-src/handler.py"),
        )
        self.assertEqual(reading.RESULT_NOT_REACHED, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])
        self.assertEqual("Waiting on the handler.", row["detail"])

    def test_a_check_recorded_after_the_words_that_covers_the_line_holds_it(self) -> None:
        tests = base.check_fact(fact_id="c9", result="failed", at=120.0, summary="pytest -q")
        row = self.resolved("The retry tests pass", (tests,))
        self.assertEqual(reading.RESULT_NOT_REACHED, row["result"])

    def test_a_call_in_flight_after_the_words_holds_it(self) -> None:
        row = self.resolved(
            "The retry handler is wired", scope=reading.SCOPE_MID_FLIGHT, open_call_at=120.0
        )
        self.assertEqual(reading.RESULT_NOT_REACHED, row["result"])

    def test_a_call_opened_before_the_words_does_not(self) -> None:
        row = self.resolved(
            "The retry handler is wired", scope=reading.SCOPE_MID_FLIGHT, open_call_at=95.0
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_the_goal_is_left_to_the_reading(self) -> None:
        # A goal has no narrower meaning than the whole session, so its applicability to the work
        # is known; the guard is for a line, whose applicability a message alone does not show.
        row = self.resolved("The retry handler is wired", name="goal")
        self.assertEqual(reading.RESULT_NOT_REACHED, row["result"])


class TheRecordShowsWorkUnderWayWithoutAGrant(base.AClaudeCodeReadingProducer):
    """A press with no tool-output grant sends no write or check, but the record still holds them,
    and a write that bears on the line shows its work under way as surely as one the prompt
    carried. Nothing the guard reads is sent."""

    def _line(self, write_at: float) -> dict[str, Any]:
        answer = {"line_1": {"result": "not_reached", "cites": [2], "detail": "Waiting on it."}}
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "idle", "turn_end_at": 150.0},
            [
                {
                    "n": 1,
                    "at": 50.0,
                    "goal": "make retry robust",
                    "lines": ["src/handler.py retries"],
                }
            ],
            [base.WORDS_FACT, said(), write_fact("src/handler.py", at=write_at)],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(answer)),
            read_lines=True,
            read_agent_words=True,
            admit_turn_stop=True,
        )
        self.assertEqual("", why)
        self.assertEqual(reading.SCOPE_LAST_TURN, cast("Any", assessment)["scope"])
        return cast("dict[str, Any]", cast("Any", assessment)["criteria"]["line_1"])

    def test_a_recorded_write_after_the_words_holds_the_line_with_no_grant(self) -> None:
        row = self._line(120.0)
        self.assertEqual(reading.RESULT_NOT_REACHED, row["result"])
        self.assertEqual(("m1",), row["cites"])

    def test_a_recorded_write_before_the_words_does_not(self) -> None:
        row = self._line(95.0)
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])


class AClearingOnTheAgentsWordDoesNotOutliveADepartingWrite(base.AClaudeCodeReadingProducer):
    """The steer-then-explain shape: a write breaks a line, the reader pastes Compass's correction,
    the agent explains the write, and the model answers the line `consistent` on that explanation.
    The record settles the line as a departure whatever the reply said, and only where a recorded
    write does: a line with no folder in its words stays the model's judgment."""

    PASTED: dict[str, Any] = {  # noqa: RUF012 - read only
        **base.WORDS_FACT,
        "fact_id": "u-paste",
        "summary": "Back to my goal: no file under frontend/e2e is edited.",
        reading.COPIED_FLAG: True,
        "at": 110.0,
    }
    EXPLAINED = "I edited the e2e fixture on purpose; the proof needs that state."

    def _line(self, facts: list[dict[str, Any]], line: str, cite: str) -> dict[str, Any]:
        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            found = re.search(rf"\[(\d+)\] [^\n]*{re.escape(cite)}", prompt)
            index = [int(found.group(1))] if found else []
            answer = {"line_1": {"result": "consistent", "cites": index, "detail": ""}}
            return json.dumps(answer), "ok"

        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [{"n": 1, "at": 50.0, "goal": "move the proof into Storybook", "lines": [line]}],
            facts,
            now=200.0,
            stamp_text="read at 10:00",
            model=model,
            tool_output=base.ADMITTED,
            read_lines=True,
            read_agent_words=True,
        )
        self.assertEqual("", why)
        return cast("dict[str, Any]", cast("Any", assessment)["criteria"]["line_1"])

    def _two_turns(self, written: str) -> list[dict[str, Any]]:
        return [
            base.WORDS_FACT,
            write_fact(written),
            self.PASTED,
            said(120.0, fact_id="m-explain", words=self.EXPLAINED),
        ]

    def test_the_explanation_does_not_clear_a_line_the_write_still_breaks(self) -> None:
        row = self._line(
            self._two_turns("frontend/e2e/fixtures/state.json"),
            "No file under frontend/e2e is edited",
            self.EXPLAINED,
        )
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(reading.WHY_RECORDED_WRITE, row["why"])
        self.assertEqual(("write-1",), row["cites"])

    # Since 2026-10-30 the explanation clears no line in a window that holds a recorded write,
    # whether or not the line's words name a folder: a consistent there needs a cited write or a
    # passing check. A line with no folder in its words was this amendment's named residual risk.

    def test_the_explanation_does_not_clear_a_line_a_write_does_not_break_either(self) -> None:
        row = self._line(
            self._two_turns("frontend/src/stories/Proof.stories.tsx"),
            "No file under frontend/e2e is edited",
            self.EXPLAINED,
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
        self.assertEqual(("m-explain",), row["cites"])

    def test_a_line_with_no_folder_in_its_words_is_not_cleared_by_the_explanation(self) -> None:
        row = self._line(
            self._two_turns("frontend/e2e/fixtures/state.json"),
            "Leave the existing fixtures alone",
            self.EXPLAINED,
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    # Controls: the explanation carries a line where nothing was written, and a pass carries one.

    def test_the_explanation_stands_where_the_window_holds_no_write(self) -> None:
        facts = [
            base.WORDS_FACT,
            self.PASTED,
            said(120.0, fact_id="m-explain", words=self.EXPLAINED),
        ]
        row = self._line(facts, "Leave the existing fixtures alone", self.EXPLAINED)
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertEqual(("m-explain",), row["cites"])

    def test_a_consistent_resting_on_a_passing_check_stands(self) -> None:
        passed = base.check_fact(fact_id="c-pass", result="passed", at=125.0)
        row = self._line(
            [*self._two_turns("frontend/src/stories/Proof.stories.tsx"), passed],
            "The retry tests pass",
            "tests/test_retry.py",
        )
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertIn("c-pass", row["cites"])


if __name__ == "__main__":
    unittest.main()
