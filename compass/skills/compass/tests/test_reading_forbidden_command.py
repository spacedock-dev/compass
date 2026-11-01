"""A "don't push" line departs when the record holds the push succeeding.

The owner ruled on 2026-11-01 (a closed push table, cited by the model and confirmed by the code):
[the amendment](docs/design-reading-a-session.md#amended-2026-11-01-owner-a-forbidden-push-that-ran-carries-its-departure).
Item 8 drops a passing command from a departure's citations, so a line the reader wrote as
"Do not push to main" read Can't tell beside a `git push origin main` that exited 0. The rule
raises nothing: it applies to an outcome line, only to the model's own `departure`, and only when
one of its raw citations is a push that matches the line.

Every fixture is a recorded field shape (`test_reading.check_fact`); no text came from a real
session. The measured shape (a push cited under a departure, then dropped) is control 1.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from compass_runtime import correction, levels, reading

from . import test_reading as base
from .test_reading_unfinished_and_cleared import said
from .test_reading_words_give_way import GOAL, command

PUSH_LINE = "Do not push to main"
PUSH = "git push origin main"


def read(
    facts: list[dict[str, Any]],
    answers: dict[str, tuple[str, tuple[str, ...]]],
    *,
    lines: tuple[str, ...] = (PUSH_LINE,),
    goal: str = GOAL,
    line_requests: dict[str, float] | None = None,
) -> dict[str, reading.Criterion]:
    ledger = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
    _prompt, selection = reading.build_prompt(ledger, goal=goal, lines=lines, max_bytes=16_384)
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
        goal=goal,
        lines=selection.lines,
        detail_cap_chars=200,
        window_start=50.0,
        line_requests=line_requests,
        recorded=reading.recorded_from(facts, "claude", "s1"),
    )


def pushed(
    text: str = PUSH, *, result: str = "passed", at: float = 110.0, fact_id: str = "k1"
) -> list[dict[str, Any]]:
    return [base.WORDS_FACT, command(fact_id, at, result, text), said(120.0)]


def departs(
    facts: list[dict[str, Any]], line: str = PUSH_LINE, cites: tuple[str, ...] = ("k1", "m1")
) -> reading.Criterion:
    return read(facts, {"line_1": ("departure", cites)}, lines=(line,))["line_1"]


class ALineThatForbidsAPushIsRecognisedWholeAndNothingElse(unittest.TestCase):
    """The grammar reads a whole sentence, so a condition after the object breaks the match."""

    IN = (
        ("Do not push to main", None, "main"),
        ("Don't push to main.", None, "main"),
        ("Never push directly to the main branch", None, "main"),
        ("Do not push to origin/main", None, "origin/main"),
        ("Don't push", None, None),
        ("Please do not push straight to `main`", None, "main"),
        ("Must not push into the release/1.0 branch!", None, "release/1.0"),
        ("Fix the retry; do not push to main.", None, "main"),
        ("Fix the retry. Never push to main", None, "main"),
        ("Don't push to main. Then open a PR.", None, "main"),
        ("And don't push to main", None, "main"),
        ("Don't force-push to main", True, "main"),
        ("Never force push", True, None),
    )
    OUT = (
        "Don't push to main until CI passes",
        "Don't push to main, unless CI is green",
        "Do not push to main without review",
        "Never push to main before the review",
        "Don't push to main when it is red",
        "Don't push to main if the tests fail",
        "Don't push to main again",
        "Push to main when done",
        "The CI job does not push to main",
        "Don't push the tag",
        "Do not pull from main",
        "Do not push to main and open a PR",
        "Don't push to main. Unless CI passes.",
        "Don't push to main. Exception: hotfixes.",
        "Don't push to main; unless the owner says so",
        "Don't push to main. Ask me first.",
        "Don't push to main. Check with me first.",
        "",
    )

    def test_every_phrasing_the_ruling_names_is_recognised_with_its_ref_and_force(self) -> None:
        for line, force, ref in self.IN:
            with self.subTest(line=line):
                bans = reading.forbidden_pushes(line)
                self.assertEqual(1, len(bans))
                self.assertEqual(
                    (bool(force), ref), (bans[0].force, bans[0].ref), f"{line!r} was misread"
                )

    def test_a_condition_or_a_second_object_after_the_push_breaks_the_match(self) -> None:
        for line in self.OUT:
            with self.subTest(line=line):
                self.assertEqual((), reading.forbidden_pushes(line))

    def test_the_condition_is_seen_because_the_clause_is_not_split_at_a_comma(self) -> None:
        # The folder rules' clause break splits at "," and "and", which would leave
        # "Don't push to main" standing alone in front of the condition.
        self.assertEqual((), reading.forbidden_pushes("Don't push to main, unless CI is green"))
        self.assertEqual((), reading.forbidden_pushes("Don't push to main, and wait for CI"))


class ACommandIsReadAsAPushOnlyWhenItStartsWithGitPush(unittest.TestCase):
    def test_a_push_with_its_remote_destinations_and_force_is_read(self) -> None:
        cases: tuple[tuple[str, str | None, set[str], bool], ...] = (
            ("git push origin main", "origin", {"main"}, False),
            ("git push -u origin main", "origin", {"main"}, False),
            ("rtk git push origin main", "origin", {"main"}, False),
            ("env CI=1 git push origin main", "origin", {"main"}, False),
            ("git push origin HEAD:main", "origin", {"main"}, False),
            ("git push origin HEAD:refs/heads/main", "origin", {"main"}, False),
            ("git push origin main:feature", "origin", {"feature"}, False),
            ("git push --force origin main", "origin", {"main"}, True),
            ("git push -f origin main", "origin", {"main"}, True),
            ("git push --force-with-lease=main origin main", "origin", {"main"}, True),
            ("git push origin +main", "origin", {"main"}, True),
            ("git push origin a b", "origin", {"a", "b"}, False),
            ("git push -o ci.skip origin main", "origin", {"main"}, False),
            ("git push --no-verify --follow-tags origin main", "origin", {"main"}, False),
            ("git push", None, set(), False),
            ("git push origin", "origin", set(), False),
            ("git push origin HEAD", "origin", set(), False),
            ("git push origin HEAD:HEAD", "origin", set(), False),
        )
        for text, remote, dests, force in cases:
            with self.subTest(text=text):
                run = reading.push_run(text)
                assert run is not None
                self.assertEqual(
                    (remote, dests, force), (run.remote, set(run.destinations), run.force)
                )

    def test_a_command_outside_the_shape_is_not_a_push(self) -> None:
        for text in (
            "npm install",
            "git -C repo push origin main",
            "git -c k=v push origin main",
            "git commit -m push",
            "git push --dry-run origin main",
            "git push --dry-run=true origin main",
            "git push -n origin main",
            "git push -d origin main",
            "git push --delete origin main",
            "git push origin :main",
            "git push --all origin",
            "git push --mirror origin",
            "git push --tags origin",
            "git push --prune origin main",
            "git push --some-new-flag origin main",
            "echo git push origin main",
            "",
        ):
            with self.subTest(text=text):
                self.assertIsNone(reading.push_run(text))


class ALineThatForbidsAPushDepartsWhenThePushRan(unittest.TestCase):
    """Control numbers are the owner's list of 15 (the page's two are in the frontend suite)."""

    def test_a_push_that_exited_zero_departs_the_line_and_is_cited_first(self) -> None:
        # Measured shape: item 8 dropped the passing push, leaving Can't tell on the message alone.
        row = departs(pushed())
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertEqual(reading.WHY_RECORDED_COMMAND, row["why"])
        self.assertEqual(("k1", "m1"), row["cites"])
        self.assertEqual(
            "`git push origin main` ran and exited 0 after this line, which rules it out.",
            row["detail"],
        )

    def test_an_unrelated_command_that_exited_zero_stays_cant_tell(self) -> None:
        row = departs(pushed("npm install"))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])

    def test_a_push_to_another_branch_stays_cant_tell(self) -> None:
        for text in ("git push origin feature-branch", "git push origin main:feature"):
            with self.subTest(text=text):
                row = departs(pushed(text))
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_a_push_that_failed_is_not_the_new_token_and_keeps_todays_departure(self) -> None:
        row = departs(pushed(result="failed"))
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])
        self.assertNotEqual(reading.WHY_RECORDED_COMMAND, row["why"])
        self.assertEqual(reading.WHY_STANDS, row["why"])

    def test_a_push_that_ran_with_no_recorded_result_stays_cant_tell(self) -> None:
        row = departs(pushed(result=""))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertNotEqual(reading.WHY_RECORDED_COMMAND, row["why"])

    def test_a_push_the_producer_marked_as_unable_to_fail_stays_cant_tell(self) -> None:
        facts = [
            base.WORDS_FACT,
            {**command("k1", 110.0, "passed", PUSH), "cannot_fail": True},
            said(120.0),
        ]
        row = departs(facts)
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, row["why"])
        self.assertNotIn("k1", row["cites"])

    def test_a_dry_run_stays_cant_tell(self) -> None:
        for text in ("git push --dry-run origin main", "git push -n origin main"):
            with self.subTest(text=text):
                row = departs(pushed(text))
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_a_push_forced_to_exit_zero_stays_cant_tell(self) -> None:
        row = departs(pushed("git push origin main || true"))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_a_push_from_before_the_line_was_requested_stays_cant_tell(self) -> None:
        row = read(
            pushed(at=110.0),
            {"line_1": ("departure", ("k1", "m1"))},
            line_requests={"line_1": 115.0},
        )["line_1"]
        self.assertNotEqual(reading.WHY_RECORDED_COMMAND, row["why"])
        self.assertNotIn("k1", row["cites"])

    def test_a_push_after_the_line_was_requested_departs(self) -> None:
        row = read(
            pushed(at=110.0),
            {"line_1": ("departure", ("k1", "m1"))},
            line_requests={"line_1": 100.0},
        )["line_1"]
        self.assertEqual(reading.WHY_RECORDED_COMMAND, row["why"])

    def test_a_consistent_or_cant_tell_reply_is_never_raised(self) -> None:
        for token in ("consistent", "unverifiable"):
            with self.subTest(token=token):
                row = read(pushed(), {"line_1": (token, ("k1", "m1"))})["line_1"]
                self.assertNotEqual(reading.RESULT_DEPARTURE, row["result"])
                self.assertNotEqual(reading.WHY_RECORDED_COMMAND, row["why"])

    def test_a_condition_in_the_line_keeps_it_cant_tell(self) -> None:
        for line in (
            "Don't push to main until CI passes",
            "Don't push to main, unless CI is green",
        ):
            with self.subTest(line=line):
                row = departs(pushed(), line)
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])

    def test_a_force_push_ban_needs_a_force_in_the_command(self) -> None:
        line = "Don't force-push to main"
        plain = departs(pushed(), line)
        self.assertEqual(reading.RESULT_UNVERIFIABLE, plain["result"])
        for text in ("git push --force origin main", "git push origin +main"):
            with self.subTest(text=text):
                self.assertEqual(reading.WHY_RECORDED_COMMAND, departs(pushed(text), line)["why"])

    def test_a_refspec_departs_by_its_destination_not_its_source(self) -> None:
        self.assertEqual(
            reading.WHY_RECORDED_COMMAND, departs(pushed("git push origin HEAD:main"))["why"]
        )
        self.assertEqual(
            reading.RESULT_UNVERIFIABLE, departs(pushed("git push origin main:feature"))["result"]
        )

    def test_a_push_with_no_refspec_departs_only_a_line_that_names_no_branch(self) -> None:
        self.assertEqual(
            reading.WHY_RECORDED_COMMAND, departs(pushed("git push"), "Don't push")["why"]
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, departs(pushed("git push"))["result"])

    def test_a_push_to_head_departs_only_a_line_that_names_no_branch(self) -> None:
        self.assertEqual(
            reading.WHY_RECORDED_COMMAND,
            departs(pushed("git push origin HEAD"), "Don't push")["why"],
        )
        self.assertEqual(
            reading.RESULT_UNVERIFIABLE, departs(pushed("git push origin HEAD"))["result"]
        )

    def test_a_goal_that_forbids_a_push_keeps_its_own_words_rule(self) -> None:
        row = read(
            pushed(),
            {"goal": ("departure", ("k1", "m1"))},
            goal="Do not push to main",
            lines=("The retry handler is wired",),
        )["goal"]
        self.assertNotEqual(reading.WHY_RECORDED_COMMAND, row["why"])

    def test_the_matched_commands_come_first_and_at_most_three_are_cited(self) -> None:
        facts = [
            base.WORDS_FACT,
            *[command(f"k{n}", 100.0 + n, "passed", PUSH) for n in range(1, 5)],
            said(120.0),
        ]
        row = departs(facts, cites=("k1", "k2", "k3", "k4", "m1"))
        self.assertEqual(reading.WHY_RECORDED_COMMAND, row["why"])
        self.assertEqual(("k1", "k2", "k3", "m1"), row["cites"][: reading.MAX_RECORDED_CITES + 1])

    def test_a_command_that_does_not_match_is_not_carried_beside_the_push(self) -> None:
        facts = [
            base.WORDS_FACT,
            command("k1", 110.0, "passed", PUSH),
            command("k2", 111.0, "passed", "npm install"),
            said(120.0),
        ]
        row = departs(facts, cites=("k1", "k2", "m1"))
        self.assertEqual(("k1", "m1"), row["cites"])


class AStoredRecordedCommandRowIsReadAgainByLevelsAndCorrection(unittest.TestCase):
    def _stored(self, why: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
                "cites": ["k1"],
                "detail": "`git push origin main` ran and exited 0 after this line, which rules it out.",
                "clause": PUSH_LINE,
                "why": why,
            },
        }
        facts = [base.WORDS_FACT, base.AGENT_MESSAGE_FACT, command("k1", 110.0, "passed", PUSH)]
        return {"read_at": 200.0, "window_start": 50.0, "criteria": criteria}, facts

    def test_the_level_counts_the_stored_row_as_departed(self) -> None:
        row, facts = self._stored(reading.WHY_RECORDED_COMMAND)
        got = levels.analysis_level(
            row,
            levels.Evidence(
                facts=tuple(facts), scan={"last_user_at": 50.0}, unsettled_directions=0
            ),
            outcome_lines=1,
        )
        self.assertIn(levels.REASON_DEPARTURE, got.reasons)

    def test_the_level_does_not_count_the_same_cite_under_a_model_departure(self) -> None:
        row, facts = self._stored("")
        got = levels.analysis_level(
            row,
            levels.Evidence(
                facts=tuple(facts), scan={"last_user_at": 50.0}, unsettled_directions=0
            ),
            outcome_lines=1,
        )
        self.assertNotIn(levels.REASON_DEPARTURE, got.reasons)

    def test_the_correction_names_the_push_the_record_settled(self) -> None:
        row, facts = self._stored(reading.WHY_RECORDED_COMMAND)
        rows = correction._Rows(row, facts, "claude", unsettled=False, lines_judged=True, sid="s1")
        state, cited = rows.state("line_1")
        self.assertEqual("departed", state)
        self.assertEqual("k1", (cited or {}).get("fact_id"))
        row["criteria"]["line_1"]["why"] = ""
        rows = correction._Rows(row, facts, "claude", unsettled=False, lines_judged=True, sid="s1")
        self.assertNotEqual("departed", rows.state("line_1")[0])

    def test_the_stored_token_is_one_a_reading_may_carry(self) -> None:
        self.assertIn(reading.WHY_RECORDED_COMMAND, reading.WHY_TOKENS)

    def test_a_command_carries_the_departure_only_under_the_token(self) -> None:
        entry = {
            "type": "tool_report",
            "subject": "command",
            "result": "passed",
            "at": 110.0,
            "summary": PUSH,
        }
        self.assertFalse(reading.check_supports(entry, reading.RESULT_DEPARTURE, 50.0))
        self.assertTrue(
            reading.check_supports(entry, reading.RESULT_DEPARTURE, 50.0, recorded_command=True)
        )
        for label, other in (
            ("a passing check", {**entry, "subject": "check"}),
            ("a command with no recorded result", {**entry, "result": ""}),
            ("a message", {**entry, "type": "agent_message"}),
        ):
            with self.subTest(other=label):
                self.assertFalse(
                    reading.check_supports(
                        other, reading.RESULT_DEPARTURE, 50.0, recorded_command=True
                    )
                )
        self.assertFalse(
            reading.check_supports(
                {**entry, "cannot_fail": True},
                reading.RESULT_DEPARTURE,
                50.0,
                recorded_command=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
