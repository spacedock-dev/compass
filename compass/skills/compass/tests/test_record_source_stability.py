"""Reading access metadata cannot invalidate unchanged transcript words."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import project_context, record_pages
from compass_runtime.state import build_runtime_state

from .support import make_config


class RecordSourceStabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "session.jsonl"
        self.config = make_config(home=str(self.root))
        self.row = {
            "type": "user",
            "timestamp": "2026-10-01T00:00:01Z",
            "message": {"role": "user", "content": "Build the synthetic fixture."},
        }
        self.raw = json.dumps(self.row).encode() + b"\n"
        event = project_context._instruction_event(self.config, self.row, "claude", "root")
        assert event is not None
        self.fact_id = project_context._semantic_fact_from_event(
            event, "steer", "user_message", ""
        )["fact_id"]

    def read(self, reader: str) -> tuple[str, list[str]]:
        if reader == "page":
            page = record_pages.read(
                self.config, str(self.path), "claude", "root", cursor_key=b"synthetic"
            )
            return page["state"], [entry["fact_id"] for entry in page["entries"]]
        coverage: dict[str, Any] = {}
        facts = project_context.transcript_user_facts(
            self.config,
            build_runtime_state(self.config, started=0),
            str(self.path),
            "claude",
            "root",
            goal_choices=True,
            coverage=coverage,
        )
        return coverage["state"], [fact["fact_id"] for fact in facts]

    def test_access_time_changes_preserve_prompt_and_page_facts(self) -> None:
        original = os.lstat
        for reader in ("prompts", "page"):
            self.path.write_bytes(self.raw)
            calls = 0

            def touched(path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
                nonlocal calls
                info = original(path, *args, **kwargs)
                if os.fspath(path) != str(self.path):
                    return info
                calls += 1
                # Model atime-only kernel updates even on filesystems mounted noatime.
                values = list(info)
                values[7] = info.st_atime + calls * 60
                return os.stat_result(
                    values,
                    {
                        "st_atime_ns": info.st_atime_ns + calls * 60_000_000_000,
                        "st_mtime_ns": info.st_mtime_ns,
                        "st_ctime_ns": info.st_ctime_ns,
                    },
                )

            with self.subTest(reader=reader), mock.patch.object(os, "lstat", side_effect=touched):
                self.assertEqual(("ok", [self.fact_id]), self.read(reader))
                self.assertGreaterEqual(calls, 2)

    def test_changed_sources_still_refuse_prompt_and_page_facts(self) -> None:
        original = record_pages._scan
        for reader in ("prompts", "page"):
            for change in ("append", "rewrite", "replace"):
                self.path.write_bytes(self.raw)

                def moving(*args: Any, change: str = change, **kwargs: Any) -> None:
                    original(*args, **kwargs)
                    if change == "append":
                        with self.path.open("ab") as handle:
                            handle.write(b"\n")
                    elif change == "rewrite":
                        stamp = self.path.stat()
                        self.path.write_bytes(self.raw.replace(b"Build", b"Check"))
                        os.utime(self.path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
                    else:
                        replacement = self.root / "replacement.jsonl"
                        replacement.write_bytes(self.raw)
                        replacement.replace(self.path)

                with (
                    self.subTest(reader=reader, change=change),
                    mock.patch.object(record_pages, "_scan", side_effect=moving),
                ):
                    state, facts = self.read(reader)
                    self.assertIn(state, ("stale", "unavailable"))
                    self.assertEqual([], facts)

    @unittest.skipIf(os.name == "nt", "POSIX symlink replacement")
    def test_swapped_leaf_links_still_refuse_prompt_and_page_facts(self) -> None:
        target = self.root / "target.jsonl"
        target.write_bytes(self.raw)
        original = record_pages._scan
        for reader in ("prompts", "page"):
            self.path.symlink_to(target)

            def swap(*args: Any, **kwargs: Any) -> None:
                original(*args, **kwargs)
                replacement = self.root / "replacement-link"
                replacement.symlink_to(target)
                replacement.replace(self.path)

            with (
                self.subTest(reader=reader),
                mock.patch.object(record_pages, "_scan", side_effect=swap),
            ):
                state, facts = self.read(reader)
                self.assertIn(state, ("stale", "unavailable"))
                self.assertEqual([], facts)
            self.path.unlink()
