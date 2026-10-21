"""The running-turn guard's two inputs the record cannot hand over as an entry.

[the amendment](docs/design-reading-a-session.md#amended-2026-10-21-a-running-turn-is-unfinished)
reads a words-only departure at the mid-flight scope as unfinished while work goes on. A call
still in flight has no entry until its result arrives, so the press asks the transcript for the
newest call it has no result for. Every transcript here is built from the recorded field shapes
(`test_claude_checks.Transcript`): an assistant record holding a `tool_use` block, and a user
record holding the `tool_result` block that answers it. No text came from a real session.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, cast
from unittest import mock

from compass_runtime import project_context, reading, records

# Read through the module, so the loader does not collect that class a second time here.
from . import test_claude_checks

NOW_OFFSET = 600.0


def _epoch(row: dict[str, Any]) -> float:
    stamp = records.parse_ts(row["timestamp"])
    assert stamp is not None
    return stamp


class ACallStillInFlightIsFoundInTheTranscript(test_claude_checks.ClaudeChecksTestCase):
    def open_call_at(self) -> float | None:
        self.session.save(self.path)
        return project_context.claude_open_call_at(self.config, str(self.path))

    def test_a_call_with_no_result_yet_is_in_flight(self) -> None:
        self.session.bash("python3 -m pytest -q", "3 passed")
        self.session.call("Agent", {"description": "read the handler", "prompt": "read it"})
        self.assertEqual(_epoch(self.session.rows[-1]), self.open_call_at())

    def test_a_call_whose_result_arrived_is_not(self) -> None:
        call_id = self.session.call("Read", {"file_path": self.file("handler.py")})
        self.session.result(call_id, "contents")
        self.assertIsNone(self.open_call_at())

    def test_the_newest_of_two_calls_in_flight_is_the_one_named(self) -> None:
        self.session.call("Read", {"file_path": self.file("a.py")})
        self.session.call("Read", {"file_path": self.file("b.py")})
        self.assertEqual(_epoch(self.session.rows[-1]), self.open_call_at())

    def test_a_message_the_reader_sent_after_it_closes_it(self) -> None:
        # An interrupted call is never answered: the reader typed over it, so nothing runs.
        self.session.call("Read", {"file_path": self.file("a.py")})
        self.session.prompt("stop, do something else")
        self.assertIsNone(self.open_call_at())

    def test_a_question_waiting_on_the_reader_is_not_work_going_on(self) -> None:
        self.session.call("AskUserQuestion", {"questions": []})
        self.assertIsNone(self.open_call_at())

    def test_a_transcript_that_is_not_there_has_none(self) -> None:
        self.assertIsNone(project_context.claude_open_call_at(self.config, str(self.path)))


class TheReadingAsksTheTranscriptOnlyWhileTheSessionRuns(test_claude_checks.ClaudeChecksTestCase):
    """`produce` over a recorded-shape mid-call transcript: the agent said what it would do and its
    next call is still running, so the missing end is not yet a departure."""

    PLAN = "The probe still shows the wrong output. Next I rerun it and push."

    def setUp(self) -> None:
        super().setUp()
        self.session.call("Agent", {"description": "rerun the probe", "prompt": "rerun it"})
        self.session.save(self.path)
        self.opened = _epoch(self.session.rows[-1])
        self.words_at = self.opened - 120.0
        self.said_at = self.opened - 60.0

    def facts(self) -> list[dict[str, Any]]:
        source = {"harness": "claude", "sid": "s1"}
        return [
            {
                "fact_id": "f1",
                "type": "user_message",
                "by": "",
                "summary": "fix the probe and push it",
                "at": self.words_at,
                "evidence": {"source": "root transcript", "confidence": "exact"},
                "source_session": source,
            },
            {
                "fact_id": "m1",
                "type": "agent_message",
                "by": "agent",
                "summary": self.PLAN,
                reading.AGENT_WORDS_FIELD: self.PLAN,
                "at": self.said_at,
                "evidence": {"source": "root transcript", "confidence": "exact"},
                "source_session": source,
            },
        ]

    def goal_result(self, row: dict[str, Any], lookup: Any) -> str:
        revision = {
            "n": 1,
            "at": self.words_at + 1.0,
            "window_start": self.words_at,
            "goal": "Fix the probe and push it.",
            "lines": (),
        }

        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            index = next(
                line.split("]")[0].lstrip("[ ").strip()
                for line in prompt.splitlines()
                if self.PLAN in line
            )
            return (
                json.dumps(
                    {
                        "goal": {
                            "result": "departure",
                            "cites": [int(index)],
                            "detail": "It ends with the probe still failing, no rerun and no push.",
                        }
                    }
                ),
                "ok",
            )

        assessment, why, _spent = reading.produce(
            cast("Any", self.config),
            row,
            [revision],
            self.facts(),
            now=self.opened + NOW_OFFSET,
            stamp_text="read at 10:00",
            model=model,
            tool_output=reading.ToolOutput(destination="Anthropic", label="Claude Code", tails={}),
            read_agent_words=True,
            admit_turn_stop=True,
            open_call_lookup=lookup,
        )
        self.assertEqual("", why)
        return str(assessment["criteria"]["goal"]["result"])  # type: ignore[index]

    def running(self) -> dict[str, Any]:
        return {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None}

    def idle_without_a_finish(self) -> dict[str, Any]:
        return {
            "harness": "claude",
            "sid": "s1",
            "state": "idle",
            "acquisition": "event",
            "ended_at": None,
        }

    def lookup(self) -> Any:
        return lambda: project_context.claude_open_call_at(self.config, str(self.path))

    def test_a_running_session_with_a_call_in_flight_does_not_depart(self) -> None:
        self.assertEqual(
            reading.RESULT_NOT_REACHED, self.goal_result(self.running(), self.lookup())
        )

    def test_the_same_reading_with_no_call_in_flight_keeps_its_departure(self) -> None:
        self.assertEqual(reading.RESULT_DEPARTURE, self.goal_result(self.running(), lambda: None))

    def test_an_idle_press_never_asks_what_is_in_flight(self) -> None:
        # The idle press reads mid-flight too, but nothing is running: an unanswered call there is an
        # interruption, so only work already recorded after the words can excuse a departure.
        asked = mock.Mock(return_value=self.opened)
        self.assertEqual(
            reading.RESULT_DEPARTURE, self.goal_result(self.idle_without_a_finish(), asked)
        )
        asked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
