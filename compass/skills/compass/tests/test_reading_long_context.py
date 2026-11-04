"""Current execution checks cannot refresh a registered job's frozen authority."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import importlib.util
import json
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    claude_settings,
    observer,
    reading,
    reading_route,
    settings,
    supervise,
)
from compass_runtime import io as runtime_io
from compass_runtime import reading_long_control as control
from compass_runtime import reading_long_jobs as jobs
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_policy as policy

from . import test_annotations_long_target as target_tests
from .test_reading_long_jobs import binding
from .test_reading_long_reservation import request


class ActiveContextTest(unittest.TestCase):
    def test_post_call_check_does_not_reserve_another_full_timeout(self) -> None:
        self.clock[0] = 190
        self.assertEqual("job-deadline", self.module.check(self.config, self.context))
        self.assertEqual("", self.module.check_after_call(self.config, self.context))
        before = self.module.Checkpoint(self.config, self.context)
        after = self.module.Checkpoint(self.config, self.context, after_call=True)
        self.assertTrue(before(force=True))
        self.assertFalse(after(force=True))
        self.clock[0] = 200
        self.assertEqual("", self.module.check_after_call(self.config, self.context))
        self.clock[0] = 201
        self.assertEqual("job-deadline", self.module.check_after_call(self.config, self.context))

    def test_post_call_check_retains_permission_and_active_owner_requirements(self) -> None:
        self.clock[0] = 190
        policy.set_consent(self.config, False, now=100)
        self.assertEqual(
            "permission-changed", self.module.check_after_call(self.config, self.context)
        )
        reading.end_job(self.config, self.key)
        self.assertEqual("context-changed", self.module.check_after_call(self.config, self.context))

    def setUp(self) -> None:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_context"))
        self.module = importlib.import_module("compass_runtime.reading_long_context")
        self.fixture = target_tests.LongTargetTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state
        self.sid, self.key = "abc123ab", "claude:abc123ab"
        self.destination = "Anthropic"
        self.controls = claude_settings.Controls(deployment="direct")
        for patcher in (
            mock.patch.object(supervise, "_SHUTDOWN", threading.Event()),
            mock.patch.object(reading_route, "_state", return_value="usable"),
            mock.patch.object(
                reading_route, "destination", side_effect=lambda *_a, **_k: self.destination
            ),
            mock.patch.object(
                claude_settings, "resolve", side_effect=lambda *_a, **_k: self.controls
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        annotation_store.annotate(
            self.config, self.state, "claude", self.sid, goal="Retain words", now=100
        )
        target = annotation_store.capture_long_target(self.config, self.state, "claude", self.sid)
        assert target is not None
        self.target = target
        permission = policy.capture_long_permission(self.config, now=100)
        assert permission is not None
        self.permission = permission
        self.route = self.module.describe(self.config, "claude")
        self.assertIsNotNone(self.route)
        self.scope = "a" * 64
        self.clock = [0.0]
        association = {
            "harness": "claude",
            "sid": self.sid,
            "incarnation": self.target.incarnation,
            "revision": self.target.revision,
        }
        declared = binding(
            publication=association,
            target_sha256=jobs.publication_digest(association),
            scope_sha256=self.module.scope_digest(self.route, self.scope),
            destination_sha256=self.module.destination_digest(self.route),
        )
        declared["plan"]["limits"]["job_ms"] = 200_000
        prepared = policy.prepare_long_job(
            permission=self.permission,
            binding=declared,
            call_timeout_ms=observer.OBSERVER_READING_TIMEOUT_SEC * 1000,
            clock=lambda: self.clock[0],
        )
        assert prepared is not None
        active = control.admit(
            self.config,
            self.key,
            provider="claude",
            label="Claude Code",
            job=prepared,
            permission=self.permission,
            now=100,
        )
        assert active is not None
        self.active = active
        self.addCleanup(reading.end_job, self.config, self.key)
        self.context = self.module.Context(self.active, self.route, self.scope)

    def check(self, **changes: Any) -> str:
        return str(
            self.module.check(
                changes.get("config", self.config), changes.get("context", self.context)
            )
        )

    def test_current_context_is_read_only_and_never_recaptures_authority(self) -> None:
        before = {
            path: path.read_bytes() for path in self.config.state_dir.rglob("*") if path.is_file()
        }
        with (
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(annotation_store, "capture_long_target", side_effect=AssertionError),
            mock.patch.object(markers, "begin", side_effect=AssertionError),
        ):
            self.assertEqual("", self.check())
            self.assertEqual("", self.check())
        after = {
            path: path.read_bytes() for path in self.config.state_dir.rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)
        marker = markers.load(self.config, self.active.job.id)
        assert marker is not None
        self.assertEqual([], marker["passes"])

    def test_target_revision_change_refuses_old_context(self) -> None:
        annotation_store.annotate(
            self.config, self.state, "claude", self.sid, goal="Changed", now=101
        )
        self.assertEqual("intent-changed", self.check())

    def test_clear_recreate_at_same_clock_does_not_alias(self) -> None:
        annotation_store.clear(self.config, self.state, "claude", self.sid)
        annotation_store.annotate(
            self.config, self.state, "claude", self.sid, goal="Retain words", now=100
        )
        target = annotation_store.capture_long_target(self.config, self.state, "claude", self.sid)
        assert target is not None
        self.assertGreater(target.revision, self.target.revision)
        self.assertNotEqual(self.target.incarnation, target.incarnation)
        self.assertEqual("intent-changed", self.check())

    def test_physically_recreated_annotation_store_cannot_refresh_target(self) -> None:
        self.fixture.path.unlink()
        annotation_store.annotate(
            self.config, self.state, "claude", self.sid, goal="Retain words", now=100
        )
        self.assertEqual("intent-changed", self.check())
        entry = annotation_store.find(annotation_store.load(self.config), "claude", self.sid)
        assert entry is not None
        self.assertEqual(self.target.revision, entry["revisions"][-1]["n"])
        self.assertNotIn("long_incarnation", entry)

    def test_pause_then_resume_never_restores_old_permission(self) -> None:
        policy.set_consent(self.config, False, now=100)
        self.assertEqual("permission-changed", self.check())
        policy.resume(self.config, now=100)
        self.assertEqual("permission-changed", self.check())

    def test_permission_store_recreation_is_not_the_captured_lineage(self) -> None:
        policy.store_path(self.config).unlink()
        self.assertEqual("store-unavailable", self.check())
        replacement = policy.capture_long_permission(self.config, now=100)
        self.assertNotEqual(self.permission, replacement)
        self.assertEqual("permission-changed", self.check())

    def test_model_destination_settings_and_managed_controls_are_bound(self) -> None:
        self.destination = "changed.example"
        self.assertEqual("context-changed", self.check())
        self.destination = "Anthropic"
        model_config = dataclasses.replace(self.config, claude_reading_model="claude-opus-4-8")
        self.assertEqual("context-changed", self.check(config=model_config))
        settings.save(self.config, {"analyze_prompt_bytes": 2_097_152})
        self.assertEqual("context-changed", self.check())
        settings.save(self.config, {"analyze_prompt_bytes": None})
        self.controls = dataclasses.replace(self.controls, window_limits=(100_000,))
        self.assertEqual("context-changed", self.check())

    def test_tool_destination_change_with_unchanged_words_destination_refuses(self) -> None:
        current = reading_route.resolve("claude", config=self.config)
        self.assertEqual("", self.check())
        with mock.patch.object(
            reading_route, "resolve", return_value={**current, "destination": "another.receiver"}
        ):
            self.assertEqual("context-changed", self.check())

    def test_preparation_checkpoint_throttles_owner_reads_but_keeps_first_real_cause(self) -> None:
        checkpoint_type = getattr(self.module, "Checkpoint", None)
        self.assertTrue(callable(checkpoint_type))
        assert callable(checkpoint_type)
        checkpoint = checkpoint_type(self.config, self.context)
        with mock.patch.object(self.module, "check", wraps=self.module.check) as checked:
            self.assertFalse(checkpoint())
            for _ in range(100):
                self.assertFalse(checkpoint())
            self.assertEqual(1, checked.call_count)
            policy.set_consent(self.config, False, now=100)
            policy.resume(self.config, now=100)
            self.clock[0] = 0.3
            self.assertTrue(checkpoint())
            self.assertEqual("permission-changed", checkpoint.reason)
            self.assertFalse(reading.job_cancelled(self.active.job))
            self.assertTrue(checkpoint())
            self.assertEqual(2, checked.call_count)

    def test_preparation_checkpoint_sees_cancel_immediately_without_waiting_for_read_interval(
        self,
    ) -> None:
        checkpoint_type = getattr(self.module, "Checkpoint", None)
        self.assertTrue(callable(checkpoint_type))
        assert callable(checkpoint_type)
        checkpoint = checkpoint_type(self.config, self.context)
        self.assertFalse(checkpoint())
        reading.cancel_job(self.config, self.key, self.active.job.id, now=100)
        self.assertTrue(checkpoint())
        self.assertEqual("cancelled", checkpoint.reason)

    def test_shared_slot_foreign_owner_and_terminal_marker_refuse(self) -> None:
        foreign = dataclasses.replace(
            self.active, owner=dataclasses.replace(self.active.owner, owner="f" * 32)
        )
        self.assertEqual(
            "context-changed", self.check(context=dataclasses.replace(self.context, active=foreign))
        )
        markers.seal(self.config, self.active.owner, state="cancelled", now=100)
        self.assertEqual("context-changed", self.check())
        reading.end_job(self.config, self.key)
        reading.start_job(self.config, self.key, provider="claude", label="Claude Code", now=100)
        self.assertEqual("context-changed", self.check())

    def test_cancel_shutdown_and_run_disabled_close_current_context(self) -> None:
        self.assertEqual(
            "run-disabled",
            self.check(config=dataclasses.replace(self.config, model_calls_disabled=True)),
        )
        supervise._SHUTDOWN.set()
        self.assertEqual("closed", self.check())
        supervise._SHUTDOWN.clear()
        reading.cancel_job(self.config, self.key, self.active.job.id, now=101)
        self.assertEqual("cancelled", self.check())

    def test_sealed_ui_job_is_no_longer_an_execution_context(self) -> None:
        reading.seal_job(self.active.job)
        self.assertEqual("context-changed", self.check())

    def test_scope_and_full_configured_timeout_are_bound(self) -> None:
        self.assertEqual(
            "context-changed",
            self.check(context=dataclasses.replace(self.context, scope_sha256="b" * 64)),
        )
        self.clock[0] = 20.0
        self.assertEqual("", self.check())
        self.clock[0] = 20.001
        self.assertEqual("job-deadline", self.check())

    def test_timeout_fit_is_rechecked_after_delayed_permission_read(self) -> None:
        original = policy.long_permission_reason

        def delayed(*args: Any, **kwargs: Any) -> str:
            result = original(*args, **kwargs)
            self.clock[0] = 20.001
            return str(result)

        with mock.patch.object(policy, "long_permission_reason", side_effect=delayed):
            self.assertEqual("job-deadline", self.check())

    def test_last_budget_charge_remains_current_without_new_permission(self) -> None:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            db.executemany("INSERT INTO spends VALUES (?)", [(100,)] * (policy.DAILY_CAP - 1))
            db.commit()
        header = jobs.live_header(self.active.owner.live)
        assert header is not None
        req = request(
            job_id=self.active.job.id,
            max_evidence_passes=3,
            plan_sha256=jobs.digest(header["plan"]),
            prompt_bytes=10,
            destination_sha256=header["destination_sha256"],
        )
        permit = markers.reserve(self.config, self.active.owner, request=req, now=100)
        self.assertTrue(permit.launch)
        self.assertEqual(policy.DAILY_CAP, policy.status(self.config, now=100)["used"])
        self.assertEqual("", self.check())

    def test_missing_permission_read_creates_nothing(self) -> None:
        path = Path(self.config.state_home) / "absent"
        config = dataclasses.replace(self.config, state_dir=path)
        self.assertEqual(
            "store-unavailable", policy.long_permission_reason(config, self.permission)
        )
        self.assertFalse(path.exists())

    def test_unattributed_or_changed_header_cannot_bind_context(self) -> None:
        route = dataclasses.replace(self.route, model="unbound-model")
        self.assertEqual(
            "context-changed", self.check(context=dataclasses.replace(self.context, route=route))
        )
        raw = json.loads(markers.marker_path(self.config, self.active.job.id).read_text())
        raw["owner"] = "f" * 32
        markers.marker_path(self.config, self.active.job.id).write_text(json.dumps(raw))
        self.assertEqual("context-changed", self.check())
