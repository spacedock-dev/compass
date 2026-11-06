"""An observed session end survives a restart of the board that observed it.

DRC-4547. The end mark lived only in the coordinator's memory, so a restart
turned every finished session back into one that merely went quiet: three
Claude sessions that published `session end observed` came back as `no end
observed`, and the final reading DEC-15 permits on an ended session could never
be taken on any of them. Nothing here invents an end. A store carrying no end
for a session is read as no end, and a stored end loses to transcript activity
later than the end plus the activity grace.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import aggregate, ends, observation, reading
from compass_runtime import annotations as annotation_store
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from . import support
from .test_history import (
    isolated_environment,
    no_instance,
    run_one_shot_cli,
    seed_claude_transcript,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from compass_runtime.config import RuntimeConfig

SESSION = "abcdef12-3456-7890-abcd-ef1234567890"
PREFIX = "abcdef12"
SECOND = "beefcafe-3456-7890-abcd-ef1234567890"
SECOND_PREFIX = "beefcafe"
# The end, and the board's clock. Well inside the display window, so the row is
# still produced from the transcript after the restart.
END_AT = support.SERVER_STARTED - 600
NOW = support.SERVER_STARTED


def _config(root: Path) -> Any:
    return build_runtime_config(
        environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
        platform_name="linux",
        os_name="posix",
        launcher_path=root / "server.py",
    )


class TheEndSurvivesARestartTest(unittest.TestCase):
    """The store contract: stored values, not sentences."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))
        self.quiet = lambda _line: None

    def test_a_recorded_end_is_read_back_by_a_fresh_load(self) -> None:
        self.assertTrue(
            ends.record(
                self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=self.quiet
            )
        )
        loaded = ends.load(self.config)
        self.assertEqual(1, len(loaded))
        self.assertEqual(
            ("claude", PREFIX, 100.0), (loaded[0]["harness"], loaded[0]["sid"], loaded[0]["at"])
        )
        self.assertEqual({("claude", PREFIX): 100.0}, ends.restored(loaded))

    def test_a_redelivered_older_end_does_not_pull_the_stamp_backwards(self) -> None:
        # `observation._mark_ended`'s max rule, kept on disk as well: delivery is
        # at-least-once and possibly reordered.
        ends.record(self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=self.quiet)
        ends.record(self.config, harness="claude", sid=PREFIX, at=90.0, diagnostic_sink=self.quiet)
        self.assertEqual({("claude", PREFIX): 100.0}, ends.restored(ends.load(self.config)))
        self.assertEqual(1, len(ends.load(self.config)), "one record per session id")

    def test_a_lifted_end_is_gone_from_disk(self) -> None:
        ends.record(self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=self.quiet)
        ends.record(self.config, harness="codex", sid="other", at=101.0, diagnostic_sink=self.quiet)
        self.assertTrue(
            ends.lift(self.config, harness="claude", sid=PREFIX, diagnostic_sink=self.quiet)
        )
        self.assertEqual({("codex", "other"): 101.0}, ends.restored(ends.load(self.config)))

    def test_lifting_an_end_that_was_never_recorded_creates_no_file(self) -> None:
        # A `session_started` for a session nothing ever saw end is the common
        # case, and the store must not come into being on it.
        self.assertFalse(
            ends.lift(self.config, harness="claude", sid=PREFIX, diagnostic_sink=self.quiet)
        )
        self.assertFalse(os.path.exists(ends.store_path(self.config)))

    def test_a_zero_or_negative_stamp_is_refused_rather_than_stored(self) -> None:
        self.assertFalse(
            ends.record(
                self.config, harness="claude", sid=PREFIX, at=0.0, diagnostic_sink=self.quiet
            )
        )
        self.assertFalse(
            ends.record(
                self.config, harness="claude", sid=PREFIX, at=-5.0, diagnostic_sink=self.quiet
            )
        )
        self.assertFalse(os.path.exists(ends.store_path(self.config)))

    def test_the_store_lives_beside_the_state_file_and_not_per_port(self) -> None:
        self.assertEqual(
            os.path.join(self.config.state_home, "compass-ends.json"), ends.store_path(self.config)
        )

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_the_file_is_owner_only(self) -> None:
        ends.record(self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=self.quiet)
        mode = stat.S_IMODE(os.stat(ends.store_path(self.config)).st_mode)
        self.assertEqual(0o600, mode)

    def test_the_newest_entries_survive_the_cap(self) -> None:
        config = self.config
        for index in range(5):
            ends.record(
                config,
                harness="claude",
                sid=f"s{index}",
                at=100.0 + index,
                diagnostic_sink=self.quiet,
            )
        capped = ends.load(dataclasses.replace(config, end_max_entries=2))
        self.assertEqual(
            {("claude", "s3"), ("claude", "s4")}, {(e["harness"], e["sid"]) for e in capped}
        )

    def test_forget_deletes_the_store_and_reports_whether_there_was_one(self) -> None:
        self.assertFalse(ends.forget(self.config))
        ends.record(self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=self.quiet)
        self.assertTrue(ends.forget(self.config))
        self.assertFalse(os.path.exists(ends.store_path(self.config)))


class AStoreCarryingNoEndIsNotReadAsOneTest(unittest.TestCase):
    """AC4, the store half: nothing claims an end it did not see."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))
        os.makedirs(self.config.state_home, mode=0o700, exist_ok=True)

    def _write(self, raw: bytes) -> None:
        with open(ends.store_path(self.config), "wb") as handle:
            handle.write(raw)

    def test_garbage_entries_are_dropped_one_at_a_time_and_this_session_has_none(self) -> None:
        self._write(
            json.dumps(
                {
                    "v": ends.SCHEMA_VERSION,
                    "entries": [
                        {"harness": "codex", "sid": "elsewhere", "at": 50.0},
                        {"harness": "claude", "sid": PREFIX, "at": 0},
                        {"harness": "claude", "sid": PREFIX, "at": "yesterday"},
                        ["claude", PREFIX, 100.0],
                        {"harness": "claude", "sid": PREFIX},
                        {"harness": "claude", "sid": PREFIX, "at": True},
                    ],
                }
            ).encode()
        )
        restored = ends.restored(ends.load(self.config))
        self.assertNotIn(("claude", PREFIX), restored)
        self.assertEqual({("codex", "elsewhere"): 50.0}, restored, "the one sound record survives")

    def test_an_over_cap_file_degrades_to_no_ends(self) -> None:
        self._write(b'{"v": 1, "entries": [' + b" " * (self.config.end_read_cap_bytes + 1) + b"]}")
        self.assertEqual((), ends.load(self.config))

    def test_a_truncated_file_degrades_to_no_ends(self) -> None:
        self._write(b'{"v": 1, "entries": [{"harness": "claude", "sid": "' + PREFIX.encode())
        self.assertEqual((), ends.load(self.config))

    def test_a_file_of_the_wrong_shape_degrades_to_no_ends(self) -> None:
        for raw in (b"[]", b"null", b'{"entries": {}}', b'{"v": 1}'):
            with self.subTest(raw=raw):
                self._write(raw)
                self.assertEqual((), ends.load(self.config))

    def test_a_missing_file_is_no_ends_and_is_not_created_by_a_read(self) -> None:
        self.assertEqual((), ends.load(self.config))
        self.assertFalse(os.path.exists(ends.store_path(self.config)))


class ConcurrentWritersKeepEveryEndTest(unittest.TestCase):
    """AC5: the lock and the per-thread temp name, measured rather than read.

    `deliveries` shipped this shape without a lock and lost a record in 60 of 60
    two-writer trials. `session_ended` and `session_started` reach `record` and
    `lift` from `ThreadingHTTPServer` handler threads, one per hook POST, so two
    sessions ending together is the ordinary case rather than a stress test.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))

    def _record(self, n: int) -> None:
        ends.record(
            self.config,
            harness="claude",
            sid=f"s-{n}",
            at=100.0 + n,
            diagnostic_sink=lambda _line: None,
        )

    def test_two_simultaneous_writers_both_land(self) -> None:
        ready = threading.Barrier(2)

        def write(n: int) -> None:
            ready.wait()
            self._record(n)

        threads = [threading.Thread(target=write, args=(n,)) for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(2, len(ends.load(self.config)))

    def test_many_writers_leave_a_store_that_still_parses(self) -> None:
        threads = [threading.Thread(target=self._record, args=(n,)) for n in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        rows = ends.load(self.config)
        self.assertEqual(12, len(rows))
        self.assertEqual(12, len({row["sid"] for row in rows}))

    def test_no_two_records_write_the_store_at_the_same_time(self) -> None:
        depth = 0
        deepest = 0
        real_open = os.open

        def watched(path: str, *args: Any, **kwargs: Any) -> int:
            nonlocal depth, deepest
            if not str(path).endswith(".tmp"):
                return real_open(path, *args, **kwargs)
            depth += 1
            deepest = max(deepest, depth)
            try:
                time.sleep(0.01)
                return real_open(path, *args, **kwargs)
            finally:
                depth -= 1

        with mock.patch.object(os, "open", watched):
            threads = [threading.Thread(target=self._record, args=(n,)) for n in range(6)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(1, deepest, "two writers were inside the store write at once")
        self.assertEqual(6, len(ends.load(self.config)))

    def test_two_concurrent_saves_do_not_share_a_temp_path(self) -> None:
        opened: list[str] = []
        # Generous: two threads reaching one line is immediate on an idle runner, not on a busy one.
        both_open = threading.Barrier(2, timeout=30)
        real_open = os.open

        def watched(path: str, *args: Any, **kwargs: Any) -> int:
            if not str(path).endswith(".tmp"):
                return real_open(path, *args, **kwargs)
            opened.append(str(path))
            handle = real_open(path, *args, **kwargs)
            both_open.wait()
            return handle

        def save(n: int) -> None:
            row: ends.End = {"harness": "claude", "sid": f"s-{n}", "at": float(n + 1)}
            ends.save(self.config, [row], diagnostic_sink=lambda _line: None)

        with mock.patch.object(os, "open", watched):
            threads = [threading.Thread(target=save, args=(n,)) for n in (1, 2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(2, len(opened))
        self.assertEqual(2, len(set(opened)), "two writers shared one temp path")


class _StubApplication:
    """Enough application for a coordinator whose worker is never started."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config


class _DrainWindow:
    """The one interleaving `_flush_end_ops` has to survive, made deterministic.

    `armed` is set by the queue's own emptiness check and consumed by the next
    release of the coordinator's lock, which is the window between the drainer's
    empty check and whatever it does with `_end_flushing` afterwards. `run` is
    the work of the second thread, executed there.
    """

    def __init__(self, run: Callable[[], None]) -> None:
        self.run = run
        self.armed = False
        self.fired = False
        self.drained = 0


class _MarkingDeque(deque[tuple[str, tuple[str, str], float]]):
    """The coordinator's end-op queue, arming the window on its empty check."""

    def __init__(self, window: _DrainWindow) -> None:
        super().__init__()
        self.window = window

    def __bool__(self) -> bool:
        if not len(self) and self.window.drained and not self.window.fired:
            self.window.armed = True
        return bool(len(self))

    def popleft(self) -> tuple[str, tuple[str, str], float]:
        self.window.drained += 1
        return super().popleft()


class _WindowLock:
    """The coordinator's lock, running the second thread's work on one release."""

    def __init__(self, window: _DrainWindow, inner: threading.Lock) -> None:
        self.window = window
        self.inner = inner

    def __enter__(self) -> bool:
        return self.inner.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.inner.release()
        if self.window.armed and not self.window.fired:
            self.window.armed = False
            self.window.fired = True
            self.window.run()


class EveryQueuedEndReachesDiskTest(unittest.TestCase):
    """AC5's other half: the queue between the coordinator and the store.

    `_flush_end_ops` keeps the file write off `_lock` and lets one thread at a
    time drain the queue. The empty check and the clearing of `_end_flushing`
    have to happen under one hold of that lock. While they were two holds, an op
    appended between them was stranded: the thread that appended it found the
    flag still set and returned, and the drainer then cleared the flag with the
    op still in the queue. Nothing drains it until some later unrelated event
    arrives, and `stop` does not drain it either, so a board stopped or
    restarted in that window loses exactly the end this store exists to keep.

    Driven through `submit`, because the defect is in the coordinator's queue
    and every other concurrency case in this module writes to the store
    directly, below it. The interleaving is injected rather than raced: 3,840
    real concurrent submits never hit the window on this machine, since it is a
    handful of bytecodes with no I/O, so a thread race here would pass whether
    or not the defect is present.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _config(Path(self.temp.name))

    @staticmethod
    def _ended(sid: str) -> dict[str, Any]:
        return {"v": 1, "event": "session_ended", "session_id": sid}

    def test_an_end_decided_at_the_drainers_empty_check_still_reaches_disk(self) -> None:
        coordinator = observation.Observation(
            _StubApplication(self.config),  # type: ignore[arg-type]
            clock=lambda: END_AT,
            diagnostic_sink=lambda _line: None,
        )

        def second_end() -> None:
            coordinator.submit("claude", self._ended(SECOND))

        window = _DrainWindow(second_end)
        queue = _MarkingDeque(window)
        with (
            mock.patch.object(coordinator, "_end_ops", queue),
            mock.patch.object(coordinator, "_lock", _WindowLock(window, coordinator._lock)),
        ):
            coordinator.submit("claude", self._ended(SESSION))

        self.assertTrue(window.fired, "the interleaving was never injected")
        self.assertEqual([], list(queue), "an end op was left in the queue")
        self.assertFalse(coordinator._end_flushing)
        self.assertEqual(
            {("claude", PREFIX): END_AT, ("claude", SECOND_PREFIX): END_AT},
            ends.restored(ends.load(self.config)),
        )


class ColdSource:
    """A coordinator that started after the end: it remembers nothing.

    Every reading absent, on the shape of the eleven stubs in
    `test_observation`, so what reaches the row can only have come from disk.
    """

    def overlays_for(self, harness: str, sid: str) -> list[Any]:
        del harness, sid
        return []

    def finished_at(self, harness: str, sid: str) -> float:
        del harness, sid
        return 0.0

    def ended_at(self, harness: str, sid: str) -> float:
        del harness, sid
        return 0.0

    def git_for(self, harness: str, sid: str) -> None:
        del harness, sid

    def focusable(self, harness: str, sid: str) -> bool:
        del harness, sid
        return False

    def note_rows(self, keys: set[tuple[str, str]]) -> None:
        pass

    def command_reports(self) -> list[dict[str, Any]]:
        return []

    def drop_counters(self) -> dict[str, int]:
        return {}


class LiveEndSource(ColdSource):
    """The coordinator that saw the end itself, still running."""

    def ended_at(self, harness: str, sid: str) -> float:
        return END_AT if (harness, sid) == ("claude", PREFIX) else 0.0


class ColdRowTestCase(support.RuntimeTestCase):
    """One quiet Claude session on a redirected store, over a redirected state home.

    Shaped on `test_observation.ApplicationOverlayTest._seeded`, plus the state
    home redirect that suite does not need: the store under test lives beside
    the state file, and reading the developer's own would make every assertion
    here about their board rather than the code.
    """

    @contextlib.contextmanager
    def _board(
        self, *, last_activity: float = END_AT - 100
    ) -> Iterator[tuple[aggregate.Application, RuntimeConfig]]:
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = projects / "-w-proj"
            project.mkdir(parents=True)
            transcript = project / f"{SESSION}.jsonl"
            transcript.write_text(json.dumps({"type": "user", "uuid": "u"}) + "\n")
            os.utime(transcript, (last_activity, last_activity))
            with (
                mock.patch.dict(os.environ, {"COMPASS_HOME": os.path.join(tmp, "state")}),
                support.store_patch(PROJECTS_DIR=str(projects)),
                support.store_patch(TASKS_DIR=str(projects / "tasks")),
            ):
                config, _state = support.runtime()
                self.assertEqual(
                    (str(projects),),
                    config.store_roots["claude.projects"],
                    "the store redirect did not take, so this read the real store",
                )
                self.assertTrue(
                    config.state_home.startswith(tmp), "the state home redirect did not take"
                )
                yield self._application(), config

    @staticmethod
    def _application() -> aggregate.Application:
        app = support.build_app()
        app.clock = lambda: NOW
        return app

    def _row(self, app: aggregate.Application) -> dict[str, Any]:
        collection = app.collect(show_all=False)
        rows = [s for s in collection["sessions"] if s["sid"] == PREFIX]
        self.assertEqual(1, len(rows), "the seeded session was not collected")
        row: dict[str, Any] = rows[0]
        return row

    def _end_then_restart(self, app: aggregate.Application) -> aggregate.Application:
        """The first run sees the end; the second is a fresh process over the same home."""
        first = observation.Observation(app, clock=lambda: END_AT, diagnostic_sink=lambda _m: None)
        app.overlays = first
        self.assertEqual(
            "accepted",
            first.submit("claude", {"v": 1, "event": "session_ended", "session_id": SESSION}),
        )
        second = self._application()
        second.overlays = observation.Observation(
            second, clock=lambda: NOW, diagnostic_sink=lambda _m: None
        )
        return second


class AStoredEndReachesAColdRowTest(ColdRowTestCase):
    """AC1 and AC2 at the row: the value, then the eligibility path."""

    def test_a_stored_end_is_published_on_a_row_the_coordinator_never_saw(self) -> None:
        with self._board() as (app, config):
            ends.record(
                config, harness="claude", sid=PREFIX, at=END_AT, diagnostic_sink=lambda _m: None
            )
            app.overlays = ColdSource()
            row = self._row(app)
        self.assertEqual("idle", row["state"], "the collector still owns the state")
        self.assertEqual(END_AT, row["ended_at"])
        self.assertIsNone(row["finished_at"], "an end is not a stop")

    def test_a_final_reading_is_takeable_on_the_cold_row(self) -> None:
        # AC2: `eligibility` reads `ended_at` off the row, so the restored end is
        # what lets it return a final scope after the restart.
        with self._board() as (app, config):
            ends.record(
                config, harness="claude", sid=PREFIX, at=END_AT, diagnostic_sink=lambda _m: None
            )
            app.overlays = ColdSource()
            row = self._row(app)
        self.assertEqual("session-end", reading.end_kind(row))
        self.assertEqual(
            (reading.SCOPE_FINAL, ""),
            reading.eligibility(row, latest_revision_at=0.0, now=NOW, settle_sec=8.0),
        )

    def test_the_end_the_first_run_observed_reaches_the_second_run_through_the_store(self) -> None:
        # The whole journey rather than a hand-written store: a real coordinator
        # takes the end, a second Application over the same home reads it cold.
        with self._board() as (app, _config):
            second = self._end_then_restart(app)
            row = self._row(second)
        self.assertEqual(END_AT, row["ended_at"])

    def test_a_previously_stored_final_reading_is_no_longer_withdrawn(self) -> None:
        # The second symptom: `_withdraw_stale_finality` compares the row's end to
        # the one the reading rested on, and a cold row carrying None retracted
        # every final reading on every restart.
        assessment: Any = {
            "revision_read": 1,
            "stamp": "",
            "cutoff": "",
            "scope": reading.SCOPE_FINAL,
            "scope_text": reading.SCOPE_TEXT[reading.SCOPE_FINAL],
            "ended_at_read": END_AT,
            "criteria": {
                name: {
                    "result": reading.RESULT_UNVERIFIABLE,
                    "cites": (),
                    "detail": "",
                    "clause": "",
                }
                for name in (reading.CONSTRAINT_GOAL,)
            },
        }
        with self._board() as (app, config):
            annotation_store.annotate(
                config, app.state, "claude", PREFIX, goal="rename", now=END_AT - 200
            )
            annotation_store.record_reading(
                config, app.state, "claude", PREFIX, assessment=assessment
            )
            second = self._end_then_restart(app)
            row = self._row(second)
        published = row["annotation_assessment"]
        self.assertEqual(reading.SCOPE_FINAL, published["scope"])
        self.assertEqual(reading.SCOPE_TEXT[reading.SCOPE_FINAL], published["scope_text"])
        self.assertEqual(
            row["ended_at"], published["ended_at_read"], "the stamp round-trips exactly"
        )

    def test_under_no_events_the_store_is_neither_read_nor_written(self) -> None:
        # decisions.md, DRC-4547: Option A. The coordinator is the only writer,
        # and with none the store is left alone in both directions.
        with self._board() as (app, config):
            ends.record(
                config, harness="claude", sid=PREFIX, at=END_AT, diagnostic_sink=lambda _m: None
            )
            before = Path(ends.store_path(config)).read_bytes()
            app.overlays = None
            row = self._row(app)
            after = Path(ends.store_path(config)).read_bytes()
        self.assertIsNone(row["ended_at"])
        self.assertEqual(before, after)


class NothingClaimsAnEndItDidNotSeeTest(ColdRowTestCase):
    """AC4 at the row, and the resumed-while-down guard."""

    def test_a_store_with_no_end_for_this_session_publishes_none(self) -> None:
        with self._board() as (app, config):
            os.makedirs(config.state_home, mode=0o700, exist_ok=True)
            Path(ends.store_path(config)).write_text(
                json.dumps(
                    {
                        "v": ends.SCHEMA_VERSION,
                        "entries": [
                            {"harness": "codex", "sid": "elsewhere", "at": END_AT},
                            {"harness": "claude", "sid": PREFIX, "at": 0},
                            {"harness": "claude", "sid": PREFIX, "at": "yesterday"},
                        ],
                    }
                )
            )
            app.overlays = ColdSource()
            row = self._row(app)
        self.assertIsNone(row["ended_at"])
        self.assertEqual("idle-unknown", reading.end_kind(row))

    def test_a_corrupt_store_publishes_none_and_every_row_still_renders(self) -> None:
        with self._board() as (app, config):
            os.makedirs(config.state_home, mode=0o700, exist_ok=True)
            Path(ends.store_path(config)).write_bytes(b'{"v": 1, "entries": [{"harness": "cl')
            app.overlays = ColdSource()
            row = self._row(app)
        self.assertIsNone(row["ended_at"])

    def test_a_stored_end_loses_to_transcript_activity_after_it(self) -> None:
        # decisions.md, DRC-4547: a session `--resume`d while the board was down
        # produced no event this process saw, so the only tell that the id is in
        # use again is the transcript writing after the end. The exposure that
        # comes with it is written in SECURITY.md: a harness that writes its
        # transcript after SessionEnd loses the restored end and the row reads as
        # it does today, which is honest rather than wrong.
        with self._board(last_activity=END_AT + 10.0 + 1) as (app, config):
            self.assertEqual(
                10.0,
                config.overlay_wait_activity_grace_sec,
                "the grace this test is built on moved",
            )
            ends.record(
                config, harness="claude", sid=PREFIX, at=END_AT, diagnostic_sink=lambda _m: None
            )
            app.overlays = ColdSource()
            row = self._row(app)
        self.assertIsNone(row["ended_at"])
        self.assertNotEqual("session-end", reading.end_kind(row))

    def test_activity_inside_the_grace_keeps_the_stored_end(self) -> None:
        # The boundary from the other side: the a1 arm of the session-end capture
        # put the end 5.581 s after the last Stop, and a transcript write inside
        # the grace is that ordering rather than a resumption.
        with self._board(last_activity=END_AT + 9.0) as (app, config):
            ends.record(
                config, harness="claude", sid=PREFIX, at=END_AT, diagnostic_sink=lambda _m: None
            )
            app.overlays = ColdSource()
            row = self._row(app)
        self.assertEqual(END_AT, row["ended_at"])

    def test_a_live_end_stays_unguarded(self) -> None:
        # The boring outcome, pinned so the guard above cannot leak: a live end is
        # retired by `_lift_ended` when the id is seen in use again, so
        # `events._side_channel_patch` applies no activity guard to it and this
        # change must not add one by another door.
        with self._board(last_activity=END_AT + 100.0) as (app, _config):
            app.overlays = LiveEndSource()
            row = self._row(app)
        self.assertEqual(END_AT, row["ended_at"])


class OneShotCommandsAndTheStoreTest(unittest.TestCase):
    """AC6: `--diagnose` neither creates nor writes the store; `--forget` removes it."""

    def setUp(self) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state_home = state.name
        self.env = isolated_environment(self.state_home, home.name)
        # One discoverable session, so a collection actually runs: `--diagnose`
        # over a machine with no stores collects nothing and would pass for the
        # defect too (the same trap `test_history` records).
        seed_claude_transcript(
            Path(self.env["CLAUDE_CONFIG_DIR"]) / "projects",
            "-nonexistent-compass-test-repos-recce-compass",
            when=time.time(),
        )
        self.config = build_runtime_config(
            environ=self.env,
            platform_name="linux",
            os_name="posix",
            launcher_path=Path(home.name) / "server.py",
        )

    def test_diagnose_over_a_discovered_session_creates_no_end_store(self) -> None:
        self.assertEqual(0, run_one_shot_cli(["--diagnose"], self.env))
        self.assertFalse(os.path.exists(ends.store_path(self.config)))

    def test_diagnose_leaves_an_existing_end_store_byte_identical(self) -> None:
        ends.record(
            self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=lambda _m: None
        )
        before = Path(ends.store_path(self.config)).read_bytes()
        self.assertEqual(0, run_one_shot_cli(["--diagnose"], self.env))
        self.assertEqual(before, Path(ends.store_path(self.config)).read_bytes())

    def test_the_refusal_under_a_live_board_names_the_store_it_is_also_keeping(self) -> None:
        # The refusal is one sentence for three files now, and a reader who ran
        # `--forget` to drop a recorded end learns nothing from a sentence that
        # names only the history store. The delete is right either way; what is
        # under test is that the sentence accounts for every file it kept.
        from compass_runtime import io as runtime_io  # noqa: PLC0415
        from compass_runtime import lifecycle  # noqa: PLC0415

        ends.record(
            self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=lambda _m: None
        )
        running = {"state": "running", "port": 4553, "pid": 4242, "started": 1.0, "log": ""}
        with (
            mock.patch.object(lifecycle, "instance_status", return_value=running),
            mock.patch.object(runtime_io, "diag") as diag,
        ):
            self.assertEqual(1, run_one_shot_cli(["--forget"], self.env))
        self.assertTrue(
            os.path.exists(ends.store_path(self.config)),
            "the end store was deleted under a live board",
        )
        # The message argument, never `str(call)`. A call's repr escapes
        # backslashes, so on Windows a path in the sentence reads as
        # `C:\\Users\\...` there and as `C:\Users\...` in the assertion, and
        # the two never match. Measured: this passed on macOS and failed the
        # Windows runner on the assertion below, which is the only one of the
        # four in this pattern that carries a path.
        said = " ".join(str(call.args[0]) for call in diag.call_args_list)
        self.assertIn(ends.STORE_FILENAME, said)
        self.assertIn("--stop", said)
        # And the third store the sweep did not reach (DRC-4565). The refusal
        # returns before that sweep, so a reader who ran the command for their
        # discard records is owed the file's name here too -- the message named
        # two of three and the shipped doc claimed all three.
        self.assertIn(
            os.path.basename(annotation_store.store_path(self.config)),
            said,
            "the refusal does not name the annotation store it also kept",
        )

    def test_forget_removes_a_discard_record_and_not_the_reader_words(self) -> None:
        """DRC-4565. `--forget` removes the machine's memory of what it
        observed, and a record that Compass deleted something is squarely
        that class. What a reader typed is not, which is why the annotation
        store is swept rather than deleted -- the module's own docstring says
        `--forget` does not reach those words and that stays true.
        """
        state = build_runtime_state(self.config, started=100.0)
        annotation_store.annotate(self.config, state, "pi", "keep", goal="still mine", now=100.0)
        annotation_store.annotate(self.config, state, "pi", "gone", goal="deleted", now=100.0)
        annotation_store.clear(
            self.config, state, "pi", "gone", now=200.0, diagnostic_sink=lambda _m: None
        )

        with no_instance():
            self.assertEqual(0, run_one_shot_cli(["--forget"], self.env))

        kept = annotation_store.load(self.config)
        self.assertEqual({"keep"}, {entry["sid"] for entry in kept})
        self.assertEqual("still mine", kept[0]["revisions"][-1]["goal"])

    def test_a_sweep_that_could_not_write_says_so_rather_than_nothing_to_remove(self) -> None:
        """DRC-4565. The one wrong sentence this command can say.

        A store it could not write still holds every record, and reporting
        that as "no discard records" tells a reader the thing they ran the
        command for is gone. The store's own failure line is silenced by
        `forget`, because that line is worded for a reader losing what they
        typed and nothing here was written at all.
        """
        from compass_runtime import io as runtime_io  # noqa: PLC0415

        state = build_runtime_state(self.config, started=100.0)
        annotation_store.annotate(self.config, state, "pi", "gone", goal="deleted", now=100.0)
        annotation_store.clear(
            self.config, state, "pi", "gone", now=200.0, diagnostic_sink=lambda _m: None
        )
        path = annotation_store.store_path(self.config)

        with (
            no_instance(),
            mock.patch.object(annotation_store, "_write", return_value=False),
            mock.patch.object(runtime_io, "diag") as diag,
        ):
            self.assertEqual(0, run_one_shot_cli(["--forget"], self.env))

        # The message argument, never `str(call)`. A call's repr escapes
        # backslashes, so on Windows a path in the sentence reads as
        # `C:\\Users\\...` there and as `C:\Users\...` in the assertion, and
        # the two never match. Measured: this passed on macOS and failed the
        # Windows runner on the assertion below, which is the only one of the
        # four in this pattern that carries a path.
        said = " ".join(str(call.args[0]) for call in diag.call_args_list)
        self.assertIn(f"could not write {path}", said)
        self.assertNotIn("no discard records", said)
        self.assertEqual({"gone"}, {entry["sid"] for entry in annotation_store.load(self.config)})

    def test_forget_deletes_the_end_store_too(self) -> None:
        # decisions.md, DRC-4547: `--forget` removes the machine's memory of what
        # it observed, and a durable end is exactly that class.
        ends.record(
            self.config, harness="claude", sid=PREFIX, at=100.0, diagnostic_sink=lambda _m: None
        )
        with no_instance():
            self.assertEqual(0, run_one_shot_cli(["--forget"], self.env))
        self.assertFalse(os.path.exists(ends.store_path(self.config)))
