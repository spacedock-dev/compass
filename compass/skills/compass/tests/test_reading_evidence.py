"""The record a stored check keeps of what it read, and the gate that holds a level to it.

[The amendment of 2026-11-24](docs/design-reading-a-session.md#amended-2026-11-24-a-stored-check-keeps-the-record-of-what-it-read).
The served tests live in `test_analysis_result.py`; these hold the pure parts to their contract.
"""

from __future__ import annotations

import math
import unittest
from typing import Any

from compass_runtime import levels, reading_evidence

KEY = "git:/work/billing"
ROW = {"harness": "claude", "sid": "s1", "project_key": KEY, "annotation_settled_through": None}
MARK: dict[str, Any] = {"key": KEY, "lineage": "a" * 32, "generation": 3}


def _fact(at: float, *, by: str = "person:me", sid: str = "s1") -> dict[str, Any]:
    return {
        "fact_id": f"u{at}",
        "type": "user_message",
        "by": by,
        "summary": "words that must never be kept",
        "at": at,
        "source_session": {"harness": "claude", "sid": sid},
    }


def _record(**over: Any) -> dict[str, Any]:
    record = reading_evidence.capture(
        ROW, [], {"read_at": 200.0}, floor=100.0, transcript_bytes=4096, mark=MARK
    )
    assert record is not None
    return {**record, **over}


def _entry(record: Any = None, *, read_at: float = 200.0) -> dict[str, Any]:
    entry: dict[str, Any] = {"assessment": {"read_at": read_at}}
    if record is not None:
        entry["reading_evidence"] = record
    return entry


class CaptureTest(unittest.TestCase):
    def test_a_check_with_every_part_keeps_five_word_free_parts(self) -> None:
        facts = [_fact(150.0), _fact(180.0), _fact(250.0), _fact(90.0), _fact(170.0, sid="s2")]
        record = reading_evidence.capture(
            ROW, facts, {"read_at": 200.0}, floor=100.0, transcript_bytes=4096, mark=MARK
        )
        self.assertEqual(
            {
                "v": 1,
                "read_at": 200.0,
                "project": reading_evidence.project_digest(KEY),
                "history": {"lineage": "a" * 32, "generation": 3},
                "transcript_bytes": 4096,
                # The latest of this session's directions after the floor and up to the check.
                "direction_at": 180.0,
            },
            record,
        )
        self.assertNotIn("words", repr(record))
        self.assertNotIn("billing", repr(record))

    def test_a_settled_direction_is_still_recorded_so_an_undone_keep_cannot_hide_it(self) -> None:
        row = {**ROW, "annotation_settled_through": 190.0}
        record = reading_evidence.capture(
            row, [_fact(150.0)], {"read_at": 200.0}, floor=100.0, transcript_bytes=1, mark=MARK
        )
        assert record is not None
        self.assertEqual(150.0, record["direction_at"])

    def test_a_part_it_cannot_capture_stores_no_record_at_all(self) -> None:
        cases: dict[str, dict[str, Any]] = {
            "no mark": {"mark": None},
            "a mark of another key": {"mark": {**MARK, "key": "path:/elsewhere"}},
            "a malformed mark": {"mark": {**MARK, "lineage": "A" * 32}},
            "no transcript": {"transcript_bytes": None},
            "a negative size": {"transcript_bytes": -1},
            "no reading": {"assessment": None},
            "a reading with no time": {"assessment": {"read_at": None}},
        }
        for name, over in cases.items():
            with self.subTest(case=name):
                given: dict[str, Any] = {
                    "assessment": {"read_at": 200.0},
                    "transcript_bytes": 1,
                    "mark": MARK,
                    **over,
                }
                self.assertIsNone(
                    reading_evidence.capture(
                        ROW,
                        [],
                        given["assessment"],
                        floor=100.0,
                        transcript_bytes=given["transcript_bytes"],
                        mark=given["mark"],
                    )
                )


class ValidateTest(unittest.TestCase):
    def test_only_the_closed_shape_reads_back(self) -> None:
        good = _record(direction_at=150.0)
        self.assertEqual(good, reading_evidence.validate(good))
        bad = {
            "an extra key": {**good, "why": "x"},
            "a missing key": {k: v for k, v in good.items() if k != "direction_at"},
            "another version": {**good, "v": 2},
            "a bool version": {**good, "v": True},
            "an uppercase digest": {**good, "project": good["project"].upper()},
            "a short lineage": {**good, "history": {**good["history"], "lineage": "ab"}},
            "an extra history key": {**good, "history": {**good["history"], "key": KEY}},
            "generation zero": {**good, "history": {**good["history"], "generation": 0}},
            "a bool generation": {**good, "history": {**good["history"], "generation": True}},
            "a huge generation": {**good, "history": {**good["history"], "generation": 2**53}},
            "a float size": {**good, "transcript_bytes": 1.0},
            "a bool size": {**good, "transcript_bytes": False},
            "NaN": {**good, "read_at": math.nan},
            "infinity": {**good, "direction_at": math.inf},
            "a zero time": {**good, "read_at": 0},
            "a text time": {**good, "direction_at": "150"},
            "not a dict": "record",
        }
        for name, value in bad.items():
            with self.subTest(case=name):
                self.assertIsNone(reading_evidence.validate(value))


class HeldTest(unittest.TestCase):
    def held(self, entry: Any, *, row: Any = ROW, **over: Any) -> reading_evidence.Held:
        given: dict[str, Any] = {"mark": MARK, "transcript_bytes": 4096, "floor": 100.0, **over}
        return reading_evidence.held(entry, row, **given)

    def test_a_record_that_still_matches_holds(self) -> None:
        self.assertEqual(reading_evidence.Held(True), self.held(_entry(_record())))
        newer = {**MARK, "generation": 9}
        self.assertTrue(self.held(_entry(_record()), mark=newer, transcript_bytes=9999).ok)

    def test_each_part_that_no_longer_matches_names_itself(self) -> None:
        cases: dict[str, tuple[Any, dict[str, Any]]] = {
            reading_evidence.PART_MISSING: (_entry(None), {}),
            reading_evidence.PART_UNREADABLE: (_entry(None) | {"reading_evidence": None}, {}),
            reading_evidence.PART_OTHER_READING: (_entry(_record(), read_at=201.0), {}),
            reading_evidence.PART_DIRECTION: (_entry(_record(direction_at=150.0)), {}),
            reading_evidence.PART_PROJECT: (
                _entry(_record()),
                {"row": {**ROW, "project_key": "x"}},
            ),
            reading_evidence.PART_HISTORY: (
                _entry(_record()),
                {"mark": {**MARK, "lineage": "b" * 32}},
            ),
            reading_evidence.PART_TRANSCRIPT: (_entry(_record()), {"transcript_bytes": 4095}),
        }
        for part, (entry, over) in cases.items():
            with self.subTest(part=part):
                self.assertEqual(reading_evidence.Held(False, part), self.held(entry, **over))

    def test_history_it_cannot_read_now_fails_as_surely_as_history_that_changed(self) -> None:
        for mark in (None, {**MARK, "generation": 2}, {**MARK, "key": "other"}, "mark"):
            with self.subTest(mark=mark):
                self.assertEqual(
                    reading_evidence.PART_HISTORY, self.held(_entry(_record()), mark=mark).part
                )
        for size in (None, True, 4095.0):
            with self.subTest(size=size):
                self.assertEqual(
                    reading_evidence.PART_TRANSCRIPT,
                    self.held(_entry(_record()), transcript_bytes=size).part,
                )

    def test_a_direction_is_open_until_the_current_floor_or_a_keep_passes_it(self) -> None:
        entry = _entry(_record(direction_at=150.0))
        self.assertEqual(reading_evidence.PART_DIRECTION, self.held(entry).part)
        self.assertTrue(self.held(entry, floor=150.0).ok)
        self.assertTrue(self.held(entry, floor=None).ok)
        settled = {**ROW, "annotation_settled_through": 150.0}
        self.assertTrue(self.held(entry, row=settled).ok)
        early = {**ROW, "annotation_settled_through": 149.0}
        self.assertEqual(reading_evidence.PART_DIRECTION, self.held(entry, row=early).part)

    def test_an_open_direction_answers_before_any_other_change(self) -> None:
        entry = _entry(_record(direction_at=150.0))
        self.assertEqual(
            reading_evidence.PART_DIRECTION, self.held(entry, mark=None, transcript_bytes=0).part
        )


class HoldTest(unittest.TestCase):
    ROWS = (
        {"level": levels.NONE_OR_LOW, "reasons": [], "cites": []},
        {"level": levels.HIGH, "reasons": [levels.REASON_FAILED_CHECK], "cites": ["c1"]},
        {"level": levels.NOT_ENOUGH, "reasons": [levels.REASON_GOAL_UNCLEAR], "cites": []},
    )

    def test_every_level_on_track_included_becomes_no_level(self) -> None:
        held = reading_evidence.hold(
            [dict(r) for r in self.ROWS],
            reading_evidence.Held(False, reading_evidence.PART_HISTORY),
        )
        self.assertEqual(
            [
                (levels.NOT_ENOUGH, [levels.REASON_RECORD_CHANGED], [], "history"),
                (levels.NOT_ENOUGH, [levels.REASON_RECORD_CHANGED], [], "history"),
                (levels.NOT_ENOUGH, [levels.REASON_GOAL_UNCLEAR], [], "history"),
            ],
            [(r["level"], r["reasons"], r["cites"], r["evidence"]) for r in held],
        )

    def test_an_open_direction_says_so_in_its_own_sentence(self) -> None:
        (row,) = reading_evidence.hold(
            [dict(self.ROWS[1])], reading_evidence.Held(False, reading_evidence.PART_DIRECTION)
        )
        self.assertEqual([levels.REASON_LATER_DIRECTION], row["reasons"])

    def test_a_record_that_holds_changes_nothing_and_adds_nothing(self) -> None:
        rows = [dict(r) for r in self.ROWS]
        self.assertEqual(list(self.ROWS), reading_evidence.hold(rows, reading_evidence.Held(True)))

    def test_the_new_reason_is_one_the_page_and_terminal_know(self) -> None:
        self.assertIn(levels.REASON_RECORD_CHANGED, levels.REASONS)
