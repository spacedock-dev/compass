"""The flaky-test tally reads CI runs through a stubbed `gh` and changes nothing.

The run lists and the failed-attempt logs under `fixtures/flaky_tally` were recorded from this
repository's own Quality Gate and Validate runs on 2026-11-06 and trimmed to the lines around each
failure. The two `FLAKY-RETRY-PASSED` logs are written in the runner's format for a fixture test
id, because no run had retried a test when they were recorded. Nothing here reaches the network.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import flaky_tally

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "flaky_tally"
REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER = REPO_ROOT / "docs/flaky-tests.md"
TODAY = date(2026, 11, 7)

FIXTURE_FLAKE = "test_fixture_flake.FixtureFlakeTest.test_a_socket_read_finishes_in_time"
OBSERVER = (
    "test_observer.SupervisedModelCallTest."
    "test_a_cli_that_floods_its_output_file_is_stopped_near_the_bound"
)
SUPERVISE = (
    "test_supervise.GroupQuiescenceTest.test_a_group_that_remains_live_exhausts_the_same_deadline"
)
OUTLINE = (
    "test_session_outline.SessionOutlineTest."
    "test_all_parent_poll_reads_share_one_actual_byte_allowance"
)


class FakeGh:
    """Answers the `gh` calls the tally makes from the recorded fixtures, and remembers them."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(list(args))
        if args[:2] == ["run", "list"]:
            workflow = args[args.index("--workflow") + 1]
            return (FIXTURES / f"runs-{workflow.removesuffix('.yml')}.json").read_text("utf-8")
        if args[:2] == ["run", "view"] and "--log-failed" in args:
            attempt = args[args.index("--attempt") + 1]
            return (FIXTURES / f"failed-{args[2]}-{attempt}.log").read_text("utf-8")
        if args[:2] == ["run", "view"] and "--log" in args:
            recorded = FIXTURES / f"log-{args[2]}.log"
            if not recorded.exists():
                recorded = FIXTURES / "log-passing.log"
            return recorded.read_text("utf-8")
        message = f"the tally made a call the fixtures do not answer: {args}"
        raise AssertionError(message)

    def runs_viewed(self, flag: str) -> list[tuple[str, str | None]]:
        return sorted(
            (call[2], call[call.index("--attempt") + 1] if "--attempt" in call else None)
            for call in self.calls
            if call[:2] == ["run", "view"] and flag in call
        )


def run_main(*argv: str, ledger: Path = LEDGER) -> tuple[int, str, FakeGh]:
    gh = FakeGh()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = flaky_tally.main(
            ["--since", "1", "--ledger", str(ledger), *argv], gh=gh, today=TODAY
        )
    return code, out.getvalue(), gh


class LogParsingTest(unittest.TestCase):
    def test_a_retried_test_and_a_failed_test_are_read_from_a_github_log(self) -> None:
        lines = [
            (
                "Runtime floor (Python 3.12, scripts 2)\tRun tests\t2026-11-06T14:02:19.5524733Z "
                "FLAKY-RETRY-PASSED: test_pre_pr.LockTest.test_waits"
            ),
            # A byte order mark before the timestamp, as some recorded lines carry.
            (
                "Tests (macos-latest, dashboard 1)\tUNKNOWN STEP\t\ufeff2026-11-06T04:54:23.2Z "
                "ERROR: test_b (compass.skills.compass.tests.test_x.T.test_b) (command='make')"
            ),
            "quality-gate\tVerify\t2026-11-06T13:35:19.6Z ERROR: worker 2 discovery",
            "lint\tRun ruff\t2026-11-06T13:35:19.6Z FAIL: setUpClass (tests.test_y.Fixture)",
            (
                "lint\tRun ruff\t2026-11-06T13:35:19.6Z "
                "ERROR: test_gone (unittest.loader._FailedTest.test_gone)"
            ),
        ]

        found = flaky_tally.parse_log("\n".join(lines))

        self.assertEqual(
            [
                (
                    "retry",
                    "Runtime floor (Python 3.12, scripts 2)",
                    "test_pre_pr.LockTest.test_waits",
                ),
                ("failed", "Tests (macos-latest, dashboard 1)", "test_x.T.test_b"),
                ("failed", "lint", "test_y.Fixture (setUpClass)"),
            ],
            found,
        )

    def test_a_short_id_is_the_last_three_parts(self) -> None:
        self.assertEqual(
            "test_x.T.test_b", flaky_tally.short_id("compass.skills.compass.tests.test_x.T.test_b")
        )
        self.assertEqual("test_x.T.test_b", flaky_tally.short_id("test_x.T.test_b"))


class LedgerTest(unittest.TestCase):
    def test_the_committed_ledger_reads_and_holds_the_seeded_flakes(self) -> None:
        rows = flaky_tally.read_ledger(LEDGER.read_text(encoding="utf-8"))

        for test in (OUTLINE, SUPERVISE, OBSERVER):
            self.assertIn(test, rows)
        fixed = rows[
            "test_long_intent_sources.LongIntentSourcesTest."
            "test_a_reader_with_a_hundred_megabyte_record_can_open_recent_words_and_get_honest_menu_coverage"
        ]
        self.assertEqual(("fixed", "#817"), (fixed.status, fixed.fixing_pr))
        for row in rows.values():
            self.assertGreaterEqual(row.count, 1)
            self.assertLessEqual(row.first_seen, row.last_seen)

    def test_a_malformed_row_is_refused_rather_than_skipped(self) -> None:
        header = (
            "| Test | First seen | Last seen | Count | Where | Symptom | Status | Fixing PR |\n"
            "|---|---|---|---|---|---|---|---|\n"
        )
        good = '| `t.C.m` | 2026-11-01 | 2026-11-02 | 1 | run 1 | "x" | open | |\n'
        self.assertIn("t.C.m", flaky_tally.read_ledger(header + good))
        for broken in (
            good.replace("| 1 |", "| one |"),
            good.replace("open", "flaky"),
            good.replace("2026-11-01", "Nov 1"),
            good.replace("`t.C.m`", "t.C.m"),
            good.replace(" | open | |", " | open |"),
            good + good,
            good.replace("2026-11-01", "2026-11-03"),
        ):
            with self.subTest(row=broken), self.assertRaises(ValueError):
                flaky_tally.read_ledger(header + broken)
        with self.assertRaises(ValueError):
            flaky_tally.read_ledger("# Flaky tests\n\nNo table here.\n")


class TallyTest(unittest.TestCase):
    def test_retries_and_failures_on_code_that_passed_are_counted_per_run(self) -> None:
        code, out, _gh = run_main()

        self.assertEqual(0, code, out)
        self.assertIn(f"  2  {FIXTURE_FLAKE}", out)
        for test in (OBSERVER, SUPERVISE, OUTLINE):
            self.assertIn(f"  1  {test}", out)
        self.assertIn("run 42188478248 attempt 1", out)
        self.assertNotIn("41952960482", out)

    def test_only_failed_attempts_whose_code_later_passed_are_read(self) -> None:
        _code, _out, gh = run_main()

        # The push failure shares its commit with a passing queue run, the queue failure has a
        # later passing entry for the same pull request, and the re-run's first attempt failed.
        # The pull request failure on a commit that never passed is not a flake candidate.
        self.assertEqual(
            [("42188478248", "1"), ("42225631356", "1"), ("42227928443", "1")],
            gh.runs_viewed("--log-failed"),
        )

    def test_every_finished_run_in_the_window_is_read_for_retries(self) -> None:
        _code, _out, gh = run_main()

        viewed = {run for run, _attempt in gh.runs_viewed("--log")}
        self.assertEqual(
            {
                "42229673360",
                "42227928443",
                "42226958994",
                "42225631356",
                "42200076259",
                "42188478248",
                "42229673293",
            },
            viewed,
        )

    def test_against_the_committed_ledger_only_the_unrecorded_test_is_new(self) -> None:
        _code, out, _gh = run_main()

        diff = out.split("Against ", 1)[1]
        self.assertIn(f"NEW     {FIXTURE_FLAKE}: 2 runs (42226958994, 42229673360)", diff)
        self.assertNotIn("UPDATE", diff)
        self.assertNotIn(SUPERVISE, diff)

    def test_unrecorded_runs_raise_a_count_and_a_fixed_test_that_fails_is_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "flaky-tests.md"
            ledger.write_text(
                "| Test | First seen | Last seen | Count | Where | Symptom | Status | Fixing PR |\n"
                "|---|---|---|---|---|---|---|---|\n"
                f'| `{SUPERVISE}` | 2026-11-01 | 2026-11-05 | 1 | Linux; run 41000000000 | "x" '
                "| open | |\n"
                f'| `{OBSERVER}` | 2026-11-01 | 2026-11-01 | 3 | macOS; run 41000000001 | "y" '
                "| fixed | #900 |\n"
                f'| `{OUTLINE}` | 2026-11-06 | 2026-11-06 | 1 | macOS; run 42188478248 | "z" '
                "| open | |\n",
                encoding="utf-8",
            )
            before = ledger.read_bytes()

            _code, out, _gh = run_main(ledger=ledger)

            self.assertEqual(before, ledger.read_bytes())
        diff = out.split("Against ", 1)[1]
        self.assertIn(
            f"UPDATE  {SUPERVISE}: count 1 -> 2, last seen 2026-11-05 -> 2026-11-06 (42225631356)",
            diff,
        )
        self.assertIn(f"REOPEN  {OBSERVER}: fixed in #900, failed again in 42227928443", diff)
        self.assertNotIn(OUTLINE, diff)

    def test_it_only_reads_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                _code, _out, gh = run_main("--repo", "spacedock-dev/compass")
            finally:
                os.chdir(cwd)
            self.assertEqual([], list(Path(tmp).iterdir()))
        for call in gh.calls:
            self.assertIn(call[:2], (["run", "list"], ["run", "view"]))
            self.assertEqual("spacedock-dev/compass", call[call.index("--repo") + 1])

    def test_a_failed_gh_call_is_an_error_not_an_empty_tally(self) -> None:
        def broken(_args: list[str]) -> str:
            raise flaky_tally.GhError("gh: authentication required")

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = flaky_tally.main(["--ledger", str(LEDGER)], gh=broken, today=TODAY)

        self.assertEqual(1, code)
        self.assertIn("authentication required", err.getvalue())


if __name__ == "__main__":
    unittest.main()
