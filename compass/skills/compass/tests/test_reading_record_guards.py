"""What a reading settles from the record before it believes the model.

Two guards, both over what Compass recorded rather than what the model said. A recorded
file write inside a folder an outcome line rules out, or outside the only folders it allows,
is a departure whatever the reply said. A recorded passing check that covers a line is cited
ahead of the agent's own message on it, so the page can say which check it rests on.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, cast

from compass_runtime import correction, levels, reading

from . import test_reading as base

WRITE_AT = 100.0


def write_fact(path: str, *, fact_id: str = "write-1", at: float = WRITE_AT) -> dict[str, Any]:
    """One `path_written` report, as `project_context` publishes it."""
    return base.check_fact(
        fact_id=fact_id,
        subject="write",
        result="",
        result_source="",
        summary=path,
        at=at,
        evidence={"source": "Claude Write call", "confidence": "exact"},
        branch={"harness": "claude", "sid": "s1", "record_id": f"call-{fact_id}"},
    )


class ARecordedWriteSettlesALineThatNamesAFolder(base.AClaudeCodeReadingProducer):
    """A write the record holds is not a judgment, so no reply can take it back."""

    def _lines(
        self,
        facts: list[dict[str, Any]],
        line: str,
        answer: dict[str, Any] | None = None,
        **produce: Any,
    ) -> dict[str, Any]:
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [{"n": 1, "at": 50.0, "goal": "move the proof into Storybook", "lines": [line]}],
            facts,
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(answer or {})),
            read_lines=True,
            read_agent_words=True,
            **produce,
        )
        self.assertEqual("", why)
        self.assertIsNotNone(assessment)
        return cast("dict[str, Any]", cast("Any", assessment)["criteria"]["line_1"])

    def test_a_write_under_a_folder_the_line_rules_out_makes_the_line_depart(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("frontend/e2e/support/state.ts")],
            "No file under frontend/e2e is edited; the proof lives in Storybook.",
        )
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(reading.WHY_RECORDED_WRITE, row["why"])
        self.assertEqual(("write-1",), row["cites"])
        self.assertIn("frontend/e2e", row["detail"])

    def test_it_departs_with_no_model_verdict_to_lean_on(self) -> None:
        for answer in (
            None,
            {"line_1": {"result": "consistent", "cites": [1], "detail": ""}},
            {"line_1": {"result": "unverifiable", "cites": [], "detail": ""}},
        ):
            with self.subTest(answer=answer):
                row = self._lines(
                    [base.WORDS_FACT, base.AGENT_MESSAGE_FACT, write_fact("frontend/e2e/a.ts")],
                    "No file under frontend/e2e is edited",
                    answer,
                )
                self.assertEqual(reading.RESULT_DEPARTURE, row["result"])

    def test_every_write_under_the_folder_is_cited_up_to_a_few(self) -> None:
        writes = [
            write_fact(f"frontend/e2e/f{n}.ts", fact_id=f"w{n}", at=WRITE_AT + n) for n in range(8)
        ]
        row = self._lines([base.WORDS_FACT, *writes], "Nothing under frontend/e2e is changed", None)
        self.assertEqual(("w0", "w1", "w2"), row["cites"])
        self.assertIn("8 files", row["detail"])

    def test_a_write_elsewhere_does_not_settle_a_line_about_another_folder(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("frontend/src/drift/result.ts")],
            "No file under frontend/e2e is edited",
        )
        self.assertNotEqual(reading.RESULT_DEPARTURE, row.get("result"))
        self.assertNotEqual(reading.WHY_RECORDED_WRITE, row["why"])

    def test_a_folder_is_a_whole_path_and_not_a_prefix_of_a_name(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("frontend/e2e-notes/a.md")],
            "No file under frontend/e2e is edited",
        )
        self.assertNotEqual(reading.RESULT_DEPARTURE, row.get("result"))

    def test_a_write_from_before_the_words_were_saved_settles_nothing(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("frontend/e2e/a.ts", at=40.0)],
            "No file under frontend/e2e is edited",
        )
        self.assertNotEqual(reading.RESULT_DEPARTURE, row.get("result"))

    def test_a_write_outside_the_only_folder_a_line_allows_makes_it_depart(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("docs/notes.md"), write_fact("src/a.py", fact_id="w2")],
            "Only files under src change",
        )
        self.assertNotEqual(reading.RESULT_DEPARTURE, row.get("result"))
        row = self._lines(
            [base.WORDS_FACT, write_fact("docs/notes.md"), write_fact("src/a.py", fact_id="w2")],
            "Only files under src/ and docs/ change; nothing else is touched",
        )
        self.assertNotEqual(reading.RESULT_DEPARTURE, row.get("result"))
        row = self._lines(
            [base.WORDS_FACT, write_fact("docs/notes.md"), write_fact("src/a.py", fact_id="w2")],
            "Only files under src/ change",
        )
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(("write-1",), row["cites"])
        self.assertIn("outside src", row["detail"])

    def test_a_line_that_names_no_folder_is_left_to_the_reading(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("frontend/e2e/a.ts")],
            "No file is edited that the issue does not name",
        )
        self.assertNotEqual(reading.WHY_RECORDED_WRITE, row["why"])

    def test_a_line_that_does_not_forbid_the_folder_does_not_depart(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("frontend/e2e/a.ts")],
            "The proof under frontend/e2e is updated",
        )
        self.assertNotEqual(reading.WHY_RECORDED_WRITE, row["why"])

    def test_a_negator_that_governs_something_else_forbids_no_folder(self) -> None:
        for line in (
            "src/parser.py is updated and no tests fail",
            "Creates docs/guide.md with no broken links",
            "Fix the bug in src/app.py without changing the public API",
            "Fix the bug in src/app.py, no other file is changed",
            "Modify frontend/src, never frontend/e2e",
        ):
            with self.subTest(line=line):
                self.assertEqual((), reading.folder_rules(line))

    def test_only_the_folder_a_negator_governs_is_ruled_out(self) -> None:
        for line, folders in (
            ("Add tests under tests/ and don't touch src/", ("src",)),
            ("Update docs/ and do not change anything in src/", ("src",)),
            ("No file under src/ is edited", ("src",)),
            ("Nothing under frontend/e2e is changed", ("frontend/e2e",)),
            ("src/ is left untouched", ("src",)),
        ):
            with self.subTest(line=line):
                self.assertEqual(((reading.RULE_FORBID, folders),), reading.folder_rules(line))

    def test_a_write_the_line_asked_for_is_not_a_departure(self) -> None:
        row = self._lines(
            [base.WORDS_FACT, write_fact("src/parser.py")],
            "src/parser.py is updated and no tests fail",
        )
        self.assertNotEqual(reading.WHY_RECORDED_WRITE, row["why"])
        row = self._lines(
            [base.WORDS_FACT, write_fact("tests/test_a.py")],
            "Add tests under tests/ and don't touch src/",
        )
        self.assertNotEqual(reading.WHY_RECORDED_WRITE, row["why"])
        row = self._lines(
            [base.WORDS_FACT, write_fact("src/a.py")],
            "Add tests under tests/ and don't touch src/",
        )
        self.assertEqual(reading.WHY_RECORDED_WRITE, row["why"])

    def test_a_write_from_before_the_line_was_requested_does_not_count(self) -> None:
        recorded = reading.Recorded(
            writes=(reading.RecordedWrite("w1", "frontend/e2e/a.ts", 60.0),)
        )
        text = "No file under frontend/e2e is edited"
        self.assertIsNotNone(
            reading.recorded_departure(
                text, text, recorded, window_start=50.0, requested_at=55.0, detail_cap_chars=240
            )
        )
        self.assertIsNone(
            reading.recorded_departure(
                text, text, recorded, window_start=50.0, requested_at=65.0, detail_cap_chars=240
            )
        )


class ARecordedWriteDepartureStandsWhereverItIsReReadAgain(unittest.TestCase):
    """The resolver and the check predicate are the page's and the level's too."""

    def test_check_supports_lets_a_recorded_write_carry_only_a_recorded_departure(self) -> None:
        write = base.entry(
            id="write-1", type="tool_report", subject="write", at=100.0, source="Claude Write call"
        )
        self.assertFalse(reading.check_supports(write, reading.RESULT_DEPARTURE, 50.0))
        self.assertTrue(
            reading.check_supports(write, reading.RESULT_DEPARTURE, 50.0, recorded_write=True)
        )
        self.assertFalse(
            reading.check_supports(write, reading.RESULT_CONSISTENT, 50.0, recorded_write=True)
        )
        before = {**write, "at": 10.0}
        self.assertFalse(
            reading.check_supports(before, reading.RESULT_DEPARTURE, 50.0, recorded_write=True)
        )

    def test_the_stored_token_is_one_a_reading_may_carry(self) -> None:
        self.assertIn(reading.WHY_RECORDED_WRITE, reading.WHY_TOKENS)

    def _stored(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        write = write_fact("frontend/e2e/a.ts")
        criteria = {
            "goal": {
                "result": reading.RESULT_CONSISTENT,
                "cites": ["m1"],
                "detail": "",
                "clause": "g",
                "why": "",
            },
            "line_1": {
                "result": reading.RESULT_DEPARTURE,
                "cites": ["write-1"],
                "detail": "1 file recorded as written under frontend/e2e, which this line rules out.",
                "clause": "No file under frontend/e2e is edited",
                "why": reading.WHY_RECORDED_WRITE,
            },
        }
        return {"read_at": 200.0, "window_start": 50.0, "criteria": criteria}, [
            base.WORDS_FACT,
            base.AGENT_MESSAGE_FACT,
            write,
        ]

    def test_the_level_reads_a_recorded_write_departure_as_a_departure(self) -> None:
        row, facts = self._stored()
        got = levels.analysis_level(
            row,
            levels.Evidence(
                facts=tuple(facts), scan={"last_user_at": 50.0}, unsettled_directions=0
            ),
            outcome_lines=1,
        )
        self.assertIn(levels.REASON_DEPARTURE, got.reasons)

    def test_the_level_does_not_read_the_same_cite_under_a_model_departure(self) -> None:
        row, facts = self._stored()
        row["criteria"]["line_1"]["why"] = ""
        got = levels.analysis_level(
            row,
            levels.Evidence(
                facts=tuple(facts), scan={"last_user_at": 50.0}, unsettled_directions=0
            ),
            outcome_lines=1,
        )
        self.assertNotIn(levels.REASON_DEPARTURE, got.reasons)

    def test_the_correction_carries_the_departure_the_record_settled(self) -> None:
        row, facts = self._stored()
        rows = correction._Rows(row, facts, "claude", unsettled=False, lines_judged=True, sid="s1")
        state, cited = rows.state("line_1")
        self.assertEqual("departed", state)
        self.assertEqual("write-1", (cited or {}).get("fact_id"))
        row["criteria"]["line_1"]["why"] = ""
        rows = correction._Rows(row, facts, "claude", unsettled=False, lines_judged=True, sid="s1")
        self.assertNotEqual("departed", rows.state("line_1")[0])


class ARecordedPassingCheckIsCitedAheadOfTheAgentsMessage(base.AClaudeCodeReadingProducer):
    """A line the agent says is done and a check covers is shown by the check."""

    def _line(
        self,
        facts: list[dict[str, Any]],
        line: str,
        cites: list[int],
        **produce: Any,
    ) -> dict[str, Any]:
        answer = {"line_1": {"result": "consistent", "cites": cites, "detail": ""}}
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [{"n": 1, "at": 50.0, "goal": "make retry robust", "lines": [line]}],
            facts,
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(answer)),
            read_lines=True,
            read_agent_words=True,
            **produce,
        )
        self.assertEqual("", why)
        self.assertIsNotNone(assessment)
        return cast("dict[str, Any]", cast("Any", assessment)["criteria"]["line_1"])

    def _passed(self, **overrides: Any) -> dict[str, Any]:
        return base.check_fact(result="passed", **overrides)

    def test_the_covering_check_leads_and_the_message_stays(self) -> None:
        for grant in (None, base.ADMITTED):
            with self.subTest(granted=grant is not None):
                facts = [base.WORDS_FACT, self._passed(), base.AGENT_MESSAGE_FACT]
                # Without a grant the check is not numbered, so the model can only cite the
                # message; with one it is row 2 and the model leaned on the message alone.
                row = self._line(
                    facts,
                    "The retry tests pass",
                    [2] if grant is None else [3],
                    tool_output=grant,
                )
                self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
                self.assertEqual(("check-1", "m1"), row["cites"])

    def test_a_check_the_reading_already_cites_is_not_cited_twice(self) -> None:
        facts = [base.WORDS_FACT, self._passed(), base.AGENT_MESSAGE_FACT]
        row = self._line(facts, "The retry tests pass", [2, 3], tool_output=base.ADMITTED)
        self.assertEqual(("check-1", "m1"), row["cites"])

    def test_a_check_of_another_kind_is_not_cited(self) -> None:
        lint = self._passed(summary="ruff check .")
        row = self._line(
            [base.WORDS_FACT, lint, base.AGENT_MESSAGE_FACT], "The retry tests pass", [2]
        )
        self.assertEqual(("m1",), row["cites"])

    def test_a_line_that_only_shares_a_keyword_with_a_passing_check_is_not_covered(self) -> None:
        # Each line says the word of a check kind it did not claim a result for: a rule about the
        # config, a directory, a count of tests. None of them is shown by the run passing.
        cases = (
            ("ruff check .", "The lint config is left as it is"),
            ("pytest -q", "Tests are not deleted"),
            ("pytest -q", "The retry test file is renamed"),
            ("ruff check .", "No lint rules are disabled"),
            ("pnpm build", "The build directory is not touched"),
            ("pnpm typecheck", "Type checks are described in the README"),
        )
        for command, line in cases:
            with self.subTest(line):
                row = self._line(
                    [
                        base.WORDS_FACT,
                        self._passed(summary=command),
                        base.AGENT_MESSAGE_FACT,
                    ],
                    line,
                    [2],
                )
                self.assertEqual(("m1",), row["cites"])

    def test_a_line_that_claims_the_checks_result_is_covered_by_a_pass_of_its_kind(self) -> None:
        cases = (
            ("pytest -q", "All the tests pass"),
            ("pytest -q", "The suite is green"),
            ("ruff check .", "Lint is clean"),
            ("ruff check .", "No lint errors remain"),
            ("pnpm build", "The build succeeds"),
            ("pnpm typecheck", "Type checks pass"),
            ("mypy", "mypy finds no errors"),
        )
        for command, line in cases:
            with self.subTest(line):
                row = self._line(
                    [
                        base.WORDS_FACT,
                        self._passed(summary=command),
                        base.AGENT_MESSAGE_FACT,
                    ],
                    line,
                    [2],
                )
                self.assertEqual(("check-1", "m1"), row["cites"])

    def test_a_check_that_names_the_lines_own_target_covers_it(self) -> None:
        lint = self._passed(summary="ruff check compass/skills/compass/compass_runtime/reading.py")
        row = self._line(
            [base.WORDS_FACT, lint, base.AGENT_MESSAGE_FACT],
            "compass_runtime/reading.py is clean",
            [2],
        )
        self.assertEqual(("check-1", "m1"), row["cites"])

    def test_a_pass_that_cannot_carry_a_consistent_is_not_cited(self) -> None:
        for name, check in (
            ("stale", self._passed(before_last_change=True)),
            ("changed after", self._passed(changed_after=True)),
            ("failed", base.check_fact(result="failed")),
            ("not recorded", base.check_fact(result="not-recorded", result_source="")),
        ):
            with self.subTest(name):
                row = self._line(
                    [base.WORDS_FACT, check, base.AGENT_MESSAGE_FACT],
                    "The retry tests pass",
                    [2],
                )
                self.assertNotIn("check-1", row.get("cites", ()))

    def test_an_unsettled_line_gains_no_check(self) -> None:
        answer = {"line_1": {"result": "unverifiable", "cites": [], "detail": ""}}
        assessment, _why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [{"n": 1, "at": 50.0, "goal": "make retry robust", "lines": ["The retry tests pass"]}],
            [base.WORDS_FACT, self._passed(), base.AGENT_MESSAGE_FACT],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(answer)),
            read_lines=True,
            read_agent_words=True,
        )
        self.assertEqual((), cast("Any", assessment)["criteria"]["line_1"]["cites"])


if __name__ == "__main__":
    unittest.main()
