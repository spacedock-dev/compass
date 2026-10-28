"""The parallel runner reaches the same verdict unittest would.

The runner replaces ``python -m unittest discover`` in every CI job that runs a
suite, so a runner that reported OK on a failing suite would turn the whole
quality gate green. Each check builds a small suite in a temporary directory and
runs it through ``run_tests.main`` with real spawned workers.
"""

from __future__ import annotations

import contextlib
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


def run(root: Path, *extra: str) -> tuple[int, str]:
    stderr = io.StringIO()
    with contextlib.redirect_stderr(stderr):
        code = run_tests.main(["-s", str(root), "-t", str(root), "-j", "2", *extra])
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
        with tempfile.TemporaryDirectory() as tmp:
            write_suite(Path(tmp), {"test_printing.py": PRINTING})
            done = subprocess.run(
                [sys.executable, run_tests.__file__, "-s", tmp, "-t", tmp, "-j", "1", *extra],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
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
