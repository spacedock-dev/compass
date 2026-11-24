"""The dashboard's half of `--footer`: one small file per Claude session."""

from __future__ import annotations

import dataclasses
import errno
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

from compass_runtime import (
    aggregate,
    cli,
    footer_lines,
    http_api,
    observation,
    project_context,
    reading_evidence,
    reading_policy,
    row_progress,
    terminal_client,
    terminal_sessions,
)
from compass_runtime import annotations as annotation_store
from compass_runtime import io as runtime_io

from . import support, test_analysis_result, test_live_estimate
from .test_analysis_result import _RowProgress
from .test_claude_checks import SHORT, SID
from .test_live_lease_http import LeaseRoute
from .test_subagent_checks import Subagent

if TYPE_CHECKING:
    from compass_runtime.reading import Assessment

NOW = 1_800_000_000.0
NAME = re.compile(r"claude-[0-9a-f]{32}\.json")


def harness(
    key: str,
    label: str,
    *,
    reports: bool = True,
    error: str | None = None,
    discovered: bool = True,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "discovered": discovered,
        "reports_needs_input": reports,
        "reports_needs_input_when": None,
        "error": error,
    }


def row(
    harness_key: str, sid: str, state: str = "working", *, active: bool = True
) -> dict[str, Any]:
    return {"harness": harness_key, "sid": sid, "state": state, "active": active}


def board(
    sessions: list[dict[str, Any]],
    harnesses: list[dict[str, Any]] | None = None,
    asks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "asks": asks or [],
        "generated": NOW,
        "harnesses": [harness("claude", "Claude Code")] if harnesses is None else harnesses,
        "sessions": sessions,
    }


def ask(session_id: str | None, question: str | None = "May I?", **more: Any) -> dict[str, Any]:
    return {"id": "a1", "harness": "claude", "session_id": session_id, "question": question} | more


def waiting_of(built: dict[tuple[str, str], dict[str, Any]], sid: str) -> object:
    return built[("claude", sid)]["waiting"]


SESSIONS_PAYLOADS = [
    json.loads(
        (
            support.SERVER_PATH.parents[3]
            / "frontend"
            / "test"
            / "fixtures"
            / "client-contract"
            / "data-session-states.json"
        ).read_text(encoding="utf-8")
    )["response"]["body"]
]


class OneRuleTest(unittest.TestCase):
    """The footer and `--sessions waiting` count the Attention queue by one definition."""

    def test_every_row_counts_the_subjects_the_sessions_list_names_less_its_own(self) -> None:
        for payload in SESSIONS_PAYLOADS:
            built = footer_lines.build(payload, pid=1, now=NOW)
            self.assertTrue(built)
            for (_harness, identity), body in built.items():
                with self.subTest(row=identity):
                    listed = terminal_sessions.board(payload, exclude=identity).waiting
                    self.assertEqual(len(listed), body["waiting"])

    def test_the_footer_holds_no_queue_rule_of_its_own(self) -> None:
        source = (support.SERVER_PATH.parent / "compass_runtime" / "footer_lines.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("terminal_sessions", source)
        for private in ("_subjects", "_ask_owner", '"needs_input"', '"question"'):
            self.assertFalse(private in source, private)

    def test_a_board_no_harness_measured_says_nothing_and_a_quiet_measured_one_says_zero(
        self,
    ) -> None:
        quiet = [row("claude", "a"), row("claude", "b")]

        unmeasured = footer_lines.build(
            board(quiet, [harness("claude", "Claude Code", reports=False)]), pid=1, now=NOW
        )
        failed = footer_lines.build(
            board(quiet, [harness("claude", "Claude Code", error="boom")]), pid=1, now=NOW
        )
        measured = footer_lines.build(board(quiet), pid=1, now=NOW)

        self.assertEqual([None, None], [waiting_of(unmeasured, s) for s in "ab"])
        self.assertEqual([None, None], [waiting_of(failed, s) for s in "ab"])
        self.assertEqual([0, 0], [waiting_of(measured, s) for s in "ab"])


class BuildTest(unittest.TestCase):
    def build(self, collection: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
        return footer_lines.build(collection, pid=4242, now=NOW)

    def test_each_session_counts_the_others_waiting_and_never_itself(self) -> None:
        built = self.build(
            board(
                [
                    row("claude", "a", "needs_input"),
                    row("claude", "b", "needs_input"),
                    row("claude", "c"),
                ]
            )
        )

        self.assertEqual((1, 1, 2), tuple(waiting_of(built, s) for s in "abc"))

    def test_a_wait_the_page_marks_unconfirmed_is_counted_as_the_page_counts_it(self) -> None:
        waiting = row("claude", "a", "needs_input") | {"wait_unconfirmed": True}

        built = self.build(board([waiting, row("claude", "b")]))

        self.assertEqual(1, waiting_of(built, "b"))

    def test_only_claude_sessions_get_a_file_and_every_harness_can_make_a_session_wait(
        self,
    ) -> None:
        built = self.build(
            board(
                [row("claude", "a"), row("codex", "x", "needs_input")],
                [harness("claude", "Claude Code"), harness("codex", "Codex")],
            )
        )

        self.assertEqual([("claude", "a")], list(built))
        self.assertEqual(1, waiting_of(built, "a"))

    def test_a_claude_row_is_filed_under_its_whole_session_id_not_the_eight_character_prefix(
        self,
    ) -> None:
        full = "abcd1234-0000-4000-8000-000000000001"
        built = self.build(
            board(
                [
                    row("claude", "abcd1234") | {"resume_id": full},
                    row("claude", "ffff0000") | {"resume_id": "other-id"},
                    row("claude", "eeee1111"),
                ]
            )
        )

        self.assertEqual(
            [("claude", full), ("claude", "ffff0000"), ("claude", "eeee1111")], list(built)
        )

    def test_the_session_waiting_is_still_excluded_from_its_own_count_under_its_whole_id(
        self,
    ) -> None:
        full = "abcd1234-0000-4000-8000-000000000001"
        built = self.build(
            board(
                [
                    row("claude", "abcd1234", "needs_input") | {"resume_id": full},
                    row("claude", "ffff0000", "needs_input"),
                ]
            )
        )

        self.assertEqual((1, 1), (waiting_of(built, full), waiting_of(built, "ffff0000")))

    def waits(self, sessions: list[dict[str, Any]], asks: list[dict[str, Any]]) -> list[object]:
        built = self.build(board(sessions, asks=asks))
        return [waiting_of(built, r["sid"]) for r in sessions]

    def test_a_pending_ask_owned_by_another_session_is_a_wait_the_footer_counts(self) -> None:
        rows = [row("claude", "aaaaaaaa"), row("claude", "bbbbbbbb")]

        self.assertEqual([1, 0], self.waits(rows, [ask("bbbbbbbb")]))

    def test_a_pending_ask_owned_by_the_current_session_is_not_counted_against_itself(self) -> None:
        rows = [row("claude", "aaaaaaaa"), row("claude", "bbbbbbbb")]

        self.assertEqual([0, 1], self.waits(rows, [ask("aaaaaaaa")]))

    def test_an_ownerless_ask_counts_for_every_session(self) -> None:
        rows = [row("claude", "aaaaaaaa"), row("claude", "bbbbbbbb")]

        self.assertEqual([1, 1], self.waits(rows, [ask(None)]))
        self.assertEqual([1, 1], self.waits(rows, [ask("nobody-has-this-id")]))

    def test_an_ask_whose_owner_matches_two_rows_is_ownerless(self) -> None:
        rows = [row("claude", "aaaaaaaa"), row("codex", "aaaaaaaa"), row("claude", "cccccccc")]

        got = self.waits(rows, [ask("aaaaaaaa", harness="")])

        self.assertEqual([1, 1, 1], got)

    def test_a_row_that_is_waiting_and_holds_an_ask_is_one_wait_not_two(self) -> None:
        rows = [row("claude", "aaaaaaaa"), row("claude", "bbbbbbbb", "needs_input")]

        self.assertEqual([1, 0], self.waits(rows, [ask("bbbbbbbb")]))

    def test_each_ask_and_each_waiting_row_is_its_own_subject(self) -> None:
        rows = [
            row("claude", "aaaaaaaa"),
            row("claude", "bbbbbbbb"),
            row("claude", "cccccccc", "needs_input"),
        ]
        asks = [ask("bbbbbbbb", id="x"), ask("bbbbbbbb", id="y"), ask(None, id="z")]

        self.assertEqual([3, 2, 2], self.waits(rows, asks))

    def test_an_ask_with_no_question_is_ignored(self) -> None:
        rows = [row("claude", "aaaaaaaa"), row("claude", "bbbbbbbb")]

        for blank in ("", "   ", None):
            with self.subTest(question=blank):
                self.assertEqual([0, 0], self.waits(rows, [ask("bbbbbbbb", question=blank)]))

    def test_pending_asks_do_not_make_an_unmeasured_board_measured(self) -> None:
        built = self.build(
            board(
                [row("claude", "aaaaaaaa")],
                [harness("claude", "Claude Code", reports=False)],
                [ask(None)],
            )
        )

        self.assertIsNone(waiting_of(built, "aaaaaaaa"))

    def test_a_board_with_no_waiter_reads_a_measured_zero(self) -> None:
        built = self.build(board([row("claude", "a"), row("claude", "b")]))

        self.assertEqual(0, waiting_of(built, "a"))

    def test_a_harness_that_cannot_report_a_wait_is_named_by_its_board_label(self) -> None:
        built = self.build(
            board(
                [row("claude", "a"), row("cursor", "x"), row("droid", "y")],
                [
                    harness("claude", "Claude Code"),
                    harness("cursor", "Cursor", reports=False),
                    harness("droid", "Droid", reports=False),
                ],
            )
        )

        self.assertEqual(["Cursor", "Droid"], built[("claude", "a")]["blind"])

    def test_a_blind_harness_with_no_active_row_is_not_named(self) -> None:
        built = self.build(
            board(
                [row("claude", "a"), row("cursor", "x", active=False)],
                [harness("claude", "Claude Code"), harness("cursor", "Cursor", reports=False)],
            )
        )

        self.assertEqual([], built[("claude", "a")]["blind"])

    def test_a_harness_whose_read_failed_is_named_because_its_waits_were_not_read(self) -> None:
        built = self.build(
            board(
                [row("claude", "a")],
                [harness("claude", "Claude Code"), harness("codex", "Codex", error="boom")],
            )
        )

        self.assertEqual(["Codex"], built[("claude", "a")]["blind"])

    def test_the_count_is_unmeasured_not_zero_when_no_reporting_harness_was_read(self) -> None:
        cases: dict[str, list[dict[str, Any]] | None] = {
            "none reporting": [harness("claude", "Claude Code", reports=False)],
            "reporter failed": [harness("claude", "Claude Code", error="boom")],
            "reporter not found": [harness("claude", "Claude Code", discovered=False)],
            "no harness block": [],
        }
        for label, harnesses in cases.items():
            with self.subTest(case=label):
                built = self.build(board([row("claude", "a")], harnesses))

                self.assertIsNone(waiting_of(built, "a"))

    def test_a_person_with_no_monitor_gets_no_level_in_the_version_one_file(
        self,
    ) -> None:
        built = self.build(board([row("claude", "a")]))

        self.assertEqual(
            {
                "v": 1,
                "at": NOW,
                "pid": 4242,
                "waiting": 0,
                "blind": [],
                "monitor": False,
                "stored_progress": None,
                "last_end": None,
                "model_calls_paused": None,
            },
            built[("claude", "a")],
        )

    def test_a_collection_that_is_not_shaped_as_expected_builds_nothing_and_raises_nothing(
        self,
    ) -> None:
        cases: tuple[dict[str, Any], ...] = (
            {},
            {"sessions": None},
            {"sessions": [5, {"sid": 1}]},
            {"sessions": [{}]},
        )
        for collection in cases:
            with self.subTest(collection=collection):
                self.assertEqual({}, self.build(collection))


class LinesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.dir = os.path.join(self.home, "footer")
        self.lines = footer_lines.Lines(self.home, pid=4242)

    def files(self) -> list[str]:
        return sorted(os.listdir(self.dir)) if os.path.isdir(self.dir) else []

    def body(self, sid: str) -> dict[str, Any]:
        with open(
            os.path.join(self.dir, footer_lines.line_name("claude", sid)), encoding="utf-8"
        ) as h:
            loaded: dict[str, Any] = json.load(h)
        return loaded

    def test_idle_touch_keeps_the_footer_readable_after_a_wall_clock_setback(self) -> None:
        self.lines.update(board([row("claude", "a")]), NOW)
        self.lines.touch(NOW - 12)
        session = terminal_client.Session("claude", "a", "status line")
        self.assertIsNotNone(terminal_client.read_line(self.home, session, NOW - 12))
        self.assertEqual(NOW - 12, self.body("a")["at"])

    def test_an_older_touch_leaves_the_newer_collections_footer_readable(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def permission() -> bool:
            if threading.current_thread() is worker:
                entered.set()
                release.wait(30)
            return False

        self.lines = footer_lines.Lines(self.home, model_calls_paused=permission)
        worker = threading.Thread(target=self.lines.touch, args=(NOW + 1,))
        collection = board([row("claude", "a")])
        self.lines.update(collection, NOW)
        worker.start()
        try:
            self.assertTrue(entered.wait(30))
            self.lines.update(collection, NOW + 70)
        finally:
            release.set()
            worker.join(30)
        self.assertFalse(worker.is_alive())
        session = terminal_client.Session("claude", "a", "status line")
        self.assertIsNotNone(terminal_client.read_line(self.home, session, NOW + 70))
        self.assertEqual(NOW + 70, self.body("a")["at"])

    def test_an_older_collection_uses_the_newer_idle_touch_stamp(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def permission() -> bool:
            if threading.current_thread() is worker:
                entered.set()
                release.wait(30)
            return False

        self.lines = footer_lines.Lines(self.home, model_calls_paused=permission)
        initial = board([row("claude", "a")])
        changed = board([row("claude", "a"), row("claude", "b", "needs_input")])
        worker = threading.Thread(target=self.lines.update, args=(changed, NOW + 1))
        session = terminal_client.Session("claude", "a", "status line")
        self.lines.update(initial, NOW)
        worker.start()
        try:
            self.assertTrue(entered.wait(30))
            self.lines.touch(NOW + 70)
            self.assertEqual(NOW + 70, self.body("a")["at"])
        finally:
            release.set()
            worker.join(30)
        self.assertFalse(worker.is_alive())
        line = terminal_client.read_line(self.home, session, NOW + 70)
        assert line is not None
        self.assertEqual(1, line.waiting)
        self.assertEqual(NOW + 70, self.body("a")["at"])

    def test_removing_all_lines_releases_the_snapshot_validators(self) -> None:
        validators = {
            key: mock.Mock()
            for key in ("validate_progress", "validate_stores", "validate_prefixes")
        }
        references = [weakref.ref(validate) for validate in validators.values()]
        self.lines.update(board([row("claude", "a")]), NOW, **validators)
        validators.clear()
        self.lines.remove_all()
        self.assertEqual([None, None, None], [reference() for reference in references])

    def test_a_person_sees_pause_resume_and_unknown_on_the_next_idle_refresh(self) -> None:
        paused: bool | None = False

        def permission() -> bool | None:
            return paused

        self.lines = footer_lines.Lines(self.home, model_calls_paused=permission)
        old_board = board([row("claude", "a")])
        old_board["reading"] = {"off": False}
        self.lines.update(old_board, NOW)
        self.assertIs(self.body("a")["model_calls_paused"], False)
        for offset, value in enumerate((True, False, True, None), 1):
            paused = value
            self.lines.touch(NOW + offset)
            self.assertIs(self.body("a")["model_calls_paused"], value)
        paused = True
        self.lines.update(old_board, NOW + 5)
        self.assertIs(self.body("a")["model_calls_paused"], True)
        self.assertEqual(1, self.body("a")["v"])

    def test_a_person_keeps_a_newer_pause_when_an_older_store_read_finishes_late(self) -> None:
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        paused = False
        hold = False

        def permission() -> bool:
            answer = paused
            if hold and not answer:
                entered.set()
                release.wait(30)
            return answer

        self.lines = footer_lines.Lines(self.home, model_calls_paused=permission)
        old = board([row("claude", "a")])
        self.lines.update(old, NOW)
        hold = True
        worker = threading.Thread(target=self.lines.update, args=(old, NOW + 1))
        worker.start()
        try:
            self.assertTrue(entered.wait(30))
            paused = True
            self.lines.touch(NOW + 2)
            self.assertIs(self.body("a")["model_calls_paused"], True)
        finally:
            release.set()
            worker.join(30)
        self.assertFalse(worker.is_alive())
        self.assertIs(self.body("a")["model_calls_paused"], True)

    def test_a_person_keeps_footer_service_while_the_permission_store_is_read(self) -> None:
        sampled = []

        def permission() -> bool:
            acquired = self.lines._lock.acquire(blocking=False)
            sampled.append(acquired)
            if acquired:
                self.lines._lock.release()
            return True

        self.lines = footer_lines.Lines(self.home, model_calls_paused=permission)
        self.lines.update(board([row("claude", "a")]), NOW)
        self.lines.touch(NOW + 1)
        self.assertEqual([True, True], sampled)
        self.assertIs(self.body("a")["model_calls_paused"], True)

    def test_a_session_gets_one_owner_only_file_in_an_owner_only_directory(self) -> None:
        self.lines.update(board([row("claude", "a")]), NOW)

        self.assertEqual([footer_lines.line_name("claude", "a")], self.files())
        self.assertRegex(self.files()[0], NAME)
        if os.name != "nt":
            self.assertEqual(0o700, stat.S_IMODE(os.stat(self.dir).st_mode))
            path = os.path.join(self.dir, self.files()[0])
            self.assertEqual(0o600, stat.S_IMODE(os.stat(path).st_mode))
        self.assertEqual(0, self.body("a")["waiting"])

    def test_an_id_with_path_characters_never_reaches_a_path_or_a_file(self) -> None:
        sid = "../../x/ünï?%#" + "z" * 150
        self.lines.update(board([row("claude", sid)]), NOW)

        self.assertEqual([footer_lines.line_name("claude", sid)], self.files())
        for name in self.files():
            with open(os.path.join(self.dir, name), encoding="utf-8") as handle:
                self.assertNotIn("zzzz", handle.read())
        self.assertEqual([], [n for n in os.listdir(self.home) if n != "footer"])

    def test_the_file_is_not_rewritten_while_its_content_is_unchanged_and_young(self) -> None:
        self.lines.update(board([row("claude", "a")]), NOW)
        with mock.patch.object(runtime_io, "atomic_write_owner_only") as write:
            self.lines.update(board([row("claude", "a")]), NOW + footer_lines.REFRESH_SEC - 1)

        write.assert_not_called()

    def test_an_unchanged_file_is_refreshed_once_it_is_older_than_the_refresh_interval(
        self,
    ) -> None:
        self.lines.update(board([row("claude", "a")]), NOW)

        later = NOW + footer_lines.REFRESH_SEC + 1
        self.lines.update(board([row("claude", "a")]), later)

        self.assertEqual(later, self.body("a")["at"])

    def test_a_changed_count_is_written_at_once(self) -> None:
        self.lines.update(board([row("claude", "a"), row("claude", "b")]), NOW)
        self.lines.update(board([row("claude", "a"), row("claude", "b", "needs_input")]), NOW + 1)

        self.assertEqual((1, NOW + 1), (self.body("a")["waiting"], self.body("a")["at"]))

    def test_touch_refreshes_only_what_has_aged_and_changes_nothing_else(self) -> None:
        self.lines.update(board([row("claude", "a", "needs_input"), row("claude", "b")]), NOW)
        with mock.patch.object(runtime_io, "atomic_write_owner_only") as write:
            self.lines.touch(NOW + footer_lines.REFRESH_SEC - 1)
        write.assert_not_called()

        later = NOW + footer_lines.REFRESH_SEC + 1
        self.lines.touch(later)

        self.assertEqual((0, later), (self.body("a")["waiting"], self.body("a")["at"]))
        self.assertEqual((1, later), (self.body("b")["waiting"], self.body("b")["at"]))

    def test_a_touch_before_anything_was_written_writes_nothing(self) -> None:
        self.lines.touch(NOW + 1000)

        self.assertEqual([], self.files())

    def test_a_stranger_file_older_than_the_sweep_age_is_removed_and_a_young_one_is_kept(
        self,
    ) -> None:
        os.makedirs(self.dir)
        old = os.path.join(self.dir, "claude-" + "0" * 32 + ".json")
        young = os.path.join(self.dir, "claude-" + "1" * 32 + ".json")
        other = os.path.join(self.dir, "notes.txt")
        for path in (old, young, other):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{}")
        os.utime(old, (NOW - footer_lines.SWEEP_AGE_SEC - 5,) * 2)
        os.utime(other, (NOW - footer_lines.SWEEP_AGE_SEC - 5,) * 2)
        os.utime(young, (NOW - 60,) * 2)

        self.lines.update(board([row("claude", "a")]), NOW)

        self.assertEqual(
            sorted(["notes.txt", os.path.basename(young), footer_lines.line_name("claude", "a")]),
            self.files(),
        )

    def test_a_departed_sessions_file_is_swept_once_it_is_old_and_is_forgotten_with_it(
        self,
    ) -> None:
        self.lines.update(board([row("claude", "a")]), NOW)
        gone = footer_lines.line_name("claude", "a")

        self.lines.update(board([row("claude", "b")]), NOW + footer_lines.SWEEP_EVERY_SEC + 10)

        self.assertNotIn(gone, self.files())
        self.assertNotIn(gone, self.lines._written)

    def test_the_sweep_runs_at_most_once_an_interval(self) -> None:
        self.lines.update(board([row("claude", "a")]), NOW)
        with mock.patch.object(os, "scandir") as scandir:
            self.lines.update(board([row("claude", "a")]), NOW + footer_lines.REFRESH_SEC + 1)

        scandir.assert_not_called()

    def test_a_failing_write_never_raises_into_the_caller_and_says_so_once_on_the_sink(
        self,
    ) -> None:
        said: list[str] = []
        lines = footer_lines.Lines(self.home, pid=1, diagnostic_sink=said.append)
        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError("full")):
            lines.update(board([row("claude", "a")]), NOW)
            lines.update(board([row("claude", "a", "needs_input"), row("claude", "b")]), NOW + 1)

        self.assertEqual(1, len(said))
        self.assertIn("footer", said[0])

    def test_a_home_that_cannot_hold_the_directory_never_raises(self) -> None:
        blocker = os.path.join(self.home, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        lines = footer_lines.Lines(blocker, pid=1, diagnostic_sink=lambda _m: None)

        lines.update(board([row("claude", "a")]), NOW)
        lines.touch(NOW + 100)

    def test_remove_all_deletes_the_files_this_instance_wrote_and_only_those(self) -> None:
        self.lines.update(board([row("claude", "a")]), NOW)
        stranger = os.path.join(self.dir, "claude-" + "2" * 32 + ".json")
        with open(stranger, "w", encoding="utf-8") as handle:
            handle.write("{}")

        self.lines.remove_all()

        self.assertEqual([os.path.basename(stranger)], self.files())

    def test_a_session_that_left_the_board_keeps_its_file_for_the_sweep_not_for_ever(self) -> None:
        self.lines.update(board([row("claude", "a"), row("claude", "b")]), NOW)
        self.lines.update(board([row("claude", "a")]), NOW + 10)

        self.assertEqual(2, len(self.files()))


class MonitorSource:
    def __init__(self) -> None:
        self.leases: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []

    def state(self, session: Any) -> dict[str, Any]:
        return self.leases.get(session["sid"], {"on": False})

    def view(self, collection: Any, session: Any, lease: Any) -> dict[str, Any]:
        del collection, lease
        self.calls.append(session["sid"])
        return {"pill": {"level": "medium"}}


class MonitorLinesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.source = MonitorSource()
        self.lines = footer_lines.Lines(
            self.home, pid=1, monitor=self.source, diagnostic_sink=lambda _m: None
        )
        self.collection = board([row("claude", "short-id") | {"resume_id": "short-id-full"}]) | {
            "annotate": True,
        }
        self.source.leases["short-id"] = {"on": True, "episode": 1, "started_at": NOW}

    def body(self, sid: str = "short-id-full") -> dict[str, Any]:
        path = os.path.join(self.home, "footer", footer_lines.line_name("claude", sid))
        with open(path, encoding="utf-8") as handle:
            result: dict[str, Any] = json.load(handle)
        return result

    def publish(self) -> None:
        self.lines.update(self.collection, NOW)
        self.lines.touch(NOW)

    def end(self, at: float = NOW + 1) -> None:
        self.source.leases["short-id"] = {"on": False, "last_end": {"reason": "ended", "at": at}}

    def test_a_live_estimate_is_neither_read_nor_published_by_the_footer(self) -> None:
        self.publish()
        self.assertTrue(self.body()["monitor"])
        self.assertNotIn("level", self.body())
        self.assertIsNone(self.body()["stored_progress"])
        self.assertEqual([], self.source.calls)

    def test_a_stored_departure_comes_from_the_row_and_is_cleared_by_its_next_snapshot(
        self,
    ) -> None:
        source = self.collection["sessions"][0]
        source["stored_progress"] = "high"
        self.end()
        self.lines.update(self.collection, NOW)
        self.assertFalse(self.body()["monitor"])
        self.assertEqual("high", self.body()["stored_progress"])
        for value in ("out-of-date", "future-level", None):
            source["stored_progress"] = value
            self.lines.update(self.collection, NOW + 2)
            self.assertIsNone(self.body()["stored_progress"])
            self.assertEqual([], self.source.calls)

    def test_a_failed_lease_lookup_cannot_refresh_another_sessions_old_departure(self) -> None:
        row_with_progress = row("claude", "other") | {"stored_progress": "high"}
        self.collection["sessions"].append(row_with_progress)
        proof = mock.Mock(return_value=True)
        self.lines.update(
            self.collection, NOW, validate_progress=proof, validate_stores=lambda: True
        )
        self.lines.touch(NOW)
        self.assertEqual("high", self.body("other")["stored_progress"])
        del row_with_progress["stored_progress"]
        original = self.source.state

        def lease(session: dict[str, Any]) -> dict[str, Any]:
            if session["sid"] == "short-id":
                raise OSError("lease unavailable")
            return original(session)

        proof.return_value = False
        with mock.patch.object(self.source, "state", side_effect=lease):
            self.lines.touch(NOW + 70)
            self.assertIsNone(self.body("other")["stored_progress"])
            self.assertEqual(NOW + 70, self.body("other")["at"])
            self.lines.update(self.collection, NOW + 71)
            self.assertIsNone(self.body("other")["stored_progress"])

    def test_a_progress_proof_that_raises_clears_only_its_own_level(self) -> None:
        rows = self.collection["sessions"]
        rows[0]["stored_progress"] = "medium"
        rows.append(row("claude", "other") | {"stored_progress": "high"})
        unavailable = False

        def broken_proof(_now: float, owner: tuple[str, str]) -> bool:
            if unavailable and owner != ("claude", "other"):
                raise OSError("proof unavailable")
            return True

        self.lines.update(
            self.collection, NOW, validate_progress=broken_proof, validate_stores=lambda: True
        )
        self.assertEqual("medium", self.body()["stored_progress"])
        self.assertEqual("high", self.body("other")["stored_progress"])
        unavailable = True
        self.lines.touch(NOW + 1)
        self.assertIsNone(self.body()["stored_progress"])
        self.assertEqual("high", self.body("other")["stored_progress"])

    def test_unavailable_annotations_clear_the_footer_level_without_stopping_the_monitor(
        self,
    ) -> None:
        self.collection["sessions"][0]["stored_progress"] = "high"
        for availability in (
            {"annotate": False},
            {"annotate_unreadable": "Annotations store could not be read."},
        ):
            with self.subTest(availability=availability):
                self.lines.update(self.collection, NOW)
                self.assertEqual("high", self.body()["stored_progress"])
                self.lines.update(self.collection | availability, NOW + 1)
                self.assertIsNone(self.body()["stored_progress"])
                self.assertTrue(self.body()["monitor"])

    def test_a_person_whose_monitor_ends_while_idle_keeps_waits(self) -> None:
        self.publish()
        self.end()
        self.lines.touch(NOW + 1)
        self.assertEqual(
            (False, None, {"reason": "ended", "at": NOW + 1}),
            tuple(self.body()[key] for key in ("monitor", "stored_progress", "last_end")),
        )
        self.collection["sessions"].append(row("codex", "waiter", "needs_input"))
        self.lines.update(self.collection, NOW + 20)
        self.assertEqual(1, self.body()["waiting"])
        self.lines.touch(NOW + 400)
        self.assertEqual(NOW + 400, self.body()["at"])
        self.assertIsNone(self.body()["stored_progress"])

    def test_a_person_who_restarts_the_monitor_loses_the_end_note(self) -> None:
        self.publish()
        self.end()
        self.lines.touch(NOW + 1)
        self.source.leases["short-id"] = {"on": True, "episode": 2, "started_at": NOW + 20}
        self.lines.touch(NOW + 20)
        self.assertEqual(
            (True, None, None),
            tuple(self.body()[k] for k in ("monitor", "stored_progress", "last_end")),
        )

    def test_a_departed_persons_monitored_row_gets_one_terminal_write(self) -> None:
        self.publish()
        self.end()
        self.lines.update(board([]), NOW + 1)
        terminal = self.body()
        self.assertIs(terminal["monitor"], False)
        self.assertIsNone(terminal["stored_progress"])
        self.lines.touch(NOW + 100)
        self.assertEqual(terminal, self.body())

    def test_a_persons_failed_end_write_is_retried_without_restamping_the_old_line(self) -> None:
        self.publish()
        self.end()
        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError("full")):
            self.lines.update(board([]), NOW + 1)
        self.lines.touch(NOW + 2)
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["stored_progress"])
        self.assertEqual(NOW + 2, self.body()["at"])
        self.lines.touch(NOW + 40)
        self.assertEqual(NOW + 2, self.body()["at"])

    def test_a_person_never_gets_a_guessed_monitor_for_duplicate_session_rows(self) -> None:
        source = self.collection["sessions"][0]
        source["stored_progress"] = "high"
        self.lines.update(self.collection, NOW)
        self.assertEqual("high", self.body()["stored_progress"])
        self.collection["sessions"].append(dict(source))
        self.lines.update(self.collection, NOW + 1)
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["stored_progress"])
        self.assertEqual([], self.source.calls)

    def test_a_departed_unmonitored_row_retries_one_clearing_write_for_stored_progress(
        self,
    ) -> None:
        self.source.leases.clear()
        self.collection["sessions"][0]["stored_progress"] = "high"
        self.lines.update(self.collection, NOW)
        self.assertEqual("high", self.body()["stored_progress"])
        self.assertFalse(self.body()["monitor"])
        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError("full")):
            self.lines.update(board([]), NOW + 1)
        self.assertEqual("high", self.body()["stored_progress"])
        self.assertEqual(NOW, self.body()["at"])
        self.lines.touch(NOW + 2)
        final = self.body()
        self.assertIsNone(final["stored_progress"])
        self.assertEqual(NOW + 2, final["at"])
        self.lines.touch(NOW + 400)
        self.assertEqual(final, self.body())

    def test_a_persons_departure_retries_an_end_that_failed_while_the_row_was_present(self) -> None:
        self.publish()
        self.end()
        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError("full")):
            self.lines.touch(NOW + 1)
        self.lines.update(board([]), NOW + 2)
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["stored_progress"])


class FooterRowProgressTest(_RowProgress):
    def test_the_board_withholds_an_archived_collision_inside_the_snapshot_memo(self) -> None:
        archive = self.path.parent.with_name("-work-archive")
        archive.mkdir()
        app, lines, footer, focused = self._departure_footer()
        app.monotonic = lambda: 100.0
        with (
            self.serving(app) as port,
            mock.patch.object(app, "collect", wraps=app.collect) as collect,
            mock.patch.object(
                app._footer_prefixes, "unambiguous", wraps=app._footer_prefixes.unambiguous
            ) as check_prefixes,
        ):
            app.warm_row_progress = None
            (view,) = self.get(port, focused)["sources"]["work"]["drift_views"]
            self.assertEqual("medium", view["pill"]["level"])
            self.assertEqual("medium", self.poll(port))
            self.assertEqual("medium", self._level(footer))
            collect.reset_mock()
            check_prefixes.reset_mock()

            lines.touch(self.now)
            self.assertEqual("medium", self.poll(port))
            self.assertEqual("medium", self.poll(port))
            collect.assert_not_called()
            check_prefixes.assert_called_once()

            self._archive_collision(archive)
            # Both clocks stay fixed so expiry cannot hide a stale board response.
            lines.touch(self.now)
            self.assertIsNone(self._level(footer))
            collect.assert_not_called()
            self.assertIsNone(self.poll(port))
            collect.assert_called_once()
            self.assertIsNone(self.poll(port))
            collect.assert_called_once()
            (view,) = self.get(port, focused)["sources"]["work"]["drift_views"]
            self.assertIsNone(view["pill"])

    def test_a_full_uuid_collision_withholds_the_board_level_and_reuses_the_memo(self) -> None:
        # A live worker keeps the older of two prefix-sharing UUIDs visible under its full id.
        self.path = self.path.with_name(f"{SID}.jsonl")
        with (
            mock.patch.object(test_analysis_result, "SHORT", SID),
            mock.patch.object(test_live_estimate, "SHORT", SID),
        ):
            self.save_goal(lines=())
            reading = self.departure()
        os.utime(self.path, (self.now - 4, self.now - 4))
        worker = self.path.with_suffix("") / "subagents" / "agent-10000.jsonl"
        subagent = Subagent(self.session, "10000")
        subagent.prompt("Check the parser.")
        subagent.save(worker)
        os.utime(worker, (self.now - 3, self.now - 3))
        neighbor = f"{SID[:-1]}2"
        other = self.path.with_name(f"{neighbor}.jsonl")
        other.write_text(self.path.read_text().replace(SID, neighbor))
        os.utime(other, (self.now, self.now))
        app, lines, footer, focused = self._footer_with_reading(SID, reading)
        app.monotonic = lambda: 100.0

        def level(port: int) -> str | None:
            (session,) = [
                row for row in self.get(port, "/api/data")["sessions"] if row["sid"] == SID
            ]
            return cast("str | None", session.get("stored_progress"))

        with self.serving(app) as port:
            self.get(port, focused)
            self.assertEqual("medium", level(port))
            self.assertEqual("medium", self._level(footer))
            archive = self.path.parent.with_name("-work-archive")
            archive.mkdir()
            duplicate = archive / self.path.name
            duplicate.write_bytes(self.path.read_bytes())
            os.utime(duplicate, (1, 1))
            lines.touch(self.now)
            self.assertIsNone(self._level(footer))
            with mock.patch.object(app, "collect", wraps=app.collect) as collect:
                self.assertEqual([None] * 4, [level(port) for _ in range(4)])
                collect.assert_called_once()
            (view,) = self.get(port, focused)["sources"]["work"]["drift_views"]
            self.assertIsNone(view["pill"])

    def test_a_persistent_scan_error_withholds_the_board_level_until_recovery(self) -> None:
        app, lines, footer, focused = self._departure_footer([])
        app.monotonic = lambda: 100.0
        archive = self.path.parent.with_name("-work-archive")
        archive.mkdir()
        scan = os.listdir

        def unavailable(path: Any = None) -> Any:
            if path == str(archive):
                raise OSError(errno.EIO, "directory read failed")
            return scan(path)

        with (
            mock.patch.object(row_progress._NameWatch, "start", return_value=None),
            self.serving(app) as port,
        ):
            app.warm_row_progress = None
            self.get(port, focused)
            self.assertEqual("medium", self.poll(port))
            with (
                mock.patch.object(os, "listdir", side_effect=unavailable),
                mock.patch.object(app, "collect", wraps=app.collect) as collect,
            ):
                lines.touch(self.now)
                self.assertIsNone(self._level(footer))
                self.assertEqual([None] * 4, [self.poll(port) for _ in range(4)])
                collect.assert_called_once()
                self.assertIsNone(
                    self.get(port, "/api/data?all=1")["sessions"][0]["stored_progress"]
                )
            lines.touch(self.now)
            self.assertEqual("medium", self._level(footer))
            self.assertEqual("medium", self.poll(port))
            self.assertEqual(
                "medium", self.get(port, "/api/data?all=1")["sessions"][0]["stored_progress"]
            )

    def test_repeated_touches_leave_the_withheld_show_all_snapshot_in_place(self) -> None:
        app, lines, footer, focused = self._departure_footer()
        app.monotonic = lambda: 100.0
        with (
            self.serving(app) as port,
            mock.patch.object(app, "collect", wraps=app.collect) as collect,
        ):
            app.warm_row_progress = None
            self.get(port, focused)
            self.assertEqual("medium", self.poll(port))
            self.assertEqual(
                "medium", self.get(port, "/api/data?all=1")["sessions"][0]["stored_progress"]
            )
            collect.reset_mock()
            self._archive_collision(self.path.parent.with_name("-work-archive"))
            generation = app.snapshot.generation()
            lines.touch(self.now)
            self.assertIsNone(self._level(footer))
            self.assertEqual(generation + 1, app.snapshot.generation())
            for _ in range(2):
                lines.touch(self.now)
                self.assertIsNone(
                    self.get(port, "/api/data?all=1")["sessions"][0]["stored_progress"]
                )
            collect.assert_called_once()
            self.assertEqual(generation + 1, app.snapshot.generation())

    def test_a_repeated_touch_does_not_discard_a_clean_collection_in_flight(self) -> None:
        app, lines, footer, focused = self._departure_footer()
        app.monotonic = lambda: 100.0
        collect = app.collect

        def collect_then_touch(*, show_all: bool) -> aggregate.Collection:
            collection = collect(show_all=show_all)
            lines.touch(self.now)
            return collection

        with self.serving(app) as port:
            app.warm_row_progress = None
            self.get(port, focused)
            self.assertEqual("medium", self.poll(port))
            self._archive_collision(self.path.parent.with_name("-work-archive"))
            lines.touch(self.now)
            self.assertIsNone(self._level(footer))
            with mock.patch.object(app, "collect", side_effect=collect_then_touch) as collected:
                self.assertIsNone(self.poll(port))
                self.assertIsNone(self.poll(port))
                collected.assert_called_once()

    def test_an_archived_transcript_in_an_existing_project_clears_the_idle_level(self) -> None:
        self._archived_collision_clears_idle_level(new_project=False)

    def test_an_archived_transcript_in_a_new_project_clears_the_idle_level(self) -> None:
        self._archived_collision_clears_idle_level(new_project=True)

    @unittest.skipUnless(os.name == "posix", "creating a directory symlink requires POSIX")
    def test_a_relocated_claude_store_keeps_checking_its_idle_level(self) -> None:
        projects = self.path.parent.parent
        relocated = projects.with_name("relocated-projects")
        projects.rename(relocated)
        projects.symlink_to(relocated.name, target_is_directory=True)
        self._archived_collision_clears_idle_level(new_project=False)

    def _archived_collision_clears_idle_level(self, *, new_project: bool) -> None:
        archive = self.path.parent.with_name("-work-archive")
        if not new_project:
            archive.mkdir()
        app, lines, footer, focused = self._departure_footer()
        with self.serving(app) as port:
            app.warm_row_progress = None
            (view,) = self.get(port, focused)["sources"]["work"]["drift_views"]
            self.assertEqual("medium", view["pill"]["level"])
            self.assertEqual("medium", self.poll(port))
            self.assertEqual("medium", json.loads(footer.read_text())["stored_progress"])

            self.now += 16
            lines.touch(self.now)
            refreshed = json.loads(footer.read_text())
            self.assertEqual(("medium", self.now), (refreshed["stored_progress"], refreshed["at"]))

            self._archive_collision(archive)
            self.now += 16
            lines.touch(self.now)
            refreshed = json.loads(footer.read_text())
            self.assertEqual((None, self.now), (refreshed["stored_progress"], refreshed["at"]))
            self.assertIsNone(self.poll(port))
            (view,) = self.get(port, focused)["sources"]["work"]["drift_views"]
            self.assertIsNone(view["pill"])

    def _archive_collision(self, archive: Path) -> None:
        archive.mkdir(exist_ok=True)
        older = archive / f"{SHORT}-older.jsonl"
        older.write_bytes(self.path.read_bytes())
        os.utime(older, (1, 1))

    def _departure_footer(
        self, diagnostics: list[str] | None = None
    ) -> tuple[aggregate.Application, footer_lines.Lines, Path, str]:
        self.save_goal(lines=())
        reading = self.departure()
        os.utime(self.path, (self.now, self.now))
        return self._footer_with_reading(SHORT, reading, diagnostics)

    def _footer_with_reading(
        self, sid: str, reading: dict[str, Any], diagnostics: list[str] | None = None
    ) -> tuple[aggregate.Application, footer_lines.Lines, Path, str]:
        app = self.cold()
        app.harnesses = tuple(
            spec
            for spec in aggregate.default_harnesses(usage_fetch_enabled=False)
            if spec.key == "claude"
        )
        (session,) = [row for row in app.collect(show_all=False)["sessions"] if row["sid"] == sid]
        evidence = support.captured_evidence(app, "claude", sid, reading)
        self.assertIsNotNone(evidence)
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.record_reading(
                self.config,
                app.state,
                "claude",
                sid,
                assessment=cast("Assessment", reading),
                evidence=evidence,
            ),
        )
        focused = (
            f"/api/project-context?project={reading_evidence.project_key(session)}"
            f"&session=claude:{sid}"
        )
        lines = footer_lines.Lines(
            self.config.state_home,
            diagnostic_sink=diagnostics.append if diagnostics is not None else None,
        )
        app.footer_lines = lines
        self.addCleanup(lines.remove_all)
        name = footer_lines.line_name("claude", session["resume_id"])
        return app, lines, Path(lines.directory) / name, focused

    def _warm_footer(self, diagnostics: list[str] | None = None) -> tuple[footer_lines.Lines, Path]:
        app, lines, footer, focused = self._departure_footer(diagnostics)
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.get(port, focused)
            self.assertEqual("medium", self.poll(port))
        self.assertEqual("medium", self._level(footer))
        return lines, footer

    @staticmethod
    def _level(footer: Path) -> str | None:
        return cast("str | None", json.loads(footer.read_text())["stored_progress"])

    def test_same_tick_transcript_in_an_existing_project_clears_the_idle_level(self) -> None:
        self._same_tick_collision(new_project=False)

    def test_same_tick_transcript_in_a_new_project_clears_the_idle_level(self) -> None:
        self._same_tick_collision(new_project=True)

    def test_renaming_a_transcript_into_the_prefix_clears_the_idle_level(self) -> None:
        self._rename_with_unchanged_stamp(project=False)

    def test_renaming_a_hidden_project_into_view_clears_the_idle_level(self) -> None:
        self._rename_with_unchanged_stamp(project=True)

    @unittest.skipUnless(sys.platform == "darwin", "uses the macOS directory event queue")
    def test_quiet_watched_projects_reuse_their_names_until_a_rename(self) -> None:
        archive = self.path.parent.with_name("archive")
        archive.mkdir()
        archived = archive / "archived.jsonl"
        archived.write_bytes(self.path.read_bytes())
        os.utime(archived, (1, 1))
        lines, footer = self._warm_footer()
        with mock.patch.object(os, "listdir", wraps=os.listdir) as scanned:
            lines.touch(self.now + 16)
        scanned.assert_not_called()
        self.assertEqual("medium", self._level(footer))

        archived.rename(archive / f"{SHORT}-older.jsonl")
        lines.touch(self.now + 17)
        self.assertIsNone(self._level(footer))

    @unittest.skipUnless(sys.platform == "darwin", "uses the macOS directory event queue")
    def test_a_linked_archive_leaves_ordinary_projects_watched_until_a_target_rename(self) -> None:
        lines, footer = self._warm_footer()
        projects = self.path.parent.parent
        linked = projects / "-archived-project-37"
        relocated = projects.with_name("relocated-project")
        for index in range(120):
            project = projects / f"-archived-project-{index}"
            archive = relocated if project == linked else project
            archive.mkdir()
            for item in range(80):
                stem = 0x80000000 + 80 * index + item
                archived = archive / f"{stem:08x}-0000-4000-b000-000000000000.jsonl"
                archived.touch()
        linked.symlink_to(relocated, target_is_directory=True)
        lines.touch(self.now)

        with mock.patch.object(os, "listdir", wraps=os.listdir) as scanned:
            lines.touch(self.now + 16)
        self.assertEqual(1, scanned.call_count)
        scanned.assert_called_with(str(linked))
        self.assertEqual("medium", self._level(footer))

        archived = linked / "80000b90-0000-4000-b000-000000000000.jsonl"
        archived.rename(linked / f"{SHORT}-older.jsonl")
        lines.touch(self.now + 17)
        self.assertIsNone(self._level(footer))

    def test_a_claude_projects_override_with_a_trailing_slash_keeps_the_idle_level(self) -> None:
        projects = self.path.parent.parent
        roots = dict(self.config.store_roots)
        roots["claude.projects"] = (f"{projects}/",)
        self.config = dataclasses.replace(self.config, store_roots=roots)
        lines, footer = self._warm_footer()
        lines.touch(self.now + 16)
        self.assertEqual("medium", self._level(footer))

    def _rename_with_unchanged_stamp(self, *, project: bool) -> None:
        archive = self.path.parent.with_name(".archive" if project else "archive")
        archive.mkdir()
        if project:
            self._archive_collision(archive)
            source, target = archive, archive.with_name("archive")
        else:
            source, target = archive / "archived.jsonl", archive / f"{SHORT}-older.jsonl"
            source.write_bytes(self.path.read_bytes())
            os.utime(source, (1, 1))
        watched = source.parent
        lines, footer = self._warm_footer()
        sampled = watched.stat()
        real_stat = os.stat

        def coarse_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            return sampled if path == str(watched) else real_stat(path, *args, **kwargs)

        # Both renames have left all directory metadata equal on HFS+.
        with (
            mock.patch.object(os, "stat", side_effect=coarse_stat),
            mock.patch.object(time, "time_ns", return_value=time.time_ns() + 3_000_000_000),
        ):
            lines.touch(self.now + 12)
            self.assertEqual("medium", self._level(footer))
            source.rename(target)
            lines.touch(self.now + 3)
        self.assertIsNone(self._level(footer))

    def _same_tick_collision(self, *, new_project: bool) -> None:
        archive = self.path.parent.with_name("-work-archive")
        if not new_project:
            archive.mkdir()
        lines, footer = self._warm_footer()
        watched = archive.parent if new_project else archive
        (watched / "prime").touch()
        sampled = watched.stat()
        real_stat = os.stat

        def coarse_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            # HFS+ can leave every fingerprint field unchanged within a single tick.
            return sampled if path == str(watched) else real_stat(path, *args, **kwargs)

        with (
            mock.patch.object(os, "stat", side_effect=coarse_stat),
            mock.patch.object(time, "time_ns", return_value=sampled.st_ctime_ns) as clock,
        ):
            lines.touch(self.now)
            self.assertEqual("medium", self._level(footer))
            self._archive_collision(archive)
            clock.return_value += 3_000_000_000
            lines.touch(self.now + 16)
        self.assertIsNone(self._level(footer))

    @unittest.skipUnless(os.name == "posix", "creating a directory symlink requires POSIX")
    def test_an_unrelated_symlink_loop_leaves_the_idle_level_intact(self) -> None:
        diagnostics: list[str] = []
        lines, footer = self._warm_footer(diagnostics)
        loop = self.path.parent.with_name("loop")
        loop.symlink_to(loop.name, target_is_directory=True)
        lines.touch(self.now + 16)
        self.assertEqual("medium", self._level(footer))
        self.assertEqual([], diagnostics)

    @unittest.skipUnless(os.name == "posix", "a mode-000 directory requires POSIX")
    def test_an_unrelated_unreadable_project_leaves_the_idle_level_intact(self) -> None:
        lines, footer = self._warm_footer()
        archive = self.path.parent.with_name("-work-archive")
        archive.mkdir(mode=0)
        self.addCleanup(archive.chmod, 0o700)
        if os.access(archive, os.R_OK | os.X_OK):
            self.skipTest("this user can enumerate a mode-000 directory")
        lines.touch(self.now + 16)
        self.assertEqual("medium", self._level(footer))

    @unittest.skipUnless(os.name == "posix", "directory symlinks and modes require POSIX")
    def test_an_inaccessible_project_symlink_is_skipped_until_it_can_hide_a_level(self) -> None:
        diagnostics: list[str] = []
        lines, footer = self._warm_footer(diagnostics)
        projects = self.path.parent.parent
        ancestor = projects.with_name("blocked")
        archive = ancestor / "archive"
        archive.mkdir(parents=True)
        self._archive_collision(archive)
        link = projects / "linked-archive"
        link.symlink_to(archive, target_is_directory=True)
        ancestor.chmod(0)
        self.addCleanup(ancestor.chmod, 0o700)
        if os.access(link, os.R_OK | os.X_OK):
            self.skipTest("this user can traverse a mode-000 directory")
        lines.touch(self.now + 16)
        self.assertEqual("medium", self._level(footer))
        self.assertEqual([], diagnostics)
        ancestor.chmod(0o700)
        lines.touch(self.now + 17)
        self.assertIsNone(self._level(footer))

    @unittest.skipUnless(os.name == "posix", "changing a directory mode requires POSIX")
    def test_idle_root_admission_preserves_a_readable_root_and_its_level(self) -> None:
        lines, footer = self._warm_footer()
        projects = self.path.parent.parent
        projects.chmod(0o755)
        lines.touch(self.now + 16)
        self.assertEqual("medium", self._level(footer))
        self.assertEqual(0o755, stat.S_IMODE(projects.stat().st_mode))

    def test_a_root_change_during_a_touch_withholds_then_restores_the_level(self) -> None:
        lines, footer = self._warm_footer()
        archive = self.path.parent.with_name("-work-archive")
        archive.mkdir()
        scan = row_progress._claude_matches

        def change_root(directory: str, sids: frozenset[str]) -> Any:
            if directory == str(archive):
                archive.with_name("unrelated").mkdir(exist_ok=True)
            return scan(directory, sids)

        with mock.patch.object(row_progress, "_claude_matches", side_effect=change_root):
            lines.touch(self.now + 16)
        self.assertIsNone(self._level(footer))
        lines.touch(self.now + 17)
        self.assertEqual("medium", self._level(footer))

    def test_a_project_change_during_enumeration_withholds_the_level(self) -> None:
        lines, footer = self._warm_footer()
        archive = self.path.parent.with_name("-work-archive")
        archive.mkdir()
        scan = row_progress._claude_matches

        def change_project(directory: str, sids: frozenset[str]) -> Any:
            matches = scan(directory, sids)
            if directory == str(archive):
                self._archive_collision(archive)
            return matches

        with mock.patch.object(row_progress, "_claude_matches", side_effect=change_project):
            lines.touch(self.now + 16)
        self.assertIsNone(self._level(footer))

    def test_a_collision_in_a_previously_settled_project_withholds_that_touch(self) -> None:
        archive = self.path.parent.with_name("archive")
        archive.mkdir()
        lines, footer = self._warm_footer()
        (archive / "prime").touch()
        visited: list[str] = []
        scan = row_progress._claude_matches

        def insert_in_the_earlier_project(directory: str, sids: frozenset[str]) -> Any:
            if len(visited) < 2:
                visited.append(directory)
                if len(visited) == 2:
                    self._archive_collision(Path(visited[0]))
            return scan(directory, sids)

        with (
            mock.patch.object(row_progress._NameWatch, "start", return_value=None),
            mock.patch.object(
                row_progress, "_claude_matches", side_effect=insert_in_the_earlier_project
            ),
        ):
            lines.touch(self.now + 16)
        self.assertEqual(2, len(visited))
        self.assertIsNone(self._level(footer))

    def test_a_rename_in_a_previously_settled_project_withholds_that_touch(self) -> None:
        later = self.path.parent.with_name("zz-archive")
        later.mkdir()
        archived = self.path.with_name("archived.jsonl")
        archived.write_bytes(self.path.read_bytes())
        os.utime(archived, (1, 1))
        lines, footer = self._warm_footer()
        (later / "prime").touch()
        watched = self.path.parent
        sampled = watched.stat()
        real_stat = os.stat
        scan = row_progress._claude_matches
        collision = archived.with_name(f"{SHORT}-older.jsonl")
        visited: list[str] = []

        def coarse_stat(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            if path == str(watched):
                return sampled
            return real_stat(path, *args, **kwargs)

        def rename_while_scanning(directory: str, sids: frozenset[str]) -> Any:
            if len(visited) < 2:
                visited.append(directory)
                if len(visited) == 2:
                    archived.rename(collision)
            return scan(directory, sids)

        with (
            mock.patch.object(os, "stat", side_effect=coarse_stat),
            mock.patch.object(row_progress._NameWatch, "start", return_value=None),
            mock.patch.object(row_progress, "_claude_matches", side_effect=rename_while_scanning),
        ):
            lines.touch(self.now + 16)
        self.assertEqual([str(watched), str(later)], visited)
        self.assertIsNone(self._level(footer))

    def test_a_collision_during_collection_publication_withholds_the_written_level(self) -> None:
        app, _, footer, focused = self._departure_footer()
        app.monotonic = lambda: 100.0
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.get(port, focused)
            self.assertEqual("medium", self.poll(port))
        archive = self.path.parent.with_name("archive")
        validate = app._footer_prefixes.unambiguous

        def insert_then_validate(paths: dict[str, str]) -> set[str]:
            self._archive_collision(archive)
            return validate(paths)

        app.snapshot.clear()
        with (
            mock.patch.object(
                app._footer_prefixes, "unambiguous", side_effect=insert_then_validate
            ),
            mock.patch.object(
                app.state.streams, "publish", wraps=app.state.streams.publish
            ) as wake,
        ):
            _, body = app.collect_json(show_all=False)
        wake.assert_not_called()
        self.assertIsNone(app.snapshot.current((app.config.window_hours, False)))
        self.assertIsNone(self._level(footer))
        self.assertEqual(self.now, json.loads(footer.read_text())["at"])
        self.assertIsNone(json.loads(body)["sessions"][0].get("stored_progress"))
        _, replacement = app.collect_json(show_all=False)
        self.assertIsNone(json.loads(replacement)["sessions"][0].get("stored_progress"))

    def test_a_reader_starting_after_an_idle_withdrawal_does_not_reuse_an_in_flight_level(
        self,
    ) -> None:
        app, lines, footer, focused = self._departure_footer()
        app.monotonic = lambda: 100.0
        before_publish, release, reader_checked = (threading.Event() for _ in range(3))
        publish, fresh = app.snapshot.publish, app._fresh_snapshot

        def pause_first_publish(*args: Any, **kwargs: Any) -> Any:
            if not before_publish.is_set():
                before_publish.set()
                self.assertTrue(release.wait(5))
            return publish(*args, **kwargs)

        def check_memo(key: tuple[float, bool]) -> Any:
            result = fresh(key)
            if before_publish.is_set() and not release.is_set():
                reader_checked.set()
            return result

        with self.serving(app) as port:
            app.warm_row_progress = None
            self.get(port, focused)
            self.assertEqual("medium", self.poll(port))
            app.snapshot.clear()
            with (
                ThreadPoolExecutor(max_workers=2) as readers,
                mock.patch.object(app.snapshot, "publish", side_effect=pause_first_publish),
                mock.patch.object(app, "_fresh_snapshot", side_effect=check_memo),
                mock.patch.object(
                    app.state.streams, "publish", wraps=app.state.streams.publish
                ) as wake,
            ):
                building = readers.submit(self.poll, port)
                try:
                    self.assertTrue(before_publish.wait(5))
                    self._archive_collision(self.path.parent.with_name("-work-archive"))
                    lines.touch(self.now)
                    self.assertIsNone(self._level(footer))
                    later = readers.submit(self.poll, port)
                    self.assertTrue(reader_checked.wait(5))
                finally:
                    release.set()
                self.assertEqual("medium", building.result(timeout=5))
                self.assertIsNone(later.result(timeout=5))
                self.assertIsNone(self.poll(port))
                wake.assert_called_once()

    def test_an_annotation_clear_during_collection_publication_withholds_the_level(self) -> None:
        app, _, footer, focused = self._departure_footer()
        with self.serving(app) as port:
            app.warm_row_progress = None
            self.get(port, focused)
            self.assertEqual("medium", self.poll(port))
        validate = app._footer_prefixes.unambiguous

        def clear_then_validate(paths: dict[str, str]) -> set[str]:
            self.assertEqual(
                annotation_store.OUTCOME_STORED,
                annotation_store.clear(self.config, self.state, "claude", SHORT, now=self.now),
            )
            return validate(paths)

        self.now += 16
        with mock.patch.object(
            app._footer_prefixes, "unambiguous", side_effect=clear_then_validate
        ):
            app.collect_json(show_all=False)
        self.assertIsNone(self._level(footer))

    def test_a_transcript_append_during_the_namespace_scan_withholds_the_level(self) -> None:
        lines, footer = self._warm_footer()
        validate = lines._validate_prefixes
        assert validate is not None

        def append_then_validate() -> set[str]:
            with self.path.open("ab") as transcript:
                transcript.write(self.path.read_bytes().splitlines(keepends=True)[-1])
            return validate()

        with mock.patch.object(lines, "_validate_prefixes", side_effect=append_then_validate):
            lines.touch(self.now + 16)
        self.assertIsNone(self._level(footer))

    def test_a_scan_error_withholds_the_level_until_the_next_good_touch(self) -> None:
        lines, footer = self._warm_footer([])
        archive = self.path.parent.with_name("-work-archive")
        archive.mkdir()
        scan = os.listdir

        def unavailable(path: Any = None) -> Any:
            if path == str(archive):
                raise OSError(errno.EIO, "directory read failed")
            return scan(path)

        with mock.patch.object(os, "listdir", side_effect=unavailable):
            lines.touch(self.now + 16)
        self.assertIsNone(self._level(footer))
        lines.touch(self.now + 17)
        self.assertEqual("medium", self._level(footer))

    def test_an_annotation_clear_during_the_namespace_scan_withholds_the_level(self) -> None:
        lines, footer = self._warm_footer()
        archive = self.path.parent.with_name("-work-archive")
        archive.mkdir()
        scan = row_progress._claude_matches
        cleared = False

        def clear_during_scan(directory: str, sids: frozenset[str]) -> Any:
            nonlocal cleared
            if directory == str(archive) and not cleared:
                self.assertEqual(
                    annotation_store.OUTCOME_STORED,
                    annotation_store.clear(self.config, self.state, "claude", SHORT, now=self.now),
                )
                cleared = True
            return scan(directory, sids)

        with mock.patch.object(row_progress, "_claude_matches", side_effect=clear_during_scan):
            lines.touch(self.now + 16)
        self.assertIsNone(self._level(footer))

    def test_failed_root_admission_withholds_the_level(self) -> None:
        lines, footer = self._warm_footer()
        projects = self.path.parent.parent
        (projects / "prime").touch()
        with mock.patch.object(runtime_io, "admit_harness_root", return_value=False):
            lines.touch(self.now + 16)
        self.assertIsNone(self._level(footer))

    def test_a_prefix_collision_leaves_the_other_sessions_level_intact(self) -> None:
        rows = self.seed_projects(held=2)
        collided, unaffected = (row["sid"] for row in rows)
        app = self.projects_app(rows)
        lines = footer_lines.Lines(self.config.state_home)
        app.footer_lines = lines
        self.addCleanup(lines.remove_all)
        with self.serving(app) as port:
            app.warm_row_progress = None
            for row in rows:
                route = f"/api/project-context?project={row['project']}&session=claude:{row['sid']}"
                (view,) = self.get(port, route)["sources"]["work"]["drift_views"]
                self.assertEqual("medium", view["pill"]["level"])
            app.collect_json(show_all=False)
            older = self.path.with_name(f"{collided}-older.jsonl")
            older.write_bytes(self.path.with_name(f"{collided}-full.jsonl").read_bytes())
            os.utime(older, (1, 1))
            lines.touch(self.now + 16)
            for sid, level in ((collided, None), (unaffected, "medium")):
                path = Path(lines.directory) / footer_lines.line_name("claude", sid)
                self.assertEqual(level, json.loads(path.read_text())["stored_progress"])

    def test_a_clear_during_idle_proof_checks_withdraws_every_footer_level(self) -> None:
        rows = self.seed_projects(held=2)
        app = self.projects_app(rows)
        lines = footer_lines.Lines(self.config.state_home)
        app.footer_lines = lines
        self.addCleanup(lines.remove_all)
        routes = {
            row["sid"]: f"/api/project-context?project={row['project']}&session=claude:{row['sid']}"
            for row in rows
        }

        def read_footers() -> dict[str, tuple[str | None, float]]:
            footers = {}
            for sid in routes:
                name = footer_lines.line_name("claude", sid)
                body = json.loads((Path(lines.directory) / name).read_text())
                footers[sid] = (body["stored_progress"], body["at"])
            return footers

        holds = row_progress.Proof.holds
        checked: list[str] = []

        def clear_during_second_proof(proof: row_progress.Proof, *args: Any) -> bool:
            if len(checked) == 1:
                self.assertEqual(
                    annotation_store.OUTCOME_STORED,
                    annotation_store.clear(
                        self.config, self.state, "claude", checked[0], now=self.now
                    ),
                )
            checked.append(proof.row["sid"])
            return holds(proof, *args)

        with self.serving(app) as port:
            app.warm_row_progress = None
            for route in routes.values():
                (view,) = self.get(port, route)["sources"]["work"]["drift_views"]
                self.assertEqual("medium", view["pill"]["level"])
            self.get(port, "/api/data")
            self.assertEqual(dict.fromkeys(routes, ("medium", self.now)), read_footers())

            self.now += 16
            with mock.patch.object(row_progress.Proof, "holds", clear_during_second_proof):
                lines.touch(self.now)
            self.assertCountEqual(routes, checked)
            self.assertEqual(dict.fromkeys(routes, (None, self.now)), read_footers())

            cleared, retained = checked
            board = self.get(port, "/api/data")
            self.assertEqual(
                {cleared: None, retained: "medium"},
                {row["sid"]: row["stored_progress"] for row in board["sessions"]},
            )
            (view,) = self.get(port, routes[cleared])["sources"]["work"]["drift_views"]
            self.assertIsNone(view["pill"])

    def test_an_expired_proof_clears_only_its_own_footer(self) -> None:
        older, newer = self.seed_projects(held=2)
        for row in (older, newer):
            row["resume_id"] = f"{row['sid']}-full"
        app = self.projects_app([older, newer])
        lines = footer_lines.Lines(self.config.state_home)
        app.footer_lines = lines
        self.addCleanup(lines.remove_all)

        def footer_progress() -> dict[str, str | None]:
            result = {}
            for row in (older, newer):
                name = footer_lines.line_name("claude", row["resume_id"])
                result[row["sid"]] = json.loads((Path(lines.directory) / name).read_text())[
                    "stored_progress"
                ]
            return result

        def board_progress(body: bytes) -> dict[str, str | None]:
            return {row["sid"]: row["stored_progress"] for row in json.loads(body)["sessions"]}

        started = self.now
        with self.serving(app) as port:
            app.warm_row_progress = None
            for row in (older, newer):
                focused = (
                    f"/api/project-context?project={row['project']}&session=claude:{row['sid']}"
                )
                (view,) = self.get(port, focused)["sources"]["work"]["drift_views"]
                self.assertEqual("medium", view["pill"]["level"])
                self.now += 100

            self.now = started + 299
            revision, body = app.collect_json(show_all=False)
            both = {older["sid"]: "medium", newer["sid"]: "medium"}
            self.assertEqual(both, board_progress(body))
            self.assertEqual(both, footer_progress())
            self.assertEqual((revision, body), app.collect_json(show_all=False))

            self.now = started + 300
            lines.touch(self.now)
            touched = footer_progress()
            self.assertLess(1, self.config.collect_memo_sec)
            refreshed_revision, refreshed_body = app.collect_json(show_all=False)
            self.assertNotEqual(revision, refreshed_revision)
            current = board_progress(refreshed_body)
            self.assertEqual({older["sid"]: None, newer["sid"]: "medium"}, current)
            self.assertEqual(current, touched)

            validate = lines._validate_progress
            assert validate is not None
            self.assertTrue(validate(self.now, ("claude", newer["sid"])))
            for owner in (("claude", "ffffffff"), ("codex", newer["sid"])):
                with self.subTest(owner=owner):
                    self.assertFalse(validate(self.now, owner))


class FooterProviderTest(unittest.TestCase):
    def test_a_person_with_no_lease_table_causes_no_context_or_record_read(self) -> None:
        app = cli.build_application(*support.make_runtime(), clock=lambda: NOW)
        source = http_api.FooterMonitorSource(app)
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.object(
                project_context, "collect", side_effect=AssertionError("unexpected context read")
            ),
            mock.patch.object(
                http_api, "_record_page", side_effect=AssertionError("unexpected record read")
            ),
        ):
            self.assertIs(source.state(row("claude", "short"))["on"], False)
            lines = footer_lines.Lines(home, monitor=source)
            lines.update(board([row("claude", "short")]), NOW)
            lines.touch(NOW)
            lines.touch(NOW + 15)
        self.assertIsNone(app.live_leases)

    def test_a_persons_lease_is_looked_up_by_short_row_id_after_the_end_overlay(self) -> None:
        leases = mock.Mock()
        leases.state.return_value = {"on": False, "last_end": {"reason": "ended", "at": NOW}}
        app = SimpleNamespace(live_leases=leases)
        source = http_api.FooterMonitorSource(app)
        session = row("claude", "short-id") | {"resume_id": "short-id-full", "ended_at": NOW}
        self.assertEqual("ended", source.state(session)["last_end"]["reason"])
        leases.state.assert_called_once_with("claude", "short-id", ended=True)


class FooterAssemblyTest(LeaseRoute):
    def test_a_person_sees_a_page_pause_and_shared_store_resume_without_a_collection(self) -> None:
        app = self.app()
        cli.attach_footer_lines(app, app.config)
        lines = app.footer_lines
        assert isinstance(lines, footer_lines.Lines)
        self.addCleanup(lines.remove_all)
        old = json.loads(app.collect_json(show_all=False)[1])
        session = old["sessions"][0]
        identity = session.get("resume_id") or session["sid"]
        old["reading"] = {"off": False}
        lines.update(old, NOW)
        path = Path(lines.directory) / footer_lines.line_name("claude", identity)

        def paused() -> Any:
            return json.loads(path.read_text())["model_calls_paused"]

        with self.serving(app) as port:
            lines.update(old, NOW)
            status, answer = self.call(
                port, "POST", "/api/reading", {"consent": "off", "press": True, "observer_model": 1}
            )
            self.assertEqual(200, status)
            self.assertIs(answer["reading"]["off"], True)
            lines.touch(NOW + 1)
            self.assertIs(paused(), True)
            lines.update(old, NOW + 2)
            self.assertIs(paused(), True)
            other = dataclasses.replace(app.config)
            reading_policy.set_consent(other, True, now=NOW + 3)
            lines.touch(NOW + 3)
            self.assertIs(paused(), False)
            with mock.patch.object(
                reading_policy, "status", return_value={"reason": "store-unavailable", "off": False}
            ):
                lines.touch(NOW + 4)
            self.assertIsNone(paused())


class ApplicationWritesTest(unittest.TestCase):
    """`collect_json` is where a published snapshot is made, so it is where the file is written."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        # Its own runtime: the shared one keeps a published snapshot that would answer first.
        self.app = cli.build_application(*support.make_runtime(), clock=time.time)
        self.collection = board([row("claude", "a", "needs_input"), row("claude", "b")])
        self.lines = footer_lines.Lines(self.home, pid=1)
        patcher = mock.patch.object(self.app, "collect", side_effect=self.fake_collect)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_collect(self, *, show_all: bool, notify: bool = True) -> dict[str, Any]:
        del notify
        return {**self.collection, "show_all": show_all}

    def names(self) -> list[str]:
        directory = os.path.join(self.home, "footer")
        return sorted(os.listdir(directory)) if os.path.isdir(directory) else []

    def test_an_application_with_no_writer_writes_nothing(self) -> None:
        self.app.collect_json(show_all=False)

        self.assertEqual([], self.names())

    def test_the_page_default_snapshot_writes_the_files(self) -> None:
        self.app.footer_lines = self.lines

        self.app.collect_json(show_all=False)

        self.assertEqual(2, len(self.names()))

    def test_the_show_all_snapshot_writes_nothing(self) -> None:
        self.app.footer_lines = self.lines

        self.app.collect_json(show_all=True)

        self.assertEqual([], self.names())

    def test_a_writer_that_raises_does_not_fail_the_request(self) -> None:
        self.app.footer_lines = mock.Mock(update=mock.Mock(side_effect=RuntimeError("bad")))

        _revision, body = self.app.collect_json(show_all=False)

        self.assertIn(b'"sessions"', body)

    def test_diagnose_style_collection_never_writes(self) -> None:
        self.app.footer_lines = self.lines

        self.app.collect(show_all=False)

        self.assertEqual([], self.names())

    def test_the_cli_does_not_attach_a_writer_when_it_only_builds_an_application(self) -> None:
        built = cli.build_application(*support.make_runtime(), clock=lambda: NOW)

        self.assertIsNone(built.footer_lines)
        self.assertIsInstance(built, aggregate.Application)


class _Stub:
    def __init__(self, config: Any, writer: Any) -> None:
        self.config = config
        self.footer_lines = writer
        self.state = SimpleNamespace(
            asks=SimpleNamespace(count=0), streams=SimpleNamespace(count=0)
        )


class CoordinatorRefreshTest(unittest.TestCase):
    """An idle dashboard with no tab collects nothing, so the coordinator keeps the file fresh."""

    def coordinator(self, writer: Any, **changes: Any) -> observation.Observation:
        config = support.make_config(**changes)
        return observation.Observation(
            _Stub(config, writer),  # type: ignore[arg-type]
            clock=lambda: NOW,
            diagnostic_sink=lambda _m: None,
        )

    def test_the_idle_worker_touches_the_writer_every_five_seconds(self) -> None:
        elapsed = 0.0
        wall = NOW
        touches = []

        def touch(now: float) -> None:
            touches.append((elapsed, now))
            if len(touches) == 2:
                coordinator.stop()

        def wait(timeout: float) -> None:
            nonlocal elapsed, wall
            # A wake before the deadline must not pull the footer refresh forward.
            if elapsed == 0.0:
                elapsed += 1.0
                wall += 1.0 - 12.0
            else:
                elapsed += timeout
                wall += timeout
            self.assertLessEqual(elapsed, 22.0, "the idle footer was not refreshed")

        coordinator = self.coordinator(SimpleNamespace(touch=touch))
        coordinator.clock = lambda: wall
        coordinator.monotonic = lambda: elapsed
        with mock.patch.object(coordinator._wake, "wait", side_effect=wait):
            coordinator._run()

        self.assertEqual([(5.0, NOW - 7.0), (10.0, NOW - 2.0)], touches)

    def test_a_writer_that_raises_cannot_stop_the_worker(self) -> None:
        calls = threading.Semaphore(0)

        def boom(_now: float) -> None:
            calls.release()
            raise RuntimeError("bad")

        writer = mock.Mock()
        writer.touch.side_effect = boom
        coordinator = self.coordinator(writer, stream_producer_interval_sec=0.01)
        coordinator.start()
        self.addCleanup(coordinator.stop)

        self.assertTrue(calls.acquire(timeout=30.0))
        self.assertTrue(calls.acquire(timeout=30.0), "the worker died after one failure")

    def test_a_persons_monitor_is_refreshed_even_when_a_probe_skips_collection(self) -> None:
        writer = mock.Mock()
        coordinator = self.coordinator(writer)
        with mock.patch.object(coordinator, "_worth_collecting", return_value=False):
            coordinator._collect("tick")
        writer.touch.assert_called_once_with(NOW)

    def test_a_persons_monitor_is_refreshed_after_collection_outside_its_lock(self) -> None:
        writer = mock.Mock()
        coordinator = self.coordinator(writer)
        coordinator.application.collect_json = mock.Mock(return_value=("r1", b"{}"))  # type: ignore[method-assign]
        coordinator._collect("event")
        writer.touch.assert_called_once_with(NOW)

    def test_no_writer_means_nothing_to_touch(self) -> None:
        coordinator = self.coordinator(None)

        coordinator._touch_footer()


class ServingTest(unittest.TestCase):
    def test_the_serving_path_attaches_a_writer_over_the_state_home(self) -> None:
        config, state = support.make_runtime(state_home="/somewhere/home")
        application = cli.build_application(config, state, clock=lambda: NOW)

        cli.attach_footer_lines(application, config)

        assert isinstance(application.footer_lines, footer_lines.Lines)
        self.assertEqual(
            os.path.join("/somewhere/home", footer_lines.DIRECTORY),
            application.footer_lines.directory,
        )

    def test_a_stopped_dashboard_removes_the_files_it_wrote(self) -> None:
        from compass_runtime import lifecycle, supervise  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as home:
            lines = footer_lines.Lines(home, pid=1)
            lines.update(board([row("claude", "a")]), NOW)
            application = mock.Mock()
            application.footer_lines = lines

            class FakeServer:
                observation = None

                def __init__(self) -> None:
                    self.application = application

                def serve_forever(self) -> None:
                    pass

                def server_close(self) -> None:
                    pass

            with (
                mock.patch.object(lifecycle, "write_state"),
                mock.patch.object(lifecycle, "remove_state"),
                mock.patch.object(lifecycle, "run_producer"),
                mock.patch.object(supervise, "kill_all"),
                mock.patch("compass_runtime.reading_jobs.recover"),
                mock.patch("compass_runtime.summary_jobs.recover"),
            ):
                lifecycle.serve(
                    support.make_config(),
                    FakeServer(),  # type: ignore[arg-type]
                    4553,
                    started=NOW,
                    diagnostic_sink=lambda _m: None,
                )

            self.assertEqual([], os.listdir(os.path.join(home, "footer")))


if __name__ == "__main__":
    unittest.main()
