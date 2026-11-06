"""The re-queue workflow runs with write access on pull request events, so its boundary is pinned.

`pull_request_target` hands a write token and secrets to a run a pull request starts. These tests
hold what makes that safe here: only the default branch's own files are checked out, every action
is pinned to a commit, a fork is skipped, no field a pull request author writes reaches a script,
nothing is restored from a cache or another run, and the enqueue credential sits alone in a job
that checks out nothing. scripts/tests/test_requeue_after_ejection.py tests the decision itself.
"""

from __future__ import annotations

import re
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
        condition = " ".join(jobs()["decide"]["if"].split())
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository", condition
        )
        self.assertIn(
            "github.event.pull_request.base.ref == github.event.repository.default_branch",
            condition,
        )
        self.assertIn("&&", condition)
        self.assertNotIn("||", condition)

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
        self.assertTrue(only["run"].lstrip().startswith("gh api graphql"))
        self.assertIn("expectedHeadOid", only["env"]["ENQUEUE"])


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
        self.assertEqual(["decide"], [job_id for job_id, _ in checkouts])
        options = checkouts[0][1]["with"]
        # Under pull_request_target, github.sha is the base branch's tip, held to the default
        # branch by the job's condition. A head ref or SHA here would run the pull request's code.
        self.assertEqual("${{ github.sha }}", options["ref"])
        self.assertIs(False, options["persist-credentials"])
        self.assertEqual(SCRIPT, options["sparse-checkout"])
        self.assertNotIn("repository", options)

    def test_the_script_runs_isolated_from_the_checkout(self) -> None:
        self.assertEqual(f"python3 -I {SCRIPT}", steps("decide")[1]["run"])

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
            },
            passed,
        )


if __name__ == "__main__":
    unittest.main()
