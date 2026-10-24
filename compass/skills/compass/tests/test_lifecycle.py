from __future__ import annotations

import argparse
import contextlib
import dataclasses
import errno
import http.client
import http.server
import io
import json
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import cli, http_api, lifecycle
from compass_runtime import io as runtime_io

from . import support
from .support import (
    SERVE_POLL_INTERVAL,
    SERVER_PATH,
    SERVER_STARTED,
    cfg,
    config_patch,
    frontend_page,
    make_runtime,
    make_server,
    poll_fast,
    serve_until_closed,
    short_circuit_native_notifications,
    state_of,
    without_focus_meta,
)

if TYPE_CHECKING:
    import email.message


class InstalledContractCharacterizationTest(unittest.TestCase):
    """The installed executable contract that extraction must preserve."""

    OWNED_INSTANCE_READY_TIMEOUT_SEC = 60.0

    def setUp(self) -> None:
        with state_of().hook_lock:
            state_of().hook_notifications.clear()
            state_of().last_popup.clear()
            state_of().last_popup_message.clear()
            state_of().last_session_state.clear()
            state_of().hook_generation.clear()
        with state_of().collect_memo_lock:
            state_of().snapshot.clear()
        # Route-shape tests run the notification code but do not assert native
        # delivery, so keep its osascript process off the host.
        short_circuit_native_notifications(self)

    def tearDown(self) -> None:
        with state_of().collect_memo_lock:
            state_of().snapshot.clear()

    @staticmethod
    def _candidate_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    @staticmethod
    def _clean_env(compass_home: Path) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        env["PYTHONNOUSERSITE"] = "1"
        env["COMPASS_HOME"] = str(compass_home)
        return env

    @staticmethod
    def _response(
        port: int,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, email.message.Message, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, response.headers, response.read()
        finally:
            conn.close()

    def _await_owned_instance(
        self, port: int, proc: subprocess.Popen[bytes], state_path: Path
    ) -> None:
        deadline = time.monotonic() + self.OWNED_INSTANCE_READY_TIMEOUT_SEC
        last_observation = "no health response"
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=2)
                self.fail(f"launcher exited: {stdout!r} {stderr!r}")
            try:
                code, _, body = self._response(port, "GET", "/api/health")
                health = json.loads(body) if code == 200 else {}
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                last_observation = f"health request failed: {type(exc).__name__}: {exc}"
                time.sleep(0.05)
                continue
            if code != 200:
                last_observation = f"health returned HTTP {code}"
                time.sleep(0.05)
                continue
            if health.get("pid") != proc.pid:
                self.fail(f"port {port} is served by pid {health.get('pid')}, not child {proc.pid}")
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                last_observation = (
                    f"owned health from pid {proc.pid}, but state {state_path} was unreadable: "
                    f"{type(exc).__name__}: {exc}"
                )
                time.sleep(0.05)
                continue
            self.assertEqual(proc.pid, state.get("pid"))
            self.assertEqual(port, state.get("port"))
            return
        self.fail(
            f"owned child {proc.pid} did not become healthy with its state file within "
            f"{self.OWNED_INSTANCE_READY_TIMEOUT_SEC:.0f}s: {last_observation}"
        )

    def _owns_instance(self, port: int, proc: subprocess.Popen[bytes], state_path: Path) -> bool:
        if proc.poll() is not None:
            return False
        try:
            code, _, body = self._response(port, "GET", "/api/health")
            health = json.loads(body) if code == 200 else {}
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return False
        return health.get("pid") == proc.pid and state.get("pid") == proc.pid

    def test_launcher_runs_from_an_unrelated_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = self._clean_env(root / "state")
            proc = subprocess.run(
                [sys.executable, str(SERVER_PATH), "--diagnose", "--json"],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertIn("platform", json.loads(proc.stdout))

    def test_cli_help_diagnose_status_stop_and_invalid_arguments_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            port = self._candidate_port()
            env = self._clean_env(root / "state")
            state_path = root / "state" / f"compass-{port}.json"
            server = subprocess.Popen(
                [sys.executable, str(SERVER_PATH), "--port", str(port)],
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            cases = (
                ("help", ["--help"], 0, "usage:"),
                ("diagnose", ["--diagnose", "--json"], 0, '"harnesses"'),
                ("status", ["--port", str(port), "--status"], 0, "running"),
                ("stop", ["--port", str(port), "--stop"], 0, "stopped"),
                ("invalid", ["--unknown-flag"], 2, "unrecognized arguments"),
            )
            try:
                self._await_owned_instance(port, server, state_path)
                for label, args, expected, text in cases:
                    with self.subTest(path=label):
                        proc = subprocess.run(
                            [sys.executable, str(SERVER_PATH), *args],
                            cwd=root,
                            env=env,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            timeout=30,
                            check=False,
                        )
                        self.assertEqual(expected, proc.returncode, proc.stderr)
                        self.assertIn(text, proc.stdout + proc.stderr)
            finally:
                if self._owns_instance(port, server, state_path):
                    subprocess.run(
                        [sys.executable, str(SERVER_PATH), "--port", str(port), "--stop"],
                        cwd=root,
                        env=env,
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
                if server.poll() is None:
                    server.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        server.wait(timeout=5)
                if server.poll() is None:
                    server.kill()
                server.wait(timeout=5)
                if server.stdout is not None:
                    server.stdout.close()
                if server.stderr is not None:
                    server.stderr.close()

    def test_daemon_respawn_uses_the_absolute_stable_launcher(self) -> None:
        args = argparse.Namespace(
            port=4553,
            window_hours=24.0,
            no_spacedock=False,
            no_usage=False,
            no_events=False,
            no_irreversible=False,
            no_dismiss=False,
            no_ask=False,
            no_git=False,
            no_focus=False,
            no_history=False,
            history_days=14.0,
            history_max_bytes=1_048_576,
            daemon=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_file = str(Path(tmp) / "compass.log")
            with mock.patch.object(subprocess, "Popen") as popen:
                popen.return_value = mock.Mock(pid=1)
                lifecycle.spawn_detached(cfg(), args, log_file)
        self.assertEqual(str(SERVER_PATH), popen.call_args.args[0][1])

    def test_copied_plugin_launches_without_repository_imports(self) -> None:  # noqa: PLR0915
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            copied_plugin = root / "copied-plugin" / "compass"
            shutil.copytree(SERVER_PATH.parents[2], copied_plugin)
            launcher = copied_plugin / "skills" / "compass" / "server.py"
            copied_skill = launcher.parent.resolve()
            copied_web = copied_skill / "compass_runtime" / "web"
            for name in (
                "react.html",
                "react.integrity.json",
                "react-licenses.txt",
                "page.py",
                *(name for name, _slot in frontend_page.FONT_ASSETS),
            ):
                with self.subTest(shipped_file=name):
                    self.assertTrue((copied_web / name).is_file())
            cwd = root / "unrelated"
            cwd.mkdir()
            compass_home = root / "state"
            port = self._candidate_port()
            env = self._clean_env(compass_home)
            probe = f"""
import importlib
import json
import pkgutil
import sys
from pathlib import Path

repository = Path({str(SERVER_PATH.parents[4])!r}).resolve()
cwd = Path.cwd().resolve()
sys.path[:] = [
    entry for entry in sys.path
    if not Path(entry or cwd).resolve().is_relative_to(repository)
]
skill = Path({str(copied_skill)!r}).resolve()
sys.path.insert(0, str(skill))
import compass_runtime
from compass_runtime.web import page

origins = {{}}
modules = [compass_runtime]
modules.extend(
    importlib.import_module(found.name)
    for found in pkgutil.walk_packages(
        compass_runtime.__path__, compass_runtime.__name__ + "."
    )
)
for module in modules:
    origins[module.__name__] = str(Path(module.__file__).resolve())
assets = {{
    name: str(page.asset_path(name).resolve())
    for name in (
        "react.html", "react.integrity.json", "react-licenses.txt",
        *(name for name, _slot in page.FONT_ASSETS),
    )
}}
print(json.dumps({{
    "origins": origins,
    "assets": assets,
    "page_size": len(page.load_frontend_page()),
}}))
"""
            origin_probe = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
            self.assertEqual(0, origin_probe.returncode, origin_probe.stderr)
            discovered = json.loads(origin_probe.stdout)
            for origin in [*discovered["origins"].values(), *discovered["assets"].values()]:
                self.assertTrue(Path(origin).is_relative_to(copied_skill), origin)
            # The repository's own page, not a pinned figure. This subject is whether the
            # copy loads its own verified files; `react.integrity.json` owns the digest.
            self.assertEqual(len(frontend_page.load_frontend_page()), discovered["page_size"])
            state_path = compass_home / f"compass-{port}.json"
            proc = subprocess.Popen(
                [sys.executable, str(launcher), "--port", str(port)],
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            owned = False
            try:
                self._await_owned_instance(port, proc, state_path)
                owned = True
                code, headers, body = self._response(port, "GET", "/")
                self.assertEqual(200, code)
                self.assertEqual("text/html; charset=utf-8", headers["Content-Type"])
                # The copy's own verified page, plus the focus capability `cli.main`
                # injects after it. Compared with that element stripped, because
                # the subject here is whether the copied installation loads
                # its page from its own files — the token is per run and cannot
                # be known from outside the process that minted it.
                self.assertEqual(frontend_page.load_frontend_page(), without_focus_meta(body))
                self.assertIn(b'<meta name="compass-focus" content="', body)
                code, headers, body = self._response(port, "GET", "/?next=true")
                self.assertEqual(404, code)
                self.assertNotEqual(frontend_page.load_frontend_page(), body)
            finally:
                stop: subprocess.CompletedProcess[bytes] | None = None
                # A live owned process has exclusive possession of its port,
                # so the copied --stop command cannot reach a foreign server.
                if owned and self._owns_instance(port, proc, state_path):
                    stop = subprocess.run(
                        [sys.executable, str(launcher), "--port", str(port), "--stop"],
                        cwd=cwd,
                        env=env,
                        capture_output=True,
                        timeout=15,
                        check=False,
                    )
                if proc.poll() is None:
                    proc.terminate()
                    with contextlib.suppress(subprocess.TimeoutExpired):
                        proc.wait(timeout=5)
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=5)
                if proc.stdout is not None:
                    proc.stdout.close()
                if proc.stderr is not None:
                    proc.stderr.close()
                if owned:
                    self.assertIsNotNone(stop, "owned launcher disappeared before safe --stop")
                    assert stop is not None
                    self.assertEqual(0, stop.returncode, stop.stderr.decode("utf-8", "replace"))
                    self.assertTrue(lifecycle.await_release(cfg(), port, timeout=5))
                    self.assertEqual([], list(compass_home.iterdir()))

    def test_windows_detached_argv_preserves_an_absolute_launcher_path(self) -> None:
        # The respawn target is config.launcher_path, so a Windows path survives
        # verbatim. Asserted as the WHOLE argv: a stray interpreter or a second
        # script prefixed in front of it is exactly the regression this catches,
        # and checking one element could not see it.
        windows_launcher = "C:\\plugin\\server.py"
        config = dataclasses.replace(cfg(), launcher_path=Path(windows_launcher))
        args = argparse.Namespace(
            port=4553,
            window_hours=24.0,
            no_spacedock=False,
            no_usage=False,
            no_events=False,
            no_irreversible=False,
            no_dismiss=False,
            no_ask=False,
            no_git=False,
            no_focus=False,
            no_history=False,
            history_days=14.0,
            history_max_bytes=1_048_576,
            daemon=True,
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(subprocess, "DETACHED_PROCESS", 8, create=True),
            mock.patch.object(subprocess, "CREATE_NEW_PROCESS_GROUP", 512, create=True),
            mock.patch.object(subprocess, "Popen") as popen,
        ):
            popen.return_value = mock.Mock(pid=1)
            lifecycle.spawn_detached(config, args, str(Path(tmp) / "compass.log"))
        self.assertEqual(
            [
                sys.executable,
                windows_launcher,
                "--port",
                "4553",
                "--window-hours",
                "24.0",
            ],
            popen.call_args.args[0],
        )
        self.assertEqual(520, popen.call_args.kwargs["creationflags"])

    def test_main_and_detached_spawn_forward_current_arguments(self) -> None:
        spawned = mock.Mock(pid=99)
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(
                sys,
                "argv",
                [
                    "server.py",
                    "--port",
                    "6789",
                    "--window-hours",
                    "7.5",
                    "--no-spacedock",
                    "--daemon",
                ],
            ),
            mock.patch.object(lifecycle, "spawn_detached", return_value=spawned) as spawn,
            mock.patch.object(lifecycle, "await_spawned", return_value=("started", 0)),
            mock.patch.object(runtime_io, "diag"),
        ):
            code = cli.main()
        self.assertEqual(0, code)
        # spawn_detached takes (config, args, log_file), and the config it was
        # handed must be the one main built, not a fresh ambient read.
        spawned_config, spawned_args = spawn.call_args.args[0], spawn.call_args.args[1]
        self.assertEqual("nt", spawned_config.os_name)
        self.assertEqual(
            [
                sys.executable,
                str(spawned_config.launcher_path),
                "--port",
                "6789",
                "--window-hours",
                "7.5",
                "--no-spacedock",
            ],
            lifecycle.spawn_argv(spawned_config, spawned_args),
        )
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(subprocess, "Popen") as popen,
        ):
            popen.return_value = spawned
            lifecycle.spawn_detached(spawned_config, spawned_args, str(Path(tmp) / "compass.log"))
        # The whole argv reaches Popen, interpreter and launcher included.
        self.assertEqual(
            [
                sys.executable,
                str(spawned_config.launcher_path),
                "--port",
                "6789",
                "--window-hours",
                "7.5",
                "--no-spacedock",
            ],
            popen.call_args.args[0],
        )


class CompassServerTest(support.RuntimeTestCase):
    def test_state_file_roundtrips_and_names_itself_per_port(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
        ):
            lifecycle.write_state(cfg(), 4553, started=SERVER_STARTED)
            lifecycle.write_state(cfg(), 9999, started=SERVER_STARTED)
            self.assertTrue(os.path.exists(os.path.join(tmp, "compass-4553.json")))
            state = lifecycle.read_state(cfg(), 4553)
            assert state is not None
            self.assertEqual(os.getpid(), state["pid"])
            self.assertEqual(4553, state["port"])
            self.assertEqual(lifecycle.log_path(cfg(), 4553), state["log"])
            self.assertEqual(sys.executable, state["python"])
            # Two instances on two ports do not overwrite each other.
            other = lifecycle.read_state(cfg(), 9999)
            assert other is not None
            self.assertEqual(9999, other["port"])
            lifecycle.remove_state(cfg(), 4553)
            self.assertIsNone(lifecycle.read_state(cfg(), 4553))
            lifecycle.remove_state(cfg(), 4553)  # removing twice is not an error

    def test_read_state_returns_none_for_absent_corrupt_and_non_object_files(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
        ):
            self.assertIsNone(lifecycle.read_state(cfg(), 4553))
            Path(lifecycle.state_path(cfg(), 4553)).write_text("{not json", encoding="utf-8")
            self.assertIsNone(lifecycle.read_state(cfg(), 4553))
            Path(lifecycle.state_path(cfg(), 4553)).write_text("[1,2]", encoding="utf-8")
            self.assertIsNone(lifecycle.read_state(cfg(), 4553))

    def test_write_state_reports_and_survives_an_unwritable_home(self) -> None:
        # A dashboard that cannot write its state file still serves; --status
        # just cannot see it. This must never be fatal.
        with tempfile.TemporaryDirectory() as tmp:
            blocker = os.path.join(tmp, "home")
            Path(blocker).write_text("not a directory", encoding="utf-8")
            with mock.patch.dict(os.environ, {"COMPASS_HOME": blocker}):
                with mock.patch.object(runtime_io, "diag") as diag:
                    lifecycle.write_state(cfg(), 4553, started=SERVER_STARTED)
                self.assertTrue(diag.called)

    def test_probe_port_classifies_compass_foreign_and_closed(self) -> None:
        httpd = make_server()
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        port = httpd.server_port
        try:
            kind, health = lifecycle.probe_port(port, timeout=2)
            self.assertEqual("compass", kind)
            assert health is not None
            self.assertEqual(os.getpid(), health["pid"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)
        # Same port, now nothing listening.
        self.assertEqual(("closed", None), lifecycle.probe_port(port, timeout=1))

    def test_probe_port_calls_a_non_compass_listener_foreign(self) -> None:
        class Other(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"hi")

            def log_message(self, *args: object) -> None:
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Other)
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            # 200 but not JSON: something else owns this port. Reporting it as
            # Compass is how a stop command ends up aimed at an unrelated
            # process.
            self.assertEqual(("foreign", None), lifecycle.probe_port(httpd.server_port, timeout=2))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_probe_port_rejects_recursive_and_lookalike_health_payloads(self) -> None:
        invalid = (
            ("recursive JSON", b"[" * 2000 + b"]" * 2000),
            ("truthy ok", b'{"ok":"yes","pid":7,"port":4553,"started":1}'),
            ("boolean pid", b'{"ok":true,"pid":true,"port":4553,"started":1}'),
            ("zero pid", b'{"ok":true,"pid":0,"port":4553,"started":1}'),
            ("wrong port", b'{"ok":true,"pid":7,"port":9999,"started":1}'),
            ("missing start time", b'{"ok":true,"pid":7,"port":4553}'),
        )
        for label, body in invalid:
            with (
                self.subTest(payload=label),
                mock.patch.object(http.client, "HTTPConnection") as connection,
            ):
                response = connection.return_value.getresponse.return_value
                response.status = 200
                response.read.return_value = body
                self.assertEqual(("foreign", None), lifecycle.probe_port(4553))
                connection.return_value.close.assert_called_once_with()

    def test_instance_status_covers_running_stale_foreign_and_absent(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
        ):
            health = {"ok": True, "pid": 4242, "port": 4553, "started": 1000.0}
            with mock.patch.object(lifecycle, "probe_port", return_value=("compass", health)):
                running = lifecycle.instance_status(cfg(), 4553)
            self.assertEqual("running", running["state"])
            self.assertEqual(4242, running["pid"])

            with mock.patch.object(lifecycle, "probe_port", return_value=("closed", None)):
                self.assertEqual("absent", lifecycle.instance_status(cfg(), 4553)["state"])
                lifecycle.write_state(cfg(), 4553, started=SERVER_STARTED)
                stale = lifecycle.instance_status(cfg(), 4553)
            self.assertEqual("stale", stale["state"])
            self.assertEqual(os.getpid(), stale["pid"])

            with mock.patch.object(lifecycle, "probe_port", return_value=("foreign", None)):
                self.assertEqual("foreign", lifecycle.instance_status(cfg(), 4553)["state"])

    def test_render_status_names_the_state_and_never_suggests_a_kill(self) -> None:
        running = lifecycle.render_status(
            {"state": "running", "port": 4553, "pid": 7, "started": 1000.0, "log": "/l"}
        )
        self.assertIn("running", running)
        self.assertIn("pid 7", running)
        self.assertIn("http://127.0.0.1:4553/", running)
        stale = lifecycle.render_status({"state": "stale", "port": 4553, "pid": 7, "log": "/l"})
        self.assertIn("--stop", stale)
        foreign = lifecycle.render_status({"state": "foreign", "port": 4553, "pid": None})
        self.assertIn("another process", foreign)
        self.assertIn("Nothing was stopped", foreign)
        self.assertIn("not running", lifecycle.render_status({"state": "absent", "port": 4553}))

    def test_render_status_survives_a_started_value_it_cannot_convert(self) -> None:
        # Keep render_status defensive even though probe_port now rejects
        # non-finite values. Tests and callers can still construct a status
        # directly, and a value outside time_t must not replace a line with a
        # traceback.
        for started in (1e19, -1e19, float("inf"), float("nan")):
            with self.subTest(started=started):
                line = lifecycle.render_status(
                    {"state": "running", "port": 4553, "pid": 7, "started": started, "log": "/l"}
                )
                self.assertIn("running", line)
                self.assertIn("since unknown", line)

    def test_port_released_is_false_while_a_server_still_holds_the_port(self) -> None:
        httpd = make_server()
        port = httpd.server_port
        thread = threading.Thread(target=poll_fast(httpd), daemon=True)
        thread.start()
        try:
            self.assertFalse(lifecycle.port_released(cfg(), port), "bound and serving")
            httpd.shutdown()
            thread.join(timeout=5)
            # The accept loop has exited but the socket is still open. A connect
            # probe cannot see this state, and repeated connects fill the
            # backlog and then wrongly report the port gone; binding sees it.
            for _ in range(http_api.CompassHTTPServer.request_queue_size + 3):
                self.assertFalse(lifecycle.port_released(cfg(), port), "bound, not accepting")
        finally:
            httpd.server_close()
            thread.join(timeout=2)
        self.assertTrue(lifecycle.port_released(cfg(), port), "closed")

    def test_stop_instance_waits_for_the_port_before_claiming_it_stopped(self) -> None:
        # A server that answers the shutdown POST but never releases the port
        # must not be reported as stopped: the caller's next move is a start.
        running = {"state": "running", "port": 4553, "pid": 7, "started": 1000.0, "log": "/l"}
        with (
            mock.patch.object(lifecycle, "instance_status", return_value=running),
            mock.patch.object(lifecycle, "port_released", return_value=False) as released,
            config_patch(stop_release_timeout_sec=0.2),
            mock.patch.object(http.client, "HTTPConnection") as conn,
        ):
            conn.return_value.getresponse.return_value.status = 200
            message, code = lifecycle.stop_instance(cfg(), 4553)
        self.assertEqual(1, code)
        self.assertIn("still listening", message)
        self.assertNotIn("stopped (pid", message)
        self.assertGreater(released.call_count, 1, "it never waited")

    def test_await_release_sleeps_between_failed_probes(self) -> None:
        with (
            mock.patch.object(lifecycle, "port_released", side_effect=(False, True)) as released,
            mock.patch.object(time, "sleep") as sleep,
        ):
            self.assertTrue(lifecycle.await_release(cfg(), 4553, timeout=1))
        self.assertEqual(2, released.call_count)
        sleep.assert_called_once_with(0.05)

    def test_stop_instance_reports_a_refused_shutdown_response(self) -> None:
        running = {"state": "running", "port": 4553, "pid": 7, "started": 1000.0, "log": "/l"}
        with (
            mock.patch.object(lifecycle, "instance_status", return_value=running),
            mock.patch.object(lifecycle, "await_release") as released,
            mock.patch.object(http.client, "HTTPConnection") as connection,
        ):
            response = connection.return_value.getresponse.return_value
            response.status = 503
            message, code = lifecycle.stop_instance(cfg(), 4553)
        self.assertEqual(1, code)
        self.assertIn("refused to stop", message)
        self.assertIn("503", message)
        released.assert_not_called()
        connection.return_value.close.assert_called_once_with()

    def test_status_flag_exits_zero_only_when_running(self) -> None:
        for state, expected in (("running", 0), ("stale", 1), ("foreign", 1), ("absent", 1)):
            with (
                mock.patch.object(
                    lifecycle,
                    "instance_status",
                    return_value={"state": state, "port": 4553, "pid": 1},
                ),
                mock.patch.object(sys, "argv", ["server.py", "--status"]),
                mock.patch.object(runtime_io, "diag"),
            ):
                code = cli.main()
            self.assertEqual(expected, code, state)

    def test_stop_instance_stops_a_running_server_over_http(self) -> None:
        httpd = make_server()
        port = httpd.server_port
        loop_exited = threading.Event()
        allow_close = threading.Event()
        result: list[tuple[str, int]] = []

        def serve_with_delayed_close() -> None:
            try:
                httpd.serve_forever(SERVE_POLL_INTERVAL)
            finally:
                loop_exited.set()
                allow_close.wait(timeout=10)
                httpd.server_close()

        thread = threading.Thread(target=serve_with_delayed_close, daemon=True)
        thread.start()
        stop_thread = threading.Thread(
            target=lambda: result.append(lifecycle.stop_instance(cfg(), port)),
            daemon=True,
        )
        try:
            stop_thread.start()
            self.assertTrue(loop_exited.wait(timeout=5), "serve_forever did not stop")
            self.assertFalse(
                lifecycle.port_released(cfg(), port), "the delayed close lost its bind"
            )
            self.assertTrue(
                stop_thread.is_alive(),
                "stop_instance returned before the listener released its port",
            )
            allow_close.set()
            stop_thread.join(timeout=10)
            self.assertFalse(stop_thread.is_alive(), "stop_instance did not notice the release")
            self.assertEqual(1, len(result))
            message, code = result[0]
            self.assertEqual(0, code, message)
            self.assertIn("stopped", message)
            self.assertTrue(lifecycle.port_released(cfg(), port), "the port is still bound")
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        finally:
            allow_close.set()
            with contextlib.suppress(OSError):
                httpd.shutdown()
            stop_thread.join(timeout=2)
            thread.join(timeout=2)
            with contextlib.suppress(OSError):
                httpd.server_close()

    @unittest.skipIf(os.name == "nt", "POSIX SO_REUSEADDR/TIME_WAIT semantics")
    def test_port_release_probe_matches_the_listener_during_time_wait(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen()
        client = socket.create_connection(("127.0.0.1", port), timeout=2)
        accepted, _ = listener.accept()
        try:
            # The server endpoint closes first, putting this local address in
            # TIME_WAIT after the client observes EOF and closes. Compass's
            # listener can rebind here because it uses SO_REUSEADDR, so its
            # release probe must use the same option or report a false hold.
            accepted.close()
            self.assertEqual(b"", client.recv(1))
            client.close()
            listener.close()
            self.assertTrue(lifecycle.port_released(cfg(), port))
        finally:
            with contextlib.suppress(OSError):
                accepted.close()
            with contextlib.suppress(OSError):
                client.close()
            with contextlib.suppress(OSError):
                listener.close()

    def test_stop_instance_removes_a_stale_state_file_and_succeeds(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
        ):
            lifecycle.write_state(cfg(), 4553, started=SERVER_STARTED)
            # port_released is mocked alongside probe_port because the stale
            # branch now waits for the port too. Left live it asks the real
            # 4553, so the result would depend on what the machine is running.
            with (
                mock.patch.object(lifecycle, "probe_port", return_value=("closed", None)),
                mock.patch.object(lifecycle, "port_released", return_value=True),
            ):
                message, code = lifecycle.stop_instance(cfg(), 4553)
            self.assertEqual(0, code)
            self.assertIn("stale", message)
            self.assertIsNone(lifecycle.read_state(cfg(), 4553))

    def test_stop_instance_will_not_call_it_stopped_while_the_port_is_held(self) -> None:
        # main() removes the state file *before* it closes the listener, so a
        # stop already in progress reaches the absent/stale branches with the
        # port still bound. Exit 0 there meant "nothing running" for a port that
        # the very next start could not bind.
        for state, probe in (("stale", True), ("absent", False)):
            with (
                self.subTest(state=state),
                tempfile.TemporaryDirectory() as tmp,
                mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
            ):
                if probe:
                    lifecycle.write_state(cfg(), 4553, started=SERVER_STARTED)
                with (
                    mock.patch.object(lifecycle, "probe_port", return_value=("closed", None)),
                    mock.patch.object(lifecycle, "port_released", return_value=False),
                    config_patch(stop_release_timeout_sec=0.1),
                ):
                    message, code = lifecycle.stop_instance(cfg(), 4553)
                self.assertEqual(1, code)
                self.assertIn("still holding the port", message)
                self.assertNotIn("nothing running", message)
                if probe:
                    # It did not own the port, so it does not get to tidy up.
                    self.assertIsNotNone(lifecycle.read_state(cfg(), 4553))

    def test_stop_instance_lets_the_port_settle_a_lost_connection(self) -> None:
        # A concurrent --stop, or the page's own button, can take the server down
        # while this request is in flight. The reset that causes is not evidence
        # the stop failed, and reporting exit 1 for it broke the documented
        # unconditional-stop idempotency about 3 runs in 5.
        running = {"state": "running", "port": 4553, "pid": 7, "started": 1000.0, "log": "/l"}
        for released, expected_code, expected in ((True, 0, "stopped"), (False, 1, "could not")):
            with (
                self.subTest(released=released),
                mock.patch.object(lifecycle, "instance_status", return_value=running),
                mock.patch.object(lifecycle, "port_released", return_value=released),
                config_patch(stop_release_timeout_sec=0.1),
                mock.patch.object(http.client, "HTTPConnection") as conn,
            ):
                conn.return_value.getresponse.side_effect = ConnectionResetError(
                    errno.ECONNRESET, "Connection reset by peer"
                )
                message, code = lifecycle.stop_instance(cfg(), 4553)
            self.assertEqual(expected_code, code, message)
            self.assertIn(expected, message)

    def test_port_released_never_requests_both_reuse_and_exclusive(self) -> None:
        # The probe answers for the real listener, so it must ask for the same
        # socket options. Winsock rejects SO_REUSEADDR on a socket already
        # carrying SO_EXCLUSIVEADDRUSE (WSAEINVAL), so the two are complements
        # of one decision, never independent switches. Gating exclusive on the
        # host's getattr instead of this config's os_name made a
        # posix-configured probe on a Windows host request both and fail every
        # bind — the same split-source bug the listener already fixed.
        #
        # Both branches run on any host: the option is patched into existence,
        # and the config is what decides, not the machine.
        requested: list[int] = []
        real_setsockopt = socket.socket.setsockopt

        def traced(sock: Any, level: int, option: int, value: Any) -> Any:
            requested.append(option)
            return real_setsockopt(sock, level, option, value)

        fake_exclusive = 0xFFFB
        for os_name, wants_reuse in (("posix", True), ("nt", False)):
            with self.subTest(os_name=os_name):
                requested.clear()
                config, _ = make_runtime(os_name=os_name)
                with (
                    mock.patch.object(socket.socket, "setsockopt", traced),
                    mock.patch.object(socket, "SO_EXCLUSIVEADDRUSE", fake_exclusive, create=True),
                    # The fake option number is rejected by the OS, which warns.
                    # That is correct behaviour, but noise in test output.
                    mock.patch.object(runtime_io, "diag"),
                ):
                    lifecycle.port_released(config, 9999)

                self.assertEqual(wants_reuse, socket.SO_REUSEADDR in requested)
                self.assertEqual(not wants_reuse, fake_exclusive in requested)

    def test_port_released_only_reads_address_in_use_as_still_held(self) -> None:
        # EACCES on a privileged port says nothing about whether the port is in
        # use, and answering "held" for it made --stop wait out its whole
        # timeout and then claim an instance was still listening when it had
        # stopped. Where a bind cannot answer, the answer is not "held".
        cases = (
            (errno.EADDRINUSE, False),
            # Windows reports an in-use port as EACCES once SO_EXCLUSIVEADDRUSE
            # is in play, so it counts as held there; on POSIX it only ever means
            # privilege, which is no evidence about use at all.
            (errno.EACCES, os.name != "nt"),
            (errno.EPERM, True),
            (errno.EMFILE, True),
            (errno.ENFILE, True),
        )
        for code, expected in cases:
            with (
                self.subTest(errno=errno.errorcode.get(code, code)),
                mock.patch.object(socket, "socket", side_effect=OSError(code, os.strerror(code))),
            ):
                self.assertEqual(expected, lifecycle.port_released(cfg(), 4553))
        # A real privileged port: nothing listens on 1, but binding is refused.
        if os.name != "nt" and os.geteuid() != 0:
            self.assertTrue(lifecycle.port_released(cfg(), 1), "EACCES read as a held port")

    def test_read_state_rejects_a_corrupt_file_instead_of_raising(self) -> None:
        # json.load raises RecursionError, not ValueError, past the nesting
        # limit, and it tracebacked straight out of --status and --stop. "None if
        # there is none to trust" has to cover corrupt, not only missing.
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
        ):
            path = Path(lifecycle.state_path(cfg(), 4553))
            for label, body in (
                ("deeply nested", "[" * 30000 + "]" * 30000),
                ("truncated", '{"pid": 1'),
                ("not an object", "[1, 2, 3]"),
                ("empty", ""),
                ("oversized", "0" * (cfg().state_read_cap_bytes + 1024)),
                (
                    "oversized valid object",
                    '{"pid": 1}' + " " * cfg().state_read_cap_bytes,
                ),
                (
                    "oversized UTF-8 object",
                    json.dumps(
                        {"note": "é" * 40000},
                        ensure_ascii=False,
                    ),
                ),
            ):
                with self.subTest(body=label):
                    path.write_text(body, encoding="utf-8")
                    self.assertIsNone(lifecycle.read_state(cfg(), 4553))
                    # And the commands built on it still explain themselves.
                    with mock.patch.object(lifecycle, "probe_port", return_value=("closed", None)):
                        self.assertIn(
                            "not running",
                            lifecycle.render_status(lifecycle.instance_status(cfg(), 4553)),
                        )

    def test_daemon_explains_a_log_it_cannot_open(self) -> None:
        # ensure_compass_home() is makedirs(exist_ok=True), which succeeds for
        # an existing directory whatever its mode — so the likeliest bad home of
        # all, one that exists and is not writable, got past that guard and
        # raised in daemon_redirect_stdio after the fork, where no message can
        # reach the terminal that asked.
        if os.name == "nt":
            self.skipTest("POSIX directory modes do not apply on Windows")
        with tempfile.TemporaryDirectory() as tmp:
            home = os.path.join(tmp, "readonly")
            os.makedirs(home)
            os.chmod(home, 0o500)
            try:
                with (
                    mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
                    mock.patch.object(sys, "argv", ["server.py", "--port", "4553", "--daemon"]),
                    mock.patch.object(runtime_io, "diag") as diag,
                    mock.patch.object(http_api, "CompassHTTPServer") as bind,
                    mock.patch.object(lifecycle, "fork_daemon") as fork,
                    mock.patch.object(lifecycle, "spawn_detached") as spawn,
                ):
                    code = cli.main()
            finally:
                # Restore before TemporaryDirectory tries to remove it, and
                # before this frame can leave a 0o500 directory behind.
                os.chmod(home, 0o700)
        self.assertEqual(1, code)
        bind.assert_not_called()
        fork.assert_not_called()
        spawn.assert_not_called()
        said = " ".join(str(call.args[0]) for call in diag.call_args_list)
        self.assertIn("COMPASS_HOME", said)
        self.assertIn(home, said)

    def test_the_windows_daemon_parent_never_constructs_a_server(self) -> None:
        # The three serve branches are deliberately different, and this is the
        # one that must not bind: on Windows the parent re-spawns a foreground
        # child and that child owns the bind, so the parent holding the port even
        # briefly would make the child lose it. Substituting the constructor with
        # a failure proves the parent never reaches it, rather than merely that
        # binding happened to succeed.
        spawned = mock.Mock(pid=4242)
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
            mock.patch.object(os, "name", "nt"),
            mock.patch.object(sys, "argv", ["server.py", "--port", "4553", "--daemon"]),
            mock.patch.object(
                http_api,
                "CompassHTTPServer",
                side_effect=AssertionError("the daemon parent must not bind"),
            ) as bind,
            mock.patch.object(lifecycle, "spawn_detached", return_value=spawned) as spawn,
            mock.patch.object(lifecycle, "await_spawned", return_value=("started", 0)) as awaited,
            mock.patch.object(lifecycle, "fork_daemon") as fork,
            mock.patch.object(runtime_io, "diag"),
        ):
            code = cli.main()

        self.assertEqual(0, code)
        bind.assert_not_called()
        # No POSIX fork either: this branch re-spawns instead.
        fork.assert_not_called()
        spawn.assert_called_once()
        # The parent waits on the child it actually spawned, matched by pid.
        self.assertIs(spawned, awaited.call_args.args[1])
        self.assertEqual(4553, awaited.call_args.args[2])

    def test_stop_instance_refuses_to_touch_a_port_owned_by_something_else(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
        ):
            lifecycle.write_state(cfg(), 4553, started=SERVER_STARTED)
            with mock.patch.object(lifecycle, "probe_port", return_value=("foreign", None)):
                message, code = lifecycle.stop_instance(cfg(), 4553)
            self.assertEqual(1, code)
            self.assertIn("another process", message)
            # The state file is evidence, not garbage: leave it alone.
            self.assertIsNotNone(lifecycle.read_state(cfg(), 4553))

    def test_stop_instance_is_idempotent_when_nothing_is_running(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}),
            mock.patch.object(lifecycle, "probe_port", return_value=("closed", None)),
            mock.patch.object(lifecycle, "port_released", return_value=True),
        ):
            message, code = lifecycle.stop_instance(cfg(), 4553)
        self.assertEqual(0, code)
        self.assertIn("nothing running", message)

    def test_stop_flag_exits_with_the_code_stop_instance_returned(self) -> None:
        with (
            mock.patch.object(lifecycle, "stop_instance", return_value=("nope", 1)) as stop,
            mock.patch.object(sys, "argv", ["server.py", "--port", "4553", "--stop"]),
            mock.patch.object(runtime_io, "diag") as diag,
        ):
            code = cli.main()
        self.assertEqual(1, code)
        self.assertEqual(4553, stop.call_args.args[1])
        diag.assert_called_once_with("nope", print)

    def test_fork_daemon_returns_parent_role_without_touching_setsid(self) -> None:
        calls: list[str] = []

        def fake_fork() -> int:
            calls.append("fork")
            return 4242  # a pid: this process is the original

        def fake_setsid() -> int:
            calls.append("setsid")
            return 0

        role, fd = lifecycle.fork_daemon(fork=fake_fork, setsid=fake_setsid)
        os.close(fd)
        self.assertEqual("parent", role)
        self.assertEqual(["fork"], calls)

    def test_fork_daemon_double_forks_and_sessions_the_daemon(self) -> None:
        calls: list[str] = []
        exited: list[int] = []

        def fake_fork() -> int:
            calls.append("fork")
            return 0  # child both times: this process becomes the daemon

        def fake_setsid() -> int:
            calls.append("setsid")
            return 0

        role, fd = lifecycle.fork_daemon(
            fork=fake_fork, setsid=fake_setsid, exit_intermediate=exited.append
        )
        os.close(fd)
        self.assertEqual("daemon", role)
        # setsid between the two forks: the second fork is what guarantees the
        # daemon is not a session leader and can never acquire a terminal.
        self.assertEqual(["fork", "setsid", "fork"], calls)
        self.assertEqual([], exited)

    def test_fork_daemon_exits_the_intermediate_child(self) -> None:
        forks = iter([0, 9999])  # child, then parent-of-grandchild
        exited: list[int] = []
        role, fd = lifecycle.fork_daemon(
            fork=lambda: next(forks),
            setsid=lambda: 0,
            exit_intermediate=exited.append,
        )
        os.close(fd)
        # The intermediate's only job was setsid. In production os._exit never
        # returns; the injected stub does, so the role is reported for the test.
        self.assertEqual([0], exited)
        self.assertEqual("daemon", role)

    @unittest.skipIf(os.name == "nt", "select() cannot watch a pipe on Windows; POSIX-only path")
    def test_await_daemon_reports_the_pid_the_daemon_announced(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b"31337\n")
        finally:
            os.close(write_fd)
        message, code = lifecycle.await_daemon(cfg(), read_fd, 4553, "/tmp/c.log", timeout=2)
        self.assertEqual(0, code)
        self.assertIn("pid 31337", message)
        self.assertIn("http://127.0.0.1:4553/", message)
        self.assertIn("/tmp/c.log", message)

    @unittest.skipIf(os.name == "nt", "select() cannot watch a pipe on Windows; POSIX-only path")
    def test_await_daemon_reports_failure_when_the_daemon_says_nothing(self) -> None:
        read_fd, write_fd = os.pipe()
        os.close(write_fd)  # daemon died before announcing
        message, code = lifecycle.await_daemon(cfg(), read_fd, 4553, "/tmp/c.log", timeout=1)
        self.assertEqual(1, code)
        self.assertIn("/tmp/c.log", message)

    @unittest.skipIf(os.name == "nt", "select() cannot watch a pipe on Windows; POSIX-only path")
    def test_await_daemon_does_not_report_a_pipe_error_as_a_timeout(self) -> None:
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        with mock.patch.object(
            select,
            "select",
            side_effect=OSError(errno.EBADF, os.strerror(errno.EBADF)),
        ):
            message, code = lifecycle.await_daemon(cfg(), read_fd, 4553, "/tmp/c.log", timeout=10)
        self.assertEqual(1, code)
        self.assertIn("readiness pipe", message)
        self.assertIn("/tmp/c.log", message)
        self.assertNotIn("within 10s", message)

    def test_daemon_rejects_the_flags_it_cannot_combine_with(self) -> None:
        for other in ("--diagnose", "--stop", "--status", "--forget"):
            with (
                mock.patch.object(sys, "argv", ["server.py", "--daemon", other]),
                # parser.error() raises: argparse owns this exit, not main().
                self.assertRaises(SystemExit) as caught,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                cli.main()
            self.assertEqual(2, caught.exception.code, other)

    def test_daemon_explains_a_home_it_cannot_create_instead_of_tracebacking(self) -> None:
        # COMPASS_HOME is user-facing in README, SKILL.md, SECURITY.md and
        # COMPATIBILITY.md, so pointing it somewhere unusable is an ordinary
        # mistake. write_state() already degrades for a foreground run; without
        # this guard only --daemon crashed, and with a raw traceback.
        with tempfile.TemporaryDirectory() as tmp:
            not_a_dir = os.path.join(tmp, "occupied")
            Path(not_a_dir).write_text("", encoding="utf-8")
            with (
                mock.patch.dict(os.environ, {"COMPASS_HOME": not_a_dir}),
                mock.patch.object(sys, "argv", ["server.py", "--port", "4553", "--daemon"]),
                mock.patch.object(runtime_io, "diag") as diag,
                # A traceback here would escape before either of these is used.
                mock.patch.object(http_api, "CompassHTTPServer") as bind,
                mock.patch.object(lifecycle, "fork_daemon") as fork,
            ):
                code = cli.main()
        self.assertEqual(1, code)
        bind.assert_not_called()
        fork.assert_not_called()
        said = " ".join(str(call.args[0]) for call in diag.call_args_list)
        self.assertIn("COMPASS_HOME", said)
        self.assertIn("--daemon", said)
        self.assertIn(not_a_dir, said)

    def test_spawn_argv_is_the_whole_command_and_drops_daemon(self) -> None:
        # One contract for the entire argv, rather than a flags-only helper plus
        # a caller that prefixes an interpreter and a script: the assertion below
        # covers the thing that actually runs.
        config = cfg()
        args = argparse.Namespace(
            port=4553,
            window_hours=12.0,
            no_spacedock=True,
            no_usage=False,
            no_events=False,
            no_irreversible=False,
            no_dismiss=False,
            no_ask=False,
            no_git=False,
            no_focus=False,
            no_history=False,
            history_days=14.0,
            history_max_bytes=1_048_576,
            daemon=True,
        )
        argv = lifecycle.spawn_argv(config, args)
        self.assertEqual(
            [
                sys.executable,
                str(config.launcher_path),
                "--port",
                "4553",
                "--window-hours",
                "12.0",
                "--no-spacedock",
            ],
            argv,
        )
        # --daemon must not be forwarded: the child is an ordinary foreground
        # run that happens to own no console. Forwarding it would re-spawn
        # forever.
        self.assertNotIn("--daemon", argv)
        plain = lifecycle.spawn_argv(
            config,
            argparse.Namespace(
                port=1,
                window_hours=24.0,
                no_spacedock=False,
                no_usage=False,
                no_events=False,
                no_irreversible=False,
                no_dismiss=False,
                no_ask=False,
                no_git=False,
                no_focus=False,
                no_history=False,
                history_days=14.0,
                history_max_bytes=1_048_576,
                daemon=True,
            ),
        )
        self.assertEqual(
            [
                sys.executable,
                str(config.launcher_path),
                "--port",
                "1",
                "--window-hours",
                "24.0",
            ],
            plain,
        )
        # config.launcher_path is the only respawn target: no second interpreter
        # and no second launcher may appear anywhere in the list.
        self.assertEqual(1, argv.count(sys.executable))

    def test_every_opt_out_reaches_the_respawned_daemon(self) -> None:
        # Windows has no fork, so a Windows daemon is always a respawn and a flag
        # missing from spawn_argv is a flag silently ignored for every Windows
        # daemon user. That happened once already, to --no-usage in Phase 0, so
        # this asserts the whole set rather than one flag at a time.
        config = cfg()
        argv = lifecycle.spawn_argv(
            config,
            argparse.Namespace(
                port=4553,
                window_hours=24.0,
                no_spacedock=True,
                no_usage=True,
                no_events=True,
                no_irreversible=False,
                no_dismiss=True,
                no_ask=False,
                no_git=True,
                no_focus=True,
                no_history=True,
                history_days=14.0,
                history_max_bytes=1_048_576,
                daemon=True,
            ),
        )
        for flag in (
            "--no-spacedock",
            "--no-usage",
            "--no-events",
            "--no-dismiss",
            "--no-git",
            "--no-focus",
            "--no-history",
        ):
            self.assertIn(flag, argv)

    def test_spawn_detached_uses_a_fixed_argv_and_detaching_flags(self) -> None:
        args = argparse.Namespace(
            port=4553,
            window_hours=24.0,
            no_spacedock=False,
            no_usage=False,
            no_events=False,
            no_irreversible=False,
            no_dismiss=False,
            no_ask=False,
            no_git=False,
            no_focus=False,
            no_history=False,
            history_days=14.0,
            history_max_bytes=1_048_576,
            daemon=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "c.log")
            with mock.patch.object(subprocess, "Popen") as popen:
                popen.return_value = mock.Mock(pid=321)
                lifecycle.spawn_detached(cfg(), args, log_file)
        argv = popen.call_args.args[0]
        self.assertEqual(sys.executable, argv[0])
        self.assertTrue(argv[1].endswith("server.py"))
        self.assertEqual(["--port", "4553", "--window-hours", "24.0"], argv[2:])
        self.assertEqual(subprocess.DEVNULL, popen.call_args.kwargs["stdin"])
        self.assertTrue(popen.call_args.kwargs["close_fds"])
        # 0 on POSIX, where these creationflags do not exist; the call must
        # still be well-formed so the test runs everywhere.
        self.assertIsInstance(popen.call_args.kwargs["creationflags"], int)

    def test_await_spawned_reports_the_child_that_answered(self) -> None:
        health = {"ok": True, "pid": 777, "port": 4553, "started": 1.0}
        proc = mock.Mock(returncode=None, pid=777)
        proc.poll.return_value = None
        with mock.patch.object(lifecycle, "probe_port", return_value=("compass", health)):
            message, code = lifecycle.await_spawned(cfg(), proc, 4553, "/tmp/c.log", timeout=2)
        self.assertEqual(0, code)
        self.assertIn("pid 777", message)
        self.assertIn("http://127.0.0.1:4553/", message)

    def test_await_spawned_does_not_mistake_another_compass_for_its_own_child(self) -> None:
        # The Windows failure this exists to prevent: the child loses the bind
        # to a dashboard already on that port, and the parent's readiness poll
        # gets a perfectly valid /api/health answer — from the *other*
        # instance. Reporting success there tells the user their daemon
        # started when it did not, and hands back a pid they do not own.
        health = {"ok": True, "pid": 999, "port": 4553, "started": 1.0}
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "c.log")
            Path(log_file).write_text("Compass: port 4553 is already in use.", encoding="utf-8")
            proc = mock.Mock(returncode=1, pid=777)
            proc.poll.return_value = 1
            with mock.patch.object(lifecycle, "probe_port", return_value=("compass", health)):
                message, code = lifecycle.await_spawned(cfg(), proc, 4553, log_file, timeout=2)
        self.assertEqual(1, code)
        self.assertNotIn("pid 999", message)
        self.assertIn("already in use", message)

    def test_await_spawned_keeps_waiting_while_a_foreign_answer_and_a_live_child(self) -> None:
        # Same mismatch, but the child is still running: the answer is not
        # evidence about our child either way, so this must time out rather
        # than claim success.
        health = {"ok": True, "pid": 999, "port": 4553, "started": 1.0}
        proc = mock.Mock(returncode=None, pid=777)
        proc.poll.return_value = None
        with mock.patch.object(lifecycle, "probe_port", return_value=("compass", health)):
            message, code = lifecycle.await_spawned(cfg(), proc, 4553, "/tmp/c.log", timeout=0.3)
        self.assertEqual(1, code)
        self.assertNotIn("pid 999", message)

    def test_await_spawned_surfaces_the_log_when_the_child_exits_at_once(self) -> None:
        # This is the case that keeps D-1's promise on Windows: the parent
        # cannot see the child's failed bind, so it shows the child's log.
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "c.log")
            Path(log_file).write_text("Compass: port 4553 is already in use.", encoding="utf-8")
            proc = mock.Mock(returncode=1)
            proc.poll.return_value = 1
            with mock.patch.object(lifecycle, "probe_port", return_value=("closed", None)):
                message, code = lifecycle.await_spawned(cfg(), proc, 4553, log_file, timeout=2)
        self.assertEqual(1, code)
        self.assertIn("already in use", message)

    def test_await_spawned_gives_up_after_the_timeout(self) -> None:
        proc = mock.Mock(returncode=None)
        proc.poll.return_value = None
        with mock.patch.object(lifecycle, "probe_port", return_value=("closed", None)):
            message, code = lifecycle.await_spawned(cfg(), proc, 4553, "/tmp/c.log", timeout=0.3)
        self.assertEqual(1, code)
        self.assertIn("/tmp/c.log", message)

    def test_log_tail_reads_the_end_and_never_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "c.log")
            Path(log_file).write_bytes(b"x" * 3000 + b"LAST LINE")
            tail = lifecycle.log_tail(log_file, limit=200)
            self.assertIn("LAST LINE", tail)
            self.assertLessEqual(len(tail), 200)
            self.assertIn("could not read", lifecycle.log_tail(os.path.join(tmp, "nope.log")))
            Path(log_file).write_bytes(b"")
            self.assertIn("empty", lifecycle.log_tail(log_file))


class DaemonLifecycleTest(unittest.TestCase):
    """The real thing: detach, outlive the caller, answer --status, stop.

    Everything else in this file tests a piece. This tests the promise.
    """

    SERVER = str(SERVER_PATH)

    @staticmethod
    def _free_port() -> int:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    def _run(self, *flags: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, self.SERVER, *flags],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_daemon_outlives_its_caller_and_stops_on_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "COMPASS_HOME": tmp}
            port = self._free_port()
            flags = ("--port", str(port))
            try:
                start = self._run(*flags, "--daemon", env=env)
                self.assertEqual(0, start.returncode, start.stdout + start.stderr)
                # The starting process has exited by now. Everything below runs
                # against a server whose parent is gone.
                self.assertIn(f"http://127.0.0.1:{port}/", start.stdout)
                self.assertIn("pid ", start.stdout)

                kind, health = lifecycle.probe_port(port, timeout=10)
                self.assertEqual("compass", kind, start.stdout)
                assert health is not None
                self.assertNotEqual(os.getpid(), health["pid"])

                state = json.loads(Path(tmp, f"compass-{port}.json").read_text(encoding="utf-8"))
                self.assertEqual(health["pid"], state["pid"])

                status = self._run(*flags, "--status", env=env)
                self.assertEqual(0, status.returncode, status.stdout + status.stderr)
                self.assertIn("running", status.stdout)

                stopped = self._run(*flags, "--stop", env=env)
                self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
                self.assertIn("stopped", stopped.stdout)

                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if lifecycle.probe_port(port, timeout=1)[0] == "closed":
                        break
                    time.sleep(0.2)
                self.assertEqual("closed", lifecycle.probe_port(port, timeout=1)[0])
                self.assertFalse(Path(tmp, f"compass-{port}.json").exists())

                after = self._run(*flags, "--status", env=env)
                self.assertEqual(1, after.returncode)
                self.assertIn("not running", after.stdout)
            finally:
                # Never leave a detached server behind, however this test ended.
                self._run(*flags, "--stop", env=env)

    def test_a_busy_port_still_explains_itself_under_daemon(self) -> None:
        """D-1's promise: binding happens before detaching, so this message
        reaches the terminal that asked for it and not just a log file."""
        httpd = make_server()
        # Closes the listener when the loop exits, so the reaping --stop below
        # does not sit out the whole release timeout waiting for a socket that
        # only the outer finally was ever going to close.
        thread = serve_until_closed(httpd)
        port = httpd.server_port
        try:
            with tempfile.TemporaryDirectory() as tmp:
                env = {**os.environ, "COMPASS_HOME": tmp}
                try:
                    result = self._run("--port", str(port), "--daemon", env=env)
                    self.assertEqual(1, result.returncode, result.stdout + result.stderr)
                    self.assertIn(f"port {port}", result.stdout + result.stderr)
                finally:
                    # If the busy-port race let the bind through anyway, this
                    # reaps the detached daemon before the temp dir is gone. It
                    # also stops this fixture, which is a real Handler on the
                    # same port and indistinguishable from a stray daemon.
                    reap = self._run("--port", str(port), "--stop", env=env)
                    self.assertEqual(0, reap.returncode, reap.stdout + reap.stderr)
        finally:
            httpd.shutdown()
            thread.join(timeout=5)
            with contextlib.suppress(OSError):
                httpd.server_close()

    def test_daemon_redirect_stdio_line_buffering(self) -> None:
        """DRC-4556: Detached daemon stdout/stderr is line-buffered while alive."""
        code = (
            "import sys, time\n"
            "from compass_runtime import lifecycle\n"
            "lifecycle.daemon_redirect_stdio(sys.argv[1])\n"
            "print('DIAGNOSTIC_LINE_WRITTEN', flush=False)\n"
            "time.sleep(10)\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "daemon.log")
            env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [str(SERVER_PATH.parent), os.environ.get("PYTHONPATH", "")]
                ).strip(os.pathsep),
            }
            proc = subprocess.Popen([sys.executable, "-c", code, log_file], env=env)
            try:
                # Wait briefly for process to redirect and print
                deadline = time.monotonic() + 5.0
                content = ""
                while time.monotonic() < deadline:
                    if os.path.exists(log_file):
                        content = Path(log_file).read_text(encoding="utf-8")
                        if "DIAGNOSTIC_LINE_WRITTEN" in content:
                            break
                    time.sleep(0.05)
                # Verify the diagnostic was written while the process was still alive
                self.assertIsNone(proc.poll(), "process exited prematurely")
                self.assertIn("DIAGNOSTIC_LINE_WRITTEN", content)
            finally:
                proc.kill()
                proc.wait()

    def test_sigterm_removes_state_file(self) -> None:
        """DRC-4551: SIGTERM causes server to remove its state file before exit."""
        if not hasattr(signal, "SIGTERM") or sys.platform == "win32":
            self.skipTest("SIGTERM not available or catchable on this platform")
        port = self._free_port()
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "COMPASS_HOME": tmp}
            flags = [sys.executable, self.SERVER, "--port", str(port)]
            proc = subprocess.Popen(flags, env=env)
            try:
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    kind, _ = lifecycle.probe_port(port, timeout=0.5)
                    if kind == "compass":
                        break
                    time.sleep(0.1)
                self.assertEqual("compass", lifecycle.probe_port(port, timeout=1)[0])
                state_file = Path(tmp, f"compass-{port}.json")
                self.assertTrue(state_file.exists(), "state file was not written")

                # Send SIGTERM
                proc.send_signal(signal.SIGTERM)
                proc.wait(timeout=10)
                self.assertFalse(
                    state_file.exists(),
                    "state file was not removed after SIGTERM",
                )
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_startup_sweeps_stale_state_files(self) -> None:
        """DRC-4181: Startup sweeps state files for dead runs whose port is closed."""
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"COMPASS_HOME": tmp}):
                config = cfg()
            dead_port = self._free_port()
            dead_file = Path(tmp, f"compass-{dead_port}.json")
            dead_file.write_text(
                json.dumps({"pid": 99999999, "port": dead_port, "started": 1.0}),
                encoding="utf-8",
            )
            live_port = self._free_port()
            live_file = Path(tmp, f"compass-{live_port}.json")
            live_file.write_text(
                json.dumps({"pid": os.getpid(), "port": live_port, "started": 1.0}),
                encoding="utf-8",
            )
            other_file = Path(tmp, "compass-deliveries.json")
            other_file.write_text("{}", encoding="utf-8")

            removed = lifecycle.sweep_stale_states(config)
            self.assertIn(dead_port, removed)
            self.assertFalse(dead_file.exists(), "dead state file was not swept")
            self.assertTrue(live_file.exists(), "live state file was swept unexpectedly")
            self.assertTrue(other_file.exists(), "deliveries store was touched")


class SpawnArgvOptOutTest(unittest.TestCase):
    """Every opt-out the parent was given has to reach the respawned child.

    Windows has no fork, so the daemon is always a respawn. A flag dropped here
    is a flag silently ignored for every Windows daemon user.
    """

    def _args(self, **overrides: object) -> argparse.Namespace:
        base: dict[str, object] = {
            "port": 4553,
            "window_hours": 24.0,
            "no_spacedock": False,
            "no_usage": False,
            "no_events": False,
            "no_irreversible": False,
            "no_dismiss": False,
            "no_ask": False,
            "no_git": False,
            "no_focus": False,
            "no_history": False,
            "no_reach": False,
            "reach_url": None,
            "history_days": 14.0,
            "history_max_bytes": 1_048_576,
        }
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_no_usage_is_forwarded(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_usage=True))
        self.assertIn("--no-usage", argv)

    def test_no_usage_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_usage=False))
        self.assertNotIn("--no-usage", argv)

    def test_no_git_is_forwarded(self) -> None:
        # DEC-3's off switch. Without the `spawn_argv` branch a user who disabled
        # the probe gets it back on the respawned daemon, which is the whole
        # failure this class exists for — and a probe re-enabled by a restart is
        # a security regression rather than a cosmetic one.
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_git=True))
        self.assertIn("--no-git", argv)

    def test_no_git_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_git=False))
        self.assertNotIn("--no-git", argv)

    def test_no_focus_is_forwarded(self) -> None:
        # SECURITY.md's focus off switch. A respawned daemon that re-enables it
        # is a security bug in as many words, and the branch reads
        # `args.no_focus` directly, so the hand-written namespaces here raise
        # AttributeError rather than quietly passing — which is the mechanism
        # that forces the branch to exist at all.
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_focus=True))
        self.assertIn("--no-focus", argv)

    def test_no_focus_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_focus=False))
        self.assertNotIn("--no-focus", argv)

    def test_no_history_is_forwarded(self) -> None:
        # DEC-6's off switch. Without the `spawn_argv` branch a user who turned
        # the store off gets it back on the respawned daemon, and the promoted
        # contract calls a respawned daemon that re-enables it a security bug in
        # as many words. Note the two exact-set assertions in this file are
        # blind to an omitted branch: what forces the edit is that the branch
        # reads `args.no_history` directly, so the seven hand-written
        # namespaces raise AttributeError rather than quietly passing.
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_history=True))
        self.assertIn("--no-history", argv)

    def test_no_history_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_history=False))
        self.assertNotIn("--no-history", argv)

    def test_a_narrowed_retention_window_is_forwarded(self) -> None:
        # The bounds are configurable as of the captain's ND-1 ruling, and a
        # respawn that dropped a narrowed one would widen a bound the operator
        # tightened — the same class of failure as re-enabling a store they
        # turned off, since what falls outside the window is gone from the file.
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(history_days=2.0))
        self.assertIn("--history-days", argv)
        self.assertEqual("2.0", argv[argv.index("--history-days") + 1])

    def test_the_retention_window_is_absent_when_it_is_the_default(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(history_days=14.0))
        self.assertNotIn("--history-days", argv)

    def test_a_moved_size_cap_is_forwarded(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(history_max_bytes=4_096))
        self.assertIn("--history-max-bytes", argv)
        self.assertEqual("4096", argv[argv.index("--history-max-bytes") + 1])

    def test_the_size_cap_is_absent_when_it_is_the_default(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(history_max_bytes=1_048_576))
        self.assertNotIn("--history-max-bytes", argv)

    def test_no_ask_is_forwarded(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_ask=True))
        self.assertIn("--no-ask", argv)

    def test_no_ask_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_ask=False))
        self.assertNotIn("--no-ask", argv)

    def test_no_reach_is_forwarded(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_reach=True))
        self.assertIn("--no-reach", argv)

    def test_no_reach_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_reach=False))
        self.assertNotIn("--no-reach", argv)

    def test_reach_url_is_forwarded(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(reach_url="https://example.com/webhook"))
        self.assertIn("--reach-url", argv)
        self.assertIn("https://example.com/webhook", argv)

    def test_no_quiet_hours_is_forwarded_when_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_quiet_hours=True))
        self.assertIn("--no-quiet-hours", argv)

    def test_no_quiet_hours_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_quiet_hours=False))
        self.assertNotIn("--no-quiet-hours", argv)

    def test_quiet_hours_is_forwarded(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(quiet_hours="22:00-08:00"))
        self.assertIn("--quiet-hours", argv)
        self.assertIn("22:00-08:00", argv)

    def test_quiet_hours_is_absent_when_not_requested(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args())
        self.assertNotIn("--quiet-hours", argv)

    def test_daemon_is_never_forwarded(self) -> None:
        """Forwarding --daemon would respawn forever."""
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(no_usage=True))
        self.assertNotIn("--daemon", argv)

    def test_host_is_forwarded_when_non_default(self) -> None:
        # AC-4: a --host 0.0.0.0 --daemon child binds the same address as the
        # parent requested. Deleting the --host append from spawn_argv makes
        # this assertion fail.
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args(host="0.0.0.0"))
        self.assertIn("--host", argv)
        self.assertIn("0.0.0.0", argv)

    def test_host_is_absent_when_default(self) -> None:
        config = cfg()
        argv = lifecycle.spawn_argv(config, self._args())
        self.assertNotIn("--host", argv)


class ProducerTest(support.RuntimeTestCase):
    """The producer keeps the snapshot warm, but only for a connected stream."""

    @staticmethod
    def _wait_for(predicate: Any, *, timeout: float = 10.0) -> bool:
        """Poll until true, or give up.

        Never a fixed sleep. A loaded CI runner can starve a 20 ms loop for a
        quarter second, which made "at least two iterations" fail on macOS while
        passing locally. Waiting on the condition tests the behaviour; sleeping
        tests the runner.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    @staticmethod
    def _server() -> Any:
        return support.make_server()

    def test_the_producer_does_nothing_with_no_connected_stream(self) -> None:
        """The guarantee this whole phase most easily breaks.

        An idle daemon does zero filesystem work today. A timer that collected
        regardless would spend a laptop's battery on a board nobody is watching.
        """
        httpd = self._server()
        calls: list[int] = []
        stop = threading.Event()

        def counting(_self: Any, *, show_all: bool) -> Any:
            del show_all
            calls.append(1)
            return (0.0, 0), b"{}"

        with mock.patch.object(type(httpd.application), "collect_json", counting):
            thread = threading.Thread(
                target=lifecycle.run_producer,
                args=(httpd,),
                kwargs={"stop": stop, "interval": 0.02},
                daemon=True,
            )
            thread.start()
            # A fixed window is right for an absence: there is no condition to
            # wait for, and 10 intervals is ample opportunity to misbehave.
            time.sleep(0.2)
            stop.set()
            thread.join(timeout=2)
        httpd.server_close()
        self.assertEqual([], calls, "no stream connected means no collection at all")

    def test_the_producer_collects_while_a_stream_is_connected(self) -> None:
        httpd = self._server()
        calls: list[int] = []
        stop = threading.Event()
        client = httpd.application.state.streams.register(limit=4)
        self.assertIsNotNone(client)
        assert client is not None
        self.addCleanup(httpd.application.state.streams.release, client)

        def counting(_self: Any, *, show_all: bool) -> Any:
            del show_all
            calls.append(1)
            return (0.0, 0), b"{}"

        with mock.patch.object(type(httpd.application), "collect_json", counting):
            thread = threading.Thread(
                target=lifecycle.run_producer,
                args=(httpd,),
                kwargs={"stop": stop, "interval": 0.02},
                daemon=True,
            )
            thread.start()
            fed = self._wait_for(lambda: len(calls) > 0)
            stop.set()
            thread.join(timeout=2)
        httpd.server_close()
        self.assertTrue(fed, "a connected stream must be fed")

    def test_the_stop_event_ends_the_producer_well_inside_one_interval(self) -> None:
        httpd = self._server()
        stop = threading.Event()
        thread = threading.Thread(
            target=lifecycle.run_producer,
            args=(httpd,),
            kwargs={"stop": stop, "interval": 30.0},
            daemon=True,
        )
        thread.start()
        stop.set()
        thread.join(timeout=3)
        httpd.server_close()
        self.assertFalse(thread.is_alive(), "stop must not wait out the interval")

    def test_a_server_without_an_application_ends_the_producer_quietly(self) -> None:
        """A server double is a real caller: cli.main's bind test uses one.

        Reaching for server.application unguarded raised inside the producer
        thread, which surfaced as an unhandled daemon-thread exception in the CI
        log without failing anything: noise that hides real signal.
        """

        class Bare:
            pass

        stop = threading.Event()
        thread = threading.Thread(
            target=lifecycle.run_producer,
            args=(Bare(),),
            kwargs={"stop": stop, "interval": 0.01},
            daemon=True,
        )
        thread.start()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive(), "it must return, not spin or raise")

    def test_a_collection_error_does_not_kill_the_producer(self) -> None:
        """A dead producer is a silently frozen dashboard."""
        httpd = self._server()
        calls: list[int] = []
        stop = threading.Event()
        client = httpd.application.state.streams.register(limit=4)
        self.assertIsNotNone(client)
        assert client is not None
        self.addCleanup(httpd.application.state.streams.release, client)

        def flaky(_self: Any, *, show_all: bool) -> Any:
            del show_all
            calls.append(1)
            if len(calls) == 1:
                msg = "store exploded"
                raise OSError(msg)
            return (0.0, 0), b"{}"

        with mock.patch.object(type(httpd.application), "collect_json", flaky):
            thread = threading.Thread(
                target=lifecycle.run_producer,
                args=(httpd,),
                kwargs={"stop": stop, "interval": 0.02},
                daemon=True,
            )
            thread.start()
            survived = self._wait_for(lambda: len(calls) > 1)
            stop.set()
            thread.join(timeout=2)
        httpd.server_close()
        self.assertTrue(survived, "the loop must survive a failed collection")


class ServeOwnsReadingJobsTest(unittest.TestCase):
    """DRC-4686: what `serve` does for the reading jobs this daemon runs.

    Q5 on the issue: a supervised CLI leads a process group of its own, so a
    foreground Ctrl-C no longer reaches it and shutdown has to kill it. Q2: a
    job a stopped dashboard left spent is recorded when the next one starts.
    """

    def _serve(self, server: Any, events: list[str]) -> Any:
        from compass_runtime import reading_jobs, supervise  # noqa: PLC0415

        config = support.make_config()

        def recovered(_application: Any, *, alive: Any) -> int:
            events.append(f"recover:{alive.func.__name__}")
            return 0

        with (
            mock.patch.object(lifecycle, "write_state"),
            mock.patch.object(lifecycle, "remove_state"),
            mock.patch.object(lifecycle, "run_producer"),
            mock.patch.object(supervise, "kill_all", side_effect=lambda: events.append("kill_all")),
            mock.patch.object(reading_jobs, "recover", side_effect=recovered) as recover,
        ):
            lifecycle.serve(
                config,
                server,
                4553,
                started=1.0,
                diagnostic_sink=lambda _message: None,
            )
        return recover

    def test_shutdown_kills_every_supervised_group_after_serving(self) -> None:
        events: list[str] = []

        class FakeServer:
            application = None

            def serve_forever(self) -> None:
                events.append("serve")

            def server_close(self) -> None:
                pass

        self._serve(FakeServer(), events)
        self.assertEqual(["serve", "kill_all"], events)

    def test_a_serving_application_records_what_a_stopped_one_left_spent_first(self) -> None:
        events: list[str] = []
        application = mock.Mock()

        class FakeServer:
            def __init__(self) -> None:
                self.application = application

            def serve_forever(self) -> None:
                events.append("serve")

            def server_close(self) -> None:
                pass

        recover = self._serve(FakeServer(), events)
        self.assertEqual(["recover:dashboard_alive", "serve", "kill_all"], events)
        self.assertIs(application, recover.call_args.args[0])


@unittest.skipIf(sys.platform == "win32", "terminal hangups are POSIX")
class AnIgnoredHangupStaysIgnoredTest(unittest.TestCase):
    """Verify N1: a server started under `nohup` must survive the hangup it was told to ignore."""

    def _serve_ignoring(self, name: str) -> None:
        server, number = self._start_ignoring(name)
        os.kill(server.pid, number)
        time.sleep(1.0)
        self.assertIsNone(server.poll(), f"a server that ignored {name} exited on it")
        server.terminate()
        self.assertEqual(0, server.wait(timeout=15))

    def _start_ignoring(
        self, name: str, *, stall_in: str | None = None
    ) -> tuple[subprocess.Popen[bytes], int]:
        """Start a server with `name` ignored, and return once it reached its point.

        Without `stall_in` the point is the state file. With it, the server parks
        in that step until killed, and the point is the step being entered.
        """
        number = getattr(signal, name)
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = int(listener.getsockname()[1])
        env = {**os.environ, "COMPASS_HOME": str(home), "PYTHONNOUSERSITE": "1"}
        env.pop("PYTHONPATH", None)
        arguments = ["--port", str(port), "--no-events"]
        reached = home / f"compass-{port}.json"
        command = [sys.executable, str(SERVER_PATH), *arguments]
        if stall_in is not None:
            reached = home / "stalled"
            command = [
                sys.executable,
                "-c",
                _STALLED_SERVER,
                str(SERVER_PATH.parent),
                stall_in,
                str(reached),
                *arguments,
            ]
        server = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=lambda: signal.signal(number, signal.SIG_IGN),  # noqa: PLW1509
        )
        self.addCleanup(server.wait)  # cleanups run last-first: reaped after the kill
        self.addCleanup(server.kill)
        self.state = home / f"compass-{port}.json"
        deadline = time.monotonic() + 20
        while not reached.exists() and server.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(reached.exists(), "the server never reached the point under test")
        return server, number

    def test_a_server_run_under_nohup_survives_a_hangup(self) -> None:
        self._serve_ignoring("SIGHUP")

    def test_a_server_that_ignores_quit_survives_it(self) -> None:
        self._serve_ignoring("SIGQUIT")

    def test_a_server_started_ignoring_sigterm_still_stops_on_it(self) -> None:
        """L1: `kill <pid>` stops the server whatever it inherited, as on main."""
        server, _ = self._start_ignoring("SIGTERM")
        os.kill(server.pid, signal.SIGTERM)
        self.assertEqual(
            0, server.wait(timeout=15), "an inherited ignore kept SIGTERM from stopping it"
        )

    def test_sigterm_between_the_state_file_and_the_serve_loop_still_stops_it(self) -> None:
        """DRC-4737: the state file is out before the serve loop, so a `kill` can land between.

        The inherited ignore used to hold until the exit handler went in after
        recovery, and a SIGTERM in that gap was dropped for good. Recovery is
        stalled here so the signal lands there every run, and the server must
        exit cleanly and take its state file with it.
        """
        server, _ = self._start_ignoring("SIGTERM", stall_in="recover")
        self.assertTrue(self.state.exists(), "the state file precedes recovery")
        os.kill(server.pid, signal.SIGTERM)
        self.assertEqual(0, server.wait(timeout=15), "a SIGTERM before the serve loop was dropped")
        self.assertFalse(self.state.exists(), "a stopped server left its state file")

    def test_sigterm_while_the_producer_thread_starts_still_stops_it(self) -> None:
        """DRC-4737 follow-up: a `kill` inside `Thread.start` must still exit 0.

        The signal can land before the new thread has reported in, and the
        cleanup's `join` then raised "cannot join thread before it is started",
        which replaced the clean exit with a traceback and exit 1 and skipped
        the state file's removal. Measured on the 3.11 runtime-floor job.
        """
        server, _ = self._start_ignoring("SIGTERM", stall_in="producer")
        self.assertTrue(self.state.exists(), "the state file precedes the producer")
        os.kill(server.pid, signal.SIGTERM)
        self.assertEqual(
            0, server.wait(timeout=15), "a SIGTERM while the producer started exited unclean"
        )
        self.assertFalse(self.state.exists(), "a stopped server left its state file")

    def test_sigterm_during_assembly_still_stops_it(self) -> None:
        """DRC-4737: before the bind there is nothing to clean up, so it stops as by default."""
        server, _ = self._start_ignoring("SIGTERM", stall_in="assembly")
        os.kill(server.pid, signal.SIGTERM)
        self.assertEqual(
            -signal.SIGTERM,
            server.wait(timeout=15),
            "a SIGTERM during assembly was dropped",
        )


class ADashboardIsAliveOnlyByItsStateFileTest(unittest.TestCase):
    """Review F4: a reused pid is not a dashboard unless a state file here names it."""

    def test_a_live_pid_is_a_dashboard_only_when_a_state_file_names_it(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config = support.make_config(state_home=home, state_dir=Path(home))
        parent = os.getppid()
        self.assertFalse(lifecycle.dashboard_alive(config, parent))
        Path(home, "compass-4599.json").write_text(json.dumps({"pid": parent, "port": 4599}))
        self.assertTrue(lifecycle.dashboard_alive(config, parent))
        Path(home, "compass-4598.json").write_text(json.dumps({"pid": 999_999_9, "port": 4598}))
        self.assertFalse(lifecycle.dashboard_alive(config, 999_999_9), "a dead pid is no dashboard")


# The server with one step parked: it announces the step, then waits there for
# a signal. `recover` runs after the state file is written, `producer` is the
# producer thread's start before the thread has reported in, and `assembly`
# is before the bind. A dropped SIGTERM reads as the wait outliving the test's own.
_STALLED_SERVER = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from compass_runtime import cli, reading_jobs
step, reached = sys.argv[2], Path(sys.argv[3])

def parked(real):
    def park(*args, **kwargs):
        reached.write_text(step)
        time.sleep(30)
        return real(*args, **kwargs)
    return park

if step == "recover":
    reading_jobs.recover = parked(reading_jobs.recover)
elif step == "producer":
    import threading
    from compass_runtime import lifecycle
    real_start = threading.Thread.start
    def start(self):
        if getattr(self, "_target", None) is lifecycle.run_producer:
            return parked(real_start)(self)
        return real_start(self)
    threading.Thread.start = start
else:
    cli.build_application = parked(cli.build_application)
raise SystemExit(cli.main(sys.argv[4:]))
"""


_HANGUP_DAEMON = """
import sys, threading, time
sys.path.insert(0, sys.argv[1])
from compass_runtime import lifecycle, supervise

lifecycle._register_sigterm_exit()
cli_pid, done = sys.argv[2], sys.argv[3]
script = "import os, time; open(%r, 'w').write(str(os.getpid())); time.sleep(60)" % cli_pid
threading.Thread(
    target=lambda: supervise.run([sys.executable, "-c", script], timeout=60), daemon=True
).start()
try:
    time.sleep(60)
finally:
    supervise.kill_all()
    open(done, "w").write("cleaned up")
"""


@unittest.skipIf(sys.platform == "win32", "terminal hangups are POSIX")
class ATerminalHangupStillCleansUpTest(unittest.TestCase):
    """Review F1: closing the terminal of a foreground run must not orphan the CLI.

    A supervised CLI leads its own group, so the terminal's SIGHUP (or a
    Ctrl-backslash SIGQUIT) reaches only the daemon. Measured before the fix:
    the daemon died without its `finally` and the CLI ran on, untimed.
    """

    @staticmethod
    def _stop(pid: int) -> None:
        if support.process_alive(pid):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)

    def _hang_up(self, sig: int) -> None:
        home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, home, True)
        cli_pid, done = home / "cli.pid", home / "done"
        daemon = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _HANGUP_DAEMON,
                str(Path(__file__).resolve().parents[1]),
                str(cli_pid),
                str(done),
            ],
            start_new_session=True,
        )
        self.addCleanup(daemon.kill)
        deadline = time.monotonic() + 10
        while not (cli_pid.exists() and cli_pid.read_text()) and time.monotonic() < deadline:
            time.sleep(0.05)
        pid = int(cli_pid.read_text())
        self.addCleanup(self._stop, pid)
        os.killpg(daemon.pid, sig)
        daemon.wait(timeout=10)
        self.assertTrue(done.exists(), "the daemon died without running its cleanup")
        deadline = time.monotonic() + 10
        while support.process_alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(support.process_alive(pid), "the CLI outlived the hangup")

    def test_a_hangup_to_a_foreground_daemons_group_kills_the_cli(self) -> None:
        self._hang_up(signal.SIGHUP)

    def test_a_quit_from_the_terminal_kills_the_cli(self) -> None:
        self._hang_up(signal.SIGQUIT)


class EveryOptOutReachesTheWindowsChildTest(unittest.TestCase):
    """DRC-4655: the Windows respawn forwards every `--no-*` the parser defines.

    Windows has no fork, so a daemon there is always `spawn_argv` parsed again
    by a child. Each case parses the parent's flags, builds its config, parses
    the respawn argv back through the same CLI and builds the child's, so what
    is compared is the run the child would have, not the argv's spelling.
    """

    NOW = 1_800_000_000.0

    def _config(self, args: argparse.Namespace) -> Any:
        config, _ = cli.build_runtime(args, started=self.NOW)
        return config

    def _child(
        self, args: argparse.Namespace, parser: argparse.ArgumentParser | None = None
    ) -> argparse.Namespace:
        parser = parser or cli.build_parser()
        argv = lifecycle.spawn_argv(self._config(args), args)
        return parser.parse_args(argv[2:])

    @staticmethod
    def _opt_outs(parser: argparse.ArgumentParser) -> list[str]:
        """Every opt-out spelling the parser accepts, aliases included."""
        return [
            option
            for action in parser._actions
            if isinstance(action, argparse._StoreTrueAction)
            for option in action.option_strings
            if option.startswith("--no-")
        ]

    def test_the_child_config_matches_the_parent_for_every_opt_out(self) -> None:
        parser = cli.build_parser()
        flags = self._opt_outs(parser)
        # The two the hand list dropped, named so the derivation cannot pass by
        # finding nothing.
        self.assertIn("--no-annotations", flags)
        self.assertIn("--no-tripwires", flags)
        for flag in flags:
            with self.subTest(flag=flag):
                parent = parser.parse_args([flag])
                child = self._child(parent)
                self.assertEqual(self._config(parent), self._config(child))
                self.assertEqual(vars(parent), {**vars(child), "port": parent.port})
        every = parser.parse_args(flags)
        self.assertEqual(self._config(every), self._config(self._child(every)))

    def test_a_new_opt_out_in_the_parser_is_forwarded_without_editing_the_list(self) -> None:
        parser = cli.build_parser()
        parser.add_argument("--no-placeholder-store", action="store_true")
        parent = parser.parse_args(["--no-placeholder-store"])
        self.assertTrue(self._child(parent, parser).no_placeholder_store)
        quiet = parser.parse_args([])
        self.assertFalse(self._child(quiet, parser).no_placeholder_store)

    def test_no_harness_usage_turns_model_calls_off_in_the_child(self) -> None:
        parent = cli.build_parser().parse_args(["--no-harness-usage"])
        self.assertTrue(self._config(parent).model_calls_disabled)
        self.assertTrue(self._config(self._child(parent)).model_calls_disabled)

    def test_compatibility_flags_and_environment_change_nothing(self) -> None:
        parser = cli.build_parser()
        baseline = self._config(parser.parse_args([]))
        self.assertTrue(baseline.observer_model_enabled)
        for flag in ("--allow-tool-output", "--observer-model"):
            with self.subTest(flag=flag):
                args = parser.parse_args([flag])
                self.assertEqual(baseline, self._config(args))
                self.assertEqual(baseline, self._config(self._child(args)))
        with mock.patch.dict(os.environ, {cli.TOOL_OUTPUT_ENV: "1"}):
            self.assertEqual(baseline, self._config(parser.parse_args([])))
        for refusal in ("--no-observer-model", "--no-harness-usage"):
            args = parser.parse_args(["--allow-tool-output", "--observer-model", refusal])
            self.assertFalse(self._config(args).observer_model_enabled)
            self.assertTrue(self._config(self._child(args)).model_calls_disabled)

    def test_an_opt_in_never_travels_without_the_model_refusal_beside_it(self) -> None:
        parser = cli.build_parser()
        opt_ins = [["--observer-model"], ["--unasked-readings"], []]
        refusals = [["--no-observer-model"], ["--no-harness-usage"], []]
        for opt_in in opt_ins:
            for refusal in refusals:
                with self.subTest(opt_in=opt_in, refusal=refusal):
                    parent = parser.parse_args([*opt_in, *refusal])
                    child = self._child(parent)
                    forwarded_in = child.observer_model or child.unasked_readings
                    if forwarded_in and parent.no_observer_model:
                        self.assertTrue(child.no_observer_model)
                    self.assertEqual(
                        self._config(parent).model_calls_disabled,
                        self._config(child).model_calls_disabled,
                    )

    @staticmethod
    def _convention_breaks(parser: argparse.ArgumentParser) -> list[str]:
        """Every parser option that `_opt_out_argv`'s naming convention would mishandle."""
        breaks = []
        for action in parser._actions:
            spelled = any(option.startswith("--no-") for option in action.option_strings)
            named = action.dest.startswith("no_")
            if not (spelled or named):
                continue
            canonical = "--" + action.dest.replace("_", "-")
            if not (
                spelled
                and named
                and isinstance(action, argparse._StoreTrueAction)
                and canonical in action.option_strings
            ):
                breaks.append(f"{action.option_strings} -> {action.dest}")
        return breaks

    def test_every_opt_out_in_the_real_parser_keeps_the_convention_the_respawn_reads(
        self,
    ) -> None:
        # `_opt_out_argv` forwards `no_*` destinations holding True, under
        # `--` plus the destination. A `--no-*` flag that takes a value is
        # dropped by that, and a `no_*` switch spelled otherwise makes the
        # child exit 2, so a flag of either shape has to fail here first.
        self.assertEqual([], self._convention_breaks(cli.build_parser()))

    def test_the_convention_check_catches_each_shape_the_respawn_would_mishandle(self) -> None:
        shapes = {
            "takes a value": ("--no-reach-after", {"dest": "no_reach_after"}),
            "spelled otherwise": ("--offline", {"dest": "no_network", "action": "store_true"}),
            "dest without no_": ("--no-extra", {"dest": "extra_disabled", "action": "store_true"}),
        }
        for shape, (flag, keywords) in shapes.items():
            with self.subTest(shape=shape):
                parser = cli.build_parser()
                parser.add_argument(flag, **keywords)  # type: ignore[arg-type]
                self.assertEqual(1, len(self._convention_breaks(parser)))
