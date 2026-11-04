"""Complete native scans retain Analyze's canonical evidence before any paging."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from compass_runtime import project_context as context
from compass_runtime import reading, reading_route
from compass_runtime.config import build_runtime_config

from .test_claude_checks import SHORT, Transcript


class CompleteReadingSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "session.jsonl"
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
        return importlib.import_module("compass_runtime.reading_source")

    def expected(self) -> tuple[tuple[dict[str, Any], ...], context.PressChecks]:
        with context.shared_tallies():
            events, _ = context.claude_tool_reports(self.config, str(self.path), SHORT)
            press = context.claude_check_press(self.config, str(self.path))
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

    def test_parent_and_admitted_child_keep_rich_facts_and_reading_guards(self) -> None:
        adapter = self.adapter()
        result = adapter.from_complete_scan(self.config, self.scan, "claude", SHORT)
        expected, press = self.expected()
        self.assertEqual(expected, result.facts)
        self.assertEqual(press, result.press)
        self.assertEqual(len(result.facts), len({fact["fact_id"] for fact in result.facts}))
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
        expected_output, actual_output = self.output(press), self.output(result.press)
        self.assertEqual(expected_output, actual_output)
        options = {
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
