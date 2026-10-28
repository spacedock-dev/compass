"""Tier 2 CI reads and tier 3 commands: what the producer records, what the resolver and the
levels read of them, and what leaves the machine.

[DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
rules the tiers and [DEC-31](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)
the vendor rule. Every command and path below is synthetic.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

from compass_runtime import (
    ci_read,
    git_status,
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
from .test_claude_checks import BOUND_GOAL, REMOTE, SHORT, ClaudeChecksTestCase

if TYPE_CHECKING:
    from pathlib import Path


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

    def test_a_failing_run_keeps_its_failure_whatever_a_line_among_its_check_rows_says(
        self,
    ) -> None:
        rows = "build\tfail\t1m2s\thttps://example.test/run/1"
        self.session.bash(
            "gh pr checks 9",
            f"Exit code 1\nretrying (HTTP 502)\n{rows}",
            is_error=True,
        )
        self.session.bash(
            "gh pr checks 10",
            f"Exit code 1\nci: authentication step\n{rows}\nHTTP 500 in the log (HTTP 500)",
            is_error=True,
        )
        self.session.bash(
            "gh pr checks 11",
            "Exit code 1\nauthentication\tfail\t3s\thttps://example.test/run/2",
            is_error=True,
        )
        by_title = {e["title"]: e["result"] for e in self.commands("ci_command")}
        for number in (9, 10, 11):
            self.assertEqual("failed", by_title[f"gh pr checks {number}"], number)

    def test_a_whole_output_that_is_one_gh_error_records_no_failure(self) -> None:
        errors = {
            24: "HTTP 404: Not Found (https://api.github.com/repos/acme/widgets/pulls/24)",
            25: "GraphQL: Could not resolve to a PullRequest with the number of 25. (repository.pullRequest)",
            26: "failed to run: error connecting to api.github.com (HTTP 502)",
            27: "To get started with GitHub CLI, please run:  gh auth login",
            28: "no checks reported on the 'fix/widget-guard' branch",
        }
        for number, message in errors.items():
            self.session.bash(f"gh pr checks {number}", f"Exit code 1\n{message}", is_error=True)
        by_title = {e["title"]: e["result"] for e in self.commands("ci_command")}
        for number in errors:
            self.assertEqual("not-recorded", by_title[f"gh pr checks {number}"], number)

    def test_the_stages_before_the_last_of_a_pipe_record_no_result(self) -> None:
        for command in (
            "pytest -q | tee out.log",
            "make test | sed 's/a/b/'",
            "make test | jq .",
            "pnpm test | tee log",
        ):
            self.session.bash(command, "1 failed, 2 passed", is_error=False)
        # The upstream program is never read as passing. A listed last stage speaks for itself,
        # as a check at the end of a pipe does: the call's status is that stage's own.
        self.assertNotIn(
            "passed", [c["result"] for c in self.commands() if c["title"] == "make test"]
        )
        self.assertEqual([], self.passed_checks())
        self.assertEqual("passed", {c["title"]: c["result"] for c in self.commands()}["sed s/a/b/"])

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


class ACiPollCountsOnlyWhenItReadsTheSessionsOwnPullRequest(ClaudeChecksTestCase):
    """A recorded `gh pr checks` or `gh run view` is a CI result only for this session's own pull
    request or repository. Every repository, number and branch below is synthetic.
    """

    def polls(self) -> dict[str, dict[str, Any]]:
        return {e["title"]: e for e in self.read()[0] if e["subject"] in ("command", "ci_command")}

    def assert_unbound(self, poll: dict[str, Any]) -> None:
        self.assertEqual(
            ("command", 3, True, "ci_poll_unbound"),
            (poll["subject"], poll["tier"], poll["cannot_fail"], poll["result_reason"]),
        )

    def test_a_poll_of_another_repositorys_pull_request_does_not_count(self) -> None:
        self.session.bash("gh pr checks 99 --repo other/old", "all pass", is_error=False)
        (poll,) = self.polls().values()
        self.assert_unbound(poll)
        # Its exit status stays on the row; only the count and the verdict are withdrawn.
        self.assertEqual("passed", poll["result"])
        _entries, scan = self.read()
        self.assertEqual(
            (0, 0, 0, 0),
            (scan["ci_passed"], scan["ci_failed"], scan["command_passed"], scan["command_failed"]),
        )

    def test_a_failed_poll_of_another_pull_request_blocks_no_level(self) -> None:
        self.session.bash("gh pr checks 99 -R other/old", "Exit code 1\nbuild\tfail", is_error=True)
        entries, scan = self.read()
        self.assertEqual(0, scan["command_failed"] + scan["ci_failed"])
        facts = facts_of(entries)
        self.assertEqual(
            [],
            [f for f in facts if f.get("subject") == "ci_command" and not reading.cannot_fail(f)],
        )

    def test_a_poll_of_a_pull_request_the_goal_names_counts(self) -> None:
        self.goal_texts = ("Merge https://github.com/acme/widgets/pull/42 once it is green.",)
        self.session.bash("gh pr checks 42", "all pass", is_error=False)
        (poll,) = self.polls().values()
        self.assertEqual(
            ("ci_command", 2, "passed"), (poll["subject"], poll["tier"], poll["result"])
        )
        self.assertEqual(1, self.read()[1]["ci_passed"])

    def test_a_poll_of_a_pull_request_a_pr_link_record_names_counts(self) -> None:
        self.goal_texts = ()
        self.session.bash("gh pr checks 17", "all pass", is_error=False)
        self.session.rows.append(
            {"type": "pr-link", "prNumber": 17, "prRepository": "acme/widgets"}
        )
        self.session.rows.append({"type": "pr-link", "prNumber": 5, "prRepository": "other/old"})
        (poll,) = self.polls().values()
        self.assertEqual("ci_command", poll["subject"])

    def test_a_record_for_another_repository_binds_nothing_here(self) -> None:
        self.goal_texts = ()
        self.session.bash("gh pr checks 5", "all pass", is_error=False)
        self.session.rows.append({"type": "pr-link", "prNumber": 5, "prRepository": "other/old"})
        (poll,) = self.polls().values()
        self.assert_unbound(poll)

    def test_a_poll_of_a_number_nothing_binds_does_not_count(self) -> None:
        self.goal_texts = ()
        self.session.bash("gh pr checks 77", "all pass", is_error=False)
        (poll,) = self.polls().values()
        self.assert_unbound(poll)

    def test_a_poll_of_a_pushed_branch_counts_and_of_another_branch_does_not(self) -> None:
        self.goal_texts = ()
        self.session.rows.append(
            {
                "type": "user",
                "toolUseResult": {"gitOperation": {"push": {"branch": "fix/widget-guard"}}},
            }
        )
        self.session.bash("gh pr checks fix/widget-guard", "all pass", is_error=False)
        self.session.bash("gh pr checks fix/elsewhere", "all pass", is_error=False)
        found = self.polls()
        self.assertEqual("ci_command", found["gh pr checks fix/widget-guard"]["subject"])
        self.assert_unbound(found["gh pr checks fix/elsewhere"])

    def test_a_poll_naming_no_repository_or_number_reads_the_folders_own_remote(self) -> None:
        self.goal_texts = ()
        self.session.bash("gh pr checks", "all pass", is_error=False)
        self.session.bash("gh pr checks --repo acme/widgets", "all pass", is_error=False)
        for poll in self.polls().values():
            self.assertEqual("ci_command", poll["subject"])

    def test_a_poll_whose_url_names_another_repository_does_not_count(self) -> None:
        self.session.bash(
            "gh pr checks https://github.com/other/old/pull/3", "all pass", is_error=False
        )
        (poll,) = self.polls().values()
        self.assert_unbound(poll)

    def test_a_gh_repo_override_in_the_environment_is_a_repository_the_poll_names(self) -> None:
        self.session.bash("GH_REPO=other/old gh pr checks 3", "all pass", is_error=False)
        (poll,) = self.polls().values()
        self.assert_unbound(poll)

    def test_no_git_identity_leaves_the_reason_token(self) -> None:
        self.remote = None
        self.session.bash("gh pr checks 3", "all pass", is_error=False)
        (poll,) = self.polls().values()
        self.assert_unbound(poll)

    def test_a_remote_that_is_not_github_binds_nothing(self) -> None:
        self.remote = ("gitlab.example.net", "acme/widgets")
        self.session.bash("gh pr checks 3", "all pass", is_error=False)
        (poll,) = self.polls().values()
        self.assert_unbound(poll)

    def test_no_git_leaves_the_reason_token_without_running_git(self) -> None:
        self.config = dataclasses.replace(self.config, git_probe_enabled=False)
        self.session.bash("gh pr checks 3", "all pass", is_error=False)
        with mock.patch.object(ci_read, "probe_session") as probe:
            (poll,) = self.polls().values()
        self.assert_unbound(poll)
        probe.assert_not_called()

    def test_a_run_view_binds_by_repository_alone(self) -> None:
        self.goal_texts = ()
        self.session.bash("gh run view 5 --exit-status", "failure", is_error=True)
        self.session.bash("gh run view 6 --exit-status --repo other/old", "failure", is_error=True)
        found = self.polls()
        self.assertEqual("failed", found["gh run view 5 --exit-status"]["result"])
        self.assertEqual("ci_command", found["gh run view 5 --exit-status"]["subject"])
        self.assert_unbound(found["gh run view 6 --exit-status --repo other/old"])

    def test_a_poll_that_only_opens_a_browser_reads_nothing(self) -> None:
        self.goal_texts = ("Merge https://github.com/acme/widgets/pull/42 once it is green.",)
        for command in (
            "gh pr checks 42 --web",
            "gh pr checks -w 42",
            "gh pr checks 42 --web=true",
            "gh pr checks -wi 5 42",
            "gh pr checks -w -i5 42",
        ):
            self.session.bash(command, "Opening github.com in your browser.", is_error=False)
        self.session.bash("gh pr checks 42", "Exit code 1\nbuild\tfail", is_error=True)
        found = self.polls()
        self.assertEqual(["gh pr checks 42"], list(found))
        _entries, scan = self.read()
        self.assertEqual((0, 1), (scan["ci_passed"], scan["ci_failed"]))

    def test_a_session_that_never_polled_runs_no_git(self) -> None:
        self.session.bash("make build", "done", is_error=False)
        with mock.patch.object(ci_read, "probe_session") as probe:
            self.read()
        probe.assert_not_called()


class ACiPollReadsTheSessionFoldersRepository(ClaudeChecksTestCase):
    """The repository a poll reads is the session folder's, wherever the call's own `cd` went.

    The probe is stubbed by folder, so no git runs; `ACiPollInRealCheckouts` runs real git.
    """

    OTHER = "/srv/other-clone"
    TREE = "/srv/widgets-worktree"

    def setUp(self) -> None:
        super().setUp()
        self.folder_remotes = {self.OTHER: ("github.com", "other/old"), self.TREE: REMOTE}

    def polls(self) -> dict[str, dict[str, Any]]:
        return {e["title"]: e for e in self.read()[0] if e["subject"] in ("command", "ci_command")}

    def assert_unbound(self, poll: dict[str, Any]) -> None:
        self.assertEqual(
            ("command", 3, True, "ci_poll_unbound"),
            (poll["subject"], poll["tier"], poll["cannot_fail"], poll["result_reason"]),
        )

    def assert_counts(self, poll: dict[str, Any]) -> None:
        self.assertEqual(("ci_command", 2), (poll["subject"], poll["tier"]))
        self.assertNotIn("result_reason", poll)

    def test_a_poll_run_in_another_clone_does_not_count(self) -> None:
        self.session.bash(f"cd {self.OTHER} && gh pr checks", "all pass", is_error=False)
        self.session.bash(f"(cd {self.OTHER} && gh pr checks 2)", "all pass", is_error=False)
        found = self.polls()
        self.assertEqual(2, len(found))
        for poll in found.values():
            self.assert_unbound(poll)

    def test_a_poll_run_in_a_worktree_of_the_same_repository_counts(self) -> None:
        self.session.bash(f"cd {self.TREE} && gh pr checks", "all pass", is_error=False)
        (poll,) = self.polls().values()
        self.assert_counts(poll)

    def test_a_poll_naming_the_session_repository_counts_from_any_directory(self) -> None:
        self.session.bash(
            f"cd {self.OTHER} && gh pr checks 3 -R acme/widgets", "ok", is_error=False
        )
        (poll,) = self.polls().values()
        self.assert_counts(poll)

    def test_a_poll_naming_another_repository_never_counts_from_the_session_folder(self) -> None:
        self.session.bash(
            f"cd {self.TREE} && gh pr checks 3 --repo other/old", "ok", is_error=False
        )
        (poll,) = self.polls().values()
        self.assert_unbound(poll)

    def test_a_directory_the_shell_decides_binds_nothing(self) -> None:
        for command in (
            'cd "$CHECKOUT" && gh pr checks 3',
            'cd "$(mktemp -d)" && gh pr checks 4',
            "if true; then cd ../old; fi; gh pr checks 5",
            "cd $DECOY && gh pr checks 6",
        ):
            self.session.bash(command, "all pass", is_error=False)
        found = self.polls()
        self.assertEqual(4, len(found))
        for poll in found.values():
            self.assert_unbound(poll)

    def test_an_unplaced_directory_does_not_stop_a_poll_that_names_the_session_repository(
        self,
    ) -> None:
        self.session.bash('cd "$CHECKOUT" && gh pr checks 3 --repo acme/widgets', "ok")
        (poll,) = self.polls().values()
        self.assert_counts(poll)

    def test_command_and_builtin_cd_move_the_directory_a_poll_runs_in(self) -> None:
        for command in (
            f"command cd {self.OTHER} && gh pr checks 3",
            f"builtin cd {self.OTHER} && gh pr checks 4",
            f"command -p cd {self.OTHER} && gh pr checks 5",
        ):
            self.session.bash(command, "all pass", is_error=False)
        self.session.bash(f"command cd {self.TREE} && gh pr checks 6", "all pass")
        found = self.polls()
        self.assertEqual(4, len(found), list(found))
        for title, poll in found.items():
            with self.subTest(title=title):
                if title == "gh pr checks 6":
                    self.assert_counts(poll)
                else:
                    self.assert_unbound(poll)

    def test_eval_or_a_variable_command_before_a_poll_leaves_its_directory_unplaced(self) -> None:
        for command in (
            'eval "$SETUP" && gh pr checks 3',
            "$GOTO /srv/elsewhere; gh pr checks 4",
            "X=1 $RUN && gh pr checks 5",
            "command eval 'cd ../old'; gh pr checks 6",
            "source ./env.sh && gh pr checks 7",
            ". ./env.sh; gh pr checks 8",
        ):
            self.session.bash(command, "all pass", is_error=False)
        found = {t: p for t, p in self.polls().items() if t.startswith("gh pr checks")}
        self.assertEqual(6, len(found))
        for poll in found.values():
            self.assert_unbound(poll)

    def test_an_eval_after_the_poll_does_not_unplace_it(self) -> None:
        self.session.bash("gh pr checks 3 && eval true", "all pass", is_error=False)
        found = {t: p for t, p in self.polls().items() if t.startswith("gh pr checks")}
        self.assertEqual({"gh pr checks 3"}, set(found))
        self.assert_counts(found["gh pr checks 3"])

    def test_an_environment_pointing_gh_elsewhere_binds_nothing(self) -> None:
        for command in (
            "export GH_REPO=other/old && gh pr checks 3",
            "GH_HOST=ghe.example.com gh pr checks 4",
            "export GH_HOST=ghe.example.com; gh pr checks 5",
            "env GH_HOST=ghe.example.com gh pr checks 6",
            "declare -x GH_REPO=other/old; gh pr checks 7",
            "export GH_ENTERPRISE_TOKEN=FakePass99; gh pr checks 8",
        ):
            self.session.bash(command, "all pass", is_error=False)
        found = {t: p for t, p in self.polls().items() if t.startswith("gh pr checks")}
        self.assertEqual(6, len(found))
        for poll in found.values():
            self.assert_unbound(poll)

    def test_a_call_of_thousands_of_polls_costs_a_pass_and_keeps_the_environment_order(
        self,
    ) -> None:
        if sys.gettrace() is not None or "coverage" in sys.modules:
            self.skipTest("timed without a tracer only")
        count = 12000
        polls = [f"gh pr checks {number}" for number in range(1, count + 1)]
        polls.insert(count // 2, "export GH_REPO=other/old")
        command = " && ".join(polls)
        started = time.process_time()
        self.session.bash(command, "all pass", is_error=False)
        found = {t: p for t, p in self.polls().items() if t.startswith("gh pr checks")}
        # Linear in the polls: about 1.5 s here. The earlier per-poll scans took half a minute.
        self.assertLess(time.process_time() - started, 8.0)
        self.assertGreater(len(found), 0)
        for text, poll in found.items():
            number = int(text.rsplit(" ", 1)[1])
            if number > count // 2:
                self.assert_unbound(poll)

    def test_a_run_view_url_binds_by_the_repository_it_names(self) -> None:
        self.goal_texts = ()
        other = "gh run view https://github.com/other/old/actions/runs/5 --exit-status"
        own = "gh run view https://github.com/acme/widgets/actions/runs/5/job/9 --exit-status"
        junk = "gh run view other-url --exit-status"
        elsewhere = "gh run view https://example.com/acme/widgets/actions/runs/5 --exit-status"
        clash = (
            "gh run view https://github.com/acme/widgets/actions/runs/5 "
            "--exit-status --repo other/old"
        )
        for command in (other, own, junk, elsewhere, clash):
            self.session.bash(command, "failure", is_error=True)
        found = self.polls()
        self.assertEqual("ci_command", found[own]["subject"])
        for command in (other, junk, elsewhere, clash):
            with self.subTest(command=command):
                self.assert_unbound(found[command])
        self.assertEqual(1, self.read()[1]["ci_failed"])

    def test_a_pull_request_the_session_created_binds_a_poll(self) -> None:
        self.goal_texts = ()
        url = "https://github.com/acme/widgets/pull/44"
        call_id = self.session.call("Bash", {"command": "gh pr create --fill"})
        self.session.result(
            call_id,
            url,
            is_error=False,
            tool_use_result={
                "gitOperation": {"pr": {"number": 44, "url": url, "action": "created"}}
            },
        )
        self.session.bash("gh pr checks 44", "all pass", is_error=False)
        self.session.bash("gh pr checks 45", "all pass", is_error=False)
        found = self.polls()
        self.assert_counts(found["gh pr checks 44"])
        self.assert_unbound(found["gh pr checks 45"])

    def test_no_git_launches_nothing_for_a_session_holding_a_poll(self) -> None:
        self.config = dataclasses.replace(self.config, git_probe_enabled=False)
        self.probe_patch.stop()
        self.session.bash(f"cd {self.OTHER} && gh pr checks 3", "all pass", is_error=False)
        self.session.bash("gh pr checks 3 --repo acme/widgets", "all pass", is_error=False)
        boom = mock.Mock(side_effect=AssertionError("a subprocess was started"))
        with mock.patch.multiple(subprocess, Popen=boom, run=boom):
            found = self.polls()
        self.assertEqual(2, len(found))
        for poll in found.values():
            self.assert_unbound(poll)


class ACiPollInRealCheckouts(ClaudeChecksTestCase):
    """Real repositories, so the folder's remote is read by git and compared, not stubbed."""

    def git(self, folder: Path, *args: str) -> None:
        # The user's own git config and hooks stay out of the fixture repositories: a global
        # `core.hooksPath`, a signing key or an `init.templateDir` would change what these build.
        environ = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        subprocess.run(
            [  # noqa: S607 - the test's own repositories, a real git on PATH
                "git",
                "-c",
                "core.hooksPath=" + os.devnull,
                "-c",
                "user.name=T",
                "-c",
                "user.email=t@example.com",
                "-c",
                "commit.gpgsign=false",
                *args,
            ],
            cwd=folder,
            check=True,
            capture_output=True,
            env=environ,
        )

    def repository(self, folder: Path, origin: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self.git(folder, "init", "-q")
        self.git(folder, "commit", "-q", "--allow-empty", "-m", "x")
        self.git(folder, "remote", "add", "origin", f"https://github.com/{origin}.git")

    def setUp(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not installed")
        super().setUp()
        self.probe_patch.stop()
        self.repository(self.cwd, "acme/widgets")
        self.other = self.root / "other-clone"
        self.repository(self.other, "other/old")
        self.tree = self.root / "widgets-tree"
        self.git(self.cwd, "worktree", "add", "-q", "-b", "side", str(self.tree))

    def polls(self) -> dict[str, dict[str, Any]]:
        return {e["title"]: e for e in self.read()[0] if e["subject"] in ("command", "ci_command")}

    def test_the_folders_remote_decides_which_checkout_a_poll_read(self) -> None:
        self.session.bash(f"cd {self.other} && gh pr checks", "all pass", is_error=False)
        self.session.bash(f"(cd {self.other} && gh pr checks 2)", "all pass", is_error=False)
        self.session.bash(f"cd {self.tree} && gh pr checks 3", "all pass", is_error=False)
        self.session.bash(f"cd {self.other} && gh pr checks 4 -R acme/widgets", "ok")
        self.session.bash("gh pr checks 5 --repo other/old", "all pass", is_error=False)
        found = self.polls()
        self.assertEqual(
            {
                "gh pr checks": "command",
                "gh pr checks 2": "command",
                "gh pr checks 3": "ci_command",
                "gh pr checks 4 -R acme/widgets": "ci_command",
                "gh pr checks 5 --repo other/old": "command",
            },
            {title: poll["subject"] for title, poll in found.items()},
        )

    def test_a_second_read_with_unchanged_git_files_starts_no_git(self) -> None:
        remotes = git_status.StampCache()
        self.session.bash(f"cd {self.tree} && gh pr checks 3", "all pass", is_error=False)
        self.session.save(self.path)

        def read() -> list[dict[str, Any]]:
            return project_context.claude_tool_reports(
                self.config,
                str(self.path),
                SHORT,
                goal_texts=self.goal_texts,
                remotes=remotes,
            )[0]

        with mock.patch.object(ci_read, "probe_session", wraps=ci_read.probe_session) as probe:
            first = read()
            started = probe.call_count
            second = read()
            self.assertEqual(started, probe.call_count)
            self.assertEqual(first, second)
            self.assertGreater(started, 0)
            self.assertEqual(
                {"ci_command"}, {e["subject"] for e in second if "gh pr" in e["title"]}
            )
            # The remote lives in the shared config, which a worktree reads from the common
            # directory: changing it moves the stamp of the session folder and of the worktree.
            self.git(self.cwd, "remote", "set-url", "origin", "https://github.com/other/old.git")
            third = read()
        self.assertGreater(probe.call_count, started)
        self.assertEqual({"command"}, {e["subject"] for e in third if "gh pr" in e["title"]})

    def test_a_failed_poll_in_another_clone_blocks_no_level(self) -> None:
        self.session.write(str(self.cwd / "src" / "a.py"))
        self.session.bash(
            f"cd {self.other} && gh pr checks", "Exit code 1\nbuild\tfail", is_error=True
        )
        entries, scan = self.read()
        self.assertEqual(0, scan["ci_failed"] + scan["command_failed"])
        self.assertEqual({"command"}, {e["subject"] for e in entries if "gh pr" in e["title"]})
        self.assertNotEqual(levels.HIGH, self.level(entries, scan).level)

    def level(self, entries: list[dict[str, Any]], scan: dict[str, Any]) -> levels.Level:
        return levels.live_level(
            levels.Evidence(tuple(facts_of(entries)), scan, 0, str(self.cwd)),
            levels.Intent(saved=True, goal="Ship the parser", lines=("It passes",)),
        )

    def test_collection_binds_a_poll_by_the_session_rows_own_goal(self) -> None:
        self.session.write(str(self.cwd / "src" / "a.py"))
        self.session.bash("gh pr checks 1", "Exit code 1\nbuild\tfail", is_error=True)
        self.session.save(self.path)
        own = "Land https://github.com/acme/widgets/pull/1"
        for row, subject, blocks in (
            ({}, "command", False),
            ({"annotation_goal": own}, "ci_command", True),
            ({"session_goal": {"text": own, "at": 1.0}}, "ci_command", True),
            ({"annotation_goal": "Land https://github.com/other/old/pull/1"}, "command", False),
        ):
            with self.subTest(row=row):
                events: list[dict[str, Any]] = []
                scans: list[dict[str, Any]] = []
                project_context._session_work_evidence(
                    self.config,
                    str(self.path),
                    {"harness": "claude", "sid": SHORT, **row},
                    events,
                    scans,
                )
                polls = [e for e in events if e.get("title") == "gh pr checks 1"]
                self.assertEqual([subject], [e["subject"] for e in polls])
                reached = self.level(events, scans[0]).level
                self.assertEqual(blocks, reached == levels.HIGH)


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
        entries, _scan = self.read()
        press = self.press()
        tails = reading_route.tails_for(provider, "claude", press.tails, press.tier3_calls)
        ledger = reading.build_ledger(
            [base.WORDS_FACT, *facts_of(entries)], "claude", SHORT, tool_output=tails
        )
        text, _selection = reading.build_prompt(
            ledger, goal="deploy", lines=("deployed",), max_bytes=16_000
        )
        return text

    def press(self) -> project_context.PressChecks:
        return project_context.claude_check_press(
            self.config, str(self.path), goal_texts=self.goal_texts
        )

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
        press = self.press()
        self.assertEqual({"toolu_001", "toolu_002"}, set(press.tier3_calls))

    def test_another_vendor_gets_no_tail_of_a_poll_the_session_is_not_bound_to(self) -> None:
        self.session.bash(
            "gh pr checks 99 --repo other/old", "SYNTHETICUNBOUNDTAIL", is_error=False
        )
        self.session.bash("gh pr checks 1", "SYNTHETICBOUNDTAIL", is_error=False)
        self.session.save(self.path)
        press = self.press()
        self.assertEqual({"toolu_001"}, set(press.tier3_calls))
        other = reading_route.tails_for("codex", "claude", press.tails, press.tier3_calls)
        same = reading_route.tails_for("claude", "claude", press.tails, press.tier3_calls)
        self.assertNotIn("SYNTHETICUNBOUNDTAIL", "\n".join(other.values()))
        self.assertIn("SYNTHETICBOUNDTAIL", "\n".join(other.values()))
        self.assertIn("SYNTHETICUNBOUNDTAIL", "\n".join(same.values()))

    def test_a_press_with_no_goal_texts_withholds_a_poll_that_names_a_number(self) -> None:
        self.session.bash("gh pr checks 1", "SYNTHETICBOUNDTAIL", is_error=False)
        self.session.save(self.path)
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual({"toolu_001"}, set(press.tier3_calls))
        other = reading_route.tails_for("codex", "claude", press.tails, press.tier3_calls)
        self.assertEqual({}, other)

    def test_the_request_handler_binds_a_poll_by_the_rows_own_goal(self) -> None:
        self.session.bash("gh pr checks 1", "SYNTHETICBOUNDTAIL", is_error=False)
        self.session.bash("gh pr checks 99 --repo other/old", "SYNTHETICUNBOUNDTAIL")
        other = "\n".join(self.route_tails("codex").values())
        self.assertIn("SYNTHETICBOUNDTAIL", other)
        self.assertNotIn("SYNTHETICUNBOUNDTAIL", other)

    def route_tails(self, provider: str) -> dict[str, str]:
        """The tails the real request handler hands a route of this provider."""
        return dict(self.route_output(provider).tails)

    def route_output(self, provider: str, destination: str = "Synthetic destination") -> Any:
        self.session.save(self.path)
        handler = SimpleNamespace(
            server=SimpleNamespace(
                application=SimpleNamespace(
                    config=self.config,
                    state=SimpleNamespace(ci_remotes=git_status.StampCache()),
                    clock=lambda: 1.0,
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
                {"harness": "claude", "sid": SHORT, "annotation_goal": BOUND_GOAL},
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
        press = self.press()
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


class TheEdgesOfTheCommandTiers(ClaudeChecksTestCase):
    def test_a_pass_of_a_command_or_a_ci_read_is_counted_by_the_unread_pass_guard(self) -> None:
        self.session.bash("make deploy", "done", is_error=False)
        self.session.bash("gh pr checks 12", "all pass", is_error=False)
        self.session.save(self.path)
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual(
            ["gh pr checks 12", "make deploy"], sorted(p[1] for p in press.passes_and_writes)
        )

    def test_a_failed_command_ranks_ahead_of_a_passed_one_and_behind_a_check(self) -> None:
        failed = reading.build_ledger(
            [base.check_fact(fact_id="c1", subject="command", tier=3, summary="make a")],
            "claude",
            "s1",
            tool_output={},
        )[0]
        passed = cast("reading.LedgerEntry", {**failed, "result": "passed"})
        check = cast("reading.LedgerEntry", {**failed, "subject": "check"})
        message = cast("reading.LedgerEntry", {**failed, "type": "agent_message", "subject": "x"})
        self.assertLess(reading._priority(check), reading._priority(failed))
        self.assertLess(reading._priority(failed), reading._priority(passed))
        self.assertLess(reading._priority(passed), reading._priority(message))

    def test_a_failed_command_a_full_bound_left_out_is_an_unread_failure(self) -> None:
        facts = [base.WORDS_FACT]
        facts += [
            base.check_fact(
                fact_id=f"c{n}",
                subject="command",
                tier=3,
                result="passed",
                summary=f"make step{n}",
                at=100.0 + n,
            )
            for n in range(40)
        ]
        facts.append(
            base.check_fact(
                fact_id="bad",
                subject="command",
                tier=3,
                result="failed",
                summary="make broken",
                at=50.0,
            )
        )
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={})
        _text, small = reading.build_prompt(
            ledger, goal="deploy", lines=("deployed",), max_bytes=2_600
        )
        self.assertGreater(len(ledger), len(small.entries))
        titles = [e["summary"] for e in small.entries]
        self.assertTrue(any("make broken" in t for t in titles), titles)
        # With room for the failures alone behind a flood of failed checks, it is carried unread.
        flood = [
            base.check_fact(
                fact_id=f"k{n}", result="failed", summary=f"pytest t{n}.py", at=60.0 + n
            )
            for n in range(60)
        ]
        ledger = reading.build_ledger(
            [base.WORDS_FACT, *flood, facts[-1]], "claude", "s1", tool_output={}
        )
        _text, tight = reading.build_prompt(
            ledger, goal="deploy", lines=("deployed",), max_bytes=2_600
        )
        self.assertTrue(any("make broken" in e["summary"] for e in tight.unread_failures))

    def test_two_directories_running_one_line_keep_distinct_fact_ids(self) -> None:
        self.session.bash("cd a && make deploy; cd b && make deploy", "done", is_error=False)
        self.session.bash("cd a && pytest -q; cd b && pytest -q", "3 passed", is_error=False)
        self.session.bash("make solo", "done", is_error=False)
        facts = facts_of(self.read()[0])
        ids = [f["fact_id"] for f in facts]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(5, len(ids))
        self.assertNotIn("id_title", json.dumps(facts))

    def test_a_single_segment_and_a_repeat_in_one_place_keep_the_id_they_had(self) -> None:
        self.session.bash("make deploy; make deploy", "done", is_error=False)
        (event,) = [e for e in self.read()[0] if e["subject"] == "command"]
        self.assertNotIn("id_title", event)
        self.session.bash("cd a && pytest -q & cd b && pytest -q", "3 passed", is_error=False)
        (check,) = [e for e in self.read()[0] if e["subject"] == "check"]
        self.assertNotIn("id_title", check)

    def test_gh_error_lines_only_withdraw_a_failure_when_gh_wrote_them(self) -> None:
        rows = {
            "gh pr checks 12": "Exit code 1\nauthentication\tfail\t1m\thttps://ci.example/1",
            "gh pr checks 13": "Exit code 1\nbuild\tfail\t1m\thttps://ci.example/HTTP 500 retry",
            "gh pr checks 14": "Exit code 1\nHTTP 404: Not Found (https://api.example/x)",
            "gh pr checks 15": "Exit code 1\nTo get started, please run:  gh auth login",
            "gh pr checks 16": "Exit code 1\nno checks reported on the 'fix/widget-guard' branch",
            "gh pr checks 20": "Exit code 1\nCould not resolve to a PullRequest",
            "gh pr checks 21": "Exit code 1\nGraphQL: Could not resolve to a PullRequest with the"
            " number of 12. (repository.pullRequest)",
            "gh pr checks 22": "Exit code 1\ngh: Not Found (HTTP 404)",
            "gh pr checks 23": "Exit code 1\ngh: GraphQL: Could not resolve to a Repository",
        }
        for command, text in rows.items():
            self.session.bash(command, text, is_error=True)
        got = {e["title"]: e["result"] for e in self.read()[0] if e["subject"] == "ci_command"}
        self.assertEqual("failed", got["gh pr checks 12"])
        self.assertEqual("failed", got["gh pr checks 13"])
        for number in (14, 15, 16, 20, 21, 22, 23):
            self.assertEqual("not-recorded", got[f"gh pr checks {number}"])

    def test_a_hostile_first_line_is_not_matched_against_the_error_shapes(self) -> None:
        for line in ("a: " * 40_000, "a" * 100_000 + " gh auth login"):
            started = time.process_time()
            self.assertFalse(project_context._gh_error_line(f"Exit code 1\n{line}"))
            self.assertLess(time.process_time() - started, 1.0)
        self.assertTrue(project_context._gh_error_line("Exit code 1\ngh: Not Found (HTTP 404)"))

    def test_the_last_stage_of_a_pipe_after_work_speaks_for_itself(self) -> None:
        self.session.bash("make stage | ./release.sh", "done", is_error=False)
        self.session.bash("make stage2 | ./fail.sh", "boom", is_error=True)
        self.session.bash("pytest -q | ./summarize.sh", "3 passed", is_error=False)
        got = {e["title"]: e["result"] for e in self.read()[0] if e["subject"] == "command"}
        self.assertEqual("passed", got["./release.sh"])
        # A failure speaks only for a call of one segment, the rule a check follows too.
        self.assertEqual("not-recorded", got["./fail.sh"])
        self.assertNotEqual("passed", got["make stage"])
        self.assertNotEqual("failed", got["make stage2"])

    def test_a_tier_3_failure_a_later_pass_covers_is_not_cited_by_the_live_level(self) -> None:
        self.session.write(self.file("src/new.py"))
        self.session.bash("git commit -m wip", "hook rejected", is_error=True)
        self.session.bash("git commit -m fix", "done", is_error=False)
        self.session.bash("pytest -q", "3 passed", is_error=False)
        entries, scan = self.read()
        facts = facts_of(entries)
        got = levels.live_level(
            lv.evidence(facts, {**lv.scan(), **scan, "last_user_at": 9e9}), lv.intent("Tests pass")
        )
        self.assertEqual(levels.NONE_OR_LOW, got.level)
        failed = [f["fact_id"] for f in facts if f.get("result") == "failed"]
        self.assertEqual(1, len(failed))
        self.assertNotIn(failed[0], got.cites)

    def test_an_uncovered_tier_3_failure_is_still_cited(self) -> None:
        self.session.write(self.file("src/new.py"))
        self.session.bash("pytest -q", "3 passed", is_error=False)
        self.session.bash("git commit -m wip", "hook rejected", is_error=True)
        entries, scan = self.read()
        facts = facts_of(entries)
        got = levels.live_level(
            lv.evidence(facts, {**lv.scan(), **scan, "last_user_at": 9e9}), lv.intent("Tests pass")
        )
        failed = [f["fact_id"] for f in facts if f.get("result") == "failed"]
        self.assertIn(failed[0], got.cites)


if __name__ == "__main__":
    unittest.main()
