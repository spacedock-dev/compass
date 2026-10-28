"""A `consistent` that rests on evidence which cannot support it, run against marks fixed first.

`scripts/premarked_cases.py` holds the case table. A different agent wrote
`docs/abstention/premarked-false-consistent-marks.json` from the descriptions and the written
rulings alone, before any case was run, and the digest of those marks was committed before this
file existed. Each case below is fed to the real reader through a model that answers `consistent`
and cites every row of the ledger: whatever the server leaves standing is the server's doing.

Nothing here calls a model, `gh` or `glab`. Every repository, branch, commit and command is
synthetic.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))

import premarked_cases
from compass_runtime import ci_read, project_context, reading

from . import test_reading as base
from .test_ci_read import GREEN, record_with
from .test_claude_checks import SHORT, START, ClaudeChecksTestCase

ROOT = Path(__file__).resolve().parents[4]
EPOCH = START.timestamp()
# The marks and the digest are read from the working copy; the order test reads history.
MARKS_FILE = Path(premarked_cases.MARKS_PATH)
DIGEST_FILE = Path(premarked_cases.DIGEST_PATH)
TEST_FILE = Path(__file__).resolve()


def committed_marks() -> dict[str, str]:
    body = json.loads(MARKS_FILE.read_text(encoding="utf-8"))
    return cast("dict[str, str]", body["marks"])


def facts_of(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        project_context._semantic_fact_from_event(dict(row), str(row["kind"]), "tool_report", "")
        for row in entries
    ]


class TheCommittedMarksAreTheOnesRun(unittest.TestCase):
    def test_the_digest_file_binds_the_marks_and_the_table(self) -> None:
        digest = json.loads(DIGEST_FILE.read_text(encoding="utf-8"))
        self.assertEqual(
            hashlib.sha256(MARKS_FILE.read_bytes()).hexdigest(), digest["marks_digest"]
        )
        self.assertEqual(premarked_cases.cases_digest(), digest["cases_digest"])
        self.assertEqual(len(premarked_cases.CASES), digest["cases"])
        self.assertEqual(digest["cases"], digest["marked"])

    def test_every_case_has_one_mark_from_the_closed_set(self) -> None:
        self.assertEqual([], premarked_cases.marks_problems({"v": 1, "marks": committed_marks()}))

    def test_every_class_has_a_case_and_every_case_has_a_fixture(self) -> None:
        by_class = {case["class"] for case in premarked_cases.CASES}
        self.assertEqual(set(premarked_cases.CLASSES), by_class)
        self.assertEqual(
            {case["id"] for case in premarked_cases.CASES}, set(premarked_cases.FIXTURES)
        )

    def test_the_marks_were_committed_before_this_test(self) -> None:
        if shutil.which("git") is None:
            self.skipTest("git is not available")

        def git(*args: str) -> list[str]:
            found = subprocess.run(
                ["git", "-C", str(ROOT), *args],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )
            return found.stdout.split() if found.returncode == 0 else []

        def first_commit(path: Path) -> str:
            added = git("log", "--diff-filter=A", "--format=%H", "--", str(path))
            return added[-1] if added else ""

        marks, digest, head = (first_commit(p) for p in (MARKS_FILE, DIGEST_FILE, TEST_FILE))
        if not (marks and digest and head):
            self.skipTest("the marks are not in a git history here")
        # The reference is the commit that first added this test, so a later edit to the marks
        # cannot move it. A squash merge puts all three in one commit, which is its own ancestor.
        for first in (marks, digest):
            ordered = subprocess.run(
                ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", first, head],  # noqa: S607
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, ordered.returncode, "the marks must precede the test")


class AnAlwaysConsistentModelFindsNoFalseSupport(ClaudeChecksTestCase):
    """Per case: the outcome the server leaves equals the mark written before the run."""

    def setUp(self) -> None:
        super().setUp()
        self.prompts: list[str] = []
        self.cited: list[list[int]] = []
        state = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, state, True)
        self.reader_config = base.WhatOnePressActuallyCostsAndProduces._Config()
        self.reader_config.state_dir = state  # type: ignore[attr-defined]

    def _read_with(
        self,
        case: dict[str, str],
        facts: list[dict[str, Any]],
        *,
        words_at: float,
        window_at: float,
        now: float,
        ci: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """One reading whose model says `consistent` for the case's constraint, citing every row."""
        words = {
            **base.WORDS_FACT,
            "at": words_at,
            "source_session": {"harness": "claude", "sid": SHORT},
        }
        every_fact = [words, *facts]
        if ci is not None:
            every_fact += ci_read.facts(ci, "claude", SHORT)
        constraint = case["constraint"]
        revision: dict[str, Any] = {"n": 1, "at": window_at}
        if constraint == "goal":
            revision.update(goal=case["words"], lines=[])
        else:
            revision.update(goal="Guard the widget form.", lines=[case["words"]])

        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            self.prompts.append(prompt)
            cites = [int(n) for n in re.findall(r"^\[(\d+)\]", prompt, re.MULTILINE)]
            self.assertTrue(cites, case["name"])
            self.cited.append(cites)
            answer = {constraint: {"result": "consistent", "cites": cites, "detail": ""}}
            return json.dumps(answer), "ok"

        assessment, why, _spent = reading.produce(
            cast("Any", self.reader_config),
            {"harness": "claude", "sid": SHORT, "state": "working", "ended_at": None},
            [revision],
            [words, *facts],
            now=now,
            stamp_text="read at 10:00",
            model=model,
            tool_output=reading.ToolOutput(destination="Anthropic", label="Claude Code"),
            read_lines=True,
            read_agent_words=True,
            ci=ci,
        )
        self.assertEqual("", why, case["name"])
        criteria = cast("dict[str, Any]", assessment)["criteria"]
        return cast("dict[str, Any]", criteria[constraint])

    def _commands(self, case: dict[str, str], fixture: dict[str, Any]) -> dict[str, Any]:
        self.session.prompt(premarked_cases.BRANCH)
        # A command that records no fact would leave nothing in the window, and the press is then
        # withheld before any model runs. A written file keeps it open. It must come first: a write
        # after the command ages every command check, and each case would then be withdrawn
        # whatever rule is under test.
        self.session.write(self.file("src/guard.py"))
        for command in fixture["commands"]:
            self.session.bash(command, "all checks passed", is_error=False)
        if fixture.get("pr"):
            pull = f"https://github.com/{premarked_cases.REPO}/pull/{fixture['pr']}"
            self.goal_texts = (f"Land {pull}",)
        entries, _scan = self.read()
        # What the collector made of the command is half the claim: a command that cannot fail is
        # never listed at all, and the others are listed with the resolver's withdrawal on them.
        listed = [e for e in entries if e["subject"] in {"command", "ci_command"}]
        if case["class"] == premarked_cases.COMMAND_CANNOT_FAIL:
            self.assertEqual([], listed, case["name"])
        else:
            self.assertEqual(len(fixture["commands"]), len(listed), case["name"])
            self.assertTrue(all(e["cannot_fail"] is True for e in listed), case["name"])
        return self._read_with(
            case,
            facts_of(entries),
            words_at=EPOCH + 1,
            window_at=EPOCH + 2,
            now=EPOCH + 3600,
            ci=None,
        )

    def _ci(self, case: dict[str, str], fixture: dict[str, Any]) -> dict[str, Any]:
        spec = fixture["ci"]
        record = record_with(
            *GREEN,
            head_matches=bool(spec["head_matches"]),
            caution=ci_read.changed_ci_configuration(fixture.get("edited", [])),
        )
        return self._read_with(case, [], words_at=90.0, window_at=50.0, now=200.0, ci=record)

    def test_each_case_ends_as_its_mark_says(self) -> None:
        marks = committed_marks()
        for case in premarked_cases.CASES:
            fixture = premarked_cases.FIXTURES[case["id"]]
            with self.subTest(case=case["name"]):
                self.setUp()
                row = self._ci(case, fixture) if "ci" in fixture else self._commands(case, fixture)
                outcome = (
                    "withdrawn"
                    if row["result"] == reading.RESULT_UNVERIFIABLE
                    else "caution-kept"
                    if row["result"] == reading.RESULT_CONSISTENT
                    else row["result"]
                )
                self.assertEqual(marks[case["id"]], outcome)

    def test_a_workflow_edit_keeps_its_caution_in_the_prompt(self) -> None:
        (case,) = (c for c in premarked_cases.CASES if c["name"] == "ci-after-workflow-edit")
        self._ci(case, premarked_cases.FIXTURES[case["id"]])
        self.assertIn(ci_read.CAUTION_TEXT, self.prompts[0])

    def test_a_case_that_withdraws_carries_no_caution_it_did_not_earn(self) -> None:
        (case,) = (c for c in premarked_cases.CASES if c["name"] == "ci-other-head")
        self._ci(case, premarked_cases.FIXTURES[case["id"]])
        self.assertNotIn(ci_read.CAUTION_TEXT, self.prompts[0])

    def test_the_workflow_edit_case_edits_ci_configuration_and_the_others_do_not(self) -> None:
        for case in premarked_cases.CASES:
            fixture = premarked_cases.FIXTURES[case["id"]]
            self.assertEqual(
                case["name"] == "ci-after-workflow-edit",
                ci_read.changed_ci_configuration(fixture.get("edited", [])),
                case["name"],
            )

    def test_controls_that_can_pass_are_left_standing(self) -> None:
        """Without the aging write in the way, a real passing command is kept: the withdrawal in
        the cases is the rule under test, not a side effect of the setup."""
        case = {
            "name": "control",
            "constraint": "line_1",
            "words": "The tests pass.",
            "class": premarked_cases.COMMAND_CANNOT_FAIL,
        }
        pull = f"https://github.com/{premarked_cases.REPO}/pull/7"
        for command, pr in (("pytest tests", None), ("gh pr checks 7", 7), ("gh pr checks 99", 7)):
            with self.subTest(command=command):
                self.setUp()
                self.session.prompt(premarked_cases.BRANCH)
                self.session.write(self.file("src/guard.py"))
                self.session.bash(command, "all checks passed", is_error=False)
                if pr:
                    self.goal_texts = (f"Land {pull}",)
                entries, _scan = self.read()
                row = self._read_with(
                    case,
                    facts_of(entries),
                    words_at=EPOCH + 1,
                    window_at=EPOCH + 2,
                    now=EPOCH + 3600,
                    ci=None,
                )
                expected = (
                    reading.RESULT_UNVERIFIABLE
                    if command.endswith("99")
                    else reading.RESULT_CONSISTENT
                )
                self.assertEqual(expected, row["result"])
