"""The Live monitor's own spend ledger and its `monitor` notice, apart from Analyze's budget.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check):
a rolling 24 h cap across the board for ticks, never `reading_policy.DAILY_CAP`, and a notice kind
of its own under [DEC-28](docs/design-session-summary.md#the-widening-opt-out-with-a-notice-for-every-call-a-reader-starts).
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path

from compass_runtime import reading_policy

from .support import make_config

NOW = 1_700_000_000.0
DAY = reading_policy.DAY_SEC


class _Store(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config = dataclasses.replace(
            make_config(), state_dir=Path(home.name), live_monitor_daily_cap=3
        )


class TheBoardWideRollingCap(_Store):
    def test_ticks_are_charged_before_launch_until_the_cap_then_refused_with_cap(self) -> None:
        for count in range(3):
            answer = reading_policy.reserve_monitor(self.config, now=NOW + count)
            self.assertEqual("", answer["reason"])
            self.assertEqual(count + 1, answer["used"])
        refused = reading_policy.reserve_monitor(self.config, now=NOW + 3)
        self.assertEqual("cap", refused["reason"])
        self.assertEqual((3, 3), (refused["used"], refused["limit"]))
        self.assertEqual(NOW + DAY, refused["retry_at"])

    def test_a_charge_leaves_the_window_after_twenty_four_hours(self) -> None:
        for count in range(3):
            reading_policy.reserve_monitor(self.config, now=NOW + count)
        answer = reading_policy.reserve_monitor(self.config, now=NOW + DAY + 0.5)
        # The first charge aged out, two stayed, and this one is the third.
        self.assertEqual("", answer["reason"])
        self.assertEqual(3, answer["used"])

    def test_a_read_charges_nothing(self) -> None:
        reading_policy.reserve_monitor(self.config, now=NOW)
        self.assertEqual(1, reading_policy.monitor_status(self.config, now=NOW + 1)["used"])
        self.assertEqual(1, reading_policy.monitor_status(self.config, now=NOW + 2)["used"])

    def test_the_default_limit_is_the_configured_one(self) -> None:
        answer = reading_policy.monitor_status(make_config(), now=NOW)
        self.assertEqual(make_config().live_monitor_daily_cap, answer["limit"])


class TheTwoBudgetsAreKeptApart(_Store):
    def test_spending_the_monitors_caps_leaves_analyze_untouched(self) -> None:
        before = reading_policy.status(self.config, now=NOW)
        for count in range(3):
            reading_policy.reserve_monitor(self.config, now=NOW + count)
        self.assertEqual("cap", reading_policy.reserve_monitor(self.config, now=NOW + 9)["reason"])
        after = reading_policy.status(self.config, now=NOW + 10)
        self.assertEqual((before["used"], before["reason"]), (after["used"], after["reason"]))
        reserved = reading_policy.reserve(self.config, now=NOW + 11, provider="claude")
        self.assertEqual(("", 1), (reserved["reason"], reserved["used"]))

    def test_spending_analyzes_cap_leaves_the_monitor_untouched(self) -> None:
        for count in range(reading_policy.DAILY_CAP):
            reading_policy.reserve(self.config, now=NOW + count, provider="claude")
        self.assertEqual("daily-cap", reading_policy.reserve(self.config, now=NOW + 200)["reason"])
        answer = reading_policy.reserve_monitor(self.config, now=NOW + 201)
        self.assertEqual(("", 1), (answer["reason"], answer["used"]))


class PauseAndTheStartupSwitchRefuseTheLedger(_Store):
    def test_pause_refuses_a_charge_and_charges_nothing(self) -> None:
        reading_policy.set_consent(self.config, False, now=NOW)
        answer = reading_policy.reserve_monitor(self.config, now=NOW + 1)
        self.assertEqual("model-calls-paused", answer["reason"])
        self.assertEqual(0, answer["used"])
        reading_policy.resume(self.config, now=NOW + 2)
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW + 3)["used"])
        self.assertEqual("", reading_policy.reserve_monitor(self.config, now=NOW + 4)["reason"])

    def test_no_observer_model_refuses_a_charge(self) -> None:
        off = dataclasses.replace(self.config, model_calls_disabled=True)
        answer = reading_policy.reserve_monitor(off, now=NOW)
        self.assertEqual("run-disabled", answer["reason"])
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW + 1)["used"])

    def test_an_unreadable_store_refuses(self) -> None:
        blocked = dataclasses.replace(self.config, state_dir=Path("/nonexistent-compass/none"))
        answer = reading_policy.reserve_monitor(blocked, now=NOW)
        self.assertEqual("store-unavailable", answer["reason"])


class TheMonitorNotice(_Store):
    def _note(self, now: float = NOW) -> reading_policy.Notice | None:
        return reading_policy.note(
            self.config,
            kind="monitor",
            provider="claude",
            destination="api.anthropic.com",
            content=reading_policy.WORDS_CONTENT_VERSION,
            tool_output="",
            now=now,
        )

    def test_monitor_is_a_notice_kind_and_is_shown_once_per_destination(self) -> None:
        self.assertIn("monitor", reading_policy.NOTICE_KINDS)
        first = self._note()
        self.assertIsNotNone(first)
        self.assertIsNone(self._note(NOW + 1))
        self.assertIn("monitor", reading_policy.status(self.config, now=NOW + 2)["notices"])

    def test_a_retracted_notice_is_shown_again(self) -> None:
        notice = self._note()
        assert notice is not None
        reading_policy.retract(self.config, notice)
        self.assertIsNotNone(self._note(NOW + 1))

    def test_pause_clears_it_so_resume_shows_it_again(self) -> None:
        self._note()
        reading_policy.set_consent(self.config, False, now=NOW + 1)
        reading_policy.resume(self.config, now=NOW + 2)
        self.assertIsNotNone(self._note(NOW + 3))


class TheGuardedSeamTakesOneReservationRule(_Store):
    def test_a_ledger_of_its_own_cannot_be_combined_with_a_job_marker(self) -> None:
        with self.assertRaises(ValueError):
            reading_policy.GuardedModel(
                self.config,
                lambda _prompt, **_kw: ("", "ok"),
                lambda: NOW,
                reserve_with=reading_policy.reserve_monitor,
                before_reserve=lambda: "job",
            )


if __name__ == "__main__":
    unittest.main()
