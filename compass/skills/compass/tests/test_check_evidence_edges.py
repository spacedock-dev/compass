"""Synthetic regressions for check provenance, shell cwd and stored citations.

DRC-4733, DRC-4727, DRC-4728 and DRC-4730. No transcript text comes from an
operator's sessions, and the shell examples are parsed rather than executed.
"""

from __future__ import annotations

import os
import shlex
import unittest
from types import SimpleNamespace
from typing import Any, cast

from compass_runtime import http_api, levels, project_context, reading

from .test_claude_checks import ClaudeChecksTestCase, Transcript
from .test_harness_records import PiRecord, exited
from .test_levels import SAVE, a_reading, analyze, check, criterion, evidence, scan


class AnotherCommandCannotSupplyTheChecksOutput(ClaudeChecksTestCase):
    def test_a_print_after_a_swallowed_or_unconditional_check_is_not_its_result(self) -> None:
        for command in ("pytest || echo '5 passed'", "pytest; echo '5 passed'"):
            with self.subTest(command=command):
                self.session = Transcript(self.cwd)
                self.session.bash(command, "5 passed", is_error=False)
                self.assertEqual("not-recorded", self.only_check()["result"])

    def test_an_independent_print_cannot_supply_a_summary_with_no_flag(self) -> None:
        for command in ("echo '5 passed'; pytest", "pytest && echo '5 passed'"):
            with self.subTest(command=command):
                self.session = Transcript(self.cwd)
                self.session.bash(command, "5 passed", is_error=None)
                self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_read_only_pipe_is_a_transform_of_the_check_output(self) -> None:
        self.session.bash("pytest | tail -2 | grep passed", "5 passed", is_error=False)
        self.assertEqual("passed", self.only_check()["result"])

    def test_a_print_after_a_pipe_cannot_supply_the_summary(self) -> None:
        self.session.bash("pytest | tail -2; echo '5 passed'", "5 passed", is_error=False)
        self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_pipe_filter_reading_another_input_cannot_supply_the_summary(self) -> None:
        for command in (
            "pytest | tail report",
            "pytest | head -2 report",
            "pytest | grep passed report",
            "pytest | tail -2 < report",
            "pytest | grep passed <<< '5 passed'",
        ):
            with self.subTest(command=command):
                self.session = Transcript(self.cwd)
                self.session.bash(command, "5 passed", is_error=False)
                self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_cd_that_can_print_its_destination_cannot_supply_a_summary(self) -> None:
        for command in ("cd -; pytest | tail -1", "CDPATH=/elsewhere cd sub; pytest | tail -1"):
            with self.subTest(command=command):
                self.session = Transcript(self.cwd)
                self.session.bash(command, "5 passed", is_error=False)
                self.assertEqual("not-recorded", self.only_check()["result"])

    def test_a_clear_and_chain_flag_still_establishes_a_pass(self) -> None:
        self.session.bash("pytest && echo done", "done", is_error=False)
        fact = self.only_check()
        self.assertEqual(("passed", "flag"), (fact["result"], fact["result_source"]))


class PisCheckCountsNeedAttributedOutput(PiRecord):
    def test_an_independent_print_never_establishes_a_check_pass(self) -> None:
        for command in ("pytest || echo '5 passed'", "pytest; echo '5 passed'"):
            with self.subTest(command=command):
                self.records.clear()
                self.bash(command, text="5 passed", is_error=False)
                fact = self.one()
                self.assertEqual("not-recorded", fact["result"])
                self.assertNotIn("checks_passed", fact)

    def test_a_negated_check_is_never_a_pass(self) -> None:
        for command in (
            "! pytest -q",
            "if ! pytest -q; then echo broke; fi",
            "ls && ! pytest -q",
            "! (cd . && pytest -q)",
            "! { cd . && pytest -q; }",
            "! if true; then pytest -q; fi",
        ):
            for text, is_error in (
                ("4 passed in 1s", False),
                ("", False),
                (exited("1 failed in 1s", 1), True),
            ):
                with self.subTest(command=command, text=text, is_error=is_error):
                    self.records.clear()
                    self.bash(command, text=text, is_error=is_error)
                    fact = self.one()
                    self.assertEqual("not-recorded", fact["result"])
                    self.assertNotIn("checks_passed", fact)

    def test_a_trusted_flag_does_not_attribute_another_prints_count(self) -> None:
        for command in ("pytest && echo '5 passed'", "echo '5 passed'; pytest"):
            with self.subTest(command=command):
                self.records.clear()
                self.bash(command, text="5 passed", is_error=False)
                fact = self.one()
                self.assertEqual(("passed", "flag"), (fact["result"], fact["result_source"]))
                self.assertNotIn("checks_passed", fact)

    def test_a_filter_can_preserve_the_check_count(self) -> None:
        self.bash("pytest | tail -1", text="5 passed", is_error=False)
        self.assertEqual(5, self.one()["checks_passed"])


class ChecksUseTheirShellsDirectory(ClaudeChecksTestCase):
    @staticmethod
    def directories(command: str) -> list[str]:
        call = project_context._ShellCall(10.0, "/w", {"command": command})
        return [os.path.normpath(call.directories[i]) for i in call.checks]

    def test_braces_run_in_the_current_shell_and_do_not_restore_its_cd(self) -> None:
        actual = self.directories("{ cd sub; pytest; }; pytest")
        self.assertEqual([os.path.normpath("/w/sub")] * 2, actual)

    def test_a_cd_after_then_is_followed_inside_the_arm(self) -> None:
        actual = self.directories("if x; then cd sub; pytest; fi")
        self.assertEqual([os.path.normpath("/w/sub")], actual)

    def test_a_conditional_cd_leaves_a_later_relative_redirect_unplaced(self) -> None:
        self.session.bash("if x; then cd sub; fi; pytest > ../conditional", "", is_error=False)
        rows, counts = self.read()
        self.assertFalse(any(row["subject"] == "write" for row in rows))
        self.assertEqual(1, counts["outside_paths"])

    def test_an_unknown_directory_cannot_supersede_a_known_directorys_failure(self) -> None:
        for command in (
            "if x; then cd sub; fi; pytest",
            "CDPATH=/elsewhere cd sub; pytest",
        ):
            with self.subTest(command=command):
                self.session = Transcript(self.cwd)
                self.session.prompt("Continue")
                self.session.bash("cd sub && pytest", "1 failed", is_error=True)
                self.session.bash(command, "", is_error=False)
                rows, counts = self.read()
                self.assertEqual(1, counts["failed"])
                self.assertTrue(any(row.get("result") == "failed" for row in rows))
                self.assertEqual(
                    levels.HIGH,
                    levels.live_level(
                        evidence(
                            [
                                project_context._semantic_fact_from_event(
                                    row, row["kind"], "tool_report", ""
                                )
                                for row in rows
                            ],
                            counts,
                        ),
                        levels.Intent(True, "Finish the work", ("Checks pass",)),
                    ).level,
                )

    def test_a_conditional_subshell_close_restores_the_parent_check_identity(self) -> None:
        for command in (
            "(if x; then cd sub; fi); pytest",
            "time (if x; then cd sub; fi); pytest",
            "( (if x; then cd sub; fi) ); pytest",
        ):
            with self.subTest(command=command):
                self.session = Transcript(self.cwd)
                self.session.bash("pytest", "1 failed", is_error=True)
                self.session.bash(command, "", is_error=False)
                rows, counts = self.read()
                checks = [row for row in rows if row["subject"] == "check"]
                self.assertEqual(0, counts["failed"])
                self.assertEqual(1, counts["passed"])
                self.assertEqual(1, len(checks))
                self.assertTrue(checks[0]["earlier_failed"])
                self.assertEqual(
                    levels.NOT_ENOUGH,
                    levels.live_level(
                        evidence(
                            [
                                project_context._semantic_fact_from_event(
                                    row, row["kind"], "tool_report", ""
                                )
                                for row in rows
                            ],
                            counts,
                        ),
                        levels.Intent(True, "Finish the work", ("Checks pass",)),
                    ).level,
                )

    def test_syntax_only_close_permutations_place_the_parent_directory(self) -> None:
        for command in (
            "(if x; then cd sub; fi); pytest",
            "(if x; then cd sub; fi;); pytest",
            "({ if x; then cd sub; fi; }); pytest",
            "(case a in a) if x; then cd sub; fi;; esac); pytest",
            "(case a in a) cd sub;; esac); pytest",
            "( (if x; then cd sub; fi) ); pytest",
        ):
            with self.subTest(command=command):
                call = project_context._ShellCall(10.0, "/w", {"command": command})
                self.assertEqual([os.path.normpath("/w")], self.directories(command))
                self.assertTrue(call.placed[call.checks[-1]])

    def test_a_relative_redirect_after_a_conditional_subshell_is_placed(self) -> None:
        self.session.bash("(if x; then cd sub; fi); pytest > result", "", is_error=False)
        rows, counts = self.read()
        self.assertEqual(["result"], [row["title"] for row in rows if row["subject"] == "write"])
        self.assertEqual(0, counts["outside_paths"])

    def test_a_case_pattern_does_not_close_its_enclosing_subshell(self) -> None:
        self.session.bash(
            "(case a in a) true;; esac; cd sub); pytest > ../outside", "", is_error=False
        )
        rows, counts = self.read()
        self.assertEqual(
            [os.path.normpath("/w")], self.directories("(case a in a) true;; esac; cd sub); pytest")
        )
        self.assertFalse(any(row["subject"] == "write" for row in rows))
        self.assertEqual(1, counts["outside_paths"])

    def test_nested_case_arms_leave_real_subshells_balanced(self) -> None:
        command = "(case a in a) (cd inner); case b in b) true;; esac;; esac; cd sub); pytest"
        self.assertEqual([os.path.normpath("/w")], self.directories(command))

    def test_case_arms_do_not_place_a_later_relative_redirect(self) -> None:
        self.session.bash(
            "case a in a|b) cd sub;; *) cd other;; esac; pytest > result", "", is_error=False
        )
        rows, counts = self.read()
        self.assertFalse(any(row["subject"] == "write" for row in rows))
        self.assertEqual(1, counts["outside_paths"])

    def test_time_opens_a_subshell_and_its_redirect_in_the_outer_directory(self) -> None:
        self.session.bash("time (cd sub && pytest) > ../outside", "", is_error=False)
        rows, counts = self.read()
        self.assertFalse(any(row["subject"] == "write" for row in rows))
        self.assertEqual(1, counts["outside_paths"])
        self.assertEqual(
            [os.path.normpath("/w/sub"), os.path.normpath("/w")],
            self.directories("time (cd sub && pytest); pytest"),
        )

    def test_pipeline_and_background_cds_do_not_change_the_parent_directory(self) -> None:
        for command in ("cd sub | cat; pytest", "cd sub & pytest", "cd sub && true & pytest"):
            with self.subTest(command=command):
                self.assertEqual([os.path.normpath("/w")], self.directories(command))

    def test_cdpath_makes_a_relative_cd_unplaceable(self) -> None:
        for prefix in ("CDPATH=/elsewhere", "CDPATH=/elsewhere;", "export CDPATH=/elsewhere;"):
            with self.subTest(prefix=prefix):
                self.session = Transcript(self.cwd)
                self.session.bash(f"{prefix} cd sub && pytest > ../outside", "", is_error=False)
                rows, counts = self.read()
                self.assertFalse(any(row["subject"] == "write" for row in rows))
                self.assertEqual(1, counts["outside_paths"])

    def test_a_literal_absolute_cd_recovers_placement_after_cdpath(self) -> None:
        self.session.bash(
            f"CDPATH=/elsewhere cd sub; cd {shlex.quote(str(self.cwd))}; pytest > result",
            "",
            is_error=False,
        )
        rows, counts = self.read()
        self.assertEqual(["result"], [r["title"] for r in rows if r["subject"] == "write"])
        self.assertEqual(0, counts["outside_paths"])


def _sourced(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        **fact,
        "source_session": {"harness": "claude", "sid": "s"},
        "evidence": {"source": "Synthetic transcript record", "confidence": "recorded"},
    }


class AStoredDepartureNeedsCurrentCitableEvidence(unittest.TestCase):
    def test_a_missing_or_pre_window_citation_cannot_supply_a_departure(self) -> None:
        old = _sourced(
            {
                "fact_id": "old",
                "type": "user_message",
                "summary": "change direction",
                "at": SAVE - 10,
            }
        )
        for facts in ([], [old]):
            with self.subTest(facts=facts):
                row = a_reading(
                    goal=criterion(reading.RESULT_DEPARTURE, "old"),
                    line_1=criterion(reading.RESULT_UNVERIFIABLE),
                )
                result = analyze(row, evidence(facts, scan()))
                self.assertEqual(levels.NOT_ENOUGH, result.level)
                self.assertNotIn(levels.REASON_DEPARTURE, result.reasons)
                self.assertNotIn("old", result.cites)

    def test_a_source_or_summary_the_resolver_refuses_cannot_supply_a_departure(self) -> None:
        current = _sourced(
            {"fact_id": "m", "type": "user_message", "summary": "change direction", "at": SAVE + 10}
        )
        variants: tuple[dict[str, Any], ...] = ({"evidence": {}}, {"summary": ""}, {"type": ""})
        for over in variants:
            with self.subTest(over=over):
                row = a_reading(
                    goal=criterion(reading.RESULT_DEPARTURE, "m"),
                    line_1=criterion(reading.RESULT_UNVERIFIABLE),
                )
                result = analyze(row, evidence([{**current, **over}], scan()))
                self.assertNotIn(levels.REASON_DEPARTURE, result.reasons)

    def test_a_current_persons_direction_can_still_supply_a_goal_departure(self) -> None:
        fact = _sourced(
            {"fact_id": "m", "type": "user_message", "summary": "change direction", "at": SAVE + 10}
        )
        row = a_reading(
            goal=criterion(reading.RESULT_DEPARTURE, "m"),
            line_1=criterion(reading.RESULT_UNVERIFIABLE),
        )
        self.assertEqual(levels.MEDIUM, analyze(row, evidence([fact], scan())).level)

    def test_a_board_paraphrase_cannot_supply_a_goal_departure(self) -> None:
        fact = _sourced(
            {
                "fact_id": "m",
                "type": "observer_snapshot",
                "summary": "change direction",
                "at": SAVE + 10,
            }
        )
        row = a_reading(
            goal=criterion(reading.RESULT_DEPARTURE, "m"),
            line_1=criterion(reading.RESULT_UNVERIFIABLE),
        )
        self.assertEqual(levels.NOT_ENOUGH, analyze(row, evidence([fact], scan())).level)

    def test_a_passing_check_does_not_support_an_outcome_departure(self) -> None:
        fact = _sourced(check("c", SAVE + 10, "passed"))
        row = a_reading(line_1=criterion(reading.RESULT_DEPARTURE, "c"))
        self.assertEqual(levels.NOT_ENOUGH, analyze(row, evidence([fact], scan(passed=1))).level)

    def test_the_production_level_reads_a_current_noncheck_goal_citation(self) -> None:
        fact = _sourced(
            {"fact_id": "m", "type": "user_message", "summary": "change direction", "at": SAVE + 10}
        )
        assessment = a_reading(
            goal=criterion(reading.RESULT_DEPARTURE, "m"),
            line_1=criterion(reading.RESULT_UNVERIFIABLE),
        )
        assessment["revision_read"] = 1
        entry = {"assessment": assessment, "revisions": [{"n": 1, "lines": ["outcome"]}]}
        context = {
            "semantic": {"facts": [fact]},
            "sources": {"work": {"tool_reports": [{**scan(), "harness": "claude", "sid": "s"}]}},
        }
        result = http_api._analysis_levels(
            SimpleNamespace(clock=lambda: SAVE + 50),
            context,
            {"harness": "claude", "sid": "s"},
            cast("Any", entry),
            None,
        )
        self.assertEqual(levels.MEDIUM, result[0]["level"])
