"""The dashboard's half of `--footer`: one small file per Claude session."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import threading
import time
import unittest
from itertools import pairwise
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    aggregate,
    cli,
    compass_turns,
    copied_corrections,
    drift_view,
    footer_lines,
    http_api,
    observation,
    project_context,
    terminal_sessions,
)
from compass_runtime import io as runtime_io

from . import support
from .test_claude_checks import SHORT
from .test_live_lease_http import LeaseRoute

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
                "level": None,
                "last_end": None,
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
        self.views: dict[str, dict[str, Any]] = {}
        self.entered: threading.Event | None = None
        self.release: threading.Event | None = None

    def state(self, session: Any) -> dict[str, Any]:
        return self.leases.get(session["sid"], {"on": False})

    def record_stamp(self, session: Any) -> object:
        del session
        return None

    def view(self, collection: Any, session: Any, lease: Any) -> dict[str, Any]:
        del collection, lease
        self.calls.append(session["sid"])
        if self.entered is not None and self.release is not None:
            self.entered.set()
            if not self.release.wait(10):
                raise TimeoutError("test did not release projection")
        return self.views.get(session["sid"], {"pill": {"level": "medium"}})


class MonitorLinesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(mock.patch.object(time, "monotonic", return_value=0.0))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = tmp.name
        self.source = MonitorSource()
        self.lines = footer_lines.Lines(
            self.home, pid=1, monitor=self.source, diagnostic_sink=lambda _m: None
        )
        self.collection = board([row("claude", "short-id") | {"resume_id": "short-id-full"}])
        self.source.leases["short-id"] = {"on": True, "started_at": NOW}

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

    def test_a_person_gets_the_page_pill_under_their_full_resume_id(self) -> None:
        self.publish()
        self.assertEqual((True, "medium"), (self.body()["monitor"], self.body()["level"]))
        self.assertEqual(["short-id"], self.source.calls)

    def test_a_person_keeps_seeing_their_level_while_other_sessions_change_the_board(self) -> None:
        self.collection["sessions"].append(row("claude", "other"))
        clock = [NOW]
        starts: list[float] = []
        original = self.source.view

        def view(collection: Any, session: Any, lease: Any) -> dict[str, Any]:
            starts.append(clock[0])
            return original(collection, session, lease)

        with (
            mock.patch.object(time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(self.source, "view", side_effect=view),
        ):
            self.publish()
            for age in range(2, 61, 2):
                with self.subTest(age=age):
                    clock[0] = NOW + age
                    other = self.collection["sessions"][1]
                    other.update(last_activity=NOW + age, annotation_revision=age)
                    other["state"] = "needs_input" if age % 4 == 0 else "working"
                    self.collection["generated"] = NOW + age
                    self.lines.update(self.collection, NOW + age)
                    self.assertEqual("medium", self.body()["level"])
                    self.assertEqual(int(age % 4 == 0), self.body()["waiting"])
                    self.lines.touch(NOW + age)
                    self.assertEqual("medium", self.body()["level"])
        self.assertGreaterEqual(len(starts), 4)
        self.assertLessEqual(len(starts), 5)
        self.assertTrue(all(b - a >= 15 for a, b in pairwise(starts)))

    def test_a_person_who_keeps_working_still_sees_their_last_level_until_it_is_rechecked(
        self,
    ) -> None:
        clock = [NOW]
        with (
            mock.patch.object(time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(self.source, "record_stamp", side_effect=lambda _row: clock[0]),
        ):
            self.publish()
            self.source.views["short-id"] = {"pill": {"level": "high"}}
            for age in range(1, 16):
                with self.subTest(age=age):
                    clock[0] = NOW + age
                    self.collection["sessions"][0].update(
                        state="working" if age % 2 else "idle",
                        prompt_at=NOW + age,
                        title=f"Working on step {age}",
                    )
                    self.lines.update(self.collection, NOW + age)
                    self.assertEqual("medium", self.body()["level"])
                    self.assertIs(self.body()["monitor"], True)
                    self.assertIsNone(self.body()["last_end"])
                    self.lines.touch(NOW + age)
                    self.assertEqual("medium" if age < 15 else "high", self.body()["level"])
                    self.assertEqual(["short-id"] * (1 if age < 15 else 2), self.source.calls)

    def test_a_person_who_replaces_saved_intent_sees_the_old_level_hidden_until_rechecked(
        self,
    ) -> None:
        self.collection["sessions"][0]["session_goal"] = {"text": "Ship the fix", "at": NOW}
        self.publish()
        self.collection["sessions"][0]["session_goal"] = {"text": "Explain the fix", "at": NOW + 1}
        self.source.views["short-id"] = {"pill": {"level": "low"}}
        self.lines.update(self.collection, NOW + 1)
        self.assertIsNone(self.body()["level"])
        self.lines.touch(NOW + 14)
        self.assertIsNone(self.body()["level"])
        self.assertEqual(["short-id"], self.source.calls)
        self.lines.touch(NOW + 15)
        self.assertEqual("low", self.body()["level"])

    def test_a_person_who_changes_their_goal_sees_the_old_level_hidden_until_reprojected(
        self,
    ) -> None:
        self.collection["sessions"][0].update(annotation_goal="Ship the fix", annotation_revision=1)
        self.publish()
        self.collection["sessions"][0].update(
            annotation_goal="Explain the fix", annotation_revision=2
        )
        self.source.views["short-id"] = {"pill": {"level": "low"}}
        self.lines.update(self.collection, NOW + 1)
        self.assertIs(self.body()["monitor"], True)
        self.assertIsNone(self.body()["level"])
        self.lines.touch(NOW + 14)
        self.assertIsNone(self.body()["level"])
        self.assertEqual(["short-id"], self.source.calls)
        self.lines.touch(NOW + 15)
        self.assertEqual("low", self.body()["level"])

    def test_a_person_keeps_their_level_when_only_their_display_age_changes(self) -> None:
        self.publish()
        self.collection["sessions"][0]["age"] = "a minute ago"
        self.lines.update(self.collection, NOW + 1)
        self.assertEqual("medium", self.body()["level"])

    def test_a_person_keeps_the_old_level_until_rechecked_when_their_own_row_changes(self) -> None:
        self.publish()
        self.collection["sessions"][0]["first_prompt"] = "A new direction"
        self.source.views["short-id"] = {"pill": {"level": "low"}}
        self.lines.update(self.collection, NOW + 1)
        self.assertEqual("medium", self.body()["level"])
        self.lines.touch(NOW + 14)
        self.assertEqual("medium", self.body()["level"])
        self.assertEqual(["short-id"], self.source.calls)
        self.lines.touch(NOW + 15)
        self.assertEqual("low", self.body()["level"])

    def test_a_person_still_gets_a_slow_projection_while_other_sessions_change(self) -> None:
        self.lines.update(self.collection, NOW)
        self.source.entered, self.source.release = threading.Event(), threading.Event()
        worker = threading.Thread(target=self.lines.touch, args=(NOW,))
        worker.start()
        try:
            self.assertTrue(self.source.entered.wait(10))
            self.collection["sessions"].append(row("claude", "other"))
            self.lines.update(self.collection, NOW + 1)
        finally:
            self.source.release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertEqual("medium", self.body()["level"])

    def test_a_person_never_sees_a_slow_projection_from_before_their_monitor_restart(self) -> None:
        self.lines.update(self.collection, NOW)
        self.source.entered, self.source.release = threading.Event(), threading.Event()
        worker = threading.Thread(target=self.lines.touch, args=(NOW,))
        worker.start()
        try:
            self.assertTrue(self.source.entered.wait(10))
            self.source.leases["short-id"] = {"on": True, "started_at": NOW + 1}
            self.lines.touch(NOW + 1)
        finally:
            self.source.release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertIs(self.body()["monitor"], True)
        self.assertIsNone(self.body()["level"])
        self.lines.touch(NOW + 15)
        self.assertEqual("medium", self.body()["level"])

    def test_a_person_with_the_monitor_off_never_publishes_a_saved_level(self) -> None:
        self.source.leases.clear()
        self.collection["sessions"].append(row("agy", "x"))
        self.collection["harnesses"].append(harness("agy", "Antigravity", reports=False))
        self.publish()
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["level"])
        self.assertEqual(["Antigravity"], self.body()["blind"])
        self.assertEqual([], self.source.calls)

    def test_a_person_whose_monitor_ends_while_idle_loses_the_level_but_keeps_waits(self) -> None:
        self.publish()
        self.end()
        self.lines.touch(NOW + 1)
        self.assertEqual(
            (False, None, {"reason": "ended", "at": NOW + 1}),
            tuple(self.body()[key] for key in ("monitor", "level", "last_end")),
        )
        self.collection["sessions"].append(row("codex", "waiter", "needs_input"))
        self.lines.update(self.collection, NOW + 20)
        self.assertEqual(1, self.body()["waiting"])
        self.lines.touch(NOW + 400)
        self.assertEqual(NOW + 400, self.body()["at"])
        self.assertIsNone(self.body()["level"])

    def test_a_person_who_restarts_the_monitor_can_see_a_level_again(self) -> None:
        self.publish()
        self.end()
        self.lines.touch(NOW + 1)
        self.source.leases["short-id"] = {"on": True, "started_at": NOW + 20}
        self.lines.touch(NOW + 20)
        self.assertEqual(
            (True, "medium", None), tuple(self.body()[k] for k in ("monitor", "level", "last_end"))
        )

    def test_a_departed_persons_monitored_row_gets_one_terminal_write(self) -> None:
        self.publish()
        self.end()
        self.lines.update(board([]), NOW + 1)
        terminal = self.body()
        self.assertIs(terminal["monitor"], False)
        self.assertIsNone(terminal["level"])
        self.lines.touch(NOW + 100)
        self.assertEqual(terminal, self.body())

    def test_a_persons_failed_end_write_is_retried_without_restamping_the_old_level(self) -> None:
        self.publish()
        self.end()
        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError("full")):
            self.lines.update(board([]), NOW + 1)
        self.lines.touch(NOW + 2)
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["level"])
        self.assertEqual(NOW + 2, self.body()["at"])
        self.lines.touch(NOW + 40)
        self.assertEqual(NOW + 2, self.body()["at"])

    def test_a_person_never_sees_a_slow_projection_resurrect_a_later_end(self) -> None:
        self.lines.update(self.collection, NOW)
        self.source.entered, self.source.release = threading.Event(), threading.Event()
        worker = threading.Thread(target=self.lines.touch, args=(NOW,))
        worker.start()
        try:
            self.assertTrue(self.source.entered.wait(10))
            self.end()
            self.lines.touch(NOW + 1)
            self.assertIs(self.body()["monitor"], False)
        finally:
            self.source.release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["level"])

    def test_a_persons_projection_runs_once_per_refresh_only_for_monitored_sessions(self) -> None:
        self.collection["sessions"].extend([row("claude", "second"), row("claude", "off")])
        self.source.leases["second"] = {"on": True, "started_at": NOW}
        self.publish()
        for age in (1, 5, 14):
            self.lines.update(self.collection, NOW + age)
            self.lines.touch(NOW + age)
        self.assertCountEqual(["short-id", "second"], self.source.calls)
        self.lines.touch(NOW + 15)
        self.assertCountEqual(["short-id", "second"] * 2, self.source.calls)

    def test_a_person_whose_neighbour_lookup_fails_still_gets_their_own_level_on_the_next_refresh(
        self,
    ) -> None:
        for failure_call in (1, 3):
            with self.subTest(neighbour_lookup=failure_call):
                self.lines = footer_lines.Lines(
                    self.home, monitor=self.source, diagnostic_sink=lambda _m: None
                )
                self.collection["sessions"] = [
                    self.collection["sessions"][0],
                    row("claude", "second"),
                    row("claude", "third"),
                ]
                for sid in ("second", "third"):
                    self.source.leases[sid] = {"on": True, "started_at": NOW}
                self.lines.update(self.collection, NOW)
                self.assertIsNone(self.body()["level"])
                neighbour_calls = 0

                def state(session: Any, *, fail_at: int = failure_call) -> dict[str, Any]:
                    nonlocal neighbour_calls
                    if session["sid"] == "second":
                        neighbour_calls += 1
                        if neighbour_calls == fail_at:
                            raise RuntimeError("neighbour lookup failed")
                    return MonitorSource.state(self.source, session)

                with mock.patch.object(self.source, "state", side_effect=state):
                    self.lines.touch(NOW)
                    self.assertEqual("medium", self.body()["level"])
                    self.lines.touch(NOW + 15)
                self.assertEqual("medium", self.body()["level"])
                self.assertEqual("medium", self.body("third")["level"])

    def test_a_person_whose_neighbour_was_slow_is_not_projected_twice_within_one_refresh(
        self,
    ) -> None:
        self.collection["sessions"].append(row("claude", "second"))
        self.source.leases["second"] = {"on": True, "started_at": NOW}
        self.lines.update(self.collection, NOW)
        clock = [100.0]
        starts: dict[str, list[float]] = {"short-id": [], "second": []}
        original = self.source.view

        def view(collection: Any, session: Any, lease: Any) -> dict[str, Any]:
            sid = session["sid"]
            starts[sid].append(clock[0])
            if sid == "short-id" and len(starts[sid]) == 1:
                clock[0] += 30
                self.lines.touch(NOW + 30)
            return original(collection, session, lease)

        with (
            mock.patch.object(time, "monotonic", side_effect=lambda: clock[0]),
            mock.patch.object(self.source, "view", side_effect=view),
        ):
            self.lines.touch(NOW)
            self.assertEqual("medium", self.body("second")["level"])
            self.assertEqual([130.0], starts["second"])
            clock[0] = 135.0
            self.lines.touch(NOW + 35)
            self.assertEqual([130.0], starts["second"])
            clock[0] = 145.0
            self.lines.touch(NOW + 45)
        self.assertEqual([130.0, 145.0], starts["second"])
        self.assertEqual("medium", self.body("second")["level"])

    def test_a_person_whose_monitor_ends_while_another_projects_costs_no_record_read(self) -> None:
        source = self.source

        class EndsOther(MonitorSource):
            def view(self, collection: Any, session: Any, lease: Any) -> dict[str, Any]:
                if session["sid"] == "short-id":
                    self.leases["second"] = {"on": False}
                return super().view(collection, session, lease)

        ending = EndsOther()
        ending.leases = {**source.leases, "second": {"on": True, "started_at": NOW}}
        self.lines = footer_lines.Lines(self.home, monitor=ending)
        self.collection["sessions"].append(row("claude", "second"))
        self.publish()
        self.assertEqual(["short-id"], ending.calls)
        self.assertIs(self.body("second")["monitor"], False)

    def test_a_persons_changed_annotation_revision_hides_the_cached_level_until_rechecked(
        self,
    ) -> None:
        self.publish()
        self.collection["sessions"][0]["annotation_revision"] = 2
        self.lines.update(self.collection, NOW + 1)
        self.assertIsNone(self.body()["level"])
        self.lines.touch(NOW + 15)
        self.assertEqual("medium", self.body()["level"])

    def test_a_person_never_gets_a_guessed_monitor_for_duplicate_session_rows(self) -> None:
        self.collection["sessions"].append(dict(self.collection["sessions"][0]))
        self.publish()
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["level"])
        self.assertEqual([], self.source.calls)

    def test_a_persons_departure_retries_an_end_that_failed_while_the_row_was_present(self) -> None:
        self.publish()
        self.end()
        with mock.patch.object(runtime_io, "atomic_write_owner_only", side_effect=OSError("full")):
            self.lines.touch(NOW + 1)
        self.lines.update(board([]), NOW + 2)
        self.assertIs(self.body()["monitor"], False)
        self.assertIsNone(self.body()["level"])

    def test_a_persons_return_to_the_board_does_not_multiply_projection_reads(self) -> None:
        self.publish()
        self.lines.update(board([]), NOW + 1)
        self.lines.update(self.collection, NOW + 2)
        self.lines.touch(NOW + 2)
        self.assertEqual(["short-id"], self.source.calls)

    def test_a_person_never_sees_a_slow_projection_for_replaced_intent(self) -> None:
        self.lines.update(self.collection, NOW)
        self.source.entered, self.source.release = threading.Event(), threading.Event()
        worker = threading.Thread(target=self.lines.touch, args=(NOW,))
        worker.start()
        try:
            self.assertTrue(self.source.entered.wait(10))
            self.collection["sessions"][0]["annotation_revision"] = 2
            self.lines.update(self.collection, NOW + 1)
        finally:
            self.source.release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(self.body()["level"])

    def test_a_persons_projection_uses_the_pages_parity_fixture_pill(self) -> None:
        path = support.SERVER_PATH.parents[3] / "frontend/test/fixtures/drift-parity.json"
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        for case in cases:
            session = case["session"]
            if session["harness"] != "claude":
                continue
            with self.subTest(case=case["name"]), tempfile.TemporaryDirectory() as home:
                source = MonitorSource()
                source.leases[session["sid"]] = {"on": True, "started_at": NOW}
                record = case.get("record")
                source.views[session["sid"]] = drift_view.derive(
                    session, case["payload"], case["context"], record["entries"] if record else None
                )
                lines = footer_lines.Lines(home, monitor=source)
                lines.update(board([session]), NOW)
                lines.touch(NOW)
                name = session.get("resume_id", session["sid"])
                with open(
                    os.path.join(home, "footer", footer_lines.line_name("claude", name)),
                    encoding="utf-8",
                ) as handle:
                    body = json.load(handle)
                pill = case["expected"]["pill"]
                self.assertEqual(pill["level"] if pill else None, body["level"])


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

    def test_a_person_gets_the_same_page_pill_without_recursive_collection(self) -> None:
        path = support.SERVER_PATH.parents[3] / "frontend/test/fixtures/drift-parity.json"
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        app = cli.build_application(*support.make_runtime(), clock=lambda: NOW)
        source = http_api.FooterMonitorSource(app)
        for case in cases:
            session = case["session"]
            if session["harness"] != "claude":
                continue
            with (
                self.subTest(case=case["name"]),
                mock.patch.object(
                    app, "collect_json", side_effect=AssertionError("recursive collection")
                ),
                mock.patch.object(
                    http_api, "_lease_row", side_effect=AssertionError("recursive row")
                ),
                mock.patch.object(
                    project_context, "collect", return_value=case["context"]
                ) as collect,
                mock.patch.object(
                    compass_turns, "mark", side_effect=lambda _c, _s, context, _r: context
                ),
                mock.patch.object(
                    copied_corrections, "mark", side_effect=lambda context, _r: context
                ),
                mock.patch.object(
                    http_api, "_with_message_ordinals", side_effect=lambda _a, context, _f: context
                ),
                mock.patch.object(
                    http_api, "_with_levels", side_effect=lambda _a, context, _r, _f, _p: context
                ),
                mock.patch.object(
                    http_api,
                    "_record_page",
                    return_value={"state": "ok", **case["record"]}
                    if case.get("record")
                    else {"state": "unavailable", "entries": []},
                ),
            ):
                lease = (
                    case["context"]
                    .get("sources", {})
                    .get("work", {})
                    .get("live_monitor", {"on": False})
                )
                result = source.view(case["payload"] | {"sessions": [session]}, session, lease)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(case["expected"]["pill"], result["pill"])
                self.assertIs(collect.call_args.kwargs["refresh"], False)
                self.assertIs(collect.call_args.kwargs["model_consent"], False)


class FooterAssemblyTest(LeaseRoute):
    def test_a_person_whose_record_changes_keeps_the_old_level_until_reprojected(
        self,
    ) -> None:
        app = self.app()
        collected = json.loads(app.collect_json(show_all=False)[1])
        session = next(r for r in collected["sessions"] if r["sid"] == SHORT)
        source = http_api.FooterMonitorSource(app)
        with (
            tempfile.TemporaryDirectory() as home,
            mock.patch.object(source, "state", return_value={"on": True, "started_at": NOW}),
            mock.patch.object(source, "view", return_value={"pill": {"level": "medium"}}) as view,
            mock.patch.object(time, "monotonic", return_value=0.0),
        ):
            lines = footer_lines.Lines(home, monitor=source)
            name = session.get("resume_id") or session["sid"]
            path = os.path.join(home, "footer", footer_lines.line_name("claude", name))

            def level() -> Any:
                with open(path, encoding="utf-8") as handle:
                    return json.load(handle)["level"]

            lines.update(collected, NOW)
            lines.touch(NOW)
            self.assertEqual("medium", level())
            self.session.bash("pytest", "1 failed", is_error=True)
            self.session.save(self.path)
            lines.touch(NOW + 1)
            self.assertEqual("medium", level())
            self.assertEqual(1, view.call_count)
            view.return_value = {"pill": {"level": "high"}}
            lines.touch(NOW + 15)
            self.assertEqual("high", level())
            self.assertEqual(2, view.call_count)

    def test_a_person_sees_a_failed_check_from_the_record_as_the_page_does(self) -> None:
        self.session.write(self.session.cwd + "/src/a.py")
        self.session.bash("pytest", "1 failed, 4 passed", is_error=True)
        self.session.save(self.path)
        app = self.app()
        collected = json.loads(app.collect_json(show_all=False)[1])
        session = next(r for r in collected["sessions"] if r["sid"] == SHORT)
        source = http_api.FooterMonitorSource(app)
        with (
            mock.patch.object(
                app, "collect_json", side_effect=AssertionError("recursive collection")
            ),
            mock.patch.object(http_api, "_lease_row", side_effect=AssertionError("recursive row")),
        ):
            projected = source.view(collected, session, {"on": True})
        assert projected is not None
        self.assertEqual("high", projected["pill"]["level"])
        self.assertEqual("live", projected["pill"]["source"])


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

    def test_a_persons_page_pill_is_projected_after_collection_releases_its_lock(self) -> None:
        source = MonitorSource()
        source.leases["a"] = {"on": True, "started_at": NOW}
        lines = footer_lines.Lines(self.home, monitor=source)
        self.app.footer_lines = lines
        self.app.collect_json(show_all=False)
        path = os.path.join(self.home, "footer", footer_lines.line_name("claude", "a"))
        with open(path, encoding="utf-8") as handle:
            self.assertIsNone(json.load(handle)["level"])
        self.assertEqual([], source.calls)
        original = source.view

        def view(collection: Any, session: Any, lease: Any) -> dict[str, Any]:
            for lock in (self.app.state.collect_memo_lock, lines._lock):
                self.assertTrue(lock.acquire(blocking=False), "projection holds a publication lock")
                lock.release()
            return original(collection, session, lease)

        with mock.patch.object(source, "view", side_effect=view):
            coordinator = observation.Observation(self.app, clock=lambda: NOW)
            coordinator._touch_footer()
        with open(path, encoding="utf-8") as handle:
            self.assertEqual("medium", json.load(handle)["level"])

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

    def coordinator(self, writer: Any) -> observation.Observation:
        config = support.make_config()
        return observation.Observation(
            _Stub(config, writer),  # type: ignore[arg-type]
            clock=lambda: NOW,
            diagnostic_sink=lambda _m: None,
        )

    def test_the_worker_touches_the_writer_when_nothing_is_due(self) -> None:
        touched = threading.Event()
        writer = mock.Mock()
        writer.touch.side_effect = lambda _now: touched.set()
        coordinator = self.coordinator(writer)
        with mock.patch.object(coordinator, "_sleep_for", return_value=0.01):
            coordinator.start()
            self.addCleanup(coordinator.stop)

            self.assertTrue(touched.wait(30.0), "the idle worker never touched the footer lines")

    def test_a_writer_that_raises_cannot_stop_the_worker(self) -> None:
        calls = threading.Semaphore(0)

        def boom(_now: float) -> None:
            calls.release()
            raise RuntimeError("bad")

        writer = mock.Mock()
        writer.touch.side_effect = boom
        coordinator = self.coordinator(writer)
        with mock.patch.object(coordinator, "_sleep_for", return_value=0.01):
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
