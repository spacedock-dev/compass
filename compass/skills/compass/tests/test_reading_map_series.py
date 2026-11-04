"""Ordered private evidence passes with real Guard/marker reservations and fake transport."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    analyze_capacity,
    analyze_diagnostics,
    reading,
    reading_map_call,
    reading_map_series,
    reading_passes,
    reading_policy,
)

from . import test_reading_long_markers as marker_tests
from .test_agent_words import _agent
from .test_reading_long_jobs import binding


class MapSeriesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = reading_map_series
        self.fixture = marker_tests.LongMarkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.markers = self.fixture.module()
        self.calls: list[tuple[int, str, int]] = []
        self.factories: list[int] = []
        self.responses: dict[int, tuple[str, str]] = {}
        self.events: list[dict[str, Any]] = []
        self.refuse = 0
        self.stop = None
        self.fail_settlement = None
        self.declared = binding()["plan"]
        self.declared["limits"].update(
            prompt_bytes=2400, input_bytes=9600, reply_bytes=8192, output_bytes=32768
        )

    def begin(self):
        prepared = reading_policy.prepare_long_job(
            permission=self.fixture.permission,
            binding=binding(plan=self.declared),
            call_timeout_ms=200,
            clock=lambda: 0.0,
        )
        self.owner = self.markers.begin(
            self.fixture.config, permission=self.fixture.permission, job=prepared, now=100
        )

    def originals(self, count=3):
        # Each complete row exactly fills one packet, so another row cannot start in it.
        originals = []
        for ordinal in range(1, count + 1):
            words = f"Evidence {ordinal:02} 界🙂. "
            row = reading.build_ledger(
                [_agent(f"a{ordinal:02}", 100.0 + ordinal, words)],
                "claude",
                "s1",
                read_agent_words=True,
            )[0]
            original = reading_passes.Original(row, words)
            for _ in range(4):
                probe = reading_map_call.invoke(
                    [original],
                    goal="Frozen goal.",
                    lines=("Frozen line.",),
                    clauses=("goal", "line_1"),
                    max_bytes=10000,
                    model=lambda *_a, **_k: ('{"version":1,"candidates":[]}', "ok"),
                )
                used = len(probe.plan.packets[0].prompt.encode())
                original = replace(
                    original, words=words + "x" * (len(original.words) - len(words) + 2400 - used)
                )
            originals.append(original)
        return originals

    def candidate(self, ordinal, kind="supports"):
        return {"clause": "line_1", "kind": kind, "cites": [1], "detail": f"Observation {ordinal}."}

    def model_for(self, ordinal):
        self.factories.append(ordinal)
        if ordinal == self.refuse:
            reading_policy.set_consent(self.fixture.config, False, now=100)

        def reserve(prompt, cap):
            self.assertEqual(8192, cap)
            request = self.fixture.request(self.owner, ordinal)
            request.update(
                kind="evidence",
                max_evidence_passes=self.declared["max_evidence_passes"],
                prompt_bytes=len(prompt.encode()),
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            )
            return self.markers.reserve(self.fixture.config, self.owner, request=request, now=100)

        def transport(prompt, *, output_cap_bytes):
            self.calls.append((ordinal, prompt, output_cap_bytes))
            return self.responses.get(
                ordinal,
                (
                    json.dumps(
                        {
                            "version": 1,
                            "candidates": [
                                self.candidate(ordinal, "departs" if ordinal == 2 else "supports")
                            ],
                        }
                    ),
                    "ok",
                ),
            )

        return reading_policy.GuardedModel(
            self.fixture.config,
            transport,
            lambda: 100,
            provider="claude",
            reserve_prompt=reserve,
            admit_prompt=analyze_capacity.Admission("codex", "unknown", "", requested_maximum=2400),
        )

    def observe(self, event):
        self.events.append(event)
        observation = event["observation"]
        if event["ended"] and self.fail_settlement:
            if self.fail_settlement == "raises":
                raise OSError("private persistence detail")
            return False
        marked = self.fixture.loaded(self.owner)["passes"]
        if any(slot["request"]["ordinal"] == observation["ordinal"] for slot in marked):
            method = self.markers.settle if event["ended"] else self.markers.observe
            return method(self.fixture.config, self.owner, observation=observation, now=100)
        return True  # Preparation/uncharged refusal remains staged outside marker slots.

    def run_series(self, originals=None):
        self.begin()
        return self.module.run(
            self.originals() if originals is None else originals,
            goal="Frozen goal.",
            lines=("Frozen line.",),
            clauses=("goal", "line_1"),
            plan=self.declared,
            model_for=self.model_for,
            stop_reason=lambda: self.stop,
            on_observation=self.observe,
        )

    def test_three_passes_keep_decisive_middle_original_and_exact_frozen_intent(self):
        planner = reading_passes.plan_packets
        originals = self.originals()
        with mock.patch.object(reading_passes, "plan_packets", wraps=planner) as plans:
            result = self.run_series(originals)
        self.assertEqual(1, plans.call_count)
        self.assertEqual([1, 2, 3], self.factories)
        self.assertEqual(3, self.fixture.spends())
        self.assertEqual(3, len(result.passes))
        self.assertEqual(
            ["a01", "a02", "a03"],
            [item.candidate.cites[0].span.fact_id for item in result.index.entries],
        )
        self.assertEqual("departs", result.index.entries[1].candidate.kind)
        self.assertEqual((), result.failed_primary)
        self.assertEqual((), result.unassigned_primary)
        self.assertEqual(
            (4, 2400, 8192),
            (
                result.final_slot.ordinal,
                result.final_slot.prompt_bytes,
                result.final_slot.reply_bytes,
            ),
        )
        for observed, (_, prompt, cap), original in zip(
            result.passes, self.calls, originals, strict=True
        ):
            self.assertEqual(observed.packet.prompt, prompt)
            self.assertEqual(8192, cap)
            self.assertEqual(2400, len(prompt.encode()))
            self.assertIn("Frozen goal.", prompt)
            self.assertIn("Frozen line.", prompt)
            self.assertEqual(original.row["id"], observed.packet.primary[0].fact_id)
            self.assertEqual(
                (0, len(original.words)),
                (observed.packet.primary[0].start, observed.packet.primary[0].end),
            )
            self.assertEqual(3, len(observed.snapshots))
            self.assertIsNone(observed.snapshots[0]["input"])
            self.assertIsNone(observed.snapshots[1]["input"])
            self.assertTrue(observed.snapshots[2]["input"]["attempt_reserved"])
        self.assertEqual(3, len(result.observations))
        self.assertTrue(all(slot["ended"] for slot in result.observations))
        self.assertEqual("active", self.fixture.loaded(self.owner)["state"])

    def test_failed_middle_slot_does_not_retry_or_hide_later_original(self):
        self.responses[2] = ("", "error")
        result = self.run_series()
        self.assertEqual([1, 2, 3], self.factories)
        self.assertEqual(
            ["a01", "a03"], [e.candidate.cites[0].span.fact_id for e in result.index.entries]
        )
        self.assertEqual(["a02"], [s.fact_id for s in result.failed_primary])
        self.assertEqual((2,), result.index.unresolved_ordinals)
        self.assertEqual("model-failed", result.passes[1].state)
        self.assertEqual(3, self.fixture.spends())

    def test_malformed_middle_slot_is_unresolved_even_when_later_reply_is_usable(self):
        self.responses[2] = ('{"version":1,"candidates":[{"fact_id":"foreign"}]}', "ok")
        result = self.run_series()
        self.assertEqual("parse-failed", result.passes[1].state)
        self.assertEqual([1, 3], [e.ordinal for e in result.index.entries])
        self.assertEqual((2,), result.index.unresolved_ordinals)
        self.assertEqual(["a02"], [s.fact_id for s in result.failed_primary])

    def test_last_uncharged_refusal_has_its_own_diagnostic_after_earlier_charges(self):
        self.refuse = 3
        result = self.run_series()
        self.assertEqual(2, self.fixture.spends())
        self.assertEqual([1, 2], [ordinal for ordinal, _, _ in self.calls])
        self.assertEqual("refused", result.passes[2].state)
        self.assertFalse(result.passes[2].snapshots[-1]["input"]["attempt_reserved"])
        self.assertTrue(result.passes[0].snapshots[-1]["input"]["attempt_reserved"])
        self.assertEqual((3,), result.index.unresolved_ordinals)

    def test_cancellation_between_calls_keeps_preplanned_uninvoked_ranges(self):
        factory = self.model_for

        def model_for(ordinal):
            model = factory(ordinal)
            self.stop = "cancelled"
            return model

        self.model_for = model_for
        result = self.run_series()
        self.assertEqual([1], self.factories)
        self.assertEqual("cancelled", result.reason)
        self.assertEqual(["a02", "a03"], [s.fact_id for s in result.unassigned_primary])
        self.assertEqual(1, self.fixture.spends())

    def test_end_observation_failure_stops_before_next_slot_and_keeps_charge_unresolved(self):
        self.fail_settlement = "false"
        result = self.run_series()
        self.assertEqual("persistence-unresolved", result.reason)
        self.assertEqual([1], self.factories)
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual((), result.index.entries)
        self.assertEqual((1,), result.index.unresolved_ordinals)
        self.assertEqual(["a01"], [s.fact_id for s in result.failed_primary])
        self.assertEqual(["a02", "a03"], [s.fact_id for s in result.unassigned_primary])
        self.assertFalse(result.observations[0]["ended"])
        self.assertTrue(result.passes[0].snapshots[-1]["input"]["attempt_reserved"])
        self.assertEqual("charged", self.fixture.loaded(self.owner)["passes"][0]["state"])

    def test_end_observation_exception_is_closed_and_never_retried(self):
        self.fail_settlement = "raises"
        result = self.run_series()
        self.assertEqual("persistence-unresolved", result.reason)
        self.assertEqual([1], self.factories)
        self.assertEqual(1, self.fixture.spends())
        self.assertNotIn("private persistence detail", repr(result))
        self.assertEqual((1,), result.index.unresolved_ordinals)

    def test_sixteen_evidence_positions_keep_the_seventeenth_final_slot_and_remaining_range(self):
        self.declared.update(max_evidence_passes=16, max_calls=17)
        self.declared["limits"].update(input_bytes=17 * 2400, output_bytes=17 * 8192)
        result = self.run_series(self.originals(17))
        self.assertEqual(list(range(1, 17)), self.factories)
        self.assertEqual(16, self.fixture.spends())
        self.assertEqual("pass-limit", result.reason)
        self.assertEqual(17, result.final_slot.ordinal)
        self.assertEqual(["a17"], [s.fact_id for s in result.unassigned_primary])
        self.assertEqual(16, len(result.index.entries))

    def test_input_allocation_keeps_the_full_final_prompt_before_partial_evidence_fit(self):
        self.declared["limits"]["input_bytes"] = 2400 + 4200
        result = self.run_series()
        self.assertLessEqual(result.plan.transmitted_bytes, 4200)
        self.assertEqual("input-limit", result.reason)
        self.assertEqual(2, len(self.calls))
        self.assertEqual(2, self.fixture.spends())
        self.assertTrue(result.unassigned_primary)
        self.assertEqual(2400, result.final_slot.prompt_bytes)

    def test_reply_allocation_keeps_the_final_reply_without_relabeling_its_position(self):
        self.declared["limits"]["output_bytes"] = 2 * 8192
        result = self.run_series()
        self.assertEqual([1], self.factories)
        self.assertEqual(4, result.final_slot.ordinal)
        self.assertEqual(8192, result.final_slot.reply_bytes)
        self.assertEqual(["a02", "a03"], [s.fact_id for s in result.unassigned_primary])

    def test_index_overflow_retains_earlier_contradictions_and_marks_overflow_pass_unresolved(self):
        self.declared.update(max_evidence_passes=5, max_calls=6)
        self.declared["limits"].update(input_bytes=6 * 2400, output_bytes=6 * 8192)
        for ordinal in range(1, 6):
            self.responses[ordinal] = (
                json.dumps(
                    {
                        "version": 1,
                        "candidates": [
                            {
                                **self.candidate(ordinal, "departs" if n % 2 else "supports"),
                                "detail": f"Observation {ordinal}-{n}.",
                            }
                            for n in range(16)
                        ],
                    }
                ),
                "ok",
            )
        result = self.run_series(self.originals(5))
        self.assertEqual(64, len(result.index.entries))
        self.assertTrue(result.index.overflow)
        self.assertEqual((5,), result.index.unresolved_ordinals)
        self.assertEqual({"supports", "departs"}, {e.candidate.kind for e in result.index.entries})
        self.assertEqual(["a05"], [s.fact_id for s in result.failed_primary])
        self.assertEqual("unresolved", result.reason)

    def test_preparation_times_include_owned_prefix_but_never_prior_model_latency(self):
        clock = [0.0]
        prefix = reading_map_call.protocol_prefix
        packet = reading_passes._packet
        factory = self.model_for

        def make_prefix(*args, **kwargs):
            self.assertTrue(self.events)
            clock[0] += 0.025
            return prefix(*args, **kwargs)

        def make_packet(*args, **kwargs):
            clock[0] += 0.001
            return packet(*args, **kwargs)

        def model_for(ordinal):
            model = factory(ordinal)
            clock[0] += 100
            return model

        self.model_for = model_for
        originals = self.originals()
        with (
            mock.patch.object(
                analyze_diagnostics, "time", SimpleNamespace(monotonic=lambda: clock[0])
            ),
            mock.patch.object(reading_map_call, "protocol_prefix", side_effect=make_prefix),
            mock.patch.object(reading_passes, "_packet", side_effect=make_packet),
        ):
            result = self.run_series(originals)
        elapsed = [p.snapshots[1]["prepared"]["build_elapsed_ms"] for p in result.passes]
        self.assertGreaterEqual(elapsed[0], 25)
        self.assertTrue(all(0 < value < 25 for value in elapsed[1:]))
        self.assertTrue(all(value < 100 for value in elapsed))

    def _factory_failure_after_one_pass(self, failure, expected):
        factory = self.model_for

        def model_for(ordinal):
            if ordinal == 2:
                self.factories.append(ordinal)
                raise failure
            return factory(ordinal)

        self.model_for = model_for
        result = self.run_series()
        self.assertEqual(expected, result.reason)
        self.assertEqual([1, 2], self.factories)
        self.assertEqual([1], [ordinal for ordinal, _, _ in self.calls])
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual([1], [passed.ordinal for passed in result.passes])
        self.assertEqual([1], [entry.ordinal for entry in result.index.entries])
        self.assertEqual((), result.failed_primary)
        self.assertEqual(["a02", "a03"], [span.fact_id for span in result.unassigned_primary])
        self.assertTrue(result.passes[0].snapshots[-1]["input"]["attempt_reserved"])
        self.assertTrue(result.observations[0]["ended"])
        second = result.observations[1]
        self.assertFalse(second["ended"])
        self.assertIsNotNone(second["observation"]["diagnostic"]["prepared"])
        self.assertIsNone(second["observation"]["diagnostic"]["input"])
        self.assertEqual(
            2, len([event for event in self.events if event["observation"]["ordinal"] == 2])
        )
        self.assertNotIn("private factory detail", repr(result))
        self.assertEqual(1, len(self.fixture.loaded(self.owner)["passes"]))

    def test_factory_exception_keeps_completed_pass_and_never_invoked_ranges(self):
        self._factory_failure_after_one_pass(OSError("private factory detail"), "factory-failed")

    def test_factory_refusal_keeps_completed_pass_without_a_called_observation(self):
        self._factory_failure_after_one_pass(
            reading_policy.RefusedError({"reason": "private factory detail"}), "factory-refused"
        )
