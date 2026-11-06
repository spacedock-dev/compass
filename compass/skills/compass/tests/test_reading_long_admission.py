"""Fresh long admission binds one source endpoint and shares ordinary priority admission."""

from __future__ import annotations

import json
import threading
import unittest
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import (
    claude_settings,
    live_monitor,
    observer,
    reading,
    reading_long_preview,
    reading_route,
    reading_source_collect,
    settings,
)
from compass_runtime import reading_long_admission as admission
from compass_runtime import reading_long_context as context
from compass_runtime import reading_long_jobs as jobs
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_policy as policy
from compass_runtime import reading_source_inventory as inventory

from . import test_http_reading_long as http_tests

if TYPE_CHECKING:
    from collections.abc import Callable


class LongAdmissionTest(unittest.TestCase):
    def test_long_stop_latches_before_handover_without_accepting_reader_cancel(self) -> None:
        started = self.admit().started
        assert started is not None
        job = started.context.active.job
        stop = getattr(reading, "stop_long_job", None)
        self.assertIsNotNone(stop)
        assert stop is not None
        accepted, group = stop(self.config, self.key, job, reason="intent-changed")
        self.assertTrue(accepted)
        self.assertIsNone(group)
        self.assertFalse(reading.job_cancelled(job))
        self.assertFalse(reading.cancel_job(self.config, self.key, job.id, now=20)[0])
        self.assertFalse(reading.commit_job(job))
        self.assertTrue(reading.hand_over(job, object()))
        self.assertEqual("intent-changed", context.check(self.config, started.context))
        probe = context.Checkpoint(self.config, started.context)
        self.assertTrue(probe())
        self.assertEqual("intent-changed", probe.reason)
        stop(self.config, self.key, job, reason="permission-changed")
        self.assertEqual("intent-changed", probe.reason)

    def test_source_collection_counts_coordinator_owned_input_graph_before_body_io(self) -> None:
        started = self.admit().started
        assert started is not None
        result = reading_source_collect.collect(
            self.config,
            started.inventory,
            held_inputs=(started._inputs, started.inputs, "x" * 65536),
            limits=reading_source_collect.Limits(retained_bytes=4096),
        )
        self.assertEqual("retained_bytes", result.reason)
        self.assertEqual(0, result.usage.source_bytes)
        self.assertIsNone(result.snapshot)

    def setUp(self) -> None:
        self.fixture = http_tests.LongReadingHTTPTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state, self.app = (
            self.fixture.config,
            self.fixture.state,
            self.fixture.app,
        )
        self.key = "claude:abc123ab"
        self.fixture.row["sid"] = "abc123ab"
        annotation_store.annotate(
            self.config, self.state, "claude", "abc123ab", goal="ship the parser", now=10
        )
        self.state.snapshot.publish(
            (self.config.window_hours, False),
            json.dumps(
                {
                    "sessions": [self.fixture.row],
                    "reading": policy.status(self.config, now=self.app.clock()),
                }
            ).encode(),
        )
        self.addCleanup(reading.end_job, self.config, self.key)
        self.clock = [10.0]
        for patcher in (
            mock.patch.object(reading_route, "resolve", return_value=self.fixture.route),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.fixture.path)),
            mock.patch.object(
                claude_settings,
                "resolve",
                return_value=claude_settings.Controls(deployment="direct"),
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.payload = self.fixture.press(
            sid="abc123ab",
            plan_binding=reading_long_preview.describe(self.app, "claude", "abc123ab")["binding"],
        )

    def admit(self, **changes: Any) -> admission.Admission:
        return admission.admit(
            self.app, self.fixture.row, {**self.payload, **changes}, clock=lambda: self.clock[0]
        )

    def test_fresh_admission_binds_current_target_route_source_and_shared_identity_without_charge(
        self,
    ) -> None:
        with mock.patch.object(
            self.app, "collect_json", side_effect=AssertionError("body collection")
        ):
            result = self.admit()
        self.assertEqual("", result.reason)
        started = result.started
        self.assertIsNotNone(started)
        assert started is not None
        job = started.context.active.job
        self.assertIs(job, reading.job(self.config, self.key))
        marker = markers.load(self.config, job.id)
        assert marker is not None
        self.assertEqual(job.id, marker["job_id"])
        self.assertEqual([], marker["passes"])
        self.assertEqual(1, marker["header"]["publication"]["revision"])
        self.assertEqual("", context.check(self.config, started.context))
        self.assertEqual(
            self.fixture.path.stat().st_size, started.inventory.streams[0].cursor.frozen.end_offset
        )
        self.assertEqual(0, policy.status(self.config, now=self.app.clock())["used"])
        before = started.inputs
        self.fixture.row["activity"] = "changed"
        before["entry"]["revisions"][-1]["goal"] = "MUTATION"
        self.assertNotEqual(before, started.inputs)
        self.assertNotEqual("changed", started.inputs["row"]["activity"])
        self.assertNotIn("ship the parser", json.dumps(marker))
        self.assertNotIn(str(self.fixture.path), json.dumps(marker))

    def test_stale_unsupported_and_paused_requests_do_not_freeze_or_take_slot(self) -> None:
        with mock.patch.object(inventory, "freeze", side_effect=AssertionError("source metadata")):
            for changes in (
                {"plan_binding": "a" * 64},
                {"expected_revision": 2},
                {"model": "foreign"},
                {"harness": "codex"},
                {"press": False},
                {"mode": None},
            ):
                with self.subTest(changes=changes):
                    result = self.admit(**changes)
                    self.assertIsNone(result.started)
                    self.assertTrue(result.reason)
                    self.assertIsNone(reading.job(self.config, self.key))
            policy.set_consent(self.config, False, now=self.app.clock())
            result = self.admit()
            self.assertEqual("model-calls-paused", result.reason)
            self.assertIsNone(result.started)

    def test_priority_wait_rechecks_target_route_and_captured_permission(self) -> None:
        real_priority = live_monitor.start_with_priority
        mutations: tuple[Callable[[], Any], ...] = (
            lambda: policy.set_consent(self.config, False, now=self.app.clock()),
            lambda: annotation_store.annotate(
                self.config, self.state, "claude", "abc123ab", goal="new", now=20
            ),
            lambda: settings.save(self.config, {"analyze_prompt_bytes": 256 * 1024}),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):

                def delayed(
                    config: Any,
                    key: str,
                    start: Callable[[], Any],
                    change: Callable[[], Any] = mutation,
                ) -> Any:
                    change()
                    return real_priority(config, key, start)

                with mock.patch.object(live_monitor, "start_with_priority", side_effect=delayed):
                    result = self.admit()
                self.assertIsNone(result.started)
                self.assertTrue(result.reason)
                self.assertIsNone(reading.job(self.config, self.key))
                policy.resume(self.config, now=self.app.clock())
                settings.save(self.config, {"analyze_prompt_bytes": None})
                entry = annotation_store.find(
                    annotation_store.load(self.config), "claude", "abc123ab"
                )
                assert entry is not None
                self.payload["expected_revision"] = entry["revisions"][-1]["n"]
                self.payload["plan_binding"] = reading_long_preview.describe(
                    self.app, "claude", "abc123ab"
                )["binding"]

    def test_ordinary_and_unasked_slot_contention_preserve_the_other_owner(self) -> None:
        ordinary = reading.start_job(
            self.config, self.key, provider="claude", label="Claude", now=self.app.clock()
        )
        self.assertIsNone(self.admit().started)
        self.assertIs(ordinary, reading.job(self.config, self.key))
        reading.end_job(self.config, self.key)
        self.assertTrue(reading.claim(self.config, self.key))
        self.assertIsNone(self.admit().started)
        self.assertFalse(reading.claim(self.config, self.key))
        reading.release(self.config, self.key)

    def test_setup_failure_frees_only_own_job_and_preserves_unresolved_marker(self) -> None:
        real = markers.begin

        def changed(*args: Any, **kwargs: Any) -> markers.MarkerOwner | None:
            owner = real(*args, **kwargs)
            annotation_store.annotate(
                self.config, self.state, "claude", "abc123ab", goal="new", now=20
            )
            return owner

        with mock.patch.object(markers, "begin", side_effect=changed):
            result = self.admit()
        self.assertIsNone(result.started)
        self.assertIsNone(reading.job(self.config, self.key))
        assert result.unresolved_job_id is not None
        marker = markers.load(self.config, result.unresolved_job_id)
        assert marker is not None
        self.assertEqual("failed", marker["state"])
        self.assertEqual([], marker["passes"])
        self.assertEqual(0, policy.status(self.config, now=self.app.clock())["used"])

    def test_whole_job_origin_includes_metadata_and_priority_wait(self) -> None:
        real = inventory.freeze

        def slow(*args: Any, **kwargs: Any) -> inventory.Inventory:
            result = real(*args, **kwargs)
            self.clock[0] += 7
            return result

        with mock.patch.object(inventory, "freeze", side_effect=slow):
            result = self.admit()
        self.assertIsNotNone(result.started)
        assert result.started is not None
        prepared = result.started.context.active.owner.live.prepared
        self.assertEqual(10.0, prepared.started_monotonic)
        self.assertEqual(17.0, prepared.clock())
        self.assertIsNotNone(jobs.header(prepared))

    def test_real_priority_wait_does_not_renew_permission_after_pause_resume(self) -> None:
        running = live_monitor._Running()
        asked = threading.Event()
        real_cancel = running.cancel
        results: list[admission.Admission] = []

        def cancel(reason: str) -> None:
            real_cancel(reason)
            asked.set()

        self.assertTrue(reading.claim(self.config, self.key))
        thread = threading.Thread(target=lambda: results.append(self.admit()))
        with (
            mock.patch.dict(
                live_monitor._RUNNING, {live_monitor._key(self.config, self.key): running}
            ),
            mock.patch.object(running, "cancel", side_effect=cancel),
        ):
            thread.start()
            try:
                self.assertTrue(asked.wait(timeout=30))
                policy.set_consent(self.config, False, now=self.app.clock())
                policy.resume(self.config, now=self.app.clock())
            finally:
                reading.release(self.config, self.key)
                running.done.set()
                thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        self.assertEqual(1, len(results))
        self.assertEqual("permission-changed", results[0].reason)
        self.assertIsNone(results[0].started)
        self.assertIsNone(reading.job(self.config, self.key))
        self.assertEqual(0, policy.status(self.config, now=self.app.clock())["used"])

    def test_marker_write_failure_leaves_no_slot_or_charge(self) -> None:
        with mock.patch.object(markers, "_write", side_effect=OSError("private error")):
            result = self.admit()
        self.assertIsNone(result.started)
        self.assertEqual("admission-unavailable", result.reason)
        self.assertIsNone(reading.job(self.config, self.key))
        self.assertEqual(0, policy.status(self.config, now=self.app.clock())["used"])

    def test_rejected_owner_callback_runs_before_expected_slot_teardown(self) -> None:
        real = markers.begin
        seen: list[admission.Started] = []

        def pause(*args: Any, **kwargs: Any) -> markers.MarkerOwner | None:
            owner = real(*args, **kwargs)
            policy.set_consent(self.config, False, now=self.app.clock())
            return owner

        def rejected(started: admission.Started, reason: str) -> None:
            self.assertEqual("permission-changed", reason)
            self.assertIs(started.context.active.job, reading.job(self.config, self.key))
            marker = markers.load(self.config, started.context.active.job.id)
            assert marker is not None
            self.assertEqual("failed", marker["state"])
            seen.append(started)

        with mock.patch.object(markers, "begin", side_effect=pause):
            result = admission.admit(
                self.app,
                self.fixture.row,
                self.payload,
                clock=lambda: self.clock[0],
                on_rejected=rejected,
            )
        self.assertIsNone(result.started)
        self.assertEqual(1, len(seen))
        self.assertIsNone(reading.job(self.config, self.key))
