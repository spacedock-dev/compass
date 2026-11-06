"""The coordinator: what it records, when it collects, and what it refuses."""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import os
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest import mock

import event_hook
from compass_runtime import (
    aggregate,
    cli,
    ends,
    events,
    git_status,
    http_api,
    lifecycle,
    observation,
    project_context,
    reading,
)
from compass_runtime import asks as runtime_asks
from compass_runtime import io as runtime_io
from compass_runtime import sessions as runtime_sessions
from compass_runtime import supervise as runtime_supervise

from . import support

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

NOW = 1_700_000_000.0
SESSION = "abcdef12-3456-7890-abcd-ef1234567890"
OTHER = "beefcafe-3456-7890-abcd-ef1234567890"
PREFIX = "abcdef12"
OTHER_PREFIX = "beefcafe"


class FakeStreams:
    def __init__(self, count: int = 0) -> None:
        self.count = count


class FakeState:
    def __init__(self, streams: FakeStreams) -> None:
        self.streams = streams
        # The real registry rather than a stand-in: `_due` reads its `count`,
        # and the meaning of that count (unresolved, not stored) is half of the
        # wedge this suite has to hold shut.
        self.asks = runtime_asks.AskRegistry()


class FakeApplication:
    """Just enough application for the coordinator: a config, streams, a collect."""

    def __init__(
        self, config: Any, *, streams: int = 0, fail: bool = False, reuse: bool = False
    ) -> None:
        self.config = config
        self.state = FakeState(FakeStreams(streams))
        self.collected = 0
        self.fail = fail
        # Stand in for the application's own collection floor: a real
        # `collect_json` inside `collect_memo_sec` returns the revision it already
        # published rather than minting a new one.
        self.reuse = reuse
        self.diagnostic_sink: Any = lambda _message: None

    def collect_json(self, *, show_all: bool) -> tuple[tuple[float, int], bytes]:
        assert show_all is False, "the coordinator only maintains the default variant"
        if self.fail:
            raise OSError("store exploded")
        if not self.reuse:
            self.collected += 1
        return (NOW, self.collected), b"{}"


class ObservationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.now = NOW
        # A real, empty state home per case. `support.make_config`'s
        # `/nonexistent-compass-test` is a path that exists nowhere, which was harmless
        # while nothing here wrote: since DRC-4547 every `session_ended` reaching
        # `_record` writes the end store, so every coordinator built here is a
        # live writer outside any sandbox. Measured: `LedgerTest` as it stood made
        # ten `os.makedirs("/nonexistent-compass-test/.compass")` calls, and it passed
        # on macOS only because that raises OSError and `ends.save` swallows it.
        # On the Windows runner the same path is creatable by an ordinary user.
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config = support.make_config(state_home=home.name, state_dir=Path(home.name))

    def clock(self) -> float:
        return self.now

    def build(self, *, reuse: bool = False, **changes: Any) -> observation.Observation:
        config = dataclasses.replace(self.config, **changes) if changes else self.config
        self.app = FakeApplication(config, reuse=reuse)
        return observation.Observation(
            self.app,  # type: ignore[arg-type]
            clock=self.clock,
            diagnostic_sink=lambda _message: None,
        )

    def open_ask(self, *, created: float | None = None) -> runtime_asks.PendingAsk:
        """One unresolved ask in the coordinator's registry.

        The sweep windows are absurd so that registering cannot expire anything:
        these tests are about what the coordinator does with an ask that is
        genuinely outstanding.
        """
        ask = runtime_asks.PendingAsk(
            harness="claude",
            session_id=SESSION,
            project="compass",
            question="Ship it?",
            options=("yes", "no"),
            created=self.now if created is None else created,
        )
        self.assertTrue(
            self.app.state.asks.register(ask, limit=8, deadline=10_000.0, retention=10_000.0)
        )
        return ask

    def envelope(self, **overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"v": 1, "event": "turn_started", "session_id": SESSION}
        payload.update(overrides)
        return payload


class SubmitTest(ObservationTestCase):
    def test_a_valid_event_is_accepted_and_recorded(self) -> None:
        coordinator = self.build()
        self.assertEqual("accepted", coordinator.submit("claude", self.envelope()))
        overlays = coordinator.overlays_for("claude", PREFIX)
        self.assertEqual([events.OVERLAY_WORKING], [item.kind for item in overlays])

    def test_a_rejected_envelope_returns_its_reason_and_records_nothing(self) -> None:
        coordinator = self.build()
        self.assertEqual(
            events.REJECT_INCOMPATIBLE, coordinator.submit("claude", self.envelope(v=99))
        )
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))
        self.assertEqual(1, coordinator.counters[f"reject.{events.REJECT_INCOMPATIBLE}"])

    def test_a_rejected_envelope_does_not_mark_anything_dirty(self) -> None:
        # Otherwise a stream of garbage would drive collections, which is the
        # cheapest denial of service against a loopback endpoint there is.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="nonsense"))
        self.now += 3600
        self.assertEqual((False, ""), coordinator._due())

    def test_arrival_seq_is_minted_per_submission_and_never_repeats(self) -> None:
        coordinator = self.build()
        for _ in range(3):
            coordinator.submit("claude", self.envelope(event="input_requested"))
        # One overlay survives per kind, and it carries the newest sequence.
        overlay = coordinator.overlays_for("claude", PREFIX)[0]
        self.assertEqual(3, overlay.arrival_seq)

    def test_concurrent_submissions_get_distinct_arrival_seqs(self) -> None:
        # The counter is minted under the lock. Two handler threads sharing one
        # sequence would make the reducer's order arbitrary between them.
        coordinator = self.build()
        seen: list[int] = []
        guard = threading.Lock()

        def submit() -> None:
            with coordinator._lock:
                coordinator._arrival_seq += 1
                seq = coordinator._arrival_seq
            with guard:
                seen.append(seq)

        threads = [threading.Thread(target=submit) for _ in range(24)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(24, len(set(seen)))

    def test_a_hint_event_marks_dirty_without_recording_an_overlay(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="store_changed"))
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))
        self.now += 3600
        self.assertEqual((True, "event"), coordinator._due())


class LedgerTest(ObservationTestCase):
    def test_one_overlay_per_kind_per_session_so_the_ledger_cannot_grow(self) -> None:
        # The reducer is last-writer-wins per kind, so an older overlay of the
        # same kind could never have changed the outcome.
        coordinator = self.build()
        for _ in range(50):
            coordinator.submit("claude", self.envelope(event="turn_started"))
        self.assertEqual(1, len(coordinator.overlays_for("claude", PREFIX)))

    def test_two_kinds_coexist_so_precedence_is_still_the_reducers_to_decide(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        self.assertEqual(
            {events.OVERLAY_NEEDS_INPUT, events.OVERLAY_IDLE},
            {item.kind for item in coordinator.overlays_for("claude", PREFIX)},
        )

    def test_two_subagents_are_two_facts_rather_than_one_superseding_the_other(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="subagent_started", subagent_id="child-1"))
        coordinator.submit("claude", self.envelope(event="subagent_started", subagent_id="child-2"))
        self.assertEqual(2, len(coordinator.overlays_for("claude", PREFIX)))

    def test_a_reordered_older_delivery_does_not_replace_a_newer_overlay(self) -> None:
        # At-least-once and possibly reordered. Keeping the newer overlay is what
        # makes replaying the ledger idempotent.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        newest = coordinator.overlays_for("claude", PREFIX)[0]
        stale = dataclasses.replace(newest, arrival_seq=newest.arrival_seq - 1, at=NOW - 500)
        with coordinator._lock:
            coordinator._remember(("claude", PREFIX), stale)
        self.assertEqual(newest, coordinator.overlays_for("claude", PREFIX)[0])
        self.assertEqual(1, coordinator.counters["overlay.stale"])

    def test_session_ended_retires_the_ledger_without_removing_a_row(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))
        self.assertEqual(1, coordinator.counters["retired"])

    def test_a_stop_is_remembered_outside_the_ledger_it_gets_retired_with(self) -> None:
        # DRC-4035's motivating case is `claude -p`: the stop and the exit arrive
        # back to back, so a mark held in the ledger is destroyed milliseconds
        # after the only session it describes finished.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))
        self.assertEqual(NOW, coordinator.finished_at("claude", PREFIX))

    def test_a_session_that_works_again_is_no_longer_finished(self) -> None:
        # The DRC-4101 failure class: the mark outlives the ledger by design, so
        # a resumption has to remove it rather than be outranked by it.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.submit("claude", self.envelope(event="turn_started"))
        self.assertEqual(0.0, coordinator.finished_at("claude", PREFIX))

    def test_a_gate_after_a_stop_is_not_a_finished_session(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.submit("claude", self.envelope(event="input_requested"))
        self.assertEqual(0.0, coordinator.finished_at("claude", PREFIX))

    def test_an_end_is_remembered_for_the_session_id_that_ended(self) -> None:
        # DRC-4036. The ledger is popped by the same event, so this mark cannot
        # live in it any more than the completion mark can.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))
        self.assertEqual(NOW, coordinator.ended_at("claude", PREFIX))

    def test_no_end_observed_reads_zero_and_never_a_guess(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        self.assertEqual(0.0, coordinator.ended_at("claude", PREFIX))

    def test_a_resumed_session_id_stops_reading_ended(self) -> None:
        # `session_started` produces NO overlay, so it reaches neither `_remember`
        # nor `_mark_finished`: without an explicit lift, `claude --resume <id>`
        # would leave the row reading ended for the rest of the run.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.now += 60
        coordinator.submit("claude", self.envelope(event="session_started"))
        self.assertEqual(0.0, coordinator.ended_at("claude", PREFIX))

    def test_a_session_working_after_its_end_stops_reading_ended(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.now += 60
        coordinator.submit("claude", self.envelope(event="turn_started"))
        self.assertEqual(0.0, coordinator.ended_at("claude", PREFIX))

    def test_a_gate_after_an_end_stops_reading_ended(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.now += 60
        coordinator.submit("claude", self.envelope(event="input_requested"))
        self.assertEqual(0.0, coordinator.ended_at("claude", PREFIX))

    def test_a_stop_after_an_end_leaves_the_mark_standing(self) -> None:
        # A `turn_stopped` says a turn ended, not that the session reopened, and
        # every clean ending has one in front of it.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.now += 60
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        self.assertEqual(NOW, coordinator.ended_at("claude", PREFIX))

    def test_an_event_stamped_before_the_end_does_not_lift_the_mark(self) -> None:
        # At-least-once delivery, reordered. The a1 arm of the session-end capture
        # had its `SessionEnd` land 5.581 s after the last Stop, which is long
        # enough for a short headless run's own earlier hook POST to arrive after
        # it. Arrival order cannot separate those — it is exactly what got
        # reordered — so the lift compares the EVENT stamps instead.
        coordinator = self.build()
        self.now += 60
        coordinator.submit("claude", self.envelope(event="session_ended"))
        # Stamped a minute before the end and delivered after it. Written through
        # the envelope rather than poked into the map, so the parse's own
        # plausibility filter is on the path a real reordered hook would take.
        older = datetime.datetime.fromtimestamp(NOW, tz=datetime.UTC).isoformat()
        coordinator.submit("claude", self.envelope(event="turn_started", timestamp=older))
        self.assertEqual(self.now, coordinator.ended_at("claude", PREFIX))

    def test_an_observed_end_is_written_to_the_end_store(self) -> None:
        # DRC-4547: the mark lived only here, so a restart forgot every end.
        # Written through on the same event that sets it, and the assertion is
        # on the file rather than on the accessor.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.assertEqual({("claude", PREFIX): NOW}, ends.restored(ends.load(coordinator.config)))

    def test_a_lifted_end_is_removed_from_the_end_store(self) -> None:
        # Delete-through on the same three edges `_lift_ended` forgets on;
        # without it a `claude --resume <id>` would come back ended after the
        # next restart even though this run had already lifted the mark.
        for event in ("session_started", "turn_started", "input_requested"):
            with self.subTest(event=event):
                coordinator = self.build()
                coordinator.submit("claude", self.envelope(event="session_ended"))
                self.now += 60
                coordinator.submit("claude", self.envelope(event=event))
                self.assertEqual(0.0, coordinator.ended_at("claude", PREFIX))
                self.assertEqual({}, ends.restored(ends.load(coordinator.config)))

    def test_a_resume_after_a_restart_lifts_the_end_an_earlier_run_stored(self) -> None:
        # The memory is empty after a restart, so `_lift_ended` has nothing to
        # forget; the disk still carries the end an earlier run observed. A
        # `session_started` is what `claude --resume <id>` emits for the id it
        # reuses, and with the board up to see it the stored end must go too,
        # or the resumed session would read as ended at its prompt until the
        # transcript guard in `aggregate` happened to drop it.
        coordinator = self.build()
        ends.record(
            coordinator.config,
            harness="claude",
            sid=PREFIX,
            at=NOW - 3600,
            diagnostic_sink=lambda _m: None,
        )
        self.assertEqual(0.0, coordinator.ended_at("claude", PREFIX), "memory starts empty")
        coordinator.submit("claude", self.envelope(event="session_started"))
        self.assertEqual({}, ends.restored(ends.load(coordinator.config)))

    def test_a_stop_after_an_end_leaves_the_stored_end(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.now += 60
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        self.assertEqual({("claude", PREFIX): NOW}, ends.restored(ends.load(coordinator.config)))

    def test_an_end_refused_at_the_cap_is_not_written(self) -> None:
        # The file mirrors what memory accepted. Writing a refused end would have
        # the next collection restore from disk what the cap just refused, so the
        # counter would say refused and the row would say ended.
        coordinator = self.build(event_overlay_max_sessions=1)
        coordinator.submit("claude", self.envelope(event="session_ended"))
        coordinator.submit("claude", self.envelope(event="session_ended", session_id=OTHER))
        self.assertEqual(1, coordinator.counters["ended.refused"])
        self.assertEqual({("claude", PREFIX): NOW}, ends.restored(ends.load(coordinator.config)))

    def test_a_session_that_never_ended_creates_no_end_store(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_started"))
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.submit("claude", self.envelope(event="session_started"))
        self.assertFalse(os.path.exists(ends.store_path(coordinator.config)))

    def test_an_end_mark_is_capped_like_the_ledger_and_counts_the_refusal(self) -> None:
        coordinator = self.build(event_overlay_max_sessions=1)
        coordinator.submit("claude", self.envelope(event="session_ended"))
        coordinator.submit("claude", self.envelope(event="session_ended", session_id=OTHER))
        self.assertEqual(NOW, coordinator.ended_at("claude", PREFIX))
        self.assertEqual(0.0, coordinator.ended_at("claude", OTHER_PREFIX))
        self.assertEqual(1, coordinator.counters["ended.refused"])

    def test_a_clear_followed_by_a_prompt_inside_one_window_reads_as_working(self) -> None:
        # Claude fires session_ended on /clear as well as on exit, so this exact
        # order arrives in practice and must not leave the row retired.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        coordinator.submit("claude", self.envelope(event="turn_started"))
        patch = events.reduce_overlays(coordinator.overlays_for("claude", PREFIX), now=self.now)
        self.assertEqual("working", patch["state"])

    def test_at_capacity_a_new_session_is_refused_rather_than_evicting_a_live_one(self) -> None:
        # Evicting the oldest ledger to make room would clear whichever permission
        # alert happened to be oldest, which is the one most likely still waiting.
        coordinator = self.build(event_overlay_max_sessions=1)
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.submit("claude", self.envelope(event="input_requested", session_id=OTHER))
        self.assertEqual(1, len(coordinator.overlays_for("claude", PREFIX)))
        self.assertEqual([], coordinator.overlays_for("claude", OTHER_PREFIX))
        self.assertEqual(1, coordinator.counters["overlay.refused"])

    def test_an_existing_session_can_still_record_at_capacity(self) -> None:
        # The cap bounds how many sessions are tracked, not how a tracked session
        # is allowed to change state.
        coordinator = self.build(event_overlay_max_sessions=1)
        coordinator.submit("claude", self.envelope(event="turn_started"))
        coordinator.submit("claude", self.envelope(event="input_requested"))
        self.assertEqual(2, len(coordinator.overlays_for("claude", PREFIX)))


class LedgerReportTest(ObservationTestCase):
    """The diagnostic read. Its job is to separate two identical-looking rows."""

    def test_the_report_carries_every_field_the_reducer_orders_on(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_started"))
        coordinator.submit("claude", self.envelope(event="input_requested"))
        report = coordinator.ledger_report()
        self.assertEqual(NOW, report["now"])
        self.assertEqual(2, report["arrival_seq"])
        self.assertEqual(
            [(events.OVERLAY_WORKING, 1), (events.OVERLAY_NEEDS_INPUT, 2)],
            [(row["kind"], row["arrival_seq"]) for row in report["overlays"]],
        )
        for row in report["overlays"]:
            self.assertEqual(("claude", PREFIX), (row["harness"], row["sid"]))
        # By value, not by presence: a report that swapped `at` for
        # `effective_at` would satisfy a membership check.
        working = report["overlays"][0]
        self.assertEqual(NOW, working["at"])
        self.assertEqual(0.0, working["effective_at"])
        self.assertEqual(NOW + self.config.overlay_working_ttl_sec, working["expires_at"])
        self.assertIsNone(report["overlays"][1]["expires_at"], "a wait has no deadline")

    def test_the_time_gate_is_evaluated_against_the_clock_rather_than_by_the_reader(self) -> None:
        # A working overlay expires; a wait does not.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_started"))
        coordinator.submit("claude", self.envelope(event="input_requested"))
        self.now += self.config.overlay_working_ttl_sec + 1
        gates = {
            row["kind"]: row["time_gate_open"] for row in coordinator.ledger_report()["overlays"]
        }
        self.assertEqual({events.OVERLAY_WORKING: False, events.OVERLAY_NEEDS_INPUT: True}, gates)

    def test_an_arrived_envelope_that_left_no_overlay_shows_up_in_the_counters(self) -> None:
        # Arrived-and-dropped versus never-posted: both leave `overlays` empty,
        # and only the counters separate them. N-5.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.submit("claude", self.envelope(event="session_ended"))
        report = coordinator.ledger_report()
        self.assertEqual([], report["overlays"])
        self.assertEqual(1, report["counters"]["retired"])
        self.assertEqual(1, report["counters"]["event.input_requested"])

    def test_the_ledger_separates_a_suppressed_wait_from_a_wait_that_never_arrived(self) -> None:
        # The whole reason the route exists: both produce the same three fields
        # on /api/data, and their fixes have nothing in common. DRC-4134.
        suppressed = self.build()
        suppressed.submit("claude", self.envelope(event="turn_started"))
        suppressed.submit("claude", self.envelope(event="input_requested"))
        never_arrived = self.build()
        never_arrived.submit("claude", self.envelope(event="turn_started"))

        # Past the grace, the row each one produces is identical.
        for coordinator in (suppressed, never_arrived):
            row: dict[str, Any] = {"state": "needs_input", "state_detail": "open question"}
            events.apply_patch(
                row,
                events.reduce_overlays(
                    coordinator.overlays_for("claude", PREFIX),
                    now=NOW,
                    own_activity=NOW + self.config.overlay_wait_activity_grace_sec + 1,
                    activity_grace_sec=self.config.overlay_wait_activity_grace_sec,
                ),
            )
            self.assertEqual(
                ("working", "event", None), (row["state"], row["acquisition"], row["state_detail"])
            )

        # The ledger is where they differ, and it is the only place they do.
        self.assertIn(
            events.OVERLAY_NEEDS_INPUT,
            [row["kind"] for row in suppressed.ledger_report()["overlays"]],
        )
        self.assertNotIn(
            events.OVERLAY_NEEDS_INPUT,
            [row["kind"] for row in never_arrived.ledger_report()["overlays"]],
        )

    def test_the_report_names_the_rows_still_waiting_for_a_collection(self) -> None:
        # An overlay for a session no collection has produced is the third way a
        # gate goes missing, and it is invisible in `overlays` alone.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.note_rows(set())
        self.assertEqual([f"claude/{PREFIX}"], coordinator.ledger_report()["pending_rows"])

    def test_an_empty_ledger_reports_empty_rather_than_failing(self) -> None:
        report = self.build().ledger_report()
        self.assertEqual([], report["overlays"])
        self.assertEqual([], report["pending_rows"])


class PendingTest(ObservationTestCase):
    def test_an_overlay_for_a_collected_row_leaves_no_pending_entry(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.note_rows({("claude", PREFIX)})
        self.assertEqual({}, coordinator._pending)
        self.assertEqual(1, len(coordinator.overlays_for("claude", PREFIX)))

    def test_an_overlay_for_an_unknown_row_waits_rather_than_rendering(self) -> None:
        # A first-session permission prompt must survive until the collector sees
        # the session, without letting a forged id invent one.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.note_rows(set())
        self.assertIn(("claude", PREFIX), coordinator._pending)
        self.assertEqual(1, len(coordinator.overlays_for("claude", PREFIX)))

    def test_a_waiting_overlay_attaches_when_a_later_collection_produces_its_row(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.note_rows(set())
        coordinator.note_rows({("claude", PREFIX)})
        self.assertEqual({}, coordinator._pending)
        self.assertEqual(1, len(coordinator.overlays_for("claude", PREFIX)))

    def test_a_completion_mark_is_dropped_once_no_collection_produces_its_row(self) -> None:
        # No event retires the mark, so this is its only bound: a session the
        # collector has stopped publishing can never render it again.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.submit("claude", self.envelope(event="session_ended"))
        coordinator.note_rows({("claude", PREFIX)})
        self.assertEqual(NOW, coordinator.finished_at("claude", PREFIX))
        coordinator.note_rows(set())
        self.assertEqual(0.0, coordinator.finished_at("claude", PREFIX))

    def test_a_mark_survives_a_collection_that_had_not_seen_its_session_yet(self) -> None:
        # A collection already in flight when the stop arrived reports a key set
        # that predates it. Its overlay is pending, so the mark waits with it.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.note_rows(set())
        self.assertEqual(NOW, coordinator.finished_at("claude", PREFIX))

    def test_an_end_mark_survives_the_note_rows_that_follows_it(self) -> None:
        # The trap `_finished`'s retirement rule walks straight into. Ending pops
        # `_overlays[key]`, so straight afterwards the key is in neither the
        # collected set nor the ledger — `_finished`'s two conditions — and a
        # mark retired there can never be re-earned, because a session fires
        # `session_ended` exactly once. A stop is re-supplied by the next
        # `turn_stopped`, so its rule tolerates being wrong; this one does not.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        coordinator.note_rows(set())
        self.assertEqual(NOW, coordinator.ended_at("claude", PREFIX))

    def test_an_end_mark_is_retired_once_its_row_is_a_whole_window_gone(self) -> None:
        # Its only bound besides the cap, and it is a time rule rather than a
        # row-set rule for the reason above. A row is produced only while its
        # activity is inside the display window, and the end is the last thing
        # that happened to that id, so past the window the row cannot come back.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.now += self.config.ended_mark_ttl_sec + 1
        coordinator.note_rows({("claude", PREFIX)})
        self.assertEqual(NOW, coordinator.ended_at("claude", PREFIX), "still collected")
        coordinator.note_rows(set())
        self.assertEqual(0.0, coordinator.ended_at("claude", PREFIX))

    def test_completion_marks_are_capped_like_the_ledger_and_count_the_refusal(self) -> None:
        coordinator = self.build(event_overlay_max_sessions=1)
        coordinator.submit("claude", self.envelope(event="turn_stopped"))
        coordinator.submit("claude", self.envelope(event="turn_stopped", session_id=OTHER))
        self.assertEqual(NOW, coordinator.finished_at("claude", PREFIX))
        self.assertEqual(0.0, coordinator.finished_at("claude", OTHER_PREFIX))
        self.assertEqual(1, coordinator.counters["finished.refused"])

    def test_a_waiting_overlay_expires_after_the_ttl_with_a_counter(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.note_rows(set())
        self.now += self.config.event_pending_ttl_sec + 1
        coordinator.note_rows(set())
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))
        self.assertEqual(1, coordinator.counters["pending.expired"])

    def test_the_ttl_is_measured_from_first_sight_not_from_the_last_attempt(self) -> None:
        # Otherwise every collection would renew the clock and nothing would ever
        # expire while collections kept happening.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator.note_rows(set())
        for _ in range(4):
            self.now += self.config.event_pending_ttl_sec / 3
            coordinator.note_rows(set())
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))

    def test_the_pending_map_refuses_beyond_its_cap_and_counts_it(self) -> None:
        coordinator = self.build(event_pending_max=1, event_overlay_max_sessions=8)
        for suffix in "0123456789ab":
            coordinator.submit(
                "claude",
                self.envelope(event="input_requested", session_id=f"1234567{suffix}-abcd-0000"),
            )
        coordinator.note_rows(set())
        self.assertEqual(1, len(coordinator._pending))
        self.assertGreaterEqual(coordinator.counters["pending.refused"], 1)


class DueTest(ObservationTestCase):
    def test_the_floor_gates_a_dirty_harness(self) -> None:
        # The floor is the store-protection guarantee. A burst of events must not
        # be able to drive collections faster than the memo ever allowed.
        coordinator = self.build()
        coordinator._last_collect_at = self.now
        coordinator.submit("claude", self.envelope())
        self.now += self.config.event_coalesce_sec + 0.01
        self.assertEqual((False, ""), coordinator._due())
        self.now += self.config.collect_memo_sec
        self.assertEqual((True, "event"), coordinator._due())

    def test_a_dirty_harness_waits_out_the_coalescing_window(self) -> None:
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        coordinator.submit("claude", self.envelope())
        self.assertEqual((False, ""), coordinator._due())
        self.now += self.config.event_coalesce_sec
        self.assertEqual((True, "event"), coordinator._due())

    def test_the_window_is_fixed_rather_than_sliding(self) -> None:
        # A sliding window never closes under a sustained burst, and the board
        # would stop updating entirely.
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        coordinator.submit("claude", self.envelope())
        opened = coordinator._coalesce_until
        for _ in range(20):
            self.now += self.config.event_coalesce_sec / 4
            coordinator.submit("claude", self.envelope(event="store_changed"))
        self.assertEqual(opened, coordinator._coalesce_until)
        self.assertEqual((True, "event"), coordinator._due())

    def test_a_connected_stream_ticks_on_the_producer_interval(self) -> None:
        coordinator = self.build()
        self.app.state.streams.count = 1
        coordinator._last_collect_at = self.now
        self.now += self.config.stream_producer_interval_sec
        self.assertEqual((True, "tick"), coordinator._due())

    def test_a_connected_stream_does_not_tick_before_the_interval_elapses(self) -> None:
        # The gap between the floor and the interval is the part that matters.
        # Past the floor a tick is *permitted*, and only the interval stops it, so
        # a test that checked one instant past the floor could not tell an
        # interval-respecting tick from one that fires as fast as the floor
        # allows. This asserts inside that gap.
        self.assertGreater(
            self.config.stream_producer_interval_sec,
            self.config.collect_memo_sec,
            "the gap this test samples has to exist",
        )
        coordinator = self.build()
        self.app.state.streams.count = 1
        coordinator._last_collect_at = self.now
        self.now += (self.config.collect_memo_sec + self.config.stream_producer_interval_sec) / 2
        self.assertEqual((False, ""), coordinator._due())

    def test_with_no_stream_connected_nothing_ticks(self) -> None:
        # An idle daemon costs nothing. A timer that collected regardless would be
        # the exact regression the phase before this one existed to avoid.
        coordinator = self.build()
        coordinator._last_collect_at = self.now
        self.now += 86_400
        self.assertEqual((False, ""), coordinator._due())

    def test_an_event_outranks_a_tick_so_the_reason_is_reported_honestly(self) -> None:
        coordinator = self.build()
        self.app.state.streams.count = 1
        coordinator._last_collect_at = self.now - 3600
        coordinator.submit("claude", self.envelope())
        self.now += self.config.event_coalesce_sec
        self.assertEqual((True, "event"), coordinator._due())


class UrgencyTest(ObservationTestCase):
    """A permission alert does not wait out a window meant for batching."""

    def test_a_needs_input_event_skips_the_coalescing_window(self) -> None:
        # The exemption this module documented for two phases without
        # implementing it. Measured worth about 117 ms of the wait.
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        coordinator.submit("claude", self.envelope(event="input_requested"))
        self.assertEqual((True, "event"), coordinator._due())

    def test_an_ordinary_event_still_waits_out_the_window(self) -> None:
        # The other half: without this the exemption is indistinguishable from
        # deleting the window.
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        coordinator.submit("claude", self.envelope(event="store_changed"))
        self.assertEqual((False, ""), coordinator._due())

    def test_urgency_does_not_lift_the_floor(self) -> None:
        # The floor is the store-protection guarantee, so it may not become a
        # derived side effect of anything.
        coordinator = self.build()
        coordinator._last_collect_at = self.now
        coordinator.submit("claude", self.envelope(event="input_requested"))
        self.assertEqual((False, ""), coordinator._due())
        self.now += self.config.collect_memo_sec
        self.assertEqual((True, "event"), coordinator._due())


class FloorReuseTest(ObservationTestCase):
    """A collection the application's own floor satisfied is not progress.

    The floor is enforced twice, by two clocks: this coordinator's
    `_last_collect_at`, and the application's snapshot age. A fresh coordinator
    has never collected, so its floor is open while the application's is not, and
    `collect_json` then returns the body it serialized before the event existed.

    Measured before this was fixed: an `input_requested` arriving in that gap was
    retired against a read that predated it and never rendered at all, until an
    unrelated event or a five-second stream tick happened along.
    """

    def _reusing(self) -> observation.Observation:
        coordinator = self.build(reuse=True)
        # The application has already published, and its floor now serves this
        # read from those bytes while the coordinator's own floor is still open.
        coordinator._last_revision = (NOW, 0)
        coordinator._last_collect_at = self.now - 3600
        coordinator.submit("claude", self.envelope(event="input_requested"))
        return coordinator

    def _dirty(self, coordinator: observation.Observation) -> bool:
        return any(
            coordinator._dirty.get(key, 0) != coordinator._collected.get(key, 0)
            for key in coordinator._dirty
        )

    def test_a_reused_publication_leaves_the_event_dirty(self) -> None:
        coordinator = self._reusing()
        due, reason = coordinator._due()
        self.assertTrue(due)
        coordinator._collect(reason)
        self.assertTrue(
            self._dirty(coordinator),
            "the event was retired against a read that predates it",
        )
        self.assertEqual(1, coordinator.counters.get("reused.floor"))

    def test_the_retry_is_scheduled_at_the_floor_not_a_producer_interval(self) -> None:
        # `_sleep_for` consults only `_coalesce_until`, so without scheduling the
        # wake the retry lands at stream_producer_interval_sec. Measured 5.2 s
        # before, 2.5 s after.
        coordinator = self._reusing()
        coordinator._collect(coordinator._due()[1])
        self.assertIsNotNone(coordinator._coalesce_until)
        self.assertLessEqual(
            coordinator._sleep_for(),
            self.config.collect_memo_sec,
            "the worker must wake at the floor rather than at the producer interval",
        )

    def test_a_real_publication_still_marks_the_event_collected(self) -> None:
        # The control. If this failed, the fix above would simply have stopped the
        # coordinator ever making progress.
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        coordinator.submit("claude", self.envelope(event="input_requested"))
        coordinator._collect(coordinator._due()[1])
        self.assertFalse(self._dirty(coordinator))
        self.assertIsNone(coordinator.counters.get("reused.floor"))


class CollectTest(ObservationTestCase):
    def test_a_collection_clears_the_dirty_generation_it_observed(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope())
        coordinator._collect("event")
        self.assertEqual(1, self.app.collected)
        self.now += 3600
        self.assertEqual((False, ""), coordinator._due())

    def test_a_generation_that_moves_during_collection_stays_dirty(self) -> None:
        # A store_changed hint cannot be recovered by replaying overlays over a
        # read that predates it, so the harness has to be read again.
        coordinator = self.build()
        coordinator.submit("claude", self.envelope())
        real = self.app.collect_json

        def racing(*, show_all: bool) -> Any:
            coordinator.submit("claude", self.envelope(event="store_changed"))
            return real(show_all=show_all)

        self.app.collect_json = racing  # type: ignore[method-assign]
        coordinator._collect("event")
        self.now += 3600
        self.assertEqual((True, "event"), coordinator._due())

    def test_a_failed_collection_is_swallowed_and_leaves_the_harness_dirty(self) -> None:
        # The per-harness failure boundary already reports the cause, and a
        # coordinator that died on one bad read would freeze every dashboard.
        coordinator = self.build()
        self.app.fail = True
        coordinator.submit("claude", self.envelope())
        coordinator._collect("event")
        self.now += 3600
        self.assertEqual((True, "event"), coordinator._due())

    def test_a_failed_collection_still_advances_the_floor(self) -> None:
        # Otherwise a permanently broken store would spin the coordinator at full
        # speed retrying it.
        coordinator = self.build()
        self.app.fail = True
        coordinator.submit("claude", self.envelope())
        coordinator._collect("event")
        self.assertEqual(self.now, coordinator._last_collect_at)

    def test_the_coalescing_window_reopens_for_the_next_burst(self) -> None:
        coordinator = self.build()
        coordinator.submit("claude", self.envelope())
        coordinator._collect("event")
        self.assertIsNone(coordinator._coalesce_until)
        coordinator.submit("claude", self.envelope())
        self.assertIsNotNone(coordinator._coalesce_until)


class ProbeTest(ObservationTestCase):
    def test_the_first_tick_reconciles_unconditionally(self) -> None:
        coordinator = self.build()
        self.assertTrue(coordinator._worth_collecting(self.now))

    def test_an_unchanged_store_lets_a_tick_skip(self) -> None:
        coordinator = self.build()
        coordinator._worth_collecting(self.now)
        self.now += 1
        self.assertFalse(coordinator._worth_collecting(self.now))

    def test_a_changed_store_makes_a_tick_collect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            projects.mkdir()
            with support.store_patch(PROJECTS_DIR=str(projects)):
                config = dataclasses.replace(
                    support.make_config(),
                    store_roots={"claude.projects": (str(projects),)},
                )
                self.assertEqual((str(projects),), config.store_roots["claude.projects"])
                app = FakeApplication(config)
                coordinator = observation.Observation(
                    app,  # type: ignore[arg-type]
                    clock=self.clock,
                    diagnostic_sink=lambda _message: None,
                )
                coordinator._worth_collecting(self.now)
                self.now += 1
                self.assertFalse(coordinator._worth_collecting(self.now))
                (projects / "-w-proj").mkdir()
                self.now += 1
                self.assertTrue(coordinator._worth_collecting(self.now))

    def test_the_reconcile_interval_forces_a_collection_the_probe_would_skip(self) -> None:
        # The probe's documented false negative is a session older than the
        # activity window becoming active again. Nothing else covers it, so this
        # interval is what bounds it instead of leaving it forever.
        coordinator = self.build()
        coordinator._worth_collecting(self.now)
        self.now += self.config.reconcile_interval_sec / 2
        self.assertFalse(coordinator._worth_collecting(self.now))
        self.now += self.config.reconcile_interval_sec
        self.assertTrue(coordinator._worth_collecting(self.now))

    def test_a_probe_negative_tick_skips_the_collection_and_counts_it(self) -> None:
        coordinator = self.build()
        coordinator._worth_collecting(self.now)
        self.now += 1
        coordinator._collect("tick")
        self.assertEqual(0, self.app.collected)
        self.assertEqual(1, coordinator.counters["skipped.probe"])

    def test_an_event_driven_collection_is_never_skipped_by_the_probe(self) -> None:
        # The probe answers "did the store move". An event is a statement about
        # what the agent is doing, and no filesystem stamp can refute it.
        coordinator = self.build()
        coordinator._worth_collecting(self.now)
        self.now += 1
        coordinator.submit("claude", self.envelope())
        coordinator._collect("event")
        self.assertEqual(1, self.app.collected)

    def test_reconcile_required_forces_the_next_tick_to_read(self) -> None:
        # Compaction. A rewritten transcript is not repaired by a cached read.
        coordinator = self.build()
        coordinator._worth_collecting(self.now)
        self.now += 1
        coordinator.submit("claude", self.envelope(event="reconcile_required"))
        self.assertTrue(coordinator._worth_collecting(self.now))


class WorkerLifecycleTest(ObservationTestCase):
    def test_construction_starts_no_thread(self) -> None:
        # The daemon forks after assembly. A coordinator that spawned in its
        # constructor would be inherited half-running, or lost with the parent.
        before = threading.active_count()
        self.build()
        self.assertEqual(before, threading.active_count())

    def test_start_spawns_one_worker_and_stop_joins_it(self) -> None:
        coordinator = self.build()
        coordinator.start()
        worker = coordinator._worker
        assert worker is not None
        self.assertTrue(worker.is_alive())
        coordinator.stop(timeout=30)
        self.assertFalse(worker.is_alive())

    def test_starting_twice_does_not_spawn_a_second_worker(self) -> None:
        coordinator = self.build()
        coordinator.start()
        first = coordinator._worker
        coordinator.start()
        self.assertIs(first, coordinator._worker)
        coordinator.stop(timeout=5)

    def test_stopping_without_starting_is_safe(self) -> None:
        self.build().stop(timeout=1)

    def test_a_worker_asked_to_stop_before_it_ran_does_no_work(self) -> None:
        # The check before the wait, not just after it. Shutdown can land between
        # start() and the worker's first loop, and a round of collection during
        # teardown would publish into a stream registry already being closed.
        coordinator = self.build()
        coordinator.stop(timeout=1)
        coordinator.start()
        worker = coordinator._worker
        assert worker is not None
        worker.join(timeout=30)
        self.assertFalse(worker.is_alive())
        self.assertEqual(0, self.app.collected)

    def test_stopping_twice_is_safe(self) -> None:
        coordinator = self.build()
        coordinator.start()
        coordinator.stop(timeout=5)
        coordinator.stop(timeout=1)

    def test_the_worker_wakes_on_an_event_rather_than_waiting_out_its_interval(self) -> None:
        # The producer interval is raised to an hour, so only the wake can collect
        # inside the wait below. At its default of five seconds the wait had to
        # stay under five, and a loaded runner missed it.
        coordinator = self.build(stream_producer_interval_sec=3600.0)
        collected = threading.Event()
        real = self.app.collect_json

        def signalling(*, show_all: bool) -> Any:
            result = real(show_all=show_all)
            collected.set()
            return result

        self.app.collect_json = signalling  # type: ignore[method-assign]
        # A real clock here: the worker actually sleeps, so a frozen clock would
        # leave the coalescing deadline permanently in the future.
        coordinator.clock = time.time
        coordinator._last_reconcile_at = coordinator.clock()
        coordinator.start()
        try:
            coordinator.submit("claude", self.envelope())
            self.assertTrue(collected.wait(timeout=30), "the coordinator did not wake on the event")
        finally:
            coordinator.stop(timeout=5)


class AskWakeTest(ObservationTestCase):
    """An outstanding question has to guarantee its own collection.

    `AskRegistry.pending` is both what renders a card and what sweeps the table,
    and its only caller is a collection. Before this, `_due` needed a dirty
    generation or a connected stream, so on a dashboard with no browser tab open
    an ask never rendered, never expired and was never released: the budget
    filled with resolved and abandoned questions and every later registration was
    refused. Measured on the branch this fixes, on the tabless path the feature
    exists for: 503 at t+321s and t+341s while the payload reported zero cards.
    """

    def test_an_outstanding_ask_is_reason_enough_to_collect(self) -> None:
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        self.open_ask()
        self.assertEqual(0, self.app.state.streams.count, "no tab, which is the whole point")
        self.assertEqual((True, "ask"), coordinator._due())

    def test_nothing_is_due_once_the_last_ask_is_resolved(self) -> None:
        # The other half. An answered ask still waiting for its poller must not
        # hold the coordinator in a collection loop for the rest of the process.
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        ask = self.open_ask()
        self.assertTrue(self.app.state.asks.answer(ask.id, 0))
        self.assertEqual((False, ""), coordinator._due())

    def test_an_ask_does_not_lift_the_floor(self) -> None:
        # The floor is the store-protection guarantee, so it may not become a
        # derived side effect of anything, this included.
        coordinator = self.build()
        coordinator._last_collect_at = self.now
        self.open_ask()
        self.assertEqual((False, ""), coordinator._due())
        self.now += self.config.collect_memo_sec
        self.assertEqual((True, "ask"), coordinator._due())

    def test_an_event_still_outranks_an_ask_so_the_reason_stays_honest(self) -> None:
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        self.open_ask()
        coordinator.submit("claude", self.envelope())
        self.now += self.config.event_coalesce_sec
        self.assertEqual((True, "event"), coordinator._due())

    def test_an_ask_driven_collection_is_never_skipped_by_the_probe(self) -> None:
        # The probe answers "did a store move", and the sweep this pass exists to
        # run does not care. A skipped sweep is the wedge again.
        coordinator = self.build()
        coordinator._worth_collecting(self.now)
        self.now += 1
        self.open_ask()
        coordinator._collect("ask")
        self.assertEqual(1, self.app.collected)
        self.assertNotIn("skipped.probe", coordinator.counters)

    def test_note_ask_marks_dirty_and_clears_the_reconcile_floor(self) -> None:
        # No ask is registered here on purpose: this asserts the seam itself,
        # which is what brings the collection forward from the next tick to now.
        coordinator = self.build()
        coordinator._last_collect_at = self.now - 3600
        coordinator._last_reconcile_at = self.now
        coordinator.note_ask()
        self.assertEqual(0.0, coordinator._last_reconcile_at)
        self.assertEqual((True, "event"), coordinator._due())

    def test_note_ask_wakes_the_worker_rather_than_waiting_out_its_interval(self) -> None:
        # The producer interval is five seconds and the page's own fallback poll
        # is twenty, which is what a registered ask used to wait on: measured at
        # 18.2 to 22.3 seconds from register to a published revision. The interval
        # is raised to an hour so a regression cannot pass on the periodic tick.
        coordinator = self.build(stream_producer_interval_sec=3600.0)
        collected = threading.Event()
        real = self.app.collect_json

        def signalling(*, show_all: bool) -> Any:
            result = real(show_all=show_all)
            collected.set()
            return result

        self.app.collect_json = signalling  # type: ignore[method-assign]
        coordinator.clock = time.time
        coordinator._last_reconcile_at = coordinator.clock()
        ask = self.open_ask(created=time.time())
        coordinator.start()
        try:
            coordinator.note_ask()
            self.assertTrue(collected.wait(timeout=30), "the coordinator did not wake on the ask")
        finally:
            self.app.state.asks.withdraw(ask.id)
            coordinator.stop(timeout=5)


class WaitDetailTest(unittest.TestCase):
    """An agreeing overlay must not blank the question the collector found."""

    def setUp(self) -> None:
        self.state = support.reset_runtime()

    class Source:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
            del harness, sid
            return [
                events.Overlay(
                    harness="claude",
                    sid=PREFIX,
                    arrival_seq=1,
                    kind=self.kind,
                    at=support.SERVER_STARTED,
                )
            ]

        def finished_at(self, harness: str, sid: str) -> float:
            del harness, sid  # this stub remembers no stop
            return 0.0

        def ended_at(self, harness: str, sid: str) -> float:
            """No end observed: this stub answers only about stops."""
            del harness, sid
            return 0.0

        def git_for(self, harness: str, sid: str) -> None:
            """Never probed: this stub has no repository behind it."""
            del harness, sid

        def focusable(self, harness: str, sid: str) -> bool:
            """No terminal identity: this stub observed no session start."""
            del harness, sid
            return False

        def note_rows(self, keys: set[tuple[str, str]]) -> None:
            pass

        def command_reports(self) -> list[dict[str, Any]]:
            return []

        def drop_counters(self) -> dict[str, int]:
            return {}

    def _apply(self, kind: str, collected: str, detail: str | None) -> dict[str, Any]:
        app = support.build_app()
        app.overlays = self.Source(kind)
        session: dict[str, Any] = {
            "harness": "claude",
            "sid": PREFIX,
            "state": collected,
            "state_detail": detail,
        }
        app._apply_overlays([session], now=support.SERVER_STARTED)
        return session

    def test_an_agreeing_wait_overlay_leaves_the_question_on_the_row(self) -> None:
        # No overlay constructor sets `detail`, so the patch always carried None
        # and applying it blanked the one thing a person at a gate wants to read.
        session = self._apply(events.OVERLAY_NEEDS_INPUT, "needs_input", "Force push to main?")
        self.assertEqual("needs_input", session["state"])
        self.assertEqual("Force push to main?", session["state_detail"])
        self.assertEqual("event", session["acquisition"], "the rest of the patch still applied")

    def test_a_working_overlay_still_clears_it(self) -> None:
        # Otherwise a question that has been answered outlives the overlay that
        # retired the wait, which is DRC-4095 and DRC-4097 territory.
        session = self._apply(events.OVERLAY_WORKING, "needs_input", "Force push to main?")
        self.assertEqual("working", session["state"])
        self.assertIsNone(session["state_detail"])

    def test_a_wait_overlay_over_a_working_row_does_not_carry_its_detail_in(self) -> None:
        # `running Bash` is true of a session that is working and false of one
        # stopped at a gate, so it must not follow the row into the wait.
        session = self._apply(events.OVERLAY_NEEDS_INPUT, "working", "running Bash")
        self.assertEqual("needs_input", session["state"])
        self.assertIsNone(session["state_detail"])

    def test_a_row_with_no_detail_of_its_own_is_unchanged(self) -> None:
        session = self._apply(events.OVERLAY_NEEDS_INPUT, "needs_input", None)
        self.assertIsNone(session["state_detail"])


class RowOrderTest(unittest.TestCase):
    """The order rows are published in — the gate queue's spine. DRC-4018."""

    @staticmethod
    def _row(sid: str, state: str, **extra: Any) -> dict[str, Any]:
        return {"sid": sid, "state": state, "last_activity": 1000, **extra}

    def _sorted(self, rows: list[dict[str, Any]]) -> list[str]:
        return [r["sid"] for r in sorted(rows, key=aggregate.row_order)]

    def test_blocked_rows_come_out_longest_blocked_first(self) -> None:
        # Session id is an arbitrary order to be stopped in. The gate that has
        # held someone up longest is the one still costing something, so it leads
        # — and the ids here run the other way, so the sort cannot pass by
        # accident.
        rows = [
            self._row("aaa", "needs_input", blocked_since=900),
            self._row("bbb", "needs_input", blocked_since=100),
            self._row("ccc", "needs_input", blocked_since=500),
        ]
        self.assertEqual(["bbb", "ccc", "aaa"], self._sorted(rows))

    def test_the_states_keep_their_ranks_and_working_rows_keep_the_id_order(self) -> None:
        # Blocked above working above idle is unchanged, and nothing but the
        # blocked group gained a key: ranking working rows is D7's question.
        rows = [
            self._row("w2", "working", blocked_since=1),
            self._row("i1", "idle"),
            self._row("w1", "working", blocked_since=999),
            self._row("n1", "needs_input", blocked_since=500),
            self._row("unknown", "something_else"),
        ]
        self.assertEqual(["n1", "w1", "w2", "i1", "unknown"], self._sorted(rows))

    def test_two_gates_blocked_at_the_same_instant_fall_through_to_the_id(self) -> None:
        rows = [
            self._row("bbb", "needs_input", blocked_since=500),
            self._row("aaa", "needs_input", blocked_since=500),
        ]
        self.assertEqual(["aaa", "bbb"], self._sorted(rows))

    def test_a_gate_with_no_blocked_since_is_ranked_by_its_last_activity(self) -> None:
        # Only the Claude and Copilot collectors and the event overlays set
        # `blocked_since`, so a harness that reports a wait without one must still
        # take a place in the queue rather than sorting to the front on a zero.
        rows = [
            self._row("has", "needs_input", blocked_since=100),
            self._row("none", "needs_input", last_activity=50),
            self._row("null", "needs_input", blocked_since=None, last_activity=900),
        ]
        self.assertEqual(["none", "has", "null"], self._sorted(rows))

    def test_the_queue_ranks_on_the_timestamp_itself_not_an_elapsed_wait(self) -> None:
        # The property that keeps the queue from reshuffling under a reader as
        # every row in it waits longer. Asserted on the key rather than on a
        # sorted order, because any monotonic function of `blocked_since` sorts
        # the same and only the raw value is stable across refreshes.
        row = self._row("aaa", "needs_input", blocked_since=1_700_000_042.5)
        self.assertEqual(1_700_000_042.5, aggregate.row_order(row)[1])
        # And nothing in the key can vary while the row does not: two calls
        # separated by real time agree.
        self.assertEqual(aggregate.row_order(row), aggregate.row_order(dict(row)))


class StateDisputeTest(unittest.TestCase):
    """When an overlay overrules a collector that had found a wait. DRC-4139."""

    def setUp(self) -> None:
        self.state = support.reset_runtime()

    class Source:
        def __init__(
            self, overlays: list[events.Overlay], counters: dict[str, int] | None = None
        ) -> None:
            self.overlays = overlays
            self.counters = counters or {}

        def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
            return self.overlays if (harness, sid) == ("claude", PREFIX) else []

        def finished_at(self, harness: str, sid: str) -> float:
            del harness, sid  # this stub remembers no stop
            return 0.0

        def ended_at(self, harness: str, sid: str) -> float:
            """No end observed: this stub answers only about stops."""
            del harness, sid
            return 0.0

        def git_for(self, harness: str, sid: str) -> None:
            """Never probed: this stub has no repository behind it."""
            del harness, sid

        def focusable(self, harness: str, sid: str) -> bool:
            """No terminal identity: this stub observed no session start."""
            del harness, sid
            return False

        def note_rows(self, keys: set[tuple[str, str]]) -> None:
            pass

        def command_reports(self) -> list[dict[str, Any]]:
            return []

        def drop_counters(self) -> dict[str, int]:
            return dict(self.counters)

    def _apply(self, collected: str, kinds: list[str], **row: Any) -> dict[str, Any]:
        """One row through the real patch path, with a hand-set collector state."""
        overlays = [
            events.Overlay(
                harness="claude",
                sid=PREFIX,
                arrival_seq=seq,
                kind=kind,
                at=support.SERVER_STARTED - 10,
            )
            for seq, kind in enumerate(kinds, start=1)
        ]
        session: dict[str, Any] = {
            "harness": "claude",
            "sid": PREFIX,
            "state": collected,
            "state_detail": "open question (ExitPlanMode), waiting 2m",
            "title": "a prompt the user typed",
            **row,
        }
        app = support.build_app()
        app.overlays = self.Source(overlays)
        app._apply_overlays([session], now=support.SERVER_STARTED)
        return session

    def test_an_overlay_overruling_a_collected_wait_is_recorded(self) -> None:
        self._apply("needs_input", [events.OVERLAY_WORKING])
        self.assertEqual(1, self.state.dispute_total)
        record = self.state.disputes[0]
        self.assertEqual(("claude", PREFIX), (record["harness"], record["sid"]))
        self.assertEqual(
            ("needs_input", "working"), (record["collector_state"], record["overlay_state"])
        )

    def test_the_record_carries_the_ledger_that_produced_it(self) -> None:
        # Without the overlays a record says a disagreement happened and nothing
        # about which of the four readings in N-5 it was.
        self._apply("needs_input", [events.OVERLAY_WORKING])
        overlays = self.state.disputes[0]["overlays"]
        self.assertEqual([events.OVERLAY_WORKING], [row["kind"] for row in overlays])
        self.assertEqual([1], [row["arrival_seq"] for row in overlays])
        self.assertIn("time_gate_open", overlays[0])

    def test_the_recorded_ledger_is_in_arrival_order_like_the_live_one(self) -> None:
        # A ledger holds one overlay per kind, so re-recording a kind leaves it
        # in its original dict slot and `overlays_for` hands back a wait at seq 2
        # after a working overlay at seq 3. That pair is exactly what tells N-5's
        # second reading from its first, so a record in the other order from the
        # live ledger is worse than no record.
        out_of_order = [
            events.Overlay(
                harness="claude", sid=PREFIX, arrival_seq=3, kind=events.OVERLAY_WORKING, at=1.0
            ),
            events.Overlay(
                harness="claude", sid=PREFIX, arrival_seq=2, kind=events.OVERLAY_NEEDS_INPUT, at=1.0
            ),
        ]
        session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
        app = support.build_app()
        app.overlays = self.Source(out_of_order)
        app._apply_overlays([session], now=support.SERVER_STARTED)
        self.assertEqual([2, 3], [row["arrival_seq"] for row in self.state.disputes[0]["overlays"]])

    def test_the_record_carries_the_activity_the_guards_read(self) -> None:
        # The grace reading is only reconstructible with these two, and they are
        # gone from the row by the time anybody looks.
        self._apply(
            "needs_input", [events.OVERLAY_WORKING], own_activity=1234.0, last_activity=5678.0
        )
        record = self.state.disputes[0]
        self.assertEqual((1234.0, 5678.0), (record["own_activity"], record["last_activity"]))

    def test_the_record_holds_no_session_content(self) -> None:
        self._apply("needs_input", [events.OVERLAY_WORKING])
        flattened = json.dumps(self.state.disputes[0])
        self.assertNotIn("a prompt the user typed", flattened)
        self.assertNotIn("ExitPlanMode", flattened)

    def test_promoting_an_idle_row_to_working_is_not_a_dispute(self) -> None:
        # The ordinary path. Counting it would bury the case this exists to find.
        self._apply("idle", [events.OVERLAY_WORKING])
        self.assertEqual(0, self.state.dispute_total)
        self.assertEqual([], list(self.state.disputes))

    def test_an_overlay_agreeing_with_a_collected_wait_is_not_a_dispute(self) -> None:
        self._apply("needs_input", [events.OVERLAY_NEEDS_INPUT])
        self.assertEqual(0, self.state.dispute_total)

    def test_an_overlay_retiring_a_wait_to_idle_is_recorded_too(self) -> None:
        # Idle is as wrong as Working for a session holding a question, and the
        # dwell makes it the likelier of the two to arrive late.
        self._apply("needs_input", [events.OVERLAY_IDLE])
        self.assertEqual("idle", self.state.disputes[0]["overlay_state"])

    def test_the_patch_is_applied_either_way(self) -> None:
        # Recording is not deciding. Changing the outcome here is the follow-up,
        # and it needs the counts this produces.
        session = self._apply("needs_input", [events.OVERLAY_WORKING])
        self.assertEqual("working", session["state"])
        self.assertEqual(1, self.state.dispute_total)

    def test_a_standing_disagreement_is_one_record_however_often_it_is_collected(self) -> None:
        # Collections run at the memo floor, so a 90-second disagreement was
        # writing dozens of records: the ring filled with one episode and
        # `dispute_total` counted polls rather than faults.
        overlays = [
            events.Overlay(
                harness="claude",
                sid=PREFIX,
                arrival_seq=1,
                kind=events.OVERLAY_WORKING,
                at=support.SERVER_STARTED - 10,
            )
        ]
        app = support.build_app()
        app.overlays = self.Source(overlays)
        for tick in range(12):
            session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
            app._apply_overlays([session], now=support.SERVER_STARTED + tick)
        self.assertEqual(1, self.state.dispute_total)
        self.assertEqual(1, len(self.state.disputes))
        record = self.state.disputes[0]
        self.assertEqual(11, record["repeats"], "the repeats count is how long it stood")
        self.assertEqual(support.SERVER_STARTED, record["at"])
        self.assertEqual(support.SERVER_STARTED + 11, record["last_seen_at"])

    def test_a_new_overlay_arriving_starts_a_new_episode(self) -> None:
        # The shape changed, so this is a second fault rather than the same one
        # seen again, and merging them would hide it.
        app = support.build_app()
        for seq in (1, 2):
            app.overlays = self.Source(
                [
                    events.Overlay(
                        harness="claude",
                        sid=PREFIX,
                        arrival_seq=seq,
                        kind=events.OVERLAY_WORKING,
                        at=support.SERVER_STARTED,
                    )
                ]
            )
            session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
            app._apply_overlays([session], now=support.SERVER_STARTED)
        self.assertEqual(2, self.state.dispute_total)

    def test_a_churning_fan_out_underneath_a_standing_wait_is_still_one_episode(self) -> None:
        # Subagent overlays patch no state, so a child transition changes the
        # disagreement not at all, but each is remembered with a fresh sequence.
        # Counting them split one wait into a record per child, on exactly the
        # sessions DRC-4121 established are likeliest to be holding a prompt.
        working = events.Overlay(
            harness="claude",
            sid=PREFIX,
            arrival_seq=1,
            kind=events.OVERLAY_WORKING,
            at=support.SERVER_STARTED,
        )
        children: list[events.Overlay] = []
        app = support.build_app()
        for child in range(6):
            children.append(
                events.Overlay(
                    harness="claude",
                    sid=PREFIX,
                    arrival_seq=2 + child,
                    kind=events.OVERLAY_SUBAGENT,
                    at=support.SERVER_STARTED,
                    subagent_id=f"child-{child}",
                )
            )
            app.overlays = self.Source([working, *children])
            session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
            app._apply_overlays([session], now=support.SERVER_STARTED)
        self.assertEqual(1, self.state.dispute_total)
        self.assertEqual(5, self.state.disputes[0]["repeats"])

    def test_an_episode_for_a_session_that_vanished_does_not_stay_open(self) -> None:
        # A row that ages out reaches neither branch, so its episode would be
        # held open forever, pinning a record the ring may already have evicted.
        app = support.build_app()
        app.overlays = self.Source(
            [
                events.Overlay(
                    harness="claude",
                    sid=PREFIX,
                    arrival_seq=1,
                    kind=events.OVERLAY_WORKING,
                    at=support.SERVER_STARTED,
                )
            ]
        )
        session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
        app._apply_overlays([session], now=support.SERVER_STARTED)
        self.assertEqual(1, len(self.state.dispute_episodes))
        app._apply_overlays([], now=support.SERVER_STARTED)
        self.assertEqual({}, self.state.dispute_episodes)

    def test_agreement_closes_the_episode_so_the_next_one_is_its_own_record(self) -> None:
        app = support.build_app()
        overlays = [
            events.Overlay(
                harness="claude",
                sid=PREFIX,
                arrival_seq=1,
                kind=events.OVERLAY_WORKING,
                at=support.SERVER_STARTED,
            )
        ]
        app.overlays = self.Source(overlays)
        for collected in ("needs_input", "working", "needs_input"):
            session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": collected}
            app._apply_overlays([session], now=support.SERVER_STARTED)
        self.assertEqual(2, self.state.dispute_total)

    def test_an_emptied_ledger_closes_the_episode_too(self) -> None:
        # `_note_dispute` is not reached at all when a row has no overlays, so
        # the close has to happen on that branch or the episode never ends.
        app = support.build_app()
        session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
        app.overlays = self.Source(
            [
                events.Overlay(
                    harness="claude",
                    sid=PREFIX,
                    arrival_seq=1,
                    kind=events.OVERLAY_WORKING,
                    at=support.SERVER_STARTED,
                )
            ]
        )
        app._apply_overlays([dict(session)], now=support.SERVER_STARTED)
        app.overlays = self.Source([])
        app._apply_overlays([dict(session)], now=support.SERVER_STARTED)
        self.assertEqual({}, self.state.dispute_episodes)

    def test_the_record_carries_the_drop_counters_and_the_grace_it_was_read_against(self) -> None:
        # Readings 3 and 4 in N-5 are a counter comparison, and the live counters
        # are cumulative: a record read tomorrow can only bracket itself against
        # its neighbours if it carries its own copy. The grace is here for the
        # same reason, since a build can move the constant.
        app = support.build_app()
        app.overlays = self.Source(
            [
                events.Overlay(
                    harness="claude",
                    sid=PREFIX,
                    arrival_seq=1,
                    kind=events.OVERLAY_WORKING,
                    at=support.SERVER_STARTED,
                )
            ],
            counters={"reject.unmappable-id": 4, "pending.expired": 1},
        )
        session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
        app._apply_overlays([session], now=support.SERVER_STARTED)
        record = self.state.disputes[0]
        self.assertEqual({"reject.unmappable-id": 4, "pending.expired": 1}, record["drop_counters"])
        self.assertEqual(
            support.cfg().overlay_wait_activity_grace_sec, record["activity_grace_sec"]
        )

    def test_the_ring_is_bounded_by_config_rather_than_by_luck(self) -> None:
        # Without the maxlen wiring in __post_init__ the ring is unbounded, and
        # every other test here still passes.
        self.assertEqual(support.cfg().dispute_log_max, self.state.disputes.maxlen)

    def test_the_ring_is_bounded_while_the_total_keeps_counting(self) -> None:
        # A machine should be able to report "this happened 60 times" long after
        # the ring has turned over. Six separate episodes, not one seen six
        # times: each overlay carries its own arrival sequence, which is what
        # makes it a new fault rather than the same one still standing.
        self.state.disputes = deque(maxlen=4)
        app = support.build_app()
        for seq in range(1, 7):
            app.overlays = self.Source(
                [
                    events.Overlay(
                        harness="claude",
                        sid=PREFIX,
                        arrival_seq=seq,
                        kind=events.OVERLAY_WORKING,
                        at=support.SERVER_STARTED,
                    )
                ]
            )
            session: dict[str, Any] = {"harness": "claude", "sid": PREFIX, "state": "needs_input"}
            app._apply_overlays([session], now=support.SERVER_STARTED)
        self.assertEqual(4, len(self.state.disputes))
        self.assertEqual(6, self.state.dispute_total)


class _NoCommandReports:
    def command_reports(self) -> list[dict[str, Any]]:
        return []


class ApplicationOverlayTest(support.RuntimeTestCase):
    """The other half: what a collection does with the ledger.

    `RuntimeTestCase` rather than a bare `TestCase` and a bare `reset_runtime`,
    because `_collect_with` runs a full `aggregate.collect`, whose `_notify_waits`
    reaches the real notifier: these three tests sent three audible banners to
    the machine running the suite (DRC-4431).
    """

    @contextlib.contextmanager
    def _seeded(self, overlays: Any) -> Iterator[aggregate.Application]:
        """One quiet Claude session on a redirected store, with an overlay source.

        A context manager rather than a collect-and-return helper because
        `collect_json` has to run inside the store redirect too, and the
        published bytes are the only place AC5's second half can be observed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = projects / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / f"{PREFIX}-0000-0000-0000-000000000000.jsonl"
            transcript.write_text(json.dumps({"type": "user", "uuid": "u"}) + "\n")
            quiet = support.SERVER_STARTED - 300
            os.utime(transcript, (quiet, quiet))
            with (
                support.store_patch(PROJECTS_DIR=str(projects)),
                support.store_patch(TASKS_DIR=str(projects / "tasks")),
            ):
                config, _state = support.runtime()
                self.assertEqual(
                    (str(projects),),
                    config.store_roots["claude.projects"],
                    "the store redirect did not take, so this read the real store",
                )
                app = support.build_app()
                app.overlays = overlays
                app.clock = lambda: support.SERVER_STARTED
                yield app

    def _collect_with(self, overlays: Any) -> dict[str, Any]:
        with self._seeded(overlays) as app:
            collection: dict[str, Any] = app.collect(show_all=False)
            return collection

    def _row(self, collection: dict[str, Any]) -> dict[str, Any]:
        rows = [s for s in collection["sessions"] if s["sid"] == PREFIX]
        self.assertEqual(1, len(rows), "the seeded session was not collected")
        row: dict[str, Any] = rows[0]
        return row

    def test_with_no_overlay_source_a_collection_is_unchanged(self) -> None:
        # This is what --no-events leaves behind, so it has to be the old path
        # exactly rather than a variant of the new one.
        row = self._row(self._collect_with(None))
        self.assertEqual("idle", row["state"])
        # Present and None, not absent. Since DRC-4473 `base_session` declares
        # the key for every harness, so the reading is the value: None is "no
        # provenance stated", and the assertion is that nothing claimed one.
        self.assertIsNone(row["acquisition"])

    def test_a_live_overlay_patches_the_matching_row(self) -> None:
        class Source(_NoCommandReports):
            def __init__(self) -> None:
                self.noted: set[tuple[str, str]] = set()

            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                if (harness, sid) != ("claude", PREFIX):
                    return []
                return [
                    events.Overlay(
                        harness="claude",
                        sid=PREFIX,
                        arrival_seq=1,
                        kind=events.OVERLAY_NEEDS_INPUT,
                        at=support.SERVER_STARTED - 10,
                    )
                ]

            def finished_at(self, harness: str, sid: str) -> float:
                del harness, sid  # this stub remembers no stop
                return 0.0

            def ended_at(self, harness: str, sid: str) -> float:
                """No end observed: this stub answers only about stops."""
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                self.noted = keys

        source = Source()
        row = self._row(self._collect_with(source))
        self.assertEqual("needs_input", row["state"])
        self.assertEqual(events.ACQUISITION_EVENT, row["acquisition"])
        self.assertIn(("claude", PREFIX), source.noted)

    def test_the_summary_counts_the_patched_state_not_the_collected_one(self) -> None:
        # Patching after the summary was counted would show a needs-input row in
        # a board reporting zero waiting sessions.
        class Source(_NoCommandReports):
            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                if (harness, sid) != ("claude", PREFIX):
                    return []
                return [
                    events.Overlay(
                        harness="claude",
                        sid=PREFIX,
                        arrival_seq=1,
                        kind=events.OVERLAY_NEEDS_INPUT,
                        at=support.SERVER_STARTED - 10,
                    )
                ]

            def finished_at(self, harness: str, sid: str) -> float:
                del harness, sid  # this stub remembers no stop
                return 0.0

            def ended_at(self, harness: str, sid: str) -> float:
                """No end observed: this stub answers only about stops."""
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        collection = self._collect_with(Source())
        self.assertEqual(1, collection["summary"]["needs_input"])

    def test_a_remembered_stop_reaches_the_row_with_no_overlay_left(self) -> None:
        # The `claude -p` row: the ledger is gone, the mark is not, and the
        # session still has to publish that its turn ended.
        class Source(_NoCommandReports):
            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                del harness, sid
                return []

            def finished_at(self, harness: str, sid: str) -> float:
                if (harness, sid) != ("claude", PREFIX):
                    return 0.0
                # After the transcript's last write, which is what a session
                # that stopped and stayed stopped looks like.
                return support.SERVER_STARTED - 200

            def ended_at(self, harness: str, sid: str) -> float:
                """No end observed: this stub answers only about stops."""
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        row = self._row(self._collect_with(Source()))
        self.assertEqual("idle", row["state"], "the collector still owns the state")
        self.assertEqual(support.SERVER_STARTED - 200, row["finished_at"])

    def test_a_remembered_end_reaches_the_row_with_no_overlay_left(self) -> None:
        # The other half of the `claude -p` row, and the one DRC-4036 adds:
        # `session_ended` pops the ledger that would have carried this, so the
        # only path onto the row is the coordinator's own memory. Activity AFTER
        # the end is deliberate — a real end lands after the transcript's last
        # write — and it proves the stop's staleness guard is not applied here.
        class Source(_NoCommandReports):
            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                del harness, sid
                return []

            def finished_at(self, harness: str, sid: str) -> float:
                del harness, sid
                return 0.0

            def ended_at(self, harness: str, sid: str) -> float:
                if (harness, sid) != ("claude", PREFIX):
                    return 0.0
                return support.SERVER_STARTED - 200

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        row = self._row(self._collect_with(Source()))
        self.assertEqual("idle", row["state"], "the collector still owns the state")
        self.assertEqual(support.SERVER_STARTED - 200, row["ended_at"])
        self.assertIsNone(row["finished_at"], "an end is not a stop")

    def test_an_observed_terminal_reaches_the_row_so_a_raise_can_be_offered(self) -> None:
        # The seam `ended_at` above is tested across and `focusable` was not.
        # Deleting the one line in `aggregate.py` that copies it onto the row
        # left the whole suite green, because every `OverlaySource` stub here
        # returns False and `sessions.py` already defaults the field to False,
        # so the stubs agreed with the mutant. What shipped in that state was a
        # board where no RAISE renders on any row and the coverage line says so
        # in well-chosen words: a confident absence over a working feature.
        class Source(_NoCommandReports):
            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                del harness, sid
                return []

            def finished_at(self, harness: str, sid: str) -> float:
                del harness, sid
                return 0.0

            def ended_at(self, harness: str, sid: str) -> float:
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                # True for this row alone, so the assertion cannot pass off a
                # blanket default the way a stub returning True everywhere would.
                return (harness, sid) == ("claude", PREFIX)

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        # The stub answers True for this one key and False for anything else, so
        # a True on the row cannot have come from a blanket default: it can only
        # have crossed the seam. That makes the positive assertion sufficient on
        # its own, and the fixture seeds a single session anyway.
        self.assertIs(True, self._row(self._collect_with(Source()))["focusable"])

    def test_a_row_with_no_observed_end_publishes_none_rather_than_a_verdict(self) -> None:
        # The session that predates this server run, which has no mark at all.
        # None means not observed; it must never read as "did not end", because
        # an absent end is also what a SIGKILL and every adapter-less harness
        # look like.
        class Source(_NoCommandReports):
            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                del harness, sid
                return []

            def finished_at(self, harness: str, sid: str) -> float:
                del harness, sid
                return 0.0

            def ended_at(self, harness: str, sid: str) -> float:
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        row = self._row(self._collect_with(Source()))
        self.assertIsNone(row["ended_at"])

    def test_a_harness_with_no_event_adapter_publishes_that_it_is_scan_only(self) -> None:
        # N-9 in `docs/design-needs-input.md`, "Letting a collector infer
        # completion" (DRC-4035): six harnesses can never earn a stop, so their
        # idle rows must say the answer is unknowable here rather than share the
        # silence of a Claude row that simply has not finished.
        config, state = support.runtime()

        def collect_one(harness: str) -> Any:
            def collect(
                _config: Any, _state: Any, _when: float, _window: float, _show_all: bool
            ) -> list[Any]:
                return [runtime_sessions.base_session(harness, f"{harness}-1", "proj")]

            return collect

        application = aggregate.Application(
            config,
            state,
            tuple(
                aggregate.HarnessSpec(
                    key=key, label=key, discover=lambda *_: True, collect=collect_one(key)
                )
                for key in ("claude", "goose")
            ),
            native_notifier=lambda _platform: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _message: None,
            clock=lambda: support.SERVER_STARTED,
        )
        rows = {str(row["harness"]): row for row in application.collect(show_all=True)["sessions"]}
        self.assertEqual(events.ACQUISITION_SCAN, rows["goose"]["acquisition"])
        self.assertIsNone(
            rows["claude"]["acquisition"],
            "a harness that can earn a stop must not be marked unknowable",
        )

    def test_a_probed_row_reaches_the_published_bytes_carrying_no_pathname(self) -> None:
        # AC5's named oracle, which did not exist: a distinctive porcelain
        # pathname fed through the REAL parse, the reading carried by an overlay
        # source, and the assertion taken on `collect_json()`'s bytes rather than
        # on a hand-built dict. The test this replaces passed its marker to
        # nothing and read `json.dumps(session)`, so it was true of any
        # implementation — including one that published the porcelain whole.
        #
        # It is also the only pin on `aggregate._apply_overlays`'s `git=`
        # forward: that line was measured entirely unpinned, and forcing it to
        # None left the suite green, so the aggregate half of the feature could
        # have been dead on arrival with CI green.
        marker = "a-very-distinctive-filename-8f3c21.txt"
        # A distinctive DIRECTORY too, not a plausible word like "another": the
        # assertion is an absence, so a component that could legitimately appear
        # in the payload for an unrelated reason makes the test flake instead of
        # catching anything.
        directory = "a-very-distinctive-dirname-4b7e05"
        porcelain = f" M {marker}\n?? {directory}/{marker}\n".encode()

        def runner(*_args: object, **_kwargs: object) -> Any:
            return SimpleNamespace(returncode=0, stdout=porcelain, stderr=b"")

        reading = git_status.probe("/", timeout_sec=1.0, runner=runner)
        self.assertIsNotNone(reading, "the fixture never reached the parse")

        class Source(_NoCommandReports):
            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                del harness, sid  # the ledger `session_ended` popped
                return []

            def finished_at(self, harness: str, sid: str) -> float:
                if (harness, sid) != ("claude", PREFIX):
                    return 0.0
                return support.SERVER_STARTED - 200

            def ended_at(self, harness: str, sid: str) -> float:
                """No end observed: this stub answers only about stops."""
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> Any:
                if (harness, sid) != ("claude", PREFIX):
                    return None
                return reading

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        with self._seeded(Source()) as app:
            _revision, body = app.collect_json(show_all=False)
        published = json.loads(body)
        row = next(s for s in published["sessions"] if s["sid"] == PREFIX)
        self.assertEqual(True, row["dirty"], "the reading never reached the wire")
        self.assertEqual(2, row["changed"])
        self.assertNotIn(marker, body.decode())
        self.assertNotIn(directory, body.decode())

    def test_an_unprobed_row_publishes_both_keys_as_null_in_the_bytes(self) -> None:
        # AC6 at the wire, and the half a row-level assertion cannot make: the
        # keys must be PRESENT and null, because an absent key and a false one
        # render identically in a consumer that reads `row.dirty || …`.
        class Source(_NoCommandReports):
            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                del harness, sid
                return []

            def finished_at(self, harness: str, sid: str) -> float:
                del harness, sid
                return 0.0

            def ended_at(self, harness: str, sid: str) -> float:
                """No end observed: this stub answers only about stops."""
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        with self._seeded(Source()) as app:
            _revision, body = app.collect_json(show_all=False)
        row = next(s for s in json.loads(body)["sessions"] if s["sid"] == PREFIX)
        self.assertIn("dirty", row)
        self.assertIn("changed", row)
        self.assertIsNone(row["dirty"])
        self.assertIsNone(row["changed"])

    def test_an_overlay_for_an_unknown_session_creates_no_row(self) -> None:
        class Source(_NoCommandReports):
            def __init__(self) -> None:
                self.asked: list[tuple[str, str]] = []

            def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
                self.asked.append((harness, sid))
                return [
                    events.Overlay(
                        harness="claude",
                        sid="ffffffff",
                        arrival_seq=1,
                        kind=events.OVERLAY_NEEDS_INPUT,
                        at=support.SERVER_STARTED,
                    )
                ]

            def finished_at(self, harness: str, sid: str) -> float:
                del harness, sid  # this stub remembers no stop
                return 0.0

            def ended_at(self, harness: str, sid: str) -> float:
                """No end observed: this stub answers only about stops."""
                del harness, sid
                return 0.0

            def git_for(self, harness: str, sid: str) -> None:
                """Never probed: this stub has no repository behind it."""
                del harness, sid

            def focusable(self, harness: str, sid: str) -> bool:
                """No terminal identity: this stub observed no session start."""
                del harness, sid
                return False

            def note_rows(self, keys: set[tuple[str, str]]) -> None:
                pass

        source = Source()
        collection = self._collect_with(source)
        self.assertNotIn("ffffffff", [s["sid"] for s in collection["sessions"]])
        # The row list is walked, not the ledger, which is what makes that true.
        self.assertNotIn(("claude", "ffffffff"), source.asked)


def _iso(at: float) -> str:
    return datetime.datetime.fromtimestamp(at, tz=datetime.UTC).isoformat()


class _StopSource(_NoCommandReports):
    """One remembered Claude stop and the idle overlay that recorded it (DRC-4770)."""

    def __init__(self, stopped: float) -> None:
        self.stopped = stopped

    def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
        if (harness, sid) != ("claude", PREFIX):
            return []
        return [
            events.Overlay(
                harness="claude",
                sid=PREFIX,
                arrival_seq=1,
                kind=events.OVERLAY_IDLE,
                at=self.stopped,
                effective_at=self.stopped,
            )
        ]

    def finished_at(self, harness: str, sid: str) -> float:
        return self.stopped if (harness, sid) == ("claude", PREFIX) else 0.0

    def ended_at(self, harness: str, sid: str) -> float:
        """No end observed: a turn stop alone."""
        del harness, sid
        return 0.0

    def git_for(self, harness: str, sid: str) -> None:
        """Never probed."""
        del harness, sid

    def focusable(self, harness: str, sid: str) -> bool:
        """No terminal identity."""
        del harness, sid
        return False

    def note_rows(self, keys: set[tuple[str, str]]) -> None:
        pass

    def drop_counters(self) -> dict[str, int]:
        return {}


class ClaudeStopSurvivesBookkeepingTest(support.RuntimeTestCase):
    """DRC-4770: a non-conversation append does not retire an observed Claude stop.

    Claude Code appends a `system`/`away_summary` record minutes after a turn
    stops. Read as transcript mtime, that append retired the stop through the
    overlay reducer's activity guard, so a reading was withheld `idle-unknown`
    on nearly every hooked session. The guard now reads the newest conversation
    record, the definition `project_context.claude_activity_between` already
    uses, while a subagent writing still retires the stop (DRC-4101).
    """

    def _collect(
        self,
        records: list[dict[str, Any]],
        *,
        mtime: float,
        stopped: float,
        subagent_mtime: float | None = None,
    ) -> tuple[dict[str, Any], str]:
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = projects / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / f"{PREFIX}-0000-0000-0000-000000000000.jsonl"
            transcript.write_text("".join(json.dumps(r) + "\n" for r in records))
            os.utime(transcript, (mtime, mtime))
            if subagent_mtime is not None:
                agents = project / transcript.stem / "subagents"
                agents.mkdir(parents=True)
                agent = agents / "agent-a1b2c3.jsonl"
                agent.write_text(json.dumps({"type": "user", "uuid": "c"}) + "\n")
                os.utime(agent, (subagent_mtime, subagent_mtime))
            with (
                support.store_patch(PROJECTS_DIR=str(projects)),
                support.store_patch(TASKS_DIR=str(projects / "tasks")),
            ):
                config, _state = support.runtime()
                self.assertEqual((str(projects),), config.store_roots["claude.projects"])
                app = support.build_app()
                app.overlays = _StopSource(stopped)
                app.clock = lambda: support.SERVER_STARTED
                collection = app.collect(show_all=False)
                rows = [s for s in collection["sessions"] if s["sid"] == PREFIX]
                self.assertEqual(1, len(rows), "the seeded session was not collected")
                # The other definition, read over the same file at the same moment.
                resumed = project_context.claude_activity_between(
                    str(transcript),
                    stopped + config.overlay_wait_activity_grace_sec,
                    support.SERVER_STARTED,
                )
                return rows[0], "resumed" if resumed else "parked"

    @staticmethod
    def _turn(at: float) -> list[dict[str, Any]]:
        return [
            {
                "type": "user",
                "uuid": "u",
                "timestamp": _iso(at - 30),
                "message": {"role": "user", "content": "do the work"},
            },
            {
                "type": "assistant",
                "uuid": "a",
                "timestamp": _iso(at),
                "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            },
        ]

    @staticmethod
    def _away(at: float) -> dict[str, Any]:
        return {"type": "system", "subtype": "away_summary", "timestamp": _iso(at)}

    def test_an_away_summary_after_the_stop_keeps_it_long_after_the_append(self) -> None:
        t = support.SERVER_STARTED - 400
        row, resumed = self._collect(
            [*self._turn(t), self._away(t + 180)], mtime=t + 180, stopped=t + 1
        )
        self.assertEqual("idle", row["state"])
        self.assertEqual(t + 1, row["finished_at"])
        self.assertEqual("turn-stop", reading.end_kind(row))
        self.assertEqual("parked", resumed, "the two definitions of resumed disagree")

    def test_an_away_summary_inside_the_working_window_keeps_the_stop(self) -> None:
        # The append is newer than `working_threshold_sec`, so the collector
        # alone calls the row working; the idle overlay must still apply.
        t = support.SERVER_STARTED - 185
        row, resumed = self._collect(
            [*self._turn(t), self._away(t + 180)], mtime=t + 180, stopped=t + 1
        )
        self.assertEqual("idle", row["state"])
        self.assertEqual(t + 1, row["finished_at"])
        self.assertEqual("turn-stop", reading.end_kind(row))
        self.assertEqual("parked", resumed)

    def test_an_assistant_record_after_the_stop_still_retires_it(self) -> None:
        t = support.SERVER_STARTED - 400
        later = {
            "type": "assistant",
            "uuid": "b",
            "timestamp": _iso(t + 180),
            "message": {"role": "assistant", "content": [{"type": "text", "text": "more"}]},
        }
        row, resumed = self._collect([*self._turn(t), later], mtime=t + 180, stopped=t + 1)
        self.assertIsNone(row["finished_at"], "DRC-4101: a resumed session is not stopped")
        self.assertNotEqual("turn-stop", reading.end_kind(row))
        self.assertEqual("resumed", resumed, "the two definitions of resumed disagree")

    def test_a_subagent_writing_after_the_stop_still_retires_it(self) -> None:
        t = support.SERVER_STARTED - 400
        row, _resumed = self._collect(self._turn(t), mtime=t, stopped=t + 1, subagent_mtime=t + 180)
        self.assertIsNone(row["finished_at"])
        self.assertNotEqual("turn-stop", reading.end_kind(row))

    def test_the_row_publishes_the_activity_the_guard_read(self) -> None:
        t = support.SERVER_STARTED - 400
        row, _ = self._collect([*self._turn(t), self._away(t + 180)], mtime=t + 180, stopped=t + 1)
        self.assertEqual(t, row["work_activity"])
        self.assertEqual(t + 180, row["last_activity"], "freshness still reads the mtime")


class WiringTest(unittest.TestCase):
    """Assembly: who builds the coordinator, and who starts it."""

    def test_the_cli_attaches_a_coordinator_both_ways(self) -> None:
        captured: dict[str, Any] = {}

        class CapturingServer:
            def __init__(
                self,
                _address: tuple[str, int],
                application: Any,
                _page: bytes,
                coordinator: Any = None,
                *,
                interaction_prototype: Any = None,
            ) -> None:
                del interaction_prototype
                captured["application"] = application
                captured["coordinator"] = coordinator

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                pass

        self._run_main(CapturingServer, [])
        self.assertIsNotNone(captured["coordinator"])
        self.assertIs(captured["coordinator"], captured["application"].overlays)

    def test_no_events_leaves_the_application_without_an_overlay_source(self) -> None:
        captured: dict[str, Any] = {}

        class CapturingServer:
            def __init__(
                self,
                _address: tuple[str, int],
                application: Any,
                _page: bytes,
                coordinator: Any = None,
                *,
                interaction_prototype: Any = None,
            ) -> None:
                del interaction_prototype
                captured["application"] = application
                captured["coordinator"] = coordinator

            def serve_forever(self) -> None:
                raise KeyboardInterrupt

            def server_close(self) -> None:
                pass

        self._run_main(CapturingServer, ["--no-events"])
        self.assertIsNone(captured["coordinator"])
        self.assertIsNone(captured["application"].overlays)

    def _run_main(self, server_class: Any, extra: list[str]) -> None:
        with (
            mock.patch.object(http_api, "CompassHTTPServer", server_class),
            mock.patch.object(lifecycle, "write_state"),
            mock.patch.object(lifecycle, "remove_state"),
            mock.patch.object(runtime_supervise, "kill_all"),
            mock.patch.object(runtime_io, "diag"),
            contextlib.suppress(KeyboardInterrupt),
        ):
            cli.main(["--port", "4553", *extra])

    def test_serve_starts_the_coordinator_instead_of_the_producer(self) -> None:
        events_seen: list[str] = []

        class FakeCoordinator:
            def capabilities(self) -> dict[str, str]:
                events_seen.append("capabilities")
                return {"claude": "token"}

            def start(self) -> None:
                events_seen.append("start")

            def stop(self, *, timeout: float) -> None:  # noqa: ARG002 (signature parity)
                events_seen.append("stop")

        class FakeServer:
            observation = FakeCoordinator()
            application = None

            def serve_forever(self) -> None:
                events_seen.append("serve")

            def server_close(self) -> None:
                pass

        config = support.make_config()
        with (
            mock.patch.object(lifecycle, "write_state"),
            mock.patch.object(lifecycle, "remove_state"),
            mock.patch.object(lifecycle, "run_producer") as producer,
            # The real one closes this worker's runner for every later test.
            mock.patch.object(runtime_supervise, "kill_all"),
        ):
            lifecycle.serve(
                config,
                FakeServer(),  # type: ignore[arg-type]
                4553,
                started=NOW,
                diagnostic_sink=lambda _message: None,
            )
        # capabilities before start: the tokens are published by write_state, and
        # a hook that fires the instant the worker begins must find them already
        # on disk rather than racing the write.
        self.assertEqual(["capabilities", "start", "serve", "stop"], events_seen)
        producer.assert_not_called()

    def test_serve_falls_back_to_the_producer_without_a_coordinator(self) -> None:
        class FakeServer:
            application = None

            def serve_forever(self) -> None:
                pass

            def server_close(self) -> None:
                pass

        config = support.make_config()
        with (
            mock.patch.object(lifecycle, "write_state"),
            mock.patch.object(lifecycle, "remove_state"),
            mock.patch.object(lifecycle, "run_producer") as producer,
            # The real one closes this worker's runner for every later test.
            mock.patch.object(runtime_supervise, "kill_all"),
        ):
            lifecycle.serve(
                config,
                FakeServer(),  # type: ignore[arg-type]
                4553,
                started=NOW,
                diagnostic_sink=lambda _message: None,
            )
        producer.assert_called_once()


class AskPayloadTest(unittest.TestCase):
    """What a collection publishes for the questions a session asked.

    Collection is the only sweep the ask registry gets, so these also stand as
    the test that a stale ask is retired by being collected rather than by a
    timer nobody runs.
    """

    def _runtime(self, **changes: Any) -> tuple[Any, Any]:
        from compass_runtime.state import build_runtime_state  # noqa: PLC0415

        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        fields: dict[str, Any] = {
            "state_home": home.name,
            "state_dir": Path(home.name),
            "os_name": support.os_name(),
        }
        fields.update(changes)
        config = support.make_config(**fields)
        return config, build_runtime_state(config, started=NOW)

    def _application(self, config: Any, state: Any, *, clock: float = NOW) -> aggregate.Application:
        return aggregate.Application(
            config,
            state,
            (),
            native_notifier=lambda _platform: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=lambda _message: None,
            clock=lambda: clock,
        )

    def _ask(
        self,
        state: Any,
        *,
        created: float,
        question: str = "Ship it?",
        limit: int = 8,
        config: Any = None,
    ) -> Any:
        """Register one ask the way the route does, or fail the test.

        With `config`, the real deadline and retention are used, so registration
        sweeps exactly as it does in the daemon. Without it the windows are
        absurd, which keeps a test about the payload from also being a test about
        the sweep.
        """
        ask = runtime_asks.PendingAsk(
            harness="claude",
            session_id=SESSION,
            project="compass",
            question=question,
            options=("yes", "no"),
            created=created,
        )
        deadline = 10_000.0 if config is None else config.ask_deadline_sec
        retention = 10_000.0 if config is None else config.ask_retention_sec
        self.assertTrue(
            state.asks.register(ask, limit=limit, deadline=deadline, retention=retention)
        )
        return ask

    def test_a_budget_full_of_answered_asks_does_not_wedge_a_tabless_dashboard(self) -> None:
        """The headline defect, end to end over the real registry and config.

        No collection happens anywhere in this test: no `/api/data`, no
        coordinator tick, no `pending`. That is a dashboard with no browser tab
        open, which is the run the ask lane exists for, and it is where the lane
        used to wedge shut for the rest of the process. Measured before the fix,
        with the cap filled and 14 answered: 503 at t+10s, t+321s and t+341s
        while the payload reported zero cards.

        The two registrations below fail for different reasons, which is why both
        are here. At t+10 nothing is overdue, so only the budget counting
        unresolved asks can accept it. At t+301 the budget is not the problem and
        the registration sweep is.
        """
        config, state = self._runtime()
        limit = config.ask_max_pending
        filled = [
            self._ask(state, created=NOW, question=f"Q{index}?", limit=limit, config=config)
            for index in range(limit)
        ]
        for ask in filled[:14]:
            self.assertTrue(state.asks.answer(ask.id, 0))

        early = self._register(state, config, created=NOW + 10.0, question="Early?")
        self.assertTrue(early, "an answered ask holds no slot worth rationing")
        late = self._register(state, config, created=NOW + 301.0, question="Late?")
        self.assertTrue(late, "the registry has to heal itself with nobody reading it")

        for ask in filled[14:]:
            self.assertEqual(("expired", None), ask.outcome, "aged out with nobody watching")
        for ask in filled[:14]:
            self.assertIsNone(state.asks.get(ask.id), "dropped once retention ran out")
            self.assertEqual(("answered", 0), ask.outcome, "the outcome outlives the row")
        self.assertEqual(2, state.asks.count)

    def _register(self, state: Any, config: Any, *, created: float, question: str) -> bool:
        """Register the way the route does, and report the refusal rather than fail."""
        ask = runtime_asks.PendingAsk(
            harness="claude",
            session_id=SESSION,
            project="compass",
            question=question,
            options=("yes", "no"),
            created=created,
        )
        accepted: bool = state.asks.register(
            ask,
            limit=config.ask_max_pending,
            deadline=config.ask_deadline_sec,
            retention=config.ask_retention_sec,
        )
        return accepted

    def test_a_pending_ask_reaches_the_payload_with_its_age(self) -> None:
        config, state = self._runtime()
        ask = self._ask(state, created=NOW - 42.4)
        data = self._application(config, state).collect(show_all=True)

        self.assertIs(True, data["ask"])
        self.assertEqual(
            [
                {
                    "id": ask.id,
                    "harness": "claude",
                    "session_id": SESSION,
                    "project": "compass",
                    "question": "Ship it?",
                    "options": ["yes", "no"],
                    "age_sec": 42,
                }
            ],
            data["asks"],
        )

    def test_the_flag_and_the_array_are_both_absent_with_the_feature_off(self) -> None:
        config, state = self._runtime(ask_enabled=False)
        self._ask(state, created=NOW)
        data = self._application(config, state).collect(show_all=True)

        self.assertNotIn("ask", data)
        self.assertNotIn("asks", data)

    def test_the_flag_rises_with_no_ask_outstanding(self) -> None:
        config, state = self._runtime()
        data = self._application(config, state).collect(show_all=True)

        self.assertIs(True, data["ask"])
        self.assertEqual([], data["asks"])

    def test_collecting_is_what_retires_an_ask_past_the_deadline(self) -> None:
        config, state = self._runtime(ask_deadline_sec=60.0)
        stale = self._ask(state, created=NOW - 61.0, question="Stale?")
        live = self._ask(state, created=NOW - 59.0, question="Live?")
        data = self._application(config, state).collect(show_all=True)

        self.assertEqual([live.id], [entry["id"] for entry in data["asks"]])
        self.assertEqual(("expired", None), stale.outcome)


class GitProbeDispatchTest(ObservationTestCase):
    """AC3 and AC4: where the probe runs, and on which edge it fires.

    The session-end edge arrives on an HTTP handler thread (`http_api` calls
    `submit` from inside a `ThreadingHTTPServer` request handler) behind the hook
    client's two-second timeout, and `_record` does its work under the coordinator
    lock. A probe run inline there would stall every other event behind the lock
    and hold the harness's own `SessionEnd` hook open past its timeout, on any
    repository big enough to take two seconds. Neither the ruling nor the merged
    contract names this; it was found by reading the tip, and these are its tests.
    """

    def end_envelope(self, **overrides: Any) -> dict[str, Any]:
        payload = self.envelope(event="session_ended", cwd="/repo/somewhere")
        payload.update(overrides)
        return payload

    def test_submit_returns_without_waiting_for_the_probe(self) -> None:
        # The falsifier: calling the probe inline in `_record`. `submit` would
        # then block until `release` is set, and this test would deadlock rather
        # than fail — which is why the wait is bounded and asserted.
        started = threading.Event()
        release = threading.Event()

        def blocking(_cwd: str) -> git_status.GitStatus | None:
            started.set()
            release.wait(timeout=60.0)
            return git_status.GitStatus(dirty=True, changed=1)

        coordinator = self.build()
        coordinator._git_prober = blocking
        self.assertEqual("accepted", coordinator.submit("claude", self.end_envelope()))
        self.assertTrue(started.wait(timeout=30.0), "the probe never started")
        # submit() has already returned while the probe is still inside its call.
        self.assertIsNone(coordinator.git_for("claude", PREFIX))
        release.set()

    def test_the_probe_does_not_run_while_the_coordinator_lock_is_held(self) -> None:
        # The other half of AC3, and the one a reordering could break silently:
        # dispatching off-thread but from inside the `with self._lock` block would
        # still stall every other event for the probe's duration.
        held: list[bool] = []
        done = threading.Event()

        def observing(_cwd: str) -> git_status.GitStatus | None:
            acquired = coordinator._lock.acquire(blocking=False)
            held.append(not acquired)
            if acquired:
                coordinator._lock.release()
            done.set()
            return None

        coordinator = self.build()
        coordinator._git_prober = observing
        coordinator.submit("claude", self.end_envelope())
        self.assertTrue(done.wait(timeout=30.0), "the probe never ran")
        self.assertEqual([False], held, "the probe ran while the lock was held")

    def test_one_probe_per_session_end_and_on_no_other_edge(self) -> None:
        # Bound 3: one-shot on `session_ended`. The falsifier is hanging the probe
        # off `_mark_finished`, which pops on every working overlay and so re-arms
        # every turn — this sequence would produce two invocations there, both at
        # the wrong moment.
        calls: list[str] = []
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda cwd: calls.append(cwd) or None  # type: ignore[func-returns-value]
        for event in ("turn_stopped", "turn_started", "turn_stopped"):
            coordinator.submit("claude", self.envelope(event=event, cwd="/repo/somewhere"))
        self.assertEqual([], calls, "a turn edge fired the probe")
        coordinator.submit("claude", self.end_envelope())
        self.assertEqual(["/repo/somewhere"], calls)

    def test_two_session_ends_probe_once_each_and_never_a_third(self) -> None:
        # Claude fires `session_ended` on `/clear` as well as on exit, so "once
        # per session" is not observable and must not be asserted. Once per edge is.
        calls: list[str] = []
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda cwd: calls.append(cwd) or None  # type: ignore[func-returns-value]
        coordinator.submit("claude", self.end_envelope())
        coordinator.submit("claude", self.end_envelope())
        self.assertEqual(2, len(calls))

    def test_no_git_stops_the_probe_running_at_all(self) -> None:
        calls: list[str] = []
        coordinator = self.build(git_probe_enabled=False)
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda cwd: calls.append(cwd) or None  # type: ignore[func-returns-value]
        coordinator.submit("claude", self.end_envelope())
        self.assertEqual([], calls)
        self.assertIsNone(coordinator.git_for("claude", PREFIX))

    def test_an_event_with_no_cwd_is_not_probed(self) -> None:
        calls: list[str] = []
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda cwd: calls.append(cwd) or None  # type: ignore[func-returns-value]
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.assertEqual([], calls)
        self.assertIsNone(coordinator.git_for("claude", PREFIX))

    def test_a_reading_is_published_and_bounded_by_the_overlay_cap(self) -> None:
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda _cwd: git_status.GitStatus(dirty=True, changed=3)
        coordinator.submit("claude", self.end_envelope())
        reading = coordinator.git_for("claude", PREFIX)
        self.assertEqual(git_status.GitStatus(dirty=True, changed=3), reading)

    def test_a_session_that_works_again_discards_its_reading(self) -> None:
        # R2's second door, which the reducer's own guards do not reach. The
        # reading describes the tree at one session end; a `turn_started` says
        # that end is over. `_mark_finished` pops the stop mark on exactly this
        # edge, and the reading has to go with it — otherwise the NEXT
        # `turn_stopped` restores a truthy, non-stale `finished_at` and re-pairs
        # this reading with a stop it was not taken at.
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda _cwd: git_status.GitStatus(dirty=False, changed=0)
        coordinator.submit("claude", self.end_envelope())
        self.assertIsNotNone(coordinator.git_for("claude", PREFIX))
        coordinator.submit("claude", self.envelope(event="turn_started"))
        self.assertIsNone(coordinator.git_for("claude", PREFIX))

    def test_a_session_that_reaches_a_gate_discards_its_reading(self) -> None:
        # The same edge on the other kind of alive. A person being asked a
        # question means the session outlived the end that produced the reading.
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda _cwd: git_status.GitStatus(dirty=True, changed=2)
        coordinator.submit("claude", self.end_envelope())
        self.assertIsNotNone(coordinator.git_for("claude", PREFIX))
        coordinator.submit("claude", self.envelope(event="input_requested"))
        self.assertIsNone(coordinator.git_for("claude", PREFIX))

    def test_a_session_end_that_probes_nothing_does_not_keep_the_last_reading(self) -> None:
        # The resurrection the two retirements above exist to prevent, driven end
        # to end rather than one edge at a time. `session_ended` pops the overlay
        # ledger but NOT the stop mark, so after end → start → stop → end the mark
        # is truthy and non-stale and no overlay is left to null anything. If the
        # second end takes no reading — no `cwd` on the envelope is the ordinary
        # way, and a timeout or an absent git are the others — the FIRST end's
        # reading is the only one there is, and it would publish against a stop it
        # was not taken at. What keeps this null is the `turn_started` in the
        # middle discarding it, which is why clearing the reading on every
        # `session_ended` was tried and dropped: nothing needs it, and two ends
        # with no turn between them would lose a reading that is still accurate.
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda _cwd: git_status.GitStatus(dirty=False, changed=0)
        coordinator.submit("claude", self.end_envelope())
        for event in ("turn_started", "turn_stopped"):
            coordinator.submit("claude", self.envelope(event=event))
        coordinator.submit("claude", self.envelope(event="session_ended"))
        self.assertGreater(
            coordinator.finished_at("claude", PREFIX), 0.0, "the mark this pairs with is gone"
        )
        self.assertEqual([], coordinator.overlays_for("claude", PREFIX))
        self.assertIsNone(coordinator.git_for("claude", PREFIX))

    def test_a_mark_for_a_row_no_collection_produced_is_dropped(self) -> None:
        # The same bound `_finished` has: a mark for a session no longer collected
        # and holding no overlay can never render again, so it goes.
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda _cwd: git_status.GitStatus(dirty=True, changed=1)
        coordinator.submit("claude", self.end_envelope())
        self.assertIsNotNone(coordinator.git_for("claude", PREFIX))
        coordinator.note_rows(set())
        self.assertIsNone(coordinator.git_for("claude", PREFIX))


class GitProbeConcurrencyTest(ObservationTestCase):
    """DRC-4443: how many probes may be in flight, and what a refusal costs.

    `_spawn_thread` starts one daemon thread per dispatch and nothing counted
    them. Measured: the event budget alone allows 40 burst plus 20/s for the
    probe's whole 10 s life, so 240 live probe threads per harness and 960 across
    the four normalizers — and each is a real `git status` inside a real
    repository. The gate is `quota`'s, which this class already reuses for the
    focus command: claim under the lock, release in a `finally`.

    `_spawn` is injected as a collector rather than as `run` here, so the claim
    can be observed while it is held. Nothing in this class spawns a thread or a
    subprocess.
    """

    def end_envelope(self, **overrides: Any) -> dict[str, Any]:
        payload = self.envelope(event="session_ended", cwd="/repo/somewhere")
        payload.update(overrides)
        return payload

    @staticmethod
    def _collector(
        coordinator: observation.Observation,
    ) -> list[Callable[[], None]]:
        """Hold every dispatched probe unrun, so the claim stays held."""
        dispatched: list[Callable[[], None]] = []
        coordinator._spawn = dispatched.append
        return dispatched

    def test_a_second_probe_for_one_session_is_refused_while_the_first_is_in_flight(self) -> None:
        coordinator = self.build()
        coordinator._git_prober = lambda _cwd: None
        dispatched = self._collector(coordinator)
        self.assertEqual("accepted", coordinator.submit("claude", self.end_envelope()))
        self.assertEqual("accepted", coordinator.submit("claude", self.end_envelope()))
        self.assertEqual(1, len(dispatched), "an overlapping probe was dispatched")
        self.assertEqual(1, coordinator.counters["git.inflight"])
        # And the claim is released by the probe rather than held for the life of
        # the process: the next edge for the same session dispatches again.
        dispatched[0]()
        coordinator.submit("claude", self.end_envelope())
        self.assertEqual(2, len(dispatched))

    def test_a_probe_that_raised_still_releases_its_claim(self) -> None:
        # The `finally` is what this asserts. Without it a repository that makes
        # git raise disables probing for that session until the process restarts,
        # which is a worse outcome than the missing reading.
        coordinator = self.build()

        def raising(_cwd: str) -> git_status.GitStatus | None:
            raise OSError("git")

        coordinator._git_prober = raising
        dispatched = self._collector(coordinator)
        coordinator.submit("claude", self.end_envelope())
        dispatched[0]()
        self.assertEqual(1, coordinator.counters["git.failed"])
        coordinator.submit("claude", self.end_envelope())
        self.assertEqual(2, len(dispatched), "the raised probe kept its claim")

    def test_a_spawn_that_cannot_start_a_thread_releases_its_claim(self) -> None:
        # `Thread.start` raises RuntimeError when the interpreter can start no
        # more threads, and nothing in the repository injected a raising `_spawn`:
        # deleting that release branch wholesale left this module at 150 tests OK.
        # What it costs is not one lost reading. The claim is taken under the lock
        # and released by `_probe_and_mark`, which never runs if the spawn raised,
        # so the session is unprobeable for the life of the process.
        coordinator = self.build()
        coordinator._git_prober = lambda _cwd: None

        def exhausted(_run: Callable[[], None]) -> None:
            raise RuntimeError("can't start new thread")

        coordinator._spawn = exhausted
        self.assertEqual("accepted", coordinator.submit("claude", self.end_envelope()))
        self.assertEqual(1, coordinator.counters["git.failed"])
        self.assertEqual(set(), coordinator._git_inflight)
        # The claim released, so the next end for the SAME key dispatches rather
        # than meeting a gate holding a slot nothing will ever free.
        dispatched = self._collector(coordinator)
        self.assertEqual("accepted", coordinator.submit("claude", self.end_envelope()))
        self.assertEqual(1, len(dispatched), "the exhausted spawn kept its claim")
        self.assertNotIn("git.inflight", coordinator.counters)

    def test_the_probe_switched_off_claims_no_slot_for_the_ends_it_ignores(self) -> None:
        # The conjunction's order is load-bearing and no assertion could see it:
        # reordering to `self._claim_git(key) and self.config.git_probe_enabled
        # and event.cwd` also left this module at 150 tests OK. `_claim_git` has
        # an effect and the two flag checks do not, so under that ordering every
        # end claims a slot and nothing releases one. Measured with the probe off:
        # two ends left both keys in `_git_inflight` permanently with nothing
        # dispatched, which saturates the ceiling after
        # `git_probe_max_inflight` ends and makes `--no-git` a one-way switch.
        coordinator = self.build(git_probe_enabled=False)
        dispatched = self._collector(coordinator)
        for index in range(2):
            payload = self.end_envelope(session_id=f"{index:08x}-3456-7890-abcd-ef1234567890")
            self.assertEqual("accepted", coordinator.submit("claude", payload))
        self.assertEqual([], dispatched)
        self.assertEqual(set(), coordinator._git_inflight)
        self.assertEqual([], sorted(n for n in coordinator.counters if n.startswith("git.")))

    def test_five_hundred_session_ends_leave_a_bounded_number_in_flight(self) -> None:
        # The shape the ceiling was measured with, and the per-key gate alone does
        # not bound it: every submit here carries a DIFFERENT session id, which is
        # a payload field, so one token holder can vary it freely.
        coordinator = self.build()
        coordinator._git_prober = lambda _cwd: None
        dispatched = self._collector(coordinator)
        for index in range(500):
            payload = self.end_envelope(session_id=f"{index:08x}-3456-7890-abcd-ef1234567890")
            self.assertEqual("accepted", coordinator.submit("claude", payload))
        self.assertEqual(self.config.git_probe_max_inflight, len(dispatched))
        # `git.saturated`, not `git.inflight`: every key here is distinct, so the
        # per-key gate turned none of them away and the ceiling turned away all
        # 468. One counter for both causes could not tell those apart.
        self.assertEqual(
            500 - self.config.git_probe_max_inflight, coordinator.counters["git.saturated"]
        )
        self.assertNotIn("git.inflight", coordinator.counters)

    def test_the_ceiling_recovers_as_probes_finish(self) -> None:
        # A ceiling that never refilled would turn a burst into a permanently
        # dead feature rather than a delayed one.
        coordinator = self.build()
        coordinator._git_prober = lambda _cwd: None
        dispatched = self._collector(coordinator)
        for index in range(self.config.git_probe_max_inflight + 1):
            coordinator.submit(
                "claude", self.end_envelope(session_id=f"{index:08x}-3456-7890-abcd-ef1234567890")
            )
        self.assertEqual(self.config.git_probe_max_inflight, len(dispatched))
        for run in list(dispatched):
            run()
        coordinator.submit(
            "claude", self.end_envelope(session_id="ffffffff-3456-7890-abcd-ef1234567890")
        )
        self.assertEqual(self.config.git_probe_max_inflight + 1, len(dispatched))

    def test_the_refusal_keeps_the_reading_the_first_probe_produces(self) -> None:
        # R13, reproduced before the gate existed: two overlapping ends for ONE
        # key, a slow probe answering 111 and a fast one answering 222. The board
        # published 222 and then 111 as each returned, and nothing counted it.
        #
        # Last completion wins is the right rule for a reading whose freshness IS
        # its completion time — an arrival-order guard, of the kind `_finished`
        # and `_remember` use for event-carried values, would let the LATER
        # arrival win, which here is the seq-2 event whose fast probe finished
        # first and so read the tree earlier. So the fix is not a guard on the
        # write: it is that the second probe never runs.
        # Keyed on cwd, not on call order: which probe answers which number must
        # not depend on the order the probes are RUN in, or the reproduction reads
        # backwards, which it did once here.
        answers = {"/repo/slow": 111, "/repo/fast": 222}
        coordinator = self.build()
        coordinator._git_prober = lambda cwd: git_status.GitStatus(dirty=True, changed=answers[cwd])
        dispatched = self._collector(coordinator)
        coordinator.submit("claude", self.end_envelope(cwd="/repo/slow"))
        coordinator.submit("claude", self.end_envelope(cwd="/repo/fast"))
        self.assertEqual(1, len(dispatched), "the overlapping probe was dispatched")
        dispatched[0]()
        published = coordinator.git_for("claude", PREFIX)
        self.assertEqual(git_status.GitStatus(dirty=True, changed=111), published)
        self.assertEqual(1, coordinator.counters["git.inflight"])

    def test_only_the_session_end_edge_dispatches_a_probe(self) -> None:
        # The cadence claim, pinned against the whole vocabulary rather than the
        # three names a reader would think to try. `_spawn_thread`'s docstring
        # rests on it: at most once per edge, and only this edge.
        dispatching = set()
        for name in sorted(events.EVENT_NAMES):
            coordinator = self.build()
            coordinator._git_prober = lambda _cwd: None
            dispatched = self._collector(coordinator)
            payload = self.envelope(event=name, cwd="/repo/somewhere")
            if name == "command_shape_reported":
                payload = {
                    "v": 1,
                    "event": name,
                    "session_id": SESSION,
                    "timestamp": "2023-11-14T22:13:20Z",
                    "pattern_id": "git_force_push",
                    "tool_name": "Bash",
                }
            self.assertEqual("accepted", coordinator.submit("claude", payload), name)
            if dispatched:
                dispatching.add(name)
        self.assertEqual({"session_ended"}, dispatching)


class GitNullSurfaceTest(ObservationTestCase):
    """AC6: every cause of an unprobed row publishes null, and `acquisition` sees none of them.

    Written at the coordinator's own boundary because that is where all seven
    causes converge: five of them make the probe return None and two stop it
    running at all, and the row cannot tell the difference — which is the point.
    """

    def _reading(self, coordinator: Any) -> Any:
        return coordinator.git_for("claude", PREFIX)

    def test_a_harness_whose_adapter_carries_no_session_end_event_is_never_probed(self) -> None:
        # The cause a `scan-only` assertion cannot see. Codex HAS an event adapter,
        # so `_mark_unreachable_by_events` leaves its `acquisition` reading "event"
        # — but `CODEX_EVENTS` registers no SessionEnd, so no `session_ended` can
        # ever arrive for it and the row is never probed. A test asserting against
        # `scan-only` alone would pass while leaving Codex and Antigravity, two of
        # the eight unprobeable harnesses, entirely unchecked.
        self.assertNotIn("session_ended", set(event_hook.CODEX_EVENTS.values()))
        self.assertIn("codex", events.IDENTITY_NORMALIZERS)
        calls: list[str] = []
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda cwd: calls.append(cwd) or None  # type: ignore[func-returns-value]
        # The envelope a Codex adapter could actually send. Its vocabulary has no
        # session-end name, so this is refused before any probe is considered.
        coordinator.submit("codex", {"v": 1, "event": "session_ended", "session_id": SESSION})
        self.assertEqual([], calls)

    def test_a_probe_that_returns_nothing_publishes_nothing(self) -> None:
        # Covers four causes at once, because the module collapses them
        # deliberately: not a repository, git absent from PATH, a timeout, and a
        # git that refused. All five of those are `probe() -> None`.
        for cause in ("not-a-repo", "git-missing", "timed-out", "refused"):
            with self.subTest(cause=cause):
                coordinator = self.build()
                coordinator._spawn = lambda run: run()
                coordinator._git_prober = lambda _cwd: None
                coordinator.submit(
                    "claude",
                    self.envelope(event="session_ended", cwd="/repo/somewhere"),
                )
                self.assertIsNone(self._reading(coordinator))

    def test_a_reading_is_never_false_when_it_was_simply_not_taken(self) -> None:
        # The DRC-4101 shape, one field over: absent evidence must not render as a
        # confident clean. The falsifier is defaulting `dirty` to False anywhere on
        # the path, which would make this assertion pass for `changed` and fail here.
        coordinator = self.build()
        coordinator._spawn = lambda run: run()
        coordinator._git_prober = lambda _cwd: None
        coordinator.submit("claude", self.envelope(event="session_ended", cwd="/repo"))
        reading = self._reading(coordinator)
        self.assertIsNone(reading)
        self.assertIsNot(reading, False)

    def test_an_unprobed_row_carries_both_keys_as_none(self) -> None:
        row = runtime_sessions.base_session("goose", "goose-1", "proj")
        self.assertIsNone(row["dirty"])
        self.assertIsNone(row["changed"])


class GitPathnamePrivacyTest(unittest.TestCase):
    """AC5 at the module's own boundary: the parse cannot carry a pathname out.

    The other half — that no pathname reaches the bytes `/api/data` serves — is
    `ApplicationOverlayTest.test_a_probed_row_reaches_the_published_bytes_carrying_no_pathname`,
    which drives a real collection. The version that used to live here passed its
    marker to nothing and read `json.dumps` of a hand-built row, so it asserted
    something true of every possible implementation.
    """

    def test_a_porcelain_pathname_never_survives_the_parse(self) -> None:
        # The probe counts entries and drops the lines. Feeding it a distinctive
        # filename and asserting the reading cannot carry it is the whole check:
        # there is no field on `GitStatus` that could hold one.
        marker = "a-very-distinctive-filename-8f3c21.txt"
        # A distinctive DIRECTORY too, not a plausible word like "another": the
        # assertion is an absence, so a component that could legitimately appear
        # in the payload for an unrelated reason makes the test flake instead of
        # catching anything.
        directory = "a-very-distinctive-dirname-4b7e05"
        porcelain = f" M {marker}\n?? {directory}/{marker}\n".encode()

        def runner(*_args: object, **_kwargs: object) -> Any:
            return SimpleNamespace(returncode=0, stdout=porcelain, stderr=b"")

        reading = git_status.probe("/", timeout_sec=1.0, runner=runner)
        self.assertIsNotNone(reading)
        assert reading is not None
        self.assertEqual(2, reading.changed)
        self.assertTrue(reading.dirty)
        self.assertNotIn(marker, repr(reading))
        self.assertEqual({"dirty", "changed"}, set(dataclasses.asdict(reading)))


class RepeatingSourceCoordinatorTest(ObservationTestCase):
    """DRC-4203 / DRC-4573: Repeating-source coordinator behavior, age preservation, and explicit resolution."""

    def test_repeating_wait_preserves_blocked_since_across_renewals(self) -> None:
        coordinator = self.build()
        self.now = 100.0
        # Initial positive observation
        coordinator.submit(
            "antigravity",
            self.envelope(
                event="input_requested",
                session_id=SESSION,
                source_instance_id="statusline",
            ),
        )
        overlays_1 = coordinator.overlays_for("antigravity", SESSION)
        self.assertEqual(1, len(overlays_1))
        self.assertEqual(100.0, overlays_1[0].blocked_since)

        # Renewed positive observation at t=200
        self.now = 200.0
        coordinator.submit(
            "antigravity",
            self.envelope(
                event="input_requested",
                session_id=SESSION,
                source_instance_id="statusline",
            ),
        )
        overlays_2 = coordinator.overlays_for("antigravity", SESSION)
        self.assertEqual(1, len(overlays_2))
        self.assertEqual(200.0, overlays_2[0].at)
        self.assertEqual(100.0, overlays_2[0].blocked_since)

    def test_matching_explicit_resolution_pops_wait_slot_from_ledger(self) -> None:
        coordinator = self.build()
        self.now = 100.0
        coordinator.submit(
            "antigravity",
            self.envelope(
                event="input_requested",
                session_id=SESSION,
                source_instance_id="statusline",
            ),
        )
        self.assertEqual(1, len(coordinator.overlays_for("antigravity", SESSION)))

        # Heartbeat does not pop wait slot
        self.now = 110.0
        coordinator.submit(
            "antigravity",
            self.envelope(
                event="turn_started",
                session_id=SESSION,
                source_instance_id="statusline",
            ),
        )
        kinds = [o.kind for o in coordinator.overlays_for("antigravity", SESSION)]
        self.assertIn(events.OVERLAY_NEEDS_INPUT, kinds)

        # Matching input_resolved pops wait slot from ledger
        self.now = 120.0
        coordinator.submit(
            "antigravity",
            self.envelope(
                event="input_resolved",
                session_id=SESSION,
                source_instance_id="statusline",
            ),
        )
        kinds_after = [o.kind for o in coordinator.overlays_for("antigravity", SESSION)]
        self.assertNotIn(events.OVERLAY_NEEDS_INPUT, kinds_after)

    def test_unrelated_source_input_resolved_does_not_pop_wait_slot(self) -> None:
        coordinator = self.build()
        self.now = 100.0
        coordinator.submit(
            "antigravity",
            self.envelope(
                event="input_requested",
                session_id=SESSION,
                source_instance_id="statusline-1",
            ),
        )
        self.now = 110.0
        coordinator.submit(
            "antigravity",
            self.envelope(
                event="input_resolved",
                session_id=SESSION,
                source_instance_id="statusline-2",
            ),
        )
        kinds = [o.kind for o in coordinator.overlays_for("antigravity", SESSION)]
        self.assertIn(events.OVERLAY_NEEDS_INPUT, kinds)
