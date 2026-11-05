"""Analyze metadata is bounded, word-free, and follows the outcome store."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import inspect
import json
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import analyze_capacity, reading, reading_policy, supervise
from compass_runtime import annotations as annotation_store

from . import test_annotations, test_reading
from .support import make_runtime


def diagnostic() -> dict[str, Any]:
    return {
        "version": 1,
        "input": {
            "kind": "actual-input",
            "prompt_bytes": 10,
            "elapsed_ms": 125,
            "outcome": "ok",
            "attempt_reserved": True,
            "model_invoked": True,
        },
        "capacity": None,
    }


class DiagnosticSchemaTest(unittest.TestCase):
    def validator(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.analyze_diagnostics"))
        return importlib.import_module("compass_runtime.analyze_diagnostics").validate

    def test_valid_input_and_current_policy_survive_without_words_or_false_fit_proof(self) -> None:
        validate = self.validator()
        value = diagnostic()
        admission = analyze_capacity.Admission(
            "codex", "secret model sentinel", "private system sentinel", requested_maximum=2_097_152
        )
        admission('A"界🙂\\')
        value["capacity"] = admission.measurement
        checked = validate(value)
        self.assertEqual(value, checked)
        self.assertIsNot(checked, value)
        checked["input"]["prompt_bytes"] = 1
        self.assertEqual(10, value["input"]["prompt_bytes"])
        self.assertNotIn("sentinel", json.dumps(checked))
        self.assertFalse(checked["capacity"]["fit_verified"])
        self.assertFalse(checked["capacity"]["policy_verified"])
        self.assertIsNone(checked["capacity"]["window_tokens"])

    def test_absent_measurements_are_unknown_and_capacity_requires_matching_actual_input(
        self,
    ) -> None:
        validate = self.validator()
        self.assertIsNone(validate(None))
        self.assertEqual(
            {"version": 1, "input": None, "capacity": None},
            validate({"version": 1, "input": None, "capacity": None}),
        )
        admission = analyze_capacity.Admission("codex", "unknown", "", requested_maximum=524_288)
        admission("abc")
        value = diagnostic()
        value["capacity"] = admission.measurement
        self.assertIsNone(validate(value))
        value["input"] = None
        self.assertIsNone(validate(value))

    def test_malformed_counts_labels_extra_fields_and_verification_claims_are_refused(self) -> None:
        validate = self.validator()
        admission = analyze_capacity.Admission("codex", "unknown", "", requested_maximum=524_288)
        admission('A"界🙂\\')
        base = diagnostic()
        base["capacity"] = admission.measurement
        corruptions = (
            ((), "version", True),
            ((), "words", "secret sentinel"),
            (("input",), "prompt_bytes", -1),
            (("input",), "prompt_bytes", True),
            (("input",), "elapsed_ms", float("nan")),
            (("input",), "elapsed_ms", 2**53),
            (("input",), "outcome", "secret sentinel"),
            (("input",), "kind", "capacity-preview"),
            (("input",), "model_invoked", "yes"),
            (("capacity",), "fit_verified", True),
            (("capacity",), "policy_verified", True),
            (("capacity",), "configuration_reason", "secret sentinel"),
            (("capacity",), "window_source", "secret sentinel"),
            (("capacity",), "prompt", "secret sentinel"),
            (("capacity",), "estimated_total_tokens", -1),
        )
        for path, key, wrong in corruptions:
            with self.subTest(path=path, key=key, wrong=wrong):
                value = copy.deepcopy(base)
                section = value
                for part in path:
                    section = section[part]
                section[key] = wrong
                self.assertIsNone(validate(value))


class DiagnosticStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config, self.state = make_runtime(
            state_dir=Path(directory.name), state_home=directory.name
        )
        annotation_store.annotate(self.config, self.state, "claude", "s1", goal="request", now=10)

    def record(self, value: Any, *, why: str = "", read_at: float = 90) -> str:
        operation = annotation_store.record_withheld if why else annotation_store.record_reading
        self.assertIn("analyze_diagnostic", inspect.signature(operation).parameters)
        arguments = (
            {"reason": why, "spent": False}
            if why
            else {
                "assessment": test_annotations.AReadingIsKeptBesideTheWordsItReadTest._assessment(
                    read_at=read_at
                )
            }
        )
        return operation(
            self.config, self.state, "claude", "s1", analyze_diagnostic=value, **arguments
        )

    def reopened(self) -> Any:
        return annotation_store.find(annotation_store.load(self.config), "claude", "s1")

    def test_reading_then_refusal_metadata_round_trip_beside_the_retained_assessment(self) -> None:
        value = diagnostic()
        self.assertEqual(annotation_store.OUTCOME_STORED, self.record(value))
        reopened = self.reopened()
        self.assertEqual(value, annotation_store.published(reopened)["reading_diagnostic"])
        self.assertEqual(value, reopened["reading_diagnostic"])
        refused = {"version": 1, "input": None, "capacity": None}
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            self.record(refused, why=reading.WITHHELD_RECORD_UNREAD),
        )
        reopened = self.reopened()
        self.assertIn("assessment", reopened)
        self.assertEqual(refused, annotation_store.published(reopened)["reading_diagnostic"])

    def test_bad_metadata_is_refused_without_a_write_or_a_raw_sentinel(self) -> None:
        self.record(diagnostic())
        before = self.reopened()
        bad = {**diagnostic(), "private": "secret sentinel"}
        self.assertEqual(annotation_store.OUTCOME_REFUSED, self.record(bad))
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED, self.record(bad, why=reading.WITHHELD_MODEL_FAILED)
        )
        self.assertEqual(before, self.reopened())
        self.assertNotIn("sentinel", json.dumps(annotation_store.published(self.reopened())))

    def test_legacy_or_malformed_loaded_metadata_is_unknown_without_losing_the_assessment(
        self,
    ) -> None:
        self.record(diagnostic())
        path = Path(annotation_store.store_path(self.config))
        stored = json.loads(path.read_text())
        stored["entries"][0]["reading_diagnostic"] = {"secret": "sentinel"}
        path.write_text(json.dumps(stored))
        reopened = self.reopened()
        self.assertIn("assessment", reopened)
        self.assertIsNone(annotation_store.published(reopened).get("reading_diagnostic"))
        self.record(None, read_at=100)
        self.assertIsNone(annotation_store.published(self.reopened()).get("reading_diagnostic"))

    def test_late_assessment_cannot_replace_diagnostics_and_clear_prevents_resurrection(
        self,
    ) -> None:
        value = diagnostic()
        self.record(value, read_at=100)
        late = {"version": 1, "input": None, "capacity": None}
        self.record(late, read_at=90)
        self.assertEqual(value, annotation_store.published(self.reopened())["reading_diagnostic"])
        annotation_store.clear(self.config, self.state, "claude", "s1", now=110)
        self.assertEqual(annotation_store.OUTCOME_REFUSED, self.record(value, read_at=120))
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED, self.record(value, why=reading.WITHHELD_MODEL_FAILED)
        )
        self.assertIsNone(annotation_store.published(self.reopened()).get("reading_diagnostic"))

    def test_store_serialization_and_direct_publication_do_not_carry_unvalidated_metadata(
        self,
    ) -> None:
        self.record(diagnostic())
        entry = self.reopened()
        entry["reading_diagnostic"] = {"secret": "sentinel"}
        self.assertNotIn("sentinel", json.dumps(annotation_store.published(entry)))
        self.assertTrue(annotation_store.save(self.config, [entry]))
        self.assertNotIn("sentinel", Path(annotation_store.store_path(self.config)).read_text())

    def test_input_reservation_must_agree_with_the_outcomes_spend_flag(self) -> None:
        self.assertEqual(
            annotation_store.OUTCOME_REFUSED,
            self.record(diagnostic(), why=reading.WITHHELD_MODEL_FAILED),
        )
        self.assertNotIn("readings", self.reopened())


class ProducerDiagnosticTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config, _ = make_runtime(state_dir=Path(directory.name), state_home=directory.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.snapshots: list[dict[str, Any]] = []
        self.prompts: list[str] = []

    def produce(self, **over: Any) -> Any:
        self.assertIn("on_diagnostic", inspect.signature(reading.produce).parameters)

        def model(prompt: str, **_kwargs: Any) -> tuple[str, str]:
            self.prompts.append(prompt)
            return "{}", "ok"

        guarded = reading_policy.GuardedModel(
            self.config,
            model,
            lambda: 200.0,
            admit_prompt=analyze_capacity.Admission(
                "codex", "unknown", "", requested_maximum=524_288
            ),
        )
        arguments: dict[str, Any] = {
            "now": 200.0,
            "stamp_text": "fixture",
            "model": guarded,
            "read_agent_words": True,
            "on_diagnostic": self.snapshots.append,
        }
        arguments.update(over)
        return reading.produce(
            self.config,
            {"harness": "claude", "sid": "s1", "state": "working"},
            [{"n": 1, "at": 50.0, "goal": "request"}],
            [test_reading.WhatOnePressActuallyCostsAndProduces.FACT],
            **arguments,
        )

    def test_prepared_bytes_match_actual_call_and_unknown_source_stays_unknown(self) -> None:
        self.produce()
        diagnostic = self.snapshots[-1]
        self.assertEqual(len(self.prompts[0].encode()), diagnostic["prepared"]["prompt_bytes"])
        self.assertEqual(
            diagnostic["prepared"]["prompt_bytes"], diagnostic["input"]["prompt_bytes"]
        )
        self.assertEqual(1, diagnostic["selection"]["selected_messages"])
        self.assertIsNone(diagnostic["selection"]["selected_source_characters"])
        self.assertIsNone(diagnostic["selection"]["expanded_message_characters"])
        self.assertNotIn("whole", json.dumps(diagnostic))
        self.assertNotIn("request", json.dumps(diagnostic).replace("requested_maximum", ""))

    def test_postassembly_error_keeps_prepared_measurement_without_invocation(self) -> None:
        def broken() -> Any:
            raise RuntimeError("private source sentinel")

        with self.assertRaisesRegex(RuntimeError, "private source sentinel"):
            self.produce(record_coverage_lookup=broken)
        diagnostic = self.snapshots[-1]
        self.assertGreater(diagnostic["prepared"]["prompt_bytes"], 0)
        self.assertIsNone(diagnostic["input"])
        self.assertIsNone(diagnostic["capacity"])
        self.assertEqual([], self.prompts)
        self.assertNotIn("sentinel", json.dumps(diagnostic))

    def test_reused_sink_early_refusal_resets_prepared_and_model_measurements(self) -> None:
        self.produce()
        self.produce(record_withheld=reading.WITHHELD_RECORD_UNREAD)
        self.assertEqual(
            {"version": 1, "input": None, "capacity": None, "prepared": None, "selection": None},
            self.snapshots[-1],
        )

    def test_serialized_message_bytes_and_partial_characters_come_from_the_printed_row(
        self,
    ) -> None:
        self.assertIn("measure", inspect.signature(reading.build_prompt).parameters)
        words = '界🙂"\\' * 3000
        row: reading.LedgerEntry = {
            "id": "a",
            "at": 10.0,
            "type": "agent_message",
            "by": "agent",
            "author": "agent",
            "source": "transcript",
            "summary": "short",
            "agent_words": json.dumps("old excerpt"),
        }
        prompt, selected = reading.build_prompt(
            [row],
            goal="request",
            max_bytes=16000,
            measure=True,
            message_lookup=lambda _wanted, _cap: [
                {"id": "a", "at": 10.0, "words": words, "total": len(words)}
            ],
        )
        coverage = selected.diagnostic
        assert coverage is not None
        self.assertEqual(1, coverage["eligible_messages"])
        self.assertEqual(1, coverage["selected_messages"])
        printed = next(line for line in prompt.splitlines(keepends=True) if line.startswith("[1]"))
        self.assertEqual(len(printed.encode()), coverage["serialized_message_bytes"])
        self.assertEqual(selected.entries[0]["text_read"], coverage["expanded_message_characters"])
        self.assertGreater(coverage["expanded_message_characters"], 0)
        self.assertLess(
            coverage["expanded_message_characters"], coverage["selected_source_characters"]
        )
        self.assertEqual(len(words), coverage["selected_source_characters"])
        self.assertNotIn("whole", coverage)
        _, ordinary = reading.build_prompt([row], goal="request", max_bytes=16000)
        self.assertIsNone(ordinary.diagnostic)

    def test_unselected_rows_do_not_turn_selected_counts_into_whole_source_coverage(self) -> None:
        rows: list[reading.LedgerEntry] = [
            {
                "id": str(index),
                "at": float(index),
                "type": "agent_message",
                "by": "agent",
                "author": "agent",
                "source": "transcript",
                "summary": "x" * 3000,
                "agent_words": json.dumps("not necessarily printed"),
            }
            for index in (1, 2)
        ]
        prompt, selected = reading.build_prompt(rows, goal="request", max_bytes=6000, measure=True)
        coverage = selected.diagnostic
        assert coverage is not None
        self.assertEqual(2, coverage["eligible_messages"])
        self.assertEqual(1, coverage["selected_messages"])
        self.assertIsNone(coverage["expanded_message_characters"])
        self.assertIsNone(coverage["selected_source_characters"])
        printed = next(line for line in prompt.splitlines(keepends=True) if line.startswith("[1]"))
        self.assertEqual(len(printed.encode()), coverage["serialized_message_bytes"])

    def test_empty_selection_keeps_measured_construction_but_has_no_model_trace(self) -> None:
        result = self.produce(max_prompt_bytes=1)
        self.assertIsNone(result[0])
        diagnostic = self.snapshots[-1]
        self.assertEqual(0, diagnostic["prepared"]["prompt_bytes"])
        self.assertEqual(0, diagnostic["selection"]["selected_entries"])
        self.assertEqual(1, diagnostic["selection"]["eligible_entries"])
        self.assertIsNone(diagnostic["input"])
        self.assertEqual([], self.prompts)

    def test_captured_preparation_rejects_word_fields_and_impossible_counts(self) -> None:
        self.produce()
        validate = importlib.import_module("compass_runtime.analyze_diagnostics").validate
        base = self.snapshots[-1]
        for section, key, value in (
            ("prepared", "prompt_bytes", True),
            ("prepared", "build_elapsed_ms", -1),
            ("prepared", "words", "sentinel"),
            ("selection", "selected_entries", 2**53),
            ("selection", "selected_messages", 100),
            ("selection", "selected_source_characters", -1),
            ("selection", "serialized_message_bytes", base["prepared"]["prompt_bytes"] + 1),
            ("selection", "whole", True),
        ):
            with self.subTest(section=section, key=key):
                corrupt = copy.deepcopy(base)
                corrupt[section][key] = value
                self.assertIsNone(validate(corrupt))
