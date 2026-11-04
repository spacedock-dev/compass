"""A bounded private collector must verify a complete native corpus before projection."""

from __future__ import annotations

import importlib
import importlib.util
import math
import unittest
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import project_context as context
from compass_runtime import reading, reading_source
from compass_runtime import reading_source_inventory as inventory_source
from compass_runtime import reading_source_stream as raw_source

from . import test_reading_source as source_tests
from .test_claude_checks import SHORT, Transcript, hook_stdout


class BoundedReadingCollectionTest(unittest.TestCase):
    def setUp(self) -> None:
        source_tests.CompleteReadingSourceTest.setUp(self)

    def module(self) -> Any:
        self.assertIsNotNone(
            importlib.util.find_spec("compass_runtime.reading_source_collect"),
            "bounded verified canonical collection is not implemented",
        )
        return importlib.import_module("compass_runtime.reading_source_collect")

    def inventory(self, **options: Any) -> Any:
        return inventory_source.freeze(
            str(self.path),
            "claude",
            SHORT,
            max_entries=options.get("max_entries", 100),
            max_streams=10,
            max_seconds=1,
        )

    def collect(self, *, inventory: Any = None, limits: Any = None, **options: Any) -> Any:
        module = self.module()
        return module.collect(
            self.config,
            inventory or self.inventory(),
            ancillary=module.Ancillary(self.scan.session_dir, self.scan.declared),
            limits=limits or module.Limits(),
            page_bytes=options.pop("page_bytes", 127),
            **options,
        )

    def test_tiny_pages_preserve_combined_history_and_exact_rich_oracle(self) -> None:
        parent = Transcript(self.root)
        parent.prompt("Update the widget and check delegated work.")
        parent.bash("pytest tests/widget.py", "1 failed", is_error=True)
        parent.write(str(self.root / "src/widget.py"))
        parent.bash("pytest tests/widget.py", "1 passed")
        parent.write(str(self.root / "src/later.py"))
        pending = parent.call("Bash", {"command": "pytest tests/widget.py"})
        rewrite = parent.call("Bash", {"command": "ruff check src"})
        parent.hook_rewrite(rewrite, hook_stdout("rtk ruff check src"))
        parent.result(rewrite, "2 failed", is_error=False)
        parent.save(self.path)
        self.scan = context._live_check_scan(self.config, str(self.path))
        expected, press = source_tests.CompleteReadingSourceTest.expected(self)
        result = self.collect()
        self.assertEqual("", result.reason)
        self.assertTrue(result.source_verified)
        self.assertIsNotNone(result.evidence)
        self.assertEqual(expected, result.evidence.facts)
        self.assertEqual(press, result.evidence.press)
        output = source_tests.CompleteReadingSourceTest.output(press)
        actual = source_tests.CompleteReadingSourceTest.output(result.evidence.press)
        self.assertEqual(output, actual)
        options = {
            "tool_output": output.tails,
            "changed_after": output.changed_after,
            "read_incomplete": output.read_incomplete,
            "read_agent_words": True,
        }
        self.assertEqual(
            reading.build_ledger(expected, "claude", SHORT, **options),
            reading.build_ledger(result.evidence.facts, "claude", SHORT, **options),
        )
        self.assertEqual(
            reading.recorded_from(expected, "claude", SHORT, tool_output=output),
            reading.recorded_from(result.evidence.facts, "claude", SHORT, tool_output=actual),
        )
        pending_fact = next(
            f for f in result.evidence.facts if f.get("branch", {}).get("record_id") == pending
        )
        self.assertEqual("not-recorded", pending_fact["result"])
        self.assertEqual(3, len(pending_fact["runs"]))
        self.assertTrue(pending_fact["earlier_failed"])
        self.assertEqual(
            "not-recorded",
            next(
                f["result"]
                for f in result.evidence.facts
                if f.get("branch", {}).get("record_id") == rewrite
            ),
        )
        self.assertTrue(any(f.get("before_last_change") for f in result.evidence.facts))
        self.assertFalse(any("CHILD PRIVATE PROSE" in str(f) for f in result.evidence.facts))
        total = sum(stream.cursor.frozen.end_offset for stream in self.inventory().streams)
        self.assertEqual(3 * total, result.usage.source_bytes)
        self.assertGreater(result.usage.source_pages, 30)
        self.assertGreater(result.usage.retained_bytes, total)
        self.assertGreater(result.usage.retained_units, len(parent.rows))

    def test_verification_and_page_costs_are_reserved_before_reading(self) -> None:
        module = self.module()
        inventory = self.inventory()
        total = sum(s.cursor.frozen.end_offset for s in inventory.streams)
        pages = sum(
            3 * max(1, math.ceil(s.cursor.frozen.end_offset / 127)) for s in inventory.streams
        )
        cases = (
            (replace(module.Limits(), source_bytes=3 * total - 1), "source_bytes"),
            (replace(module.Limits(), source_pages=pages - 1), "source_pages"),
            (replace(module.Limits(), retained_bytes=1), "retained_bytes"),
            (replace(module.Limits(), retained_units=1), "retained_units"),
            (replace(module.Limits(), prepare_ms=0), "time"),
        )
        for limits, reason in cases:
            with (
                self.subTest(reason=reason),
                mock.patch.object(
                    raw_source, "read", side_effect=AssertionError("must reserve before reading")
                ),
            ):
                result = self.collect(inventory=inventory, limits=limits)
            self.assertIsNone(result.evidence)
            self.assertEqual(reason, result.reason)
            self.assertEqual(0, result.usage.source_bytes)

    def test_retained_raw_parsed_and_projection_state_must_fit_together(self) -> None:
        module = self.module()
        result = self.collect(limits=replace(module.Limits(), retained_bytes=20_000))
        self.assertIsNone(result.evidence)
        self.assertEqual("retained_bytes", result.reason)
        self.assertGreater(result.usage.source_bytes, 0)
        self.assertLessEqual(result.usage.retained_bytes, 20_000)
        with mock.patch.object(
            reading_source,
            "from_complete_scan",
            return_value=reading_source.CanonicalEvidence(
                ({"huge": "x" * 40_000},),
                context._press(context._tally_from_scan(self.scan)),
            ),
        ) as project:
            projection = self.collect(limits=replace(module.Limits(), retained_bytes=60_000))
        self.assertTrue(project.called)
        self.assertIsNone(projection.evidence)
        self.assertEqual("retained_bytes", projection.reason)

    def test_unknown_inventory_and_permanent_raw_gaps_never_project(self) -> None:
        self.module()
        with mock.patch.object(
            reading_source, "from_complete_scan", side_effect=AssertionError("gap")
        ):
            unknown = self.collect(inventory=self.inventory(max_entries=0))
            self.assertEqual("inventory", unknown.reason)
            self.assertTrue(unknown.inventory_gaps)
            with self.path.open("ab") as target:
                target.write(b'{"unfinished":')
            partial = self.collect()
        self.assertIsNone(partial.evidence)
        self.assertEqual("source_gap", partial.reason)
        self.assertTrue(
            any(gap.gap.reason == "unfinished_line" and gap.gap.permanent for gap in partial.gaps)
        )
        self.assertFalse(partial.source_verified)

    def test_rewrite_after_baseline_refuses_all_provisional_rows(self) -> None:
        self.module()
        original = raw_source.read
        changed = False

        def read(cursor: Any, **options: Any) -> Any:
            nonlocal changed
            page = original(cursor, **options)
            if cursor.phase == "records" and not changed:
                data = self.path.read_bytes()
                self.path.write_bytes(data.replace(b"Check the parent", b"Other the parent", 1))
                changed = True
            return page

        with mock.patch.object(raw_source, "read", side_effect=read):
            result = self.collect()
        self.assertIsNone(result.evidence)
        self.assertEqual("source_changed", result.reason)
        self.assertTrue(any(gap.gap.reason == "source_changed" for gap in result.gaps))

    def test_cancellation_is_checked_after_pages_and_after_projection(self) -> None:
        self.module()
        stopped = False
        original = raw_source.read

        def read(cursor: Any, **options: Any) -> Any:
            nonlocal stopped
            page = original(cursor, **options)
            stopped = True
            return page

        with mock.patch.object(raw_source, "read", side_effect=read):
            result = self.collect(cancelled=lambda: stopped)
        self.assertEqual("cancelled", result.reason)
        self.assertEqual(1, result.usage.source_pages)
        stopped = False
        project = reading_source.from_complete_scan

        def materialize(*args: Any, **kwargs: Any) -> Any:
            nonlocal stopped
            value = project(*args, **kwargs)
            stopped = True
            return value

        with mock.patch.object(reading_source, "from_complete_scan", side_effect=materialize):
            result = self.collect(cancelled=lambda: stopped)
        self.assertEqual("cancelled", result.reason)
        self.assertIsNone(result.evidence)

    def test_no_progress_stops_once_and_ancillary_work_never_rescans(self) -> None:
        self.module()
        with mock.patch.object(
            raw_source, "read", return_value=raw_source.Page("limited", "baseline")
        ) as read:
            result = self.collect()
        self.assertEqual("no_progress", result.reason)
        self.assertEqual(1, read.call_count)
        with (
            mock.patch.object(context, "_live_check_scan", side_effect=AssertionError("rescan")),
            mock.patch.object(context, "_session_directory", side_effect=AssertionError("head")),
            mock.patch.object(
                context, "_declared_scripts", side_effect=AssertionError("declarations")
            ),
            mock.patch.object(context, "_CiBinding", side_effect=AssertionError("live CI")),
        ):
            result = self.collect()
        self.assertIsNotNone(result.evidence)

    def test_deadline_is_checked_after_page_and_projection(self) -> None:
        self.module()
        now = 0.0
        original = raw_source.read

        def read(cursor: Any, **options: Any) -> Any:
            nonlocal now
            page = original(cursor, **options)
            now = 61.0
            return page

        with mock.patch.object(raw_source, "read", side_effect=read):
            result = self.collect(clock=lambda: now)
        self.assertEqual("time", result.reason)
        self.assertEqual(1, result.usage.source_pages)
        self.assertIsNone(result.evidence)
        now = 0.0
        original_project = reading_source.from_complete_scan

        def project(*args: Any, **kwargs: Any) -> Any:
            nonlocal now
            evidence = original_project(*args, **kwargs)
            now = 61.0
            return evidence

        with mock.patch.object(reading_source, "from_complete_scan", side_effect=project):
            result = self.collect(clock=lambda: now)
        self.assertEqual("time", result.reason)
        self.assertTrue(result.source_verified)
        self.assertIsNone(result.evidence)

    def test_verified_bytes_do_not_prove_named_missing_child(self) -> None:
        self.module()
        parent = Transcript(self.root)
        parent.prompt("Delegate the check.")
        call = parent.call(
            "Agent", {"prompt": "Check missing work", "subagent_type": "general-purpose"}
        )
        parent.result(call, "done", tool_use_result={"agentId": "deadbeef"})
        parent.save(self.path)
        result = self.collect()
        self.assertTrue(result.source_verified)
        self.assertEqual("native_incomplete", result.reason)
        self.assertIsNone(result.evidence)
