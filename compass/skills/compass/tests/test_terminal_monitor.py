"""The session's terminal holder: spend admission, ownership, and bounded lifetime."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import monitor_store
from compass_runtime import terminal_client as client
from compass_runtime import terminal_monitor as monitor


class MonitorCommandTest(unittest.TestCase):
    def test_a_person_without_a_session_starts_nothing_and_sends_nothing(self) -> None:
        with (
            mock.patch.object(client, "ensure_dashboard") as ensure,
            mock.patch.object(client, "post") as post,
            mock.patch.object(monitor, "spawn") as spawn,
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(1, client.run_monitor(environ={}))
        ensure.assert_not_called()
        post.assert_not_called()
        spawn.assert_not_called()

    def test_a_person_s_full_session_id_selects_only_the_matching_resume_id(self) -> None:
        row = {
            "harness": "claude",
            "sid": "abcdefab",
            "resume_id": "abcdefab-1111-4111-8111-111111111111",
        }
        self.assertEqual(
            row, monitor.select_row({"sessions": [row]}, "abcdefab-1111-4111-8111-111111111111")
        )
        self.assertIsNone(
            monitor.select_row({"sessions": [row]}, "abcdefab-2222-4222-8222-222222222222")
        )
        self.assertIsNone(
            monitor.select_row({"sessions": [row, row]}, "abcdefab-1111-4111-8111-111111111111")
        )

    def test_a_person_can_only_combine_monitor_with_off_and_session(self) -> None:
        self.assertEqual(
            (True, True, "claude:one"),
            client.parse_monitor_args(["--session=claude:one", "--monitor", "--off"]),
        )
        for argv in (["--off"], ["--monitor", "--daemon"], ["--monitor", "--off", "--off"]):
            self.assertFalse(client.parse_monitor_args(argv)[0])

    def test_a_person_in_another_harness_is_not_told_a_drift_action_ran(self) -> None:
        err = io.StringIO()
        with mock.patch("sys.stderr", err), mock.patch.object(monitor, "spawn") as spawn:
            self.assertEqual(
                1,
                client.run_monitor(
                    environ={"CODEX_THREAD_ID": "thread", "CLAUDE_CODE_SESSION_ID": "inherited"}
                ),
            )
        self.assertNotIn("drift", err.getvalue())
        spawn.assert_not_called()


class SidecarTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 0.0
        self.actions: list[str] = []
        self.dashboard = client.Dashboard(4553, 42, 100.0, "1.0.0")
        self.answer: Any = {"ok": True, "state": {"on": True}, "activity": 100}

    def wait(self, seconds: float) -> bool:
        self.now += seconds
        return False

    def post(self, _port: int, _path: str, payload: Any, **_kwargs: Any) -> client.Reply:
        self.actions.append(payload["action"])
        return client.Reply(200, self.answer)

    def run_loop(self, **kwargs: Any) -> str:
        return monitor.hold(
            self.dashboard,
            "one",
            "generation",
            clock=lambda: self.now,
            wait=self.wait,
            stopped=lambda: False,
            alive=lambda: True,
            post=self.post,
            probe=lambda *_a, **_k: self.dashboard,
            **kwargs,
        )

    def test_a_person_s_ended_lease_exits_within_one_lapse_and_never_restarts(self) -> None:
        self.answer = {
            "ok": False,
            "reason": "not-monitoring",
            "state": {"on": False, "last_end": {"reason": "left"}},
        }
        self.assertEqual("left", self.run_loop())
        self.assertLess(self.now, 50)
        self.assertEqual(["beat"], self.actions)

    def test_a_person_s_restarted_dashboard_ends_the_holder_without_replaying_start(self) -> None:
        self.dashboard = client.Dashboard(4553, 99, 200.0, "1.0.0")
        original = client.Dashboard(4553, 42, 100.0, "1.0.0")
        reason = monitor.hold(
            original,
            "one",
            "generation",
            clock=lambda: self.now,
            wait=self.wait,
            stopped=lambda: False,
            alive=lambda: True,
            post=self.post,
            probe=lambda *_a, **_k: self.dashboard,
        )
        self.assertEqual("restarted", reason)
        self.assertEqual([], self.actions)
        self.assertLess(self.now, 50)

    def test_a_person_s_dead_harness_ends_the_holder_within_one_lapse(self) -> None:
        with mock.patch.object(monitor, "BEAT_SEC", 20):
            reason = monitor.hold(
                self.dashboard,
                "one",
                "generation",
                clock=lambda: self.now,
                wait=self.wait,
                stopped=lambda: False,
                alive=lambda: self.now < 5,
                post=self.post,
                probe=lambda *_a, **_k: self.dashboard,
            )
        self.assertEqual("session-gone", reason)
        self.assertLess(self.now, 50)

    def test_a_person_s_missing_dashboard_exhausts_one_continuous_failure_budget(self) -> None:
        reason = monitor.hold(
            self.dashboard,
            "one",
            "generation",
            clock=lambda: self.now,
            wait=self.wait,
            stopped=lambda: False,
            alive=lambda: True,
            post=self.post,
            probe=lambda *_a, **_k: None,
        )
        self.assertEqual("unreachable", reason)
        self.assertLessEqual(self.now, 31)
        self.assertEqual([], self.actions)

    def test_a_person_s_holder_checks_the_harness_without_starting_ps_on_every_file_poll(
        self,
    ) -> None:
        alive = mock.Mock(side_effect=lambda: self.now < 25)
        reason = monitor.hold(
            self.dashboard,
            "one",
            "generation",
            clock=lambda: self.now,
            wait=self.wait,
            stopped=lambda: False,
            alive=alive,
            post=self.post,
            probe=lambda *_a, **_k: self.dashboard,
        )
        self.assertEqual("session-gone", reason)
        self.assertLess(self.now, 50)
        self.assertLessEqual(alive.call_count, 6)

    def test_a_person_s_answering_health_probe_cannot_extend_a_failed_beat_budget(self) -> None:
        post = mock.Mock(side_effect=client.DashboardUnreachable)
        reason = monitor.hold(
            self.dashboard,
            "one",
            "generation",
            clock=lambda: self.now,
            wait=self.wait,
            stopped=lambda: False,
            alive=lambda: True,
            post=post,
            probe=lambda *_a, **_k: self.dashboard,
        )
        self.assertEqual("unreachable", reason)
        self.assertLessEqual(self.now, 31)
        self.assertTrue(post.called)

    def test_a_person_s_idle_session_cannot_leave_an_orphan_forever(self) -> None:
        self.assertEqual("idle", self.run_loop())
        self.assertLessEqual(self.now, 7201)
        self.assertNotIn("start", self.actions)


class LockTest(unittest.TestCase):
    def test_a_person_s_crashed_holder_leaves_a_reclaimable_persistent_lock_path(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = monitor_store.Store(root, "one")
            with store.lock("life") as first:
                self.assertTrue(first)
                with store.lock("life") as second:
                    self.assertFalse(second)
            with store.lock("life") as third:
                self.assertTrue(third)
            self.assertTrue((Path(root) / "monitor" / (store.key + ".life.lock")).is_file())


class AncestorTest(unittest.TestCase):
    def test_a_person_s_nearest_claude_ancestor_is_bound_to_its_start_time(self) -> None:
        with (
            mock.patch.object(os, "getppid", return_value=30),
            mock.patch.object(
                monitor,
                "process_identity",
                side_effect=[
                    (20, "/bin/bash", "shell-start"),
                    (10, "/tools/claude", "harness-start"),
                ],
            ),
        ):
            record = monitor.ancestor()
        self.assertEqual({"pid": 20, "started": "harness-start"}, record)
        for identity, expected in (
            (None, False),
            ((10, "claude", "reused"), False),
            ((10, "claude", "harness-start"), True),
        ):
            with mock.patch.object(monitor, "process_identity", return_value=identity):
                self.assertEqual(expected, monitor.ancestor_alive(record))
        self.assertTrue(monitor.ancestor_alive({}))

    def test_a_person_s_windows_holder_does_not_probe_pids_with_kill(self) -> None:
        with (
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(os, "kill") as kill,
        ):
            self.assertIsNone(monitor.process_identity(99))
        kill.assert_not_called()


class SpawnTest(unittest.TestCase):
    def test_a_person_s_source_and_frozen_holders_detach_without_inherited_pipes(self) -> None:
        for frozen in (False, True):
            for platform in ("linux", "win32"):
                with (
                    mock.patch.object(sys, "frozen", frozen, create=True),
                    mock.patch.object(sys, "platform", platform),
                    mock.patch.object(subprocess, "DETACHED_PROCESS", 8, create=True),
                    mock.patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True),
                    mock.patch.object(subprocess, "Popen") as popen,
                ):
                    monitor.spawn("one", "a" * 32)
                argv = popen.call_args.args[0]
                options = popen.call_args.kwargs
                self.assertEqual([monitor.SIDECAR_FLAG, "one", "a" * 32], argv[-3:])
                self.assertEqual(4 if frozen else 6, len(argv))
                self.assertTrue(options["close_fds"])
                for stream in ("stdin", "stdout", "stderr"):
                    self.assertEqual(subprocess.DEVNULL, options[stream])
                self.assertNotIn("shell", options)
                if platform == "win32":
                    self.assertEqual(520, options["creationflags"])
                else:
                    self.assertTrue(options["start_new_session"])

    def test_a_person_whose_filesystem_cannot_lock_starts_nothing(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.object(monitor_store.Store, "lock", side_effect=PermissionError),
            mock.patch.object(monitor, "spawn") as spawn,
            mock.patch.object(client, "ensure_dashboard") as ensure,
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(
                1,
                monitor.command(
                    client.Session("claude", "one", "flag"), off=False, home=home, in_session=False
                ),
            )
        spawn.assert_not_called()
        ensure.assert_not_called()


class ReadinessTest(unittest.TestCase):
    def test_a_person_whose_start_times_out_does_not_leave_a_late_ready_worker(self) -> None:
        store = mock.Mock()
        store.read.return_value = {"generation": "a" * 32, "reason": "started"}
        worker = mock.Mock()
        with (
            mock.patch.object(monitor, "spawn", return_value=worker),
            mock.patch("time.monotonic", side_effect=[0, 13]),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(1, monitor._await_start(store, "one", "a" * 32))
        store.write.assert_called_once_with("stop", {"generation": "a" * 32})
        worker.wait.assert_called_once()

    def test_a_person_s_stop_request_cannot_stop_a_new_generation(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "one")
            generation = "a" * 32
            store.write(
                "run",
                {
                    "generation": generation,
                    "sid": "one",
                    "dashboard": [4553, 42, 100.0, "1.0.0"],
                    "typed": True,
                    "ancestor": {},
                },
            )
            store.write("stop", {"generation": "b" * 32})
            answer = client.Reply(200, {"ok": True})
            with (
                mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
                mock.patch("signal.signal"),
                mock.patch.object(client, "post", return_value=answer) as post,
                mock.patch.object(
                    client, "probe", return_value=client.Dashboard(4553, 42, 100.0, "1.0.0")
                ),
                mock.patch.object(monitor, "hold", return_value="stopped") as hold,
            ):
                self.assertEqual(0, monitor.sidecar("one", generation))
                self.assertFalse(hold.call_args.kwargs["stopped"]())
                store.write("stop", {"generation": generation})
                self.assertTrue(hold.call_args.kwargs["stopped"]())
            self.assertEqual("monitor on", post.call_args_list[0].args[2]["typed_action"])
            self.assertEqual(
                ["start", "stop"], [call.args[2]["action"] for call in post.call_args_list]
            )
