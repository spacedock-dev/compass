"""Registered shells share the ordinary slot and never turn identity into authority."""

from __future__ import annotations

import contextlib
import dataclasses
import importlib
import importlib.util
import unittest
from typing import Any
from unittest import mock

from compass_runtime import io as runtime_io
from compass_runtime import reading
from compass_runtime import reading_policy as policy

from . import test_reading_long_markers as marker_tests
from .test_reading_long_jobs import binding


class RegisteredShellTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = marker_tests.LongMarkerTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        self.permission = self.fixture.permission
        assert self.permission is not None
        self.prepared = policy.prepare_long_job(
            permission=self.permission, binding=binding(), call_timeout_ms=200, clock=lambda: 0.0
        )
        assert self.prepared is not None
        self.key = "claude:shell"
        self.addCleanup(reading.end_job, self.config, self.key)

    def module(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_control"))
        return importlib.import_module("compass_runtime.reading_long_control")

    def admit(self, **changes: Any) -> Any:
        options = {
            "provider": "claude",
            "label": "Claude Code",
            "job": self.prepared,
            "permission": self.permission,
            "now": 100,
            **changes,
        }
        return self.module().admit(self.config, self.key, **options)

    def ordinary(self) -> reading.Job | None:
        return reading.start_job(
            self.config, self.key, provider="claude", label="Claude Code", now=100
        )

    def registrations(self) -> int:
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='long_job_registrations'"
            ).fetchone()
            return (
                int(db.execute("SELECT count(*) FROM long_job_registrations").fetchone()[0])
                if exists
                else 0
            )

    def test_fresh_registration_has_one_ui_marker_and_cancel_identity_without_a_charge(
        self,
    ) -> None:
        active = self.admit()
        self.assertIsNotNone(active)
        assert self.prepared is not None
        self.assertEqual(self.prepared.job_id, active.job.id)
        self.assertEqual(active.job.id, active.owner.live.prepared.job_id)
        self.assertIs(active.job, reading.job(self.config, self.key))
        shown = reading.published_jobs(self.config)[self.key]
        self.assertEqual(active.job.id, shown["id"])
        stored = self.fixture.loaded(active.owner)
        self.assertEqual(active.job.id, stored["job_id"])
        self.assertEqual(active.owner.owner, stored["owner"])
        self.assertEqual(
            (True, None), reading.cancel_job(self.config, self.key, shown["id"], now=101)
        )
        self.assertEqual(1, self.registrations())
        self.assertEqual(0, self.fixture.spends())
        self.assertEqual([], stored["passes"])

    def test_ordinary_and_unasked_contention_never_register_or_replace_a_job(self) -> None:
        ordinary = self.ordinary()
        self.assertIsNone(self.admit())
        self.assertIs(ordinary, reading.job(self.config, self.key))
        self.assertEqual(0, self.registrations())
        reading.end_job(self.config, self.key)
        self.assertTrue(reading.claim(self.config, self.key))
        self.assertIsNone(self.admit())
        self.assertFalse(reading.claim(self.config, self.key))
        self.assertEqual({}, reading.published_jobs(self.config))
        self.assertEqual(0, self.registrations())

    def test_revoked_permission_frees_admission_slot_without_registration(self) -> None:
        policy.set_consent(self.config, False, now=100)
        policy.resume(self.config, now=100)
        self.assertIsNone(self.admit())
        self.assertEqual(0, self.registrations())
        self.assertIsNone(reading.job(self.config, self.key))
        self.assertIsNotNone(self.ordinary())

    def test_replay_frees_slot_and_does_not_mutate_original_marker(self) -> None:
        active = self.admit()
        before = self.fixture.path(active.owner).read_bytes()
        reading.end_job(self.config, self.key)
        self.assertIsNone(self.admit())
        self.assertEqual(before, self.fixture.path(active.owner).read_bytes())
        self.assertEqual(1, self.registrations())
        self.assertIsNotNone(self.ordinary())

    def test_failed_marker_write_releases_slot_but_registration_cannot_be_replayed(self) -> None:
        with mock.patch.object(self.fixture.module(), "_write", side_effect=OSError):
            self.assertIsNone(self.admit())
        self.assertEqual(1, self.registrations())
        self.assertIsNone(reading.job(self.config, self.key))
        self.assertIsNone(self.admit())
        self.assertIsNotNone(self.ordinary())
        self.assertEqual(0, self.fixture.spends())

    def test_provider_header_and_permission_mismatches_never_take_slot(self) -> None:
        assert self.permission is not None
        for changes in (
            {"provider": "codex"},
            {"job": None},
            {"permission": None},
            {"permission": dataclasses.replace(self.permission, epoch=self.permission.epoch + 1)},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(self.admit(**changes))
                self.assertIsNone(reading.job(self.config, self.key))
                self.assertTrue(reading.claim(self.config, self.key))
                reading.release(self.config, self.key)
        self.assertEqual(0, self.registrations())

    def test_failed_setup_cleans_own_slot_but_never_a_replacement(self) -> None:
        with (
            mock.patch.object(self.fixture.module(), "begin", side_effect=RuntimeError("setup")),
            self.assertRaises(RuntimeError),
        ):
            self.admit()
        self.assertIsNone(reading.job(self.config, self.key))
        replacement: list[reading.Job | None] = []

        def replaced(*_args: Any, **_kwargs: Any) -> None:
            reading.end_job(self.config, self.key)
            replacement.append(self.ordinary())

        with mock.patch.object(self.fixture.module(), "begin", side_effect=replaced):
            self.assertIsNone(self.admit())
        self.assertIs(replacement[0], reading.job(self.config, self.key))
        self.assertFalse(reading.claim(self.config, self.key))

    def test_publishing_reads_do_not_register_recapture_or_mutate_marker(self) -> None:
        active = self.admit()
        before = self.fixture.path(active.owner).read_bytes()
        with (
            mock.patch.object(policy, "register_long_job", side_effect=AssertionError),
            mock.patch.object(policy, "capture_long_permission", side_effect=AssertionError),
            mock.patch.object(self.fixture.module(), "begin", side_effect=AssertionError),
        ):
            for _ in range(3):
                self.assertIs(active.job, reading.job(self.config, self.key))
                self.assertEqual(active.job.id, reading.published_jobs(self.config)[self.key]["id"])
        self.assertEqual(before, self.fixture.path(active.owner).read_bytes())
        self.assertEqual(1, self.registrations())
