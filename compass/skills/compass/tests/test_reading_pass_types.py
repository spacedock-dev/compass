"""Long-reading metadata declares bounds without granting calls or proving coverage."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import unittest
from typing import Any

from compass_runtime import analyze_diagnostics


def plan() -> dict[str, Any]:
    return {
        "version": 1,
        "mode": "long",
        "max_evidence_passes": 16,
        "max_reconciliation_passes": 1,
        "max_calls": 17,
        "limits": {
            "prompt_bytes": 2_097_152,
            "input_bytes": 16_777_216,
            "reply_bytes": 8_192,
            "output_bytes": 139_264,
            "source_bytes": 268_435_456,
            "prepare_ms": 60_000,
            "retained_bytes": 33_554_432,
            "retained_units": 65_536,
            "source_pages": 512,
            "job_ms": 1_800_000,
        },
    }


class PlanValidationTest(unittest.TestCase):
    def validator(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_pass_types"))
        return importlib.import_module("compass_runtime.reading_pass_types").validate_plan

    def test_bounded_plan_returns_independent_limits(self) -> None:
        validate = self.validator()
        supplied = plan()
        checked = validate(supplied)
        self.assertEqual(plan(), checked)
        self.assertIsNot(supplied, checked)
        supplied["limits"]["prompt_bytes"] = 1
        supplied["max_calls"] = 2
        self.assertEqual(2_097_152, checked["limits"]["prompt_bytes"])
        self.assertEqual(17, checked["max_calls"])
        checked["limits"]["source_pages"] = 1
        self.assertEqual(512, supplied["limits"]["source_pages"])

    def test_one_evidence_pass_still_reserves_a_reconciliation_call(self) -> None:
        value = plan()
        value.update(max_evidence_passes=1, max_calls=2)
        self.assertEqual(value, self.validator()(value))

    def test_invalid_call_envelopes_are_refused(self) -> None:
        validate = self.validator()
        changes = (
            ("version", True),
            ("version", 2),
            ("mode", "short"),
            ("mode", ["long"]),
            ("max_evidence_passes", True),
            ("max_evidence_passes", 0),
            ("max_evidence_passes", -1),
            ("max_evidence_passes", 17),
            ("max_evidence_passes", 16.0),
            ("max_reconciliation_passes", True),
            ("max_reconciliation_passes", 0),
            ("max_reconciliation_passes", 2),
            ("max_calls", True),
            ("max_calls", 16),
            ("max_calls", 18),
            ("max_calls", 17.0),
        )
        for key, value in changes:
            with self.subTest(key=key, value=value):
                self.assertIsNone(validate({**plan(), key: value}))

    def test_each_resource_limit_must_be_a_positive_safe_integer(self) -> None:
        validate = self.validator()
        for key in plan()["limits"]:
            for wrong in (None, True, False, 0, -1, 1.0, "1", float("nan"), float("inf"), 2**53):
                with self.subTest(key=key, wrong=wrong):
                    value = plan()
                    value["limits"][key] = wrong
                    self.assertIsNone(validate(value))
        value = plan()
        value["limits"] = dict.fromkeys(value["limits"], 1)
        self.assertEqual(value, validate(value))

    def test_absent_extra_or_nonobject_fields_are_refused(self) -> None:
        validate = self.validator()
        invalid: Any
        for invalid in (None, [], 1, "long", {**plan(), "words": "private sentinel"}):
            with self.subTest(invalid=invalid):
                self.assertIsNone(validate(invalid))
        for key in plan():
            with self.subTest(missing=key):
                value = plan()
                del value[key]
                self.assertIsNone(validate(value))
        for key in plan()["limits"]:
            with self.subTest(missing_limit=key):
                value = plan()
                del value["limits"][key]
                self.assertIsNone(validate(value))
        invalid_limits: Any
        for invalid_limits in (None, [], "private sentinel", {**plan()["limits"], "words": "x"}):
            with self.subTest(limits=invalid_limits):
                self.assertIsNone(validate({**plan(), "limits": invalid_limits}))


def diagnostic() -> dict[str, Any]:
    return {
        "version": 1,
        "prepared": {"prompt_bytes": 10, "build_elapsed_ms": 2},
        "selection": {
            "eligible_entries": 2,
            "selected_entries": 1,
            "eligible_messages": 2,
            "selected_messages": 1,
            "serialized_message_bytes": 8,
            "expanded_message_characters": None,
            "selected_source_characters": None,
        },
        "input": {
            "kind": "actual-input",
            "prompt_bytes": 10,
            "elapsed_ms": 4,
            "outcome": "context-config-after-reserve",
            "attempt_reserved": True,
            "model_invoked": True,
        },
        "capacity": {
            "prompt_bytes": 10,
            "system_prompt_bytes": 3,
            "maximum_prompt_bytes": 2_097_152,
            "estimated_input_tokens": 4,
            "estimated_system_tokens": 1,
            "generation_reserve_tokens": 128_000,
            "cli_reserve_tokens": 16_384,
            "requested_maximum": 2_097_152,
            "window_tokens": 1_000_000,
            "estimated_total_tokens": 144_389,
            "reason": "allowed",
            "window_source": "documented",
            "estimate_method": "utf8-bytes-div-3",
            "policy": "analyze-context-v1",
            "configuration_reason": "",
            "allowed": True,
            "fit_verified": False,
            "policy_verified": False,
        },
    }


def observation() -> dict[str, Any]:
    return {"version": 1, "ordinal": 1, "kind": "evidence", "diagnostic": diagnostic()}


class PassValidationTest(unittest.TestCase):
    def validator(self) -> Any:
        module = importlib.import_module("compass_runtime.reading_pass_types")
        self.assertTrue(callable(getattr(module, "validate_pass", None)))
        return module.validate_pass

    def test_charged_late_refusal_preserves_initial_allowance_and_unknown_characters(self) -> None:
        validate = self.validator()
        supplied = observation()
        self.assertIsNotNone(analyze_diagnostics.validate(supplied["diagnostic"]))
        checked = validate(supplied, plan=plan())
        self.assertEqual(supplied, checked)
        measured = checked["diagnostic"]
        self.assertEqual("context-config-after-reserve", measured["input"]["outcome"])
        self.assertTrue(measured["input"]["attempt_reserved"])
        self.assertTrue(measured["input"]["model_invoked"])
        self.assertTrue(measured["capacity"]["allowed"])
        self.assertIsNone(measured["selection"]["expanded_message_characters"])
        self.assertIsNone(measured["selection"]["selected_source_characters"])

    def test_reconciliation_ordinal_is_reserved_even_without_other_observations(self) -> None:
        validate = self.validator()
        for limit, reconciliation in ((16, 17), (1, 2)):
            with self.subTest(limit=limit):
                supplied_plan = {
                    **plan(),
                    "max_evidence_passes": limit,
                    "max_calls": reconciliation,
                }
                value = {**observation(), "ordinal": reconciliation, "kind": "reconciliation"}
                self.assertEqual(value, validate(value, plan=supplied_plan))
                self.assertIsNone(validate({**value, "kind": "evidence"}, plan=supplied_plan))
                self.assertIsNone(validate({**value, "ordinal": limit}, plan=supplied_plan))
                evidence = {**value, "ordinal": limit, "kind": "evidence"}
                self.assertEqual(evidence, validate(evidence, plan=supplied_plan))

    def test_unknown_is_distinct_from_measured_zero_and_preparation_without_a_call(self) -> None:
        validate = self.validator()
        unknown = {**observation(), "diagnostic": None}
        self.assertEqual(unknown, validate(unknown, plan=plan()))
        initial = {
            "version": 1,
            "input": None,
            "capacity": None,
            "prepared": None,
            "selection": None,
        }
        value = {**observation(), "diagnostic": initial}
        self.assertEqual(initial, validate(value, plan=plan())["diagnostic"])
        prepared = diagnostic()
        prepared.update(input=None, capacity=None)
        value = {**observation(), "diagnostic": prepared}
        self.assertEqual(prepared, validate(value, plan=plan())["diagnostic"])
        zero = diagnostic()
        zero["prepared"]["prompt_bytes"] = 0
        zero["input"]["prompt_bytes"] = 0
        zero["capacity"] = None
        zero["selection"]["serialized_message_bytes"] = 0
        value = {**observation(), "diagnostic": zero}
        self.assertEqual(0, validate(value, plan=plan())["diagnostic"]["prepared"]["prompt_bytes"])

    def test_preflight_refusal_does_not_inherit_another_pass_reservation(self) -> None:
        validate = self.validator()
        first = validate(observation(), plan=plan())
        refused = diagnostic()
        refused["capacity"] = None
        refused["input"].update(outcome="refused", attempt_reserved=False, model_invoked=False)
        second = {**observation(), "ordinal": 2, "diagnostic": refused}
        self.assertEqual(second, validate(second, plan=plan()))
        self.assertTrue(first["diagnostic"]["input"]["attempt_reserved"])

    def test_every_nested_measurement_is_copied_in_both_directions(self) -> None:
        validate = self.validator()
        for section, key in (
            ("input", "prompt_bytes"),
            ("capacity", "prompt_bytes"),
            ("prepared", "prompt_bytes"),
            ("selection", "serialized_message_bytes"),
        ):
            with self.subTest(section=section):
                supplied = observation()
                checked = validate(supplied, plan=plan())
                supplied["diagnostic"][section][key] = 0
                self.assertEqual(observation(), checked)
                checked["diagnostic"][section][key] = 100
                self.assertEqual(0, supplied["diagnostic"][section][key])
        supplied = observation()
        checked = validate(supplied, plan=plan())
        supplied["diagnostic"]["capacity"] = None
        supplied["ordinal"] = 2
        self.assertEqual(observation(), checked)

    def test_malformed_nonnull_diagnostics_reject_the_pass_instead_of_becoming_unknown(
        self,
    ) -> None:
        validate = self.validator()
        invalid: Any
        for invalid in ({}, [], "private sentinel", 0, False):
            with self.subTest(invalid=invalid):
                self.assertIsNone(validate({**observation(), "diagnostic": invalid}, plan=plan()))
        changes = (
            ("prepared", "prompt_bytes", 11),
            ("capacity", "prompt_bytes", 11),
            ("capacity", "fit_verified", True),
            ("capacity", "policy_verified", True),
            ("capacity", "reason", "private sentinel"),
            ("selection", "selected_entries", 3),
            ("selection", "selected_source_characters", -1),
            ("input", "attempt_reserved", False),
            ("input", "outcome", "private sentinel"),
            ("input", "prompt_bytes", True),
            ("input", "words", "private sentinel"),
        )
        for section, key, wrong in changes:
            with self.subTest(section=section, key=key):
                value = observation()
                value["diagnostic"][section][key] = wrong
                self.assertIsNone(analyze_diagnostics.validate(value["diagnostic"]))
                self.assertIsNone(validate(value, plan=plan()))

    def test_legacy_v1_shape_is_preserved_without_inventing_preparation(self) -> None:
        legacy = copy.deepcopy(diagnostic())
        del legacy["prepared"]
        del legacy["selection"]
        value = {**observation(), "diagnostic": legacy}
        self.assertEqual(value, self.validator()(value, plan=plan()))

    def test_invalid_envelopes_or_plans_are_refused(self) -> None:
        validate = self.validator()
        for key, wrong in (
            ("version", True),
            ("version", 2),
            ("ordinal", True),
            ("ordinal", 0),
            ("ordinal", -1),
            ("ordinal", 18),
            ("ordinal", 1.0),
            ("kind", "summary"),
            ("kind", ["evidence"]),
            ("words", "private sentinel"),
        ):
            with self.subTest(key=key, wrong=wrong):
                self.assertIsNone(validate({**observation(), key: wrong}, plan=plan()))
        for key in observation():
            with self.subTest(missing=key):
                value = observation()
                del value[key]
                self.assertIsNone(validate(value, plan=plan()))
        invalid: Any
        for invalid in (None, [], 1, "private sentinel"):
            with self.subTest(invalid=invalid):
                self.assertIsNone(validate(invalid, plan=plan()))
                self.assertIsNone(validate(observation(), plan=invalid))
        self.assertIsNone(validate(observation(), plan={**plan(), "max_calls": 18}))
