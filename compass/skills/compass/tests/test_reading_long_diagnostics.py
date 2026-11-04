"""Long metrics keep source, observations and authoritative receipts distinct."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import unittest
from dataclasses import replace
from typing import Any

from compass_runtime import (
    reading_long_inspection,
    reading_source_collect,
    reading_source_inventory,
    reading_source_stream,
)

from . import test_reading_map_series as series_tests
from . import test_reading_source_collect as source_tests
from .test_reading_pass_types import diagnostic, observation, plan


class LongDiagnosticsTest(unittest.TestCase):
    def module(self) -> Any:
        self.assertIsNotNone(
            importlib.util.find_spec("compass_runtime.reading_long_diagnostics"),
            "the closed long diagnostic envelope is not implemented",
        )
        return importlib.import_module("compass_runtime.reading_long_diagnostics")

    def series(self) -> Any:
        fixture = series_tests.MapSeriesTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def source(self) -> tuple[Any, Any, Any]:
        fixture = source_tests.BoundedReadingCollectionTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        inventory = fixture.inventory()
        return fixture, inventory, fixture.collect(inventory=inventory)

    def test_missing_measurements_stay_unknown_and_legacy_envelopes_reject(self) -> None:
        module = self.module()
        value = module.derive(plan=plan())
        self.assertIsNone(value["source"])
        self.assertIsNone(value["maps"])
        self.assertIsNone(value["observations"])
        self.assertEqual(
            {"state": "unknown", "totals": None, "attempted_job": None}, value["accounting"]
        )
        self.assertIsNone(value["complete"])
        self.assertEqual(value, module.validate(value))
        self.assertIsNone(module.validate(diagnostic()))

    def test_reconciliation_merge_only_accepts_one_reserved_final_position(self) -> None:
        module = self.module()
        final: dict[str, Any] = {
            "observation": {**observation(), "ordinal": 17, "kind": "reconciliation"},
            "ended": True,
        }
        for slots in (
            [final, final],
            [{"observation": {**final["observation"], "ordinal": 16}, "ended": True}],
            [{"observation": {**final["observation"], "kind": "evidence"}, "ended": True}],
            [{"observation": observation(), "ended": True}],
        ):
            with self.subTest(slots=slots), self.assertRaises(ValueError):
                module.derive(plan=plan(), reconciliation_observations=slots)
        with self.assertRaises(ValueError):
            module.derive(plan=plan(), observations=[final], reconciliation_observations=[final])
        self.assertEqual(
            [final], module.derive(plan=plan(), reconciliation_observations=[final])["observations"]
        )

    def test_observation_copy_bounds_nested_validation_and_no_complete_assertion(self) -> None:
        module = self.module()
        slots: list[dict[str, Any]] = [{"observation": observation(), "ended": True}]
        value = module.derive(plan=plan(), observations=slots)
        before = copy.deepcopy(value)
        slots[0]["observation"]["diagnostic"]["input"]["prompt_bytes"] = 999
        self.assertEqual(before, value)
        checked = module.validate(value)
        checked["plan"]["limits"]["prompt_bytes"] = 1
        checked["observations"][0]["observation"]["diagnostic"]["input"]["prompt_bytes"] = 1
        self.assertEqual(before, value)
        for change in (
            {"complete": True},
            {"complete": 0},
            {"words": "PRIVATE"},
            {"version": True},
            {"version": 2},
            {"outcome": "completed"},
        ):
            self.assertIsNone(module.validate({**value, **change}))
        for bad in (
            [slots[0]] * 18,
            [slots[0], slots[0]],
            [{**slots[0], "ended": 1}],
            [{"observation": {**observation(), "diagnostic": {}}, "ended": True}],
        ):
            self.assertIsNone(module.validate({**value, "observations": bad}))
        all_slots = [
            {"observation": {**observation(), "ordinal": n}, "ended": True} for n in range(1, 17)
        ]
        all_slots.append(
            {
                "observation": {**observation(), "ordinal": 17, "kind": "reconciliation"},
                "ended": True,
            }
        )
        self.assertEqual(
            17, len(module.derive(plan=plan(), observations=all_slots)["observations"])
        )

    def test_real_collection_distinguishes_io_projection_and_unknown_eligible_extent(self) -> None:
        module = self.module()
        fixture, inventory, collected = self.source()
        value = module.derive(plan=plan(), inventory=inventory, collection=collected)
        source = value["source"]
        frozen = sum(s.cursor.frozen.end_offset for s in inventory.streams)
        self.assertEqual(frozen, source["frozen_bytes"])
        self.assertEqual(collected.usage.source_bytes, source["usage"]["io_bytes"])
        self.assertGreater(source["usage"]["io_bytes"], frozen)
        self.assertEqual(
            collected.usage.retained_bytes, source["usage"]["retained_graph_peak_bytes"]
        )
        self.assertTrue(source["source_verified"])
        self.assertEqual(len(collected.evidence.facts), source["canonical_fact_count"])
        self.assertIsNone(source["eligible_entries"])
        self.assertIsNone(source["eligible_message_characters"])
        self.assertIsNone(value["complete"])
        for stream in source["streams"]:
            self.assertEqual(stream["frozen_bytes"], stream["verified_end"])
        self.assertNotIn(str(fixture.path), json.dumps(value))
        stopped = replace(collected, reason="canonical_limit", evidence=None)
        stopped_value = module.derive(plan=plan(), inventory=inventory, collection=stopped)
        self.assertTrue(stopped_value["source"]["source_verified"])
        self.assertIsNone(stopped_value["source"]["canonical_fact_count"])
        self.assertFalse(stopped_value["complete"])

    def test_partial_and_bounded_inventory_never_invent_a_frontier_or_extent(self) -> None:
        module = self.module()
        fixture, inventory, collected = self.source()
        limited = fixture.collect(
            inventory=inventory, limits=reading_source_collect.Limits(source_bytes=1)
        )
        value = module.derive(plan=plan(), inventory=inventory, collection=limited)
        self.assertIsNone(value["source"]["streams"][0]["verified_end"])
        self.assertFalse(value["complete"])
        expanded = replace(
            inventory,
            streams=inventory.streams[:1] * 513,
            gaps=(reading_source_inventory.InventoryGap("streams"),),
        )
        value = module.derive(plan=plan(), inventory=expanded)
        self.assertEqual(512, len(value["source"]["streams"]))
        self.assertEqual(1, value["source"]["streams_omitted"])
        self.assertTrue(value["source"]["unexpanded_extent_unknown"])
        self.assertFalse(value["complete"])
        value["source"]["streams"].append(value["source"]["streams"][0])
        self.assertIsNone(module.validate(value))
        with self.assertRaises(ValueError):
            module.derive(plan=plan(), collection=collected)

    def test_real_series_counts_receipts_not_capture_emissions_and_leaks_no_words(self) -> None:
        module = self.module()
        fixture = self.series()
        series = fixture.run_series()
        inspected = reading_long_inspection.inspect(
            fixture.fixture.config, fixture.owner.live.prepared.job_id, now=100
        )
        value = module.derive(plan=fixture.declared, series=series, inspected=inspected)
        self.assertEqual(9, sum(len(p.snapshots) for p in series.passes))
        self.assertEqual(3, len(value["observations"]))
        self.assertEqual(
            {"calls": 3, "prompt_bytes": 7200, "reply_bytes": 24576}, value["accounting"]["totals"]
        )
        self.assertEqual(1, value["accounting"]["attempted_job"])
        self.assertEqual(7200, value["maps"]["planned_prompt_bytes"])
        self.assertEqual(7200, value["maps"]["observed_prompt_bytes"])
        self.assertEqual(3, value["maps"]["usable_primary_ranges"])
        self.assertEqual(0, value["maps"]["failed_primary_ranges"])
        self.assertIsNone(value["complete"])
        encoded = json.dumps(value)
        for canary in (
            "Frozen goal.",
            "Frozen line.",
            "Evidence 01",
            "Observation 1.",
            "a01",
            fixture.owner.live.prepared.job_id,
        ):
            self.assertNotIn(canary, encoded)

    def test_failed_map_and_never_called_ranges_are_distinct_from_historical_charges(self) -> None:
        module = self.module()
        fixture = self.series()
        fixture.responses[2] = ("PRIVATE RAW ERROR", "error")
        fixture.refuse = 3
        series = fixture.run_series()
        inspected = reading_long_inspection.inspect(
            fixture.fixture.config, fixture.owner.live.prepared.job_id, now=100
        )
        value = module.derive(plan=fixture.declared, series=series, inspected=inspected)
        self.assertEqual(2, value["accounting"]["totals"]["calls"])
        self.assertEqual(2, value["maps"]["failed_primary_ranges"])
        self.assertFalse(
            value["observations"][-1]["observation"]["diagnostic"]["input"]["attempt_reserved"]
        )
        self.assertFalse(value["complete"])
        self.assertNotIn("PRIVATE", json.dumps(value))

    def test_exact_zero_minimum_and_unknown_keep_distinct_job_count_evidence(self) -> None:
        module = self.module()
        fixture = self.series()
        fixture.begin()
        exact = reading_long_inspection.inspect(
            fixture.fixture.config, fixture.owner.live.prepared.job_id, now=100
        )
        self.assertEqual(
            0, module.derive(plan=fixture.declared, inspected=exact)["accounting"]["attempted_job"]
        )
        for totals, expected in (
            (reading_long_inspection.Totals(0, 0, 0), None),
            (reading_long_inspection.Totals(2, 20, 16384), 1),
        ):
            minimum = reading_long_inspection.Inspection("a" * 32, minimum=totals)
            accounting = module.derive(plan=plan(), inspected=minimum)["accounting"]
            self.assertEqual("minimum", accounting["state"])
            self.assertEqual(expected, accounting["attempted_job"])
        unknown = reading_long_inspection.Inspection("a" * 32, reason="ledger-unavailable")
        self.assertIsNone(module.derive(plan=plan(), inspected=unknown)["accounting"]["totals"])

    def test_all_counts_are_safe_integers_and_producer_nan_rejects(self) -> None:
        module = self.module()
        _, inventory, collected = self.source()
        value = module.derive(plan=plan(), inventory=inventory, collection=collected)
        for bad in (True, -1, 1.5, float("nan"), float("inf"), 2**53, "PRIVATE"):
            malformed = copy.deepcopy(value)
            malformed["source"]["usage"]["io_bytes"] = bad
            self.assertIsNone(module.validate(malformed))
        malformed = copy.deepcopy(value)
        malformed["source"]["usage"]["private"] = "PRIVATE CONFIG"
        self.assertIsNone(module.validate(malformed))
        with self.assertRaises(ValueError):
            module.derive(
                plan=plan(),
                inventory=inventory,
                collection=replace(
                    collected, usage=replace(collected.usage, prepare_ms=float("nan"))
                ),
            )

    def test_invalid_elapsed_values_cannot_round_into_valid_counts(self) -> None:
        module = self.module()
        _, inventory, collected = self.source()
        for invalid in (True, -0.1, float("inf"), "PRIVATE"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                module.derive(
                    plan=plan(),
                    inventory=inventory,
                    collection=replace(
                        collected, usage=replace(collected.usage, prepare_ms=invalid)
                    ),
                )

    def test_receipt_allocations_and_exact_observation_conservation(self) -> None:
        module = self.module()
        exact = reading_long_inspection.Inspection(
            "a" * 32, exact=reading_long_inspection.Totals(2, 20, 16384)
        )
        value = module.derive(plan=plan(), inspected=exact)
        value["accounting"]["totals"]["reply_bytes"] = 1
        self.assertIsNone(module.validate(value))
        slots = [{"observation": {**observation(), "ordinal": n}, "ended": True} for n in (1, 2, 3)]
        with self.assertRaises(ValueError):
            module.derive(plan=plan(), inspected=exact, observations=slots)
        minimum = replace(exact, exact=None, minimum=reading_long_inspection.Totals(1, 10, 8192))
        self.assertEqual(
            "minimum",
            module.derive(plan=plan(), inspected=minimum, observations=slots)["accounting"][
                "state"
            ],
        )

    def test_gap_metadata_is_bounded_closed_and_keeps_omitted_extent_explicit(self) -> None:
        module = self.module()
        _, inventory, collected = self.source()
        gap = reading_source_collect.KnownGap(
            0, reading_source_stream.Gap(0, 1, "unreadable_record", True)
        )
        stopped = replace(
            collected,
            source_verified=False,
            verified_streams=0,
            reason="source_gap",
            evidence=None,
            gaps=(gap,) * 513,
        )
        value = module.derive(plan=plan(), inventory=inventory, collection=stopped)
        self.assertEqual(512, len(value["source"]["gaps"]))
        self.assertEqual(1, value["source"]["gaps_omitted"])
        self.assertFalse(value["complete"])
        for key, invalid in (
            ("stream", True),
            ("reason", "PRIVATE ERROR"),
            ("end", -1),
            ("permanent", 1),
            ("path", "PRIVATE PATH"),
        ):
            wrong = copy.deepcopy(value)
            wrong["source"]["gaps"][0][key] = invalid
            self.assertIsNone(module.validate(wrong))
        value["source"]["gaps"].append(value["source"]["gaps"][0])
        self.assertIsNone(module.validate(value))

    def test_primary_characters_exclude_repeated_context_and_unknown_input_is_not_zero(
        self,
    ) -> None:
        module = self.module()
        fixture = self.series()
        originals = fixture.originals()
        series = fixture.run_series(originals)
        value = module.derive(plan=fixture.declared, series=series)
        self.assertEqual(
            sum(len(o.words) for o in originals), value["maps"]["planned_primary_characters"]
        )
        duplicated_context = tuple(
            replace(packet, context=packet.primary * 2) for packet in series.plan.packets
        )
        repeated = replace(
            series, plan=replace(series.plan, packets=duplicated_context, covered_characters=999999)
        )
        self.assertEqual(
            value["maps"]["planned_primary_characters"],
            module.derive(plan=fixture.declared, series=repeated)["maps"][
                "planned_primary_characters"
            ],
        )
        unknown = copy.deepcopy(series.observations)
        unknown[1]["observation"]["diagnostic"] = None
        value = module.derive(plan=fixture.declared, series=replace(series, observations=unknown))
        self.assertIsNone(value["maps"]["observed_prompt_bytes"])
