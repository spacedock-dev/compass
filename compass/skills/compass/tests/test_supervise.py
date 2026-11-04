"""The supervised runner every model call goes through (DRC-4686).

Each test runs a real child: `sys.executable -c ...` standing in for a CLI.
A fake runner cannot show the property that matters, which is that the whole
tree the CLI started dies on a timeout, and that the daemon's own group is
never the one signalled.
"""

from __future__ import annotations

import contextlib
import errno
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import supervise

from .support import process_alive

# A CLI that starts a grandchild, writes the grandchild's pid where the test can
# read it, and then outlives any timeout the test sets.
_SPAWNS_A_GRANDCHILD = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "with open(sys.argv[1], 'w') as out:\n"
    "    out.write(str(child.pid))\n"
    "time.sleep(60)\n"
)


def _wait_until(predicate: Any, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


class GroupQuiescenceTest(unittest.TestCase):
    def test_only_a_running_member_of_the_group_keeps_its_output_open(self) -> None:
        for output, expected in (
            ("42 S\n42 Z\n", True),
            ("42 Z+\n17 S\n", False),
            ("42 Z\n17 ?\n", False),
            ("17 S\n", None),
            ("42 ?\n", None),
            ("not a snapshot\n", None),
            ("", None),
        ):
            with self.subTest(snapshot=output):
                self.assertIs(expected, supervise._group_state(output, 42))

    @unittest.skipIf(sys.platform == "win32", "native POSIX process states")
    def test_the_native_probe_distinguishes_a_running_group_from_its_zombie(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
        )
        try:
            self.assertIs(True, supervise._group_running(process.pid, 1.0))
            process.kill()
            self.assertTrue(_wait_until(lambda: supervise._state(process.pid, 0.0) == "exited"))
            self.assertIs(False, supervise._group_running(process.pid, 1.0))
            self.assertIsNone(process.returncode, "the probe reaped the reserved leader identity")
        finally:
            with contextlib.suppress(OSError):
                process.kill()
            process.wait()

    def test_a_probe_spawn_that_stalls_cannot_hold_the_reap_past_its_bound(self) -> None:
        started, release, cleaned = threading.Event(), threading.Event(), threading.Event()

        class Probe:
            stdout = None

            def poll(self) -> None:
                return None

            def kill(self) -> None:
                pass

            def communicate(self) -> None:
                cleaned.set()

        def spawn(*_a: Any, **_kw: Any) -> Probe:
            started.set()
            release.wait(3)
            return Probe()

        try:
            with mock.patch.object(subprocess, "Popen", spawn):
                before = time.monotonic()
                self.assertIsNone(supervise._group_running(42, 0.05))
                # The stub blocks for up to three seconds, so anything under two shows the probe gave up.
                self.assertLess(time.monotonic() - before, 2.0)
                self.assertTrue(started.is_set())
                release.set()
                self.assertTrue(cleaned.wait(1), "a late probe was not killed and reaped")
        finally:
            release.set()

    def test_an_unreadable_snapshot_does_not_prove_the_group_stopped(self) -> None:
        with mock.patch.object(subprocess, "Popen", side_effect=OSError("unavailable")):
            self.assertIsNone(supervise._group_running(42, 1.0))

    def test_a_failed_native_probe_cannot_prove_the_group_stopped(self) -> None:
        process = mock.Mock(returncode=1)
        process.communicate.return_value = ("42 Z\n", None)
        process.poll.return_value = 1
        with mock.patch.object(subprocess, "Popen", return_value=process):
            self.assertIsNone(supervise._group_running(42, 1.0))
        process.stdout.close.assert_called_once()

    def test_a_probe_read_timeout_kills_and_reaps_only_that_probe(self) -> None:
        process = mock.Mock(returncode=None)
        process.communicate.side_effect = (subprocess.TimeoutExpired("ps", 0.01), ("", None))
        process.poll.return_value = None
        with mock.patch.object(subprocess, "Popen", return_value=process):
            self.assertIsNone(supervise._group_running(42, 1.0))
        process.kill.assert_called_once()
        self.assertEqual(2, process.communicate.call_count)
        process.stdout.close.assert_called_once()

    def test_a_probe_thread_that_cannot_start_does_not_prove_the_group_stopped(self) -> None:
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("unavailable")):
            self.assertIsNone(supervise._group_running(42, 1.0))

    def test_an_expired_group_deadline_starts_no_further_probe(self) -> None:
        group = supervise.Group(_FakeWindowsProcess(exits=True))  # type: ignore[arg-type]
        with (
            mock.patch.object(supervise, "_group_running") as probe,
            self.assertRaises(supervise.UnstoppedError),
        ):
            group._wait_group(time.monotonic() - 1)
        probe.assert_not_called()

    def test_a_group_that_remains_live_exhausts_the_same_deadline(self) -> None:
        group = supervise.Group(_FakeWindowsProcess(exits=True))  # type: ignore[arg-type]
        before = time.monotonic()
        with (
            mock.patch.object(supervise, "_group_running", return_value=True) as probe,
            self.assertRaises(supervise.UnstoppedError),
        ):
            group._wait_group(before + 0.025)
        self.assertTrue(probe.called)
        self.assertLess(time.monotonic() - before, 5.0)

    @unittest.skipIf(sys.platform == "win32", "POSIX leader identity")
    def test_failed_quiescence_observation_refuses_and_reaps_the_killed_leader(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
        )
        group = supervise.Group(process)
        try:
            with (
                mock.patch.object(supervise, "_group_running", return_value=None),
                self.assertRaises(supervise.UnstoppedError),
            ):
                group._finish()
            self.assertIsNotNone(process.returncode)
            with mock.patch.object(os, "killpg", side_effect=AssertionError("reused group")):
                group.kill()
        finally:
            with contextlib.suppress(OSError):
                process.kill()
            process.wait()

    def test_a_windows_job_whose_writers_do_not_stop_has_one_reap_deadline(self) -> None:
        group = supervise.Group(_FakeWindowsProcess(exits=True), job=7)  # type: ignore[arg-type]
        group._reap_by = time.monotonic() + 0.05
        before = time.monotonic()
        with (
            mock.patch.object(supervise._windows, "terminate", return_value=True),
            mock.patch.object(supervise._windows, "active", return_value=1),
            self.assertRaises(supervise.UnstoppedError),
        ):
            group._finish_windows()
        self.assertLess(time.monotonic() - before, 5.0)

    def test_a_failed_windows_job_query_cannot_publish_a_normal_reply(self) -> None:
        group = supervise.Group(_FakeWindowsProcess(exits=True), job=7)  # type: ignore[arg-type]
        with (
            mock.patch.object(supervise._windows, "terminate", return_value=True),
            mock.patch.object(supervise._windows, "active", side_effect=OSError("query failed")),
            self.assertRaises(supervise.UnstoppedError),
        ):
            group._finish_windows()
        self.assertFalse(group.cleanup_complete())

    def test_windows_cleanup_fact_requires_successful_job_quiescence(self) -> None:
        process = cast("subprocess.Popen[Any]", _FakeWindowsProcess(exits=True))
        group = supervise.Group(process, job=7)
        self.assertFalse(group.cleanup_complete())
        with (
            mock.patch.object(supervise._windows, "terminate", return_value=True),
            mock.patch.object(supervise._windows, "active", return_value=0),
        ):
            group._finish_windows()
        self.assertTrue(group.cleanup_complete())


class SupervisedRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, True))
        # A shutdown closes the runner for the life of the process. Each test
        # gets an open one, so a test that shuts it cannot close it for the next.
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _grandchild(self, pid_file: Path) -> int:
        self.assertTrue(
            _wait_until(lambda: pid_file.exists() and pid_file.read_text().strip()),
            "the fake CLI never started its grandchild",
        )
        return int(pid_file.read_text())

    def test_a_timeout_kills_the_grandchild_as_well_as_the_child(self) -> None:
        pid_file = self.home / "grandchild.pid"
        seen: list[supervise.Group] = []

        def spawned(group: supervise.Group) -> None:
            seen.append(group)

        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            supervise.run(
                [sys.executable, "-c", _SPAWNS_A_GRANDCHILD, str(pid_file)],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                timeout=3,
                check=False,
                on_spawn=spawned,
            )
        grandchild = self._grandchild(pid_file)
        self.assertLess(time.monotonic() - started, 30, "the timeout did not bound the call")
        self.assertEqual(1, len(seen))
        self.assertFalse(process_alive(seen[0].pid), "the child outlived its timeout")
        self.assertTrue(seen[0].cleanup_complete(), "a clean timeout must retain cleanup proof")
        self.assertTrue(
            _wait_until(lambda: not process_alive(grandchild)),
            "the grandchild outlived the timeout: only the direct child was killed",
        )

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_the_daemons_own_process_group_is_never_signalled(self) -> None:
        pid_file = self.home / "grandchild.pid"
        own = os.getpgrp()
        with (
            mock.patch.object(os, "killpg", wraps=os.killpg) as killpg,
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            supervise.run(
                [sys.executable, "-c", _SPAWNS_A_GRANDCHILD, str(pid_file)],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            )
        groups = [call.args[0] for call in killpg.call_args_list]
        self.assertTrue(groups, "nothing was killed, so this test proved nothing")
        self.assertNotIn(own, groups)

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_a_kill_aimed_at_the_daemons_own_group_is_refused(self) -> None:
        with mock.patch.object(os, "killpg") as killpg:
            supervise.kill_group(os.getpgrp())
            supervise.kill_group(0)
            supervise.kill_group(1)
        killpg.assert_not_called()

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_the_child_leads_a_process_group_of_its_own(self) -> None:
        out = self.home / "group.txt"
        with out.open("w") as handle:
            supervise.run(
                [sys.executable, "-c", "import os; print(os.getpgrp(), os.getpid())"],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=30,
            )
        group, pid = (int(part) for part in out.read_text().split())
        self.assertEqual(pid, group)
        self.assertNotEqual(os.getpgrp(), group)

    def test_a_long_prompt_arrives_whole_on_stdin(self) -> None:
        out = self.home / "length.txt"
        prompt = "x" * 16_384
        with out.open("w") as handle:
            result = supervise.run(
                [sys.executable, "-c", "import sys; print(len(sys.stdin.read()))"],
                input=prompt,
                stdout=handle,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
        self.assertEqual(0, result.returncode)
        self.assertEqual("16384", out.read_text().strip())

    def test_on_spawn_fires_once_while_the_child_is_running(self) -> None:
        running: list[bool] = []

        def spawned(group: supervise.Group) -> None:
            running.append(group.running())

        result = supervise.run(
            [sys.executable, "-c", "import time; time.sleep(0.5)"],
            input="",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            on_spawn=spawned,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual([True], running)

    def test_a_nonzero_exit_is_returned_rather_than_raised(self) -> None:
        result = supervise.run(
            [sys.executable, "-c", "raise SystemExit(3)"],
            input="",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        self.assertEqual(3, result.returncode)

    def test_a_failing_on_spawn_still_kills_and_reaps_the_child(self) -> None:
        seen: list[supervise.Group] = []

        def spawned(group: supervise.Group) -> None:
            seen.append(group)
            raise RuntimeError("the job could not be told")

        with self.assertRaises(RuntimeError):
            supervise.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                on_spawn=spawned,
            )
        self.assertFalse(seen[0].running())
        self.assertEqual(frozenset(), supervise.live())

    def test_shutdown_kills_every_running_supervised_child(self) -> None:
        pid_file = self.home / "grandchild.pid"
        spawned = threading.Event()
        results: list[Any] = []

        def call() -> None:
            results.append(
                supervise.run(
                    [sys.executable, "-c", _SPAWNS_A_GRANDCHILD, str(pid_file)],
                    input="",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    on_spawn=lambda _group: spawned.set(),
                )
            )

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        self.assertTrue(spawned.wait(10))
        grandchild = self._grandchild(pid_file)
        self.assertEqual(1, len(supervise.live()))
        supervise.kill_all()
        worker.join(timeout=15)
        self.assertFalse(worker.is_alive(), "a killed child left its caller waiting")
        self.assertNotEqual(0, results[0].returncode)
        self.assertTrue(_wait_until(lambda: not process_alive(grandchild)))
        self.assertEqual(frozenset(), supervise.live())

    # Correction round (review F2): nothing spawns once shutdown has begun.

    def test_a_spawn_after_shutdown_is_refused_and_starts_nothing(self) -> None:
        supervise.kill_all()
        self.assertTrue(supervise.closed())
        with (
            mock.patch.object(subprocess, "Popen") as popen,
            self.assertRaises(supervise.ClosedError),
        ):
            supervise.run([sys.executable, "-c", "pass"], input="", timeout=5)
        popen.assert_not_called()
        self.assertIsInstance(supervise.ClosedError(), OSError)

    def test_a_shutdown_that_meets_a_spawn_in_progress_waits_for_it_and_kills_it(self) -> None:
        """The interleaving the review measured: spawned, not yet registered, then shutdown."""
        spawned, go = threading.Event(), threading.Event()
        real = subprocess.Popen
        results: list[Any] = []

        def slow_popen(*args: Any, **kwargs: Any) -> Any:
            process = real(*args, **kwargs)
            spawned.set()
            go.wait(10)
            return process

        def call() -> None:
            results.append(
                supervise.run(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    input="",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                )
            )

        with mock.patch.object(subprocess, "Popen", slow_popen):
            worker = threading.Thread(target=call, daemon=True)
            worker.start()
            self.assertTrue(spawned.wait(10))
            shutdown = threading.Thread(target=supervise.kill_all, daemon=True)
            shutdown.start()
            shutdown.join(0.3)
            self.assertTrue(shutdown.is_alive(), "shutdown snapshotted before the spawn registered")
            go.set()
            shutdown.join(10)
            worker.join(15)
        self.assertFalse(worker.is_alive(), "the child spawned during shutdown outlived it")
        self.assertNotEqual(0, results[0].returncode)

    # Correction round (review F7): never a bare group signal after the leader is reaped.

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_the_group_is_only_ever_signalled_while_its_leader_is_unreaped(self) -> None:
        groups: list[supervise.Group] = []
        reaped_at_kill: list[bool] = []
        real_killpg = os.killpg

        def killpg(pgid: int, sig: int) -> None:
            reaped_at_kill.append(groups[0]._process.returncode is not None)
            real_killpg(pgid, sig)

        for script, timeout in (("pass", 30.0), ("import time; time.sleep(60)", 1.0)):
            with self.subTest(script=script):
                groups.clear()
                reaped_at_kill.clear()
                with (
                    mock.patch.object(os, "killpg", killpg),
                    contextlib.suppress(subprocess.TimeoutExpired),
                ):
                    supervise.run(
                        [sys.executable, "-c", script],
                        input="",
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=timeout,
                        on_spawn=groups.append,
                    )
                self.assertTrue(reaped_at_kill, "no sweep ran, so this proved nothing")
                self.assertEqual([False] * len(reaped_at_kill), reaped_at_kill)
                self.assertIsNotNone(groups[0]._process.returncode)

    @unittest.skipIf(sys.platform == "win32", "reaping is a POSIX hazard")
    def test_asking_whether_a_group_runs_does_not_reap_its_leader(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        self.addCleanup(process.wait)
        group = supervise.Group(process)
        self.assertTrue(_wait_until(lambda: not group.running()))
        self.assertIsNone(process.returncode, "running() reaped the leader")

    # Correction round (codex F6): a kill that fails must not hang the call.

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_a_kill_that_fails_is_bounded_and_reported_rather_than_waited_on(self) -> None:
        groups: list[supervise.Group] = []
        started = time.monotonic()
        with (
            mock.patch.object(os, "killpg", side_effect=PermissionError(1, "denied")),
            mock.patch.object(supervise, "REAP_TIMEOUT_SEC", 1.0),
            self.assertRaises(supervise.UnstoppedError),
        ):
            supervise.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1,
                on_spawn=groups.append,
            )
        self.assertLess(time.monotonic() - started, 15)
        process = groups[0]._process
        process.kill()
        process.wait()
        self.assertTrue(issubclass(supervise.UnstoppedError, subprocess.SubprocessError))

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_a_group_already_gone_is_told_apart_from_a_failed_kill(self) -> None:
        with mock.patch.object(os, "killpg", side_effect=ProcessLookupError()):
            self.assertTrue(supervise.kill_group(99_999))
        with mock.patch.object(os, "killpg", side_effect=PermissionError()):
            self.assertFalse(supervise.kill_group(99_999))

    # Correction round (review F6): the limit of a process group, documented.

    @unittest.skipIf(sys.platform == "win32", "a Job Object has no such exit")
    def test_a_helper_that_leaves_the_group_is_not_reached(self) -> None:
        """The documented limit: SECURITY.md and COMPATIBILITY.md name it.

        A helper that calls `setsid` leads a session of its own, so the kill
        that ends the CLI's group cannot reach it. If this ever fails, the
        runner contains more than the docs say, and they can be widened.
        """
        pid_file = self.home / "escaped.pid"
        escapes = (
            "import os, subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],"
            " start_new_session=True)\n"
            "open(sys.argv[1], 'w').write(str(child.pid))\n"
            "time.sleep(60)\n"
        )
        with self.assertRaises(subprocess.TimeoutExpired):
            supervise.run(
                [sys.executable, "-c", escapes, str(pid_file)],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
        escaped = self._grandchild(pid_file)
        try:
            self.assertTrue(process_alive(escaped))
        finally:
            with contextlib.suppress(OSError):
                os.kill(escaped, signal.SIGKILL)

    # Final round (verify N2): an exit that cannot be observed is never read as one.

    @unittest.skipUnless(hasattr(select, "kqueue") and not hasattr(os, "waitid"), "kqueue path")
    def test_a_kqueue_error_other_than_esrch_is_unknown_not_an_exit(self) -> None:
        class _Queue:
            def __init__(self, data: int) -> None:
                self.data = data

            def control(self, *_a: Any) -> list[Any]:
                return [mock.Mock(flags=select.KQ_EV_ERROR, data=self.data)]

            def close(self) -> None:
                pass

        for data, expected in ((errno.EPERM, "unknown"), (errno.ESRCH, "exited")):
            with (
                self.subTest(errno=data),
                mock.patch.object(select, "kqueue", lambda d=data: _Queue(d)),
            ):
                self.assertEqual(expected, supervise._state(os.getpid(), 0.0))

    @unittest.skipIf(sys.platform == "win32", "process groups are POSIX")
    def test_a_child_whose_exit_cannot_be_watched_is_never_killed_early(self) -> None:
        killed: list[int] = []
        real_killpg = os.killpg

        def killpg(pgid: int, sig: int) -> None:
            killed.append(pgid)
            real_killpg(pgid, sig)

        with (
            mock.patch.object(supervise, "_state", return_value="unknown"),
            mock.patch.object(os, "killpg", killpg),
        ):
            result = supervise.run(
                [sys.executable, "-c", "import time; time.sleep(0.3)"],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            self.assertEqual(0, result.returncode, "a running child was killed as if it had exited")
            self.assertEqual([], killed)
            with self.assertRaises(subprocess.TimeoutExpired):
                supervise.run(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    input="",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1,
                )
        self.assertEqual(1, len(killed), "the timeout no longer killed the group")


# A process that runs one supervised CLI and cancels it the way the reading
# route does, then reports on itself. "daemon" calls `setsid` first, as
# `--daemon` does; "foreground" keeps a sentinel sibling in its own group, as
# a terminal's job would hold one.
_CANCELS_ITS_CLI = (
    "import json, os, subprocess, sys, threading, time\n"
    "sys.path.insert(0, sys.argv[3])\n"
    "from compass_runtime import supervise\n"
    "mode, pid_file = sys.argv[1], sys.argv[2]\n"
    "sentinel = None\n"
    "if mode == 'daemon':\n"
    "    os.setsid()\n"
    "else:\n"
    "    sentinel = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "groups, spawned = [], threading.Event()\n"
    "def call():\n"
    "    supervise.run([sys.executable, '-c', sys.argv[4], pid_file], input='',\n"
    "        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,\n"
    "        on_spawn=lambda g: (groups.append(g), spawned.set()))\n"
    "worker = threading.Thread(target=call, daemon=True)\n"
    "worker.start()\n"
    "spawned.wait(10)\n"
    "deadline = time.monotonic() + 10\n"
    "while time.monotonic() < deadline and not os.path.exists(pid_file):\n"
    "    time.sleep(0.02)\n"
    "groups[0].cancel()\n"
    "worker.join(15)\n"
    "report = {'cli_done': not worker.is_alive(), 'cli': groups[0].pid,\n"
    "    'sentinel': sentinel is not None and sentinel.poll() is None}\n"
    "if sentinel is not None:\n"
    "    sentinel.kill()\n"
    "    sentinel.wait()\n"
    "print(json.dumps(report))\n"
)


class CancelKillsTheCliAndNothingElseTest(unittest.TestCase):
    """DRC-4693: Cancel ends the CLI's group or Job Object, and never the caller's."""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, True))
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _running(self) -> tuple[list[supervise.Group], list[Any], threading.Thread, Path]:
        pid_file = self.home / "grandchild.pid"
        groups: list[supervise.Group] = []
        outcome: list[Any] = []

        def call() -> None:
            try:
                outcome.append(
                    supervise.run(
                        [sys.executable, "-c", _SPAWNS_A_GRANDCHILD, str(pid_file)],
                        input="",
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=60,
                        on_spawn=groups.append,
                    )
                )
            except supervise.UnstoppedError as exc:
                outcome.append(exc)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        self.assertTrue(_wait_until(lambda: pid_file.exists() and pid_file.read_text().strip()))
        return groups, outcome, worker, pid_file

    def test_a_cancel_ends_the_cli_and_its_grandchild_well_inside_the_call_timeout(self) -> None:
        """On Windows this is the Job Object's `TerminateJobObject`, run by platform-tests."""
        groups, outcome, worker, pid_file = self._running()
        grandchild = int(pid_file.read_text())
        started = time.monotonic()
        groups[0].cancel()
        worker.join(15)
        self.assertFalse(worker.is_alive(), "a cancelled CLI left its caller waiting")
        self.assertLess(time.monotonic() - started, 10)
        self.assertNotEqual(0, outcome[0].returncode)
        self.assertTrue(groups[0].cancelled())
        self.assertTrue(_wait_until(lambda: not process_alive(grandchild)))
        self.assertEqual(frozenset(), supervise.live())

    def test_a_cancel_whose_kill_fails_is_reported_unstopped_within_the_bound(self) -> None:
        with (
            mock.patch.object(supervise.Group, "_kill", return_value=False),
            mock.patch.object(supervise, "REAP_TIMEOUT_SEC", 0.5),
        ):
            groups, outcome, worker, pid_file = self._running()
            started = time.monotonic()
            groups[0].cancel()
            worker.join(15)
        self.assertLess(time.monotonic() - started, 10, "Cancel waited out the call timeout")
        self.assertIsInstance(outcome[0], supervise.UnstoppedError)
        # Clean up what the patched kill left running.
        with contextlib.suppress(OSError):
            os.kill(int(pid_file.read_text()), signal.SIGTERM)
        with contextlib.suppress(OSError):
            groups[0]._process.kill()
            groups[0]._process.wait(5)

    def test_a_cancel_after_the_reap_signals_nothing(self) -> None:
        groups: list[supervise.Group] = []
        supervise.run(
            [sys.executable, "-c", "pass"],
            input="",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            on_spawn=groups.append,
        )
        with mock.patch.object(supervise.Group, "_kill") as kill:
            groups[0].cancel()
        kill.assert_not_called()

    # Correction round (S6 review).

    def test_a_cancel_never_holds_the_request_thread_on_the_group_lock(self) -> None:
        groups, _outcome, worker, _pid = self._running()
        group = groups[0]
        group._lock.acquire()
        try:
            done = threading.Event()

            def cancel() -> None:
                group.cancel()
                done.set()

            threading.Thread(target=cancel, daemon=True).start()
            self.assertTrue(done.wait(1.0), "Cancel blocked its caller on the group lock")
        finally:
            group._lock.release()
        worker.join(15)
        self.assertFalse(worker.is_alive())

    def test_a_cancel_kills_on_the_callers_thread_when_the_lock_is_free(self) -> None:
        groups, _outcome, worker, _pid = self._running()
        seen: list[Any] = []
        real = supervise.Group._kill

        def kill(group: supervise.Group) -> bool:
            seen.append(threading.current_thread())
            return real(group)

        with mock.patch.object(supervise.Group, "_kill", kill):
            groups[0].cancel()
            self.assertIn(threading.current_thread(), seen)
            worker.join(15)
        self.assertFalse(worker.is_alive())

    def test_a_cancel_of_an_unwatchable_exit_ends_the_call_without_a_timeout(self) -> None:
        """Cancel's kill misses; the call's own reap must still end it, and return."""
        real = supervise.Group._kill
        canceller = threading.current_thread()

        # Only Cancel's own kill misses. "The first call misses" was a race:
        # `cancel` sets its flag before it tries the lock, so a call thread that
        # wakes in that gap kills first, takes the miss, and leaves the group
        # running out the reap (DRC-4743, reproduced every time by holding
        # `cancel` 0.2 s between the two). The CLI was never killed at all.
        def kill(group: supervise.Group) -> bool:
            return False if threading.current_thread() is canceller else real(group)

        with (
            mock.patch.object(supervise, "_state", return_value=supervise._UNKNOWN),
            mock.patch.object(supervise.Group, "_kill", kill),
        ):
            groups, outcome, worker, _pid = self._running()
            started = time.monotonic()
            groups[0].cancel()
            worker.join(15)
        self.assertFalse(worker.is_alive(), "the cancelled call waited for its own timeout")
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(1, len(outcome))
        self.assertNotIsInstance(outcome[0], BaseException)

    def test_a_windows_cancel_whose_reap_outlasts_the_call_timeout_does_not_spin(self) -> None:
        """Review P2: once cancelled, the wait keeps its poll step whatever the deadline says.

        A fake process, because `_wait_windows` runs only on Windows: its
        `wait` never finishes, and the kill never lands.
        """

        class _Process:
            pid, args = 4242, ["cli"]

            def __init__(self) -> None:
                self.calls = 0

            def wait(self, timeout: float | None = None) -> None:
                self.calls += 1
                if timeout:
                    time.sleep(timeout)
                raise subprocess.TimeoutExpired("cli", timeout or 0.0)

        process = _Process()
        group = supervise.Group(process)  # type: ignore[arg-type]
        with (
            mock.patch.object(supervise.Group, "_kill", return_value=False),
            mock.patch.object(supervise, "REAP_TIMEOUT_SEC", 0.5),
        ):
            group.cancel()
            with self.assertRaises(supervise.UnstoppedError):
                supervise._wait_windows(group, 0.05)
        # About 0.5 s at 0.1 s a step, plus the call's own 0.05 s: a handful.
        self.assertLess(process.calls, 50, "the reap window spun on a zero timeout")

    def _harness(self, mode: str) -> dict[str, Any]:
        root = str(Path(supervise.__file__).resolve().parent.parent)
        # The foreground harness leads a group of its own, so a wrong kill lands
        # on it and its sentinel rather than on this test runner. The daemon
        # one must not lead a group yet: `setsid` refuses a group leader.
        options: dict[str, Any] = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined,unused-ignore]
            if sys.platform == "win32"
            else {"start_new_session": mode != "daemon"}
        )
        done = subprocess.run(
            [
                sys.executable,
                "-c",
                _CANCELS_ITS_CLI,
                mode,
                str(self.home / f"{mode}.pid"),
                root,
                _SPAWNS_A_GRANDCHILD,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            **options,
        )
        self.assertEqual(0, done.returncode, f"the process that cancelled died: {done.stderr}")
        report: dict[str, Any] = __import__("json").loads(done.stdout)
        return report

    @unittest.skipIf(sys.platform == "win32", "`--daemon` calls setsid, which is POSIX only")
    def test_a_cancel_under_a_daemon_leaves_the_daemon_running(self) -> None:
        report = self._harness("daemon")
        self.assertTrue(report["cli_done"])
        self.assertFalse(process_alive(report["cli"]))

    def test_a_cancel_in_a_foreground_run_leaves_the_launching_group_alone(self) -> None:
        report = self._harness("foreground")
        self.assertTrue(report["cli_done"])
        self.assertTrue(report["sentinel"], "a sibling in the launching group was killed")


# A CLI that starts a grandchild, writes its pid to argv[1], then floods its
# stdout 1 MiB at a time. The pause between chunks keeps one 0.1 s slice to a
# few MiB, so "killed near the bound" is a measurement and not disk speed.
_FLOODS_ITS_OUTPUT = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "with open(sys.argv[1], 'w') as out:\n"
    "    out.write(str(child.pid))\n"
    "chunk = b'x' * (1 << 20)\n"
    "for _ in range(50):\n"
    "    sys.stdout.buffer.write(chunk)\n"
    "    sys.stdout.flush()\n"
    "    time.sleep(0.02)\n"
    "time.sleep(60)\n"
)


# The same, without the pause: it writes as fast as the disk takes it, and
# stamps the wall clock just before the write that crosses 1 MiB, so a test
# measures the time to the kill rather than a size that depends on the disk.
# Capped at 400 MiB so a runner that never stops it cannot fill the disk.
_FLOODS_UNTHROTTLED = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "with open(sys.argv[1], 'w') as out:\n"
    "    out.write(str(child.pid))\n"
    "sys.stdout.buffer.write(b'x' * ((1 << 20) - 1))\n"
    "sys.stdout.flush()\n"
    "with open(sys.argv[2], 'w') as out:\n"
    "    out.write(repr(time.time()))\n"
    "chunk = b'x' * (1 << 20)\n"
    "for _ in range(400):\n"
    "    sys.stdout.buffer.write(chunk)\n"
    "    sys.stdout.flush()\n"
    "time.sleep(60)\n"
)
# Writes 2 MiB in one burst and exits at once: over the bound, inside a slice.
_BURSTS_AND_EXITS = "import sys; sys.stdout.buffer.write(b'x' * (2 << 20)); sys.stdout.flush()"


class _FakeWindowsProcess:
    """A Windows `Popen` that has already exited, or that runs until it is killed."""

    pid, args, stdin = 4244, ["cli"], None

    def __init__(self, *, exits: bool) -> None:
        self.returncode: int | None = 0 if exits else None
        self.killed = False

    def kill(self, _group: Any = None) -> bool:
        self.killed = True
        self.returncode = 1
        return True

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is not None:
            return self.returncode
        time.sleep(timeout or 0.0)
        raise subprocess.TimeoutExpired("cli", timeout or 0.0)


class AnOutputFileHasABoundTest(unittest.TestCase):
    """DRC-4667: a CLI that writes far past what a call can use is stopped near the bound."""

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, True))
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_stderr_is_bounded_independently_after_an_immediate_exit(self) -> None:
        out, error = self.home / "reply.txt", self.home / "error.txt"
        with (
            out.open("wb") as stdout,
            error.open("wb") as stderr,
            self.assertRaises(supervise.OversizedError),
        ):
            supervise.run(
                [sys.executable, "-c", "import os; os.write(2, bytes([120]) * 8192)"],
                stdout=stdout,
                stderr=stderr,
                timeout=3,
                output_limit=(str(out), 1 << 20),
                output_limits=((str(error), 4096),),
            )
        self.assertEqual(0, out.stat().st_size)
        self.assertGreater(error.stat().st_size, 4096)

    def test_extra_limit_preserves_the_original_stdout_bound(self) -> None:
        out, error = self.home / "reply.txt", self.home / "error.txt"
        with (
            out.open("wb") as stdout,
            error.open("wb") as stderr,
            self.assertRaises(supervise.OversizedError),
        ):
            supervise.run(
                [sys.executable, "-c", "import os; os.write(1, bytes([120]) * 8192)"],
                stdout=stdout,
                stderr=stderr,
                timeout=3,
                output_limit=(str(out), 4096),
                output_limits=((str(error), 1 << 20),),
            )
        self.assertGreater(out.stat().st_size, 4096)
        self.assertEqual(0, error.stat().st_size)

    def test_a_cli_that_floods_its_output_file_is_killed_soon_after_the_bound(self) -> None:
        """Time to the kill, not size: an unpaused writer's overshoot is the disk's speed."""
        out, pid_file = self.home / "reply.txt", self.home / "helper.pid"
        crossed = self.home / "crossed"
        limit = 1 << 20
        with out.open("wb") as handle, self.assertRaises(supervise.OversizedError):
            supervise.run(
                [sys.executable, "-c", _FLOODS_UNTHROTTLED, str(pid_file), str(crossed)],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                timeout=60,
                output_limit=(str(out), limit),
            )
        # Includes the kill and the reap; generous for a loaded runner, and
        # far inside the 60 s timeout the call would otherwise run to.
        self.assertLess(time.time() - float(crossed.read_text()), 20.0)
        self.assertGreater(out.stat().st_size, limit)
        helper = int(pid_file.read_text())
        self.assertTrue(_wait_until(lambda: not process_alive(helper)), "its helper outlived it")

    @unittest.skipIf(sys.platform == "win32", "`_state` is the POSIX wait; Windows has its own")
    def test_a_limit_shortens_the_wait_slice(self) -> None:
        """F1: while a bound is set the size is looked at every 0.01 s, not every 0.1 s."""
        steps: list[float] = []
        real = supervise._state

        def state(pid: int, timeout: float) -> str:
            steps.append(timeout)
            return real(pid, timeout)

        out = self.home / "reply.txt"
        with mock.patch.object(supervise, "_state", state), out.open("wb") as handle:
            supervise.run(
                [sys.executable, "-c", "import time; time.sleep(0.3)"],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                timeout=30,
                output_limit=(str(out), 1 << 20),
            )
        waits = [step for step in steps if step > 0]
        self.assertTrue(waits)
        self.assertLessEqual(max(waits), 0.01)

    def test_a_limit_shortens_the_windows_wait_slice(self) -> None:
        """F1 on Windows: `_wait_windows` waits in 0.01 s steps while a bound is set.

        A fake process, so it runs on every OS: the test above patches `_state`,
        which only the POSIX wait calls, and it measured nothing on Windows.
        """
        steps: list[float] = []

        class _Process(_FakeWindowsProcess):
            def wait(self, timeout: float | None = None) -> int:
                steps.append(timeout or 0.0)
                if len(steps) >= 20:
                    self.returncode = 0
                return super().wait(timeout)

        out = self.home / "reply.txt"
        out.write_bytes(b"")
        for limit, most in (((str(out), 1 << 20), 0.01), (None, supervise._CANCEL_POLL_SEC)):
            with self.subTest(limit=limit):
                steps.clear()
                group = supervise.Group(_Process(exits=False))  # type: ignore[arg-type]
                group._limit = limit
                supervise._wait_windows(group, 30)
                self.assertEqual(20, len(steps))
                self.assertEqual(most, max(steps))

    def test_a_cli_that_writes_past_the_bound_and_exits_at_once_is_oversized(self) -> None:
        """Codex P2: the exit inside a slice once hid the size, and it read as a reply."""
        out = self.home / "reply.txt"
        with out.open("wb") as handle, self.assertRaises(supervise.OversizedError):
            supervise.run(
                [sys.executable, "-c", _BURSTS_AND_EXITS],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                timeout=30,
                output_limit=(str(out), 1 << 20),
            )

    @unittest.skipIf(sys.platform == "win32", "the Job Object has its own completion test")
    def test_a_helpers_last_write_is_checked_after_the_whole_group_stops(self) -> None:
        out = self.home / "reply.txt"
        pid_file, ready, release = (self.home / name for name in ("helper.pid", "ready", "release"))
        helper = (
            "import pathlib, sys, time\n"
            "ready, release = map(pathlib.Path, sys.argv[1:])\n"
            "ready.touch()\n"
            "deadline = time.monotonic() + 10\n"
            "while not release.exists() and time.monotonic() < deadline: time.sleep(0.005)\n"
            "if not release.exists(): sys.exit(1)\n"
            "sys.stdout.buffer.write(bytes(2 << 20)); sys.stdout.flush()\n"
        )
        leader = (
            "import pathlib, subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', sys.argv[4], sys.argv[2], sys.argv[3]])\n"
            "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
            "while not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.005)\n"
        )
        real_probe = getattr(supervise, "_group_running", None)
        probes: list[int] = []
        groups: list[supervise.Group] = []
        finished = False

        def probe(pgid: int, timeout: float) -> bool | None:
            # The helper's last write is held until quiescence is actually
            # observed, so a leader-only wait always sees an empty file.
            deadline = time.monotonic() + timeout
            release.touch()
            probes.append(pgid)
            assert real_probe is not None
            helper_pid = int(pid_file.read_text())
            # macOS can show this exiting helper as `?E`. The controlled
            # fixture waits for its exit; production still refuses that state.
            self.assertTrue(
                _wait_until(
                    lambda: not process_alive(helper_pid),
                    timeout=max(0.0, deadline - time.monotonic()),
                ),
                "the controlled helper did not finish its last write and exit",
            )
            self.assertEqual(2 << 20, out.stat().st_size)
            return cast("bool | None", real_probe(pgid, max(0.0, deadline - time.monotonic())))

        try:
            with (
                mock.patch.object(supervise, "kill_group", return_value=True),
                mock.patch.object(supervise, "_group_running", probe, create=True),
                out.open("wb") as handle,
                self.assertRaises(supervise.OversizedError),
            ):
                supervise.run(
                    [sys.executable, "-c", leader, str(pid_file), str(ready), str(release), helper],
                    stdout=handle,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                    output_limit=(str(out), 1 << 20),
                    on_spawn=groups.append,
                )
            finished = True
            self.assertTrue(probes)
            self.assertEqual(2 << 20, out.stat().st_size)
        finally:
            if not finished and groups and pid_file.exists():
                with contextlib.suppress(OSError):
                    pid = int(pid_file.read_text())
                    if os.getpgid(pid) == groups[0].pid:
                        os.kill(pid, signal.SIGKILL)

    def test_a_windows_helpers_last_write_is_checked_after_the_job_stops(self) -> None:
        out = self.home / "reply.txt"
        out.write_bytes(b"")
        process = _FakeWindowsProcess(exits=True)
        group = supervise.Group(process, job=7)  # type: ignore[arg-type]
        states = iter((1, 0))

        def active(_job: int) -> int:
            count = next(states)
            if count == 0:
                out.write_bytes(bytes(2 << 20))
            return count

        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(supervise._windows, "terminate", return_value=True),
            mock.patch.object(supervise._windows, "active", active, create=True),
            mock.patch.object(supervise._windows, "close"),
            mock.patch.object(supervise, "_spawn", return_value=group),
            self.assertRaises(supervise.OversizedError),
        ):
            supervise.run(["cli"], stdout=subprocess.DEVNULL, output_limit=(str(out), 1 << 20))

    @unittest.skipIf(sys.platform == "win32", "a Job Object has no unwatchable exit")
    def test_the_poll_fallback_still_reports_a_burst_that_exits_at_once(self) -> None:
        """Codex P1, the part the poll can reach: the final size is still read."""
        out = self.home / "reply.txt"
        with (
            mock.patch.object(supervise, "_state", return_value="unknown"),
            out.open("wb") as handle,
            self.assertRaises(supervise.OversizedError),
        ):
            supervise.run(
                [sys.executable, "-c", _BURSTS_AND_EXITS],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                timeout=30,
                output_limit=(str(out), 1 << 20),
            )

    @unittest.skipIf(sys.platform == "win32", "a Job Object has no unwatchable exit")
    def test_the_poll_fallback_also_stops_a_flood(self) -> None:
        """Review T3: the bound holds, and the group dies, where the exit cannot be watched."""
        out, pid_file = self.home / "reply.txt", self.home / "helper.pid"
        started = time.monotonic()
        with (
            mock.patch.object(supervise, "_state", return_value="unknown"),
            out.open("wb") as handle,
            self.assertRaises(supervise.OversizedError),
        ):
            supervise.run(
                [sys.executable, "-c", _FLOODS_ITS_OUTPUT, str(pid_file)],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                timeout=20,
                output_limit=(str(out), 1 << 20),
            )
        self.assertLess(time.monotonic() - started, 15)
        helper = int(pid_file.read_text())
        self.assertTrue(_wait_until(lambda: not process_alive(helper)), "its helper outlived it")

    def test_the_windows_wait_stops_a_flood(self) -> None:
        """Review T3: a fake process, because `_wait_windows` runs only on Windows."""
        out = self.home / "reply.txt"
        out.write_bytes(b"x" * (2 << 20))
        process = _FakeWindowsProcess(exits=False)
        group = supervise.Group(process)  # type: ignore[arg-type]
        group._limit = (str(out), 1 << 20)
        with mock.patch.object(supervise.Group, "_kill", process.kill):
            supervise._wait_windows(group, 3)
        self.assertTrue(group._oversized)
        self.assertTrue(process.killed)

    def test_a_windows_cli_that_writes_past_the_bound_and_exits_is_oversized(self) -> None:
        """Codex P2 on Windows: the final size is read while the Job Object can still be ended."""
        out = self.home / "reply.txt"
        out.write_bytes(b"x" * (2 << 20))
        process = _FakeWindowsProcess(exits=True)
        group = supervise.Group(process, job=7)  # type: ignore[arg-type]
        terminated: list[int] = []

        def terminate(job: int) -> bool:
            terminated.append(job)
            return True

        with (
            mock.patch.object(sys, "platform", "win32"),
            mock.patch.object(supervise._windows, "terminate", terminate),
            mock.patch.object(supervise._windows, "active", return_value=0),
            mock.patch.object(supervise._windows, "close", lambda _job: None),
            mock.patch.object(supervise, "_spawn", lambda *_a, **_k: group),
            self.assertRaises(supervise.OversizedError),
        ):
            supervise.run(["cli"], input=None, timeout=3, output_limit=(str(out), 1 << 20))
        self.assertEqual([7], terminated, "the Job Object was not ended before it closed")

    def test_a_reply_inside_the_bound_is_returned_as_usual(self) -> None:
        out = self.home / "reply.txt"
        with out.open("wb") as handle:
            result = supervise.run(
                [sys.executable, "-c", "import sys; sys.stdout.write('x' * 4096)"],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                timeout=30,
                output_limit=(str(out), 1 << 20),
            )
        self.assertEqual(0, result.returncode)
        self.assertEqual(4096, out.stat().st_size)

    def test_an_unconfirmed_kill_outranks_the_oversized_answer(self) -> None:
        out, pid_file = self.home / "reply.txt", self.home / "helper.pid"
        groups: list[supervise.Group] = []
        try:
            with (
                mock.patch.object(supervise.Group, "_kill", return_value=False),
                mock.patch.object(supervise, "REAP_TIMEOUT_SEC", 0.5),
                out.open("wb") as handle,
                self.assertRaises(supervise.UnstoppedError),
            ):
                supervise.run(
                    [sys.executable, "-c", _FLOODS_ITS_OUTPUT, str(pid_file)],
                    input="",
                    stdout=handle,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    on_spawn=groups.append,
                    output_limit=(str(out), 1 << 20),
                )
        finally:
            # The kill was faked as failing, so the CLI and its helper still
            # run; on Windows closing the job ended them already.
            if groups and sys.platform != "win32":
                supervise.kill_group(groups[0].pid)
                groups[0]._process.wait(10)


class TheReservationAndTheShutdownShareALockTest(unittest.TestCase):
    """DRC-4712: `admitting` holds the lock `kill_all` takes, so the two are ordered."""

    def setUp(self) -> None:
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_shutdown_waits_for_an_admission_in_progress(self) -> None:
        with supervise.admitting() as open_:
            self.assertTrue(open_)
            stopper = threading.Thread(target=supervise.kill_all, daemon=True)
            stopper.start()
            stopper.join(0.3)
            self.assertTrue(stopper.is_alive(), "the shutdown did not wait for the admission")
            self.assertFalse(supervise.closed())
        stopper.join(5)
        self.assertFalse(stopper.is_alive())
        with supervise.admitting() as open_:
            self.assertFalse(open_)


class _UnreadStdin:
    """A Windows pipe nobody reads: a write blocks until the test ends."""

    def __init__(self, drained: threading.Event) -> None:
        self._drained = drained

    def write(self, _data: Any) -> None:
        self._drained.wait(30)

    def close(self) -> None:
        pass


class _UnreadWindowsProcess:
    """A Windows `Popen` whose CLI never reads stdin and exits only when killed.

    `communicate` writes on the calling thread first, as CPython's does there.
    """

    pid, args = 4242, ["cli"]

    def __init__(self, drained: threading.Event) -> None:
        self.stdin: Any = _UnreadStdin(drained)
        self.returncode: int | None = None
        self.killed = False

    def communicate(self, data: Any = None, timeout: float | None = None) -> None:
        if data is not None and self.stdin is not None:
            self.stdin.write(data)
        self.wait(timeout)

    def wait(self, timeout: float | None = None) -> int:
        if self.killed:
            self.returncode = 1
            return 1
        time.sleep(timeout or 0.0)
        raise subprocess.TimeoutExpired("cli", timeout or 0.0)


class AWindowsPromptNobodyReadsTest(unittest.TestCase):
    """DRC-4713: a CLI that never reads stdin still meets the call's deadline.

    CPython's Windows `communicate` writes stdin in the calling thread before
    any timed wait, so a prompt larger than the pipe held the call past its
    timeout for as long as the CLI ran.
    """

    def setUp(self) -> None:
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_call_whose_cli_never_reads_stdin_still_times_out(self) -> None:
        """A real child, on every platform; the Windows CI job is the one this guards."""
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            supervise.run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                input="x" * (1 << 20),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                timeout=1,
            )
        self.assertLess(time.monotonic() - started, 1 + supervise.REAP_TIMEOUT_SEC + 3)

    def test_the_windows_wait_never_writes_the_prompt_on_its_own_thread(self) -> None:
        """A fake process, because `_run_windows` runs only on Windows: its stdin never drains."""
        drained = threading.Event()
        self.addCleanup(drained.set)
        process = _UnreadWindowsProcess(drained)
        group = supervise.Group(process)  # type: ignore[arg-type]
        outcome: list[BaseException] = []

        def kill(_group: Any) -> bool:
            process.killed = True
            return True

        def call() -> None:
            try:
                supervise._run_windows(group, "prompt", 0.5, None)
            except BaseException as exc:  # noqa: BLE001 (reported to the test thread)
                outcome.append(exc)

        with mock.patch.object(supervise.Group, "_kill", kill):
            worker = threading.Thread(target=call, daemon=True)
            worker.start()
            worker.join(10)
        self.assertFalse(worker.is_alive(), "the call waited on a prompt nobody read")
        self.assertEqual(1, len(outcome))
        self.assertIsInstance(outcome[0], subprocess.TimeoutExpired)


class TheWindowsPromptIsStillSentTest(unittest.TestCase):
    """Review T4: feeding from a thread must still deliver the prompt, whole."""

    def test_the_windows_runner_still_sends_the_prompt(self) -> None:
        written: list[Any] = []
        done = threading.Event()

        class _Stdin:
            def write(self, data: Any) -> None:
                written.append(data)

            def close(self) -> None:
                done.set()

        class _Process:
            pid, args = 4243, ["cli"]

            def __init__(self) -> None:
                self.stdin: Any = _Stdin()
                self.returncode: int | None = None

            def wait(self, timeout: float | None = None) -> int:
                if done.wait(timeout or 0.0):
                    self.returncode = 0
                    return 0
                raise subprocess.TimeoutExpired("cli", timeout or 0.0)

        group = supervise.Group(_Process())  # type: ignore[arg-type]
        with mock.patch.object(supervise.Group, "_kill", lambda _g: True):
            self.assertEqual(0, supervise._run_windows(group, "prompt", 5, None))
        self.assertEqual(["prompt"], written)


class ThePollFallbackLimitIsDocumentedTest(unittest.TestCase):
    """DRC-4712 L4, pinned rather than fixed (owner, 2026-09-27).

    When neither `waitid` nor kqueue can watch the exit, the call polls, and the
    poll reaps the leader, so helpers still in its group after a NORMAL exit are
    not swept. COMPATIBILITY.md and SECURITY.md say so. A timeout still kills the
    group, because that kill comes before the reap. If this starts sweeping,
    change the two documents with it.
    """

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.home, True))
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipIf(sys.platform == "win32", "a Job Object has no unwatchable exit")
    def test_a_helper_left_after_a_normal_exit_survives_the_poll_fallback(self) -> None:
        pid_file = self.home / "helper.pid"
        leaves_a_helper = (
            "import subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            "open(sys.argv[1], 'w').write(str(child.pid))\n"
        )
        with mock.patch.object(supervise, "_state", return_value="unknown"):
            supervise.run(
                [sys.executable, "-c", leaves_a_helper, str(pid_file)],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        helper = int(pid_file.read_text())
        try:
            self.assertTrue(process_alive(helper), "the poll fallback now sweeps: update the docs")
        finally:
            with contextlib.suppress(OSError):
                os.kill(helper, signal.SIGKILL)

    @unittest.skipIf(sys.platform == "win32", "a Job Object has no unwatchable exit")
    def test_a_helper_that_writes_after_the_leader_exits_is_not_bounded_here(self) -> None:
        """Codex P1, pinned: the poll that sees the exit is the reap, so nothing is swept.

        SECURITY.md states what that costs: such a helper writes to the removed
        file, bounded by nothing but the disk, until it exits.
        """
        pid_file, out = self.home / "helper.pid", self.home / "reply.txt"
        leaves_a_writer = (
            "import subprocess, sys\n"
            "child = subprocess.Popen([sys.executable, '-c',\n"
            "    'import sys, time\\nwhile True:\\n    time.sleep(0.05)\\n'\n"
            "    '    sys.stdout.buffer.write(bytes(65536)); sys.stdout.flush()\\n'])\n"
            "open(sys.argv[1], 'w').write(str(child.pid))\n"
        )
        with (
            mock.patch.object(supervise, "_state", return_value="unknown"),
            out.open("wb") as handle,
        ):
            supervise.run(
                [sys.executable, "-c", leaves_a_writer, str(pid_file)],
                input="",
                stdout=handle,
                stderr=subprocess.DEVNULL,
                timeout=30,
                output_limit=(str(out), 1 << 20),
            )
        helper = int(pid_file.read_text())
        try:
            self.assertTrue(process_alive(helper), "the poll fallback now sweeps: update the docs")
        finally:
            with contextlib.suppress(OSError):
                os.kill(helper, signal.SIGKILL)

    def test_the_limit_is_stated_where_the_runner_is_documented(self) -> None:
        root = Path(supervise.__file__).resolve().parents[4]
        for name in ("COMPATIBILITY.md", "SECURITY.md"):
            with self.subTest(document=name):
                text = " ".join((root / name).read_text(encoding="utf-8").split())
                phrase = "helpers still in its group after a normal exit are not swept"
                self.assertTrue(phrase in text, f"{name} does not state the poll-fallback limit")

    def test_the_cost_of_a_helper_still_writing_is_stated(self) -> None:
        """The pin above's cost: a helper already writing, or starting to, is not reached."""
        root = Path(supervise.__file__).resolve().parents[4]
        documents = ("COMPATIBILITY.md", "SECURITY.md", "docs/design-reading-a-session.md")
        for name in documents:
            with self.subTest(document=name):
                text = " ".join((root / name).read_text(encoding="utf-8").split())
                phrase = "a helper still writing after the leader's exit is not reached"
                self.assertTrue(phrase in text, f"{name} does not state the helper's cost")
        security = " ".join((root / "SECURITY.md").read_text(encoding="utf-8").split())
        self.assertTrue("bounded by nothing but the disk until the helper exits" in security)


if __name__ == "__main__":
    unittest.main()
