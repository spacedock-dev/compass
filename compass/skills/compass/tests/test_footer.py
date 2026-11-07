"""`--footer`: the status line segment the terminal client prints without reaching the dashboard."""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, TextIO
from unittest import mock

from compass_runtime import (
    cli,
    entry,
    footer_lines,
    levels,
    lifecycle,
    live_lease,
    terminal_client,
    terminal_drift,
)

from .support import SERVER_PATH

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW = 1_800_000_000.0
# The outer guard only separates "the reader is hung" from "the reader is slow". It is not a
# deadline check: whether the reader gives up at its own deadline is decided on a controlled
# clock (`LogicalDeadline`), because a wall-clock upper bound over the deadline measures the
# scheduler as much as the reader (0.352 s observed against 0.2 s + 0.15 s on a loaded macOS lane).
HANG_GUARD_SEC = 5.0
# The hang guard and the footer subprocess's exit are waited for on the wall clock.
REAL_TIME_TESTS = True

# `LogicalDeadline` replaces the clock and the `select` of `_read_pipe`, which Windows never runs
# (its reader is a thread), so the tests that observe the logical budget are POSIX tests.
POSIX_ONLY = unittest.skipIf(os.name == "nt", "the Windows reader is a thread, not a select loop")


def pro_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "session_id": "sess-1",
        "rate_limits": {
            "five_hour": {"used_percentage": 82.4, "resets_at": NOW + 2 * 3600 + 10 * 60 + 5},
            "seven_day": {"used_percentage": 30, "resets_at": NOW + 4 * 86400},
        },
    }
    payload.update(overrides)
    return payload


@contextlib.contextmanager
def held_open_pipe() -> Iterator[tuple[TextIO, int]]:
    """A text stream on a pipe whose write end stays open, as a status line that has not closed."""
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "r", encoding="utf-8")
    try:
        yield stream, write_fd
    finally:
        # The write end goes first. A reader still blocked in `stream.read()` holds the buffered
        # stream's lock, so `stream.close()` would wait behind it for as long as the writer stays
        # open; end of input lets that read return and release the lock.
        with contextlib.suppress(OSError):
            os.close(write_fd)
        stream.close()


class LogicalDeadline:
    """A controlled clock under the reader's real pipe, so the deadline is observed and not timed.

    The reader still `select`s and `os.read`s a real `os.pipe`. Only its clock and the length of an
    idle wait are replaced: an idle `select` reports the timeout the reader asked for, advances the
    clock by exactly that much and answers "nothing ready" without sleeping, so the reader sees the
    deadline arrive and a slow host cannot make it arrive late. Data is never faked: `feed` writes
    its fragments into the real pipe, one per wait, and each one moves the clock on by `gap`.
    """

    MAX_WAITS = 100  # a reader that never reaches its deadline fails here instead of looping

    def __init__(self, write_fd: int, *, feed: tuple[bytes, ...] = (), gap: float = 0.0) -> None:
        self.write_fd = write_fd
        self.feed = list(feed)
        self.gap = gap
        self.now = 1_000.0
        self.started = self.now
        self.idle_waits: list[float] = []  # each timeout the reader asked an empty pipe to cover
        self.overdrawn: list[tuple[float, float]] = []  # (asked, still left) when asked > left
        self._deadline = 0.0
        self._real_select = select.select

    def monotonic(self) -> float:
        return self.now

    def __getattr__(self, name: str) -> object:
        return getattr(time, name)  # `terminal_client.time.time` and the rest stay real

    def select(
        self, rlist: list[int], wlist: list[int], xlist: list[int], timeout: float | None = None
    ) -> tuple[list[int], list[int], list[int]]:
        if len(rlist) != 1 or wlist or xlist:
            return self._real_select(rlist, wlist, xlist, timeout)
        if timeout is None:
            raise AssertionError("the reader waited on the pipe with no bound")
        left = self._deadline - (self.now - self.started)
        if timeout > left + 1e-9:
            self.overdrawn.append((timeout, left))
        if self.feed:
            os.write(self.write_fd, self.feed.pop(0))
            self.now += self.gap
        ready = self._real_select(rlist, wlist, xlist, 0)
        if not ready[0]:
            self.idle_waits.append(timeout)
            self.now += timeout
            if len(self.idle_waits) > self.MAX_WAITS:
                raise AssertionError("the reader kept waiting past its deadline")
        return ready

    @property
    def elapsed(self) -> float:
        return self.now - self.started

    def read(self, stream: TextIO, deadline: float | None) -> dict[str, object] | None:
        """Read under this clock; `None` reads with the caller's default deadline."""
        self._deadline = terminal_client.STDIN_DEADLINE_SEC if deadline is None else deadline
        with (
            mock.patch.object(terminal_client, "time", self),
            mock.patch.object(select, "select", self.select),
        ):
            return read_guarded(stream, deadline)


def read_guarded(stream: TextIO, deadline: float | None) -> dict[str, object] | None:
    """`read_status_line` under an outer wall-clock guard that only tells hung from slow."""
    box: list[dict[str, object] | None] = []
    failed: list[BaseException] = []

    def run() -> None:
        try:
            if deadline is None:
                box.append(terminal_client.read_status_line(stream))
            else:
                box.append(terminal_client.read_status_line(stream, deadline=deadline))
        except BaseException as error:  # noqa: BLE001 — re-raised on the test's own thread
            failed.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(HANG_GUARD_SEC)
    if worker.is_alive():
        raise AssertionError(f"read_status_line was still running after {HANG_GUARD_SEC}s")
    if failed:
        raise failed[0]
    return box[0]


class HangGuardTest(unittest.TestCase):
    """The outer guard itself, in a child process, because a regression in it is a hung test run.

    A reader blocked in `stream.read()` holds the buffered stream's lock, so closing the stream
    before the write end blocks behind it for as long as the writer stays open. The guard must
    fail the test and the cleanup must return. The child runs with a short guard, and this test
    kills it at a fixed limit, so a regression here is a failure and never a hang.
    """

    CHILD_LIMIT_SEC = 20.0  # kill limit for the child; the child itself needs about a second

    SCRIPT = """
import sys
import time

from tests import test_footer as t
from compass_runtime import terminal_client

t.HANG_GUARD_SEC = 0.3
mutant = sys.argv[1]
if mutant == "blocked-in-stream-read":
    terminal_client.read_status_line = lambda stream, deadline: stream.read()
else:
    def spin(stream, deadline):
        while True:
            time.sleep(0.01)
    terminal_client.read_status_line = spin
try:
    with t.held_open_pipe() as (stream, write_fd):
        t.read_guarded(stream, 0.2)
except AssertionError as error:
    print("guard fired:", error)
else:
    print("guard did not fire")
"""

    def run_child(self, mutant: str) -> subprocess.CompletedProcess[str]:
        package_root = Path(__file__).resolve().parents[1]
        return subprocess.run(
            [sys.executable, "-c", self.SCRIPT, mutant],
            cwd=package_root,
            capture_output=True,
            text=True,
            timeout=self.CHILD_LIMIT_SEC,
            check=False,
        )

    def test_a_reader_blocked_in_the_stream_is_failed_by_the_guard_and_cleaned_up(self) -> None:
        try:
            done = self.run_child("blocked-in-stream-read")
        except subprocess.TimeoutExpired:
            self.fail("cleanup after the guard hung while the reader held the stream lock")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("guard fired", done.stdout)

    def test_a_reader_that_never_returns_is_failed_by_the_guard_and_cleaned_up(self) -> None:
        try:
            done = self.run_child("spins-forever")
        except subprocess.TimeoutExpired:
            self.fail("cleanup after the guard hung while the reader kept running")

        self.assertEqual(0, done.returncode, done.stderr)
        self.assertIn("guard fired", done.stdout)


class ReadStatusLineTest(unittest.TestCase):
    @POSIX_ONLY
    def test_a_pipe_held_open_with_nothing_written_answers_none_at_the_deadline(self) -> None:
        with held_open_pipe() as (stream, write_fd):
            clock = LogicalDeadline(write_fd)

            got = clock.read(stream, 0.2)

        self.assertIsNone(got)
        self.assertEqual([], clock.overdrawn)
        self.assertAlmostEqual(0.2, sum(clock.idle_waits))
        self.assertAlmostEqual(0.2, clock.elapsed)

    def test_a_pipe_held_open_with_nothing_written_is_given_up_on_in_real_time(self) -> None:
        with held_open_pipe() as (stream, _write_fd):
            started = time.monotonic()
            got = read_guarded(stream, 0.2)
            elapsed = time.monotonic() - started

        self.assertIsNone(got)
        self.assertGreaterEqual(
            elapsed, 0.1
        )  # a late wake-up is the scheduler's, an early one is not

    def test_json_with_no_newline_and_no_eof_is_answered_without_waiting_for_the_deadline(
        self,
    ) -> None:
        # A deadline far past the hang guard: a reader that waited for it fails the guard instead
        # of an elapsed bound that a busy runner can also cross.
        with held_open_pipe() as (stream, write_fd):
            os.write(write_fd, b'{"session_id": "abc", "n": 1}')
            got = read_guarded(stream, 60.0)

        self.assertEqual({"session_id": "abc", "n": 1}, got)

    @POSIX_ONLY
    def test_json_with_no_newline_and_no_eof_spends_none_of_the_deadline(self) -> None:
        with held_open_pipe() as (stream, write_fd):
            os.write(write_fd, b'{"session_id": "abc", "n": 1}')
            clock = LogicalDeadline(write_fd)

            got = clock.read(stream, 5.0)

        self.assertEqual({"session_id": "abc", "n": 1}, got)
        self.assertEqual([], clock.idle_waits)
        self.assertEqual(0.0, clock.elapsed)

    @POSIX_ONLY
    def test_a_silent_producer_costs_the_footer_its_quarter_second_default(self) -> None:
        # The default the footer command reads its stdin with, which the subprocess test below
        # can only bound loosely.
        with held_open_pipe() as (stream, write_fd):
            clock = LogicalDeadline(write_fd)

            got = clock.read(stream, None)

        self.assertIsNone(got)
        self.assertEqual([], clock.overdrawn)
        self.assertAlmostEqual(0.25, clock.elapsed)

    def test_json_that_arrives_in_two_writes_is_joined(self) -> None:
        with held_open_pipe() as (stream, write_fd):
            os.write(write_fd, b'{"session_id": ')
            timer = threading.Timer(0.05, os.write, (write_fd, b'"abc"}'))
            timer.start()
            got = terminal_client.read_status_line(stream, deadline=2.0)
            timer.join()

        self.assertEqual({"session_id": "abc"}, got)

    @POSIX_ONLY
    def test_a_partial_object_that_stalls_answers_none_at_the_deadline(self) -> None:
        with held_open_pipe() as (stream, write_fd):
            os.write(write_fd, b'{"session_id": "ab')
            clock = LogicalDeadline(write_fd)

            got = clock.read(stream, 0.2)

        self.assertIsNone(got)
        self.assertEqual([], clock.overdrawn)
        self.assertAlmostEqual(0.2, sum(clock.idle_waits))
        self.assertAlmostEqual(0.2, clock.elapsed)

    def test_a_partial_object_that_stalls_is_given_up_on_in_real_time(self) -> None:
        with held_open_pipe() as (stream, write_fd):
            os.write(write_fd, b'{"session_id": "ab')
            started = time.monotonic()
            got = read_guarded(stream, 0.2)
            elapsed = time.monotonic() - started

        self.assertIsNone(got)
        self.assertGreaterEqual(elapsed, 0.1)

    @POSIX_ONLY
    def test_a_producer_that_keeps_writing_without_finishing_is_cut_off_at_one_deadline(
        self,
    ) -> None:
        fragments = (b'{"session_id": "', *(b"ab",) * 9)
        with held_open_pipe() as (stream, write_fd):
            clock = LogicalDeadline(write_fd, feed=fragments, gap=0.1)

            got = clock.read(stream, 0.25)

        self.assertIsNone(got)
        self.assertEqual([], clock.overdrawn)
        self.assertEqual(
            [], clock.idle_waits
        )  # every wait was answered; the budget, not a stall, ended it
        self.assertEqual(
            len(fragments) - 3, len(clock.feed)
        )  # 0.1 + 0.1 + 0.1 covers the 0.25 budget
        self.assertAlmostEqual(0.3, clock.elapsed)

    @POSIX_ONLY
    def test_the_wait_after_the_last_data_is_only_what_the_budget_has_left(self) -> None:
        with held_open_pipe() as (stream, write_fd):
            os.write(write_fd, b'{"a": ')
            clock = LogicalDeadline(write_fd, feed=(b'"b', b"c"), gap=0.05)

            got = clock.read(stream, 0.2)

        self.assertIsNone(got)
        self.assertEqual([], clock.overdrawn)
        self.assertAlmostEqual(0.1, sum(clock.idle_waits))  # 0.2 less the 0.1 the fragments took
        self.assertAlmostEqual(0.2, clock.elapsed)

    def test_a_stream_without_a_file_descriptor_is_read_the_same_way(self) -> None:
        got = terminal_client.read_status_line(io.StringIO('{"a": 1}'))

        self.assertEqual({"a": 1}, got)

    def test_what_is_not_one_object_is_none(self) -> None:
        for text in ("", "not json", "[1]", "5", '"x"', "null"):
            with self.subTest(text=text):
                self.assertIsNone(terminal_client.read_status_line(io.StringIO(text)))

    def test_more_than_the_cap_is_none_and_is_not_read_past_it(self) -> None:
        stream = io.StringIO('{"pad": "' + "x" * 200_000 + '"}')

        got = terminal_client.read_status_line(stream)

        self.assertIsNone(got)
        self.assertLessEqual(stream.tell(), terminal_client.STDIN_CAP_CHARS + 1)

    def test_a_terminal_is_never_read(self) -> None:
        class Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

            def read(self, *_a: object) -> str:
                raise AssertionError("read a terminal")

        self.assertIsNone(terminal_client.read_status_line(Tty('{"a": 1}')))

    def test_no_stream_is_none(self) -> None:
        self.assertIsNone(terminal_client.read_status_line(None))


class ResolveSessionFromPayloadTest(unittest.TestCase):
    def test_a_payload_already_read_names_the_session_without_reading_stdin_again(self) -> None:
        class Spent(io.StringIO):
            def read(self, *_a: object) -> str:
                raise AssertionError("read stdin twice")

        got = terminal_client.resolve_session(
            None, {}, Spent(), payload={"session_id": "from-payload"}
        )

        self.assertEqual(terminal_client.Session("claude", "from-payload", "status line"), got)


class TightestWindowTest(unittest.TestCase):
    def test_the_window_with_the_higher_percent_used_wins(self) -> None:
        got = terminal_client.tightest_window(pro_payload(), NOW)

        assert got is not None
        self.assertEqual(("5h", 82.4), (got.label, got.used))

    def test_the_seven_day_window_wins_when_it_is_the_tighter(self) -> None:
        payload = pro_payload(
            rate_limits={
                "five_hour": {"used_percentage": 10, "resets_at": NOW + 600},
                "seven_day": {"used_percentage": 91, "resets_at": NOW + 2 * 86400 + 4 * 3600},
            }
        )

        got = terminal_client.tightest_window(payload, NOW)

        assert got is not None
        self.assertEqual("7d", got.label)

    def test_a_tie_goes_to_the_window_that_resets_sooner(self) -> None:
        payload = pro_payload(
            rate_limits={
                "five_hour": {"used_percentage": 50, "resets_at": NOW + 3600},
                "seven_day": {"used_percentage": 50, "resets_at": NOW + 60},
            }
        )

        got = terminal_client.tightest_window(payload, NOW)

        assert got is not None
        self.assertEqual("7d", got.label)

    def test_no_rate_limits_is_no_window(self) -> None:
        cases: tuple[dict[str, object], ...] = (
            {},
            {"rate_limits": None},
            {"rate_limits": []},
            {"rate_limits": {}},
        )
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertIsNone(terminal_client.tightest_window(payload, NOW))

    def test_a_window_that_has_already_reset_is_dropped_and_the_other_is_used(self) -> None:
        payload = pro_payload(
            rate_limits={
                "five_hour": {"used_percentage": 99, "resets_at": NOW - 1},
                "seven_day": {"used_percentage": 12, "resets_at": NOW + 3600},
            }
        )

        got = terminal_client.tightest_window(payload, NOW)

        assert got is not None
        self.assertEqual("7d", got.label)

    def test_a_bad_percent_is_withheld_and_never_read_as_zero(self) -> None:
        bad = ("50", True, None, float("nan"), float("inf"), -1, 101, [1], {"a": 1})
        for value in bad:
            with self.subTest(value=value):
                payload = {
                    "rate_limits": {"five_hour": {"used_percentage": value, "resets_at": NOW + 60}}
                }
                self.assertIsNone(terminal_client.tightest_window(payload, NOW))

    def test_a_bad_window_does_not_hide_the_good_one(self) -> None:
        payload = {
            "rate_limits": {
                "five_hour": {"used_percentage": "lots", "resets_at": NOW + 60},
                "seven_day": {"used_percentage": 20, "resets_at": NOW + 600},
            }
        }

        got = terminal_client.tightest_window(payload, NOW)

        assert got is not None
        self.assertEqual("7d", got.label)

    def test_an_iso_reset_is_read_as_well_as_epoch_seconds(self) -> None:
        payload = {
            "rate_limits": {
                "five_hour": {"used_percentage": 40, "resets_at": "2027-01-12T08:20:00Z"}
            }
        }
        base = 1_799_740_800.0  # 2027-01-12T08:00:00Z, so the reset is 20 minutes later
        got = terminal_client.tightest_window(payload, base)

        assert got is not None
        self.assertEqual(base + 20 * 60, got.resets_at)

    def test_a_valid_percent_with_no_usable_reset_is_kept_without_a_reset(self) -> None:
        for reset in (None, "tomorrow", True, float("nan"), "", [5]):
            with self.subTest(reset=reset):
                payload = {
                    "rate_limits": {"five_hour": {"used_percentage": 40, "resets_at": reset}}
                }

                got = terminal_client.tightest_window(payload, NOW)

                assert got is not None
                self.assertIsNone(got.resets_at)

    def test_a_millisecond_epoch_is_not_mistaken_for_seconds(self) -> None:
        payload = {
            "rate_limits": {"five_hour": {"used_percentage": 40, "resets_at": (NOW + 600) * 1000}}
        }

        got = terminal_client.tightest_window(payload, NOW)

        assert got is not None
        self.assertIsNone(got.resets_at)


class FormatWindowTest(unittest.TestCase):
    def fmt(self, label: str, used: float, ahead: float | None) -> str:
        window = terminal_client.Window(label, used, None if ahead is None else NOW + ahead)
        return terminal_client.format_window(window, NOW)

    def test_a_reset_is_said_relative_to_now(self) -> None:
        self.assertEqual("5h 82% resets in 2h 10m", self.fmt("5h", 82.4, 2 * 3600 + 10 * 60 + 5))
        self.assertEqual("7d 91% resets in 2d 4h", self.fmt("7d", 91, 2 * 86400 + 4 * 3600 + 30))

    def test_the_unit_steps_at_the_boundaries(self) -> None:
        self.assertEqual("resets in 59m", self.fmt("5h", 1, 59 * 60 + 30).split("% ")[1])
        self.assertEqual("resets in 1h 0m", self.fmt("5h", 1, 3600).split("% ")[1])
        self.assertEqual("resets in 23h 59m", self.fmt("5h", 1, 86400 - 60).split("% ")[1])
        self.assertEqual("resets in 1d 0h", self.fmt("7d", 1, 86400).split("% ")[1])

    def test_a_reset_under_a_minute_reads_one_minute(self) -> None:
        self.assertEqual("5h 5% resets in 1m", self.fmt("5h", 5, 5))

    def test_the_percent_rounds_half_up(self) -> None:
        self.assertEqual("5h 3% resets in 1m", self.fmt("5h", 2.5, 5))
        self.assertEqual("5h 2% resets in 1m", self.fmt("5h", 2.49, 5))

    def test_a_window_with_no_reset_prints_the_percent_alone(self) -> None:
        self.assertEqual("5h 40%", self.fmt("5h", 40, None))


def line_file(home: str, harness: str, sid: str, body: object, *, mode: int = 0o600) -> str:
    path = os.path.join(home, "footer", terminal_client.line_name(harness, sid))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body if isinstance(body, str) else json.dumps(body))
    os.chmod(path, mode)
    return path


def good_line(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "v": 1,
        "at": NOW - 5,
        "pid": 4242,
        "waiting": 2,
        "blind": [],
        "monitor": None,
        "level": None,
    }
    body.update(overrides)
    return body


class LineNameTest(unittest.TestCase):
    def test_the_client_and_the_writer_name_a_session_file_the_same_way(self) -> None:
        for harness, sid in (("claude", "abc"), ("codex", "a/b/../c"), ("claude", "x" * 200)):
            with self.subTest(sid=sid):
                self.assertEqual(
                    footer_lines.line_name(harness, sid), terminal_client.line_name(harness, sid)
                )

    def test_an_outside_id_never_reaches_a_path(self) -> None:
        for sid in ("../../etc/passwd", "a/b", "a\\b", "a?b#c%d", "x" * 200, "ünï"):
            with self.subTest(sid=sid):
                name = terminal_client.line_name("claude", sid)

                self.assertRegex(name, r"\Aclaude-[0-9a-f]{32}\.json\Z")


class ReadLineTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.session = terminal_client.Session("claude", "sess-1", "status line")

    def read(self) -> terminal_client.Line | None:
        return terminal_client.read_line(self.home, self.session, NOW)

    def test_a_person_sees_pause_without_a_monitor_and_keeps_waiting_and_quota(self) -> None:
        payload = {"rate_limits": {"five_hour": {"used_percentage": 60}}}
        for value, expected in (
            (True, True),
            (False, False),
            (None, False),
            (1, False),
            ("true", False),
        ):
            with self.subTest(value=value):
                line_file(self.home, "claude", "sess-1", good_line(model_calls_paused=value))
                text = terminal_client.compose_footer(payload, self.read(), NOW)
                self.assertEqual(expected, "model calls paused" in text)
                self.assertIn("2 waiting", text)
                self.assertIn("5h 60%", text)
        line_file(self.home, "claude", "sess-1", good_line(model_calls_paused=True, at=NOW - 10000))
        self.assertNotIn(
            "model calls paused", terminal_client.compose_footer(payload, self.read(), NOW)
        )

    def test_a_person_sees_model_calls_paused_once_when_their_monitor_ended_for_it(self) -> None:
        line_file(
            self.home,
            "claude",
            "sess-1",
            good_line(
                model_calls_paused=True, monitor=False, last_end={"reason": "paused", "at": NOW}
            ),
        )
        text = terminal_client.compose_footer(None, self.read(), NOW)
        self.assertEqual("model calls paused · monitor off · 2 waiting", text)
        self.assertEqual(1, text.count("model calls paused"))
        self.assertNotIn("monitor off:", text)

    def test_a_person_who_resumes_loses_pause_text_even_after_a_monitor_ended_paused(self) -> None:
        line_file(
            self.home,
            "claude",
            "sess-1",
            good_line(
                model_calls_paused=False, monitor=False, last_end={"reason": "paused", "at": NOW}
            ),
        )
        text = terminal_client.compose_footer(None, self.read(), NOW)
        self.assertNotIn("model calls paused", text)
        self.assertIn("2 waiting", text)

    def test_a_fresh_line_is_read(self) -> None:
        line_file(self.home, "claude", "sess-1", good_line(blind=["Cursor"]))

        got = self.read()

        assert got is not None
        self.assertEqual((2, ("Cursor",)), (got.waiting, got.blind))

    def test_every_way_a_file_can_be_unusable_leaves_it_out(self) -> None:
        cases: dict[str, object] = {
            "corrupt": "{not json",
            "array": "[1]",
            "wrong version": good_line(v=2),
            "no version": {k: v for k, v in good_line().items() if k != "v"},
            "stale": good_line(at=NOW - terminal_client.LINE_STALE_SEC - 1),
            "future": good_line(at=NOW + 60),
            "no time": good_line(at="now"),
            "boolean time": good_line(at=True),
            "huge": "{" + " " * 70_000 + "}",
        }
        for label, body in cases.items():
            with self.subTest(case=label):
                line_file(self.home, "claude", "sess-1", body)

                self.assertIsNone(self.read())

    def test_a_missing_file_a_directory_and_a_symlink_leave_it_out(self) -> None:
        self.assertIsNone(self.read())
        path = os.path.join(self.home, "footer", terminal_client.line_name("claude", "sess-1"))
        os.makedirs(path)
        self.assertIsNone(self.read())
        os.rmdir(path)
        target = line_file(self.home, "claude", "other", good_line())
        os.symlink(target, path)
        self.assertIsNone(self.read())

    @unittest.skipIf(os.name == "nt" or os.geteuid() == 0, "mode bits do not bind here")
    def test_an_unreadable_file_leaves_it_out(self) -> None:
        line_file(self.home, "claude", "sess-1", good_line(), mode=0)

        self.assertIsNone(self.read())

    def test_an_unmeasured_wait_stays_unmeasured_and_is_never_zero(self) -> None:
        for waiting in (None, "2", True, -1, 1.5, [1]):
            with self.subTest(waiting=waiting):
                line_file(self.home, "claude", "sess-1", good_line(waiting=waiting))

                got = self.read()

                assert got is not None
                self.assertIsNone(got.waiting)

    def test_labels_are_kept_only_when_they_are_short_plain_text(self) -> None:
        line_file(
            self.home,
            "claude",
            "sess-1",
            good_line(blind=["Cursor", "bad\x1b[31mred", 5, "", "x" * 100, "Droid\n"]),
        )

        got = self.read()

        assert got is not None
        self.assertEqual(("Cursor",), got.blind)


class MonitorFooterTest(ReadLineTest):
    def footer(self, *, now: float = NOW, **fields: object) -> str:
        line_file(self.home, "claude", "sess-1", good_line(waiting=0, **fields))
        line = terminal_client.read_line(self.home, self.session, now)
        return terminal_client.compose_footer(None, line, now)

    def test_a_person_with_the_monitor_off_sees_only_the_existing_blind_segment(self) -> None:
        self.assertEqual(
            "waits not reported for Antigravity",
            self.footer(monitor=False, level="high", blind=["Antigravity"]),
        )

    def test_a_person_sees_the_pages_level_first_or_a_stated_absence(self) -> None:
        for token, label in terminal_drift.LEVEL_NAMES.items():
            with self.subTest(token=token):
                self.assertEqual(
                    f"drift {label} · waits not reported for Antigravity",
                    self.footer(monitor=True, level=token, blind=["Antigravity"]),
                )
        self.assertEqual("drift: no level yet", self.footer(monitor=True, level=None))

    def test_a_person_never_sees_an_unknown_level_or_a_truthy_monitor(self) -> None:
        for monitor, level in (
            (True, "bogus"),
            (True, "no_live_level"),
            (True, []),
            (1, "high"),
            ("true", "high"),
            (None, "high"),
        ):
            with self.subTest(monitor=monitor, level=level):
                self.assertEqual(
                    "waits not reported for Antigravity",
                    self.footer(monitor=monitor, level=level, blind=["Antigravity"]),
                )

    def test_a_persons_unknown_live_level_never_revives_an_old_end_note(self) -> None:
        self.assertEqual(
            "waits not reported for Antigravity",
            self.footer(
                monitor=True,
                level="bogus",
                last_end={"reason": "paused", "at": NOW},
                blind=["Antigravity"],
            ),
        )

    def test_a_person_sees_why_the_monitor_ended_for_five_minutes_only(self) -> None:
        notes = {
            "ended": "monitor off: session ended",
            "left": "monitor off: check-in expired",
            "paused": "monitor off",
            "unanswered": "monitor off: no answer",
            "declined": "monitor off: as you asked",
            "cap": "monitor off: check limit reached",
            "stopped": "",
        }
        for reason, note in notes.items():
            with self.subTest(reason=reason):
                self.assertEqual(
                    note,
                    self.footer(
                        monitor=False, level="high", last_end={"reason": reason, "at": NOW - 299}
                    ),
                )
                self.assertEqual(
                    "",
                    self.footer(
                        monitor=False, level="high", last_end={"reason": reason, "at": NOW - 300}
                    ),
                )
        self.assertEqual(
            "drift High",
            self.footer(monitor=True, level="high", last_end={"reason": "paused", "at": NOW}),
        )

    def test_a_person_keeps_other_segments_when_an_end_is_malformed(self) -> None:
        ends: tuple[object, ...] = (
            {"reason": "bogus", "at": NOW},
            {"reason": [], "at": NOW},
            {"reason": "ended", "at": True},
            {"reason": "ended", "at": float("nan")},
            {"reason": "ended", "at": NOW + 6},
            [],
            None,
        )
        for end in ends:
            with self.subTest(end=end):
                self.assertEqual(
                    "waits not reported for Antigravity",
                    self.footer(monitor=False, last_end=end, blind=["Antigravity"]),
                )

    def test_a_person_with_an_old_monitor_file_still_sees_fresh_stdin_quota(self) -> None:
        for age in (61, -6):
            with self.subTest(age=age):
                line_file(
                    self.home,
                    "claude",
                    "sess-1",
                    good_line(monitor=True, level="extreme", at=NOW - age),
                )
                line = self.read()
                self.assertEqual(
                    "5h 82% resets in 2h 10m",
                    terminal_client.compose_footer(pro_payload(), line, NOW),
                )

    def test_the_persons_level_and_end_vocabularies_agree_with_the_producers(self) -> None:
        self.assertEqual(
            set(levels.DRIFT_SCALE) | {levels.NOT_ENOUGH}, set(terminal_client.FOOTER_LEVELS)
        )
        self.assertEqual(set(live_lease.END_REASONS), set(terminal_client.MONITOR_END_NOTES))


class ComposeFooterTest(unittest.TestCase):
    def compose(self, payload: dict[str, object] | None, line: terminal_client.Line | None) -> str:
        return terminal_client.compose_footer(payload, line, NOW)

    def test_a_count_and_the_tightest_window_are_printed_together(self) -> None:
        line = terminal_client.Line(2, ())

        self.assertEqual("2 waiting · 5h 82% resets in 2h 10m", self.compose(pro_payload(), line))

    def test_no_rate_limits_prints_no_quota(self) -> None:
        got = self.compose(pro_payload(rate_limits=None), terminal_client.Line(1, ()))

        self.assertEqual("1 waiting", got)

    def test_no_line_prints_the_quota_alone(self) -> None:
        self.assertEqual("5h 82% resets in 2h 10m", self.compose(pro_payload(), None))

    def test_a_steady_board_with_no_quota_prints_nothing(self) -> None:
        self.assertEqual("", self.compose({}, terminal_client.Line(0, ())))
        self.assertEqual("", self.compose(None, None))
        self.assertEqual("", self.compose({}, terminal_client.Line(None, ())))

    def test_zero_waiting_is_not_printed_beside_a_quota(self) -> None:
        got = self.compose(pro_payload(), terminal_client.Line(0, ()))

        self.assertEqual("5h 82% resets in 2h 10m", got)

    def test_harnesses_that_cannot_report_a_wait_are_named_by_their_board_labels(self) -> None:
        got = self.compose({}, terminal_client.Line(0, ("Cursor", "Droid")))

        self.assertEqual("waits not reported for Cursor, Droid", got)

    def test_an_unmeasured_wait_beside_blind_harnesses_names_them_and_counts_nothing(self) -> None:
        got = self.compose({}, terminal_client.Line(None, ("Cursor",)))

        self.assertEqual("waits not reported for Cursor", got)

    def test_the_segments_run_waiting_then_blind_then_quota(self) -> None:
        got = self.compose(pro_payload(), terminal_client.Line(3, ("Cursor",)))

        self.assertEqual("3 waiting · waits not reported for Cursor · 5h 82% resets in 2h 10m", got)


class ParseFooterArgsTest(unittest.TestCase):
    def test_a_lone_footer_and_its_session_forms_are_the_client_s(self) -> None:
        for argv, flag in (
            (["--footer"], None),
            (["--footer", "--session", "claude:abc"], "claude:abc"),
            (["--session", "claude:abc", "--footer"], "claude:abc"),
            (["--footer", "--session=claude:abc"], "claude:abc"),
            (["--session=claude:abc", "--footer"], "claude:abc"),
        ):
            with self.subTest(argv=argv):
                self.assertTrue(terminal_client.handles(argv))
                self.assertEqual((True, flag), terminal_client.parse_footer_args(argv))

    def test_anything_beside_it_goes_to_the_cli(self) -> None:
        for argv in (
            ["--footer", "--port", "4631"],
            ["--footer", "--status"],
            ["--footer", "--version"],
            ["--footer", "--footer"],
            ["--footer", "--session"],
            ["--session", "claude:abc"],
            ["--footer", "extra"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(terminal_client.handles(argv))


class RunFooterTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.env = {"COMPASS_HOME": self.home}

    def run_footer(
        self,
        argv: list[str],
        stdin_text: str = "",
        env: dict[str, str] | None = None,
        now: float = NOW,
    ) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            code = terminal_client.run_footer(
                argv,
                self.env if env is None else env,
                io.StringIO(stdin_text),
                out,
                now=now,
            )
        return code, out.getvalue(), err.getvalue()

    def test_a_line_file_and_a_pro_payload_print_the_count_and_the_tightest_window(self) -> None:
        line_file(self.home, "claude", "sess-1", good_line())

        code, out, err = self.run_footer(["--footer"], json.dumps(pro_payload()))

        self.assertEqual((0, "2 waiting · 5h 82% resets in 2h 10m\n", ""), (code, out, err))

    def test_no_rate_limits_prints_no_quota(self) -> None:
        line_file(self.home, "claude", "sess-1", good_line())

        _, out, _ = self.run_footer(["--footer"], json.dumps(pro_payload(rate_limits=None)))

        self.assertEqual("2 waiting\n", out)

    def test_a_stale_missing_or_unreadable_line_leaves_its_segments_out_and_exits_zero(
        self,
    ) -> None:
        stdin = json.dumps(pro_payload())
        stale = good_line(at=NOW - 10_000)
        for body in (None, stale, "{bad"):
            with self.subTest(body=body):
                if body is not None:
                    line_file(self.home, "claude", "sess-1", body)

                code, out, err = self.run_footer(["--footer"], stdin)

                self.assertEqual((0, "5h 82% resets in 2h 10m\n", ""), (code, out, err))

    def test_nothing_to_say_prints_nothing_and_exits_zero(self) -> None:
        self.assertEqual((0, "", ""), self.run_footer(["--footer"], "", env={}))

    def test_a_session_it_cannot_tell_prints_nothing_with_no_stderr(self) -> None:
        line_file(self.home, "claude", "sess-1", good_line())

        for argv, stdin in (
            (["--footer"], "{}"),
            (["--footer", "--session", "bad flag"], json.dumps(pro_payload())),
            (["--footer", "--session", "claude:a b"], json.dumps(pro_payload())),
        ):
            with self.subTest(argv=argv):
                code, out, err = self.run_footer(argv, stdin)

                self.assertEqual((0, "", ""), (code, out, err))

    def test_the_session_flag_wins_over_the_payload_and_the_environment(self) -> None:
        line_file(self.home, "claude", "flagged", good_line(waiting=7))
        env = {**self.env, "CLAUDE_CODE_SESSION_ID": "env-id"}

        _, out, _ = self.run_footer(
            ["--footer", "--session", "claude:flagged"], json.dumps(pro_payload()), env=env
        )

        self.assertTrue(out.startswith("7 waiting"))

    def test_the_environment_names_the_session_when_stdin_does_not(self) -> None:
        line_file(self.home, "claude", "env-id", good_line(waiting=4))
        env = {**self.env, "CLAUDE_CODE_SESSION_ID": "env-id"}

        _, out, _ = self.run_footer(["--footer"], "", env=env)

        self.assertEqual("4 waiting\n", out)

    def test_a_number_too_large_for_a_float_withholds_its_window_not_the_whole_line(self) -> None:
        line_file(self.home, "claude", "sess-1", good_line(waiting=2))
        huge = 10**400
        for field in ("used_percentage", "resets_at"):
            payload = pro_payload(
                rate_limits={
                    "five_hour": {"used_percentage": 50, "resets_at": NOW + 600} | {field: huge}
                }
            )
            with self.subTest(field=field):
                text = json.dumps(payload)

                code, out, err = self.run_footer(["--footer"], text)

                self.assertEqual(0, code)
                self.assertEqual("", err)
                self.assertTrue(out.startswith("2 waiting"), out)

    def test_nothing_it_does_can_raise_into_the_status_bar(self) -> None:
        with mock.patch.object(terminal_client, "compose_footer", side_effect=RuntimeError("x")):
            code, out, err = self.run_footer(["--footer"], json.dumps(pro_payload()))

        self.assertEqual((0, "", ""), (code, out, err))

    def test_a_broken_stdout_still_exits_zero(self) -> None:
        class Broken(io.StringIO):
            def write(self, _s: str) -> int:
                raise BrokenPipeError

        code = terminal_client.run_footer(
            ["--footer"], self.env, io.StringIO(json.dumps(pro_payload())), Broken(), now=NOW
        )

        self.assertEqual(0, code)

    def test_it_opens_no_socket(self) -> None:
        line_file(self.home, "claude", "sess-1", good_line(monitor=True, level="high"))
        boom = AssertionError("the footer touched the network")
        with (
            mock.patch.object(socket.socket, "connect", side_effect=boom),
            mock.patch.object(socket, "create_connection", side_effect=boom),
            mock.patch.object(socket, "getaddrinfo", side_effect=boom),
        ):
            code, out, _ = self.run_footer(["--footer"], json.dumps(pro_payload()))

        self.assertEqual(0, code)
        self.assertTrue(out.startswith("drift High · 2 waiting"))


class FooterDispatchTest(unittest.TestCase):
    def test_a_lone_footer_is_answered_without_calling_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as home, mock.patch.object(cli, "main") as main:
            out = io.StringIO()
            with (
                mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
                mock.patch.object(sys, "stdin", io.StringIO("")),
                contextlib.redirect_stdout(out),
            ):
                code = entry.main(["--footer"])

        self.assertEqual(0, code)
        main.assert_not_called()

    def test_footer_beside_serving_options_is_a_usage_error_from_the_cli(self) -> None:
        acted = AssertionError("a usage error must come before anything acts")
        for argv in (
            ["--footer", "--port", "4631"],
            ["--footer", "--status"],
            ["--footer", "--stop"],
            ["--footer", "--forget"],
            ["--footer", "--diagnose"],
        ):
            with self.subTest(argv=argv), tempfile.TemporaryDirectory() as home:
                err = io.StringIO()
                # These options stop, inspect and delete from a real dashboard and a real home, so
                # a regression must fail loudly here rather than reach either: a temporary home,
                # and every action patched to raise.
                with (
                    mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
                    contextlib.redirect_stderr(err),
                    mock.patch.object(cli, "build_runtime", side_effect=acted),
                    mock.patch.object(cli, "run_one_shot", side_effect=acted),
                    mock.patch.object(lifecycle, "stop_instance", side_effect=acted),
                    mock.patch.object(lifecycle, "instance_status", side_effect=acted),
                    mock.patch.object(lifecycle, "serve", side_effect=acted),
                    self.assertRaises(SystemExit) as raised,
                ):
                    cli.main(argv)

                self.assertEqual(2, raised.exception.code)
                self.assertIn("--footer", err.getvalue())

    def test_session_alone_is_a_usage_error_from_the_cli(self) -> None:
        err = io.StringIO()
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.dict(os.environ, {"COMPASS_HOME": home}),
            mock.patch.object(cli, "build_runtime", side_effect=AssertionError("acted")),
            contextlib.redirect_stderr(err),
            self.assertRaises(SystemExit) as raised,
        ):
            cli.main(["--session", "claude:abc"])

        self.assertEqual(2, raised.exception.code)

    def test_both_options_are_in_the_parser_and_the_help(self) -> None:
        parser = cli.build_parser()
        spellings = {s for action in parser._actions for s in action.option_strings}

        self.assertLessEqual({"--footer", "--session"}, spellings)
        self.assertIn("--footer", parser.format_help())


class FooterLightPathTest(unittest.TestCase):
    """The footer's budget is mostly import time, so the import set is the deterministic proof."""

    def run_server(self, *args: str, stdin: str, home: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "importtime", str(SERVER_PATH), *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            env={**os.environ, "COMPASS_HOME": home, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def test_footer_through_server_py_imports_neither_the_cli_nor_an_http_client(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            line_file(
                home, "claude", "sess-1", good_line(at=time.time(), monitor=True, level="medium")
            )
            payload = pro_payload(
                rate_limits={"five_hour": {"used_percentage": 12, "resets_at": time.time() + 3600}}
            )

            done = self.run_server("--footer", stdin=json.dumps(payload), home=home)

        self.assertEqual(0, done.returncode)
        self.assertTrue(
            done.stdout.startswith("drift Medium · 2 waiting · 5h 12% resets in "), done.stdout
        )
        loaded = [
            name
            for name in (
                "compass_runtime.cli",
                "compass_runtime.http_api",
                "compass_runtime.aggregate",
                "http.client",
                "socket",
            )
            if f" {name}\n" in done.stderr
        ]
        self.assertEqual([], loaded)

    def test_a_pipe_held_open_cannot_hang_the_command(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            started = time.monotonic()
            proc = subprocess.Popen(
                [sys.executable, str(SERVER_PATH), "--footer"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "COMPASS_HOME": home, "CLAUDE_CODE_SESSION_ID": ""},
            )
            try:
                code = proc.wait(timeout=60)
                elapsed = time.monotonic() - started
            finally:
                proc.kill()
                proc.wait()
                for stream in (proc.stdin, proc.stdout, proc.stderr):
                    if stream is not None:
                        stream.close()

        self.assertEqual(0, code)
        # Hung against slow: a cold interpreter on a loaded runner measures its start-up here. The
        # quarter-second stdin default is decided on the logical clock above.
        self.assertLess(elapsed, 30.0)


class FooterDocumentationTest(unittest.TestCase):
    ROOT = SERVER_PATH.parents[3]

    def doc(self, name: str) -> str:
        return (self.ROOT / name).read_text(encoding="utf-8")

    def test_the_manual_carries_a_row_for_each_option_and_the_files_it_reads(self) -> None:
        manual = self.doc("MANUAL.md")

        self.assertIn("| `--footer` |", manual)
        self.assertIn("| `--session HARNESS:SESSION_ID` |", manual)
        self.assertIn("| `footer/HARNESS-HASH.json` |", manual)

    def test_the_security_policy_names_the_line_files_and_says_the_footer_sends_nothing(
        self,
    ) -> None:
        security = self.doc("SECURITY.md")

        self.assertIn("### The status line files", security)
        self.assertIn("footer/claude-<hash>.json", security)
        self.assertIn("| `--footer`, the status line segment | Nothing.", security)

    def test_how_to_use_gives_the_plain_procedure_and_the_wrapper_procedure(self) -> None:
        how = self.doc("HOW_TO_USE.md")

        self.assertIn("## Show waiting sessions and quota in the Claude Code status line", how)
        self.assertIn("### A status line of its own", how)
        self.assertIn("### A status line you already have, such as Barista", how)
        self.assertIn("input=$(cat)", how)

    def test_no_public_document_names_a_tracker_for_it(self) -> None:
        for name in ("HOW_TO_USE.md", "MANUAL.md", "SECURITY.md"):
            with self.subTest(name=name):
                self.assertNotRegex(self.doc(name), r"DRC-\d+|linear\.app")


class LineStaleCeilingTest(unittest.TestCase):
    def test_the_ceiling_outlasts_the_writers_refresh_with_room_for_a_missed_one(self) -> None:
        self.assertGreaterEqual(
            terminal_client.LINE_STALE_SEC, 2 * footer_lines.REFRESH_SEC + footer_lines.REFRESH_SEC
        )
        self.assertTrue(math.isfinite(terminal_client.LINE_STALE_SEC))


class NothingElseImportsTheWriterTest(unittest.TestCase):
    def test_the_client_does_not_import_the_writer(self) -> None:
        source = Path(terminal_client.__file__).read_text(encoding="utf-8")

        self.assertNotIn("footer_lines", source)


if __name__ == "__main__":
    unittest.main()
