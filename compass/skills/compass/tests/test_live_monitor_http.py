"""The two presses that end a tick: Pause model calls and Analyze drift.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check):
Pause cancels a check in flight, and an Analyze press cancels one that holds the reading slot and
then takes it. Driven through the real routes, with a stub runner in place of the CLI.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import live_monitor, reading, reading_policy, reading_route

from . import test_http_api
from .test_live_monitor import GOAL, NOW, FakeRunner, facts

KEY = "claude:s1"


class APressEndsATickInFlight(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_http_api.ReadingRouteTest()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture._runtime()
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.transcript = Path(home.name) / "session.jsonl"
        self.transcript.write_text('{"n":1}\n', encoding="utf-8")
        patch = mock.patch.object(reading_route, "destination", return_value="")
        patch.start()
        self.addCleanup(patch.stop)

    def _start_tick(self, runner: FakeRunner) -> tuple[threading.Thread, list[live_monitor.Tick]]:
        live_monitor.begin_window(self.config, KEY, now=NOW)
        results: list[live_monitor.Tick] = []
        thread = threading.Thread(
            target=lambda: results.append(
                live_monitor.tick(
                    self.config,
                    KEY,
                    now=NOW,
                    transcript_path=str(self.transcript),
                    facts=facts(sid="s1"),
                    intent=GOAL,
                    estimate={"level": "none_or_low"},
                    runner=runner,
                    binary_resolver=lambda _name: "/synthetic/bin/claude",
                )
            )
        )
        thread.start()
        self.assertTrue(runner.started.wait(timeout=10))
        return thread, results

    def test_pause_model_calls_cancels_the_check_and_the_next_one_is_refused(self) -> None:
        runner = FakeRunner(hold=True)
        thread, results = self._start_tick(runner)
        with self.fixture._serving(
            self.fixture._app(self.config, self.state, harness="claude")
        ) as port:
            status, _raw = self.fixture._post(
                port, {"consent": "off", "press": True, "observer_model": 1}
            )
        thread.join(timeout=10)
        self.assertEqual(200, status)
        self.assertTrue(runner.groups[0].cancelled.is_set())
        self.assertEqual(
            ("cancelled", "model-calls-paused"), (results[0].status, results[0].reason)
        )
        self.assertIsNone(live_monitor.published(self.config, KEY))
        again = live_monitor.tick(
            self.config,
            KEY,
            now=NOW + 120,
            transcript_path=str(self.transcript),
            facts=facts(sid="s1"),
            intent=GOAL,
            estimate={"level": "none_or_low"},
            runner=runner,
            binary_resolver=lambda _name: "/synthetic/bin/claude",
        )
        self.assertEqual(("refused", "model-calls-paused"), (again.status, again.reason))

    def test_an_analyze_press_cancels_the_tick_takes_the_slot_and_is_not_refused(self) -> None:
        runner = FakeRunner(hold=True)
        thread, results = self._start_tick(runner)
        with (
            self.fixture._counting_model(("claude",), harness="claude") as calls,
            self.fixture._serving(
                self.fixture._app(self.config, self.state, harness="claude")
            ) as port,
        ):
            status, raw = self.fixture._post(
                port, self.fixture._press(harness="claude", provider="claude")
            )
        thread.join(timeout=10)
        self.assertEqual(202, status, raw)
        self.assertNotEqual("in-flight", json.loads(raw).get("reason"))
        self.assertEqual(1, len(calls))
        self.assertEqual(("cancelled", "analyze"), (results[0].status, results[0].reason))
        # The tick's reserved spend stays spent; Analyze charged its own budget besides.
        self.assertEqual(1, reading_policy.monitor_status(self.config, now=NOW)["used"])
        self.assertTrue(reading.claim(self.config, KEY))
        reading.release(self.config, KEY)


class AnalyzeThatIsRefusedAnywayDoesNotWasteATick(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = test_http_api.ReadingRouteTest()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture._runtime()
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.transcript = Path(home.name) / "session.jsonl"
        self.transcript.write_text('{"n":1}\n', encoding="utf-8")
        patch = mock.patch.object(reading_route, "destination", return_value="")
        patch.start()
        self.addCleanup(patch.stop)

    def _press_with_a_tick_running(self, *, installed: tuple[str, ...]) -> tuple[int, FakeRunner]:
        runner = FakeRunner(hold=True)
        live_monitor.begin_window(self.config, KEY, now=NOW)
        thread = threading.Thread(
            target=lambda: live_monitor.tick(
                self.config,
                KEY,
                now=NOW,
                transcript_path=str(self.transcript),
                facts=facts(sid="s1"),
                intent=GOAL,
                estimate={"level": "none_or_low"},
                runner=runner,
                binary_resolver=lambda _name: "/synthetic/bin/claude",
            )
        )
        thread.start()
        self.assertTrue(runner.started.wait(timeout=10))
        with (
            self.fixture._counting_model(installed, harness="claude"),
            self.fixture._serving(
                self.fixture._app(self.config, self.state, harness="claude")
            ) as port,
        ):
            status, _raw = self.fixture._post(
                port, self.fixture._press(harness="claude", provider="claude"), settle=False
            )
            still_running = not runner.groups[0].cancelled.is_set()
            live_monitor.cancel_all(self.config, "test-cleanup")
        thread.join(timeout=10)
        self.assertTrue(still_running, "the press was refused, so it must not cancel the tick")
        return status, runner

    def test_a_spent_analyze_cap_leaves_the_tick_running(self) -> None:
        for count in range(reading_policy.DAILY_CAP):
            reading_policy.reserve(self.config, now=NOW + count, provider="claude")
        status, _runner = self._press_with_a_tick_running(installed=("claude",))
        self.assertNotEqual(202, status)

    def test_a_missing_claude_cli_leaves_the_tick_running(self) -> None:
        status, _runner = self._press_with_a_tick_running(installed=())
        self.assertNotEqual(202, status)


if __name__ == "__main__":
    unittest.main()
