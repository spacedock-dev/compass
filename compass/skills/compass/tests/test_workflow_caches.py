"""No job that holds a write credential restores a cache, in any workflow.

actions/cache extracts an entry with `tar -xf ARCHIVE -P -C WORKSPACE`, and `-P` keeps `../` and
absolute member names, so an entry writes wherever the runner user can before any later step can
check it, and what it restores runs as it is. Main-branch gate runs save the pip cache after
running third-party code (lint, typecheck and the suites), so a dependency compromised in one of
them could shape an entry. A job holding a write token or any secret, such as a deploy key, must
never be the one that restores it.

`test_release_workflow.NoCacheTest` reuses this module's setup-action classifier for every release
job. This module scans all workflows and also bans caches in read-only frontend dependency jobs,
including the verification log a setup action can restore and save behind a disabled store cache.
"""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[4]
WORKFLOWS = ROOT / ".github/workflows"

# Actions read and found to restore nothing. An action missing from this set and from
# `restores_a_cache`'s own cases counts as restoring one, so a write-token job cannot use it until
# someone has read what it does. That is the point: a third-party action restores through the
# same `tar -P` extraction as actions/cache, and a ban on `actions/cache` alone would miss it.
RESTORES_NOTHING = frozenset(
    {
        "actions/checkout",
        "actions/upload-artifact",
        "peter-evans/find-comment",
        "peter-evans/create-or-update-comment",
    }
)


def workflows() -> dict[str, dict[str, Any]]:
    return {
        path.name: cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
    }


def holds_write_credential(workflow: dict[str, Any], job: dict[str, Any]) -> bool:
    """Whether the job's token can write, or it holds a secret. Fails closed on an unread shape."""
    # A deploy key arrives as a secret beside a read-only token (release.yml's `marketplace` and
    # `homebrew`), and nothing here can tell which secrets write, so every one counts.
    if "secrets" in job or "secrets." in json.dumps(job):
        return True
    # Workflow env reaches this job except for names the job replaces. Do not scan the whole
    # workflow: that would attribute a publisher's secret to unrelated read-only jobs.
    inherited_env = {**(workflow.get("env") or {}), **(job.get("env") or {})}
    inherited = {"env": inherited_env, "defaults": workflow.get("defaults")}
    if "secrets." in json.dumps(inherited):
        return True
    if "permissions" in job:
        permissions = job["permissions"]
    elif "permissions" in workflow:
        permissions = workflow["permissions"]
    else:
        # The repository's default token, which this file cannot see and which may be write-all.
        return True
    if isinstance(permissions, dict):
        return any(value == "write" for value in permissions.values())
    if isinstance(permissions, str):
        return permissions != "read-all"
    return True


def restores_a_cache(step: dict[str, Any]) -> bool:
    """Whether a step restores untrusted files or saves a cache, including setup post steps."""
    if "uses" not in step:
        return False
    action = step["uses"].split("@")[0]
    options = step.get("with") or {}
    # pnpm/setup v3.0.0 restores its lockfile verification log on every run, "independently of the
    # `cache` input" (its README), so `cache: false` does not make it cache-free.
    if action.startswith("actions/cache") or action == "pnpm/setup":
        return True
    if action == "actions/download-artifact":
        # Any of these reaches another run's artifacts, which a pull request's untrusted code may
        # have written: the artifact counterpart of a poisoned cache entry.
        return any(key in options for key in ("run-id", "github-token", "repository"))
    if action == "actions/setup-python":
        # `cache` has no default (v7.0.0 action.yml): nothing is restored unless it is named.
        return bool(options.get("cache"))
    if action == "actions/setup-node":
        # `package-manager-cache` defaults to true (v7.0.0 action.yml), and an explicit `cache` is
        # read before it, so only both held off restores nothing.
        return bool(options.get("cache")) or options.get("package-manager-cache") is not False
    return action not in RESTORES_NOTHING


class FrontendCachesTest(unittest.TestCase):
    def assert_no_cache(self, job: dict[str, Any]) -> None:
        for step in job["steps"]:
            self.assertFalse(
                restores_a_cache(step),
                f"{step.get('name') or step.get('uses')} can restore or save a cache after dependency code",
            )

    def test_a_contributor_and_release_builder_never_reuse_a_verification_log(self) -> None:
        seen = set()
        for name, workflow in workflows().items():
            for job_id, job in workflow["jobs"].items():
                # Follow setup/verification-cache references too, so a new or renamed job
                # cannot recover the implicit cache simply by leaving the known frontend IDs.
                mentions_pnpm = any(
                    word in json.dumps(job) for word in ("pnpm", "lockfile-verified")
                )
                if (
                    job_id.startswith("frontend")
                    or job_id in {"storybook", "verify-frontend"}
                    or mentions_pnpm
                ):
                    seen.add((name, job_id))
                    with self.subTest(workflow=name, job=job_id):
                        self.assert_no_cache(job)
        self.assertIn(("quality-gate.yml", "storybook"), seen)
        self.assertIn(("release.yml", "verify-frontend"), seen)

    def test_a_maintainer_cannot_hide_a_verification_cache_behind_a_different_job_name(
        self,
    ) -> None:
        for step in (
            {"uses": "pnpm/setup@sha", "with": {"cache": False}},
            {
                "uses": "actions/cache/save@sha",
                "with": {"path": "lockfile-verified.jsonl", "key": "verification"},
            },
        ):
            planted = copy.deepcopy(workflows())
            planted["release.yml"]["jobs"]["dependency-audit"] = {
                "permissions": {"contents": "read"},
                "steps": [step],
            }
            result = unittest.TestResult()
            with mock.patch(__name__ + ".workflows", return_value=planted):
                FrontendCachesTest(
                    "test_a_contributor_and_release_builder_never_reuse_a_verification_log"
                ).run(result)
            with self.subTest(step=step):
                self.assertTrue(
                    result.failures,
                    "a maintainer must see verification caches rejected under any job name",
                )
                self.assertIn("can restore or save a cache", result.failures[0][1])

    def test_a_maintainer_cannot_reintroduce_an_implicit_restore_or_a_post_job_save(self) -> None:
        for step in (
            {
                "uses": "pnpm/setup@fbda4c85fc2e1e08721cd8763afea8f48d60f024",
                "with": {"cache": False},
            },
            *(
                {
                    "uses": f"actions/cache{suffix}@sha",
                    "with": {
                        "path": "~/.cache/pnpm/lockfile-verified.jsonl",
                        "key": "verification",
                    },
                }
                for suffix in ("", "/restore", "/save")
            ),
        ):
            job = copy.deepcopy(workflows()["release.yml"]["jobs"]["verify-frontend"])
            job["steps"] = [step]
            with self.subTest(step=step), self.assertRaisesRegex(AssertionError, "restore or save"):
                self.assert_no_cache(job)


class WriteCredentialRestoresNoCacheTest(unittest.TestCase):
    def assert_no_credential_cache(self, workflow: dict[str, Any], job: dict[str, Any]) -> None:
        if not holds_write_credential(workflow, job):
            return
        # A reusable workflow's steps are not in this file, so it cannot be read here.
        self.assertNotIn("uses", job, "a called workflow is unread")
        for step in job["steps"]:
            self.assertFalse(
                restores_a_cache(step),
                f"{step.get('name') or step['uses']} restores a cache",
            )

    def test_no_job_holding_a_write_credential_restores_a_cache(self) -> None:
        for name, workflow in workflows().items():
            for job_id, job in workflow["jobs"].items():
                with self.subTest(workflow=name, job=job_id):
                    self.assert_no_credential_cache(workflow, job)

    def test_the_scan_reaches_the_jobs_that_hold_the_token(self) -> None:
        # Guards the test above against passing vacuously, say on a renamed workflow directory.
        seen = {
            (name, job_id)
            for name, workflow in workflows().items()
            for job_id, job in workflow["jobs"].items()
            if holds_write_credential(workflow, job)
        }
        self.assertLessEqual(
            {
                ("quality-gate.yml", "coverage-comment"),
                ("quality-gate.yml", "frontend-coverage-comment"),
                ("release.yml", "release"),
                ("release.yml", "attach-cli"),
                # A read-only token, but a deploy key that writes to another repository.
                ("release.yml", "marketplace"),
                ("release.yml", "homebrew"),
                # pull_request_target: a write token on a run a pull request starts.
                ("requeue-after-ejection.yml", "decide"),
                # No token at all, but the secret that enqueues.
                ("requeue-after-ejection.yml", "enqueue"),
                # pull_request_target again: corrects the comment when the enqueue fails.
                ("requeue-after-ejection.yml", "report"),
            },
            seen,
        )

    def test_a_reader_is_protected_when_their_job_inherits_a_workflow_secret(self) -> None:
        for inherited in (
            {"env": {"DEPLOY_KEY": "${{ secrets.DEPLOY_KEY }}"}},
            {"defaults": {"run": {"shell": "${{ secrets.SHELL }}"}}},
        ):
            for permissions in ("read-all", {"contents": "read"}, {}):
                workflow = {"permissions": "read-all", **inherited}
                job = {"permissions": permissions, "steps": [{"uses": "actions/cache@sha"}]}
                with self.subTest(inherited=inherited, permissions=permissions):
                    self.assertTrue(
                        holds_write_credential(workflow, job),
                        "an inherited secret must close the cache boundary",
                    )

    def test_a_reader_does_not_inherit_another_jobs_secret_or_replaced_environment(self) -> None:
        reference = "${{ secrets.DEPLOY_KEY }}"
        workflow = {
            "permissions": "read-all",
            "env": {"KEY": reference},
            "jobs": {"publisher": {"env": {"KEY": reference}}},
        }
        self.assertFalse(holds_write_credential(workflow, {"env": {"KEY": "public"}}))
        self.assertTrue(holds_write_credential(workflow, {"env": {"OTHER": "public"}}))
        self.assertTrue(holds_write_credential(workflow, {}))
        workflow.pop("env")
        self.assertFalse(holds_write_credential(workflow, {}))

    def test_a_reader_inheriting_a_secret_cannot_restore_a_planted_cache(self) -> None:
        for scope in ("env", "defaults"):
            workflow = copy.deepcopy(workflows()["release.yml"])
            job = workflow["jobs"]["verify-tree"]
            job["permissions"] = {"contents": "read"}
            job["steps"] = [{"uses": "actions/cache/restore@sha"}]
            workflow[scope] = {"KEY": "${{ secrets.DEPLOY_KEY }}"}
            with (
                self.subTest(scope=scope),
                self.assertRaisesRegex(AssertionError, "restores a cache"),
            ):
                self.assert_no_credential_cache(workflow, job)

    def test_the_credential_reading_fails_closed(self) -> None:
        cases: tuple[tuple[dict[str, Any], dict[str, Any], bool], ...] = (
            ({}, {}, True),  # the repository default
            ({"permissions": {"contents": "read"}}, {}, False),
            ({"permissions": "write-all"}, {}, True),
            ({"permissions": "read-all"}, {}, False),
            ({"permissions": {"contents": "read"}}, {"permissions": {"issues": "write"}}, True),
            ({"permissions": "write-all"}, {"permissions": {"contents": "read"}}, False),
            ({"permissions": "write-all"}, {"permissions": {}}, False),
            ({}, {"permissions": {"id-token": "write"}}, True),
            ({}, {"permissions": None}, True),
            (
                {"permissions": "read-all"},
                {"steps": [{"env": {"KEY": "${{ secrets.TAP_DEPLOY_KEY }}"}}]},
                True,
            ),
            (
                {"permissions": "read-all"},
                {"steps": [{"with": {"ssh-key": "${{ secrets.DEPLOY_KEY }}"}}]},
                True,
            ),
            (
                {"permissions": "read-all"},
                {"uses": "./.github/workflows/x.yml", "secrets": "inherit"},
                True,
            ),
        )
        for workflow, job, expected in cases:
            with self.subTest(workflow=workflow, job=job):
                self.assertIs(expected, holds_write_credential(workflow, job))

    def test_every_way_a_step_restores_a_cache_is_seen(self) -> None:
        cases = (
            ({"run": "pip install -r requirements-dev.txt"}, False),
            ({"uses": "actions/checkout@sha"}, False),
            ({"uses": "actions/download-artifact@sha"}, False),
            ({"uses": "actions/download-artifact@sha", "with": {"name": "coverage-1"}}, False),
            # Another run's artifacts, which may be a pull request's that ran untrusted code.
            ({"uses": "actions/download-artifact@sha", "with": {"run-id": "1"}}, True),
            ({"uses": "actions/download-artifact@sha", "with": {"github-token": "t"}}, True),
            ({"uses": "actions/download-artifact@sha", "with": {"repository": "o/r"}}, True),
            ({"uses": "actions/cache@sha"}, True),
            ({"uses": "actions/cache/restore@sha"}, True),
            ({"uses": "actions/setup-python@sha", "with": {"python-version": "3.14"}}, False),
            ({"uses": "actions/setup-python@sha", "with": {"cache": "pip"}}, True),
            ({"uses": "actions/setup-node@sha", "with": {"node-version": "24"}}, True),
            ({"uses": "actions/setup-node@sha", "with": {"package-manager-cache": False}}, False),
            (
                {
                    "uses": "actions/setup-node@sha",
                    "with": {"package-manager-cache": False, "cache": "pnpm"},
                },
                True,
            ),
            ({"uses": "pnpm/setup@sha", "with": {"cache": False}}, True),
            ({"uses": "pnpm/action-setup@unread", "with": {"cache": False}}, True),
            ({"uses": "someone/unread-action@sha"}, True),
        )
        for step, expected in cases:
            with self.subTest(step=step):
                self.assertIs(expected, restores_a_cache(step))


if __name__ == "__main__":
    unittest.main()
