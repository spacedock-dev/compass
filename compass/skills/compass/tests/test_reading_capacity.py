"""Analyze capacity is a conservative estimate over the assembled prompt."""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import json
import unittest
from typing import Any


class ReadingCapacityTest(unittest.TestCase):
    def assess(self, prompt: str = "hello", **overrides: Any) -> Any:
        self.assertIsNotNone(
            importlib.util.find_spec("compass_runtime.reading_capacity"),
            "Analyze needs a pure estimated capacity policy",
        )
        module = importlib.import_module("compass_runtime.reading_capacity")
        arguments = {
            "system_prompt": "system",
            "provider": "claude",
            "model": "claude-sonnet-5-5",
            "deployment": "direct",
        }
        arguments.update(overrides)
        return module.assess(prompt, **arguments)

    def test_exact_documented_direct_models_allow_two_mib_at_the_boundary(self) -> None:
        for model in ("claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5", "claude-opus-5-5"):
            with self.subTest(model=model):
                result = self.assess("x" * 2_097_152, model=model)
                self.assertTrue(result.allowed)
                self.assertEqual(2_097_152, result.maximum_prompt_bytes)
                self.assertEqual(1_000_000, result.window_tokens)
                self.assertEqual("documented", result.window_source)
                self.assertFalse(result.fit_verified)
                self.assertEqual(
                    "prompt-too-large", self.assess("x" * 2_097_153, model=model).reason
                )

    def test_unknown_models_providers_and_deployments_keep_legacy_ceiling(self) -> None:
        routes = (
            {"model": "sonnet"},
            {"model": "claude-sonnet-5-5-20990101"},
            {"model": "claude-future"},
            {"provider": "codex"},
            {"provider": "future"},
            {"deployment": "gateway"},
            {"deployment": "cloud"},
            {"deployment": "unknown"},
        )
        for route in routes:
            with self.subTest(route=route):
                result = self.assess("x" * 524_288, **route)
                self.assertTrue(result.allowed)
                self.assertEqual(524_288, result.maximum_prompt_bytes)
                self.assertIsNone(result.window_tokens)
                self.assertEqual("unknown", result.window_source)
                self.assertEqual("legacy-byte-cap", result.estimate_method)
                self.assertIsNone(result.estimated_total_tokens)
                self.assertFalse(result.fit_verified)
                self.assertFalse(self.assess("x" * 524_289, **route).allowed)

    def test_lower_window_reserves_system_generation_and_cli_before_input(self) -> None:
        result = self.assess(
            "x" * 166_674, system_prompt="s" * 172, window_limits=(200_000, 500_000)
        )
        self.assertTrue(result.allowed)
        self.assertEqual(200_000, result.window_tokens)
        self.assertEqual("configured", result.window_source)
        self.assertEqual(128_000, result.generation_reserve_tokens)
        self.assertEqual(16_384, result.cli_reserve_tokens)
        self.assertEqual(58, result.estimated_system_tokens)
        self.assertEqual(55_558, result.estimated_input_tokens)
        self.assertEqual(200_000, result.estimated_total_tokens)
        self.assertEqual(166_674, result.maximum_prompt_bytes)
        self.assertFalse(
            self.assess("x" * 166_675, system_prompt="s" * 172, window_limits=(200_000,)).allowed
        )
        self.assertTrue(self.assess("x" * 40_960, window_limits=(200_000,)).allowed)

    def test_positive_controls_never_enlarge_an_unknown_route(self) -> None:
        for limit in (1_000_000, 10_000_000):
            with self.subTest(limit=limit):
                result = self.assess("x" * 524_289, deployment="gateway", window_limits=(limit,))
                self.assertFalse(result.allowed)
                self.assertEqual(524_288, result.maximum_prompt_bytes)
                self.assertEqual("configured", result.window_source)
                self.assertFalse(result.fit_verified)
        self.assertEqual(
            166_842,
            self.assess(deployment="gateway", window_limits=(200_000,)).maximum_prompt_bytes,
        )
        self.assertEqual(1_000_000, self.assess(window_limits=(10_000_000,)).window_tokens)

    def test_utf8_bytes_and_rounding_determine_the_actual_assembled_input(self) -> None:
        result = self.assess("🙂", window_limits=(144_388,))
        self.assertTrue(result.allowed)
        self.assertEqual(4, result.prompt_bytes)
        self.assertEqual(2, result.estimated_input_tokens)
        self.assertEqual(6, result.maximum_prompt_bytes)
        self.assertEqual(6, result.system_prompt_bytes)
        self.assertEqual(144_388, result.estimated_total_tokens)
        self.assertFalse(self.assess("界🙂", window_limits=(144_388,)).allowed)
        self.assertEqual(1, self.assess("\ud800").prompt_bytes)
        self.assertEqual(2, self.assess(system_prompt="🙂").estimated_system_tokens)

    def test_no_headroom_refuses_even_empty_input_without_reducing_reserves(self) -> None:
        for limit in (0, 100, 128_000, 144_386):
            with self.subTest(limit=limit):
                result = self.assess("", window_limits=(limit,))
                self.assertFalse(result.allowed)
                self.assertEqual("context-no-room", result.reason)
                self.assertEqual(0, result.maximum_prompt_bytes)
                self.assertEqual(128_000, result.generation_reserve_tokens)
                self.assertEqual(16_384, result.cli_reserve_tokens)

    def test_malformed_or_ambiguous_controls_fail_closed(self) -> None:
        controls = (
            {"window_limits": (-1,)},
            {"window_limits": (True,)},
            {"window_limits": (200_000.0,)},
            {"window_limits": ("200000",)},
            {"window_limits": None},
            {"window_limits": "200000"},
            {"configuration_ambiguous": True},
            {"configuration_ambiguous": "false"},
            {"deployment": "misspelled"},
        )
        for control in controls:
            with self.subTest(control=control):
                result = self.assess(**control)
                self.assertFalse(result.allowed)
                self.assertEqual("context-config", result.reason)
                self.assertEqual(0, result.maximum_prompt_bytes)
                self.assertFalse(result.fit_verified)

    def test_no_selected_provider_cannot_be_admitted(self) -> None:
        result = self.assess(provider="")
        self.assertFalse(result.allowed)
        self.assertEqual("no-route", result.reason)

    def test_result_contains_only_counts_and_closed_labels_without_fit_claim(self) -> None:
        result = self.assess(
            "private-prompt", system_prompt="private-system", model="private-model"
        )
        metadata = dataclasses.asdict(result)
        encoded = json.dumps(metadata)
        for private in ("private-prompt", "private-system", "private-model"):
            self.assertNotIn(private, encoded)
        self.assertEqual("analyze-context-v1", result.policy)
        self.assertEqual("allowed", result.reason)
        self.assertFalse(result.fit_verified)
        self.assertEqual("utf8-bytes-div-3", self.assess().estimate_method)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.allowed = False
