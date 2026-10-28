"""Text a "goal met" reason quotes, found in the output of a check Compass recorded.

The evaluator read the transcript, so its quote is in the transcript by construction and a match
anywhere proves nothing: `echo "coverage ok"` would satisfy it. Only the output a recorded check's
own rules attribute to that one check is searched, and a match is worded as where the text is,
never as a pass.
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar, cast

from compass_runtime import annotations as annotation_store
from compass_runtime import project_context, reading

from . import test_reading as base
from .test_ci_read import GOAL_URL, GREEN, record_with
from .test_claude_checks import SHORT, ClaudeChecksTestCase
from .test_goal_verdict import GOAL, VERDICT_AT, goal_row
from .test_reading_record_guards import write_fact

OUTPUT = "Ran 412 tests in 3.1s"


class TheAttributedOutputOfARecordedCheckIsHeldForThePress(ClaudeChecksTestCase):
    def quotable(self) -> dict[tuple[str, str], str]:
        self.session.save(self.path)
        return dict(project_context.claude_check_press(self.config, str(self.path)).quotable)

    def test_a_single_unpiped_check_is_held_under_its_call_and_line(self) -> None:
        call = self.session.bash("pytest", f"{OUTPUT}\n412 passed")
        self.assertEqual({(call, "pytest"): f"{OUTPUT}\n412 passed"}, self.quotable())

    def test_an_echo_beside_the_check_is_never_held(self) -> None:
        self.session.bash(f"echo '{OUTPUT}' && pytest", f"{OUTPUT}\n412 passed")
        self.session.bash("pytest; echo done-printing-text", "412 passed\ndone-printing-text")
        self.assertEqual({}, self.quotable())

    def test_an_echo_alone_is_no_check_and_holds_nothing(self) -> None:
        self.session.bash(f"echo '{OUTPUT}'", OUTPUT)
        self.assertEqual({}, self.quotable())

    def test_a_read_of_a_file_holds_nothing(self) -> None:
        call = self.session.call("Read", {"file_path": self.file("notes.txt")})
        self.session.result(call, OUTPUT)
        self.session.bash(f"cat notes.txt && grep -n '{OUTPUT}' notes.txt", OUTPUT)
        self.assertEqual({}, self.quotable())

    def test_two_checks_in_one_call_hold_nothing(self) -> None:
        self.session.bash("pytest && ruff check .", f"{OUTPUT}\nAll checks passed!")
        self.assertEqual({}, self.quotable())

    def test_a_check_followed_by_a_command_that_may_change_files_is_not_held(self) -> None:
        self.session.bash("pytest", OUTPUT)
        self.session.bash("ruff format src", "1 file reformatted")
        self.assertEqual({}, self.quotable())

    def test_only_the_latest_run_of_a_check_is_held(self) -> None:
        self.session.bash("pytest", "first run output here", is_error=True)
        last = self.session.bash("pytest", OUTPUT)
        self.assertEqual({(last, "pytest"): OUTPUT}, self.quotable())

    def test_a_tier_3_command_holds_nothing(self) -> None:
        self.session.bash("./deploy.sh", OUTPUT)
        self.assertEqual({}, self.quotable())

    def test_a_background_check_holds_nothing(self) -> None:
        self.session.bash("pytest", OUTPUT, run_in_background=True)
        self.assertEqual({}, self.quotable())

    def test_a_check_that_cannot_fail_holds_nothing(self) -> None:
        self.session.bash("pytest || true", OUTPUT)
        self.assertEqual({}, self.quotable())

    def test_a_write_after_the_check_is_left_to_the_verdicts_stale_mark(self) -> None:
        call = self.session.bash("pytest", OUTPUT)
        write = self.session.call("Write", {"file_path": self.file("a.md"), "content": "x"})
        self.session.result(write, "ok")
        self.assertEqual({(call, "pytest"): OUTPUT}, self.quotable())

    def test_the_press_output_reaches_a_verdict_through_the_real_facts(self) -> None:
        call = self.session.bash("pytest -q", f"{OUTPUT}\n412 passed")
        self.session.save(self.path)
        events, _ = project_context.claude_tool_reports(self.config, str(self.path), SHORT)
        facts = []
        for event in events:
            fact = project_context._semantic_fact_from_event(
                event, event["kind"], project_context._SEMANTIC_FACT_TYPES[event["kind"]], ""
            )
            fact["source_session"] = {"harness": "claude", "sid": SHORT}
            facts.append(fact)
        press = project_context.claude_check_press(self.config, str(self.path))
        self.assertEqual({(call, "pytest -q")}, set(press.quotable))
        recorded = reading.recorded_from(
            facts,
            "claude",
            SHORT,
            tool_output=reading.ToolOutput(destination="", label="x", quotable=press.quotable),
        )
        (held,) = recorded.outputs.values()
        self.assertEqual("pytest -q", held.line)
        stamp = recorded.checks[0]["at"]
        cited, count = reading._quoted_in_checks(
            f'it printed "{OUTPUT}"', recorded, stamp - 1, stamp + 60
        )
        self.assertEqual(([recorded.checks[0]["id"]], 1), (cited, count))

    def test_a_credential_in_the_output_is_redacted_before_it_is_held(self) -> None:
        self.session.bash("pytest", f"token=ghp_{'a1B2c3D4e5' * 4} {OUTPUT}")
        held = next(iter(self.quotable().values()))
        self.assertNotIn("ghp_", held)


def quoting(*spans: str, reason: str = "") -> str:
    return (reason or "the log reads ") + " and ".join(f'"{s}"' for s in spans)


class AQuoteInARecordedChecksOutputIsSaidToBeThere(base.AClaudeCodeReadingProducer):
    ANSWER: ClassVar[dict[str, Any]] = {
        "goal": {"result": "consistent", "cites": [1], "detail": ""}
    }

    def _verdict(
        self,
        facts: list[dict[str, Any]],
        reason: str,
        outputs: dict[tuple[str, str], str] | None = None,
        *,
        row: dict[str, Any] | None = None,
        ci: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        output = (
            reading.ToolOutput(destination="", label="x", quotable=outputs)
            if outputs is not None
            else None
        )
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            row or goal_row(reason),
            [{"n": 1, "at": 50.0, "goal": GOAL, "lines": []}],
            [base.WORDS_FACT, *facts],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps(self.ANSWER)),
            read_lines=True,
            read_agent_words=True,
            tool_output=output,
            ci=ci,
        )
        self.assertEqual("", why)
        found = cast("dict[str, Any]", assessment)
        return found, found["goal_verdict"]

    def _check(self, **kw: Any) -> dict[str, Any]:
        return base.check_fact(result="passed", at=130.0, summary="pytest -q", **kw)

    CALL = ("call-1", "pytest -q")

    def assertNoQuote(self, verdict: dict[str, Any]) -> None:  # noqa: N802
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, verdict["check"])
        self.assertNotEqual(reading.GOAL_VERDICT_QUOTED, verdict["why"])
        self.assertNotIn("quoted", verdict)

    def test_a_quote_in_one_recorded_checks_output_names_that_check(self) -> None:
        _read, verdict = self._verdict(
            [self._check()], quoting(OUTPUT), {self.CALL: f"{OUTPUT}\n412 passed"}
        )
        self.assertEqual(
            {
                "at": VERDICT_AT,
                "check": reading.GOAL_VERDICT_UNCONFIRMED,
                "why": reading.GOAL_VERDICT_QUOTED,
                "cites": ("check-1",),
                "quoted": 1,
            },
            verdict,
        )

    def test_the_match_ignores_case_and_runs_of_whitespace(self) -> None:
        _read, verdict = self._verdict(
            [self._check()], quoting("ran 412   TESTS in 3.1s"), {self.CALL: OUTPUT}
        )
        self.assertEqual(reading.GOAL_VERDICT_QUOTED, verdict["why"])

    def test_a_quote_nothing_recorded_printed_is_not_found(self) -> None:
        _read, verdict = self._verdict(
            [self._check()], quoting("Ran 999 tests in 1.0s"), {self.CALL: OUTPUT}
        )
        self.assertNoQuote(verdict)
        self.assertNotIn("quoted", verdict)

    def test_output_held_for_no_recorded_check_is_never_searched(self) -> None:
        # The echo case: no check fact, so a press holds no output for it and nothing matches.
        _read, verdict = self._verdict([], quoting(OUTPUT), {("call-9", "echo"): OUTPUT})
        self.assertNotEqual(reading.GOAL_VERDICT_QUOTED, verdict["why"])
        self.assertNoQuote(verdict)

    def test_a_check_after_the_verdict_cannot_be_what_the_evaluator_quoted(self) -> None:
        late = base.check_fact(result="passed", at=VERDICT_AT + 5, summary="pytest -q")
        _read, verdict = self._verdict([late], quoting(OUTPUT), {self.CALL: OUTPUT})
        self.assertNoQuote(verdict)

    def test_a_check_that_files_changed_after_is_not_searched(self) -> None:
        for aged in ({"changed_after": True}, {"before_last_change": True}):
            with self.subTest(aged=aged):
                _read, verdict = self._verdict(
                    [{**self._check(), **aged}], quoting(OUTPUT), {self.CALL: OUTPUT}
                )
                self.assertNoQuote(verdict)

    def test_spans_of_only_result_words_and_short_spans_are_ignored(self) -> None:
        for spans in (
            ("pass",),
            ("ok", "passed"),
            ("All OK",),
            ("Ran 4",),
            ("All checks passed!",),
            ("zero errors found",),
            ("no issues found",),
        ):
            with self.subTest(spans=spans):
                _read, verdict = self._verdict(
                    [self._check()],
                    quoting(*spans),
                    {
                        self.CALL: "pass ok passed All OK tests ok Ran 4 tests All checks passed! zero errors found no issues found"
                    },
                )
                self.assertNoQuote(verdict)

    def test_a_file_or_command_in_code_formatting_is_no_quote_of_output(self) -> None:
        for text in (
            "I created `docs/overview.md` as asked",
            "see 'tests/test_retry.py' for it",
            "ran `python -m pytest -q tests`",
        ):
            with self.subTest(text=text):
                _read, verdict = self._verdict(
                    [self._check()],
                    text,
                    {
                        self.CALL: "docs/overview.md:1: ok tests/test_retry.py ... python -m pytest -q tests"
                    },
                )
                self.assertNoQuote(verdict)

    def test_a_span_the_checks_own_command_line_holds_is_not_found(self) -> None:
        fact = base.check_fact(result="passed", at=130.0, summary=f"pytest -q '{OUTPUT}'")
        _read, verdict = self._verdict(
            [fact], quoting(OUTPUT), {("call-1", fact["summary"]): OUTPUT}
        )
        self.assertNoQuote(verdict)

    def test_a_runners_recipe_echo_is_not_found_but_a_line_it_printed_is(self) -> None:
        fact = base.check_fact(result="passed", at=130.0, summary="npm test")
        key = ("call-1", "npm test")
        _read, echoed = self._verdict(
            [fact], quoting(OUTPUT), {key: f"> app@1.0.0 test\n> echo '{OUTPUT}'\n"}
        )
        self.assertNoQuote(echoed)
        _read, printed = self._verdict(
            [fact], quoting(OUTPUT), {key: f"> app@1.0.0 test\n> vitest\n{OUTPUT}\n"}
        )
        self.assertEqual(reading.GOAL_VERDICT_QUOTED, printed["why"])

    def test_a_pytest_failing_source_line_is_found_and_a_recipe_echo_above_it_is_not(self) -> None:
        fact = base.check_fact(result="failed", at=130.0, summary="pnpm test")
        key = ("call-1", "pnpm test")
        failing = ">       assert total == 1"
        for output in (
            f"> app@1.0.0 test /work/app\n> pytest -q\n\n{failing}\nE  assert 2 == 1\n",
            f"{failing}\nE  assert 2 == 1\n",
        ):
            with self.subTest(output=output):
                _read, verdict = self._verdict([fact], quoting("assert total == 1"), {key: output})
                self.assertEqual(reading.GOAL_VERDICT_QUOTED, verdict["why"])
        _read, echoed = self._verdict(
            [fact],
            quoting("assert total == 1"),
            {key: f"> app@1.0.0 test /work/app\n> {failing[2:]}\n\nran\n"},
        )
        self.assertNoQuote(echoed)

    def test_a_span_past_the_searched_tail_is_not_looked_for(self) -> None:
        longer = "x" * (reading.MAX_QUOTED_SPAN_CHARS + 1)
        self.assertEqual((), reading._quoted_spans(f'"{longer}"'))
        fits = "y" * reading.MAX_QUOTED_SPAN_CHARS
        self.assertEqual((fits,), reading._quoted_spans(f'"{fits}"'))
        self.assertEqual(180, reading.MAX_QUOTED_SPAN_CHARS)
        self.assertEqual(project_context.TOOL_REPORT_TAIL_CHARS, reading.MAX_QUOTED_SPAN_CHARS)

    def test_unbalanced_quotes_are_scanned_in_linear_time(self) -> None:
        for unit in ("\u201c", "\u201c a", '\u201c"', '"', '" a'):
            with self.subTest(unit=unit):
                started = time.monotonic()
                self.assertEqual((), reading._quoted_spans(unit * 20000))
                self.assertLess(time.monotonic() - started, 2.0)

    def test_a_span_naming_a_remote_job_is_left_to_the_ci_facts(self) -> None:
        for span in ("coverage-gate pass", "server-unittest pass", "ci/lint passed"):
            with self.subTest(span=span):
                _read, verdict = self._verdict(
                    [self._check()], quoting(span), {self.CALL: f"{span} printed locally"}
                )
                self.assertNoQuote(verdict)

    def test_a_credential_shaped_quote_is_never_searched_or_carried(self) -> None:
        secret = "ghp_" + "a1B2c3D4e5" * 4
        read, verdict = self._verdict(
            [self._check()], quoting(f"token={secret}"), {self.CALL: f"token={secret} here"}
        )
        self.assertNoQuote(verdict)
        self.assertNotIn(secret, json.dumps(read))

    def test_no_output_text_reaches_the_payload(self) -> None:
        marker = "UNIQUE_OUTPUT_MARKER_7731 passed everything"
        read, verdict = self._verdict(
            [self._check()], quoting(marker), {self.CALL: f"{marker} at the end"}
        )
        self.assertEqual(reading.GOAL_VERDICT_QUOTED, verdict["why"])
        self.assertEqual({"at", "check", "why", "cites", "quoted"}, set(verdict))
        self.assertNotIn("UNIQUE_OUTPUT_MARKER_7731", json.dumps(read))
        stored = annotation_store._goal_verdict(verdict)
        self.assertEqual(verdict["cites"], stored["cites"] if stored else None)

    def test_the_count_is_of_distinct_spans_found_and_spans_are_capped(self) -> None:
        spans = [f"unique output line number {n} here" for n in range(12)]
        _read, verdict = self._verdict(
            [self._check()], quoting(*spans, spans[0]), {self.CALL: "\n".join(spans)}
        )
        self.assertEqual(reading.MAX_QUOTED_SPANS, verdict["quoted"])

    def test_it_never_raises_the_answer_to_agrees(self) -> None:
        # A recorded passing check of the claimed kind already agrees; a quote alone never does.
        _read, quoted_only = self._verdict([self._check()], quoting(OUTPUT), {self.CALL: OUTPUT})
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, quoted_only["check"])
        _read, kind = self._verdict(
            [self._check()], f'the tests pass, it printed "{OUTPUT}"', {self.CALL: OUTPUT}
        )
        self.assertEqual(reading.GOAL_VERDICT_AGREES, kind["check"])
        self.assertEqual(reading.GOAL_VERDICT_PASSED, kind["why"])
        self.assertNotIn("quoted", kind)

    def test_a_failed_check_still_disputes_before_any_quote_is_read(self) -> None:
        failing = base.check_fact(result="failed", at=130.0, summary="pytest -q")
        _read, verdict = self._verdict(
            [failing], f'the tests pass, it printed "{OUTPUT}"', {self.CALL: OUTPUT}
        )
        self.assertEqual(reading.GOAL_VERDICT_DISPUTED, verdict["check"])
        self.assertEqual(reading.GOAL_VERDICT_FAILED, verdict["why"])

    def test_a_write_the_reason_names_agrees_as_it_did(self) -> None:
        _read, verdict = self._verdict(
            [write_fact("findings.md", at=120.0), self._check()],
            f'findings.md was written and it printed "{OUTPUT}"',
            {self.CALL: OUTPUT},
        )
        self.assertEqual(reading.GOAL_VERDICT_WRITTEN, verdict["why"])

    def test_a_reason_with_nothing_else_checkable_still_finds_its_quote(self) -> None:
        _read, verdict = self._verdict(
            [self._check()], f'the log reads "{OUTPUT}"', {self.CALL: OUTPUT}
        )
        self.assertEqual(reading.GOAL_VERDICT_QUOTED, verdict["why"])

    def test_a_claim_with_no_reason_has_no_quote_to_search(self) -> None:
        _read, verdict = self._verdict([self._check()], "", {self.CALL: OUTPUT})
        self.assertNotEqual(reading.GOAL_VERDICT_QUOTED, verdict["why"])
        self.assertNotIn("quoted", verdict)

    def test_a_press_without_the_output_reads_as_before(self) -> None:
        _read, verdict = self._verdict([self._check()], quoting(OUTPUT), None)
        self.assertNoQuote(verdict)

    def test_the_stored_quoted_count_is_admitted_only_beside_its_token(self) -> None:
        good = {
            "at": VERDICT_AT,
            "check": "unconfirmed",
            "why": reading.GOAL_VERDICT_QUOTED,
            "cites": ["check-1"],
            "quoted": 2,
        }
        self.assertIsNotNone(annotation_store._goal_verdict(good))
        for bad in (
            {**good, "why": "not-found"},
            {**good, "quoted": 0},
            {**good, "quoted": True},
            {**good, "quoted": "2"},
            {**good, "path": "a.md", "changed_at": 1.0},
            {k: v for k, v in good.items() if k != "quoted"},
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(annotation_store._goal_verdict(bad))


class QuotedCiRowsAreLeftToTheCiFacts(base.AClaudeCodeReadingProducer):
    def _read(self, record: dict[str, Any] | None) -> dict[str, Any]:
        reason = (
            f'CI on {GOAL_URL}: "coverage-gate pass" and "server-unittest pass" from the last poll'
        )
        row = goal_row(reason)
        assessment, why, _spent = reading.produce(
            self.config,  # type: ignore[arg-type]
            row,
            [{"n": 1, "at": 50.0, "goal": GOAL, "lines": []}],
            [base.WORDS_FACT],
            now=200.0,
            stamp_text="read at 10:00",
            model=self._model(json.dumps({"goal": {"result": "consistent", "cites": [1]}})),
            read_lines=True,
            read_agent_words=True,
            tool_output=reading.ToolOutput(
                destination="",
                label="x",
                quotable={("call-1", "pytest -q"): "coverage-gate pass server-unittest pass"},
            ),
            ci=record,
        )
        self.assertEqual("", why)
        return cast("dict[str, Any]", cast("Any", assessment)["goal_verdict"])

    def test_without_ci_facts_it_stays_unconfirmed_and_not_found(self) -> None:
        verdict = self._read(None)
        self.assertEqual(reading.GOAL_VERDICT_UNCONFIRMED, verdict["check"])
        self.assertEqual(reading.GOAL_VERDICT_NOT_FOUND, verdict["why"])

    def test_with_green_ci_facts_it_agrees_citing_them(self) -> None:
        verdict = self._read(record_with(*GREEN))
        self.assertEqual(reading.GOAL_VERDICT_AGREES, verdict["check"])
        self.assertEqual(reading.GOAL_VERDICT_CI, verdict["why"])
        self.assertTrue(verdict["cites"])
