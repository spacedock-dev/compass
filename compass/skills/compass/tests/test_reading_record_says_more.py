"""Three corrections to the 2026-10-30 guards, from the owner's rulings of 2026-11-01.

- A line about the agent's own report to the reader ("Tell me which files changed") is judged on
  the agent's message even beside a write, under two gates
  ([the amendment](docs/design-reading-a-session.md#amended-2026-11-01-owner-a-line-about-what-the-agent-tells-you-rests-on-its-message)).
- "Not shown" is withdrawn by a run with no recorded result that came before a pass of the same
  command only when that pass came after the claim (`earlier_unrecorded_ats`), and the publisher's
  one-fact-per-command collapse is pinned through the real publisher.
- A recorded pass covers an outcome line only when the check noun it claims is unqualified, so an
  unrelated `pytest -q` pass no longer settles "The frontend tests pass".
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from compass_runtime import project_context, reading

from . import test_reading as base
from .test_claude_checks import START, ClaudeChecksTestCase
from .test_codex_checks import CodexChecksTestCase
from .test_harness_records import PiRecord
from .test_reading_record_guards import write_fact
from .test_reading_unfinished_and_cleared import said
from .test_reading_words_give_way import GOAL, check, command

REPORT_LINE = "Tell me which files changed"


def read(
    facts: list[dict[str, Any]],
    answers: dict[str, tuple[str, tuple[str, ...]]],
    *,
    lines: tuple[str, ...] = (REPORT_LINE,),
    max_bytes: int = 16_384,
) -> dict[str, reading.Criterion]:
    ledger = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
    _prompt, selection = reading.build_prompt(ledger, goal=GOAL, lines=lines, max_bytes=max_bytes)
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
        recorded=reading.recorded_from(facts, "claude", "s1"),
    )


class ALineAboutTheAgentsReportIsRecognisedByAStrictGrammar(unittest.TestCase):
    """The class is a strict subset of the 2026-10-01 tells-the-person pattern, so the rule that
    withdraws a pass and the exemption never disagree about it."""

    IN = (
        "Tell me which files changed",
        "Please tell me which files changed and why",
        "Let me know when you're done",
        "Report back with the list of endpoints you touched",
        "Explain to me why the migration was needed",
        "Summarise for me what changed",
        "Tell me what you changed and why it was needed",
        "Please also tell me what changed.",
        "Report back to me with what you found",
        "Describe for me how it works",
        "Tell me what changed and the reasons",
    )
    EMPTY = ("Tell me", "Tell me.", "Report back", "Let me know.")
    NOT_A_REPORT = (
        "Tell me when the deploy is green",
        "Let me know if anything breaks",
        "Tell me what changed and all files are removed",
        "Tell me what you did and the deploy succeeded",
        "Report back to me after pushing to main",
        "Tell me what you will delete",
        "Let me know the migration ran",
    )
    OUT = (
        "Tell the user in the README how to install",
        "Tell me in the PR description which files changed",
        "Report generation must handle empty input",
        "The CLI reports 0 failures",
        "Report the test counts",
        "Its counts are reported",
        "Tell me which files changed and fix the flaky test",
        "Tell me which files changed; then push",
        "Tell me whether the tests pass",
        "Let me know if lint is clean",
        "Tell me which files under src/ changed",
        "Make the error tell me what went wrong",
        "Show me the diff",
        "Give me the list of files",
        "List the files that changed for me",
        "Confirm to me that it works",
        "Explain why the test failed",
    )

    def test_every_ruling_example_is_in_the_class(self) -> None:
        for line in (*self.IN, *self.EMPTY):
            with self.subTest(line=line):
                self.assertTrue(reading.asks_for_a_report(line))

    def test_every_ruling_out_of_class_line_is_out(self) -> None:
        for line in self.OUT:
            with self.subTest(line=line):
                self.assertFalse(reading.asks_for_a_report(line))

    def test_a_request_that_asks_about_the_world_or_orders_an_action_is_not_a_report_request(
        self,
    ) -> None:
        # The subject of these is the deploy, the migration or a later action, not what the
        # agent tells you, so no message of the agent's can show or break them.
        for line in self.NOT_A_REPORT:
            with self.subTest(line=line):
                self.assertFalse(reading.asks_for_a_report(line))

    def test_every_line_in_the_class_is_one_the_tells_the_person_rule_already_reads(self) -> None:
        for line in self.IN:
            with self.subTest(line=line):
                self.assertIsNotNone(reading._TELLS_THE_PERSON.search(line))


class ARequestForTheAgentsReportBesideAWriteRestsOnItsMessage(unittest.TestCase):
    """Probes P11 and P12 of the retry correction review: beside a write, C2 withdrew the
    consistent and C1 the departure, though only the message can show such a line."""

    def facts(self, *, message_at: float = 110.0, words: str = "I changed src/handler.py.") -> Any:
        return [
            base.WORDS_FACT,
            write_fact("src/handler.py", at=95.0),
            said(message_at, words=words),
        ]

    def test_a_consistent_on_a_message_sent_after_the_write_stands(self) -> None:
        row = read(self.facts(), {"line_1": ("consistent", ("m1",))})["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertEqual(("m1",), row["cites"])

    def test_a_consistent_on_a_message_sent_before_the_write_reads_no_work_shown(self) -> None:
        row = read(self.facts(message_at=90.0), {"line_1": ("consistent", ("m1",))})["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_a_consistent_on_a_line_outside_the_class_still_reads_no_work_shown(self) -> None:
        row = read(
            self.facts(),
            {"line_1": ("consistent", ("m1",))},
            lines=("Tell the user in the README how to install",),
        )["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_a_departure_on_the_newest_whole_message_stands(self) -> None:
        row = read(self.facts(words="Done."), {"line_1": ("departure", ("m1",))})["line_1"]
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])
        self.assertEqual(("m1",), row["cites"])

    def test_a_departure_on_a_message_that_is_not_the_newest_reads_no_work_shown(self) -> None:
        facts = [*self.facts(words="Done."), said(120.0, fact_id="m2", words="Wrapping up.")]
        row = read(facts, {"line_1": ("departure", ("m1",))})["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
        row = read(facts, {"line_1": ("departure", ("m1", "m2"))})["line_1"]
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])

    def test_a_departure_on_a_message_carried_as_an_excerpt_reads_no_work_shown(self) -> None:
        cropped = {**said(110.0, words="Done."), "agent_words_total": 5_000}
        facts = [base.WORDS_FACT, write_fact("src/handler.py", at=95.0), cropped]
        row = read(facts, {"line_1": ("departure", ("m1",))})["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_a_departure_when_the_selection_left_a_message_out_reads_no_work_shown(self) -> None:
        # Every message is long enough that the budget cannot carry them all: the reading never
        # saw the whole of what the agent told the reader, so "it did not tell you" cannot rest on it.
        filler = "x" * 400
        facts = [
            base.WORDS_FACT,
            write_fact("src/handler.py", at=95.0),
            *(said(100.0 + n, fact_id=f"m{n}", words=f"Note {n}: {filler}") for n in range(1, 30)),
        ]
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
        _prompt, selection = reading.build_prompt(
            ledger, goal=GOAL, lines=(REPORT_LINE,), max_bytes=4_000
        )
        carried = [e for e in selection.entries if e["type"] == reading.AGENT_MESSAGE_TYPE]
        self.assertLess(len(carried), 29, "the fixture must crowd a message out")
        self.assertFalse(selection.agent_words_whole)
        newest = max(carried, key=lambda e: e["at"])["id"]
        row = read(facts, {"line_1": ("departure", (newest,))}, max_bytes=4_000)["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_every_message_carried_whole_is_what_the_selection_records(self) -> None:
        ledger = reading.build_ledger(
            self.facts(), "claude", "s1", tool_output={}, read_agent_words=True
        )
        _prompt, selection = reading.build_prompt(
            ledger, goal=GOAL, lines=(REPORT_LINE,), max_bytes=16_384
        )
        self.assertTrue(selection.agent_words_whole)

    def test_a_reply_that_is_not_a_raise_stays_unverifiable(self) -> None:
        row = read(self.facts(), {"line_1": ("unverifiable", ())})["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_a_not_a_report_line_beside_a_write_keeps_its_withdrawal(self) -> None:
        for line in ALineAboutTheAgentsReportIsRecognisedByAStrictGrammar.NOT_A_REPORT:
            with self.subTest(line=line, side="consistent"):
                facts = self.facts(words="Working on it.")
                row = read(facts, {"line_1": ("consistent", ("m1",))}, lines=(line,))["line_1"]
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
            with self.subTest(line=line, side="departure"):
                row = read(
                    self.facts(words="Done."), {"line_1": ("departure", ("m1",))}, lines=(line,)
                )["line_1"]
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_a_line_outside_the_class_keeps_the_departure_guard(self) -> None:
        row = read(
            self.facts(words="Done."),
            {"line_1": ("departure", ("m1",))},
            lines=("Tell the user in the README how to install",),
        )["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_the_tells_the_person_rule_still_runs_first(self) -> None:
        # A passing check cited under the line, with no message at or after it, reads as before.
        facts = [base.WORDS_FACT, check("c1", 100.0, "passed"), said(90.0, words="Starting.")]
        row = read(facts, {"line_1": ("consistent", ("c1", "m1"))})["line_1"]
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_TELLS_THE_PERSON, row["why"])


def codex(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        **fact,
        "source_session": {"harness": "codex", "sid": "s1"},
        "branch": {**fact.get("branch", {}), "harness": "codex", "sid": "s1"},
    }


def read_codex(
    facts: list[dict[str, Any]], answers: dict[str, tuple[str, tuple[str, ...]]], line: str
) -> reading.Criterion:
    ledger = reading.build_ledger(facts, "codex", "s1", tool_output={}, read_agent_words=True)
    _prompt, selection = reading.build_prompt(ledger, goal=GOAL, lines=(line,), max_bytes=16_384)
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
        recorded=reading.recorded_from(facts, "codex", "s1"),
    )["line_1"]


class ARecordedPassCoversOnlyTheCheckTheLineNames(unittest.TestCase):
    """Probes P8 and P8b of the retry correction review: a keyword match let an unrelated
    `pytest -q` pass settle "The frontend tests pass" beside a write, undoing the guard that
    withdraws a `consistent` resting on the agent's word. `covering_checks` is tightened and
    `covers_line` is not, because the running-turn guard reads it through `_bears_on`."""

    def beside_a_write(self, line: str) -> reading.Criterion:
        facts = [
            base.WORDS_FACT,
            write_fact("frontend/src/App.tsx", at=95.0),
            check("c1", 100.0, "passed", summary="pytest -q"),
            said(110.0, words="Frontend tests pass."),
        ]
        return read(facts, {"line_1": ("consistent", ("m1",))}, lines=(line,))["line_1"]

    def test_a_pass_of_another_kind_of_tests_does_not_settle_a_qualified_line(self) -> None:
        for line in (
            "The frontend tests pass",
            "The Rust tests pass",
            "The e2e tests pass",
            "The new tests pass",
            "Python tests pass",
            "The unit tests pass",
            "Make sure the frontend tests pass",
            "The retry tests pass",
        ):
            with self.subTest(line=line):
                row = self.beside_a_write(line)
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
                self.assertEqual(("m1",), row["cites"])

    def test_a_postmodified_noun_is_not_covered(self) -> None:
        for line in (
            "Tests for the parser pass",
            "The tests in the frontend pass",
            "tests pass for the frontend",
            "The tests pass in the Rust crate",
        ):
            with self.subTest(line=line):
                row = self.beside_a_write(line)
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
                self.assertEqual(("m1",), row["cites"])

    def test_a_second_clause_naming_a_qualified_check_is_not_covered(self) -> None:
        for line in (
            "The tests pass and the frontend tests pass",
            "Both the frontend and backend tests pass",
        ):
            with self.subTest(line=line):
                row = self.beside_a_write(line)
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(("m1",), row["cites"])

    def test_a_line_naming_another_kind_of_check_is_not_covered(self) -> None:
        # Only a pytest pass is recorded, and the line also claims lint.
        row = self.beside_a_write("Lint and tests pass")
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
        self.assertEqual(("m1",), row["cites"])

    def test_codex_reads_the_same_way(self) -> None:
        facts = [
            {**base.WORDS_FACT, "source_session": {"harness": "codex", "sid": "s1"}},
            codex(write_fact("src/lib.rs", at=95.0)),
            codex(check("c1", 100.0, "passed", summary="pytest -q")),
            codex(command("k1", 101.0, "passed", "cargo test")),
        ]
        row = read_codex(facts, {"line_1": ("consistent", ("k1",))}, "Rust tests pass")
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
        self.assertEqual(("k1",), row["cites"])

    # Controls: an unqualified noun, or one qualified only by an article or a quantifier, is
    # still covered, and the running-turn guard's reading of a line is unchanged.

    def test_an_unqualified_line_is_still_covered(self) -> None:
        for line in (
            "The tests pass",
            "All tests pass",
            "All the tests pass",
            "Every test passes",
            "Our tests pass",
            "No test failures",
            "pytest passes",
            "Make sure the tests pass",
        ):
            with self.subTest(line=line):
                row = self.beside_a_write(line)
                self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
                self.assertIn("c1", row["cites"])

    def test_a_line_that_names_a_path_is_covered_as_before(self) -> None:
        facts = [
            base.WORDS_FACT,
            write_fact("src/handler.py", at=95.0),
            check("c1", 100.0, "passed", summary="pytest tests/test_handler.py"),
            said(110.0),
        ]
        row = read(
            facts,
            {"line_1": ("consistent", ("m1",))},
            lines=("tests/test_handler.py passes",),
        )["line_1"]
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertIn("c1", row["cites"])

    def test_the_running_turn_guard_still_reads_a_qualified_line_as_borne_on(self) -> None:
        ledger = reading.build_ledger(
            [base.WORDS_FACT, check("c1", 100.0, "passed", summary="pytest -q")],
            "claude",
            "s1",
            tool_output={},
            read_agent_words=True,
        )
        entry = next(row for row in ledger if row["id"] == "c1")
        self.assertTrue(reading._bears_on("Rust tests pass", entry))
        self.assertTrue(reading.covers_line("Rust tests pass", "pytest -q"))


class ARunWithNoResultIsSettledByAReRunOfTheSameCommand(ClaudeChecksTestCase):
    """The publisher keeps one fact per command identity, the directory plus the stripped words,
    and it is the run with the newest evidence. So a run with no result followed by a passing run
    of the same command reaches the reader as one passing fact, and "not shown" is not withdrawn
    for it; a re-run in another directory or none is another identity and still withdraws. The
    shape the issue first filed, two facts sharing a text, is not one the publisher produces.
    A run with no result before the claim and a pass after it is `earlier_unrecorded_ats`'s case."""

    def at(self, seconds: float) -> float:
        return START.timestamp() + seconds

    def claims(self, steps: list[tuple[str, str]], claim_at: float) -> reading.Criterion:
        """The claims row after a claim at `claim_at`, over what the publisher made of `steps`:
        ("run", command) is a call whose result never arrived, ("pass", command) a passing one."""
        for kind, text in steps:
            if kind == "run":
                self.session.call("Bash", {"command": text})
            else:
                self.session.bash(text, "5 passed")
        events, _scan = self.read()
        self.published = [
            event for event in events if event["kind"] in ("check_run", "command_run")
        ]
        facts = [
            {
                **project_context._semantic_fact_from_event(
                    event, str(event["kind"]), "tool_report", ""
                ),
                "source_session": {"harness": "claude", "sid": "s1"},
                "branch": {"harness": "claude", "sid": "s1", "record_id": event["record_id"]},
            }
            for event in self.published
        ]
        return read(
            [base.WORDS_FACT, *facts, said(claim_at, words="Deployed to production.")],
            {"claims": ("unsupported", ("m1",))},
        )["claims"]

    def test_a_pass_of_the_same_command_before_the_claim_settles_the_earlier_run(self) -> None:
        row = self.claims([("run", "pytest"), ("pass", "pytest")], self.at(60))
        self.assertEqual(1, len(self.published))
        self.assertEqual("passed", self.published[0]["result"])
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])

    def test_a_lost_run_before_the_claim_is_not_hidden_by_a_later_lost_run_and_a_pass(self) -> None:
        # Lost at 10, the claim at 12, lost again at 15, passed at 20: the newest lost run alone
        # is after the claim, but the first one was part of the record the claim was made against.
        row = self.claims([("run", "pytest"), ("run", "pytest"), ("pass", "pytest")], self.at(12))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    def test_a_lost_run_after_the_claim_alone_does_not_withdraw(self) -> None:
        row = self.claims([("run", "pytest"), ("pass", "pytest")], self.at(7))
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])

    def test_a_pass_after_the_claim_does_not_settle_a_run_that_came_before_it(self) -> None:
        row = self.claims([("run", "pytest"), ("pass", "pytest")], self.at(12))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    # Controls: with no re-run, or a re-run that is another command by the publisher's identity.

    def test_a_run_with_no_re_run_withdraws(self) -> None:
        row = self.claims([("run", "pytest")], self.at(60))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    def test_a_pass_in_another_directory_does_not_settle_it(self) -> None:
        row = self.claims([("run", "pytest"), ("pass", "cd sub && pytest")], self.at(60))
        self.assertEqual(2, len(self.published))
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    def test_a_pass_in_an_unplaced_directory_does_not_settle_it(self) -> None:
        row = self.claims([("run", "pytest"), ("pass", 'cd "$(mktemp -d)" && pytest')], self.at(60))
        self.assertEqual(2, len(self.published))
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    def test_a_pass_before_the_claim_with_nothing_earlier_stands(self) -> None:
        row = self.claims([("pass", "pytest")], self.at(60))
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])


class AClaudeCodePassKeepsWhenAnEarlierRunHadNoResult(ClaudeChecksTestCase):
    def test_the_pass_carries_the_time_of_the_run_that_had_none(self) -> None:
        self.session.call("Bash", {"command": "pytest"})
        self.session.bash("pytest", "5 passed")
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        self.assertEqual([START.timestamp() + 10], check["earlier_unrecorded_ats"])

    def test_the_publisher_keeps_every_lost_run_time(self) -> None:
        for _ in range(3):
            self.session.call("Bash", {"command": "pytest"})
        self.session.bash("pytest", "5 passed")
        lost = self.only_check()["earlier_unrecorded_ats"]
        self.assertEqual(
            [START.timestamp() + 10, START.timestamp() + 15, START.timestamp() + 20], lost
        )

    def test_the_newest_sixteen_lost_run_times_are_kept_oldest_first(self) -> None:
        for _ in range(20):
            self.session.call("Bash", {"command": "pytest"})
        self.session.bash("pytest", "5 passed")
        lost = self.only_check()["earlier_unrecorded_ats"]
        self.assertEqual(16, len(lost))
        self.assertEqual(sorted(lost), lost)
        self.assertEqual(START.timestamp() + 10 + 5 * 4, lost[0])

    def test_a_pass_with_no_lost_run_before_it_carries_none(self) -> None:
        self.session.bash("pytest", "5 passed")
        self.assertNotIn("earlier_unrecorded_ats", self.only_check())

    def test_a_latest_run_with_no_result_carries_none(self) -> None:
        self.session.bash("pytest", "5 passed")
        self.session.call("Bash", {"command": "pytest"})
        check = self.only_check()
        self.assertEqual("not-recorded", check["result"])
        self.assertNotIn("earlier_unrecorded_ats", check)


class ACodexPassKeepsWhenAnEarlierRunHadNoResult(CodexChecksTestCase):
    def test_the_pass_carries_the_time_of_the_run_that_had_none(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=-9)
        self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=0)
        check = self.only_check()
        self.assertEqual("passed", check["result"])
        (lost,) = check["earlier_unrecorded_ats"]
        self.assertLess(lost, check["at"])

    def test_the_publisher_keeps_every_lost_run_time(self) -> None:
        for _ in range(2):
            self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=-9)
        self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=0)
        check = self.only_check()
        self.assertEqual(2, len(check["earlier_unrecorded_ats"]))
        self.assertEqual(sorted(check["earlier_unrecorded_ats"]), check["earlier_unrecorded_ats"])

    def test_a_pass_with_no_lost_run_before_it_carries_none(self) -> None:
        self.rollout.command("pytest -q", "3 passed in 0.1s", exit_code=0)
        self.assertNotIn("earlier_unrecorded_ats", self.only_check())


class APiPassKeepsWhenAnEarlierRunHadNoResult(PiRecord):
    def test_the_pass_carries_the_time_of_the_run_that_had_none(self) -> None:
        self.bash("pytest -q &", is_error=False, text="5 passed in 0.1s")
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        got = self.one()
        self.assertEqual("passed", got["result"])
        self.assertEqual(1, len(got["earlier_unrecorded_ats"]))

    def test_the_publisher_keeps_every_lost_run_time(self) -> None:
        self.bash("pytest -q &", is_error=False, text="5 passed in 0.1s")
        self.bash("pytest -q &", is_error=False, text="5 passed in 0.1s")
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        got = self.one()
        self.assertEqual(2, len(got["earlier_unrecorded_ats"]))
        self.assertEqual(sorted(got["earlier_unrecorded_ats"]), got["earlier_unrecorded_ats"])

    def test_a_pass_with_no_lost_run_before_it_carries_none(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.assertNotIn("earlier_unrecorded_ats", self.one())


if __name__ == "__main__":
    unittest.main()
