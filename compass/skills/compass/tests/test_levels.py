"""The four drift levels, and the two ways a session can say it has too little to tell.

[DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)
rules two sources, each over its own named evidence: a live estimate computed without a model from
the checks and written paths the transcript recorded, and an analysis level derived from a stored
reading's per-line results. DRC-4692 names six cases the levels must get right before any reader
sees one; each is a class below, and each runs both functions.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import levels, reading

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SAVE = 1_800_000_000.0


def check(
    fid: str, at: float | None, result: str, *, stale: bool = False, changed: bool = False
) -> dict[str, Any]:
    """A check's latest run, as layer 1 publishes it into the observed record."""
    return {
        "fact_id": fid,
        "type": "tool_report",
        "subject": "check",
        "summary": "node --test",
        "result": result,
        "before_last_change": stale,
        "changed_after": changed,
        "at": at,
        "source_session": {"harness": "claude", "sid": "s"},
        "evidence": {"source": "Claude Bash call and paired result", "confidence": "recorded"},
    }


def wrote(fid: str, at: float, path: str) -> dict[str, Any]:
    """A written path, relative to the session's working directory."""
    return {"fact_id": fid, "type": "tool_report", "subject": "write", "summary": path, "at": at}


def scan(**counts: Any) -> dict[str, Any]:
    """The full-scan counts, zero unless named."""
    body: dict[str, Any] = dict.fromkeys(
        (
            "failed",
            "passed",
            "not_recorded",
            "background",
            "written_paths",
            "outside_paths",
            "more",
        ),
        0,
    )
    body["last_changing_command_at"] = None
    body["last_user_at"] = SAVE
    body.update(counts)
    return body


def evidence(
    facts: Sequence[Mapping[str, Any]],
    counts: Mapping[str, Any],
    *,
    directions: int = 0,
    cwd: str = "/synthetic/project",
) -> levels.Evidence:
    return levels.Evidence(
        facts=tuple(facts), scan=counts, unsettled_directions=directions, cwd=cwd
    )


def analyze(
    row: Mapping[str, Any] | None, facts: levels.Evidence, *, lines: int | None = None
) -> levels.Level:
    """The analysis level, told how many outcome lines the intent holds (by default, as many as
    the reading answers, so only the tests about a missing line pass a different count)."""
    criteria = (row or {}).get("criteria") or {}
    count = sum(1 for k in criteria if reading.is_outcome_line(k)) if lines is None else lines
    return levels.analysis_level(row, facts, outcome_lines=count)


def intent(
    *lines: str, saved: bool = True, goal: str = "Build the tic-tac-toe game"
) -> levels.Intent:
    return levels.Intent(saved=saved, goal=goal, lines=tuple(lines))


def criterion(result: str | None, *cites: str, why: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {"cites": cites, "detail": "", "clause": "", "why": why}
    if result is not None:
        row["result"] = result
    return row


def a_reading(**criteria: dict[str, Any]) -> dict[str, Any]:
    return {"read_at": SAVE + 600, "window_start": SAVE, "criteria": criteria}


PASSING = evidence(
    [
        wrote("w1", SAVE + 10, "index.html"),
        check("c1", SAVE + 20, "passed"),
        {
            "fact_id": "m1",
            "type": "agent_message",
            "summary": "Synthetic final account",
            "at": SAVE + 20,
            "source_session": {"harness": "claude", "sid": "s"},
            "evidence": {"source": "Claude assistant message", "confidence": "recorded"},
        },
    ],
    scan(passed=1, written_paths=1),
)
SUPPORTED = a_reading(
    goal=criterion(reading.RESULT_CONSISTENT, "m1"),
    line_1=criterion(reading.RESULT_CONSISTENT, "c1"),
)


def done_fact(fid: str, subject: str, summary: str, at: float) -> dict[str, Any]:
    """A created pull request or a used skill, as layer 1 publishes it."""
    return {
        "fact_id": fid,
        "type": "tool_report",
        "subject": subject,
        "summary": summary,
        "at": at,
        "source_session": {"harness": "claude", "sid": "s"},
        "evidence": {"source": "Claude Bash call result", "confidence": "exact"},
    }


RECORDED_DONE = evidence(
    [
        done_fact("skill1", "skill", "linear-deep-dive", SAVE + 10),
        done_fact("pr1", "pr", "example-org/example-repo#7", SAVE + 20),
        *PASSING.facts[2:],
    ],
    scan(),
)
RECORDED_DONE_READING = a_reading(
    goal=criterion(reading.RESULT_CONSISTENT, "skill1", "pr1"),
    line_1=criterion(reading.RESULT_CONSISTENT, "pr1"),
)


class AnIncompletePassIsCautionTest(unittest.TestCase):
    def test_it_does_not_meet_the_live_floor(self) -> None:
        facts = evidence(
            [{**check("c1", SAVE + 20, "passed"), "read_incomplete": True}], scan(passed=1)
        )
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertIn("pass-older-than-read", got.reasons)
        self.assertNotIn("command-after-pass", got.reasons)

    def test_it_does_not_show_a_consistent_line_or_claim_a_change_in_analysis(self) -> None:
        facts = evidence(
            [{**check("c1", SAVE + 20, "passed"), "read_incomplete": True}], scan(passed=1)
        )
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertNotIn("pass-then-write", got.reasons)

    def test_a_stored_incomplete_reason_without_a_cited_fact_still_withholds(self) -> None:
        got = analyze(
            a_reading(line_1=criterion(reading.RESULT_UNVERIFIABLE, why="check-read-incomplete")),
            PASSING,
        )
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertNotIn("pass-then-write", got.reasons)

    def test_an_independent_failure_remains_high(self) -> None:
        facts = evidence(
            [
                {**check("c1", SAVE + 20, "passed"), "read_incomplete": True},
                check("c2", SAVE + 30, "failed"),
            ],
            scan(passed=1, failed=1),
        )
        self.assertEqual(levels.HIGH, levels.live_level(facts, intent("Tests pass")).level)


class FailedCheckTest(unittest.TestCase):
    """The latest run of a check failed: High on both sources (starting definitions)."""

    FACTS = evidence([check("c1", SAVE + 20, "failed")], scan(failed=1))

    def test_the_live_estimate_is_high_and_names_the_failed_check(self) -> None:
        got = levels.live_level(self.FACTS, intent("Tests pass"))
        self.assertEqual(got.level, levels.HIGH)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)
        self.assertEqual(got.cites, ("c1",))
        self.assertEqual(got.source, levels.SOURCE_LIVE)

    def test_an_analysis_departing_on_that_failure_is_high(self) -> None:
        got = analyze(a_reading(line_1=criterion(reading.RESULT_DEPARTURE, "c1")), self.FACTS)
        self.assertEqual(got.level, levels.HIGH)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)
        self.assertEqual(got.source, levels.SOURCE_ANALYSIS)

    def test_a_failure_the_analysis_did_not_cite_still_keeps_it_high(self) -> None:
        got = analyze(
            a_reading(line_1=criterion(reading.RESULT_UNVERIFIABLE, why="failed-check-unread")),
            self.FACTS,
        )
        self.assertEqual(got.level, levels.HIGH)

    def test_an_earlier_passing_run_does_not_soften_it(self) -> None:
        facts = evidence(
            [check("c1", SAVE + 20, "failed"), check("c2", SAVE + 5, "passed")],
            scan(failed=1, passed=1),
        )
        self.assertEqual(levels.live_level(facts, intent("Tests pass")).level, levels.HIGH)


class CheckWithNoRecordedResultTest(unittest.TestCase):
    """A check with no recorded result never counts toward "None or low" (DEC-26 item 1)."""

    def test_the_live_estimate_reads_not_enough(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "not-recorded")], scan(not_recorded=1))
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_CHECK_NOT_RECORDED, got.reasons)

    def test_one_such_check_beside_a_pass_still_withholds_the_floor(self) -> None:
        facts = evidence(
            [check("c1", SAVE + 20, "not-recorded"), check("c2", SAVE + 30, "passed")],
            scan(not_recorded=1, passed=1),
        )
        self.assertEqual(levels.live_level(facts, intent("Tests pass")).level, levels.NOT_ENOUGH)

    def test_a_run_only_ever_launched_in_the_background_withholds_the_floor(self) -> None:
        # 3f4e7b30: a background-only check is not listed and not counted, so
        # only the launch count shows that something ran without a result.
        facts = evidence(list(PASSING.facts), scan(passed=1, background=1))
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_BACKGROUND_RUN, got.reasons)

    def test_an_analysis_citing_it_reads_not_enough(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "not-recorded")], scan(not_recorded=1))
        got = analyze(a_reading(line_1=criterion(reading.RESULT_UNVERIFIABLE, "c1")), facts)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_LINE_NOT_SHOWN, got.reasons)

    def test_a_consistent_resting_on_it_is_not_counted_as_shown(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "not-recorded")], scan(not_recorded=1))
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(got.level, levels.NOT_ENOUGH)


class PassFollowedByWriteTest(unittest.TestCase):
    """A pass followed by writes is Medium (starting definitions)."""

    FACTS = evidence(
        [check("c1", SAVE + 20, "passed", stale=True), wrote("w1", SAVE + 30, "index.html")],
        scan(passed=1, written_paths=1),
    )

    def test_the_live_estimate_is_medium_and_cites_the_aged_pass(self) -> None:
        got = levels.live_level(self.FACTS, intent("Tests pass"))
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_PASS_THEN_WRITE, got.reasons)
        self.assertIn("c1", got.cites)

    def test_an_analysis_demoting_the_aged_pass_is_medium(self) -> None:
        got = analyze(
            a_reading(
                line_1=criterion(
                    reading.RESULT_UNVERIFIABLE, "c1", why=reading.WHY_CHECK_DOES_NOT_SHOW_IT
                )
            ),
            self.FACTS,
        )
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_PASS_THEN_WRITE, got.reasons)

    def test_a_pass_a_later_command_may_have_changed_is_medium_too(self) -> None:
        got = analyze(
            a_reading(
                line_1=criterion(
                    reading.RESULT_UNVERIFIABLE, "c1", why=reading.WHY_CHANGED_AFTER_CHECK
                )
            ),
            evidence([check("c1", SAVE + 20, "passed")], scan(passed=1)),
        )
        self.assertEqual(got.level, levels.MEDIUM)


class OwnAccountOnlyTest(unittest.TestCase):
    """845fe493: the final message claims a layout no check covers.

    The live estimate reads checks and file paths, not what the intent says, so a
    session whose checks pass reads "None or low" there and says so. Since the
    owner's ruling of 2026-10-03 a reading may rest an outcome line on the agent's
    own account, but the analysis floor still needs a passing check (DEC-26): the
    agent's word alone never reassures, and a departure on it reads Medium.
    """

    def test_a_departure_on_the_agents_account_reads_medium(self) -> None:
        got = analyze(a_reading(line_1=criterion(reading.RESULT_DEPARTURE, "m1")), PASSING)
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_DEPARTURE, got.reasons)
        self.assertEqual(got.cites, ("m1",))

    def test_the_live_estimate_meets_its_floor_and_says_what_it_read(self) -> None:
        got = levels.live_level(PASSING, intent("Works on a phone"))
        self.assertEqual(got.level, levels.NONE_OR_LOW)
        self.assertIn(levels.REASON_FLOOR_MET, got.reasons)
        self.assertEqual(got.source_line, levels.LIVE_SOURCE_LINE)

    def test_an_outcome_line_on_the_agents_account_reads_not_enough(self) -> None:
        got = analyze(
            a_reading(
                goal=criterion(reading.RESULT_CONSISTENT, "c1"),
                line_1=criterion(reading.RESULT_UNVERIFIABLE, "m1", why=reading.WHY_NO_WORK_SHOWN),
            ),
            PASSING,
        )
        self.assertEqual(got.level, levels.NOT_ENOUGH)

    def test_a_consistent_citing_only_a_message_is_never_the_floor(self) -> None:
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "m1")), PASSING)
        self.assertEqual(got.level, levels.NOT_ENOUGH)

    def test_the_goal_may_rest_on_the_sessions_own_account(self) -> None:
        got = analyze(SUPPORTED, PASSING)
        self.assertEqual(got.level, levels.NONE_OR_LOW)
        self.assertEqual(got.source_line, levels.ANALYSIS_SOURCE_LINE)
        self.assertEqual(got.computed_at, SAVE + 600)


class IntentNamesNoFolderTest(unittest.TestCase):
    """The folder signal is not used when the intent names no folder, so it is never read as 0%."""

    SPREAD = evidence(
        [
            wrote("w1", SAVE + 5, "server/app.py"),
            wrote("w2", SAVE + 6, "server/db.py"),
            wrote("w3", SAVE + 7, "web/index.html"),
            check("c1", SAVE + 20, "passed"),
        ],
        scan(passed=1, written_paths=3),
    )

    def test_no_folder_leaves_the_share_unread(self) -> None:
        got = levels.live_level(self.SPREAD, intent("Tests pass"))
        self.assertEqual(got.level, levels.NONE_OR_LOW)
        self.assertIn(levels.REASON_NO_FOLDER, got.reasons)
        self.assertIsNone(got.writes_outside)
        self.assertIsNone(got.writes_total)

    def test_a_named_folder_with_some_writes_outside_is_medium(self) -> None:
        got = levels.live_level(self.SPREAD, intent("Only touch `server/`", "Tests pass"))
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_SOME_OUTSIDE, got.reasons)
        self.assertEqual((got.writes_outside, got.writes_total), (1, 3))
        self.assertEqual(got.cites, ("w3",))

    def test_most_writes_outside_is_high(self) -> None:
        got = levels.live_level(self.SPREAD, intent("Only touch web/", "Tests pass"))
        self.assertEqual(got.level, levels.HIGH)
        self.assertIn(levels.REASON_MOST_OUTSIDE, got.reasons)

    def test_every_write_inside_meets_the_floor_and_counts_the_share(self) -> None:
        got = levels.live_level(self.SPREAD, intent("Work in server/ and web/"))
        self.assertEqual(got.level, levels.NONE_OR_LOW)
        self.assertEqual((got.writes_outside, got.writes_total), (0, 3))

    def test_a_write_outside_the_working_directory_is_outside_every_folder(self) -> None:
        with mock.patch("compass_runtime.levels.os.path.isdir", return_value=True):
            facts = evidence([check("c1", SAVE + 20, "passed")], scan(passed=1, outside_paths=1))
            got = levels.live_level(facts, intent("Only touch server/"))
            self.assertEqual(got.level, levels.HIGH)

    def test_the_analysis_does_not_read_folders_at_all(self) -> None:
        self.assertEqual(analyze(SUPPORTED, self.SPREAD).level, levels.NONE_OR_LOW)


class UnsavedDraftTest(unittest.TestCase):
    """Over an unsaved draft there is no live level (DEC-26 item 2)."""

    def test_the_live_estimate_has_no_level_even_over_a_failure(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "failed")], scan(failed=1))
        got = levels.live_level(facts, intent("Tests pass", saved=False))
        self.assertEqual(got.level, levels.NO_LIVE_LEVEL)
        self.assertEqual(got.reasons, (levels.REASON_DRAFT_UNSAVED,))
        self.assertEqual(got.cites, ())

    def test_with_no_reading_the_analysis_has_too_little(self) -> None:
        got = analyze(None, PASSING)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertEqual(got.reasons, (levels.REASON_NO_READING,))


class FloorTest(unittest.TestCase):
    """What else keeps "None or low" off a session: DEC-26 item 1, clause by clause."""

    def test_zero_checks_is_too_little(self) -> None:
        facts = evidence([wrote("w1", SAVE + 5, "index.html")], scan(written_paths=1))
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_NO_PASSING_CHECK, got.reasons)

    def test_a_goal_alone_can_read_none_or_low_when_a_passing_check_shows_it(self) -> None:
        got = analyze(a_reading(goal=criterion(reading.RESULT_CONSISTENT, "c1")), PASSING)
        self.assertEqual(got.level, levels.NONE_OR_LOW)
        self.assertNotIn(levels.REASON_NO_OUTCOME_LINE, got.reasons)

    def test_recorded_harness_facts_show_a_goal_and_its_line_with_no_passing_check(self) -> None:
        # DEC-26's 2026-10-24 amendment: a created pull request or a used skill is a recorded
        # harness fact, so a consistent line that cites one reaches the floor without a pass.
        got = analyze(RECORDED_DONE_READING, RECORDED_DONE)
        self.assertEqual(levels.NONE_OR_LOW, got.level)
        self.assertEqual((levels.REASON_FLOOR_MET,), got.reasons)
        self.assertEqual({"pr1"}, set(got.cites))

    def test_the_same_shape_citing_only_the_agents_words_draws_no_level(self) -> None:
        row = a_reading(
            goal=criterion(reading.RESULT_CONSISTENT, "m1"),
            line_1=criterion(reading.RESULT_CONSISTENT, "m1"),
        )
        got = analyze(row, RECORDED_DONE)
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertIn(levels.REASON_LINE_NOT_SHOWN, got.reasons)

    def test_one_line_resting_on_words_alone_still_keeps_the_floor_off(self) -> None:
        row = a_reading(
            goal=criterion(reading.RESULT_CONSISTENT, "skill1", "pr1"),
            line_1=criterion(reading.RESULT_CONSISTENT, "m1"),
        )
        self.assertEqual(levels.NOT_ENOUGH, analyze(row, RECORDED_DONE).level)

    def test_a_failed_check_or_a_later_direction_still_blocks_recorded_facts(self) -> None:
        failing = evidence([*RECORDED_DONE.facts, check("f1", SAVE + 40, "failed")], scan(failed=1))
        self.assertNotEqual(levels.NONE_OR_LOW, analyze(RECORDED_DONE_READING, failing).level)
        later = evidence(list(RECORDED_DONE.facts), dict(RECORDED_DONE.scan), directions=1)
        got = analyze(RECORDED_DONE_READING, later)
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertIn(levels.REASON_LATER_DIRECTION, got.reasons)

    def test_a_recorded_fact_outside_the_reading_window_does_not_show_a_line(self) -> None:
        early = evidence(
            [
                {**f, "at": SAVE - 50} if f["fact_id"] in ("skill1", "pr1") else f
                for f in RECORDED_DONE.facts
            ],
            dict(RECORDED_DONE.scan),
        )
        self.assertEqual(levels.NOT_ENOUGH, analyze(RECORDED_DONE_READING, early).level)

    def test_a_goal_alone_the_agents_word_only_supports_is_not_none_or_low(self) -> None:
        got = analyze(a_reading(goal=criterion(reading.RESULT_CONSISTENT, "m1")), PASSING)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_LINE_NOT_SHOWN, got.reasons)
        self.assertNotIn(levels.REASON_NO_OUTCOME_LINE, got.reasons)

    def test_a_goal_alone_the_model_could_not_settle_is_not_none_or_low(self) -> None:
        got = analyze(a_reading(goal=criterion(reading.RESULT_UNVERIFIABLE)), PASSING)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertNotIn(levels.REASON_NO_OUTCOME_LINE, got.reasons)

    def test_a_goal_unclear_reading_has_no_level_whatever_the_record_holds(self) -> None:
        failing = evidence([check("f1", SAVE + 20, "failed")], scan(failed=1))
        for lines in (0, 1):
            with self.subTest(lines=lines):
                row = a_reading(goal=criterion(reading.RESULT_GOAL_UNCLEAR))
                if lines:
                    row["criteria"]["line_1"] = criterion(
                        reading.RESULT_UNVERIFIABLE, why=reading.WHY_NOT_ASKED
                    )
                got = analyze(row, failing)
                self.assertEqual(got.level, levels.NOT_ENOUGH)
                self.assertEqual(got.reasons, (levels.REASON_GOAL_UNCLEAR,))

    def test_the_retired_reason_stays_a_known_token_for_readings_stored_before(self) -> None:
        self.assertIn(levels.REASON_NO_OUTCOME_LINE, levels.REASONS)
        self.assertIn(levels.REASON_GOAL_UNCLEAR, levels.REASONS)

    def test_a_later_direction_blocks_the_floor_and_is_never_drift(self) -> None:
        with_direction = evidence(list(PASSING.facts), dict(PASSING.scan), directions=1)
        got = levels.live_level(with_direction, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_LATER_DIRECTION, got.reasons)
        self.assertEqual(analyze(SUPPORTED, with_direction).level, levels.NOT_ENOUGH)

    def test_a_later_direction_does_not_raise_a_level(self) -> None:
        failed = evidence([check("c1", SAVE + 20, "failed")], scan(failed=1), directions=2)
        self.assertEqual(levels.live_level(failed, intent("Tests pass")).level, levels.HIGH)

    def test_a_changing_command_after_the_pass_blocks_the_floor_and_is_never_drift(self) -> None:
        facts = evidence(list(PASSING.facts), scan(passed=1, last_changing_command_at=SAVE + 40))
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_CHANGING_COMMAND, got.reasons)

    def test_a_changing_command_before_the_pass_does_not(self) -> None:
        facts = evidence(list(PASSING.facts), scan(passed=1, last_changing_command_at=SAVE + 1))
        self.assertEqual(levels.live_level(facts, intent("Tests pass")).level, levels.NONE_OR_LOW)

    def test_a_pass_the_listed_entries_cannot_show_withholds_the_floor(self) -> None:
        # Item 4: every answer comes from the full scan. A pass counted and not
        # listed has no time to compare a write or a command against.
        facts = evidence(list(PASSING.facts), scan(passed=2, written_paths=1, more=1))
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_UNLISTED, got.reasons)

    def test_an_unlisted_write_withholds_the_floor_where_folders_are_named(self) -> None:
        facts = evidence(
            [wrote("w1", SAVE + 5, "web/index.html"), check("c1", SAVE + 20, "passed")],
            scan(passed=1, written_paths=2, more=1),
        )
        got = levels.live_level(facts, intent("Only touch web/"))
        # The unplaced write counts as outside (L2), so one of two is outside.
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_UNLISTED, got.reasons)

    def test_an_analysis_with_every_line_supported_meets_the_floor(self) -> None:
        got = analyze(SUPPORTED, PASSING)
        self.assertEqual(got.level, levels.NONE_OR_LOW)
        self.assertEqual(got.cites, ("c1",))


class ALineAboutWhatTheAgentTellsYouIsReadLikeAnyOtherTest(unittest.TestCase):
    """DRC-4742 withdrew a `consistent` on a line about what the agent tells the
    reader. Since the owner's ruling of 2026-10-03 the agent's messages are in
    evidence, so such a line is checkable and the level reads it like any other."""

    LINE = "node --test is run once, unpiped, and its counts are reported"

    def test_a_stored_consistent_on_a_telling_line_with_a_passing_check_meets_the_floor(
        self,
    ) -> None:
        stored = a_reading(
            goal=criterion(reading.RESULT_CONSISTENT, "m1"),
            line_1={**criterion(reading.RESULT_CONSISTENT, "c1", "m1"), "clause": self.LINE},
        )
        got = analyze(stored, PASSING)
        self.assertEqual(levels.NONE_OR_LOW, got.level)
        self.assertIn("c1", got.cites)

    def test_on_the_agents_account_alone_it_never_reaches_the_floor(self) -> None:
        stored = a_reading(
            line_1={**criterion(reading.RESULT_CONSISTENT, "m1"), "clause": self.LINE},
        )
        got = analyze(stored, PASSING)
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertIn(levels.REASON_LINE_NOT_SHOWN, got.reasons)

    def test_a_stored_tells_the_person_row_still_reads_back(self) -> None:
        stored = a_reading(
            goal=criterion(reading.RESULT_CONSISTENT, "m1"),
            line_1=criterion(reading.RESULT_UNVERIFIABLE, why=reading.WHY_TELLS_THE_PERSON),
        )
        got = analyze(stored, PASSING)
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertNotIn(levels.REASON_READING_MALFORMED, got.reasons)


class ExtremeTest(unittest.TestCase):
    """Extreme: both of High's conditions hold."""

    def test_a_failed_check_and_most_writes_outside_is_extreme(self) -> None:
        with mock.patch("compass_runtime.levels.os.path.isdir", return_value=True):
            facts = evidence(
                [check("c1", SAVE + 20, "failed"), wrote("w1", SAVE + 5, "server/app.py")],
                scan(failed=1, written_paths=1),
            )
            got = levels.live_level(facts, intent("Only touch web/"))
            self.assertEqual(got.level, levels.EXTREME)
            self.assertEqual(set(got.cites), {"c1", "w1"})

    def test_an_analysis_never_reads_extreme_because_it_reads_no_folder(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "failed")], scan(failed=1))
        got = analyze(
            a_reading(
                line_1=criterion(reading.RESULT_DEPARTURE, "c1"),
                line_2=criterion(reading.RESULT_DEPARTURE, "m1"),
                line_3=criterion(reading.RESULT_CONSISTENT, "c9"),
            ),
            facts,
        )
        self.assertEqual(got.level, levels.HIGH)

    def test_a_departure_on_no_failed_check_is_medium(self) -> None:
        got = analyze(
            a_reading(
                goal=criterion(reading.RESULT_DEPARTURE, "m1"),
                line_1=criterion(reading.RESULT_UNVERIFIABLE),
            ),
            PASSING,
        )
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_DEPARTURE, got.reasons)


class NamedFoldersTest(unittest.TestCase):
    """What counts as a folder the intent names: a path-shaped word, never a URL or a file."""

    def test_the_forms_that_name_a_folder(self) -> None:
        self.assertEqual(
            levels.named_folders(intent("Work in `src/app/` and ./web, then tests/unit.")),
            ("src/app", "tests/unit", "web"),
        )

    def test_v1_a_multi_part_path_names_a_folder(self) -> None:
        # V1: the verifier's inputs, which L8 had made name nothing.
        for words, folder in (
            ("only touch web/app", "web/app"),
            ("edit src/components", "src/components"),
            ("keep to compass_runtime/web", "compass_runtime/web"),
            ("src/foo_bar", "src/foo_bar"),
            ("touch web/Makefile", "web/Makefile"),
            ("touch web/.env", "web"),
        ):
            self.assertEqual(levels.named_folders(intent(words)), (folder,), words)

    def test_v1_an_absolute_folder_inside_the_cwd_needs_no_slash(self) -> None:
        got = levels.named_folders(intent("only touch /work/ttt/web"), cwd="/work/ttt")
        self.assertEqual(got, ("web",))

    def test_v1_only_the_closed_prose_list_is_refused(self) -> None:
        prose = "and/or either/or client/server input/output read/write true/false yes/no"
        prose += " on/off before/after And/Or"
        self.assertEqual(levels.named_folders(intent(prose)), ())

    def test_v1_a_named_multi_part_folder_reads_writes_outside_it(self) -> None:
        with mock.patch("compass_runtime.levels.os.path.isdir", return_value=True):
            facts = evidence(
                [wrote("w1", SAVE + 5, "src/x.py"), check("c1", SAVE + 20, "passed")],
                scan(passed=1, written_paths=1),
            )
            got = levels.live_level(facts, intent("only touch web/app"))
            self.assertEqual(got.level, levels.HIGH)
            self.assertIn(levels.REASON_MOST_OUTSIDE, got.reasons)

    def test_prose_with_a_slash_names_nothing(self) -> None:
        # L8: "and/or" and "client/server" are words, not paths.
        self.assertEqual(
            levels.named_folders(intent("Fix the client/server split and/or the input/output")), ()
        )

    def test_a_trailing_slash_marks_a_folder_even_with_a_dot(self) -> None:
        self.assertEqual(levels.named_folders(intent("Only touch `.github/`")), (".github",))

    def test_an_absolute_folder_inside_the_working_directory_reads_as_relative(self) -> None:
        # L9
        got = levels.named_folders(intent("Only edit /work/ttt/web/"), cwd="/work/ttt")
        self.assertEqual(got, ("web",))

    def test_an_absolute_folder_outside_it_is_still_named(self) -> None:
        got = levels.named_folders(intent("Only edit /elsewhere/lib/"), cwd="/work/ttt")
        self.assertEqual(got, ("/elsewhere/lib",))

    def test_a_trailing_slash_names_a_single_folder(self) -> None:
        self.assertEqual(levels.named_folders(intent("Only touch server/")), ("server",))

    def test_urls_and_bare_words_name_none(self) -> None:
        self.assertEqual(
            levels.named_folders(intent("See https://example.com/a/b and edit index.html")), ()
        )

    def test_a_file_path_names_its_folder(self) -> None:
        self.assertEqual(levels.named_folders(intent("Change web/app.js")), ("web",))

    def test_a_write_to_the_folder_itself_or_below_is_inside(self) -> None:
        self.assertTrue(levels.inside("web/app.js", ("web",)))
        self.assertTrue(levels.inside("web", ("web",)))
        self.assertFalse(levels.inside("website/app.js", ("web",)))

    @unittest.expectedFailure  # DRC-4891: the ruling is recorded; levels.inside changes in its own PR.
    def test_a_worktree_checkout_write_is_read_inside_its_checkout(self) -> None:
        # Ruled 2026-10-21 (DRC-4891): the same folder inside its checkout, not outside it.
        prefix = ".claude/worktrees/agent-a1"
        self.assertTrue(levels.inside(f"{prefix}/src/m.py", ("src",)))
        self.assertTrue(levels.inside(f"{prefix}/src", ("src",)))
        self.assertFalse(levels.inside(f"{prefix}/web/m.py", ("src",)))
        self.assertFalse(levels.inside(f"{prefix}/srcs/m.py", ("src",)))
        self.assertFalse(levels.inside(".claude/worktrees/src/m.py", ("src",)))


class CorrectionRoundTest(unittest.TestCase):
    """DRC-4692's review round. Every correction moves toward a higher level or Not enough."""

    def test_l1_a_change_later_in_the_passing_call_blocks_the_floor(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "passed", changed=True)], scan(passed=1))
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_CHANGING_COMMAND, got.reasons)

    def test_l1_a_changing_command_at_the_same_time_as_the_pass_blocks_the_floor(self) -> None:
        facts = evidence(
            [check("c1", SAVE + 20, "passed")], scan(passed=1, last_changing_command_at=SAVE + 20)
        )
        self.assertEqual(levels.live_level(facts, intent("Tests pass")).level, levels.NOT_ENOUGH)

    def test_l2_an_unplaced_write_counts_as_outside(self) -> None:
        with mock.patch("compass_runtime.levels.os.path.isdir", return_value=True):
            facts = evidence(
                [check("c1", SAVE + 20, "passed"), wrote("w1", SAVE + 5, "src/a.py")],
                scan(passed=1, written_paths=3, more=2),
            )
            got = levels.live_level(facts, intent("Only touch web/"))
            self.assertEqual(got.level, levels.HIGH)
            self.assertEqual((got.writes_outside, got.writes_total), (3, 3))
            self.assertIn(levels.REASON_UNLISTED, got.reasons)

    def test_l2_unplaced_writes_can_make_a_listed_inside_write_a_minority(self) -> None:
        facts = evidence(
            [check("c1", SAVE + 20, "passed"), wrote("w1", SAVE + 5, "web/a.js")],
            scan(passed=1, written_paths=3, more=2),
        )
        self.assertEqual(levels.live_level(facts, intent("Only touch web/")).level, levels.HIGH)

    def test_l3_a_failure_before_the_window_still_blocks_the_floor(self) -> None:
        facts = evidence(
            [check("f1", SAVE - 100, "failed"), check("c1", SAVE + 20, "passed")],
            scan(failed=1, passed=1),
        )
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)

    def test_l3_a_failure_with_no_time_blocks_the_floor_without_raising_high(self) -> None:
        facts = evidence(
            [check("f1", None, "failed"), check("c1", SAVE + 20, "passed")],
            scan(failed=1, passed=1),
        )
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)

    def test_l4_a_row_that_is_not_an_object_is_malformed(self) -> None:
        row = a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1"))
        row["criteria"]["line_2"] = "garbage"
        got = analyze(row, PASSING, lines=2)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_READING_MALFORMED, got.reasons)

    def test_l4_a_key_outside_the_constraints_is_malformed(self) -> None:
        row = a_reading(
            line_1=criterion(reading.RESULT_CONSISTENT, "c1"),
            notes=criterion(reading.RESULT_CONSISTENT, "c1"),
        )
        self.assertEqual(analyze(row, PASSING, lines=1).level, levels.NOT_ENOUGH)

    def test_l4_a_gap_in_the_lines_is_malformed(self) -> None:
        row = a_reading(
            line_1=criterion(reading.RESULT_CONSISTENT, "c1"),
            line_3=criterion(reading.RESULT_CONSISTENT, "c1"),
        )
        self.assertEqual(analyze(row, PASSING, lines=3).level, levels.NOT_ENOUGH)

    def test_l4_a_line_the_reading_did_not_answer_is_missing(self) -> None:
        row = a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1"))
        got = analyze(row, PASSING, lines=2)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_READING_MALFORMED, got.reasons)

    def test_l4_a_result_outside_the_three_is_malformed(self) -> None:
        row = a_reading(line_1=criterion("done", "c1"))
        self.assertEqual(analyze(row, PASSING).level, levels.NOT_ENOUGH)

    def test_l5_a_cited_pass_that_aged_after_the_reading_is_medium(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "passed", stale=True)], scan(passed=1))
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_PASS_THEN_WRITE, got.reasons)

    def test_l5_a_cited_pass_a_command_later_changed_is_medium(self) -> None:
        facts = evidence([check("c1", SAVE + 20, "passed", changed=True)], scan(passed=1))
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(got.level, levels.MEDIUM)

    def test_v5_a_cited_pass_before_the_window_does_not_show_a_line(self) -> None:
        facts = evidence([check("c1", SAVE - 50, "passed")], scan(passed=1))
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_LINE_NOT_SHOWN, got.reasons)

    def test_v5_a_cited_pass_with_no_time_does_not_show_a_line(self) -> None:
        facts = evidence([check("c1", None, "passed")], scan(passed=1))
        got = analyze(a_reading(line_1=criterion(reading.RESULT_CONSISTENT, "c1")), facts)
        self.assertEqual(got.level, levels.NOT_ENOUGH)

    def test_l6_a_scan_missing_its_keys_is_too_little(self) -> None:
        facts = evidence(list(PASSING.facts), {"passed": 1})
        got = levels.live_level(facts, intent("Tests pass"))
        self.assertEqual(got.level, levels.NOT_ENOUGH)
        self.assertIn(levels.REASON_SCAN_INCOMPLETE, got.reasons)

    def test_l6_a_listed_failure_the_counts_miss_still_reads_high(self) -> None:
        facts = evidence([check("f1", SAVE + 20, "failed")], scan(passed=1))
        self.assertEqual(levels.live_level(facts, intent("Tests pass")).level, levels.HIGH)

    def test_l6_the_analysis_withholds_on_an_incomplete_scan_too(self) -> None:
        facts = evidence(list(PASSING.facts), {"passed": 1})
        self.assertEqual(analyze(SUPPORTED, facts).level, levels.NOT_ENOUGH)

    def test_l7_is_retired_a_goal_departure_with_no_outcome_line_reads_medium(self) -> None:
        got = analyze(a_reading(goal=criterion(reading.RESULT_DEPARTURE, "m1")), PASSING)
        self.assertEqual(got.level, levels.MEDIUM)
        self.assertIn(levels.REASON_DEPARTURE, got.reasons)
        self.assertNotIn(levels.REASON_NO_OUTCOME_LINE, got.reasons)

    def test_l7_is_retired_a_goal_alone_with_a_fresh_failure_reads_high(self) -> None:
        failing = evidence([check("f1", SAVE + 20, "failed")], scan(failed=1))
        got = analyze(a_reading(goal=criterion(reading.RESULT_CONSISTENT, "f1")), failing)
        self.assertEqual(got.level, levels.HIGH)

    def test_l8_a_file_path_no_longer_widens_to_prose(self) -> None:
        with mock.patch("compass_runtime.levels.os.path.isdir", return_value=True):
            # "change src/retry.py" names src/; a write elsewhere is outside it.
            facts = evidence(
                [wrote("w1", SAVE + 5, "lib/other.py"), check("c1", SAVE + 20, "passed")],
                scan(passed=1, written_paths=1),
            )
            self.assertEqual(
                levels.live_level(facts, intent("Change src/retry.py")).level, levels.HIGH
            )

    def test_l8_a_dotted_folder_keeps_its_boundary(self) -> None:
        facts = evidence(
            [wrote("w1", SAVE + 5, "src/app.py"), check("c1", SAVE + 20, "passed")],
            scan(passed=1, written_paths=1),
        )
        with mock.patch("compass_runtime.levels.os.path.isdir", return_value=True):
            self.assertEqual(
                levels.live_level(facts, intent("Only touch `.github/`")).level, levels.HIGH
            )

    def test_l9_an_absolute_folder_inside_the_cwd_places_relative_writes(self) -> None:
        facts = evidence(
            [wrote("w1", SAVE + 5, "web/a.js"), check("c1", SAVE + 20, "passed")],
            scan(passed=1, written_paths=1),
            cwd="/work/ttt",
        )
        got = levels.live_level(facts, intent("Only edit /work/ttt/web/"))
        self.assertEqual(got.level, levels.NONE_OR_LOW)
        self.assertEqual((got.writes_outside, got.writes_total), (0, 1))


if __name__ == "__main__":
    unittest.main()


class ResultTimeTest(unittest.TestCase):
    """DRC-4702: a check whose call began before the window and whose result
    landed inside it is read as inside the window, by both sources' window
    checks. Change comparisons keep the call time."""

    def test_a_straddling_pass_shows_the_line(self) -> None:
        facts = evidence(
            [check("c1", SAVE - 10, "passed") | {"result_at": SAVE + 5}],
            scan(passed=1),
        )
        level = analyze(SUPPORTED, facts)
        self.assertEqual(levels.NONE_OR_LOW, level.level)
        self.assertIn("c1", level.cites)

    def test_a_straddling_failure_reads_high(self) -> None:
        facts = evidence(
            [check("c1", SAVE - 10, "failed") | {"result_at": SAVE + 5}], scan(failed=1)
        )
        self.assertEqual(levels.HIGH, analyze(SUPPORTED, facts).level)

    def test_a_result_before_the_window_stays_outside_it(self) -> None:
        facts = evidence(
            [check("c1", SAVE - 10, "failed") | {"result_at": SAVE - 5}], scan(failed=1)
        )
        self.assertEqual(levels.NOT_ENOUGH, analyze(SUPPORTED, facts).level)


class CountedCiBacksTheFloorTest(unittest.TestCase):
    """A consistent goal resting on the agent's account reaches the floor on green CI checks that
    count, a pull request merged into the session's branch among them (owner, 2026-10-28)."""

    @staticmethod
    def ci(**over: Any) -> list[dict[str, Any]]:
        from compass_runtime import ci_read  # noqa: PLC0415

        record = {
            **ci_read.blank(
                ci_read.Binding("acme/widgets", 12, ci_read.SOURCE_GOAL),
                "a" * 40,
                False,
                SAVE + 500,
            ),
            "head": "b" * 40,
            "merged_in": True,
            "counts": {"pass": 1, "fail": 0, "pending": 0, "skipping": 0, "cancel": 0},
            "checks": [{"name": "quality-gate", "bucket": "pass", "completed_at": SAVE + 400}],
            **over,
        }
        return ci_read.facts(record, "claude", "s")

    def level(self, ci_facts: list[dict[str, Any]]) -> levels.Level:
        facts = evidence([*PASSING.facts, *ci_facts], PASSING.scan)
        return analyze(a_reading(goal=criterion(reading.RESULT_CONSISTENT, "m1")), facts, lines=0)

    def test_green_counted_checks_back_a_goal_the_model_rested_on_the_agents_account(self) -> None:
        got = self.level(self.ci())
        self.assertEqual(levels.NONE_OR_LOW, got.level)

    def test_checks_that_do_not_count_back_nothing(self) -> None:
        got = self.level(self.ci(merged_in=False))
        self.assertNotEqual(levels.NONE_OR_LOW, got.level)

    def test_a_counted_failure_backs_nothing(self) -> None:
        got = self.level(
            self.ci(
                counts={"pass": 1, "fail": 1, "pending": 0, "skipping": 0, "cancel": 0},
                checks=[
                    {"name": "quality-gate", "bucket": "pass", "completed_at": SAVE + 400},
                    {"name": "unit", "bucket": "fail", "completed_at": SAVE + 400},
                ],
            )
        )
        self.assertNotEqual(levels.NONE_OR_LOW, got.level)
