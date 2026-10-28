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
import time
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import cli, departures, reading, reading_route, unasked
from compass_runtime import observer as runtime_observer
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
                    row["result"] = result
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


class AFailureALaterPassSupersededIsNotListed(unittest.TestCase):
    def _facts(self, later: str) -> list[dict[str, Any]]:
        passed = _report("later", "passed", 4_300.0, summary=f"python3 -m pytest {later}".strip())
        return [WORDS, _report("bad", "failed", 4_200.0), passed]

    def test_a_later_whole_suite_pass_drops_the_failure_and_is_never_listed(self) -> None:
        rows = _ledger(self._facts("."))
        self.assertEqual(["w1"], [row["id"] for row in rows])

    def test_a_later_narrower_pass_leaves_the_failure_listed(self) -> None:
        rows = _ledger(self._facts("tests"))
        self.assertEqual(["w1", "bad"], [row["id"] for row in rows])

    def test_a_pass_before_the_failure_leaves_it_listed(self) -> None:
        facts = [
            WORDS,
            _report("ok", "passed", 4_100.0, summary="python3 -m pytest ."),
            _report("bad", "failed", 4_200.0),
        ]
        self.assertEqual(["w1", "bad"], [row["id"] for row in _ledger(facts)])


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
        partial: bool = False,
        passing_calls: frozenset[str] = frozenset(),
        counts: dict[str, int] | None = None,
        coverage: dict[str, Any] | None = None,
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
                masked_values_partial=partial,
                passing_calls=passing_calls,
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
            command_counts_for=lambda _state, _row: counts or {},
            record_coverage_for=lambda _state, _row: coverage or {},
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

    def _tool_output_for(self, *, partial: bool) -> Any:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        self._consider(self._lane(facts, {}, partial=partial))
        return self.kwargs[0]["tool_output"]

    def test_a_press_that_dropped_masked_values_says_so_to_the_reading(self) -> None:
        self.assertTrue(self._tool_output_for(partial=True).masked_values_partial)

    def test_a_press_that_kept_every_masked_value_says_nothing_was_dropped(self) -> None:
        self.assertFalse(self._tool_output_for(partial=False).masked_values_partial)

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

    def test_a_superseded_failure_makes_no_model_call_citing_it(self) -> None:
        facts = [
            WORDS,
            _report("bad", "failed", 4_200.0),
            _report("later", "passed", 4_300.0, summary="python3 -m pytest ."),
        ]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})

        self._consider(lane)

        for prompt in self.prompts:
            self.assertNotIn("tests/bad.py", prompt)
            self.assertNotIn(PASS_TAIL, prompt)
        self.assertEqual([], [c for c in departures.load(self.config) if c.get("constraint")])

    def test_the_prompt_says_passes_are_withheld_and_a_pressed_reading_does_not(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})
        self._consider(lane)
        (prompt,) = self.prompts
        self.assertIn(reading.FAILURES_ONLY_RULE, prompt)
        pressed, _ = reading.build_prompt(_ledger(facts), goal="add retry", max_bytes=20_000)
        self.assertNotIn(reading.FAILURES_ONLY_RULE, pressed)

    def test_the_tail_of_a_call_with_no_pass_is_still_sent(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(
            facts,
            {"goal": {"result": "unverifiable", "cites": []}},
            passing_calls=frozenset({"call-elsewhere"}),
        )

        self._consider(lane)

        (prompt,) = self.prompts
        self.assertIn("AssertionError", prompt)

    def _press_of(self, command: str, output: str, *, is_error: bool = True) -> PressChecks:
        from compass_runtime import project_context  # noqa: PLC0415

        lines = [
            {
                "type": "assistant",
                "timestamp": "2026-10-20T10:00:00Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "c1",
                            "name": "Bash",
                            "input": {"command": command},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "timestamp": "2026-10-20T10:00:01Z",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "c1",
                            "is_error": is_error,
                            "content": output,
                        }
                    ]
                },
            },
        ]
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "t.jsonl"
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n")
            config = build_runtime_config(
                environ={"HOME": root},
                platform_name="linux",
                os_name="posix",
                launcher_path=Path(root) / "server.py",
            )
            return project_context.claude_check_press(config, str(path))

    def _sent_tails(self, command: str, output: str) -> dict[str, str]:
        press = self._press_of(command, output)
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})
        lane.press_for = lambda *_a: press
        self._consider(lane)
        return dict(self.kwargs[0]["tool_output"].tails)

    def test_a_failing_chained_call_sends_its_line_and_no_tail(self) -> None:
        output = f"Exit code 1\nAll checks passed!\n{TAIL}\n=== 1 failed in 0.2s ==="
        tails = self._sent_tails("ruff check . && python3 -m pytest tests/b.py -x", output)
        self.assertEqual({}, tails)
        (prompt,) = self.prompts
        self.assertNotIn("All checks passed!", prompt)
        self.assertIn("tests/bad.py", prompt)

    def test_a_failing_single_check_call_still_sends_its_tail(self) -> None:
        tails = self._sent_tails("python3 -m pytest tests/b.py", f"Exit code 1\n{TAIL}")
        self.assertIn("c1", tails)
        self.assertIn("AssertionError", tails["c1"])

    def test_a_single_check_call_naming_two_files_still_sends_its_tail(self) -> None:
        tails = self._sent_tails("python3 -m pytest tests/a.py tests/b.py", f"Exit code 1\n{TAIL}")
        self.assertIn("c1", tails)

    def test_the_tally_names_every_call_that_held_a_pass(self) -> None:
        press = self._press_of("python3 -m pytest tests/a.py", "3 passed in 0.1s", is_error=False)
        self.assertIn("c1", press.passing_calls)

    def _cutoff_through_lane(self, facts: list[dict[str, Any]]) -> str:
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
        return str(seen[0]["cutoff"])

    def test_the_stored_cutoff_counts_one_failure_a_later_pass_superseded(self) -> None:
        listed = _report("bad", "failed", 4_300.0, summary="python3 -m pytest tests/bad.py")
        one = self._cutoff_through_lane(
            [
                WORDS,
                _report("old", "failed", 4_100.0, summary="python3 -m pytest ."),
                _report("later", "passed", 4_150.0, summary="python3 -m pytest ."),
                listed,
            ]
        )
        self.assertIn("A failed check was recorded and a later passing run superseded it.", one)

    def test_the_stored_cutoff_counts_two_failures_later_passes_superseded(self) -> None:
        listed = _report("bad", "failed", 4_300.0, summary="python3 -m pytest tests/bad.py")
        two = self._cutoff_through_lane(
            [
                WORDS,
                _report("a", "failed", 4_100.0),
                _report("b", "failed", 4_110.0, summary="python3 -m pytest tests/b.py"),
                _report("later", "passed", 4_150.0, summary="python3 -m pytest ."),
                listed,
            ]
        )
        self.assertIn("2 failed checks were recorded and later passing runs superseded them.", two)

    def test_the_default_lookups_carry_counts_and_coverage_from_the_transcript(self) -> None:
        from compass_runtime import project_context  # noqa: PLC0415

        root = Path(self.temp.name)
        path = root / "t.jsonl"
        path.write_text(
            json.dumps({"type": "user", "timestamp": "2026-10-20T10:00:00Z"}) + "\n",
            encoding="utf-8",
        )
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = unasked.Lane(
            self.config,
            popup_notifier=self._popup,
            diagnostic_sink=lambda _line: None,
            clock=lambda: NOW,
            spawn=lambda work: work(),
            press_for=lambda *_a: PressChecks({"call-bad": TAIL}, frozenset()),
        )
        row = {"harness": "claude", "sid": "s-1"}
        context = {
            "semantic": {"facts": facts},
            "sources": {
                "work": {
                    "tool_reports": [
                        {
                            "harness": "claude",
                            "sid": "s-1",
                            "other_commands": 5,
                            "read_only_commands": 2,
                        }
                    ]
                }
            },
        }
        with (
            mock.patch.object(project_context, "collect", return_value=context),
            mock.patch.object(runtime_observer, "resolve_transcript", return_value=str(path)),
        ):
            self.assertEqual(facts, list(lane._facts(self.state, row, NOW)))
            counts = lane._command_counts(self.state, row)
            coverage = lane._record_coverage(self.state, row)
            self.assertEqual({"other_commands": 5, "read_only_commands": 2}, dict(counts))
            self.assertIs(False, coverage["tail_truncated"])
            self.assertIsNotNone(coverage["tail_start"])
            # The transcript grew after the facts were collected: the reach is unknown.
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"type": "user", "timestamp": "2026-10-20T10:05:00Z"}) + "\n"
                )
            grown = lane._record_coverage(self.state, row)
        self.assertEqual({"tail_truncated": None, "tail_start": None}, dict(grown))

    def test_a_coverage_lookup_with_no_stamp_taken_is_unknown(self) -> None:
        lane = unasked.Lane(self.config, popup_notifier=self._popup)
        row = {"harness": "claude", "sid": "s-2"}
        self.assertEqual(
            {"tail_truncated": None, "tail_start": None},
            dict(lane._record_coverage(self.state, row)),
        )

    def test_a_withheld_reading_leaves_no_counts_or_stamp_behind(self) -> None:
        lane = self._lane([WORDS], {})
        lane._counts[("claude", "s-1")] = {"other_commands": 1}
        lane._stamps[("claude", "s-1")] = (1, 2, 3, 4)
        with mock.patch.object(reading_route, "destination", return_value=""):
            self._consider(lane)
        self.assertEqual({}, lane._counts)
        self.assertEqual({}, lane._stamps)

    def test_a_destination_that_cannot_be_named_sends_no_check(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})

        with mock.patch.object(reading_route, "destination", return_value=""):
            self._consider(lane)

        self.assertIsNone(self.kwargs[0]["tool_output"])
        for prompt in self.prompts:
            self.assertNotIn("tests/bad.py", prompt)

    def _unread_flags(self, facts: list[dict[str, Any]]) -> list[bool]:
        seen: list[bool] = []
        real = reading._resolve_one

        def spy(*args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs["checks_unread"])
            return real(*args, **kwargs)

        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})
        with mock.patch.object(reading, "_resolve_one", spy):
            self._consider(lane)
        return seen

    def test_produce_flags_the_checks_it_left_out_as_unread(self) -> None:
        facts = [WORDS, _report("ok", "passed", 4_100.0), _report("bad", "failed", 4_200.0)]
        flags = self._unread_flags(facts)
        self.assertTrue(flags)
        self.assertTrue(all(flags))

    def test_produce_flags_nothing_unread_when_every_report_was_sent(self) -> None:
        flags = self._unread_flags([WORDS, _report("bad", "failed", 4_200.0)])
        self.assertTrue(flags)
        self.assertFalse(any(flags))

    def test_the_codex_fallback_stays_on_the_words_its_allow_covers(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})

        with mock.patch.object(
            shutil, "which", side_effect=lambda name, **_: "/bin/codex" if name == "codex" else None
        ):
            self._consider(lane)

        self.assertIsNone(self.kwargs[0]["tool_output"])
        for prompt in self.prompts:
            self.assertNotIn(reading.FAILURES_ONLY_RULE, prompt)

    def test_the_rule_is_added_where_the_lane_admitted_tool_reports(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})
        self._consider(lane)
        self.assertIn(reading.FAILURES_ONLY_RULE, self.prompts[0])

    def test_the_lane_hands_produce_both_lookups_and_the_reading_records_the_counts(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        seen: list[Any] = []

        def produce(config: Any, row: Any, revisions: Any, found: Any, **kwargs: Any) -> Any:
            self.kwargs.append(kwargs)
            result = reading.produce(
                config,
                row,
                revisions,
                found,
                **{**kwargs, "model": lambda _p, **_k: ("{}", "ok"), "now": NOW},
            )
            seen.append(result[0])
            return result

        lane = self._lane(
            facts,
            {},
            counts={"other_commands": 7, "read_only_commands": 4},
            coverage={"tail_truncated": False, "tail_start": 3_900.0},
        )
        lane.produce = produce
        self._consider(lane)

        self.assertIsNotNone(self.kwargs[0]["command_counts_lookup"])
        self.assertIsNotNone(self.kwargs[0]["record_coverage_lookup"])
        coverage = seen[0]["coverage"]
        self.assertEqual(7, coverage["other_commands"])
        self.assertEqual(4, coverage["read_only_commands"])
        self.assertIs(False, coverage["tail_truncated"])

    def test_the_lane_carries_what_the_press_holds_to_find_a_quoted_output(self) -> None:
        facts = [WORDS, _report("bad", "failed", 4_200.0)]
        quotable = {("call-bad", "python3 -m pytest tests/bad.py"): TAIL}
        lane = self._lane(facts, {"goal": {"result": "unverifiable", "cites": []}})
        lane.press_for = lambda *_a: PressChecks({"call-bad": TAIL}, frozenset(), quotable=quotable)
        self._consider(lane)
        self.assertEqual(quotable, dict(self.kwargs[0]["tool_output"].quotable))


class TheCutoffAndTheUnreadFlagSayWhatWasWithheld(unittest.TestCase):
    def _cutoff_and_unsent(self, facts: list[dict[str, Any]]) -> tuple[Any, ...]:
        ledger, superseded = reading.failure_ledger(
            facts,
            "claude",
            "s-1",
            cap_chars=reading.LEDGER_SUMMARY_CAP_CHARS,
            tool_output={},
            changed_after=frozenset(),
            read_incomplete=frozenset(),
            read_agent_words=False,
        )
        note = reading._unsent_checks_note(
            cast("Any", object()),
            facts,
            "claude",
            "s-1",
            True,
            True,
            sent_failure=any(row["type"] == "tool_report" for row in ledger),
            superseded=superseded,
        )
        unsent = reading._has_unsent_reports(facts, "claude", "s-1", ledger, True, True)
        return note, unsent

    def test_a_failure_a_later_pass_superseded_is_said_so_and_not_called_unrecorded(self) -> None:
        note, _ = self._cutoff_and_unsent(
            [
                WORDS,
                _report("bad", "failed", 4_200.0),
                _report("later", "passed", 4_300.0, summary="python3 -m pytest ."),
            ]
        )
        self.assertIn("A failed check was recorded and a later passing run superseded it", note)
        self.assertNotIn("No failed check or command was recorded", note)

    def test_a_superseded_failure_beside_a_listed_one_is_counted_in_the_sent_sentence(self) -> None:
        note, _ = self._cutoff_and_unsent(
            [
                WORDS,
                _report("old", "failed", 4_100.0, summary="python3 -m pytest ."),
                _report("later", "passed", 4_150.0, summary="python3 -m pytest ."),
                _report("bad", "failed", 4_200.0, summary="python3 -m pytest tests/bad.py"),
            ]
        )
        self.assertIn("Only the failed checks and commands", note)
        self.assertIn("A failed check was recorded and a later passing run superseded it", note)

    def test_two_superseded_failures_are_counted(self) -> None:
        note, _ = self._cutoff_and_unsent(
            [
                WORDS,
                _report("a", "failed", 4_100.0),
                _report("b", "failed", 4_110.0, summary="python3 -m pytest tests/b.py"),
                _report("later", "passed", 4_300.0, summary="python3 -m pytest ."),
            ]
        )
        self.assertIn("2 failed checks were recorded and later passing runs superseded them", note)

    def test_a_failure_with_a_pass_leaves_the_pass_unsent(self) -> None:
        note, unsent = self._cutoff_and_unsent(
            [WORDS, _report("ok", "passed", 4_100.0), _report("bad", "failed", 4_200.0)]
        )
        self.assertTrue(unsent)
        self.assertIn("Only the failed checks and commands", note)

    def test_a_session_with_no_report_has_nothing_unsent(self) -> None:
        _, unsent = self._cutoff_and_unsent([WORDS])
        self.assertFalse(unsent)

    def _window_note(self, facts: list[dict[str, Any]], stopped_at: float) -> str:
        ledger, superseded = reading.failure_ledger(
            facts,
            "claude",
            "s-1",
            cap_chars=reading.LEDGER_SUMMARY_CAP_CHARS,
            tool_output={},
            changed_after=frozenset(),
            read_incomplete=frozenset(),
            read_agent_words=False,
        )
        row = {"harness": "claude", "finished_at": stopped_at}
        kept, _stop, _left, withheld = reading._ledger_to_read(
            ledger, row, reading.SCOPE_LAST_TURN, 4_000.0
        )
        self.assertEqual("", withheld)
        return reading._unsent_checks_note(
            cast("Any", object()),
            facts,
            "claude",
            "s-1",
            True,
            True,
            sent_failure=any(entry["type"] == "tool_report" for entry in kept),
            superseded=superseded,
            outside_window=reading._failures_left_out(ledger, kept),
        )

    def test_a_failure_after_the_stop_is_not_called_unrecorded(self) -> None:
        note = self._window_note([WORDS, _report("bad", "failed", 4_200.0)], stopped_at=4_100.0)
        self.assertIn("A failed check was recorded outside the window this check read", note)
        self.assertNotIn("No failed check or command was recorded", note)

    def test_two_failures_outside_the_window_are_counted(self) -> None:
        note = self._window_note(
            [
                WORDS,
                _report("a", "failed", 4_200.0),
                _report("b", "failed", 4_300.0, summary="python3 -m pytest tests/b.py"),
            ],
            stopped_at=4_100.0,
        )
        self.assertIn("2 failed checks were recorded outside the window this check read", note)

    def test_passes_only_says_no_failure_was_recorded(self) -> None:
        note, unsent = self._cutoff_and_unsent([WORDS, _report("ok", "passed", 4_100.0)])
        self.assertTrue(unsent)
        self.assertIn("No failed check or command was recorded", note)


class TheStalenessCheckStaysLinear(unittest.TestCase):
    def test_a_long_session_of_failures_and_passes_is_decided_quickly(self) -> None:
        facts = [WORDS]
        for i in range(1_500):
            facts.append(
                _report(f"f{i}", "failed", 4_100.0 + i, summary=f"python3 -m pytest tests/f{i}.py")
            )
            facts.append(
                _report(f"p{i}", "passed", 4_100.5 + i, summary=f"python3 -m pytest tests/p{i}.py")
            )
        started = time.monotonic()
        rows = _ledger(facts)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(1_500, len([r for r in rows if r["type"] == "tool_report"]))


class TheOperatorHelpDoesNotDenyTheFailureTail(unittest.TestCase):
    def test_the_flag_help_says_a_failed_check_goes_and_a_pass_never_does(self) -> None:
        help_text = " ".join(cli.build_parser().format_help().split())
        self.assertNotIn("outcome lines or tool output", help_text)
        self.assertIn("one that passed never does", help_text)


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
