"""The event-latency benchmark: the parts that can be tested without waiting.

`sample()` deliberately sleeps out a real collection floor, so it is exercised by
running the script rather than by the suite. What is tested here is everything
around it: the envelope it posts, the publish detector, and the reporting, because
a benchmark that silently measures the wrong thing is worse than no benchmark.
"""

from __future__ import annotations

import sys
import time
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bench_event_latency as bench


class FakeSnapshot:
    """A snapshot whose revision changes only when told to."""

    def __init__(self, revision: tuple[float, int] | None) -> None:
        self.revision = revision

    def current(self, _key: Any) -> tuple[tuple[float, int], bytes] | None:
        return None if self.revision is None else (self.revision, b"{}")


class FakeApp:
    def __init__(self, revision: tuple[float, int] | None = (1.0, 1)) -> None:
        self.config = SimpleNamespace(window_hours=24.0)
        self.snapshot = FakeSnapshot(revision)


class EnvelopeTest(unittest.TestCase):
    def test_the_envelope_is_the_shape_the_ingress_accepts(self) -> None:
        # A benchmark posting a rejected envelope would measure the reject path
        # and report it as latency.
        built = bench._envelope("input_requested")
        self.assertEqual(1, built["v"])
        self.assertEqual("input_requested", built["event"])
        self.assertEqual(36, len(built["session_id"]))

    def test_the_envelope_carries_no_content(self) -> None:
        self.assertEqual({"v", "event", "session_id"}, set(bench._envelope("store_changed")))


class WaitForPublishTest(unittest.TestCase):
    def test_a_changed_revision_is_detected_and_timed(self) -> None:
        app = FakeApp(revision=(1.0, 1))

        def flip(_seconds: float) -> None:
            app.snapshot.revision = (1.0, 2)

        timer = unittest.mock.Mock(side_effect=flip)
        # The sleep is patched, so a generous deadline costs nothing and a loaded
        # runner cannot run out of it before the second poll.
        with unittest.mock.patch.object(time, "sleep", timer):
            taken = bench._wait_for_publish(app, deadline=30.0)
        self.assertIsNotNone(taken)
        assert taken is not None
        self.assertGreaterEqual(taken, 0.0)

    def test_no_publish_within_the_deadline_is_none_rather_than_zero(self) -> None:
        # None and 0.0 are opposite findings, and a report that conflated them
        # would present a dropped event as an instant one.
        app = FakeApp(revision=(1.0, 1))
        started = time.perf_counter()
        self.assertIsNone(bench._wait_for_publish(app, deadline=0.05))
        self.assertGreaterEqual(time.perf_counter() - started, 0.04)

    def test_a_first_publication_counts_as_a_change(self) -> None:
        app = FakeApp(revision=None)

        def publish(_seconds: float) -> None:
            app.snapshot.revision = (1.0, 1)

        sleeper = unittest.mock.Mock(side_effect=publish)
        with unittest.mock.patch.object(time, "sleep", sleeper):
            self.assertIsNotNone(bench._wait_for_publish(app, deadline=30.0))


class ReportTest(unittest.TestCase):
    def _report(self, values: dict[str, float | None]) -> str:
        config = SimpleNamespace(collect_memo_sec=2.5, event_coalesce_sec=0.1)
        with (
            unittest.mock.patch.object(bench, "_config", return_value=config),
            unittest.mock.patch.object(bench, "sample", side_effect=lambda case: values[case]),
        ):
            return bench.report(1)

    def test_every_case_is_reported_with_the_configuration_it_depended_on(self) -> None:
        text = self._report({"ordinary": 0.3, "urgent": 0.18, "floored": 2.86})
        for case in ("ordinary", "urgent", "floored"):
            self.assertIn(case, text)
        self.assertIn("2.5", text, "the floor is what the numbers mean nothing without")
        self.assertIn("0.1", text)

    def test_milliseconds_rather_than_seconds(self) -> None:
        text = self._report({"ordinary": 0.3, "urgent": 0.18, "floored": 2.86})
        self.assertIn("300.0ms", text)
        self.assertIn("2860.0ms", text)

    def test_a_case_that_never_published_says_so_rather_than_reporting_zero(self) -> None:
        text = self._report({"ordinary": 0.3, "urgent": 0.18, "floored": None})
        self.assertIn("no publish observed", text)

    def test_main_honours_the_sample_count_and_never_asks_for_zero(self) -> None:
        with unittest.mock.patch.object(bench, "report", return_value="") as report:
            self.assertEqual(0, bench.main(["bench", "--samples", "0"]))
        report.assert_called_once_with(1)


if __name__ == "__main__":
    unittest.main()
