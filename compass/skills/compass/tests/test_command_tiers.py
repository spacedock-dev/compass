"""Tier 2 CI reads and tier 3 commands: what the producer records, what the resolver and the
levels read of them, and what leaves the machine.

[DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
rules the tiers and [DEC-31](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)
the vendor rule. Every command and path below is synthetic.
"""

from __future__ import annotations

import json
import shlex
import time
import unittest
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from compass_runtime import (
    http_api,
    levels,
    observer,
    project_context,
    reading,
    reading_route,
    records,
)

from . import test_levels as lv
from . import test_reading as base
from .test_claude_checks import SHORT, ClaudeChecksTestCase


def facts_of(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        project_context._semantic_fact_from_event(dict(row), str(row["kind"]), "tool_report", "")
        for row in entries
    ]


ALWAYS_ZERO_SPELLINGS = (
    "/bin/true",
    "/usr/bin/true",
    "command true",
    "/bin/echo done",
    "exit 00",
    "exit",
    "nohup true",
    "eval true",
    "return 0",
    "set -e",
    "tee out.log",
)


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

    def test_an_inline_script_is_shown_as_an_opaque_word_on_a_tier_3_line(self) -> None:
        for command, _title in (
            ("python -c 'token=\"FakePass99\"; deploy()'", "python -c …"),
            ("python3 -c 'print(1)'", "python3 -c …"),
            ("python3.12 -Wignore -c 'x=FakePass99'", "python3.12 -Wignore -c …"),
            ("node -e 'send(\"FakePass99\")'", "node -e …"),
            ("node --eval 'send(1)'", "node --eval …"),
            ("ruby -e 'puts \"FakePass99\"'", "ruby -e …"),
            ("perl -e 'print \"FakePass99\"'", "perl -e …"),
            ("perl -pi -e 's/a/FakePass99/' notes.txt", "perl -p…REDACTED -e … notes.txt"),
            ('python -c"print(FakePass99)"', "python -c…"),
        ):
            with self.subTest(command=command):
                self.session.bash(command, "done", is_error=False)
        titles = [event["title"] for event in self.commands()]
        self.assertEqual(
            sorted(
                [
                    "python -c …",
                    "python3 -c …",
                    "python3.12 -Wignore -c …",
                    "node -e …",
                    "node --eval …",
                    "ruby -e …",
                    "perl -e …",
                    "perl -p…REDACTED -e … notes.txt",
                    "python -c…",
                ]
            ),
            sorted(titles),
        )
        self.assertNotIn("FakePass99", " ".join(titles))

    def test_an_interpreter_flag_that_takes_no_value_does_not_expose_the_script(self) -> None:
        for command in (
            "python3 -I -c 'login(\"FakePassNine99xyz\")'",
            "python -i -c 'login(\"FakePassNine99xyz\")'",
            "perl -i -pe 's/a/FakePassNine99xyz/' f",
            "node -i -e 'login(\"FakePassNine99xyz\")'",
            "node --env-file cfg.txt -e 'login(\"FakePassNine99xyz\")'",
        ):
            with self.subTest(command=command):
                line = project_context._command_line(shlex.split(command))
                self.assertNotIn("FakePassNine99xyz", line)
                self.assertIn("…", line)

    def test_a_module_run_keeps_its_own_c_flag_readable(self) -> None:
        self.assertEqual(
            {}, records.inline_script_words(shlex.split("python -m pytest -c conf.ini"))
        )

    def test_an_inline_script_is_hidden_behind_a_wrapper_program(self) -> None:
        for command in (
            "docker exec c python3 -c 'x=\"FakePassNine99xyz\"'",
            "kubectl exec p -- python3 -c 'x=\"FakePassNine99xyz\"'",
            "timeout 10 python3 -c 'x=\"FakePassNine99xyz\"'",
            "uv run --with requests python -c 'x=\"FakePassNine99xyz\"'",
            "uv run --python 3.12 python -c 'x=\"FakePassNine99xyz\"'",
            "nodejs -e 'x=\"FakePassNine99xyz\"'",
        ):
            with self.subTest(command=command):
                line = project_context._command_line(shlex.split(command))
                self.assertNotIn("FakePassNine99xyz", line)
                self.assertIn("…", line)

    def test_a_script_file_or_module_argument_is_not_an_inline_script(self) -> None:
        for command in (
            "python deploy.py -c prod",
            "python -m deploy -c prod",
            "node deploy.js -e prod",
        ):
            self.session.bash(command, "done", is_error=False)
        self.assertEqual(
            sorted(
                [
                    "python deploy.py -c prod",
                    "python -m deploy -c prod",
                    "node deploy.js -e prod",
                ]
            ),
            sorted(event["title"] for event in self.commands()),
        )

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

    def test_gh_run_view_records_only_a_failure_and_only_with_exit_status(self) -> None:
        # `--exit-status` exits 0 for a run still in progress, so a pass says nothing.
        self.session.bash("gh run view 5", "completed failure", is_error=False)
        self.session.bash("gh run view 6 --exit-status", "in_progress", is_error=False)
        self.session.bash("gh run view 7 --exit-status", "failure", is_error=True)
        self.assertEqual(
            {
                "gh run view 6 --exit-status": "not-recorded",
                "gh run view 7 --exit-status": "failed",
            },
            {e["title"]: e["result"] for e in self.commands("ci_command")},
        )

    def test_gh_pr_checks_records_a_failure_only_for_exit_1_with_checks_reported(self) -> None:
        self.session.bash("gh pr checks 20", "Exit code 1\nbuild\tfail", is_error=True)
        self.session.bash("gh pr checks 14", "Exit code 4\nrun gh auth login", is_error=True)
        self.session.bash("gh pr checks 15", "Exit code 1\nno checks reported", is_error=True)
        self.session.bash("gh pr checks 16", "Exit code 2\ncancelled", is_error=True)
        by_title = {e["title"]: e["result"] for e in self.commands("ci_command")}
        self.assertEqual("failed", by_title["gh pr checks 20"])
        for number in (14, 15, 16):
            self.assertEqual("not-recorded", by_title[f"gh pr checks {number}"])

    def test_a_filter_at_the_end_of_a_pipe_speaks_for_nothing_upstream(self) -> None:
        for command in (
            "pytest -q | tee out.log",
            "make test | sed 's/a/b/'",
            "make test | jq .",
            "pnpm test | tee log",
        ):
            self.session.bash(command, "1 failed, 2 passed", is_error=False)
        self.assertNotIn("passed", [c["result"] for c in self.commands()])
        self.assertEqual([], self.passed_checks())

    def test_a_lone_command_and_one_before_a_read_only_filter_read_as_they_did(self) -> None:
        self.session.bash("sed -n 1p notes.txt", "x", is_error=False)
        self.session.bash("./release.sh | tail -5", "done", is_error=False)
        self.assertEqual(
            {"sed -n 1p notes.txt": "passed", "./release.sh": "not-recorded"},
            {c["title"]: c["result"] for c in self.commands()},
        )

    def test_a_command_that_cannot_fail_is_never_listed_under_any_spelling(self) -> None:
        for command in ALWAYS_ZERO_SPELLINGS:
            with self.subTest(command=command):
                self.session.bash(command, "", is_error=False)
        self.assertEqual([], self.commands())

    def test_a_listed_command_always_says_whether_it_can_fail(self) -> None:
        self.session.bash("make deploy", "done", is_error=False)
        self.session.bash("find build -delete", "", is_error=False)
        self.assertEqual([False, False], [c["cannot_fail"] for c in self.commands()])

    def test_a_huge_exit_argument_neither_raises_nor_reads_as_a_failure(self) -> None:
        zeros = "0" * 5000
        self.assertTrue(project_context._always_zero(["exit", zeros]))
        self.assertFalse(project_context._always_zero(["exit", zeros + "1"]))
        reading.cannot_fail({"summary": "exit " + zeros})
        self.assertEqual(
            ("failed", "x"), project_context._ci_outcome("pr_checks", "failed", "x", "Exit code 1")
        )
        project_context._ci_outcome("pr_checks", "failed", "x", "Exit code " + zeros)

    def test_listing_many_segments_stays_linear(self) -> None:
        command = "make x; " * 6000
        started = time.monotonic()
        call = project_context._ShellCall(0.0, "/", {"command": command})
        masked = [call.status_masked(i) for i in range(len(call.parts))]
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertFalse(any(masked[-1:]))

    def test_the_resolvers_never_fails_words_are_the_producers_read_only_words(self) -> None:
        for word in reading._NEVER_FAILS_WORDS:
            with self.subTest(word=word):
                self.assertTrue(
                    project_context._always_zero([word])
                    or project_context._reads_only([], [word, "x"]),
                )
        for text in (*reading._NEVER_FAILS_PAIRS, *reading._NEVER_FAILS_TRIPLES):
            with self.subTest(text=text):
                self.assertTrue(project_context._reads_only([], [*text.split(), "x"]))

    def passed_checks(self) -> list[dict[str, Any]]:
        return [c for c in self.checks() if c["result"] == "passed"]

    def read_levels(self, *, last_user_at: float = 1.0) -> levels.Level:
        entries, scan = self.read()
        return levels.live_level(
            lv.evidence(facts_of(entries), {**lv.scan(), **scan, "last_user_at": last_user_at}),
            lv.intent("Tests pass"),
        )

    def test_a_failed_ci_read_after_the_person_reads_high_like_a_failed_check(self) -> None:
        self.session.write(self.file("src/new.py"))
        self.session.bash("gh pr checks 3", "Exit code 1\nbuild\tfail", is_error=True)
        got = self.read_levels()
        self.assertEqual(levels.HIGH, got.level)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)

    def test_a_pending_ci_read_blocks_the_live_floor_as_a_check_without_a_result_does(self) -> None:
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.write(self.file("src/new.py"))
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.bash("gh pr checks 3", "Exit code 8\npending", is_error=True)
        got = self.read_levels(last_user_at=9e9)
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertIn(levels.REASON_CHECK_NOT_RECORDED, got.reasons)

    def test_a_tier_3_failure_blocks_the_floor_only_until_something_later_passes(self) -> None:
        self.session.write(self.file("src/new.py"))
        self.session.bash("git commit -m wip", "hook rejected", is_error=True)
        self.session.bash("git commit -m fix", "done", is_error=False)
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.assertEqual(levels.NONE_OR_LOW, self.read_levels(last_user_at=9e9).level)

    def test_a_tier_3_failure_with_nothing_passing_after_it_still_blocks_the_floor(self) -> None:
        self.session.write(self.file("src/new.py"))
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.bash("git commit -m wip", "hook rejected", is_error=True)
        got = self.read_levels(last_user_at=9e9)
        self.assertEqual(levels.NOT_ENOUGH, got.level)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)

    def test_a_failed_command_a_listing_names_still_supports_a_departure(self) -> None:
        self.session.bash("git commit -m wip", "hook rejected", is_error=True)
        self.session.bash("git commit -m fix", "done", is_error=False)
        entries, _scan = self.read()
        rows = reading.build_ledger(
            [base.WORDS_FACT, *facts_of(entries)], "claude", SHORT, tool_output={}
        )
        failed = next(r for r in rows if r.get("result") == "failed")
        self.assertTrue(reading.check_supports(failed, reading.RESULT_DEPARTURE, 0.0))

    def test_a_command_that_writes_is_not_withdrawn_as_one_that_cannot_fail(self) -> None:
        self.session.bash("find build -delete", "", is_error=False)
        entries, _scan = self.read()
        rows = reading.build_ledger(facts_of(entries), "claude", SHORT, tool_output={})
        self.assertTrue(any(row["work"] for row in rows))

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
            *(self.command(summary=spelling) for spelling in ALWAYS_ZERO_SPELLINGS),
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

    def test_a_rerun_command_leaves_no_earlier_tail_for_another_vendor(self) -> None:
        self.session.bash("./stage.sh && pytest -q tests/a.py", "SYNTHETICSTAGEOUT\n3 passed")
        self.session.bash("./stage.sh", "SYNTHETICLATERSTAGE")
        self.assertNotIn("SYNTHETICSTAGEOUT", self.prompt("codex"))
        self.assertIn("SYNTHETICSTAGEOUT", self.prompt("claude"))
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual({"toolu_001", "toolu_002"}, set(press.tier3_calls))

    def route_tails(self, provider: str) -> dict[str, str]:
        """The tails the real request handler hands a route of this provider."""
        return dict(self.route_output(provider).tails)

    def route_output(self, provider: str, destination: str = "Synthetic destination") -> Any:
        self.session.save(self.path)
        handler = SimpleNamespace(
            server=SimpleNamespace(
                application=SimpleNamespace(
                    config=self.config, state=SimpleNamespace(), clock=lambda: 1.0
                )
            )
        )
        route = {
            "harness": "claude",
            "provider": provider,
            "destination": destination,
            "words_destination": "Synthetic destination",
            "label": "Claude Code",
            "model": "synthetic-model",
        }
        hooks = SimpleNamespace(
            spawned=None, reserved=None, before_reserve=None, cancelled=None, phase=None
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            arguments = http_api._RequestHandler._reading_arguments(
                cast("Any", handler),
                {"harness": "claude", "sid": SHORT},
                cast("Any", {"revisions": []}),
                cast("Any", route),
                cast("Any", hooks),
            )
        return arguments["tool_output"]

    def test_the_request_handler_hands_the_quote_search_the_press_output_on_both_routes(
        self,
    ) -> None:
        self.session.bash("pytest -q", "SYNTHETICCHECKTAIL\n3 passed")
        self.session.save(self.path)
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertTrue(press.quotable)
        for destination in ("", "Synthetic destination"):
            with self.subTest(destination=destination):
                output = self.route_output("claude", destination)
                self.assertEqual(dict(press.quotable), dict(output.quotable))

    def test_the_request_handler_sends_a_codex_route_no_tier_3_call_tail(self) -> None:
        self.session.bash("make deploy", "SYNTHETICTIER3TAIL", is_error=False)
        self.session.bash("./stage.sh && pytest -q tests/a.py", "SYNTHETICSTAGEOUT\n3 passed")
        self.session.bash("./stage.sh", "SYNTHETICLATERSTAGE")
        self.session.bash("pytest -q", "SYNTHETICCHECKTAIL\n3 passed", is_error=False)
        other = "\n".join(self.route_tails("codex").values())
        same = "\n".join(self.route_tails("claude").values())
        for marker in ("SYNTHETICTIER3TAIL", "SYNTHETICSTAGEOUT", "SYNTHETICLATERSTAGE"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, other)
                self.assertIn(marker, same)
        self.assertIn("SYNTHETICCHECKTAIL", other)

    def test_the_notice_names_the_vendor_rule_in_one_line_either_way(self) -> None:
        same = reading_route._tool_output_sentence("claude", "claude", "Anthropic")
        other = reading_route._tool_output_sentence("codex", "claude", "OpenAI")
        self.assertIn("Other commands go too, with their output.", same)
        self.assertIn("Other commands go with their exit status and no output.", other)


if __name__ == "__main__":
    unittest.main()
