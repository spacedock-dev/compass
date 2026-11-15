"""Unsafe filesystem leaves refuse without blocking or changing another file."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import os
import secrets
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import agy_hook
import event_hook
import mcp_server
import statusline_hook
from compass_runtime import annotations as annotation_store
from compass_runtime import (
    claude_data,
    deliveries,
    departures,
    ends,
    lifecycle,
    observer,
    project_context,
    reading_policy,
    reading_source_stream,
    semantic_history,
    session_source,
    spacedock,
)
from compass_runtime import io as runtime_io

from .support import make_runtime
from .test_claude_checks import Transcript

# A planted FIFO must finish before a short join, rather than wait for a writer.
REAL_TIME_TESTS = True
UUID = "12345678-1234-1234-1234-123456789abc"

if TYPE_CHECKING:
    from collections.abc import Callable


class OwnerIoTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.root = Path(home.name)
        self.config, self.state = make_runtime(state_home=home.name, state_dir=self.root)

    def readers(self, path: str) -> list[Any]:
        return [
            lambda: runtime_io.read_tail(self.config, path),
            lambda: runtime_io.read_first_json(self.config, path),
            lambda: runtime_io.read_prefix_bytes(path, max_bytes=64),
            lambda: list(runtime_io.iter_bounded_text_lines(path, max_lines=2, per_line_bytes=64)),
            lambda: list(runtime_io.reverse_lines(self.config, path)),
            lambda: runtime_io.scan_reverse_lines(self.config, path, runtime_io.ReadBudget(64)),
            lambda: runtime_io.scan_stood_lines(
                path, runtime_io.ReadBudget(64), lambda _raw: False
            ),
            lambda: spacedock.open_regular(path),
            lambda: runtime_io.open_sqlite_read_only(path, self.state),
        ]

    def refused(self, call: Any) -> Any:
        try:
            result = call()
        except (OSError, runtime_io.sqlite_module.Error):
            return None
        if isinstance(result, runtime_io.TranscriptRead):
            self.assertTrue(result.failed)
        elif isinstance(result, int):
            os.close(result)
            self.fail("unsafe regular-file descriptor was returned")
        else:
            self.assertFalse(result)
        return result

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_readers_refuse_leaf_symlinks(self) -> None:
        target = self.root / "real"
        target.write_text('{"private":true}\n')
        path = self.root / "link"
        path.symlink_to(target)
        for index, call in enumerate(self.readers(str(path))):
            with self.subTest(reader=index):
                self.refused(call)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unavailable")
    def test_readers_refuse_fifo_without_waiting_for_a_writer(self) -> None:
        path = self.root / "fifo"
        os.mkfifo(path)
        for index, call in enumerate(self.readers(str(path))):
            with self.subTest(reader=index):
                errors: list[BaseException] = []

                def run(call: Any = call, errors: list[BaseException] = errors) -> None:
                    try:
                        self.refused(call)
                    except BaseException as exc:  # noqa: BLE001 - surface the worker failure in the test thread
                        errors.append(exc)

                thread = threading.Thread(target=run, daemon=True)
                thread.start()
                thread.join(0.5)
                blocked = thread.is_alive()
                if blocked:
                    # Release a regressed blocking reader before temp-directory cleanup.
                    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
                    os.close(fd)
                    thread.join(2)
                self.assertFalse(blocked, f"reader {index} blocked on a FIFO")
                if errors:
                    raise errors[0]

    def test_symlinked_store_directory_still_reads_regular_leaves(self) -> None:
        store = self.root / "store"
        store.mkdir()
        (store / "session").write_text("hello\n")
        alias = self.root / "alias"
        alias.symlink_to(store, target_is_directory=True)
        self.assertEqual(["hello", ""], runtime_io.read_tail(self.config, str(alias / "session")))

    def test_hooks_and_mcp_refuse_symlinked_capability_files(self) -> None:
        target = self.root / "real"
        target.write_text(
            json.dumps({"port": 9999, "capabilities": {"antigravity": "test", "claude": "test"}})
        )
        (self.root / "compass-9999.json").symlink_to(target)
        with mock.patch.dict(os.environ, {"COMPASS_HOME": str(self.root)}):
            self.assertIsNone(event_hook.capability(9999, "claude"))
            self.assertIsNone(agy_hook.capability(9999))
            self.assertIsNone(statusline_hook.capability(9999))
            self.assertEqual([], mcp_server._published_ports())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unavailable")
    def test_hooks_and_mcp_refuse_fifo_capability_files(self) -> None:
        path = self.root / "compass-9999.json"
        os.mkfifo(path)
        with mock.patch.dict(os.environ, {"COMPASS_HOME": str(self.root)}):
            calls = [
                lambda: event_hook.capability(9999, "claude"),
                lambda: agy_hook.capability(9999),
                lambda: statusline_hook.capability(9999),
                mcp_server._published_ports,
            ]
            for call in calls:
                thread = threading.Thread(target=call, daemon=True)
                thread.start()
                thread.join(0.5)
                blocked = thread.is_alive()
                if blocked:
                    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
                    os.close(fd)
                    thread.join(2)
                self.assertFalse(blocked)

    def test_antigravity_ids_require_uuid_and_memo_rechecks_direct_call(self) -> None:
        for bad in ("x" * 36, "x\\..\\..\\" + "a" * 28):
            self.assertEqual(36, len(bad))
            self.assertIsNone(statusline_hook.conversation_id({"conversation_id": bad}))
            with mock.patch.dict(os.environ, {"ANTIGRAVITY_CONVERSATION_ID": ""}):
                self.assertIsNone(agy_hook.conversation_id({"conversationId": bad}))
            with mock.patch.dict(os.environ, {"COMPASS_HOME": str(self.root)}):
                statusline_hook.write_memo(bad, {"state": "idle"})
        self.assertEqual([], list(self.root.iterdir()))
        self.assertEqual(
            UUID.upper(), statusline_hook.conversation_id({"session_id": UUID.upper()})
        )

    def test_memo_write_refuses_link_and_creates_private_atomic_file(self) -> None:
        target = self.root / "real"
        target.write_text("keep")
        memo = self.root / f"statusline-antigravity-{UUID}.json"
        memo.symlink_to(target)
        with mock.patch.dict(os.environ, {"COMPASS_HOME": str(self.root)}):
            statusline_hook.write_memo(UUID, {"state": "idle"})
            self.assertEqual("keep", target.read_text())
            self.assertTrue(memo.is_symlink())
            memo.unlink()
            statusline_hook.write_memo(UUID, {"state": "idle"})
        self.assertEqual({"state": "idle"}, json.loads(memo.read_text()))
        if os.name != "nt":
            self.assertEqual(0o600, stat.S_IMODE(memo.stat().st_mode))

    @unittest.skipIf(os.name == "nt", "POSIX modes and uid")
    def test_owner_directory_tightens_but_foreign_directory_refuses(self) -> None:
        self.root.chmod(0o755)
        runtime_io.ensure_owner_dir(str(self.root))
        self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))
        self.root.chmod(0o755)
        with (
            mock.patch.object(os, "getuid", return_value=os.getuid() + 1),
            self.assertRaises(OSError),
        ):
            runtime_io.ensure_owner_dir(str(self.root))
        self.assertEqual(0o755, stat.S_IMODE(self.root.stat().st_mode))

    def test_atomic_writer_refuses_symlink_target(self) -> None:
        target = self.root / "real"
        target.write_text("keep")
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            runtime_io.atomic_write_owner_only(str(link), "new")
        self.assertTrue(link.is_symlink())
        self.assertEqual("keep", target.read_text())

    def test_locks_refuse_symlinks_and_fifo(self) -> None:
        real = self.root / "real"
        real.write_text("keep")
        path = self.root / "lock"
        path.symlink_to(real)
        with runtime_io.held_file_lock(path, wait=0) as held:
            self.assertEqual(runtime_io.LOCK_DENIED, held)
        path.unlink()
        if hasattr(os, "mkfifo"):
            os.mkfifo(path)
            with runtime_io.held_file_lock(path, wait=0) as held:
                self.assertEqual(runtime_io.LOCK_DENIED, held)

    @unittest.skipIf(os.name == "nt", "POSIX modes and uid")
    def test_lock_tightens_mode_and_refuses_wrong_uid(self) -> None:
        path = self.root / "lock"
        path.write_text("")
        path.chmod(0o644)
        with runtime_io.held_file_lock(path, wait=0) as held:
            self.assertEqual(runtime_io.LOCK_HELD, held)
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        with (
            mock.patch.object(os, "getuid", return_value=os.getuid() + 1),
            runtime_io.held_file_lock(path, wait=0) as held,
        ):
            self.assertEqual(runtime_io.LOCK_DENIED, held)

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_policy_logs_and_state_writers_tighten_existing_home(self) -> None:
        operations: list[Callable[[], Any]] = [
            lambda: reading_policy.set_consent(self.config, False, now=100),
            lambda: lifecycle.prepare_daemon_home(self.config, str(self.root / "compass-9999.log")),
            lambda: annotation_store.save(self.config, []),
            lambda: semantic_history._write(self.config, {"projects": {}}),
            lambda: deliveries.save(self.config, []),
            lambda: departures.save(self.config, []),
            lambda: ends.save(self.config, []),
            lambda: observer.write_sidecar(self.config, "claude", UUID, {"goal": "test"}),
        ]
        for index, operation in enumerate(operations):
            self.root.chmod(0o755)
            with self.subTest(writer=index):
                operation()
                self.assertEqual(0o700, stat.S_IMODE(self.root.stat().st_mode))
        for path in self.root.rglob("*"):
            self.assertEqual(
                0o700 if path.is_dir() else 0o600, stat.S_IMODE(path.stat().st_mode), str(path)
            )

    def test_daemon_log_refuses_symlink_without_clobbering(self) -> None:
        target = self.root / "real"
        target.write_text("keep")
        path = self.root / "compass-9999.log"
        path.symlink_to(target)
        self.assertFalse(
            lifecycle.prepare_daemon_home(
                self.config, str(path), diagnostic_sink=lambda _text: None
            )
        )
        self.assertEqual("keep", target.read_text())

    def test_parallel_sidecar_publications_all_complete(self) -> None:
        # Pause every publication at rename, after all writers have opened and written.
        count = 8
        barrier = threading.Barrier(count)
        replace = os.replace

        def publish(src: str, dst: str) -> None:
            barrier.wait(timeout=10)
            replace(src, dst)

        with (
            mock.patch.object(os, "replace", side_effect=publish),
            concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool,
        ):
            results = list(
                pool.map(
                    lambda index: observer.write_sidecar(
                        self.config, "claude", UUID, {"index": index}
                    ),
                    range(count),
                )
            )
        self.assertTrue(all(results))
        path = observer.sidecar_path(self.config, "claude", UUID)
        assert path is not None
        self.assertIn(json.loads(Path(path).read_text())["index"], range(count))
        self.assertEqual([], list(self.root.rglob("*.tmp")))

    def test_session_page_refuses_a_symlinked_parent_transcript(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Private parent message")
        target = self.root / "real.jsonl"
        transcript.save(target)
        link = self.root / "session.jsonl"
        link.symlink_to(target)
        page = session_source.read(self.config, str(link), "claude", UUID)
        self.assertEqual("unavailable", page.state)
        self.assertEqual(0, page.bytes_read)

    def test_instruction_events_refuse_leaf_symlinks(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Private instructions")
        target = self.root / "real.jsonl"
        transcript.save(target)
        link = self.root / "session.jsonl"
        link.symlink_to(target)
        self.assertEqual(
            [], project_context.instruction_events(self.config, str(link), "claude", UUID)
        )

    def test_frozen_reading_refuses_a_symlinked_parent_transcript(self) -> None:
        target = self.root / "real.jsonl"
        target.write_text('{"type":"user"}\n')
        link = self.root / "session.jsonl"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            reading_source_stream.freeze(str(link), "claude", UUID)

    def test_sqlite_goal_reader_refuses_a_leaf_symlink(self) -> None:
        sqlite = runtime_io.sqlite_module
        target = self.root / "real.db"
        with sqlite.connect(target) as db:
            db.execute(
                "CREATE TABLE thread_goals (thread_id, objective, created_at_ms, updated_at_ms, status)"
            )
            db.execute("INSERT INTO thread_goals VALUES ('id', 'private goal', 1, 2, 'complete')")
        link = self.root / "link.db"
        link.symlink_to(target)
        with self.assertRaises(sqlite.Error):
            claude_data._read_codex_goals(str(link))

    def test_state_writers_refuse_link_targets(self) -> None:
        operations: list[tuple[str, Callable[[], Any]]] = [
            (
                annotation_store.store_path(self.config),
                lambda: annotation_store.save(self.config, [], diagnostic_sink=lambda _text: None),
            ),
            (
                semantic_history.store_path(self.config),
                lambda: semantic_history._write(self.config, {"projects": {}}),
            ),
            (
                deliveries.store_path(self.config),
                lambda: deliveries.save(self.config, [], diagnostic_sink=lambda _text: None),
            ),
            (
                departures.store_path(self.config),
                lambda: departures.save(self.config, [], diagnostic_sink=lambda _text: None),
            ),
            (
                ends.store_path(self.config),
                lambda: ends.save(self.config, [], diagnostic_sink=lambda _text: None),
            ),
        ]
        target = self.root / "real"
        target.write_text("keep")
        for name, operation in operations:
            path = Path(name)
            path.symlink_to(target)
            with self.subTest(writer=path.name):
                self.assertFalse(operation())
                self.assertTrue(path.is_symlink())
                self.assertEqual("keep", target.read_text())
        sidecar = observer.sidecar_path(self.config, "claude", UUID)
        assert sidecar is not None
        path = Path(sidecar)
        path.parent.mkdir()
        path.symlink_to(target)
        self.assertIsNone(observer.write_sidecar(self.config, "claude", UUID, {"goal": "test"}))
        self.assertTrue(path.is_symlink())
        self.assertEqual("keep", target.read_text())

    def test_owner_directory_refuses_a_symlink_without_chmodding_its_target(self) -> None:
        target = self.root / "directory"
        target.mkdir()
        if os.name != "nt":
            target.chmod(0o755)
        link = self.root / "alias"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(OSError):
            runtime_io.ensure_owner_dir(str(link))
        if os.name != "nt":
            self.assertEqual(0o755, target.stat().st_mode & 0o777)

    def test_permission_store_refuses_a_symlink(self) -> None:
        target = self.root / "real.db"
        target.write_text("keep")
        reading_policy.store_path(self.config).symlink_to(target)
        result = reading_policy.set_consent(self.config, True, now=100)
        self.assertEqual("store-unavailable", result["reason"])
        self.assertEqual("keep", target.read_text())

    @unittest.skipIf(os.name == "nt", "POSIX permissions")
    def test_new_policy_and_log_homes_are_private(self) -> None:
        home = self.root / "policy-home"
        config = dataclasses.replace(self.config, state_home=str(home), state_dir=home)
        reading_policy.set_consent(config, False, now=100)
        self.assertEqual(0o700, home.stat().st_mode & 0o777)
        self.assertEqual(0o600, reading_policy.store_path(config).stat().st_mode & 0o777)
        home = self.root / "log-home"
        config = dataclasses.replace(self.config, state_home=str(home), state_dir=home)
        log = home / "compass-9999.log"
        self.assertTrue(lifecycle.prepare_daemon_home(config, str(log)))
        self.assertEqual(0o700, home.stat().st_mode & 0o777)
        self.assertEqual(0o600, log.stat().st_mode & 0o777)

    def test_planted_atomic_temporary_symlink_cannot_clobber_its_target(self) -> None:
        target = self.root / "state.json"
        target.write_text("old state")
        outside = self.root / "elsewhere"
        outside.write_text("keep")
        temporary = Path(f"{target}.{os.getpid()}.fixed.tmp")
        temporary.symlink_to(outside)
        with (
            mock.patch.object(secrets, "token_hex", return_value="fixed"),
            self.assertRaises(OSError),
        ):
            runtime_io.atomic_write_owner_only(str(target), "new state")
        self.assertEqual("old state", target.read_text())
        self.assertEqual("keep", outside.read_text())
        self.assertTrue(temporary.is_symlink())
