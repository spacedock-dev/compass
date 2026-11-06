"""The parallel runner reaches the same verdict unittest would.

The runner replaces ``python -m unittest discover`` in every CI job that runs a
suite, so a runner that reported OK on a failing suite would turn the whole
quality gate green. Each check builds a small suite in a temporary directory and
runs it through ``run_tests.main`` with real spawned workers.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_tests

PASSING = """
import os
import unittest


class Kept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.environ["RUNNER_PID_LOG"], "a") as log:
            log.write(f"setup {os.getpid()}\\n")

    def _note(self):
        with open(os.environ["RUNNER_PID_LOG"], "a") as log:
            log.write(f"test {os.getpid()}\\n")

    def test_one(self):
        self._note()

    def test_two(self):
        self._note()

    def test_three(self):
        self._note()


class Other(unittest.TestCase):
    def test_other(self):
        self.assertTrue(True)
"""

MIXED = """
import unittest


class Mixed(unittest.TestCase):
    def test_passes(self):
        self.assertEqual(1, 1)

    def test_fails(self):
        self.assertEqual(1, 2)

    def test_errors(self):
        raise RuntimeError("boom")

    @unittest.skip("not here")
    def test_skipped(self):
        pass
"""


def write_suite(root: Path, modules: dict[str, str]) -> None:
    for name, body in modules.items():
        (root / name).write_text(textwrap.dedent(body), encoding="utf-8")


def run(root: Path, *extra: str, summary: Path | None = None) -> tuple[int, str]:
    stderr = io.StringIO()
    # The parent's discovery imports the suite here, and two tests that each write a
    # `test_broken.py` must not see the other's module.
    imported = set(sys.modules)
    where = os.path.realpath(root)
    # Never the inherited one: a retry here would write into the step summary of the CI job
    # running this suite.
    with contextlib.redirect_stderr(stderr), mock.patch.dict(os.environ):
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        if summary is not None:
            os.environ["GITHUB_STEP_SUMMARY"] = str(summary)
        try:
            code = run_tests.main(["-s", str(root), "-t", str(root), "-j", "2", *extra])
        finally:
            for name in set(sys.modules) - imported:
                path = getattr(sys.modules[name], "__file__", None) or ""
                if os.path.realpath(path).startswith(where + os.sep):
                    del sys.modules[name]
    return code, stderr.getvalue()


class RunnerVerdictTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "pids.log"
        self.addCleanup(self.tmp.cleanup)
        # The pid, not multiprocessing.parent_process(): under the runner this
        # test itself runs in a worker, so "has a parent" is true everywhere.
        env = mock_env({"RUNNER_PID_LOG": str(self.log), "RUNNER_PARENT_PID": str(os.getpid())})
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)

    def test_a_passing_suite_is_ok_and_keeps_each_class_on_one_worker(self) -> None:
        write_suite(self.root, {"test_passing.py": PASSING})

        code, out = run(self.root)

        self.assertEqual(0, code, out)
        self.assertIn("Ran 4 tests", out)
        self.assertTrue(out.rstrip().endswith("OK"), out)
        lines = self.log.read_text(encoding="utf-8").split()
        pids = set(lines[1::2])
        self.assertEqual(1, lines.count("setup"), "setUpClass must run once for its class")
        self.assertEqual(1, len(pids), "a class was split across workers")

    def test_failures_errors_skips_and_an_import_failure_all_reach_the_verdict(self) -> None:
        write_suite(
            self.root,
            {"test_mixed.py": MIXED, "test_broken.py": "import a_module_that_does_not_exist\n"},
        )

        code, out = run(self.root)

        self.assertEqual(1, code, out)
        self.assertIn("FAIL: test_fails", out)
        self.assertIn("ERROR: test_errors", out)
        self.assertIn("a_module_that_does_not_exist", out)
        self.assertIn("FAILED (failures=1, errors=2, skipped=1)", out)

    def test_a_class_only_the_parent_could_import_is_an_error_not_an_empty_pass(self) -> None:
        # The false green the review reproduced: the worker's discovery lacked
        # the class, ran an empty suite for it, and the verdict was OK.
        write_suite(
            self.root,
            {
                "test_worker_only_fails.py": """
                import os
                import unittest

                if str(os.getpid()) != os.environ["RUNNER_PARENT_PID"]:
                    raise ImportError("only a worker fails to import this")


                class Hidden(unittest.TestCase):
                    def test_fails(self):
                        self.fail("serial unittest reports this")
                """
            },
        )

        code, out = run(self.root)

        self.assertEqual(1, code, out)
        self.assertIn("discovery", out)

    def test_a_class_only_a_worker_could_import_is_an_error_not_skipped(self) -> None:
        write_suite(
            self.root,
            {
                "test_parent_only_fails.py": """
                import os
                import unittest

                if str(os.getpid()) == os.environ["RUNNER_PARENT_PID"]:
                    raise ImportError("only the parent fails to import this")


                class Seen(unittest.TestCase):
                    def test_passes(self):
                        pass
                """
            },
        )

        code, out = run(self.root)

        self.assertEqual(1, code, out)
        self.assertIn("test_parent_only_fails", out)

    def test_every_worker_gets_a_state_home_outside_the_real_one(self) -> None:
        # The tripwire for the whole class of leak, not one test: any test the
        # runner starts resolves COMPASS_HOME to a scratch directory, even when
        # the shell exported the real one.
        real = str(Path("~/.compass").expanduser())
        write_suite(
            self.root,
            {
                "test_state_home.py": f"""
                import os
                import unittest


                class StateHome(unittest.TestCase):
                    def test_is_scratch(self):
                        home = os.environ.get("COMPASS_HOME", "")
                        self.assertTrue(home, "COMPASS_HOME is unset in a worker")
                        self.assertNotEqual({real!r}, os.path.realpath(home))
                        self.assertIn("compass-runner-home-", home)
                """
            },
        )
        with mock_env({"COMPASS_HOME": real}):
            code, out = run(self.root)

        self.assertEqual(0, code, out)

    def test_discovering_nothing_is_a_failure_not_a_pass(self) -> None:
        # A mistyped -s would otherwise turn a CI job green having run nothing.
        code, out = run(self.root)

        self.assertEqual(1, code, out)
        self.assertIn("Ran 0 tests", out)


PRINTING = """
import sys
import unittest


class Printing(unittest.TestCase):
    def test_passes_noisily(self):
        print("PASSING-STDOUT")
        sys.stderr.write("PASSING-STDERR\\n")

    def test_fails_noisily(self):
        print("FAILING-STDOUT")
        self.fail("boom")
"""


class OutputBufferTest(unittest.TestCase):
    """A worker writes to the real descriptors, so only a child process sees what it printed."""

    def output(self, *extra: str) -> str:
        # The failing test is retried, and a retry writes to the step summary it inherits.
        env = {key: value for key, value in os.environ.items() if key != "GITHUB_STEP_SUMMARY"}
        with tempfile.TemporaryDirectory() as tmp:
            write_suite(Path(tmp), {"test_printing.py": PRINTING})
            done = subprocess.run(
                [sys.executable, run_tests.__file__, "-s", tmp, "-t", tmp, "-j", "1", *extra],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
                env=env,
            )
        self.assertEqual(1, done.returncode, done.stderr)
        return done.stdout + done.stderr

    def test_a_passing_test_prints_nothing_and_a_failing_one_shows_what_it_printed(self) -> None:
        out = self.output()

        self.assertNotIn("PASSING-STDOUT", out)
        self.assertNotIn("PASSING-STDERR", out)
        self.assertIn("FAILING-STDOUT", out)

    def test_no_buffer_prints_what_a_passing_test_wrote(self) -> None:
        out = self.output("--no-buffer")

        self.assertIn("PASSING-STDOUT", out)
        self.assertIn("PASSING-STDERR", out)


def mock_env(values: dict[str, str]) -> contextlib.AbstractContextManager[object]:
    return mock.patch.dict(os.environ, values)


if __name__ == "__main__":
    unittest.main()


class ShardTest(unittest.TestCase):
    def test_every_module_lands_in_exactly_one_shard_and_the_heavy_ones_are_spread(self) -> None:
        modules = [
            "test_analyze_campaign",
            "test_release_transition",
            "test_quick_a",
            "test_quick_b",
        ]
        modules += ["test_qualification_conditional_priority", "test_closure_qualification"]
        for count in (1, 2, 3, 4):
            with self.subTest(count=count):
                owner = run_tests.assign_shards(modules, count)
                self.assertEqual(set(modules), set(owner))
                self.assertTrue(all(0 <= index < count for index in owner.values()))
        three = run_tests.assign_shards(modules, 3)
        heavy = [
            "test_analyze_campaign",
            "test_qualification_conditional_priority",
            "test_closure_qualification",
        ]
        self.assertEqual(3, len({three[name] for name in heavy}))

    def test_assignment_does_not_depend_on_the_order_modules_are_found_in(self) -> None:
        modules = [f"test_m{index}" for index in range(12)] + ["test_analyze_campaign"]
        self.assertEqual(
            run_tests.assign_shards(modules, 3), run_tests.assign_shards(reversed(modules), 3)
        )

    def test_the_shards_of_a_suite_run_every_test_once_and_no_test_twice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("test_alpha", "test_beta", "test_gamma", "test_delta"):
                (root / f"{name}.py").write_text(
                    "import unittest\n\nclass T(unittest.TestCase):\n"
                    "    def test_a(self):\n        pass\n    def test_b(self):\n        pass\n",
                    encoding="utf-8",
                )
            whole = run_tests.discover(str(root), str(root), "test*.py")
            parts = [
                run_tests.discover(str(root), str(root), "test*.py", (k, 3)) for k in (1, 2, 3)
            ]
            seen = [unit for part in parts for unit in part]
            self.assertEqual(sorted(whole), sorted(seen))
            self.assertEqual(len(seen), len(set(seen)))

    def test_a_malformed_shard_is_refused(self) -> None:
        for text in ("0/3", "4/3", "x", "1/", "1/0", "-1/2"):
            with self.subTest(text=text), self.assertRaises(SystemExit):
                run_tests.parse_shard(text)
        self.assertEqual((2, 3), run_tests.parse_shard("2/3"))


# Fails the first time it runs and passes after, keyed by a marker file per test, so the second
# attempt passes whichever process makes it.
FLAKY_TEMPLATE = """
import os
import unittest
from pathlib import Path
{header}

class Flaky(unittest.TestCase):
{methods}
"""
# The attempt after the first logs its pid when RUNNER_RETRY_PID_LOG is set, then runs `then`.
FLAKY_METHOD = """
    def test_{name}(self):
        marker = Path(os.environ["RUNNER_FLAKY_DIR"]) / "{name}"
        if not marker.exists():
            marker.write_text("failed once", encoding="utf-8")
            {first}
        if os.environ.get("RUNNER_RETRY_PID_LOG"):
            with open(os.environ["RUNNER_RETRY_PID_LOG"], "a") as log:
                log.write(str(os.getpid()) + "\\n")
        {then}
"""
PASSING_ALONE = """
import unittest


class Alone(unittest.TestCase):
    def test_a(self):
        pass
"""
ALWAYS_FAILS = """
import unittest


class Broken(unittest.TestCase):
    def test_always(self):
        self.assertEqual("bytes", "time")
"""


def flaky_suite(
    *names: str, header: str = "", first: str = "self.assertGreater(0, 0)", then: str = "pass"
) -> str:
    methods = "".join(FLAKY_METHOD.format(name=name, first=first, then=then) for name in names)
    return FLAKY_TEMPLATE.format(header=header, methods=methods)


def flaky_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("FLAKY-RETRY-PASSED: ")]


class RetryTest(unittest.TestCase):
    """A test that fails once and passes on its own rerun does not fail the run, and is named."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "suite"
        self.root.mkdir()
        self.markers = Path(self.tmp.name) / "markers"
        self.markers.mkdir()
        self.addCleanup(self.tmp.cleanup)
        env = mock_env({"RUNNER_FLAKY_DIR": str(self.markers)})
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)

    def test_a_test_that_passes_on_its_retry_passes_the_run_and_is_listed(self) -> None:
        write_suite(self.root, {"test_flaky.py": flaky_suite("once"), "test_fine.py": PASSING})
        with mock_env({"RUNNER_PID_LOG": str(self.root / "pids.log")}):
            code, out = run(self.root)

        self.assertEqual(0, code, out)
        self.assertIn("Passed only on retry", out)
        self.assertIn("AssertionError: 0 not greater than 0", out)
        self.assertEqual(["FLAKY-RETRY-PASSED: test_flaky.Flaky.test_once"], flaky_lines(out))
        self.assertNotIn("FAIL: test_once", out)
        self.assertTrue(out.rstrip().endswith("OK (passed on retry=1)"), out)

    def test_a_test_that_errors_once_and_passes_on_its_retry_passes_the_run(self) -> None:
        write_suite(
            self.root,
            {"test_flaky.py": flaky_suite("once", first='raise FileNotFoundError("gone")')},
        )

        code, out = run(self.root)

        self.assertEqual(0, code, out)
        self.assertIn("FileNotFoundError: gone", out)
        self.assertEqual(["FLAKY-RETRY-PASSED: test_flaky.Flaky.test_once"], flaky_lines(out))
        self.assertNotIn("ERROR: test_once", out)
        self.assertTrue(out.rstrip().endswith("OK (passed on retry=1)"), out)

    def test_a_test_that_skips_itself_on_its_retry_fails_the_run(self) -> None:
        write_suite(
            self.root,
            {"test_flaky.py": flaky_suite("once", then='self.skipTest("port busy")')},
        )

        code, out = run(self.root)

        self.assertEqual(1, code, out)
        self.assertIn("Failed again on retry", out)
        self.assertIn("skipped on retry: port busy", out)
        self.assertIn("FAIL: test_once", out)
        self.assertEqual([], flaky_lines(out))

    def test_a_test_that_fails_twice_fails_the_run_as_before(self) -> None:
        write_suite(self.root, {"test_broken.py": ALWAYS_FAILS})

        code, out = run(self.root)

        self.assertEqual(1, code, out)
        self.assertIn("FAIL: test_always", out)
        self.assertIn("Failed again on retry", out)
        self.assertEqual([], flaky_lines(out))
        self.assertTrue(out.rstrip().endswith("FAILED (failures=1)"), out)

    def test_no_retry_leaves_a_first_failure_failing(self) -> None:
        write_suite(self.root, {"test_flaky.py": flaky_suite("once")})

        code, out = run(self.root, "--no-retry")

        self.assertEqual(1, code, out)
        self.assertIn("FAIL: test_once", out)
        self.assertEqual([], flaky_lines(out))

    def test_the_retry_limit_is_inclusive_and_more_failures_retry_nothing(self) -> None:
        limit = run_tests.RETRY_LIMIT
        names = [f"n{index}" for index in range(limit + 1)]
        write_suite(self.root, {"test_flaky.py": flaky_suite(*names[:limit])})
        retries = Path(self.tmp.name) / "retry-pids.log"
        with mock_env({"RUNNER_RETRY_PID_LOG": str(retries)}):
            code, out = run(self.root)
        self.assertEqual(0, code, out)
        self.assertEqual(limit, len(flaky_lines(out)))
        # Retries run one at a time, in one process, so a retried test never shares the machine
        # with another retry.
        pids = retries.read_text(encoding="utf-8").split()
        self.assertEqual(limit, len(pids), pids)
        self.assertEqual(1, len(set(pids)), pids)

        for marker in self.markers.iterdir():
            marker.unlink()
        write_suite(self.root, {"test_flaky.py": flaky_suite(*names)})
        code, out = run(self.root)
        self.assertEqual(1, code, out)
        self.assertIn(f"{limit + 1} tests failed, more than {limit}: retrying none", out)
        self.assertEqual([], flaky_lines(out))

    def test_a_step_summary_gets_the_retried_tests(self) -> None:
        write_suite(
            self.root, {"test_flaky.py": flaky_suite("once"), "test_broken.py": ALWAYS_FAILS}
        )
        summary = Path(self.tmp.name) / "step-summary.md"
        summary.write_text("earlier step\n", encoding="utf-8")

        code, out = run(self.root, summary=summary)

        self.assertEqual(1, code, out)
        text = summary.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("earlier step\n"), text)
        self.assertIn("Passed only on retry", text)
        self.assertIn("`test_flaky.Flaky.test_once`", text)
        self.assertIn("0 not greater than 0", text)
        self.assertIn("Failed again on retry", text)
        self.assertIn("`test_broken.Broken.test_always`", text)

    def test_a_run_with_nothing_to_retry_leaves_the_step_summary_alone(self) -> None:
        write_suite(self.root, {"test_other.py": PASSING_ALONE})
        summary = Path(self.tmp.name) / "step-summary.md"

        code, out = run(self.root, summary=summary)

        self.assertEqual(0, code, out)
        self.assertFalse(summary.exists())

    def test_a_failing_subtest_retries_its_whole_test_once(self) -> None:
        write_suite(
            self.root,
            {
                "test_sub.py": """
                import os
                import unittest
                from pathlib import Path


                class Sub(unittest.TestCase):
                    def test_cases(self):
                        marker = Path(os.environ["RUNNER_FLAKY_DIR"]) / "sub"
                        first = not marker.exists()
                        marker.write_text("seen", encoding="utf-8")
                        for value in (1, 2):
                            with self.subTest(value=value):
                                self.assertFalse(first)
                """
            },
        )

        code, out = run(self.root)

        self.assertEqual(0, code, out)
        self.assertEqual(["FLAKY-RETRY-PASSED: test_sub.Sub.test_cases"], flaky_lines(out))

    def test_a_class_fixture_error_is_not_retried(self) -> None:
        write_suite(
            self.root,
            {
                "test_fixture.py": """
                import unittest


                class Fixture(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls):
                        raise RuntimeError("fixture broke")

                    def test_a(self):
                        pass
                """
            },
        )

        code, out = run(self.root)

        self.assertEqual(1, code, out)
        self.assertIn("fixture broke", out)
        self.assertNotIn("Failed again on retry", out)

    @unittest.skipUnless(importlib.util.find_spec("coverage"), "coverage is not installed")
    def test_the_retry_records_coverage_beside_the_workers(self) -> None:
        write_suite(self.root, {"test_flaky.py": flaky_suite("once")})
        work = Path(self.tmp.name) / "work"
        work.mkdir()
        env = {**os.environ, "RUNNER_FLAKY_DIR": str(self.markers)}
        env.pop("GITHUB_STEP_SUMMARY", None)
        suite = str(self.root)
        done = subprocess.run(
            [sys.executable, run_tests.__file__, "-s", suite, "-t", suite, "-j", "1", "--coverage"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            cwd=work,
            env=env,
        )
        self.assertEqual(0, done.returncode, done.stderr)
        # One data file from the worker and one from the retry, for `coverage combine` to merge.
        self.assertEqual(2, len(list(work.glob(".coverage.*"))), done.stderr)


PARALLEL_MODULE = """
import os
import time
import unittest


class Parallel(unittest.TestCase):
{methods}
"""
PARALLEL_METHOD = """
    def test_{name}(self):
        time.sleep(0.2)
        with open(os.environ["RUNNER_PID_LOG"], "a") as log:
            log.write(f"parallel {{os.getpid()}} {name}\\n")
"""
# Logs its pid, its name and which parallel worker pids are still alive when it runs.
SERIAL_MODULE = """
import os
import unittest

REAL_TIME_TESTS = {flag}


class Serial(unittest.TestCase):
    def test_after_workers(self):
        alive = []
        with open(os.environ["RUNNER_PID_LOG"]) as log:
            for line in log:
                kind, pid = line.split()[:2]
                if kind != "parallel":
                    continue
                try:
                    os.kill(int(pid), 0)
                except OSError:
                    continue
                alive.append(pid)
        with open(os.environ["RUNNER_PID_LOG"], "a") as log:
            log.write(f"serial {{os.getpid()}} {name} {{','.join(sorted(set(alive))) or '-'}}\\n")
"""


def parallel_module(*names: str) -> str:
    methods = "".join(PARALLEL_METHOD.format(name=name) for name in names)
    return PARALLEL_MODULE.format(methods=methods)


def serial_module(name: str, flag: str = "True") -> str:
    return SERIAL_MODULE.format(flag=flag, name=name)


class SerialPassTest(unittest.TestCase):
    """Modules that declare REAL_TIME_TESTS run alone, after every parallel worker has exited."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.log = self.root / "pids.log"
        self.log.write_text("", encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)
        env = mock_env({"RUNNER_PID_LOG": str(self.log)})
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)

    def lines(self) -> list[list[str]]:
        return [line.split() for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_a_declared_module_runs_after_the_workers_exit_in_its_own_process(self) -> None:
        write_suite(
            self.root,
            {
                "test_parallel.py": parallel_module("a", "b", "c", "d"),
                "test_real_time.py": serial_module("real_time"),
                # Only `True` declares it; anything else stays with the workers.
                "test_not_declared.py": serial_module("not_declared", flag="'yes'"),
            },
        )

        code, out = run(self.root)

        self.assertEqual(0, code, out)
        lines = self.lines()
        self.assertEqual(6, len(lines), lines)
        parallel_pids = {line[1] for line in lines if line[0] == "parallel"}
        last = lines[-1]
        self.assertEqual(["serial", "real_time", "-"], [last[0], *last[2:]], lines)
        self.assertNotIn(last[1], parallel_pids)
        undeclared = [line for line in lines if line[2:3] == ["not_declared"]]
        self.assertEqual(1, len(undeclared), lines)
        self.assertNotEqual(last[1], undeclared[0][1], lines)

    def test_each_declared_module_runs_in_exactly_one_shards_serial_pass(self) -> None:
        modules = {f"test_p{index}.py": parallel_module(f"p{index}") for index in range(4)}
        modules |= {f"test_rt_{name}.py": serial_module(name) for name in ("x", "y")}
        write_suite(self.root, modules)

        for shard in ("1/3", "2/3", "3/3"):
            with self.subTest(shard=shard):
                code, out = run(self.root, "--shard", shard)
                self.assertEqual(0, code, out)

        lines = self.lines()
        self.assertEqual(["x", "y"], sorted(line[2] for line in lines if line[0] == "serial"))
        self.assertEqual(4, sum(1 for line in lines if line[0] == "parallel"))
        self.assertTrue(all(line[3] == "-" for line in lines if line[0] == "serial"), lines)

    def test_a_failure_in_the_serial_pass_is_retried_too(self) -> None:
        markers = self.root / "markers"
        markers.mkdir()
        late = flaky_suite("late", header="\nREAL_TIME_TESTS = True\n")
        write_suite(self.root, {"test_late.py": late, "test_parallel.py": parallel_module("a")})
        with mock_env({"RUNNER_FLAKY_DIR": str(markers)}):
            code, out = run(self.root)

        self.assertEqual(0, code, out)
        self.assertEqual(["FLAKY-RETRY-PASSED: test_late.Flaky.test_late"], flaky_lines(out))
