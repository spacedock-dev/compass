"""The command-coverage report: its figures on a synthetic corpus, and what it never prints.

Every transcript under `fixtures/command_coverage/` is invented (acme-style paths, fake credentials).
No real transcript and no real command head belongs in this repository.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import command_coverage

CORPUS = Path(__file__).resolve().parent / "fixtures" / "command_coverage"
# The recorded-result share the corpus gives today: 6 of its 7 foreground check runs carry a result.
# A floor, not a pin: a change that reads more of these runs may raise it, and none may lower it.
RECORDED_SHARE_FLOOR = Fraction(6, 7)


def _report() -> dict[str, Any]:
    return command_coverage.measure(command_coverage.find_transcripts(str(CORPUS)))


class TheFiguresOnTheFixtureCorpus(unittest.TestCase):
    report: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.report = _report()

    def test_subagent_transcripts_are_not_sessions(self) -> None:
        self.assertEqual(4, self.report["transcripts"])
        self.assertEqual(0, self.report["unreadable"])

    def test_sessions_with_bash_with_a_check_and_polling_ci(self) -> None:
        self.assertEqual(3, self.report["sessions_with_bash"])
        self.assertEqual(2, self.report["sessions_with_closed_list_check"])
        self.assertEqual(2, self.report["sessions_polling_ci"])

    def test_check_runs_by_result(self) -> None:
        runs = self.report["check_runs"]
        self.assertEqual(
            {"passed": 5, "failed": 1, "not_recorded": 1, "background": 1, "foreground": 7},
            {
                key: runs[key]
                for key in ("passed", "failed", "not_recorded", "background", "foreground")
            },
        )

    def test_a_subagents_check_run_is_in_the_tally_and_not_in_the_session_counts(self) -> None:
        # `ruff format --check .` runs only in the subagent transcript beside proj-a's parent.
        self.assertEqual(5, self.report["check_runs"]["passed"])
        self.assertEqual(3, self.report["sessions_with_bash"])

    def test_a_blank_withheld_reason_is_counted_as_no_token(self) -> None:
        self.assertEqual({"no token": 1}, self.report["withheld_by_reason"])

    def test_unclassified_heads_are_first_words_or_a_tool_and_its_subcommand(self) -> None:
        heads = {row["head"]: row["count"] for row in self.report["top_unclassified_heads"]}
        self.assertEqual(2, heads["terraform plan"])
        self.assertEqual(1, heads["make"])
        self.assertEqual(1, heads["psql"])
        self.assertEqual(1, heads["terraform apply"])
        self.assertNotIn("pytest", " ".join(heads))
        self.assertNotIn("git log", heads)

    def test_the_output_rewriting_hook_is_seen(self) -> None:
        self.assertEqual(
            {"present": True, "records": 2, "sessions": 2}, self.report["output_rewriting_hook"]
        )

    def test_the_hook_is_seen_as_text_in_stdout_and_as_nested_keys(self) -> None:
        # proj-b carries the shape a real transcript has (the hook's JSON as text in `stdout`);
        # proj-a carries the second accepted form, `updatedInput` as a nested key.
        stdout_form = {
            "type": "attachment",
            "attachment": {
                "hookName": "PreToolUse:Bash",
                "stdout": '{"hookSpecificOutput": {"updatedInput": {"command": "x"}}}',
            },
        }
        nested_form = {
            "type": "attachment",
            "attachment": {
                "hookName": "PreToolUse:Bash",
                "hookSpecificOutput": {"updatedInput": {}},
            },
        }
        plain = {"type": "attachment", "attachment": {"hookName": "PreToolUse:Bash", "stdout": ""}}
        self.assertTrue(command_coverage._is_rewriting_hook(stdout_form))
        self.assertTrue(command_coverage._is_rewriting_hook(nested_form))
        self.assertFalse(command_coverage._is_rewriting_hook(plain))

    def test_the_text_report_carries_every_figure(self) -> None:
        text = command_coverage.render(self.report)
        for expected in (
            "sessions with Bash",
            "closed-list check",
            "polling CI",
            "not recorded 1",
            "background 1",
            "85.7%",
            "no token",
            "terraform plan",
            "present (2 records in 2 sessions)",
        ):
            self.assertIn(expected, text)


class TheRecordedShareFloor(unittest.TestCase):
    def test_the_recorded_result_share_never_falls_below_its_floor(self) -> None:
        # Raise RECORDED_SHARE_FLOOR when a change legitimately reads more results. Lowering it is the
        # regression this test exists to refuse.
        runs = _report()["check_runs"]
        share = Fraction(runs["passed"] + runs["failed"], runs["foreground"])
        self.assertGreaterEqual(share, RECORDED_SHARE_FLOOR)


class WhatTheReportNeverHolds(unittest.TestCase):
    def test_no_argument_and_no_output_text_reaches_either_form(self) -> None:
        report = _report()
        both = json.dumps(report) + command_coverage.render(report)
        for secret in (
            "FakePass99",
            "hunter2db",
            "--password",
            "plan.bin",
            "tests/test_widgets.py",
            "/work/widgets",
        ):
            self.assertNotIn(secret, both)

    def test_a_head_that_is_not_a_name_is_dropped(self) -> None:
        for words in (["/usr/local/bin/tool=FakePass99"], ["a b"], ["x" * 40], ["$(FakePass99)"]):
            self.assertIsNone(command_coverage._head(words), words)
        self.assertEqual("gh pr", command_coverage._head(["gh", "pr", "checks", "12"]))
        self.assertEqual("gh", command_coverage._head(["gh", "FakePass99"]))
        self.assertEqual("git diff", command_coverage._head(["git", "diff", "--stat"]))

    def test_a_lowercase_argument_never_becomes_part_of_a_head(self) -> None:
        for words, expected in (
            (["psql", "hunter2db", "-c", "select 1"], "psql"),
            (["python3", "hunter2", "--x"], "python3"),
            (["curl", "internalhost"], "curl"),
            (["npx", "supersecrettoken"], "npx"),
            (["uv", "run", "hunter2"], "uv run"),
            (["make", "deploy"], "make"),
        ):
            head = command_coverage._head(words)
            self.assertEqual(expected, head, words)
            for argument in ("hunter2", "internalhost", "supersecrettoken", "deploy"):
                self.assertNotIn(argument, head or "")

    def test_a_runner_argument_stripped_by_the_runtime_is_never_the_head(self) -> None:
        import collections  # noqa: PLC0415

        _config, pc = command_coverage._runtime()
        for command, expected in (
            ("npx supersecrettoken", "npx"),
            ("uv run hunter2", "uv run"),
            ("rtk hunter2", "rtk"),
            ("pnpm exec hunter2", "pnpm"),
            ("FOO=1 npx hunter2", "npx"),
            ("rtk git status", "git status"),
        ):
            heads: collections.Counter[str] = collections.Counter()
            call = pc._ShellCall(0.0, "/", {"command": command})  # noqa: SLF001
            command_coverage._count_heads(call, pc, heads)
            self.assertEqual({expected}, set(heads), command)

    def test_prose_that_names_a_ci_command_is_not_a_poll(self) -> None:
        polls = command_coverage._polls_ci
        self.assertTrue(polls(["gh", "pr", "checks", "1"]))
        self.assertTrue(polls(["rtk", "glab", "ci", "status"]))
        self.assertFalse(polls(["echo", "glab ci status"]))
        self.assertFalse(polls(["git", "commit", "-m", "see gh pr checks"]))


class TheCommandLine(unittest.TestCase):
    def _run(self, *argv: str) -> tuple[int, str]:
        lines: list[str] = []
        code = command_coverage.main(list(argv), say=lines.append)
        return code, "\n".join(lines)

    def test_json_output_parses(self) -> None:
        code, out = self._run("--dir", str(CORPUS), "--json")
        self.assertEqual(0, code)
        self.assertEqual(3, json.loads(out)["sessions_with_bash"])

    def test_a_directory_name_with_glob_characters_is_read_literally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp, "dir[1]", "s.jsonl")
            transcript.parent.mkdir()
            transcript.write_text("{}\n", encoding="utf-8")
            self.assertEqual(
                [str(transcript)],
                command_coverage.find_transcripts(str(transcript.parent.parent / "dir[1]")),
            )

    def test_the_figures_line_up(self) -> None:
        lines = command_coverage.render(_report()).splitlines()[:6]
        for line in lines:
            self.assertEqual(" ", line[35], line)
            self.assertNotEqual(" ", line[36], line)

    def test_days_bounds_by_modification_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp, "p", "old.jsonl")
            old.parent.mkdir()
            old.write_text("{}\n", encoding="utf-8")
            stamp = time.time() - 40 * 86400
            os.utime(old, (stamp, stamp))
            self.assertEqual([], command_coverage.find_transcripts(tmp, 30))
            self.assertEqual([str(old)], command_coverage.find_transcripts(tmp, 60))

    def test_a_missing_directory_is_refused(self) -> None:
        code, _out = self._run("--dir", str(CORPUS / "nowhere"))
        self.assertEqual(2, code)

    def test_the_default_corpus_follows_compass_home(self) -> None:
        before = os.environ.get("COMPASS_HOME")
        os.environ["COMPASS_HOME"] = "/elsewhere"
        try:
            self.assertEqual(
                os.path.join("/elsewhere", "drift-replay"), command_coverage.default_dir()
            )
        finally:
            if before is None:
                del os.environ["COMPASS_HOME"]
            else:
                os.environ["COMPASS_HOME"] = before


if __name__ == "__main__":
    unittest.main()
