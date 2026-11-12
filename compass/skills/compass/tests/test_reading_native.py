"""Native preparation and Assessment formatting never rebuild the model's menu."""

from __future__ import annotations

import datetime as dt
import json
import re
import unittest
from copy import deepcopy
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import (
    project_context,
    reading,
    reading_final_call,
    reading_long_finalize,
    reading_map_call,
    reading_map_series,
    reading_native,
    reading_pass_context,
    reading_passes,
    reading_policy,
    reading_reconcile_packet,
    reading_source_collect,
    settings,
)

from . import test_reading_useful_long as long_tests
from .test_claude_checks import SHORT


class NativeProducerTest(unittest.TestCase):
    def setUp(self) -> None:
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

    def prepare(self, *, large: bool = False, copied: bool = False) -> reading_native.Preparation:
        f = self.fixture
        if large:
            f.collect_large()
        else:
            f.source.parent.prompt("Do not push to main.")
            f.source.parent.bash("pytest tests/retry.py", "1 failed", is_error=True)
            f.source.say("The retry check failed.")
        self.collection: reading_source_collect.Collection = f.source.collect()
        assert self.collection.evidence is not None
        facts = self.collection.evidence.facts
        self.row: dict[str, Any] = {
            "harness": "claude",
            "sid": SHORT,
            "state": "idle",
            "ended_at": max(fact["at"] for fact in facts) + 10,
        }
        self.revision: dict[str, Any] = {
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
        # Independent fixture oracle; preparation consumes Collection.origins instead.
        self.order = tuple(
            (fact["fact_id"], fact["at"])
            for fact in sorted(facts, key=lambda fact: positions[fact["at"]])
        )
        return self.call_prepare()

    def call_prepare(self, **changes: Any) -> reading_native.Preparation:
        args: dict[str, Any] = {
            "config": self.fixture.source.config,
            "row": self.row,
            "revisions": [self.revision],
            "collection": self.collection,
            "route": self.route,
            "now": self.row["ended_at"] + 60,
            "prompt_bytes": self.fixture.marker.declared["limits"]["prompt_bytes"],
        }
        args.update(changes)
        return reading_native.prepare(**args)

    def invoke(
        self, prepared: reading_native.Prepared
    ) -> tuple[reading_map_series.Series, reading_final_call.Result]:
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
            line_cap_chars=800,
        )
        return series, result

    def test_actual_native_multi_prompt_preparation_and_partial_assessment(self) -> None:
        preparation = self.prepare(large=True)
        self.assertEqual("", preparation.reason)
        self.assertGreaterEqual(preparation.elapsed_ms, 0)
        prepared = preparation.prepared
        assert prepared is not None
        self.assertEqual(self.order, tuple((o.row["id"], o.row["at"]) for o in prepared.originals))
        assert prepared.inputs.tool_output is not None
        assert self.collection.evidence is not None
        self.assertEqual(
            self.collection.evidence.press.changed_after, prepared.inputs.tool_output.changed_after
        )
        assert self.collection.words is not None
        self.assertEqual(self.collection.words, prepared.inputs.message_words)
        with (
            mock.patch.object(reading, "produce", side_effect=AssertionError("must not replay")),
            mock.patch.object(
                reading, "build_prompt", side_effect=AssertionError("must not rebuild")
            ),
        ):
            series, result = self.invoke(prepared)
            assessment = reading_native.assessment(
                prepared,
                series,
                result,
                now=self.row["ended_at"] + 61,
                stamp_text="Fake model · read now",
            )
            assert assessment is not None
        self.assertGreater(len(series.passes), 1)
        self.assertEqual("partial", result.state)
        self.assertEqual(result.criteria, assessment["criteria"])
        self.assertEqual(2, assessment["revision_read"])
        self.assertEqual(reading.SCOPE_FINAL, assessment["scope"])
        self.assertIn("Native source", assessment["cutoff"])
        self.assertIn("Evidence prompts", assessment["cutoff"])
        self.assertIn("Final original packet", assessment["cutoff"])
        self.assertIn("already-mapped agent text", assessment["cutoff"])
        assert self.collection.evidence is not None
        self.assertEqual(
            max(f["at"] for f in self.collection.evidence.facts), assessment["evidence_through"]
        )
        self.assertEqual(len(series.passes) + 1, self.fixture.marker.fixture.spends())

    def test_the_smallest_prompt_sets_aside_lines_it_has_no_room_for(self) -> None:
        # Analyze's smallest prompt with the widest saved intent: before lines were set aside, a
        # 1,000-character goal and six 800-character lines left no packet at all ("prompt-unfit").
        smallest = settings.ANALYZE_PROMPT_MIN_BYTES
        for char in ("界", "😀"):
            with self.subTest(char=char):
                self.prepare()
                goal = char * 1000
                self.revision["goal"] = goal
                self.revision["lines"] = [{"text": char * 800, "source": "typed"}] * 6
                lines = reading.outcome_lines(self.revision)
                whole = self.call_prepare().prepared
                assert whole is not None
                self.assertEqual((), whole.inputs.unposed_lines)
                posed = reading_passes.plan_packets(
                    whole.originals,
                    goal=goal,
                    lines=lines,
                    protocol_prefix=reading_map_call.protocol_prefix(
                        goal, lines, ("goal", *(f"line_{n}" for n in range(1, 7)))
                    )
                    + reading_pass_context.goal_rule(whole.context),
                    max_bytes=smallest,
                    max_passes=16,
                    frozen_context=whole.context,
                    final=whole.final,
                )
                self.assertEqual(((), "prompt-unfit"), (posed.packets, posed.reason))
                self.assertFalse(reading_map_call.lines_fit(goal, lines, smallest))
                self.assertTrue(reading_map_call.lines_fit(goal, lines, 512 * 1024))

                prepared = self.call_prepare(prompt_bytes=smallest).prepared
                assert prepared is not None
                self.assertEqual(lines, prepared.inputs.unposed_lines)
                self.assertEqual((), reading.outcome_lines(prepared.inputs.revision))
                self.assertEqual([], prepared.context.value()["provenance"]["lines"])
                maps = reading_passes.plan_packets(
                    prepared.originals,
                    goal=goal,
                    lines=(),
                    protocol_prefix=reading_map_call.protocol_prefix(goal, (), ("goal",))
                    + reading_pass_context.goal_rule(prepared.context),
                    max_bytes=smallest,
                    max_passes=16,
                    frozen_context=prepared.context,
                    final=prepared.final,
                )
                self.assertTrue(maps.packets)
                self.assertEqual("complete", maps.reason)
                # The final packet fits the same prompt, and its answer says so per line.
                floor = reading_reconcile_packet.preflight(
                    prepared.originals,
                    goal=goal,
                    lines=(),
                    scope=prepared.scope,
                    scope_floor=prepared.floor,
                    final=prepared.final,
                    slot=reading_map_series.FinalSlot(17, smallest, reading.REPLY_CAP_BYTES),
                    frozen_context=prepared.context,
                )
                assert floor.packet is not None, floor.reason
                self.assertLessEqual(len(floor.packet.prompt.encode()), smallest)
                self.assertIn('"lines": []', floor.packet.prompt)
                criteria, reason = reading_final_call._resolve(
                    json.dumps({"goal": {"result": "consistent", "cites": [], "detail": ""}}),
                    floor.packet,
                    prepared.inputs,
                    prepared.context.value(),
                    240,
                    1_000,
                    800,
                )
                self.assertEqual("ok", reason)
                assert criteria is not None
                for n in range(1, 7):
                    row = criteria[f"line_{n}"]
                    self.assertEqual(reading.WHY_LINES_NO_ROOM, row["why"])
                    self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                    self.assertEqual(char * 800, row["clause"])
                # The store still holds the lines, and publication binds them to this job.
                entry: Any = {"revisions": [deepcopy(self.revision)]}
                self.assertTrue(reading_long_finalize._locked_intent(entry, prepared.context))

    def test_a_requested_line_set_aside_keeps_its_request_time(self) -> None:
        # A line the reader asked for, set aside at the smallest prompt, is still not judged by a
        # write made before the request, as the single prompt's `lines-no-room` lines are not.
        f = self.fixture
        rule = "No file under docs/ is edited."
        f.source.parent.write(f"{f.source.parent.cwd}/docs/guide.md")
        f.source.parent.prompt(rule)
        self.prepare()
        assert self.collection.evidence is not None
        requested = next(
            fact
            for fact in self.collection.evidence.facts
            if fact["type"] == "user_message" and fact["summary"] == rule
        )
        # The window opens before the write, so only the request time keeps it from the line.
        self.revision["goal_saved_at"] = self.revision["window_start"] = self.revision["at"]
        self.revision["at"] = requested["at"] + 1
        recovered = project_context._transcript_user_scan(
            f.source.config, f.source.path.read_bytes(), "claude", self.row["sid"]
        )
        request = reading.line_request_binding(
            recovered,
            source_id=requested["fact_id"],
            text=rule,
            harness="claude",
            sid=self.row["sid"],
            now=self.revision["at"],
        )
        assert request is not None
        goal = "界" * 1000
        self.revision["goal"] = goal
        self.revision["lines"] = [
            {
                "text": rule,
                "source": "entry",
                "source_id": requested["fact_id"],
                "request": request,
            },
            *[{"text": "界" * 800, "source": "typed"}] * 5,
        ]
        smallest = settings.ANALYZE_PROMPT_MIN_BYTES
        prepared = self.call_prepare(prompt_bytes=smallest, recovered_sources=recovered).prepared
        assert prepared is not None
        self.assertEqual(rule, prepared.inputs.unposed_lines[0])
        floor = reading_reconcile_packet.preflight(
            prepared.originals,
            goal=goal,
            lines=(),
            scope=prepared.scope,
            scope_floor=prepared.floor,
            final=prepared.final,
            slot=reading_map_series.FinalSlot(17, smallest, reading.REPLY_CAP_BYTES),
            frozen_context=prepared.context,
        )
        packet = floor.packet
        assert packet is not None, floor.reason
        reply = json.dumps({"goal": {"result": "consistent", "cites": [], "detail": ""}})

        def line_1(inputs: reading_final_call.Inputs) -> reading.Criterion:
            criteria, reason = reading_final_call._resolve(
                reply, packet, inputs, prepared.context.value(), 240, 1_000, 800
            )
            self.assertEqual("ok", reason)
            assert criteria is not None
            return criteria["line_1"]

        kept = line_1(prepared.inputs)
        self.assertEqual(reading.WHY_LINES_NO_ROOM, kept["why"])
        self.assertEqual(reading.RESULT_UNVERIFIABLE, kept["result"])
        self.assertEqual((), tuple(kept["cites"]))
        # Without the request time the earlier write would decide the line.
        lost = line_1(replace(prepared.inputs, unposed_rows=()))
        self.assertEqual(reading.RESULT_DEPARTURE, lost["result"])

    def test_lines_are_measured_with_the_context_a_packet_carries(self) -> None:
        # Lines that pass the measure before anything is frozen, and not once the frozen context
        # is added, are set aside on a second preparation rather than leaving no packet.
        self.prepare()
        calls: list[bool] = []
        fit = reading_map_call.lines_fit

        def measured(goal: str, lines: Any, prompt_bytes: int, context: Any = None) -> bool:
            calls.append(context is not None)
            return context is None and fit(goal, lines, prompt_bytes)

        with mock.patch.object(reading_map_call, "lines_fit", measured):
            prepared = self.call_prepare().prepared
        assert prepared is not None
        # Before freezing, with the context, then the second preparation sets the lines aside.
        self.assertEqual([False, True], calls)
        self.assertEqual(reading.outcome_lines(self.revision), prepared.inputs.unposed_lines)
        self.assertEqual((), reading.outcome_lines(prepared.inputs.revision))
        self.assertEqual([], prepared.context.value()["provenance"]["lines"])
        goal = prepared.inputs.revision["goal"]
        self.assertTrue(fit(goal, (), 512 * 1024, prepared.context))

    def test_missing_ambiguous_or_detached_origins_never_fall_back_to_clock(self) -> None:
        self.prepare()
        origins = self.collection.origins
        assert origins is not None
        for changed in (
            None,
            origins[:-1],
            (replace(origins[0], position=None, reason="ambiguous"), *origins[1:]),
            (replace(origins[0], fact_id="foreign"), *origins[1:]),
            (replace(origins[0], canonical_index=True), *origins[1:]),
        ):
            result = self.call_prepare(collection=replace(self.collection, origins=changed))
            self.assertEqual("original-order-unavailable", result.reason)
            self.assertIsNone(result.prepared)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_unknown_outside_window_origin_does_not_discard_eligible_originals(self) -> None:
        self.prepare()
        assert self.collection.evidence is not None
        earliest = min(self.collection.evidence.facts, key=lambda f: f["at"])
        self.revision["at"] = earliest["at"] + 1
        assert self.collection.origins is not None
        origins = tuple(
            replace(o, position=None, reason="ambiguous") if o.fact_id == earliest["fact_id"] else o
            for o in self.collection.origins
        )
        prepared = self.call_prepare(collection=replace(self.collection, origins=origins)).prepared
        assert prepared is not None
        self.assertIsNotNone(prepared)
        self.assertNotIn(earliest["fact_id"], [o.row["id"] for o in prepared.originals])

    def test_real_native_clock_rollback_keeps_collected_physical_order(self) -> None:
        self.prepare()
        rows = self.fixture.source.parent.rows
        rows[1]["timestamp"] = (
            dt.datetime.fromisoformat(rows[0]["timestamp"]) - dt.timedelta(seconds=10)
        ).isoformat()
        self.collection = self.fixture.source.collect()
        assert self.collection.evidence is not None
        self.revision["at"] = min(f["at"] for f in self.collection.evidence.facts)
        prepared = self.call_prepare().prepared
        assert prepared is not None
        self.assertIsNotNone(prepared)
        self.assertGreater(prepared.originals[0].row["at"], prepared.originals[1].row["at"])

    def test_eligibility_and_incomplete_source_stop_before_any_calls(self) -> None:
        self.prepare()
        self.assertEqual(reading.WITHHELD_DISCARDED, self.call_prepare(discarded=True).reason)
        self.assertEqual(reading.WITHHELD_NOTHING_TYPED, self.call_prepare(revisions=[]).reason)
        result = self.call_prepare(collection=replace(self.collection, source_verified=False))
        self.assertEqual("source-incomplete", result.reason)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_copied_correction_stays_derived_uncitable_after_mapping_and_resolution(self) -> None:
        prepared = self.prepare(copied=True).prepared
        assert prepared is not None
        original = next(o for o in prepared.originals if o.row["id"] == self.copied_id)
        self.assertEqual(reading.AUTHOR_DERIVED, original.row["author"])
        self.assertIn(self.copied_id, prepared.context.value()["settlement"]["uncitable"])
        original_factory = self.fixture.model_for

        def factory(ordinal: int) -> reading_policy.GuardedModel:
            guard = original_factory(ordinal)
            original_transport = guard.model

            def transport(prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
                original_transport(prompt, output_cap_bytes=output_cap_bytes)
                match = re.search(r"^\[(\d+)\] user_message.*Do not push", prompt, re.MULTILINE)
                self.assertIsNotNone(match)
                assert match is not None
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

        model_patch = mock.patch.object(self.fixture, "model_for", factory)
        model_patch.start()
        self.addCleanup(model_patch.stop)
        series, result = self.invoke(prepared)
        self.assertTrue(
            any(
                row["id"] == self.copied_id and row["author"] == reading.AUTHOR_DERIVED
                for packet in series.plan.packets
                for row in packet.selection.entries
            )
        )
        assert result.criteria is not None
        self.assertTrue(
            all(
                c.get("result") not in {reading.RESULT_CONSISTENT, reading.RESULT_DEPARTURE}
                for c in result.criteria.values()
            )
        )

    def test_copied_source_cannot_be_adopted_as_person_intent(self) -> None:
        self.prepare(copied=True)
        assert self.collection.evidence is not None
        copied = next(f for f in self.collection.evidence.facts if f["fact_id"] == self.copied_id)
        self.revision.update(
            goal="Do not push to main.", goal_source="chosen-prompt", goal_source_at=copied["at"]
        )
        result = self.call_prepare()
        self.assertEqual("adopted-goal-unavailable", result.reason)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_request_and_settlement_use_full_facts_and_freeze_before_mapping(self) -> None:
        self.prepare()
        assert self.collection.evidence is not None
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
        assert request is not None
        self.revision["lines"][0] = {
            "text": "Do not push to main.",
            "source": "entry",
            "source_id": requested["fact_id"],
            "request": request,
        }
        unbound = self.call_prepare(recovered_sources=()).prepared
        assert unbound is not None
        self.assertIsNone(unbound.context.value()["provenance"]["lines"][0]["requested_at"])
        prepared = self.call_prepare(
            settled_through=requested["at"], recovered_sources=recovered
        ).prepared
        assert prepared is not None
        automatic = self.call_prepare(settled_through=requested["at"]).prepared
        assert automatic is not None
        self.assertEqual(prepared.inputs.recovered_sources, automatic.inputs.recovered_sources)
        self.assertEqual(prepared.context, automatic.context)
        value = prepared.context.value()
        self.assertEqual(requested["at"], value["provenance"]["lines"][0]["requested_at"])
        self.assertIn(requested["fact_id"], value["settlement"]["uncitable"])
        self.revision["goal"] = "Changed after preparation."
        self.row["ended_at"] += 100
        self.assertEqual("Keep the retry safe.", prepared.inputs.revision["goal"])
        self.assertNotEqual(self.row["ended_at"], prepared.inputs.row["ended_at"])

    def test_unknown_enabled_ci_binding_is_a_frozen_gap_without_any_ci_lookup(self) -> None:
        self.prepare()
        self.route["ci_read"] = "on"
        collection = replace(
            self.collection,
            ancillary_info=replace(self.collection.ancillary_info, ci_binding="unknown"),
        )
        prepared = self.call_prepare(collection=collection).prepared
        assert prepared is not None
        self.assertIn("context", prepared.context.value()["safety"]["gaps"])
        series, result = self.invoke(prepared)
        self.assertIsNone(result.criteria)
        self.assertIsNone(
            reading_native.assessment(
                prepared, series, result, now=self.row["ended_at"] + 61, stamp_text="Fake"
            )
        )

    def test_missing_complete_message_words_refuses_before_calls(self) -> None:
        self.prepare()
        assert self.collection.words is not None
        collection = replace(self.collection, words=self.collection.words[1:])
        result = self.call_prepare(collection=collection)
        self.assertEqual("message-words-unavailable", result.reason)
        self.assertEqual(0, self.fixture.marker.fixture.spends())

    def test_known_missing_or_unfit_required_final_refuses_before_calls(self) -> None:
        self.prepare()
        assert self.collection.final is not None
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

    def test_formatter_refuses_a_detached_success_or_a_new_reassuring_partial(self) -> None:
        prepared = self.prepare().prepared
        assert prepared is not None
        series, result = self.invoke(prepared)
        self.assertEqual("resolved", result.state)

        def format_result(
            candidate: reading_final_call.Result, planned: reading_map_series.Series = series
        ) -> reading.Assessment | None:
            return reading_native.assessment(
                prepared, planned, candidate, now=self.row["ended_at"] + 61, stamp_text="Fake"
            )

        self.assertIsNotNone(format_result(result))
        assert result.packet is not None
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

    def test_unnamed_tool_destination_retains_full_record_but_sends_no_output(self) -> None:
        self.prepare()
        self.route["destination"] = ""
        prepared = self.call_prepare().prepared
        assert prepared is not None
        self.assertTrue(any(f["type"] == reading.TOOL_REPORT_TYPE for f in prepared.inputs.facts))
        assert prepared.inputs.tool_output is not None
        self.assertFalse(prepared.inputs.tool_output.tails)
        self.assertTrue(prepared.floor.checks_unsent)
        self.assertFalse(any(o.row["type"] == reading.TOOL_REPORT_TYPE for o in prepared.originals))
