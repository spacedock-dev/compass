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
# The recorded-result share the corpus gives today: 5 of its 6 foreground check runs carry a result.
# A floor, not a pin: a change that reads more of these runs may raise it, and none may lower it.
RECORDED_SHARE_FLOOR = Fraction(5, 6)


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
            {"passed": 4, "failed": 1, "not_recorded": 1, "background": 1, "foreground": 6},
            {
                key: runs[key]
                for key in ("passed", "failed", "not_recorded", "background", "foreground")
            },
        )

    def test_a_blank_withheld_reason_is_counted_as_no_token(self) -> None:
        self.assertEqual({"no token": 1}, self.report["withheld_by_reason"])

    def test_unclassified_heads_are_first_words_or_a_tool_and_its_subcommand(self) -> None:
        heads = {row["head"]: row["count"] for row in self.report["top_unclassified_heads"]}
        self.assertEqual(2, heads["terraform plan"])
        self.assertEqual(1, heads["make deploy"])
        self.assertNotIn("pytest", " ".join(heads))
        self.assertNotIn("git log", heads)

    def test_the_output_rewriting_hook_is_seen(self) -> None:
        self.assertEqual(
            {"present": True, "records": 1, "sessions": 1}, self.report["output_rewriting_hook"]
        )

    def test_the_text_report_carries_every_figure(self) -> None:
        text = command_coverage.render(self.report)
        for expected in (
            "sessions with Bash",
            "closed-list check",
            "polling CI",
            "not recorded 1",
            "background 1",
            "83.3%",
            "no token",
            "terraform plan",
            "PreToolUse hook present",
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


class TheCommandLine(unittest.TestCase):
    def _run(self, *argv: str) -> tuple[int, str]:
        lines: list[str] = []
        code = command_coverage.main(list(argv), say=lines.append)
        return code, "\n".join(lines)

    def test_json_output_parses(self) -> None:
        code, out = self._run("--dir", str(CORPUS), "--json")
        self.assertEqual(0, code)
        self.assertEqual(3, json.loads(out)["sessions_with_bash"])

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
