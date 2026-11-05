"""Current CI uses retained native inputs and the original shared preparation allowance."""

from __future__ import annotations

import json
import subprocess
import unittest
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import ci_read, git_status, reading_ci_acquire, reading_preparation, supervise
from compass_runtime import reading_source_collect as source

from . import test_reading_source_ci as source_tests
from .test_reading_pass_types import plan


class CurrentCiAcquisitionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = source_tests.FrozenCiBindingTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.collection, _calls = self.fixture.current_inputs()
        assert self.collection.snapshot is not None
        self.snapshot = self.collection.snapshot
        self.tick = 0.0
        self.budget = reading_preparation.Budget(self.snapshot, plan(), clock=lambda: self.tick)
        self.calls: list[list[str]] = []
        self.groups: list[Any] = []
        self.stopped = False
        self.valid = True
        self.remote_head = "a" * 40
        self.merge = ""
        self.job_left = 1000.0

    def current(self) -> str:
        # The actual worker revalidates this same account, so the gate must not hold its lock.
        checked = source.revalidate(self.snapshot, clock=lambda: self.tick)
        self.assertEqual("", checked.reason)
        return "" if self.valid else "context-changed"

    def runner(self, argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(argv))
        self.tick += 1
        options["on_spawn"](object())
        if "merge-base" in argv:
            self.assertEqual(subprocess.DEVNULL, options["stdout"])
            return subprocess.CompletedProcess(argv, 0)
        self.assertEqual(ci_read.TIMEOUT_SEC, options["timeout"])
        self.assertEqual(
            (
                (options["stdout"].name, ci_read.OUTPUT_LIMIT_BYTES),
                (options["stderr"].name, ci_read.STDERR_LIMIT_BYTES),
            ),
            options["output_limits"],
        )
        value: Any
        if argv[1] == "api":
            value = (
                [{"name": "unit", "status": "success", "finished_at": None, "allow_failure": False}]
                if "/jobs?" in argv[2]
                else {
                    "iid": 7,
                    "sha": self.remote_head,
                    "head_pipeline": {"id": 22, "sha": self.remote_head, "status": "success"},
                }
            )
        elif argv[2] == "view":
            value = {
                "headRefOid": self.remote_head,
                "number": 11,
                "state": "MERGED" if self.merge else "OPEN",
                "mergeCommit": {"oid": self.merge} if self.merge else None,
            }
        else:
            value = [
                {
                    "name": "unit",
                    "bucket": "pass",
                    "state": "SUCCESS",
                    "completedAt": "2026-11-05T00:00:00Z",
                }
            ]
        options["stdout"].write(json.dumps(value).encode())
        return subprocess.CompletedProcess(argv, 0)

    def acquire(self, **options: Any) -> reading_ci_acquire.Result:
        with (
            mock.patch.object(
                git_status, "executable", side_effect=lambda name, _env: "/owned/" + name
            ),
            mock.patch.object(git_status, "_executable", return_value="/owned/git"),
            mock.patch.object(ci_read, "glab_hosts", return_value=frozenset({"gitlab.com"})),
            mock.patch.object(ci_read, "scan_records", side_effect=AssertionError("legacy scan")),
        ):
            return reading_ci_acquire.acquire(
                self.fixture.config,
                self.collection,
                self.budget,
                current=options.pop("current", self.current),
                cancelled=lambda: self.stopped,
                remaining_seconds=lambda: self.job_left - self.tick,
                on_spawn=self.groups.append,
                now=options.pop("now", 1000.0),
                environ={},
                runner=options.pop("runner", self.runner),
                **options,
            )

    def test_real_owner_read_keeps_exact_input_association_record_and_shared_usage(self) -> None:
        before = self.snapshot.account.usage
        result = self.acquire()
        self.assertEqual(("complete", ""), (result.state, result.reason))
        self.assertIs(result.inputs, self.collection.current_ci)
        record = result.value()
        assert record is not None
        self.assertEqual(record, ci_read.validate(record))
        self.assertTrue(ci_read.green(record))
        self.assertEqual(1000.0, record["read_at"])
        self.assertEqual((4, 0, 4), (result.ci_calls, result.git_calls, result.spawned))
        self.assertEqual(4, len(self.groups))
        self.assertEqual(before.source_bytes, self.snapshot.account.usage.source_bytes)
        self.assertEqual(before.source_pages, self.snapshot.account.usage.source_pages)
        self.assertAlmostEqual(before.prepare_ms + 4000, self.snapshot.account.usage.prepare_ms)
        self.assertGreater(self.snapshot.account.retained_base_bytes, before.retained_bytes)
        record["checks"][0]["name"] = "mutated"
        again = result.value()
        assert again is not None
        self.assertEqual("unit", again["checks"][0]["name"])
        self.assertEqual("ci:11:0", ci_read.facts(again, "claude", "abc")[0]["fact_id"])

    def test_insufficient_original_or_job_timeout_launches_nothing(self) -> None:
        self.job_left = ci_read.TIMEOUT_SEC - 1
        result = self.acquire()
        self.assertEqual(("stopped", "job-time"), (result.state, result.reason))
        self.assertEqual([], self.calls)
        self.job_left = 1000
        self.snapshot.account.usage = replace(self.snapshot.account.usage, prepare_ms=45_000)
        result = self.acquire()
        self.assertEqual(("stopped", "prepare-time"), (result.state, result.reason))
        self.assertEqual([], self.calls)
        self.assertIsNone(result.value())

    def test_cancel_after_call_and_context_change_at_handover_withhold_record(self) -> None:
        def cancel(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            result = self.runner(argv, **options)
            self.stopped = True
            return result

        result = self.acquire(runner=cancel)
        self.assertEqual(("stopped", "cancelled"), (result.state, result.reason))
        self.assertIsNone(result.value())
        self.assertEqual(1, result.ci_calls)
        self.stopped = False
        self.calls.clear()

        def change(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            result = self.runner(argv, **options)
            if len(self.calls) == 4:
                self.valid = False
            return result

        result = self.acquire(runner=change)
        self.assertEqual(("stopped", "current"), (result.state, result.reason))
        self.assertIsNone(result.value())
        self.assertEqual(4, result.ci_calls)

    def test_owner_ancestry_uses_the_same_guard_budget_and_supervised_spawn(self) -> None:
        self.remote_head, self.merge = "b" * 40, "c" * 40
        result = self.acquire()
        record = result.value()
        assert record is not None
        self.assertTrue(record["merged_in"])
        self.assertFalse(record["head_matches"])
        self.assertTrue(ci_read.green(record))
        self.assertEqual((4, 1, 5), (result.ci_calls, result.git_calls, result.spawned))

    def test_unavailable_input_is_reported_without_a_network_launch(self) -> None:
        self.fixture.config = replace(self.fixture.config, git_probe_enabled=False)
        self.collection, _calls = self.fixture.current_inputs()
        assert self.collection.snapshot is not None
        self.snapshot = self.collection.snapshot
        self.budget = reading_preparation.Budget(self.snapshot, plan(), clock=lambda: self.tick)
        result = self.acquire()
        self.assertEqual(("unavailable", "input-unavailable"), (result.state, result.reason))
        assert result.inputs is not None
        self.assertEqual("disabled", result.inputs.state)
        self.assertEqual([], self.calls)

    def test_gitlab_uses_same_owner_deadline_guard_and_meter(self) -> None:
        self.collection, _calls = self.fixture.current_inputs(
            current_ci_goals=("Read https://gitlab.com/acme/widgets/-/merge_requests/7",)
        )
        assert self.collection.snapshot is not None
        self.snapshot = self.collection.snapshot
        self.budget = reading_preparation.Budget(self.snapshot, plan(), clock=lambda: self.tick)
        result = self.acquire()
        record = result.value()
        assert record is not None
        self.assertEqual(("complete", ""), (result.state, result.reason))
        self.assertTrue(ci_read.green(record))
        self.assertEqual(3, result.ci_calls)
        self.assertEqual("gitlab", ci_read.facts(record, "claude", "abc")[0]["by"])
        self.assertTrue(all(command[-2:] == ["--method", "GET"] for command in self.calls))

    def test_owner_cli_failure_is_unavailable_and_unknown_ancestry_is_never_positive(self) -> None:
        def failing(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            self.tick += 1
            options["stderr"].write(b"authentication required")
            return subprocess.CompletedProcess(argv, 1)

        result = self.acquire(runner=failing)
        record = result.value()
        assert record is not None
        self.assertEqual(("unavailable", "ci-read"), (result.state, result.reason))
        self.assertTrue(record["error"])
        self.assertFalse(ci_read.green(record))
        self.assertEqual(1, result.ci_calls)
        self.remote_head, self.merge = "b" * 40, "c" * 40

        def unknown(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            if "merge-base" in argv:
                self.tick += 1
                raise subprocess.TimeoutExpired(argv, options["timeout"])
            return self.runner(argv, **options)

        result = self.acquire(runner=unknown)
        record = result.value()
        assert record is not None
        self.assertFalse(record["merged_in"])
        self.assertFalse(record["head_matches"])
        self.assertFalse(any(fact["ci_counts"] for fact in ci_read.facts(record, "claude", "abc")))

    def test_retention_clock_and_exception_failures_charge_and_release_shared_account(self) -> None:
        before = self.snapshot.account.usage.prepare_ms

        def out_of_room(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            result = self.runner(argv, **options)
            if len(self.calls) == 4:
                self.snapshot.account.limits = replace(
                    self.snapshot.account.limits,
                    retained_bytes=self.snapshot.account.retained_base_bytes + 50,
                )
            return result

        result = self.acquire(runner=out_of_room)
        self.assertEqual(("stopped", "retained-bytes"), (result.state, result.reason))
        self.assertIsNone(result.value())
        self.assertGreaterEqual(self.snapshot.account.usage.prepare_ms, before + 1000)
        self.assertTrue(self.snapshot.account.lock.acquire(blocking=False))
        self.snapshot.account.lock.release()
        with self.assertRaises(reading_preparation.LimitError):
            reading_preparation.Budget(self.snapshot, plan(), clock=lambda: self.tick)

    def test_runner_exception_and_invalid_interval_clock_stop_without_lock_or_record(self) -> None:
        def broken(_argv: list[str], **_options: Any) -> subprocess.CompletedProcess[bytes]:
            self.tick += 1
            raise RuntimeError("private failure detail")

        before = self.snapshot.account.usage.prepare_ms
        result = self.acquire(runner=broken)
        self.assertEqual(("stopped", "context-error"), (result.state, result.reason))
        self.assertIsNone(result.value())
        self.assertAlmostEqual(before + 1000, self.snapshot.account.usage.prepare_ms)
        self.assertTrue(self.snapshot.account.lock.acquire(blocking=False))
        self.snapshot.account.lock.release()

        def invalid(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            result = self.runner(argv, **options)
            self.tick = float("nan")
            return result

        result = self.acquire(runner=invalid)
        self.assertEqual(("stopped", "budget"), (result.state, result.reason))
        self.assertIsNone(result.value())
        self.assertTrue(self.snapshot.account.lock.acquire(blocking=False))
        self.snapshot.account.lock.release()
        self.assertEqual(0, self.snapshot.account.limits.prepare_ms)

    def test_owner_output_bounds_and_job_expiry_withhold_false_success(self) -> None:
        def oversized(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            self.tick += 1
            options["stdout"].write(b"x" * (ci_read.OUTPUT_LIMIT_BYTES + 1))
            return subprocess.CompletedProcess(argv, 0)

        result = self.acquire(runner=oversized)
        record = result.value()
        assert record is not None
        self.assertEqual(("unavailable", "ci-read"), (result.state, result.reason))
        self.assertEqual(ci_read.ERROR_OUTPUT, record["error"])

        def expire(argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
            result = self.runner(argv, **options)
            self.job_left = self.tick
            return result

        result = self.acquire(runner=expire)
        self.assertEqual(("stopped", "job-time"), (result.state, result.reason))
        self.assertIsNone(result.value())

    def test_terminal_supervisor_errors_stop_instead_of_becoming_optional_ci_failure(self) -> None:
        for error_type in (supervise.ClosedError, supervise.UnstoppedError):
            with self.subTest(error=error_type.__name__):

                def terminal(
                    _argv: list[str], _error: type[Exception] = error_type, **_options: Any
                ) -> subprocess.CompletedProcess[bytes]:
                    self.tick += 1
                    raise _error("owned terminal state")

                result = self.acquire(runner=terminal)
                self.assertEqual("stopped", result.state)
                self.assertIsNone(result.value())
                self.assertEqual(1, result.ci_calls)
                self.assertEqual(0, result.spawned)

    def test_unknown_acquisition_time_never_launches_a_read(self) -> None:
        result = self.acquire(now=float("nan"))
        self.assertEqual(("stopped", "output"), (result.state, result.reason))
        self.assertEqual([], self.calls)
        self.assertIsNone(result.value())
