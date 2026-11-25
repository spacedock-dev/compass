"""The required gate measures frontend changes and cannot hide a failed matrix."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

from . import test_quality_gate as detector
from .test_workflow_caches import BOOTSTRAP_RUN, assert_locked_pnpm

ROOT = Path(__file__).resolve().parents[4]
WORKFLOW = ROOT / ".github/workflows/quality-gate.yml"


def jobs() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(WORKFLOW.read_text())["jobs"])


@unittest.skipUnless(detector.BASH, "the shipped gate uses Bash")
class FrontendDetectorControlsTest(unittest.TestCase):
    def test_sources_builds_and_relevant_workflows_run_the_frontend_lane(self) -> None:
        for path in (
            "frontend/src/main.tsx",
            "frontend/test/setup.ts",
            "pnpm-lock.yaml",
            "tools/pnpm-bootstrap/package.json",
            "tools/pnpm-bootstrap/package-lock.json",
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
                self.assertEqual("true", detector.detect_in_process(path)["frontend"])

    def test_the_shipped_step_agrees_for_a_frontend_path(self) -> None:
        # The in-process cases above call ci_scope.scope directly; this is the one real run of the
        # workflow step, so the wiring around that call cannot drift from them unseen. A source path
        # that only the frontend lane claims, so the answer differs from the fail-open one.
        path = "frontend/src/main.tsx"
        expected = detector.detect_in_process(path)
        self.assertEqual("false", expected["python"], "a fail-open answer would read true here")
        self.assertEqual(expected, detector.QualityGateDetectorTest().detect(path))

    def test_actual_frontend_doc_reads_precede_prose_classification(self) -> None:
        # Real temporary source inputs, not an invented detector result.
        with tempfile.TemporaryDirectory(prefix="frontend-doc-filter-") as temp:
            root = Path(temp)
            builder = root / "frontend/build/package.mjs"
            builder.parent.mkdir(parents=True)
            builder.write_text(
                "const WEB = 'web';\nasync function authoredSources(root) {\n"
                "  const files = [\n    '.gitattributes',\n  ];\n}\n"
            )
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
            # Read by a Vitest file: that file runs, not the lane.
            for path in (root_doc, quoted_doc):
                with self.subTest(path=path):
                    found = probe.detect(path, root=root)
                    self.assertEqual(
                        ("false", "true", "frontend/test/setup.test.ts"),
                        (found["frontend"], found["frontend_docs"], found["frontend_docs_tests"]),
                    )
            # Cited, with no citation check in this tree to run: the whole lane stands in.
            self.assertEqual("true", probe.detect(cited_doc, root=root)["frontend"])
            source.unlink()
            for path in (root_doc, quoted_doc):
                found = probe.detect(path, root=root)
                self.assertEqual(("false", "false"), (found["frontend"], found["frontend_docs"]))
            # An unreadable source scan cannot authorize the prose skip path.
            source.write_bytes(b"\xff")
            found = probe.detect(root_doc, root=root)
            self.assertEqual(("true", "true"), (found["python"], found["frontend"]))

    def test_unrelated_workflow_prose_keeps_its_short_path(self) -> None:
        found = detector.QualityGateDetectorTest().detect(".github/workflows/version-guard.yml")
        self.assertEqual(("false", "false"), (found["python"], found["frontend"]))


# Every gate job the aggregate reads, from the detector's own table.
JOBS = tuple(detector._ci_scope().EVERYTHING.jobs())


@unittest.skipUnless(detector.BASH, "the shipped aggregate uses Bash")
class FrontendAggregateControlsTest(unittest.TestCase):
    def aggregate(
        self,
        *,
        runs: Mapping[str, object] | str,
        results: dict[str, str],
        changes: str = "success",
    ) -> subprocess.CompletedProcess[str]:
        script = next(step["run"] for step in jobs()["quality-gate"]["steps"] if "run" in step)
        needs = {"changes": {"result": changes, "outputs": {}}}
        needs |= {job: {"result": result, "outputs": {}} for job, result in results.items()}
        return subprocess.run(
            [detector.BASH or "bash", "-c", script],
            env={
                **os.environ,
                "R_CHANGES": changes,
                "JOBS": runs if isinstance(runs, str) else json.dumps(runs),
                "NEEDS": json.dumps(needs),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_every_job_that_should_run_rejects_failure_cancellation_and_skip(self) -> None:
        runs = dict.fromkeys(JOBS, True)
        successful = dict.fromkeys(JOBS, "success")
        self.assertEqual(0, self.aggregate(runs=runs, results=successful).returncode)
        for job in JOBS:
            for bad in ("failure", "cancelled", "skipped"):
                with self.subTest(job=job, bad=bad):
                    result = self.aggregate(runs=runs, results={**successful, job: bad})
                    self.assertNotEqual(0, result.returncode, result.stdout)

    def test_a_job_may_skip_only_when_the_detector_said_not_to_run_it(self) -> None:
        skipped = dict.fromkeys(JOBS, "skipped")
        nothing = dict.fromkeys(JOBS, False)
        self.assertEqual(0, self.aggregate(runs=nothing, results=skipped).returncode)
        for bad in ("failure", "cancelled", "skipped"):
            with self.subTest(detector=bad):
                result = self.aggregate(runs=nothing, results=skipped, changes=bad)
                self.assertNotEqual(0, result.returncode)
        for job in JOBS:
            with self.subTest(failed=job):
                result = self.aggregate(runs=nothing, results={**skipped, job: "failure"})
                self.assertNotEqual(0, result.returncode)
            # Only this job should run: it must have, and every other job may skip.
            only = {**nothing, job: True}
            ran = {**skipped, job: "success"}
            with self.subTest(only=job):
                self.assertEqual(0, self.aggregate(runs=only, results=ran).returncode)
                result = self.aggregate(runs=only, results=skipped)
                self.assertNotEqual(0, result.returncode, result.stdout)

    def test_a_lost_or_garbled_answer_fails_the_gate(self) -> None:
        # Every job skipped would pass if any of these read as "run nothing".
        skipped = dict.fromkeys(JOBS, "skipped")
        nothing = dict.fromkeys(JOBS, False)
        for runs in ("", "null", "[]", "{", json.dumps({**nothing, "lint": "false"})):
            with self.subTest(runs=runs):
                result = self.aggregate(runs=runs, results=skipped)
                self.assertNotEqual(0, result.returncode, result.stdout)

    def test_the_detector_and_the_aggregate_must_name_the_same_jobs(self) -> None:
        successful = dict.fromkeys(JOBS, "success")
        runs = dict.fromkeys(JOBS, True)
        missing = dict(list(runs.items())[1:])
        extra = {**runs, "new-job": True}
        for found in (missing, extra):
            with self.subTest(names=sorted(found)):
                result = self.aggregate(runs=found, results=successful)
                self.assertNotEqual(0, result.returncode, result.stdout)
        # A job the aggregate needs and the detector never names fails too.
        result = self.aggregate(runs=runs, results={**successful, "new-job": "success"})
        self.assertNotEqual(0, result.returncode, result.stdout)

    def test_the_aggregate_reads_every_job_it_needs_and_each_job_reads_its_answer(self) -> None:
        workflow = jobs()
        aggregate = workflow["quality-gate"]
        self.assertEqual({"changes", *JOBS}, set(aggregate["needs"]))
        env = aggregate["steps"][0]["env"]
        self.assertEqual(
            {
                "R_CHANGES": "${{ needs.changes.result }}",
                "JOBS": "${{ needs.changes.outputs.jobs }}",
                "NEEDS": "${{ toJSON(needs) }}",
            },
            env,
        )
        self.assertEqual("${{ steps.detect.outputs.jobs }}", workflow["changes"]["outputs"]["jobs"])
        for job in JOBS:
            with self.subTest(job=job):
                self.assertEqual(detector.runs_if(job), workflow[job]["if"])
                needs = workflow[job]["needs"]
                self.assertIn("changes", [needs] if isinstance(needs, str) else needs)
        # The fallback for a detector that cannot run names every job too.
        line = next(line for line in detector.detect_step().splitlines() if "jobs={" in line)
        named = set(re.findall(r'"([a-z-]+)":', line))
        self.assertEqual(set(JOBS), named)


class FrontendWiringControlsTest(unittest.TestCase):
    def test_the_css_ratchet_reads_the_actual_pr_base_without_shell_specific_variables(
        self,
    ) -> None:
        frontend = jobs()["frontend"]
        steps = frontend["steps"]
        ratchet = next((step for step in steps if step.get("run") == "pnpm test:styles"), None)
        self.assertIsNotNone(ratchet, "the PR base gate must remain on the Linux frontend job")
        assert ratchet is not None
        self.assertEqual("${{ github.event.pull_request.base.sha }}", ratchet["env"]["PR_BASE"])
        self.assertEqual("github.event_name == 'pull_request'", ratchet["if"])
        self.assertNotIn("continue-on-error", ratchet)
        checkout = next(
            step for step in steps if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertEqual(0, checkout["with"]["fetch-depth"])
        unit = next(
            step for step in jobs()["frontend-macos"]["steps"] if step.get("run") == "pnpm test"
        )
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
        self.assertEqual("ubuntu-latest", frontend["runs-on"])
        self.assertEqual("Frontend (ubuntu-latest)", frontend["name"])
        macos = workflow_jobs["frontend-macos"]
        self.assertEqual("macos-latest", macos["runs-on"])
        self.assertEqual("Frontend (macos-latest)", macos["name"])
        platform = workflow_jobs["platform-tests"]
        self.check_runners(platform, ["macos-latest"])
        # The two suites run as parallel legs so the slow script suite does not hold the dashboard one.
        self.assertEqual(["dashboard", "scripts"], platform["strategy"]["matrix"]["suite"])
        self.assertEqual([1, 2, 3], platform["strategy"]["matrix"]["shard"])
        self.assertEqual(
            [{"suite": "dashboard", "shard": 3}],
            platform["strategy"]["matrix"]["exclude"],
        )
        # The newest stable CPython on every Python change: on macOS beside the 3.12 leg above when
        # `platform` is on (3.12 takes the kqueue exit watch in supervise.py and 3.13 or newer takes
        # `os.waitid`, so each branch runs on its own OS), and on Linux otherwise, because no other
        # job runs that interpreter.
        current = workflow_jobs["platform-tests-current"]
        self.check_runners(
            current,
            [
                (
                    "${{ needs.changes.outputs.platform == 'true' "
                    "&& 'macos-latest' || 'ubuntu-latest' }}"
                )
            ],
        )
        self.assertEqual(
            "3.15",
            next(s for s in current["steps"] if "setup-python" in s.get("uses", ""))["with"][
                "python-version"
            ],
        )
        self.assertIn(
            "scripts/run_tests.py",
            next(s for s in current["steps"] if "run_tests" in s.get("run", ""))["run"],
        )
        gated = {step["name"]: step.get("if") for step in platform["steps"] if "if" in step}
        self.assertEqual(
            {
                "Run dashboard test discovery": "matrix.suite == 'dashboard'",
                "Run script unit tests": "matrix.suite == 'scripts'",
            },
            gated,
        )
        self.assertLessEqual(frontend["timeout-minutes"], 30)
        self.assertEqual("changes", frontend["needs"])
        self.assertEqual(detector.runs_if("frontend"), frontend["if"])
        # Which mode runs each job is the detector's (test_ci_scope); each job only reads it.
        for name in (
            "lint",
            "typecheck",
            "test",
            "coverage",
            "runtime-floor",
            "frontend-contract",
            "frontend-docs",
            "platform-tests",
            "platform-tests-current",
            "frontend-macos",
            "actionlint",
        ):
            with self.subTest(job=name):
                self.assertEqual(detector.runs_if(name), workflow_jobs[name]["if"])
        aggregate = workflow_jobs["quality-gate"]
        self.assertEqual("always()", aggregate["if"])
        self.assertEqual(
            {
                "changes",
                "lint",
                "typecheck",
                "runtime-floor",
                "test",
                "coverage",
                "platform-tests",
                "platform-tests-current",
                "frontend",
                "frontend-macos",
                "frontend-coverage",
                "frontend-production",
                "storybook",
                "frontend-contract",
                "frontend-docs",
                "actionlint",
            },
            set(aggregate["needs"]),
        )
        for comment in ("coverage-comment", "frontend-coverage-comment"):
            self.assertNotIn(comment, aggregate["needs"], "a comment never gates")
        self.assertNotIn("frontend-proofs", workflow_jobs)

    def test_runtime_floor_runs_as_parallel_legs_with_one_smoke_launch(self) -> None:
        floor = jobs()["runtime-floor"]
        matrix = floor["strategy"]["matrix"]
        # The dashboard suite in two shards and the script suite in three, one runner each, like
        # `platform-tests`: serial in one job they took 557 s, and the script suite set the wall clock.
        self.assertEqual(["dashboard", "scripts"], matrix["suite"])
        self.assertEqual([1, 2, 3], matrix["shard"])
        self.assertEqual([{"suite": "dashboard", "shard": 3}], matrix["exclude"])
        self.assertFalse(floor["strategy"]["fail-fast"])
        by_name = {step["name"]: step for step in floor["steps"] if "name" in step}
        smoke = by_name["Direct-launch smoke on the supported floor"]
        self.assertEqual(
            "matrix.suite == 'dashboard' && matrix.shard == 1", smoke["if"], "the launch runs once"
        )
        self.assertIn("server.py", smoke["run"])
        dashboard = by_name["Run dashboard test discovery on the floor"]
        scripts = by_name["Run script unit tests on the floor"]
        self.assertEqual("matrix.suite == 'dashboard'", dashboard["if"])
        self.assertEqual("matrix.suite == 'scripts'", scripts["if"])
        # The shard reaches the shell through env, never interpolated into `run`.
        self.assertEqual("${{ matrix.shard }}", scripts["env"]["SCRIPT_SHARD"])
        self.assertIn('--shard "$SCRIPT_SHARD/3"', scripts["run"])
        self.assertEqual("${{ matrix.shard }}", dashboard["env"]["DASHBOARD_SHARD"])
        self.assertIn('--shard "$DASHBOARD_SHARD/2"', dashboard["run"])
        # Together the legs run the same two suites the single job ran, with nothing left out.
        self.assertIn("-s compass/skills/compass/tests -t .", dashboard["run"])
        self.assertIn("-s scripts/tests -t scripts/tests", scripts["run"])
        # The shard count in the command is the count in the matrix, or a shard would never run.
        self.assertEqual(
            len(matrix["shard"]), int(scripts["run"].split("$SCRIPT_SHARD/")[1].split('"')[0])
        )
        # One job id, so the aggregator reads one result for every leg and a failed leg fails it.
        self.assertIn("runtime-floor", jobs()["quality-gate"]["needs"])

    def test_bootstrap_is_exact_without_auth_or_implicit_dependency_scripts(self) -> None:
        for name in (
            "frontend",
            "frontend-macos",
            "frontend-coverage",
            "frontend-production",
            "storybook",
            "frontend-contract",
            "frontend-docs",
        ):
            with self.subTest(job=name):
                self.check_bootstrap(jobs()[name])

    @staticmethod
    def label_check(step: dict[str, Any]) -> bool:
        return step.get("id") == "exception"

    def check_bootstrap(self, job: dict[str, Any]) -> None:
        steps = job["steps"]
        node = next(
            step for step in steps if step.get("uses", "").startswith("actions/setup-node@")
        )
        self.assertEqual(
            "actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1", node["uses"]
        )
        self.assertEqual(".node-version", node["with"]["node-version-file"])
        self.assertFalse(node["with"]["check-latest"])
        self.assertFalse(node["with"]["package-manager-cache"])
        commands = [step.get("run", "") for step in steps]
        assert_locked_pnpm(self, job)
        bootstrap = commands.index(BOOTSTRAP_RUN)
        self.assertLess(steps.index(node), bootstrap)
        checkout = next(
            step for step in steps if step.get("uses", "").startswith("actions/checkout@")
        )
        self.assertFalse(checkout["with"]["persist-credentials"])
        commands = [step.get("run", "") for step in steps]
        self.assertIn("pnpm install --frozen-lockfile --ignore-scripts", commands)
        self.assertFalse(any("corepack" in command.lower() for command in commands))
        install = commands.index("pnpm install --frozen-lockfile --ignore-scripts")
        self.assertLess(bootstrap, install)
        for index, step in enumerate(steps):
            self.assertNotIn("registry-url", step.get("with", {}))
            # The coverage-exception label check reads the PR with the job's read-only token. It is the
            # one step allowed a token, and it runs before any dependency is installed.
            if self.label_check(step):
                self.assertLess(index, install, "a token-bearing step runs before the install")
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
        self.assertEqual(
            "github.event_name == 'pull_request' || github.event_name == 'merge_group'", label["if"]
        )
        self.assertEqual("${{ github.token }}", label["env"]["GH_TOKEN"])
        self.assertEqual("python3 scripts/coverage_exception.py", label["run"])
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

    def test_each_coverage_comment_holds_the_write_token_and_runs_no_code(self) -> None:
        for name, source in (
            ("frontend-coverage-comment", "frontend-coverage"),
            ("coverage-comment", "coverage"),
        ):
            with self.subTest(job=name):
                self.assert_comment_job(name, source)

    def assert_comment_job(self, name: str, source: str) -> None:
        job = jobs()[name]
        self.assertEqual({"pull-requests": "write"}, job["permissions"])
        self.assertEqual(source, job["needs"])
        # Superseded runs post nothing, and a skipped coverage job leaves nothing to post.
        self.assertIn("!cancelled()", job["if"])
        self.assertIn(f"needs.{source}.result != 'skipped'", job["if"])
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository", job["if"]
        )
        upload = next(
            step for step in jobs()[source]["steps"] if "upload-artifact" in step.get("uses", "")
        )
        fetch = job["steps"][0]
        self.assertEqual(upload["with"]["name"], fetch["with"]["name"], "the artifact it posts")
        post = next(s for s in job["steps"] if "create-or-update-comment" in s.get("uses", ""))
        folder, body = post["with"]["body-path"].split("/", 1)
        self.assertEqual(fetch["with"]["path"], folder)
        self.assertIn(body, upload["with"]["path"], "the body is in the artifact it fetched")
        for step in job["steps"]:
            with self.subTest(job=name, step=step.get("name")):
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

    def test_the_coverage_comment_reads_only_its_own_attempts_summary(self) -> None:
        """The summary artifact is named for the attempt, so a re-run never posts an earlier one's figures.

        A re-run that fails before Vitest writes no summary, and actions/upload-artifact at the pinned
        SHA neither uploads nor deletes when it finds no files (src/upload/upload-artifact.ts), so a
        name shared across attempts would hand the comment job the earlier attempt's summary. Re-running
        `frontend-coverage` re-runs the comment job in the same attempt; the comment job re-run alone
        finds no summary for its attempt and posts nothing, which never gates.
        """
        upload = next(
            s
            for s in jobs()["frontend-coverage"]["steps"]
            if "upload-artifact" in s.get("uses", "")
        )
        download = next(
            s
            for s in jobs()["frontend-coverage-comment"]["steps"]
            if "download-artifact" in s.get("uses", "")
        )
        name = upload["with"]["name"]
        self.assertEqual(name, download["with"]["name"])
        self.assertIn("${{ github.run_id }}", name)
        self.assertIn("${{ github.run_attempt }}", name)
        self.assertEqual("always()", upload["if"], "a red threshold still reports its figures")
        self.assertEqual("ignore", upload["with"]["if-no-files-found"])

    def test_each_frontend_job_runs_the_lifecycle_tests_once_and_no_browser_proof(self) -> None:
        """The browser proofs left the gate (owner, 2026-10-12): the UI is verified by the Storybook job.

        `pnpm test:dev` runs on Linux for every frontend change and on macOS when `platform` is on,
        because its process handling is what the macOS leg exists for."""
        for name in ("frontend", "frontend-macos"):
            steps = jobs()[name]["steps"]
            matches = [step for step in steps if step.get("run") == "pnpm test:dev"]
            with self.subTest(job=name):
                self.assertEqual(1, len(matches), "the lifecycle tests run exactly once")
                step = matches[0]
                self.assertNotIn("if", step)
                self.assertNotIn("continue-on-error", step)
                self.assertGreater(step.get("timeout-minutes", 0), 0)
                self.assertEqual(
                    "${{ steps.python.outputs.python-path }}", step["env"]["COMPASS_TEST_PYTHON"]
                )
        for name in ("frontend", "frontend-macos", "frontend-production"):
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
        self.assertEqual(detector.runs_if("frontend-production"), job["if"])
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
        # The steps took about 4 minutes a run with nothing installed from apt.
        self.assertLessEqual(job["timeout-minutes"], 15)
        commands = [step["run"] for step in job["steps"] if "run" in step]
        ordered = [
            BOOTSTRAP_RUN,
            "pnpm install --frozen-lockfile --ignore-scripts",
            "pnpm build:storybook",
            "pnpm exec playwright install chromium",
            "pnpm test:parser",
            "pnpm test:installed",
            "pnpm test:stories",
        ]
        self.assertEqual(len(ordered), len(commands), commands)
        for fragment, command in zip(ordered, commands, strict=True):
            self.assertIn(fragment, command)
        # The job also runs on the contract lane for the release's two browser proofs; only the
        # Storybook steps wait for the frontend lane, and nothing else may be skipped.
        frontend_only = {"pnpm build:storybook", "pnpm test:stories"}
        # No host packages: the image carries every library Chromium needs (owner ruling, 2026-11-06).
        self.assertNotIn("--with-deps", json.dumps(job))
        self.assertNotIn("install-deps", json.dumps(job))
        self.assertNotIn("apt-get", json.dumps(job))
        for step in job["steps"]:
            if "run" in step:
                self.assertGreater(step.get("timeout-minutes", 0), 0)
                if step["run"] in frontend_only:
                    self.assertEqual("needs.changes.outputs.frontend == 'true'", step["if"])
                else:
                    self.assertNotIn("if", step)


@unittest.skipUnless(detector.BASH, "the shipped steps use Bash")
class StorybookChromiumInstallTest(unittest.TestCase):
    """Chromium installs fresh on every run, and no host package is installed.

    Measured 2026-11-06: the browser download takes about 6 s. `install-deps` added only nine font
    packages (21.9 MB) from the Azure Ubuntu mirror at about 35 KB/s, roughly 10 minutes a run, while
    every library Chromium needs was already on the image, and no story assertion reads a glyph. So
    nothing is installed from apt (owner ruling, 2026-11-06).

    Neither is restored from a cache (owner ruling, 2026-11-06). A restored entry's files run as they
    are, and the browser cache held the `chrome` binary the stories start. actions/cache also extracts
    with `tar -xf ARCHIVE -P -C WORKSPACE`, and `-P` keeps `../` and absolute member names, so an entry
    that third-party code shaped in one main-branch run could write outside its path as well.
    """

    @staticmethod
    def steps() -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", jobs()["storybook"]["steps"])

    def step_running(self, fragment: str) -> dict[str, Any]:
        matches = [step for step in self.steps() if fragment in step.get("run", "")]
        self.assertEqual(1, len(matches), fragment)
        return matches[0]

    def test_the_job_restores_and_saves_no_cache(self) -> None:
        steps = self.steps()
        # An allowlist rather than a ban on `actions/cache`: a third-party cache action, or
        # `actions/setup-python` with `cache: pip`, restores through the same `tar -P` extraction.
        # A new action fails here until someone has read what it restores.
        self.assertEqual(
            {"actions/checkout", "actions/setup-node", "actions/setup-python"},
            {step["uses"].split("@")[0] for step in steps if "uses" in step},
        )
        # setup-python is here for the installed proof's interpreter; `cache: pip` would restore.
        python = next(s for s in steps if s.get("uses", "").startswith("actions/setup-python@"))
        self.assertNotIn("cache", python.get("with", {}))
        for step in steps:
            for key, value in step.get("with", {}).items():
                with self.subTest(step=step.get("uses"), key=key):
                    # setup-node reads an explicit `cache: pnpm` before `package-manager-cache`
                    # (v7.0.0 src/main.ts), so every cache input is held off, not just the one
                    # that is set today.
                    if "cache" in key:
                        self.assertIs(False, value)
        node = next(s for s in steps if s.get("uses", "").startswith("actions/setup-node@"))
        self.assertIs(False, node["with"]["package-manager-cache"])
        browser = self.step_running("pnpm exec playwright install chromium")
        self.assertLess(steps.index(browser), steps.index(self.step_running("pnpm test:stories")))

    def test_nothing_is_installed_from_apt(self) -> None:
        for step in self.steps():
            with self.subTest(step=step.get("name")):
                text = json.dumps(step)
                self.assertNotIn("install-deps", text)
                self.assertNotIn("apt-get", text)
                self.assertNotIn("--with-deps", text)

    def test_no_frontend_job_can_fail_open(self) -> None:
        """A job-level `continue-on-error` makes `needs.<job>.result` read success for a red job; a weakened `if`
        lets the job skip where the aggregator expects it to run."""
        workflow_jobs = jobs()
        for name in (
            "frontend",
            "frontend-macos",
            "frontend-coverage",
            "frontend-production",
            "storybook",
            "frontend-contract",
            "frontend-docs",
        ):
            condition = detector.runs_if(name)
            with self.subTest(job=name):
                job = workflow_jobs[name]
                self.assertNotIn("continue-on-error", job)
                self.assertEqual("changes", job["needs"])
                self.assertEqual(condition, job["if"])
                for step in job["steps"]:
                    self.assertNotIn("continue-on-error", step)
        self.assertNotIn("continue-on-error", workflow_jobs["quality-gate"])

    def test_the_document_job_runs_exactly_the_files_the_detector_named_on_linux(self) -> None:
        job = jobs()["frontend-docs"]
        self.assertEqual("ubuntu-latest", job["runs-on"])
        self.assertLessEqual(job["timeout-minutes"], 15)
        self.assertNotIn("permissions", job, "the job inherits the workflow's read-only token")
        run = next(step for step in job["steps"] if "vitest run" in step.get("run", ""))
        self.assertEqual("${{ needs.changes.outputs.frontend_docs_tests }}", run["env"]["FILES"])
        self.assertIn("pnpm exec vitest run $FILES", run["run"])
        self.assertGreater(run["timeout-minutes"], 0)
        # An empty list with the lane on is a broken derivation, never a pass.
        self.assertIn("exit 1", run["run"])
        self.assertEqual(
            "${{ steps.detect.outputs.frontend_docs_tests }}",
            jobs()["changes"]["outputs"]["frontend_docs_tests"],
        )

    @unittest.skipUnless(detector.BASH, "the shipped step uses Bash")
    def test_the_document_job_refuses_an_empty_list(self) -> None:
        run = next(
            step["run"]
            for step in jobs()["frontend-docs"]["steps"]
            if "vitest run" in step.get("run", "")
        )
        result = subprocess.run(
            [detector.BASH or "bash", "-c", run],
            env={**os.environ, "FILES": ""},
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)

    def test_the_runtime_contract_runs_on_linux_unless_platform_is_on(self) -> None:
        self.assertEqual(
            "${{ needs.changes.outputs.platform == 'true' && 'macos-latest' || 'ubuntu-latest' }}",
            jobs()["frontend-contract"]["runs-on"],
        )

    def test_main_nightly_and_manual_runs_trigger_the_gate(self) -> None:
        workflow = yaml.safe_load(WORKFLOW.read_text())
        triggers = workflow.get("on", workflow.get(True))  # YAML 1.1 reads a bare `on` as true
        self.assertEqual(
            {"push", "pull_request", "merge_group", "schedule", "workflow_dispatch"}, set(triggers)
        )
        self.assertEqual(["main"], triggers["push"]["branches"])
        self.assertEqual(1, len(triggers["schedule"]))
        # A nightly run must not cancel a push run on main, or the reverse.
        self.assertIn("github.event_name", workflow["concurrency"]["group"])
        detect = next(s for s in jobs()["changes"]["steps"] if s.get("id") == "detect")
        self.assertEqual("${{ github.event_name }}", detect["env"]["EVENT"])

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
        # Linux runs every check a frontend change needs; Vitest runs there under coverage in
        # `frontend-coverage`, so this job runs the Node build tests rather than the suite again.
        expected = {
            "frontend": (
                "pnpm lint",
                "pnpm typecheck",
                "node --test frontend/build/*.test.mjs",
                "pnpm test:dev",
                "pnpm build:preview",
            ),
            "frontend-macos": ("pnpm test", "pnpm test:dev", "pnpm build:preview"),
        }
        for name, wanted in expected.items():
            steps = jobs()[name]["steps"]
            commands = {step.get("run"): step for step in steps if "run" in step}
            with self.subTest(job=name):
                for command in wanted:
                    self.assertIn(command, commands)
                    self.assertNotIn("if", commands[command])
                self.assertNotIn("pnpm build:check", commands)
                self.assertTrue(
                    all(step.get("timeout-minutes", 0) > 0 for step in steps if "run" in step)
                )
                python = next(step for step in steps if step.get("id") == "python")
                self.assertEqual("3.12", python["with"]["python-version"])
        self.assertNotIn("pnpm test", {step.get("run") for step in jobs()["frontend"]["steps"]})
        coverage = {step.get("run", "") for step in jobs()["frontend-coverage"]["steps"]}
        self.assertTrue(any("pnpm test:coverage" in command for command in coverage))
        steps = jobs()["frontend"]["steps"]
        commands = {step.get("run"): step for step in steps if "run" in step}
        production_build = next(
            step
            for step in jobs()["frontend-production"]["steps"]
            if step.get("run") == "pnpm build:check"
        )
        self.assertNotIn("if", production_build)
        self.assertTrue(all("pnpm preview" not in command for command in commands))
        self.assertTrue(all("pnpm test:browser" not in command for command in commands))

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
        for command in ("pnpm lint", "pnpm typecheck"):
            self.assertIn(command, frontend)


if __name__ == "__main__":
    unittest.main()
