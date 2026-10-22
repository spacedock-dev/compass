"""The harness's "goal met" verdict is a claim Compass tests against the record.

DRC-4948. The evaluator's reason names what it saw: a file it was written to, a check that passed.
The producer looks for those in what the record holds and for anything after the verdict that undoes
them. The check is code over recorded writes and checks, never a model call, and it is stored beside
the criteria and never in them: the verdict cannot lower a level or stand in for a passing check.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, ClassVar, cast

from compass_runtime import annotations as annotation_store
from compass_runtime import reading

from . import test_reading as base
from .test_reading_record_guards import write_fact

GOAL_AT = 60.0
VERDICT_AT = 150.0
GOAL = "the retry tests pass and findings.md exists"


def goal_row(
    reason: str, *, verdict_at: float = VERDICT_AT, verdict: bool = True
) -> dict[str, Any]:
    goal: dict[str, Any] = {"text": GOAL, "at": GOAL_AT}
    if verdict:
        goal["verdict"] = {"met": True, "at": verdict_at, "reason": reason}
    return {
        "harness": "claude",
        "sid": "s1",
        "state": "working",
        "ended_at": None,
        "session_goal": goal,
    }


class AHarnessVerdictIsAClaimTheRecordTests(base.AClaudeCodeReadingProducer):
    ANSWER: ClassVar[dict[str, Any]] = {
        "goal": {"result": "consistent", "cites": [1], "detail": ""}
    }

    def _read(
        self, facts: list[dict[str, Any]], row: dict[str, Any], answer: Any = None
    ) -> dict[str, Any]:
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            row,
            [{"n": 1, "at": 50.0, "goal": GOAL, "lines": []}],
            facts,
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(self.ANSWER if answer is None else answer)),
            read_lines=True,
            read_agent_words=True,
        )
        self.assertEqual("", why)
        self.assertIsNotNone(assessment)
        return cast("dict[str, Any]", assessment)

    def _checked(self, facts: list[dict[str, Any]], reason: str, **kw: Any) -> dict[str, Any]:
        read = self._read([base.WORDS_FACT, *facts], goal_row(reason, **kw))
        return cast("dict[str, Any]", read["goal_verdict"])

    def test_a_file_the_reason_cites_that_the_record_shows_written_agrees(self) -> None:
        checked = self._checked([write_fact("findings.md", at=120.0)], "findings.md was written")
        self.assertEqual(
            {
                "at": VERDICT_AT,
                "check": reading.GOAL_VERDICT_AGREES,
                "why": reading.GOAL_VERDICT_WRITTEN,
                "cites": ("write-1",),
            },
            checked,
        )

    def test_a_later_write_to_the_file_the_reason_cites_disputes_it(self) -> None:
        checked = self._checked(
            [
                write_fact("findings.md", at=120.0),
                write_fact("findings.md", fact_id="w2", at=170.0),
            ],
            "findings.md was written",
        )
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_WRITTEN_AFTER, checked["why"])
        self.assertEqual(("w2",), checked["cites"])

    def test_a_file_named_by_its_folder_path_matches_a_write_of_it(self) -> None:
        checked = self._checked(
            [write_fact("docs/findings.md", at=120.0)], "findings.md was written"
        )
        self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])

    def test_a_path_the_evaluator_elided_with_dots_matches_a_write_by_its_tail(self) -> None:
        reason = "File created successfully at: .../scratchpad/e2e/goal/docs/e2e/findings.md"
        self.assertEqual(
            ("scratchpad/e2e/goal/docs/e2e/findings.md",), reading._verdict_files(reason)
        )
        checked = self._checked([write_fact("docs/e2e/findings.md", at=120.0)], reason)
        self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_WRITTEN, checked["why"])

    def test_an_elided_path_written_again_after_the_verdict_disputes_it(self) -> None:
        checked = self._checked(
            [write_fact("docs/e2e/findings.md", at=170.0)], "wrote .../e2e/docs/e2e/findings.md"
        )
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, checked["check"])

    def test_a_passing_check_of_the_kind_the_reason_claims_agrees(self) -> None:
        checked = self._checked(
            [base.check_fact(result="passed", at=130.0)], "the retry tests pass"
        )
        self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_PASSED, checked["why"])
        self.assertEqual(("check-1",), checked["cites"])

    def test_a_check_that_failed_after_the_verdict_disputes_a_claim_that_it_passed(self) -> None:
        checked = self._checked(
            [
                base.check_fact(result="passed", fact_id="c1", at=130.0),
                base.check_fact(result="failed", fact_id="c2", at=160.0),
            ],
            "the retry tests pass",
        )
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_FAILED, checked["why"])
        self.assertEqual(("c2",), checked["cites"])

    def test_a_check_that_failed_before_the_verdict_and_never_passed_disputes_it(self) -> None:
        checked = self._checked(
            [base.check_fact(result="failed", at=130.0)], "the retry tests pass"
        )
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, checked["check"])

    def test_a_check_of_another_kind_is_not_the_one_the_reason_claims(self) -> None:
        checked = self._checked(
            [base.check_fact(result="failed", at=160.0, summary="ruff check .")],
            "the retry tests pass",
        )
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, checked["check"])

    def test_a_dispute_outweighs_what_agrees(self) -> None:
        checked = self._checked(
            [
                write_fact("findings.md", at=120.0),
                base.check_fact(result="failed", at=160.0),
            ],
            "findings.md was written and the retry tests pass",
        )
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, checked["check"])

    def test_a_cited_file_the_record_never_shows_is_unconfirmed_and_not_disputed(self) -> None:
        # Absence is not contradiction: the listing is capped and the file may have existed.
        checked = self._checked([], "findings.md was written")
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_NOT_FOUND, checked["why"])
        self.assertEqual((), checked["cites"])

    def test_a_reason_that_names_nothing_checkable_is_unconfirmed(self) -> None:
        checked = self._checked(
            [write_fact("findings.md", at=120.0)], "The goal looks done, e.g. 2.1"
        )
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_NOTHING_CHECKABLE, checked["why"])

    def test_a_write_from_before_the_goal_was_set_is_outside_it(self) -> None:
        checked = self._checked([write_fact("findings.md", at=55.0)], "findings.md was written")
        self.assertEqual(reading.GOAL_VERDICT_NOT_FOUND, checked["why"])

    def test_a_session_with_no_verdict_carries_no_check(self) -> None:
        assessment = self._read([base.WORDS_FACT], goal_row("", verdict=False))
        self.assertNotIn("goal_verdict", assessment)

    def test_a_session_with_no_goal_carries_no_check(self) -> None:
        row = {**goal_row("x"), "session_goal": None}
        self.assertNotIn("goal_verdict", self._read([base.WORDS_FACT], row))

    def test_a_malformed_verdict_carries_no_check(self) -> None:
        for bad in (
            {"met": True},
            {"met": False, "at": 1.0, "reason": ""},
            "met",
            {"met": True, "at": "x"},
        ):
            with self.subTest(bad=bad):
                row = goal_row("x")
                row["session_goal"]["verdict"] = bad
                self.assertNotIn("goal_verdict", self._read([base.WORDS_FACT], row))

    def test_the_verdict_never_changes_the_criteria(self) -> None:
        facts = [base.WORDS_FACT, write_fact("findings.md", at=170.0)]
        with_verdict = self._read(facts, goal_row("findings.md was written"))
        without = self._read(facts, goal_row("", verdict=False))
        self.assertEqual(without["criteria"], with_verdict["criteria"])

    def test_a_met_claim_beside_a_departure_leaves_the_departure(self) -> None:
        answer = {"goal": {"result": "departure", "cites": [2], "detail": "wrote outside"}}
        row = goal_row("findings.md was written")
        facts = [base.WORDS_FACT, write_fact("findings.md", at=120.0), base.AGENT_MESSAGE_FACT]
        assessment = self._read(facts, row, answer)
        self.assertEqual(reading.RESULT_DEPARTURE, assessment["criteria"]["goal"]["result"])
        self.assertEqual(reading.GOAL_VERDICT_AGREES, assessment["goal_verdict"]["check"])

    def test_the_verdict_is_not_a_check_the_record_holds(self) -> None:
        recorded = reading.recorded_from([base.WORDS_FACT], "claude", "s1")
        self.assertEqual((), recorded.checks)


class TheStoredCheckIsValidatedOnTheWayBackIn(base.AClaudeCodeReadingProducer):
    def _stored(self, **overrides: Any) -> dict[str, Any]:
        assessment, _why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            goal_row("findings.md was written"),
            [{"n": 1, "at": 50.0, "goal": GOAL, "lines": []}],
            [base.WORDS_FACT, write_fact("findings.md", at=120.0)],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(
                json.dumps({"goal": {"result": "consistent", "cites": [1], "detail": ""}})
            ),
            read_lines=True,
            read_agent_words=True,
        )
        stored = json.loads(json.dumps(assessment))
        stored.update(overrides)
        return cast("dict[str, Any]", stored)

    def test_a_stored_check_reads_back_whole(self) -> None:
        back = annotation_store._assessment(self._stored(), 240)
        assert back is not None
        self.assertEqual(
            {
                "at": VERDICT_AT,
                "check": "agrees",
                "why": "written-before",
                "cites": ("write-1",),
            },
            back["goal_verdict"],
        )

    def test_a_reading_with_no_check_reads_back_with_none(self) -> None:
        stored = self._stored()
        del stored["goal_verdict"]
        back = annotation_store._assessment(stored, 240)
        assert back is not None
        self.assertNotIn("goal_verdict", back)

    def test_a_token_the_producer_never_writes_refuses_the_reading_whole(self) -> None:
        for patch in (
            {"check": "confirmed"},
            {"why": "trust-me"},
            {"at": "later"},
            {"cites": "write-1"},
            {"extra": 1},
        ):
            with self.subTest(patch=patch):
                stored = self._stored()
                stored["goal_verdict"] = {**stored["goal_verdict"], **patch}
                self.assertIsNone(annotation_store._assessment(stored, 240))

    def test_the_key_is_one_the_assessment_declares(self) -> None:
        self.assertIn("goal_verdict", reading.ASSESSMENT_KEYS)


if __name__ == "__main__":
    unittest.main()
