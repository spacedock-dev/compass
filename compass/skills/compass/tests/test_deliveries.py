"""What became of a raise, and what the record may not claim about it.

DRC-4540. Before this store there was no raise record at all: the only trace
was a cooldown floor in memory, overwritten on every raise, so a signal that
never left the machine and one handed to the operating system left the same
mark.
"""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

if TYPE_CHECKING:
    from compass_runtime.deliveries import Delivery

from compass_runtime import aggregate, deliveries, notifications, unasked
from compass_runtime import sessions as runtime_sessions
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state


def _config(root: Path) -> Any:
    return build_runtime_config(
        environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
        platform_name="linux",
        os_name="posix",
        launcher_path=root / "server.py",
    )


class TheSentencesAreDisjointTest(unittest.TestCase):
    """One sentence per cause and never a shared one.

    `reading.WITHHELD`'s rule, for its reason: folding causes together makes the
    least true of them read as the most reassuring. Asserted rather than
    intended, because nothing else would notice a copy-paste.
    """

    def test_every_outcome_has_a_sentence(self) -> None:
        self.assertEqual(set(deliveries.OUTCOMES), set(deliveries.DELIVERY))

    def test_no_two_outcomes_read_alike(self) -> None:
        self.assertEqual(len(deliveries.DELIVERY), len(set(deliveries.DELIVERY.values())))

    def test_no_sentence_claims_the_reader_saw_anything(self) -> None:
        # The whole point of the wording. `osascript` exits zero under Do Not
        # Disturb and with the hosting app's notifications switched off, so the
        # call returning says the service accepted it and nothing more.
        every = [
            *deliveries.DELIVERY.values(),
            deliveries.NO_RECORD,
            deliveries.BROWSER_LANE_REPORTED,
            deliveries.BROWSER_LANE_UNREPORTED,
        ]
        for sentence in every:
            with self.subTest(sentence=sentence[:40]):
                lowered = sentence.lower()
                for claim in (
                    "you saw",
                    "you were told",
                    "was seen",
                    "was delivered",
                    "reached you",
                ):
                    self.assertNotIn(claim, lowered)

    def test_the_handed_over_sentence_declines_the_claim_in_its_own_words(self) -> None:
        handed = deliveries.DELIVERY[deliveries.OUTCOME_HANDED_OVER]
        self.assertIn("whether anyone saw it, is not something that call reports", handed)

    def test_a_timeout_is_not_a_failure(self) -> None:
        # Collapsing these is the same error the module exists to refuse one
        # level down: the call did not return, so what it did is unknown.
        timed_out = deliveries.DELIVERY[deliveries.OUTCOME_DID_NOT_RETURN]
        self.assertIn("unrecorded rather than known to have failed", timed_out)
        self.assertNotIn("error", timed_out)

    def test_an_unreadable_record_does_not_say_undelivered(self) -> None:
        # And it names the cause that can actually select it. An earlier
        # wording said "predates the delivery record", which describes a case
        # that writes no record at all and so can never reach this sentence.
        self.assertIn("not one this build can read", deliveries.NO_RECORD)
        self.assertIn("unknown rather than known to have failed", deliveries.NO_RECORD)
        self.assertNotIn("not delivered", deliveries.NO_RECORD)

    def test_the_two_ways_a_call_fails_do_not_share_a_sentence(self) -> None:
        # The service running and rejecting, against the call never starting.
        # Sharing one would tell a reader their notification service refused
        # something it never saw.
        refused = deliveries.DELIVERY[deliveries.OUTCOME_REFUSED]
        not_launched = deliveries.DELIVERY[deliveries.OUTCOME_NOT_LAUNCHED]

        self.assertNotEqual(refused, not_launched)
        self.assertIn("returned an error", refused)
        self.assertIn("never reached the notification service", not_launched)

    def test_the_unreported_browser_lane_declines_to_say_the_raise_missed(self) -> None:
        # DEC-19: absence is stale in one direction only, because a tab that
        # opens sends a report and a tab that closes sends none. Trimming the
        # second sentence is what would turn this into the forbidden claim.
        self.assertIn(
            "says nothing about whether the page raised one", deliveries.BROWSER_LANE_UNREPORTED
        )


class TheRecordSurvivesARestartTest(unittest.TestCase):
    """DRC-4547's defect one layer over, refused here rather than repeated.

    An outcome held in memory would make the no-record sentence fire for every
    raise before the last restart, and that sentence means "this predates the
    record" rather than "this board forgot".
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))

    def test_a_recorded_outcome_reads_back_from_disk(self) -> None:
        self.assertTrue(
            deliveries.record(
                self.config,
                harness="claude",
                sid="s-1",
                lane="native",
                outcome=deliveries.OUTCOME_HANDED_OVER,
                now=100.0,
                diagnostic_sink=lambda _line: None,
            )
        )

        rows = deliveries.load(self.config)
        self.assertEqual(1, len(rows))
        self.assertEqual(deliveries.OUTCOME_HANDED_OVER, rows[0]["outcome"])
        self.assertEqual("native", rows[0]["lane"])

    def test_two_raises_on_one_session_are_two_records(self) -> None:
        # Session history could not hold this: `appended` keeps one transition
        # per (harness, sid) and would collapse them.
        for stamp in (100.0, 200.0):
            deliveries.record(
                self.config,
                harness="claude",
                sid="s-1",
                lane="native",
                outcome=deliveries.OUTCOME_HANDED_OVER,
                now=stamp,
                diagnostic_sink=lambda _line: None,
            )

        self.assertEqual(2, len(deliveries.load(self.config)))

    def test_an_outcome_outside_the_closed_set_is_refused_on_the_way_in(self) -> None:
        self.assertFalse(
            deliveries.record(
                self.config,
                harness="claude",
                sid="s-1",
                lane="native",
                outcome="delivered",
                now=100.0,
                diagnostic_sink=lambda _line: None,
            )
        )
        self.assertEqual((), deliveries.load(self.config))

    def test_an_outcome_outside_the_closed_set_reads_back_as_an_unknown(self) -> None:
        # Any local process can rewrite this file, and a later build can write a
        # fifth outcome this one has never heard of. The token is blanked so a
        # writer cannot choose what the board says; the RAISE is kept, because
        # dropping the row loses the raise as well and the session then reads as
        # one nobody was alerted about.
        os.makedirs(self.config.state_home, mode=0o700, exist_ok=True)
        with open(deliveries.store_path(self.config), "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "v": 1,
                    "entries": [
                        {
                            "harness": "claude",
                            "sid": "s-1",
                            "at": 1.0,
                            "lane": "native",
                            "outcome": "seen-by-the-reader",
                        },
                        {
                            "harness": "claude",
                            "sid": "s-2",
                            "at": 2.0,
                            "lane": "native",
                            "outcome": deliveries.OUTCOME_REFUSED,
                        },
                    ],
                },
                handle,
            )

        rows = deliveries.load(self.config)
        self.assertEqual(2, len(rows), "an unreadable outcome must not lose the raise")
        unknown = next(row for row in rows if row["sid"] == "s-1")
        self.assertEqual("", unknown["outcome"])
        self.assertNotIn("seen-by-the-reader", json.dumps(list(rows)))

    def test_an_unknown_outcome_renders_as_unknown_and_not_as_a_verdict(self) -> None:
        # AC3: a raise with no readable record renders as unknown. Never as
        # undelivered, which is the claim the absence of a record cannot make.
        rows: list[Delivery] = [
            {"harness": "claude", "sid": "s-1", "at": 1.0, "lane": "gate", "outcome": ""}
        ]

        row = deliveries.published(rows, "claude", "s-1")

        self.assertEqual(deliveries.NO_RECORD, row["delivery_why"])
        self.assertEqual(1, row["delivery_raises"])
        self.assertNotIn("not delivered", str(row["delivery_why"]))

    def test_an_unknown_outcome_is_not_counted_as_an_attempt(self) -> None:
        rows: list[Delivery] = [
            {"harness": "claude", "sid": "s-1", "at": 1.0, "lane": "gate", "outcome": ""}
        ]

        counted = deliveries.counts(rows)

        self.assertEqual(1, counted["raises"])
        self.assertEqual(0, counted["attempted"])
        self.assertEqual(0, counted["handed_over"])

    def test_no_caller_may_mint_an_unknown_outcome(self) -> None:
        # A read produces one; a write never does. `record` refusing "" is what
        # keeps the unknown a statement about a store this build cannot read.
        self.assertFalse(
            deliveries.record(
                self.config,
                harness="claude",
                sid="s-1",
                lane="gate",
                outcome="",
                now=100.0,
                diagnostic_sink=lambda _line: None,
            )
        )

    def test_a_corrupt_store_is_no_records_rather_than_a_raise(self) -> None:
        os.makedirs(self.config.state_home, mode=0o700, exist_ok=True)
        with open(deliveries.store_path(self.config), "w", encoding="utf-8") as handle:
            handle.write("{not json")

        self.assertEqual((), deliveries.load(self.config))

    def test_the_oldest_record_is_the_one_that_gives_way(self) -> None:
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": f"s-{n}",
                "at": float(n),
                "lane": "native",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            }
            for n in range(1, 6)
        ]
        bounded = deliveries._bounded(rows, 3)

        self.assertEqual(["s-3", "s-4", "s-5"], [row["sid"] for row in bounded])


class TheCountsAreTwoNumbersAndNotOneTest(unittest.TestCase):
    """Attempts and hand-overs answer different questions.

    A single ratio answers neither, and neither figure is a compliance number:
    what a person saw is not in here and cannot be derived from it.
    """

    def _rows(self) -> list[Delivery]:
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": "a",
                "at": 1.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            },
            {
                "harness": "claude",
                "sid": "b",
                "at": 2.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_REFUSED,
            },
            {
                "harness": "claude",
                "sid": "c",
                "at": 3.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_DID_NOT_RETURN,
            },
            {
                "harness": "claude",
                "sid": "d",
                "at": 4.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_NO_LANE,
            },
        ]
        return rows

    def test_a_raise_with_no_lane_is_not_an_attempt(self) -> None:
        counted = deliveries.counts(self._rows())

        self.assertEqual(4, counted["raises"])
        self.assertEqual(3, counted["attempted"])
        self.assertEqual(1, counted["handed_over"])

    def test_a_timeout_counts_as_attempted_and_not_as_handed_over(self) -> None:
        counted = deliveries.counts(self._rows())

        self.assertNotEqual(counted["attempted"], counted["handed_over"])


class ThePublishedRowNamesTheLatestOutcomeTest(unittest.TestCase):
    def test_a_session_with_no_raise_publishes_an_absence_and_not_a_verdict(self) -> None:
        row = deliveries.published((), "claude", "s-1")

        self.assertEqual("", row["delivery_outcome"])
        self.assertEqual("", row["delivery_why"])
        self.assertEqual(0, row["delivery_raises"])

    def test_the_absence_of_a_raise_carries_a_sentence_of_its_own(self) -> None:
        """DRC-4514. Silence beside a departure reads as a raise nobody minded.

        Its own key rather than `delivery_why`, because the session page draws
        nothing at all for a session nobody was raised about and must keep
        doing so: this sentence is only true beside a departure, and the page
        prints it only there.
        """
        row = deliveries.published((), "claude", "s-1")

        self.assertEqual(deliveries.NO_RAISE_RECORDED, row["delivery_none_why"])
        # Never both. A row with a raise has an outcome to report instead.
        self.assertNotEqual(row["delivery_none_why"], row["delivery_why"])

    def test_the_absence_sentence_says_which_raises_it_counted(self) -> None:
        """DRC-4514, walked on the board. The unnarrowed sentence was false.

        The session page prints this one inside the departure block, which is
        narrowed to the departure lane, and prints the NOTIFICATIONS block from
        every lane directly beneath it. Measured with one hook refusal on
        record and no departure raise: "No notification raise about this
        session is on record" rendered one line above "One notification was
        raised about this session". A sentence a caller narrows has to say what
        it counted.
        """
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": "s-1",
                "at": 9.0,
                "lane": "hook",
                "outcome": deliveries.OUTCOME_REFUSED,
            }
        ]

        board = deliveries.published(rows, "claude", "s-1")
        narrowed = deliveries.published(rows, "claude", "s-1", lane=deliveries.LANE_DEPARTURE)

        self.assertEqual("", board["delivery_none_why"])
        self.assertNotEqual("", narrowed["delivery_none_why"])
        self.assertNotEqual(deliveries.NO_RAISE_RECORDED, narrowed["delivery_none_why"])
        self.assertIn("departure", narrowed["delivery_none_why"])

    def test_every_lane_a_caller_narrows_to_has_its_own_absence_sentence(self) -> None:
        """The unasked lane is the only narrowing caller, and it is bound here.

        `aggregate` passes `unasked.LANE`; a lane token with no sentence would
        fall back to the board-wide wording, which is the sentence this pair
        exists to stop.
        """
        self.assertIn(unasked.LANE, deliveries.NO_RAISE_BY_LANE)
        self.assertEqual(deliveries.LANE_DEPARTURE, unasked.LANE)

    def test_a_session_with_a_raise_publishes_no_absence_sentence(self) -> None:
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": "s-1",
                "at": 9.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            }
        ]

        row = deliveries.published(rows, "claude", "s-1")

        self.assertEqual("", row["delivery_none_why"])

    def test_the_newest_raise_is_the_one_described(self) -> None:
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": "s-1",
                "at": 1.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_NO_LANE,
            },
            {
                "harness": "claude",
                "sid": "s-1",
                "at": 9.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            },
            {
                "harness": "claude",
                "sid": "other",
                "at": 5.0,
                "lane": "native",
                "outcome": deliveries.OUTCOME_REFUSED,
            },
        ]

        row = deliveries.published(rows, "claude", "s-1")

        self.assertEqual(deliveries.OUTCOME_HANDED_OVER, row["delivery_outcome"])
        self.assertEqual(2, row["delivery_raises"])
        self.assertIn("accepted it", row["delivery_why"])


class ARealRaiseWritesARecordTest(unittest.TestCase):
    """End to end through `maybe_popup`, not through the store's own API.

    Asserted here rather than only in `test_notifications` because the thing
    under test is that the outcome reaches the store at all: the notifier is
    called outside the lock and the record is written outside it too, so a
    refactor that drops the call site leaves both suites green otherwise.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))
        self.state = build_runtime_state(self.config, started=1_000.0)

    def _raise(self, outcome: str | None) -> None:
        notifications.maybe_popup(
            self.config,
            self.state,
            notifications.PopupSubject(
                harness="claude", label="Claude", prefix="s-1", activity=0.0
            ),
            "needs_input",
            "a detail",
            popup_notifier=lambda _title, _message: outcome,
        )

    def test_the_outcome_the_notifier_reported_is_what_is_stored(self) -> None:
        self._raise(deliveries.OUTCOME_REFUSED)

        rows = deliveries.load(self.config)
        self.assertEqual(1, len(rows))
        self.assertEqual(deliveries.OUTCOME_REFUSED, rows[0]["outcome"])
        self.assertEqual("gate", rows[0]["lane"])
        self.assertEqual("s-1", rows[0]["sid"])

    def test_a_notifier_that_declines_to_report_writes_no_record(self) -> None:
        # `None` is a notifier that does not report, which is not a fifth
        # outcome. Recording a guess here is the collapse this store refuses.
        self._raise(None)

        self.assertEqual((), deliveries.load(self.config))

    def test_a_gate_that_never_reaches_the_notifier_writes_no_record(self) -> None:
        # Not entering needs_input: the raise does not happen, so there is
        # nothing that became of it.
        notifications.maybe_popup(
            self.config,
            self.state,
            notifications.PopupSubject(
                harness="claude", label="Claude", prefix="s-1", activity=0.0
            ),
            "working",
            None,
            popup_notifier=lambda _title, _message: deliveries.OUTCOME_HANDED_OVER,
        )

        self.assertEqual((), deliveries.load(self.config))


class TheBrowserLaneSentencesTest(unittest.TestCase):
    """DEC-19's three, and what each of them refuses to say.

    Asserted on the rendered string rather than on the stored flag, because
    the flag cannot overclaim and the sentence can.
    """

    HOUR = 3_600.0

    def _why(self, reported_at: float, raised_at: float) -> str:
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": "s-1",
                "at": raised_at,
                "lane": "gate",
                "outcome": deliveries.OUTCOME_NO_LANE,
            }
        ]
        return str(
            deliveries.published(rows, "claude", "s-1", lane_reported_at=reported_at)[
                "browser_lane_why"
            ]
        )

    def test_no_report_does_not_say_the_raise_missed(self) -> None:
        why = self._why(0.0, 100.0)

        self.assertIn("No dashboard tab has reported", why)
        self.assertIn("says nothing about whether the page raised one", why)

    def test_a_report_before_the_raise_says_how_long_before(self) -> None:
        # The age is the whole point: a lane reported three hours before the
        # raise is weaker evidence than one reported a minute before, and
        # hiding the gap makes them read alike.
        why = self._why(100.0, 100.0 + 3 * self.HOUR)

        self.assertIn("3 hours", why)
        self.assertIn("before this raise", why)

    def test_a_report_after_the_raise_says_it_is_about_a_later_moment(self) -> None:
        why = self._why(100.0 + 3 * self.HOUR, 100.0)

        self.assertIn("after this raise", why)
        self.assertIn("says nothing about", why)

    def test_the_three_cases_are_three_different_sentences(self) -> None:
        every = {
            self._why(0.0, 100.0),
            self._why(100.0, 100.0 + self.HOUR),
            self._why(100.0 + self.HOUR, 100.0),
        }

        self.assertEqual(3, len(every))

    def test_no_lane_sentence_claims_the_reader_was_reached_or_missed(self) -> None:
        for why in (
            self._why(0.0, 100.0),
            self._why(100.0, 100.0 + self.HOUR),
            self._why(100.0 + self.HOUR, 100.0),
        ):
            with self.subTest(why=why[:40]):
                lowered = why.lower()
                for claim in ("reached you", "did not reach", "you saw", "was delivered"):
                    self.assertNotIn(claim, lowered)

    def test_a_session_with_no_raise_gets_no_lane_sentence_at_all(self) -> None:
        # Every sentence here is RELATIVE to a raise. An earlier version
        # answered a raise-less row with the positive wording and a fabricated
        # gap, so a session nobody had ever been alerted about published "a
        # dashboard tab reported a working notification lane a moment before
        # this raise".
        reported = deliveries.published((), "claude", "s-1", lane_reported_at=4_000.0)
        unreported = deliveries.published((), "claude", "s-1", lane_reported_at=0.0)

        self.assertEqual("", reported["browser_lane_why"])
        self.assertEqual("", unreported["browser_lane_why"])
        # The facts still ride, because they claim nothing on their own.
        self.assertTrue(reported["browser_lane"])
        self.assertFalse(unreported["browser_lane"])


class ARaiseThatWasNeverAttemptedSpendsNoCooldownTest(unittest.TestCase):
    """The floors are spent before the call, so a `no-lane` return refunds them.

    Without this a platform with no backend suppresses the next real
    transition for `popup_cooldown_sec` on the strength of a notification that
    did not happen, which is the same collapse this store exists to refuse.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))
        self.state = build_runtime_state(self.config, started=1_000.0)

    def _raise(self, outcome: str, prefix: str = "s-1") -> None:
        notifications.maybe_popup(
            self.config,
            self.state,
            notifications.PopupSubject(
                harness="claude", label="Claude", prefix=prefix, activity=0.0
            ),
            "needs_input",
            "a detail",
            popup_notifier=lambda _title, _message: outcome,
        )

    def test_a_no_lane_raise_leaves_both_floors_unchanged(self) -> None:
        self._raise(deliveries.OUTCOME_NO_LANE)

        self.assertNotIn("s-1", self.state.last_popup)
        self.assertNotIn("_global", self.state.last_popup)

    def test_the_next_transition_is_still_eligible_after_a_no_lane_raise(self) -> None:
        seen: list[str] = []

        def notifier(_title: str, _message: str) -> str:
            seen.append("called")
            return deliveries.OUTCOME_NO_LANE

        for _ in range(2):
            # Back to working and in again, which is the edge the floor gates.
            notifications.maybe_popup(
                self.config,
                self.state,
                notifications.PopupSubject(
                    harness="claude", label="Claude", prefix="s-1", activity=0.0
                ),
                "working",
                None,
                popup_notifier=notifier,
            )
            notifications.maybe_popup(
                self.config,
                self.state,
                notifications.PopupSubject(
                    harness="claude", label="Claude", prefix="s-1", activity=0.0
                ),
                "needs_input",
                "a detail",
                popup_notifier=notifier,
            )

        self.assertEqual(2, len(seen))

    def test_an_attempted_raise_still_spends_both_floors(self) -> None:
        # The refund must be about the outcome and nothing else. A handed-over
        # raise that refunded would re-pop the same standing gate every poll.
        self._raise(deliveries.OUTCOME_HANDED_OVER)

        self.assertIn("s-1", self.state.last_popup)
        self.assertIn("_global", self.state.last_popup)

    def test_a_refund_does_not_roll_back_another_raise_floor(self) -> None:
        # The global floor is shared. A no-lane raise refunding a value some
        # other session wrote after it would unsilence that session's gate.
        self.state.last_popup["_global"] = 9_999_999_999.0

        self._raise(deliveries.OUTCOME_NO_LANE)

        self.assertEqual(9_999_999_999.0, self.state.last_popup["_global"])


def _spec(key: str, rows: list[dict[str, Any]]) -> Any:
    """A stub harness that publishes exactly the rows it was handed."""

    def discover(_config: Any, _state: Any) -> bool:
        return True

    def collect(
        _config: Any,
        _state: Any,
        _now: float,
        _window_hours: float,
        _show_all: bool,
    ) -> list[dict[str, Any]]:
        out = []
        for row in rows:
            session = runtime_sessions.base_session(key, row["sid"], "proj")
            session.update(row)
            out.append(session)
        return out

    return aggregate.HarnessSpec(key=key, label=key.title(), discover=discover, collect=collect)


class ThePublishedPayloadCarriesTheSentencesTest(unittest.TestCase):
    """Through `collect`, which is what a reader actually gets.

    The store's own API is covered above. This is the half that would stay
    green if the attach were dropped: every row would simply carry the
    constructor's blanks, and nothing else in the suite compares them against a
    store that has records in it.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))
        self.state = build_runtime_state(self.config, started=1_000.0)

    def _collect(self, *, platform: str = "darwin") -> dict[str, Any]:
        config = dataclasses.replace(self.config, platform_name=platform)
        application = aggregate.Application(
            config,
            self.state,
            (_spec("claude", [{"sid": "s-1", "state": "idle", "active": False}]),),
            native_notifier=lambda name: "osascript" if name == "darwin" else "",
            popup_notifier=lambda _title, _message: deliveries.OUTCOME_HANDED_OVER,
            diagnostic_sink=lambda _line: None,
            clock=lambda: 9_000.0,
        )
        return dict(application.collect(show_all=True))

    def _record(self, outcome: str, *, at: float = 8_000.0) -> None:
        deliveries.record(
            self.config,
            harness="claude",
            sid="s-1",
            lane="gate",
            outcome=outcome,
            now=at,
            diagnostic_sink=lambda _line: None,
        )

    def test_a_handed_over_raise_renders_as_handed_over_and_not_as_seen(self) -> None:
        # AC2, on the rendered string rather than on the stored token: the
        # token cannot overclaim and the sentence can.
        self._record(deliveries.OUTCOME_HANDED_OVER)

        row = self._collect()["sessions"][0]

        self.assertIn("accepted it", row["delivery_why"])
        self.assertNotIn("seen", row["delivery_why"])
        self.assertIn("not something that call reports", row["delivery_why"])

    def test_a_session_nobody_raised_about_publishes_the_keys_empty(self) -> None:
        row = self._collect()["sessions"][0]

        self.assertEqual("", row["delivery_outcome"])
        self.assertEqual(0, row["delivery_raises"])

    def test_the_two_browser_lane_cases_render_as_different_sentences(self) -> None:
        # AC5, on a platform with no server-side lane.
        self._record(deliveries.OUTCOME_NO_LANE)

        unreported = self._collect(platform="linux")["sessions"][0]["browser_lane_why"]
        self.state.lane_reported_at = 4_000.0
        reported = self._collect(platform="linux")["sessions"][0]["browser_lane_why"]

        self.assertNotEqual(unreported, reported)
        for why in (unreported, reported):
            with self.subTest(why=why[:40]):
                self.assertNotIn("did not reach", why.lower())
                self.assertNotIn("reached you", why.lower())

    def test_a_report_older_than_the_raise_renders_its_age(self) -> None:
        self._record(deliveries.OUTCOME_NO_LANE, at=8_000.0)
        self.state.lane_reported_at = 8_000.0 - 2 * 3_600.0

        row = self._collect(platform="linux")["sessions"][0]

        self.assertIn("2 hours before this raise", row["browser_lane_why"])

    def test_the_lane_is_published_at_the_top_of_the_payload(self) -> None:
        # The page reads THIS key to decide whether its report has landed.
        # Publishing it only on the rows left the page unable to tell a server
        # that has its report from one that has not, and it posted a fresh
        # report on every payload, so `lane_reported_at` was always "now".
        self.state.lane_reported_at = 4_000.0

        payload = self._collect()

        self.assertIs(True, payload["browser_lane"])
        self.assertEqual(4_000.0, payload["browser_lane_at"])

    def test_an_unreported_lane_publishes_the_key_rather_than_omitting_it(self) -> None:
        payload = self._collect()

        self.assertIs(False, payload["browser_lane"])
        self.assertIsNone(payload["browser_lane_at"])

    def test_an_ask_lane_raise_reaches_the_row_it_was_about(self) -> None:
        # The ask lane records the session id the CALLER sent. For Claude that
        # is the whole UUID against a row carrying the eight-character
        # transcript prefix, so an exact match orphaned every one of them.
        deliveries.record(
            self.config,
            harness="claude",
            sid="s-1-0000-1111-2222-333344445555",
            lane="ask",
            outcome=deliveries.OUTCOME_HANDED_OVER,
            now=8_000.0,
            diagnostic_sink=lambda _line: None,
        )

        row = self._collect()["sessions"][0]

        self.assertEqual(1, row["delivery_raises"])
        self.assertEqual(deliveries.BINDING_BY_PREFIX, row["delivery_binding_why"])

    def test_the_counts_ride_on_the_payload_as_two_numbers(self) -> None:
        self._record(deliveries.OUTCOME_HANDED_OVER, at=8_000.0)
        self._record(deliveries.OUTCOME_NO_LANE, at=8_001.0)

        counts = self._collect()["delivery_counts"]

        self.assertEqual(2, counts["raises"])
        self.assertEqual(1, counts["attempted"])
        self.assertEqual(1, counts["handed_over"])


class TheOutcomesAreSeparatelyReachableTest(unittest.TestCase):
    """AC1, one leg each, with the platform set on the config.

    Set rather than read from the host deliberately: read from it, the darwin
    arm never executes on two of the three platform legs CI runs, and the three
    outcomes that need it would be untested exactly where they matter.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = dataclasses.replace(_config(Path(self.temp.name)), platform_name="darwin")

    def _notify(self, **run: Any) -> str:
        with mock.patch.object(subprocess, "run", **run):
            return notifications.notify_mac(
                self.config, "a title", "a message", diagnostic_sink=lambda _line: None
            )

    def test_a_call_that_exits_zero_is_handed_over(self) -> None:
        done = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        self.assertEqual(deliveries.OUTCOME_HANDED_OVER, self._notify(return_value=done))

    def test_a_call_that_exits_non_zero_is_refused(self) -> None:
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="nope")

        self.assertEqual(deliveries.OUTCOME_REFUSED, self._notify(return_value=failed))

    def test_a_call_that_times_out_did_not_return(self) -> None:
        # Not refused. The call did not return, so whether a banner was drawn is
        # unknown, and the two were indistinguishable while this returned None.
        blown = subprocess.TimeoutExpired(cmd="osascript", timeout=5)

        self.assertEqual(deliveries.OUTCOME_DID_NOT_RETURN, self._notify(side_effect=blown))

    def test_a_platform_with_no_backend_is_no_lane(self) -> None:
        config = dataclasses.replace(self.config, platform_name="linux")

        outcome = notifications.notify_mac(
            config, "a title", "a message", diagnostic_sink=lambda _line: None
        )

        self.assertEqual(deliveries.OUTCOME_NO_LANE, outcome)

    def test_the_five_outcomes_are_five_values(self) -> None:
        self.assertEqual(5, len(set(deliveries.OUTCOMES)))

    def test_a_call_that_cannot_start_is_not_the_service_refusing(self) -> None:
        # A missing or unexecutable binary. The service never saw the request,
        # so reporting it as a refusal names the wrong party.
        missing = OSError(2, "No such file or directory")

        self.assertEqual(deliveries.OUTCOME_NOT_LAUNCHED, self._notify(side_effect=missing))


class ConcurrentWritersKeepEveryRecordTest(unittest.TestCase):
    """Three threads reach `record`, and the store has to survive all three.

    The collection worker raises the gate lane, the `/api/notify` handler the
    hook lane, the `/api/ask` handler the ask lane, all in one server. Measured
    before the lock: two barrier-synchronised writers lost a record in 60 of 60
    trials, and three writers against a seeded store left it unparseable and
    rebuilt it with a handful of entries.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))

    def _record(self, n: int) -> None:
        deliveries.record(
            self.config,
            harness="claude",
            sid=f"s-{n}",
            lane="gate",
            outcome=deliveries.OUTCOME_HANDED_OVER,
            now=100.0 + n,
            diagnostic_sink=lambda _line: None,
        )

    def test_two_simultaneous_writers_both_land(self) -> None:
        ready = threading.Barrier(2)

        def write(n: int) -> None:
            ready.wait()
            self._record(n)

        threads = [threading.Thread(target=write, args=(n,)) for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(2, len(deliveries.load(self.config)))

    def test_many_writers_leave_a_store_that_still_parses(self) -> None:
        threads = [threading.Thread(target=self._record, args=(n,)) for n in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        rows = deliveries.load(self.config)
        self.assertEqual(12, len(rows))
        self.assertEqual(12, len({row["sid"] for row in rows}))

    def test_no_two_records_write_the_store_at_the_same_time(self) -> None:
        # The lock, measured rather than asserted by reading. Without it the
        # read-modify-write interleaves and the later writer saves a list built
        # before the earlier one landed.
        depth = 0
        deepest = 0
        real_open = os.open

        def watched(path: str, *args: Any, **kwargs: Any) -> int:
            nonlocal depth, deepest
            if not str(path).endswith(".tmp"):
                return real_open(path, *args, **kwargs)
            depth += 1
            deepest = max(deepest, depth)
            try:
                # Long enough that an unlocked sibling would be inside its own
                # save by the time this returns.
                time.sleep(0.01)
                return real_open(path, *args, **kwargs)
            finally:
                depth -= 1

        with mock.patch.object(os, "open", watched):
            threads = [threading.Thread(target=self._record, args=(n,)) for n in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(1, deepest, "two writers were inside the store write at once")
        self.assertEqual(6, len(deliveries.load(self.config)))

    def test_two_concurrent_saves_do_not_share_a_temp_path(self) -> None:
        # `save` is public and takes no lock: it replaces the whole store, so
        # two callers racing is a lost update rather than a corrupt file, and
        # only if they do not share a temp name. A shared one means both open it
        # O_TRUNC on independent descriptors and `os.replace` the interleaving.
        opened: list[str] = []
        both_open = threading.Barrier(2, timeout=30)
        real_open = os.open

        def watched(path: str, *args: Any, **kwargs: Any) -> int:
            if not str(path).endswith(".tmp"):
                return real_open(path, *args, **kwargs)
            opened.append(str(path))
            handle = real_open(path, *args, **kwargs)
            both_open.wait()
            return handle

        def save(n: int) -> None:
            row: Delivery = {
                "harness": "claude",
                "sid": f"s-{n}",
                "at": float(n + 1),
                "lane": "gate",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            }
            deliveries.save(self.config, [row], diagnostic_sink=lambda _line: None)

        with mock.patch.object(os, "open", watched):
            threads = [threading.Thread(target=save, args=(n,)) for n in (1, 2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(2, len(opened))
        self.assertEqual(2, len(set(opened)), "two writers shared one temp path")


class RaisesBoundToTheRowTheyWereAboutTest(unittest.TestCase):
    """The ask lane records the id the CALLER sent, not the one the row carries.

    For Claude those differ: the caller sends the whole UUID and the collector
    publishes the transcript stem's first eight characters. Matching them
    exactly orphaned every ask-lane outcome from its row, so a question the
    reader had been alerted to showed no raise at all.
    """

    def _rows(self) -> list[Delivery]:
        return [
            {
                "harness": "claude",
                "sid": "abcd1234-5678-90ab-cdef-000000000000",
                "at": 5.0,
                "lane": "ask",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            }
        ]

    def test_a_full_uuid_raise_reaches_the_eight_character_row(self) -> None:
        row = deliveries.published(self._rows(), "claude", "abcd1234", by_prefix=True)

        self.assertEqual(1, row["delivery_raises"])
        self.assertEqual(deliveries.OUTCOME_HANDED_OVER, row["delivery_outcome"])

    def test_the_prefix_binding_says_so_rather_than_claiming_certainty(self) -> None:
        row = deliveries.published(self._rows(), "claude", "abcd1234", by_prefix=True)

        self.assertEqual(deliveries.BINDING_BY_PREFIX, row["delivery_binding_why"])
        self.assertIn("would be counted here", str(row["delivery_binding_why"]))

    def test_an_exact_binding_claims_nothing_about_prefixes(self) -> None:
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": "abcd1234",
                "at": 5.0,
                "lane": "gate",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            }
        ]

        row = deliveries.published(rows, "claude", "abcd1234")

        self.assertEqual(1, row["delivery_raises"])
        self.assertEqual("", row["delivery_binding_why"])

    def test_the_prefix_never_runs_the_other_way(self) -> None:
        # A short stored key must not claim every longer session that starts
        # with it. Only the ROW's sid may be the truncation.
        rows: list[Delivery] = [
            {
                "harness": "claude",
                "sid": "abcd1234",
                "at": 5.0,
                "lane": "gate",
                "outcome": deliveries.OUTCOME_HANDED_OVER,
            }
        ]

        row = deliveries.published(rows, "claude", "abcd1234-5678", by_prefix=True)

        self.assertEqual(0, row["delivery_raises"])

    def test_a_row_with_no_identity_claims_no_raise(self) -> None:
        row = deliveries.published(self._rows(), "claude", "", by_prefix=True)

        self.assertEqual(0, row["delivery_raises"])


class MixedOutcomesAreNamedRatherThanFlattenedTest(unittest.TestCase):
    """One sentence is published and the count is plural, so they must not read
    as one claim.

    A session whose first raise was refused and whose second was handed over
    would otherwise render as two hand-overs.
    """

    def _rows(self, *outcomes: str) -> list[Delivery]:
        return [
            {
                "harness": "claude",
                "sid": "s-1",
                "at": float(n + 1),
                "lane": "gate",
                "outcome": outcome,
            }
            for n, outcome in enumerate(outcomes)
        ]

    def test_two_different_outcomes_are_reported_as_mixed(self) -> None:
        row = deliveries.published(
            self._rows(deliveries.OUTCOME_REFUSED, deliveries.OUTCOME_HANDED_OVER), "claude", "s-1"
        )

        self.assertIs(True, row["delivery_mixed"])
        self.assertEqual(deliveries.MIXED_OUTCOMES, row["delivery_mixed_why"])
        self.assertEqual(deliveries.OUTCOME_HANDED_OVER, row["delivery_outcome"])

    def test_repeated_identical_outcomes_are_not_mixed(self) -> None:
        row = deliveries.published(
            self._rows(deliveries.OUTCOME_HANDED_OVER, deliveries.OUTCOME_HANDED_OVER),
            "claude",
            "s-1",
        )

        self.assertIs(False, row["delivery_mixed"])
        self.assertEqual("", row["delivery_mixed_why"])


if __name__ == "__main__":
    unittest.main()
