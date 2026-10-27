"""A reader lists a project's own check commands in a file under the Compass home.

[DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
rules the tiers, and its 2026-10-27 amendment on reader-listed checks says what the file may hold.
Every project, command and path here is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from compass_runtime import diagnostics, project_context, reader_checks, reading, sessions

from .test_claude_checks import ClaudeChecksTestCase

BAZEL = "bazel test //..."


class ReaderChecksTestCase(ClaudeChecksTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = Path(reader_checks.store_path(self.config))

    def list_checks(self, projects: dict[str, Any] | None = None, *, v: int = 1) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        listed = {str(self.cwd): [BAZEL]} if projects is None else projects
        self.store.write_text(json.dumps({"v": v, "projects": listed}), encoding="utf-8")

    def titles(self, subject: str = "check") -> list[str]:
        return [e["title"] for e in self.read()[0] if e["subject"] == subject]

    def report(self) -> dict[str, Any]:
        return reader_checks.report(self.config, project_context.listed_entry_refusal)


class ACommandTheReaderListedIsATier2Check(ReaderChecksTestCase):
    def test_a_listed_command_is_a_check_with_its_result_and_says_so(self) -> None:
        self.list_checks()
        self.session.bash(BAZEL, "Executed 4 tests, 4 tests pass.")
        check = self.only_check()
        self.assertEqual((BAZEL, "passed"), (check["title"], check["result"]))
        self.assertIs(True, check["listed_by_reader"])
        self.assertEqual([], self.titles("command"))

    def test_a_failing_listed_command_is_a_failed_check(self) -> None:
        self.list_checks()
        self.session.bash(BAZEL, "FAILED", is_error=True)
        self.assertEqual("failed", self.only_check()["result"])

    def test_without_the_file_the_same_command_is_a_tier_3_command(self) -> None:
        self.session.bash(BAZEL, "ok")
        self.assertEqual([], self.titles())
        self.assertEqual([BAZEL], self.titles("command"))

    def test_an_ordinary_check_does_not_carry_the_listed_mark(self) -> None:
        self.list_checks()
        self.session.bash("pytest -q", "1 passed in 0.1s")
        self.assertNotIn("listed_by_reader", self.only_check())

    def test_only_the_listed_words_count_and_another_target_is_a_command(self) -> None:
        self.list_checks()
        self.session.bash("bazel test //other/...", "ok")
        self.assertEqual([], self.titles())

    def test_the_project_may_be_named_by_its_published_key(self) -> None:
        key = sessions.project_identity(self.config, str(self.cwd))["key"]
        self.list_checks({key: [BAZEL]})
        self.session.bash(BAZEL, "ok")
        self.assertEqual([BAZEL], self.titles())

    def test_another_projects_listing_does_not_apply(self) -> None:
        self.list_checks({str(self.root / "work" / "other"): [BAZEL]})
        self.session.bash(BAZEL, "ok")
        self.assertEqual([], self.titles())

    def test_a_listed_command_still_ages_an_earlier_pass(self) -> None:
        self.list_checks({str(self.cwd): ["make verify-all"]})
        self.session.bash("pytest -q", "1 passed in 0.1s")
        self.session.bash("make verify-all", "done")
        passed = next(c for c in self.read()[0] if c["title"] == "pytest -q")
        self.assertIs(True, passed["changed_after"])


class NothingIsReadFromTheRepository(ReaderChecksTestCase):
    def test_a_compass_folder_inside_the_project_is_never_read(self) -> None:
        inside = self.cwd / ".compass"
        inside.mkdir()
        (inside / self.store.name).write_text(
            json.dumps({"v": 1, "projects": {str(self.cwd): [BAZEL]}}), encoding="utf-8"
        )
        self.session.bash(BAZEL, "ok")
        self.assertEqual([], self.titles())
        self.assertEqual([BAZEL], self.titles("command"))

    def test_the_file_is_read_from_the_compass_home_only(self) -> None:
        self.assertEqual(Path(self.config.state_home), self.store.parent)


class WhatCannotBeACheckIsIgnoredAndDiagnoseSaysSo(ReaderChecksTestCase):
    ENTRIES = ("echo ok", "true", ":", "exit 0", "printf done", "ls -la", "git status", "cd /tmp")

    def test_a_command_that_cannot_fail_or_only_reads_never_counts(self) -> None:
        self.list_checks({str(self.cwd): [*self.ENTRIES, BAZEL]})
        for entry in self.ENTRIES:
            self.session.bash(entry, "ok")
        self.assertEqual([], self.titles())

    def test_the_report_names_each_ignored_entry_with_its_program_and_a_reason(self) -> None:
        self.list_checks({str(self.cwd): [*self.ENTRIES, BAZEL]})
        report = self.report()
        ignored = {item["program"]: item["reason"] for item in report["ignored"]}
        self.assertEqual({"echo", "true", ":", "exit", "printf", "ls", "git", "cd"}, set(ignored))
        self.assertEqual(reader_checks.CANNOT_FAIL_REASON, ignored["echo"])
        self.assertEqual(reader_checks.READ_ONLY_REASON, ignored["ls"])
        self.assertEqual(reader_checks.BUILTIN_REASON, ignored["cd"])
        self.assertEqual(1, report["listed"])
        text = diagnostics.render_reader_checks(report)
        self.assertIn(str(self.store), text)
        self.assertIn("echo", text)
        self.assertIn(reader_checks.CANNOT_FAIL_REASON, text)

    def test_a_line_that_is_not_one_plain_command_is_ignored(self) -> None:
        entries = ["make a && make b", "make a | tee log", "make a > out.txt", "make $(whoami)"]
        self.list_checks({str(self.cwd): entries})
        report = self.report()
        self.assertEqual(4, len(report["ignored"]))
        self.assertEqual(0, report["listed"])
        self.assertEqual(
            {reader_checks.NOT_ONE_COMMAND_REASON}, {i["reason"] for i in report["ignored"]}
        )

    def test_a_fixer_is_ignored(self) -> None:
        self.list_checks({str(self.cwd): ["ruff check --fix ."]})
        self.assertEqual(
            [reader_checks.WRITES_REASON], [i["reason"] for i in self.report()["ignored"]]
        )


class AnUnreadableFileIsDiscardedNotRepaired(ReaderChecksTestCase):
    def test_corrupt_json_lists_nothing_and_diagnose_says_so(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text('{"v": 1, "projects": {', encoding="utf-8")
        self.session.bash(BAZEL, "ok")
        self.assertEqual([], self.titles())
        self.assertEqual(reader_checks.UNREADABLE_REASON, self.report()["error"])
        self.assertEqual('{"v": 1, "projects": {', self.store.read_text(encoding="utf-8"))

    def test_a_file_over_the_cap_lists_nothing(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(" " * (reader_checks.MAX_FILE_BYTES + 1), encoding="utf-8")
        self.assertEqual(reader_checks.SIZE_REASON, self.report()["error"])

    def test_a_symlink_or_a_folder_is_not_a_regular_file(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.mkdir()
        self.assertEqual(reader_checks.NOT_REGULAR_REASON, self.report()["error"])

    def test_an_absent_file_is_not_an_error(self) -> None:
        report = self.report()
        self.assertIsNone(report["error"])
        self.assertEqual(0, report["listed"])

    def test_a_wrong_shape_lists_nothing(self) -> None:
        self.list_checks({str(self.cwd): "make verify"})
        self.assertEqual(0, self.report()["listed"])
        self.assertEqual(reader_checks.SHAPE_REASON, self.report()["error"])

    def test_the_counts_are_bounded(self) -> None:
        many = {str(self.cwd): [f"make t{i}" for i in range(reader_checks.MAX_COMMANDS + 5)]}
        self.list_checks(many)
        self.assertEqual(reader_checks.MAX_COMMANDS, self.report()["listed"])
        long_entry = "make " + "x" * reader_checks.MAX_COMMAND_CHARS
        self.list_checks({str(self.cwd): [long_entry]})
        self.assertEqual(0, self.report()["listed"])
        self.assertEqual(1, len(self.report()["ignored"]))


class ASessionThatWroteTheFileIsFlaggedAndNothingCounts(ReaderChecksTestCase):
    def test_a_recorded_write_withdraws_the_listing_and_the_scan_says_so(self) -> None:
        self.list_checks()
        self.session.write(str(self.store), "{}")
        self.session.bash(BAZEL, "ok")
        events, scan = self.read()
        self.assertEqual([], [e for e in events if e["subject"] == "check"])
        self.assertIs(True, scan["reader_checks_written"])

    def test_a_session_that_did_not_write_it_carries_no_flag(self) -> None:
        self.list_checks()
        self.session.bash(BAZEL, "ok")
        self.assertNotIn("reader_checks_written", self.read()[1])

    def test_a_write_by_an_edit_tool_in_another_folder_of_that_name_is_flagged_too(self) -> None:
        self.list_checks()
        self.session.edit(str(self.cwd / ".compass" / self.store.name))
        self.session.bash(BAZEL, "ok")
        self.assertIs(True, self.read()[1]["reader_checks_written"])


class TheModelAndThePublishedFactSayTheReaderListedIt(ReaderChecksTestCase):
    def test_the_row_the_model_reads_says_it(self) -> None:
        fact = {
            "subject": "check",
            "summary": BAZEL,
            "result": "passed",
            "result_source": "flag",
            "listed_by_reader": True,
        }
        row = reading._tool_report_summary(fact, 200)
        self.assertIn(reading.CHECK_LISTED_BY_READER, row)
        plain = reading._tool_report_summary({**fact, "listed_by_reader": False}, 200)
        self.assertNotIn(reading.CHECK_LISTED_BY_READER, plain)

    def test_the_published_fact_keeps_the_mark_and_an_ordinary_check_has_none(self) -> None:
        event = {
            "kind": "check_run",
            "subject": "check",
            "at": 1.0,
            "title": BAZEL,
            "listed_by_reader": True,
        }
        fact = project_context._semantic_fact_from_event(event, "tool_report", "tool_report", "")
        self.assertIs(True, fact["listed_by_reader"])
        plain = project_context._semantic_fact_from_event(
            {k: v for k, v in event.items() if k != "listed_by_reader"},
            "tool_report",
            "tool_report",
            "",
        )
        self.assertNotIn("listed_by_reader", plain)
