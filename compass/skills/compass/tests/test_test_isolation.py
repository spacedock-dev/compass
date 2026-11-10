"""Real test servers must not inherit the production update-check default."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import cli, update_check

from . import support


class UpdateCheckIsolationTest(unittest.TestCase):
    def test_shared_configs_never_reserve_or_fetch_an_update(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            with (
                support.config_patch(state_home=home),
                mock.patch.object(update_check, "fetch_release") as fetch,
            ):
                for config in (support.cfg(), support.make_config(state_home=home)):
                    self.assertTrue(config.update_check_disabled)
                    update_check.UpdateChecker(config).tick()
            fetch.assert_not_called()
            self.assertEqual([], list(Path(home).iterdir()))

    def test_real_launches_disable_checks_through_the_public_cli(self) -> None:
        command = support.server_command("--daemon", "--port", "4553")
        args = cli.build_parser().parse_args(command[2:])
        config, _ = cli.build_runtime(args, started=1)
        self.assertTrue(config.update_check_disabled)
        self.assertTrue(args.daemon)

    def test_unmocked_update_fetches_are_refused_before_sending(self) -> None:
        with self.assertRaisesRegex(AssertionError, "test attempted a live update check"):
            update_check.fetch_release(support.make_config(update_check_disabled=False))

    def test_direct_and_launcher_subprocesses_cannot_omit_the_opt_out(self) -> None:
        for prefix in (
            [sys.executable],
            [sys.executable, str(support.SERVER_PATH.parent / "launch.py")],
        ):
            with self.subTest(prefix=prefix), mock.patch.object(support, "_REAL_POPEN_INIT") as run:
                support._refusing_popen_init(
                    object(), [*prefix, str(support.SERVER_PATH), "--daemon"]
                )
                command = run.call_args.args[1]
                args = cli.build_parser().parse_args(command[len(prefix) + 1 :])
                config, _ = cli.build_runtime(args, started=1)
                self.assertTrue(config.update_check_disabled)

    def test_the_bare_version_keeps_its_light_entry_path(self) -> None:
        command = [sys.executable, str(support.SERVER_PATH), "--version"]
        with mock.patch.object(support, "_REAL_POPEN_INIT") as run:
            support._refusing_popen_init(object(), command)
        self.assertEqual(command, run.call_args.args[1])

    def test_every_automatic_start_keeps_checks_disabled(self) -> None:
        for arguments in (
            ["--drift"],
            ["--drift", "--status"],
            ["--drift", "--internal=on"],
            ["--monitor"],
            ["--summary"],
            ["--goal", "my goal"],
            ["--goal", "--clear"],
            ["--goal", "--adopt"],
        ):
            command = [sys.executable, str(support.SERVER_PATH), *arguments]
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(support, "_REAL_POPEN_INIT") as run,
            ):
                support._refusing_popen_init(object(), command)
            self.assertIn("--no-update-check", run.call_args.args[1])

    def test_commands_that_never_start_a_dashboard_keep_their_arguments(self) -> None:
        for arguments in (
            ["--footer"],
            ["--footer", "--session", "claude:one"],
            ["--monitor", "--off", "--session", "claude:one"],
            ["--sessions"],
            ["--project"],
            ["--goal", "--session", "claude:one"],
            ["--goal", "--session", "claude:one", "--port=4554"],
            ["--summaries", "off"],
            ["--pause-model-calls"],
            ["--forget"],
            ["--monitor-sidecar", "one", "generation"],
        ):
            command = [sys.executable, str(support.SERVER_PATH), *arguments]
            with (
                self.subTest(arguments=arguments),
                mock.patch.object(support, "_REAL_POPEN_INIT") as run,
            ):
                support._refusing_popen_init(object(), command)
            self.assertEqual(command, run.call_args.args[1])
