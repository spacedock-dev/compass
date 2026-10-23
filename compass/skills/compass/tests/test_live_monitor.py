"""The Live monitor's tick: admission, spacing, caps, refusals, cancellation and the reply it keeps.

[DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)
holds the rulings these tests pin. No test calls a provider: a runner is injected, or a stub
script stands in for the CLI under the real supervised runner.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import os
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    live_estimate,
    live_monitor,
    reading,
    reading_policy,
    reading_route,
    supervise,
)

from .support import make_config

NOW = 1_700_000_000.0
KEY = "claude:one"
OTHER = "claude:two"
GOAL = "Make the parser accept trailing commas."
OK_ESTIMATE = {"level": "none_or_low"}


def facts(*extra: dict[str, Any], sid: str = "one") -> list[dict[str, Any]]:
    base: list[dict[str, Any]] = [
        {"fact_id": "u1", "type": "user_message", "at": NOW - 90, "reader_words": GOAL},
        {
            "fact_id": "a1",
            "type": reading.AGENT_MESSAGE_TYPE,
            "at": NOW - 60,
            reading.AGENT_WORDS_FIELD: "I changed the tokenizer.",
        },
        {
            "fact_id": "c1",
            "type": "tool_report",
            "subject": "check",
            "summary": "pytest -q",
            "result": "passed",
            "at": NOW - 30,
        },
    ]
    return [
        {"source_session": {"harness": "claude", "sid": sid}, **fact} for fact in [*base, *extra]
    ]


def reply(
    level: str = "none_or_low",
    reason: str = "The latest turns ran a check.",
    cites: tuple[int, ...] = (1,),
) -> str:
    return json.dumps({"level": level, "reason": reason, "cites": list(cites)})


class FakeGroup:
    def __init__(self) -> None:
        self.cancelled = threading.Event()

    def cancel(self) -> None:
        self.cancelled.set()


class FakeRunner:
    """Stands in for `supervise.run`: records each call, and may hold it until cancelled."""

    def __init__(self, text: str = "", *, hold: bool = False, release_delay: float = 0.0) -> None:
        self.text = text or reply()
        self.hold = hold
        self.release_delay = release_delay
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.started = threading.Event()
        self.groups: list[FakeGroup] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append((argv, kwargs))
        group = FakeGroup()
        self.groups.append(group)
        spawned = kwargs.get("on_spawn")
        if spawned is not None:
            spawned(group)
        self.started.set()
        if self.hold:
            group.cancelled.wait(timeout=10)
            threading.Event().wait(self.release_delay)
            return subprocess.CompletedProcess(argv, -15)
        kwargs["stdout"].write(self.text.encode())
        return subprocess.CompletedProcess(argv, 0)


class Case(unittest.TestCase):
    def setUp(self) -> None:
        home, state = tempfile.TemporaryDirectory(), tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.addCleanup(state.cleanup)
        self.home = Path(home.name)
        self.config = dataclasses.replace(
            make_config(), state_dir=Path(state.name), live_monitor_daily_cap=50
        )
        self.extra: list[dict[str, Any]] = []
        self.transcript = self.home / "session.jsonl"
        self.transcript.write_text('{"n":1}\n', encoding="utf-8")
        self.runner = FakeRunner()
        # The route's own answer, so the destination the tick names is the one it re-checks.
        patch = mock.patch.object(reading_route, "destination", return_value="api.anthropic.com")
        patch.start()
        self.addCleanup(patch.stop)

    def touch(self) -> None:
        """The transcript changes and nothing new is said in it."""
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write('{"n":2}\n')
        stamp = self.transcript.stat().st_mtime_ns + 1_000_000
        os.utime(self.transcript, ns=(stamp, stamp))

    def grow(self) -> None:
        """The transcript changes and the reader says something new in it."""
        self.touch()
        number = len(self.extra) + 1
        self.extra.append(
            {
                "fact_id": f"later{number}",
                "type": "user_message",
                "at": NOW + number,
                "reader_words": f"Another instruction {number}.",
            }
        )

    def begin(self, key: str = KEY, now: float = NOW) -> None:
        live_monitor.begin_window(self.config, key, now=now)

    def tick(
        self,
        now: float = NOW,
        *,
        key: str = KEY,
        runner: Any = None,
        estimate: dict[str, Any] | None = None,
        turns: list[dict[str, Any]] | None = None,
        config: Any = None,
        ended: bool = False,
    ) -> live_monitor.Tick:
        sid = key.partition(":")[2]
        return live_monitor.tick(
            config or self.config,
            key,
            now=now,
            transcript_path=str(self.transcript),
            facts=turns if turns is not None else facts(*self.extra, sid=sid),
            intent=GOAL,
            estimate=estimate or OK_ESTIMATE,
            runner=runner or self.runner,
            binary_resolver=lambda _name: "/synthetic/bin/claude",
            ended=ended,
        )


class SpacingAndTheReadingSlot(Case):
    def test_two_checks_of_one_session_never_start_less_than_sixty_seconds_apart(self) -> None:
        self.begin()
        self.assertEqual("ran", self.tick(NOW).status)
        self.grow()
        early = self.tick(NOW + 59.9)
        self.assertEqual(("refused", "too-soon"), (early.status, early.reason))
        self.assertEqual(1, len(self.runner.calls))
        late = self.tick(NOW + 60.0)
        self.assertEqual("ran", late.status)
        self.assertEqual(2, len(self.runner.calls))

    def test_no_check_starts_while_an_analyze_reading_holds_the_slot(self) -> None:
        self.begin()
        self.assertTrue(reading.claim(self.config, KEY))
        self.addCleanup(reading.release, self.config, KEY)
        held = self.tick(NOW)
        self.assertEqual(("refused", "busy"), (held.status, held.reason))
        self.assertEqual([], self.runner.calls)
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW)["used"])

    def test_the_slot_is_given_back_after_a_check(self) -> None:
        self.begin()
        self.tick(NOW)
        self.assertTrue(reading.claim(self.config, KEY))
        reading.release(self.config, KEY)

    def test_an_analyze_press_cancels_a_tick_that_holds_the_slot_and_takes_it(self) -> None:
        self.begin()
        runner = FakeRunner(hold=True)
        results: list[live_monitor.Tick] = []
        thread = threading.Thread(target=lambda: results.append(self.tick(NOW, runner=runner)))
        thread.start()
        self.assertTrue(runner.started.wait(timeout=10))
        self.assertTrue(live_monitor.preempt(self.config, KEY, wait_sec=10.0))
        # The press can now take the slot, because the tick has let go of it.
        self.assertTrue(reading.claim(self.config, KEY))
        reading.release(self.config, KEY)
        thread.join(timeout=10)
        self.assertEqual(("cancelled", "analyze"), (results[0].status, results[0].reason))
        self.assertIsNone(results[0].level)
        # The reserved spend is not refunded: the call had left.
        self.assertEqual(1, reading_policy.monitor_status(self.config, now=NOW)["used"])

    def test_preempt_does_nothing_when_no_tick_holds_the_slot(self) -> None:
        self.begin()
        self.assertFalse(live_monitor.preempt(self.config, KEY, wait_sec=0.1))
        self.assertTrue(reading.claim(self.config, KEY))
        self.assertFalse(live_monitor.preempt(self.config, KEY, wait_sec=0.1))
        reading.release(self.config, KEY)

    def test_the_board_runs_one_check_at_a_time(self) -> None:
        self.begin()
        self.begin(OTHER)
        runner = FakeRunner(hold=True)
        thread = threading.Thread(target=lambda: self.tick(NOW, runner=runner))
        thread.start()
        self.assertTrue(runner.started.wait(timeout=10))
        second = self.tick(NOW, key=OTHER)
        self.assertEqual(("refused", "busy"), (second.status, second.reason))
        live_monitor.cancel_all(self.config, "model-calls-paused")
        thread.join(timeout=10)


class AnUnchangedTranscriptCostsNothing(Case):
    def test_no_level_exists_until_a_tick_completes(self) -> None:
        self.begin()
        self.assertIsNone(live_monitor.published(self.config, KEY))
        empty = self.tick(NOW, turns=[])
        self.assertEqual(("skipped", "no-new-turns"), (empty.status, empty.reason))
        self.assertIsNone(live_monitor.published(self.config, KEY))
        self.assertEqual([], self.runner.calls)

    def test_a_tick_that_ran_and_found_nothing_differs_from_one_that_never_ran(self) -> None:
        self.begin()
        self.assertIsNone(live_monitor.published(self.config, KEY))
        self.tick(NOW)
        level = live_monitor.published(self.config, KEY)
        assert level is not None
        self.assertEqual("none_or_low", level["level"])
        self.assertEqual((1, 0), (level["checks"], level["findings"]))

    def test_an_unchanged_transcript_makes_no_call_charges_nothing_and_counts_nothing(
        self,
    ) -> None:
        self.begin()
        self.tick(NOW)
        before = live_monitor.published(self.config, KEY)
        skipped = self.tick(NOW + 120)
        self.assertEqual(("skipped", "unchanged"), (skipped.status, skipped.reason))
        self.assertIsNone(skipped.level)
        self.assertEqual(1, len(self.runner.calls))
        self.assertEqual(1, reading_policy.monitor_status(self.config, now=NOW + 121)["used"])
        self.assertEqual(before, live_monitor.published(self.config, KEY))
        # And the skip did not count against the session's window or the interval floor.
        self.grow()
        self.assertEqual("ran", self.tick(NOW + 125).status)

    def test_a_changed_transcript_with_nothing_new_to_say_is_skipped_too(self) -> None:
        self.begin()
        self.tick(NOW)
        self.touch()
        skipped = self.tick(NOW + 120)
        self.assertEqual(("skipped", "no-new-turns"), (skipped.status, skipped.reason))
        self.assertEqual(1, len(self.runner.calls))

    def test_a_later_tick_resends_the_recent_window_so_one_quiet_turn_cannot_flip_the_level(
        self,
    ) -> None:
        self.begin()
        self.tick(NOW)
        self.grow()
        fresh = {
            "fact_id": "u2",
            "type": "user_message",
            "at": NOW + 70,
            "reader_words": "ok",
            "source_session": {"harness": "claude", "sid": "one"},
        }
        self.tick(NOW + 120, turns=facts(fresh))
        sent = self.runner.calls[1][1]["input"]
        # The check sees the earlier turns beside the new one, so a one-word turn does not
        # stand alone as the whole of what Haiku read.
        self.assertIn("I changed the tokenizer.", sent)
        self.assertIn("pytest -q: passed", sent)
        self.assertLess(sent.index("I changed the tokenizer."), sent.rindex("ok"))

    def test_the_resent_window_is_bounded_by_the_prompt_cap(self) -> None:
        capped = dataclasses.replace(self.config, live_monitor_prompt_cap_chars=500)
        live_monitor.begin_window(capped, KEY, now=NOW)
        for index in range(6):
            self.touch()
            turn = {
                "fact_id": f"big{index}",
                "type": "user_message",
                "at": NOW + index,
                "reader_words": f"turn{index} " + "Q" * 300,
                "source_session": {"harness": "claude", "sid": "one"},
            }
            self.tick(NOW + 60 * index, turns=[turn], config=capped)
        for _argv, kwargs in self.runner.calls:
            self.assertLessEqual(kwargs["input"].count("Q"), 500)
        self.assertIn("turn5", self.runner.calls[-1][1]["input"])

    def test_an_unsaved_intent_is_never_checked(self) -> None:
        self.begin()
        result = live_monitor.tick(
            self.config,
            KEY,
            now=NOW,
            transcript_path=str(self.transcript),
            facts=facts(),
            intent="",
            estimate=OK_ESTIMATE,
            runner=self.runner,
            binary_resolver=lambda _name: "/synthetic/bin/claude",
        )
        self.assertEqual(("skipped", "no-intent"), (result.status, result.reason))
        self.assertEqual([], self.runner.calls)


class TheCaps(Case):
    def test_a_session_stops_after_its_cap_in_one_window(self) -> None:
        capped = dataclasses.replace(self.config, live_monitor_session_tick_cap=3)
        live_monitor.begin_window(capped, KEY, now=NOW)
        for index in range(3):
            self.grow()
            self.assertEqual("ran", self.tick(NOW + 60 * index, config=capped).status)
        self.grow()
        stopped = self.tick(NOW + 180, config=capped)
        self.assertEqual(("refused", "cap"), (stopped.status, stopped.reason))
        self.assertEqual(3, len(self.runner.calls))

    def test_a_fresh_window_restores_the_session_cap(self) -> None:
        capped = dataclasses.replace(self.config, live_monitor_session_tick_cap=1)
        live_monitor.begin_window(capped, KEY, now=NOW)
        self.assertEqual("ran", self.tick(NOW, config=capped).status)
        self.grow()
        self.assertEqual("cap", self.tick(NOW + 60, config=capped).reason)
        live_monitor.begin_window(capped, KEY, now=NOW + 61, renew=True)
        self.assertEqual("ran", self.tick(NOW + 122, config=capped).status)

    def test_the_board_stops_at_its_rolling_cap_whichever_session_asks(self) -> None:
        capped = dataclasses.replace(self.config, live_monitor_daily_cap=2)
        live_monitor.begin_window(capped, KEY, now=NOW)
        live_monitor.begin_window(capped, OTHER, now=NOW)
        self.assertEqual("ran", self.tick(NOW, config=capped).status)
        self.assertEqual("ran", self.tick(NOW + 1, key=OTHER, config=capped).status)
        self.grow()
        stopped = self.tick(NOW + 61, config=capped)
        self.assertEqual(("refused", "cap"), (stopped.status, stopped.reason))
        # Analyze's own budget is untouched by every tick above.
        reserved = reading_policy.reserve(capped, now=NOW + 62, provider="claude")
        self.assertEqual(("", 1), (reserved["reason"], reserved["used"]))

    def test_a_window_ends_when_its_clock_runs_out(self) -> None:
        self.begin()
        over = self.tick(NOW + self.config.live_monitor_window_sec)
        self.assertEqual(("refused", "window-ended"), (over.status, over.reason))

    def test_a_session_with_no_window_is_not_monitored(self) -> None:
        refused = self.tick(NOW)
        self.assertEqual(("refused", "not-monitored"), (refused.status, refused.reason))
        self.assertEqual([], self.runner.calls)


class RefusalsPrecedeEverything(Case):
    def test_pause_refuses_without_a_call_a_charge_or_a_notice(self) -> None:
        self.begin()
        reading_policy.set_consent(self.config, False, now=NOW)
        refused = self.tick(NOW + 1)
        self.assertEqual(("refused", "model-calls-paused"), (refused.status, refused.reason))
        self.assertEqual([], self.runner.calls)
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW + 2)["used"])
        self.assertEqual({}, reading_policy.status(self.config, now=NOW + 2)["notices"])

    def test_no_observer_model_refuses_every_check(self) -> None:
        off = dataclasses.replace(self.config, model_calls_disabled=True)
        live_monitor.begin_window(off, KEY, now=NOW)
        refused = self.tick(NOW + 1, config=off)
        self.assertEqual(("refused", "run-disabled"), (refused.status, refused.reason))
        self.assertEqual([], self.runner.calls)

    def test_an_unreadable_store_refuses_and_says_so(self) -> None:
        blocked = dataclasses.replace(self.config, state_dir=Path("/nonexistent-compass/none"))
        live_monitor.begin_window(blocked, KEY, now=NOW)
        refused = self.tick(NOW + 1, config=blocked)
        self.assertEqual(("refused", "store-unavailable"), (refused.status, refused.reason))
        self.assertEqual([], self.runner.calls)

    def test_pause_kills_a_check_in_flight_and_its_reply_cannot_publish(self) -> None:
        self.begin()
        runner = FakeRunner(hold=True)
        results: list[live_monitor.Tick] = []
        thread = threading.Thread(target=lambda: results.append(self.tick(NOW, runner=runner)))
        thread.start()
        self.assertTrue(runner.started.wait(timeout=10))
        self.assertEqual(1, live_monitor.cancel_all(self.config, "model-calls-paused"))
        thread.join(timeout=10)
        self.assertTrue(runner.groups[0].cancelled.is_set())
        self.assertEqual(
            ("cancelled", "model-calls-paused"), (results[0].status, results[0].reason)
        )
        self.assertIsNone(live_monitor.published(self.config, KEY))
        # Released, so the next press or tick can take the slot.
        self.assertTrue(reading.claim(self.config, KEY))
        reading.release(self.config, KEY)


class OnlyThisSessionsFactsAreSent(Case):
    def test_another_sessions_facts_and_unlabelled_ones_are_never_sent(self) -> None:
        self.begin()
        elsewhere = {
            "fact_id": "x1",
            "type": "user_message",
            "at": NOW - 5,
            "reader_words": "From another session entirely.",
            "source_session": {"harness": "claude", "sid": "two"},
        }
        unlabelled = {
            "fact_id": "x2",
            "type": "user_message",
            "at": NOW - 4,
            "reader_words": "From nowhere in particular.",
        }
        self.tick(NOW, turns=[*facts(), elsewhere, unlabelled])
        sent = self.runner.calls[0][1]["input"]
        self.assertNotIn("another session entirely", sent)
        self.assertNotIn("nowhere in particular", sent)
        self.assertIn("I changed the tokenizer.", sent)


class TheLeaseInterface(Case):
    def test_the_window_accessor_holds_the_only_clock(self) -> None:
        self.assertIsNone(live_monitor.window(self.config, KEY))
        self.begin()
        self.assertEqual(
            {
                "started_at": NOW,
                "banner_due_at": NOW + 1200.0,
                "deadline": NOW + 1800.0,
            },
            live_monitor.window(self.config, KEY),
        )
        self.assertEqual(1200.0, self.config.live_monitor_banner_sec)

    def test_one_tab_leaving_does_not_stop_another_tabs_monitor(self) -> None:
        live_monitor.begin_window(self.config, KEY, now=NOW, holder="tab-a")
        live_monitor.begin_window(self.config, KEY, now=NOW + 5, holder="tab-b")
        # A second tab does not move the first one's clock.
        self.assertEqual(NOW, (live_monitor.window(self.config, KEY) or {})["started_at"])
        self.assertFalse(live_monitor.end(self.config, KEY, holder="tab-a"))
        self.assertEqual("ran", self.tick(NOW + 10).status)
        self.assertTrue(live_monitor.end(self.config, KEY, holder="tab-b"))
        self.assertEqual("not-monitored", self.tick(NOW + 80).reason)
        self.assertIsNone(live_monitor.published(self.config, KEY))

    def test_a_yes_resets_the_clock_and_the_tick_count_before_the_deadline(self) -> None:
        capped = dataclasses.replace(self.config, live_monitor_session_tick_cap=1)
        live_monitor.begin_window(capped, KEY, now=NOW)
        self.assertEqual("ran", self.tick(NOW, config=capped).status)
        self.grow()
        self.assertEqual("cap", self.tick(NOW + 60, config=capped).reason)
        self.assertTrue(live_monitor.begin_window(capped, KEY, now=NOW + 1199, renew=True))
        self.assertEqual(NOW + 1199, (live_monitor.window(capped, KEY) or {})["started_at"])
        self.assertEqual("ran", self.tick(NOW + 1260, config=capped).status)

    def test_a_yes_after_the_deadline_is_refused_and_the_monitor_is_off(self) -> None:
        self.begin()
        self.tick(NOW)
        self.assertFalse(live_monitor.begin_window(self.config, KEY, now=NOW + 1800, renew=True))
        self.assertIsNone(live_monitor.window(self.config, KEY))
        self.assertIsNone(live_monitor.published(self.config, KEY))
        # A fresh start is the reader switching it on again, which is allowed.
        self.assertTrue(live_monitor.begin_window(self.config, KEY, now=NOW + 1900))

    def test_a_yes_for_a_session_not_monitored_is_refused(self) -> None:
        self.assertFalse(live_monitor.begin_window(self.config, KEY, now=NOW, renew=True))

    def test_a_window_that_runs_out_drops_its_entry_and_its_level(self) -> None:
        self.begin()
        self.tick(NOW)
        self.assertIsNotNone(live_monitor.published(self.config, KEY))
        over = self.tick(NOW + self.config.live_monitor_window_sec)
        self.assertEqual("window-ended", over.reason)
        self.assertIsNone(live_monitor.published(self.config, KEY))
        self.assertIsNone(live_monitor.window(self.config, KEY))

    def test_an_ended_session_refuses_and_turns_the_monitor_off(self) -> None:
        self.begin()
        self.tick(NOW)
        refused = self.tick(NOW + 60, ended=True)
        self.assertEqual(("refused", "session-ended"), (refused.status, refused.reason))
        self.assertEqual(1, len(self.runner.calls))
        self.assertIsNone(live_monitor.published(self.config, KEY))
        self.assertIsNone(live_monitor.window(self.config, KEY))

    def test_an_end_between_the_gate_and_the_slot_neither_launches_nor_charges(self) -> None:
        self.begin()
        real = live_estimate._live_signature

        def ending(config: Any, path: str) -> Any:
            live_monitor.end(config, KEY)
            return real(config, path)

        with mock.patch.object(live_estimate, "_live_signature", ending):
            result = self.tick(NOW)
        self.assertEqual(("refused", "not-monitored"), (result.status, result.reason))
        self.assertEqual([], self.runner.calls)
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW + 1)["used"])
        self.assertTrue(reading.claim(self.config, KEY))
        reading.release(self.config, KEY)


class AnAnalyzePressIsNeverRefusedBecauseOfATick(Case):
    def test_the_wait_covers_a_tick_that_is_queued_behind_the_stores_write_lock(self) -> None:
        self.assertGreaterEqual(live_monitor.PRESS_WAIT_SEC, reading_policy.WRITE_WAIT_SEC + 5)

    def test_a_tick_cannot_take_the_slot_between_the_cancel_and_the_press(self) -> None:
        self.begin()
        seen: list[live_monitor.Tick] = []

        def start() -> str:
            # The press has not taken the slot yet: a tick arriving now must be turned away.
            seen.append(self.tick(NOW))
            return "job"

        self.assertEqual("job", live_monitor.start_with_priority(self.config, KEY, start))
        self.assertEqual(("refused", "busy"), (seen[0].status, seen[0].reason))
        self.assertEqual([], self.runner.calls)
        # And the mark is gone afterwards.
        self.assertEqual("ran", self.tick(NOW + 61).status)

    def test_a_slow_release_is_waited_for_and_the_start_is_retried_once(self) -> None:
        self.begin()
        runner = FakeRunner(hold=True, release_delay=0.6)
        thread = threading.Thread(target=lambda: self.tick(NOW, runner=runner))
        thread.start()
        self.assertTrue(runner.started.wait(timeout=10))
        attempts: list[bool] = []

        def start() -> str | None:
            taken = reading.claim(self.config, KEY)
            attempts.append(taken)
            return "job" if taken else None

        with mock.patch.object(live_monitor, "PRESS_WAIT_SEC", 0.4):
            job = live_monitor.start_with_priority(self.config, KEY, start)
        thread.join(timeout=10)
        self.assertEqual("job", job)
        self.assertEqual([False, True], attempts)
        reading.release(self.config, KEY)

    def test_with_no_tick_the_start_is_tried_once(self) -> None:
        calls: list[int] = []

        def start() -> None:
            calls.append(1)

        self.assertIsNone(live_monitor.start_with_priority(self.config, KEY, start))
        self.assertEqual([1], calls)


class ReservationBeforeLaunch(Case):
    def test_a_charge_is_made_before_the_child_starts_and_is_kept_when_it_fails(self) -> None:
        self.begin()
        seen: list[int] = []

        def runner(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[Any]:
            seen.append(reading_policy.monitor_status(self.config, now=NOW + 1)["used"])
            return subprocess.CompletedProcess(argv, 1)

        failed = self.tick(NOW, runner=runner)
        self.assertEqual([1], seen)
        self.assertEqual(("failed", "failed"), (failed.status, failed.reason))
        self.assertEqual(1, reading_policy.monitor_status(self.config, now=NOW + 2)["used"])
        self.assertIsNone(live_monitor.published(self.config, KEY))

    def test_a_cli_that_is_not_installed_charges_nothing_and_withdraws_the_notice(self) -> None:
        self.begin()
        result = live_monitor.tick(
            self.config,
            KEY,
            now=NOW,
            transcript_path=str(self.transcript),
            facts=facts(),
            intent=GOAL,
            estimate=OK_ESTIMATE,
            runner=self.runner,
            binary_resolver=lambda _name: None,
        )
        self.assertEqual(("refused", "unavailable"), (result.status, result.reason))
        self.assertEqual(0, reading_policy.monitor_status(self.config, now=NOW + 1)["used"])
        self.assertEqual({}, reading_policy.status(self.config, now=NOW + 1)["notices"])


class TheNoticeAndTheProvenance(Case):
    def test_the_first_charged_tick_carries_the_monitor_notice_and_it_is_on_record_first(
        self,
    ) -> None:
        self.begin()
        on_record: list[bool] = []

        def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
            notices = reading_policy.status(self.config, now=NOW + 1)["notices"]
            on_record.append("monitor" in notices)
            kwargs["stdout"].write(reply().encode())
            return subprocess.CompletedProcess(argv, 0)

        first = self.tick(NOW, runner=runner)
        self.assertEqual([True], on_record)
        assert first.notice is not None
        self.assertEqual(("monitor", "claude"), (first.notice["kind"], first.notice["provider"]))
        self.assertIn("api.anthropic.com", first.disclosure)
        self.assertIn("Pause model calls", first.disclosure)
        self.grow()
        self.assertIsNone(self.tick(NOW + 60, runner=runner).notice)

    def test_the_disclosure_names_what_is_sent_and_where(self) -> None:
        text = live_monitor.disclosure("api.anthropic.com")
        for phrase in (
            "Haiku",
            "api.anthropic.com",
            "once a minute",
            "commands of checks with their result",
            "paths of files written",
            "sent again",
            "turned off and on",
            "redacted",
            "Pause model calls",
        ):
            self.assertIn(phrase, text)
        self.assertNotIn("No command", text)

    def test_the_notice_names_the_tool_output_class_as_analyze_does(self) -> None:
        self.begin()
        first = self.tick(NOW)
        assert first.notice is not None
        self.assertEqual("api.anthropic.com", first.notice["tool_output"])

    def test_with_no_nameable_destination_checks_and_paths_are_not_sent(self) -> None:
        self.begin()
        self.extra.append(
            {
                "fact_id": "w1",
                "type": "tool_report",
                "subject": "write",
                "summary": "src/p.py",
                "at": NOW - 10,
            }
        )
        with mock.patch.object(reading_route, "destination", return_value=""):
            first = self.tick(NOW)
        sent = self.runner.calls[0][1]["input"]
        self.assertNotIn("pytest -q", sent)
        self.assertNotIn("src/p.py", sent)
        self.assertIn(GOAL.split(maxsplit=1)[0], sent)
        self.assertIn("I changed the tokenizer.", sent)
        assert first.notice is not None
        self.assertEqual("", first.notice["tool_output"])
        self.assertNotIn("commands of checks", first.disclosure)

    def test_each_tick_records_the_model_it_asked_for(self) -> None:
        self.begin()
        result = self.tick(NOW)
        self.assertEqual(live_monitor.provenance(self.config), result.provenance)
        assert result.level is not None
        self.assertEqual("claude-haiku-5-5", result.level["provenance"]["selected_model"])
        self.assertEqual("Live monitor · Haiku", result.level["source"])
        argv = self.runner.calls[0][0]
        self.assertEqual("claude-haiku-5-5", argv[argv.index("--model") + 1])


class TheReplyIsHeldToTheShapeContract(Case):
    def _ran(self, text: str, *, estimate: dict[str, Any] | None = None) -> live_monitor.Tick:
        self.begin()
        return self.tick(NOW, runner=FakeRunner(text), estimate=estimate)

    def test_a_drift_level_with_a_citation_is_published_beside_the_fallback(self) -> None:
        result = self._ran(
            reply("medium", "The latest turns wrote outside the saved folders.", (2,)),
            estimate={"level": "not_enough"},
        )
        assert result.level is not None
        self.assertEqual("medium", result.level["level"])
        self.assertEqual("not_enough", result.level["fallback"])
        self.assertEqual(["a1"], [cite["fact_id"] for cite in result.level["cites"]])
        self.assertEqual((1, 1), (result.level["checks"], result.level["findings"]))

    def test_the_owners_case_a_pull_request_and_no_check_still_reads_none_or_low(self) -> None:
        # No check ran, so the estimate has too little (no passing check). That does not block
        # Haiku's own None or low when it cites a turn it was sent.
        result = self._ran(
            reply("none_or_low", "A pull request was opened and nothing else moved.", (2,)),
            estimate={
                "level": "not_enough",
                "reasons": ["no-passing-check", "intent-names-no-folder"],
            },
        )
        assert result.level is not None
        self.assertEqual("none_or_low", result.level["level"])
        self.assertFalse(result.level["floor_applied"])

    def test_a_failed_check_or_an_unsettled_direction_blocks_the_models_none_or_low(self) -> None:
        for reasons, expected in (
            (["failed-check"], "not_enough"),
            (["later-direction", "no-passing-check"], "not_enough"),
        ):
            with self.subTest(reasons=reasons):
                live_monitor._SESSIONS.clear()
                result = self._ran(
                    reply("none_or_low"), estimate={"level": "not_enough", "reasons": reasons}
                )
                assert result.level is not None
                self.assertEqual(expected, result.level["level"])
                self.assertTrue(result.level["floor_applied"])

    def test_the_other_blockers_of_the_estimate_do_not_block_it(self) -> None:
        # The shell-command blocker is the live estimate's own (DEC-26 item 1 names it for
        # "the live estimate", not for every source), so it does not bind a model level.
        for reasons in (
            ["command-after-pass"],
            ["check-not-recorded"],
            ["background-run", "entries-not-listed"],
            ["scan-incomplete"],
        ):
            with self.subTest(reasons=reasons):
                live_monitor._SESSIONS.clear()
                result = self._ran(
                    reply("none_or_low"), estimate={"level": "not_enough", "reasons": reasons}
                )
                assert result.level is not None
                self.assertEqual("none_or_low", result.level["level"])

    def test_the_floor_works_both_ways_a_higher_estimate_is_never_hidden(self) -> None:
        failed = {"level": "high", "reasons": ["failed-check"]}
        for model, estimate, expected in (
            ("medium", failed, "high"),
            ("not_enough", failed, "high"),
            ("none_or_low", failed, "high"),
            ("medium", {"level": "extreme", "reasons": ["failed-check"]}, "extreme"),
            ("high", {"level": "medium", "reasons": ["pass-then-write"]}, "high"),
            ("medium", {"level": "none_or_low", "reasons": ["floor-met"]}, "medium"),
            ("not_enough", {"level": "none_or_low", "reasons": ["floor-met"]}, "not_enough"),
            ("not_enough", {"level": "not_enough", "reasons": []}, "not_enough"),
        ):
            with self.subTest(model=model, estimate=estimate["level"]):
                live_monitor._SESSIONS.clear()
                cites = () if model == "not_enough" else (1,)
                result = self._ran(reply(model, "A turn moved.", cites), estimate=estimate)
                assert result.level is not None
                self.assertEqual(expected, result.level["level"])
                self.assertEqual(model, result.level["model_level"])

    def test_a_reply_that_states_a_verdict_is_refused(self) -> None:
        result = self._ran(reply("none_or_low", "The work is complete and every goal was met."))
        self.assertEqual(("failed", "verdict-stated"), (result.status, result.reason))
        self.assertIsNone(live_monitor.published(self.config, KEY))

    def test_a_success_word_is_a_verdict_however_it_is_qualified(self) -> None:
        for reason in (
            "PR opened; goal achieved, no problems",
            "Goal achieved with no drift.",
            "The work is completed and nothing is missing.",
            "Everything works and no check failed.",
        ):
            with self.subTest(reason=reason):
                live_monitor._SESSIONS.clear()
                result = self._ran(reply("none_or_low", reason))
                self.assertEqual(("failed", "verdict-stated"), (result.status, result.reason))
                self.assertIsNone(live_monitor.published(self.config, KEY))

    def test_malformed_replies_publish_nothing(self) -> None:
        bad = (
            "not json",
            json.dumps(["level"]),
            json.dumps({"level": "severe", "reason": "x", "cites": [1]}),
            json.dumps({"level": "no_live_level", "reason": "x", "cites": [1]}),
            json.dumps({"level": "high", "reason": "x", "cites": [1], "extra": 1}),
            json.dumps({"level": "high", "reason": "x" * 400, "cites": [1]}),
            json.dumps({"level": "high", "reason": "line\nbreak", "cites": [1]}),
            json.dumps({"level": "high", "reason": "x", "cites": []}),
            json.dumps({"level": "high", "reason": "x", "cites": [99]}),
            json.dumps({"level": "high", "reason": "x", "cites": [True]}),
        )
        for text in bad:
            with self.subTest(text=text[:40]):
                live_monitor._SESSIONS.clear()
                result = self._ran(text)
                self.assertEqual(("failed", "malformed"), (result.status, result.reason))
                self.assertIsNone(live_monitor.published(self.config, KEY))

    def test_not_enough_may_cite_nothing(self) -> None:
        result = self._ran(reply("not_enough", "Too little recorded to say.", ()))
        assert result.level is not None
        self.assertEqual("not_enough", result.level["level"])

    def test_the_prompt_treats_the_turns_as_data_and_is_bounded(self) -> None:
        capped = dataclasses.replace(self.config, live_monitor_prompt_cap_chars=600)
        live_monitor.begin_window(capped, KEY, now=NOW)
        long_run = [
            {
                "fact_id": f"u{n}",
                "type": "user_message",
                "at": NOW - n,
                "reader_words": "Q" * 300,
                "source_session": {"harness": "claude", "sid": "one"},
            }
            for n in range(1, 9)
        ]
        self.tick(NOW, turns=long_run, config=capped)
        sent = self.runner.calls[0][1]["input"]
        self.assertIn("untrusted", sent)
        self.assertLessEqual(sent.count("Q"), 600)
        self.assertGreater(sent.count("Q"), 0)

    def test_a_secret_in_a_turn_is_not_sent(self) -> None:
        self.begin()
        # A shape-matching value built at run time, so no such value sits in this file.
        secret = "AKIA" + "ZZZZZZZZZZZZZZZZ"
        leak = {
            "fact_id": "u9",
            "type": "user_message",
            "at": NOW - 1,
            "reader_words": f"use {secret} for the upload",
        }
        self.tick(NOW, turns=facts(leak))
        self.assertNotIn(secret, self.runner.calls[0][1]["input"])


class TheChildIsSupervisedAndTheSessionIsNeverTouched(Case):
    def test_nothing_is_written_into_or_resumed_in_the_watched_session(self) -> None:
        self.begin()
        digest = hashlib.sha256(self.transcript.read_bytes()).hexdigest()
        before = sorted(p.name for p in self.home.iterdir())
        self.tick(NOW)
        argv, kwargs = self.runner.calls[0]
        for flag in ("--resume", "--continue", "--session-id", "--fork-session"):
            self.assertNotIn(flag, argv)
        self.assertIn("--no-session-persistence", argv)
        self.assertEqual("", argv[argv.index("--tools") + 1])
        self.assertNotEqual(str(self.home), kwargs["cwd"])
        self.assertEqual(digest, hashlib.sha256(self.transcript.read_bytes()).hexdigest())
        self.assertEqual(before, sorted(p.name for p in self.home.iterdir()))

    def test_the_default_runner_is_the_supervised_one(self) -> None:
        import inspect  # noqa: PLC0415

        default = inspect.signature(live_monitor.tick).parameters["runner"].default
        self.assertIs(supervise.run, default)
        self.assertIs(
            supervise.run, inspect.signature(live_monitor.prepare).parameters["runner"].default
        )

    def test_a_real_supervised_child_is_killed_by_cancel_and_leaves_nothing(self) -> None:
        stub = self.home / "claude"
        marker = self.home / "child.pid"
        stub.write_text(f"#!/bin/sh\necho $$ > {marker}\nexec sleep 30\n", encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.begin()
        results: list[live_monitor.Tick] = []

        def run() -> None:
            results.append(
                live_monitor.tick(
                    self.config,
                    KEY,
                    now=NOW,
                    transcript_path=str(self.transcript),
                    facts=facts(),
                    intent=GOAL,
                    estimate=OK_ESTIMATE,
                    binary_resolver=lambda _name: str(stub),
                )
            )

        thread = threading.Thread(target=run)
        thread.start()
        for _ in range(200):
            if marker.exists() and marker.read_text().strip():
                break
            threading.Event().wait(0.05)
        pid = int(marker.read_text().strip())
        self.assertEqual(1, live_monitor.cancel_all(self.config, "model-calls-paused"))
        thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertEqual("cancelled", results[0].status)
        self.assertEqual([], list((self.config.state_dir).glob("reading-claude-*")))


class TheMonitorNeverTouchesTheUnaskedLaneOrNotifications(Case):
    def test_the_module_imports_neither_the_lane_nor_notifications(self) -> None:
        source = Path(live_monitor.__file__).read_text(encoding="utf-8")
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                imported.update(alias.name for alias in node.names)
                imported.add(node.module or "")
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        for name in ("unasked", "notifications", "deliveries", "reach"):
            self.assertNotIn(name, imported)

    def test_a_tick_spends_no_unasked_budget_and_publishes_no_notification_field(self) -> None:
        self.begin()
        result = self.tick(NOW)
        assert result.level is not None
        self.assertFalse({"notify", "notification", "attention"} & set(result.level))
        self.assertEqual(0, reading_policy.status(self.config, now=NOW + 1)["used"])
        answer = reading_policy.unasked_status(
            self.config, now=NOW + 1, provider="claude", destination="api.anthropic.com"
        )
        self.assertEqual("run-disabled", answer["reason"])

    def test_the_slot_it_takes_is_the_one_the_unasked_lane_asks_for(self) -> None:
        self.begin()
        runner = FakeRunner(hold=True)
        thread = threading.Thread(target=lambda: self.tick(NOW, runner=runner))
        thread.start()
        self.assertTrue(runner.started.wait(timeout=10))
        # The lane's `claim` is refused while a tick holds the slot, so a tick can never feed it.
        self.assertFalse(reading.claim(self.config, KEY))
        live_monitor.cancel_all(self.config, "model-calls-paused")
        thread.join(timeout=10)


if __name__ == "__main__":
    unittest.main()
