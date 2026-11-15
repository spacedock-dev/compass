"""State ownership across network and process namespaces, without real host state."""

from __future__ import annotations

import contextlib
import ctypes
import dataclasses
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import mock

from compass_runtime import cli, lifecycle, terminal_client, terminal_monitor
from compass_runtime import io as runtime_io

from .support import SERVER_PATH, cfg, make_server
from .test_terminal_client import FakeDashboard, closed_port

if TYPE_CHECKING:
    from collections.abc import Callable

REAL_TIME_TESTS = True
LOCAL = {"machine": "machine-a", "boot": "boot-a", "network": "net-a", "process": "pid-a"}
REMOTE = {**LOCAL, "network": "net-b", "process": "pid-b"}


class StateOwnershipTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.config = dataclasses.replace(cfg(), state_home=self.home, state_dir=Path(self.home))
        self.port = closed_port()
        self.state = Path(lifecycle.state_path(self.config, self.port))

    def record(self, identity: dict[str, str] | None = LOCAL) -> None:
        with mock.patch.object(
            lifecycle, "environment_identity", create=True, return_value=identity
        ):
            lifecycle.write_state(self.config, self.port, started=1.0)

    def test_foreign_namespace_is_preserved_by_status_stop_sweep_and_publication(self) -> None:
        self.record(REMOTE)
        before = self.state.read_bytes()
        with mock.patch.object(lifecycle, "environment_identity", create=True, return_value=LOCAL):
            status = lifecycle.instance_status(self.config, self.port)
            self.assertEqual("unreachable", status["state"])
            self.assertNotIn("stale", lifecycle.render_status(status))
            self.assertNotIn("--stop", lifecycle.render_status(status))
            message, code = lifecycle.stop_instance(self.config, self.port)
            self.assertEqual(1, code)
            self.assertIn("cannot reach", message)
            self.assertEqual([], lifecycle.sweep_stale_states(self.config))
            with self.assertRaises(lifecycle.StateOwnershipError):
                lifecycle.write_state(self.config, self.port, started=2.0)
        self.assertEqual(before, self.state.read_bytes())

    def test_explicit_daemon_start_preserves_foreign_record(self) -> None:
        self.record(REMOTE)
        before = self.state.read_bytes()
        with (
            mock.patch.dict(os.environ, {"COMPASS_HOME": self.home}),
            mock.patch.object(lifecycle, "environment_identity", create=True, return_value=LOCAL),
            mock.patch.object(lifecycle, "fork_daemon") as fork,
            contextlib.redirect_stdout(io.StringIO()) as output,
            contextlib.redirect_stderr(output),
        ):
            code = cli.main(["--daemon", "--port", str(self.port), "--no-update-check"])
        self.assertEqual(1, code)
        self.assertIn("cannot reach", output.getvalue())
        fork.assert_not_called()
        self.assertEqual(before, self.state.read_bytes())

    def test_failed_serving_publication_does_not_remove_foreign_state(self) -> None:
        self.record(REMOTE)
        before = self.state.read_bytes()
        server = make_server()
        with (
            mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL),
            self.assertRaises(lifecycle.StateOwnershipError),
        ):
            lifecycle.serve(
                self.config, server, self.port, started=2.0, diagnostic_sink=lambda _m: None
            )
        self.assertEqual(before, self.state.read_bytes())
        self.assertEqual(-1, server.fileno())

    def test_same_environment_crash_is_swept(self) -> None:
        self.record()
        with (
            mock.patch.object(lifecycle, "environment_identity", create=True, return_value=LOCAL),
            mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
        ):
            status = lifecycle.instance_status(self.config, self.port)
            self.assertEqual("stale", status["state"])
            self.assertIn(
                terminal_client.launch_command("--daemon"), lifecycle.render_status(status)
            )
            self.assertEqual([self.port], lifecycle.sweep_stale_states(self.config))
        self.assertFalse(self.state.exists())

    def test_same_machine_reboot_is_swept_without_using_local_pids(self) -> None:
        self.record()
        with (
            mock.patch.object(
                lifecycle,
                "environment_identity",
                create=True,
                return_value={**LOCAL, "boot": "new"},
            ),
            mock.patch.object(lifecycle, "_state_process_exists", return_value=True),
        ):
            self.assertEqual([self.port], lifecycle.sweep_stale_states(self.config))

    def test_different_boot_requires_a_start_before_this_boot(self) -> None:
        self.record()
        before = self.state.read_bytes()
        for boot_start in (None, 0.5, 1.0):
            with (
                self.subTest(boot_start=boot_start),
                mock.patch.object(
                    lifecycle, "environment_identity", return_value={**LOCAL, "boot": "new"}
                ),
                mock.patch.object(lifecycle, "boot_started", create=True, return_value=boot_start),
                mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
            ):
                self.assertEqual(
                    "unreachable", lifecycle.instance_status(self.config, self.port)["state"]
                )
                self.assertEqual(1, lifecycle.stop_instance(self.config, self.port)[1])
                self.assertEqual([], lifecycle.sweep_stale_states(self.config))
                with self.assertRaises(lifecycle.StateOwnershipError):
                    lifecycle.write_state(self.config, self.port, started=3.0)
        self.assertEqual(before, self.state.read_bytes())

    def test_shared_machine_id_clone_before_local_boot_is_reclaimable(self) -> None:
        # Reboot recovery deliberately treats unregenerated cloned machine IDs as one host.
        self.record({**REMOTE, "boot": "clone-boot"})
        with (
            mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL),
            mock.patch.object(lifecycle, "boot_started", create=True, return_value=2000.0),
            mock.patch.object(lifecycle, "_state_process_exists", return_value=True),
        ):
            self.assertEqual([self.port], lifecycle.sweep_stale_states(self.config))

    def test_incomplete_new_publication_never_uses_legacy_cleanup(self) -> None:
        publish = runtime_io.atomic_write_owner_only

        def fail_origin(target: str, content: bytes | str, **_kwargs: object) -> None:
            if target.endswith(".origin"):
                raise PermissionError("origin refused")
            publish(target, content, root=self.home)

        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=fail_origin):
            lifecycle.write_state(
                self.config, self.port, started=1.0, diagnostic_sink=lambda _m: None
            )
        before = self.state.read_bytes()
        with mock.patch.object(lifecycle, "_state_process_exists", return_value=False):
            self.assertEqual(
                "unreachable", lifecycle.instance_status(self.config, self.port)["state"]
            )
            self.assertEqual(1, lifecycle.stop_instance(self.config, self.port)[1])
            self.assertEqual([], lifecycle.sweep_stale_states(self.config))
            with self.assertRaises(lifecycle.StateOwnershipError):
                lifecycle.write_state(self.config, self.port, started=2.0)
        self.assertEqual(before, self.state.read_bytes())

    def test_legacy_status_and_stop_keep_the_upgrade_behavior_even_with_a_live_pid(self) -> None:
        for pid in (99999999, os.getpid()):
            with self.subTest(pid=pid):
                self.state.write_text(json.dumps({"pid": pid, "port": self.port, "started": 1}))
                self.assertEqual(
                    "stale", lifecycle.instance_status(self.config, self.port)["state"]
                )
                message, code = lifecycle.stop_instance(self.config, self.port)
                self.assertEqual(0, code, message)
                self.assertFalse(self.state.exists())

    def test_legacy_sweep_preserves_a_live_pid_but_removes_a_crashed_writer(self) -> None:
        for pid, removed in ((os.getpid(), []), (99999999, [self.port])):
            with self.subTest(pid=pid):
                self.state.write_text(json.dumps({"pid": pid, "port": self.port, "started": 1}))
                self.assertEqual(removed, lifecycle.sweep_stale_states(self.config))
                self.assertEqual(not bool(removed), self.state.exists())

    def test_explicit_start_recovers_a_crashed_legacy_record_without_manual_deletion(self) -> None:
        self.state.write_text(json.dumps({"pid": 99999999, "port": self.port, "started": 1}))
        with (
            mock.patch.dict(os.environ, {"COMPASS_HOME": self.home}),
            mock.patch.object(cli, "build_server"),
            mock.patch.object(lifecycle, "fork_daemon", side_effect=RuntimeError("fork boundary")),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "fork boundary"),
        ):
            cli.main(["--daemon", "--port", str(self.port), "--no-update-check"])
        self.assertFalse(self.state.exists())

    def test_live_or_unknown_process_in_same_environment_is_not_stale(self) -> None:
        self.record()
        for exists in (True, None):
            with (
                self.subTest(exists=exists),
                mock.patch.object(
                    lifecycle, "environment_identity", create=True, return_value=LOCAL
                ),
                mock.patch.object(lifecycle, "_state_process_exists", return_value=exists),
            ):
                self.assertEqual(
                    "unreachable", lifecycle.instance_status(self.config, self.port)["state"]
                )
                self.assertEqual([], lifecycle.sweep_stale_states(self.config))

    def test_stop_reports_a_failed_stale_file_removal(self) -> None:
        self.record()
        with (
            mock.patch.object(lifecycle, "environment_identity", create=True, return_value=LOCAL),
            mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
            mock.patch("compass_runtime.config.remove_state_file", return_value=False),
        ):
            message, code = lifecycle.stop_instance(self.config, self.port)
        self.assertEqual(1, code)
        self.assertIn("could not remove", message)
        self.assertNotIn("removed the", message)
        self.assertTrue(self.state.exists())

    def test_origin_contains_no_capability_and_is_private(self) -> None:
        with mock.patch.object(lifecycle, "environment_identity", create=True, return_value=LOCAL):
            lifecycle.write_state(
                self.config, self.port, started=1.0, capabilities={"claude": "secret"}
            )
        origin = Path(lifecycle.origin_path(self.config, self.port))
        self.assertNotIn("secret", origin.read_text())
        if os.name != "nt":
            self.assertEqual(0o600, origin.stat().st_mode & 0o777)

    def test_mismatched_origin_does_not_authorize_removal(self) -> None:
        self.record()
        origin = Path(lifecycle.origin_path(self.config, self.port))
        data = json.loads(origin.read_text())
        data["started"] = 9.0
        origin.write_text(json.dumps(data))
        with (
            mock.patch.object(lifecycle, "environment_identity", create=True, return_value=LOCAL),
            mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
        ):
            self.assertEqual([], lifecycle.sweep_stale_states(self.config))

    @unittest.skipIf(os.name == "nt", "POSIX special files")
    def test_origin_fifo_and_symlink_are_refused_without_blocking(self) -> None:
        self.record()
        origin = Path(lifecycle.origin_path(self.config, self.port))
        target = Path(self.home, "target")
        target.write_bytes(origin.read_bytes())
        origin.unlink()
        for special in ("fifo", "link"):
            with self.subTest(special=special):
                if special == "fifo":
                    os.mkfifo(origin)
                else:
                    origin.symlink_to(target)
                with (
                    mock.patch.object(
                        lifecycle, "environment_identity", create=True, return_value=LOCAL
                    ),
                    mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
                ):
                    self.assertEqual([], lifecycle.sweep_stale_states(self.config))
                origin.unlink()
        self.assertTrue(self.state.exists())

    def test_malformed_state_and_origin_are_not_a_reboot_death_proof(self) -> None:
        self.record()
        state = json.loads(self.state.read_text())
        origin = Path(lifecycle.origin_path(self.config, self.port))
        record = json.loads(origin.read_text())
        state["pid"] = record["pid"] = None
        self.state.write_text(json.dumps(state))
        origin.write_text(json.dumps(record))
        with mock.patch.object(
            lifecycle, "environment_identity", return_value={**LOCAL, "boot": "new"}
        ):
            self.assertEqual([], lifecycle.sweep_stale_states(self.config))

    def test_unrepresentable_start_time_is_unknown_instead_of_raising(self) -> None:
        self.record()
        origin = Path(lifecycle.origin_path(self.config, self.port))
        for path in (self.state, origin):
            data = json.loads(path.read_text())
            data["started"] = 10**400
            path.write_text(json.dumps(data))
        with mock.patch.object(
            lifecycle, "environment_identity", return_value={**LOCAL, "boot": "new"}
        ):
            self.assertEqual(
                "unreachable", lifecycle.instance_status(self.config, self.port)["state"]
            )
            self.assertEqual([], lifecycle.sweep_stale_states(self.config))

    def test_boolean_origin_pid_does_not_authorize_cleanup(self) -> None:
        self.record()
        origin = Path(lifecycle.origin_path(self.config, self.port))
        for path, pid in ((self.state, 1), (origin, True)):
            data = json.loads(path.read_text())
            data["pid"] = pid
            path.write_text(json.dumps(data))
        with mock.patch.object(
            lifecycle, "environment_identity", return_value={**LOCAL, "boot": "new"}
        ):
            self.assertEqual([], lifecycle.sweep_stale_states(self.config))

    def test_origin_write_failure_still_tracks_ownership_for_clean_exit(self) -> None:
        publish = runtime_io.atomic_write_owner_only

        def fail_origin(target: str, content: bytes | str, **_kwargs: object) -> None:
            if target.endswith(".origin"):
                raise PermissionError("origin refused")
            publish(target, content, root=self.home)

        with (
            mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL),
            mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=fail_origin),
        ):
            published = lifecycle.write_state(
                self.config, self.port, started=1.0, diagnostic_sink=lambda _m: None
            )
        self.assertTrue(published)
        self.assertTrue(lifecycle.remove_state(self.config, self.port, owner_started=1.0))
        self.assertFalse(self.state.exists())

    def test_busy_state_lock_refuses_publication(self) -> None:
        self.record()
        before = self.state.read_bytes()
        with (
            runtime_io.held_file_lock(
                lifecycle.state_path(self.config, self.port) + ".lock", wait=0
            ),
            self.assertRaises(lifecycle.StateOwnershipError),
        ):
            lifecycle.write_state(self.config, self.port, started=2.0)
        self.assertEqual(before, self.state.read_bytes())

    def test_replacement_after_start_preflight_is_preserved_at_publication(self) -> None:
        self.record()
        origin = Path(lifecycle.origin_path(self.config, self.port))
        with (
            mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL),
            mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
        ):
            self.assertIsNone(lifecycle.start_refusal(self.config, self.port))
            data = json.loads(origin.read_text())
            data["environment"] = REMOTE
            origin.write_text(json.dumps(data))
            before = (self.state.read_bytes(), origin.read_bytes())
            with self.assertRaises(lifecycle.StateOwnershipError):
                lifecycle.write_state(self.config, self.port, started=2.0)
            self.assertEqual(before, (self.state.read_bytes(), origin.read_bytes()))

    def test_start_preflight_accepts_a_home_that_has_not_been_created(self) -> None:
        config = dataclasses.replace(self.config, state_home=str(Path(self.home, "new")))
        self.assertIsNone(lifecycle.start_refusal(config, self.port))

    def test_removal_rechecks_a_port_that_became_occupied(self) -> None:
        original_probe = lifecycle.probe_port
        with FakeDashboard() as fake:
            with mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL):
                lifecycle.write_state(self.config, self.port, started=1.0)
            target_config = self.config
            # A peer can bind between the caller's status probe and the lock-held mutation.
            with (
                mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL),
                mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
                mock.patch.object(
                    lifecycle,
                    "probe_port",
                    side_effect=lambda _port, **kw: original_probe(fake.port, **kw),
                ),
            ):
                self.assertFalse(lifecycle.remove_state(target_config, self.port))
        self.assertTrue(self.state.exists())

    def test_stop_rechecks_replacement_after_legacy_status(self) -> None:
        self.state.write_text(json.dumps({"pid": 99999999, "port": self.port, "started": 1}))

        def replace(_config: object, _port: int) -> bool:
            self.state.unlink()
            self.record(REMOTE)
            return True

        with (
            mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL),
            mock.patch.object(lifecycle, "await_release", side_effect=replace),
        ):
            message, code = lifecycle.stop_instance(self.config, self.port)
        self.assertEqual(1, code, message)
        self.assertTrue(self.state.exists())


class SystemIdentityFileTest(unittest.TestCase):
    def test_root_owned_os_identity_is_readable_to_an_ordinary_user(self) -> None:
        # The harness opener deliberately rejects root-owned content. OS identity
        # is root-owned on Linux, and needs its own bounded external-input read.
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "identity")
            path.write_text("machine")
            actual = os.fstat

            def owned_by_root(fd: int) -> os.stat_result:
                values = list(actual(fd))
                values[4] = 0
                return os.stat_result(values)

            with (
                mock.patch.object(os, "getuid", return_value=501, create=True),
                mock.patch.object(os, "fstat", side_effect=owned_by_root),
            ):
                self.assertEqual("machine", lifecycle._identity_text(str(path)))

    @unittest.skipIf(os.name == "nt", "POSIX special files")
    def test_system_identity_rejects_links_fifos_and_oversized_content(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "identity")
            path.write_text("x" * 1025)
            self.assertEqual("", lifecycle._identity_text(str(path)))
            link = Path(home, "link")
            link.symlink_to(path)
            with self.assertRaises(OSError):
                lifecycle._identity_text(str(link))
            fifo = Path(home, "fifo")
            os.mkfifo(fifo)
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys;from compass_runtime import lifecycle;\ntry: lifecycle._identity_text(sys.argv[1])\nexcept OSError: sys.exit(0)\nsys.exit(1)",
                    str(fifo),
                ],
                cwd=SERVER_PATH.parent,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)


class WindowsDeathProofTest(unittest.TestCase):
    def test_missing_process_handle_needs_an_absence_error(self) -> None:
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 0
        for error, expected in ((87, False), (5, True), (8, None)):
            with (
                self.subTest(error=error),
                mock.patch.object(sys, "platform", "win32"),
                mock.patch.object(ctypes, "WinDLL", create=True, return_value=kernel),
                mock.patch.object(ctypes, "get_last_error", create=True, return_value=error),
            ):
                self.assertIs(expected, lifecycle._state_process_exists(99999999))


class UnreachableClientTest(unittest.TestCase):
    def test_read_commands_name_checked_ports_and_home(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            port = closed_port()
            Path(home, f"compass-{port}.json").write_text("tokens must never be opened")
            env = {"COMPASS_HOME": home, "CLAUDE_CODE_SESSION_ID": "caller"}
            actions: tuple[Callable[[], int], ...] = (
                lambda: terminal_client.run_sessions(port=port, environ=env),
                lambda: terminal_client.run_project(port=port, environ=env),
                lambda: terminal_client.run_goal(
                    terminal_client.GoalRequest(), port=port, environ=env
                ),
            )
            for action in actions:
                with (
                    self.subTest(action=action),
                    contextlib.redirect_stderr(io.StringIO()) as error,
                ):
                    self.assertEqual(1, action())
                message = error.getvalue()
                self.assertIn(str(port), message)
                self.assertIn(home, message)
                self.assertIn("cannot reach", message)
                self.assertIn("container or sandbox", message)
                self.assertIn(terminal_client.launch_command("--daemon"), message)

    def test_unrelated_record_does_not_veto_default_or_explicit_target(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            remote = closed_port()
            path = Path(home, f"compass-{remote}.json")
            path.write_text("tokens")
            target = closed_port()
            for chosen in (None, target):
                started: list[int] = []
                with mock.patch.object(terminal_client, "DEFAULT_PORT", target):
                    terminal_client.ensure_dashboard(
                        home, port=chosen, spend=True, own_version="x", start=started.append
                    )
                self.assertEqual([target], started)
                self.assertEqual("tokens", path.read_text())

    def test_delegated_unknown_target_refusal_names_the_exact_file(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            port = closed_port()
            path = Path(home, f"compass-{port}.json")
            path.write_text("tokens")
            with mock.patch.dict(os.environ, {"COMPASS_HOME": home}):
                result = terminal_client.ensure_dashboard(
                    home, port=port, spend=True, own_version="x", no_update_check=True
                )
            self.assertIsInstance(result, terminal_client.Refusal)
            assert isinstance(result, terminal_client.Refusal)
            self.assertIn(str(path), result.message)
            self.assertEqual("tokens", path.read_text())

    def test_drift_summary_and_monitor_delegate_dead_target_recovery(self) -> None:
        for legacy in (False, True):
            for action in ("drift", "summary", "monitor"):
                with (
                    self.subTest(action=action, legacy=legacy),
                    tempfile.TemporaryDirectory() as home,
                ):
                    port = closed_port()
                    config = dataclasses.replace(cfg(), state_home=home, state_dir=Path(home))
                    path = Path(lifecycle.state_path(config, port))
                    with mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL):
                        lifecycle.write_state(config, port, started=1.0)
                    if legacy:
                        data = json.loads(path.read_text())
                        data.pop("state_format")
                        path.write_text(json.dumps(data))
                        Path(lifecycle.origin_path(config, port)).unlink()
                    started: list[int] = []

                    def delegated(
                        argv: list[str], **_kwargs: object
                    ) -> subprocess.CompletedProcess[bytes]:
                        # Exercise the real CLI ownership/sweep boundary without detaching a daemon.
                        with (
                            mock.patch.object(cli, "build_server"),
                            mock.patch.object(
                                lifecycle, "fork_daemon", side_effect=RuntimeError("fork boundary")
                            ),
                        ):
                            try:
                                code = cli.main(argv[3:])
                            except RuntimeError as exc:
                                self.assertEqual("fork boundary", str(exc))
                                started.append(port)
                                code = 0
                        return subprocess.CompletedProcess(argv, code, b"", b"")

                    env = {"COMPASS_HOME": home, "CLAUDE_CODE_SESSION_ID": "caller"}
                    with (
                        mock.patch.dict(os.environ, env),
                        mock.patch.object(terminal_client, "DEFAULT_PORT", port),
                        mock.patch.object(lifecycle, "environment_identity", return_value=LOCAL),
                        mock.patch.object(lifecycle, "_state_process_exists", return_value=False),
                        mock.patch.object(lifecycle, "pid_exists", return_value=False),
                        mock.patch.object(subprocess, "run", side_effect=delegated),
                        mock.patch.object(terminal_monitor, "spawn") as spawn,
                        contextlib.redirect_stdout(io.StringIO()),
                        contextlib.redirect_stderr(io.StringIO()),
                    ):
                        if action == "drift":
                            terminal_client.run_drift(environ=env)
                        elif action == "summary":
                            terminal_client.run_summary(
                                terminal_client.SummaryRequest(), environ=env
                            )
                        else:
                            terminal_client.run_monitor(environ=env)
                    self.assertEqual([port], started)
                    self.assertFalse(path.exists())
                    spawn.assert_not_called()

    def test_a_client_in_another_copy_reads_a_dashboard_of_another_release(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            FakeDashboard(
                version="0.0.1", answers={"/api/sessions": (200, {}, b'{"sessions": []}')}
            ) as fake,
        ):
            copied = Path(home, "copied-skill")
            shutil.copytree(
                SERVER_PATH.parent, copied, ignore=shutil.ignore_patterns("tests", "__pycache__")
            )
            result = subprocess.run(
                [sys.executable, str(copied / "server.py"), "--sessions", "--port", str(fake.port)],
                env={**os.environ, "COMPASS_HOME": home},
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(("GET", "/api/sessions"), fake.requests)

    def test_no_file_preserves_exact_sentence_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            result = terminal_client.ensure_dashboard(
                home, port=closed_port(), spend=False, own_version=None
            )
        self.assertIsInstance(result, terminal_client.Refusal)
        assert isinstance(result, terminal_client.Refusal)
        self.assertEqual(terminal_client.sentence("not_running"), result.message)
        self.assertEqual(1, result.code)

    def test_health_reply_after_045_seconds_has_same_verdict_for_both_clients(self) -> None:
        with FakeDashboard(
            delays={"/api/health": 0.45}, answers={"/api/sessions": (200, {}, b'{"sessions": []}')}
        ) as fake:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, terminal_client.run_sessions(port=fake.port, environ={}))
            self.assertEqual("compass", lifecycle.probe_port(fake.port)[0])
