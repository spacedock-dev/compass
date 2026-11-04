"""A real multi-megabyte source must yield useful original-bound partial findings."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import unittest
from typing import TYPE_CHECKING, Any

from compass_runtime import (
    analyze_capacity,
    reading,
    reading_final_call,
    reading_long_markers,
    reading_map_series,
    reading_passes,
    reading_policy,
    reading_source_collect,
)

from . import test_reading_map_series as series_tests
from . import test_reading_source_final as source_tests
from .test_claude_checks import SHORT
from .test_reading_source import CompleteReadingSourceTest

if TYPE_CHECKING:
    from collections.abc import Mapping


class UsefulLongReconciliationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.source = source_tests.RetainedStrictFinalTest()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        self.marker = series_tests.MapSeriesTest()
        self.marker.setUp()
        self.addCleanup(self.marker.doCleanups)
        self.marker.declared.update(max_evidence_passes=16, max_calls=17)
        self.marker.declared["limits"].update(
            prompt_bytes=512 * 1024,
            input_bytes=17 * 512 * 1024,
            reply_bytes=8192,
            output_bytes=17 * 8192,
        )
        self.marker.begin()
        self.calls: list[tuple[int, str, int]] = []
        self.failed_map: int | None = None
        self.fail_middle = False
        self.always_consistent = False
        self.agent_hypothesis = False

    def collect_large(self, *, repair: bool = False, write: bool = False) -> None:
        for index in range(24):
            self.source.say(f"Context {index:02}. " + "x" * (128 * 1024 - 15), "tool_use")
            if index == 12:
                self.source.parent.bash("pytest tests/retry.py", "1 failed", is_error=True)
        if repair:
            self.source.parent.bash("pytest tests/retry.py", "1 passed")
        if write:
            self.source.parent.write(str(self.source.root / "retry.py"))
        self.source.say(
            "Correction: earlier claims of completion are withdrawn. Check the recorded retry results."
        )
        collection: reading_source_collect.Collection = self.source.collect()
        assert collection.evidence is not None
        assert collection.words is not None
        assert collection.final is not None
        self.assertGreater(self.source.path.stat().st_size, 3 * 1024 * 1024)
        self.assertTrue(collection.source_verified)
        self.assertEqual("", collection.reason)
        self.assertEqual("whole", collection.final["outcome"])
        self.assertLess(len(collection.final["words"]), 16384)
        self.assertTrue(
            all(
                w.total is not None and w.total < 256 * 1024
                for w in collection.words
                if w.state == "whole"
            )
        )
        facts = collection.evidence.facts
        output = CompleteReadingSourceTest.output(collection.evidence.press)
        self.inputs = reading_final_call.Inputs(
            {
                "harness": "claude",
                "sid": SHORT,
                "state": "idle",
                "annotation_assessment": {"detail": "STORED_READING_CANARY"},
                "ended_at": max(f["at"] for f in facts) + 10,
            },
            {
                "n": 1,
                "at": min(f["at"] for f in facts),
                "goal": "Keep the retry safe.",
                "lines": [
                    {"text": "The tests pass", "source": "typed"},
                    {"text": "Preserve retry behavior", "source": "typed"},
                ],
            },
            tuple(facts),
            output,
            message_words=collection.words,
        )
        self.floor = reading_final_call.scope_floor(self.inputs, scope=reading.SCOPE_FINAL)
        self.context = reading_final_call.freeze_context(
            self.inputs, self.floor, scope=reading.SCOPE_FINAL, source_complete=True
        )
        words = {(w.fact_id, w.at): w.words for w in collection.words if w.state == "whole"}
        # Fixture oracle only: generated native timestamps uniquely identify physical rows.
        # The production source-origin return seam is not implemented here.
        positions = {
            dt.datetime.fromisoformat(row["timestamp"]).timestamp(): index
            for index, row in enumerate(self.source.parent.rows)
        }
        self.originals = sorted(
            [
                reading_passes.Original(
                    row,
                    words.get((row["id"], row["at"])),
                    "whole" if row["id"] == collection.final["fact_id"] else None,
                )
                for row in self.floor.entries
            ],
            key=lambda o: positions[o.row["at"]],
        )
        self.final = collection.final
        self.middle = next(
            o.row["id"] for o in self.originals if o.row.get("subject") == reading.CHECK_SUBJECT
        )

    def model_for(self, ordinal: int) -> reading_policy.GuardedModel:
        def reserve(prompt: str, cap: int) -> reading_long_markers.Permit:
            self.assertEqual(8192, cap)
            request = self.marker.fixture.request(self.marker.owner, ordinal)
            request.update(
                kind="reconciliation" if ordinal == 17 else "evidence",
                max_evidence_passes=16,
                prompt_bytes=len(prompt.encode()),
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            )
            return self.marker.markers.reserve(
                self.marker.fixture.config, self.marker.owner, request=request, now=100
            )

        def transport(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
            self.calls.append((ordinal, prompt, output_cap_bytes))
            match = re.search(r"^\[(\d+)\] tool_report.*tests/retry\.py", prompt, re.MULTILINE)
            cites = [int(match[1])] if match else []
            if ordinal == 17:
                return json.dumps(
                    {
                        "goal": {"result": "consistent", "cites": cites, "detail": ""},
                        "line_1": {
                            "result": "consistent" if self.always_consistent else "departure",
                            "cites": cites,
                            "detail": "The retry check failed.",
                        },
                        "line_2": {"result": "consistent", "cites": cites, "detail": ""},
                    }
                ), "ok"
            if ordinal == self.failed_map or (self.fail_middle and cites):
                self.failed_map = ordinal
                return "invalid reply", "ok"
            if self.agent_hypothesis and ordinal == 1:
                agent = re.search(r"^\[(\d+)\] agent_message", prompt, re.MULTILINE)
                self.assertIsNotNone(agent)
                assert agent is not None
                cites = [int(agent[1])]
            return json.dumps(
                {
                    "version": 1,
                    "candidates": [
                        {
                            "clause": "line_1",
                            "kind": "departs",
                            "cites": cites,
                            "detail": "The check failed.",
                        }
                    ]
                    if cites
                    else [],
                }
            ), "ok"

        return reading_policy.GuardedModel(
            self.marker.fixture.config,
            transport,
            lambda: 100,
            provider="claude",
            reserve_prompt=reserve,
            admit_prompt=analyze_capacity.Admission(
                "codex", "unknown", "", requested_maximum=512 * 1024
            ),
        )

    def run_maps(self) -> reading_map_series.Series:
        return reading_map_series.run(
            self.originals,
            goal=self.inputs.revision["goal"],
            lines=reading.outcome_lines(self.inputs.revision),
            clauses=("goal", "line_1", "line_2"),
            plan=self.marker.declared,
            model_for=self.model_for,
            stop_reason=lambda: None,
            on_observation=self.marker.observe,
            frozen_context=self.context,
            final=self.final,
        )

    def invoke(self, series: reading_map_series.Series) -> reading_final_call.Result:
        return reading_final_call.run(
            self.originals,
            series,
            inputs=self.inputs,
            scope_floor=self.floor,
            final=self.final,
            plan=self.marker.declared,
            model_for=self.model_for,
            stop_reason=lambda: None,
            detail_cap_chars=240,
            on_observation=self.marker.observe,
        )

    def test_three_megabyte_actual_plan_retains_middle_check_departure_without_global_reassurance(
        self,
    ) -> None:
        self.collect_large()
        series = self.run_maps()
        self.assertGreater(len(series.passes), 1)
        self.assertFalse(series.failed_primary or series.unassigned_primary)
        for packet in series.plan.packets:
            self.assertLessEqual(len(packet.prompt.encode()), 512 * 1024)
            self.assertEqual(self.context, packet.frozen_context)
            self.assertIn(self.inputs.revision["goal"], packet.prompt)
            for line in reading.outcome_lines(self.inputs.revision):
                self.assertIn(line, packet.prompt)
            self.assertNotIn("STORED_READING_CANARY", packet.prompt)
        final_spans = [
            s for p in series.plan.packets for s in p.primary if s.fact_id == self.final["fact_id"]
        ]
        self.assertEqual(1, len(final_spans))
        self.assertEqual((0, len(self.final["words"])), (final_spans[0].start, final_spans[0].end))
        self.assertTrue(
            any(c.candidate.cites[0].span.fact_id == self.middle for c in series.index.entries)
        )
        result = self.invoke(series)
        self.assertEqual("partial", result.state)
        assert result.criteria is not None
        self.assertEqual(reading.RESULT_DEPARTURE, result.criteria["line_1"]["result"])
        self.assertEqual((self.middle,), result.criteria["line_1"]["cites"])
        assert result.packet is not None
        self.assertFalse(result.packet.selection.agent_words_whole)
        self.assertNotIn("STORED_READING_CANARY", result.packet.prompt)
        for name in ("goal", "line_2", "claims"):
            self.assertEqual(reading.RESULT_UNVERIFIABLE, result.criteria[name]["result"])
            self.assertEqual("long-reconciliation-coverage", result.criteria[name]["why"])
            self.assertEqual((), result.criteria[name]["cites"])
        self.assertEqual(len(series.passes) + 1, self.marker.fixture.spends())

    def test_failed_middle_map_keeps_later_evidence_but_withholds_always_consistent_final(
        self,
    ) -> None:
        self.collect_large()
        self.fail_middle = self.always_consistent = True
        series = self.run_maps()
        self.assertTrue(series.failed_primary)
        assert self.failed_map is not None
        self.assertGreater(len(series.passes), self.failed_map)
        self.assertEqual("mapped", series.passes[-1].state)
        result = self.invoke(series)
        self.assertIsNone(result.criteria)
        self.assertEqual("unresolved", result.state)
        self.assertIn("map-unresolved", result.unresolved)
        self.assertEqual(len(series.passes) + 1, self.marker.fixture.spends())

    def test_repaired_check_and_later_write_do_not_preserve_stale_middle_departure(self) -> None:
        self.collect_large(repair=True, write=True)
        series = self.run_maps()
        self.assertFalse(series.failed_primary or series.unassigned_primary)
        result = self.invoke(series)
        self.assertEqual("partial", result.state)
        assert result.packet is not None
        self.assertTrue(
            any(
                row.get("stale")
                for row in result.packet.selection.entries
                if row.get("subject") == reading.CHECK_SUBJECT
            )
        )
        assert result.criteria is not None
        self.assertEqual(reading.RESULT_UNVERIFIABLE, result.criteria["line_1"]["result"])
        self.assertEqual((), result.criteria["line_1"]["cites"])
        self.assertTrue(
            all(c["result"] != reading.RESULT_CONSISTENT for c in result.criteria.values())
        )

    def test_agent_hypothesis_requires_unfit_later_original_retraction_context(self) -> None:
        self.collect_large()
        self.agent_hypothesis = True
        series = self.run_maps()
        self.assertFalse(series.failed_primary or series.unassigned_primary)
        result = self.invoke(series)
        self.assertEqual("local-unfit", result.state)
        self.assertIsNone(result.criteria)
        self.assertTrue(result.unresolved)
        self.assertNotIn(17, [ordinal for ordinal, _prompt, _cap in self.calls])
        self.assertEqual(len(series.passes), self.marker.fixture.spends())

    def test_strict_final_never_splits_or_uses_named_unfit_fallback(self) -> None:
        self.source.say("Final words. " + "x" * 500)
        collection: reading_source_collect.Collection = self.source.collect()
        assert collection.evidence is not None
        assert collection.words is not None
        assert collection.final is not None
        proof = collection.final
        row = next(
            row
            for row in reading.build_ledger(
                collection.evidence.facts, "claude", SHORT, read_agent_words=True
            )
            if row["id"] == proof["fact_id"]
        )
        original = reading_passes.Original(row, proof["words"], "whole")

        def plan(
            max_bytes: int, final: Mapping[str, Any] | None = proof
        ) -> reading_passes.PacketPlan:
            return reading_passes.plan_packets(
                [original],
                goal="Goal",
                lines=(),
                protocol_prefix="Map",
                max_bytes=max_bytes,
                max_passes=4,
                final=final,
                overlap_chars=20,
            )

        full = plan(5000)
        self.assertEqual(1, len(full.packets))
        exact = len(full.packets[0].prompt.encode())
        self.assertEqual((), plan(exact - 1).packets)
        self.assertEqual(
            (0, len(proof["words"])),
            (plan(exact - 1).uncovered_primary[0].start, plan(exact - 1).uncovered_primary[0].end),
        )
        blocked = plan(
            5000, {k: v for k, v in {**proof, "outcome": "too-long"}.items() if k != "words"}
        )
        self.assertEqual((), blocked.packets)
        self.assertEqual(proof["fact_id"], blocked.uncovered_primary[0].fact_id)
        self.assertEqual(
            (0, len(proof["words"])),
            (blocked.uncovered_primary[0].start, blocked.uncovered_primary[0].end),
        )
        for changed in (
            {**proof, "fact_id": "foreign"},
            {**proof, "at": proof["at"] + 1},
            {**proof, "at": True},
            {**proof, "words": "different complete words"},
            {**proof, "extra": True},
        ):
            with self.subTest(proof=changed), self.assertRaises(ValueError):
                plan(5000, changed)
