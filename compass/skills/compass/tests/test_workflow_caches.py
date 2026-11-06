"""No job that holds a write token restores a cache, in any workflow.

actions/cache extracts an entry with `tar -xf ARCHIVE -P -C WORKSPACE`, and `-P` keeps `../` and
absolute member names, so an entry writes wherever the runner user can before any later step can
check it, and what it restores runs as it is. Main-branch gate runs save the pip cache after
running third-party code (lint, typecheck and the suites), so a dependency compromised in one of
them could shape an entry. A job holding a write token must never be the one that restores it.

`test_release_workflow.NoCacheTest` holds the release workflow to the stricter rule that no job
there uses a cache at all; this module covers every job of every workflow, the release ones too.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, cast

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
        "actions/download-artifact",
        "peter-evans/find-comment",
        "peter-evans/create-or-update-comment",
    }
)


def workflows() -> dict[str, dict[str, Any]]:
    return {
        path.name: cast("dict[str, Any]", yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
    }


def holds_write_token(workflow: dict[str, Any], job: dict[str, Any]) -> bool:
    """Whether the job's GITHUB_TOKEN can write anything. Fails closed on a shape it cannot read."""
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
    """Whether the step can restore a cache entry, read from the pinned action's own inputs."""
    if "uses" not in step:
        return False
    action = step["uses"].split("@")[0]
    options = step.get("with") or {}
    if action.startswith("actions/cache"):
        return True
    if action == "actions/setup-python":
        # `cache` has no default (v7.0.0 action.yml): nothing is restored unless it is named.
        return bool(options.get("cache"))
    if action == "actions/setup-node":
        # `package-manager-cache` defaults to true (v7.0.0 action.yml), and an explicit `cache` is
        # read before it, so only both held off restores nothing.
        return bool(options.get("cache")) or options.get("package-manager-cache") is not False
    if action == "pnpm/setup":
        # v3.0.0 restores its lockfile verification log on every run, "independently of the
        # `cache` input" (its README), so `cache: false` does not make it cache-free.
        return True
    return action not in RESTORES_NOTHING


class WriteTokenRestoresNoCacheTest(unittest.TestCase):
    def test_no_job_holding_a_write_token_restores_a_cache(self) -> None:
        for name, workflow in workflows().items():
            for job_id, job in workflow["jobs"].items():
                if not holds_write_token(workflow, job):
                    continue
                with self.subTest(workflow=name, job=job_id):
                    # A reusable workflow's steps are not in this file, so it cannot be read here.
                    self.assertNotIn("uses", job, "a called workflow is unread")
                    for step in job["steps"]:
                        self.assertFalse(
                            restores_a_cache(step),
                            f"{step.get('name') or step['uses']} restores a cache",
                        )

    def test_the_scan_reaches_the_jobs_that_hold_the_token(self) -> None:
        # Guards the test above against passing vacuously, say on a renamed workflow directory.
        seen = {
            (name, job_id)
            for name, workflow in workflows().items()
            for job_id, job in workflow["jobs"].items()
            if holds_write_token(workflow, job)
        }
        self.assertLessEqual(
            {
                ("quality-gate.yml", "coverage-comment"),
                ("quality-gate.yml", "frontend-coverage-comment"),
                ("release.yml", "release"),
                ("release.yml", "attach-cli"),
            },
            seen,
        )

    def test_the_token_reading_fails_closed(self) -> None:
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
        )
        for workflow, job, expected in cases:
            with self.subTest(workflow=workflow, job=job):
                self.assertIs(expected, holds_write_token(workflow, job))

    def test_every_way_a_step_restores_a_cache_is_seen(self) -> None:
        cases = (
            ({"run": "pip install -r requirements-dev.txt"}, False),
            ({"uses": "actions/checkout@sha"}, False),
            ({"uses": "actions/download-artifact@sha"}, False),
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
            ({"uses": "someone/unread-action@sha"}, True),
        )
        for step, expected in cases:
            with self.subTest(step=step):
                self.assertIs(expected, restores_a_cache(step))


if __name__ == "__main__":
    unittest.main()
