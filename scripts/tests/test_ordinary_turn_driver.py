"""Synthetic controls only: no CLI, account store, or observer evidence is produced."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ordinary_turn_driver as driver


class FakeScope:
    """Deliberately cannot provide readiness or real-turn proof."""

    def __init__(self, test: ControlFixture) -> None:
        self.test = test

    def launch(self, plan: driver.Plan, limits: driver.Limits) -> driver.NativeCapture:
        self.test.events.append("launch")
        body = json.loads(self.test.budget.read_text())
        self.test.assertEqual("charged", body["calls"][-1]["status"])
        self.test.assertEqual(plan.fingerprint(), body["calls"][-1]["inputs_sha256"])
        self.test.assertEqual(driver.Limits(), limits)
        if self.test.launch_error:
            raise self.test.launch_error
        return self.test.capture(plan)

    def cleanup(self) -> bool:
        self.test.events.append("cleanup")
        return self.test.cleaned

    def close(self) -> driver.Observation:
        self.test.events.append("close")
        if self.test.close_error:
            raise self.test.close_error
        return driver.Observation(
            evidence_kind="synthetic-control-only",
            loss=self.test.loss,
            compass_model_calls=self.test.model_calls,
            elapsed_seconds=self.test.elapsed,
            output_bytes=self.test.output_bytes,
            receipt_sha256=driver.sha(b"fake observer receipt, never real proof"),
        )


class FakeAdapter:
    def __init__(self, test: ControlFixture) -> None:
        self.test = test

    def admit(self, plan: driver.Plan) -> FakeScope:
        self.test.events.append("admit-before-launch")
        if self.test.admission_error:
            raise self.test.admission_error
        plan.validate()
        return FakeScope(self.test)


class ControlFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.authority = self.root / "authority"
        self.authority.mkdir()
        self.budget = self.authority / "ordinary-turn-budget.json"
        self.budget.write_text(json.dumps(self.initial()))
        grant = b'{"test": "synthetic authority only"}'
        (self.authority / "grant.json").write_bytes(grant)
        for patch in (
            mock.patch.object(driver, "AUTHORITY_DIR", self.authority),
            mock.patch.object(driver, "GRANT_SHA256", driver.sha(grant)),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.events: list[str] = []
        self.launch_error: BaseException | None = None
        self.admission_error: BaseException | None = None
        self.close_error: BaseException | None = None
        self.cleaned = True
        self.loss = 0
        self.model_calls = 0
        self.elapsed = 1.0
        self.output_bytes = 20
        self.native_bytes = b""
        self.plan = self.make_plan()
        self.adapter = FakeAdapter(self)

    def initial(self) -> dict[str, Any]:
        return {"cap": 10, "calls": [], "enabled": True, "requires_complete_owned_observer": True}

    def make_plan(self) -> driver.Plan:
        workspace = self.root / "workspace"
        workspace.mkdir()
        home = self.root / "owned-home"
        home.mkdir(mode=0o700)
        files: dict[str, driver.FileBinding] = {}
        for name in ("cli", "settings", "hooks", "mcp"):
            path = self.root / name
            path.write_bytes(name.encode())
            files[name] = driver.FileBinding(str(path), driver.sha(path.read_bytes()))
        return driver.Plan(
            ordinal=1,
            session_id="00000000-0000-4000-8000-000000000001",
            revision="a" * 40,
            workspace=str(workspace),
            model="reviewed-model",
            effort="reviewed-effort",
            prompt="Write the next ordinary reply.",
            argv=(str(self.root / "cli"), "reviewed-native-arguments"),
            environment={"COMPASS_HOME": str(home)},
            files=files,
            board_port=4599,
            transcript_path=str(self.root / "native-session.jsonl"),
        )

    def capture(self, plan: driver.Plan) -> driver.NativeCapture:
        user = {
            "type": "user",
            "sessionId": plan.session_id,
            "uuid": f"user-{plan.ordinal}",
            "parentUuid": None,
            "message": {"role": "user", "content": plan.prompt},
        }
        final = {
            "type": "assistant",
            "sessionId": plan.session_id,
            "uuid": f"final-{plan.ordinal}",
            "parentUuid": f"user-{plan.ordinal}",
            "message": {"role": "assistant", "stop_reason": "end_turn"},
        }
        hooks = [
            {
                "hook_event_name": kind,
                "session_id": plan.session_id,
                "cwd": plan.workspace,
                "transcript_path": plan.transcript_path,
                **({"prompt": plan.prompt} if kind == "UserPromptSubmit" else {}),
            }
            for kind in ("UserPromptSubmit", "Stop")
        ]
        before = self.native_bytes
        self.native_bytes += self.lines([user, final])
        return driver.NativeCapture(before, self.native_bytes, self.lines(hooks))

    def lines(self, rows: list[dict[str, Any]]) -> bytes:
        return b"".join(json.dumps(row).encode() + b"\n" for row in rows)

    def run_turn(self, plan: driver.Plan | None = None) -> dict[str, Any]:
        return driver.run_turn(plan or self.plan, self.adapter)

    def assert_refuses_without_launch(self) -> None:
        with self.assertRaises(driver.RefusalError):
            self.run_turn()
        self.assertNotIn("launch", self.events)


class OrdinaryControls(ControlFixture):
    def test_fresh_helper_has_no_personal_authority_and_refuses_before_admission(self) -> None:
        name = "ordinary_driver_unbound_control"
        spec = importlib.util.spec_from_file_location(name, driver.__file__)
        assert spec is not None and spec.loader is not None
        fresh = importlib.util.module_from_spec(spec)
        with (
            mock.patch.dict(sys.modules, {name: fresh}),
            mock.patch.dict(os.environ, {"HOME": str(self.root), "COMPASS_HOME": str(self.root)}),
        ):
            spec.loader.exec_module(fresh)
        self.assertIsNone(fresh.AUTHORITY_DIR)
        self.assertIsNone(fresh.GRANT_SHA256)
        before = self.budget.read_bytes()
        with self.assertRaises(fresh.RefusalError):
            fresh.run_turn(self.plan, self.adapter)
        self.assertEqual([], self.events)
        self.assertEqual(before, self.budget.read_bytes())

    def test_native_join_refuses_unanchored_or_ineligible_new_source_records(self) -> None:
        capture = self.capture(self.plan)
        user, final = driver.rows(capture.after)
        variants = {
            "pre-person orphan": [
                {**final, "uuid": "orphan", "parentUuid": "unrelated"},
                user,
                final,
            ],
            "meta final": [user, {**final, "isMeta": True}],
            "wrong final role": [
                user,
                {**final, "message": {"role": "user", "stop_reason": "end_turn"}},
            ],
            "empty person": [{**user, "uuid": ""}, {**final, "parentUuid": ""}],
            "blank person": [{**user, "uuid": " "}, {**final, "parentUuid": " "}],
        }
        for label, messages in variants.items():
            with self.subTest(source=label), self.assertRaises(driver.RefusalError):
                driver.native_join(
                    self.plan, dataclasses.replace(capture, after=self.lines(messages))
                )

    def test_native_join_refuses_identity_reuse_across_the_exact_prior_prefix(self) -> None:
        self.run_turn()
        plan = dataclasses.replace(self.plan, ordinal=2, prompt="Second synthetic turn")
        capture = self.capture(plan)
        user, final = driver.rows(capture.after[len(capture.before) :])
        for messages in (
            [{**user, "uuid": "user-1"}, {**final, "parentUuid": "user-1"}],
            [user, {**final, "uuid": "final-1"}],
        ):
            with self.subTest(messages=messages), self.assertRaises(driver.RefusalError):
                driver.native_join(
                    plan, dataclasses.replace(capture, after=capture.before + self.lines(messages))
                )

    def test_native_join_preserves_a_valid_sibling_dag_and_tool_result_branch(self) -> None:
        capture = self.capture(self.plan)
        user, final = driver.rows(capture.after)
        draft = {
            **final,
            "uuid": "draft",
            "message": {"role": "assistant", "stop_reason": "tool_use"},
        }
        tool = {
            "type": "user",
            "sessionId": self.plan.session_id,
            "uuid": "tool",
            "parentUuid": "draft",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "tool-1", "content": "fixture result"}
                ],
            },
        }
        proof = driver.native_join(
            self.plan, dataclasses.replace(capture, after=self.lines([user, draft, tool, final]))
        )
        self.assertEqual("final-1", proof["native_final_uuid"])

    @unittest.skipUnless(os.name == "posix", "directory fsync is POSIX-only")
    def test_completion_directory_fsync_failure_holds_before_another_ordinal(self) -> None:
        real_fsync = os.fsync

        def fail_completion(fd: int) -> None:
            if (
                stat.S_ISDIR(os.fstat(fd).st_mode)
                and json.loads(self.budget.read_text())["calls"][-1]["status"] == "synthetic-joined"
            ):
                raise OSError("synthetic completion directory fsync uncertainty")
            real_fsync(fd)

        with (
            mock.patch.object(os, "fsync", side_effect=fail_completion),
            self.assertRaises(OSError),
        ):
            self.run_turn()
        body = json.loads(self.budget.read_text())
        self.assertEqual(1, len(body["calls"]))
        self.assertEqual("held", body["calls"][0]["status"])
        self.assertFalse(body["calls"][0]["real_turn_proof"])
        self.events.clear()
        with self.assertRaises(driver.RefusalError):
            self.run_turn(dataclasses.replace(self.plan, ordinal=2, prompt="Second turn"))
        self.assertEqual([], self.events)

    def test_persistent_completion_storage_failure_preserves_the_original_error_and_charge(
        self,
    ) -> None:
        real_write = driver.write_private

        def failed_hold(path: Path, body: Any) -> None:
            status = body["calls"][-1]["status"]
            if status == "held":
                raise OSError("synthetic persistent storage failure")
            real_write(path, body)
            if status == "synthetic-joined":
                raise OSError("synthetic completion uncertainty")

        with (
            mock.patch.object(driver, "write_private", side_effect=failed_hold),
            self.assertRaisesRegex(OSError, "completion uncertainty"),
        ):
            self.run_turn()
        body = json.loads(self.budget.read_text())
        self.assertEqual(1, len(body["calls"]))
        self.assertEqual("synthetic-joined", body["calls"][0]["status"])
        self.assertEqual(["cleanup", "close"], self.events[-2:])

    def test_cli_cannot_select_or_activate_an_authority(self) -> None:
        before = self.budget.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            driver.main(
                [
                    "--revision",
                    "a" * 40,
                    "--manifest-out",
                    str(self.root / "unused.json"),
                    "--authority-dir",
                    str(self.authority),
                ]
            )
        self.assertEqual(2, raised.exception.code)
        self.assertEqual(before, self.budget.read_bytes())

    def test_disabled_budget_has_no_charge_or_lock_side_effect(self) -> None:
        body = self.initial()
        body["enabled"] = False
        self.budget.write_text(json.dumps(body))
        before = self.budget.read_bytes()
        self.assert_refuses_without_launch()
        self.assertEqual(before, self.budget.read_bytes())
        self.assertFalse(self.budget.with_suffix(".json.lock").exists())

    def test_missing_adapter_and_unknown_config_admission_are_zero_attempts(self) -> None:
        with self.assertRaises(driver.RefusalError):
            driver.run_turn(self.plan)
        self.admission_error = driver.RefusalError("managed/installed customizations not admitted")
        self.assert_refuses_without_launch()
        self.assertEqual([], json.loads(self.budget.read_text())["calls"])

    def test_charge_is_durable_before_launch_and_fake_join_is_not_real_evidence(self) -> None:
        result = self.run_turn()
        self.assertEqual(["admit-before-launch", "launch", "cleanup", "close"], self.events)
        self.assertEqual("synthetic-joined", result["status"])
        self.assertFalse(result["real_turn_proof"])
        if os.name == "posix":
            self.assertEqual(0o600, self.budget.stat().st_mode & 0o777)

    def test_failed_launch_never_refunds_and_always_cleans_and_closes(self) -> None:
        self.launch_error = RuntimeError("synthetic native error")
        with self.assertRaises(RuntimeError):
            self.run_turn()
        self.assertEqual(["admit-before-launch", "launch", "cleanup", "close"], self.events)
        body = json.loads(self.budget.read_text())
        self.assertEqual(1, len(body["calls"]))
        self.assertEqual("held", body["calls"][0]["status"])
        self.assert_refuses_without_launch_after_clear()

    def assert_refuses_without_launch_after_clear(self) -> None:
        self.events.clear()
        self.assert_refuses_without_launch()

    def test_interruption_and_close_failure_preserve_charge_and_hold(self) -> None:
        self.launch_error = KeyboardInterrupt()
        self.close_error = OSError("synthetic observer failure")
        with self.assertRaises(KeyboardInterrupt):
            self.run_turn()
        self.assertEqual(1, len(json.loads(self.budget.read_text())["calls"]))
        self.assert_refuses_without_launch_after_clear()

    def test_cleanup_exception_still_closes_observer_and_holds(self) -> None:
        with (
            mock.patch.object(FakeScope, "cleanup", side_effect=OSError("cleanup failed")),
            self.assertRaises(OSError),
        ):
            self.run_turn()
        self.assertIn("close", self.events)
        self.assertEqual("held", json.loads(self.budget.read_text())["calls"][0]["status"])

    def test_budget_write_failure_prevents_launch_and_closes_admitted_scope(self) -> None:
        with (
            mock.patch.object(driver, "write_private", side_effect=OSError("synthetic fsync")),
            self.assertRaises(OSError),
        ):
            self.run_turn()
        self.assertEqual(["admit-before-launch", "cleanup", "close"], self.events)
        self.assertEqual([], json.loads(self.budget.read_text())["calls"])

    def test_cli_argument_preparation_preserves_one_native_session_and_hooks(self) -> None:
        first = dataclasses.replace(self.plan, argv=driver.claude_arguments(self.plan))
        resumed = dataclasses.replace(first, ordinal=2, prompt="Next ordinary reply")
        resumed = dataclasses.replace(resumed, argv=driver.claude_arguments(resumed))
        self.assertIn("--session-id", first.argv)
        self.assertIn("--resume", resumed.argv)
        self.assertEqual(first.session_id, resumed.session_id)
        self.assertEqual(first.campaign(), resumed.campaign())
        self.assertNotEqual(first.fingerprint(), resumed.fingerprint())
        for flag in (
            "--include-hook-events",
            "--replay-user-messages",
            "--settings",
            "--strict-mcp-config",
        ):
            self.assertIn(flag, first.argv)
        self.run_turn(first)
        self.run_turn(resumed)

    def test_prep_argument_refuses_a_session_lifecycle_mismatch(self) -> None:
        first = dataclasses.replace(self.plan, argv=driver.claude_arguments(self.plan))
        with self.assertRaises(driver.RefusalError):
            self.run_turn(
                dataclasses.replace(
                    first,
                    argv=tuple("--resume" if arg == "--session-id" else arg for arg in first.argv),
                )
            )

    def test_ten_serial_attempts_only_one_session_and_no_duplicate_ordinal(self) -> None:
        for ordinal in range(1, 11):
            plan = dataclasses.replace(
                self.plan, ordinal=ordinal, prompt=f"Ordinary turn {ordinal}"
            )
            self.run_turn(plan)
        self.events.clear()
        with self.assertRaises(driver.RefusalError):
            self.run_turn(dataclasses.replace(self.plan, ordinal=11))
        self.assertNotIn("launch", self.events)
        self.assertEqual(10, len(json.loads(self.budget.read_text())["calls"]))

    def test_existing_charge_is_an_open_hold_not_a_restart_or_pid_liveness_hint(self) -> None:
        self.run_turn()
        body = json.loads(self.budget.read_text())
        body["calls"][0]["status"] = "charged"
        self.budget.write_text(json.dumps(body))
        self.assert_refuses_without_launch_after_clear()

    def test_a_second_reply_under_the_same_sid_cannot_reset_the_native_prefix(self) -> None:
        self.run_turn()
        self.native_bytes = b""
        with self.assertRaises(driver.RefusalError):
            self.run_turn(dataclasses.replace(self.plan, ordinal=2, prompt="Second ordinary reply"))
        self.assertEqual("held", json.loads(self.budget.read_text())["calls"][-1]["status"])

    def test_concurrent_second_attempt_cannot_launch_against_the_open_charge(self) -> None:
        entered, release = threading.Event(), threading.Event()
        errors: list[BaseException] = []
        original = FakeScope.launch

        def blocked(
            scope: FakeScope, plan: driver.Plan, limits: driver.Limits
        ) -> driver.NativeCapture:
            entered.set()
            if not release.wait(timeout=2):
                raise RuntimeError("fixture release missing")
            return original(scope, plan, limits)

        def run_first() -> None:
            try:
                self.run_turn()
            except BaseException as error:  # noqa: BLE001 - fixture records thread interruption too
                errors.append(error)

        with mock.patch.object(FakeScope, "launch", new=blocked):
            first = threading.Thread(target=run_first)
            first.start()
            try:
                self.assertTrue(entered.wait(timeout=2))
                with self.assertRaises(driver.RefusalError):
                    self.run_turn(dataclasses.replace(self.plan, ordinal=2))
            finally:
                release.set()
                first.join(timeout=2)
        self.assertFalse(first.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(1, self.events.count("launch"))

    def test_changed_session_workspace_config_or_model_cannot_share_the_allowance(self) -> None:
        self.run_turn()
        for edits in (
            {"session_id": "00000000-0000-4000-8000-000000000002"},
            {"model": "other"},
            {"effort": "other"},
            {"revision": "b" * 40},
            {"argv": (*self.plan.argv, "changed")},
            {"environment": {**self.plan.environment, "OTHER": "changed"}},
        ):
            with self.subTest(edits=edits):
                self.events.clear()
                with self.assertRaises(driver.RefusalError):
                    self.run_turn(dataclasses.replace(self.plan, ordinal=2, **edits))
                self.assertNotIn("launch", self.events)

    def test_loss_cleanup_bounds_and_nonzero_compass_calls_are_held(self) -> None:
        for field, value in (
            ("loss", 1),
            ("cleaned", False),
            ("model_calls", 1),
            ("elapsed", 901.0),
            ("output_bytes", 4 * 1024 * 1024 + 1),
        ):
            with self.subTest(field=field):
                self.budget.write_text(json.dumps(self.initial()))
                self.native_bytes = b""
                setattr(self, field, value)
                with self.assertRaises(driver.RefusalError):
                    self.run_turn()
                self.assertEqual("held", json.loads(self.budget.read_text())["calls"][0]["status"])
                setattr(self, field, True if field == "cleaned" else 0)

    def test_changed_grant_budget_cap_and_malformed_history_refuse(self) -> None:
        mutations: tuple[dict[str, Any], ...] = (
            {"cap": 11},
            {"calls": [{}]},
            {"enabled": 1},
            {"requires_complete_owned_observer": False},
        )
        for mutation in mutations:
            self.budget.write_text(json.dumps({**self.initial(), **mutation}))
            self.assert_refuses_without_launch()
        self.budget.write_text(json.dumps(self.initial()))
        (self.authority / "grant.json").write_text("{}")
        self.assert_refuses_without_launch()

    def test_unpersisted_flags_owner_ports_and_missing_home_refuse(self) -> None:
        mutations: tuple[dict[str, Any], ...] = (
            {"argv": (*self.plan.argv, "--no-session-persistence")},
            {"argv": (*self.plan.argv, "--safe-mode")},
            {"argv": (*self.plan.argv, "--bare")},
            {"board_port": 4553},
            {"board_port": 4563},
            {"board_port": 4567},
            {"environment": {}},
        )
        for edits in mutations:
            with self.subTest(edits=edits), self.assertRaises(driver.RefusalError):
                self.run_turn(dataclasses.replace(self.plan, **edits))
        self.assertNotIn("launch", self.events)

    def test_cli_exit_or_a_stale_or_unjoined_final_is_not_a_turn(self) -> None:
        capture = self.capture(self.plan)
        for broken in (
            dataclasses.replace(capture, after=b""),
            dataclasses.replace(capture, before=capture.after),
            dataclasses.replace(capture, after=capture.after.replace(b"end_turn", b"tool_use")),
            dataclasses.replace(capture, after=capture.after.replace(b'user-1"', b'other"', 1)),
            dataclasses.replace(capture, hooks=b""),
            dataclasses.replace(capture, hooks=capture.hooks.replace(b"Stop", b"SubagentStop")),
            dataclasses.replace(capture, hooks=capture.hooks.replace(b"4599", b"4553")),
        ):
            if broken == capture:
                continue
            with self.subTest(broken=broken), self.assertRaises(driver.RefusalError):
                driver.native_join(self.plan, broken)

    def test_prefix_rewrite_later_user_and_newer_unproven_assistant_refuse(self) -> None:
        capture = self.capture(self.plan)
        extra = {
            "type": "assistant",
            "sessionId": self.plan.session_id,
            "uuid": "newer",
            "parentUuid": "final-1",
            "message": {"role": "assistant"},
        }
        with self.assertRaises(driver.RefusalError):
            driver.native_join(
                self.plan, dataclasses.replace(capture, after=capture.after + self.lines([extra]))
            )
        with self.assertRaises(driver.RefusalError):
            driver.native_join(self.plan, dataclasses.replace(capture, before=b"rewritten\n"))
        with self.assertRaises(driver.RefusalError):
            driver.native_join(
                self.plan, dataclasses.replace(capture, after=capture.after + capture.after)
            )

    def test_changed_input_file_after_admission_is_charged_but_not_launched(self) -> None:
        original = self.adapter.admit

        def changed(plan: driver.Plan) -> FakeScope:
            scope = original(plan)
            Path(plan.files["settings"].path).write_bytes(b"changed after review")
            return scope

        with (
            mock.patch.object(self.adapter, "admit", side_effect=changed),
            self.assertRaises(driver.RefusalError),
        ):
            self.run_turn()
        self.assertNotIn("launch", self.events)
        self.assertEqual("held", json.loads(self.budget.read_text())["calls"][0]["status"])

    def test_manifest_has_four_blocked_runs_and_exact_zero_call_expectations(self) -> None:
        manifest = driver.manifest("a" * 40)
        self.assertEqual(
            ["default", "monitor", "no-harness", "declined"],
            [run["kind"] for run in manifest["runs"]],
        )
        self.assertFalse(manifest["real_readiness"])
        self.assertEqual("external-required", manifest["complete_owned_observer"])
        self.assertEqual(10, manifest["ordinary_attempt_cap"])
        for run in manifest["runs"]:
            self.assertEqual("blocked", run["status"])
            self.assertIn("copy_readback", run["required_artifacts"])
            if run["kind"] != "default":
                self.assertEqual(0, run["expected_compass_model_calls"])

    def test_preparation_cli_writes_private_blocked_manifest_without_authority_changes(
        self,
    ) -> None:
        before = self.budget.read_bytes()
        destination = self.root / "four-runs.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                0, driver.main(["--revision", "a" * 40, "--manifest-out", str(destination)])
            )
        self.assertFalse(json.loads(destination.read_text())["real_readiness"])
        if os.name == "posix":
            self.assertEqual(0o600, destination.stat().st_mode & 0o777)
        self.assertEqual(before, self.budget.read_bytes())

    def test_preparation_cannot_overwrite_an_existing_budget_or_receipt(self) -> None:
        before = self.budget.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            driver.main(["--revision", "a" * 40, "--manifest-out", str(self.budget)])
        self.assertEqual(2, raised.exception.code)
        self.assertEqual(before, self.budget.read_bytes())


class StubGate:
    """A test-only injected gate, not an observer admission or certificate."""

    def before_native_launch(self, plan: driver.Plan) -> None:
        plan.validate()


class StubConfiguration:
    def __init__(self, test: ControlFixture) -> None:
        self.test = test
        self.snapshots = 0
        self.last: driver.NativeCapture | None = None

    def admit(self, plan: driver.Plan) -> None:
        self.test.events.append("synthetic-config-admission")
        plan.validate()

    def capture(self, plan: driver.Plan) -> driver.NativeCapture:
        self.snapshots += 1
        if self.snapshots == 1:
            return driver.NativeCapture(b"", b"", b"")
        if self.last is None:
            self.last = self.test.capture(plan)
        return self.last


class StubOwnedObservation(FakeScope):
    def before_native_launch(self, plan: driver.Plan) -> None:
        plan.validate()
        self.test.events.append("already-admitted-before-native-child")
        self.test.assertEqual(
            "charged", json.loads(self.test.budget.read_text())["calls"][-1]["status"]
        )


class StubCompleteObserver:
    def __init__(self, test: ControlFixture) -> None:
        self.test = test

    def admit_controller(self, pid: int, plan: driver.Plan) -> StubOwnedObservation:
        self.test.events.append("controller-ancestry-admitted")
        self.test.assertGreater(pid, 0)
        plan.validate()
        return StubOwnedObservation(self.test)


@unittest.skipUnless(os.name == "posix", "native guard is POSIX-only; no Windows readiness claimed")
class StubNativeProcess(ControlFixture):
    """Only local Python fixture processes; no real native provider is invoked."""

    def test_an_exited_parent_is_reaped_before_its_group_can_be_signalled(self) -> None:
        process = driver.NativeProcess(StubGate())
        child = mock.Mock(spec=subprocess.Popen)
        child.pid = 12345
        child.returncode = None
        child.poll.return_value = 0
        process.process = child
        with mock.patch.object(os, "killpg") as signal_group:
            self.assertTrue(process.cleanup())
        child.poll.assert_called_once_with()
        signal_group.assert_not_called()
        child.wait.assert_not_called()

    def test_exit_racing_a_group_signal_error_is_reaped_without_another_signal(self) -> None:
        process = driver.NativeProcess(StubGate())
        child = mock.Mock(spec=subprocess.Popen)
        child.pid = 12345
        child.returncode = None
        child.poll.side_effect = (None, 0)
        process.process = child
        with mock.patch.object(os, "killpg", side_effect=PermissionError) as signal_group:
            self.assertTrue(process.cleanup())
            self.assertTrue(process.cleanup())
        self.assertEqual(2, child.poll.call_count)
        signal_group.assert_called_once()
        child.wait.assert_not_called()

    def test_an_exiting_owned_parent_is_reaped_after_a_signal_error(self) -> None:
        process = driver.NativeProcess(StubGate())
        child = mock.Mock(spec=subprocess.Popen)
        child.pid = 12345
        child.returncode = None
        child.poll.return_value = None

        def exit_during_wait(*_args: Any, **_kwargs: Any) -> int:
            child.returncode = 0
            return 0

        child.wait.side_effect = exit_during_wait
        process.process = child
        with mock.patch.object(os, "killpg", side_effect=PermissionError) as signal_group:
            self.assertTrue(process.cleanup())
            self.assertTrue(process.cleanup())
        signal_group.assert_called_once()
        child.wait.assert_called_once_with(timeout=2)

    def test_a_live_parent_with_a_group_signal_error_is_not_reported_cleaned(self) -> None:
        process = driver.NativeProcess(StubGate())
        child = mock.Mock(spec=subprocess.Popen)
        child.pid = 12345
        child.returncode = None
        child.poll.return_value = None
        child.wait.side_effect = subprocess.TimeoutExpired("owned fixture", 2)
        process.process = child
        with mock.patch.object(os, "killpg", side_effect=PermissionError):
            self.assertFalse(process.cleanup())
        self.assertFalse(process.cleaned)
        child.wait.assert_called_once_with(timeout=2)

    def stub(self, body: str) -> driver.Plan:
        script = self.root / "stub_cli.py"
        script.write_text(body)
        cli = str(Path(sys.executable).resolve())
        return dataclasses.replace(
            self.plan,
            argv=(cli, str(script)),
            files={
                **self.plan.files,
                "cli": driver.FileBinding(cli, driver.sha(Path(cli).read_bytes())),
            },
        )

    def test_local_stub_receives_exact_prompt_environment_and_workspace(self) -> None:
        plan = self.stub(
            "import os,sys\nprint(os.getcwd())\nprint(os.environ['COMPASS_HOME'])\nprint(sys.stdin.read())\n"
        )
        driver.reserve(plan)
        process = driver.NativeProcess(StubGate())
        result = process.run(plan, driver.Limits(seconds=2, output_bytes=1024))
        self.addCleanup(process.cleanup)
        self.assertEqual(0, result.exit_code)
        self.assertEqual(
            (
                str(Path(plan.workspace).resolve())
                + "\n"
                + plan.environment["COMPASS_HOME"]
                + "\n"
                + plan.prompt
                + "\n"
            ).encode(),
            result.stdout,
        )
        self.assertTrue(process.cleanup())

    def test_aggregate_stdout_stderr_bound_and_wall_timeout(self) -> None:
        for body, limits in (
            (
                "import os\nos.write(1,b'a'*1000)\nos.write(2,b'b'*1000)\n",
                driver.Limits(seconds=2, output_bytes=1024),
            ),
            ("import time\ntime.sleep(5)\n", driver.Limits(seconds=0.05, output_bytes=1024)),
        ):
            with self.subTest(body=body):
                plan = self.stub(body)
                self.budget.write_text(json.dumps(self.initial()))
                driver.reserve(plan)
                process = driver.NativeProcess(StubGate())
                self.addCleanup(process.cleanup)
                with self.assertRaises(driver.RefusalError):
                    process.run(plan, limits)
                self.assertTrue(process.cleanup())

    def test_nonzero_cli_exit_cannot_supply_native_completion(self) -> None:
        plan = self.stub("raise SystemExit(3)\n")
        driver.reserve(plan)
        process = driver.NativeProcess(StubGate())
        self.addCleanup(process.cleanup)
        with self.assertRaises(driver.RefusalError):
            process.run(plan, driver.Limits(seconds=2))
        self.assertTrue(process.cleanup())

    def test_group_cleanup_includes_local_child_and_is_not_complete_observer_proof(self) -> None:
        receipt = self.root / "owned-child.pid"
        plan = self.stub(
            "import os,subprocess,sys,time\nfrom pathlib import Path\n"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'])\n"
            "receipt=Path(os.environ['CHILD_RECEIPT'])\n"
            "receipt.with_suffix('.tmp').write_text(str(child.pid))\n"
            "receipt.with_suffix('.tmp').replace(receipt)\ntime.sleep(10)\n"
        )
        plan = dataclasses.replace(
            plan, environment={**plan.environment, "CHILD_RECEIPT": str(receipt)}
        )
        driver.reserve(plan)
        process = driver.NativeProcess(StubGate())
        self.addCleanup(process.cleanup)
        # Two seconds, not 0.1: on a loaded runner the limit fired after the stub created its receipt and before it
        # wrote the PID, and the test read "" (Python 3.11 runtime floor, 2026-10-22). The receipt is also written by
        # rename, so it is either absent or whole.
        with self.assertRaises(driver.RefusalError):
            process.run(plan, driver.Limits(seconds=2))
        self.assertTrue(process.cleanup())
        self.assertFalse(process.complete_descendant_proof)
        self.assertTrue(receipt.exists(), "the stub did not spawn its child within the limit")
        child_pid = int(receipt.read_text())
        # Read only this fixture-owned PID. A zombie is stopped, not an exec/flow
        # observer proof; no global process list or application automation runs.
        ps = shutil.which("ps")
        if ps is None:
            self.skipTest("owned-PID ground-truth read needs the POSIX ps executable")
        status = subprocess.run(
            [ps, "-p", str(child_pid), "-o", "stat="], capture_output=True, text=True, check=False
        )
        self.assertTrue(status.returncode == 1 or status.stdout.strip().startswith("Z"))

    def test_reaped_parent_group_id_is_not_signalled_again(self) -> None:
        plan = self.stub("print('one fixture reply')\n")
        driver.reserve(plan)
        process = driver.NativeProcess(StubGate())
        self.addCleanup(process.cleanup)
        with mock.patch("ordinary_turn_driver.os.killpg") as signal_group:
            process.run(plan, driver.Limits(seconds=2))
            process.cleanup()
        signal_group.assert_not_called()

    def test_native_spawn_requires_charge_and_external_admission(self) -> None:
        plan = self.stub("print('never launched')\n")
        with mock.patch("ordinary_turn_driver.subprocess.Popen") as spawn:
            with self.assertRaises(driver.RefusalError):
                driver.NativeProcess(StubGate()).run(plan, driver.Limits())
            driver.reserve(plan)
            with self.assertRaises(driver.RefusalError):
                driver.NativeProcess().run(plan, driver.Limits())
            spawn.assert_not_called()

    def test_a_new_process_guard_cannot_launch_twice_against_one_charge(self) -> None:
        plan = self.stub("print('one fixture launch')\n")
        driver.reserve(plan)
        first = driver.NativeProcess(StubGate())
        self.addCleanup(first.cleanup)
        first.run(plan, driver.Limits(seconds=2))
        with mock.patch("ordinary_turn_driver.subprocess.Popen") as spawn:
            with self.assertRaises(driver.RefusalError):
                driver.NativeProcess(StubGate()).run(plan, driver.Limits(seconds=2))
            spawn.assert_not_called()

    def test_admission_rejection_and_start_write_failure_never_spawn(self) -> None:
        plan = self.stub("print('never launched')\n")
        driver.reserve(plan)
        with mock.patch("ordinary_turn_driver.subprocess.Popen") as spawn:
            with (
                mock.patch.object(
                    StubGate,
                    "before_native_launch",
                    side_effect=driver.RefusalError("loss/admission unavailable"),
                ),
                self.assertRaises(driver.RefusalError),
            ):
                driver.NativeProcess(StubGate()).run(plan, driver.Limits())
            with (
                mock.patch.object(
                    driver, "write_private", side_effect=OSError("start fsync failed")
                ),
                self.assertRaises(OSError),
            ):
                driver.NativeProcess(StubGate()).run(plan, driver.Limits())
            spawn.assert_not_called()

    def test_concrete_native_adapter_is_still_synthetic_without_real_external_admission(
        self,
    ) -> None:
        plan = self.stub("print('local fixture reply')\n")
        observer = StubCompleteObserver(self)
        adapter = driver.NativeAdapter(StubConfiguration(self), observer)
        result = driver.run_turn(plan, adapter)
        self.assertEqual("synthetic-joined", result["status"])
        self.assertFalse(result["real_turn_proof"])
        self.assertLess(
            self.events.index("controller-ancestry-admitted"),
            self.events.index("already-admitted-before-native-child"),
        )
        self.assertEqual(["cleanup", "close"], self.events[-2:])

    def test_native_adapter_unknown_config_never_admits_observer_or_launches(self) -> None:
        adapter = driver.NativeAdapter(StubConfiguration(self), StubCompleteObserver(self))
        with (
            mock.patch.object(
                StubConfiguration,
                "admit",
                side_effect=driver.RefusalError("unknown installed plugin hook"),
            ),
            mock.patch("ordinary_turn_driver.subprocess.Popen") as spawn,
            self.assertRaises(driver.RefusalError),
        ):
            driver.run_turn(self.stub("print('never launched')\n"), adapter)
        spawn.assert_not_called()
        self.assertNotIn("controller-ancestry-admitted", self.events)
        self.assertEqual([], json.loads(self.budget.read_text())["calls"])

    def test_native_source_moving_during_cleanup_cannot_be_completed(self) -> None:
        config = StubConfiguration(self)
        original = config.capture

        def moved(plan: driver.Plan) -> driver.NativeCapture:
            capture = original(plan)
            if config.snapshots > 2:
                return dataclasses.replace(capture, after=capture.after + b'{"type":"later"}\n')
            return capture

        with (
            mock.patch.object(config, "capture", side_effect=moved),
            self.assertRaises(driver.RefusalError),
        ):
            driver.run_turn(
                self.stub("print('local fixture')\n"),
                driver.NativeAdapter(config, StubCompleteObserver(self)),
            )
        self.assertEqual("held", json.loads(self.budget.read_text())["calls"][-1]["status"])


if __name__ == "__main__":
    unittest.main()
