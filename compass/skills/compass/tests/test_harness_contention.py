"""Run the ledger's behavioural assertions with deterministic scheduler interference."""

from __future__ import annotations

import socket
import subprocess
import sys
import time
import types
import unittest
from typing import Any
from unittest import mock

from compass_runtime import supervise

from . import (
    test_ci_read,
    test_ci_read_gitlab,
    test_lifecycle,
    test_observer,
    test_project_script_checks,
    test_react_frontend,
    test_supervise,
    test_transcripts,
)

# Real child processes and a real installed-copy server; run after the parallel workers.
REAL_TIME_TESTS = True


class AReaderCanTrustTheHarnessUnderContention(unittest.TestCase):
    def check_case(self, case: unittest.TestCase) -> None:
        result = unittest.TestResult()
        case.run(result)
        self.assertEqual([], result.errors + result.failures)
        self.assertEqual([], result.skipped, "the behavioural proof did not run")

    @unittest.skipIf(sys.platform == "win32", "terminal hangups are POSIX")
    def test_a_reader_closing_the_terminal_during_thread_start_still_gets_cleanup(self) -> None:
        script = test_lifecycle._HANGUP_DAEMON.replace(
            "lifecycle._register_sigterm_exit()",
            """real_start = threading.Thread.start
def delayed_start(self):
    real_start(self)
    if threading.current_thread() is threading.main_thread():
        time.sleep(120)
threading.Thread.start = delayed_start
lifecycle._register_sigterm_exit()""",
        )
        with mock.patch.object(test_lifecycle, "_HANGUP_DAEMON", script):
            for method in (
                "test_a_hangup_to_a_foreground_daemons_group_kills_the_cli",
                "test_a_quit_from_the_terminal_kills_the_cli",
            ):
                with self.subTest(method=method):
                    self.check_case(test_lifecycle.ATerminalHangupStillCleansUpTest(method))

    def test_a_reader_of_a_long_record_is_not_charged_for_another_processes_cpu(self) -> None:
        # The old best-of-three baseline was 10 ms; one scheduler stall on every
        # large sample made linear code fail. No actual load or sleep is needed.
        readings = iter([0.0, 0.01] * 3 + [0.0, 1.0] * 3)
        clock = types.SimpleNamespace(perf_counter=lambda: next(readings))
        with mock.patch.object(test_transcripts, "time", clock):
            self.check_case(
                test_transcripts.ReviewFixTest("test_reverse_lines_stays_linear_on_one_long_record")
            )

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_a_reader_keeps_the_previous_check_while_the_next_repository_is_prepared(self) -> None:
        case = test_project_script_checks.ProjectScriptTestCase()
        case.setUp()
        try:

            def git_output(*args: str) -> bytes:
                result = subprocess.run(
                    [test_project_script_checks.GIT or "git", *args],
                    cwd=case.cwd,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(
                    0,
                    result.returncode,
                    "a pending check lost its repository: " + result.stderr.decode(),
                )
                return result.stdout

            case.commit(
                {"package.json": test_project_script_checks.package(typecheck="tsc --noEmit")}
            )
            # A pending object read must not lose its database between subtests.
            prior = git_output("rev-parse", "HEAD").strip()
            case.fresh_repo()
            case.commit({"package.json": test_project_script_checks.package(typecheck="echo skip")})
            old = git_output("show", prior.decode() + ":package.json")
            self.assertIn(b"tsc --noEmit", old)
            history = git_output("rev-list", "--count", "HEAD")
            self.assertEqual(b"1", history.strip(), "the next case inherited prior history")
        finally:
            case.doCleanups()

    def test_a_reader_can_start_again_while_another_process_owns_the_suggested_port(self) -> None:
        case = test_react_frontend.InstalledFrontendTest(
            "test_a_second_start_on_a_busy_port_says_to_use_the_running_dashboard"
        )
        with socket.socket() as contender:
            contender.bind(("127.0.0.1", 0))
            contender.listen()
            with mock.patch.object(case, "free_port", return_value=contender.getsockname()[1]):
                self.check_case(case)

    @unittest.skipIf(sys.platform == "win32", "native ps observation is POSIX")
    def test_a_reader_gets_the_same_kill_and_reply_after_a_delayed_reap_probe(self) -> None:
        real_popen = subprocess.Popen
        offset = 0.0

        def delayed_probe(*args: Any, **kwargs: Any) -> subprocess.Popen[Any]:
            nonlocal offset
            if args and args[0][0] == "/bin/ps":
                offset += supervise.REAP_TIMEOUT_SEC + 1
            return real_popen(*args, **kwargs)

        real_monotonic = time.monotonic
        wall_clock = types.SimpleNamespace(
            monotonic=lambda: real_monotonic() + offset, sleep=time.sleep
        )
        cases = (
            test_supervise.SupervisedRunTest(
                "test_the_daemons_own_process_group_is_never_signalled"
            ),
            test_supervise.AnOutputFileHasABoundTest("test_the_poll_fallback_also_stops_a_flood"),
            test_ci_read.TheLaunchKeepsEverySafeguard(
                "test_output_that_is_not_the_schema_is_unreadable"
            ),
            test_ci_read_gitlab.TheClosedErrorTokens(
                "test_output_that_is_not_the_schema_is_unreadable"
            ),
            test_observer.SupervisedModelCallTest(
                "test_a_cli_that_floods_its_output_file_is_stopped_near_the_bound"
            ),
        )
        with (
            mock.patch.object(supervise, "time", wall_clock),
            mock.patch.object(subprocess, "Popen", side_effect=delayed_probe),
        ):
            for case in cases:
                with self.subTest(case=case.id()):
                    self.check_case(case)
