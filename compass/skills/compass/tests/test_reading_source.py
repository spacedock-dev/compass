"""Complete native scans retain Analyze's canonical evidence before any paging."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict
from unittest import mock

from compass_runtime import ci_read, reading, reading_route, reading_source
from compass_runtime import project_context as context
from compass_runtime.config import build_runtime_config

from .test_claude_checks import SHORT, Transcript

if TYPE_CHECKING:
    from collections.abc import Mapping


class LedgerOptions(TypedDict):
    tool_output: Mapping[str, str]
    changed_after: frozenset[tuple[str, str]]
    read_incomplete: frozenset[tuple[str, str]]
    read_agent_words: bool


class CompleteReadingSourceFixture(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "session.jsonl"
        self.goal_texts: tuple[str, ...] = ()
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        parent = Transcript(self.root)
        parent.prompt("Check the parent and delegated work.")
        parent._entry("assistant", [{"type": "text", "text": "I will inspect both."}])
        parent.bash("pytest tests/test_parent.py", "1 passed")
        parent.write(str(self.root / "parent.py"))
        parent.save(self.path)
        child = Transcript(self.root)
        child.calls = 20
        child.seconds = 60
        child.prompt("CHILD PRIVATE PROSE")
        self.child_call = child.bash("pytest tests/test_child.py", "1 failed", is_error=True)
        child.write(str(self.root / "child.py"))
        for row in child.rows:
            row["isSidechain"] = True
        self.child_path = self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl"
        child.save(self.child_path)
        self.scan = context._live_check_scan(self.config, str(self.path))

    def adapter(self) -> Any:
        self.assertIsNotNone(
            importlib.util.find_spec("compass_runtime.reading_source"),
            "the complete-scan canonical adapter is not implemented",
        )
        importlib.import_module("compass_runtime.reading_source")
        return reading_source

    def expected(self) -> tuple[tuple[dict[str, Any], ...], context.PressChecks]:
        with context.shared_tallies():
            events, _ = context.claude_tool_reports(
                self.config, str(self.path), SHORT, goal_texts=self.goal_texts
            )
            press = context.claude_check_press(
                self.config, str(self.path), goal_texts=self.goal_texts
            )
        messages = context.instruction_events(self.config, str(self.path), "claude", SHORT)
        messages += context.agent_message_events(self.config, str(self.path), "claude", SHORT)
        facts = context._semantic_model([*messages, *events], [])["facts"]
        return tuple(facts), press

    @staticmethod
    def output(press: context.PressChecks) -> reading.ToolOutput:
        return reading.ToolOutput(
            destination="test destination",
            label="test route",
            tails=reading_route.tails_for("codex", "claude", press.tails, press.tier3_calls),
            changed_after=press.changed_after,
            read_incomplete=press.read_incomplete,
            passes_and_writes=press.passes_and_writes,
            removals=press.removals,
            masked_values=press.masked_values,
            masked_values_partial=press.masked_values_partial,
            quotable=press.quotable,
        )

    def assert_parity(self) -> reading_source.CanonicalEvidence:
        self.adapter()
        result = reading_source.from_complete_scan(self.config, self.scan, "claude", SHORT)
        expected, press = self.expected()
        self.assertEqual(expected, result.facts)
        self.assertEqual(press, result.press)
        self.assertEqual(len(result.facts), len({fact["fact_id"] for fact in result.facts}))
        expected_output, actual_output = self.output(press), self.output(result.press)
        self.assertEqual(expected_output, actual_output)
        options: LedgerOptions = {
            "tool_output": actual_output.tails,
            "changed_after": actual_output.changed_after,
            "read_incomplete": actual_output.read_incomplete,
            "read_agent_words": True,
        }
        self.assertEqual(
            reading.build_ledger(expected, "claude", SHORT, **options),
            reading.build_ledger(result.facts, "claude", SHORT, **options),
        )
        self.assertEqual(
            reading.recorded_from(expected, "claude", SHORT, tool_output=expected_output),
            reading.recorded_from(result.facts, "claude", SHORT, tool_output=actual_output),
        )

        return result


class CompleteReadingSourceTest(CompleteReadingSourceFixture):
    def test_parent_and_admitted_child_keep_rich_facts_and_reading_guards(self) -> None:
        result = self.assert_parity()
        child = next(
            fact
            for fact in result.facts
            if fact.get("branch", {}).get("record_id") == self.child_call
        )
        self.assertEqual("failed", child["result"])
        self.assertEqual("subagent", child["worker_kind"])
        self.assertEqual({"harness": "claude", "sid": SHORT}, child["source_session"])
        self.assertEqual("exact", child["evidence"]["confidence"])
        self.assertIn("subagent", child["evidence"]["source"])
        self.assertEqual(self.child_call, child["branch"]["record_id"])
        self.assertEqual("check", child["subject"])
        self.assertTrue(child["runs"])
        self.assertIn("result_at", child)
        self.assertIn("result_source", child)
        self.assertFalse(any("CHILD PRIVATE PROSE" in str(fact) for fact in result.facts))
        self.assertFalse(
            any(":segment:" in str(fact) or ":write:" in str(fact) for fact in result.facts)
        )

    def test_incomplete_or_unsupported_scan_is_refused(self) -> None:
        adapter = self.adapter()
        parent_path, parent_read = self.scan.source_reads[0]
        assert parent_read is not None
        scans = [
            self.scan._replace(unread=1),
            self.scan._replace(horizon=1.0),
            self.scan._replace(named_unread=True),
            self.scan._replace(parent_failed=True),
            self.scan._replace(orphan_unread=True),
            self.scan._replace(source_reads=()),
            self.scan._replace(source_reads=((parent_path, None),)),
            self.scan._replace(source_reads=((parent_path, replace(parent_read, complete=False)),)),
        ]
        for scan in scans:
            with self.subTest(scan=scan._fields), self.assertRaises(ValueError):
                adapter.from_complete_scan(self.config, scan, "claude", SHORT)
        with self.assertRaises(ValueError):
            adapter.from_complete_scan(self.config, self.scan, "codex", SHORT)

    def test_record_claims_cannot_override_canonical_source_and_snapshots_own_their_data(
        self,
    ) -> None:
        adapter = self.adapter()
        self.scan.parent[0]["source_session"] = {"harness": "claude", "sid": "foreign"}
        self.scan.parent[0]["evidence"] = {"source": "invented proof"}
        first = adapter.from_complete_scan(self.config, self.scan, "claude", SHORT)
        saved = copy.deepcopy(first)
        second = adapter.from_complete_scan(self.config, self.scan, "claude", SHORT)
        check = next(fact for fact in second.facts if fact.get("subject") == "check")
        check["runs"][0]["piped"] = "changed"
        check["evidence"]["source"] = "changed"
        second.press.tails.clear()
        self.scan.parent.clear()
        self.scan.children[0].clear()
        self.assertEqual(saved, first)
        for fact in first.facts:
            self.assertEqual({"harness": "claude", "sid": SHORT}, fact["source_session"])
            self.assertNotEqual("invented proof", fact["evidence"]["source"])

    def new_parent(self) -> Transcript:
        self.child_path.unlink(missing_ok=True)
        parent = Transcript(self.root)
        parent.prompt("Update the widget.")
        return parent

    def project(self, parent: Transcript) -> reading_source.CanonicalEvidence:
        parent.save(self.path)
        self.scan = context._live_check_scan(
            self.config, str(self.path), goal_texts=self.goal_texts
        )
        return self.assert_parity()

    @staticmethod
    def checks(result: reading_source.CanonicalEvidence) -> list[dict[str, Any]]:
        return [fact for fact in result.facts if fact.get("subject") == "check"]

    def test_later_write_ages_the_same_passing_check_in_facts_and_recorded_work(self) -> None:
        parent = self.new_parent()
        call = parent.bash("pytest tests/widget.py", "1 passed")
        parent.write(str(self.root / "src/widget.py"))
        result = self.project(parent)
        (check,) = self.checks(result)
        self.assertEqual(call, check["branch"]["record_id"])
        self.assertEqual("passed", check["result"])
        self.assertIs(True, check["before_last_change"])
        recorded = reading.recorded_from(
            result.facts, "claude", SHORT, tool_output=self.output(result.press)
        )
        self.assertIs(True, recorded.checks[0]["stale"])
        self.assertEqual(["src/widget.py"], [write.path for write in recorded.writes])

    def test_combined_check_history_keeps_failures_and_unrecorded_runs(self) -> None:
        cases = (
            (("failed", "passed"), "passed", True),
            (("passed", "failed"), "failed", False),
            (("passed", "unrecorded"), "not-recorded", False),
            (("unrecorded", "passed"), "passed", False),
        )
        for history, expected_result, earlier_failed in cases:
            with self.subTest(history=history):
                parent = self.new_parent()
                calls = []
                for outcome in history:
                    if outcome == "unrecorded":
                        calls.append(parent.call("Bash", {"command": "pytest tests/widget.py"}))
                    else:
                        calls.append(
                            parent.bash(
                                "pytest tests/widget.py",
                                "1 failed" if outcome == "failed" else "1 passed",
                                is_error=outcome == "failed",
                            )
                        )
                result = self.project(parent)
                (check,) = self.checks(result)
                self.assertEqual(calls[-1], check["branch"]["record_id"])
                self.assertEqual(expected_result, check["result"])
                self.assertIs(earlier_failed, check["earlier_failed"])
                self.assertEqual(2, len(check["runs"]))
                if history[-1] == "unrecorded":
                    self.assertNotIn("result_at", check)
                    self.assertNotIn("result_source", check)
                if history[0] == "unrecorded":
                    self.assertEqual([check["runs"][0]["at"]], check["earlier_unrecorded_ats"])

    def test_repeated_segments_keep_one_canonical_check_and_both_run_records(self) -> None:
        parent = self.new_parent()
        call = parent.bash("pytest tests/widget.py; pytest tests/widget.py", "1 passed")
        result = self.project(parent)
        (check,) = self.checks(result)
        self.assertEqual(call, check["branch"]["record_id"])
        self.assertEqual(2, len(check["runs"]))
        self.assertEqual({"piped", "at"}, set(check["runs"][0]))
        self.assertNotIn(":segment:", str(result.facts))

    @staticmethod
    def push_verdict(facts: tuple[dict[str, Any], ...], call: str) -> reading.Criterion:
        ledger = reading.build_ledger(facts, "claude", SHORT, tool_output={}, read_agent_words=True)
        goal, lines = "Update the widget.", ("Do not push to main",)
        _prompt, selection = reading.build_prompt(ledger, goal=goal, lines=lines, max_bytes=16_384)
        fact_id = next(
            fact["fact_id"] for fact in facts if fact.get("branch", {}).get("record_id") == call
        )
        cites = [
            index
            for index, row in selection.by_index().items()
            if row["id"] == fact_id or row["type"] == "agent_message"
        ]
        parsed = reading.parse_reply(
            json.dumps({"line_1": {"result": "departure", "cites": cites, "detail": "Read so."}}),
            reading.constraints_for(selection.lines, claims=selection.asked_claims),
        )
        return reading.resolve(
            parsed,
            selection,
            goal=goal,
            lines=selection.lines,
            detail_cap_chars=200,
            recorded=reading.recorded_from(facts, "claude", SHORT),
        )["line_1"]

    def test_native_push_evidence_preserves_resolver_outcomes_and_vendor_tail_filter(self) -> None:
        cases = (
            (
                "git push origin main",
                "passed",
                False,
                reading.RESULT_DEPARTURE,
                reading.WHY_RECORDED_COMMAND,
            ),
            ("git push origin main", "failed", False, reading.RESULT_DEPARTURE, reading.WHY_STANDS),
            (
                "git push --dry-run origin main",
                "passed",
                False,
                reading.RESULT_UNVERIFIABLE,
                reading.WHY_NO_WORK_SHOWN,
            ),
            (
                "git push origin main || true",
                "passed",
                True,
                reading.RESULT_UNVERIFIABLE,
                reading.WHY_NO_WORK_SHOWN,
            ),
            (
                "git push origin main",
                "unrecorded",
                False,
                reading.RESULT_UNVERIFIABLE,
                reading.WHY_NO_WORK_SHOWN,
            ),
        )
        for command, outcome, cannot_fail, verdict, why in cases:
            with self.subTest(command=command, outcome=outcome):
                parent = self.new_parent()
                call = parent.call("Bash", {"command": command})
                if outcome != "unrecorded":
                    parent.result(
                        call,
                        "Exit code 1\nPUSH OUTPUT" if outcome == "failed" else "PUSH OUTPUT",
                        is_error=outcome == "failed",
                    )
                parent._entry("assistant", [{"type": "text", "text": "The command is complete."}])
                result = self.project(parent)
                command_fact = next(
                    fact for fact in result.facts if fact.get("subject") == "command"
                )
                self.assertIs(cannot_fail, command_fact["cannot_fail"])
                self.assertIn(call, result.press.tier3_calls)
                self.assertNotIn(call, self.output(result.press).tails)
                expected, _press = self.expected()
                resolved = self.push_verdict(result.facts, call)
                self.assertEqual(self.push_verdict(expected, call), resolved)
                self.assertEqual((verdict, why), (resolved["result"], resolved["why"]))
                if why == reading.WHY_RECORDED_COMMAND:
                    self.assertEqual(command_fact["fact_id"], resolved["cites"][0])

    def test_skill_structured_pr_and_removal_survive_without_private_arguments(self) -> None:
        parent = self.new_parent()
        skill = parent.call("Skill", {"skill": "widget-check", "args": "PRIVATE SKILL ARGS"})
        parent.result(skill, "Launching skill", tool_use_result={"success": True})
        call = parent.call("Bash", {"command": "gh pr create --title PRIVATE_TITLE"})
        parent.result(
            call,
            "PRIVATE OUTPUT",
            is_error=False,
            tool_use_result={
                "gitOperation": {
                    "pr": {
                        "number": 7,
                        "url": "https://github.com/example/widgets/pull/7",
                        "action": "created",
                    }
                },
            },
        )
        parent.bash("rm docs/obsolete.md", "", is_error=False)
        result = self.project(parent)
        by_subject = {fact.get("subject"): fact for fact in result.facts}
        self.assertEqual("widget-check", by_subject["skill"]["summary"])
        self.assertEqual(skill, by_subject["skill"]["branch"]["record_id"])
        self.assertEqual("example/widgets", by_subject["pr"]["pr_repository"])
        self.assertEqual(7, by_subject["pr"]["pr_number"])
        self.assertEqual(call, by_subject["pr"]["branch"]["record_id"])
        for private in ("PRIVATE SKILL ARGS", "PRIVATE_TITLE", "PRIVATE OUTPUT"):
            self.assertNotIn(private, str(result.facts))
        recorded = reading.recorded_from(
            result.facts, "claude", SHORT, tool_output=self.output(result.press)
        )
        self.assertEqual(7, recorded.prs[0].number)
        self.assertEqual(
            [("docs/obsolete.md", "deleted")],
            [(removal.path, removal.kind) for removal in recorded.removals],
        )

    def test_shared_output_does_not_become_attributable_check_evidence(self) -> None:
        for command, quotable in (("pytest", True), ("pytest && ruff check .", False)):
            with self.subTest(command=command):
                parent = self.new_parent()
                call = parent.bash(command, "1 passed")
                result = self.project(parent)
                if quotable:
                    self.assertEqual({(call, "pytest"): "1 passed"}, result.press.quotable)
                    self.assertNotIn(call, result.press.shared_calls)
                else:
                    self.assertEqual({}, result.press.quotable)
                    self.assertIn(call, result.press.shared_calls)

    def test_native_ci_binding_survives_with_unbound_poll_withheld(self) -> None:
        parent = self.new_parent()
        self.goal_texts = ("https://github.com/example/widgets/pull/7",)
        bound = parent.bash("gh pr checks 7", "all pass")
        unbound = parent.bash("gh pr checks 99", "all pass")
        with mock.patch.object(
            ci_read, "folder_remote", return_value=("github.com", "example/widgets")
        ):
            result = self.project(parent)
        polls = {
            fact["branch"]["record_id"]: fact
            for fact in result.facts
            if fact.get("subject") in {"command", "ci_command"}
        }
        self.assertEqual(("ci_command", 2), (polls[bound]["subject"], polls[bound]["tier"]))
        self.assertIs(False, polls[bound]["cannot_fail"])
        self.assertNotIn("result_reason", polls[bound])
        self.assertEqual(
            ("command", 3, True, "ci_poll_unbound"),
            (
                polls[unbound]["subject"],
                polls[unbound]["tier"],
                polls[unbound]["cannot_fail"],
                polls[unbound]["result_reason"],
            ),
        )
        self.assertNotIn(unbound, self.output(result.press).tails)
