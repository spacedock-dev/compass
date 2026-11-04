"""Startup owns bounded historical recovery; probes never signal Windows processes."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
import types
import unittest
from typing import Any
from unittest import mock

from compass_runtime import lifecycle, reading_jobs, summary_jobs, supervise
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_long_recovery as recovery
from compass_runtime import reading_policy as policy

from . import test_reading_recovered_publication as fixtures


class LongRecoveryStartupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = fixtures.RecoveredPublicationTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state

    def process(self, pid: int = 42) -> Any:
        probe: Any = getattr(lifecycle, "_recovery_process_exists", None)
        self.assertTrue(callable(probe), "recovery needs an independent conservative process probe")
        return probe(pid)

    def test_posix_only_esrch_proves_absence(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            for code, answer in (
                (errno.ESRCH, False),
                (errno.EPERM, True),
                (errno.EACCES, None),
                (errno.EIO, None),
            ):
                with mock.patch.object(os, "kill", side_effect=OSError(code, "synthetic")) as kill:
                    self.assertIs(answer, self.process())
                    kill.assert_called_once_with(42, 0)
            with mock.patch.object(os, "kill") as kill:
                self.assertIs(True, self.process())
                self.assertIsNone(self.process(0))
                kill.assert_called_once_with(42, 0)

    def test_windows_native_handle_proof_closes_handles_without_signaling(self) -> None:
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 42
        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(
                ctypes, "windll", types.SimpleNamespace(kernel32=kernel), create=True
            ),
            mock.patch.object(os, "kill", side_effect=AssertionError),
        ):
            for result, answer in ((0, False), (258, True), (0xFFFFFFFF, None), (1, None)):
                kernel.WaitForSingleObject.return_value = result
                self.assertIs(answer, self.process())
            self.assertEqual(4, kernel.CloseHandle.call_count)
            kernel.OpenProcess.return_value = 0
            self.assertIsNone(self.process())
            self.assertEqual(4, kernel.CloseHandle.call_count)
            kernel.OpenProcess.side_effect = OSError("unknown")
            self.assertIsNone(self.process())

    def startup(self) -> Any:
        function: Any = getattr(lifecycle, "_recover_long_jobs", None)
        self.assertTrue(callable(function), "one startup owner must retain bounded inspection")
        return function(self.config, self.state, now=102)

    def test_real_startup_publishes_exact_once_without_execution_authority_or_discard(self) -> None:
        self.fixture.fixture.reserve()
        self.fixture.die()
        with (
            mock.patch.object(lifecycle, "dashboard_alive", return_value=False),
            mock.patch.object(
                lifecycle, "_recovery_process_exists", return_value=False, create=True
            ),
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(policy, "reserve_registered_pass", side_effect=AssertionError),
            mock.patch.object(markers, "begin", side_effect=AssertionError),
            mock.patch.object(recovery, "discard_terminal", side_effect=AssertionError),
        ):
            result = self.startup()
            self.assertEqual(1, len(result.items))
            self.assertEqual((), self.startup().items)
        self.assertEqual(1, self.fixture.fixture.entry()["readings"])

    def test_unknown_accounting_is_returned_unresolved_without_publication(self) -> None:
        self.fixture.die()
        policy.store_path(self.config).unlink()
        with (
            mock.patch.object(lifecycle, "dashboard_alive", return_value=False),
            mock.patch.object(
                lifecycle, "_recovery_process_exists", return_value=False, create=True
            ),
            mock.patch.object(recovery, "publish_terminal", side_effect=AssertionError),
            mock.patch.object(recovery, "discard_terminal", side_effect=AssertionError),
        ):
            result = self.startup()
        self.assertEqual("unknown", result.items[0].inspected.accounting)
        self.assertTrue(self.fixture.path.exists())

    def test_serve_orders_one_recovery_after_sigterm_before_observation_and_http(self) -> None:
        events: list[str] = []
        observer = types.SimpleNamespace(
            start=lambda: events.append("observe"), stop=lambda **_: None, capabilities=lambda: ()
        )
        server: Any = types.SimpleNamespace(
            application=types.SimpleNamespace(state=self.state),
            observation=observer,
            serve_forever=lambda: events.append("http"),
            server_close=lambda: None,
        )
        with (
            mock.patch.object(
                lifecycle, "_register_sigterm_exit", side_effect=lambda: events.append("signal")
            ),
            mock.patch.object(
                lifecycle, "write_state", side_effect=lambda *_a, **_k: events.append("state")
            ),
            mock.patch.object(lifecycle, "remove_state"),
            mock.patch.object(
                lifecycle,
                "_recover_long_jobs",
                side_effect=lambda *_a, **_k: events.append("long"),
                create=True,
            ) as long,
            mock.patch.object(
                reading_jobs,
                "recover",
                side_effect=lambda *_a, **_k: events.append("ordinary"),
            ),
            mock.patch.object(
                summary_jobs,
                "recover",
                side_effect=lambda *_a, **_k: events.append("summary"),
            ),
            mock.patch.object(supervise, "kill_all"),
            mock.patch.object(lifecycle, "run_producer", side_effect=AssertionError),
        ):
            lifecycle.serve(self.config, server, 4553, started=1, diagnostic_sink=lambda _: None)
        self.assertEqual(
            ["signal", "state", "ordinary", "summary", "long", "observe", "http"], events
        )
        long.assert_called_once()
