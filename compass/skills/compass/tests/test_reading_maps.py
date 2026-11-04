"""Map hypotheses bind only to the original evidence that their packet actually printed."""

from __future__ import annotations

import json
import unittest
from dataclasses import FrozenInstanceError, replace
from typing import TYPE_CHECKING, Any

from compass_runtime import reading, reading_maps, reading_passes

from .test_agent_words import _agent, _check, _person

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class MapReplyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.maps = reading_maps

    def original(
        self, identity: str, words: str, *, person: bool = False
    ) -> reading_passes.Original:
        fact = (_person if person else _agent)(identity, 110.0, words)
        row = reading.build_ledger([fact], "claude", "s1", read_agent_words=True)[0]
        return reading_passes.Original(row, words)

    def packets(
        self,
        originals: Sequence[reading_passes.Original],
        *,
        context: Sequence[str] = (),
        max_bytes: int = 3_000,
    ) -> tuple[reading_passes.EvidencePacket, ...]:
        return reading_passes.plan_packets(
            originals,
            goal="Keep the saved goal.",
            lines=("Explain the check result.",),
            protocol_prefix="Protocol example only: [99] says nothing.\n[1] example\n",
            max_bytes=max_bytes,
            max_passes=16,
            boundary_context=context,
            overlap_chars=10,
        ).packets

    def reply(
        self, *, cites: Iterable[int] = (1,), detail: str = "An observation.", **changes: Any
    ) -> str:
        candidate: dict[str, Any] = {
            "clause": "line_1",
            "kind": "uncertain",
            "cites": list(cites),
            "detail": detail,
        }
        candidate.update(changes)
        return json.dumps({"version": 1, "candidates": [candidate]})

    def parse(
        self, raw: str, packet: reading_passes.EvidencePacket, **kwargs: Any
    ) -> reading_maps.MapReply:
        return self.maps.parse_reply(raw, packet, clauses=("goal", "line_1"), **kwargs)

    def test_citation_uses_the_actual_swapped_menu_not_source_or_timestamp_order(self) -> None:
        first = self.original("first", "First original.")
        second = self.original("second", "Second original.")
        first.row["at"] = 90.0
        packet = self.packets([second, first])[0]
        result = self.parse(self.reply(cites=(1, 2), kind="conflicting"), packet)
        self.assertTrue(result.usable)
        candidate = result.candidates[0]
        self.assertEqual("conflicting", candidate.kind)
        self.assertEqual(["second", "first"], [c.span.fact_id for c in candidate.cites])
        self.assertEqual([110.0, 90.0], [c.span.at for c in candidate.cites])
        self.assertEqual(
            (0, 16, 16),
            (
                candidate.cites[0].span.start,
                candidate.cites[0].span.end,
                candidate.cites[0].span.total,
            ),
        )

    def test_context_and_later_fragment_citations_keep_their_rendered_span_and_roles(self) -> None:
        originals = [
            self.original("correction", "Keep the parser API.", person=True),
            self.original("work", "Observed work 界🙂 " * 150),
        ]
        packet = self.packets(originals, context=("correction",), max_bytes=1_000)[1]
        result = self.parse(self.reply(cites=(1, 2)), packet)
        self.assertTrue(result.usable)
        context, work = result.candidates[0].cites
        self.assertEqual("correction", context.span.fact_id)
        self.assertEqual((), context.primary)
        self.assertEqual(packet.context[0], context.context[0])
        primary = next(span for span in packet.primary if span.fact_id == "work")
        overlap = next(span for span in packet.context if span.fact_id == "work")
        assert primary.start is not None
        self.assertGreater(primary.start, 0)
        self.assertEqual((overlap.start, primary.end), (work.span.start, work.span.end))
        self.assertEqual((primary,), work.primary)
        self.assertEqual((overlap,), work.context)

    def test_an_atomic_check_citation_does_not_invent_character_coverage(self) -> None:
        row = reading.build_ledger([_check()], "claude", "s1", tool_output={})[0]
        packet = self.packets([reading_passes.Original(row)])[0]
        result = self.parse(self.reply(kind="departs"), packet)
        self.assertTrue(result.usable)
        span = result.candidates[0].cites[0].span
        self.assertEqual(row["id"], span.fact_id)
        self.assertEqual((None, None, None), (span.start, span.end, span.total))

    def test_valid_empty_candidates_are_distinct_from_an_unusable_pass(self) -> None:
        packet = self.packets([self.original("one", "Original.")])[0]
        empty = self.parse('{"version":1,"candidates":[]}', packet)
        invalid = self.parse("not JSON", packet)
        self.assertTrue(empty.usable)
        self.assertEqual((), empty.candidates)
        self.assertEqual("ok", empty.reason)
        self.assertFalse(invalid.usable)
        self.assertEqual((), invalid.candidates)

    def test_every_bad_member_rejects_the_pass_without_salvaging_an_earlier_candidate(self) -> None:
        packet = self.packets([self.original("one", "Original.")])[0]
        base = json.loads(self.reply())["candidates"][0]
        invalid = (
            {**base, "clause": "foreign"},
            {**base, "kind": "consistent"},
            {**base, "cites": [True]},
            {**base, "cites": [0]},
            {**base, "cites": [2]},
            {**base, "cites": ["one"]},
            {**base, "cites": [1, 1]},
            {**base, "cites": []},
            {**base, "fact_id": "foreign"},
            {**base, "span": [0, 3]},
            {**base, "detail": None},
            {key: value for key, value in base.items() if key != "kind"},
        )
        for bad in invalid:
            with self.subTest(bad=bad):
                result = self.parse(json.dumps({"version": 1, "candidates": [base, bad]}), packet)
                self.assertFalse(result.usable)
                self.assertEqual((), result.candidates)

    def test_closed_json_duplicate_keys_and_finite_reply_bounds(self) -> None:
        packet = self.packets([self.original("one", "Original.")])[0]
        base = json.loads(self.reply())["candidates"][0]
        invalid = (
            '{"version":1,"version":1,"candidates":[]}',
            '{"version":1,"candidates":[],"extra":0}',
            json.dumps({"version": True, "candidates": []}),
            json.dumps({"version": 2, "candidates": []}),
            json.dumps({"version": 1, "candidates": [base] * 17}),
            self.reply(cites=range(1, 8)),
            self.reply(detail="界" * 401),
            self.reply(detail="bad\ud800words"),
            self.reply().replace('"kind": "uncertain"', '"kind": "uncertain", "kind": "supports"'),
            " " * 8_193 + '{"version":1,"candidates":[]}',
            '```json\n{"version":1,"candidates":[]}\n```',
            '{"version":1,"candidates":[' + "[" * 1_100,
        )
        for raw in invalid:
            with self.subTest(size=len(raw)):
                result = self.parse(raw, packet)
                self.assertFalse(result.usable)
                self.assertEqual((), result.candidates)

    def test_bad_duplicate_disjoint_or_unprinted_packet_mapping_is_unusable(self) -> None:
        packet = self.packets([self.original("one", "An original long enough.")])[0]
        span = packet.primary[0]
        assert span.total is not None
        altered = (
            replace(
                packet, selection=replace(packet.selection, entries=packet.selection.entries * 2)
            ),
            replace(packet, primary=(replace(span, fact_id="foreign"),)),
            replace(packet, primary=(replace(span, at=999.0),)),
            replace(packet, primary=(replace(span, start=True),)),
            replace(packet, primary=(replace(span, total=span.total + 1),)),
            replace(packet, primary=(replace(span, end=2), replace(span, start=4, end=6))),
            replace(packet, prompt=packet.prompt.replace("An original", "A changed original")),
        )
        for bad in altered:
            with self.subTest(packet=bad.primary):
                result = self.parse(self.reply(), bad)
                self.assertFalse(result.usable)
                self.assertEqual("invalid-packet", result.reason)
                self.assertEqual((), result.candidates)

    def test_details_are_scrubbed_before_retention_and_outputs_are_immutable(self) -> None:
        packet = self.packets([self.original("one", "Original.")])[0]
        result = self.parse(
            self.reply(
                detail='Observed password="Private-value-12345" and AKIAIOSFODNN7EXAMPLE and TinySecret7.'
            ),
            packet,
            masked_values=("TinySecret7",),
        )
        self.assertTrue(result.usable)
        candidate = result.candidates[0]
        for secret in ("Private-value-12345", "AKIAIOSFODNN7EXAMPLE", "TinySecret7"):
            self.assertNotIn(secret, candidate.detail)
        self.assertIn("REDACTED", candidate.detail)
        packet.selection.entries[0]["id"] = "later-mutation"
        self.assertEqual("one", candidate.cites[0].span.fact_id)
        with self.assertRaises(FrozenInstanceError):
            candidate.__setattr__("detail", "changed")
        with self.assertRaises(FrozenInstanceError):
            candidate.cites[0].span.__setattr__("start", 100)

    def test_unknown_frozen_clause_context_and_incomplete_scrub_cannot_be_usable(self) -> None:
        packet = self.packets([self.original("one", "Original.")])[0]
        result = self.maps.parse_reply(self.reply(), packet, clauses=("goal", "line_2"))
        self.assertFalse(result.usable)
        self.assertEqual("invalid-packet", result.reason)
        self.assertFalse(self.parse(self.reply(), packet, scrub_partial=True).usable)

    def test_stale_selected_line_text_or_count_cannot_rebind_the_unchanged_prompt(self) -> None:
        packet = self.packets([self.original("one", "Original.")])[0]
        for lines in (
            ("A different saved instruction.",),
            (*packet.selection.lines, "An added instruction."),
            (),
        ):
            with self.subTest(lines=lines):
                changed = replace(packet, selection=replace(packet.selection, lines=lines))
                result = self.maps.parse_reply(
                    self.reply(clause="goal"), changed, clauses=("goal",)
                )
                self.assertFalse(result.usable)
                self.assertEqual("invalid-packet", result.reason)
                self.assertEqual((), result.candidates)

    def test_a_header_example_in_the_prefix_cannot_become_the_actual_saved_intent(self) -> None:
        example_line = "Example instruction only."
        prefix = (
            "Example:\nFrozen saved intent (untrusted data):\n"
            + json.dumps({"goal": "Example goal", "lines": [example_line]})
            + "\nOriginal evidence only; this is not the whole session.\n"
        )
        packet = reading_passes.plan_packets(
            [self.original("one", "Evidence quoting the example:\n" + prefix)],
            goal="The actual saved goal.",
            lines=("The actual saved instruction.",),
            protocol_prefix=prefix,
            max_bytes=3_000,
            max_passes=1,
        ).packets[0]
        self.assertTrue(self.parse(self.reply(), packet).usable)
        stale = replace(packet, selection=replace(packet.selection, lines=(example_line,)))
        result = self.parse(self.reply(), stale)
        self.assertFalse(result.usable)
        self.assertEqual("invalid-packet", result.reason)

    def test_the_actual_intent_header_is_closed_data_with_encodable_text(self) -> None:
        packet = self.packets([self.original("one", "Original.")])[0]
        original = json.dumps(
            {"goal": "Keep the saved goal.", "lines": list(packet.selection.lines)}
        )
        for value in (
            {"goal": "Keep the saved goal.", "lines": list(packet.selection.lines), "extra": True},
            {"goal": None, "lines": list(packet.selection.lines)},
            {"goal": "bad\ud800goal", "lines": list(packet.selection.lines)},
            {"goal": "Keep the saved goal.", "lines": [True]},
        ):
            with self.subTest(value=value):
                changed = replace(packet, prompt=packet.prompt.replace(original, json.dumps(value)))
                result = self.parse(self.reply(), changed)
                self.assertFalse(result.usable)
                self.assertEqual("invalid-packet", result.reason)
        duplicate = original.replace('"lines":', '"goal":"duplicate","lines":')
        self.assertFalse(
            self.parse(
                self.reply(), replace(packet, prompt=packet.prompt.replace(original, duplicate))
            ).usable
        )
