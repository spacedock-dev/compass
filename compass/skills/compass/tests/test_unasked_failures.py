"""The unasked lane reads a session's failed results, and never a pass.

[DEC-31](docs/design-reading-a-session.md#dec-31-the-text-of-a-command-that-is-not-a-check-may-leave-the-machine-by-vendor)
item 5 opens item 10 of the checks ruling for failed results only: a failure raises a departure and a
pass reassures, which the lane never does. Every fixture is synthetic.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import departures, reading, reading_route, unasked
from compass_runtime.config import build_runtime_config
from compass_runtime.project_context import PressChecks
from compass_runtime.state import build_runtime_state

from .test_subject_consumers import ALL_SUBJECTS, fact

SESSION = {"harness": "claude", "sid": "s-1"}
TAIL = "FAILED tests/test_retry.py::test_backoff - AssertionError: 2 != 3"
PASS_TAIL = "3 passed in 0.12s"  # noqa: S105 - a test runner line, not a credential
NOW = 5_000.0


def _report(fact_id: str, result: str, at: float, **extra: Any) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": "tool_report",
        "subject": "check",
        "result": result,
        "result_source": "flag",
        "summary": f"python3 -m pytest tests/{fact_id}.py",
        "at": at,
        "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
        "source_session": dict(SESSION),
        "branch": {"harness": "claude", "sid": "s-1", "record_id": f"call-{fact_id}"},
        **extra,
    }


WORDS = {
    "fact_id": "w1",
    "type": "user_message",
    "by": "",
    "summary": "add retry to the webhook",
    "at": 4_000.0,
    "evidence": {"source": "root transcript", "confidence": "exact"},
    "source_session": dict(SESSION),
}


def _ledger(facts: list[dict[str, Any]], **kwargs: Any) -> tuple[Any, ...]:
    return reading.build_ledger(facts, "claude", "s-1", tool_output={}, failed_only=True, **kwargs)


class OnlyAFailedResultReachesTheLedger(unittest.TestCase):
    def test_every_subject_and_result_is_listed_only_when_it_is_a_failure_that_can_fail(
        self,
    ) -> None:
        for subject in ALL_SUBJECTS:
            for result in ("failed", "passed", ""):
                with self.subTest(subject=subject, result=result):
                    row = {**fact(subject, result or "passed"), "source_session": dict(SESSION)}
                    row["result"] = result if subject in reading.RESULT_SUBJECTS else ""
                    listed = bool(_ledger([row]))
                    self.assertEqual(
                        listed,
                        result == "failed" and reading.admits("unasked_ledger", subject),
                    )

    def test_the_table_admits_exactly_the_three_subjects_that_carry_a_result(self) -> None:
        self.assertEqual(reading.RESULT_SUBJECTS, reading.CONSUMER_SUBJECTS["unasked_ledger"])

    def test_a_command_that_cannot_fail_is_not_listed_whatever_it_reported(self) -> None:
        row = {**fact("command", "failed"), "cannot_fail": True, "source_session": dict(SESSION)}
        self.assertEqual((), _ledger([row]))

    def test_a_pass_and_a_no_result_run_are_not_listed_beside_a_failure(self) -> None:
        facts = [
            WORDS,
            _report("ok", "passed", 4_100.0),
            _report("none", "", 4_150.0),
            _report("bad", "failed", 4_200.0),
        ]
        self.assertEqual(["w1", "bad"], [row["id"] for row in _ledger(facts)])

    def test_the_tail_of_a_failure_is_carried_and_the_tail_of_a_pass_is_not(self) -> None:
        facts = [_report("ok", "passed", 4_100.0), _report("bad", "failed", 4_200.0)]
        rows = reading.build_ledger(
            facts,
            "claude",
            "s-1",
            tool_output={"call-bad": TAIL, "call-ok": PASS_TAIL},
            failed_only=True,
        )
        text = json.dumps(rows)
        self.assertIn("AssertionError", text)
        self.assertNotIn(PASS_TAIL, text)

    def test_without_tool_output_a_failure_is_still_not_listed(self) -> None:
        rows = reading.build_ledger(
            [_report("bad", "failed", 4_200.0)], "claude", "s-1", failed_only=True
        )
        self.assertEqual((), rows)

    def test_the_default_caller_is_unchanged(self) -> None:
        rows = reading.build_ledger(
            [_report("ok", "passed", 4_100.0)], "claude", "s-1", tool_output={}
        )
        self.assertEqual(["ok"], [row["id"] for row in rows])


class TheLaneIsHandedFailuresAndNothingElse(unittest.TestCase):
    """The lane, the producer and the prompt, with only the model replaced."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
            unasked_enabled=True,
        )
        self.config = dataclasses.replace(config, state_dir=root / "state")
        self.state = build_runtime_state(self.config, started=1_000.0)
        self.prompts: list[str] = []
        self.kwargs: list[dict[str, Any]] = []
        self.popups: list[tuple[str, str]] = []
        for patcher in (
            mock.patch.object(shutil, "which", side_effect=lambda name, **_: f"/bin/{name}"),
            mock.patch.object(reading_route, "destination", return_value="api.anthropic.com"),
            mock.patch.object(reading, "claim", return_value=True),
            mock.patch.object(reading, "release"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _popup(self, title: str, message: str) -> str:
        self.popups.append((title, message))
        return "ok"

    def _lane(
        self,
        facts: list[dict[str, Any]],
        answer: dict[str, Any],
        *,
        tails: dict[str, str] | None = None,
    ) -> unasked.Lane:
        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            self.prompts.append(prompt)
            return json.dumps(answer), "ok"

        def produce(config: Any, row: Any, revisions: Any, found: Any, **kwargs: Any) -> Any:
            self.kwargs.append(kwargs)
            return reading.produce(
                config, row, revisions, found, **{**kwargs, "model": model, "now": NOW}
            )

        def press(*_args: Any) -> PressChecks:
            return PressChecks(
                tails or {"call-bad": TAIL, "call-ok": PASS_TAIL},
                frozenset(),
                masked_values=frozenset(),
            )

        return unasked.Lane(
            self.config,
            popup_notifier=self._popup,
            diagnostic_sink=lambda _line: None,
            clock=lambda: NOW,
            produce=produce,
            facts_for=lambda _state, _row, _now: facts,
            spawn=lambda work: work(),
            press_for=press,
        )

    def _consider(self, lane: unasked.Lane) -> None:
        entry = {
            "harness": "claude",
            "sid": "s-1",
            "revisions": (
                {"n": 1, "goal": "add retry to the webhook", "lines": (), "at": 4_000.0},
            ),
        }
        row = {"harness": "claude", "sid": "s-1", "state": "working", "project": "acme/widgets"}
        lane.consider(self.state, [row], [cast("Any", entry)], now=NOW)
        ended = {**row, "state": "idle", "ended_at": 4_900.0}
        lane.consider(self.state, [ended], [cast("Any", entry)], now=NOW)

    def test_a_failed_check_after_the_goal_raises_a_departure_citing_it(self) -> None:
        facts = [WORDS, _report("ok", "passed", 4_100.0), _report("bad", "failed", 4_200.0)]
        answer = {"goal": {"result": "departure", "cites": [2], "detail": "the retry test failed"}}
        lane = self._lane(facts, answer)

        self._consider(lane)

        (prompt,) = self.prompts
        self.assertIn(json.dumps(TAIL), prompt)
        self.assertNotIn(PASS_TAIL, prompt)
        self.assertNotIn("tests/ok.py", prompt)
        raised = [c for c in departures.load(self.config) if c.get("constraint")]
        self.assertEqual(1, len(raised))
        self.assertEqual("bad", raised[0]["evidence"])
        self.assertEqual(1, len(self.popups))
        self.assertTrue(self.kwargs[0]["failures_only"])

    def test_a_session_with_only_passes_sends_no_check_and_no_tail(self) -> None:
        facts = [WORDS, _report("ok", "passed", 4_100.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})

        self._consider(lane)

        (prompt,) = self.prompts
        self.assertNotIn("tests/ok.py", prompt)
        self.assertNotIn(PASS_TAIL, prompt)

    def test_a_pass_never_reaches_the_prompt_whatever_the_press_read(self) -> None:
        facts = [
            WORDS,
            _report("ok", "passed", 4_100.0),
            _report("ci", "passed", 4_120.0, subject="ci_command"),
            _report("run", "", 4_130.0, subject="command"),
            _report("bad", "failed", 4_200.0),
        ]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})

        self._consider(lane)

        (prompt,) = self.prompts
        for passed in ("tests/ok.py", "tests/ci.py", "tests/run.py", PASS_TAIL):
            self.assertNotIn(passed, prompt)
        self.assertIn("tests/bad.py", prompt)

    def test_the_reading_says_that_only_failures_were_sent(self) -> None:
        facts = [WORDS, _report("ok", "passed", 4_100.0), _report("bad", "failed", 4_200.0)]
        seen: list[Any] = []

        def produce(config: Any, row: Any, revisions: Any, found: Any, **kwargs: Any) -> Any:
            result = reading.produce(
                config,
                row,
                revisions,
                found,
                **{**kwargs, "model": lambda _p, **_k: ("{}", "ok"), "now": NOW},
            )
            seen.append(result[0])
            return result

        lane = self._lane(facts, {})
        lane.produce = produce
        self._consider(lane)

        self.assertIn("failed checks and commands", seen[0]["cutoff"])

    def test_a_destination_that_cannot_be_named_sends_no_check(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})

        with mock.patch.object(reading_route, "destination", return_value=""):
            self._consider(lane)

        self.assertIsNone(self.kwargs[0]["tool_output"])
        for prompt in self.prompts:
            self.assertNotIn("tests/bad.py", prompt)

    def test_the_codex_fallback_stays_on_the_words_its_allow_covers(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})

        with mock.patch.object(
            shutil, "which", side_effect=lambda name, **_: "/bin/codex" if name == "codex" else None
        ):
            self._consider(lane)

        self.assertIsNone(self.kwargs[0]["tool_output"])


class TheDisclosureNamesWhatTheLaneSends(unittest.TestCase):
    def _route(self, harness: str, where: str) -> Any:
        with (
            mock.patch.object(reading_route, "destination", return_value=where),
            mock.patch.object(shutil, "which", side_effect=lambda name, **_: f"/bin/{name}"),
        ):
            return reading_route.resolve(harness, unasked=True)

    def test_a_claude_session_discloses_failed_results_and_says_passes_stay(self) -> None:
        parts = " ".join(reading_route.unasked_parts(self._route("claude", "api.anthropic.com")))
        self.assertIn("failed", parts)
        self.assertIn("Nothing that passed is sent", parts)

    def test_an_unnameable_destination_or_another_harness_discloses_none(self) -> None:
        for harness, where in (("claude", ""), ("pi", "api.anthropic.com")):
            with self.subTest(harness=harness, where=where):
                parts = " ".join(reading_route.unasked_parts(self._route(harness, where)))
                self.assertNotIn("Nothing that passed is sent", parts)


if __name__ == "__main__":
    unittest.main()
