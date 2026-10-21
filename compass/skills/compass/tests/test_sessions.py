from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from compass_runtime import aggregate, observer, reading, records
from compass_runtime import annotations as annotation_store
from compass_runtime import events as runtime_events
from compass_runtime import sessions as runtime_sessions
from compass_runtime import turns as runtime_turns
from compass_runtime.collectors import claude as claude_collector

from .fixtures import HARNESSES
from .support import (
    STORE_OVERRIDES,
    HarnessContractTestCase,
    RuntimeTestCase,
    collect,
    collect_claude,
    config_patch,
    make_config,
    make_runtime,
    store_patch,
)
from .support import runtime as support_runtime

# The payload's declared field set, written out here rather than derived from
# base_session(), so the two sides cannot move together. Comparing a function
# against the table it reads from holds no matter how wrong the table is.
#
# Module level rather than a class attribute because two tests read it: the
# constructor's key set, and a published payload row's. One table, or the weaker
# of the two checks becomes the one a new field gets declared against.
DECLARED_SESSION_FIELDS = frozenset(
    {
        "session",
        "summary",
        "sid",
        "harness",
        "project",
        "project_key",
        "project_name",
        "project_identity_source",
        "worktree",
        "provider",
        "model",
        "consumption",
        "title",
        "last_prompt",
        "prompt_states_work",
        "prompt_at",
        "first_prompt",
        "first_prompt_at",
        "first_prompt_control",
        "last_output",
        "instruction",
        "state",
        "state_detail",
        "active",
        "last_activity",
        "own_activity",
        "work_activity",
        "started_at",
        "finished_at",
        "turn_end_at",
        "delegated_launches",
        "delegated_unpaired",
        "delegated_latest_launch_at",
        "delegated_last_activity_at",
        "delegated_quiet_since",
        "delegated_visibility",
        "ended_at",
        "dirty",
        "changed",
        "focusable",
        "command_reports",
        "rate_per_min",
        "session_output_tokens",
        "turn_output_tokens",
        "total",
        "done",
        "open",
        "progress_pct",
        "eta_h",
        "turn",
        "loop",
        "resume_id",
        "subagents",
        "subagents_omitted",
        "subagent_hierarchy",
        "subagent_events",
        "tasks",
        "spacedock",
        "cached_deterministic_goal",
        "source_gaps",
        # The two below are written onto the row after `base_session` returns,
        # which is why they went undeclared until the check reached the payload
        # (DRC-4473). `acquisition` is stamped by
        # `Application._mark_unreachable_by_events` for the six harnesses absent
        # from `events.IDENTITY_NORMALIZERS`; `blocked_since` is published by the
        # Claude, Copilot and Cursor collectors. Both are also in
        # `events.PATCHABLE`, so an event envelope can write either onto any row.
        "acquisition",
        "blocked_since",
        "wait_unconfirmed",
        # Same provenance as the two above: written onto every row by
        # `Application._attach_annotations` after `base_session` returns. Every
        # row and not only the annotated ones, because a missing key renders as
        # `undefined` where an absence has to state its reason. Fifteen flat
        # fields and not one mapping, because `history.PROMPT_TEXT_ALLOWLIST`
        # admits field names and a name cannot reach inside a dict.
        "annotation_goal",
        "annotation_goal_why",
        "annotation_lines_why",
        "annotation_line_1",
        "annotation_line_1_source",
        "annotation_line_1_source_id",
        "annotation_line_2",
        "annotation_line_2_source",
        "annotation_line_2_source_id",
        "annotation_line_3",
        "annotation_line_3_source",
        "annotation_line_3_source_id",
        "annotation_line_4",
        "annotation_line_4_source",
        "annotation_line_4_source_id",
        "annotation_line_5",
        "annotation_line_5_source",
        "annotation_line_5_source_id",
        "annotation_line_6",
        "annotation_line_6_source",
        "annotation_line_6_source_id",
        "annotation_revision",
        "annotation_revision_count",
        "annotation_at",
        "annotation_goal_source",
        "annotation_goal_source_at",
        "annotation_goal_saved_at",
        "annotation_window_start",
        "annotation_binding_why",
        "annotation_discarded_at",
        "annotation_discarded_why",
        "annotation_settled_at",
        "annotation_settled_through",
        "annotation_settled_revision",
        "annotation_assessment",
        "annotation_reading_count",
        "annotation_reading_withheld",
        "annotation_reading_withheld_at",
        "reading_eligibility",
        "annotation_reading_refused",
        "annotation_not_accurate",
        "copied_prompts",
        "delivery_outcome",
        "delivery_why",
        "delivery_none_why",
        "delivery_at",
        "delivery_raises",
        "delivery_mixed",
        "delivery_mixed_why",
        "delivery_binding_why",
        "delivery_departure",
        "browser_lane",
        "browser_lane_at",
        "browser_lane_why",
        "departures",
        "departure_why",
        "departure_checked",
    }
)


class CompassServerTest(RuntimeTestCase):
    def test_two_worktrees_of_one_repository_file_under_one_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "one" / "compass"
            (main / ".git").mkdir(parents=True)
            trees = {}
            for name in ("haiku-a", "haiku-b"):
                tree = main / ".claude" / "worktrees" / name
                gitdir = main / ".git" / "worktrees" / name
                gitdir.mkdir(parents=True)
                (tree / "src").mkdir(parents=True)
                tree.joinpath(".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
                (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
                trees[name] = tree
            config = make_config()

            def filed(cwd: Path) -> dict[str, Any]:
                row = runtime_sessions.base_session(
                    "claude", "s", runtime_sessions.project_from_cwd(config, str(cwd))
                )
                runtime_sessions.apply_project_identity(config, row, str(cwd))
                return dict(row)

            a, b = filed(trees["haiku-a"] / "src"), filed(trees["haiku-b"])
            top = filed(main)

        self.assertEqual("one/compass", a["project"])
        self.assertEqual(a["project"], b["project"])
        self.assertEqual(a["project"], top["project"])
        self.assertEqual(a["project_key"], b["project_key"])
        self.assertEqual("haiku-a", a["worktree"])
        self.assertEqual("haiku-b", b["worktree"])
        self.assertIsNone(top["worktree"])

    def test_git_identity_collapses_main_and_worktree_without_basename_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            main = root / "one" / "compass"
            worktree = root / "worktrees" / "feature"
            unrelated = root / "two" / "compass"
            (main / ".git" / "worktrees" / "feature").mkdir(parents=True)
            (worktree / "src").mkdir(parents=True)
            unrelated.joinpath(".git").mkdir(parents=True)
            worktree.joinpath(".git").write_text(
                f"gitdir: {main / '.git' / 'worktrees' / 'feature'}\n",
                encoding="utf-8",
            )
            (main / ".git" / "worktrees" / "feature" / "commondir").write_text(
                "../..\n", encoding="utf-8"
            )
            config = make_config()

            main_identity = runtime_sessions.project_identity(config, str(main))
            worktree_identity = runtime_sessions.project_identity(config, str(worktree / "src"))
            unrelated_identity = runtime_sessions.project_identity(config, str(unrelated))

        self.assertEqual(main_identity, worktree_identity)
        self.assertEqual("compass", main_identity["name"])
        self.assertNotEqual(main_identity["key"], unrelated_identity["key"])
        self.assertEqual("compass", unrelated_identity["name"])

    def test_large_transcript_recovers_turn_start_before_bounded_tail(self) -> None:
        prompt_time = "2026-01-01T00:00:00Z"
        prompt = {
            "type": "user",
            "timestamp": prompt_time,
            "message": {"content": "long request"},
        }
        events = [
            {
                "type": "assistant",
                "timestamp": f"2026-01-01T00:00:{second:02d}Z",
                "message": {"content": "x" * 40},
            }
            for second in range(1, 20)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in [prompt, *events]) + "\n")
            config, state = make_runtime(turn_scan_max_bytes=200)
            turns = runtime_turns.scan_turns(config, state, str(path), "claude")

        assert turns is not None
        self.assertEqual(records.parse_ts(prompt_time), turns["turn_start"])

    def test_large_append_recovers_new_turn_start_from_skipped_delta(self) -> None:
        first_time = "2026-01-01T00:00:00Z"
        second_time = "2026-01-01T00:01:00Z"
        first_prompt = {
            "type": "user",
            "timestamp": first_time,
            "message": {"content": "first"},
        }
        second_prompt = {
            "type": "user",
            "timestamp": second_time,
            "message": {"content": "second"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "growing.jsonl"
            path.write_text(json.dumps(first_prompt) + "\n")
            # Both scan calls share one runtime: the scanner is incremental, so
            # the second must see the state the first recorded.
            config, state = make_runtime(turn_scan_max_bytes=200)
            runtime_turns.scan_turns(config, state, str(path), "claude")
            with path.open("a") as output:
                output.write(json.dumps(second_prompt) + "\n")
                for second in range(1, 20):
                    output.write(
                        json.dumps(
                            {
                                "type": "assistant",
                                "timestamp": (f"2026-01-01T00:01:{second:02d}Z"),
                                "message": {"content": "x" * 40},
                            }
                        )
                        + "\n"
                    )
            turns = runtime_turns.scan_turns(config, state, str(path), "claude")

        assert turns is not None
        self.assertEqual(records.parse_ts(second_time), turns["turn_start"])

    # One turn's worth of a tight failure loop: a prompt, then `count` tool
    # calls each answered by a failing result. The shape is the measured one —
    # `is_error` rides the `tool_result` block, and the tool name is only ever on
    # the `tool_use` block whose id the result points back to.
    @staticmethod
    def _loop_transcript(count: int, *, tool: str = "Bash", minute: int = 0) -> list[Any]:
        out: list[Any] = [
            {
                "type": "user",
                "timestamp": f"2026-01-01T00:{minute:02d}:00Z",
                "message": {"content": "fix the thing"},
            }
        ]
        for i in range(count):
            out.append(
                {
                    "type": "assistant",
                    "timestamp": f"2026-01-01T00:{minute:02d}:{i * 2 + 1:02d}Z",
                    "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": tool}]},
                }
            )
            out.append(
                {
                    "type": "user",
                    "timestamp": f"2026-01-01T00:{minute:02d}:{i * 2 + 2:02d}Z",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": f"t{i}", "is_error": True}
                        ]
                    },
                }
            )
        return out

    @staticmethod
    def _mixed_transcript(pattern: str, *, tool: str = "Bash", minute: int = 0) -> list[Any]:
        """One turn whose tool calls succeed or fail in the order `pattern` gives.

        `f` is a failed call, `o` a successful one. `_loop_transcript` can only
        build a run, and every case C2 exists for needs a success partway through.
        """
        out: list[Any] = [
            {
                "type": "user",
                "timestamp": f"2026-01-01T00:{minute:02d}:00Z",
                "message": {"content": "fix the thing"},
            }
        ]
        for i, outcome in enumerate(pattern):
            out.append(
                {
                    "type": "assistant",
                    "timestamp": f"2026-01-01T00:{minute:02d}:{i * 2 + 1:02d}Z",
                    "message": {"content": [{"type": "tool_use", "id": f"t{i}", "name": tool}]},
                }
            )
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": f"t{i}"}
            if outcome == "f":
                result["is_error"] = True
            out.append(
                {
                    "type": "user",
                    "timestamp": f"2026-01-01T00:{minute:02d}:{i * 2 + 2:02d}Z",
                    "message": {"content": [result]},
                }
            )
        return out

    @staticmethod
    def _scan(written: list[Any], path: Path, **overrides: Any) -> dict[str, Any]:
        path.write_text("\n".join(json.dumps(record) for record in written) + "\n")
        config, state = make_runtime(**overrides)
        scan = runtime_turns.scan_turns(config, state, str(path), "claude")
        assert scan is not None
        return scan

    def test_a_run_of_failing_tool_results_is_counted_and_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(self._loop_transcript(4), Path(tmp) / "loop.jsonl")
        self.assertEqual(4, scan["err_peak"])
        self.assertEqual("Bash", scan["err_tool"])

    def test_a_successful_call_breaks_the_run_but_not_the_peak(self) -> None:
        # Two facts in one test because they are one decision: "consecutive"
        # means the live run resets on any success, and what the turn publishes
        # is the peak, which does not — a loop that has just stopped failing is
        # exactly when the reader walks back to the machine.
        written = self._loop_transcript(4)
        written.append(
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:20Z",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "t3", "is_error": False}]
                },
            }
        )
        written.extend(self._loop_transcript(1)[1:])
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "loop.jsonl")
        self.assertEqual(1, scan["err_run"])
        self.assertEqual(4, scan["err_peak"])

    def test_the_next_prompt_clears_the_loop_signal(self) -> None:
        written = self._loop_transcript(4) + self._loop_transcript(1, minute=1)
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "loop.jsonl")
        self.assertEqual(1, scan["err_peak"])

    def test_the_loop_threshold_is_what_decides_the_signal(self) -> None:
        # The threshold IS the product: at 3 and at 4 the detector fired in the
        # same 1 of 25 local transcripts, so the extra rung costs no yield and
        # buys distance from the benign runs the sample was full of. A run one
        # short of it publishes nothing at all, not a smaller signal.
        # Both fixtures bracket the run with a success on purpose. Three
        # failures and nothing else is a barren turn under its own threshold,
        # which would answer this test with the wrong signal; a success at each
        # end isolates the run rung, which is what this test is about.
        config, _ = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            short = self._scan(self._mixed_transcript("offfo"), Path(tmp) / "short.jsonl")
            long_enough = self._scan(self._mixed_transcript("offffo"), Path(tmp) / "long.jsonl")
        self.assertEqual(4, config.loop_error_run_threshold)
        self.assertEqual(3, short["err_peak"])
        self.assertIsNone(runtime_turns.loop_signal(short, config))
        self.assertEqual(
            {"errors": 4, "failures": 4, "barren": False, "tool": "Bash"},
            runtime_turns.loop_signal(long_enough, config),
        )
        self.assertIsNone(runtime_turns.loop_signal(None, config))

    def test_the_failure_total_counts_across_a_success_the_run_forgets(self) -> None:
        # The whole of C2 in one scan: three failures, a success, three more.
        # `err_run` resets on the success and `err_peak` therefore tops out at
        # three, so the turn reads as cleaner than it was. The total does not
        # reset, because six calls failed however they were spaced.
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(self._mixed_transcript("fffoff" + "f"), Path(tmp) / "loop.jsonl")
        self.assertEqual(3, scan["err_peak"])
        self.assertEqual(6, scan["err_total"])
        self.assertEqual(1, scan["ok_total"])

    def test_the_failure_total_raises_a_signal_the_run_of_four_misses(self) -> None:
        # The case the issue was filed for. The peak never reaches four, so
        # today this turn publishes nothing at all.
        config, _ = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(self._mixed_transcript("fffofff"), Path(tmp) / "loop.jsonl")
        self.assertEqual(6, config.loop_error_total_threshold)
        self.assertLess(scan["err_peak"], config.loop_error_run_threshold)
        signal = runtime_turns.loop_signal(scan, config)
        assert signal is not None
        self.assertEqual(3, signal["errors"])
        self.assertEqual(6, signal["failures"])
        self.assertFalse(signal["barren"])

    def test_six_failures_among_many_successes_is_a_healthy_turn_and_stays_quiet(self) -> None:
        # Measured, not reasoned. Replaying 60 real Claude transcripts, three
        # reached six scattered failures on turns that were plainly healthy: the
        # worst was 7 failures among 198 successes with a longest run of 2. The
        # count alone would call that stuck and rank it above a real loop, so the
        # failures must also outnumber the successes.
        config, _ = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(
                self._mixed_transcript("fo" * 6 + "o" * 8), Path(tmp) / "healthy.jsonl"
            )
        self.assertEqual(6, scan["err_total"])
        self.assertEqual(14, scan["ok_total"])
        self.assertGreaterEqual(scan["err_total"], config.loop_error_total_threshold)
        self.assertIsNone(runtime_turns.loop_signal(scan, config))

        # The same six failures, with the successes that made them ordinary
        # removed, is the turn this rung exists to catch.
        with tempfile.TemporaryDirectory() as tmp:
            stuck = self._scan(self._mixed_transcript("fffofff"), Path(tmp) / "stuck.jsonl")
        self.assertEqual(6, stuck["err_total"])
        self.assertEqual(1, stuck["ok_total"])
        signal = runtime_turns.loop_signal(stuck, config)
        assert signal is not None
        self.assertEqual(6, signal["failures"])

    def test_scattered_failures_under_the_total_threshold_stay_quiet(self) -> None:
        # The false positive the higher threshold buys. Four failures spread
        # through a productive turn is not a loop, and the peak-run design was
        # right to ignore it; reusing the run threshold for the total would
        # have fired here.
        config, _ = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(self._mixed_transcript("fofofofooo"), Path(tmp) / "loop.jsonl")
        self.assertEqual(1, scan["err_peak"])
        self.assertEqual(4, scan["err_total"])
        self.assertIsNone(runtime_turns.loop_signal(scan, config))

    def test_a_turn_where_no_tool_call_succeeded_is_flagged_barren(self) -> None:
        # Three failures and nothing working, below both other thresholds. The
        # reader's question is not how long the run is, it is whether anything
        # in this turn has worked at all.
        config, _ = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(self._mixed_transcript("fff"), Path(tmp) / "loop.jsonl")
        self.assertEqual(3, config.loop_barren_failure_threshold)
        self.assertEqual(0, scan["ok_total"])
        signal = runtime_turns.loop_signal(scan, config)
        assert signal is not None
        self.assertTrue(signal["barren"])
        self.assertEqual(3, signal["failures"])

    def test_one_success_is_enough_to_clear_barren(self) -> None:
        # A single success is the whole difference between "nothing works" and
        # "some things work", and it must not need to be the last call.
        config, _ = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(self._mixed_transcript("fof"), Path(tmp) / "loop.jsonl")
        self.assertEqual(1, scan["ok_total"])
        self.assertIsNone(runtime_turns.loop_signal(scan, config))

    def test_two_failures_and_nothing_else_are_too_early_to_call_barren(self) -> None:
        # A turn is barren for a moment at its start, every time. The floor is
        # what stops the signal firing on the second call of a healthy turn.
        config, _ = make_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(self._mixed_transcript("ff"), Path(tmp) / "loop.jsonl")
        self.assertEqual(0, scan["ok_total"])
        self.assertIsNone(runtime_turns.loop_signal(scan, config))

    def test_the_next_prompt_clears_the_failure_total_and_the_success_count(self) -> None:
        # Both new counters are turn state, like the run and the peak beside
        # them. A fresh prompt starts a fresh turn with nothing carried over.
        written = self._mixed_transcript("fffofff") + self._mixed_transcript("fo", minute=1)
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "loop.jsonl")
        self.assertEqual(1, scan["err_total"])
        self.assertEqual(1, scan["ok_total"])

    def test_a_quiet_gap_inside_a_turn_does_not_make_it_look_barren(self) -> None:
        # A permission wait is exactly what the gap re-anchor exists for, and it
        # is not a new request. Zeroing the success count there let five
        # successes, a six-minute pause and three failures publish "none
        # succeeded" about a request in which five calls had worked.
        config, _ = make_runtime()
        written: list[Any] = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the thing"},
            }
        ]
        for i in range(5):
            written.append(
                {
                    "type": "assistant",
                    "timestamp": f"2026-01-01T00:00:{i * 2 + 1:02d}Z",
                    "message": {"content": [{"type": "tool_use", "id": f"a{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": f"2026-01-01T00:00:{i * 2 + 2:02d}Z",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": f"a{i}"}]},
                }
            )
        for i in range(3):
            written.append(
                {
                    "type": "assistant",
                    "timestamp": f"2026-01-01T00:{7 + i:02d}:00Z",
                    "message": {"content": [{"type": "tool_use", "id": f"b{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": f"2026-01-01T00:{7 + i:02d}:30Z",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": f"b{i}", "is_error": True}
                        ]
                    },
                }
            )
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "gap.jsonl")
        # The run and its peak still go with the gap, which is the documented
        # and correct half: failures either side of six minutes of silence are
        # not one tight loop.
        self.assertEqual(3, scan["err_peak"])
        # The totals do not, because they describe the request.
        self.assertEqual(5, scan["ok_total"])
        self.assertEqual(3, scan["err_total"])
        self.assertIsNone(runtime_turns.loop_signal(scan, config))

    def test_a_turn_the_scan_never_saw_open_publishes_no_total_and_no_barren(self) -> None:
        # The bounded tail cannot see the successes before it, so a request with
        # twenty successful calls and three failures at the end read as a request
        # where nothing had worked. `turn_complete` is the flag the module
        # already uses to withhold the turn token count off this same state.
        written: list[Any] = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the thing"},
            }
        ]
        for i in range(20):
            written.append(
                {
                    "type": "assistant",
                    "timestamp": f"2026-01-01T00:{i // 30:02d}:{i % 30 + 1:02d}Z",
                    "message": {"content": [{"type": "tool_use", "id": f"a{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": f"2026-01-01T00:{i // 30:02d}:{i % 30 + 1:02d}Z",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": f"a{i}"}]},
                }
            )
        for i in range(3):
            written.append(
                {
                    "type": "assistant",
                    "timestamp": f"2026-01-01T00:01:{i * 2 + 1:02d}Z",
                    "message": {"content": [{"type": "tool_use", "id": f"b{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": f"2026-01-01T00:01:{i * 2 + 2:02d}Z",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": f"b{i}", "is_error": True}
                        ]
                    },
                }
            )
        config, _ = make_runtime(turn_scan_max_bytes=900)
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "tail.jsonl", turn_scan_max_bytes=900)
        self.assertFalse(scan["turn_complete"])
        self.assertEqual(0, scan["ok_total"])
        # Nothing at all is published. The peak run is 3, one short of its own
        # threshold, and the two request-wide readings are withheld, so the
        # honest answer to "is this turn stuck" is silence rather than a claim
        # built on the successes the scan could not see.
        self.assertEqual(3, scan["err_peak"])
        self.assertIsNone(runtime_turns.loop_signal(scan, config))

        # And once the request is fully in view the same counts do speak.
        whole = self._scan(written, Path(tempfile.mkdtemp()) / "whole.jsonl")
        self.assertTrue(whole["turn_complete"])
        self.assertEqual(20, whole["ok_total"])
        self.assertIsNone(runtime_turns.loop_signal(whole, config))

    def test_an_incomplete_turn_that_does_fire_still_withholds_both_totals(self) -> None:
        # The run reaches its threshold inside the bytes read, so a signal is
        # published. It must carry the run alone: the request-wide readings are
        # still unknowable, and a partial total presented as the turn's total is
        # a false number rather than a quiet one.
        written: list[Any] = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the thing"},
            }
        ]
        for i in range(20):
            written.append(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {"content": [{"type": "tool_use", "id": f"a{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": "2026-01-01T00:00:02Z",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": f"a{i}"}]},
                }
            )
        for i in range(7):
            written.append(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:01:01Z",
                    "message": {"content": [{"type": "tool_use", "id": f"b{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": "2026-01-01T00:01:02Z",
                    "message": {
                        "content": [
                            {"type": "tool_result", "tool_use_id": f"b{i}", "is_error": True}
                        ]
                    },
                }
            )
        config, _ = make_runtime(turn_scan_max_bytes=1600)
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "firing.jsonl", turn_scan_max_bytes=1600)
        self.assertFalse(scan["turn_complete"])
        self.assertGreaterEqual(scan["err_peak"], config.loop_error_run_threshold)
        self.assertGreaterEqual(scan["err_total"], config.loop_error_total_threshold)
        self.assertEqual(0, scan["ok_total"])
        signal = runtime_turns.loop_signal(scan, config)
        assert signal is not None
        self.assertEqual({"errors", "tool"}, set(signal))
        self.assertNotIn("failures", signal)
        self.assertNotIn("barren", signal)

    def test_the_total_rung_will_not_fire_on_a_turn_the_scan_never_saw_open(self) -> None:
        # The one case where the gate is the only thing keeping the signal
        # quiet: the tail holds six failures with a success among them, so the
        # total reaches its threshold while the run stays at three. Firing here
        # would state a turn total counted from part of the turn.
        written: list[Any] = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the thing"},
            }
        ]
        for i in range(20):
            written.append(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "message": {"content": [{"type": "tool_use", "id": f"a{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": "2026-01-01T00:00:02Z",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": f"a{i}"}]},
                }
            )
        for i, outcome in enumerate("fffofff"):
            result: dict[str, Any] = {"type": "tool_result", "tool_use_id": f"b{i}"}
            if outcome == "f":
                result["is_error"] = True
            written.append(
                {
                    "type": "assistant",
                    "timestamp": "2026-01-01T00:01:01Z",
                    "message": {"content": [{"type": "tool_use", "id": f"b{i}", "name": "Bash"}]},
                }
            )
            written.append(
                {
                    "type": "user",
                    "timestamp": "2026-01-01T00:01:02Z",
                    "message": {"content": [result]},
                }
            )
        config, _ = make_runtime(turn_scan_max_bytes=1900)
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "partial.jsonl", turn_scan_max_bytes=1900)
        self.assertFalse(scan["turn_complete"])
        self.assertLess(scan["err_peak"], config.loop_error_run_threshold)
        self.assertGreaterEqual(scan["err_total"], config.loop_error_total_threshold)
        self.assertIsNone(runtime_turns.loop_signal(scan, config))

    def test_the_named_tool_is_the_most_recent_failure_not_the_one_at_the_peak(self) -> None:
        # `err_tool` was written only when the run set a new peak, so the three
        # Read failures after a Bash peak published "most recently Bash".
        written = self._mixed_transcript("fffo", tool="Bash")
        # Re-key the second half so its ids do not collide with the first, and
        # keep each call paired with its own result.
        tail = self._mixed_transcript("fff", tool="Read")[1:]
        for record in tail:
            for block in record["message"]["content"]:
                for key in ("id", "tool_use_id"):
                    if key in block:
                        block[key] = "r" + block[key]
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written + tail, Path(tmp) / "tools.jsonl")
        self.assertEqual(6, scan["err_total"])
        self.assertEqual("Read", scan["err_tool"])

    def test_only_claude_records_report_a_failure_total(self) -> None:
        # The same absence the peak already asserts. An unmeasured semantic
        # must not arrive as a measurement through the new counter either.
        for harness in ("droid", "codex", "copilot", "gemini"):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "loop.jsonl"
                path.write_text(
                    "\n".join(json.dumps(r) for r in self._mixed_transcript("fffofff")) + "\n"
                )
                config, state = make_runtime()
                scan = runtime_turns.scan_turns(config, state, str(path), harness)
                assert scan is not None
                self.assertEqual(0, scan["err_total"])
                self.assertEqual(0, scan["ok_total"])
                self.assertIsNone(runtime_turns.loop_signal(scan, config))

    def test_only_claude_records_report_a_failed_tool_call(self) -> None:
        # Every other harness gets nothing, and the assertion is the absence:
        # Codex's tool-output records carry no error field, Copilot's analyzer
        # reads no tool-end record, and Droid's block shape matches Claude's but
        # no failing Droid call has been captured. An unmeasured semantic must
        # not arrive as a measurement — so the same transcript scanned as
        # another harness counts nothing.
        for harness in ("droid", "codex", "copilot", "gemini"):
            with self.subTest(harness=harness), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "loop.jsonl"
                path.write_text("\n".join(json.dumps(r) for r in self._loop_transcript(6)) + "\n")
                config, state = make_runtime()
                scan = runtime_turns.scan_turns(config, state, str(path), harness)
                assert scan is not None
                self.assertEqual(0, scan["err_peak"])
                self.assertIsNone(runtime_turns.loop_signal(scan, config))

    def test_a_run_split_by_a_quiet_stretch_is_not_a_loop(self) -> None:
        # A permission prompt or an open question parks a turn for minutes at a
        # time, and the scanner already re-anchors the clock there. Failures on
        # either side of that gap are not a tight loop, so the run goes with it.
        written = self._loop_transcript(2)
        later = self._loop_transcript(2, minute=30)[1:]  # same turn, after the gap
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written + later, Path(tmp) / "gap.jsonl")
        self.assertEqual(2, scan["err_peak"])

    def test_the_run_survives_an_incremental_scan_without_double_counting(self) -> None:
        # The scanner carries state between /api/data requests, so a counter is
        # exactly the shape that double-advances when the second call re-reads a
        # record the first already applied.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "growing.jsonl"
            written = self._loop_transcript(4)
            path.write_text("\n".join(json.dumps(r) for r in written) + "\n")
            config, state = make_runtime()
            first = runtime_turns.scan_turns(config, state, str(path), "claude")
            assert first is not None
            after_first = first["err_peak"]
            with path.open("a") as output:
                for record in self._loop_transcript(1, minute=1)[1:]:
                    output.write(json.dumps(record) + "\n")
            second = runtime_turns.scan_turns(config, state, str(path), "claude")
        assert second is not None
        self.assertEqual(4, after_first)
        self.assertEqual(5, second["err_peak"])

    def test_a_scan_result_is_a_snapshot_not_the_live_accumulator(self) -> None:
        # The accumulator lives in `state.turn_scan` for the life of the file, so
        # handing it back by reference makes every result an alias of the next
        # one. A top-level copy is not enough either: `durations` is appended to
        # in place, and the tail trim at the end of a scan rebinds it, so a
        # shallow copy points at the list the NEXT call appends to.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "aliased.jsonl"
            written = self._loop_transcript(2) + self._loop_transcript(2, minute=1)
            path.write_text("\n".join(json.dumps(record) for record in written) + "\n")
            config, state = make_runtime()
            first = runtime_turns.scan_turns(config, state, str(path), "claude")
            assert first is not None
            durations, peak = list(first["durations"]), first["err_peak"]
            with path.open("a") as output:
                for record in self._loop_transcript(3, minute=2):
                    output.write(json.dumps(record) + "\n")
            second = runtime_turns.scan_turns(config, state, str(path), "claude")
            assert second is not None
            self.assertIsNot(first, second)
            self.assertIsNot(state.turn_scan[str(path)], second)
        # The two calls disagree, which is what makes the assertions above bite.
        self.assertNotEqual(durations, second["durations"])
        self.assertNotEqual(peak, second["err_peak"])
        self.assertEqual(durations, first["durations"])
        self.assertEqual(peak, first["err_peak"])

    def test_a_failure_is_attributed_to_the_tool_that_failed(self) -> None:
        # The name is only on the `tool_use` block, so the id is the whole join.
        # Two calls issued in one batch and answered out of order is where a
        # "most recent name wins" shortcut names the wrong tool.
        written: list[Any] = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": {"content": "fix the thing"},
            },
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "a", "name": "Bash"},
                        {"type": "tool_use", "id": "b", "name": "Edit"},
                    ]
                },
            },
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:02Z",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "b", "is_error": True},
                        {"type": "tool_result", "tool_use_id": "a", "is_error": True},
                    ]
                },
            },
        ]
        written.extend(self._loop_transcript(2, tool="Read")[1:])
        with tempfile.TemporaryDirectory() as tmp:
            scan = self._scan(written, Path(tmp) / "batch.jsonl")
        self.assertEqual(4, scan["err_peak"])
        self.assertEqual("Read", scan["err_tool"])

    def test_base_session_exposes_full_sid_and_truncated_display_id(self) -> None:
        s = runtime_sessions.base_session("gemini", "session-abcdef123", "proj")
        self.assertEqual("session-", s["session"])  # display stays 8 chars
        self.assertEqual("session-abcdef123", s["sid"])  # identity stays full

    def test_every_constructed_session_row_declares_the_same_field_set(self) -> None:
        # Why the set is fixed at all: a key that appears for only some harnesses
        # makes every consumer test for presence rather than for a value. So a
        # field arriving for one harness is declared for all of them, and this
        # test is the place that has to be edited to say so.
        #
        # The constructor's half. It cannot be the whole guarantee, because every
        # field written onto a row after construction is outside its reach:
        # measured, an undeclared key added to a published row left all 2,325
        # tests green. PublishedSessionFieldSetTest below is the half that reaches
        # the payload, and it is the one that catches that.
        for harness in ("claude", "copilot", "goose", "pi"):
            with self.subTest(harness=harness):
                row = runtime_sessions.base_session(harness, f"{harness}-1", "proj")
                self.assertSetEqual(set(DECLARED_SESSION_FIELDS), set(row))

    def test_a_resume_token_is_admitted_only_in_a_shape_a_shell_reads_as_one_word(
        self,
    ) -> None:
        # This value is published so the page can put a shell command on someone's
        # clipboard, which makes the grammar the guard rather than any quoting the
        # page might do. It comes off a filename, and a filename is untrusted: the
        # store belongs to the harness, not to us.
        self.assertEqual(
            "27d10654-1cb5-481e-8194-6ce868b91bb5",
            runtime_sessions.resume_token("27d10654-1cb5-481e-8194-6ce868b91bb5"),
        )
        self.assertEqual("019fa752_a888", runtime_sessions.resume_token("019fa752_a888"))
        for refused in (
            None,
            "",
            "id with spaces",
            "id;rm -rf ~",
            "$(whoami)",
            "`id`",
            "id\nnewline",
            "../../etc/passwd",
            "a" * 65,
            # A leading dash is the one hostile shape a shell does NOT split, and
            # so the one the word-splitting reading of this grammar missed. Both
            # of these are real valueless flags on the CLIs the verb table names,
            # and both disable that harness's permission checks: `claude --resume`
            # takes an optional value, so it never consumes a `-`-leading token,
            # and clap binds one to the option rather than to Codex's positional.
            # The published id would be dropped and the flag applied.
            "--dangerously-skip-permissions",
            "--dangerously-bypass-approvals-and-sandbox",
            "-p",
        ):
            with self.subTest(refused=refused):
                self.assertIsNone(runtime_sessions.resume_token(refused))

    def test_no_collector_may_fill_the_completion_stamp(self) -> None:
        # Only the event path can observe a turn ending. A collector inferring it
        # from a last-record kind would render identically to a measurement, and
        # six of the ten harnesses have nothing to infer it from at all — so the
        # declared None has to survive every collector in the registry.
        self.assertIsNone(runtime_sessions.base_session("claude", "abc", "proj")["finished_at"])
        source = Path(runtime_sessions.__file__).parent
        writers = [
            path.name
            for path in sorted((source / "collectors").glob("*.py"))
            if '"finished_at"' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual([], writers, "a collector is guessing at completion")

    def test_an_unmeasured_session_start_is_declared_as_none(self) -> None:
        self.assertIsNone(runtime_sessions.base_session("pi", "abc", "proj")["started_at"])

    def test_consumption_ships_unfilled_for_a_harness_that_keeps_no_ledger(self) -> None:
        # Copilot's collector fills this; every other harness leaves the declared
        # None, which reads as "no accounting", never as "spent nothing".
        self.assertIsNone(runtime_sessions.base_session("goose", "abc", "proj")["consumption"])

    def test_model_ships_unfilled_and_bounded_by_a_cap_of_its_own(self) -> None:
        # None is the declared value, and it means "not read" rather than "no
        # model" — five harnesses in ten publish it after this batch, so it is the
        # commonest reading and not an edge. The page draws it as an explicit dash
        # for that reason; a blank slot is indistinguishable from a measurement.
        row = runtime_sessions.base_session("goose", "abc", "proj")
        self.assertIsNone(row["model"])
        self.assertIsNone(row["provider"])
        self.assertEqual([], row["subagents"])

        # The cap is this module's own symbol even though `quota` already has a
        # 40. `quota` imports this module, so importing back is a cycle — but the
        # reason they are separate is that they answer different questions: quota's
        # cap feeds a distinctness digest so two long model names sharing a prefix
        # stay two usage rows, and a session row, holding one model and nothing to
        # tell it apart from, only truncates. Either may move without the other,
        # which is what this asserts: agreement is not required, independence is.
        self.assertEqual(40, runtime_sessions.MODEL_CAP_CHARS)
        source = Path(runtime_sessions.__file__ or "").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"^\s*(?:from|import)\b.*\bquota\b", source, re.MULTILINE),
            "sessions.py imported quota — quota.py imports sessions, so that is a cycle",
        )

    def test_a_subagent_element_always_carries_measurement_keys(self) -> None:
        # The published element declares model and started_at even when neither
        # was measured. A parallel map of only measured values would be smaller,
        # but absence from it would mean either "same as the parent" / "started
        # with the parent" or "nobody measured it", which collapses the facts.
        # A parallel list of only the children whose model differs is refused for
        # the same reason: absence from such a list means
        # either "same as the parent" or "nobody read one", which collapses in the
        # wire format the two facts this field exists to keep apart. There is also
        # no sound join key to build one on — several collectors fall back to a
        # bare "subagent" label, so two unnamed children collide and a model gets
        # attributed to a sibling.
        #
        # Nothing here builds an element; the collectors do, each in its own test.
        # What this pins is that the one shared consumer survives either shape:
        # `working_detail` counts elements without reading inside them, which is
        # why the collectors can be converted one at a time.
        self.assertEqual([], runtime_sessions.base_session("claude", "abc", "proj")["subagents"])
        self.assertEqual(
            "running 2 subagents",
            runtime_sessions.working_detail(None, [{"name": "a", "model": None}, "b"]),
        )
        self.assertEqual(
            "running 1 subagent", runtime_sessions.working_detail(None, [{"name": "a"}])
        )
        self.assertEqual("generating…", runtime_sessions.working_detail(None, []))

    def test_base_session_declares_subagents_omitted_zero(self) -> None:
        self.assertEqual(
            0, runtime_sessions.base_session("claude", "abc", "proj")["subagents_omitted"]
        )

    def test_cap_subagents_roster_orders_live_first_and_newest_finished_next(self) -> None:
        roster: list[dict[str, Any]] = [
            {"name": "old-finished", "active": False, "started_at": 1000.0},
            {"name": "live-older", "active": True, "started_at": 1500.0},
            {"name": "newest-finished", "active": False, "started_at": 3000.0},
            {"name": "live-newer", "active": True, "started_at": 2000.0},
            {"name": "unmeasured-finished", "active": None, "started_at": 2500.0},
        ]
        capped, omitted = runtime_sessions.cap_subagents_roster(roster, cap=3)
        self.assertEqual(2, omitted)
        self.assertEqual(
            ["live-older", "live-newer", "newest-finished"],
            [r["name"] for r in capped],
        )

    def test_cap_subagents_roster_returns_zero_omitted_under_cap(self) -> None:
        roster: list[dict[str, Any]] = [{"name": "worker", "active": True, "started_at": 1000.0}]
        capped, omitted = runtime_sessions.cap_subagents_roster(roster, cap=60)
        self.assertEqual(0, omitted)
        self.assertEqual(roster, capped)

    def test_turn_clock_reanchors_after_quiet_gap(self) -> None:
        # Time blocked on a human (permission prompt, AskUserQuestion, sleep)
        # writes nothing to the transcript. A quiet gap longer than
        # TURN_GAP_RESET_SEC inside a turn must re-anchor the elapsed clock at
        # the post-gap event instead of billing the wait as generation time.
        base = 1_784_000_000.0

        def iso(offset: float) -> str:
            return str(datetime.fromtimestamp(base + offset, UTC).isoformat())

        records = [
            {
                "type": "user",
                "timestamp": iso(0),
                "message": {"role": "user", "content": "start the work"},
            },
            {
                "type": "assistant",
                "timestamp": iso(20),
                "message": {"role": "assistant", "content": []},
            },
            {
                "type": "assistant",
                "timestamp": iso(40),
                "message": {"role": "assistant", "content": []},
            },
            # 45-minute wait on the human, then generation resumes.
            {
                "type": "assistant",
                "timestamp": iso(40 + 2700),
                "message": {"role": "assistant", "content": []},
            },
            {
                "type": "assistant",
                "timestamp": iso(70 + 2700),
                "message": {"role": "assistant", "content": []},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
            config, state = make_runtime()
            scan = runtime_turns.scan_turns(config, state, str(path), "claude")

        assert scan is not None
        # Clock re-anchored at the post-gap record, not the original prompt.
        self.assertEqual(base + 40 + 2700, scan["turn_start"])
        # The pre-gap active segment is banked as a finished duration.
        self.assertIn(40.0, scan["durations"])

    def test_local_command_output_is_not_a_turn_start(self) -> None:
        rec = {
            "type": "user",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "user",
                "content": "<local-command-stdout>ok</local-command-stdout>",
            },
        }
        self.assertIsNone(records._turn_signal(rec, "claude"))
        caveat = {
            "type": "user",
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {
                "role": "user",
                "content": "<local-command-caveat>x</local-command-caveat>",
            },
        }
        self.assertIsNone(records._turn_signal(caveat, "claude"))

    def test_uuidv7_sessions_started_together_get_distinct_display_ids(self) -> None:
        # DRC-3962. Codex ids are UUIDv7: the first 48 bits are a millisecond
        # timestamp, so a fan-out launched in one directory shares its leading
        # hex. Truncating the display id to 8 chars rendered four distinct
        # sessions as the same harness, project and id — one session, seen
        # four times. Observed live: 019fa752-a888…, -a889…, -a88d…, -a8a7….
        sessions = [
            runtime_sessions.base_session(
                "codex", f"019fa752-a88{tail}-7fe3-a529-ebd8042771c{i}", "p"
            )
            for i, tail in enumerate(("8", "9", "d"))
        ]
        runtime_sessions.assign_display_ids(make_config(), sessions)
        shown = [s["session"] for s in sessions]

        self.assertEqual(len(shown), len(set(shown)))
        # The full id stays intact for keying; only the display id grows.
        self.assertEqual("019fa752-a888-7fe3-a529-ebd8042771c0", sessions[0]["sid"])

    def test_display_ids_widen_only_for_the_harness_that_collides(self) -> None:
        # Expanding every id because one pair collides would churn the whole
        # UI. The other harness's ids must be long enough to *show* whether
        # they were truncated: an 8-char sid is unaffected by any width, so a
        # test using one cannot tell per-harness widening from global.
        sessions = [
            runtime_sessions.base_session("gemini", "aaaa1111-cccc-4444-8888-000000000001", "p"),
            runtime_sessions.base_session("gemini", "bbbb2222-dddd-4444-8888-000000000002", "p"),
            runtime_sessions.base_session("codex", "019fa752-a888-7fe3-a529-ebd8042771c1", "p"),
            runtime_sessions.base_session("codex", "019fa752-a889-73a3-88ba-d362c54a1ae6", "p"),
        ]
        runtime_sessions.assign_display_ids(make_config(), sessions)

        # Gemini's ids already differ at 8 chars, so they stay at the floor
        # even though Codex in the same snapshot had to widen.
        self.assertEqual(["aaaa1111", "bbbb2222"], [s["session"] for s in sessions[:2]])
        codex = [s["session"] for s in sessions[2:]]
        self.assertEqual(len(codex), len(set(codex)))
        self.assertTrue(all(len(c) > 8 for c in codex))

    def test_a_colliding_fan_out_does_not_widen_unrelated_projects(self) -> None:
        # A four-agent fan-out started in the same millisecond needs 16 to 18
        # characters to separate. Grouping by harness alone would hand that
        # width to every other Codex row, including a lone session in an
        # unrelated worktree that was never ambiguous.
        sessions = [
            runtime_sessions.base_session(
                "codex", "019fa752-a888-7fe3-a529-ebd8042771c1", "recce/infra"
            ),
            runtime_sessions.base_session(
                "codex", "019fa752-a889-73a3-88ba-d362c54a1ae6", "recce/infra"
            ),
            runtime_sessions.base_session(
                "codex", "019fa752-a88d-7d23-978a-a8d2d2584c3b", "recce/infra"
            ),
            runtime_sessions.base_session(
                "codex", "019fa752-a8a7-71f1-ac29-fd97c876c5e3", "recce/other"
            ),
        ]
        runtime_sessions.assign_display_ids(make_config(), sessions)

        # The lone row in the other worktree keeps the floor.
        self.assertEqual("019fa752", sessions[3]["session"])
        colliding = [s["session"] for s in sessions[:3]]
        self.assertEqual(len(colliding), len(set(colliding)))

    def test_display_ids_ignore_collisions_across_different_harnesses(self) -> None:
        # Two harnesses can hand out the same id without either row being
        # ambiguous: the harness badge already separates them.
        shared = "019fa752-a888-7fe3-a529-ebd8042771c1"
        sessions = [
            runtime_sessions.base_session("codex", shared, "p"),
            runtime_sessions.base_session("gemini", shared, "p"),
        ]
        runtime_sessions.assign_display_ids(make_config(), sessions)

        self.assertEqual(["019fa752", "019fa752"], [s["session"] for s in sessions])

    def test_collect_widens_colliding_display_ids_end_to_end(self) -> None:
        # The widening is only worth anything if collect() actually applies
        # it: deleting the call leaves every unit test green.
        now = time.time()
        iso = datetime.fromtimestamp(now - 5, UTC).isoformat()
        sids = (
            "019fa752-a888-7fe3-a529-ebd8042771c1",
            "019fa752-a889-73a3-88ba-d362c54a1ae6",
        )
        with tempfile.TemporaryDirectory() as tmp:
            rollout = Path(tmp) / "codex" / "2026" / "07" / "28"
            rollout.mkdir(parents=True)
            for sid in sids:
                (rollout / f"rollout-2026-07-28T09-36-23-{sid}.jsonl").write_text(
                    json.dumps(
                        {
                            "timestamp": iso,
                            "type": "session_meta",
                            "payload": {"id": sid, "cwd": "/w/proj", "source": "exec"},
                        }
                    )
                    + "\n"
                )
            with (
                store_patch(CODEX_SESSIONS_DIR=str(Path(tmp) / "codex")),
                mock.patch.dict(STORE_OVERRIDES, {"codex.sessions": [str(Path(tmp) / "codex")]}),
            ):
                data = collect(24, False)

        codex = [s for s in data["sessions"] if s["harness"] == "codex"]
        self.assertEqual(2, len(codex))
        shown = [s["session"] for s in codex]
        self.assertEqual(len(shown), len(set(shown)), f"collect() left ambiguous ids: {shown}")

    def test_identical_sids_do_not_widen_display_ids_forever(self) -> None:
        # Two rows with the same sid cannot be told apart by widening, so the
        # widening must not fire at all: it terminates, and it leaves the id
        # short rather than pointlessly expanding both to the full uuid.
        sessions = [
            runtime_sessions.base_session("codex", "019fa752-a888-7fe3-a529-ebd8042771c1", "p"),
            runtime_sessions.base_session("codex", "019fa752-a888-7fe3-a529-ebd8042771c1", "p"),
        ]
        runtime_sessions.assign_display_ids(make_config(), sessions)

        self.assertEqual(["019fa752"] * 2, [s["session"] for s in sessions])


class DurationAndEpochTest(unittest.TestCase):
    """`fmt_duration` and `norm_epoch` render on every card and had no tests at
    all. Mutation-checked: each boundary below fails a real off-by-one that the
    suite previously missed."""

    def test_each_unit_changes_at_its_own_boundary(self) -> None:
        # The second either side of every cutover, because `<` vs `<=` here is
        # the difference between a card reading "60m" and "1h 0m".
        for seconds, expected in (
            (0, "0s"),
            (59, "59s"),
            (60, "1m"),
            (3599, "59m"),
            (3600, "1h 0m"),
            (3661, "1h 1m"),
            (86399, "23h 59m"),
            (86400, "1d 0h"),
            (90061, "1d 1h"),
        ):
            with self.subTest(seconds=seconds):
                self.assertEqual(expected, runtime_sessions.fmt_duration(seconds))

    def test_an_unknown_or_impossible_duration_renders_a_dash(self) -> None:
        # A negative duration means the clock moved, not that work took
        # negative time, so the card must decline to state one.
        for bad in (None, -1, -0.5, -86400):
            with self.subTest(seconds=bad):
                self.assertEqual("–", runtime_sessions.fmt_duration(bad))

    def test_millisecond_timestamps_are_detected_by_magnitude(self) -> None:
        """Harness stores mix seconds and milliseconds. Guessing wrong puts a
        session in 1970 or 55000 AD, and it silently reads as never-active."""
        self.assertEqual(1_700_000_000, records.norm_epoch(1_700_000_000))
        self.assertEqual(1_700_000_000.0, records.norm_epoch(1_700_000_000_000))
        # The cutover itself: 1e12 is seconds, one above it is milliseconds.
        self.assertEqual(1e12, records.norm_epoch(1e12))
        self.assertAlmostEqual(1e9, records.norm_epoch(1e12 + 1), places=0)

    def test_a_task_shorter_than_the_floor_does_not_licence_an_estimate(self) -> None:
        """The skill body promises "no estimate" until a session has a completed
        task that took at least 30s, so a burst of instant tasks cannot imply a
        confident ETA. Mutation-checked: `>=` vs `>` on that floor survived.

        The rule is exercised through `load_tasks` rather than through real
        files because `created` comes from `st_birthtime`, which Linux does not
        have. On that runner it degrades to mtime, every task looks
        zero-length, and a file-based fixture would assert nothing.
        """
        now = 1_700_000_000.0

        def tasks(took: float) -> dict[str, list[dict[str, Any]]]:
            return {
                "abcd1234": [
                    {
                        "id": "1",
                        "subject": "done",
                        "activeForm": "",
                        "status": "completed",
                        "created": now - took,
                        "updated": now,
                    },
                    {
                        "id": "2",
                        "subject": "still open",
                        "activeForm": "",
                        "status": "pending",
                        "created": now - 10,
                        "updated": now,
                    },
                ]
            }

        with tempfile.TemporaryDirectory() as empty:
            observed = {}
            for took in (29, 30, 60):
                with (
                    mock.patch.object(
                        claude_collector, "load_tasks", lambda _config, t=took: tasks(t)
                    ),
                    store_patch(PROJECTS_DIR=empty),
                ):
                    observed[took] = collect_claude(now, 24, True)[0]["eta_h"]

        self.assertIsNone(observed[29], "29s of evidence is not enough for an ETA")
        # One open task times the 30s average.
        self.assertEqual("30s", observed[30])
        self.assertEqual("1m", observed[60])

    def test_a_missing_or_nonsense_timestamp_is_not_activity(self) -> None:
        # 0 is the "no timestamp" sentinel every freshness check treats as
        # ancient. Returning the raw value instead would date a session to 1970
        # and, for a negative, to before it.
        nonsense: list[Any] = [0, -5, "1700000000", None, [], {}]
        for bad in nonsense:
            with self.subTest(value=bad):
                self.assertEqual(0, records.norm_epoch(bad))


class ClockSkewTest(unittest.TestCase):
    # A future timestamp satisfies every `now - ts <= threshold` test, so before
    # age()/is_fresh() a clock-skewed store pinned its session to Working
    # permanently and kept feeding its tokens into the output rate.
    NOW = 1_700_000_000.0
    SKEW = 86_400.0  # a day ahead, e.g. a WSL2 guest clock after host suspend

    def test_an_implausibly_future_timestamp_is_rejected(self) -> None:
        config = make_config()
        self.assertIsNone(runtime_sessions.age(config, self.NOW, self.NOW + self.SKEW))
        self.assertEqual(10.0, runtime_sessions.age(config, self.NOW, self.NOW - 10))

    def test_sampling_noise_is_clamped_rather_than_rejected(self) -> None:
        # stat() and the collection clock are read microseconds apart, and
        # coarse filesystems round upward — a small overshoot is not skew.
        config = make_config()
        jitter = config.future_skew_tolerance_sec / 2
        self.assertEqual(0.0, runtime_sessions.age(config, self.NOW, self.NOW + jitter))
        self.assertTrue(runtime_sessions.is_fresh(config, self.NOW, self.NOW + jitter, 1))

    def test_a_future_timestamp_does_not_read_as_activity(self) -> None:
        # The whole point: negative ages used to pass every threshold test.
        config = make_config()
        self.assertFalse(
            runtime_sessions.is_fresh(
                config, self.NOW, self.NOW + self.SKEW, config.working_threshold_sec
            )
        )

    def test_future_dated_tokens_do_not_inflate_the_output_rate(self) -> None:
        info = {"usage_events": [(self.NOW + self.SKEW, 5000)]}
        self.assertEqual(0, runtime_sessions.rate_from(info, self.NOW, make_config()))

    def test_a_future_dated_turn_start_yields_no_eta(self) -> None:
        scan = {"turn_start": self.NOW + self.SKEW, "durations": [60.0]}
        self.assertIsNone(runtime_turns.turn_progress(scan, "working", self.NOW, make_config()))

    def test_a_future_dated_transcript_does_not_read_as_working(self) -> None:
        session_id = "beefcafe-1111-2222-3333-444455556666"
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = projects / "-w-skewed"
            project.mkdir(parents=True)
            transcript = project / f"{session_id}.jsonl"
            transcript.write_text(json.dumps({"type": "user", "uuid": "u1"}) + "\n")
            future = self.NOW + self.SKEW
            os.utime(transcript, (future, future))
            with (
                store_patch(PROJECTS_DIR=str(projects)),
                store_patch(TASKS_DIR=str(Path(tmp) / "tasks")),
            ):
                # A day-ahead mtime previously made `now - mtime` negative, so
                # the session reported "working" for the whole day of skew.
                sessions = collect_claude(self.NOW, 24, True)

        self.assertEqual(1, len(sessions))
        self.assertEqual("idle", sessions[0]["state"])


class ReviewFixTest(unittest.TestCase):
    """Regressions found by the adversarial review passes on PR #7."""

    NOW = 1_700_000_000.0

    def test_the_same_session_in_two_stores_yields_one_row(self) -> None:
        # Scanning every candidate root can find a session left behind by a
        # migration twice; the DB-backed collectors append per store.
        rows = [
            {**runtime_sessions.base_session("opencode", "same", "p"), "last_activity": 10.0},
            {**runtime_sessions.base_session("opencode", "same", "p"), "last_activity": 99.0},
            {**runtime_sessions.base_session("goose", "same", "p"), "last_activity": 5.0},
        ]
        merged = runtime_sessions.dedupe_sessions(rows)
        self.assertEqual(2, len(merged), "duplicate session id was not merged")
        opencode = next(r for r in merged if r["harness"] == "opencode")
        self.assertEqual(99.0, opencode["last_activity"], "kept the staler copy")


class VerificationFixTest(unittest.TestCase):
    """Regressions found by the adversarial pass that tried to refute the fixes."""

    NOW = 1_700_000_000.0

    FUTURE = NOW + 86_400

    def test_newest_plausible_ignores_skew(self) -> None:
        config = make_config()
        self.assertEqual(
            self.NOW,
            runtime_sessions.newest_plausible(config, self.NOW, (self.FUTURE, self.NOW)),
        )
        self.assertEqual(0.0, runtime_sessions.newest_plausible(config, self.NOW, (self.FUTURE,)))
        self.assertEqual(0.0, runtime_sessions.newest_plausible(config, self.NOW, ()))

    def test_a_skewed_duplicate_does_not_win_deduplication(self) -> None:
        # Ranking by raw last_activity let a clock-skewed migrated copy beat the
        # live one — the very problem rejecting future timestamps is for.
        config = make_config()
        good = {**runtime_sessions.base_session("opencode", "same", "p"), "state": "working"}
        good["last_activity"] = runtime_sessions.newest_plausible(config, self.NOW, (self.NOW,))
        skewed = {**runtime_sessions.base_session("opencode", "same", "p"), "state": "idle"}
        skewed["last_activity"] = runtime_sessions.newest_plausible(
            config, self.NOW, (self.FUTURE,)
        )
        for order in ([good, skewed], [skewed, good]):
            with self.subTest(order=[s["state"] for s in order]):
                self.assertEqual("working", runtime_sessions.dedupe_sessions(order)[0]["state"])


class PublishedSessionFieldSetTest(HarnessContractTestCase):
    """The declared field set, held against the rows a reader's page receives.

    The constructor's half of this lives in `CompassServerTest` above and cannot
    stand alone: it inspects `base_session()`'s return value, so every field
    written onto a row after construction is outside its reach. Measured at
    5bca94b — an undeclared key added to every published row in
    `Application.collect` left all 2,325 tests green (DRC-4473). `acquisition`
    and `blocked_since` had been sitting in exactly that blind spot.
    """

    def test_every_published_session_row_declares_the_same_field_set(self) -> None:
        # Ten real stores, one at a time, through a full collection: the payload
        # rather than the constructor, because the constructor is not where the
        # last writer is. Equality and not a subset — a name declared for some
        # rows and absent from others is what makes every consumer test for
        # presence rather than for a value, which is the whole point of the table.
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                rows = self.sessions_for(self.collect(build, when=self.NOW), key)
                self.assertEqual(1, len(rows), f"expected one session, got {rows}")
                # Both sides `set` and not a frozenset against a set, so
                # unittest dispatches assertSetEqual and the failure NAMES the
                # offending key. Compared as mismatched types it reports two
                # truncated reprs instead, which leaves whoever hit it grepping.
                self.assertSetEqual(set(DECLARED_SESSION_FIELDS), set(rows[0]))

    def test_the_published_annotation_is_never_the_constructor_default(self) -> None:
        # `base_session` declares these empty, the way it declares
        # `acquisition` as None, because that module has no runtime imports.
        # The comment there claims a blank never reaches a reader, and this is
        # what makes the claim checkable: the payload carries the absence and
        # its reason, which is a sentence the board can print.
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                rows = self.sessions_for(self.collect(build, when=self.NOW), key)
                self.assertEqual("", rows[0]["annotation_goal"])
                self.assertTrue(rows[0]["annotation_goal_why"], "an absence with no reason")
                self.assertTrue(rows[0]["annotation_lines_why"], "an absence with no reason")
                self.assertEqual(0, rows[0]["annotation_revision_count"])
                self.assertIsNone(rows[0]["annotation_revision"])

    def test_every_published_row_says_whether_a_press_could_read_it(self) -> None:
        # Computed on every row by the collection, never left at the
        # constructor's None while annotations are on (DRC-4758 slice A2), and
        # it is the answer the press check gives for the row as published.
        for key, build in HARNESSES:
            with self.subTest(harness=key, fixture=build.__name__):
                rows = self.sessions_for(self.collect(build, when=self.NOW), key)
                published = rows[0]["reading_eligibility"]
                self.assertIsInstance(published, dict)
                self.assertSetEqual({"ok", "reason", "until", "sentence"}, set(published))
                self.assertEqual(published["ok"], published["reason"] is None)
                if published["reason"] is not None:
                    self.assertIn(published["reason"], reading.PRESS_WITHHELD)
                config, _state = support_runtime()
                self.assertEqual(
                    reading.press_eligibility(
                        rows[0], (), now=self.NOW, settle_sec=config.reading_settle_sec
                    ),
                    published,
                )

    def test_an_idle_row_with_no_stop_and_no_end_is_published_as_unreadable(self) -> None:
        key, build = next((k, b) for k, b in HARNESSES if k == "codex")
        # Written ten minutes before the collection, so the row is idle.
        rows = self.sessions_for(self.collect(build, when=self.NOW - 600), key)
        self.assertEqual("idle", rows[0]["state"], "the fixture is not the idle case")
        self.assertIsNone(rows[0]["finished_at"])
        self.assertEqual(
            {
                "ok": False,
                "reason": reading.WITHHELD_IDLE_UNKNOWN,
                "until": None,
                "sentence": reading.withheld_sentence(reading.WITHHELD_IDLE_UNKNOWN, rows[0]),
            },
            rows[0]["reading_eligibility"],
        )

    def test_a_stored_annotation_reaches_the_published_row_through_collect(self) -> None:
        # The wiring nothing else covered. `AnnotationOnTheRowTest` calls the
        # attach pass directly, so removing its call site in `Application.collect`
        # left every test green while the feature's whole purpose stopped
        # working. Verified as a real gap by mutation before this was written.
        key, build = next((k, b) for k, b in HARNESSES if k == "codex")
        with self.subTest(harness=key):
            config, _state = support_runtime()
            annotation_store.annotate(
                config,
                _state,
                key,
                self.SID,
                goal="Ship the cockpit",
                lines=["A screenshot per screen", "No board edits"],
                now=self.NOW,
            )
            # The store is the shared runtime's and outlives this test, so the
            # sibling asserting an unannotated row would see these words.
            self.addCleanup(annotation_store.clear, config, _state, key, self.SID)
            rows = self.sessions_for(self.collect(build, when=self.NOW), key)
            self.assertEqual("Ship the cockpit", rows[0]["annotation_goal"])
            self.assertEqual(1, rows[0]["annotation_revision"])
            self.assertEqual("", rows[0]["annotation_goal_why"])
            # Each outcome line reaches the row as its own field, never the
            # constructor's empty default (DEC-24 item 3).
            self.assertEqual("A screenshot per screen", rows[0]["annotation_line_1"])
            self.assertEqual("No board edits", rows[0]["annotation_line_2"])
            self.assertEqual("typed", rows[0]["annotation_line_2_source"])
            self.assertEqual("", rows[0]["annotation_line_3"])
            self.assertEqual("", rows[0]["annotation_lines_why"])

    def test_every_field_an_event_may_patch_is_a_declared_field(self) -> None:
        # The reachable-by-an-envelope half, which no store fixture can produce:
        # an overlay writes any member of `events.PATCHABLE` onto a row it
        # matched, so an undeclared name there is a key an untrusted POST can add
        # to a published row. `blocked_since` was one of them.
        self.assertLessEqual(set(runtime_events.PATCHABLE), DECLARED_SESSION_FIELDS)

    def test_collection_republishes_saved_goals_without_producing_observations(self) -> None:
        key, build = next((k, b) for k, b in HARNESSES if k == "codex")
        config, _state = support_runtime()
        path = observer.write_sidecar(
            config,
            key,
            self.SID,
            {
                "goal": "Model prose",
                "goal_source": "model",
                "deterministic_goal": "Saved goal",
                "observed_at": 100,
                "transcript": ["old-signature", 1],
            },
        )
        assert path is not None
        self.addCleanup(Path(path).unlink, missing_ok=True)
        with contextlib.ExitStack() as stack:
            for name in ("analyze", "CodexGoalModel", "write_sidecar", "resolve_transcript"):
                stack.enter_context(
                    mock.patch.object(observer, name, side_effect=AssertionError(name))
                )
            read = stack.enter_context(
                mock.patch.object(observer, "read_sidecar", wraps=observer.read_sidecar)
            )
            data = self.collect(build, when=self.NOW)
            rows = self.sessions_for(data, key)
            self.assertEqual(
                {"goal": "Saved goal", "source": "deterministic", "observed_at": 100},
                rows[0]["cached_deterministic_goal"],
            )
            self.assertTrue(data["spacedock_enabled"])
            read.assert_called_once_with(mock.ANY, key, self.SID)
            Path(path).write_text('{"deterministic_goal":"Changed saved goal"}', encoding="utf-8")
            rows = self.sessions_for(self.collect(build, when=self.NOW), key)
            self.assertEqual("Changed saved goal", rows[0]["cached_deterministic_goal"]["goal"])
            self.assertIsNone(rows[0]["cached_deterministic_goal"]["observed_at"])
            Path(path).unlink()
            rows = self.sessions_for(self.collect(build, when=self.NOW), key)
            self.assertIsNone(rows[0]["cached_deterministic_goal"])
            with config_patch(spacedock_enabled=False):
                self.assertFalse(self.collect(build, when=self.NOW)["spacedock_enabled"])

    def test_malformed_cached_goal_cannot_remove_any_board_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config, state = make_runtime(
                state_dir=Path(tmp), annotations_enabled=False, dismissals_enabled=False
            )
            spec = aggregate.HarnessSpec(
                key="pi",
                label="Pi",
                discover=lambda *_: True,
                collect=lambda *_: [
                    runtime_sessions.base_session("pi", sid, "example")
                    for sid in ("bad", "healthy")
                ],
            )
            app = aggregate.Application(
                config,
                state,
                (spec,),
                native_notifier=lambda *_: "",
                popup_notifier=lambda *_: None,
                diagnostic_sink=lambda *_: None,
            )
            path = observer.sidecar_path(config, "pi", "bad")
            assert path is not None
            corrupt = '{"unused":' + "[" * 30000 + "0" + "]" * 30000 + "}"
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(corrupt, encoding="utf-8")
            self.assertLess(Path(path).stat().st_size, config.state_read_cap_bytes)
            rows = app.collect(show_all=True)["sessions"]
            self.assertEqual({"bad", "healthy"}, {row["sid"] for row in rows})
            self.assertTrue(all(row["cached_deterministic_goal"] is None for row in rows))
            self.assertEqual(corrupt, Path(path).read_text(encoding="utf-8"))
