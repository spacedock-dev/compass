"""Session mode from the measured Claude entrypoints, never from a missing value.

Shapes: docs/captures/claude/headless-command-shapes-2.1.319-macos.jsonl and
docs/captures/claude/scheduled-command-shapes-2.1.319-macos.jsonl.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import claude_data
from compass_runtime import sessions as runtime_sessions

from .fixtures import _iso, _jsonl
from .support import HarnessContractTestCase, make_runtime


def prompt(entrypoint: Any = None, **extra: Any) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": _iso(1_700_000_000.0),
        "message": {"role": "user", "content": "Check the placeholder build."},
        **({"entrypoint": entrypoint} if entrypoint is not None else {}),
        **extra,
    }


class ASessionPublishesItsOwnEntrypointTest(HarnessContractTestCase):
    def test_the_row_distinguishes_headless_interactive_and_unknown(self) -> None:
        for entrypoint, expected in (("sdk-cli", True), ("cli", False), (None, None)):
            with self.subTest(entrypoint=entrypoint):

                def build(
                    root: Path, when: float, sid: str, _title: str, mode: Any = entrypoint
                ) -> dict[str, str]:
                    projects = root / "projects"
                    _jsonl(projects / "-w-proj" / f"{sid}.jsonl", [prompt(mode)], when)
                    _jsonl(
                        projects / "-w-proj" / sid / "subagents" / "agent-child.jsonl",
                        [prompt("sdk-cli", isSidechain=True)],
                        when,
                    )
                    return {"PROJECTS_DIR": str(projects), "TASKS_DIR": str(root / "tasks")}

                (row,) = self.sessions_for(self.collect(build, when=self.NOW), "claude")
                self.assertIs(row.get("headless"), expected)

    def test_an_unread_or_other_harness_row_has_no_measured_mode(self) -> None:
        for harness in ("claude", "codex", "gemini", "pi"):
            with self.subTest(harness=harness):
                row = runtime_sessions.base_session(harness, "s", "p")
                self.assertIn("headless", row)
                self.assertIsNone(row["headless"])


class TheIncrementalReadKeepsOnlyMeasuredEntrypointsTest(unittest.TestCase):
    def test_append_partial_lines_and_replacement_update_the_same_read(self) -> None:
        config, state = make_runtime()
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "session.jsonl")
            _jsonl(path, [prompt()], 1_700_000_000.0)

            def read() -> bool | None:
                claude_data.session_goal(config, state, str(path))
                return claude_data.session_entrypoint(state, str(path)).published()["headless"]

            self.assertIsNone(read())
            with path.open("a") as source:
                source.write(json.dumps(prompt("sdk-cli")))
            self.assertIsNone(read())
            with path.open("a") as source:
                source.write("\n")
            self.assertIs(read(), True)
            with mock.patch("builtins.open", side_effect=AssertionError("unchanged file reread")):
                self.assertIs(read(), True)
            with path.open("a") as source:
                source.write(json.dumps(prompt("cli")) + "\n")
            self.assertIs(read(), False)
            with path.open("a") as source:
                source.write(json.dumps(prompt("sdk-cli", isSidechain=True)) + "\n")
            self.assertIs(read(), False)
            with path.open("a") as source:
                source.write(json.dumps(prompt("future-entrypoint")) + "\n")
            self.assertIsNone(read())
            with path.open("a") as source:
                source.write(json.dumps(prompt("sdk-cli")) + "\n")
            self.assertIs(read(), True)
            replacement = Path(home, "replacement.jsonl")
            _jsonl(replacement, [prompt()], 1_700_000_000.0)
            replacement.replace(path)
            self.assertIsNone(read())

    def test_unmeasured_and_sidechain_entrypoints_do_not_claim_interactive(self) -> None:
        for record in (
            prompt("future-entrypoint"),
            prompt(["cli"]),
            prompt("sdk-cli", isSidechain=True),
            prompt("cli", isSidechain=True),
        ):
            with self.subTest(record=record), tempfile.TemporaryDirectory() as home:
                config, state = make_runtime()
                path = Path(home, "session.jsonl")
                _jsonl(path, [record], 1_700_000_000.0)
                claude_data.session_goal(config, state, str(path))
                self.assertIsNone(
                    claude_data.session_entrypoint(state, str(path)).published()["headless"]
                )

    def test_a_cold_read_that_misses_the_entrypoint_stays_unknown(self) -> None:
        config, state = make_runtime(turn_scan_max_bytes=300)
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "session.jsonl")
            _jsonl(path, [prompt("sdk-cli"), *([prompt()] * 20)], 1_700_000_000.0)
            claude_data.session_goal(config, state, str(path))
            self.assertIsNone(
                claude_data.session_entrypoint(state, str(path)).published()["headless"]
            )
