"""Declaration acquisition stays inside a complete frozen native collection."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import ci_read, claude_data, project_scripts, reader_checks, reading_source
from compass_runtime import project_context as context
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory

from . import test_project_script_checks as scripts
from . import test_reading_source as source_tests
from .test_claude_checks import SHORT, Transcript


@unittest.skipIf(scripts.GIT is None, "git is not on PATH")
class CollectedDeclarationTest(unittest.TestCase):
    def setUp(self) -> None:
        source_tests.CompleteReadingSourceTest.setUp(self)
        project_scripts.reset()
        self.addCleanup(project_scripts.reset)
        self.project = self.root / "project"
        self.project.mkdir()
        scripts.git(self.project, "init", "-q")
        (self.project / "package.json").write_text(
            scripts.package(**{"check:custom": "tsc --noEmit"})
        )
        scripts.git(self.project, "add", "package.json")
        scripts.git(self.project, "commit", "-q", "-m", "synthetic declaration base")
        self.store = Path(reader_checks.store_path(self.config))
        self.store.parent.mkdir(exist_ok=True)
        self.store.write_text(json.dumps({"projects": {str(self.project): ["bazel test //..."]}}))
        self.parent = Transcript(self.project)
        self.parent.prompt("Verify the project and delegated changes.")
        self.custom = self.parent.bash("pnpm check:custom", "clean")
        self.listed = self.parent.bash("bazel test //...", "all tests passed")
        self.parent.save(self.path)
        self.config = replace(self.config, git_probe_enabled=True)

    def collect(self, **options: Any) -> Any:
        frozen = inventory.freeze(
            str(self.path), "claude", SHORT, max_entries=100, max_streams=10, max_seconds=1
        )
        return collector.collect(
            self.config, frozen, clock=options.pop("clock", lambda: 0.0), **options
        )

    def test_real_declarations_and_listing_match_oracle_without_source_rereads(self) -> None:
        scan = context._live_check_scan(self.config, str(self.path))
        expected = reading_source.from_complete_scan(self.config, scan, "claude", SHORT)
        project_scripts.reset()
        with (
            mock.patch.object(
                claude_data, "head_cwd", side_effect=AssertionError("head cwd reread")
            ),
            mock.patch.object(
                claude_data, "head_start", side_effect=AssertionError("head time reread")
            ),
            mock.patch.object(context, "_live_check_scan", side_effect=AssertionError("live scan")),
            mock.patch.object(ci_read, "scan_records", side_effect=AssertionError("CI reread")),
            mock.patch.object(ci_read, "folder_remote", side_effect=AssertionError("lazy remote")),
            mock.patch.object(project_scripts, "load", wraps=project_scripts.load) as project,
            mock.patch.object(
                reader_checks, "for_project", wraps=reader_checks.for_project
            ) as listed,
        ):
            result = self.collect(page_bytes=127)
        self.assertEqual("", result.reason)
        self.assertEqual(expected.facts, result.evidence.facts)
        self.assertEqual(expected.press, result.evidence.press)
        self.assertEqual(1, project.call_count)
        self.assertEqual(1, listed.call_count)
        self.assertEqual(str(self.project), project.call_args.args[0])
        self.assertEqual(context._oldest_at(self.parent.rows), project.call_args.args[1])
        for call in (self.custom, self.listed):
            fact = next(
                f for f in result.evidence.facts if f.get("branch", {}).get("record_id") == call
            )
            self.assertEqual(("check", "passed"), (fact["subject"], fact["result"]))
        self.assertEqual("acquired", result.ancillary_info.origin)
        self.assertEqual("available", result.ancillary_info.project_scripts)
        self.assertEqual(
            "available" if self.config.git_probe_enabled else "disabled",
            result.ancillary_info.ci_binding,
        )
        self.assertEqual(
            (1, 1), (result.ancillary_info.project_loads, result.ancillary_info.reader_loads)
        )
        self.assertEqual(
            3 * (self.path.stat().st_size + self.child_path.stat().st_size),
            result.usage.source_bytes,
        )

    def test_whole_corpus_withdraws_child_written_and_reader_listed_declarations(self) -> None:
        child = Transcript(self.project)
        child.calls, child.seconds = 200, 100
        child.write(str(self.project / "package.json"))
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.child_path)
        self.parent.write(str(self.store))
        self.parent.save(self.path)
        result = self.collect(page_bytes=127)
        self.assertEqual("", result.reason)
        for call in (self.custom, self.listed):
            fact = next(
                f for f in result.evidence.facts if f.get("branch", {}).get("record_id") == call
            )
            self.assertEqual("command", fact["subject"])
            self.assertFalse(fact.get("listed_by_reader", False))
        # The physical declaration files never changed; native recorded writes withdraw them.
        self.assertTrue(self.store.exists())
        self.assertEqual(
            "tsc --noEmit",
            json.loads((self.project / "package.json").read_text())["scripts"]["check:custom"],
        )

    def test_no_git_and_unavailable_project_metadata_never_claim_custom_check(self) -> None:
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                self.config = replace(self.config, git_probe_enabled=enabled)
                with mock.patch.object(project_scripts, "load", return_value=None) as load:
                    result = self.collect()
                self.assertEqual("", result.reason)
                self.assertEqual(int(enabled), load.call_count)
                custom = next(
                    f
                    for f in result.evidence.facts
                    if f.get("branch", {}).get("record_id") == self.custom
                )
                listed = next(
                    f
                    for f in result.evidence.facts
                    if f.get("branch", {}).get("record_id") == self.listed
                )
                self.assertEqual("command", custom["subject"])
                self.assertEqual("check", listed["subject"])
                self.assertEqual(
                    "unavailable" if enabled else "disabled", result.ancillary_info.project_scripts
                )
                self.assertEqual(
                    "available" if self.config.git_probe_enabled else "disabled",
                    result.ancillary_info.ci_binding,
                )

    def test_full_git_timeout_must_fit_before_acquisition(self) -> None:
        with mock.patch.object(
            project_scripts, "load", side_effect=AssertionError("unreserved probe")
        ):
            result = self.collect(limits=replace(collector.Limits(), prepare_ms=4999))
        self.assertEqual("time", result.reason)
        self.assertTrue(result.source_verified)
        self.assertIsNone(result.evidence)
        self.assertEqual(0, result.ancillary_info.project_loads)

    def test_cancel_and_deadline_after_loading_withhold_projection(self) -> None:
        for stop in ("cancelled", "time"):
            with self.subTest(stop=stop):
                self.assert_load_stopped(stop)

    def assert_load_stopped(self, stop: str) -> None:
        now = 0.0
        cancelled = False
        load = project_scripts.load

        def acquired(*args: Any, **options: Any) -> Any:
            nonlocal now, cancelled
            value = load(*args, **options)
            now = 61.0 if stop == "time" else 0.0
            cancelled = stop == "cancelled"
            return value

        with mock.patch.object(project_scripts, "load", side_effect=acquired):
            result = self.collect(clock=lambda: now, cancelled=lambda: cancelled)
        self.assertEqual(stop, result.reason)
        self.assertIsNone(result.evidence)
        self.assertEqual(1, result.ancillary_info.project_loads)
        self.assertEqual(0, result.ancillary_info.reader_loads)

    def test_loaded_declaration_graph_must_fit_before_listing_or_projection(self) -> None:
        package = {
            f"verify{number}": "tsc --noEmit" for number in range(project_scripts.MAX_SCRIPTS)
        }
        (self.project / "package.json").write_text(scripts.package(**package))
        scripts.git(self.project, "add", "package.json")
        scripts.git(self.project, "commit", "-q", "-m", "synthetic bounded declaration set")
        with (
            mock.patch.object(project_scripts, "load", wraps=project_scripts.load) as load,
            mock.patch.object(
                reader_checks, "for_project", side_effect=AssertionError("unadmitted metadata")
            ),
        ):
            result = self.collect(limits=replace(collector.Limits(), retained_units=1200))
        self.assertTrue(load.called)
        self.assertEqual("retained_units", result.reason)
        self.assertIsNone(result.evidence)
        self.assertLessEqual(result.usage.retained_units, 1200)
