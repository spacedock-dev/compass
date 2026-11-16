"""The event envelope: what is accepted, what it means, and what it may patch."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

import event_hook
from compass_runtime import events

from . import fixtures, support

NOW = 1_700_000_000.0
# A UUID whose first eight characters are the prefix the Claude collector keys on.
SESSION = "abcdef12-3456-7890-abcd-ef1234567890"
PREFIX = "abcdef12"


def envelope(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"v": 1, "event": "turn_started", "session_id": SESSION}
    payload.update(overrides)
    return payload


class ParseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = support.make_config()

    def parse(self, payload: dict[str, Any], *, harness: str = "claude", seq: int = 1) -> Any:
        return events.parse(harness, payload, arrival_seq=seq, config=self.config, now=NOW)

    def test_a_valid_envelope_becomes_an_event_keyed_on_the_collector_prefix(self) -> None:
        result = self.parse(envelope())
        assert isinstance(result, events.Event)
        self.assertEqual(PREFIX, result.sid)
        self.assertEqual(SESSION, result.session_id)
        self.assertEqual("turn_started", result.event)
        self.assertEqual("claude", result.harness)

    def test_an_unsupported_version_reports_incompatible_rather_than_being_ignored(self) -> None:
        # The whole point of the distinction: an adapter too old for this server
        # is something the user can fix, and the unknown-name rule would hide it.
        result = self.parse(envelope(v=99))
        self.assertEqual(events.Rejected(events.REJECT_INCOMPATIBLE), result)

    def test_a_missing_version_is_incompatible(self) -> None:
        payload = envelope()
        del payload["v"]
        self.assertEqual(events.Rejected(events.REJECT_INCOMPATIBLE), self.parse(payload))

    def test_a_boolean_version_is_not_read_as_one(self) -> None:
        # bool is a subclass of int in Python, so `True` would pass a bare
        # isinstance check and then compare equal to version 1.
        self.assertEqual(events.Rejected(events.REJECT_INCOMPATIBLE), self.parse(envelope(v=True)))

    def test_an_unknown_event_name_is_rejected_not_accepted_into_state(self) -> None:
        result = self.parse(envelope(event="rm_minus_rf"))
        self.assertEqual(events.Rejected(events.REJECT_UNKNOWN_EVENT), result)

    def test_the_version_is_checked_before_the_vocabulary(self) -> None:
        # An adapter from the future may use a name this build has never heard
        # of; reporting that as an unknown name would send the user hunting for a
        # typo instead of an upgrade.
        result = self.parse(envelope(v=99, event="not_a_known_name"))
        self.assertEqual(events.Rejected(events.REJECT_INCOMPATIBLE), result)

    def test_a_harness_without_a_registered_normalizer_is_refused(self) -> None:
        # The identity mapping has to be established per harness before its
        # adapter ships. A passthrough default would quietly skip that step.
        result = self.parse(envelope(), harness="goose")
        self.assertEqual(events.Rejected(events.REJECT_UNKNOWN_HARNESS), result)

    def test_a_session_id_too_short_to_map_is_refused(self) -> None:
        # Seven characters would match every row sharing the prefix, which is a
        # guess rather than a lookup.
        result = self.parse(envelope(session_id="abcdef1"))
        self.assertEqual(events.Rejected(events.REJECT_UNMAPPABLE), result)

    def test_a_session_id_that_is_not_uuid_shaped_is_refused(self) -> None:
        result = self.parse(envelope(session_id="../../etc/passwd"))
        self.assertEqual(events.Rejected(events.REJECT_UNMAPPABLE), result)

    def test_a_missing_session_id_is_malformed(self) -> None:
        payload = envelope()
        del payload["session_id"]
        self.assertEqual(events.Rejected(events.REJECT_MALFORMED), self.parse(payload))

    def test_an_oversized_session_id_is_malformed(self) -> None:
        result = self.parse(envelope(session_id="a" * (events.MAX_ID_LEN + 1)))
        self.assertEqual(events.Rejected(events.REJECT_MALFORMED), result)

    def test_unrelated_native_fields_are_discarded_rather_than_rejected(self) -> None:
        # A harness adding a field must not take out its own adapter, and the
        # prompt text it added must not survive into anything Compass holds.
        result = self.parse(envelope(prompt="my secret prompt", tool_input={"cmd": "ls"}))
        assert isinstance(result, events.Event)
        self.assertNotIn("prompt", vars(result))
        self.assertNotIn("my secret prompt", repr(result))

    def test_the_allowlist_matches_the_fields_the_event_actually_carries(self) -> None:
        # Both sides of the envelope contract in one assertion, so adding a field
        # to one without the other fails here rather than silently.
        carried = {
            "event",
            "session_id",
            "timestamp",
            "source_instance_id",
            "source_sequence",
            "cwd",
            "subagent_id",
            "transcript_path",
            "tmux_socket",
            "tmux_pane",
            "tmux_server",
            "pattern_id",
            "tool_name",
            "declared_parent",
        }
        self.assertEqual(events.ALLOWED_FIELDS, carried | {"v"})

    def test_optional_hints_are_carried_through(self) -> None:
        result = self.parse(
            envelope(
                cwd="/w/proj",
                subagent_id="child-1",
                transcript_path="/store/projects/-w-proj/abcdef12.jsonl",
                source_instance_id="inst-1",
                source_sequence=7,
            )
        )
        assert isinstance(result, events.Event)
        self.assertEqual("/w/proj", result.cwd)
        self.assertEqual("child-1", result.subagent_id)
        self.assertEqual(7, result.source_sequence)
        self.assertEqual("inst-1", result.source_instance_id)

    def test_a_wrongly_typed_hint_is_dropped_and_the_event_still_parses(self) -> None:
        result = self.parse(envelope(cwd=12345, subagent_id=["a"]))
        assert isinstance(result, events.Event)
        self.assertIsNone(result.cwd)
        self.assertIsNone(result.subagent_id)

    def test_a_negative_source_sequence_is_dropped(self) -> None:
        result = self.parse(envelope(source_sequence=-1))
        assert isinstance(result, events.Event)
        self.assertIsNone(result.source_sequence)

    def test_a_boolean_source_sequence_is_dropped(self) -> None:
        result = self.parse(envelope(source_sequence=True))
        assert isinstance(result, events.Event)
        self.assertIsNone(result.source_sequence)

    def test_arrival_seq_is_taken_from_the_caller_not_the_body(self) -> None:
        # The server mints this under its ingress lock. A payload field claiming
        # one would let a hook choose its own place in the order.
        result = self.parse(envelope(arrival_seq=999), seq=4)
        assert isinstance(result, events.Event)
        self.assertEqual(4, result.arrival_seq)


class NormalizeSessionIdTest(unittest.TestCase):
    """The normalizer on its own, because the pending map calls it directly.

    `parse` refuses an unregistered harness before it gets here, so these cover
    the other caller: the coordinator resolving a native id against a collected
    row without a whole envelope to hand.
    """

    def test_claude_maps_a_uuid_onto_the_collectors_prefix(self) -> None:
        self.assertEqual(PREFIX, events.normalize_session_id("claude", SESSION))

    def test_an_unregistered_harness_maps_to_nothing(self) -> None:
        self.assertIsNone(events.normalize_session_id("goose", SESSION))

    def test_the_registry_only_holds_harnesses_whose_adapter_has_shipped(self) -> None:
        # Each of these four had its mapping established against a real session
        # before it was added. A fifth goes in the same way, not by analogy.
        # Gemini's evidence is docs/captures/gemini/identity-0.53.1-macos.jsonl.
        self.assertEqual(
            {"claude", "codex", "antigravity", "gemini", "opencode", "pi", "droid"},
            set(events.IDENTITY_NORMALIZERS),
        )

    def test_codex_antigravity_gemini_and_droid_key_on_the_whole_id(self) -> None:
        # Measured, not assumed. Codex's hook session_id matched the session_meta
        # id of the rollout the same session wrote; Antigravity's conversation_id
        # matched the stem of a real conversations/<id>.db; Gemini's matched the
        # sessionId on line 1 of the chats/session-*.jsonl the same session wrote;
        # Droid's matched the stem and session_start id. Truncating any of them
        # the way Claude's is truncated would key on a row that does not exist.
        for harness in ("codex", "antigravity", "gemini", "droid"):
            with self.subTest(harness):
                self.assertEqual(SESSION, events.normalize_session_id(harness, SESSION))

    def test_claude_still_truncates_and_the_others_do_not(self) -> None:
        # The whole reason identity is per harness rather than one shared rule.
        self.assertEqual(PREFIX, events.normalize_session_id("claude", SESSION))
        self.assertNotEqual(
            events.normalize_session_id("claude", SESSION),
            events.normalize_session_id("codex", SESSION),
        )
        self.assertNotEqual(
            events.normalize_session_id("claude", SESSION),
            events.normalize_session_id("droid", SESSION),
        )

    def test_a_whole_id_harness_refuses_a_wrong_length(self) -> None:
        # Checked exactly rather than as a floor: these harnesses write
        # 36-character ids, and a longer string that merely starts like one is not
        # a near miss to tolerate.
        for harness in ("codex", "droid"):
            for candidate in (SESSION[:-1], SESSION + "0", PREFIX):
                with self.subTest(harness=harness, candidate=candidate):
                    self.assertIsNone(events.normalize_session_id(harness, candidate))

    def test_a_whole_id_harness_refuses_a_non_uuid_shape(self) -> None:
        forged = "../../../etc/passwd" + "-" * (36 - len("../../../etc/passwd"))
        self.assertEqual(36, len(forged), "the guard under test is the charset, not the length")
        self.assertIsNone(events.normalize_session_id("codex", forged))
        self.assertIsNone(events.normalize_session_id("droid", forged))


class TimestampTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = support.make_config()

    def parse(self, **overrides: Any) -> events.Event:
        result = events.parse(
            "claude", envelope(**overrides), arrival_seq=1, config=self.config, now=NOW
        )
        assert isinstance(result, events.Event)
        return result

    def test_an_iso_stamp_with_z_is_parsed_to_epoch_seconds(self) -> None:
        self.assertEqual(1_700_000_000.0, self.parse(timestamp="2023-11-14T22:13:20Z").timestamp)

    def test_an_offset_stamp_is_parsed(self) -> None:
        self.assertEqual(
            1_700_000_000.0, self.parse(timestamp="2023-11-14T23:13:20+01:00").timestamp
        )

    def test_a_naive_stamp_is_read_as_utc(self) -> None:
        self.assertEqual(1_700_000_000.0, self.parse(timestamp="2023-11-14T22:13:20").timestamp)

    def test_a_missing_stamp_falls_back_to_arrival(self) -> None:
        self.assertEqual(NOW, self.parse().timestamp)

    def test_an_unparseable_stamp_falls_back_to_arrival(self) -> None:
        self.assertEqual(NOW, self.parse(timestamp="last tuesday").timestamp)

    def test_a_stamp_hours_in_the_future_is_replaced_by_arrival(self) -> None:
        # A hook in a container whose clock runs ahead must not be able to pin a
        # row. Believing it would read as fresh activity for as long as the skew
        # lasts, which is the failure the store-timestamp filter already prevents.
        future = self.parse(timestamp="2023-11-15T22:13:20Z")
        self.assertEqual(NOW, future.timestamp)

    def test_a_stamp_inside_the_skew_tolerance_is_kept(self) -> None:
        # Sampling noise, not a broken clock: the same tolerance the store
        # timestamps get.
        seconds = self.config.future_skew_tolerance_sec / 2
        kept = self.parse(timestamp="2023-11-14T22:14:20Z")
        self.assertGreater(kept.timestamp, NOW)
        self.assertLessEqual(kept.timestamp - NOW, seconds + 1)


class OverlayMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = support.make_config()

    def event(self, name: str, *, seq: int = 1, at: float = NOW) -> events.Event:
        return events.Event(
            harness="claude",
            event=name,
            sid=PREFIX,
            session_id=SESSION,
            timestamp=at,
            arrival_seq=seq,
        )

    def overlay(self, name: str, **kwargs: Any) -> events.Overlay | None:
        return events.overlay_for(self.event(name, **kwargs), config=self.config)

    def test_a_prompt_means_working_with_a_deadline(self) -> None:
        overlay = self.overlay("turn_started")
        assert overlay is not None
        self.assertEqual(events.OVERLAY_WORKING, overlay.kind)
        self.assertEqual(NOW + self.config.overlay_working_ttl_sec, overlay.expires_at)

    def test_a_permission_reply_means_working_again(self) -> None:
        overlay = self.overlay("input_resolved")
        assert overlay is not None
        self.assertEqual(events.OVERLAY_WORKING, overlay.kind)

    def test_a_permission_request_means_needs_input_with_no_expiry(self) -> None:
        # The asymmetry is the point. A real permission wait can last hours, so a
        # generic timeout would clear a live alert while the user was at lunch.
        overlay = self.overlay("input_requested")
        assert overlay is not None
        self.assertEqual(events.OVERLAY_NEEDS_INPUT, overlay.kind)
        self.assertIsNone(overlay.expires_at)

    def test_a_stop_means_idle_only_after_the_dwell(self) -> None:
        overlay = self.overlay("turn_stopped")
        assert overlay is not None
        self.assertEqual(events.OVERLAY_IDLE, overlay.kind)
        self.assertFalse(overlay.applies(now=NOW))
        self.assertTrue(overlay.applies(now=NOW + self.config.overlay_idle_dwell_sec))

    def test_the_idle_dwell_is_well_above_the_coalescing_window(self) -> None:
        # The dwell exists so a stop followed immediately by a new prompt resolves
        # inside one publish. A dwell at or below the coalescing window would not
        # cover the case it was added for.
        self.assertGreater(self.config.overlay_idle_dwell_sec, 0.15 * 4)

    def test_the_working_deadline_matches_what_the_collectors_mean_by_working(self) -> None:
        # Tied to the existing threshold rather than chosen separately: an overlay
        # outliving it would claim Working for a session the scan calls Idle.
        self.assertEqual(self.config.working_threshold_sec, self.config.overlay_working_ttl_sec)

    def test_hint_events_produce_no_overlay(self) -> None:
        # These mean the store probably moved. A hint has no business patching a
        # display field, and session_started says nothing about activity at all.
        for name in ("store_changed", "tasks_changed", "reconcile_required", "session_started"):
            with self.subTest(name):
                self.assertIsNone(self.overlay(name))

    def test_session_ended_produces_no_overlay_and_retires_instead(self) -> None:
        ended = self.event("session_ended")
        self.assertIsNone(events.overlay_for(ended, config=self.config))
        self.assertTrue(events.retires_overlays(ended))

    def test_only_session_ended_retires(self) -> None:
        self.assertFalse(events.retires_overlays(self.event("turn_stopped")))

    def test_only_reconcile_required_asks_for_reconciliation(self) -> None:
        self.assertTrue(events.requires_reconcile(self.event("reconcile_required")))
        self.assertFalse(events.requires_reconcile(self.event("store_changed")))

    def test_a_subagent_event_is_recorded_as_its_own_kind(self) -> None:
        overlay = self.overlay("subagent_started")
        assert overlay is not None
        self.assertEqual(events.OVERLAY_SUBAGENT, overlay.kind)

    def test_every_event_name_is_either_an_overlay_a_retirement_or_a_hint(self) -> None:
        # No name may fall through unclassified: an event that means nothing to
        # any of the three paths would be accepted and then dropped in silence.
        for name in sorted(events.EVENT_NAMES):
            with self.subTest(name):
                event = self.event(name)
                classified = (
                    events.overlay_for(event, config=self.config) is not None
                    or events.retires_overlays(event)
                    or events.requires_reconcile(event)
                    or name
                    in {
                        "session_started",
                        "store_changed",
                        "tasks_changed",
                        "command_shape_reported",
                    }
                )
                self.assertTrue(classified)


class GrantedPermissionTest(support.RuntimeTestCase):
    """End to end: a wait no hook ever closes, and the row that has to escape it.

    The reducer unit tests pin the rule. This pins the wiring, which is where the
    bug actually lived: the collector has to report `own_activity`, the
    application has to hand it to the reducer, and the grace has to come off the
    config rather than a literal.
    """

    def _collect(self, *, parent_at: float, requested_at: float, now: float) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            seeded = fixtures.build_claude(
                Path(tmp), parent_at, "12345678-1111-2222-3333-444444444444", "seeded"
            )
            with support.store_patch(**seeded):
                app = support.build_app()
                app.clock = lambda: now
                app.overlays = _StubOverlays(
                    events.Overlay(
                        harness="claude",
                        sid="12345678",
                        arrival_seq=1,
                        kind=events.OVERLAY_NEEDS_INPUT,
                        at=requested_at,
                    )
                )
                rows = app.collect(show_all=True)["sessions"]
        return next(r for r in rows if r["sid"].startswith("12345678"))

    def test_a_turn_that_carried_on_is_not_still_waiting_on_you(self) -> None:
        # The reported case: an AskUserQuestion answered 16 minutes ago, on a
        # session that has been generating ever since (DRC-4097).
        now = 1_700_000_000.0
        row = self._collect(parent_at=now - 30, requested_at=now - 960, now=now)
        self.assertNotEqual("needs_input", row["state"])
        self.assertIsNone(row.get("blocked_since"))

    def test_a_prompt_still_open_is_still_your_call(self) -> None:
        # The true positive that the fix must not clear: the transcript stopped
        # at the request and has not moved since.
        now = 1_700_000_000.0
        row = self._collect(parent_at=now - 960, requested_at=now - 950, now=now)
        self.assertEqual("needs_input", row["state"])
        self.assertEqual(now - 950, row["blocked_since"])


class GrantedCodexPermissionTest(support.RuntimeTestCase):
    """The same wiring on the second harness that can report a gate.

    Codex's `PermissionRequest` hook is the only source it has, so nothing ever
    arrives to say the user answered -- exactly Claude's situation in
    `GrantedPermissionTest`, and exactly why that class pins the wiring rather
    than the rule. Without the collector reporting `own_activity` the row stayed
    red from the approval until the turn's `Stop`, which is DRC-4097 again on a
    harness that had no such row when DRC-4097 was fixed.

    The signal is measured rather than borrowed. With a real approval prompt
    standing open on 0.149.0 the session's rollout held at one timestamp across
    25 seconds and advanced only once the gate was answered, so the newest record
    in the session's own rollout separates the two states.
    """

    SID = "019fd197-19e4-77b2-913d-d16c3190bb52"

    def _collect(self, *, rollout_at: float, requested_at: float, now: float) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            seeded = fixtures.build_codex(Path(tmp), rollout_at, self.SID, "seeded")
            with support.store_patch(**seeded):
                app = support.build_app()
                app.clock = lambda: now
                app.overlays = _StubOverlays(
                    events.Overlay(
                        harness="codex",
                        sid=self.SID,
                        arrival_seq=1,
                        kind=events.OVERLAY_NEEDS_INPUT,
                        at=requested_at,
                    )
                )
                rows = app.collect(show_all=True)["sessions"]
        return next(r for r in rows if r["harness"] == "codex")

    def test_an_approved_gate_stops_counting_once_the_session_moves_on(self) -> None:
        # The user approved 16 minutes ago and the turn has been generating since.
        now = 1_700_000_000.0
        row = self._collect(rollout_at=now - 30, requested_at=now - 960, now=now)
        self.assertNotEqual("needs_input", row["state"])
        self.assertIsNone(row.get("blocked_since"))

    def test_a_gate_still_open_is_still_your_call(self) -> None:
        # The true positive the fix must not clear: the rollout stopped at the
        # request and has not moved since, which is what the arm measured.
        now = 1_700_000_000.0
        row = self._collect(rollout_at=now - 960, requested_at=now - 950, now=now)
        self.assertEqual("needs_input", row["state"])
        self.assertEqual(now - 950, row["blocked_since"])


class _StubOverlays:
    """The overlay source shape `Application` consumes, with one overlay in it."""

    def __init__(self, overlay: events.Overlay) -> None:
        self.overlay = overlay

    def overlays_for(self, harness: str, sid: str) -> list[events.Overlay]:
        if (harness, sid) == (self.overlay.harness, self.overlay.sid):
            return [self.overlay]
        return []

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
        del keys  # the real coordinator ages unmatched overlays here; a stub has none

    def command_reports(self) -> list[dict[str, Any]]:
        return []

    def drop_counters(self) -> dict[str, int]:
        return {}


class ReduceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = support.make_config()

    def overlay(self, kind: str, *, seq: int, at: float = NOW, **kwargs: Any) -> events.Overlay:
        return events.Overlay(
            harness="claude", sid=PREFIX, arrival_seq=seq, kind=kind, at=at, **kwargs
        )

    def test_an_empty_ledger_patches_nothing(self) -> None:
        self.assertEqual({}, events.reduce_overlays([], now=NOW))

    def test_working_patches_state_and_marks_the_row_event_acquired(self) -> None:
        patch = events.reduce_overlays(
            [self.overlay(events.OVERLAY_WORKING, seq=1, expires_at=NOW + 90)], now=NOW
        )
        self.assertEqual("working", patch["state"])
        self.assertTrue(patch["active"])
        self.assertEqual(events.ACQUISITION_EVENT, patch["acquisition"])

    def test_needs_input_records_when_the_wait_began(self) -> None:
        patch = events.reduce_overlays(
            [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1, at=NOW - 30)], now=NOW
        )
        self.assertEqual("needs_input", patch["state"])
        self.assertEqual(NOW - 30, patch["blocked_since"])

    def test_working_clears_a_standing_blocked_since(self) -> None:
        patch = events.reduce_overlays(
            [
                self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1),
                self.overlay(events.OVERLAY_WORKING, seq=2, expires_at=NOW + 90),
            ],
            now=NOW,
        )
        self.assertEqual("working", patch["state"])
        self.assertIsNone(patch["blocked_since"])

    def test_arrival_order_decides_not_timestamp_order(self) -> None:
        # Two hook processes that raced. Only the server's own counter is
        # trustworthy enough to order them, so the later arrival wins even though
        # its own clock says it happened first.
        patch = events.reduce_overlays(
            [
                self.overlay(events.OVERLAY_WORKING, seq=1, at=NOW, expires_at=NOW + 90),
                self.overlay(events.OVERLAY_NEEDS_INPUT, seq=2, at=NOW - 600),
            ],
            now=NOW,
        )
        self.assertEqual("needs_input", patch["state"])

    def test_reducing_is_independent_of_the_order_the_ledger_is_iterated_in(self) -> None:
        # At-least-once, possibly reordered delivery: the reducer sorts, so a
        # ledger handed over backwards must produce the same answer.
        ledger = [
            self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1),
            self.overlay(events.OVERLAY_WORKING, seq=2, expires_at=NOW + 90),
        ]
        self.assertEqual(
            events.reduce_overlays(ledger, now=NOW),
            events.reduce_overlays(list(reversed(ledger)), now=NOW),
        )

    def test_reducing_twice_gives_the_same_patch(self) -> None:
        ledger = [self.overlay(events.OVERLAY_WORKING, seq=1, expires_at=NOW + 90)]
        self.assertEqual(
            events.reduce_overlays(ledger, now=NOW), events.reduce_overlays(ledger, now=NOW)
        )

    def test_an_expired_working_overlay_stops_patching(self) -> None:
        # A missed stop must not pin Working. Past the deadline the collector's
        # own reading of the store is what shows.
        ledger = [self.overlay(events.OVERLAY_WORKING, seq=1, expires_at=NOW + 90)]
        self.assertEqual({}, events.reduce_overlays(ledger, now=NOW + 91))

    def test_a_needs_input_overlay_never_expires_on_its_own(self) -> None:
        ledger = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1, at=NOW)]
        patch = events.reduce_overlays(ledger, now=NOW + 86_400)
        self.assertEqual("needs_input", patch["state"])

    def test_own_activity_after_the_request_ends_the_wait(self) -> None:
        # Claude has no hook for a permission being granted, so nothing arrives
        # to close the wait mid-turn. The session's own transcript moving on is
        # the only evidence there is (DRC-4097).
        ledger = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, own_activity=NOW - 5, activity_grace_sec=10.0
        )
        self.assertEqual({}, patch, "the collector's own state should show, not a stale wait")

    def test_own_activity_before_the_request_leaves_the_wait_standing(self) -> None:
        # The ordinary open prompt: the session's last write landed before the
        # request, and nothing has been written since. What that last write was
        # does not matter here, and is not guaranteed to be the tool_use record:
        # see docs/design-needs-input.md (N-2).
        ledger = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, own_activity=NOW - 601, activity_grace_sec=10.0
        )
        self.assertEqual("needs_input", patch["state"])
        self.assertEqual(NOW - 600, patch["blocked_since"])

    def test_activity_inside_the_grace_does_not_end_the_wait(self) -> None:
        # A hook process and the write that provoked it can land either way
        # round by a second or two. Only that ordering is what the grace covers.
        ledger = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, own_activity=NOW - 594, activity_grace_sec=10.0
        )
        self.assertEqual("needs_input", patch["state"])

    def test_an_unreported_own_activity_leaves_the_wait_standing(self) -> None:
        # Harnesses whose collectors do not fill the field send 0. Treating that
        # as "active since the epoch" would clear every wait on the board.
        ledger = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(ledger, now=NOW, own_activity=0.0, activity_grace_sec=10.0)
        self.assertEqual("needs_input", patch["state"])

    def test_session_activity_after_the_stop_retires_the_idle_overlay(self) -> None:
        # The reported shape of DRC-4101: a session that stopped, then resumed on
        # something other than a user prompt, so no `turn_started` ever arrived to
        # lift the stop. It was published idle and inactive while writing its
        # transcript at 4,000 tokens a minute with a subagent running.
        ledger = [self.overlay(events.OVERLAY_IDLE, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, session_activity=NOW - 5, activity_grace_sec=10.0
        )
        self.assertEqual({}, patch, "the collector's Working reading should show, not a stale stop")

    def test_a_quiet_session_still_goes_idle(self) -> None:
        # The guard must not become "never go idle". Nothing has been written
        # since the stop, which is what an ended session looks like.
        ledger = [self.overlay(events.OVERLAY_IDLE, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, session_activity=NOW - 601, activity_grace_sec=10.0
        )
        self.assertEqual("idle", patch["state"])
        self.assertFalse(patch["active"])

    def test_a_stop_publishes_when_the_turn_ended(self) -> None:
        # DRC-4035: "finished, and nobody read it" needs the stop's own stamp on
        # the row, not just the Idle state, because Idle alone cannot say whether
        # the turn ended or the session is still waiting on a reply nobody gave.
        ledger = [self.overlay(events.OVERLAY_IDLE, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, session_activity=NOW - 601, activity_grace_sec=10.0
        )
        self.assertEqual(NOW - 600, patch["finished_at"])

    def test_a_remembered_stop_survives_the_ledger_being_retired(self) -> None:
        # The `claude -p` case: Stop then SessionEnd arrive back to back, the
        # ledger is popped, and the row that finished has no overlay left. The
        # mark is reduced from the coordinator's own memory instead, and it
        # patches nothing else — the collector still owns the state.
        patch = events.reduce_overlays(
            [], now=NOW, session_activity=NOW - 601, activity_grace_sec=10.0, finished_at=NOW - 600
        )
        self.assertEqual({"finished_at": NOW - 600}, patch)

    def test_activity_after_a_remembered_stop_clears_the_mark(self) -> None:
        # DRC-4101 by another door. The mark outlives the ledger by design, so
        # nothing but this guard stops a session resumed by a background task
        # from reading "finished" while it generates.
        patch = events.reduce_overlays(
            [], now=NOW, session_activity=NOW - 5, activity_grace_sec=10.0, finished_at=NOW - 600
        )
        self.assertEqual({}, patch, "a session that worked again is not finished")

    def test_a_live_working_overlay_outranks_a_remembered_stop(self) -> None:
        # The other way a stop is superseded: a prompt arrived, so the row is
        # working and the mark from the previous turn must go with it.
        ledger = [self.overlay(events.OVERLAY_WORKING, seq=2, at=NOW - 5)]
        patch = events.reduce_overlays(ledger, now=NOW, finished_at=NOW - 600)
        self.assertEqual("working", patch["state"])
        self.assertIsNone(patch["finished_at"])

    def test_a_gate_outranks_a_remembered_stop(self) -> None:
        # A session waiting on a person is the other kind of idle, and it is the
        # one this mark exists to be told apart from.
        ledger = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=2, at=NOW - 5)]
        patch = events.reduce_overlays(ledger, now=NOW, finished_at=NOW - 600)
        self.assertEqual("needs_input", patch["state"])
        self.assertIsNone(patch["finished_at"])

    def test_an_observed_end_publishes_its_own_stamp(self) -> None:
        # DRC-4036. A turn stopping and a session id ending are two facts, and
        # only the second one means the row will never move again.
        patch = events.reduce_overlays([], now=NOW, ended_at=NOW - 600)
        self.assertEqual({"ended_at": NOW - 600}, patch)

    def test_activity_after_an_observed_end_leaves_the_stamp_standing(self) -> None:
        # Deliberately NOT `finished_at`'s rule, and this is the assertion that
        # pins the difference. A stop is a reading of a moment that later writing
        # invalidates; an end is a fact about an id, and the id cannot write again
        # without a `session_started`, which retires the mark at the coordinator.
        # An end also arrives AFTER the last write — 5.581 s after the last Stop
        # in the a1 arm of the session-end capture — so an activity guard here
        # would be deciding on the wrong side of the very sequence it saw.
        patch = events.reduce_overlays(
            [], now=NOW, session_activity=NOW - 5, activity_grace_sec=10.0, ended_at=NOW - 600
        )
        self.assertEqual({"ended_at": NOW - 600}, patch)

    def test_a_live_working_overlay_outranks_an_observed_end(self) -> None:
        # A session doing something is not ended, whatever this process
        # remembers. `claude --resume <id>` reuses the id, so the row has to be
        # able to stop reading ended.
        ledger = [self.overlay(events.OVERLAY_WORKING, seq=2, at=NOW - 5)]
        patch = events.reduce_overlays(ledger, now=NOW, ended_at=NOW - 600)
        self.assertEqual("working", patch["state"])
        self.assertIsNone(patch["ended_at"])

    def test_a_live_gate_outranks_an_observed_end(self) -> None:
        # A session holding a question open is alive and someone is expected to
        # answer it, which is the reading an end would suppress.
        ledger = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=2, at=NOW - 5)]
        patch = events.reduce_overlays(ledger, now=NOW, ended_at=NOW - 600)
        self.assertEqual("needs_input", patch["state"])
        self.assertIsNone(patch["ended_at"])

    def test_an_idle_overlay_does_not_lift_an_observed_end(self) -> None:
        # A `turn_stopped` is not evidence a session reopened: every tidy ending
        # has one in front of it, and delivery is at-least-once and reorderable,
        # so lifting on idle would erase the mark for exactly the endings this
        # field exists to show.
        ledger = [self.overlay(events.OVERLAY_IDLE, seq=1, at=NOW - 610)]
        patch = events.reduce_overlays(ledger, now=NOW, ended_at=NOW - 600)
        self.assertEqual("idle", patch["state"])
        self.assertEqual(NOW - 600, patch["ended_at"])

    def test_no_end_observed_publishes_no_end_key_at_all(self) -> None:
        # `apply_patch` writes only the keys present, so an absent key leaves the
        # row's declared None standing. Writing 0.0 or False here would be null's
        # job done by a value, which is what DRC-4101 cost.
        patch = events.reduce_overlays([], now=NOW, finished_at=NOW - 600)
        self.assertNotIn("ended_at", patch)

    def test_activity_inside_the_grace_does_not_retire_the_stop(self) -> None:
        # The final flush of the transcript can land just after the Stop hook it
        # provoked. Only that ordering is what the grace covers.
        ledger = [self.overlay(events.OVERLAY_IDLE, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, session_activity=NOW - 594, activity_grace_sec=10.0
        )
        self.assertEqual("idle", patch["state"])

    def test_an_unreported_session_activity_leaves_the_stop_standing(self) -> None:
        # Collectors that do not fill the field send 0. Treating that as "active
        # since the epoch" would mean no session on the board could ever be idle.
        ledger = [self.overlay(events.OVERLAY_IDLE, seq=1, at=NOW - 600)]
        patch = events.reduce_overlays(
            ledger, now=NOW, session_activity=0.0, activity_grace_sec=10.0
        )
        self.assertEqual("idle", patch["state"])

    def test_the_two_guards_read_different_activity(self) -> None:
        # A parked parent with a running child: the whole-tree reading is fresh
        # and the parent's own is not. Idle must retire (the subagent proves the
        # session is working) and a wait must stand (a background agent writing
        # says nothing about whether the human answered).
        stop = [self.overlay(events.OVERLAY_IDLE, seq=1, at=NOW - 600)]
        self.assertEqual(
            {},
            events.reduce_overlays(
                stop,
                now=NOW,
                own_activity=NOW - 601,
                session_activity=NOW - 5,
                activity_grace_sec=10.0,
            ),
        )
        wait = [self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1, at=NOW - 600)]
        self.assertEqual(
            "needs_input",
            events.reduce_overlays(
                wait,
                now=NOW,
                own_activity=NOW - 601,
                session_activity=NOW - 5,
                activity_grace_sec=10.0,
            )["state"],
        )

    def test_activity_does_not_disturb_a_working_overlay(self) -> None:
        ledger = [self.overlay(events.OVERLAY_WORKING, seq=1, expires_at=NOW + 90)]
        patch = events.reduce_overlays(ledger, now=NOW, own_activity=NOW, activity_grace_sec=10.0)
        self.assertEqual("working", patch["state"])

    def test_an_expired_overlay_does_not_truncate_the_replay_behind_it(self) -> None:
        # Skipping rather than stopping. The dead overlay is deliberately the
        # earlier of the two: with it last, stopping and skipping agree, and the
        # first version of this test could not tell them apart.
        ledger = [
            self.overlay(events.OVERLAY_WORKING, seq=1, at=NOW - 100, expires_at=NOW - 10),
            self.overlay(events.OVERLAY_NEEDS_INPUT, seq=2, at=NOW - 5),
        ]
        self.assertEqual("needs_input", events.reduce_overlays(ledger, now=NOW)["state"])

    def test_a_stop_inside_its_dwell_does_not_yet_override_working(self) -> None:
        ledger = [
            self.overlay(events.OVERLAY_WORKING, seq=1, expires_at=NOW + 90),
            self.overlay(
                events.OVERLAY_IDLE, seq=2, effective_at=NOW + self.config.overlay_idle_dwell_sec
            ),
        ]
        self.assertEqual("working", events.reduce_overlays(ledger, now=NOW)["state"])
        self.assertEqual(
            "idle",
            events.reduce_overlays(ledger, now=NOW + self.config.overlay_idle_dwell_sec)["state"],
        )

    def test_a_subagent_overlay_does_not_change_the_parents_state(self) -> None:
        # A child starting says nothing about what the parent is doing, and the
        # parent's subagent list is the collector's to reconstruct.
        ledger = [self.overlay(events.OVERLAY_SUBAGENT, seq=1, subagent_id="child-1")]
        self.assertEqual({}, events.reduce_overlays(ledger, now=NOW))

    def test_a_subagent_overlay_does_not_erase_a_live_needs_input(self) -> None:
        ledger = [
            self.overlay(events.OVERLAY_NEEDS_INPUT, seq=1),
            self.overlay(events.OVERLAY_SUBAGENT, seq=2, subagent_id="child-1"),
        ]
        self.assertEqual("needs_input", events.reduce_overlays(ledger, now=NOW)["state"])


class GitReadingReduceTest(unittest.TestCase):
    """The end-of-session reading at the reducer: what publishes it, and what nulls it.

    Every line these tests cover was measured entirely unpinned before they
    existed. Two agents independently mutated the three overlay branches — one
    deleting all six `dirty`/`changed` lines, one forcing `aggregate`'s `git=`
    argument to None — and the suite stayed green (253 and 213 tests OK), because
    the only `git=` call in the whole tree passed `overlays=[]` so no overlay
    branch ever ran with a reading present. AC5's own `Falsified by:` names that
    mutation, which made the criterion unenforced.
    """

    def overlay(self, kind: str, *, seq: int = 1, at: float = NOW, **kwargs: Any) -> events.Overlay:
        return events.Overlay(
            harness="claude", sid=PREFIX, arrival_seq=seq, kind=kind, at=at, **kwargs
        )

    def test_a_reading_publishes_alongside_the_stop_it_was_taken_at(self) -> None:
        # The happy path, and the control for everything below: `session_ended`
        # pops the overlay ledger whole, so what reaches the reducer at a real
        # session end is no overlays plus the two side-channel values.
        patch = events.reduce_overlays([], now=NOW, finished_at=NOW - 600, git=(True, 4))
        self.assertEqual(True, patch["dirty"])
        self.assertEqual(4, patch["changed"])

    def test_a_reading_with_no_stop_behind_it_is_not_published(self) -> None:
        # R2. `_mark_finished` pops the stop on a working or waiting overlay, so
        # `session_ended` then `turn_started` leaves a recorded reading with
        # `finished_at == 0.0`. The guard was `bool(finished_at) and …`, which is
        # False there, so the reading applied unguarded — and no later branch
        # nulls it once the working overlay lapses. A clean tree then republishes
        # as `dirty: false` over a session that kept working, permanently: null's
        # job done by false, the DRC-4101 shape AC6 exists to prevent.
        patch = events.reduce_overlays([], now=NOW, finished_at=0.0, git=(False, 0))
        self.assertNotIn("dirty", patch)
        self.assertNotIn("changed", patch)

    def test_a_lapsed_working_overlay_leaves_the_reading_unpublished(self) -> None:
        # R2 as reproduced: the same state one `overlay_working_ttl_sec` later.
        # The expired overlay patches nothing, so the reducer's clears cannot be
        # what saves this — only the side-channel guard can.
        lapsed = [self.overlay(events.OVERLAY_WORKING, expires_at=NOW + 90)]
        patch = events.reduce_overlays(lapsed, now=NOW + 91, finished_at=0.0, git=(False, 0))
        self.assertEqual({}, patch)

    def test_a_reading_older_than_the_sessions_last_write_is_not_published(self) -> None:
        # The guard that did work: a session that wrote after the stop was
        # observed has a tree the reading no longer describes.
        patch = events.reduce_overlays(
            [],
            now=NOW,
            finished_at=NOW - 600,
            session_activity=NOW - 5,
            activity_grace_sec=10.0,
            git=(True, 4),
        )
        self.assertEqual({}, patch)

    def test_a_live_working_overlay_nulls_the_reading(self) -> None:
        # R3, first of three. Working again means the tree has moved on from
        # whatever the probe saw, and a stale count is worse than none.
        patch = events.reduce_overlays(
            [self.overlay(events.OVERLAY_WORKING, expires_at=NOW + 90)],
            now=NOW,
            finished_at=NOW - 600,
            git=(True, 4),
        )
        self.assertEqual("working", patch["state"], "the branch under test did not run")
        self.assertIsNone(patch["dirty"])
        self.assertIsNone(patch["changed"])

    def test_a_live_gate_overlay_nulls_the_reading(self) -> None:
        # R3, second. Waiting on a person means the session is alive past the end
        # that produced the reading.
        patch = events.reduce_overlays(
            [self.overlay(events.OVERLAY_NEEDS_INPUT, at=NOW - 5)],
            now=NOW,
            finished_at=NOW - 600,
            git=(True, 4),
        )
        self.assertEqual("needs_input", patch["state"], "the branch under test did not run")
        self.assertIsNone(patch["dirty"])
        self.assertIsNone(patch["changed"])

    def test_a_live_idle_overlay_nulls_the_reading(self) -> None:
        # R3, third, and the least obvious: a turn stop is not a session end and
        # only a session end probes, so a LIVE idle overlay means a turn ran after
        # the reading was taken.
        patch = events.reduce_overlays(
            [self.overlay(events.OVERLAY_IDLE, seq=2, at=NOW - 5)],
            now=NOW,
            finished_at=NOW - 600,
            git=(True, 4),
        )
        self.assertEqual("idle", patch["state"], "the branch under test did not run")
        self.assertIsNone(patch["dirty"])
        self.assertIsNone(patch["changed"])

    def test_no_reading_at_all_patches_neither_key(self) -> None:
        # `git=None` is "not probed", and it must not become a null WRITE either:
        # the row already declares both keys as None, and a patch that carried
        # them would make `PATCHABLE` filtering the only thing standing between
        # an absent reading and an overwritten one.
        patch = events.reduce_overlays([], now=NOW, finished_at=NOW - 600, git=None)
        self.assertNotIn("dirty", patch)
        self.assertNotIn("changed", patch)


class NeedsInputSupersedingTest(unittest.TestCase):
    """A turn that starts after a permission wait ends that wait, permanently.

    `input_requested` deliberately has no expiry, because a real permission wait must
    not be timed out. That left a defect (DRC-4095): a later `turn_started` only
    *outranked* the needs-input overlay, and outranking lasts exactly as long as the
    working overlay's own `overlay_working_ttl_sec` deadline. When that lapsed the
    needs-input overlay applied again, carrying its ORIGINAL `blocked_since`, so a
    turn still running 90 seconds after its permission was granted reverted to
    "waiting for you" and claimed to have been waiting the whole time.

    Superseding is now permanent, and deliberately independent of whether the overlay
    that superseded it is still live. Once a turn has started, the earlier wait is
    over as a matter of history, and history does not lapse.

    What it falls back to matters as much as what it stops doing: with the wait
    superseded and the working overlay expired, no overlay patches anything and the
    collector's own reading of the store stands. Trusting the store after the deadline
    is the point of the deadline.
    """

    def setUp(self) -> None:
        self.config = support.make_config()

    def _event(self, name: str, *, at: float, seq: int) -> events.Event:
        return events.Event(
            harness="claude",
            event=name,
            sid=PREFIX,
            session_id=SESSION,
            timestamp=at,
            arrival_seq=seq,
        )

    def _reduce(self, now: float) -> dict[str, Any]:
        # Built through overlay_for rather than by hand, so this covers the deadline
        # each overlay is really given. Constructing Overlays directly would leave the
        # construction path unpinned, and the deadline IS the defect.
        built = [
            events.overlay_for(self._event("input_requested", at=NOW, seq=1), config=self.config),
            events.overlay_for(self._event("turn_started", at=NOW + 10, seq=2), config=self.config),
        ]
        self.assertTrue(all(o is not None for o in built), "both events must make overlays")
        return events.reduce_overlays([o for o in built if o is not None], now=now)

    def test_working_outranks_a_standing_permission_wait_while_it_is_live(self) -> None:
        patch = self._reduce(NOW + 15)
        self.assertEqual("working", patch["state"])
        self.assertIsNone(patch["blocked_since"])

    def test_the_wait_does_not_return_when_working_expires(self) -> None:
        # DRC-4095. Before the fix this asserted the opposite: needs_input, with the
        # original blocked_since. An empty patch is the correct answer, because the
        # only honest thing left to say is whatever the collector says.
        patch = self._reduce(NOW + 10 + self.config.overlay_working_ttl_sec + 1)
        self.assertEqual({}, patch, "a superseded wait must not come back")

    def test_a_permission_asked_for_during_a_turn_still_stands(self) -> None:
        # The risk in the fix, pinned. Superseding is by arrival order, so a wait that
        # arrives AFTER the turn started is a live wait and must survive. Getting this
        # backwards would silence every mid-turn permission prompt, which is the
        # majority of them.
        built = [
            events.overlay_for(self._event("turn_started", at=NOW, seq=1), config=self.config),
            events.overlay_for(
                self._event("input_requested", at=NOW + 10, seq=2), config=self.config
            ),
        ]
        patch = events.reduce_overlays([o for o in built if o is not None], now=NOW + 15)
        self.assertEqual("needs_input", patch["state"])
        self.assertEqual(NOW + 10, patch["blocked_since"])

    def test_a_wait_with_no_turn_after_it_is_never_timed_out(self) -> None:
        # The guarantee the missing expiry exists for. A real permission prompt that
        # nobody answers must stay visible however long it waits.
        built = events.overlay_for(
            self._event("input_requested", at=NOW, seq=1), config=self.config
        )
        assert built is not None
        patch = events.reduce_overlays([built], now=NOW + 86_400)
        self.assertEqual("needs_input", patch["state"])
        self.assertEqual(NOW, patch["blocked_since"])

    def test_a_stop_also_ends_a_wait(self) -> None:
        built = [
            events.overlay_for(self._event("input_requested", at=NOW, seq=1), config=self.config),
            events.overlay_for(self._event("turn_stopped", at=NOW + 10, seq=2), config=self.config),
        ]
        overlays = [o for o in built if o is not None]
        patch = events.reduce_overlays(overlays, now=NOW + 86_400)
        self.assertEqual("idle", patch["state"])
        self.assertIsNone(patch["blocked_since"])

    def test_an_expiring_stop_would_still_not_let_the_wait_return(self) -> None:
        """The invariant, not today's configuration.

        `turn_stopped` wins permanently today for an incidental reason: an idle
        overlay carries no deadline, so there is nothing to lapse. That makes
        `idle`'s membership of `ENDS_A_WAIT` untestable through `overlay_for`, and an
        untestable invariant is one a later change can drop silently -- which is
        exactly how DRC-4095 arrived through the working overlay.

        So this builds the idle overlay directly, with a deadline it does not have
        today, and asserts the superseded wait stays gone once it lapses.
        """
        wait = events.overlay_for(self._event("input_requested", at=NOW, seq=1), config=self.config)
        assert wait is not None
        stopped = events.Overlay(
            harness="claude",
            sid=PREFIX,
            arrival_seq=2,
            kind=events.OVERLAY_IDLE,
            at=NOW + 10,
            expires_at=NOW + 20,
        )
        self.assertEqual("idle", events.reduce_overlays([wait, stopped], now=NOW + 15)["state"])
        self.assertEqual(
            {},
            events.reduce_overlays([wait, stopped], now=NOW + 25),
            "a wait ended by a stop must not return when the stop lapses",
        )

    def test_nothing_produces_the_event_that_would_clear_it_properly(self) -> None:
        # The root cause, pinned so that adding a producer is a deliberate act.
        self.assertIn("input_resolved", events.EVENT_NAMES)
        produced = (
            set(event_hook.CLAUDE_EVENTS.values())
            | set(event_hook.CODEX_EVENTS.values())
            | set(event_hook.GEMINI_EVENTS.values())
        )
        self.assertNotIn("input_resolved", produced)


class ApplyPatchTest(unittest.TestCase):
    def test_only_patchable_fields_are_written(self) -> None:
        # The collector owns everything else. A reducer that grew a key by mistake
        # must not be able to rewrite a title or a token rate.
        session = {"title": "real title", "tokens": 1234, "state": "idle"}
        events.apply_patch(session, {"state": "working", "title": "forged", "tokens": 0})
        self.assertEqual("working", session["state"])
        self.assertEqual("real title", session["title"])
        self.assertEqual(1234, session["tokens"])

    def test_the_patchable_set_is_exactly_the_documented_ten(self) -> None:
        # Grew by two for the end-of-session git reading, then by one for the
        # observed session end (DRC-4036), then by one for wait_unconfirmed
        # (DRC-4203). Written out rather than derived, so adding a key to the
        # module has to be a deliberate edit here.
        self.assertEqual(
            {
                "state",
                "state_detail",
                "active",
                "blocked_since",
                "wait_unconfirmed",
                "acquisition",
                "finished_at",
                "ended_at",
                "dirty",
                "changed",
            },
            set(events.PATCHABLE),
        )

    def test_every_key_a_reducer_emits_is_patchable(self) -> None:
        # Otherwise a reducer could produce a field that apply_patch silently
        # drops, and the overlay would look applied while doing nothing.
        config = support.make_config()
        emitted: set[str] = set()
        for kind in (events.OVERLAY_WORKING, events.OVERLAY_NEEDS_INPUT, events.OVERLAY_IDLE):
            overlay = events.Overlay(harness="claude", sid=PREFIX, arrival_seq=1, kind=kind, at=NOW)
            emitted |= set(
                events.reduce_overlays([overlay], now=NOW + config.overlay_idle_dwell_sec)
            )
        self.assertLessEqual(emitted, set(events.PATCHABLE))


class RepeatingSourceWaitLeaseTest(unittest.TestCase):
    """DRC-4203 / DRC-4573: repeating-source wait lease, heartbeats, and visible uncertainty."""

    def test_ac1_repeating_wait_survives_heartbeats_and_preserves_blocked_since(self) -> None:
        wait = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=1,
            kind=events.OVERLAY_NEEDS_INPUT,
            at=NOW,
            event="input_requested",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
            blocked_since=NOW,
        )
        hb_working = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=2,
            kind=events.OVERLAY_WORKING,
            at=NOW + 10,
            event="turn_started",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
        )
        hb_idle = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=3,
            kind=events.OVERLAY_IDLE,
            at=NOW + 20,
            event="turn_stopped",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
        )
        patch = events.reduce_overlays([wait, hb_working, hb_idle], now=NOW + 25)
        self.assertEqual("needs_input", patch["state"])
        self.assertEqual(NOW, patch["blocked_since"])
        self.assertFalse(patch["wait_unconfirmed"])

    def test_ac2_explicit_resolution_permanently_retires_repeating_wait(self) -> None:
        wait = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=1,
            kind=events.OVERLAY_NEEDS_INPUT,
            at=NOW,
            event="input_requested",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
            blocked_since=NOW,
        )
        resolved = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=2,
            kind=events.OVERLAY_WORKING,
            at=NOW + 10,
            expires_at=NOW + 100,
            event="input_resolved",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
        )
        patch = events.reduce_overlays([wait, resolved], now=NOW + 15)
        self.assertEqual("working", patch["state"])
        self.assertFalse(patch["wait_unconfirmed"])
        self.assertIsNone(patch["blocked_since"])

        # Beyond working TTL (101 seconds later): old wait does not resurrect
        lapsed = events.reduce_overlays([wait, resolved], now=NOW + 105)
        self.assertEqual({}, lapsed)

    def test_ac2_unrelated_source_resolution_does_not_retire_wait(self) -> None:
        wait = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=1,
            kind=events.OVERLAY_NEEDS_INPUT,
            at=NOW,
            event="input_requested",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline-1",
            blocked_since=NOW,
        )
        other_resolved = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=2,
            kind=events.OVERLAY_WORKING,
            at=NOW + 10,
            expires_at=NOW + 100,
            event="input_resolved",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline-2",
        )
        patch = events.reduce_overlays([wait, other_resolved], now=NOW + 15)
        self.assertEqual("needs_input", patch["state"])
        self.assertEqual(NOW, patch["blocked_since"])

    def test_ac3_300s_lease_boundary_heartbeats_and_renewal(self) -> None:
        wait = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=1,
            kind=events.OVERLAY_NEEDS_INPUT,
            at=NOW,
            event="input_requested",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
            blocked_since=NOW,
            lease_sec=300.0,
        )
        hb_working = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=2,
            kind=events.OVERLAY_WORKING,
            at=NOW + 150,
            event="turn_started",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
        )
        overlays = [wait, hb_working]

        # Exactly 300 - epsilon: still confirmed
        patch_before = events.reduce_overlays(overlays, now=NOW + 300.0 - 0.001)
        self.assertEqual("needs_input", patch_before["state"])
        self.assertFalse(patch_before["wait_unconfirmed"])
        self.assertEqual(NOW, patch_before["blocked_since"])

        # Exactly 300: unconfirmed
        patch_at = events.reduce_overlays(overlays, now=NOW + 300.0)
        self.assertEqual("needs_input", patch_at["state"])
        self.assertTrue(patch_at["wait_unconfirmed"])
        self.assertEqual(NOW, patch_at["blocked_since"])

        # Exactly 300 + epsilon: unconfirmed
        patch_after = events.reduce_overlays(overlays, now=NOW + 300.0 + 0.001)
        self.assertEqual("needs_input", patch_after["state"])
        self.assertTrue(patch_after["wait_unconfirmed"])
        self.assertEqual(NOW, patch_after["blocked_since"])

        # Fresh positive observation renews lease and reconfirms without resetting age
        renewed = events.Overlay(
            harness="antigravity",
            sid=PREFIX,
            arrival_seq=3,
            kind=events.OVERLAY_NEEDS_INPUT,
            at=NOW + 350.0,
            event="input_requested",
            source_class=events.SOURCE_CLASS_REPEATING,
            source_instance_id="statusline",
            blocked_since=NOW,
            lease_sec=300.0,
        )
        overlays.append(renewed)

        # At t=400: reconfirmed, wait_unconfirmed=False, age still NOW
        patch_renewed = events.reduce_overlays(overlays, now=NOW + 400.0)
        self.assertEqual("needs_input", patch_renewed["state"])
        self.assertFalse(patch_renewed["wait_unconfirmed"])
        self.assertEqual(NOW, patch_renewed["blocked_since"])

        # Expires again at 350 + 300 = 650
        patch_second_expiry = events.reduce_overlays(overlays, now=NOW + 651.0)
        self.assertEqual("needs_input", patch_second_expiry["state"])
        self.assertTrue(patch_second_expiry["wait_unconfirmed"])
        self.assertEqual(NOW, patch_second_expiry["blocked_since"])

    def test_ac3_explicit_resolution_adapters_gain_no_timeout(self) -> None:
        # A discrete wait (e.g. Claude, OpenCode, Pi) does not expire at 300s
        discrete_wait = events.Overlay(
            harness="opencode",
            sid=PREFIX,
            arrival_seq=1,
            kind=events.OVERLAY_NEEDS_INPUT,
            at=NOW,
            event="input_requested",
            source_class=events.SOURCE_CLASS_DISCRETE,
            blocked_since=NOW,
        )
        patch = events.reduce_overlays([discrete_wait], now=NOW + 86_400)
        self.assertEqual("needs_input", patch["state"])
        self.assertFalse(patch["wait_unconfirmed"])
        self.assertEqual(NOW, patch["blocked_since"])
