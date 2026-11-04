"""Real adapters require a fresh bound slot and a current context at runner entry."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import hashlib
import importlib
import importlib.util
import os
import subprocess
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import (
    analyze_diagnostics,
    annotations,
    observer,
    reading,
    reading_route,
    settings,
    supervise,
)
from compass_runtime import reading_long_control as control
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_jobs as jobs
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_policy as policy

from . import test_reading_long_context as context_tests
from .test_reading_pass_types import diagnostic


class LongExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_execution"))
        self.module = importlib.import_module("compass_runtime.reading_long_execution")
        self.fixture = context_tests.ActiveContextTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.active = self.fixture.config, self.fixture.active
        self.calls: list[dict[str, Any]] = []
        self.reserved: list[bool] = []
        patcher = mock.patch.object(
            observer, "reading_workdir_root", return_value=str(self.config.state_dir)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, command: Any, **kwargs: Any) -> Any:
        self.calls.append({"command": command, **kwargs})
        if hasattr(kwargs["stdout"], "write"):
            kwargs["stdout"].write(b"reply")
        else:
            Path(command[command.index("--output-last-message") + 1]).write_text("reply")
        return subprocess.CompletedProcess(command, 0)

    def guard(self, **changes: Any) -> Any:
        return self.module.guard(
            self.config,
            self.fixture.context,
            1,
            **{
                "clock": lambda: 100,
                "runner": self.runner,
                "binary_resolver": lambda name: f"/never/{name}",
                "on_reserved": lambda: self.reserved.append(True),
                **changes,
            },
        )

    def call(self, guard: Any, prompt: str = "界🙂", cap: int = 10) -> Any:
        seen: list[dict[str, Any]] = []
        capture = analyze_diagnostics.Capture(seen.append)
        capture.prepared(
            prompt, {**diagnostic()["selection"], "serialized_message_bytes": 0}, capture.start()
        )
        try:
            return guard(prompt, output_cap_bytes=cap)
        finally:
            capture.called(guard)
            self.last = seen[-1]
            self.assertIsNotNone(analyze_diagnostics.validate(self.last))

    def proof(self, calls: int, *, invoked: bool) -> None:
        value = inspection.inspect(self.config, self.active.job.id, now=100)
        assert value.exact is not None
        self.assertEqual(calls, value.exact.calls)
        self.assertEqual(bool(calls), self.last["input"]["attempt_reserved"])
        self.assertEqual(invoked, self.last["input"]["model_invoked"])
        self.assertEqual([True] if calls else [], self.reserved)

    def test_exact_unchanged_prompt_cap_model_timeout_and_replay(self) -> None:
        guard = self.guard()
        self.assertIsInstance(guard.model, reading.ClaudeReadingModel)
        self.assertTrue(guard.model.analyze)
        self.assertEqual(("reply", "ok"), self.call(guard))
        self.assertEqual("界🙂", self.calls[0]["input"])
        self.assertEqual(180, self.calls[0]["timeout"])
        self.proof(1, invoked=True)
        marker = markers.load(self.config, self.active.job.id)
        assert marker is not None
        req = marker["passes"][0]["request"]
        self.assertEqual(7, req["prompt_bytes"])
        self.assertEqual(hashlib.sha256("界🙂".encode()).hexdigest(), req["prompt_sha256"])
        self.assertEqual(10, marker["header"]["plan"]["limits"]["reply_bytes"])
        with self.assertRaises(policy.RefusedError):
            self.call(guard)
        self.assertEqual(1, len(self.calls))
        self.assertFalse(self.last["input"]["attempt_reserved"])

    def test_actual_reply_cap_mismatch_refuses_before_pending_or_charge(self) -> None:
        with self.assertRaises(policy.RefusedError):
            self.call(self.guard(), cap=9)
        self.proof(0, invoked=False)
        self.assertEqual([], markers.load(self.config, self.active.job.id)["passes"])

    def test_codex_fallback_uses_real_adapter_and_cannot_reuse_runner_permission(self) -> None:
        patcher = mock.patch.object(
            reading_route,
            "_state",
            side_effect=lambda provider, _which: "usable" if provider == "codex" else "missing",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        route = self.fixture.module.describe(self.config, "claude")
        self.assertEqual("codex", route.provider)
        header = jobs.live_header(self.active.owner.live)
        assert header is not None
        binding = {
            key: value
            for key, value in header.items()
            if key not in ("version", "nonce", "lineage", "epoch")
        }
        binding.update(
            provider=route.provider,
            scope_sha256=self.fixture.module.scope_digest(route, self.fixture.scope),
            destination_sha256=self.fixture.module.destination_digest(route),
        )
        prepared = policy.prepare_long_job(
            permission=self.fixture.permission,
            binding=binding,
            call_timeout_ms=180_000,
            clock=lambda: self.fixture.clock[0],
        )
        reading.end_job(self.config, self.fixture.key)
        self.active = control.admit(
            self.config,
            self.fixture.key,
            provider="codex",
            label="Codex",
            job=prepared,
            permission=self.fixture.permission,
            now=100,
        )
        self.fixture.context = self.fixture.module.Context(self.active, route, self.fixture.scope)
        guard = self.guard()
        self.assertIsInstance(guard.model, reading.CodexReadingModel)
        self.assertEqual(("reply", "ok"), self.call(guard))
        self.assertEqual(180, self.calls[0]["timeout"])
        self.proof(1, invoked=True)
        with self.assertRaises(policy.RefusedError):
            guard.model("界🙂", output_cap_bytes=10)
        self.assertEqual(1, len(self.calls))

    def test_invalid_utf8_cannot_bind_replacement_bytes_to_a_different_wire_prompt(self) -> None:
        with self.assertRaises(policy.RefusedError):
            self.call(self.guard(), prompt="bad\ud800")
        self.proof(0, invoked=False)
        self.assertEqual([], self.calls)

    def test_pause_resume_before_reservation_cannot_refresh_permission(self) -> None:
        guard = self.guard()
        policy.set_consent(self.config, False, now=100)
        policy.resume(self.config, now=100)
        with self.assertRaises(policy.RefusedError):
            self.call(guard)
        self.proof(0, invoked=False)

    def test_target_edit_before_reservation_is_unspent(self) -> None:
        guard = self.guard()
        annotations.annotate(
            self.config, self.fixture.state, "claude", self.fixture.sid, goal="Changed", now=101
        )
        with self.assertRaises(policy.RefusedError):
            self.call(guard)
        self.proof(0, invoked=False)

    def test_clear_after_charge_prevents_adapter_entry(self) -> None:
        def reserved() -> None:
            self.reserved.append(True)
            annotations.clear(self.config, self.fixture.state, "claude", self.fixture.sid)

        with self.assertRaises(policy.RefusedError):
            self.call(self.guard(on_reserved=reserved))
        self.proof(1, invoked=False)
        self.assertEqual([], self.calls)

    def test_settings_change_after_adapter_preparation_prevents_runner(self) -> None:
        original = observer.prepare_claude_exec

        @contextlib.contextmanager
        def prepare(*args: Any, **kwargs: Any) -> Any:
            with original(*args, **kwargs) as prepared:
                settings.save(self.config, {"analyze_prompt_bytes": 2_097_152})
                yield prepared

        with (
            mock.patch.object(observer, "prepare_claude_exec", prepare),
            self.assertRaises(policy.RefusedError),
        ):
            self.call(self.guard())
        self.proof(1, invoked=True)
        self.assertEqual([], self.calls)
        self.assertEqual([], list(self.config.state_dir.glob("reading-claude-*")))

    def test_destination_moves_after_reservation_no_adapter_or_refund(self) -> None:
        def reserved() -> None:
            self.reserved.append(True)
            self.fixture.destination = "moved.example"

        with self.assertRaises(policy.RefusedError):
            self.call(self.guard(on_reserved=reserved))
        self.proof(1, invoked=False)
        self.assertEqual([], self.calls)

    def test_full_timeout_unavailable_after_preparation_never_shortens_runner_timeout(self) -> None:
        original = observer.prepare_claude_exec

        @contextlib.contextmanager
        def prepare(*args: Any, **kwargs: Any) -> Any:
            with original(*args, **kwargs) as prepared:
                self.fixture.clock[0] = 20.001
                yield prepared

        with (
            mock.patch.object(observer, "prepare_claude_exec", prepare),
            self.assertRaises(policy.RefusedError),
        ):
            self.call(self.guard())
        self.proof(1, invoked=True)
        self.assertEqual([], self.calls)

    def test_slot_read_delay_is_before_the_final_timeout_check(self) -> None:
        self.assertTrue(hasattr(self.module, "_require_slot"))
        original = self.module._require_slot

        def delayed(*args: Any, **kwargs: Any) -> None:
            original(*args, **kwargs)
            self.fixture.clock[0] = 20.001

        with (
            mock.patch.object(self.module, "_require_slot", side_effect=delayed),
            self.assertRaises(policy.RefusedError),
        ):
            self.call(self.guard())
        self.proof(1, invoked=False)
        self.assertEqual([], self.calls)

    def test_cancel_after_charge_retains_attempt_without_adapter(self) -> None:
        def reserved() -> None:
            self.reserved.append(True)
            reading.cancel_job(self.config, self.fixture.key, self.active.job.id, now=101)

        self.assertEqual(("", "cancelled"), self.call(self.guard(on_reserved=reserved)))
        self.proof(1, invoked=False)
        self.assertEqual([], self.calls)

    def test_cancel_during_actual_commit_wait_rolls_back_receipt(self) -> None:
        guard = self.guard()
        entered = threading.Event()
        original = supervise.admitting

        @contextlib.contextmanager
        def admitting() -> Any:
            entered.set()
            with original() as opened:
                yield opened

        # Wait specifically at the reservation admission, not at a preflight read.
        original_reserve = policy.reserve_registered_pass

        def reserving(*args: Any, **kwargs: Any) -> Any:
            with mock.patch.object(supervise, "admitting", admitting):
                return original_reserve(*args, **kwargs)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with mock.patch.object(policy, "reserve_registered_pass", reserving), supervise._LOCK:
                pending = pool.submit(self.call, guard)
                self.assertTrue(entered.wait(5))
                self.assertEqual(
                    (True, None),
                    reading.cancel_job(self.config, self.fixture.key, self.active.job.id, now=101),
                )
            with self.assertRaises(policy.RefusedError):
                pending.result(timeout=5)
        self.proof(0, invoked=False)
        self.assertEqual([], self.calls)

    def test_malformed_owner_and_ordinal_cannot_construct_guard(self) -> None:
        for ordinal in (True, 0, 5):
            with self.subTest(ordinal=ordinal), self.assertRaises(ValueError):
                self.module.guard(self.config, self.fixture.context, ordinal)
        foreign = dataclasses.replace(
            self.fixture.context,
            active=dataclasses.replace(
                self.active, owner=dataclasses.replace(self.active.owner, owner="f" * 32)
            ),
        )
        with self.assertRaises(policy.RefusedError):
            self.module.guard(self.config, foreign, 1)

    def test_wrapped_real_supervisor_keeps_output_limits_and_late_cancel_handover(self) -> None:
        group = mock.Mock()
        group._over_limit.return_value = False
        group._oversized = False
        spawned: list[dict[str, Any]] = []

        def spawn(_command: Any, **kwargs: Any) -> Any:
            spawned.append(kwargs)
            return group

        def run_group(actual: Any, _input: Any, timeout: Any, on_spawn: Any) -> int:
            self.assertIs(group, actual)
            self.assertEqual(180, timeout)
            self.assertEqual(observer.OUTPUT_FILE_LIMIT_BYTES, group._limit[1])
            self.assertEqual(observer.OUTPUT_FILE_LIMIT_BYTES, group._limits[0][1])
            self.assertEqual(
                os.fstat(spawned[0]["stdout"].fileno()).st_ino, Path(group._limit[0]).stat().st_ino
            )
            reading.cancel_job(self.config, self.fixture.key, self.active.job.id, now=101)
            on_spawn(group)
            spawned[0]["stdout"].write(b"reply")
            return 0

        with (
            mock.patch.object(supervise, "_spawn", side_effect=spawn),
            mock.patch.object(supervise, "_run_posix", side_effect=run_group),
            mock.patch.object(supervise, "_run_windows", side_effect=run_group),
        ):
            self.assertEqual(("reply", "ok"), self.call(self.guard(runner=supervise.run)))
        self.assertIs(group, self.active.job.group)
        group.cancel.assert_called_once()
        group.close.assert_called_once()
        self.proof(1, invoked=True)
