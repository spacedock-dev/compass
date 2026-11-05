"""Reconciliation cites rehydrated originals, never map hypotheses."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from compass_runtime import (
    reading,
    reading_map_series,
    reading_maps,
    reading_passes,
    reading_reconcile_packet,
    reading_source_collect,
)

from . import test_reading_source_final as final_tests
from .test_agent_words import _agent, _check, _person, _write
from .test_claude_checks import SHORT
from .test_reading_source import CompleteReadingSourceFixture

GOAL = "Keep the retry safe."
LINES = ("The tests pass", "Do not delete the repository.")


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class ReconciliationPacketTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = reading_reconcile_packet

    def originals(self, facts: Sequence[Mapping[str, Any]]) -> list[reading_passes.Original]:
        words = {
            f["fact_id"]: f.get(reading.WORDS_FIELD, f.get(reading.AGENT_WORDS_FIELD))
            for f in facts
        }
        return [
            reading_passes.Original(row, words[row["id"]])
            for row in reading.build_ledger(
                facts, "claude", "s1", read_agent_words=True, tool_output={}
            )
        ]

    def packets(
        self,
        originals: Sequence[reading_passes.Original],
        *,
        max_bytes: int = 10000,
        overlap: int = 0,
        boundary_chars: int = 0,
    ) -> tuple[reading_passes.EvidencePacket, ...]:
        return reading_passes.plan_packets(
            originals,
            goal=GOAL,
            lines=LINES,
            protocol_prefix="Map protocol",
            max_bytes=max_bytes,
            max_passes=16,
            overlap_chars=overlap,
            boundary_chars=boundary_chars,
        ).packets

    def series(
        self, packets: Sequence[reading_passes.EvidencePacket] = (), *, bound: int = 20000
    ) -> reading_map_series.Series:
        index = reading_map_series.CandidateIndex()
        passed = []
        for ordinal, packet in enumerate(packets, 1):
            reply = reading_maps.parse_reply(
                json.dumps(
                    {
                        "version": 1,
                        "candidates": [
                            {
                                "clause": "line_1",
                                "kind": "conflicting" if ordinal % 2 else "supports",
                                "cites": [1],
                                "detail": "HYPOTHESIS_ONLY: the work might be safe.",
                            }
                        ],
                    }
                ),
                packet,
                clauses=("goal", "line_1", "line_2"),
            )
            self.assertTrue(reply.usable)
            index = index.add(ordinal, reply)
            passed.append(reading_map_series.EvidencePass(ordinal, packet, "mapped", "ok", ()))
        return reading_map_series.Series(
            "passes-ended",
            reading_passes.PacketPlan(tuple(packets), (), "complete", 0, 0),
            tuple(passed),
            index,
            (),
            (),
            (),
            reading_map_series.FinalSlot(17, bound, 8192),
        )

    def build(
        self,
        originals: Sequence[reading_passes.Original],
        series: reading_map_series.Series | None = None,
        *,
        scope_floor: reading.Selection | None = None,
        final: Mapping[str, Any] | None = None,
    ) -> reading_reconcile_packet.Reconciliation:
        return self.module.build(
            originals,
            series or self.series(self.packets(originals)),
            goal=GOAL,
            lines=LINES,
            scope=reading.SCOPE_FINAL,
            scope_floor=scope_floor or reading.Selection(tuple(o.row for o in originals)),
            final=final,
        )

    def test_failed_then_passed_and_later_write_all_reach_fresh_original_menu(self) -> None:
        facts = [
            _check(fact_id="fail", at=110.0, result="failed"),
            _check(fact_id="pass", at=120.0, result="passed"),
            {**_write(), "at": 130.0},
        ]
        originals = self.originals(facts)
        result = self.build(originals, self.series(self.packets(originals[:1])))
        self.assertEqual("ready", result.reason)
        assert result.packet is not None
        self.assertEqual(
            ["fail", "pass", "write-1"], [r["id"] for r in result.packet.selection.entries]
        )
        self.assertIn("HYPOTHESIS_ONLY", result.packet.prompt)
        self.assertNotIn("HYPOTHESIS_ONLY", repr(result.packet.selection.entries))
        self.assertEqual((), result.packet.selection.unread_checks)
        self.assertFalse(result.packet.selection.agent_words_whole)
        self.assertFalse(result.packet.selection.goal_whole)

    def test_pass_then_failure_and_irreversible_command_are_not_dropped_by_empty_index(
        self,
    ) -> None:
        facts = [
            _person("rule", 100, "Do not delete the repository."),
            _check(fact_id="pass", at=110, result="passed"),
            _check(fact_id="fail", at=120, result="failed"),
            _check(
                fact_id="delete",
                at=130,
                subject=reading.COMMAND_SUBJECT,
                summary="rm -rf repository",
                result="passed",
            ),
        ]
        result = self.build(self.originals(facts), self.series())
        assert result.packet is not None
        self.assertEqual(
            ["rule", "pass", "fail", "delete"], [r["id"] for r in result.packet.selection.entries]
        )
        self.assertIn("rm -rf repository", result.packet.prompt)
        parsed = reading.parse_reply(
            json.dumps({"line_1": {"result": "consistent", "cites": [3], "detail": ""}}),
            reading.constraints_for(LINES),
        )
        resolved = reading.resolve(
            parsed,
            result.packet.selection,
            goal=GOAL,
            lines=LINES,
            detail_cap_chars=400,
            scope=reading.SCOPE_FINAL,
            recorded=reading.recorded_from(facts, "claude", "s1"),
        )
        self.assertEqual(reading.RESULT_UNVERIFIABLE, resolved["line_1"]["result"])

    def test_cross_pass_correction_and_later_agent_words_remain_original_evidence(self) -> None:
        originals = self.originals(
            [
                _agent("first", 110, "The tests passed."),
                _person("correction", 120, "Correction: the retry test was never run."),
                _agent("later", 130, "I still need to run the retry test."),
            ]
        )
        packets = (self.packets(originals[:1])[0], self.packets(originals[1:])[0])
        result = self.build(originals, self.series(packets))
        assert result.packet is not None
        self.assertEqual(
            ["first", "correction", "later"], [r["id"] for r in result.packet.selection.entries]
        )
        self.assertIn("Correction: the retry test was never run.", result.packet.prompt)
        self.assertIn("I still need to run the retry test.", result.packet.prompt)
        self.assertIn('"conflicting"', result.packet.prompt)
        self.assertIn('"supports"', result.packet.prompt)

    def test_swapped_map_menu_rebinds_navigation_and_real_resolver_to_fresh_numbers(self) -> None:
        facts = [
            _person("rule", 100, "The tests pass"),
            _check(fact_id="check", at=110, result="passed"),
        ]
        originals = self.originals(facts)
        result = self.build(originals, self.series(self.packets(list(reversed(originals)))))
        assert result.packet is not None
        self.assertEqual(["rule", "check"], [r["id"] for r in result.packet.selection.entries])
        self.assertEqual([2], result.navigation[0]["cites"])
        raw = json.dumps({"line_1": {"result": "consistent", "cites": [2], "detail": ""}})
        resolved = reading.resolve(
            reading.parse_reply(raw, reading.constraints_for(LINES)),
            result.packet.selection,
            goal=GOAL,
            lines=LINES,
            detail_cap_chars=400,
            scope=reading.SCOPE_FINAL,
            recorded=reading.recorded_from(facts, "claude", "s1"),
        )
        self.assertEqual(("check",), resolved["line_1"]["cites"])

    def test_adjacent_overlapping_slices_merge_but_disjoint_slices_require_whole_original(
        self,
    ) -> None:
        original = self.originals([_agent("message", 110, "abcdefghij" * 120)])[0]
        packets = self.packets([original], max_bytes=500, overlap=10)
        result = self.build([original], self.series(packets[:2]))
        assert result.packet is not None
        span = result.packet.primary[0]
        self.assertEqual((0, packets[1].primary[0].end), (span.start, span.end))
        self.assertEqual(1, len(result.packet.selection.entries))
        self.assertIn("agent-words-partial", result.unresolved)
        disjoint = self.build([original], self.series((packets[0], packets[2])))
        assert disjoint.packet is not None
        assert original.words is not None
        self.assertEqual(
            (0, len(original.words)),
            (disjoint.packet.primary[0].start, disjoint.packet.primary[0].end),
        )
        limited = self.build([original], self.series((packets[0], packets[2]), bound=500))
        self.assertIsNone(limited.packet)
        self.assertEqual("prompt-unfit", limited.reason)

    def test_forged_or_foreign_candidate_bindings_refuse_the_packet(self) -> None:
        originals = self.originals([_agent("message", 110, "Original words.")])
        series = self.series(self.packets(originals))
        indexed = series.index.entries[0]
        cite = indexed.candidate.cites[0]
        for changed in (
            replace(cite, menu=2),
            replace(cite, span=replace(cite.span, fact_id="foreign")),
            replace(cite, span=replace(cite.span, at=999)),
            replace(cite, span=replace(cite.span, end=True)),
        ):
            with self.subTest(cite=changed):
                candidate = replace(indexed.candidate, cites=(changed,))
                bad = replace(
                    series,
                    index=replace(series.index, entries=(replace(indexed, candidate=candidate),)),
                )
                result = self.build(originals, bad)
                self.assertIsNone(result.packet)
                self.assertEqual("invalid-candidates", result.reason)

    def test_two_sided_middle_citation_restores_original_and_rejects_changed_context(self) -> None:
        originals = self.originals([_agent("message", 110, "abcdefghijkl" * 200)])
        packet = self.packets(originals, max_bytes=700, boundary_chars=4)[1]
        self.assertEqual(2, len(packet.context))
        series = self.series((packet,))
        result = self.build(originals, series)
        assert result.packet is not None
        cite = series.index.entries[0].candidate.cites[0]
        restored = result.packet.selection.entries[0]
        self.assertEqual("message", restored["id"])
        self.assertEqual(110, restored["at"])
        assert originals[0].words is not None
        self.assertEqual(
            originals[0].words[cite.span.start : cite.span.end], json.loads(restored["agent_words"])
        )
        indexed = series.index.entries[0]
        changed = replace(cite, context=(replace(cite.context[0], at=999), *cite.context[1:]))
        candidate = replace(indexed.candidate, cites=(changed,))
        bad = replace(
            series, index=replace(series.index, entries=(replace(indexed, candidate=candidate),))
        )
        refused = self.build(originals, bad)
        self.assertIsNone(refused.packet)
        self.assertEqual("invalid-candidates", refused.reason)

    def test_scope_floor_and_missing_passes_survive_even_when_packet_subset_fits(self) -> None:
        originals = self.originals(
            [_person("rule", 100, "The tests pass"), _check(at=110, result="passed")]
        )
        missing = reading.build_ledger(
            [_check(fact_id="missing", at=140, result="failed")], "claude", "s1", tool_output={}
        )[0]
        floor = reading.Selection(
            tuple(o.row for o in originals),
            unread_checks=(missing,),
            unread_failures=(missing,),
            record_failed=True,
            checks_unsent=True,
            unlisted=(150.0,),
        )
        series = self.series()
        series = replace(
            series, index=replace(series.index, overflow=True, unresolved_ordinals=(2,))
        )
        result = self.build(originals, series, scope_floor=floor)
        self.assertIn("candidate-overflow", result.unresolved)
        self.assertIn("map-unresolved", result.unresolved)
        assert result.packet is not None
        self.assertEqual((missing,), result.packet.selection.unread_checks)
        self.assertTrue(result.packet.selection.record_failed)
        self.assertTrue(result.packet.selection.checks_unsent)
        self.assertEqual((150.0,), result.packet.selection.unlisted)

    def test_missing_required_words_and_mandatory_counterproof_unfit_are_explicit(self) -> None:
        originals = self.originals(
            [_person("rule", 100, "Keep the entire direction."), _check(at=110)]
        )
        missing = [replace(originals[0], words=None), originals[1]]
        result = self.build(missing, self.series())
        self.assertIsNone(result.packet)
        self.assertEqual("original-unavailable", result.reason)
        unfit = self.build(originals, self.series(bound=100))
        self.assertIsNone(unfit.packet)
        self.assertEqual("prompt-unfit", unfit.reason)

    def test_collection_final_is_whole_only_when_full_serialized_packet_fits(self) -> None:
        fixture = final_tests.RetainedStrictFinalTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.say('Finished. 界🙂"\\' * 100)
        collection: reading_source_collect.Collection = fixture.collect()
        assert collection.evidence is not None
        assert collection.words is not None
        assert collection.final is not None
        final = collection.final
        facts = collection.evidence.facts
        words = {(w.fact_id, w.at): w.words for w in collection.words if w.state == "whole"}
        originals = [
            reading_passes.Original(row, words.get((row["id"], row["at"])))
            for row in reading.build_ledger(
                facts, "claude", SHORT, read_agent_words=True, tool_output={}
            )
        ]
        result = self.build(originals, self.series(), final=final)
        assert result.packet is not None
        self.assertEqual("whole", result.packet.selection.newest_final)
        self.assertFalse(result.packet.selection.agent_words_whole)
        final_row = next(
            row for row in result.packet.selection.entries if row["id"] == final["fact_id"]
        )
        self.assertEqual(final["words"], json.loads(final_row["agent_words"]))
        wire_bytes = len(result.packet.prompt.encode("utf-8"))
        too_small = self.build(originals, self.series(bound=wire_bytes - 1), final=final)
        self.assertIsNone(too_small.packet)
        self.assertEqual("unfit", too_small.final_state)
        self.assertIn("final-unfit", too_small.unresolved)
        named = {"outcome": "too-long", "fact_id": final["fact_id"], "at": final["at"]}
        blocked = self.build(originals, self.series(), final=named)
        assert blocked.packet is not None
        self.assertNotIn(final["fact_id"], [r["id"] for r in blocked.packet.selection.entries])
        self.assertEqual("unfit", blocked.packet.selection.newest_final)
        self.assertIn("final-unfit", blocked.unresolved)

    def test_boolean_range_cannot_alias_a_valid_one_character_candidate(self) -> None:
        originals = self.originals([_agent("message", 110, "x")])
        series = self.series(self.packets(originals))
        indexed = series.index.entries[0]
        cite = indexed.candidate.cites[0]
        bad = replace(cite, span=replace(cite.span, end=True))
        candidate = replace(indexed.candidate, cites=(bad,))
        altered = replace(
            series, index=replace(series.index, entries=(replace(indexed, candidate=candidate),))
        )
        result = self.build(originals, altered)
        self.assertIsNone(result.packet)
        self.assertEqual("invalid-candidates", result.reason)

    def test_later_cited_agent_still_requires_its_whole_counterproof_message(self) -> None:
        originals = self.originals(
            [
                _agent("early", 110, "The tests passed."),
                _agent("later", 120, "Correction. " + "context " * 150 + "COUNTERPROOF_TAIL"),
            ]
        )
        packets = (self.packets(originals[:1])[0], self.packets(originals[1:], max_bytes=500)[0])
        result = self.build(originals, self.series(packets))
        assert result.packet is not None
        later = next(span for span in result.packet.primary if span.fact_id == "later")
        assert originals[1].words is not None
        self.assertEqual((0, len(originals[1].words)), (later.start, later.end))
        self.assertIn("COUNTERPROOF_TAIL", result.packet.prompt)

    def test_physical_later_retraction_is_whole_despite_clock_rollback(self) -> None:
        originals = [
            self.originals([_agent("claim", 10, "The tests passed.")])[0],
            self.originals([_agent("retraction", 9, "Correction: the tests did not run.")])[0],
        ]
        result = self.build(originals, self.series(self.packets(originals[:1])))
        assert result.packet is not None
        self.assertEqual(
            [("claim", 10.0), ("retraction", 9.0)],
            [(row["id"], row["at"]) for row in result.packet.selection.entries],
        )
        retraction = result.packet.primary[1]
        assert originals[1].words is not None
        self.assertEqual((0, len(originals[1].words)), (retraction.start, retraction.end))
        self.assertIn("Correction: the tests did not run.", result.packet.prompt)

    def test_equal_timestamps_use_physical_order_for_later_counterproof(self) -> None:
        originals = [
            self.originals([_agent("before", 10, "Earlier background.")])[0],
            self.originals([_agent("claim", 10, "The tests passed.")])[0],
            self.originals([_agent("after", 10, "Correction: the retry test is still failing.")])[
                0
            ],
        ]
        result = self.build(originals, self.series(self.packets(originals[1:2])))
        assert result.packet is not None
        self.assertEqual(["claim", "after"], [row["id"] for row in result.packet.selection.entries])
        self.assertEqual([10.0, 10.0], [row["at"] for row in result.packet.selection.entries])
        after = result.packet.primary[1]
        assert originals[2].words is not None
        self.assertEqual((0, len(originals[2].words)), (after.start, after.end))
        self.assertIn("agent-words-partial", result.unresolved)

    def test_real_collected_reruns_and_later_write_keep_existing_resolver_guards(self) -> None:
        for history, write_after, expected in (
            (("failed", "passed"), False, reading.RESULT_CONSISTENT),
            (("passed", "failed"), False, reading.RESULT_UNVERIFIABLE),
            (("passed",), True, reading.RESULT_UNVERIFIABLE),
        ):
            with self.subTest(history=history, write_after=write_after):
                fixture = final_tests.RetainedStrictFinalTest()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                for outcome in history:
                    fixture.parent.bash(
                        "pytest tests/retry.py", f"1 {outcome}", is_error=outcome == "failed"
                    )
                if write_after:
                    fixture.parent.write("src/retry.py")
                collection: reading_source_collect.Collection = fixture.collect()
                assert collection.evidence is not None
                assert collection.words is not None
                assert collection.final is not None
                facts = collection.evidence.facts
                output = CompleteReadingSourceFixture.output(collection.evidence.press)
                words = {(w.fact_id, w.at): w.words for w in collection.words if w.state == "whole"}
                originals = [
                    reading_passes.Original(row, words.get((row["id"], row["at"])))
                    for row in reading.build_ledger(
                        facts,
                        "claude",
                        SHORT,
                        tool_output=output.tails,
                        changed_after=output.changed_after,
                        read_incomplete=output.read_incomplete,
                        read_agent_words=True,
                    )
                ]
                result = self.build(originals, self.series(), final=collection.final)
                assert result.packet is not None
                check_number = next(
                    index
                    for index, row in result.packet.selection.by_index().items()
                    if row.get("subject") == reading.CHECK_SUBJECT
                )
                parsed = reading.parse_reply(
                    json.dumps(
                        {"line_1": {"result": "consistent", "cites": [check_number], "detail": ""}}
                    ),
                    reading.constraints_for(LINES),
                )
                resolved = reading.resolve(
                    parsed,
                    result.packet.selection,
                    goal=GOAL,
                    lines=LINES,
                    detail_cap_chars=400,
                    scope=reading.SCOPE_FINAL,
                    recorded=reading.recorded_from(facts, "claude", SHORT, tool_output=output),
                )
                self.assertEqual(expected, resolved["line_1"]["result"])
