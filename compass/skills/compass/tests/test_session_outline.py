"""The focused outline groups recorded evidence without a model or word publication."""

from __future__ import annotations

import dataclasses
import hashlib
import http.client
import importlib
import json
import math
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from unittest import mock
from urllib.parse import urlparse

from compass_runtime import http_api, observer, project_scripts, reader_checks, summary_store
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from . import test_record_pages, test_session_source
from .support import make_server, poll_fast
from .test_claude_checks import Transcript, hook_stdout
from .test_project_script_checks import git, package

# How long a test waits for a poll that returns at once on an idle runner, and how long a
# held read waits to be released: longer, so a poll that blocks fails the wait instead.
WAIT_SEC = 30.0
HOLD_SEC = 2 * WAIT_SEC

if TYPE_CHECKING:
    from collections.abc import Iterator

# Outline reads run under the real 0.25 s budget, and the default-budget test measures that budget.
REAL_TIME_TESTS = True


class OutlineFactBoundsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.outline = importlib.import_module("compass_runtime.session_outline")
        self.source = importlib.import_module("compass_runtime.session_source")
        self.assertTrue(
            hasattr(self.outline, "_merge_facts"), "bounded word-free fact admission is missing"
        )

    def observation(
        self,
        fact_id: str = "check-1",
        *,
        offset: int = 10,
        authority: tuple[int, int] = (0, 10),
        result: str | None = "failed",
        at: float = 100,
        retired: bool = False,
    ) -> Any:
        entry = self.source.SourceEntry(
            fact_id,
            "fingerprint",
            "check",
            "agent",
            "parent",
            at,
            "pytest tests",
            result=result,
            path="src/a.py",
            folder="src",
            subject="pytest tests",
            words="PRIVATE-WORDS-SENTINEL " * 1000,
        )
        return self.outline._FactObservation(
            fact_id, None if retired else entry, (offset, 0, 0), authority
        )

    def test_retained_facts_strip_words_and_projection_preserves_display_fields(self) -> None:
        observation = self.observation()
        result = self.outline._merge_facts(None, [observation])
        self.assertFalse(result.limited)
        fact = result.graph.facts["check-1"]
        self.assertFalse(hasattr(fact, "words"))
        projected = self.outline._ordered_entries(result.graph)
        self.assertEqual((dataclasses.replace(observation.entry, words=None),), projected)
        self.assertNotIn("PRIVATE-WORDS-SENTINEL", repr(result.graph))
        self.assertIsNot(observation.entry, fact)
        pending = [result.graph]
        seen: set[int] = set()
        while pending:
            value = pending.pop()
            if id(value) in seen:
                continue
            seen.add(id(value))
            self.assertNotIsInstance(
                value,
                (
                    self.source.SourceEntry,
                    self.source.SourcePage,
                    self.source.SourceCursor,
                    self.source.SourceSnapshot,
                    bytes,
                ),
            )
            if dataclasses.is_dataclass(value):
                for field in dataclasses.fields(value):
                    self.assertNotIn(field.name, {"words", "input", "raw", "fragment"})
                    pending.append(getattr(value, field.name))
            elif isinstance(value, (dict, MappingProxyType)):
                pending.extend(value.keys())
                pending.extend(value.values())
            elif isinstance(value, (tuple, list)):
                pending.extend(value)
            elif isinstance(value, str):
                self.assertNotIn("PRIVATE-WORDS-SENTINEL", value)

    def test_source_metadata_is_joined_by_fact_id_in_any_mapping_order(self) -> None:
        first, second = self.observation("first").entry, self.observation("second").entry
        page = self.source.SourcePage(
            "ok",
            "claude",
            "root",
            (first, second),
            positions=(("second", (20, 0, 0)), ("first", (10, 0, 0))),
            observations=(("first", 30), ("second", 40)),
        )
        observations = tuple(self.outline._observations(page))
        self.assertEqual(
            [("first", (10, 0, 0), (0, 30)), ("second", (20, 0, 0), (0, 40))],
            [(item.fact_id, item.position, item.authority) for item in observations],
        )
        for changes in (
            {"positions": (("first", (10, 0, 0)), ("first", (20, 0, 0)))},
            {"positions": (("first", (10, 0, 0)),)},
            {"observations": (("first", 30), ("other", 40))},
            {"observations": (("first", 30), ("first", 40))},
            {"observations": (("first", 30), ("second", -1))},
            {"entries": (first, first)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                tuple(self.outline._observations(dataclasses.replace(page, **changes)))

    def test_older_pass_and_unknown_cannot_downgrade_newer_failure(self) -> None:
        first = self.outline._merge_facts(None, [self.observation(authority=(0, 100))])
        for status in ("passed", None):
            with self.subTest(status=status):
                later = self.outline._merge_facts(
                    first.graph, [self.observation(authority=(0, 20), result=status)]
                )
                self.assertEqual("failed", later.graph.facts["check-1"].result)
                self.assertEqual((0, 100), later.graph.facts["check-1"].authority)

    def test_replacement_and_empty_replacement_retire_without_resurrection(self) -> None:
        first = self.outline._merge_facts(None, [self.observation()])
        replaced = self.outline._merge_facts(
            first.graph,
            [
                self.observation(retired=True, authority=(0, 50)),
                self.observation("renamed", authority=(0, 50), result="passed"),
            ],
        )
        self.assertEqual(["renamed"], list(replaced.graph.facts))
        replay = self.outline._merge_facts(replaced.graph, [self.observation()])
        self.assertEqual(["renamed"], list(replay.graph.facts))
        empty = self.outline._merge_facts(
            replay.graph,
            [
                self.observation("renamed", retired=True, authority=(1, 0)),
                self.observation("never-emitted", retired=True, authority=(1, 0)),
            ],
        )
        self.assertEqual({}, dict(empty.graph.facts))
        self.assertEqual({"check-1", "renamed", "never-emitted"}, set(empty.graph.retired))
        fresh = self.outline._merge_facts(
            empty.graph, [self.observation("renamed", authority=(1, 1), result="passed")]
        )
        self.assertEqual("passed", fresh.graph.facts["renamed"].result)

    def test_projection_uses_physical_order_despite_backward_timestamps(self) -> None:
        result = self.outline._merge_facts(
            None,
            [
                self.observation("last", offset=20, at=1, result="passed"),
                self.observation("first", offset=10, at=100),
            ],
        )
        entries = self.outline._ordered_entries(result.graph)
        self.assertEqual(["first", "last"], [entry.fact_id for entry in entries])
        self.assertEqual({"first"}, self.outline._runs(entries).fixed)

    def test_retirement_wins_an_equal_authority_replay(self) -> None:
        prior = self.outline._merge_facts(None, [self.observation()])
        result = self.outline._merge_facts(
            prior.graph,
            [
                self.observation(retired=True),
                self.observation(),
            ],
        )
        self.assertEqual({}, dict(result.graph.facts))
        self.assertEqual({"check-1": (0, 10)}, dict(result.graph.retired))

    def test_oversized_display_field_is_refused_before_retention(self) -> None:
        prior = self.outline._merge_facts(None, [self.observation()])
        observation = self.observation("large")
        observation = dataclasses.replace(
            observation,
            entry=dataclasses.replace(observation.entry, title="long display title " * 10_000),
        )
        result = self.outline._merge_facts(
            prior.graph, [observation], limits=self.outline._FactLimits(bytes=20_000)
        )
        self.assertTrue(result.limited)
        self.assertIs(prior.graph, result.graph)

    def test_byte_object_and_fact_refusals_preserve_previous_graph_and_frontier(self) -> None:
        prior = self.outline._merge_facts(None, [self.observation()], extras={"frontier": 10})
        for limits in (
            self.outline._FactLimits(bytes=1),
            self.outline._FactLimits(objects=1),
            self.outline._FactLimits(facts=1),
        ):
            with self.subTest(limits=limits):
                refused = self.outline._merge_facts(
                    prior.graph,
                    [self.observation("second")],
                    extras={"frontier": 100},
                    limits=limits,
                )
                self.assertTrue(refused.limited)
                self.assertEqual("outline_state_limit", refused.reason)
                self.assertIs(prior.graph, refused.graph)
                self.assertEqual({"frontier": 10}, refused.graph.extras)
                self.assertEqual(["check-1"], list(prior.graph.facts))

    def test_answer_plan_and_checkpoint_share_the_admission_budget(self) -> None:
        for extras in (
            {"answer": {"blocks": ["answer" * 1000]}},
            {"plan": {"windows": [str(index) for index in range(1000)]}},
            {"checkpoint": MappingProxyType({str(index): index for index in range(1000)})},
        ):
            with self.subTest(key=next(iter(extras))):
                result = self.outline._merge_facts(
                    None,
                    [self.observation()],
                    extras=extras,
                    limits=self.outline._FactLimits(bytes=4000, objects=100),
                )
                self.assertTrue(result.limited)
                self.assertIsNone(result.graph)

    def test_tombstones_are_bounded_and_candidates_stop_at_first_refusal(self) -> None:
        seen: list[int] = []

        def changes() -> Iterator[Any]:
            for index in range(100):
                seen.append(index)
                yield self.observation(str(index), retired=True)

        result = self.outline._merge_facts(
            None, changes(), limits=self.outline._FactLimits(facts=2)
        )
        self.assertTrue(result.limited)
        self.assertEqual([0, 1, 2], seen)
        self.assertIsNone(result.graph)

    def test_actual_retained_graph_has_no_source_payload_objects(self) -> None:
        for forbidden in (
            self.observation().entry,
            self.source.SourcePage("ok", "claude", "root"),
            b"PRIVATE-RAW-FRAGMENT",
            {"input": "PRIVATE-INPUT-SENTINEL"},
            {"words": "PRIVATE-WORDS-SENTINEL"},
        ):
            with self.subTest(kind=type(forbidden).__name__):
                result = self.outline._merge_facts(None, [], extras=forbidden)
                self.assertTrue(result.limited)
                self.assertIsNone(result.graph)

    def test_input_json_mapping_cannot_enter_retained_extras(self) -> None:
        result = self.outline._merge_facts(
            None, (), extras={"input_json": "owned raw command sentinel"}
        )
        self.assertTrue(result.limited)
        self.assertIsNone(result.graph)

    def test_pending_call_cannot_enter_retained_extras(self) -> None:
        pending = self.source.PendingCall(
            "parent",
            100,
            "/synthetic",
            "call-1",
            "Bash",
            '{"command":"owned raw command sentinel"}',
        )
        result = self.outline._merge_facts(None, (), extras=pending)
        self.assertTrue(result.limited)
        self.assertIsNone(result.graph)

    def test_measurement_counts_slots_dicts_keys_proxies_and_fixed_hash_state(self) -> None:
        @dataclasses.dataclass
        class Checkpoint:
            digest: object
            locators: object

        small = Checkpoint(hashlib.sha256(), MappingProxyType({"position": (10, 20)}))
        allowed = self.outline._merge_facts(None, [self.observation()], extras=small)
        self.assertFalse(allowed.limited)
        for payload in (
            Checkpoint(hashlib.sha256(), {"large-key" * 1000: None}),
            MappingProxyType({"key": "large-value" * 1000}),
            list(range(1000)),
        ):
            with self.subTest(kind=type(payload).__name__):
                self.assertIsNone(
                    self.outline._measure_facts(
                        payload, self.outline._FactLimits(bytes=3000, objects=100)
                    )
                )


class SessionOutlineTest(unittest.TestCase):
    def setUp(self) -> None:
        test_session_source.stop_the_clock(self)
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

    def test_a_fix_in_an_admitted_hidden_opening_group_stays_known(self) -> None:
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
            (0, 0), (first["counts"]["checks_failed"], first["counts"]["checks_unknown"])
        )
        self.assertEqual(1, first["counts"]["checks_fixed"])

    def test_all_parent_poll_reads_share_one_actual_byte_allowance(self) -> None:
        self._large()
        config = dataclasses.replace(self.config, session_outline_max_bytes=6000)
        meter = test_session_source.SessionSourceTest()
        meter.source = self.source
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            meter._meter_source_reads() as reads,
        ):
            for _poll in range(4):
                before = reads[0]
                result, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
                self.assertGreater(reads[0] - before, 0)
                self.assertLessEqual(reads[0] - before, 6000)
                self.assertTrue(result["blocks"][0]["opening"])

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
        self.assertTrue(result["coverage"]["unread"])
        self.assertGreater(result["coverage"]["unread"][0]["start_offset"], 0)
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
            mock.patch.object(
                self.source, "_read_outline", wraps=self.source._read_outline
            ) as read,
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
                self.source, "_read_outline", side_effect=AssertionError("cache must stat only")
            ):
                self.assertIs(
                    first, self.outline.for_session(self.config, self.state, "claude", "root")
                )
            transcript.prompt("Read the next synthetic record.")
            transcript.save(self.path)
            later = self.outline.for_session(self.config, self.state, "claude", "root")
        self.assertIsNot(first, later)
        self.assertEqual(2, len(later["blocks"]))

    def test_unchanged_bounded_polls_keep_opening_and_fill_missing_middle(self) -> None:
        transcript = Transcript(self.root)
        for number in range(12):
            transcript.prompt(f"Synthetic phase {number}: {'pad ' * 40}")
            transcript.bash(f"pytest tests/test_{number}.py", "1 passed")
            transcript.write(str(self.root / f"src/file_{number}.py"))
        transcript.save(self.path)
        size = self.path.stat().st_size
        config = dataclasses.replace(
            self.config,
            session_outline_max_bytes=6000,
            session_outline_head_bytes=1800,
            session_outline_max_seconds=30,
            session_outline_max_blocks=64,
            session_source_page_max_seconds=30,
        )
        self.assertGreater(size, 3 * config.session_outline_max_bytes)
        self.assertLess(max(map(len, self.path.read_bytes().splitlines())), 1500)
        whole = self.source.read(config, str(self.path), "claude", "root", max_bytes=size + 1)
        self.assertTrue(whole.coverage.complete)
        expected = self.outline.build(whole, config)
        self.assertEqual(12, sum(block["counts"]["checks"] for block in expected["blocks"]))
        self.assertEqual(12, sum(block["counts"]["files"] for block in expected["blocks"]))
        opening_id = expected["blocks"][0]["prompt"]["fact_id"]
        newest_id = expected["blocks"][-1]["prompt"]["fact_id"]

        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
            self.assertFalse(first["coverage"]["complete"])
            self.assertTrue(first["blocks"][0]["opening"])
            remaining = sum(
                region["end_offset"] - region["start_offset"]
                for region in first["coverage"]["unread"]
                if region["stream"] == "parent"
            )
            self.assertGreater(remaining, 0)
            result = first
            for _poll in range(100):
                prompt_ids = {
                    block["prompt"]["fact_id"] for block in result["blocks"] if block["prompt"]
                }
                self.assertTrue({opening_id, newest_id} <= prompt_ids)
                missing = sum(
                    region["end_offset"] - region["start_offset"]
                    for region in result["coverage"]["unread"]
                    if region["stream"] == "parent"
                )
                self.assertLessEqual(missing, remaining)
                remaining = missing
                if result["coverage"]["complete"]:
                    break
                result, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
            self.assertTrue(
                result["coverage"]["complete"],
                f"unchanged bounded polls never filled the missing middle: {remaining} bytes unread",
            )
            self.assertEqual([], result["coverage"]["unread"])
            self.assertEqual(expected["blocks"], result["blocks"])
            self.assertEqual(12, sum(block["counts"]["checks"] for block in result["blocks"]))
            self.assertEqual(12, sum(block["counts"]["files"] for block in result["blocks"]))
            again, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
            self.assertIs(result, again)
            self.assertEqual(expected["blocks"], again["blocks"])

    def test_impossible_retained_metadata_limit_never_retries_source_reads(self) -> None:
        self._large()
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.outline, "_FACT_LIMITS", self.outline._FactLimits(bytes=1)),
            mock.patch.object(
                self.source, "_read_outline", wraps=self.source._read_outline
            ) as read,
        ):
            for _poll in range(3):
                answer, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
                self.assertEqual("outline_state_limit", answer["reason"])
                self.assertFalse(answer["coverage"]["complete"])
            self.assertEqual(0, read.call_count)

    def test_refused_parent_growth_keeps_known_facts_and_stops_unchanged_reads(self) -> None:
        self._large()
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=1800
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
            graph = next(iter(self.state.session_outlines.values()))
            before = graph.extras.checkpoint
            limits = dataclasses.replace(self.outline._FACT_LIMITS, facts=len(graph.facts))
            with mock.patch.object(self.outline, "_FACT_LIMITS", limits):
                limited, _ = self.outline.for_session_with_plan(
                    config, self.state, "claude", "root"
                )
                self.assertEqual("outline_state_limit", limited["reason"])
                self.assertEqual(first["blocks"], limited["blocks"])
                retained = next(iter(self.state.session_outlines.values()))
                self.assertIs(before, retained.extras.checkpoint)
                self.assertIsNotNone(self.outline._measure_facts(retained, limits))
                with mock.patch.object(
                    self.source,
                    "_read_outline",
                    side_effect=AssertionError("unchanged refusal must not read"),
                ):
                    again, _ = self.outline.for_session_with_plan(
                        config, self.state, "claude", "root"
                    )
                self.assertIs(limited, again)

    def test_parent_cache_graph_retains_no_transcript_payload_objects(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Synthetic opening. " + "PRIVATE-UNRETAINED-SENTINEL " * 100)
        transcript.call("Bash", {"command": "pytest tests", "private": "PRIVATE-INPUT-SENTINEL"})
        for number in range(20):
            transcript.prompt(f"Later {number}. " + "padding " * 50)
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=4000
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            self.outline.for_session_with_plan(config, self.state, "claude", "root")
        graph = next(iter(self.state.session_outlines.values()))
        self.assertIsNotNone(self.outline._measure_facts(graph, self.outline._FACT_LIMITS))
        self.assertNotIn("PRIVATE-INPUT-SENTINEL", repr(graph))
        self.assertNotIn("PRIVATE-UNRETAINED-SENTINEL " * 10, repr(graph))
        pending = [graph]
        while pending:
            value = pending.pop()
            self.assertNotIsInstance(
                value,
                (
                    self.source.SourcePage,
                    self.source.SourceEntry,
                    self.source.SourceCursor,
                    self.source.SourceSnapshot,
                    bytes,
                ),
            )
            if dataclasses.is_dataclass(value):
                for field in dataclasses.fields(value):
                    self.assertNotIn(field.name, {"words", "input_json", "fragment"})
                    pending.append(getattr(value, field.name))
            elif isinstance(value, (dict, MappingProxyType)):
                pending.extend(value.values())
            elif isinstance(value, (tuple, list)):
                pending.extend(value)

    def _declaration_record(self, **scripts: str) -> Transcript:
        project_scripts.reset()
        self.addCleanup(project_scripts.reset)
        self.config = dataclasses.replace(
            self.config,
            git_probe_enabled=True,
            session_outline_max_bytes=4000,
            session_outline_head_bytes=1400,
            session_outline_max_blocks=64,
        )
        git(self.root, "init", "-q")
        (self.root / "package.json").write_text(package(**scripts))
        git(self.root, "add", "package.json")
        git(self.root, "commit", "-q", "-m", "owned base")
        transcript = Transcript(self.root)
        transcript.prompt("Owned classification reconciliation.")
        return transcript

    def _settle_declaration_outline(self) -> list[dict[str, Any]]:
        whole = self.source.read(self.config, str(self.path), "claude", "root", max_bytes=100000)
        self.assertTrue(whole.coverage.complete)
        expected = self.outline.build(whole, self.config)
        meter = test_session_source.SessionSourceTest()
        meter.source = self.source
        answers = []
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            meter._meter_source_reads() as reads,
        ):
            for _poll in range(100):
                before = reads[0]
                answer, plan = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
                self.assertLessEqual(reads[0] - before, self.config.session_outline_max_bytes)
                answers.append(answer)
                if answer["coverage"]["complete"]:
                    break
            self.assertTrue(answer["coverage"]["complete"], "classification replay never settled")
            self.assertEqual(expected["blocks"], answer["blocks"])
            self.assertIsNotNone(plan)
            self.assertFalse(plan["complete"])
            before = reads[0]
            again, _ = self.outline.for_session_with_plan(self.config, self.state, "claude", "root")
            self.assertIs(answer, again)
            self.assertEqual(before, reads[0])
        graph = next(iter(self.state.session_outlines.values()))
        self.assertIsNotNone(self.outline._measure_facts(graph, self.outline._FACT_LIMITS))
        for forbidden in ("input_json", "words=", "fragment=", "SourcePage(", "SourceCursor("):
            self.assertNotIn(forbidden, repr(graph))
        return answers

    def test_cached_late_parent_head_matches_all_canonical_fields_and_order(self) -> None:
        self._declaration_record(typecheck="tsc --noEmit")
        for missing in ("cwd", "timestamp"):
            self.state = build_runtime_state(self.config, started=1)
            transcript = Transcript(self.root)
            transcript.prompt("Owned late head.")
            if missing == "cwd":
                transcript.bash(f"cd {self.root} && pnpm typecheck", "1 passed")
                transcript.write(str(self.root / "src/early.py"))
                transcript.bash("pytest tests/direct.py", "1 passed")
            for number in range(55):
                transcript.prompt(f"Before metadata {number}. " + "padding " * 20)
            for row in transcript.rows:
                row.pop(missing, None)
            transcript.prompt("First canonical metadata.")
            for number in range(8):
                transcript.prompt(f"After metadata {number}. " + "padding " * 20)
            transcript.save(self.path)
            if missing == "timestamp":
                child = Transcript(self.root)
                child.bash("pnpm typecheck", "1 passed")
                child.write(str(self.root / "src/child.py"))
                for row in child.rows:
                    row["isSidechain"] = True
                child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
            with self.subTest(missing=missing):
                self._settle_declaration_outline()
                whole = self.source.read(
                    self.config, str(self.path), "claude", "root", max_bytes=100000
                )
                graph = next(iter(self.state.session_outlines.values()))
                self.assertEqual(
                    tuple(dataclasses.replace(entry, words=None) for entry in whole.entries),
                    self.outline._ordered_entries(graph),
                )

    def test_cached_declaration_withdrawal_matches_whole_source_after_replay(self) -> None:
        transcript = self._declaration_record(typecheck="tsc --noEmit")
        transcript.bash("pnpm typecheck; pytest tests/direct.py", "1 passed")
        transcript.write(str(self.root / "src/keep.py"))
        for number in range(6):
            transcript.prompt(f"Before declaring write {number}. " + "padding " * 80)
        transcript.write(str(self.root / "package.json"))
        for number in range(6):
            transcript.prompt(f"After declaring write {number}. " + "padding " * 80)
        transcript.bash("pnpm typecheck", "1 passed")
        transcript.save(self.path)
        answers = self._settle_declaration_outline()
        self.assertTrue(
            any(
                check["title"] == "pnpm typecheck"
                for block in answers[0]["blocks"]
                for check in block["checks"]
            )
        )
        self.assertEqual(
            ["pytest tests/direct.py"],
            [check["title"] for block in answers[-1]["blocks"] for check in block["checks"]],
        )
        self.assertEqual(2, sum(block["counts"]["files"] for block in answers[-1]["blocks"]))

    def test_cached_withdrawal_restores_a_previously_unemitted_check(self) -> None:
        transcript = self._declaration_record(test="echo skipped")
        transcript.bash("pnpm test", "1 passed")
        for number in range(6):
            transcript.prompt(f"Before declaration removal {number}. " + "padding " * 80)
        transcript.write(str(self.root / "package.json"))
        for number in range(6):
            transcript.prompt(f"After declaration removal {number}. " + "padding " * 80)
        transcript.save(self.path)
        answers = self._settle_declaration_outline()
        self.assertFalse(any(block["checks"] for block in answers[0]["blocks"]))
        self.assertEqual(
            ["pnpm test"],
            [check["title"] for block in answers[-1]["blocks"] for check in block["checks"]],
        )

    def test_cached_withdrawal_preserves_unaffected_latest_failure(self) -> None:
        transcript = self._declaration_record(typecheck="tsc --noEmit")
        self.config = dataclasses.replace(self.config, session_outline_max_bytes=6000)
        direct = transcript.call("Bash", {"command": "pytest tests/direct.py"})
        transcript.bash("pnpm typecheck", "1 passed")
        for number in range(4):
            transcript.prompt(f"Before earlier result {number}. " + "padding " * 80)
        transcript.result(direct, "1 passed")
        transcript.write(str(self.root / "package.json"))
        for number in range(10):
            transcript.prompt(f"Before tail failure {number}. " + "padding " * 80)
        transcript.result(direct, "Exit code 1\n1 failed", is_error=True)
        transcript.prompt("After the latest direct result. " + "padding " * 130)
        transcript.save(self.path)
        for answer in self._settle_declaration_outline():
            self.assertEqual(
                ["failed"],
                [
                    check["result"]
                    for block in answer["blocks"]
                    for check in block["checks"]
                    if check["title"] == "pytest tests/direct.py"
                ],
            )

    def test_cached_replayed_call_accepts_a_later_result(self) -> None:
        transcript = self._declaration_record(typecheck="tsc --noEmit")
        call = transcript.call("Bash", {"command": "pnpm typecheck"})
        for number in range(6):
            transcript.prompt(f"Before unrelated withdrawal {number}. " + "padding " * 80)
        transcript.write(str(self.root / reader_checks.FILENAME))
        for number in range(10):
            transcript.prompt(f"Before later result {number}. " + "padding " * 80)
        transcript.result(call, "1 passed")
        for number in range(8):
            transcript.prompt(f"After later result {number}. " + "padding " * 80)
        transcript.save(self.path)
        answers = self._settle_declaration_outline()
        results = [
            [check["result"] for block in answer["blocks"] for check in block["checks"]]
            for answer in answers
        ]
        self.assertIn(["not-recorded"], results)
        self.assertEqual(["passed"], results[-1])
        graph = next(iter(self.state.session_outlines.values()))
        checks = [fact for fact in graph.facts.values() if fact.kind == "check"]
        self.assertTrue(checks)
        self.assertTrue(all(fact.authority[0] > 0 for fact in checks))

    def test_cached_native_eof_keeps_polling_until_classification_settles(self) -> None:
        transcript = self._declaration_record(typecheck="tsc --noEmit")
        transcript.bash("pnpm typecheck", "1 passed")
        transcript.prompt("Pad 0. " + "padding " * 50)
        transcript.write(str(self.root / "package.json"))
        transcript.prompt("Final. " + "padding " * 200)
        transcript.save(self.path)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            self.outline.for_session_with_plan(self.config, self.state, "claude", "root")
            pending, _ = self.outline.for_session_with_plan(
                self.config, self.state, "claude", "root"
            )
            graph = next(iter(self.state.session_outlines.values()))
            checkpoint = graph.extras.checkpoint
            self.assertEqual(checkpoint.stamp[2], checkpoint.frontier.offset)
            self.assertTrue(checkpoint.replay)
            self.assertFalse(pending["coverage"]["complete"])
            self.assertIn(
                "classification_pending", [gap["reason"] for gap in pending["coverage"]["unread"]]
            )
        answers = self._settle_declaration_outline()
        self.assertFalse(any(block["checks"] for block in answers[-1]["blocks"]))
        graph = next(iter(self.state.session_outlines.values()))
        self.assertTrue(graph.retired)
        self.assertTrue(all(authority[0] > 0 for authority in graph.retired.values()))

    def test_cached_dependency_limit_is_terminal_without_claiming_completion(self) -> None:
        transcript = self._declaration_record(typecheck="tsc --noEmit")
        transcript.bash("pnpm typecheck", "1 passed")
        transcript.save(self.path)
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.source, "_OUTLINE_DEPENDENCY_LIMIT", 0),
        ):
            answer, _ = self.outline.for_session_with_plan(
                self.config, self.state, "claude", "root"
            )
            self.assertFalse(answer["coverage"]["complete"])
            self.assertIn(
                "outline_dependency_limit", [gap["reason"] for gap in answer["coverage"]["unread"]]
            )
            with mock.patch.object(
                self.source,
                "_read_outline",
                side_effect=AssertionError("terminal refusal must not reread"),
            ):
                again, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertIs(answer, again)

    def test_cold_later_failure_survives_revisiting_earlier_pass(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Run the owned check.")
        call = transcript.call("Bash", {"command": "pytest tests"})
        for number in range(4):
            transcript.prompt(f"Before first result {number}. " + "padding " * 50)
        transcript.result(call, "1 passed", is_error=False)
        for number in range(8):
            transcript.prompt(f"Before latest result {number}. " + "padding " * 50)
        transcript.result(call, "Exit code 1\n1 failed", is_error=True)
        transcript.prompt("After the last result. " + "padding " * 130)
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=1800
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for _poll in range(20):
                answer, plan = self.outline.for_session_with_plan(
                    config, self.state, "claude", "root"
                )
                checks = [check for block in answer["blocks"] for check in block["checks"]]
                self.assertEqual(["failed"], [check["result"] for check in checks])
                if answer["coverage"]["complete"]:
                    break
            self.assertTrue(answer["coverage"]["complete"])
            self.assertIsNotNone(plan)
            self.assertFalse(plan["complete"])

    def test_cold_denial_tombstone_prevents_replayed_call_resurrection(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Run the owned check.")
        call = transcript.call("Bash", {"command": "pytest tests"})
        for number in range(4):
            transcript.prompt(f"Before first result {number}. " + "padding " * 50)
        transcript.result(call, "1 passed", is_error=False)
        for number in range(8):
            transcript.prompt(f"Before latest result {number}. " + "padding " * 50)
        transcript.result(call, "Permission denied by reader.", is_error=True)
        transcript.prompt("After the last result. " + "padding " * 130)
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=1800
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for _poll in range(20):
                answer, plan = self.outline.for_session_with_plan(
                    config, self.state, "claude", "root"
                )
                checks = [check for block in answer["blocks"] for check in block["checks"]]
                self.assertEqual([], checks)
                if answer["coverage"]["complete"]:
                    break
            self.assertTrue(answer["coverage"]["complete"])
            self.assertIsNotNone(plan)
            self.assertFalse(plan["complete"])

    @contextmanager
    def _blocked_poll(self, config: Any = None) -> Iterator[tuple[Any, Any, list[str]]]:
        entered, release = threading.Event(), threading.Event()
        calls: list[str] = []
        real = self.source._read_outline

        def blocked(*args: Any, **kwargs: Any) -> Any:
            calls.append(args[3])
            result = real(*args, **kwargs)
            if len(calls) == 1:
                entered.set()
                if not release.wait(HOLD_SEC):
                    raise AssertionError("owned read barrier timed out")
            return result

        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.source, "_read_outline", side_effect=blocked),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(
                self.outline.for_session_with_plan,
                config or self.config,
                self.state,
                "claude",
                "root",
            )
            try:
                self.assertTrue(entered.wait(WAIT_SEC))
                yield pool, first, calls
            finally:
                release.set()
                first.result(timeout=WAIT_SEC)

    def test_same_session_cold_poll_is_singleflight_and_truthfully_busy(self) -> None:
        self._large(2)
        with self._blocked_poll() as (pool, first, calls):
            second = pool.submit(
                self.outline.for_session_with_plan, self.config, self.state, "claude", "root"
            )
            pending, plan = second.result(timeout=WAIT_SEC)
            self.assertEqual(("unavailable", "outline_busy"), (pending["state"], pending["reason"]))
            self.assertIsNone(pending["coverage"])
            self.assertIsNone(plan)
            self.assertEqual(["root"], calls)
        self.assertEqual("ok", first.result()[0]["state"])
        self.assertEqual(0, self.state.session_outline_active)

    def test_same_session_busy_poll_returns_prior_accepted_progress_promptly(self) -> None:
        self._large()
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=6000, session_outline_head_bytes=1800
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            accepted = self.outline.for_session_with_plan(config, self.state, "claude", "root")
        with self._blocked_poll(config) as (pool, _first, calls):
            second = pool.submit(
                self.outline.for_session_with_plan, config, self.state, "claude", "root"
            )
            answer = second.result(timeout=WAIT_SEC)
            self.assertIs(accepted[0], answer[0])
            self.assertIs(accepted[1], answer[1])
            self.assertEqual(["root"], calls)

    def test_config_replacement_fences_late_result_and_publication(self) -> None:
        self._large(2)
        changed = dataclasses.replace(
            self.config,
            session_summary_attempts_per_part=self.config.session_summary_attempts_per_part + 1,
        )
        with self._blocked_poll() as (pool, first, calls):
            second = pool.submit(
                self.outline.for_session_with_plan, changed, self.state, "claude", "root"
            )
            self.assertEqual("outline_busy", second.result(timeout=WAIT_SEC)[0]["reason"])
            self.assertEqual(["root"], calls)
        self.assertEqual("stale", first.result()[0]["state"])
        self.assertEqual({}, self.state.session_outlines)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            current = self.outline.for_session_with_plan(changed, self.state, "claude", "root")
        self.assertEqual("ok", current[0]["state"])
        self.assertEqual(0, self.state.session_outline_active)

    def test_source_replacement_fences_late_result_and_publication(self) -> None:
        self._large(2)
        with self._blocked_poll() as (pool, first, _calls):
            replacement = Transcript(self.root)
            replacement.prompt("Replacement source generation.")
            replacement.save(self.path)
            second = pool.submit(
                self.outline.for_session_with_plan, self.config, self.state, "claude", "root"
            )
            self.assertEqual("outline_busy", second.result(timeout=WAIT_SEC)[0]["reason"])
        self.assertEqual("stale", first.result()[0]["state"])
        self.assertEqual({}, self.state.session_outlines)

    def test_evicted_slot_cannot_publish_or_return_over_recreated_slot(self) -> None:
        self._large(2)
        with self._blocked_poll() as (pool, first, calls):
            with self.state.session_outline_lock:
                self.state.session_outline_slots.clear()
                self.state.session_outlines.clear()
            second = pool.submit(
                self.outline.for_session_with_plan, self.config, self.state, "claude", "root"
            )
            newer = second.result(timeout=WAIT_SEC)
            self.assertEqual("ok", newer[0]["state"])
            self.assertEqual(["root", "root"], calls)
        self.assertEqual("stale", first.result()[0]["state"])
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            self.assertIs(
                newer[0],
                self.outline.for_session_with_plan(self.config, self.state, "claude", "root")[0],
            )
        self.assertEqual(0, self.state.session_outline_active)

    def test_evicted_busy_slots_do_not_release_active_work_capacity(self) -> None:
        self._large(2)
        config = dataclasses.replace(self.config, session_outline_cache_limit=1)
        with self._blocked_poll(config) as (pool, _first, calls):
            for number in range(5):
                with self.state.session_outline_lock:
                    self.state.session_outline_slots.clear()
                next_poll = pool.submit(
                    self.outline.for_session_with_plan,
                    config,
                    self.state,
                    "claude",
                    f"cold-{number}",
                )
                self.assertEqual("outline_busy", next_poll.result(timeout=WAIT_SEC)[0]["reason"])
                self.assertEqual(["root"], calls)
                self.assertEqual(1, self.state.session_outline_active)
        self.assertEqual(0, self.state.session_outline_active)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            self.assertEqual(
                "ok",
                self.outline.for_session_with_plan(config, self.state, "claude", "after")[0][
                    "state"
                ],
            )

    def test_source_exception_releases_slot_and_active_permit(self) -> None:
        self._large(2)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            with (
                mock.patch.object(
                    self.source, "_read_outline", side_effect=OSError("owned fixture read failure")
                ),
                self.assertRaisesRegex(OSError, "owned fixture"),
            ):
                self.outline.for_session_with_plan(self.config, self.state, "claude", "root")
            self.assertEqual(0, self.state.session_outline_active)
            self.assertEqual(
                "ok",
                self.outline.for_session_with_plan(self.config, self.state, "claude", "root")[0][
                    "state"
                ],
            )

    def test_registry_lock_never_covers_stat_source_plan_or_graph_measurement(self) -> None:
        self._large(2)

        def outside_registry(real: Any, *args: Any, **kwargs: Any) -> Any:
            acquired = self.state.session_outline_lock.acquire(blocking=False)
            self.assertTrue(acquired, "expensive work ran under the registry lock")
            if acquired:
                self.state.session_outline_lock.release()
            return real(*args, **kwargs)

        owners = [
            (self.source, "_outline_stamps"),
            (self.source, "_read_outline"),
            (self.outline, "_plan"),
            (self.outline, "_project_parent"),
            (self.outline, "_measure_facts"),
        ]
        with ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path))
            )
            for owner, name in owners:
                real = getattr(owner, name)
                stack.enter_context(
                    mock.patch.object(
                        owner,
                        name,
                        side_effect=lambda *args, real=real, **kwargs: outside_registry(
                            real, *args, **kwargs
                        ),
                    )
                )
            answer, _ = self.outline.for_session_with_plan(
                self.config, self.state, "claude", "root"
            )
        self.assertTrue(answer["coverage"]["complete"])

    def test_cooperative_row_or_plan_overrun_keeps_verified_progress(self) -> None:
        self._large(2)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        for stage in ("source", "plan"):
            self.state = build_runtime_state(self.config, started=1)
            now = [100.0]
            target = self.source if stage == "source" else self.outline
            name = "_message" if stage == "source" else "_plan"
            real = getattr(target, name)

            def overrun(*args: Any, real: Any = real, now: list[float] = now, **kwargs: Any) -> Any:
                result = real(*args, **kwargs)
                now[0] += 0.3
                return result

            meter = test_session_source.SessionSourceTest()
            meter.source = self.source
            with (
                self.subTest(stage=stage),
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                mock.patch.object(
                    self.outline.time, "monotonic", side_effect=lambda now=now: now[0]
                ),
                mock.patch.object(target, name, side_effect=overrun),
                meter._meter_source_reads() as reads,
            ):
                answer, _plan = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
                self.assertLessEqual(reads[0], self.config.session_outline_max_bytes)
                self.assertEqual("ok", answer["state"])
                self.assertTrue(answer["blocks"][0]["opening"])
                graph = next(iter(self.state.session_outlines.values()))
                self.assertGreater(graph.extras.checkpoint.frontier.end_offset, 0)
                self.assertEqual(1, graph.extras.checkpoint.next_stream)
                # The next poll gets the child, not an endless retry of the discarded parent.
                answer, _plan = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
                self.assertTrue(
                    any(block["counts"]["subagent_entries"] for block in answer["blocks"])
                )

    def test_default_budget_wordful_parent_and_children_eventually_complete(self) -> None:
        transcript = Transcript(self.root)
        for number in range(8):
            transcript.prompt(f"Owned wordful phase {number}. " + "padding " * 24000)
        transcript.save(self.path)
        for name in ("agent-ab12.jsonl", "workflows/owned/agent-ab12.jsonl"):
            child = Transcript(self.root)
            for number in range(2):
                child.bash(f"pytest tests/child_{number}.py", "1 passed " + "output " * 14000)
            for row in child.rows:
                row["isSidechain"] = True
            child.save(self.path.with_suffix("") / "subagents" / name)
        self.assertEqual(0.25, self.config.session_outline_max_seconds)
        self.assertEqual(2 * 1024 * 1024, self.config.session_outline_max_bytes)
        whole = self.source.read(
            self.config,
            str(self.path),
            "claude",
            "root",
            max_bytes=8 * 1024 * 1024,
            deadline=self.outline.time.monotonic() + 30,
        )
        self.assertTrue(whole.coverage.complete)
        expected = {entry.fact_id for entry in whole.entries}
        opening = whole.entries[0].fact_id
        meter = test_session_source.SessionSourceTest()
        meter.source = self.source
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            meter._meter_source_reads() as reads,
        ):
            for _poll in range(24):
                before = reads[0]
                answer, plan = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
                self.assertLessEqual(reads[0] - before, self.config.session_outline_max_bytes)
                self.assertEqual("ok", answer["state"])
                graph = next(iter(self.state.session_outlines.values()))
                self.assertIn(opening, graph.facts)
                if plan is not None:
                    self.assertFalse(plan["complete"])
                if answer["coverage"]["complete"]:
                    break
            self.assertTrue(
                answer["coverage"]["complete"], "wordful parent starved the remaining streams"
            )
            self.assertEqual(expected, set(graph.facts))
            before = reads[0]
            again, _ = self.outline.for_session_with_plan(self.config, self.state, "claude", "root")
            self.assertIs(answer, again)
            self.assertEqual(before, reads[0])

    def test_word_heavy_partial_page_defers_optional_plan(self) -> None:
        transcript = Transcript(self.root)
        transcript.prompt("Owned large words. " + "padding " * 20000)
        transcript.save(self.path)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(
                self.outline.session_summary,
                "plan",
                side_effect=AssertionError(
                    "optional word-heavy partial estimate must not consume the poll"
                ),
            ),
        ):
            answer, plan = self.outline.for_session_with_plan(
                self.config, self.state, "claude", "root"
            )
        self.assertEqual("ok", answer["state"])
        self.assertFalse(answer["coverage"]["complete"])
        self.assertIsNone(plan)

    def test_final_validation_rejects_changed_inventory_or_source_after_overrun(self) -> None:
        self._large(2)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        directory = self.path.with_suffix("") / "subagents"
        child.save(directory / "agent-ab12.jsonl")
        added = directory / "agent-added.jsonl"
        for finish, changed in (
            (3, "source"),
            (3, "inventory"),
            (3, "validation_time"),
            (4, "source"),
            (4, "inventory"),
            (4, "validation_time"),
        ):
            self.state = build_runtime_state(self.config, started=1)
            now = [100.0]
            calls = [0]
            real = self.source._outline_stamps

            def stamps(
                *args: Any,
                calls: list[int] = calls,
                finish: int = finish,
                changed: str = changed,
                now: list[float] = now,
                real: Any = real,
                **kwargs: Any,
            ) -> Any:
                calls[0] += 1
                if calls[0] == finish:
                    if changed == "inventory":
                        child.save(added)
                    elif changed == "source":
                        with self.path.open("a") as handle:
                            handle.write("\n")
                    else:
                        # The finishing allowance is finite, not a freshness-check bypass.
                        now[0] = kwargs["deadline"] + 0.001
                return real(*args, **kwargs)

            message = self.source._message

            def overrun(
                *args: Any, message: Any = message, now: list[float] = now, **kwargs: Any
            ) -> Any:
                result = message(*args, **kwargs)
                now[0] += 0.3
                return result

            with (
                self.subTest(finish=finish, changed=changed),
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                mock.patch.object(
                    self.outline.time, "monotonic", side_effect=lambda now=now: now[0]
                ),
                mock.patch.object(self.source, "_outline_stamps", side_effect=stamps),
                mock.patch.object(self.source, "_message", side_effect=overrun),
            ):
                answer, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            if changed == "validation_time":
                self.assertEqual("time", answer["reason"])
                self.assertEqual([], answer["blocks"])
                self.assertTrue(
                    all(
                        graph.extras.checkpoint is None
                        for graph in self.state.session_outlines.values()
                    )
                )
            else:
                self.assertEqual("stale", answer["state"])
                self.assertEqual({}, self.state.session_outlines)
            self.assertEqual(0, self.state.session_outline_active)
            if added.exists():
                added.unlink()

    def test_source_deadline_includes_time_spent_before_slot_admission(self) -> None:
        self._large(2)
        now = [100.0]
        deadlines = []
        real = self.source._read_outline

        def resolve(*_args: Any) -> str:
            now[0] = 109.0
            return str(self.path)

        def read(*args: Any, **kwargs: Any) -> Any:
            deadlines.append(kwargs["deadline"])
            return real(*args, **kwargs)

        config = dataclasses.replace(self.config, session_outline_max_seconds=10)
        with (
            mock.patch.object(observer, "resolve_transcript", side_effect=resolve),
            mock.patch.object(self.outline.time, "monotonic", side_effect=lambda: now[0]),
            mock.patch.object(self.source, "_read_outline", side_effect=read),
        ):
            self.outline.for_session_with_plan(config, self.state, "claude", "root")
        self.assertEqual([110.0], deadlines)

    def test_blocked_parent_read_does_not_block_another_session(self) -> None:
        self._large(2)
        other = self.root / "other.jsonl"
        other.write_bytes(self.path.read_bytes())
        entered, release = threading.Event(), threading.Event()
        real = self.source._read_outline

        def blocked(*args: Any, **kwargs: Any) -> Any:
            result = real(*args, **kwargs)
            if args[3] == "root":
                entered.set()
                if not release.wait(HOLD_SEC):
                    raise AssertionError("owned read barrier timed out")
            return result

        with (
            mock.patch.object(
                observer,
                "resolve_transcript",
                side_effect=lambda _c, _s, _h, sid: str(self.path if sid == "root" else other),
            ),
            mock.patch.object(self.source, "_read_outline", side_effect=blocked),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first = pool.submit(
                self.outline.for_session_with_plan, self.config, self.state, "claude", "root"
            )
            try:
                self.assertTrue(entered.wait(WAIT_SEC))
                second = pool.submit(
                    self.outline.for_session_with_plan, self.config, self.state, "claude", "other"
                )
                try:
                    result = second.result(timeout=WAIT_SEC)
                except TimeoutError:
                    self.fail("session B waited behind session A source I/O")
                self.assertEqual("ok", result[0]["state"])
            finally:
                release.set()
                self.assertEqual("ok", first.result(timeout=WAIT_SEC)[0]["state"])

    def test_codex_polls_accumulate_person_only_in_order_with_one_byte_budget(self) -> None:
        rows = []
        for number in range(12):
            rows.extend(
                [
                    test_record_pages.RecordPagesTest.record(
                        number * 3,
                        harness="codex",
                        text=f"Owned person phase {number}. " + "PERSON_PRIVATE_SENTINEL " * 8,
                    ),
                    test_record_pages.RecordPagesTest.record(
                        number * 3 + 1,
                        harness="codex",
                        role="assistant",
                        text="ASSISTANT_PRIVATE_SENTINEL " * 8,
                    ),
                    {
                        "type": "response_item",
                        "timestamp": "2026-10-01T00:00:00Z",
                        "payload": {
                            "type": "function_call",
                            "name": "shell_command",
                            "call_id": f"call-{number}",
                            "arguments": '{"command":"TOOL_PRIVATE_SENTINEL pytest tests"}',
                        },
                    },
                ]
            )
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        config = dataclasses.replace(
            self.config,
            session_outline_max_bytes=2400,
            session_outline_head_bytes=700,
            session_outline_max_blocks=64,
        )
        whole = self.source.read(
            config, str(self.path), "codex", "root", max_bytes=self.path.stat().st_size + 1
        )
        expected = [entry.fact_id for entry in whole.entries]
        self.assertEqual(12, len(expected))
        meter = test_session_source.SessionSourceTest()
        meter.source = self.source
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            meter._meter_source_reads() as reads,
        ):
            for _poll in range(30):
                before = reads[0]
                result, plan = self.outline.for_session_with_plan(
                    config, self.state, "codex", "root"
                )
                self.assertIsNone(plan)
                self.assertLessEqual(reads[0] - before, 2400)
                ids = [block["prompt"]["fact_id"] for block in result["blocks"]]
                self.assertTrue({expected[0], expected[-1]} <= set(ids))
                if result["coverage"]["complete"]:
                    break
            self.assertTrue(
                result["coverage"]["complete"], "unchanged Codex polls never fill the middle"
            )
            self.assertEqual(expected, [block["prompt"]["fact_id"] for block in result["blocks"]])
            self.assertEqual("not_read", result["coverage"]["agent_replies"])
            self.assertEqual("not_admitted", result["coverage"]["checks_and_files"])
            self.assertEqual(
                ["codex_agent_words_not_admitted", "codex_checks_and_files_not_admitted"],
                result["coverage"]["notes"],
            )
            self.assertTrue(all(block["counts"]["checks"] == 0 for block in result["blocks"]))
            self.assertLessEqual(reads[0] - before, 2400)
            retained = next(iter(self.state.session_outlines.values()))
            self.assertIsNotNone(self.outline._measure_facts(retained, self.outline._FACT_LIMITS))
            self.assertNotIn("ASSISTANT_PRIVATE_SENTINEL", repr(retained))
            self.assertNotIn("TOOL_PRIVATE_SENTINEL", repr(retained))
            self.assertNotIn("PERSON_PRIVATE_SENTINEL " * 8, repr(retained))
            before = reads[0]
            again, plan = self.outline.for_session_with_plan(config, self.state, "codex", "root")
            self.assertIs(result, again)
            self.assertIsNone(plan)
            self.assertEqual(before, reads[0])

    def test_codex_cold_state_refusal_preserves_person_only_admission_flags(self) -> None:
        self.path.write_text(
            json.dumps(test_record_pages.RecordPagesTest.record(0, harness="codex")) + "\n"
        )
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(self.outline, "_FACT_LIMITS", self.outline._FactLimits(bytes=1)),
        ):
            answer, plan = self.outline.for_session_with_plan(
                self.config, self.state, "codex", "root"
            )
        self.assertEqual("outline_state_limit", answer["reason"])
        self.assertIsNone(plan)
        self.assertEqual("not_read", answer["coverage"]["agent_replies"])
        self.assertEqual("not_admitted", answer["coverage"]["checks_and_files"])
        self.assertEqual(
            ["codex_agent_words_not_admitted", "codex_checks_and_files_not_admitted"],
            answer["coverage"]["notes"],
        )

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
            with mock.patch.object(
                self.source, "_read_outline", wraps=self.source._read_outline
            ) as read:
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
            self.assertIsNotNone(
                self.outline._measure_facts(self.state.session_outlines, self.outline._FACT_LIMITS)
            )

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

    def test_repeated_native_rows_are_coalesced_on_cold_resumed_and_appended_polls(self) -> None:
        transcript = Transcript(self.root)
        for number in range(18):
            transcript.prompt(f"Owned duplicate phase {number}: " + "padding " * 70)
        transcript.rows.insert(5, dict(transcript.rows[4]))
        transcript.save(self.path)
        config = dataclasses.replace(
            self.config,
            session_outline_max_bytes=4000,
            session_outline_head_bytes=1000,
            session_outline_max_blocks=64,
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for expected in (18, 19):
                for _poll in range(30):
                    answer, _ = self.outline.for_session_with_plan(
                        config, self.state, "claude", "root"
                    )
                    ids = [block["prompt"]["fact_id"] for block in answer["blocks"]]
                    self.assertEqual(len(ids), len(set(ids)))
                    if answer["coverage"]["complete"]:
                        break
                self.assertTrue(answer["coverage"]["complete"])
                self.assertEqual(expected, len(ids))
                transcript.rows.append(dict(transcript.rows[4]))
                transcript.prompt("New phase after duplicate append.")
                transcript.save(self.path)

    def test_child_polls_replay_canonical_order_and_complete_all_streams(self) -> None:
        parent = Transcript(self.root)
        for number in range(10):
            parent.prompt(f"Parent phase {number}. " + "padding " * 60)
            parent.bash(f"pytest tests/parent_{number}.py", "1 passed")
        parent.save(self.path)
        child = Transcript(self.root)
        child.bash("pytest tests/child_first.py", "1 failed", is_error=True)
        call = child.call("Bash", {"command": "pytest tests/old.py"})
        for number in range(5):
            child.prompt(f"PRIVATE_CHILD_PADDING {number}. " + "private " * 100)
        child.hook_rewrite(call, hook_stdout("pytest tests/new.py"))
        for number in range(5):
            child.prompt(f"PRIVATE_CHILD_AFTER_REWRITE {number}. " + "private " * 100)
        child.result(call, "1 passed")
        child.bash("pytest tests/backward.py", "1 passed")
        child.rows[-2]["timestamp"] = child.rows[0]["timestamp"]
        sibling = Transcript(self.root)
        sibling.bash("pytest tests/sibling.py", "1 passed")
        for transcript, name in (
            (child, "agent-ab12.jsonl"),
            (sibling, "workflows/owned/agent-ab12.jsonl"),
        ):
            for row in transcript.rows:
                row["isSidechain"] = True
            transcript.save(self.path.with_suffix("") / "subagents" / name)
        config = dataclasses.replace(
            self.config,
            session_outline_max_bytes=2800,
            session_outline_head_bytes=900,
            session_outline_max_blocks=64,
        )
        whole = self.source.read(config, str(self.path), "claude", "root", max_bytes=100000)
        self.assertTrue(whole.coverage.complete)
        expected = self.outline.build(whole, config)
        self.assertEqual(14, sum(block["counts"]["checks"] for block in expected["blocks"]))
        meter = test_session_source.SessionSourceTest()
        meter.source = self.source
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(
                self.source, "source_stamps", side_effect=AssertionError("unbounded inventory")
            ),
            meter._meter_source_reads() as reads,
        ):
            for _poll in range(80):
                before = reads[0]
                result, plan = self.outline.for_session_with_plan(
                    config, self.state, "claude", "root"
                )
                self.assertLessEqual(reads[0] - before, 2800)
                self.assertTrue(
                    all(
                        region["stream"] in {"parent", "agent-ab12", "workflows/owned/agent-ab12"}
                        for region in result["coverage"]["unread"]
                    )
                )
                if _poll == 0:
                    self.assertFalse(result["coverage"]["complete"])
                    self.assertTrue(
                        any(region["stream"] != "parent" for region in result["coverage"]["unread"])
                    )
                if result["coverage"]["complete"]:
                    break
            self.assertTrue(
                result["coverage"]["complete"],
                "bounded child polls never reached all-stream completion",
            )
            self.assertEqual(expected["blocks"], result["blocks"])
            self.assertIsNotNone(plan)
            self.assertFalse(plan["complete"])
            before = reads[0]
            again, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
            self.assertIs(result, again)
            self.assertEqual(before, reads[0])
            retained = next(iter(self.state.session_outlines.values()))
            self.assertIsNotNone(self.outline._measure_facts(retained, self.outline._FACT_LIMITS))
            self.assertNotIn("PRIVATE_CHILD_PADDING", repr(retained))
            self.assertNotIn("PRIVATE_CHILD_AFTER_REWRITE", repr(retained))

    def test_bounded_inventory_refusal_is_explicit_without_unbounded_fallback(self) -> None:
        self._large(1)
        child = Transcript(self.root)
        child.bash("pytest tests", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        with (
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
            mock.patch.object(
                self.source,
                "source_stamps",
                side_effect=AssertionError("unbounded inventory must not run"),
            ),
            mock.patch.object(self.source, "_OUTLINE_STREAM_LIMIT", 1),
        ):
            result, plan = self.outline.for_session_with_plan(
                self.config, self.state, "claude", "root"
            )
        self.assertEqual(
            ("unavailable", "outline_stream_limit"), (result["state"], result["reason"])
        )
        self.assertIsNone(result["coverage"])
        self.assertIsNone(plan)
        self.assertEqual(0, self.state.session_outline_active)

    def test_child_inventory_time_cut_keeps_frontier_retryable(self) -> None:
        self._large(1)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first, _ = self.outline.for_session_with_plan(self.config, self.state, "claude", "root")
            checkpoint = next(iter(self.state.session_outlines.values())).extras.checkpoint
            real = self.source._outline_stamps
            calls = [0]

            def cut_once(*args: Any, **kwargs: Any) -> Any:
                calls[0] += 1
                if calls[0] == 3:
                    raise ValueError("time")
                return real(*args, **kwargs)

            with mock.patch.object(self.source, "_outline_stamps", side_effect=cut_once):
                clipped, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertEqual(first["blocks"], clipped["blocks"])
            self.assertEqual("time", clipped["reason"])
            gaps = clipped["coverage"]["unread"]
            for _retry in range(2):
                calls[0] = 0
                with mock.patch.object(self.source, "_outline_stamps", side_effect=cut_once):
                    repeated, _ = self.outline.for_session_with_plan(
                        self.config, self.state, "claude", "root"
                    )
                self.assertEqual(gaps, repeated["coverage"]["unread"])
            self.assertIs(
                checkpoint, next(iter(self.state.session_outlines.values())).extras.checkpoint
            )
            for _poll in range(4):
                complete, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
                if complete["coverage"]["complete"]:
                    break
            self.assertTrue(
                complete["coverage"]["complete"], "one time cut permanently stopped child progress"
            )
            self.assertEqual(2, sum(block["counts"]["checks"] for block in complete["blocks"]))

    def test_unfinished_child_is_terminal_partial_without_unchanged_rereads(self) -> None:
        self._large(1)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        path = self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl"
        child.save(path)
        path.write_bytes(path.read_bytes()[:-8])
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for _poll in range(4):
                answer, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertFalse(answer["coverage"]["complete"])
            self.assertIn(
                ("agent-ab12", "partial_line"),
                [(gap["stream"], gap["reason"]) for gap in answer["coverage"]["unread"]],
            )
            with mock.patch.object(
                self.source,
                "_read_outline",
                side_effect=AssertionError("partial EOF must be stat-only"),
            ):
                again, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertIs(answer, again)

    def test_child_inventory_deadline_before_or_after_read_is_not_an_http_error(self) -> None:
        self._large(1)
        for fail_at in (1, 4):
            self.state = build_runtime_state(self.config, started=1)
            calls = [0]
            real = self.source._outline_stamps

            def deadline(
                *args: Any,
                calls: list[int] = calls,
                fail_at: int = fail_at,
                real: Any = real,
                **kwargs: Any,
            ) -> Any:
                calls[0] += 1
                if calls[0] == fail_at:
                    raise ValueError("time")
                return real(*args, **kwargs)

            with (
                self.subTest(fail_at=fail_at),
                mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                mock.patch.object(self.source, "_outline_stamps", side_effect=deadline),
            ):
                answer, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertEqual(("unavailable", "time"), (answer["state"], answer["reason"]))
            self.assertIsNone(answer["coverage"])
            self.assertEqual({}, self.state.session_outlines)
            self.assertEqual(0, self.state.session_outline_active)

    def test_unreadable_child_does_not_stop_healthy_sibling_progress(self) -> None:
        self._large(1)
        directory = self.path.with_suffix("") / "subagents"
        (directory / "agent-dead.jsonl").mkdir(parents=True)
        child = Transcript(self.root)
        child.bash("pytest tests/healthy.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(directory / "agent-eeee.jsonl")
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for _poll in range(4):
                answer, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertFalse(answer["coverage"]["complete"])
            self.assertEqual(2, sum(block["counts"]["checks"] for block in answer["blocks"]))
            self.assertIn(
                ("agent-dead", "unreadable_subagent"),
                [(gap["stream"], gap["reason"]) for gap in answer["coverage"]["unread"]],
            )
            checkpoint = next(iter(self.state.session_outlines.values())).extras.checkpoint
            self.assertTrue(checkpoint.children[0][1].stopped)
            self.assertTrue(checkpoint.children[1][1].parent_complete)
            with mock.patch.object(
                self.source,
                "_read_outline",
                side_effect=AssertionError("settled gap must not spin"),
            ):
                again, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertIs(answer, again)

    def test_child_fix_in_hidden_group_reconciles_opening_failure(self) -> None:
        parent = Transcript(self.root)
        parent.prompt("Opening failed check.")
        parent.bash("pytest tests/shared.py", "1 failed", is_error=True)
        parent.prompt("Hidden delegated repair.")
        child = Transcript(self.root)
        child.seconds = parent.seconds
        child.bash("pytest tests/shared.py", "1 passed")
        parent.seconds += 20
        parent.prompt("Newest phase.")
        parent.save(self.path)
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        config = dataclasses.replace(self.config, session_outline_max_blocks=1)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for _poll in range(4):
                answer, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
                if answer["coverage"]["complete"]:
                    break
        self.assertTrue(answer["coverage"]["complete"])
        self.assertEqual(1, answer["more_blocks"])
        first = answer["blocks"][0]
        self.assertEqual(
            (1, 0, 0),
            (
                first["counts"]["checks_fixed"],
                first["counts"]["checks_failed"],
                first["counts"]["checks_unknown"],
            ),
        )

    def test_source_checkpoint_refusal_retains_prior_child_graph_and_is_sticky(self) -> None:
        self._large(1)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            first, _ = self.outline.for_session_with_plan(self.config, self.state, "claude", "root")
            previous = next(iter(self.state.session_outlines.values())).extras.checkpoint
            with mock.patch.object(self.source, "_OUTLINE_CHECKPOINT_BYTES", 1):
                limited, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertEqual("outline_state_limit", limited["reason"])
            self.assertEqual(first["blocks"], limited["blocks"])
            self.assertIs(
                previous, next(iter(self.state.session_outlines.values())).extras.checkpoint
            )
            with mock.patch.object(
                self.source,
                "_read_outline",
                side_effect=AssertionError("source refusal must not repeat"),
            ):
                again, _ = self.outline.for_session_with_plan(
                    self.config, self.state, "claude", "root"
                )
            self.assertIs(limited, again)

    def test_child_work_is_not_the_opening_when_parent_opening_is_unread(self) -> None:
        parent = Transcript(self.root)
        parent.prompt("Unread opening. " + "padding " * 600)
        parent.save(self.path)
        child = Transcript(self.root)
        child.bash("pytest tests/child.py", "1 passed")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        config = dataclasses.replace(
            self.config, session_outline_max_bytes=2000, session_outline_head_bytes=500
        )
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for _poll in range(10):
                answer, _ = self.outline.for_session_with_plan(config, self.state, "claude", "root")
                if answer["blocks"]:
                    break
        self.assertTrue(answer["blocks"])
        self.assertFalse(answer["coverage"]["complete"])
        self.assertFalse(any(block["opening"] for block in answer["blocks"]))

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
            for _poll in range(4):
                first = self.outline.for_session(self.config, self.state, "claude", "root")
                if first["coverage"]["complete"]:
                    break
            self.assertTrue(first["coverage"]["complete"])
            child.bash("pytest tests", "1 failed", is_error=True)
            for row in child.rows:
                row["isSidechain"] = True
            child.save(path)
            for _poll in range(4):
                later = self.outline.for_session(self.config, self.state, "claude", "root")
                if later["coverage"]["complete"]:
                    break
            self.assertTrue(later["coverage"]["complete"])
        self.assertIsNot(first, later)
        self.assertEqual(1, sum(block["counts"]["checks_failed"] for block in later["blocks"]))
        rewritten = Transcript(self.root)
        rewritten.bash("pytest tests", "1 passed")
        for row in rewritten.rows:
            row["isSidechain"] = True
        rewritten.save(path)
        with mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)):
            for _poll in range(4):
                updated = self.outline.for_session(self.config, self.state, "claude", "root")
                if updated["coverage"]["complete"]:
                    break
        self.assertTrue(updated["coverage"]["complete"])
        self.assertIsNot(later, updated)
        self.assertEqual(0, sum(block["counts"]["checks_failed"] for block in updated["blocks"]))
        self.assertEqual(1, sum(block["counts"]["checks"] for block in updated["blocks"]))

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
                with mock.patch.object(
                    self.source, "_read_outline", wraps=self.source._read_outline
                ) as source_read:
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
            connection = http.client.HTTPConnection(
                "127.0.0.1", server.server_port, timeout=WAIT_SEC
            )
            self.addCleanup(connection.close)
            connection.request("GET", path)
            response = connection.getresponse()
            self.assertEqual(200, response.status)
            return json.loads(response.read())

        with mock.patch.object(self, "request", side_effect=request):
            self.check_handler(handler)
