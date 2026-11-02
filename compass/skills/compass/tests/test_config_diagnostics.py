from __future__ import annotations

import argparse
import contextlib
import glob
import io
import json
import ntpath
import os
import socket
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from compass_runtime import aggregate, cli, diagnostics, http_api, lifecycle, notifications
from compass_runtime import config as runtime_config
from compass_runtime import io as runtime_io
from compass_runtime import sessions as runtime_sessions
from compass_runtime.collectors import claude as claude_collector
from compass_runtime.config import build_runtime_config
from compass_runtime.state import bounded_put, build_runtime_state

from .support import (
    REGISTRY,
    SERVER_PATH,
    STATE_HOME,
    STORE_OVERRIDES,
    RuntimeTestCase,
    cfg,
    collect_claude,
    diagnose,
    make_config,
    make_runtime,
    runtime,
    store_patch,
)


class CompassServerTest(RuntimeTestCase):
    def test_compass_home_returns_the_authoritative_override_verbatim(self) -> None:
        # Round-tripping an override through a native Path changes its separators
        # on Windows, breaking the documented string and dirname contracts. The
        # config therefore freezes both: state_home verbatim for every string
        # this prints or joins, state_dir for anything that wants a Path.
        override = "C:/plugin/state"
        config = build_runtime_config(
            environ={"HOME": "/nonexistent-compass-test", "COMPASS_HOME": override},
            platform_name="win32",
            os_name="nt",
            launcher_path=SERVER_PATH,
        )

        self.assertEqual(override, config.state_home)
        self.assertEqual(override, lifecycle.compass_home(config))
        # The dirname contract holds against the string the user actually wrote.
        self.assertEqual(override, os.path.dirname(lifecycle.state_path(config, 4553)))
        self.assertEqual(override, os.path.dirname(lifecycle.log_path(config, 4553)))
        # Both fields name the same location; only the spelling may differ.
        self.assertEqual(Path(override), Path(config.state_home))
        self.assertEqual(Path(override), config.state_dir)

    def test_the_shared_fixture_never_resolves_the_real_user_home(self) -> None:
        # Since DRC-4039 every collection reads the dismissal store under
        # state_home, so a fixture that falls through to the real ~/.compass
        # makes the suite's verdict depend on what the developer happens to have
        # dismissed. The default is a temporary directory; this is the assertion
        # that notices if it ever stops being one.
        self.assertEqual(STATE_HOME, cfg().state_home)
        self.assertEqual(STATE_HOME, str(cfg().state_dir))
        self.assertNotEqual(os.path.join(os.path.expanduser("~"), ".compass"), cfg().state_home)

    def test_compass_home_honours_the_override_and_defaults_under_home(self) -> None:
        with mock.patch.dict(os.environ, {"COMPASS_HOME": "/tmp/elsewhere"}):
            self.assertEqual("/tmp/elsewhere", lifecycle.compass_home(cfg()))
            self.assertEqual("/tmp/elsewhere", os.path.dirname(lifecycle.state_path(cfg(), 4553)))
        environ = {k: v for k, v in os.environ.items() if k != "COMPASS_HOME"}
        with mock.patch.dict(os.environ, environ, clear=True):
            self.assertEqual(os.path.join(cfg().home, ".compass"), lifecycle.compass_home(cfg()))
        for blank in ("", " ", "\t\r\n"):
            with (
                self.subTest(blank=repr(blank)),
                mock.patch.dict(os.environ, {"COMPASS_HOME": blank}),
            ):
                self.assertEqual(
                    os.path.join(cfg().home, ".compass"),
                    lifecycle.compass_home(cfg()),
                )

    def test_cli_port_type_rejects_values_outside_the_tcp_range(self) -> None:
        for value in ("-1", "0", "65536", "not-a-port"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                lifecycle.tcp_port(value)
        for value in ("1", "4553", "65535"):
            with self.subTest(value=value):
                self.assertEqual(int(value), lifecycle.tcp_port(value))
        with (
            mock.patch.object(sys, "argv", ["server.py", "--port", "0"]),
            mock.patch.object(sys, "stderr", io.StringIO()),
            mock.patch.object(http_api, "CompassHTTPServer") as bind,
            # argparse still owns its own usage errors, so this one exits rather
            # than returning a code.
            self.assertRaises(SystemExit) as caught,
        ):
            cli.main()
        self.assertEqual(2, caught.exception.code)
        bind.assert_not_called()

    def test_build_runtime_freezes_the_parsed_launch_options(self) -> None:
        # The CLI is the only place these three reach configuration. Rebuilding
        # from defaults anywhere downstream would discard the port, window and
        # Spacedock choices the user actually asked for.
        args = cli.build_parser().parse_args(
            [
                "--port",
                "6789",
                "--window-hours",
                "7.5",
                "--no-spacedock",
                "--no-git",
                "--no-history",
            ]
        )
        config, state = cli.build_runtime(args, started=1234.5, launcher_path=SERVER_PATH)

        self.assertEqual((6789, 7.5, False), (config.port, config.window_hours, False))
        self.assertFalse(config.spacedock_enabled)
        # `--no-git` is the DEC-3 off switch. Dropping the build_runtime line makes
        # this fail (git_probe_enabled stays True) while every other assertion here
        # still passes, which is the point of asserting it separately.
        self.assertFalse(config.git_probe_enabled)
        # `--no-history` is DEC-6's off switch, asserted separately for the same
        # reason: dropping its build_runtime line leaves history_enabled True, so
        # the store would go on being written for a user who turned it off, which
        # the promoted contract calls a security bug in as many words.
        self.assertFalse(config.history_enabled)
        self.assertIs(config, state.config)
        self.assertEqual(1234.5, state.server_started)

    def test_build_runtime_threads_host_into_config(self) -> None:
        # The --host flag reaches RuntimeConfig.host, which build_runtime_config
        # already carried as a dormant field. Dropping the host=args.host line
        # in build_runtime makes this fail (config.host stays "127.0.0.1").
        args = cli.build_parser().parse_args(["--host", "0.0.0.0"])
        config, _state = cli.build_runtime(args, started=1.0, launcher_path=SERVER_PATH)
        self.assertEqual("0.0.0.0", config.host)

    def test_build_runtime_threads_quiet_hours_into_config(self) -> None:
        args = cli.build_parser().parse_args(["--quiet-hours", "22:00-08:00"])
        config, _state = cli.build_runtime(args, started=1.0, launcher_path=SERVER_PATH)
        self.assertEqual("22:00-08:00", config.quiet_hours)
        self.assertTrue(config.quiet_hours_enabled)

    def test_build_runtime_threads_no_quiet_hours_into_config(self) -> None:
        args = cli.build_parser().parse_args(["--no-quiet-hours"])
        config, _state = cli.build_runtime(args, started=1.0, launcher_path=SERVER_PATH)
        self.assertFalse(config.quiet_hours_enabled)

    def test_host_flag_defaults_to_loopback(self) -> None:
        args = cli.build_parser().parse_args([])
        self.assertEqual("127.0.0.1", args.host)

    def test_host_flag_accepts_all_interfaces(self) -> None:
        args = cli.build_parser().parse_args(["--host", "0.0.0.0"])
        self.assertEqual("0.0.0.0", args.host)

    def _refused(self, value: str) -> str:
        """Parse `--host <value>`, require a refusal, and return what argparse said.

        Captured rather than left to escape. `parser.error()` writes a usage
        block plus the message to stderr, and these three tests refuse twelve
        values between them, so an uncaptured run buries the CI log for the
        whole suite under seventy-odd lines of usage that report nothing wrong.
        Returning the text rather than discarding it also lets each caller
        assert the refusal is about `--host` and not some unrelated parse error
        that would otherwise pass as a SystemExit.
        """
        captured = io.StringIO()
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stderr(captured):
            cli.build_parser().parse_args(["--host", value])
        self.assertEqual(2, caught.exception.code, value)
        return captured.getvalue()

    def test_host_flag_refuses_a_single_interface_bind(self) -> None:
        # A well-formed IPv4 that is neither loopback nor the wildcard. Refused
        # rather than half-supported: nothing that talks to the dashboard —
        # `--status`, `--stop`, the four hook forwarders, the MCP server — knows
        # any destination but loopback, and such a bind does not answer there.
        # `--stop` was the sharp end: it read "not running", exited 0, and
        # deleted the live instance's state file with its event-ingress
        # capability tokens while the server kept serving.
        for value in ("192.168.1.5", "10.0.0.2", "203.0.113.7"):
            with self.subTest(host=value):
                self.assertIn("--host", self._refused(value))

    def test_host_flag_rejects_malformed_addresses(self) -> None:
        # `ipaddress`, not a dotted-quad split with `int()`: that accepted a
        # sign, surrounding whitespace and non-ASCII digits, so each of these
        # parsed and then reached `socket.bind`.
        for value in ("+127.0.0.1", "127.0.0.1\n", " 127.0.0.1", "127.0.0.256", "127.0.0"):
            with self.subTest(host=value):
                self.assertIn("--host", self._refused(value))

    def test_host_flag_rejects_ipv6(self) -> None:
        # IPv6 binds are out of scope (the server is IPv4-only), so the type
        # validator rejects IPv6 literals at parse time.
        for value in ("::", "::1", "[::1]", "fe80::1"):
            with self.subTest(host=value):
                self.assertIn("--host", self._refused(value))

    def test_build_runtime_has_no_operational_side_effects(self) -> None:
        # --diagnose, --status and --stop are the recovery commands, so assembly
        # must not open a store, a socket or a log on the way to them.
        args = cli.build_parser().parse_args([])
        with (
            mock.patch.object(socket.socket, "bind", side_effect=AssertionError("bound")),
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("spawned")),
        ):
            config, state = cli.build_runtime(args, started=1.0, launcher_path=SERVER_PATH)

        self.assertEqual({}, dict(state.store_errors))
        self.assertEqual({}, dict(state.metadata_cache))
        self.assertTrue(config.store_roots)


class RuntimeConfigTest(unittest.TestCase):
    POSIX_ENV: ClassVar[dict[str, str]] = {
        "HOME": "/home/ada",
        "XDG_DATA_HOME": "/var/data/ada",
    }
    WINDOWS_ENV: ClassVar[dict[str, str]] = {
        "HOME": r"C:\Users\ada",
        "USERPROFILE": r"C:\Users\ada",
        "LOCALAPPDATA": r"C:\Users\ada\AppData\Local",
        "APPDATA": r"C:\Users\ada\AppData\Roaming",
    }

    def build(
        self,
        *,
        environ: dict[str, str],
        platform_name: str = "linux",
        os_name: str = "posix",
        **changes: Any,
    ) -> Any:
        return build_runtime_config(
            environ=environ,
            platform_name=platform_name,
            os_name=os_name,
            launcher_path=Path("/opt/compass/server.py"),
            **changes,
        )

    def test_explicit_posix_environment_builds_home_data_and_store_roots(self) -> None:
        # Reading ambient os.environ would replace these literal fixture roots.
        with mock.patch.dict(
            os.environ,
            {"HOME": "/ambient", "XDG_DATA_HOME": "/ambient/data"},
            clear=True,
        ):
            config = self.build(environ=dict(self.POSIX_ENV))

        self.assertEqual("/home/ada", config.home)
        self.assertEqual("/var/data/ada", config.data_home)
        self.assertEqual(("/home/ada/.claude/projects",), config.store_roots["claude.projects"])
        self.assertEqual(("/var/data/ada/opencode",), config.store_roots["opencode.data"])
        self.assertIsInstance(config.store_roots, types.MappingProxyType)

    def test_explicit_windows_environment_uses_target_path_rules(self) -> None:
        # Joining with host POSIX rules would produce mixed-separator Windows roots.
        config = self.build(
            environ=dict(self.WINDOWS_ENV),
            platform_name="win32",
            os_name="nt",
        )

        self.assertEqual(r"C:\Users\ada", config.home)
        self.assertEqual(r"C:\Users\ada\.local\share", config.data_home)
        self.assertEqual(
            (r"C:\Users\ada\.codex\sessions",),
            config.store_roots["codex.sessions"],
        )
        self.assertEqual(
            (
                r"C:\Users\ada\.local\share\opencode",
                r"C:\Users\ada\AppData\Local\opencode\data",
                r"C:\Users\ada\AppData\Local\opencode",
            ),
            config.store_roots["opencode.data"],
        )

    def test_documented_store_environment_overrides_remain_authoritative(self) -> None:
        # Appending default candidates would resurrect stale stores after relocation.
        environ = {
            **self.POSIX_ENV,
            "CLAUDE_CONFIG_DIR": "/srv/claude",
            "CODEX_HOME": "/srv/codex",
            "GEMINI_CLI_HOME": "/srv/gemini",
            "COPILOT_HOME": "/srv/copilot",
            "PI_CODING_AGENT_DIR": "/srv/pi",
            "PI_CODING_AGENT_SESSION_DIR": "/srv/pi-history",
        }
        config = self.build(environ=environ)

        self.assertEqual(("/srv/claude/projects",), config.store_roots["claude.projects"])
        self.assertEqual(("/srv/claude/tasks",), config.store_roots["claude.tasks"])
        self.assertEqual(("/srv/codex/sessions",), config.store_roots["codex.sessions"])
        self.assertEqual(("/srv/gemini/.gemini/tmp",), config.store_roots["gemini.tmp"])
        self.assertEqual(("/srv/copilot",), config.store_roots["copilot.root"])
        self.assertEqual(("/srv/pi-history",), config.store_roots["pi.sessions"])

    def test_selected_root_replaces_only_that_store_candidate_tuple(self) -> None:
        # Falling through after a patched primary can leak a developer's real store.
        config = self.build(
            environ=dict(self.WINDOWS_ENV),
            platform_name="win32",
            os_name="nt",
            store_root_overrides={"opencode.data": r"D:\fixture\opencode"},
        )

        self.assertEqual((r"D:\fixture\opencode",), config.store_roots["opencode.data"])
        self.assertEqual(
            (
                r"C:\Users\ada\.local\share\goose\sessions\sessions.db",
                r"C:\Users\ada\AppData\Roaming\Block\goose\data\sessions\sessions.db",
                r"C:\Users\ada\AppData\Local\Block\goose\data\sessions\sessions.db",
            ),
            config.store_roots["goose.db"],
        )

    def test_pi_session_dir_setting_resolves_relative_to_config_root(self) -> None:
        # Using the host path module instead of the requested target platform
        # creates mixed separators and scans a different Pi history directory.
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "pi"
            config_dir.mkdir()
            (config_dir / "settings.json").write_text(
                '{"sessionDir": "history"}',
                encoding="utf-8",
            )
            settings = runtime_config.load_pi_settings(str(config_dir))

        cases = (
            ("linux", "/opt/pi", "/home/ada", "/opt/pi/history"),
            ("win32", r"C:\Pi\agent", r"C:\Users\ada", r"C:\Pi\agent\history"),
        )
        for platform_name, config_root, home, expected in cases:
            with self.subTest(platform=platform_name):
                roots = runtime_config.resolve_store_roots(
                    platform_name=platform_name,
                    environ={"PI_CODING_AGENT_DIR": config_root},
                    home=home,
                    pi_settings=settings,
                )
                self.assertEqual(
                    [expected],
                    roots["pi.sessions"],
                )

    def test_runtime_options_and_state_directory_are_preserved(self) -> None:
        # Dropping a constructor argument would make the runtime use a CLI default.
        config = self.build(
            environ={**self.POSIX_ENV, "COMPASS_HOME": "/run/compass"},
            host="127.0.0.9",
            port=9123,
            window_hours=6.5,
            spacedock_enabled=False,
        )

        self.assertEqual(Path("/run/compass"), config.state_dir)
        self.assertEqual(Path("/opt/compass/server.py"), config.launcher_path)
        self.assertEqual("127.0.0.9", config.host)
        self.assertEqual(9123, config.port)
        self.assertEqual(6.5, config.window_hours)
        self.assertFalse(config.spacedock_enabled)
        self.assertEqual("linux", config.platform_name)
        self.assertEqual("posix", config.os_name)

    def test_every_threshold_and_limit_has_the_locked_default(self) -> None:
        # A reordered or copied-wrong limit changes bounded reads and cache behavior.
        config = self.build(environ=dict(self.POSIX_ENV))
        actual = (
            config.rate_window_sec,
            config.working_threshold_sec,
            config.turn_gap_reset_sec,
            config.tail_bytes,
            config.popup_cooldown_sec,
            config.global_popup_cooldown_sec,
            config.popup_repeat_suppress_sec,
            config.long_turn_warn_sec,
            config.loop_error_run_threshold,
            config.future_skew_tolerance_sec,
            config.sql_message_limit,
            config.max_cache_entries,
            config.gemini_seen_entries,
            config.reverse_chunk_bytes,
            config.display_id_len,
            config.claude_cwd_scan_lines,
            config.claude_cwd_line_bytes,
            config.turn_scan_max_bytes,
            config.claude_agent_scan_lines,
            config.claude_agent_cache_negative_min_bytes,
            config.claude_agent_scan_bytes,
            config.cursor_meta_rows,
            config.antigravity_log_head_bytes,
            config.spacedock_boot_scan_bytes,
            config.spacedock_readme_bytes,
            config.spacedock_entity_bytes,
            config.spacedock_max_frontmatter_lines,
            config.spacedock_max_stages,
            config.spacedock_max_workflows,
            config.spacedock_max_entities,
            config.spacedock_max_entity_files,
            config.spacedock_max_boot_records,
            config.spacedock_max_boot_candidates,
            config.collect_memo_sec,
            config.daemon_ready_timeout_sec,
            config.stop_release_timeout_sec,
            config.state_read_cap_bytes,
            config.prompt_path_collapse_min_length,
            config.first_line_json_cap_bytes,
            config.notification_body_cap_bytes,
        )
        self.assertEqual(
            (
                600,
                90,
                300,
                400_000,
                60,
                15,
                600,
                900,
                4,
                120,
                400,
                8192,
                2048,
                262_144,
                8,
                50,
                200_000,
                8 * 1024 * 1024,
                50,
                16_384,
                16_384,
                50,
                80_000,
                512_000,
                65_536,
                8_192,
                400,
                32,
                8,
                12,
                96,
                16,
                64,
                2.5,
                10.0,
                5.0,
                65_536,
                25,
                200_000,
                65_536,
            ),
            actual,
        )

    def test_runtime_states_retain_start_times_and_isolate_mutable_fields(self) -> None:
        # A default clock read, shared lock, or shared dict crosses runtime boundaries.
        _, first = make_runtime(started=1234.5)
        _, second = make_runtime(started=9876.5)

        self.assertEqual(1234.5, first.server_started)
        self.assertEqual(9876.5, second.server_started)
        dict_fields = (
            "hook_notifications",
            "last_popup",
            "last_popup_message",
            "last_session_state",
            "hook_generation",
            "store_errors",
            "metadata_cache",
            "claude_title_cache",
            "claude_user_event_cache",
            "cwd_cache",
            "pi_scan",
            "turn_scan",
            "agent_class_cache",
            "conversation_cache",
            "spacedock_role_cache",
            "spacedock_boot_cache",
            "spacedock_workflow_cache",
            "spacedock_entity_cache",
            "cursor_metadata_cache",
        )
        lock_fields = ("hook_lock", "cache_lock", "scanner_lock", "collect_memo_lock")
        for name in (*dict_fields, *lock_fields):
            with self.subTest(field=name):
                self.assertIsNot(getattr(first, name), getattr(second, name))

    def test_runtime_state_builder_never_reads_a_clock(self) -> None:
        # Reading and discarding a clock value is still an implicit time dependency.
        config, _ = make_runtime(started=1.0)
        with mock.patch("time.time", side_effect=AssertionError("clock read")):
            state = build_runtime_state(config, started=4321.25)
        self.assertEqual(4321.25, state.server_started)

    def test_bounded_put_evicts_only_for_a_new_key_at_the_limit(self) -> None:
        # Evicting on replacement drops an unrelated live cache entry.
        below_limit = {"first": 1}
        bounded_put(below_limit, "second", 2, limit=3)
        self.assertEqual({"first": 1, "second": 2}, below_limit)

        cache = {"oldest": 1, "newest": 2}
        bounded_put(cache, "newest", 3, limit=2)
        self.assertEqual({"oldest": 1, "newest": 3}, cache)

        bounded_put(cache, "third", 4, limit=2)
        self.assertEqual({"newest": 3, "third": 4}, cache)


class StoreRootsTest(unittest.TestCase):
    """resolve_store_roots is pure, so every platform's layout is checked here
    regardless of which runner is executing."""

    POSIX_HOME = "/home/u"
    WIN_HOME = r"C:\Users\j"
    WIN_ENV: ClassVar[dict[str, str]] = {
        "LOCALAPPDATA": r"C:\Users\j\AppData\Local",
        "APPDATA": r"C:\Users\j\AppData\Roaming",
    }

    def resolve(
        self, platform_name: str, environ: dict[str, str], home: str
    ) -> dict[str, list[str]]:
        roots: dict[str, list[str]] = runtime_config.resolve_store_roots(
            platform_name=platform_name, environ=environ, home=home
        )
        return roots

    def test_posix_defaults_are_unchanged(self) -> None:
        # These are the paths that work today; a regression here silently
        # blinds the dashboard on the platform it was built for.
        roots = self.resolve("darwin", {}, self.POSIX_HOME)
        self.assertEqual(["/home/u/.claude/projects"], roots["claude.projects"])
        self.assertEqual(["/home/u/.claude/tasks"], roots["claude.tasks"])
        self.assertEqual(["/home/u/.claude/teams"], roots["claude.teams"])
        self.assertEqual(["/home/u/.codex/sessions"], roots["codex.sessions"])
        self.assertEqual(["/home/u/.gemini/tmp"], roots["gemini.tmp"])
        self.assertEqual(["/home/u/.copilot"], roots["copilot.root"])
        self.assertEqual(["/home/u/.cursor/chats"], roots["cursor.chats"])
        # Sessions first: droid 0.202.0 writes <home>/.factory/sessions/<slugified-cwd>/
        # <id>.jsonl, and with `projects` as the only root three real transcripts
        # discovered nothing (DRC-4331). `projects` stays as the fallback because
        # no measurement says which versions wrote there.
        self.assertEqual(
            ["/home/u/.factory/sessions", "/home/u/.factory/projects"], roots["droid.projects"]
        )
        self.assertEqual(["/home/u/.local/share/opencode"], roots["opencode.data"])
        self.assertEqual(["/home/u/.local/share/goose/sessions/sessions.db"], roots["goose.db"])

    def test_pi_defaults_to_its_agent_sessions_directory(self) -> None:
        # Removing Pi's default candidate would leave an ordinary installation
        # invisible, even though every other harness still resolves normally.
        roots = self.resolve("darwin", {}, self.POSIX_HOME)
        self.assertEqual(["/home/u/.pi/agent/sessions"], roots["pi.sessions"])

    def test_pi_session_environment_override_is_authoritative(self) -> None:
        # A user may relocate sessions independently of Pi's configuration;
        # searching the configured or default directory as well risks stale
        # sessions appearing in the dashboard.
        roots = runtime_config.resolve_store_roots(
            platform_name="linux",
            environ={
                "PI_CODING_AGENT_DIR": "/opt/pi",
                "PI_CODING_AGENT_SESSION_DIR": "/sessions",
            },
            home=self.POSIX_HOME,
            pi_settings={"sessionDir": "/global-history"},
        )
        self.assertEqual(["/sessions"], roots["pi.sessions"])

    def test_pi_global_session_directory_precedes_the_default(self) -> None:
        # Ignoring Pi's global setting would scan the wrong store after a user
        # changes the history location without setting the session env var.
        roots = runtime_config.resolve_store_roots(
            platform_name="linux",
            environ={"PI_CODING_AGENT_DIR": "/opt/pi"},
            home=self.POSIX_HOME,
            pi_settings={"sessionDir": "history"},
        )
        self.assertEqual(["/opt/pi/history"], roots["pi.sessions"])

    def test_pi_session_setting_expands_home_and_accepts_absolute_paths(self) -> None:
        # Treating either setting as relative would redirect an intentional
        # custom location underneath Pi's configuration directory.
        tilde = runtime_config.resolve_store_roots(
            platform_name="linux",
            environ={"PI_CODING_AGENT_DIR": "/opt/pi"},
            home=self.POSIX_HOME,
            pi_settings={"sessionDir": "~/pi-history"},
        )
        absolute = runtime_config.resolve_store_roots(
            platform_name="linux",
            environ={"PI_CODING_AGENT_DIR": "/opt/pi"},
            home=self.POSIX_HOME,
            pi_settings={"sessionDir": "/var/lib/pi/sessions"},
        )
        self.assertEqual(["/home/u/pi-history"], tilde["pi.sessions"])
        self.assertEqual(["/var/lib/pi/sessions"], absolute["pi.sessions"])

    def test_pi_invalid_session_settings_fall_back_to_its_default(self) -> None:
        # A malformed global settings file must not make Pi disappear; its
        # documented sessions child remains the safe fallback.
        invalid_values: tuple[Any, ...] = ("", "   ", None, 42, [])
        for value in invalid_values:
            with self.subTest(value=value):
                roots = runtime_config.resolve_store_roots(
                    platform_name="linux",
                    environ={"PI_CODING_AGENT_DIR": "/opt/pi"},
                    home=self.POSIX_HOME,
                    pi_settings={"sessionDir": value},
                )
                self.assertEqual(["/opt/pi/sessions"], roots["pi.sessions"])

    def test_load_pi_settings_reads_only_a_json_object(self) -> None:
        # Returning arbitrary JSON would make the resolver trust a malformed
        # global settings file as if it had Pi's object-shaped configuration.
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "agent"
            config.mkdir()
            (config / "settings.json").write_text('{"sessionDir":"history"}')
            self.assertEqual(
                {"sessionDir": "history"}, runtime_config.load_pi_settings(str(config))
            )
            (config / "settings.json").write_text("[]")
            self.assertEqual({}, runtime_config.load_pi_settings(str(config)))
            (config / "settings.json").write_text("{")
            self.assertEqual({}, runtime_config.load_pi_settings(str(config)))

        self.assertEqual({}, runtime_config.load_pi_settings("/not/a/pi/config"))

    def test_pi_uses_target_windows_path_rules(self) -> None:
        # A POSIX host resolving a Windows Pi path must not produce mixed
        # separators, which Windows then interprets as a different location.
        roots = runtime_config.resolve_store_roots(
            platform_name="win32",
            environ={"PI_CODING_AGENT_DIR": r"D:\Pi"},
            home=self.WIN_HOME,
            pi_settings={"sessionDir": r"history\today"},
        )
        self.assertEqual([r"D:\Pi\history\today"], roots["pi.sessions"])

    def test_xdg_data_home_is_honored(self) -> None:
        roots = self.resolve("linux", {"XDG_DATA_HOME": "/xdg"}, self.POSIX_HOME)
        self.assertEqual(["/xdg/opencode"], roots["opencode.data"])
        self.assertEqual(["/xdg/goose/sessions/sessions.db"], roots["goose.db"])

    def test_windows_uses_native_separators_and_app_data(self) -> None:
        roots = self.resolve("win32", dict(self.WIN_ENV), self.WIN_HOME)
        self.assertEqual([r"C:\Users\j\.claude\projects"], roots["claude.projects"])
        # App-data locations are searched in addition to the XDG-style one.
        self.assertIn(r"C:\Users\j\AppData\Local\opencode\data", roots["opencode.data"])
        self.assertIn(
            r"C:\Users\j\AppData\Roaming\Block\goose\data\sessions\sessions.db",
            roots["goose.db"],
        )

    def test_candidates_are_deduplicated(self) -> None:
        # On Windows the XDG-style default and the explicit ~/.local/share
        # entry are the same path; it must not be scanned twice.
        roots = self.resolve("win32", dict(self.WIN_ENV), self.WIN_HOME)
        for key, candidates in roots.items():
            with self.subTest(key=key):
                folded = [ntpath.normcase(c) for c in candidates]
                self.assertEqual(len(folded), len(set(folded)))

    def test_documented_env_overrides_are_authoritative(self) -> None:
        roots = self.resolve(
            "linux",
            {
                "CLAUDE_CONFIG_DIR": "/opt/cc",
                "CODEX_HOME": "/opt/cx",
                "COPILOT_HOME": "/opt/cp",
            },
            self.POSIX_HOME,
        )
        # Only the override is searched — a relocated store must never fall
        # back to a stale default.
        self.assertEqual(["/opt/cc/projects"], roots["claude.projects"])
        self.assertEqual(["/opt/cc/tasks"], roots["claude.tasks"])
        # CLAUDE_CONFIG_DIR relocates the teams registry with the rest of the
        # Claude stores; a member roster left behind at the default would be
        # read against a session store nothing else searches.
        self.assertEqual(["/opt/cc/teams"], roots["claude.teams"])
        self.assertEqual(["/opt/cx/sessions"], roots["codex.sessions"])
        self.assertEqual(["/opt/cp"], roots["copilot.root"])

    def test_gemini_cli_home_names_a_parent_directory(self) -> None:
        # Documented behavior: the CLI creates ".gemini" *inside* the value.
        roots = self.resolve("linux", {"GEMINI_CLI_HOME": "/opt/g"}, self.POSIX_HOME)
        self.assertEqual(["/opt/g/.gemini/tmp"], roots["gemini.tmp"])
        self.assertEqual(["/opt/g/.gemini/antigravity-cli"], roots["antigravity.root"])

    def test_blank_env_values_fall_back_to_defaults(self) -> None:
        roots = self.resolve("linux", {"CLAUDE_CONFIG_DIR": "   "}, self.POSIX_HOME)
        self.assertEqual(["/home/u/.claude/projects"], roots["claude.projects"])

    def test_an_override_suppresses_the_other_candidates(self) -> None:
        # The override seam: pointing a store at a fixture must scan that and
        # nothing else, or a test could pick up a real store on the box.
        with store_patch(OPENCODE_DATA="/fixture"):
            config = cfg()
            self.assertEqual(("/fixture",), runtime_config.store_roots(config, "opencode.data"))
            self.assertEqual("/fixture", runtime_config.primary_store(config, "opencode.data"))
        # With no override, every resolved candidate is searched, and the
        # primary is the first of them.
        config = cfg()
        candidates = runtime_config.store_roots(config, "opencode.data")
        self.assertGreaterEqual(len(candidates), 1)
        self.assertEqual(candidates[0], runtime_config.primary_store(config, "opencode.data"))

    def test_sessions_from_two_candidate_roots_are_merged(self) -> None:
        now = 1_700_000_000.0
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a", Path(tmp) / "b"
            for root, sid in ((first, "11111111"), (second, "22222222")):
                (root / "proj").mkdir(parents=True)
                transcript = root / "proj" / f"{sid}-0000-0000-0000-000000000000.jsonl"
                transcript.write_text(json.dumps({"type": "user", "uuid": "u"}) + "\n")
                os.utime(transcript, (now, now))
            with (
                # The override IS the candidate list, so naming the primary
                # separately would just overwrite it with one root.
                mock.patch.dict(
                    STORE_OVERRIDES,
                    {"claude.projects": [str(first), str(second)]},
                ),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
            ):
                sessions = collect_claude(now, 24, False)

        self.assertEqual({"11111111", "22222222"}, {s["session"] for s in sessions})

    def test_patched_candidate_order_reaches_runtime_globbing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / "a", Path(tmp) / "b"
            first.mkdir()
            second.mkdir()
            first_file = first / "first.jsonl"
            second_file = second / "second.jsonl"
            first_file.write_text("{}\n")
            second_file.write_text("{}\n")
            with (
                mock.patch.dict(
                    STORE_OVERRIDES,
                    {"claude.projects": [str(first), str(second)]},
                ),
            ):
                config, _ = runtime()
                found = runtime_io.glob_stores(config, "claude.projects", "*.jsonl")

        self.assertEqual([str(first_file), str(second_file)], found)


class DiagnoseTest(unittest.TestCase):
    def test_report_names_every_candidate_and_what_was_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            (projects / "proj").mkdir(parents=True)
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(Path(tmp) / "absent")),
            ):
                report = diagnose(24)

        claude = report["stores"]["claude.projects"]["candidates"]
        self.assertEqual("directory", claude[0]["kind"])
        self.assertTrue(claude[0]["readable"])
        # A missing store is reported as missing, not omitted — the whole point
        # is distinguishing "looked and found nothing" from "never looked".
        self.assertEqual("missing", report["stores"]["claude.tasks"]["candidates"][0]["kind"])
        self.assertEqual(sys.platform, report["platform"])
        self.assertIn("available", report["sqlite"])

    @unittest.skipIf(os.name == "nt", "POSIX permission bits; Windows uses ACLs")
    def test_an_unreadable_store_is_distinguished_from_a_missing_one(self) -> None:
        # The distinction that matters on Windows, where Defender, EDR, and
        # OneDrive hydration all produce transient permission failures: a store
        # that exists but cannot be read must not look like an absent harness.
        with tempfile.TemporaryDirectory() as tmp:
            locked = Path(tmp) / "locked"
            locked.mkdir()
            locked.chmod(0o000)
            try:
                report = diagnostics.candidate_report(str(locked))
            finally:
                locked.chmod(0o700)  # or TemporaryDirectory cannot clean up

        self.assertEqual("directory", report["kind"])
        self.assertFalse(report["readable"])
        self.assertIn("PermissionError", report["error"])
        self.assertNotEqual("missing", report["kind"])

    def test_rendering_is_ascii_only(self) -> None:
        # This output gets pasted into issues from consoles whose encoding we
        # do not control.
        text = diagnostics.render_diagnosis(diagnose(24))
        text.encode("ascii")  # must not raise
        self.assertIn("Stores searched", text)
        self.assertIn("Harnesses", text)

    def test_json_report_survives_a_round_trip_intact(self) -> None:
        """`--diagnose --json` is what a user pastes into an issue, so the
        contract is that it round-trips and still carries the fields that make
        it diagnostic. "Did not raise" would also be satisfied by `{}`."""
        report = diagnose(24)

        self.assertEqual(report, json.loads(json.dumps(report)))
        self.assertLessEqual(
            {"platform", "python", "executable", "home", "env", "stores", "harnesses"},
            set(report),
        )
        # Every registered harness is accounted for, present or not: a missing
        # row is indistinguishable from a harness that was never checked.
        self.assertEqual(
            {spec.key for spec in REGISTRY},
            {h["key"] for h in report["harnesses"]},
        )
        for harness in report["harnesses"]:
            with self.subTest(harness=harness["key"]):
                self.assertLessEqual({"key", "label", "discovered", "error"}, set(harness))

    def test_per_harness_session_counts_are_reported(self) -> None:
        # "discovered" only says a store exists. The session count is what
        # separates "found the store, read nothing" from "working", and it is
        # the first number anyone looks at in a bug report.
        # Mutation-checked: reporting a flat zero passed the whole suite.
        counted = [
            {"harness": "claude", "state": "idle"},
            {"harness": "claude", "state": "idle"},
            {"harness": "codex", "state": "idle"},
        ]

        def collect(_self: Any, *, show_all: bool, notify: bool = True) -> dict[str, Any]:
            assert show_all, "diagnose must ask for every session, not just active ones"
            assert not notify, "diagnose must ask for notify=False to prevent writes and popups"
            return {
                "sessions": counted,
                "tripwires": {"error": ""},
                "harnesses": [
                    {"key": "claude", "label": "Claude", "discovered": True, "error": None},
                    {"key": "codex", "label": "Codex", "discovered": True, "error": None},
                    {"key": "goose", "label": "Goose", "discovered": False, "error": None},
                ],
            }

        with mock.patch.object(aggregate.Application, "collect", collect):
            report = diagnose(24)

        self.assertEqual(
            {"claude": 2, "codex": 1, "goose": 0},
            {h["key"]: h["sessions"] for h in report["harnesses"]},
        )
        text = diagnostics.render_diagnosis(report)
        self.assertIn("2 session(s)", text)
        self.assertIn("1 session(s)", text)

    def test_store_report_order_is_pinned_not_inherited_from_the_resolver(self) -> None:
        # --diagnose output is diffed between machines and pasted into issues, so
        # the store order is part of the contract. The resolver groups Claude's
        # two stores the other way round, so taking its order would silently
        # swap two lines. Mutation-checked: both halves of this passed before.
        config = make_config(
            store_roots=types.MappingProxyType(
                {
                    "claude.tasks": ("/t",),
                    "claude.projects": ("/p",),
                    "goose.db": ("/g",),
                    "brand.new": ("/n",),
                }
            )
        )
        primaries = diagnostics.store_primaries(config)

        self.assertEqual(
            ["claude.projects", "claude.tasks", "goose.db", "brand.new"], list(primaries)
        )
        # A store the resolver knows about but this module has never heard of is
        # still reported. Dropping it would hide the one path a user needs.
        self.assertEqual("/n", primaries["brand.new"])

    def test_env_overrides_are_surfaced(self) -> None:
        with mock.patch.dict(os.environ, {"CODEX_HOME": "/opt/cx"}):
            report = diagnose(24)
        self.assertEqual("/opt/cx", report["env"]["CODEX_HOME"])

    def test_pi_overrides_and_session_candidate_are_surfaced(self) -> None:
        # Omitting either override or the candidate leaves a relocated Pi
        # install indistinguishable from a harness Compass does not support.
        with (
            mock.patch.dict(
                os.environ,
                {
                    "PI_CODING_AGENT_DIR": "/opt/pi",
                    "PI_CODING_AGENT_SESSION_DIR": "/sessions",
                },
            ),
            store_patch(PI_SESSIONS_DIR="/sessions"),
        ):
            report = diagnose(24)

        self.assertEqual("/opt/pi", report["env"]["PI_CODING_AGENT_DIR"])
        self.assertEqual("/sessions", report["env"]["PI_CODING_AGENT_SESSION_DIR"])
        self.assertEqual("/sessions", report["stores"]["pi.sessions"]["candidates"][0]["path"])

    def test_compass_home_and_xdg_overrides_are_surfaced(self) -> None:
        """DRC-4180: COMPASS_HOME and XDG_DATA_HOME are reported in env and compass_home."""
        with mock.patch.dict(
            os.environ, {"COMPASS_HOME": "/opt/compass", "XDG_DATA_HOME": "/opt/xdg"}
        ):
            report = diagnose(24)
        self.assertEqual("/opt/compass", report.get("compass_home"))
        self.assertEqual("/opt/compass", report["env"].get("COMPASS_HOME"))
        self.assertEqual("/opt/xdg", report["env"].get("XDG_DATA_HOME"))
        text = diagnostics.render_diagnosis(report)
        self.assertIn("  compass   /opt/compass", text)
        self.assertIn("COMPASS_HOME=/opt/compass", text)
        self.assertIn("XDG_DATA_HOME=/opt/xdg", text)

    def test_diagnose_over_needs_input_session_writes_nothing(self) -> None:
        """DRC-4553: --diagnose reads local paths only and writes nothing."""
        import time  # noqa: PLC0415
        from datetime import UTC, datetime  # noqa: PLC0415

        from compass_runtime.cli import main as cli_main  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as td:
            compass_home = Path(td) / "compass"
            compass_home.mkdir(mode=0o700)
            home = Path(td) / "home"
            claude_dir = home / ".claude" / "projects" / "-test-project"
            claude_dir.mkdir(parents=True)
            stamp = datetime.fromtimestamp(time.time(), tz=UTC).isoformat()
            transcript = claude_dir / "a1b2c3d4-0000-0000-0000-000000000000.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "user",
                                "uuid": "u1",
                                "timestamp": stamp,
                                "message": {"content": "hello"},
                            }
                        ),
                        json.dumps(
                            {
                                "type": "assistant",
                                "timestamp": stamp,
                                "message": {
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "id": "t1",
                                            "name": "AskUserQuestion",
                                            "input": {"questions": [{"question": "Which?"}]},
                                        }
                                    ],
                                    "usage": {"output_tokens": 10},
                                },
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "COMPASS_HOME": str(compass_home),
                "HOME": str(home),
                "CLAUDE_CONFIG_DIR": str(home / ".claude"),
            }
            with mock.patch.dict(os.environ, env, clear=True):
                code = cli_main(["--diagnose"])
            self.assertEqual(0, code)
            self.assertEqual(
                [], os.listdir(compass_home), "--diagnose wrote files into compass_home"
            )


class OperatingSystemExpectationTest(unittest.TestCase):
    """What Compass should do per OS, stated as expectations rather than
    derived from bugs. Every case is exercised on every runner by passing the
    platform in, so Linux CI checks the Windows behaviour too."""

    def test_project_labels_shorten_on_every_platform(self) -> None:
        # Claude encodes the working directory into the projects/ directory
        # name. Replacing only "/" did nothing to a Windows home, so every
        # Claude row there showed the whole encoded path instead of a project.
        cases = [
            ("/Users/jared", "-Users-jared-repos-compass", "repos-compass"),
            ("/home/u", "-home-u-work-my-repo", "work-my-repo"),
            (r"C:\Users\jared", "C--Users-jared-repos-compass", "repos-compass"),
            (r"C:\Users\jared", "C--Users-jared", "(home)"),
            # Unknown encoding must degrade to showing the name, never crash.
            ("/Users/jared", "-somewhere-else", "somewhere-else"),
        ]
        for home, encoded, expected in cases:
            with self.subTest(home=home, encoded=encoded):
                config = make_config(home=home)
                self.assertEqual(expected, runtime_sessions.project_label(config, encoded))

    def test_the_bounded_fallback_label_caps_the_encoded_path_at_two_segments(self) -> None:
        # The fallback three collectors reach when a transcript carries no `cwd`.
        # `project_label` returns every remaining segment of a home-relative path
        # joined by `-`, so the cap belongs here: this is the only place a label
        # is built by joining path segments, and therefore the only place the
        # difference between a path and a hyphenated directory name is known.
        cases = [
            # The measured six-directory case, encoded the way Claude encodes one.
            (
                "/nonexistent-compass-test",
                (
                    "-nonexistent-compass-test-repos-recce-recce-cloud-infra"
                    "--claude-worktrees-drc-3976-finish"
                ),
                "3976-finish",
            ),
            ("/Users/jared", "-Users-jared-alpha-beta-gamma-delta-epsilon-zeta", "epsilon-zeta"),
            # Already two segments, so the cap is a no-op rather than a trim.
            ("/Users/jared", "-Users-jared-repos-compass", "repos-compass"),
            ("/Users/jared", "-somewhere-else", "somewhere-else"),
            # The home sentinel is a label, not a path, and must survive whole.
            (r"C:\Users\jared", "C--Users-jared", "(home)"),
        ]
        for home, encoded, expected in cases:
            with self.subTest(home=home, encoded=encoded):
                config = make_config(home=home)
                self.assertEqual(
                    expected,
                    runtime_sessions.bounded_project_label(config, encoded),
                )

    def test_project_from_cwd_is_parent_over_basename(self) -> None:
        # DRC-3963. Bare basename collapses every checkout named "subspace"
        # into one label, so the contract is the last two path segments.
        # The home and OS name come from an explicit config, so this runner
        # exercises both platforms rather than only its own.
        posix = [
            ("/Users/cl/git/spacedock-research/spacedock/subspace", "spacedock/subspace"),
            ("/Users/cl/repos/recce/compass", "recce/compass"),
            # Trailing separators are noise, not a segment.
            ("/Users/cl/repos/recce/compass/", "recce/compass"),
            # Outside home, one segment below root has no parent to show.
            ("/srv", "srv"),
            # A path under home is labelled relative to it, so the account
            # name never reaches a row. project_label() strips the same
            # prefix; the two must agree on this directory.
            ("/Users/cl/foo", "foo"),
            # Backslash is a legal POSIX filename character, so it must not
            # split a segment here (docs/design-cross-platform.md).
            ("/srv/my\\proj", "srv/my\\proj"),
            # Unusable input degrades to "" so each collector can apply its
            # own harness-name fallback.
            ("", ""),
            ("/", ""),
            ("relative/path", ""),
            ("..", ""),
            ("/Users/cl/repos/..", ""),
        ]
        posix_config = make_config(home="/Users/cl", os_name="posix")
        for cwd, expected in posix:
            with self.subTest(cwd=cwd, platform="posix"):
                self.assertEqual(expected, runtime_sessions.project_from_cwd(posix_config, cwd))

        windows = [
            (r"C:\Users\cl\git\spacedock\subspace", "spacedock/subspace"),
            # Windows accepts either separator spelling for the same path.
            ("C:/Users/cl/git/spacedock/subspace", "spacedock/subspace"),
            (r"C:\proj", "proj"),
            (r"C:\Users\cl\foo", "foo"),
            (r"relative\path", ""),
        ]
        windows_config = make_config(home=r"C:\Users\cl", os_name="nt")
        for cwd, expected in windows:
            with self.subTest(cwd=cwd, platform="windows"):
                self.assertEqual(
                    expected,
                    runtime_sessions.project_from_cwd(windows_config, cwd),
                )

    def test_project_from_cwd_names_the_home_directory_in_any_spelling(self) -> None:
        # project_label() renders a session started in $HOME as "(home)".
        # On Windows the same directory can be recorded with either separator
        # and either case, and all of those spellings are one directory.
        posix_config = make_config(home="/Users/cl", os_name="posix")
        self.assertEqual("(home)", runtime_sessions.project_from_cwd(posix_config, "/Users/cl"))
        self.assertEqual("(home)", runtime_sessions.project_from_cwd(posix_config, "/Users/cl/"))
        # A sibling whose name merely starts with the home path is not home.
        self.assertEqual(
            "Users/clXYZ",
            runtime_sessions.project_from_cwd(posix_config, "/Users/clXYZ"),
        )
        windows_config = make_config(home=r"C:\Users\jared", os_name="nt")
        for spelling in (r"C:\Users\jared", "C:/Users/jared", r"c:\users\JARED", "C:/Users/Jared/"):
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    "(home)",
                    runtime_sessions.project_from_cwd(windows_config, spelling),
                )

    def test_a_split_directory_resolves_to_its_path_form_when_it_exists_on_disk(self) -> None:
        """DRC-4629. The encoding flattens ``/`` to ``-``, so the string alone
        cannot tell ``recce/compass`` from a directory named
        ``recce-compass``. The machine that wrote the store is the machine
        reading it, so the directory settles it.
        """
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "repos", "recce", "compass"))
            config = make_config(home=home)
            encoded = runtime_sessions.encoded_home_prefix(home) + "-repos-recce-compass"
            self.assertEqual(
                "recce/compass",
                runtime_sessions.bounded_project_label(config, encoded),
            )

    def test_a_directory_genuinely_named_with_a_dash_keeps_the_dash(self) -> None:
        """The case the resolution must not break: one real directory whose own
        name contains the separator the encoding uses.
        """
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "work-my-repo"))
            config = make_config(home=home)
            encoded = runtime_sessions.encoded_home_prefix(home) + "-work-my-repo"
            self.assertEqual(
                "work-my-repo",
                runtime_sessions.bounded_project_label(config, encoded),
            )

    def test_an_encoded_name_with_no_directory_behind_it_falls_back_closed(self) -> None:
        """A wrong join merges two projects that are genuinely different, which
        is worse than the split it replaces, so an unresolvable name keeps the
        label it has today.
        """
        with tempfile.TemporaryDirectory() as home:
            config = make_config(home=home)
            encoded = runtime_sessions.encoded_home_prefix(home) + "-repos-recce-compass"
            self.assertEqual(
                "recce-compass",
                runtime_sessions.bounded_project_label(config, encoded),
            )

    def test_a_resolved_path_is_still_capped_at_two_segments(self) -> None:
        """Resolution must not become a way to write a home-relative path into a
        fourteen-day store, which is the rule the cap exists to keep.
        """
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "a", "b", "c", "d", "e"))
            config = make_config(home=home)
            encoded = runtime_sessions.encoded_home_prefix(home) + "-a-b-c-d-e"
            self.assertEqual(
                "d/e",
                runtime_sessions.bounded_project_label(config, encoded),
            )

    def test_project_from_cwd_agrees_with_project_label_under_home(self) -> None:
        # The whole point of DRC-3963 is that one directory reads the same on
        # every row. The cwd path and the encoded-name fallback are the two
        # ways a label is produced, so they have to produce the same string.
        config = make_config(home="/Users/cl", os_name="posix")
        for cwd in ("/Users/cl/foo", "/Users/cl/git/spacedock/subspace"):
            with self.subTest(cwd=cwd):
                encoded = runtime_sessions.encoded_home_prefix(cwd)
                from_cwd = runtime_sessions.project_from_cwd(config, cwd)
                from_name = runtime_sessions.project_label(config, encoded)
                # The encoded name cannot be split back into segments, so it
                # keeps its hyphens; what must agree is that neither leaks the
                # account name.
                self.assertNotIn("cl", from_cwd.split("/")[0])
                self.assertEqual(
                    from_name.replace("-", "/").split("/")[-1], from_cwd.split("/")[-1]
                )

    def test_task_age_degrades_to_mtime_without_birthtime(self) -> None:
        # Linux exposes no st_birthtime. The
        # documented consequence is that completed-task ages come from mtime;
        # it must degrade, not raise.
        now = 1_700_000_000.0
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "abcdef12-0000-0000-0000-000000000000"
            session.mkdir()
            (session / "1.json").write_text(
                json.dumps({"id": "1", "subject": "task", "status": "completed"}),
                encoding="utf-8",
            )
            os.utime(session / "1.json", (now, now))

            real_stat = os.stat

            class NoBirthtime:
                """A stat result with birthtime removed, as on ext4."""

                def __init__(self, wrapped: Any) -> None:
                    self._wrapped = wrapped

                def __getattr__(self, name: str) -> Any:
                    if name == "st_birthtime":
                        raise AttributeError(name)
                    return getattr(self._wrapped, name)

            with (
                store_patch(TASKS_DIR=str(tmp)),
                mock.patch.object(os, "stat", lambda p: NoBirthtime(real_stat(p))),
            ):
                tasks = claude_collector.load_tasks(runtime()[0])

        task = tasks["abcdef12"][0]
        self.assertEqual(now, task["created"], "created should fall back to mtime")
        self.assertEqual(now, task["updated"])

    def test_notification_ownership_per_platform(self) -> None:
        # Exactly one layer notifies. macOS has a native backend, so the page
        # must stay silent there; the others have none yet, so the page owns it.
        self.assertEqual("osascript", notifications.native_notifier("darwin"))
        for platform_name in ("linux", "win32", "cygwin", "freebsd14"):
            with self.subTest(platform=platform_name):
                self.assertEqual("", notifications.native_notifier(platform_name))

    def test_port_sharing_policy_per_platform(self) -> None:
        # POSIX: SO_REUSEADDR only bypasses TIME_WAIT, so restarts work.
        # Windows: it lets another process bind an already-bound port.
        self.assertTrue(http_api.reuse_address_allowed("posix"))
        self.assertFalse(http_api.reuse_address_allowed("nt"))

    def test_the_listener_takes_its_reuse_policy_from_the_config(self) -> None:
        # The helper above is pure, but the server has to actually ask it with
        # THIS application's os_name. Reading the ambient os.name instead agrees
        # with the config on every runner we test on, so only a config that
        # disagrees with the host can tell the two apart.
        # Mutation-checked: substituting os.name passed the whole suite.
        for os_name, expected in (("nt", False), ("posix", True)):
            with self.subTest(os_name=os_name):
                config, state = make_runtime(os_name=os_name)
                application = aggregate.Application(
                    config,
                    state,
                    (),
                    native_notifier=lambda _platform: "",
                    popup_notifier=lambda _title, _message: None,
                    diagnostic_sink=lambda _line: None,
                )
                httpd = http_api.CompassHTTPServer(("127.0.0.1", 0), application, b"<page>")
                try:
                    self.assertIs(expected, httpd.allow_reuse_address)
                finally:
                    httpd.server_close()

    def test_store_locations_per_platform(self) -> None:
        posix = runtime_config.resolve_store_roots(
            platform_name="darwin", environ={}, home="/Users/u"
        )
        linux = runtime_config.resolve_store_roots(
            platform_name="linux", environ={"XDG_DATA_HOME": "/xdg"}, home="/home/u"
        )
        windows = runtime_config.resolve_store_roots(
            platform_name="win32",
            environ={
                "LOCALAPPDATA": r"C:\Users\j\AppData\Local",
                "APPDATA": r"C:\Users\j\AppData\Roaming",
            },
            home=r"C:\Users\j",
        )
        # Dot-directories under $HOME on every platform.
        self.assertEqual(["/Users/u/.claude/projects"], posix["claude.projects"])
        self.assertEqual([r"C:\Users\j\.claude\projects"], windows["claude.projects"])
        # XDG only where XDG applies.
        self.assertEqual(["/xdg/opencode"], linux["opencode.data"])
        self.assertEqual(["/xdg/goose/sessions/sessions.db"], linux["goose.db"])
        # Windows searches app-data in addition, never instead.
        self.assertIn(r"C:\Users\j\AppData\Local\opencode\data", windows["opencode.data"])
        self.assertIn(
            r"C:\Users\j\AppData\Roaming\Block\goose\data\sessions\sessions.db",
            windows["goose.db"],
        )
        # Every platform's paths use that platform's separator.
        for key, roots in windows.items():
            with self.subTest(key=key):
                self.assertTrue(all("/" not in r for r in roots), roots)
        for key, roots in posix.items():
            with self.subTest(key=key):
                self.assertTrue(all("\\" not in r for r in roots), roots)


class TextIoTest(unittest.TestCase):
    def test_task_json_is_read_as_utf8_regardless_of_locale(self) -> None:
        # The locale default is cp1252 on Windows, which mojibakes this subject
        # and raises on the bytes that code page leaves undefined.
        subject = "Ship the café ☕ feature"
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "abcdef12-0000-0000-0000-000000000000"
            session.mkdir()
            (session / "1.json").write_text(
                json.dumps({"id": "1", "subject": subject, "status": "pending"}),
                encoding="utf-8",
            )
            with store_patch(TASKS_DIR=str(tmp)):
                tasks = claude_collector.load_tasks(runtime()[0])

        self.assertEqual([subject], [t["subject"] for t in tasks["abcdef12"]])

    def test_undecodable_task_file_is_skipped_not_raised(self) -> None:
        # UnicodeDecodeError is a ValueError but not a JSONDecodeError, so the
        # original handler let it escape and error the whole Claude collector.
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp) / "abcdef12-0000-0000-0000-000000000000"
            session.mkdir()
            (session / "1.json").write_bytes(b'{"subject": "\xff\xfe bad utf-8"}')
            (session / "2.json").write_text(
                json.dumps({"id": "2", "subject": "good", "status": "pending"}),
                encoding="utf-8",
            )
            with store_patch(TASKS_DIR=str(tmp)):
                tasks = claude_collector.load_tasks(runtime()[0])

        self.assertEqual(["good"], [t["subject"] for t in tasks["abcdef12"]])

    def test_diag_survives_an_unencodable_stream(self) -> None:
        class AsciiOnly(io.TextIOBase):
            def __init__(self) -> None:
                self.written: list[str] = []

            def write(self, s: str) -> int:
                s.encode("ascii")  # raises UnicodeEncodeError like a redirected log
                self.written.append(s)
                return len(s)

        stream = AsciiOnly()
        with contextlib.redirect_stdout(stream):
            runtime_io.diag("collector error: café ☕", print)
        self.assertIn("caf\\xe9", "".join(stream.written))

    def test_a_closed_stream_costs_one_line_not_the_diagnostics(self) -> None:
        """Losing stdout mid-run must not raise, and must not leave the writer
        broken either. "Did not raise" alone would pass an implementation that
        silently stopped writing for the rest of the process."""
        closed = io.StringIO()
        closed.close()
        with contextlib.redirect_stdout(closed):
            runtime_io.diag("swallowed", print)

        recovered = io.StringIO()
        with contextlib.redirect_stdout(recovered):
            runtime_io.diag("written after the failure", print)

        self.assertEqual("written after the failure\n", recovered.getvalue())


class ReviewFixTest(unittest.TestCase):
    """Regressions found by the adversarial review passes on PR #7."""

    NOW = 1_700_000_000.0

    @unittest.skipIf(os.name == "nt", "POSIX permission bits; Windows uses ACLs")
    def test_an_unreadable_parent_reports_inaccessible_not_missing(self) -> None:
        # isdir()/isfile() swallow OSError and return False, so a candidate
        # under a locked parent looked simply absent.
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp) / "locked"
            (parent / "inner").mkdir(parents=True)
            parent.chmod(0o000)
            try:
                report = diagnostics.candidate_report(str(parent / "inner"))
            finally:
                parent.chmod(0o700)

        self.assertEqual("inaccessible", report["kind"])
        self.assertIn("PermissionError", report["error"])

    def test_candidate_report_survives_a_listable_but_unreadable_directory(self) -> None:
        # Platform-independent: the Windows failure mode is an ACL or a
        # Defender lock, which surfaces as listdir raising, not as a mode bit.
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(os, "scandir", side_effect=PermissionError("locked")),
        ):
            report = diagnostics.candidate_report(tmp)
        self.assertEqual("directory", report["kind"])
        self.assertFalse(report["readable"])
        self.assertIn("PermissionError", report["error"])

    def test_env_paths_are_not_stripped(self) -> None:
        # Trailing whitespace is legal in a POSIX path, and XDG_DATA_HOME was
        # honoured before this resolver existed — stripping it would move an
        # existing store out from under a macOS or Linux user.
        roots = runtime_config.resolve_store_roots(
            platform_name="darwin", environ={"XDG_DATA_HOME": "/data/Agent Data "}, home="/h"
        )
        self.assertEqual("/data/Agent Data /opencode", roots["opencode.data"][0])
        # Whitespace-only still counts as unset.
        blank = runtime_config.resolve_store_roots(
            platform_name="darwin", environ={"XDG_DATA_HOME": "   "}, home="/h"
        )
        self.assertEqual("/h/.local/share/opencode", blank["opencode.data"][0])


class VerificationFixTest(unittest.TestCase):
    """Regressions found by the adversarial pass that tried to refute the fixes."""

    NOW = 1_700_000_000.0

    FUTURE = NOW + 86_400

    @unittest.skipIf(os.name == "nt", "POSIX symlinks and FIFOs")
    def test_special_files_are_not_reported_as_readable_stores(self) -> None:
        # stat() follows symlinks, so a dangling one looked absent, and every
        # non-directory looked like a readable regular file.
        with tempfile.TemporaryDirectory() as tmp:
            dangling = Path(tmp) / "dangling"
            dangling.symlink_to(Path(tmp) / "nowhere")
            fifo = Path(tmp) / "pipe"
            os.mkfifo(fifo)
            self.assertEqual("broken symlink", diagnostics.candidate_report(str(dangling))["kind"])
            self.assertEqual("special file", diagnostics.candidate_report(str(fifo))["kind"])


class GlobUnderTest(unittest.TestCase):
    HOSTILE = "A [Contractor]"

    def test_metacharacters_in_the_root_are_treated_literally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / self.HOSTILE
            (root / "sub").mkdir(parents=True)
            (root / "sub" / "found.jsonl").write_text("{}\n")

            self.assertEqual([], glob.glob(str(root / "*" / "*.jsonl")))  # the old behavior
            self.assertEqual(
                [str(root / "sub" / "found.jsonl")],
                runtime_io.glob_under(str(root), "*", "*.jsonl"),
            )

    def test_results_are_sorted_for_deterministic_tie_breaks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("c.jsonl", "a.jsonl", "b.jsonl"):
                (Path(tmp) / name).write_text("{}\n")
            found = [Path(p).name for p in runtime_io.glob_under(str(tmp), "*.jsonl")]
        self.assertEqual(["a.jsonl", "b.jsonl", "c.jsonl"], found)


class AnyGlobUnderTest(unittest.TestCase):
    """The existence probes, beside the sorting readers they are not."""

    HOSTILE = "A [Contractor]"

    def test_the_probe_stops_at_the_first_match(self) -> None:
        # The whole point: a predicate must not pay for matches it will never
        # read. `bool(glob_under(...))` consumes and sorts every match, so a
        # naive "drop the sorted()" fix still counts three here.
        #
        # `real_iglob` is captured before the patch because `glob.iglob` is what
        # the wrapper itself calls -- resolving it through the module inside the
        # wrapper is infinite recursion, and the test would stay red against a
        # correct implementation.
        real_iglob = glob.iglob
        consumed = 0

        def counting(pattern: str, **kwargs: Any) -> Any:
            nonlocal consumed
            for match in real_iglob(pattern, **kwargs):
                consumed += 1
                yield match

        with tempfile.TemporaryDirectory() as tmp:
            for name in ("a.db", "b.db", "c.db"):
                (Path(tmp) / name).write_text("")
            with mock.patch.object(glob, "iglob", counting):
                found = runtime_io.any_glob_under(str(tmp), "*.db")

        self.assertTrue(found)
        self.assertEqual(1, consumed)

    def test_metacharacters_in_the_root_are_treated_literally(self) -> None:
        # Same contract as `glob_under` above: a bracket in a real directory
        # name is a character class to `glob`, so the root is escaped and the
        # pattern is not.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / self.HOSTILE
            root.mkdir()
            self.assertFalse(runtime_io.any_glob_under(str(root), "*.jsonl"))
            (root / "a.jsonl").write_text("{}\n")
            self.assertTrue(runtime_io.any_glob_under(str(root), "*.jsonl"))

    def test_the_multi_root_probe_answers_across_every_store_root(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            (Path(second) / "found.jsonl").write_text("{}\n")
            with mock.patch.dict(STORE_OVERRIDES, {"claude.projects": (first, second)}):
                config, _ = runtime()
                self.assertTrue(runtime_io.any_glob_stores(config, "claude.projects", "*.jsonl"))
                self.assertFalse(runtime_io.any_glob_stores(config, "claude.projects", "*.absent"))
