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
        self.assertNotIn("run count or piping", prompt)

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
