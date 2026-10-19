from __future__ import annotations

import ast
import contextlib
import http.client
import json
import os
import runpy
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

from compass_runtime import aggregate, cli, http_api, notifications, observation, records
from compass_runtime import io as runtime_io
from compass_runtime import sessions as runtime_sessions
from compass_runtime import transcripts as runtime_transcripts
from compass_runtime import turns as runtime_turns
from compass_runtime.collectors import claude as claude_collector
from compass_runtime.collectors import codex as codex_collector
from compass_runtime.collectors import gemini as gemini_collector

from .fixtures import (
    CURSOR_MODEL,
    HARNESSES,
    OPENCODE_MODEL,
    STORE_CONSTANTS,
    build_cursor,
    build_opencode,
    build_pi,
)
from .support import (
    REGISTRY,
    SERVER_PATH,
    STORE_OVERRIDES,
    HarnessContractTestCase,
    RuntimeTestCase,
    collect,
    collect_claude,
    config_patch,
    make_runtime,
    runtime,
    serve_until_closed,
    store_patch,
)

SKILL_DIR = Path(__file__).resolve().parents[1]
RUNTIME_DIR = SKILL_DIR / "compass_runtime"
RUNTIME_PREFIX = "compass_runtime"
FORBIDDEN_RUNTIME_PREFIX = "compass.skills.compass.compass_runtime"

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState


class ApplicationIsolationTest(unittest.TestCase):
    """Two applications in one process must share nothing.

    The design requires it because a contract test starts two servers with
    different configurations and proves requests and notification state do not
    cross. Everything asserted here is what "do not cross" has to mean.
    """

    @staticmethod
    def _spec(
        key: str,
        *,
        discover_error: BaseException | None = None,
        collect_error: BaseException | None = None,
        sessions: int = 1,
        usage_entries: list[dict[str, Any]] | None = None,
        usage_error: BaseException | None = None,
        usage_is_fetch: bool = False,
    ) -> aggregate.HarnessSpec:
        """A runtime-native harness: it reads the config and state it is given."""

        def discover(config: RuntimeConfig, state: RuntimeState) -> bool:
            if discover_error is not None:
                raise discover_error
            state.store_errors[f"{key}-discovered"] = config.home
            return True

        def collect(
            config: RuntimeConfig,
            state: RuntimeState,
            now: float,
            window_hours: float,
            show_all: bool,
        ) -> list[dict[str, Any]]:
            if collect_error is not None:
                raise collect_error
            rows = []
            for index in range(sessions):
                row = runtime_sessions.base_session(key, f"{key}-{index}", config.home)
                # Carry the inputs into the row so a crossed config, state,
                # clock or window is visible in the collection itself.
                row["last_activity"] = now
                row["title"] = f"{id(state)}|{window_hours}|{show_all}"
                rows.append(row)
            return rows

        usage: aggregate.UsageProvider | None = None
        if usage_entries is not None or usage_error is not None:

            def usage(
                config: RuntimeConfig,
                state: RuntimeState,
                now: float,
                window_hours: float,
            ) -> list[dict[str, Any]]:
                del config, state, now, window_hours
                if usage_error is not None:
                    raise usage_error
                return list(usage_entries or [])

        return aggregate.HarnessSpec(
            key=key,
            label=key.title(),
            discover=discover,
            collect=collect,
            usage=usage,
            usage_is_fetch=usage_is_fetch,
        )

    @staticmethod
    def _rate_spec(
        key: str,
        *,
        reports_rate: bool,
        rate_per_min: int = 0,
        active: bool = False,
    ) -> aggregate.HarnessSpec:
        def collect(
            config: RuntimeConfig,
            state: RuntimeState,
            now: float,
            window_hours: float,
            show_all: bool,
        ) -> list[dict[str, Any]]:
            del state, window_hours, show_all
            row = runtime_sessions.base_session(key, f"{key}-0", config.home)
            row.update(
                last_activity=now,
                rate_per_min=rate_per_min,
                active=active,
                state="working" if active else "idle",
            )
            return [row]

        return aggregate.HarnessSpec(
            key=key,
            label=key.title(),
            discover=lambda _config, _state: True,
            collect=collect,
            reports_rate=reports_rate,
        )

    def _application(
        self,
        *,
        home: str,
        started: float,
        clock: float,
        notifier: str,
        harnesses: tuple[aggregate.HarnessSpec, ...],
        platform_name: str = "linux",
    ) -> tuple[aggregate.Application, RuntimeConfig, RuntimeState, list[str], list[str]]:
        config, state = make_runtime(started=started, home=home, platform_name=platform_name)
        diagnostics: list[str] = []
        popups: list[str] = []
        application = aggregate.Application(
            config,
            state,
            harnesses,
            # Echo the argument: the field must be derived from this
            # application's platform, never from ambient sys.platform.
            native_notifier=lambda platform: f"{notifier}@{platform}",
            popup_notifier=lambda title, message: popups.append(f"{title}:{message}"),
            diagnostic_sink=diagnostics.append,
            clock=lambda: clock,
        )
        return application, config, state, diagnostics, popups

    def test_two_applications_share_no_config_state_memo_clock_or_notifier(self) -> None:
        first, config_a, state_a, diag_a, popups_a = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(self._spec("alpha"),),
        )
        second, config_b, state_b, diag_b, popups_b = self._application(
            home="/home/b",
            started=22.0,
            clock=2000.0,
            notifier="notifier-b",
            harnesses=(self._spec("beta"),),
            platform_name="win32",
        )

        data_a = first.collect(show_all=True)
        data_b = second.collect(show_all=True)

        # The clock is per application, so "generated" cannot be shared.
        self.assertEqual(1000.0, data_a["generated"])
        self.assertEqual(2000.0, data_b["generated"])
        # The native-notify field comes from the injected notifier, called with
        # this application's platform. Mutation-checked: reading sys.platform
        # here instead of config.platform_name previously passed the suite.
        self.assertEqual(f"notifier-a@{config_a.platform_name}", data_a["native_notify"])
        self.assertEqual(f"notifier-b@{config_b.platform_name}", data_b["native_notify"])
        self.assertNotEqual(config_a.platform_name, config_b.platform_name)
        # Each application saw only its own registry.
        self.assertEqual(["alpha"], [h["key"] for h in data_a["harnesses"]])
        self.assertEqual(["beta"], [h["key"] for h in data_b["harnesses"]])
        # Each collector read its own config and state, not the other's.
        self.assertEqual(["/home/a"], [s["project"] for s in data_a["sessions"]])
        self.assertEqual(["/home/b"], [s["project"] for s in data_b["sessions"]])
        self.assertEqual(
            f"{id(state_a)}|{config_a.window_hours}|True", data_a["sessions"][0]["title"]
        )
        self.assertEqual(
            f"{id(state_b)}|{config_b.window_hours}|True", data_b["sessions"][0]["title"]
        )
        # Discovery also received the right config and state.
        self.assertEqual({"alpha-discovered": "/home/a"}, state_a.store_errors)
        self.assertEqual({"beta-discovered": "/home/b"}, state_b.store_errors)
        # Separate sinks, separate popup notifiers, separate start times.
        self.assertEqual(([], []), (diag_a, diag_b))
        self.assertIsNot(popups_a, popups_b)
        self.assertEqual((11.0, 22.0), (state_a.server_started, state_b.server_started))

    def test_rate_blind_rows_publish_unknown_without_erasing_a_real_zero(self) -> None:
        application, *_ = self._application(
            home="/home/rates",
            started=1.0,
            clock=1000.0,
            notifier="none",
            harnesses=(
                self._rate_spec("blind", reports_rate=False),
                self._rate_spec("measured", reports_rate=True),
            ),
        )

        rows = application.collect(show_all=True)["sessions"]
        rates = {row["harness"]: row["rate_per_min"] for row in rows}

        self.assertIsNone(rates["blind"])
        self.assertEqual(0, rates["measured"])

    def test_summary_sums_measured_rates_when_an_active_rate_is_unknown(self) -> None:
        application, *_ = self._application(
            home="/home/rates",
            started=1.0,
            clock=1000.0,
            notifier="none",
            harnesses=(
                self._rate_spec("blind", reports_rate=False, rate_per_min=99, active=True),
                self._rate_spec("measured", reports_rate=True, rate_per_min=7, active=True),
            ),
        )

        data = application.collect(show_all=True)

        self.assertIsNone(data["sessions"][0]["rate_per_min"])
        self.assertEqual(7, data["summary"]["rate_per_min"])

    def _get(self, port: int, path: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def _post(self, port: int, path: str, payload: dict[str, Any]) -> bytes:
        body = json.dumps(payload).encode()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
            return conn.getresponse().read()
        finally:
            conn.close()

    def test_two_servers_answer_only_for_their_own_application(self) -> None:
        # The design requires this: CompassHTTPServer stores exactly one
        # application and one page, and handlers read them off the server
        # instance. Two live servers in one interpreter must not cross.
        first, config_a, state_a, _, popups_a = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(self._spec("alpha"),),
        )
        second, config_b, state_b, _, popups_b = self._application(
            home="/home/b",
            started=22.0,
            clock=2000.0,
            notifier="notifier-b",
            harnesses=(self._spec("beta"),),
        )
        coordinators = [
            observation.Observation(app, diagnostic_sink=lambda _message: None)
            for app in (first, second)
        ]
        servers = [
            http_api.CompassHTTPServer(("127.0.0.1", 0), app, page, coordinator)
            for (app, page), coordinator in zip(
                ((first, b"<page-a>"), (second, b"<page-b>")), coordinators, strict=True
            )
        ]
        threads = [serve_until_closed(httpd) for httpd in servers]
        port_a, port_b = (httpd.server_port for httpd in servers)
        try:
            # The page is per instance, not a module global.
            self.assertEqual((200, b"<page-a>"), self._get(port_a, "/"))
            self.assertEqual((200, b"<page-b>"), self._get(port_b, "/"))

            data_a = json.loads(self._get(port_a, "/api/data")[1])
            data_b = json.loads(self._get(port_b, "/api/data")[1])
            self.assertEqual(["alpha"], [h["key"] for h in data_a["harnesses"]])
            self.assertEqual(["beta"], [h["key"] for h in data_b["harnesses"]])
            # Each collected on its own injected clock and config.
            self.assertEqual((1000.0, 2000.0), (data_a["generated"], data_b["generated"]))
            self.assertEqual(["/home/a"], [row["project"] for row in data_a["sessions"]])
            self.assertEqual(["/home/b"], [row["project"] for row in data_b["sessions"]])

            # /api/health reports each server's own port and start stamp.
            health_a = json.loads(self._get(port_a, "/api/health")[1])
            health_b = json.loads(self._get(port_b, "/api/health")[1])
            self.assertEqual((port_a, 11.0), (health_a["port"], health_a["started"]))
            self.assertEqual((port_b, 22.0), (health_b["port"], health_b["started"]))

            # A notification POST lands in the receiving server's state only,
            # and pops through that application's own notifier.
            self._post(port_a, "/api/notify", {"session_id": "aaaaaaaa", "message": "permission"})
            self.assertIn("aaaaaaaa", state_a.hook_notifications)
            self.assertEqual({}, dict(state_b.hook_notifications))
            self.assertEqual(1, len(popups_a))
            self.assertEqual([], popups_b)

            # Give B its own standing hook, then end that session on A. A
            # SessionEnd is the most destructive payload there is; it must not
            # reach across.
            self._post(port_b, "/api/notify", {"session_id": "aaaaaaaa", "message": "permission"})
            self.assertIn("aaaaaaaa", state_b.hook_notifications)
            self._post(
                port_a,
                "/api/notify",
                {"session_id": "aaaaaaaa", "hook_event_name": "SessionEnd"},
            )
            self.assertNotIn("aaaaaaaa", state_a.hook_notifications)
            self.assertIn("aaaaaaaa", state_b.hook_notifications)
            self.assertEqual(1, state_a.hook_generation["aaaaaaaa"])
            self.assertEqual(0, state_b.hook_generation.get("aaaaaaaa", 0))
            self.assertNotEqual(config_a.home, config_b.home)

            # /api/overlays reads the coordinator off the instance too. An event
            # submitted to A's coordinator must not appear in B's ledger, or the
            # diagnostic would attribute one server's overlays to the other,
            # which is the exact mistake it exists to prevent.
            coordinators[0].submit(
                "claude",
                {
                    "v": 1,
                    "event": "input_requested",
                    "session_id": "aaaaaaaa-0000-0000-0000-0000000a",
                },
            )
            self.assertEqual(
                ["needs_input"],
                [
                    row["kind"]
                    for row in json.loads(self._get(port_a, "/api/overlays")[1])["overlays"]
                ],
            )
            self.assertEqual([], json.loads(self._get(port_b, "/api/overlays")[1])["overlays"])
        finally:
            for httpd, thread in zip(servers, threads, strict=True):
                httpd.shutdown()
                thread.join(timeout=5)

    def test_health_reports_the_captured_start_stamp_without_a_second_clock_read(self) -> None:
        # --status and the daemon readiness wait poll this in a loop. Sampling a
        # clock in the handler would report a different uptime on every poll for
        # one unchanging process, so the value must be the sentinel that
        # build_runtime_state captured.
        sentinel = 1_234_567.5
        application, _, state, _, _ = self._application(
            home="/home/a",
            started=sentinel,
            clock=9_999_999.0,
            notifier="notifier-a",
            harnesses=(),
        )
        self.assertEqual(sentinel, state.server_started)
        httpd = http_api.CompassHTTPServer(("127.0.0.1", 0), application, b"<page>")
        thread = serve_until_closed(httpd)
        try:
            first = json.loads(self._get(httpd.server_port, "/api/health")[1])
            second = json.loads(self._get(httpd.server_port, "/api/health")[1])
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

        self.assertEqual(sentinel, first["started"])
        # Same value on a second poll, and never the application's clock.
        self.assertEqual(first["started"], second["started"])
        self.assertEqual(os.getpid(), first["pid"])

    def test_the_collection_memo_does_not_cross_applications(self) -> None:
        first, config_a, _, _, _ = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(self._spec("alpha"),),
        )
        second, config_b, _, _, _ = self._application(
            home="/home/b",
            started=22.0,
            clock=2000.0,
            notifier="notifier-b",
            harnesses=(self._spec("beta"),),
        )

        rev_a, body_a = first.collect_json(show_all=False)
        rev_b, body_b = second.collect_json(show_all=False)

        self.assertNotEqual(body_a, body_b)
        # Each application publishes into its own snapshot, so neither can serve
        # the other's bytes and their revisions count independently.
        self.assertIsNot(first.snapshot, second.snapshot)
        self.assertIsNone(first.snapshot.current((config_a.window_hours, True)))
        self.assertIsNone(second.snapshot.current((config_b.window_hours, True)))
        # A warm read comes from the application's own snapshot, not the
        # neighbour's, and reuse does not mint a revision.
        self.assertEqual((rev_a, body_a), first.collect_json(show_all=False))
        self.assertEqual((rev_b, body_b), second.collect_json(show_all=False))
        # A different show_all is a different key, so it is a second entry.
        first.collect_json(show_all=True)
        self.assertIsNotNone(first.snapshot.current((config_a.window_hours, True)))
        # The neighbour gained nothing from it.
        self.assertIsNone(second.snapshot.current((config_b.window_hours, True)))

    def test_the_memo_expires_on_the_injected_clock(self) -> None:
        # Mutation-checked: reading time.time() instead of self.clock() in the
        # freshness comparison previously passed the whole suite, which would
        # make every warm read look stale under an injected clock.
        now = [1000.0]
        config, state = make_runtime()
        collections: list[float] = []

        def collect(
            _config: RuntimeConfig,
            _state: RuntimeState,
            when: float,
            _window_hours: float,
            _show_all: bool,
        ) -> list[dict[str, Any]]:
            collections.append(when)
            return []

        application = aggregate.Application(
            config,
            state,
            (aggregate.HarnessSpec(key="a", label="A", discover=lambda *_: True, collect=collect),),
            native_notifier=lambda _platform: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _message: None,
            clock=lambda: now[0],
        )

        application.collect_json(show_all=False)
        self.assertEqual([1000.0], collections)
        # Still inside the window: served warm, and the entry carries the
        # injected clock's timestamp rather than a real reading.
        now[0] += config.collect_memo_sec / 2
        application.collect_json(show_all=False)
        self.assertEqual([1000.0], collections)
        # The published entry carries the injected clock, so its age at that
        # instant is zero rather than a real reading.
        self.assertEqual(0.0, application.snapshot.age((config.window_hours, False), now=1000.0))
        # Past the window: collected again, and the entry is re-stamped.
        now[0] = 1000.0 + config.collect_memo_sec + 1
        application.collect_json(show_all=False)
        self.assertEqual([1000.0, now[0]], collections)
        # Re-stamped on the injected clock: age is zero at the new "now".
        self.assertEqual(0.0, application.snapshot.age((config.window_hours, False), now=now[0]))

    def test_a_discovery_failure_marks_only_that_harness_absent(self) -> None:
        application, _, _, diagnostics, _ = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(
                self._spec("broken", discover_error=OSError("no store")),
                self._spec("healthy"),
            ),
        )

        data = application.collect(show_all=True)

        broken, healthy = data["harnesses"]
        self.assertEqual(
            ("broken", False, None), (broken["key"], broken["discovered"], broken["error"])
        )
        self.assertEqual(
            ("healthy", True, None), (healthy["key"], healthy["discovered"], healthy["error"])
        )
        # An absent store is not an error, so nothing is reported.
        self.assertEqual([], diagnostics)
        self.assertEqual(["healthy"], [s["harness"] for s in data["sessions"]])

    def test_usage_key_appears_only_when_a_provider_is_discovered(self) -> None:
        entry = {"harness": "quota", "state": "ok", "asOf": 999, "week": {"pct": 62}}
        with_provider, _, _, _, _ = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(self._spec("plain"), self._spec("quota", usage_entries=[entry])),
        )
        without_provider, _, _, _, _ = self._application(
            home="/home/b",
            started=11.0,
            clock=1000.0,
            notifier="notifier-b",
            harnesses=(self._spec("plain"),),
        )

        self.assertEqual([entry], with_provider.collect(show_all=True)["usage"])
        # No provider anywhere: the key is absent and the page stays dormant.
        self.assertNotIn("usage", without_provider.collect(show_all=True))

    def test_usage_fetch_flag_rises_only_for_a_discovered_fetch_provider(self) -> None:
        entry = {"harness": "fetched", "state": "ok", "asOf": 999, "week": {"pct": 10}}
        fetcher, _, _, _, _ = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(self._spec("fetched", usage_entries=[entry], usage_is_fetch=True),),
        )
        disk_only, _, _, _, _ = self._application(
            home="/home/b",
            started=11.0,
            clock=1000.0,
            notifier="notifier-b",
            harnesses=(self._spec("disk", usage_entries=[entry]),),
        )

        # The flag is what wakes the page's first-run disclosure banner, so a
        # disk-read provider must never raise it — the banner would then be
        # disclosing a fetch that does not exist.
        self.assertTrue(fetcher.collect(show_all=True).get("usage_fetch"))
        self.assertNotIn("usage_fetch", disk_only.collect(show_all=True))

    def test_no_usage_leaves_every_network_row_without_a_provider(self) -> None:
        # --no-usage arrives at assembly: each row keeps its fetch marking but
        # loses the provider, so nothing reads the fetch cache and the flag
        # can never rise. Asserted for every row that is marked as a fetch
        # rather than for Claude alone, so a second fetch vendor wired in
        # without the gate fails here instead of quietly fetching under
        # --no-usage. Antigravity is included by name: its quota is pushed in
        # rather than fetched, but the flag still drops it, because turning
        # usage off means the whole section.
        rows = {spec.key: spec for spec in aggregate.default_harnesses(usage_fetch_enabled=False)}
        default_rows = {spec.key: spec for spec in REGISTRY}
        gated = {key for key, spec in default_rows.items() if spec.usage_is_fetch} | {"antigravity"}
        self.assertEqual({"claude", "cursor", "antigravity"}, gated)
        for key in sorted(gated):
            with self.subTest(harness=key):
                self.assertIsNotNone(default_rows[key].usage, "no provider by default")
                self.assertIsNone(rows[key].usage, "--no-usage left a provider behind")
        # A disk reader is untouched by --no-usage's network half; the flag only
        # governs the fetch, and Codex's snapshots were already on this machine.
        self.assertIsNotNone(rows["codex"].usage)
        self.assertIsNotNone(rows["copilot"].usage)

    def test_a_usage_failure_is_contained_to_diagnostics(self) -> None:
        application, _, _, diagnostics, _ = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(self._spec("quota", usage_error=RuntimeError("torn snapshot")),),
        )

        data = application.collect(show_all=True)

        # The harness's session rows survive, its strip shows no error, and the
        # band gets an empty list rather than disappearing.
        self.assertEqual(["quota"], [s["harness"] for s in data["sessions"]])
        self.assertIsNone(data["harnesses"][0]["error"])
        self.assertEqual([], data["usage"])
        self.assertTrue(any("torn snapshot" in line for line in diagnostics))

    def test_a_collector_failure_sets_only_its_own_error(self) -> None:
        application, _, _, diagnostics, _ = self._application(
            home="/home/a",
            started=11.0,
            clock=1000.0,
            notifier="notifier-a",
            harnesses=(
                self._spec("broken", collect_error=RuntimeError("broken store")),
                self._spec("healthy"),
            ),
        )

        data = application.collect(show_all=True)

        broken, healthy = data["harnesses"]
        self.assertTrue(broken["discovered"])
        self.assertEqual("RuntimeError: broken store", broken["error"])
        self.assertIsNone(healthy["error"])
        # The failure is reported through the injected sink, never printed.
        self.assertEqual(["[broken] collector error: RuntimeError: broken store"], diagnostics)
        # The surviving harness still contributes its sessions.
        self.assertEqual(["healthy"], [s["harness"] for s in data["sessions"]])


class LauncherContractTest(unittest.TestCase):
    """server.py is the stable entry point and owns nothing else."""

    def test_the_launcher_is_only_a_call_into_the_cli(self) -> None:
        # This file is what users and every harness manifest point at, so its
        # shape is a contract: one import, one call, no re-exports.
        source = SERVER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom | ast.Import)]
        self.assertEqual(1, len(imports), "the launcher imports more than the CLI")
        only = imports[0]
        assert isinstance(only, ast.ImportFrom)
        self.assertEqual("compass_runtime.cli", only.module)
        self.assertEqual(["main"], [alias.name for alias in only.names])
        # No definitions and no assignments that could re-export a symbol,
        # anywhere in the tree rather than only at the top level: `if True:` with
        # a collector nested under it would pass a tree.body-only check.
        banned = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Assign
        offenders = [type(n).__name__ for n in ast.walk(tree) if isinstance(n, banned)]
        self.assertEqual([], offenders, "the launcher defines or assigns something")

    def test_running_the_launcher_calls_the_cli_exactly_once(self) -> None:
        # runpy executes the real file under __main__, which is the only way to
        # prove the `if __name__` guard wires through to cli.main and that the
        # exit code is the one main returned.
        calls: list[object] = []

        def fake_main(*args: object, **kwargs: object) -> int:
            calls.append((args, kwargs))
            return 7

        with (
            mock.patch.object(cli, "main", fake_main),
            self.assertRaises(SystemExit) as caught,
        ):
            runpy.run_path(str(SERVER_PATH), run_name="__main__")

        self.assertEqual(7, caught.exception.code)
        self.assertEqual(1, len(calls))

    def test_importing_the_runtime_opens_no_store_socket_or_subprocess(self) -> None:
        # Import must be inert: --diagnose, --status and --stop all assemble a
        # runtime first, and a module that scanned a store or bound a port at
        # import time would make those unusable exactly when they are needed.
        probe = (
            "import importlib, pkgutil, socket, sqlite3, subprocess, sys\n"
            # The root arrives as argv, never interpolated into this source: a
            # Windows path's backslashes would be read as escape sequences.
            "sys.path.insert(0, sys.argv[1])\n"
            "import compass_runtime\n"
            "def boom(*a, **k):\n"
            "    raise AssertionError('side effect at import')\n"
            "socket.socket.bind = boom\n"
            "socket.socket.connect = boom\n"
            "subprocess.Popen.__init__ = boom\n"
            "sqlite3.connect = boom\n"
            "names = [m.name for m in pkgutil.walk_packages(\n"
            "    compass_runtime.__path__, 'compass_runtime.')]\n"
            "for name in names:\n"
            "    importlib.import_module(name)\n"
            "assert len(names) >= 20, names\n"
            "print('OK', len(names))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe, str(SERVER_PATH.parent)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("OK", result.stdout)

    def test_every_runtime_module_resolves_inside_the_skill_directory(self) -> None:
        # A copied plugin has no repository around it. Walking the package and
        # checking each module's __file__ proves nothing resolved back to a
        # checkout, and it inspects every module rather than a maintained list.
        probe = (
            "import importlib, pkgutil, sys\n"
            "from pathlib import Path\n"
            # Same rule as the probe above: the root is argv, not source.
            "root = Path(sys.argv[1]).resolve()\n"
            "sys.path.insert(0, str(root))\n"
            "import compass_runtime\n"
            "from compass_runtime.web import page\n"
            "names = [m.name for m in pkgutil.walk_packages(\n"
            "    compass_runtime.__path__, 'compass_runtime.')]\n"
            # is_relative_to, not a string prefix: Windows differs from POSIX in
            # separator and in drive-letter case, and both would defeat a prefix.
            "for name in names:\n"
            "    mod = importlib.import_module(name)\n"
            "    assert mod.__file__, name\n"
            "    resolved = Path(mod.__file__).resolve()\n"
            "    assert resolved.is_relative_to(root), (name, str(resolved))\n"
            "for asset in ('react.html', 'react.integrity.json', 'react-licenses.txt',\n"
            "              *(name for name, _slot in page.FONT_ASSETS)):\n"
            "    found = page.asset_path(asset).resolve()\n"
            "    assert found.is_relative_to(root), (asset, str(found))\n"
            "print('OK', len(names))\n"
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
        }
        env["PYTHONNOUSERSITE"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", probe, str(SERVER_PATH.parent)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            # An unrelated working directory: nothing may resolve via ".".
            cwd=tempfile.gettempdir(),
            env=env,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("OK", result.stdout)


class HarnessRegistryTest(RuntimeTestCase):
    """The registry is ten collector modules and nothing else."""

    def test_the_registry_order_is_pinned(self) -> None:
        # Registry order is the collection order AND the order /api/data lists
        # harnesses in, which is the order the page renders its harness chips.
        # Mutation-checked: moving a row silently reordered the chips and passed
        # the whole suite.
        self.assertEqual(
            [
                "claude",
                "codex",
                "pi",
                "gemini",
                "antigravity",
                "copilot",
                "opencode",
                "cursor",
                "goose",
                "droid",
            ],
            [spec.key for spec in REGISTRY],
        )

    def test_no_registry_callback_resolves_into_the_launcher(self) -> None:
        # Every callback resolves to a collector module, with no exception.
        # Claude's used to be one: the registry wrapped it to bind a popup
        # notifier, and that wrapper resolved to aggregate. DRC-4192 moved the
        # popup decision to `Application`, so the wrapper is gone.
        for spec in REGISTRY:
            with self.subTest(harness=spec.key):
                for role, fn in (("discover", spec.discover), ("collect", spec.collect)):
                    module = getattr(fn, "__module__", "")
                    self.assertNotEqual(
                        "compass_runtime.cli",
                        module,
                        f"{spec.key}.{role} is defined in the launcher",
                    )
                    self.assertTrue(
                        module.startswith("compass_runtime.collectors."),
                        f"{spec.key}.{role} resolves to {module!r}",
                    )
        # Every callback is the module attribute itself, not a copy.
        self.assertIs(
            codex_collector.collect,
            next(s.collect for s in REGISTRY if s.key == "codex"),
        )
        self.assertIs(
            claude_collector.collect,
            next(s.collect for s in REGISTRY if s.key == "claude"),
        )

    def test_the_registry_row_notifies_through_the_applications_own_notifier(self) -> None:
        # The popup comes out of the callable the application was built with, not
        # a module global. Mutation-checked in its earlier form: handing the
        # collector a silent notifier passed the whole suite, because every other
        # popup test patches notify_mac underneath the binding and so cannot tell
        # which callable was actually used.
        now = 1_700_000_000.0
        prefix = "abcdef12"
        fired: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projects" / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / f"{prefix}-0000-0000-0000-000000000000.jsonl"
            transcript.write_text(json.dumps({"type": "user", "uuid": "u"}) + "\n")
            # Quiet, so the standing hook decides the state rather than activity.
            os.utime(transcript, (now - 300, now - 300))
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
            ):
                config, state = runtime()
                with state.hook_lock:
                    state.hook_notifications[prefix] = {"ts": now, "message": "permission"}
                spec = next(s for s in aggregate.default_harnesses() if s.key == "claude")
                application = aggregate.Application(
                    config,
                    state,
                    (spec,),
                    native_notifier=lambda _platform: "osascript",
                    popup_notifier=lambda title, message: fired.append((title, message)),
                    diagnostic_sink=lambda _line: None,
                    clock=lambda: now,
                )
                collection = application.collect(show_all=True)

        self.assertEqual(["needs_input"], [s["state"] for s in collection["sessions"]])
        self.assertEqual(1, len(fired), "the application's notifier was not the one used")
        self.assertIn("permission", fired[0][1])
        # The title too, not only the body. The label is resolved from the
        # registry, so a wrong lookup would raise a truthful-looking popup naming
        # the wrong harness, and the body assertion above cannot see that.
        self.assertEqual("Claude is waiting on you", fired[0][0])

    def test_a_harness_label_resolves_only_through_the_registry(self) -> None:
        # The popup title for an ask goes through this, and an ask's `harness` is
        # agent-authored text bounded only at `ask_option_cap_chars` — the
        # shipped stdio server sends the literal "unknown" for every client but
        # Claude Code. So "" and never the key echoed back: the page's session-row
        # fallback IS the key, which is right there (a row's harness comes from a
        # collector and is a registry key by construction) and would title the
        # common case here "unknown is asking you".
        application = aggregate.Application(
            *make_runtime(),
            aggregate.default_harnesses(),
            native_notifier=lambda _platform: "",
            popup_notifier=lambda _title, _message: None,
            diagnostic_sink=lambda _line: None,
        )
        self.assertEqual("Claude", application.harness_label("claude"))
        self.assertEqual("Antigravity", application.harness_label("antigravity"))
        for key in ("unknown", "", "claude ", "x" * 120):
            with self.subTest(key=key):
                self.assertEqual("", application.harness_label(key))

    def test_the_registry_keys_and_labels_match_the_runtime_default(self) -> None:
        # Nothing downstream may rewrite the registry the runtime declares.
        runtime_registry = aggregate.default_harnesses()
        self.assertEqual(
            [(spec.key, spec.label) for spec in runtime_registry],
            [(spec.key, spec.label) for spec in REGISTRY],
        )


class PublishedTextSweepTest(unittest.TestCase):
    """Every hand-built row field reaches `records.redact_secrets`.

    The cross-harness `test_no_harness_publishes_a_credential_out_of_a_prompt`
    covers the fields the fixtures happen to fill. It passed while
    `state_detail` and `subagents[].name` published a key, because no fixture
    routes the prompt into either. This asserts the sweep's list directly.
    """

    # A real prefix and a run of one letter, which is the only kind of
    # credential value this repository may hold.
    FAKE: ClassVar[str] = "sk-ant-api03-" + "A" * 95
    MARKER: ClassVar[str] = "sk-ant-…REDACTED"

    def test_the_state_detail_line_carries_no_credential(self) -> None:
        # The measured leak: an in-progress task's `activeForm` is copied into
        # `state_detail` by the collector BEFORE the sweep runs, so redacting
        # the task and not the line published the key twice over — once on the
        # card and once in notification text, which can leave the page through
        # the native notifier.
        row: Any = {
            "state_detail": f"{self.FAKE}…",
            "tasks": [{"subject": self.FAKE, "activeForm": self.FAKE, "status": "in_progress"}],
        }
        aggregate._redact_published_text([row])
        self.assertNotIn("A" * 20, json.dumps(row))
        self.assertIn(self.MARKER, row["state_detail"])

    def test_a_subagent_name_carries_no_credential(self) -> None:
        # On opencode this is the child session's own TITLE, which is the same
        # string the sweep redacts when that session is a parent row.
        row: Any = {"subagents": [{"name": f"reviewing {self.FAKE}", "model": None}]}
        aggregate._redact_published_text([row])
        self.assertNotIn("A" * 20, json.dumps(row))
        self.assertIn(self.MARKER, row["subagents"][0]["name"])

    def test_a_subagent_parent_carries_no_credential(self) -> None:
        # DRC-4344 added `parent` beside `name` and did not add it to the sweep
        # table, so the same untrusted `agentName` came back redacted in one key
        # and raw in the other. That is the third time a field on this element
        # was left out on the second reading; the docstring above names the
        # first two. It uses this class's own fixture rather than a new
        # credential-shaped literal.
        row: Any = {
            "subagents": [{"name": f"reviewing {self.FAKE}", "parent": f"lead {self.FAKE}"}]
        }
        aggregate._redact_published_text([row])
        self.assertNotIn("A" * 20, json.dumps(row))
        self.assertIn(self.MARKER, row["subagents"][0]["parent"])

    def test_a_long_subagent_name_is_swept_before_it_is_bounded(self) -> None:
        # The element bounds both untrusted strings at 70 characters. Slicing
        # first published up to 70 characters of key body with no marker on it:
        # the tail the cut removed is what the shape matches on, so a run
        # straddling the bound stopped matching and went out raw. `redact_clip`
        # owns the order, and the collector calls it for both keys.
        # Falsified by: restoring `(name or "subagent")[:70]` and
        # `parent[:70]` in `published_agent`, which drops the marker from both
        # values below and leaves `sk-ant-api03-AAAA…` on the wire.
        #
        # Both offsets, because they fail differently and only the second one
        # states the defect in full: at lead 60 the slice cut the run short
        # enough that the shape stopped matching and the KEY PREFIX went out
        # unmarked, while at lead 1 the whole value fits inside the bound only
        # after the marker replaces it -- the slice published a 56-character
        # run of key BODY, measured. One case reads as a cosmetic truncation;
        # the pair reads as the leak it was.
        for lead in ("x", "a" * 60):
            element = claude_collector.published_agent(
                f"{lead}{self.FAKE}",
                model=None,
                started_at=None,
                active=True,
                parent=f"{lead}{self.FAKE}",
            )
            for key in ("name", "parent"):
                with self.subTest(lead=len(lead), key=key):
                    self.assertIn(self.MARKER, element[key])
                    self.assertNotIn("A" * 20, element[key])
            # And the bound still holds: `redact_clip` may overrun only far
            # enough to finish a marker the cut landed inside.
            with self.subTest(lead=len(lead), bound=True):
                self.assertLessEqual(len(element["name"]), 70 + len("…REDACTED"))

    # `model` is the one string on the element published through
    # `records.safe_text` and bounded at `MODEL_CAP_CHARS` by every collector, so
    # it does not reach the raw-text table. Excusing it by name rather than by
    # omission is the point: a key that is neither swept nor listed here fails
    # the check below, which is what `parent` needed and did not get.
    SAFE_TEXTED_ELEMENT_KEYS: ClassVar[frozenset[str]] = frozenset({"model"})

    # Every argument shape the collector actually builds this element with: an
    # own agent or a live child, a retained one, a grandchild naming its
    # teammate, and a pending member. One tuple was not enough — a key whose
    # value is conditionally a string (`None if active else "…"`) is invisible
    # on the arm the probe does not walk, and the inactive arm is most of the
    # roster.
    ELEMENT_ARGUMENTS: ClassVar[tuple[dict[str, Any], ...]] = (
        {"name": "n", "model": "m", "started_at": 1.0, "active": True, "parent": None},
        {"name": "n", "model": None, "started_at": None, "active": False, "parent": None},
        {"name": "n", "model": None, "started_at": 1.0, "active": True, "parent": "p"},
        {"name": "n", "model": None, "started_at": 1.0, "active": None, "parent": "p"},
    )

    def test_every_published_subagent_string_is_swept_or_named_as_safe(self) -> None:
        # Asserted against the element the collector actually builds, not a
        # fixture, so a future string key has to be classified before it ships.
        strings: set[str] = set()
        for arguments in self.ELEMENT_ARGUMENTS:
            element = claude_collector.published_agent(
                arguments["name"],
                model=arguments["model"],
                started_at=arguments["started_at"],
                active=arguments["active"],
                parent=arguments["parent"],
            )
            strings |= {key for key, value in element.items() if isinstance(value, str)}
        swept = set(dict(aggregate._RAW_NESTED_TEXT)["subagents"])
        unaccounted = strings - swept - self.SAFE_TEXTED_ELEMENT_KEYS
        self.assertEqual(
            set(),
            unaccounted,
            "a published subagent string must be swept or named as already safe",
        )
        # And the excuse cannot be used to quietly drop a swept field.
        self.assertFalse(swept & self.SAFE_TEXTED_ELEMENT_KEYS)

    def test_the_instruction_line_on_an_assembled_row_carries_no_credential(self) -> None:
        # The one branch of the sweep no fixture reaches: only Claude and Codex
        # publish a line 2, and neither builds it by hand — `records.safe_text`
        # already covers both. That is exactly why it needs asserting here. A
        # collector that starts writing one is covered without being asked, and
        # this is the assertion that says so.
        row: Any = {"instruction": {"label": "asked", "text": f"deploy with {self.FAKE}"}}
        aggregate._redact_published_text([row])
        self.assertNotIn("A" * 20, json.dumps(row))
        self.assertIn(self.MARKER, row["instruction"]["text"])

    def test_a_malformed_row_does_not_stop_the_sweep(self) -> None:
        # Collectors are a failure boundary, so the sweep has to survive a row
        # whose lists hold something other than dicts.
        row: Any = {"tasks": ["not a task", None], "subagents": [42], "title": self.FAKE}
        aggregate._redact_published_text([row])
        self.assertIn(self.MARKER, row["title"])


class RuntimeImportGraphTest(unittest.TestCase):
    """Every runtime dependency is reviewed in the task that introduces it."""

    EXPECTED: ClassVar[dict[str, set[str]]] = {
        "compass_runtime": set(),
        # `events` arrived with the overlay patch. `aggregate` applies overlays to
        # the rows it just collected and stays below `observation`, which owns the
        # ledger: the coordinator is reached through the `OverlaySource` protocol
        # declared here, so the dependency does not invert.
        # `dismissals` arrived with the handled control. `aggregate` is the one
        # place that can subtract a cleared row before `summary` is counted, so
        # this edge is what keeps every published total honest; `dismissals` is a
        # leaf beside `records`, so it stays inward.
        # `notifications` arrived with DRC-4192, and it is the same ownership
        # decision `dismissals` is: the popup gate has to read a row's FINAL
        # state, which only exists after `_apply_overlays`, and only aggregate
        # holds that. The alternative was one caller per collector, which is the
        # arrangement that left nine harnesses notifying nobody. `notifications`
        # imports no module that imports aggregate, so this stays inward.
        # `records` arrived with the credential filter (DRC-4267). `safe_text`
        # redacts every string that passes through it, and the hand-built row
        # fields do not: the collectors slice `title`, `last_prompt`,
        # `state_detail` and a subagent name straight out of the transcript.
        # Aggregate is the one place that holds every row from every harness
        # before it is published, so the sweep lives there rather than in ten
        # collectors and whichever one is added next. `records` is a leaf, so
        # this stays inward.
        "compass_runtime.aggregate": {
            # Each row's small summary state; no blocks and no transcript read.
            "compass_runtime.summary_store",
            # The summary grant on the board and each row's `summary.job` metadata.
            "compass_runtime.summary_jobs",
            "compass_runtime.reading_policy",
            # The served page's build, so an open tab can tell it is stale
            # (regressions major 1, ui5).
            "compass_runtime.web",
            # Attaches each row's recognised copied corrections (DRC-4678).
            "compass_runtime.copied_corrections",
            # Publishes who reads each harness's sessions (DRC-4650).
            "compass_runtime.reading_route",
            "compass_runtime.tripwires",
            "compass_runtime.annotations",
            "compass_runtime.collectors",
            "compass_runtime.config",
            "compass_runtime.deliveries",
            "compass_runtime.departures",
            "compass_runtime.dismissals",
            "compass_runtime.ends",
            "compass_runtime.events",
            "compass_runtime.git_status",
            "compass_runtime.io",
            "compass_runtime.notifications",
            "compass_runtime.observer",
            "compass_runtime.quota",
            "compass_runtime.reach",
            "compass_runtime.reading",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.snapshot",
            "compass_runtime.state",
            "compass_runtime.unasked",
        },
        # Not a leaf: it re-reads a Claude Code transcript and recomputes fact
        # ids through `project_context`, as `direction_text` does, rather than
        # editing that module, which the abstention qualification freezes
        # (DRC-4678), and renders each message as `transcripts` renders a row's
        # prompt fields, to place those fields on the message they quote. Only
        # `aggregate`, `http_api` and `cli` reach it.
        # Pure composition: the copy route's cap and harnesses, and the reading's rules.
        "compass_runtime.correction": {
            "compass_runtime.copied_corrections",
            "compass_runtime.reading",
        },
        "compass_runtime.copied_corrections": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.observer",
            "compass_runtime.project_context",
            "compass_runtime.reading",
            "compass_runtime.records",
            "compass_runtime.state",
            "compass_runtime.transcripts",
        },
        # A leaf over the same four as `dismissals`, for the same reason: the
        # lane writes it, the application publishes it and a review surface
        # reads it, and none of those could depend on it if it depended on any
        # of them.
        "compass_runtime.departures": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
        },
        # A leaf over the same three, for DRC-4547: `observation` writes it
        # through on the event that sets the end mark and `aggregate` reads it
        # back onto a cold row, and those two are joined only by the
        # `OverlaySource` protocol. A store either of them depended on would
        # give the pair a second, real edge.
        "compass_runtime.ends": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
        },
        # An orchestrator rather than a leaf, and the reason it is its own
        # module: it reaches the producer, the evidence, the baseline, the
        # record and the raise, and `aggregate` imports neither of the last two
        # halves. Keeping it here is what stops the application growing an edge
        # to `project_context` for one feature.
        "compass_runtime.unasked": {
            "compass_runtime.annotations",
            "compass_runtime.config",
            "compass_runtime.departures",
            "compass_runtime.io",
            "compass_runtime.notifications",
            "compass_runtime.project_context",
            "compass_runtime.reading",
            # The Allow binding a press reads, asked before each send, so the
            # lane never sends where a press would ask again (consent F5, ui5).
            "compass_runtime.reading_policy",
            "compass_runtime.reading_route",
            "compass_runtime.state",
        },
        # The CLI is the assembly point, so it may import any runtime module.
        "compass_runtime.cli": {
            # `--forget` deletes the summary store.
            "compass_runtime.summary_store",
            # Startup-only development admission and inert fixture notifiers.
            "compass_runtime.frontend_dev",
            "compass_runtime.deliveries",
            "compass_runtime.reading_policy",
            # `--forget` deletes the copied-correction digests (DRC-4678).
            "compass_runtime.copied_corrections",
            "compass_runtime.aggregate",
            # `--forget` sweeps the discard records this store keeps
            # (DRC-4565): a record that Compass deleted something is the
            # machine's memory of an act it observed, so the command reaches
            # it by name the way it reaches history and the ends.
            "compass_runtime.annotations",
            "compass_runtime.config",
            "compass_runtime.diagnostics",
            "compass_runtime.ends",
            "compass_runtime.history",
            "compass_runtime.http_api",
            "compass_runtime.interaction_prototype",
            "compass_runtime.io",
            "compass_runtime.lifecycle",
            "compass_runtime.notifications",
            "compass_runtime.observation",
            "compass_runtime.state",
            "compass_runtime.unasked",
            "compass_runtime.web",
        },
        # Outstanding asks and their one-slot answer mailboxes. Imports no
        # runtime module, for the reason `stream` does not: that is what lets
        # `state` own the registry while `http_api` and `aggregate` serve from it
        # without a cycle. The consequence is that it cannot reach
        # `records.safe_text`, so the HTTP ingress bounds the text instead.
        "compass_runtime.asks": set(),
        "compass_runtime.collectors": set(),
        # `sessions` arrived with the event envelope: an event timestamp passes
        # through the same plausibility filter as every store timestamp, so a
        # hook with a skewed clock cannot invent activity that a store read
        # could not. `records` is here for one function, `iso_epoch`: the rule
        # that an offset-less ISO stamp means UTC has to be the same rule the
        # collectors apply, and it stopped being that when two of the four
        # readers grew their own copy. `records` is a leaf, so this stays inward
        # and the module stays pure.
        "compass_runtime.irreversible": set(),
        "compass_runtime.events": {
            "compass_runtime.irreversible",
            "compass_runtime.config",
            "compass_runtime.records",
            "compass_runtime.sessions",
        },
        "compass_runtime.diagnostics": {
            "compass_runtime.tripwires",
            "compass_runtime.aggregate",
            "compass_runtime.config",
            "compass_runtime.io",
        },
        # `records` arrived with the redact-then-slice fix. Every collector that
        # bounds a prompt with a slice has to redact BEFORE it, or the sweep in
        # `aggregate` is handed a shape whose tail has already fallen off and no
        # longer matches — which is what published a clipped `@` out of a URL
        # credential. `records.redact_clip` is the one place that ordering
        # lives, so the two collectors that had no reason to import `records`
        # now do. It is a leaf, so both edges stay inward.
        "compass_runtime.collectors.claude": {
            "compass_runtime.project_context",
            "compass_runtime.transcripts",
            "compass_runtime.claude_data",
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.notifications",
            "compass_runtime.quota",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.spacedock",
            "compass_runtime.state",
            "compass_runtime.turns",
        },
        # `records` and `config` arrived with the AIU usage tile: the store
        # timestamps need SQL-shaped parsing, and the session-store database
        # sits at the store root rather than under a globbed subdirectory.
        "compass_runtime.collectors.copilot": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            "compass_runtime.transcripts",
            "compass_runtime.turns",
        },
        # `quota` arrived with the Cursor usage provider: Cursor keeps no
        # allowance on disk and pushes nothing in, so the collector reads back
        # what the fetch thread cached, exactly as Claude's does.
        # `records` is on this list because the collector reads a model name out
        # of a chat blob and bounds it through `records.safe_text` before it is
        # published, exactly as the Antigravity collector does with its own.
        "compass_runtime.collectors.cursor": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.quota",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
        },
        # `records` for the same reason `collectors.claude` has it: the title
        # and the prompt are bounded here, and the bound has to run after the
        # filter rather than before it.
        "compass_runtime.collectors.droid": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            "compass_runtime.transcripts",
            "compass_runtime.turns",
        },
        # Antigravity reads protobuf metadata and CLI logs, never transcripts;
        # the legacy Gemini pass reads JSONL transcripts and never the store
        # helpers Antigravity needs. Splitting them apart split their imports too.
        # `quota` arrived with the status-line usage provider: Antigravity's
        # quota is pushed in and cached there, so the collector reads it back
        # rather than parsing anything of its own.
        "compass_runtime.collectors.antigravity": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.quota",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            # The title fallback reads the newest typed direction (DRC-4689).
            "compass_runtime.transcripts",
            "compass_runtime.turns",
        },
        "compass_runtime.collectors.gemini": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            "compass_runtime.transcripts",
            "compass_runtime.turns",
        },
        "compass_runtime.collectors.goose": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            "compass_runtime.turns",
        },
        "compass_runtime.collectors.opencode": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            "compass_runtime.turns",
        },
        "compass_runtime.collectors.pi": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            # `spacedock` arrived with the Pi first-officer strip. Pi writes no
            # `agentSetting`, so the collector classifies off the boot envelope the
            # shared parsers already read, the same inward edge Claude's has.
            "compass_runtime.spacedock",
            "compass_runtime.state",
            "compass_runtime.transcripts",
            "compass_runtime.turns",
        },
        # `dismissals` is here because a gate the reader cleared must raise no
        # popup, and the popup policy is this module's. The alternative was for
        # the collector to decide and hand the answer in, which would put half of
        # one rule in a file that owns none of it.
        # `deliveries` joins for the same shape of reason as `dismissals`: what
        # became of a raise is decided where the raise is made, and handing the
        # outcome back to a caller to store would put half of one rule in a file
        # that owns none of it.
        "compass_runtime.notifications": {
            "compass_runtime.claude_data",
            "compass_runtime.config",
            "compass_runtime.deliveries",
            "compass_runtime.dismissals",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.state",
        },
        # The store: `config` for its path and its caps, `records` for the
        # untrusted-input discipline, `io` for the diagnostic sink, `state` for
        # the lock and this process's copy. It imports nothing above itself, which
        # is what lets aggregate, notifications and http_api all consult it.
        # The delivery record, a leaf on the same three as `dismissals` minus
        # `state`: it holds no in-process copy, because the read is deliberately
        # later than the write and a cache would answer from a process that may
        # not be the one that wrote it.
        "compass_runtime.deliveries": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
        },
        "compass_runtime.dismissals": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.state",
        },
        # `annotations` is `dismissals`' shape over the reader's own words rather
        # than over a mark, so it is a leaf on the same four and nothing else.
        # The one behavioural difference is the absent watermark, which costs no
        # edge: see that module's docstring for why an annotation does not lapse.
        # `reading` for the shape of a stored assessment and the closed
        # vocabularies that validate one. The arrow runs this way because the
        # shape belongs with the producer, and it stays a DAG: `reading`
        # imports neither this module nor `state`.
        "compass_runtime.annotations": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.reading",
            "compass_runtime.records",
            "compass_runtime.state",
        },
        # The observer analyzer: a read-only bystander that derives goal +
        # stage + block from a session transcript head and its workflow entity
        # dir. `spacedock` provides the read-only entity-dir frontmatter reader;
        # `transcripts` provides the first-line metadata reader the path
        # resolver uses. Both are lower-level modules that do not import back.
        # A leaf. It reads the reader's words and the observed facts the caller
        # hands it, and calls one sandboxed subprocess through `observer` --
        # deliberately through it rather than beside it, so a second model lane
        # cannot drift from the first one's flags.
        # Off-machine nudge delivery: reaches the operator away from the desk.
        "compass_runtime.reach": {
            "compass_runtime.config",
            "compass_runtime.sessions",
            "compass_runtime.state",
        },
        # The durable permission and budget: config names its store, io owns
        # optional SQLite loading, and the runner says whether Compass is
        # stopping. It reaches no session or model producer.
        "compass_runtime.reading_policy": {
            "compass_runtime.config",
            "compass_runtime.io",
            # Whether Compass is stopping, so a call it cannot send is not charged.
            "compass_runtime.supervise",
        },
        "compass_runtime.reading": {
            "compass_runtime.config",
            "compass_runtime.observer",
            "compass_runtime.reading_policy",
            "compass_runtime.records",
            "compass_runtime.supervise",
        },
        # The drift levels (DEC-26) read the producer's closed vocabulary: its
        # result sentences, `why` tokens and outcome-line names, spelt once
        # there. `live_estimate` imports it (DRC-4696); DRC-4695 will too.
        "compass_runtime.levels": {
            "compass_runtime.reading",
        },
        # The live estimate (DRC-4696) replays `project_context`'s own tally and
        # counts later directions by Steer back's rule, with no model.
        "compass_runtime.live_estimate": {
            "compass_runtime.config",
            "compass_runtime.correction",
            "compass_runtime.levels",
            "compass_runtime.project_context",
        },
        # A reading job's thread (DRC-4686): it writes the outcome through the
        # store and reads the job registry beside the slot in `reading`. The
        # application it runs over is a protocol, so it never imports upward.
        "compass_runtime.reading_jobs": {
            "compass_runtime.annotations",
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.reading",
            "compass_runtime.reading_policy",
            "compass_runtime.state",
            # Whether the runner is shut, so a stop records `interrupted`.
            "compass_runtime.supervise",
        },
        # The supervised runner every model call uses: a leaf on purpose, so
        # the kill guard it holds depends on nothing in the runtime.
        "compass_runtime.supervise": set(),
        # Who reads a session: each provider's gate, then its CLI on PATH. It
        # validates the model floor in `config`, reaches ids in `observer` and never
        # a producer, and uses credential shapes in `records` so no key names a host.
        "compass_runtime.reading_route": {
            "compass_runtime.config",
            "compass_runtime.annotations",
            "compass_runtime.observer",
            "compass_runtime.records",
        },
        "compass_runtime.observer": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.reading_policy",
            "compass_runtime.records",
            "compass_runtime.spacedock",
            "compass_runtime.state",
            "compass_runtime.supervise",
            "compass_runtime.transcripts",
        },
        # The quota fetch: the whole outbound network surface, kept below the
        # collectors so the one provider that fetches shares nothing with the
        # eight that read disk.
        "compass_runtime.quota": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
        },
        # `records` for `safe_text`: the workflow README's `title` is published
        # as the goal line, the one piece of project-authored text on the
        # surface, and it goes through the same bounding and control-character
        # stripping every other untrusted string does. `records` is a leaf, so
        # this is not a layering break.
        "compass_runtime.tripwires": {
            "compass_runtime.config",
            "compass_runtime.state",
            "compass_runtime.deliveries",
        },
        "compass_runtime.spacedock": {
            "compass_runtime.config",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
        },
        # `sessions` is a pure leaf inside this package, so depending on it is
        # not a layering break: the transcript reader needs `MODEL_CAP_CHARS` to
        # bound a model string at the one door that string comes through.
        "compass_runtime.claude_data": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            "compass_runtime.transcripts",
        },
        "compass_runtime.collectors.codex": {
            "compass_runtime.spacedock",
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
            "compass_runtime.transcripts",
            "compass_runtime.turns",
        },
        # Immutable development identity is typed by the stdlib-only leaf.
        "compass_runtime.config": {"compass_runtime.frontend_dev"},
        "compass_runtime.frontend_dev": set(),
        # `observation` is here for typing only: the server carries the
        # coordinator so `serve` can start it, and the ingress route reaches it
        # through that attribute rather than through a module global. `events`
        # arrived with that route, which reads the registered-harness set to
        # decide whether `/api/events/<harness>` exists at all.
        # `asks` and `records` arrived together with the ask lane, and for one
        # reason: `asks` imports nothing, so it cannot bound the untrusted
        # question and option text it stores. The register route builds the
        # `PendingAsk` and is therefore the one place that bounding can happen.
        "compass_runtime.http_api": {
            # Deterministic grouping belongs only to the focused context answer.
            "compass_runtime.session_outline",
            # Stored summaries on the focused answer, and `POST /api/summary/delete`.
            "compass_runtime.summary_store",
            # Summary consent, start, cancel and delete routes, and the job on the focused answer.
            "compass_runtime.summary_jobs",
            # The summary start route reads the source page the job summarizes.
            "compass_runtime.session_source",
            # Each message's fixed number on the record pages and the focused context (DRC-4897).
            "compass_runtime.entry_numbers",
            "compass_runtime.record_pages",
            # The immutable admitted identity selects stricter dev authority.
            "compass_runtime.frontend_dev",
            "compass_runtime.reading_policy",
            # `POST /api/correction/copied`, and the `copied` mark on facts (DRC-4678).
            "compass_runtime.copied_corrections",
            # `POST /api/correction`, Steer back's correction (DRC-4681).
            "compass_runtime.correction",
            # The focused project context's live drift estimate (DRC-4696).
            "compass_runtime.live_estimate",
            # And its analysis-derived level, recomputed from the stored reading (DRC-4695).
            "compass_runtime.levels",
            # Resolves the one provider a press may reach (DRC-4650).
            "compass_runtime.reading_route",
            "compass_runtime.tripwires",
            "compass_runtime.annotations",
            "compass_runtime.aggregate",
            "compass_runtime.asks",
            # The Intent log's route serves sessions that have left the board,
            # so it reads the departure store directly rather than through the
            # payload. `departures` is a leaf, so this stays inward.
            "compass_runtime.departures",
            "compass_runtime.dismissals",
            "compass_runtime.events",
            "compass_runtime.interaction_prototype",
            "compass_runtime.io",
            "compass_runtime.notifications",
            "compass_runtime.observation",
            "compass_runtime.observer",
            "compass_runtime.project_context",
            "compass_runtime.quota",
            "compass_runtime.reading",
            # A press starts a reading job and answers with it (DRC-4686).
            "compass_runtime.reading_jobs",
            "compass_runtime.records",
            "compass_runtime.snapshot",
            "compass_runtime.stream",
        },
        # Above aggregate, events and probe, and the module that starts the
        # runtime's standing threads (a reading job's thread is `reading_jobs`'). Nothing imports it except the assembly point and the
        # server that carries it.
        "compass_runtime.observation": {
            "compass_runtime.irreversible",
            "compass_runtime.aggregate",
            "compass_runtime.config",
            "compass_runtime.ends",
            "compass_runtime.events",
            "compass_runtime.focus",
            "compass_runtime.git_status",
            "compass_runtime.io",
            "compass_runtime.probe",
        },
        "compass_runtime.lifecycle": {
            "compass_runtime.config",
            "compass_runtime.http_api",
            "compass_runtime.interaction_prototype",
            "compass_runtime.io",
            # Serving records what a stopped dashboard left spent, and shutdown
            # kills every supervised group (DRC-4686, Q2 and Q5).
            "compass_runtime.reading_jobs",
            "compass_runtime.summary_jobs",
            "compass_runtime.supervise",
        },
        # The read-only terminal substrate uses only the standard library. Its
        # CLI, lifecycle and HTTP integrations stay above it.
        "compass_runtime.interaction_prototype": set(),
        "compass_runtime.io": {
            "compass_runtime.config",
            "compass_runtime.state",
        },
        # Read-only project composition sits above the bounded observer,
        # Spacedock, and record readers. The HTTP route is its only caller.
        "compass_runtime.project_context": {
            "compass_runtime.claude_data",
            # The focused session's message index, for the fixed position of each check and file.
            "compass_runtime.entry_numbers",
            # Exact parent-source binding shares the canonical collector-key normalizer.
            "compass_runtime.events",
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.observer",
            # The goal notice names the Codex destination the reading route resolves.
            "compass_runtime.reading_route",
            "compass_runtime.record_pages",
            "compass_runtime.records",
            "compass_runtime.semantic_history",
            "compass_runtime.sessions",
            "compass_runtime.spacedock",
            "compass_runtime.state",
            "compass_runtime.transcripts",
        },
        # The message index, a small cache keyed by transcript. It reads messages through the record pages'
        # own reader, imported locally because that module imports project context, which imports this one.
        "compass_runtime.entry_numbers": {
            "compass_runtime.config",
            "compass_runtime.record_pages",
            "compass_runtime.state",
        },
        # Project context shares the stateless chunk walker through a local import;
        # pages still reach its fact builders, without an import-time cycle.
        "compass_runtime.record_pages": {
            "compass_runtime.config",
            "compass_runtime.project_context",
        },
        # Forward evidence shares the admitted message ids and tool classifier, retaining no cache.
        # It opens transcripts with the existing no-follow open, following links where the
        # observer's direction harnesses say the transcript read does. `records` decides which
        # person-turn text the harness relayed, so it is admitted as relayed, not as the person's.
        "compass_runtime.session_source": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.observer",
            "compass_runtime.project_context",
            "compass_runtime.record_pages",
            "compass_runtime.records",
        },
        # The summary store persists the producer's frozen result and compares it with a fresh
        # source read; it resolves the focused transcript itself and holds no model seam.
        "compass_runtime.summary_store": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.observer",
            "compass_runtime.records",
            "compass_runtime.session_source",
            "compass_runtime.session_summary",
            "compass_runtime.state",
        },
        # Summary jobs run the producer part by part under reading_policy's grant and ledger,
        # reuse the reading lane's process supervision, and write through the summary store.
        "compass_runtime.summary_jobs": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.observer",
            "compass_runtime.reading_jobs",
            "compass_runtime.reading_policy",
            "compass_runtime.reading_route",
            "compass_runtime.session_source",
            "compass_runtime.session_summary",
            "compass_runtime.state",
            "compass_runtime.summary_store",
            "compass_runtime.supervise",
        },
        # Grouping resolves one transcript and keeps only built outlines in the state leaf. It
        # calls the producer's pure plan for the focused plan, never its model seam.
        "compass_runtime.session_outline": {
            "compass_runtime.config",
            "compass_runtime.observer",
            "compass_runtime.session_source",
            "compass_runtime.session_summary",
            "compass_runtime.state",
        },
        # The summary producer is a pure function of source facts and a model seam:
        # no store, thread or subprocess. Policy is imported only for a guarded refusal.
        "compass_runtime.session_summary": {
            "compass_runtime.config",
            "compass_runtime.records",
            "compass_runtime.session_source",
            "compass_runtime.reading_policy",
        },
        # Semantic history is a pure reducer over bounded records and process
        # state. Project composition owns the higher-level joins.
        "compass_runtime.semantic_history": {
            "compass_runtime.config",
            "compass_runtime.records",
            "compass_runtime.state",
        },
        # The coarse store probe: stat only, no globbing and no reads. Imports
        # config for typing alone, which is why it sits at the bottom layer with
        # sessions and state rather than beside the collectors.
        # The end-of-session git probe. A leaf on purpose: it imports no runtime
        # module, holds no state and takes no lock, which is what lets the
        # coordinator call it from a thread of its own without ordering concerns.
        # The focus command. A leaf for `git_status`'s reason and with the same
        # consequence: the coordinator runs it from a request thread with no
        # ordering to think about, and nothing it does can reach back into state.
        "compass_runtime.focus": set(),
        "compass_runtime.git_status": set(),
        # `history` imports `config` and `io` (for the shared owner-only write
        # helper; DRC-4345), which is narrower than `dismissals` beside it
        # (that one reaches `records` and `state`).
        "compass_runtime.history": {
            "compass_runtime.records",
            "compass_runtime.config",
            "compass_runtime.io",
        },
        "compass_runtime.probe": {"compass_runtime.config"},
        "compass_runtime.records": set(),
        "compass_runtime.sessions": {"compass_runtime.config"},
        # The published snapshot is a passive container: it holds bytes and a
        # revision and takes a lock. It imports no runtime module, which is what
        # lets both aggregate and the HTTP layer depend on it without a cycle.
        "compass_runtime.snapshot": set(),
        # Connected SSE clients and their one-slot mailboxes. Imports no runtime
        # module, which is what lets state own a registry without a cycle.
        "compass_runtime.stream": set(),
        "compass_runtime.state": {
            "compass_runtime.asks",
            "compass_runtime.config",
            "compass_runtime.snapshot",
            "compass_runtime.stream",
        },
        "compass_runtime.transcripts": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
        },
        "compass_runtime.turns": {
            "compass_runtime.config",
            "compass_runtime.io",
            "compass_runtime.records",
            "compass_runtime.sessions",
            "compass_runtime.state",
        },
        "compass_runtime.web": set(),
        "compass_runtime.web.page": set(),
    }

    @staticmethod
    def _module_name(path: Path) -> str:
        relative = path.relative_to(SKILL_DIR).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _relative_target(self, module: str, node: ast.ImportFrom, *, is_package: bool) -> str:
        package = module.split(".") if is_package else module.split(".")[:-1]
        if node.level > len(package):
            self.fail(f"{module} has a relative import that climbs above compass_runtime")
        base = package[: len(package) - node.level + 1]
        if not base or base[0] != RUNTIME_PREFIX:
            self.fail(f"{module} has a relative import that climbs above compass_runtime")
        return ".".join([*base, *([node.module] if node.module else [])])

    def _run_graph_fixture(
        self,
        source: str,
        expected_dependencies: set[str],
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp)
            runtime_dir = skill_dir / "compass_runtime"
            runtime_dir.mkdir()
            module_path = runtime_dir / "fixture.py"
            module_path.write_text(source, encoding="utf-8")
            expected = {"compass_runtime.fixture": expected_dependencies}
            with (
                mock.patch.multiple(
                    sys.modules[__name__],
                    SKILL_DIR=skill_dir,
                    RUNTIME_DIR=runtime_dir,
                ),
                mock.patch.object(self, "EXPECTED", expected),
            ):
                self.test_runtime_import_graph_matches_the_reviewed_allowlist()

    def test_importfrom_namespace_aliases_are_rejected(self) -> None:
        forbidden = (
            "from compass.skills.compass import compass_runtime\n",
            "from compass.skills.compass import compass_runtime as runtime\n",
            "from compass.skills.compass import compass_runtime, server\n",
        )
        for source in forbidden:
            with (
                self.subTest(source=source),
                self.assertRaisesRegex(AssertionError, "namespace-qualified runtime import"),
            ):
                self._run_graph_fixture(source, set())

    def test_canonical_import_forms_remain_legal(self) -> None:
        source = """
import compass_runtime.web.page
from compass_runtime.web import page
from . import page as sibling_page
"""
        self._run_graph_fixture(
            source,
            {
                "compass_runtime.page",
                "compass_runtime.web",
                "compass_runtime.web.page",
            },
        )

    def test_relative_import_cannot_climb_above_runtime(self) -> None:
        with self.assertRaisesRegex(AssertionError, "climbs above compass_runtime"):
            self._run_graph_fixture("from .. import server\n", set())

    def test_runtime_import_graph_matches_the_reviewed_allowlist(self) -> None:
        actual: dict[str, set[str]] = {}
        for path in sorted(RUNTIME_DIR.rglob("*.py")):
            module = self._module_name(path)
            dependencies: set[str] = set()
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(
                            alias.name == FORBIDDEN_RUNTIME_PREFIX
                            or alias.name.startswith(f"{FORBIDDEN_RUNTIME_PREFIX}."),
                            f"{module} uses namespace-qualified runtime import {alias.name}",
                        )
                        if alias.name == RUNTIME_PREFIX or alias.name.startswith(
                            f"{RUNTIME_PREFIX}."
                        ):
                            dependencies.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    imported = (
                        self._relative_target(
                            module,
                            node,
                            is_package=path.name == "__init__.py",
                        )
                        if node.level
                        else (node.module or "")
                    )
                    candidates = [
                        imported,
                        *(f"{imported}.{alias.name}" for alias in node.names),
                    ]
                    for candidate in candidates:
                        self.assertFalse(
                            candidate == FORBIDDEN_RUNTIME_PREFIX
                            or candidate.startswith(f"{FORBIDDEN_RUNTIME_PREFIX}."),
                            f"{module} uses namespace-qualified runtime import {candidate}",
                        )
                    if imported == RUNTIME_PREFIX or imported.startswith(f"{RUNTIME_PREFIX}."):
                        if imported == RUNTIME_PREFIX or node.module is None:
                            dependencies.update(f"{imported}.{alias.name}" for alias in node.names)
                        else:
                            dependencies.add(imported)
            dependencies.discard(module)
            actual[module] = dependencies
        self.assertEqual(self.EXPECTED, actual)

    def test_moved_symbols_exist_only_on_their_runtime_owner(self) -> None:
        launcher_source = SERVER_PATH.read_text(encoding="utf-8")
        io_symbols = (
            "glob_stores",
            "read_tail",
            "reverse_lines",
            "sqlite_ro_uri",
            "record_store_error",
        )
        record_symbols = (
            "safe_text",
            "parse_ts",
            "as_dict",
            "record_fingerprint",
            "gemini_records",
            "_turn_signal",
        )
        session_symbols = (
            "encoded_home_prefix",
            "HOME_PREFIX",
            "project_label",
            "project_from_cwd",
            "fmt_duration",
            "age",
            "is_fresh",
            "newest_plausible",
            "dedupe_sessions",
            "assign_display_ids",
            "base_session",
            "rate_from",
            "working_detail",
        )
        notification_symbols = (
            "normalized_notification_type",
            "notification_disposition",
            "native_notifier",
            "notify_mac",
            "hook_generation",
            "current_hook",
            "maybe_popup",
            "IDLE_NOTIFICATION_TYPES",
            "CLEARING_NOTIFICATION_TYPES",
        )
        spacedock_symbols = (
            "sd_frontmatter_lines",
            "sd_read_workflow",
            "sd_read_entities",
            "sd_session_workflows",
            "SPACEDOCK_FO",
            "SD_STAGE_RE",
        )
        lifecycle_symbols = (
            "tcp_port",
            "compass_home",
            "state_path",
            "log_path",
            "ensure_compass_home",
            "write_state",
            "read_state",
            "remove_state",
            "probe_port",
            "port_released",
            "await_release",
            "instance_status",
            "render_status",
            "stop_instance",
            "fork_daemon",
            "daemon_redirect_stdio",
            "daemon_announce",
            "await_daemon",
            "forwarded_args",
            "spawn_detached",
            "log_tail",
            "await_spawned",
        )
        http_symbols = (
            "normalize_host",
            "reuse_address_allowed",
            "bind_error_message",
            "LoopbackHTTPServer",
            "Handler",
        )
        diagnostics_symbols = (
            "store_primaries",
            "candidate_report",
            "render_diagnosis",
        )
        claude_collector_symbols = (
            "load_tasks",
            "claude_agent_transcripts",
            "load_claude_subagents",
            "collect_claude",
            "claude_spacedock",
            "CLAUDE_SUBAGENT_GLOBS",
        )
        claude_data_symbols = (
            "claude_session_title",
            "claude_last_user_event",
            "analyze_transcript",
            "claude_session_cwd",
            "claude_hook_user_event",
            "claude_agent_identity",
            "claude_agent_setting",
            "claude_prefix_is_agent",
            "INPUT_TOOLS",
        )
        transcript_symbols = (
            "first_line_meta",
            "codex_meta",
            "gemini_meta",
            "copilot_meta",
            "droid_meta",
            "pi_meta",
            "shorten_paths",
            "clip",
            "prompt_title",
            "analyze_codex_transcript",
            "analyze_gemini_transcript",
            "analyze_copilot_events",
            "analyze_droid_transcript",
        )
        turn_symbols = (
            "_apply_turn_record",
            "_latest_turn_context",
            "scan_turns",
            "turns_from_events",
            "turn_progress",
        )
        for symbol in (
            *io_symbols,
            *record_symbols,
            *session_symbols,
            *transcript_symbols,
            *turn_symbols,
            *claude_data_symbols,
            *notification_symbols,
            *claude_collector_symbols,
            *diagnostics_symbols,
            *http_symbols,
            *lifecycle_symbols,
            *spacedock_symbols,
        ):
            with self.subTest(symbol=symbol):
                # The launcher has no namespace to check, so the contract is on
                # its source: none of these may reappear there.
                self.assertNotIn(symbol, launcher_source)
        self.assertTrue(all(hasattr(runtime_io, symbol) for symbol in io_symbols))
        self.assertTrue(all(hasattr(records, symbol) for symbol in record_symbols))
        # HOME_PREFIX is deliberately gone rather than relocated: project_label
        # derives the encoded prefix from config.home on every call.
        self.assertTrue(
            all(
                hasattr(runtime_sessions, symbol)
                for symbol in session_symbols
                if symbol != "HOME_PREFIX"
            )
        )
        self.assertFalse(hasattr(runtime_sessions, "HOME_PREFIX"))
        self.assertTrue(all(hasattr(runtime_transcripts, symbol) for symbol in transcript_symbols))
        self.assertIs(sys.modules["compass_runtime.io"], runtime_io)
        self.assertIs(sys.modules["compass_runtime.records"], records)
        self.assertIs(sys.modules["compass_runtime.sessions"], runtime_sessions)
        self.assertTrue(all(hasattr(runtime_turns, s) for s in turn_symbols))
        self.assertIs(sys.modules["compass_runtime.transcripts"], runtime_transcripts)
        self.assertIs(sys.modules["compass_runtime.turns"], runtime_turns)

    def test_importing_lower_runtime_layers_performs_no_external_operation(self) -> None:
        # Reading ambient state or opening a file, socket, browser, log, or child
        # during import would make copied-plugin discovery and diagnostics unsafe.
        script = """
import builtins
import compass_runtime
import dataclasses
import io
import json
import logging
import ntpath
import os
import pathlib
import posixpath
import socket
import subprocess
import threading
import time
import types
import typing
import webbrowser

def forbidden(*_args, **_kwargs):
    raise AssertionError("runtime import performed an external operation")

class ForbiddenEnvironment:
    get = forbidden
    __getitem__ = forbidden
    __contains__ = forbidden
    __iter__ = forbidden
    items = forbidden
    keys = forbidden
    values = forbidden

builtins.open = forbidden
io.open = forbidden
os.environ = ForbiddenEnvironment()
os.access = forbidden
os.listdir = forbidden
os.lstat = forbidden
os.scandir = forbidden
os.stat = forbidden
os.walk = forbidden
pathlib.Path.exists = forbidden
pathlib.Path.is_dir = forbidden
pathlib.Path.is_file = forbidden
pathlib.Path.iterdir = forbidden
pathlib.Path.open = forbidden
pathlib.Path.read_bytes = forbidden
pathlib.Path.read_text = forbidden
socket.socket = forbidden
subprocess.Popen = forbidden
subprocess.run = forbidden
time.monotonic = forbidden
time.perf_counter = forbidden
time.time = forbidden
webbrowser.open = forbidden
logging.Logger._log = forbidden

import compass_runtime.config
import compass_runtime.io
import compass_runtime.records
import compass_runtime.sessions
import compass_runtime.state
import compass_runtime.transcripts
import compass_runtime.turns
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=SKILL_DIR,
            env={**os.environ, "PYTHONPATH": str(SKILL_DIR)},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


class CollectorAgreementTest(RuntimeTestCase):
    def test_claude_and_codex_agree_on_one_directory(self) -> None:
        # DRC-3963. The reported case: one worktree, two harnesses, two
        # different project strings — Claude showed the whole encoded path
        # ("git-spacedock-research-spacedock-subspace") while Codex showed a
        # bare basename. Same directory has to read the same on every row.
        now = time.time()
        home = "/Users/cl"
        cwd = f"{home}/git/spacedock-research/spacedock/subspace"
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        encoded = runtime_sessions.encoded_home_prefix(cwd)  # Claude's projects/ dir name
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "projects" / encoded
            project_dir.mkdir(parents=True)
            (project_dir / "aaaa1111-0000-0000-0000-000000000000.jsonl").write_text(
                json.dumps(
                    {
                        "type": "user",
                        "timestamp": iso,
                        "cwd": cwd,
                        "message": {"role": "user", "content": "hi"},
                    }
                )
                + "\n"
            )
            rollout = Path(tmp) / "codex" / "2026" / "07" / "28"
            rollout.mkdir(parents=True)
            sid = "019f855d-aaaa-7000-8000-000000000001"
            (rollout / f"rollout-2026-07-28T09-36-23-{sid}.jsonl").write_text(
                json.dumps(
                    {
                        "timestamp": iso,
                        "type": "session_meta",
                        "payload": {"id": sid, "cwd": cwd, "source": "exec"},
                    }
                )
                + "\n"
            )
            with (
                store_patch(PROJECTS_DIR=str(Path(tmp) / "projects")),
                store_patch(TASKS_DIR=str(Path(tmp) / "no-tasks")),
                store_patch(CODEX_SESSIONS_DIR=str(Path(tmp) / "codex")),
                mock.patch.dict(
                    STORE_OVERRIDES,
                    {
                        "claude.projects": [str(Path(tmp) / "projects")],
                        "claude.tasks": [str(Path(tmp) / "no-tasks")],
                        "codex.sessions": [str(Path(tmp) / "codex")],
                    },
                ),
                config_patch(home=home),
            ):
                claude = collect_claude(now, 24, False)
                config, state = runtime()
                codex = codex_collector.collect(config, state, now, 24, False)

        self.assertEqual(1, len(claude))
        self.assertEqual(1, len(codex))
        self.assertEqual("spacedock/subspace", claude[0]["project"])
        self.assertEqual(claude[0]["project"], codex[0]["project"])


class HarnessContractTest(HarnessContractTestCase):
    """One behavioural contract, asserted against every harness.

    The rest of the suite grew out of specific bugs, so it covers Claude deeply
    and the other eight thinly. This states what the dashboard must do and
    checks all of them, on whichever OS the runner is.
    """

    def test_pi_store_is_registered_as_a_harness(self) -> None:
        # Removing Pi from the registry would make a valid store invisible.
        # One runtime package, imported by its own name. A namespace-qualified
        # copy would give every module a second identity and a second cache.
        self.assertNotIn("compass.skills.compass.compass_runtime", sys.modules)
        data = self.collect(build_pi, when=self.NOW)
        self.assertTrue(
            any(harness["key"] == "pi" for harness in data["harnesses"]),
            "Pi store must appear in the harness registry",
        )

    def test_a_fresh_store_is_discovered_and_reads_working(self) -> None:
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                data = self.collect(build, when=self.NOW)
                harness = next(h for h in data["harnesses"] if h["key"] == key)
                self.assertTrue(harness["discovered"], "store present but not discovered")
                self.assertIsNone(harness["error"])
                sessions = self.sessions_for(data, key)
                self.assertEqual(1, len(sessions), f"expected one session, got {sessions}")
                self.assertEqual("working", sessions[0]["state"])

    def test_only_a_harness_with_a_verified_resume_verb_publishes_a_resume_token(
        self,
    ) -> None:
        # Two harnesses have a re-entry verb read off the installed CLI's own help
        # rather than off documentation: Claude Code 2.1.261 `--resume <session-id>`
        # and Codex 0.153.4 `resume <SESSION_ID>`. Every other row publishes None,
        # which is what keeps the page from offering a guessed command. When one of
        # the other eight earns a verb, this set is the place that says so.
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                data = self.collect(build, when=self.NOW)
                row = self.sessions_for(data, key)[0]
                token = row["resume_id"]
                if key in {"claude", "codex"}:
                    self.assertIsNotNone(token)
                    self.assertEqual(token, runtime_sessions.resume_token(token))
                else:
                    self.assertIsNone(token)

    def test_no_harness_publishes_a_credential_out_of_a_prompt(self) -> None:
        # DRC-4267. Every row here is built from what the operator typed, and on
        # the machine this was found on that text held seven live Anthropic
        # keys. The fake is a real prefix and a run of one letter, which is the
        # only kind of credential value this repository may hold.
        #
        # Asserted over the serialized row rather than over `title`, because the
        # same prompt reaches `last_prompt` and the instruction line as well, and
        # the requirement is about the DOM rather than about one field.
        fake = "sk-ant-api03-" + "A" * 95
        self.TITLE = f"deploy with {fake} and report back"
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                data = self.collect(build, when=self.NOW)
                rows = self.sessions_for(data, key)
                self.assertEqual(1, len(rows))
                # `project` is dropped, and only `project`: three fixtures spell
                # the working directory out of the same string they use for the
                # prompt, so it carries the fake here in a way no real store
                # does. A path is not prompt-derived text and is not in scope.
                row = {k: v for k, v in rows[0].items() if k != "project"}
                serialized = json.dumps(row, ensure_ascii=False)
                self.assertNotIn("A" * 20, serialized)
                published = (row["title"] or "") + (row["last_prompt"] or "")
                if published:
                    self.assertIn("sk-ant-\u2026REDACTED", serialized)

    def test_no_harness_publishes_a_credential_the_cap_cut_in_half(self) -> None:
        # DRC-4269. The ordering, driven through the collectors rather than
        # asserted on `safe_text` alone — which is what let the defect ship. Ten
        # collectors sliced `title` and `last_prompt` out of the transcript and
        # the sweep in `aggregate` ran afterwards, so a shape the slice had
        # already cut no longer matched and the head of it published unmarked.
        # The lead puts the 140-character cap nine characters into the key's
        # body, which is below the sixteen the shape needs. A slice that ran
        # first would leave a run the filter can no longer see, which is the
        # whole mechanism.
        fake = "sk-ant-api03-" + "A" * 95
        self.TITLE = "x" * 105 + " deploy with " + fake
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                data = self.collect(build, when=self.NOW)
                rows = self.sessions_for(data, key)
                self.assertEqual(1, len(rows))
                row = {k: v for k, v in rows[0].items() if k != "project"}
                self.assertNotIn("A" * 8, json.dumps(row, ensure_ascii=False))

    def test_a_stale_store_reads_idle_but_still_appears(self) -> None:
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                data = self.collect(build, when=self.NOW - 7200)
                sessions = self.sessions_for(data, key)
                self.assertEqual(1, len(sessions))
                self.assertEqual("idle", sessions[0]["state"])

    def test_an_absent_store_is_not_discovered_and_is_not_an_error(self) -> None:
        # "No harness here" and "harness broken" must never look the same.
        data = self.collect(lambda *_a: {}, when=self.NOW)
        for harness in data["harnesses"]:
            with self.subTest(harness=harness["key"]):
                self.assertFalse(harness["discovered"])
                self.assertIsNone(harness["error"])
        self.assertEqual([], data["sessions"])

    def test_a_future_dated_store_does_not_read_working(self) -> None:
        # A clock-skewed store must not invent activity, on any harness.
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                data = self.collect(build, when=self.NOW + 86_400)
                for session in self.sessions_for(data, key):
                    self.assertNotEqual("working", session["state"])
                    reports_rate = next(spec.reports_rate for spec in REGISTRY if spec.key == key)
                    expected_rate = 0 if reports_rate else None
                    self.assertEqual(expected_rate, session["rate_per_min"])

    def test_one_session_in_two_candidate_roots_yields_one_row(self) -> None:
        # De-duplication has to be wired into collect(), not merely available:
        # scanning every candidate root is what makes a migrated store appear
        # twice, and only the full pass can collapse it.
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty"
            empty.mkdir()
            first, second = Path(tmp) / "one", Path(tmp) / "two"
            build_opencode(first, self.NOW, self.SID, self.TITLE)
            build_opencode(second, self.NOW - 60, self.SID, self.TITLE)
            patches: dict[str, str] = {n: str(empty / n) for n in STORE_CONSTANTS}
            patches["OPENCODE_DATA"] = str(first)
            with contextlib.ExitStack() as stack:
                stack.enter_context(store_patch(**patches))
                # primary == candidates[0], so the whole list is scanned. This
                # override carries BOTH roots, which store_patch cannot express.
                stack.enter_context(
                    mock.patch.dict(
                        STORE_OVERRIDES,
                        {"opencode.data": str(first)},
                    )
                )
                stack.enter_context(mock.patch.object(notifications, "notify_mac"))
                stack.enter_context(mock.patch.object(time, "time", lambda: self.NOW))
                data = collect(24, show_all=True)

        opencode = [s for s in data["sessions"] if s["harness"] == "opencode"]
        self.assertEqual(1, len(opencode), f"duplicate rows: {opencode}")
        self.assertEqual(self.NOW, opencode[0]["last_activity"], "kept the staler copy")
        self.assertEqual(1, data["summary"]["active_sessions"])

    def test_a_corrupt_store_never_breaks_the_collector(self) -> None:
        # Every store file replaced with junk: the harness may vanish or report
        # an error, but collection must complete and the others must survive.
        for key, build in HARNESSES:
            with (
                self.subTest(harness=key, fixture=build.__name__),
                tempfile.TemporaryDirectory() as tmp,
            ):
                empty = Path(tmp) / "empty"
                empty.mkdir()
                patches: dict[str, str] = {n: str(empty / n) for n in STORE_CONSTANTS}
                store = Path(tmp) / "store"
                patches.update(build(store, self.NOW, self.SID, self.TITLE))
                for path in store.rglob("*"):
                    if path.is_file():
                        path.write_bytes(b"\x00\xff not a valid store at all \xfe")
                with contextlib.ExitStack() as stack:
                    stack.enter_context(store_patch(**patches))
                    stack.enter_context(mock.patch.object(notifications, "notify_mac"))
                    data = collect(24, show_all=True)  # must not raise
                self.assertIsInstance(data["sessions"], list)

    def test_every_session_reports_a_model_as_a_reading_or_as_unread(self) -> None:
        # Three states, not two. A measured model and "no model reported" are
        # different facts and the wire format has to keep them apart, so the key
        # is always present and None is the only spelling of "not read". An
        # empty string is the collapse this guards: it is not a reading, and the
        # page draws it as a blank where the dash belongs.
        #
        # The two branches are asserted, not one. `if model is None: continue`
        # alone reads as a ten-harness contract and pins whichever fixtures
        # happen to carry a value — every other harness falls out of the loop
        # before the shape assertions, so a fixture that quietly stopped
        # publishing a model would move this test from "checked" to "skipped"
        # without changing its result. So: the unread branch asserts the value is
        # literally None (not "", not 0, not False — those are falsy spellings of
        # "not read" that the page would draw as a blank), the read branch runs
        # the shape assertions for every harness that does publish, and the tally
        # below proves the read branch ran at all and that all ten fixtures were
        # visited.
        measured: dict[str, str] = {}
        unread: list[str] = []
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                data = self.collect(build, when=self.NOW)
                sessions = self.sessions_for(data, key)
                self.assertTrue(sessions, "the fixture published no session to check")
                for session in sessions:
                    self.assertIn("model", session, "the model slot must never vanish")
                    model = session["model"]
                    if not model:
                        self.assertIsNone(model, "None is the only spelling of 'not read'")
                        unread.append(key)
                        continue
                    self.assertIsInstance(model, str)
                    self.assertTrue(model.strip(), "an empty string is not a reading")
                    self.assertLessEqual(len(model), runtime_sessions.MODEL_CAP_CHARS)
                    measured[key] = model
        self.assertEqual(
            {key for key, _ in HARNESSES},
            set(measured) | set(unread),
            "a harness landed in neither branch: its fixture produced no row, or its"
            " model failed a check above and never reached the tally",
        )
        # At least one fixture must reach the read branch, or the shape assertions
        # above are dead code dressed as a cross-harness contract. Cursor and
        # OpenCode carry a model end to end today; the assertion is a floor, not
        # a pin, so a fixture gaining a model strengthens it instead of failing.
        self.assertIn(
            "cursor",
            measured,
            "no fixture exercised the model shape — the read branch never ran",
        )

    def test_a_cursor_store_reports_the_model_its_own_blobs_name(self) -> None:
        # The one shared fixture that carries a measurable model end to end, and
        # the only assertion that proves the chain. Cursor reaches its model
        # through meta -> latestRootBlobId -> root blob -> child message, and a
        # break at any hop returns None — which the contract above accepts as an
        # honest "not read", so without this the whole read could rot unseen.
        data = self.collect(build_cursor, when=self.NOW)
        self.assertEqual(CURSOR_MODEL, self.sessions_for(data, "cursor")[0]["model"])

    def test_an_opencode_store_reports_the_model_on_its_session_row(self) -> None:
        # DRC-4436. OpenCode 1.18.20 keeps the model as a JSON object in
        # `session.model` — `{"id", "providerID", "variant"}` — so the published
        # value is that object's `id` and not the column verbatim. The contract
        # above would accept a raw `'{"id": ...}'` string as an honest reading,
        # which is what this pins against.
        data = self.collect(build_opencode, when=self.NOW)
        self.assertEqual(OPENCODE_MODEL, self.sessions_for(data, "opencode")[0]["model"])


class SubagentElementContractTest(unittest.TestCase):
    """A published subagent is an object carrying a name and a model.

    Claude, Codex, Copilot, Antigravity, Goose and OpenCode each pin this in
    their own module. Gemini's producer had no assertion anywhere in the tree,
    so its conversion to the grown element shipped untested; this is that
    assertion, kept here rather than beside Gemini's other tests because the
    shape is a cross-harness contract and not a Gemini behaviour.
    """

    NOW = 1_700_000_000.0
    PARENT = "abcdef12-3456-7890-abcd-ef1234567890"

    def test_a_gemini_subagent_is_a_name_and_an_unread_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chats = Path(tmp) / "proj" / "chats"
            (chats / records.alnum(self.PARENT)).mkdir(parents=True)
            main = chats / f"session-{self.PARENT}.jsonl"
            main.write_text(
                json.dumps({"sessionId": self.PARENT, "kind": "main", "directories": ["/w/proj"]})
                + "\n"
                + json.dumps({"type": "user", "timestamp": "2023-11-14T22:13:20Z", "content": "hi"})
                + "\n",
                encoding="utf-8",
            )
            os.utime(main, (self.NOW, self.NOW))
            child = chats / records.alnum(self.PARENT) / "9f3c1a55-child.jsonl"
            child.write_text(
                json.dumps({"sessionId": "9f3c1a55", "kind": "subagent"}) + "\n",
                encoding="utf-8",
            )
            os.utime(child, (self.NOW, self.NOW))
            with store_patch(GEMINI_TMP=str(tmp)):
                config, state = runtime()
                rows = gemini_collector.collect(config, state, self.NOW, 24, True)

        # Nobody has looked for where Gemini records a model, so None here says
        # "not read" — never that the child runs on no model, and never a value
        # borrowed from the parent card.
        self.assertEqual(
            [
                {
                    "name": "subagent 9f3c1a55",
                    "model": None,
                    "started_at": None,
                    "active": None,
                    "parent": None,
                }
            ],
            rows[0]["subagents"],
        )


class HostilePathContractTest(unittest.TestCase):
    """Store paths users really have. Every character here is legal on macOS,
    Linux and Windows; the ones Windows forbids (<>:"/\\|?*) are excluded so the
    same contract runs on all three."""

    NOW = 1_700_000_000.0
    SID = "abcdef12-3456-7890-abcd-ef1234567890"
    HOSTILE = (
        "A [Contractor]",  # glob character class
        "100% pure",  # SQLite URI percent-decoding
        "Ünïcode Café",  # non-ASCII
        "a#b",  # URI fragment
        "with space",
        "it's & more",
        "plus+equals=sign",
        "semi;colon,comma",
        "dollar$at@tilde~",
        "brace{s}paren(s)",
    )

    def test_every_harness_survives_a_hostile_store_path(self) -> None:
        for component in self.HOSTILE:
            for key, build in HARNESSES:
                with self.subTest(path=component, harness=key, fixture=build.__name__):
                    with tempfile.TemporaryDirectory() as tmp:
                        empty = Path(tmp) / "empty"
                        empty.mkdir()
                        patches: dict[str, str] = {n: str(empty / n) for n in STORE_CONSTANTS}
                        patches.update(
                            build(Path(tmp) / component / "store", self.NOW, self.SID, "T")
                        )
                        with contextlib.ExitStack() as stack:
                            stack.enter_context(store_patch(**patches))
                            stack.enter_context(mock.patch.object(notifications, "notify_mac"))
                            stack.enter_context(mock.patch.object(time, "time", lambda: self.NOW))
                            data = collect(24, show_all=True)
                    found = [s for s in data["sessions"] if s["harness"] == key]
                    self.assertEqual(1, len(found), f"{key} lost its session under {component!r}")


class DiscoveryCostContractTest(unittest.TestCase):
    """A `discover()` answers one bit and must not pay for a list to do it.

    `glob_under` and `glob_stores` materialise every match and sort it. Four
    collectors used one as a truthiness test and then `collect()` repeated the
    identical glob in the same pass, so the store was walked twice to publish
    one row. The probes exist now; this is what stops the idiom coming back in
    the next collector.
    """

    SORTING = ("glob_under", "glob_stores")

    def test_no_discover_builds_a_sorted_match_list(self) -> None:
        collectors = Path(runtime_io.__file__).parent / "collectors"
        modules = sorted(p for p in collectors.glob("*.py") if p.name != "__init__.py")
        self.assertTrue(modules, "no collector modules found")
        for path in modules:
            with self.subTest(collector=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                discover = next(
                    (
                        node
                        for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "discover"
                    ),
                    None,
                )
                if discover is None:
                    # Not every collector declares one; the registry treats a
                    # missing `discover` as "always look".
                    continue
                used = sorted(
                    {
                        node.attr
                        for node in ast.walk(discover)
                        if isinstance(node, ast.Attribute) and node.attr in self.SORTING
                    }
                )
                self.assertEqual(
                    [],
                    used,
                    f"{path.name} discover() calls {used}; use any_glob_under/any_glob_stores",
                )


class RepeatingSourceContractsTest(unittest.TestCase):
    """DRC-4203 / AC-5: Registry/coverage makes no native AGY reporting claim, and statusline hook maps no wait."""

    def test_antigravity_does_not_claim_needs_input_reporting(self) -> None:
        spec = next(h for h in aggregate.default_harnesses() if h.key == "antigravity")
        self.assertFalse(spec.reports_needs_input)

    def test_statusline_envelope_identifies_repeating_source(self) -> None:
        import statusline_hook  # noqa: PLC0415

        env = statusline_hook.envelope(
            {"session_id": "12345678-1234-5678-1234-567812345678", "agent_state": "working"}
        )
        assert env is not None
        self.assertEqual("statusline", env.get("source_instance_id"))
