"""A check `&&` joins ahead of a later check shown to have run passed.

`&&` runs what follows only after what precedes it exits 0. Measured on an 18-hour session with
its subagents (2026-10-28): `ruff check . && mypy 2>&1 | tail -3` read "ran, result not recorded"
for ruff although mypy's own summary on the last line proves ruff exited 0.
"""

from __future__ import annotations

from .test_claude_checks import ClaudeChecksTestCase, results_by_title

MYPY_OK = "Success: no issues found in 3 source files"
MYPY_FAILED = "Found 2 errors in 1 file (checked 3 source files)"


class AChainedCheckPasses(ClaudeChecksTestCase):
    def results(self, command: str, output: str, *, is_error: bool = False) -> dict[str, str]:
        self.session.bash(command, output, is_error=is_error)
        return results_by_title(self.read()[0])

    def test_an_earlier_check_passes_when_the_last_ones_summary_shows_it_ran(self) -> None:
        found = self.results("ruff check . && mypy src 2>&1 | tail -3", MYPY_OK)
        self.assertEqual({"ruff check .": "passed", "mypy src": "passed"}, found)

    def test_a_failing_last_check_still_shows_the_earlier_one_passed(self) -> None:
        found = self.results("ruff check . && mypy src 2>&1 | tail -3", MYPY_FAILED, is_error=True)
        self.assertEqual("passed", found["ruff check ."])
        self.assertEqual("failed", found["mypy src"])

    def test_the_source_says_how_it_was_known(self) -> None:
        self.session.bash("ruff check . && mypy src 2>&1 | tail -3", MYPY_OK)
        ruff = next(event for event in self.read()[0] if event.get("title") == "ruff check .")
        self.assertEqual("chain", ruff["result_source"])

    def test_nothing_is_passed_without_the_later_checks_own_summary(self) -> None:
        for output in ("", "some other text", "OK"):
            with self.subTest(output=output):
                self.setUp()
                found = self.results("ruff check . && mypy src 2>&1 | tail -3", output)
                self.assertEqual("not-recorded", found["ruff check ."])

    def test_a_semicolon_or_or_between_them_proves_nothing(self) -> None:
        for command in (
            "ruff check .; mypy src 2>&1 | tail -3",
            "ruff check . || mypy src 2>&1 | tail -3",
            "ruff check . | cat && mypy src 2>&1 | tail -3",
        ):
            with self.subTest(command=command):
                self.setUp()
                found = self.results(command, MYPY_OK)
                self.assertNotEqual("passed", found.get("ruff check ."))

    def test_an_earlier_check_of_the_same_runner_makes_the_last_line_ambiguous(self) -> None:
        found = self.results("mypy a && mypy b 2>&1 | tail -3", MYPY_OK)
        self.assertNotEqual("passed", found["mypy a"])

    def test_output_printed_after_the_last_check_is_not_its_summary(self) -> None:
        found = self.results(f"ruff check . && mypy src; echo '{MYPY_OK}'", MYPY_OK)
        self.assertNotEqual("passed", found["ruff check ."])
