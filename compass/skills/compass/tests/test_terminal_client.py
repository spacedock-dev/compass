"""The terminal client: one stdlib-only way for a short command to reach the dashboard."""

from __future__ import annotations

import builtins
import contextlib
import http.client
import io
import itertools
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar, Self
from unittest import mock

from compass_runtime import (
    cli,
    entry,
    lifecycle,
    terminal_client,
    terminal_drift,
    terminal_sessions,
)

from . import support
from .support import SERVER_PATH
from .test_terminal_sessions import PAYLOAD

MANIFEST = SERVER_PATH.parents[2] / ".claude-plugin" / "plugin.json"
HEAVY = ("compass_runtime.cli", "compass_runtime.http_api", "compass_runtime.aggregate")
# Session-list tests measure a cold reply and the whole-exchange deadline on real sockets.
REAL_TIME_TESTS = True


class FakeDashboard:
    """A loopback listener that answers `/api/health` and counts every request it receives.

    `version=None` leaves the key out, as an older dashboard does. `answers` maps a path to a
    `(status, headers, body)` for anything else, so a redirect or a refusal can be staged.
    """

    def __init__(
        self,
        *,
        version: str | None = "1.0.0",
        answers: dict[str, tuple[int, dict[str, str], bytes]] | None = None,
        health: dict[str, object] | None = None,
        delays: dict[str, float | None] | None = None,
    ) -> None:
        self.requests: list[tuple[str, str]] = []
        self.release = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                return

            def _answer(self) -> None:
                outer.requests.append((self.command, self.path))
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                status, headers, body = (
                    200,
                    {"Content-Type": "application/json"},
                    json.dumps(outer.health_body()).encode(),
                )
                if self.path != "/api/health":
                    status, headers, body = (outer.answers or {}).get(self.path, (404, {}, b"{}"))
                delay = (delays or {}).get(self.path, 0)
                if delay != 0 and outer.release.wait(delay):
                    return
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = _answer  # noqa: N815

        self.answers = answers
        self._version = version
        self._health = health
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port

    def health_body(self) -> dict[str, object]:
        if self._health is not None:
            return self._health
        body: dict[str, object] = {"ok": True, "pid": 4242, "port": self.port, "started": 100.0}
        if self._version is not None:
            body["version"] = self._version
        return body

    def posts(self) -> list[tuple[str, str]]:
        return [seen for seen in self.requests if seen[0] == "POST"]

    def __enter__(self) -> Self:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release.set()
        self.server.shutdown()
        self.server.server_close()


def run_entry(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = entry.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class LightPathTest(unittest.TestCase):
    def test_version_through_server_py_never_imports_the_cli(self) -> None:
        done = subprocess.run(
            [sys.executable, "-X", "importtime", str(SERVER_PATH), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
        self.assertEqual((0, f"{expected}\n"), (done.returncode, done.stdout))
        loaded = [name for name in HEAVY if f" {name}\n" in done.stderr]
        self.assertEqual([], loaded)

    def test_anything_but_a_bare_version_is_handed_to_the_cli_untouched(self) -> None:
        for argv in (["--version", "--bogus"], ["--status"], ["--help"], []):
            with self.subTest(argv=argv), mock.patch.object(cli, "main", return_value=7) as main:
                code = entry.main(argv)

            self.assertEqual(7, code)
            main.assert_called_once_with(argv)

    def test_a_bare_version_is_answered_without_calling_the_cli(self) -> None:
        with mock.patch.object(cli, "main") as main:
            code, out, _ = run_entry("--version")

        self.assertEqual(0, code)
        main.assert_not_called()
        self.assertTrue(out.strip())


class OperationTableTest(unittest.TestCase):
    def test_every_operation_the_client_owns_is_in_the_parser_with_its_help(self) -> None:
        actions = {
            option: action
            for action in cli.build_parser()._actions
            for option in action.option_strings
        }

        for operation in terminal_client.OPERATIONS:
            with self.subTest(flag=operation.flag):
                self.assertEqual(operation.help, actions[operation.flag].help)

    def test_the_client_claims_only_flags_it_owns(self) -> None:
        flags = {operation.flag for operation in terminal_client.OPERATIONS}

        self.assertTrue(all(terminal_client.handles([flag]) for flag in flags))
        self.assertFalse(terminal_client.handles(["--stop"]))


class SessionsOperationTest(unittest.TestCase):
    def test_sessions_takes_an_optional_waiting_value_in_the_parser(self) -> None:
        parser = cli.build_parser()

        self.assertIs(True, parser.parse_args(["--sessions"]).sessions)
        self.assertEqual("waiting", parser.parse_args(["--sessions", "waiting"]).sessions)
        self.assertEqual("waiting", parser.parse_args(["--sessions=waiting"]).sessions)
        self.assertFalse(parser.parse_args([]).sessions)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as refused:
            parser.parse_args(["--sessions", "bogus"])
        self.assertEqual(2, refused.exception.code)

    def test_the_client_claims_a_lone_sessions_in_its_three_spellings_and_nothing_else(
        self,
    ) -> None:
        for argv in (["--sessions"], ["--sessions", "waiting"], ["--sessions=waiting"]):
            with self.subTest(argv=argv):
                self.assertTrue(terminal_client.handles(argv))
        for argv in (
            ["--sessions", "bogus"],
            ["--sessions=bogus"],
            ["--sessions", "--port", "4581"],
            ["--sessions", "waiting", "extra"],
            ["--sessions", "--sessions"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(terminal_client.handles(argv))


class ReleaseVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def stamp(self, text: str | None) -> Path:
        path = self.root / "stamp"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        return path

    def test_a_binary_stamp_wins_over_the_manifest(self) -> None:
        with mock.patch.object(terminal_client, "BUNDLED_VERSION_PATH", self.stamp("9.8.7\n")):
            self.assertEqual("9.8.7", terminal_client.release_version())

    def test_without_a_stamp_the_manifest_names_the_version(self) -> None:
        expected = json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]
        with mock.patch.object(terminal_client, "BUNDLED_VERSION_PATH", self.stamp(None)):
            self.assertEqual(expected, terminal_client.release_version())

    def test_the_cli_prints_the_version_the_client_resolves(self) -> None:
        out = io.StringIO()
        with (
            mock.patch.object(terminal_client, "BUNDLED_VERSION_PATH", self.stamp("4.5.6")),
            contextlib.redirect_stdout(out),
        ):
            code = cli.main(["--version", "--status"])

        self.assertEqual((0, "4.5.6\n"), (code, out.getvalue()))


class PublishedVersionTest(unittest.TestCase):
    def test_health_names_the_release_the_dashboard_runs(self) -> None:
        with support.config_patch(release_version="7.7.7"):
            httpd = support.make_server()
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=30)
        self.addCleanup(conn.close)

        conn.request("GET", "/api/health")
        health = json.loads(conn.getresponse().read())

        self.assertEqual("7.7.7", health["version"])
        self.assertTrue(health["ok"])

    def test_the_state_file_names_the_release_the_dashboard_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = support.make_config(
                state_dir=Path(tmp), state_home=tmp, release_version="7.7.7"
            )

            lifecycle.write_state(config, 4553, started=1.0, diagnostic_sink=lambda _m: None)

            written = json.loads(Path(lifecycle.state_path(config, 4553)).read_text())
        self.assertEqual("7.7.7", written["version"])

    def test_a_dashboard_started_by_the_cli_publishes_the_release_version(self) -> None:
        release = terminal_client.release_version()
        self.assertIsNotNone(release)

        config, state = cli.build_runtime(cli.build_parser().parse_args([]), started=1.0)

        self.assertEqual(release, config.release_version)
        application = cli.build_application(config, state)
        self.assertEqual(release, application.config.release_version)

    def test_a_health_answer_without_a_version_still_counts_as_a_dashboard(self) -> None:
        with FakeDashboard(version=None) as fake:
            kind, answered = lifecycle.probe_port(fake.port)

        self.assertEqual("compass", kind)
        self.assertNotIn("version", answered or {})


def closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class HomeCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        # The real default is where an operator's own dashboard may be listening.
        patch = mock.patch.object(terminal_client, "DEFAULT_PORT", closed_port())
        patch.start()
        self.addCleanup(patch.stop)

    def state_file(self, name: str, body: str = "{}", mtime: float | None = None) -> str:
        path = os.path.join(self.home, name)
        Path(path).write_text(body, encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path


class StateHomeTest(unittest.TestCase):
    def test_a_nonblank_compass_home_wins_over_the_default(self) -> None:
        self.assertEqual("/x/y", terminal_client.state_home({"COMPASS_HOME": "/x/y"}))

    def test_a_blank_compass_home_falls_back_to_the_default(self) -> None:
        home = terminal_client.state_home({"COMPASS_HOME": "  "})

        self.assertEqual(".compass", os.path.basename(home))


class DiscoveryTest(HomeCase):
    def test_ports_come_from_state_file_names_newest_first(self) -> None:
        self.state_file("compass-5000.json", mtime=100)
        self.state_file("compass-6000.json", mtime=300)
        self.state_file("compass-7000.json", mtime=200)

        self.assertEqual([6000, 7000, 5000], terminal_client.published_ports(self.home))

    def test_no_state_file_is_ever_opened(self) -> None:
        self.state_file("compass-5000.json", '{"capabilities": {"claude": "secret"}}')
        opened: list[str] = []
        real_open, real_os_open = builtins.open, os.open

        def spy_open(file: object, *args: object, **kwargs: object) -> object:
            opened.append(str(file))
            return real_open(file, *args, **kwargs)  # type: ignore[call-overload]

        def spy_os_open(path: object, *args: object, **kwargs: object) -> int:
            opened.append(str(path))
            return real_os_open(path, *args, **kwargs)  # type: ignore[arg-type]

        with (
            mock.patch.object(builtins, "open", spy_open),
            mock.patch.object(os, "open", spy_os_open),
        ):
            terminal_client.published_ports(self.home)
            terminal_client.find_dashboard(self.home, timeout=0.2)

        self.assertEqual([], [path for path in opened if "compass-" in path])

    def test_names_that_are_not_a_plain_port_file_are_ignored(self) -> None:
        for name in (
            "compass-0.json",
            "compass-65536.json",
            "compass-099.json",
            "compass-80.json.tmp",
            "compass-80.log",
            "compass-abc.json",
            "xcompass-80.json",
            "compass--1.json",
        ):
            self.state_file(name)
        os.mkdir(os.path.join(self.home, "compass-81.json"))
        target = self.state_file("target")
        os.symlink(target, os.path.join(self.home, "compass-82.json"))

        self.assertEqual([], terminal_client.published_ports(self.home))

    def test_a_missing_home_has_no_ports(self) -> None:
        self.assertEqual([], terminal_client.published_ports(os.path.join(self.home, "none")))

    def test_the_candidate_list_ends_with_the_default_and_is_bounded(self) -> None:
        for index in range(12):
            self.state_file(f"compass-{5000 + index}.json", mtime=float(index))

        candidates = terminal_client.candidate_ports(self.home)

        self.assertEqual(terminal_client.MAX_CANDIDATES, len(candidates))
        self.assertEqual(5011, candidates[0])
        self.assertEqual(terminal_client.DEFAULT_PORT, candidates[-1])

    def test_an_explicit_port_is_the_only_candidate(self) -> None:
        self.state_file("compass-5000.json")

        self.assertEqual((6000,), terminal_client.candidate_ports(self.home, port=6000))

    def test_the_dashboard_answering_on_a_published_port_is_found(self) -> None:
        with FakeDashboard(version="3.2.1") as fake:
            self.state_file(f"compass-{fake.port}.json")

            found = terminal_client.find_dashboard(self.home, timeout=30)

        assert found is not None
        self.assertEqual((fake.port, "3.2.1"), (found.port, found.version))

    def test_a_stale_state_file_over_a_closed_port_finds_nothing(self) -> None:
        self.state_file(f"compass-{closed_port()}.json")

        self.assertIsNone(terminal_client.find_dashboard(self.home, port=None, timeout=0.5))

    def test_something_else_answering_health_is_not_a_dashboard(self) -> None:
        for health in ({"ok": False}, {"ok": True, "pid": 1, "port": 1, "started": 1.0}, [1]):
            with self.subTest(health=health), FakeDashboard(health=health) as fake:  # type: ignore[arg-type]
                found = terminal_client.find_dashboard(self.home, port=fake.port, timeout=2)

            self.assertIsNone(found)

    def test_a_dashboard_without_a_version_is_found_with_none(self) -> None:
        with FakeDashboard(version=None) as fake:
            found = terminal_client.find_dashboard(self.home, port=fake.port, timeout=30)

        assert found is not None
        self.assertIsNone(found.version)


class RequestPathTest(unittest.TestCase):
    def test_a_get_returns_the_status_and_the_parsed_body(self) -> None:
        with FakeDashboard(answers={"/api/x": (200, {}, b'{"a": 1}')}) as fake:
            reply = terminal_client.get(fake.port, "/api/x")

        self.assertEqual((200, {"a": 1}), (reply.status, reply.data))

    def test_a_post_sends_json_and_the_headers_it_is_given(self) -> None:
        with FakeDashboard(answers={"/api/x": (200, {}, b"{}")}) as fake:
            reply = terminal_client.post(fake.port, "/api/x", {"k": "v"}, headers={"X-Test": "1"})

        self.assertEqual(200, reply.status)
        self.assertEqual([("POST", "/api/x")], fake.posts())

    def test_a_redirect_is_returned_and_never_followed(self) -> None:
        answers = {"/api/x": (307, {"Location": "/api/elsewhere"}, b"")}
        with FakeDashboard(answers=answers) as fake:
            reply = terminal_client.get(fake.port, "/api/x")

        self.assertEqual(307, reply.status)
        self.assertEqual([("GET", "/api/x")], fake.requests)

    def test_a_proxy_in_the_environment_is_never_contacted(self) -> None:
        with FakeDashboard() as proxy, FakeDashboard(answers={"/api/x": (200, {}, b"{}")}) as fake:
            env = {
                "HTTP_PROXY": f"http://127.0.0.1:{proxy.port}",
                "http_proxy": f"http://127.0.0.1:{proxy.port}",
                "ALL_PROXY": f"http://127.0.0.1:{proxy.port}",
            }
            with mock.patch.dict(os.environ, env):
                reply = terminal_client.get(fake.port, "/api/x")

        self.assertEqual(200, reply.status)
        self.assertEqual([], proxy.requests)

    def test_a_port_that_is_not_a_plain_integer_is_refused_before_connecting(self) -> None:
        for bad in ("80", "80@evil.example", 0, 65536, -1, True, 80.0):
            with (
                self.subTest(port=bad),
                mock.patch.object(socket, "create_connection") as connect,
                self.assertRaises(ValueError),
            ):
                terminal_client.get(bad, "/api/x")  # type: ignore[arg-type]

            connect.assert_not_called()

    def test_a_path_that_could_split_the_request_is_refused(self) -> None:
        for bad in ("api/x", "/api/x HTTP/1.1\r\nHost: evil", "/a b", "//evil.example/x", ""):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                terminal_client.get(4553, bad)

    def test_a_closed_port_raises_one_named_error(self) -> None:
        with self.assertRaises(terminal_client.DashboardUnreachable):
            terminal_client.get(closed_port(), "/api/x")

    def test_a_reply_is_read_to_a_bound(self) -> None:
        huge = b"[" + b"0," * 2048 + b"0]"
        with (
            mock.patch.object(terminal_client, "REPLY_CAP_BYTES", 1024),
            FakeDashboard(answers={"/api/x": (200, {}, huge)}) as fake,
        ):
            reply = terminal_client.get(fake.port, "/api/x")

        self.assertIsNone(reply.data)


class VersionGuardTest(unittest.TestCase):
    def found(self, version: str | None) -> terminal_client.Dashboard:
        return terminal_client.Dashboard(port=4553, pid=1, started=1.0, version=version)

    def test_the_same_version_raises_no_sentence(self) -> None:
        self.assertIsNone(terminal_client.version_guard(self.found("1.2.3"), "1.2.3"))

    def test_another_version_names_both_and_the_two_commands(self) -> None:
        sentence = terminal_client.version_guard(self.found("1.2.2"), "1.2.3")

        assert sentence is not None
        for part in ("1.2.2", "1.2.3", terminal_client.STOP_COMMAND, terminal_client.START_COMMAND):
            self.assertIn(part, sentence)
        self.assertNotIn("\n", sentence)

    def test_a_dashboard_that_reports_no_version_counts_as_another(self) -> None:
        self.assertIsNotNone(terminal_client.version_guard(self.found(None), "1.2.3"))

    def test_the_restart_commands_use_only_the_documented_options(self) -> None:
        parser_options = {
            option for action in cli.build_parser()._actions for option in action.option_strings
        }
        for command, option in (
            (terminal_client.STOP_COMMAND, "--stop"),
            (terminal_client.START_COMMAND, "--daemon"),
        ):
            with self.subTest(command=command):
                # `spacedock compass` exists only from Spacedock 0.28; this name works on both.
                self.assertEqual(["spacedock-compass", option], command.split(" "))
                self.assertIn(option, parser_options)


class MissingDashboardTest(HomeCase):
    def test_a_read_with_no_dashboard_says_so_once_and_names_the_start_command(self) -> None:
        port = closed_port()
        started: list[int] = []

        result = terminal_client.ensure_dashboard(
            self.home, port=port, spend=False, own_version="1.0.0", start=started.append
        )

        assert isinstance(result, terminal_client.Refusal)
        self.assertEqual(1, result.code)
        self.assertIn(terminal_client.START_COMMAND, result.message)
        self.assertNotIn("\n", result.message)
        self.assertEqual([], started)

    def test_a_spend_with_no_dashboard_starts_one_and_says_so(self) -> None:
        said: list[str] = []
        calls: list[int] = []

        with FakeDashboard() as fake:

            def start(requested: int) -> None:
                calls.append(requested)
                # the daemon the start command launches would now be listening
                self.state_file(f"compass-{fake.port}.json")

            result = terminal_client.ensure_dashboard(
                self.home,
                port=None,
                spend=True,
                own_version="1.0.0",
                start=start,
                say=said.append,
            )

        assert isinstance(result, terminal_client.Dashboard)
        self.assertEqual([terminal_client.DEFAULT_PORT], calls)
        self.assertEqual([terminal_client.sentence("starting")], said)

    def test_a_start_that_leaves_nothing_listening_is_refused_with_one_sentence(self) -> None:
        result = terminal_client.ensure_dashboard(
            self.home,
            port=closed_port(),
            spend=True,
            own_version="1.0.0",
            start=lambda _p: None,
            say=lambda _m: None,
        )

        assert isinstance(result, terminal_client.Refusal)
        self.assertEqual(terminal_client.sentence("start_failed"), result.message)

    def test_a_spend_against_another_version_sends_nothing_and_refuses(self) -> None:
        with FakeDashboard(version="0.0.1") as fake:
            result = terminal_client.ensure_dashboard(
                self.home, port=fake.port, spend=True, own_version="1.0.0", start=lambda _p: None
            )

        assert isinstance(result, terminal_client.Refusal)
        self.assertIn("0.0.1", result.message)
        self.assertEqual([], fake.posts())

    def test_a_read_against_another_version_is_still_served(self) -> None:
        with FakeDashboard(version="0.0.1") as fake:
            result = terminal_client.ensure_dashboard(
                self.home, port=fake.port, spend=False, own_version="1.0.0", start=lambda _p: None
            )

        self.assertIsInstance(result, terminal_client.Dashboard)

    def test_the_start_command_runs_the_launcher_with_daemon_on_the_port(self) -> None:
        with mock.patch.object(subprocess, "run") as run:
            terminal_client.start_daemon(4999)

        argv = run.call_args.args[0]
        self.assertEqual(sys.executable, argv[0])
        self.assertEqual(["--daemon", "--port", "4999"], argv[-3:])
        self.assertTrue(argv[1].endswith("launch.py") and argv[2].endswith("server.py"))


class SessionTest(unittest.TestCase):
    def test_the_flag_wins_over_the_status_line_and_the_environment(self) -> None:
        env = {"CLAUDE_CODE_SESSION_ID": "env-id"}
        stdin = io.StringIO('{"session_id": "line-id"}')

        got = terminal_client.resolve_session("codex:abc", env, stdin)

        self.assertEqual(terminal_client.Session("codex", "abc", "flag"), got)

    def test_the_status_line_wins_over_the_environment(self) -> None:
        env = {"CLAUDE_CODE_SESSION_ID": "env-id"}
        stdin = io.StringIO('{"session_id": "line-id", "other": 1}')

        got = terminal_client.resolve_session(None, env, stdin)

        self.assertEqual(terminal_client.Session("claude", "line-id", "status line"), got)

    def test_the_environment_names_a_claude_session(self) -> None:
        got = terminal_client.resolve_session(None, {"CLAUDE_CODE_SESSION_ID": "env-id"}, None)

        self.assertEqual(terminal_client.Session("claude", "env-id", "environment"), got)

    def test_another_tool_s_session_is_never_read_as_the_claude_session_it_started_in(
        self,
    ) -> None:
        env = {"CLAUDE_CODE_SESSION_ID": "outer", "CODEX_THREAD_ID": "thread-1"}

        got = terminal_client.resolve_session(None, env, None)

        self.assertEqual(terminal_client.Unresolved(terminal_client.sentence("other_harness")), got)

    def test_the_status_line_still_names_its_session_inside_another_tool(self) -> None:
        env = {"CODEX_THREAD_ID": "thread-1"}

        got = terminal_client.resolve_session(None, env, None, payload={"session_id": "line-id"})

        self.assertEqual(terminal_client.Session("claude", "line-id", "status line"), got)

    def test_with_nothing_it_says_it_cannot_tell_and_never_guesses_from_the_directory(self) -> None:
        with mock.patch.object(os, "getcwd", side_effect=AssertionError("read the cwd")):
            got = terminal_client.resolve_session(None, {}, None)

        self.assertEqual(terminal_client.Unresolved(terminal_client.sentence("no_session")), got)

    def test_a_malformed_flag_is_refused_and_not_replaced_by_the_environment(self) -> None:
        env = {"CLAUDE_CODE_SESSION_ID": "env-id"}
        for bad in (
            "claude",
            ":abc",
            "claude:",
            "Claude:abc",
            "claude:a b",
            "claude:a\x00b",
            "claude:" + "x" * 201,
            "",
        ):
            with self.subTest(flag=bad):
                got = terminal_client.resolve_session(bad, env, None)

                self.assertEqual(
                    terminal_client.Unresolved(terminal_client.sentence("bad_session_flag")), got
                )

    def test_a_status_line_that_is_not_usable_falls_through(self) -> None:
        env = {"CLAUDE_CODE_SESSION_ID": "env-id"}
        for text in (
            "",
            "not json",
            "[1]",
            '{"session_id": 5}',
            '{"session_id": ""}',
            "x" * 70_000,
        ):
            with self.subTest(text=text[:20]):
                got = terminal_client.resolve_session(None, env, io.StringIO(text))

                assert isinstance(got, terminal_client.Session)
                self.assertEqual("environment", got.source)

    def test_a_terminal_on_stdin_is_never_read(self) -> None:
        class Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

            def read(self, *_a: object) -> str:
                raise AssertionError("read a terminal")

        got = terminal_client.resolve_session(None, {"CLAUDE_CODE_SESSION_ID": "e"}, Tty())

        self.assertEqual("environment", got.source)  # type: ignore[union-attr]

    def test_the_status_line_is_read_to_a_bound(self) -> None:
        stream = io.StringIO('{"session_id": "a"}' + " " * 200_000)

        terminal_client.resolve_session(None, {}, stream)

        self.assertLessEqual(stream.tell(), terminal_client.STDIN_CAP_CHARS + 1)


def data_reply(body: object) -> dict[str, tuple[int, dict[str, str], bytes]]:
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return {"/api/sessions": (200, {"Content-Type": "application/json"}, raw)}


BOARD = {
    "generated": 1000.0,
    "ask": False,
    "annotate": False,
    "harnesses": [{"key": "claude", "label": "Claude Code", "reports_needs_input": True}],
    "sessions": [
        {
            "harness": "claude",
            "sid": "a1b2c3d4",
            "project": "alpha",
            "title": "Wire the parser",
            "state": "working",
            "last_activity": 990.0,
            "resume_id": "a1b2c3d4-0000-4000-8000-000000000000",
        }
    ],
}

WAITING_BOARD = {
    **BOARD,
    "sessions": [{**BOARD["sessions"][0], "state": "needs_input", "blocked_since": 900.0}],  # type: ignore[index]
}
HISTORY_ONLY_BOARD = {
    **BOARD,
    "sessions": [
        {**BOARD["sessions"][0], "state": "idle", "title": "Old work", "last_activity": 100.0}  # type: ignore[index]
    ],
}


class SessionsCommandTest(HomeCase):
    def run_sessions(
        self,
        mode: str | None = None,
        *,
        port: int | None = None,
        environ: dict[str, str] | None = None,
    ) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        env = {"COMPASS_HOME": self.home, **(environ or {})}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = terminal_client.run_sessions(mode, port=port, environ=env)
        return code, out.getvalue(), err.getvalue()

    def test_with_no_dashboard_the_shared_sentence_goes_to_stderr_and_the_exit_is_one(self) -> None:
        code, out, err = self.run_sessions()

        self.assertEqual((1, ""), (code, out))
        self.assertEqual(terminal_client.sentence("not_running") + "\n", err)

    def test_a_board_is_read_from_the_dashboard_and_printed_to_stdout(self) -> None:
        with FakeDashboard(answers=data_reply(BOARD)) as fake:
            code, out, err = self.run_sessions(port=fake.port)

        self.assertEqual((0, ""), (code, err))
        self.assertIn("Wire the parser", out)
        self.assertEqual([("GET", "/api/health"), ("GET", "/api/sessions")], fake.requests)

    def test_the_read_never_asks_for_usage_or_the_wider_window(self) -> None:
        with FakeDashboard(answers=data_reply(BOARD)) as fake:
            self.run_sessions(port=fake.port)

        self.assertEqual([], [path for _, path in fake.requests if "?" in path])

    def test_a_person_can_read_their_sessions_when_the_cold_board_takes_six_seconds(self) -> None:
        with FakeDashboard(answers=data_reply(BOARD), delays={"/api/sessions": 6}) as fake:
            code, out, err = self.run_sessions(port=fake.port)

        self.assertEqual((0, ""), (code, err))
        self.assertIn("Wire the parser", out)
        self.assertNotIn("could not be read", out)

    def test_a_person_is_not_left_waiting_forever_for_their_session_list(self) -> None:
        with FakeDashboard(answers=data_reply(BOARD), delays={"/api/sessions": None}) as fake:
            # Release the fixture even if the client's deadline is broken, so that the test
            # reports a failure instead of leaving a listener and a blocked request behind.
            guard = threading.Timer(35, fake.release.set)
            guard.start()
            try:
                started = time.monotonic()
                code, out, err = self.run_sessions(port=fake.port)
                elapsed = time.monotonic() - started
            finally:
                guard.cancel()
                guard.join()

        self.assertEqual(
            (1, "", "Compass answered, but its session list could not be read.\n"),
            (code, out, err),
        )
        self.assertGreater(elapsed, 6)
        self.assertLess(elapsed, 34)

    def test_a_person_reads_both_lists_when_history_and_full_rows_exceed_the_cap(self) -> None:
        board = {
            **PAYLOAD,
            "sessions": [PAYLOAD["sessions"][i % 13] for i in range(3751)],
            "history": {"pad": "x" * (terminal_client.DATA_CAP_BYTES + 1)},
        }
        self.assertGreater(
            len(json.dumps({"sessions": board["sessions"]})), terminal_client.DATA_CAP_BYTES
        )
        lean = terminal_sessions.list_payload(board)
        with FakeDashboard(answers=data_reply(lean)) as fake:
            for mode in (None, "waiting"):
                with self.subTest(mode=mode):
                    code, out, err = self.run_sessions(mode, port=fake.port)
                    lines = (
                        terminal_sessions.render_sessions(board)
                        if mode is None
                        else terminal_sessions.render_waiting(
                            board,
                            port=fake.port,
                            exclude=None,
                            nothing=terminal_client.sentence("nothing_waiting"),
                            caveat=terminal_client.sentence("caller_unknown"),
                        )
                    )
                    self.assertEqual((0, "\n".join(lines) + "\n", ""), (code, out, err))
        self.assertNotIn(("GET", "/api/data"), fake.requests)

    def test_a_person_can_reuse_the_structured_session_reader(self) -> None:
        with FakeDashboard(answers=data_reply(BOARD)) as fake:
            self.assertEqual(BOARD, terminal_client.read_sessions(fake.port))
        self.assertEqual([("GET", "/api/sessions")], fake.requests)

    def test_a_person_with_an_older_dashboard_still_reads_their_sessions(self) -> None:
        board = {**PAYLOAD, "history": {"pad": "x" * (terminal_client.REPLY_CAP_BYTES + 1)}}
        answers = {
            **data_reply(terminal_sessions.list_payload(board)),
            "/api/data": (200, {}, json.dumps(board).encode()),
        }
        with FakeDashboard(version="0.0.1", answers=answers) as fake:
            for mode in (None, "waiting"):
                with self.subTest(mode=mode):
                    answers["/api/sessions"] = data_reply(terminal_sessions.list_payload(board))[
                        "/api/sessions"
                    ]
                    expected = self.run_sessions(mode, port=fake.port)
                    self.assertEqual((0, ""), (expected[0], expected[2]))
                    fake.requests.clear()
                    answers["/api/sessions"] = (404, {}, b"{}")

                    actual = self.run_sessions(mode, port=fake.port)

                    self.assertEqual(expected, actual)
                    self.assertEqual(
                        [("GET", "/api/health"), ("GET", "/api/sessions"), ("GET", "/api/data")],
                        fake.requests,
                    )

    def test_a_person_is_not_shown_a_fallback_list_after_another_read_failure(self) -> None:
        replies: list[tuple[int, dict[str, str], bytes]] = [
            (500, {}, b"{}"),
            (200, {}, b"{"),
            (200, {}, b'{"sessions":3}'),
        ]
        for reply in replies:
            with (
                self.subTest(reply=reply),
                FakeDashboard(
                    answers={
                        "/api/sessions": reply,
                        "/api/data": (200, {}, json.dumps(BOARD).encode()),
                    }
                ) as fake,
            ):
                for mode in (None, "waiting"):
                    self.assertEqual(
                        (1, "", "Compass answered, but its session list could not be read.\n"),
                        self.run_sessions(mode, port=fake.port),
                    )
                self.assertNotIn(("GET", "/api/data"), fake.requests)

    def test_a_person_gets_no_false_empty_list_when_the_older_dashboard_reply_is_unreadable(
        self,
    ) -> None:
        replies: list[tuple[int, dict[str, str], bytes]] = [
            (500, {}, b'{"sessions":[]}'),
            (200, {}, b"{"),
            (200, {}, b'{"sessions":[{}]}'),
        ]
        for reply in replies:
            with (
                self.subTest(reply=reply),
                FakeDashboard(
                    answers={"/api/sessions": (404, {}, b"{}"), "/api/data": reply}
                ) as fake,
            ):
                self.assertEqual(
                    (1, "", "Compass answered, but its session list could not be read.\n"),
                    self.run_sessions(port=fake.port),
                )

    def test_a_person_is_told_when_the_older_dashboard_reply_exceeds_the_safety_bound(self) -> None:
        answers: dict[str, tuple[int, dict[str, str], bytes]] = {
            "/api/sessions": (404, {}, b"{}"),
            "/api/data": (200, {}, json.dumps({**BOARD, "history": "x" * 2000}).encode()),
        }
        with (
            FakeDashboard(answers=answers) as fake,
            mock.patch.object(terminal_client, "DATA_CAP_BYTES", 1000),
        ):
            self.assertEqual(
                (1, "", "Compass answered, but its session list could not be read.\n"),
                self.run_sessions(port=fake.port),
            )
        self.assertIn(("GET", "/api/data"), fake.requests)

    def test_a_person_gets_an_unreadable_answer_instead_of_a_false_empty_list(self) -> None:
        malformed: list[dict[str, Any]] = [
            {},
            {"sessions": [None]},
            {"sessions": [{}]},
            {"sessions": [], "harnesses": {}},
            {"sessions": [], "harnesses": [None]},
            {"sessions": [], "asks": {}},
            {"sessions": [], "asks": [None]},
            {"sessions": [], "ask": True, "asks": [{}]},
        ]
        replies: list[tuple[int, dict[str, str], bytes]] = [
            (404, {}, b"{}"),
            (500, {}, b"{}"),
            (200, {}, b"{"),
            *[(200, {}, json.dumps(body).encode()) for body in malformed],
        ]
        for reply in replies:
            with self.subTest(reply=reply), FakeDashboard(answers={"/api/sessions": reply}) as fake:
                with self.assertRaises(terminal_client.UnreadableSessionsError):
                    terminal_client.read_sessions(fake.port)
                for mode in (None, "waiting"):
                    code, out, err = self.run_sessions(mode, port=fake.port)
                    self.assertEqual(
                        (1, "", terminal_client.sentence("unreadable_reply") + "\n"),
                        (code, out, err),
                    )

    def test_a_person_can_read_a_legitimately_empty_board(self) -> None:
        with FakeDashboard(answers=data_reply({"sessions": []})) as fake:
            for mode in (None, "waiting"):
                code, out, err = self.run_sessions(mode, port=fake.port)
                self.assertEqual((0, ""), (code, err))
                self.assertIn(
                    "Active now" if mode is None else terminal_client.sentence("nothing_waiting"),
                    out,
                )

    def test_a_board_over_the_bound_is_one_sentence_and_exit_one(self) -> None:
        padded = {**BOARD, "history": {"pad": "x" * 2_000}}
        with (
            mock.patch.object(terminal_client, "DATA_CAP_BYTES", 1_000),
            FakeDashboard(answers=data_reply(padded)) as fake,
        ):
            for mode in (None, "waiting"):
                code, out, err = self.run_sessions(mode, port=fake.port)
                self.assertEqual((1, ""), (code, out))
                self.assertEqual(terminal_client.sentence("unreadable_reply") + "\n", err)

    def test_a_refusal_or_a_body_that_is_no_board_is_one_sentence_and_exit_one(self) -> None:
        replies = {
            "a 500": (500, {}, b"{}"),
            "html": (200, {"Content-Type": "text/html"}, b"<html></html>"),
            "a list": (200, {}, b"[]"),
            "no sessions list": (200, {}, b'{"sessions": 3}'),
        }
        for name, reply in replies.items():
            with self.subTest(name), FakeDashboard(answers={"/api/sessions": reply}) as fake:
                for mode in (None, "waiting"):
                    code, out, err = self.run_sessions(mode, port=fake.port)
                    self.assertEqual((1, ""), (code, out))
                    self.assertEqual(terminal_client.sentence("unreadable_reply") + "\n", err)

    def test_a_dashboard_that_dies_between_the_probe_and_the_read_is_one_sentence(self) -> None:
        with (
            FakeDashboard() as fake,
            mock.patch.object(
                terminal_client, "get", side_effect=terminal_client.DashboardUnreachable("gone")
            ),
        ):
            code, out, err = self.run_sessions(port=fake.port)

        self.assertEqual((1, ""), (code, out))
        self.assertEqual(terminal_client.sentence("unreadable_reply") + "\n", err)

    def test_a_listing_that_fails_to_render_is_one_sentence_and_exit_one_never_a_traceback(
        self,
    ) -> None:
        for name in ("render_sessions", "render_waiting"):
            with (
                self.subTest(name),
                FakeDashboard(answers=data_reply(BOARD)) as fake,
                mock.patch.object(terminal_sessions, name, side_effect=OverflowError("big")),
            ):
                code, out, err = self.run_sessions(
                    "waiting" if name == "render_waiting" else None, port=fake.port
                )

            self.assertEqual((1, ""), (code, out))
            self.assertEqual(terminal_client.sentence("unreadable_reply") + "\n", err)

    def test_the_cli_path_renders_from_the_named_port_and_starts_nothing(self) -> None:
        with (
            FakeDashboard(answers=data_reply(BOARD)) as fake,
            mock.patch.dict(os.environ, {"COMPASS_HOME": self.home}),
            mock.patch.object(lifecycle, "serve") as serve,
        ):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = cli.main(["--sessions", "--port", str(fake.port)])

        self.assertEqual(0, code)
        serve.assert_not_called()
        self.assertIn("Wire the parser", out.getvalue())

    def test_a_port_that_was_not_typed_leaves_discovery_on(self) -> None:
        with (
            mock.patch.object(terminal_client, "run_sessions", return_value=0) as run,
        ):
            cli.main(["--sessions", "waiting"])
            cli.main(["--sessions", "--port", "4581"])

        self.assertEqual(
            [mock.call("waiting", port=None), mock.call(True, port=4581)], run.call_args_list
        )

    def test_the_caller_is_left_out_of_the_waiting_list_by_its_full_session_id(self) -> None:
        waiting = {
            **BOARD,
            "sessions": [
                {**BOARD["sessions"][0], "state": "needs_input", "blocked_since": 900.0},  # type: ignore[index]
                {
                    "harness": "claude",
                    "sid": "ffffffff",
                    "project": "beta",
                    "title": "Another waiter",
                    "state": "needs_input",
                    "blocked_since": 800.0,
                },
            ],
        }
        with FakeDashboard(answers=data_reply(waiting)) as fake:
            _, out, _ = self.run_sessions(
                "waiting",
                port=fake.port,
                environ={"CLAUDE_CODE_SESSION_ID": "a1b2c3d4-0000-4000-8000-000000000000"},
            )

        self.assertIn("Another waiter", out)
        self.assertNotIn("Wire the parser", out)

    def waiting_output(
        self,
        environ: dict[str, str],
        mode: str | None = "waiting",
        board: dict[str, Any] | None = None,
    ) -> str:
        with FakeDashboard(answers=data_reply(BOARD if board is None else board)) as fake:
            _, out, _ = self.run_sessions(mode, port=fake.port, environ=environ)
        return out

    def test_a_reader_whose_session_cannot_be_identified_is_told_it_may_be_in_the_waiting_list(
        self,
    ) -> None:
        notice = terminal_client.sentence("caller_unknown")
        for name, environ in {
            "no id": {},
            "an id that is not one": {"CLAUDE_CODE_SESSION_ID": "not an id!"},
            "an empty id": {"CLAUDE_CODE_SESSION_ID": ""},
        }.items():
            with self.subTest(name):
                out = self.waiting_output(environ, board=WAITING_BOARD)

                self.assertEqual(1, out.count(notice))
                self.assertEqual(notice, out.splitlines()[0])
                self.assertLess(out.index(notice), out.index(terminal_sessions.PROVENANCE))
                self.assertLess(out.index(notice), out.index("Wire the parser"))

    def test_the_notice_names_no_harness_and_no_variable_the_reader_could_set(self) -> None:
        notice = terminal_client.sentence("caller_unknown")

        self.assertNotIn("CLAUDE", notice)
        self.assertEqual(
            "Compass could not tell which session is asking, so this list may include it.", notice
        )

    def test_a_reader_with_nobody_waiting_is_not_told_the_list_may_include_their_session(
        self,
    ) -> None:
        out = self.waiting_output({})

        self.assertIn(terminal_client.sentence("nothing_waiting"), out)
        self.assertNotIn(terminal_client.sentence("caller_unknown"), out)

    def test_a_reader_whose_session_is_identified_is_not_told_anything_about_it(self) -> None:
        out = self.waiting_output(
            {"CLAUDE_CODE_SESSION_ID": "a1b2c3d4-0000-4000-8000-000000000000"},
            board=WAITING_BOARD,
        )

        self.assertNotIn(terminal_client.sentence("caller_unknown"), out)

    def test_the_plain_session_list_never_mentions_the_waiting_list_caveat(self) -> None:
        out = self.waiting_output({}, mode=None)

        self.assertNotIn(terminal_client.sentence("caller_unknown"), out)
        self.assertIn("Wire the parser", out)

    def test_every_list_that_prints_other_sessions_words_says_they_are_data_once(self) -> None:
        for name, mode, board in (
            ("all", None, BOARD),
            ("history only", None, HISTORY_ONLY_BOARD),
            ("waiting", "waiting", WAITING_BOARD),
        ):
            with self.subTest(name):
                out = self.waiting_output({}, mode, board)

                self.assertEqual(1, out.count(terminal_sessions.PROVENANCE))
                title = board["sessions"][0]["title"]  # type: ignore[index]
                self.assertLess(out.index(terminal_sessions.PROVENANCE), out.index(title))

    def test_a_list_with_no_sessions_prints_no_provenance_line(self) -> None:
        for name, mode, board in (
            ("all", None, {**BOARD, "sessions": []}),
            ("waiting", "waiting", BOARD),
        ):
            with self.subTest(name):
                out = self.waiting_output({}, mode, board)

                self.assertNotIn(terminal_sessions.PROVENANCE, out)

    def test_a_lone_sessions_never_loads_the_dashboard_modules(self) -> None:
        program = (
            "import sys\n"
            f"sys.path.insert(0, {str(SERVER_PATH.parent)!r})\n"
            "from compass_runtime import entry, terminal_client\n"
            f"terminal_client.DEFAULT_PORT = {closed_port()}\n"
            "code = entry.main(['--sessions'])\n"
            "print(code, [m for m in sys.modules if m in "
            "('compass_runtime.cli', 'compass_runtime.http_api', 'compass_runtime.aggregate')])\n"
        )
        with tempfile.TemporaryDirectory() as home:
            done = subprocess.run(
                [sys.executable, "-c", program],
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
                env={**os.environ, "COMPASS_HOME": home},
            )

        self.assertEqual("1 []\n", done.stdout)
        self.assertEqual(terminal_client.sentence("not_running") + "\n", done.stderr)


class DriftOperationTest(unittest.TestCase):
    def test_drift_takes_an_optional_again_value_in_the_parser(self) -> None:
        parser = cli.build_parser()

        self.assertIs(True, parser.parse_args(["--drift"]).drift)
        self.assertEqual("again", parser.parse_args(["--drift", "again"]).drift)
        self.assertEqual("again", parser.parse_args(["--drift=again"]).drift)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as refused:
            parser.parse_args(["--drift", "bogus"])
        self.assertEqual(2, refused.exception.code)

    def test_the_client_claims_drift_with_again_and_one_session_in_any_order(self) -> None:
        for argv, expected in (
            (["--drift"], (True, False, None)),
            (["--drift", "again"], (True, True, None)),
            (["--drift=again"], (True, True, None)),
            (["--drift", "--session", "claude:abc"], (True, False, "claude:abc")),
            (["--session=claude:abc", "--drift", "again"], (True, True, "claude:abc")),
            (["--drift", "again", "--session", "claude:abc"], (True, True, "claude:abc")),
        ):
            with self.subTest(argv=argv):
                self.assertEqual(expected, terminal_client.parse_drift_args(argv))
                self.assertTrue(terminal_client.handles(argv))
        for argv in (
            ["--drift", "bogus"],
            ["--drift", "--drift"],
            ["--drift", "--session"],
            ["--drift", "--session", "a:b", "--session", "a:c"],
            ["--drift", "--port", "4581"],
            ["--drift", "again", "again"],
            ["--drift", "--footer"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(terminal_client.parse_drift_args(argv)[0])
                self.assertFalse(terminal_client.handles(argv))

    def test_a_typed_port_reaches_drift_through_the_cli_with_its_session(self) -> None:
        with mock.patch.object(terminal_client, "run_drift", return_value=0) as run:
            code = cli.main(["--drift", "again", "--session", "claude:abc", "--port", "4581"])

        self.assertEqual(0, code)
        run.assert_called_once_with(again=True, session="claude:abc", port=4581)


class DriftCommandTest(HomeCase):
    VIEW: ClassVar[dict[str, Any]] = {
        "harness": "claude",
        "sid": "abc",
        "malformed": "",
        "pill": {"level": "medium", "so_far": False},
        "analysis": {"level": "medium"},
        "lines": [
            {
                "key": "goal",
                "state": "departs",
                "numbers": ["41"],
                "clause": "Accept tabs",
                "detail": "It rejected them.",
            }
        ],
        "departures": ["goal"],
        "priors": [],
        "stale": None,
    }
    ROW: ClassVar[dict[str, Any]] = {
        "harness": "claude",
        "sid": "abc",
        "project": "compass",
        "title": "Tabs",
        "annotation_goal": "Accept tabs",
        "annotation_revision": 1,
        "annotation_assessment": {"read_at": 1000.0, "revision_read": 1},
    }

    def answers(self) -> dict[str, tuple[int, dict[str, str], bytes]]:
        json_type = {"Content-Type": "application/json"}
        board = {"annotate": True, "generated": 1100.0, "sessions": [self.ROW], "reading_jobs": {}}
        context = {"sources": {"work": {"drift_views": [self.VIEW]}}}
        correction = {"ok": True, "parts": ["Keep accepting tabs."]}
        return {
            "/api/data": (200, json_type, json.dumps(board).encode()),
            "/api/project-context?project=compass&session=claude%3Aabc": (
                200,
                json_type,
                json.dumps(context).encode(),
            ),
            "/api/correction": (200, json_type, json.dumps(correction).encode()),
            "/api/reading": (409, json_type, b'{"ok": false, "reason": "provider-changed"}'),
        }

    def run_drift(
        self,
        *,
        again: bool = False,
        session: str | None = None,
        port: int | None = None,
        environ: dict[str, str] | None = None,
        tty: bool = False,
    ) -> tuple[int, str, str]:
        """`tty` is whether standard output is a terminal; an agent's tool reads it from a pipe."""

        class Stdout(io.StringIO):
            def isatty(self) -> bool:
                return tty

        out, err = Stdout(), io.StringIO()
        env = {"COMPASS_HOME": self.home, **(environ or {})}
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = terminal_client.run_drift(again=again, session=session, port=port, environ=env)
        return code, out.getvalue(), err.getvalue()

    def test_a_person_who_names_no_session_is_told_how_and_nothing_is_reached(self) -> None:
        with FakeDashboard() as fake:
            code, out, err = self.run_drift(port=fake.port, tty=True)

        self.assertEqual((1, ""), (code, out))
        self.assertEqual(terminal_client.sentence("no_session") + "\n", err)
        self.assertEqual([], fake.requests)

    def test_a_person_whose_agent_has_no_session_id_is_not_told_to_pass_a_flag(self) -> None:
        # The skill runs `--drift` through a pipe and never adds `--session`, so a flag to pass is
        # an instruction the agent must not follow and the person cannot use there.
        with FakeDashboard() as fake:
            code, out, err = self.run_drift(port=fake.port, tty=False)

        self.assertEqual((1, ""), (code, out))
        self.assertEqual(terminal_client.sentence("no_session_in_session") + "\n", err)
        self.assertNotIn("--session", err)
        self.assertIn("reads Claude Code sessions", err)
        self.assertIn("nothing was read or spent", err)
        self.assertEqual([], fake.requests)

    def test_a_person_in_another_tool_s_session_started_under_claude_code_reads_nothing(
        self,
    ) -> None:
        # Codex started inside a Claude Code session inherits that session's id; read as this
        # session, it would print, and spend on, the outer session's reading.
        env = {terminal_client.CLAUDE_SESSION_ENV: "abc", "CODEX_THREAD_ID": "thread-1"}
        version = terminal_client.release_version()
        for tty in (True, False):
            with (
                self.subTest(tty=tty),
                FakeDashboard(version=version, answers=self.answers()) as fake,
            ):
                code, out, err = self.run_drift(port=fake.port, environ=env, tty=tty)

                self.assertEqual((1, ""), (code, out))
                self.assertEqual(terminal_client.sentence("other_harness") + "\n", err)
                self.assertNotIn("on the board, so nothing was read", err)
                self.assertEqual([], fake.requests)

    def test_a_person_in_another_tool_s_session_may_still_name_a_claude_session(self) -> None:
        env = {terminal_client.CLAUDE_SESSION_ENV: "abc", "CODEX_THREAD_ID": "thread-1"}
        version = terminal_client.release_version()
        with FakeDashboard(version=version, answers=self.answers()) as fake:
            code, out, _err = self.run_drift(
                session="claude:abc", port=fake.port, environ=env, tty=True
            )

        self.assertEqual(0, code)
        self.assertIn("Level: Medium", out)

    def test_a_person_whose_drift_started_compass_reads_that_in_the_session(self) -> None:
        # The skill prints standard output on success, so the line goes there inside a session.
        version = terminal_client.release_version()
        with FakeDashboard(version=version, answers=self.answers()) as fake:

            def start(_port: int, **_budget: Any) -> None:
                self.state_file(f"compass-{fake.port}.json")

            with mock.patch.object(terminal_client, "start_daemon", side_effect=start):
                code, out, err = self.run_drift(
                    environ={terminal_client.CLAUDE_SESSION_ENV: "abc"}, tty=False
                )

        self.assertEqual(0, code)
        self.assertEqual(terminal_client.sentence("starting"), out.splitlines()[0])
        self.assertNotIn(terminal_client.sentence("starting"), err)

    def test_a_person_whose_drift_started_compass_and_was_refused_reads_both(self) -> None:
        # On a refusal the skill prints standard error, so the start is said there too.
        version = terminal_client.release_version()
        answers = self.answers()
        answers["/api/data"] = (200, {}, json.dumps({"sessions": [], "annotate": True}).encode())
        with FakeDashboard(version=version, answers=answers) as fake:

            def start(_port: int, **_budget: Any) -> None:
                self.state_file(f"compass-{fake.port}.json")

            with mock.patch.object(terminal_client, "start_daemon", side_effect=start):
                code, _out, err = self.run_drift(
                    environ={terminal_client.CLAUDE_SESSION_ENV: "abc"}, tty=False
                )

        self.assertEqual(1, code)
        lines = err.splitlines()
        self.assertEqual(terminal_client.sentence("starting"), lines[0])
        self.assertIn("no session claude:abc on the board", lines[1])

    def test_a_person_at_a_shell_whose_drift_started_compass_is_told_on_standard_error(
        self,
    ) -> None:
        version = terminal_client.release_version()
        with FakeDashboard(version=version, answers=self.answers()) as fake:

            def start(_port: int, **_budget: Any) -> None:
                self.state_file(f"compass-{fake.port}.json")

            with mock.patch.object(terminal_client, "start_daemon", side_effect=start):
                code, out, err = self.run_drift(session="claude:abc", tty=True)

        self.assertEqual(0, code)
        self.assertEqual(terminal_client.sentence("starting") + "\n", err)
        self.assertNotIn(terminal_client.sentence("starting"), out)

    def test_a_person_in_a_session_is_told_how_to_restart_another_release_without_the_cli(
        self,
    ) -> None:
        with FakeDashboard(version="0.0.1", answers=self.answers()) as fake:
            code, _out, err = self.run_drift(
                port=fake.port, environ={terminal_client.CLAUDE_SESSION_ENV: "abc"}, tty=False
            )

        self.assertEqual(1, code)
        self.assertIn("version 0.0.1", err)
        self.assertNotIn("spacedock-compass", err)
        self.assertIn("/compass:compass", err)
        self.assertEqual([("GET", "/api/health")], fake.requests)

    def test_a_dashboard_start_inside_a_session_is_bounded_by_what_is_left_of_its_wait(
        self,
    ) -> None:
        budgets: list[float] = []

        def start(_port: int, *, timeout: float) -> None:
            budgets.append(timeout)

        with (
            mock.patch.object(terminal_client, "start_daemon", side_effect=start),
            mock.patch(
                "time.time", side_effect=itertools.chain([1000.0], itertools.repeat(1080.0))
            ),
        ):
            self.run_drift(environ={terminal_client.CLAUDE_SESSION_ENV: "abc"}, tty=False)

        self.assertEqual(1, len(budgets))
        self.assertLessEqual(budgets[0], 20.0)

    def test_a_person_whose_session_does_not_parse_is_refused_before_anything_is_reached(
        self,
    ) -> None:
        with FakeDashboard() as fake:
            code, _out, err = self.run_drift(session="nocolon", port=fake.port)

        self.assertEqual(1, code)
        self.assertEqual(terminal_client.sentence("bad_session_flag") + "\n", err)
        self.assertEqual([], fake.requests)

    def test_a_person_at_a_shell_reads_the_stored_reading_and_its_correction(self) -> None:
        version = terminal_client.release_version()
        with FakeDashboard(version=version, answers=self.answers()) as fake:
            code, out, err = self.run_drift(session="claude:abc", port=fake.port, tty=True)

        self.assertEqual((0, ""), (code, err))
        self.assertIn("Level: Medium", out)
        self.assertIn("Correction to copy:\nKeep accepting tabs.", out)
        self.assertNotIn(("POST", "/api/reading"), fake.requests)

    def test_a_person_whose_agent_names_the_session_through_a_pipe_keeps_the_correction_out(
        self,
    ) -> None:
        # An agent's shell tool, and Claude Code's `!` mode, read the output from a pipe, so the
        # correction would land in the context of the agent it is addressed to.
        version = terminal_client.release_version()
        with FakeDashboard(version=version, answers=self.answers()) as fake:
            code, out, _err = self.run_drift(session="claude:abc", port=fake.port, tty=False)

        self.assertEqual(0, code)
        self.assertIn("Level: Medium", out)
        self.assertNotIn("Keep accepting tabs.", out)
        self.assertNotIn("Correction to copy:", out)
        self.assertIn("A correction is ready to copy on the session page", out)

    def test_a_person_inside_the_session_is_named_by_the_environment_and_gets_no_correction(
        self,
    ) -> None:
        version = terminal_client.release_version()
        for tty in (True, False):
            with (
                self.subTest(tty=tty),
                FakeDashboard(version=version, answers=self.answers()) as fake,
            ):
                code, out, _err = self.run_drift(
                    port=fake.port, environ={terminal_client.CLAUDE_SESSION_ENV: "abc"}, tty=tty
                )

                self.assertEqual(0, code)
                self.assertNotIn("Keep accepting tabs.", out)
                self.assertIn("A correction is ready to copy on the session page", out)

    def test_a_person_s_agent_is_never_told_to_run_a_command_that_prints_the_correction(
        self,
    ) -> None:
        version = terminal_client.release_version()
        with FakeDashboard(version=version, answers=self.answers()) as fake:
            _code, out, _err = self.run_drift(session="claude:abc", port=fake.port)

        ready = next(line for line in out.splitlines() if "correction is ready" in line)
        self.assertNotRegex(ready, r"^A correction is ready to copy: run ")
        self.assertIn("only", ready)
        self.assertIn("your own terminal", ready)

    def test_a_refused_press_is_read_from_the_refusal_s_own_body(self) -> None:
        version = terminal_client.release_version()
        answers = self.answers()
        with FakeDashboard(version=version, answers=answers) as fake:
            answers["/api/data"] = (
                200,
                {},
                json.dumps(
                    {
                        "annotate": True,
                        "generated": 1100.0,
                        "sessions": [self.ROW],
                        "reading_jobs": {},
                        "reading_routes": {"claude": {"provider": "claude", "model": "m"}},
                        "reading": {"consent": True},
                        "reading_check": "passed",
                    }
                ).encode(),
            )
            code, _out, err = self.run_drift(again=True, session="claude:abc", port=fake.port)

        self.assertEqual(1, code)
        self.assertEqual(terminal_drift.PROVIDER_CHANGED + "\n", err)

    def test_a_press_against_another_release_sends_nothing(self) -> None:
        with FakeDashboard(version="0.0.1", answers=self.answers()) as fake:
            code, _out, err = self.run_drift(session="claude:abc", port=fake.port)

        self.assertEqual(1, code)
        self.assertIn("version 0.0.1", err)
        self.assertEqual([("GET", "/api/health")], fake.requests)


class InSessionBudgetTest(unittest.TestCase):
    def test_a_press_is_sent_only_with_time_left_to_hear_whether_it_started(self) -> None:
        self.assertGreaterEqual(
            terminal_drift.PRESS_RESERVE_SEC,
            terminal_client.DRIFT_REQUEST_TIMEOUT_SEC + terminal_drift.POLL_SEC,
        )

    def test_no_exchange_inside_a_session_outlasts_what_is_left_of_its_wait(self) -> None:
        with mock.patch("time.time", return_value=1000.0):
            board = terminal_client.LoopbackBoard(4553, deadline=1010.0)
            self.assertLessEqual(board.timeout(), 9.0)
            self.assertEqual(
                terminal_client.DRIFT_REQUEST_TIMEOUT_SEC,
                terminal_client.LoopbackBoard(4553).timeout(),
            )


class WordingTest(unittest.TestCase):
    def test_every_sentence_is_one_line_and_every_placeholder_is_filled(self) -> None:
        for key in terminal_client.SENTENCES:
            with self.subTest(key=key):
                text = terminal_client.sentence(
                    key, own="1.0.0", theirs="0.9.0", stop="S", start="T"
                )

                self.assertNotIn("\n", text)
                self.assertNotIn("{", text)

    def test_the_sentences_a_reader_sees_are_pinned(self) -> None:
        self.assertEqual(
            "Compass is not running. Start it with `spacedock-compass --daemon`.",
            terminal_client.sentence("not_running"),
        )
        self.assertEqual(
            "Compass was not running, so this started it as `--daemon` does.",
            terminal_client.sentence("starting"),
        )
        self.assertEqual(
            "Compass could not start the dashboard. Start it with `spacedock-compass --daemon`.",
            terminal_client.sentence("start_failed"),
        )
        self.assertEqual(
            "Compass cannot tell which session this is. Pass --session claude:SESSION_ID.",
            terminal_client.sentence("no_session"),
        )
        self.assertEqual(
            "The drift action reads Claude Code sessions and this command runs inside another "
            "tool's session, so nothing was read or spent; that session's page on the board shows "
            "its drift.",
            terminal_client.sentence("other_harness"),
        )
        self.assertEqual(
            "The drift action reads Claude Code sessions and this command was given no Claude Code "
            "session id, so nothing was read or spent; a session's page on the board shows its "
            "drift.",
            terminal_client.sentence("no_session_in_session"),
        )
        self.assertEqual(
            "Compass answered, but its session list could not be read.",
            terminal_client.sentence("unreadable_reply"),
        )
        self.assertEqual(
            "The running dashboard is version 0.9.0 and this is version 1.0.0, so nothing was sent. "
            "Stop it with `spacedock-compass --stop` and start it again with "
            "`spacedock-compass --daemon`.",
            terminal_client.sentence("version_mismatch", own="1.0.0", theirs="0.9.0"),
        )


if __name__ == "__main__":
    unittest.main()
