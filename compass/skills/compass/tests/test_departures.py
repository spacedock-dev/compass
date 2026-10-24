"""What the departure store says about a raise, and about what came after it.

DRC-4514. Two things live here that the store alone did not answer before.

The four why-sentences moved down from `unasked.published`, because the review
surface and the Intent log both need them and neither may reach the lane: one
owner, so a spent cap cannot be worded one way on the session page and another
way where the reader reviews it.

The follow-up sentence is derived from later CHECKS in this same store rather
than from a second model call. That is what makes it affordable, and it is also
the only evidence available: a reader-requested reading carries its evidence
cutoff as a producer's sentence and not as a number, so nothing on it can be
compared with a departure's cutoff.
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import departures
from compass_runtime.config import build_runtime_config


def _config(root: Path, **changes: Any) -> Any:
    config = build_runtime_config(
        environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
        platform_name="linux",
        os_name="posix",
        launcher_path=root / "server.py",
        unasked_enabled=True,
    )
    return dataclasses.replace(config, **changes) if changes else config


def _check(**over: Any) -> departures.Check:
    row: dict[str, Any] = {
        "harness": "claude",
        "sid": "abcd1234",
        "at": 1_000.0,
        "constraint": "TYPED GOAL",
        "clause": "do not change the board while capturing",
        "reading": "Two turns edited the running board's markup between captures.",
        "evidence": "turn transcript · Claude",
        "revision": 2,
        "cutoff": 1_000.0,
        "cutoff_text": "Evidence stops at 13:22.",
        "withdrawn": False,
    }
    row.update(over)
    return row  # type: ignore[return-value]


class DepartureWhySentenceTest(unittest.TestCase):
    """The four sentences, chosen once and read from three surfaces."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.config = _config(Path(self._dir.name))

    def test_a_session_nobody_checked_is_not_a_session_found_to_be_on_track(self) -> None:
        why = departures.why(
            self.config, (), "claude", "abcd1234", has_words=True, discarded=False, now=2_000.0
        )

        self.assertEqual(departures.NEVER_CHECKED, why)

    def test_a_checked_session_with_no_raise_says_nothing_departed(self) -> None:
        stored = (_check(constraint="", clause="", reading="", evidence=""),)

        why = departures.why(
            self.config, stored, "claude", "abcd1234", has_words=True, discarded=False, now=2_000.0
        )

        self.assertEqual(departures.NOTHING_DEPARTED, why)

    def test_a_spent_session_cap_says_a_limit_was_spent(self) -> None:
        stored = tuple(
            _check(at=1_000.0 + n, cutoff=1_000.0 + n, constraint="", clause="")
            for n in range(self.config.unasked_session_cap)
        )

        why = departures.why(
            self.config, stored, "claude", "abcd1234", has_words=True, discarded=False, now=2_000.0
        )

        self.assertEqual(departures.SESSION_EXHAUSTED, why)

    def test_a_spent_day_cap_outranks_a_session_that_has_room(self) -> None:
        stored = (
            *(
                _check(sid=f"s-{n}", at=1_000.0 + n, cutoff=1_000.0 + n, constraint="")
                for n in range(self.config.unasked_daily_cap)
            ),
            _check(constraint=""),
        )

        why = departures.why(
            self.config, stored, "claude", "abcd1234", has_words=True, discarded=False, now=1_100.0
        )

        self.assertEqual(departures.DAY_EXHAUSTED, why)

    def test_a_session_with_a_raise_earns_no_absence_sentence(self) -> None:
        why = departures.why(
            self.config,
            (_check(),),
            "claude",
            "abcd1234",
            has_words=True,
            discarded=False,
            now=2_000.0,
        )

        self.assertEqual("", why)

    def test_a_checked_session_with_no_words_left_is_not_a_session_found_on_track(self) -> None:
        """DRC-4560. The blank-save route leaves a check with nothing behind it.

        `clear` beside the box empties it and the save after it mints a
        revision holding two empty strings, so the entry survives with nothing
        in it while the check recorded against the earlier revisions stays
        standing. Read against those words, nothing has been checked.
        """
        stored = (_check(constraint="", clause="", reading="", evidence=""),)

        why = departures.why(
            self.config, stored, "claude", "abcd1234", has_words=False, discarded=False, now=2_000.0
        )

        self.assertEqual(departures.NEVER_CHECKED, why)

    def test_a_check_with_no_words_behind_it_is_not_a_check_of_what_you_ask_now(self) -> None:
        """The figure and the sentence move together, on one predicate."""
        stored = (_check(constraint="", clause="", reading="", evidence=""),)

        self.assertIs(False, departures.checked(stored, "claude", "abcd1234", has_words=False))
        self.assertIs(True, departures.checked(stored, "claude", "abcd1234", has_words=True))

    def test_a_standing_raise_is_never_printed_under_the_never_checked_sentence(self) -> None:
        """DRC-4560, the half the words test would otherwise have introduced.

        `published` serves every non-withdrawn row whatever the words now say,
        and both surfaces print this sentence directly beneath those rows, so
        the wordless session read "One departure was raised", the raise itself,
        and then "Compass has not checked this session against what you asked
        for" on one screen. That is the contradiction class DRC-4560 exists to
        remove, arriving from the other side.
        """
        stored = (_check(),)

        why = departures.why(
            self.config, stored, "claude", "abcd1234", has_words=False, discarded=False, now=2_000.0
        )

        self.assertEqual("", why)
        # And the figure stays unmeasured, which is what DRC-4560 wanted: the
        # check read words that are gone, so nothing counts it as a reading of
        # what the reader asks for now.
        self.assertIs(False, departures.checked(stored, "claude", "abcd1234", has_words=False))

    def test_a_spent_cap_still_outranks_a_standing_raise_with_no_words(self) -> None:
        """The stand-down is only over the never-checked sentence.

        A cap that is spent is a fact about what will run next, and it stays
        true of a session whose words have gone; only the sentence claiming
        nothing was ever looked at here is the false one.
        """
        stored = tuple(_check(at=1_000.0 + n) for n in range(self.config.unasked_session_cap))

        why = departures.why(
            self.config, stored, "claude", "abcd1234", has_words=False, discarded=False, now=2_000.0
        )

        self.assertEqual(departures.SESSION_EXHAUSTED, why)

    def test_a_discard_record_earns_no_absence_sentence_at_all(self) -> None:
        """DRC-4565. The third state, and the reason `has_words` cannot carry it.

        A record has no words, so every argument here matches the wordless
        session above and the ladder answered `NEVER_CHECKED`. The record
        beside it has already said what happened, in the board's own voice,
        and this sentence reads as a second account of it.
        """
        why = departures.why(
            self.config, (), "claude", "abcd1234", has_words=False, discarded=True, now=2_000.0
        )

        self.assertEqual("", why)
        # The same inputs without the record earn the sentence, so the argument
        # and not something else is what stood it down.
        self.assertEqual(
            departures.NEVER_CHECKED,
            departures.why(
                self.config, (), "claude", "abcd1234", has_words=False, discarded=False, now=2_000.0
            ),
        )

    def test_a_record_of_a_session_that_was_checked_says_nothing_about_the_past(self) -> None:
        """The half the sentence gets wrong twice over.

        A check ran, then the words went and the row was withdrawn. `checked`
        needs words, so the ladder said this session had never been checked
        against what the reader asked for -- about a session it had checked.
        """
        stored = (_check(constraint="", clause="", reading="", evidence="", withdrawn=True),)

        why = departures.why(
            self.config, stored, "claude", "abcd1234", has_words=False, discarded=True, now=2_000.0
        )

        self.assertEqual("", why)


class DepartureFollowUpTest(unittest.TestCase):
    """What later evidence showed, and never that the raise caused it."""

    def test_unknown_is_the_default_and_names_its_reason(self) -> None:
        rows = departures.published((_check(),), "claude", "abcd1234")

        self.assertEqual(departures.FOLLOW_UP_NO_LATER_CHECK, rows[0]["follow_up"])

    def test_the_sentence_claims_a_later_check_ran_and_never_what_it_read(self) -> None:
        """The store holds no evidence bound, so no sentence may rest on one.

        Both producer write sites record `cutoff = now`, so two checks over
        byte-identical evidence carry different cutoffs and two checks over
        different evidence can carry the same one. The branch that reported "a
        later check read evidence from after this raise" compared those two
        numbers, and its own test built a row the runtime cannot write: `at`
        2000 against `cutoff` 900.
        """
        same_evidence = (
            _check(cutoff_text="Read 12 of the 12 entries after your words."),
            _check(
                at=2_000.0,
                cutoff=2_000.0,
                cutoff_text="Read 12 of the 12 entries after your words.",
                constraint="",
            ),
        )

        rows = departures.published(same_evidence, "claude", "abcd1234")

        self.assertEqual(departures.FOLLOW_UP_NOT_RAISED_AGAIN, rows[0]["follow_up"])
        for sentence in (
            departures.FOLLOW_UP_NOT_RAISED_AGAIN,
            departures.FOLLOW_UP_RAISED_AGAIN,
        ):
            with self.subTest(sentence=sentence[:24]):
                self.assertIn("A later check ran after this raise", sentence)
                self.assertNotIn("evidence", sentence)

    def test_a_later_check_that_raised_nothing_reports_the_evidence_not_an_effect(self) -> None:
        stored = (_check(), _check(at=2_000.0, cutoff=2_000.0, constraint="", clause=""))

        rows = departures.published(stored, "claude", "abcd1234")

        self.assertEqual(departures.FOLLOW_UP_NOT_RAISED_AGAIN, rows[0]["follow_up"])
        # The issue's third prohibition, asserted rather than trusted to the
        # wording: nothing here may read as the raise having worked.
        self.assertNotIn("because", rows[0]["follow_up"])

    def test_a_later_check_raising_the_same_constraint_says_it_departed_again(self) -> None:
        stored = (_check(), _check(at=2_000.0, cutoff=2_000.0))

        rows = departures.published(stored, "claude", "abcd1234")

        self.assertEqual(departures.FOLLOW_UP_RAISED_AGAIN, rows[1]["follow_up"])
        self.assertEqual(departures.FOLLOW_UP_NO_LATER_CHECK, rows[0]["follow_up"])

    def test_a_later_check_raising_a_different_constraint_is_not_this_one(self) -> None:
        stored = (_check(), _check(at=2_000.0, cutoff=2_000.0, constraint="EXPECTED OUTPUT"))

        rows = departures.published(stored, "claude", "abcd1234")
        by_constraint = {row["constraint"]: row["follow_up"] for row in rows}

        self.assertEqual(departures.FOLLOW_UP_NOT_RAISED_AGAIN, by_constraint["TYPED GOAL"])

    def test_a_later_check_that_never_finished_says_no_later_check(self) -> None:
        """A cancelled or failed call is a withdrawn row: charged, and not a check.

        Read as a check it published "did not raise this constraint again" about
        a check that never read anything.
        """
        stored = (
            _check(),
            _check(at=2_000.0, cutoff=2_000.0, constraint="", clause="", withdrawn=True),
        )

        rows = departures.published(stored, "claude", "abcd1234")

        self.assertEqual(departures.FOLLOW_UP_NO_LATER_CHECK, rows[0]["follow_up"])
        self.assertEqual(2, departures.counts(stored, "claude", "abcd1234", since=0)[0])

    def test_another_session_s_later_check_says_nothing_about_this_one(self) -> None:
        stored = (_check(), _check(sid="zzzz9999", at=2_000.0, cutoff=2_000.0, constraint=""))

        rows = departures.published(stored, "claude", "abcd1234")

        self.assertEqual(departures.FOLLOW_UP_NO_LATER_CHECK, rows[0]["follow_up"])

    def test_the_follow_up_is_derived_at_publish_and_never_read_from_the_file(self) -> None:
        """A stored row that already carries one is not trusted on read-back.

        The store is a file any local process can rewrite, and a sentence about
        what happened next is the one a rewriter would most want to choose.
        """
        rows = departures.published((_check(follow_up="anything at all"),), "claude", "abcd1234")

        self.assertEqual(departures.FOLLOW_UP_NO_LATER_CHECK, rows[0]["follow_up"])


class DepartureCountsAreNotRaiseCountsTest(unittest.TestCase):
    """A row for every check is what bounds spend; it is not a count of raises."""

    def test_twelve_quiet_checks_and_two_raises_publish_two_rows(self) -> None:
        stored = (
            *(_check(at=100.0 + n, cutoff=100.0 + n, constraint="") for n in range(12)),
            _check(at=200.0),
            _check(at=201.0, constraint="EXPECTED OUTPUT"),
        )

        rows = departures.published(stored, "claude", "abcd1234")

        # Fourteen rows in the store, two of them raises. A surface counting
        # store rows would tell the reader this session departed fourteen times.
        self.assertEqual(14, len(stored))
        self.assertEqual(2, len(rows))


class DepartureWithdrawalTest(unittest.TestCase):
    """Clearing what you asked withdraws the raises made against those words.

    `GET /api/annotations` serves the departure store for sessions that have
    left the board, and `SECURITY.md` says words withdrawn with a clear are gone
    from that response. `annotations.clear` deletes every revision and reaches
    no other store, so a session cleared and re-annotated served the withdrawn
    clause verbatim under a model's sentence about it.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.config = _config(Path(self._dir.name))
        departures.save(self.config, (_check(), _check(at=1_001.0, constraint="")))

    def test_the_words_go_and_the_row_stays(self) -> None:
        self.assertIs(True, departures.withdraw(self.config, "claude", "abcd1234"))
        stored = departures.load(self.config)

        # The row is still there, because it is what the caps count.
        self.assertEqual(2, len(stored))
        for row in stored:
            with self.subTest(at=row["at"]):
                self.assertIs(True, row["withdrawn"])
                self.assertEqual("", row["clause"])
                self.assertEqual("", row["reading"])
                self.assertEqual("", row["constraint"])
                self.assertEqual("", row["evidence"])
                self.assertEqual("", row["cutoff_text"])
        # And the raise leaves the wire it was leaking through.
        self.assertEqual([], departures.published(stored, "claude", "abcd1234"))

    def test_another_session_s_raise_is_untouched(self) -> None:
        departures.save(
            self.config,
            (*departures.load(self.config), _check(sid="zzzz9999", at=1_002.0)),
        )

        departures.withdraw(self.config, "claude", "abcd1234")

        rows = departures.published(departures.load(self.config), "claude", "zzzz9999")
        self.assertEqual("do not change the board while capturing", rows[0]["clause"])

    def test_a_withdrawn_session_reads_as_never_checked_against_what_you_ask_now(self) -> None:
        departures.withdraw(self.config, "claude", "abcd1234")

        why = departures.why(
            self.config,
            departures.load(self.config),
            "claude",
            "abcd1234",
            has_words=True,
            discarded=False,
            now=2_000.0,
        )

        # Not NOTHING_DEPARTED, which would say the words on the row now had
        # been read and found clean. Nothing has read them at all.
        self.assertEqual(departures.NEVER_CHECKED, why)

    def test_a_withdrawal_is_not_a_refund_of_the_cap_it_spent(self) -> None:
        """The row stays for exactly this reason, and the sentence must say so.

        Deleting the rows would hand the session its per-session cap back, and
        the caps are what bound a `codex` subprocess at `reasoning_effort=max`:
        five healthy sessions ran 480 of them in a simulated day against a daily
        cap of 12 on the version that counted raises instead of checks.
        """
        spent = tuple(
            _check(at=1_000.0 + n, cutoff=1_000.0 + n, constraint="")
            for n in range(self.config.unasked_session_cap)
        )
        departures.save(self.config, spent)
        departures.withdraw(self.config, "claude", "abcd1234")
        stored = departures.load(self.config)

        mine, _today = departures.counts(stored, "claude", "abcd1234", since=0.0)
        self.assertEqual(self.config.unasked_session_cap, mine)
        # And the board says the cap is spent rather than only that nothing has
        # been checked, because no further check will run either way.
        self.assertEqual(
            departures.SESSION_EXHAUSTED,
            departures.why(
                self.config,
                stored,
                "claude",
                "abcd1234",
                has_words=True,
                discarded=False,
                now=2_000.0,
            ),
        )

    def test_nothing_to_withdraw_is_a_success_and_not_a_write(self) -> None:
        before = Path(departures.store_path(self.config)).read_bytes()

        self.assertIs(True, departures.withdraw(self.config, "claude", "no-such-session"))

        self.assertEqual(before, Path(departures.store_path(self.config)).read_bytes())

    def test_a_rewritten_file_cannot_serve_a_withdrawn_raise_by_keeping_a_constraint(
        self,
    ) -> None:
        """The mark is tested, not only the blanking it comes with.

        `withdraw` blanks the quotations AND marks the row, so the constraint
        filter alone happens to hide what it produces and a test through the
        producer cannot tell the two guards apart. This file is writable by any
        local process, which is the whole reason `_entry` type-checks it, and a
        row marked withdrawn while still carrying a constraint is what that
        process would write.
        """
        departures.save(
            self.config,
            (_check(withdrawn=True), _check(at=1_003.0, constraint="EXPECTED OUTPUT")),
        )

        rows = departures.published(departures.load(self.config), "claude", "abcd1234")

        self.assertEqual(["EXPECTED OUTPUT"], [row["constraint"] for row in rows])

    def test_the_mark_never_reaches_the_wire(self) -> None:
        """A served row is by construction not withdrawn, so the key is noise."""
        rows = departures.published(departures.load(self.config), "claude", "abcd1234")

        self.assertNotIn("withdrawn", rows[0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
