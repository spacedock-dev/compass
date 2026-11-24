"""`--forward-usage`: Claude Code's status line hands its two quota windows to the board.

The forwarder runs on every status line refresh beside the reader's own status line, so it is held
to the footer's rules for that path: bounded stdin, silence, exit 0. It is held to one more, which
is what makes it safe to run on a payload that names the session, its transcript and its folder:
the only thing it sends is the two windows' numbers.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from typing import Any
from unittest import mock

from compass_runtime import cli, entry, quota, terminal_client

from .support import SERVER_PATH, RuntimeTestCase, build_app, make_server, poll_fast
from .test_terminal_client import FakeDashboard, HomeCase

NOW = 1_700_000_000.0
FIVE_RESET = int(NOW + 3_600)
WEEK_RESET = int(NOW + 4 * 86_400)
# Values a real status line carries that must never leave this process. Deliberately distinct
# strings, so an assertion that one is absent cannot pass because another happened to be.
SESSION_ID = "forward-test-session-0001"
TRANSCRIPT = "/Users/someone/.claude/projects/private-repo/forward-test.jsonl"
CWD = "/Users/someone/private-repo"


def payload(**rate_limits: Any) -> dict[str, Any]:
    """A status line payload shaped like Claude Code's, with every identifying field filled in."""
    body: dict[str, Any] = {
        "session_id": SESSION_ID,
        "transcript_path": TRANSCRIPT,
        "cwd": CWD,
        "session_name": "private work",
        "model": {"id": "claude-opus-test", "display_name": "Opus"},
        "workspace": {"current_dir": CWD, "project_dir": CWD, "repo": {"name": "private-repo"}},
        "version": "2.1.330",
        "cost": {"total_cost_usd": 1.25},
    }
    if rate_limits:
        body["rate_limits"] = rate_limits
    return body


def both_windows() -> dict[str, Any]:
    return payload(
        five_hour={"used_percentage": 42.5, "resets_at": FIVE_RESET},
        seven_day={"used_percentage": 61, "resets_at": WEEK_RESET},
        spend_limit={"used_usd": 12, "limit_usd": 100, "resets_at": WEEK_RESET},
    )


class ForwardedWindowsTest(unittest.TestCase):
    """What the forwarder lifts out of a payload, before anything is sent."""

    def test_the_forwarder_extracts_only_the_two_windows(self) -> None:
        windows = terminal_client.forwarded_windows(both_windows(), NOW)

        self.assertEqual(
            {
                "five_hour": {"used_percentage": 42.5, "resets_at": FIVE_RESET},
                "seven_day": {"used_percentage": 61, "resets_at": WEEK_RESET},
            },
            windows,
        )

    def test_extra_fields_inside_a_window_are_not_carried(self) -> None:
        body = payload(
            five_hour={"used_percentage": 10, "resets_at": FIVE_RESET, "account": "someone"}
        )

        self.assertEqual(
            {"five_hour": {"used_percentage": 10, "resets_at": FIVE_RESET}},
            terminal_client.forwarded_windows(body, NOW),
        )

    def test_a_figure_that_is_not_a_percentage_withholds_its_window(self) -> None:
        for used in (None, "42", True, -1, 100.5, math.nan, math.inf, 10**400):
            with self.subTest(used=used):
                body = payload(five_hour={"used_percentage": used, "resets_at": FIVE_RESET})
                self.assertEqual({}, terminal_client.forwarded_windows(body, NOW))

    def test_a_reset_that_cannot_be_read_or_has_passed_withholds_its_window(self) -> None:
        for resets_at in (None, True, "soon", "2026-11-24", NOW - 1, NOW, 0, -5, NOW * 1000):
            with self.subTest(resets_at=resets_at):
                body = payload(five_hour={"used_percentage": 10, "resets_at": resets_at})
                self.assertEqual({}, terminal_client.forwarded_windows(body, NOW))

    def test_an_iso_reset_is_sent_as_whole_epoch_seconds(self) -> None:
        body = payload(five_hour={"used_percentage": 10, "resets_at": "2023-11-14T23:13:20.75Z"})

        self.assertEqual(
            {"five_hour": {"used_percentage": 10, "resets_at": 1_700_003_600}},
            terminal_client.forwarded_windows(body, NOW),
        )

    def test_one_window_alone_is_forwarded(self) -> None:
        body = payload(seven_day={"used_percentage": 3, "resets_at": WEEK_RESET + 0.9})

        self.assertEqual(
            {"seven_day": {"used_percentage": 3, "resets_at": WEEK_RESET}},
            terminal_client.forwarded_windows(body, NOW),
        )

    def test_a_payload_without_rate_limits_forwards_nothing(self) -> None:
        bodies: tuple[dict[str, Any] | None, ...] = (
            None,
            {},
            payload(),
            {"rate_limits": None},
            {"rate_limits": []},
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assertEqual({}, terminal_client.forwarded_windows(body, NOW))


class ForwardUsageCommandTest(HomeCase):
    """The command as a status line runs it: stdin in, one POST out, nothing printed."""

    def forward(self, stdin: str, port: int | None = None) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = terminal_client.run_forward_usage(
                io.StringIO(stdin), environ={"COMPASS_HOME": self.home}, port=port, now=NOW
            )
        return code, out.getvalue(), err.getvalue()

    def test_a_status_line_payload_is_posted_as_the_two_windows_and_nothing_else(self) -> None:
        bodies: list[Any] = []
        real_post = terminal_client.post

        def posted(port: int, path: str, body: Any, **kw: Any) -> Any:
            bodies.append((path, body))
            return real_post(port, path, body, **kw)

        answers: dict[str, tuple[int, dict[str, str], bytes]] = {
            "/api/usage/claude": (200, {}, b'{"ok":true,"usage":2}')
        }
        with (
            FakeDashboard(answers=answers) as fake,
            mock.patch.object(terminal_client, "post", posted),
        ):
            code, out, err = self.forward(json.dumps(both_windows()), fake.port)

        self.assertEqual((0, "", ""), (code, out, err))
        self.assertEqual([("POST", "/api/usage/claude")], fake.posts())
        (path, body) = bodies[0]
        self.assertEqual("/api/usage/claude", path)
        self.assertEqual(
            {
                "rate_limits": {
                    "five_hour": {"used_percentage": 42.5, "resets_at": FIVE_RESET},
                    "seven_day": {"used_percentage": 61, "resets_at": WEEK_RESET},
                }
            },
            body,
        )
        sent = json.dumps(body)
        for private in (SESSION_ID, TRANSCRIPT, CWD, "private", "Opus", "spend", "cost"):
            self.assertNotIn(private, sent)

    def test_malformed_or_oversized_stdin_sends_nothing_and_exits_0(self) -> None:
        oversized = json.dumps(
            {**both_windows(), "pad": "x" * (terminal_client.STDIN_CAP_CHARS + 1)}
        )
        for stdin in ("", "{not json", "[1, 2]", "null", oversized, json.dumps(payload())):
            with self.subTest(stdin=stdin[:20]), FakeDashboard() as fake:
                code, out, err = self.forward(stdin, fake.port)
                self.assertEqual((0, "", ""), (code, out, err))
                self.assertEqual([], fake.requests)

    def test_no_dashboard_running_is_silent_and_exits_0(self) -> None:
        code, out, err = self.forward(json.dumps(both_windows()))

        self.assertEqual((0, "", ""), (code, out, err))

    def test_a_refusal_or_an_old_dashboard_without_the_route_is_silent(self) -> None:
        for status in (403, 404, 413, 500):
            answers: dict[str, tuple[int, dict[str, str], bytes]] = {
                "/api/usage/claude": (status, {}, b"{}")
            }
            with self.subTest(status=status), FakeDashboard(answers=answers) as fake:
                code, out, err = self.forward(json.dumps(both_windows()), fake.port)
                self.assertEqual((0, "", ""), (code, out, err))
                self.assertEqual([("POST", "/api/usage/claude")], fake.posts())

    def test_it_never_starts_a_dashboard(self) -> None:
        with (
            mock.patch.object(terminal_client, "start_daemon") as start,
            mock.patch.object(terminal_client, "ensure_dashboard") as ensure,
        ):
            code, _, _ = self.forward(json.dumps(both_windows()))

        self.assertEqual(0, code)
        start.assert_not_called()
        ensure.assert_not_called()

    def test_a_dashboard_that_never_answers_costs_at_most_the_budget(self) -> None:
        # A listener that accepts and never replies is the worst case a status line can meet.
        with socket.socket() as hung:
            hung.bind(("127.0.0.1", 0))
            hung.listen(8)
            started = time.monotonic()
            code, out, err = self.forward(json.dumps(both_windows()), hung.getsockname()[1])
            spent = time.monotonic() - started

        self.assertEqual((0, "", ""), (code, out, err))
        self.assertLess(spent, terminal_client.FORWARD_BUDGET_SEC + 0.75)

    def test_a_raising_step_is_swallowed(self) -> None:
        with mock.patch.object(terminal_client, "candidate_ports", side_effect=RuntimeError("x")):
            code, out, err = self.forward(json.dumps(both_windows()))

        self.assertEqual((0, "", ""), (code, out, err))

    def test_the_newest_started_dashboard_receives_the_post(self) -> None:
        answers: dict[str, tuple[int, dict[str, str], bytes]] = {
            "/api/usage/claude": (200, {}, b'{"ok":true,"usage":2}')
        }
        with FakeDashboard(answers=answers) as older, FakeDashboard(answers=answers) as newer:
            newer._health = {"ok": True, "pid": 1, "port": newer.port, "started": 200.0}
            older._health = {"ok": True, "pid": 2, "port": older.port, "started": 100.0}
            ports = (older.port, newer.port)
            with mock.patch.object(terminal_client, "candidate_ports", return_value=ports):
                code, _, _ = self.forward(json.dumps(both_windows()))

        self.assertEqual(0, code)
        self.assertEqual([], older.posts())
        self.assertEqual([("POST", "/api/usage/claude")], newer.posts())


class ForwardUsageDispatchTest(unittest.TestCase):
    def test_a_lone_forward_usage_is_answered_without_the_cli(self) -> None:
        self.assertTrue(terminal_client.handles(["--forward-usage"]))
        with (
            mock.patch.object(terminal_client, "run_forward_usage", return_value=0) as forward,
            mock.patch("compass_runtime.cli.main") as main,
        ):
            self.assertEqual(0, entry.main(["--forward-usage"]))
        forward.assert_called_once()
        main.assert_not_called()

    def test_forward_usage_takes_no_session_or_value(self) -> None:
        for argv in (
            ["--forward-usage", "--session", "claude:one"],
            ["--forward-usage=yes"],
            ["--forward-usage", "--footer"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(terminal_client.handles(argv))

    def test_forward_usage_beside_another_option_is_a_usage_error_before_anything_acts(
        self,
    ) -> None:
        acted = AssertionError("a usage error must come before anything acts")
        for argv in (["--forward-usage", "--port", "4631"], ["--forward-usage", "--status"]):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as home:
                err = io.StringIO()
                with (
                    mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
                    contextlib.redirect_stderr(err),
                    mock.patch.object(cli, "build_runtime", side_effect=acted),
                    mock.patch.object(cli, "run_one_shot", side_effect=acted),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cli.main(argv)
                self.assertEqual(2, raised.exception.code)
                self.assertIn("--forward-usage", err.getvalue())


class ForwardUsageLightPathTest(unittest.TestCase):
    """Through `server.py` as a status line runs it: silent, exit 0, and no dashboard code loaded."""

    def test_the_command_loads_neither_the_cli_nor_the_server(self) -> None:
        # The subprocess finds dashboards the real way, and the default port is where a person's
        # own board listens. Every window here reset in 2023, so the command sends nothing to it.
        self.assertEqual({}, terminal_client.forwarded_windows(both_windows(), time.time()))
        with tempfile.TemporaryDirectory() as home:
            done = subprocess.run(
                [sys.executable, "-X", "importtime", str(SERVER_PATH), "--forward-usage"],
                input=json.dumps(both_windows()),
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
                env={**os.environ, "COMPASS_HOME": home, "PYTHONDONTWRITEBYTECODE": "1"},
            )

        self.assertEqual((0, ""), (done.returncode, done.stdout))
        loaded = [
            name
            for name in (
                "compass_runtime.cli",
                "compass_runtime.http_api",
                "compass_runtime.aggregate",
            )
            if f" {name}\n" in done.stderr
        ]
        self.assertEqual([], loaded)
        # Nothing but the interpreter's own import timings reaches stderr.
        self.assertEqual(
            [], [line for line in done.stderr.splitlines() if "import time:" not in line]
        )


class ForwardUsageEndToEndTest(RuntimeTestCase):
    """Through the real route: the board holds the two windows and nothing that identifies."""

    def test_a_forwarded_reading_reaches_the_board_and_names_nothing(self) -> None:
        application = build_app()
        httpd = make_server(application=application)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        now = time.time()
        body = payload(
            five_hour={"used_percentage": 42, "resets_at": now + 3_600},
            seven_day={"used_percentage": 61, "resets_at": now + 4 * 86_400},
        )
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = terminal_client.run_forward_usage(
                    io.StringIO(json.dumps(body)), environ={}, port=httpd.server_port
                )
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

        self.assertEqual((0, ""), (code, out.getvalue()))
        (entry_,) = quota.claude_receipt_entries(
            application.config, application.state, time.time(), 24
        )
        self.assertEqual("claude", entry_["harness"])
        self.assertEqual(42, entry_["fiveH"]["pct"])
        self.assertEqual(61, entry_["week"]["pct"])
        stored = json.dumps(application.state.usage_receipts)
        for private in (SESSION_ID, TRANSCRIPT, CWD, "private", "Opus"):
            self.assertNotIn(private, stored)


if __name__ == "__main__":
    unittest.main()
