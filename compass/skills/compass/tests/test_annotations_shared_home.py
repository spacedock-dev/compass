"""DRC-4661: two dashboards sharing one Compass home lose no saved intent.

Every writer in `annotations` re-reads the file under `state.annotation_lock`,
which is a `threading.Lock` on one `RuntimeState`. A second dashboard is a
second state, usually a second process, so that lock never met it: a writer
paused after its read let the other dashboard commit, then renamed its older
copy over the newer one. Two states in one process reproduce it exactly,
because each carries its own lock, and the last test runs two real processes.

The rule each case holds: every write that answered `stored` is still on
disk afterwards, and no revision number is used twice. A guarded writer that
lost the race is refused with the stale-revision answer it already had.
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import reading as runtime_reading
from compass_runtime import sessions as runtime_sessions
from compass_runtime.state import RuntimeState, build_runtime_state

from .support import make_runtime

if TYPE_CHECKING:
    from collections.abc import Callable

SKILL_DIR = Path(__file__).resolve().parents[1]
SID = "0123456789abcdef-shared-home"
FIRST = "Add retry with backoff to the webhook handler."
START = 1_800_000_000.0
FIRST_AT = START + 5
# How long the second dashboard is given to commit while the first is paused
# after its read. Before the fix it committed in milliseconds.
BLOCKED_FOR = 0.6


def _row(**extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict(runtime_sessions.base_session("claude", SID, "billing"))
    row.update(
        {
            "project": "billing",
            "state": "working",
            "active": True,
            "last_activity": START + 3600,
            "first_prompt": FIRST,
            "first_prompt_at": FIRST_AT,
        }
    )
    row.update(extra)
    return row


class _PauseAfterRead:
    """Stop one thread straight after its read of the store, until released."""

    def __init__(self) -> None:
        self.paused = threading.Event()
        self.release = threading.Event()
        self.thread: threading.Thread | None = None
        self._real = annotation_store._read_store

    def __call__(self, config: Any) -> Any:
        store = self._real(config)
        if threading.current_thread() is self.thread and not self.paused.is_set():
            self.paused.set()
            self.release.wait(10)
        return store


class _SharedHomeCase(unittest.TestCase):
    def setUp(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        self.config, self.first = make_runtime(state_home=home, state_dir=Path(home))
        # The second dashboard: its own state, so its own `annotation_lock`.
        self.second: RuntimeState = build_runtime_state(self.config, started=START)

    def entry(self) -> Any:
        return annotation_store.find(annotation_store._read(self.config), "claude", SID)

    def race(self, first: Callable[[], str], second: Callable[[], str]) -> tuple[str, str, bool]:
        """Run `first` paused after its read, then `second`, then resume `first`.

        Returns both outcomes and whether `second` committed while `first` sat
        between its read and its write, which is the window the fix closes.
        """
        pause = _PauseAfterRead()
        outcomes: dict[str, str] = {}

        def run(name: str, write: Callable[[], str]) -> None:
            outcomes[name] = write()

        one = threading.Thread(target=run, args=("first", first))
        two = threading.Thread(target=run, args=("second", second))
        pause.thread = one
        with mock.patch.object(annotation_store, "_read_store", pause):
            one.start()
            try:
                self.assertTrue(pause.paused.wait(10), "the first writer never read the store")
                two.start()
                two.join(BLOCKED_FOR)
                committed_while_paused = not two.is_alive()
            finally:
                pause.release.set()
                one.join(20)
                if two.ident is not None:
                    two.join(20)
        self.assertFalse(one.is_alive() or two.is_alive(), "a writer never finished")
        return outcomes["first"], outcomes["second"], committed_while_paused

    def goal(self, state: RuntimeState, text: str, now: float) -> Callable[[], str]:
        return lambda: annotation_store.annotate(
            self.config, state, "claude", SID, goal=text, now=now
        )

    def hold(self, *, stop: bool = False) -> subprocess.Popen[bytes]:
        """Hold the store's lock from a second real process until the test ends.

        `stop` suspends the holder once it holds the lock, a dashboard stopped
        with Ctrl-Z in the middle of a write. Windows has no SIGSTOP, and a
        holder asleep inside the lock is the same thing to the waiter.
        """
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _HOLD_LOCK,
                str(SKILL_DIR),
                annotation_store.lock_path(self.config),
                "stop" if stop and hasattr(signal, "SIGSTOP") else "sleep",
            ],
            stdout=subprocess.PIPE,
        )
        self.addCleanup(_kill, holder)
        assert holder.stdout is not None
        # rstrip: a Windows child writes "\r\n" through its text-mode stdout.
        self.assertEqual(b"held", holder.stdout.readline().rstrip())
        return holder

    def assert_numbers_unique(self, entry: Any) -> None:
        numbers = [revision["n"] for revision in entry["revisions"]]
        self.assertEqual(sorted(set(numbers)), numbers)


class TheIssuesInterleavingTest(_SharedHomeCase):
    """The reproduction on the issue, step for step."""

    def test_an_older_save_resumed_after_a_newer_commit_keeps_both_revisions(self) -> None:
        first, second, overlapped = self.race(
            self.goal(self.first, "Older goal typed at 100", START + 100),
            self.goal(self.second, "Newer goal typed at 101", START + 101),
        )

        self.assertFalse(overlapped, "the second dashboard committed inside the first's window")
        self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
        entry = self.entry()
        self.assertEqual([1, 2], [revision["n"] for revision in entry["revisions"]])
        self.assertEqual(
            ["Older goal typed at 100", "Newer goal typed at 101"],
            [revision["goal"] for revision in entry["revisions"]],
        )


class EveryWriterSharesTheBoundaryTest(_SharedHomeCase):
    """One case per writer: a stale writer never drops what the other committed."""

    def seed(self, goal: str = "Seeded goal", lines: list[str] | None = None) -> None:
        outcome = annotation_store.annotate(
            self.config, self.first, "claude", SID, goal=goal, lines=lines, now=START + 50
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, outcome)

    def add_line(self, state: RuntimeState, text: str, fact: str, **over: Any) -> Callable[[], str]:
        arguments: dict[str, Any] = {
            "source_id": fact,
            "text": text,
            "entry_at": FIRST_AT + 60,
            "expected_revision": 0,
            "now": FIRST_AT + 120,
        }
        arguments.update(over)
        return lambda: annotation_store.add_direction(self.config, state, _row(), **arguments)

    def test_outcome_lines_a_stale_list_is_refused_rather_than_written_over(self) -> None:
        def lines(state: RuntimeState, text: str) -> Callable[[], str]:
            return lambda: annotation_store.annotate(
                self.config, state, "claude", SID, lines=[text], expected_revision=0, now=START
            )

        first, second, overlapped = self.race(
            lines(self.first, "First dashboard's line"),
            lines(self.second, "Second dashboard's line"),
        )

        self.assertFalse(overlapped)
        self.assertEqual(annotation_store.OUTCOME_STORED, first)
        self.assertEqual(annotation_store.OUTCOME_REFUSED, second)
        entry = self.entry()
        self.assertEqual(
            ["First dashboard's line"], [x["text"] for x in entry["revisions"][-1]["lines"]]
        )
        self.assert_numbers_unique(entry)

    def test_prompt_adoption_never_replaces_a_goal_committed_after_its_empty_check(self) -> None:
        adopt = lambda: annotation_store.adopt(  # noqa: E731
            self.config,
            self.first,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=START + 100,
        )

        first, second, overlapped = self.race(
            adopt, self.goal(self.second, "Typed on the other dashboard", START + 101)
        )

        self.assertFalse(overlapped)
        self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
        entry = self.entry()
        self.assertEqual("Typed on the other dashboard", entry["revisions"][-1]["goal"])
        self.assertEqual(
            [FIRST, "Typed on the other dashboard"], [r["goal"] for r in entry["revisions"]]
        )
        self.assert_numbers_unique(entry)

    def test_add_direction_a_stale_line_is_refused_and_the_committed_one_stays(self) -> None:
        first, second, overlapped = self.race(
            self.add_line(self.first, "Use the placeholder lexer", "fact:aaaaaaaaaaaaaaaa"),
            self.add_line(self.second, "Keep the parser tests", "fact:bbbbbbbbbbbbbbbb"),
        )

        self.assertFalse(overlapped)
        self.assertEqual(annotation_store.OUTCOME_STORED, first)
        self.assertEqual(annotation_store.OUTCOME_REFUSED, second)
        entry = self.entry()
        self.assertEqual(
            ["fact:aaaaaaaaaaaaaaaa"],
            [line["source_id"] for line in entry["revisions"][-1]["lines"]],
        )
        self.assertIsNotNone(entry.get("settled"))

    def test_outcome_line_adoption_and_its_settlement_survive_a_typed_goal(self) -> None:
        adopting = self.add_line(
            self.first,
            "Use the placeholder lexer",
            "fact:aaaaaaaaaaaaaaaa",
            adopt="first-prompt",
            expected_prompt=FIRST,
            expected_prompt_at=FIRST_AT,
        )

        first, second, overlapped = self.race(
            adopting, self.goal(self.second, "Typed on the other dashboard", FIRST_AT + 130)
        )

        self.assertFalse(overlapped)
        self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
        entry = self.entry()
        latest = entry["revisions"][-1]
        self.assertEqual("Typed on the other dashboard", latest["goal"])
        self.assertEqual(["fact:aaaaaaaaaaaaaaaa"], [x.get("source_id") for x in latest["lines"]])
        self.assertEqual(FIRST_AT + 60, entry["settled"]["through"])
        self.assert_numbers_unique(entry)

    def test_keep_over_a_draft_settles_without_losing_the_other_dashboards_goal(self) -> None:
        keep = lambda: annotation_store.adopt(  # noqa: E731
            self.config,
            self.first,
            _row(),
            source="first-prompt",
            expected_text=FIRST,
            expected_at=FIRST_AT,
            now=START + 100,
            expected_revision=0,
            settle_through=START + 90,
        )

        first, second, overlapped = self.race(
            keep, self.goal(self.second, "Typed on the other dashboard", START + 101)
        )

        self.assertFalse(overlapped)
        self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
        entry = self.entry()
        self.assertEqual("Typed on the other dashboard", entry["revisions"][-1]["goal"])
        self.assertEqual(START + 90, entry["settled"]["through"])
        self.assert_numbers_unique(entry)

    def test_a_settlement_and_a_newer_goal_both_stand_in_either_order(self) -> None:
        def settle(state: RuntimeState) -> Callable[[], str]:
            return lambda: annotation_store.settle(
                self.config, state, "claude", SID, through=START + 80, now=START + 100
            )

        for order in ("settle-first", "goal-first"):
            with self.subTest(order=order):
                self.setUp()
                self.seed()
                if order == "settle-first":
                    first, second, overlapped = self.race(
                        settle(self.first), self.goal(self.second, "Newer goal", START + 101)
                    )
                else:
                    first, second, overlapped = self.race(
                        self.goal(self.first, "Newer goal", START + 101), settle(self.second)
                    )
                self.assertFalse(overlapped)
                self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
                entry = self.entry()
                self.assertEqual("Newer goal", entry["revisions"][-1]["goal"])
                self.assertEqual(START + 80, entry["settled"]["through"])
                self.assert_numbers_unique(entry)

    def test_a_discard_is_not_undone_by_a_save_that_read_before_it(self) -> None:
        self.seed()
        clear = lambda: annotation_store.clear(  # noqa: E731
            self.config, self.second, "claude", SID, now=START + 102
        )

        first, second, overlapped = self.race(
            self.goal(self.first, "Saved just before the discard", START + 101), clear
        )

        self.assertFalse(overlapped)
        self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
        entry = self.entry()
        self.assertTrue(annotation_store.is_discarded(entry))
        self.assertEqual(2, annotation_store.discarded_revision(entry))

    def test_a_save_after_a_discard_never_reuses_a_revision_number(self) -> None:
        self.seed()
        clear = lambda: annotation_store.clear(  # noqa: E731
            self.config, self.first, "claude", SID, now=START + 100
        )

        first, second, overlapped = self.race(
            clear, self.goal(self.second, "Typed after the discard", START + 101)
        )

        self.assertFalse(overlapped)
        self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
        entry = self.entry()
        # Revision 1 was discarded, so the save over the record is 2, not 1.
        self.assertEqual([2], [revision["n"] for revision in entry["revisions"]])
        self.assertEqual("Typed after the discard", entry["revisions"][-1]["goal"])

    def test_a_reading_outcome_does_not_write_away_a_newer_goal(self) -> None:
        self.seed()
        withheld = lambda: annotation_store.record_withheld(  # noqa: E731
            self.config,
            self.first,
            "claude",
            SID,
            reason=next(iter(runtime_reading.WITHHELD)),
            spent=True,
            job_id="5a4ed0e0f0a1e5",
        )

        first, second, overlapped = self.race(
            withheld, self.goal(self.second, "Newer goal", START + 101)
        )

        self.assertFalse(overlapped)
        self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
        entry = self.entry()
        self.assertEqual("Newer goal", entry["revisions"][-1]["goal"])
        self.assertEqual(1, entry.get("readings"))
        self.assertIn("5a4ed0e0f0a1e5", entry.get("jobs", ()))

    def test_a_discard_drawn_against_an_older_revision_withdraws_nothing(self) -> None:
        # This dashboard drew revision 1; the other saved revision 2 since.
        self.seed()
        newer = annotation_store.annotate(
            self.config, self.second, "claude", SID, goal="Newer words", now=START + 101
        )
        self.assertEqual(annotation_store.OUTCOME_STORED, newer)
        receipt: dict[str, int] = {}

        outcome = annotation_store.clear(
            self.config,
            self.first,
            "claude",
            SID,
            now=START + 102,
            expected_revision=1,
            receipt=receipt,
        )

        self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
        self.assertEqual({}, receipt)
        entry = self.entry()
        self.assertFalse(annotation_store.is_discarded(entry))
        self.assertEqual(
            ["Seeded goal", "Newer words"], [revision["goal"] for revision in entry["revisions"]]
        )
        # The press that names what it drew still discards.
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.clear(
                self.config, self.first, "claude", SID, now=START + 103, expected_revision=2
            ),
        )
        self.assertEqual(2, annotation_store.discarded_revision(self.entry()))

    def test_a_discard_naming_a_revision_that_is_not_a_number_is_refused(self) -> None:
        self.seed()
        for bad in ("1", True, 1.0):
            with self.subTest(bad=bad):
                outcome = annotation_store.clear(
                    self.config, self.first, "claude", SID, now=START + 102, expected_revision=bad
                )
                self.assertEqual(annotation_store.OUTCOME_REFUSED, outcome)
                self.assertFalse(annotation_store.is_discarded(self.entry()))

    def test_a_guarded_discard_racing_a_newer_save_never_takes_the_newer_words(self) -> None:
        self.seed()
        clear = lambda: annotation_store.clear(  # noqa: E731
            self.config, self.second, "claude", SID, now=START + 102, expected_revision=1
        )

        first, second, overlapped = self.race(
            self.goal(self.first, "Saved just before the discard", START + 101), clear
        )

        self.assertFalse(overlapped)
        self.assertEqual(
            (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_REFUSED), (first, second)
        )
        entry = self.entry()
        self.assertFalse(annotation_store.is_discarded(entry))
        self.assertEqual("Saved just before the discard", entry["revisions"][-1]["goal"])

    def test_forget_does_not_write_away_a_session_saved_while_it_swept(self) -> None:
        self.seed()
        annotation_store.clear(self.config, self.first, "claude", SID, now=START + 60)
        other = lambda: annotation_store.annotate(  # noqa: E731
            self.config, self.second, "claude", "another-session", goal="Kept", now=START + 101
        )

        first, second, overlapped = self.race(lambda: annotation_store.forget(self.config), other)

        self.assertFalse(overlapped)
        self.assertEqual(annotation_store.FORGET_SWEPT, first)
        self.assertEqual(annotation_store.OUTCOME_STORED, second)
        entries = annotation_store._read(self.config)
        self.assertIsNone(annotation_store.find(entries, "claude", SID))
        kept = annotation_store.find(entries, "claude", "another-session")
        assert kept is not None
        self.assertEqual("Kept", kept["revisions"][-1]["goal"])


class ABusyStoreIsReportedNotWrittenTest(_SharedHomeCase):
    """Another process holding the store past the wait: nothing is written, and it says so."""

    OTHER = "another-session"

    def test_a_save_that_cannot_take_the_lock_answers_unwritable_and_writes_nothing(self) -> None:
        said: list[str] = []
        self.hold()
        with mock.patch.object(annotation_store, "_STORE_LOCK_WAIT_SECONDS", 0.2):
            outcome = annotation_store.annotate(
                self.config,
                self.first,
                "claude",
                SID,
                goal="Typed while another process held the store",
                now=START,
                diagnostic_sink=said.append,
            )

        self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, outcome)
        self.assertFalse(os.path.exists(annotation_store.store_path(self.config)))
        self.assertTrue(any("annotation store" in line for line in said), said)

    def writers(self) -> dict[str, Callable[[], str]]:
        """Every writer, each one that would store if the lock were free."""
        config, state = self.config, self.first
        fresh = _row(sid="fresh-session")
        return {
            "goal": lambda: annotation_store.annotate(
                config, state, "claude", SID, goal="A newer goal", now=START + 200
            ),
            "lines": lambda: annotation_store.annotate(
                config, state, "claude", SID, lines=["A line"], expected_revision=1, now=START
            ),
            "reading outcome": lambda: annotation_store.record_reading(
                config, state, "claude", SID, assessment=_assessment(), job_id="0a0b0c0d0e0f01"
            ),
            "withheld outcome": lambda: annotation_store.record_withheld(
                config,
                state,
                "claude",
                SID,
                reason=next(iter(runtime_reading.WITHHELD)),
                spent=True,
                job_id="0a0b0c0d0e0f02",
            ),
            "settle": lambda: annotation_store.settle(
                config, state, "claude", SID, through=START + 80, now=START + 200
            ),
            "adoption": lambda: annotation_store.adopt(
                config,
                state,
                fresh,
                source="first-prompt",
                expected_text=FIRST,
                expected_at=FIRST_AT,
                now=START + 200,
            ),
            "adoption with settle_through": lambda: annotation_store.adopt(
                config,
                state,
                fresh,
                source="first-prompt",
                expected_text=FIRST,
                expected_at=FIRST_AT,
                now=START + 200,
                expected_revision=0,
                settle_through=START + 90,
            ),
            "add_direction": lambda: annotation_store.add_direction(
                config,
                state,
                fresh,
                source_id="fact:aaaaaaaaaaaaaaaa",
                text="Use the placeholder lexer",
                entry_at=FIRST_AT + 60,
                expected_revision=0,
                now=FIRST_AT + 120,
            ),
            "discard": lambda: annotation_store.clear(
                config, state, "claude", SID, now=START + 200
            ),
            "--forget": lambda: annotation_store.forget(config),
        }

    def test_every_writer_refuses_while_another_process_holds_the_store(self) -> None:
        annotation_store.annotate(self.config, self.first, "claude", SID, goal="Seed", now=START)
        annotation_store.annotate(
            self.config, self.first, "claude", self.OTHER, goal="Gone", now=START
        )
        annotation_store.clear(self.config, self.first, "claude", self.OTHER, now=START + 1)
        store = Path(annotation_store.store_path(self.config))
        before = store.read_bytes()
        cached = annotation_store.refresh(self.config, self.first)
        self.hold()
        refusals = {
            "--forget": annotation_store.FORGET_UNWRITABLE,
        }
        with (
            mock.patch.object(annotation_store, "_STORE_LOCK_WAIT_SECONDS", 0.1),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for name, write in self.writers().items():
                with self.subTest(writer=name):
                    outcome = write()
                    self.assertEqual(
                        refusals.get(name, annotation_store.OUTCOME_UNWRITABLE), outcome
                    )
                    self.assertEqual(before, store.read_bytes())
                    self.assertEqual(cached, annotation_store.active(self.config, self.first))

    def test_every_writer_stores_once_the_store_is_free(self) -> None:
        # The other half of the refusal test: each writer above is one that
        # writes when nothing holds the lock, so its refusal is the lock's.
        for name in self.writers():
            with self.subTest(writer=name):
                self.setUp()
                annotation_store.annotate(
                    self.config, self.first, "claude", SID, goal="Seed", now=START
                )
                annotation_store.annotate(
                    self.config, self.first, "claude", self.OTHER, goal="Gone", now=START
                )
                annotation_store.clear(self.config, self.first, "claude", self.OTHER, now=START + 1)
                with contextlib.redirect_stdout(io.StringIO()):
                    outcome = self.writers()[name]()
                self.assertIn(
                    outcome, (annotation_store.OUTCOME_STORED, annotation_store.FORGET_SWEPT)
                )

    def test_a_stuck_holder_costs_each_waiting_save_one_wait_and_readers_none(self) -> None:
        annotation_store.annotate(self.config, self.first, "claude", SID, goal="Seed", now=START)
        wait = 1.5
        self.hold(stop=True)
        took: dict[str, tuple[str, float]] = {}

        def timed(name: str, call: Callable[[], object]) -> None:
            began = time.monotonic()
            answer = call()
            took[name] = (str(answer)[:20], time.monotonic() - began)

        def save(name: str) -> Callable[[], str]:
            return lambda: annotation_store.annotate(
                self.config, self.first, "claude", SID, goal=f"typed {name}", now=START + 9
            )

        calls: list[tuple[str, Callable[[], object]]] = [
            ("save1", save("save1")),
            ("save2", save("save2")),
            ("save3", save("save3")),
            ("refresh", lambda: annotation_store.refresh(self.config, self.first)),
            ("active", lambda: annotation_store.active(self.config, self.first)),
        ]
        threads = []
        with (
            mock.patch.object(annotation_store, "_STORE_LOCK_WAIT_SECONDS", wait),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for name, call in calls:
                thread = threading.Thread(target=timed, args=(name, call))
                thread.start()
                threads.append(thread)
                time.sleep(0.1)
            for thread in threads:
                thread.join(30)

        self.assertEqual({name for name, _ in calls}, set(took), took)
        for name in ("save1", "save2", "save3"):
            answer, seconds = took[name]
            self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, answer)
            # One wait each. Queued behind the in-process lock they answered
            # at one, two and three waits.
            self.assertLess(seconds, wait * 1.9, took)
        for name in ("refresh", "active"):
            self.assertLess(took[name][1], wait * 0.9, took)

    def test_forget_on_a_machine_that_never_saved_creates_nothing(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, _ = make_runtime(
            state_home=os.path.join(home, "state"), state_dir=Path(home, "state")
        )

        self.assertEqual(annotation_store.FORGET_NOTHING, annotation_store.forget(config))
        self.assertFalse(os.path.lexists(config.state_home))

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_the_lock_file_is_readable_by_its_owner_alone(self) -> None:
        annotation_store.annotate(self.config, self.first, "claude", SID, goal="Seed", now=START)
        mode = stat.S_IMODE(os.stat(annotation_store.lock_path(self.config)).st_mode)
        self.assertEqual(0, mode & 0o077, oct(mode))


class AnUnlockableStoreIsRefusedOrNamedTest(_SharedHomeCase):
    """A lock file this user cannot use refuses; a filesystem that cannot lock says so.

    DRC-4661's rule is that a save is kept or explicitly refused. Proceeding
    without the lock is neither when the file is there and refuses this user,
    so only a filesystem that reports locking unsupported falls back to the
    in-process lock, and names what that costs once.
    """

    def setUp(self) -> None:
        super().setUp()
        annotation_store._UNLOCKABLE_NAMED.clear()
        self.addCleanup(annotation_store._UNLOCKABLE_NAMED.clear)

    def save(self, said: list[str], text: str = "Typed") -> str:
        return annotation_store.annotate(
            self.config,
            self.first,
            "claude",
            SID,
            goal=text,
            now=START,
            diagnostic_sink=said.append,
        )

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "POSIX modes, and root opens anything")
    def test_a_lock_file_this_user_cannot_open_refuses_every_save_from_both_processes(
        self,
    ) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        state_dir = os.path.join(home, "state")
        os.makedirs(state_dir, mode=0o700)
        lock = os.path.join(state_dir, "compass-annotations.json.lock")
        Path(lock).touch()
        os.chmod(lock, 0)
        self.addCleanup(os.chmod, lock, 0o600)
        outcomes, said = _two_processes_save(home, 30)

        self.assertEqual([annotation_store.OUTCOME_UNWRITABLE] * 60, outcomes)
        self.assertFalse(os.path.exists(os.path.join(state_dir, "compass-annotations.json")))
        self.assertIn(lock, said)

    @unittest.skipIf(os.name == "nt", "the CRT reports every LockFile failure as EACCES")
    def test_a_filesystem_that_cannot_lock_saves_under_this_process_lock_and_says_so_once(
        self,
    ) -> None:
        for code in sorted({errno.ENOLCK, errno.EOPNOTSUPP, errno.ENOTSUP}):
            with self.subTest(errno=errno.errorcode[code]):
                self.setUp()
                said: list[str] = []
                refusal = OSError(code, os.strerror(code))
                with mock.patch("fcntl.flock", side_effect=refusal):
                    first = self.save(said, "First")
                    second = self.save(said, "Second")

                self.assertEqual((annotation_store.OUTCOME_STORED,) * 2, (first, second))
                self.assertEqual(
                    [
                        (
                            "Compass: the annotation store "
                            f"{annotation_store.store_path(self.config)} cannot be locked on "
                            "this filesystem; saves from another dashboard sharing this home "
                            "may overwrite each other"
                        )
                    ],
                    said,
                )

    @unittest.skipIf(os.name == "nt", "fcntl")
    def test_a_lock_refused_for_any_other_reason_writes_nothing(self) -> None:
        for code in (errno.EACCES, errno.EPERM, errno.EIO):
            with self.subTest(errno=errno.errorcode[code]):
                self.setUp()
                said: list[str] = []
                refusal = OSError(code, os.strerror(code))
                with mock.patch("fcntl.flock", side_effect=refusal):
                    outcome = self.save(said)

                self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, outcome)
                self.assertFalse(os.path.exists(annotation_store.store_path(self.config)))
                self.assertTrue(said)

    @unittest.skipIf(os.name == "nt", "the holder's lock file cannot be unlinked while held")
    def test_a_lock_file_that_cannot_be_made_writes_nothing_while_another_process_holds_it(
        self,
    ) -> None:
        # The state home vanished or filled between the makedirs and the lock
        # open, while another dashboard held the lock. The write that follows
        # makes its own directory and would succeed with no lock at all, over
        # the holder's store, so the save must not write.
        annotation_store.annotate(self.config, self.first, "claude", SID, goal="Seed", now=START)
        store = Path(annotation_store.store_path(self.config))
        before = store.read_bytes()
        self.hold()
        lock = annotation_store.lock_path(self.config)
        os.unlink(lock)
        real_open = os.open

        def open_(path: Any, *args: Any, **kwargs: Any) -> int:
            if os.fspath(path) == lock:
                raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))
            return real_open(path, *args, **kwargs)

        said: list[str] = []
        with mock.patch("os.open", side_effect=open_):
            outcome = self.save(said, "Typed while the home was gone")

        self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, outcome)
        self.assertEqual(before, store.read_bytes())
        # The words stay in this process, which is what `unwritable` promises.
        entry = annotation_store.find(
            annotation_store.active(self.config, self.first), "claude", SID
        )
        assert entry is not None
        self.assertEqual("Typed while the home was gone", entry["revisions"][-1]["goal"])
        self.assertTrue(any("could not write the annotation store" in line for line in said), said)

    def test_running_out_of_descriptors_is_a_refusal_not_a_home_without_room(self) -> None:
        # No lock file yet, and an open that fails for a reason about this
        # process rather than its directory: the store could still be written,
        # so proceeding would be a save without the lock.
        lock = annotation_store.lock_path(self.config)
        real_open = os.open

        def open_(path: Any, *args: Any, **kwargs: Any) -> int:
            if os.fspath(path) == lock:
                raise OSError(errno.EMFILE, os.strerror(errno.EMFILE))
            return real_open(path, *args, **kwargs)

        said: list[str] = []
        with mock.patch("os.open", side_effect=open_):
            outcome = self.save(said)

        self.assertEqual(annotation_store.OUTCOME_UNWRITABLE, outcome)
        self.assertFalse(os.path.exists(annotation_store.store_path(self.config)))


# Holds the store's lock from a second process until killed. Run on every
# platform the suite runs on, so windows-latest exercises the `msvcrt` branch.
_HOLD_LOCK = textwrap.dedent(
    """
    import os, signal, sys, time
    sys.path.insert(0, sys.argv[1])
    from compass_runtime import io as runtime_io
    with runtime_io.held_file_lock(sys.argv[2], wait=5.0) as held:
        print(held, flush=True)
        if sys.argv[3] == "stop":
            os.kill(os.getpid(), signal.SIGSTOP)
        time.sleep(60)
    """
)

_SAVER = textwrap.dedent(
    """
    import json, os, sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from compass_runtime import annotations as store
    from compass_runtime.config import build_runtime_config
    from compass_runtime.state import build_runtime_state
    home, name, count = sys.argv[2], sys.argv[3], int(sys.argv[4])
    config = build_runtime_config(
        environ={**os.environ, "HOME": home, "COMPASS_HOME": os.path.join(home, "state")},
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=Path(home) / "server.py",
    )
    state = build_runtime_state(config, started=time.time())
    said = []
    Path(home, f"ready-{name}").touch()
    go = os.path.join(home, "go")
    while not os.path.exists(go):
        time.sleep(0.01)
    outcomes = [
        store.annotate(
            config, state, "claude", "shared", goal=f"{name} save {k}", diagnostic_sink=said.append
        )
        for k in range(count)
    ]
    print(json.dumps({"outcomes": outcomes, "said": said}))
    """
)


# `_SAVER` with eight threads per process and `flock` routed to `lockf`, whose
# locks belong to the process: Linux NFS's emulation of `flock`. Each read is
# slowed so a lost update shows rather than hides in a narrow window.
_THREADED_LOCKF_SAVER = textwrap.dedent(
    """
    import fcntl, json, os, sys, threading, time
    from pathlib import Path
    from unittest import mock
    sys.path.insert(0, sys.argv[1])
    from compass_runtime import annotations as store
    from compass_runtime.config import build_runtime_config
    from compass_runtime.state import build_runtime_state
    home, name, count = sys.argv[2], sys.argv[3], int(sys.argv[4])
    config = build_runtime_config(
        environ={**os.environ, "HOME": home, "COMPASS_HOME": os.path.join(home, "state")},
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=Path(home) / "server.py",
    )
    state = build_runtime_state(config, started=time.time())

    def per_process(fd, op):
        if op & fcntl.LOCK_UN:
            return fcntl.lockf(fd, fcntl.LOCK_UN)
        return fcntl.lockf(fd, fcntl.LOCK_EX | (op & fcntl.LOCK_NB))

    real_read = store._read_store

    def slow(c):
        s = real_read(c)
        time.sleep(0.002)
        return s

    mock.patch("fcntl.flock", side_effect=per_process).start()
    mock.patch.object(store, "_read_store", side_effect=slow).start()
    said, outcomes, guard, go = [], [], threading.Lock(), threading.Event()

    def work(i):
        go.wait()
        for k in range(count):
            answer = store.annotate(
                config, state, "claude", "shared", goal=f"{name}{i}-{k}",
                diagnostic_sink=said.append,
            )
            with guard:
                outcomes.append(answer)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    Path(home, f"ready-{name}").touch()
    while not os.path.exists(os.path.join(home, "go")):
        time.sleep(0.005)
    go.set()
    for thread in threads:
        thread.join()
    print(json.dumps({"outcomes": outcomes, "said": said}))
    """
)


class TwoProcessesOnOneHomeTest(unittest.TestCase):
    """Two real dashboards' worth of processes, saving into one home at once."""

    SAVES = 30

    def test_every_save_from_both_processes_takes_its_own_revision_number(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        outcomes, _ = _two_processes_save(home, self.SAVES)

        self.assertEqual([annotation_store.OUTCOME_STORED] * 2 * self.SAVES, outcomes)
        data = json.loads(Path(home, "state", "compass-annotations.json").read_text("utf-8"))
        (entry,) = data["entries"]
        numbers = [revision["n"] for revision in entry["revisions"]]
        # Sixty stored saves are sixty revision numbers: the last is 60 and the
        # kept tail is consecutive. A lost update leaves the last number short.
        self.assertEqual(2 * self.SAVES, numbers[-1])
        self.assertEqual(list(range(numbers[0], numbers[-1] + 1)), numbers)


class ThreadsInOneProcessTest(_SharedHomeCase):
    """Sixteen threads of one dashboard saving into one session at once.

    Each read is slowed so any overlap of two read-check-writes loses a
    revision. Run once under the OS lock and once where the filesystem reports
    it cannot lock, where only this process's own exclusion keeps them apart.
    """

    THREADS = 16
    SAVES = 10

    def run_threads(self) -> list[str]:
        real = annotation_store._read_store

        def slow(config: Any) -> Any:
            store = real(config)
            time.sleep(0.002)
            return store

        outcomes: list[str] = []
        guard = threading.Lock()
        go = threading.Event()

        def work(i: int) -> None:
            go.wait()
            for k in range(self.SAVES):
                answer = annotation_store.annotate(
                    self.config, self.first, "claude", SID, goal=f"{i}-{k}", now=START + k
                )
                with guard:
                    outcomes.append(answer)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(self.THREADS)]
        with (
            mock.patch.object(annotation_store, "_read_store", side_effect=slow),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            for thread in threads:
                thread.start()
            go.set()
            for thread in threads:
                thread.join(60)
        return outcomes

    def assert_every_save_kept(self, outcomes: list[str]) -> None:
        total = self.THREADS * self.SAVES
        self.assertEqual([annotation_store.OUTCOME_STORED] * total, outcomes)
        entry = self.entry()
        numbers = [revision["n"] for revision in entry["revisions"]]
        self.assertEqual(total, numbers[-1])
        self.assertEqual(list(range(numbers[0], numbers[-1] + 1)), numbers)

    def test_every_save_takes_its_own_revision_number(self) -> None:
        self.assert_every_save_kept(self.run_threads())

    @unittest.skipIf(os.name == "nt", "fcntl")
    def test_every_save_takes_its_own_revision_number_where_the_filesystem_cannot_lock(
        self,
    ) -> None:
        annotation_store._UNLOCKABLE_NAMED.clear()
        self.addCleanup(annotation_store._UNLOCKABLE_NAMED.clear)
        refusal = OSError(errno.ENOLCK, os.strerror(errno.ENOLCK))
        with mock.patch("fcntl.flock", side_effect=refusal):
            outcomes = self.run_threads()
        self.assert_every_save_kept(outcomes)


class ARefreshCannotUndoASaveTest(_SharedHomeCase):
    """A collection that read the store before a save must not put its copy over it.

    The a11y lens's Keep over a draft (cccc0013, dddd0013): a collection's
    `refresh` read the file, Keep's adoption committed, and the refresh then
    assigned its older copy, so the press that followed found no entry.
    """

    def save_during_refresh(self) -> str:
        """A save pressed while a refresh sits between its read and its copy; its outcome.

        Over a store holding no entries, because a refresh with no file reads nothing.
        """
        Path(annotation_store.store_path(self.config)).write_text(
            json.dumps({"v": annotation_store.SCHEMA_VERSION, "entries": []}), "utf-8"
        )
        pause = _PauseAfterRead()
        saved: list[str] = []
        refreshing = threading.Thread(
            target=annotation_store.refresh, args=(self.config, self.first)
        )
        saving = threading.Thread(
            target=lambda: saved.append(
                annotation_store.annotate(
                    self.config, self.first, "claude", SID, goal=FIRST, now=FIRST_AT
                )
            )
        )
        pause.thread = refreshing
        with mock.patch.object(annotation_store, "_read_store", pause):
            refreshing.start()
            try:
                self.assertTrue(pause.paused.wait(10), "the refresh never read the store")
                saving.start()
                saving.join(BLOCKED_FOR)
            finally:
                pause.release.set()
                refreshing.join(20)
                saving.join(20)
        self.assertFalse(refreshing.is_alive() or saving.is_alive())
        return saved[0]

    def test_a_refresh_that_read_before_a_save_keeps_the_saved_entry(self) -> None:
        self.assertEqual(annotation_store.OUTCOME_STORED, self.save_during_refresh())
        entry = annotation_store.find(
            annotation_store.active(self.config, self.first), "claude", SID
        )
        self.assertIsNotNone(entry, "the refresh put its older copy over the save")

    def test_a_save_during_a_refresh_leaves_the_store_notice_true_to_the_file(self) -> None:
        # The board said the store was unreadable, and the file has since been
        # repaired: the next refresh reads it whole while a save lands.
        store = Path(annotation_store.store_path(self.config))
        store.write_text("not a store", "utf-8")
        annotation_store.refresh(self.config, self.first)
        self.assertEqual(
            annotation_store.STORE_UNREADABLE, annotation_store.store_notice(self.first)
        )

        # `save_during_refresh` repairs the file before the refresh reads it.
        self.assertEqual(annotation_store.OUTCOME_STORED, self.save_during_refresh())

        self.assertTrue(self.first.annotations_trusted, "the notice stayed up over a whole file")
        self.assertEqual("", annotation_store.store_notice(self.first))


# A collection's refresh in a second process, holding its read handle on the
# store open for `HOLD` seconds. While held it keeps a marker beside the store,
# which the saving process reads as Windows does an open handle: `os.replace`
# onto the store is refused. The marker goes just before the handle closes, so
# it marks the window the handle is open and nothing after it.
_REFRESH_HOLDING_READ = textwrap.dedent(
    """
    import builtins, os, sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    from compass_runtime import annotations as store
    from compass_runtime.config import build_runtime_config
    from compass_runtime.state import build_runtime_state
    home, hold = sys.argv[2], float(sys.argv[3])
    config = build_runtime_config(
        environ={**os.environ, "HOME": home, "COMPASS_HOME": os.path.join(home, "state")},
        platform_name=sys.platform,
        os_name=os.name,
        launcher_path=Path(home) / "server.py",
    )
    state = build_runtime_state(config, started=time.time())
    marker = store.store_path(config) + ".reading"

    class Held:
        def __init__(self, handle):
            self.handle = handle
        def __enter__(self):
            Path(marker).touch()
            print("reading", flush=True)
            time.sleep(hold)
            return self.handle
        def __exit__(self, *exc):
            os.unlink(marker)
            self.handle.close()

    def held_open(path, *args, **kwargs):
        handle = builtins.open(path, *args, **kwargs)
        return Held(handle) if os.fspath(path) == store.store_path(config) else handle

    store.open = held_open
    entries = store.refresh(config, state)
    print("read", len(entries), flush=True)
    """
)


class ARefreshNeverFailsAnotherDashboardsSaveTest(unittest.TestCase):
    """A collection in one dashboard reading while another dashboard saves.

    Windows refuses `os.replace` onto a file another handle has open, and the
    replace retries for about a third of a second. A refresh that read outside
    the store's lock held its handle across the other dashboard's whole write,
    so a read slower than the retries failed that save. CI has no Windows, so
    the refusal is modelled: the saving process's `os.replace` is refused for
    as long as the refreshing process holds its real read handle.
    """

    HOLD = 1.5

    @unittest.skipIf(os.name == "nt", "models Windows' refusal on POSIX")
    def test_a_save_made_while_another_process_reads_the_store_is_stored(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        config, state = make_runtime(
            state_home=os.path.join(home, "state"), state_dir=Path(home, "state")
        )
        seeded = annotation_store.annotate(config, state, "claude", SID, goal="Seed", now=START)
        self.assertEqual(annotation_store.OUTCOME_STORED, seeded)
        target = annotation_store.store_path(config)
        marker = f"{target}.reading"
        real_replace = os.replace

        def windows_replace(src: Any, dst: Any) -> None:
            if os.fspath(dst) == target and os.path.exists(marker):
                raise PermissionError(errno.EACCES, "held open by another process", target)
            real_replace(src, dst)

        env = {k: v for k, v in os.environ.items() if not k.startswith("COMPASS_")}
        reader = subprocess.Popen(
            [sys.executable, "-c", _REFRESH_HOLDING_READ, str(SKILL_DIR), home, str(self.HOLD)],
            stdout=subprocess.PIPE,
            env=env,
        )
        self.addCleanup(_kill, reader)
        assert reader.stdout is not None
        self.assertEqual(b"reading", reader.stdout.readline().rstrip())
        said: list[str] = []
        with mock.patch("os.replace", side_effect=windows_replace):
            outcome = annotation_store.annotate(
                config,
                state,
                "claude",
                SID,
                goal="Saved while the other dashboard read",
                now=START + 1,
                diagnostic_sink=said.append,
            )
        out, _ = reader.communicate(timeout=30)

        self.assertEqual(annotation_store.OUTCOME_STORED, outcome, said)
        self.assertEqual(0, reader.returncode)
        self.assertEqual(b"read 1", out.strip())
        entry = annotation_store.find(annotation_store._read(config), "claude", SID)
        assert entry is not None
        self.assertEqual("Saved while the other dashboard read", entry["revisions"][-1]["goal"])


class AWriterInsideAWriterTest(_SharedHomeCase):
    """A writer called while this thread already writes the store fails at once."""

    def test_a_nested_writer_raises_rather_than_waiting_out_its_own_lock(self) -> None:
        began = time.monotonic()
        with (
            annotation_store._locked_store(self.config, None, lambda _line: None) as store,
            self.assertRaisesRegex(RuntimeError, "already writing"),
        ):
            self.assertIsNotNone(store)
            annotation_store.annotate(self.config, self.first, "claude", SID, goal="Nested")
        # Far inside the ten-second store wait the nested writer would otherwise sit through.
        self.assertLess(time.monotonic() - began, 5.0)
        # The outer write released everything on the way out.
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.annotate(self.config, self.first, "claude", SID, goal="After"),
        )


class PerProcessLocksTest(unittest.TestCase):
    """Two processes of eight threads each, where the OS lock belongs to the process.

    Linux NFS clients emulate `flock` with whole-file POSIX locks, which a
    process owns: a second thread's open "gets" a lock its sibling holds, and
    either thread's close releases it for the other process. Modelled here by
    routing `flock` to `lockf`. One OS-lock user per process is what keeps
    every stored save; without it this lost 6 to 23 of 160 per run.
    """

    @unittest.skipIf(os.name == "nt", "fcntl")
    def test_every_stored_save_is_kept_when_the_lock_is_per_process(self) -> None:
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        outcomes, _ = _two_processes_save(home, 10, script=_THREADED_LOCKF_SAVER)

        self.assertEqual([annotation_store.OUTCOME_STORED] * 160, outcomes)
        data = json.loads(Path(home, "state", "compass-annotations.json").read_text("utf-8"))
        (entry,) = data["entries"]
        numbers = [revision["n"] for revision in entry["revisions"]]
        self.assertEqual(160, numbers[-1])
        self.assertEqual(list(range(numbers[0], numbers[-1] + 1)), numbers)


def _two_processes_save(home: str, saves: int, script: str = "") -> tuple[list[str], str]:
    """Two real processes, each making `saves` goal saves into `home` at once.

    Each touches a ready file once imported, and neither starts until both
    have, so a slow start cannot run one's saves before the other begins.
    Returns every outcome and everything either process said.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("COMPASS_")}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script or _SAVER, str(SKILL_DIR), home, name, str(saves)],
            stdout=subprocess.PIPE,
            env=env,
        )
        for name in ("one", "two")
    ]
    try:
        deadline = time.monotonic() + 60
        while not all(Path(home, f"ready-{name}").exists() for name in ("one", "two")):
            if time.monotonic() > deadline or any(p.poll() is not None for p in procs):
                msg = "a saver never became ready"
                raise AssertionError(msg)
            time.sleep(0.01)
        Path(home, "go").touch()
        outcomes: list[str] = []
        said: list[str] = []
        for proc in procs:
            out, _ = proc.communicate(timeout=120)
            if proc.returncode != 0:
                msg = f"a saver exited {proc.returncode}"
                raise AssertionError(msg)
            report = json.loads(out)
            outcomes.extend(report["outcomes"])
            said.extend(report["said"])
    finally:
        for proc in procs:
            _kill(proc)
    return outcomes, "\n".join(said)


def _assessment() -> Any:
    return {
        "revision_read": 1,
        "stamp": "read at 10:00",
        "cutoff": "Read 1 of the 1 entry after your words",
        "scope": runtime_reading.SCOPE_FINAL,
        "scope_text": runtime_reading.SCOPE_TEXT[runtime_reading.SCOPE_FINAL],
        "ended_at_read": 99.0,
        "criteria": {
            "goal": {
                "result": runtime_reading.RESULT_DEPARTURE,
                "cites": ("f1",),
                "detail": "it renamed a different flag",
                "clause": "Seed",
            },
        },
    }


def _kill(proc: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired, OSError):
        proc.wait(5)
    if proc.stdout is not None:
        proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
