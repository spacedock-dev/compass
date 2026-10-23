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

from compass_runtime import live_monitor, reading, reading_policy, reading_route, supervise

from .support import make_config

NOW = 1_700_000_000.0
KEY = "claude:one"
OTHER = "claude:two"
GOAL = "Make the parser accept trailing commas."
OK_ESTIMATE = {"level": "none_or_low"}


def facts(*extra: dict[str, Any]) -> list[dict[str, Any]]:
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
    return [*base, *extra]


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

    def __init__(self, text: str = "", *, hold: bool = False) -> None:
        self.text = text or reply()
        self.hold = hold
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
    ) -> live_monitor.Tick:
        return live_monitor.tick(
            config or self.config,
            key,
            now=now,
            transcript_path=str(self.transcript),
            facts=turns if turns is not None else facts(*self.extra),
            intent=GOAL,
            estimate=estimate or OK_ESTIMATE,
            runner=runner or self.runner,
            binary_resolver=lambda _name: "/synthetic/bin/claude",
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

    def test_only_the_turns_since_the_last_check_are_sent(self) -> None:
        self.begin()
        self.tick(NOW)
        self.grow()
        fresh = {
            "fact_id": "u2",
            "type": "user_message",
            "at": NOW + 70,
            "reader_words": "Also add tests.",
        }
        self.tick(NOW + 120, turns=facts(fresh))
        sent = self.runner.calls[1][1]["input"]
        self.assertIn("Also add tests.", sent)
        self.assertNotIn("I changed the tokenizer.", sent)

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
        live_monitor.begin_window(capped, KEY, now=NOW + 61)
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

    def test_a_store_that_cannot_be_read_refuses_for_want_of_consent(self) -> None:
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
        for phrase in ("Haiku", "api.anthropic.com", "once a minute", "No command", "redacted"):
            self.assertIn(phrase, text)

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

    def test_none_or_low_stands_only_where_the_floor_is_met(self) -> None:
        for estimate, expected in (
            ({"level": "none_or_low"}, "none_or_low"),
            ({"level": "not_enough"}, "not_enough"),
            ({"level": "high"}, "high"),
        ):
            with self.subTest(estimate=estimate["level"]):
                live_monitor._SESSIONS.clear()
                result = self._ran(reply("none_or_low"), estimate=estimate)
                assert result.level is not None
                self.assertEqual(expected, result.level["level"])
                self.assertEqual(estimate["level"] != "none_or_low", result.level["floor_applied"])

    def test_a_reply_that_states_a_verdict_is_refused(self) -> None:
        result = self._ran(reply("none_or_low", "The work is complete and every goal was met."))
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
            {"fact_id": f"u{n}", "type": "user_message", "at": NOW - n, "reader_words": "Q" * 300}
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
