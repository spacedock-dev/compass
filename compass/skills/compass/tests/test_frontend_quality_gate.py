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
    def test_sources_builds_and_relevant_workflows_run_the_frontend_lane(self) -> None:
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


# Each result the aggregate reads, and the detector outputs that must all be on for its job to run.
LANES_OF = {
    "R_LINT": ("LINT",),
    "R_TYPECHECK": ("PYTHON",),
    "R_FLOOR": ("SUITES",),
    "R_TEST": ("PYTHON",),
    "R_COVERAGE": ("PYTHON",),
    "R_PLATFORM": ("PYTHON", "PLATFORM"),
    "R_PLATFORM_CURRENT": ("PYTHON",),
    "R_FRONTEND": ("FRONTEND",),
    "R_FRONTEND_MACOS": ("FRONTEND", "PLATFORM"),
    "R_FRONTEND_COVERAGE": ("FRONTEND",),
    "R_FRONTEND_PRODUCTION": ("FRONTEND",),
    "R_STORYBOOK": ("FRONTEND",),
    "R_CONTRACT": ("CONTRACT",),
    "R_FRONTEND_DOCS": ("FRONTEND_DOCS",),
}
ALL_ON = {
    "PYTHON": "true",
    "LINT": "true",
    "FRONTEND": "true",
    "CONTRACT": "true",
    "SUITES": "true",
    "FRONTEND_DOCS": "true",
    "PLATFORM": "true",
}
ALL_OFF = dict.fromkeys(ALL_ON, "false")
# The aggregate's env name for each job's result, and the job it reads.
RESULT_OF = {
    "R_LINT": "lint",
    "R_TYPECHECK": "typecheck",
    "R_FLOOR": "runtime-floor",
    "R_TEST": "test",
    "R_COVERAGE": "coverage",
    "R_PLATFORM": "platform-tests",
    "R_PLATFORM_CURRENT": "platform-tests-current",
    "R_FRONTEND": "frontend",
    "R_FRONTEND_MACOS": "frontend-macos",
    "R_FRONTEND_COVERAGE": "frontend-coverage",
    "R_FRONTEND_PRODUCTION": "frontend-production",
    "R_STORYBOOK": "storybook",
    "R_CONTRACT": "frontend-contract",
    "R_FRONTEND_DOCS": "frontend-docs",
}


@unittest.skipUnless(detector.BASH, "the shipped aggregate uses Bash")
class FrontendAggregateControlsTest(unittest.TestCase):
    def aggregate(
        self, *, lanes: dict[str, str], results: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        script = next(step["run"] for step in jobs()["quality-gate"]["steps"] if "run" in step)
        return subprocess.run(
            [detector.BASH or "bash", "-c", script],
            env={**os.environ, **lanes, "R_CHANGES": "success", **results},
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

    def test_every_required_result_rejects_failure_cancellation_and_unexpected_skip(self) -> None:
        successful = dict.fromkeys(LANES_OF, "success")
        for name in successful:
            for bad in ("failure", "cancelled", "skipped"):
                with self.subTest(name=name, bad=bad):
                    result = self.aggregate(lanes=ALL_ON, results={**successful, name: bad})
                    self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertEqual(0, self.aggregate(lanes=ALL_ON, results=successful).returncode)

    def test_a_job_may_skip_only_when_its_own_lane_is_off(self) -> None:
        skipped = dict.fromkeys(LANES_OF, "skipped")
        self.assertEqual(0, self.aggregate(lanes=ALL_OFF, results=skipped).returncode)
        for bad in ("failure", "cancelled", "skipped"):
            with self.subTest(detector=bad):
                self.assertNotEqual(
                    0,
                    self.aggregate(lanes=ALL_OFF, results={**skipped, "R_CHANGES": bad}).returncode,
                )
        for name in LANES_OF:
            with self.subTest(failed=name):
                self.assertNotEqual(
                    0,
                    self.aggregate(lanes=ALL_OFF, results={**skipped, name: "failure"}).returncode,
                )
        # One lane on: its jobs must have run, and every other job may skip.
        for lane in ALL_ON:
            on = {name for name, owners in LANES_OF.items() if owners == (lane,)}
            lanes = {**ALL_OFF, lane: "true"}
            with self.subTest(lane=lane):
                ran = {name: ("success" if name in on else "skipped") for name in LANES_OF}
                self.assertEqual(0, self.aggregate(lanes=lanes, results=ran).returncode)
                for name in on:
                    result = self.aggregate(lanes=lanes, results={**ran, name: "skipped"})
                    self.assertNotEqual(0, result.returncode, name)

    def test_a_macos_leg_may_skip_when_platform_is_off_and_not_when_it_is_on(self) -> None:
        macos = {name for name, owners in LANES_OF.items() if "PLATFORM" in owners}
        self.assertEqual({"R_PLATFORM", "R_FRONTEND_MACOS"}, macos)
        for name in sorted(macos):
            lanes = {**ALL_OFF, **dict.fromkeys(LANES_OF[name], "true")}
            ran = {
                other: (
                    "success"
                    if set(owners) <= {k for k, v in lanes.items() if v == "true"}
                    else "skipped"
                )
                for other, owners in LANES_OF.items()
            }
            with self.subTest(job=name):
                self.assertEqual(0, self.aggregate(lanes=lanes, results=ran).returncode)
                # The lane it shares is on and platform is off: the leg skipped on purpose.
                off = {**lanes, "PLATFORM": "false"}
                skipped = {**ran, name: "skipped"}
                self.assertEqual(0, self.aggregate(lanes=off, results=skipped).returncode)
                # Both on and the leg skipped: a dependency died, which is a failure.
                result = self.aggregate(lanes=lanes, results=skipped)
                self.assertNotEqual(0, result.returncode, result.stdout)

    def test_a_platform_answer_that_is_neither_true_nor_false_fails_the_gate(self) -> None:
        # Every other lane fails closed on a missing output; a lost `platform` must not read as off.
        python_only = {
            name: ("skipped" if "PLATFORM" in owners else "success")
            for name, owners in LANES_OF.items()
        }
        for value in ("", "True", "yes"):
            with self.subTest(platform=value):
                result = self.aggregate(lanes={**ALL_ON, "PLATFORM": value}, results=python_only)
                self.assertNotEqual(0, result.returncode, result.stdout)

    def test_the_aggregate_reads_every_job_it_needs(self) -> None:
        aggregate = jobs()["quality-gate"]
        env = aggregate["steps"][0]["env"]
        for variable, job in RESULT_OF.items():
            with self.subTest(job=job):
                self.assertEqual(f"${{{{ needs.{job}.result }}}}", env[variable])
                self.assertIn(job, aggregate["needs"])
        for output in ("frontend_docs", "platform"):
            with self.subTest(output=output):
                self.assertIn(f"needs.changes.outputs.{output}", json.dumps(env))
        self.assertEqual(
            set(RESULT_OF), {key for key in env if key.startswith("R_")} - {"R_CHANGES"}
        )


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
            [{"suite": "dashboard", "shard": 2}, {"suite": "dashboard", "shard": 3}],
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
        self.assertEqual("needs.changes.outputs.frontend == 'true'", frontend["if"])
        for name, lane in (
            ("lint", "lint"),
            ("typecheck", "python"),
            ("test", "python"),
            ("coverage", "python"),
            ("runtime-floor", "python_suites"),
            ("frontend-contract", "contract"),
            ("frontend-docs", "frontend_docs"),
            ("platform-tests-current", "python"),
        ):
            with self.subTest(job=name):
                self.assertEqual(
                    f"needs.changes.outputs.{lane} == 'true'", workflow_jobs[name]["if"]
                )
        # A macOS leg runs only where macOS can differ from the Linux run beside it.
        for name, lane in (
            ("platform-tests", "python"),
            ("frontend-macos", "frontend"),
        ):
            with self.subTest(job=name):
                self.assertEqual(
                    f"needs.changes.outputs.{lane} == 'true' && "
                    "needs.changes.outputs.platform == 'true'",
                    workflow_jobs[name]["if"],
                )
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
            },
            set(aggregate["needs"]),
        )
        self.assertNotIn("frontend-coverage-comment", aggregate["needs"], "the comment never gates")
        env = aggregate["steps"][0]["env"]
        self.assertEqual("${{ needs.test.result }}", env["R_TEST"])
        self.assertEqual("${{ needs.coverage.result }}", env["R_COVERAGE"])
        self.assertEqual("${{ needs.frontend.result }}", env["R_FRONTEND"])
        self.assertEqual("${{ needs.frontend-coverage.result }}", env["R_FRONTEND_COVERAGE"])
        self.assertEqual("${{ needs.frontend-production.result }}", env["R_FRONTEND_PRODUCTION"])
        self.assertEqual("${{ needs.storybook.result }}", env["R_STORYBOOK"])
        self.assertEqual("${{ needs.frontend-contract.result }}", env["R_CONTRACT"])
        self.assertNotIn("frontend-proofs", workflow_jobs)
        self.assertNotIn("R_FRONTEND_PROOFS", env)

    def test_runtime_floor_runs_as_parallel_legs_with_one_smoke_launch(self) -> None:
        floor = jobs()["runtime-floor"]
        matrix = floor["strategy"]["matrix"]
        # The dashboard suite and the script suite in three shards, one runner each, like
        # `platform-tests`: serial in one job they took 557 s, and the script suite set the wall clock.
        self.assertEqual(["dashboard", "scripts"], matrix["suite"])
        self.assertEqual([1, 2, 3], matrix["shard"])
        self.assertEqual(
            [{"suite": "dashboard", "shard": 2}, {"suite": "dashboard", "shard": 3}],
            matrix["exclude"],
        )
        self.assertFalse(floor["strategy"]["fail-fast"])
        by_name = {step["name"]: step for step in floor["steps"] if "name" in step}
        smoke = by_name["Direct-launch smoke on the supported floor"]
        self.assertEqual("matrix.suite == 'dashboard'", smoke["if"], "the launch runs once")
        self.assertIn("server.py", smoke["run"])
        dashboard = by_name["Run dashboard test discovery on the floor"]
        scripts = by_name["Run script unit tests on the floor"]
        self.assertEqual("matrix.suite == 'dashboard'", dashboard["if"])
        self.assertEqual("matrix.suite == 'scripts'", scripts["if"])
        self.assertIn("--shard ${{ matrix.shard }}/3", scripts["run"])
        self.assertNotIn("--shard", dashboard["run"])
        # Together the legs run the same two suites the single job ran, with nothing left out.
        self.assertIn("-s compass/skills/compass/tests -t .", dashboard["run"])
        self.assertIn("-s scripts/tests -t scripts/tests", scripts["run"])
        # The shard count in the command is the count in the matrix, or a shard would never run.
        self.assertEqual(len(matrix["shard"]), int(scripts["run"].split("}}/")[1].split()[0]))
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
        install = commands.index("pnpm install --frozen-lockfile --ignore-scripts")
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
        self.assertEqual("needs.changes.outputs.frontend == 'true'", job["if"])
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
        commands = [step["run"] for step in job["steps"] if "run" in step]
        ordered = [
            "pnpm install --frozen-lockfile --ignore-scripts",
            "pnpm build:storybook",
            "pnpm exec playwright install chromium",
            "pnpm exec playwright install-deps chromium",
            "pnpm test:stories",
        ]
        self.assertEqual(len(ordered), len(commands), commands)
        for fragment, command in zip(ordered, commands, strict=True):
            self.assertIn(fragment, command)
        self.assertNotIn("--with-deps", json.dumps(job), "the host packages install on their own")
        for step in job["steps"]:
            if "run" in step:
                self.assertGreater(step.get("timeout-minutes", 0), 0)
                self.assertNotIn("if", step)


@unittest.skipUnless(detector.BASH, "the shipped steps use Bash")
class StorybookChromiumInstallTest(unittest.TestCase):
    """Chromium and its host packages install fresh on every run, the packages bounded and retried once.

    Measured on the two timed-out runs (2026-11-06): the browser download took about 6 s on each, and
    the step spent its whole 5 minutes fetching nine font packages (21.9 MB) from the Ubuntu mirror at
    tens of KB/s. Every other library Chromium needs was already on the runner image.

    Nothing is restored from a cache (owner ruling, 2026-11-06). actions/cache extracts an entry with
    `tar -xf ARCHIVE -P -C WORKSPACE`, and `-P` keeps `../` and absolute member names, so an entry that
    third-party code shaped in one main-branch run could plant files that every later run executes.
    """

    @staticmethod
    def steps() -> list[dict[str, Any]]:
        return cast("list[dict[str, Any]]", jobs()["storybook"]["steps"])

    def step_running(self, fragment: str) -> dict[str, Any]:
        matches = [step for step in self.steps() if fragment in step.get("run", "")]
        self.assertEqual(1, len(matches), fragment)
        return matches[0]

    def run_step(
        self, step: dict[str, Any], cwd: Path, env: dict[str, str]
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [detector.BASH or "bash", "-c", step["run"]],
            cwd=cwd,
            env={**os.environ, **env},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_the_job_restores_and_saves_no_cache(self) -> None:
        steps = self.steps()
        for step in steps:
            with self.subTest(step=step.get("name") or step.get("uses")):
                # `actions/cache`, `actions/cache/restore` and `actions/cache/save` alike.
                self.assertFalse(step.get("uses", "").startswith("actions/cache"))
        node = next(s for s in steps if s.get("uses", "").startswith("actions/setup-node@"))
        self.assertFalse(node["with"]["package-manager-cache"])
        manager = next(s for s in steps if s.get("uses", "").startswith("pnpm/setup@"))
        self.assertFalse(manager["with"]["cache"])
        # With nothing to restore, apt keeps its own archive directory: nothing points it at a path
        # a cache used to fill.
        packages = self.step_running("install-deps")["run"]
        self.assertNotIn("Dir::Cache", packages)
        self.assertNotIn(".cache", packages)
        browser = self.step_running("pnpm exec playwright install chromium")
        self.assertLess(steps.index(browser), steps.index(self.step_running("install-deps")))
        self.assertLess(
            steps.index(self.step_running("install-deps")),
            steps.index(self.step_running("pnpm test:stories")),
        )

    def install_deps(self, failures: int) -> tuple[int, list[str]]:
        """Run the shipped host-package step with `pnpm` failing its first `failures` calls."""
        step = self.step_running("install-deps")
        with tempfile.TemporaryDirectory(prefix="bld-hyg-sb-") as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            calls = Path(tmp) / "calls"
            fakes = {
                # Root is not available here: the fake swallows what the step pipes to it.
                "sudo": "#!/bin/sh\ncat > /dev/null\n",
                # Records the bound it was given, then runs the command without one.
                "timeout": (
                    '#!/bin/sh\nwhile [ "${1#-}" != "$1" ]; do shift; done\n'
                    f'echo "bound $1" >> "{calls}"\nshift\nexec "$@"\n'
                ),
                "pnpm": (
                    f'#!/bin/sh\necho "pnpm $*" >> "{calls}"\n'
                    f'[ "$(grep -c "^pnpm" "{calls}")" -gt {failures} ]\n'
                ),
            }
            for name, body in fakes.items():
                (bin_dir / name).write_text(body)
                (bin_dir / name).chmod(0o755)
            result = self.run_step(
                step,
                Path(tmp),
                {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": tmp},
            )
            return result.returncode, calls.read_text().splitlines()

    def test_the_host_packages_get_one_bounded_retry_and_no_more(self) -> None:
        limit = self.step_running("install-deps")["timeout-minutes"] * 60
        for failures, ok in ((0, True), (1, True), (2, False), (5, False)):
            with self.subTest(failures=failures):
                code, calls = self.install_deps(failures)
                self.assertEqual(ok, code == 0, calls)
                attempts = [line for line in calls if line.startswith("pnpm")]
                self.assertEqual(min(failures + 1, 2), len(attempts), calls)
                self.assertTrue(
                    all(line == "pnpm exec playwright install-deps chromium" for line in attempts)
                )
                bounds = [int(line.split()[1]) for line in calls if line.startswith("bound")]
                self.assertEqual(len(attempts), len(bounds), "every attempt is bounded")
                # Both attempts fit inside the step's own limit, so the retry can actually run.
                self.assertLess(2 * max(bounds), limit)
                # A retry resumes from the same mirror, so the cold path's real budget is the sum.
                # It must not be less than the 300 s the old single `--with-deps` step had.
                self.assertGreaterEqual(2 * min(bounds), 300)

    def test_no_frontend_job_can_fail_open(self) -> None:
        """A job-level `continue-on-error` makes `needs.<job>.result` read success for a red job; a weakened `if`
        lets the job skip where the aggregator expects it to run."""
        workflow_jobs = jobs()
        for name, condition in (
            ("frontend", "needs.changes.outputs.frontend == 'true'"),
            (
                "frontend-macos",
                (
                    "needs.changes.outputs.frontend == 'true' && "
                    "needs.changes.outputs.platform == 'true'"
                ),
            ),
            ("frontend-coverage", "needs.changes.outputs.frontend == 'true'"),
            ("frontend-production", "needs.changes.outputs.frontend == 'true'"),
            ("storybook", "needs.changes.outputs.frontend == 'true'"),
            ("frontend-contract", "needs.changes.outputs.contract == 'true'"),
            ("frontend-docs", "needs.changes.outputs.frontend_docs == 'true'"),
        ):
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
