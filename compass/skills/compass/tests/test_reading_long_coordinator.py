"""Actual source threads finalize under their shared slot, including zero-call failures."""

from __future__ import annotations

import contextlib
import http.client
import json
import subprocess
import sys
import threading
import time
import types
import unittest
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import (
    aggregate,
    observer,
    reading,
    reading_route,
    reading_source_collect,
    supervise,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import reading_long_admission as admission
from compass_runtime import reading_long_coordinator as coordinator
from compass_runtime import reading_long_execution as execution
from compass_runtime import reading_long_finalize as finalization
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_long_reconcile as reconcile
from compass_runtime import reading_long_worker as worker
from compass_runtime import reading_policy as policy

from . import test_reading_long_admission as admission_tests
from . import test_reading_long_worker as worker_tests

if TYPE_CHECKING:
    from collections.abc import Callable


def advancing_clock(start: float) -> Callable[[], float]:
    began = time.monotonic()
    return lambda: start + time.monotonic() - began


class LongCoordinatorTest(unittest.TestCase):
    def test_http_long_start_shared_slot_duplicate_and_cancel_use_actual_source_thread(
        self,
    ) -> None:
        entered, release = threading.Event(), threading.Event()
        original = reading_source_collect.collect
        seen: list[str] = []
        threads: list[threading.Thread] = []
        launch = coordinator.launch

        def launched(*args: Any, **kwargs: Any) -> threading.Thread:
            thread = launch(*args, **kwargs)
            threads.append(thread)
            return thread

        def collect(*args: Any, **kwargs: Any) -> reading_source_collect.Collection:
            seen.append("source")
            entered.set()
            self.assertTrue(release.wait(30))
            return original(*args, **kwargs)

        with (
            mock.patch.object(reading_source_collect, "collect", side_effect=collect),
            mock.patch.object(coordinator, "launch", side_effect=launched),
            mock.patch.object(
                self.app, "collect_json", side_effect=AssertionError("ordinary source scan")
            ),
            self.fixture.fixture.fixture._serving(self.app) as port,
        ):
            try:
                status, body = self.fixture.fixture.fixture._post(port, self.fixture.payload)
                self.assertEqual(202, status, body)
                job = json.loads(body)["job"]
                self.assertEqual("long", job["mode"])
                self.assertTrue(entered.wait(30))
                self.assertIsNotNone(markers.load(self.config, job["id"]))
                status, body = self.fixture.fixture.fixture._post(port, self.fixture.payload)
                self.assertEqual(409, status, body)
                self.assertEqual("in-flight", json.loads(body)["reason"])
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                try:
                    for identity, expected in (("0" * 32, 409), (job["id"], 202)):
                        conn.request(
                            "POST",
                            "/api/reading/cancel",
                            json.dumps(
                                {
                                    "harness": "claude",
                                    "sid": "abc123ab",
                                    "job": identity,
                                    "press": True,
                                    "observer_model": 1,
                                }
                            ),
                            {"Content-Type": "application/json"},
                        )
                        response = conn.getresponse()
                        self.assertEqual(expected, response.status, response.read())
                finally:
                    conn.close()
            finally:
                release.set()
                for thread in threads:
                    thread.join(30)
                    self.assertFalse(thread.is_alive())
        self.assertEqual(["source"], seen)

    def test_clear_between_real_spawn_and_handover_stops_child_without_reader_cancel(self) -> None:
        self.parked_stop("clear")

    def test_pause_then_resume_between_spawn_and_handover_does_not_reopen_job(self) -> None:
        self.parked_stop("pause")

    def parked_stop(self, action: str) -> None:  # noqa: PLR0915 - actual HTTP/process race and durable cleanup proof
        started = self.admitted()
        job = started.context.active.job
        entered, release = threading.Event(), threading.Event()
        seen: list[supervise.Group] = []
        errors: list[BaseException] = []
        handover = reading.hand_over
        popen = subprocess.Popen

        def parked(current: reading.Job, group: supervise.Group) -> bool:
            seen.append(group)
            entered.set()
            self.assertTrue(release.wait(30))
            return handover(current, group)

        def spawn(_command: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            command = (
                # Outlives any HTTP round trip, so only the handover's cancel can end it:
                # at one second a slow Clear let it exit by itself first.
                [sys.executable, "-c", "import time; time.sleep(60)"]
                if _command[0] == "/fixture/cli"
                else _command
            )
            return popen(command, **kwargs)

        def call() -> None:
            try:
                model = execution.guard(
                    self.config,
                    started.context,
                    1,
                    clock=self.app.clock,
                    runner=supervise.run,
                    binary_resolver=lambda _name: "/fixture/cli",
                )
                model("actual prompt", output_cap_bytes=8192)
            except Exception as error:  # noqa: BLE001 - surface thread errors to the test owner
                errors.append(error)

        with (
            mock.patch.object(
                observer, "reading_workdir_root", return_value=str(self.config.state_dir)
            ),
            mock.patch.object(reading, "hand_over", side_effect=parked),
            mock.patch.object(subprocess, "Popen", side_effect=spawn),
            self.fixture.fixture.fixture._serving(self.app) as port,
        ):
            thread = threading.Thread(target=call)
            thread.start()
            try:
                self.assertTrue(entered.wait(30), errors)
                self.assertIsNone(job.group)
                if action == "clear":
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
                    try:
                        conn.request(
                            "POST",
                            "/api/annotate",
                            json.dumps(
                                {
                                    "harness": "claude",
                                    "sid": "abc123ab",
                                    "clear": True,
                                    "expected_revision": 1,
                                }
                            ),
                            {"Content-Type": "application/json"},
                        )
                        response = conn.getresponse()
                        self.assertEqual(200, response.status, response.read())
                    finally:
                        conn.close()
                else:
                    for consent in ("off", "on"):
                        status, body = self.fixture.fixture.fixture._post(
                            port,
                            {
                                "consent": consent,
                                "press": True,
                                "observer_model": 1,
                            },
                        )
                        self.assertEqual(200, status, body)
            finally:
                release.set()
                thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertTrue(seen[0].cleanup_complete(), errors)
        self.assertTrue(seen[0].cancelled())
        self.assertFalse(reading.job_cancelled(job))
        self.assertFalse(reading.commit_job(job), "Clear/Pause must latch before handover")
        self.assertEqual(
            "intent-changed" if action == "clear" else "permission-changed",
            reading.long_stop_reason(job),
        )
        inspected = inspection.inspect(self.config, job.id, now=self.app.clock())
        assert inspected.exact is not None
        self.assertEqual(1, inspected.exact.calls)
        with mock.patch.object(seen[0], "cleanup_complete", return_value=False):
            result = self.module.finish_withheld(self.app, started, "cancelled")
        self.assertEqual("unstopped", result.reason)
        self.assertIs(job, reading.job(self.config, self.fixture.key))
        public = reading.published_jobs(self.config)[self.fixture.key]
        self.assertEqual("cleanup-unresolved", public.get("blocked_reason"))
        public["blocked_reason"] = "changed"
        self.assertEqual(
            "cleanup-unresolved",
            reading.published_jobs(self.config)[self.fixture.key]["blocked_reason"],
        )
        marker = markers.load(self.config, job.id)
        assert marker is not None
        self.assertEqual("active", marker["state"])
        result = self.module.finish_withheld(self.app, started, reading.long_stop_reason(job))
        self.assertIsNone(reading.job(self.config, self.fixture.key))
        self.assertEqual(action == "pause", result.acknowledged)
        if action == "pause":
            self.assertIsNone(markers.load(self.config, job.id))
            self.assertEqual(1, annotation_store.published(self.entry())["reading_count"])
        else:
            self.assertIsNotNone(markers.load(self.config, job.id))

    def setUp(self) -> None:
        self.module = coordinator
        self.fixture = admission_tests.LongAdmissionTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app, self.config, self.state = (
            self.fixture.app,
            self.fixture.config,
            self.fixture.state,
        )

    def admitted(self) -> admission.Started:
        result = self.fixture.admit()
        assert result.started is not None
        return result.started

    def entry(self) -> annotation_store.Annotation:
        value = annotation_store.find(annotation_store.load(self.config), "claude", "abc123ab")
        assert value is not None
        return value

    def diagnostic(self) -> dict[str, Any]:
        value = self.entry().get("long_diagnostic")
        assert value is not None
        return value

    def test_real_incomplete_source_stores_truthful_zero_call_outcome_before_teardown(self) -> None:
        started = self.admitted()
        with mock.patch.object(
            self.app, "collect_json", side_effect=AssertionError("extra source scan")
        ):
            thread = self.module.launch(self.app, started)
            thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(reading.job(self.config, self.fixture.key))
        self.assertIsNone(markers.load(self.config, started.context.active.job.id))
        entry = self.entry()
        self.assertEqual(reading.WITHHELD["long-incomplete"], entry["withheld"])
        self.assertEqual("exact", self.diagnostic()["accounting"]["state"])
        self.assertEqual(0, self.diagnostic()["accounting"]["totals"]["calls"])
        self.assertEqual(0, annotation_store.published(entry)["reading_count"])
        self.assertGreater(self.diagnostic()["source"]["usage"]["io_bytes"], 0)

    def test_post_registration_rejection_is_finalized_before_admission_releases_its_job(
        self,
    ) -> None:
        begin = markers.begin

        def paused(*args: Any, **kwargs: Any) -> markers.MarkerOwner | None:
            owner = begin(*args, **kwargs)
            policy.set_consent(self.config, False, now=self.app.clock())
            return owner

        def rejected(started: admission.Started, reason: str) -> None:
            coordinator.finish_withheld(self.app, started, reason)

        with mock.patch.object(markers, "begin", side_effect=paused):
            result = admission.admit(
                self.app,
                self.fixture.fixture.row,
                self.fixture.payload,
                clock=lambda: self.fixture.clock[0],
                on_rejected=rejected,
            )
        self.assertEqual("permission-changed", result.reason)
        assert result.unresolved_job_id is not None
        self.assertIsNone(markers.load(self.config, result.unresolved_job_id))
        self.assertIsNone(reading.job(self.config, self.fixture.key))
        self.assertEqual(0, self.diagnostic()["accounting"]["totals"]["calls"])

    def test_unknown_ledger_retains_marker_without_inventing_zero_or_annotation_ack(self) -> None:
        started = self.admitted()
        policy.store_path(self.config).unlink()
        result = coordinator.finish_withheld(self.app, started, "permission-changed")
        self.assertFalse(result.acknowledged)
        self.assertIsNotNone(markers.load(self.config, started.context.active.job.id))
        self.assertNotIn("long_diagnostic", self.entry())
        self.assertNotIn("jobs", self.entry())
        self.assertIsNone(reading.job(self.config, self.fixture.key))

    def test_ordinary_job_is_not_stopped_by_long_pause_or_clear_hooks(self) -> None:
        job = reading.start_job(
            self.config, self.fixture.key, provider="claude", label="Claude", now=self.app.clock()
        )
        assert job is not None
        self.assertFalse(coordinator.stop(self.app, self.fixture.key, reason="intent-changed"))
        coordinator.stop_all(self.app)
        self.assertTrue(reading.commit_job(job))
        self.assertFalse(reading.job_cancelled(job))
        self.assertNotIn("mode", reading.published_jobs(self.config)[self.fixture.key])

    def test_completed_cleanup_unknown_projects_blocked_even_after_accepted_cancel(self) -> None:
        started = self.admitted()
        job = started.context.active.job
        self.assertTrue(reading.cancel_job(self.config, self.fixture.key, job.id, now=12)[0])
        # Unknown cleanup is not completion, even if no qualified candidate can be examined.
        reading.hand_over(job, object())
        with mock.patch.object(finalization, "completed", side_effect=AssertionError):
            coordinator._completed(
                self.app,
                started,
                mock.Mock(spec=reading_source_collect.Collection),
                mock.Mock(spec=worker.Mapped),
                mock.Mock(spec=reconcile.Finished),
            )
        self.assertIs(job, reading.job(self.config, self.fixture.key))
        self.assertEqual(
            "cleanup-unresolved",
            reading.published_jobs(self.config)[self.fixture.key]["blocked_reason"],
        )
        self.assertEqual("unstopped", reading.long_stop_reason(job))
        self.assertIsNotNone(markers.load(self.config, job.id))
        self.assertNotIn("long_diagnostic", self.entry())

    def test_a_resource_or_deadline_stop_is_not_overwritten_by_earlier_provider_failure(
        self,
    ) -> None:
        started = self.admitted()
        inspected = inspection.inspect(
            self.config, started.context.active.job.id, now=self.app.clock()
        )
        diagnostic = {
            "observations": [
                {
                    "observation": {
                        "diagnostic": {
                            "input": {
                                "outcome": "error",
                                "attempt_reserved": True,
                            }
                        }
                    }
                }
            ]
        }
        for cause in ("prepare-time", "job-deadline"):
            with self.subTest(cause=cause):
                reason, outcome = coordinator._outcome(
                    started, inspected, cause, diagnostic, reading.WITHHELD_CLAUDE_TIMED_OUT
                )
                self.assertEqual(reading.WITHHELD_LONG_INCOMPLETE, reason)
                self.assertEqual("withheld", outcome)

    def test_a_permission_or_intent_stop_names_its_cause_over_an_earlier_provider_failure(
        self,
    ) -> None:
        started = self.admitted()
        inspected = inspection.inspect(
            self.config, started.context.active.job.id, now=self.app.clock()
        )
        failed = {
            "observations": [
                {
                    "observation": {
                        "diagnostic": {"input": {"outcome": "error", "attempt_reserved": True}}
                    }
                }
            ]
        }
        expected = {
            "permission-changed": reading.WITHHELD_LONG_PERMISSION_CHANGED,
            "model-calls-paused": reading.WITHHELD_LONG_PERMISSION_CHANGED,
            "run-disabled": reading.WITHHELD_LONG_PERMISSION_CHANGED,
            "intent-changed": reading.WITHHELD_LONG_INTENT_CHANGED,
        }
        for cause, key in expected.items():
            with self.subTest(cause=cause):
                self.assertEqual(
                    (key, "withheld"),
                    coordinator._outcome(
                        started, inspected, cause, failed, reading.WITHHELD_CLAUDE_TIMED_OUT
                    ),
                )

    def test_thread_start_failure_finalizes_known_zero_while_still_owning_slot(self) -> None:
        started = self.admitted()
        with (
            mock.patch.object(
                threading.Thread, "start", side_effect=RuntimeError("thread refused")
            ),
            self.assertRaises(RuntimeError),
        ):
            self.module.launch(self.app, started)
        self.assertIsNone(reading.job(self.config, self.fixture.key))
        self.assertIsNone(markers.load(self.config, started.context.active.job.id))
        self.assertEqual(0, self.diagnostic()["accounting"]["totals"]["calls"])

    def test_initial_input_joins_use_the_same_preparation_allowance(self) -> None:
        started = self.admitted()
        goals = coordinator._goals

        def slow(inputs: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
            self.fixture.clock[0] += 61
            return goals(inputs)

        with mock.patch.object(coordinator, "_goals", side_effect=slow):
            thread = coordinator.launch(self.app, started)
            thread.join(30)
        self.assertFalse(thread.is_alive())
        self.assertEqual("time", self.diagnostic()["source"]["reason"])
        self.assertEqual(0, self.diagnostic()["source"]["usage"]["io_bytes"])
        self.assertGreaterEqual(self.diagnostic()["source"]["usage"]["prepare_ms"], 61000)
        self.assertEqual("resource-limit", self.diagnostic().get("stop_reason"))

    def test_cancel_during_preparation_is_immediate_and_unspent(self) -> None:
        started = self.admitted()
        original = reading_source_collect.collect

        def collect(*args: Any, **kwargs: Any) -> reading_source_collect.Collection:
            reading.cancel_job(
                self.config, self.fixture.key, started.context.active.job.id, now=self.app.clock()
            )
            self.assertTrue(kwargs["cancelled"]())
            return original(*args, **kwargs)

        with mock.patch.object(reading_source_collect, "collect", side_effect=collect):
            thread = self.module.launch(self.app, started)
            thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        self.assertEqual(
            reading.WITHHELD[reading.WITHHELD_CANCELLED_UNSENT], self.entry()["withheld"]
        )
        self.assertEqual(0, policy.status(self.config, now=self.app.clock())["used"])

    def test_cross_dashboard_pause_during_preparation_is_not_relabelled_reader_cancel(self) -> None:
        started = self.admitted()
        original = reading_source_collect.collect

        def collect(*args: Any, **kwargs: Any) -> reading_source_collect.Collection:
            policy.set_consent(self.config, False, now=self.app.clock())
            policy.resume(self.config, now=self.app.clock())
            self.fixture.clock[0] += 1
            self.assertTrue(kwargs["cancelled"]())
            return original(*args, **kwargs)

        with mock.patch.object(reading_source_collect, "collect", side_effect=collect):
            thread = self.module.launch(self.app, started)
            thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        self.assertFalse(reading.job_cancelled(started.context.active.job))
        self.assertEqual(
            reading.WITHHELD[reading.WITHHELD_LONG_PERMISSION_CHANGED], self.entry()["withheld"]
        )
        self.assertEqual(0, self.diagnostic()["accounting"]["totals"]["calls"])

    def test_clear_during_preparation_preserves_marker_and_never_recreates_annotation(self) -> None:
        started = self.admitted()
        original = reading_source_collect.collect

        def collect(*args: Any, **kwargs: Any) -> reading_source_collect.Collection:
            annotation_store.clear(self.config, self.state, "claude", "abc123ab")
            self.fixture.clock[0] += 1
            self.assertTrue(kwargs["cancelled"]())
            return original(*args, **kwargs)

        with mock.patch.object(reading_source_collect, "collect", side_effect=collect):
            thread = self.module.launch(self.app, started)
            thread.join(timeout=30)
        self.assertFalse(thread.is_alive())
        self.assertEqual((), self.entry()["revisions"])
        self.assertNotIn("long_diagnostic", self.entry())
        self.assertIsNotNone(markers.load(self.config, started.context.active.job.id))
        self.assertIsNone(reading.job(self.config, self.fixture.key))


# The final pass is built for the plan's last ordinal, after the one map pass of this fixture.
FINAL_ORDINAL = 17


class ActualLongCoordinatorTest(unittest.TestCase):
    def test_real_source_two_owned_cli_calls_and_qualified_partial_count_one_job(self) -> None:
        saved = self.actual_case()
        self.assertIn("assessment", saved)
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual("partial", diagnostic["outcome"])
        self.assertFalse(diagnostic["complete"])
        assessment = saved["assessment"]
        assert assessment is not None
        self.assertEqual(reading.RESULT_UNVERIFIABLE, assessment["criteria"]["goal"]["result"])
        self.assertEqual(reading.RESULT_DEPARTURE, assessment["criteria"]["line_1"]["result"])

    def test_a_reading_whose_context_changes_before_its_first_pass_says_the_context_changed(
        self,
    ) -> None:
        saved = self.actual_case(context_changes_at=1)
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_LONG_CONTEXT_CHANGED], saved["withheld"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual("context-changed", diagnostic["stop_reason"])
        self.assertEqual(0, diagnostic["accounting"]["totals"]["calls"])

    def test_a_reading_whose_target_could_not_be_confirmed_after_a_charged_pass_says_so_and_keeps_the_count(
        self,
    ) -> None:
        saved = self.actual_case(context_changes_at=FINAL_ORDINAL, stop_latch="intent-changed")
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_LONG_INTENT_CHANGED], saved["withheld"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual("context-changed", diagnostic["stop_reason"])
        self.assertEqual(1, diagnostic["accounting"]["totals"]["calls"])

    def test_a_real_goal_edit_after_a_charged_pass_stores_nothing_against_the_new_revision(
        self,
    ) -> None:
        saved = self.actual_case(context_changes_at=FINAL_ORDINAL, target_change="edit")
        self.assertEqual(2, len(saved["revisions"]))
        self.assertEqual("Changed", saved["revisions"][-1]["goal"])
        for key in ("withheld", "long_diagnostic", "assessment"):
            self.assertNotIn(key, saved)
        self.assertEqual(0, annotation_store.published(saved)["reading_count"])

    def test_a_real_clear_after_a_charged_pass_stores_nothing_against_the_discarded_entry(
        self,
    ) -> None:
        saved = self.actual_case(context_changes_at=FINAL_ORDINAL, target_change="clear")
        self.assertEqual((), saved["revisions"])
        for key in ("withheld", "long_diagnostic", "assessment"):
            self.assertNotIn(key, saved)

    def test_a_reading_paused_after_a_charged_pass_says_so_and_keeps_the_count(self) -> None:
        saved = self.actual_case(context_changes_at=FINAL_ORDINAL, stop_latch="permission-changed")
        self.assertEqual(
            reading.WITHHELD[reading.WITHHELD_LONG_PERMISSION_CHANGED], saved["withheld"]
        )
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual("permission-changed", diagnostic["stop_reason"])
        self.assertEqual(1, diagnostic["accounting"]["totals"]["calls"])

    def test_a_final_pass_refused_at_its_call_for_a_changed_context_says_so_after_charged_evidence(
        self,
    ) -> None:
        saved = self.actual_case(context_changes_at=FINAL_ORDINAL, refuse_call="context-changed")
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_LONG_CONTEXT_CHANGED], saved["withheld"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual("context-changed", diagnostic["stop_reason"])
        self.assertEqual(1, diagnostic["accounting"]["totals"]["calls"])

    def test_a_final_pass_refused_at_its_call_for_a_daily_cap_stays_incomplete(self) -> None:
        saved = self.actual_case(context_changes_at=FINAL_ORDINAL, refuse_call="daily-cap")
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_LONG_INCOMPLETE], saved["withheld"])

    def test_settings_refused_on_the_final_pass_names_the_settings_after_charged_evidence(
        self,
    ) -> None:
        saved = self.actual_case(context_changes_at=FINAL_ORDINAL, preflight="settings-refused")
        self.assertEqual(
            reading.WITHHELD[reading.WITHHELD_LONG_SETTINGS_REFUSED], saved["withheld"]
        )
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual(1, diagnostic["accounting"]["totals"]["calls"])

    def test_settings_refused_before_any_charge_says_nothing_was_sent(self) -> None:
        saved = self.actual_case(context_changes_at=1, preflight="settings-refused")
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_SETTINGS_REFUSED], saved["withheld"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual(0, diagnostic["accounting"]["totals"]["calls"])

    def test_advancing_real_clock_publishes_after_two_actual_owned_calls(self) -> None:
        saved = self.actual_case(advancing=True)
        self.assertIn("assessment", saved)
        self.assertEqual(1, saved["readings"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual("partial", diagnostic["outcome"])

    def test_unacknowledged_publication_failure_keeps_measured_withheld_after_actual_calls(
        self,
    ) -> None:
        with mock.patch.object(
            annotation_store, "record_reading", return_value=annotation_store.OUTCOME_REFUSED
        ):
            saved = self.actual_case(advancing=True)
        self.assertNotIn("assessment", saved)
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_LONG_INCOMPLETE], saved["withheld"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual("withheld", diagnostic["outcome"])
        self.assertEqual("unknown", diagnostic["stop_reason"])
        self.assertEqual(2, diagnostic["accounting"]["totals"]["calls"])

    def test_invalid_or_unavailable_publication_falls_back_without_claiming_final_coverage(
        self,
    ) -> None:
        for reason in ("publication-invalid", "publication-unavailable"):
            with (
                self.subTest(reason=reason),
                mock.patch.object(
                    finalization, "completed", return_value=finalization.Finalized(reason=reason)
                ),
            ):
                saved = self.actual_case(advancing=True)
                diagnostic = saved["long_diagnostic"]
                assert diagnostic is not None
                self.assertEqual("withheld", diagnostic["outcome"])
                self.assertEqual("unknown", diagnostic["stop_reason"])

    def test_durable_acknowledgment_never_falls_back_when_retirement_fails(self) -> None:
        with (
            mock.patch.object(inspection, "_retire_locked", return_value=False),
            mock.patch.object(coordinator, "finish_withheld", side_effect=AssertionError),
        ):
            saved = self.actual_case(advancing=True, retained="acknowledged")
        self.assertIn("assessment", saved)
        self.assertNotIn("withheld", saved)

    def test_failed_fallback_store_keeps_marker_and_does_not_ack_or_count(self) -> None:
        original = annotation_store.record_withheld

        def unwritable(*args: Any, **kwargs: Any) -> str:
            with mock.patch.object(annotation_store, "save", return_value=False):
                return original(*args, **kwargs)

        with (
            mock.patch.object(
                annotation_store, "record_reading", return_value=annotation_store.OUTCOME_REFUSED
            ),
            mock.patch.object(annotation_store, "record_withheld", side_effect=unwritable),
        ):
            self.actual_case(advancing=True, retained="unpublished")

    def test_accounting_lost_at_publication_retains_marker_without_fabricated_count(self) -> None:
        original = finalization.completed

        def lost(*args: Any, **kwargs: Any) -> finalization.Finalized:
            policy.store_path(args[0]).unlink()
            return original(*args, **kwargs)

        with mock.patch.object(finalization, "completed", side_effect=lost):
            self.actual_case(advancing=True, retained="unpublished")

    def test_owned_timeout_retains_charge_and_specific_reason_after_proven_cleanup(self) -> None:
        saved = self.actual_case(timed_out=True)
        self.assertNotIn("assessment", saved)
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CLAUDE_TIMED_OUT], saved["withheld"])

    def test_unstopped_first_map_never_starts_a_later_factory_or_replaces_uncertain_group(
        self,
    ) -> None:
        self.actual_case(unstopped="evidence")

    def test_unstopped_final_preserves_its_observation_marker_slot_and_blocked_state(self) -> None:
        self.actual_case(unstopped="reconciliation")

    def test_unstopped_owned_ci_never_reaches_model_factory_or_charge(self) -> None:
        self.actual_case(unstopped="ci")

    def actual_case(  # noqa: C901, PLR0913, PLR0915 - one harness shared by every actual-run scenario
        self,
        *,
        timed_out: bool = False,
        unstopped: str = "",
        advancing: bool = False,
        retained: str = "",
        context_changes_at: int = 0,
        stop_latch: str = "",
        refuse_call: str = "",
        preflight: str = "",
        target_change: str = "",
    ) -> annotation_store.Annotation:
        fixture = worker_tests.GuardedNativeWorkerTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        if unstopped != "ci":
            fixture.goal = "Keep the retry safe."
        fixture.make_case(
            ci_state="ready" if unstopped == "ci" else "unbound", large=unstopped == "evidence"
        )
        entry = annotation_store.find(
            annotation_store.load(fixture.config), "claude", fixture.row["sid"]
        )
        assert entry is not None
        started = admission.Started(
            fixture.context,
            fixture.inventory,
            json.dumps(
                {
                    "row": fixture.row,
                    "entry": entry,
                    "route": reading_route.resolve("claude", config=fixture.config),
                }
            ),
        )
        app = aggregate.Application(
            fixture.config,
            fixture.env.state,
            (),
            native_notifier=lambda _: "",
            popup_notifier=lambda _title, _body: None,
            diagnostic_sink=lambda _: None,
            clock=advancing_clock(fixture.now) if advancing else lambda: fixture.now,
        )
        popen = subprocess.Popen
        real_guard = execution.guard

        def guard(*args: Any, **kwargs: Any) -> Any:
            if args[2] == context_changes_at:
                if preflight:
                    # The guard's own pre-reservation check refuses, as a managed-mcp.json would.
                    model = real_guard(*args, **kwargs)
                    object.__setattr__(model, "_preflight", lambda: preflight)
                    return model
                if refuse_call:
                    # Built fine, then refused at the call itself, before any reservation.
                    model = real_guard(*args, **kwargs)

                    def refused(*_a: Any, **_k: Any) -> Any:
                        raise policy.RefusedError(policy._answer(reason=refuse_call))

                    object.__setattr__(model, "_call", refused)
                    return model
                if target_change:
                    # What the real Edit and Clear routes do: change the stored target, then latch.
                    sid = fixture.row["sid"]
                    if target_change == "edit":
                        annotation_store.annotate(
                            fixture.config,
                            fixture.env.state,
                            "claude",
                            sid,
                            goal="Changed",
                            now=fixture.now,
                        )
                    else:
                        annotation_store.clear(fixture.config, fixture.env.state, "claude", sid)
                    job = started.context.active.job
                    stopped, _ = reading.stop_long_job(
                        fixture.config, f"claude:{sid}", job, reason="intent-changed"
                    )
                    self.assertTrue(stopped)
                    return real_guard(*args, **kwargs)
                if stop_latch:
                    # What Clear, an edit or Pause do while a reading runs: latch first, so the
                    # real gate refuses with the reader's cause rather than a hand-raised one.
                    job = started.context.active.job
                    stopped, _ = reading.stop_long_job(
                        fixture.config, f"claude:{fixture.row['sid']}", job, reason=stop_latch
                    )
                    self.assertTrue(stopped)
                    return real_guard(*args, **kwargs)
                raise policy.RefusedError(policy._answer(reason="context-changed"))
            return real_guard(*args, **kwargs)

        calls: list[list[str]] = []
        ci_calls: list[list[str]] = []
        uncertain: list[supervise.Group] = []
        wait_group = supervise.Group._wait_group

        def quiescence(group: supervise.Group, deadline: float) -> None:
            if not uncertain and (
                bool(ci_calls)
                if unstopped == "ci"
                else len(calls) == (1 if unstopped == "evidence" else 2)
            ):
                uncertain.append(group)
                raise supervise.UnstoppedError(group.pid)
            wait_group(group, deadline)

        def spawn(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
            if command[0] == "/owned/git":
                value = "a" * 40 if command[-1] == "HEAD" else "https://github.com/acme/widgets"
                return popen([sys.executable, "-c", f"print({value!r})"], **kwargs)
            if command[0] == "/owned/gh":
                ci_calls.append(command)
                return popen([sys.executable, "-c", "print('{}')"], **kwargs)
            if command[0] != "/owned/claude":
                return popen(command, **kwargs)
            calls.append(command)
            script = (
                "import sys,json,re; p=sys.stdin.read(); "
                "n=int(re.search(r'^\\[(\\d+)\\] tool_report.*pytest tests/retry.py',p,re.M)[1]); "
                "print(json.dumps("
                + (
                    "{'version':1,'candidates':[{'clause':'line_1','kind':'departs','cites':[n],'detail':'The retry check failed.'}]}"
                    if len(calls) == 1
                    else "{'goal':{'result':'consistent','cites':[n],'detail':''},'line_1':{'result':'departure','cites':[n],'detail':'The retry check failed.'}}"
                )
                + "))"
            )
            return popen([sys.executable, "-c", script], **kwargs)

        with (
            mock.patch.object(subprocess, "Popen", side_effect=spawn),
            mock.patch.object(
                coordinator, "finish_withheld", wraps=coordinator.finish_withheld
            ) as withheld,
            mock.patch.object(supervise, "_wait_posix", return_value=True)
            if timed_out
            else contextlib.nullcontext(),
            mock.patch.object(supervise.Group, "_wait_group", quiescence)
            if unstopped
            else contextlib.nullcontext(),
            mock.patch.object(execution, "guard", side_effect=guard) as factory,
            mock.patch.object(markers, "reserve", wraps=markers.reserve) as reserve,
        ):
            thread = coordinator.launch(app, started, binary_resolver=lambda name: f"/owned/{name}")
            thread.join(45)
        self.assertFalse(thread.is_alive())
        count = 0 if unstopped == "ci" else 1 if timed_out or unstopped == "evidence" else 2
        guards = count
        if context_changes_at:
            # The one map pass is ordinal 1; the final pass takes the plan's last ordinal.
            count = 0 if context_changes_at == 1 else 1
            guards = count + 1
        if timed_out:
            self.assertEqual(
                reading.WITHHELD_CLAUDE_TIMED_OUT,
                withheld.call_args.kwargs.get("withheld_reason"),
                withheld.call_args.args[2],
            )
        self.assertEqual(count, len(calls), [call.args[2] for call in withheld.call_args_list])
        self.assertEqual(guards, factory.call_count)
        self.assertEqual(count, reserve.call_count)
        if unstopped:
            self.assertEqual(1 if unstopped == "ci" else 0, len(ci_calls))
            self.assert_unstopped(fixture, started, uncertain[0], count)
            return entry
        if context_changes_at:
            # No pass ran, so no reading is counted and assert_saved's one-reading rule is moot.
            refused = annotation_store.find(
                annotation_store.load(fixture.config), "claude", fixture.row["sid"]
            )
            assert refused is not None
            return refused
        self.assertTrue(started.context.active.job.group.cleanup_complete())
        return self.assert_saved(fixture, started, count, retained)

    def assert_saved(
        self,
        fixture: worker_tests.GuardedNativeWorkerTest,
        started: admission.Started,
        count: int,
        retained: str,
    ) -> annotation_store.Annotation:
        saved = annotation_store.find(
            annotation_store.load(fixture.config), "claude", fixture.row["sid"]
        )
        assert saved is not None
        self.assertIsNone(reading.job(fixture.config, f"claude:{fixture.row['sid']}"))
        marker = markers.load(fixture.config, started.context.active.job.id)
        self.assertEqual(bool(retained), marker is not None)
        if retained == "unpublished":
            self.assertNotIn("readings", saved)
            self.assertNotIn("long_diagnostic", saved)
            return saved
        self.assertEqual(1, annotation_store.published(saved)["reading_count"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual(count, diagnostic["accounting"]["totals"]["calls"])
        return saved

    def assert_unstopped(
        self,
        fixture: worker_tests.GuardedNativeWorkerTest,
        started: admission.Started,
        group: supervise.Group,
        count: int,
    ) -> None:
        self.assertIs(group, started.context.active.job.group)
        self.assertFalse(group.cleanup_complete())
        key = f"claude:{fixture.row['sid']}"
        self.assertEqual(
            "cleanup-unresolved", reading.published_jobs(fixture.config)[key].get("blocked_reason")
        )
        marker = markers.load(fixture.config, started.context.active.job.id)
        assert marker is not None
        self.assertEqual("active", marker["state"])
        self.assertEqual(count, len(marker["passes"]))
        if count:
            self.assertEqual(
                "unstopped", marker["passes"][-1]["observation"]["diagnostic"]["input"]["outcome"]
            )
        measured = inspection.inspect(
            fixture.config, started.context.active.job.id, now=fixture.now
        )
        assert measured.exact is not None
        self.assertEqual(count, measured.exact.calls)
        self.assertNotIn(
            "long_diagnostic",
            annotation_store.find(
                annotation_store.load(fixture.config), "claude", fixture.row["sid"]
            )
            or {},
        )


class TransportReasonTest(unittest.TestCase):
    @staticmethod
    def _diagnostic(outcome: str, *, attempt_reserved: bool) -> dict[str, Any]:
        measured = {"outcome": outcome, "attempt_reserved": attempt_reserved}
        return {"observations": [{"observation": {"diagnostic": {"input": measured}}}]}

    def test_a_reading_refused_by_settings_before_any_charge_says_so(self) -> None:
        # managed-mcp.json can appear after admission and before the pass reserves its call.
        refused = self._diagnostic("settings-refused", attempt_reserved=False)
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                self.assertEqual(
                    reading.WITHHELD_SETTINGS_REFUSED,
                    coordinator._transport_reason(provider, False, refused),
                )

    def test_a_settings_refusal_after_earlier_charged_passes_names_the_settings_without_claiming_nothing_spent(
        self,
    ) -> None:
        # An uncharged late pass must not describe the earlier charged passes as unspent.
        refused = self._diagnostic("settings-refused", attempt_reserved=False)
        self.assertEqual(
            reading.WITHHELD_LONG_SETTINGS_REFUSED,
            coordinator._transport_reason("claude", True, refused),
        )
        sentence = reading.WITHHELD[reading.WITHHELD_LONG_SETTINGS_REFUSED].lower()
        for phrase in ("nothing was sent", "no reading was counted", "no attempt"):
            self.assertNotIn(phrase, sentence)


class ContextChangedOutcomeTest(unittest.TestCase):
    @staticmethod
    def _decide(
        *,
        calls: int,
        cancelled: bool = False,
        closed: bool = False,
        cause: str = "context-changed",
        latch: str = "",
    ) -> tuple[str, str]:
        job = types.SimpleNamespace(cancelled_after_close=False)
        started = types.SimpleNamespace(
            context=types.SimpleNamespace(active=types.SimpleNamespace(job=job))
        )
        inspected = types.SimpleNamespace(exact=types.SimpleNamespace(calls=calls))
        with (
            mock.patch.object(reading, "job_cancelled", return_value=cancelled),
            mock.patch.object(reading, "long_stop_reason", return_value=latch),
            mock.patch.object(supervise, "closed", return_value=closed),
        ):
            return coordinator._outcome(started, inspected, cause)  # type: ignore[arg-type]

    def test_an_intent_change_after_charged_passes_says_the_lines_changed_and_claims_nothing_unspent(
        self,
    ) -> None:
        for calls in (0, 3):
            for latch in ("", "intent-changed"):
                with self.subTest(calls=calls, latch=latch):
                    self.assertEqual(
                        (reading.WITHHELD_LONG_INTENT_CHANGED, "withheld"),
                        self._decide(calls=calls, cause="intent-changed", latch=latch),
                    )

    def test_paused_disabled_or_changed_permission_names_it_whether_latched_or_checked(
        self,
    ) -> None:
        for cause in ("permission-changed", "model-calls-paused", "run-disabled"):
            for calls in (0, 3):
                for latch in ("", "permission-changed"):
                    with self.subTest(cause=cause, calls=calls, latch=latch):
                        self.assertEqual(
                            (reading.WITHHELD_LONG_PERMISSION_CHANGED, "withheld"),
                            self._decide(calls=calls, cause=cause, latch=latch),
                        )

    def test_an_internal_fault_says_compass_could_not_confirm_its_progress_whether_or_not_spent(
        self,
    ) -> None:
        for cause in (
            "probe-failed",
            "header-unavailable",
            "identity-mismatch",
            "slot-unavailable",
            "marker-incomplete",
        ):
            for calls in (0, 3):
                with self.subTest(cause=cause, calls=calls):
                    self.assertEqual(
                        (reading.WITHHELD_LONG_FAULT, "withheld"),
                        self._decide(calls=calls, cause=cause),
                    )

    def test_no_long_stop_sentence_claims_nothing_was_sent_or_counted(self) -> None:
        for key in (
            *reading.LONG_STOP_WITHHELD.values(),
            reading.WITHHELD_LONG_SETTINGS_REFUSED,
        ):
            with self.subTest(key=key):
                sentence = reading.WITHHELD[key].lower()
                for phrase in ("nothing", "no attempt", "no reading was counted", "unspent"):
                    self.assertNotIn(phrase, sentence)
                self.assertIn("any recorded calls remain counted", sentence)

    def test_a_cancel_or_stop_still_wins_over_a_permission_or_intent_stop(self) -> None:
        for cause in ("intent-changed", "permission-changed", "run-disabled"):
            with self.subTest(cause=cause):
                self.assertEqual(
                    (reading.WITHHELD_CANCELLED, "cancelled"),
                    self._decide(calls=2, cancelled=True, cause=cause),
                )
                self.assertEqual(
                    (reading.WITHHELD_INTERRUPTED, "interrupted"),
                    self._decide(calls=2, closed=True, cause=cause),
                )

    def test_a_context_change_after_charged_passes_never_claims_nothing_was_spent(self) -> None:
        for calls in (0, 3):
            with self.subTest(calls=calls):
                self.assertEqual(
                    (reading.WITHHELD_LONG_CONTEXT_CHANGED, "withheld"), self._decide(calls=calls)
                )
        self.assertNotIn("nothing", reading.WITHHELD[reading.WITHHELD_LONG_CONTEXT_CHANGED].lower())

    def test_a_cancel_or_stop_still_wins_over_a_context_change(self) -> None:
        self.assertEqual(
            (reading.WITHHELD_CANCELLED, "cancelled"), self._decide(calls=2, cancelled=True)
        )
        self.assertEqual(
            (reading.WITHHELD_INTERRUPTED, "interrupted"), self._decide(calls=2, closed=True)
        )
