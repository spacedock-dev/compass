"""A reader gets an honest refusal before any automatic start or model request."""

from __future__ import annotations

import contextlib
import errno
import functools
import io
import os
import shlex
import sys
from pathlib import Path, PureWindowsPath
from unittest import mock

from compass_runtime import loopback_transport, terminal_client

from .test_terminal_client import FakeDashboard, HomeCase, data_reply
from .test_terminal_sessions import PAYLOAD


class RefusalTest(HomeCase):
    def test_a_person_is_given_the_start_command_for_the_copy_they_are_running(self) -> None:
        root = Path(self.home).resolve() / "plugin with spaces" / "skills" / "compass"
        module = root / "compass_runtime" / "terminal_client.py"
        for frozen in (False, True):
            executable = str(Path(self.home) / "bin with spaces" / "compass")
            expected = [executable]
            if not frozen:
                expected += [str(root / "launch.py"), str(root / "server.py")]
            out, err = io.StringIO(), io.StringIO()
            with (
                self.subTest(frozen=frozen),
                mock.patch.object(sys, "frozen", frozen, create=True),
                mock.patch.object(sys, "executable", executable),
                mock.patch.object(terminal_client, "__file__", str(module)),
                mock.patch.object(terminal_client, "find_dashboard", return_value=None),
                mock.patch.object(terminal_client, "start_daemon") as start,
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                code = terminal_client.run_sessions(environ={"COMPASS_HOME": self.home})
            self.assertEqual((1, ""), (code, out.getvalue()))
            message = err.getvalue().strip()
            self.assertTrue(message.startswith("Compass is not running; start it with `"))
            command = message.split("`", 2)[1]
            if os.name == "nt":
                self.assertEqual(
                    " ".join(f'"{Path(token).as_posix()}"' for token in [*expected, "--daemon"]),
                    command,
                )
            else:
                self.assertEqual([*expected, "--daemon"], shlex.split(command))
            self.assertNotIn("spacedock-compass", message)
            start.assert_not_called()

    def test_a_person_on_windows_can_copy_the_start_command_into_cmd_or_bash(self) -> None:
        class WindowsPath(PureWindowsPath):
            def resolve(self) -> WindowsPath:
                return self

        windows_os = mock.Mock(wraps=os)
        windows_os.name = "nt"
        for folder in ("compass", "compass with spaces"):
            for frozen in (False, True):
                with self.subTest(folder=folder, frozen=frozen):
                    root = WindowsPath("C:/Users/me") / folder / "skills" / "compass"
                    executable = WindowsPath("C:/Users/me") / folder / "python.exe"
                    expected = [executable.as_posix()]
                    if not frozen:
                        expected += [
                            (root / "launch.py").as_posix(),
                            (root / "server.py").as_posix(),
                        ]
                    expected.append("--daemon")
                    err = io.StringIO()
                    with (
                        mock.patch.object(terminal_client, "os", windows_os),
                        mock.patch.object(terminal_client, "Path", WindowsPath),
                        mock.patch.object(sys, "frozen", frozen, create=True),
                        mock.patch.object(sys, "executable", str(executable)),
                        mock.patch.object(
                            terminal_client,
                            "__file__",
                            str(root / "compass_runtime" / "terminal_client.py"),
                        ),
                        mock.patch.object(terminal_client, "find_dashboard", return_value=None),
                        contextlib.redirect_stderr(err),
                    ):
                        self.assertEqual(1, terminal_client.run_sessions(environ={}))
                    command = err.getvalue().split("`", 2)[1]
                    self.assertEqual(" ".join(f'"{token}"' for token in expected), command)
                    self.assertNotIn("\\", command)
                    self.assertEqual(expected, shlex.split(command))

    def test_a_person_whose_loopback_connection_is_blocked_is_told_why_and_starts_nothing(
        self,
    ) -> None:
        for number in (errno.EPERM, errno.EACCES):
            for spend in (False, True):
                out, err = io.StringIO(), io.StringIO()
                with (
                    self.subTest(errno=number, spend=spend),
                    mock.patch.object(
                        loopback_transport._Socket,
                        "connect",
                        side_effect=OSError(number, "blocked"),
                    ),
                    mock.patch.object(terminal_client, "start_daemon") as start,
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                ):
                    env = {"COMPASS_HOME": self.home, "CLAUDE_CODE_SESSION_ID": "caller"}
                    code = (
                        terminal_client.run_drift(environ=env)
                        if spend
                        else terminal_client.run_sessions(environ=env)
                    )
                self.assertEqual((1, ""), (code, out.getvalue()))
                self.assertEqual(
                    "Compass's connection to the dashboard was blocked by a sandbox or permissions.\n",
                    err.getvalue(),
                )
                self.assertNotIn("not running", err.getvalue())
                start.assert_not_called()

    def test_a_person_is_told_when_permissions_block_a_read_after_the_dashboard_answered_health(
        self,
    ) -> None:
        for number in (errno.EPERM, errno.EACCES):
            env = {"COMPASS_HOME": self.home, "CLAUDE_CODE_SESSION_ID": "caller"}
            commands = {
                "sessions": functools.partial(terminal_client.run_sessions, environ=env),
                "waiting": functools.partial(terminal_client.run_sessions, "waiting", environ=env),
                "drift": functools.partial(terminal_client.run_drift, environ=env),
                "monitor": functools.partial(terminal_client.run_monitor, environ=env),
                "project": functools.partial(terminal_client.run_project, environ=env),
                "goal": functools.partial(
                    terminal_client.run_goal, terminal_client.GoalRequest(), environ=env
                ),
                "summary": functools.partial(
                    terminal_client.run_summary, terminal_client.SummaryRequest(), environ=env
                ),
            }
            for action, command in commands.items():
                out, err = io.StringIO(), io.StringIO()
                with (
                    self.subTest(errno=number, action=action),
                    mock.patch.object(
                        terminal_client,
                        "find_dashboard",
                        return_value=terminal_client.Dashboard(
                            terminal_client.DEFAULT_PORT, 1, 1.0, terminal_client.release_version()
                        ),
                    ),
                    mock.patch.object(
                        loopback_transport._Socket,
                        "connect",
                        side_effect=OSError(number, "blocked"),
                    ),
                    mock.patch.object(terminal_client, "start_daemon") as start,
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                ):
                    self.assertEqual(1, command())
                    self.assertEqual("", out.getvalue())
                    self.assertEqual(
                        "Compass's connection to the dashboard was blocked by a sandbox or permissions.\n",
                        err.getvalue(),
                    )
                    start.assert_not_called()

    def test_a_person_gets_the_blocked_reason_for_a_permission_error_even_without_an_errno(
        self,
    ) -> None:
        errors = [PermissionError("sandbox"), OSError("sandbox"), OSError("sandbox")]
        errors[1].errno = errno.EPERM
        errors[2].errno = errno.EACCES
        for error in errors:
            for answered_health in (False, True):
                out, err = io.StringIO(), io.StringIO()
                found = terminal_client.Dashboard(terminal_client.DEFAULT_PORT, 1, 1.0, "test")
                with (
                    self.subTest(error=repr(error), answered_health=answered_health),
                    mock.patch.object(
                        terminal_client,
                        "candidate_ports",
                        return_value=(terminal_client.DEFAULT_PORT,),
                    ),
                    mock.patch.object(loopback_transport._Socket, "connect", side_effect=error),
                    mock.patch.object(terminal_client, "start_daemon") as start,
                    contextlib.redirect_stdout(out),
                    contextlib.redirect_stderr(err),
                    contextlib.ExitStack() as stack,
                ):
                    if answered_health:
                        stack.enter_context(
                            mock.patch.object(terminal_client, "find_dashboard", return_value=found)
                        )
                    code = terminal_client.run_sessions(environ={"COMPASS_HOME": self.home})
                    self.assertEqual((1, ""), (code, out.getvalue()))
                    self.assertEqual(
                        "Compass's connection to the dashboard was blocked by a sandbox or permissions.\n",
                        err.getvalue(),
                    )
                    start.assert_not_called()

    def test_a_person_with_an_absent_dashboard_keeps_the_usual_start_policy(self) -> None:
        for number in (errno.ECONNREFUSED, errno.ETIMEDOUT):
            for spend in (False, True):
                err = io.StringIO()
                with (
                    self.subTest(errno=number, spend=spend),
                    mock.patch.object(
                        loopback_transport._Socket, "connect", side_effect=OSError(number, "absent")
                    ),
                    mock.patch.object(terminal_client, "start_daemon") as start,
                    contextlib.redirect_stderr(err),
                ):
                    env = {"COMPASS_HOME": self.home, "CLAUDE_CODE_SESSION_ID": "caller"}
                    code = (
                        terminal_client.run_drift(environ=env)
                        if spend
                        else terminal_client.run_sessions(environ=env)
                    )
                self.assertEqual(1, code)
                self.assertNotIn("blocked", err.getvalue())
                if spend:
                    start.assert_called_once()
                    self.assertIn("could not start", err.getvalue())
                else:
                    start.assert_not_called()
                    self.assertIn("not running", err.getvalue())

    def test_a_person_without_a_resolvable_caller_gets_their_own_actions_reason(self) -> None:
        outcomes = {
            "monitor": "no Live monitor was started or stopped",
            "project": "no project brief was read",
            "goal": "no goal was read or changed",
            "summary": "no summary was read or requested",
        }
        drift = {
            False: (
                "The drift action reads Claude Code sessions and this command was given no Claude Code "
                "session id, so nothing was read or spent; a session's page on the board shows its drift.\n"
            ),
            True: (
                "The drift action reads Claude Code sessions and this command runs inside another tool's "
                "session, so nothing was read or spent; that session's page on the board shows its drift.\n"
            ),
        }

        class Output(io.StringIO):
            def isatty(self) -> bool:
                return tty

        for tty in (False, True):
            for other in (False, True):
                env = {"COMPASS_HOME": self.home}
                if other:
                    env.update(CODEX_THREAD_ID="inner", CLAUDE_CODE_SESSION_ID="outer")
                for action in (
                    "drift",
                    "monitor",
                    "project",
                    "goal",
                    "summary",
                    "sessions waiting",
                ):
                    with self.subTest(tty=tty, other=other, action=action):
                        out, err = Output(), io.StringIO()
                        with (
                            FakeDashboard(answers=data_reply(PAYLOAD)) as fake,
                            mock.patch.object(terminal_client, "start_daemon") as start,
                            contextlib.redirect_stdout(out),
                            contextlib.redirect_stderr(err),
                        ):
                            commands = {
                                "goal": functools.partial(
                                    terminal_client.run_goal,
                                    terminal_client.GoalRequest(),
                                    environ=env,
                                ),
                                "summary": functools.partial(
                                    terminal_client.run_summary,
                                    terminal_client.SummaryRequest(),
                                    environ=env,
                                ),
                                "sessions waiting": functools.partial(
                                    terminal_client.run_sessions,
                                    "waiting",
                                    port=fake.port,
                                    environ=env,
                                ),
                                "drift": functools.partial(terminal_client.run_drift, environ=env),
                                "monitor": functools.partial(
                                    terminal_client.run_monitor, environ=env
                                ),
                                "project": functools.partial(
                                    terminal_client.run_project, environ=env
                                ),
                            }
                            code = commands[action]()
                        if action == "sessions waiting":
                            self.assertEqual(0, code)
                            self.assertEqual(
                                "Compass could not tell which session is asking, so this list may include it.",
                                out.getvalue().splitlines()[0],
                            )
                            self.assertEqual("", err.getvalue())
                        else:
                            self.assertEqual((1, ""), (code, out.getvalue()))
                            expected = (
                                drift[other]
                                if action == "drift"
                                else (
                                    f"The {action} action cannot identify this caller inside another tool's "
                                    f"session, so {outcomes[action]}.\n"
                                    if other
                                    else f"The {action} action was given no Claude Code session id, so {outcomes[action]}.\n"
                                )
                            )
                            self.assertEqual(expected, err.getvalue())
                            self.assertEqual([], fake.requests)
                        if not tty or other:
                            self.assertNotIn("--session", err.getvalue())
                        start.assert_not_called()

    def test_a_person_without_a_caller_gets_a_goal_reason_even_when_they_requested_a_save(
        self,
    ) -> None:
        for tty in (False, True):
            for env in ({}, {"CODEX_THREAD_ID": "inner", "CLAUDE_CODE_SESSION_ID": "outer"}):
                for request in (
                    terminal_client.GoalRequest(text="Keep the goal"),
                    terminal_client.GoalRequest(clear=True),
                    terminal_client.GoalRequest(adopt=True),
                ):
                    out, err = io.StringIO(), io.StringIO()
                    with (
                        self.subTest(tty=tty, env=env, request=request),
                        mock.patch.object(out, "isatty", return_value=tty),
                        mock.patch.object(terminal_client, "ensure_dashboard") as ensure,
                        contextlib.redirect_stdout(out),
                        contextlib.redirect_stderr(err),
                    ):
                        code = terminal_client.run_goal(request, environ=env)
                        self.assertEqual((1, ""), (code, out.getvalue()))
                        self.assertIn("goal action", err.getvalue())
                        self.assertIn("no goal was read or changed", err.getvalue())
                        self.assertNotIn("--session", err.getvalue())
                        ensure.assert_not_called()

    def test_a_person_whose_monitor_session_flag_is_invalid_keeps_that_specific_reason(
        self,
    ) -> None:
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = terminal_client.run_monitor(
                session="invalid", environ={"COMPASS_HOME": self.home}
            )
        self.assertEqual(1, code)
        self.assertEqual(
            "The session must look like claude:SESSION_ID, with no spaces.\n", err.getvalue()
        )
