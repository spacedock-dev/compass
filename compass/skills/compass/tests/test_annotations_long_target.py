"""Long-job publication binds one durable annotation incarnation and revision."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import annotations as store
from compass_runtime import reading
from compass_runtime.state import build_runtime_state

from .support import make_runtime


class LongTargetTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.config, self.state = make_runtime(state_home=home.name, state_dir=Path(home.name))
        self.path = Path(store.store_path(self.config))
        self.seed()

    def seed(self, goal: str = "Ship the cockpit") -> None:
        self.assertEqual(
            store.OUTCOME_STORED,
            store.annotate(self.config, self.state, "claude", "s1", goal=goal, now=100.0),
        )

    def capture(self) -> Any:
        capture: Any = getattr(store, "capture_long_target", None)
        self.assertTrue(callable(capture), "capture_long_target must exist")
        return capture(self.config, self.state, "claude", "s1")

    def entry(self) -> Any:
        return store.find(store.load(self.config), "claude", "s1")

    def assessment(self, revision: int = 1, at: float = 200.0) -> Any:
        return {
            "revision_read": revision,
            "read_at": at,
            "stamp": "read now",
            "cutoff": "Read 1 entry",
            "scope": reading.SCOPE_FINAL,
            "scope_text": reading.SCOPE_TEXT[reading.SCOPE_FINAL],
            "ended_at_read": 99.0,
            "criteria": {
                "goal": {
                    "result": reading.RESULT_UNVERIFIABLE,
                    "cites": (),
                    "detail": "",
                    "clause": "",
                }
            },
        }

    def publish(self, kind: str, token: Any, **extra: Any) -> str:
        if kind == "reading":
            return store.record_reading(
                self.config,
                self.state,
                "claude",
                "s1",
                assessment=self.assessment(token.revision if hasattr(token, "revision") else 1),
                long_target=token,
                **extra,
            )
        return store.record_withheld(
            self.config,
            self.state,
            "claude",
            "s1",
            reason=next(iter(reading.WITHHELD)),
            spent=True,
            long_target=token,
            **extra,
        )

    def test_legacy_capture_is_durable_and_changes_no_words_revision_or_public_payload(
        self,
    ) -> None:
        before = self.entry()
        self.assertNotIn("long_incarnation", before)
        public = store.published(before)
        token = self.capture()
        self.assertIsNotNone(token)
        self.assertEqual(1, token.revision)
        self.assertRegex(token.incarnation, r"^[0-9a-f]{32}$")
        self.assertEqual(before, {k: v for k, v in self.entry().items() if k != "long_incarnation"})
        self.assertEqual(public, store.published(self.entry()))
        self.state = build_runtime_state(self.config, started=300.0)
        self.assertEqual(token, self.capture())
        self.assertEqual(
            token.incarnation, json.loads(self.path.read_text())["entries"][0]["long_incarnation"]
        )

    def test_reading_withheld_settle_and_reload_keep_identity_and_default_behavior(self) -> None:
        token = self.capture()
        self.assertEqual(store.OUTCOME_STORED, self.publish("reading", token, job_id="a1"))
        self.assertEqual(store.OUTCOME_UNCHANGED, self.publish("reading", token, job_id="a1"))
        self.assertEqual(
            store.OUTCOME_STORED,
            store.settle(
                self.config,
                self.state,
                "claude",
                "s1",
                through=150,
                now=200,
                expected_revision=1,
            ),
        )
        self.assertEqual(
            store.OUTCOME_STORED,
            store.record_withheld(
                self.config,
                self.state,
                "claude",
                "s1",
                reason=next(iter(reading.WITHHELD)),
                spent=False,
            ),
        )
        self.assertEqual(token, self.capture())
        self.assertEqual(store.OUTCOME_STORED, self.publish("withheld", token, job_id="a2"))
        entry = self.entry()
        self.assertEqual(2, entry["readings"])
        self.assertEqual(1, entry["assessment"]["revision_read"])
        self.assertEqual(150, entry["settled"]["through"])

    def test_intent_revision_change_refuses_both_outcomes_without_any_write(self) -> None:
        token = self.capture()
        self.seed("Ship something else")
        fresh = self.capture()
        self.assertEqual(token.incarnation, fresh.incarnation)
        self.assertEqual(2, fresh.revision)
        for kind in ("reading", "withheld"):
            with self.subTest(kind=kind):
                before = self.path.read_bytes()
                self.assertEqual(store.OUTCOME_REFUSED, self.publish(kind, token))
                self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(store.OUTCOME_STORED, self.publish("reading", fresh))

    def test_clear_then_recreate_never_reuses_incarnation_at_same_clock(self) -> None:
        token = self.capture()
        self.assertEqual(store.OUTCOME_STORED, store.clear(self.config, self.state, "claude", "s1"))
        self.assertIsNone(self.capture())
        self.seed()
        fresh = self.capture()
        self.assertNotEqual(token.incarnation, fresh.incarnation)
        for kind in ("reading", "withheld"):
            self.assertEqual(store.OUTCOME_REFUSED, self.publish(kind, token))

    def test_physical_store_recreation_refuses_old_token_even_at_same_revision_and_time(
        self,
    ) -> None:
        token = self.capture()
        self.path.unlink()
        self.seed()
        self.assertEqual(token.revision, self.entry()["revisions"][-1]["n"])
        for kind in ("reading", "withheld"):
            self.assertEqual(store.OUTCOME_REFUSED, self.publish(kind, token))
        fresh = self.capture()
        self.assertNotEqual(token.incarnation, fresh.incarnation)
        self.assertEqual(store.OUTCOME_STORED, self.publish("withheld", fresh))

    def test_missing_malformed_foreign_and_wrong_assessment_revision_refuse(self) -> None:
        token = self.capture()
        invalid: Any
        for invalid in (
            None,
            {},
            (token.incarnation, token.revision),
            token._replace(incarnation="x"),
            token._replace(revision=True),
            token._replace(revision=0),
            token._replace(incarnation="0" * 32),
        ):
            for kind in ("reading", "withheld"):
                with self.subTest(invalid=invalid, kind=kind):
                    before = self.path.read_bytes()
                    self.assertEqual(store.OUTCOME_REFUSED, self.publish(kind, invalid))
                    self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(
            store.OUTCOME_REFUSED,
            store.record_reading(
                self.config,
                self.state,
                "claude",
                "s1",
                assessment=self.assessment(2),
                long_target=token,
            ),
        )
        store.annotate(self.config, self.state, "claude", "s2", goal="Other", now=100)
        self.assertEqual(
            store.OUTCOME_REFUSED,
            store.record_withheld(
                self.config,
                self.state,
                "claude",
                "s2",
                reason=next(iter(reading.WITHHELD)),
                spent=True,
                long_target=token,
            ),
        )

    def test_malformed_marker_is_closed_invalid_and_never_reminted(self) -> None:
        token = self.capture()
        marker: Any
        for marker in (None, "words that must not survive", 1, {}, "F" * 32):
            with self.subTest(marker=marker):
                raw = json.loads(self.path.read_text())
                raw["entries"][0]["long_incarnation"] = marker
                self.path.write_text(json.dumps(raw))
                self.assertIsNone(self.capture())
                self.assertEqual("Ship the cockpit", self.entry()["revisions"][-1]["goal"])
                for kind in ("reading", "withheld"):
                    self.assertEqual(store.OUTCOME_REFUSED, self.publish(kind, token))
                store.settle(self.config, self.state, "claude", "s1", through=150, now=200)
                self.assertIsNone(
                    json.loads(self.path.read_text())["entries"][0]["long_incarnation"]
                )
                self.assertIsNone(self.capture())

    def test_unavailable_disabled_and_untrusted_stores_cannot_capture_or_publish(self) -> None:
        token = self.capture()
        self.path.unlink()
        # A legacy entry whose migration cannot persist cannot yield a token.
        self.seed()
        with mock.patch.object(store, "save", return_value=False):
            self.assertIsNone(self.capture())
        with (
            mock.patch.object(store, "_STORE_LOCK_WAIT_SECONDS", 0),
            store._writer_lock(str(self.path)),
        ):
            self.assertIsNone(self.capture())
        self.config = dataclasses.replace(self.config, annotations_enabled=False)
        self.assertIsNone(self.capture())
        self.assertEqual(store.OUTCOME_REFUSED, self.publish("reading", token))
        self.config = dataclasses.replace(self.config, annotations_enabled=True)
        self.path.write_text("not JSON")
        self.assertIsNone(self.capture())
        for kind in ("reading", "withheld"):
            self.assertEqual(store.OUTCOME_UNTRUSTED, self.publish(kind, token))

    def test_existing_newer_assessment_and_diagnostic_barriers_still_apply(self) -> None:
        token = self.capture()
        self.assertEqual(
            store.OUTCOME_STORED,
            store.record_reading(
                self.config,
                self.state,
                "claude",
                "s1",
                assessment=self.assessment(at=300),
            ),
        )
        self.assertEqual(store.OUTCOME_STORED, self.publish("reading", token))
        self.assertEqual(300, self.entry()["assessment"]["read_at"])
        before = self.path.read_bytes()
        self.assertEqual(
            store.OUTCOME_REFUSED, self.publish("withheld", token, analyze_diagnostic={})
        )
        self.assertEqual(before, self.path.read_bytes())

    def test_waiting_publication_checks_revision_after_other_process_commits(self) -> None:
        for kind in ("reading", "withheld"):
            with self.subTest(kind=kind):
                self.race(kind)

    def race(self, kind: str) -> None:
        token = self.capture()
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _EDIT_WHILE_LOCKED,
                str(Path(__file__).resolve().parents[1]),
                str(self.config.state_dir),
                kind,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(child.kill if child.poll() is None else lambda: None)
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
        worker = threading.Thread(target=lambda: answers.append(self.publish(kind, token)))
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
        self.assertEqual([store.OUTCOME_REFUSED], answers)
        self.assertNotIn("readings", self.entry())


_EDIT_WHILE_LOCKED = r"""
import sys
from pathlib import Path
from unittest import mock
sys.path.insert(0, sys.argv[1])
from compass_runtime import annotations as store
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state
config = build_runtime_config(
    environ={"HOME": sys.argv[2], "COMPASS_HOME": sys.argv[2]},
    platform_name="linux", os_name="posix", launcher_path=Path(sys.argv[1]) / "server.py",
)
state = build_runtime_state(config, started=100)
original = store._read_store
def paused(config):
    result = original(config)
    print("locked", flush=True)
    sys.stdin.readline()
    return result
with mock.patch.object(store, "_read_store", paused):
    print(store.annotate(config, state, "claude", "s1", goal=sys.argv[3], now=100), flush=True)
"""
