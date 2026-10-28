"""The command report boundary, independently of ordinary lifecycle hints."""

from __future__ import annotations

import contextlib
import dataclasses
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import event_hook
from compass_runtime import aggregate, cli, irreversible, lifecycle, observation, sessions

from . import support
from .test_events_ingress import FakeApplication

if TYPE_CHECKING:
    from collections.abc import Callable

SESSION = "abcdef12-3456-7890-abcd-ef1234567890"
NOW = 1_700_000_000.0
HOOK = Path(event_hook.__file__).resolve()
ROOT = HOOK.parents[3]


def native(command: Any, **changes: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "PostToolUse",
        "session_id": SESSION,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": "private-output",
        **changes,
    }


def wire(pattern: str = "git_force_push", **changes: Any) -> dict[str, Any]:
    return {
        "v": 1,
        "event": "command_shape_reported",
        "session_id": SESSION,
        "timestamp": datetime.fromtimestamp(NOW, UTC).isoformat(),
        "pattern_id": pattern,
        "tool_name": "Bash",
        **changes,
    }


POSITIVES = (
    ("git push --force private_force", "git_force_push"),
    ("git push -f private_short", "git_force_push"),
    ("git push private_remote private_ref --force-with-lease", "git_force_push"),
    ("git reset --hard", "git_hard_reset"),
    ("git reset --hard private_revision", "git_hard_reset"),
    ("psql -c 'DROP TABLE private_psql;'", "sql_drop_table"),
    ('mysql -e "drop table if exists private_mysql"', "sql_drop_table"),
    ("sqlite3 private_database 'DROP TABLE private_schema.private_table;'", "sql_drop_table"),
    ("rm -r private_r", "recursive_delete"),
    ("rm -R private_R", "recursive_delete"),
    ("rm -rf private_rf", "recursive_delete"),
    ("rm -fr private_fr", "recursive_delete"),
    ("rm -Rf private_Rf", "recursive_delete"),
    ("rm -fR private_fR", "recursive_delete"),
    ("rm -r -f -- /tmp/private_temp private_outside", "recursive_delete"),
)
NEGATIVES = (
    "",
    " ",
    "git push",
    "git push --forceful",
    "git push -vf",
    "git push --force --dry-run",
    "git push --force-with-lease=branch",
    "git -C /repo push --force",
    "git reset --hard -q",
    "git reset --hard a b",
    "rm -f private",
    "rm -rf /tmp/private",
    "rm -rf /private/tmp/private",
    "rm -rf /var/tmp/private",
    "rm -rf /tmp/../private",
    "rm -rf --",
    "rm -rf -v private",
    "git push --force; echo private",
    "git push --force && echo private",
    "git push --force\necho private",
    "git push --force $PRIVATE",
    "git push --force `private`",
    "git push --force > private",
    "git push --force | private",
    "git push --force #private",
    "git push --force private\\ name",
    "sudo git push --force",
    "env PRIVATE=1 git push --force",
    "/usr/bin/git push --force",
    "rtk proxy proxy git push --force",
    "rtk bypass bypass git push --force",
    "rtk proxy bypass git push --force",
    "rtk",
    "rtk proxy",
    "git push '--force'",
    "psql -c 'DROP TABLE private; DELETE FROM private;'",
    "psql -c 'DROP TABLE private CASCADE;'",
    "psql -c 'DROP TABLE private' extra",
    "psql -c 'DROP TABLE private",
    "psql -c 'DROP TABLE 123;'",
    'psql -c "DROP TABLE $PRIVATE;"',
    "mysql -e 'DROP TABLE private --comment;'",
    "sqlite3 -flag 'DROP TABLE private;'",
    "git push --force " + "x" * 4096,
    "git push --force " + "x " * 64,
    "git\vpush --force private",
    "git push --force private\x00",
)


class _InlineThread:
    """Deterministic lexical/socket oracle; real timing has separate process proofs."""

    def __init__(self, *, target: Callable[[], None], daemon: bool) -> None:
        assert daemon
        self.target = target

    def start(self) -> None:
        self.target()

    def join(self, timeout: float) -> None:
        assert timeout == 0.005

    def is_alive(self) -> bool:
        return False


def deterministic_driver() -> str:
    return (
        "from collections.abc import Callable; from types import SimpleNamespace\n"
        + inspect.getsource(_InlineThread)
        + "\nevent_hook.threading = SimpleNamespace(Thread=_InlineThread)\n"
        + "event_hook.time = SimpleNamespace(monotonic=lambda: 0.0)"
    )


class CommandSocketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config, state = support.make_runtime(
            state_home=self.tmp.name,
            state_dir=Path(self.tmp.name),
            annotations_enabled=False,
            dismissals_enabled=False,
            history_enabled=False,
            event_burst_max=1000,
            focus_enabled=False,
            git_probe_enabled=False,
        )
        spec = aggregate.HarnessSpec(
            "claude",
            "Claude",
            lambda *_: True,
            lambda *_: [sessions.base_session("claude", SESSION[:8], "project")],
        )
        self.app = aggregate.Application(
            self.config,
            state,
            (spec,),
            native_notifier=lambda _: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _: None,
            clock=lambda: NOW,
        )
        self.coordinator = observation.Observation(self.app, clock=lambda: NOW)
        self.app.overlays = self.coordinator
        self.received: list[dict[str, Any]] = []
        submit = self.coordinator.submit

        def capture(harness: str, payload: Any) -> str:
            result = submit(harness, payload)
            if result == "accepted" and payload.get("event") == "command_shape_reported":
                self.received.append(payload)
            return result

        patcher = patch.object(self.coordinator, "submit", capture)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = support.make_server(application=self.app, observation=self.coordinator)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.addCleanup(self.close_server)
        self.write_state(True)

    def close_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(1)

    def write_state(self, enabled: bool | None) -> None:
        data: dict[str, Any] = {"capabilities": self.coordinator.capabilities()}
        if enabled is not None:
            data["irreversible_enabled"] = enabled
        target = Path(self.tmp.name, f"compass-{self.port}.json")
        pending = target.with_suffix(".tmp")
        pending.write_text(json.dumps(data))
        pending.replace(target)

    def run_hook(
        self, payload: Any, harness: str = "claude", *, driver: str = "", timeout: float = 3
    ) -> subprocess.CompletedProcess[bytes]:
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); import event_hook\n"
            + driver
            + "\nraise SystemExit(event_hook.main(['event_hook', sys.argv[2], sys.argv[3]]))"
        )
        return subprocess.run(
            [sys.executable, "-c", code, str(HOOK.parent), harness, str(self.port)],
            input=json.dumps(payload).encode(),
            capture_output=True,
            timeout=timeout,
            env={**os.environ, "COMPASS_HOME": self.tmp.name},
            check=False,
        )

    def run_hook_inprocess(self, payload: Any, harness: str = "claude") -> tuple[int, str, str]:
        """`run_hook` with `deterministic_driver`, without starting an interpreter.

        The driver already replaces `threading` and `time` inside the child, so a
        fresh interpreter proves nothing per case that the same `main` over the
        same socket does not; what it costs is a Python start and an HTTP import
        per case, about 90ms against about 15ms (measured 2026-09-23). The tests
        below keep real subprocess cases so the shipped script is still run.
        """
        stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "stdin", stdin),
            patch.dict(os.environ, {"COMPASS_HOME": self.tmp.name}),
            patch.object(event_hook, "threading", SimpleNamespace(Thread=_InlineThread)),
            patch.object(event_hook, "time", SimpleNamespace(monotonic=lambda: 0.0)),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            code = event_hook.main(["event_hook", harness, str(self.port)])
        return code, out.getvalue(), err.getvalue()

    def post(self, payload: dict[str, Any], harness: str = "claude") -> dict[str, Any]:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/events/{harness}",
            data=json.dumps(payload).encode(),
            headers={"X-Compass-Capability": self.coordinator.capability(harness)},
        )
        with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310 — fixed loopback URL
            result: dict[str, Any] = json.loads(response.read())
            return result

    def timed_hook(
        self, driver: str, *, after_main: str = "", timeout: float | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        # 2 seconds, and the number is chosen by what it has to DISTINGUISH
        # rather than by how prompt the hook ought to be.
        #
        # The callers that must not time out inject a hang of 10 seconds or an
        # unbounded spin, so every limit under 10 seconds has identical
        # detection power and the only thing a tighter one buys is a flake. The
        # old value was 0.25 (1.0 on Windows), and that split is itself the
        # tell: it was tracking machine speed, not the property. It failed on a
        # loaded macOS runner on 2026-09-21.
        #
        # What makes a tight limit actively harmful here is that the failure is
        # **indistinguishable from the defect**. A hook that hung and a runner
        # that was busy both surface as `TimeoutExpired`, so a flake reads as a
        # regression in the one guard that would catch a real one.
        #
        # The hook's own watchdog is `MATCH_WAIT_SEC = 0.005`, and
        # `irreversible_report` says in as many words that a 5 ms join is "best
        # effort, not a hard deadline for scheduling". A test asserting a hard
        # deadline over a documented best-effort one is asserting more than the
        # code promises.
        #
        # Measured 2026-09-22 on an idle M-series desk, three samples: the value
        # the budget actually bounds, `main_to_exit_ms`, ran 23 to 37 ms. So the
        # old limit carried **6.8x** headroom over the worst sample and the new
        # one carries **54x**. A hosted runner is several times slower than this
        # desk before any parallel job load, which is the gap 6.8x does not
        # cover. The figures are from this test's own C6_PHASE diagnostics and
        # can be retaken the same way.
        #
        # The negative control goes the other way and passes its own short
        # timeout: it EXPECTS `TimeoutExpired`, so a shorter limit makes it more
        # certain rather than less.
        limit = 2.0 if timeout is None else timeout
        ready = Path(self.tmp.name, "hook-ready.json")
        phases = Path(self.tmp.name, "hook-phases.json")
        ready.unlink(missing_ok=True)
        phases.unlink(missing_ok=True)
        # Interpreter/import and diagnostic setup precede readiness. Real main, both socket
        # paths, the daemon worker and interpreter exit remain in the timed window.
        # Containment uses 250 ms; normal matching is a separate bounded measurement.
        # Prepare diagnostic storage before readiness: post-main file I/O releases
        # the GIL to the injected spin and measures work the shipped hook never does.
        code = (
            (
                "import time; child_started = time.perf_counter()\n"
                "import sys, json; from pathlib import Path\n"
                "sys.path.insert(0, sys.argv[1]); import event_hook\n"
                "event_hook._shared()\n"
            )
            + driver
            + "\n"
            + """
marks = {}
original_shape = event_hook.command_shape
original_report = event_hook.irreversible_report
original_clock = event_hook.time.monotonic
clock_reads = []
def observed_shape(command):
    marks['matcher_start'] = time.perf_counter()
    result = original_shape(command)
    marks['matcher_end'] = time.perf_counter()
    marks['lexical_result'] = result
    return result
def observed_clock():
    value = original_clock()
    clock_reads.append(value)
    return value
def observed_report(*args):
    result = original_report(*args)
    marks['report_return'] = time.perf_counter()
    marks['report_present'] = result is not None
    return result
event_hook.command_shape = observed_shape
event_hook.irreversible_report = observed_report
event_hook.time.monotonic = observed_clock
import mmap
phase_file = open(sys.argv[3], 'w+b')
phase_file.write(b'\\0' * 4096)
phase_file.flush()
phase_map = mmap.mmap(phase_file.fileno(), 4096)
ready = Path(sys.argv[4])
pending = ready.with_suffix('.tmp')
pending.write_text(json.dumps({'child_setup_ms': (time.perf_counter()-child_started)*1000}))
pending.replace(ready)
sys.stdin.buffer.peek(1)
marks['main_start'] = time.perf_counter()
status = event_hook.main(['event_hook', 'claude', sys.argv[2]])
marks['main_end'] = time.perf_counter()
"""
            + after_main
            + "\n"
            + """
marks['clock_reads'] = clock_reads
phase_bytes = json.dumps(marks).encode()
phase_map[:len(phase_bytes)] = phase_bytes
raise SystemExit(status)
"""
        )
        started = time.perf_counter()
        with subprocess.Popen(
            [sys.executable, "-c", code, str(HOOK.parent), str(self.port), str(phases), str(ready)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "COMPASS_HOME": self.tmp.name},
        ) as proc:
            try:
                while not ready.exists():
                    if proc.poll() is not None or time.perf_counter() - started > 3:
                        self.fail("hook did not reach its import/readiness boundary")
                    time.sleep(0.001)
                setup = json.loads(ready.read_text())
                call_started = time.perf_counter()
                setup["parent_startup_ms"] = (call_started - started) * 1000
                try:
                    stdout, stderr = proc.communicate(
                        json.dumps(native("git push --force")).encode(), timeout=limit
                    )
                except subprocess.TimeoutExpired as exc:
                    proc.kill()
                    exc.output, exc.stderr = proc.communicate()
                    print(
                        "C6_PHASE "
                        + json.dumps({**setup, "outcome": "timeout", "limit_ms": limit * 1000})
                    )
                    raise
                elapsed = time.perf_counter() - call_started
                marks = json.loads(phases.read_bytes().rstrip(b"\0"))
                self.last_phases = {**setup, **marks, "main_to_exit_ms": elapsed * 1000}
                self.last_phases["total_process_ms"] = (time.perf_counter() - started) * 1000
                print("C6_PHASE " + json.dumps(self.last_phases, sort_keys=True))
                self.assertLess(elapsed, limit)
                return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()

    def assert_literals_report_over_the_socket(self, harness: str, wrapper: str) -> None:
        """Every positive literal, under one harness and wrapper, reaches one fixed report.

        One method per harness and wrapper rather than one loop over all six, so
        the parallel runner can spread them: on the Windows runner each loopback
        request cost about 0.47s, and the single loop was a 42s unit on its own
        (measured 2026-09-23). The assertions are the loop's, unchanged.
        """
        for index, (command, pattern) in enumerate(POSITIVES):
            with self.subTest(harness=harness, wrapper=wrapper, command=command):
                before = len(self.received)
                # The first case per harness runs the shipped script as a real
                # process; the rest run the same `main` in-process.
                if index == 0 and not wrapper:
                    proc = self.run_hook(
                        native(wrapper + command), harness, driver=deterministic_driver()
                    )
                    outcome = (proc.returncode, proc.stdout.decode(), proc.stderr.decode())
                else:
                    outcome = self.run_hook_inprocess(native(wrapper + command), harness)
                self.assertEqual((0, "", ""), outcome)
                self.assertEqual(before + 1, len(self.received))
                report = self.received[-1]
                self.assertEqual(set(wire()), set(report))
                self.assertEqual(pattern, report["pattern_id"])
                self.assertNotIn("private", json.dumps(report))
        served = json.loads(self.app.collect_json(show_all=False)[1])
        self.assertNotIn("private", json.dumps(served["command_reports"]))
        self.assertNotIn("private", str(self.coordinator._command_reports.__dict__))

    def test_every_literal_reaches_only_fixed_reports_over_a_socket_claude(self) -> None:
        self.assert_literals_report_over_the_socket("claude", "")

    def test_every_literal_under_rtk_reaches_only_fixed_reports_claude(self) -> None:
        self.assert_literals_report_over_the_socket("claude", "rtk ")

    def test_every_literal_under_rtk_proxy_reaches_only_fixed_reports_claude(self) -> None:
        self.assert_literals_report_over_the_socket("claude", "rtk proxy ")

    def test_every_literal_under_rtk_bypass_reaches_only_fixed_reports_claude(self) -> None:
        self.assert_literals_report_over_the_socket("claude", "rtk bypass ")

    def test_every_literal_under_rtk_bypass_reaches_only_fixed_reports_codex(self) -> None:
        self.assert_literals_report_over_the_socket("codex", "rtk bypass ")

    def test_every_literal_reaches_only_fixed_reports_over_a_socket_codex(self) -> None:
        self.assert_literals_report_over_the_socket("codex", "")

    def test_every_literal_under_rtk_reaches_only_fixed_reports_codex(self) -> None:
        self.assert_literals_report_over_the_socket("codex", "rtk ")

    def test_every_literal_under_rtk_proxy_reaches_only_fixed_reports_codex(self) -> None:
        self.assert_literals_report_over_the_socket("codex", "rtk proxy ")

    def test_ambiguous_malformed_and_oversized_calls_produce_no_report(self) -> None:
        malformed: tuple[Any, ...] = (*NEGATIVES, None, 2, [], {})
        payloads = [native(command) for command in malformed]
        payloads.extend(
            [
                native("git push --force", tool_name="exec_command"),
                native("git push --force", hook_event_name="PreToolUse"),
                native("git push --force", hook_event_name="PostToolUseFailure"),
                native("git push --force", tool_input="bad"),
                native("git push --force", session_id=""),
                native("git push --force", session_id="x" * 201),
            ]
        )
        for index, payload in enumerate(payloads):
            with self.subTest(payload=payload):
                if index == 0:
                    proc = self.run_hook(payload)
                    outcome = (proc.returncode, proc.stdout.decode(), proc.stderr.decode())
                else:
                    outcome = self.run_hook_inprocess(payload)
                self.assertEqual((0, "", ""), outcome)
        self.assertEqual([], self.received)
        self.assertEqual([], self.coordinator.command_reports())
        # A canary through the same in-process path: `main` swallows every
        # exception, so a broken path would pass every negative above vacuously.
        self.run_hook_inprocess(native(POSITIVES[0][0]))
        self.assertEqual(1, len(self.received))

    def test_recorded_harness_shapes_admit_only_the_measured_after_tool_field(self) -> None:
        for harness, filename in (
            ("claude", "command-shapes-2.1.270-macos.jsonl"),
            ("codex", "command-shapes-0.154.0-macos.jsonl"),
        ):
            records = [
                json.loads(line)
                for line in (ROOT / "docs/captures" / harness / filename).read_text().splitlines()
            ]
            for record in (row for row in records if row["tool"] == "Bash"):
                self.assertEqual("str", record["input_fields"]["command"])
                payload: dict[str, Any] = dict.fromkeys(record["keys"])
                payload.update(
                    hook_event_name=record["event"], tool_name=record["tool"], session_id=SESSION
                )
                payload["tool_input"] = dict.fromkeys(record["input_fields"], "private-description")
                payload["tool_input"]["command"] = "git push --force private-replay"
                before = len(self.received)
                proc = self.run_hook(payload, harness, driver=deterministic_driver())
                self.assertEqual((0, b"", b""), (proc.returncode, proc.stdout, proc.stderr))
                self.assertEqual(before + int(record["event"] == "PostToolUse"), len(self.received))

    def test_no_events_publishes_no_enablement_and_no_reports(self) -> None:
        self.server.observation = None
        self.app.overlays = None
        lifecycle.write_state(self.config, self.port, started=NOW, capabilities=None)
        self.assertEqual(0, self.run_hook(native("git push --force")).returncode)
        self.assertEqual([], self.received)
        payload = self.app.collect(show_all=False)
        self.assertFalse(payload["irreversible_enabled"])
        self.assertNotIn("command_reports", payload)

    def test_forged_vocabulary_or_extra_private_fields_never_enter_the_ledger(self) -> None:
        for forged in (
            wire(pattern_id="private"),
            wire(tool_name="private"),
            wire(cwd="private"),
            wire(tool_input="private"),
            wire(timestamp="private"),
            wire(v=True),
            wire(pattern_id=[]),
            wire(tool_name={}),
            wire(timestamp=0),
        ):
            self.assertNotEqual("accepted", self.post(forged).get("outcome"))
        self.post(wire(), "gemini")
        self.assertEqual([], self.received)
        self.assertEqual([], self.coordinator.command_reports())

    def test_fresh_off_old_and_missing_state_never_enters_the_matcher(self) -> None:
        marker = Path(self.tmp.name, "matcher-entered")
        driver = (
            "from pathlib import Path; event_hook.irreversible_report = lambda *a: Path("
            + repr(str(marker))
            + ").write_text('entered')"
        )
        for enabled in (False, None, "missing"):
            if enabled == "missing":
                Path(self.tmp.name, f"compass-{self.port}.json").unlink()
            else:
                assert enabled is None or isinstance(enabled, bool)
                self.write_state(enabled)
            proc = self.run_hook(native("git push --force"), driver=driver)
            self.assertEqual((0, b"", b""), (proc.returncode, proc.stdout, proc.stderr))
            self.assertFalse(marker.exists())
        self.assertEqual([], self.received)
        self.assertEqual(2, self.coordinator.counters.get("event.store_changed"))

    def test_sleep_and_spin_exit_the_actual_hook_without_late_publication(self) -> None:
        drivers = [
            "import time; event_hook.command_shape = lambda _: time.sleep(10)",
            "exec('def spin(_):\\n while True: pass'); event_hook.command_shape = spin",
        ]
        for driver in drivers:
            proc = self.timed_hook(driver)
            self.assertEqual((0, b"", b""), (proc.returncode, proc.stdout, proc.stderr))
            self.assertIn("matcher_start", self.last_phases)
            self.assertFalse(self.last_phases["report_present"])
        self.assertEqual([], self.received)

    def test_a_gil_held_regex_remains_a_rejected_negative_control(self) -> None:
        # Only this injected negative control writes a diagnostic to stderr.
        driver = (
            "import os, re; event_hook.command_shape = lambda _: ("
            "os.write(2, b'regex-entered'), re.fullmatch('(a+)+$', 'a'*30+'!'))[1]"
        )
        # Its own limit, below the generous default: the regex never finishes, so
        # any budget proves the hang. 0.25 s was measured too short on Windows
        # runners, where the interpreter had not written `regex-entered` yet.
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            self.timed_hook(driver, timeout=3)
        self.assertEqual(b"", caught.exception.output)
        self.assertEqual(b"regex-entered", caught.exception.stderr)
        self.assertEqual([], self.received)

    def test_completed_late_success_stays_discarded_before_real_process_exit(self) -> None:
        # The matcher finishes only once main has returned, so its success is late
        # by construction. A 30 ms sleep raced the 5 ms join instead, and a loaded
        # macOS runner returned the report after it (DRC-4659).
        proc = self.timed_hook(
            "import threading; late = threading.Event()\n"
            "event_hook.command_shape = lambda _: (late.wait(5), 'git_force_push')[1]",
            after_main="late.set()\nwhile 'matcher_end' not in marks: time.sleep(.001)",
        )
        self.assertEqual((0, b"", b""), (proc.returncode, proc.stdout, proc.stderr))
        self.assertEqual("git_force_push", self.last_phases["lexical_result"])
        self.assertGreater(self.last_phases["matcher_end"], self.last_phases["report_return"])
        self.assertFalse(self.last_phases["report_present"])
        self.assertEqual([], self.received)

    def test_normal_matching_reports_its_real_scheduling_and_startup_phases(self) -> None:
        for _ in range(5):
            before = len(self.received)
            proc = self.timed_hook("", timeout=3)
            self.assertEqual((0, b"", b""), (proc.returncode, proc.stdout, proc.stderr))
            self.assertEqual(before + int(self.last_phases["report_present"]), len(self.received))
            if self.last_phases["report_present"]:
                self.assertEqual("git_force_push", self.received[-1]["pattern_id"])

    def test_duplicate_and_reordered_reports_survive_collection_and_end(self) -> None:
        self.post(wire())
        self.post(
            wire("git_hard_reset", timestamp=datetime.fromtimestamp(NOW - 10, UTC).isoformat())
        )
        self.post(wire())
        self.post({"v": 1, "event": "session_ended", "session_id": SESSION})
        self.coordinator._collect("event")
        payload = json.loads(self.app.collect_json(show_all=False)[1])
        reports = payload["command_reports"]
        self.assertEqual(
            ["git_force_push", "git_force_push", "git_hard_reset"],
            [r["pattern_id"] for r in reports],
        )
        self.assertEqual(reports, payload["sessions"][0]["command_reports"])
        self.assertEqual(NOW, payload["sessions"][0]["ended_at"])
        replacement = observation.Observation(self.app, clock=lambda: NOW)
        self.app.overlays = replacement
        self.assertEqual([], self.app.collect(show_all=False)["command_reports"])

    def test_an_off_replacement_rejects_a_report_even_with_its_current_capability(self) -> None:
        self.close_server()
        self.coordinator.config = dataclasses.replace(self.config, irreversible_enabled=False)
        self.app.config = self.coordinator.config
        self.coordinator = observation.Observation(self.app, clock=lambda: NOW)
        self.app.overlays = self.coordinator
        self.server = support.make_server(
            port=self.port, application=self.app, observation=self.coordinator
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self.thread.start()
        self.write_state(False)
        self.assertEqual("disabled", self.post(wire())["outcome"])
        self.assertEqual([], self.received)
        payload = self.app.collect(show_all=False)
        self.assertFalse(payload["irreversible_enabled"])
        self.assertNotIn("command_reports", payload)
        self.assertIsNone(payload["sessions"][0]["command_reports"])


class CommandRetentionTest(unittest.TestCase):
    def test_caps_retain_newest_reports_and_expiry_removes_them(self) -> None:
        ledger = irreversible.Ledger()
        for n in range(1100):
            ledger.add(
                irreversible.Report("claude", str(n // 22), "git_force_push", "Bash", NOW + n, n),
                now=NOW + 1100,
            )
        reports = ledger.published(now=NOW + 1100)
        self.assertEqual(1000, len(reports))
        self.assertEqual(NOW + 1099, reports[0]["timestamp"])
        self.assertTrue(all(sum(r["sid"] == str(s) for r in reports) == 20 for s in range(50)))
        ledger.add(
            irreversible.Report("claude", "extra", "git_hard_reset", "Bash", NOW + 1200, 1200),
            now=NOW + 1200,
        )
        self.assertEqual(1000, len(ledger.published(now=NOW + 1200)))
        self.assertEqual([], ledger.published(now=NOW + 1200 + 86400))

    def test_respawn_keeps_off_and_the_atomic_state_publishes_the_effective_bit(self) -> None:
        for flags in ([], ["--no-irreversible"], ["--no-events"]):
            args = cli.build_parser().parse_args(flags)
            config, _ = cli.build_runtime(args, started=NOW)
            child = cli.build_parser().parse_args(lifecycle.spawn_argv(config, args)[2:])
            child_config, _ = cli.build_runtime(child, started=NOW)
            self.assertEqual(not flags, child_config.irreversible_enabled)
            with tempfile.TemporaryDirectory() as tmp:
                config = dataclasses.replace(config, state_home=tmp, state_dir=Path(tmp))
                lifecycle.write_state(config, 4553, started=NOW, capabilities={"claude": "test"})
                with patch.dict(os.environ, {"COMPASS_HOME": tmp}):
                    self.assertEqual(
                        "test" if not flags else None,
                        event_hook.capability(4553, "claude", irreversible=True),
                    )


class CommandReportTest(unittest.TestCase):
    def test_a_finished_match_beyond_the_nominal_wait_is_discarded(self) -> None:
        with (
            patch.object(event_hook, "threading", SimpleNamespace(Thread=_InlineThread)),
            patch.object(
                event_hook, "time", SimpleNamespace(monotonic=iter((1.0, 1.006)).__next__)
            ),
        ):
            self.assertIsNone(event_hook.irreversible_report(native("git push --force"), "claude"))

    def test_a_matching_command_reduces_to_six_fixed_routing_fields(self) -> None:
        payload = {
            "hook_event_name": "PostToolUse",
            "session_id": SESSION,
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force private-sentinel"},
            "tool_response": "private-output",
            "cwd": "private-directory",
        }
        with (
            patch.object(event_hook, "threading", SimpleNamespace(Thread=_InlineThread)),
            patch.object(event_hook, "time", SimpleNamespace(monotonic=lambda: 0.0)),
        ):
            report = event_hook.irreversible_report(payload, "claude")
        self.assertIsNotNone(report)
        assert report is not None
        self.assertEqual(
            {"v", "event", "session_id", "timestamp", "pattern_id", "tool_name"}, set(report)
        )
        self.assertEqual("git_force_push", report["pattern_id"])
        self.assertNotIn("private", str(report))

    def test_two_reports_survive_one_coalescing_window_and_session_end(self) -> None:
        coordinator = observation.Observation(
            FakeApplication(
                support.make_config(state_home=self.enterContext(tempfile.TemporaryDirectory()))
            ),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        report = {
            "v": 1,
            "event": "command_shape_reported",
            "session_id": SESSION,
            "timestamp": "2023-11-14T22:13:20Z",
            "pattern_id": "git_force_push",
            "tool_name": "Bash",
        }
        self.assertEqual("accepted", coordinator.submit("claude", report))
        self.assertEqual("accepted", coordinator.submit("claude", report))
        coordinator.submit("claude", {"v": 1, "event": "session_ended", "session_id": SESSION})
        self.assertEqual(2, len(coordinator.command_reports()))
