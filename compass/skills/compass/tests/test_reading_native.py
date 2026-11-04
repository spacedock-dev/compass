"""Native preparation and Assessment formatting never rebuild the model's menu."""

from __future__ import annotations

import datetime as dt
import importlib
import json
import re
import unittest
from dataclasses import replace
from unittest import mock

from compass_runtime import project_context, reading, reading_final_call, reading_map_series

from . import test_reading_useful_long as long_tests


class NativeProducerTest(unittest.TestCase):
    def setUp(self):
        self.fixture = long_tests.UsefulLongReconciliationTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.route = {
            "harness": "claude",
            "provider": "codex",
            "destination": "test destination",
            "label": "test route",
            "ci_read": "off",
        }

    def native(self):
        return importlib.import_module("compass_runtime.reading_native")

    def prepare(self, *, large=False, copied=False):
        f = self.fixture
        if large:
            f.collect_large()
        else:
            f.source.parent.prompt("Do not push to main.")
            f.source.parent.bash("pytest tests/retry.py", "1 failed", is_error=True)
            f.source.say("The retry check failed.")
        self.collection = f.source.collect()
        facts = self.collection.evidence.facts
        self.row = {
            "harness": "claude",
            "sid": long_tests.source_tests.SHORT,
            "state": "idle",
            "ended_at": max(fact["at"] for fact in facts) + 10,
        }
        self.revision = {
            "n": 2,
            "at": min(fact["at"] for fact in facts),
            "goal": "Keep the retry safe.",
            "lines": [
                {"text": "The tests pass", "source": "typed"},
                {"text": "Preserve retry behavior", "source": "typed"},
            ],
        }
        if copied:
            self.copied_id = next(
                fact["fact_id"]
                for fact in facts
                if fact["type"] == "user_message" and "push" in fact["summary"]
            )
            self.row[reading.COPIED_PROMPTS] = [{"fact_id": self.copied_id}]
        positions = {
            dt.datetime.fromisoformat(row["timestamp"]).timestamp(): i
            for i, row in enumerate(f.source.parent.rows)
        }
        # Explicit fixture-only oracle. The source owner's PhysicalOrigin join is pending.
        self.order = tuple(
            (fact["fact_id"], fact["at"])
            for fact in sorted(facts, key=lambda fact: positions[fact["at"]])
        )
        return self.call_prepare()

    def call_prepare(self, **changes):
        args = {
            "config": self.fixture.source.config,
            "row": self.row,
            "revisions": [self.revision],
            "collection": self.collection,
            "route": self.route,
            "physical_order": self.order,
            "now": self.row["ended_at"] + 60,
        }
        args.update(changes)
        return self.native().prepare(**args)

    def invoke(self, prepared):
        f = self.fixture
        series = reading_map_series.run(
            prepared.originals,
            goal=prepared.inputs.revision["goal"],
            lines=reading.outcome_lines(prepared.inputs.revision),
            clauses=("goal", "line_1", "line_2"),
            plan=f.marker.declared,
            model_for=f.model_for,
            stop_reason=lambda: None,
            on_observation=f.marker.observe,
            frozen_context=prepared.context,
            final=prepared.final,
        )
        result = reading_final_call.run(
            prepared.originals,
            series,
            inputs=prepared.inputs,
            scope_floor=prepared.floor,
            final=prepared.final,
            plan=f.marker.declared,
            model_for=f.model_for,
            stop_reason=lambda: None,
            detail_cap_chars=240,
            on_observation=f.marker.observe,
        )
        return series, result

    def test_actual_native_multi_prompt_preparation_and_partial_assessment(self):
        preparation = self.prepare(large=True)
        self.assertEqual("", preparation.reason)
        self.assertGreaterEqual(preparation.elapsed_ms, 0)
        prepared = preparation.prepared
        self.assertEqual(self.order, tuple((o.row["id"], o.row["at"]) for o in prepared.originals))
        self.assertEqual(
            self.collection.evidence.press.changed_after, prepared.inputs.tool_output.changed_after
        )
        self.assertEqual(self.collection.words, prepared.inputs.message_words)
        with (
            mock.patch.object(reading, "produce", side_effect=AssertionError("must not replay")),
            mock.patch.object(
                reading, "build_prompt", side_effect=AssertionError("must not rebuild")
            ),
        ):
            series, result = self.invoke(prepared)
            assessment = self.native().assessment(
                prepared,
                series,
                result,
                now=self.row["ended_at"] + 61,
                stamp_text="Fake model · read now",
            )
        self.assertGreater(len(series.passes), 1)
        self.assertEqual("partial", result.state)
        self.assertEqual(result.criteria, assessment["criteria"])
        self.assertEqual(2, assessment["revision_read"])
        self.assertEqual(reading.SCOPE_FINAL, assessment["scope"])
        self.assertIn("Native source", assessment["cutoff"])
        self.assertIn("Evidence prompts", assessment["cutoff"])
        self.assertIn("Final original packet", assessment["cutoff"])
        self.assertIn("already-mapped agent text", assessment["cutoff"])
        self.assertEqual(
            max(f["at"] for f in self.collection.evidence.facts), assessment["evidence_through"]
        )
        self.assertEqual(len(series.passes) + 1, self.fixture.marker.fixture.spends())

    def test_missing_ambiguous_or_retimed_physical_order_never_falls_back_to_clock(self):
        self.prepare()
        for order in (
            self.order[:-1],
            (*self.order, self.order[0]),
            ((self.order[0][0], self.order[0][1] + 1), *self.order[1:]),
        ):
            result = self.call_prepare(physical_order=order)
            self.assertEqual("original-order-unavailable", result.reason)
            self.assertIsNone(result.prepared)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_eligibility_and_incomplete_source_stop_before_any_calls(self):
        self.prepare()
        self.assertEqual(reading.WITHHELD_DISCARDED, self.call_prepare(discarded=True).reason)
        self.assertEqual(reading.WITHHELD_NOTHING_TYPED, self.call_prepare(revisions=[]).reason)
        result = self.call_prepare(collection=replace(self.collection, source_verified=False))
        self.assertEqual("source-incomplete", result.reason)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_copied_correction_stays_derived_uncitable_after_mapping_and_resolution(self):
        prepared = self.prepare(copied=True).prepared
        original = next(o for o in prepared.originals if o.row["id"] == self.copied_id)
        self.assertEqual(reading.AUTHOR_DERIVED, original.row["author"])
        self.assertIn(self.copied_id, prepared.context.value()["settlement"]["uncitable"])
        original_factory = self.fixture.model_for

        def factory(ordinal):
            guard = original_factory(ordinal)
            original_transport = guard.model

            def transport(prompt, *, output_cap_bytes):
                original_transport(prompt, output_cap_bytes=output_cap_bytes)
                match = re.search(r"^\[(\d+)\] user_message.*Do not push", prompt, re.MULTILINE)
                self.assertIsNotNone(match)
                cite = int(match[1])
                if ordinal == 17:
                    return json.dumps(
                        {
                            name: {
                                "result": "consistent",
                                "cites": [cite],
                                "detail": "Copied conclusion supports this.",
                            }
                            for name in ("goal", "line_1", "line_2")
                        }
                    ), "ok"
                return json.dumps(
                    {
                        "version": 1,
                        "candidates": [
                            {
                                "clause": "goal",
                                "kind": "supports",
                                "cites": [cite],
                                "detail": "Copied conclusion.",
                            }
                        ],
                    }
                ), "ok"

            guard.model = transport
            return guard

        self.fixture.model_for = factory
        series, result = self.invoke(prepared)
        self.assertTrue(
            any(
                row["id"] == self.copied_id and row["author"] == reading.AUTHOR_DERIVED
                for packet in series.plan.packets
                for row in packet.selection.entries
            )
        )
        self.assertTrue(
            all(
                c.get("result") not in {reading.RESULT_CONSISTENT, reading.RESULT_DEPARTURE}
                for c in result.criteria.values()
            )
        )

    def test_copied_source_cannot_be_adopted_as_person_intent(self):
        self.prepare(copied=True)
        copied = next(f for f in self.collection.evidence.facts if f["fact_id"] == self.copied_id)
        self.revision.update(
            goal="Do not push to main.", goal_source="chosen-prompt", goal_source_at=copied["at"]
        )
        result = self.call_prepare()
        self.assertEqual("adopted-goal-unavailable", result.reason)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_request_and_settlement_use_full_facts_and_freeze_before_mapping(self):
        self.prepare()
        requested = next(
            f
            for f in self.collection.evidence.facts
            if f["type"] == "user_message" and "push" in f["summary"]
        )
        self.revision["goal_saved_at"] = self.revision["at"]
        self.revision["at"] = requested["at"] + 1
        recovered = project_context._transcript_user_scan(
            self.fixture.source.config,
            self.fixture.source.path.read_bytes(),
            "claude",
            self.row["sid"],
        )
        request = reading.line_request_binding(
            recovered,
            source_id=requested["fact_id"],
            text="Do not push to main.",
            harness="claude",
            sid=self.row["sid"],
            now=self.revision["at"],
        )
        self.assertIsNotNone(request)
        self.revision["lines"][0] = {
            "text": "Do not push to main.",
            "source": "entry",
            "source_id": requested["fact_id"],
            "request": request,
        }
        self.assertIsNone(
            self.call_prepare().prepared.context.value()["provenance"]["lines"][0]["requested_at"]
        )
        prepared = self.call_prepare(
            settled_through=requested["at"], recovered_sources=recovered
        ).prepared
        value = prepared.context.value()
        self.assertEqual(requested["at"], value["provenance"]["lines"][0]["requested_at"])
        self.assertIn(requested["fact_id"], value["settlement"]["uncitable"])
        self.revision["goal"] = "Changed after preparation."
        self.row["ended_at"] += 100
        self.assertEqual("Keep the retry safe.", prepared.inputs.revision["goal"])
        self.assertNotEqual(self.row["ended_at"], prepared.inputs.row["ended_at"])

    def test_unknown_enabled_ci_binding_is_a_frozen_gap_without_any_ci_lookup(self):
        self.prepare()
        self.route["ci_read"] = "on"
        collection = replace(
            self.collection,
            ancillary_info=replace(self.collection.ancillary_info, ci_binding="unknown"),
        )
        prepared = self.call_prepare(collection=collection).prepared
        self.assertIn("context", prepared.context.value()["safety"]["gaps"])
        series, result = self.invoke(prepared)
        self.assertIsNone(result.criteria)
        self.assertIsNone(
            self.native().assessment(
                prepared, series, result, now=self.row["ended_at"] + 61, stamp_text="Fake"
            )
        )

    def test_missing_complete_message_words_refuses_before_calls(self):
        self.prepare()
        collection = replace(self.collection, words=self.collection.words[1:])
        result = self.call_prepare(collection=collection)
        self.assertEqual("message-words-unavailable", result.reason)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_known_missing_or_unfit_required_final_refuses_before_calls(self):
        self.prepare()
        proof = {k: v for k, v in self.collection.final.items() if k != "words"}
        for final, reason in (
            (None, "final-unavailable"),
            ({**proof, "outcome": "too-long"}, "final-unfit"),
        ):
            with self.subTest(reason=reason):
                result = self.call_prepare(collection=replace(self.collection, final=final))
                self.assertIsNone(result.prepared)
                self.assertEqual(reason, result.reason)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_failed_map_cannot_be_formatted_as_an_assessment(self):
        prepared = self.prepare().prepared
        self.fixture.fail_middle = self.fixture.always_consistent = True
        series, result = self.invoke(prepared)
        self.assertIsNone(result.criteria)
        self.assertIsNone(
            self.native().assessment(
                prepared, series, result, now=self.row["ended_at"] + 61, stamp_text="Fake"
            )
        )

    def test_formatter_refuses_a_detached_success_or_a_new_reassuring_partial(self):
        prepared = self.prepare().prepared
        series, result = self.invoke(prepared)
        self.assertEqual("resolved", result.state)

        def format_result(candidate, planned=series):
            return self.native().assessment(
                prepared, planned, candidate, now=self.row["ended_at"] + 61, stamp_text="Fake"
            )

        self.assertIsNotNone(format_result(result))
        self.assertIsNone(
            format_result(replace(result, packet=replace(result.packet, frozen_context=None)))
        )
        self.assertIsNone(
            format_result(
                replace(
                    result,
                    state="partial",
                    reason="final-context-partial",
                    unresolved=("agent-words-partial",),
                )
            )
        )
        self.assertIsNone(
            format_result(result, replace(series, failed_primary=series.plan.packets[0].primary))
        )

    def test_unnamed_tool_destination_retains_full_record_but_sends_no_output(self):
        self.prepare()
        self.route["destination"] = ""
        prepared = self.call_prepare().prepared
        self.assertTrue(any(f["type"] == reading.TOOL_REPORT_TYPE for f in prepared.inputs.facts))
        self.assertFalse(prepared.inputs.tool_output.tails)
        self.assertTrue(prepared.floor.checks_unsent)
        self.assertFalse(any(o.row["type"] == reading.TOOL_REPORT_TYPE for o in prepared.originals))
