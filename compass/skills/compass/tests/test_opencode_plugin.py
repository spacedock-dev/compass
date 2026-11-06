"""Exercise the shipped passive callback and its real loopback transport."""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from compass_runtime import events, observation

from . import fixtures, support

PLUGIN = support.SERVER_PATH.parent / "opencode_plugin.js"
SID = "ses_" + "a" * 26
OTHER = "ses_" + "a" * 25 + "b"
TOKEN = "test-capability"  # noqa: S105 — local test sentinel
NODE = shutil.which("node")
# The adapter's HTTP deadline is measured as a real node process's wall-clock lifetime.
REAL_TIME_TESTS = True
RUNNER = r"""
import {readFileSync, writeFileSync, unlinkSync} from "node:fs";
import {pathToFileURL} from "node:url";
const input = JSON.parse(readFileSync(0, "utf8"));
const module = await import(pathToFileURL(input.plugin));
const hooks = await module.CompassPlugin({});
const times = [];
for (const step of input.steps) {
  if ("state" in step) {
    if (step.state === null) { try { unlinkSync(input.state); } catch {} }
    else writeFileSync(input.state, typeof step.state === "string" ? step.state : JSON.stringify(step.state));
  }
  const start = performance.now();
  await hooks.event({event: step.event});
  times.push(performance.now() - start);
  await new Promise(resolve => setTimeout(resolve, step.delay ?? 60));
}
await new Promise(resolve => setTimeout(resolve, input.settle ?? 350));
process.stdout.write(JSON.stringify({hooks: Object.keys(hooks), times}));
"""


def native(kind: str, request: str = "req-one", sid: str = SID) -> dict[str, Any]:
    return {
        "type": kind,
        "properties": {
            "sessionID": sid,
            "id": request,
            "requestID": request,
            "reply": "once",
            "metadata": {"command": "secret-command"},
            "patterns": ["private-path"],
        },
    }


@unittest.skipUnless(NODE, "node is required to exercise the JavaScript adapter")
class OpenCodePluginTest(support.RuntimeTestCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.records: list[dict[str, Any]] = []
        records = self.records
        self.response_delay = 0.0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                records.append(
                    {
                        "path": self.path,
                        "token": self.headers.get("X-Compass-Capability"),
                        "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                    }
                )
                time.sleep(owner.response_delay)
                self.send_response(204)
                self.end_headers()

            def log_message(self, _format: str, *args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=support.poll_fast(self.server), daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port
        self.state = self.home / f"compass-{self.port}.json"
        self.state.write_text(json.dumps({"capabilities": {"opencode": TOKEN}}))

    def run_plugin(
        self,
        steps: list[dict[str, Any]],
        **options: Any,
    ) -> dict[str, Any]:
        self.assertTrue(PLUGIN.is_file(), "the per-project OpenCode adapter is not shipped")
        plugin = self.home / "plugin.mjs"
        shutil.copyfile(PLUGIN, plugin)
        payload = {"plugin": str(plugin), "state": str(self.state), "steps": steps, **options}
        runner = self.home / "runner.mjs"
        runner.write_text(RUNNER)
        started = time.monotonic()
        result = subprocess.run(
            [str(NODE), str(runner)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env={**os.environ, "COMPASS_HOME": str(self.home), "COMPASS_PORT": str(self.port)},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)
        observed: dict[str, Any] = json.loads(result.stdout)
        observed["elapsed"] = time.monotonic() - started
        return observed

    def test_a_parent_permission_wait_clears_only_after_its_last_answer(self) -> None:
        result = self.run_plugin(
            [
                {"event": native("permission.asked")},
                {"event": native("permission.asked")},
                {"event": native("permission.asked", "req-two")},
                {"event": native("permission.replied", "unknown")},
                {"event": native("session.status")},
                {"event": native("permission.replied")},
                {"event": native("permission.replied", "req-two")},
                {"event": native("permission.replied", "req-two")},
            ]
        )
        self.assertEqual(["event"], result["hooks"])
        self.assertEqual(
            ["input_requested", "input_resolved"], [r["body"]["event"] for r in self.records]
        )
        self.assertEqual({"/api/events/opencode"}, {r["path"] for r in self.records})
        for record in self.records:
            self.assertEqual(TOKEN, record["token"])
            self.assertEqual({"v", "event", "session_id"}, set(record["body"]))
            self.assertEqual(SID, record["body"]["session_id"])
        self.assertNotIn("secret-command", json.dumps(self.records))

    def test_two_whole_ids_sharing_a_prefix_reach_distinct_overlay_keys(self) -> None:
        self.run_plugin(
            [
                {"event": native("permission.asked")},
                {"event": native("permission.asked", sid=OTHER)},
                {"event": native("permission.replied")},
            ]
        )
        config = support.make_config()
        ledger = []
        for seq, record in enumerate(self.records):
            parsed = events.parse(
                "opencode", record["body"], arrival_seq=seq + 1, config=config, now=1000
            )
            self.assertIsInstance(parsed, events.Event)
            assert isinstance(parsed, events.Event)
            ledger.append(events.overlay_for(parsed, config=config))
        for sid, expected in ((SID, "working"), (OTHER, "needs_input")):
            rows = [o for o in ledger if o is not None and o.sid == sid]
            self.assertEqual(expected, events.reduce_overlays(rows, now=1000)["state"])

    def test_invalid_ids_cannot_reach_a_session(self) -> None:
        for sid in ("../" + SID, SID[:-1], SID + "a", "ses_" + "é" * 26, "ses_" + "a" * 25 + "/"):
            with self.subTest(sid=sid):
                self.assertIsNone(events.normalize_session_id("opencode", sid))

    def test_a_delayed_duplicate_ask_does_not_reopen_an_answered_request(self) -> None:
        self.run_plugin(
            [
                {"event": native("permission.asked")},
                {"event": native("permission.replied")},
                {"event": native("permission.asked")},
            ]
        )
        self.assertEqual(
            ["input_requested", "input_resolved"], [r["body"]["event"] for r in self.records]
        )

    def test_missing_invalid_or_disabled_state_sends_no_permission_content(self) -> None:
        states: tuple[Any, ...] = (
            None,
            "{broken",
            [],
            {},
            {"capabilities": {}},
            {"capabilities": {"opencode": "bad\nheader"}},
            "x" * 65537,
        )
        for state in states:
            with self.subTest(state_type=type(state).__name__):
                self.records.clear()
                self.run_plugin([{"state": state, "event": native("permission.asked")}])
                self.assertEqual([], self.records)

    def test_a_restarted_dashboard_gets_its_new_capability(self) -> None:
        self.run_plugin(
            [
                {"event": native("permission.asked")},
                {
                    "state": {"capabilities": {"opencode": "next-token"}},
                    "event": native("permission.replied"),
                },
            ]
        )
        self.assertEqual([TOKEN, "next-token"], [r["token"] for r in self.records])

    def test_a_slow_server_cannot_hold_the_permission_callback(self) -> None:
        # A healthy run ends with the runner's settle, 0.67 s plus node's startup.
        # A deadline that resolves without destroying the socket holds the process
        # for this delay plus 0.25 s, and no deadline holds it for twice the delay.
        # The delay was 1.0 s against a 1.6 s bound, which a healthy Windows run
        # crossed at 1.69 s (PR #456, run 36798591299), then 4.5 s against 3.7 s.
        # The delay costs a healthy run nothing, so it is 20 s: a 15 s bound leaves
        # a loaded runner's node startup room and sits 5 s under either defect.
        self.response_delay = 20.0
        result = self.run_plugin(
            [
                {"event": native("permission.asked"), "delay": 10},
                {"event": native("permission.replied"), "delay": 10},
            ],
            settle=650,
        )
        self.assertLess(max(result["times"]), 100)
        self.assertLess(result["elapsed"], 15.0, "HTTP deadline did not release the host socket")
        self.assertEqual(
            ["input_requested", "input_resolved"], [r["body"]["event"] for r in self.records]
        )

    def test_unrelated_or_malformed_native_events_emit_nothing(self) -> None:
        self.run_plugin(
            [
                {"event": event}
                for event in (
                    None,
                    {},
                    {"type": "permission.asked"},
                    native("permission.ask"),
                    native("session.status"),
                    native("permission.asked", sid="../../secret"),
                    native("permission.asked", request=""),
                )
            ]
        )
        self.assertEqual([], self.records)

    def test_real_http_ingress_joins_only_the_answered_collector_row(self) -> None:
        store = self.home / "store"
        store.mkdir()
        now = time.time()
        fixtures.build_opencode(store, now, SID, "First parent")
        with contextlib.closing(sqlite3.connect(store / "opencode.db")) as connection:
            connection.execute(
                "INSERT INTO session SELECT ?, parent_id, directory, ?, time_updated, time_archived, model FROM session",
                (OTHER, "Second parent"),
            )
            connection.commit()
        with support.store_patch(
            **{
                **dict.fromkeys(support.STORE_KEYS, str(self.home / "empty")),
                "OPENCODE_DATA": str(store),
            }
        ):
            app = support.build_app()
            coordinator = observation.Observation(app, diagnostic_sink=lambda _message: None)
            app.overlays = coordinator
            httpd = support.make_server(application=app, observation=coordinator)
            thread = threading.Thread(target=support.poll_fast(httpd), daemon=True)
            thread.start()
            self.addCleanup(httpd.server_close)
            self.addCleanup(httpd.shutdown)
            self.port = httpd.server_port
            self.state = self.home / f"compass-{self.port}.json"
            self.state.write_text(json.dumps({"capabilities": coordinator.capabilities()}))
            self.run_plugin(
                [
                    {"event": native("permission.asked")},
                    {"event": native("permission.asked", sid=OTHER)},
                    {"event": native("permission.replied")},
                ]
            )
            rows = {row["sid"]: row for row in app.collect(show_all=False)["sessions"]}
            self.assertEqual("working", rows[SID]["state"])
            self.assertEqual("needs_input", rows[OTHER]["state"])
            self.assertEqual("event", rows[OTHER]["acquisition"])
            self.assertIsNotNone(rows[OTHER]["blocked_since"])

    def test_a_refused_connection_cannot_throw_into_the_host(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        result = self.run_plugin([{"event": native("permission.asked")}])
        self.assertLess(max(result["times"]), 100)
        self.assertEqual([], self.records)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO control is POSIX-only")
    def test_a_state_fifo_cannot_leave_a_host_read_blocked(self) -> None:
        self.state.unlink()
        os.mkfifo(self.state)
        result = self.run_plugin([{"event": native("permission.asked")}])
        # A blocked FIFO read never ends, so the defect is the runner's 60 s
        # timeout; the healthy floor is 0.41 s plus the same node startup that
        # cost 1.02 s on Windows above. 1.6 s, then 8 s, left a loaded runner
        # too little room.
        self.assertLess(result["elapsed"], 30.0)
        self.assertEqual([], self.records)

    def test_request_overflow_never_claims_clearance_for_untracked_waits(self) -> None:
        steps = [{"event": native("permission.asked", str(i)), "delay": 0} for i in range(65)]
        steps += [{"event": native("permission.replied", str(i)), "delay": 0} for i in range(65)]
        self.run_plugin(steps)
        self.assertEqual(["input_requested"], [r["body"]["event"] for r in self.records])
