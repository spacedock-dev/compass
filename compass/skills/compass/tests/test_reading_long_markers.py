"""Durable marker ordering permits one fresh execution and preserves uncertain charges."""

from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import importlib
import importlib.util
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import analyze_diagnostics, reading_long_jobs, supervise
from compass_runtime import io as runtime_io
from compass_runtime import reading_policy as policy

from .support import make_runtime
from .test_reading_long_jobs import binding
from .test_reading_long_reservation import request
from .test_reading_pass_types import diagnostic, observation


class Crash(BaseException):
    """An injected process stop, never converted into a successful return."""


class LongMarkerTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(home.name), state_home=home.name)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.permission = policy.capture_long_permission(self.config, now=100)

    def module(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_markers"))
        return importlib.import_module("compass_runtime.reading_long_markers")

    def begin(self, *, now: float = 100) -> Any:
        module = self.module()
        assert self.permission is not None
        prepared = policy.prepare_long_job(
            permission=self.permission,
            binding=binding(started_at=now),
            call_timeout_ms=200,
            clock=lambda: 0.0,
        )
        return module.begin(self.config, permission=self.permission, job=prepared, now=now)

    def request(self, owner: Any, ordinal: int = 1) -> dict[str, Any]:
        prepared = owner.live.prepared
        header = json.loads(prepared.binding)
        return request(
            job_id=prepared.job_id,
            started_at=header["started_at"],
            ordinal=ordinal,
            kind="reconciliation" if ordinal == 4 else "evidence",
            max_evidence_passes=3,
            plan_sha256=reading_long_jobs.digest(header["plan"]),
            prompt_bytes=10,
            destination_sha256=header["destination_sha256"],
        )

    def reserve(self, owner: Any, ordinal: int = 1) -> Any:
        return self.module().reserve(
            self.config, owner, request=self.request(owner, ordinal), now=100
        )

    def loaded(self, owner: Any) -> Any:
        return self.module().load(self.config, owner.live.prepared.job_id)

    def path(self, owner: Any) -> Path:
        return Path(self.module().marker_path(self.config, owner.live.prepared.job_id))

    def spends(self) -> int:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            return int(db.execute("SELECT count(*) FROM spends").fetchone()[0])

    def settle(self, owner: Any, ordinal: int = 1, value: Any = None) -> bool:
        return bool(
            self.module().settle(
                self.config,
                owner,
                observation={
                    **observation(),
                    "ordinal": ordinal,
                    "diagnostic": diagnostic() if value is None else value,
                },
                now=100,
            )
        )

    def test_pending_precedes_sql_charge_and_charged_write_precedes_one_execution_permission(
        self,
    ) -> None:
        module = self.module()
        owner = self.begin()
        original = module._write
        seen: list[tuple[str, int]] = []

        def writing(path: Any, marker: Any) -> Any:
            seen.append((marker["passes"][-1]["state"], self.spends()))
            return original(path, marker)

        with mock.patch.object(module, "_write", side_effect=writing):
            result = self.reserve(owner)
        self.assertEqual([("pending", 0), ("charged", 1)], seen)
        self.assertTrue(result.launch)
        self.assertIs(True, result.charged)
        self.assertTrue(result.fresh_charge)
        replay = self.reserve(owner)
        self.assertFalse(replay.launch)
        self.assertFalse(replay.fresh_charge)
        self.assertEqual(1, self.spends())
        self.assertEqual("charged", self.loaded(owner)["passes"][0]["state"])

    def test_failed_pending_write_never_charges_or_authorizes_execution(self) -> None:
        module = self.module()
        owner = self.begin()
        with mock.patch.object(module, "_write", side_effect=OSError("private error words")):
            result = self.reserve(owner)
        self.assertFalse(result.launch)
        self.assertIsNone(result.charged)
        self.assertEqual(0, self.spends())
        self.assertEqual([], self.loaded(owner)["passes"])
        self.assertNotIn("private error words", self.path(owner).read_text())

    def test_failed_post_charge_marker_write_blocks_launch_and_keeps_charge_unknown_on_disk(
        self,
    ) -> None:
        module = self.module()
        owner = self.begin()
        original = module._write

        def writing(path: Any, marker: Any) -> Any:
            if marker["passes"][-1]["state"] == "charged":
                raise OSError("private failure")
            return original(path, marker)

        with mock.patch.object(module, "_write", side_effect=writing):
            result = self.reserve(owner)
        self.assertFalse(result.launch)
        self.assertIs(True, result.charged)
        self.assertTrue(result.fresh_charge)
        self.assertEqual(1, self.spends())
        slot = self.loaded(owner)["passes"][0]
        self.assertEqual("pending", slot["state"])
        self.assertIsNone(slot["charged"])
        self.assertFalse(self.reserve(owner).launch)
        self.assertFalse(self.reserve(owner, 2).launch)
        self.assertEqual(1, self.spends())

    def test_crashes_before_and_after_sql_commit_leave_pending_without_execution_permission(
        self,
    ) -> None:
        for committed in (False, True):
            with self.subTest(committed=committed):
                self.crash_reservation(committed)

    def crash_reservation(self, committed: bool) -> None:
        owner = self.begin()
        original = policy.reserve_registered_pass
        before = self.spends()

        def reserve(*args: Any, **kwargs: Any) -> Any:
            self.assertEqual("pending", self.loaded(owner)["passes"][0]["state"])
            if committed:
                original(*args, **kwargs)
            raise Crash

        with (
            mock.patch.object(policy, "reserve_registered_pass", side_effect=reserve),
            self.assertRaises(Crash),
        ):
            self.reserve(owner)
        self.assertEqual(before + int(committed), self.spends())
        self.assertEqual("pending", self.loaded(owner)["passes"][0]["state"])
        self.assertFalse(self.reserve(owner).launch)

    def test_crash_after_charged_write_does_not_turn_reload_into_execution_permission(self) -> None:
        module = self.module()
        owner = self.begin()
        original = module._write

        def writing(path: Any, marker: Any) -> Any:
            original(path, marker)
            if marker["passes"][-1]["state"] == "charged":
                raise Crash

        with mock.patch.object(module, "_write", side_effect=writing), self.assertRaises(Crash):
            self.reserve(owner)
        self.assertEqual("charged", self.loaded(owner)["passes"][0]["state"])
        self.assertFalse(self.reserve(owner).launch)
        self.assertEqual(1, self.spends())

    def test_settlement_is_durable_and_ended_slots_and_sealed_jobs_never_reopen(self) -> None:
        module = self.module()
        owner = self.begin()
        self.assertTrue(self.reserve(owner).launch)
        with mock.patch.object(module, "_write", side_effect=OSError("settle failed")):
            self.assertFalse(self.settle(owner))
        self.assertEqual("charged", self.loaded(owner)["passes"][0]["state"])
        self.assertTrue(self.settle(owner))
        before = self.path(owner).read_bytes()
        self.assertFalse(self.settle(owner))
        self.assertFalse(module.observe(self.config, owner, observation=observation(), now=100))
        self.assertEqual(before, self.path(owner).read_bytes())
        self.assertTrue(module.seal(self.config, owner, state="completed", now=100))
        sealed = self.path(owner).read_bytes()
        self.assertFalse(self.reserve(owner, 2).launch)
        self.assertFalse(module.seal(self.config, owner, state="active", now=100))
        self.assertFalse(module.observe(self.config, owner, observation=observation(), now=100))
        self.assertEqual(sealed, self.path(owner).read_bytes())

    def test_crash_after_settlement_keeps_slot_ended(self) -> None:
        module = self.module()
        owner = self.begin()
        self.reserve(owner)
        original = module._write

        def writing(path: Any, marker: Any) -> Any:
            original(path, marker)
            raise Crash

        with mock.patch.object(module, "_write", side_effect=writing), self.assertRaises(Crash):
            self.settle(owner)
        self.assertEqual("settled", self.loaded(owner)["passes"][0]["state"])
        self.assertFalse(self.settle(owner))
        self.assertEqual(1, self.spends())

    def test_real_capture_replaces_one_observation_and_preserves_durable_charge(self) -> None:
        module = self.module()
        owner = self.begin()
        self.reserve(owner)
        snapshots: list[dict[str, Any]] = []
        capture = analyze_diagnostics.Capture(snapshots.append)
        capture.prepared("abcdefghij", diagnostic()["selection"], capture.start())
        capture.called(
            SimpleNamespace(
                analyze_diagnostic=diagnostic()["input"],
                admit_prompt=SimpleNamespace(measurement=diagnostic()["capacity"]),
            )
        )
        self.assertEqual(3, len(snapshots))
        for index, snapshot in enumerate(snapshots):
            callback = module.settle if index == 2 else module.observe
            self.assertTrue(
                callback(
                    self.config,
                    owner,
                    observation={**observation(), "diagnostic": snapshot},
                    now=100,
                )
            )
        stored = self.loaded(owner)
        self.assertEqual(1, len(stored["passes"]))
        slot = stored["passes"][0]
        self.assertIs(True, slot["charged"])
        self.assertEqual("settled", slot["state"])
        self.assertEqual(
            "context-config-after-reserve", slot["observation"]["diagnostic"]["input"]["outcome"]
        )
        self.assertTrue(slot["observation"]["diagnostic"]["capacity"]["allowed"])
        self.assertIsNone(
            slot["observation"]["diagnostic"]["selection"]["selected_source_characters"]
        )
        snapshots[-1]["capacity"]["prompt_bytes"] = 999
        self.assertEqual(
            10,
            self.loaded(owner)["passes"][0]["observation"]["diagnostic"]["capacity"][
                "prompt_bytes"
            ],
        )

    def test_malformed_observation_and_private_extra_fields_never_reach_disk(self) -> None:
        module = self.module()
        policy.note(
            self.config,
            kind="reading",
            provider="claude",
            destination="CONFIG_CANARY",
            content=6,
            tool_output="NOTICE_CANARY",
            now=100,
        )
        self.assertIn("CONFIG_CANARY", json.dumps(policy.status(self.config, now=100)))
        self.assertIn("NOTICE_CANARY", json.dumps(policy.status(self.config, now=100)))
        owner = self.begin()
        self.reserve(owner)
        before = self.path(owner).read_bytes()
        self.assertNotIn(b"CONFIG_CANARY", before)
        self.assertNotIn(b"NOTICE_CANARY", before)
        prompt_request = {**self.request(owner, 2), "prompt": "PROMPT_CANARY"}
        self.assertFalse(module.reserve(self.config, owner, request=prompt_request, now=100).launch)
        self.assertEqual(before, self.path(owner).read_bytes())
        for bad in (
            {**observation(), "private": "source words"},
            {**observation(), "diagnostic": {"reply": "model words"}},
        ):
            self.assertFalse(module.observe(self.config, owner, observation=bad, now=100))
            self.assertEqual(before, self.path(owner).read_bytes())
        raw = json.loads(before)
        raw["reply"] = "must not parse"
        self.path(owner).write_text(json.dumps(raw))
        malformed = self.path(owner).read_bytes()
        self.assertIsNone(self.loaded(owner))
        self.assertFalse(self.reserve(owner, 2).launch)
        self.assertEqual(malformed, self.path(owner).read_bytes())

    def test_load_is_read_only_and_foreign_owner_cannot_update(self) -> None:
        owner = self.begin()
        before = self.path(owner).read_bytes()
        foreign = dataclasses.replace(owner, owner="e" * 32)
        self.assertFalse(self.reserve(foreign).launch)
        with (
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(policy, "reserve_registered_pass", side_effect=AssertionError),
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
        ):
            first = self.loaded(owner)
            second = self.loaded(owner)
        first["header"]["plan"]["limits"]["prompt_bytes"] = 1
        self.assertEqual(100, second["header"]["plan"]["limits"]["prompt_bytes"])
        self.assertEqual(before, self.path(owner).read_bytes())

    def test_concurrent_pending_calls_yield_one_execution_permission(self) -> None:
        owner = self.begin()
        barrier = threading.Barrier(2)

        def reserve(_: int) -> Any:
            barrier.wait(timeout=30)
            return self.reserve(owner)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, range(2)))
        self.assertEqual(1, sum(result.launch for result in results))
        self.assertEqual(1, self.spends())

    def test_size_and_count_bounds_never_retire_unacknowledged_records(
        self,
    ) -> None:
        module = self.module()
        with mock.patch.object(module, "MAX_MARKERS", 2):
            completed = self.begin()
            self.reserve(completed)
            self.settle(completed)
            module.seal(self.config, completed, state="completed", now=100)
            unresolved = self.begin()
            with (
                mock.patch.object(policy, "reserve_registered_pass", side_effect=Crash),
                self.assertRaises(Crash),
            ):
                self.reserve(unresolved)
            module.seal(self.config, unresolved, state="failed", now=100)
            self.assertIsNone(self.begin())
            fresh = self.begin(now=100 + policy.JOB_LEDGER_SEC + 1)
            self.assertIsNone(fresh)
            self.assertTrue(self.path(completed).exists())
            self.assertTrue(self.path(unresolved).exists())
        owner = self.begin()
        before = self.spends()
        with mock.patch.object(module, "MAX_MARKER_BYTES", len(self.path(owner).read_bytes()) + 1):
            self.assertFalse(
                module.reserve(
                    self.config,
                    owner,
                    request=self.request(owner),
                    now=100,
                ).launch
            )
        self.assertEqual(before, self.spends())

    def test_owner_only_atomic_writes_sync_files_and_supporting_directory(self) -> None:
        module = self.module()
        synced: list[bool] = []
        original = os.fsync

        def sync(fd: int) -> Any:
            synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
            return original(fd)

        with mock.patch.object(module.os, "fsync", side_effect=sync):
            owner = self.begin()
            self.assertTrue(self.reserve(owner).launch)
        self.assertGreaterEqual(synced.count(False), 3)
        if hasattr(os, "O_DIRECTORY"):
            self.assertGreaterEqual(synced.count(True), 3)
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(self.path(owner).stat().st_mode))
