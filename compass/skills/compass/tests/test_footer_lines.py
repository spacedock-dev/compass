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
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import aggregate, cli, footer_lines, observation, terminal_sessions
from compass_runtime import io as runtime_io

from . import support

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

    def test_the_shape_is_versioned_and_carries_the_monitor_keys_the_later_issue_fills(
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
                "monitor": None,
                "level": None,
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
