"""The Live monitor's lease: who holds it, when it lapses, and what ends it.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)
puts the TTL clock on the server, and the owner's ruling stops the monitor when the reader leaves.
Every time here is a fake clock and no test sends a beacon: a killed tab sends nothing.
"""

from __future__ import annotations

import dataclasses
import itertools
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import live_lease, live_monitor, reading_policy, reading_route

from .support import make_config
from .test_live_monitor import GOAL, FakeRunner, facts

NOW = 1_700_000_000.0
HARNESS, SID, KEY = "claude", "one", "claude:one"
TAB_A, TAB_B = "tab-a", "tab-b"


class Rig(unittest.TestCase):
    """A lease table over fake rows and a fake tick, on a clock the test moves."""

    def setUp(self) -> None:
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state_dir = Path(state.name)
        self.config = dataclasses.replace(
            make_config(), state_dir=self.state_dir, live_monitor_daily_cap=50
        )
        patch = mock.patch.object(reading_route, "destination", return_value="api.anthropic.com")
        patch.start()
        self.addCleanup(patch.stop)
        self.now = NOW
        self.rows: dict[tuple[str, str], dict[str, Any]] = {
            (HARNESS, SID): {"harness": HARNESS, "sid": SID, "ended_at": None}
        }
        self.ticks: list[tuple[str, float]] = []
        self.inputs_built = 0
        self.verdict = live_monitor.Tick("skipped", "unchanged")
        self.leases = self.make()
        self.addCleanup(self.leases.close)

    def make(self, config: Any = None) -> live_lease.Leases:
        return live_lease.Leases(
            config or self.config,
            clock=lambda: self.now,
            row_for=lambda harness, sid: self.rows.get((harness, sid)),
            inputs_for=self._inputs,
            tick=self._tick,
            start_thread=False,
        )

    def _inputs(self, _h: str, _s: str, _row: Any) -> live_lease.Inputs:
        self.inputs_built += 1
        return live_lease.Inputs(
            transcript_path="/synthetic/session.jsonl",
            facts=[],
            intent=GOAL,
            estimate={"level": "none_or_low"},
        )

    def _tick(self, _config: Any, session_key: str, **_kwargs: Any) -> live_monitor.Tick:
        self.ticks.append((session_key, self.now))
        return self.verdict

    def at(self, seconds: float) -> None:
        self.now = NOW + seconds

    def run_for(self, seconds: float, *, every: float = 5.0, beat: tuple[str, ...] = ()) -> None:
        """Advance the clock, beating for the tabs named, and let the ticker pass each step."""
        end = self.now + seconds
        while self.now < end:
            self.now += every
            for tab in beat:
                self.leases.beat(HARNESS, SID, tab)
            self.leases.step()

    def start(self, tab: str = TAB_A, **options: Any) -> dict[str, Any]:
        return self.leases.start(HARNESS, SID, tab, **options)


class StartIsRefusedFor(Rig):
    def test_an_ended_session(self) -> None:
        self.rows[(HARNESS, SID)]["ended_at"] = NOW - 5
        refused = self.start()
        self.assertEqual((False, "unavailable"), (refused["ok"], refused["reason"]))
        self.assertFalse(refused["state"]["on"])

    def test_a_harness_other_than_claude_code(self) -> None:
        self.rows[("codex", SID)] = {"harness": "codex", "sid": SID, "ended_at": None}
        refused = self.leases.start("codex", SID, TAB_A)
        self.assertEqual((False, "unsupported-harness"), (refused["ok"], refused["reason"]))

    def test_the_sample_session(self) -> None:
        self.rows[(HARNESS, "sample")] = {"harness": HARNESS, "sid": "sample", "ended_at": None}
        refused = self.leases.start(HARNESS, "sample", TAB_A)
        self.assertEqual((False, "sample"), (refused["ok"], refused["reason"]))

    def test_a_session_the_board_does_not_hold(self) -> None:
        refused = self.leases.start(HARNESS, "nobody", TAB_A)
        self.assertEqual((False, "unavailable"), (refused["ok"], refused["reason"]))

    def test_an_ended_session_and_an_unknown_one_are_refused_in_the_same_words(self) -> None:
        # A start must not tell a caller which session ids exist.
        self.rows[(HARNESS, SID)]["ended_at"] = NOW - 5
        ended = self.start()
        unknown = self.leases.start(HARNESS, "nobody", TAB_A)
        self.assertEqual((ended["ok"], ended["reason"]), (unknown["ok"], unknown["reason"]))
        self.assertEqual("unavailable", ended["reason"])

    def test_a_session_with_two_rows_is_refused_too(self) -> None:
        self.rows[(HARNESS, SID)] = {"harness": HARNESS, "sid": SID, "ambiguous": True}
        self.assertEqual("unavailable", self.start()["reason"])

    def test_paused_model_calls(self) -> None:
        reading_policy.set_consent(self.config, False, now=NOW)
        refused = self.start()
        self.assertEqual((False, "paused"), (refused["ok"], refused["reason"]))

    def test_the_startup_switch_that_refuses_every_model_call(self) -> None:
        off = dataclasses.replace(self.config, model_calls_disabled=True)
        leases = self.make(off)
        self.addCleanup(leases.close)
        refused = leases.start(HARNESS, SID, TAB_A)
        self.assertEqual((False, "no-observer-model"), (refused["ok"], refused["reason"]))

    def test_none_of_them_leaves_a_lease_behind_or_runs_a_check(self) -> None:
        self.rows[(HARNESS, SID)]["ended_at"] = NOW - 5
        self.start()
        self.run_for(300, beat=(TAB_A,))
        self.assertEqual([], self.ticks)
        self.assertFalse(self.leases.state(HARNESS, SID)["on"])


class AStartedLease(Rig):
    def test_publishes_the_clock_the_server_holds(self) -> None:
        answer = self.start()
        self.assertTrue(answer["ok"])
        state = answer["state"]
        self.assertEqual(
            (True, NOW, NOW + 1200.0, NOW + 1800.0, None),
            (
                state["on"],
                state["started_at"],
                state["banner_due_at"],
                state["deadline"],
                state["confirm_by"],
            ),
        )
        self.assertEqual("Live monitor · Haiku", state["label"])
        self.assertIsNone(state["level"])

    def test_it_carries_what_is_sent_and_where_for_the_page_to_show(self) -> None:
        state = self.start()["state"]
        self.assertEqual("api.anthropic.com", state["destination"])
        for phrase in ("Haiku", "api.anthropic.com", "once a minute", "Pause model calls"):
            self.assertIn(phrase, state["disclosure"])

    def test_it_says_nothing_of_what_is_sent_while_off(self) -> None:
        state = self.leases.state(HARNESS, SID)
        self.assertEqual(
            (False, None, None), (state["on"], state["disclosure"], state["destination"])
        )

    def test_a_second_tab_joins_without_moving_the_clock(self) -> None:
        self.start(TAB_A)
        self.at(30)
        second = self.start(TAB_B)
        self.assertEqual(NOW, second["state"]["started_at"])

    def test_nothing_is_written_to_disk_for_it(self) -> None:
        before = sorted(self.state_dir.iterdir())
        self.start()
        self.run_for(120, beat=(TAB_A,))
        self.assertEqual(before, sorted(self.state_dir.iterdir()))

    def test_a_restart_starts_with_no_leases_and_makes_no_check_until_a_new_start(self) -> None:
        self.start()
        self.run_for(70, beat=(TAB_A,))
        self.assertTrue(self.ticks)
        restarted = self.make()
        self.addCleanup(restarted.close)
        self.assertFalse(restarted.state(HARNESS, SID)["on"])
        before = len(self.ticks)
        self.now += 300
        restarted.beat(HARNESS, SID, TAB_A)
        restarted.step()
        self.assertEqual(before, len(self.ticks))


class ALeaseThatIsAbandoned(Rig):
    def test_a_killed_tab_ends_the_lease_left_within_the_grace_and_no_check_follows(self) -> None:
        # No stop, no beacon: the tab simply stops beating.
        self.start()
        self.run_for(30, beat=(TAB_A,))
        checks_while_alive = len(self.ticks)
        self.assertGreaterEqual(checks_while_alive, 1)
        self.run_for(self.config.live_monitor_lapse_sec + 10, beat=())
        state = self.leases.state(HARNESS, SID)
        self.assertFalse(state["on"])
        self.assertEqual("left", state["last_end"]["reason"])
        count = len(self.ticks)
        self.run_for(600, beat=())
        self.assertEqual(count, len(self.ticks))

    def test_the_grace_is_the_configured_lapse_not_a_beacon(self) -> None:
        self.start()
        self.at(self.config.live_monitor_lapse_sec - 1)
        self.leases.step()
        self.assertTrue(self.leases.state(HARNESS, SID)["on"])
        self.at(self.config.live_monitor_lapse_sec + 1)
        self.leases.step()
        self.assertFalse(self.leases.state(HARNESS, SID)["on"])

    def test_one_tab_leaving_does_not_stop_another_tabs_monitor(self) -> None:
        self.start(TAB_A)
        self.start(TAB_B)
        self.leases.stop(HARNESS, SID, TAB_A)
        self.assertTrue(self.leases.state(HARNESS, SID)["on"])
        self.leases.stop(HARNESS, SID, TAB_B)
        state = self.leases.state(HARNESS, SID)
        self.assertEqual((False, "stopped"), (state["on"], state["last_end"]["reason"]))

    def test_a_hidden_tab_pauses_the_checks_and_resumes_them_within_the_ttl(self) -> None:
        self.start()
        self.run_for(5, beat=(TAB_A,))
        self.leases.beat(HARNESS, SID, TAB_A, visible=False)
        paused_at = len(self.ticks)
        self.run_for(600)  # hidden for ten minutes, sending nothing
        self.assertEqual(paused_at, len(self.ticks))
        self.assertTrue(self.leases.state(HARNESS, SID)["on"])
        self.leases.beat(HARNESS, SID, TAB_A, visible=True)
        self.run_for(70, beat=(TAB_A,))
        self.assertGreater(len(self.ticks), paused_at)


class TwoTabsSpendNoMoreThanOne(Rig):
    def test_two_tabs_beating_one_session_produce_at_most_one_check_a_minute(self) -> None:
        self.start(TAB_A)
        self.start(TAB_B)
        self.run_for(600, beat=(TAB_A, TAB_B))
        starts = [at for _key, at in self.ticks]
        self.assertGreaterEqual(len(starts), 5)
        for earlier, later in itertools.pairwise(starts):
            self.assertGreaterEqual(later - earlier, self.config.live_monitor_interval_sec)


class TheSessionEnds(Rig):
    def test_a_session_that_gains_an_end_ends_its_lease_on_the_next_pass(self) -> None:
        self.start()
        self.run_for(10, beat=(TAB_A,))
        self.rows[(HARNESS, SID)]["ended_at"] = self.now
        before = len(self.ticks)
        self.leases.step()
        state = self.leases.state(HARNESS, SID)
        self.assertEqual((False, "ended"), (state["on"], state["last_end"]["reason"]))
        self.assertEqual(before, len(self.ticks))
        self.assertEqual("unavailable", self.start()["reason"])

    def test_a_session_that_leaves_the_board_ends_its_lease(self) -> None:
        self.start()
        del self.rows[(HARNESS, SID)]
        self.leases.step()
        self.assertEqual("ended", self.leases.state(HARNESS, SID)["last_end"]["reason"])


class TheQuestionAndTheClock(Rig):
    def test_confirm_by_appears_at_twenty_minutes_and_the_lease_ends_unanswered_at_thirty(
        self,
    ) -> None:
        self.start()
        self.run_for(1195, beat=(TAB_A,))
        self.assertIsNone(self.leases.state(HARNESS, SID)["confirm_by"])
        self.run_for(10, beat=(TAB_A,))
        state = self.leases.state(HARNESS, SID)
        self.assertEqual(NOW + 1800.0, state["confirm_by"])
        # Checks go on while the question stands, then stop at the deadline.
        self.run_for(590, beat=(TAB_A,))
        self.assertTrue(self.leases.state(HARNESS, SID)["on"])
        self.run_for(10, beat=(TAB_A,))
        state = self.leases.state(HARNESS, SID)
        self.assertEqual((False, "unanswered"), (state["on"], state["last_end"]["reason"]))
        count = len(self.ticks)
        self.run_for(300, beat=(TAB_A,))
        self.assertEqual(count, len(self.ticks))

    def test_yes_resets_the_clock_and_the_next_question_is_twenty_minutes_later(self) -> None:
        self.start()
        self.run_for(1300, beat=(TAB_A,))
        answer = self.leases.confirm(HARNESS, SID, TAB_A, yes=True)
        self.assertTrue(answer["ok"])
        state = answer["state"]
        self.assertEqual(
            (self.now, self.now + 1200.0), (state["started_at"], state["banner_due_at"])
        )
        self.assertIsNone(state["confirm_by"])
        self.run_for(1195, beat=(TAB_A,))
        self.assertIsNone(self.leases.state(HARNESS, SID)["confirm_by"])
        self.run_for(10, beat=(TAB_A,))
        self.assertIsNotNone(self.leases.state(HARNESS, SID)["confirm_by"])

    def test_no_ends_the_lease_declined(self) -> None:
        self.start()
        self.run_for(1300, beat=(TAB_A,))
        answer = self.leases.confirm(HARNESS, SID, TAB_A, yes=False)
        self.assertEqual(
            (False, "declined"), (answer["state"]["on"], answer["state"]["last_end"]["reason"])
        )
        count = len(self.ticks)
        self.run_for(120, beat=(TAB_A,))
        self.assertEqual(count, len(self.ticks))

    def test_a_yes_after_the_deadline_is_refused_and_the_monitor_is_off(self) -> None:
        self.start()
        self.run_for(1790, beat=(TAB_A,))
        self.at(1805)
        answer = self.leases.confirm(HARNESS, SID, TAB_A, yes=True)
        self.assertFalse(answer["ok"])
        self.assertEqual(
            (False, "unanswered"), (answer["state"]["on"], answer["state"]["last_end"]["reason"])
        )

    def test_an_answer_when_no_question_is_open_changes_nothing(self) -> None:
        self.start()
        self.run_for(100, beat=(TAB_A,))
        answer = self.leases.confirm(HARNESS, SID, TAB_A, yes=False)
        self.assertTrue(answer["ok"])
        self.assertTrue(answer["state"]["on"])

    def test_the_second_tabs_late_no_does_not_undo_the_first_tabs_yes(self) -> None:
        self.start(TAB_A)
        self.start(TAB_B)
        self.run_for(1300, beat=(TAB_A, TAB_B))
        self.leases.confirm(HARNESS, SID, TAB_A, yes=True)
        late = self.leases.confirm(HARNESS, SID, TAB_B, yes=False)
        self.assertTrue(late["state"]["on"])

    def test_the_shipped_timings_are_twenty_and_thirty_and_nothing_shortens_them(self) -> None:
        config = make_config()
        self.assertEqual(
            (1200.0, 1800.0), (config.live_monitor_banner_sec, config.live_monitor_window_sec)
        )
        from compass_runtime import cli  # noqa: PLC0415

        options = {
            option for action in cli.build_parser()._actions for option in action.option_strings
        }
        self.assertFalse({o for o in options if "monitor" in o} - {"--claude-monitor-model"})


class WhatEndsTheLeaseOtherwise(Rig):
    def test_a_spent_cap_ends_it_cap(self) -> None:
        self.verdict = live_monitor.Tick("refused", "cap")
        self.start()
        self.run_for(70, beat=(TAB_A,))
        state = self.leases.state(HARNESS, SID)
        self.assertEqual((False, "cap"), (state["on"], state["last_end"]["reason"]))

    def test_pause_ends_every_lease_paused_and_cancels_a_check_in_flight(self) -> None:
        self.rows[(HARNESS, "two")] = {"harness": HARNESS, "sid": "two", "ended_at": None}
        self.start()
        self.leases.start(HARNESS, "two", TAB_A)
        with mock.patch.object(live_monitor, "cancel_all", return_value=1) as cancelled:
            ended = self.leases.stop_all("paused")
        self.assertEqual(2, ended)
        cancelled.assert_called_once_with(self.config, "model-calls-paused")
        for sid in (SID, "two"):
            state = self.leases.state(HARNESS, sid)
            self.assertEqual((False, "paused"), (state["on"], state["last_end"]["reason"]))

    def test_a_pause_that_lands_between_passes_ends_the_lease_on_the_next(self) -> None:
        self.start()
        reading_policy.set_consent(self.config, False, now=NOW)
        self.run_for(10, beat=(TAB_A,))
        self.assertEqual("paused", self.leases.state(HARNESS, SID)["last_end"]["reason"])
        self.assertEqual([], self.ticks)

    def test_a_later_start_forgets_the_earlier_end(self) -> None:
        self.start()
        self.leases.stop(HARNESS, SID, TAB_A)
        self.assertIsNotNone(self.leases.state(HARNESS, SID)["last_end"])
        self.start()
        self.assertIsNone(self.leases.state(HARNESS, SID)["last_end"])

    def test_a_check_that_raises_does_not_stop_the_ticker_or_the_lease(self) -> None:
        def boom(*_args: Any, **_kwargs: Any) -> live_monitor.Tick:
            msg = "synthetic"
            raise RuntimeError(msg)

        messages: list[str] = []
        leases = live_lease.Leases(
            self.config,
            clock=lambda: self.now,
            row_for=lambda h, s: self.rows.get((h, s)),
            inputs_for=lambda *_: live_lease.Inputs("/x", [], GOAL, {"level": "none_or_low"}),
            tick=boom,
            diagnostic_sink=messages.append,
            start_thread=False,
        )
        self.addCleanup(leases.close)
        leases.start(HARNESS, SID, TAB_A)
        leases.step()
        self.assertTrue(leases.state(HARNESS, SID)["on"])
        self.assertTrue(messages)


class AHiddenTabIsNeverTicked(Rig):
    def test_a_start_from_a_hidden_tab_holds_the_lease_and_runs_no_check(self) -> None:
        answer = self.start(visible=False)
        self.assertTrue(answer["ok"])
        self.assertFalse(answer["state"]["visible"])
        self.run_for(300)
        self.assertEqual([], self.ticks)
        self.assertTrue(self.leases.state(HARNESS, SID)["on"])
        self.leases.beat(HARNESS, SID, TAB_A, visible=True)
        self.run_for(70, beat=(TAB_A,))
        self.assertTrue(self.ticks)

    def test_a_start_is_visible_unless_it_says_otherwise(self) -> None:
        self.assertTrue(self.start()["state"]["visible"])


class OnlyAHolderCanBeat(Rig):
    def test_a_tab_that_never_started_cannot_join_by_beating(self) -> None:
        self.start(TAB_A)
        answer = self.leases.beat(HARNESS, SID, TAB_B)
        self.assertEqual((False, "not-monitoring"), (answer["ok"], answer["reason"]))
        self.assertTrue(answer["state"]["on"])
        self.assertEqual({TAB_A}, set(live_monitor._SESSIONS[(str(self.state_dir), KEY)].holders))
        # So the one holder leaving stops it, with no stranger left holding it.
        self.leases.stop(HARNESS, SID, TAB_A)
        self.assertFalse(self.leases.state(HARNESS, SID)["on"])

    def test_a_holder_that_lapsed_while_the_computer_slept_does_not_revive_the_lease(self) -> None:
        self.start(TAB_A)
        self.at(500)
        answer = self.leases.beat(HARNESS, SID, TAB_A)
        self.assertFalse(answer["ok"])
        self.assertEqual("left", answer["state"]["last_end"]["reason"])

    def test_a_yes_from_a_tab_that_does_not_hold_the_lease_changes_nothing(self) -> None:
        self.start(TAB_A)
        self.run_for(1300, beat=(TAB_A,))
        started = (live_monitor.window(self.config, KEY) or {})["started_at"]
        self.leases.confirm(HARNESS, SID, TAB_B, yes=True)
        self.assertEqual(started, (live_monitor.window(self.config, KEY) or {})["started_at"])


class ATickThatCannotRunBuildsNothing(Rig):
    def test_a_check_that_is_not_ready_builds_no_inputs(self) -> None:
        self.start()
        with mock.patch.object(live_monitor, "ready", return_value="busy"):
            self.run_for(30, beat=(TAB_A,))
        self.assertEqual(0, self.inputs_built)
        self.assertEqual([], self.ticks)
        self.assertTrue(self.leases.state(HARNESS, SID)["on"])

    def test_a_spent_cap_found_before_the_inputs_ends_the_lease_cap(self) -> None:
        self.start()
        with mock.patch.object(live_monitor, "ready", return_value="cap"):
            self.run_for(10, beat=(TAB_A,))
        self.assertEqual(0, self.inputs_built)
        self.assertEqual("cap", self.leases.state(HARNESS, SID)["last_end"]["reason"])


class ADuplicateRowDoesNotEndTheLease(Rig):
    def test_two_rows_skip_the_check_and_keep_the_lease(self) -> None:
        self.start()
        self.rows[(HARNESS, SID)] = {"harness": HARNESS, "sid": SID, "ambiguous": True}
        self.run_for(30, beat=(TAB_A,))
        self.assertEqual([], self.ticks)
        state = self.leases.state(HARNESS, SID)
        self.assertEqual((True, None), (state["on"], state["last_end"]))
        self.rows[(HARNESS, SID)] = {"harness": HARNESS, "sid": SID, "ended_at": None}
        self.run_for(10, beat=(TAB_A,))
        self.assertTrue(self.ticks)


class TheTickerComesAndGoesWithTheLeases(Rig):
    def _threaded(self) -> live_lease.Leases:
        fast = dataclasses.replace(self.config, live_monitor_ticker_sec=0.01)
        leases = live_lease.Leases(
            fast,
            clock=lambda: self.now,
            row_for=lambda h, s: self.rows.get((h, s)),
            inputs_for=self._inputs,
            tick=self._tick,
            start_thread=True,
        )
        self.addCleanup(leases.close)
        return leases

    def _until(self, check: Any) -> bool:
        for _ in range(300):
            if check():
                return True
            threading.Event().wait(0.01)
        return False

    def test_the_ticker_exits_when_no_lease_remains_and_returns_with_the_next_start(self) -> None:
        leases = self._threaded()
        self.assertFalse(leases.running())
        leases.start(HARNESS, SID, TAB_A)
        self.assertTrue(leases.running())
        leases.stop(HARNESS, SID, TAB_A)
        self.assertTrue(self._until(lambda: not leases.running()))
        leases.start(HARNESS, SID, TAB_A)
        self.assertTrue(leases.running())

    def test_a_table_that_was_closed_starts_nothing(self) -> None:
        leases = self._threaded()
        leases.close()
        answer = leases.start(HARNESS, SID, TAB_A)
        self.assertFalse(answer["ok"])
        self.assertFalse(leases.running())
        self.assertFalse(leases.state(HARNESS, SID)["on"])


class TheRealCheckBehindTheLease(Rig):
    """The real tick, a stub runner and a real transcript: the level reaches the lease's state."""

    def test_a_started_lease_publishes_the_haiku_level_it_earned(self) -> None:
        transcript = self.state_dir.parent / f"{self.state_dir.name}-session.jsonl"
        transcript.write_text('{"n":1}\n', encoding="utf-8")
        self.addCleanup(transcript.unlink)
        runner = FakeRunner()
        leases = live_lease.Leases(
            self.config,
            clock=lambda: self.now,
            row_for=lambda h, s: self.rows.get((h, s)),
            inputs_for=lambda *_: live_lease.Inputs(
                str(transcript), facts(), GOAL, {"level": "none_or_low", "reasons": []}
            ),
            runner=runner,
            binary_resolver=lambda _name: "/synthetic/bin/claude",
            start_thread=False,
        )
        self.addCleanup(leases.close)
        leases.start(HARNESS, SID, TAB_A)
        self.now += 10
        leases.beat(HARNESS, SID, TAB_A)
        leases.step()
        state = leases.state(HARNESS, SID)
        self.assertEqual("none_or_low", state["level"]["level"])
        self.assertEqual("Live monitor · Haiku", state["level"]["source"])
        self.assertEqual(1, len(runner.calls))


class TheTickerThread(Rig):
    def test_close_stops_the_ticker_and_cancels_a_check_in_flight(self) -> None:
        release = threading.Event()
        entered = threading.Event()

        def slow(_config: Any, _session_key: str, **_kwargs: Any) -> live_monitor.Tick:
            entered.set()
            release.wait(timeout=10)
            return live_monitor.Tick("skipped", "unchanged")

        fast = dataclasses.replace(self.config, live_monitor_ticker_sec=0.01)
        leases = live_lease.Leases(
            fast,
            clock=lambda: self.now,
            row_for=lambda h, s: self.rows.get((h, s)),
            inputs_for=lambda *_: live_lease.Inputs("/x", [], GOAL, {"level": "none_or_low"}),
            tick=slow,
            start_thread=True,
        )
        leases.start(HARNESS, SID, TAB_A)
        self.assertTrue(entered.wait(timeout=10))
        with mock.patch.object(live_monitor, "cancel_all") as cancelled:
            release.set()
            leases.close()
        cancelled.assert_called_with(fast, "stopped")
        self.assertFalse(leases.running())
        self.assertFalse(leases.state(HARNESS, SID)["on"])


if __name__ == "__main__":
    unittest.main()
