"""Private Originals positions come from native records, never their clocks."""

from __future__ import annotations

import copy
import os
import unittest
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import project_context as context
from compass_runtime import reading_source
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory

from . import test_reading_source as sources
from .test_claude_checks import SHORT, Transcript


class PhysicalOriginsTest(unittest.TestCase):
    def setUp(self) -> None:
        sources.CompleteReadingSourceTest.setUp(self)
        self.child_path.unlink()
        self.parent = Transcript(self.root)

    def collect(self, **options: Any) -> Any:
        self.parent.save(self.path)
        frozen = inventory.freeze(
            str(self.path), "claude", SHORT, max_entries=100, max_streams=10, max_seconds=1
        )
        result = collector.collect(
            self.config,
            frozen,
            ancillary=collector.Ancillary(str(self.root)),
            clock=lambda: 0.0,
            **options,
        )
        self.assertTrue(hasattr(result, "origins"), "private physical origins are missing")
        return result

    def placed(self, result: Any) -> list[Any]:
        self.assertEqual("", result.reason)
        self.assertEqual(len(result.evidence.facts), len(result.origins))
        for index, (fact, origin) in enumerate(
            zip(result.evidence.facts, result.origins, strict=True)
        ):
            self.assertEqual((fact["fact_id"], index), (origin.fact_id, origin.canonical_index))
        return sorted(
            (origin for origin in result.origins if origin.position is not None),
            key=lambda origin: (
                origin.position.stream,
                origin.position.start_offset,
                origin.canonical_index,
            ),
        )

    def assert_position(self, origin: Any, path: Any, stream: int, record: int) -> None:
        lines = path.read_bytes().splitlines(keepends=True)
        self.assertEqual("", origin.reason)
        self.assertEqual(
            (stream, record, sum(map(len, lines[:record])), sum(map(len, lines[: record + 1]))),
            (
                origin.position.stream,
                origin.position.record,
                origin.position.start_offset,
                origin.position.end_offset,
            ),
        )

    def test_clock_rollback_ties_and_native_message_positions_preserve_canonical_facts(
        self,
    ) -> None:
        self.parent.prompt("First physical direction.")
        self.parent._entry("assistant", [{"type": "text", "text": "Second physical record."}])
        self.parent.prompt("Third physical direction.")
        self.parent.rows[0]["timestamp"] = "2026-11-05T03:00:00Z"
        self.parent.rows[1]["timestamp"] = "2026-11-05T01:00:00Z"
        self.parent.rows[2]["timestamp"] = self.parent.rows[1]["timestamp"]
        self.parent.save(self.path)
        expected = reading_source.from_complete_scan(
            self.config, context._live_check_scan(self.config, str(self.path)), "claude", SHORT
        )
        with mock.patch.object(context, "_live_check_scan", side_effect=AssertionError("rescan")):
            result = self.collect(page_bytes=97)
        self.assertEqual(expected, result.evidence)
        placed = self.placed(result)
        self.assertEqual(3, len(placed))
        for number, origin in enumerate(placed):
            self.assert_position(origin, self.path, 0, number)
        self.assertEqual([0, 2, 1], [origin.canonical_index for origin in placed])
        self.assertEqual(3 * self.path.stat().st_size, result.usage.source_bytes)

    def test_grouped_rerun_points_to_latest_call_not_later_result_and_segments_share_position(
        self,
    ) -> None:
        self.parent.prompt("Check the changes.")
        first = self.parent.bash("pytest tests/retry.py", "1 failed", is_error=True)
        selected_record = len(self.parent.rows)
        selected = self.parent.call("Bash", {"command": "pytest tests/retry.py"})
        self.parent.write(str(self.root / "later.py"))
        self.parent.result(selected, "1 passed", is_error=False)
        segment_record = len(self.parent.rows)
        segmented = self.parent.bash("pytest tests/other.py && ruff check .", "all pass")
        result = self.collect(page_bytes=127)
        self.placed(result)
        check = next(
            f for f in result.evidence.facts if f.get("branch", {}).get("record_id") == selected
        )
        self.assertEqual(2, len(check["runs"]))
        self.assertNotEqual(first, selected)
        origin = next(o for o in result.origins if o.fact_id == check["fact_id"])
        self.assert_position(origin, self.path, 0, selected_record)
        segments = [
            o
            for o in result.origins
            if result.evidence.facts[o.canonical_index].get("branch", {}).get("record_id")
            == segmented
        ]
        self.assertEqual(2, len(segments))
        self.assertNotEqual(segments[0].fact_id, segments[1].fact_id)
        for origin in segments:
            self.assert_position(origin, self.path, 0, segment_record)

    def test_tool_variants_and_admitted_children_follow_frozen_inventory_order(self) -> None:
        self.parent.prompt("Apply the change.")
        calls = {}
        for name, arguments in (
            ("Skill", {"skill": "review"}),
            ("Write", {"file_path": str(self.root / "file.py"), "content": "body"}),
            ("Bash", {"command": "rm obsolete.py"}),
            ("Agent", {"prompt": "child", "run_in_background": True}),
        ):
            position = len(self.parent.rows)
            call = self.parent.call(name, arguments)
            self.parent.result(call, "done", is_error=False)
            calls[call] = position
        pr_position = len(self.parent.rows)
        pr = self.parent.call("Bash", {"command": "gh pr create --title private"})
        self.parent.result(
            pr,
            "created",
            is_error=False,
            tool_use_result={
                "gitOperation": {
                    "pr": {
                        "number": 7,
                        "url": "https://github.com/example/widgets/pull/7",
                        "action": "created",
                    }
                }
            },
        )
        calls[pr] = pr_position
        child_paths = []
        for number, filename in enumerate(("agent-ab12.jsonl", "agent-cd34.jsonl")):
            child = Transcript(self.root)
            child.calls = 100 * (number + 1)
            child.prompt("CHILD PROSE")
            child.bash(f"pytest tests/child{number}.py", "1 passed")
            child.call("Agent", {"run_in_background": True})
            for row in child.rows:
                row["isSidechain"] = True
                row["timestamp"] = "2026-01-01T00:00:00Z"
            path = self.path.with_suffix("") / "subagents" / filename
            child.save(path)
            os.utime(path, (200 - number, 200 - number))
            child_paths.append(path)
        result = self.collect()
        placed = self.placed(result)
        self.assertEqual(len(result.origins), len(placed))
        self.assertEqual(
            sorted(o.position.stream for o in placed), [o.position.stream for o in placed]
        )
        subjects = {fact.get("subject") for fact in result.evidence.facts}
        self.assertTrue({"skill", "write", "command", "launch", "pr", "check"} <= subjects)
        for origin in placed:
            fact = result.evidence.facts[origin.canonical_index]
            call = fact.get("branch", {}).get("record_id")
            if origin.position.stream == 0 and call in calls:
                self.assert_position(origin, self.path, 0, calls[call])
            elif origin.position.stream:
                number = origin.position.stream - 1
                self.assert_position(
                    origin, child_paths[number], number + 1, 1 if fact["subject"] == "check" else 3
                )
        self.assertNotIn("CHILD PROSE", str(result.evidence.facts))
        self.assertNotIn(str(self.root), str(result.origins))

    def test_queued_duplicates_use_exact_join_position_and_raw_conflict_is_unplaced(self) -> None:
        queued = {
            "type": "attachment",
            "timestamp": "2026-11-05T02:00:00Z",
            "attachment": {
                "type": "queued_command",
                "timestamp": "2026-11-05T01:00:00Z",
                "commandMode": "prompt",
                "origin": {"kind": "human"},
                "prompt": "Review parser.",
            },
        }
        self.parent.rows = [queued, copy.deepcopy(queued)]
        result = self.collect()
        placed = self.placed(result)
        self.assertEqual(1, len(placed))
        self.assert_position(placed[0], self.path, 0, 1)
        self.assertEqual(result.words[0].at, result.evidence.facts[0]["at"])
        self.parent.rows[0]["attachment"]["prompt"] += ' password="FIRST"'
        self.parent.rows[1]["attachment"]["prompt"] += ' password="OTHER"'
        result = self.collect()
        self.assertEqual([], self.placed(result))
        self.assertEqual("conflict", result.words[0].reason)
        self.assertEqual("conflict", result.origins[0].reason)
        self.assertIsNone(result.origins[0].position)

    def test_ambiguous_tool_identity_and_foreign_message_are_explicit_unknowns(self) -> None:
        self.parent.bash("pytest tests/one.py", "1 passed")
        self.parent.rows.append(copy.deepcopy(self.parent.rows[0]))
        foreign = self.parent._entry("assistant", [{"type": "text", "text": "Foreign words."}])
        foreign["sessionId"] = "foreign"
        result = self.collect()
        self.assertEqual([], self.placed(result))
        self.assertEqual({"ambiguous", "source"}, {o.reason for o in result.origins})
        # Missing native association cannot be repaired using the same timestamp/title.
        original = reading_source.from_complete_scan

        def missing(*args: Any, **kwargs: Any) -> Any:
            projected = original(*args, **kwargs)
            for fact in projected.facts:
                if fact.get("subject") == "check":
                    fact["branch"]["record_id"] = "not-a-native-call"
            return projected

        with mock.patch.object(reading_source, "from_complete_scan", side_effect=missing):
            result = self.collect()
        self.assertIn("missing", {o.reason for o in result.origins})
        self.assertTrue(all(o.position is None for o in result.origins))

    def test_returned_origin_graph_is_inside_retention_and_snapshot_account(self) -> None:
        self.parent.prompt("Bound the retained evidence.")
        for number in range(8):
            self.parent.bash(f"pytest tests/{number}.py", "1 passed")
        full = self.collect()
        self.placed(full)
        self.assertEqual(full.usage, full.snapshot.account.usage)
        self.assertEqual(full.usage.retained_bytes, full.snapshot.account.retained_base_bytes)
        limits = replace(collector.Limits(), retained_bytes=full.usage.retained_bytes // 2)
        refused = self.collect(limits=limits)
        self.assertEqual("retained_bytes", refused.reason)
        for field in ("evidence", "words", "final", "snapshot", "origins"):
            self.assertIsNone(getattr(refused, field))

    def test_cancellation_after_association_withholds_origins_and_all_other_proof(self) -> None:
        self.parent.prompt("Keep the private proof bounded.")
        stopped = False
        original = collector._Collection.origin_for

        def cancel_after(owner: Any, fact: Any, index: int) -> Any:
            nonlocal stopped
            result = original(owner, fact, index)
            stopped = True
            return result

        with mock.patch.object(collector._Collection, "origin_for", cancel_after):
            result = self.collect(cancelled=lambda: stopped)
        self.assertEqual("cancelled", result.reason)
        self.assertTrue(result.source_verified)
        for field in ("evidence", "words", "final", "snapshot", "origins"):
            self.assertIsNone(getattr(result, field))
