"""The quality gate's lane detector: what each kind of change runs, and that it fails open."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_scope

ROOT = Path(__file__).resolve().parents[2]


_REPOSITORY_DOCUMENTS = (ci_scope.python_documents(ROOT), ci_scope.frontend_documents(ROOT))


def write_builder(root: Path) -> None:
    """The one file the detector needs in a temporary root: the bundle's own source list."""
    builder = root / "frontend/build/package.mjs"
    builder.parent.mkdir(parents=True, exist_ok=True)
    builder.write_text(
        "const WEB = 'web';\nasync function authoredSources(root) {\n"
        "  const files = [\n    '.gitattributes',\n    `${WEB}/page.py`,\n  ];\n}\n",
        encoding="utf-8",
    )


def lanes_of(*paths: str, root: Path = ROOT) -> dict[str, str]:
    # The repository's own scan is read once; a temporary root is scanned on every call.
    documents = _REPOSITORY_DOCUMENTS if root == ROOT else None
    return ci_scope.scope(list(paths), root, documents).outputs()


ALL_OFF = {
    "python": "false",
    "lint": "false",
    "frontend": "false",
    "contract": "false",
    "python_suites": "false",
    "frontend_docs": "false",
    "frontend_docs_tests": "",
    "platform": "false",
}
CHECK = "frontend/test/docCitations.test.ts"


class EachKindOfChangeRunsItsLaneTest(unittest.TestCase):
    def test_a_frontend_source_runs_the_frontend_lane_and_the_python_suites_once(self) -> None:
        # The Python suites read nearly every frontend file, so they run, but ruff, mypy, coverage
        # and the macOS legs do not.
        for path in ("frontend/src/main.tsx", "frontend/test/setup.ts", "frontend/vite.config.mts"):
            with self.subTest(path=path):
                self.assertEqual(
                    {**ALL_OFF, "frontend": "true", "python_suites": "true"}, lanes_of(path)
                )

    def test_the_frontend_toolchain_runs_the_frontend_lane(self) -> None:
        for path in (
            "pnpm-lock.yaml",
            "package.json",
            ".node-version",
            "biome.json",
            "tsconfig.json",
        ):
            with self.subTest(path=path):
                self.assertEqual("true", lanes_of(path)["frontend"])
                self.assertEqual("false", lanes_of(path)["python"])

    def test_a_runtime_change_runs_python_and_only_the_frontend_tests_that_read_it(self) -> None:
        for path in (
            "compass/skills/compass/server.py",
            "compass/skills/compass/compass_runtime/reading.py",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    {
                        **ALL_OFF,
                        "python": "true",
                        "lint": "true",
                        "contract": "true",
                        "python_suites": "true",
                    },
                    lanes_of(path),
                )

    def test_a_python_change_the_frontend_never_reads_runs_python_alone(self) -> None:
        for path in (
            "compass/skills/compass/tests/test_sessions.py",
            "compass/skills/compass/notify_hook.py",
            "compass-gemini/hooks/event_hook.py",
            "scripts/owned_observer.py",
            "pyproject.toml",
            "requirements-dev.txt",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    {**ALL_OFF, "python": "true", "lint": "true", "python_suites": "true"},
                    lanes_of(path),
                )

    def test_the_built_page_and_the_gates_own_wiring_run_both_lanes(self) -> None:
        for path in (
            "compass/skills/compass/compass_runtime/web/react.html",
            "compass/skills/compass/compass_runtime/web/page.py",
            ".github/workflows/quality-gate.yml",
            ".github/workflows/validate.yml",
            ".github/workflows/release.yml",
            ".github/workflows/frontend-build.yaml",
            ".github/actions/frontend-toolchain/action.yml",
            "scripts/ci_scope.py",
            "frontend/test/terminal_backend.py",
        ):
            with self.subTest(path=path):
                found = lanes_of(path)
                self.assertEqual(("true", "true"), (found["python"], found["frontend"]))

    def test_a_runtime_change_beside_a_frontend_one_needs_no_separate_contract_run(self) -> None:
        found = lanes_of(
            "compass/skills/compass/compass_runtime/reading.py", "frontend/src/main.tsx"
        )
        self.assertEqual(
            ("true", "true", "false"), (found["python"], found["frontend"], found["contract"])
        )

    def test_prose_no_test_reads_runs_nothing(self) -> None:
        for path in (
            "docs/" + "design-harness-registry.md",
            ".github/workflows/version-guard.yml",
            ".github/ISSUE_TEMPLATE/bug_report.yml",
        ):
            with self.subTest(path=path):
                self.assertEqual(ALL_OFF, lanes_of(path))

    def test_an_unknown_path_and_an_empty_diff_fail_open(self) -> None:
        for paths in (("somewhere/new.file",), ()):
            with self.subTest(paths=paths):
                found = lanes_of(*paths)
                self.assertEqual(("true", "true"), (found["python"], found["frontend"]))


class DocumentsTestsReadAreNotProseTest(unittest.TestCase):
    def test_documents_the_python_suites_open_run_those_suites_and_nothing_else(self) -> None:
        # A document can break an assertion, never a lint, a type, coverage or a platform.
        for path in (
            "docs/captures/README.md",
            "docs/promise-map.md",
            "README.md",
            "SECURITY.md",
            "CONTRIBUTING.md",
        ):
            with self.subTest(path=path):
                self.assertEqual({**ALL_OFF, "python_suites": "true"}, lanes_of(path))

    def test_data_the_python_tests_read_runs_only_those_suites(self) -> None:
        for path in (
            "compass/skills/compass/SKILL.md",
            "tests/README.md",
            "sample-session/README.md",
            ".claude/skills/sync-docs/SKILL.md",
            ".gitignore",
        ):
            with self.subTest(path=path):
                self.assertEqual({**ALL_OFF, "python_suites": "true"}, lanes_of(path))

    def test_every_document_a_runtime_citation_reaches_runs_the_python_lane(self) -> None:
        # Derived the way the detector derives it, so this holds for the citations that exist
        # rather than for one that happens to today.
        cited = ci_scope.python_documents(ROOT) - ci_scope.COMPOSED_PYTHON_READS
        runtime = {doc for doc in cited if doc.startswith("docs/")}
        self.assertTrue(runtime, "no citations found, so this asserts nothing")
        for path in sorted(runtime):
            with self.subTest(path=path):
                self.assertEqual("true", lanes_of(path)["python_suites"])

    def test_a_document_only_vitest_files_read_runs_those_files_not_the_lane(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ci-scope-") as temp:
            root = Path(temp)
            write_builder(root)
            check = root / CHECK
            check.parent.mkdir(parents=True)
            check.write_text("// reads every citation below\n", encoding="utf-8")
            reader = root / "frontend/src/drift/reader.test.ts"
            reader.parent.mkdir(parents=True)
            root_doc = "CONTRIBUTING" + ".md"
            quoted = "docs/" + "frontend-reader" + ".md"
            relative = "docs/" + "frontend-citation" + ".md"
            reader.write_text(
                f"readFileSync('{root_doc}');\nreadFileSync(\"{quoted}\");\n",
                encoding="utf-8",
            )
            # A citation in a source is read by the citation check, not by the source.
            source = root / "frontend/src/drift/level.ts"
            source.write_text(f"// [why](../../../{relative}#reader-state)\n", encoding="utf-8")
            expected = {
                root_doc: "frontend/src/drift/reader.test.ts",
                quoted: "frontend/src/drift/reader.test.ts",
                relative: CHECK,
            }
            for path, tests in expected.items():
                with self.subTest(path=path):
                    self.assertEqual(
                        {**ALL_OFF, "frontend_docs": "true", "frontend_docs_tests": tests},
                        lanes_of(path, root=root),
                    )
            self.assertEqual(
                f"frontend/src/drift/reader.test.ts {CHECK}",
                lanes_of(quoted, relative, root=root)["frontend_docs_tests"],
            )
            # The whole lane already runs every Vitest file, so the narrow job stays off.
            found = lanes_of(quoted, "frontend/src/main.tsx", root=root)
            self.assertEqual(
                ("true", "false", ""),
                (found["frontend"], found["frontend_docs"], found["frontend_docs_tests"]),
            )
            reader.unlink()
            self.assertEqual(ALL_OFF, lanes_of(quoted, root=root))
            # A source the scan cannot read cannot authorize a skip.
            reader.write_bytes(b"\xff")
            out = io.StringIO()
            with redirect_stdout(out):
                ci_scope.main(["--root", str(root), "--paths", quoted])
            self.assertIn("python=true\nlint=true\nfrontend=true", out.getvalue())

    def test_a_document_a_file_vitest_does_not_run_reads_runs_the_whole_lane(self) -> None:
        # A story, an end-to-end proof, a build script: no one Vitest file stands for it.
        with tempfile.TemporaryDirectory(prefix="ci-scope-") as temp:
            root = Path(temp)
            write_builder(root)
            quoted = "docs/" + "frontend-reader" + ".md"
            for reader in (
                "frontend/stories/Reader.stories.tsx",
                "frontend/e2e/reader.mjs",
                "frontend/build/reader.test.mjs",
            ):
                with self.subTest(reader=reader):
                    target = root / reader
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(f"read('{quoted}');\n", encoding="utf-8")
                    found = lanes_of(quoted, root=root)
                    self.assertEqual(("true", "false"), (found["frontend"], found["frontend_docs"]))
                    target.unlink()

    def test_a_citation_with_no_citation_check_to_run_runs_the_whole_lane(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ci-scope-") as temp:
            root = Path(temp)
            write_builder(root)
            relative = "docs/" + "frontend-citation" + ".md"
            source = root / "frontend/src/level.ts"
            source.parent.mkdir(parents=True)
            source.write_text(f"// [why]({relative}#reader-state)\n", encoding="utf-8")
            found = lanes_of(relative, root=root)
            self.assertEqual(("true", "false"), (found["frontend"], found["frontend_docs"]))

    def test_the_drift_record_runs_the_citation_check_and_the_python_suites(self) -> None:
        # Measured 2026-11-06: three drift PRs ran the whole frontend lane, macOS included, only
        # because they recorded a ruling in this document, which frontend comments cite.
        found = lanes_of("docs/design-reading-a-session.md")
        self.assertEqual(
            {
                **ALL_OFF,
                "python_suites": "true",
                "frontend_docs": "true",
                "frontend_docs_tests": CHECK,
            },
            found,
        )

    def test_every_vitest_file_the_detector_names_is_one_vitest_runs(self) -> None:
        # The detector's notion of a Vitest file is vitest.config.mts's include globs.
        config = (ROOT / "vitest.config.mts").read_text(encoding="utf-8")
        for pattern in ci_scope.VITEST_FILES:
            with self.subTest(pattern=pattern):
                self.assertIn(f"include: ['{pattern}']", config)
        self.assertTrue((ROOT / CHECK).is_file())
        readers = ci_scope.frontend_documents(ROOT).tests
        self.assertTrue(readers, "no document is read by Vitest alone, so this asserts nothing")
        for document, tests in readers.items():
            for test in tests:
                with self.subTest(document=document, test=test):
                    self.assertTrue(ci_scope.is_vitest_file(test))
                    self.assertTrue((ROOT / test).is_file())


class TheBundlesOwnInputsRunTheFrontendLaneTest(unittest.TestCase):
    def test_every_file_the_bundle_hashes_runs_the_frontend_lane(self) -> None:
        # `.gitattributes` is the one no location rule sends there; the build records its hash.
        sources = ci_scope.bundle_sources(ROOT)
        self.assertIn(".gitattributes", sources)
        self.assertIn("compass/skills/compass/compass_runtime/web/page.py", sources)
        for path in sorted(sources):
            with self.subTest(path=path):
                self.assertEqual("true", lanes_of(path)["frontend"])

    def test_a_builder_whose_list_cannot_be_read_fails_open(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ci-scope-") as temp:
            root = Path(temp)
            (root / "frontend/build").mkdir(parents=True)
            (root / "frontend/build/package.mjs").write_text("export {};\n", encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                ci_scope.main(["--root", str(root), "--paths", ".gitattributes"])
            self.assertIn("python=true\nlint=true\nfrontend=true", out.getvalue())


class PlatformSensitiveChangesRunTheMacosLegsTest(unittest.TestCase):
    def test_a_change_outside_the_platform_list_runs_no_macos_leg(self) -> None:
        for path in (
            "compass/skills/compass/compass_runtime/reading.py",
            "compass/skills/compass/compass_runtime/config.py",
            "compass/skills/compass/tests/test_sessions.py",
            "scripts/owned_observer.py",
            "frontend/src/main.tsx",
            "pnpm-lock.yaml",
            "docs/design-reading-a-session.md",
        ):
            with self.subTest(path=path):
                self.assertEqual("false", lanes_of(path)["platform"])

    def test_platform_sensitive_code_runs_the_macos_legs(self) -> None:
        for path in (
            "compass/skills/compass/compass_runtime/supervise.py",
            "compass/skills/compass/compass_runtime/lifecycle.py",
            "compass/skills/compass/launch.py",
            "compass-gemini/hooks/launch.py",
            "compass/skills/compass/tests/test_supervise.py",
            "scripts/capture_terminal_identity.py",
            "frontend/dev/supervisor.mjs",
        ):
            with self.subTest(path=path):
                self.assertEqual("true", lanes_of(path)["platform"])

    def test_an_exit_watch_change_runs_the_python_lane_on_macos(self) -> None:
        found = lanes_of("compass/skills/compass/compass_runtime/supervise.py")
        self.assertEqual(("true", "true"), (found["python"], found["platform"]))

    def test_every_platform_entry_names_a_file_that_exists(self) -> None:
        # A renamed module would otherwise leave its entry matching nothing, silently.
        for pattern in ci_scope.PLATFORM_PATHS:
            with self.subTest(pattern=pattern):
                self.assertTrue(
                    any(ROOT.glob(pattern)) or (ROOT / pattern).exists(),
                    f"{pattern} matches no file",
                )

    def test_the_gates_own_wiring_and_an_unknown_path_run_the_macos_legs(self) -> None:
        for path in (".github/workflows/quality-gate.yml", "scripts/ci_scope.py", "new/thing"):
            with self.subTest(path=path):
                self.assertEqual("true", lanes_of(path)["platform"])

    def test_main_nightly_and_a_manual_run_turn_on_every_lane(self) -> None:
        for event in ("push", "schedule", "workflow_dispatch"):
            with self.subTest(event=event):
                found = ci_scope.decide(event, "", "", ROOT).outputs()
                for lane in ("python", "lint", "frontend", "python_suites", "platform"):
                    self.assertEqual("true", found[lane], lane)


class RuffAndRenamesTest(unittest.TestCase):
    def test_python_in_a_data_directory_is_linted_and_typed(self) -> None:
        for path in ("tests/raw_sessions/helper.py", ".claude/skills/burndown/helper.py"):
            with self.subTest(path=path):
                self.assertEqual("true", lanes_of(path)["python"])

    def test_markdown_holding_python_the_formatter_checks_runs_ruff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ci-scope-") as temp:
            root = Path(temp)
            write_builder(root)
            (root / "docs/plans").mkdir(parents=True)
            fence = "```python\nx = 1\n```\n"
            (root / "docs/quoted.md").write_text(fence, encoding="utf-8")
            (root / "docs/plain.md").write_text("words\n", encoding="utf-8")
            (root / "docs/plans/fragment.md").write_text(fence, encoding="utf-8")
            self.assertEqual({**ALL_OFF, "lint": "true"}, lanes_of("docs/quoted.md", root=root))
            self.assertEqual(ALL_OFF, lanes_of("docs/plain.md", root=root))
            # pyproject.toml excludes plan docs from the formatter, and a deleted file has no block.
            self.assertEqual(ALL_OFF, lanes_of("docs/plans/fragment.md", root=root))
            self.assertEqual(ALL_OFF, lanes_of("docs/gone.md", root=root))


class TheWorkflowRunAsksGitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ci-scope-git-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def git(self, *args: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        return subprocess.run(
            ["git", "-C", str(self.tmp), *args],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            env=env,
        ).stdout.strip()

    def test_the_pull_requests_own_changes_decide_and_anything_else_fails_open(self) -> None:
        self.git("init", "-q", "-b", "main")
        write_builder(self.tmp)
        (self.tmp / "frontend").mkdir(exist_ok=True)
        (self.tmp / "frontend/a.ts").write_text("1\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD")
        (self.tmp / "frontend/a.ts").write_text("2\n", encoding="utf-8")
        self.git("commit", "-qam", "head")
        head = self.git("rev-parse", "HEAD")
        cwd = Path.cwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(
            {**ALL_OFF, "frontend": "true", "python_suites": "true"},
            ci_scope.decide("pull_request", base, head, self.tmp).outputs(),
        )
        for event, b, h in (
            ("push", base, head),
            ("pull_request", "", head),
            ("pull_request", "nope", head),
        ):
            with self.subTest(event=event, base=b):
                self.assertIs(ci_scope.EVERYTHING, ci_scope.decide(event, b, h, self.tmp))

    def test_a_move_counts_where_the_file_left_as_well_as_where_it_went(self) -> None:
        self.git("init", "-q", "-b", "main")
        write_builder(self.tmp)
        (self.tmp / "frontend/build/LICENSE.txt").write_text("text\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        base = self.git("rev-parse", "HEAD")
        (self.tmp / "docs").mkdir()
        self.git("mv", "frontend/build/LICENSE.txt", "docs/license.md")
        self.git("commit", "-qm", "move")
        head = self.git("rev-parse", "HEAD")
        cwd = Path.cwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, cwd)
        paths = ci_scope.changed_paths(base, head)
        self.assertEqual(["docs/license.md", "frontend/build/LICENSE.txt"], sorted(paths or []))
        self.assertEqual(
            "true", ci_scope.decide("pull_request", base, head, self.tmp).outputs()["frontend"]
        )

    def test_the_answer_reaches_github_output(self) -> None:
        output = self.tmp / "output"
        out = io.StringIO()
        previous = os.environ.get("GITHUB_OUTPUT")
        os.environ["GITHUB_OUTPUT"] = str(output)
        self.addCleanup(
            lambda: (
                os.environ.pop("GITHUB_OUTPUT")
                if previous is None
                else os.environ.__setitem__("GITHUB_OUTPUT", previous)
            )
        )
        with redirect_stdout(out):
            ci_scope.main(["--root", str(ROOT), "--paths", "pnpm-lock.yaml"])
        self.assertEqual(
            "python=false\nlint=false\nfrontend=true\ncontract=false\npython_suites=true\n"
            "frontend_docs=false\nfrontend_docs_tests=\nplatform=false\n",
            output.read_text(encoding="utf-8"),
        )
        self.assertIn("pnpm-lock.yaml: frontend", out.getvalue())


if __name__ == "__main__":
    unittest.main()
