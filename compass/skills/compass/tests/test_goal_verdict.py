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
        self,
        facts: list[dict[str, Any]],
        row: dict[str, Any],
        answer: Any = None,
        tool_output: reading.ToolOutput | None = None,
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
            tool_output=tool_output,
        )
        self.assertEqual("", why)
        self.assertIsNotNone(assessment)
        return cast("dict[str, Any]", assessment)

    def _checked(
        self,
        facts: list[dict[str, Any]],
        reason: str,
        removals: tuple[tuple[str, float, str], ...] = (),
        **kw: Any,
    ) -> dict[str, Any]:
        output = (
            reading.ToolOutput(destination="", label="x", removals=removals) if removals else None
        )
        read = self._read([base.WORDS_FACT, *facts], goal_row(reason, **kw), tool_output=output)
        return cast("dict[str, Any]", read["goal_verdict"])

    def test_a_file_the_reason_names_that_was_deleted_after_the_verdict_disputes_it(self) -> None:
        # DRC-4948 on a real session: notes.md was created, the harness said met, a later turn rm'd it.
        checked = self._checked(
            [write_fact("docs/e2e/notes.md", at=120.0)],
            "the file docs/e2e/notes.md was created and read back",
            removals=(("docs/e2e/notes.md", 170.0, "deleted"),),
        )
        self.assertEqual(
            {
                "at": VERDICT_AT,
                "check": reading.GOAL_VERDICT_DISPUTED,
                "why": reading.GOAL_VERDICT_DELETED_AFTER,
                "cites": (),
                "path": "docs/e2e/notes.md",
                "changed_at": 170.0,
            },
            checked,
        )

    def test_a_file_and_its_folder_removed_in_one_call_name_the_file(self) -> None:
        # Measured on met-undone2: `rm docs/e2e/notes.md && rmdir docs/e2e` gives both the same time,
        # and the card named the folder, not the file the verdict relied on.
        for removals in (
            (("docs/e2e", 170.0, "deleted"), ("docs/e2e/notes.md", 170.0, "deleted")),
            (("docs/e2e/notes.md", 170.0, "deleted"), ("docs/e2e", 170.0, "deleted")),
        ):
            with self.subTest(order=[path for path, _at, _kind in removals]):
                checked = self._checked(
                    [write_fact("docs/e2e/notes.md", at=120.0)],
                    "the file docs/e2e/notes.md was created and read back",
                    removals=removals,
                )
                self.assertEqual("docs/e2e/notes.md", checked["path"])

    def test_a_move_away_after_the_verdict_disputes_it_as_moved(self) -> None:
        checked = self._checked(
            [write_fact("findings.md", at=120.0)],
            "findings.md was written",
            removals=(("findings.md", 170.0, "moved"),),
        )
        self.assertEqual(reading.GOAL_VERDICT_MOVED_AFTER, checked["why"])
        self.assertEqual("findings.md", checked["path"])

    def test_deleting_the_folder_that_holds_the_file_disputes_it(self) -> None:
        checked = self._checked(
            [write_fact("docs/e2e/notes.md", at=120.0)],
            "docs/e2e/notes.md exists",
            removals=(("docs/e2e", 170.0, "deleted"),),
        )
        self.assertEqual(reading.GOAL_VERDICT_DELETED_AFTER, checked["why"])
        self.assertEqual("docs/e2e", checked["path"])

    def test_the_condition_naming_the_file_is_enough_when_the_reason_names_none(self) -> None:
        # GOAL names findings.md; the reason only says tests passed.
        checked = self._checked(
            [], "the retry tests pass", removals=(("findings.md", 170.0, "deleted"),)
        )
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_DELETED_AFTER, checked["why"])

    def test_a_removal_from_before_the_verdict_does_not_dispute_it(self) -> None:
        checked = self._checked(
            [write_fact("findings.md", at=120.0)],
            "findings.md was written",
            removals=(("findings.md", 100.0, "deleted"),),
        )
        self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])
        self.assertNotIn("path", checked)

    def test_a_file_written_again_after_the_removal_is_written_after_not_deleted(self) -> None:
        checked = self._checked(
            [
                write_fact("findings.md", at=120.0),
                write_fact("findings.md", fact_id="w2", at=190.0),
            ],
            "findings.md was written",
            removals=(("findings.md", 170.0, "deleted"),),
        )
        self.assertEqual(reading.GOAL_VERDICT_WRITTEN_AFTER, checked["why"])

    def test_a_removal_of_an_unrelated_file_leaves_the_verdict_alone(self) -> None:
        checked = self._checked(
            [write_fact("findings.md", at=120.0)],
            "findings.md was written",
            removals=(("scratch.txt", 170.0, "deleted"),),
        )
        self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])

    def test_nothing_in_the_record_for_or_against_stays_unconfirmed(self) -> None:
        checked = self._checked([], "findings.md was written")
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, checked["check"])

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

    def test_a_claim_with_no_reason_is_tested_against_what_the_goal_names(self) -> None:
        # Every Codex verdict has an empty reason. The goal names findings.md, so a write of it before
        # the verdict agrees, and no write of it is "not found" rather than "nothing checkable".
        checked = self._checked([write_fact("docs/findings.md", at=120.0)], "")
        self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])
        self.assertEqual(reading.GOAL_VERDICT_WRITTEN, checked["why"])
        missing = self._checked([], "")
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, missing["check"])
        self.assertEqual(reading.GOAL_VERDICT_NOT_FOUND, missing["why"])

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

    def test_a_path_followed_by_a_closing_quote_bracket_or_period_is_still_named(self) -> None:
        for reason, expected in (
            ('wrote docs/plans/DRC-4754-b.md".', "docs/plans/DRC-4754-b.md"),
            ('the file "docs/plans/DRC-4754-b.md".', "docs/plans/DRC-4754-b.md"),
            ('created .../plans/DRC-4754-b.md".', "plans/DRC-4754-b.md"),
            ("see 'DRC-4754-b.md'.", "DRC-4754-b.md"),
            ("file docs/DRC-4754-b.md).", "docs/DRC-4754-b.md"),
            ('wrote "docs/DRC-4754-b.md",', "docs/DRC-4754-b.md"),
            ("see \u201cDRC-4754-b.md\u201d.", "DRC-4754-b.md"),
            ("file DRC-4754-b.md.", "DRC-4754-b.md"),
        ):
            with self.subTest(reason=reason):
                self.assertEqual((expected,), reading._verdict_files(reason))

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

    def test_a_ci_job_name_in_the_reason_does_not_agree_on_a_local_pytest_run(self) -> None:
        passing = [base.check_fact(result="passed", at=130.0)]
        for reason in (
            "the server-unittest pass shows it",
            "coverage-gate pass and server-unittest pass, nothing marked fail",
            "the tests pass in CI",
            "the workflow shows the tests passed",
            "the tests passed https://github.com/acme/widgets/actions/runs/123456",
            "the tests passed https://gitlab.com/acme/widgets/-/pipelines/99",
            "`server-unittest` passed",
            "server-unittest passes",
            "server-unittest is green",
            "server-unittest succeeded",
            "server-unittest: pass",
            "server-unittest (pass)",
            "'server-unittest' passed",
            "the server-unittest job passed",
            "the server-unittest check passed",
            "nothing red; build-and-test pass",
            "tests passed in github actions",
            "tests passed on ci",
        ):
            with self.subTest(reason=reason):
                checked = self._checked(passing, reason)
                self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, checked["check"])

    def test_a_ci_job_in_the_reason_claims_no_kind(self) -> None:
        self.assertEqual(
            frozenset(), reading._verdict_check_kinds("ci/lint failed earlier, then passed")
        )

    def test_a_hyphen_joined_job_name_holding_a_kind_word_claims_no_kind(self) -> None:
        for reason in ("server-unittest pass", "build-and-test passed", "ci/lint pass"):
            with self.subTest(reason=reason):
                self.assertEqual(frozenset(), reading._verdict_check_kinds(reason))

    def test_a_joined_list_of_kinds_is_a_local_claim(self) -> None:
        for reason, kinds in (
            ("pytest/ruff pass", {"test", "lint"}),
            ("lint/type-check pass", {"lint", "types"}),
            ("tests/lint pass", {"test", "lint"}),
            ("pytest-ruff pass", {"test", "lint"}),
        ):
            with self.subTest(reason=reason):
                self.assertEqual(frozenset(kinds), reading._verdict_check_kinds(reason))

    def test_outcome_line_coverage_ignores_remote_phrasing(self) -> None:
        self.assertTrue(reading.covers_line("the tests pass in CI", "pytest -x"))
        self.assertTrue(reading.covers_line("the tests pass in CI", "python3 -m pytest tests"))

    def test_local_claims_that_look_like_job_names_keep_their_kind(self) -> None:
        for reason in (
            "tests: 14/14 pass",
            "all tests in tests/unit pass",
            "the tests in compass/skills pass",
            "pytest 14/14 passed",
            "CI-related tests pass",
            "Actions: all tests pass",
            "the ciremoterun tests pass",
        ):
            with self.subTest(reason=reason):
                self.assertEqual(frozenset({"test"}), reading._verdict_check_kinds(reason))

    def test_all_the_local_tests_passing_still_agrees(self) -> None:
        for reason in ("All 14 tests pass", "pytest passes", "type-check passed"):
            with self.subTest(reason=reason):
                fact = base.check_fact(result="passed", at=130.0)
                if reason.startswith("type"):
                    fact = base.check_fact(result="passed", at=130.0, summary="mypy")
                checked = self._checked([fact], reason)
                self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])

    def test_a_reason_mixing_a_local_claim_and_a_ci_job_agrees_on_the_local_one(self) -> None:
        checked = self._checked(
            [base.check_fact(result="passed", at=130.0)],
            "All 14 tests pass locally and the server-unittest check on the PR passed",
        )
        self.assertEqual(reading.GOAL_VERDICT_AGREES, checked["check"])
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

    def test_a_stored_removal_dispute_reads_back_whole_with_its_file_and_time(self) -> None:
        stored = self._stored()
        stored["goal_verdict"] = {
            "at": VERDICT_AT,
            "check": "disputed",
            "why": "deleted-after",
            "cites": [],
            "path": "docs/e2e/notes.md",
            "changed_at": 170.0,
        }
        back = annotation_store._assessment(stored, 240)
        assert back is not None
        self.assertEqual("docs/e2e/notes.md", back["goal_verdict"]["path"])
        self.assertEqual(170.0, back["goal_verdict"]["changed_at"])

    def test_the_file_and_time_travel_together_and_only_with_a_removal(self) -> None:
        for patch in (
            {"path": "a.md"},
            {"changed_at": 170.0},
            {"why": "written-after", "path": "a.md", "changed_at": 170.0},
            {"why": "deleted-after", "path": 5, "changed_at": 170.0},
            {"why": "deleted-after", "path": "a.md", "changed_at": "late"},
        ):
            with self.subTest(patch=patch):
                stored = self._stored()
                stored["goal_verdict"] = {**stored["goal_verdict"], **patch}
                back = annotation_store._assessment(stored, 240)
                assert back is not None
                self.assertNotIn("goal_verdict", back)

    def test_a_token_the_producer_never_writes_drops_the_check_and_keeps_the_reading(self) -> None:
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
                back = annotation_store._assessment(stored, 240)
                assert back is not None
                self.assertNotIn("goal_verdict", back)

    def _pair(self, check: str, why: str, cites: list[str]) -> dict[str, Any]:
        stored = self._stored()
        stored["goal_verdict"] = {"at": VERDICT_AT, "check": check, "why": why, "cites": cites}
        if why in reading.GOAL_VERDICT_REMOVAL_WHYS:
            stored["goal_verdict"].update({"path": "a.md", "changed_at": 170.0})
        if why == reading.GOAL_VERDICT_QUOTED:
            stored["goal_verdict"]["quoted"] = 1
        return stored

    def test_every_pair_the_producer_gives_is_accepted(self) -> None:
        for why, (check, cited) in reading.GOAL_VERDICT_PAIRS.items():
            with self.subTest(why=why):
                back = annotation_store._assessment(
                    self._pair(check, why, ["write-1"] if cited else []), 240
                )
                assert back is not None
                self.assertEqual(check, back["goal_verdict"]["check"])

    def test_the_producer_and_the_validator_read_one_table(self) -> None:
        self.assertEqual(set(reading.GOAL_VERDICT_WHYS), set(reading.GOAL_VERDICT_PAIRS))
        self.assertEqual(
            set(reading.GOAL_VERDICT_CHECKS),
            {check for check, _ in reading.GOAL_VERDICT_PAIRS.values()},
        )

    def test_a_pair_the_producer_cannot_emit_drops_the_check_and_keeps_the_reading(self) -> None:
        for check, why, cites in (
            ("agrees", "not-found", []),
            ("agrees", "nothing-checkable", []),
            ("disputed", "written-before", ["write-1"]),
            ("unconfirmed", "ci-passed", ["ci-1"]),
            ("agrees", "check-failed", ["check-1"]),
        ):
            with self.subTest(check=check, why=why):
                back = annotation_store._assessment(self._pair(check, why, cites), 240)
                assert back is not None
                self.assertNotIn("goal_verdict", back)

    def test_a_pair_the_producer_always_cites_is_refused_without_cites(self) -> None:
        for why in ("ci-passed", "passed-before", "written-before", "written-after"):
            with self.subTest(why=why):
                check, _ = reading.GOAL_VERDICT_PAIRS[why]
                back = annotation_store._assessment(self._pair(check, why, []), 240)
                assert back is not None
                self.assertNotIn("goal_verdict", back)

    def test_a_pair_the_producer_never_cites_is_refused_with_cites(self) -> None:
        for why in ("not-found", "nothing-checkable", "deleted-after"):
            with self.subTest(why=why):
                check, _ = reading.GOAL_VERDICT_PAIRS[why]
                back = annotation_store._assessment(self._pair(check, why, ["write-1"]), 240)
                assert back is not None
                self.assertNotIn("goal_verdict", back)

    def test_the_key_is_one_the_assessment_declares(self) -> None:
        self.assertIn("goal_verdict", reading.ASSESSMENT_KEYS)


if __name__ == "__main__":
    unittest.main()
