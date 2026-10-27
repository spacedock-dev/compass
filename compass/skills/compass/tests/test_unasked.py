"""The unasked reading lane, and the four things it must never do.

DRC-4541. The lane checks an annotated session against what the reader typed
without being asked and raises a departure. It is off by default, it spends the
reader's own model capacity, and the reader is by construction not at the desk
while it runs, which is why most of what is asserted here is a refusal.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

from compass_runtime import (
    departures,
    diagnostics,
    reading,
    reading_policy,
    supervise,
    unasked,
)
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

if TYPE_CHECKING:
    from compass_runtime.annotations import Annotation


def _config(root: Path, **changes: Any) -> Any:
    config = build_runtime_config(
        environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
        platform_name="linux",
        os_name="posix",
        launcher_path=root / "server.py",
        unasked_enabled=True,
    )
    import dataclasses  # noqa: PLC0415

    return dataclasses.replace(config, **changes) if changes else config


def _installed_providers(case: unittest.TestCase) -> None:
    """Both provider binaries found, so a lane test never depends on the machine it runs on.

    The reading route asks `shutil.which` whether `claude` or `codex` is installed. These
    tests drive `Lane.consider` directly, so a machine with neither (CI) refused every
    reading and counted none, while a desk with both passed.
    """
    patcher = mock.patch.object(shutil, "which", side_effect=lambda name, **_: f"/bin/{name}")
    patcher.start()
    case.addCleanup(patcher.stop)


def _taking(seen: list[str]) -> Any:
    """A `reading.claim` stub that records the key and always grants."""

    def claim(_config: Any, key: str) -> bool:
        seen.append(key)
        return True

    return claim


def _annotation(sid: str = "s-1") -> Annotation:
    return {
        "harness": "claude",
        "sid": sid,
        "revisions": ({"n": 4, "goal": "Ship the cockpit", "lines": (), "at": 10.0},),
    }


def _row(sid: str = "s-1", state: str = "working") -> dict[str, Any]:
    return {"harness": "claude", "sid": sid, "state": state, "project": "trio/app"}


def _assessment(*results: str) -> reading.Assessment:
    return {
        "revision_read": 4,
        "revision_read_at": 10.0,
        "window_start": None,
        "read_at": None,
        "stamp": "a stamp",
        # Prose, which is what the producer actually writes: `cutoff_text`
        # composes a sentence about what was read, by count and by author.
        # An earlier fixture put "900.0" here and hid a parser that returned 0
        # on every real reading.
        "cutoff": "12 entries read, 3 by you and 9 by the agent.",
        "scope": "final",
        "scope_text": "",
        "ended_at_read": None,
        "evidence_through": None,
        "criteria": {
            f"c{n}": {
                "result": result,
                "cites": ("e1",),
                "detail": "went elsewhere",
                "clause": "G",
                "why": reading.WHY_STANDS,
            }
            for n, result in enumerate(results)
        },
    }


class _Harness:
    """One lane with every outside edge replaced by something countable."""

    def __init__(self, config: Any, assessment: reading.Assessment | None) -> None:
        self.config = config
        self.state = build_runtime_state(config, started=1_000.0)
        self.readings: list[str] = []
        self.popups: list[tuple[str, str]] = []
        self.assessment = assessment

        def produce(_config: Any, row: Any, *_args: Any, **_kwargs: Any) -> Any:
            self.readings.append(str(row.get("sid")))
            # A withheld reading spent nothing, as `reading.produce` answers;
            # a spent failure is `AFailedCallStillSpendsTheCapsTest`'s case.
            return (self.assessment, "", self.assessment is not None)

        def popup(title: str, message: str) -> str:
            self.popups.append((title, message))
            return "handed-over"

        self.lane = unasked.Lane(
            config,
            popup_notifier=popup,
            diagnostic_sink=lambda _line: None,
            clock=lambda: 5_000.0,
            produce=produce,
            facts_for=lambda _state, _row, _now: [{"id": "e1"}],
            # Inline rather than threaded, so a test asserts on what happened
            # rather than on what was scheduled. The lane's own threading is
            # covered by the in-flight test below.
            spawn=lambda work: work(),
        )

    def consider(self, rows: list[dict[str, Any]], *, now: float = 5_000.0) -> None:
        with mock.patch.object(
            shutil,
            "which",
            side_effect=lambda name: f"/bin/{name}" if name == "codex" else None,
        ):
            self.lane.consider(self.state, rows, [_annotation()], now=now)


class TheSwitchIsTheWholeGateTest(unittest.TestCase):
    """AC1. With the switch off nothing runs, asserted on the absence of a call.

    Asserted at the assembly point rather than inside the lane, because with the
    switch off there is no lane: `build_application` does not attach one, so
    there is no code path a later refactor could leave reachable.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_the_switch_defaults_off(self) -> None:
        config = build_runtime_config(
            environ={"HOME": str(self.root)},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )

        self.assertFalse(config.unasked_enabled)

    def test_no_lane_is_attached_with_the_switch_off(self) -> None:
        from compass_runtime import cli  # noqa: PLC0415

        config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        state = build_runtime_state(config, started=1_000.0)

        application = cli.build_application(config, state, diagnostic_sink=lambda _line: None)

        self.assertIsNone(application.unasked_lane)

    def test_diagnose_attaches_no_lane_even_with_the_switch_on(self) -> None:
        # `--diagnose` runs a collection and must not start a codex subprocess
        # while reporting what the stores hold. It is the one caller that says
        # no to `record_history`, and this rides the same signal rather than
        # inventing a second is-this-diagnose flag.
        from compass_runtime import cli  # noqa: PLC0415

        config = _config(self.root)
        state = build_runtime_state(config, started=1_000.0)

        application = cli.build_application(
            config, state, diagnostic_sink=lambda _line: None, record_history=False
        )

        self.assertIsNone(application.unasked_lane)

    def test_the_lane_is_attached_when_the_switch_is_on(self) -> None:
        from compass_runtime import cli  # noqa: PLC0415

        config = _config(self.root)
        state = build_runtime_state(config, started=1_000.0)

        application = cli.build_application(config, state, diagnostic_sink=lambda _line: None)

        self.assertIsNotNone(application.unasked_lane)

    def _serving(self, *argv: str) -> Any:
        """An application built the way `server.py` builds one, from argv."""
        from compass_runtime import cli  # noqa: PLC0415

        environ = {"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")}
        args = cli.build_parser().parse_args(list(argv))
        with mock.patch.object(cli, "runtime_environ", return_value=environ):
            config, state = cli.build_runtime(args, started=1_000.0)
        return cli.build_application(config, state, diagnostic_sink=lambda _line: None)

    def test_the_off_switch_refuses_the_lane(self) -> None:
        # DRC-4649. SECURITY.md's Light harness usage off switch refuses every
        # model call for the run, and the unasked lane is the one caller that
        # used to not read it: `--unasked-readings --no-harness-usage` started
        # codex readings anyway. Both spellings, because the alias is the one
        # the issue was reported against.
        #
        # The lane is the only thing that starts a codex subprocess for an
        # unasked reading, so the assertion is that it is never constructed.
        # Patching `subprocess` around a collection instead would pass with the
        # guard removed: a fresh home has no annotated session to read, so no
        # reading is attempted either way.
        for off_switch in ("--no-harness-usage", "--no-observer-model"):
            with self.subTest(off_switch=off_switch):
                with mock.patch.object(unasked, "Lane", wraps=unasked.Lane) as lane:
                    application = self._serving("--unasked-readings", off_switch)
                    payload = application.collect(show_all=False)

                lane.assert_not_called()
                self.assertIsNone(application.unasked_lane)
                self.assertFalse(application.config.unasked_enabled)
                # The page draws the lane-off sentence from this key's absence.
                self.assertNotIn("unasked", payload)
                # And no toggle or cue can be drawn: the page reads who the lane
                # would reach from this key alone.
                self.assertNotIn("unasked_routes", payload)
                self.assertIs(False, diagnostics.diagnose(application)["unasked"]["enabled"])

    def test_no_annotations_turns_the_lane_off(self) -> None:
        # The lane reads typed goals and the Codex toggle is refused without
        # annotations, so publishing either would draw a control that never works.
        application = self._serving("--unasked-readings", "--no-annotations")
        self.assertIsNone(application.unasked_lane)
        self.assertFalse(application.config.unasked_enabled)
        payload = application.collect(show_all=False)
        self.assertNotIn("unasked", payload)
        self.assertNotIn("unasked_routes", payload)

    def test_the_switch_alone_still_attaches_the_lane(self) -> None:
        # The control for the test above, so its refusal is the off switch's
        # doing and not a harness that never attaches the lane from argv.
        application = self._serving("--unasked-readings")

        self.assertIsNotNone(application.unasked_lane)
        payload = application.collect(show_all=False)
        self.assertIs(True, payload.get("unasked"))
        self.assertIsInstance(payload.get("unasked_routes"), dict)
        self.assertIs(True, diagnostics.diagnose(application)["unasked"]["enabled"])


class ItEvaluatesOnAChangeAndNotPerCollectionTest(unittest.TestCase):
    """AC2. A working session generates nothing until something changes."""

    def setUp(self) -> None:
        _installed_providers(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.harness = _Harness(_config(Path(self.temp.name)), _assessment("departure"))

    def _harness(self) -> _Harness:
        return self.harness

    def test_the_first_sighting_of_a_row_is_not_a_change(self) -> None:
        # The board restarts and has observed nothing. Treating every row of
        # the first collection as a transition would read the whole board at
        # once on a boot nobody asked for.
        self.harness.consider([_row(state="working")])

        self.assertEqual([], self.harness.readings)

    def test_an_unchanged_session_produces_none(self) -> None:
        for _ in range(4):
            self.harness.consider([_row(state="working")])

        self.assertEqual([], self.harness.readings)

    def test_one_change_produces_one_reading(self) -> None:
        self.harness.consider([_row(state="working")])
        self.harness.consider([_row(state="idle")])
        self.harness.consider([_row(state="idle")])

        self.assertEqual(["s-1"], self.harness.readings)

    def test_a_session_nobody_annotated_is_never_read(self) -> None:
        self.harness.lane.consider(self.harness.state, [_row(state="working")], [], now=5_000.0)
        self.harness.lane.consider(self.harness.state, [_row(state="idle")], [], now=5_000.0)

        self.assertEqual([], self.harness.readings)

    def test_an_annotation_arriving_later_is_not_itself_a_change(self) -> None:
        # The state is noted for every row whether or not it is a candidate, so
        # a session annotated after it was first seen does not read as a
        # transition the moment the words land.
        self.harness.lane.consider(self.harness.state, [_row(state="working")], [], now=5_000.0)
        self.harness.consider([_row(state="working")])

        self.assertEqual([], self.harness.readings)

    def test_two_collections_over_unchanged_evidence_add_no_row(self) -> None:
        """DRC-4514 AC2, asserted on the store rather than on the lane's log.

        The review surface reads the store, so the claim that matters there is
        that the file did not grow. Verified, not rebuilt.

        Which side binds, measured by mutation: removing the `changed` gate in
        `consider` alone leaves this green, because `_claim`'s per-session floor
        still holds the second reading off. Removing both turns it red at
        `1 != 2`. So this binds the pair rather than either one, which is the
        claim the review surface actually rests on.
        """
        self.harness.consider([_row(state="working")])
        self.harness.consider([_row(state="idle")])
        after_one_change = departures.load(self.harness.config)

        for _ in range(3):
            self.harness.consider([_row(state="idle")])

        self.assertEqual(1, len(after_one_change))
        self.assertEqual(after_one_change, departures.load(self.harness.config))

    def test_only_one_reading_starts_per_collection(self) -> None:
        # Forty annotated sessions crossing a boundary together must not start
        # forty subprocesses. Written against a SYNCHRONOUS worker on purpose:
        # with an asynchronous one the in-flight slot masks this, and the
        # guarantee would then rest on a `codex` subprocess outliving the loop
        # rather than on anything this function does. Measured without the
        # guard: four candidate rows started four readings.
        annotations = [_annotation(f"s-{n}") for n in range(4)]
        rows = [_row(f"s-{n}", "working") for n in range(4)]
        self.harness.lane.consider(self.harness.state, rows, annotations, now=5_000.0)
        moved = [_row(f"s-{n}", "idle") for n in range(4)]
        self.harness.lane.consider(self.harness.state, moved, annotations, now=5_000.0)

        self.assertEqual(1, len(self.harness.readings))

    def test_a_collection_with_no_candidate_reads_the_store_not_at_all(self) -> None:
        # `_claim` used to load the store per row. On a board where most rows
        # are not candidates that is a file read per row per collection, and
        # nothing else in the suite would have noticed.
        reads = 0
        real_load = departures.load

        def counted(config: Any) -> Any:
            nonlocal reads
            reads += 1
            return real_load(config)

        with mock.patch.object(departures, "load", counted):
            rows = [_row(f"s-{n}", "working") for n in range(20)]
            self.harness.lane.consider(self.harness.state, rows, [], now=5_000.0)
            moved = [_row(f"s-{n}", "idle") for n in range(20)]
            self.harness.lane.consider(self.harness.state, moved, [], now=5_000.0)

        self.assertEqual(0, reads)

    def test_candidates_that_all_fail_to_claim_still_read_the_store_once(self) -> None:
        # The case the cached read exists for, and the only one that reaches it:
        # the per-collection guard is set by a SUCCESSFUL claim, so a board
        # whose candidates are all held off by a cap walks the whole list. Once
        # per row would be a file read per annotated session per collection.
        reads = 0
        real_load = departures.load

        def counted(config: Any) -> Any:
            nonlocal reads
            reads += 1
            return real_load(config)

        spent: list[departures.Check] = [
            {
                "harness": "claude",
                "sid": f"s-{n}",
                "at": 4_000.0,
                "constraint": "Goal",
                "clause": "G",
                "reading": "went elsewhere",
                "evidence": "e1",
                "revision": 4,
                "cutoff": 900.0,
                "cutoff_text": "",
                "withdrawn": False,
            }
            for n in range(20)
            for _ in range(self.harness.config.unasked_session_cap)
        ]
        departures.record(self.harness.config, spent, diagnostic_sink=lambda _line: None)
        annotations = [_annotation(f"s-{n}") for n in range(20)]
        rows = [_row(f"s-{n}", "working") for n in range(20)]
        self.harness.lane.consider(self.harness.state, rows, annotations, now=5_000.0)
        with mock.patch.object(departures, "load", counted):
            moved = [_row(f"s-{n}", "idle") for n in range(20)]
            self.harness.lane.consider(self.harness.state, moved, annotations, now=5_000.0)

        self.assertEqual([], self.harness.readings, "every candidate was at its cap")
        self.assertEqual(1, reads)

    def test_a_collection_with_candidates_reads_the_store_once(self) -> None:
        reads = 0
        real_load = departures.load

        def counted(config: Any) -> Any:
            nonlocal reads
            reads += 1
            return real_load(config)

        # The worker is collected rather than run, so the only reads counted are
        # the ones `consider` itself makes. The worker's own read is the
        # store's read-modify-write and is not this test's subject.
        self.harness.lane.spawn = lambda _work: None
        annotations = [_annotation(f"s-{n}") for n in range(20)]
        rows = [_row(f"s-{n}", "working") for n in range(20)]
        self.harness.lane.consider(self.harness.state, rows, annotations, now=5_000.0)
        with mock.patch.object(departures, "load", counted):
            moved = [_row(f"s-{n}", "idle") for n in range(20)]
            self.harness.lane.consider(self.harness.state, moved, annotations, now=5_000.0)

        self.assertEqual(1, reads)


class ADiscardRecordIsNotSomethingToCheckTest(unittest.TestCase):
    """DRC-4565. The free composition, proved rather than reasoned.

    decisions.md says `has_typed_words` already routes this lane correctly for
    an entry with no revisions, so a discard record needs no gate of its own.
    The lane's own `not entry.get("revisions")` continue is what does it, and
    a test is what stops a later reader "tidying" that into an
    entry-existence check -- which is the exact defect DRC-4560 shipped one
    layer over.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    RECORD: ClassVar[Any] = {
        "harness": "claude",
        "sid": "s-1",
        "revisions": (),
        "discarded": 4_000.0,
    }

    def test_no_reading_is_started_against_a_discard_record(self) -> None:
        harness = _Harness(_config(self.root), _assessment("departure"))

        # A state change, which is the transition the lane reads on. Without
        # it nothing runs for any entry and the assertion below is vacuous.
        harness.lane.consider(harness.state, [_row(state="working")], [self.RECORD], now=5_000.0)
        harness.lane.consider(harness.state, [_row(state="idle")], [self.RECORD], now=5_000.0)

        self.assertEqual([], harness.readings)

    def test_the_same_transition_with_words_does_start_one(self) -> None:
        """The positive control. Without it the assertion above is true of any
        lane that never runs at all."""
        harness = _Harness(_config(self.root), _assessment("departure"))

        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertEqual(["s-1"], harness.readings)


class OnlyDeparturesAreRaisedTest(unittest.TestCase):
    """AC4. An unasked reassurance is the output the evidence floor called most
    damaging, and it has no value to someone away from the desk."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _run(self, assessment: reading.Assessment | None) -> _Harness:
        harness = _Harness(_config(self.root), assessment)
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])
        return harness

    def test_a_consistent_reading_raises_nothing(self) -> None:
        harness = self._run(_assessment(reading.RESULT_CONSISTENT))

        self.assertEqual(["s-1"], harness.readings, "the reading still ran")
        self.assertEqual([], harness.popups)
        self.assertEqual([], departures.published(departures.load(harness.config), "claude", "s-1"))

    def test_a_reading_that_raises_nothing_is_still_recorded_as_a_check(self) -> None:
        # It spent a `codex` subprocess, which is what the caps bound, and it
        # is the only evidence that THIS session was looked at.
        harness = self._run(_assessment(reading.RESULT_CONSISTENT))

        stored = departures.load(harness.config)
        self.assertEqual(1, len(stored))
        self.assertEqual("", stored[0]["constraint"])
        # The words are still typed here: the lane just read them.
        self.assertIs(True, departures.checked(stored, "claude", "s-1", has_words=True))

    def test_an_unverifiable_reading_raises_nothing(self) -> None:
        harness = self._run(_assessment(reading.RESULT_UNVERIFIABLE))

        self.assertEqual([], harness.popups)
        self.assertEqual([], departures.published(departures.load(harness.config), "claude", "s-1"))

    def test_a_withheld_reading_records_no_check_because_it_spent_nothing(self) -> None:
        # `produce` refuses before the subprocess, so counting this against the
        # reader's cap would charge them for a spend that did not happen.
        harness = self._run(None)

        self.assertEqual([], harness.popups)
        self.assertEqual((), departures.load(harness.config))

    def test_a_departure_is_raised_and_named_apart_from_a_question(self) -> None:
        harness = self._run(_assessment(reading.RESULT_DEPARTURE))

        self.assertEqual(1, len(harness.popups))
        title = harness.popups[0][0]
        self.assertIn("may be going off track", title)
        self.assertNotIn("waiting on you", title)
        self.assertNotIn("is asking you", title)

    def test_a_mixed_reading_raises_only_its_departures(self) -> None:
        harness = self._run(_assessment(reading.RESULT_CONSISTENT, reading.RESULT_DEPARTURE))

        stored = departures.load(harness.config)
        self.assertEqual(1, len(stored))
        self.assertEqual("c1", stored[0]["constraint"])

    def test_two_departures_in_one_reading_are_one_banner(self) -> None:
        # One reading is one thing that happened. Two banners about it would
        # read as two events.
        harness = self._run(_assessment(reading.RESULT_DEPARTURE, reading.RESULT_DEPARTURE))

        self.assertEqual(2, len(departures.load(harness.config)))
        self.assertEqual(1, len(harness.popups))
        self.assertIn("2 constraints departed", harness.popups[0][1])

    def test_the_raise_records_its_delivery_outcome(self) -> None:
        # The record DRC-4540 built. A departure that never left the machine
        # must not read as one the reader ignored.
        from compass_runtime import deliveries  # noqa: PLC0415

        harness = self._run(_assessment(reading.RESULT_DEPARTURE))

        rows = deliveries.load(harness.config)
        self.assertEqual(1, len(rows))
        self.assertEqual("departure", rows[0]["lane"])


class TheRaiseCarriesItsOwnBaselineTest(unittest.TestCase):
    """AC3. By the time this is read the annotation may be at a later revision
    and the evidence window has moved."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.harness = _Harness(
            _config(Path(self.temp.name)), _assessment(reading.RESULT_DEPARTURE)
        )
        self.harness.consider([_row(state="working")])
        self.harness.consider([_row(state="idle")])

    def test_the_revision_and_cutoff_are_stored_with_the_raise(self) -> None:
        stored = departures.load(self.harness.config)

        self.assertEqual(4, stored[0]["revision"])
        # The moment the reading ran. `Assessment.cutoff` is prose for the page,
        # so the earlier code parsed it as a float and stored 0 on every real
        # reading, which is the amendment's cutoff never being recorded at all.
        self.assertEqual(5_000.0, stored[0]["cutoff"])

    def test_the_producers_own_account_of_what_it_read_is_kept_verbatim(self) -> None:
        # A reading resting entirely on the session's own account is a different
        # thing from one a person's words corroborate, and only this sentence
        # says which.
        stored = departures.load(self.harness.config)

        self.assertEqual("12 entries read, 3 by you and 9 by the agent.", stored[0]["cutoff_text"])

    def test_a_later_revision_does_not_rewrite_what_was_raised(self) -> None:
        # The store holds the baseline, not a pointer to one, so a save after
        # the raise cannot change what the raise said it read.
        before = departures.load(self.harness.config)[0]["revision"]

        self.harness.lane.consider(
            self.harness.state,
            [_row(state="working")],
            [
                {
                    "harness": "claude",
                    "sid": "s-1",
                    "revisions": (
                        {"n": 4, "goal": "Ship the cockpit", "lines": (), "at": 10.0},
                        {"n": 9, "goal": "Something else entirely", "lines": (), "at": 20.0},
                    ),
                }
            ],
            now=5_000.0,
        )

        self.assertEqual(before, departures.load(self.harness.config)[0]["revision"])

    def test_a_reading_whose_account_is_empty_stores_an_empty_account(self) -> None:
        assessment = _assessment(reading.RESULT_DEPARTURE)
        assessment["cutoff"] = ""
        harness = _Harness(_config(Path(self.temp.name) / "other"), assessment)
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        stored = departures.load(harness.config)[0]
        self.assertEqual("", stored["cutoff_text"])
        self.assertEqual(5_000.0, stored["cutoff"], "the moment is still recorded")

    def test_the_cutoff_is_the_same_clock_as_the_moment_the_check_ran(self) -> None:
        """The premise `departures.follow_up` may not compare, bound here.

        Both write sites record `cutoff = now`, so it is an upper bound on the
        evidence and not a second, comparable number. `follow_up` once tested
        one row's cutoff against another's and reported that the later check had
        "read evidence from after this raise"; that test was `at > at` written
        twice, and its own fixture built a row with `at` 2000 and `cutoff` 900,
        which neither of these two sites can produce. If a real evidence bound
        is ever recorded, this assertion is the one that must be changed first.
        """
        raised = departures.load(self.harness.config)[0]
        quiet = _Harness(
            _config(Path(self.temp.name) / "quiet"), _assessment(reading.RESULT_CONSISTENT)
        )
        quiet.consider([_row(state="working")])
        quiet.consider([_row(state="idle")])
        check = departures.load(quiet.config)[0]

        self.assertEqual(raised["at"], raised["cutoff"])
        self.assertEqual("", check["constraint"], "the row for a check that raised nothing")
        self.assertEqual(check["at"], check["cutoff"])


class ExhaustedNeverReadsLikeQuietTest(unittest.TestCase):
    """AC5. The reader is by construction not present, so "nothing departed" and
    "nothing was checked" must never render alike.

    `checked` is read from the store PER SESSION. It used to be board-wide, so
    every row said "Compass has checked this session and found nothing to
    raise" on the strength of the switch being on, including sessions with no
    annotation that the lane never touches.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name), unasked_session_cap=2, unasked_daily_cap=3)

    def _store(self, count: int, *, sid: str = "s-1", constraint: str = "Goal") -> None:
        rows: list[departures.Check] = [
            {
                "harness": "claude",
                "sid": sid,
                "at": 4_000.0 + n,
                "constraint": f"{constraint}{n}" if constraint else "",
                "clause": "G",
                "reading": "went elsewhere" if constraint else "",
                "evidence": "e1" if constraint else "",
                "revision": 4,
                "cutoff": 4_000.0 + n,
                "cutoff_text": "",
                "withdrawn": False,
            }
            for n in range(count)
        ]
        departures.record(self.config, rows, diagnostic_sink=lambda _line: None)

    def _why(self, sid: str = "s-1", *, entries: Any = None) -> str:
        stored = departures.load(self.config)
        # A real annotation with words in it, because the sentence is about
        # what a check could have read and every one of these cases is a
        # session that HAS typed words (DRC-4560).
        published = unasked.published(
            self.config,
            stored,
            _row(sid),
            entries=(_annotation(sid),) if entries is None else entries,
            now=5_000.0,
        )
        return str(published["departure_why"])

    def test_a_session_nobody_checked_says_so(self) -> None:
        self.assertEqual(departures.NEVER_CHECKED, self._why())
        self.assertIn("has not checked", self._why())

    def test_a_session_the_lane_never_reached_does_not_claim_it_was_checked(self) -> None:
        # The board has run checks, on another session. This one must not
        # borrow them: the reader was not there to know which they are reading.
        self._store(1, sid="other", constraint="")

        self.assertEqual(departures.NEVER_CHECKED, self._why("s-1"))

    def test_a_checked_session_with_nothing_found_says_so_and_not_the_same_thing(self) -> None:
        self._store(1, constraint="")

        self.assertEqual(departures.NOTHING_DEPARTED, self._why())
        self.assertNotEqual(departures.NEVER_CHECKED, departures.NOTHING_DEPARTED)

    def test_a_spent_session_cap_says_a_limit_was_spent(self) -> None:
        self._store(2, constraint="")

        why = self._why()

        self.assertEqual(departures.SESSION_EXHAUSTED, why)
        self.assertIn("not a session found to be on track", why)

    def test_a_spent_day_cap_says_so_apart_from_the_session_cap(self) -> None:
        # Three checks across three sessions: no session is at its cap and the
        # board is at its daily one, which is the case a single number hides.
        # `s-1` has one of them, so it has been checked and is not the
        # never-checked case.
        for n in range(2):
            self._store(1, sid=f"other-{n}", constraint="")
        self._store(1, constraint="")

        why = self._why()

        self.assertEqual(departures.DAY_EXHAUSTED, why)
        self.assertNotEqual(departures.SESSION_EXHAUSTED, departures.DAY_EXHAUSTED)

    def test_never_checked_outranks_a_spent_day_cap(self) -> None:
        # A session nobody looked at is not a session held off by a cap. The
        # second implies something was checked here and nothing was.
        for n in range(3):
            self._store(1, sid=f"other-{n}", constraint="")

        self.assertEqual(departures.NEVER_CHECKED, self._why("s-1"))

    def test_a_departure_leaves_the_sentence_to_the_rows(self) -> None:
        self._store(1)

        stored = departures.load(self.config)
        published = unasked.published(
            self.config, stored, _row(), entries=(_annotation(),), now=5_000.0
        )

        self.assertEqual("", published["departure_why"])
        self.assertEqual(1, len(published["departures"]))

    def test_a_row_says_whether_this_session_was_ever_checked(self) -> None:
        """DRC-4514, walked on the board. Zero was standing in for unmeasured.

        `departures` is `[]` on a session the lane has never read and on one it
        read and found nothing in, so a length is not a measurement. The review
        section printed "Departures the checks run while you were away raised
        0" four lines under "Compass has not checked this session against what
        you asked for". A figure nobody measured has to say so, which is the
        shared contract's first rule and the rule the lane-off case already
        obeys.
        """
        self._store(1, sid="other", constraint="")

        stored = departures.load(self.config)
        unread = unasked.published(
            self.config, stored, _row("s-1"), entries=(_annotation("s-1"),), now=5_000.0
        )

        self.assertIs(False, unread["departure_checked"])
        self.assertEqual([], unread["departures"])

    def test_a_checked_session_that_raised_nothing_says_it_was_checked(self) -> None:
        # The case where zero IS a measurement, and the one the row above must
        # be distinguishable from.
        self._store(1, constraint="")

        stored = departures.load(self.config)
        published = unasked.published(
            self.config, stored, _row(), entries=(_annotation(),), now=5_000.0
        )

        self.assertIs(True, published["departure_checked"])
        self.assertEqual([], published["departures"])

    def test_a_check_whose_words_are_gone_does_not_claim_it_read_them(self) -> None:
        """DRC-4560. The state the blank-save path leaves behind.

        The lane never checks a wordless session, so this is only reachable
        after the fact: the check is recorded, the reader empties the box and
        saves, and the entry stands with a revision holding two empty strings.
        Neither the sentence nor the figure may go on claiming a reading of
        words that are not there.
        """
        self._store(1, constraint="")
        blank: Any = {
            "harness": "claude",
            "sid": "s-1",
            "revisions": ({"n": 5, "goal": "", "lines": (), "at": 20.0},),
        }

        stored = departures.load(self.config)
        published = unasked.published(self.config, stored, _row(), entries=(blank,), now=5_000.0)

        self.assertEqual(departures.NEVER_CHECKED, published["departure_why"])
        self.assertIs(False, published["departure_checked"])

    def test_the_rows_and_the_never_checked_sentence_never_go_out_together(self) -> None:
        """DRC-4560, from the other side, on one payload.

        This is the reachable state the walk measured, not a constructed one:
        the reader empties the box, saves, and the raises made against the
        earlier revisions stay standing because only a whole-annotation discard
        withdraws them. `published` goes on serving every one of those rows, so
        a sentence saying nothing was ever read here would print directly under
        the quotations of what was read.
        """
        self._store(1)
        blank: Any = {
            "harness": "claude",
            "sid": "s-1",
            "revisions": ({"n": 5, "goal": "", "lines": (), "at": 20.0},),
        }

        stored = departures.load(self.config)
        published = unasked.published(self.config, stored, _row(), entries=(blank,), now=5_000.0)

        self.assertEqual(1, len(published["departures"]))
        self.assertEqual("", published["departure_why"])
        # The figure is still not a measurement of what the reader asks for
        # now, which is the half the words test was added for.
        self.assertIs(False, published["departure_checked"])

    def test_a_session_with_no_annotation_at_all_is_the_same_answer(self) -> None:
        """The other route to it: the annotation store evicted or lost."""
        self._store(1, constraint="")

        stored = departures.load(self.config)
        published = unasked.published(self.config, stored, _row(), entries=(), now=5_000.0)

        self.assertEqual(departures.NEVER_CHECKED, published["departure_why"])
        self.assertIs(False, published["departure_checked"])

    def test_the_four_sentences_are_four_sentences(self) -> None:
        every = {
            departures.NEVER_CHECKED,
            departures.NOTHING_DEPARTED,
            departures.SESSION_EXHAUSTED,
            departures.DAY_EXHAUSTED,
        }

        self.assertEqual(4, len(every))

    def test_no_sentence_claims_the_session_is_on_track(self) -> None:
        for sentence in (
            departures.NEVER_CHECKED,
            departures.NOTHING_DEPARTED,
            departures.SESSION_EXHAUSTED,
            departures.DAY_EXHAUSTED,
        ):
            with self.subTest(sentence=sentence[:40]):
                lowered = sentence.lower()
                self.assertNotIn("is on track", lowered)
                for claim in ("is fine", "no problem", "as you asked"):
                    self.assertNotIn(claim, lowered)


class TheCapsStopTheReadingRatherThanTheRaiseTest(unittest.TestCase):
    """A cap that let the subprocess run and dropped the result would have spent
    the reader's capacity to produce nothing, which is the failure
    `reading.produce` refuses one layer down."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _harness(self, **changes: Any) -> _Harness:
        return _Harness(_config(self.root, **changes), _assessment(reading.RESULT_DEPARTURE))

    def test_a_session_at_its_cap_starts_no_reading(self) -> None:
        harness = self._harness(unasked_session_cap=1, unasked_session_floor_sec=0.0)
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertEqual(["s-1"], harness.readings)

    def test_the_board_at_its_day_cap_starts_no_reading_on_any_session(self) -> None:
        harness = self._harness(unasked_daily_cap=1, unasked_session_floor_sec=0.0)
        harness.consider([_row("s-1", "working")])
        harness.consider([_row("s-1", "idle")])
        harness.lane.consider(
            harness.state, [_row("s-2", "working")], [_annotation("s-2")], now=5_000.0
        )
        harness.lane.consider(
            harness.state, [_row("s-2", "idle")], [_annotation("s-2")], now=5_000.0
        )

        self.assertEqual(["s-1"], harness.readings)

    def test_the_per_session_floor_holds_a_second_reading_off(self) -> None:
        # A session can cross a state boundary repeatedly inside a minute, and
        # the cap is not a rate limit.
        harness = self._harness()
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertEqual(["s-1"], harness.readings)

    def test_the_floor_opens_again_once_it_has_passed(self) -> None:
        harness = self._harness()
        harness.consider([_row(state="working")], now=5_000.0)
        harness.consider([_row(state="idle")], now=5_000.0)
        harness.consider([_row(state="working")], now=99_000.0)
        harness.consider([_row(state="idle")], now=99_000.0)

        self.assertEqual(["s-1", "s-1"], harness.readings)

    def test_a_reading_in_flight_blocks_the_next(self) -> None:
        # Counted, not inspected. Asserting on the in-flight SET passed with the
        # check removed, because a second claim re-adds the same key and the set
        # reads identically either way.
        harness = self._harness()
        spawned: list[Any] = []
        harness.lane.spawn = spawned.append  # never runs, so the slot stays held
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertEqual(1, len(spawned))
        self.assertEqual({"claude:s-1"}, harness.state.unasked_inflight)

    def test_a_reading_still_in_flight_blocks_the_next_collection(self) -> None:
        # One reading at a TIME, which is the rule the per-collection guard does
        # not give. A different session in a LATER collection is the only shape
        # that isolates it: the same session would be held by its own floor, and
        # the same collection by the guard.
        harness = self._harness()
        spawned: list[Any] = []
        harness.lane.spawn = spawned.append  # never runs, so the slot stays held
        both = [_annotation("s-1"), _annotation("s-2")]
        harness.lane.consider(
            harness.state, [_row("s-1", "working"), _row("s-2", "working")], both, now=5_000.0
        )
        harness.lane.consider(harness.state, [_row("s-1", "idle")], both, now=5_000.0)
        self.assertEqual(1, len(spawned), "the first collection started one")

        harness.lane.consider(harness.state, [_row("s-2", "idle")], both, now=5_000.0)

        self.assertEqual(1, len(spawned))
        self.assertEqual({"claude:s-1"}, harness.state.unasked_inflight)

    def test_the_slot_is_released_once_the_reading_finishes(self) -> None:
        # Held, not leaked. A slot never released would silence the lane for the
        # life of the process, which reads exactly like a board with nothing to
        # raise.
        harness = self._harness()
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertEqual(set(), harness.state.unasked_inflight)

    def test_a_reading_that_raises_still_releases_the_slot(self) -> None:
        harness = self._harness()
        harness.lane.produce = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom"))
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertEqual(set(), harness.state.unasked_inflight)


class TheDepartureStoreSurvivesConcurrentWritersTest(unittest.TestCase):
    """The lesson `deliveries` had to be measured into, applied here from the
    first commit rather than after the same loss."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))

    def _write(self, n: int) -> None:
        departures.record(
            self.config,
            [
                {
                    "harness": "claude",
                    "sid": f"s-{n}",
                    "at": 100.0 + n,
                    "constraint": "Goal",
                    "clause": "G",
                    "reading": "went elsewhere",
                    "evidence": "e1",
                    "revision": 4,
                    "cutoff": 900.0,
                    "cutoff_text": "",
                    "withdrawn": False,
                }
            ],
            diagnostic_sink=lambda _line: None,
        )

    def test_two_simultaneous_writers_both_land(self) -> None:
        ready = threading.Barrier(2)

        def write(n: int) -> None:
            ready.wait()
            self._write(n)

        threads = [threading.Thread(target=write, args=(n,)) for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(2, len(departures.load(self.config)))

    def test_a_reading_lands_whole_or_not_at_all(self) -> None:
        # One reading's departures are one raise. Splitting them would let a
        # restart between two writes publish half a raise.
        rows: list[departures.Check] = [
            {
                "harness": "claude",
                "sid": "s-1",
                "at": 100.0 + n,
                "constraint": f"c{n}",
                "clause": "G",
                "reading": "went elsewhere",
                "evidence": "e1",
                "revision": 4,
                "cutoff": 900.0,
                "cutoff_text": "",
                "withdrawn": False,
            }
            for n in range(3)
        ]

        departures.record(self.config, rows, diagnostic_sink=lambda _line: None)

        self.assertEqual(3, len(departures.load(self.config)))

    def test_a_corrupt_store_is_no_records_rather_than_a_raise(self) -> None:
        import os  # noqa: PLC0415

        os.makedirs(self.config.state_home, mode=0o700, exist_ok=True)
        with open(departures.store_path(self.config), "w", encoding="utf-8") as handle:
            handle.write("{not json")

        self.assertEqual((), departures.load(self.config))


class TheCapsBoundSpendAndNotFindingsTest(unittest.TestCase):
    """The defect the caps shipped with: they counted raises.

    A healthy board raises nothing, so nothing ever advanced the count and the
    lane ran forever. Reproduced on that version at 480 `codex` subprocesses in
    a simulated day against a documented daily cap of 12.
    """

    def setUp(self) -> None:
        _installed_providers(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _flip(self, harness: _Harness, sid: str, *, at: float) -> None:
        entries = [_annotation(sid)]
        harness.lane.consider(harness.state, [_row(sid, "working")], entries, now=at)
        harness.lane.consider(harness.state, [_row(sid, "idle")], entries, now=at)

    def test_a_healthy_session_still_reaches_its_cap(self) -> None:
        # Every reading returns `consistent`, so nothing is ever raised. The
        # cap must still stop the spend.
        harness = _Harness(
            _config(self.root, unasked_session_cap=3, unasked_session_floor_sec=0.0),
            _assessment(reading.RESULT_CONSISTENT),
        )

        for n in range(20):
            self._flip(harness, "s-1", at=5_000.0 + n)

        self.assertEqual(3, len(harness.readings))
        self.assertEqual([], departures.published(departures.load(harness.config), "claude", "s-1"))

    def test_a_healthy_board_still_reaches_its_day_cap(self) -> None:
        harness = _Harness(
            _config(self.root, unasked_daily_cap=4, unasked_session_floor_sec=0.0),
            _assessment(reading.RESULT_CONSISTENT),
        )

        for n in range(20):
            self._flip(harness, f"s-{n}", at=5_000.0 + n)

        self.assertEqual(4, len(harness.readings))

    def test_the_day_cap_is_a_rolling_window_and_not_a_permanent_stop(self) -> None:
        harness = _Harness(
            _config(self.root, unasked_daily_cap=2, unasked_session_floor_sec=0.0),
            _assessment(reading.RESULT_CONSISTENT),
        )
        for n in range(6):
            self._flip(harness, f"s-{n}", at=5_000.0 + n)
        self.assertEqual(2, len(harness.readings))

        # A day later the window has moved past them.
        self._flip(harness, "s-9", at=5_000.0 + unasked.DAY_SEC + 10)

        self.assertEqual(3, len(harness.readings))


class ARaiseThatCannotBeRecordedIsNotRaisedTest(unittest.TestCase):
    """A banner saying a departure was found, over a board that has no record of
    one and says nothing departed, is the board contradicting its own alert."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_an_unwritable_store_raises_no_banner(self) -> None:
        # The state home is a file, so `save`'s makedirs fails and nothing
        # reaches disk. Everything else about the lane still runs.
        blocked = self.root / "state"
        blocked.parent.mkdir(parents=True, exist_ok=True)
        blocked.write_text("not a directory", encoding="utf-8")
        harness = _Harness(_config(self.root), _assessment(reading.RESULT_DEPARTURE))

        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertEqual(["s-1"], harness.readings, "the reading ran")
        self.assertEqual([], harness.popups)
        self.assertEqual((), departures.load(harness.config))


class TheSlotsAreGivenBackOnEveryPathTest(unittest.TestCase):
    """A slot never released silences the lane for the life of the process, and
    that reads exactly like a board with nothing to raise."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.harness = _Harness(
            _config(Path(self.temp.name)), _assessment(reading.RESULT_DEPARTURE)
        )

    def test_a_spawn_that_cannot_start_releases_the_slot(self) -> None:
        # The slot is taken before the worker exists. A thread that will not
        # start would otherwise hold it forever.
        def refuse(_work: Any) -> None:
            raise RuntimeError("cannot start a thread")

        self.harness.lane.spawn = refuse
        self.harness.consider([_row(state="working")])
        self.harness.consider([_row(state="idle")])

        self.assertEqual(set(), self.harness.state.unasked_inflight)

    def test_a_spawn_that_cannot_start_does_not_break_the_collection(self) -> None:
        # `consider` runs inside a collection. A raise here would take down
        # every connected dashboard.
        def refuse(_work: Any) -> None:
            raise RuntimeError("cannot start a thread")

        self.harness.lane.spawn = refuse
        self.harness.consider([_row(state="working")])
        self.harness.consider([_row(state="idle")])

    def test_the_producers_own_session_slot_is_taken_and_given_back(self) -> None:
        # Without it, pressing `Ask for a reading` while an unasked one runs
        # starts a second subprocess on one session, which is what that slot
        # exists to refuse.
        taken: list[str] = []
        released: list[str] = []
        with (
            mock.patch.object(reading, "claim", _taking(taken)),
            mock.patch.object(reading, "release", lambda _c, key: released.append(key)),
        ):
            self.harness.consider([_row(state="working")])
            self.harness.consider([_row(state="idle")])

        self.assertEqual(["claude:s-1"], taken)
        self.assertEqual(["claude:s-1"], released)

    def test_a_session_the_reader_is_already_reading_is_left_alone(self) -> None:
        with mock.patch.object(reading, "claim", lambda _c, _key: False):
            self.harness.consider([_row(state="working")])
            self.harness.consider([_row(state="idle")])

        self.assertEqual([], self.harness.readings)
        self.assertEqual(set(), self.harness.state.unasked_inflight, "the board slot came back")


class TheLaneStateIsBoundedTest(unittest.TestCase):
    """Every other per-session cache on `RuntimeState` is bounded, and these
    two are written for every row of every collection."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name), max_cache_entries=8)
        self.harness = _Harness(self.config, _assessment(reading.RESULT_CONSISTENT))

    def test_the_seen_map_does_not_grow_without_bound(self) -> None:
        for n in range(40):
            self.harness.lane.consider(
                self.harness.state, [_row(f"s-{n}", "working")], [], now=5_000.0
            )

        self.assertLessEqual(len(self.harness.state.unasked_seen), 8)


class TheBannerNamesWhatTheBoardNamesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.harness = _Harness(
            _config(Path(self.temp.name)), _assessment(reading.RESULT_DEPARTURE)
        )

    def test_the_registry_label_is_used_and_not_the_collector_key(self) -> None:
        # A row badged Antigravity produced a notification headed
        # `antigravity`, where every other popup on this board says what the
        # board says.
        self.harness.lane.harness_label = lambda key: key.title()
        self.harness.consider([_row(state="working")])
        self.harness.consider([_row(state="idle")])

        self.assertIn("Claude may be going off track", self.harness.popups[0][0])

    def test_the_constraint_survives_a_clipped_body(self) -> None:
        # `notify_mac` keeps the HEAD of the body, so the subject has to come
        # first or a long reading is cut mid-claim under a title saying the
        # session may be going off track.
        assessment = _assessment(reading.RESULT_DEPARTURE)
        assessment["criteria"]["c0"]["detail"] = "x" * 400
        harness = _Harness(_config(Path(self.temp.name) / "other"), assessment)
        harness.consider([_row(state="working")])
        harness.consider([_row(state="idle")])

        self.assertTrue(harness.popups[0][1].startswith("c0: "))


if __name__ == "__main__":
    unittest.main()


class AFailedCallStillSpendsTheCapsTest(unittest.TestCase):
    """A model call that started and failed is charged like any other.

    Before Claude Code could run the lane without a grant, a call could not
    start without a Codex Allow this build does not write, so this was
    unreachable. A signed-out or rate-limited CLI then started again on every
    state change: reproduced at 199 calls with 0 recorded against a session cap
    of 3 and a day cap of 12.
    """

    def setUp(self) -> None:
        _installed_providers(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _failing(self, **changes: Any) -> _Harness:
        harness = _Harness(
            _config(self.root, unasked_session_floor_sec=0.0, **changes),
            None,
        )

        def produce(_config: Any, row: Any, *_args: Any, **_kwargs: Any) -> Any:
            harness.readings.append(str(row.get("sid")))
            return None, reading.WITHHELD_MODEL_FAILED, True

        harness.lane.produce = produce
        return harness

    def _flip(self, harness: _Harness, sid: str, *, at: float) -> None:
        entries = [_annotation(sid)]
        harness.lane.consider(harness.state, [_row(sid, "working")], entries, now=at)
        harness.lane.consider(harness.state, [_row(sid, "idle")], entries, now=at)

    def test_the_session_cap_stops_a_model_that_keeps_failing(self) -> None:
        harness = self._failing(unasked_session_cap=3)
        for n in range(20):
            self._flip(harness, "s-1", at=5_000.0 + n)
        self.assertEqual(3, len(harness.readings))
        stored = departures.load(harness.config)
        self.assertEqual(3, departures.counts(stored, "claude", "s-1", since=0)[0])
        # Charged, and not a check: nothing claims the session was read.
        self.assertFalse(departures.checked(stored, "claude", "s-1", has_words=True))
        self.assertEqual([], harness.popups)

    def test_the_day_cap_stops_a_model_that_keeps_failing(self) -> None:
        harness = self._failing(unasked_daily_cap=4)
        for n in range(20):
            self._flip(harness, f"s-{n}", at=5_000.0 + n)
        self.assertEqual(4, len(harness.readings))

    def test_a_withheld_call_that_spent_nothing_is_still_not_charged(self) -> None:
        # The control: only a spent call is charged.
        harness = self._failing(unasked_session_cap=3)
        harness.lane.produce = lambda *_a, **_k: (None, reading.WITHHELD_MODEL_UNAVAILABLE, False)
        self._flip(harness, "s-1", at=5_000.0)
        self.assertEqual((), departures.load(harness.config))


class TheUnaskedLaneUsesTheSessionProviderTest(unittest.TestCase):
    def test_a_claude_session_uses_its_accepted_producer_through_the_guarded_seam(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            config = _config(Path(home))
            harness = _Harness(config, _assessment(reading.RESULT_CONSISTENT))
            models: list[Any] = []

            def produce(_config: Any, _row: Any, *_args: Any, **kwargs: Any) -> Any:
                models.append(kwargs["model"])
                return harness.assessment, "", True

            harness.lane.produce = produce
            with mock.patch.object(shutil, "which", side_effect=lambda name: f"/bin/{name}"):
                harness.lane.consider(
                    harness.state, [_row(state="working")], [_annotation()], now=5000.0
                )
                harness.lane.consider(
                    harness.state, [_row(state="idle")], [_annotation()], now=5000.0
                )
            self.assertEqual(1, len(models))
            self.assertIsInstance(models[0], reading_policy.GuardedModel)
            self.assertIsInstance(models[0].model, reading.ClaudeReadingModel)

    def test_revoking_cancels_the_running_child_and_keeps_its_result_from_raising(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            harness = _Harness(_config(Path(home)), _assessment(reading.RESULT_DEPARTURE))
            group = mock.Mock()

            def produce(_config: Any, _row: Any, *_args: Any, **kwargs: Any) -> Any:
                kwargs["model"].model.on_spawn(group)
                harness.lane.stop("codex")
                return harness.assessment, "", True

            harness.lane.produce = produce
            harness.consider([_row(state="working")])
            harness.consider([_row(state="idle")])
            group.cancel.assert_called_once_with()
            self.assertEqual([], harness.popups)
            stored = departures.load(harness.config)
            self.assertEqual((1, 1), departures.counts(stored, "claude", "s-1", since=0))
            self.assertFalse(departures.checked(stored, "claude", "s-1", has_words=True))
            self.assertEqual([], departures.published(stored, "claude", "s-1"))

    def test_a_revoke_after_the_reading_returns_still_publishes_nothing(self) -> None:
        # `stop` landing between the model's answer and the write: the write
        # and the cancel test share the lock, so only the spend is kept.
        with tempfile.TemporaryDirectory() as home:
            harness = _Harness(_config(Path(home)), _assessment(reading.RESULT_DEPARTURE))
            departures_of = harness.lane._departures

            def revoked_between(*args: Any) -> Any:
                found = departures_of(*args)
                harness.lane.stop()
                return found

            with mock.patch.object(harness.lane, "_departures", side_effect=revoked_between):
                harness.consider([_row(state="working")])
                harness.consider([_row(state="idle")])
            self.assertEqual([], harness.popups)
            stored = departures.load(harness.config)
            self.assertEqual((1, 1), departures.counts(stored, "claude", "s-1", since=0))
            self.assertEqual([], departures.published(stored, "claude", "s-1"))


class TheUnaskedLaneNeverSendsACheckTest(unittest.TestCase):
    """DEC-23 item 10 as the 2026-10-27 amendment leaves it: the lane sends no tool outcome
    on a route its Allow does not cover, whatever the reader allowed for a press. Here that is
    the Codex fallback, whose Allow covers words; the Claude Code route sends failures only
    (`test_unasked_failures`). Run through the real producer, so the prompt the lane would send
    is the one asserted on."""

    CHECK: ClassVar[dict[str, Any]] = {
        "fact_id": "check-1",
        "type": "tool_report",
        "subject": "check",
        "result": "failed",
        "result_source": "flag",
        "summary": "python3 -m pytest tests/test_retry.py",
        "at": 20.0,
        "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
        "source_session": {"harness": "claude", "sid": "s-1"},
        "branch": {"harness": "claude", "sid": "s-1", "record_id": "call-1"},
    }
    WORDS: ClassVar[dict[str, Any]] = {
        "fact_id": "f1",
        "type": "user_message",
        "summary": "ship the cockpit please",
        "at": 15.0,
        "evidence": {"source": "root transcript", "confidence": "exact"},
        "source_session": {"harness": "claude", "sid": "s-1"},
    }

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_a_reader_who_allowed_tool_output_still_gets_no_check_sent_unasked(self) -> None:
        from compass_runtime import reading_policy  # noqa: PLC0415

        from .reading_pins import named_machine  # noqa: PLC0415

        config = _config(self.root)
        # The words' own Allow at OpenAI as well, which the lane sends under.
        reading_policy.set_consent(
            config, True, now=1_000.0, provider="codex", tool_output="OpenAI", destination="OpenAI"
        )
        prompts: list[str] = []

        def call(_self: Any, prompt: str, **_kw: Any) -> tuple[str, str]:
            prompts.append(prompt)
            return "{}", "ok"

        harness = _Harness(config, None)
        self.enterContext(mock.patch.object(supervise, "_SHUTDOWN", threading.Event()))
        harness.lane.produce = reading.produce
        harness.lane.facts_for = lambda _state, _row, _now: [self.WORDS, self.CHECK]
        with (
            named_machine(),
            mock.patch.object(reading.CodexReadingModel, "__call__", call),
            mock.patch.object(reading.CodexReadingModel, "available", return_value=True),
        ):
            # A change to a running row, which a mid-flight reading may read.
            harness.consider([_row(state="idle")])
            harness.consider([_row(state="working")])
        self.assertEqual(1, len(prompts), "the lane did not read, so this proves nothing")
        self.assertIn("ship the cockpit please", prompts[0])
        self.assertNotIn("pytest", prompts[0])
        self.assertNotIn("tool_report", prompts[0])


class TheGuardedReadingCallersKnowTheClaudeCodeProducerTest(unittest.TestCase):
    """Admitting the unasked lane does not admit an arbitrary new model caller.

    Each additional caller needs its own permission and spend boundary rather
    than inheriting the lane's opt-in by importing the producer.
    """

    SKILL = Path(__file__).resolve().parents[1]
    RUNTIME = SKILL / "compass_runtime"
    # The MCP server and `scripts/` sit outside the runtime package, and a
    # caller there never passes through the route resolver or the gate. The
    # scorer is the one admitted: its `--producer claude` is DRC-4666's
    # qualification, which must drive the producer before the gate can open,
    # and its spend ledger bounds it at the owner's twenty calls. Tests are
    # not callers, so `scripts/tests` is not scanned.
    SCRIPTS = SKILL.parents[2] / "scripts"
    SCORER = "scripts/score_abstention.py"
    # The drift replay check's Analyze tier, authorized by the owner on 2026-10-03 with its own
    # capped ledger; it builds the model through the scorer's verified, pinned CLI.
    REPLAY = "scripts/drift_replay.py"

    def _users(self, name: str) -> set[str]:
        sources = [
            *self.RUNTIME.rglob("*.py"),
            *(p for p in self.SCRIPTS.rglob("*.py") if "tests" not in p.parts),
            *self.SKILL.glob("*.py"),
        ]
        self.assertIn(self.SKILL / "mcp_server.py", sources)
        self.assertTrue(any(path.name == "score_abstention.py" for path in sources))
        return {
            path.relative_to(self.SKILL.parents[2]).as_posix()
            for path in sources
            if name in path.read_text(encoding="utf-8")
        }

    def test_the_reading_route_and_unasked_lane_build_a_claude_code_model(self) -> None:
        self.assertEqual(
            {
                "compass/skills/compass/compass_runtime/reading.py",
                "compass/skills/compass/compass_runtime/http_api.py",
                "compass/skills/compass/compass_runtime/unasked.py",
                self.SCORER,
                self.REPLAY,
            },
            self._users("ClaudeReadingModel"),
        )

    def test_only_the_claude_code_model_calls_the_claude_code_subprocess(self) -> None:
        self.assertEqual(
            {
                "compass/skills/compass/compass_runtime/observer.py",
                "compass/skills/compass/compass_runtime/reading.py",
                # A reader-requested session summary job runs its own multi-part
                # calls through the same exec under its own grant and ledger.
                "compass/skills/compass/compass_runtime/summary_jobs.py",
                # The Live monitor's once-a-minute Haiku check enters `prepare_claude_exec` on its
                # own pinned model, under its own ledger; it builds no Claude reading model.
                "compass/skills/compass/compass_runtime/live_monitor.py",
                # `argv_digest` only: it hands the exec a runner that raises
                # before any process starts.
                self.SCORER,
                # Signature binding calls the scorer's non-spawning argv probe.
                "scripts/analyze_campaign.py",
                # The authorized foreground study wraps the unchanged consent
                # route's executor; it builds no alternate Claude model.
                "scripts/live_analyze_campaign.py",
                # One qualified foreground browser reading, bound to its held
                # live allocation; it constructs no alternate Claude model.
                "scripts/claude_route_verification.py",
            },
            self._users("claude_exec"),
        )


class TheLaneSendsOnlyWhereAPressWouldNotAskAgainTest(unittest.TestCase):
    """Consent F5 (ui5): the lane sends the goal and messages to Codex with
    nobody at the desk, so it consults the same Allow binding a press does,
    before each send. Where a press would ask again, because no Allow is on
    record, it was turned off, or the destination moved since it was given,
    the send is skipped and recorded, and the lane's own caps are unchanged.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def _run(self, environ: dict[str, str], allow: str | None, *, off: bool = False) -> Any:
        from compass_runtime import reading_policy  # noqa: PLC0415

        from .reading_pins import named_machine  # noqa: PLC0415

        config = _config(self.root / str(len(list(self.root.iterdir()))))
        if allow is not None:
            reading_policy.set_consent(
                config, True, now=1_000.0, provider="codex", destination=allow
            )
        if off:
            reading_policy.set_consent(config, False, now=1_000.0)
        sent: list[str] = []
        lines: list[str] = []
        harness = _Harness(config, _assessment(reading.RESULT_CONSISTENT))

        def produce(_config: Any, _row: Any, *_args: Any, **kwargs: Any) -> Any:
            # As the real producer does: the model is the send.
            kwargs["model"]("the prompt", output_cap_bytes=100)
            return (harness.assessment, "", True)

        def call(_self: Any, prompt: str, **_kw: Any) -> tuple[str, str]:
            sent.append(prompt)
            return "{}", "ok"

        self.enterContext(mock.patch.object(supervise, "_SHUTDOWN", threading.Event()))
        harness.lane.produce = produce
        harness.lane.diagnostic_sink = lines.append
        with (
            named_machine(environ),
            mock.patch.object(reading.CodexReadingModel, "__call__", call),
            mock.patch.object(reading.CodexReadingModel, "available", return_value=True),
        ):
            harness.consider([_row(state="working")])
            harness.consider([_row(state="idle")])
        return sent, lines, departures.load(config), harness

    def test_an_allow_for_todays_destination_lets_the_lane_send(self) -> None:
        sent, lines, checks, _harness = self._run({}, "OpenAI")
        self.assertEqual(["the prompt"], sent)
        self.assertEqual([], lines)
        self.assertEqual(1, len(checks))

    def test_where_a_press_would_ask_again_nothing_is_sent_and_the_skip_is_recorded(
        self,
    ) -> None:
        for name, environ, allow, off in (
            ("no Allow at all", {}, None, False),
            ("turned off", {}, "OpenAI", True),
            (
                "moved to a base URL",
                {"OPENAI_BASE_URL": "https://gw.corp.example"},
                "OpenAI",
                False,
            ),
            ("moved from unnamed to named", {}, "", False),
        ):
            with self.subTest(case=name):
                sent, lines, checks, harness = self._run(environ, allow, off=off)
                self.assertEqual([], sent, "the lane sent where a press would ask again")
                self.assertEqual(1, len(lines))
                self.assertIn(unasked.UNCOVERED, lines[0])
                # Nothing was spent, so nothing counts against the caps.
                self.assertEqual((), checks)
                # The slots are given back, so the lane is not wedged.
                self.assertEqual(set(), harness.state.unasked_inflight)

    def test_an_unnamed_allow_covers_an_unnamed_destination_as_a_press_does(self) -> None:
        sent, _lines, _checks, _harness = self._run(
            {"OPENAI_BASE_URL": "https://gw.corp.example"}, ""
        )
        self.assertEqual(["the prompt"], sent)
