"""The session's terminal holder: spend admission, ownership, and bounded lifetime."""

from __future__ import annotations

import contextlib
import gc
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import warnings
import weakref
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from compass_runtime import monitor_store
from compass_runtime import terminal_client as client
from compass_runtime import terminal_monitor as monitor

from .test_terminal_client import FakeDashboard


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
    def test_a_person_whose_dashboard_cannot_be_reached_gets_the_transport_failure(self) -> None:
        store = mock.Mock()
        store.read.return_value = {"generation": "a" * 32, "reason": "unreachable", "answer": {}}
        with mock.patch.object(monitor, "spawn"), mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(1, monitor._await_start(store, "one", "a" * 32))
        self.assertIn("could not start or stop", err.getvalue())

    def test_a_person_repeating_the_command_reads_the_board_without_another_start(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "one")
            store.write(
                "run", {"sid": "one", "project": "billing", "dashboard": [4553, 42, 100.0, "1.0.0"]}
            )
            for due in (False, True):
                board = {
                    "sources": {
                        "work": {
                            "live_monitor": {
                                "notice_due": due,
                                "disclosure": "Sends to the changed destination.",
                            }
                        }
                    }
                }
                with (
                    self.subTest(due=due),
                    mock.patch.object(store, "running", return_value=True),
                    mock.patch.object(client, "get", return_value=client.Reply(200, board)) as get,
                    mock.patch.object(client, "post") as post,
                    mock.patch.object(monitor, "spawn") as spawn,
                    mock.patch("sys.stdout", io.StringIO()) as out,
                ):
                    self.assertEqual(
                        0,
                        monitor._command(
                            store,
                            client.Session("claude", "one", "flag"),
                            off=False,
                            in_session=True,
                        ),
                    )
                    self.assertEqual(due, "Sends to the changed destination." in out.getvalue())
                    self.assertIn("already running", out.getvalue())
                    self.assertIn("/api/project-context?", get.call_args.args[1])
                    post.assert_not_called()
                    spawn.assert_not_called()

    def test_a_person_s_long_unicode_goal_keeps_the_start_receipt_readable(self) -> None:
        answer = {
            "ok": True,
            "terminal": {
                "goal_status": "adopted",
                "goal": {"text": "字" * 10000, "source": "first-prompt"},
                "disclosure": "Sends to Haiku.",
                "notice_due": True,
            },
        }
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "one")
            store.write("status", {"answer": monitor._start_receipt(client.Reply(200, answer))})
            saved = store.read("status")["answer"]
            self.assertTrue(saved["ok"])
            self.assertTrue(saved["terminal"]["goal"]["text"].endswith("…"))
            self.assertEqual("Sends to Haiku.", saved["terminal"]["disclosure"])

    def test_a_person_reads_the_receipt_even_when_the_holder_already_exited(self) -> None:
        answer = {
            "ok": True,
            "terminal": {
                "notice_due": True,
                "disclosure": "Sends your words to Haiku.",
                "goal_status": "adopted",
                "goal": {"text": "Ship the parser", "source": "first-prompt", "at": 100},
                "page_url": "http://127.0.0.1:4553/#n=session:billing:claude:one",
            },
        }
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "one")
            generation = "a" * 32
            store.write(
                "run",
                {
                    "generation": generation,
                    "sid": "one",
                    "dashboard": [4553, 42, 100.0, "1.0.0"],
                    "ancestor": {},
                },
            )
            with (
                mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
                mock.patch("signal.signal"),
                mock.patch.object(client, "post", return_value=client.Reply(200, answer)),
                mock.patch.object(
                    client, "probe", return_value=client.Dashboard(4553, 42, 100.0, "1.0.0")
                ),
                mock.patch.object(monitor, "hold", return_value="stopped"),
            ):
                self.assertEqual(0, monitor.sidecar("one", generation))
            with (
                mock.patch.object(monitor, "spawn"),
                mock.patch("sys.stdout", io.StringIO()) as out,
            ):
                self.assertEqual(0, monitor._await_start(store, "one", generation))
            self.assertIn("Sends your words to Haiku.", out.getvalue())
            self.assertIn("From your first prompt · saved", out.getvalue())
            self.assertIn("Ship the parser", out.getvalue())
            self.assertIn("http://127.0.0.1:4553/#n=session:billing:claude:one", out.getvalue())

    def test_a_person_without_a_goal_is_told_why_the_monitor_is_quiet(self) -> None:
        with mock.patch("sys.stdout", io.StringIO()) as out:
            self.assertEqual(
                0,
                monitor._report_start(
                    {
                        "ok": True,
                        "terminal": {
                            "goal_status": "missing",
                            "page_url": "http://127.0.0.1:4553/#n=session:p:claude:one",
                        },
                    }
                ),
            )
        self.assertIn("on", out.getvalue())
        self.assertIn("no check until a goal is saved", out.getvalue())
        self.assertIn("http://127.0.0.1:4553/", out.getvalue())

    def test_a_person_reads_one_sentence_for_each_known_refusal(self) -> None:
        for reason, words in (
            ("paused", "paused"),
            ("no-observer-model", "--no-observer-model"),
            ("ended", "ended"),
        ):
            with self.subTest(reason=reason), mock.patch("sys.stderr", io.StringIO()) as err:
                self.assertEqual(1, monitor._report_start({"ok": False, "reason": reason}))
                self.assertIn(words, err.getvalue())
                self.assertEqual(1, len(err.getvalue().splitlines()))

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


class MonitorCorrectionsTest(unittest.TestCase):
    row: ClassVar[dict[str, str]] = {
        "harness": "claude",
        "sid": "abcdefab",
        "resume_id": "abcdefab-1111-4111-8111-111111111111",
    }
    dashboard = client.Dashboard(4553, 42, 100.0, "1.0.0")

    def test_a_person_only_hears_ended_when_the_board_uniquely_identifies_their_session(
        self,
    ) -> None:
        for reply, sentence in (
            (client.Reply(200, {"session": {**self.row, "ended_at": 100.0}}), "monitor_ended"),
            (client.Reply(404, {"reason": "not-found"}), "monitor_unavailable"),
            (client.Reply(409, {"reason": "ambiguous"}), "monitor_unavailable"),
        ):
            with (
                self.subTest(reply=reply),
                tempfile.TemporaryDirectory() as home,
                mock.patch.object(client, "ensure_dashboard", return_value=self.dashboard),
                mock.patch.object(client, "get", return_value=reply),
                mock.patch.object(monitor, "spawn") as spawn,
                mock.patch("sys.stderr", io.StringIO()) as err,
            ):
                result = monitor.command(
                    client.Session("claude", self.row["resume_id"], "flag"),
                    off=False,
                    home=home,
                    in_session=False,
                )
                self.assertEqual(1, result)
                self.assertEqual(client.sentence(sentence) + "\n", err.getvalue())
                spawn.assert_not_called()

    def test_a_person_with_a_long_history_still_finds_their_live_session(self) -> None:
        history = json.dumps(
            {"sessions": [self.row], "history": "x" * client.DATA_CAP_BYTES}
        ).encode()
        self.assertGreater(len(history), client.DATA_CAP_BYTES)
        path = "/api/session?harness=claude&sid=" + self.row["resume_id"]
        answers = {
            "/api/data?all=1": (200, {"Content-Type": "application/json"}, history),
            path: (
                200,
                {"Content-Type": "application/json"},
                json.dumps({"session": self.row}).encode(),
            ),
        }
        with (
            FakeDashboard(answers=answers) as board,
            tempfile.TemporaryDirectory() as home,
            mock.patch.object(
                client, "ensure_dashboard", return_value=self.dashboard._replace(port=board.port)
            ),
            mock.patch.object(monitor, "_await_start", return_value=0),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            result = monitor.command(
                client.Session("claude", self.row["resume_id"], "flag"),
                off=False,
                home=home,
                in_session=False,
            )
        self.assertEqual(0, result)
        self.assertEqual([("GET", path)], board.requests)

    def test_a_person_with_an_unreadable_board_is_never_told_their_session_is_missing(self) -> None:
        for reply in (
            client.Reply(200, None),
            client.Reply(200, {}),
            client.Reply(500, {}),
            client.Reply(404, None),
            client.Reply(200, {"session": {}}),
        ):
            with (
                self.subTest(reply=reply),
                tempfile.TemporaryDirectory() as home,
                mock.patch.object(client, "ensure_dashboard", return_value=self.dashboard),
                mock.patch.object(client, "get", return_value=reply),
                mock.patch.object(monitor, "spawn") as spawn,
                mock.patch("sys.stderr", io.StringIO()) as err,
            ):
                self.assertEqual(
                    1,
                    monitor.command(
                        client.Session("claude", "abcdefab", "flag"),
                        off=False,
                        home=home,
                        in_session=False,
                    ),
                )
                self.assertIn("could not read", err.getvalue())
                self.assertNotIn("could not find", err.getvalue())
                spawn.assert_not_called()

    def test_a_person_who_stops_the_monitor_while_a_killed_start_is_still_launching_is_not_left_with_one_running(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "abcdefab")
            generation = "a" * 32
            store.write(
                "run",
                {
                    **self.row,
                    "generation": generation,
                    "dashboard": list(self.dashboard),
                    "ancestor": {},
                },
            )
            waiting = threading.Event()
            results: list[int] = []
            lock = monitor_store.Store.lock

            @contextlib.contextmanager
            def observed_lock(target: monitor_store.Store, kind: str) -> Any:
                with lock(target, kind) as held:
                    if kind == "command" and not held:
                        waiting.set()
                    yield held

            def off() -> None:
                results.append(
                    monitor.command(
                        client.Session("claude", self.row["resume_id"], "flag"),
                        off=True,
                        home=home,
                        in_session=False,
                    )
                )

            with (
                mock.patch("sys.stdout", io.StringIO()),
                mock.patch.object(monitor_store.Store, "lock", observed_lock),
            ):
                with store.lock("command") as held:
                    self.assertTrue(held)
                    stopper = threading.Thread(target=off)
                    stopper.start()
                    self.assertTrue(waiting.wait(2), "off never waited on the starting command")
                # Releasing command models its owner being killed before the worker takes life.
                stopper.join(timeout=3)
                self.assertFalse(stopper.is_alive())
                self.assertEqual([0], results)
            with (
                mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
                mock.patch("signal.signal"),
                mock.patch.object(client, "probe", return_value=self.dashboard),
                mock.patch.object(
                    client, "post", return_value=client.Reply(200, {"ok": True})
                ) as post,
                mock.patch.object(monitor, "hold", return_value="stopped"),
            ):
                self.assertEqual(0, monitor.sidecar("abcdefab", generation))
            self.assertNotIn("start", [call.args[2]["action"] for call in post.call_args_list])
            self.assertFalse(store.running())

    def test_a_person_stopping_a_different_full_id_does_not_cancel_a_pending_monitor(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "abcdefab")
            store.write("run", {**self.row, "generation": "a" * 32})
            with mock.patch("sys.stdout", io.StringIO()):
                monitor.command(
                    client.Session("claude", "abcdefab-2222-4222-8222-222222222222", "flag"),
                    off=True,
                    home=home,
                    in_session=False,
                )
            self.assertEqual({}, store.read("stop"))

    def test_a_person_who_starts_a_monitor_for_another_session_keeps_it_when_their_own_session_closes(
        self,
    ) -> None:
        for own, expected_alive in (
            ("abcdefab-2222-4222-8222-222222222222", True),
            (self.row["resume_id"], False),
            ("abcdefab", False),
        ):
            with (
                self.subTest(own=own),
                tempfile.TemporaryDirectory() as home,
                mock.patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": own}),
                mock.patch.object(client, "ensure_dashboard", return_value=self.dashboard),
                mock.patch.object(
                    client,
                    "get",
                    return_value=client.Reply(200, {"session": self.row, "sessions": [self.row]}),
                ),
                mock.patch.object(
                    monitor, "ancestor", return_value={"pid": 99999, "started": "gone"}
                ),
                mock.patch.object(monitor, "process_identity", return_value=None),
                mock.patch.object(monitor, "_await_start", return_value=0),
            ):
                store = monitor_store.Store(home, "abcdefab")
                self.assertEqual(
                    0,
                    monitor.command(
                        client.Session("claude", self.row["resume_id"], "flag"),
                        off=False,
                        home=home,
                        in_session=False,
                    ),
                )
                self.assertEqual(
                    expected_alive, monitor.ancestor_alive(store.read("run")["ancestor"])
                )

    def test_a_person_on_windows_running_two_monitor_commands_at_once_is_told_one_is_busy(
        self,
    ) -> None:
        locks: set[int] = set()

        def locking(fd: int, action: int, _size: int) -> None:
            self.assertEqual(0, os.lseek(fd, 0, os.SEEK_CUR))
            if action == 1:
                if locks:
                    raise PermissionError
                locks.add(fd)
            else:
                locks.remove(fd)

        msvcrt = types.SimpleNamespace(LK_NBLCK=1, LK_UNLCK=2, locking=locking)
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "abcdefab")
            with (
                mock.patch.dict(sys.modules, {"msvcrt": msvcrt}),
                mock.patch.object(sys, "platform", "win32"),
            ):
                with store.lock("command") as first:
                    self.assertTrue(first)
                    with store.lock("command") as second:
                        self.assertFalse(second)
                    self.assertEqual(b"", store.path("command.lock").read_bytes())
                self.assertEqual(set(), locks)
                with store.lock("command") as third:
                    self.assertTrue(third)

    def test_a_person_on_windows_gets_a_failure_instead_of_busy_when_locking_is_broken(
        self,
    ) -> None:
        msvcrt = types.SimpleNamespace(
            LK_NBLCK=1, LK_UNLCK=2, locking=mock.Mock(side_effect=OSError("broken"))
        )
        with tempfile.TemporaryDirectory() as home:
            store = monitor_store.Store(home, "abcdefab")
            with (
                mock.patch.dict(sys.modules, {"msvcrt": msvcrt}),
                mock.patch.object(sys, "platform", "win32"),
                self.assertRaises(OSError),
                store.lock("command"),
            ):
                pass

    def test_a_person_whose_board_hangs_is_told_the_monitor_failed_instead_of_refused(self) -> None:
        store = mock.Mock()
        store.read.return_value = {"generation": "a" * 32, "reason": "unreachable"}
        with mock.patch.object(monitor, "spawn"), mock.patch("sys.stderr", io.StringIO()) as err:
            self.assertEqual(1, monitor._await_start(store, "one", "a" * 32))
        self.assertIn(client.sentence("monitor_failed"), err.getvalue())
        self.assertNotIn("refused", err.getvalue())

    def test_a_person_whose_worker_ignores_terminate_does_not_leave_it_after_a_readiness_timeout(
        self,
    ) -> None:
        store = mock.Mock()
        worker = mock.Mock()
        worker.poll.return_value = None
        worker.wait.side_effect = [
            subprocess.TimeoutExpired("worker", 6),
            subprocess.TimeoutExpired("worker", 6),
            0,
        ]
        with (
            mock.patch.object(monitor, "spawn", return_value=worker),
            mock.patch("time.monotonic", side_effect=[0, 13]),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(1, monitor._await_start(store, "one", "a" * 32))
        worker.kill.assert_called_once()
        self.assertEqual(3, worker.wait.call_count)

    def test_a_person_whose_monitor_starts_does_not_get_a_resource_warning(self) -> None:
        store = mock.Mock()
        store.read.return_value = {"generation": "a" * 32, "reason": "started"}
        workers: list[weakref.ReferenceType[subprocess.Popen[bytes]]] = []

        def launch(*_args: Any) -> subprocess.Popen[bytes]:
            worker = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(20)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            workers.append(weakref.ref(worker))
            return worker

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                with (
                    mock.patch.object(monitor, "spawn", side_effect=launch),
                    mock.patch("sys.stdout", io.StringIO()),
                ):
                    self.assertEqual(0, monitor._await_start(store, "one", "a" * 32))
                gc.collect()
            self.assertFalse([w for w in caught if w.category is ResourceWarning])
        finally:
            worker = workers[0]() if workers else None
            if worker is not None:
                worker.kill()
                worker.wait()
