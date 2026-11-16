"""Durable launcher claims use private state and retain their original clock."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import multiprocessing
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import aggregate, cli, declared_sessions, lifecycle, observation
from compass_runtime import annotations as annotation_store
from compass_runtime import declared_parent_store as store

from .support import make_runtime
from .test_declared_sessions import CHILD, NOW, PARENT, row
from .test_events_ingress import FakeApplication


def writer(home: str, sid: str) -> None:
    config, _ = make_runtime(state_home=home, state_dir=Path(home))
    source = observation.Observation(FakeApplication(config), clock=lambda: NOW)  # type: ignore[arg-type]
    source.submit(
        "claude",
        {
            "v": 1,
            "event": "session_started",
            "session_id": sid,
            "declared_parent": {"harness": "claude", "sid": PARENT},
        },
    )


class DurableClaims(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.config, self.state = make_runtime(state_home=temp.name, state_dir=self.home)
        self.now = NOW
        self.messages: list[str] = []

    def source(self) -> observation.Observation:
        return observation.Observation(
            FakeApplication(self.config),  # type: ignore[arg-type]
            clock=lambda: self.now,
            diagnostic_sink=self.messages.append,
        )

    def declare(self, source: observation.Observation, sid: str = CHILD) -> None:
        self.assertEqual(
            "accepted",
            source.submit(
                "claude",
                {
                    "v": 1,
                    "event": "session_started",
                    "session_id": sid,
                    "declared_parent": {"harness": "claude", "sid": PARENT},
                },
            ),
        )

    def test_expired_absent_claims_are_pruned_without_extending_a_hold(self) -> None:
        original = self.source()
        self.declare(original)
        self.now += self.config.focus_target_ttl_sec + 1
        restarted = self.source()
        restarted.note_rows({("claude", CHILD[:8])})
        self.assertIn(("claude", CHILD[:8]), restarted.parent_declarations())
        rows = [row("claude", PARENT[:8]), row("claude", CHILD[:8], state="working")]
        declared_sessions.attach(
            rows, restarted.parent_declarations(), config=self.config, now=self.now
        )
        self.assertIsNone(rows[0]["waiting_on_child"])
        restarted.note_rows(set())
        self.assertEqual({}, restarted.parent_declarations())
        self.assertEqual({}, self.source().parent_declarations())

    def test_concurrent_claim_writers_preserve_each_others_changes(self) -> None:
        context = multiprocessing.get_context("spawn")
        workers = [
            context.Process(target=writer, args=(str(self.home), sid))
            for sid in (CHILD, "87654321-3456-7890-abcd-ef1234567890")
        ]
        try:
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                self.assertEqual(0, worker.exitcode)
            self.assertEqual(2, len(self.source().parent_declarations()))
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)

    def test_unsafe_declaration_store_paths_are_refused(self) -> None:
        store = self.home / "declared-parents" / "claims.json"
        store.parent.mkdir(mode=0o700)
        outside = self.home / "outside.json"
        outside.write_text("untouched")
        for kind in ("symlink", "fifo", "lock", "directory"):
            with self.subTest(kind=kind):
                if kind == "fifo" and not hasattr(os, "mkfifo"):
                    continue
                target = store.parent / "claims.lock" if kind == "lock" else store
                if kind == "lock":
                    target.unlink(missing_ok=True)
                if kind == "fifo":
                    os.mkfifo(target)
                elif kind == "directory":
                    target.mkdir()
                else:
                    target.symlink_to(outside)
                try:
                    began = time.monotonic()
                    source = self.source()
                    self.declare(source)
                    self.assertLess(time.monotonic() - began, 1)
                    self.assertTrue(source.parent_declarations())
                    self.assertTrue(self.messages)
                    self.assertEqual("untouched", outside.read_text())
                finally:
                    target.rmdir() if kind == "directory" else target.unlink()
                with contextlib.suppress(FileNotFoundError):
                    store.unlink()
        # Configured roots may resolve links; descendants must never do so.
        (store.parent / "claims.lock").unlink(missing_ok=True)
        store.parent.rmdir()
        other = self.home / "other"
        other.mkdir()
        store.parent.symlink_to(other, target_is_directory=True)
        self.declare(self.source())
        self.assertEqual([], list(other.iterdir()))

    def test_corrupt_or_unwritable_store_is_diagnosed_and_not_overwritten(self) -> None:
        store = self.home / "declared-parents" / "claims.json"
        store.parent.mkdir(mode=0o700)
        for content in ("no json", '{"v":2,"claims":[]}', '{"v":1,"claims":[{}]}'):
            store.write_text(content)
            self.declare(self.source())
            self.assertEqual(content, store.read_text())
            self.assertTrue(self.messages)
        store.unlink()
        with mock.patch("compass_runtime.io.atomic_write_owner_only", side_effect=OSError("full")):
            source = self.source()
            self.declare(source)
        self.assertTrue(source.parent_declarations())
        self.assertEqual({}, self.source().parent_declarations())
        self.assertTrue(any("memory" in message for message in self.messages))

    def test_an_unpersisted_claim_survives_collection_until_expired_or_replaced(self) -> None:
        source = self.source()
        with mock.patch.object(store, "record", return_value=None):
            self.declare(source)
        source.note_rows({("claude", CHILD[:8])})
        self.assertIn(("claude", CHILD[:8]), source.parent_declarations())
        self.now += self.config.focus_target_ttl_sec + 1
        source.note_rows(set())
        self.assertEqual({}, source.parent_declarations())

    def test_in_memory_capacity_and_expiry_hold_when_storage_is_unavailable(self) -> None:
        self.config = dataclasses.replace(self.config, event_overlay_max_sessions=1)
        source = self.source()
        with (
            mock.patch.object(store, "record", return_value=None),
            mock.patch.object(store, "prune", return_value=None),
        ):
            self.declare(source)
            self.declare(source, "87654321-3456-7890-abcd-ef1234567890")
            self.assertEqual(1, len(source.parent_declarations()))
            self.now += self.config.focus_target_ttl_sec + 1
            source.note_rows(set())
            self.assertEqual({}, source.parent_declarations())

    def test_declaration_capacity_and_expiry_remain_bounded(self) -> None:
        self.config = dataclasses.replace(self.config, event_overlay_max_sessions=1)
        source = self.source()
        self.declare(source)
        self.declare(source, "87654321-3456-7890-abcd-ef1234567890")
        self.assertEqual(1, len(self.source().parent_declarations()))
        self.now += self.config.focus_target_ttl_sec + 1
        restarted = self.source()
        restarted.note_rows(set())
        self.assertEqual({}, self.source().parent_declarations())

    def test_private_bounded_schema_preserves_timestamps_and_refuses_oversized_write(self) -> None:
        self.declare(self.source())
        path = self.home / "declared-parents" / "claims.json"
        content = json.loads(path.read_text())
        self.assertEqual(NOW, content["claims"][0]["at"])
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))
        for field, bad in (
            ("at", float("nan")),
            ("at", 10**400),
            ("at", True),
            ("at", NOW + 1),
            ("sid", "../x"),
            ("parent", {"harness": "claude", "sid": "../x"}),
        ):
            broken = json.loads(json.dumps(content))
            broken["claims"][0][field] = bad
            path.write_text(json.dumps(broken))
            self.assertEqual({}, self.source().parent_declarations())
        path.write_text(json.dumps(content))
        with mock.patch.object(store, "MAX_BYTES", len(path.read_bytes()) + 10):
            self.declare(self.source(), "87654321-3456-7890-abcd-ef1234567890")
            self.assertEqual(content, json.loads(path.read_text()))

    def test_forget_removes_declarations_while_retaining_user_authored_groups(self) -> None:
        self.declare(self.source())
        annotation_store.annotate(
            self.config, self.state, "claude", PARENT[:8], group="Owner", now=NOW
        )
        with (
            mock.patch.object(lifecycle, "instance_status", return_value={"state": "stopped"}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = cli.run_one_shot(
                cli.build_parser().parse_args(["--forget"]), self.config, self.state
            )
        self.assertEqual(0, result)
        self.assertEqual({}, self.source().parent_declarations())
        self.assertEqual("Owner", annotation_store.load(self.config)[0]["group"])

    def test_later_events_cannot_introduce_or_replace_declarations(self) -> None:
        source = self.source()
        envelope = {
            "v": 1,
            "event": "turn_started",
            "session_id": CHILD,
            "declared_parent": {"harness": "claude", "sid": PARENT},
        }
        source.submit("claude", envelope)
        self.assertEqual({}, self.source().parent_declarations())
        self.declare(source)
        self.now += 1
        source.submit("claude", envelope)
        path = self.home / "declared-parents" / "claims.json"
        self.assertEqual(self.now, json.loads(path.read_text())["claims"][0]["at"])

    def test_no_events_collection_does_not_restore_claims(self) -> None:
        self.declare(self.source())
        app = aggregate.Application(
            self.config,
            self.state,
            (
                aggregate.HarnessSpec(
                    "claude",
                    "Claude",
                    lambda *_: True,
                    lambda *_: [
                        row("claude", PARENT[:8]),
                        row("claude", CHILD[:8], state="working"),
                    ],
                ),
            ),
            native_notifier=lambda _: "",
            popup_notifier=lambda *_: None,
            diagnostic_sink=self.messages.append,
            clock=lambda: NOW,
        )
        published = app.collect(show_all=False, notify=False)["sessions"]
        self.assertTrue(
            all(r["declared_parent"] is None and r["waiting_on_child"] is None for r in published)
        )
