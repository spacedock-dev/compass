"""The version guard's shipped step, run on a pull request and on a merge queue entry."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/version-guard.yml"
BASH = shutil.which("bash")
JQ = shutil.which("jq")
MANIFEST = "compass/.claude-plugin/plugin.json"


def _workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _job() -> dict[str, Any]:
    job = _workflow()["jobs"]["version-guard"]
    assert isinstance(job, dict)
    return job


def _check_step() -> str:
    return str(next(step["run"] for step in _job()["steps"] if "run" in step))


class VersionGuardWiringTest(unittest.TestCase):
    def test_a_queue_entry_reads_the_groups_shas_and_keeps_its_own_concurrency_group(self) -> None:
        workflow = _workflow()
        triggers = workflow.get(True) or workflow["on"]
        self.assertIn("merge_group", triggers)
        # A pull request keeps its number; a queue entry, which has none, falls back to its own
        # unique ref instead of collapsing every entry into one group that cancels the rest.
        self.assertEqual(
            "version-guard-${{ github.event.pull_request.number || github.ref }}",
            workflow["concurrency"]["group"],
        )
        env = _job()["env"]
        head = "${{ github.event.pull_request.head.sha || github.event.merge_group.head_sha }}"
        self.assertEqual(head, env["HEAD_SHA"])
        # The branch the entry lands on, not merge_group.base_sha: that is the head of the entry
        # queued ahead, so diffing from it would check this pull request alone.
        self.assertEqual("${{ github.event.merge_group.base_ref }}", env["GROUP_BASE_REF"])
        self.assertNotIn("GROUP_BASE_SHA", env)
        self.assertEqual("${{ github.event_name }}", env["EVENT"])
        checkout = next(step for step in _job()["steps"] if "uses" in step)
        self.assertEqual(head, checkout["with"]["ref"])
        self.assertEqual(0, checkout["with"]["fetch-depth"])


@unittest.skipUnless(BASH and JQ, "the shipped step needs bash and jq")
class VersionGuardStepTest(unittest.TestCase):
    """Main moves on after the branch point, as it does under a queue, and only a bump fails."""

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="version-guard-"))
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        self.git("init", "-q", "-b", "main")
        self.write_version("1.0.0")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")

    def git(self, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()

    def write_version(self, version: str) -> None:
        path = self.repo / MANIFEST
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"name": "compass", "version": version}) + "\n")

    def commit_change(self, *, bump: bool, number: int = 12) -> str:
        if bump:
            self.write_version("1.0.1")
        (self.repo / "notes.txt").write_text(f"a change for #{number}\n")
        self.git("add", ".")
        self.git("commit", "-qm", f"change (#{number})")
        return self.git("rev-parse", "HEAD")

    def run_step(self, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH or "bash", "-c", _check_step()],
            cwd=self.repo,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def run_queue_entry(self, head: str) -> subprocess.CompletedProcess[str]:
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.git("checkout", "-q", head)
        return self.run_step(
            {"EVENT": "merge_group", "HEAD_SHA": head, "GROUP_BASE_REF": "refs/heads/main"}
        )

    def run_pull_request(self, head: str) -> subprocess.CompletedProcess[str]:
        self.git("update-ref", "refs/remotes/origin/main", self.base)
        self.git("checkout", "-q", head)
        return self.run_step({"EVENT": "pull_request", "HEAD_SHA": head, "GITHUB_BASE_REF": "main"})

    def test_a_queue_entry_without_a_bump_passes(self) -> None:
        result = self.run_queue_entry(self.commit_change(bump=False))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"merge-base ({self.base})", result.stdout)

    def test_a_queue_entry_carrying_a_bump_fails(self) -> None:
        result = self.run_queue_entry(self.commit_change(bump=True))
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("plugin manifest version changed (1.0.0 -> 1.0.1)", result.stdout)

    def test_a_bump_in_an_entry_queued_ahead_fails_the_entry_behind_it(self) -> None:
        # #9 bumps and is queued first; #12 is built on #9's group head. Under a grouping rule
        # that checks only the head of a group, #12 passing would land #9's bump too.
        self.commit_change(bump=True, number=9)
        result = self.run_queue_entry(self.commit_change(bump=False, number=12))
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn(f"merge-base ({self.base})", result.stdout)
        self.assertIn("plugin manifest version changed (1.0.0 -> 1.0.1)", result.stdout)

    def test_a_pull_request_is_judged_as_it_was(self) -> None:
        for bump, code in ((False, 0), (True, 1)):
            with self.subTest(bump=bump):
                self.git("checkout", "-q", "-B", f"topic-{bump}", self.base)
                result = self.run_pull_request(self.commit_change(bump=bump))
                self.assertEqual(code, result.returncode, result.stdout + result.stderr)

    def test_a_queue_entry_with_an_unknown_base_fails_rather_than_passing(self) -> None:
        head = self.commit_change(bump=False)
        self.git("checkout", "-q", head)
        result = self.run_step({"EVENT": "merge_group", "HEAD_SHA": head, "GROUP_BASE_REF": ""})
        self.assertEqual(1, result.returncode)
        self.assertIn("cannot compute merge-base", result.stdout)


if __name__ == "__main__":
    unittest.main()
