"""The focused outline groups recorded evidence without a model or word publication."""

from __future__ import annotations

import dataclasses
import http.client
import importlib
import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlparse

from compass_runtime import http_api, observer, summary_store
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from . import test_record_pages
from .support import make_server, poll_fast
from .test_claude_checks import Transcript


class SessionOutlineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "session.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.state = build_runtime_state(self.config, started=1)
        self.outline = importlib.import_module("compass_runtime.session_outline")
        self.source = importlib.import_module("compass_runtime.session_source")

    def test_blocks_include_leading_work_spans_counts_failures_and_folders(self) -> None:
        transcript = Transcript(self.root)
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.prompt("Change the synthetic module.")
        transcript.write(str(self.root / "src/a.py"))
        transcript.bash("mypy src", "1 error", is_error=True)
        transcript.prompt("Add another synthetic case.")
        transcript.save(self.path)
        page = self.source.read(self.config, str(self.path), "claude", "root")
        result = self.outline.build(page, self.config)
        self.assertEqual(("compass", "grouping"), (result["made_by"], result["basis"]))
        self.assertEqual(3, len(result["blocks"]))
        leading, middle, last = result["blocks"]
        self.assertIsNone(leading["prompt"])
        self.assertEqual(1, leading["counts"]["checks_failed"])
        self.assertEqual("failed", leading["failures"][0]["result"])
        self.assertEqual(3, middle["span"]["entries"])
        self.assertEqual([{"folder": "src", "files": 1}], middle["folders"])
        self.assertEqual(page.entries[-1].fact_id, last["span"]["last"])
        self.assertNotIn('"words":', json.dumps(result))

    def test_a_failing_run_followed_by_a_passing_run_of_the_same_check_is_fixed(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Write the failing test first, then make it pass.")
        transcript.bash("pytest tests/test_a.py", "1 failed", is_error=True)
        transcript.write(str(self.root / "src/a.py"))
        transcript.bash("pytest tests/test_a.py", "1 passed")
        transcript.prompt("Now lint it.")
        transcript.bash("ruff check .", "1 error", is_error=True)
        transcript.save(self.path)
        first, second = self.outline.build(
            self.source.read(self.config, str(self.path), "claude", "root"), self.config
        )["blocks"]
        self.assertEqual(
            (2, 0, 1),
            (
                first["counts"]["checks"],
                first["counts"]["checks_failed"],
                first["counts"]["checks_fixed"],
            ),
        )
        self.assertEqual([], first["failures"])
        # A check still red at the end of the read stays a failure.
        self.assertEqual(
            (1, 0), (second["counts"]["checks_failed"], second["counts"]["checks_fixed"])
        )
        self.assertEqual(["failed"], [row["result"] for row in second["failures"]])

    def test_a_fix_in_a_later_part_still_clears_the_earlier_failure(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Break it on purpose.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.prompt("Now fix it.")
        transcript.bash("pytest tests", "1 passed")
        transcript.save(self.path)
        first, second = self.outline.build(
            self.source.read(self.config, str(self.path), "claude", "root"), self.config
        )["blocks"]
        self.assertEqual(
            (0, 1), (first["counts"]["checks_failed"], first["counts"]["checks_fixed"])
        )
        self.assertEqual(
            (0, 0), (second["counts"]["checks_failed"], second["counts"]["checks_fixed"])
        )

    def test_a_check_that_failed_again_after_passing_is_failing_once(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Keep the suite green.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.bash("pytest tests", "1 passed")
        transcript.bash("pytest tests", "2 failed", is_error=True)
        transcript.bash("pytest tests", "3 failed", is_error=True)
        transcript.save(self.path)
        (block,) = self.outline.build(
            self.source.read(self.config, str(self.path), "claude", "root"), self.config
        )["blocks"]
        self.assertEqual(
            (1, 0), (block["counts"]["checks_failed"], block["counts"]["checks_fixed"])
        )
        self.assertEqual(1, len(block["failures"]))

    def test_a_prompt_longer_than_the_title_bound_is_cut_at_a_word_with_an_ellipsis(self) -> None:
        words = [f"word{n:03d}" for n in range(80)]
        # Every bound the cut could land on, so a cut inside a word cannot hide at one offset.
        for lead in range(9):
            with self.subTest(lead=lead):
                transcript = Transcript(self.root)
                transcript.prompt(("a" * lead + " " if lead else "") + " ".join(words))
                transcript.save(self.path)
                page = self.source.read(self.config, str(self.path), "claude", "root")
                (block,) = self.outline.build(page, self.config)["blocks"]
                title = block["prompt"]["title"]
                self.assertTrue(title.endswith("…"), title)
                kept = title.removesuffix("…").split()
                self.assertTrue(all(word in words or word == "a" * lead for word in kept), title)

    def test_a_check_still_failing_in_the_next_phase_is_listed_once(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Keep the suite green.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.prompt("Look at the lint.")
        transcript.bash("pytest tests", "2 failed", is_error=True)
        transcript.bash("ruff check .", "1 error", is_error=True)
        transcript.save(self.path)
        first, second = self.outline.build(
            self.source.read(self.config, str(self.path), "claude", "root"), self.config
        )["blocks"]
        self.assertEqual(1, len(first["failures"]))
        self.assertEqual(1, first["counts"]["checks_failed"])
        # The pytest failure is the first part's; this part lists only the check that is new.
        self.assertEqual(["ruff check ."], [row["title"] for row in second["failures"]])
        self.assertEqual(1, second["counts"]["checks_failed"])
        self.assertEqual(2, second["counts"]["checks"])

    def test_a_failure_fixed_after_two_phases_counts_as_fixed_once(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Break it.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.prompt("Still broken.")
        transcript.bash("pytest tests", "2 failed", is_error=True)
        transcript.bash("pytest tests", "1 passed")
        transcript.save(self.path)
        first, second = self.outline.build(
            self.source.read(self.config, str(self.path), "claude", "root"), self.config
        )["blocks"]
        self.assertEqual(
            1, first["counts"]["checks_fixed"] + second["counts"]["checks_fixed"], (first, second)
        )

    def test_a_failure_after_a_fix_is_a_new_failure_in_the_next_phase(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Break it.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.bash("pytest tests", "1 passed")
        transcript.prompt("Break it again.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.save(self.path)
        first, second = self.outline.build(
            self.source.read(self.config, str(self.path), "claude", "root"), self.config
        )["blocks"]
        self.assertEqual(
            (0, 1), (first["counts"]["checks_failed"], first["counts"]["checks_fixed"])
        )
        self.assertEqual(["pytest tests"], [row["title"] for row in second["failures"]])

    def test_a_failure_the_highlight_cap_dropped_is_listed_by_the_next_phase(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Run the checks.")
        transcript.bash("pytest tests/test_a.py", "1 failed", is_error=True)
        transcript.bash("pytest tests/test_b.py", "1 failed", is_error=True)
        transcript.prompt("Run them again.")
        transcript.bash("pytest tests/test_a.py", "1 failed", is_error=True)
        transcript.bash("pytest tests/test_b.py", "1 failed", is_error=True)
        transcript.save(self.path)
        config = dataclasses.replace(self.config, session_outline_highlights=1)
        first, second = self.outline.build(
            self.source.read(config, str(self.path), "claude", "root"), config
        )["blocks"]
        self.assertEqual(["pytest tests/test_b.py"], [row["title"] for row in first["failures"]])
        # The dropped one was never shown, so the next part still owes the reader a row for it.
        self.assertEqual(["pytest tests/test_a.py"], [row["title"] for row in second["failures"]])

    def test_the_server_cut_title_story_fixture_is_what_the_server_makes(self) -> None:
        # The ServerCutTitleEndsAtAWord story draws this title; reverting the cut turns it red here.
        fixture = json.loads(
            (Path(__file__).parents[4] / "frontend/test/fixtures/server-cut-title.json").read_text(
                encoding="utf-8"
            )
        )
        transcript = Transcript(self.root)
        transcript.prompt(fixture["prompt"])
        transcript.save(self.path)
        page = self.source.read(self.config, str(self.path), "claude", "root")
        (block,) = self.outline.build(page, self.config)["blocks"]
        self.assertEqual(fixture["title"], block["prompt"]["title"])

    def test_a_complete_title_of_exactly_the_bound_is_not_cut_again(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Fix " + "x" * 107 + ".")
        transcript.save(self.path)
        page = self.source.read(self.config, str(self.path), "claude", "root")
        (block,) = self.outline.build(page, self.config)["blocks"]
        title = block["prompt"]["title"]
        self.assertEqual(112, len(title))
        self.assertTrue(title.endswith("x."), title)

    def test_an_opening_failure_with_unread_work_after_it_is_unknown_not_failing(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Synthetic first request.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        for n in range(30):
            transcript.prompt(f"Synthetic later request {n}: {'pad ' * 40}")
            transcript.bash(f"ruff check {n}", "1 passed")
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=2500
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            result, _plan = self.outline.for_session_with_plan(config, self.state, "claude", "root")
        first = result["blocks"][0]
        self.assertTrue(first["opening"])
        self.assertEqual(
            (0, 1, []),
            (
                first["counts"]["checks_failed"],
                first["counts"]["checks_unknown"],
                first["failures"],
            ),
        )

    def test_an_opening_failure_fixed_in_a_group_the_head_read_dropped_is_unknown(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Synthetic first request.")
        transcript.bash("pytest tests", "1 failed", is_error=True)
        transcript.prompt("Synthetic second request.")
        transcript.bash("pytest tests", "1 passed")
        for n in range(30):
            transcript.prompt(f"Synthetic later request {n}: {'pad ' * 40}")
            transcript.bash(f"ruff check {n}", "1 passed")
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=1_000_000
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            result, _plan = self.outline.for_session_with_plan(config, self.state, "claude", "root")
        first = result["blocks"][0]
        self.assertTrue(first["opening"])
        self.assertEqual(
            (0, 1), (first["counts"]["checks_failed"], first["counts"]["checks_unknown"])
        )

    def test_the_head_read_spends_what_the_window_left_of_one_budget(self) -> None:
        self._large()
        config = dataclasses.replace(self.config, session_outline_max_bytes=6000)
        deadlines: list[float] = []
        real = self.source.read

        def spy(*args: Any, **kwargs: Any) -> Any:
            deadlines.append(kwargs["deadline"])
            return real(*args, **kwargs)

        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.source, "read", side_effect=spy),
        ):
            self.outline.for_session_with_plan(config, self.state, "claude", "root")
        self.assertEqual(2, len(deadlines))
        self.assertEqual(deadlines[0], deadlines[1])

    def test_block_cap_keeps_the_opening_and_the_newest_and_counts_dropped_blocks(self) -> None:
        self.path.write_text(
            "".join(
                json.dumps(test_record_pages.RecordPagesTest.record(i)) + "\n" for i in range(5)
            )
        )
        config = dataclasses.replace(self.config, session_outline_max_blocks=2)
        result = self.outline.build(
            self.source.read(config, str(self.path), "claude", "root"), config
        )
        self.assertEqual(2, result["more_blocks"])
        self.assertEqual(
            ["Build synthetic step 0.", "Build synthetic step 3.", "Build synthetic step 4."],
            [b["prompt"]["title"] for b in result["blocks"]],
        )
        self.assertEqual([True, False, False], [b["opening"] for b in result["blocks"]])

    def _large(self, prompts: int = 40) -> Transcript:
        transcript = Transcript(self.root)
        for n in range(prompts):
            transcript.prompt(f"Synthetic request number {n}: {'pad ' * 40}")
            transcript.bash(f"pytest tests/test_{n}.py", "1 passed")
        transcript.save(self.path)
        return transcript

    def test_a_session_larger_than_the_read_bound_still_has_a_phase_at_its_first_prompt(
        self,
    ) -> None:
        self._large()
        config = dataclasses.replace(self.config, session_outline_max_bytes=6000)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            result, _plan = self.outline.for_session_with_plan(config, self.state, "claude", "root")
        self.assertIn("before_window", [r["reason"] for r in result["coverage"]["unread"]])
        first, *rest = result["blocks"]
        self.assertTrue(first["opening"])
        self.assertTrue(first["prompt"]["title"].startswith("Synthetic request number 0:"))
        # The head read reached the second prompt, so the opening part is whole.
        self.assertFalse(first["partial"])
        self.assertEqual((1, 0), (first["counts"]["checks"], first["counts"]["checks_failed"]))
        self.assertTrue(rest)
        self.assertEqual([False] * len(rest), [b["opening"] for b in rest])
        self.assertTrue(rest[-1]["prompt"]["title"].startswith("Synthetic request number 39:"))
        self.assertNotIn('"words":', json.dumps(result))

    def test_the_opening_part_is_marked_partial_when_its_read_ends_inside_it(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("The only prompt, then a long run of work.")
        for n in range(60):
            transcript.bash(f"pytest tests/test_{n}.py", "1 passed" + " ok" * 40)
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=4000, session_outline_head_bytes=3000
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            result, _plan = self.outline.for_session_with_plan(config, self.state, "claude", "root")
        first, second = result["blocks"]
        self.assertEqual(
            ("The only prompt, then a long run of work.", True, True),
            (first["prompt"]["title"], first["opening"], first["partial"]),
        )
        # The newest window's own part has no prompt to name and is not the opening.
        self.assertEqual(
            (None, False, False), (second["prompt"], second["opening"], second["partial"])
        )
        self.assertLess(first["counts"]["checks"], 60)

    def test_a_first_prompt_past_the_head_budget_leaves_no_block_marked_as_the_opening(
        self,
    ) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Synthetic first request. " + "x " * 2000)
        transcript.bash("pytest tests/test_first.py", "1 passed")
        for n in range(30):
            transcript.prompt(f"Synthetic later request {n}: {'pad ' * 40}")
            transcript.bash(f"pytest tests/test_{n}.py", "1 passed")
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=1000
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            result, _plan = self.outline.for_session_with_plan(config, self.state, "claude", "root")
        self.assertGreater(result["coverage"]["start_offset"], 0)
        self.assertTrue(result["blocks"])
        self.assertEqual([False] * len(result["blocks"]), [b["opening"] for b in result["blocks"]])

    def test_a_read_that_starts_at_the_beginning_makes_no_head_read(self) -> None:
        self._large(3)
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.source, "read", wraps=self.source.read) as read,
        ):
            result, _plan = self.outline.for_session_with_plan(
                self.config, self.state, "claude", "root"
            )
        self.assertEqual(1, read.call_count)
        self.assertEqual([True, False, False], [b["opening"] for b in result["blocks"]])
        self.assertFalse(result["blocks"][0]["partial"])

    def test_highlights_are_bounded_and_counts_are_not(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Run synthetic checks.")
        for n in range(6):
            transcript.bash(f"pytest tests/test_{n}.py", "1 failed", is_error=True)
            transcript.write(str(self.root / f"folder{n}/a.py"))
        transcript.save(self.path)
        config = dataclasses.replace(self.config, session_outline_highlights=2)
        block = self.outline.build(
            self.source.read(config, str(self.path), "claude", "root"), config
        )["blocks"][0]
        self.assertEqual(6, block["counts"]["checks_failed"])
        for key in ("checks", "failures", "folders"):
            self.assertEqual(2, len(block[key]))

    def test_cache_reuses_object_and_rebuilds_after_append(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Read the synthetic record.")
        transcript.save(self.path)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first = self.outline.for_session(self.config, self.state, "claude", "root")
            with mock.patch.object(
                self.source, "read", side_effect=AssertionError("cache must stat only")
            ):
                self.assertIs(
                    first, self.outline.for_session(self.config, self.state, "claude", "root")
                )
            transcript.prompt("Read the next synthetic record.")
            transcript.save(self.path)
            later = self.outline.for_session(self.config, self.state, "claude", "root")
        self.assertIsNot(first, later)
        self.assertEqual(2, len(later["blocks"]))

    def test_plan_shares_outline_read_cache_and_config_invalidation(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Read the synthetic record.")
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config,
            session_summary_max_seconds=601,
            session_summary_max_calls=3,
            session_summary_call_timeout=61,
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            with mock.patch.object(self.source, "read", wraps=self.source.read) as read:
                outline, plan = self.outline.for_session_with_plan(
                    config, self.state, "claude", "root"
                )
                again, cached = self.outline.for_session_with_plan(
                    config, self.state, "claude", "root"
                )
                self.assertEqual(1, read.call_count)
                self.assertIs(outline, again)
                self.assertIs(plan, cached)
            assert plan is not None
            self.assertEqual(
                {"reason": None, "complete": True, "parts": 2, "windows": 1, "calls": 3},
                {key: plan[key] for key in ("reason", "complete", "parts", "windows", "calls")},
            )
            self.assertEqual(4, plan["minutes"])
            self.assertEqual(3, plan["largest_read"]["calls"])
            self.assertEqual(61, plan["largest_read"]["call_timeout"])
            changed = dataclasses.replace(config, session_summary_max_seconds=60)
            _, plan = self.outline.for_session_with_plan(changed, self.state, "claude", "root")
            self.assertEqual(1, plan["minutes"])
            self.assertNotIn('"words":', json.dumps(self.state.session_outlines))

    def test_plan_off_a_partial_read_counts_the_whole_job_call_ceiling(self) -> None:
        transcript = Transcript(self.root)
        for n in range(20):
            transcript.prompt(f"Read synthetic record number {n} with some padding words.")
        transcript.save(self.path)
        config = dataclasses.replace(self.config, session_outline_max_bytes=600)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            outline, plan = self.outline.for_session_with_plan(config, self.state, "claude", "root")
        self.assertFalse(outline["coverage"]["complete"])
        assert plan is not None
        self.assertFalse(plan["complete"])
        self.assertEqual(config.session_summary_max_calls, plan["calls"])
        self.assertEqual(
            math.ceil(
                min(
                    config.session_summary_max_calls * config.session_summary_call_timeout,
                    config.session_summary_max_seconds,
                )
                / 60
            ),
            plan["minutes"],
        )

    def test_time_clipped_outline_is_not_cached(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Read the synthetic record.")
        transcript.save(self.path)
        config = dataclasses.replace(self.config, session_outline_max_seconds=-1.0)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first = self.outline.for_session(config, self.state, "claude", "root")
            second = self.outline.for_session(config, self.state, "claude", "root")
        self.assertEqual("ok", first["state"])
        self.assertIn("time", [region["reason"] for region in first["coverage"]["unread"]])
        self.assertEqual({}, dict(self.state.session_outlines))
        self.assertIsNot(first, second)

    def test_unmatched_focus_keeps_the_outline_shape(self) -> None:
        built = self.outline.build(
            self.source.SourcePage("unavailable", "claude", "root"), self.config
        )
        result = self.outline.unmatched(self.config, "claude", "root")
        self.assertEqual(set(built), set(result))
        self.assertEqual(
            ("unavailable", "session_not_matched", "compass", "grouping", "claude"),
            (
                result["state"],
                result["reason"],
                result["made_by"],
                result["basis"],
                result["harness"],
            ),
        )

    def test_unsupported_does_not_resolve_or_stat(self) -> None:
        with mock.patch.object(
            observer, "resolve_transcript", side_effect=AssertionError("no disk")
        ):
            result = self.outline.for_session(self.config, self.state, "pi", "root")
        self.assertEqual(
            ("unsupported", "no_paged_record", []),
            (result["state"], result["reason"], result["blocks"]),
        )

    def test_cache_rebuilds_for_child_only_append(self) -> None:
        parent = Transcript(self.root)
        parent.prompt("Delegate synthetic checks.")
        parent.save(self.path)
        child = Transcript(self.root)
        child.bash("pytest tests", "1 passed")
        path = self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl"
        for row in child.rows:
            row["isSidechain"] = True
        child.save(path)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first = self.outline.for_session(self.config, self.state, "claude", "root")
            child.bash("pytest tests", "1 failed", is_error=True)
            for row in child.rows:
                row["isSidechain"] = True
            child.save(path)
            later = self.outline.for_session(self.config, self.state, "claude", "root")
        self.assertIsNot(first, later)
        self.assertEqual(1, sum(block["counts"]["checks_failed"] for block in later["blocks"]))

    def check_handler(self, handler: Any) -> None:
        application = handler.server.application
        application.config = self.config
        application.state = self.state
        row = {"harness": "claude", "sid": "root", "project": "synthetic"}
        application.collect_json = lambda **_: (1, json.dumps({"sessions": [row]}).encode())
        for harness in ("claude", "codex", "pi"):
            row["harness"] = harness
            self.path.write_text(
                json.dumps(test_record_pages.RecordPagesTest.record(1, harness=harness)) + "\n"
            )
            with (
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                mock.patch.object(
                    observer, "prepare_claude_exec", side_effect=AssertionError("no model")
                ) as claude,
                mock.patch.object(
                    observer, "codex_exec", side_effect=AssertionError("no model")
                ) as codex,
            ):
                with mock.patch.object(self.source, "read", wraps=self.source.read) as source_read:
                    result = self.request(
                        handler, f"/api/project-context?project=synthetic&session={harness}:root"
                    )
                self.assertEqual(0 if harness == "pi" else 1, source_read.call_count)
            self.assertEqual(0, claude.call_count + codex.call_count)
            summary = result["sources"]["summary"]
            if harness == "claude":
                plan = summary["plan"]
                # Two parts, two attempts each, at the default 180 s timeout; the 600 s job
                # ceiling caps the 720 s that would give.
                self.assertEqual(
                    {"complete": True, "parts": 2, "windows": 1, "calls": 4, "minutes": 10},
                    {
                        key: plan[key]
                        for key in ("complete", "parts", "windows", "calls", "minutes")
                    },
                )
                self.assertEqual(
                    self.config.session_summary_window_bytes,
                    plan["largest_read"]["window_bytes"],
                )
            else:
                self.assertIsNone(summary["plan"])
            outline = result["sources"]["outline"]
            self.assertEqual("unsupported" if harness == "pi" else "ok", outline["state"])
            if harness == "pi":
                self.assertEqual("no_paged_record", outline["reason"])
            else:
                self.assertEqual(1, len(outline["blocks"]))
                self.assertEqual(
                    "not_read" if harness == "codex" else "read",
                    outline["coverage"]["agent_replies"],
                )
            self.assertNotIn('"words":', json.dumps(outline))
        self.assertNotIn(
            "outline", self.request(handler, "/api/project-context?project=synthetic")["sources"]
        )

    def test_focused_http_plan_is_null_for_existing_or_unavailable_summary(self) -> None:
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = mock.Mock(application=mock.Mock())
        application = handler.server.application
        application.config = self.config
        application.state = self.state
        application.clock.return_value = 1_790_000_000.0
        row = {"harness": "claude", "sid": "root", "project": "synthetic"}
        application.collect_json = lambda **_: (1, json.dumps({"sessions": [row]}).encode())
        handler._local_ok = lambda: True
        handler._send = mock.Mock()
        transcript = Transcript(self.root)
        transcript.prompt("Inspect")
        transcript.save(self.path)
        for state, exists in (("ok", True), ("unavailable", False)):
            with (
                self.subTest(state=state),
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                mock.patch.object(
                    summary_store,
                    "for_session",
                    return_value={
                        "state": state,
                        "exists": exists,
                        "job": None,
                    },
                ),
            ):
                result = self.request(
                    handler, "/api/project-context?project=synthetic&session=claude:root"
                )
                self.assertIsNone(result["sources"]["summary"]["plan"])
        result = self.request(
            handler, "/api/project-context?project=synthetic&session=claude:missing"
        )
        self.assertIsNone(result["sources"]["summary"]["plan"])

    def request(self, handler: Any, path: str) -> Any:
        handler._project_context(urlparse(path))
        return json.loads(handler._send.call_args.args[0])

    def test_focused_http_handler_adds_outline_without_model_consent(self) -> None:
        handler: Any = object.__new__(http_api._RequestHandler)
        handler.server = mock.Mock(application=mock.Mock())
        handler.server.application.clock.return_value = 1_790_000_000.0
        handler._local_ok = lambda: True
        handler._send = mock.Mock()
        self.check_handler(handler)

    def test_focused_http_over_ephemeral_loopback(self) -> None:
        try:
            server = make_server()
        except PermissionError:
            self.skipTest("sandbox denies loopback socket binding")
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=poll_fast(server), daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(server.shutdown)
        handler = mock.Mock(server=server)

        def request(_handler: Any, path: str) -> Any:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
            self.addCleanup(connection.close)
            connection.request("GET", path)
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            return json.loads(response.read())

        with mock.patch.object(self, "request", side_effect=request):
            self.check_handler(handler)
