"""Session mode from the measured Claude entrypoints, never from a missing value.

Shapes: docs/captures/claude/headless-command-shapes-2.1.319-macos.jsonl and
docs/captures/claude/scheduled-command-shapes-2.1.319-macos.jsonl.
"""

from __future__ import annotations

import json
import os
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
        "sessionId": "session",
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
                    _jsonl(
                        projects / "-w-proj" / f"{sid}.jsonl",
                        [prompt(mode, sessionId=sid)],
                        when,
                    )
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
    def test_copied_records_cannot_decide_the_native_sessions_mode(self) -> None:
        for native, copied, expected in (("cli", "sdk-cli", False), ("sdk-cli", "cli", True)):
            with self.subTest(native=native), tempfile.TemporaryDirectory() as home:
                config, state = make_runtime()
                path = Path(home, "session.jsonl")
                _jsonl(
                    path,
                    [prompt(copied, sessionId="copied"), prompt(native)],
                    1_700_000_000.0,
                )
                claude_data.session_goal(config, state, str(path))
                with path.open("a") as source:
                    source.write(json.dumps(prompt(copied, sessionId="copied")) + "\n")
                claude_data.session_goal(config, state, str(path))
                self.assertIs(claude_data.session_entrypoint(state, str(path)).headless, expected)
                # The cold reader must also skip a newer copied record.
                _, fresh = make_runtime()
                claude_data.session_goal(config, fresh, str(path))
                self.assertIs(claude_data.session_entrypoint(fresh, str(path)).headless, expected)

    def test_an_equal_length_in_place_rewrite_replaces_the_cached_mode(self) -> None:
        for unfinished in ("", '{"type":'):
            with self.subTest(unfinished=unfinished), tempfile.TemporaryDirectory() as home:
                config, state = make_runtime()
                path = Path(home, "session.jsonl")
                before = json.dumps(prompt("sdk-cli")) + "\n" + unfinished
                after = json.dumps(prompt("cli")) + "    \n" + unfinished
                self.assertEqual(len(before), len(after))
                path.write_text(before)
                claude_data.session_goal(config, state, str(path))
                self.assertIs(claude_data.session_entrypoint(state, str(path)).headless, True)
                stat = path.stat()
                path.write_text(after)
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
                self.assertEqual(path.stat().st_ino, stat.st_ino)
                claude_data.session_goal(config, state, str(path))
                self.assertIs(claude_data.session_entrypoint(state, str(path)).headless, False)

    def test_a_failed_stat_or_open_withholds_the_previous_mode(self) -> None:
        for failure in ("stat", "append-open", "replacement-open"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as home:
                config, state = make_runtime()
                path = Path(home, "session.jsonl")
                _jsonl(path, [prompt("sdk-cli")], 1_700_000_000.0)
                claude_data.session_goal(config, state, str(path))
                self.assertIs(claude_data.session_entrypoint(state, str(path)).headless, True)
                if failure == "append-open":
                    with path.open("a") as source:
                        source.write(json.dumps(prompt("cli")) + "\n")
                elif failure == "replacement-open":
                    replacement = Path(home, "replacement.jsonl")
                    _jsonl(replacement, [prompt("cli")], 1_700_000_001.0)
                    replacement.replace(path)
                target = (
                    "compass_runtime.claude_data.os.stat" if failure == "stat" else "builtins.open"
                )
                with mock.patch(target, side_effect=PermissionError("cannot read transcript")):
                    self.assertIsNone(claude_data.session_goal(config, state, str(path)))
                self.assertIsNone(claude_data.session_entrypoint(state, str(path)).headless)
                claude_data.session_goal(config, state, str(path))
                self.assertIs(
                    claude_data.session_entrypoint(state, str(path)).headless, failure == "stat"
                )

    def test_the_bounded_scan_decodes_only_the_newest_native_entrypoint(self) -> None:
        config, state = make_runtime(turn_scan_max_bytes=8192)
        with tempfile.TemporaryDirectory() as home:
            path = Path(home, "session.jsonl")
            _jsonl(
                path,
                [
                    *([prompt("sdk-cli")] * 200),
                    prompt("cli"),
                    prompt("sdk-cli", sessionId="copied"),
                    prompt("sdk-cli", isSidechain=True),
                ],
                1_700_000_000.0,
            )
            with mock.patch("compass_runtime.claude_data.json.loads", wraps=json.loads) as decodes:
                claude_data.session_goal(config, state, str(path))
            self.assertIs(claude_data.session_entrypoint(state, str(path)).headless, False)
            self.assertEqual(decodes.call_count, 2)

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
            prompt("sdk-cli", sessionId=None),
            prompt("sdk-cli", sessionId="copied", note="session"),
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
