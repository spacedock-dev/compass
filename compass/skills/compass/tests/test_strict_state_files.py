"""Compass state must never borrow another file's identity or wait on a pipe."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

from compass_runtime import annotations as runtime_annotations
from compass_runtime import (
    copied_corrections,
    deliveries,
    departures,
    dismissals,
    ends,
    history,
    interaction_prototype,
    monitor_store,
    observer,
    reading_jobs,
    reading_long_markers,
    semantic_history,
    settings,
    summary_jobs,
    summary_store,
    tripwires,
    typed_press,
)

from . import test_reading_long_markers as marker_tests
from .support import make_config
from .test_security_primitives import NON_STATE_READ_GAPS, RAW_FILES

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class StrictStateFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = make_config(state_home=str(self.root), state_dir=self.root)

    @contextlib.contextmanager
    def planted(self, path: Path, kind: str) -> Iterator[None]:
        content = path.read_bytes()
        target = path.with_name(path.name + ".original")
        path.rename(target)
        try:
            if kind == "symlink":
                path.symlink_to(target)
            elif kind == "fifo":
                os.mkfifo(path)
            else:
                path.write_bytes(content)
            if kind == "foreign":
                inode = path.stat().st_ino
                original = os.fstat

                def foreign(fd: int) -> os.stat_result:
                    info = original(fd)
                    if info.st_ino == inode:
                        fields = list(info)
                        fields[4] = os.getuid() + 1
                        return os.stat_result(fields)
                    return info

                original_stat = os.stat

                def foreign_stat(*args: Any, **kwargs: Any) -> os.stat_result:
                    info = original_stat(*args, **kwargs)
                    if info.st_ino == inode:
                        fields = list(info)
                        fields[4] = os.getuid() + 1
                        return os.stat_result(fields)
                    return info

                with (
                    mock.patch.object(os, "fstat", side_effect=foreign),
                    mock.patch.object(os, "stat", side_effect=foreign_stat),
                ):
                    yield
            else:
                yield
        finally:
            path.unlink(missing_ok=True)
            target.rename(path)

    def readers(self) -> list[tuple[Path, Any, Callable[[], Any], Any]]:
        config = self.config
        row = {"harness": "claude", "sid": "abcdefgh", "at": 100, "lane": "ask"}
        envelope = {"entries": [row]}
        store = monitor_store.Store(str(self.root), "abcdefgh")
        cases: list[tuple[Path, Any, Callable[[], Any], Any]] = [
            (
                Path(runtime_annotations.store_path(config)),
                {"entries": []},
                lambda: runtime_annotations._read_store(config).trusted,
                False,
            ),
            (
                Path(cast("str", observer.sidecar_path(config, "claude", "abcdefgh"))),
                {"goal": "own goal"},
                lambda: observer.read_sidecar(config, "claude", "abcdefgh"),
                None,
            ),
            (
                Path(settings.store_path(config)),
                {"analyze_record_events": 300},
                lambda: settings.load(config),
                settings.DEFAULTS,
            ),
            (
                Path(settings.store_path(config)),
                {"no_update_check": False},
                lambda: settings.no_update_check(config),
                True,
            ),
            (Path(deliveries.store_path(config)), envelope, lambda: deliveries.load(config), ()),
            (Path(departures.store_path(config)), envelope, lambda: departures.load(config), ()),
            (Path(ends.store_path(config)), envelope, lambda: ends.load(config), ()),
            (Path(dismissals.store_path(config)), envelope, lambda: dismissals.load(config), ()),
            (
                Path(history.store_path(config)),
                {"v": history.SCHEMA_VERSION, "entries": []},
                lambda: history.load(config)[1],
                history.RESET_UNREADABLE,
            ),
            (
                Path(semantic_history.store_path(config)),
                {"v": 1, "projects": {"own": {}}},
                lambda: semantic_history._read(config),
                {"v": semantic_history.SCHEMA_VERSION, "projects": {}},
            ),
            (
                Path(summary_store.store_path(config)),
                {"v": summary_store.SCHEMA_VERSION, "entries": []},
                lambda: summary_store.load(config).state,
                "unavailable",
            ),
            (
                Path(copied_corrections.store_path(config)),
                {
                    "entries": [
                        {
                            **row,
                            "copies": [],
                            "matches": [
                                {"fact_id": "fact:" + "a" * 16, "at": 100, "copied_at": 90}
                            ],
                        }
                    ]
                },
                lambda: copied_corrections._read(config),
                {},
            ),
            (
                Path(tripwires.store_path(config)),
                {"v": 1, "rules": []},
                lambda: tripwires.load(config),
                None,
            ),
            (
                typed_press.store_path(config),
                {"consumed": ["own"], "consumed_at": {"own": 100}},
                lambda: typed_press._consumed(typed_press.store_path(config)),
                None,
            ),
            (store.path("control"), {"resume_id": "own"}, lambda: store.read("control"), {}),
            (
                self.root / "reading-jobs" / "holder.json",
                {"pid": 123},
                lambda: reading_jobs._holder(self.root / "reading-jobs" / "holder.json", ""),
                0,
            ),
            (
                self.root / "summary-jobs" / "eligible.json",
                {"reason": "own-reason"},
                lambda: summary_jobs._eligible(
                    SimpleNamespace(config=config),
                    cast("Any", SimpleNamespace(harness="claude", sid="abcdefgh")),
                ),
                OSError,
            ),
        ]
        return cases

    def check_readers(self, kind: str) -> None:
        for path, payload, read, refused in self.readers():
            with self.subTest(reader=path.name, kind=kind):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload))
                with mock.patch.object(summary_jobs, "_marker", return_value=path):
                    self.assertNotEqual(refused, read(), "the owned positive control must load")
                    with self.planted(path, kind):
                        if refused is OSError:
                            with self.assertRaises(OSError):
                                read()
                        else:
                            self.assertEqual(refused, read())

    @unittest.skipIf(os.name == "nt", "POSIX symlinks")
    def test_the_board_refuses_linked_state_in_every_remaining_store(self) -> None:
        self.check_readers("symlink")

    @unittest.skipIf(os.name == "nt", "POSIX UID")
    def test_the_board_refuses_another_users_state_in_every_remaining_store(self) -> None:
        self.check_readers("foreign")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO")
    def test_the_board_never_waits_for_a_planted_state_pipe(self) -> None:
        # A child bounds the test even if the production nonblocking flag is removed.
        try:
            result = subprocess.run(
                [sys.executable, "-m", "unittest", __name__ + ".StrictStateFilesTest.pipe_readers"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("a state reader blocked on the planted pipe")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def pipe_readers(self) -> None:
        self.check_readers("fifo")
        self.check_long_marker("fifo")

    @unittest.skipIf(os.name == "nt", "POSIX UID and symlinks")
    def test_long_reading_markers_refuse_links_pipes_and_another_users_file(self) -> None:
        for kind in ("symlink", "foreign"):
            with self.subTest(kind=kind):
                self.check_long_marker(kind)

    def check_long_marker(self, kind: str) -> None:
        fixture = marker_tests.LongMarkerTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        owner = fixture.begin()
        self.assertIsNotNone(owner)
        path = fixture.path(owner)
        self.assertIsNotNone(fixture.loaded(owner))
        with self.planted(path, kind):
            self.assertIsNone(fixture.loaded(owner))

    @unittest.skipIf(os.name == "nt", "POSIX UID")
    def test_another_users_settings_directory_cannot_set_limits_or_allow_update_checks(
        self,
    ) -> None:
        settings.save(self.config, {"analyze_record_events": 300})
        self.assertEqual(300, settings.load(self.config).analyze_record_events)
        self.assertFalse(settings.no_update_check(self.config))
        original = os.fstat
        inode = self.root.stat().st_ino

        def foreign_directory(fd: int) -> os.stat_result:
            info = original(fd)
            if info.st_ino == inode:
                fields = list(info)
                fields[4] = os.getuid() + 1
                return os.stat_result(fields)
            return info

        with mock.patch.object(os, "fstat", side_effect=foreign_directory):
            self.assertEqual(settings.DEFAULTS, settings.load(self.config))
            self.assertTrue(settings.no_update_check(self.config))

    def test_no_compass_written_state_reader_keeps_a_raw_read_exemption(self) -> None:
        self.assertEqual(
            [],
            [
                key
                for key, (_, reason) in RAW_FILES.items()
                if reason.startswith("KNOWN GAP") and key not in NON_STATE_READ_GAPS
            ],
        )

    def test_publishers_leave_unsafe_existing_targets_in_place(self) -> None:
        fixture = marker_tests.LongMarkerTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        owner = fixture.begin()
        self.assertIsNotNone(owner)
        marker_path = fixture.path(owner)
        marker = fixture.loaded(owner)
        store = monitor_store.Store(str(self.root), "abcdefgh")
        registration = self.root / "registration.json"
        prototype = interaction_prototype.InteractionPrototype(
            mock.Mock(),
            registration_file=registration,
        )
        client_path = self.root / "client.json"
        adapter = object.__new__(interaction_prototype.TmuxAdapter)
        adapter._origin = None
        adapter._client_config = client_path
        publishers: list[tuple[Path, Callable[[], Any]]] = [
            (Path(tripwires.store_path(self.config)), lambda: tripwires.save(self.config, {})),
            (store.path("control"), lambda: store.write("control", {"own": True})),
            (marker_path, lambda: reading_long_markers._write(marker_path, marker)),
            (registration, lambda: prototype._write_registration_file(8081)),
            (
                client_path,
                lambda: adapter.start_client(8081, "synthetic", "session", 1, cast("Any", None)),
            ),
        ]
        for path, publish in publishers:
            for kind in ("symlink", "fifo", "foreign"):
                if os.name == "nt":
                    continue
                with self.subTest(publisher=path.name, kind=kind):
                    path.write_text('{"original":true}')
                    with self.planted(path, kind):
                        before = path.lstat()
                        with contextlib.suppress(
                            OSError, interaction_prototype.OriginUnavailableError
                        ):
                            self.assertIsNot(publish(), True)
                        self.assertEqual(before.st_ino, path.lstat().st_ino)
                        self.assertEqual(before.st_mode, path.lstat().st_mode)
                    self.assertEqual('{"original":true}', path.read_text())

    @unittest.skipIf(os.name == "nt", "POSIX owner and special file checks")
    def test_a_monitor_never_takes_an_unsafe_control_lock(self) -> None:
        store = monitor_store.Store(str(self.root), "abcdefgh")
        path = store.path("life.lock")
        path.write_bytes(b"")
        for kind in ("symlink", "fifo", "foreign"):
            with self.subTest(kind=kind), self.planted(path, kind):
                try:
                    with store.lock("life") as held:
                        self.assertFalse(held)
                except OSError:
                    pass

    @unittest.skipIf(os.name == "nt", "POSIX symlinks")
    def test_a_monitor_lock_refuses_a_linked_state_subdirectory(self) -> None:
        store = monitor_store.Store(str(self.root), "abcdefgh")
        outside = self.root / "outside"
        outside.mkdir()
        target = outside / store.path("life.lock").name
        target.write_bytes(b"")
        before = target.stat().st_mode
        store.root.rmdir()
        store.root.symlink_to(outside, target_is_directory=True)
        try:
            with store.lock("life") as held:
                self.assertFalse(held)
        except OSError:
            pass
        self.assertEqual(before, target.stat().st_mode)
