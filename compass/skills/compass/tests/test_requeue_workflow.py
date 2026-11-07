"""The re-queue workflow runs with write access on pull request events, so its boundary is pinned.

`pull_request_target` hands a write token and secrets to a run a pull request starts. These tests
hold what makes that safe here: only the default branch's own files are checked out, every action
is pinned to a commit, a fork is skipped, no field a pull request author writes reaches a script,
nothing is restored from a cache or another run, and the enqueue credential sits alone in a job
that checks out nothing and passes on only a fixed failure name. When that enqueue fails, a third
job, with the ordinary token and never the secret, corrects the comment.
scripts/tests/test_requeue_after_ejection.py tests the decision and the correction themselves.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

import yaml

from .test_workflow_caches import holds_write_credential, restores_a_cache

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/requeue-after-ejection.yml"
SCRIPT = "scripts/requeue_after_ejection.py"
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
# Fields of a pull_request event that its author, or anyone who can push a branch, chooses.
AUTHORED = ("title", "body", "head.ref", "head.label", "user.login", "labels", "commits")


def workflow() -> dict[Any, Any]:
    return cast("dict[Any, Any]", yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))


def triggers() -> dict[str, Any]:
    # PyYAML reads the bare key `on` as the boolean True.
    found = workflow()
    return cast("dict[str, Any]", found.get("on", found.get(True)))


def jobs() -> dict[str, dict[str, Any]]:
    return cast("dict[str, dict[str, Any]]", workflow()["jobs"])


def steps(job: str) -> list[dict[str, Any]]:
    return cast("list[dict[str, Any]]", jobs()[job]["steps"])


class TriggerTest(unittest.TestCase):
    def test_it_runs_on_a_dequeue_alone_from_the_default_branch(self) -> None:
        self.assertEqual({"pull_request_target": {"types": ["dequeued"]}}, triggers())

    def test_each_pull_request_runs_one_at_a_time_and_none_is_cancelled(self) -> None:
        concurrency = workflow()["concurrency"]
        self.assertIn("github.event.pull_request.number", concurrency["group"])
        self.assertIs(False, concurrency["cancel-in-progress"])

    def test_forks_and_other_bases_are_skipped(self) -> None:
        for job in ("decide", "report"):
            with self.subTest(job=job):
                condition = " ".join(jobs()[job]["if"].split())
                self.assertIn(
                    "github.event.pull_request.head.repo.full_name == github.repository", condition
                )
                self.assertIn(
                    "github.event.pull_request.base.ref == github.event.repository.default_branch",
                    condition,
                )
                self.assertIn("&&", condition)
                self.assertNotIn("||", condition)

    def test_the_report_runs_only_when_a_requeue_was_tried_and_did_not_land(self) -> None:
        report = jobs()["report"]
        self.assertEqual(["decide", "enqueue"], report["needs"])
        condition = " ".join(report["if"].split())
        # always(): a failed enqueue would otherwise skip every job that needs it.
        self.assertTrue(condition.startswith("always() && "))
        self.assertIn("needs.decide.outputs.action == 'requeue'", condition)
        self.assertIn("needs.enqueue.result != 'success'", condition)

    def test_the_enqueue_waits_for_a_requeue_decision(self) -> None:
        enqueue = jobs()["enqueue"]
        self.assertEqual("decide", enqueue["needs"])
        self.assertEqual("needs.decide.outputs.action == 'requeue'", enqueue["if"])


class PermissionsTest(unittest.TestCase):
    def test_the_default_token_starts_with_nothing(self) -> None:
        self.assertEqual({}, workflow()["permissions"])

    def test_each_job_holds_only_what_it_uses(self) -> None:
        self.assertEqual(
            {"contents": "read", "pull-requests": "write", "actions": "read"},
            jobs()["decide"]["permissions"],
        )
        self.assertEqual({}, jobs()["enqueue"]["permissions"])
        self.assertEqual(
            {"contents": "read", "pull-requests": "write", "actions": "read"},
            jobs()["report"]["permissions"],
        )

    def test_the_enqueue_credential_is_used_in_one_step_of_one_job(self) -> None:
        # Every expression naming a secret, anywhere in the file: an env key, a job-level or
        # workflow-level env, or a `with:` would each add one.
        named = [
            " ".join(expression.split())
            for expression in EXPRESSION.findall(WORKFLOW.read_text(encoding="utf-8"))
            if "secrets" in expression
        ]
        self.assertEqual(["secrets.MERGE_QUEUE_TOKEN != ''", "secrets.MERGE_QUEUE_TOKEN"], named)
        self.assertEqual(
            "${{ secrets.MERGE_QUEUE_TOKEN }}",
            steps("enqueue")[0]["env"]["GH_TOKEN"],
        )
        # `decide` learns only whether it is set, as a boolean expression.
        self.assertEqual(
            "${{ secrets.MERGE_QUEUE_TOKEN != '' }}", steps("decide")[1]["env"]["QUEUE_TOKEN_SET"]
        )

    def test_env_is_set_only_on_steps(self) -> None:
        # A workflow-level or job-level env reaches every step beneath it.
        self.assertNotIn("env", workflow())
        for job_id, job in jobs().items():
            with self.subTest(job=job_id):
                self.assertNotIn("env", job)

    def test_the_enqueue_job_runs_plain_gh_and_checks_out_nothing(self) -> None:
        (only,) = steps("enqueue")
        self.assertNotIn("uses", only)
        self.assertIn('gh api graphql -f query="$ENQUEUE"', only["run"])
        self.assertIn("expectedHeadOid", only["env"]["ENQUEUE"])

    def test_the_enqueue_job_passes_on_only_a_fixed_failure_name(self) -> None:
        (only,) = steps("enqueue")
        self.assertEqual(
            {"failure": "${{ steps.enqueue.outputs.failure }}"}, jobs()["enqueue"]["outputs"]
        )
        self.assertEqual("enqueue", only["id"])
        written = set(re.findall(r"\bfailure=([a-z-]+)", only["run"]))
        self.assertEqual({"token-rejected", "token-forbidden", "other"}, written)
        self.assertEqual(1, only["run"].count('>> "$GITHUB_OUTPUT"'))


class NoPullRequestCodeTest(unittest.TestCase):
    def test_every_action_is_pinned_to_a_commit(self) -> None:
        for job_id in jobs():
            for step in steps(job_id):
                if "uses" in step:
                    with self.subTest(job=job_id, step=step["uses"]):
                        self.assertRegex(step["uses"], PINNED)

    def test_the_only_checkout_is_the_default_branchs_script(self) -> None:
        checkouts = [
            (job_id, step)
            for job_id in jobs()
            for step in steps(job_id)
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        self.assertEqual(["decide", "report"], [job_id for job_id, _ in checkouts])
        for job_id, step in checkouts:
            with self.subTest(job=job_id):
                options = step["with"]
                # Under pull_request_target, github.sha is the base branch's tip, held to the
                # default branch by the job's condition. A head ref or SHA here would run the pull
                # request's code.
                self.assertEqual("${{ github.sha }}", options["ref"])
                self.assertIs(False, options["persist-credentials"])
                self.assertEqual(SCRIPT, options["sparse-checkout"])
                self.assertNotIn("repository", options)

    def test_the_script_runs_isolated_from_the_checkout(self) -> None:
        self.assertEqual(f"python3 -I {SCRIPT}", steps("decide")[1]["run"])
        self.assertEqual(f"python3 -I {SCRIPT} --report-failed-enqueue", steps("report")[1]["run"])

    def test_nothing_is_restored_from_a_cache_or_another_run(self) -> None:
        for job_id, job in jobs().items():
            self.assertTrue(holds_write_credential(workflow(), job), job_id)
            for step in steps(job_id):
                with self.subTest(job=job_id, step=step.get("name") or step.get("uses")):
                    self.assertFalse(restores_a_cache(step))
                    self.assertNotIn("download-artifact", step.get("uses", ""))


class NoAuthoredFieldReachesAScriptTest(unittest.TestCase):
    def test_no_run_block_interpolates_an_expression(self) -> None:
        for job_id in jobs():
            for step in steps(job_id):
                if "run" in step:
                    with self.subTest(job=job_id, step=step.get("name")):
                        self.assertNotIn("${{", step["run"])

    def test_no_authored_field_is_read_anywhere(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        for expression in EXPRESSION.findall(text):
            for field in AUTHORED:
                with self.subTest(expression=expression.strip(), field=field):
                    self.assertNotIn(f"pull_request.{field}", expression)

    def test_what_reaches_the_scripts_is_numbers_shas_and_github_s_own_values(self) -> None:
        # Keyed by where each value lands, so the right value under the wrong job or key fails.
        passed = {
            (job_id, step.get("name"), key): value
            for job_id in jobs()
            for step in steps(job_id)
            for key, value in step.get("env", {}).items()
            if "${{" in value
        }
        decide = "Decide"
        enqueue = "Put it back in the queue"
        report = "Say it was not re-queued"
        self.assertEqual(
            {
                ("decide", decide, "GH_TOKEN"): "${{ github.token }}",
                ("decide", decide, "REPO"): "${{ github.repository }}",
                ("decide", decide, "PR_NUMBER"): "${{ github.event.pull_request.number }}",
                ("decide", decide, "HEAD_SHA"): "${{ github.event.pull_request.head.sha }}",
                # Held to the default branch by the job's condition before the step runs.
                ("decide", decide, "BASE_REF"): "${{ github.event.pull_request.base.ref }}",
                ("decide", decide, "EVENT_REASON"): "${{ github.event.reason }}",
                ("decide", decide, "QUEUE_TOKEN_SET"): "${{ secrets.MERGE_QUEUE_TOKEN != '' }}",
                ("enqueue", enqueue, "GH_TOKEN"): "${{ secrets.MERGE_QUEUE_TOKEN }}",
                ("enqueue", enqueue, "PR_NODE_ID"): "${{ github.event.pull_request.node_id }}",
                ("enqueue", enqueue, "HEAD_SHA"): "${{ github.event.pull_request.head.sha }}",
                ("report", report, "GH_TOKEN"): "${{ github.token }}",
                ("report", report, "REPO"): "${{ github.repository }}",
                ("report", report, "PR_NUMBER"): "${{ github.event.pull_request.number }}",
                ("report", report, "HEAD_SHA"): "${{ github.event.pull_request.head.sha }}",
                ("report", report, "BASE_REF"): "${{ github.event.pull_request.base.ref }}",
                # Written by decide (a number from GitHub's answer) and enqueue (a fixed name).
                ("report", report, "COMMENT_ID"): "${{ needs.decide.outputs.comment_id }}",
                ("report", report, "ENQUEUE_FAILURE"): "${{ needs.enqueue.outputs.failure }}",
                ("report", report, "RUN_URL"): (
                    "${{ github.server_url }}/${{ github.repository }}"
                    "/actions/runs/${{ github.run_id }}"
                ),
            },
            passed,
        )


@unittest.skipUnless(shutil.which("bash"), "the enqueue step is a bash script")
class EnqueueStepTest(unittest.TestCase):
    """The enqueue step's own shell, run against a gh that answers the way GitHub did."""

    def run_step(self, answer: str, status: int) -> tuple[int, str]:
        (step,) = steps("enqueue")
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake = bin_dir / "gh"
            fake.write_text(
                f"#!/usr/bin/env bash\nprintf '%s\\n' {answer!r} >&2\nexit {status}\n",
                encoding="utf-8",
            )
            fake.chmod(0o755)
            script = Path(tmp) / "step.sh"
            script.write_text(step["run"], encoding="utf-8")
            output = Path(tmp) / "output"
            output.touch()
            env = {
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
                "GITHUB_OUTPUT": str(output),
                "ENQUEUE": step["env"]["ENQUEUE"],
                "PR_NODE_ID": "PR_node",
                "HEAD_SHA": "a" * 40,
            }
            # GitHub runs a step with `bash -e`, so the failure must be caught inside it.
            ran = subprocess.run(
                ["bash", "-e", str(script)],  # noqa: S607 - bash from PATH
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            return ran.returncode, output.read_text(encoding="utf-8")

    def test_a_rejected_token_is_named_and_fails_the_job(self) -> None:
        self.assertEqual(
            (1, "failure=token-rejected\n"), self.run_step("gh: Bad credentials (HTTP 401)", 1)
        )

    def test_a_token_without_the_permission_is_named(self) -> None:
        answer = "GraphQL: Resource not accessible by personal access token (enqueuePullRequest)"
        self.assertEqual((1, "failure=token-forbidden\n"), self.run_step(answer, 1))
        self.assertEqual(
            (1, "failure=token-forbidden\n"), self.run_step("gh: Forbidden (HTTP 403)", 1)
        )

    def test_a_rate_limit_is_not_called_a_permission_problem(self) -> None:
        # GitHub answers a rate limit with HTTP 403 too; it says nothing about the token.
        answer = "gh: API rate limit exceeded for user ID 1. (HTTP 403)"
        self.assertEqual((1, "failure=other\n"), self.run_step(answer, 1))

    def test_any_other_failure_is_other(self) -> None:
        answer = "GraphQL: Head ref has been modified since the pull request was last fetched"
        self.assertEqual((1, "failure=other\n"), self.run_step(answer, 1))

    def test_a_queued_pull_request_writes_no_failure(self) -> None:
        self.assertEqual((0, ""), self.run_step('{"data": {}}', 0))


if __name__ == "__main__":
    unittest.main()
