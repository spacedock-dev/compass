"""Qualifying the Claude Code reading producer (DRC-4666), with no model spend.

Every model here is a fake that records its prompts, so a test can say what
the producer was given and prove what was not spent. Format 5 is the packet
this qualification scores: a per-case intent with several outcome lines, and a
Claude Code case's checks frozen as they stood at the capture.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

if TYPE_CHECKING:
    from collections.abc import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abstention_ledger
import mark_abstention
import score_abstention

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "compass" / "skills" / "compass"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from compass_runtime import observer, reading  # noqa: E402

CLAUDE_SID = "c1a2b3c4-SECRET-SID"
CODEX_SID = "d5e6f7a8-SECRET-SID"
GOAL = "GOAL_WORDS make the computer win when it can"
LINE_ONE = "LINE_ONE_WORDS the ai tests pass"
LINE_TWO = "LINE_TWO_WORDS the toggle switches the theme"
TAIL = "TAIL_WORDS 29 passed"
PROSE = "MODEL_PROSE the agent did something else"


class _Config:
    reading_settle_sec = 8.0
    annotation_text_cap_chars = 240
    annotation_goal_cap_chars = 1_000


class _Model:
    """A reply per call, in order, and every prompt it was asked."""

    def __init__(self, *replies: tuple[str, str]) -> None:
        self.replies = list(replies) or [("{}", "ok")]
        self.prompts: list[str] = []

    def __call__(self, prompt: str, **_kw: Any) -> tuple[str, str]:
        self.prompts.append(prompt)
        return self.replies[min(len(self.prompts), len(self.replies)) - 1]


def _reply(**tokens: tuple[str, tuple[int, ...]]) -> str:
    return json.dumps(
        {
            name: {"result": token, "cites": list(cites), "detail": PROSE}
            for name, (token, cites) in tokens.items()
        }
    )


def _fact(fid: str, *, sid: str, harness: str, at: float, **fields: Any) -> dict[str, Any]:
    return {
        "fact_id": fid,
        "type": "result",
        "summary": "I finished the change",
        "at": at,
        "evidence": {"source": "session assistant/tool exchange", "confidence": "exact"},
        "source_session": {"harness": harness, "sid": sid},
        **fields,
    }


def _check(
    fid: str, *, at: float, result: str = "passed", record: str = "toolu_9"
) -> dict[str, Any]:
    return _fact(
        fid,
        sid=CLAUDE_SID,
        harness="claude",
        at=at,
        type="tool_report",
        subject="check",
        result=result,
        result_source="flag",
        summary="node --test tests/ai.test.js",
        evidence={"source": "Claude Bash call and paired result", "confidence": "exact"},
        branch={"harness": "claude", "sid": CLAUDE_SID, "record_id": record},
    )


def _claude_case() -> dict[str, Any]:
    return {
        "id": mark_abstention._case_id("claude", CLAUDE_SID),
        "harness": "claude",
        "sid": CLAUDE_SID,
        "origin": "recorded",
        "title": "TITLE_WORDS",
        "captured_at": 110.0,
        # A turn stop at 100 s, captured after the settle.
        "row_snapshot": {
            "harness": "claude",
            "sid": CLAUDE_SID,
            "state": "idle",
            "finished_at": 100.0,
            "ended_at": None,
        },
        "producer_facts": [
            _fact("a1", sid=CLAUDE_SID, harness="claude", at=80.0),
            _check("k1", at=90.0),
        ],
        "intent": {
            "goal": GOAL,
            "lines": [{"text": LINE_ONE, "source": "typed"}, {"text": LINE_TWO, "source": "typed"}],
        },
        "tool_output": {"tails": {"toolu_9": TAIL}, "changed_after": []},
        # What the freeze stamps on a Claude Code case, so the marker's shape
        # check and the scorer's parser check see a packet this checkout froze.
        "transcript_bytes": 0,
        "parser": mark_abstention.parser_digest(),
        "unconfirmed": [],
    }


def _codex_case() -> dict[str, Any]:
    # A recorded history `working` observation, frozen at its last activity.
    return {
        "id": mark_abstention._case_id("codex", CODEX_SID),
        "harness": "codex",
        "sid": CODEX_SID,
        "origin": "recorded",
        "captured_at": 200.0,
        "row_snapshot": {"harness": "codex", "sid": CODEX_SID, "state": "working"},
        "producer_facts": [_fact("x1", sid=CODEX_SID, harness="codex", at=150.0)],
        "intent": {"goal": GOAL, "lines": [{"text": LINE_ONE}]},
        "unconfirmed": [],
    }


BINDING = {
    "producer": "claude",
    "model": observer.CLAUDE_READING_MODEL,
    "argv_digest": "ab" * 32,
    "destination": "Anthropic",
    "binary": "~/.local/share/claude/versions/2.1.281",
    "binary_sha256": "cd" * 32,
    "cli_version": "2.1.281 (Claude Code)",
    "signature": "Developer ID Q6L2SF6YDW com.anthropic.claude-code",
}

_VERIFIED = score_abstention.VerifiedClaude(
    BINDING["binary"],
    BINDING["cli_version"],
    "/abs/claude",
    BINDING["signature"],
    (0, 0, 0, 0, 0, BINDING["binary_sha256"]),
)

_LEDGER_PATCH: Any = None


def setUpModule() -> None:
    """Never the real ledger: every test here charges a throwaway one."""
    global _LEDGER_PATCH  # noqa: PLW0603
    folder = tempfile.mkdtemp()
    _LEDGER_PATCH = mock.patch.multiple(
        abstention_ledger,
        LEDGER_PATH=str(Path(folder, "never-real.json")),
        CLAUDE_SUMMARY_PATH=str(Path(folder, "never-committed.json")),
        CONTINUATION_PATHS=tuple(
            str(Path(folder, f"never-continuation-{k}.json"))
            for k in range(abstention_ledger.MAX_GRANTS)
        ),
        CONTINUATION_SUMMARY_PATHS=tuple(
            str(Path(folder, f"never-continuation-result-{k}.json"))
            for k in range(abstention_ledger.MAX_GRANTS)
        ),
    )
    _LEDGER_PATCH.start()


def tearDownModule() -> None:
    _LEDGER_PATCH.stop()


class _Packet(unittest.TestCase):
    """A format 5 packet on disk in a temp home, marked, and a way to score it."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.cases = [_claude_case()]
        self.marks: dict[str, dict[str, str]] = {
            self.cases[0]["id"]: {"goal": "judge", "line_1": "judge", "line_2": "abstain"}
        }
        self.rubric: dict[str, Any] = {}
        self.result = self.home / "local.json"
        self.summary = self.home / "claude-results.json"
        self.ledger_path = self.home / "spend.json"

    def body(self) -> dict[str, Any]:
        return {"v": 5, "cases": self.cases}

    def corpus(self) -> score_abstention.Corpus:
        marks = {
            "v": 4,
            "cases_digest": mark_abstention.cases_digest(self.body()),
            "marks": self.marks,
        }
        return score_abstention.Corpus(self.body(), marks, json.dumps(marks).encode(), self.rubric)

    def score(
        self,
        model: _Model,
        *,
        destination: str | None = "Anthropic",
        cap: int = 19,
        resume: dict[str, Any] | None = None,
        binding: dict[str, str] | None = None,
        vouch: Any = None,
        printed: list[str] | None = None,
    ) -> int:
        sink = printed if printed is not None else []
        with (
            mock.patch.object(score_abstention, "_get", side_effect=AssertionError("live read")),
            mock.patch(
                "builtins.print", side_effect=lambda *a, **_k: sink.append(" ".join(map(str, a)))
            ),
        ):
            return score_abstention.score(
                1,
                self.corpus(),
                config=_Config(),
                model=model,
                results_path=str(self.result),
                summary_path=str(self.summary),
                now=100000.0,
                binding=BINDING if binding is None else binding,
                tool_destination=destination,
                ledger_path=str(self.ledger_path),
                max_calls=cap,
                resume=resume,
                # The machine's own records are not this test's subject, so every
                # case is vouched for unless a test says otherwise (V2 tests do).
                vouch=vouch or (lambda _case: []),
            )

    def calls(self) -> list[dict[str, Any]]:
        return list(json.loads(self.ledger_path.read_text())["calls"])

    def committed(self) -> Any:
        return json.loads(self.summary.read_text())

    def local(self) -> Any:
        return json.loads(self.result.read_text())


class TheClaudeProducerIsChosenExplicitlyTest(unittest.TestCase):
    """Test 4: `--producer` is required to score, and the result names what ran."""

    def test_scoring_without_a_producer_refuses_before_building_any_model(self) -> None:
        printed: list[str] = []
        with (
            mock.patch.object(reading, "ClaudeReadingModel", side_effect=AssertionError),
            mock.patch.object(reading, "CodexReadingModel", side_effect=AssertionError),
            mock.patch("builtins.print", side_effect=lambda *a, **_k: printed.append(" ".join(a))),
        ):
            self.assertEqual(2, score_abstention.main(["--score"]))
        self.assertIn("--producer", "\n".join(printed))

    def test_the_claude_producer_builds_the_claude_model_and_its_own_result_file(self) -> None:
        seen: dict[str, Any] = {}

        def fake_score(*_args: Any, **kwargs: Any) -> int:
            seen.update(kwargs)
            return 0

        corpus = score_abstention.Corpus({"v": 5, "cases": [_claude_case()]}, {}, b"", {})
        with (
            mock.patch.object(score_abstention, "_load_corpus", return_value=corpus),
            mock.patch.object(score_abstention, "score", side_effect=fake_score),
            mock.patch.object(score_abstention, "argv_digest", return_value="cd" * 32),
            mock.patch.object(
                score_abstention,
                "verify_claude_binary",
                return_value=_VERIFIED,
            ),
            mock.patch("compass_runtime.reading_route.destination", return_value="Anthropic"),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(0, score_abstention.main(["--score", "--producer", "claude"]))
        self.assertIsInstance(seen["model"], reading.ClaudeReadingModel)
        self.assertIsInstance(seen["model"].binary_resolver, score_abstention.PinnedClaude)
        self.assertEqual(score_abstention.CLAUDE_SUMMARY_PATH, seen["summary_path"])
        self.assertEqual(
            ("docs", "abstention", "claude-results.json"), Path(seen["summary_path"]).parts[-3:]
        )
        self.assertEqual({**BINDING, "argv_digest": "cd" * 32}, dict(seen["binding"]))
        self.assertEqual(28, seen["max_calls"])
        self.assertEqual(abstention_ledger.LEDGER_PATH, seen["ledger_path"])

    def test_an_explicit_baseline_is_bound_to_the_qualification_model_and_result(self) -> None:
        seen: dict[str, Any] = {}

        def fake_score(*_args: Any, **kwargs: Any) -> int:
            seen.update(kwargs)
            return 0

        corpus = score_abstention.Corpus({"v": 5, "cases": [_claude_case()]}, {}, b"", {})
        with (
            mock.patch.object(score_abstention, "_load_corpus", return_value=corpus),
            mock.patch.object(score_abstention, "score", side_effect=fake_score),
            mock.patch.object(score_abstention, "argv_digest", return_value="cd" * 32),
            mock.patch.object(score_abstention, "verify_claude_binary", return_value=_VERIFIED),
            mock.patch("compass_runtime.reading_route.destination", return_value="Anthropic"),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(
                0,
                score_abstention.main(
                    [
                        "--score",
                        "--producer",
                        "claude",
                        "--claude-reading-model",
                        "claude-sonnet-5",
                    ]
                ),
            )
        self.assertEqual("claude-sonnet-5", seen["model"].config.claude_reading_model)
        self.assertEqual("claude-sonnet-5", seen["binding"]["model"])

    def test_the_argv_digest_is_read_without_running_anything(self) -> None:
        with mock.patch("subprocess.run", side_effect=AssertionError("spent")):
            first = score_abstention.argv_digest("claude", _state_config())
            again = score_abstention.argv_digest("claude", _state_config())
            with mock.patch.object(observer, "CLAUDE_READING_EFFORT", "low"):
                moved = score_abstention.argv_digest("claude", _state_config())
            codex = score_abstention.argv_digest("codex", _state_config())
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(first, again)
        self.assertNotEqual(first, moved)
        self.assertEqual(codex, score_abstention.argv_digest("codex", _state_config()))


def _state_config() -> Any:
    from compass_runtime.config import build_runtime_config  # noqa: PLC0415

    home = tempfile.mkdtemp()
    return build_runtime_config(
        environ={"HOME": home, "COMPASS_HOME": home},
        platform_name="linux",
        os_name="posix",
        launcher_path=Path(home, "server.py"),
    )


class TheSummaryIsBoundToWhatProducedItTest(_Packet):
    def test_the_committed_file_names_the_producer_the_model_and_the_argv(self) -> None:
        self.assertEqual(0, self.score(_Model()))
        committed = self.committed()
        for key, value in BINDING.items():
            self.assertEqual(value, committed[key])


class TheFrozenChecksReachTheProducerTest(_Packet):
    """Test 5: the frozen tails go to the prompt, and only with a named destination."""

    def test_the_frozen_check_and_its_tail_are_in_the_prompt(self) -> None:
        model = _Model()
        self.score(model)
        self.assertEqual(1, len(model.prompts))
        self.assertIn("node --test tests/ai.test.js", model.prompts[0])
        self.assertIn(TAIL, model.prompts[0])
        self.assertTrue(self.committed()["cases"][self.cases[0]["id"]]["asks_output"])

    def test_an_unnamed_destination_refuses_to_score_before_anything(self) -> None:
        model = _Model()
        self.assertEqual(2, self.score(model, destination=""))
        self.assertEqual([], model.prompts)
        self.assertFalse(self.summary.exists())
        self.assertFalse(self.result.exists())
        self.assertFalse(self.ledger_path.exists())


class ATurnStopIsReadWhereTheRouteReadsOneTest(_Packet):
    """Test 6: `admit_turn_stop` for a Claude Code turn stop, never for Codex."""

    def test_a_claude_turn_stop_reaches_the_model(self) -> None:
        model = _Model()
        self.score(model)
        self.assertEqual(1, len(model.prompts))
        self.assertEqual("", self.local()["cases"][self.cases[0]["id"]]["withheld"])

    def test_a_codex_turn_stop_stays_withheld(self) -> None:
        case = _codex_case()
        case["row_snapshot"].update(state="idle", finished_at=150.0)
        self.cases = [case]
        self.marks = {case["id"]: {"goal": "judge", "line_1": "abstain"}}
        model = _Model()
        self.score(model)
        self.assertEqual([], model.prompts)
        self.assertEqual("turn-stop", self.local()["cases"][case["id"]]["withheld"])

    def test_a_recorded_working_observation_is_a_codex_case(self) -> None:
        case = _codex_case()
        self.cases = [case]
        self.marks = {case["id"]: {"goal": "judge", "line_1": "abstain"}}
        model = _Model()
        self.score(model)
        self.assertEqual(1, len(model.prompts))
        # No work evidence on Codex, so the line is the ruling's answer.
        self.assertFalse(self.committed()["cases"][case["id"]]["asks_output"])


class EachOutcomeLineIsItsOwnConstraintTest(_Packet):
    """Test 7: marks and outcomes per line, and a line marked abstain that judged fails."""

    def test_the_outcomes_are_keyed_goal_then_each_line(self) -> None:
        self.score(_Model(("{}", "ok")))
        outcomes = self.committed()["cases"][self.cases[0]["id"]]["outcomes"]
        self.assertEqual(["goal", "line_1", "line_2"], list(outcomes))

    def test_an_abstain_marked_line_judged_consistent_fails_the_check(self) -> None:
        reply = _reply(
            goal=("consistent", (2,)), line_1=("consistent", (2,)), line_2=("consistent", (2,))
        )
        self.assertEqual(1, self.score(_Model((reply, "ok"))))
        committed = self.committed()
        outcomes = committed["cases"][self.cases[0]["id"]]["outcomes"]
        self.assertEqual("judged:consistent", outcomes["line_1"])
        self.assertEqual("judged:consistent", outcomes["line_2"])
        self.assertEqual([self.cases[0]["id"]], committed["dec17"]["failed"])
        self.assertEqual("failed", committed["verdict"])

    def test_a_mark_missing_a_line_refuses_the_packet(self) -> None:
        self.marks[self.cases[0]["id"]].pop("line_2")
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)


class WhatAConsistentRestsOnTest(_Packet):
    """Test 8: a Goal consistent on the agent's own account is never tool-reported."""

    def test_the_basis_token_tells_a_check_from_the_agents_account(self) -> None:
        reply = _reply(
            goal=("consistent", (1,)), line_1=("consistent", (2,)), line_2=("unverifiable", ())
        )
        self.score(_Model((reply, "ok")))
        committed = self.committed()
        case = committed["cases"][self.cases[0]["id"]]
        self.assertEqual("judged:consistent", case["outcomes"]["goal"])
        self.assertEqual("account", case["basis"]["goal"])
        self.assertEqual("tool", case["basis"]["line_1"])
        self.assertEqual("", case["basis"]["line_2"])
        self.assertEqual(1, committed["counts"]["goal_consistent_on_account"])


class ARubricFalseReassuranceFailsTest(_Packet):
    """Decision of 2026-09-24: marking the line abstain is not enough on its own."""

    def test_a_false_reassurance_fails_a_run_the_marks_would_pass(self) -> None:
        self.marks[self.cases[0]["id"]]["line_2"] = "judge"
        self.rubric = {
            "cases": {
                self.cases[0]["id"]: {
                    "kind": "misleading-completion",
                    "origin": "recorded",
                    "expect": {"line_1": {"result": "unverifiable", "cites": []}},
                }
            }
        }
        reply = _reply(
            goal=("unverifiable", ()), line_1=("consistent", (2,)), line_2=("unverifiable", ())
        )
        self.assertEqual(1, self.score(_Model((reply, "ok"))))
        committed = self.committed()
        self.assertEqual([], committed["dec17"]["failed"])
        self.assertEqual(1, committed["rubric"]["counts"]["false-reassurance"])
        self.assertEqual("failed", committed["verdict"])


class TheCommittedFileHoldsNothingReadableTest(_Packet):
    """Test 13: no sid, no intent text, no tail and no model prose under docs/."""

    def test_the_summary_carries_none_of_the_session(self) -> None:
        reply = _reply(
            goal=("departure", (1,)), line_1=("consistent", (2,)), line_2=("unverifiable", ())
        )
        self.score(_Model((reply, "ok")))
        text = self.summary.read_text()
        for absent in (
            CLAUDE_SID,
            GOAL,
            LINE_ONE,
            LINE_TWO,
            TAIL,
            PROSE,
            "TITLE_WORDS",
            "node --test",
        ):
            self.assertNotIn(absent, text)
        self.assertNotIn(TAIL, self.ledger_path.read_text())
        self.assertNotIn(CLAUDE_SID, self.ledger_path.read_text())


class TheMarkerAsksPerLineAndShowsTheChecksTest(unittest.TestCase):
    """Test 10: the screen lists the frozen checks, and each line is its own question."""

    def run_marker(
        self, case: dict[str, Any], answers: list[str]
    ) -> tuple[Any, list[str], dict[str, Any]]:
        body = {"v": 5, "cases": [case]}
        printed: list[str] = []
        with tempfile.TemporaryDirectory() as folder:
            cases, marks = Path(folder, "cases.json"), Path(folder, "marks.json")
            cases.write_text(json.dumps(body))
            with (
                mock.patch.object(mark_abstention, "CASES_PATH", str(cases)),
                mock.patch.object(mark_abstention, "MARKS_PATH", str(marks)),
                mock.patch.object(mark_abstention, "_ask", side_effect=answers) as ask,
                mock.patch(
                    "builtins.print",
                    side_effect=lambda *a, **_k: printed.append(" ".join(map(str, a))),
                ),
            ):
                self.assertEqual(0, mark_abstention.mark())
            saved = json.loads(marks.read_text())
        self.assertEqual(mark_abstention.cases_digest(body), saved["cases_digest"])
        return ask, printed, saved["marks"][case["id"]]

    def test_a_claude_case_with_a_check_asks_the_goal_and_every_line(self) -> None:
        ask, printed, saved = self.run_marker(_claude_case(), ["judge", "judge", "abstain"])
        self.assertEqual(3, ask.call_count)
        self.assertIn(GOAL, ask.call_args_list[0].args[0])
        self.assertIn(LINE_ONE, ask.call_args_list[1].args[0])
        self.assertIn(LINE_TWO, ask.call_args_list[2].args[0])
        self.assertEqual({"goal": "judge", "line_1": "judge", "line_2": "abstain"}, saved)
        screen = "\n".join(printed)
        self.assertIn("node --test tests/ai.test.js (passed, as the tool reported)", screen)
        self.assertIn(TAIL, screen)
        self.assertIn("Recorded lifecycle: turn-stop", screen)

    def test_a_record_with_no_check_fixes_every_line_at_abstain(self) -> None:
        ask, _printed, saved = self.run_marker(_codex_case(), ["judge"])
        self.assertEqual(1, ask.call_count)
        self.assertEqual({"goal": "judge", "line_1": "abstain"}, saved)


class TheFreezeKeepsOnlyWhatStoodAtTheCaptureTest(unittest.TestCase):
    """Test 9, end to end: board facts after the capture and live checks are dropped."""

    def test_a_frozen_claude_case_is_a_valid_packet_with_its_checks_rebuilt(self) -> None:
        start = dt.datetime(2026, 9, 24, 3, 0, 0, tzinfo=dt.UTC).timestamp()

        def stamp(seconds: int) -> str:
            return (
                dt.datetime.fromtimestamp(start + seconds, tz=dt.UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )

        rows = [
            {"type": "assistant", "isSidechain": False, "cwd": "/w", "timestamp": stamp(10),
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "isSidechain": False, "cwd": "/w", "timestamp": stamp(15),
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "toolu_1", "content": "5 passed", "is_error": False}]}},
            {"type": "assistant", "isSidechain": False, "cwd": "/w", "timestamp": stamp(40),
             "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "pytest"}}]}},
            {"type": "user", "isSidechain": False, "cwd": "/w", "timestamp": stamp(45),
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "toolu_2", "content": "1 failed", "is_error": True}]}},
        ]  # fmt: skip
        rows.insert(0, _asked(start, CLAUDE_SID, 5))
        rows.append(_asked(start, CLAUDE_SID, 50))
        with tempfile.TemporaryDirectory() as folder:
            transcript = Path(folder, "t.jsonl")
            transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            board = [
                _fact("early", sid=CLAUDE_SID, harness="claude", at=start + 5),
                _fact("late", sid=CLAUDE_SID, harness="claude", at=start + 50),
                _check("live", at=start + 40, result="failed", record="toolu_2"),
                _fact("other", sid="someone-else", harness="claude", at=start + 5),
            ]
            entry = {
                "harness": "claude",
                "sid": CLAUDE_SID,
                "project": "p",
                "captured_at": start + 30,
                "row": {"state": "idle", "finished_at": start + 20},
                "intent": {"goal": GOAL, "lines": [{"text": LINE_ONE}]},
                "transcript": str(transcript),
            }
            config = _state_config()
            case = mark_abstention.freeze_case(config, entry, board)
            with self.assertRaises(mark_abstention.FreezeError):
                mark_abstention.freeze_case(config, {**entry, "captured_at": start + 25}, board)
        ids = [fact["fact_id"] for fact in case["producer_facts"]]
        # A Claude Code case takes the reader's words from the transcript as it stood
        # at the capture, never from the board, so no board fact survives the freeze.
        for absent in ("early", "late", "live", "other"):
            self.assertNotIn(absent, ids)
        said = [f for f in case["producer_facts"] if f["type"] == "user_message"]
        self.assertEqual([start + 5], [f["at"] for f in said])
        self.assertEqual("capture", case["transcript_cut"])
        checks = [f for f in case["producer_facts"] if f["type"] == "tool_report"]
        self.assertEqual(["passed"], [c["result"] for c in checks])
        self.assertEqual({"toolu_1": "5 passed"}, case["tool_output"]["tails"])
        # A hand-written transcript outside ~/.claude/projects, with no session
        # id of its own and a lifecycle nothing recorded, is never a recorded case.
        self.assertEqual("synthetic", case["origin"])
        self.assertIn("transcript-outside-projects", case["unconfirmed"])
        self.assertIn("lifecycle-unconfirmed", case["unconfirmed"])
        corpus = score_abstention.Corpus({"v": 5, "cases": [case]}, {}, b"", {})
        with mock.patch("builtins.print"):
            self.assertTrue(score_abstention._replay_preflight(corpus))


# ------------------------------------------------------------------ DRC-4666 correction round


def _stamp(start: float, seconds: int) -> str:
    return dt.datetime.fromtimestamp(start + seconds, tz=dt.UTC).isoformat().replace("+00:00", "Z")


def _transcript(start: float, session_id: str) -> list[dict[str, Any]]:
    """One passing check, in the recorded shapes, stamped with its own session id."""
    return [
        {"type": "assistant", "isSidechain": False, "cwd": "/w", "sessionId": session_id,
         "timestamp": _stamp(start, 10), "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest"}}]}},
        {"type": "user", "isSidechain": False, "cwd": "/w", "sessionId": session_id,
         "timestamp": _stamp(start, 15), "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "toolu_1", "content": "5 passed",
              "is_error": False}]}},
    ]  # fmt: skip


class _Ledgered(_Packet):
    """A packet plus a way to charge its ledger directly, as earlier runs would have."""

    def packet_ledger(self) -> abstention_ledger.Ledger:
        corpus = self.corpus()
        return abstention_ledger.Ledger(
            str(self.ledger_path),
            cap=19,
            marks_digest=score_abstention.marks_digest(corpus),
            inputs_digest=score_abstention._inputs_digest(corpus),
            producer="claude",
        )

    def precharge(self, count: int) -> None:
        ledger = self.packet_ledger()
        for _ in range(count):
            ledger.settle(ledger.charge(self.cases[0]["id"]), "ok")


class Q1TheMarksAreBoundToEveryChargeTest(_Ledgered):
    """F1: a mark rewritten after an output was seen must not re-score cleanly."""

    def test_every_charge_records_the_marks_and_inputs_digest(self) -> None:
        self.score(_Model())
        corpus = self.corpus()
        (call,) = self.calls()
        self.assertEqual(score_abstention.marks_digest(corpus), call["marks_digest"])
        self.assertEqual(score_abstention._inputs_digest(corpus), call["inputs_digest"])

    def test_scoring_again_under_rewritten_marks_is_refused(self) -> None:
        self.score(_Model())
        self.marks[self.cases[0]["id"]]["line_2"] = "judge"
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)
        self.assertEqual(1, len(self.calls()))

    def test_scoring_again_under_changed_cases_is_refused(self) -> None:
        self.score(_Model())
        self.cases[0]["intent"]["goal"] = "CHANGED"
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)

    def test_new_marks_and_a_reset_are_refused_once_a_call_is_charged(self) -> None:
        self.precharge(1)
        body = {"v": 5, "cases": [_claude_case()]}
        cases, marks = self.home / "cases.json", self.home / "marks.json"
        cases.write_text(json.dumps(body))
        marks.write_text("{}")
        with (
            mock.patch.object(abstention_ledger, "LEDGER_PATH", str(self.ledger_path)),
            mock.patch.object(mark_abstention, "CASES_PATH", str(cases)),
            mock.patch.object(mark_abstention, "MARKS_PATH", str(marks)),
            mock.patch.object(mark_abstention, "_ask", side_effect=AssertionError("asked")),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(1, mark_abstention.mark())
            self.assertEqual(1, mark_abstention.main(["--reset"]))
        self.assertEqual("{}", marks.read_text())

    def test_the_summary_records_both_digests_and_a_report_flags_ledger_drift(self) -> None:
        self.score(_Model())
        committed = self.committed()
        corpus = self.corpus()
        self.assertEqual(score_abstention.marks_digest(corpus), committed["marks_digest"])
        self.assertEqual(score_abstention._inputs_digest(corpus), committed["inputs_digest"])
        # A call charged under other marks, as a re-marked run would leave behind.
        body = json.loads(self.ledger_path.read_text())
        body["calls"].append({**body["calls"][0], "id": "x" * 32, "marks_digest": "0" * 64})
        self.ledger_path.write_text(json.dumps(body))
        printed: list[str] = []
        with (
            mock.patch.object(abstention_ledger, "LEDGER_PATH", str(self.ledger_path)),
            mock.patch("builtins.print", side_effect=lambda *a, **_k: printed.append(str(a))),
        ):
            score_abstention.report(corpus, committed)
        self.assertIn("STALE", "\n".join(printed))


class Q2OneLedgerThatFailsClosedTest(_Ledgered):
    """F2: one fixed ledger for every producer and home, locked, and never reset by damage."""

    def test_an_operator_cannot_move_the_account_ledger_with_a_store_override(self) -> None:
        import importlib  # noqa: PLC0415

        with mock.patch.dict("os.environ", {"COMPASS_HOME": str(self.home / "fresh")}):
            fresh = importlib.reload(abstention_ledger)
            path = fresh.LEDGER_PATH
        importlib.reload(abstention_ledger)
        _LEDGER_PATCH.stop()
        _LEDGER_PATCH.start()
        self.assertEqual(abstention_ledger.canonical_store_path("drc-4666-spend.json"), path)
        self.assertNotIn("fresh", path)

    def test_the_cap_is_the_owners_ceiling_and_cannot_be_raised(self) -> None:
        # 28 scorer calls across every packet: the owner's 2026-10-01 ruling (DRC-4666)
        # added five past the DRC-4758 ceiling of 23 for one more qualification run.
        # Everything past the argument refusal raises, so a cap that let 29 through fails
        # here at once instead of verifying the real CLI and scoring against this machine.
        def unreachable(*_args: object, **_kwargs: object) -> None:
            msg = "the --max-calls refusal let a raised cap reach the scoring path"
            raise AssertionError(msg)

        printed: list[str] = []
        with (
            mock.patch.object(abstention_ledger, "home_moved", return_value=False),
            mock.patch.object(abstention_ledger, "Ledger", side_effect=unreachable),
            mock.patch.object(score_abstention, "_runtime", side_effect=unreachable),
            mock.patch.object(score_abstention, "verify_claude_binary", side_effect=unreachable),
            mock.patch.object(score_abstention, "score", side_effect=unreachable),
            mock.patch.object(score_abstention, "probe_argv", side_effect=unreachable),
            mock.patch.object(score_abstention, "_load_corpus", side_effect=unreachable),
            mock.patch.object(score_abstention, "summary_path_for", side_effect=unreachable),
            mock.patch("builtins.print", side_effect=lambda *a, **_k: printed.append(str(a[0]))),
        ):
            code = score_abstention.main(["--score", "--producer", "claude", "--max-calls", "29"])
        self.assertEqual(2, code)
        self.assertEqual(["--max-calls must be between 1 and 28, the authorized spend."], printed)
        self.assertEqual(28, abstention_ledger.MAX_CALLS)

    def test_the_cap_counts_every_earlier_run(self) -> None:
        self.precharge(18)
        second = _codex_case()
        self.cases.append(second)
        self.marks[second["id"]] = {"goal": "judge", "line_1": "abstain"}
        self.ledger_path.unlink()
        self.precharge(18)
        model = _Model()
        self.score(model)
        self.assertEqual(1, len(model.prompts))
        withheld = sorted(v["withheld"] for v in self.local()["cases"].values())
        self.assertEqual(["", "spend-cap"], withheld)
        self.assertEqual(19, len(self.calls()))

    def test_a_damaged_ledger_refuses_every_call_and_is_left_alone(self) -> None:
        for damage in (
            "{not json",
            json.dumps({"v": 1, "calls": "malformed", "runs": []}),
            json.dumps({"v": 1, "calls": [{"id": "a", "status": "ok"}], "runs": []}),
            json.dumps([]),
        ):
            with self.subTest(damage=damage[:20]):
                self.ledger_path.write_text(damage)
                model = _Model()
                self.assertEqual(2, self.score(model))
                self.assertEqual([], model.prompts)
                self.assertEqual(damage, self.ledger_path.read_text())
                self.assertFalse(self.summary.exists())

    def test_a_missing_ledger_is_an_empty_one(self) -> None:
        self.assertFalse(self.ledger_path.exists())
        model = _Model()
        self.score(model)
        self.assertEqual(1, len(model.prompts))

    def test_concurrent_processes_never_charge_past_the_cap(self) -> None:
        corpus = self.corpus()
        # Each process sleeps between its read and its write, which is where an
        # unlocked ledger loses charges: without the lock this over-charges.
        script = (
            "import sys, time; sys.path.insert(0, sys.argv[1]); import abstention_ledger as L\n"
            "L.CONTINUATION_PATHS = tuple(f'{sys.argv[5]}-{k}' for k in range(L.MAX_GRANTS))\n"
            "read = L.read\n"
            "def slow(path):\n    body = read(path); time.sleep(0.05); return body\n"
            "L.read = slow\n"
            "l = L.Ledger(sys.argv[2], cap=3, marks_digest=sys.argv[3], inputs_digest=sys.argv[4],"
            " producer='claude')\n"
            "try:\n    l.charge('0123456789abcdef'); print('charged')\n"
            "except L.SpendCapError:\n    print('capped')\n"
        )
        args = [
            str(Path(__file__).resolve().parents[1]),
            str(self.ledger_path),
            score_abstention.marks_digest(corpus),
            score_abstention._inputs_digest(corpus),
            str(self.home / "no-continuation-grant.json"),
        ]
        runs = [
            subprocess.Popen(
                [sys.executable, "-c", script, *args], stdout=subprocess.PIPE, text=True
            )
            for _ in range(8)
        ]
        said = [run.communicate(timeout=60)[0].strip() for run in runs]
        self.assertEqual(3, said.count("charged"), said)
        self.assertEqual(5, said.count("capped"), said)
        self.assertEqual(3, len(self.calls()))
        self.assertEqual([], list(self.home.glob("*.tmp")) + list(self.home.glob(".spend-*")))

    def test_codex_live_scoring_is_refused(self) -> None:
        printed: list[str] = []
        corpus = score_abstention.Corpus({"v": 5, "cases": [_claude_case()]}, {}, b"", {})
        with (
            mock.patch.object(score_abstention, "_load_corpus", return_value=corpus),
            mock.patch.object(score_abstention, "score", side_effect=AssertionError("scored")),
            mock.patch.object(reading, "CodexReadingModel", side_effect=AssertionError("built")),
            mock.patch("builtins.print", side_effect=lambda *a, **_k: printed.append(str(a))),
        ):
            self.assertEqual(2, score_abstention.main(["--score", "--producer", "codex"]))
        self.assertIn("no Codex spend", "\n".join(printed))


class Q3TheDestinationAndBinaryAreBoundTest(_Packet):
    """F3: a result must show that Anthropic's model answered through the real CLI."""

    def test_a_stub_destination_refuses_before_anything_is_written(self) -> None:
        model = _Model()
        stub = {**BINDING, "destination": "127.0.0.1:9"}
        self.assertEqual(2, self.score(model, binding=stub))
        self.assertEqual([], model.prompts)
        self.assertFalse(self.summary.exists())
        self.assertFalse(self.ledger_path.exists())

    def test_main_refuses_unless_the_destination_is_anthropic(self) -> None:
        corpus = score_abstention.Corpus({"v": 5, "cases": [_claude_case()]}, {}, b"", {})
        with (
            mock.patch.object(score_abstention, "_load_corpus", return_value=corpus),
            mock.patch.object(score_abstention, "score", side_effect=AssertionError("scored")),
            mock.patch("compass_runtime.reading_route.destination", return_value="127.0.0.1:9"),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(2, score_abstention.main(["--score", "--producer", "claude"]))

    def test_only_the_installed_claude_cli_is_accepted(self) -> None:
        versions = self.home / "share" / "claude" / "versions"
        versions.mkdir(parents=True)
        real = versions / "2.1.281"
        real.write_text("")
        stub = self.home / "bin" / "claude"
        stub.parent.mkdir()
        stub.write_text("")
        # Named like a version, outside the installed versions: only the layout refuses it.
        lookalike = self.home / "elsewhere" / "2.1.281"
        lookalike.parent.mkdir()
        lookalike.write_text("")

        def run(version: str) -> Any:
            return mock.Mock(return_value=mock.Mock(returncode=0, stdout=f"{version}\n"))

        with mock.patch.object(score_abstention, "CLAUDE_VERSIONS_ROOTS", (str(versions),)):
            verified = score_abstention.verify_claude_binary(
                resolver=lambda _name: str(real), runner=run("2.1.281 (Claude Code)")
            )
            self.addCleanup(verified.close)
            self.assertEqual("2.1.281 (Claude Code)", verified.version)
            self.assertNotEqual(str(real.resolve()), verified.path)
            for resolver, runner in (
                (lambda _name: str(stub), run("2.1.281 (Claude Code)")),
                (lambda _name: str(lookalike), run("2.1.281 (Claude Code)")),
                (lambda _name: str(real), run("9.9.9 (Claude Code)")),
                (lambda _name: str(real), run("2.1.281 (Not Claude)")),
                (lambda _name: None, run("2.1.281 (Claude Code)")),
            ):
                with self.subTest(), self.assertRaises(score_abstention.BinaryError):
                    score_abstention.verify_claude_binary(resolver=resolver, runner=runner)
        self.assertNotIn(str(Path.home()), verified.shown)

    def test_the_probe_writes_no_result_and_charges_nothing(self) -> None:
        results = self.home / "claude-results.json"
        with (
            mock.patch.object(score_abstention, "CLAUDE_SUMMARY_PATH", str(results)),
            mock.patch.object(abstention_ledger, "LEDGER_PATH", str(self.ledger_path)),
            mock.patch.object(
                score_abstention,
                "verify_claude_binary",
                return_value=_VERIFIED,
            ),
            mock.patch.object(score_abstention, "probe_argv", return_value=0) as probe,
            mock.patch("builtins.print"),
        ):
            self.assertEqual(0, score_abstention.main(["--probe-argv"]))
        probe.assert_called_once()
        self.assertEqual("/abs/claude", probe.call_args.args[1])
        self.assertFalse(results.exists())
        self.assertFalse(self.ledger_path.exists())
        self.assertEqual([], list(self.home.glob("*.json")))


class _Proxy:
    """A forwarding proxy that answers as the real model would, and counts what reached it."""

    def __init__(self) -> None:
        import http.server  # noqa: PLC0415
        import threading  # noqa: PLC0415

        hits: list[str] = []
        self.hits = hits

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("content-length") or 0))
                hits.append(self.path)
                body = json.dumps({"content": [{"type": "text", "text": "ok"}]}).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: Any) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


# The probe runs only where `reading_route.destination` names its stub, and on
# Windows that names nothing (SECURITY.md, "or the machine is Windows"), so
# every pass refuses before the CLI runs. What it would print there cannot be
# asserted; `test_on_windows_the_probe_refuses_before_running_anything` pins
# the refusal itself on every platform.
_NAMES_A_DESTINATION = unittest.skipIf(
    sys.platform == "win32", "reading_route names no destination on Windows, so the probe refuses"
)


class DRC4710TheProbeCannotReachARealModelTest(unittest.TestCase):
    """DRC-4710 V5: `--probe-argv` accepted any loopback address, a forwarding proxy included.

    Refused, not charged: the probe points the CLI at a stub it starts itself,
    strips every variable that could move the call, and counts the probe good
    only when the reply carries a nonce that only its own stub knows.
    """

    def setUp(self) -> None:
        self.proxy = _Proxy()
        self.addCleanup(self.proxy.close)
        # The operator's own configuration: every route a call could take elsewhere.
        self.operator = {
            "HOME": str(Path.home()),
            "PATH": os.environ.get("PATH", ""),
            "ANTHROPIC_BASE_URL": self.proxy.url,
            "HTTPS_PROXY": self.proxy.url,
            "https_proxy": self.proxy.url,
            "ANTHROPIC_API_KEY": "PLACEHOLDER-operator-key",
            "ANTHROPIC_AUTH_TOKEN": "PLACEHOLDER-token",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_OAUTH_TOKEN": "PLACEHOLDER-operator-oauth",
            "CLAUDE_CONFIG_DIR": str(Path(tempfile.mkdtemp(), "operator-config")),
            "CLAUDE_CODE_HTTPS_PROXY": self.proxy.url,
            "CLAUDE_CODE_HTTP_PROXY": self.proxy.url,
            "CLAUDE_CODE_PROXY_URL": self.proxy.url,
            "ALL_PROXY": self.proxy.url,
        }
        self.seen: list[dict[str, Any]] = []
        self.printed: list[str] = []

    @staticmethod
    def account(env: dict[str, str]) -> dict[str, str]:
        path = Path(env.get("CLAUDE_CONFIG_DIR", "/nonexistent"), ".claude.json")
        if not path.is_file():
            return {}
        account: dict[str, str] = json.loads(path.read_text()).get("oauthAccount") or {}
        return account

    def cli(
        self, *, obeys: bool = True, adds: str = "", leak: str = "", header_leak: bool = False
    ) -> Any:
        """A fake Claude Code CLI: posts one Messages request and prints the reply text."""
        import urllib.request  # noqa: PLC0415

        def run(command: list[str], **kwargs: Any) -> Any:
            env = kwargs["env"]
            self.seen.append({"command": list(command), "env": dict(env)})
            base = (
                env.get("ANTHROPIC_BASE_URL", "") if obeys else self.operator["ANTHROPIC_BASE_URL"]
            )
            system = command[command.index("--system-prompt") + 1] + adds
            messages: list[dict[str, Any]] = [{"role": "user", "content": kwargs["input"]}]
            account = self.account(env)
            headers = {"content-type": "application/json"}
            user_id = {"device_id": "d" * 64, "account_uuid": "", "session_id": "s"}
            if account and "ANTHROPIC_API_KEY" not in env:
                # What 2.1.283 adds under OAuth sign-in, as the review measured.
                messages[0]["content"] = (
                    "<system-reminder>\n# userEmail\nThe user's email address is "
                    f"{account['emailAddress']}. Use it only to identify the user.\n"
                    f"</system-reminder>\n{kwargs['input']}"
                )
                user_id["account_uuid"] = account["accountUuid"]
                system += leak.replace("EMAIL", account["emailAddress"])
                if header_leak:
                    headers["x-probe-account"] = account["accountUuid"]
            body = json.dumps(
                {
                    "model": observer.CLAUDE_READING_MODEL,
                    "system": [{"type": "text", "text": system}],
                    "messages": messages,
                    "metadata": {"user_id": json.dumps(user_id)},
                    "stream": False,
                }
            ).encode()
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request = urllib.request.Request(  # noqa: S310 - loopback only
                f"{base}/v1/messages", data=body, headers=headers
            )
            with opener.open(request, timeout=10) as response:
                reply = json.loads(response.read())
            kwargs["stdout"].write(reply["content"][0]["text"].encode())
            self.seen[-1]["account"] = account
            self.seen[-1]["config_left"] = Path(env.get("CLAUDE_CONFIG_DIR", "")).exists()
            return subprocess.CompletedProcess(command, 0)

        return run

    def probe(self, runner: Any) -> int:
        with mock.patch("builtins.print", side_effect=_collect_into(self.printed)):
            return score_abstention.probe_argv(
                _state_config(), "/abs/claude", runner=runner, environ=self.operator
            )

    @_NAMES_A_DESTINATION
    def test_the_cli_is_pointed_only_at_the_probes_own_stub(self) -> None:
        self.assertEqual(0, self.probe(self.cli()), self.printed)
        self.assertEqual([], self.proxy.hits)
        env = self.seen[0]["env"]
        self.assertTrue(env["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:"))
        self.assertNotEqual(self.proxy.url, env["ANTHROPIC_BASE_URL"])
        for gone in (
            "HTTPS_PROXY",
            "https_proxy",
            "ALL_PROXY",
            "ANTHROPIC_AUTH_TOKEN",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_HTTPS_PROXY",
            "CLAUDE_CODE_HTTP_PROXY",
            "CLAUDE_CODE_PROXY_URL",
        ):
            for index in (0, 1):
                with self.subTest(gone=gone, index=index):
                    self.assertNotIn(gone, self.seen[index]["env"])
        self.assertNotEqual(self.operator["ANTHROPIC_API_KEY"], env["ANTHROPIC_API_KEY"])
        said = "\n".join(self.printed)
        self.assertIn("argv carries --system-prompt: yes", said)
        self.assertIn("request carries the fixed instruction: yes", said)
        self.assertIn("request names the home directory: no", said)

    @_NAMES_A_DESTINATION
    def test_the_probe_also_runs_signed_in_with_a_placeholder_account(self) -> None:
        # Owner ruling of 2026-09-27 on Sent F1: under OAuth the CLI adds the
        # account's email and UUID. Accepted and disclosed, and measured on a
        # placeholder account the probe makes, never the operator's.
        self.assertEqual(0, self.probe(self.cli()), self.printed)
        self.assertEqual(2, len(self.seen))
        api, oauth = self.seen[0]["env"], self.seen[1]["env"]
        self.assertIn("ANTHROPIC_API_KEY", api)
        self.assertNotIn("ANTHROPIC_API_KEY", oauth)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN", oauth)
        self.assertNotEqual(
            self.operator["CLAUDE_CODE_OAUTH_TOKEN"], oauth["CLAUDE_CODE_OAUTH_TOKEN"]
        )
        self.assertNotEqual(self.operator["CLAUDE_CONFIG_DIR"], oauth["CLAUDE_CONFIG_DIR"])
        account = self.seen[1]["account"]
        self.assertTrue(account["emailAddress"].endswith("@example.invalid"))
        self.assertRegex(account["accountUuid"], r"^[0-9a-f-]{36}$")
        self.assertFalse(
            Path(oauth["CLAUDE_CONFIG_DIR"]).exists(), "the placeholder account stayed"
        )
        said = "\n".join(self.printed)
        self.assertIn("api-key sign-in", said)
        self.assertIn("OAuth sign-in", said)
        self.assertIn("request carries the account's email in the disclosed block: yes", said)
        self.assertIn("request names the account's email or UUID anywhere else: no", said)
        self.assertNotIn(account["emailAddress"], said)
        self.assertNotIn("none anywhere else", said)

    @_NAMES_A_DESTINATION
    def test_the_account_email_beyond_the_disclosed_block_fails_the_probe(self) -> None:
        self.assertEqual(1, self.probe(self.cli(leak=" signed in as EMAIL")))
        self.assertIn(
            "request names the account's email or UUID anywhere else: yes", "\n".join(self.printed)
        )

    @_NAMES_A_DESTINATION
    def test_the_home_or_user_name_in_another_case_fails_the_probe(self) -> None:
        # Review N1: the CLI fixes the case of the path it names, so a
        # case-sensitive needle printed "user name: no" over a leak.
        home = abstention_ledger.real_home()
        for label, text in (
            ("home", home.upper()),
            ("user", "/private/tmp/" + os.path.basename(home.rstrip(os.sep)).upper() + "-x"),
        ):
            with self.subTest(label=label):
                self.seen.clear()
                self.printed.clear()
                self.assertEqual(1, self.probe(self.cli(adds=" " + text)))

    @_NAMES_A_DESTINATION
    def test_the_account_uuid_in_a_header_fails_the_probe(self) -> None:
        self.assertEqual(1, self.probe(self.cli(header_leak=True)))

    @_NAMES_A_DESTINATION
    def test_a_reply_from_elsewhere_is_refused_even_when_the_stub_was_also_called(self) -> None:
        # From the scoring lens's killers (K2): a real model's answer to the
        # probe's sentence is "ok", so only the nonce tells the two apart.
        import urllib.request  # noqa: PLC0415

        def run(command: list[str], **kwargs: Any) -> Any:
            env = kwargs["env"]
            system = command[command.index("--system-prompt") + 1]
            body = json.dumps({"model": "m", "system": [{"type": "text", "text": system}],
                               "messages": [{"role": "user", "content": "x"}],
                               "stream": False}).encode()  # fmt: skip
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for base in (env["ANTHROPIC_BASE_URL"], self.proxy.url):
                request = urllib.request.Request(  # noqa: S310 - loopback only
                    f"{base}/v1/messages", data=body, headers={"content-type": "application/json"}
                )
                with opener.open(request, timeout=10) as response:
                    reply = json.loads(response.read())
            kwargs["stdout"].write(reply["content"][0]["text"].encode())
            return subprocess.CompletedProcess(command, 0)

        self.assertEqual(2, self.probe(run))

    def test_every_route_variable_is_stripped(self) -> None:
        # From the scoring lens's killers (K4), with the CLI's own proxy names.
        env = score_abstention.probe_environment(
            {
                "CLAUDE_CODE_CUSTOM_OAUTH_URL": "https://x",
                "ALL_PROXY": "http://p",
                "all_proxy": "http://p",
                "CLAUDE_CODE_HTTPS_PROXY": "http://p",
                "CLAUDE_CODE_OAUTH_TOKEN": "PLACEHOLDER",
                "CLAUDE_CONFIG_DIR": "/operator",
                "PATH": "/bin",
            },
            "127.0.0.1:1",
        )
        for gone in (
            "CLAUDE_CODE_CUSTOM_OAUTH_URL",
            "ALL_PROXY",
            "all_proxy",
            "CLAUDE_CODE_HTTPS_PROXY",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "CLAUDE_CONFIG_DIR",
        ):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, env)
        self.assertEqual("1", env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"])

    @_NAMES_A_DESTINATION
    def test_a_reply_that_did_not_come_from_the_stub_is_refused(self) -> None:
        # A CLI that reached the operator's proxy anyway: the real model's
        # answer cannot carry the nonce, so the probe says so and passes nothing.
        self.assertEqual(2, self.probe(self.cli(obeys=False)))
        self.assertEqual(1, len(self.proxy.hits))
        self.assertIn("Refused", "\n".join(self.printed))

    def test_a_destination_other_than_the_stub_runs_nothing(self) -> None:
        runner = mock.Mock(side_effect=AssertionError("ran"))
        with mock.patch("compass_runtime.reading_route.destination", return_value="Anthropic"):
            self.assertEqual(2, self.probe(runner))
        runner.assert_not_called()

    def test_on_windows_the_probe_refuses_before_running_anything(self) -> None:
        # What the Windows runner measured on PR #416: the route names nothing
        # there, so the probe says so and the CLI never starts.
        runner = mock.Mock(side_effect=AssertionError("ran"))
        with mock.patch("compass_runtime.reading_route.platform.system", return_value="Windows"):
            self.assertEqual(2, self.probe(runner))
        runner.assert_not_called()
        self.assertEqual(
            ["Refused: the CLI would reach an unnamed host, not the probe's stub."], self.printed
        )

    @_NAMES_A_DESTINATION
    def test_a_request_naming_this_machine_fails_the_probe(self) -> None:
        self.assertEqual(1, self.probe(self.cli(adds=f" cwd {Path.home()}")))
        self.assertIn("request names the home directory: yes", "\n".join(self.printed))


class _InstalledLayout(unittest.TestCase):
    """A file in a patched versions root, and a fake `codesign` and `--version`."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        versions = Path(self.temp.name, "versions")
        versions.mkdir()
        self.binary = versions / "9.9.9"
        self.binary.write_bytes(b"#!/bin/sh\necho '9.9.9 (Claude Code)'\n")
        patch = mock.patch.object(score_abstention, "CLAUDE_VERSIONS_ROOTS", (str(versions),))
        patch.start()
        self.addCleanup(patch.stop)
        self.ran: list[list[str]] = []

    def runner(self, *, signed: bool) -> Any:
        def run(command: list[str], **_kwargs: Any) -> Any:
            self.ran.append(list(command))
            if Path(command[0]).name == "codesign":
                return mock.Mock(returncode=0 if signed else 1, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="9.9.9 (Claude Code)\n", stderr="")

        return run

    def verify(self, platform: str, *, signed: bool) -> score_abstention.VerifiedClaude:
        verified = score_abstention.verify_claude_binary(
            resolver=lambda _name: str(self.binary),
            runner=self.runner(signed=signed),
            platform=platform,
        )
        self.addCleanup(verified.close)
        return verified


class DRC4731VerifiedPrivateBytesTest(_InstalledLayout):
    """Install-path changes must never select the executable after verification."""

    def test_oversized_source_refuses_before_allocating_a_copy(self) -> None:
        with self.binary.open("wb") as source:
            source.truncate(2 << 20)
        destination = Path(self.temp.name, "oversized-copy")
        with (
            mock.patch.object(score_abstention, "MAX_CLAUDE_COPY_BYTES", 1 << 20, create=True),
            self.assertRaises(score_abstention.BinaryError),
        ):
            score_abstention._copy_claude(str(self.binary), str(destination))
        self.assertFalse(destination.exists())

    def test_growing_source_cannot_write_past_the_copy_limit(self) -> None:
        self.binary.write_bytes(b"x" * (1 << 19))
        destination = Path(self.temp.name, "growing-copy")
        native_open = score_abstention._open_cli
        source_path = self.binary

        class GrowingStream:
            def __init__(self, stream: Any) -> None:
                self.stream = stream
                self.grew = False

            def __enter__(self) -> Any:
                self.stream.__enter__()
                return self

            def __exit__(self, *exc: object) -> None:
                self.stream.__exit__(*exc)

            def fileno(self) -> int:
                return int(self.stream.fileno())

            def read(self, count: int) -> bytes:
                if not self.grew:
                    with source_path.open("ab") as source:
                        source.write(b"y" * (1 << 20))
                    self.grew = True
                return bytes(self.stream.read(count))

        def opened(path: str) -> GrowingStream:
            return GrowingStream(native_open(path))

        with (
            mock.patch.object(score_abstention, "MAX_CLAUDE_COPY_BYTES", 1 << 20, create=True),
            mock.patch.object(score_abstention, "_open_cli", side_effect=opened),
            self.assertRaises(score_abstention.BinaryError),
        ):
            score_abstention._copy_claude(str(self.binary), str(destination))
        self.assertLessEqual(destination.stat().st_size, 1 << 20)

    def test_signature_and_version_execute_only_an_owner_private_copy(self) -> None:
        verified = self.verify("darwin", signed=True)
        self.assertNotEqual(str(self.binary.resolve()), verified.path)
        copied = Path(verified.path)
        self.assertEqual(self.binary.read_bytes(), copied.read_bytes())
        if os.name != "nt":  # POSIX modes; Windows uses profile ACLs/read-only attributes.
            self.assertEqual(0o700, copied.parent.stat().st_mode & 0o777)
            self.assertEqual(0o500, copied.stat().st_mode & 0o777)
        self.assertEqual(verified.path, self.ran[0][-1])
        self.assertEqual([verified.path, "--version"], self.ran[1])
        installed = self.binary.resolve()
        shown = (
            "~/" + installed.relative_to(Path.home()).as_posix()
            if installed.is_relative_to(Path.home())
            else str(installed)
        )
        self.assertEqual(shown, verified.shown)
        verified.close()
        self.assertFalse(copied.parent.exists())

    def test_install_swap_after_copy_does_not_replace_the_version_executable(self) -> None:
        original = self.binary.read_bytes()

        def run(command: list[str], **_kwargs: Any) -> Any:
            if Path(command[0]).name == "codesign":
                self.binary.write_bytes(b"replacement install bytes")
                return mock.Mock(returncode=0, stdout="", stderr="")
            self.assertNotEqual(str(self.binary.resolve()), command[0])
            self.assertEqual(original, Path(command[0]).read_bytes())
            return mock.Mock(returncode=0, stdout="9.9.9 (Claude Code)\n", stderr="")

        verified = score_abstention.verify_claude_binary(
            resolver=lambda _name: str(self.binary), runner=run, platform="darwin"
        )
        self.addCleanup(verified.close)
        self.assertEqual(original, Path(verified.path).read_bytes())

    @unittest.skipIf(os.name == "nt", "controlled POSIX helper, not an authentic CLI measurement")
    def test_a_reading_executes_verified_bytes_after_the_install_is_rewritten(self) -> None:
        self.binary.write_bytes(
            b'#!/bin/sh\nif [ "$1" = "--version" ]; then\n'
            b"printf '9.9.9 (Claude Code)\\n'\nelse\nprintf 'verified-reading'\nfi\n"
        )
        config = _state_config()
        self.addCleanup(shutil.rmtree, config.state_home, True)
        with score_abstention.verify_claude_binary(
            resolver=lambda _name: str(self.binary), platform="linux"
        ) as verified:
            self.binary.write_bytes(b"#!/bin/sh\nprintf 'replacement-reading'\n")
            model = reading.ClaudeReadingModel(
                config,
                binary_resolver=score_abstention.PinnedClaude(verified.path, verified.identity),
            )
            self.assertEqual(("verified-reading", "ok"), model("synthetic", output_cap_bytes=64))
        self.assertFalse(Path(verified.path).exists())

    def test_signature_refusal_removes_the_private_copy(self) -> None:
        with self.assertRaises(score_abstention.BinaryError):
            self.verify("darwin", signed=False)
        self.assertEqual(1, len(self.ran))
        self.assertFalse(Path(self.ran[0][-1]).parent.exists())

    def test_version_refusal_removes_the_private_copy(self) -> None:
        paths: list[Path] = []

        def runner(command: list[str], **_kwargs: Any) -> Any:
            paths.append(Path(command[0]))
            return mock.Mock(returncode=0, stdout="8.8.8 (Claude Code)", stderr="")

        with self.assertRaises(score_abstention.BinaryError):
            score_abstention.verify_claude_binary(
                resolver=lambda _name: str(self.binary), runner=runner, platform="linux"
            )
        self.assertEqual(1, len(paths))
        self.assertFalse(paths[0].parent.exists())

    def interrupted_verification_cleans(self, phase: str) -> None:
        root = Path(self.temp.name, "copies")
        root.mkdir()
        for error in (KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(phase=phase, interruption=type(error).__name__):

                def runner(
                    command: list[str], *, interruption: BaseException = error, **_kwargs: Any
                ) -> Any:
                    signature = Path(command[0]).name == "codesign"
                    if signature == (phase == "signature"):
                        raise interruption
                    return subprocess.CompletedProcess(
                        command, 0, stdout="9.9.9 (Claude Code)\n", stderr=""
                    )

                with (
                    mock.patch.object(observer, "reading_workdir_root", return_value=str(root)),
                    self.assertRaises(type(error)) as interrupted,
                ):
                    score_abstention.verify_claude_binary(
                        resolver=lambda _name: str(self.binary), runner=runner, platform="darwin"
                    )
                self.assertIs(error, interrupted.exception)
                self.assertEqual([], list(root.iterdir()), "interrupted verification left its copy")

    def test_signature_interruption_removes_the_private_copy(self) -> None:
        self.interrupted_verification_cleans("signature")

    def test_version_interruption_removes_the_private_copy(self) -> None:
        self.interrupted_verification_cleans("version")

    def test_cleanup_removes_a_copy_on_a_host_that_denies_read_only_deletion(self) -> None:
        verified = self.verify("linux", signed=False)
        copied = Path(verified.path)
        native = shutil.rmtree

        def readonly_sensitive(path: str, **kwargs: Any) -> None:
            if copied.exists() and not copied.stat().st_mode & 0o200:
                return  # The Windows read-only attribute makes ignore_errors leave the file.
            native(path, **kwargs)

        with mock.patch.object(shutil, "rmtree", side_effect=readonly_sensitive):
            verified.close()
        self.assertFalse(copied.parent.exists())

    def test_a_source_change_while_copying_refuses_before_any_executable_runs(self) -> None:
        native = os.fdopen

        class SourceStream:
            def __init__(self, stream: Any) -> None:
                self.stream = stream
                self.changed = False

            def __enter__(self) -> Any:
                return self

            def __exit__(self, *_exc: object) -> None:
                self.stream.close()

            def fileno(self) -> int:
                return int(self.stream.fileno())

            def read(inner, count: int) -> bytes:  # noqa: N805 - enclosing test owns `self`
                block: bytes = inner.stream.read(count)
                if not inner.changed:
                    self.binary.write_bytes(b"source changed during held-handle copy")
                    inner.changed = True
                return block

        def opened(descriptor: int, mode: str) -> Any:
            return SourceStream(native(descriptor, mode))

        with (
            mock.patch.object(os, "fdopen", side_effect=opened),
            self.assertRaises(score_abstention.BinaryError),
        ):
            self.verify("darwin", signed=True)
        self.assertEqual([], self.ran)

    @unittest.skipIf(os.name == "nt", "POSIX FIFO and nonblocking file open")
    def test_a_fifo_in_the_install_layout_refuses_within_the_local_bound(self) -> None:
        self.binary.unlink()
        os.mkfifo(self.binary, 0o600)
        code = (
            "import sys; sys.path.insert(0, sys.argv[3]); import score_abstention as s; "
            "s.CLAUDE_VERSIONS_ROOTS=(sys.argv[2],); "
            "\ndef runner(*a,**kw): raise AssertionError('an executable ran')"
            "\ntry: s.verify_claude_binary(resolver=lambda _:sys.argv[1],runner=runner)"
            "\nexcept s.BinaryError: sys.exit(0)"
            "\nraise AssertionError('FIFO was accepted')"
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(self.binary),
                str(self.binary.parent),
                str(ROOT / "scripts"),
            ],
            capture_output=True,
            timeout=2,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr.decode())

    def test_a_private_identity_read_detects_a_change_during_hashing(self) -> None:
        native = os.fstat
        reads = 0

        class ChangedStat:
            def __init__(self, value: os.stat_result) -> None:
                self.value = value

            def __getattr__(self, name: str) -> Any:
                return getattr(self.value, name) + (1 if name == "st_ctime_ns" else 0)

        def changed(fd: int) -> Any:
            nonlocal reads
            reads += 1
            value = native(fd)
            return ChangedStat(value) if reads > 2 else value

        with mock.patch.object(os, "fstat", side_effect=changed), self.assertRaises(OSError):
            score_abstention.file_identity(str(self.binary))


class DRC4731PreparationBeforeChargeTest(unittest.TestCase):
    """Local refusal creates no charged row, even when the binary resolves."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = _state_config()
        self.addCleanup(shutil.rmtree, self.config.state_home, True)
        self.ledger_path = Path(self.temp.name, "ledger.json")
        self.ledger = abstention_ledger.Ledger(
            path=str(self.ledger_path),
            cap=19,
            marks_digest="a" * 64,
            inputs_digest="b" * 64,
            producer="claude",
        )
        self.runs: list[str] = []

        def runner(command: list[str], **kwargs: Any) -> Any:
            self.runs.append(command[0])
            kwargs["stdout"].write(b"{}")
            return subprocess.CompletedProcess(command, 0)

        self.model = reading.ClaudeReadingModel(
            self.config, runner=runner, binary_resolver=lambda _name: "/synthetic/claude"
        )

    def refused(self) -> None:
        charged = score_abstention._Charged(self.ledger, "c" * 16, self.model)
        try:
            result = charged("prompt", output_cap_bytes=32)
        except (KeyError, OSError) as error:
            self.fail(f"local preparation escaped instead of refusing: {error}")
        self.assertEqual([], self.runs)
        self.assertFalse(self.ledger_path.exists(), "preparation spent a model call")
        self.assertEqual(("", "failed"), result)

    @unittest.skipIf(os.name == "nt", "password database is POSIX")
    def test_missing_password_database_entry_refuses_without_a_charge(self) -> None:
        with mock.patch.object(observer, "_account", side_effect=KeyError("no account")):
            self.refused()

    @unittest.skipIf(os.name == "nt", "password database is POSIX")
    def test_root_home_refuses_without_a_charge(self) -> None:
        with mock.patch.object(observer, "_account", return_value=("/", "root")):
            self.refused()

    def test_unwritable_private_workdir_refuses_without_a_charge(self) -> None:
        with mock.patch.object(tempfile, "mkdtemp", side_effect=PermissionError("no")):
            self.refused()

    def test_unwritable_output_directory_refuses_without_a_charge(self) -> None:
        native = tempfile.mkstemp

        def mkstemp(**kwargs: Any) -> tuple[int, str]:
            if kwargs.get("prefix") == "reading-claude-":
                raise PermissionError("no")
            return native(**kwargs)

        with mock.patch.object(tempfile, "mkstemp", side_effect=mkstemp):
            self.refused()

    def test_failed_output_stream_creation_closes_the_raw_descriptor(self) -> None:
        native = tempfile.mkstemp
        descriptors: list[int] = []

        def mkstemp(**kwargs: Any) -> tuple[int, str]:
            descriptor, path = native(**kwargs)
            if kwargs.get("prefix") == "reading-claude-":
                descriptors.append(descriptor)
            return descriptor, path

        with (
            mock.patch.object(tempfile, "mkstemp", side_effect=mkstemp),
            mock.patch.object(os, "fdopen", side_effect=OSError("cannot open stream")),
        ):
            self.refused()
        self.assertEqual(1, len(descriptors))
        try:
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])
        finally:
            with contextlib.suppress(OSError):
                os.close(descriptors[0])

    def interrupted_preparation_cleans(self, phase: str) -> None:
        root = Path(self.temp.name, "cwd")
        root.mkdir()
        native = tempfile.mkstemp
        for error in (KeyboardInterrupt(), SystemExit(7)):
            with self.subTest(phase=phase, interruption=type(error).__name__):
                descriptors: list[int] = []

                def mkstemp(
                    *,
                    interruption: BaseException = error,
                    captured: list[int] = descriptors,
                    **kwargs: Any,
                ) -> tuple[int, str]:
                    if phase == "output":
                        raise interruption
                    descriptor, path = native(**kwargs)
                    captured.append(descriptor)
                    return descriptor, path

                try:
                    with (
                        mock.patch.object(observer, "reading_workdir_root", return_value=str(root)),
                        mock.patch.object(tempfile, "mkstemp", side_effect=mkstemp),
                        mock.patch.object(os, "fdopen", side_effect=error),
                        self.assertRaises(type(error)) as interrupted,
                    ):
                        score_abstention._Charged(self.ledger, "c" * 16, self.model)(
                            "prompt", output_cap_bytes=32
                        )
                    self.assertIs(error, interrupted.exception)
                    self.assertEqual([], self.runs)
                    self.assertFalse(self.ledger_path.exists(), "interruption charged a model call")
                    for descriptor in descriptors:
                        with self.assertRaises(OSError):
                            os.fstat(descriptor)
                    self.assertEqual([], list(root.iterdir()), "interruption left a private cwd")
                    self.assertEqual([], list(self.config.state_dir.iterdir()))
                finally:
                    for descriptor in descriptors:
                        with contextlib.suppress(OSError):
                            os.close(descriptor)

    def test_output_allocation_interruption_removes_the_private_cwd(self) -> None:
        self.interrupted_preparation_cleans("output")

    def test_stream_open_interruption_closes_the_descriptor_and_removes_private_files(self) -> None:
        self.interrupted_preparation_cleans("stream")

    def test_prepared_files_are_removed_when_the_ledger_refuses(self) -> None:
        with (
            mock.patch.object(
                self.ledger, "charge", side_effect=abstention_ledger.LedgerError("locked")
            ),
            self.assertRaises(abstention_ledger.LedgerError),
        ):
            score_abstention._Charged(self.ledger, "c" * 16, self.model)(
                "prompt", output_cap_bytes=32
            )
        self.assertEqual([], list(self.config.state_dir.iterdir()))
        self.assertEqual([], self.runs)

    def test_success_charges_once_after_private_files_exist(self) -> None:
        charged = score_abstention._Charged(self.ledger, "c" * 16, self.model)
        self.assertEqual(("{}", "ok"), charged("prompt", output_cap_bytes=32))
        self.assertEqual(["/synthetic/claude"], self.runs)
        calls = abstention_ledger.read(str(self.ledger_path))["calls"]
        self.assertEqual(1, len(calls))
        self.assertEqual("ok", calls[0]["status"])
        self.assertEqual([], list(self.config.state_dir.iterdir()))


class DRC4731CodeSensitiveParserStampTest(unittest.TestCase):
    """The stamp ignores layout, while changed derivation still invalidates packets."""

    def setUp(self) -> None:
        self.actual_parser_files = mark_abstention._PARSER_FILES
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        runtime = Path(self.temp.name, "compass_runtime")
        runtime.mkdir()
        self.parser = runtime / "sample.py"
        patch = mock.patch.multiple(
            mark_abstention, _SKILL=self.temp.name, _PARSER_FILES=("sample.py",)
        )
        patch.start()
        self.addCleanup(patch.stop)

    def stamp(self, source: str) -> str:
        self.parser.write_text(source)
        return mark_abstention.parser_digest()

    def test_comments_and_formatting_keep_the_same_stamp(self) -> None:
        first = self.stamp("def derive(row):\n    return row.get('result', 0)\n")
        second = self.stamp(
            "# prose changed\ndef derive( row ):\n\n    # another comment\n"
            '    return row.get( "result", 0 )\n'
        )
        self.assertEqual(first, second)

    def test_changed_derivation_invalidates_the_stamp(self) -> None:
        first = self.stamp("def derive(row):\n    return row.get('result', 0)\n")
        second = self.stamp("def derive(row):\n    return row.get('result', 1)\n")
        self.assertNotEqual(first, second)

    def test_shared_byte_reader_change_invalidates_a_frozen_packet(self) -> None:
        runtime = Path(self.temp.name, "compass_runtime")
        for name in ("project_context.py", "reading.py", "io.py"):
            shutil.copy2(SKILL / "compass_runtime" / name, runtime / name)
        with mock.patch.object(mark_abstention, "_PARSER_FILES", self.actual_parser_files):
            before = mark_abstention.parser_digest()
            with (runtime / "io.py").open("a") as handle:
                handle.write("\nDERIVATION_PROBE = 1\n")
            after = mark_abstention.parser_digest()
        self.assertNotEqual(before, after)


class DRC4710TheCliIsBoundByItsSignatureTest(_InstalledLayout):
    """DRC-4710 V4: a stub saved in the install layout was recorded as Anthropic's CLI."""

    def test_on_macos_a_stub_in_the_install_layout_is_refused_before_it_runs(self) -> None:
        with self.assertRaises(score_abstention.BinaryError):
            self.verify("darwin", signed=False)
        self.assertEqual(["codesign"], [Path(c[0]).name for c in self.ran])

    def test_on_macos_the_pinned_team_and_identifier_are_required(self) -> None:
        signature = self.verify("darwin", signed=True).signature
        codesign = self.ran[0]
        self.assertEqual("/usr/bin/codesign", codesign[0])
        self.assertIn("--strict", codesign)
        requirement = codesign[codesign.index("-R") + 1]
        self.assertIn('certificate leaf[subject.OU] = "Q6L2SF6YDW"', requirement)
        self.assertIn('identifier "com.anthropic.claude-code"', requirement)
        self.assertIn("anchor apple generic", requirement)
        self.assertNotEqual(str(self.binary.resolve()), codesign[-1])
        self.assertEqual("Developer ID Q6L2SF6YDW com.anthropic.claude-code", signature)
        self.assertEqual("--version", self.ran[1][1])

    def test_on_macos_without_codesign_the_run_is_refused(self) -> None:
        def missing(command: list[str], **_kwargs: Any) -> Any:
            if Path(command[0]).name == "codesign":
                raise FileNotFoundError(command[0])
            return mock.Mock(returncode=0, stdout="9.9.9 (Claude Code)\n")

        with self.assertRaises(score_abstention.BinaryError):
            score_abstention.verify_claude_binary(
                resolver=lambda _name: str(self.binary), runner=missing, platform="darwin"
            )

    def test_elsewhere_no_signature_is_checked_and_the_hash_is_recorded(self) -> None:
        digest = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        for platform in ("linux", "win32"):
            with self.subTest(platform=platform):
                self.ran.clear()
                signature = self.verify(platform, signed=False).signature
                self.assertEqual(f"unchecked sha256:{digest}", signature)
                self.assertNotIn("codesign", [Path(c[0]).name for c in self.ran])


class DRC4710TheVerifiedFileIsTheOneThatRunsTest(_InstalledLayout):
    """Sent F4 and Codex 1: the pin was checked once on a path, then that path ran 19 times.

    The smaller sound option: the verified file's identity (device, inode,
    size, mtime, ctime and sha256) is recorded at the check and compared before
    every call, and a call on a changed file is refused.
    """

    def test_the_identity_is_recorded_at_the_check(self) -> None:
        verified = self.verify("darwin", signed=True)
        # From a handle, as `file_identity` reads it, and not by path: CPython
        # 3.12 on Windows gives `os.stat` the creation time as `st_ctime` and
        # `os.fstat` the change time, which differ whenever the write lands a
        # clock tick after the create (DRC-4707, PR #419 run 36359883058).
        with open(verified.path, "rb") as handle:
            stat = os.fstat(handle.fileno())
        self.assertEqual(
            (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
             hashlib.sha256(self.binary.read_bytes()).hexdigest()),
            verified.identity,
        )  # fmt: skip

    def test_a_file_swapped_after_the_check_is_refused_before_the_call(self) -> None:
        verified = self.verify("darwin", signed=True)
        pinned = score_abstention.PinnedClaude(verified.path, verified.identity)
        with mock.patch("builtins.print"):
            self.assertEqual(verified.path, pinned("claude"))
            copied = Path(verified.path)
            if os.name == "nt":
                copied.chmod(0o700)  # Windows cannot replace a read-only destination.
            replacement = copied.with_name("swap")
            replacement.write_bytes(b"#!/bin/sh\necho stub\n")
            os.replace(replacement, copied)
            self.assertIsNone(pinned("claude"))
            self.assertIsNone(pinned("claude"), "a refusal is not undone by the next call")

    def test_a_file_rewritten_in_place_is_refused(self) -> None:
        verified = self.verify("darwin", signed=True)
        pinned = score_abstention.PinnedClaude(verified.path, verified.identity)
        copied = Path(verified.path)
        copied.chmod(0o700)
        original = copied.read_bytes()
        with mock.patch("builtins.print"):
            with copied.open("r+b") as handle:
                handle.write(b"X")
            self.assertIsNone(pinned("claude"))
        fresh = score_abstention.PinnedClaude(verified.path, verified.identity)
        copied.write_bytes(original)
        stat = copied.stat()
        os.utime(copied, ns=(stat.st_atime_ns, verified.identity[3]))
        with mock.patch("builtins.print"):
            # Review N2: identical bytes and mtime no longer pass, because
            # the write moved the inode's ctime, which `os.utime` cannot set.
            self.assertIsNone(fresh("claude"), "restored bytes and mtime still moved ctime")

    def test_a_swap_and_swap_back_during_verification_is_refused(self) -> None:
        # Review N2: a runner swapped a signed copy in for `codesign` and the
        # original back after `--version`. Device, inode, size, mtime and
        # bytes all matched; only the inode's change time moved, as a rename
        # away and back does on APFS. The fake stands in for that rename.
        real_fstat = os.fstat
        moved = {"on": False}

        class _Stat:
            def __init__(self, inner: os.stat_result) -> None:
                self._inner = inner

            def __getattr__(self, name: str) -> Any:
                value = getattr(self._inner, name)
                return value + 1 if name == "st_ctime_ns" and moved["on"] else value

        def fstat(fd: int) -> Any:
            return _Stat(real_fstat(fd))

        def run(command: list[str], **_kwargs: Any) -> Any:
            if Path(command[0]).name == "codesign":
                moved["on"] = True
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="9.9.9 (Claude Code)\n", stderr="")

        with (
            mock.patch.object(os, "fstat", fstat),
            self.assertRaises(score_abstention.BinaryError),
        ):
            score_abstention.verify_claude_binary(
                resolver=lambda _name: str(self.binary), runner=run, platform="darwin"
            )

    def test_a_file_changed_between_the_signature_and_the_version_is_refused(self) -> None:
        def run(command: list[str], **_kwargs: Any) -> Any:
            if Path(command[0]).name == "codesign":
                copied = Path(command[-1])
                copied.chmod(0o700)
                copied.write_bytes(b"#!/bin/sh\necho '9.9.9 (Claude Code)' # swapped\n")
                return mock.Mock(returncode=0, stdout="", stderr="")
            return mock.Mock(returncode=0, stdout="9.9.9 (Claude Code)\n", stderr="")

        with self.assertRaises(score_abstention.BinaryError):
            score_abstention.verify_claude_binary(
                resolver=lambda _name: str(self.binary), runner=run, platform="darwin"
            )


class TheApprovedWordingIsPinnedTest(unittest.TestCase):
    """From the scoring lens's killers (K3): the sentence the owner approves is this one."""

    def test_the_system_prompt_is_the_approved_sentence(self) -> None:
        self.assertEqual(
            "You assess a record of an agent's work session against goals a reader wrote. "
            "Use only the text of the user message. Reply with the JSON object it asks for "
            "and nothing else.",
            observer.CLAUDE_READING_SYSTEM_PROMPT,
        )


class _RecordedCaseFixture(unittest.TestCase):
    """A Claude Code transcript under a scratch projects root, and a freeze over it."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name, "projects")
        self.start = dt.datetime(2026, 9, 24, 3, 0, 0, tzinfo=dt.UTC).timestamp()
        self.config = _state_config()

    def transcript(self, session_id: str = CLAUDE_SID, *, inside: bool = True) -> str:
        folder = self.root / "-w" if inside else Path(self.temp.name, "elsewhere")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{session_id}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in _transcript(self.start, session_id)))
        return str(path)

    def freeze(
        self, transcript: str, observations: list[dict[str, Any]], **entry: Any
    ) -> dict[str, Any]:
        base = {
            "harness": "claude",
            "sid": CLAUDE_SID,
            "project": "p",
            "captured_at": self.start + 30,
            "row": {"state": "idle", "finished_at": self.start + 20},
            "intent": {"goal": GOAL, "lines": [{"text": LINE_ONE}]},
            "transcript": transcript,
            **entry,
        }
        with mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root)):
            return mark_abstention.freeze_case(
                self.config, base, [], observations=observations, ends=[]
            )

    def stop(self, at: float) -> list[dict[str, Any]]:
        return [
            {"harness": "claude", "sid": CLAUDE_SID, "state": "idle", "last_activity": at},
        ]


class Q4OnlyAGenuineCaseIsRecordedTest(_RecordedCaseFixture):
    """F4: a case is recorded only when the machine's own records say so."""

    def test_a_transcript_in_projects_with_its_own_id_and_a_recorded_stop_is_recorded(
        self,
    ) -> None:
        case = self.freeze(self.transcript(), self.stop(self.start + 20))
        self.assertEqual("recorded", case["origin"])
        self.assertEqual([], case["unconfirmed"])

    def test_anything_less_is_synthetic(self) -> None:
        for name, transcript, observations, reason in (
            ("outside", self.transcript(inside=False), self.stop(self.start + 20),
             "transcript-outside-projects"),
            ("other id", self.transcript("zz-other"), self.stop(self.start + 20),
             "transcript-other-session"),
            ("no stop", self.transcript(), [], "lifecycle-unconfirmed"),
            ("other stop", self.transcript(), self.stop(self.start + 19), "lifecycle-unconfirmed"),
        ):  # fmt: skip
            with self.subTest(name=name):
                case = self.freeze(transcript, observations)
                self.assertEqual("synthetic", case["origin"])
                self.assertIn(reason, case["unconfirmed"])

    def test_a_codex_working_case_needs_its_history_observation(self) -> None:
        entry = {
            "harness": "codex",
            "sid": CODEX_SID,
            "project": "p",
            "captured_at": 5000.0,
            "row": {"state": "working"},
            "intent": {"goal": GOAL, "lines": [{"text": LINE_ONE}]},
        }
        seen = {"harness": "codex", "sid": CODEX_SID, "state": "working", "last_activity": 5000.0}
        for observations, origin in (
            ([seen], "recorded"),
            ([], "synthetic"),
            ([{**seen, "last_activity": 4999.0}], "synthetic"),
            ([{**seen, "state": "idle"}], "synthetic"),
        ):
            with self.subTest(observations=observations):
                case = mark_abstention.freeze_case(
                    self.config, entry, [], observations=observations, ends=[]
                )
                self.assertEqual(origin, case["origin"])


class Q4ATurnStopTheHistoryRolledPastIsVouchedByTheTranscriptTest(_RecordedCaseFixture):
    """Owner ruling 2026-10-01 (DRC-4666): the history store is capped and rolls, so a
    turn stop older than its oldest observation is confirmed by the transcript's own
    Stop-hook record instead, and only then."""

    def marked(
        self,
        *,
        at: int = 20,
        sidechain: bool = False,
        prevented: bool = False,
        session_id: str = CLAUDE_SID,
        subtype: str = "stop_hook_summary",
        feedback: bool = False,
    ) -> str:
        path = self.transcript()
        # The reply the turn ended on, then, for a Stop hook that blocked the stop or a goal
        # not met, the `isMeta` feedback that keeps the turn going (verifier S1).
        before = [
            {"type": "assistant", "isSidechain": False, "sessionId": session_id,
             "timestamp": _stamp(self.start, at - 2),
             "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
        ]  # fmt: skip
        if feedback:
            before.append(
                {"type": "user", "isMeta": True, "isSidechain": False, "sessionId": session_id,
                 "timestamp": _stamp(self.start, at - 1),
                 "message": {"role": "user", "content": "Stop hook feedback: not yet"}}
            )  # fmt: skip
        with open(path, "a", encoding="utf-8") as handle:
            handle.writelines("\n" + json.dumps(row) for row in before)
        marker = {
            "type": "system",
            "subtype": subtype,
            "isSidechain": sidechain,
            "preventedContinuation": prevented,
            "sessionId": session_id,
            "timestamp": _stamp(self.start, at),
        }
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n" + json.dumps(marker))
        return path

    def rolled(self) -> list[dict[str, Any]]:
        # Another session's observation, later than the stop: the store no longer reaches it.
        return [
            {
                "harness": "claude",
                "sid": "other-sid",
                "state": "idle",
                "last_activity": self.start + 3600,
            }
        ]

    def test_a_stop_older_than_the_history_store_is_recorded_on_its_stop_hook_record(self) -> None:
        case = self.freeze(self.marked(), self.rolled())
        self.assertEqual("recorded", case["origin"])
        self.assertEqual([], case["unconfirmed"])
        self.assertEqual("transcript", case["lifecycle_from"])

    def test_a_stop_hook_that_ended_the_turn_is_vouched_for(self) -> None:
        # `preventedContinuation: true` is "Stop hook prevented continuation": the turn ended.
        case = self.freeze(self.marked(prevented=True), self.rolled())
        self.assertEqual("transcript", case["lifecycle_from"])

    def test_a_packet_naming_the_boards_short_id_is_vouched_too(self) -> None:
        # Measured 2026-10-01: every Claude case in the real packets names 8 characters.
        case = self.freeze(self.marked(), self.rolled(), sid=CLAUDE_SID[:8])
        self.assertEqual("transcript", case["lifecycle_from"])
        self.assertEqual("recorded", case["origin"])
        shorter = self.freeze(self.marked(), self.rolled(), sid=CLAUDE_SID[:7])
        self.assertIn("lifecycle-unconfirmed", shorter["unconfirmed"])

    def test_a_stop_the_history_store_still_covers_needs_its_observation(self) -> None:
        covering = [{**self.rolled()[0], "last_activity": self.start + 5}]
        case = self.freeze(self.marked(), covering)
        self.assertEqual("synthetic", case["origin"])
        self.assertIn("lifecycle-unconfirmed", case["unconfirmed"])

    def test_an_observed_stop_still_says_it_came_from_the_history_store(self) -> None:
        case = self.freeze(self.marked(), self.stop(self.start + 20))
        self.assertEqual("history", case["lifecycle_from"])

    def test_no_history_at_all_vouches_for_nothing(self) -> None:
        self.assertEqual("synthetic", self.freeze(self.marked(), [])["origin"])

    def test_only_a_top_level_stop_of_this_session_at_that_moment_counts(self) -> None:
        # Built inside the loop: every transcript here shares one path, so a tuple of
        # paths built up front would leave each subtest reading the last one written.
        builds: tuple[tuple[str, Callable[[], str]], ...] = (
            ("no marker", self.transcript),
            ("other moment", lambda: self.marked(at=19)),
            ("sidechain", lambda: self.marked(sidechain=True)),
            ("hook kept it going", lambda: self.marked(feedback=True)),
            ("other session", lambda: self.marked(session_id="zz-other")),
            ("another system record", lambda: self.marked(subtype="turn_duration")),
        )
        for name, build in builds:
            with self.subTest(name=name):
                case = self.freeze(build(), self.rolled())
                self.assertEqual("synthetic", case["origin"])
                self.assertIn("lifecycle-unconfirmed", case["unconfirmed"])

    def test_an_end_or_a_running_row_is_never_vouched_by_the_transcript(self) -> None:
        for row in ({"state": "idle", "ended_at": self.start + 20},
                    {"state": "working"}):  # fmt: skip
            with self.subTest(row=row):
                case = self.freeze(self.marked(), self.rolled(), row=row)
                self.assertIn("lifecycle-unconfirmed", case["unconfirmed"])

    def test_an_older_observation_keeps_the_stop_inside_the_stores_reach(self) -> None:
        # The floor is the OLDEST observation: a newer one alone must not open the fallback.
        both = [*self.rolled(), {**self.rolled()[0], "last_activity": self.start + 5}]
        self.assertIn("lifecycle-unconfirmed", self.freeze(self.marked(), both)["unconfirmed"])

    def test_a_stop_at_the_oldest_observation_is_still_inside_the_stores_reach(self) -> None:
        at_floor = [{**self.rolled()[0], "last_activity": self.start + 20}]
        self.assertIn("lifecycle-unconfirmed", self.freeze(self.marked(), at_floor)["unconfirmed"])

    def test_an_end_or_a_running_row_stays_refused_even_with_a_stop_stamp(self) -> None:
        for row in ({"state": "idle", "finished_at": self.start + 20, "ended_at": self.start + 20},
                    {"state": "working", "finished_at": self.start + 20}):  # fmt: skip
            with self.subTest(row=row):
                case = self.freeze(self.marked(), self.rolled(), row=row)
                self.assertIn("lifecycle-unconfirmed", case["unconfirmed"])

    def test_the_scorer_refuses_a_stop_moved_past_the_capture(self) -> None:
        case = self.freeze(self.marked(), self.rolled())
        moved = {**case, "row_snapshot": {**case["row_snapshot"], "finished_at": self.start + 29}}
        path = self.marked(at=29)
        with mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root)):
            reasons = mark_abstention.provenance(
                moved,
                observations=self.rolled(),
                ends=[],
                index={CLAUDE_SID[:8]: path},
                config=self.config,
            )
        self.assertIn("captured-before-settled", reasons)

    def test_the_scorer_counts_the_stop_it_derived_not_the_one_the_packet_claims(self) -> None:
        for derived, claimed in (("transcript", "history"), ("history", "transcript")):
            with self.subTest(derived=derived):

                def vouch(_case: Any) -> list[str]:
                    return []

                vouch.lifecycle = lambda _case, d=derived: d  # type: ignore[attr-defined]
                case = {"id": "a" * 16, "origin": "recorded", "lifecycle_from": claimed}
                self.assertEqual(derived, score_abstention._vouched(case, vouch)["stop_vouched_by"])

    def test_the_summary_and_report_disclose_a_transcript_vouched_stop(self) -> None:
        recorded = _rubric_record("supported-departure", "claude", {"goal": "correct"})
        recorded["id"] = "a" * 16
        synthetic = {**_rubric_record("legitimate-change", "claude", {"goal": "correct"}),
                     "id": "b" * 16, "origin": "synthetic"}  # fmt: skip
        summary = score_abstention.summarize(
            [], marks={}, marks_bytes=b"", now=1.0, rubric_records=[recorded, synthetic],
            binding=BINDING, transcript_stops={"a" * 16, "b" * 16},
        )  # fmt: skip
        # Only the recorded case counts; a synthetic one never meets the floor anyway.
        self.assertEqual(1, summary["counts"]["recorded_on_transcript_stop"])
        report = "\n".join(score_abstention.render(summary))
        self.assertIn("recorded on a turn stop its transcript vouched for", report)

    def test_the_scorer_repeats_the_same_rule(self) -> None:
        path = self.marked()
        case = self.freeze(path, self.rolled())
        index = {CLAUDE_SID[:8]: path}
        with mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root)):
            vouched = mark_abstention.provenance(
                case, observations=self.rolled(), ends=[], index=index, config=self.config
            )
            covered = mark_abstention.provenance(
                case,
                observations=[{**self.rolled()[0], "last_activity": self.start}],
                ends=[],
                index=index,
                config=self.config,
            )
        self.assertNotIn("lifecycle-unconfirmed", vouched)
        self.assertIn("lifecycle-unconfirmed", covered)


class TheCaptureCutIsTheFirstLineStampedAfterItTest(unittest.TestCase):
    """`capture_prefix` cuts where the check scan cuts (review, DRC-4666)."""

    def cut(self, lines: list[str], captured: float) -> tuple[int, bytes]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, "t.jsonl")
            data = "".join(lines).encode()
            path.write_bytes(data)
            end = mark_abstention.capture_prefix(str(path), captured)
        return end, data[:end]

    def line(self, seconds: int | None, text: str = "x") -> str:
        start = dt.datetime(2026, 9, 24, 3, 0, 0, tzinfo=dt.UTC).timestamp()
        body: dict[str, Any] = {"type": "user", "text": text}
        if seconds is not None:
            body["timestamp"] = _stamp(start, seconds)
        return json.dumps(body) + "\n"

    def at(self, seconds: int) -> float:
        return dt.datetime(2026, 9, 24, 3, 0, 0, tzinfo=dt.UTC).timestamp() + seconds

    def test_unstamped_lines_before_the_next_later_stamp_are_kept(self) -> None:
        lines = [self.line(1), self.line(None, "kept"), self.line(9)]
        _end, kept = self.cut(lines, self.at(5))
        self.assertEqual("".join(lines[:2]).encode(), kept)

    def test_an_earlier_stamp_after_a_later_one_is_not_pulled_in(self) -> None:
        lines = [self.line(1), self.line(9), self.line(3, "out of order")]
        _end, kept = self.cut(lines, self.at(5))
        self.assertEqual(lines[0].encode(), kept)

    def test_a_capture_before_any_stamp_keeps_nothing_and_after_all_keeps_all(self) -> None:
        lines = [self.line(4), self.line(6)]
        self.assertEqual(0, self.cut(lines, self.at(1))[0])
        self.assertEqual(len("".join(lines).encode()), self.cut(lines, self.at(10))[0])


def _asked(start: float, session_id: str, seconds: int = 5) -> dict[str, Any]:
    """A reader's typed turn, in the recorded shape."""
    return {
        "type": "user", "isSidechain": False, "cwd": "/w", "sessionId": session_id,
        "uuid": f"u-{session_id}-{seconds}", "timestamp": _stamp(start, seconds),
        "message": {"role": "user", "content": "ASKED_WORDS make the tests pass"},
    }  # fmt: skip


def _board_facts(config: Any, rows: list[dict[str, Any]], sid: str) -> list[dict[str, Any]]:
    """What the board publishes for these rows' typed turns: its own derivation, as measured.

    Measured 2026-09-27 on a scratch board over the recorded sessions H2,
    1b4a141f and a2364dbf: every non-check fact a Claude Code case carries is
    a `steer` user message, and this rebuild matched the board's ledger rows.
    """
    from compass_runtime import project_context  # noqa: PLC0415

    facts = []
    for row in rows:
        event = project_context._instruction_event(config, row, "claude", sid)
        if event is not None:
            facts.append(
                project_context._semantic_fact_from_event(event, "steer", "user_message", "")
            )
    return facts


class DRC4711TheContentsAreCheckedAgainstTheTranscriptTest(_Packet):
    """DRC-4711: identity alone vouched for a case whose facts were invented."""

    def setUp(self) -> None:
        super().setUp()
        self.root = self.home / "projects"
        self.start = dt.datetime(2026, 9, 24, 3, 0, 0, tzinfo=dt.UTC).timestamp()
        self.config = _state_config()
        self.index: dict[str, str] = {}
        self.stops: list[dict[str, Any]] = []
        patch = mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root))
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, sid: str, asks: tuple[int, ...], extra: tuple[dict[str, Any], ...]) -> Any:
        rows = sorted(
            [*(_asked(self.start, sid, at) for at in asks), *_transcript(self.start, sid), *extra],
            key=lambda row: row["timestamp"],
        )
        folder = self.root / "-w"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{sid}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.index[sid[:8]] = str(path)
        return rows, path

    def genuine(
        self,
        sid: str = CLAUDE_SID,
        *,
        asks: tuple[int, ...] = (5,),
        extra: tuple[dict[str, Any], ...] = (),
        working: bool = False,
    ) -> dict[str, Any]:
        rows, path = self.write(sid, asks, extra)
        captured = self.start + 30
        if working:
            row: dict[str, Any] = {"state": "working"}
            self.stops.append(
                {"harness": "claude", "sid": sid, "state": "working", "last_activity": captured}
            )
        else:
            row = {"state": "idle", "finished_at": self.start + 20}
            self.stops.append(
                {"harness": "claude", "sid": sid, "state": "idle", "last_activity": self.start + 20}
            )
        entry = {
            "harness": "claude",
            "sid": sid,
            "project": "p",
            "captured_at": captured,
            "row": row,
            "intent": {"goal": GOAL, "lines": [{"text": LINE_ONE}]},
            "transcript": str(path),
        }
        case = mark_abstention.freeze_case(
            self.config,
            entry,
            _board_facts(self.config, rows, sid),
            observations=self.stops,
            ends=[],
        )
        self.assertEqual("recorded", case["origin"], case["unconfirmed"])
        copied: dict[str, Any] = json.loads(json.dumps(case))
        return copied

    def vouch(self) -> Any:
        return mark_abstention.make_vouch(
            observations=self.stops, ends=[], index=self.index, config=self.config
        )

    def later_work(self, size: int) -> tuple[dict[str, Any], ...]:
        """Turns appended after the capture, `size` bytes of them, the reader silent."""
        filler = "x" * 2000
        return tuple(
            {"type": "assistant", "isSidechain": False, "cwd": "/w", "sessionId": CLAUDE_SID,
             "timestamp": _stamp(self.start, 100 + index),
             "message": {"role": "assistant", "content": [{"type": "text", "text": filler}]}}
            for index in range(size // 2100 + 1)
        )  # fmt: skip

    def test_a_session_that_ran_on_past_the_boards_tail_keeps_the_readers_words(self) -> None:
        # Measured 2026-10-01: the correction a supported departure rests on sat 750 KB from
        # the end of a transcript whose session ran on, past the board's 400 KB tail.
        case = self.genuine(extra=self.later_work(self.config.tail_bytes + 50_000))
        said = [f for f in case["producer_facts"] if f["type"] == "user_message"]
        self.assertEqual([self.start + 5], [f["at"] for f in said])
        path = self.index[CLAUDE_SID[:8]]
        self.assertLess(case["transcript_bytes"], os.path.getsize(path))
        self.assertEqual(
            case["transcript_bytes"], mark_abstention.capture_prefix(path, self.start + 30)
        )
        self.assertEqual([], self.vouch()(case))

    def test_a_length_other_than_the_captures_is_demoted(self) -> None:
        case = self.genuine(extra=self.later_work(self.config.tail_bytes + 50_000))
        for size in (case["transcript_bytes"] - 1, case["transcript_bytes"] + 1):
            with self.subTest(size=size):
                moved = {**case, "transcript_bytes": size}
                self.assertIn("transcript-bytes-differ", self.vouch()(moved))

    def test_a_packet_with_no_cut_marker_still_cannot_name_less_than_the_capture(self) -> None:
        # Review: deleting the optional marker, zeroing the length and dropping the
        # reader's only message once left a case vouched as recorded.
        case = self.genuine(extra=self.later_work(self.config.tail_bytes + 50_000))
        stripped = {k: v for k, v in case.items() if k != "transcript_cut"}
        stripped["transcript_bytes"] = 0
        stripped["producer_facts"] = [
            f for f in case["producer_facts"] if f["type"] != "user_message"
        ]
        self.assertIn("transcript-bytes-differ", self.vouch()(stripped))
        legacy = {**stripped, "producer_facts": case["producer_facts"],
                  "transcript_bytes": os.path.getsize(self.index[CLAUDE_SID[:8]])}  # fmt: skip
        self.assertNotIn("transcript-bytes-differ", self.vouch()(legacy))

    def test_a_message_older_than_the_captures_tail_is_not_frozen(self) -> None:
        # The board at the capture read only its last `tail_bytes`; a message before
        # that is not what a press then saw, so the freeze leaves it out too.
        early = _asked(self.start, CLAUDE_SID, 1)
        bulk = tuple(
            {**row, "timestamp": _stamp(self.start, 2)}
            for row in self.later_work(self.config.tail_bytes + 50_000)
        )
        case = self.genuine(asks=(5,), extra=(early, *bulk))
        said = [f["at"] for f in case["producer_facts"] if f["type"] == "user_message"]
        self.assertEqual([self.start + 5], said)

    def test_the_freeze_ignores_the_boards_words_for_a_claude_case(self) -> None:
        rows, path = self.write(CLAUDE_SID, (5,), ())
        self.stops.append({"harness": "claude", "sid": CLAUDE_SID, "state": "idle",
                           "last_activity": self.start + 20})  # fmt: skip
        forged = _fact("forged", sid=CLAUDE_SID, harness="claude", at=self.start + 6)
        case = mark_abstention.freeze_case(
            self.config,
            {"harness": "claude", "sid": CLAUDE_SID, "project": "p",
             "captured_at": self.start + 30, "row": {"state": "idle", "finished_at": self.start + 20},
             "intent": {"goal": GOAL, "lines": [{"text": LINE_ONE}]}, "transcript": str(path)},
            [*_board_facts(self.config, rows, CLAUDE_SID), forged],
            observations=self.stops, ends=[],
        )  # fmt: skip
        self.assertNotIn("forged", [f["fact_id"] for f in case["producer_facts"]])
        self.assertEqual("recorded", case["origin"])

    def test_a_genuine_case_stays_vouched_for(self) -> None:
        case = self.genuine()
        self.assertEqual(
            {"user_message", "tool_report"}, {f["type"] for f in case["producer_facts"]}
        )
        self.assertEqual([], self.vouch()(case))

    def test_invented_checks_are_demoted(self) -> None:
        case = self.genuine()
        for fact in case["producer_facts"]:
            if fact["type"] == "tool_report":
                fact["result"] = "failed"
        self.assertIn("checks-differ", self.vouch()(case))

    def test_an_invented_check_added_beside_the_real_one_is_demoted(self) -> None:
        case = self.genuine()
        case["producer_facts"].append(_check("k-invented", at=self.start + 12, record="toolu_77"))
        self.assertIn("checks-differ", self.vouch()(case))

    def test_invented_tool_output_is_demoted(self) -> None:
        case = self.genuine()
        case["tool_output"]["tails"]["toolu_1"] = "INVENTED 99 passed"
        self.assertIn("tool-output-differs", self.vouch()(case))

    def test_an_invented_non_check_fact_with_the_checks_intact_is_demoted(self) -> None:
        case = self.genuine()
        case["producer_facts"].append(
            _fact("a-invented", sid=CLAUDE_SID, harness="claude", at=self.start + 6)
        )
        self.assertIn("facts-unconfirmed", self.vouch()(case))
        # A user message reaches the ledger by its summary and, since the 2026-10-01 ruling,
        # its whole words beside it: an invention in either is demoted.
        for field in ("summary", "reader_words"):
            case = self.genuine()
            for fact in case["producer_facts"]:
                if fact["type"] == "user_message":
                    self.assertTrue(fact.get(field), fact)
                    fact[field] = "INVENTED words the reader never typed"
            self.assertIn("facts-unconfirmed", self.vouch()(case), field)

    def test_a_transcript_that_grew_after_the_capture_is_not_demoted(self) -> None:
        case = self.genuine()
        path = Path(self.index[CLAUDE_SID[:8]])
        later = [
            _asked(self.start, CLAUDE_SID, seconds=60),
            {"type": "assistant", "isSidechain": False, "cwd": "/w", "sessionId": CLAUDE_SID,
             "timestamp": _stamp(self.start, 70), "message": {"role": "assistant", "content": [
                 {"type": "tool_use", "id": "toolu_5", "name": "Bash",
                  "input": {"command": "pytest"}}]}},
            {"type": "user", "isSidechain": False, "cwd": "/w", "sessionId": CLAUDE_SID,
             "timestamp": _stamp(self.start, 75), "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "toolu_5",
                  "content": "Exit code 1\n1 failed", "is_error": True}]}},
        ]  # fmt: skip
        with path.open("a") as handle:
            handle.write("\n".join(json.dumps(r) for r in later) + "\n")
        self.assertEqual([], self.vouch()(case))

    def user_messages(self, case: dict[str, Any]) -> list[dict[str, Any]]:
        return [f for f in case["producer_facts"] if f["type"] == "user_message"]

    def later_turn(self, sid: str = CLAUDE_SID, at: int = 60) -> tuple[dict[str, Any], ...]:
        return (
            _asked(self.start, sid, at),
            {"type": "assistant", "isSidechain": False, "cwd": "/w", "sessionId": sid,
             "timestamp": _stamp(self.start, at + 10), "message": {"role": "assistant",
             "content": [{"type": "tool_use", "id": f"toolu_{at}", "name": "Bash",
                          "input": {"command": "pytest"}}]}},
            {"type": "user", "isSidechain": False, "cwd": "/w", "sessionId": sid,
             "timestamp": _stamp(self.start, at + 12), "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": f"toolu_{at}",
                  "content": "Exit code 1\n1 failed", "is_error": True}]}},
        )  # fmt: skip

    def test_a_capture_moved_past_a_later_turn_is_demoted(self) -> None:
        # Scoring F1: a later turn stood inside a capture moved forward, and
        # its failed run replaced the pass the stop had shown.
        case = self.genuine()
        with Path(self.index[CLAUDE_SID[:8]]).open("a") as handle:
            handle.write("\n".join(json.dumps(r) for r in self.later_turn()) + "\n")
        case["captured_at"] = self.start + 100
        self.assertIn("activity-after-stop", self.vouch()(case))

    def test_the_freeze_refuses_a_record_between_the_stop_and_the_capture(self) -> None:
        with self.assertRaises(mark_abstention.FreezeError) as raised:
            self.genuine(extra=(_asked(self.start, CLAUDE_SID, 25),))
        self.assertEqual("activity-after-stop", str(raised.exception))

    def test_administrative_records_after_stop_do_not_demote_a_case(self) -> None:
        case = self.genuine(
            extra=(
                {
                    "type": "system",
                    "subtype": "turn_duration",
                    "durationMs": 4,
                    "timestamp": _stamp(self.start, 25),
                },
                {
                    "type": "progress",
                    "data": {"type": "hook_progress"},
                    "timestamp": _stamp(self.start, 26),
                },
            )
        )
        self.assertEqual("recorded", case["origin"])
        self.assertEqual([], self.vouch()(case))

    def test_a_tool_result_after_stop_is_still_activity(self) -> None:
        result = {
            "type": "user", "isSidechain": False, "cwd": "/w", "sessionId": CLAUDE_SID,
            "timestamp": _stamp(self.start, 25), "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "synthetic", "content": "29 passed"}]},
        }  # fmt: skip
        with self.assertRaises(mark_abstention.FreezeError) as raised:
            self.genuine(extra=(result,))
        self.assertEqual("activity-after-stop", str(raised.exception))

    def test_the_freeze_refuses_a_parent_check_cutoff_beyond_its_byte_budget(self) -> None:
        self.config = dataclasses.replace(self.config, turn_scan_max_bytes=1)
        with self.assertRaises(mark_abstention.FreezeError) as raised:
            self.genuine()
        self.assertEqual("check-cutoff-unreachable", str(raised.exception))

    def test_score_time_recheck_demotes_an_unreachable_parent_check_cutoff(self) -> None:
        case = self.genuine()
        config = dataclasses.replace(self.config, turn_scan_max_bytes=1)
        transcript = self.index[CLAUDE_SID[:8]]
        self.assertEqual(
            ["check-cutoff-unreachable"],
            mark_abstention.content_refusal(config, case, transcript),
        )

    def test_a_dropped_newer_message_is_demoted(self) -> None:
        # Scoring F2 and Codex 2: the redirect is what tells a prompt-directed
        # change from a departure, and dropping it passed.
        case = self.genuine(asks=(5, 17))
        typed = self.user_messages(case)
        case["producer_facts"].remove(typed[-1])
        self.assertIn("facts-unconfirmed", self.vouch()(case))

    def test_a_dropped_middle_message_is_demoted(self) -> None:
        case = self.genuine(asks=(3, 5, 17))
        case["producer_facts"].remove(self.user_messages(case)[1])
        self.assertIn("facts-unconfirmed", self.vouch()(case))

    def test_a_duplicated_message_is_demoted(self) -> None:
        # Scoring F3: the producer read one message twice.
        case = self.genuine(asks=(5, 17))
        case["producer_facts"].append(dict(self.user_messages(case)[0]))
        self.assertIn("facts-unconfirmed", self.vouch()(case))

    def test_an_old_message_the_board_still_reads_may_not_be_dropped(self) -> None:
        case = self.genuine(asks=(3, 5))
        case["producer_facts"].remove(self.user_messages(case)[0])
        self.assertIn("facts-unconfirmed", self.vouch()(case))

    def test_an_old_message_past_the_boards_bounded_tail_may_be_absent(self) -> None:
        import dataclasses  # noqa: PLC0415

        case = self.genuine(asks=(3, 5))
        case["producer_facts"].remove(self.user_messages(case)[0])
        # A tail that holds the newer records but not the oldest message.
        path = Path(self.index[CLAUDE_SID[:8]])
        lines = path.read_bytes().split(b"\n")
        self.config = dataclasses.replace(self.config, tail_bytes=len(b"\n".join(lines[1:])))
        self.assertEqual([], self.vouch()(case))

    def grow_past_the_tail(self) -> None:
        """Append later turns larger than `tail_bytes`, as a session that ran on does."""
        path = Path(self.index[CLAUDE_SID[:8]])
        filler = {"type": "assistant", "isSidechain": False, "cwd": "/w",
                  "sessionId": CLAUDE_SID, "timestamp": _stamp(self.start, 200),
                  "message": {"role": "assistant",
                              "content": [{"type": "text", "text": "x" * 1_000}]}}  # fmt: skip
        with path.open("a") as handle:
            while path.stat().st_size < 3 * self.config.tail_bytes:
                handle.write(json.dumps(filler) + "\n")
                handle.flush()

    def test_the_freeze_records_the_transcript_size(self) -> None:
        case = self.genuine()
        self.assertEqual(Path(self.index[CLAUDE_SID[:8]]).stat().st_size, case["transcript_bytes"])

    def test_the_tail_minimum_holds_after_the_transcript_grows_past_the_tail(self) -> None:
        # Review N3: once the session appended more than `tail_bytes` after
        # the freeze, today's tail began after `captured_at`, counted no user
        # message, and dropping every one of them passed.
        import dataclasses  # noqa: PLC0415

        self.config = dataclasses.replace(self.config, tail_bytes=20_000)
        genuine = self.genuine(asks=(3, 5, 17))
        self.grow_past_the_tail()
        self.assertEqual([], self.vouch()(genuine))
        oldest = json.loads(json.dumps(genuine))
        oldest["producer_facts"].remove(self.user_messages(oldest)[0])
        self.assertIn("facts-unconfirmed", self.vouch()(oldest))
        none = json.loads(json.dumps(genuine))
        for fact in self.user_messages(none):
            none["producer_facts"].remove(fact)
        self.assertIn("facts-unconfirmed", self.vouch()(none))

    def test_a_transcript_shorter_than_it_was_at_the_freeze_is_demoted(self) -> None:
        case = self.genuine()
        path = Path(self.index[CLAUDE_SID[:8]])
        path.write_bytes(path.read_bytes()[:-1])
        self.assertIn("transcript-truncated", self.vouch()(case))

    def test_a_case_with_no_recorded_size_is_demoted(self) -> None:
        case = self.genuine()
        for value in (None, "12", -1, True):
            with self.subTest(value=value):
                case["transcript_bytes"] = value
                self.assertIn("transcript-truncated", self.vouch()(case))
        del case["transcript_bytes"]
        self.assertIn("transcript-truncated", self.vouch()(case))

    def test_a_message_stamped_at_a_working_capture_is_held(self) -> None:
        # From the scoring lens's killers (K5): the rebuild's bound is inclusive.
        case = self.genuine(asks=(5, 30), working=True)
        self.assertEqual(2, len(self.user_messages(case)))
        self.assertEqual([], self.vouch()(case))

    def test_a_later_failing_run_in_the_recorded_shape_is_not_a_mismatch(self) -> None:
        # From the scoring lens's killers (K1): the rebuild stops at the capture.
        case = self.genuine()
        path = Path(self.index[CLAUDE_SID[:8]])
        with path.open("a") as handle:
            handle.write("\n".join(json.dumps(r) for r in self.later_turn(at=70)[1:]) + "\n")
        self.assertEqual([], self.vouch()(case))

    def test_a_case_frozen_on_another_parser_says_so(self) -> None:
        # Scoring F7: a parser change between freeze and score demoted every
        # case with the words tampering gets.
        case = self.genuine()
        self.assertEqual(mark_abstention.parser_digest(), case["parser"])
        case["parser"] = "0" * 64
        self.assertEqual(["frozen-on-another-parser"], self.vouch()(case))
        del case["parser"]
        self.assertEqual(["frozen-on-another-parser"], self.vouch()(case))

    def test_a_run_built_only_from_invented_cases_reads_short(self) -> None:
        sids = [f"{i:x}{i:x}{i:x}{i:x}b2c3-REAL-SID" for i in range(len(score_abstention.KINDS))]
        self.cases = [self.genuine(sid) for sid in sids]
        self.marks = {c["id"]: {"goal": "abstain", "line_1": "abstain"} for c in self.cases}
        self.rubric = {
            "cases": {
                c["id"]: {
                    "kind": kind,
                    "origin": "recorded",
                    "expect": {n: {"result": "unverifiable"} for n in ("goal", "line_1")},
                }
                for c, kind in zip(self.cases, score_abstention.KINDS, strict=True)
            }
        }
        reply = _reply(goal=("unverifiable", ()), line_1=("unverifiable", ()))
        self.score(_Model((reply, "ok")), vouch=self.vouch())
        self.assertEqual("passed", self.committed()["verdict"])
        self.summary.unlink()
        self.ledger_path.unlink()
        for case in self.cases:
            for fact in case["producer_facts"]:
                if fact["type"] == "tool_report":
                    fact["summary"] = "INVENTED npm test"
        model = _Model((reply, "ok"))
        self.score(model, vouch=self.vouch())
        committed = self.committed()
        self.assertEqual("short", committed["verdict"])
        self.assertEqual(0, committed["coverage"]["claude"]["kinds"])
        self.assertEqual([], model.prompts)
        origins = {e["origin"] for e in committed["rubric"]["cases"].values()}
        self.assertEqual({"synthetic"}, origins)


class Q4ASyntheticCaseNeverMeetsTheFloorTest(_Packet):
    def test_its_rubric_entry_is_counted_synthetic_whatever_the_rubric_says(self) -> None:
        self.cases[0]["origin"] = "synthetic"
        self.rubric = {
            "cases": {
                self.cases[0]["id"]: {
                    "kind": "misleading-completion",
                    "origin": "recorded",
                    "expect": {
                        name: {"result": "unverifiable", "cites": []}
                        for name in ("goal", "line_1", "line_2")
                    },
                }
            }
        }
        self.score(_Model())
        rubric = self.committed()["rubric"]["cases"][self.cases[0]["id"]]
        self.assertEqual("synthetic", rubric["origin"])
        self.assertEqual(0, self.committed()["coverage"]["claude"]["kinds"])


class Q5MarksAreClosedTokensTest(_Packet):
    """F5: nothing hand-typed in the marks file reaches the committed summary."""

    def test_any_other_key_or_value_refuses_the_packet(self) -> None:
        case_id = self.cases[0]["id"]
        for name, marks in (
            ("extra key", {case_id: {**self.marks[case_id], "note": "PROMPT_TEXT"}}),
            ("orphan", {**self.marks, f"claude|{CLAUDE_SID}": {"goal": "SID_AS_VALUE"}}),
            ("value", {case_id: {**self.marks[case_id], "line_1": "maybe"}}),
            ("legacy key", {case_id: {**self.marks[case_id], "output": "judge"}}),
        ):
            with self.subTest(name=name):
                self.marks = marks
                model = _Model()
                self.assertEqual(2, self.score(model))
                self.assertEqual([], model.prompts)
                self.assertFalse(self.summary.exists())

    def test_the_summary_copies_marks_from_the_scored_records_only(self) -> None:
        record = {
            "id": "0123456789abcdef",
            "harness": "claude",
            "constraints": ["goal"],
            "marks": {"goal": "judge"},
            "outcomes": {"goal": "abstained"},
            "basis": {"goal": ""},
            "reached_model": True,
            "asks_output": False,
        }
        summary = score_abstention.summarize(
            [record],
            marks={"0123456789abcdef": {"goal": "judge", "note": "PROMPT_TEXT"}, "x": {"a": "b"}},
            marks_bytes=b"",
            now=1.0,
        )
        self.assertEqual({"0123456789abcdef": {"goal": "judge"}}, summary["marks"])
        self.assertNotIn("PROMPT_TEXT", json.dumps(summary))


def _rubric_record(kind: str, harness: str, judgement: dict[str, str]) -> dict[str, Any]:
    return {
        "id": "0123456789abcdef",
        "kind": kind,
        "harness": harness,
        "origin": "recorded",
        "admitted": True,
        "refused": "",
        "scored": True,
        "reached_model": True,
        "judgement": judgement,
        "extraction": {},
        "unknown_expectations": 0,
    }


class Q6AnUnscoredRequiredJudgementBlocksAPassTest(_Packet):
    """F6 and codex 3: a rubric that did not score what the case asks cannot pass."""

    def rubric_for(self, expect: dict[str, Any]) -> None:
        self.marks[self.cases[0]["id"]] = {"goal": "judge", "line_1": "judge", "line_2": "judge"}
        self.rubric = {
            "cases": {
                self.cases[0]["id"]: {
                    "kind": "misleading-completion",
                    "origin": "recorded",
                    "expect": expect,
                }
            }
        }

    def test_an_expectation_under_a_key_the_case_lacks_blocks(self) -> None:
        self.rubric_for({"goal": {"result": "consistent"}, "output": {"result": "unverifiable"}})
        reply = _reply(
            goal=("consistent", (2,)), line_1=("consistent", (2,)), line_2=("consistent", (2,))
        )
        self.score(_Model((reply, "ok")))
        committed = self.committed()
        entry = committed["rubric"]["cases"][self.cases[0]["id"]]
        self.assertEqual(1, entry["unknown_expectations"])
        self.assertEqual("unscored:missing-expectation", entry["judgement"]["line_1"])
        self.assertNotIn("output", json.dumps(entry["judgement"]))
        self.assertEqual("blocked", committed["verdict"])

    def test_a_misspelt_required_expectation_blocks(self) -> None:
        self.rubric_for({name: {"result": "unverifyable"} for name in ("goal", "line_1", "line_2")})
        self.score(_Model())
        self.assertEqual("blocked", self.committed()["verdict"])

    def test_coverage_counts_only_cases_whose_required_judgements_were_scored(self) -> None:
        full = {"goal": "correct", "line_1": "correct"}
        records = [
            _rubric_record(kind, harness, full)
            for kind in score_abstention.KINDS
            for harness in ("claude", "codex")
        ]
        self.assertEqual(5, score_abstention._coverage(records)["claude"]["kinds"])
        records[0]["judgement"] = {"goal": "correct", "line_1": "unscored:bad-expectation"}
        self.assertEqual(4, score_abstention._coverage(records)["claude"]["kinds"])
        coverage = score_abstention._coverage(records)
        counts = dict.fromkeys(score_abstention.RUBRIC_OUTCOMES, 0)
        counts["unscored:bad-expectation"] = 1
        dec17: dict[str, list[str]] = {"failed": [], "held": []}
        self.assertEqual("blocked", score_abstention._verdict(dec17, coverage, counts))


class TheFloorIsJudgedPerProducerTest(unittest.TestCase):
    """Owner ruling, 2026-09-27: the producer scored needs every kind; the other is a control.

    Codex produced no supported departure in six attempts, and one it was told
    to make does not count, so a floor that required it could never be met.
    """

    def summary(self, missing: dict[str, str], binding: dict[str, str] | None) -> dict[str, Any]:
        full = {"goal": "correct", "line_1": "correct"}
        records = [
            _rubric_record(kind, harness, full)
            for harness in ("claude", "codex")
            for kind in score_abstention.KINDS
            if missing.get(harness) != kind
        ]
        for index, record in enumerate(records):
            record["id"] = f"{index:016x}"
        return score_abstention.summarize(
            [], marks={}, marks_bytes=b"", now=1.0, rubric_records=records, binding=binding
        )

    def test_a_claude_complete_set_passes_with_a_codex_kind_never_produced(self) -> None:
        summary = self.summary({"codex": "supported-departure"}, BINDING)
        self.assertEqual("passed", summary["verdict"])
        codex = summary["coverage"]["codex"]
        self.assertEqual("control", codex["role"])
        self.assertEqual(["supported-departure"], codex["not_produced"])
        self.assertEqual([], codex["missing"])
        self.assertEqual("scored", summary["coverage"]["claude"]["role"])

    def test_a_claude_set_missing_a_kind_reads_short(self) -> None:
        summary = self.summary({"claude": "supported-departure"}, BINDING)
        self.assertEqual("short", summary["verdict"])
        self.assertEqual(["supported-departure"], summary["coverage"]["claude"]["missing"])

    def test_the_report_says_not_produced_and_never_short_for_the_control(self) -> None:
        lines = "\n".join(
            score_abstention.render(self.summary({"codex": "legitimate-change"}, BINDING))
        )
        self.assertIn("cross-harness control", lines)
        self.assertIn("not produced: legitimate-change", lines)
        self.assertNotIn("missing: legitimate-change", lines)
        self.assertIn("PASSED", lines)

    def test_a_run_that_names_no_producer_keeps_both_harnesses_required(self) -> None:
        # Every summary written before the amendment was scored under the
        # original floor; the amendment does not rewrite them.
        self.assertEqual("short", self.summary({"codex": "supported-departure"}, None)["verdict"])


class Q7EveryCaseIsMarkedBeforeAnyCallTest(_Packet):
    def test_a_partly_marked_packet_spends_nothing(self) -> None:
        self.cases.append(_codex_case())
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)
        self.assertFalse(self.ledger_path.exists())

    def test_a_format_below_five_cannot_write_a_claude_result(self) -> None:
        case = {k: v for k, v in _claude_case().items() if k not in ("intent", "tool_output")}
        self.cases = [case]
        self.marks = {case["id"]: {"goal": "judge", "output": "abstain"}}
        model = _Model()
        with (
            mock.patch.object(self, "body", return_value={
                "v": 4, "goal": GOAL, "output": LINE_ONE, "cases": [case]}),
        ):  # fmt: skip
            self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)


class Q8AWriteAloneIsTheAgentsAccountTest(_Packet):
    def test_a_goal_consistent_citing_only_a_written_file_is_account(self) -> None:
        write = _fact(
            "w1",
            sid=CLAUDE_SID,
            harness="claude",
            at=90.0,
            type="tool_report",
            subject="write",
            summary="index.html",
            evidence={"source": "Claude Write call", "confidence": "exact"},
            branch={"harness": "claude", "sid": CLAUDE_SID, "record_id": "toolu_5"},
        )
        self.cases[0]["producer_facts"] = [
            _fact("a1", sid=CLAUDE_SID, harness="claude", at=80.0),
            write,
        ]
        self.cases[0]["tool_output"] = {"tails": {}, "changed_after": []}
        # Citing the agent's own words and the write: before the fix the write
        # alone made this `tool`.
        reply = _reply(goal=("consistent", (1, 2)))
        self.score(_Model((reply, "ok")))
        case = self.committed()["cases"][self.cases[0]["id"]]
        self.assertEqual("judged:consistent", case["outcomes"]["goal"])
        self.assertEqual("account", case["basis"]["goal"])

    def test_basis_calls_a_cited_write_account_and_only_a_recorded_check_tool(self) -> None:
        # Direct, because the producer's own item 8 drops a write from what a
        # verdict rests on today; the basis must not lean on that.
        agent: dict[str, Any] = {"id": "a1", "type": "result", "author": "agent"}
        write: dict[str, Any] = {"id": "w1", "type": "tool_report", "subject": "write", "result": "",
                 "author": "agent", "work": True}  # fmt: skip
        check = {**write, "id": "k1", "subject": "check", "result": "passed"}
        unrecorded = {**check, "id": "k2", "result": "not-recorded"}
        consistent = reading.RESULT_CONSISTENT
        cases: tuple[tuple[tuple[str, ...], list[dict[str, Any]], str], ...] = (
            (("w1",), [agent, write], "account"),
            (("a1", "w1"), [agent, write], "account"),
            (("k2",), [unrecorded], "account"),
            (("k1",), [check], "tool"),
        )
        for cites, ledger, want in cases:
            with self.subTest(cites=cites):
                criterion = {"result": consistent, "cites": cites}
                self.assertEqual(want, score_abstention.basis(criterion, ledger))


class Q9AResumeTrustsOnlyRecordsTheLedgerVouchesForTest(_Ledgered):
    def two_cases(self) -> None:
        second = _codex_case()
        self.cases.append(second)
        self.marks[second["id"]] = {"goal": "judge", "line_1": "abstain"}

    def test_a_resume_re_calls_only_the_cases_the_model_failed(self) -> None:
        self.two_cases()
        self.score(_Model(("", "failed"), ("{}", "ok")))
        failed = [k for k, v in self.local()["cases"].items() if v["withheld"] == "model-failed"]
        self.assertEqual([self.cases[0]["id"]], failed)
        model = _Model(("{}", "ok"))
        self.assertEqual(0, self.score(model, resume=self.local()))
        self.assertEqual(1, len(model.prompts))
        self.assertIn(TAIL, model.prompts[0])
        self.assertEqual(3, len(self.calls()))

    def test_a_newly_demoted_case_does_not_carry_its_prior_record(self) -> None:
        self.score(_Model((_reply(goal=("consistent", (1,))), "ok")))
        previous = self.local()
        case_id = self.cases[0]["id"]
        self.assertTrue(previous["records"][case_id]["reached_model"])
        calls = self.calls()
        model = _Model()
        self.assertEqual(
            0,
            self.score(model, resume=previous, vouch=lambda _case: ["transcript-missing"]),
        )
        self.assertEqual([], model.prompts)
        self.assertEqual(calls, self.calls())
        record = self.local()["records"][case_id]
        self.assertFalse(record["reached_model"])
        self.assertEqual(score_abstention.WITHHELD_NOT_RECORDED, record["withheld"])
        self.assertEqual(0, self.committed()["counts"]["reached_model"])

    def test_a_hand_edited_record_refuses_the_resume(self) -> None:
        self.two_cases()
        self.score(_Model(("", "failed"), ("{}", "ok")))
        previous = self.local()
        other = self.cases[1]["id"]
        previous["records"][other]["outcomes"]["goal"] = "abstained"
        model = _Model()
        self.assertEqual(2, self.score(model, resume=previous))
        self.assertEqual([], model.prompts)

    def test_a_resume_against_other_inputs_refuses(self) -> None:
        self.score(_Model(("", "failed")))
        previous = self.local()
        self.cases[0]["intent"]["goal"] = "CHANGED"
        model = _Model()
        self.assertEqual(2, self.score(model, resume=previous))
        self.assertEqual([], model.prompts)


class DRC4731ResumeBindsTheVerifiedProducerTest(_Ledgered):
    """Editable summary metadata cannot relabel the producer of authenticated records."""

    def assert_resume_refused(self, previous: dict[str, Any], binding: dict[str, str]) -> None:
        before = {path: path.read_bytes() for path in (self.result, self.summary, self.ledger_path)}
        model = _Model()
        self.assertEqual(2, self.score(model, resume=previous, binding=binding))
        self.assertEqual([], model.prompts)
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_editing_the_summary_cannot_rebind_any_owned_producer_field(self) -> None:
        replacements = {
            "producer": "codex",
            "model": "another-model",
            "argv_digest": "ef" * 32,
            "destination": "another-destination",
            "binary": "~/.local/share/claude/versions/9.9.9",
            "binary_sha256": "ef" * 32,
            "cli_version": "9.9.9 (Claude Code)",
            "signature": "unchecked sha256:" + "ef" * 32,
        }
        for name, replacement in replacements.items():
            with self.subTest(binding=name):
                self.score(_Model())
                previous = self.local()
                binding = {**BINDING, name: replacement}
                previous["summary"][name] = replacement
                self.assert_resume_refused(previous, binding)

    def test_a_legacy_records_only_ledger_run_cannot_resume(self) -> None:
        self.score(_Model())
        previous = self.local()
        self.packet_ledger().record_run(abstention_ledger.digest(previous["records"]))
        self.assert_resume_refused(previous, BINDING)

    def test_the_same_binding_carries_records_without_another_call(self) -> None:
        self.score(_Model())
        previous = self.local()
        calls = self.calls()
        model = _Model()
        self.assertEqual(0, self.score(model, resume=previous))
        self.assertEqual([], model.prompts)
        self.assertEqual(calls, self.calls())
        self.assertEqual(previous["records"], self.local()["records"])

    def test_a_new_copied_digest_refuses_an_unedited_resume(self) -> None:
        self.score(_Model())
        self.assert_resume_refused(self.local(), {**BINDING, "binary_sha256": "ef" * 32})

    def test_a_resume_without_the_copied_digest_refuses(self) -> None:
        self.score(_Model())
        previous = self.local()
        del previous["summary"]["binary_sha256"]
        self.assert_resume_refused(previous, BINDING)


# ------------------------------------------------------------------ DRC-4666 verifier round


@unittest.skipIf(os.name == "nt", "missing passwd admission is POSIX only")
class DRC4731ColdAccountAdmissionTest(unittest.TestCase):
    """Missing account authority is refused before importing runtime or touching evidence/spend."""

    CHILD = r"""
import argparse, contextlib, importlib, io, json, os, pwd, runpy, sys, types
from pathlib import Path
scripts, mode, canonical = sys.argv[1:]
sys.path.insert(0, scripts)
counts = {'data_reads': 0, 'writes': 0, 'children': 0, 'network': 0, 'runtime': 0}
def audit(event, args):
    if event == 'subprocess.Popen':
        counts['children'] += 1
        raise AssertionError('nested process forbidden')
    if event in ('socket.connect', 'socket.bind'):
        counts['network'] += 1
        raise AssertionError('network forbidden')
    if event == 'import' and str(args[0]).startswith('compass_runtime'):
        counts['runtime'] += 1
        raise AssertionError('runtime must not be reached')
    if event in ('os.mkdir', 'os.remove', 'os.rename', 'os.rmdir', 'os.link', 'os.symlink', 'os.chmod'):
        counts['writes'] += 1
        raise AssertionError('filesystem mutation forbidden')
    if event == 'open':
        path, _mode, flags = args
        if isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            counts['writes'] += 1
            raise AssertionError('file write forbidden')
        if isinstance(path, str) and path.endswith(('.json', '.jsonl', '.sqlite', '.db', '.lock')):
            counts['data_reads'] += 1
            raise AssertionError('evidence or ledger read forbidden')
sys.addaudithook(audit)
def absent(_uid):
    raise KeyError('synthetic missing passwd entry')
known = lambda _uid: types.SimpleNamespace(pw_dir=canonical, pw_name='synthetic_account')
pwd.getpwuid = absent if mode.startswith('missing') or mode == 'recovered_cli' else known
result = {'mode': mode}
try:
    if mode in ('missing_cli', 'recovered_cli'):
        if mode == 'recovered_cli':
            importlib.import_module('score_abstention')
            pwd.getpwuid = known
        sys.argv = [str(Path(scripts, 'score_abstention.py')), '--score', '--producer', 'claude', '--max-calls', '1']
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            try:
                runpy.run_path(sys.argv[0], run_name='__main__')
            except SystemExit as exit:
                result['exit_code'] = exit.code
        result['stdout'] = captured.getvalue()
    else:
        score = importlib.import_module('score_abstention')
        ledger = importlib.import_module('abstention_ledger')
        marker = importlib.import_module('mark_abstention')
        result['imported'] = True
        if mode == 'missing_import':
            result['unavailable_roots'] = ledger.LEDGER_PATH is None and marker.CLAUDE_PROJECTS_ROOT is None and marker.STORE_HOME is None and score.CLAUDE_VERSIONS_ROOTS == ()
            result['home_guard_closed'] = ledger.home_moved() is True
            try:
                ledger.read(ledger.LEDGER_PATH)
            except ledger.LedgerError:
                result['default_read_refused'] = True
            try:
                ledger.Ledger(ledger.LEDGER_PATH, cap=1, marks_digest='a' * 64, inputs_digest='b' * 64, producer='claude').charge('c' * 16)
            except ledger.LedgerError:
                result['default_charge_refused'] = True
        else:
            result['canonical_roots'] = ledger.LEDGER_PATH == os.path.join(canonical, '.compass', 'drc-4666-spend.json') and marker.CLAUDE_PROJECTS_ROOT == os.path.join(canonical, '.claude', 'projects') and marker.STORE_HOME == os.path.join(canonical, '.compass') and score.CLAUDE_VERSIONS_ROOTS == (os.path.join(canonical, '.local', 'share', 'claude', 'versions'),)
            args = argparse.Namespace(score=True, probe_argv=False, producer='claude', max_calls=1, resume=False)
            result['refusal'] = score._argument_refusal(args)
            result['home_moved'] = ledger.home_moved()
except BaseException as error:
    result['exception'] = type(error).__name__
result['counts'] = counts
print(json.dumps(result))
"""

    def run_cold(self, mode: str) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="qualification-cold-account-") as temporary:
            canonical = str(Path(temporary, "canonical-account"))
            environ = {
                **os.environ,
                "HOME": canonical + ("-other" if mode == "moved_home" else ""),
                "COMPASS_HOME": str(Path(temporary, "private-packet")),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            result = subprocess.run(
                [sys.executable, "-B", "-c", self.CHILD, str(ROOT / "scripts"), mode, canonical],
                cwd=temporary,
                env=environ,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stderr)
        observed: dict[str, Any] = json.loads(result.stdout)
        self.assertEqual(
            {"data_reads": 0, "writes": 0, "children": 0, "network": 0, "runtime": 0},
            observed["counts"],
            observed,
        )
        return observed

    def test_missing_passwd_cold_import_keeps_canonical_roots_unavailable(self) -> None:
        observed = self.run_cold("missing_import")
        self.assertNotIn("exception", observed)
        for name in (
            "imported",
            "unavailable_roots",
            "home_guard_closed",
            "default_read_refused",
            "default_charge_refused",
        ):
            self.assertIs(True, observed.get(name), observed)

    def test_missing_passwd_actual_score_cli_refuses_before_any_action(self) -> None:
        observed = self.run_cold("missing_cli")
        self.assertNotIn("exception", observed)
        self.assertEqual(2, observed.get("exit_code"), observed)
        self.assertIn("Refused:", observed.get("stdout", ""))
        self.assertIn("unavailable", observed.get("stdout", "").lower())

    def test_account_recovery_cannot_skip_the_cached_unavailable_default_ledger(self) -> None:
        observed = self.run_cold("recovered_cli")
        self.assertNotIn("exception", observed)
        self.assertEqual(2, observed.get("exit_code"), observed)
        self.assertIn("Refused:", observed.get("stdout", ""))
        self.assertIn("unavailable", observed.get("stdout", "").lower())

    def test_canonical_account_roots_and_matching_home_are_preserved(self) -> None:
        observed = self.run_cold("canonical")
        self.assertNotIn("exception", observed)
        self.assertIs(True, observed.get("canonical_roots"), observed)
        self.assertIs(False, observed.get("home_moved"), observed)
        self.assertEqual("", observed.get("refusal"), observed)

    def test_moved_home_still_refuses_without_touching_canonical_roots(self) -> None:
        observed = self.run_cold("moved_home")
        self.assertNotIn("exception", observed)
        self.assertIs(True, observed.get("canonical_roots"), observed)
        self.assertIs(True, observed.get("home_moved"), observed)
        self.assertIn("Refused: HOME", observed.get("refusal", ""))


def _real_home() -> str:
    import pwd  # noqa: PLC0415 - POSIX only, as the scorer's own check is

    return pwd.getpwuid(os.getuid()).pw_dir


@unittest.skipIf(sys.platform == "win32", "the account's home comes from pwd, POSIX only")
class V1HomeComesFromTheAccountNotTheEnvironmentTest(_Packet):
    """V1: `HOME=/tmp/x` moved the ledger and the installed-CLI check with it."""

    def test_a_moved_home_moves_neither_the_ledger_nor_the_install_roots(self) -> None:
        import importlib  # noqa: PLC0415

        fake = str(self.home / "x")
        with mock.patch.dict("os.environ", {"HOME": fake}):
            self.assertEqual(fake, os.path.expanduser("~"))
            ledger = importlib.reload(abstention_ledger).LEDGER_PATH
            roots = importlib.reload(score_abstention).CLAUDE_VERSIONS_ROOTS
            marker = importlib.reload(mark_abstention)
            projects, store = marker.CLAUDE_PROJECTS_ROOT, marker.STORE_HOME
        importlib.reload(abstention_ledger)
        importlib.reload(mark_abstention)
        importlib.reload(score_abstention)
        _LEDGER_PATCH.stop()
        _LEDGER_PATCH.start()
        for path in (ledger, *roots, projects, store):
            with self.subTest(path=path):
                self.assertTrue(path.startswith(_real_home()), path)
                self.assertNotIn(fake, path)

    def test_a_symlinked_versions_directory_under_a_moved_home_is_refused(self) -> None:
        # The verifier's h4: the real versions directory symlinked into a fake home.
        installed = self.home / "installed" / "versions"
        installed.mkdir(parents=True)
        (installed / "2.1.281").write_text("")
        fake = self.home / "x"
        (fake / ".local" / "share" / "claude").mkdir(parents=True)
        (fake / ".local" / "share" / "claude" / "versions").symlink_to(installed)
        found = str(fake / ".local" / "share" / "claude" / "versions" / "2.1.281")
        runner = mock.Mock(return_value=mock.Mock(returncode=0, stdout="2.1.281 (Claude Code)\n"))
        with (
            mock.patch.dict("os.environ", {"HOME": str(fake)}),
            self.assertRaises(score_abstention.BinaryError),
        ):
            score_abstention.verify_claude_binary(resolver=lambda _name: found, runner=runner)

    def test_scoring_refuses_when_home_is_not_the_accounts(self) -> None:
        printed: list[str] = []
        corpus = score_abstention.Corpus({"v": 5, "cases": [_claude_case()]}, {}, b"", {})
        with (
            mock.patch.dict("os.environ", {"HOME": str(self.home / "x")}),
            mock.patch.object(score_abstention, "_load_corpus", return_value=corpus),
            mock.patch.object(score_abstention, "score", side_effect=AssertionError("scored")),
            mock.patch("builtins.print", side_effect=lambda *a, **_k: printed.append(str(a))),
        ):
            self.assertEqual(2, score_abstention.main(["--score", "--producer", "claude"]))
        self.assertIn("HOME", "\n".join(printed))


def _invented(harness: str, index: int) -> dict[str, Any]:
    sid = f"{harness[:2]}{index:06d}-INVENTED"
    case = {
        "id": mark_abstention._case_id(harness, sid),
        "harness": harness,
        "sid": sid,
        "origin": "recorded",
        "captured_at": 200.0,
        "row_snapshot": {"harness": harness, "sid": sid, "state": "working"},
        "producer_facts": [_fact(f"f{index}", sid=sid, harness=harness, at=150.0)],
        "intent": {"goal": GOAL, "lines": [{"text": LINE_ONE}]},
    }
    if harness == "claude":
        case["tool_output"] = {"tails": {}, "changed_after": []}
        # Every real Claude Code freeze stamps its parser; this fixture's subject is
        # invented provenance, not a missing stamp.
        case["parser"] = mark_abstention.parser_digest()
    return case


class V2TheScorerReChecksProvenanceTest(_Packet):
    """V2: ten hand-written cases called recorded met the floor and passed."""

    def invented_packet(self) -> None:
        self.cases = [
            _invented(harness, i)
            for i, harness in enumerate(
                h for h in ("claude", "codex") for _ in score_abstention.KINDS
            )
        ]
        self.marks = {c["id"]: {"goal": "judge", "line_1": "abstain"} for c in self.cases}
        kinds = list(score_abstention.KINDS) * 2
        self.rubric = {
            "cases": {
                c["id"]: {
                    "kind": kind,
                    "origin": "recorded",
                    "expect": {
                        "goal": {"result": "unverifiable"},
                        "line_1": {"result": "unverifiable"},
                    },
                }
                for c, kind in zip(self.cases, kinds, strict=True)
            }
        }

    def machine(self, **stores: Any) -> Any:
        return mark_abstention.make_vouch(
            observations=stores.get("observations", []),
            ends=stores.get("ends", []),
            index=stores.get("index", {}),
        )

    def test_invented_cases_called_recorded_never_pass(self) -> None:
        self.invented_packet()
        reply = _reply(goal=("unverifiable", ()), line_1=("unverifiable", ()))
        # Trusted, as 1dc5f86b trusted them: the floor is met and it passes.
        self.score(_Model((reply, "ok")))
        self.assertEqual("passed", self.committed()["verdict"])
        self.ledger_path.unlink()
        self.summary.unlink()
        rc = self.score(_Model((reply, "ok")), vouch=self.machine())
        committed: Any = self.committed() if self.summary.exists() else {"verdict": "refused"}
        self.assertIn(committed["verdict"], ("short", "refused"), rc)
        self.assertEqual(0, committed.get("coverage", {}).get("claude", {}).get("kinds", 0))
        origins = {e["origin"] for e in committed.get("rubric", {}).get("cases", {}).values()}
        self.assertEqual({"synthetic"}, origins)

    def test_a_case_the_machine_vouches_for_stays_recorded(self) -> None:
        case = _invented("codex", 1)
        self.cases = [case]
        self.marks = {case["id"]: {"goal": "judge", "line_1": "abstain"}}
        self.rubric = {
            "cases": {
                case["id"]: {"kind": "legitimate-change", "origin": "recorded",
                             "expect": {"goal": {"result": "unverifiable"}}}
            }
        }  # fmt: skip
        seen = {"harness": "codex", "sid": case["sid"], "state": "working", "last_activity": 200.0}
        self.score(_Model(), vouch=self.machine(observations=[seen]))
        entry = self.committed()["rubric"]["cases"][case["id"]]
        self.assertEqual("recorded", entry["origin"])
        self.assertEqual(1, self.committed()["coverage"]["codex"]["kinds"])

    def test_a_claude_case_needs_its_transcript_in_the_index(self) -> None:
        case = _invented("claude", 2)
        stop = {"harness": "claude", "sid": case["sid"], "state": "working", "last_activity": 200.0}
        why = self.machine(observations=[stop])(case)
        self.assertIn("transcript-missing", why)

    def test_main_builds_the_machines_vouch(self) -> None:
        seen: dict[str, Any] = {}
        corpus = score_abstention.Corpus({"v": 5, "cases": [_claude_case()]}, {}, b"", {})
        with (
            mock.patch.object(score_abstention, "_load_corpus", return_value=corpus),
            mock.patch.object(
                score_abstention, "score", side_effect=lambda *_a, **k: seen.update(k) or 0
            ),
            mock.patch.object(score_abstention, "argv_digest", return_value="cd" * 32),
            mock.patch.object(
                score_abstention,
                "verify_claude_binary",
                return_value=_VERIFIED,
            ),
            mock.patch.object(mark_abstention, "machine_vouch", return_value="VOUCH") as built,
            mock.patch("compass_runtime.reading_route.destination", return_value="Anthropic"),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(0, score_abstention.main(["--score", "--producer", "claude"]))
        self.assertEqual("VOUCH", seen["vouch"])
        built.assert_called_once_with(mark_abstention.STORE_HOME)


class V3ADeletedLedgerCannotUnfreezeTheKeyTest(_Ledgered):
    """V3: score, delete the ledger, re-mark, score again. The second run must be refused."""

    def test_the_summary_commits_the_chain_and_a_rescore_after_deletion_is_refused(self) -> None:
        self.marks[self.cases[0]["id"]] = {
            "goal": "abstain",
            "line_1": "abstain",
            "line_2": "abstain",
        }
        reply = _reply(
            goal=("consistent", (2,)), line_1=("consistent", (2,)), line_2=("consistent", (2,))
        )
        self.assertEqual(1, self.score(_Model((reply, "ok"))))
        committed = self.committed()
        (call,) = self.calls()
        self.assertEqual(call["id"], committed["ledger_chain"]["first"])
        self.assertEqual(1, committed["ledger_chain"]["calls"])
        self.assertEqual(abstention_ledger.chain([call]), committed["ledger_chain"]["head"])
        self.ledger_path.unlink()
        self.marks[self.cases[0]["id"]] = {"goal": "judge", "line_1": "judge", "line_2": "judge"}
        model = _Model((reply, "ok"))
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)
        self.assertEqual(committed, self.committed())

    def test_the_marker_stays_frozen_once_a_result_committed_a_chain(self) -> None:
        self.score(_Model())
        self.ledger_path.unlink()
        cases, marks = self.home / "cases.json", self.home / "marks.json"
        cases.write_text(json.dumps({"v": 5, "cases": [_claude_case()]}))
        marks.write_text("{}")
        with (
            mock.patch.object(abstention_ledger, "LEDGER_PATH", str(self.ledger_path)),
            mock.patch.object(abstention_ledger, "CLAUDE_SUMMARY_PATH", str(self.summary)),
            mock.patch.object(mark_abstention, "CASES_PATH", str(cases)),
            mock.patch.object(mark_abstention, "MARKS_PATH", str(marks)),
            mock.patch.object(mark_abstention, "_ask", side_effect=AssertionError("asked")),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(1, mark_abstention.mark())
            self.assertEqual(1, mark_abstention.main(["--reset"]))

    def test_report_flags_a_ledger_that_does_not_begin_with_the_committed_chain(self) -> None:
        self.score(_Model())
        committed = self.committed()
        self.ledger_path.unlink()
        self.precharge(1)
        printed: list[str] = []
        with (
            mock.patch.object(abstention_ledger, "LEDGER_PATH", str(self.ledger_path)),
            mock.patch("builtins.print", side_effect=lambda *a, **_k: printed.append(str(a))),
        ):
            score_abstention.report(self.corpus(), committed)
        self.assertIn("STALE", "\n".join(printed))


# ------------------------------------------------------------------ DRC-4666 second re-check


class V3bTheCommittedResultIsReadWhereverOutPoints(_Ledgered):
    """V3b: deleting the ledger and scoring with `--out` elsewhere reset the cap."""

    def test_a_rescore_to_another_out_after_deletion_is_refused(self) -> None:
        with mock.patch.object(abstention_ledger, "CLAUDE_SUMMARY_PATH", str(self.summary)):
            self.score(_Model())
            self.ledger_path.unlink()
            self.marks[self.cases[0]["id"]]["line_2"] = "judge"
            self.summary_elsewhere = self.home / "elsewhere.json"
            self.summary, committed = self.summary_elsewhere, self.summary
            model = _Model()
            self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)
        self.assertFalse(self.summary_elsewhere.exists())
        self.assertTrue(committed.exists())


class V3dACommittedResultWithoutAChainIsRefused(_Ledgered):
    """V3d: a committed result stripped of its chain was skipped, not refused."""

    def strip_chain(self) -> None:
        body = json.loads(self.summary.read_text())
        body.pop("ledger_chain")
        self.summary.write_text(json.dumps(body))

    def test_stripped_with_the_ledger_kept_is_refused(self) -> None:
        self.score(_Model())
        self.strip_chain()
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)

    def test_stripped_with_the_ledger_deleted_is_refused(self) -> None:
        self.score(_Model())
        self.strip_chain()
        self.ledger_path.unlink()
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)


class V3eTheChainCoversTheMarksEachCallWasChargedUnder(_Ledgered):
    """V3e: rewriting the ledger's digests in place kept the id-only chain intact."""

    def test_rewriting_marks_digests_in_place_breaks_the_chain(self) -> None:
        self.score(_Model())
        committed = self.committed()
        self.marks[self.cases[0]["id"]]["line_2"] = "judge"
        rewritten = score_abstention.marks_digest(self.corpus())
        body = json.loads(self.ledger_path.read_text())
        for entry in (*body["calls"], *body["runs"]):
            entry["marks_digest"] = rewritten
        self.ledger_path.write_text(json.dumps(body))
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)
        printed: list[str] = []
        with (
            mock.patch.object(abstention_ledger, "LEDGER_PATH", str(self.ledger_path)),
            mock.patch("builtins.print", side_effect=lambda *a, **_k: printed.append(str(a))),
        ):
            score_abstention.report(self.corpus(), committed)
        self.assertIn("STALE", "\n".join(printed))


def _collect_into(sink: list[str]) -> Any:
    def record(*args: Any, **_kwargs: Any) -> None:
        sink.append(" ".join(map(str, args)))

    return record


class N3AnUnconfirmedCaseIsNeverCharged(_Ledgered):
    """N3: demoted cases still spent calls on a run that could only be short."""

    def test_a_case_the_machine_does_not_vouch_for_spends_nothing(self) -> None:
        model = _Model()
        self.score(model, vouch=lambda _case: ["lifecycle-unconfirmed"])
        self.assertEqual([], model.prompts)
        self.assertFalse(self.ledger_path.exists() and self.calls())
        case = self.local()["cases"][self.cases[0]["id"]]
        self.assertEqual("not-recorded", case["withheld"])

    def test_the_pre_run_report_counts_only_confirmed_cases(self) -> None:
        self.rubric = {
            "cases": {self.cases[0]["id"]: {"kind": "misleading-completion", "origin": "recorded"}}
        }
        for vouch, want in (
            (lambda _case: ["transcript-missing"], "claude: 0 confirmed recorded, 0 kind-tagged"),
            (lambda _case: [], "claude: 1 confirmed recorded, 1 kind-tagged"),
        ):
            printed: list[str] = []
            with mock.patch("builtins.print", side_effect=_collect_into(printed)):
                score_abstention.report(self.corpus(), None, vouch=vouch)
            with self.subTest(want=want):
                self.assertIn(want, "\n".join(printed))


# ------------------------------------------------------------------ DRC-4666 round 3 riders


class N4OnlyAWellFormedChainIsAccepted(_Ledgered):
    """N4: a committed chain whose count was not a positive int was waved through."""

    def test_every_malformed_chain_refuses_a_rescore_after_deletion(self) -> None:
        self.score(_Model())
        good = self.committed()
        empty = abstention_ledger.chain([])
        for bad in (
            {"calls": 0, "first": "x", "head": empty},
            {"calls": 0, "first": "", "head": "0" * 64},
            {"calls": -1, "first": "", "head": empty},
            {"calls": "1", "first": good["ledger_chain"]["first"], "head": empty},
            {"calls": 1.0, "first": good["ledger_chain"]["first"], "head": empty},
            {"calls": True, "first": good["ledger_chain"]["first"], "head": empty},
            {"calls": 1, "first": None, "head": good["ledger_chain"]["head"]},
            {"calls": 1, "head": good["ledger_chain"]["head"]},
        ):
            with self.subTest(bad=bad):
                self.summary.write_text(json.dumps({**good, "ledger_chain": bad}))
                if self.ledger_path.exists():
                    self.ledger_path.unlink()
                model = _Model()
                self.assertEqual(2, self.score(model))
                self.assertEqual([], model.prompts)

    def test_a_genuine_zero_call_result_is_accepted_and_still_guards(self) -> None:
        refuse = lambda _case: ["lifecycle-unconfirmed"]  # noqa: E731
        self.score(_Model(), vouch=refuse)
        chain = self.committed()["ledger_chain"]
        self.assertEqual({"first": "", "calls": 0, "head": abstention_ledger.chain([])}, chain)
        self.assertNotEqual(2, self.score(_Model(), vouch=refuse))
        self.precharge(1)
        model = _Model()
        self.assertEqual(2, self.score(model))
        self.assertEqual([], model.prompts)


class AWrittenResultThatSpentIsNeverReplacedByAFreshRunTest(_Ledgered):
    """A fresh run over a result that charged calls would re-spend its key (review, DRC-4666)."""

    def test_a_fresh_run_over_a_spent_result_is_refused_before_any_call(self) -> None:
        self.assertNotEqual(2, self.score(_Model()))
        spent = self.committed()["ledger_chain"]["calls"]
        self.assertGreater(spent, 0)
        before = self.summary.read_bytes()
        model = _Model()
        printed: list[str] = []
        self.assertEqual(2, self.score(model, printed=printed))
        self.assertEqual([], model.prompts)
        self.assertEqual(spent, len(self.calls()))
        self.assertEqual(before, self.summary.read_bytes())
        self.assertTrue(any("A fresh run never replaces one" in line for line in printed))

    def test_a_symlinked_result_path_is_refused(self) -> None:
        target = self.summary.with_name("elsewhere.json")
        target.write_text("{}")
        self.summary.symlink_to(target)
        self.assertEqual(2, self.score(_Model()))
        self.assertEqual("{}", target.read_text())


class AScoreFromAnotherParserIsRefusedBeforeAnyChargeTest(_Ledgered):
    """A checkout whose parser differs from the freeze demotes every Claude Code case.

    Before this refusal the run still went ahead: each such case was withheld
    unscored, while every other case was charged against the spend cap.
    """

    def stale_packet(self) -> None:
        self.cases[0]["parser"] = "0" * 64
        codex = _codex_case()
        self.cases.append(codex)
        self.marks[codex["id"]] = {"goal": "judge", "line_1": "abstain"}

    def as_the_machine_would(self, case: Any) -> list[str]:
        # The score-time re-check's own verdict on a stamp that does not match.
        stamped = case.get("parser", mark_abstention.parser_digest())
        return [] if stamped == mark_abstention.parser_digest() else ["frozen-on-another-parser"]

    def test_nothing_is_charged_called_or_written(self) -> None:
        self.stale_packet()
        model, printed = _Model(), list[str]()
        code = self.score(model, vouch=self.as_the_machine_would, printed=printed)
        said = "\n".join(printed)
        self.assertEqual(2, code, said)
        self.assertEqual([], model.prompts)
        self.assertFalse(self.ledger_path.exists() and self.calls())
        self.assertFalse(self.summary.exists())
        self.assertFalse(self.result.exists())
        for words in (
            "io.py, project_context.py or reading.py differs from the one these cases were frozen on",
            "every one of them would be demoted",
            "check out the commit the packet was frozen on",
            "re-freeze",
            "Nothing was charged",
        ):
            self.assertIn(words, said)

    def test_it_refuses_before_the_ledger_is_even_consulted(self) -> None:
        self.stale_packet()
        with mock.patch.object(
            abstention_ledger.Ledger, "check", side_effect=AssertionError("ledger read")
        ):
            self.assertEqual(2, self.score(_Model(), vouch=self.as_the_machine_would))

    def test_the_preflight_report_says_the_score_will_refuse(self) -> None:
        self.stale_packet()
        printed: list[str] = []
        with mock.patch("builtins.print", side_effect=_collect_into(printed)):
            score_abstention.report(self.corpus(), None, vouch=self.as_the_machine_would)
        said = "\n".join(printed)
        self.assertIn("--score will refuse: this checkout's io.py", said)
        self.assertIn("1 of 2 cases carry another parser digest", said)

    def sentinel_ledger(self) -> Any:
        return mock.patch.object(
            abstention_ledger.Ledger, "check", side_effect=AssertionError("ledger read")
        )

    def test_a_recorded_claude_case_with_no_stamp_is_refused_before_the_ledger(self) -> None:
        # The stale check read `"parser" in case`, so an absent stamp passed it.
        del self.cases[0]["parser"]
        model, printed = _Model(), list[str]()
        with self.sentinel_ledger():
            code = self.score(model, vouch=self.as_the_machine_would, printed=printed)
        said = "\n".join(printed)
        self.assertEqual(2, code, said)
        self.assertEqual([], model.prompts)
        self.assertFalse(self.ledger_path.exists() and self.calls())
        self.assertIn("carry no parser stamp", said)
        self.assertIn("Nothing was charged", said)

    def test_the_report_says_a_missing_stamp_will_refuse(self) -> None:
        del self.cases[0]["parser"]
        printed: list[str] = []
        with mock.patch("builtins.print", side_effect=_collect_into(printed)):
            score_abstention.report(self.corpus(), None, vouch=self.as_the_machine_would)
        self.assertIn("--score will refuse:", "\n".join(printed))

    def test_an_unstamped_reviewed_export_claude_case_is_refused_before_the_ledger(self) -> None:
        # ReviewedExports.validate runs content_refusal, which demotes a missing stamp.
        del self.cases[0]["parser"]
        self.cases[0]["reviewed_export"] = {"manifest": "m"}
        model, printed = _Model(), list[str]()
        with self.sentinel_ledger():
            code = self.score(model, vouch=self.as_the_machine_would, printed=printed)
        self.assertEqual(2, code, "\n".join(printed))
        self.assertEqual([], model.prompts)
        self.assertIn("carry no parser stamp", "\n".join(printed))

    def test_the_report_follows_the_rule_the_score_will_apply(self) -> None:
        # A Codex producer never scores, so it rechecks nothing and refuses nothing.
        del self.cases[0]["parser"]
        printed: list[str] = []
        with mock.patch("builtins.print", side_effect=_collect_into(printed)):
            score_abstention.report(
                self.corpus(), None, vouch=self.as_the_machine_would, rechecked=False
            )
        self.assertNotIn("--score will refuse:", "\n".join(printed))

    def test_a_recorded_codex_and_a_synthetic_claude_case_may_omit_the_stamp(self) -> None:
        self.cases[0]["origin"] = "synthetic"
        self.assertNotIn("parser", _codex_case())
        codex = _codex_case()
        self.cases.append(codex)
        self.assertEqual([], score_abstention.parser_mismatch(self.corpus()))
        del self.cases[0]["parser"]
        self.assertEqual([], score_abstention.parser_mismatch(self.corpus()))

    def test_a_current_stamp_passes_the_check(self) -> None:
        self.assertEqual([], score_abstention.parser_mismatch(self.corpus()))

    def test_a_packet_this_checkout_froze_is_scored(self) -> None:
        model = _Model()
        self.score(model, vouch=self.as_the_machine_would)
        self.assertEqual(1, len(model.prompts))
        self.assertEqual(1, len(self.calls()))


class ADeclaredSyntheticCaseIsScoredAndCanFail(_Ledgered):
    """The 1dc5f86b contract: a synthetic case is marked and scored, never counted.

    89a5ec26 withheld it with the unconfirmed ones, so it could no longer fail
    a run. Only a case that claims recorded and is not confirmed is withheld.
    """

    def test_it_is_sent_charged_and_can_fail_but_never_covers(self) -> None:
        self.cases[0]["origin"] = "synthetic"
        self.marks[self.cases[0]["id"]] = {
            "goal": "abstain",
            "line_1": "abstain",
            "line_2": "abstain",
        }
        self.rubric = {
            "cases": {
                self.cases[0]["id"]: {
                    "kind": "misleading-completion",
                    "origin": "recorded",
                    "expect": {n: {"result": "unverifiable"} for n in ("goal", "line_1", "line_2")},
                }
            }
        }
        reply = _reply(
            goal=("consistent", (2,)), line_1=("consistent", (2,)), line_2=("consistent", (2,))
        )
        model = _Model((reply, "ok"))
        self.assertEqual(1, self.score(model, vouch=lambda _case: ["transcript-missing"]))
        self.assertEqual(1, len(model.prompts))
        self.assertEqual(1, len(self.calls()))
        committed = self.committed()
        self.assertEqual("failed", committed["verdict"])
        self.assertEqual(0, committed["coverage"]["claude"]["kinds"])
        self.assertEqual("synthetic", committed["rubric"]["cases"][self.cases[0]["id"]]["origin"])

    def test_a_demoted_recorded_claim_says_it_was_withheld(self) -> None:
        printed: list[str] = []
        with mock.patch("builtins.print", side_effect=_collect_into(printed)):
            score_abstention._vouched(self.cases[0], lambda _case: ["transcript-missing"])
        said = "\n".join(printed)
        self.assertIn("withheld without a model call", said)
        self.assertNotIn("scored as synthetic", said)


class FrozenIncompleteReadReplayTest(unittest.TestCase):
    def test_replay_carries_the_distinct_incomplete_pairs(self) -> None:
        case = {
            "harness": "claude",
            "tool_output": {
                "tails": {},
                "changed_after": [],
                "read_incomplete": [["call-1", "pytest"]],
            },
        }
        output = score_abstention._tool_output(case, "Anthropic", "Claude Code", {"v": 5})
        self.assertEqual(
            frozenset({("call-1", "pytest")}), getattr(output, "read_incomplete", None)
        )
        self.assertEqual(frozenset(), output.changed_after)

    def test_replay_refuses_malformed_incomplete_pairs(self) -> None:
        case = {
            "harness": "claude",
            "intent": {"goal": "Run tests", "lines": ["Tests pass"]},
            "tool_output": {"tails": {}, "changed_after": [], "read_incomplete": [["call-1"]]},
        }
        self.assertEqual("replay-bad-tool-output", score_abstention.intent_refusal(case))
