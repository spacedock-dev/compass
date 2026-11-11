"""Release lookups are daily, silent, bounded and explicitly marked."""

from __future__ import annotations

import contextlib
import errno
import http.client
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import (
    cli,
    config,
    entry,
    frontend_dev,
    lifecycle,
    reach,
    settings,
    terminal_client,
    update_check,
)
from compass_runtime import io as runtime_io

from . import support
from .support import REAL_FETCH_RELEASE, SERVER_PATH, make_config, make_runtime, serve_until_closed
from .test_cli_version import run_main

REAL_TIME_TESTS = True  # Measures the DNS and whole-exchange timeout against wall time.


class DailyCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config = make_config(
            state_home=home.name, release_version="2.8.0", update_check_disabled=False
        )
        self.now = datetime(2026, 11, 10, 23, 59, 59, tzinfo=UTC).timestamp()

    def checker(self) -> update_check.UpdateChecker:
        return update_check.UpdateChecker(self.config, clock=lambda: self.now)

    def test_a_running_server_checks_on_the_first_tick_after_utc_midnight(self) -> None:
        with mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch:
            check = self.checker()
            check.tick()
            check.tick()
            self.assertEqual(fetch.call_count, 1)
            self.now += 2
            check.tick()
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            update_check.published(self.config), {"version": "2.9.0", "checked_at": self.now}
        )

    def test_a_server_paused_across_midnight_cannot_replace_todays_reservation(self) -> None:
        original = os.makedirs
        crossed = False

        def delayed(path: str, *, mode: int, exist_ok: bool) -> None:
            nonlocal crossed
            original(path, mode=mode, exist_ok=exist_ok)
            if not crossed:
                crossed = True
                self.now += 2
                self.checker().tick()

        with (
            mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch,
            mock.patch.object(os, "makedirs", side_effect=delayed),
        ):
            self.checker().tick()
            self.checker().tick()
        self.assertEqual(fetch.call_count, 1)
        stored = json.loads(Path(self.config.state_home, update_check.STORE_FILENAME).read_text())
        self.assertEqual(stored["attempt_day"], "2026-11-11")

    def test_two_starts_in_one_day_make_one_attempt(self) -> None:
        with mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch:
            self.checker().tick()
            self.checker().tick()
        self.assertEqual(fetch.call_count, 1)

    def test_two_servers_sharing_a_home_make_one_attempt(self) -> None:
        gate = threading.Barrier(2)

        def tick() -> None:
            gate.wait()
            self.checker().tick()

        with (
            mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch,
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            list(pool.map(lambda _: tick(), range(2)))
        self.assertEqual(fetch.call_count, 1)

    def test_a_failed_attempt_is_not_retried_and_keeps_the_last_answer(self) -> None:
        with mock.patch.object(update_check, "fetch_release", return_value="2.9.0"):
            self.checker().tick()
        success = update_check.published(self.config)
        self.now += 86400
        with mock.patch.object(update_check, "fetch_release", side_effect=OSError) as fetch:
            self.checker().tick()
            self.checker().tick()
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(update_check.published(self.config), success)

    def test_the_attempt_is_saved_before_the_request(self) -> None:
        def fetch(_config: config.RuntimeConfig) -> str:
            stored = json.loads(
                Path(self.config.state_home, update_check.STORE_FILENAME).read_text()
            )
            self.assertEqual(stored["attempt_day"], "2026-11-10")
            return "2.9.0"

        with mock.patch.object(update_check, "fetch_release", side_effect=fetch):
            self.checker().tick()

    def test_either_off_switch_sends_nothing(self) -> None:
        with mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch:
            update_check.UpdateChecker(replace(self.config, update_check_disabled=True)).tick()
            settings.save(self.config, {"no_update_check": True})
            self.checker().tick()
        fetch.assert_not_called()
        self.assertFalse(Path(self.config.state_home, update_check.STORE_FILENAME).exists())

    def test_unreadable_preferences_fail_closed_without_breaking_reading_defaults(self) -> None:
        for raw in (
            b'{"no_update_check":true',
            b"[]",
            b"\xff",
            b" " * 4097,
            b'{"no_update_check": "false"}',
        ):
            with self.subTest(raw=raw[:30]):
                Path(settings.store_path(self.config)).write_bytes(raw)
                with mock.patch.object(
                    update_check, "fetch_release", return_value="2.9.0"
                ) as fetch:
                    self.checker().tick()
                fetch.assert_not_called()
                self.assertEqual(settings.load(self.config), settings.DEFAULTS)
        with (
            mock.patch.object(settings, "_read_store", side_effect=PermissionError),
            mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch,
        ):
            self.checker().tick()
        fetch.assert_not_called()

    def test_saving_reading_limits_cannot_erase_an_unreadable_opt_out(self) -> None:
        Path(settings.store_path(self.config)).write_text('{"no_update_check":true')
        settings.save(self.config, {"analyze_record_events": 4000})
        with mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch:
            self.checker().tick()
        fetch.assert_not_called()
        self.assertEqual(settings.load(self.config).analyze_record_events, 4000)

    def test_existing_invalid_attempt_state_is_never_reinitialized(self) -> None:
        path = Path(self.config.state_home, update_check.STORE_FILENAME)
        for raw in (
            "{",
            "[]",
            "{}",
            '{"attempt_day":"invalid"}',
            '{"attempt_day":123}',
            '{"version":"2.9.0"}',
        ):
            with self.subTest(raw=raw):
                path.write_text(raw)
                with mock.patch.object(
                    update_check, "fetch_release", return_value="2.9.0"
                ) as fetch:
                    self.checker().tick()
                fetch.assert_not_called()
                self.assertEqual(path.read_text(), raw)
        with (
            mock.patch.object(os, "open", side_effect=PermissionError),
            mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch,
        ):
            self.checker().tick()
        fetch.assert_not_called()

    def test_nonfinite_saved_timestamps_are_not_published(self) -> None:
        path = Path(self.config.state_home, update_check.STORE_FILENAME)
        for value in ("1e999", "NaN", "-Infinity", "1" + "0" * 400):
            with self.subTest(value=value):
                path.write_text('{"version":"999.0.0","checked_at":' + value + "}")
                self.assertIsNone(update_check.published(self.config))

    def test_an_unwritable_attempt_store_sends_nothing(self) -> None:
        with (
            mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError),
            mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch,
        ):
            self.checker().tick()
        fetch.assert_not_called()

    def test_only_a_newer_stable_release_draws_a_notice(self) -> None:
        for version, expected in (
            ("2.8.0", False),
            ("2.7.99", False),
            ("2.10.0", True),
            ("2.9.0-rc.1", False),
        ):
            with self.subTest(version=version):
                self.now += 86400
                with mock.patch.object(update_check, "fetch_release", return_value=version):
                    self.checker().tick()
                self.assertEqual(update_check.published(self.config) is not None, expected)

    def test_the_background_check_does_not_delay_the_serving_loop(self) -> None:
        entered, release = threading.Event(), threading.Event()
        stop = threading.Event()
        threads: list[threading.Thread] = []
        original = threading.Thread

        def tracked(*args: object, **kwargs: object) -> threading.Thread:
            thread = original(*args, **kwargs)  # type: ignore[arg-type]
            threads.append(thread)
            return thread

        def fetch(_config: config.RuntimeConfig) -> str:
            entered.set()
            release.wait(2)
            return "2.9.0"

        try:
            with (
                mock.patch.object(update_check, "fetch_release", side_effect=fetch),
                mock.patch.object(threading, "Thread", side_effect=tracked),
            ):
                update_check.start(self.config, stop)
                self.assertTrue(entered.wait(1))
                self.assertFalse(release.is_set())
                # Startup returned while the endpoint is still waiting for an answer.
        finally:
            stop.set()
            release.set()
            for thread in threads:
                thread.join(2)

    def test_a_running_ticker_checks_again_after_midnight_without_a_restart(self) -> None:
        stop = mock.Mock(spec=threading.Event)
        stop.is_set.return_value = False

        def wait(_period: float) -> bool:
            self.now += 2
            return self.now > datetime(2026, 11, 11, 0, 0, 1, tzinfo=UTC).timestamp()

        stop.wait.side_effect = wait
        with mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch:
            update_check.run(self.config, stop, clock=lambda: self.now)
        self.assertEqual(fetch.call_count, 2)

    def test_invalid_clock_timestamps_keep_the_ticker_running_and_send_nothing(self) -> None:
        for value, error in (
            (float("inf"), None),
            (-1.0, OSError),
            (-1.0, ValueError),
            (-1.0, OverflowError),
        ):
            with self.subTest(value=value, error=error):
                self.now = value
                stop = mock.Mock(spec=threading.Event)
                stop.is_set.return_value = False
                stop.wait.side_effect = [False, True]
                with (
                    mock.patch.object(update_check, "datetime", wraps=datetime) as dates,
                    mock.patch.object(update_check, "fetch_release") as fetch,
                ):
                    dates.fromtimestamp.side_effect = error
                    update_check.run(self.config, stop, clock=lambda: self.now)
                self.assertEqual(stop.wait.call_count, 2)
                fetch.assert_not_called()
                self.assertFalse(Path(self.config.state_home, update_check.STORE_FILENAME).exists())

    def test_the_saved_off_switch_survives_other_settings_writes_and_restart(self) -> None:
        settings.save(self.config, {"no_update_check": True})
        settings.save(self.config, {"analyze_record_events": 4000})
        self.assertTrue(settings.no_update_check(self.config))
        with mock.patch.object(update_check, "fetch_release", return_value="2.9.0") as fetch:
            self.checker().tick()
        fetch.assert_not_called()
        settings.save(self.config, {"no_update_check": None})
        self.assertFalse(settings.no_update_check(self.config))
        self.assertEqual(settings.load(self.config).analyze_record_events, 4000)
        for value in (0, 1, "true", ["wrong"]):
            with self.subTest(value=value), self.assertRaises(settings.InvalidSettingError):
                settings.save(self.config, {"no_update_check": value})


class StartupHintTest(unittest.TestCase):
    def test_hint_requires_all_switches_and_a_published_notice(self) -> None:
        cfg = make_config(update_check_disabled=False)
        hint = "Compass 9.9.9 is available. Update Compass through your installer.\n"
        for enabled, disabled, saved, notice, expected in (
            (True, False, False, {"version": "9.9.9", "checked_at": 1}, hint),
            (False, False, False, {"version": "9.9.9", "checked_at": 1}, ""),
            (True, True, False, {"version": "9.9.9", "checked_at": 1}, ""),
            (True, False, True, {"version": "9.9.9", "checked_at": 1}, ""),
            (True, False, False, None, ""),
        ):
            out, err = io.StringIO(), io.StringIO()
            with (
                self.subTest(enabled=enabled, disabled=disabled, saved=saved, notice=notice),
                mock.patch.object(config, "UPDATE_CHECK_DEFAULT_ENABLED", enabled),
                mock.patch.object(settings, "no_update_check", return_value=saved),
                mock.patch.object(update_check, "published", return_value=notice),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                update_check.print_startup_hint(replace(cfg, update_check_disabled=disabled))
                self.assertEqual((out.getvalue(), err.getvalue()), (expected, ""))

    def test_hint_reads_only_a_valid_newer_stable_cached_version(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            cfg = make_config(state_home=home, release_version="2.8.0", update_check_disabled=False)
            cache = Path(home, update_check.STORE_FILENAME)
            for raw, expected in (
                (None, ""),
                ("{", ""),
                ("[]", ""),
                ('{"version":"2.8.0","checked_at":1}', ""),
                ('{"version":"2.7.99","checked_at":1}', ""),
                ('{"version":"2.9.0-rc.1","checked_at":1}', ""),
                ('{"version":"2.9.0","checked_at":false}', ""),
                ('{"version":"2.9.0\\u001b[31m","checked_at":1}', ""),
                (
                    '{"version":"v2.9.0","checked_at":1}',
                    "Compass 2.9.0 is available. Update Compass through your installer.\n",
                ),
            ):
                with self.subTest(raw=raw):
                    if raw is not None:
                        cache.write_text(raw, encoding="utf-8")
                    out, err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        update_check.print_startup_hint(cfg)
                    self.assertEqual((out.getvalue(), err.getvalue()), (expected, ""))


class StartupEntryPointTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, self.state = make_runtime(
            state_home=home.name, release_version="2.8.0", update_check_disabled=False
        )
        Path(home.name, update_check.STORE_FILENAME).write_text(
            '{"version":"9.9.9","checked_at":1}', encoding="utf-8"
        )
        self.hint = "Compass 9.9.9 is available. Update Compass through your installer.\n"
        self.enterContext(
            mock.patch.object(cli, "build_runtime", return_value=(self.config, self.state))
        )
        self.enterContext(mock.patch.object(lifecycle, "serve"))

    def test_failed_assets_or_bind_print_no_hint(self) -> None:
        for stage in ("page", "development", "bind"):
            with self.subTest(stage=stage), contextlib.ExitStack() as stack:
                argv = ["--no-events", "--no-focus"]
                if stage == "page":
                    stack.enter_context(
                        mock.patch.object(cli, "load_frontend_page", return_value=None)
                    )
                elif stage == "development":
                    argv.extend(["--frontend-dev-manifest", "missing.json"])
                    stack.enter_context(
                        mock.patch.object(
                            frontend_dev, "admit", side_effect=RuntimeError("invalid")
                        )
                    )
                else:
                    stack.enter_context(
                        mock.patch.object(
                            cli, "build_server", side_effect=OSError(errno.EADDRINUSE, "busy")
                        )
                    )
                code, out, _ = run_main(*argv)
                self.assertEqual(code, 1)
                self.assertNotIn(self.hint.strip(), out)

    def test_foreground_start_prints_once_after_binding(self) -> None:
        with mock.patch.object(cli, "build_server") as bind:
            bind.side_effect = lambda *_args, **_kwargs: self.assertNotIn(
                self.hint.strip(), cast("io.StringIO", sys.stdout).getvalue()
            )
            code, out, err = run_main("--no-events", "--no-focus")
        self.assertEqual((code, out, err), (0, self.hint, ""))

    def test_short_operations_stay_quiet_with_an_enabled_cached_notice(self) -> None:
        with (
            mock.patch.dict(
                os.environ,
                {"COMPASS_HOME": self.config.state_home, "CLAUDE_CODE_SESSION_ID": "test"},
                clear=True,
            ),
            mock.patch.object(lifecycle, "probe_port", return_value=("none", None)),
            mock.patch.object(
                terminal_client,
                "ensure_dashboard",
                return_value=terminal_client.Refusal("No dashboard is running.", 1),
            ),
        ):
            for operation, expected in (
                ("--status", 1),
                ("--version", 0),
                ("--sessions", 1),
                ("--drift", 1),
                ("--goal", 1),
                ("--summary", 1),
            ):
                with self.subTest(operation=operation):
                    code, out, err = run_main(operation)
                    self.assertEqual(code, expected)
                    self.assertNotIn(self.hint.strip(), out + err)

    def test_posix_daemon_hint_belongs_only_to_a_successful_parent(self) -> None:
        for role, code, expected in (
            ("parent", 0, self.hint),
            ("parent", 1, ""),
            ("daemon", 0, ""),
        ):
            with (
                self.subTest(role=role, code=code),
                mock.patch.object(cli, "build_server"),
                mock.patch.object(lifecycle, "fork_daemon", return_value=(role, 123)),
                mock.patch.object(
                    lifecycle, "await_daemon", return_value=("ready or failed", code)
                ),
                mock.patch.object(lifecycle, "daemon_redirect_stdio"),
            ):
                result, out, _ = run_main("--daemon", "--no-events", "--no-focus")
                self.assertEqual(result, code)
                self.assertEqual(out.count(self.hint), int(bool(expected)))

    def test_windows_respawn_never_logs_a_hint_and_only_success_announces_one(self) -> None:
        windows = replace(self.config, os_name="nt")

        def spawn(_argv: list[str], **kwargs: Any) -> mock.Mock:
            # Run the child entry point with the exact environment and log handle
            # supplied to Popen; only the OS process creation and bind are faked.
            log = io.TextIOWrapper(kwargs["stdout"], encoding="utf-8", write_through=True)
            try:
                with (
                    mock.patch.dict(os.environ, kwargs.get("env", os.environ), clear=True),
                    contextlib.redirect_stdout(log),
                    contextlib.redirect_stderr(log),
                ):
                    child_code = cli.main(_argv[2:])
            finally:
                log.detach()
            proc = mock.Mock(pid=99, returncode=child_code)
            proc.poll.return_value = child_code or None
            return proc

        for failed in (False, True):
            log_path = Path(self.config.state_home, "compass-4553.log")
            log_path.write_text("", encoding="utf-8")
            with (
                self.subTest(failed=failed),
                mock.patch.object(cli, "build_runtime", return_value=(windows, self.state)),
                mock.patch.object(
                    cli,
                    "build_server",
                    side_effect=OSError(errno.EADDRINUSE, "busy") if failed else None,
                ),
                mock.patch.object(subprocess, "Popen", side_effect=spawn),
                mock.patch.object(
                    lifecycle,
                    "probe_port",
                    return_value=("none", None) if failed else ("compass", {"pid": 99}),
                ),
            ):
                code, out, err = run_main("--daemon", "--no-events", "--no-focus")
                self.assertEqual(code, int(failed))
                self.assertEqual(out.count(self.hint), int(not failed))
                self.assertNotIn(self.hint.strip(), err + log_path.read_text())


class StartupNoticeTest(unittest.TestCase):
    def test_dashboard_start_prints_a_cached_hint_once_and_honours_opt_outs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            env = {**os.environ, "CI": "1", "COMPASS_HOME": tmp}
            cache = home / "compass-update-check.json"
            cache.write_text(
                json.dumps(
                    {
                        "attempt_day": datetime.now(UTC).date().isoformat(),
                        "version": "9.9.9",
                        "checked_at": 1794355200,
                    }
                ),
                encoding="utf-8",
            )

            def run(*args: str) -> subprocess.CompletedProcess[str]:
                # Today's saved attempt prevents a request. Restore real Popen so the
                # suite's guard cannot append --no-update-check to this opt-in proof.
                with mock.patch.object(subprocess.Popen, "__init__", support._REAL_POPEN_INIT):
                    return subprocess.run(
                        [sys.executable, str(SERVER_PATH), "--port", str(port), *args],
                        env=env,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=60,
                    )

            hint = "Compass 9.9.9 is available. Update Compass through your installer.\n"
            for mode in ("enabled", "flag", "saved"):
                with self.subTest(mode=mode):
                    (home / "compass-settings.json").write_text(
                        json.dumps({"no_update_check": mode == "saved"}), encoding="utf-8"
                    )
                    before = cache.read_bytes()
                    flags = [
                        "--daemon",
                        "--no-observer-model",
                        "--no-usage",
                        "--no-git",
                        "--no-ci-read",
                        "--no-focus",
                        "--no-events",
                        "--no-spacedock",
                        "--no-tripwires",
                        "--no-reach",
                        "--no-ask",
                        "--no-history",
                    ]
                    if mode == "flag":
                        flags.append("--no-update-check")
                    try:
                        start = run(*flags)
                        self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
                        self.assertEqual(
                            start.stdout.count(hint),
                            int(mode == "enabled"),
                            repr(start.stdout) + repr(start.stderr),
                        )
                        self.assertNotIn(hint.strip(), start.stderr)
                        self.assertNotIn(hint.strip(), (home / f"compass-{port}.log").read_text())
                        if mode == "enabled":
                            status = run("--status")
                            self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
                            self.assertNotIn(hint.strip(), status.stdout + status.stderr)
                            version = run("--version")
                            self.assertEqual(
                                version.stdout,
                                json.loads(
                                    (
                                        SERVER_PATH.parents[2] / ".claude-plugin/plugin.json"
                                    ).read_text()
                                )["version"]
                                + "\n",
                            )
                        self.assertEqual(cache.read_bytes(), before)
                    finally:
                        run("--stop")


class InternalMarkerTest(unittest.TestCase):
    def test_the_command_persists_the_flag_and_the_environment_overrides_off(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"HOME": home, "COMPASS_HOME": home}, clear=True),
        ):
            self.assertEqual(run_main("--internal"), (0, "off\n", ""))
            self.assertEqual(run_main("--internal", "on"), (0, "on\n", ""))
            self.assertEqual(run_main("--internal"), (0, "on\n", ""))
            self.assertEqual(run_main("--internal", "off"), (0, "off\n", ""))
            with mock.patch.dict(os.environ, {"SPACEDOCK_INTERNAL": "1"}):
                self.assertEqual(run_main("--internal"), (0, "on\n", ""))
            self.assertEqual(run_main("--internal"), (0, "off\n", ""))

    def test_the_cli_off_switch_reaches_runtime_configuration(self) -> None:
        args = cli.build_parser().parse_args(["--no-update-check"])
        built, _ = cli.build_runtime(args, started=1)
        self.assertTrue(built.update_check_disabled)

    def test_the_entry_point_forwards_the_off_switch_to_automatic_drift_startup(self) -> None:
        for argv in (["--no-update-check", "--drift"], ["--drift", "--no-update-check"]):
            with (
                self.subTest(argv=argv),
                mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "test"}, clear=True),
                mock.patch.object(terminal_client, "find_dashboard", return_value=None),
                mock.patch(
                    "subprocess.run", return_value=subprocess.CompletedProcess([], 0)
                ) as run,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(entry.main(argv), 1)
                self.assertIn("--no-update-check", run.call_args.args[0])

    def test_a_development_version_is_not_an_internal_marker(self) -> None:
        cfg = make_config(release_version="2.8.0+dev", update_check_internal_env=False)
        with mock.patch.object(update_check, "_read", return_value={}):
            self.assertFalse(update_check.internal(cfg))

    def test_automatic_terminal_starts_forward_the_update_opt_out(self) -> None:
        for operation in (
            ["--monitor"],
            ["--summary"],
            ["--summary", "--update"],
            ["--summary", "--again"],
            ["--goal", "my goal"],
            ["--goal", "--clear"],
            ["--goal", "--adopt"],
            ["--summary", "--port", "4554"],
            ["--goal", "my goal", "--port=4554"],
        ):
            for before in (True, False):
                arguments = [*operation, "--session", "claude:one"]
                argv = (
                    ["--no-update-check", *arguments]
                    if before
                    else [*arguments, "--no-update-check"]
                )
                with (
                    self.subTest(argv=argv),
                    tempfile.TemporaryDirectory() as home,
                    mock.patch.dict(os.environ, {"COMPASS_HOME": home}, clear=True),
                    mock.patch.object(sys.stdout, "isatty", return_value=True),
                    mock.patch.object(terminal_client, "find_dashboard", return_value=None),
                    mock.patch(
                        "subprocess.run", return_value=subprocess.CompletedProcess([], 0)
                    ) as run,
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(entry.main(argv), 1)
                    command = run.call_args.args[0]
                    self.assertIn("--no-update-check", command)
                    self.assertIn("--daemon", command)


class LocalTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.status = 200
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.calls.append((self.path, dict(self.headers.items())))
                body = json.dumps({"tag_name": "v2.9.0"}).encode()
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                if owner.status == 302:
                    self.send_header("Location", "/redirected")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        serve_until_closed(server)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_port
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config = make_config(
            state_home=home.name,
            update_check_disabled=False,
            release_version="2.8.0+dev",
            platform_name="win32",
            update_check_arch="AMD64",
        )

        class LocalHTTPS(urllib.request.HTTPSHandler):
            handler_order = 100

            # Only this fake endpoint speaks HTTP under an HTTPS address. The production opener's
            # redirect handler and request bytes still run unchanged over a real local socket.
            def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
                return self.do_open(http.client.HTTPConnection, req)

        opener = reach.build_reach_opener()
        opener.add_handler(LocalHTTPS())
        self.patch = mock.patch(
            "compass_runtime.update_check.build_reach_opener", return_value=opener
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        url = mock.patch.object(
            update_check, "RELEASE_URL", f"https://127.0.0.1:{self.port}/latest-release/compass"
        )
        url.start()
        self.addCleanup(url.stop)

    def test_the_request_carries_exactly_the_disclosed_fields_and_user_agent(self) -> None:
        self.assertEqual(REAL_FETCH_RELEASE(self.config), "2.9.0")
        path, headers = self.calls[0]
        self.assertEqual(
            path,
            "/latest-release/compass",
        )
        self.assertEqual(headers.pop("User-Agent"), "compass/2.8.0+dev (windows; amd64)")
        self.assertEqual(
            headers,
            {
                "Accept-Encoding": "identity",
                "Host": f"127.0.0.1:{self.port}",
                "Connection": "close",
            },
        )
        update_check.save_internal(self.config, True)
        self.assertEqual(REAL_FETCH_RELEASE(self.config), "2.9.0")
        self.assertEqual(
            self.calls[-1][1]["User-Agent"], "compass/2.8.0+dev (windows; amd64; internal)"
        )

    def test_a_redirect_is_never_followed(self) -> None:
        self.status = 302
        with self.assertRaises(OSError):
            REAL_FETCH_RELEASE(self.config)
        self.assertEqual(len(self.calls), 1)

    def test_a_non_https_target_is_refused_before_any_connection(self) -> None:
        with (
            mock.patch.object(update_check, "RELEASE_URL", f"http://127.0.0.1:{self.port}/"),
            self.assertRaises(ValueError),
        ):
            REAL_FETCH_RELEASE(self.config)
        self.assertEqual(self.calls, [])

    def test_a_closed_port_is_silent_and_not_retried(self) -> None:
        with ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler) as closed:
            port = closed.server_port
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(update_check, "RELEASE_URL", f"https://127.0.0.1:{port}/"),
            mock.patch.object(update_check, "fetch_release", REAL_FETCH_RELEASE),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            update_check.UpdateChecker(self.config).tick()
            update_check.UpdateChecker(self.config).tick()
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))
        self.assertIsNone(update_check.published(self.config))


class RequestValuesTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = home.name

    def test_the_shipped_default_starts_the_background_worker(self) -> None:
        built = make_config(release_version="2.8.0+dev", update_check_disabled=False)
        stop = threading.Event()
        with mock.patch.object(threading, "Thread") as thread:
            update_check.start(built, stop)
        thread.assert_called_once_with(target=update_check.run, args=(built, stop), daemon=True)
        thread.return_value.start.assert_called_once_with()

    def test_the_cli_off_switch_starts_no_worker(self) -> None:
        with mock.patch.object(threading, "Thread") as thread:
            update_check.start(make_config(update_check_disabled=True), threading.Event())
        thread.assert_not_called()

    def test_the_lookup_is_a_plain_get_without_query_fields(self) -> None:
        req = update_check.request(make_config(release_version="2.9.1"))
        self.assertEqual(req.full_url, "https://spacedock.md/latest-release/compass")
        self.assertEqual(req.get_method(), "GET")

    def test_the_user_agent_contains_only_the_client_version_and_platform(self) -> None:
        req = update_check.request(
            make_config(release_version="2.9.1", platform_name="darwin", update_check_arch="arm64")
        )
        self.assertEqual(req.header_items(), [("User-agent", "compass/2.9.1 (darwin; arm64)")])

    def test_a_leading_v_is_removed_from_the_installed_version(self) -> None:
        req = update_check.request(
            make_config(release_version="v2.9.1", platform_name="darwin", update_check_arch="arm64")
        )
        self.assertEqual(req.get_header("User-agent"), "compass/2.9.1 (darwin; arm64)")

    def test_an_unavailable_or_invalid_version_is_unknown(self) -> None:
        for version in (
            None,
            "",
            "unknown",
            "vv2.9.1",
            "2.9.1 (extra)",
            "2.9.1\r\nX: injected",
            "1.0.0-alpha.beta.gamma.delta.epsilon",
        ):
            with self.subTest(version=version):
                req = update_check.request(
                    make_config(
                        release_version=version, platform_name="linux", update_check_arch="x64"
                    )
                )
                self.assertEqual(req.get_header("User-agent"), "compass/unknown (linux; amd64)")

    def test_ci_only_adds_a_token_for_the_four_ascii_truth_values(self) -> None:
        for value, expected in (
            ("true", "compass/2.9.1 (linux; amd64; ci)"),
            (" TRUE ", "compass/2.9.1 (linux; amd64; ci)"),
            ("1", "compass/2.9.1 (linux; amd64; ci)"),
            ("yes", "compass/2.9.1 (linux; amd64; ci)"),
            ("ON", "compass/2.9.1 (linux; amd64; ci)"),
            ("false", "compass/2.9.1 (linux; amd64)"),
            ("0", "compass/2.9.1 (linux; amd64)"),
            ("", "compass/2.9.1 (linux; amd64)"),
            ("\u00a0true\u00a0", "compass/2.9.1 (linux; amd64)"),
        ):
            with (
                self.subTest(value=value),
                mock.patch.dict(os.environ, {"CI": value, "COMPASS_HOME": self.home}, clear=True),
            ):
                args = cli.build_parser().parse_args([])
                built, _ = cli.build_runtime(args, started=1)
                req = update_check.request(
                    replace(
                        built,
                        release_version="2.9.1",
                        platform_name="linux",
                        update_check_arch="x64",
                    )
                )
                self.assertEqual(req.get_header("User-agent"), expected)

    def test_the_saved_internal_flag_adds_only_the_internal_token(self) -> None:
        cfg = make_config(
            state_home=self.home,
            release_version="2.9.1",
            platform_name="darwin",
            update_check_arch="arm64",
        )
        update_check.save_internal(cfg, True)
        self.assertEqual(
            update_check.request(cfg).get_header("User-agent"),
            "compass/2.9.1 (darwin; arm64; internal)",
        )

    def test_the_internal_environment_override_requires_exactly_one(self) -> None:
        for value, expected in (
            ("1", "compass/2.9.1 (darwin; arm64; internal)"),
            ("true", "compass/2.9.1 (darwin; arm64)"),
            (" 1 ", "compass/2.9.1 (darwin; arm64)"),
            ("0", "compass/2.9.1 (darwin; arm64)"),
        ):
            with (
                self.subTest(value=value),
                mock.patch.dict(
                    os.environ, {"SPACEDOCK_INTERNAL": value, "COMPASS_HOME": self.home}, clear=True
                ),
            ):
                args = cli.build_parser().parse_args([])
                built, _ = cli.build_runtime(args, started=1)
                req = update_check.request(
                    replace(
                        built,
                        release_version="2.9.1",
                        platform_name="darwin",
                        update_check_arch="arm64",
                    )
                )
                self.assertEqual(req.get_header("User-agent"), expected)

    def test_ci_precedes_internal_when_both_markers_are_set(self) -> None:
        req = update_check.request(
            make_config(
                release_version="2.9.1",
                platform_name="darwin",
                update_check_arch="arm64",
                update_check_ci=True,
                update_check_internal_env=True,
            )
        )
        self.assertEqual(
            req.get_header("User-agent"), "compass/2.9.1 (darwin; arm64; ci; internal)"
        )

    def test_prerelease_and_build_suffixes_are_preserved_without_marking_internal(self) -> None:
        req = update_check.request(
            make_config(
                release_version="v2.9.1-rc.1+dev", platform_name="linux", update_check_arch="x64"
            )
        )
        self.assertEqual(req.get_header("User-agent"), "compass/2.9.1-rc.1+dev (linux; amd64)")

    def test_os_values_match_the_shared_mapping_in_the_user_agent(self) -> None:
        for source, expected in (
            ("darwin", "compass/2.9.1 (darwin; arm64)"),
            ("Darwin", "compass/2.9.1 (darwin; arm64)"),
            ("LINUX", "compass/2.9.1 (linux; arm64)"),
            ("win32", "compass/2.9.1 (windows; arm64)"),
            ("WINDOWS", "compass/2.9.1 (windows; arm64)"),
            ("MINGW64_NT-10.0", "compass/2.9.1 (windows; arm64)"),
            ("MINGW32_NT-10.0", "compass/2.9.1 (windows; arm64)"),
            ("MSYS_NT-10.0", "compass/2.9.1 (windows; arm64)"),
            ("freebsd", "compass/2.9.1 (freebsd; arm64)"),
            ("freebsd13", "compass/2.9.1 (freebsd; arm64)"),
            ("freebsd14", "compass/2.9.1 (freebsd; arm64)"),
            ("FreeBSD", "compass/2.9.1 (freebsd; arm64)"),
            ("plan9", "compass/2.9.1 (unknown; arm64)"),
        ):
            with self.subTest(source=source):
                req = update_check.request(
                    make_config(
                        release_version="2.9.1", platform_name=source, update_check_arch="arm64"
                    )
                )
                self.assertEqual(req.get_header("User-agent"), expected)

    def test_arch_values_match_the_shared_mapping_in_the_user_agent(self) -> None:
        for source, expected in (
            ("AMD64", "compass/2.9.1 (linux; amd64)"),
            ("x86_64", "compass/2.9.1 (linux; amd64)"),
            ("x64", "compass/2.9.1 (linux; amd64)"),
            ("aarch64", "compass/2.9.1 (linux; arm64)"),
            ("ARM64", "compass/2.9.1 (linux; arm64)"),
            ("i686", "compass/2.9.1 (linux; unknown)"),
        ):
            with self.subTest(source=source):
                req = update_check.request(
                    make_config(
                        release_version="2.9.1", platform_name="linux", update_check_arch=source
                    )
                )
                self.assertEqual(req.get_header("User-agent"), expected)


class MemoryTransportTest(unittest.TestCase):
    """A byte-level HTTP endpoint for runners that cannot bind a loopback socket."""

    def setUp(self) -> None:
        self.sent: list[bytes] = []
        self.status = 200
        owner = self

        class Endpoint:
            def sendall(self, data: bytes) -> None:
                owner.sent.append(data)

            def makefile(self, _mode: str) -> io.BytesIO:
                body = b'{"tag_name":"v2.9.0"}'
                return io.BytesIO(
                    f"HTTP/1.1 {owner.status} Answer\r\nContent-Length: {len(body)}\r\n"
                    "Location: https://must-not-be-reached.invalid/\r\n\r\n".encode()
                    + body
                )

            def close(self) -> None:
                pass

        class Connection(http.client.HTTPConnection):
            def connect(self) -> None:
                self.sock = cast("socket.socket", Endpoint())

        class Handler(urllib.request.HTTPSHandler):
            handler_order = 100

            def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
                return self.do_open(Connection, req)

        opener = reach.build_reach_opener()
        opener.add_handler(Handler())
        self.config = make_config(
            release_version="2.8.0+dev", platform_name="win32", update_check_arch="AMD64"
        )
        patch = mock.patch("compass_runtime.update_check.build_reach_opener", return_value=opener)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_urllib_wire_has_only_the_disclosed_fields_and_headers(self) -> None:
        self.assertEqual(REAL_FETCH_RELEASE(self.config), "2.9.0")
        self.assertEqual(
            self.sent,
            [
                (
                    b"GET /latest-release/compass HTTP/1.1\r\n"
                    b"Accept-Encoding: identity\r\nHost: spacedock.md\r\nUser-Agent: compass/2.8.0+dev (windows; amd64)\r\nConnection: close\r\n\r\n"
                )
            ],
        )

    def test_a_redirect_never_sends_a_second_request(self) -> None:
        self.status = 302
        with self.assertRaises(OSError):
            REAL_FETCH_RELEASE(self.config)
        self.assertEqual(len(self.sent), 1)


class ExchangeDeadlineTest(unittest.TestCase):
    def test_a_stalled_dns_lookup_expires_before_any_connection(self) -> None:
        release = threading.Event()
        finished = threading.Event()

        def resolve(*_args: object, **_kwargs: object) -> list[object]:
            try:
                release.wait(2)
                return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443))]
            finally:
                finished.set()

        began = time.monotonic()
        with mock.patch.object(socket.socket, "connect") as connect:
            try:
                with (
                    mock.patch.object(socket, "getaddrinfo", side_effect=resolve),
                    mock.patch.object(update_check, "_TIMEOUT_SEC", 0.1),
                    self.assertRaises(OSError),
                ):
                    REAL_FETCH_RELEASE(make_config(release_version="2.8.0"))
                self.assertLess(time.monotonic() - began, 0.6)
            finally:
                release.set()
                self.assertTrue(finished.wait(1))
            connect.assert_not_called()

    def test_continuously_dripping_headers_and_body_cannot_extend_the_exchange(self) -> None:
        for phase in ("headers", "body"):
            with self.subTest(phase=phase):
                self.dripping_exchange(phase)

    def dripping_exchange(self, phase: str) -> None:
        client, server = socket.socketpair()
        stop = threading.Event()

        def drip() -> None:
            try:
                server.recv(4096)
                if phase == "body":
                    server.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
                else:
                    server.sendall(b"HTTP/1.1 200 OK\r\nX-Drip: ")
                for _ in range(40):
                    if stop.wait(0.02):
                        return
                    server.sendall(b" ")
                server.shutdown(socket.SHUT_WR)
            except OSError:
                pass

        worker = threading.Thread(target=drip, daemon=True)
        worker.start()
        self.addCleanup(server.close)
        self.addCleanup(client.close)
        began = time.monotonic()
        try:
            # Exercise the real opener and deadline transport; only TCP/TLS setup is
            # replaced by a local socket so no network or certificate is needed.
            with (
                mock.patch.object(
                    http.client.HTTPSConnection,
                    "connect",
                    lambda connection: setattr(connection, "sock", client),
                ),
                mock.patch.object(update_check, "_TIMEOUT_SEC", 0.1),
                self.assertRaises((OSError, http.client.HTTPException)),
            ):
                REAL_FETCH_RELEASE(make_config(release_version="2.8.0"))
            self.assertLess(time.monotonic() - began, 0.6)
        finally:
            stop.set()
            worker.join(1)
