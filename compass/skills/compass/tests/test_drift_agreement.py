"""A reader gets one evidence boundary across the drift level and correction."""

from __future__ import annotations

import time
import unittest
from typing import Any
from unittest import mock

from compass_runtime import correction, levels, reading

from . import test_claims_and_adopted_goal as claims
from . import test_claude_checks as checks
from . import test_levels as tier


class AnUnshownClaimAsksForEvidence(unittest.TestCase):
    def test_a_claim_not_shown_blocks_reassurance_without_raising_medium(self) -> None:
        stored = claims._stored(reading.RESULT_UNSUPPORTED, ["a1"])
        stored["criteria"]["goal"] = {"result": reading.RESULT_CONSISTENT, "cites": ["a1"]}
        stored["criteria"]["line_1"] = {"result": reading.RESULT_CONSISTENT, "cites": ["c1"]}
        evidence = levels.Evidence(
            (claims.SAID, claims.PASSED), {**dict.fromkeys(levels.SCAN_KEYS, 0), "passed": 1}, 0
        )
        result = levels.analysis_level(stored, evidence, outcome_lines=1)
        self.assertEqual(levels.NOT_ENOUGH, result.level)
        self.assertIn(levels.REASON_CLAIM_NOT_SHOWN, result.reasons)

    def test_the_correction_asks_for_evidence_instead_of_asserting_a_missing_result(self) -> None:
        text = claims.SteerBackSaysWhatTheRecordDoesNotShowTest().compose(
            reading.RESULT_UNSUPPORTED, ["a1"], [claims.SAID]
        )
        self.assertIn("Can you show evidence", text)
        self.assertNotIn("the record does not show it", text)

    def test_a_short_title_or_bare_url_is_never_quoted_as_the_claim(self) -> None:
        for title in ("All done", "https://example.com/results"):
            with self.subTest(title=title):
                fact = {**claims.SAID, "summary": title}
                text = claims.SteerBackSaysWhatTheRecordDoesNotShowTest().compose(
                    reading.RESULT_UNSUPPORTED, ["a1"], [fact]
                )
                self.assertNotIn('"' + title + '"', text)
                self.assertIn("show evidence", text)


class AFailureBelongsToThePersonsLastTurn(unittest.TestCase):
    def facts(self, failed_at: float, *, writes: bool = False) -> levels.Evidence:
        facts = [
            tier.check("failed", failed_at, "failed"),
            tier.check("passed", tier.SAVE + 5, "passed"),
        ]
        if writes:
            facts.append(tier.wrote("write", failed_at + 1, "src/a.py"))
        return tier.evidence(facts, tier.scan(failed=1, passed=1, last_user_at=tier.SAVE))

    def test_an_older_failure_blocks_none_or_low_but_raises_neither_level(self) -> None:
        facts = self.facts(tier.SAVE - 5)
        for result in (
            levels.live_level(facts, tier.intent("Tests pass")),
            tier.analyze(tier.SUPPORTED, facts),
        ):
            self.assertEqual(levels.NOT_ENOUGH, result.level)
            self.assertIn(levels.REASON_FAILED_CHECK, result.reasons)

    def test_an_older_listed_failure_keeps_its_citation(self) -> None:
        got = levels.live_level(self.facts(tier.SAVE - 5), tier.intent("Tests pass"))
        self.assertIn("failed", got.cites)

    def test_a_failure_after_the_last_message_is_high_on_both_sources(self) -> None:
        facts = self.facts(tier.SAVE + 10)
        for result in (
            levels.live_level(facts, tier.intent("Tests pass")),
            tier.analyze(tier.SUPPORTED, facts),
        ):
            self.assertEqual(levels.HIGH, result.level)
            self.assertIn("failed", result.cites)

    def test_writes_after_that_failure_limit_it_to_medium(self) -> None:
        facts = self.facts(tier.SAVE + 10, writes=True)
        for result in (
            levels.live_level(facts, tier.intent("Tests pass")),
            tier.analyze(tier.SUPPORTED, facts),
        ):
            self.assertEqual(levels.MEDIUM, result.level)

    def test_an_unplaced_failure_cannot_raise_high_without_a_citation(self) -> None:
        facts = tier.evidence(
            [tier.check("passed", tier.SAVE + 5, "passed")],
            tier.scan(failed=1, passed=1, last_user_at=tier.SAVE),
        )
        for result in (
            levels.live_level(facts, tier.intent("Tests pass")),
            tier.analyze(tier.SUPPORTED, facts),
        ):
            self.assertEqual(levels.NOT_ENOUGH, result.level)

    def test_a_failure_with_unknown_time_cannot_raise_high(self) -> None:
        facts = tier.evidence(
            [tier.check("failed", None, "failed")], tier.scan(failed=1, last_user_at=tier.SAVE)
        )
        self.assertEqual(
            levels.NOT_ENOUGH, levels.live_level(facts, tier.intent("Tests pass")).level
        )

    def test_no_outcome_line_no_longer_withholds_the_analysis_level_from_a_fresh_failure(
        self,
    ) -> None:
        goal_only = tier.a_reading(goal=tier.criterion(reading.RESULT_CONSISTENT, "m1"))
        got = levels.analysis_level(goal_only, self.facts(tier.SAVE + 10), outcome_lines=0)
        self.assertEqual(levels.HIGH, got.level)
        self.assertNotIn(levels.REASON_NO_OUTCOME_LINE, got.reasons)


class AFolderSignalNamesARecordedPlace(unittest.TestCase):
    def test_a_branch_shaped_word_without_a_directory_or_write_is_not_weighed(self) -> None:
        facts = tier.evidence(
            [tier.wrote("w", tier.SAVE + 1, "src/a.py")], tier.scan(written_paths=1)
        )
        got = levels.live_level(facts, tier.intent("Review feat/my-branch and web/ PR"))
        self.assertIsNone(got.writes_total)
        self.assertIn(levels.REASON_NO_FOLDER, got.reasons)

    def test_unknown_or_relative_session_cwd_cannot_borrow_a_daemon_folder(self) -> None:
        for cwd in ("", "relative"):
            with (
                self.subTest(cwd=cwd),
                mock.patch("compass_runtime.levels.os.path.isdir", return_value=True),
            ):
                facts = levels.Evidence(
                    (tier.wrote("w", tier.SAVE + 1, "outside/a.py"),),
                    tier.scan(written_paths=1),
                    0,
                    cwd,
                )
                got = levels.live_level(facts, tier.intent("Only touch scripts/"))
                self.assertIsNone(got.writes_total)

    def test_a_folder_with_a_recorded_write_can_be_weighed_without_disk_access(self) -> None:
        facts = tier.evidence(
            [
                tier.wrote("w", tier.SAVE + 1, "src/a.py"),
                tier.wrote("x", tier.SAVE + 2, "other/a.py"),
            ],
            tier.scan(written_paths=2),
        )
        got = levels.live_level(facts, tier.intent("Only touch src/"))
        self.assertEqual((1, 2), (got.writes_outside, got.writes_total))


class ACorrectionNamesTheCurrentGap(unittest.TestCase):
    def compose(self, facts: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        row = {
            **claims.SID,
            "annotation_goal": "Ship the retry",
            "annotation_revision": 1,
            "annotation_window_start": 50,
            "annotation_settled_through": 120,
            **extra,
        }
        return correction.compose(
            row, facts, floor=50, lines_judged=True, clock=lambda at: f"T{int(at)}"
        )

    def test_a_later_direction_alone_never_offers_a_correction(self) -> None:
        result = self.compose([claims._person("p2", 120, "Pause the retry")])
        self.assertEqual({"ok": False, "reason": "nothing"}, result)

    def test_a_settled_direction_is_absent_from_a_correction_for_a_claim(self) -> None:
        result = self.compose(
            [claims._person("p2", 120, "Pause the retry"), claims.SAID],
            annotation_assessment={
                "revision_read": 1,
                "window_start": 50,
                "read_at": 500,
                "criteria": {"claims": {"result": reading.RESULT_UNSUPPORTED, "cites": ["a1"]}},
            },
        )
        text = "".join(p if isinstance(p, str) else "{entry}" for p in result["parts"])
        self.assertNotIn("later direction", text)
        self.assertIn("show evidence", text)

    def test_an_old_failure_alone_offers_nothing_after_the_person_answers(self) -> None:
        result = self.compose(
            [claims._check("f", 95, "failed"), claims._person("p2", 120, "Continue")]
        )
        self.assertEqual({"ok": False, "reason": "nothing"}, result)

    def test_a_fresh_failure_keeps_a_correction_available(self) -> None:
        result = self.compose(
            [claims._person("p2", 60, "Continue"), claims._check("f", 95, "failed")]
        )
        self.assertTrue(result["ok"])

    def test_a_goal_departure_is_timed_before_unshown_outcomes(self) -> None:
        result = self.compose(
            [claims.SAID],
            annotation_line_1="The retry backs off",
            annotation_assessment={
                "revision_read": 1,
                "window_start": 50,
                "read_at": 500,
                "criteria": {"goal": {"result": reading.RESULT_DEPARTURE, "cites": ["a1"]}},
            },
        )
        text = "".join(p if isinstance(p, str) else "{entry}" for p in result["parts"])
        self.assertIn("departed from my goal at T90", text)
        self.assertLess(text.index("departed"), text.index("can you show evidence"))

    def test_an_older_correction_clock_includes_its_date(self) -> None:
        today = time.struct_time((2026, 10, 5, 12, 0, 0, 0, 278, -1))
        older = time.struct_time((2026, 10, 4, 9, 15, 0, 6, 277, -1))
        with mock.patch("compass_runtime.correction.time.localtime", side_effect=[older, today]):
            self.assertEqual("2026-10-04 09:15", correction.clock_text(1))
        with mock.patch("compass_runtime.correction.time.localtime", side_effect=[today, today]):
            self.assertEqual("12:00", correction.clock_text(1))

    def test_an_unconfirmed_consistent_line_names_the_sessions_account(self) -> None:
        result = self.compose(
            [claims.SAID],
            annotation_line_1="The retry backs off",
            annotation_assessment={
                "revision_read": 1,
                "window_start": 50,
                "read_at": 500,
                "criteria": {
                    "goal": {"result": reading.RESULT_DEPARTURE, "cites": ["a1"]},
                    "line_1": {"result": reading.RESULT_CONSISTENT, "cites": ["a1"]},
                },
            },
        )
        text = "".join(p if isinstance(p, str) else "{entry}" for p in result["parts"])
        self.assertIn("the session says this is done; not confirmed by a tool", text)
        self.assertNotIn("nothing recorded shows this yet", text)


class ABroaderPassingRunRetiresTheCoveredFailure(checks.ClaudeChecksTestCase):
    def test_a_module_pass_supersedes_a_failed_unittest_method(self) -> None:
        self.session.bash("python3 -m unittest tests.test_retry.Retry.test_backoff", is_error=True)
        self.session.bash("python3 -m unittest tests.test_retry")
        found = self.checks()
        self.assertEqual(["passed"], [row["result"] for row in found])
        self.assertTrue(found[0]["earlier_failed"])

    def test_a_pytest_file_pass_supersedes_its_failed_test(self) -> None:
        self.session.bash("python3 -m pytest tests/test_retry.py::test_backoff", is_error=True)
        self.session.bash("python3 -m pytest tests/test_retry.py")
        self.assertEqual(["passed"], [row["result"] for row in self.checks()])

    def test_a_pass_cannot_retire_a_failure_outside_its_proven_scope(self) -> None:
        for failed, passed in (
            (
                "python3 -m unittest tests.test_retry.Bad.test_backoff",
                "python3 -m unittest tests.test_retry.Good",
            ),
            (
                "python3 -m pytest tests/test_retry.py::test_backoff",
                "python3 -m pytest tests/test_retry.py -k happy",
            ),
            ("python3 -m pytest tests/test_retry.py", "python3 -m unittest tests.test_retry"),
            (
                "python3 -m unittest tests.test_retry_more.Retry.test_backoff",
                "python3 -m unittest tests.test_retry",
            ),
        ):
            with self.subTest(failed=failed, passed=passed):
                self.session = checks.Transcript(self.cwd)
                self.session.prompt("Continue")
                self.session.bash(failed, is_error=True)
                self.session.bash(passed)
                self.assertEqual({"failed", "passed"}, {row["result"] for row in self.checks()})

    def test_the_same_scope_in_another_directory_cannot_retire_the_failure(self) -> None:
        self.session.bash("python3 -m unittest tests.test_retry.Retry.test_backoff", is_error=True)
        self.session.bash("cd elsewhere && python3 -m unittest tests.test_retry")
        self.assertEqual({"failed", "passed"}, {row["result"] for row in self.checks()})

    def test_a_different_explicit_interpreter_or_environment_cannot_cover_the_failure(self) -> None:
        for first, second in (
            ("/venv/a/python3", "/venv/b/python3"),
            ("MODE=old python3", "MODE=new python3"),
        ):
            with self.subTest(first=first):
                self.session = checks.Transcript(self.cwd)
                self.session.prompt("Continue")
                self.session.bash(
                    first + " -m unittest tests.test_retry.Retry.test_backoff", is_error=True
                )
                self.session.bash(second + " -m unittest tests.test_retry")
                self.assertEqual({"failed", "passed"}, {row["result"] for row in self.checks()})

    def test_a_later_failure_is_not_hidden_by_an_earlier_broader_pass(self) -> None:
        self.session.bash("python3 -m unittest tests.test_retry")
        self.session.bash("python3 -m unittest tests.test_retry.Retry.test_backoff", is_error=True)
        self.assertEqual({"failed", "passed"}, {row["result"] for row in self.checks()})


class TheCorrectionComposerHoldsItsLimits(unittest.TestCase):
    def test_a_marked_reading_cannot_offer_a_correction(self) -> None:
        stored = {
            "revision_read": 1,
            "window_start": 50,
            "read_at": 500,
            "criteria": {"goal": {"result": reading.RESULT_DEPARTURE, "cites": ["a1"]}},
        }
        row = {
            **claims.SID,
            "annotation_goal": "Ship the retry",
            "annotation_revision": 1,
            "annotation_assessment": stored,
            "annotation_not_accurate": True,
        }
        self.assertEqual(
            {"ok": False, "reason": "nothing"},
            correction.compose(row, [claims.SAID], floor=50, lines_judged=True),
        )

    def test_an_adopted_goal_cites_its_source_or_shows_the_clip(self) -> None:
        row = {
            **claims.SID,
            "annotation_goal": "Ship the retry",
            "annotation_goal_source": "latest-prompt",
            "annotation_goal_source_at": 60,
            "annotation_window_start": 50,
        }
        person = claims._person("goal-source", 60, "Ship the retry with safe backoff")
        failed = claims._check("f", 95, "failed")
        found = correction.compose(row, [person, failed], floor=50, lines_judged=True)
        self.assertIn({"entry": "goal-source"}, found["parts"])
        missing = correction.compose(
            row, [claims._person("p0", 50, "Continue"), failed], floor=50, lines_judged=True
        )
        self.assertIn("Ship the retry…", "".join(p for p in missing["parts"] if isinstance(p, str)))
