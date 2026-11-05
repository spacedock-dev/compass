"""Completed publication is a sealed terminal check, never another execution admission."""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    reading,
    reading_long_markers,
    reading_policy,
    settings,
    supervise,
)

from . import test_reading_long_context as context_tests


class TerminalContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = context_tests.ActiveContextTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.context = self.fixture.config, self.fixture.context
        active, permission = self.fixture.active, self.fixture.permission
        assert active is not None and permission is not None
        self.active, self.permission = active, permission

    def complete(self) -> None:
        self.assertTrue(
            reading_long_markers.seal(self.config, self.active.owner, state="completed", now=100)
        )
        self.assertFalse(reading.seal_job(self.active.job))

    def check(self, **changes: Any) -> str:
        function: Any = getattr(self.fixture.module, "check_publication", None)
        self.assertTrue(callable(function), "the terminal publication gate must be separate")
        return str(
            function(changes.get("config", self.config), changes.get("context", self.context))
        )

    def test_completed_near_deadline_needs_no_new_call_timeout(self) -> None:
        self.complete()
        self.fixture.clock[0] = 199.0
        self.assertEqual("", self.check())
        self.assertEqual("context-changed", self.fixture.check())
        self.fixture.clock[0] = 200.0
        self.assertEqual("", self.check())
        self.fixture.clock[0] = 200.001
        self.assertEqual("job-deadline", self.check())

    def test_active_unsealed_failed_cancelled_or_foreign_slot_never_looks_completed(self) -> None:
        self.assertEqual("context-changed", self.check())
        self.assertTrue(
            reading_long_markers.seal(self.config, self.active.owner, state="completed", now=100)
        )
        self.assertEqual("context-changed", self.check())
        reading.seal_job(self.active.job)
        self.assertEqual("", self.check())
        reading.end_job(self.config, self.fixture.key)
        reading.start_job(self.config, self.fixture.key, provider="claude", label="Claude", now=100)
        self.assertEqual("context-changed", self.check())

    def test_cancel_accepted_before_seal_refuses_prose_and_late_cancel_is_rejected(self) -> None:
        self.assertTrue(
            reading.cancel_job(self.config, self.fixture.key, self.active.job.id, now=101)[0]
        )
        reading_long_markers.seal(self.config, self.active.owner, state="completed", now=100)
        self.assertTrue(reading.seal_job(self.active.job))
        self.assertEqual("cancelled", self.check())
        self.assertFalse(
            reading.cancel_job(self.config, self.fixture.key, self.active.job.id, now=102)[0]
        )

    def test_other_valid_terminal_marker_states_do_not_authorize_completed_prose(self) -> None:
        self.complete()
        path = reading_long_markers.marker_path(self.config, self.active.job.id)
        raw = json.loads(path.read_text())
        for state in ("failed", "cancelled", "interrupted"):
            raw["state"] = state
            path.write_text(json.dumps(raw))
            self.assertIsNotNone(reading_long_markers.load(self.config, self.active.job.id))
            self.assertEqual("context-changed", self.check())

    def test_foreign_process_header_and_descriptor_refuse(self) -> None:
        self.complete()
        foreign = dataclasses.replace(
            self.active,
            owner=dataclasses.replace(self.active.owner, process=object()),
        )
        for context in (
            None,
            dataclasses.replace(self.context, active=foreign),
            dataclasses.replace(self.context, scope_sha256="b" * 64),
        ):
            self.assertEqual("context-changed", self.check(context=context))
        path = reading_long_markers.marker_path(self.config, self.active.job.id)
        raw = json.loads(path.read_text())
        raw["header"]["content"] = 1
        path.write_text(json.dumps(raw))
        self.assertEqual("context-changed", self.check())

    def test_target_edit_and_clear_recreation_refuse_without_writing(self) -> None:
        self.complete()
        annotation_store.annotate(
            self.config, self.fixture.state, "claude", self.fixture.sid, goal="Changed", now=101
        )
        self.assertEqual("intent-changed", self.check())
        annotation_store.clear(self.config, self.fixture.state, "claude", self.fixture.sid)
        annotation_store.annotate(
            self.config,
            self.fixture.state,
            "claude",
            self.fixture.sid,
            goal="Retain words",
            now=100,
        )
        self.assertEqual("intent-changed", self.check())

    def test_route_settings_run_disabled_and_shutdown_refuse(self) -> None:
        self.complete()
        self.fixture.destination = "changed.example"
        self.assertEqual("context-changed", self.check())
        self.fixture.destination = "Anthropic"
        settings.save(self.config, {"analyze_prompt_bytes": 2_097_152})
        self.assertEqual("context-changed", self.check())
        settings.save(self.config, {"analyze_prompt_bytes": None})
        self.assertEqual(
            "run-disabled",
            self.check(config=dataclasses.replace(self.config, model_calls_disabled=True)),
        )
        supervise._SHUTDOWN.set()
        self.assertEqual("closed", self.check())

    def test_elapsed_clock_is_rechecked_after_reads_and_unknown_clock_refuses(self) -> None:
        self.complete()
        original = annotation_store.long_target_current

        def delayed(*args: Any, **kwargs: Any) -> bool:
            result = original(*args, **kwargs)
            self.fixture.clock[0] = 201.0
            return result

        with mock.patch.object(annotation_store, "long_target_current", side_effect=delayed):
            self.assertEqual("job-deadline", self.check())
        for clock in (float("nan"), float("inf"), -1, True):
            self.fixture.clock[0] = clock
            self.assertEqual("job-clock-invalid", self.check())

    def test_read_only_gate_does_not_seal_refresh_permission_or_invoke_any_model(self) -> None:
        self.complete()
        before = {p: p.read_bytes() for p in self.config.state_dir.rglob("*") if p.is_file()}
        with (
            mock.patch.object(reading, "seal_job", side_effect=AssertionError),
            mock.patch.object(reading_policy, "long_permission_reason", side_effect=AssertionError),
            mock.patch.object(
                reading_policy, "capture_long_permission", side_effect=AssertionError
            ),
            mock.patch.object(reading_policy, "reserve", side_effect=AssertionError),
            mock.patch.object(supervise, "run", side_effect=AssertionError),
        ):
            self.assertEqual("", self.check())
        self.assertEqual(
            before, {p: p.read_bytes() for p in self.config.state_dir.rglob("*") if p.is_file()}
        )
        reading_policy.set_consent(self.config, False, now=100)
        # The terminal gate alone grants nothing: permission is a separate held fence.
        self.assertEqual("", self.check())
        with reading_policy.long_publication_permission(self.config, self.permission) as reason:
            self.assertEqual("permission-changed", reason)

    def test_unknown_group_and_running_probe_cannot_claim_cleanup(self) -> None:
        self.complete()
        for group in (object(), mock.Mock(running=lambda: False), supervise.Group(mock.Mock())):
            self.active.job.group = group
            self.assertEqual("unstopped", self.check())
        with mock.patch.object(group, "cleanup_complete", return_value=None):
            self.assertEqual("unstopped", self.check())
        with mock.patch.object(group, "cleanup_complete", side_effect=RuntimeError("PRIVATE")):
            self.assertNotEqual("", self.check())
        self.active.job.group = None
        with mock.patch.object(
            annotation_store, "long_target_current", side_effect=OSError("PRIVATE")
        ):
            self.assertNotEqual("", self.check())

    def test_actual_supervised_child_is_not_complete_until_cleanup_and_gate_never_polls(
        self,
    ) -> None:
        self.complete()
        seen: list[supervise.Group] = []

        def spawned(group: supervise.Group) -> None:
            self.active.job.group = group
            seen.append(group)
            self.assertEqual("unstopped", self.check())

        supervise.run(
            [sys.executable, "-c", "pass"],
            input="",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            on_spawn=spawned,
        )
        with (
            mock.patch.object(seen[0], "running", side_effect=AssertionError),
            mock.patch.object(seen[0]._process, "poll", side_effect=AssertionError),
            mock.patch.object(seen[0], "kill", side_effect=AssertionError),
        ):
            self.assertEqual("", self.check())

    @unittest.skipIf(sys.platform == "win32", "POSIX group quiescence failure")
    def test_unstopped_group_reaped_for_pid_safety_is_not_successful_cleanup(self) -> None:
        self.complete()
        seen: list[supervise.Group] = []

        def spawned(group: supervise.Group) -> None:
            seen.append(group)
            self.active.job.group = group

        with (
            mock.patch.object(supervise, "_group_running", return_value=None),
            self.assertRaises(supervise.UnstoppedError),
        ):
            supervise.run(
                [sys.executable, "-c", "pass"],
                input="",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                on_spawn=spawned,
            )
        self.assertTrue(seen[0]._reaped)
        self.assertEqual("unstopped", self.check())
