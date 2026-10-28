"""A merged pull request's checks count when the session's branch holds its merge commit.

Measured 2026-10-28: a burndown's last pull request was squash-merged into `main`, and the session's
folder moved on to later commits. Its head is no commit that folder will ever be on again, so its
three passing required checks read "settle nothing" although what they ran is in the branch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from typing import Any

from compass_runtime import ci_read, git_status

from .test_ci_read import OTHER_HEAD, SESSION_HEAD, StubGh, read

MERGE = "c" * 40


class AMergedPullRequestCounts(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = StubGh(self)

    def merged(self, *, state: str = "MERGED", merge: str = MERGE) -> None:
        answer = {
            "headRefOid": OTHER_HEAD,
            "number": 12,
            "state": state,
            "mergeCommit": {"oid": merge},
        }
        self.stub.set(view={"stdout": json.dumps(answer)})

    def test_merged_by_a_commit_the_branch_holds_counts(self) -> None:
        self.merged()
        asked: list[str] = []

        def contains(commit: str) -> bool:
            asked.append(commit)
            return True

        record = read(self.stub, contains=contains)
        self.assertEqual([MERGE], asked)
        self.assertIs(False, record["head_matches"])
        self.assertIs(True, record["merged_in"])
        facts = ci_read.facts(record, "claude", "s1")
        self.assertTrue(facts)
        # Every pass counts; a skipped check never does, merged or not.
        self.assertTrue(all(fact["ci_counts"] for fact in facts if fact["result"] == "passed"))
        self.assertTrue(all(ci_read.MERGED_IN_TEXT in fact["summary"] for fact in facts))
        self.assertFalse(any(ci_read.HEAD_MOVED_TEXT in fact["summary"] for fact in facts))
        self.assertEqual(record, ci_read.validate(record))

    def test_a_merge_commit_the_branch_does_not_hold_counts_nothing(self) -> None:
        self.merged()
        record = read(self.stub, contains=lambda _commit: False)
        self.assertIs(False, record["merged_in"])
        self.assertFalse(any(fact["ci_counts"] for fact in ci_read.facts(record, "claude", "s1")))

    def test_an_open_pull_request_or_no_question_counts_nothing(self) -> None:
        for state, contains in (("OPEN", lambda _c: True), ("MERGED", None)):
            with self.subTest(state=state, contains=contains):
                self.merged(state=state)
                self.assertIs(False, read(self.stub, contains=contains)["merged_in"])

    def test_a_record_stored_before_the_field_still_reads(self) -> None:
        self.merged()
        record = read(self.stub, contains=lambda _c: False)
        record.pop("merged_in")
        self.assertIs(False, (ci_read.validate(record) or {}).get("merged_in"))

    def test_a_record_cannot_claim_both_or_merged_in_with_no_session_commit(self) -> None:
        self.merged()
        record = read(self.stub, contains=lambda _c: True)
        self.assertIsNone(ci_read.validate({**record, "head_matches": True, "head": SESSION_HEAD}))
        self.assertIsNone(ci_read.validate({**record, "session_head": ""}))


class TheAncestryQuestion(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = tempfile.mkdtemp()
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}

        def git(*args: str) -> str:
            return subprocess.run(
                [shutil.which("git") or "git", *args],
                cwd=self.folder,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        git("init", "-q")
        git(
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "a",
        )
        self.first = git("rev-parse", "HEAD")
        git(
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "b",
        )
        self.second = git("rev-parse", "HEAD")

    def ask(self, commit: str, head: str, **over: Any) -> bool:
        return git_status.is_ancestor(self.folder, commit, head, timeout_sec=10, **over)

    def test_an_ancestor_and_the_head_itself_are_held(self) -> None:
        self.assertTrue(self.ask(self.first, self.second))
        self.assertTrue(self.ask(self.second, self.second))

    def test_a_descendant_or_an_unknown_commit_is_not(self) -> None:
        self.assertFalse(self.ask(self.second, self.first))
        self.assertFalse(self.ask("d" * 40, self.second))

    def test_anything_but_two_commit_ids_starts_no_process(self) -> None:
        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("a process was started")

        for commit, head in (("HEAD", self.second), (self.first, "--all"), ("", self.second)):
            with self.subTest(commit=commit, head=head):
                self.assertFalse(self.ask(commit, head, runner=refuse))
