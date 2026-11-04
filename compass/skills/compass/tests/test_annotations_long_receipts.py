"""Unretired long publication receipts outlive the ordinary recent-job history."""

from __future__ import annotations

import contextlib
import inspect
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import reading

from . import test_annotations_long_target as target_tests


class LongPublicationReceiptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = target_tests.LongTargetTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config, self.state = self.fixture.config, self.fixture.state
        self.token = self.fixture.capture()
        self.job_id = "a" * 32

    def publish(self, *, kind: str = "withheld", spent: bool = True, **changes: Any) -> str:
        function = store.record_reading if kind == "reading" else store.record_withheld
        self.assertIn("long_publication", inspect.signature(function).parameters)
        options = {
            "job_id": self.job_id,
            "long_target": self.token,
            "long_publication": True,
            **changes,
        }
        if kind == "reading":
            options["assessment"] = self.fixture.assessment()
        else:
            options.update(reason=reading.WITHHELD_MODEL_FAILED, spent=spent)
        return function(self.config, self.state, "claude", "s1", **options)

    def raw_receipts(self, value: Any) -> None:
        raw = json.loads(self.fixture.path.read_text())
        raw["entries"][0]["long_receipts"] = value
        self.fixture.path.write_text(json.dumps(raw))

    def test_replay_after_thirty_three_ordinary_jobs_keeps_one_long_job_count(self) -> None:
        self.assertEqual(store.OUTCOME_STORED, self.publish(kind="reading"))
        initial = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish(kind="reading"))
        self.assertEqual(initial, self.fixture.path.read_bytes())
        for index in range(33):
            self.assertEqual(
                store.OUTCOME_STORED,
                store.record_withheld(
                    self.config,
                    self.state,
                    "claude",
                    "s1",
                    reason=reading.WITHHELD_MODEL_FAILED,
                    spent=True,
                    job_id=f"{index:016x}",
                ),
            )
        entry = self.fixture.entry()
        self.assertNotIn(self.job_id, entry["jobs"])
        self.assertEqual([self.job_id], entry["long_receipts"])
        before = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish(kind="reading"))
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertEqual(34, self.fixture.entry()["readings"])

    def test_zero_spent_receipt_is_durable_and_replay_never_changes_the_count(self) -> None:
        self.assertEqual(store.OUTCOME_STORED, self.publish(spent=False))
        self.assertNotIn("readings", self.fixture.entry())
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish(spent=True))
        self.assertNotIn("readings", self.fixture.entry())
        self.assertEqual(store.OUTCOME_STORED, self.publish(job_id="b" * 32))
        self.assertEqual(1, self.fixture.entry()["readings"])
        self.assertEqual([self.job_id, "b" * 32], self.fixture.entry()["long_receipts"])

    def test_receipts_survive_ordinary_edits_settlement_and_remain_private(self) -> None:
        self.assertEqual(store.OUTCOME_STORED, self.publish())
        self.fixture.seed("A revised goal")
        self.assertEqual(
            store.OUTCOME_STORED,
            store.settle(self.config, self.state, "claude", "s1", through=150, now=200),
        )
        entry = self.fixture.entry()
        self.assertEqual([self.job_id], entry["long_receipts"])
        public = store.published(entry)
        self.assertNotIn("long_receipts", public)
        self.assertNotIn(self.job_id, json.dumps(public))
        self.assertEqual(1, public["reading_count"])
        self.assertEqual(store.OUTCOME_REFUSED, self.publish())

    def test_full_receipts_refuse_new_publication_without_evicting_existing_receipts(self) -> None:
        # A bounded predecessor fixture parsed by the real store, then real boundary writes.
        old = [f"{index:032x}" for index in range(127)]
        self.raw_receipts(old)
        self.assertEqual(store.OUTCOME_STORED, self.publish())
        self.assertEqual([*old, self.job_id], self.fixture.entry()["long_receipts"])
        before = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_REFUSED, self.publish(job_id="b" * 32))
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish())
        self.assertEqual(1, self.fixture.entry()["readings"])

    def test_malformed_receipts_fail_closed_and_ordinary_writes_preserve_invalid_state(
        self,
    ) -> None:
        self.assertIn("long_publication", inspect.signature(store.record_withheld).parameters)
        invalid: Any
        for invalid in (
            None,
            False,
            "PRIVATE_CANARY",
            {},
            ["bad"],
            [self.job_id, self.job_id],
            [f"{n:032x}" for n in range(129)],
        ):
            with self.subTest(invalid=invalid):
                self.raw_receipts(invalid)
                self.assertIsNone(self.fixture.entry()["long_receipts"])
                before = self.fixture.path.read_bytes()
                self.assertEqual(store.OUTCOME_REFUSED, self.publish())
                self.assertEqual(before, self.fixture.path.read_bytes())
                self.assertEqual(
                    store.OUTCOME_STORED,
                    store.record_withheld(
                        self.config,
                        self.state,
                        "claude",
                        "s1",
                        reason=reading.WITHHELD_MODEL_FAILED,
                        spent=False,
                    ),
                )
                raw = json.loads(self.fixture.path.read_text())["entries"][0]
                self.assertIsNone(raw["long_receipts"])
                self.assertNotIn("PRIVATE_CANARY", json.dumps(raw))
                self.assertEqual("Ship the cockpit", self.fixture.entry()["revisions"][-1]["goal"])
                self.assertEqual(store.OUTCOME_REFUSED, self.publish())

    def test_opt_in_requires_exact_id_and_valid_target_while_defaults_remain_compatible(
        self,
    ) -> None:
        for changes in (
            {"job_id": ""},
            {"job_id": "a1"},
            {"job_id": "A" * 32},
            {"job_id": True},
            {"long_target": None},
            {"long_publication": 1},
        ):
            with self.subTest(changes=changes):
                before = self.fixture.path.read_bytes()
                self.assertEqual(store.OUTCOME_REFUSED, self.publish(**changes))
                self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertEqual(
            store.OUTCOME_STORED, self.fixture.publish("reading", self.token, job_id="a1")
        )
        self.assertNotIn("long_receipts", self.fixture.entry())

    def test_legacy_job_match_cannot_pretend_to_hold_a_durable_long_acknowledgment(self) -> None:
        self.assertEqual(
            store.OUTCOME_STORED, self.fixture.publish("reading", self.token, job_id=self.job_id)
        )
        before = self.fixture.path.read_bytes()
        self.assertEqual(store.OUTCOME_REFUSED, self.publish())
        self.assertEqual(before, self.fixture.path.read_bytes())
        self.assertNotIn("long_receipts", self.fixture.entry())

    def test_clear_or_store_recreation_never_publishes_old_target_or_restores_receipts(
        self,
    ) -> None:
        for physical in (False, True):
            with self.subTest(physical=physical):
                self.token = self.fixture.capture()
                self.assertEqual(store.OUTCOME_STORED, self.publish())
                if physical:
                    self.fixture.path.unlink()
                else:
                    self.assertEqual(
                        store.OUTCOME_STORED, store.clear(self.config, self.state, "claude", "s1")
                    )
                self.fixture.seed()
                before = self.fixture.path.read_bytes()
                self.assertEqual(store.OUTCOME_REFUSED, self.publish())
                self.assertEqual(before, self.fixture.path.read_bytes())
                self.assertNotIn("long_receipts", self.fixture.entry())
                self.assertNotIn("readings", self.fixture.entry())

    def test_two_writer_processes_commit_one_receipt_and_one_job_count(self) -> None:
        self.assertIn("long_publication", inspect.signature(store.record_withheld).parameters)
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _PUBLISH_WHILE_LOCKED,
                str(Path(__file__).resolve().parents[1]),
                str(self.config.state_dir),
                self.token.incarnation,
                str(self.token.revision),
                self.job_id,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        assert child.stdout is not None and child.stdin is not None
        self.assertEqual(b"locked\n", child.stdout.readline())
        entered = threading.Event()
        original = store._store_locks

        @contextlib.contextmanager
        def entering(*args: Any, **kwargs: Any) -> Any:
            entered.set()
            with original(*args, **kwargs) as held:
                yield held

        answers: list[str] = []
        worker = threading.Thread(target=lambda: answers.append(self.publish()))
        with mock.patch.object(store, "_store_locks", entering):
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
            finally:
                child.stdin.write(b"continue\n")
                child.stdin.flush()
                worker.join(10)
        output, error = child.communicate(timeout=10)
        self.assertEqual(0, child.returncode, error)
        self.assertEqual(b"stored\n", output)
        self.assertFalse(worker.is_alive())
        self.assertEqual([store.OUTCOME_UNCHANGED], answers)
        self.assertEqual([self.job_id], self.fixture.entry()["long_receipts"])
        self.assertEqual(1, self.fixture.entry()["readings"])


_PUBLISH_WHILE_LOCKED = r"""
import sys
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
from compass_runtime import annotations as store, reading
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state
config = build_runtime_config(environ={"HOME": sys.argv[2], "COMPASS_HOME": sys.argv[2]}, platform_name="linux", os_name="posix", launcher_path=Path(sys.argv[1]) / "server.py")
state = build_runtime_state(config, started=100)
target = store.LongTarget(sys.argv[3], int(sys.argv[4]))
original = store._read_store
def paused(config):
    result = original(config)
    print("locked", flush=True)
    sys.stdin.readline()
    return result
with mock.patch.object(store, "_read_store", paused):
    print(store.record_withheld(config, state, "claude", "s1", reason=reading.WITHHELD_MODEL_FAILED, spent=True, job_id=sys.argv[5], long_target=target, long_publication=True), flush=True)
"""
