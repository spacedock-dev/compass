"""Optional immutable routing identifiers do not grant recovery or publication authority."""

from __future__ import annotations

import contextlib
import copy
import dataclasses
import json
import unittest
from typing import Any

from compass_runtime import io as runtime_io
from compass_runtime import (
    reading,
    reading_long_control,
    reading_long_inspection,
    reading_long_jobs,
)
from compass_runtime import reading_policy as policy

from . import test_reading_long_control as control_tests
from .test_reading_long_jobs import binding


def association(**changes: Any) -> dict[str, Any]:
    return {
        "harness": "claude",
        "sid": "abc123ab",
        "incarnation": "e" * 32,
        "revision": 1,
        **changes,
    }


class PublicationIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = control_tests.RegisteredShellTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.config
        assert self.fixture.permission is not None
        self.permission = self.fixture.permission

    def prepare(self, value: Any, **changes: Any) -> Any:
        supplied = binding(
            publication=value, target_sha256=reading_long_jobs.digest(value), **changes
        )
        return policy.prepare_long_job(
            permission=self.permission, binding=supplied, call_timeout_ms=200, clock=lambda: 0.0
        )

    def valid(self) -> Any:
        job = self.prepare(association())
        self.assertIsNotNone(job, "A closed publication association must bind a prepared job")
        return job

    def admit(self, job: Any, key: str = "claude:abc123ab", provider: str = "claude") -> Any:
        self.addCleanup(reading.end_job, self.config, key)
        return reading_long_control.admit(
            self.config,
            key,
            provider=provider,
            label="Claude Code",
            job=job,
            permission=self.permission,
            now=100,
        )

    def test_association_roundtrips_with_independent_copies_and_no_user_words(self) -> None:
        supplied = association()
        job = self.prepare(supplied)
        self.assertIsNotNone(job)
        supplied["revision"] = 2
        header = reading_long_jobs.header(job)
        assert header is not None
        self.assertEqual(association(), header["publication"])
        self.assertEqual(reading_long_jobs.digest(association()), header["target_sha256"])
        header["publication"]["sid"] = "ffffffff"
        again = reading_long_jobs.header(job)
        assert again is not None
        self.assertEqual("abc123ab", again["publication"]["sid"])

    def test_canonical_publication_digest_validates_before_binding(self) -> None:
        helper: Any = getattr(reading_long_jobs, "publication_digest", None)
        self.assertTrue(callable(helper))
        self.assertEqual(reading_long_jobs.digest(association()), helper(association()))
        self.assertIsNone(helper({**association(), "revision": True}))
        self.assertIsNone(helper(None))

    def test_every_association_field_participates_in_the_immutable_job_id(self) -> None:
        job = self.valid()
        original = json.loads(job.binding)
        for key, value in (
            ("harness", "codex"),
            ("sid", "ffffffff"),
            ("incarnation", "f" * 32),
            ("revision", 2),
        ):
            with self.subTest(key=key):
                changed = copy.deepcopy(original)
                changed["publication"][key] = value
                changed["target_sha256"] = reading_long_jobs.digest(changed["publication"])
                self.assertIsNone(reading_long_jobs.validate_header(changed, job.job_id))
        removed = copy.deepcopy(original)
        removed.pop("publication")
        self.assertIsNone(reading_long_jobs.validate_header(removed, job.job_id))
        wrong_target = copy.deepcopy(original)
        wrong_target["target_sha256"] = "a" * 64
        self.assertIsNone(
            reading_long_jobs.validate_header(
                wrong_target, reading_long_jobs.digest(wrong_target)[:32]
            )
        )

    def test_malformed_nonnull_associations_are_rejected_without_sanitizing(self) -> None:
        self.valid()
        values: list[Any] = [
            True,
            [],
            "private words",
            {},
            {**association(), "prompt": "PROMPT_CANARY"},
        ]
        for key, wrong in (
            ("harness", "unknown"),
            ("harness", []),
            ("sid", True),
            ("sid", ""),
            ("sid", "a" * 65),
            ("sid", "abc123ab-more"),
            ("sid", "abc123ab\n"),
            ("sid", "/private/path"),
            ("sid", "private words"),
            ("incarnation", "E" * 32),
            ("incarnation", "e" * 31),
            ("incarnation", False),
            ("revision", True),
            ("revision", 0),
            ("revision", 2**53),
            ("revision", 1.0),
        ):
            values.append({**association(), key: wrong})
        for value in values:
            with self.subTest(value=value):
                self.assertIsNone(self.prepare(value))

    def test_admission_rejects_foreign_session_or_provider_before_registration(self) -> None:
        job = self.valid()
        for key, provider in (
            ("claude:ffffffff", "claude"),
            ("codex:abc123ab", "claude"),
            ("claude:abc123ab", "codex"),
        ):
            with self.subTest(key=key, provider=provider):
                self.assertIsNone(self.admit(job, key, provider))
                self.assertIsNone(reading.job(self.config, key))
                self.assertTrue(reading.claim(self.config, key))
                reading.release(self.config, key)
        self.assertEqual(0, self.fixture.registrations())
        self.assertIsNotNone(self.admit(job))

    def test_attributed_marker_and_real_receipts_keep_closed_metadata(self) -> None:
        active = self.admit(self.valid())
        marker_fixture = self.fixture.fixture
        self.assertTrue(marker_fixture.reserve(active.owner).launch)
        marker = marker_fixture.loaded(active.owner)
        self.assertEqual(association(), marker["header"]["publication"])
        totals = reading_long_inspection.inspect(self.config, active.job.id, now=100)
        self.assertIsNotNone(totals.exact)
        assert totals.exact is not None
        self.assertEqual(1, totals.exact.calls)
        assert runtime_io.sqlite_module is not None
        with contextlib.closing(
            runtime_io.sqlite_module.connect(policy.store_path(self.config))
        ) as db:
            registered = json.loads(
                db.execute("SELECT binding FROM long_job_registrations").fetchone()[0]
            )
            receipt = json.loads(
                db.execute("SELECT binding FROM long_pass_reservations").fetchone()[0]
            )
        self.assertEqual(association(), registered["publication"])
        self.assertNotIn("publication", receipt)
        self.assertEqual(active.job.id, receipt["job_id"])
        for word in ("PROMPT_CANARY", "REPLY_CANARY", "/private/path", "private words"):
            self.assertNotIn(word, json.dumps([marker, registered, receipt]))

    def test_missing_and_null_association_remain_unattributed_with_working_accounting(self) -> None:
        self.valid()
        for job in (self.fixture.prepared, self.prepare(None)):
            with self.subTest(job=job):
                self.assertIsNotNone(job)
                header = reading_long_jobs.header(job)
                assert header is not None
                self.assertIsNone(header.get("publication"))
                active = self.admit(job, self.fixture.key)
                self.assertIsNotNone(active)
                self.assertTrue(self.fixture.fixture.reserve(active.owner).launch)
                totals = reading_long_inspection.inspect(self.config, active.job.id, now=100)
                self.assertIsNotNone(totals.exact)
                assert totals.exact is not None
                self.assertEqual(1, totals.exact.calls)
                reading.end_job(self.config, self.fixture.key)

    def test_foreign_association_cannot_replace_header_under_the_original_id(self) -> None:
        job = self.valid()
        active = self.admit(job)
        before = self.fixture.fixture.path(active.owner).read_bytes()
        reading.end_job(self.config, "claude:abc123ab")
        header = json.loads(job.binding)
        header["publication"]["incarnation"] = "f" * 32
        header["target_sha256"] = reading_long_jobs.digest(header["publication"])
        foreign = dataclasses.replace(job, binding=reading_long_jobs.canonical(header))
        self.assertIsNone(self.admit(foreign))
        self.assertEqual(before, self.fixture.fixture.path(active.owner).read_bytes())
