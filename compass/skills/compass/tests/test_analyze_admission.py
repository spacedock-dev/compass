"""Requested Analyze admits the actual prompt before any durable reservation."""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import inspect
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import claude_settings, observer, reading, reading_policy, supervise

from .support import make_runtime

if TYPE_CHECKING:
    from collections.abc import Iterator


class AnalyzeAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config, _ = make_runtime(state_dir=Path(directory.name), state_home=directory.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def guard(self, model: Any, **kwargs: Any) -> Any:
        self.assertIn("admit_prompt", inspect.signature(reading_policy.GuardedModel).parameters)
        return reading_policy.GuardedModel(self.config, model, lambda: 100.0, **kwargs)

    def module(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.analyze_capacity"))
        return importlib.import_module("compass_runtime.analyze_capacity")

    def test_actual_prompt_refusal_precedes_marker_reservation_and_spawn(self) -> None:
        model = mock.Mock(return_value=("reply", "ok"))
        model.available = mock.Mock(return_value=True)
        marker, reserved = mock.Mock(), mock.Mock()
        admission = mock.Mock(return_value="context-admission")
        guarded = self.guard(
            model, admit_prompt=admission, before_reserve=marker, on_reserved=reserved
        )
        with mock.patch.object(reading_policy, "reserve") as reserve:
            self.assertEqual(
                ("", "context-admission"), guarded("assembled 界🙂", output_cap_bytes=1)
            )
        admission.assert_called_once_with("assembled 界🙂")
        marker.assert_not_called()
        reserve.assert_not_called()
        reserved.assert_not_called()
        model.assert_not_called()
        self.assertFalse(guarded.reserved)

    def test_admitted_call_keeps_the_existing_marker_charge_spawn_order(self) -> None:
        order: list[str] = []

        def model(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
            order.append("model")
            return "reply", "ok"

        guarded = self.guard(
            model,
            admit_prompt=lambda _prompt: order.append("admit"),
            before_reserve=lambda: order.append("marker"),
            on_reserved=lambda: order.append("reserved"),
        )
        self.assertEqual(("reply", "ok"), guarded("small", output_cap_bytes=1))
        self.assertEqual(["admit", "marker", "reserved", "model"], order)
        self.assertTrue(guarded.reserved)

    def test_pause_cancel_shutdown_and_moved_destination_outrank_capacity(self) -> None:
        for gate in ("pause", "cancel", "shutdown", "destination"):
            with self.subTest(gate=gate):
                admission = mock.Mock(return_value="context-admission")
                model = mock.Mock(return_value=("reply", "ok"))
                model.available = mock.Mock(return_value=True)
                guarded = self.guard(
                    model,
                    admit_prompt=admission,
                    cancelled=lambda gate=gate: gate == "cancel",
                    destination="before",
                    resolve_destination=lambda gate=gate: (
                        "after" if gate == "destination" else "before"
                    ),
                )
                if gate == "pause":
                    reading_policy.set_consent(self.config, False, now=100)
                if gate == "shutdown":
                    supervise._SHUTDOWN.set()
                if gate in {"pause", "destination"}:
                    with self.assertRaises(reading_policy.RefusedError):
                        guarded("large", output_cap_bytes=1)
                else:
                    self.assertEqual(
                        "cancelled" if gate == "cancel" else "closed",
                        guarded("large", output_cap_bytes=1)[1],
                    )
                admission.assert_not_called()
                model.assert_not_called()
                reading_policy.resume(self.config, now=100)
                supervise._SHUTDOWN.clear()

    def test_policy_failure_after_reservation_has_a_different_spend_status(self) -> None:
        guarded = self.guard(
            lambda *_a, **_k: ("", "context-config"), admit_prompt=lambda _prompt: None
        )
        result = guarded("small", output_cap_bytes=1)
        self.assertEqual(("", "context-config-after-reserve"), result)
        self.assertTrue(guarded.reserved)
        late = reading._call_failed(guarded, result[1])
        initial = reading._call_failed(guarded, "context-config")
        assert late is not None and initial is not None
        self.assertTrue(late[1])
        self.assertFalse(initial[1])

    def test_cancellation_during_admission_never_reaches_the_marker(self) -> None:
        cancelled = threading.Event()
        marker = mock.Mock()

        def admit(_prompt: str) -> None:
            cancelled.set()

        guarded = self.guard(
            mock.Mock(), admit_prompt=admit, cancelled=cancelled.is_set, before_reserve=marker
        )
        self.assertEqual(("", "cancelled"), guarded("small", output_cap_bytes=1))
        marker.assert_not_called()
        self.assertFalse(guarded.reserved)

    def test_high_requested_maximum_is_independent_of_a_small_actual_prompt(self) -> None:
        admission = self.module().Admission("codex", "unknown", "", requested_maximum=2_097_152)
        self.assertIsNone(admission("small 界🙂"))
        self.assertEqual(13, admission.measurement["prompt_bytes"])
        self.assertFalse(admission.measurement["fit_verified"])
        self.assertEqual("context-admission", admission("x" * 524_289))
        self.assertEqual(2_097_152, admission.measurement["requested_maximum"])

    def test_fresh_managed_capacity_after_reservation_controls_the_unchanged_prompt(self) -> None:
        model_id = self.config.claude_reading_model
        restrictions = (
            {
                "autoCompactWindow": 200_000,
                "env": {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "190000"},
                "modelSettings": {model_id: {"autoCompactWindow": 180_000}},
            },
            {"env": {"ANTHROPIC_BASE_URL": "https://synthetic.invalid"}},
            {"modelOverrides": {model_id: "synthetic-remapped-model"}},
        )
        for timing in ("on_reserved", "after_preparation"):
            for restriction in restrictions:
                for prompt in ('small "界🙂"', "x" * 600_000):
                    with self.subTest(timing=timing, restriction=restriction, size=len(prompt)):
                        self.check_fresh_capacity(timing, restriction, prompt)

    def check_fresh_capacity(self, timing: str, restriction: dict[str, Any], prompt: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            managed = root / "etc/claude-code/managed-settings.json"
            managed.parent.mkdir(parents=True)
            managed.write_text("{}")
            original_resolve = claude_settings.resolve
            original_prepare = observer.prepare_claude_exec
            observed: list[claude_settings.Controls] = []
            invoked: list[str] = []
            reservations: list[bool] = []

            def resolve(model: str, **_kwargs: Any) -> claude_settings.Controls:
                controls = original_resolve(
                    model,
                    environ={"HOME": "/synthetic-home", "USER": "synthetic-user"},
                    root=root,
                    system="Linux",
                )
                observed.append(controls)
                return controls

            def reserved() -> None:
                reservations.append(True)
                if timing == "on_reserved":
                    managed.write_text(json.dumps(restriction))

            @contextlib.contextmanager
            def prepare(*args: Any, **kwargs: Any) -> Iterator[Any]:
                with original_prepare(*args, **kwargs) as prepared:
                    if timing == "after_preparation":
                        managed.write_text(json.dumps(restriction))
                    yield prepared

            def runner(command: list[str], **kwargs: Any) -> Any:
                invoked.append(kwargs["input"])
                kwargs["stdout"].write(b"{}")
                return subprocess.CompletedProcess(command, 0)

            admission = self.module().Admission(
                "claude",
                self.config.claude_reading_model,
                observer.CLAUDE_READING_SYSTEM_PROMPT,
                requested_maximum=2_097_152,
            )
            model = reading.ClaudeReadingModel(
                self.config,
                runner=runner,
                binary_resolver=lambda _name: "/never-launched/claude",
                analyze=True,
            )
            guard = self.guard(
                model, provider="claude", admit_prompt=admission, on_reserved=reserved
            )
            used = reading_policy.status(self.config, now=100)["used"]
            with (
                mock.patch.object(claude_settings, "resolve", side_effect=resolve),
                mock.patch.object(observer, "prepare_claude_exec", side_effect=prepare),
                mock.patch.object(observer, "reading_workdir_root", return_value=str(root)),
            ):
                result = guard(prompt, output_cap_bytes=100)
            fits = len(prompt) < 600_000
            self.assertEqual(("{}", "ok") if fits else ("", "context-config-after-reserve"), result)
            self.assertEqual([prompt] if fits else [], invoked)
            self.assertEqual([True], reservations)
            self.assertEqual(used + 1, reading_policy.status(self.config, now=100)["used"])
            self.assertTrue(guard.reserved)
            self.assertEqual(2_097_152, admission.measurement["maximum_prompt_bytes"])
            self.assertTrue(admission.measurement["allowed"])
            self.assertEqual(result[1], self.trace(guard)["outcome"])
            self.assertEqual(len(prompt.encode()), self.trace(guard)["prompt_bytes"])
            if "autoCompactWindow" in restriction:
                self.assertEqual({180_000, 190_000, 200_000}, set(observed[-1].window_limits))
            else:
                self.assertIn(observed[-1].deployment, {"gateway", "unknown"})

    def test_capacity_rechecks_reduced_dynamic_and_empty_windows_at_the_call(self) -> None:
        module = self.module()
        admission = module.Admission(
            "claude", "claude-sonnet-5-5", "system", requested_maximum=2_097_152
        )
        for controls, expected in (
            (
                claude_settings.Controls(deployment="direct", window_limits=(200_000,)),
                "context-admission",
            ),
            (
                claude_settings.Controls(deployment="direct", window_limits=(128_000,)),
                "context-no-room",
            ),
            (claude_settings.Controls(refusal="dynamic-policy"), "context-dynamic"),
            (claude_settings.Controls(refusal="fallback-policy-conflict"), "context-fallback"),
            (claude_settings.Controls(refusal="context-config"), "context-config"),
        ):
            with (
                self.subTest(expected=expected),
                mock.patch.object(claude_settings, "resolve", return_value=controls),
            ):
                self.assertEqual(expected, admission("x" * 200_000))
                self.assertFalse(admission.measurement["fit_verified"])
        with mock.patch.object(
            claude_settings, "resolve", return_value=claude_settings.Controls(deployment="direct")
        ):
            self.assertIsNone(admission("x" * 200_000))

    def test_default_and_unasked_guards_do_not_apply_analyze_admission(self) -> None:
        admission = mock.Mock(return_value="context-admission")

        def model(*_args: Any, **_kwargs: Any) -> tuple[str, str]:
            return "reply", "ok"

        self.assertEqual(("reply", "ok"), self.guard(model)("small", output_cap_bytes=1))
        with mock.patch.object(reading_policy, "unasked_status", return_value={"reason": ""}):
            guarded = self.guard(model, admit_prompt=admission, unasked=True)
            self.assertEqual(("reply", "ok"), guarded("small", output_cap_bytes=1))
        admission.assert_not_called()

    def test_model_and_provenance_use_the_same_explicit_analyze_option(self) -> None:
        self.assertIn("analyze", inspect.signature(reading.ClaudeReadingModel).parameters)
        for analyze in (False, True):
            with (
                self.subTest(analyze=analyze),
                mock.patch.object(observer, "claude_exec", return_value=("{}", "ok")) as execute,
            ):
                model = reading.ClaudeReadingModel(self.config, analyze=analyze)
                self.assertEqual(("{}", "ok"), model("unchanged", output_cap_bytes=1))
                self.assertEqual(analyze, execute.call_args.kwargs["analyze"])
                provenance = model.provenance()
                self.assertEqual(
                    observer.claude_reading_provenance(self.config, analyze=analyze), provenance
                )
                self.assertIsNone(provenance["resolved_model"])
        self.assertNotEqual(
            observer.claude_reading_provenance(self.config)["envelope_digest"],
            observer.claude_reading_provenance(self.config, analyze=True)["envelope_digest"],
        )

    def trace(self, guarded: Any) -> dict[str, Any]:
        value = getattr(guarded, "analyze_diagnostic", None)
        self.assertIsInstance(value, dict, "each requested invocation needs its own trace")
        assert isinstance(value, dict)
        return value

    def test_trace_counts_exact_assembled_bytes_and_elapsed_seam_time(self) -> None:
        admission = self.module().Admission("codex", "unknown", "", requested_maximum=2_097_152)
        guarded = self.guard(lambda *_a, **_k: ("private reply", "ok"), admit_prompt=admission)
        with mock.patch(
            "compass_runtime.reading_policy.time.monotonic", side_effect=(10.0, 10.125)
        ):
            guarded('A"界🙂\\', output_cap_bytes=1)
        self.assertEqual(
            {
                "kind": "actual-input",
                "prompt_bytes": 10,
                "elapsed_ms": 125,
                "outcome": "ok",
                "attempt_reserved": True,
                "model_invoked": True,
            },
            self.trace(guarded),
        )

    def test_reused_guard_clears_capacity_before_unavailable_preflight(self) -> None:
        admission = self.module().Admission("codex", "unknown", "", requested_maximum=2_097_152)
        model = mock.Mock(return_value=("reply", "ok"))
        model.available.return_value = True
        guarded = self.guard(model, admit_prompt=admission)
        guarded("first private prompt", output_cap_bytes=1)
        self.assertIsNotNone(admission.measurement)
        model.available.return_value = False
        with mock.patch("compass_runtime.reading_policy.time.monotonic", side_effect=(20.0, 20.25)):
            self.assertEqual(("", "unavailable"), guarded("界🙂", output_cap_bytes=1))
        self.assertIsNone(admission.measurement, "a preflight refusal cannot retain prior capacity")
        trace = self.trace(guarded)
        self.assertEqual(7, trace["prompt_bytes"])
        self.assertEqual(250, trace["elapsed_ms"])
        self.assertEqual("unavailable", trace["outcome"])
        self.assertFalse(trace["attempt_reserved"])
        self.assertFalse(trace["model_invoked"])

    def test_trace_distinguishes_initial_refusal_from_counted_late_failure(self) -> None:
        for admit, model_status, outcome, reserved in (
            ("context-admission", "ok", "context-admission", False),
            (None, "context-config", "context-config-after-reserve", True),
            (None, "error", "error", True),
        ):
            with self.subTest(outcome=outcome):
                guarded = self.guard(
                    lambda *_a, model_status=model_status, **_k: (
                        "private error sentinel",
                        model_status,
                    ),
                    admit_prompt=lambda _prompt, admit=admit: admit,
                )
                guarded("private input sentinel", output_cap_bytes=1)
                trace = self.trace(guarded)
                self.assertEqual(outcome, trace["outcome"])
                self.assertEqual(reserved, trace["attempt_reserved"])
                self.assertEqual(reserved, trace["model_invoked"])
                self.assertNotIn("sentinel", json.dumps(trace))

    def test_reused_guard_clears_capacity_before_cancelled_preflight(self) -> None:
        admission = self.module().Admission("codex", "unknown", "", requested_maximum=2_097_152)
        cancelled = threading.Event()
        guarded = self.guard(
            lambda *_a, **_k: ("reply", "ok"),
            admit_prompt=admission,
            cancelled=cancelled.is_set,
        )
        guarded("first prompt", output_cap_bytes=1)
        cancelled.set()
        self.assertEqual(("", "cancelled"), guarded("second", output_cap_bytes=1))
        self.assertIsNone(admission.measurement)
        trace = self.trace(guarded)
        self.assertEqual(6, trace["prompt_bytes"])
        self.assertEqual("cancelled", trace["outcome"])
        self.assertFalse(trace["attempt_reserved"])
        self.assertFalse(trace["model_invoked"])

    def test_exception_and_unknown_outcomes_never_publish_error_words(self) -> None:
        for fails_before_reserve in (False, True):
            with self.subTest(fails_before_reserve=fails_before_reserve):
                guarded = self.guard(
                    mock.Mock(side_effect=RuntimeError("secret error sentinel")),
                    admit_prompt=lambda _prompt: None,
                    before_reserve=(
                        mock.Mock(side_effect=RuntimeError("secret marker sentinel"))
                        if fails_before_reserve
                        else None
                    ),
                )
                with self.assertRaises(RuntimeError):
                    guarded("secret input sentinel", output_cap_bytes=1)
                trace = self.trace(guarded)
                self.assertEqual("error", trace["outcome"])
                self.assertEqual(not fails_before_reserve, trace["attempt_reserved"])
                self.assertEqual(not fails_before_reserve, trace["model_invoked"])
                self.assertNotIn("sentinel", json.dumps(trace))
        guarded = self.guard(
            lambda *_a, **_k: ("", "secret outcome sentinel"), admit_prompt=lambda _p: None
        )
        guarded("secret input sentinel", output_cap_bytes=1)
        self.assertEqual("error", self.trace(guarded)["outcome"])

    def test_pause_refusal_trace_is_unspent_and_default_callers_have_no_trace(self) -> None:
        model = lambda *_a, **_k: ("reply", "ok")  # noqa: E731
        ordinary = self.guard(model)
        ordinary("ordinary", output_cap_bytes=1)
        self.assertIsNone(getattr(ordinary, "analyze_diagnostic", None))
        guarded = self.guard(model, admit_prompt=lambda _p: None)
        reading_policy.set_consent(self.config, False, now=100)
        with self.assertRaises(reading_policy.RefusedError):
            guarded("not sent", output_cap_bytes=1)
        trace = self.trace(guarded)
        self.assertEqual("refused", trace["outcome"])
        self.assertFalse(trace["attempt_reserved"])
        self.assertFalse(trace["model_invoked"])
