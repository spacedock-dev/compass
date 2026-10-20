"""A reader's expected outcome, written as a checklist and read one line at a time (DRC-4685).

[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
item 3 turns the single expected output into up to six lines, each at most 240 characters on one
line, each recording its source, each read as its own constraint. Every test here is a sentence
about the person who typed those lines: what they get back, what they are refused and why, and
what never reaches a model they did not ask to run.
"""

from __future__ import annotations

import contextlib
import dataclasses
import http.client
import json
import os
import pathlib
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    cli,
    departures,
    history,
    observer,
    reading,
    reading_route,
    unasked,
)
from compass_runtime import sessions as runtime_sessions
from compass_runtime.config import RuntimeConfig, build_runtime_config
from compass_runtime.state import build_runtime_state

from .reading_pins import cli_on_path, named_machine, refuse_real_models
from .support import make_config, make_runtime, make_server, serve_until_closed
from .support import os_name as support_os_name

if TYPE_CHECKING:
    from collections.abc import Callable

NOW = 1_800_000_000.0
REPO = pathlib.Path(__file__).resolve().parents[4]
SIX = [
    "Failed events retry with backoff",
    "Events that still fail go to a dead-letter table",
    "Tests cover the retry path",
    "Tests cover the failure path",
    "The public API does not change",
    "The logging migration stays out of this branch",
]


def _config(root: Path, **changes: Any) -> RuntimeConfig:
    config = build_runtime_config(
        environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
        platform_name="linux",
        os_name="posix",
        launcher_path=root / "server.py",
    )
    return dataclasses.replace(config, **changes) if changes else config


class _StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = _config(self.root)
        self.state = build_runtime_state(self.config, started=NOW)

    def entry(self, sid: str = "s-1") -> annotation_store.Annotation:
        found = annotation_store.find(annotation_store.load(self.config), "claude", sid)
        assert found is not None
        return found

    def write_raw(self, payload: Any) -> None:
        path = annotation_store.store_path(self.config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)


class SixLinesAreKeptAndShownOneByOneTest(_StoreCase):
    def test_a_reader_who_types_six_lines_gets_six_lines_back_each_marked_typed(self) -> None:
        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", goal="Harden the ingest", lines=SIX, now=NOW
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
        lines = self.entry()["revisions"][-1]["lines"]
        self.assertEqual(SIX, [line["text"] for line in lines])
        self.assertEqual(["typed"] * 6, [line["source"] for line in lines])
        published = annotation_store.published(self.entry())
        self.assertEqual(SIX, [published[f"line_{k}"] for k in range(1, 7)])
        self.assertEqual(["typed"] * 6, [published[f"line_{k}_source"] for k in range(1, 7)])
        self.assertEqual("", published["lines_why"])

    def test_a_240_character_line_is_kept_whole(self) -> None:
        line = "x" * 240

        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=[line], now=NOW)

        self.assertEqual(line, self.entry()["revisions"][-1]["lines"][0]["text"])

    def test_a_session_with_no_lines_says_why_rather_than_rendering_blanks(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="G", now=NOW)

        published = annotation_store.published(self.entry())
        self.assertEqual(annotation_store.NO_LINES_TYPED, published["lines_why"])
        self.assertEqual("", published["line_1"])
        self.assertIsNone(published["line_1_source"])
        self.assertEqual(
            annotation_store.NO_LINES_TYPED, annotation_store.published(None)["lines_why"]
        )

    def test_a_seventh_line_is_refused_and_nothing_is_minted(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=SIX, now=NOW)
        with open(annotation_store.store_path(self.config), "rb") as handle:
            before = handle.read()

        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", lines=[*SIX, "a seventh"], now=NOW + 1
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        with open(annotation_store.store_path(self.config), "rb") as handle:
            self.assertEqual(before, handle.read())
        self.assertEqual(1, self.entry()["revisions"][-1]["n"])

    def test_a_line_over_240_characters_is_refused_rather_than_saved_clipped(self) -> None:
        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", lines=["y" * 241], now=NOW
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        self.assertEqual((), annotation_store.load(self.config))

    def test_a_pasted_line_break_collapses_so_each_line_stays_one_line(self) -> None:
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=["retry with\nbackoff", "no \u202ereordering"],
            now=NOW,
        )

        texts = [line["text"] for line in self.entry()["revisions"][-1]["lines"]]
        self.assertEqual(["retry with backoff", "no  reordering"], texts)

    def test_an_empty_line_is_dropped_rather_than_stored(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", "s-1", lines=["one", "  ", "", "two"], now=NOW
        )

        texts = [line["text"] for line in self.entry()["revisions"][-1]["lines"]]
        self.assertEqual(["one", "two"], texts)

    def test_saving_the_same_list_again_mints_no_revision(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=SIX, now=NOW)

        again = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", lines=list(SIX), now=NOW + 5
        )

        self.assertEqual(annotation_store.OUTCOME_UNCHANGED, again)
        self.assertEqual(1, self.entry()["revisions"][-1]["n"])

    def test_saving_only_the_goal_leaves_the_lines_alone(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=SIX, now=NOW)

        annotation_store.annotate(
            self.config, self.state, "claude", "s-1", goal="new goal", now=NOW + 1
        )

        latest = self.entry()["revisions"][-1]
        self.assertEqual(SIX, [line["text"] for line in latest["lines"]])
        self.assertEqual("new goal", latest["goal"])

    def test_an_empty_list_clears_every_line(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=SIX, now=NOW)

        annotation_store.annotate(
            self.config, self.state, "claude", "s-1", lines=[], expected_revision=1, now=NOW + 1
        )

        self.assertEqual((), self.entry()["revisions"][-1]["lines"])

    def test_a_stale_list_from_a_second_tab_is_refused(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=["a"], now=NOW)
        annotation_store.annotate(
            self.config, self.state, "claude", "s-1", lines=["b"], expected_revision=1, now=NOW + 1
        )

        stale = annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=["a", "c"],
            expected_revision=1,
            now=NOW + 2,
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, stale)
        self.assertEqual(["b"], [line["text"] for line in self.entry()["revisions"][-1]["lines"]])

    def test_a_list_naming_the_current_revision_is_saved(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=["a"], now=NOW)

        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=["a", "c"],
            expected_revision=1,
            now=NOW + 2,
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)


class ALineKeepsItsSourceTest(_StoreCase):
    """Only the server may say a line came from an entry, and an edit makes it typed."""

    def seed_entry_line(self) -> None:
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [
                            {
                                "n": 1,
                                "at": NOW,
                                "goal": "G",
                                "lines": [
                                    {
                                        "text": "from the record",
                                        "source": "entry",
                                        "source_id": "f-9",
                                    },
                                    {"text": "typed one", "source": "typed"},
                                ],
                            }
                        ],
                    }
                ],
            }
        )

    def test_a_line_added_from_an_entry_reads_back_with_its_entry(self) -> None:
        self.seed_entry_line()

        published = annotation_store.published(self.entry())

        self.assertEqual("entry", published["line_1_source"])
        self.assertEqual("f-9", published["line_1_source_id"])
        self.assertEqual("typed", published["line_2_source"])
        self.assertEqual("", published["line_2_source_id"])

    def test_resaving_an_unchanged_entry_line_keeps_its_source(self) -> None:
        self.seed_entry_line()

        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=["from the record", "typed one", "a third"],
            expected_revision=1,
            now=NOW + 1,
        )

        lines = self.entry()["revisions"][-1]["lines"]
        self.assertEqual(
            {"text": "from the record", "source": "entry", "source_id": "f-9"}, lines[0]
        )

    def test_editing_an_entry_line_saves_it_as_typed(self) -> None:
        self.seed_entry_line()

        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=["from the record, edited", "typed one"],
            expected_revision=1,
            now=NOW + 1,
        )

        self.assertEqual(
            {"text": "from the record, edited", "source": "typed"},
            self.entry()["revisions"][-1]["lines"][0],
        )

    def test_a_client_cannot_claim_a_line_came_from_an_entry(self) -> None:
        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=cast("Any", [{"text": "forged", "source": "entry", "source_id": "f-1"}]),
            now=NOW,
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        self.assertEqual((), annotation_store.load(self.config))

    def test_an_unknown_line_source_on_disk_refuses_the_whole_entry(self) -> None:
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [
                            {"n": 1, "at": NOW, "goal": "old", "lines": []},
                            {
                                "n": 2,
                                "at": NOW,
                                "goal": "G",
                                "lines": [{"text": "x", "source": "model"}],
                            },
                        ],
                    }
                ],
            }
        )

        # Dropping only the bad revision would bring back older words the reader replaced.
        self.assertEqual((), annotation_store.load(self.config))

    def test_seven_lines_on_disk_refuse_the_whole_entry(self) -> None:
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [
                            {
                                "n": 1,
                                "at": NOW,
                                "goal": "G",
                                "lines": [{"text": f"l{k}", "source": "typed"} for k in range(7)],
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual((), annotation_store.load(self.config))


class AnOlderStoreStillReadsTest(_StoreCase):
    def test_an_old_single_expected_output_reads_as_one_typed_line(self) -> None:
        self.write_raw(
            {
                "v": 1,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [{"n": 3, "at": NOW, "goal": "G", "output": "a CSV export"}],
                    }
                ],
            }
        )

        latest = self.entry()["revisions"][-1]

        self.assertEqual(({"text": "a CSV export", "source": "typed"},), latest["lines"])
        self.assertEqual("a CSV export", annotation_store.published(self.entry())["line_1"])

    def test_an_old_empty_expected_output_reads_as_no_lines(self) -> None:
        self.write_raw(
            {
                "v": 1,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [{"n": 3, "at": NOW, "goal": "G", "output": ""}],
                    }
                ],
            }
        )

        self.assertEqual((), self.entry()["revisions"][-1]["lines"])

    def test_the_next_save_writes_lines_and_no_output_key(self) -> None:
        self.write_raw(
            {
                "v": 1,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [{"n": 3, "at": NOW, "goal": "G", "output": "a CSV export"}],
                    }
                ],
            }
        )

        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="G2", now=NOW + 1)

        with open(annotation_store.store_path(self.config), encoding="utf-8") as handle:
            written = json.load(handle)
        self.assertEqual(annotation_store.SCHEMA_VERSION, written["v"])
        for revision in written["entries"][0]["revisions"]:
            self.assertNotIn("output", revision)
            self.assertIn("lines", revision)
        self.assertEqual(
            [{"text": "a CSV export", "source": "typed"}],
            written["entries"][0]["revisions"][-1]["lines"],
        )

    def legacy_reading(self, output: dict[str, Any]) -> dict[str, Any]:
        return {
            "revision_read": 3,
            "revision_read_at": NOW,
            "read_at": NOW + 10,
            "stamp": "read at 10:00",
            "cutoff": "Read 1 of the 1 entry after your words.",
            "scope": "mid-flight",
            "scope_text": reading.SCOPE_TEXT["mid-flight"],
            "ended_at_read": None,
            "criteria": {
                "goal": {
                    "result": reading.RESULT_UNVERIFIABLE,
                    "cites": [],
                    "detail": "",
                    "clause": "G",
                    "why": "",
                },
                "output": output,
            },
        }

    def seed_reading(self, output: dict[str, Any]) -> None:
        self.write_raw(
            {
                "v": 1,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [{"n": 3, "at": NOW, "goal": "G", "output": "a CSV export"}],
                        "readings": 1,
                        "assessment": self.legacy_reading(output),
                    }
                ],
            }
        )

    def test_a_reading_stored_before_this_change_still_loads_with_its_outcome_as_line_one(
        self,
    ) -> None:
        self.seed_reading(
            {
                "result": reading.RESULT_DEPARTURE,
                "cites": ["f1"],
                "detail": "no CSV was written",
                "clause": "a CSV export",
                "why": "",
            }
        )

        entry = self.entry()

        self.assertNotIn("refused", entry)
        assessment = entry["assessment"]
        self.assertEqual({"goal", "line_1"}, set(assessment["criteria"]))
        self.assertEqual("a CSV export", assessment["criteria"]["line_1"]["clause"])
        self.assertIsNone(assessment["evidence_through"])

    def test_a_legacy_output_nobody_typed_is_dropped_rather_than_shown_as_a_line(self) -> None:
        # Stored with its reason, and stored before `why` existed, which is the same field with
        # the reason missing.
        for reason in ({"why": reading.WHY_NOT_ASKED}, {}):
            with self.subTest(reason=reason):
                self.seed_reading(
                    {
                        "result": reading.RESULT_UNVERIFIABLE,
                        "cites": [],
                        "detail": "",
                        "clause": "",
                        **reason,
                    }
                )

                self.assertEqual({"goal"}, set(self.entry()["assessment"]["criteria"]))

    def test_a_reading_with_a_gap_in_its_lines_is_refused_whole(self) -> None:
        criterion = {
            "result": reading.RESULT_UNVERIFIABLE,
            "cites": [],
            "detail": "",
            "clause": "x",
            "why": "",
        }
        reading_value = self.legacy_reading(criterion)
        reading_value["criteria"] = {"goal": criterion, "line_1": criterion, "line_3": criterion}
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [{"n": 3, "at": NOW, "goal": "G", "lines": []}],
                        "assessment": reading_value,
                    }
                ],
            }
        )

        entry = self.entry()
        self.assertTrue(entry.get("refused"))
        self.assertNotIn("assessment", entry)

    def test_a_reading_keeps_the_time_its_evidence_ran_through(self) -> None:
        criterion = {
            "result": reading.RESULT_UNVERIFIABLE,
            "cites": [],
            "detail": "",
            "clause": "x",
            "why": "",
        }
        reading_value = self.legacy_reading(criterion)
        reading_value["criteria"] = {"goal": criterion, "line_1": criterion}
        reading_value["evidence_through"] = NOW - 60
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [{"n": 3, "at": NOW, "goal": "G", "lines": []}],
                        "assessment": reading_value,
                    }
                ],
            }
        )

        self.assertEqual(NOW - 60, self.entry()["assessment"]["evidence_through"])


class TheStoreNeverOutgrowsItsReadLimitTest(_StoreCase):
    """Owner ruling, 2026-09-24: a store over the read limit was ignored and then overwritten.

    The read limit is 16 MiB, and a write trims oldest-first until the file fits under it, so
    the next read always reads what the last write kept.
    """

    def full_entry(self, index: int, char: str) -> annotation_store.Annotation:
        text = char * 240
        criterion = {
            "result": reading.RESULT_DEPARTURE,
            "cites": tuple(
                f"{index:04d}".ljust(annotation_store.KEY_CAP_CHARS, "k") for _ in range(12)
            ),
            "detail": text,
            "clause": text,
            "why": "",
        }
        return cast(
            "annotation_store.Annotation",
            {
                "harness": "claude",
                "sid": f"s-{index:04d}",
                "revisions": tuple(
                    {
                        "n": n,
                        "at": NOW + index + n / 100,
                        "goal": text,
                        "lines": tuple({"text": text, "source": "typed"} for _ in range(6)),
                    }
                    for n in range(1, 17)
                ),
                "readings": 1,
                "assessment": {
                    "revision_read": 16,
                    "revision_read_at": NOW,
                    "read_at": NOW,
                    "stamp": "s",
                    "cutoff": "c",
                    "scope": "mid-flight",
                    "scope_text": reading.SCOPE_TEXT["mid-flight"],
                    "ended_at_read": None,
                    "evidence_through": NOW,
                    "criteria": {
                        name: dict(criterion)
                        for name in ("goal", *(f"line_{k}" for k in range(1, 7)))
                    },
                },
            },
        )

    def test_the_read_limit_is_sixteen_mib(self) -> None:
        self.assertEqual(16 * 1024 * 1024, self.config.annotation_read_cap_bytes)

    def test_every_count_bound_full_still_writes_and_reads_back_whole(self) -> None:
        entries = [self.full_entry(i, "a") for i in range(self.config.annotation_max_sessions)]

        self.assertTrue(annotation_store.save(self.config, entries))

        size = os.path.getsize(annotation_store.store_path(self.config))
        self.assertLessEqual(size, self.config.annotation_read_cap_bytes)
        loaded = annotation_store.load(self.config)
        self.assertEqual(self.config.annotation_max_sessions, len(loaded))
        self.assertEqual(16, len(loaded[-1]["revisions"]))
        self.assertEqual(6, len(loaded[-1]["revisions"][-1]["lines"]))

    def test_a_store_that_would_pass_the_limit_is_trimmed_oldest_first_rather_than_lost(
        self,
    ) -> None:
        # Astral characters serialise as twelve bytes each under `ensure_ascii`, so the count
        # bounds alone permit a store several times the read limit.
        entries = [
            self.full_entry(i, "\U0001f600") for i in range(self.config.annotation_max_sessions)
        ]

        self.assertTrue(annotation_store.save(self.config, entries))

        size = os.path.getsize(annotation_store.store_path(self.config))
        self.assertLessEqual(size, self.config.annotation_read_cap_bytes)
        loaded = annotation_store.load(self.config)
        self.assertGreater(len(loaded), 0, "the store was discarded on read")
        self.assertLess(len(loaded), len(entries))
        newest = f"s-{self.config.annotation_max_sessions - 1:04d}"
        self.assertIn(newest, {entry["sid"] for entry in loaded})
        self.assertNotIn("s-0000", {entry["sid"] for entry in loaded})

    def test_a_store_exactly_at_the_limit_is_kept_and_one_byte_less_drops_the_oldest(self) -> None:
        entries = [self.full_entry(i, "b") for i in range(3)]
        annotation_store.save(self.config, entries)
        exact = os.path.getsize(annotation_store.store_path(self.config))

        at_limit = dataclasses.replace(self.config, annotation_read_cap_bytes=exact)
        annotation_store.save(at_limit, entries)
        self.assertEqual(3, len(annotation_store.load(at_limit)))

        under = dataclasses.replace(self.config, annotation_read_cap_bytes=exact - 1)
        annotation_store.save(under, entries)
        kept = annotation_store.load(under)
        self.assertEqual(["s-0001", "s-0002"], [entry["sid"] for entry in kept])


class TheEntryBeingWrittenIsNeverTheOneTrimmedTest(_StoreCase):
    """D1: the trim drops by last write, and never drops the entry it was asked to write."""

    def seed(self, count: int, char: str) -> None:
        for i in range(count):
            annotation_store.annotate(
                self.config,
                self.state,
                "claude",
                f"s-{i}",
                goal=char * 200,
                lines=[char * 200] * 6,
                now=NOW + i,
            )

    def tight(self) -> RuntimeConfig:
        size = os.path.getsize(annotation_store.store_path(self.config))
        return dataclasses.replace(self.config, annotation_read_cap_bytes=size + 40)

    def assessment(self, char: str) -> reading.Assessment:
        criterion: reading.Criterion = {
            "result": reading.RESULT_UNVERIFIABLE,
            "cites": (),
            "detail": "",
            "clause": char * 200,
            "why": "",
        }
        return {
            "revision_read": 1,
            "revision_read_at": NOW,
            "window_start": None,
            "read_at": NOW,
            "stamp": "s",
            "cutoff": "c",
            "scope": "mid-flight",
            "scope_text": reading.SCOPE_TEXT["mid-flight"],
            "ended_at_read": None,
            "evidence_through": None,
            "criteria": {"goal": criterion, "line_1": cast("reading.Criterion", dict(criterion))},
        }

    def test_a_settle_on_the_oldest_entry_keeps_it_and_drops_the_next_oldest(self) -> None:
        for char in ("中", "\U0001f600"):
            with self.subTest(text=char):
                shutil.rmtree(self.root / "state", ignore_errors=True)
                self.seed(3, char)
                config = self.tight()

                outcome = annotation_store.settle(
                    config, self.state, "claude", "s-0", through=NOW, now=NOW + 10
                )

                kept = [e["sid"] for e in annotation_store.load(config)]
                self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
                self.assertEqual(["s-0", "s-2"], sorted(kept))

    def test_a_withheld_reason_and_a_reading_on_the_oldest_entry_keep_it(self) -> None:
        for char in ("中", "\U0001f600"):
            for kind in ("withheld", "reading"):
                with self.subTest(text=char, kind=kind):
                    shutil.rmtree(self.root / "state", ignore_errors=True)
                    self.seed(3, char)
                    config = self.tight()
                    if kind == "withheld":
                        outcome = annotation_store.record_withheld(
                            config,
                            self.state,
                            "claude",
                            "s-0",
                            reason=reading.WITHHELD_MODEL_FAILED,
                            spent=True,
                        )
                    else:
                        outcome = annotation_store.record_reading(
                            config, self.state, "claude", "s-0", assessment=self.assessment(char)
                        )

                    kept = [e["sid"] for e in annotation_store.load(config)]
                    self.assertEqual(annotation_store.OUTCOME_STORED, outcome)
                    self.assertEqual(["s-0", "s-2"], sorted(kept))

    def test_an_entry_that_cannot_fit_alone_is_refused_and_nothing_is_written(self) -> None:
        self.seed(1, "a")
        with open(annotation_store.store_path(self.config), "rb") as handle:
            before = handle.read()
        # The stored entry still fits; the one being written cannot, even with it dropped.
        config = dataclasses.replace(self.config, annotation_read_cap_bytes=len(before) + 10)

        outcome = annotation_store.annotate(
            config, self.state, "claude", "s-9", goal="b" * 240, lines=["b" * 240] * 6, now=NOW + 50
        )

        self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, outcome)
        with open(annotation_store.store_path(self.config), "rb") as handle:
            self.assertEqual(before, handle.read())

    def test_the_cache_is_what_the_file_holds_after_every_mutator(self) -> None:
        # T2: the mutators trim their own copy the way the write trims the file.
        actions: dict[str, Callable[[RuntimeConfig], str]] = {
            "annotate": lambda config: annotation_store.annotate(
                config, self.state, "claude", "s-new", goal="g" * 240, now=NOW + 99
            ),
            "unchanged": lambda config: annotation_store.annotate(
                config, self.state, "claude", "s-2", goal="中" * 200, now=NOW + 99
            ),
            "settle": lambda config: annotation_store.settle(
                config, self.state, "claude", "s-2", through=NOW, now=NOW + 99
            ),
            "clear": lambda config: annotation_store.clear(
                config, self.state, "claude", "s-2", now=NOW + 99
            ),
        }
        for name, act in actions.items():
            with self.subTest(mutator=name):
                shutil.rmtree(self.root / "state", ignore_errors=True)
                self.seed(3, "中")
                entries = list(annotation_store.load(self.config))
                # A cap the seeded store just fits, so any write that grows it trims.
                config = self.tight()
                self.state.annotations = cast("Any", tuple(entries))

                act(config)

                cached = [e["sid"] for e in (self.state.annotations or ())]
                self.assertEqual([e["sid"] for e in annotation_store.load(config)], cached)


class AStoreThatCannotBeReadIsNeverOverwrittenTest(_StoreCase):
    """D2: missing is not unreadable. Every write refuses over a store this build cannot trust."""

    def seed(self) -> bytes:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="keep me", now=NOW)
        with open(annotation_store.store_path(self.config), "rb") as handle:
            return handle.read()

    def untrusted(self) -> dict[str, Callable[[], object]]:
        path = annotation_store.store_path(self.config)
        return {
            "truncated": lambda: pathlib.Path(path).write_bytes(
                pathlib.Path(path).read_bytes()[:-1]
            ),
            "over the cap": lambda: pathlib.Path(path).write_bytes(
                pathlib.Path(path).read_bytes() + b" " * self.config.annotation_read_cap_bytes
            ),
            "not an object": lambda: pathlib.Path(path).write_bytes(b"[1, 2]"),
        }

    def test_every_write_is_refused_and_the_file_is_left_alone(self) -> None:
        writes: dict[str, Callable[[], str]] = {
            "annotate": lambda: annotation_store.annotate(
                self.config, self.state, "claude", "s-2", goal="new", now=NOW + 1
            ),
            "settle": lambda: annotation_store.settle(
                self.config, self.state, "claude", "s-1", through=NOW, now=NOW + 1
            ),
            "clear": lambda: annotation_store.clear(self.config, self.state, "claude", "s-1"),
            "withheld": lambda: annotation_store.record_withheld(
                self.config,
                self.state,
                "claude",
                "s-1",
                reason=reading.WITHHELD_MODEL_FAILED,
                spent=True,
            ),
        }
        for damage_name, damage in self.untrusted().items():
            for write_name, write in writes.items():
                with self.subTest(store=damage_name, write=write_name):
                    shutil.rmtree(self.root / "state", ignore_errors=True)
                    self.seed()
                    damage()
                    with open(annotation_store.store_path(self.config), "rb") as handle:
                        before = handle.read()

                    outcome = write()

                    self.assertEqual(annotation_store.OUTCOME_UNTRUSTED, outcome)
                    with open(annotation_store.store_path(self.config), "rb") as handle:
                        self.assertEqual(before, handle.read())

    def test_forget_leaves_an_untrusted_store_alone(self) -> None:
        self.seed()
        self.untrusted()["truncated"]()
        with open(annotation_store.store_path(self.config), "rb") as handle:
            before = handle.read()

        self.assertEqual(annotation_store.FORGET_UNTRUSTED, annotation_store.forget(self.config))
        with open(annotation_store.store_path(self.config), "rb") as handle:
            self.assertEqual(before, handle.read())

    def test_a_missing_store_is_simply_empty_and_takes_the_first_save(self) -> None:
        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", goal="first", now=NOW
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)

    def test_the_ruling_discloses_the_downgrade_over_a_large_store(self) -> None:
        text = (REPO / "docs" / "design-reading-a-session.md").read_text(encoding="utf-8")
        flat = re.sub(r"\s+", " ", text)
        self.assertIn("over 2.5 MiB", flat)
        self.assertIn("every session's saved words", flat)


class AStaleOrOlderPageCannotReplaceTheListTest(_StoreCase):
    """D3: the legacy one-line alias, and any replacement, need the revision they were drafted on."""

    def test_an_older_page_posting_one_output_over_a_list_is_refused(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=SIX[:3], now=NOW)

        for output in ("older text", ""):
            with self.subTest(output=output):
                outcome = annotation_store.annotate(
                    self.config, self.state, "claude", "s-1", output=output, now=NOW + 1
                )

                self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
                lines = self.entry()["revisions"][-1]["lines"]
                self.assertEqual(SIX[:3], [line["text"] for line in lines])

    def test_an_older_page_is_refused_over_one_line_too_without_a_revision(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=["one"], now=NOW)

        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", output="other", now=NOW + 1
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)

    def test_an_older_page_may_still_type_the_first_line_of_an_empty_list(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="G", now=NOW)

        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", output="a CSV", now=NOW + 1
        )

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)

    def test_replacing_a_list_without_the_revision_it_was_drafted_on_is_refused(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=["a"], now=NOW)

        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", lines=["b"], now=NOW + 1
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        self.assertEqual(["a"], [line["text"] for line in self.entry()["revisions"][-1]["lines"]])


class AnEntryThisBuildCannotReadIsKeptTest(_StoreCase):
    """D4: an entry refused on read goes back to disk as it was, like a refused reading."""

    FUTURE: dict[str, Any] = {  # noqa: RUF012
        "harness": "claude",
        "sid": "from-a-later-build",
        "revisions": [
            {"n": 1, "at": NOW, "goal": "G", "lines": [{"text": "x", "source": "model"}]}
        ],
    }

    def seed(self) -> None:
        self.write_raw({"v": 3, "entries": [dict(self.FUTURE)]})

    def on_disk(self) -> list[dict[str, Any]]:
        with open(annotation_store.store_path(self.config), encoding="utf-8") as handle:
            return list(json.load(handle)["entries"])

    def test_a_save_to_another_session_keeps_it_verbatim(self) -> None:
        self.seed()

        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="mine", now=NOW)

        self.assertIn(self.FUTURE, self.on_disk())
        self.assertIsNone(
            annotation_store.find(
                annotation_store.load(self.config), "claude", "from-a-later-build"
            )
        )

    def test_forget_keeps_it_verbatim(self) -> None:
        self.seed()
        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="mine", now=NOW)
        annotation_store.clear(self.config, self.state, "claude", "s-1", now=NOW + 1)

        self.assertEqual(annotation_store.FORGET_SWEPT, annotation_store.forget(self.config))
        self.assertIn(self.FUTURE, self.on_disk())


class ASessionHeldRawIsNeverWrittenOverTest(_StoreCase):
    """Round 2, F1: a session whose words this build cannot read takes no save, adopt or clear."""

    RAW: dict[str, Any] = {  # noqa: RUF012
        "harness": "claude",
        "sid": "future",
        "revisions": [
            {"n": 1, "at": NOW, "goal": "G", "lines": []},
            {
                "n": 2,
                "at": NOW,
                "goal": "G",
                "lines": [{"text": f"l{k}", "source": "typed"} for k in range(7)],
            },
        ],
    }

    def seed(self) -> bytes:
        self.write_raw({"v": 3, "entries": [dict(self.RAW)]})
        with open(annotation_store.store_path(self.config), "rb") as handle:
            return handle.read()

    def test_a_save_adopt_or_clear_on_that_session_is_refused_and_writes_nothing(self) -> None:
        row = {
            "harness": "claude",
            "sid": "future",
            "first_prompt": "Shape the cockpit",
            "first_prompt_at": NOW - 10,
        }
        writes: dict[str, Callable[[], str]] = {
            "goal": lambda: annotation_store.annotate(
                self.config, self.state, "claude", "future", goal="typed on old build", now=NOW
            ),
            "lines": lambda: annotation_store.annotate(
                self.config, self.state, "claude", "future", lines=["x"], now=NOW
            ),
            "adopt": lambda: annotation_store.adopt(
                self.config,
                self.state,
                row,
                source="first-prompt",
                expected_text="Shape the cockpit",
                expected_at=NOW - 10,
                now=NOW,
            ),
            "clear": lambda: annotation_store.clear(self.config, self.state, "claude", "future"),
        }
        for name, write in writes.items():
            with self.subTest(write=name):
                before = self.seed()

                outcome = write()

                self.assertEqual(annotation_store.OUTCOME_UNREADABLE, outcome)
                with open(annotation_store.store_path(self.config), "rb") as handle:
                    self.assertEqual(before, handle.read())


class AnUnreadableStoreNamesTheFileAndTheStepTest(_StoreCase):
    """Round 2, F2 and F3: every sentence about an unreadable store names the file and a step."""

    def damage(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="keep me", now=NOW)
        path = pathlib.Path(annotation_store.store_path(self.config))
        path.write_bytes(path.read_bytes()[:-1])

    def test_the_discard_sentence_names_the_file_and_the_step(self) -> None:
        said = annotation_store.DISCARD_UNTRUSTED
        self.assertIn("compass-annotations.json", said)
        self.assertIn("Move or repair that file", said)

    def test_the_board_says_the_store_could_not_be_read_rather_than_nothing_typed(self) -> None:
        self.damage()

        annotation_store.refresh(self.config, self.state)

        said = annotation_store.store_notice(self.state)
        self.assertIn("could not read compass-annotations.json", said)
        self.assertIn("Move or repair that file", said)

    def test_the_payload_carries_the_notice_to_the_page(self) -> None:
        self.damage()
        application = cli.build_application(
            self.config, self.state, diagnostic_sink=lambda _l: None
        )

        payload = application.collect(show_all=False)

        self.assertEqual(annotation_store.STORE_UNREADABLE, payload["annotate_unreadable"])

    def test_a_readable_store_publishes_no_notice(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="G", now=NOW)

        annotation_store.refresh(self.config, self.state)

        self.assertEqual("", annotation_store.store_notice(self.state))

    def test_forget_says_the_store_could_not_be_read(self) -> None:
        self.damage()

        self.assertEqual(annotation_store.FORGET_UNTRUSTED, annotation_store.forget(self.config))
        source = (REPO / "compass" / "skills" / "compass" / "compass_runtime" / "cli.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("could not be read", source)


class AnEntryLineKeepsItsOwnEntryTest(_StoreCase):
    """Round 2, F5: of two same-text entry lines, the one the page says it kept keeps its entry."""

    def seed(self) -> None:
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [
                            {
                                "n": 1,
                                "at": NOW,
                                "goal": "G",
                                "lines": [
                                    {"text": "same", "source": "entry", "source_id": "f-1"},
                                    {"text": "same", "source": "entry", "source_id": "f-2"},
                                ],
                            }
                        ],
                    }
                ],
            }
        )

    def save(self, **kwargs: Any) -> tuple[Any, ...]:
        annotation_store.annotate(
            self.config, self.state, "claude", "s-1", expected_revision=1, now=NOW + 1, **kwargs
        )
        return tuple(line.get("source_id") for line in self.entry()["revisions"][-1]["lines"])

    def test_deleting_the_first_of_two_keeps_the_survivors_own_entry(self) -> None:
        self.seed()

        self.assertEqual(("f-2",), self.save(lines=["same"], origins=[1]))

    def test_without_origins_a_line_keeps_the_source_in_its_own_place(self) -> None:
        self.seed()

        # First-text matching would give the second line f-1; its own place held f-2.
        self.assertEqual((None, "f-2"), self.save(lines=["typed first", "same"]))

    def test_an_origin_naming_a_different_text_gives_no_source(self) -> None:
        self.seed()

        self.assertEqual((None,), self.save(lines=["other"], origins=[0]))

    def test_malformed_origins_refuse_the_save(self) -> None:
        self.seed()
        for origins in ([0, 1], ["0"], [True], [-1]):
            with self.subTest(origins=origins):
                outcome = annotation_store.annotate(
                    self.config,
                    self.state,
                    "claude",
                    "s-1",
                    lines=["same"],
                    origins=origins,
                    expected_revision=1,
                    now=NOW + 1,
                )
                self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)


class AnEntryLineKeepsItsSourceOnceTest(_StoreCase):
    """D5: sources match one to one, so a typed duplicate of an entry line is typed."""

    def test_a_newly_typed_duplicate_of_an_entry_line_is_typed(self) -> None:
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [
                            {
                                "n": 1,
                                "at": NOW,
                                "goal": "G",
                                "lines": [{"text": "same", "source": "entry", "source_id": "f-9"}],
                            }
                        ],
                    }
                ],
            }
        )

        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=["same", "same"],
            expected_revision=1,
            now=NOW + 1,
        )

        lines = self.entry()["revisions"][-1]["lines"]
        self.assertEqual(["entry", "typed"], [line["source"] for line in lines])


class TheStoresOwnEdgeRulesTest(_StoreCase):
    """Tests F10 and F11: rules the store holds on its own, without the route in front."""

    def test_the_file_version_is_two(self) -> None:
        annotation_store.annotate(self.config, self.state, "claude", "s-1", goal="G", now=NOW)
        with open(annotation_store.store_path(self.config), encoding="utf-8") as handle:
            self.assertEqual(2, json.load(handle)["v"])

    def test_a_goal_beside_a_list_the_store_refuses_is_not_saved_either(self) -> None:
        outcome = annotation_store.annotate(
            self.config, self.state, "claude", "s-1", goal="G", lines=["y" * 241], now=NOW
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        self.assertEqual((), annotation_store.load(self.config))

    def test_a_boolean_revision_is_refused_by_the_store_itself(self) -> None:
        # `True == 1`, so over revision 1 only the type check tells it apart.
        annotation_store.annotate(self.config, self.state, "claude", "s-1", lines=["a"], now=NOW)

        outcome = annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s-1",
            lines=["b"],
            expected_revision=True,
            now=NOW + 1,
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)

    def test_an_entry_line_with_no_entry_named_refuses_the_whole_entry(self) -> None:
        self.write_raw(
            {
                "v": 2,
                "entries": [
                    {
                        "harness": "claude",
                        "sid": "s-1",
                        "revisions": [
                            {
                                "n": 1,
                                "at": NOW,
                                "goal": "G",
                                "lines": [{"text": "x", "source": "entry"}],
                            }
                        ],
                    }
                ],
            }
        )

        self.assertEqual((), annotation_store.load(self.config))


# --------------------------------------------------------------------------------- producer


class _Config:
    reading_settle_sec = 8.0
    annotation_text_cap_chars = 240


def _pi_fact(fact_id: str, at: float, summary: str = "wrote the retry loop") -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": "work_result",
        "by": "agent",
        "summary": summary,
        "at": at,
        "evidence": {"source": "transcript", "confidence": "high"},
        "source_session": {"harness": "pi", "sid": "p1"},
    }


def _reply(names: list[str], **over: dict[str, Any]) -> str:
    body = {name: {"result": "consistent", "cites": [1], "detail": ""} for name in names}
    body.update(over)
    return json.dumps(body)


class _ProducerCase(unittest.TestCase):
    ROW: dict[str, Any] = {"harness": "pi", "sid": "p1", "state": "working", "ended_at": None}  # noqa: RUF012

    def setUp(self) -> None:
        self.prompts: list[str] = []
        self.caps: list[int] = []

    def model(self, raw: str) -> Any:
        def run(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            self.prompts.append(prompt)
            self.caps.append(output_cap_bytes)
            return raw.encode("utf-8")[:output_cap_bytes].decode("utf-8", "ignore"), "ok"

        return run

    def produce(
        self,
        raw: str,
        *,
        lines: list[str] | None = None,
        facts: list[dict[str, Any]] | None = None,
        read_lines: bool = True,
    ) -> Any:
        revision = {
            "n": 2,
            "at": 10.0,
            "goal": "Harden the ingest",
            "lines": [
                {"text": text, "source": "typed"} for text in (SIX if lines is None else lines)
            ],
        }
        return reading.produce(
            cast("Any", _Config()),
            self.ROW,
            [revision],
            facts if facts is not None else [_pi_fact("f1", 100.0)],
            now=500.0,
            stamp_text="read",
            model=self.model(raw),
            read_lines=read_lines,
        )


class EachLineIsAskedOnItsOwnTest(_ProducerCase):
    def test_each_line_is_posed_in_its_own_tag_and_named_in_the_answer_shape(self) -> None:
        self.produce(_reply(["goal", *(f"line_{k}" for k in range(1, 7))]))

        prompt = self.prompts[0]
        for k, text in enumerate(SIX, start=1):
            with self.subTest(line=k):
                self.assertIn(f'<outcome_line n="{k}">\n{text}\n</outcome_line>', prompt)
                self.assertIn(f'"line_{k}": A', prompt)
        self.assertIn("Per clause: own evidence", prompt)
        self.assertIn("no copied Goal/line verdict.", prompt)
        self.assertNotIn("<expected_output>", prompt)

    def test_six_lines_come_back_as_six_criteria_beside_the_goal(self) -> None:
        assessment, why, spent = self.produce(_reply(["goal", *(f"line_{k}" for k in range(1, 7))]))

        self.assertEqual(("", True), (why, spent))
        assert assessment is not None
        self.assertEqual(
            ["goal", "line_1", "line_2", "line_3", "line_4", "line_5", "line_6"],
            list(assessment["criteria"]),
        )
        self.assertEqual(SIX[3], assessment["criteria"]["line_4"]["clause"])
        self.assertEqual(reading.RESULT_CONSISTENT, assessment["criteria"]["line_4"]["result"])

    def test_an_old_single_expected_output_is_read_as_line_one(self) -> None:
        assessment, _why, _spent = reading.produce(
            cast("Any", _Config()),
            self.ROW,
            [{"n": 1, "at": 10.0, "goal": "G", "output": "a CSV export"}],
            [_pi_fact("f1", 100.0)],
            now=500.0,
            stamp_text="read",
            model=self.model(_reply(["goal", "line_1"])),
            read_lines=True,
        )

        assert assessment is not None
        self.assertEqual({"goal", "line_1"}, set(assessment["criteria"]))
        self.assertEqual("a CSV export", assessment["criteria"]["line_1"]["clause"])

    def test_a_line_resting_only_on_the_readers_words_is_not_verifiable_while_another_stands(
        self,
    ) -> None:
        request = {**_pi_fact("n1", 90.0, "please finish it"), "type": "user_message"}
        facts = [request, _pi_fact("f1", 100.0)]
        raw = _reply(
            ["goal", "line_1", "line_2"],
            line_1={"result": "consistent", "cites": [1], "detail": ""},
            line_2={"result": "consistent", "cites": [2], "detail": ""},
        )

        assessment, _why, _spent = self.produce(raw, lines=SIX[:2], facts=facts)

        assert assessment is not None
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, assessment["criteria"]["line_1"]["why"])
        self.assertEqual(reading.RESULT_UNVERIFIABLE, assessment["criteria"]["line_1"]["result"])
        self.assertEqual(reading.RESULT_CONSISTENT, assessment["criteria"]["line_2"]["result"])

    def test_a_line_resting_only_on_the_agents_narration_is_not_verifiable_while_another_stands(
        self,
    ) -> None:
        # Narration is not one of the agent's messages: only `agent_message` joins
        # work in carrying a line (review, 2026-10-03).
        narration = {**_pi_fact("n1", 90.0, "said it was finished"), "type": "tool_use"}
        facts = [narration, _pi_fact("f1", 100.0)]
        raw = _reply(
            ["goal", "line_1", "line_2"],
            line_1={"result": "consistent", "cites": [1], "detail": ""},
            line_2={"result": "consistent", "cites": [2], "detail": ""},
        )

        assessment, _why, _spent = self.produce(raw, lines=SIX[:2], facts=facts)

        assert assessment is not None
        self.assertEqual(reading.WHY_NO_WORK_SHOWN, assessment["criteria"]["line_1"]["why"])
        self.assertEqual(reading.RESULT_UNVERIFIABLE, assessment["criteria"]["line_1"]["result"])
        self.assertEqual(reading.RESULT_CONSISTENT, assessment["criteria"]["line_2"]["result"])

    def test_a_check_that_does_not_show_a_lines_verdict_withdraws_only_that_line(self) -> None:
        passed = {
            "type": reading.TOOL_REPORT_TYPE,
            "subject": reading.CHECK_SUBJECT,
            "result": "passed",
        }
        ledger = (
            {**_ledger_entry("c1", 100.0), **passed},
            {**_ledger_entry("c2", 110.0), **passed},
        )
        selection = reading.Selection(cast("Any", ledger))
        parsed: dict[str, dict[str, Any]] = {
            "goal": {"token": "", "cites": (), "detail": ""},
            "line_1": {"token": "departure", "cites": (1,), "detail": "the retry loop is missing"},
            "line_2": {"token": "consistent", "cites": (2,), "detail": ""},
        }

        criteria = reading.resolve(
            parsed, selection, goal="", lines=SIX[:2], detail_cap_chars=240, window_start=50.0
        )

        self.assertEqual(reading.WHY_CHECK_DOES_NOT_SHOW_IT, criteria["line_1"]["why"])
        self.assertEqual(reading.RESULT_CONSISTENT, criteria["line_2"]["result"])

    def test_with_no_work_in_the_record_no_line_is_asked_and_the_goal_still_is(self) -> None:
        person = {
            **_pi_fact("m1", 100.0, "please harden the ingest"),
            "type": "user_message",
            "by": "person:jared",
        }

        assessment, _why, _spent = self.produce(_reply(["goal", "line_1"]), facts=[person])

        assert assessment is not None
        self.assertNotIn("<outcome_line", self.prompts[0])
        self.assertIn("<goal>", self.prompts[0])
        for k in range(1, 7):
            with self.subTest(line=k):
                self.assertEqual(reading.WHY_NOT_ASKED, assessment["criteria"][f"line_{k}"]["why"])
        self.assertNotEqual(reading.WHY_NOT_ASKED, assessment["criteria"]["goal"]["why"])


def _ledger_entry(fact_id: str, at: float) -> dict[str, Any]:
    return {
        "id": fact_id,
        "type": "work_result",
        "by": "agent",
        "summary": "wrote it",
        "at": at,
        "author": reading.AUTHOR_AGENT,
        "source": "transcript \u00b7 high",
        "work": True,
    }


class TheReplyAndThePromptHaveRoomForSevenTest(_ProducerCase):
    def worst_reply(self) -> str:
        detail = "\u00e9" * 240
        body = {
            name: {"result": "departure", "cites": list(range(1000, 1012)), "detail": detail}
            for name in ("goal", *(f"line_{k}" for k in range(1, 7)))
        }
        return json.dumps(body, indent=2, ensure_ascii=False)

    def test_the_reply_cap_is_8192_bytes(self) -> None:
        self.produce(_reply(["goal", "line_1"]))

        self.assertEqual([reading.REPLY_CAP_BYTES], self.caps)
        self.assertEqual(8_192, reading.REPLY_CAP_BYTES)

    def test_a_reply_exactly_at_the_cap_keeps_all_seven_answers(self) -> None:
        raw = self.worst_reply()
        size = len(raw.encode("utf-8"))
        self.assertLess(size, reading.REPLY_CAP_BYTES)
        raw = raw[:-1] + " " * (reading.REPLY_CAP_BYTES - size) + "}"
        self.assertEqual(reading.REPLY_CAP_BYTES, len(raw.encode("utf-8")))
        names = ["goal", *(f"line_{k}" for k in range(1, 7))]

        parsed = reading.parse_reply(raw, names)

        self.assertEqual(["departure"] * 7, [parsed[name]["token"] for name in names])

    def test_a_reply_cut_in_the_middle_of_a_line_keeps_every_answer_before_the_cut(self) -> None:
        raw = self.worst_reply()
        cut = raw[: raw.index('"line_5"') + 40]
        names = ["goal", *(f"line_{k}" for k in range(1, 7))]

        parsed = reading.parse_reply(cut, names, salvage=True)

        self.assertEqual(["departure"] * 5 + ["", ""], [parsed[name]["token"] for name in names])

    def test_a_cut_reply_never_turns_every_line_into_cant_tell(self) -> None:
        # The produce-level half: the model's reply is cut at the cap by the exec layer.
        raw = _reply(
            ["goal", *(f"line_{k}" for k in range(1, 7))],
            line_6={"result": "consistent", "cites": [1], "detail": "x" * 20_000},
        )

        assessment, _why, _spent = self.produce(raw)

        assert assessment is not None
        self.assertEqual(reading.RESULT_CONSISTENT, assessment["criteria"]["line_1"]["result"])
        self.assertNotIn("result", assessment["criteria"]["line_6"])
        self.assertEqual(reading.WHY_UNREADABLE, assessment["criteria"]["line_6"]["why"])

    def test_the_worst_intent_fits_its_share_and_leaves_room_for_the_record(self) -> None:
        astral = "\U0001f600" * 240
        # With the claims question too (owner, 2026-10-04): it took its room
        # from the answer shape, spelt once, and not from the record.
        header = reading._header(astral, (astral,) * 6, tool_note=True, claims=True)

        size = len(header.encode("utf-8"))
        self.assertLessEqual(size, reading.INTENT_SHARE_BYTES)
        self.assertEqual(9_216, reading.INTENT_SHARE_BYTES)
        self.assertGreaterEqual(observer.OBSERVER_MODEL_MAX_PROMPT_BYTES - size, 7_168)

    def test_an_intent_between_its_share_and_the_budget_still_drops_every_line(self) -> None:
        # Past 9,216 bytes and under 16,384, so only the share can be what refuses it.
        wide = "\U0001f600" * 500
        ledger = reading.build_ledger([_pi_fact("f1", 100.0)], "pi", "p1")
        header = reading._header("G", (wide,) * 6, tool_note=False)
        size = len(header.encode("utf-8"))
        self.assertGreater(size, reading.INTENT_SHARE_BYTES)
        self.assertLess(size, observer.OBSERVER_MODEL_MAX_PROMPT_BYTES)

        prompt, selection = reading.build_prompt(
            ledger, goal="G", lines=(wide,) * 6, max_bytes=observer.OBSERVER_MODEL_MAX_PROMPT_BYTES
        )

        self.assertNotIn("<outcome_line", prompt)
        self.assertIs(False, selection.asked_output)

    def test_an_intent_over_its_share_drops_every_line_together(self) -> None:
        huge = "\U0001f600" * 2_000
        ledger = reading.build_ledger([_pi_fact("f1", 100.0)], "pi", "p1")

        prompt, selection = reading.build_prompt(
            ledger, goal="G", lines=(huge,) * 6, max_bytes=observer.OBSERVER_MODEL_MAX_PROMPT_BYTES
        )

        self.assertNotIn("<outcome_line", prompt)
        self.assertIs(False, selection.asked_output)


class AReadingSaysHowFarItsEvidenceRanTest(_ProducerCase):
    def test_evidence_through_is_the_newest_entry_even_one_the_prompt_had_no_room_for(self) -> None:
        # Person-authored entries are reserved first, so a newer agent entry is the one left out.
        people = [
            {
                **_pi_fact(f"m{i}", 100.0 + i, "please " + "harden the ingest " * 9),
                "type": "user_message",
                "by": "person:jared",
            }
            for i in range(120)
        ]
        newest = _pi_fact("late", 900.0)

        assessment, _why, _spent = self.produce(_reply(["goal"]), facts=[*people, newest])

        assert assessment is not None
        self.assertNotIn("wrote the retry loop", self.prompts[0])
        self.assertEqual(900.0, assessment["evidence_through"])

    def test_evidence_through_counts_a_check_that_was_not_sent(self) -> None:
        # A Claude Code check with no tool-output grant is left out of the ledger, and it was
        # still in the record when the reading ran.
        row = {"harness": "claude", "sid": "c1", "state": "working", "ended_at": None}
        facts = [
            {
                "fact_id": "m1",
                "type": "user_message",
                "by": "person:jared",
                "summary": "harden the ingest",
                "at": 100.0,
                "evidence": {"source": "transcript", "confidence": "exact"},
                "source_session": {"harness": "claude", "sid": "c1"},
            },
            {
                "fact_id": "c9",
                "type": reading.TOOL_REPORT_TYPE,
                "subject": reading.CHECK_SUBJECT,
                "result": "failed",
                "by": "agent",
                "summary": "pytest",
                "at": 300.0,
                "evidence": {"source": "transcript", "confidence": "exact"},
                "source_session": {"harness": "claude", "sid": "c1"},
            },
            {**_pi_fact("x", 900.0), "source_session": {"harness": "claude", "sid": "other"}},
        ]

        assessment, _why, _spent = reading.produce(
            cast("Any", _Config()),
            row,
            [{"n": 1, "at": 10.0, "goal": "G", "lines": []}],
            facts,
            now=500.0,
            stamp_text="read",
            model=self.model(_reply(["goal"])),
            read_lines=True,
        )

        assert assessment is not None
        self.assertEqual(300.0, assessment["evidence_through"])

    def test_a_record_with_no_usable_time_is_not_read(self) -> None:
        # DRC-4715: an entry with no time cannot be placed after the words, so a record of only
        # those leaves the window nothing to read, and no reading claims how far it ran.
        assessment, why, spent = self.produce(_reply(["goal"]), facts=[_pi_fact("f1", 0.0)])

        self.assertIsNone(assessment)
        self.assertEqual(reading.WITHHELD_WINDOW_EMPTY, why)
        self.assertFalse(spent)


# ------------------------------------------------------------------------------ unasked lane


class TheUnaskedLaneSeesNoLinesTest(unittest.TestCase):
    """DEC-24 item 12: the unasked lane receives no outcome lines."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name), unasked_enabled=True)
        self.state = build_runtime_state(self.config, started=1_000.0)
        self.prompts: list[str] = []
        self.results: list[Any] = []

    def lane(self) -> unasked.Lane:
        prompts = self.prompts
        results = self.results

        class Model:
            def __init__(self, _config: Any, **_kw: Any) -> None:
                pass

            def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
                del output_cap_bytes
                prompts.append(prompt)
                # A model volunteering answers about lines it was never shown.
                return _reply(["goal", "line_1", "line_2"]), "ok"

        def produce(*args: Any, **kwargs: Any) -> Any:
            result = reading.produce(*args, **kwargs)
            results.append(result)
            return result

        refuse_real_models(self)
        self.enterContext(mock.patch.object(reading, "ClaudeReadingModel", Model))
        # A Claude Code session's unasked check is Claude Code's, which needs no
        # grant (owner, 2026-10-20); the CLI is pinned so every runner routes it there.
        self.enterContext(cli_on_path("claude"))
        self.enterContext(named_machine())
        assert reading_route.resolve("claude", unasked=True)["provider"] == reading_route.CLAUDE
        return unasked.Lane(
            self.config,
            popup_notifier=lambda _title, _message: "handed-over",
            diagnostic_sink=lambda _line: None,
            clock=lambda: 5_000.0,
            produce=produce,
            facts_for=lambda _state, _row, _now: [
                {**_pi_fact("f1", 100.0), "source_session": {"harness": "claude", "sid": "s-1"}}
            ],
            spawn=lambda work: work(),
        )

    def consider(self, entry: annotation_store.Annotation) -> None:
        lane = self.lane()
        for state in ("idle", "working"):
            lane.consider(
                self.state,
                [{"harness": "claude", "sid": "s-1", "state": state, "project": "p"}],
                [entry],
                now=5_000.0,
            )

    def test_the_lane_prompt_holds_no_line_and_no_answer_is_kept_for_one(self) -> None:
        entry = cast(
            "annotation_store.Annotation",
            {
                "harness": "claude",
                "sid": "s-1",
                "revisions": (
                    {
                        "n": 1,
                        "at": 10.0,
                        "goal": "Harden the ingest",
                        "lines": tuple({"text": text, "source": "typed"} for text in SIX),
                    },
                ),
            },
        )

        self.consider(entry)

        self.assertEqual(1, len(self.prompts), "the lane never read the goal")
        for text in SIX:
            with self.subTest(line=text):
                self.assertNotIn(text, self.prompts[0])
        self.assertNotIn("outcome_line", self.prompts[0])
        assessment = self.results[0][0]
        assert assessment is not None
        self.assertEqual(["goal"], list(assessment["criteria"]))

    def test_a_session_with_lines_and_no_goal_is_not_read_by_the_lane(self) -> None:
        entry = cast(
            "annotation_store.Annotation",
            {
                "harness": "claude",
                "sid": "s-1",
                "revisions": (
                    {
                        "n": 1,
                        "at": 10.0,
                        "goal": "",
                        "lines": ({"text": "a line", "source": "typed"},),
                    },
                ),
            },
        )

        self.consider(entry)

        self.assertEqual([], self.prompts)
        self.assertEqual([], self.results)


# ----------------------------------------------------------------------------------- history


class HistoryKeepsEachLineOnItsOwnTest(unittest.TestCase):
    def setUp(self) -> None:
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.config = make_config(
            state_home=self.home.name, state_dir=Path(self.home.name), os_name=support_os_name()
        )

    def row(self, lines: list[str], activity: float = 1_000.0) -> dict[str, Any]:
        row = runtime_sessions.base_session("claude", "sid-1", "recce/compass")
        row.update({"state": "working", "last_activity": activity, "own_activity": activity})
        for k, text in enumerate(lines, start=1):
            row[f"annotation_line_{k}"] = text
            row[f"annotation_line_{k}_source"] = "typed"
        return row

    def test_each_line_is_its_own_flat_field_with_its_source(self) -> None:
        history.record(self.config, [self.row(SIX)], now=1_000.0)

        entries, _reset = history.load(self.config)

        self.assertEqual(SIX, [entries[0][f"annotation_line_{k}"] for k in range(1, 7)])  # type: ignore[literal-required]
        self.assertEqual("typed", entries[0]["annotation_line_1_source"])

    def test_a_line_is_capped_at_256_characters_and_scrubbed(self) -> None:
        history.record(self.config, [self.row(["a\u202eb" + "z" * 400])], now=1_000.0)

        entries, _reset = history.load(self.config)

        stored = entries[0]["annotation_line_1"]
        self.assertEqual(256, len(stored))
        self.assertNotIn("\u202e", stored)

    def test_editing_any_one_line_is_a_transition(self) -> None:
        for k in range(1, 7):
            with self.subTest(line=k):
                shutil.rmtree(self.home.name, ignore_errors=True)
                os.makedirs(self.home.name, exist_ok=True)
                before = list(SIX)
                after = list(SIX)
                after[k - 1] = "edited"
                history.record(self.config, [self.row(before)], now=1_000.0)
                history.record(self.config, [self.row(after)], now=1_001.0)

                entries, _reset = history.load(self.config)

                self.assertEqual(2, len(entries))

    def test_a_change_of_source_alone_is_a_transition(self) -> None:
        history.record(self.config, [self.row(["one"])], now=1_000.0)
        moved = self.row(["one"])
        moved["annotation_line_1_source"] = "entry"
        history.record(self.config, [moved], now=1_001.0)

        entries, _reset = history.load(self.config)

        self.assertEqual(["typed", "entry"], [e["annotation_line_1_source"] for e in entries])

    def test_a_source_is_a_closed_token_and_only_beside_words(self) -> None:
        row = self.row(["one"])
        row["annotation_line_1_source"] = "model"
        row["annotation_line_2_source"] = "typed"
        history.record(self.config, [row], now=1_000.0)

        entries, _reset = history.load(self.config)

        self.assertIsNone(entries[0]["annotation_line_1_source"])
        self.assertIsNone(entries[0]["annotation_line_2_source"])

    def test_editing_a_line_is_a_transition(self) -> None:
        history.record(self.config, [self.row(["one"])], now=1_000.0)
        history.record(self.config, [self.row(["two"], activity=1_000.0)], now=1_001.0)

        entries, _reset = history.load(self.config)

        self.assertEqual(["one", "two"], [entry["annotation_line_1"] for entry in entries])

    def test_a_version_three_record_brings_its_expected_output_forward_as_line_one(self) -> None:
        path = history.store_path(self.config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {
            "harness": "claude",
            "sid": "sid-1",
            "project": "recce/compass",
            "state": "working",
            "last_activity": 1_000.0,
            "annotation_goal": "G",
            "annotation_output": "a CSV export",
            "annotation_revision": 2,
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"v": 3, "entries": [record]}, handle)

        entries, reset = history.load(self.config)

        self.assertIsNone(reset)
        self.assertEqual("a CSV export", entries[0]["annotation_line_1"])
        self.assertEqual("typed", entries[0]["annotation_line_1_source"])
        self.assertEqual("", entries[0]["annotation_line_2"])
        self.assertNotIn("annotation_output", entries[0])

    def test_the_store_version_moved_and_still_reads_the_old_ones(self) -> None:
        self.assertEqual(4, history.SCHEMA_VERSION)
        self.assertEqual((1, 2, 3, 4), history.READABLE_VERSIONS)

    def test_every_line_is_an_allowlisted_carrier_and_the_old_field_is_gone(self) -> None:
        lines = tuple(f"annotation_line_{k}" for k in range(1, 7))
        self.assertEqual(("first_prompt", "annotation_goal", *lines), history.PROMPT_TEXT_ALLOWLIST)
        for name in ("annotation_output",):
            self.assertNotIn(name, history.OBSERVATION_FIELDS)
            self.assertNotIn(name, history.PROMPT_TEXT_ALLOWLIST)
        for name in lines:
            self.assertIn(name, history.PROMPT_DERIVED_CARRIERS)


# -------------------------------------------------------------------------------------- HTTP


class TheAnnotateRouteTakesAListTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(state_home=home, state_dir=Path(home))
        self.application = cli.build_application(self.config, self.state, clock=lambda: NOW)

    @contextlib.contextmanager
    def serving(self) -> Any:
        httpd = make_server(application=self.application)
        thread = serve_until_closed(httpd)
        try:
            yield httpd.server_port
        finally:
            httpd.shutdown()
            thread.join(timeout=5)

    @staticmethod
    def post(port: int, body: bytes) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("POST", "/api/annotate", body=body, headers={"Content-Type": "text/plain"})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_a_list_of_lines_is_saved_and_answered_as_stored(self) -> None:
        with self.serving() as port:
            status, body = self.post(
                port, json.dumps({"harness": "claude", "sid": "s-1", "lines": SIX[:2]}).encode()
            )

        self.assertEqual(200, status)
        self.assertEqual("stored", json.loads(body)["outcome"])
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s-1")
        assert entry is not None
        self.assertEqual(SIX[:2], [line["text"] for line in entry["revisions"][-1]["lines"]])

    def test_origins_that_are_not_a_list_of_saved_positions_are_refused_with_400(self) -> None:
        for origins in ("0", [0, 1], ["0"], [True]):
            with self.subTest(origins=origins), self.serving() as port:
                status, _body = self.post(
                    port,
                    json.dumps(
                        {"harness": "claude", "sid": "s-1", "lines": ["a"], "origins": origins}
                    ).encode(),
                )
                self.assertEqual(400, status)

    def test_anything_but_a_list_of_strings_is_refused_with_400(self) -> None:
        for lines in ("one line", [1, 2], [{"text": "x", "source": "entry"}], {"a": 1}):
            with self.subTest(lines=lines), self.serving() as port:
                status, _body = self.post(
                    port, json.dumps({"harness": "claude", "sid": "s-1", "lines": lines}).encode()
                )
                self.assertEqual(400, status)
        self.assertEqual((), annotation_store.load(self.config))

    def test_a_seventh_line_answers_refused_and_mints_nothing(self) -> None:
        with self.serving() as port:
            status, body = self.post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "s-1", "lines": [*SIX, "seventh"]}
                ).encode(),
            )

        self.assertEqual(200, status)
        self.assertEqual("refused", json.loads(body)["outcome"])
        self.assertEqual((), annotation_store.load(self.config))

    def test_a_non_integer_expected_revision_is_refused_with_400(self) -> None:
        with self.serving() as port:
            status, _body = self.post(
                port,
                json.dumps(
                    {"harness": "claude", "sid": "s-1", "lines": ["a"], "expected_revision": True}
                ).encode(),
            )

        self.assertEqual(400, status)

    def test_the_body_cap_is_12288_bytes(self) -> None:
        self.assertEqual(12_288, self.config.annotation_body_cap_bytes)
        base = {"harness": "claude", "sid": "s-1", "lines": ["a"], "pad": ""}
        spare = 12_288 - len(json.dumps(base).encode())
        with self.serving() as port:
            fits, _ = self.post(port, json.dumps({**base, "pad": "p" * spare}).encode())
            over, _ = self.post(port, json.dumps({**base, "pad": "p" * (spare + 1)}).encode())

        self.assertEqual((200, 413), (fits, over))

    def test_six_lines_of_pasted_control_characters_fit_the_body_the_page_sends(self) -> None:
        # `JSON.stringify` writes each C0 control character as six bytes, and the page's box
        # counts characters, so this is the widest body a paste can produce before the store
        # collapses the characters to spaces.
        pasted = "\x01" * 240
        body = json.dumps(
            {
                "harness": "claude",
                "sid": "x" * 64,
                "goal": pasted,
                "lines": [pasted] * 6,
                "expected_revision": 123456,
            },
            separators=(",", ":"),
        ).encode()

        self.assertLessEqual(len(body), self.config.annotation_body_cap_bytes)

    def test_six_astral_lines_and_a_goal_fit_the_body_the_page_sends(self) -> None:
        astral = "\U0001f600" * 240
        body = json.dumps(
            {
                "harness": "claude",
                "sid": "x" * 64,
                "goal": astral,
                "lines": [astral] * 6,
                "expected_revision": 123456,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()

        self.assertLessEqual(len(body), self.config.annotation_body_cap_bytes)


class TheUnaskedSentenceSaysWhatTheLaneReadTest(unittest.TestCase):
    """C1: the lane reads a typed goal alone, so only a goal is something it has checked."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name), unasked_enabled=True)

    def entry(self, goal: str) -> annotation_store.Annotation:
        return cast(
            "annotation_store.Annotation",
            {
                "harness": "claude",
                "sid": "s-1",
                "revisions": (
                    {
                        "n": 2,
                        "at": 10.0,
                        "goal": goal,
                        "lines": ({"text": "A exists", "source": "typed"},),
                    },
                ),
            },
        )

    def check(self) -> Any:
        return {
            "harness": "claude",
            "sid": "s-1",
            "at": 4_000.0,
            "constraint": "",
            "clause": "",
            "reading": "",
            "evidence": "",
            "revision": 1,
            "cutoff": 4_000.0,
            "cutoff_text": "",
            "withdrawn": False,
        }

    def published(self, goal: str) -> dict[str, Any]:
        return unasked.published(
            self.config,
            (self.check(),),
            {"harness": "claude", "sid": "s-1"},
            entries=(self.entry(goal),),
            now=5_000.0,
        )

    def test_a_clean_check_says_it_read_the_goal_and_not_the_lines(self) -> None:
        said = self.published("G")

        self.assertTrue(said["departure_checked"])
        self.assertIn("your goal", said["departure_why"])
        self.assertIn(
            "Checks run while you were away read only your goal, not your expected outcome.",
            said["departure_why"],
        )

    def test_lines_with_no_goal_are_never_called_checked(self) -> None:
        said = self.published("")

        self.assertFalse(said["departure_checked"])
        self.assertEqual(departures.NEVER_CHECKED, said["departure_why"])

    def test_the_intent_log_uses_the_same_goal_only_test(self) -> None:
        source = (
            REPO / "compass" / "skills" / "compass" / "compass_runtime" / "http_api.py"
        ).read_text(encoding="utf-8")
        start = source.index('"departure_why": departures.why(')
        self.assertIn("has_typed_goal(entry)", source[start : start + 400])


class OnlyACutReplyIsSalvagedTest(unittest.TestCase):
    """C3: recovery is for a reply the cap cut, never for prose around an answer."""

    NAMES = ("goal", "line_1", "line_2")

    def test_prose_around_an_answer_is_unreadable_under_the_cap(self) -> None:
        draft = '{"goal": {"result": "consistent", "cites": [1]}, "line_2": {"result": "consistent", "cites": [1]}}'
        final = '{"goal": {"result": "consistent", "cites": [1]}, "line_2": {"result": "departure", "cites": [1]}}'
        for raw in (f"Sure: {final}", f"Draft: {draft}\nFinal: {final}", f"{final} trailing words"):
            with self.subTest(raw=raw[:20]):
                parsed = reading.parse_reply(
                    raw, self.NAMES, salvage=len(raw) >= reading.REPLY_CAP_BYTES
                )

                self.assertEqual(["", "", ""], [parsed[name]["token"] for name in self.NAMES])

    def test_produce_salvages_only_at_the_cap(self) -> None:
        case = _ProducerCase()
        case.setUp()
        body = '{"goal": {"result": "departure", "cites": [1], "detail": "x"}, "line_1": {"result'
        assessment, _why, _spent = case.produce(body, lines=SIX[:1])

        assert assessment is not None
        self.assertNotIn("result", assessment["criteria"]["goal"])


class ThePromptAndTheResolverNumberTheSameLinesTest(_ProducerCase):
    """C5: one filter decides which lines exist, for the prompt and for the answers."""

    def test_a_line_that_scrubs_to_nothing_takes_no_number(self) -> None:
        raw = _reply(
            ["goal", "line_1"], line_1={"result": "consistent", "cites": [1], "detail": ""}
        )

        assessment, _why, _spent = self.produce(raw, lines=["\u200b", "B must exist"])

        assert assessment is not None
        self.assertIn('<outcome_line n="1">\nB must exist\n</outcome_line>', self.prompts[0])
        self.assertEqual(["goal", "line_1"], list(assessment["criteria"]))
        self.assertEqual("B must exist", assessment["criteria"]["line_1"]["clause"])


class TheConsentNamesTheOutcomeLinesTest(unittest.TestCase):
    """C6: the disclosure names the field the reader now sees."""

    def test_the_consent_sentence_says_expected_outcome_lines(self) -> None:
        source = (
            REPO / "compass" / "skills" / "compass" / "compass_runtime" / "reading_route.py"
        ).read_text(encoding="utf-8")
        self.assertIn("expected outcome lines", source)
        self.assertNotIn("Your expected output is sent", source)


# -------------------------------------------------------------------------------------- docs


class TheRulingStatesEveryFigureTest(unittest.TestCase):
    """DEC-24 item 3: the layer that first stores or sends lines writes each figure there."""

    def item_three(self) -> str:
        text = (REPO / "docs" / "design-reading-a-session.md").read_text(encoding="utf-8")
        section = text[text.index("## DEC-24") :]
        start = section.index("\n3. The checklist.")
        return re.sub(r"\s+", " ", section[start : section.index("\n4. ", start)])

    def test_each_bound_is_written_into_item_three_as_the_code_holds_it(self) -> None:
        config = make_config()
        item = self.item_three()
        figures = {
            "lines": f"{reading.MAX_OUTCOME_LINES} lines",
            "line cap": f"{config.annotation_text_cap_chars} characters",
            "prompt share": f"{reading.INTENT_SHARE_BYTES:,} of {observer.OBSERVER_MODEL_MAX_PROMPT_BYTES:,} bytes",
            "reply cap": f"{reading.REPLY_CAP_BYTES:,} bytes",
            "body cap": f"{config.annotation_body_cap_bytes:,} bytes",
            "read limit": f"{config.annotation_read_cap_bytes // (1024 * 1024)} MiB",
            "history": f"{history.FIELD_CAP_CHARS} characters",
        }
        for name, figure in figures.items():
            with self.subTest(bound=name):
                self.assertIn(figure, item)
        self.assertNotIn("have no figure yet", item)


if __name__ == "__main__":
    unittest.main()
