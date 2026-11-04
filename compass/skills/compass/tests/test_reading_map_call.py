"""One map invocation through real reservation/marker ownership and a fake transport."""

from __future__ import annotations

import hashlib
import json
import unittest
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

from compass_runtime import (
    analyze_capacity,
    analyze_diagnostics,
    reading,
    reading_long_markers,
    reading_map_call,
    reading_pass_types,
    reading_passes,
    reading_policy,
)

from . import test_reading_long_markers as marker_tests
from .test_agent_words import _agent
from .test_reading_long_jobs import binding

if TYPE_CHECKING:
    from pathlib import Path


class MapInvocationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = reading_map_call
        self.fixture = marker_tests.LongMarkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.markers = reading_long_markers
        assert self.fixture.permission is not None
        self.binding = binding()
        self.binding["plan"]["limits"].update(
            prompt_bytes=4_096, input_bytes=16_384, reply_bytes=8_192, output_bytes=32_768
        )
        prepared = reading_policy.prepare_long_job(
            permission=self.fixture.permission,
            binding=self.binding,
            call_timeout_ms=200,
            clock=lambda: 0.0,
        )
        assert prepared is not None
        owner = reading_long_markers.begin(
            self.config, permission=self.fixture.permission, job=prepared, now=100
        )
        assert owner is not None
        self.owner = owner
        self.calls: list[tuple[str, int]] = []
        self.requests: list[tuple[str, int]] = []
        self.snapshots: list[dict[str, Any]] = []
        self.raw = json.dumps(
            {
                "version": 1,
                "candidates": [
                    {"clause": "line_1", "kind": "uncertain", "cites": [1], "detail": "Observed."}
                ],
            }
        )
        self.status = "ok"
        self.failure: Exception | None = None

    def transport(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        self.calls.append((prompt, output_cap_bytes))
        if self.failure is not None:
            raise self.failure
        return self.raw, self.status

    def reserve(self, prompt: str, output_cap_bytes: int) -> reading_long_markers.Permit:
        self.requests.append((prompt, output_cap_bytes))
        self.assertEqual(8_192, output_cap_bytes)
        request = self.fixture.request(self.owner)
        request.update(
            prompt_bytes=len(prompt.encode("utf-8")),
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        )
        return self.markers.reserve(self.config, self.owner, request=request, now=100)

    def guard(self) -> reading_policy.GuardedModel:
        return reading_policy.GuardedModel(
            self.config,
            self.transport,
            lambda: 100,
            provider="claude",
            reserve_prompt=self.reserve,
            admit_prompt=analyze_capacity.Admission(
                "codex", "unknown", "", requested_maximum=4_096
            ),
        )

    def originals(self, *, long: bool = False) -> list[reading_passes.Original]:
        result = []
        for identity, at in (("second", 120.0), ("first", 110.0)):
            words = f"Original {identity} 界🙂. " * (300 if long else 1)
            row = reading.build_ledger(
                [_agent(identity, at, words)], "claude", "s1", read_agent_words=True
            )[0]
            result.append(reading_passes.Original(row, words))
        return result

    def invoke(
        self, *, max_bytes: int = 4_096, long: bool = False, **changes: Any
    ) -> reading_map_call.Invocation:
        return self.module.invoke(
            self.originals(long=long),
            goal="The exact frozen goal.",
            lines=("The exact saved outcome line.",),
            clauses=("goal", "line_1"),
            max_bytes=max_bytes,
            model=self.guard(),
            on_diagnostic=self.snapshots.append,
            **changes,
        )

    def test_capture_precedes_rendering_and_one_exact_packet_reaches_one_charge_and_call(
        self,
    ) -> None:
        clock = [0.0]
        planner = reading_passes.plan_packets

        def plan(*args: Any, **kwargs: Any) -> reading_passes.PacketPlan:
            self.assertEqual(1, len(self.snapshots))
            self.assertIsNone(self.snapshots[0]["prepared"])
            result = planner(*args, **kwargs)
            clock[0] += 0.125
            return result

        with (
            mock.patch.object(
                analyze_diagnostics, "time", SimpleNamespace(monotonic=lambda: clock[0])
            ),
            mock.patch.object(reading_passes, "plan_packets", side_effect=plan),
        ):
            result = self.invoke()
        self.assertEqual("mapped", result.state)
        assert result.plan is not None
        assert result.reply is not None
        assert result.diagnostic is not None
        self.assertEqual(1, len(self.calls))
        self.assertEqual(self.requests, self.calls)
        self.assertEqual(1, self.fixture.spends())
        packet = result.plan.packets[0]
        self.assertEqual(packet.prompt, self.calls[0][0])
        self.assertIn("The exact frozen goal.", packet.prompt)
        self.assertIn("The exact saved outcome line.", packet.prompt)
        self.assertEqual("second", result.reply.candidates[0].cites[0].span.fact_id)
        self.assertEqual(3, len(self.snapshots))
        self.assertEqual(125, result.diagnostic["prepared"]["build_elapsed_ms"])
        self.assertEqual(len(packet.prompt.encode()), result.diagnostic["input"]["prompt_bytes"])
        self.assertTrue(result.diagnostic["input"]["attempt_reserved"])
        self.assertTrue(result.diagnostic["input"]["model_invoked"])
        self.assertTrue(result.diagnostic["capacity"]["allowed"])
        counts = result.diagnostic["selection"]
        self.assertEqual(
            (2, 2, 2),
            (counts["eligible_entries"], counts["selected_entries"], counts["selected_messages"]),
        )
        rows = packet.prompt.rsplit("Range roles (menu, start, end, total):\n", 1)[1].split(
            "\n", 1
        )[1]
        self.assertEqual(len(rows.encode()), counts["serialized_message_bytes"])
        self.assertEqual(
            sum(len(cast("str", o.words)) for o in self.originals()),
            counts["expanded_message_characters"],
        )
        observations: list[dict[str, Any]] | None = []
        for index, diagnostic in enumerate(self.snapshots):
            observations = reading_pass_types.update_observations(
                observations,
                {"version": 1, "ordinal": 1, "kind": "evidence", "diagnostic": diagnostic},
                plan=self.binding["plan"],
                ended=index == 2,
            )
        assert observations is not None
        self.assertEqual(1, len(observations))
        marker = self.fixture.loaded(self.owner)
        self.assertEqual("active", marker["state"])
        self.assertEqual(1, len(marker["passes"]))
        self.assertEqual("charged", marker["passes"][0]["state"])

    def test_local_overflow_has_uncovered_ranges_without_call_charge_or_zero_measurement(
        self,
    ) -> None:
        result = self.invoke(max_bytes=50)
        assert result.plan is not None
        assert result.diagnostic is not None
        self.assertEqual("local-unfit", result.state)
        self.assertEqual("prompt-unfit", result.reason)
        self.assertEqual(["second", "first"], [r.fact_id for r in result.plan.uncovered_primary])
        self.assertEqual([], self.calls)
        self.assertEqual([], self.requests)
        self.assertEqual(0, self.fixture.spends())
        self.assertEqual(1, len(self.snapshots))
        self.assertIsNone(result.diagnostic["prepared"])
        self.assertIsNone(result.diagnostic["input"])
        self.assertEqual([], self.fixture.loaded(self.owner)["passes"])

    def test_a_charged_transport_failure_is_not_retried_or_parsed(self) -> None:
        self.status = "error"
        result = self.invoke()
        assert result.diagnostic is not None
        self.assertEqual("model-failed", result.state)
        self.assertEqual("error", result.reason)
        self.assertIsNone(result.reply)
        self.assertEqual(1, len(self.calls))
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual("error", result.diagnostic["input"]["outcome"])

    def test_post_charge_marker_failure_keeps_the_charge_without_adapter_entry(self) -> None:
        writer = self.markers._write

        def write(path: Path, marker: dict[str, Any]) -> None:
            if marker["passes"][-1]["state"] == "charged":
                raise OSError("private failure detail")
            return writer(path, marker)

        with mock.patch.object(self.markers, "_write", side_effect=write):
            result = self.invoke()
        self.assertEqual("refused", result.state)
        assert result.diagnostic is not None
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual([], self.calls)
        self.assertEqual(1, len(self.requests))
        self.assertTrue(result.diagnostic["input"]["attempt_reserved"])
        self.assertFalse(result.diagnostic["input"]["model_invoked"])
        self.assertEqual("refused", result.diagnostic["input"]["outcome"])
        self.assertNotIn("private failure detail", repr(result))
        self.assertIsNone(self.fixture.loaded(self.owner)["passes"][0]["charged"])

    def test_transport_exception_keeps_actual_measurement_without_private_error_or_retry(
        self,
    ) -> None:
        self.failure = OSError("private transport detail")
        result = self.invoke()
        assert result.diagnostic is not None
        self.assertEqual(("model-failed", "error"), (result.state, result.reason))
        self.assertEqual(1, len(self.calls))
        self.assertEqual(1, self.fixture.spends())
        self.assertTrue(result.diagnostic["input"]["attempt_reserved"])
        self.assertTrue(result.diagnostic["input"]["model_invoked"])
        self.assertEqual("error", result.diagnostic["input"]["outcome"])
        self.assertNotIn("private transport detail", repr(result))

    def test_a_late_context_refusal_keeps_initial_capacity_and_charge(self) -> None:
        self.status = "context-config"
        self.raw = ""
        result = self.invoke()
        assert result.diagnostic is not None
        self.assertEqual("model-failed", result.state)
        self.assertEqual("context-config-after-reserve", result.reason)
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual(1, len(self.calls))
        self.assertTrue(result.diagnostic["capacity"]["allowed"])
        self.assertTrue(result.diagnostic["input"]["attempt_reserved"])
        self.assertTrue(result.diagnostic["input"]["model_invoked"])

    def test_corrupt_map_reply_is_failed_coverage_after_one_successful_transport(self) -> None:
        self.raw = '{"version":1,"candidates":[{"fact_id":"injected"}]}'
        result = self.invoke()
        assert result.reply is not None
        assert result.diagnostic is not None
        self.assertEqual("parse-failed", result.state)
        self.assertFalse(result.reply.usable)
        self.assertEqual((), result.reply.candidates)
        self.assertEqual("ok", result.diagnostic["input"]["outcome"])
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual(1, len(self.calls))

    def test_valid_empty_hypotheses_do_not_complete_uncovered_primary_ranges(self) -> None:
        self.raw = '{"version":1,"candidates":[]}'
        result = self.invoke(long=True)
        assert result.plan is not None
        assert result.reply is not None
        assert result.diagnostic is not None
        self.assertEqual("mapped", result.state)
        self.assertEqual((), result.reply.candidates)
        self.assertEqual("pass-limit", result.plan.reason)
        self.assertTrue(result.plan.uncovered_primary)
        self.assertEqual(1, len(self.calls))
        self.assertEqual(1, self.fixture.spends())
        self.assertLess(
            result.diagnostic["selection"]["expanded_message_characters"],
            result.diagnostic["selection"]["selected_source_characters"],
        )
