"""One production plan, with advisory previews that cannot start or reserve work."""

from __future__ import annotations

import builtins
import copy
import importlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import (
    analyze_capacity,
    reading,
    reading_long_plan,
    reading_pass_types,
    reading_policy,
    reading_route,
    settings,
)
from compass_runtime import annotations as annotations_store
from compass_runtime import reading_long_control as control
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_source_collect as source
from compass_runtime import reading_source_inventory as inventory


class LongPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_plan"))
        self.module = importlib.import_module("compass_runtime.reading_long_plan")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.preferences = settings.DEFAULTS
        with mock.patch.object(reading_route, "_state", return_value="usable"):
            self.route = reading_route.resolve(
                "claude",
                environ={},
                root=Path(temporary.name),
                binary_resolver=lambda _name: "/fixture/cli",
            )
        self.row = {"harness": "claude", "sid": "abc123ab", "activity": "working"}
        self.entry: dict[str, Any] = {
            "harness": "claude",
            "sid": "abc123ab",
            "revisions": [
                {"n": 3, "at": 200.0, "window_start": 100.0, "goal": "PRIVATE GOAL", "lines": []},
            ],
        }
        self.status = {
            "used": 12,
            "limit": reading_policy.DAILY_CAP,
            "reason": "",
            "off": False,
            "consent": True,
        }
        self.native = self.module.SourceEstimate(
            "claude", "abc123ab", "native-claude", 12345, 300.0
        )

    def describe(self, **changes: Any) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "row": self.row,
            "entry": self.entry,
            "route": self.route,
            "preferences": self.preferences,
            "policy_status": self.status,
            "source": self.native,
            "now": 400.0,
            "settle_sec": 10.0,
        }
        return reading_long_plan.describe(**(arguments | changes))

    def test_actual_plan_uses_source_owner_reply_owner_and_saved_route_minimum(self) -> None:
        plan = self.module.build(self.route, self.preferences)
        self.assertEqual(plan, reading_pass_types.validate_plan(plan))
        self.assertEqual(
            (16, 1, 17),
            tuple(
                plan[k] for k in ("max_evidence_passes", "max_reconciliation_passes", "max_calls")
            ),
        )
        limits = plan["limits"]
        for name, value in asdict(source.Limits()).items():
            self.assertEqual(value, limits[name])
        self.assertEqual(16 * 1024 * 1024, limits["input_bytes"])
        self.assertEqual(reading.REPLY_CAP_BYTES, limits["reply_bytes"])
        self.assertEqual(17 * reading.REPLY_CAP_BYTES, limits["output_bytes"])
        self.assertEqual(1800 * 1000, limits["job_ms"])
        self.assertEqual(
            min(
                self.preferences.analyze_prompt_bytes,
                self.route["capacity"]["maximum_prompt_bytes"],
            ),
            limits["prompt_bytes"],
        )
        larger = self.preferences._replace(analyze_prompt_bytes=2_097_152)
        constrained = copy.deepcopy(self.route)
        constrained["capacity"]["maximum_prompt_bytes"] = 100_000
        self.assertEqual(100_000, self.module.build(constrained, larger)["limits"]["prompt_bytes"])
        self.assertEqual(2_097_152, larger.analyze_prompt_bytes)
        limits["source_bytes"] = 1
        self.assertEqual(
            source.Limits().source_bytes,
            self.module.build(self.route, self.preferences)["limits"]["source_bytes"],
        )

    def test_preview_is_zero_io_zero_authority_and_discloses_distinct_measurements(self) -> None:
        with (
            mock.patch.object(builtins, "open", side_effect=AssertionError("file IO")),
            mock.patch.object(io, "open", side_effect=AssertionError("path IO")),
            mock.patch.object(os, "stat", side_effect=AssertionError("metadata lookup")),
            mock.patch.object(subprocess, "Popen", side_effect=AssertionError("process launch")),
            mock.patch.object(
                reading_policy, "status", side_effect=AssertionError("permission transaction")
            ),
            mock.patch.object(
                reading_policy,
                "capture_long_permission",
                side_effect=AssertionError("permission capture"),
            ),
            mock.patch.object(
                annotations_store,
                "capture_long_target",
                side_effect=AssertionError("annotation write"),
            ),
            mock.patch.object(markers, "begin", side_effect=AssertionError("marker write")),
            mock.patch.object(control, "admit", side_effect=AssertionError("slot claim")),
            mock.patch.object(source, "collect", side_effect=AssertionError("corpus")),
            mock.patch.object(inventory, "freeze", side_effect=AssertionError("discovery")),
            mock.patch.object(reading_route, "resolve", side_effect=AssertionError("route lookup")),
            mock.patch.object(
                analyze_capacity, "preview", side_effect=AssertionError("capacity lookup")
            ),
        ):
            first, second = self.describe(), self.describe()
        self.assertEqual(first, second)
        self.assertTrue(first["supported"])
        self.assertTrue(first["can_start"])
        self.assertEqual("", first["reason"])
        self.assertEqual({"revision": 3, "start_at": 100.0}, first["intent"])
        self.assertEqual(12345, first["source"]["parent_bytes"])
        self.assertIsNone(first["source"]["record_count"])
        self.assertIsNone(first["source"]["stream_count"])
        self.assertFalse(first["source"]["frozen"])
        self.assertEqual(
            self.preferences.analyze_prompt_bytes, first["prompt"]["saved_ceiling_bytes"]
        )
        self.assertEqual(
            self.route["capacity"]["maximum_prompt_bytes"], first["prompt"]["route_ceiling_bytes"]
        )
        self.assertFalse(first["prompt"]["fit_verified"])
        self.assertEqual(88, first["allowance"]["remaining"])
        self.assertFalse(first["allowance"]["reserved"])
        self.assertEqual(self.module.build(self.route, self.preferences), first["plan"])
        self.assertEqual("native-actual-io", first["measurements"]["source_bytes"])
        self.assertEqual("retained-object-graph", first["measurements"]["retained_bytes"])
        self.assertEqual("source-and-analysis-preparation", first["measurements"]["prepare_ms"])
        self.assertEqual("whole-job-elapsed", first["measurements"]["job_ms"])
        wire = json.dumps(first, allow_nan=False)
        self.assertNotIn("PRIVATE GOAL", wire)

    def test_binding_changes_for_route_plan_or_saved_intent_not_advisory_estimates(self) -> None:
        original = self.describe()
        for key, value in (
            ("model", "claude-sonnet-5"),
            ("words_destination", "Private gateway"),
            ("provider", "codex"),
        ):
            changed: dict[str, Any] = copy.deepcopy(dict(self.route))
            changed[key] = value
            self.assertNotEqual(original["binding"], self.describe(route=changed)["binding"])
        changed_entry = copy.deepcopy(self.entry)
        changed_entry["revisions"][-1]["goal"] = "Another private goal"
        self.assertNotEqual(original["binding"], self.describe(entry=changed_entry)["binding"])
        self.assertNotEqual(
            original["binding"],
            self.describe(preferences=self.preferences._replace(analyze_prompt_bytes=100_000))[
                "binding"
            ],
        )
        self.assertEqual(
            original["binding"], self.describe(policy_status={**self.status, "used": 99})["binding"]
        )
        estimate = self.module.SourceEstimate("claude", "abc123ab", "native-claude", 99999, 500.0)
        self.assertEqual(original["binding"], self.describe(source=estimate)["binding"])

    def test_only_explicit_matching_native_source_capability_can_offer_start(self) -> None:
        for estimate in (
            None,
            self.module.SourceEstimate("claude", "abc123ab", "unknown"),
            self.module.SourceEstimate("claude", "abc123ab", "unsupported"),
            self.module.SourceEstimate("claude", "different", "native-claude"),
        ):
            with self.subTest(source=estimate):
                result = self.describe(source=estimate)
                self.assertFalse(result["supported"])
                self.assertFalse(result["can_start"])
                self.assertIsNone(result["source"]["parent_bytes"])
        row = {**self.row, "harness": "codex"}
        self.assertEqual("unsupported-source", self.describe(row=row)["reason"])
        estimate = self.module.SourceEstimate("claude", "abc123ab", "native-claude")
        result = self.describe(source=estimate)
        self.assertTrue(result["can_start"])
        self.assertIsNone(result["source"]["parent_bytes"])
        self.assertIsNone(result["source"]["observed_at"])

    def test_invalid_or_blocked_capacity_never_builds_zero_byte_plan(self) -> None:
        for maximum in (0, -1, True, float("nan"), 2**53, 100):
            route = copy.deepcopy(self.route)
            route["capacity"]["maximum_prompt_bytes"] = maximum
            self.assertIsNone(self.module.build(route, self.preferences))
            result = self.describe(route=route)
            self.assertFalse(result["can_start"])
            self.assertIsNone(result["plan"])
        for reason in ("context-config", "context-dynamic", "context-no-room", "unavailable"):
            route = copy.deepcopy(self.route)
            route["capacity"]["reason"] = reason
            self.assertIsNone(self.module.build(route, self.preferences))
        self.assertIsNone(self.module.build(None, self.preferences))
        self.assertEqual("route-unavailable", self.describe(route=None)["reason"])
        for provider in ("", "third-party"):
            result = self.describe(route={**self.route, "provider": provider})
            self.assertEqual("route-unavailable", result["reason"])
            self.assertFalse(result["can_start"])

    def test_unknown_or_blocked_allowance_and_missing_intent_are_honest(self) -> None:
        for status in (
            None,
            {**self.status, "used": True},
            {**self.status, "used": float("nan")},
            {**self.status, "reason": "store-unavailable"},
        ):
            result = self.describe(policy_status=status)
            self.assertFalse(result["can_start"])
            self.assertIsNone(result["allowance"]["used"])
            self.assertIsNone(result["allowance"]["remaining"])
        result = self.describe(policy_status={**self.status, "used": 100, "reason": "daily-cap"})
        self.assertEqual(0, result["allowance"]["remaining"])
        self.assertFalse(result["can_start"])
        paused = self.describe(
            policy_status={
                **self.status,
                "off": True,
                "consent": False,
                "reason": "model-calls-paused",
            }
        )
        self.assertFalse(paused["can_start"])
        self.assertEqual("paused", paused["allowance"]["state"])
        disabled = self.describe(
            policy_status={
                **self.status,
                "consent": False,
                "reason": "run-disabled",
            }
        )
        self.assertFalse(disabled["can_start"])
        self.assertEqual("run-disabled", disabled["allowance"]["state"])
        self.assertIsNone(disabled["allowance"]["used"])
        self.assertEqual("intent-unavailable", self.describe(entry=None)["reason"])
        empty = {**self.entry, "revisions": []}
        self.assertIsNone(self.describe(entry=empty)["intent"]["start_at"])
        self.assertFalse(self.describe(now=float("nan"))["can_start"])

    def test_invalid_settings_and_estimate_numbers_never_escape_closed_descriptor(self) -> None:
        for value in (True, 0, -1, float("nan"), float("inf"), 2**53):
            with self.subTest(value=value):
                # Deliberately bypass the Settings annotation to exercise malformed input.
                result = self.describe(
                    preferences=self.preferences._replace(analyze_prompt_bytes=cast("int", value))
                )
                self.assertIsNone(result["plan"])
                self.assertIsNone(result["prompt"]["saved_ceiling_bytes"])
                self.assertFalse(result["can_start"])
                json.dumps(result, allow_nan=False)
                estimate = self.module.SourceEstimate(
                    "claude", "abc123ab", "native-claude", value, value
                )
                preview = self.describe(source=estimate)
                self.assertIsNone(preview["source"]["observed_at"])
                if value != 0:
                    self.assertIsNone(preview["source"]["parent_bytes"])
                json.dumps(preview, allow_nan=False)

    def test_tool_output_destination_is_independently_disclosed_and_bound(self) -> None:
        original = self.describe()
        for destination in ("Separate tool receiver", ""):
            with self.subTest(destination=destination):
                route = {**self.route, "destination": destination}
                changed = self.describe(route=route)
                self.assertTrue(changed["can_start"])
                self.assertEqual(destination, changed["route"]["destination"])
                self.assertEqual(
                    original["route"]["words_destination"], changed["route"]["words_destination"]
                )
                self.assertNotEqual(original["binding"], changed["binding"])
        self.assertNotIn(
            "destination",
            self.describe(route={**self.route, "destination": None}).get("route") or {},
        )

    def test_populated_provider_cannot_override_a_captured_route_refusal(self) -> None:
        for reason in (
            reading_route.REASON_NOT_INSTALLED,
            reading_route.REASON_MISSING_OTHER_UNQUALIFIED,
            reading_route.REASON_UNQUALIFIED_OTHER_MISSING,
            reading_route.REASON_UNQUALIFIED,
            "unknown-route-reason",
        ):
            with self.subTest(reason=reason):
                result = self.describe(route={**self.route, "reason": reason})
                self.assertEqual("route-unavailable", result["reason"])
                self.assertFalse(result["can_start"])
                self.assertIsNone(result["plan"])
        for reason in (
            reading_route.REASON_FALLBACK_MISSING,
            reading_route.REASON_FALLBACK_UNQUALIFIED,
        ):
            route = {**self.route, "provider": "codex", "reason": reason, "fallback": True}
            result = self.describe(route=route)
            self.assertTrue(result["can_start"])
            self.assertEqual(reason, result["route"]["reason"])
        self.assertTrue(self.describe(route={**self.route, "ci_read": "flag-off"})["can_start"])
