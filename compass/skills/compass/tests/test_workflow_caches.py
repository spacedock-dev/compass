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

import base64
import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
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


# Any expression that names the secrets context: `secrets.X`, `secrets['X']`, `toJSON(secrets)`,
# in any letter case. A plain "secrets" in a run script is not an expression and does not count.
_EXPRESSION_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_SECRETS_RE = re.compile(r"\bsecrets\b", re.IGNORECASE)


def names_a_secret(value: object) -> bool:
    return any(_SECRETS_RE.search(expr) for expr in _EXPRESSION_RE.findall(json.dumps(value)))


def holds_write_credential(workflow: dict[str, Any], job: dict[str, Any]) -> bool:
    """Whether the job's token can write, or it holds a secret. Fails closed on an unread shape."""
    # A deploy key arrives as a secret beside a read-only token (release.yml's `marketplace` and
    # `homebrew`), and nothing here can tell which secrets write, so every one counts.
    if "secrets" in job or names_a_secret(job):
        return True
    # Workflow env reaches this job except for names the job replaces. Do not scan the whole
    # workflow: that would attribute a publisher's secret to unrelated read-only jobs.
    inherited_env = {**(workflow.get("env") or {}), **(job.get("env") or {})}
    inherited = {"env": inherited_env, "defaults": workflow.get("defaults")}
    if names_a_secret(inherited):
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


BOOTSTRAP_RUN = (
    "npm ci --ignore-scripts --prefix tools/pnpm-bootstrap\n"
    'echo "$GITHUB_WORKSPACE/tools/pnpm-bootstrap/node_modules/.bin" >> "$GITHUB_PATH"\n'
)


def assert_locked_pnpm(test: unittest.TestCase, job: dict[str, Any]) -> None:
    """A runner must execute the binary whose bytes this checkout pins, before project code."""
    steps = job["steps"]
    test.assertEqual(
        "0",
        job.get("env", {}).get("COREPACK_ENABLE_NETWORK"),
        "a missing optional binary must never download outside the lock",
    )
    commands = [step.get("run", "") for step in steps]
    test.assertEqual(
        1, commands.count(BOOTSTRAP_RUN), "install pnpm from the committed bootstrap lock"
    )
    bootstrap = commands.index(BOOTSTRAP_RUN)
    step = steps[bootstrap]
    test.assertEqual("bash", step.get("shell"), "bootstrap must stop if npm rejects an integrity")
    test.assertNotIn("if", step, "bootstrap cannot be skipped")
    test.assertNotIn("continue-on-error", step, "bootstrap integrity failures must stop the job")
    test.assertGreater(step.get("timeout-minutes", 0), 0)
    for action in ("actions/checkout@", "actions/setup-node@"):
        matches = [i for i, item in enumerate(steps) if item.get("uses", "").startswith(action)]
        test.assertEqual(1, len(matches), action)
        test.assertLess(matches[0], bootstrap, "bootstrap uses this checkout and the pinned Node")
    for index, item in enumerate(steps):
        action = item.get("uses", "").lower()
        test.assertFalse(action.startswith("pnpm/"), "pnpm setup actions bypass the bootstrap lock")
        test.assertEqual(
            "0",
            item.get("env", {}).get("COREPACK_ENABLE_NETWORK", "0"),
            "steps must keep the wrapper download fallback disabled",
        )
        command = item.get("run", "")
        test.assertNotRegex(command.lower(), r"\b(?:corepack|npx)\b", "alternate pnpm installer")
        if re.search(r"\bnpm\s", command):
            test.assertEqual(BOOTSTRAP_RUN, command, "npm must use the committed bootstrap lock")
        if re.search(r"(?:^|[\s;&|])pnpm\s", command):
            test.assertLess(bootstrap, index, "pnpm must run after the locked binary reaches PATH")
            test.assertNotRegex(command, r"\bpnpm\s+(?:env|self-update|setup)\b")


class PnpmBootstrapTest(unittest.TestCase):
    def test_a_builder_installs_only_the_pnpm_bytes_the_checkout_approves(self) -> None:
        seen = set()
        for name, workflow in workflows().items():
            for job_id, job in workflow["jobs"].items():
                text = json.dumps(job).lower()
                if "pnpm" in text or "corepack" in text:
                    seen.add((name, job_id))
                    with self.subTest(workflow=name, job=job_id):
                        assert_locked_pnpm(self, job)
        self.assertLessEqual(
            {
                ("quality-gate.yml", job)
                for job in (
                    "frontend",
                    "frontend-macos",
                    "frontend-coverage",
                    "frontend-production",
                    "storybook",
                    "frontend-contract",
                    "frontend-docs",
                )
            }
            | {("release.yml", "verify-frontend")},
            seen,
        )

    def test_a_maintainer_cannot_add_an_alternate_installer_under_an_unfamiliar_job_name(
        self,
    ) -> None:
        for step in (
            {"run": "npm install --global --ignore-scripts pnpm@12.9.1"},
            {"run": "npm i -g pnpm@12.9.1"},
            {"run": "npm exec --package=pnpm -- pnpm --version"},
            {"run": "corepack prepare pnpm@12.9.1 --activate"},
            {"uses": "pnpm/setup@sha", "with": {"cache": False}},
            {"uses": "pnpm/action-setup@sha"},
        ):
            planted = copy.deepcopy(workflows())
            planted["quality-gate.yml"]["jobs"]["new-builder"] = copy.deepcopy(
                planted["quality-gate.yml"]["jobs"]["frontend"]
            )
            planted["quality-gate.yml"]["jobs"]["new-builder"]["steps"].append(step)
            result = unittest.TestResult()
            with mock.patch(__name__ + ".workflows", return_value=planted):
                PnpmBootstrapTest(
                    "test_a_builder_installs_only_the_pnpm_bytes_the_checkout_approves"
                ).run(result)
            with self.subTest(step=step):
                self.assertTrue(result.failures, "a maintainer sees an unlocked installer rejected")

    def test_a_builder_has_reviewable_hashes_for_every_supported_ci_platform(self) -> None:
        directory = ROOT / "tools/pnpm-bootstrap"
        for name in ("package.json", "package-lock.json"):
            self.assertTrue(
                (directory / name).is_file(), "pnpm needs a committed bootstrap manifest and lock"
            )
        manifest = json.loads((directory / "package.json").read_text())
        lock = json.loads((directory / "package-lock.json").read_text())
        project = json.loads((ROOT / "package.json").read_text())
        version = project["packageManager"].removeprefix("pnpm@")
        self.assertIs(True, manifest["private"])
        self.assertNotIn("scripts", manifest)
        self.assertEqual({"pnpm": version}, manifest["dependencies"])
        self.assertEqual(version, project["engines"]["pnpm"])
        self.assertEqual(3, lock["lockfileVersion"])
        packages = lock["packages"]
        self.assertEqual(manifest["dependencies"], packages[""]["dependencies"])
        self.assertEqual(version, packages["node_modules/pnpm"]["version"])
        for key, package in packages.items():
            if not key:
                continue
            with self.subTest(package=key):
                self.assertEqual(version, package["version"])
                self.assertRegex(
                    package["resolved"], r"^https://registry\.npmjs\.org/(?:pnpm|@pnpm/)"
                )
                algorithm, digest = package["integrity"].split("-", 1)
                self.assertEqual("sha512", algorithm)
                self.assertEqual(64, len(base64.b64decode(digest, validate=True)))
        optional = packages["node_modules/pnpm"]["optionalDependencies"]
        self.assertEqual(
            {"", "node_modules/pnpm"} | {f"node_modules/{name}" for name in optional}, set(packages)
        )
        for system in ("linux", "darwin"):
            for cpu in ("x64", "arm64"):
                name = f"@pnpm/exe.{system}-{cpu}"
                self.assertEqual(version, optional[name])
                package = packages[f"node_modules/{name}"]
                self.assertEqual([system], package["os"])
                self.assertEqual([cpu], package["cpu"])
                self.assertIs(True, package["optional"])


@unittest.skipUnless(
    os.environ.get("COMPASS_PNPM_TEST_CACHE"),
    "populate an isolated npm cache for the offline bootstrap proof",
)
class PnpmOfflineBootstrapTest(unittest.TestCase):
    """Run with COMPASS_PNPM_TEST_CACHE pointing to a cache populated by the locked npm ci.

    No network or user npm configuration is used, and every mutation lives in a temporary copy.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.workspace = self.home / "workspace with spaces"
        self.bootstrap = self.workspace / "tools/pnpm-bootstrap"
        self.bootstrap.mkdir(parents=True)
        for name in ("package.json", "package-lock.json"):
            shutil.copyfile(ROOT / "tools/pnpm-bootstrap" / name, self.bootstrap / name)
        for name in ("user.npmrc", "global.npmrc"):
            (self.home / name).write_text("")
        self.env = {
            key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR") if key in os.environ
        }
        self.env.update(
            {
                "HOME": str(self.home),
                "NPM_CONFIG_USERCONFIG": str(self.home / "user.npmrc"),
                "NPM_CONFIG_GLOBALCONFIG": str(self.home / "global.npmrc"),
                "NPM_CONFIG_CACHE": os.environ["COMPASS_PNPM_TEST_CACHE"],
                "NPM_CONFIG_UPDATE_NOTIFIER": "false",
                "COREPACK_ENABLE_NETWORK": "0",
            }
        )

    def install(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                shutil.which("npm") or "npm",
                "ci",
                "--offline",
                "--ignore-scripts",
                "--prefix",
                str(self.bootstrap),
                "--no-audit",
                "--no-fund",
            ],
            cwd=self.bootstrap,
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def corrupt(self, key: str) -> None:
        path = self.bootstrap / "package-lock.json"
        lock = json.loads(path.read_text())
        integrity = lock["packages"][key]["integrity"]
        lock["packages"][key]["integrity"] = (
            "sha512-" + ("A" if integrity[7] != "A" else "B") + integrity[8:]
        )
        path.write_text(json.dumps(lock))

    def version(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.bootstrap / "node_modules/.bin/pnpm"), "--version"],
            cwd=self.home,
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_a_builder_can_run_the_locked_binary_offline_with_scripts_denied(self) -> None:
        before = (self.bootstrap / "package-lock.json").read_bytes()
        installed = self.install()
        self.assertEqual(0, installed.returncode, installed.stderr)
        version = self.version()
        self.assertEqual(0, version.returncode, version.stderr)
        self.assertEqual("12.9.1", version.stdout.strip())
        self.assertEqual(before, (self.bootstrap / "package-lock.json").read_bytes())
        self.assertFalse(
            (self.bootstrap / "node_modules/pnpm/pnpm-native").exists(),
            "the wrapper must use the locked optional package",
        )

    def test_a_builder_finds_the_locked_binary_through_the_workflow_path_even_with_spaces(
        self,
    ) -> None:
        path_file = self.home / "github path"
        env = {
            **self.env,
            "GITHUB_WORKSPACE": str(self.workspace),
            "GITHUB_PATH": str(path_file),
            "NPM_CONFIG_OFFLINE": "true",
        }
        installed = subprocess.run(
            [
                shutil.which("bash") or "bash",
                "--noprofile",
                "--norc",
                "-e",
                "-o",
                "pipefail",
                "-c",
                BOOTSTRAP_RUN,
            ],
            cwd=self.workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(0, installed.returncode, installed.stderr)
        self.assertEqual(
            [str(self.bootstrap / "node_modules/.bin")], path_file.read_text().splitlines()
        )
        env["PATH"] = path_file.read_text().strip() + os.pathsep + env["PATH"]
        executable = shutil.which("pnpm", path=env["PATH"])
        self.assertEqual(str(self.bootstrap / "node_modules/.bin/pnpm"), executable)
        assert executable is not None
        version = subprocess.run(
            [executable, "--version"],
            cwd=self.workspace,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(0, version.returncode, version.stderr)
        self.assertEqual("12.9.1", version.stdout.strip())

    def test_a_builder_rejects_a_changed_pnpm_integrity_before_running_it(self) -> None:
        baseline = self.install()
        self.assertEqual(0, baseline.returncode, baseline.stderr)
        self.corrupt("node_modules/pnpm")
        installed = self.install()
        self.assertNotEqual(
            0,
            installed.returncode,
            "npm ci must reject bytes that differ from the checkout's integrity",
        )
        # npm's content-addressed offline cache cannot serve the same tarball under a changed
        # digest; online it reports EINTEGRITY after fetching the bytes again.
        self.assertRegex(installed.stderr, r"EINTEGRITY|ENOTCACHED")

    def test_a_builder_cannot_download_around_a_rejected_optional_binary(self) -> None:
        # Corrupt both Linux libc variants: the wrapper accepts either if installed.
        lock = json.loads((self.bootstrap / "package-lock.json").read_text())
        for key in lock["packages"]:
            if key.startswith("node_modules/@pnpm/exe."):
                self.corrupt(key)
        installed = self.install()
        # npm treats optional failures as optional; the wrapper must fail closed instead.
        self.assertEqual(0, installed.returncode, installed.stderr)
        version = self.version()
        self.assertNotEqual(
            0, version.returncode, "a failed optional package must never escape the committed lock"
        )
        self.assertIn("Network access is disabled", version.stderr)
        self.assertNotIn("Downloading the pnpm", version.stderr)


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

    def test_a_reader_is_protected_from_every_spelling_of_a_secret(self) -> None:
        for reference in (
            "${{ secrets['DEPLOY_KEY'] }}",
            '${{ secrets["DEPLOY_KEY"] }}',
            "${{ toJSON(secrets) }}",
            "${{ SECRETS.DEPLOY_KEY }}",
        ):
            for place in ("job", "workflow"):
                workflow: dict[str, Any] = {"permissions": "read-all"}
                job: dict[str, Any] = {"permissions": {"contents": "read"}}
                (job if place == "job" else workflow)["env"] = {"KEY": reference}
                with self.subTest(reference=reference, place=place):
                    self.assertTrue(holds_write_credential(workflow, job))
        workflow = {"permissions": "read-all", "env": {"TOKEN": "${{ github.token }}"}}
        job = {"permissions": {"contents": "read"}, "steps": [{"run": "echo no secrets here"}]}
        self.assertFalse(holds_write_credential(workflow, job))

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
