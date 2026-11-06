"""`--drift`: a person reads a session against their goal from a shell, and spends only when asked.

The board here is a fake with the dashboard's routes and nothing else: it holds one `/api/data`
payload and one focused context, counts every request, and plays a reading job forward as the
fake clock passes. The drift view it serves is written to the shape layer B publishes on
`sources.work.drift_views`; `terminal_drift.adapt` is the one place that shape is read.
"""

from __future__ import annotations

import copy
import io
import json
import os
import re
import shlex
import signal
import time
import unittest
from typing import TYPE_CHECKING, Any

from compass_runtime import terminal_client, terminal_drift

if TYPE_CHECKING:
    from collections.abc import Mapping

from .support import SERVER_PATH

RECORDED_CONTEXT = (
    SERVER_PATH.parents[3]
    / "frontend"
    / "test"
    / "fixtures"
    / "client-contract"
    / "context-focused-drift.json"
)

ROOT = SERVER_PATH.parents[3]
ALLOWANCE = ROOT / "frontend" / "test" / "fixtures" / "prompt-allowance.json"

NOW = 1_800_000_000.0
KEY = "claude:abc"
PORT = 4553
PAGE = f"http://127.0.0.1:{PORT}/#n=session:compass:claude:abc"
CAPACITY = {
    "kind": "capacity-preview",
    "policy": "analyze-context-v1",
    "maximum_prompt_bytes": 524288,
    "window_tokens": 200000,
    "window_source": "documented",
    "generation_reserve_tokens": 32000,
    "cli_reserve_tokens": 8000,
    "estimated_system_tokens": 4000,
    "estimate_method": "utf8-bytes-div-3",
    "fit_verified": False,
    "policy_verified": False,
    "configuration_reason": "",
    "reason": "estimated",
    "can_lower_prompt_setting": False,
}
ROUTE = {
    "provider": "claude",
    "model": "claude-sonnet-5-5",
    "note": "",
    "capacity": CAPACITY,
}
ASSESSMENT = {"read_at": NOW - 600, "revision_read": 3, "criteria": {}}


def a_row(**fields: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "harness": "claude",
        "sid": "abc",
        "project": "compass",
        "title": "Fix the parser",
        "annotation_goal": "Make the parser accept tabs",
        "annotation_goal_saved_at": NOW - 3600,
        "annotation_revision": 3,
        "annotation_line_1": "The tests pass",
        "annotation_line_1_source": "typed",
        "annotation_line_2": "",
        "annotation_assessment": None,
        "annotation_reading_withheld": "",
        "annotation_reading_withheld_at": None,
        "reading_eligibility": {"ok": True, "reason": None, "until": None},
    }
    row.update(fields)
    return row


def a_payload(row: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "annotate": True,
        "generated": NOW,
        "sessions": [a_row() if row is None else row],
        "reading_routes": {"claude": copy.deepcopy(ROUTE)},
        "reading": {"consent": True, "reason": None},
        "reading_check": "passed",
        "reading_jobs": {},
    }
    payload.update(fields)
    return payload


def a_view(**fields: Any) -> dict[str, Any]:
    """A `drift_views` row, as the DRC-5102 analysis specifies it."""
    view: dict[str, Any] = {
        "harness": "claude",
        "sid": "abc",
        "revision": 3,
        "live_on": False,
        "unsettled": False,
        "drafted": False,
        "malformed": "",
        "pill": {"level": "medium", "source": "analysis", "so_far": False},
        "analysis": {"level": "medium", "reasons": ["departure"], "withheld": False},
        "estimate": None,
        "lines": [
            {
                "key": "goal",
                "state": "departs",
                "result": "departure",
                "why": "",
                "rests_on": "tool",
                "cites": ["fact:a", "fact:b"],
                "numbers": ["41", "41.2"],
                "clause": "Make the parser accept tabs",
                "detail": "The agent rewrote the lexer to reject tabs.",
                "partial": False,
            },
            {
                "key": "line_1",
                "state": "consistent",
                "result": "consistent",
                "why": "",
                "rests_on": "tool",
                "cites": ["fact:c"],
                "numbers": ["44"],
                "clause": "The tests pass",
                "detail": "",
                "partial": False,
            },
        ],
        "departures": ["goal"],
        "priors": [],
        "stale": None,
    }
    view.update(fields)
    return view


class FakeBoard:
    """The dashboard's drift routes, with a reading job that finishes after `job_polls` polls."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        view: dict[str, Any] | None = None,
        *,
        reply: tuple[int, Any] | None = None,
        job_polls: int = 2,
        finished_view: dict[str, Any] | None = None,
        correction: tuple[int, Any] | None = None,
        cancel: tuple[int, Any] = (202, {"ok": True, "cancelling": True}),
        publishes_views: bool = True,
    ) -> None:
        self.payload = a_payload() if payload is None else payload
        self.view = view
        self.reply = reply
        self.job_polls = job_polls
        self.finished_view = a_view() if finished_view is None else finished_view
        self.correction = correction or (
            200,
            {"ok": True, "parts": ["Steer back: keep tabs.", {"entry": "fact:a"}, "\nThanks."]},
        )
        self.cancel = cancel
        self.publishes_views = publishes_views
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[str] = []
        self.model_calls = 0
        self._polls_left: int | None = None

    def data(self) -> Any:
        self.gets.append("/api/data")
        jobs = self.payload.get("reading_jobs") or {}
        if KEY in jobs and self._polls_left is not None:
            if self._polls_left <= 0:
                self._finish()
            else:
                self._polls_left -= 1
        return copy.deepcopy(self.payload)

    def context(self, project: str, session: str) -> Any:
        self.gets.append(f"/api/project-context?project={project}&session={session}")
        work: dict[str, Any] = {}
        if self.publishes_views:
            work["drift_views"] = [] if self.view is None else [copy.deepcopy(self.view)]
        return {"sources": {"work": work}}

    def post(self, path: str, body: Mapping[str, Any]) -> tuple[int, Any]:
        self.posts.append((path, copy.deepcopy(dict(body))))
        if path == "/api/reading":
            if self.reply is not None:
                return self.reply
            return self._start(body)
        if path == "/api/reading/cancel":
            return self.cancel
        if path == "/api/correction":
            return self.correction
        return 404, None

    def readings_started(self) -> int:
        return sum(1 for path, _ in self.posts if path == "/api/reading")

    def _start(self, body: Mapping[str, Any]) -> tuple[int, Any]:
        self.model_calls += 1
        job = {
            "id": "job-1",
            "phase": "preparing",
            "phase_at": NOW,
            "started_at": NOW,
            "provider": "claude",
            "cancelling": False,
            "steps": [
                {"phase": "preparing", "text": "Preparing what is sent"},
                {"phase": "waiting", "text": "Waiting for Claude Code"},
                {"phase": "checking", "text": "Checking the reply"},
            ],
        }
        self.payload["reading_jobs"] = {KEY: job}
        self._polls_left = self.job_polls
        self._adopt = body.get("adopt")
        return 202, {"ok": True, "job": job}

    def _finish(self) -> None:
        self.payload["reading_jobs"] = {}
        self._polls_left = None
        row = self.payload["sessions"][0]
        row["annotation_assessment"] = {**ASSESSMENT, "read_at": NOW + 1}
        if getattr(self, "_adopt", None):
            row["annotation_goal"] = row.get("first_prompt") or row.get("annotation_goal")
            row["annotation_goal_source"] = self._adopt
        self.view = copy.deepcopy(self.finished_view)


class Clock:
    """A fake clock that a fake sleep advances, so a long reading costs no wall time."""

    def __init__(self, at: float = NOW) -> None:
        self.at = at
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.at += seconds


def drift(  # noqa: PLR0913 - each is a seam of `terminal_drift.run`
    board: FakeBoard,
    *,
    again: bool = False,
    at_shell: bool = True,
    in_session: bool = False,
    harness: str = "claude",
    clock: Clock | None = None,
    sleep: Any = None,
    began: float | None = None,
    note: str = "",
) -> tuple[int, str, str]:
    """`in_session` is the skill's own run: named by the environment, read through a pipe."""
    out, err = io.StringIO(), io.StringIO()
    ticking = clock or Clock()
    code = terminal_drift.run(
        harness,
        "abc",
        again=again,
        at_shell=at_shell,
        in_session=in_session,
        board=board,
        port=PORT,
        out=out,
        err=err,
        clock=ticking,
        sleep=sleep or ticking.sleep,
        began=began,
        note=note,
    )
    return code, out.getvalue(), err.getvalue()


def stored(**row_fields: Any) -> FakeBoard:
    """A board holding a current stored reading of the session."""
    return FakeBoard(
        a_payload(a_row(annotation_assessment=dict(ASSESSMENT), **row_fields)), view=a_view()
    )


class AllowanceTest(unittest.TestCase):
    def test_a_person_reads_the_same_allowance_the_page_draws_for_every_preview(self) -> None:
        cases = json.loads(ALLOWANCE.read_text(encoding="utf-8"))["cases"]
        self.assertGreater(len(cases), 20)
        for case in cases:
            with self.subTest(case["name"]):
                route = {"capacity": case["capacity"]}
                self.assertEqual(case["lines"], terminal_drift.allowance_lines(route))

    def test_a_person_with_no_route_is_told_the_allowance_is_unknown(self) -> None:
        self.assertEqual(
            [
                (
                    "Next Analyze prompt: Allowance unknown. "
                    "This server did not provide a usable estimate."
                )
            ],
            terminal_drift.allowance_lines(None),
        )


class NativeSessionIdTest(unittest.TestCase):
    """Claude Code gives the command its full session UUID; the board keys the row by its first
    eight characters and carries the full id as `resume_id` (measured on a real board,
    2026-11-06), so the skill's own run must find its row by the same rule `--sessions` uses."""

    FULL = "734243e7-d73d-47ec-b97b-0e3bb1a02f09"

    def board(self) -> FakeBoard:
        row = a_row(sid="734243e7", resume_id=self.FULL, annotation_assessment=dict(ASSESSMENT))
        return FakeBoard(a_payload(row), view=a_view(sid="734243e7"))

    def run_with(self, board: FakeBoard, sid: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        ticking = Clock()
        code = terminal_drift.run(
            "claude",
            sid,
            again=False,
            at_shell=False,
            in_session=True,
            board=board,
            port=PORT,
            out=out,
            err=err,
            clock=ticking,
            sleep=ticking.sleep,
            began=None,
            note="",
        )
        return code, out.getvalue(), err.getvalue()

    def test_a_person_in_a_session_reads_the_reading_the_board_keeps_under_the_short_id(
        self,
    ) -> None:
        code, out, err = self.run_with(self.board(), self.FULL)

        self.assertEqual(0, code, err)
        self.assertIn(terminal_drift.PROVENANCE, out)
        self.assertNotIn("on the board, so nothing was read", err)
        self.assertIn("claude:734243e7", out)

    def test_a_person_naming_the_short_id_still_reads_the_same_session(self) -> None:
        code, out, err = self.run_with(self.board(), "734243e7")

        self.assertEqual(0, code, err)
        self.assertIn(terminal_drift.PROVENANCE, out)

    def test_another_session_sharing_the_prefix_is_not_read_as_this_one(self) -> None:
        other = "734243e7-0000-4000-8000-000000000000"
        code, _, err = self.run_with(self.board(), other)

        self.assertEqual(1, code)
        self.assertIn("on the board, so nothing was read", err)


class FreeReadTest(unittest.TestCase):
    def test_a_person_with_a_current_reading_reads_it_and_spends_nothing(self) -> None:
        board = stored()
        code, out, _err = drift(board)
        self.assertEqual(0, code)
        self.assertEqual(0, board.readings_started())
        self.assertIn("Level: Medium", out)
        self.assertNotIn("Next Analyze prompt", out)

    def test_a_person_who_runs_it_twice_with_nothing_new_spends_only_the_first_time(self) -> None:
        board = FakeBoard()
        first, _out, _err = drift(board)
        self.assertEqual(0, first)
        self.assertEqual(1, board.model_calls)
        second, out, _err = drift(board)
        self.assertEqual(0, second)
        self.assertEqual(1, board.model_calls)
        self.assertEqual(1, board.readings_started())
        self.assertIn("Level: Medium", out)

    def test_a_person_who_asks_again_spends_even_over_a_current_reading(self) -> None:
        board = stored()
        code, _out, _err = drift(board, again=True)
        self.assertEqual(0, code)
        self.assertEqual(1, board.model_calls)

    def test_a_person_reads_the_goal_with_where_it_came_from(self) -> None:
        clock = time.strftime("%H:%M", time.localtime(NOW - 3600))
        _code, out, _err = drift(stored())
        self.assertIn(f"Goal (You typed this · saved at {clock}): Make the parser accept tabs", out)

    def test_a_person_reads_each_outcome_line_with_its_state_and_source(self) -> None:
        _code, out, _err = drift(stored())
        self.assertIn("- Departs · Goal: Make the parser accept tabs", out)
        self.assertIn("- Consistent · Line 1 (typed): The tests pass", out)

    def test_a_person_reads_each_departure_with_their_words_entries_and_reason(self) -> None:
        _code, out, _err = drift(stored())
        self.assertIn(
            '- Goal: "Make the parser accept tabs" · entries #41, #41.2 · '
            "The agent rewrote the lexer to reject tabs.",
            out,
        )

    def test_a_person_reads_that_the_reading_is_a_model_s_and_is_data(self) -> None:
        _code, out, _err = drift(stored())
        self.assertIn(terminal_drift.PROVENANCE, out)
        self.assertLess(out.index(terminal_drift.PROVENANCE), out.index("Level:"))

    def test_a_person_reads_a_departure_demoted_by_a_later_message_as_not_verifiable(self) -> None:
        view = a_view(departures=[], analysis={"level": "not_enough", "withheld": True}, pill=None)
        view["lines"][0].update(state="cant-tell", why="baseline-open")
        board = FakeBoard(a_payload(a_row(annotation_assessment=dict(ASSESSMENT))), view=view)
        _code, out, _err = drift(board)
        self.assertIn(
            "- Can't tell · Goal: Make the parser accept tabs — a message you sent after your "
            "goal is not settled",
            out,
        )
        self.assertNotIn("Level:", out)
        self.assertNotIn("Departures:", out)

    def test_a_person_whose_reading_found_not_enough_reads_no_level_as_the_page_draws_none(
        self,
    ) -> None:
        # The page draws no level for a stored reading held at not_enough: no bar stands in for
        # the verdict sentence, so the terminal prints none either.
        view = a_view(departures=[], pill=None)
        view["analysis"] = {
            "level": "not_enough",
            "reasons": ["later-direction"],
            "withheld": False,
        }
        board = FakeBoard(a_payload(a_row(annotation_assessment=dict(ASSESSMENT))), view=view)
        _code, out, _err = drift(board)
        self.assertNotIn("Level:", out)
        self.assertNotIn("Not enough recorded yet", out)

    def test_a_person_over_a_drafted_goal_reads_no_level_as_the_page_draws_none(self) -> None:
        board = FakeBoard(
            a_payload(a_row(annotation_assessment=dict(ASSESSMENT))), view=a_view(drafted=True)
        )
        _code, out, _err = drift(board)
        self.assertNotIn("Level:", out)

    def test_a_person_whose_agent_claimed_nothing_reads_no_claims_row(self) -> None:
        # Measured on a real session: the claims row arrives unverifiable with no clause, and the
        # page draws no row for it (`claimsDrawn`).
        view = a_view()
        view["lines"].append(
            {
                "key": "claims",
                "state": "cant-tell",
                "result": "not verifiable from available evidence",
                "why": "",
                "clause": "",
                "detail": "",
                "numbers": [],
            }
        )
        board = FakeBoard(a_payload(a_row(annotation_assessment=dict(ASSESSMENT))), view=view)
        _code, out, _err = drift(board)
        self.assertNotIn("What the agent claimed", out)
        self.assertIn("- Consistent · Line 1 (typed): The tests pass", out)

    def test_a_person_reads_a_claim_the_record_does_not_show_without_an_empty_clause(
        self,
    ) -> None:
        view = a_view()
        view["lines"].append(
            {
                "key": "claims",
                "state": "unshown",
                "result": "not shown by the record",
                "why": "",
                "clause": "",
                "detail": "",
                "numbers": [],
            }
        )
        board = FakeBoard(a_payload(a_row(annotation_assessment=dict(ASSESSMENT))), view=view)
        _code, out, _err = drift(board)
        self.assertIn("\n- Not shown · What the agent claimed\n", out)

    def test_a_person_whose_words_were_not_retained_reads_that_instead_of_a_blank(self) -> None:
        view = a_view()
        view["lines"][1]["clause"] = ""
        view["lines"][0]["clause"] = ""
        board = FakeBoard(a_payload(a_row(annotation_assessment=dict(ASSESSMENT))), view=view)
        _code, out, _err = drift(board)
        unretained = "the words of the revision this reading read are not retained"
        self.assertIn(f"- Consistent · Line 1 (typed): {unretained}", out)
        self.assertIn(f"- Goal: {unretained} · entries #41, #41.2", out)
        self.assertNotRegex(out, r"(?m)^- .*: *$")

    def test_a_person_reads_how_many_later_messages_were_left_unsettled(self) -> None:
        board = stored()
        board.view = a_view(unsettled=True, unsettled_count=2)
        _code, out, _err = drift(board)
        self.assertIn(
            "2 messages you sent after your goal were left unsettled, so a departure they could "
            "change reads as not verifiable. The session page can add them as lines or make one "
            "the goal.",
            out,
        )

    def test_a_person_reads_earlier_departures_still_in_view(self) -> None:
        board = stored()
        board.view = a_view(
            priors=[
                {
                    "key": "line_1",
                    "read_at": NOW - 7200,
                    "answer": "said",
                    "cites": ["fact:z"],
                    "numbers": ["12"],
                    "clause": "The tests pass",
                    "detail": "A test was skipped.",
                }
            ]
        )
        _code, out, _err = drift(board)
        clock = time.strftime("%H:%M", time.localtime(NOW - 7200))
        self.assertIn("Earlier departures:", out)
        self.assertIn(
            f'- Line 1: "The tests pass" · read at {clock} · entries #12 · A test was skipped.', out
        )

    def test_a_person_reads_why_a_reading_is_stale_and_how_to_check_again(self) -> None:
        board = stored()
        board.view = a_view(stale={"kind": "work", "before": NOW - 300})
        _code, out, _err = drift(board)
        clock = time.strftime("%H:%M", time.localtime(NOW - 300))
        self.assertIn(f"Read before your message at {clock}. New work since this analysis.", out)
        self.assertIn("--drift again", out)

    def test_a_person_told_how_to_ask_over_a_stale_reading_is_told_that_it_spends(self) -> None:
        for at_shell in (True, False):
            with self.subTest(at_shell=at_shell):
                board = stored()
                board.view = a_view(stale={"kind": "work", "before": NOW - 300})
                _code, out, _err = drift(board, at_shell=at_shell)
                asked = [line for line in out.splitlines() if "drift again" in line]
                self.assertTrue(asked)
                for line in asked:
                    self.assertIn("spends", line)
                    self.assertNotIn("check again", line)

    def test_a_person_whose_words_changed_reads_that_their_intent_changed(self) -> None:
        board = stored()
        board.view = a_view(stale={"kind": "intent", "before": None})
        _code, out, _err = drift(board)
        self.assertIn("Your intent changed after this analysis.", out)

    def test_a_person_in_a_shell_reads_the_correction_to_copy(self) -> None:
        board = stored()
        _code, out, _err = drift(board, at_shell=True)
        self.assertIn("Correction to copy:", out)
        self.assertIn("Steer back: keep tabs.\nThanks.", out)
        self.assertIn(("/api/correction"), [path for path, _ in board.posts])

    def test_a_person_in_a_session_reads_only_that_a_correction_is_ready(self) -> None:
        board = stored()
        _code, out, _err = drift(board, at_shell=False)
        self.assertNotIn("Steer back: keep tabs.", out)
        self.assertIn(
            "A correction is ready to copy on the session page. `spacedock-compass --drift "
            "--session claude:abc` prints it only when you run it in your own terminal.",
            out,
        )

    def test_a_person_with_no_departure_is_shown_no_correction(self) -> None:
        board = stored()
        board.view = a_view(departures=[])
        _code, out, _err = drift(board)
        self.assertNotIn("orrection", out)
        self.assertNotIn("/api/correction", [path for path, _ in board.posts])

    def test_a_person_whose_correction_is_too_long_reads_why(self) -> None:
        board = stored()
        board.correction = (200, {"ok": False, "reason": "too-long", "why": "Too long to send."})
        code, out, _err = drift(board)
        self.assertEqual(0, code)
        self.assertIn("Too long to send.", out)

    def test_a_person_reads_the_session_page_last(self) -> None:
        _code, out, _err = drift(stored())
        self.assertEqual(f"Session page: {PAGE}", out.rstrip("\n").splitlines()[-1])

    def test_a_person_is_never_steered_by_control_characters_in_a_reason(self) -> None:
        board = stored()
        view = a_view()
        view["lines"][0]["detail"] = "evil\x1b]52;c;cGF5bG9hZA==\x07 text\nsecond line"
        board.view = view
        _code, out, _err = drift(board)
        self.assertNotIn("\x1b", out)
        self.assertIn("evil text second line", out)

    def test_a_person_reads_a_reading_this_build_cannot_read_as_one_sentence(self) -> None:
        board = stored()
        board.view = a_view(malformed="unknown-key")
        code, _out, err = drift(board)
        self.assertEqual(1, code)
        self.assertEqual(1, len(err.strip().splitlines()))
        self.assertIn(PAGE, err)


class SpendTest(unittest.TestCase):
    def test_a_person_reads_the_allowance_before_the_reading_is_sent(self) -> None:
        board = FakeBoard()
        _code, out, _err = drift(board)
        self.assertIn("Next Analyze prompt: Estimated allowance: 512 KB.", out)
        self.assertLess(out.index("Next Analyze prompt"), out.index("Level:"))

    def test_a_person_s_press_is_the_page_s_and_settles_nothing(self) -> None:
        board = FakeBoard()
        drift(board)
        path, body = board.posts[0]
        self.assertEqual("/api/reading", path)
        self.assertEqual(
            {
                "harness": "claude",
                "sid": "abc",
                "provider": "claude",
                "press": True,
                "observer_model": 1,
                "expected_revision": 3,
                "model": "claude-sonnet-5-5",
            },
            body,
        )
        self.assertNotIn("/api/annotate", [p for p, _ in board.posts])
        self.assertNotIn("/api/direction", [p for p, _ in board.posts])

    def test_a_person_with_no_saved_goal_adopts_the_draft_and_is_told_it_was_saved(self) -> None:
        row = a_row(
            annotation_goal="",
            annotation_revision=None,
            annotation_goal_saved_at=None,
            annotation_line_1="",
            first_prompt="Teach the parser about tabs",
            first_prompt_at=NOW - 4000,
        )
        board = FakeBoard(a_payload(row))
        code, out, _err = drift(board)
        self.assertEqual(0, code)
        body = board.posts[0][1]
        self.assertEqual("first-prompt", body["adopt"])
        self.assertEqual("Teach the parser about tabs", body["expected_prompt"])
        self.assertEqual(NOW - 4000, body["expected_prompt_at"])
        self.assertIn(
            "Saved the goal drafted from your first prompt, so this reading reads against it.",
            out,
        )
        self.assertIn("Goal (From your first prompt · saved): Teach the parser about tabs", out)

    def test_a_person_sees_the_one_time_notice_when_the_server_says_it_is_due(self) -> None:
        board = FakeBoard()
        original = board._start

        def with_notice(body: Mapping[str, Any]) -> tuple[int, Any]:
            status, answer = original(body)
            answer["notice"] = {
                "kind": "reading",
                "provider": "claude",
                "destination": "Anthropic, through your Claude Code",
                "tool_output": "",
                "at": NOW,
            }
            return status, answer

        board._start = with_notice  # type: ignore[method-assign]
        _code, out, _err = drift(board)
        self.assertIn(
            "Notice: this request sends to Claude Code. "
            "Words go to: Anthropic, through your Claude Code.",
            out,
        )

    def test_a_person_sees_no_notice_when_none_is_due(self) -> None:
        _code, out, _err = drift(FakeBoard())
        self.assertNotIn("Notice:", out)

    def test_a_person_sees_progress_while_the_reading_runs(self) -> None:
        _code, _out, err = drift(FakeBoard())
        self.assertIn("Preparing what is sent", err)

    def test_a_person_still_gets_a_reading_that_takes_longer_than_ten_minutes(self) -> None:
        clock = Clock()
        board = FakeBoard(job_polls=200)
        code, out, _err = drift(board, clock=clock)
        self.assertEqual(0, code)
        self.assertGreater(clock.at - NOW, 600)
        self.assertIn("Level: Medium", out)

    def test_a_person_who_interrupts_a_reading_they_started_cancels_exactly_it(self) -> None:
        board = FakeBoard(job_polls=50)
        calls = {"n": 0}

        def interrupted(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt

        code, out, _err = drift(board, sleep=interrupted)
        self.assertEqual(130, code)
        cancels = [body for path, body in board.posts if path == "/api/reading/cancel"]
        self.assertEqual(
            [
                {
                    "harness": "claude",
                    "sid": "abc",
                    "job": "job-1",
                    "press": True,
                    "observer_model": 1,
                }
            ],
            cancels,
        )
        self.assertIn("Cancelled. Nothing more will be read.", out)

    def test_a_person_who_interrupts_a_reading_they_found_running_leaves_it_running(
        self,
    ) -> None:
        board = FakeBoard()
        board.payload["reading_jobs"] = {
            KEY: {"id": "job-9", "phase": "waiting", "started_at": NOW, "steps": []}
        }
        board._polls_left = 50

        def interrupted(_seconds: float) -> None:
            raise KeyboardInterrupt

        code, out, err = drift(board, sleep=interrupted)
        self.assertEqual(130, code)
        self.assertEqual([], [path for path, _ in board.posts])
        said = (out + err).strip().splitlines()
        self.assertEqual(1, len(said))
        self.assertIn("keeps running", said[0])
        self.assertIn(PAGE, said[0])
        self.assertNotIn("Cancelled", out + err)

    def test_a_person_told_a_reading_is_in_flight_does_not_cancel_it_on_interrupt(self) -> None:
        # Another tab's press landed first: the board answers with that job, which this run
        # waits on but did not start.
        board = FakeBoard(
            reply=(409, {"ok": False, "produced": False, "reason": "in-flight", "job": {"id": "j"}})
        )
        board._polls_left = 50
        real_post = board.post

        def press_then_publish(path: str, body: Mapping[str, Any]) -> tuple[int, Any]:
            answer = real_post(path, body)
            if path == "/api/reading":
                board.payload["reading_jobs"] = {KEY: {"id": "j", "phase": "waiting"}}
            return answer

        def interrupted(_seconds: float) -> None:
            raise KeyboardInterrupt

        board.post = press_then_publish  # type: ignore[method-assign]
        code, _out, _err = drift(board, sleep=interrupted)
        self.assertEqual(130, code)
        self.assertNotIn("/api/reading/cancel", [path for path, _ in board.posts])

    def test_a_person_who_interrupts_before_a_job_is_known_is_told_where_to_look(self) -> None:
        board = FakeBoard()

        def interrupted(path: str, body: Mapping[str, Any]) -> tuple[int, Any]:
            board.posts.append((path, dict(body)))
            raise KeyboardInterrupt

        board.post = interrupted  # type: ignore[method-assign]
        code, _out, err = drift(board)
        self.assertEqual(130, code)
        self.assertEqual(f"{terminal_drift.INTERRUPTED} {PAGE}", err.strip())

    def test_a_person_in_a_session_is_told_to_ask_again_when_the_reading_runs_long(self) -> None:
        board = FakeBoard(job_polls=500)
        code, out, _err = drift(board, at_shell=False)
        self.assertEqual(0, code)
        self.assertIn("Still reading", out)
        self.assertNotIn("/api/reading/cancel", [path for path, _ in board.posts])
        # Asking again attaches to the job that is still running and starts no second one.
        board._polls_left = 1
        code, out, _err = drift(board, at_shell=False)
        self.assertEqual(0, code)
        self.assertEqual(1, board.readings_started())
        self.assertIn("Level: Medium", out)

    def test_a_person_in_a_session_who_follows_the_still_reading_line_spends_nothing_more(
        self,
    ) -> None:
        board = FakeBoard(job_polls=500)
        _code, out, _err = drift(board, at_shell=False)
        line = next(line for line in out.splitlines() if line.startswith("Still reading"))
        self.assertNotIn("nothing more", line)
        command = re.search(r"`spacedock-compass ([^`]*)`", line)
        self.assertIsNotNone(command, line)
        assert command is not None
        claimed, again, session = terminal_client.parse_drift_args(shlex.split(command.group(1)))
        self.assertEqual((True, KEY), (claimed, session))
        # The reading ends between the two runs, and the person follows the line as printed.
        board._finish()
        code, out, _err = drift(board, again=again, at_shell=False)
        self.assertEqual(0, code)
        self.assertEqual(1, board.readings_started())
        self.assertIn("Level: Medium", out)

    def test_a_person_in_a_session_hears_still_reading_within_the_wait_counted_from_the_start(
        self,
    ) -> None:
        # A dashboard started, and a slow board read, before the wait both come out of the same
        # budget: the tool's timeout counts from the command's start, not from the press.
        clock = Clock()
        began = NOW - 60
        board = FakeBoard(job_polls=500)
        code, out, _err = drift(board, at_shell=False, clock=clock, began=began)
        self.assertEqual(0, code)
        self.assertIn("Still reading", out)
        self.assertLessEqual(clock.at - began, terminal_drift.IN_SESSION_WAIT_SEC)
        self.assertNotIn("/api/reading/cancel", [path for path, _ in board.posts])

    def test_a_person_in_a_session_is_not_charged_a_reading_there_is_no_time_left_to_hear(
        self,
    ) -> None:
        clock = Clock()
        board = FakeBoard()
        code, out, err = drift(board, at_shell=False, clock=clock, began=NOW - 80)
        self.assertEqual((1, ""), (code, out))
        self.assertEqual(terminal_drift.NO_TIME, err.strip())
        self.assertEqual(0, board.readings_started())

    def test_a_person_at_a_shell_is_never_cut_short_by_the_in_session_wait(self) -> None:
        clock = Clock()
        board = FakeBoard(job_polls=50)
        code, out, _err = drift(board, at_shell=True, clock=clock, began=NOW - 99)
        self.assertEqual(0, code)
        self.assertEqual(1, board.readings_started())
        self.assertIn("Level: Medium", out)

    def test_a_person_in_a_session_whose_last_read_ran_out_of_time_hears_it_keeps_running(
        self,
    ) -> None:
        clock = Clock()
        board = FakeBoard(job_polls=500)
        real_data = board.data
        reads = {"n": 0}

        def slow(*_args: Any) -> Any:
            reads["n"] += 1
            if reads["n"] == 3:
                # The loopback read was cut at what was left of the wait.
                clock.at = NOW + terminal_drift.IN_SESSION_WAIT_SEC - 1
                raise terminal_drift.Lost("/api/data")
            return real_data()

        board.data = slow  # type: ignore[method-assign]
        code, out, err = drift(board, at_shell=False, clock=clock)
        self.assertEqual(0, code)
        self.assertIn("Still reading", out)
        self.assertNotIn(terminal_drift.LOST, out + err)

    def test_a_person_in_a_session_whose_tool_ends_the_wait_hears_the_reading_keeps_running(
        self,
    ) -> None:
        board = FakeBoard(job_polls=500)
        calls = {"n": 0}

        def terminated(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                os.kill(os.getpid(), signal.SIGTERM)

        before = signal.getsignal(signal.SIGTERM)
        code, out, _err = drift(board, at_shell=False, sleep=terminated)
        self.assertEqual(0, code)
        self.assertIn("Still reading", out)
        self.assertNotIn("/api/reading/cancel", [path for path, _ in board.posts])
        self.assertEqual(before, signal.getsignal(signal.SIGTERM))

    def test_a_person_in_a_session_is_told_to_type_the_skill_s_command_not_the_cli(self) -> None:
        board = FakeBoard(job_polls=500)
        _code, out, _err = drift(board, at_shell=False, in_session=True)
        line = next(line for line in out.splitlines() if line.startswith("Still reading"))
        self.assertIn("type `/compass:compass drift`", line)
        self.assertNotIn("spacedock-compass", out)

    def test_a_person_in_a_session_reads_a_correction_is_ready_without_a_command_to_run(
        self,
    ) -> None:
        _code, out, _err = drift(stored(), at_shell=False, in_session=True)
        ready = next(line for line in out.splitlines() if "correction is ready" in line)
        self.assertNotIn("spacedock-compass", ready)
        self.assertNotIn("Steer back: keep tabs.", out)

    def test_a_person_in_a_session_is_told_to_type_drift_again_over_a_stale_reading(self) -> None:
        board = stored()
        board.view = a_view(stale={"kind": "work", "before": NOW - 300})
        _code, out, _err = drift(board, at_shell=False, in_session=True)
        self.assertIn(
            "Type `/compass:compass drift again` for a new reading; that spends one.", out
        )
        self.assertNotIn("spacedock-compass", out)

    def test_a_person_in_a_session_told_the_dashboard_is_outdated_is_not_named_the_cli(
        self,
    ) -> None:
        board = FakeBoard(reply=(400, {"ok": False, "reason": "page-outdated"}))
        code, _out, err = drift(board, at_shell=False, in_session=True)
        self.assertEqual(1, code)
        self.assertNotIn("spacedock-compass", err)
        self.assertIn("/compass:compass", err)
        self.assertIn("nothing was sent", err)

    def test_a_person_in_a_session_reads_that_compass_was_started_first(self) -> None:
        _code, out, _err = drift(stored(), at_shell=False, in_session=True, note="Started.")
        self.assertEqual("Started.", out.splitlines()[0])
        board = FakeBoard(a_payload(a_row(sid="other")))
        code, out, err = drift(board, at_shell=False, in_session=True, note="Started.")
        self.assertEqual(1, code)
        self.assertEqual("Started.", err.splitlines()[0])

    def test_a_person_who_asks_while_a_reading_runs_attaches_and_starts_none(self) -> None:
        board = FakeBoard()
        board.payload["reading_jobs"] = {
            KEY: {"id": "job-9", "phase": "waiting", "started_at": NOW, "steps": []}
        }
        board._polls_left = 1
        code, out, _err = drift(board, again=True)
        self.assertEqual(0, code)
        self.assertEqual(0, board.readings_started())
        self.assertIn("Level: Medium", out)

    def test_a_person_told_in_flight_with_the_job_waits_for_that_job(self) -> None:
        board = FakeBoard(
            reply=(409, {"ok": False, "produced": False, "reason": "in-flight", "job": {"id": "j"}})
        )
        board.payload["reading_jobs"] = {}

        def finished_already(_seconds: float) -> None:
            return

        code, out, _err = drift(board, sleep=finished_already)
        self.assertEqual(1, code)
        self.assertIn("No new reading was produced.", out + _err)

    def test_a_person_whose_reading_was_withheld_reads_the_server_s_sentence(self) -> None:
        board = FakeBoard()
        original = board._finish

        def withheld() -> None:
            original()
            row = board.payload["sessions"][0]
            row["annotation_assessment"] = None
            row["annotation_reading_withheld"] = "The model did not answer."
            row["annotation_reading_withheld_at"] = NOW + 5

        board._finish = withheld  # type: ignore[method-assign]
        code, _out, err = drift(board)
        self.assertEqual(1, code)
        self.assertIn("The model did not answer.", err)


DYNAMIC_POLICY = (
    "Nothing was sent to the model, and no Analyze attempt was counted. "
    "This route uses managed policy that can change at launch. "
    "Use a route whose context and model-switching controls Compass can check locally."
)


class TypedCommandTest(unittest.TestCase):
    """A press from inside a session names the action, and the dashboard checks it was typed."""

    def test_a_person_s_typed_drift_press_names_its_action(self) -> None:
        for again, action in ((False, "drift"), (True, "drift again")):
            with self.subTest(action=action):
                board = FakeBoard()
                drift(board, again=again, at_shell=False, in_session=True)
                self.assertEqual(action, board.posts[0][1]["typed_action"])

    def test_a_press_from_a_shell_or_through_a_pipe_names_no_typed_action(self) -> None:
        for at_shell in (True, False):
            with self.subTest(at_shell=at_shell):
                board = FakeBoard()
                drift(board, at_shell=at_shell)
                self.assertNotIn("typed_action", board.posts[0][1])

    def test_a_person_whose_agent_asked_on_its_own_reads_that_nothing_was_spent(self) -> None:
        board = FakeBoard(
            reply=(409, {"ok": False, "produced": False, "reason": "typed-command-required"})
        )
        code, _out, err = drift(board, at_shell=False, in_session=True)
        self.assertEqual(1, code)
        self.assertEqual(terminal_drift.TYPED_REQUIRED, err.strip())
        self.assertEqual(0, board.model_calls)
        self.assertIn("/compass:compass drift again", terminal_drift.TYPED_REQUIRED)
        self.assertIn("nothing was read or spent", terminal_drift.TYPED_REQUIRED)

    def test_a_person_whose_typed_command_could_not_be_confirmed_reads_so(self) -> None:
        board = FakeBoard(
            reply=(409, {"ok": False, "produced": False, "reason": "typed-command-unconfirmed"})
        )
        code, _out, err = drift(board, at_shell=False, in_session=True)
        self.assertEqual(1, code)
        self.assertEqual(terminal_drift.TYPED_UNCONFIRMED, err.strip())

    def test_a_person_s_plain_drift_over_a_stored_reading_never_asks_the_check(self) -> None:
        board = stored()
        code, out, _err = drift(board, at_shell=False, in_session=True)
        self.assertEqual(0, code)
        self.assertNotIn("/api/reading", [path for path, _ in board.posts])
        self.assertIn("Level: Medium", out)


class ManagedPolicyTest(unittest.TestCase):
    """Measured on a real Claude Code session: a route under managed policy that can change at
    launch publishes a `context-dynamic` allowance, the press starts a job, and the job ends
    withheld before any model call. The press's adoption still saved the drafted goal."""

    def board(self) -> FakeBoard:
        row = a_row(
            annotation_goal="",
            annotation_revision=None,
            annotation_goal_saved_at=None,
            annotation_line_1="",
            first_prompt="Teach the parser about tabs",
            first_prompt_at=NOW - 4000,
        )
        payload = a_payload(row)
        payload["reading_routes"]["claude"]["capacity"] = {
            **CAPACITY,
            "maximum_prompt_bytes": 0,
            "reason": "context-dynamic",
            "configuration_reason": "dynamic-policy",
        }
        board = FakeBoard(payload)
        original = board._finish

        def withheld() -> None:
            original()
            row = board.payload["sessions"][0]
            row["annotation_assessment"] = None
            row["annotation_reading_withheld"] = DYNAMIC_POLICY
            row["annotation_reading_withheld_at"] = NOW + 2

        board._finish = withheld  # type: ignore[method-assign]
        return board

    def test_a_person_reads_the_server_s_one_sentence_that_nothing_was_spent(self) -> None:
        code, _out, err = drift(self.board())
        self.assertEqual(1, code)
        # Progress lines come first on stderr; the refusal is the one sentence that ends it.
        self.assertEqual(DYNAMIC_POLICY, err.strip().splitlines()[-1])
        self.assertEqual(1, err.count("Nothing was sent"))

    def test_a_person_reads_why_before_the_press_in_the_allowance(self) -> None:
        _code, out, _err = drift(self.board())
        self.assertEqual(
            "Next Analyze prompt: This route\u2019s policy can change when it starts, so its "
            "allowance cannot be established. Check its managed settings or choose another route.",
            out.splitlines()[0],
        )

    def test_a_person_reads_that_the_drafted_goal_was_saved_though_nothing_was_read(
        self,
    ) -> None:
        _code, out, _err = drift(self.board())
        self.assertIn("Goal (From your first prompt · saved): Teach the parser about tabs", out)
        self.assertNotIn("reads against it", out)
        self.assertNotIn("Level:", out)

    def test_a_person_is_not_told_a_goal_was_saved_when_the_board_shows_it_was_not(
        self,
    ) -> None:
        board = self.board()
        finish = board._finish

        def unsaved() -> None:
            finish()
            row = board.payload["sessions"][0]
            row["annotation_goal"] = ""
            row["annotation_goal_source"] = None

        board._finish = unsaved  # type: ignore[method-assign]
        _code, out, _err = drift(board)
        self.assertNotIn("· saved", out)
        self.assertIn("Goal (Drafted from your first prompt · not saved)", out)


class SessionLinkTest(unittest.TestCase):
    def test_a_person_opens_the_session_page_by_its_project_label_not_its_identity_key(
        self,
    ) -> None:
        # Measured on a real board: the page routes by the project label, and a link built from
        # `project_key` opened to "This session is not in the current payload."
        row = a_row(
            annotation_assessment=dict(ASSESSMENT),
            project="recce/compass",
            project_key="git:0845df6280c14f16ae3019bc",
        )
        board = FakeBoard(a_payload(row), view=a_view())
        _code, out, _err = drift(board)
        self.assertEqual(
            f"Session page: http://127.0.0.1:{PORT}/#n=session:recce%2Fcompass:claude:abc",
            out.rstrip("\n").splitlines()[-1],
        )
        # The context read keeps the identity key, which the server matches first.
        self.assertIn(
            f"/api/project-context?project=git:0845df6280c14f16ae3019bc&session={KEY}", board.gets
        )


class OtherHarnessTest(unittest.TestCase):
    def test_a_person_on_another_harness_is_sent_to_the_session_page(self) -> None:
        row = a_row(harness="codex")
        board = FakeBoard(a_payload(row))
        code, out, err = drift(board, harness="codex")
        self.assertEqual(0, code)
        text = out + err
        self.assertEqual(1, len(text.strip().splitlines()))
        self.assertIn("http://127.0.0.1:4553/#n=session:compass:codex:abc", text)
        self.assertNotIn("cannot", text.lower())
        self.assertEqual([], board.posts)


class RefusalTest(unittest.TestCase):
    """Every refusal the page can show is one sentence on stderr, and nothing is spent."""

    def refuse(self, board: FakeBoard, sentence: str, *, again: bool = False) -> None:
        code, out, err = drift(board, again=again)
        self.assertEqual(1, code)
        self.assertEqual("", out)
        self.assertEqual(sentence, err.strip())
        self.assertEqual(0, board.readings_started())

    def press_refused(self, reply: tuple[int, Any], sentence: str) -> None:
        board = FakeBoard(reply=reply)
        code, _out, err = drift(board)
        self.assertEqual(1, code)
        self.assertEqual(sentence, err.strip())
        self.assertEqual(1, board.readings_started())
        self.assertEqual(0, board.model_calls)

    def test_a_session_not_on_the_board(self) -> None:
        board = FakeBoard(a_payload(a_row(sid="other")))
        self.refuse(board, "Compass has no session claude:abc on the board, so nothing was read.")

    def test_annotations_off(self) -> None:
        self.refuse(FakeBoard(a_payload(annotate=False)), terminal_drift.ANNOTATIONS_OFF)

    def test_a_route_that_is_not_published(self) -> None:
        self.refuse(FakeBoard(a_payload(reading_routes={})), terminal_drift.ROUTE_UNREAD)

    def test_a_route_with_no_provider(self) -> None:
        note = "Claude Code is not installed, so no analysis can run for this session."
        routes = {"claude": {**ROUTE, "provider": "", "note": note}}
        self.refuse(FakeBoard(a_payload(reading_routes=routes)), note)

    def test_a_press_the_board_withholds(self) -> None:
        row = a_row(reading_eligibility={"ok": False, "reason": "turn-stop", "until": None})
        self.refuse(
            FakeBoard(a_payload(row)), "Analyze opens while a turn runs or once the session ends."
        )

    def test_a_press_withheld_for_a_reason_with_only_the_server_s_sentence(self) -> None:
        row = a_row(
            reading_eligibility={
                "ok": False,
                "reason": "later",
                "sentence": "Not yet.",
                "until": None,
            }
        )
        self.refuse(FakeBoard(a_payload(row)), "Not yet.")

    def test_a_prompt_whose_time_was_not_published(self) -> None:
        row = a_row(
            annotation_goal="",
            annotation_line_1="",
            instruction={"label": "asked", "text": "Do the thing", "at": None},
        )
        self.refuse(FakeBoard(a_payload(row)), terminal_drift.PROMPT_TIME_UNPUBLISHED)

    def test_nothing_typed_and_no_prompt_to_draft(self) -> None:
        row = a_row(annotation_goal="", annotation_line_1="")
        self.refuse(FakeBoard(a_payload(row)), terminal_drift.NO_WORDS)

    def test_words_the_reader_discarded(self) -> None:
        row = a_row(annotation_goal="", annotation_line_1="", annotation_discarded_at=NOW - 10)
        self.refuse(FakeBoard(a_payload(row)), terminal_drift.SAVE_STEP)

    def test_a_store_that_cannot_be_read(self) -> None:
        payload = a_payload(annotate_unreadable="The intent store could not be read.")
        self.refuse(FakeBoard(payload), "The intent store could not be read.")

    def test_model_calls_off_for_this_run(self) -> None:
        payload = a_payload(reading={"reason": "run-disabled"})
        self.refuse(FakeBoard(payload), terminal_drift.MODEL_OFF)

    def test_reading_permission_that_cannot_be_read(self) -> None:
        payload = a_payload(reading={"reason": "store-unavailable"})
        self.refuse(FakeBoard(payload), terminal_drift.POLICY_UNREADABLE)

    def test_model_calls_paused(self) -> None:
        payload = a_payload(reading={"reason": "model-calls-paused", "off": True})
        self.refuse(FakeBoard(payload), terminal_drift.READINGS_OFF)

    def test_reading_availability_not_published(self) -> None:
        self.refuse(FakeBoard(a_payload(reading=None)), terminal_drift.MODEL_UNREAD)

    def test_the_daily_limit(self) -> None:
        at = NOW + 3600
        payload = a_payload(reading={"reason": "daily-cap", "retry_at": at})
        clock = time.strftime("%H:%M", time.localtime(at))
        self.refuse(
            FakeBoard(payload), f"Analysis limit reached. You can analyze again at {clock}."
        )

    def test_a_build_where_analysis_is_not_enabled(self) -> None:
        self.refuse(FakeBoard(a_payload(reading_check="pending")), terminal_drift.UNAUTHORIZED)

    def test_a_dashboard_that_does_not_publish_the_drift_view(self) -> None:
        board = FakeBoard(publishes_views=False)
        code, _out, err = drift(board)
        self.assertEqual(1, code)
        self.assertIn(PAGE, err)
        self.assertEqual([], board.posts)

    def test_a_session_context_that_could_not_be_read(self) -> None:
        board = FakeBoard()

        def lost(_project: str, _session: str) -> Any:
            raise terminal_drift.Lost("/api/project-context")

        board.context = lost  # type: ignore[method-assign,assignment]
        code, _out, err = drift(board)
        self.assertEqual(1, code)
        self.assertEqual(f"{terminal_drift.CONTEXT_UNREAD} {PAGE}", err.strip())
        self.assertEqual([], board.posts)

    def test_a_store_busy_when_pressed(self) -> None:
        self.press_refused(
            (503, {"ok": False, "reason": "annotation-store-busy"}), terminal_drift.STORE_BUSY
        )

    def test_a_store_unusable_when_pressed(self) -> None:
        self.press_refused(
            (503, {"ok": False, "reason": "annotation-store-unavailable"}),
            terminal_drift.STORE_UNUSABLE,
        )

    def test_a_reader_that_changed(self) -> None:
        self.press_refused(
            (409, {"ok": False, "reason": "provider-changed"}), terminal_drift.PROVIDER_CHANGED
        )

    def test_a_destination_that_changed(self) -> None:
        self.press_refused(
            (409, {"ok": False, "reason": "destination-changed"}),
            terminal_drift.DESTINATION_CHANGED,
        )

    def test_words_that_changed_while_sending(self) -> None:
        self.press_refused(
            (409, {"ok": False, "reason": "revision-changed"}), terminal_drift.REVISION_CHANGED
        )

    def test_a_request_the_dashboard_calls_outdated(self) -> None:
        self.press_refused(
            (400, {"ok": False, "reason": "page-outdated"}), terminal_drift.CLIENT_OUTDATED
        )

    def test_a_reading_in_flight_with_no_job_published(self) -> None:
        self.press_refused((409, {"ok": False, "reason": "in-flight"}), terminal_drift.IN_FLIGHT)

    def test_a_route_with_no_provider_in_the_reply(self) -> None:
        self.press_refused(
            (503, {"ok": False, "route": {"provider": "", "note": "No reader is installed."}}),
            "No reader is installed.",
        )

    def test_a_press_withheld_by_the_server(self) -> None:
        self.press_refused(
            (
                200,
                {
                    "ok": False,
                    "reason": "withheld",
                    "withheld": "settling",
                    "sentence": "The session is settling.",
                },
            ),
            "Ready in a few seconds.",
        )

    def test_an_adoption_the_server_refused(self) -> None:
        self.press_refused(
            (422, {"ok": False, "adoption_refused": True}), terminal_drift.ADOPTION_REFUSED
        )

    def test_a_policy_refusal_in_the_reply(self) -> None:
        self.press_refused(
            (403, {"ok": False, "reading": {"reason": "model-calls-paused", "off": True}}),
            terminal_drift.READINGS_OFF,
        )

    def test_no_annotated_session_by_that_name(self) -> None:
        self.press_refused(
            (200, {"ok": True, "produced": False, "reason": "no annotated session by that name"}),
            terminal_drift.NOTHING_PRODUCED,
        )

    def test_a_lost_reply(self) -> None:
        board = FakeBoard()

        def lost(path: str, body: Mapping[str, Any]) -> tuple[int, Any]:
            board.posts.append((path, dict(body)))
            raise terminal_drift.Lost(path)

        board.post = lost  # type: ignore[method-assign]
        code, _out, err = drift(board)
        self.assertEqual(1, code)
        self.assertEqual(terminal_drift.LOST, err.strip())

    def test_a_reply_that_is_not_the_server_s(self) -> None:
        self.press_refused((503, {"ok": False, "reason": "no-thread"}), terminal_drift.LOST)


class DraftTest(unittest.TestCase):
    """The goal a goal-less session arrives with, ported from the page with no reader state held."""

    def label(self, **fields: Any) -> str:
        return terminal_drift.goal_source_line(a_row(**fields), a_payload())

    def test_a_drafted_first_prompt_reads_as_not_saved(self) -> None:
        self.assertEqual(
            "Drafted from your first prompt · not saved",
            self.label(annotation_goal="", first_prompt="Do it", first_prompt_at=NOW),
        )

    def test_a_clipped_draft_says_analyze_reads_the_whole_prompt(self) -> None:
        self.assertEqual(
            "Drafted from your first prompt · not saved · Shortened here; Analyze reads the "
            "whole prompt",
            self.label(annotation_goal="", first_prompt="Do it…", first_prompt_at=NOW),
        )

    def test_a_goal_set_with_slash_goal_reads_as_from_your_goal(self) -> None:
        clock = time.strftime("%H:%M", time.localtime(NOW))
        self.assertEqual(
            f"From your /goal at {clock} · not saved",
            self.label(annotation_goal="", session_goal={"text": "Ship it", "at": NOW}),
        )

    def test_a_saved_adoption_reads_as_saved_from_its_prompt(self) -> None:
        self.assertEqual(
            "From your latest prompt · saved",
            self.label(annotation_goal_source="latest-prompt"),
        )

    def test_a_typed_goal_with_no_saved_time_reads_as_saved(self) -> None:
        self.assertEqual(
            "You typed this · saved",
            self.label(annotation_goal_saved_at=None),
        )

    def test_a_copied_first_prompt_is_never_drafted(self) -> None:
        row = a_row(
            annotation_goal="",
            first_prompt="Steer back",
            first_prompt_at=NOW,
            copied_prompts=[{"fact_id": "x", "quoted_as": ["first_prompt"]}],
        )
        self.assertIsNone(terminal_drift.draft(row, a_payload()))

    def test_a_session_opened_with_a_control_drafts_nothing(self) -> None:
        row = a_row(
            annotation_goal="",
            first_prompt="/clear",
            first_prompt_at=NOW,
            first_prompt_control=True,
        )
        self.assertIsNone(terminal_drift.draft(row, a_payload()))


class AdapterTest(unittest.TestCase):
    def test_the_view_for_another_session_is_not_read(self) -> None:
        context = {"sources": {"work": {"drift_views": [a_view(sid="zzz")]}}}
        self.assertIsNone(terminal_drift.view_of(context, "claude", "abc"))

    def test_a_state_this_build_does_not_know_makes_the_view_unreadable(self) -> None:
        view = a_view()
        view["lines"][0]["state"] = "maybe"
        self.assertTrue(terminal_drift.adapt(view).malformed)

    def test_a_mid_flight_reading_with_no_drawn_level_reads_so_far(self) -> None:
        # Measured on a live board: a not_enough reading draws no level pill, so `pill` is null, yet
        # the page still leads its answer with "So far:" from the reading's own scope.
        view = a_view()
        view["pill"] = None
        view["so_far"] = True
        view["analysis"] = {"level": "not_enough", "reasons": [], "withheld": False}
        adapted = terminal_drift.adapt(view)
        self.assertTrue(adapted.so_far)
        self.assertFalse(adapted.level_so_far)
        row = {"harness": "claude", "sid": "abc"}
        out = "\n".join(terminal_drift.render(row, {}, adapted, adopted=None, again_hint=""))
        self.assertIn(terminal_drift.SO_FAR_LINE, out)
        self.assertNotIn("Level:", out)

    def test_a_finished_reading_says_nothing_of_so_far_and_the_pill_keeps_its_own(self) -> None:
        view = a_view()
        view["pill"] = {"level": "medium", "source": "analysis", "so_far": True}
        view["so_far"] = False
        adapted = terminal_drift.adapt(view)
        self.assertFalse(adapted.so_far)
        self.assertTrue(adapted.level_so_far)
        row = {"harness": "claude", "sid": "abc"}
        out = "\n".join(terminal_drift.render(row, {}, adapted, adopted=None, again_hint=""))
        self.assertNotIn("So far:", out)
        self.assertIn("Level: Medium so far", out)

    def test_the_recorded_server_row_reads_through_adapt_and_render(self) -> None:
        # The fixture is layer B's own recorded response, so this stays bound to what is published.
        recorded = json.loads(RECORDED_CONTEXT.read_text(encoding="utf-8"))["response"]["body"]
        found = terminal_drift.view_of(recorded, "claude", "a1b2c3d4")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertIn("so_far", found)
        adapted = terminal_drift.adapt(found)
        self.assertEqual("", adapted.malformed)
        self.assertEqual(found["so_far"] is True, adapted.so_far)
        row = {"harness": "claude", "sid": "a1b2c3d4"}
        out = "\n".join(terminal_drift.render(row, {}, adapted, adopted=None, again_hint=""))
        self.assertIn("Outcome lines:", out)
        self.assertEqual(adapted.so_far, terminal_drift.SO_FAR_LINE in out)
        # The recorded reading is held at not_enough, which the page draws no level for.
        self.assertEqual("not_enough", found["analysis"]["level"])
        self.assertNotIn("Level:", out)


if __name__ == "__main__":
    unittest.main()
