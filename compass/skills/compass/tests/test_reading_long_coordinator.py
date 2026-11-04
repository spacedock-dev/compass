"""Actual source threads finalize under their shared slot, including zero-call failures."""

from __future__ import annotations

import contextlib
import http.client
import json
import subprocess
import sys
import threading
import unittest
from typing import Any
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
from compass_runtime import reading_long_inspection as inspection
from compass_runtime import reading_long_markers as markers
from compass_runtime import reading_policy as policy

from . import test_reading_long_admission as admission_tests
from . import test_reading_long_worker as worker_tests


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
            self.assertTrue(release.wait(5))
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
                self.assertTrue(entered.wait(3))
                self.assertIsNotNone(markers.load(self.config, job["id"]))
                status, body = self.fixture.fixture.fixture._post(port, self.fixture.payload)
                self.assertEqual(409, status, body)
                self.assertEqual("in-flight", json.loads(body)["reason"])
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
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
                    thread.join(5)
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
            self.assertTrue(release.wait(3))
            return handover(current, group)

        def spawn(_command: Any, **kwargs: Any) -> subprocess.Popen[bytes]:
            command = (
                [sys.executable, "-c", "import time; time.sleep(1)"]
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
                self.assertTrue(entered.wait(3), errors)
                self.assertIsNone(job.group)
                if action == "clear":
                    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
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
                thread.join(5)
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
            thread.join(timeout=5)
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

    def test_resource_or_permission_stop_is_not_overwritten_by_earlier_provider_failure(
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
        for cause in ("prepare-time", "permission-changed", "intent-changed", "job-deadline"):
            with self.subTest(cause=cause):
                reason, outcome = coordinator._outcome(
                    started, inspected, cause, diagnostic, reading.WITHHELD_CLAUDE_TIMED_OUT
                )
                self.assertEqual(reading.WITHHELD_LONG_INCOMPLETE, reason)
                self.assertEqual("withheld", outcome)

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
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual("time", self.diagnostic()["source"]["reason"])
        self.assertEqual(0, self.diagnostic()["source"]["usage"]["io_bytes"])
        self.assertGreaterEqual(self.diagnostic()["source"]["usage"]["prepare_ms"], 61000)

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
            thread.join(timeout=5)
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
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertFalse(reading.job_cancelled(started.context.active.job))
        self.assertEqual(reading.WITHHELD["long-incomplete"], self.entry()["withheld"])
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
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual((), self.entry()["revisions"])
        self.assertNotIn("long_diagnostic", self.entry())
        self.assertIsNotNone(markers.load(self.config, started.context.active.job.id))
        self.assertIsNone(reading.job(self.config, self.fixture.key))


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

    def test_owned_timeout_retains_charge_and_specific_reason_after_proven_cleanup(self) -> None:
        saved = self.actual_case(timed_out=True)
        self.assertNotIn("assessment", saved)
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CLAUDE_TIMED_OUT], saved["withheld"])

    def actual_case(self, *, timed_out: bool = False) -> annotation_store.Annotation:
        fixture = worker_tests.GuardedNativeWorkerTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.goal = "Keep the retry safe."
        fixture.make_case(ci_state="unbound")
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
            clock=lambda: fixture.now,
        )
        popen = subprocess.Popen
        calls: list[list[str]] = []

        def spawn(command: list[str], **kwargs: Any) -> subprocess.Popen[bytes]:
            if command[0] == "/owned/git":
                value = "a" * 40 if command[-1] == "HEAD" else "https://github.com/acme/widgets"
                return popen([sys.executable, "-c", f"print({value!r})"], **kwargs)
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
        ):
            thread = coordinator.launch(app, started, binary_resolver=lambda name: f"/owned/{name}")
            thread.join(20)
        self.assertFalse(thread.is_alive())
        count = 1 if timed_out else 2
        if timed_out:
            self.assertEqual(
                reading.WITHHELD_CLAUDE_TIMED_OUT,
                withheld.call_args.kwargs.get("withheld_reason"),
                withheld.call_args.args[2],
            )
        self.assertEqual(count, len(calls), [call.args[2] for call in withheld.call_args_list])
        self.assertTrue(started.context.active.job.group.cleanup_complete())
        saved = annotation_store.find(
            annotation_store.load(fixture.config), "claude", fixture.row["sid"]
        )
        assert saved is not None
        self.assertEqual(1, annotation_store.published(saved)["reading_count"])
        diagnostic = saved["long_diagnostic"]
        assert diagnostic is not None
        self.assertEqual(count, diagnostic["accounting"]["totals"]["calls"])
        self.assertIsNone(markers.load(fixture.config, started.context.active.job.id))
        self.assertIsNone(reading.job(fixture.config, f"claude:{fixture.row['sid']}"))
        return saved
