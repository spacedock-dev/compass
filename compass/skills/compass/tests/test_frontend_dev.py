from __future__ import annotations

import dataclasses
import hashlib
import hmac
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
from contextlib import redirect_stderr, suppress
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import cli, http_api
from compass_runtime import config as runtime_config
from compass_runtime.state import build_runtime_state

from .support import SERVER_PATH

try:
    from compass_runtime import frontend_dev
except ImportError:
    frontend_dev = None  # type: ignore[assignment]

# The handshake's two-second elapsed deadline runs on the wall clock against a real listener.
REAL_TIME_TESTS = True


class FrontendDevelopmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(frontend_dev, "development startup admission is missing")
        self.temp = tempfile.TemporaryDirectory(prefix="compass-dev-admission-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "manifest.json"
        self.data: dict[str, Any] = {
            "format": 1,
            "python_origin": "http://127.0.0.1:4581",
            "vite_origin": "http://127.0.0.1:4582",
            "nonce": "00" * 32,
            "vite_generation": "22" * 16,
            "backend_generation": "33" * 16,
            "vite_pid": 12345,
        }
        self.write_manifest()

    def write_manifest(self) -> None:
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        self.path.chmod(0o600)

    def config(self, **changes: Any) -> runtime_config.RuntimeConfig:
        config = runtime_config.build_runtime_config(
            environ={
                "HOME": str(self.root),
                "USERPROFILE": str(self.root),
                "COMPASS_HOME": str(self.root / "state"),
            },
            platform_name="linux",
            os_name="posix",
            launcher_path=SERVER_PATH,
            port=4581,
            model_calls_disabled=True,
            usage_fetch_enabled=False,
            git_probe_enabled=False,
            focus_enabled=False,
        )
        return dataclasses.replace(config, **changes)

    def test_shared_handshake_vector_and_secret_not_in_admitted_config_repr(self) -> None:
        manifest = frontend_dev.load_manifest(self.path)
        self.assertEqual(
            "57b38c7f16c2655778f5e2f994b677722d6c9d55fcd925bd32c2cf003ba8bf63",
            frontend_dev.signature(manifest, "11" * 32),
        )
        self.assertNotIn("00" * 32, repr(manifest))

    def test_closed_manifest_refuses_remote_aliases_redirect_syntax_and_wrong_types(self) -> None:
        for key, value in (
            ("vite_origin", "http://localhost:4582"),
            ("vite_origin", "https://127.0.0.1:4582"),
            ("vite_origin", "http://192.0.2.1:4582"),
            ("vite_origin", "http://u:p@127.0.0.1:4582"),
            ("vite_origin", "http://127.0.0.1:4582/?origin=elsewhere"),
            ("vite_origin", "http://127.0.0.1:4581"),
            ("vite_pid", True),
            ("format", True),
            ("nonce", "f" * 63),
        ):
            with self.subTest(key=key, value=value):
                saved = self.data[key]
                self.data[key] = value
                self.write_manifest()
                with self.assertRaises(RuntimeError):
                    frontend_dev.load_manifest(self.path)
                self.data[key] = saved
        self.data["extra"] = "not admitted"
        self.write_manifest()
        with self.assertRaises(RuntimeError):
            frontend_dev.load_manifest(self.path)
        del self.data["extra"]
        self.path.write_text(
            json.dumps(self.data).replace('"format": 1', '"format": 1, "format": 1'),
            encoding="utf-8",
        )
        with self.assertRaises(RuntimeError):
            frontend_dev.load_manifest(self.path)

    def test_runtime_containment_covers_every_collector_candidate_and_symlink(self) -> None:
        manifest = frontend_dev.load_manifest(self.path)
        config = self.config()
        frontend_dev.validate_runtime(manifest, config)
        for key in config.store_roots:
            roots = dict(config.store_roots)
            roots[key] = (*roots[key], str(self.root.parent / "real-transcripts"))
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                frontend_dev.validate_runtime(
                    manifest, dataclasses.replace(config, store_roots=roots)
                )
        external = tempfile.TemporaryDirectory(prefix="compass-external-root-")
        self.addCleanup(external.cleanup)
        link = self.root / "escaped-store"
        try:
            link.symlink_to(external.name, target_is_directory=True)
        except OSError:
            return  # native Windows can disallow unprivileged symlink creation
        roots = dict(config.store_roots)
        roots["codex.sessions"] = (str(link),)
        with self.assertRaises(RuntimeError):
            frontend_dev.validate_runtime(manifest, dataclasses.replace(config, store_roots=roots))

    def test_bind_and_model_usage_scope_cannot_be_widened(self) -> None:
        manifest = frontend_dev.load_manifest(self.path)
        for changes in (
            {"host": "0.0.0.0"},
            {"port": 4589},
            {"model_calls_disabled": False},
            {"usage_fetch_enabled": True},
            {"home": "/real-home"},
            {"state_home": "/real-state"},
        ):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                frontend_dev.validate_runtime(manifest, self.config(**changes))

    @staticmethod
    def write_slow_response(
        handler: BaseHTTPRequestHandler, mode: str, body: bytes, stop: threading.Event
    ) -> None:
        # Each drip lasts 40 s in all, so a client whose deadline renewed on every
        # byte would still be reading well past the test's 30 s bound.
        with suppress(ConnectionError):
            if mode == "slow-headers":
                handler.wfile.write(b"HTTP/1.1 200 OK\r\n")
                for index in range(160):
                    handler.wfile.write(f"X-Synthetic-{index}: drip\r\n".encode())
                    if stop.wait(0.25):
                        return
                handler.wfile.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            else:
                handler.wfile.write(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n")
                # read1 itself parses this chunk-size line: an idle timeout
                # cannot bound bytes arriving continuously.
                for byte in b"1;" + b"x" * 158:
                    handler.wfile.write(bytes([byte]))
                    if stop.wait(0.25):
                        return
                handler.wfile.write(b"\r\nx\r\n0\r\n\r\n")

    def start_listener(self, *, bad: str = "") -> ThreadingHTTPServer:
        owner = self
        stop = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def do_GET(self) -> None:
                if bad == "timeout":
                    time.sleep(2.2)
                challenge = self.headers.get("x-compass-dev-challenge", "")
                owner.assertEqual("/__compass_dev_handshake", self.path)
                owner.assertEqual(
                    owner.data["backend_generation"], self.headers.get("x-compass-dev-generation")
                )
                owner.assertIsNone(self.headers.get("Origin"))
                fields = [
                    "compass-vite-dev-v1",
                    challenge,
                    owner.data["python_origin"],
                    owner.data["vite_origin"],
                    owner.data["vite_generation"],
                    owner.data["backend_generation"],
                    str(owner.data["vite_pid"]),
                ]
                signed = hmac.new(
                    bytes.fromhex(owner.data["nonce"]),
                    "\n".join(fields).encode("ascii"),
                    hashlib.sha256,
                ).hexdigest()
                body = json.dumps(
                    {
                        "format": 1,
                        "vite_generation": owner.data["vite_generation"],
                        "backend_generation": owner.data["backend_generation"],
                        "vite_pid": owner.data["vite_pid"],
                        "signature": "0" * 64 if bad == "signature" else signed,
                    }
                ).encode()
                if bad == "oversized":
                    body = b" " * 2049
                if bad in ("slow-headers", "slow-body"):
                    owner.write_slow_response(self, bad, body, stop)
                    return
                self.send_response(307 if bad == "redirect" else 200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Location", "http://192.0.2.1/")
                self.end_headers()
                with suppress(ConnectionError):
                    self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        self.addCleanup(stop.set)
        self.data["vite_origin"] = f"http://127.0.0.1:{server.server_port}"
        self.write_manifest()
        return server

    def test_actual_owned_listener_challenge_admits_and_document_uses_only_frozen_origin(
        self,
    ) -> None:
        self.start_listener()
        admitted = frontend_dev.admit(self.path, self.config())
        html = frontend_dev.load_page(admitted)
        self.assertIn(self.data["vite_origin"].encode() + b"/@vite/client", html)
        self.assertIn(self.data["vite_origin"].encode() + b"/@react-refresh", html)
        self.assertIn(self.data["backend_generation"].encode(), html)
        self.assertNotIn(self.data["nonce"].encode(), html)
        self.assertEqual(1, html.count(b"</head>"))
        self.assertEqual(
            1, cli.inject_focus_capability(html, "abcdef").count(b'name="compass-focus"')
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            admitted.vite_origin = "http://127.0.0.1:9999"  # type: ignore[misc]

    def test_foreign_bad_signature_redirect_and_oversized_listener_refuse(self) -> None:
        for bad in ("signature", "redirect", "oversized", "timeout"):
            with self.subTest(bad=bad):
                server = self.start_listener(bad=bad)
                with self.assertRaises(RuntimeError):
                    frontend_dev.admit(self.path, self.config())
                self.assertTrue(
                    server.socket.fileno() >= 0, "refusal must not kill an unrelated listener"
                )

    def test_slow_headers_cannot_extend_elapsed_handshake_deadline(self) -> None:
        self.assert_slow_listener_deadline("slow-headers")

    def test_slow_chunk_metadata_cannot_extend_elapsed_body_deadline(self) -> None:
        self.assert_slow_listener_deadline("slow-body")

    def assert_slow_listener_deadline(self, mode: str) -> None:
        server = self.start_listener(bad=mode)
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            frontend_dev.admit(self.path, self.config())
        # The deadline is two seconds; the drip outlasts 30, so this bound separates
        # a held deadline from a renewed one with room for a loaded runner.
        self.assertLess(
            time.monotonic() - started,
            30,
            "continuous bytes must not renew the two-second elapsed deadline",
        )
        self.assertGreaterEqual(server.socket.fileno(), 0, "only the owned client may close")

    def test_elapsed_watchdog_joins_on_success_and_refusal(self) -> None:
        timer_factory = threading.Timer
        timers: list[threading.Timer] = []

        def record_timer(*args: Any, **kwargs: Any) -> threading.Timer:
            timer = timer_factory(*args, **kwargs)
            timers.append(timer)
            return timer

        for bad in ("", "signature", "slow-headers", "slow-body"):
            with self.subTest(bad=bad):
                timers.clear()
                self.start_listener(bad=bad)
                with mock.patch.object(threading, "Timer", side_effect=record_timer):
                    if bad:
                        with self.assertRaises(RuntimeError):
                            frontend_dev.admit(self.path, self.config())
                    else:
                        frontend_dev.admit(self.path, self.config())
                self.assertTrue(timers, "elapsed deadline must have an owned watchdog")
                self.assertTrue(all(not timer.is_alive() for timer in timers))

    def test_cli_dev_requires_a_foreground_loopback_server_and_freezes_safe_services(self) -> None:
        parser = cli.build_parser()
        for args in (("--daemon",), ("--host", "0.0.0.0")):
            with (
                self.subTest(args=args),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                cli.main(["--frontend-dev-manifest", str(self.path), *args])
        parsed = parser.parse_args(["--frontend-dev-manifest", str(self.path)])
        cli.validate_frontend_args(parser, parsed)
        config, _ = cli.build_runtime(parsed, started=1)
        self.assertTrue(config.model_calls_disabled)
        self.assertFalse(config.usage_fetch_enabled)
        self.assertFalse(config.focus_enabled)
        self.assertTrue(parsed.no_events)

    def test_development_http_authority_refuses_alias_wrong_port_and_origin(self) -> None:
        self.start_listener()
        dev = frontend_dev.admit(self.path, self.config())
        config = self.config(frontend_dev=dev)
        state = build_runtime_state(config, started=1)
        app = cli.build_application(
            config, state, record_history=False, frontend_page_bytes=frontend_dev.load_page(dev)
        )
        server = http_api.CompassHTTPServer(("127.0.0.1", 0), app, frontend_dev.load_page(dev))
        origin = f"http://127.0.0.1:{server.server_port}"
        app.config = dataclasses.replace(
            config,
            port=server.server_port,
            frontend_dev=dataclasses.replace(dev, python_origin=origin),
        )
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for headers, want in (
            ({"Origin": origin}, 200),
            ({"Host": f"localhost:{server.server_port}"}, 403),
            ({"Host": "127.0.0.1:1"}, 403),
            ({"Origin": origin + "/not-an-origin"}, 403),
            ({"Origin": dev.vite_origin}, 403),
        ):
            with self.subTest(headers=headers):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=30)
                connection.request("GET", "/api/health", headers=headers)
                response = connection.getresponse()
                response.read()
                self.assertEqual(want, response.status)
                self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
                connection.close()

    def test_two_development_instances_bind_matching_identity_and_restart_generation(self) -> None:
        self.start_listener()
        dev = frontend_dev.admit(self.path, self.config())
        for generation in ("33" * 16, "44" * 16):
            selected = dataclasses.replace(dev, backend_generation=generation)
            html = frontend_dev.load_page(selected)
            config = self.config(frontend_dev=selected)
            state = build_runtime_state(config, started=1)
            app = cli.build_application(
                config, state, record_history=False, frontend_page_bytes=html
            )
            result = app.collect(show_all=False, notify=False)
            self.assertEqual("react-dev-" + hashlib.sha256(html).hexdigest()[:16], result["build"])
            self.assertEqual("", app.native_notifier(config.platform_name))
            self.assertEqual("no-lane", app.popup_notifier("fixture", "fixture"))

    def test_wrong_ticket_refuses_before_state_writes_and_recovery_skips_handshake(self) -> None:
        self.start_listener(bad="signature")
        env = {
            "HOME": str(self.root),
            "USERPROFILE": str(self.root),
            "COMPASS_HOME": str(self.root / "state"),
        }
        args = ["--frontend-dev-manifest", str(self.path), "--port", "4581"]
        with (
            mock.patch.object(cli, "runtime_environ", return_value=env),
            redirect_stderr(io.StringIO()),
        ):
            self.assertEqual(1, cli.main(args))
            self.assertFalse((self.root / "state").exists())
            self.path.unlink()
            with mock.patch.object(
                frontend_dev, "admit", side_effect=AssertionError("recovery probed Vite")
            ):
                self.assertIn(cli.main([*args, "--status"]), (0, 1))

    def test_inert_capability_fixture_uses_real_cli_authentication_without_native_focus(
        self,
    ) -> None:
        helper = Path(__file__).resolve().parents[4] / "frontend/test/dev_capability_backend.py"
        self.assertTrue(helper.is_file(), "inert capability fixture is missing")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        self.data["python_origin"] = f"http://127.0.0.1:{port}"
        self.start_listener()
        env = dict(os.environ)
        env.update(
            HOME=str(self.root),
            USERPROFILE=str(self.root),
            COMPASS_HOME=str(self.root / "state"),
            XDG_DATA_HOME=str(self.root / "data"),
            LOCALAPPDATA=str(self.root / "local"),
            APPDATA=str(self.root / "roaming"),
        )
        for name in runtime_config.STORE_ENV_VARS:
            env[name] = str(self.root / name.lower())
        process = subprocess.Popen(
            [
                sys.executable,
                str(helper),
                "--frontend-dev-manifest",
                str(self.path),
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 30
            body = b""
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    _, stderr = process.communicate(timeout=30)
                    self.fail(stderr.decode())
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                    connection.request("GET", "/")
                    response = connection.getresponse()
                    body = response.read()
                    connection.close()
                    if response.status == 200:
                        break
                except OSError:
                    time.sleep(0.02)

            class FocusMeta(HTMLParser):
                token = ""

                def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                    values = dict(attrs)
                    if tag == "meta" and values.get("name") == "compass-focus":
                        self.token = values.get("content") or ""

            parser = FocusMeta()
            parser.feed(body.decode())
            self.assertEqual(64, len(parser.token))
            for token, want in ((parser.token, 200), ("0" * 64, 403), ("", 403)):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                connection.request(
                    "POST",
                    "/api/focus",
                    body=b'{"harness":"codex","sid":"inert-missing"}',
                    headers={
                        "Content-Type": "application/json",
                        "X-Compass-Capability": token,
                        "Origin": self.data["python_origin"],
                    },
                )
                response = connection.getresponse()
                answer = response.read()
                self.assertEqual(want, response.status)
                if want == 200:
                    self.assertEqual({"focused": False}, json.loads(answer))
                connection.close()
        finally:
            process.terminate()
            process.communicate(timeout=30)


if __name__ == "__main__":
    unittest.main()
