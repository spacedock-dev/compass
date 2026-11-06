"""The pre-PR runner: which checks each kind of change plans, the canonical list, and the lock."""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pre_pr

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

OFF = {
    "python": "false",
    "lint": "false",
    "frontend": "false",
    "contract": "false",
    "python_suites": "false",
}

ALWAYS = (
    "ruff check .",
    "ruff format --check .",
    "mypy",
    "python3 scripts/validate_plugins.py",
    "python3 scripts/bump_version.py --current",
)


def installed(name: str) -> str:
    """A `which` that finds every tool, so a plan never depends on this machine's PATH."""
    return f"/usr/bin/{name}"


def plan(outputs: dict[str, str], **options: object) -> list[pre_pr.Item]:
    lanes = {**OFF, **outputs}
    return pre_pr.plan(lanes, which=installed, root=ROOT, **options)  # type: ignore[arg-type]


def ran(items: list[pre_pr.Item]) -> list[str]:
    return [item.text for item in items if item.reason is None]


def skipped(items: list[pre_pr.Item]) -> list[str]:
    return [item.text for item in items if item.reason is not None]


def pnpm(commands: list[str]) -> list[str]:
    return [command for command in commands if command.startswith("pnpm")]


def canonical_list(agents: str) -> list[str]:
    """The commands in AGENTS.md's Pre-PR block, read independently of the runner.

    Comment lines go, a trailing `   # note` goes, a `\\` continuation joins its next line.
    """
    section = agents.split("\n## Pre-PR Checks\n", 1)[1].split("\n## ", 1)[0]
    block = section.split("```bash\n", 1)[1].split("\n```", 1)[0]
    joined = re.sub(r"\\\n\s*", " ", block)
    commands = []
    for line in joined.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        commands.append(" ".join(re.sub(r"\s+#\s.*$", "", stripped).split()))
    return commands


class LanePlanTest(unittest.TestCase):
    """What each kind of change runs, read from `--dry-run`'s plan with the lanes injected."""

    def test_markdown_only_runs_the_docs_checks_and_no_pnpm_step(self) -> None:
        items = plan({})
        commands = ran(items)
        for command in ALWAYS:
            self.assertIn(command, commands)
        self.assertIn(pre_pr.DOCUMENTATION_TEST, commands)
        self.assertEqual(pnpm(commands), [])
        self.assertNotIn(pre_pr.DASHBOARD_SUITE, commands)
        self.assertNotIn(pre_pr.SCRIPTS_SUITE, commands)

    def test_python_change_runs_both_suites_without_coverage_and_no_pnpm_step(self) -> None:
        commands = ran(plan({"python": "true", "lint": "true", "python_suites": "true"}))
        self.assertIn(pre_pr.DASHBOARD_SUITE, commands)
        self.assertIn(pre_pr.SCRIPTS_SUITE, commands)
        self.assertFalse(any("--coverage" in command for command in commands))
        self.assertFalse(any(command.startswith("coverage ") for command in commands))
        self.assertEqual(pnpm(commands), [])
        # The dashboard suite already runs test_documentation.
        self.assertNotIn(pre_pr.DOCUMENTATION_TEST, commands)

    def test_coverage_flag_runs_the_canonical_coverage_commands(self) -> None:
        commands = ran(plan({"python": "true", "python_suites": "true"}, coverage=True))
        for command in (
            "coverage erase",
            "python3 scripts/run_tests.py --coverage -s compass/skills/compass/tests -t .",
            "python3 scripts/run_tests.py --coverage -s scripts/tests -t scripts/tests",
            "coverage combine",
            "coverage report",
        ):
            self.assertIn(command, commands)

    def test_frontend_change_runs_the_pnpm_steps(self) -> None:
        commands = ran(plan({"frontend": "true", "python_suites": "true"}))
        for command in (
            "pnpm install --frozen-lockfile",
            "pnpm lint",
            "pnpm typecheck",
            "pnpm test:styles --base origin/main",
            "pnpm test",
            "pnpm build:storybook",
            "pnpm test:stories",
            "pnpm test:dev",
            "pnpm build",
            "pnpm build:check",
        ):
            self.assertIn(command, commands)
        self.assertNotIn("pnpm test:coverage", commands)

    def test_frontend_docs_runs_exactly_the_named_vitest_files(self) -> None:
        tests = "frontend/src/a.test.ts frontend/src/b.test.tsx"
        commands = ran(plan({"frontend_docs": "true", "frontend_docs_tests": tests}))
        self.assertEqual(
            pnpm(commands),
            [
                "pnpm install --frozen-lockfile",
                "pnpm exec vitest run frontend/src/a.test.ts frontend/src/b.test.tsx",
            ],
        )

    def test_contract_runs_the_frontend_tests_that_read_the_runtime(self) -> None:
        commands = ran(plan({"python": "true", "contract": "true", "python_suites": "true"}))
        vitest = [command for command in commands if command.startswith("pnpm exec vitest run")]
        self.assertIn("pnpm test:dev", commands)
        self.assertIn("node --test frontend/build/*.test.mjs", commands)
        self.assertEqual(len(vitest), 1)
        self.assertIn(".test.ts", vitest[0])
        self.assertNotIn("pnpm build:storybook", commands)

    def test_every_skip_names_a_reason(self) -> None:
        for item in plan({}):
            if item.reason is not None:
                self.assertTrue(item.reason.strip(), item.text)
        self.assertIn("pnpm test:stories", skipped(plan({})))

    def test_platform_lane_runs_nothing_locally(self) -> None:
        self.assertEqual(ran(plan({"platform": "true"})), ran(plan({})))

    def test_an_unknown_lane_runs_the_whole_list(self) -> None:
        commands = ran(plan({"someday": "true"}))
        self.assertEqual(commands, ran(plan({}, everything=True)))

    def test_base_reaches_the_commands_that_compare_against_it(self) -> None:
        commands = ran(plan({"frontend": "true"}, base="upstream/main"))
        self.assertIn("pnpm test:styles --base upstream/main", commands)


class CanonicalListTest(unittest.TestCase):
    """`--all` and AGENTS.md's list are the same commands in the same order."""

    def test_all_is_the_canonical_list_in_agents_md(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        expected = canonical_list(agents)
        self.assertGreater(len(expected), 20)
        items = plan({}, everything=True, base="origin/main")
        self.assertEqual([item.text for item in items], expected)
        self.assertEqual(skipped(items), [])

    def test_all_reports_a_missing_native_validator_rather_than_dropping_it(self) -> None:
        def no_agy(name: str) -> str | None:
            return None if name == "agy" else installed(name)

        items = pre_pr.plan(OFF, which=no_agy, root=ROOT, everything=True)
        self.assertEqual(skipped(items), ["agy plugin validate ./compass"])


class DryRunTest(unittest.TestCase):
    """`--dry-run` prints the plan, every skip with its reason, and runs nothing."""

    def test_dry_run_prints_runs_and_skips(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = pre_pr.main(["--dry-run"], classify=lambda _base: (dict(OFF), ["AGENTS.md"]))
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("run   ruff check .", text)
        self.assertRegex(text, r"skip  pnpm lint\s+\(")
        self.assertIn("AGENTS.md", text)

    def test_classifier_failure_runs_everything(self) -> None:
        def broken(_base: str) -> tuple[dict[str, str], list[str]]:
            message = "no merge base"
            raise pre_pr.ScopeError(message)

        out = io.StringIO()
        with redirect_stdout(out):
            pre_pr.main(["--dry-run"], classify=broken)
        self.assertIn("run   pnpm build:check", out.getvalue())
        self.assertIn("no merge base", out.getvalue())


class ChangedPathsTest(unittest.TestCase):
    """A pre-PR run classifies the tree about to be committed, not only the commits."""

    def test_commits_edits_and_new_files_all_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args: str) -> None:
                subprocess.run(
                    ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
                    cwd=root,
                    check=True,
                    capture_output=True,
                )

            git("init", "-q", "-b", "main")
            (root / "kept.md").write_text("a\n", encoding="utf-8")
            (root / "edited.py").write_text("a = 1\n", encoding="utf-8")
            git("add", ".")
            git("commit", "-q", "-m", "base")
            git("switch", "-q", "-c", "work")
            (root / "committed.md").write_text("b\n", encoding="utf-8")
            git("add", "committed.md")
            git("commit", "-q", "-m", "work")
            (root / "edited.py").write_text("a = 2\n", encoding="utf-8")
            (root / "new.ts").write_text("x\n", encoding="utf-8")
            self.assertEqual(
                pre_pr.changed_paths("main", root), ["committed.md", "edited.py", "new.ts"]
            )
            with self.assertRaises(pre_pr.ScopeError):
                pre_pr.changed_paths("no-such-ref", root)


class LockTest(unittest.TestCase):
    """Only one run per repository at a time: a second holder waits, and says so."""

    def test_a_second_holder_waits_until_the_first_releases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-pr.lock"
            waited: list[str] = []
            with pre_pr.hold_lock(path):
                with (
                    self.assertRaises(TimeoutError),
                    pre_pr.hold_lock(path, on_wait=waited.append, poll=0.05, timeout=0.3),
                ):
                    self.fail("acquired a lock another holder has")
                self.assertEqual(len(waited), 1)
            with pre_pr.hold_lock(path, timeout=0.3):
                pass

    def test_another_process_cannot_take_a_held_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-pr.lock"
            probe = textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {str(SCRIPTS)!r})
                import pre_pr
                try:
                    with pre_pr.hold_lock(__import__("pathlib").Path({str(path)!r}), timeout=0.3):
                        sys.exit(0)
                except TimeoutError:
                    sys.exit(3)
                """
            )
            with pre_pr.hold_lock(path):
                held = subprocess.run([sys.executable, "-c", probe], check=False, timeout=30)
            free = subprocess.run([sys.executable, "-c", probe], check=False, timeout=30)
            self.assertEqual(held.returncode, 3)
            self.assertEqual(free.returncode, 0)

    def test_the_lock_lives_in_the_git_common_directory(self) -> None:
        common = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(pre_pr.lock_path(ROOT).parent, Path(common))


if __name__ == "__main__":
    unittest.main()
