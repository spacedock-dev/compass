"""One final slot uses original evidence and the existing resolver, never hypotheses."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from compass_runtime import (
    analyze_capacity,
    analyze_diagnostics,
    reading,
    reading_final_call,
    reading_long_diagnostics,
    reading_long_inspection,
    reading_map_call,
    reading_map_series,
    reading_passes,
    reading_policy,
    reading_reconcile_packet,
)

from . import test_reading_map_series as series_tests
from . import test_reading_source_final as source_tests
from .test_agent_words import _check, _person


class FinalCallTest(unittest.TestCase):
    def setUp(self):
        self.module = reading_final_call
        self.fixture = series_tests.MapSeriesTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.declared.update(max_evidence_passes=16, max_calls=17)
        self.fixture.declared["limits"].update(
            prompt_bytes=20000, input_bytes=340000, output_bytes=139264
        )
        self.fixture.begin()
        self.calls = []
        self.factories = []
        self.raw = json.dumps({"line_1": {"result": "consistent", "cites": [2], "detail": ""}})
        self.status = "ok"
        self.stop = None
        self.failure = None
        self.final = {"outcome": "none"}
        self.after_transport = None
        self.before_invoke = None
        self.output = reading.ToolOutput("test", "test")
        self.recovered = ()
        self.settled_through = None
        self.open_call_at = None
        self.scope = reading.SCOPE_FINAL
        self.goal_status = None
        self.message_words = ()
        self.facts = [
            _person("rule", 100, "The tests pass"),
            _check(fact_id="middle", at=110, result="passed"),
        ]
        self.row = {"harness": "claude", "sid": "s1", "ended_at": 200, "state": "idle"}
        self.revision = {
            "n": 1,
            "at": 100,
            "goal": "Keep the retry safe.",
            "lines": [{"text": "The tests pass", "source": "typed"}],
        }

    def prepare(self, *, single_maps=False):
        self.inputs = self.module.Inputs(
            self.row,
            self.revision,
            tuple(self.facts),
            self.output,
            self.recovered,
            self.settled_through,
            self.open_call_at,
            self.message_words,
        )
        self.floor = self.module.scope_floor(self.inputs, scope=self.scope)
        ledger = self.floor.entries
        words = {
            f["fact_id"]: f.get(reading.WORDS_FIELD, f.get(reading.AGENT_WORDS_FIELD))
            for f in self.facts
        }
        words.update({w.fact_id: w.words for w in self.message_words if w.state == "whole"})
        self.originals = [reading_passes.Original(row, words[row["id"]]) for row in ledger]
        self.context = self.module.freeze_context(
            self.inputs,
            self.floor,
            scope=self.scope,
            source_complete=True,
            goal_status=self.goal_status,
        )
        if single_maps:
            self.series = self.single_map_series()
            return
        self.series = reading_map_series.run(
            self.originals,
            goal=self.revision["goal"],
            lines=reading.outcome_lines(self.revision),
            clauses=("goal", "line_1"),
            plan=self.fixture.declared,
            model_for=self.fixture.model_for,
            stop_reason=lambda: None,
            on_observation=self.fixture.observe,
            frozen_context=self.context,
        )

    def single_map_series(self):
        # Real individual invocation owners, each with one distinct original and local #1.
        # Grouping is deliberate test setup; range planning has its own integration tests.
        packets, passes, observations, failed = [], [], [], []
        index = reading_map_series.CandidateIndex()
        for ordinal, original in enumerate(self.originals, 1):
            snapshots = []

            def observe(diagnostic, snapshots=snapshots, ordinal=ordinal):
                snapshots.append(diagnostic)
                self.fixture.observe(
                    {
                        "observation": {
                            "version": 1,
                            "ordinal": ordinal,
                            "kind": "evidence",
                            "diagnostic": diagnostic,
                        },
                        "ended": False,
                    }
                )

            call = reading_map_call.invoke(
                [original],
                goal=self.revision["goal"],
                lines=reading.outcome_lines(self.revision),
                clauses=("goal", "line_1"),
                max_bytes=20000,
                model=self.fixture.model_for(ordinal),
                frozen_context=self.context,
                on_diagnostic=observe,
            )
            packet = call.plan.packets[0]
            packets.append(packet)
            index = index.add(ordinal, call.reply)
            if ordinal in index.unresolved_ordinals:
                failed.extend(packet.primary)
            event = {
                "observation": {
                    "version": 1,
                    "ordinal": ordinal,
                    "kind": "evidence",
                    "diagnostic": call.diagnostic,
                },
                "ended": True,
            }
            self.assertTrue(self.fixture.observe(event))
            observations.append(event)
            passes.append(
                reading_map_series.EvidencePass(
                    ordinal, packet, call.state, call.reason, tuple(snapshots)
                )
            )
        return reading_map_series.Series(
            "unresolved" if failed else "passes-ended",
            reading_passes.PacketPlan(
                tuple(packets), (), "complete", sum(len(p.prompt.encode()) for p in packets), 0
            ),
            tuple(passes),
            index,
            (),
            tuple(failed),
            tuple(observations),
            reading_map_series.FinalSlot(17, 20000, 8192),
            self.context,
        )

    def model_for(self, ordinal):
        self.factories.append(ordinal)
        if self.failure:
            raise self.failure

        def reserve(prompt, cap):
            self.assertEqual(8192, cap)
            request = self.fixture.fixture.request(self.fixture.owner, ordinal)
            request.update(
                kind="reconciliation",
                max_evidence_passes=16,
                prompt_bytes=len(prompt.encode()),
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            )
            return self.fixture.markers.reserve(
                self.fixture.fixture.config, self.fixture.owner, request=request, now=100
            )

        def transport(prompt, *, output_cap_bytes):
            self.calls.append((ordinal, prompt, output_cap_bytes))
            if self.after_transport:
                self.after_transport()
            return self.raw, self.status

        return reading_policy.GuardedModel(
            self.fixture.fixture.config,
            transport,
            lambda: 100,
            provider="claude",
            reserve_prompt=reserve,
            before_invoke=self.before_invoke,
            admit_prompt=analyze_capacity.Admission(
                "codex", "unknown", "", requested_maximum=20000
            ),
        )

    def invoke(self):
        return self.module.run(
            self.originals,
            self.series,
            inputs=self.inputs,
            scope_floor=self.floor,
            final=self.final,
            plan=self.fixture.declared,
            model_for=self.model_for,
            stop_reason=lambda: self.stop,
            on_observation=self.fixture.observe,
            detail_cap_chars=240,
        )

    def test_reserved_seventeenth_slot_cites_original_middle_and_preserves_map_accounting(self):
        self.prepare()
        map_bytes = self.series.plan.transmitted_bytes
        result = self.invoke()
        self.assertEqual("resolved", result.state)
        self.assertEqual([17], self.factories)
        self.assertEqual(2, self.fixture.fixture.spends())
        self.assertEqual(("middle",), result.criteria["line_1"]["cites"])
        self.assertEqual(reading.RESULT_CONSISTENT, result.criteria["line_1"]["result"])
        self.assertEqual(result.packet.prompt, self.calls[0][1])
        self.assertEqual(8192, self.calls[0][2])
        self.assertEqual(3, len(result.snapshots))
        self.assertEqual([1, 17], [s["observation"]["ordinal"] for s in result.observations])
        self.assertEqual("reconciliation", result.observations[-1]["observation"]["kind"])
        self.assertTrue(result.observations[-1]["ended"])
        self.assertEqual(map_bytes, self.series.plan.transmitted_bytes)
        self.assertEqual("active", self.fixture.fixture.loaded(self.fixture.owner)["state"])

    def test_failed_map_and_always_consistent_final_cannot_make_a_verdict(self):
        self.fixture.responses[1] = ("not JSON", "ok")
        self.prepare()
        result = self.invoke()
        self.assertEqual("unresolved", result.state)
        self.assertIn("map-unresolved", result.unresolved)
        self.assertIsNone(result.criteria)
        self.assertEqual(2, self.fixture.fixture.spends())

    def test_three_pass_local_one_citation_becomes_fresh_middle_number_two(self):
        self.facts.append(_person("later", 120, "Preserve the original evidence."))
        self.prepare(single_maps=True)
        result = self.invoke()
        self.assertEqual([1, 2, 3], [p.ordinal for p in self.series.passes])
        self.assertTrue(
            all(
                p.packet.selection.by_index()[1]["id"] == o.row["id"]
                for p, o in zip(self.series.passes, self.originals, strict=True)
            )
        )
        self.assertEqual(("middle",), result.criteria["line_1"]["cites"])
        self.assertEqual(4, self.fixture.fixture.spends())
        self.assertEqual([1, 2, 3, 17], [o["observation"]["ordinal"] for o in result.observations])

    def test_failed_middle_pass_followed_by_usable_pass_still_withholds_consistent_final(self):
        self.facts.append(_person("later", 120, "Preserve the original evidence."))
        self.fixture.responses[2] = ("malformed", "ok")
        self.prepare(single_maps=True)
        result = self.invoke()
        self.assertEqual([1, 3], [c.ordinal for c in self.series.index.entries])
        self.assertEqual(["middle"], [s.fact_id for s in self.series.failed_primary])
        self.assertIsNone(result.criteria)
        self.assertIn("map-unresolved", result.unresolved)
        self.assertEqual(4, self.fixture.fixture.spends())
        self.assertEqual("unresolved", result.state)

    def test_factory_failure_preserves_prior_charge_without_called_final_observation(self):
        self.prepare()
        self.failure = OSError("private factory text")
        result = self.invoke()
        self.assertEqual("factory-failed", result.state)
        self.assertEqual(1, self.fixture.fixture.spends())
        self.assertEqual([], self.calls)
        self.assertEqual(2, len(result.snapshots))
        self.assertIsNone(result.snapshots[-1]["input"])
        self.assertFalse(result.observations[-1]["ended"])
        self.assertNotIn("private factory text", repr(result))

    def test_omitted_atomic_original_from_full_facts_refuses_before_final_charge(self):
        self.prepare()
        self.originals = self.originals[:1]
        result = self.invoke()
        self.assertEqual("local-unfit", result.state)
        self.assertIsNone(result.criteria)
        self.assertEqual(1, self.fixture.fixture.spends())
        self.assertEqual([], self.factories)

    def test_actual_tool_output_change_cannot_use_a_stale_map_safety_floor(self):
        self.prepare()
        self.inputs = replace(
            self.inputs,
            tool_output=replace(
                self.inputs.tool_output,
                changed_after=frozenset({("call-1", self.facts[1]["summary"])}),
            ),
        )
        result = self.invoke()
        self.assertEqual("local-unfit", result.state)
        self.assertEqual(1, self.fixture.fixture.spends())

    def test_failed_final_settlement_keeps_charge_without_publishable_criteria(self):
        self.prepare()
        self.fixture.fail_settlement = "raises"
        result = self.invoke()
        self.assertEqual("persistence-unresolved", result.state)
        self.assertIsNone(result.criteria)
        self.assertEqual(2, self.fixture.fixture.spends())
        self.assertEqual(1, len(self.calls))
        self.assertFalse(result.observations[-1]["ended"])
        self.assertTrue(result.snapshots[-1]["input"]["attempt_reserved"])
        self.assertEqual(
            "charged", self.fixture.fixture.loaded(self.fixture.owner)["passes"][-1]["state"]
        )
        self.assertNotIn("private persistence detail", repr(result))

    def test_cancelled_deadline_or_paused_before_final_factory_cost_nothing_more(self):
        self.prepare()
        for stopped in ("cancelled", "job-deadline", "paused"):
            self.stop = stopped
            result = self.invoke()
            self.assertEqual(stopped, result.state)
            self.assertIsNone(result.criteria)
            self.assertEqual([], self.factories)
            self.assertEqual(1, self.fixture.fixture.spends())

    def test_named_unavailable_final_is_coverage_gap_not_unreadable_reply(self):
        self.prepare()
        self.final = None
        result = self.invoke()
        self.assertEqual("unresolved", result.state)
        self.assertEqual("coverage-incomplete", result.reason)
        self.assertIn("final-unavailable", result.unresolved)
        self.assertIsNone(result.criteria)

    def test_cancellation_after_successful_transport_retains_charge_but_not_criteria(self):
        self.prepare()
        self.after_transport = lambda: setattr(self, "stop", "cancelled")
        result = self.invoke()
        self.assertEqual("cancelled", result.state)
        self.assertIsNone(result.criteria)
        self.assertEqual(2, self.fixture.fixture.spends())
        self.assertEqual(1, len(self.calls))

    def test_original_metadata_cannot_differ_from_full_frozen_fact(self):
        self.prepare()
        self.originals[1] = replace(
            self.originals[1], row={**self.originals[1].row, "result": "failed"}
        )
        result = self.invoke()
        self.assertEqual("local-unfit", result.state)
        self.assertEqual([], self.factories)

    def test_successful_transport_with_invalid_json_has_no_criteria_and_keeps_charge(self):
        self.prepare()
        self.raw = "private invalid reply"
        result = self.invoke()
        self.assertEqual("parse-failed", result.state)
        self.assertIsNone(result.criteria)
        self.assertEqual(2, self.fixture.fixture.spends())
        self.assertNotIn(self.raw, repr(result))

    def test_foreign_menu_number_cannot_resolve_to_original_or_publish_detail(self):
        self.prepare()
        self.raw = json.dumps(
            {"line_1": {"result": "consistent", "cites": [999], "detail": "Unbound detail."}}
        )
        result = self.invoke()
        self.assertNotEqual(reading.RESULT_CONSISTENT, result.criteria["line_1"].get("result"))
        self.assertEqual((), result.criteria["line_1"]["cites"])
        self.assertNotIn("Unbound detail.", repr(result))

    def test_final_unfit_never_constructs_a_guard_or_charges(self):
        self.prepare()
        self.fixture.declared["limits"]["prompt_bytes"] = 200
        self.series = replace(
            self.series, final_slot=replace(self.series.final_slot, prompt_bytes=200)
        )
        result = self.invoke()
        self.assertEqual("local-unfit", result.state)
        self.assertEqual("prompt-unfit", result.reason)
        self.assertEqual([], self.factories)
        self.assertEqual(1, self.fixture.fixture.spends())

    def test_postcharge_refusal_never_calls_transport_or_retries(self):
        self.prepare()

        def refuse():
            raise reading_policy.RefusedError({"reason": "private late refusal"})

        self.before_invoke = refuse
        result = self.invoke()
        self.assertEqual("refused", result.state)
        self.assertEqual([], self.calls)
        self.assertEqual([17], self.factories)
        self.assertEqual(2, self.fixture.fixture.spends())
        self.assertTrue(result.snapshots[-1]["input"]["attempt_reserved"])
        self.assertFalse(result.snapshots[-1]["input"]["model_invoked"])
        self.assertNotIn("private late refusal", repr(result))

    def test_no_stored_reading_enters_prompt_and_recorded_owner_receives_all_facts(self):
        self.row["assessment"] = {"detail": "STORED_READING_CANARY"}
        self.prepare()
        with mock.patch.object(reading, "recorded_from", wraps=reading.recorded_from) as record:
            result = self.invoke()
        self.assertEqual(tuple(self.facts), record.call_args.args[0])
        self.assertEqual(self.inputs.tool_output, record.call_args.kwargs["tool_output"])
        self.assertNotIn("STORED_READING_CANARY", result.packet.prompt)

    def test_verified_request_floor_keeps_earlier_failed_action_from_later_line(self):
        text = "Write the result as JSON"
        source = {
            **_person("request", 120, text),
            "request_source_digest": "a" * 64,
            "request_words_digest": reading._request_digest(text),
        }
        self.facts = [_check(fact_id="early", at=110, result_at=130, result="failed"), source]
        self.revision.update(
            at=200,
            window_start=100,
            lines=[
                {
                    "text": text,
                    "source": "entry",
                    "source_id": "request",
                    "request": reading.line_request_binding(
                        [source],
                        source_id="request",
                        text=text,
                        harness="claude",
                        sid="s1",
                        now=200,
                    ),
                }
            ],
        )
        self.row["ended_at"] = 300
        self.recovered = (source,)
        self.prepare()
        self.assertEqual(120, self.context.value()["provenance"]["lines"][0]["requested_at"])
        self.raw = json.dumps(
            {
                "line_1": {
                    "result": "departure",
                    "cites": [1],
                    "detail": "The recorded attempt used CSV.",
                }
            }
        )
        result = self.invoke()
        self.assertEqual(reading.RESULT_UNVERIFIABLE, result.criteria["line_1"]["result"])

    def test_changed_request_proof_is_refused_before_final_charge(self):
        self.prepare()
        changed = {**self.revision, "at": 101}
        self.inputs = replace(self.inputs, revision=changed)
        result = self.invoke()
        self.assertEqual("invalid-context", result.reason)
        self.assertEqual(1, self.fixture.fixture.spends())

    def test_settled_direction_remains_uncitable_and_open_call_comes_from_frozen_scope(self):
        self.facts.append(_person("correction", 120, "Use the later direction."))
        self.row.update(state="working", ended_at=None)
        self.scope = reading.SCOPE_MID_FLIGHT
        self.open_call_at = 125
        self.settled_through = 130
        self.prepare()
        self.raw = json.dumps(
            {
                "goal": {
                    "result": "departure",
                    "cites": [3],
                    "detail": "The reader changed direction.",
                }
            }
        )
        with mock.patch.object(reading, "resolve", wraps=reading.resolve) as resolver:
            result = self.invoke()
        self.assertEqual(frozenset({"correction"}), resolver.call_args.kwargs["uncitable"])
        self.assertEqual(125, resolver.call_args.kwargs["open_call_at"])
        self.assertNotIn("correction", result.criteria["goal"]["cites"])
        self.assertNotEqual(reading.RESULT_DEPARTURE, result.criteria["goal"].get("result"))

    def collected_check(self, history, write_after):
        collected = source_tests.RetainedStrictFinalTest()
        collected.setUp()
        self.addCleanup(collected.doCleanups)
        for outcome in history:
            collected.parent.bash(
                "pytest tests/retry.py", f"1 {outcome}", is_error=outcome == "failed"
            )
        if write_after:
            collected.parent.write("src/retry.py")
        collection = collected.collect()
        self.facts = list(collection.evidence.facts)
        self.output = source_tests.source_tests.CompleteReadingSourceTest.output(
            collection.evidence.press
        )
        self.row["sid"] = source_tests.SHORT
        self.row["ended_at"] = max(f["at"] for f in self.facts) + 100
        self.revision["window_start"] = 1
        self.final = collection.final
        self.prepare()
        # Every atomic original is mandatory; its final number comes from the fresh menu.
        number = next(
            i
            for i, o in reversed(list(enumerate(self.originals, 1)))
            if o.row.get("subject") == reading.CHECK_SUBJECT
        )
        self.raw = json.dumps({"line_1": {"result": "consistent", "cites": [number], "detail": ""}})
        return self.invoke()

    def test_actual_collected_rerun_and_later_write_use_tool_output_guards(self):
        result = self.collected_check(("failed", "passed"), True)
        self.assertEqual(reading.RESULT_UNVERIFIABLE, result.criteria["line_1"]["result"])

    def test_actual_collected_failed_then_passed_check_uses_existing_rerun_policy(self):
        result = self.collected_check(("failed", "passed"), False)
        self.assertEqual(reading.RESULT_CONSISTENT, result.criteria["line_1"]["result"])

    def test_actual_collected_passed_then_failed_check_cannot_reassure(self):
        result = self.collected_check(("passed", "failed"), False)
        self.assertNotEqual(reading.RESULT_CONSISTENT, result.criteria["line_1"].get("result"))

    def test_legacy_saved_output_uses_existing_outcome_line_semantics(self):
        self.revision.pop("lines")
        self.revision["output"] = "The tests pass"
        self.prepare()
        result = self.invoke()
        self.assertEqual(reading.RESULT_CONSISTENT, result.criteria["line_1"]["result"])

    def test_final_observation_merges_without_changing_map_byte_totals(self):
        self.prepare()
        result = self.invoke()
        before = reading_long_diagnostics.derive(plan=self.fixture.declared, series=self.series)
        combined = reading_long_diagnostics.derive(
            plan=self.fixture.declared,
            series=self.series,
            reconciliation_observations=list(result.observations[-1:]),
            inspected=reading_long_inspection.inspect(
                self.fixture.fixture.config, self.fixture.owner.live.prepared.job_id, now=100
            ),
        )
        self.assertEqual(before["maps"], combined["maps"])
        self.assertEqual([1, 17], [s["observation"]["ordinal"] for s in combined["observations"]])
        self.assertIsNone(combined["complete"])
        self.assertEqual(2, combined["accounting"]["totals"]["calls"])

    def test_uncharged_actual_guard_consent_refusal_preserves_the_map_charge(self):
        self.prepare()
        reading_policy.set_consent(self.fixture.fixture.config, False, now=100)
        result = self.invoke()
        self.assertEqual("refused", result.state)
        self.assertEqual([], self.calls)
        self.assertEqual(1, self.fixture.fixture.spends())
        self.assertFalse(result.snapshots[-1]["input"]["attempt_reserved"])

    def test_factory_refusal_has_no_final_attempt_or_raw_reason(self):
        self.prepare()
        self.failure = reading_policy.RefusedError({"reason": "PRIVATE_FACTORY_REASON"})
        result = self.invoke()
        self.assertEqual("factory-refused", result.state)
        self.assertIsNone(result.snapshots[-1]["input"])
        self.assertEqual(1, self.fixture.fixture.spends())
        self.assertNotIn("PRIVATE_FACTORY_REASON", repr(result))

    def test_final_transport_failure_is_charged_once_without_retry_or_criteria(self):
        self.prepare()
        self.status = "timeout"
        result = self.invoke()
        self.assertEqual("model-failed", result.state)
        self.assertIsNone(result.criteria)
        self.assertEqual([17], self.factories)
        self.assertEqual(1, len(self.calls))
        self.assertEqual(2, self.fixture.fixture.spends())

    def test_capture_begins_before_owned_packet_build_and_excludes_model_factory_latency(self):
        self.prepare()
        clock = [0.0]
        build = reading_reconcile_packet.build
        factory = self.model_for

        def build_packet(*args, **kwargs):
            latest = self.fixture.events[-1]["observation"]
            self.assertEqual("reconciliation", latest["kind"])
            self.assertIsNone(latest["diagnostic"]["prepared"])
            clock[0] += 0.025
            return build(*args, **kwargs)

        def make_model(ordinal):
            clock[0] += 100
            return factory(ordinal)

        self.model_for = make_model
        with (
            mock.patch.object(
                analyze_diagnostics, "time", SimpleNamespace(monotonic=lambda: clock[0])
            ),
            mock.patch.object(reading_reconcile_packet, "build", side_effect=build_packet),
        ):
            result = self.invoke()
        self.assertEqual(25, result.snapshots[1]["prepared"]["build_elapsed_ms"])

    def test_original_successful_forbidden_command_retains_existing_departure_policy(self):
        self.revision["lines"] = [{"text": "Do not push to main", "source": "typed"}]
        self.facts[1] = _check(
            fact_id="push",
            at=110,
            result="passed",
            subject=reading.COMMAND_SUBJECT,
            summary="git push origin main",
        )
        self.prepare()
        self.raw = json.dumps(
            {
                "line_1": {
                    "result": "departure",
                    "cites": [2],
                    "detail": "The command pushed to main.",
                }
            }
        )
        result = self.invoke()
        self.assertEqual(reading.RESULT_DEPARTURE, result.criteria["line_1"]["result"])
        self.assertEqual(("push",), result.criteria["line_1"]["cites"])

    def test_adopted_goal_metadata_cannot_promote_an_unrestored_goal_into_whole_proof(self):
        self.revision.update(goal_source="chosen-prompt", goal_source_at=100)
        self.goal_status = "whole"
        self.prepare()
        result = self.invoke()
        self.assertIsNone(result.criteria)
        self.assertIn("adopted-goal-unavailable", result.unresolved)
        self.assertEqual([], self.factories)
        self.assertEqual(1, self.fixture.fixture.spends())
