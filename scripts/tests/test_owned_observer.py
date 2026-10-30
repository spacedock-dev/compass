"""The owned-process observer: it loses no event, keeps no words, and is off unless asked.

docs/design-owned-process-observer.md owns what the observer can and cannot see. These tests hold
the three claims that make its trace worth attaching: the control run's counts agree with what
independently happened, a long argument is recorded as its length, and nothing in the shipped
plugin can turn the hook on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import observe_journey
import owned_observer

ROOT = Path(__file__).resolve().parents[2]
SHIPPED_ROOTS = (ROOT / "compass", ROOT / "compass-gemini", ROOT / "compass-droid")


def _clean_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in (owned_observer.ENV_LOG, "NODE_OPTIONS", "BUN_OPTIONS"):
        env.pop(name, None)
    return env


class TheObserverIsOffUnlessAskedTest(unittest.TestCase):
    """The shipped server is unchanged: nothing turns the hook on but `exec` with a log named."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_exec_refuses_without_the_variable_and_runs_nothing(self) -> None:
        marker = self.tmp / "ran"
        target = self.tmp / "target.py"
        target.write_text(f"open({str(marker)!r}, 'w').write('ran')\n")
        result = subprocess.run(
            [sys.executable, str(observe_journey.OBSERVER), "exec", "--", str(target)],
            env=_clean_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(owned_observer.ENV_LOG, result.stderr)
        self.assertFalse(marker.exists())

    def test_install_from_an_environment_without_a_log_installs_nothing(self) -> None:
        program = textwrap.dedent(
            f"""
            import subprocess, sys
            sys.path.insert(0, {str(Path(owned_observer.__file__).parent)!r})
            import owned_observer
            print(owned_observer.install_from_environment({{}}))
            subprocess.run(["/bin/sh", "-c", "true"], check=True)
            print(sorted(owned_observer._state))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            env=_clean_environment(),
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.split(), ["False", "[]"])

    def test_the_shipped_server_ignores_the_variable(self) -> None:
        log = self.tmp / "trace.jsonl"
        env = _clean_environment() | {
            owned_observer.ENV_LOG: str(log),
            "COMPASS_HOME": str(self.tmp / "home"),
        }
        result = subprocess.run(
            [sys.executable, str(observe_journey.SERVER), "--version"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(log.exists(), "server.py started the ordinary way wrote a trace")

    @unittest.skipUnless(shutil.which("node"), "node is not on PATH")
    def test_the_preload_does_nothing_without_the_variable(self) -> None:
        env = _clean_environment() | {"NODE_OPTIONS": f"--require={owned_observer.PRELOAD}"}
        result = subprocess.run(
            [
                shutil.which("node") or "node",
                "-e",
                "require('child_process').spawnSync('true'); console.log(typeof globalThis.__compassOwnedObserver)",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            cwd=self.tmp,
        )
        self.assertEqual(result.stdout.strip(), "undefined")
        self.assertEqual(list(self.tmp.iterdir()), [])

    def test_no_shipped_file_names_the_observer(self) -> None:
        needles = ("owned_observer", owned_observer.ENV_LOG, "addaudithook")
        found = []
        for root in SHIPPED_ROOTS:
            for path in root.rglob("*"):
                if (
                    not path.is_file()
                    or "node_modules" in path.parts
                    or "__pycache__" in path.parts
                ):
                    continue
                text = path.read_bytes().decode("utf-8", errors="ignore")
                found += [
                    f"{path.relative_to(ROOT)}: {needle}" for needle in needles if needle in text
                ]
        self.assertEqual(found, [])


class TheControlRunLosesNothingTest(unittest.TestCase):
    """Every launch, connection, lookup and request of a known workload is one trace line."""

    def _control(self, runtimes: tuple[str, ...]) -> observe_journey.ControlResult:
        out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        result = observe_journey.control_run(out, count=12, runtimes=runtimes)
        self.assertEqual(result.observed, result.expected)
        self.assertEqual(result.launches_observed, result.launches_ran)
        self.assertEqual(result.connections_observed, result.accepted)
        self.assertFalse(result.lost)
        return result

    def test_the_server_side_loses_no_event(self) -> None:
        result = self._control(())
        # 12 Popen and 12 posix_spawn programs ran; 24 connections reached the listener.
        self.assertEqual(sum(result.launches_ran.values()), 24)
        self.assertEqual(result.accepted, 24)

    @unittest.skipUnless(shutil.which("node"), "node is not on PATH")
    def test_a_node_child_loses_no_event(self) -> None:
        result = self._control(("node",))
        self.assertEqual(result.launches_ran["node-spawnSync"], 12)
        self.assertEqual(result.accepted, 24 + 36)

    @unittest.skipUnless(shutil.which("bun"), "bun is not on PATH")
    def test_a_bun_child_loses_no_event(self) -> None:
        result = self._control(("bun",))
        self.assertEqual(result.launches_ran["bun-execFile"], 12)
        self.assertEqual(result.accepted, 24 + 36)

    def test_a_lost_event_is_reported_as_lost(self) -> None:
        expected = observe_journey.expected_events(3, ("node",))
        self.assertEqual(expected[("node", "connect", "socket.connect")], 9)
        result = observe_journey.ControlResult((), {"a": 1}, {"a": 1}, {}, {}, 4, 3, 0.0, "")
        self.assertTrue(result.lost)


class TheTraceKeepsNoWordsTest(unittest.TestCase):
    """A launch is recorded by program and short arguments; a prompt-sized argument by length."""

    def test_a_long_or_multiline_argument_is_recorded_as_its_length(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        words = "the reader typed this and it must not reach the trace " * 4
        target = tmp / "target.py"
        target.write_text(
            f"import subprocess\nsubprocess.run(['/bin/echo', '--model', {words!r}, 'a\\nb'], check=True, capture_output=True)\n"
        )
        trace = tmp / "trace.jsonl"
        env = owned_observer.observed_environment(_clean_environment(), str(trace))
        subprocess.run(
            [sys.executable, str(observe_journey.OBSERVER), "exec", "--", str(target)],
            env=env,
            check=True,
        )
        launch = next(e for e in observe_journey.read_trace(trace) if e["kind"] == "launch")
        self.assertEqual(launch["program"], "echo")
        self.assertEqual(
            launch["argv"], ["/bin/echo", "--model", f"<{len(words)} chars>", "<3 chars>"]
        )
        self.assertTrue(launch["hooked"])
        self.assertNotIn("reader typed", trace.read_text())


def _event(kind: str, op: str, **fields: object) -> dict[str, object]:
    return {"t": 1.0, "src": "python", "pid": 10, "ppid": 1, "kind": kind, "op": op} | fields


class TheReportDiffsAgainstTheAuditTableTest(unittest.TestCase):
    """Each event lands on a SECURITY.md row, and what a run's switches forbid is a departure."""

    def test_every_row_the_report_uses_is_a_row_of_the_table(self) -> None:
        rows = observe_journey.table_rows()
        self.assertGreater(len(rows), 15)
        self.assertEqual([row for row in observe_journey.ROWS_USED if row not in rows], [])

    def _trace(self) -> list[dict[str, object]]:
        return [
            _event("start", "process", program="python3"),
            _event("launch", "subprocess.Popen", program="claude", argv=["claude", "--print"]),
            _event("spawned", "subprocess.Popen", child=20, program="claude"),
            {"t": 1.1, "src": "bun", "pid": 20, "ppid": 10, "kind": "start", "op": "process"},
            {
                "t": 1.2,
                "src": "bun",
                "pid": 20,
                "ppid": 10,
                "kind": "request",
                "op": "fetch",
                "host": "api.anthropic.com",
                "port": 443,
            },
            _event("exit", "subprocess.Popen", child=20, code=0),
            _event("launch", "subprocess.Popen", program="git", argv=["git", "rev-parse"]),
            _event("resolve", "socket.getaddrinfo", host="api.anthropic.com", port=443),
            _event("connect", "socket.connect", family="inet", host="api.anthropic.com", port=443),
        ]

    def test_a_default_run_attributes_every_event_and_departs_nowhere(self) -> None:
        result = observe_journey.report(self._trace(), "default")
        self.assertEqual(result["departures"], [])
        self.assertEqual(result["unlisted"], [])
        self.assertIn(
            "bun request api.anthropic.com:443", result["by_row"][observe_journey.ROW_PRESS]
        )
        self.assertIn(observe_journey.ROW_GIT, result["by_row"])
        self.assertIn(observe_journey.ROW_QUOTA, result["by_row"])
        claude = next(launch for launch in result["launches"] if launch["program"] == "claude")
        self.assertTrue(claude["seen_inside"])
        self.assertEqual(result["opaque_launches"], [])

    def test_a_model_launch_under_no_model_is_a_departure(self) -> None:
        for mode in ("no-model", "declined"):
            with self.subTest(mode=mode):
                result = observe_journey.report(self._trace(), mode)
                self.assertEqual(
                    [item["row"] for item in result["departures"]], [observe_journey.ROW_PRESS]
                )

    def test_monitor_only_admits_the_haiku_check_and_nothing_else(self) -> None:
        trace = self._trace()
        self.assertEqual(len(observe_journey.report(trace, "monitor-only")["departures"]), 1)
        trace[1] = _event(
            "launch",
            "subprocess.Popen",
            program="claude",
            argv=["claude", "--model", "claude-haiku-5-5"],
        )
        self.assertEqual(observe_journey.report(trace, "monitor-only")["departures"], [])

    def test_an_unlisted_connection_and_a_unix_socket_are_reported(self) -> None:
        trace = [
            _event("start", "process"),
            _event("connect", "socket.connect", family="inet", host="example.com", port=443),
            _event("connect", "socket.connect", family="unix", path="/tmp/sock"),
        ]
        result = observe_journey.report(trace, "default")
        self.assertEqual([event["host"] for event in result["unlisted"]], ["example.com"])
        self.assertEqual(len(result["departures"]), 1)

    def test_a_launch_the_preload_did_not_reach_is_opaque(self) -> None:
        trace = [
            _event("start", "process"),
            _event("launch", "subprocess.Popen", program="codex", argv=["codex"]),
            _event("spawned", "subprocess.Popen", child=30, program="codex"),
        ]
        self.assertEqual(observe_journey.report(trace, "default")["opaque_launches"], ["codex"])

    def test_a_transcript_check_says_whether_its_earlier_bytes_survived(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        transcript = tmp / "session.jsonl"
        transcript.write_text('{"a": 1}\n')
        before = observe_journey.snapshot(transcript)
        transcript.write_text('{"a": 1}\n{"b": 2}\n{"c": 3}\n')
        appended = observe_journey.transcript_change(transcript, before)
        self.assertEqual((appended["prefix_preserved"], appended["appended_lines"]), (True, 2))
        self.assertNotIn('"b"', json.dumps(appended))
        transcript.write_text('{"a": 9}\n')
        self.assertFalse(observe_journey.transcript_change(transcript, before)["prefix_preserved"])

    def test_the_run_starts_this_checkouts_server_under_the_observer(self) -> None:
        command = observe_journey.journey_command(4599, "no-model", ["--no-reach"])
        self.assertEqual(command[1:4], [str(observe_journey.OBSERVER), "exec", "--"])
        self.assertEqual(
            command[4:],
            [str(observe_journey.SERVER), "--port", "4599", "--no-observer-model", "--no-reach"],
        )
        env = observe_journey.journey_environment(Path("/x/trace.jsonl"), Path("/x/home"), None)
        self.assertEqual(env[owned_observer.ENV_LOG], "/x/trace.jsonl")
        self.assertEqual(env["COMPASS_HOME"], "/x/home")
        self.assertIn(f"--require={owned_observer.PRELOAD}", env["NODE_OPTIONS"])
        self.assertIn(f"--preload={owned_observer.PRELOAD}", env["BUN_OPTIONS"])


if __name__ == "__main__":
    unittest.main()
