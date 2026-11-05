"""What two harnesses' records may say: Pi's validation results and Antigravity's directions.

DRC-4690: a Pi validation run is read under
[DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)'s
rules. Only a command on the closed runner list counts, failure is read first, a zero count is
"ran, result not recorded", and the error flag speaks only as the 0.87.1 capture
(`docs/captures/pi/validation-results-0.87.1-macos.jsonl`) shows it: set with Pi's own
"Command exited with code N" status line, it is a nonzero exit.

DRC-4689: Antigravity's `USER_INPUT` directions are read from its transcript into the observed
record and as the title fallback, and nothing else in that file is read. A harness with no record
reader gets its own withheld sentence rather than "no entry names this session".
"""

from __future__ import annotations

import calendar
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import (
    http_api,
    levels,
    observer,
    project_context,
    reading,
    semantic_history,
    transcripts,
)
from compass_runtime.collectors import antigravity
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

NOW = 1_800_000_000.0
AT = "2026-08-24T20:00:00Z"
AT_EPOCH = 1_787_601_600.0


def _call(call_id: str, name: str, arguments: dict[str, Any], at: str, rid: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": rid,
        "timestamp": at,
        "message": {
            "role": "assistant",
            "content": [{"type": "toolCall", "id": call_id, "name": name, "arguments": arguments}],
        },
    }


def _result(call_id: str, *, is_error: bool, text: str, at: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": f"r-{call_id}",
        "timestamp": at,
        "message": {
            "role": "toolResult",
            "toolCallId": call_id,
            "toolName": "bash",
            "isError": is_error,
            "content": [{"type": "text", "text": text}],
        },
    }


def exited(text: str, code: int) -> str:
    """Pi 0.87.1's own status line, appended after a nonzero exit (the capture)."""
    return (
        f"{text}\n\nCommand exited with code {code}" if text else f"Command exited with code {code}"
    )


class PiRecord(unittest.TestCase):
    """A scratch Pi transcript and the outcome events `_work_evidence` reads from it."""

    SID = "pi-session"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"pi.sessions": str(self.root)},
        )
        self.path = self.root / "t.jsonl"
        self.records: list[dict[str, Any]] = []
        self.seq = 0

    def bash(self, command: str, *, is_error: bool | None, text: str = "") -> None:
        """One bash call; `is_error=None` leaves it with no paired result yet."""
        self.seq += 1
        call_id = f"c{self.seq}"
        minute = f"2026-08-24T20:{self.seq:02d}:00Z"
        self.records.append(_call(call_id, "bash", {"command": command}, minute, f"a{self.seq}"))
        if is_error is not None:
            done = f"2026-08-24T20:{self.seq:02d}:05Z"
            self.records.append(_result(call_id, is_error=is_error, text=text, at=done))

    def tool(self, name: str, arguments: dict[str, Any]) -> None:
        self.seq += 1
        call_id = f"c{self.seq}"
        minute = f"2026-08-24T20:{self.seq:02d}:00Z"
        self.records.append(_call(call_id, name, arguments, minute, f"a{self.seq}"))
        done = f"2026-08-24T20:{self.seq:02d}:05Z"
        self.records.append(_result(call_id, is_error=False, text="ok", at=done))

    def checks(self) -> list[dict[str, Any]]:
        self.path.write_text(
            "\n".join(json.dumps(record) for record in self.records) + "\n", encoding="utf-8"
        )
        events, _stats = project_context._work_evidence(self.config, str(self.path), "pi", self.SID)
        return [event for event in events if event.get("kind") == "outcome"]

    def one(self) -> dict[str, Any]:
        found = self.checks()
        self.assertEqual(1, len(found), found)
        return found[0]


class APiValidationRunIsReadUnderDec23(PiRecord):
    def test_a_failed_run_with_its_exit_recorded_is_a_failure_with_its_count(self) -> None:
        self.bash(
            "pytest -q",
            is_error=True,
            text=exited("FAILED t.py::x - assert 1 == 2\n2 failed, 3 passed in 0.12s", 1),
        )
        got = self.one()
        self.assertEqual("check", got["subject"])
        self.assertEqual("failed", got["result"])
        self.assertEqual(2, got["checks_failed"])
        self.assertNotIn("checks_passed", got)
        self.assertEqual("2 validation checks failed", got["title"])

    def test_a_failure_summary_outranks_a_clear_flag(self) -> None:
        self.bash("pytest -q", is_error=False, text="1 failed, 9 passed in 0.3s")
        got = self.one()
        self.assertEqual("failed", got["result"])
        self.assertEqual("summary", got["result_source"])
        self.assertNotIn("passed", got["title"])

    def test_a_zero_count_is_ran_and_not_recorded_never_a_pass(self) -> None:
        self.bash("pytest -q -k nomatch", is_error=False, text="0 passed in 0.01s")
        got = self.one()
        self.assertEqual("not-recorded", got["result"])
        self.assertNotIn("passed", got["title"])
        self.assertNotIn("checks_passed", got)
        self.assertEqual("Validation ran, result not recorded", got["title"])

    def test_a_run_of_nothing_is_not_recorded_on_each_runner(self) -> None:
        for command, text in (
            ("python3 -m unittest", "\n----\nRan 0 tests in 0.000s\n\nOK\n"),
            ("node --test", "\u2139 tests 0\n\u2139 pass 0\n\u2139 fail 0\n"),
        ):
            with self.subTest(command=command):
                self.records.clear()
                self.bash(command, is_error=False, text=text)
                self.assertEqual("not-recorded", self.one()["result"])

    def test_output_from_a_command_that_is_not_a_check_is_never_a_result(self) -> None:
        self.bash("echo '5 passed'", is_error=False, text="5 passed")
        self.assertEqual([], self.checks())

    def test_a_passing_run_is_a_pass_with_its_count(self) -> None:
        self.bash("pytest -q", is_error=False, text="7 passed in 0.2s")
        got = self.one()
        self.assertEqual("passed", got["result"])
        self.assertEqual(7, got["checks_passed"])
        self.assertEqual("7 validation checks passed", got["title"])

    def test_the_published_fact_carries_subject_and_result(self) -> None:
        self.bash("pytest -q", is_error=True, text=exited("2 failed, 3 passed in 0.12s", 1))
        fact = project_context._semantic_fact_from_event(self.one(), "outcome", "result", "")
        self.assertEqual("check", fact["subject"])
        self.assertEqual("failed", fact["result"])
        self.assertIn("changed_after", fact)


class PisErrorFlagSpeaksOnlyAsTheCaptureShowsIt(PiRecord):
    """0.87.1 sets `isError` exactly when its bash tool throws, and appends one status line:
    `Command exited with code N` for a nonzero exit, `Command timed out after N seconds` or
    `Command aborted` otherwise. Anything else flagged never ran."""

    def test_a_nonzero_exit_of_one_check_is_a_failure_with_no_text(self) -> None:
        self.bash("pytest -q", is_error=True, text=exited("", 1))
        got = self.one()
        self.assertEqual("failed", got["result"])
        self.assertEqual("flag", got["result_source"])
        self.assertEqual("Validation failed", got["title"])

    def test_a_timed_out_check_ran_and_its_result_is_not_recorded(self) -> None:
        self.bash("pytest -q", is_error=True, text="..\n\nCommand timed out after 1 seconds")
        self.assertEqual("not-recorded", self.one()["result"])

    def test_a_flagged_call_with_no_status_line_never_ran(self) -> None:
        self.bash("pytest -q", is_error=True, text="Tool call blocked by an extension")
        self.assertEqual([], self.checks())

    def test_a_swallowed_exit_with_another_print_has_no_attributed_result(self) -> None:
        # The flag speaks for echo, and its output may include a summary of
        # its own (DRC-4733), so even failure text has no established source.
        self.bash("pytest -q; echo done", is_error=False, text="1 failed, 1 passed\ndone")
        self.assertEqual("not-recorded", self.one()["result"])

    def test_the_captures_swallowed_run_is_not_recorded_as_claude_codes_would_be(self) -> None:
        # The capture's `swallowed` run. `true` is not on the read-only list, so
        # DEC-23 lets no output speak for the check beside it.
        self.bash("pytest -q; true", is_error=False, text="1 failed, 1 passed in 0.02s")
        self.assertEqual("not-recorded", self.one()["result"])

    def test_a_nonzero_exit_of_a_multi_segment_call_speaks_for_no_check(self) -> None:
        self.bash("pytest -q && ruff check .", is_error=True, text=exited("", 1))
        self.assertEqual(["not-recorded", "not-recorded"], [e["result"] for e in self.checks()])

    def test_a_status_line_in_long_output_is_read_past_the_text_bound(self) -> None:
        noise = "x" * 70 + "\n"
        self.bash("pytest -q", is_error=True, text=exited(noise * 400 + "1 failed in 3s", 1))
        got = self.one()
        self.assertEqual("failed", got["result"])
        self.assertEqual(1, got["checks_failed"])

    def test_a_call_still_running_lists_its_check_as_not_recorded(self) -> None:
        self.bash("pytest -q", is_error=None)
        self.assertEqual("not-recorded", self.one()["result"])


class OnlyTheLatestRunOfAPiCheckIsListed(PiRecord):
    def test_a_failure_then_a_pass_lists_the_pass_and_says_one_failed_earlier(self) -> None:
        self.bash("pytest -q", is_error=True, text=exited("1 failed in 1s", 1))
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        got = self.one()
        self.assertEqual("passed", got["result"])
        self.assertIs(True, got["earlier_failed"])

    def test_a_later_edit_ages_a_pass_and_a_later_read_does_not(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.bash("ls -la", is_error=False, text="total 0")
        clean = self.one()
        self.assertIs(False, clean["changed_after"])
        self.assertIs(False, clean["before_last_change"])
        self.tool("edit", {"path": "a.py", "oldText": "a", "newText": "b"})
        aged = self.one()
        self.assertIs(True, aged["changed_after"])
        self.assertIs(True, aged["before_last_change"])

    def test_a_later_changing_command_marks_a_pass_changed_after(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.bash("rm -rf build", is_error=False, text="")
        self.assertIs(True, self.one()["changed_after"])


class APiCheckReachesTheLevelsAndTheReadingRules(PiRecord):
    def _facts(self) -> list[dict[str, Any]]:
        facts = []
        for event in self.checks():
            fact = project_context._semantic_fact_from_event(event, "outcome", "result", "")
            fact["source_session"] = {"harness": "pi", "sid": self.SID}
            facts.append(fact)
        return facts

    def test_a_failed_pi_check_in_the_window_makes_the_analysis_level_high(self) -> None:
        self.bash("pytest -q", is_error=True, text=exited("2 failed, 3 passed in 0.12s", 1))
        facts = self._facts()
        row = {
            "read_at": NOW,
            "window_start": AT_EPOCH,
            "criteria": {"line_1": {"result": reading.RESULT_UNVERIFIABLE, "cites": []}},
        }
        got = levels.analysis_level(
            row,
            levels.Evidence(
                facts=tuple({**fact, "type": "tool_report"} for fact in facts),
                scan={"last_user_at": AT_EPOCH - 1},
                unsettled_directions=0,
            ),
            outcome_lines=1,
        )
        self.assertEqual(levels.HIGH, got.level)
        self.assertIn(levels.REASON_FAILED_CHECK, got.reasons)

    def _ledger(self) -> tuple[reading.LedgerEntry, ...]:
        return reading.build_ledger(self._facts(), "pi", self.SID)

    def test_a_not_recorded_pi_check_carries_no_consistent(self) -> None:
        self.bash("pytest -q", is_error=False, text="0 passed in 0.01s")
        (entry,) = self._ledger()
        self.assertFalse(reading.check_supports(entry, reading.RESULT_CONSISTENT, 0.0))
        self.assertFalse(reading.check_supports(entry, reading.RESULT_DEPARTURE, 0.0))

    def test_a_pi_pass_before_the_window_carries_no_consistent(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        (entry,) = self._ledger()
        self.assertTrue(reading.check_supports(entry, reading.RESULT_CONSISTENT, AT_EPOCH))
        self.assertFalse(reading.check_supports(entry, reading.RESULT_CONSISTENT, NOW))

    def test_a_pi_pass_followed_by_an_edit_carries_no_consistent(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.tool("write", {"path": "a.py", "content": "b"})
        (entry,) = self._ledger()
        self.assertFalse(reading.check_supports(entry, reading.RESULT_CONSISTENT, AT_EPOCH))

    def test_a_failed_pi_check_in_the_window_may_carry_a_departure_only(self) -> None:
        self.bash("pytest -q", is_error=True, text=exited("1 failed in 1s", 1))
        (entry,) = self._ledger()
        self.assertTrue(reading.check_supports(entry, reading.RESULT_DEPARTURE, AT_EPOCH))
        self.assertFalse(reading.check_supports(entry, reading.RESULT_CONSISTENT, AT_EPOCH))


class PisOwnExitLineOutranksAClearFlag(PiRecord):
    """A `tool_result` extension may clear `isError` on a call that threw, leaving Pi's own
    "Command exited with code N" line in place (0.87.1 `afterToolCall`). The capture shows the
    two agreeing, so a record where they disagree is not one it vouches for: never a pass."""

    def test_a_clear_flag_beside_the_exit_line_is_not_recorded(self) -> None:
        self.bash("pytest -q", is_error=False, text=exited("E   assert 1 == 2", 1))
        self.assertEqual("not-recorded", self.one()["result"])

    def test_a_pass_summary_beside_the_exit_line_is_not_a_pass(self) -> None:
        self.bash("pytest -q", is_error=False, text=exited("5 passed in 0.1s", 1))
        got = self.one()
        self.assertEqual("not-recorded", got["result"])
        self.assertNotIn("passed", got["title"])

    def test_the_same_holds_through_rtk(self) -> None:
        self.bash("rtk pytest -q", is_error=False, text=exited("", 1))
        self.assertEqual("not-recorded", self.one()["result"])

    def test_an_absent_flag_beside_the_exit_line_is_not_a_pass(self) -> None:
        self.bash("pytest -q", is_error=False, text=exited("5 passed", 1))
        del self.records[-1]["message"]["isError"]
        self.assertEqual("not-recorded", self.one()["result"])

    def test_a_failure_summary_beside_the_exit_line_still_reads_failed(self) -> None:
        self.bash("pytest -q", is_error=False, text=exited("1 failed, 4 passed", 1))
        self.assertEqual("failed", self.one()["result"])


class AnyPiToolNotKnownToBeReadOnlyAgesAPass(PiRecord):
    def test_a_later_powershell_call_ages_a_pass(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.tool("powershell", {"command": "Set-Content a.py 'b'"})
        got = self.one()
        self.assertIs(True, got["changed_after"])
        self.assertIs(True, got["before_last_change"])

    def test_a_later_unknown_tool_ages_a_pass(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.tool("some_extension_tool", {"target": "a.py"})
        self.assertIs(True, self.one()["changed_after"])

    def test_the_read_only_tools_leave_a_pass_current(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        for name in ("read", "grep", "find", "ls"):
            self.tool(name, {"path": "a.py"})
        got = self.one()
        self.assertIs(False, got["changed_after"])
        self.assertIs(False, got["before_last_change"])


def _epoch(stamp: str) -> float:
    return float(calendar.timegm(time.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")))


class EachPiReadingRuleIsPinned(PiRecord):
    """One case per rule the mutation run found no test for (gF review, correctness)."""

    def test_a_timed_out_run_whose_tail_says_passed_is_not_a_pass(self) -> None:
        self.bash("pytest -q", is_error=True, text="5 passed\n\nCommand timed out after 9 seconds")
        self.assertEqual("not-recorded", self.one()["result"])

    def test_a_check_run_in_the_background_is_not_read(self) -> None:
        self.bash("pytest -q &", is_error=False, text="5 passed in 0.1s")
        self.assertEqual("not-recorded", self.one()["result"])

    def test_a_check_after_or_is_not_read(self) -> None:
        self.bash("false || pytest -q", is_error=False, text="5 passed in 0.1s")
        self.assertEqual("not-recorded", self.one()["result"])

    def test_the_latest_run_is_the_one_whose_result_came_last(self) -> None:
        # The first call's pass lands after the second call's failure.
        self.records += [
            _call("c1", "bash", {"command": "pytest -q"}, "2026-08-24T20:01:00Z", "a1"),
            _call("c2", "bash", {"command": "pytest -q"}, "2026-08-24T20:02:00Z", "a2"),
            _result("c2", is_error=True, text=exited("1 failed", 1), at="2026-08-24T20:02:05Z"),
            _result("c1", is_error=False, text="4 passed", at="2026-08-24T20:03:00Z"),
        ]
        got = self.one()
        self.assertEqual("passed", got["result"])
        self.assertIs(True, got["earlier_failed"])

    def test_a_change_later_in_the_same_call_marks_the_pass_changed_after_alone(self) -> None:
        self.bash("pytest -q && sed -i s/a/b/ a.py", is_error=False, text="5 passed in 0.1s")
        got = self.one()
        self.assertEqual("passed", got["result"])
        self.assertIs(True, got["changed_after"])
        self.assertIs(False, got["before_last_change"])

    def test_a_fixer_that_is_the_check_ages_its_own_pass_and_nothing_follows_it(self) -> None:
        self.bash("ruff check --fix .", is_error=False, text="All checks passed!")
        got = self.one()
        self.assertEqual("passed", got["result"])
        self.assertIs(True, got["before_last_change"])
        self.assertIs(False, got["changed_after"])

    def test_an_aborted_run_after_a_pass_is_the_latest_run(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.bash("pytest -q", is_error=True, text="..\n\nCommand aborted")
        self.assertEqual("not-recorded", self.one()["result"])

    def test_an_exit_line_the_program_printed_itself_is_not_pis(self) -> None:
        self.bash("pytest -q", is_error=False, text="Command exited with code 1\n5 passed in 0.1s")
        self.assertEqual("passed", self.one()["result"])

    def test_the_result_time_is_kept(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.assertEqual(_epoch("2026-08-24T20:01:05Z"), self.one()["result_at"])

    def test_a_check_before_since_is_left_out(self) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        self.checks()
        events, _stats = project_context._work_evidence(
            self.config, str(self.path), "pi", self.SID, since=_epoch("2026-08-24T20:30:00Z")
        )
        self.assertEqual([], [e for e in events if e.get("kind") == "outcome"])


class APiCheckCarriesItsFieldsIntoTheLedger(PiRecord):
    def _ledger(self) -> tuple[reading.LedgerEntry, ...]:
        facts = []
        for event in self.checks():
            fact = project_context._semantic_fact_from_event(event, "outcome", "result", "")
            fact["source_session"] = {"harness": "pi", "sid": self.SID}
            facts.append(fact)
        return reading.build_ledger(facts, "pi", self.SID)

    def test_a_result_that_landed_inside_the_window_counts_though_its_call_began_before(
        self,
    ) -> None:
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        (entry,) = self._ledger()
        self.assertEqual(_epoch("2026-08-24T20:01:05Z"), entry["result_at"])
        window_start = _epoch("2026-08-24T20:01:02Z")
        self.assertTrue(reading.check_supports(entry, reading.RESULT_CONSISTENT, window_start))

    def test_a_change_later_in_the_call_withholds_a_consistent(self) -> None:
        self.bash("pytest -q && sed -i s/a/b/ a.py", is_error=False, text="5 passed in 0.1s")
        (entry,) = self._ledger()
        self.assertIs(True, entry["changed_after"])
        self.assertFalse(reading.check_supports(entry, reading.RESULT_CONSISTENT, 0.0))

    def test_a_pass_before_its_own_fix_withholds_a_consistent(self) -> None:
        self.bash("ruff check --fix .", is_error=False, text="All checks passed!")
        (entry,) = self._ledger()
        self.assertIs(True, entry["stale"])
        self.assertFalse(reading.check_supports(entry, reading.RESULT_CONSISTENT, 0.0))

    def test_an_earlier_failure_is_carried(self) -> None:
        self.bash("pytest -q", is_error=True, text=exited("1 failed in 1s", 1))
        self.bash("pytest -q", is_error=False, text="4 passed in 1s")
        (entry,) = self._ledger()
        self.assertIs(True, entry["earlier_failed"])

    def _failure_and_pass(self) -> tuple[tuple[reading.LedgerEntry, ...], int, int]:
        self.bash("pytest -q", is_error=True, text=exited("1 failed in 1s", 1))
        self.bash("ruff check .", is_error=False, text="All checks passed!")
        ledger = self._ledger()
        prompt, _selection = reading.build_prompt(ledger, goal="add a retry", max_bytes=1 << 20)
        head = len(prompt[: prompt.index("[1] ")].encode())
        row = max(len(line.encode()) + 1 for line in prompt.splitlines() if line[:1] == "[")
        return ledger, head, row

    def test_a_pi_failure_is_reserved_before_a_newer_pass(self) -> None:
        ledger, head, row = self._failure_and_pass()
        _prompt, selection = reading.build_prompt(
            ledger, goal="add a retry", max_bytes=head + row + 2
        )
        self.assertEqual(["failed"], [entry["result"] for entry in selection.entries])

    def test_a_pi_failure_the_bound_left_out_is_counted_unread(self) -> None:
        ledger, head, _row = self._failure_and_pass()
        _prompt, selection = reading.build_prompt(ledger, goal="add a retry", max_bytes=head + 1)
        self.assertEqual((), selection.entries)
        self.assertEqual(["failed"], [entry["result"] for entry in selection.unread_failures])


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class APiCheckNeverComesBackFromSemanticHistory(unittest.TestCase):
    """DEC-23 item 6 keeps check facts out of the semantic history store, as Claude Code's are:
    the store keeps an allowlist of fact keys without `subject` or `result`, so a check read back
    from it is a bare "5 validation checks passed" that no rule can age or supersede."""

    SID = "pi-history"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "pi").mkdir()
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
            store_root_overrides={"pi.sessions": str(self.root / "pi")},
        )
        self.state = build_runtime_state(self.config, started=time.time())
        self.now = time.time()
        self.records: list[dict[str, Any]] = [
            {
                "type": "session",
                "id": self.SID,
                "cwd": str(self.root),
                "timestamp": _iso(self.now - 600),
            },
            {
                "type": "message",
                "id": "u1",
                "timestamp": _iso(self.now - 590),
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Add a retry to the webhook handler"}],
                },
            },
        ]

    def bash(self, call_id: str, command: str, *, ago: float, is_error: bool, text: str) -> None:
        self.records.append(
            _call(call_id, "bash", {"command": command}, _iso(self.now - ago), f"a-{call_id}")
        )
        self.records.append(
            _result(call_id, is_error=is_error, text=text, at=_iso(self.now - ago + 5))
        )

    def collect(self) -> dict[str, Any]:
        (self.root / "pi" / "s.jsonl").write_text(
            "\n".join(json.dumps(record) for record in self.records) + "\n", encoding="utf-8"
        )
        row = {
            "harness": "pi",
            "sid": self.SID,
            "project": "p",
            "project_key": "p",
            "active": True,
            "state": "working",
            "cwd": str(self.root),
        }
        return project_context.collect(
            self.config,
            self.state,
            [row],
            "p",
            now=time.time(),
            focus=("pi", self.SID),
            model_consent=False,
        )

    def _no_entry_carries_a_consistent(self, facts: list[dict[str, Any]]) -> None:
        ledger = reading.build_ledger(facts, "pi", self.SID)
        revisions = [
            {
                "n": 1,
                "goal": "Add a retry to the webhook handler",
                "at": self.now - 595,
                "line_1": "The webhook tests pass",
                "lines": ["The webhook tests pass"],
            }
        ]
        row = {"harness": "pi", "sid": self.SID, "state": "working", "ended_at": None}
        for number in range(1, len(ledger) + 1):
            reply = json.dumps(
                {
                    "goal": {"result": "unverifiable", "cites": [], "detail": ""},
                    "line_1": {"result": "consistent", "cites": [number], "detail": ""},
                }
            )
            got, _why, _spent = reading.produce(
                self.config,
                row,
                revisions,
                facts,
                now=time.time(),
                stamp_text="x",
                model=lambda _prompt, _reply=reply, **_kw: (_reply, "ok"),
                read_lines=True,
            )
            with self.subTest(cited=number):
                assert got is not None
                self.assertNotEqual(reading.RESULT_CONSISTENT, got["criteria"]["line_1"]["result"])

    def test_a_pass_superseded_by_a_later_failure_carries_no_consistent(self) -> None:
        self.bash("c1", "pytest -q", ago=500, is_error=False, text="5 passed in 0.1s")
        self.collect()
        self.bash("c2", "pytest -q", ago=300, is_error=True, text=exited("1 failed, 4 passed", 1))
        facts = self.collect()["semantic"]["facts"]
        results = [fact for fact in facts if fact.get("type") == "result"]
        self.assertEqual(["failed"], [fact.get("result") for fact in results], results)
        self._no_entry_carries_a_consistent(facts)

    def test_the_store_is_never_handed_a_pi_check(self) -> None:
        self.bash("c1", "pytest -q", ago=500, is_error=False, text="5 passed in 0.1s")
        self.collect()
        store = json.loads(
            Path(semantic_history.store_path(self.config)).read_text(encoding="utf-8")
        )
        events = [event for project in store["projects"].values() for event in project["events"]]
        self.assertTrue(events, "the collect wrote no history at all")
        self.assertEqual([], [e for e in events if e["event_type"] == "result"])

    def test_the_store_and_the_reader_name_one_source_prefix(self) -> None:
        # Spelled in both modules so the reader need not import the store.
        self.assertEqual(
            semantic_history.PI_CHECK_SOURCE_PREFIX,
            reading._PI_CHECK_SOURCE_PREFIX,
        )
        self.bash("c1", "pytest -q", ago=500, is_error=False, text="5 passed in 0.1s")
        (check,) = [f for f in self.collect()["semantic"]["facts"] if f.get("subject") == "check"]
        self.assertTrue(
            check["evidence"]["source"].startswith(semantic_history.PI_CHECK_SOURCE_PREFIX)
        )

    def _old_row(self, fact_id: str, source: str, ago: float) -> dict[str, Any]:
        fact = {
            "fact_id": fact_id,
            "at": self.now - ago,
            "type": "result",
            "source_kind": "outcome",
            "summary": "5 validation checks passed",
            "scope": "session",
            "actor_claim": "session assistant/tool exchange",
            "work_item_id": None,
            "source_session": {"harness": "pi", "sid": self.SID},
            "branch": {"harness": "pi", "sid": self.SID, "record_id": fact_id},
            "evidence": {"source": source, "confidence": "exact"},
        }
        return {
            "event_id": fact_id,
            "event_type": "result",
            "at": self.now - ago,
            "source_identity": f"pi:{self.SID}",
            "source_ref": fact_id,
            "work_binding": None,
            "summary": fact["summary"],
            "fact": fact,
            "work_item": None,
        }

    def test_a_pre_upgrade_row_supports_no_verdict(self) -> None:
        # The first row is what the build before DRC-4690 wrote for `echo '5 passed'`; the
        # second is a superseded pass this change's first build let into the store.
        rows = [
            self._old_row("fact:old-echo", "Pi bash tool call and paired successful result", 400),
            self._old_row("fact:old-pass", "Pi bash tool call and paired result", 350),
        ]
        Path(self.config.state_home).mkdir(parents=True, exist_ok=True)
        Path(semantic_history.store_path(self.config)).write_text(
            json.dumps(
                {
                    "v": semantic_history.SCHEMA_VERSION,
                    "projects": {"p": {"events": rows, "cursors": {}}},
                }
            ),
            encoding="utf-8",
        )
        self.bash("c1", "echo '5 passed'", ago=300, is_error=False, text="5 passed")
        facts = self.collect()["semantic"]["facts"]
        ledger = reading.build_ledger(facts, "pi", self.SID)
        old = [entry for entry in ledger if entry["id"] in {"fact:old-echo", "fact:old-pass"}]
        self.assertEqual(2, len(old), ledger)
        for entry in old:
            for verdict in (reading.RESULT_CONSISTENT, reading.RESULT_DEPARTURE):
                with self.subTest(entry=entry["id"], verdict=verdict):
                    self.assertFalse(reading.check_supports(entry, verdict, 0.0))
        self._no_entry_carries_a_consistent(facts)


# --- Antigravity ------------------------------------------------------------------------------

AGY_SID = "11111111-2222-3333-4444-555555555555"


class AntigravityHome(unittest.TestCase):
    """A synthetic 1.2.x Antigravity home: a store, a CLI log without the prompt marker the
    collector once read (0 of 7 real 1.2.11 logs carry it), and a brain transcript."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.home = root / "home"
        self.agy = self.home / ".gemini" / "antigravity-cli"
        for part in ("conversations", "log", "cache"):
            (self.agy / part).mkdir(parents=True)
        self.work = self.home / "proj"
        self.work.mkdir()
        self.config = build_runtime_config(
            environ={"HOME": str(self.home), "COMPASS_HOME": str(root / "state")},
            platform_name="darwin",
            os_name="posix",
            launcher_path=root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=time.time())
        (self.agy / "conversations" / f"{AGY_SID}.db").write_bytes(b"")
        (self.agy / "cache" / "last_conversations.json").write_text(
            json.dumps({str(self.work): AGY_SID}), encoding="utf-8"
        )
        (self.agy / "log" / "cli-1.log").write_text(
            f"I0923 workspaceDirs=[{self.work}] appDataDir=/x\n"
            f"I0923 Created conversation {AGY_SID}\n"
            f"I0923 Forwarding user message to conversation {AGY_SID}\n",
            encoding="utf-8",
        )
        self.logs = self.agy / "brain" / AGY_SID / ".system_generated" / "logs"
        self.transcript = self.logs / "transcript.jsonl"

    def write(self, *records: dict[str, Any]) -> None:
        self.logs.mkdir(parents=True, exist_ok=True)
        self.transcript.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )


def agy(
    kind: str, step: int, at: str, content: Any = "", source: str = "MODEL", **extra: Any
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": kind,
        "source": source,
        "status": "DONE",
        "step_index": step,
        "created_at": at,
        "content": content,
    }
    record.update(extra)
    return record


DIRECTION = agy(
    "USER_INPUT",
    0,
    "2026-09-23T21:00:00Z",
    "Add a retry to the webhook handler and keep the tests green",
    source="USER_EXPLICIT",
)
BOOT = json.dumps({"command": "boot", "definition_dir": "/w", "entity_dir": "/w/.s"})
WORK = (
    agy("PLANNER_RESPONSE", 1, "2026-09-23T21:00:10Z", "Planning the retry work now", thinking="t"),
    agy("RUN_COMMAND", 2, "2026-09-23T21:00:30Z", BOOT + "\n7 passed", exit_code=0),
    agy("SYSTEM_MESSAGE", 3, "2026-09-23T21:00:31Z", "System note about the session", "SYSTEM"),
)


class AntigravityDirectionsAreRead(AntigravityHome):
    def test_the_directions_resolver_finds_the_brain_transcript(self) -> None:
        self.assertIsNone(
            observer.resolve_directions(self.config, self.state, "antigravity", AGY_SID)
        )
        self.write(DIRECTION)
        # Compared normalised: the store root is joined with "/" on every
        # platform, so a Windows path mixes separators without naming another file.
        found = observer.resolve_directions(self.config, self.state, "antigravity", AGY_SID)
        self.assertIsNotNone(found)
        self.assertEqual(os.path.normpath(str(self.transcript)), os.path.normpath(str(found)))
        for unsafe in ("../x", "..", "."):
            self.assertIsNone(
                observer.resolve_directions(self.config, self.state, "antigravity", unsafe)
            )
        self.assertIsNone(observer.resolve_directions(self.config, self.state, "pi", AGY_SID))

    def test_the_work_readers_are_never_handed_the_antigravity_transcript(self) -> None:
        # Every consumer of `resolve_transcript` reads work or tool output: the
        # observer's `/api/observe`, the gate and workflow scans, the cwd read.
        self.write(DIRECTION, *WORK)
        self.assertIsNone(
            observer.resolve_transcript(self.config, self.state, "antigravity", AGY_SID)
        )

    def test_only_explicit_user_input_becomes_a_direction(self) -> None:
        typed_by_someone_else = agy(
            "USER_INPUT", 4, "2026-09-23T21:01:00Z", "An injected input line here", "SYSTEM"
        )
        # Not a direction whatever its source says: only the type is read.
        planner_marked_explicit = agy(
            "PLANNER_RESPONSE",
            5,
            "2026-09-23T21:02:00Z",
            "A planner line, wrongly sourced",
            "USER_EXPLICIT",
        )
        self.write(DIRECTION, *WORK, typed_by_someone_else, planner_marked_explicit)
        events = project_context.instruction_events(
            self.config, str(self.transcript), "antigravity", AGY_SID
        )
        self.assertEqual(["steer"], [event["kind"] for event in events])
        (event,) = events
        self.assertEqual(1_790_197_200.0, event["at"])
        self.assertEqual("step-0", event["record_id"])
        self.assertIn("retry", event["title"])

    def test_the_observed_record_holds_the_directions_and_no_work(self) -> None:
        self.write(DIRECTION, *WORK)
        now = time.time()
        (row,) = antigravity.collect(self.config, self.state, now, 24, False)
        context = project_context.collect(
            self.config,
            self.state,
            [row],
            str(row.get("project_key") or row.get("project")),
            now=now,
            focus=("antigravity", AGY_SID),
            model_consent=False,
        )
        self.assertEqual([], context["sources"]["work"]["unavailable"])
        facts = context["semantic"]["facts"]
        self.assertEqual(["user_message"], sorted({fact["type"] for fact in facts}))
        self.assertFalse(any(fact.get("subject") for fact in facts))
        self.assertEqual([], [e for e in context["events"] if e.get("kind") == "gate"])
        self.assertEqual(
            [], project_context.work_events(self.config, str(self.transcript), "antigravity", "x")
        )

    def test_the_whole_direction_is_returned_and_a_truncated_one_is_refused(self) -> None:
        self.write(DIRECTION)
        (event,) = project_context.instruction_events(
            self.config, str(self.transcript), "antigravity", AGY_SID
        )
        fact = project_context._semantic_fact_from_event(event, "steer", "user_message", "")
        self.assertEqual(
            DIRECTION["content"],
            project_context.direction_text(
                self.config, self.state, "antigravity", AGY_SID, fact["fact_id"]
            ).text,
        )
        self.write({**DIRECTION, "truncated_fields": ["content"]})
        self.assertEqual(
            "",
            project_context.direction_text(
                self.config, self.state, "antigravity", AGY_SID, fact["fact_id"]
            ).text,
        )


class AntigravityRefusesALinkAnywhereUnderBrain(AntigravityHome):
    """SECURITY.md: the transcript is refused when it is a link, and the conversation id when it
    could climb out of `brain/`. That holds for every component below `brain/`, not only the
    file, and at the open as well as at the check."""

    def setUp(self) -> None:
        super().setUp()
        probe = Path(self.temp.name) / "probe"
        try:
            probe.symlink_to(self.temp.name, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted")
        probe.unlink()

    def _outside(self) -> Path:
        elsewhere = Path(self.temp.name) / "elsewhere"
        logs = elsewhere / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        (logs / "transcript.jsonl").write_text(json.dumps(DIRECTION) + "\n", encoding="utf-8")
        return elsewhere

    def _resolved(self) -> str | None:
        return observer.resolve_directions(self.config, self.state, "antigravity", AGY_SID)

    def test_a_linked_transcript_file_is_refused(self) -> None:
        outside = self._outside() / ".system_generated" / "logs" / "transcript.jsonl"
        self.logs.mkdir(parents=True)
        self.transcript.symlink_to(outside)
        self.assertIsNone(self._resolved())

    def test_a_linked_conversation_directory_is_refused(self) -> None:
        (self.agy / "brain").mkdir()
        (self.agy / "brain" / AGY_SID).symlink_to(self._outside(), target_is_directory=True)
        self.assertIsNone(self._resolved())
        (row,) = antigravity.collect(self.config, self.state, time.time(), 24, False)
        self.assertIsNone(row["title"])

    def test_a_linked_logs_directory_is_refused(self) -> None:
        self.logs.parent.mkdir(parents=True)
        self.logs.symlink_to(
            self._outside() / ".system_generated" / "logs", target_is_directory=True
        )
        self.assertIsNone(self._resolved())

    def test_a_linked_system_generated_directory_is_refused(self) -> None:
        self.logs.parent.parent.mkdir(parents=True)
        self.logs.parent.symlink_to(self._outside() / ".system_generated", target_is_directory=True)
        self.assertIsNone(self._resolved())

    def test_a_link_to_another_conversation_inside_brain_is_refused(self) -> None:
        other = self.agy / "brain" / "other" / ".system_generated" / "logs"
        other.mkdir(parents=True)
        (other / "transcript.jsonl").write_text(json.dumps(DIRECTION) + "\n", encoding="utf-8")
        (self.agy / "brain" / AGY_SID).symlink_to(
            self.agy / "brain" / "other", target_is_directory=True
        )
        self.assertIsNone(self._resolved())

    def test_a_store_reached_through_a_linked_home_is_still_read(self) -> None:
        # A link above `brain/` is the person's own layout, such as a dotfiles checkout.
        self.write(DIRECTION)
        real = Path(self.temp.name) / "dotfiles-gemini"
        (self.home / ".gemini").rename(real)
        (self.home / ".gemini").symlink_to(real, target_is_directory=True)
        found = self._resolved()
        self.assertIsNotNone(found)
        self.assertEqual(os.path.normpath(str(self.transcript)), os.path.normpath(str(found)))

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "the open-time refusal needs O_NOFOLLOW")
    def test_a_file_swapped_for_a_link_after_the_check_is_not_followed(self) -> None:
        self.write(DIRECTION)
        path = self._resolved()
        assert path is not None
        outside = self._outside() / ".system_generated" / "logs" / "transcript.jsonl"
        self.transcript.unlink()
        self.transcript.symlink_to(outside)
        self.assertEqual(
            [], project_context.instruction_events(self.config, path, "antigravity", AGY_SID)
        )
        self.assertEqual("", transcripts.antigravity_newest_direction(self.config, path))
        backfill = project_context.instruction_events(
            self.config, path, "antigravity", AGY_SID, max_bytes=1 << 20
        )
        self.assertEqual([], backfill)


class AntigravityTitleFallsBackToTheNewestDirection(AntigravityHome):
    def test_a_log_without_the_marker_takes_the_title_from_the_transcript(self) -> None:
        later = agy(
            "USER_INPUT", 5, "2026-09-23T21:05:00Z", "Now also log each retry", "USER_EXPLICIT"
        )
        self.write(DIRECTION, *WORK, later)
        (row,) = antigravity.collect(self.config, self.state, time.time(), 24, False)
        self.assertEqual("Now also log each retry", row["title"])
        self.assertEqual("Now also log each retry", row["last_prompt"])

    def test_with_neither_the_title_stays_unpublished(self) -> None:
        self.write(*WORK)
        (row,) = antigravity.collect(self.config, self.state, time.time(), 24, False)
        self.assertIsNone(row["title"])
        self.assertEqual("", row["last_prompt"])


class APressOnAHarnessWithNoRecordSaysSo(AntigravityHome):
    REVISIONS = ({"n": 1, "goal": "Add a retry", "at": 1_790_197_100.0},)

    def _row(self, harness: str) -> dict[str, Any]:
        return {"harness": harness, "sid": AGY_SID, "state": "working", "ended_at": None}

    def test_an_antigravity_session_with_directions_reaches_the_model(self) -> None:
        self.write(DIRECTION, *WORK)
        now = time.time()
        (row,) = antigravity.collect(self.config, self.state, now, 24, False)
        context = project_context.collect(
            self.config,
            self.state,
            [row],
            str(row.get("project_key") or row.get("project")),
            now=now,
            focus=("antigravity", AGY_SID),
            model_consent=False,
        )
        calls: list[str] = []

        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            calls.append(prompt)
            return "{}", "ok"

        withheld = reading.record_withheld(context, "antigravity", AGY_SID)
        self.assertEqual("", withheld)
        reading.produce(
            self.config,
            self._row("antigravity"),
            list(self.REVISIONS),
            context["semantic"]["facts"],
            now=1_790_197_300.0,
            stamp_text="x",
            model=model,
            read_lines=True,
            record_withheld=withheld,
        )
        self.assertEqual(1, len(calls))

    def test_a_harness_with_no_reader_is_withheld_before_anything_is_spent(self) -> None:
        row = {**self._row("copilot"), "project": "p", "active": True}
        context = project_context.collect(
            self.config, self.state, [row], "p", now=NOW, focus=("copilot", AGY_SID)
        )
        withheld = reading.record_withheld(context, "copilot", AGY_SID)
        self.assertEqual(reading.WITHHELD_NO_RECORD_READER, withheld)
        calls: list[str] = []

        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            calls.append(prompt)
            return "{}", "ok"

        got = reading.produce(
            self.config,
            self._row("copilot"),
            list(self.REVISIONS),
            [],
            now=1_790_197_300.0,
            stamp_text="x",
            model=model,
            read_lines=True,
            record_withheld=withheld,
        )
        self.assertEqual((None, reading.WITHHELD_NO_RECORD_READER, False), got)
        self.assertEqual([], calls)
        sentence = reading.WITHHELD[reading.WITHHELD_NO_RECORD_READER]
        self.assertNotIn("No entry in the observed record", sentence)

    def test_the_no_reader_sentence_says_what_compass_does_read(self) -> None:
        # Every one of these harnesses' prompts and titles is read for the board (privacy
        # review F1), so the sentence may not say the record goes unread.
        self.assertEqual(
            "Compass reads only this harness's prompts and titles, not the session's work, so "
            "there is nothing to read your words against. No reading was made and nothing was "
            "spent.",
            reading.WITHHELD[reading.WITHHELD_NO_RECORD_READER],
        )

    def test_a_reader_whose_transcript_is_missing_says_unread_not_empty(self) -> None:
        row = {**self._row("antigravity"), "project": "p", "active": True}
        context = project_context.collect(
            self.config, self.state, [row], "p", now=NOW, focus=("antigravity", AGY_SID)
        )
        self.assertEqual(
            reading.WITHHELD_RECORD_UNREAD,
            reading.record_withheld(context, "antigravity", AGY_SID),
        )

    def test_another_sessions_missing_reader_does_not_withhold_this_one(self) -> None:
        context = {
            "sources": {
                "work": {
                    "unavailable": [
                        {
                            "harness": "copilot",
                            "sid": "other",
                            "reason": observer.READER_UNAVAILABLE,
                        }
                    ]
                }
            }
        }
        self.assertEqual("", reading.record_withheld(context, "copilot", AGY_SID))
        self.assertEqual(
            reading.WITHHELD_NO_RECORD_READER, reading.record_withheld(context, "copilot", "other")
        )

    def test_the_reading_route_passes_the_unread_record_to_the_producer(self) -> None:
        row = {**self._row("copilot"), "project": "p", "active": True}
        handler = SimpleNamespace(
            server=SimpleNamespace(
                application=SimpleNamespace(config=self.config, state=self.state, clock=lambda: NOW)
            ),
            _reading_arguments=lambda *_a: {"model": None, "stamp_text": "x", "now": NOW},
        )
        with mock.patch.object(reading, "produce", return_value=(None, "x", False)) as produce:
            compose: Any = http_api._RequestHandler._compose_reading
            compose(
                handler,
                row,
                {"revisions": list(self.REVISIONS)},
                {},
                SimpleNamespace(phase=None, capture=lambda _value: None),
            )
        self.assertEqual(
            reading.WITHHELD_NO_RECORD_READER, produce.call_args.kwargs["record_withheld"]
        )

    def test_every_harness_is_either_read_or_named_unread(self) -> None:
        read = set(observer.TRANSCRIPT_HARNESSES) | set(observer.DIRECTION_HARNESSES)
        self.assertEqual({"claude", "codex", "pi", "antigravity"}, read)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
