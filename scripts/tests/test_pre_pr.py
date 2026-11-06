"""The pre-PR runner: which checks each kind of change plans, the canonical list, and the lock."""

from __future__ import annotations

import contextlib
import io
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

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


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )


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
        self.assertEqual(pnpm(commands), [])
        self.assertNotIn(pre_pr.SCRIPTS_SUITE, commands)

    def test_a_change_with_no_suite_lane_runs_what_validate_yml_runs(self) -> None:
        # validate.yml's backstop for a document the detector calls prose: the dashboard suite,
        # and the validator and bump-version tests it runs on every pull request.
        commands = ran(plan({}))
        self.assertIn(pre_pr.DASHBOARD_SUITE, commands)
        self.assertIn(pre_pr.VALIDATE_TESTS, commands)
        self.assertNotIn(pre_pr.VALIDATE_TESTS, ran(plan({"python_suites": "true"})))
        self.assertFalse(any("--coverage" in command for command in ran(plan({}, coverage=True))))

    def test_a_requirements_change_installs_the_toolchain_first(self) -> None:
        install = "python3 -m pip install -r requirements-validation.txt -r requirements-dev.txt"
        self.assertIn(install, skipped(plan({"python": "true"})))
        commands = ran(plan({"python": "true"}, requirements=True))
        self.assertEqual(commands[0], install)

    def test_python_change_runs_both_suites_without_coverage_and_no_pnpm_step(self) -> None:
        commands = ran(plan({"python": "true", "lint": "true", "python_suites": "true"}))
        self.assertIn(pre_pr.DASHBOARD_SUITE, commands)
        self.assertIn(pre_pr.SCRIPTS_SUITE, commands)
        self.assertFalse(any("--coverage" in command for command in commands))
        self.assertFalse(any(command.startswith("coverage ") for command in commands))
        self.assertEqual(pnpm(commands), [])
        # The scripts suite already runs the validator and bump-version tests.
        self.assertNotIn(pre_pr.VALIDATE_TESTS, commands)

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

    def test_the_browser_is_installed_before_the_stories_need_it(self) -> None:
        commands = ran(plan({"frontend": "true"}))
        install = commands.index("pnpm exec playwright install chromium")
        self.assertLess(install, commands.index("pnpm build:storybook"))
        self.assertLess(install, commands.index("pnpm test:stories"))

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

    def test_a_detector_without_the_docs_lane_says_so(self) -> None:
        reasons = {item.text: item.reason for item in plan({})}
        docs = "pnpm exec vitest run <the Vitest files that read a changed document>"
        self.assertIn("frontend_docs", str(reasons[docs]))
        with_lane = {item.text: item.reason for item in plan({"frontend_docs": "false"})}
        self.assertEqual(with_lane[docs], "no changed document is read by a frontend test")

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
            code = pre_pr.main(
                ["--dry-run"], classify=lambda _base: (dict(OFF), ["AGENTS.md"], ["AGENTS.md"])
            )
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("run   ruff check .", text)
        self.assertRegex(text, r"skip  pnpm lint\s+\(")
        self.assertIn("AGENTS.md", text)

    def test_a_changed_requirements_file_plans_the_install(self) -> None:
        out = io.StringIO()
        paths = ["requirements-dev.txt"]
        lanes = {**OFF, "python": "true", "python_suites": "true"}
        with redirect_stdout(out):
            pre_pr.main(["--dry-run"], classify=lambda _base: (lanes, paths, paths))
        self.assertIn("run   python3 -m pip install", out.getvalue())

    def test_checks_ci_runs_and_this_does_not_are_named(self) -> None:
        out = io.StringIO()
        lanes = {**OFF, "frontend": "true", "python_suites": "true"}
        with redirect_stdout(out):
            pre_pr.main(["--dry-run"], classify=lambda _base: (lanes, [], []))
        text = out.getvalue()
        self.assertIn("server.py --diagnose --json", text)
        self.assertIn("pnpm build:preview", text)

    def test_classifier_failure_runs_everything(self) -> None:
        def broken(_base: str) -> tuple[dict[str, str], list[str], list[str]]:
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
            git(root, "init", "-q", "-b", "main")
            (root / "kept.md").write_text("a\n", encoding="utf-8")
            (root / "edited.py").write_text("a = 1\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "base")
            git(root, "switch", "-q", "-c", "work")
            (root / "committed.md").write_text("b\n", encoding="utf-8")
            git(root, "add", "committed.md")
            git(root, "commit", "-q", "-m", "work")
            (root / "edited.py").write_text("a = 2\n", encoding="utf-8")
            (root / "new.ts").write_text("x\n", encoding="utf-8")
            self.assertEqual(
                pre_pr.changed_paths("main", root), ["committed.md", "edited.py", "new.ts"]
            )
            with self.assertRaises(pre_pr.ScopeError):
                pre_pr.changed_paths("no-such-ref", root)


class ExecuteTest(unittest.TestCase):
    """A failing check is a FAIL row; it never stops the commands after it."""

    def test_a_version_check_without_a_merge_base_fails_and_the_run_goes_on(self) -> None:
        later = pre_pr.Item("later", argv=(sys.executable, "-c", "pass"))
        version = pre_pr.Item("version", check=pre_pr._version_check("no-such-ref", ROOT))
        out = io.StringIO()
        with redirect_stdout(out):
            code = pre_pr._execute([version, later], ROOT)
        text = out.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("==> later", text)
        self.assertRegex(text, r"FAIL \(1\)\s+\S+\s+version")
        self.assertIn("1 passed, 1 failed", text)

    def test_an_interrupt_still_prints_what_already_ran(self) -> None:
        def interrupt() -> int:
            raise KeyboardInterrupt

        first = pre_pr.Item("first", argv=(sys.executable, "-c", "pass"))
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(KeyboardInterrupt):
            pre_pr._execute([first, pre_pr.Item("second", check=interrupt)], ROOT)
        self.assertIn("1 passed, 0 failed", out.getvalue())

    def test_an_uncommitted_version_edit_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "plugin.json"
            manifest.write_text('{"version": "1.0.0"}\n', encoding="utf-8")
            git(root, "init", "-q", "-b", "main")
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "base")
            check = pre_pr._version_check("main", root)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(check(), 0)
                manifest.write_text('{"version": "1.0.1"}\n', encoding="utf-8")
                self.assertEqual(check(), 1)


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

    def test_two_worktrees_share_one_lock(self) -> None:
        # In a main checkout --git-dir and --git-common-dir agree, so only a second worktree can
        # tell a per-worktree lock from the shared one.
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main"
            main.mkdir()
            git(main, "init", "-q", "-b", "main")
            git(main, "commit", "-q", "--allow-empty", "-m", "base")
            other = Path(tmp) / "other"
            git(main, "worktree", "add", "-q", "-b", "other", str(other))
            self.assertEqual(pre_pr.lock_path(main), pre_pr.lock_path(other))
            with (
                pre_pr.hold_lock(pre_pr.lock_path(main)),
                self.assertRaises(TimeoutError),
                pre_pr.hold_lock(pre_pr.lock_path(other), poll=0.05, timeout=0.3),
            ):
                self.fail("a second worktree took the lock the first holds")


HOLDER = textwrap.dedent(
    """
    import pathlib, sys, time
    sys.path.insert(0, sys.argv[1])
    import pre_pr
    with pre_pr.hold_lock(pathlib.Path(sys.argv[2]), timeout=30):
        print("held", flush=True)
        time.sleep(60)
    """
)


class Clock:
    """A monotonic clock that only moves when the code under test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds


class HolderProcess:
    """Another process holding the lock at `path` until it is killed."""

    def __init__(self, path: Path) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-c", HOLDER, str(SCRIPTS), str(path)],
            stdout=subprocess.PIPE,
            text=True,
        )
        assert self.process.stdout is not None
        if self.process.stdout.readline().strip() != "held":
            self.kill()
            message = "the holder never took the lock"
            raise AssertionError(message)

    def kill(self) -> None:
        self.process.kill()
        self.process.wait(timeout=30)
        assert self.process.stdout is not None
        self.process.stdout.close()


class WaitTimeoutTest(unittest.TestCase):
    """A run behind another worktree's run waits a bounded time, then says what it did not run."""

    def run_behind_a_held_lock(self, *argv: str) -> tuple[int, str, Clock]:
        clock = Clock()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-pr.lock"
            with pre_pr.hold_lock(path), redirect_stdout(out):
                code = pre_pr.main(
                    list(argv),
                    classify=lambda _base: (dict(OFF), ["AGENTS.md"], ["AGENTS.md"]),
                    lock=lambda: path,
                    clock=clock,
                    sleep=clock.sleep,
                )
        return code, out.getvalue(), clock

    def test_a_timed_out_run_names_every_check_it_did_not_run_and_fails(self) -> None:
        code, text, clock = self.run_behind_a_held_lock("--wait-timeout", "90")
        self.assertNotEqual(code, 0)
        self.assertEqual(code, pre_pr.WAIT_TIMED_OUT)
        self.assertEqual(clock.now, 90)
        self.assertNotIn("==> ", text)
        report = text.split("Gave up", 1)[1]
        for command in ran(plan({})):
            self.assertIn(f"  not run  {command}", report)
        self.assertNotIn("not run  pnpm lint", report)

    def test_the_default_wait_is_thirty_minutes(self) -> None:
        code, _text, clock = self.run_behind_a_held_lock()
        self.assertEqual(code, pre_pr.WAIT_TIMED_OUT)
        self.assertEqual(clock.now, 30 * 60)

    def test_a_zero_timeout_gives_up_without_waiting(self) -> None:
        code, _text, clock = self.run_behind_a_held_lock("--wait-timeout", "0")
        self.assertEqual(code, pre_pr.WAIT_TIMED_OUT)
        self.assertEqual(clock.sleeps, 0)

    def test_a_negative_timeout_is_refused(self) -> None:
        for value in ("-1", "nan", "soon"):
            with (
                redirect_stdout(io.StringIO()),
                redirect_stderr(io.StringIO()) as err,
                self.assertRaises(SystemExit),
            ):
                pre_pr.main(["--dry-run", "--wait-timeout", value])
            self.assertIn("--wait-timeout", err.getvalue())

    def test_a_check_that_times_out_is_not_reported_as_a_lock_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-pr.lock"
            out = io.StringIO()
            with (
                redirect_stdout(out),
                mock.patch.object(pre_pr, "_execute", side_effect=TimeoutError("a check")),
                self.assertRaises(TimeoutError),
            ):
                pre_pr.main(
                    [],
                    classify=lambda _base: (dict(OFF), [], []),
                    lock=lambda: path,
                )
            self.assertNotIn("Gave up", out.getvalue())


class DeadHolderTest(unittest.TestCase):
    """A holder that died leaves no lock behind; a live one keeps its lock."""

    def test_a_killed_holders_lock_is_recovered_at_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-pr.lock"
            holder = HolderProcess(path)
            dead = holder.process.pid
            self.assertIn(f"pid {dead} ", path.read_text(encoding="utf-8"))
            holder.kill()
            # Killed outright, so nothing of its own released the lock or cleared its record.
            self.assertIn(f"pid {dead} ", path.read_text(encoding="utf-8"))
            with pre_pr.hold_lock(path, timeout=0):
                self.assertIn(f"pid {os.getpid()} ", path.read_text(encoding="utf-8"))

    def test_a_live_holders_lock_is_not_taken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pre-pr.lock"
            holder = HolderProcess(path)
            clock = Clock()
            try:
                with (
                    self.assertRaises(pre_pr.LockTimeoutError) as raised,
                    pre_pr.hold_lock(path, timeout=5, clock=clock, sleep=clock.sleep),
                ):
                    self.fail("took the lock a live process holds")
                self.assertIn(f"pid {holder.process.pid} ", str(raised.exception))
                self.assertIn(f"pid {holder.process.pid} ", path.read_text(encoding="utf-8"))
                self.assertEqual(clock.now, 5)
            finally:
                holder.kill()


# A run whose one check starts a grandchild, as `run_tests.py` starts workers and pnpm starts node.
STOPPED_HOLDER = textwrap.dedent(
    """
    import pathlib, sys, time
    sys.path.insert(0, sys.argv[1])
    import pre_pr
    grandchild = "import time; time.sleep(60)"
    check = (
        "import os, pathlib, subprocess, sys, time;"
        f"g = subprocess.Popen([sys.executable, '-c', {grandchild!r}]);"
        f"pathlib.Path({sys.argv[3]!r}).write_text(f'{{os.getpid()}} {{g.pid}}');"
        "time.sleep(60)"
    )
    item = pre_pr.Item("check", argv=(sys.executable, "-c", check))
    sys.exit(pre_pr._run_locked([item], pathlib.Path(sys.argv[2]), 0, time.monotonic, time.sleep))
    """
)


def alive(pid: int) -> bool:
    """Whether `pid` still exists a few seconds on: a check left running sleeps for a minute."""
    # A process killed a moment ago lingers as a zombie until its new parent reaps it.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        time.sleep(0.05)
    return True


@unittest.skipIf(sys.platform == "win32", "process groups and these signals are POSIX")
class StoppedHolderTest(unittest.TestCase):
    """Stopping a run stops the check it was running, so the next run does not start beside it."""

    def test_a_stopped_run_takes_its_check_down_before_freeing_the_lock(self) -> None:
        for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=signum.name), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "pre-pr.lock"
                pids = Path(tmp) / "pids"
                holder = subprocess.Popen(
                    [sys.executable, "-c", STOPPED_HOLDER, str(SCRIPTS), str(path), str(pids)],
                    stdout=subprocess.DEVNULL,
                )
                started: list[int] = []
                try:
                    deadline = time.monotonic() + 30
                    while len(started) < 2 and time.monotonic() < deadline:
                        time.sleep(0.05)
                        with contextlib.suppress(OSError):
                            started = [int(pid) for pid in pids.read_text(encoding="utf-8").split()]
                    self.assertEqual(len(started), 2, "the check never started its grandchild")
                    holder.send_signal(signum)
                    self.assertNotEqual(holder.wait(timeout=30), 0)
                    with pre_pr.hold_lock(path, timeout=0):
                        self.assertEqual([pid for pid in started if alive(pid)], [])
                finally:
                    holder.kill()
                    holder.wait(timeout=30)
                    for pid in started:
                        with contextlib.suppress(ProcessLookupError):
                            os.kill(pid, signal.SIGKILL)

    def test_a_check_that_times_out_is_stopped_with_what_it_started(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pids = Path(tmp) / "pids"
            check = (
                "import os, pathlib, subprocess, sys, time;"
                "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
                f"pathlib.Path({str(pids)!r}).write_text(f'{{os.getpid()}} {{g.pid}}');"
                "time.sleep(60)"
            )
            item = pre_pr.Item("check", argv=(sys.executable, "-c", check), timeout=3)
            with redirect_stdout(io.StringIO()) as out:
                code = pre_pr._run(item, Path(tmp))
            started = [int(pid) for pid in pids.read_text(encoding="utf-8").split()]
            try:
                self.assertEqual(code, 124)
                self.assertIn("timed out after 3 s", out.getvalue())
                self.assertEqual([pid for pid in started if alive(pid)], [])
            finally:
                for pid in started:
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(pid, signal.SIGKILL)


if __name__ == "__main__":
    unittest.main()
