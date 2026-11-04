"""Prompt-bound marker permits distinguish fresh charges from historical replay."""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import unittest
from typing import Any
from unittest import mock

from compass_runtime import (
    analyze_capacity,
    analyze_diagnostics,
    claude_settings,
    observer,
    reading,
)
from compass_runtime import reading_policy as policy

from . import test_reading_long_markers as marker_tests
from .test_reading_pass_types import diagnostic


class LongGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = marker_tests.LongMarkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.owner = self.fixture.begin()
        self.module = self.fixture.module()
        self.calls: list[tuple[str, int]] = []
        self.reservations: list[bool] = []
        self.received: list[tuple[str, int]] = []

    def model(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        self.calls.append((prompt, output_cap_bytes))
        return "reply", "ok"

    def reserve_prompt(self, prompt: str, output_cap_bytes: int) -> Any:
        self.received.append((prompt, output_cap_bytes))
        self.assertEqual(10, output_cap_bytes)
        request = self.fixture.request(self.owner)
        request.update(
            prompt_bytes=len(prompt.encode("utf-8", "replace")),
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest(),
        )
        return self.module.reserve(self.config, self.owner, request=request, now=100)

    def guard(self, **changes: Any) -> Any:
        self.assertIn("reserve_prompt", inspect.signature(policy.GuardedModel).parameters)
        options = {
            "provider": "claude",
            "reserve_prompt": self.reserve_prompt,
            "admit_prompt": analyze_capacity.Admission(
                "codex", "unknown", "", requested_maximum=524_288
            ),
            "on_reserved": lambda: self.reservations.append(True),
            **changes,
        }
        return policy.GuardedModel(
            self.config, options.pop("model", self.model), lambda: 100, **options
        )

    def captured(self, guard: Any, prompt: str = "界🙂") -> dict[str, Any]:
        snapshots: list[dict[str, Any]] = []
        capture = analyze_diagnostics.Capture(snapshots.append)
        selection = {**diagnostic()["selection"], "serialized_message_bytes": 0}
        capture.prepared(prompt, selection, capture.start())
        try:
            guard(prompt, output_cap_bytes=10)
        finally:
            capture.called(guard)
            self.assertEqual(3, len(snapshots))
            self.assertIsNotNone(analyze_diagnostics.validate(snapshots[-1]))
            self.last = snapshots[-1]
        return snapshots[-1]

    def test_exact_prompt_and_cap_reach_reservation_and_adapter_once(self) -> None:
        guard = self.guard()
        value = self.captured(guard)
        self.assertEqual([("界🙂", 10)], self.received)
        self.assertEqual(self.received, self.calls)
        self.assertEqual([True], self.reservations)
        self.assertEqual(1, self.fixture.spends())
        self.assertTrue(value["input"]["attempt_reserved"])
        self.assertTrue(value["input"]["model_invoked"])
        slot = self.fixture.loaded(self.owner)["passes"][0]
        self.assertEqual(7, slot["request"]["prompt_bytes"])
        self.assertEqual(
            hashlib.sha256("界🙂".encode()).hexdigest(), slot["request"]["prompt_sha256"]
        )
        self.assertNotIn("界", json.dumps(slot, ensure_ascii=False))

    def test_post_charge_write_failure_counts_fresh_attempt_without_adapter_entry(self) -> None:
        guard = self.guard()
        original = self.module._write

        def write(path: Any, marker: Any) -> Any:
            if marker["passes"][-1]["state"] == "charged":
                raise OSError("private failure")
            return original(path, marker)

        with (
            mock.patch.object(self.module, "_write", side_effect=write),
            self.assertRaises(policy.RefusedError),
        ):
            self.captured(guard)
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual([True], self.reservations)
        self.assertEqual([], self.calls)
        self.assertTrue(guard.reserved)
        self.assertTrue(self.last["input"]["attempt_reserved"])
        self.assertFalse(self.last["input"]["model_invoked"])
        self.assertEqual("refused", self.last["input"]["outcome"])
        self.assertIsNone(self.fixture.loaded(self.owner)["passes"][0]["charged"])

    def test_replay_has_no_new_reservation_or_adapter_and_resets_observation(self) -> None:
        guard = self.guard()
        first = self.captured(guard)
        with self.assertRaises(policy.RefusedError):
            self.captured(guard)
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual([True], self.reservations)
        self.assertEqual([("界🙂", 10)], self.calls)
        self.assertFalse(guard.reserved)
        self.assertFalse(self.last["input"]["attempt_reserved"])
        self.assertFalse(self.last["input"]["model_invoked"])
        self.assertTrue(first["input"]["attempt_reserved"])
        self.assertTrue(self.fixture.loaded(self.owner)["passes"][0]["charged"])

    def test_pending_write_failure_is_uncharged_without_adapter(self) -> None:
        guard = self.guard()
        with (
            mock.patch.object(self.module, "_write", side_effect=OSError),
            self.assertRaises(policy.RefusedError),
        ):
            self.captured(guard)
        self.assertEqual(0, self.fixture.spends())
        self.assertEqual([], self.calls)
        self.assertEqual([], self.reservations)
        self.assertFalse(self.last["input"]["attempt_reserved"])

    def test_actual_capacity_refusal_never_enters_marker_callback(self) -> None:
        guard = self.guard()
        self.captured(guard, "x" * 524_289)
        self.assertEqual([], self.received)
        self.assertEqual([], self.calls)
        self.assertEqual(0, self.fixture.spends())
        self.assertFalse(self.last["capacity"]["allowed"])
        self.assertFalse(self.last["input"]["attempt_reserved"])

    def test_pause_precedes_marker_and_capacity(self) -> None:
        guard = self.guard()
        policy.set_consent(self.config, False, now=100)
        with self.assertRaises(policy.RefusedError):
            self.captured(guard)
        self.assertIsNone(self.last["capacity"])
        self.assertEqual([], self.received)
        self.assertEqual(0, self.fixture.spends())

    def test_prompt_seam_without_capacity_hook_still_reports_attempt_and_checks_permission(
        self,
    ) -> None:
        guard = self.guard(admit_prompt=None)
        self.captured(guard)
        self.assertTrue(self.last["input"]["attempt_reserved"])
        self.assertIsNone(self.last["capacity"])
        policy.set_consent(self.config, False, now=100)
        with self.assertRaises(policy.RefusedError):
            self.captured(guard)
        self.assertFalse(self.last["input"]["attempt_reserved"])
        self.assertEqual(1, len(self.received))

    def test_incompatible_reservation_hooks_and_unasked_fail_at_construction(self) -> None:
        for options in (
            {"before_reserve": lambda: "job"},
            {"reserve_with": policy.reserve_monitor},
            {"unasked": True},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.guard(**options)
        self.assertEqual([], self.received)
        self.assertEqual(0, self.fixture.spends())

    def test_launch_flag_without_fresh_charge_never_enters_adapter(self) -> None:
        guard = self.guard(reserve_prompt=lambda *_: self.module.Permit(launch=True, charged=True))
        with self.assertRaises(policy.RefusedError):
            self.captured(guard)
        self.assertEqual([], self.calls)
        self.assertEqual([], self.reservations)
        self.assertFalse(guard.reserved)

    def test_final_prepared_claude_restriction_keeps_charge_and_initial_allowed_capacity(
        self,
    ) -> None:
        root = self.config.state_dir / "managed-root"
        managed = root / "etc/claude-code/managed-settings.json"
        managed.parent.mkdir(parents=True)
        managed.write_text("{}")
        original_resolve = claude_settings.resolve
        original_prepare = observer.prepare_claude_exec

        def resolve(model: str, **_kwargs: Any) -> Any:
            return original_resolve(
                model,
                environ={"HOME": "/synthetic", "USER": "synthetic"},
                root=root,
                system="Linux",
            )

        @contextlib.contextmanager
        def prepare(*args: Any, **kwargs: Any) -> Any:
            with original_prepare(*args, **kwargs) as prepared:
                managed.write_text(json.dumps({"env": {"DISABLE_COMPACT": "0"}}))
                yield prepared

        def runner(*_args: Any, **_kwargs: Any) -> Any:
            self.fail("Final PreparedClaude restriction must prevent CLI entry")

        model = reading.ClaudeReadingModel(
            self.config,
            runner=runner,
            binary_resolver=lambda _: "/never-launched/claude",
            analyze=True,
        )
        admission = analyze_capacity.Admission(
            "claude",
            self.config.claude_reading_model,
            observer.CLAUDE_READING_SYSTEM_PROMPT,
            requested_maximum=2_097_152,
        )
        guard = self.guard(model=model, admit_prompt=admission)
        with (
            mock.patch.object(claude_settings, "resolve", side_effect=resolve),
            mock.patch.object(observer, "prepare_claude_exec", side_effect=prepare),
            mock.patch.object(observer, "reading_workdir_root", return_value=str(root)),
        ):
            self.captured(guard)
        self.assertEqual(1, self.fixture.spends())
        self.assertEqual([True], self.reservations)
        self.assertTrue(self.last["capacity"]["allowed"])
        self.assertTrue(self.last["input"]["attempt_reserved"])
        self.assertTrue(self.last["input"]["model_invoked"])
        self.assertEqual("context-config-after-reserve", self.last["input"]["outcome"])
