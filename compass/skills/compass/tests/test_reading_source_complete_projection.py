"""Long source evidence cannot inherit the board's ranked twelve-row listing."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import project_context as context
from compass_runtime import reading, reading_source, reading_source_final
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory_source

from . import test_reading_source as source_tests
from .test_claude_checks import SHORT, Transcript


class CompleteCanonicalProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        source_tests.CompleteReadingSourceTest.setUp(self)
        parent = Transcript(self.root)
        parent.prompt("Check every parent and delegated change.")
        self.parent_failures = set()
        for number in range(18):
            if number == 7:
                parent.bash("pytest tests/middle_pass.py", "1 failed", is_error=True)
                self.middle = parent.bash("pytest tests/middle_pass.py", "1 passed")
            self.parent_failures.add(
                parent.bash(f"pytest tests/failure_{number}.py", "1 failed", is_error=True)
            )
        parent.write(str(self.root / "src/later.py"))
        parent.save(self.path)
        child = Transcript(self.root)
        child.calls, child.seconds = 1000, 1000
        child.prompt("PRIVATE CHILD PROSE")
        self.child_checks = {
            child.bash(f"pytest tests/child_{number}.py", "1 failed", is_error=True)
            for number in range(13)
        }
        for number in range(13):
            child.write(str(self.root / f"src/child_{number}.py"))
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.child_path)
        self.scan = context._live_check_scan(self.config, str(self.path))
        # Concrete fixture census: 18 failed + one passing history + 13 child
        # checks, one parent file + 13 child files. Not a displayed-list count.
        self.eligible = 46

    def collect(self, **options: Any) -> Any:
        frozen = inventory_source.freeze(
            str(self.path),
            "claude",
            SHORT,
            max_entries=100,
            max_streams=10,
            max_seconds=1,
        )
        return collector.collect(
            self.config,
            frozen,
            ancillary=collector.Ancillary(self.scan.session_dir, self.scan.declared),
            **options,
        )

    def test_long_collector_keeps_all_canonical_candidates_and_history_guards(self) -> None:
        full = reading_source.from_complete_scan(
            self.config,
            self.scan,
            "claude",
            SHORT,
            listed_cap=self.eligible,
        )
        legacy = reading_source.from_complete_scan(self.config, self.scan, "claude", SHORT)
        self.assertEqual(12, len([f for f in legacy.facts if f.get("subject") == "check"]))
        self.assertFalse(
            any(f.get("branch", {}).get("record_id") == self.middle for f in legacy.facts)
        )
        result = self.collect()
        self.assertEqual("", result.reason)
        self.assertTrue(result.source_verified)
        self.assertIsNotNone(result.evidence)
        self.assertEqual(self.eligible + 1, len(result.evidence.facts))
        self.assertEqual(full.facts, result.evidence.facts)
        self.assertEqual(full.press, result.evidence.press)
        self.assertEqual(legacy.press, result.evidence.press)
        checks = [fact for fact in result.evidence.facts if fact.get("subject") == "check"]
        self.assertEqual(
            self.parent_failures | self.child_checks | {self.middle},
            {fact["branch"]["record_id"] for fact in checks},
        )
        passed = next(fact for fact in checks if fact["branch"]["record_id"] == self.middle)
        self.assertEqual("passed", passed["result"])
        self.assertEqual(2, len(passed["runs"]))
        self.assertTrue(passed["earlier_failed"])
        self.assertTrue(passed["before_last_change"])
        # Native Write ages the check; the separate shell-change output guard stays false.
        self.assertFalse(passed["changed_after"])
        self.assertFalse(passed["read_incomplete"])
        children = [fact for fact in checks if fact.get("worker_kind") == "subagent"]
        self.assertEqual(13, len(children))
        self.assertTrue(
            all(fact["result"] == "failed" and fact["result_source"] for fact in children)
        )
        files = [fact for fact in result.evidence.facts if fact.get("subject") == "write"]
        self.assertEqual(14, len(files))
        self.assertEqual(13, len([fact for fact in files if fact.get("worker_kind") == "subagent"]))
        self.assertFalse(any("PRIVATE CHILD PROSE" in str(fact) for fact in result.evidence.facts))
        self.assertTrue(
            all(
                fact["source_session"] == {"harness": "claude", "sid": SHORT}
                for fact in result.evidence.facts
            )
        )
        output = source_tests.CompleteReadingSourceTest.output(result.evidence.press)
        expected_output = source_tests.CompleteReadingSourceTest.output(full.press)
        options = {
            "tool_output": output.tails,
            "changed_after": output.changed_after,
            "read_incomplete": output.read_incomplete,
            "read_agent_words": True,
        }
        self.assertEqual(
            reading.build_ledger(full.facts, "claude", SHORT, **options),
            reading.build_ledger(result.evidence.facts, "claude", SHORT, **options),
        )
        self.assertEqual(
            reading.recorded_from(full.facts, "claude", SHORT, tool_output=expected_output),
            reading.recorded_from(result.evidence.facts, "claude", SHORT, tool_output=output),
        )

    def test_complete_projection_refuses_a_small_allowance_before_ranked_drops(self) -> None:
        self.assertTrue(
            hasattr(context, "ToolReportLimitError"), "complete projection cap refusal is missing"
        )
        with self.assertRaises(context.ToolReportLimitError) as raised:
            reading_source.from_complete_scan(
                self.config,
                self.scan,
                "claude",
                SHORT,
                listed_cap=12,
                require_complete=True,
            )
        self.assertEqual(self.eligible, raised.exception.eligible)
        self.assertEqual(12, raised.exception.limit)
        full = reading_source.from_complete_scan(
            self.config,
            self.scan,
            "claude",
            SHORT,
            listed_cap=self.eligible,
            require_complete=True,
        )
        self.assertEqual(self.eligible + 1, len(full.facts))

    def test_projected_graph_budget_refuses_all_evidence_after_verified_read(self) -> None:
        full = self.collect()
        self.assertEqual(self.eligible + 1, len(full.evidence.facts))
        # Remove the shallow fact dictionaries' measured footprint from the
        # successful job's headroom: the native corpus still fits, projection does not.
        limit = full.usage.retained_bytes - sum(sys.getsizeof(fact) for fact in full.evidence.facts)
        del full
        with (
            mock.patch.object(
                reading_source, "from_complete_scan", wraps=reading_source.from_complete_scan
            ) as project,
            mock.patch.object(
                reading_source_final,
                "build",
                side_effect=AssertionError("projection must refuse before final proof"),
            ),
        ):
            limited = self.collect(limits=replace(collector.Limits(), retained_bytes=limit))
        self.assertTrue(project.called)
        self.assertTrue(limited.source_verified)
        self.assertEqual("retained_bytes", limited.reason)
        self.assertIsNone(limited.evidence)
        self.assertIsNone(limited.words)
        self.assertIsNone(limited.final)
        self.assertLessEqual(limited.usage.retained_bytes, limit)

    def test_compound_candidates_refuse_the_remaining_unit_allowance_explicitly(self) -> None:
        self.child_path.unlink()
        parent = Transcript(self.root)
        parent.prompt("Check each separate target.")
        parent.call(
            "Bash", {"command": "; ".join(f"pytest test_{number}.py" for number in range(1000))}
        )
        parent.save(self.path)
        result = self.collect(limits=replace(collector.Limits(), retained_units=1000))
        self.assertTrue(result.source_verified)
        self.assertEqual("canonical_limit", result.reason)
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.words)
        self.assertIsNone(result.final)
