"""`;`-separated checks each take their own summary line, in order (owner, 2026-10-28).

Measured on an 18-hour session: agents ran `a | tail -2; b | tail -1; c && d | tail -1`, whose
status is the last filter's, so every check but the last read "ran, result not recorded", and a
test-first red run was never cleared by the green re-run that followed it.
"""

from __future__ import annotations

from .test_claude_checks import ClaudeChecksTestCase, results_by_title

RAN = "Ran 4 tests in 0.010s"
MYPY_OK = "Success: no issues found in 3 source files"


class EachGroupTakesItsOwnSummary(ClaudeChecksTestCase):
    def results(self, command: str, output: str) -> dict[str, str]:
        self.session.bash(command, output, is_error=False)
        return results_by_title(self.read()[0])

    def test_two_tailed_unittest_runs_and_a_chain_each_read_their_own_line(self) -> None:
        found = self.results(
            "python3 -m unittest tests.test_a 2>&1 | tail -3; "
            "python3 -m unittest tests.test_b 2>&1 | tail -3; "
            "ruff check -q . && mypy src 2>&1 | tail -1",
            f"{RAN}\n\nOK\n{RAN}\n\nFAILED (failures=1)\n{MYPY_OK}",
        )
        self.assertEqual("passed", found["python3 -m unittest tests.test_a"])
        self.assertEqual("failed", found["python3 -m unittest tests.test_b"])
        self.assertEqual("passed", found["ruff check -q ."])
        self.assertEqual("passed", found["mypy src"])

    def test_a_bare_ok_counts_only_where_the_command_names_its_tests(self) -> None:
        found = self.results(
            "python3 -m unittest tests.test_a 2>&1 | tail -1; "
            "python3 -m unittest discover 2>&1 | tail -1; mypy src",
            f"OK\nOK\n{MYPY_OK}",
        )
        self.assertEqual("passed", found["python3 -m unittest tests.test_a"])
        self.assertNotEqual("passed", found["python3 -m unittest discover"])

    def test_setup_before_the_first_check_may_run(self) -> None:
        found = self.results(
            "sed -i '' 's/a/b/' src/x.py && python3 -m unittest tests.test_a 2>&1 | tail -1; "
            "mypy src",
            f"OK\n{MYPY_OK}",
        )
        self.assertEqual("passed", found["python3 -m unittest tests.test_a"])

    def test_one_line_too_many_or_too_few_reads_nothing(self) -> None:
        for output in (f"OK\nOK\n{MYPY_OK}", MYPY_OK, f"{MYPY_OK}\nOK"):
            with self.subTest(output=output):
                self.setUp()
                found = self.results(
                    "python3 -m unittest tests.test_a 2>&1 | tail -1; mypy src", output
                )
                self.assertEqual("not-recorded", found["python3 -m unittest tests.test_a"])

    def test_a_printing_command_between_checks_reads_nothing(self) -> None:
        found = self.results(
            "python3 -m unittest tests.test_a 2>&1 | tail -1; echo done; mypy src",
            f"OK\ndone\n{MYPY_OK}",
        )
        self.assertEqual("not-recorded", found["python3 -m unittest tests.test_a"])

    def test_a_projects_run_tests_script_reads_as_unittest(self) -> None:
        found = self.results(
            "python3 scripts/run_tests.py -s tests -p 'test_a.py' 2>&1 | tail -3; mypy src",
            f"{RAN} (2 workers)\n\nOK\n{MYPY_OK}",
        )
        # The `-p` value is masked in the title, so the run is found by how the line starts.
        run_tests = [result for title, result in found.items() if "run_tests.py" in title]
        self.assertEqual(["passed"], run_tests)


PYTEST_FAILED = "=== 1 failed, 3 passed in 0.50s ==="
RUFF_OK = "All checks passed!"


class NothingIsPassedThatDidNotPass(ClaudeChecksTestCase):
    """The review's false passes of 2026-10-28, each read as passed before the fix."""

    def results(self, command: str, output: str) -> dict[str, str]:
        self.session.bash(command, output, is_error=False)
        return results_by_title(self.read()[0])

    def test_a_runner_repeated_inside_a_group_reads_nothing(self) -> None:
        found = self.results(
            "pytest tests/a && pytest tests/b | tail -1; ruff check . | tail -1",
            f"FAILED tests/a.py::t\n{PYTEST_FAILED}\n{RUFF_OK}",
        )
        self.assertNotEqual("passed", found["pytest tests/a"])
        self.assertNotEqual("failed", found["pytest tests/b"])

    def test_a_later_group_that_does_not_match_leaves_the_earlier_ones(self) -> None:
        found = self.results(
            "python3 -m unittest tests.test_a; mypy srcx | tail -1; ruff check .",
            f"OK\nFAIL: test_x\nFAILED (failures=1)\nmypy: can't read file 'srcx'\n{RUFF_OK}",
        )
        self.assertNotEqual("passed", found["python3 -m unittest tests.test_a"])

    def test_setup_that_may_print_reads_nothing(self) -> None:
        for setup in ("echo OK", "curl -sf http://127.0.0.1:8000/healthz"):
            with self.subTest(setup=setup):
                self.setUp()
                found = self.results(
                    f"{setup}; python3 -m unittest tests.test_a 2>&1 | tail -1; mypy src",
                    f"OK\nTraceback\nSyntaxError: invalid syntax\n{MYPY_OK}",
                )
                self.assertNotEqual("passed", found["python3 -m unittest tests.test_a"])

    def test_a_package_name_is_not_a_named_test(self) -> None:
        found = self.results("python3 -m unittest tests 2>&1 | tail -1; mypy src", f"OK\n{MYPY_OK}")
        self.assertNotEqual("passed", found["python3 -m unittest tests"])

    def test_a_check_that_cannot_fail_is_not_passed_by_its_chain(self) -> None:
        self.session.bash(
            "ruff check --exit-zero . && mypy src | tail -1",
            f"x.py:1:1: F401 unused\nFound 1 error.\n{MYPY_OK}",
            is_error=False,
        )
        found = results_by_title(self.read()[0])
        self.assertNotEqual("passed", found["ruff check --exit-zero ."])
