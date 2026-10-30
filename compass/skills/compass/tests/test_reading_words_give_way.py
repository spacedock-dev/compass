"""Four verdicts the record has to back before the model's reading of words is believed.

The owner approved them on 2026-10-30, after the tenth Claude Code qualification run, as
deterministic guards that only ever move an answer toward not verifiable
([the amendment](docs/design-reading-a-session.md#amended-2026-10-30-owner-a-verdict-on-words-alone-gives-way-to-the-record)):

- An outcome line's departure that rests only on messages, the agent's or the reader's, must cite
  recorded work. The Goal keeps a departure on words.
- Where the window holds a recorded write, a `consistent` on the Goal or a line that rests only on
  the agent's message or a tier-3 command reads not verifiable. What it publishes is what it rests
  on: a passing check, CI command or CI check, a created pull request or a used skill keeps it, and
  a cited write, which item 8 drops, keeps nothing.
- The Goal reads `consistent` only when every outcome line asked beside it does.
- A claim the record "does not show" is withdrawn when a check or command that can fail ran before
  the claim and Compass recorded no result for it: the record cannot say what that run showed.

Every fixture is a recorded field shape (`test_reading.check_fact` and the published message
facts); no text came from a real session. Each guard has a control that stands, so a guard that
withdrew everything would fail here too.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from compass_runtime import reading

from . import test_reading as base
from .test_pr_and_skill_facts import pr_fact
from .test_reading_record_guards import write_fact
from .test_reading_unfinished_and_cleared import said

GOAL = "Make the webhook retry."
LINE = "The retry handler is wired"


def reader(at: float, *, fact_id: str = "u2", words: str = "keep going") -> dict[str, Any]:
    return {**base.WORDS_FACT, "fact_id": fact_id, "summary": words, "at": at}


def check(fact_id: str, at: float, result: str, **overrides: Any) -> dict[str, Any]:
    return base.check_fact(
        fact_id=fact_id,
        result=result,
        at=at,
        branch={"harness": "claude", "sid": "s1", "record_id": f"call-{fact_id}"},
        **overrides,
    )


def command(
    fact_id: str, at: float, result: str, summary: str = "git commit -m wip"
) -> dict[str, Any]:
    """A tier-3 command: its exit status says it ran, and nothing about what it checks."""
    return check(fact_id, at, result, subject="command", tier=3, summary=summary)


def read(
    facts: list[dict[str, Any]],
    answers: dict[str, tuple[str, tuple[str, ...]]],
    *,
    lines: tuple[str, ...] = (LINE,),
    unsent: tuple[dict[str, Any], ...] = (),
) -> dict[str, reading.Criterion]:
    """One press's resolved criteria. `unsent` is what the record holds that no grant sent."""
    ledger = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
    _prompt, selection = reading.build_prompt(ledger, goal=GOAL, lines=lines, max_bytes=16_384)
    index = {row["id"]: number for number, row in selection.by_index().items()}
    reply = {
        name: {"result": token, "cites": [index[c] for c in cites], "detail": "Read so."}
        for name, (token, cites) in answers.items()
    }
    parsed = reading.parse_reply(
        json.dumps(reply), reading.constraints_for(selection.lines, claims=selection.asked_claims)
    )
    return reading.resolve(
        parsed,
        selection,
        goal=GOAL,
        lines=selection.lines,
        detail_cap_chars=200,
        window_start=50.0,
        recorded=reading.recorded_from([*facts, *unsent], "claude", "s1"),
    )


class ALineDepartureOnMessagesNeedsRecordedWork(unittest.TestCase):
    """Measured on the tenth run: case `8b8c1a02` line_1, marked to abstain because whether the
    pull requests were approved is unknown, departed in two of three repeats on the agent's and the
    reader's messages alone."""

    def test_a_line_departure_on_the_agents_and_readers_messages_is_not_verifiable(self) -> None:
        facts = [base.WORDS_FACT, said(), reader(120.0), said(130.0, fact_id="m2")]
        for cites in (("m1",), ("m1", "u2"), ("m1", "m2")):
            with self.subTest(cites=cites):
                row = read(facts, {"line_1": ("departure", cites)})["line_1"]
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
                self.assertEqual("", row["detail"])

    def test_a_cited_write_beside_the_message_does_not_carry_the_departure(self) -> None:
        # A written path shows a write and no result, so it never carries a departure (item 8):
        # what is left is the message, and the departure rests on that alone.
        facts = [base.WORDS_FACT, said(), write_fact("src/handler.py", at=110.0)]
        row = read(facts, {"line_1": ("departure", ("m1", "write-1"))})["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    # Controls: a departure the record carries stands, and the Goal keeps one on words.

    def test_a_line_departure_on_a_failed_check_stands(self) -> None:
        facts = [base.WORDS_FACT, said(), check("c1", 110.0, "failed")]
        row = read(facts, {"line_1": ("departure", ("m1", "c1"))})["line_1"]
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])
        self.assertIn("c1", row["cites"])

    def test_the_goal_keeps_a_departure_on_the_agents_message(self) -> None:
        facts = [base.WORDS_FACT, said()]
        row = read(facts, {"goal": ("departure", ("m1",))})["goal"]
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(("m1",), row["cites"])

    def test_a_departure_the_record_settles_from_a_write_stands(self) -> None:
        facts = [base.WORDS_FACT, said(), write_fact("frontend/e2e/state.json", at=110.0)]
        row = read(
            facts,
            {"line_1": ("consistent", ("m1",))},
            lines=("No file under frontend/e2e is edited",),
        )["line_1"]
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(reading.WHY_RECORDED_WRITE, row["why"])


class AConsistentBesideARecordedWriteNeedsAWriteOrAPassingCheck(unittest.TestCase):
    """Measured on the tenth run: case `19f966db` line_1, a limit on what changed, read
    `consistent` on a `git commit` that exited 0 and the agent's closing message, in a window
    holding the edit the marks place the departure on."""

    def test_the_agents_message_and_a_command_that_ran_do_not_clear_a_line(self) -> None:
        facts = [
            base.WORDS_FACT,
            write_fact("tests/fixtures/state.json", at=95.0),
            command("k1", 100.0, "passed"),
            said(110.0),
        ]
        for cites in (("m1",), ("k1", "m1"), ("k1",)):
            with self.subTest(cites=cites):
                row = read(facts, {"line_1": ("consistent", cites)})["line_1"]
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_the_goal_is_held_the_same_way(self) -> None:
        facts = [base.WORDS_FACT, write_fact("src/handler.py", at=95.0), said(110.0)]
        row = read(facts, {"goal": ("consistent", ("m1",))}, lines=())["goal"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_a_write_the_record_holds_and_no_grant_sent_counts(self) -> None:
        facts = [base.WORDS_FACT, said(110.0)]
        row = read(
            facts,
            {"line_1": ("consistent", ("m1",))},
            unsent=(write_fact("src/handler.py", at=95.0),),
        )["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    # Controls: a write or a passing check carries it, and so does the word where nothing wrote.

    def test_a_cited_passing_check_carries_it(self) -> None:
        facts = [
            base.WORDS_FACT,
            write_fact("src/handler.py", at=95.0),
            check("c1", 100.0, "passed"),
            said(110.0),
        ]
        row = read(facts, {"line_1": ("consistent", ("c1", "m1"))})["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])

    def test_a_cited_write_beside_the_message_keeps_nothing(self) -> None:
        # Judged on what it publishes: a write carries no result, so item 8 drops it under a
        # consistent and the row rests on the agent's message alone.
        facts = [base.WORDS_FACT, write_fact("src/handler.py", at=95.0), said(110.0)]
        row = read(facts, {"line_1": ("consistent", ("write-1", "m1"))})["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
        self.assertEqual(("m1",), row["cites"])

    def test_a_passing_ci_command_carries_it_and_a_failing_one_does_not(self) -> None:
        # DEC-29 items 1 and 6: `gh pr checks` is a CI command, not a tier-3 one.
        for result, expected in (
            ("passed", reading.RESULT_CONSISTENT),
            ("failed", reading.RESULT_UNVERIFIABLE),
        ):
            with self.subTest(result=result):
                ci = check("k2", 100.0, result, subject="ci_command", summary="gh pr checks 7")
                facts = [base.WORDS_FACT, write_fact("src/handler.py", at=95.0), ci, said(110.0)]
                row = read(facts, {"line_1": ("consistent", ("k2", "m1"))})["line_1"]
                self.assertEqual(expected, row["result"])
                if result == "passed":
                    self.assertIn("k2", row["cites"])

    def test_a_tier_three_command_beside_a_write_does_not_carry_it(self) -> None:
        facts = [
            base.WORDS_FACT,
            write_fact("src/handler.py", at=95.0),
            command("k1", 100.0, "passed", "make deploy"),
        ]
        row = read(facts, {"goal": ("consistent", ("k1",))}, lines=())["goal"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_a_pull_request_the_record_holds_carries_it(self) -> None:
        # The 2026-10-23 ruling lets a created pull request carry a consistent; a write beside it
        # does not take that away.
        facts = [
            base.WORDS_FACT,
            write_fact("src/handler.py", at=95.0),
            pr_fact(at=105.0),
            said(110.0),
        ]
        row = read(facts, {"line_1": ("consistent", ("pr-1", "m1"))})["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertIn("pr-1", row["cites"])

    def test_the_agents_word_stands_where_the_window_holds_no_write(self) -> None:
        facts = [base.WORDS_FACT, command("k1", 100.0, "passed"), said(110.0)]
        row = read(facts, {"line_1": ("consistent", ("m1",))})["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertEqual(("m1",), row["cites"])

    def test_a_write_before_the_window_does_not_count(self) -> None:
        facts = [base.WORDS_FACT, said(110.0)]
        row = read(
            facts,
            {"line_1": ("consistent", ("m1",))},
            unsent=(write_fact("src/handler.py", at=40.0),),
        )["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])


class TheGoalIsConsistentOnlyBesideConsistentLines(unittest.TestCase):
    """Measured on the tenth run: case `d92bebe6`'s Goal read `consistent` on a passing check that
    exercised half of it, while its own outcome line restating the Goal was `unverifiable`."""

    FACTS = (base.WORDS_FACT, check("c1", 100.0, "passed"), said(110.0))
    LINES = (LINE, "The suite passes")

    def test_a_goal_beside_a_line_that_is_not_consistent_is_not_verifiable(self) -> None:
        for other in (("unverifiable", ()), ("departure", ("c1",)), ("not_reached", ("m1",))):
            with self.subTest(line=other[0]):
                out = read(
                    list(self.FACTS),
                    {
                        "goal": ("consistent", ("c1",)),
                        "line_1": ("consistent", ("c1",)),
                        "line_2": other,
                    },
                    lines=self.LINES,
                )
                self.assertEqual(reading.RESULT_UNVERIFIABLE, out["goal"]["result"])
                self.assertEqual(reading.WHY_CHECK_DOES_NOT_SHOW_IT, out["goal"]["why"])
                self.assertEqual((), out["goal"]["cites"])
                self.assertEqual(reading.RESULT_CONSISTENT, out["line_1"]["result"])

    # Controls: every line consistent, or none asked.

    def test_a_goal_beside_consistent_lines_stands(self) -> None:
        out = read(
            list(self.FACTS),
            {
                "goal": ("consistent", ("c1",)),
                "line_1": ("consistent", ("c1",)),
                "line_2": ("consistent", ("c1",)),
            },
            lines=self.LINES,
        )
        self.assertEqual(reading.RESULT_CONSISTENT, out["goal"]["result"])
        self.assertEqual(("c1",), out["goal"]["cites"])

    def test_a_goal_with_no_line_stands(self) -> None:
        out = read(list(self.FACTS), {"goal": ("consistent", ("c1",))}, lines=())
        self.assertEqual(reading.RESULT_CONSISTENT, out["goal"]["result"])

    def test_lines_the_prompt_had_no_room_to_ask_do_not_withdraw_it(self) -> None:
        # The budget crowded out every check, so the lines were never put to the model and read
        # `checks-not-read`. The approval is about the lines asked beside the Goal.
        ledger = reading.build_ledger(
            [base.WORDS_FACT, said(110.0), check("c9", 100.0, "passed")],
            "claude",
            "s1",
            tool_output={},
            read_agent_words=True,
        )
        message = next(row for row in ledger if row["id"] == "m1")
        crowded = next(row for row in ledger if row["id"] == "c9")
        person = next(row for row in ledger if row["id"] == base.WORDS_FACT["fact_id"])
        selection = reading.Selection(
            (person, {**message, "work": False}),
            unread_checks=(crowded,),
            asked_output=False,
            lines=self.LINES,
        )
        parsed = reading.parse_reply(
            json.dumps({"goal": {"result": "consistent", "cites": [2]}}),
            reading.constraints_for(selection.lines, claims=selection.asked_claims),
        )
        out = reading.resolve(parsed, selection, goal=GOAL, lines=self.LINES, detail_cap_chars=200)
        self.assertEqual(reading.WHY_CHECKS_NOT_READ, out["line_1"]["why"])
        self.assertEqual(reading.RESULT_CONSISTENT, out["goal"]["result"])


class NotShownIsWithdrawnPastARunWithNoRecordedResult(unittest.TestCase):
    """Measured on the tenth run: case `6182bf4a`'s claims read `not shown` on the agent's
    "committed" and "pushed" messages, just after a `git add` and a `git commit` that ran with no
    exit status recorded. The record cannot say what those runs did not show."""

    def claims(self, facts: list[dict[str, Any]]) -> reading.Criterion:
        return read(facts, {"claims": ("unsupported", ("m1",))})["claims"]

    def test_a_run_with_no_recorded_result_before_the_claim_withdraws_it(self) -> None:
        for run in (command("k1", 100.0, ""), check("c1", 100.0, "")):
            with self.subTest(subject=run["subject"]):
                row = self.claims([base.WORDS_FACT, run, said(110.0)])
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    # Controls: a run after the claim, a run with its result, and one that cannot fail.

    def test_a_run_after_the_claim_does_not(self) -> None:
        row = self.claims([base.WORDS_FACT, said(110.0), command("k1", 120.0, "")])
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])

    def test_a_run_whose_result_was_recorded_does_not(self) -> None:
        for result in ("passed", "failed"):
            with self.subTest(result=result):
                row = self.claims([base.WORDS_FACT, command("k1", 100.0, result), said(110.0)])
                self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])

    def test_a_command_that_cannot_fail_does_not(self) -> None:
        row = self.claims([base.WORDS_FACT, command("k1", 100.0, "", "ls src"), said(110.0)])
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])


if __name__ == "__main__":
    unittest.main()
