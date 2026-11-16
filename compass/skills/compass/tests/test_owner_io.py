"""Unsafe filesystem leaves refuse without blocking or changing another file."""

from __future__ import annotations

import concurrent.futures
import dataclasses
import importlib.util
import json
import os
import secrets
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

import agy_hook
import event_hook
import mcp_server
import notify_hook
import statusline_hook
from compass_runtime import annotations as annotation_store
from compass_runtime import (
    claude_data,
    compass_turns,
    copied_corrections,
    deliveries,
    departures,
    ends,
    entry_numbers,
    lifecycle,
    observer,
    project_context,
    reading_policy,
    reading_source_stream,
    record_pages,
    semantic_history,
    session_source,
    spacedock,
    transcripts,
    turns,
    typed_press,
)
from compass_runtime import (
    config as runtime_config,
)
from compass_runtime import io as runtime_io
from compass_runtime.collectors import antigravity, claude, pi

from .fixtures import protobuf_bytes_field, protobuf_int_field
from .support import make_runtime
from .test_claude_checks import Transcript

UUID = "12345678-1234-1234-1234-123456789abc"

if TYPE_CHECKING:
    from collections.abc import Callable


class OwnerIoTest(unittest.TestCase):
    # FIFO refusals finish immediately; joins only guard against a blocked reader.

    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.root = Path(home.name)
        self.config, self.state = make_runtime(state_home=home.name, state_dir=self.root)

    @unittest.skipIf(os.name == "nt", "POSIX directory ownership and modes")
    def test_owned_linked_home_supports_start_state_and_hooks(self) -> None:
        target = self.root / "owned-home"
        target.mkdir(mode=0o755)
        target.chmod(0o755)
        home = self.root / "linked-home"
        home.symlink_to(target, target_is_directory=True)
        config = dataclasses.replace(self.config, state_home=str(home), state_dir=home)
        self.assertTrue(lifecycle.prepare_daemon_home(config, str(home / "compass-9999.log")))
        self.assertTrue(deliveries.save(config, []))
        self.assertNotEqual(
            "store-unavailable", reading_policy.set_consent(config, False, now=100).get("reason")
        )
        notify_hook.write_owner_json(str(home / "memo.json"), {"ok": True})
        self.assertEqual({"ok": True}, json.loads((target / "memo.json").read_text()))
        self.assertEqual(0o700, stat.S_IMODE(target.stat().st_mode))

    @unittest.skipIf(os.name == "nt", "POSIX directory modes")
    def test_nested_state_creation_secures_every_created_parent(self) -> None:
        before = stat.S_IMODE(self.root.stat().st_mode)
        old_umask = os.umask(0o022)
        try:
            runtime_io.atomic_write_owner_only(str(self.root / "state" / "nested" / "x"), "ok")
            notify_hook.write_owner_json(str(self.root / "hook" / "nested" / "x"), {"ok": True})
        finally:
            os.umask(old_umask)
        for name in ("state", "state/nested", "hook", "hook/nested"):
            self.assertEqual(0o700, stat.S_IMODE((self.root / name).stat().st_mode), name)
        self.assertEqual(before, stat.S_IMODE(self.root.stat().st_mode))

    @unittest.skipIf(os.name == "nt", "POSIX directory ownership")
    def test_foreign_root_refuses_without_chmod_or_creation(self) -> None:
        home = self.root / "foreign"
        home.mkdir(mode=0o755)
        home.chmod(0o755)
        writers: list[Callable[[], Any]] = [
            lambda: runtime_io.atomic_write_owner_only(str(home / "nested" / "x"), "bad"),
            lambda: notify_hook.write_owner_json(str(home / "nested" / "x"), {"bad": True}),
        ]
        for writer in writers:
            with (
                mock.patch.object(os, "getuid", return_value=os.getuid() + 1),
                self.assertRaises(OSError),
            ):
                writer()
            self.assertEqual([], list(home.iterdir()))
            self.assertEqual(0o755, stat.S_IMODE(home.stat().st_mode))

    def harness_readers(self, path: str) -> dict[str, Callable[[], Any]]:
        return {
            "title": lambda: claude_data.session_title(self.config, self.state, path),
            "goal": lambda: claude_data.session_goal(self.config, self.state, path),
            "prompts": lambda: claude_data._advance_prompts(
                path, claude_data._PromptRead((0, 0), 0)
            ),
            "conversation": lambda: claude_data.has_conversation(self.config, self.state, path),
            "turns": lambda: turns.scan_turns(self.config, self.state, path, "claude"),
            "first_prompt": lambda: transcripts.first_prompt(
                self.config, self.state, path, "claude"
            ),
            "page": lambda: record_pages.read(
                self.config, path, "claude", UUID, cursor_key=b"k" * 32
            ),
            "page_scan": lambda: record_pages.scan_source(
                self.config, path, lambda _raw: None, max_bytes=4096, deadline=time.monotonic() + 1
            ),
            "index": lambda: entry_numbers.MessageIndex("claude", UUID).extend(
                self.config, path, time.monotonic() + 1
            ),
            "pi_end": lambda: pi._complete_end(self.config, path, 1),
            "pi_scan": lambda: pi.scan_pi_session(self.config, self.state, path),
            "teams": lambda: self._store_reader(path, claude.load_team_members, "teams"),
            "tasks": lambda: self._store_reader(path, claude.load_tasks, "tasks"),
            "agent_label": lambda: claude.agent_label(path.removesuffix(".meta.json") + ".jsonl"),
            "antigravity": lambda: self._antigravity_metadata(path),
            "compass_turns": lambda: compass_turns._advance(
                path, compass_turns._Read((0, 0), 0, (), None)
            ),
            "codex_prefix": lambda: project_context.codex_source_prefix(
                self.config, path, time.time()
            ),
            "session": lambda: session_source.read(self.config, path, "claude", UUID),
            "typed_press": lambda: typed_press.tail_lines(path),
            "corrections": lambda: copied_corrections._scan(self.config, path, UUID, 0, 1),
            "pi_settings": lambda: self._pi_settings(path),
            "tail": lambda: runtime_io.read_tail(self.config, path),
        }

    def _pi_settings(self, path: str) -> Any:
        settings = self.root / "settings.json"
        if not settings.exists():
            settings.symlink_to(path)
        return runtime_config.load_pi_settings(str(self.root))

    def _store_reader(self, path: str, reader: Any, _kind: str) -> Any:
        with mock.patch.object(runtime_io, "glob_stores", return_value=[path]):
            return reader(self.config)

    def _antigravity_metadata(self, path: str) -> Any:
        with mock.patch.object(antigravity, "_last_conversations_path", return_value=path):
            return antigravity._session_metadata(self.config, time.time(), 24, True)

    def _quick(self, call: Callable[[], Any], fifo: Path) -> Any:
        results: list[Any] = []
        errors: list[BaseException] = []

        def run() -> None:
            try:
                results.append(call())
            except (OSError, project_context.FrozenCheckCutoffUnreachableError):
                results.append(None)
            except BaseException as exc:  # noqa: BLE001 - propagate worker failures
                errors.append(exc)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(0.5)
        blocked = thread.is_alive()
        if blocked:
            fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
            os.close(fd)
            thread.join(2)
        self.assertFalse(blocked, "reader waited for a FIFO writer")
        if errors:
            raise errors[0]
        return results[0]

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unavailable")
    def test_directory_fallback_refuses_fifo_without_writer(self) -> None:
        path = self.root / "not-a-directory"
        os.mkfifo(path)
        for directory_flag in (None, 0):
            for opener in (
                lambda: runtime_io._directory_fd(str(path)),
                lambda: runtime_io._owner_directory_fd(
                    str(path), root=str(self.root), create=False
                ),
            ):
                with (
                    self.subTest(flag=directory_flag, opener=opener),
                    mock.patch.object(os, "O_DIRECTORY", directory_flag, create=True),
                ):
                    self.assertIsNone(self._quick(opener, path))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs unavailable")
    def test_all_harness_readers_refuse_fifo_without_writer(self) -> None:
        path = self.root / "session.meta.json"
        os.mkfifo(path)
        for name, call in self.harness_readers(str(path)).items():
            with self.subTest(reader=name):
                self._quick(call, path)
        self.assertFalse(claude_data.has_conversation(self.config, self.state, str(path)))

    def test_owned_leaf_and_directory_links_work_across_readers(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Owned parent message")
        target = self.root / "real.jsonl"
        transcript.save(target)
        leaf = self.root / "leaf.jsonl"
        leaf.symlink_to(target)
        directory = self.root / "directory"
        directory.symlink_to(self.root, target_is_directory=True)
        for path in (target, leaf, directory / target.name):
            with self.subTest(path=path):
                self.assertEqual(
                    "Owned parent message",
                    claude_data.session_title(self.config, self.state, str(path)),
                )
                self.assertEqual(
                    "Owned parent message",
                    transcripts.first_prompt(self.config, self.state, str(path), "claude")[
                        "first_prompt"
                    ],
                )
                self.assertEqual(
                    "ok",
                    record_pages.read(self.config, str(path), "claude", UUID, cursor_key=b"k" * 32)[
                        "state"
                    ],
                )
                self.assertNotEqual(
                    "unavailable", session_source.read(self.config, str(path), "claude", UUID).state
                )
                self.assertEqual(
                    "Owned parent message",
                    claude_data._advance_prompts(
                        str(path), claude_data._PromptRead((0, 0), 0)
                    ).words,
                )
                index = entry_numbers.MessageIndex("claude", UUID)
                index.extend(self.config, str(path), time.monotonic() + 1)
                self.assertTrue(index.keys)
                self.assertEqual(
                    target.read_bytes(),
                    project_context.codex_source_prefix(self.config, str(path), time.time()),
                )
                frozen = reading_source_stream.freeze(str(path), "claude", UUID)
                self.assertEqual(target.stat().st_size, frozen.frozen.end_offset)
                pages = []
                while True:
                    page = reading_source_stream.read(frozen, max_bytes=4096, max_seconds=1)
                    pages.append(page)
                    if page.next is None:
                        break
                    frozen = page.next
                self.assertEqual("verified", pages[-1].state)
                self.assertEqual(
                    target.read_bytes(), b"".join(row.raw for page in pages for row in page.records)
                )
                self.assertEqual(
                    runtime_io.read_tail(self.config, str(target)),
                    runtime_io.read_tail(self.config, str(path)),
                )

    def test_owned_links_work_for_metadata_and_pi_readers(self) -> None:
        directory = self.root / "session-12345678"
        directory.mkdir()
        metadata = directory / "real.meta.json"
        metadata.write_text(
            json.dumps(
                {
                    "members": [{"agentId": "reviewer@team", "name": "reviewer"}],
                    "id": "1",
                    "subject": "Owned task",
                    "status": "in_progress",
                    "name": "Owned agent",
                }
            )
        )
        leaf = directory / "link.meta.json"
        leaf.symlink_to(metadata)
        alias = self.root / "linked-directory"
        alias.symlink_to(directory, target_is_directory=True)
        for path in (metadata, leaf, alias / metadata.name):
            self.assertTrue(self._store_reader(str(path), claude.load_team_members, "teams"))
            tasks = self._store_reader(str(path), claude.load_tasks, "tasks")
            self.assertEqual("Owned task", next(iter(tasks.values()))[0]["subject"])
            self.assertEqual(
                "Owned agent", claude.agent_label(str(path).removesuffix(".meta.json") + ".jsonl")
            )
        pi_target = directory / "pi.jsonl"
        pi_target.write_text(
            json.dumps({"type": "session", "version": 3, "id": UUID, "cwd": "/work/project"})
            + "\n"
            + json.dumps(
                {
                    "type": "message",
                    "id": "m1",
                    "parentId": None,
                    "timestamp": "2026-11-15T00:00:00Z",
                    "message": {"role": "user", "content": "Owned Pi prompt"},
                }
            )
            + "\n"
        )
        pi_link = directory / "pi-link.jsonl"
        pi_link.symlink_to(pi_target)
        expected = pi.scan_pi_session(self.config, self.state, str(pi_target))
        self.assertTrue(expected)
        for path in (pi_link, alias / pi_target.name):
            self.assertEqual(expected, pi.scan_pi_session(self.config, self.state, str(path)))
            self.assertEqual(
                pi_target.stat().st_size,
                pi._complete_end(self.config, str(path), pi_target.stat().st_size),
            )

    @unittest.skipIf(os.name == "nt", "POSIX ownership and FIFO swaps")
    def test_foreign_link_targets_and_raced_substitutions_refuse(self) -> None:
        target = self.root / "private.jsonl"
        target.write_text('{"private":"secret"}\n')
        link = self.root / "link.jsonl"
        link.symlink_to(target)
        original = os.fstat
        for inode in (target.stat().st_ino, self.root.stat().st_ino):

            def foreign(fd: int, inode: int = inode) -> os.stat_result:
                info = original(fd)
                if info.st_ino == inode:
                    values = list(info)
                    values[4] = os.getuid() + 1
                    return os.stat_result(values)
                return info

            with self.subTest(inode=inode), mock.patch.object(os, "fstat", side_effect=foreign):
                self.assertEqual([], runtime_io.read_tail(self.config, str(target)))
                self.assertEqual([], runtime_io.read_tail(self.config, str(link)))
                for name, call in self.harness_readers(str(link)).items():
                    with self.subTest(reader=name):
                        result = self._quick(call, target)
                        self.assertNotIn("secret", repr(result))
        original_open = os.open

        def swap(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            if os.fspath(path) in (str(target), target.name) and target.is_file():
                target.unlink()
                os.mkfifo(target)
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(os, "open", side_effect=swap):
            self.assertEqual(
                [], self._quick(lambda: runtime_io.read_tail(self.config, str(target)), target)
            )

    @unittest.skipIf(os.name == "nt", "POSIX ownership")
    def test_memo_writer_refuses_foreign_target(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        copies = [
            repo / "compass/skills/compass/notify_hook.py",
            repo / "compass-gemini/hooks/notify_hook.py",
            repo / "compass-droid/hooks/notify_hook.py",
        ]
        target = self.root / "memo.json"
        target.write_text("old memo")
        original = os.stat

        def foreign(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            info = original(path, *args, **kwargs)
            if os.fspath(path) in (str(target), target.name):
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info

        for source in copies:
            spec = importlib.util.spec_from_file_location("memo_copy", source)
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with (
                self.subTest(copy=source),
                mock.patch.object(os, "stat", side_effect=foreign),
                self.assertRaises(OSError),
            ):
                module.write_owner_json(str(target), {"new": "memo"})
            self.assertEqual("old memo", target.read_text())
            self.assertEqual([target], list(self.root.iterdir()))

    @unittest.skipIf(os.name == "nt", "POSIX modes and uid")
    def test_existing_log_tightens_mode_and_refuses_foreign_owner(self) -> None:
        path = self.root / "daemon.log"
        path.write_bytes(b"old")
        path.chmod(0o644)
        with runtime_io.open_owner_append(str(path)) as log:
            log.write(b" new")
        self.assertEqual(b"old new", path.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        path.chmod(0o644)
        inode = path.stat().st_ino
        original = os.fstat

        def foreign(fd: int) -> os.stat_result:
            info = original(fd)
            if info.st_ino == inode:
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info

        with (
            mock.patch.object(os, "fstat", side_effect=foreign),
            self.assertRaises(OSError),
            runtime_io.open_owner_append(str(path)) as log,
        ):
            log.write(b" bad")
        self.assertEqual(b"old new", path.read_bytes())
        self.assertEqual(0o644, stat.S_IMODE(path.stat().st_mode))

    @unittest.skipIf(os.name == "nt", "POSIX ownership")
    def test_atomic_write_refuses_foreign_target(self) -> None:
        target = self.root / "state.json"
        target.write_text("keep")
        original = os.stat

        def foreign(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            info = original(path, *args, **kwargs)
            if os.fspath(path) in (str(target), target.name):
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info

        with mock.patch.object(os, "stat", side_effect=foreign), self.assertRaises(OSError):
            runtime_io.atomic_write_owner_only(str(target), "bad")
        self.assertEqual("keep", target.read_text())
        self.assertEqual([target], list(self.root.iterdir()))

    def test_memo_read_refuses_invalid_uuid_symlink_and_fifo(self) -> None:
        with mock.patch.dict(os.environ, {"COMPASS_HOME": str(self.root)}):
            invalid = self.root / "statusline-antigravity-invalid.json"
            invalid.write_text('{"private":true}')
            self.assertEqual({}, statusline_hook.read_memo("invalid"))
            path = self.root / f"statusline-antigravity-{UUID}.json"
            path.symlink_to(invalid)
            self.assertEqual({}, statusline_hook.read_memo(UUID))
            path.unlink()
            if hasattr(os, "mkfifo"):
                os.mkfifo(path)
                self.assertEqual({}, self._quick(lambda: statusline_hook.read_memo(UUID), path))

    @unittest.skipIf(os.name == "nt", "POSIX ownership")
    def test_antigravity_sqlite_refuses_foreign_source(self) -> None:
        path = self.root / "steps.db"
        now = time.time()
        metadata = protobuf_bytes_field(
            1, protobuf_int_field(1, int(now) - 1)
        ) + protobuf_bytes_field(31, b"private action")
        with runtime_io.sqlite_module.connect(path) as db:
            db.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, metadata BLOB)")
            db.execute("INSERT INTO steps VALUES (1, 15, ?)", (metadata,))
        self.assertEqual(
            "private action",
            antigravity._step_activity(self.config, self.state, str(path), now)["last_tool_action"],
        )
        inode = path.stat().st_ino
        original = os.fstat

        def foreign(fd: int) -> os.stat_result:
            info = original(fd)
            if info.st_ino == inode:
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info

        with mock.patch.object(os, "fstat", side_effect=foreign):
            result = antigravity._step_activity(self.config, self.state, str(path), now)
        self.assertEqual("", result["last_tool_action"])
        self.assertIn(str(path), self.state.store_errors)

    def test_state_writer_refuses_link_below_configured_root(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        home = self.root / "home"
        home.mkdir()
        config = dataclasses.replace(self.config, state_home=str(home), state_dir=home)
        # Observer sidecars use a nested directory inside the configured root.
        path = observer.sidecar_path(config, "claude", UUID)
        assert path is not None
        Path(path).parent.symlink_to(outside, target_is_directory=True)
        self.assertIsNone(observer.write_sidecar(config, "claude", UUID, {"private": "words"}))
        self.assertEqual([], list(outside.iterdir()))

    @unittest.skipIf(os.name == "nt", "POSIX modes")
    def test_root_creation_leaves_linked_existing_ancestors_unchanged(self) -> None:
        ancestor = self.root / "ancestor"
        ancestor.mkdir(mode=0o755)
        ancestor.chmod(0o755)
        alias = self.root / "alias"
        alias.symlink_to(ancestor, target_is_directory=True)
        runtime_io.ensure_owner_dir(str(alias / "home"))
        self.assertEqual(0o755, stat.S_IMODE(ancestor.stat().st_mode))
        self.assertEqual(0o700, stat.S_IMODE((ancestor / "home").stat().st_mode))

    @unittest.skipIf(os.name == "nt", "POSIX ownership and directory swaps")
    def test_raced_foreign_directory_is_never_chmodded(self) -> None:
        foreign = self.root / "foreign"
        foreign.mkdir()
        foreign.chmod(0o755)
        inode = foreign.stat().st_ino
        parent = self.root / "home"
        parent.mkdir()
        target = parent / "new"
        original_open, original_stat = os.open, os.fstat

        def swap(path: Any, *args: Any, **kwargs: Any) -> int:
            if path == "new" and target.exists() and foreign.exists():
                target.rmdir()
                foreign.rename(target)
            return original_open(path, *args, **kwargs)

        def foreign_stat(fd: int) -> os.stat_result:
            info = original_stat(fd)
            if info.st_ino == inode:
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info

        with (
            mock.patch.object(os, "open", side_effect=swap),
            mock.patch.object(os, "fstat", side_effect=foreign_stat),
            self.assertRaises(OSError),
        ):
            runtime_io.ensure_owner_dir(str(target))
        self.assertEqual(0o755, stat.S_IMODE(target.stat().st_mode))

    @unittest.skipIf(os.name == "nt", "POSIX root ownership and permissions")
    def test_configured_harness_root_is_owned_and_private(self) -> None:
        store = self.root / "store"
        store.mkdir()
        store.chmod(0o755)
        (store / "session.jsonl").write_text("{}\n")
        alias = self.root / "store-link"
        alias.symlink_to(store, target_is_directory=True)
        config = dataclasses.replace(self.config, store_roots={"claude.projects": (str(alias),)})
        self.assertEqual(
            [str(alias / "session.jsonl")],
            runtime_io.glob_stores(config, "claude.projects", "*.jsonl"),
        )
        self.assertEqual(0o700, stat.S_IMODE(store.stat().st_mode))
        store.chmod(0o755)
        with mock.patch.object(os, "getuid", return_value=os.getuid() + 1):
            self.assertEqual([], runtime_io.glob_stores(config, "claude.projects", "*.jsonl"))
        self.assertEqual(0o755, stat.S_IMODE(store.stat().st_mode))

    def test_model_outputs_remain_readable_under_an_owned_linked_home(self) -> None:
        target = self.root / "model-home"
        target.mkdir()
        home = self.root / "linked-model-home"
        home.symlink_to(target, target_is_directory=True)
        config = dataclasses.replace(self.config, state_home=str(home), state_dir=home)

        def codex(command: list[str], **_options: Any) -> Any:
            Path(command[command.index("--output-last-message") + 1]).write_text("owned answer")
            return subprocess.CompletedProcess(command, 0)

        def claude(command: list[str], **options: Any) -> Any:
            options["stdout"].write(b"owned answer")
            return subprocess.CompletedProcess(command, 0)

        self.assertEqual(
            ("owned answer", "ok"),
            observer.codex_exec(
                config,
                "test prompt",
                output_cap_bytes=128,
                runner=codex,
                binary_resolver=lambda _: "/usr/bin/codex",
            ),
        )
        with observer.prepare_claude_exec(
            config, runner=claude, binary_resolver=lambda _: "/usr/bin/claude"
        ) as prepared:
            self.assertEqual(("owned answer", "ok"), prepared("test prompt", output_cap_bytes=128))

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
    def test_strict_state_readers_refuse_leaf_symlinks(self) -> None:
        target = self.root / "real"
        target.write_text('{"private":true}\n')
        path = self.root / "link"
        path.symlink_to(target)
        for index, call in enumerate(
            [
                lambda: runtime_io.open_regular(path),
                lambda: runtime_io.read_prefix_bytes(str(path), max_bytes=64),
                lambda: spacedock.open_regular(str(path)),
            ]
        ):
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

        def publish(src: str, dst: str, **options: Any) -> None:
            barrier.wait(timeout=10)
            replace(src, dst, **options)

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

    def test_sqlite_goal_reader_follows_an_owned_leaf_symlink(self) -> None:
        sqlite = runtime_io.sqlite_module
        target = self.root / "real.db"
        with sqlite.connect(target) as db:
            db.execute(
                "CREATE TABLE thread_goals (thread_id, objective, created_at_ms, updated_at_ms, status)"
            )
            db.execute("INSERT INTO thread_goals VALUES ('id', 'private goal', 1, 2, 'complete')")
        link = self.root / "link.db"
        link.symlink_to(target)
        self.assertEqual(
            claude_data._read_codex_goals(str(target)), claude_data._read_codex_goals(str(link))
        )

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
