"""DRC-4682's server half: adopting a later direction as an outcome line, and Keep.

DEC-24 item 4 and DEC-16's 2026-09-24 amendment. "Add it to my intent" opens a
later direction's raw text for review and saves it as an outcome line the
server marks as added from that entry; "Keep my intent" settles every
unsettled direction, and over an unsaved draft both adopt the draft in the same
store write. Every text here is placeholder prose, and the one credential shape
is the documented `AKIAIOSFODNN7EXAMPLE`.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.client
import io
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    aggregate,
    history,
    http_api,
    observer,
    project_context,
    reading_policy,
    reading_route,
    records,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import reading as runtime_reading
from compass_runtime import reading_jobs as runtime_reading_jobs
from compass_runtime import sessions as runtime_sessions
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .support import make_runtime, make_server, serve_until_closed
from .test_claude_checks import SHORT, START, Transcript

FIRST = "Add retry with backoff to the webhook handler."
FIRST_AT = START.timestamp() + 5
NOW = START.timestamp() + 3600
# A 300-character, two-line direction: over the 240 a line may hold, so it
# opens for review and can never be saved as it is.
LONG = (
    "Use the placeholder lexer for every token in the fixture. "
    + "x" * 180
    + ("\nThen keep the parser tests exactly as they are today, please.")
)


LATER = "Keep the placeholder parser tests as they are."
LATER_AT = FIRST_AT + 100


def _with_latest() -> dict[str, Any]:
    return _row(instruction={"label": "asked", "text": LATER, "at": LATER_AT})


def _row(**extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict(runtime_sessions.base_session("claude", SHORT, "billing"))
    row.update(
        {
            "project": "billing",
            "state": "working",
            "active": True,
            "last_activity": NOW,
            "first_prompt": FIRST,
            "first_prompt_at": FIRST_AT,
        }
    )
    row.update(extra)
    return row


def _six(config: Any, state: Any, *, now: float = 20.0) -> None:
    annotation_store.annotate(
        config,
        state,
        "claude",
        SHORT,
        goal="Ship the placeholder parser",
        lines=[f"Line {k}" for k in range(1, 7)],
        now=now,
    )


class _Writes:
    """Every `_write` the store makes, counted, so "one write" is measured."""

    def __init__(self) -> None:
        self.count = 0
        self._real = annotation_store._write

    def __call__(self, *args: Any, **kwargs: Any) -> bool:
        self.count += 1
        return self._real(*args, **kwargs)


class GoalEditWindowTest(unittest.TestCase):
    """The owner's ruling of 2026-10-21: editing the goal keeps the reading's start.

    Read from now is the reader's explicit choice, so only `read_from_now`
    reopens the window, as a first save would.
    """

    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(state_home=home, state_dir=Path(home))
        self.opened = FIRST_AT + 5
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            goal="Ship the placeholder parser",
            now=FIRST_AT + 10,
            window_start=self.opened,
        )

    def _published(self) -> Any:
        return annotation_store.published(
            annotation_store.find(annotation_store.load(self.config), "claude", SHORT)
        )

    def _edit(self, now: float, **over: Any) -> str:
        return annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            goal="Ship the placeholder parser and its lexer",
            now=now,
            window_start=now - 5,
            **over,
        )

    def test_a_goal_edit_keeps_the_start_the_first_save_opened(self) -> None:
        self.assertEqual(annotation_store.OUTCOME_STORED, self._edit(FIRST_AT + 200))
        self.assertEqual(self.opened, self._published()["window_start"])
        self._edit(FIRST_AT + 300, lines=["A line"], expected_revision=2)
        self.assertEqual(self.opened, self._published()["window_start"])

    def test_using_a_prompt_as_the_goal_keeps_the_start_too(self) -> None:
        outcome = annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=FIRST_AT + 200,
            expected_revision=1,
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.assertEqual(self.opened, self._published()["window_start"])
        # A lines-only save over the adopted goal does not reopen it at the prompt's time.
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            lines=["A line"],
            expected_revision=2,
            now=FIRST_AT + 300,
        )
        self.assertEqual(self.opened, self._published()["window_start"])

    def test_read_from_now_reopens_a_typed_edit_at_the_latest_message(self) -> None:
        self._edit(FIRST_AT + 200, read_from_now=True)
        self.assertEqual(FIRST_AT + 195, self._published()["window_start"])

    def test_read_from_now_reopens_an_adopted_goal_at_its_source_time(self) -> None:
        annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=FIRST_AT + 200,
            expected_revision=1,
            read_from_now=True,
        )
        self.assertEqual(FIRST_AT, self._published()["window_start"])

    def test_read_from_now_over_unchanged_words_still_moves_the_start(self) -> None:
        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            goal="Ship the placeholder parser",
            now=FIRST_AT + 200,
            window_start=FIRST_AT + 150,
            read_from_now=True,
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.assertEqual(FIRST_AT + 150, self._published()["window_start"])
        self.assertEqual(2, self._published()["revision"])


class GoalAfterLinesWindowTest(unittest.TestCase):
    """A line saved before any goal is not the start of the work the goal names."""

    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(state_home=home, state_dir=Path(home))
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            lines=["A line"],
            now=FIRST_AT + 500,
            window_start=FIRST_AT + 490,
        )

    def _published(self) -> Any:
        return annotation_store.published(
            annotation_store.find(annotation_store.load(self.config), "claude", SHORT)
        )

    def test_adopting_a_prompt_after_a_lines_only_save_opens_at_the_prompt(self) -> None:
        outcome = annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=FIRST_AT + 600,
            expected_revision=1,
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.assertEqual(FIRST_AT, self._published()["window_start"])

    def test_typed_goal_after_a_lines_only_save_opens_at_the_typed_window(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            goal="Ship the placeholder parser",
            now=FIRST_AT + 600,
            window_start=FIRST_AT + 20,
            expected_revision=1,
        )
        self.assertEqual(FIRST_AT + 20, self._published()["window_start"])

    def test_a_second_lines_only_save_still_carries_the_start(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            lines=["A line", "Another"],
            now=FIRST_AT + 700,
            window_start=FIRST_AT + 690,
            expected_revision=1,
        )
        self.assertEqual(FIRST_AT + 490, self._published()["window_start"])


class AddDirectionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(state_home=home, state_dir=Path(home))
        self.writes = _Writes()
        patcher = mock.patch.object(annotation_store, "_write", self.writes)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _entry(self) -> Any:
        return annotation_store.find(annotation_store.load(self.config), "claude", SHORT)

    def _add(self, row: dict[str, Any] | None = None, **over: Any) -> str:
        arguments: dict[str, Any] = {
            "source_id": "fact:0123456789abcdef",
            "text": "Use the placeholder lexer",
            "entry_at": FIRST_AT + 60,
            "expected_revision": 0,
            "now": FIRST_AT + 120,
        }
        arguments.update(over)
        return annotation_store.add_direction(self.config, self.state, row or _row(), **arguments)

    def _adopt(self, now: float, **over: Any) -> str:
        return annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=now,
            **over,
        )

    def _adopting(self, **over: Any) -> str:
        return self._add(
            adopt="first-prompt", expected_prompt=FIRST, expected_prompt_at=FIRST_AT, **over
        )

    def test_over_a_draft_one_write_holds_the_goal_the_line_and_the_settlement(self) -> None:
        self.assertEqual(annotation_store.OUTCOME_STORED, self._adopting())
        self.assertEqual(1, self.writes.count)
        entry = self._entry()
        revision = entry["revisions"][-1]
        self.assertEqual(1, revision["n"])
        self.assertEqual(FIRST, revision["goal"])
        self.assertEqual("first-prompt", revision["goal_source"])
        self.assertEqual(FIRST_AT, revision["goal_source_at"])
        self.assertEqual(
            (
                {
                    "text": "Use the placeholder lexer",
                    "source": "entry",
                    "source_id": "fact:0123456789abcdef",
                },
            ),
            revision["lines"],
        )
        self.assertEqual(
            {"at": FIRST_AT + 120, "through": FIRST_AT + 60, "revision": 1}, entry["settled"]
        )

    def test_a_refused_adoption_writes_nothing_at_all(self) -> None:
        outcome = self._add(
            adopt="first-prompt", expected_prompt="Different words", expected_prompt_at=FIRST_AT
        )
        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        self.assertEqual(0, self.writes.count)
        self.assertIsNone(self._entry())

    def test_an_untrusted_store_is_never_written_over(self) -> None:
        path = Path(annotation_store.store_path(self.config))
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(annotation_store.OUTCOME_UNTRUSTED, self._adopting())
        self.assertEqual(0, self.writes.count)
        self.assertEqual("{not json", path.read_text(encoding="utf-8"))

    def test_a_stale_page_is_refused_by_its_revision(self) -> None:
        _six(self.config, self.state)
        before = self.writes.count
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED, self._add(expected_revision=0, replace=0)
        )
        self.assertEqual(before, self.writes.count)
        self.assertEqual(annotation_store.OUTCOME_REFUSED, self._add(expected_revision=None))

    def test_a_full_list_is_refused_without_an_explicit_replacement(self) -> None:
        _six(self.config, self.state)
        before = self.writes.count
        self.assertEqual(annotation_store.OUTCOME_REFUSED, self._add(expected_revision=1))
        self.assertEqual(before, self.writes.count)
        self.assertEqual(6, len(self._entry()["revisions"][-1]["lines"]))
        for bad in (-1, 6, True, "1"):
            with self.subTest(replace=bad):
                self.assertEqual(
                    annotation_store.OUTCOME_REFUSED, self._add(expected_revision=1, replace=bad)
                )

    def test_replacing_names_one_line_and_every_other_line_keeps_its_source(self) -> None:
        _six(self.config, self.state)
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            self._add(expected_revision=1, replace=2, source_id="fact:aaaa"),
        )
        # A typed goal is floored at its own save, which the add did not
        # move, so a direction given before the add is still later.
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            self._add(
                expected_revision=2,
                replace=4,
                source_id="fact:bbbb",
                text="Second",
                entry_at=FIRST_AT + 90,
                now=FIRST_AT + 140,
            ),
        )
        lines = self._entry()["revisions"][-1]["lines"]
        self.assertEqual(6, len(lines))
        self.assertEqual(
            ["Line 1", "Line 2", "Use the placeholder lexer", "Line 4", "Second", "Line 6"],
            [line["text"] for line in lines],
        )
        self.assertEqual(
            {"text": "Use the placeholder lexer", "source": "entry", "source_id": "fact:aaaa"},
            lines[2],
        )
        self.assertEqual("typed", lines[0]["source"])

    def test_a_direction_already_saved_as_a_line_is_refused_a_second_place(self) -> None:
        # Update intent instead could offer it again (page F1); two lines from one entry would
        # write a typed line away for a copy of one already kept.
        _six(self.config, self.state)
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            self._add(expected_revision=1, replace=1, source_id="fact:aaaa"),
        )
        before = self.writes.count
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            self._add(expected_revision=2, replace=2, source_id="fact:aaaa"),
        )
        self.assertEqual(before, self.writes.count)
        lines = self._entry()["revisions"][-1]["lines"]
        self.assertEqual("Line 3", lines[2]["text"])
        # Replacing the very line that holds it leaves one line from that entry, and stands.
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            self._add(expected_revision=2, replace=1, source_id="fact:aaaa", text="Reworded"),
        )
        self.assertEqual(
            ["fact:aaaa"],
            [
                line.get("source_id")
                for line in self._entry()["revisions"][-1]["lines"]
                if line.get("source_id")
            ],
        )

    def test_a_long_or_multi_line_direction_is_refused_never_clipped(self) -> None:
        self.assertEqual(annotation_store.OUTCOME_REFUSED, self._adopting(text=LONG))
        self.assertEqual(0, self.writes.count)
        self.assertEqual(annotation_store.OUTCOME_REFUSED, self._adopting(text="   "))
        # Within 240 once collapsed, a pasted line break is one space, as a
        # typed line's is, and nothing is summarised.
        self.assertEqual(
            annotation_store.OUTCOME_STORED, self._adopting(text="First half\nsecond half")
        )
        self.assertEqual(
            "First half second half", self._entry()["revisions"][-1]["lines"][0]["text"]
        )

    def test_a_direction_that_is_not_later_than_the_words_is_refused(self) -> None:
        for at in (FIRST_AT, FIRST_AT - 1, None, True, FIRST_AT + 999_999):
            with self.subTest(at=at):
                self.assertEqual(annotation_store.OUTCOME_REFUSED, self._adopting(entry_at=at))
        self.assertEqual(0, self.writes.count)

    def test_the_settlement_never_moves_back_over_one_already_given(self) -> None:
        annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=FIRST_AT + 10,
        )
        annotation_store.settle(
            self.config, self.state, "claude", SHORT, through=FIRST_AT + 90, now=FIRST_AT + 100
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, self._add(expected_revision=1))
        settled = self._entry()["settled"]
        self.assertEqual(FIRST_AT + 90, settled["through"])
        self.assertEqual(2, settled["revision"])

    def test_adopted_words_keep_their_floor_so_a_later_direction_stays_open(self) -> None:
        annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=FIRST_AT + 10,
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, self._add(expected_revision=1))
        published = annotation_store.published(self._entry())
        self.assertEqual(FIRST_AT, published["goal_source_at"])
        self.assertEqual(FIRST_AT + 60, published["settled_through"])
        self.assertEqual("entry", published["line_1_source"])
        self.assertEqual("fact:0123456789abcdef", published["line_1_source_id"])

    def test_adding_one_direction_to_a_typed_goal_keeps_a_later_one_open(self) -> None:
        # Store review F1: the typed goal's floor is its own save, so adding
        # the earlier direction d1 leaves d2 later and unsettled.
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="My typed goal", now=FIRST_AT + 10
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, self._add(expected_revision=1))
        entry = self._entry()
        published = annotation_store.published(entry)
        self.assertEqual(FIRST_AT + 10, published["goal_saved_at"])
        self.assertEqual(FIRST_AT + 10, annotation_store.direction_floor(entry, _row()))
        self.assertEqual(FIRST_AT + 60, published["settled_through"])
        self.assertLess(published["settled_through"], FIRST_AT + 90)

    def test_only_a_change_to_the_goals_words_moves_its_save_time(self) -> None:
        def save(now: float, **fields: Any) -> Any:
            annotation_store.annotate(self.config, self.state, "claude", SHORT, now=now, **fields)
            return annotation_store.published(self._entry())["goal_saved_at"]

        self.assertEqual(FIRST_AT + 10, save(FIRST_AT + 10, goal="My typed goal"))
        self.assertEqual(FIRST_AT + 10, save(FIRST_AT + 20, lines=["A line"], expected_revision=1))
        self.assertEqual(
            FIRST_AT + 10,
            save(FIRST_AT + 30, goal="My typed goal", lines=["A line", "B"], expected_revision=2),
        )
        self.assertEqual(FIRST_AT + 40, save(FIRST_AT + 40, goal="Retyped goal"))
        self._adopt(FIRST_AT + 50, expected_revision=4)
        self.assertIsNone(annotation_store.published(self._entry())["goal_saved_at"])
        self.assertIsNone(annotation_store.published(None)["goal_saved_at"])

    def test_a_goal_save_time_after_its_own_save_refuses_the_entry(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="My typed goal", now=FIRST_AT + 10
        )
        path = Path(annotation_store.store_path(self.config))
        value = json.loads(path.read_text(encoding="utf-8"))
        value["entries"][0]["revisions"][0]["goal_saved_at"] = FIRST_AT + 99
        path.write_text(json.dumps(value), encoding="utf-8")
        self.assertIsNone(self._entry())

    def test_a_backward_clock_step_never_writes_a_save_time_after_its_revision(self) -> None:
        # Verifier V-1: the carried save time is clamped to the new save, so a
        # 1 ms step back leaves the entry readable and later saves working.
        annotate = annotation_store.annotate
        annotate(self.config, self.state, "claude", SHORT, goal="My typed goal", now=FIRST_AT + 100)
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotate(
                self.config,
                self.state,
                "claude",
                SHORT,
                lines=["A line"],
                expected_revision=1,
                now=FIRST_AT + 99.999,
            ),
        )
        self.assertIsNotNone(self._entry())
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            # An add cannot bind the clamp itself (its direction must be later
            # than the floor and not in the future), so it runs over the entry
            # the skewed save left, and the re-save below steps back again.
            self._add(expected_revision=2, entry_at=FIRST_AT + 100.2, now=FIRST_AT + 100.5),
        )
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotate(
                self.config,
                self.state,
                "claude",
                SHORT,
                goal="My typed goal",
                lines=["A line", "Use the placeholder lexer", "B"],
                expected_revision=3,
                now=FIRST_AT + 99.9,
            ),
        )
        entry = self._entry()
        self.assertIsNotNone(entry)
        latest = entry["revisions"][-1]
        self.assertLessEqual(latest["goal_saved_at"], latest["at"])
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.settle(
                self.config, self.state, "claude", SHORT, through=FIRST_AT, now=FIRST_AT + 101
            ),
        )

    # The store lens's killing tests (M9, M10, M11, M13, M14, M22).
    def test_a_direction_between_the_prompt_and_the_adoption_is_later(self) -> None:
        self._adopt(FIRST_AT + 100)
        self.assertEqual(annotation_store.OUTCOME_STORED, self._add(expected_revision=1))

    def test_a_lines_only_save_does_not_move_the_floor(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            lines=["A typed line"],
            expected_revision=0,
            now=FIRST_AT + 100,
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, self._add(expected_revision=1))

    def test_with_no_goal_the_first_prompt_floors_before_the_latest(self) -> None:
        self.assertEqual(annotation_store.OUTCOME_STORED, self._add(_with_latest()))

    def test_adopting_the_latest_prompt_floors_at_its_time(self) -> None:
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            self._add(
                _with_latest(),
                adopt="latest-prompt",
                expected_prompt=LATER,
                expected_prompt_at=LATER_AT,
            ),
        )
        self.assertIsNone(self._entry())

    def test_an_add_that_adopts_never_replaces_saved_words(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="My typed goal", now=FIRST_AT + 20
        )
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            self._add(
                expected_revision=1,
                adopt="first-prompt",
                expected_prompt=FIRST,
                expected_prompt_at=FIRST_AT,
            ),
        )
        self.assertEqual("My typed goal", self._entry()["revisions"][-1]["goal"])

    def test_an_add_without_a_revision_is_refused_on_a_list_with_room(self) -> None:
        self._adopt(FIRST_AT + 10)
        self.assertEqual(annotation_store.OUTCOME_REFUSED, self._add(expected_revision=None))
        self.assertEqual((), self._entry()["revisions"][-1]["lines"])


class AdoptionReceiptStoreTest(unittest.TestCase):
    """A receipt names the saved revision, never the client's revision guess."""

    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(state_home=home, state_dir=Path(home))

    def _adopt(self, receipt: dict[str, int], **over: Any) -> str:
        return annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=NOW,
            receipt=receipt,
            **over,
        )

    def test_stored_and_stale_repeat_receipts_name_actual_saved_revision(self) -> None:
        receipt = {"saved_revision": 999}
        self.assertEqual("stored", self._adopt(receipt, expected_revision=0))
        self.assertEqual({"saved_revision": 1}, receipt)
        self.assertEqual("unchanged", self._adopt(receipt, expected_revision=0))
        self.assertEqual({"saved_revision": 1}, receipt)

    def test_rebirth_and_settlement_receipts_do_not_guess_an_increment(self) -> None:
        for n in range(3):
            annotation_store.annotate(
                self.config,
                self.state,
                "claude",
                SHORT,
                goal=f"Synthetic goal {n}",
                now=NOW + n,
            )
        self.assertEqual("stored", annotation_store.clear(self.config, self.state, "claude", SHORT))
        receipt: dict[str, int] = {}
        self.assertEqual("stored", self._adopt(receipt, expected_revision=0))
        self.assertEqual({"saved_revision": 4}, receipt)
        self.assertEqual(
            "stored",
            self._adopt(
                receipt,
                expected_revision=4,
                settle_through=FIRST_AT + 60,
            ),
        )
        self.assertEqual({"saved_revision": 4}, receipt)

    def test_refused_unwritten_disabled_and_invalid_source_clear_receipts(self) -> None:
        self.assertEqual("stored", self._adopt({}, expected_revision=0))
        receipt = {"saved_revision": 999}
        self.assertEqual(
            "refused", self._adopt(receipt, expected_revision=8, settle_through=FIRST_AT + 60)
        )
        self.assertEqual({}, receipt)
        for over in ({"expected_text": "Other words"}, {"source": "unknown"}):
            with self.subTest(over=over):
                receipt["saved_revision"] = 999
                arguments: dict[str, Any] = {
                    "source": "first-prompt",
                    "expected_text": FIRST,
                    "expected_at": FIRST_AT,
                    "now": NOW,
                }
                arguments.update(over)
                self.assertEqual(
                    "refused",
                    annotation_store.adopt(
                        self.config,
                        self.state,
                        _row(),
                        receipt=receipt,
                        **arguments,
                    ),
                )
                self.assertEqual({}, receipt)
        with mock.patch.object(annotation_store, "save", return_value=False):
            receipt["saved_revision"] = 999
            self.assertEqual(
                annotation_store.OUTCOME_UNWRITABLE,
                self._adopt(
                    receipt,
                    expected_revision=1,
                    settle_through=FIRST_AT + 60,
                ),
            )
            self.assertEqual({}, receipt)
        receipt["saved_revision"] = 999
        self.config = dataclasses.replace(self.config, annotations_enabled=False)
        self.assertEqual("refused", self._adopt(receipt))
        self.assertEqual({}, receipt)


class KeepStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(state_home=home, state_dir=Path(home))

    def _adopt(self, now: float, **over: Any) -> str:
        return annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=now,
            **over,
        )

    def _settled(self) -> Any:
        return annotation_store.load(self.config)[0].get("settled")

    # The store lens's killing test (M5).
    def test_keep_over_a_draft_clamps_a_future_settlement_to_now(self) -> None:
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            self._adopt(FIRST_AT + 200, settle_through=FIRST_AT + 10_000_000, expected_revision=0),
        )
        self.assertEqual(FIRST_AT + 200, self._settled()["through"])

    def test_a_keep_never_moves_a_settlement_back(self) -> None:
        # D-2: a stale tab's Keep through an older moment reopens nothing.
        self._adopt(FIRST_AT + 10)
        annotation_store.settle(
            self.config, self.state, "claude", SHORT, through=FIRST_AT + 90, now=FIRST_AT + 100
        )
        annotation_store.settle(
            self.config, self.state, "claude", SHORT, through=FIRST_AT + 60, now=FIRST_AT + 110
        )
        self.assertEqual(FIRST_AT + 90, self._settled()["through"])

    def test_a_settlement_is_never_a_non_finite_moment(self) -> None:
        # Verifier: one NaN made every later payload invalid JSON.
        self._adopt(FIRST_AT + 10)
        for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
            with self.subTest(through=bad):
                self.assertEqual(
                    annotation_store.OUTCOME_REFUSED,
                    annotation_store.settle(
                        self.config, self.state, "claude", SHORT, through=bad, now=FIRST_AT + 20
                    ),
                )
                self.assertEqual(
                    annotation_store.OUTCOME_REFUSED,
                    self._adopt(FIRST_AT + 20, settle_through=bad, expected_revision=1),
                )
        self.assertIsNone(self._settled())

    def test_a_keep_from_a_stale_revision_settles_nothing(self) -> None:
        # D-3: checked under the store lock on both Keep writes.
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, lines=["A line"], now=FIRST_AT + 10
        )
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            self._adopt(FIRST_AT + 200, settle_through=FIRST_AT + 150, expected_revision=0),
        )
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            annotation_store.settle(
                self.config,
                self.state,
                "claude",
                SHORT,
                through=FIRST_AT + 150,
                now=FIRST_AT + 200,
                expected_revision=0,
            ),
        )
        self.assertIsNone(self._settled())
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            self._adopt(FIRST_AT + 200, settle_through=FIRST_AT + 150, expected_revision=1),
        )

    def test_keep_never_adopts_over_a_different_saved_goal(self) -> None:
        # D-4: "Keep my intent" must not write the prompt over the reader's words.
        annotation_store.annotate(
            self.config, self.state, "claude", SHORT, goal="My own typed goal", now=FIRST_AT + 10
        )
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            self._adopt(FIRST_AT + 200, settle_through=FIRST_AT + 150, expected_revision=1),
        )
        entry = annotation_store.load(self.config)[0]
        self.assertEqual("My own typed goal", entry["revisions"][-1]["goal"])
        self.assertNotIn("settled", entry)

    def test_keep_over_a_draft_adopts_and_settles_in_one_write(self) -> None:
        writes = _Writes()
        with mock.patch.object(annotation_store, "_write", writes):
            outcome = annotation_store.adopt(
                self.config,
                self.state,
                _row(),
                source="first-prompt",
                expected_text=FIRST,
                expected_at=FIRST_AT,
                now=FIRST_AT + 200,
                settle_through=FIRST_AT + 150,
                expected_revision=0,
            )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        self.assertEqual(1, writes.count)
        entry = annotation_store.load(self.config)[0]
        self.assertEqual(FIRST, entry["revisions"][-1]["goal"])
        self.assertEqual(
            {"at": FIRST_AT + 200, "through": FIRST_AT + 150, "revision": 1}, entry["settled"]
        )

    def test_a_refused_keep_settles_nothing(self) -> None:
        outcome = annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            source="first-prompt",
            expected_text="Other words",
            expected_at=FIRST_AT,
            now=FIRST_AT + 200,
            settle_through=FIRST_AT + 150,
            expected_revision=0,
        )
        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        self.assertEqual((), annotation_store.load(self.config))
        for bad in (True, "soon", float("nan")):
            with self.subTest(through=bad):
                self.assertEqual(
                    annotation_store.OUTCOME_REFUSED,
                    annotation_store.adopt(
                        self.config,
                        self.state,
                        _row(),
                        source="first-prompt",
                        expected_text=FIRST,
                        expected_at=FIRST_AT,
                        now=FIRST_AT + 200,
                        settle_through=bad,
                        expected_revision=0,
                    ),
                )

    def test_keep_over_words_already_adopted_still_settles(self) -> None:
        arguments: dict[str, Any] = {
            "source": "first-prompt",
            "expected_text": FIRST,
            "expected_at": FIRST_AT,
        }
        annotation_store.adopt(self.config, self.state, _row(), now=FIRST_AT + 10, **arguments)
        outcome = annotation_store.adopt(
            self.config,
            self.state,
            _row(),
            now=FIRST_AT + 200,
            expected_revision=1,
            settle_through=FIRST_AT + 150,
            **arguments,
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        entry = annotation_store.load(self.config)[0]
        self.assertEqual(1, len(entry["revisions"]))
        self.assertEqual(FIRST_AT + 150, entry["settled"]["through"])


class DirectionReviewTest(unittest.TestCase):
    def test_the_review_text_is_whole_one_line_redacted_and_says_whether_it_fits(self) -> None:
        text, clipped, fits = annotation_store.direction_review(LONG, 240)
        self.assertEqual(" ".join(LONG.split()), text)
        self.assertGreater(len(text), 240)
        self.assertFalse(clipped)
        self.assertFalse(fits)
        text, clipped, fits = annotation_store.direction_review(
            "Rotate AKIAIOSFODNN7EXAMPLE\nthen stop", 240
        )
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", text)
        self.assertNotIn("\n", text)
        self.assertEqual((False, True), (clipped, fits))
        huge = "word " * 2000
        text, clipped, fits = annotation_store.direction_review(huge, 240)
        self.assertLessEqual(len(text), annotation_store.DIRECTION_TEXT_CAP_CHARS)
        self.assertEqual((True, False), (clipped, fits))

    def test_raw_text_that_reaches_the_cap_is_clipped(self) -> None:
        # The record reader already cut the message at the same 2,000 characters
        # (`records.EXTRACT_TEXT_CAP_CHARS`), so the review never sees the overflow.
        cap = annotation_store.DIRECTION_TEXT_CAP_CHARS
        reached = ("Keep the lanes. " * cap)[:cap]
        _text, clipped, fits = annotation_store.direction_review(reached, 240)
        self.assertEqual((True, False), (clipped, fits))
        _text, clipped, _fits = annotation_store.direction_review(reached[:-1], 240)
        self.assertFalse(clipped)

    # The store lens's killing test (M27).
    def test_the_review_collapses_whitespace_runs(self) -> None:
        text, clipped, fits = annotation_store.direction_review("one\n\n   two\tthree", 240)
        self.assertEqual(("one two three", False, True), (text, clipped, fits))


class DirectionReviewMaskingTest(unittest.TestCase):
    """S-1: past the first sentence, each shapeless form is masked as a check line's is."""

    SECRET = "PLACEHOLDERpw9"  # noqa: S105 - a placeholder, never a credential

    def _review(self, form: str) -> str:
        text, _clipped, _fits = annotation_store.direction_review(
            f"Credential case is next. Then run {form} and carry on.", 240
        )
        self.assertTrue(text.startswith("Credential case is next."))
        return text

    def test_each_named_form_is_masked_after_the_first_sentence(self) -> None:
        forms = {
            "NAME=value": f"PGPASSWORD={self.SECRET}",
            "--password value": f"--password {self.SECRET}",
            "--password=value": f"--password={self.SECRET}",
            "--token value": f"--token {self.SECRET}",
            "-pvalue": f"-p{self.SECRET}",
            "Authorization header": f"Authorization: Bearer {self.SECRET}",
            "X-Api-Key header": f"X-Api-Key: {self.SECRET}",
            "user:pw@host": f"deploy:{self.SECRET}@db.example",
            "quoted user:pw@host": f"'deploy:{self.SECRET}@db.example'",
            "quoted with a space": f"'deploy:{self.SECRET} two@db.example'",
        }
        for label, form in forms.items():
            with self.subTest(form=label):
                text = self._review(form)
                self.assertNotIn(self.SECRET, text)
                self.assertNotIn("two@", text)
                self.assertIn(records.SECRET_MARKER, text)

    def test_the_verifiers_edge_forms_are_masked(self) -> None:
        forms = {
            "no space after the colon": f"authorization:Bearer {self.SECRET}",
            "zero-width after a flag": f"--password\u200b {self.SECRET}",
            "soft hyphen after a flag": f"--token\u00ad {self.SECRET}",
            "bell after a NAME": f"-p\u0007 {self.SECRET}",
        }
        for label, form in forms.items():
            with self.subTest(form=label):
                self.assertNotIn(self.SECRET, self._review(form))

    def test_joiners_in_words_and_emoji_come_back_byte_identical(self) -> None:
        # U+200D joins a family emoji and U+200C spells Persian, Urdu and
        # Kurdish words; neither can hide a flag, so neither is stripped.
        for label, text in {
            "ZWJ emoji": "Ship it \U0001f468\u200d\U0001f469\u200d\U0001f467 today",
            "ZWNJ Persian": "\u0645\u06cc\u200c\u062e\u0648\u0627\u0647\u0645 this",
        }.items():
            with self.subTest(text=label):
                review, clipped, fits = annotation_store.direction_review(text, 240)
                self.assertEqual(text.encode(), review.encode())
                self.assertEqual((False, True), (clipped, fits))
        self.assertNotIn(self.SECRET, self._review(f"--password\u200b {self.SECRET}"))

    def test_a_key_split_by_any_line_separator_is_masked_whole(self) -> None:
        for label, separator in {
            "form feed": "\x0c",
            "vertical tab": "\x0b",
            "NEL": "\x85",
            "line separator": "\u2028",
            "paragraph separator": "\u2029",
        }.items():
            with self.subTest(separator=label):
                text = self._review(f"AKIAIOSFODNN7{separator}EXAMPLE")
                self.assertNotIn("AKIAIOSFODNN7", text)
                self.assertNotIn("EXAMPLE", text)

    def test_a_key_split_by_a_blank_line_is_masked_whole(self) -> None:
        text = self._review("AKIAIOSFODNN7\n\nEXAMPLE")
        self.assertNotIn("AKIAIOSFODNN7", text)
        self.assertNotIn("EXAMPLE", text)

    def test_a_key_split_by_a_line_break_is_masked_whole(self) -> None:
        text = self._review("AKIAIOSFODNN7\nEXAMPLE")
        self.assertNotIn("AKIAIOSFODNN7", text)
        self.assertNotIn("EXAMPLE", text)
        self.assertIn(records.SECRET_MARKER, text)


class _ClaudeSession(unittest.TestCase):
    """A real Claude Code transcript under a store root the resolver globs."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        cwd = self.root / "work" / "billing"
        cwd.mkdir(parents=True)
        self.path = self.root / "claude" / "projects" / "-work-billing" / f"{SHORT}-full.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"claude.projects": str(self.root / "claude" / "projects")},
        )
        self.state = build_runtime_state(self.config, started=NOW)
        patcher = mock.patch.object(observer.CodexGoalModel, "__call__", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session = Transcript(cwd)
        self.session.prompt(FIRST)
        self.session.bash("pytest", "5 passed")
        self.session.prompt(LONG)
        self.session.save(self.path)

    def facts(self) -> list[dict[str, Any]]:
        context = project_context.collect(
            self.config, self.state, [_row()], "billing", now=NOW, focus=("claude", SHORT)
        )
        return list(context["semantic"]["facts"])

    def direction(self) -> dict[str, Any]:
        return next(
            fact
            for fact in self.facts()
            if fact.get("type") == "user_message" and float(fact["at"]) > FIRST_AT
        )


class DirectionReReadTest(_ClaudeSession):
    def test_the_recomputed_fact_id_finds_the_full_text_of_a_claude_message(self) -> None:
        fact = self.direction()
        # The summary is the first sentence clipped; the re-read is the message.
        self.assertLess(len(str(fact["summary"])), len(LONG))
        self.assertEqual(
            LONG,
            project_context.direction_text(
                self.config, self.state, "claude", SHORT, str(fact["fact_id"])
            ).text,
        )

    def test_claude_user_message_ids_still_carry_no_record_id(self) -> None:
        # Claude spells it `uuid`; joining it to the hash would move every
        # stored citation of a Claude user message (the 2026-09-12 precedent).
        fact = self.direction()
        self.assertNotIn("record_id", fact.get("branch") or {})

    def test_an_unknown_id_reads_nothing_and_an_older_message_reaches_its_source(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        self.assertEqual(
            "",
            project_context.direction_text(self.config, self.state, "claude", SHORT, "fact:0").text,
        )
        for _ in range(40):
            self.session.bash("pytest", "p" * 200)
        self.session.save(self.path)
        narrow = dataclasses.replace(self.config, tail_bytes=4096)
        self.assertEqual(
            LONG, project_context.direction_text(narrow, self.state, "claude", SHORT, fact_id).text
        )


class DirectionRouteTest(_ClaudeSession):
    """`POST /api/direction` and the `add_direction` arm over a real socket."""

    def _adoption_payload(self, **over: Any) -> dict[str, Any]:
        return {
            "harness": "claude",
            "sid": SHORT,
            "adopt": "first-prompt",
            "expected_prompt": FIRST,
            "expected_prompt_at": FIRST_AT,
            "expected_revision": 0,
            **over,
        }

    def test_using_a_prompt_as_the_goal_keeps_the_start_unless_read_from_now_is_pressed(
        self,
    ) -> None:
        with self._serving() as port:
            status, body = self._post(
                port,
                "/api/annotate",
                {"harness": "claude", "sid": SHORT, "goal": "Ship the placeholder parser"},
            )
            self.assertEqual((200, "stored"), (status, body["outcome"]))
            opened = annotation_store.load(self.config)[0]["revisions"][-1]["window_start"]
            self.assertGreater(opened, FIRST_AT)
            status, body = self._post(
                port, "/api/annotate", self._adoption_payload(expected_revision=1)
            )
            self.assertEqual((200, "stored"), (status, body["outcome"]))
            revision = annotation_store.load(self.config)[0]["revisions"][-1]
            self.assertEqual(FIRST, revision["goal"])
            self.assertEqual(opened, revision["window_start"])
            status, body = self._post(
                port,
                "/api/annotate",
                self._adoption_payload(expected_revision=2, read_from_now=True),
            )
            self.assertEqual((200, "stored"), (status, body["outcome"]))
            moved = annotation_store.load(self.config)[0]["revisions"][-1]
            self.assertEqual(FIRST_AT, moved["window_start"])

    def test_adoption_receipt_survives_an_actual_post_lock_concurrent_write(self) -> None:
        # The adoption releases the real store lock before the HTTP route rereads
        # current state. Another dashboard's write then advances only `revision`.
        for repeated in (False, True):
            with self.subTest(repeated=repeated):
                self._post_lock_race(repeated)

    def _post_lock_race(self, repeated: bool) -> None:
        if repeated:
            # A fresh source goal replaces the preceding concurrent edit.
            annotation_store.adopt(
                self.config,
                self.state,
                _row(),
                source="first-prompt",
                expected_text=FIRST,
                expected_at=FIRST_AT,
                now=NOW,
                expected_revision=2,
            )
        saved = 3 if repeated else 1
        completed = threading.Event()
        resume = threading.Event()
        answers: list[tuple[int, dict[str, Any]]] = []
        original = annotation_store.adopt

        def pause_after_commit(*args: Any, **kwargs: Any) -> str:
            outcome = original(*args, **kwargs)
            completed.set()
            if not resume.wait(5):
                raise AssertionError("Synthetic concurrent writer did not resume adoption")
            return outcome

        with (
            self._serving() as port,
            mock.patch.object(annotation_store, "adopt", pause_after_commit),
        ):
            caller = threading.Thread(
                target=lambda: answers.append(
                    self._post(
                        port,
                        "/api/annotate",
                        self._adoption_payload(expected_revision=saved if repeated else 0),
                    )
                )
            )
            caller.start()
            try:
                self.assertTrue(completed.wait(5))
                self.assertEqual(
                    "stored",
                    annotation_store.annotate(
                        self.config,
                        self.state,
                        "claude",
                        SHORT,
                        goal=f"Concurrent synthetic goal {saved}",
                        now=NOW + 1,
                    ),
                )
            finally:
                resume.set()
                caller.join(timeout=10)
            self.assertFalse(caller.is_alive())
        status, reply = answers[0]
        self.assertEqual((200, "unchanged" if repeated else "stored"), (status, reply["outcome"]))
        self.assertEqual(saved + 1, reply["revision"])
        self.assertEqual(saved, reply["saved_revision"])
        self.assertEqual(saved + 1, annotation_store.load(self.config)[0]["revisions"][-1]["n"])

    def test_reborn_unchanged_and_refused_socket_receipts_are_server_authored(self) -> None:
        for n in range(3):
            annotation_store.annotate(
                self.config, self.state, "claude", SHORT, goal=f"Synthetic {n}", now=NOW + n
            )
        annotation_store.clear(self.config, self.state, "claude", SHORT)
        with self._serving() as port:
            for expected, outcome, receipt in (
                (0, "stored", 4),
                (0, "unchanged", 4),
                (8, "refused", None),
            ):
                payload = self._adoption_payload(
                    expected_revision=expected,
                    saved_revision=999,
                    receipt={"saved_revision": 999},
                    **({"settle_through": FIRST_AT + 60} if outcome == "refused" else {}),
                )
                status, reply = self._post(port, "/api/annotate", payload)
                self.assertEqual((200, outcome), (status, reply["outcome"]))
                self.assertEqual(receipt, reply["saved_revision"])
                self.assertEqual(4, reply["revision"])
            status, reply = self._post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "goal": "Typed synthetic goal",
                    "saved_revision": 999,
                },
            )
            self.assertEqual(
                (200, "stored", None), (status, reply["outcome"], reply["saved_revision"])
            )
            self.assertNotIn("saved_revision", annotation_store.load(self.config)[0])

    def test_unchanged_receipt_does_not_hide_a_concurrent_checklist_revision(self) -> None:
        with self._serving() as port:
            status, first = self._post(port, "/api/annotate", self._adoption_payload())
            self.assertEqual(
                (200, "stored", 1), (status, first["outcome"], first["saved_revision"])
            )
            status, concurrent = self._post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "lines": ["Concurrent synthetic checklist"],
                    "expected_revision": 1,
                },
            )
            self.assertEqual(
                (200, "stored", 2), (status, concurrent["outcome"], concurrent["revision"])
            )
            # Adoption's exact goal repeat intentionally accepts a stale baseline.
            # This honest receipt must not upgrade a frozen checklist's baseline.
            status, repeat = self._post(
                port, "/api/annotate", self._adoption_payload(expected_revision=1)
            )
            self.assertEqual(
                (200, "unchanged", 2), (status, repeat["outcome"], repeat["saved_revision"])
            )
            status, refused = self._post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "lines": ["Frozen synthetic checklist"],
                    "expected_revision": 1,
                },
            )
            self.assertEqual(
                (200, "refused", None), (status, refused["outcome"], refused["saved_revision"])
            )
        revision = annotation_store.load(self.config)[0]["revisions"][-1]
        self.assertEqual(
            (2, ["Concurrent synthetic checklist"]),
            (
                revision["n"],
                [line["text"] for line in revision["lines"]],
            ),
        )

    def test_non_adoption_socket_arms_have_no_receipt(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", SHORT, goal=FIRST, now=NOW)
        with self._serving() as port:
            for fields in (
                {"add_direction": "fact:unknown", "text": "Synthetic", "expected_revision": 1},
                {"not_accurate": True, "read_at": NOW},
                {"settle_through": FIRST_AT + 60, "expected_revision": 1},
                {"clear": True},
            ):
                with self.subTest(arm=next(iter(fields))):
                    status, reply = self._post(
                        port,
                        "/api/annotate",
                        {
                            "harness": "claude",
                            "sid": SHORT,
                            "saved_revision": 999,
                            "receipt": {"saved_revision": 999},
                            **fields,
                        },
                    )
                    self.assertEqual(200, status)
                    self.assertIsNone(reply["saved_revision"])

    def test_unpersisted_socket_adoption_has_no_receipt(self) -> None:
        with (
            self._serving() as port,
            mock.patch.object(annotation_store, "save", return_value=False),
        ):
            status, reply = self._post(port, "/api/annotate", self._adoption_payload())
        self.assertEqual(
            (200, annotation_store.OUTCOME_UNWRITABLE, False, None),
            (
                status,
                reply["outcome"],
                reply["persisted"],
                reply["saved_revision"],
            ),
        )

    def test_an_unedited_complete_direction_keeps_its_actual_request_time(self) -> None:
        text = "Keep every test."
        self.session.prompt(text)
        self.session.save(self.path)
        source = max(
            (fact for fact in self.facts() if fact.get("type") == "user_message"),
            key=lambda fact: float(fact["at"]),
        )
        with self._serving() as port:
            status, body = self._post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "add_direction": source["fact_id"],
                    "text": text,
                    "expected_revision": 0,
                    "adopt": "first-prompt",
                    "expected_prompt": FIRST,
                    "expected_prompt_at": FIRST_AT,
                },
            )
        self.assertEqual((200, "stored"), (status, body["outcome"]))
        line = annotation_store.load(self.config)[0]["revisions"][-1]["lines"][0]
        self.assertEqual(text, line["text"])
        self.assertEqual(float(source["at"]), line["request"]["at"])

    def _app(self, **row: Any) -> Any:
        def collect(
            config: Any, state: Any, now: float, window_hours: float, show_all: bool
        ) -> list[dict[str, Any]]:
            del config, state, now, window_hours, show_all
            return [_row(**row)]

        spec = aggregate.HarnessSpec(
            key="claude", label="Claude", discover=lambda *_: True, collect=collect
        )
        return aggregate.Application(
            self.config,
            self.state,
            (spec,),
            native_notifier=lambda _p: "",
            popup_notifier=lambda _t, _b: None,
            diagnostic_sink=lambda _m: None,
            clock=lambda: NOW,
        )

    @contextlib.contextmanager
    def _serving(self, application: Any | None = None) -> Any:
        httpd = make_server(application=application or self._app())
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def _post(
        port: int,
        path: str,
        payload: Any,
        *,
        headers: dict[str, str] | None = None,
        declared: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            if declared is None:
                conn.request(
                    "POST",
                    path,
                    body=json.dumps(payload).encode(),
                    headers={"Content-Type": "application/json", **(headers or {})},
                )
            else:
                conn.putrequest("POST", path)
                conn.putheader("Content-Length", declared)
                conn.endheaders()
            response = conn.getresponse()
            body = response.read()
        finally:
            conn.close()
        try:
            return response.status, json.loads(body)
        except ValueError:
            return response.status, {}

    def _open(self, port: int, fact_id: str, **over: Any) -> tuple[int, dict[str, Any]]:
        return self._post(
            port,
            "/api/direction",
            {"harness": "claude", "sid": SHORT, "fact_id": fact_id, **over},
        )

    def test_a_direction_longer_than_compass_opens_answers_clipped(self) -> None:
        # The wire review's live case: 3,663 characters, the last sentence out of reach.
        steps = "".join(f"Step {n}: rename lane {n} and keep its tests green. " for n in range(80))
        final = "FINAL: and then delete the tests folder entirely."
        huge = steps[: 3663 - len(final)] + final
        self.assertEqual(3663, len(huge))
        self.session.prompt(huge)
        self.session.save(self.path)
        fact = max(
            (f for f in self.facts() if f.get("type") == "user_message"),
            key=lambda f: float(f["at"]),
        )
        with self._serving() as port:
            status, body = self._open(port, str(fact["fact_id"]))
        self.assertEqual(200, status)
        self.assertEqual((True, True, False), (body["ok"], body["clipped"], body["fits"]))
        self.assertNotIn("FINAL", body["text"])

    def test_open_returns_the_whole_direction_and_says_it_does_not_fit(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        with self._serving() as port:
            status, body = self._open(port, fact_id)
        self.assertEqual(200, status)
        self.assertEqual(
            {
                "ok": True,
                "fact_id": fact_id,
                "text": " ".join(LONG.split()),
                "clipped": False,
                "fits": False,
                "goal_choice": {
                    "fact_id": fact_id,
                    "at": self.direction()["at"],
                    "text": records.safe_text(LONG, 240).strip(),
                    "cut": True,
                },
            },
            body,
        )

    def test_a_long_direction_on_a_list_of_six_is_never_saved_clipped(self) -> None:
        _six(self.config, self.state)
        fact_id = str(self.direction()["fact_id"])
        add = {
            "harness": "claude",
            "sid": SHORT,
            "add_direction": fact_id,
            "expected_revision": 1,
            "replace": 5,
        }
        with self._serving() as port:
            _, opened = self._open(port, fact_id)
            status, refused = self._post(port, "/api/annotate", {**add, "text": opened["text"]})
            self.assertEqual((200, "refused"), (status, refused["outcome"]))
            edited = "Use the placeholder lexer; keep the parser tests"
            status, stored = self._post(port, "/api/annotate", {**add, "text": edited})
        self.assertEqual("stored", stored["outcome"])
        lines = annotation_store.load(self.config)[0]["revisions"][-1]["lines"]
        self.assertEqual(6, len(lines))
        self.assertEqual(
            {"text": edited, "source": "entry", "source_id": fact_id},
            {key: lines[5][key] for key in ("text", "source", "source_id")},
        )
        self.assertNotIn("request", lines[5])
        self.assertNotIn(opened["text"], json.dumps(annotation_store.load(self.config)))

    def test_a_settled_direction_that_is_not_the_latest_prompt_is_added_from_its_entry(
        self,
    ) -> None:
        # Update intent instead (DRC-4697): after an analysis's Keep settled every direction,
        # the one a departure cites is added from its own entry, with later prompts after it,
        # and the goal is kept.
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            SHORT,
            goal="Ship the placeholder parser",
            lines=["The parser tests pass"],
            now=20.0,
        )
        self.session.prompt("Later still: rename the placeholder lexer.")
        self.session.save(self.path)
        latest = max(
            (f for f in self.facts() if f.get("type") == "user_message"),
            key=lambda f: float(f["at"]),
        )
        annotation_store.settle(
            self.config,
            self.state,
            "claude",
            SHORT,
            through=latest["at"],
            now=NOW,
            expected_revision=1,
        )
        fact_id = str(
            min(
                (
                    f
                    for f in self.facts()
                    if f.get("type") == "user_message" and float(f["at"]) > FIRST_AT
                ),
                key=lambda f: float(f["at"]),
            )["fact_id"]
        )
        self.assertNotEqual(fact_id, latest["fact_id"])
        with self._serving() as port:
            _, opened = self._open(port, fact_id)
            self.assertIs(True, opened["ok"])
            status, stored = self._post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "add_direction": fact_id,
                    "text": "Use the placeholder lexer for every token",
                    "expected_revision": 1,
                },
            )
        self.assertEqual((200, "stored"), (status, stored["outcome"]))
        revision = annotation_store.load(self.config)[0]["revisions"][-1]
        self.assertEqual("Ship the placeholder parser", revision["goal"])
        self.assertEqual(
            {
                "text": "Use the placeholder lexer for every token",
                "source": "entry",
                "source_id": fact_id,
            },
            {key: revision["lines"][1][key] for key in ("text", "source", "source_id")},
        )
        self.assertNotIn("request", revision["lines"][1])

    def test_add_over_the_draft_adopts_it_in_the_same_request(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        with self._serving() as port:
            status, body = self._post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "add_direction": fact_id,
                    "text": "Use the placeholder lexer",
                    "expected_revision": 0,
                    "adopt": "first-prompt",
                    "expected_prompt": FIRST,
                    "expected_prompt_at": FIRST_AT,
                },
            )
        self.assertEqual((200, "stored", 1), (status, body["outcome"], body["revision"]))
        entry = annotation_store.load(self.config)[0]
        self.assertEqual(FIRST, entry["revisions"][-1]["goal"])
        self.assertEqual(self.direction()["at"], entry["settled"]["through"])

    def test_every_unopenable_direction_answers_one_body(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        first_id = next(
            str(f["fact_id"])
            for f in self.facts()
            if f.get("type") == "user_message" and float(f["at"]) == FIRST_AT
        )
        tool_id = next(str(f["fact_id"]) for f in self.facts() if f.get("type") != "user_message")
        with self._serving() as port:
            answers = [
                self._open(port, "fact:0"),
                self._open(port, tool_id),
                self._open(port, first_id),
                self._open(port, fact_id, sid="nobody00"),
                self._open(port, fact_id, harness="codex"),
            ]
        expected = (
            200,
            {
                "ok": False,
                "reason": "not_found",
                "why": "Compass could not find that later direction in the session's current record. Nothing was opened.",
            },
        )
        for answer in answers:
            self.assertEqual(expected, answer)

    def test_a_reader_can_open_a_batch_with_the_single_answer_shapes_in_request_order(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        ids = ["missing", fact_id, fact_id]
        with self._serving() as port:
            single = self._open(port, fact_id)[1]
            with mock.patch.object(
                project_context, "direction_lookups", wraps=project_context.direction_lookups
            ) as scan:
                status, body = self._post(
                    port, "/api/direction", {"harness": "claude", "sid": SHORT, "fact_ids": ids}
                )
        self.assertEqual(200, status)
        self.assertEqual(1, scan.call_count)
        self.assertEqual("not_found", body["results"][0]["reason"])
        self.assertEqual([single, single], body["results"][1:])

    def test_a_reader_cannot_send_an_unbounded_or_mixed_direction_batch(self) -> None:
        cases: tuple[dict[str, Any], ...] = (
            {"fact_ids": []},
            {"fact_ids": ["x"] * 65},
            {"fact_ids": ["x" * 257]},
            {"fact_ids": [1]},
            {"fact_ids": "x"},
            {"fact_ids": ["x"], "fact_id": "x"},
        )
        with self._serving() as port:
            for fields in cases:
                status, _ = self._post(
                    port, "/api/direction", {"harness": "claude", "sid": SHORT, **fields}
                )
                self.assertEqual(400, status)

    def test_a_reader_gets_a_distinct_reason_when_a_later_direction_is_beyond_the_search(
        self,
    ) -> None:
        fact_id = str(self.direction()["fact_id"])
        with (
            self._serving() as port,
            mock.patch.object(
                project_context,
                "direction_lookup",
                return_value=project_context.DirectionLookup(
                    project_context.DirectionText(""), "out_of_reach"
                ),
            ),
        ):
            status, body = self._open(port, fact_id)
        self.assertEqual(200, status)
        self.assertEqual("out_of_reach", body["reason"])
        self.assertIn("search", body["why"])

    def test_a_reader_is_asked_to_press_again_when_the_session_wrote_during_the_lookup(
        self,
    ) -> None:
        fact_id = str(self.direction()["fact_id"])
        with (
            self._serving() as port,
            mock.patch.object(
                project_context,
                "direction_lookup",
                return_value=project_context.DirectionLookup(
                    project_context.DirectionText(""), "changed"
                ),
            ),
        ):
            status, body = self._open(port, fact_id)
        self.assertEqual(200, status)
        self.assertFalse(body["ok"])
        self.assertEqual("changed", body["reason"])
        self.assertIn("Press again", body["why"])

    def test_a_reader_can_open_a_paged_direction_after_it_left_semantic_history(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        with (
            self._serving() as port,
            mock.patch.object(http_api._RequestHandler, "_session_facts", return_value=[]),
        ):
            status, body = self._open(port, fact_id)
        self.assertEqual(200, status)
        self.assertTrue(body["ok"])
        self.assertEqual(LONG.replace("\n", " "), body["text"])

    def test_a_reader_opening_a_verified_native_direction_does_not_repeat_project_collection(
        self,
    ) -> None:
        fact_id = str(self.direction()["fact_id"])
        with (
            self._serving() as port,
            mock.patch.object(
                http_api._RequestHandler, "_session_facts", return_value=[]
            ) as collections,
        ):
            status, body = self._open(port, fact_id)
        self.assertEqual(200, status)
        self.assertTrue(body["ok"])
        self.assertEqual(0, collections.call_count)

    def test_a_reader_gets_not_found_for_a_known_earlier_prompt_even_when_the_search_is_bounded(
        self,
    ) -> None:
        first_id = next(
            str(f["fact_id"])
            for f in self.facts()
            if f.get("type") == "user_message" and f["at"] == FIRST_AT
        )
        narrow = dataclasses.replace(self.config, direction_scan_max_bytes=16)
        with mock.patch.object(self, "config", narrow), self._serving() as port:
            status, body = self._open(port, first_id)
        self.assertEqual(200, status)
        self.assertEqual("not_found", body["reason"])

    def test_a_direction_older_than_the_tail_is_opened_and_added_from_its_source(self) -> None:
        # The fact still resolves (history keeps it) while the tail no longer
        # holds its record, which is exactly when the 112-character summary
        # would be the only text left to save.
        fact_id = str(self.direction()["fact_id"])
        real = project_context.direction_text

        def aged(config: Any, *rest: Any) -> project_context.DirectionText:
            return real(dataclasses.replace(config, tail_bytes=16), *rest)

        with (
            mock.patch.object(project_context, "direction_text", aged),
            self._serving() as port,
        ):
            status, body = self._open(port, fact_id)
            _, added = self._post(
                port,
                "/api/annotate",
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "add_direction": fact_id,
                    "text": "Use the placeholder lexer",
                    "expected_revision": 0,
                    "adopt": "first-prompt",
                    "expected_prompt": FIRST,
                    "expected_prompt_at": FIRST_AT,
                },
            )
        self.assertEqual(200, status)
        self.assertEqual(" ".join(LONG.split()), body["text"])
        self.assertEqual("stored", added["outcome"])
        self.assertEqual(
            "Use the placeholder lexer",
            annotation_store.load(self.config)[0]["revisions"][-1]["lines"][0]["text"],
        )

    def test_the_text_comes_back_redacted(self) -> None:
        self.session.prompt("Rotate AKIAIOSFODNN7EXAMPLE before the release")
        self.session.save(self.path)
        fact = next(
            f
            for f in self.facts()
            if f.get("type") == "user_message" and "before" in str(f["summary"])
        )
        with self._serving() as port:
            _, body = self._open(port, str(fact["fact_id"]))
        self.assertTrue(body["ok"])
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", body["text"])

    def test_the_route_is_guarded_as_the_intent_routes_are(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        body = {"harness": "claude", "sid": SHORT, "fact_id": fact_id}
        cases = (
            ("cross-site origin", {"Origin": "http://evil.example"}, 403),
            ("another local port", {"Origin": "http://127.0.0.1:1"}, 403),
            ("rebound host", {"Host": "evil.example"}, 403),
            ("cross-site fetch", {"Sec-Fetch-Site": "cross-site"}, 403),
            ("same-site fetch", {"Sec-Fetch-Site": "same-site"}, 403),
            (
                "document navigation",
                {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
                403,
            ),
        )
        with self._serving() as port:
            for label, headers, code in cases:
                with self.subTest(shape=label):
                    status, answer = self._post(port, "/api/direction", body, headers=headers)
                    self.assertEqual(code, status)
                    self.assertNotIn("text", answer)
            status, _ = self._post(
                port,
                "/api/direction",
                None,
                declared=str(self.config.annotation_body_cap_bytes + 1),
            )
            self.assertEqual(413, status)
            malformed: list[dict[str, Any]] = [
                {**body, "fact_id": {"x": 1}},
                {**body, "sid": 7},
                {"harness": "claude"},
            ]
            for bad in malformed:
                self.assertEqual(400, self._post(port, "/api/direction", bad)[0])
            for bad in (
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "add_direction": fact_id,
                    "text": ["x"],
                    "expected_revision": 0,
                },
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "add_direction": fact_id,
                    "text": "x",
                    "expected_revision": 0,
                    "replace": True,
                },
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "add_direction": 5,
                    "text": "x",
                    "expected_revision": 0,
                },
                {
                    "harness": "claude",
                    "sid": SHORT,
                    "lines": [{"text": "x", "source": "entry", "source_id": fact_id}],
                },
            ):
                self.assertEqual(400, self._post(port, "/api/annotate", bad)[0])

    def test_the_route_answers_503_with_annotations_off(self) -> None:
        self.config = dataclasses.replace(self.config, annotations_enabled=False)
        with self._serving() as port:
            status, _ = self._open(port, str(self.direction()["fact_id"]))
        self.assertEqual(503, status)

    def test_no_full_prompt_text_reaches_the_payload_or_session_history(self) -> None:
        fact_id = str(self.direction()["fact_id"])
        with self._serving() as port:
            self._open(port, fact_id)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/api/data")
            data = conn.getresponse().read().decode("utf-8")
            conn.close()
        tail = "Then keep the parser tests exactly as they are today"
        self.assertNotIn(tail, data)
        store = Path(history.store_path(self.config))
        self.assertNotIn(tail, store.read_text(encoding="utf-8") if store.exists() else "")
        self.assertFalse(
            [name for name in history.OBSERVATION_FIELDS if "direction" in name],
            "a direction's text became a history field",
        )


class _ReadingRouteHandler(unittest.TestCase):
    """A handler over a real store, whose replies are recorded rather than sent."""

    replies: list[tuple[dict[str, Any], int]]

    def _runtime(self) -> Any:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        return make_runtime(state_home=home, state_dir=Path(home))

    def _handler(self, config: Any, state: Any, payload: dict[str, Any]) -> Any:
        from compass_runtime import cli  # noqa: PLC0415

        app: Any = cli.build_application(config, state, clock=lambda: NOW)
        app.collect_json = lambda **_: (1, json.dumps({"sessions": [_row()]}).encode())
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = SimpleNamespace(application=app, server_port=4580)
        self.replies: list[tuple[dict[str, Any], int]] = []
        handler._send = lambda body, _ctype, code=200, **_k: self.replies.append(
            (json.loads(body), code)
        )
        handler._reject = lambda code, *_a: self.replies.append(({}, code))
        body = json.dumps(payload).encode()
        handler.headers = {"Host": "127.0.0.1:4580", "Content-Length": str(len(body))}
        handler.client_address = ("127.0.0.1", 10000)
        handler.rfile = io.BytesIO(body)
        return handler


class KeepRouteTest(_ReadingRouteHandler):
    """Keep on both routes: settling needs no reader, and a press settles first."""

    KEEP: dict[str, Any] = {  # noqa: RUF012
        "harness": "claude",
        "sid": SHORT,
        "adopt": "first-prompt",
        "expected_prompt": FIRST,
        "expected_prompt_at": FIRST_AT,
        "settle_through": FIRST_AT + 60,
        "expected_revision": 0,
    }

    def test_keep_with_no_reader_settles_on_the_annotate_route(self) -> None:
        config, state = self._runtime()
        handler = self._handler(config, state, dict(self.KEEP))
        handler._annotate()
        answer, code = self.replies[-1]
        self.assertEqual((200, "stored"), (code, answer["outcome"]))
        entry = annotation_store.load(config)[0]
        self.assertEqual(FIRST, entry["revisions"][-1]["goal"])
        self.assertEqual(FIRST_AT + 60, entry["settled"]["through"])

    def _press(self, config: Any, state: Any, **over: Any) -> Any:
        payload = {
            **self.KEEP,
            "press": True,
            "observer_model": 1,
            "provider": "codex",
            "allow": True,
            "words_destination": "",
            **over,
        }
        # `adopt=None` names a Keep over saved words, which sends no adoption.
        payload = {k: v for k, v in payload.items() if not (k == "adopt" and v is None)}
        handler = self._handler(config, state, payload)
        with (
            mock.patch.object(
                shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "codex" else None
            ),
            mock.patch.object(reading_route, "destination", return_value=""),
            mock.patch.object(
                handler, "_compose_reading", return_value=(None, "test", False)
            ) as compose,
        ):
            handler._reading()
        return compose

    def test_the_keep_press_adopts_and_settles_before_the_job(self) -> None:
        config, state = self._runtime()
        compose = self._press(config, state)
        self.assertEqual(1, compose.call_count)
        entry = compose.call_args.args[1]
        self.assertEqual(FIRST, entry["revisions"][-1]["goal"])
        self.assertEqual(FIRST_AT + 60, entry["settled"]["through"])
        answer, code = self.replies[-1]
        self.assertEqual((202, "stored"), (code, answer["settled"]))

    def test_keep_over_a_draft_analyzes_when_a_collection_overwrote_the_cache(self) -> None:
        # The a11y lens's cccc0013/dddd0013 case: a collection that read the store before
        # Keep's write assigns its copy after it, so the cache has no entry for the session.
        config, state = self._runtime()
        payload = {
            **self.KEEP,
            "press": True,
            "observer_model": 1,
            "provider": "codex",
            "allow": True,
            "words_destination": "",
        }
        handler = self._handler(config, state, payload)
        route = handler._reading_route

        def stale_cache(*args: Any, **kwargs: Any) -> Any:
            answer = route(*args, **kwargs)
            state.annotations = ()
            return answer

        handler._reading_route = stale_cache
        with (
            mock.patch.object(
                shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "codex" else None
            ),
            mock.patch.object(reading_route, "destination", return_value=""),
            mock.patch.object(
                handler, "_compose_reading", return_value=(None, "test", False)
            ) as compose,
        ):
            handler._reading()
        answer, code = self.replies[-1]
        self.assertEqual((202, "stored"), (code, answer.get("settled")), answer)
        self.assertEqual(1, compose.call_count)
        self.assertEqual(FIRST, compose.call_args.args[1]["revisions"][-1]["goal"])

    def test_a_press_that_cannot_start_still_leaves_the_settlement(self) -> None:
        config, state = self._runtime()
        compose = self._press(config, state, provider="someone-else")
        self.assertEqual(0, compose.call_count)
        answer, code = self.replies[-1]
        self.assertEqual(
            (409, "provider-changed", "stored"), (code, answer["reason"], answer["settled"])
        )
        self.assertEqual(FIRST_AT + 60, annotation_store.load(config)[0]["settled"]["through"])

    def test_a_refused_keep_starts_nothing_and_settles_nothing(self) -> None:
        config, state = self._runtime()
        compose = self._press(config, state, expected_prompt="Other words")
        self.assertEqual(0, compose.call_count)
        answer, code = self.replies[-1]
        self.assertEqual(
            (422, True, "refused"), (code, answer["adoption_refused"], answer["settled"])
        )
        self.assertEqual((), annotation_store.load(config))

    def test_a_keep_press_must_name_its_revision_and_a_stale_one_settles_nothing(self) -> None:
        # D-3: a stale tab is refused and settles nothing, on the press as on annotate.
        config, state = self._runtime()
        annotation_store.annotate(
            config, state, "claude", SHORT, lines=["A line"], now=FIRST_AT + 10
        )
        for over in ({"expected_revision": None}, {"expected_revision": 0}):
            with self.subTest(**over):
                compose = self._press(config, state, **over)
                self.assertEqual(0, compose.call_count)
                answer, code = self.replies[-1]
                self.assertEqual((422, "refused"), (code, answer["settled"]))
        for keep in (
            {k: v for k, v in self.KEEP.items() if k != "adopt"},
            {**self.KEEP, "expected_revision": 0},
        ):
            handler = self._handler(config, state, keep)
            handler._annotate()
            self.assertEqual("refused", self.replies[-1][0]["outcome"])
        self.assertNotIn("settled", annotation_store.load(config)[0])

    def test_a_non_finite_settle_time_is_refused_on_both_routes(self) -> None:
        config, state = self._runtime()
        annotation_store.annotate(config, state, "claude", SHORT, goal="My goal", now=FIRST_AT)
        for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
            with self.subTest(through=bad):
                plain = {"harness": "claude", "sid": SHORT, "settle_through": bad}
                self._handler(config, state, plain)._annotate()
                self.assertEqual("refused", self.replies[-1][0]["outcome"])
                compose = self._press(
                    config,
                    state,
                    adopt=None,
                    settle_through=bad,
                    expected_revision=1,
                )
                self.assertEqual(0, compose.call_count)
                self.assertEqual(
                    (422, "refused"), (self.replies[-1][1], self.replies[-1][0]["settled"])
                )
        self.assertNotIn("settled", annotation_store.load(config)[0])

    def test_a_press_with_no_thread_to_run_on_still_says_it_settled(self) -> None:
        # D-5: the settlement is on disk, so the 503 says so.
        config, state = self._runtime()
        with mock.patch.object(runtime_reading_jobs, "launch", side_effect=RuntimeError):
            self._press(config, state)
        answer, code = self.replies[-1]
        self.assertEqual((503, "stored"), (code, answer.get("settled")))


class APlainPressNamesItsRevisionTest(_ReadingRouteHandler):
    """DRC-4732: Analyze from a page drawn against an older revision starts nothing.

    Before the route, the permission, any Allow write, the adoption and the job,
    so a stale tab's press neither reads words its reader never saw nor records
    anything. A press that names no revision (an older page) is unchanged.
    """

    def _plain(self, config: Any, state: Any, **over: Any) -> Any:
        payload = {
            "harness": "claude",
            "sid": SHORT,
            "press": True,
            "observer_model": 1,
            "provider": "codex",
            # Where the stubbed route says the words go, as the page sends it.
            **({"words_destination": ""} if over.get("allow") else {}),
            **over,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        handler = self._handler(config, state, payload)
        with (
            mock.patch.object(
                shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "codex" else None
            ),
            mock.patch.object(reading_route, "destination", return_value=""),
            mock.patch.object(
                handler, "_compose_reading", return_value=(None, "test", False)
            ) as compose,
        ):
            handler._reading()
        return compose

    def _saved(self, config: Any, state: Any) -> None:
        annotation_store.annotate(config, state, "claude", SHORT, goal="My goal", now=FIRST_AT)

    def test_a_press_naming_the_current_revision_starts_the_analysis(self) -> None:
        config, state = self._runtime()
        self._saved(config, state)
        compose = self._plain(config, state, allow=True, expected_revision=1)
        self.assertEqual(1, compose.call_count)
        self.assertEqual(202, self.replies[-1][1])

    def test_a_stale_press_starts_nothing_and_records_no_allow(self) -> None:
        config, state = self._runtime()
        self._saved(config, state)
        annotation_store.annotate(config, state, "claude", SHORT, goal="Newer", now=FIRST_AT + 1)
        compose = self._plain(config, state, allow=True, expected_revision=1)
        self.assertEqual(0, compose.call_count)
        answer, code = self.replies[-1]
        self.assertEqual((409, "revision-changed", False), (code, answer["reason"], answer["ok"]))
        self.assertEqual({}, runtime_reading.published_jobs(config))
        self.assertFalse(
            reading_policy.status(config, now=NOW, provider="codex")["providers"]["codex"],
            "a refused press recorded the Allow it carried",
        )

    def test_a_stale_press_over_a_draft_adopts_nothing(self) -> None:
        config, state = self._runtime()
        self._saved(config, state)
        compose = self._plain(
            config,
            state,
            allow=True,
            adopt="first-prompt",
            expected_prompt=FIRST,
            expected_prompt_at=FIRST_AT,
            expected_revision=0,
        )
        self.assertEqual(0, compose.call_count)
        self.assertEqual(409, self.replies[-1][1])
        self.assertEqual("My goal", annotation_store.load(config)[0]["revisions"][-1]["goal"])

    def test_a_press_that_names_no_revision_is_read_as_before(self) -> None:
        config, state = self._runtime()
        self._saved(config, state)
        annotation_store.annotate(config, state, "claude", SHORT, goal="Newer", now=FIRST_AT + 1)
        compose = self._plain(config, state, allow=True)
        self.assertEqual(1, compose.call_count)

    def test_the_published_revision_after_a_discard_starts_the_analysis(self) -> None:
        # Numbering continues past a discard, so the revision is not the count (wire F7, S5).
        config, state = self._runtime()
        self._saved(config, state)
        annotation_store.clear(config, state, "claude", SHORT, now=FIRST_AT + 1)
        annotation_store.annotate(config, state, "claude", SHORT, goal="Again", now=FIRST_AT + 2)
        published = annotation_store.published(annotation_store.load(config)[0])
        self.assertEqual((2, 1), (published["revision"], published["revision_count"]))
        compose = self._plain(config, state, allow=True, expected_revision=2)
        self.assertEqual(1, compose.call_count)
        self.assertEqual(202, self.replies[-1][1])

    def test_the_revision_is_checked_before_the_route(self) -> None:
        # A stale press naming another provider is answered as stale (wire F7, S7).
        config, state = self._runtime()
        self._saved(config, state)
        annotation_store.annotate(config, state, "claude", SHORT, goal="Newer", now=FIRST_AT + 1)
        compose = self._plain(config, state, provider="someone-else", expected_revision=1)
        self.assertEqual(0, compose.call_count)
        answer, code = self.replies[-1]
        self.assertEqual((409, "revision-changed"), (code, answer["reason"]))

    def test_a_save_made_by_another_dashboard_refuses_the_press(self) -> None:
        # Two dashboards on one home: this one's cache still holds revision 1.
        config, state = self._runtime()
        other = build_runtime_state(config, started=NOW)
        self._saved(config, state)
        annotation_store.annotate(config, other, "claude", SHORT, goal="OMEGA", now=FIRST_AT + 1)
        self.assertEqual(1, annotation_store.active(config, state)[0]["revisions"][-1]["n"])
        compose = self._plain(config, state, allow=True, expected_revision=1)
        self.assertEqual(0, compose.call_count)
        self.assertEqual(409, self.replies[-1][1])
        self.assertEqual({}, runtime_reading.published_jobs(config))
        # Refused before the route, so the Allow it carried was not recorded either.
        self.assertFalse(
            reading_policy.status(config, now=NOW, provider="codex")["providers"]["codex"]
        )

    def _between(self, handler: Any, act: Any) -> None:
        """Run `act` after the check and the route, before the entry is composed."""
        route = handler._reading_route

        def raced(*args: Any, **kwargs: Any) -> Any:
            answer = route(*args, **kwargs)
            act()
            return answer

        handler._reading_route = raced

    def _raced_press(self, config: Any, state: Any, act: Any, **over: Any) -> Any:
        payload = {
            "harness": "claude",
            "sid": SHORT,
            "press": True,
            "observer_model": 1,
            "provider": "codex",
            "allow": True,
            "words_destination": "",
            **over,
        }
        handler = self._handler(config, state, payload)
        self._between(handler, act)
        with (
            mock.patch.object(
                shutil, "which", lambda name: f"/usr/local/bin/{name}" if name == "codex" else None
            ),
            mock.patch.object(reading_route, "destination", return_value=""),
            mock.patch.object(
                handler, "_compose_reading", return_value=(None, "test", False)
            ) as compose,
        ):
            handler._reading()
        return compose

    def test_a_save_landing_after_the_check_never_reaches_the_model(self) -> None:
        config, state = self._runtime()
        other = build_runtime_state(config, started=NOW)
        self._saved(config, state)
        compose = self._raced_press(
            config,
            state,
            lambda: annotation_store.annotate(
                config, other, "claude", SHORT, goal="OMEGA", now=FIRST_AT + 1
            ),
            expected_revision=1,
        )
        self.assertEqual(0, compose.call_count)
        answer, code = self.replies[-1]
        self.assertEqual((409, "revision-changed"), (code, answer["reason"]))
        self.assertEqual({}, runtime_reading.published_jobs(config))

    def test_a_save_landing_after_keep_settles_never_reaches_the_model(self) -> None:
        config, state = self._runtime()
        other = build_runtime_state(config, started=NOW)
        self._saved(config, state)
        compose = self._raced_press(
            config,
            state,
            lambda: annotation_store.annotate(
                config, other, "claude", SHORT, goal="OMEGA", now=FIRST_AT + 1
            ),
            settle_through=FIRST_AT + 60,
            expected_revision=1,
        )
        self.assertEqual(0, compose.call_count)
        answer, code = self.replies[-1]
        self.assertEqual(
            (409, "revision-changed", "stored"), (code, answer["reason"], answer["settled"])
        )

    def test_a_revision_that_is_not_a_number_is_refused(self) -> None:
        config, state = self._runtime()
        self._saved(config, state)
        for bad in ("1", True, 1.0):
            with self.subTest(bad=bad):
                compose = self._plain(config, state, allow=True, expected_revision=bad)
                self.assertEqual(0, compose.call_count)
                self.assertEqual(400, self.replies[-1][1])


if __name__ == "__main__":
    unittest.main()
