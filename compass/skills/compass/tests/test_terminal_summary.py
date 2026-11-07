"""The terminal reads the recorded summary, including what it cannot claim."""

from __future__ import annotations

import copy
import io
import json
import signal
import time
import unittest
from typing import Any
from unittest import mock

from compass_runtime import terminal_client, terminal_drift, terminal_summary

from .support import SERVER_PATH
from .test_claude_checks import SHORT, SID


def recorded() -> dict[str, Any]:
    fixture = json.loads(
        (SERVER_PATH.parents[3] / "frontend/src/sample/session.fixture.json").read_text()
    )
    summary: dict[str, Any] = fixture["context"]["sources"]["summary"]
    return summary


class Board:
    port = 4553

    def __init__(self, summary: dict[str, Any]) -> None:
        self.payload = {
            "session": {"harness": "claude", "sid": "s/1", "project": "a b"},
            "summary": summary,
            "summaries": {},
            "citation_labels": {},
        }
        self.posts: list[tuple[str, Any]] = []
        self.answer: tuple[int, Any] = (409, {"reason": "in-flight"})

    def summary(self, _harness: str, _sid: str) -> Any:
        return copy.deepcopy(self.payload)

    def post(self, path: str, body: Any) -> tuple[int, Any]:
        self.posts.append((path, body))
        return self.answer


class APersonReadsASummary(unittest.TestCase):
    def run_command(self, board: Any, **kwargs: Any) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        result = terminal_summary.run(
            named=terminal_client.Session("claude", "s/1", "environment"),
            board=board,
            out=out,
            err=err,
            **kwargs,
        )
        return result, out.getvalue(), err.getvalue()

    def test_a_person_reads_the_write_time_in_their_local_clock_without_a_utc_date(self) -> None:
        local = time.struct_time((2026, 11, 8, 5, 28, 3, 6, 312, 0))
        for state, wording in (("complete", "summarized at"), ("running", "updated")):
            summary = recorded()
            summary["made_at"] = 1794086883.719384
            summary["job"] = {"state": state}
            with mock.patch.object(time, "localtime", return_value=local):
                _, out, _ = self.run_command(Board(summary))
            self.assertIn(f"claude-sonnet-5-5 · {wording} 05:28", out)
            self.assertNotIn("+00:00", out)
            self.assertNotIn("2026-11", out)

    def test_a_person_reads_why_cited_checks_or_files_cannot_open_counted_once(self) -> None:
        for count in (0, 1, 3):
            summary = recorded()
            checks = [f"earlier-check-{n}" for n in range(count)]
            summary["lede"] = {"text": "Opening.", "cites": ["older-message", *checks]}
            summary["blocks"][0]["phases"] = [
                {
                    "title": "Reading",
                    "bullets": [
                        {"text": "Asked for tests.", "kind": "asked", "cites": ["older-message"]},
                        {"text": "Read checks.", "kind": "did", "cites": checks * 2},
                    ],
                }
            ]
            for block in summary["blocks"][1:]:
                block["phases"] = []
            _, out, _ = self.run_command(Board(summary))
            if count == 1:
                self.assertIn(
                    "1 cited entry is an earlier check or file that Full activity does not list, so it cannot be opened from here.",
                    out,
                )
            elif count:
                self.assertIn(
                    "3 cited entries are earlier checks or files that Full activity does not list, so they cannot be opened from here.",
                    out,
                )
            else:
                self.assertNotIn("cannot be opened from here", out)
            self.assertNotIn("no available label", out)

    def test_a_person_reads_the_right_update_reason_and_when_the_record_changed(self) -> None:
        cases = (
            (
                "unchanged",
                2,
                "Some message text remains unsummarized. Update summary continues from where it stopped.",
            ),
            ("appended", 1, "1 new entry since 05:28."),
            ("appended", 2, "2 new entries since 05:28."),
            ("changed_earlier", 0, "A check\u2019s result arrived since 05:28."),
        )
        for kind, count, expected in cases:
            with self.subTest(kind=kind, count=count):
                summary = recorded()
                summary["out_of_date"] = {"kind": kind, "action": "update", "new_entries": count}
                with mock.patch.object(terminal_drift, "clock_text", return_value="05:28"):
                    _, out, _ = self.run_command(Board(summary))
                self.assertIn(expected, out)
                if kind != "unchanged":
                    self.assertNotIn("Some message text remains unsummarized", out)

    def test_a_person_keeps_lowercase_mentions_after_abbreviations_in_the_opening(self) -> None:
        summary = recorded()
        summary["lede"]["text"] = (
            "The person asked for tests. Followed instructions, e.g. the person asked for tests."
        )
        _, out, _ = self.run_command(Board(summary))
        self.assertIn(
            "You asked for tests. Followed instructions, e.g. the person asked for tests.", out
        )
        self.assertNotIn("e.g. You", out)

    def test_a_person_reads_why_the_opening_is_absent_or_still_being_written(self) -> None:
        for reason, state, expected in (
            (
                "stopped",
                "complete",
                "No opening summary: The summary stopped before every part was summarized.",
            ),
            (
                "bytes",
                "complete",
                "No opening summary: The summary reached the largest size it may be saved at, so its newest parts were left out.",
            ),
            (
                "no_valid_reply",
                "complete",
                "No opening summary: The summary stopped (no_valid_reply).",
            ),
            (None, "complete", "No opening summary."),
            ("stopped", "running", "The opening summary is written once every part has been read."),
            (
                "stopped",
                "stopping",
                "The opening summary is written once every part has been read.",
            ),
        ):
            with self.subTest(reason=reason, state=state):
                summary = recorded()
                summary.update(lede=None, lede_reason=reason, job={"state": state})
                _, out, _ = self.run_command(Board(summary))
                self.assertIn(expected, out.splitlines())
                self.assertNotIn("No opening summary. (", out)
                if state in ("running", "stopping"):
                    self.assertNotIn("No opening summary", out)

    def test_a_person_with_an_older_dashboard_hears_how_to_restart_without_a_spend(self) -> None:
        board = terminal_client.LoopbackBoard(4553)
        for in_session in (False, True):
            with (
                self.subTest(in_session=in_session),
                mock.patch.object(
                    terminal_client, "get", return_value=terminal_client.Reply(404, {})
                ),
            ):
                code, out, err = self.run_command(board, in_session=in_session)
            self.assertEqual((1, ""), (code, out))
            self.assertIn("older release than this client", err)
            self.assertIn("Ask `/compass:compass` to stop" if in_session else "Stop it with", err)
            self.assertNotIn("unambiguously", err)

    def test_a_person_in_a_session_gets_the_skill_instruction_for_a_version_mismatch(self) -> None:
        err = io.StringIO()
        with (
            mock.patch.object(
                terminal_client,
                "resolve_session",
                return_value=terminal_client.Session("claude", "s/1", "environment"),
            ),
            mock.patch.object(
                terminal_client,
                "find_dashboard",
                return_value=terminal_client.Dashboard(4553, 1, 0, "old"),
            ),
            mock.patch.object(terminal_client, "release_version", return_value="new"),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stderr", err),
        ):
            code = terminal_client.run_summary(terminal_client.SummaryRequest(), environ={})
        self.assertEqual(1, code)
        self.assertIn("Ask `/compass:compass` to stop the dashboard", err.getvalue())
        self.assertNotIn("Stop it with", err.getvalue())

    def test_a_person_redirecting_an_explicit_session_still_needs_their_typed_command_to_spend(
        self,
    ) -> None:
        board = Board({"exists": False})
        with (
            mock.patch.object(
                terminal_client,
                "ensure_dashboard",
                return_value=terminal_client.Dashboard(4553, 1, 0, "1"),
            ),
            mock.patch.object(
                terminal_client.LoopbackBoard,
                "session",
                return_value={"session": board.payload["session"]},
            ),
            mock.patch.object(terminal_client.LoopbackBoard, "summary", side_effect=board.summary),
            mock.patch.object(terminal_client.LoopbackBoard, "post", side_effect=board.post),
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(
                1,
                terminal_client.run_summary(
                    terminal_client.SummaryRequest("claude:s/1"), environ={}
                ),
            )
        self.assertEqual("summary", board.posts[0][1].get("typed_action"))

    def test_a_person_reads_stored_phases_twice_without_a_start_even_when_stale(self) -> None:
        board = Board(recorded())
        board.payload["summary"]["out_of_date"] = {
            "kind": "appended",
            "action": "update",
            "new_entries": 2,
        }
        for _ in range(2):
            code, out, err = self.run_command(board)
            self.assertEqual((0, ""), (code, err))
            self.assertIn("2 new entries", out)
            self.assertIn("You asked the agent to coordinate Haiku", out)
            self.assertIn("claude-sonnet-5-5", out)
            self.assertIn("Merging PRs 9325 and 9327", out)
            self.assertIn("s%2F1", out)
            self.assertNotIn("The person asked the agent", out)
        self.assertEqual([], board.posts)

    def test_a_person_sees_unknown_freshness_gaps_fragments_and_withheld_words(self) -> None:
        summary = recorded()
        summary["out_of_date"] = {"kind": "unknown", "reason": "source_unavailable"}
        summary["blocks"][0]["gap"] = True
        summary["blocks"][0]["reason"] = "ceiling"
        summary["blocks"][0]["span"] = {"first_offset": 1, "last_offset": 2, "last_total": 3}
        summary["lede"]["text"] = {"withheld": True, "reason": "completion_claim"}
        _, out, _ = self.run_command(Board(summary))
        self.assertIn("cannot tell whether this summary is current", out)
        self.assertIn("Some fragments were not summarized", out)
        self.assertIn("Some parts were not summarized", out)
        self.assertIn("record does not back", out)
        self.assertNotIn("{'withheld'", out)
        self.assertNotIn(summary["blocks"][0]["phases"][0]["title"], out)

    def test_a_person_updates_only_appendable_work_and_never_silently_reruns(self) -> None:
        board = Board(recorded())
        self.assertEqual(0, self.run_command(board, update=True)[0])
        self.assertEqual([], board.posts)
        board.payload["summary"]["out_of_date"] = {
            "kind": "appended",
            "action": "update",
            "new_entries": 2,
        }
        self.run_command(board, update=True)
        self.assertEqual("update", board.posts[-1][1]["action"])
        self.assertEqual("summary update", board.posts[-1][1]["typed_action"])
        board.posts.clear()
        board.payload["summary"]["out_of_date"] = {"kind": "changed", "action": "summarize_again"}
        self.assertEqual(1, self.run_command(board, update=True)[0])
        self.assertEqual([], board.posts)
        self.run_command(board, again=True)
        self.assertEqual("rerun", board.posts[0][1]["action"])
        self.assertEqual("summary again", board.posts[0][1]["typed_action"])

    def test_a_person_interrupting_cancels_only_the_job_they_started(self) -> None:
        board = Board({"exists": False})
        board.answer = (202, {"job": {"id": "mine", "state": "running"}})
        with mock.patch.object(board, "summary", side_effect=[board.payload, KeyboardInterrupt]):
            self.assertEqual(130, self.run_command(board)[0])
        self.assertEqual(
            ("/api/summary/cancel", {"harness": "claude", "sid": "s/1", "expected_job": "mine"}),
            board.posts[-1],
        )
        board.posts.clear()
        board.payload["summary"]["job"] = {"id": "someone-else", "state": "running"}
        with mock.patch.object(board, "summary", side_effect=KeyboardInterrupt):
            self.assertEqual(130, self.run_command(board)[0])
        self.assertEqual([], board.posts)

    def test_a_person_reads_partial_stored_text_immediately_while_someone_else_is_summarizing(
        self,
    ) -> None:
        board = Board(recorded())
        board.payload["summary"]["job"] = {"id": "theirs", "state": "running"}
        with mock.patch.object(board, "summary", wraps=board.summary) as read:
            code, out, _ = self.run_command(board)
        self.assertEqual(0, code)
        self.assertIn("Merging PRs", out)
        self.assertIn("still running", out.splitlines()[1])
        self.assertNotIn("summarized at", out.splitlines()[1])
        self.assertEqual(1, read.call_count)
        self.assertEqual([], board.posts)

    def test_a_person_waits_on_an_injected_clock_and_never_cancels_on_timeout(self) -> None:
        board = Board({"exists": False})
        board.answer = (202, {"job": {"id": "mine", "state": "running"}})
        first = copy.deepcopy(board.payload)
        board.payload["summary"]["job"] = {"id": "mine", "state": "running"}
        after = copy.deepcopy(board.payload)
        board.summary = mock.Mock(side_effect=[first, after])  # type: ignore[method-assign]
        clock = mock.Mock(side_effect=[0.0, 1.0, 21.0])
        code, _, err = self.run_command(board, clock=clock, sleep=lambda _: None)
        self.assertEqual(1, code)
        self.assertIn("still running", err)
        self.assertEqual(1, len(board.posts))

    def test_a_person_resolves_the_full_identity_before_the_focused_read(self) -> None:
        board = Board(recorded())
        board.payload["session"].update(sid=SHORT, resume_id=SID)
        snapshot = {"session": board.payload["session"]}
        with (
            mock.patch.object(
                terminal_client,
                "resolve_session",
                return_value=terminal_client.Session("claude", SID, "environment"),
            ),
            mock.patch.object(
                terminal_client,
                "ensure_dashboard",
                return_value=terminal_client.Dashboard(4553, 1, 0, "1"),
            ),
            mock.patch.object(
                terminal_client.LoopbackBoard, "session", return_value=snapshot
            ) as session,
            mock.patch.object(
                terminal_client.LoopbackBoard, "summary", side_effect=board.summary
            ) as focused,
            mock.patch("sys.stdout", io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertEqual(0, terminal_client.run_summary(terminal_client.SummaryRequest()))
        session.assert_called_once_with("claude", SID)
        focused.assert_called_once_with("claude", SHORT)

    def test_a_person_sees_the_current_notice_once_on_the_job_that_starts(self) -> None:
        board = Board({"exists": False})
        first = copy.deepcopy(board.payload)
        board.payload["summary"] = recorded()
        board.payload["summary"]["job"] = {"id": "mine", "state": "complete"}
        board.answer = (
            202,
            {
                "job": {"id": "mine", "notice": {"destination": "Anthropic"}},
                "disclosure": "The current summary disclosure.",
            },
        )
        with mock.patch.object(board, "summary", side_effect=[first, board.payload]):
            code, out, _ = self.run_command(board, sleep=lambda _: None)
        self.assertEqual(0, code)
        self.assertEqual(1, out.count("The current summary disclosure."))
        self.assertNotIn("disclosure", self.run_command(board)[1])

    def test_a_person_whose_tool_is_terminated_leaves_their_job_running(self) -> None:
        board = Board({"exists": False})
        first = copy.deepcopy(board.payload)
        board.answer = (202, {"job": {"id": "mine", "state": "running"}})
        handlers: list[Any] = []

        def install(_signum: int, handler: Any) -> Any:
            handlers.append(handler)
            return signal.SIG_DFL

        def read(*_args: Any) -> Any:
            if len(board.posts):
                handlers[0](signal.SIGTERM, None)
            return first

        with (
            mock.patch.object(signal, "signal", side_effect=install),
            mock.patch.object(board, "summary", side_effect=read),
        ):
            code, _, err = self.run_command(board, sleep=lambda _: None)
        self.assertEqual(143, code)
        self.assertIn("keeps running", err)
        self.assertEqual(1, len(board.posts))
        self.assertEqual(signal.SIG_DFL, handlers[-1])

    def test_a_person_sees_that_their_rerun_stopped_even_when_an_older_summary_is_stored(
        self,
    ) -> None:
        board = Board(recorded())
        first = copy.deepcopy(board.payload)
        board.answer = (202, {"job": {"id": "mine", "state": "running"}})
        board.payload["summary"]["job"] = {
            "id": "mine",
            "state": "cancelled",
            "reason": "model-calls-paused",
        }
        with mock.patch.object(board, "summary", side_effect=[first, board.payload]):
            code, out, _ = self.run_command(board, again=True, sleep=lambda _: None)
        self.assertEqual(0, code)
        self.assertIn("Summary job: cancelled (model-calls-paused)", out)
        self.assertIn("Merging PRs", out)

    def test_a_person_sees_cut_citations_and_phase_limits_without_the_withheld_title(self) -> None:
        summary = recorded()
        block = summary["blocks"][0]
        phase = block["phases"][0]
        title = phase["title"]
        phase["cut"] = {"title": True, "bullets": 1}
        phase["bullets"][0]["cites_cut"] = 1
        block["cut"] = {"phases": 1, "reply": True}
        _, out, _ = self.run_command(Board(summary))
        self.assertNotIn(title, out)
        self.assertIn("1 more line was cut from this phase.", out)
        self.assertIn("1 more phase was cut from this part.", out)
        self.assertIn("1 more citation was cut", out)
        self.assertIn("reply for this part was cut short", out)

    def test_a_person_can_dispatch_exact_summary_forms_and_reject_conflicts(self) -> None:
        for args in (
            ["--summary"],
            ["--summary", "--update"],
            ["--summary", "--again"],
            ["--summaries", "off"],
        ):
            self.assertTrue(terminal_client.handles(args), args)
        for args in (
            ["--summary", "--update", "--again"],
            ["--update"],
            ["--summaries", "on"],
            ["--summary", "again"],
        ):
            self.assertIsNone(terminal_client.parse_summary_args(args), args)


class APersonTurnsSummariesOff(unittest.TestCase):
    def test_a_person_turns_summaries_off_without_a_session_or_launch_and_hears_a_pause(
        self,
    ) -> None:
        for status, data, expected in (
            (200, {"ok": True, "summaries": {"consent": False}}, "every session"),
            (
                403,
                {"reason": "model-calls-paused"},
                "Model calls are paused; summaries were not changed.",
            ),
        ):
            out, err = io.StringIO(), io.StringIO()
            with (
                mock.patch.object(
                    terminal_client,
                    "ensure_dashboard",
                    return_value=terminal_client.Dashboard(4553, 1, 0, "1"),
                ) as discover,
                mock.patch.object(
                    terminal_client, "post", return_value=terminal_client.Reply(status, data)
                ) as post,
                mock.patch("sys.stdout", out),
                mock.patch("sys.stderr", err),
            ):
                code = terminal_client.run_summaries_off(environ={})
            self.assertEqual(0 if status == 200 else 1, code)
            self.assertIn(expected, out.getvalue() + err.getvalue())
            self.assertFalse(discover.call_args.kwargs["spend"])
            self.assertEqual({"consent": "off"}, post.call_args.args[2])
