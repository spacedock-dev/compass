"""A prepared long identity uses the ordinary slot without granting execution authority."""

from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import reading

from .support import make_runtime


class PreparedJobIdentityTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, _ = make_runtime(state_dir=Path(home.name), state_home=home.name)
        self.key = "claude:slot-id"
        self.addCleanup(reading.end_job, self.config, self.key)

    def start(self, **kwargs: Any) -> reading.Job | None:
        return reading.start_job(
            self.config, self.key, provider="claude", label="Claude Code", now=100, **kwargs
        )

    def explicit(self, identity: Any = "a" * 32) -> reading.Job | None:
        self.assertIn("prepared_job_id", inspect.signature(reading.start_job).parameters)
        return self.start(prepared_job_id=identity)

    def test_identity_is_stable_through_publication_cancel_handover_seal_and_end(self) -> None:
        job = self.explicit()
        assert job is not None
        self.assertEqual("a" * 32, job.id)
        self.assertIs(job, reading.job(self.config, self.key))
        first = reading.published_jobs(self.config)[self.key]
        self.assertEqual(job.id, first["id"])
        self.assertEqual(
            (False, None), reading.cancel_job(self.config, self.key, "b" * 32, now=101)
        )
        self.assertFalse(reading.job_cancelled(job))
        self.assertEqual(
            (True, None), reading.cancel_job(self.config, self.key, first["id"], now=102)
        )
        group = object()
        self.assertTrue(reading.hand_over(job, group))
        self.assertEqual((True, group), reading.cancel_job(self.config, self.key, job.id, now=103))
        self.assertTrue(reading.seal_job(job))
        self.assertEqual((False, None), reading.cancel_job(self.config, self.key, job.id, now=104))
        self.assertEqual(first["id"], reading.published_jobs(self.config)[self.key]["id"])
        reading.end_job(self.config, self.key)
        self.assertIsNone(reading.job(self.config, self.key))
        self.assertEqual({}, reading.published_jobs(self.config))
        self.assertTrue(reading.claim(self.config, self.key))

    def test_explicit_and_default_jobs_contend_for_the_same_slot(self) -> None:
        explicit = self.explicit()
        self.assertIsNotNone(explicit)
        self.assertIsNone(self.start())
        self.assertIsNone(self.explicit("b" * 32))
        self.assertFalse(reading.claim(self.config, self.key))
        reading.end_job(self.config, self.key)
        ordinary = self.start()
        assert ordinary is not None
        self.assertRegex(ordinary.id, r"^[0-9a-f]{16}$")
        self.assertIsNone(self.explicit())
        self.assertEqual(
            (False, None), reading.cancel_job(self.config, self.key, "a" * 32, now=101)
        )
        self.assertFalse(reading.job_cancelled(ordinary))

    def test_unasked_claim_prevents_explicit_job_without_inventing_one(self) -> None:
        self.assertTrue(reading.claim(self.config, self.key))
        self.assertIsNone(self.explicit())
        self.assertIsNone(reading.job(self.config, self.key))
        self.assertEqual({}, reading.published_jobs(self.config))
        reading.release(self.config, self.key)
        self.assertIsNotNone(self.explicit())

    def test_invalid_identity_never_consumes_or_replaces_the_slot(self) -> None:
        value: Any
        for value in (
            "",
            "a" * 16,
            "a" * 31,
            "a" * 33,
            "A" * 32,
            "g" * 32,
            "a" * 32 + "\n",
            True,
            32,
            [],
            {},
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.explicit(value)
                self.assertIsNone(reading.job(self.config, self.key))
                self.assertTrue(reading.claim(self.config, self.key))
                with self.assertRaises(ValueError):
                    self.explicit(value)
                self.assertFalse(reading.claim(self.config, self.key))
                reading.release(self.config, self.key)

    def test_identity_registry_grants_no_durable_authority_and_is_not_a_replay_ledger(self) -> None:
        before = list(self.config.state_dir.iterdir())
        first = self.explicit()
        reading.end_job(self.config, self.key)
        second = self.explicit()
        assert first is not None and second is not None
        self.assertIsNot(first, second)
        self.assertEqual(first.id, second.id)
        self.assertEqual(before, list(self.config.state_dir.iterdir()))
        self.assertIsNone(second.group)
        self.assertEqual(reading.PHASE_PREPARING, second.phase)
