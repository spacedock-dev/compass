"""Tier 2 CI reads and tier 3 commands: what the producer records, what the resolver and the
levels read of them, and what leaves the machine.

[DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
rules the tiers and [DEC-31](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)
the vendor rule. Every command and path below is synthetic.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, cast

from compass_runtime import levels, project_context, reading, reading_route

from . import test_levels as lv
from . import test_reading as base
from .test_claude_checks import SHORT, ClaudeChecksTestCase


def facts_of(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        project_context._semantic_fact_from_event(dict(row), str(row["kind"]), "tool_report", "")
        for row in entries
    ]


class TheProducerListsEachTier(ClaudeChecksTestCase):
    def commands(self, subject: str = "command") -> list[dict[str, Any]]:
        return [event for event in self.read()[0] if event["subject"] == subject]

    def test_a_command_off_both_lists_is_a_tier_3_fact_apart_from_a_check(self) -> None:
        self.session.bash("make deploy", "done", is_error=False)
        (command,) = self.commands()
        self.assertEqual(
            ("command", 3, "passed"), (command["subject"], command["tier"], command["result"])
        )
        self.assertEqual("make deploy", command["title"])
        self.assertEqual("command_run", command["kind"])
        self.assertEqual([], self.checks())

    def test_a_failed_command_is_a_failure_when_it_ran_alone(self) -> None:
        self.session.bash("make deploy", "boom", is_error=True)
        (command,) = self.commands()
        self.assertEqual("failed", command["result"])

    def test_a_command_that_cannot_fail_is_never_listed(self) -> None:
        for command in ("printf done", "echo ready", "true", ": noop", "exit 0", "export A=1"):
            self.session.bash(command, "", is_error=False)
        self.assertEqual([], self.commands())

    def test_a_command_whose_status_a_later_true_forces_has_no_result(self) -> None:
        self.session.bash("make deploy || true", "", is_error=False)
        self.session.bash("./release.sh; exit 0", "", is_error=False)
        found = self.commands()
        self.assertEqual(2, len(found))
        for command in found:
            with self.subTest(command=command["title"]):
                self.assertEqual("not-recorded", command["result"])
                self.assertTrue(command["cannot_fail"])

    def test_a_read_only_command_is_never_a_command(self) -> None:
        for command in ("ls -la", "git status", "gh pr view 7", "gh run list", "sleep 5"):
            self.session.bash(command, "", is_error=False)
        self.assertEqual([], self.commands())

    def test_a_pass_of_a_closed_list_check_stays_a_check(self) -> None:
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.assertEqual([], self.commands())
        self.assertEqual(1, len(self.checks()))

    def test_gh_pr_checks_counts_by_its_exit_status_and_pending_is_never_a_pass(self) -> None:
        self.session.bash("gh pr checks 12", "all pass", is_error=False)
        self.session.bash("gh pr checks 13", "Exit code 8\npending", is_error=True)
        self.session.bash("gh pr checks 14", "Exit code 1\nfailing", is_error=True)
        by_title = {event["title"]: event for event in self.commands("ci_command")}
        self.assertEqual("passed", by_title["gh pr checks 12"]["result"])
        self.assertEqual("not-recorded", by_title["gh pr checks 13"]["result"])
        self.assertEqual("failed", by_title["gh pr checks 14"]["result"])
        self.assertEqual({2}, {event["tier"] for event in by_title.values()})

    def test_gh_run_view_counts_only_with_exit_status(self) -> None:
        self.session.bash("gh run view 5", "completed failure", is_error=False)
        self.session.bash("gh run view 6 --exit-status", "ok", is_error=False)
        self.assertEqual(
            [("gh run view 6 --exit-status", "passed")],
            [(e["title"], e["result"]) for e in self.commands("ci_command")],
        )

    def test_glab_ci_status_records_no_result(self) -> None:
        self.session.bash("glab ci status", "running", is_error=False)
        self.assertEqual([], self.commands("ci_command"))
        self.assertEqual([], self.commands())

    def test_a_ci_read_never_ages_an_earlier_pass_but_a_command_does(self) -> None:
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.bash("gh pr checks 12", "all pass", is_error=False)
        self.assertFalse(self.only_check()["changed_after"])
        self.session.bash("make deploy", "done", is_error=False)
        self.assertTrue(self.only_check()["changed_after"])

    def test_a_command_pass_after_a_check_ages_it_in_the_live_level(self) -> None:
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.bash("make deploy", "done", is_error=False)
        entries, scan = self.read()
        got = levels.live_level(
            lv.evidence(facts_of(entries), {**lv.scan(), **scan}), lv.intent("Tests pass")
        )
        self.assertIn(levels.REASON_CHANGING_COMMAND, got.reasons)
        self.assertEqual(levels.NOT_ENOUGH, got.level)

    def test_tier_3_never_displaces_another_kind_of_entry_from_the_listing(self) -> None:
        for index in range(15):
            self.session.bash(f"make step{index}", "done", is_error=False)
        for index in range(12):
            self.session.bash(f"pytest tests/test_{index}.py", "1 passed", is_error=False)
        self.session.write(self.file("src/new.py"))
        entries, scan = self.read()
        self.assertEqual(12, len(entries))
        self.assertEqual({"check"}, {e["subject"] for e in entries})
        self.assertEqual(15, scan["commands"])
        self.assertEqual(16, scan["more"])

    def test_the_more_count_names_every_command_the_listing_left_out(self) -> None:
        for index in range(14):
            self.session.bash(f"make step{index}", "done", is_error=False)
        entries, scan = self.read()
        self.assertEqual(12, len(entries))
        self.assertEqual(2, scan["more"])
        self.assertEqual(14, scan["command_passed"])

    def test_a_failed_command_is_listed_before_the_rest_of_its_tier(self) -> None:
        for index in range(13):
            self.session.bash(f"make step{index}", "done", is_error=False)
        self.session.bash("make release", "boom", is_error=True)
        entries, _scan = self.read()
        self.assertIn("make release", [e["title"] for e in entries])

    def test_a_listed_command_takes_no_place_number_and_moves_none(self) -> None:
        self.session.bash("pytest -q", "3 passed", is_error=False)
        before = self.only_check().get("ordinal")
        self.session.bash("make deploy", "done", is_error=False)
        (command,) = self.commands()
        self.assertNotIn("ordinal", command)
        self.assertEqual(before, self.only_check().get("ordinal"))

    def test_the_scan_counts_commands_apart_from_checks(self) -> None:
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.bash("make deploy", "boom", is_error=True)
        self.session.bash("gh pr checks 1", "ok", is_error=False)
        scan = self.read()[1]
        self.assertEqual((1, 0), (scan["passed"], scan["failed"]))
        self.assertEqual(
            (0, 1, 1), (scan["command_passed"], scan["command_failed"], scan["ci_passed"])
        )


class TheResolverReadsATierThreeResult(base.AClaudeCodeReadingProducer):
    def command(self, **overrides: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "fact_id": "cmd-1",
            "subject": "command",
            "tier": 3,
            "result": "passed",
            "result_source": "flag",
            "summary": "make deploy",
            "at": 100.0,
            "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
            "branch": {"harness": "claude", "sid": "s1", "record_id": "call-cmd-1"},
        }
        row.update(overrides)
        return base.check_fact(**row)

    def line(self, facts: list[dict[str, Any]], answer: dict[str, Any]) -> dict[str, Any]:
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            [
                {
                    "n": 1,
                    "at": 50.0,
                    "goal": "The release is deployed",
                    "lines": ["The release is deployed"],
                }
            ],
            facts,
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(answer)),
            tool_output=reading.ToolOutput(destination="Anthropic", label="Claude Code"),
            read_lines=True,
            read_agent_words=True,
        )
        self.assertEqual("", why)
        return cast("dict[str, Any]", cast("Any", assessment)["criteria"]["line_1"])

    def cite(self, fact: dict[str, Any], result: str = "consistent") -> dict[str, Any]:
        facts = [base.WORDS_FACT, fact]
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={})
        n = 1 + next(i for i, row in enumerate(ledger) if row.get("subject") == fact["subject"])
        return self.line(
            facts, {"line_1": {"result": result, "cites": [n], "detail": "The command ran."}}
        )

    def test_a_command_that_can_fail_settles_a_line_consistent_with_its_label(self) -> None:
        row = self.cite(self.command())
        self.assertEqual(reading.RESULT_CONSISTENT, row["result"])
        self.assertEqual(("cmd-1",), tuple(row["cites"]))
        self.assertIn("exited 0; Compass does not know what it checks", self.prompts[0])
        self.assertNotIn("passed, as the tool reported", self.prompts[0])

    def test_a_failed_command_supports_a_departure_and_never_a_consistent(self) -> None:
        fact = self.command(result="failed")
        self.assertEqual(reading.RESULT_DEPARTURE, self.cite(fact, "departure")["result"])
        self.assertNotEqual(reading.RESULT_CONSISTENT, self.cite(fact)["result"])

    def test_an_always_consistent_model_citing_only_a_command_that_cannot_fail_settles_nothing(
        self,
    ) -> None:
        for fact in (
            self.command(summary="echo deployed"),
            self.command(summary="printf done"),
            self.command(summary="make deploy || true"),
            self.command(summary="make deploy; exit 0"),
            self.command(summary="git status"),
            self.command(cannot_fail=True),
        ):
            with self.subTest(summary=fact["summary"], flag=fact.get("cannot_fail")):
                self.assertNotEqual(reading.RESULT_CONSISTENT, self.cite(fact)["result"])

    def test_the_level_counts_a_command_that_can_fail_and_not_one_that_cannot(self) -> None:
        def read(fact: dict[str, Any]) -> levels.Level:
            session = {"harness": "claude", "sid": "s"}
            message = {
                "fact_id": "m1",
                "type": "agent_message",
                "summary": "Synthetic final account",
                "at": lv.SAVE + 20,
                "source_session": session,
                "evidence": {"source": "Claude assistant message", "confidence": "recorded"},
            }
            facts = [{**fact, "at": lv.SAVE + 20, "source_session": session}, message]
            row = lv.a_reading(
                goal=lv.criterion(reading.RESULT_CONSISTENT, "m1"),
                line_1=lv.criterion(reading.RESULT_CONSISTENT, "cmd-1"),
            )
            return lv.analyze(row, lv.evidence(facts, lv.scan(passed=1, written_paths=1)))

        self.assertEqual(levels.NONE_OR_LOW, read(self.command()).level)
        self.assertNotEqual(levels.NONE_OR_LOW, read(self.command(cannot_fail=True)).level)
        self.assertNotEqual(levels.NONE_OR_LOW, read(self.command(summary="echo deployed")).level)

    def test_a_command_row_reads_as_work_and_never_as_a_check_pass(self) -> None:
        (row,) = reading.build_ledger([self.command()], "claude", "s1", tool_output={})
        self.assertTrue(row["work"])
        self.assertEqual("command", row["subject"])
        self.assertNotIn("passed", row["summary"])

    def test_a_command_that_cannot_fail_is_not_work(self) -> None:
        (row,) = reading.build_ledger(
            [self.command(summary="echo done")], "claude", "s1", tool_output={}
        )
        self.assertFalse(row["work"])

    def test_the_prompt_reserves_room_for_everything_before_a_command(self) -> None:
        facts = [base.WORDS_FACT, base.check_fact(fact_id="c0", result="passed"), self.command()]
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={})
        priorities = {
            str(row.get("subject") or row["type"]): reading._priority(row) for row in ledger
        }
        self.assertLess(priorities["check"], priorities["command"])
        self.assertLess(priorities["user_message"], priorities["command"])


class TheVendorRuleDecidesWhatOutputLeaves(ClaudeChecksTestCase):
    def prompt(self, provider: str) -> str:
        self.session.save(self.path)
        entries, _scan = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        press = project_context.claude_check_press(self.config, str(self.path))
        tails = reading_route.tails_for(provider, "claude", press.tails, press.tier3_calls)
        ledger = reading.build_ledger(
            [base.WORDS_FACT, *facts_of(entries)], "claude", SHORT, tool_output=tails
        )
        text, _selection = reading.build_prompt(
            ledger, goal="deploy", lines=("deployed",), max_bytes=16_000
        )
        return text

    def transcript(self) -> None:
        self.session.bash("make deploy", "SYNTHETICTIER3TAIL", is_error=False)
        self.session.bash("pytest -q", "SYNTHETICCHECKTAIL\n3 passed", is_error=False)
        self.session.bash("gh pr checks 1", "SYNTHETICCITAIL", is_error=False)
        self.session.bash(
            "./stage.sh && pytest -q tests/a.py", "SYNTHETICMIXEDTAIL", is_error=False
        )

    def test_the_same_vendor_is_sent_every_commands_tail(self) -> None:
        self.transcript()
        text = self.prompt("claude")
        self.assertIn("SYNTHETICTIER3TAIL", text)
        self.assertIn("SYNTHETICCHECKTAIL", text)

    def test_another_vendor_gets_no_tier_3_output_tail(self) -> None:
        self.transcript()
        text = self.prompt("codex")
        self.assertNotIn("SYNTHETICTIER3TAIL", text)
        self.assertNotIn("SYNTHETICMIXEDTAIL", text)
        # A tier 1 or 2 tail still goes, and the command and its status go without one.
        self.assertIn("SYNTHETICCHECKTAIL", text)
        self.assertIn("SYNTHETICCITAIL", text)
        self.assertIn("make deploy (exited 0; Compass does not know what it checks)", text)

    def test_the_notice_names_the_vendor_rule_in_one_line_either_way(self) -> None:
        same = reading_route._tool_output_sentence("claude", "claude", "Anthropic")
        other = reading_route._tool_output_sentence("codex", "claude", "OpenAI")
        self.assertIn("Other commands go too, with their output.", same)
        self.assertIn("Other commands go with their exit status and no output.", other)


if __name__ == "__main__":
    unittest.main()
