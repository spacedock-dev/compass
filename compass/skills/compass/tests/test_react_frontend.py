from __future__ import annotations

import hashlib
import http.client
import importlib.util
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import aggregate, cli, lifecycle
from compass_runtime import config as runtime_config
from compass_runtime.web import page

from .support import make_runtime


class ReactFrontendTest(unittest.TestCase):
    HTML = b'<!doctype html><html><head><title>React</title></head><body><div id="root"></div></body></html>\n'

    def setUp(self) -> None:
        self.assertTrue(
            callable(getattr(page, "load_frontend_page", None)),
            "selected artifact loader is missing",
        )
        self.temp = tempfile.TemporaryDirectory(prefix="compass-react-page-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(page, "WEB_DIR", self.root).start()
        # `build_id` is cached for the life of a process, and React is the default now, so
        # any earlier test that built an application has already cached the real page's id.
        page.build_id.cache_clear()
        self.addCleanup(page.build_id.cache_clear)
        self.write_package(self.HTML)

    def write_package(self, html: bytes) -> None:
        licenses = b"Controlled test license\n"
        self.metadata: dict[str, Any] = {
            "format": 1,
            "frontend": "react",
            "document": {
                "file": "react.html",
                "bytes": len(html),
                "sha256": hashlib.sha256(html).hexdigest(),
            },
            "licenses": {
                "file": "react-licenses.txt",
                "bytes": len(licenses),
                "sha256": hashlib.sha256(licenses).hexdigest(),
            },
            "provenance": {"sources": [], "fonts": [], "packages": []},
        }
        (self.root / "react.html").write_bytes(html)
        (self.root / "react-licenses.txt").write_bytes(licenses)
        self.write_metadata()

    def write_metadata(self) -> None:
        (self.root / "react.integrity.json").write_text(
            json.dumps(self.metadata) + "\n", encoding="utf-8"
        )

    def test_selected_page_and_focus_injection_preserve_pre_capability_identity(self) -> None:
        loaded = page.load_frontend_page()
        self.assertEqual(self.HTML, loaded)
        injected = cli.inject_focus_capability(loaded, "abcdef")
        self.assertEqual(1, injected.count(b'name="compass-focus"'))
        self.assertEqual(1, injected.count(b"</head>"))
        self.assertEqual(
            self.HTML, injected.replace(b'<meta name="compass-focus" content="abcdef">', b"")
        )
        self.assertEqual("react-" + hashlib.sha256(self.HTML).hexdigest()[:16], page.build_id())

    def test_missing_or_corrupt_required_files_refuse_without_fallback(self) -> None:
        for name in ("react.html", "react.integrity.json", "react-licenses.txt"):
            with self.subTest(name=name):
                self.write_package(self.HTML)
                (self.root / name).unlink()
                with self.assertRaises((OSError, RuntimeError)):
                    page.load_frontend_page()
                self.write_package(self.HTML)
                (self.root / name).write_bytes(b"corrupt")
                with self.assertRaises((OSError, RuntimeError)):
                    page.load_frontend_page()

    def test_rehashed_ambiguous_head_or_existing_capability_refuses(self) -> None:
        for html in (
            self.HTML.replace(b"</head>", b"</head></head>"),
            self.HTML.replace(b"</head>", b"</HEAD>"),
            self.HTML.replace(b"</head>", b'<meta name="compass-focus" content="dead"></head>'),
            self.HTML.replace(b"\n", b"\r\n"),
            self.HTML + b"\xff",
        ):
            with self.subTest(html=html):
                self.write_package(html)
                with self.assertRaises(RuntimeError):
                    page.load_frontend_page()

    def test_head_literal_in_comment_script_or_data_cannot_impersonate_real_head_end(self) -> None:
        for literal in (
            b"<!-- </head> -->",
            b'<script>const literal="</head>";</script>',
            b"<script src=\"data:text/javascript,console.log('</head>')\"></script>",
        ):
            with self.subTest(literal=literal):
                html = self.HTML.replace(b"</head>", literal + b"</HEAD>")
                self.write_package(html)
                with self.assertRaises(RuntimeError):
                    page.load_frontend_page()

    def test_unicode_multiline_prefix_keeps_actual_head_injection_position(self) -> None:
        html = self.HTML.replace(b"<html>", "\n<!-- Ω🙂 -->\n<html>\n".encode())
        self.write_package(html)
        loaded = page.load_frontend_page()
        self.assertEqual(html, loaded)
        meta = b'<meta name="compass-focus" content="abcdef">'
        self.assertEqual(
            html.replace(b"</head>", meta + b"</head>"),
            cli.inject_focus_capability(loaded, "abcdef"),
        )

    def test_wrong_schema_typed_size_and_path_cannot_redirect_loader(self) -> None:
        for key, value in (
            ("bytes", True),
            ("bytes", len(self.HTML) + 1),
            ("file", "../index.html"),
            ("sha256", "0" * 64),
        ):
            with self.subTest(key=key, value=value):
                self.write_package(self.HTML)
                self.metadata["document"][key] = value
                self.write_metadata()
                with self.assertRaises(RuntimeError):
                    page.load_frontend_page()
        self.write_package(self.HTML)
        self.metadata["unexpected"] = "not accepted"
        self.write_metadata()
        with self.assertRaises(RuntimeError):
            page.load_frontend_page()

    def test_there_is_no_renderer_choice_to_make(self) -> None:
        parser = cli.build_parser()
        for argv in (["--frontend", "react"], ["--frontend", "legacy"], ["--frontend=react"]):
            with (
                self.subTest(argv=argv),
                self.assertRaises(SystemExit),
                redirect_stderr(io.StringIO()),
            ):
                parser.parse_args(argv)
        config, _ = cli.build_runtime(parser.parse_args([]), started=1)
        self.assertFalse(hasattr(config, "frontend"))
        for name in ("DEFAULT_FRONTEND", "FRONTENDS"):
            self.assertFalse(hasattr(runtime_config, name), name)
        with self.assertRaises(TypeError):
            runtime_config.build_runtime_config(
                environ={"HOME": "/nonexistent-compass-test"},
                platform_name="linux",
                os_name="posix",
                launcher_path=Path("server.py"),
                frontend="react",  # type: ignore[call-arg]  # the removed keyword is the subject
            )

    def test_the_detached_child_is_spawned_without_a_renderer_argument(self) -> None:
        parser = cli.build_parser()
        selected = parser.parse_args(["--daemon"])
        config, _ = cli.build_runtime(selected, started=1)
        argv = lifecycle.spawn_argv(config, selected)
        self.assertNotIn("--frontend", argv)
        self.assertNotIn("--daemon", argv)
        # The child parses what it was given, so a stray renderer argument would refuse here.
        parser.parse_args(argv[2:])

    def test_the_development_frontend_wants_a_foreground_loopback_server(self) -> None:
        parser = cli.build_parser()
        manifest = ["--frontend-dev-manifest", "ticket.json"]
        cli.validate_frontend_args(parser, parser.parse_args(manifest))
        for extra in (["--daemon"], ["--host", "0.0.0.0"], ["--diagnose"]):
            with (
                self.subTest(extra=extra),
                self.assertRaises(SystemExit),
                redirect_stderr(io.StringIO()),
            ):
                cli.validate_frontend_args(parser, parser.parse_args([*manifest, *extra]))

    def test_bad_selected_artifact_fails_before_server_or_daemon_setup(self) -> None:
        (self.root / "react.html").unlink()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(1, cli.main(["--no-events", "--daemon"]))
        self.assertIn("cannot load frontend assets", stderr.getvalue())

    def test_a_broken_build_says_to_reinstall_and_serves_nothing_in_its_place(self) -> None:
        (self.root / "react.html").unlink()
        loads: list[bool] = []
        real = page.load_frontend_page

        def spy() -> bytes:
            loads.append(True)
            return real()

        stderr = io.StringIO()
        with mock.patch.object(page, "load_frontend_page", spy), redirect_stderr(stderr):
            self.assertEqual(1, cli.main(["--no-events"]))
        self.assertEqual([True], loads)
        self.assertIn("reinstall the plugin", stderr.getvalue())

    def test_duplicate_metadata_keys_and_bad_provenance_refuse(self) -> None:
        self.metadata["provenance"]["sources"] = [
            {"file": "../private-session", "sha256": "0" * 64}
        ]
        self.write_metadata()
        with self.assertRaises(RuntimeError):
            page.load_frontend_page()
        self.write_package(self.HTML)
        encoded = json.dumps(self.metadata).replace('"format": 1', '"format": 1, "format": 1')
        (self.root / "react.integrity.json").write_text(encoded, encoding="utf-8")
        with self.assertRaises(RuntimeError):
            page.load_frontend_page()

    def test_optional_terminal_inventory_checks_fixed_local_assets(self) -> None:
        (self.root / "vendor").mkdir()
        terminal = {}
        for kind, name in (("javascript", "xterm.js"), ("stylesheet", "xterm.css")):
            payload = b"synthetic asset\n"
            (self.root / "vendor" / name).write_bytes(payload)
            terminal[kind] = {
                "file": "vendor/" + name,
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        self.metadata["optionalTerminal"] = terminal
        self.write_metadata()
        self.assertEqual(self.HTML, page.load_frontend_page())
        (self.root / "vendor/xterm.js").write_bytes(b"corrupt")
        with self.assertRaises(RuntimeError):
            page.load_frontend_page()

    def test_an_application_publishes_the_identity_of_the_page_it_was_given(self) -> None:
        config, state = make_runtime(
            usage_fetch_enabled=False, history_enabled=False, annotations_enabled=False
        )
        app = aggregate.Application(
            config,
            state,
            (),
            native_notifier=lambda _: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _: None,
            frontend_page_bytes=self.HTML,
        )
        result = app.collect(show_all=False)
        self.assertEqual("react-" + hashlib.sha256(self.HTML).hexdigest()[:16], result["build"])
        self.assertNotIn("frontend", result)


# The twenty script parts of the retired page. The page is a React build now, so none of them may
# ship under `web/`; the parts themselves were removed with the paused study that bound them.
RETIRED_PAGE_PARTS: tuple[str, ...] = (
    "next-boot.js",
    "next-observed.js",
    "next-attention.js",
    "next-notify.js",
    "next-cockpit-compat.js",
    "project.js",
    "next-chrome.js",
    "next-capacity.js",
    "next-sessions.js",
    "next-projects.js",
    "next-project.js",
    "next-intent.js",
    "next-activity.js",
    "next-session.js",
    "next-workstream.js",
    "next-delegation.js",
    "next-controls.js",
    "next-cockpit.js",
    "next-render.js",
    "next-live.js",
)


class TheDashboardNoLongerCarriesTheRetiredPageTest(unittest.TestCase):
    def test_no_part_remains_under_the_shipped_web_directory(self) -> None:
        web = Path(page.__file__).resolve().parent
        self.assertTrue((web / "react.html").is_file(), "not the shipped web directory")
        for name in RETIRED_PAGE_PARTS:
            with self.subTest(part=name):
                self.assertFalse((web / name).exists())


class InstalledFrontendTest(unittest.TestCase):
    @staticmethod
    def child_environment(root: Path) -> dict[str, str]:
        env = {
            "PATH": str(root / "no-node"),
            "HOME": str(root / "home"),
            "USERPROFILE": str(root / "home"),
            "COMPASS_HOME": str(root / "state"),
            "PYTHONNOUSERSITE": "1",
        }
        if os.name == "nt":
            env.update(
                {
                    key: value
                    for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR"}
                }
            )
        return env

    def test_windows_loader_environment_survives_without_host_data_or_executables(self) -> None:
        helper = Path(__file__).resolve().parents[4] / "frontend/test/installed_backend.py"
        spec = importlib.util.spec_from_file_location("installed_backend_environment", helper)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(
            callable(getattr(module, "isolated_environment", None)),
            "OS loader environment isolation is missing",
        )
        scratch = Path("/owned-fixture")
        hostile = {
            "SystemRoot": "C:\\Windows",
            "windir": "C:\\Windows",
            "HOME": "/real-user",
            "USERPROFILE": "/real-user",
            "PATH": "/real-node-bin",
            "APPDATA": "/real-agent-data",
            "LOCALAPPDATA": "/real-agent-data",
            "CODEX_HOME": "/real-codex",
            "CLAUDE_CONFIG_DIR": "/real-claude",
            "PI_CODING_AGENT_DIR": "/real-pi",
            "XDG_DATA_HOME": "/real-data",
            "OPENAI_API_KEY": "synthetic-secret",
            "NODE_AUTH_TOKEN": "synthetic-secret",
        }
        expected = {
            "HOME": str(scratch),
            "USERPROFILE": str(scratch),
            "COMPASS_HOME": str(scratch / "state"),
            "PATH": str(scratch / "no-executables"),
            "SYSTEMROOT": "C:\\Windows",
            "WINDIR": "C:\\Windows",
        }
        self.assertEqual(expected, module.isolated_environment(scratch, hostile, os_name="nt"))
        self.assertEqual(
            {k: v for k, v in expected.items() if k not in {"SYSTEMROOT", "WINDIR"}},
            module.isolated_environment(scratch, hostile, os_name="posix"),
        )

    @staticmethod
    def close_owned_process(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                stream.close()

    def assert_terminal_fixture(
        self, conn: http.client.HTTPConnection, ready: dict[str, Any], plugin: Path
    ) -> None:
        self.assertIn(":console", ready["terminal_fragment"])
        conn.request(
            "GET",
            "/api/interaction/origin?harness=codex&sid=disposable-tmux-origin%3A1",
        )
        response = conn.getresponse()
        origin = json.loads(response.read())
        self.assertEqual("registered", origin["state"])
        self.assertEqual("not-exposed", origin["keyboard_input"])
        for asset in ("xterm.js", "xterm.css"):
            conn.request(
                "GET",
                "/assets/" + asset,
                headers={"Sec-Fetch-Site": "same-origin"},
            )
            response = conn.getresponse()
            self.assertEqual(200, response.status)
            self.assertEqual(
                (plugin / "skills/compass/compass_runtime/web/vendor" / asset).read_bytes(),
                response.read(),
            )
            conn.request(
                "GET",
                "/assets/" + asset,
                headers={"Sec-Fetch-Site": "cross-site"},
            )
            response = conn.getresponse()
            self.assertEqual(403, response.status)
            response.read()

    def test_selected_corruption_fails_before_bind_and_recovery_ignores_assets(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory(prefix="compass-installed-corrupt-") as temporary:
            root = Path(temporary)
            plugin = root / "plugin"
            shutil.copytree(
                repo / "compass", plugin, ignore=shutil.ignore_patterns("tests", "__pycache__")
            )
            env = self.child_environment(root)
            launcher = plugin / "skills/compass/server.py"
            web = plugin / "skills/compass/compass_runtime/web"
            # Hold the candidate port ourselves: a startup that reaches bind
            # would report a port collision instead of the selected asset error.
            with socket.socket() as held:
                held.bind(("127.0.0.1", 0))
                port = str(held.getsockname()[1])
                for name in ("react.html", "react.integrity.json", "react-licenses.txt"):
                    original = (web / name).read_bytes()
                    for mutation in (None, b"corrupt"):
                        with self.subTest(name=name, mutation=mutation):
                            if mutation is None:
                                (web / name).unlink()
                            else:
                                (web / name).write_bytes(mutation)
                            result = subprocess.run(
                                [
                                    sys.executable,
                                    str(launcher),
                                    "--daemon",
                                    "--port",
                                    port,
                                ],
                                capture_output=True,
                                text=True,
                                env=env,
                                timeout=10,
                                check=False,
                            )
                            self.assertEqual(1, result.returncode)
                            self.assertIn("cannot load frontend assets", result.stderr)
                            self.assertFalse((root / "state").exists())
                            (web / name).write_bytes(original)
            (web / "react.html").unlink()
            for option in ("--help", "--status", "--stop"):
                result = subprocess.run(
                    [sys.executable, str(launcher), "--port", port, option],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=10,
                    check=False,
                )
                self.assertIn(result.returncode, (0, 1))
                self.assertNotIn("cannot load frontend assets", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_the_installed_launcher_serves_the_react_page(self) -> None:
        # The real launcher, not the fixture helper: this is what a reader types. Node is
        # absent from PATH and the home is empty, so the page can only come from the
        # installed copy's own files and no real store is read.
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory(prefix="compass-installed-default-") as temporary:
            root = Path(temporary)
            plugin = root / "plugin"
            shutil.copytree(
                repo / "compass", plugin, ignore=shutil.ignore_patterns("tests", "__pycache__")
            )
            env = self.child_environment(root)
            launcher = plugin / "skills/compass/server.py"
            react_page = (plugin / "skills/compass/compass_runtime/web/react.html").read_bytes()
            quiet = ("--no-usage", "--no-git", "--no-focus", "--no-reach", "--no-history")
            for label, detach in (("foreground", False), ("detached", True)):
                with self.subTest(label=label):
                    port = self.free_port()
                    argv = [sys.executable, str(launcher), "--port", str(port), *quiet]
                    stop = [sys.executable, str(launcher), "--port", str(port), "--stop"]
                    proc: subprocess.Popen[str] | None = None
                    try:
                        if detach:
                            started = subprocess.run(
                                [*argv, "--daemon"],
                                capture_output=True,
                                text=True,
                                env=env,
                                timeout=60,
                                check=False,
                            )
                            self.assertEqual(0, started.returncode, started.stdout + started.stderr)
                        else:
                            proc = subprocess.Popen(
                                argv,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                env=env,
                                text=True,
                            )
                        body, payload = self.fetch_page_and_data(port, proc)
                        self.assertEqual(react_page, body)
                        self.assertEqual(
                            "react-" + hashlib.sha256(body).hexdigest()[:16], payload["build"]
                        )
                        self.assertNotIn("frontend", payload)
                    finally:
                        subprocess.run(
                            stop,
                            capture_output=True,
                            env=env,
                            timeout=30,
                            check=False,
                        )
                        if proc is not None:
                            self.close_owned_process(proc)

    def test_a_second_start_on_a_busy_port_says_to_use_the_running_dashboard(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory(prefix="compass-installed-occupied-") as temporary:
            root = Path(temporary)
            plugin = root / "plugin"
            shutil.copytree(
                repo / "compass", plugin, ignore=shutil.ignore_patterns("tests", "__pycache__")
            )
            env = self.child_environment(root)
            launcher = str(plugin / "skills/compass/server.py")
            quiet = ("--no-usage", "--no-git", "--no-focus", "--no-reach", "--no-history")
            port = self.free_port()
            base = [sys.executable, launcher, "--port", str(port), *quiet]

            def run(*extra: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [*base, *extra],
                    capture_output=True,
                    text=True,
                    env=env,
                    timeout=60,
                    check=False,
                )

            try:
                started = run("--daemon")
                self.assertEqual(0, started.returncode, started.stdout + started.stderr)
                status = run("--status")
                self.assertEqual(0, status.returncode, status.stdout + status.stderr)
                self.assertNotIn("frontend", status.stdout)
                for detach in (("--daemon",), ()):
                    again = run(*detach)
                    self.assertEqual(1, again.returncode, again.stdout + again.stderr)
                    self.assertIn("use it", again.stdout + again.stderr)
            finally:
                run("--stop")

    @staticmethod
    def free_port() -> int:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    @staticmethod
    def fetch_page_and_data(
        port: int, proc: subprocess.Popen[str] | None
    ) -> tuple[bytes, dict[str, Any]]:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if proc is not None and proc.poll() is not None:
                assert proc.stderr is not None
                raise AssertionError(f"launcher exited early: {proc.stderr.read()}")
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    conn.request("GET", "/")
                    body = conn.getresponse().read()
                    conn.request("GET", "/api/data")
                    payload = json.loads(conn.getresponse().read())
                finally:
                    conn.close()
            except (OSError, ValueError):
                time.sleep(0.1)
                continue
            return body, payload
        raise AssertionError(f"nothing answered on port {port}")

    def test_installed_copy_serves_without_node_and_cleans_up_on_eof(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        helper = repo / "frontend/test/installed_backend.py"
        self.assertTrue(helper.is_file(), "installed-copy backend helper is missing")
        with tempfile.TemporaryDirectory(prefix="compass-installed-react-") as temporary:
            root = Path(temporary)
            plugin = root / "plugin"
            shutil.copytree(
                repo / "compass", plugin, ignore=shutil.ignore_patterns("tests", "__pycache__")
            )
            env = self.child_environment(root)
            for label, extra in (
                ("focus capability", ["--focus-token", "abcdef"]),
                ("terminal fixture", ["--terminal-fixture"]),
            ):
                with self.subTest(label=label):
                    proc = subprocess.Popen(
                        [
                            sys.executable,
                            str(helper),
                            "--plugin-root",
                            str(plugin),
                            "--port",
                            "0",
                            *extra,
                        ],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                        text=True,
                    )
                    try:
                        assert proc.stdout is not None
                        ready_line = proc.stdout.readline()
                        if not ready_line:
                            assert proc.stderr is not None
                            self.fail(proc.stderr.read())
                        ready = json.loads(ready_line)
                        self.assertTrue(ready["ready"])
                        self.assertTrue(Path(ready["runtime"]).is_relative_to(plugin.resolve()))
                        conn = http.client.HTTPConnection("127.0.0.1", ready["port"], timeout=5)
                        conn.request("GET", "/")
                        response = conn.getresponse()
                        body = response.read()
                        self.assertEqual(200, response.status)
                        if label == "focus capability":
                            self.assertEqual(
                                1, body.count(b'<meta name="compass-focus" content="abcdef">')
                            )
                        conn.request("GET", "/?frontend=legacy")
                        response = conn.getresponse()
                        self.assertEqual(body, response.read())
                        conn.request("GET", "/api/data")
                        response = conn.getresponse()
                        payload = json.loads(response.read())
                        if label == "terminal fixture":
                            self.assert_terminal_fixture(conn, ready, plugin)
                        conn.close()
                        self.assertEqual(
                            "react-"
                            + hashlib.sha256(
                                body.replace(b'<meta name="compass-focus" content="abcdef">', b"")
                            ).hexdigest()[:16],
                            payload["build"],
                        )
                        assert proc.stdin is not None
                        proc.stdin.close()
                        proc.wait(timeout=10)
                        self.assertEqual(0, proc.returncode)
                    finally:
                        self.close_owned_process(proc)


if __name__ == "__main__":
    unittest.main()
