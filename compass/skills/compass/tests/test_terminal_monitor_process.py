"""Competing real terminal commands and a detached holder, over a synthetic non-spending board."""

from __future__ import annotations

import dataclasses
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from compass_runtime import http_api, live_lease, monitor_store
from compass_runtime import terminal_client as client

from .support import SERVER_PATH, make_config

# Measures readiness and cooperative exit of real detached subprocesses.
REAL_TIME_TESTS = True
NATIVE = "abcdefab-1111-4111-8111-111111111111"
SID = NATIVE[:8]


class ProcessTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = temp.name
        self.env = {**os.environ, "COMPASS_HOME": self.home}
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)
        self.row: dict[str, Any] = {
            "harness": "claude",
            "sid": SID,
            "resume_id": NATIVE,
            "last_activity": time.time(),
            "ended_at": None,
        }
        self.actions: list[dict[str, Any]] = []
        self.started = time.time() + 100
        config = dataclasses.replace(make_config(), state_dir=Path(self.home))
        self.leases = live_lease.Leases(
            config, row_for=lambda *_a: self.row, inputs_for=lambda *_a: None, start_thread=False
        )
        self.addCleanup(self.leases.close)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def answer(self, data: Any) -> None:
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/api/health":
                    self.answer(
                        {
                            "ok": True,
                            "pid": os.getpid(),
                            "port": outer.server.server_port,
                            "started": outer.started,
                            "version": client.release_version(),
                        }
                    )
                else:
                    self.answer({"sessions": [outer.row]})

            def do_POST(self) -> None:
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.actions.append(payload)
                parsed = http_api._lease_request(payload, 200)
                assert parsed is not None
                self.answer(http_api._lease_answer(outer.leases, *parsed))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=self.server.serve_forever)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_port
        (Path(self.home) / ("compass-" + str(self.port) + ".json")).write_text("{}")
        self.store = monitor_store.Store(self.home, SID)
        self.addCleanup(self.cleanup_holder)

    def cleanup_holder(self) -> None:
        if self.store.running():
            self.store.write("stop", {"generation": self.store.read("run").get("generation")})
            self.until(lambda: not self.store.running())

    def until(self, predicate: Any) -> None:
        end = time.monotonic() + 10
        while not predicate() and time.monotonic() < end:
            time.sleep(0.05)
        self.assertTrue(predicate())

    def launch(self, *options: str) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [
                sys.executable,
                str(SERVER_PATH),
                "--monitor",
                *options,
                "--session",
                "claude:" + NATIVE,
            ],
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self.reap, process)
        return process

    @staticmethod
    def reap(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)

    def test_two_people_starting_at_once_share_one_sidecar_and_off_preserves_the_browser(
        self,
    ) -> None:
        self.assertTrue(self.leases.start("claude", SID, "browser")["ok"])
        first, second = self.launch(), self.launch()
        outputs = [p.communicate(timeout=20) for p in (first, second)]
        self.assertEqual([0, 0], [first.returncode, second.returncode], outputs)
        self.assertEqual(1, sum(a["action"] == "start" for a in self.actions))
        self.assertEqual(1, sum("already running" in out for out, _err in outputs))
        self.assertTrue(self.store.running())
        off = self.launch("--off")
        out, err = off.communicate(timeout=20)
        self.assertEqual(0, off.returncode, err)
        self.assertIn("stopped", out)
        self.assertFalse(self.store.running())
        self.assertTrue(client.probe(self.port))
        self.assertTrue(self.leases.state("claude", SID)["on"])
        self.assertTrue(self.leases.beat("claude", SID, "browser")["ok"])
        terminal = next(a["tab_id"] for a in self.actions if a["action"] == "start")
        self.assertFalse(self.leases.beat("claude", SID, terminal)["ok"])
        self.assertEqual(1, sum(a["action"] == "stop" for a in self.actions))
        repeat = self.launch("--off")
        self.assertIn("not running", repeat.communicate(timeout=20)[0])

    def test_a_person_with_a_same_prefix_different_full_id_cannot_stop_the_holder(self) -> None:
        start = self.launch()
        self.assertEqual(0, start.wait(timeout=20))
        wrong = subprocess.run(
            [
                sys.executable,
                str(SERVER_PATH),
                "--monitor",
                "--off",
                "--session",
                "claude:abcdefab-2222-4222-8222-222222222222",
            ],
            env=self.env,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(1, wrong.returncode)
        self.assertTrue(self.store.running())
        self.assertFalse(any(a["action"] == "stop" for a in self.actions))

    def test_a_person_s_dead_worker_releases_its_lock_for_the_next_start(self) -> None:
        # Crash a lock holder without relying on a PID from the on-disk control record.
        code = (
            "from compass_runtime import monitor_store; import sys,time; "
            "s=monitor_store.Store(sys.argv[1],sys.argv[2]); "
            "c=s.lock('life'); c.__enter__(); print('held',flush=True); time.sleep(30)"
        )
        env = {**self.env, "PYTHONPATH": str(SERVER_PATH.parent)}
        process = subprocess.Popen(
            [sys.executable, "-c", code, self.home, SID], env=env, stdout=subprocess.PIPE, text=True
        )
        self.addCleanup(self.reap, process)
        assert process.stdout is not None
        self.assertEqual("held", process.stdout.readline().strip())
        self.assertTrue(self.store.running())
        process.kill()
        process.wait(timeout=5)
        self.assertFalse(self.store.running())

    @unittest.skipIf(os.name == "nt", "Windows has no ancestor watch")
    def test_a_person_s_hard_killed_harness_leaves_no_detached_holder(self) -> None:
        # A shell symlink supplies a real executable named claude without starting a model or
        # installing harness hooks. The dashboard still publishes a live row after its death.
        executable = Path(self.home) / "claude"
        executable.symlink_to("/bin/sh")
        command = shlex.join(
            [sys.executable, str(SERVER_PATH), "--monitor", "--session", "claude:" + NATIVE]
        )
        parent = subprocess.Popen(
            [str(executable), "-c", command + "; sleep 30; :"],
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

        def cleanup() -> None:
            if parent.poll() is None:
                os.killpg(parent.pid, signal.SIGKILL)
            parent.communicate(timeout=5)

        self.addCleanup(cleanup)
        assert parent.stdout is not None
        self.assertIn("started", parent.stdout.readline())
        self.assertEqual(parent.pid, self.store.read("run")["ancestor"]["pid"])
        began = time.monotonic()
        os.killpg(parent.pid, signal.SIGKILL)
        parent.wait(timeout=5)
        self.until(lambda: not self.store.running())
        self.assertLess(time.monotonic() - began, 50)
        self.assertEqual("session-gone", self.store.read("status")["reason"])
        self.assertIsNone(self.row["ended_at"])
        self.assertTrue(client.probe(self.port))

    @unittest.skipIf(os.name == "nt", "Windows has no FIFO")
    def test_a_person_s_control_read_rejects_a_fifo_without_waiting_for_a_writer(self) -> None:
        os.mkfifo(self.store.path("status"))
        code = (
            "from compass_runtime import monitor_store; import sys; "
            "print(monitor_store.Store(sys.argv[1],sys.argv[2]).read('status'))"
        )
        result = subprocess.run(
            [sys.executable, "-c", code, self.home, SID],
            env={**self.env, "PYTHONPATH": str(SERVER_PATH.parent)},
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("{}", result.stdout.strip())
