"""Late long-pass refusals preserve committed accounting without adapter entry."""

from __future__ import annotations

import inspect
import threading
import unittest
from typing import Any

from compass_runtime import reading_policy as policy
from compass_runtime import supervise

from . import test_reading_long_guard as guard_tests


class LongBeforeInvokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = guard_tests.LongGuardTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def guard(self, **options: Any) -> Any:
        self.assertIn("before_invoke", inspect.signature(policy.GuardedModel).parameters)
        return self.fixture.guard(**options)

    def assert_charged_without_entry(self, guard: Any, outcome: str) -> None:
        self.assertTrue(guard.reserved)
        self.assertEqual([True], self.fixture.reservations)
        self.assertEqual(1, self.fixture.fixture.spends())
        self.assertEqual([], self.fixture.calls)
        value = self.fixture.last
        self.assertTrue(value["capacity"]["allowed"])
        self.assertTrue(value["input"]["attempt_reserved"])
        self.assertFalse(value["input"]["model_invoked"])
        self.assertEqual(outcome, value["input"]["outcome"])

    def test_on_reserved_cancellation_prevents_adapter_entry(self) -> None:
        cancelled = threading.Event()

        def reserved() -> None:
            self.fixture.reservations.append(True)
            cancelled.set()

        guard = self.fixture.guard(on_reserved=reserved, cancelled=cancelled.is_set)
        self.fixture.captured(guard)
        self.assert_charged_without_entry(guard, "cancelled")

    def test_on_reserved_shutdown_prevents_adapter_entry(self) -> None:
        def reserved() -> None:
            self.fixture.reservations.append(True)
            supervise._SHUTDOWN.set()

        guard = self.fixture.guard(on_reserved=reserved)
        self.fixture.captured(guard)
        self.assert_charged_without_entry(guard, "closed")

    def test_on_reserved_destination_change_prevents_adapter_entry(self) -> None:
        destination = [""]

        def reserved() -> None:
            self.fixture.reservations.append(True)
            destination[0] = "moved"

        guard = self.fixture.guard(on_reserved=reserved, resolve_destination=lambda: destination[0])
        with self.assertRaises(policy.RefusedError) as refused:
            self.fixture.captured(guard)
        self.assertEqual(policy.DESTINATION_MOVED, refused.exception.answer["reason"])
        self.assert_charged_without_entry(guard, "refused")

    def test_callback_context_refusal_retains_charge(self) -> None:
        calls: list[bool] = []

        def current_context() -> str:
            calls.append(True)
            self.assertEqual([True], self.fixture.reservations)
            self.assertEqual([], self.fixture.calls)
            return "intent-changed"

        guard = self.guard(before_invoke=current_context)
        with self.assertRaises(policy.RefusedError) as refused:
            self.fixture.captured(guard)
        self.assertEqual("intent-changed", refused.exception.answer["reason"])
        self.assertEqual([True], calls)
        self.assert_charged_without_entry(guard, "refused")

    def test_callback_can_raise_permission_refusal(self) -> None:
        def permission_changed() -> None:
            policy.set_consent(self.fixture.config, False, now=100)
            raise policy.RefusedError(policy._answer(reason="permission-changed"))

        guard = self.guard(before_invoke=permission_changed)
        with self.assertRaises(policy.RefusedError):
            self.fixture.captured(guard)
        self.assert_charged_without_entry(guard, "refused")

    def test_cancellation_during_callback_is_rechecked(self) -> None:
        cancelled = threading.Event()
        guard = self.guard(before_invoke=cancelled.set, cancelled=cancelled.is_set)
        self.fixture.captured(guard)
        self.assert_charged_without_entry(guard, "cancelled")

    def test_destination_change_during_callback_is_rechecked(self) -> None:
        destination = [""]

        def moved() -> None:
            destination[0] = "moved"

        guard = self.guard(before_invoke=moved, resolve_destination=lambda: destination[0])
        with self.assertRaises(policy.RefusedError):
            self.fixture.captured(guard)
        self.assert_charged_without_entry(guard, "refused")

    def test_callback_exception_is_charged_error_without_adapter(self) -> None:
        def failed() -> None:
            raise OSError("private error canary")

        guard = self.guard(before_invoke=failed)
        with self.assertRaises(OSError):
            self.fixture.captured(guard)
        self.assert_charged_without_entry(guard, "error")
        self.assertNotIn("private error canary", str(self.fixture.last))

    def test_callback_return_must_be_a_closed_refusal_or_none(self) -> None:
        guard = self.guard(before_invoke=lambda: "private arbitrary reason")
        with self.assertRaises(ValueError):
            self.fixture.captured(guard)
        self.assert_charged_without_entry(guard, "error")
        self.assertNotIn("private arbitrary reason", str(self.fixture.last))

    def test_success_preserves_actual_prompt_and_cap_after_one_callback(self) -> None:
        seen: list[bool] = []

        def current() -> None:
            seen.append(True)
            self.assertEqual([True], self.fixture.reservations)
            self.assertEqual([], self.fixture.calls)

        guard = self.guard(before_invoke=current)
        value = self.fixture.captured(guard)
        self.assertEqual([True], seen)
        self.assertEqual([("界🙂", 10)], self.fixture.calls)
        self.assertEqual(self.fixture.calls, self.fixture.received)
        self.assertTrue(value["input"]["model_invoked"])
        self.assertEqual(1, self.fixture.fixture.spends())

    def test_callback_requires_prompt_reservation_at_construction(self) -> None:
        for options in ({}, {"unasked": True}, {"reserve_with": policy.reserve_monitor}):
            with self.subTest(options=options):
                self.assertIn("before_invoke", inspect.signature(policy.GuardedModel).parameters)
                with self.assertRaises(ValueError):
                    policy.GuardedModel(
                        self.fixture.config,
                        self.fixture.model,
                        lambda: 100,
                        before_invoke=lambda: None,
                        **options,
                    )
        self.assertEqual(0, self.fixture.fixture.spends())
