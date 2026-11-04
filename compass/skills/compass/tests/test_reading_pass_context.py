"""Frozen request metadata is exact budgeted data in every long-reading packet."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from typing import Any

from compass_runtime import (
    reading,
    reading_map_call,
    reading_map_series,
    reading_maps,
    reading_pass_context,
    reading_passes,
    reading_reconcile_packet,
)

from . import test_reading_map_call as call_tests
from .test_agent_words import _agent, _check, _person, _write
from .test_reading_pass_types import plan as declared_plan

GOAL = "The exact frozen goal."
LINES = ("The exact saved outcome line.",)


def metadata() -> dict[str, Any]:
    return {
        "revision": {"number": 7, "at": 100.0},
        "provenance": {
            "goal_source": "typed",
            "goal_source_at": None,
            "goal_saved_at": 90.0,
            "goal_status": "typed",
            "lines": [
                {"id": "line_1", "source": "entry", "source_id": "request", "requested_at": 80.0}
            ],
        },
        "window": {
            "start": 70.0,
            "end": 200.0,
            "scope": reading.SCOPE_FINAL,
            "end_kind": "session-end",
            "open_call_at": None,
        },
        "settlement": {"through": 95.0, "uncitable": ["kept-direction"]},
        "safety": {
            "record_failed": True,
            "checks_unsent": True,
            "unread_checks": [["check", 150.0]],
            "unread_failures": [["check", 150.0]],
            "unlisted": [160.0],
            "newest_final": "unavailable",
            "agent_words_whole": False,
            "goal_whole": False,
            "source_complete": None,
            "gaps": ["source"],
            "checks": [["check", 150.0, "failed", False, False, False]],
            "writes": [["write", 160.0]],
        },
    }


class FrozenPassContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = reading_pass_context

    def context(self, value: dict[str, Any] | None = None) -> reading_pass_context.Frozen:
        return self.module.freeze(GOAL, LINES, metadata() if value is None else value)

    def original(self, words: str = "An original.") -> reading_passes.Original:
        row = reading.build_ledger(
            [_agent("original", 110.0, words)], "claude", "s1", read_agent_words=True
        )[0]
        return reading_passes.Original(row, words)

    def packet(
        self, context: reading_pass_context.Frozen | None = None
    ) -> reading_passes.EvidencePacket:
        return reading_passes.plan_packets(
            [self.original()],
            goal=GOAL,
            lines=LINES,
            protocol_prefix=reading_map_call.protocol_prefix(GOAL, LINES, ("goal", "line_1")),
            max_bytes=6000,
            max_passes=1,
            frozen_context=context or self.context(),
        ).packets[0]

    def test_context_is_closed_immutable_and_independent_from_caller_mutation(self) -> None:
        supplied = metadata()
        context = self.context(supplied)
        supplied["revision"]["number"] = 99
        self.assertEqual(7, context.value()["revision"]["number"])
        decoded = context.value()
        decoded["safety"]["unread_checks"].clear()
        self.assertEqual([["check", 150.0]], context.value()["safety"]["unread_checks"])
        with self.assertRaises(FrozenInstanceError):
            context.__setattr__("encoded", "changed")

    def test_unknown_fields_bool_counts_bad_times_foreign_clauses_and_oversized_lists_refuse(
        self,
    ) -> None:
        variants = []
        for key, value in (("number", True), ("at", float("nan"))):
            bad = metadata()
            bad["revision"][key] = value
            variants.append(bad)
        bad = metadata()
        bad["provenance"]["lines"][0]["id"] = "line_2"
        variants.append(bad)
        bad = metadata()
        bad["provenance"]["goal_source"] = "invented"
        variants.append(bad)
        bad = metadata()
        bad["window"]["extra"] = "raw prose"
        variants.append(bad)
        bad = metadata()
        bad["safety"]["checks"] *= 513
        variants.append(bad)
        bad = metadata()
        bad["settlement"]["uncitable"] = ["bad\ud800id"]
        variants.append(bad)
        bad = metadata()
        bad["assessment"] = {"result": "consistent"}
        variants.append(bad)
        for variant in variants:
            with self.subTest(value=variant), self.assertRaises(ValueError):
                self.context(variant)

    def test_every_planned_map_packet_contains_the_same_intent_context_before_byte_fit(
        self,
    ) -> None:
        context = self.context()
        plan = reading_passes.plan_packets(
            [self.original("界🙂" * 3000)],
            goal=GOAL,
            lines=LINES,
            protocol_prefix=reading_map_call.protocol_prefix(GOAL, LINES, ("goal", "line_1")),
            max_bytes=4000,
            max_passes=3,
            frozen_context=context,
        )
        self.assertEqual(3, len(plan.packets))
        for packet in plan.packets:
            self.assertEqual(context, packet.frozen_context)
            self.assertLessEqual(len(packet.prompt.encode()), 4000)
            self.assertIn('"revision": {"at": 100.0, "number": 7}', packet.prompt)
            self.assertIn('"requested_at": 80.0', packet.prompt)
            self.assertIn('"record_failed": true', packet.prompt)
            self.assertTrue(
                reading_maps.parse_reply(
                    '{"version":1,"candidates":[]}', packet, clauses=("goal", "line_1")
                ).usable
            )

    def test_stale_missing_or_mismatched_metadata_cannot_bind_map_reply(self) -> None:
        packet = self.packet()
        other = metadata()
        other["revision"]["number"] = 8
        for altered in (
            replace(packet, frozen_context=self.context(other)),
            replace(packet, frozen_context=None),
            replace(packet, prompt=packet.prompt.replace('"number": 7', '"number": 8')),
        ):
            with self.subTest(context=altered.frozen_context):
                parsed = reading_maps.parse_reply(
                    '{"version":1,"candidates":[]}', altered, clauses=("goal", "line_1")
                )
                self.assertEqual("invalid-packet", parsed.reason)
        with self.assertRaises(ValueError):
            reading_passes.plan_packets(
                [self.original()],
                goal="Different goal",
                lines=LINES,
                protocol_prefix="protocol",
                max_bytes=6000,
                max_passes=1,
                frozen_context=self.context(),
            )

    def test_real_guard_local_overflow_from_context_has_no_charge_and_success_binds_context(
        self,
    ) -> None:
        fixture = call_tests.MapInvocationTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        unfit = fixture.invoke(max_bytes=1700, frozen_context=self.context())
        self.assertEqual("local-unfit", unfit.state)
        self.assertEqual(0, fixture.fixture.spends())
        self.assertEqual([], fixture.calls)
        result = fixture.invoke(frozen_context=self.context())
        self.assertEqual("mapped", result.state)
        self.assertEqual(1, fixture.fixture.spends())
        assert result.plan is not None
        self.assertEqual(self.context(), result.plan.packets[0].frozen_context)

    def test_series_and_reconciliation_share_identical_context_and_refuse_changed_scope(
        self,
    ) -> None:
        person = _person("direction", 100, "Keep the saved instruction.")
        row = reading.build_ledger([person], "claude", "s1")[0]
        originals = [reading_passes.Original(row, person[reading.WORDS_FIELD]), self.original()]
        declaration = declared_plan()
        declaration["limits"].update(
            prompt_bytes=12000, reply_bytes=8192, input_bytes=24000, output_bytes=16384
        )
        series = reading_map_series.run(
            originals,
            goal=GOAL,
            lines=LINES,
            clauses=("goal", "line_1"),
            plan=declaration,
            model_for=lambda _n: lambda *_a, **_k: ('{"version":1,"candidates":[]}', "ok"),
            stop_reason=lambda: None,
            frozen_context=self.context(),
        )
        self.assertEqual(self.context(), series.frozen_context)
        check = reading.build_ledger(
            [_check(fact_id="check", at=150.0)], "claude", "s1", tool_output={}
        )[0]
        write = reading.build_ledger(
            [{**_write(), "fact_id": "write", "at": 160.0}], "claude", "s1", tool_output={}
        )[0]
        floor = reading.Selection(
            (*tuple(o.row for o in originals), check, write),
            unread_checks=(check,),
            unread_failures=(check,),
            record_failed=True,
            checks_unsent=True,
            unlisted=(160.0,),
            newest_final="unavailable",
        )
        result = reading_reconcile_packet.build(
            originals,
            series,
            goal=GOAL,
            lines=LINES,
            scope=reading.SCOPE_FINAL,
            scope_floor=floor,
            final=None,
        )
        self.assertIsNotNone(result.packet)
        assert result.packet is not None
        self.assertEqual(series.frozen_context, result.packet.frozen_context)
        self.assertIn('"requested_at": 80.0', result.packet.prompt)
        self.assertIn("source-incomplete", result.unresolved)
        weakened = reading_reconcile_packet.build(
            originals,
            series,
            goal=GOAL,
            lines=LINES,
            scope=reading.SCOPE_FINAL,
            scope_floor=replace(floor, checks_unsent=False),
            final=None,
        )
        self.assertIsNone(weakened.packet)
        self.assertEqual("invalid-candidates", weakened.reason)
        changed = reading_reconcile_packet.build(
            originals,
            series,
            goal=GOAL,
            lines=LINES,
            scope=reading.SCOPE_MID_FLIGHT,
            scope_floor=floor,
            final=None,
        )
        self.assertIsNone(changed.packet)
        self.assertIn("invalid", changed.reason)

    def test_context_change_after_valid_empty_map_cannot_rebind_final_packet(self) -> None:
        packet = self.packet()
        declared = reading_map_series.Series(
            "passes-ended",
            reading_passes.PacketPlan((packet,), (), "complete", 0, 0),
            (reading_map_series.EvidencePass(1, packet, "mapped", "ok", ()),),
            reading_map_series.CandidateIndex(),
            (),
            (),
            (),
            reading_map_series.FinalSlot(17, 12000, 8192),
            self.context(),
        )
        changed = metadata()
        changed["revision"]["number"] = 8
        declared = replace(declared, frozen_context=self.context(changed))
        result = reading_reconcile_packet.build(
            [self.original()],
            declared,
            goal=GOAL,
            lines=LINES,
            scope=reading.SCOPE_FINAL,
            scope_floor=reading.Selection((self.original().row,)),
            final=None,
        )
        self.assertIsNone(result.packet)
        self.assertEqual("invalid-candidates", result.reason)
