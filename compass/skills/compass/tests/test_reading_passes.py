"""An ordinary original's exact packets retain text, intent and citation identity."""

from __future__ import annotations

import json
import re
import unittest
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from compass_runtime import project_context, reading, reading_passes
from compass_runtime.config import build_runtime_config

from .test_agent_words import _agent, _person

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class OrdinaryMessagePacketsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.row = reading.build_ledger(
            [_agent("original-message", 110.0, "The displayed excerpt.")],
            "claude",
            "s1",
            read_agent_words=True,
        )[0]
        self.goal = 'Review "parser" without changing its behavior. 界🙂'
        self.lines: tuple[str, ...] = ("Explain the result.", "Keep every quoted \\ path intact.")

    def prepare(
        self, words: str, *, max_bytes: int = 800, final_state: str | None = None
    ) -> Iterator[reading_passes.MessagePacket]:
        return reading_passes.message_packets(
            self.row,
            words=words,
            goal=self.goal,
            lines=self.lines,
            max_bytes=max_bytes,
            final_state=final_state,
        )

    def test_complete_masked_unicode_ranges_recover_the_original_without_a_cut_secret(self) -> None:
        config = build_runtime_config(
            environ={"HOME": "/synthetic"},
            platform_name="linux",
            os_name="posix",
            launcher_path=Path("/synthetic/server.py"),
        )
        phrase = '界🙂 "quoted" \\ path '
        raw = 'Before password="' + "Private-cut-value-0123456789" * 50 + '"\n\u2003'
        raw += phrase * 80 + "AFTER"
        record = {
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": raw}]},
        }
        # The real G2 source owner masks and normalizes once, before the renderer sees a cut.
        words = project_context.whole_message_words(config, record, "claude", len(raw) * 4)
        expected = "Before password=…REDACTED " + phrase * 80 + "AFTER"
        self.assertEqual(expected, words)
        packets = list(self.prepare(words))
        self.assertGreater(len(packets), 1)
        pieces: list[str] = []
        for packet in packets:
            self.assertEqual(len("".join(pieces)), packet.start)
            self.assertGreater(packet.end, packet.start)
            self.assertEqual(len(expected), packet.total)
            self.assertLessEqual(len(packet.prompt.encode("utf-8", "replace")), 800)
            self.assertNotIn("Private-cut-value", packet.prompt)
            self.assertNotIn("\ufffd", packet.prompt)
            selected = packet.selection.by_index()
            self.assertEqual([1], list(selected))
            actual = json.loads(selected[1]["agent_words"])
            self.assertEqual(expected[packet.start : packet.end], actual)
            # Read the sent JSON independently rather than trusting the projected row.
            wire = packet.prompt.encode("utf-8", "replace").decode("utf-8")
            menu = wire.split("\n[1] ", 1)[1]
            match = re.search(r"quoted, untrusted(?: \([^\n]*\))?: (.*)\n$", menu)
            self.assertIsNotNone(match, menu)
            assert match is not None
            self.assertEqual(actual, json.loads(match[1]))
            pieces.append(actual)
        self.assertEqual(expected, "".join(pieces))

    def test_each_packet_keeps_frozen_intent_and_original_metadata(self) -> None:
        original = self.row.copy()
        packets = self.prepare("ordinary words " * 200)
        self.row["summary"] = "A later mutation must not change this packet."
        for packet in packets:
            wire = packet.prompt.encode("utf-8", "replace").decode("utf-8")
            intent = json.loads(wire.split("\n", 2)[1])
            self.assertEqual({"goal": self.goal, "lines": list(self.lines)}, intent)
            self.assertEqual(self.lines, packet.selection.lines)
            selected = packet.selection.entries
            self.assertEqual(1, len(selected))
            for field in ("id", "at", "type", "author", "source", "summary", "work"):
                self.assertEqual(original[field], selected[0][field])
            self.assertEqual(packet.end - packet.start, selected[0]["text_read"])
            self.assertEqual(packet.total, selected[0]["text_total"])
            self.assertFalse(packet.selection.agent_words_whole)
            self.assertIsNone(packet.selection.newest_final)

    def test_exact_serialized_boundary_fits_and_one_byte_less_refuses(self) -> None:
        packet = next(self.prepare("🙂", max_bytes=10_000))
        size = len(packet.prompt.encode("utf-8", "replace"))
        self.assertGreater(size, len(packet.prompt))
        self.assertEqual(packet.prompt, next(self.prepare("🙂", max_bytes=size)).prompt)
        with self.assertRaises(ValueError):
            list(self.prepare("🙂", max_bytes=size - 1))

    def test_a_fitting_whole_row_is_not_refused_by_longer_fragment_labels(self) -> None:
        packet = next(self.prepare("ordinary words", max_bytes=10_000))
        size = len(packet.prompt.encode("utf-8", "replace"))
        self.assertEqual([packet], list(self.prepare("ordinary words", max_bytes=size)))

    def test_unencodable_words_refuse_before_even_a_clean_prefix_packet(self) -> None:
        for case, words in (
            ("high", "ok\ud800done"),
            ("low", "ok\udfffdone"),
            ("late", "ordinary words " * 200 + "\ud800"),
        ):
            with self.subTest(case=case), self.assertRaises(ValueError):
                next(self.prepare(words))

    def test_unencodable_saved_goal_or_line_is_not_silently_replaced_on_the_wire(self) -> None:
        for field in ("goal", "line"):
            for surrogate in ("\ud800", "\udfff"):
                with self.subTest(field=field, surrogate=repr(surrogate)):
                    self.goal = "Read the parser."
                    self.lines = ("Keep this exact saved line.",)
                    if field == "goal":
                        self.goal += surrogate
                    else:
                        self.lines = (*self.lines, "Explain " + surrogate + " exactly.")
                    with self.assertRaises(ValueError):
                        next(self.prepare("ordinary words"))

    def test_intent_is_never_shortened_to_make_room_for_evidence(self) -> None:
        self.lines = (*self.lines, "Keep this exact saved line. " * 80)
        with self.assertRaises(ValueError):
            list(self.prepare("ordinary words", max_bytes=800))

    def test_empty_words_and_invalid_bounds_refuse_without_yielding_a_header(self) -> None:
        with self.assertRaises(ValueError):
            list(self.prepare(""))

        # Deliberately violate the typed API to exercise its runtime boundary.
        for cap in (0, -1, True, 1.5):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                list(self.prepare("words", max_bytes=cast("int", cap)))

    def test_a_named_strict_final_never_enters_the_ordinary_fragment_path(self) -> None:
        for state in ("whole", "unfit", "unavailable"):
            with self.subTest(state=state), self.assertRaises(ValueError):
                list(self.prepare("FINAL_TAIL_SENTINEL" * 200, final_state=state))

    def test_a_non_agent_row_cannot_use_this_ordinary_agent_leaf(self) -> None:
        self.row = {**self.row, "type": "user_message", "author": "person"}
        with self.assertRaises(ValueError):
            list(self.prepare("person words"))


class OrderedPacketPlanTest(unittest.TestCase):
    def original(
        self, fact_id: str, words: str, *, person: bool = False
    ) -> reading_passes.Original:
        fact = (_person if person else _agent)(fact_id, 110.0, words)
        row = reading.build_ledger([fact], "claude", "s1", read_agent_words=True)[0]
        return reading_passes.Original(row, words)

    def plan(
        self, originals: Sequence[reading_passes.Original], **kwargs: Any
    ) -> reading_passes.PacketPlan:
        return reading_passes.plan_packets(
            originals,
            goal="Keep the saved parser goal.",
            lines=("Explain the check result.",),
            protocol_prefix="Caller protocol: inspect these originals only.\n",
            max_bytes=kwargs.pop("max_bytes", 1_100),
            max_passes=kwargs.pop("max_passes", 16),
            **kwargs,
        )

    def test_two_originals_pack_under_the_actual_numbered_menu_in_caller_order(self) -> None:
        originals = [
            self.original("first", "First words."),
            self.original("second", "Second words."),
        ]
        originals[1].row["at"] = 90.0
        result = self.plan(originals)
        self.assertEqual("complete", result.reason)
        self.assertEqual((), result.uncovered_primary)
        self.assertEqual(1, len(result.packets))
        packet = result.packets[0]
        self.assertEqual(["first", "second"], [row["id"] for row in packet.selection.entries])
        wire = packet.prompt.encode("utf-8", "replace").decode("utf-8")
        for index, original in enumerate(originals, 1):
            self.assertIn(f"[{index}] agent_message", wire)
            selected = packet.selection.by_index()[index]
            self.assertIn(selected["agent_words"], wire)
            self.assertEqual(original.words, json.loads(selected["agent_words"]))
        self.assertEqual(len(wire.encode()), result.transmitted_bytes)
        self.assertEqual(
            sum(len(cast("str", original.words)) for original in originals),
            result.covered_characters,
        )

    def test_split_primary_ranges_join_once_and_overlap_keeps_one_menu_identity(self) -> None:
        originals = [
            self.original("first", '界🙂 "one" \\ ' * 80),
            self.original("second", "second original " * 40),
        ]
        result = self.plan(originals, overlap_chars=13)
        self.assertEqual("complete", result.reason)
        self.assertGreater(len(result.packets), 2)
        primary: dict[str, list[tuple[int | None, int | None]]] = {
            original.row["id"]: [] for original in originals
        }
        transmitted_characters = 0
        for packet in result.packets:
            self.assertLessEqual(len(packet.prompt.encode()), 1_100)
            ids = [row["id"] for row in packet.selection.entries]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertFalse(packet.selection.agent_words_whole)
            self.assertIsNone(packet.selection.newest_final)
            for span in packet.primary:
                primary[span.fact_id].append((span.start, span.end))
            wire = packet.prompt.encode("utf-8", "replace").decode("utf-8")
            for index, row in packet.selection.by_index().items():
                sent_row = wire.split(f"\n[{index}] ", 1)[1].split("\n", 1)[0]
                sent_words = json.loads(sent_row.split("quoted, untrusted", 1)[1].split(": ", 1)[1])
                self.assertEqual(json.loads(row["agent_words"]), sent_words)
                transmitted_characters += len(sent_words)
        for original in originals:
            end = 0
            for start, following in primary[original.row["id"]]:
                self.assertEqual(end, start)
                assert start is not None and following is not None
                self.assertGreater(following, start)
                end = following
            self.assertEqual(len(cast("str", original.words)), end)
        self.assertEqual(
            sum(len(cast("str", o.words)) for o in originals), result.covered_characters
        )
        self.assertGreater(transmitted_characters, result.covered_characters)
        self.assertEqual(
            sum(len(p.prompt.encode()) for p in result.packets), result.transmitted_bytes
        )

    def test_adjacent_original_correction_is_required_context_without_duplicate_numbering(
        self,
    ) -> None:
        correction = self.original(
            "correction", "Correction: keep the parser public API.", person=True
        )
        work = self.original("work", "Read the recorded work carefully. " * 80)
        result = self.plan([correction, work], boundary_context=("correction",), overlap_chars=8)
        self.assertEqual("complete", result.reason)
        self.assertGreater(len(result.packets), 1)
        assigned_correction: list[reading_passes.EvidenceRange] = []
        for packet in result.packets:
            self.assertEqual(1, sum(r["id"] == "correction" for r in packet.selection.entries))
            self.assertIn(correction.words, packet.prompt)
            self.assertIn("correction", [span.fact_id for span in packet.context])
            assigned_correction.extend(
                span for span in packet.primary if span.fact_id == "correction"
            )
        self.assertEqual(1, len(assigned_correction))
        self.assertEqual(
            len(cast("str", correction.words)) + len(cast("str", work.words)),
            result.covered_characters,
        )

    def test_pass_cap_returns_the_exact_uncovered_primary_suffix(self) -> None:
        originals = [
            self.original("first", "first " * 200),
            self.original("second", "second " * 200),
        ]
        result = self.plan(originals, max_passes=1, overlap_chars=10)
        self.assertEqual("pass-limit", result.reason)
        self.assertEqual(1, len(result.packets))
        assigned = result.packets[0].primary[-1]
        self.assertEqual("first", assigned.fact_id)
        self.assertEqual(
            [
                ("first", assigned.end, len(cast("str", originals[0].words))),
                ("second", 0, len(cast("str", originals[1].words))),
            ],
            [(r.fact_id, r.start, r.end) for r in result.uncovered_primary],
        )

    def test_two_sided_boundary_context_keeps_exact_unicode_primary_coverage(self) -> None:
        originals = [
            self.original("failure", '界🙂 "retry failed" ' * 40),
            self.original("repair", "The retry is repaired; the check passes. " * 25),
            self.original("regression", "Later regression: it fails again. " * 25),
            self.original("conflict", "The claim of success conflicts with the failed check."),
        ]
        result = self.plan(originals, boundary_chars=40, max_bytes=1700)
        self.assertEqual("complete", result.reason)
        for original in originals:
            assert original.words is not None
            ranges = [
                s for p in result.packets for s in p.primary if s.fact_id == original.row["id"]
            ]
            self.assertEqual(0, ranges[0].start)
            self.assertEqual(len(original.words), ranges[-1].end)
            self.assertTrue(all(a.end == b.start for a, b in pairwise(ranges)))
        self.assertTrue(any(s.fact_id == "repair" for p in result.packets for s in p.context))
        self.assertTrue(all(len(p.prompt.encode("utf-8")) <= 1700 for p in result.packets))
        self.assertEqual(
            sum(len(p.prompt.encode("utf-8")) for p in result.packets), result.transmitted_bytes
        )

    def test_unfit_whole_final_neighbor_is_never_clipped_for_boundary_context(self) -> None:
        first = self.original("first", "Earlier failure." * 100)
        final = self.original("final", "The repair now passes." * 100)
        result = self.plan(
            [first, final],
            boundary_chars=40,
            max_bytes=1100,
            final={"outcome": "whole", "fact_id": "final", "at": 110.0, "words": final.words},
        )
        self.assertEqual("context-unfit", result.reason)
        self.assertTrue(result.uncovered_primary)
        self.assertFalse(any(s.fact_id == "final" for p in result.packets for s in p.context))
        self.assertTrue(all(len(p.prompt.encode("utf-8")) <= 1100 for p in result.packets))

    def test_required_context_that_does_not_fit_is_not_clipped_or_discarded(self) -> None:
        originals = [
            self.original("correction", "The complete correction must stay. " * 100, person=True),
            self.original("work", "Small work."),
        ]
        result = self.plan(originals, boundary_context=("correction",))
        self.assertEqual("context-unfit", result.reason)
        self.assertEqual((), result.packets)
        self.assertEqual(["correction", "work"], [r.fact_id for r in result.uncovered_primary])
        self.assertEqual(0, result.transmitted_bytes)
        self.assertEqual(0, result.covered_characters)

    def test_first_unfit_atomic_row_stops_before_a_smaller_later_original(self) -> None:
        message = self.original("later", "Small later original.")
        atomic = reading_passes.Original(
            {
                "id": "check",
                "at": 100.0,
                "type": "tool_report",
                "by": "agent",
                "author": "agent",
                "source": "recorded check",
                "summary": "An intact admitted check " * 100,
                "work": True,
                "subject": "check",
                "result": "failed",
            }
        )
        result = self.plan([atomic, message])
        self.assertEqual("prompt-unfit", result.reason)
        self.assertEqual((), result.packets)
        self.assertEqual(["check", "later"], [r.fact_id for r in result.uncovered_primary])
        self.assertIsNone(result.uncovered_primary[0].start)
        self.assertIsNone(result.uncovered_primary[0].end)

    def test_protocol_prefix_is_counted_before_evidence_allocation(self) -> None:
        original = self.original("one", "A short original.")
        packet = self.plan([original]).packets[0]
        exact = len(packet.prompt.encode())
        self.assertEqual("complete", self.plan([original], max_bytes=exact).reason)
        result = reading_passes.plan_packets(
            [original],
            goal="Keep the saved parser goal.",
            lines=("Explain the check result.",),
            protocol_prefix="Required protocol " * 100,
            max_bytes=exact,
            max_passes=1,
        )
        self.assertEqual("prompt-unfit", result.reason)
        self.assertEqual((), result.packets)

    def test_ambiguous_identity_and_strict_final_or_unencodable_input_refuse(self) -> None:
        original = self.original("one", "A short original.")
        with self.assertRaises(ValueError):
            self.plan([original, original])
        with self.assertRaises(ValueError):
            self.plan([reading_passes.Original(original.row, original.words, "unfit")])
        with self.assertRaises(ValueError):
            self.plan([original, self.original("late", "bad\ud800words")])
        for cap in (0, 17, True):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                self.plan([original], max_passes=cap)
