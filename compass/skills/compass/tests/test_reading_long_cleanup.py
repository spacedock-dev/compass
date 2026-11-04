"""Receipt release requires confirmed marker absence under its publication barrier."""

from __future__ import annotations

import contextlib
import copy
import importlib
import importlib.util
import json
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import (
    reading,
    reading_long_inspection,
    reading_long_jobs,
    reading_long_markers,
)
from compass_runtime import reading_policy as policy

from . import test_annotations_long_target as target_tests
from .test_reading_long_jobs import binding


class LongReceiptCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = target_tests.LongTargetTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state
        self.sid = "abc123ab"
        store.annotate(
            self.config, self.state, "claude", self.sid, goal="Retain these words", now=100
        )
        target = store.capture_long_target(self.config, self.state, "claude", self.sid)
        assert target is not None
        self.target = target
        publication = {
            "harness": "claude",
            "sid": self.sid,
            "incarnation": target.incarnation,
            "revision": target.revision,
        }
        permission = policy.capture_long_permission(self.config, now=100)
        assert permission is not None
        job = policy.prepare_long_job(
            permission=permission,
            binding=binding(
                publication=publication,
                target_sha256=reading_long_jobs.publication_digest(publication),
            ),
            call_timeout_ms=200,
            clock=lambda: 0.0,
        )
        assert job is not None
        self.job_id = job.job_id
        self.header = reading_long_jobs.header(job)
        owner = reading_long_markers.begin(self.config, permission=permission, job=job, now=100)
        assert owner is not None
        self.owner = owner
        self.path = reading_long_markers.marker_path(self.config, self.job_id)
        self.assertEqual(
            store.OUTCOME_STORED,
            store.record_withheld(
                self.config,
                self.state,
                "claude",
                self.sid,
                reason=reading.WITHHELD_MODEL_FAILED,
                spent=False,
                job_id=self.job_id,
                long_target=target,
                long_publication=True,
            ),
        )

    def entry(self) -> Any:
        return store.find(store.load(self.config), "claude", self.sid)

    def module(self) -> Any:
        self.assertIsNotNone(importlib.util.find_spec("compass_runtime.reading_long_cleanup"))
        return importlib.import_module("compass_runtime.reading_long_cleanup")

    def release(self, **changes: Any) -> str:
        return str(
            self.module().release_receipt(
                self.config, self.state, **{"job_id": self.job_id, "header": self.header, **changes}
            )
        )

    def retire(self) -> None:
        self.assertTrue(
            reading_long_markers.seal(self.config, self.owner, state="cancelled", now=100)
        )
        inspected = reading_long_inspection.inspect(self.config, self.job_id, now=100)
        self.assertIsNotNone(inspected.exact)
        self.assertTrue(
            reading_long_inspection.retire(self.config, inspected, acknowledged=True, now=100)
        )

    def test_present_marker_refuses_then_real_acknowledged_retirement_allows_one_release(
        self,
    ) -> None:
        self.assertEqual(
            store.OUTCOME_STORED,
            store.record_withheld(
                self.config,
                self.state,
                "claude",
                self.sid,
                reason=reading.WITHHELD_MODEL_FAILED,
                spent=False,
                job_id="b" * 32,
                long_target=self.target,
                long_publication=True,
            ),
        )
        before = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_REFUSED, self.release())
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.retire()
        public = store.published(self.entry())
        written = self.entry()["written"]
        self.assertEqual(store.OUTCOME_STORED, self.release())
        self.assertEqual(["b" * 32], self.entry()["long_receipts"])
        self.assertEqual(public, store.published(self.entry()))
        self.assertEqual(written, self.entry()["written"])
        after = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_UNCHANGED, self.release())
        self.assertEqual(after, self.fixture.path.read_bytes())

    def test_revision_may_advance_but_old_or_recreated_incarnation_cannot_release(self) -> None:
        self.retire()
        store.annotate(self.config, self.state, "claude", self.sid, goal="New intent", now=101)
        public = store.published(self.entry())
        self.assertEqual(store.OUTCOME_STORED, self.release())
        self.assertEqual(public, store.published(self.entry()))
        store.clear(self.config, self.state, "claude", self.sid)
        self.assertEqual(store.OUTCOME_REFUSED, self.release())
        store.annotate(self.config, self.state, "claude", self.sid, goal="Recreated", now=101)
        fresh = store.capture_long_target(self.config, self.state, "claude", self.sid)
        assert fresh is not None
        self.assertNotEqual(self.target.incarnation, fresh.incarnation)
        before = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_REFUSED, self.release())
        self.assertEqual(before, self.fixture.path.read_bytes())

    def test_unknown_malformed_and_foreign_headers_never_release(self) -> None:
        self.retire()
        assert self.header is not None
        changed = copy.deepcopy(self.header)
        changed["publication"]["incarnation"] = "f" * 32
        absent = copy.deepcopy(self.header)
        absent.pop("publication")
        null = {**self.header, "publication": None}
        for header in (None, {}, changed, absent, null):
            with self.subTest(header=header):
                before = self.fixture.path.read_bytes()
                self.assertEqual(store.OUTCOME_REFUSED, self.release(header=header))
                self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertEqual(store.OUTCOME_REFUSED, self.release(job_id="b" * 32))

    def test_malformed_unreadable_and_symlink_markers_never_prove_absence(self) -> None:
        self.path.write_text("not a marker")
        self.assertEqual(store.OUTCOME_REFUSED, self.release())
        original = Path.lstat

        def denied(path: Path, *args: Any, **kwargs: Any) -> Any:
            if path == self.path:
                raise PermissionError("synthetic unreadable marker")
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "lstat", denied):
            self.assertEqual(store.OUTCOME_REFUSED, self.release())
        self.path.unlink()
        self.path.symlink_to(self.config.state_dir / "missing-marker-target")
        self.assertEqual(store.OUTCOME_REFUSED, self.release())
        self.assertEqual([self.job_id], self.entry()["long_receipts"])

    def test_malformed_receipt_state_is_not_reset_by_cleanup(self) -> None:
        self.retire()
        raw = json.loads(self.fixture.path.read_text())
        next(entry for entry in raw["entries"] if entry["sid"] == self.sid)["long_receipts"] = [
            "bad"
        ]
        self.fixture.path.write_text(json.dumps(raw))
        before = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_REFUSED, self.release())
        self.assertEqual(before, self.fixture.path.read_bytes())

    def test_waiting_cleanup_rechecks_marker_after_real_publication_lock(self) -> None:
        marker = reading_long_markers.load(self.config, self.job_id)
        assert marker is not None
        self.retire()
        entered = threading.Event()
        original = reading_long_markers.publication_lock

        @contextlib.contextmanager
        def entering(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            with original(*args, **kwargs) as root:
                yield root

        answers: list[str] = []
        worker = threading.Thread(target=lambda: answers.append(self.release()))
        self.module()
        with (
            original(self.config),
            mock.patch.object(reading_long_markers, "publication_lock", entering),
        ):
            worker.start()
            self.assertTrue(entered.wait(5))
            reading_long_markers._write(self.path, marker)
        worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual([store.OUTCOME_REFUSED], answers)
        self.assertEqual([self.job_id], self.entry()["long_receipts"])
