"""The coarse probe's mutation corpus and its cost budget.

This module is the Phase 2 coarse-probe gate from
`docs/design-event-driven-observation.md`. The gate says: do not use the
probe to reduce scans until its mutation corpus has no false negatives on
supported local filesystems, and its cost passes on all three OSes.

Every case below is a real filesystem mutation performed against a real
temporary store, not a mocked stat. The one documented false negative has its own
test asserting it is still exactly that, so widening or narrowing the watched set
cannot change it silently.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from compass_runtime import probe as runtime_probe

from . import support


def _touch(path: Path, text: str = "{}\n") -> None:
    path.write_text(text, encoding="utf-8")


def _advance_mtime(path: Path, *, seconds: float = 2.0) -> None:
    """Move a path's mtime forward explicitly.

    Never sleep for it. A coarse filesystem timestamp (HFS+ and ext4 are
    one-second, some network stores worse) makes a real write inside one tick
    invisible to mtime, so a test that relied on wall-clock timing would pass or
    fail on machine speed rather than on behaviour.
    """
    stamp = time.time() + seconds
    os.utime(path, (stamp, stamp))


class ProbeMutationCorpusTest(support.RuntimeTestCase):
    """Each mutation a harness actually performs, and whether the probe sees it."""

    def setUp(self) -> None:
        super().setUp()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.project = self.root / "project-a"
        self.project.mkdir()
        self.transcript = self.project / "session.jsonl"
        _touch(self.transcript)
        support.STORE_OVERRIDES["claude.projects"] = str(self.root)
        self.config, _state = support.runtime()
        # The override is keyed by resolved store key, not by the fixture's
        # constant name. Getting that wrong silently points the whole corpus at
        # the developer's real store, where every case passes for the wrong
        # reason, so assert the redirect took.
        self.assertEqual((str(self.root),), self.config.store_roots["claude.projects"])

    def _stamp(self, *, tracked: tuple[str, ...] = ()) -> runtime_probe.Stamp:
        return runtime_probe.stamp(self.config, tracked=tracked)

    def _detects(self, mutate: object, *, tracked: tuple[str, ...] = ()) -> bool:
        before = self._stamp(tracked=tracked)
        assert callable(mutate)
        mutate()
        return runtime_probe.changed(before, self._stamp(tracked=tracked))

    def test_a_first_probe_reports_change_so_a_cold_start_collects(self) -> None:
        self.assertTrue(runtime_probe.changed(None, self._stamp()))

    def test_an_unchanged_store_reports_no_change(self) -> None:
        """The property the whole idea rests on: quiet is cheap and quiet."""
        tracked = (str(self.transcript),)
        self.assertFalse(self._detects(lambda: None, tracked=tracked))

    def test_an_append_to_a_tracked_transcript_is_detected(self) -> None:
        """The event that matters most, and the one a directory-only probe misses.

        Appending to a file changes no directory's mtime on any supported
        filesystem, so this case is the entire reason the probe stats files.
        """

        def append() -> None:
            with self.transcript.open("a", encoding="utf-8") as handle:
                handle.write('{"more": 1}\n')
            _advance_mtime(self.transcript)

        self.assertTrue(self._detects(append, tracked=(str(self.transcript),)))

    def test_an_append_inside_one_filesystem_tick_is_still_detected(self) -> None:
        """Size carries the change when a coarse mtime does not.

        Pinning mtime back to its old value is exactly what a one-second
        filesystem reports for two writes in the same second.
        """
        tracked = (str(self.transcript),)
        before_stat = self.transcript.stat()

        def append_without_moving_mtime() -> None:
            with self.transcript.open("a", encoding="utf-8") as handle:
                handle.write('{"same-tick": 1}\n')
            os.utime(self.transcript, (before_stat.st_atime, before_stat.st_mtime))

        self.assertTrue(self._detects(append_without_moving_mtime, tracked=tracked))

    def test_a_new_session_file_in_a_known_project_is_detected(self) -> None:
        def add_session() -> None:
            _touch(self.project / "second.jsonl")
            _advance_mtime(self.project)

        self.assertTrue(self._detects(add_session))

    def test_a_new_project_directory_is_detected(self) -> None:
        def add_project() -> None:
            (self.root / "project-b").mkdir()
            _advance_mtime(self.root)

        self.assertTrue(self._detects(add_project))

    def test_a_deleted_tracked_transcript_is_detected(self) -> None:
        """Absence stamps as a sentinel, so vanishing is a change like any other."""
        self.assertTrue(
            self._detects(self.transcript.unlink, tracked=(str(self.transcript),)),
        )

    def test_a_renamed_transcript_is_detected(self) -> None:
        def rename() -> None:
            self.transcript.rename(self.project / "renamed.jsonl")
            _advance_mtime(self.project)

        self.assertTrue(self._detects(rename, tracked=(str(self.transcript),)))

    def test_a_sqlite_write_that_lands_only_in_the_wal_is_detected(self) -> None:
        """The case a database-only stamp misses.

        A busy harness in WAL mode leaves the database file untouched for many
        writes, so the companions are stamped with it.
        """
        database = self.project / "store.db"
        connection = sqlite3.connect(database)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE t (a INTEGER)")
        connection.commit()
        tracked = (str(database),)
        before = self._stamp(tracked=tracked)
        connection.execute("INSERT INTO t VALUES (1)")
        connection.commit()
        after = self._stamp(tracked=tracked)
        connection.close()
        self.assertTrue(runtime_probe.changed(before, after))

    def test_the_wal_and_shm_companions_are_watched_for_a_tracked_database(self) -> None:
        database = str(self.project / "store.db")
        watched = runtime_probe.watched_paths(self.config, tracked=(database,))
        self.assertIn(database + "-wal", watched)
        self.assertIn(database + "-shm", watched)

    def test_a_companion_is_not_invented_for_a_non_database_path(self) -> None:
        watched = runtime_probe.watched_paths(self.config, tracked=(str(self.transcript),))
        self.assertNotIn(str(self.transcript) + "-wal", watched)

    def test_an_unreadable_store_root_does_not_raise(self) -> None:
        """A permission error must degrade to "no signal", never to a crash."""
        support.STORE_OVERRIDES["claude.projects"] = str(self.root / "does-not-exist")
        config, _state = support.runtime()
        self.assertIsInstance(runtime_probe.stamp(config), dict)

    def test_the_documented_false_negative_is_still_exactly_that(self) -> None:
        """An untracked session waking up is invisible, and that is deliberate.

        A session older than the activity window becomes active again: its
        transcript's mtime moves, but it is not tracked and appending changed no
        directory. Widening the watched set to cover it means statting every
        historical transcript, which on a real machine is tens of thousands of
        files and costs more than the collection the probe exists to avoid.

        This test exists so that trade cannot be changed by accident. If it ever
        starts failing, the watched set grew, and the cost budget below is the
        thing to re-measure before celebrating.
        """
        untracked = self.project / "older.jsonl"
        _touch(untracked)
        _advance_mtime(self.project)
        # Nothing is tracked, and the directory stamp is already current.
        before = self._stamp()

        with untracked.open("a", encoding="utf-8") as handle:
            handle.write('{"woke": 1}\n')
        _advance_mtime(untracked)

        self.assertFalse(
            runtime_probe.changed(before, self._stamp()),
            "if this now passes, the watched set changed: re-measure the budget",
        )
        # And the same mutation IS caught once the session is tracked, which is
        # what reconciliation buys by feeding the tracked set back in.
        tracked = (str(untracked),)
        before_tracked = self._stamp(tracked=tracked)
        with untracked.open("a", encoding="utf-8") as handle:
            handle.write('{"woke": 2}\n')
        _advance_mtime(untracked, seconds=4.0)
        self.assertTrue(runtime_probe.changed(before_tracked, self._stamp(tracked=tracked)))


class ProbeCostBudgetTest(support.RuntimeTestCase):
    """The other half of the gate: the probe has to be cheap enough to be free.

    Asserted as a per-path budget rather than a total, so the threshold means the
    same thing on a fast laptop and a slow CI runner, and so it does not silently
    pass by walking fewer paths than it should.
    """

    # Generous by two orders of magnitude against the measured 0.14 ms for 97
    # paths (about 1.4 microseconds per path). A regression that made the probe
    # glob or read would blow through this; ordinary machine variance will not.
    # It is CPU time, so a runner busy with other work does not stretch it.
    MAX_MICROSECONDS_PER_PATH = 150.0

    def test_the_probe_walks_a_bounded_set_and_stats_it_cheaply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 60 projects, each with 40 files: the shape of a real store, where
            # the file count dwarfs the directory count.
            for index in range(60):
                project = root / f"project-{index}"
                project.mkdir()
                for file_index in range(40):
                    _touch(project / f"session-{file_index}.jsonl")
            support.STORE_OVERRIDES["claude.projects"] = str(root)
            config, _state = support.runtime()
            self.assertEqual((str(root),), config.store_roots["claude.projects"])

            paths = runtime_probe.watched_paths(config)
            started = time.process_time()
            for _ in range(5):
                runtime_probe.stamp(config)
            elapsed = (time.process_time() - started) / 5
            with (
                mock.patch.object(os, "stat", wraps=os.stat) as stat,
                mock.patch.object(os, "scandir", wraps=os.scandir) as scandir,
            ):
                runtime_probe.stamp(config)
            roots = [path for group in config.store_roots.values() for path in group]

        # The same budget as calls, which no runner's speed can move: one stat per
        # watched path, and a listing of each store root and nothing below it.
        self.assertEqual(len(paths), stat.call_count)
        self.assertEqual(len(roots), scandir.call_count)

        self.assertGreater(len(paths), 60, "the watched set must cover every project")
        self.assertLess(
            len(paths),
            2_400,
            "the probe must not walk into files: 60 projects x 40 files is the trap",
        )
        per_path = (elapsed / len(paths)) * 1_000_000
        self.assertLess(
            per_path,
            self.MAX_MICROSECONDS_PER_PATH,
            f"{per_path:.1f} microseconds per path over {len(paths)} paths",
        )


if __name__ == "__main__":
    unittest.main()
