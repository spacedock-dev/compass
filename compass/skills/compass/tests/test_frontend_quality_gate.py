"""The required gate measures frontend changes and cannot hide a failed matrix."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

import yaml

from . import test_quality_gate as detector

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/quality-gate.yml"


def jobs() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(WORKFLOW.read_text())["jobs"])


@unittest.skipUnless(detector.BASH, "the shipped gate uses Bash")
class FrontendDetectorControlsTest(unittest.TestCase):
    def test_sources_builds_and_relevant_workflows_request_measurable_jobs(self) -> None:
        probe = detector.QualityGateDetectorTest()
        for path in (
            "frontend/src/main.tsx",
            "frontend/test/setup.ts",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            ".node-version",
            ".npmrc",
            "package.json",
            "biome.json",
            "frontend/vite.config.mts",
            "scripts/build_frontend.mjs",
            "compass/skills/compass/compass_runtime/web/react.html",
            ".github/workflows/release.yml",
            ".github/workflows/release.yaml",
            ".github/workflows/frontend-build.yml",
            ".github/workflows/frontend-build.yaml",
            ".github/actions/frontend-toolchain/action.yml",
        ):
            with self.subTest(path=path):
                self.assertEqual("code=true", probe.detect(path))

    def test_actual_frontend_doc_reads_precede_prose_classification(self) -> None:
        # Real temporary source inputs, not an invented detector result.
        with tempfile.TemporaryDirectory(prefix="frontend-doc-filter-") as temp:
            root = Path(temp)
            tests = root / "compass/skills/compass/tests"
            tests.mkdir(parents=True)
            (tests / "dummy.py").write_text("pass\n")
            runtime = root / "compass/skills/compass/compass_runtime"
            runtime.mkdir()
            frontend = root / "frontend/test"
            frontend.mkdir(parents=True)
            source = frontend / "setup.test.ts"
            root_doc = "CONTRIBUTING" + ".md"
            quoted_doc = "docs/" + "frontend-reader" + ".md"
            cited_doc = "docs/" + "frontend-citation" + ".md"
            source.write_text(
                f"readFileSync('{root_doc}');\nreadFileSync(\"{quoted_doc}\");\n"
                f"// See ({cited_doc}#reader-state)\n"
            )
            probe = detector.QualityGateDetectorTest()
            for path in (root_doc, quoted_doc, cited_doc):
                with self.subTest(path=path):
                    self.assertEqual("code=true", probe.detect(path, root=root))
            source.unlink()
            self.assertEqual("code=false", probe.detect(root_doc, root=root))
            self.assertEqual("code=false", probe.detect(quoted_doc, root=root))
            # An unreadable source scan cannot authorize the prose skip path.
            source.write_bytes(b"\xff")
            self.assertEqual("code=true", probe.detect(root_doc, root=root))

    def test_unrelated_workflow_prose_keeps_its_short_path(self) -> None:
        self.assertEqual(
            "code=false",
            detector.QualityGateDetectorTest().detect(".github/workflows/version-guard.yml"),
        )


@unittest.skipUnless(detector.BASH, "the shipped aggregate uses Bash")
class FrontendAggregateControlsTest(unittest.TestCase):
    def aggregate(self, *, code: str, results: dict[str, str]) -> subprocess.CompletedProcess[str]:
        script = next(step["run"] for step in jobs()["quality-gate"]["steps"] if "run" in step)
        return subprocess.run(
            [detector.BASH or "bash", "-c", script],
            env={**os.environ, "CODE": code, **results},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    def test_every_required_result_rejects_failure_cancellation_and_unexpected_skip(self) -> None:
        successful = {
            "R_CHANGES": "success",
            "R_LINT": "success",
            "R_TYPECHECK": "success",
            "R_FLOOR": "success",
            "R_TEST": "success",
            "R_PLATFORM": "success",
            "R_FRONTEND": "success",
            "R_FRONTEND_COVERAGE": "success",
            "R_FRONTEND_PRODUCTION": "success",
            "R_STORYBOOK": "success",
        }
        for name in successful:
            for bad in ("failure", "cancelled", "skipped"):
                with self.subTest(name=name, bad=bad):
                    result = self.aggregate(code="true", results={**successful, name: bad})
                    self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertEqual(0, self.aggregate(code="true", results=successful).returncode)

    def test_skip_is_allowed_only_for_prose_and_a_successful_detector(self) -> None:
        skipped = {
            "R_CHANGES": "success",
            "R_LINT": "skipped",
            "R_TYPECHECK": "skipped",
            "R_FLOOR": "skipped",
            "R_TEST": "skipped",
            "R_PLATFORM": "skipped",
            "R_FRONTEND": "skipped",
            "R_FRONTEND_COVERAGE": "skipped",
            "R_FRONTEND_PRODUCTION": "skipped",
            "R_STORYBOOK": "skipped",
        }
        self.assertEqual(0, self.aggregate(code="false", results=skipped).returncode)
        for bad in ("failure", "cancelled", "skipped"):
            with self.subTest(detector=bad):
                self.assertNotEqual(
                    0,
                    self.aggregate(code="false", results={**skipped, "R_CHANGES": bad}).returncode,
                )
        for name in ("R_FRONTEND", "R_FRONTEND_COVERAGE", "R_FRONTEND_PRODUCTION", "R_STORYBOOK"):
            with self.subTest(failed=name):
                self.assertNotEqual(
                    0, self.aggregate(code="false", results={**skipped, name: "failure"}).returncode
                )


class FrontendWiringControlsTest(unittest.TestCase):
    def test_the_css_ratchet_reads_the_actual_pr_base_without_shell_specific_variables(
        self,
    ) -> None:
        frontend = jobs()["frontend"]
        steps = frontend["steps"]
        ratchet = next((step for step in steps if step.get("run") == "pnpm test:styles"), None)
        self.assertIsNotNone(ratchet, "the PR base gate must remain on the macOS frontend leg")
        assert ratchet is not None
        self.assertEqual("${{ github.event.pull_request.base.sha }}", ratchet["env"]["PR_BASE"])
        self.assertEqual("github.event_name == 'pull_request'", ratchet["if"])
        self.assertNotIn("continue-on-error", ratchet)
        checkout = next(
            step for step in steps if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertEqual(0, checkout["with"]["fetch-depth"])
        unit = next(step for step in steps if step.get("run") == "pnpm test")
        self.assertGreaterEqual(unit["timeout-minutes"], 6)

    def check_runners(self, job: dict[str, Any], runners: list[str]) -> None:
        selection = job["strategy"]["matrix"]["os"]
        self.assertEqual(runners, selection)
        self.assertNotIn("windows-ci", json.dumps(job))

    def test_gate_checkouts_do_not_leave_credentials_for_later_commands(self) -> None:
        for name, job in jobs().items():
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/checkout@"):
                    with self.subTest(job=name):
                        self.assertFalse(step.get("with", {}).get("persist-credentials", True))

    def test_matrix_is_required_and_keeps_all_current_python_jobs(self) -> None:
        workflow_jobs = jobs()
        frontend = workflow_jobs["frontend"]
        self.check_runners(frontend, ["macos-latest"])
        self.assertEqual("Frontend (${{ matrix.os }})", frontend["name"])
        platform = workflow_jobs["platform-tests"]
        self.check_runners(platform, ["macos-latest"])
        # The two suites run as parallel legs so the slow script suite does not hold the dashboard one.
        self.assertEqual(["dashboard", "scripts"], platform["strategy"]["matrix"]["suite"])
        self.assertEqual([1, 2, 3], platform["strategy"]["matrix"]["shard"])
        self.assertEqual(
            [{"suite": "dashboard", "shard": 2}, {"suite": "dashboard", "shard": 3}],
            platform["strategy"]["matrix"]["exclude"],
        )
        gated = {step["name"]: step.get("if") for step in platform["steps"] if "if" in step}
        self.assertEqual(
            {
                "Run dashboard test discovery": "matrix.suite == 'dashboard'",
                "Run script unit tests": "matrix.suite == 'scripts'",
            },
            gated,
        )
        self.assertFalse(frontend["strategy"]["fail-fast"])
        self.assertLessEqual(frontend["timeout-minutes"], 30)
        self.assertEqual("changes", frontend["needs"])
        self.assertEqual("needs.changes.outputs.code == 'true'", frontend["if"])
        aggregate = workflow_jobs["quality-gate"]
        self.assertEqual("always()", aggregate["if"])
        self.assertEqual(
            {
                "changes",
                "lint",
                "typecheck",
                "runtime-floor",
                "test",
                "platform-tests",
                "frontend",
                "frontend-coverage",
                "frontend-production",
                "storybook",
            },
            set(aggregate["needs"]),
        )
        self.assertNotIn("frontend-coverage-comment", aggregate["needs"], "the comment never gates")
        env = aggregate["steps"][0]["env"]
        self.assertEqual("${{ needs.frontend.result }}", env["R_FRONTEND"])
        self.assertEqual("${{ needs.frontend-coverage.result }}", env["R_FRONTEND_COVERAGE"])
        self.assertEqual("${{ needs.frontend-production.result }}", env["R_FRONTEND_PRODUCTION"])
        self.assertEqual("${{ needs.storybook.result }}", env["R_STORYBOOK"])
        self.assertNotIn("frontend-proofs", workflow_jobs)
        self.assertNotIn("R_FRONTEND_PROOFS", env)

    def test_bootstrap_is_exact_without_auth_or_implicit_dependency_scripts(self) -> None:
        for name in ("frontend", "frontend-coverage", "frontend-production", "storybook"):
            with self.subTest(job=name):
                self.check_bootstrap(jobs()[name]["steps"])

    @staticmethod
    def label_check(step: dict[str, Any]) -> bool:
        return step.get("id") == "exception"

    def check_bootstrap(self, steps: list[dict[str, Any]]) -> None:
        node = next(
            step for step in steps if step.get("uses", "").startswith("actions/setup-node@")
        )
        self.assertEqual(
            "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020", node["uses"]
        )
        self.assertEqual(".node-version", node["with"]["node-version-file"])
        self.assertFalse(node["with"]["check-latest"])
        self.assertFalse(node["with"]["package-manager-cache"])
        manager = next(step for step in steps if step.get("uses", "").startswith("pnpm/setup@"))
        self.assertEqual("pnpm/setup@fbda4c85fc2e1e08721cd8763afea8f48d60f024", manager["uses"])
        self.assertEqual("12.9.1", manager["with"]["version"])
        self.assertFalse(manager["with"]["install"])
        self.assertFalse(manager["with"]["node-version-file"])
        checkout = next(
            step for step in steps if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertFalse(checkout["with"]["persist-credentials"])
        commands = [step.get("run", "") for step in steps]
        self.assertIn("pnpm install --frozen-lockfile --ignore-scripts", commands)
        self.assertFalse(any("corepack" in command.lower() for command in commands))
        for step in steps:
            self.assertNotIn("registry-url", step.get("with", {}))
            # The coverage-exception label check reads the PR with the job's read-only token. It is the
            # one step allowed a token, and it runs before any dependency is installed.
            if self.label_check(step):
                continue
            for name in ("NODE_AUTH_TOKEN", "NPM_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
                self.assertNotIn(name, step.get("env", {}))

    def test_frontend_coverage_enforces_the_thresholds_with_a_visible_bypass(self) -> None:
        """The frontend threshold is held as the Python one is: enforced on every run, bypassed only by the
        `coverage-exception` label, and owned by vitest.config.mts so a local `pnpm test:coverage` agrees."""
        job = jobs()["frontend-coverage"]
        self.assertEqual("ubuntu-latest", job["runs-on"])
        self.assertEqual({"contents": "read", "pull-requests": "read"}, job["permissions"])
        steps = job["steps"]
        names = [step.get("name") for step in steps]
        label = next(step for step in steps if self.label_check(step))
        self.assertEqual("github.event_name == 'pull_request'", label["if"])
        self.assertEqual("${{ github.token }}", label["env"]["GH_TOKEN"])
        self.assertIn("coverage-exception", label["run"])
        install = names.index("Frozen install with dependency scripts denied")
        self.assertLess(steps.index(label), install, "the token is used before dependencies exist")
        gate = next(step for step in steps if "pnpm test:coverage" in step.get("run", ""))
        self.assertNotIn("if", gate)
        self.assertGreater(gate["timeout-minutes"], 0)
        self.assertEqual(
            "${{ steps.exception.outputs.has_exception || '0' }}", gate["env"]["EXCEPTION"]
        )
        enforced, bypass = gate["run"].split("else")[1], gate["run"].split("else")[0]
        self.assertIn("pnpm test:coverage", enforced)
        self.assertNotIn(
            "thresholds", enforced, "without the label the configured thresholds apply"
        )
        for metric in ("statements", "branches", "functions", "lines"):
            self.assertIn(f"--coverage.thresholds.{metric}=0", bypass)
        scripts = json.loads((ROOT / "package.json").read_text())["scripts"]
        self.assertEqual("vitest run --coverage", scripts["test:coverage"])
        config = (ROOT / "vitest.config.mts").read_text()
        self.assertIn(
            "thresholds: { statements: 80, branches: 80, functions: 80, lines: 80 }", config
        )

    def test_the_coverage_comment_holds_the_write_token_and_runs_no_code(self) -> None:
        job = jobs()["frontend-coverage-comment"]
        self.assertEqual({"pull-requests": "write"}, job["permissions"])
        self.assertEqual("frontend-coverage", job["needs"])
        for step in job["steps"]:
            with self.subTest(step=step.get("name")):
                self.assertNotIn("run", step)
                self.assertTrue(step.get("continue-on-error"), "the comment never gates")
                action = step["uses"].split("@")[0]
                self.assertIn(
                    action,
                    {
                        "actions/download-artifact",
                        "peter-evans/find-comment",
                        "peter-evans/create-or-update-comment",
                    },
                )
                self.assertRegex(step["uses"], r"@[0-9a-f]{40}$")

    def test_the_macos_job_runs_the_lifecycle_tests_once_and_no_browser_proof(self) -> None:
        """The browser proofs left the gate (owner, 2026-10-12): the UI is verified by the Storybook job."""
        steps = jobs()["frontend"]["steps"]
        matches = [step for step in steps if step.get("run") == "pnpm test:dev"]
        self.assertEqual(1, len(matches), "the lifecycle tests run exactly once")
        step = matches[0]
        self.assertNotIn("if", step)
        self.assertNotIn("continue-on-error", step)
        self.assertGreater(step.get("timeout-minutes", 0), 0)
        self.assertEqual(
            "${{ steps.python.outputs.python-path }}", step["env"]["COMPASS_TEST_PYTHON"]
        )
        for name in ("frontend", "frontend-production"):
            with self.subTest(job=name):
                commands = [step.get("run", "") for step in jobs()[name]["steps"]]
                self.assertFalse(
                    any(":browser" in command or "playwright" in command for command in commands),
                    commands,
                )
                self.assertFalse(any("pnpm test:installed" in command for command in commands))

    def test_each_browser_script_runs_every_proof_it_names(self) -> None:
        """A script that chains two proofs is one workflow step, so the step test alone cannot see one dropped."""
        scripts = json.loads((ROOT / "package.json").read_text())["scripts"]
        expected = {
            "test:terminal:browser": ("terminal-parity.mjs", "timeline-filter.mjs"),
            "test:sessions:browser": ("sessions-parity.mjs",),
            "test:intent:browser": ("intent-parity.mjs",),
            "test:drift:browser": ("drift-parity.mjs",),
            "test:project:browser": ("project-parity.mjs",),
            "test:console:browser": ("console-parity.mjs",),
            "test:attention:browser": ("attention-parity.mjs",),
            "test:capacity:browser": ("capacity-parity.mjs",),
            "test:shell:browser": ("shell-routing.mjs",),
            "test:controls:browser": ("controls-continuity.mjs", "popover-continuity.mjs"),
            "test:storage:browser": ("storage-conformance.mjs",),
            "test:css:browser": ("css-contract.mjs",),
        }
        for name, files in expected.items():
            for file in files:
                with self.subTest(script=name, proof=file):
                    self.assertIn(f"frontend/e2e/{file}", scripts[name])

    def test_production_bundle_job_compares_the_rebuilt_artifact_and_runs_no_proof(self) -> None:
        job = jobs()["frontend-production"]
        self.assertEqual("ubuntu-latest", job["runs-on"])
        self.assertEqual("changes", job["needs"])
        self.assertEqual("needs.changes.outputs.code == 'true'", job["if"])
        self.assertNotIn("strategy", job, "one rebuild, no shards")
        self.assertLessEqual(job["timeout-minutes"], 15)
        self.assertNotIn("permissions", job, "the job inherits the workflow's read-only token")
        self.assertEqual("read", yaml.safe_load(WORKFLOW.read_text())["permissions"]["contents"])
        self.assertEqual("Frontend production bundle (ubuntu-latest)", job["name"])
        steps = job["steps"]
        for step in steps:
            self.assertNotIn("continue-on-error", step)
            self.assertNotIn("secrets", json.dumps(step))
            if "run" in step:
                self.assertGreater(step.get("timeout-minutes", 0), 0)
        commands = [step.get("run") for step in steps]
        self.assertEqual(1, commands.count("pnpm build:check"))
        build = steps[commands.index("pnpm build:check")]
        self.assertNotIn("if", build)
        self.assertLess(
            commands.index("pnpm install --frozen-lockfile --ignore-scripts"),
            commands.index("pnpm build:check"),
        )

    def test_storybook_job_builds_and_tests_offline_in_pinned_chromium(self) -> None:
        job = jobs()["storybook"]
        self.assertEqual("Storybook (ubuntu-latest)", job["name"])
        self.assertEqual("ubuntu-latest", job["runs-on"])
        self.assertLessEqual(job["timeout-minutes"], 15)
        commands = [step.get("run") for step in job["steps"]]
        ordered = [
            "pnpm install --frozen-lockfile --ignore-scripts",
            "pnpm build:storybook",
            "pnpm exec playwright install --with-deps chromium",
            "pnpm test:stories",
        ]
        self.assertEqual(ordered, [command for command in commands if command])
        for step in job["steps"]:
            if "run" in step:
                self.assertGreater(step.get("timeout-minutes", 0), 0)
                self.assertNotIn("if", step)

    def test_no_frontend_job_can_fail_open(self) -> None:
        """A job-level `continue-on-error` makes `needs.<job>.result` read success for a red job; a weakened `if`
        lets the job skip where the aggregator expects it to run."""
        workflow_jobs = jobs()
        for name in ("frontend", "frontend-coverage", "frontend-production", "storybook"):
            with self.subTest(job=name):
                job = workflow_jobs[name]
                self.assertNotIn("continue-on-error", job)
                self.assertEqual("changes", job["needs"])
                self.assertEqual("needs.changes.outputs.code == 'true'", job["if"])
                for step in job["steps"]:
                    self.assertNotIn("continue-on-error", step)
        self.assertNotIn("continue-on-error", workflow_jobs["quality-gate"])

    def test_production_runner_refuses_an_unknown_argument_before_running_anything(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        runner = str(ROOT / "frontend/e2e/production-proofs.mjs")
        for arguments in (
            ["--bogus"],
            ["--shards", "a"],
            ["--shard"],
            ["--shard", "zz"],
            ["--", "--shard", "a"],
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [node, runner, *arguments],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=20,
                )
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("Usage:", result.stderr)
                self.assertNotIn("===", result.stdout, "a proof started")

    def test_native_build_is_separate_from_the_canonical_artifact_check(self) -> None:
        steps = jobs()["frontend"]["steps"]
        commands = {step.get("run"): step for step in steps if "run" in step}
        for command in (
            "pnpm lint",
            "pnpm typecheck",
            "pnpm test",
            "pnpm test:dev",
            "pnpm build:preview",
        ):
            self.assertIn(command, commands)
            self.assertNotIn("if", commands[command])
        self.assertNotIn("pnpm build:check", commands)
        production_build = next(
            step
            for step in jobs()["frontend-production"]["steps"]
            if step.get("run") == "pnpm build:check"
        )
        self.assertNotIn("if", production_build)
        self.assertTrue(all("pnpm preview" not in command for command in commands))
        self.assertTrue(all("pnpm test:browser" not in command for command in commands))
        self.assertTrue(all(step.get("timeout-minutes", 0) > 0 for step in steps if "run" in step))
        python = next(step for step in steps if step.get("id") == "python")
        self.assertEqual("3.11", python["with"]["python-version"])

    def test_no_step_runs_the_retired_embedded_linter_or_a_legacy_recording_mode(self) -> None:
        # The embedded linter checked the previous interface's sources and went with them; Biome,
        # strict types, the unit tests, Storybook and `pnpm build:check` (the production job) are what
        # check the React sources and the page built from them.
        text = WORKFLOW.read_text()
        self.assertNotIn("lint_embedded", text)
        self.assertNotIn("COMPASS_LEGACY", text)
        lint_steps = [step.get("run", "") for step in jobs()["lint"]["steps"]]
        self.assertFalse(any("scripts/" in command for command in lint_steps), lint_steps)
        frontend = {step.get("run") for step in jobs()["frontend"]["steps"]}
        for command in ("pnpm lint", "pnpm typecheck", "pnpm test"):
            self.assertIn(command, frontend)


if __name__ == "__main__":
    unittest.main()
