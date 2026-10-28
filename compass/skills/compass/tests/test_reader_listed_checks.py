"""A reader lists a project's own check commands in a file under the Compass home.

[DEC-29](docs/design-reading-a-session.md#dec-29-a-commands-result-is-evidence-by-tier-and-a-command-that-cannot-fail-never-passes)
rules the tiers, and its 2026-10-27 amendment on reader-listed checks says what the file may hold.
Every project, command and path here is synthetic.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    diagnostics,
    project_context,
    project_scripts,
    reader_checks,
    reading,
    session_source,
    sessions,
)

from .test_claude_checks import ClaudeChecksTestCase

BAZEL = "bazel test //..."


class ReaderChecksTestCase(ClaudeChecksTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.store = Path(reader_checks.store_path(self.config))

    def list_checks(self, projects: dict[str, Any] | None = None) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        listed = {str(self.cwd): [BAZEL]} if projects is None else projects
        self.store.write_text(json.dumps({"projects": listed}), encoding="utf-8")

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
            json.dumps({"projects": {str(self.cwd): [BAZEL]}}), encoding="utf-8"
        )
        self.session.bash(BAZEL, "ok")
        self.assertEqual([], self.titles())
        self.assertEqual([BAZEL], self.titles("command"))


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

    def test_exit_and_a_wrapped_command_that_cannot_fail_are_ignored(self) -> None:
        entries = ["exit 1", "return 1", "nice true", "sudo true", "xargs echo hi", "sudo ls"]
        self.list_checks({str(self.cwd): [*entries, BAZEL]})
        report = self.report()
        self.assertEqual(len(entries), len(report["ignored"]))
        self.assertEqual(1, report["listed"])
        for entry in entries:
            self.session.bash(entry, "ok")
        self.assertEqual([], self.titles())

    def test_every_shell_builtin_is_refused_bare_and_with_an_argument(self) -> None:
        for name in sorted(project_context._LISTED_BUILTINS):
            for entry in (name, f"{name} x"):
                with self.subTest(entry=entry):
                    reason, _program = project_context.listed_entry_refusal(entry)
                    self.assertNotEqual("", reason)
        for name in ("shopt", "bind", "typeset", "exec", "compgen", "history", "exit", "kill"):
            self.assertIn(name, project_context._LISTED_BUILTINS)

    def test_a_fixer_is_ignored(self) -> None:
        self.list_checks({str(self.cwd): ["ruff check --fix ."]})
        self.assertEqual(
            [reader_checks.WRITES_REASON], [i["reason"] for i in self.report()["ignored"]]
        )


class NoPublishedProgramIsAnArgumentOrAPath(ReaderChecksTestCase):
    SECRET = "FakePass99"  # noqa: S105

    def test_an_assignment_or_a_long_entry_never_publishes_its_value(self) -> None:
        long_entry = f"/home/x/{self.SECRET}/run " + "a" * reader_checks.MAX_COMMAND_CHARS
        entries = [
            f"API_TOKEN={self.SECRET} make a && make b",
            f"PGPASSWORD={self.SECRET} psql -c x | cat",
            f"API_TOKEN={self.SECRET} " + "b" * reader_checks.MAX_COMMAND_CHARS,
            long_entry,
        ]
        self.list_checks({str(self.cwd): entries})
        report = self.report()
        self.assertEqual(4, len(report["ignored"]))
        self.assertNotIn(self.SECRET, json.dumps(report))
        self.assertNotIn(self.SECRET, diagnostics.render_reader_checks(report))
        self.assertEqual({"make", "psql"}, {i["program"] for i in report["ignored"][:2]})

    def test_an_ignored_item_names_a_program_and_a_reason_and_no_project(self) -> None:
        self.list_checks({str(self.cwd): ["ls"]})
        self.assertEqual({"program", "reason"}, set(self.report()["ignored"][0]))
        self.assertNotIn(str(self.cwd), json.dumps(self.report()))

    def test_the_ignored_list_is_capped_and_the_rest_counted(self) -> None:
        self.list_checks({str(self.cwd): ["ls"] * (reader_checks.MAX_IGNORED + 5)})
        report = self.report()
        self.assertEqual(reader_checks.MAX_IGNORED, len(report["ignored"]))
        self.assertEqual(5, report["ignored_more"])


class AnUnreadableFileIsDiscardedNotRepaired(ReaderChecksTestCase):
    def test_corrupt_json_lists_nothing_and_diagnose_says_so(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text('{"projects": {', encoding="utf-8")
        self.session.bash(BAZEL, "ok")
        self.assertEqual([], self.titles())
        self.assertEqual(reader_checks.UNREADABLE_REASON, self.report()["error"])
        self.assertEqual('{"projects": {', self.store.read_text(encoding="utf-8"))

    def test_a_file_over_the_cap_lists_nothing(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(" " * (reader_checks.MAX_FILE_BYTES + 1), encoding="utf-8")
        self.assertEqual(reader_checks.SIZE_REASON, self.report()["error"])

    def test_a_folder_is_not_a_regular_file(self) -> None:
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

    def test_the_counts_are_bounded_and_the_overflow_is_reported(self) -> None:
        many = {str(self.cwd): [f"make t{i}" for i in range(reader_checks.MAX_COMMANDS + 5)]}
        self.list_checks(many)
        report = self.report()
        self.assertEqual(reader_checks.MAX_COMMANDS, report["listed"])
        self.assertEqual([reader_checks.COUNT_REASON] * 5, [i["reason"] for i in report["ignored"]])
        projects = {f"/p/{i}": [BAZEL] for i in range(reader_checks.MAX_PROJECTS + 3)}
        self.list_checks(projects)
        report = self.report()
        self.assertEqual(reader_checks.MAX_PROJECTS, report["projects"])
        self.assertEqual(3, report["projects_dropped"])
        self.assertIn("3", diagnostics.render_reader_checks(report))
        long_entry = "make " + "x" * reader_checks.MAX_COMMAND_CHARS
        self.list_checks({str(self.cwd): [long_entry]})
        self.assertEqual(0, self.report()["listed"])
        self.assertEqual(1, len(self.report()["ignored"]))

    def test_a_version_key_is_neither_required_nor_read(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(
            json.dumps({"v": 9, "projects": {str(self.cwd): [BAZEL]}}), encoding="utf-8"
        )
        self.assertEqual(1, self.report()["listed"])


class ASessionThatWroteTheFileIsFlaggedAndNothingCounts(ReaderChecksTestCase):
    def test_a_recorded_write_withdraws_the_listing_and_the_scan_says_so(self) -> None:
        self.list_checks()
        self.session.write(str(self.store), "{}")
        self.session.bash(BAZEL, "ok")
        events, scan = self.read()
        self.assertEqual([], [e for e in events if e["subject"] == "check"])
        self.assertIs(True, scan["reader_checks_written"])

    def test_a_shell_command_naming_the_file_withdraws_the_listing_too(self) -> None:
        for command in (
            f"echo hi > {self.store}",
            f"cp /tmp/x {self.store}",
            f"echo hi | tee {self.store}",
        ):
            with self.subTest(command=command):
                self.session.rows.clear()
                self.list_checks()
                self.session.bash(command)
                self.session.bash(BAZEL, "ok")
                events, scan = self.read()
                self.assertEqual([], [e for e in events if e["subject"] == "check"])
                self.assertIs(True, scan["reader_checks_written"])

    def test_a_read_only_command_naming_the_file_does_not_withdraw_the_listing(self) -> None:
        for command in (
            f"cat {self.store}",
            f"grep bazel {self.store}",
            f"rg bazel {self.store}",
            f"head -5 {self.store}",
            f"less {self.store}",
            f"wc -l {self.store}",
            f"ls -l {self.store} && cat {self.store} | wc -l",
        ):
            with self.subTest(command=command):
                self.session.rows.clear()
                self.list_checks()
                self.session.bash(command)
                self.session.bash(BAZEL, "ok")
                events, scan = self.read()
                self.assertEqual([BAZEL], [e["title"] for e in events if e["subject"] == "check"])
                self.assertNotIn("reader_checks_written", scan)

    def test_a_read_that_redirects_into_the_file_is_still_a_write(self) -> None:
        self.list_checks()
        self.session.bash(f"cat other.json > {self.store}")
        self.session.bash(BAZEL, "ok")
        events, scan = self.read()
        self.assertEqual([], [e for e in events if e["subject"] == "check"])
        self.assertIs(True, scan["reader_checks_written"])

    def test_an_interpreter_or_editor_naming_the_file_withdraws_the_listing(self) -> None:
        for command in (
            f"python3 -c \"open('{self.store}', 'w').write('{{}}')\"",
            f"node -e \"require('fs').writeFileSync('{self.store}', '{{}}')\"",
            f"perl -pi -e 's/bazel/true/' {self.store}",
            f"ruby -i -pe '$_.upcase!' {self.store}",
        ):
            with self.subTest(command=command):
                self.session.rows.clear()
                self.list_checks()
                self.session.bash(command)
                self.session.bash(BAZEL, "ok")
                events, scan = self.read()
                self.assertEqual([], [e for e in events if e["subject"] == "check"])
                self.assertIs(True, scan["reader_checks_written"])

    def test_a_write_with_nothing_listed_is_not_flagged(self) -> None:
        self.session.write(str(self.cwd / reader_checks.FILENAME), "{}")
        self.session.bash("pytest -q", "1 passed in 0.1s")
        self.assertNotIn("reader_checks_written", self.read()[1])

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


class AListedScriptThePathNamesNeedsTheProjectRootAndAnUntouchedFile(ReaderChecksTestCase):
    SCRIPT = "./check.sh"

    def test_the_script_run_from_the_project_root_counts(self) -> None:
        self.list_checks({str(self.cwd): [self.SCRIPT]})
        self.session.bash(self.SCRIPT, "ok")
        self.assertEqual([self.SCRIPT], self.titles())

    def test_a_script_the_session_wrote_or_edited_does_not_count(self) -> None:
        self.list_checks({str(self.cwd): [self.SCRIPT]})
        self.session.write(str(self.cwd / "check.sh"), "exit 0")
        self.session.bash(self.SCRIPT, "ok")
        self.assertEqual([], self.titles())

    def test_a_script_the_shell_wrote_does_not_count(self) -> None:
        for command in ("echo 'exit 0' > check.sh", "cp /tmp/x check.sh", "chmod +x check.sh"):
            with self.subTest(command=command):
                self.session.rows.clear()
                self.list_checks({str(self.cwd): [self.SCRIPT]})
                self.session.bash(command)
                self.session.bash(self.SCRIPT, "ok")
                self.assertEqual([], self.titles())

    def test_an_interpreter_that_names_the_script_in_its_code_withdraws_it(self) -> None:
        for command in (
            "python3 -c \"open('check.sh', 'w').write('exit 0')\"",
            "node -e \"require('fs').writeFileSync('check.sh', 'exit 0')\"",
            "perl -pi -e 's/a/b/' check.sh",
            "ruby -i -pe '$_.upcase!' ./check.sh",
        ):
            with self.subTest(command=command):
                self.session.rows.clear()
                self.list_checks({str(self.cwd): [self.SCRIPT]})
                self.session.bash(command)
                self.session.bash(self.SCRIPT, "ok")
                self.assertEqual([], self.titles())

    def test_reading_or_running_the_script_leaves_it_listed(self) -> None:
        for command in ("cat check.sh", "grep exit check.sh", "head -3 ./check.sh", "wc -l check.sh",
                        "./check.sh --fast", "bash check.sh", "ls -l check.sh"):  # fmt: skip
            with self.subTest(command=command):
                self.session.rows.clear()
                self.list_checks({str(self.cwd): [self.SCRIPT]})
                self.session.bash(command, "ok")
                self.session.bash(self.SCRIPT, "ok")
                self.assertEqual([self.SCRIPT], self.titles())

    def test_a_script_run_in_another_folder_does_not_count(self) -> None:
        self.list_checks({str(self.cwd): [self.SCRIPT]})
        self.session.bash(f"cd {self.root / 'elsewhere'} && {self.SCRIPT}", "ok")
        self.assertEqual([], self.titles())

    def test_a_script_run_from_a_linked_worktree_root_counts(self) -> None:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "x",
            "GIT_AUTHOR_EMAIL": "x@x",
            "GIT_COMMITTER_NAME": "x",
            "GIT_COMMITTER_EMAIL": "x@x",
        }
        repo = self.root / "wtrepo"
        repo.mkdir()
        worktree = self.root / "wtree"
        for args, where in (
            (["init", "-q"], repo),
            (["commit", "-q", "--allow-empty", "-m", "i"], repo),
            (["worktree", "add", "-q", str(worktree)], repo),
        ):
            subprocess.run(
                ["/usr/bin/git", *args], cwd=where, check=True, capture_output=True, env=env
            )
        for label, began in (("main", repo), ("worktree", worktree), ("subdir", worktree / "pkg")):
            with self.subTest(began=label):
                (worktree / "pkg").mkdir(exist_ok=True)
                self.session = type(self.session)(began)
                self.session.prompt("go")
                self.list_checks({str(repo): [self.SCRIPT]})
                self.session.bash(self.SCRIPT, "ok")
                self.assertEqual([] if label == "subdir" else [self.SCRIPT], self.titles())

    def test_a_program_on_the_path_still_counts_from_any_folder(self) -> None:
        self.list_checks()
        self.session.bash(f"cd {self.root / 'elsewhere'} && {BAZEL}", "ok")
        self.assertEqual([BAZEL], self.titles())


class EveryReaderOfTheListingAgrees(ReaderChecksTestCase):
    def test_a_paged_read_withdraws_the_listing_a_session_wrote_as_a_whole_read_does(self) -> None:
        self.list_checks()
        self.session.write(str(self.store), "{}")
        for _ in range(30):
            self.session.bash("ls", "a b c")
        self.session.bash(BAZEL, "ok")
        self.session.save(self.path)
        whole = session_source.read(
            self.config, str(self.path), "claude", "root", max_bytes=self.path.stat().st_size * 4
        )
        self.assertEqual([], [e.title for e in whole.entries if e.kind == "check"])
        size = self.path.stat().st_size
        cursor = None
        pages = 0
        found: list[str] = []
        while True:
            page = session_source.read(
                self.config, str(self.path), "claude", "root", after=cursor, max_bytes=size // 4
            )
            pages += 1
            found.extend(e.title for e in page.entries if e.kind == "check")
            cursor = page.next
            if cursor is None or pages > 40:
                break
        self.assertGreater(pages, 2)
        self.assertEqual([], found)


class ACallIsParsedOnceWhenAScriptIsListed(ReaderChecksTestCase):
    def test_every_bash_call_is_parsed_once_not_twice(self) -> None:
        self.list_checks({str(self.cwd): ["./check.sh"]})
        commands = [f"echo {i} && ls" for i in range(6)] + ["cat check.sh", "cd . && ./check.sh"]
        for command in commands:
            self.session.bash(command, "ok")
        project_context._call_parts_once.cache_clear()
        real = project_context._call_parts
        seen: list[str] = []

        def counting(text: str, depth: int = 0) -> Any:
            seen.append(text)
            return real(text, depth)

        with mock.patch.object(project_context, "_call_parts", side_effect=counting):
            self.read()
        # The call parts of one call are the same text, so they are parsed once for every
        # reader of it; before, the script-name scan parsed each call a second time.
        self.assertEqual(sorted(commands), sorted(c for c in seen if c in commands))


class APagedReadKeepsAnEarlierPagesListingWrite(ReaderChecksTestCase):
    def test_a_page_with_nothing_listed_carries_the_earlier_write_forward(self) -> None:
        self.session.bash("ls", "a")
        self.session.save(self.path)
        first = session_source.read(self.config, str(self.path), "claude", "root")
        assert first.snapshot is not None
        cursor = dataclasses.replace(
            first.snapshot.cursor, listing_writes=frozenset({reader_checks.FILENAME})
        )
        self.session.bash("ls", "b")
        self.session.save(self.path)
        empty = project_scripts.Declarations("", "", {}, {}, {})
        with mock.patch.object(project_context, "_declared_scripts", return_value=empty):
            second = session_source.read(
                self.config, str(self.path), "claude", "root", after=cursor
            )
        assert second.snapshot is not None
        self.assertEqual(frozenset({reader_checks.FILENAME}), second.snapshot.cursor.listing_writes)
