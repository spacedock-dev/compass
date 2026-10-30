"""A reader-pressed reading run as a server-owned job (DRC-4686).

The route tests in `test_http_api.ReadingRouteTest` drive the job through a
real socket. These drive `reading_jobs` directly, with an application that
records what each collection published, so the order of the job's effects is
observable rather than inferred from a final state.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import io as runtime_io
from compass_runtime import reading, reading_jobs, reading_policy, supervise

from .support import make_runtime, process_alive

if TYPE_CHECKING:
    from collections.abc import Iterator

KEY = "claude:s1"


@contextlib.contextmanager
def _windows_rename() -> Iterator[None]:
    """`Path.rename` and `Path.read_text` as a Windows MoveFileEx meets them.

    MoveFileEx opens its source by path for DELETE, sharing everything, and then
    renames through that handle: a second rename follows the file wherever the
    first moved it, and a plain read while such a handle is open fails with a
    sharing violation. Inferred from the runner's failure, not observed there.
    """
    held: dict[int, int] = {}
    guard = threading.Lock()
    rename, read_text = Path.rename, Path.read_text

    def moved(path: Path, target: Any) -> Any:
        inode = path.stat().st_ino
        with guard:
            held[inode] = held.get(inode, 0) + 1
        try:
            time.sleep(0.002)
            current = next((p for p in path.parent.iterdir() if p.stat().st_ino == inode), None)
            if current is None:
                raise PermissionError(13, "deleted under the handle")
            return rename(current, target)
        finally:
            with guard:
                held[inode] -= 1

    def read(path: Path, *args: Any, **kwargs: Any) -> str:
        try:
            inode = path.stat().st_ino
        except OSError:
            inode = -1
        with guard:
            busy = held.get(inode, 0) > 0
        if busy:
            raise PermissionError(32, "sharing violation")
        return read_text(path, *args, **kwargs)

    with mock.patch.object(Path, "rename", moved), mock.patch.object(Path, "read_text", read):
        yield


class _Application:
    """Enough of `aggregate.Application` for a job: it records every publish."""

    def __init__(self, config: Any, state: Any, events: list[Any]) -> None:
        self.config = config
        self.state = state
        self.events = events
        self.diagnostics: list[str] = []
        self.diagnostic_sink = self.diagnostics.append

    @staticmethod
    def clock() -> float:
        return 1_700_000_100.0

    def collect_json(self, *, show_all: bool) -> tuple[Any, bytes]:
        del show_all
        running = reading.published_jobs(self.config).get(KEY)
        self.events.append(("publish", running["phase"] if running else None))
        return (0.0, 0), b"{}"


class ReadingJobTest(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(
            state_home=home, state_dir=Path(home), annotations_enabled=True
        )
        annotation_store.annotate(
            self.config, self.state, "claude", "s1", goal="ship the parser", output="", now=10.0
        )
        self.events: list[Any] = []
        self.application: Any = _Application(self.config, self.state, self.events)
        self.addCleanup(reading.end_job, self.config, KEY)
        # A dashboard's shutdown closes the runner for the life of its process,
        # and an earlier test that ran `serve` in this worker would leave it
        # closed: every outcome here would then read as a stop.
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, compose: Any) -> reading.Job:
        job = reading.start_job(
            self.config, KEY, provider="claude", label="Claude Code", now=1_700_000_100.0
        )
        assert job is not None
        self.events.append(("started", job.phase))
        record_reading = annotation_store.record_reading
        record_withheld = annotation_store.record_withheld

        def wrote(kind: str, real: Any) -> Any:
            def spy(*args: Any, **kwargs: Any) -> Any:
                self.events.append((kind, kwargs.get("reason"), kwargs.get("spent")))
                return real(*args, **kwargs)

            return spy

        end_job = reading.end_job

        def ended(*args: Any) -> None:
            self.events.append(("ended", reading.job(self.config, KEY) is not None))
            end_job(*args)

        with (
            mock.patch.object(annotation_store, "record_reading", wrote("reading", record_reading)),
            mock.patch.object(
                annotation_store, "record_withheld", wrote("withheld", record_withheld)
            ),
            mock.patch.object(reading, "end_job", ended),
        ):
            thread = reading_jobs.launch(self.application, job, compose)
            thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "the job never finished")
        return job

    def _markers(self) -> list[Path]:
        return sorted((Path(self.config.state_dir) / reading_jobs.MARKER_DIR).glob("*.json"))

    def test_each_real_phase_is_published_once_and_in_order(self) -> None:
        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.before_reserve()
            hooks.reserved()
            hooks.spawned(object())
            hooks.phase(reading.PHASE_CHECKING)
            return None, reading.WITHHELD_MODEL_FAILED, True

        self._run(compose)
        published = [phase for kind, phase, *_ in self.events if kind == "publish"]
        self.assertEqual(["preparing", "waiting", "checking", None], published)

    def test_the_lines_a_check_answered_reach_the_store(self) -> None:
        # The store holds fact ids only, so the press says which lines rest on a passing check, and
        # the store drops an earlier departure there for good (owner, 2026-10-30).
        stored: dict[str, Any] = {}

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.on_a_check = frozenset({"line_2"})
            return {"read_at": 1.0}, "", True

        def record(*_args: Any, **kwargs: Any) -> str:
            stored.update(kwargs)
            return annotation_store.OUTCOME_STORED

        with mock.patch.object(annotation_store, "record_reading", record):
            job = reading.start_job(
                self.config, KEY, provider="claude", label="Claude Code", now=1_700_000_100.0
            )
            assert job is not None
            thread = reading_jobs.launch(self.application, job, compose)
            thread.join(timeout=10)
        self.assertEqual(frozenset({"line_2"}), stored.get("on_a_check"))

    def test_the_store_is_written_before_the_job_leaves_and_one_revision_follows(self) -> None:
        self._run(lambda _hooks: (None, reading.WITHHELD_LEDGER_EMPTY, False))
        tail = self.events[-3:]
        self.assertEqual(("withheld", reading.WITHHELD_LEDGER_EMPTY, False), tail[0])
        self.assertEqual(("ended", True), tail[1])
        self.assertEqual(("publish", None), tail[2])

    def test_the_spawned_group_is_kept_on_the_job_for_a_later_cancel(self) -> None:
        group = object()
        seen: list[Any] = []

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.spawned(group)
            running = reading.job(self.config, KEY)
            seen.append(running.group if running else None)
            return None, reading.WITHHELD_MODEL_FAILED, True

        self._run(compose)
        self.assertEqual([group], seen)

    def test_an_exception_in_the_job_still_frees_the_slot(self) -> None:
        for reserved in (False, True):
            with self.subTest(reserved=reserved):
                self.events.clear()

                def compose(hooks: reading_jobs.Hooks, *, spend: bool = reserved) -> Any:
                    if spend:
                        hooks.before_reserve()
                        hooks.reserved()
                    raise RuntimeError("the record could not be read")

                self._run(compose)
                self.assertIsNone(reading.job(self.config, KEY))
                self.assertTrue(reading.claim(self.config, KEY))
                reading.release(self.config, KEY)
                self.assertIn(("withheld", reading.WITHHELD_MODEL_FAILED, reserved), self.events)
                self.assertEqual([], self._markers())

    def test_a_refusal_at_the_model_seam_writes_nothing(self) -> None:
        def compose(_hooks: reading_jobs.Hooks) -> Any:
            raise reading_policy.RefusedError(
                reading_policy.status(self.config, now=1_700_000_100.0)
            )

        self._run(compose)
        self.assertEqual([], [e for e in self.events if e[0] in {"reading", "withheld"}])
        self.assertIsNone(reading.job(self.config, KEY))

    def test_a_spent_attempt_leaves_a_marker_until_its_outcome_is_stored(self) -> None:
        during: list[list[dict[str, Any]]] = []

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.before_reserve()
            hooks.reserved()
            during.append([json.loads(p.read_text()) for p in self._markers()])
            return None, reading.WITHHELD_MODEL_FAILED, True

        job = self._run(compose)
        self.assertEqual(
            [[{"id": job.id, "harness": "claude", "sid": "s1", "pid": os.getpid()}]],
            [[{k: m[k] for k in ("id", "harness", "sid", "pid")} for m in d] for d in during],
        )
        self.assertEqual([], self._markers())

    def test_an_unspent_job_leaves_no_marker(self) -> None:
        during: list[int] = []

        def compose(_hooks: reading_jobs.Hooks) -> Any:
            during.append(len(self._markers()))
            return None, reading.WITHHELD_LEDGER_EMPTY, False

        self._run(compose)
        self.assertEqual([0], during)

    # Correction round.

    def test_a_graceful_shutdown_records_the_attempt_as_interrupted(self) -> None:
        """Review F5: a job the shutdown killed is "interrupted", as the docs say."""
        from compass_runtime import supervise  # noqa: PLC0415

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.before_reserve()
            hooks.reserved()
            supervise._SHUTDOWN.set()
            return None, reading.WITHHELD_MODEL_FAILED, True

        with mock.patch.object(supervise, "_SHUTDOWN", threading.Event()):
            self._run(compose)
        self.assertIn(("withheld", reading.WITHHELD_INTERRUPTED, True), self.events)

    def test_a_shutdown_keeps_the_unstopped_reason(self) -> None:
        """Verify N5: "may still be running" is the one sentence a stop must not hide."""

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.before_reserve()
            hooks.reserved()
            supervise._SHUTDOWN.set()
            return None, reading.WITHHELD_UNSTOPPED, True

        self._run(compose)
        self.assertIn(("withheld", reading.WITHHELD_UNSTOPPED, True), self.events)

    def test_a_shutdown_after_a_flood_kill_keeps_oversized(self) -> None:
        """Review T5: the flood kill came first, so the stop does not rename it."""

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.before_reserve()
            hooks.reserved()
            supervise._SHUTDOWN.set()
            return None, reading.WITHHELD_OVERSIZED, True

        self._run(compose)
        self.assertIn(("withheld", reading.WITHHELD_OVERSIZED, True), self.events)

    def test_a_kept_marker_recovers_as_a_refused_write_not_as_a_stop(self) -> None:
        """Verify N6: the analysis finished; the store refused its outcome."""

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.before_reserve()
            hooks.reserved()
            return None, reading.WITHHELD_MODEL_FAILED, True

        with mock.patch.object(
            annotation_store, "_record", return_value=annotation_store.OUTCOME_UNWRITABLE
        ):
            job = self._run(compose)
        self.assertEqual([f"{job.id}.json"], [p.name for p in self._markers()])
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_UNSTORED], entry.get("withheld"))
        self.assertEqual(1, entry.get("readings"))

    def test_a_kept_marker_keeps_a_stop_or_an_unconfirmed_kill_as_its_reason(self) -> None:
        """L3: a refused "interrupted", "unstopped" or "oversized" must not recover as "ran"."""
        for reason in (
            reading.WITHHELD_INTERRUPTED,
            reading.WITHHELD_UNSTOPPED,
            reading.WITHHELD_OVERSIZED,
        ):
            with self.subTest(reason=reason):
                annotation_store.annotate(
                    self.config, self.state, "claude", "s1", goal=f"g {reason}", output="", now=11.0
                )

                def compose(hooks: reading_jobs.Hooks, *, why: str = reason) -> Any:
                    hooks.before_reserve()
                    hooks.reserved()
                    return None, why, True

                with mock.patch.object(
                    annotation_store, "_record", return_value=annotation_store.OUTCOME_UNWRITABLE
                ):
                    self._run(compose)
                reading_jobs.recover(self.application, alive=lambda _pid: False)
                entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
                assert entry is not None
                self.assertEqual(reading.WITHHELD[reason], entry.get("withheld"))

    def test_a_marker_that_cannot_be_written_stops_the_job_before_anything_is_spent(
        self,
    ) -> None:
        """Codex review: a spend no marker records could be lost to a restart."""
        spent: list[bool] = []

        def compose(hooks: reading_jobs.Hooks) -> Any:
            hooks.before_reserve()
            spent.append(True)
            return None, reading.WITHHELD_MODEL_FAILED, True

        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError("full")):
            self._run(compose)
        self.assertEqual([], spent, "the job went on to spend with no marker")
        self.assertIn(("withheld", reading.WITHHELD_JOB_UNRECORDED, False), self.events)

    def test_a_store_that_refuses_a_spent_outcome_keeps_the_marker(self) -> None:
        """Codex review: the marker is the only record of the spend until the store has it."""
        for outcome in (annotation_store.OUTCOME_UNWRITABLE, annotation_store.OUTCOME_UNTRUSTED):
            with self.subTest(outcome=outcome):

                def compose(hooks: reading_jobs.Hooks) -> Any:
                    hooks.before_reserve()
                    hooks.reserved()
                    return None, reading.WITHHELD_MODEL_FAILED, True

                with mock.patch.object(annotation_store, "_record", return_value=outcome):
                    job = self._run(compose)
                self.assertEqual([f"{job.id}.json"], [p.name for p in self._markers()])
                for marker in self._markers():
                    marker.unlink()

    def test_a_thread_that_cannot_start_frees_the_job_and_the_slot(self) -> None:
        """Review F8: a failed start would otherwise answer every later press 409."""
        job = reading.start_job(self.config, KEY, provider="claude", label="Claude Code", now=1.0)
        assert job is not None
        with (
            mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("no thread")),
            self.assertRaises(RuntimeError),
        ):
            reading_jobs.launch(self.application, job, lambda _h: (None, "", False))
        self.assertIsNone(reading.job(self.config, KEY))
        self.assertTrue(reading.claim(self.config, KEY))
        reading.release(self.config, KEY)


class ARestartRecordsTheAttemptItInterruptedTest(unittest.TestCase):
    """Q2: a job lost on restart is a spent `interrupted` attempt, never a silent loss."""

    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.state = make_runtime(
            state_home=home, state_dir=Path(home), annotations_enabled=True
        )
        annotation_store.annotate(
            self.config, self.state, "claude", "s1", goal="ship the parser", output="", now=10.0
        )
        self.application: Any = _Application(self.config, self.state, [])
        self.markers = Path(self.config.state_dir) / reading_jobs.MARKER_DIR

    def _marker(self, name: str, content: str) -> Path:
        self.markers.mkdir(parents=True, exist_ok=True)
        path = self.markers / f"{name}.json"
        path.write_text(content)
        return path

    def _entry(self) -> Any:
        # From disk: a second dashboard's write never reaches this state's cache.
        return annotation_store.find(annotation_store.load(self.config), "claude", "s1")

    def test_a_marker_left_by_a_process_that_is_gone_becomes_a_spent_interrupted_attempt(
        self,
    ) -> None:
        marker = self._marker(
            "abc", json.dumps({"id": "abc", "harness": "claude", "sid": "s1", "pid": 4242})
        )
        recovered = reading_jobs.recover(self.application, alive=lambda _pid: False)
        self.assertEqual(1, recovered)
        entry = self._entry()
        self.assertEqual(1, entry.get("readings"))
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_INTERRUPTED], entry.get("withheld"))
        self.assertFalse(marker.exists())

    def test_a_marker_whose_process_still_runs_is_another_dashboards_live_job(self) -> None:
        marker = self._marker(
            "abc", json.dumps({"id": "abc", "harness": "claude", "sid": "s1", "pid": 4242})
        )
        self.assertEqual(0, reading_jobs.recover(self.application, alive=lambda _pid: True))
        self.assertTrue(marker.exists())
        self.assertNotIn("readings", self._entry())

    def test_no_marker_writes_nothing(self) -> None:
        with mock.patch.object(annotation_store, "record_withheld") as record:
            self.assertEqual(0, reading_jobs.recover(self.application, alive=lambda _pid: False))
        record.assert_not_called()

    def test_an_unreadable_marker_is_removed_and_records_nothing(self) -> None:
        marker = self._marker("bad", "{not json")
        with mock.patch.object(annotation_store, "record_withheld") as record:
            self.assertEqual(0, reading_jobs.recover(self.application, alive=lambda _pid: False))
        record.assert_not_called()
        self.assertFalse(marker.exists())

    def test_an_outcome_already_stored_for_the_job_is_not_counted_again(self) -> None:
        """Review F3: the process died after the write and before the marker went."""
        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            "s1",
            reason=reading.WITHHELD_MODEL_FAILED,
            spent=True,
            job_id="abc",
        )
        marker = self._marker(
            "abc", json.dumps({"id": "abc", "harness": "claude", "sid": "s1", "pid": 4242})
        )
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        self.assertEqual(1, self._entry().get("readings"))
        self.assertFalse(marker.exists())

    def test_recording_one_job_twice_counts_it_once(self) -> None:
        for _ in range(2):
            annotation_store.record_withheld(
                self.config,
                self.state,
                "claude",
                "s1",
                reason=reading.WITHHELD_MODEL_FAILED,
                spent=True,
                job_id="abc",
            )
        self.assertEqual(1, self._entry().get("readings"))

    def test_two_dashboards_recovering_one_marker_count_it_once(self) -> None:
        for attempt in range(20):
            with self.subTest(attempt=attempt):
                job_id = f"job{attempt}"
                self._marker(
                    job_id,
                    json.dumps({"id": job_id, "harness": "claude", "sid": "s1", "pid": 4242}),
                )
                before = self._entry().get("readings", 0)
                _, other_state = make_runtime(
                    state_home=str(self.config.state_dir),
                    state_dir=Path(self.config.state_dir),
                    annotations_enabled=True,
                )
                other: Any = _Application(self.config, other_state, [])
                gate = threading.Barrier(2)

                def recover(app: Any, gate: threading.Barrier = gate) -> None:
                    gate.wait(5)
                    reading_jobs.recover(app, alive=lambda _pid: False)

                threads = [
                    threading.Thread(target=recover, args=(app,))
                    for app in (self.application, other)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(10)
                self.assertEqual(before + 1, self._entry().get("readings"))
                self.assertEqual([], list(self.markers.iterdir()))

    def test_two_dashboards_count_it_once_where_the_rename_is_not_exclusive(self) -> None:
        """The Windows shape, emulated: the recovery lock holds without the rename.

        Measured against the build before the lock: every one of the 20
        subtests lost the attempt, the `before + 1 != before` shape the
        windows-latest runner reported for the test above in 3 of 20.
        """
        with _windows_rename():
            self.test_two_dashboards_recovering_one_marker_count_it_once()

    def test_a_claim_that_cannot_be_read_is_left_rather_than_deleted(self) -> None:
        self._marker(
            "abc", json.dumps({"id": "abc", "harness": "claude", "sid": "s1", "pid": 4242})
        )
        real = Path.read_text

        def refuse(path: Path, *args: Any, **kwargs: Any) -> str:
            if ".claim-" in path.name:
                raise PermissionError(32, "sharing violation")
            return real(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", refuse):
            self.assertEqual(0, reading_jobs.recover(self.application, alive=lambda _pid: False))
        self.assertIsNone(self._entry().get("readings"))
        self.assertEqual(["abc.json.claim-"], [p.name[:15] for p in self.markers.iterdir()])

    def test_a_marker_naming_this_process_is_an_earlier_run(self) -> None:
        """Review F4: a container's dashboard is PID 1 on every start."""
        self._marker(
            "abc", json.dumps({"id": "abc", "harness": "claude", "sid": "s1", "pid": os.getpid()})
        )
        self.assertEqual(1, reading_jobs.recover(self.application, alive=lambda _pid: True))
        self.assertEqual(1, self._entry().get("readings"))

    # DRC-4713: recovery counts an attempt as spent only when the ledger holds
    # its charge, and counts it when the ledger cannot say.

    def _ledgered(self, job_id: str, **extra: Any) -> Path:
        marker = {
            "id": job_id,
            "harness": "claude",
            "sid": "s1",
            "pid": 4242,
            "started_at": 1_700_000_000.0,
            "ledger": True,
            **extra,
        }
        return self._marker(job_id, json.dumps(marker))

    def _used(self) -> int:
        return reading_policy.status(self.config, now=1_700_000_100.0)["used"]

    def _open_store(self) -> None:
        # Before any job: the ledger answers only for jobs after it began.
        reading_policy.set_consent(self.config, True, now=1_699_999_000.0)

    def test_a_marker_with_no_charge_on_record_recovers_unspent(self) -> None:
        self._open_store()
        reading_policy.reserve(self.config, now=1_700_000_050.0, job_id="other")
        self._ledgered("dead")
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        entry = self._entry()
        self.assertNotIn("readings", entry)
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_STOPPING], entry.get("withheld"))
        self.assertEqual(1, self._used(), "recovery charged or refunded the budget")

    def test_a_marker_whose_charge_is_on_record_recovers_spent(self) -> None:
        self._open_store()
        reading_policy.reserve(self.config, now=1_700_000_050.0, job_id="dead")
        self._ledgered("dead")
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        entry = self._entry()
        self.assertEqual(1, entry.get("readings"))
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_INTERRUPTED], entry.get("withheld"))
        self.assertEqual(1, self._used())

    def test_a_cancelled_marker_with_no_charge_recovers_cancelled_unsent(self) -> None:
        self._open_store()
        reading_policy.reserve(self.config, now=1_700_000_050.0, job_id="other")
        self._ledgered("dead", reason=reading.WITHHELD_CANCELLED)
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        entry = self._entry()
        self.assertNotIn("readings", entry)
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CANCELLED_UNSENT], entry.get("withheld"))

    def test_a_ledger_that_cannot_answer_counts_the_attempt_spent(self) -> None:
        cases: list[tuple[str, Any, dict[str, Any]]] = [
            ("no store", None, {}),
            ("no SQLite", mock.patch.object(runtime_io, "sqlite_module", None), {}),
            ("older than the ledger keeps", None, {"started_at": 1.0}),
            ("no start time", None, {"started_at": None}),
        ]
        for count, (name, patch, extra) in enumerate(cases, start=1):
            with self.subTest(name):
                if count == 2:
                    # From here a ledger exists, and would answer "no charge"
                    # for these ids if it were asked.
                    self._open_store()
                    reading_policy.reserve(self.config, now=1_700_000_050.0, job_id="other")
                job_id = name.replace(" ", "-")
                annotation_store.annotate(
                    self.config, self.state, "claude", "s1", goal=f"g {name}", output="", now=11.0
                )
                self._ledgered(job_id, **extra)
                with patch or contextlib.nullcontext():
                    reading_jobs.recover(self.application, alive=lambda _pid: False)
                entry = self._entry()
                self.assertEqual(count, entry.get("readings"))
                self.assertEqual(
                    reading.WITHHELD[reading.WITHHELD_INTERRUPTED], entry.get("withheld")
                )

    def test_a_marker_from_a_build_without_the_ledger_is_counted_spent(self) -> None:
        """Written before an upgrade or during a rollback: its charge carried no job id."""
        self._open_store()
        reading_policy.reserve(self.config, now=1_700_000_050.0, job_id="other")
        self._marker(
            "old",
            json.dumps(
                {"id": "old", "harness": "claude", "sid": "s1", "pid": 4242, "started_at": 1.7e9}
            ),
        )
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        self.assertEqual(1, self._entry().get("readings"))

    def test_the_interrupted_sentence_says_the_attempt_counted(self) -> None:
        sentence = reading.WITHHELD[reading.WITHHELD_INTERRUPTED]
        self.assertIn("stopped before it finished", sentence)
        self.assertIn("fresh press is the only retry", sentence)


# A CLI standing in for `codex exec`: in "sleep" it starts a grandchild, writes
# both pids where the test reads them, and outlives any call; in "reply" it
# writes a reply to the output file codex_exec names and exits.
_FAKE_CLI = (
    "import os, subprocess, sys, time\n"
    "mode, pids, args = sys.argv[1], sys.argv[2], sys.argv[3:]\n"
    "sys.stdin.read()\n"
    "if mode == 'reply':\n"
    "    with open(args[args.index('--output-last-message') + 1], 'w') as out:\n"
    "        out.write('{}')\n"
    "    sys.exit(0)\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "with open(pids + '.tmp', 'w') as out:\n"
    "    out.write(f'{os.getpid()} {child.pid}')\n"
    "os.replace(pids + '.tmp', pids)\n"
    "time.sleep(60)\n"
)
NOW = 1_700_000_100.0


def _wait_until(predicate: Any, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


class CancelAnAnalysisTest(unittest.TestCase):
    """DRC-4693: Cancel on a running analysis, driven through a real supervised CLI.

    The job runs `produce` over the real `CodexReadingModel` and the real
    runner, so a kill is a kill of a process tree the test can look for
    afterwards. Every race is held open with a barrier at a named seam, never
    by a sleep: sleep-timed races passed and lied in S5's review.
    """

    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, True)
        self.config, self.state = make_runtime(
            state_home=str(self.home), state_dir=self.home, annotations_enabled=True
        )
        annotation_store.annotate(
            self.config, self.state, "claude", "s1", goal="ship the parser", output="", now=10.0
        )
        # Before the press, so the ledger can answer for the job (review F2).
        reading_policy.set_consent(self.config, True, now=NOW - 100.0)
        self.events: list[Any] = []
        self.application: Any = _Application(self.config, self.state, self.events)
        self.addCleanup(reading.end_job, self.config, KEY)
        patcher = mock.patch.object(supervise, "_SHUTDOWN", threading.Event())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.script = self.home / "fake_cli.py"
        self.script.write_text(_FAKE_CLI)
        self.pids = self.home / "cli.pids"
        self.mode = "sleep"
        self.after_run: Any = None
        self.addCleanup(self._kill_leftovers)

    def _kill_leftovers(self) -> None:
        for pid in self._pids():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)

    def _pids(self) -> list[int]:
        try:
            return [int(part) for part in self.pids.read_text().split()]
        except (OSError, ValueError):
            return []

    def _runner(self, command: list[str], **kwargs: Any) -> Any:
        result = supervise.run(
            [sys.executable, str(self.script), self.mode, str(self.pids), *command[1:]], **kwargs
        )
        if self.after_run is not None:
            self.after_run()
        return result

    def _compose(self, hooks: reading_jobs.Hooks, model: Any = None) -> Any:
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        inner = model or reading.CodexReadingModel(
            self.config,
            runner=self._runner,
            binary_resolver=lambda _name: sys.executable,
            on_spawn=hooks.spawned,
        )
        return reading.produce(
            self.config,
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            entry["revisions"],
            [
                {
                    "fact_id": "f1",
                    "type": "user_message",
                    "by": "",
                    "summary": "ship the parser please",
                    "at": 90.0,
                    "evidence": {"source": "root transcript", "confidence": "exact"},
                    "source_session": {"harness": "claude", "sid": "s1"},
                }
            ],
            now=NOW,
            stamp_text="Codex · read at 10:00",
            model=reading_policy.GuardedModel(
                self.config,
                inner,
                lambda: NOW,
                provider="codex",
                on_reserved=hooks.reserved,
                before_reserve=hooks.before_reserve,
                cancelled=hooks.cancelled,
            ),
            on_phase=hooks.phase,
        )

    def _start(self, compose: Any = None) -> tuple[reading.Job, threading.Thread]:
        job = reading.start_job(self.config, KEY, provider="codex", label="Codex", now=NOW)
        assert job is not None
        record_reading = annotation_store.record_reading
        record_withheld = annotation_store.record_withheld

        def wrote(kind: str, real: Any) -> Any:
            def spy(*args: Any, **kwargs: Any) -> Any:
                self.events.append((kind, kwargs.get("reason"), kwargs.get("spent")))
                return real(*args, **kwargs)

            return spy

        for name, kind in (("record_reading", "reading"), ("record_withheld", "withheld")):
            patcher = mock.patch.object(
                annotation_store,
                name,
                wrote(kind, record_reading if kind == "reading" else record_withheld),
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        thread = reading_jobs.launch(self.application, job, compose or self._compose)
        return job, thread

    def _finish(self, thread: threading.Thread, within: float = 15.0) -> None:
        thread.join(timeout=within)
        self.assertFalse(thread.is_alive(), "the job never finished")

    def _spawned(self) -> list[int]:
        self.assertTrue(_wait_until(lambda: len(self._pids()) == 2), "the fake CLI never started")
        return self._pids()

    def _entry(self) -> Any:
        return annotation_store.find(annotation_store.load(self.config), "claude", "s1")

    def _used(self) -> int:
        return reading_policy.status(self.config, now=NOW)["used"]

    def test_a_reader_who_cancels_mid_call_sees_the_cancelled_sentence_and_one_attempt_counted(
        self,
    ) -> None:
        job, thread = self._start()
        child, grandchild = self._spawned()
        self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
        self._finish(thread)
        entry = self._entry()
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CANCELLED], entry.get("withheld"))
        self.assertEqual(1, entry.get("readings"))
        self.assertEqual(1, self._used())
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)
        self.assertTrue(_wait_until(lambda: not process_alive(child)), "the CLI outlived Cancel")
        self.assertTrue(
            _wait_until(lambda: not process_alive(grandchild)), "its helper outlived Cancel"
        )
        self.assertIsNone(reading.job(self.config, KEY))

    def test_a_reader_who_cancels_before_anything_is_reserved_spends_nothing(self) -> None:
        at_seam, go = threading.Event(), threading.Event()
        reserve = mock.patch.object(reading_policy, "reserve", wraps=reading_policy.reserve)

        class _Held:
            """A model whose availability check is the seam before the reservation."""

            def __call__(self, _prompt: str, **_kw: Any) -> tuple[str, str]:
                raise AssertionError("a cancelled press reached the model")

            @staticmethod
            def available() -> bool:
                at_seam.set()
                go.wait(10)
                return True

        with reserve as reserved:
            job, thread = self._start(lambda hooks: self._compose(hooks, _Held()))
            self.assertTrue(at_seam.wait(10))
            self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
            go.set()
            self._finish(thread)
        reserved.assert_not_called()
        entry = self._entry()
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CANCELLED_UNSENT], entry.get("withheld"))
        self.assertNotIn("readings", entry)
        self.assertEqual(0, self._used())
        self.assertEqual([], sorted((self.home / reading_jobs.MARKER_DIR).glob("*.json*")))

    def test_a_reply_that_arrives_after_cancel_is_never_shown_and_checking_never_lights(
        self,
    ) -> None:
        self.mode = "reply"
        at_reply, go = threading.Event(), threading.Event()

        def compose(hooks: reading_jobs.Hooks) -> Any:
            phase = hooks.phase

            def held(name: str) -> None:
                if name == reading.PHASE_CHECKING:
                    at_reply.set()
                    go.wait(10)
                phase(name)

            hooks.phase = held  # type: ignore[method-assign,assignment]
            return self._compose(hooks)

        job, thread = self._start(compose)
        self.assertTrue(at_reply.wait(10), "the reply never arrived")
        self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
        go.set()
        self._finish(thread)
        self.assertNotIn("reading", [kind for kind, *_ in self.events])
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)
        self.assertNotIn("assessment", self._entry())
        published = [phase for kind, phase, *_ in self.events if kind == "publish"]
        self.assertNotIn(reading.PHASE_CHECKING, published)

    def test_a_cancel_that_meets_a_finished_reading_changes_nothing(self) -> None:
        """After the seal the result is being written: Cancel answers not-running."""
        self.mode = "reply"
        at_record, go = threading.Event(), threading.Event()
        record = reading_jobs._record

        def held(*args: Any, **kwargs: Any) -> bool:
            at_record.set()
            go.wait(10)
            return record(*args, **kwargs)

        with mock.patch.object(reading_jobs, "_record", held):
            job, thread = self._start()
            self.assertTrue(at_record.wait(10))
            self.assertFalse(reading_jobs.cancel(self.application, KEY, job.id))
            self.assertFalse(reading.published_jobs(self.config)[KEY]["cancelling"])
            go.set()
            self._finish(thread)
        self.assertIn("reading", [kind for kind, *_ in self.events])
        self.assertIn("assessment", self._entry())

    def test_a_cancel_just_before_the_seal_discards_the_finished_reading(self) -> None:
        self.mode = "reply"
        at_seal, go = threading.Event(), threading.Event()
        seal = reading.seal_job

        def held(job: reading.Job) -> bool:
            at_seal.set()
            go.wait(10)
            return seal(job)

        with mock.patch.object(reading, "seal_job", held):
            job, thread = self._start()
            self.assertTrue(at_seal.wait(10))
            self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
            go.set()
            self._finish(thread)
        self.assertNotIn("reading", [kind for kind, *_ in self.events])
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)

    def test_a_cancel_landing_between_spawn_and_handover_still_kills_the_cli(self) -> None:
        at_handover, go = threading.Event(), threading.Event()
        hand_over = reading.hand_over
        groups: list[Any] = []

        def held(job: reading.Job, group: Any) -> bool:
            groups.append(group)
            at_handover.set()
            go.wait(10)
            return hand_over(job, group)

        with mock.patch.object(reading, "hand_over", held):
            job, thread = self._start()
            self.assertTrue(at_handover.wait(10))
            # No group on the job yet: the cancel can only set the flag.
            self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
            started = time.monotonic()
            go.set()
            self._finish(thread)
        # Well inside the fake CLI's 60 s: the handover killed it.
        self.assertLess(time.monotonic() - started, 10)
        self.assertTrue(_wait_until(lambda: not process_alive(groups[0].pid)))
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)

    def test_a_cancel_whose_kill_is_unconfirmed_still_says_it_may_be_running(self) -> None:
        with (
            mock.patch.object(supervise.Group, "_kill", return_value=False),
            mock.patch.object(supervise, "REAP_TIMEOUT_SEC", 0.5),
        ):
            job, thread = self._start()
            self._spawned()
            started = time.monotonic()
            self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
            self._finish(thread)
        self.assertLess(time.monotonic() - started, 10, "an unconfirmed kill held the slot")
        self.assertIn(("withheld", reading.WITHHELD_UNSTOPPED, True), self.events)
        self.assertIn("may still be running", self._entry().get("withheld"))
        # The slot is free anyway, as the timeout and shutdown paths free it.
        self.assertTrue(reading.claim(self.config, KEY))
        reading.release(self.config, KEY)

    def test_a_cancelled_outcome_the_store_refused_is_recovered_as_cancelled_not_as_ran(
        self,
    ) -> None:
        with mock.patch.object(
            annotation_store, "_record", return_value=annotation_store.OUTCOME_UNWRITABLE
        ):
            job, thread = self._start()
            self._spawned()
            reading_jobs.cancel(self.application, KEY, job.id)
            self._finish(thread)
        markers = sorted((self.home / reading_jobs.MARKER_DIR).glob("*.json"))
        self.assertEqual([f"{job.id}.json"], [path.name for path in markers])
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        entry = self._entry()
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CANCELLED], entry.get("withheld"))
        self.assertEqual(1, entry.get("readings"))

    def test_a_dashboard_that_died_after_a_cancel_records_the_cancel_at_next_start(
        self,
    ) -> None:
        at_record, go = threading.Event(), threading.Event()
        record = reading_jobs._record
        left: list[str] = []

        def held(*args: Any, **kwargs: Any) -> bool:
            at_record.set()
            go.wait(10)
            return record(*args, **kwargs)

        with mock.patch.object(reading_jobs, "_record", held):
            job, thread = self._start()
            self._spawned()
            reading_jobs.cancel(self.application, KEY, job.id)
            self.assertTrue(at_record.wait(10))
            # What a dashboard that died here would leave for the next start.
            left.append((self.home / reading_jobs.MARKER_DIR / f"{job.id}.json").read_text())
            go.set()
            self._finish(thread)
        self.assertEqual(reading.WITHHELD_CANCELLED, json.loads(left[0]).get("reason"))
        other = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, other, True)
        config, state = make_runtime(
            state_home=str(other), state_dir=other, annotations_enabled=True
        )
        annotation_store.annotate(config, state, "claude", "s1", goal="g", output="", now=10.0)
        (other / reading_jobs.MARKER_DIR).mkdir()
        (other / reading_jobs.MARKER_DIR / f"{job.id}.json").write_text(left[0])
        reading_jobs.recover(_Application(config, state, []), alive=lambda _pid: False)
        entry = annotation_store.find(annotation_store.load(config), "claude", "s1")
        assert entry is not None
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CANCELLED], entry.get("withheld"))

    def test_the_slot_frees_only_after_the_cli_is_reaped_and_its_files_are_gone(self) -> None:
        reaped, go = threading.Event(), threading.Event()

        def hold() -> None:
            reaped.set()
            go.wait(10)

        self.after_run = hold
        job, thread = self._start()
        child, _ = self._spawned()
        self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
        self.assertTrue(reaped.wait(10))
        # Reaped, and codex_exec's `finally` has not run: the reply file is still
        # there, so the slot and the published job must be too.
        self.assertFalse(process_alive(child))
        self.assertTrue(list(self.home.glob("observer-model-*")))
        self.assertIsNone(
            reading.start_job(self.config, KEY, provider="codex", label="Codex", now=NOW)
        )
        # A reload now draws the same box, with Cancel shown as finishing.
        self.assertTrue(reading.published_jobs(self.config)[KEY]["cancelling"])
        go.set()
        self._finish(thread)
        self.assertEqual([], list(self.home.glob("observer-model-*")))
        self.assertNotIn(KEY, reading.published_jobs(self.config))

    def test_a_cancel_naming_another_job_or_none_stops_nothing(self) -> None:
        job, thread = self._start()
        child, _ = self._spawned()
        self.assertFalse(reading_jobs.cancel(self.application, KEY, "not-the-job"))
        self.assertFalse(reading_jobs.cancel(self.application, "claude:other", job.id))
        self.assertFalse(reading.published_jobs(self.config)[KEY]["cancelling"])
        self.assertTrue(process_alive(child))
        reading_jobs.cancel(self.application, KEY, job.id)
        self._finish(thread)

    def test_a_job_nobody_cancelled_publishes_cancelling_false(self) -> None:
        """A default is not a measurement: the flag is checked on the boring job too."""
        job = reading.start_job(self.config, KEY, provider="codex", label="Codex", now=NOW)
        assert job is not None
        self.assertIs(False, reading.published_jobs(self.config)[KEY]["cancelling"])
        self.assertTrue(reading.cancel_job(self.config, KEY, job.id, now=NOW)[0])
        self.assertIs(True, reading.published_jobs(self.config)[KEY]["cancelling"])
        # The handle is never published, cancelled or not.
        self.assertNotIn("group", reading.published_jobs(self.config)[KEY])

    def test_a_cancel_made_before_a_shutdown_is_not_retold_as_the_stop(self) -> None:
        job, thread = self._start()
        self._spawned()
        reading_jobs.cancel(self.application, KEY, job.id)
        supervise._SHUTDOWN.set()
        self._finish(thread)
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)

    # Correction round (S6 review).

    def test_a_cancel_between_the_seams_check_and_the_reservation_spends_nothing(self) -> None:
        """Spend F1: the line is the reservation itself, not the seam's first look."""
        checked, go = threading.Event(), threading.Event()
        real_cancelled = reading_jobs.Hooks.cancelled

        def cancelled(hooks: reading_jobs.Hooks) -> bool:
            answer = real_cancelled(hooks)
            checked.set()
            go.wait(10)
            return answer

        with (
            mock.patch.object(reading_jobs.Hooks, "cancelled", cancelled),
            mock.patch.object(supervise, "_spawn", wraps=supervise._spawn) as spawn,
            mock.patch.object(reading_policy, "reserve", wraps=reading_policy.reserve) as reserve,
        ):
            job, thread = self._start()
            self.assertTrue(checked.wait(10))
            self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
            go.set()
            self._finish(thread)
        reserve.assert_not_called()
        spawn.assert_not_called()
        self.assertEqual(0, self._used())
        entry = self._entry()
        self.assertNotIn("readings", entry)
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_CANCELLED_UNSENT], entry.get("withheld"))
        self.assertEqual([], sorted((self.home / reading_jobs.MARKER_DIR).glob("*.json*")))

    def test_a_cancel_before_the_commit_point_is_not_reported_as_a_failed_job(self) -> None:
        """Verify N2: the cancel is an outcome, so no "a reading job failed" line is written."""
        checked, go = threading.Event(), threading.Event()
        real_cancelled = reading_jobs.Hooks.cancelled

        def cancelled(hooks: reading_jobs.Hooks) -> bool:
            answer = real_cancelled(hooks)
            checked.set()
            go.wait(10)
            return answer

        with mock.patch.object(reading_jobs.Hooks, "cancelled", cancelled):
            job, thread = self._start()
            self.assertTrue(checked.wait(10))
            self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
            go.set()
            self._finish(thread)
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED_UNSENT, False), self.events)
        self.assertEqual([], self.application.diagnostics)

    def test_a_cancel_after_the_commit_point_is_charged_and_its_marker_says_cancelled(
        self,
    ) -> None:
        """The other side of the line: committed, so charged once, and a restart says why."""
        at_record, go = threading.Event(), threading.Event()
        record, reserve = reading_jobs._record, reading_policy.reserve
        holder: dict[str, Any] = {}
        left: list[str] = []

        def late(*args: Any, **kwargs: Any) -> Any:
            self.assertTrue(reading_jobs.cancel(self.application, KEY, holder["job"].id))
            return reserve(*args, **kwargs)

        def held(*args: Any, **kwargs: Any) -> bool:
            at_record.set()
            go.wait(10)
            return record(*args, **kwargs)

        with (
            mock.patch.object(reading_policy, "reserve", late),
            mock.patch.object(reading_jobs, "_record", held),
        ):
            real_start = reading.start_job

            def start(*args: Any, **kwargs: Any) -> Any:
                holder["job"] = real_start(*args, **kwargs)
                return holder["job"]

            with mock.patch.object(reading, "start_job", start):
                job, thread = self._start()
            self.assertTrue(at_record.wait(15))
            left.append((self.home / reading_jobs.MARKER_DIR / f"{job.id}.json").read_text())
            go.set()
            self._finish(thread)
        self.assertEqual(reading.WITHHELD_CANCELLED, json.loads(left[0]).get("reason"))
        self.assertEqual(1, self._used())
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)

    def test_a_cancel_after_the_stop_began_while_preparing_keeps_the_stops_word(self) -> None:
        """Spend F2: both are unspent, and the stop came first, so its sentence stands."""
        at_seam, go = threading.Event(), threading.Event()

        class _Held:
            def __call__(self, _prompt: str, **_kw: Any) -> tuple[str, str]:
                raise AssertionError("a stopping dashboard reached the model")

            @staticmethod
            def available() -> bool:
                at_seam.set()
                go.wait(10)
                return True

        job, thread = self._start(lambda hooks: self._compose(hooks, _Held()))
        self.assertTrue(at_seam.wait(10))
        supervise._SHUTDOWN.set()
        self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
        go.set()
        self._finish(thread)
        self.assertIn(("withheld", reading.WITHHELD_STOPPING, False), self.events)
        self.assertNotIn("readings", self._entry())

    def test_a_cancel_after_the_dashboard_began_stopping_keeps_the_stops_own_word(self) -> None:
        job, thread = self._start()
        self._spawned()
        supervise._SHUTDOWN.set()
        self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
        self._finish(thread)
        self.assertIn(("withheld", reading.WITHHELD_INTERRUPTED, True), self.events)
        self.assertNotIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)

    def test_a_second_cancel_after_the_stop_does_not_rewrite_who_came_first(self) -> None:
        job, thread = self._start()
        self._spawned()
        self.assertTrue(reading_jobs.cancel(self.application, KEY, job.id))
        supervise._SHUTDOWN.set()
        reading_jobs.cancel(self.application, KEY, job.id)
        self._finish(thread)
        self.assertIn(("withheld", reading.WITHHELD_CANCELLED, True), self.events)

    def test_the_cancel_outcome_counts_exactly_what_was_charged(self) -> None:
        """Either witness of a charge makes the cancel spent; neither makes it unspent."""
        job = reading.start_job(self.config, KEY, provider="codex", label="Codex", now=NOW)
        assert job is not None
        self.assertEqual(
            (None, reading.WITHHELD_CANCELLED, True),
            reading_jobs._cancelled(job, (None, reading.WITHHELD_MODEL_FAILED, True), spent=False),
        )
        self.assertEqual(
            (None, reading.WITHHELD_CANCELLED, True),
            reading_jobs._cancelled(job, (None, reading.WITHHELD_LEDGER_EMPTY, False), spent=True),
        )
        self.assertEqual(
            (None, reading.WITHHELD_CANCELLED_UNSENT, False),
            reading_jobs._cancelled(job, (None, reading.WITHHELD_LEDGER_EMPTY, False), spent=False),
        )

    def test_a_cancel_racing_the_stored_outcome_never_leaves_a_marker_behind(self) -> None:
        """The marker lock: an unlocked rewrite resurrects a marker the store answered for."""
        real = runtime_io.atomic_write_owner_only
        holder: dict[str, Any] = {}

        def write(path: str, text: str) -> Any:
            if threading.current_thread() is holder.get("canceller") and "reason" in text:
                holder["job"].group.cancel()
                holder["thread"].join(3)
            return real(path, text)

        with mock.patch.object(runtime_io, "atomic_write_owner_only", write):
            job, thread = self._start()
            self._spawned()
            holder.update(job=job, thread=thread)
            canceller = threading.Thread(
                target=reading_jobs.cancel, args=(self.application, KEY, job.id)
            )
            holder["canceller"] = canceller
            canceller.start()
            canceller.join(15)
            self._finish(thread)
        self.assertEqual([], sorted((self.home / reading_jobs.MARKER_DIR).glob("*.json*")))

    # DRC-4712 and DRC-4713: the stop's line is the reservation, and a job the
    # dashboard died in is counted from the ledger. Barriers, never sleeps.

    def _held_at(self, target: Any, name: str, *, after: bool) -> tuple[Any, Any, Any]:
        """Patch `target.name` to stop at a barrier before or after the real call."""
        real = getattr(target, name)
        at, go = threading.Event(), threading.Event()

        def held(*args: Any, **kwargs: Any) -> Any:
            if not after:
                at.set()
                go.wait(10)
            answer = real(*args, **kwargs)
            if after:
                at.set()
                go.wait(10)
            return answer

        return mock.patch.object(target, name, held), at, go

    def test_a_shutdown_between_the_seams_check_and_the_reservation_spends_nothing(self) -> None:
        patch, at, go = self._held_at(reading_jobs.Hooks, "before_reserve", after=True)
        with patch, mock.patch.object(supervise, "_spawn", wraps=supervise._spawn) as spawn:
            _job, thread = self._start()
            self.assertTrue(at.wait(10))
            supervise.kill_all()
            go.set()
            self._finish(thread)
        spawn.assert_not_called()
        self.assertEqual(0, self._used())
        self.assertIn(("withheld", reading.WITHHELD_STOPPING, False), self.events)
        self.assertNotIn("readings", self._entry())
        self.assertEqual([], sorted((self.home / reading_jobs.MARKER_DIR).glob("*.json*")))

    def test_a_shutdown_after_the_reservation_is_spent_and_interrupted(self) -> None:
        patch, at, go = self._held_at(reading_policy, "reserve", after=True)
        with patch, mock.patch.object(supervise, "_spawn", wraps=supervise._spawn) as spawn:
            _job, thread = self._start()
            self.assertTrue(at.wait(10))
            supervise.kill_all()
            go.set()
            self._finish(thread)
        spawn.assert_not_called()
        self.assertEqual(1, self._used())
        self.assertIn(("withheld", reading.WITHHELD_INTERRUPTED, True), self.events)
        self.assertEqual(1, self._entry().get("readings"))

    def _died_before_the_write(self) -> tuple[Any, list[str]]:
        """What a dashboard that died just before the outcome's write leaves: its marker."""
        left: list[str] = []

        def record(_application: Any, job: reading.Job, _outcome: Any, **_kwargs: Any) -> bool:
            left.append((self.home / reading_jobs.MARKER_DIR / f"{job.id}.json").read_text())
            return True

        return mock.patch.object(reading_jobs, "_record", record), left

    def _restart_with(self, marker: str) -> Any:
        markers = self.home / reading_jobs.MARKER_DIR
        markers.mkdir(exist_ok=True)
        (markers / f"{json.loads(marker)['id']}.json").write_text(marker)
        reading_jobs.recover(self.application, alive=lambda _pid: False)
        return self._entry()

    def test_a_dashboard_killed_between_the_marker_and_the_reservation_recovers_unspent(
        self,
    ) -> None:
        real = reading_jobs.Hooks.before_reserve

        def died(hooks: reading_jobs.Hooks) -> Any:
            real(hooks)
            raise RuntimeError("the process ends here")

        died_here, left = self._died_before_the_write()
        with died_here, mock.patch.object(reading_jobs.Hooks, "before_reserve", died):
            _job, thread = self._start()
            self._finish(thread)
        entry = self._restart_with(left[0])
        self.assertNotIn("readings", entry)
        self.assertEqual(0, self._used())
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_STOPPING], entry.get("withheld"))

    def test_a_dashboard_killed_after_the_reservation_recovers_spent(self) -> None:
        self.mode = "reply"
        died_here, left = self._died_before_the_write()
        with died_here:
            _job, thread = self._start()
            self._finish(thread)
        entry = self._restart_with(left[0])
        self.assertEqual(1, entry.get("readings"))
        self.assertEqual(1, self._used())
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_INTERRUPTED], entry.get("withheld"))

    def test_a_stop_at_the_reservation_then_a_death_before_the_write_recovers_unspent(
        self,
    ) -> None:
        patch, at, go = self._held_at(reading_jobs.Hooks, "before_reserve", after=True)
        died_here, left = self._died_before_the_write()
        with patch, died_here:
            _job, thread = self._start()
            self.assertTrue(at.wait(10))
            supervise.kill_all()
            go.set()
            self._finish(thread)
        entry = self._restart_with(left[0])
        self.assertNotIn("readings", entry)
        self.assertEqual(0, self._used())
        self.assertEqual(reading.WITHHELD[reading.WITHHELD_STOPPING], entry.get("withheld"))

    def test_the_cancel_sentences_say_what_the_reader_may_rely_on(self) -> None:
        spent = reading.WITHHELD[reading.WITHHELD_CANCELLED]
        unsent = reading.WITHHELD[reading.WITHHELD_CANCELLED_UNSENT]
        self.assertEqual(
            "The analysis was cancelled before it finished. Nothing is shown from it, the "
            "attempt still counts, and a fresh press is the only retry.",
            spent,
        )
        self.assertEqual(
            "The analysis was cancelled before anything was sent. Nothing was sent or spent.",
            unsent,
        )
        for sentence in (spent, unsent):
            self.assertNotIn("You cancelled", sentence)


class TheThreadIsNamedForItsJobTest(unittest.TestCase):
    def test_a_job_thread_carries_its_id(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, state = make_runtime(state_home=home, state_dir=Path(home))
        job = reading.start_job(config, KEY, provider="codex", label="Codex", now=1.0)
        assert job is not None
        release = threading.Event()
        application: Any = _Application(config, state, [])
        thread = reading_jobs.launch(
            application,
            job,
            lambda _hooks: (release.wait(5), (None, reading.WITHHELD_LEDGER_EMPTY, False))[1],
        )
        try:
            self.assertEqual(f"{reading_jobs.THREAD_PREFIX}{job.id}", thread.name)
            self.assertTrue(thread.daemon)
        finally:
            release.set()
            thread.join(5)


if __name__ == "__main__":
    unittest.main()
