"""Long outcome identity and late publication guards are closed and target-bound."""

from __future__ import annotations

import concurrent.futures
import contextlib
import copy
import inspect
import json
import threading
import unittest
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import reading_long_diagnostics as diagnostics
from compass_runtime import reading_pass_context

from . import test_annotations_long_diagnostics as storage_tests
from . import test_reading_long_finalize as finalize_tests
from . import test_reading_pass_context as context_tests
from .test_reading_pass_types import plan


class PublicationBindingTest(unittest.TestCase):
    def binding(self) -> Any:
        helper: Any = getattr(diagnostics, "bind_context", None)
        self.assertTrue(callable(helper), "long metrics need frozen intent/window identity")
        metadata: Any = context_tests.metadata
        frozen = reading_pass_context.freeze(context_tests.GOAL, context_tests.LINES, metadata())
        return helper(frozen, started_at=201)

    def test_closed_binding_preserves_exact_revision_window_and_old_unknown(self) -> None:
        binding = self.binding()
        self.assertEqual(
            {
                "revision": 7,
                "revision_at": 100,
                "window_start": 70,
                "window_end": 200,
                "scope": "final",
                "end_kind": "session-end",
                "open_call_at": None,
                "job_started_at": 201,
            },
            binding,
        )
        value = diagnostics.derive(plan=plan(), outcome="completed", binding=binding)
        self.assertIsNone(value["complete"])
        self.assertEqual(binding, value["binding"])
        checked = diagnostics.validate(value)
        assert checked is not None
        checked["binding"]["revision"] = 999
        self.assertEqual(7, value["binding"]["revision"])
        self.assertNotIn(context_tests.GOAL, json.dumps(value))
        legacy = diagnostics.derive(plan=plan())
        checked_legacy = diagnostics.validate(legacy)
        assert checked_legacy is not None
        self.assertNotIn("binding", checked_legacy)

    def test_binding_rejects_bool_nan_extra_words_and_unbound_completed_outcome(self) -> None:
        value = diagnostics.derive(plan=plan(), outcome="completed", binding=self.binding())
        for key, bad in (
            ("revision", True),
            ("revision_at", float("nan")),
            ("window_start", -1),
            ("scope", "PRIVATE"),
            ("job_started_at", 2**53),
            ("path", "/PRIVATE"),
        ):
            wrong = copy.deepcopy(value)
            wrong["binding"][key] = bad
            self.assertIsNone(diagnostics.validate(wrong))
        binding: Any
        for binding in (None, {}, "PRIVATE"):
            self.assertIsNone(diagnostics.validate({**value, "binding": binding}))

    def test_new_completed_outcome_cannot_enter_the_measured_withheld_path(self) -> None:
        fixture = finalize_tests.WithheldFinalizationTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.seal()
        storage = storage_tests.MeasuredWithheldFinalizationTest()
        storage.fixture = fixture
        value = storage.diagnostic()
        value.update(outcome="completed", complete=None, binding=self.binding())
        self.assertIsNotNone(diagnostics.validate(value))
        self.assertFalse(storage.finalize(value).acknowledged)
        self.assertTrue(fixture.path.exists())


class LockedPublicationGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = storage_tests.LongDiagnosticStorageTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def publish(self, guard: Any) -> str:
        self.assertIn("long_publish_guard", inspect.signature(store.record_withheld).parameters)
        return self.fixture.publish(storage_tests.measured(1), long_publish_guard=guard)

    def test_guard_sees_an_independent_locked_annotation_before_write_and_replay(self) -> None:
        seen: list[int] = []

        def guard(entry: store.Annotation) -> bool:
            seen.append(entry["revisions"][-1]["n"])
            entry["revisions"][-1]["goal"] = "PRIVATE MUTATION"
            return True

        self.assertEqual(store.OUTCOME_STORED, self.publish(guard))
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish(guard))
        self.assertEqual([1, 1], seen)
        self.assertEqual("Ship the cockpit", self.fixture.entry()["revisions"][-1]["goal"])
        before = self.fixture.fixture.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_REFUSED, self.publish(lambda _entry: False))
        self.assertEqual(before, self.fixture.fixture.fixture.path.read_bytes())

    def test_false_unknown_nonboolean_and_exception_refuse_without_acknowledgment(self) -> None:
        def failure(_entry: store.Annotation) -> bool:
            raise OSError("PRIVATE")

        for guard in (
            lambda _entry: False,
            lambda _entry: None,
            lambda _entry: 1,
            failure,
            "PRIVATE",
        ):
            before = self.fixture.fixture.fixture.path.read_bytes()
            self.assertEqual(store.OUTCOME_REFUSED, self.publish(guard))
            self.assertEqual(before, self.fixture.fixture.fixture.path.read_bytes())
        self.assertNotIn("long_receipts", self.fixture.entry())
        self.assertNotIn("readings", self.fixture.entry())

    def test_eligibility_change_while_waiting_for_real_annotation_lock_is_observed(self) -> None:
        entered = threading.Event()
        eligible = [True]
        observed: list[bool] = []
        original = store._store_locks

        @contextlib.contextmanager
        def waiting(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            with original(*args, **kwargs) as held:
                yield held

        def guard(_entry: store.Annotation) -> bool:
            observed.append(eligible[0])
            return eligible[0]

        before = self.fixture.fixture.fixture.path.read_bytes()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with (
                original(self.fixture.config, self.fixture.state, wait=2, make_home=False),
                mock.patch.object(store, "_store_locks", waiting),
            ):
                future = pool.submit(self.publish, guard)
                self.assertTrue(entered.wait(2))
                self.assertEqual([], observed)
                self.assertFalse(future.done())
                eligible[0] = False
            self.assertEqual(store.OUTCOME_REFUSED, future.result(timeout=5))
        self.assertEqual([False], observed)
        self.assertEqual(before, self.fixture.fixture.fixture.path.read_bytes())
