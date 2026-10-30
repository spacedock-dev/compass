"""A line about how a check ran is judged from what the record says about that run.

The owner's ruling of 2026-10-30, "Judge from recorded facts": a line such as "node --test
tests/game.test.js is run once, unpiped, and its counts are reported" is read against the record's
facts about the run (how many times it ran inside the window, whether its call piped its output,
and the output the tier allows), and a recorded fact that contradicts the line is a departure
([DEC-29](docs/design-reading-a-session.md#amended-2026-10-30-owner-a-line-about-how-a-check-ran-is-judged-from-the-records-facts-about-that-run)).

No keyword rule reads the line. The collector publishes each run's time and whether its call
piped, the ledger row says what those facts are inside the window, and the trusted header tells the
model the facts settle such a line. Every transcript is built from the recorded field shapes; no
text came from a real session.
"""

from __future__ import annotations

import json
from typing import Any

from compass_runtime import project_context, reading

from . import test_claude_checks
from . import test_reading as base

COUNTS = "# tests 30\n# pass 30\n# fail 0"


class TheRecordSaysHowEachRunOfACheckRan(test_claude_checks.ClaudeChecksTestCase):
    def test_a_piped_run_and_a_later_unpiped_run_are_both_on_the_check(self) -> None:
        self.session.bash("node --test tests/game.test.js | tail -3", COUNTS)
        self.session.bash("node --test tests/game.test.js", COUNTS)
        check = self.only_check()
        self.assertEqual([True, False], [run["piped"] for run in check["runs"]])
        self.assertEqual(2, len({run["at"] for run in check["runs"]}))

    def test_one_unpiped_run_is_one_run_not_piped(self) -> None:
        self.session.bash("node --test tests/game.test.js", COUNTS)
        check = self.only_check()
        self.assertEqual([False], [run["piped"] for run in check["runs"]])

    def test_a_pipe_later_in_the_call_is_not_the_checks_own(self) -> None:
        # Review, 2026-10-30: the row says "piped" of the check, so only the check's own
        # pipeline counts, not a pipe in a later command of the same call.
        self.session.bash("node --test tests/game.test.js && git log --oneline | head -3", COUNTS)
        check = self.only_check()
        self.assertEqual([False], [run["piped"] for run in check["runs"]])

    def test_a_check_another_pipes_into_is_piped(self) -> None:
        self.session.bash("printf '' | node --test tests/game.test.js", COUNTS)
        check = self.only_check()
        self.assertEqual([True], [run["piped"] for run in check["runs"]])

    def test_a_narrower_failure_a_later_pass_covers_is_not_a_run_of_the_pass(self) -> None:
        # Review, 2026-10-30: the covered failure joins the pass's history for its result, and
        # the pass ran once, so its row must not say it ran twice.
        self.session.bash(
            "python3 -m unittest tests.test_a.T.test_x",
            "Ran 1 test in 0.01s\n\nFAILED (failures=1)",
            is_error=True,
        )
        self.session.bash("python3 -m unittest tests.test_a", "Ran 4 tests in 0.01s\n\nOK")
        passed = [check for check in self.checks() if check["result"] == "passed"]
        self.assertEqual(1, len(passed), self.checks())
        self.assertEqual(1, len(passed[0]["runs"]))

    def test_the_runs_reach_the_published_fact(self) -> None:
        self.session.bash("node --test tests/game.test.js", COUNTS)
        event = self.only_check()
        fact = project_context._semantic_fact_from_event(event, event["kind"], "tool_report", "")
        self.assertEqual(event["runs"], fact["runs"])


def check_with_runs(*runs: tuple[float, bool]) -> dict[str, Any]:
    """The a3c76f89 line_3 shape: one check of the line's own command, passing, with its runs."""
    return base.check_fact(
        fact_id="c-node",
        result="passed",
        summary="node --test tests/game.test.js",
        at=runs[-1][0],
        runs=[{"at": at, "piped": piped} for at, piped in runs],
    )


LINE = "node --test tests/game.test.js is run once, unpiped, and its counts are reported"


class AReadingIsGivenTheRunFactsAndAskedToJudgeThem(base.AClaudeCodeReadingProducer):
    def _prompt(self, check: dict[str, Any]) -> str:
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "idle", "turn_end_at": 150.0},
            [{"n": 1, "at": 50.0, "goal": "add a board-full check", "lines": [LINE]}],
            [base.WORDS_FACT, check, base.AGENT_MESSAGE_FACT],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps({})),
            tool_output=base.ADMITTED,
            read_lines=True,
            read_agent_words=True,
            admit_turn_stop=True,
        )
        self.assertEqual("", why)
        self.assertIsNotNone(assessment)
        return self.prompts[-1]

    def _row(self, prompt: str) -> str:
        return next(line for line in prompt.splitlines() if "] tool_report" in line)

    def test_a_piped_run_is_named_piped_on_the_checks_row(self) -> None:
        row = self._row(self._prompt(check_with_runs((100.0, True))))
        self.assertIn(reading.ran_words(1, 1), row)

    def test_one_unpiped_run_is_named_once_and_not_piped(self) -> None:
        row = self._row(self._prompt(check_with_runs((100.0, False))))
        self.assertIn(reading.ran_words(1, 0), row)

    def test_a_run_before_the_words_is_not_counted(self) -> None:
        row = self._row(self._prompt(check_with_runs((40.0, False), (100.0, False))))
        self.assertIn(reading.ran_words(1, 0), row)

    def test_two_runs_in_the_window_are_counted(self) -> None:
        row = self._row(self._prompt(check_with_runs((95.0, True), (100.0, False))))
        self.assertIn(reading.ran_words(2, 1), row)

    def test_the_header_asks_the_model_to_judge_a_run_from_those_facts(self) -> None:
        prompt = self._prompt(check_with_runs((100.0, True)))
        self.assertIn(reading.RUN_FACTS_RULE, prompt)

    def test_counts_still_prove_no_run_count_where_a_row_states_no_runs(self) -> None:
        # Review, 2026-10-30: a check recorded before this build, or another harness's, carries no
        # runs, and nothing else stops its counts being read as one unpiped run.
        prompt = self._prompt(base.check_fact(result="passed", at=100.0))
        self.assertRegex(
            prompt, r"Counts prove no untested toggle, scorekeeping.*run count or piping"
        )

    def test_the_run_words_never_take_the_commands_room(self) -> None:
        # Review, 2026-10-30: a failed check with every flag clipped its command to nothing once
        # the run words joined the capped suffix, and fell out of the citable menu.
        fact = base.check_fact(
            result="failed",
            result_source="marker",
            summary="python3 -m pytest tests/test_board.py::test_a_full_board_is_a_draw -q",
            earlier_failed=True,
            before_last_change=True,
            listed_by_reader=True,
            read_incomplete=True,
            at=100.0,
        )
        cap = reading.LEDGER_SUMMARY_CAP_CHARS
        without = reading._tool_report_summary(fact, cap, window_start=50.0)
        with_runs = reading._tool_report_summary(
            {**fact, "runs": [{"at": 60.0 + n, "piped": False} for n in range(3)]},
            cap,
            window_start=50.0,
        )
        self.assertIn(reading.ran_words(3, 0), with_runs)
        self.assertTrue(reading._check_text({"summary": without}).strip())  # type: ignore[typeddict-item]
        self.assertEqual(
            reading._check_text({"summary": without}),  # type: ignore[typeddict-item]
            reading._check_text({"summary": with_runs}),  # type: ignore[typeddict-item]
        )
        ledger = reading.build_ledger(
            [{**fact, "runs": [{"at": 60.0 + n, "piped": False} for n in range(3)]}],
            "claude",
            "s1",
            tool_output={},
            window_start=50.0,
        )
        self.assertEqual(["check-1"], [row["id"] for row in ledger if reading._citable(row)])

    def test_a_check_with_no_run_facts_says_nothing_of_its_runs(self) -> None:
        # An older fact, or another harness's check, carries no runs: nothing is said rather than
        # a guess, and the line is left to what the record does hold.
        row = self._row(
            self._prompt(
                base.check_fact(result="passed", at=100.0, summary="node --test tests/game.test.js")
            )
        )
        self.assertNotIn("in the window read", row)

    def test_the_words_read_as_the_facts(self) -> None:
        self.assertEqual("ran once in the window read, not piped", reading.ran_words(1, 0))
        self.assertEqual("ran once in the window read, piped", reading.ran_words(1, 1))
        self.assertEqual("ran 3 times in the window read, 2 piped", reading.ran_words(3, 2))
        self.assertEqual(
            "ran at least 3 times in the window read, none piped",
            reading.ran_words(3, 0, floor=True),
        )

    def test_the_reading_knows_how_many_runs_the_collector_lists(self) -> None:
        # Spelled twice so the reading does not import the collector; a full list is a floor.
        self.assertEqual(project_context.MAX_PUBLISHED_RUNS, reading.RUNS_LISTED_CAP)
        runs = tuple((60.0 + n, False) for n in range(reading.RUNS_LISTED_CAP))
        row = self._row(self._prompt(check_with_runs(*runs)))
        self.assertIn(reading.ran_words(reading.RUNS_LISTED_CAP, 0, floor=True), row)
