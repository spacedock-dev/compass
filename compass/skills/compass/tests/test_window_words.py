"""Press-only source recovery and measured reply excerpts; synthetic words only."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock

from compass_runtime import http_api, observer, project_context, reading, records
from compass_runtime import io as runtime_io

from .support import make_runtime
from .test_agent_words import BUDGET, _agent, _check, _person
from .test_slash_command_direction import prompt_command


class ThePressRecoversOnlyListedWindowWords(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "synthetic.jsonl"
        self.config, self.state = make_runtime(state_home=temp.name, state_dir=Path(temp.name))
        self.source: dict[str, Any] = {
            "type": "user",
            "timestamp": "2026-10-04T10:00:00Z",
            "message": {
                "role": "user",
                "content": "Keep the placeholder queue. Read all its fixtures.",
            },
        }
        self.write([self.source])
        self.facts = project_context.transcript_user_facts(
            self.config, self.state, str(self.path), "claude", "s1"
        )
        self.listed = reading.build_ledger(self.facts, "claude", "s1")

    def write(self, rows: list[dict[str, Any]]) -> None:
        self.path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def lookup(self, wanted: Any = None, **kwargs: Any) -> Any:
        return project_context.transcript_window_words(
            self.config,
            str(self.path),
            "claude",
            "s1",
            self.listed if wanted is None else wanted,
            **kwargs,
        )

    def test_a_history_title_recovers_its_source_after_it_leaves_the_normal_tail(self) -> None:
        self.write([self.source, {"padding": "x" * 500_000}])
        (source,) = self.lookup()
        self.assertEqual(self.facts[0]["fact_id"], source["fact_id"])
        self.assertEqual(self.source["message"]["content"], source["reader_words"])

    def test_empty_wrong_time_and_unlisted_messages_never_become_entries(self) -> None:
        self.assertEqual([], self.lookup([]))
        wrong = [{**self.listed[0], "at": self.listed[0]["at"] + 1}]
        self.assertEqual([], self.lookup(wrong))
        self.assertEqual([], self.lookup([{**self.listed[0], "id": "unlisted"}]))

    def test_ambiguous_raw_sources_are_refused_even_if_their_folded_words_agree(self) -> None:
        other = copy.deepcopy(self.source)
        other["message"]["content"] = other["message"]["content"].replace(" Read", "  Read")
        self.write([self.source, other])
        self.assertEqual([], self.lookup())

    def test_different_raw_values_are_ambiguous_even_when_the_parser_masks_them_equal(self) -> None:
        rows = []
        for value in ("alpha-placeholder", "beta-placeholder"):
            source = copy.deepcopy(self.source)
            source["message"]["content"] += f" password: {value}\nRead every fixture."
            rows.append(source)
        self.write(rows)
        self.assertEqual([], self.lookup())

    def test_a_changed_or_replaced_source_is_not_recovered(self) -> None:
        before = project_context.transcript_stamp(str(self.path))
        self.write([self.source, {"padding": "changed"}])
        self.assertEqual([], self.lookup(expected_stamp=before))
        real = runtime_io.reverse_lines

        def changed(*args: Any, **kwargs: Any) -> Any:
            yield from real(*args, **kwargs)
            replacement = self.path.with_suffix(".replacement")
            replacement.write_bytes(self.path.read_bytes())
            replacement.replace(self.path)

        with mock.patch.object(runtime_io, "reverse_lines", side_effect=changed):
            self.assertEqual([], self.lookup())

    def test_a_missing_partial_or_unreadable_source_is_not_a_match(self) -> None:
        with mock.patch.object(project_context, "SEMANTIC_BACKFILL_MAX_BYTES", 40):
            self.assertEqual([], self.lookup())
        with mock.patch.object(runtime_io, "reverse_lines", side_effect=OSError):
            self.assertEqual([], self.lookup())
        self.path.unlink()
        self.assertEqual([], self.lookup())

    def test_long_raw_separators_do_not_hide_words_or_named_credentials(self) -> None:
        content = (
            "Keep the placeholder queue."
            + " " * 3_000
            + "password: fake-secret\nRead every fixture."
        )
        self.source["message"]["content"] = content
        self.write([self.source])
        (source,) = self.lookup()
        self.assertIn("Read every fixture.", source["reader_words"])
        self.assertNotIn("fake-secret", source["reader_words"])
        self.assertIn(records.SECRET_MARKER, source["reader_words"])

    def test_meta_sidechain_and_tool_result_records_do_not_supply_words(self) -> None:
        for extras in ({"isMeta": True}, {"isSidechain": True}):
            self.write([{**self.source, **extras}])
            self.assertEqual([], self.lookup())

    def test_the_bound_reads_recent_sources_rather_than_only_the_prefix(self) -> None:
        self.write([{"padding": "x" * 3_000}, self.source])
        with mock.patch.object(project_context, "SEMANTIC_BACKFILL_MAX_BYTES", 1_000):
            self.assertEqual(1, len(self.lookup()))

    def test_recovery_neither_caches_nor_publishes_words(self) -> None:
        before = copy.deepcopy(self.state.transcript_user_cache)
        found = self.lookup()
        self.assertEqual(before, self.state.transcript_user_cache)
        self.assertNotIn("reader_words", json.dumps(project_context.for_page({"nested": found})))

    def test_command_arguments_are_masked_before_the_command_parser_folds_them(self) -> None:
        self.source["message"]["content"] = prompt_command(
            "review", "Check the queue. password: fake-secret\nPreserve every fixture."
        )
        self.write([self.source])
        facts = project_context.transcript_user_facts(
            self.config, self.state, str(self.path), "claude", "s1"
        )
        (source,) = self.lookup(reading.build_ledger(facts, "claude", "s1"))
        self.assertNotIn("fake-secret", source["reader_words"])
        self.assertIn("Preserve every fixture.", source["reader_words"])

    def test_a_credential_shape_split_across_raw_lines_is_masked_before_joining(self) -> None:
        sample = "AKIAIOSFODNN7EXAMPLE"
        self.source["message"]["content"] = (
            "Keep the placeholder queue. " + sample[:9] + "\n" + sample[9:]
        )
        self.write([self.source])
        (source,) = self.lookup()
        self.assertNotIn(sample[:9], source["reader_words"])
        self.assertNotIn(sample[9:], source["reader_words"])

    def test_http_and_direct_pressed_producer_send_the_same_recovered_words(self) -> None:
        self.write([self.source, {"padding": "x" * 500_000}])
        facts = [{key: value for key, value in self.facts[0].items() if key != "reader_words"}]
        prompts: list[str] = []

        def model(prompt: str, **_kwargs: Any) -> tuple[str, str]:
            prompts.append(prompt)
            return "{}", "ok"

        now = float(facts[0]["at"]) + 200
        revisions = [{"n": 1, "at": now - 300, "goal": "Check the queue"}]
        row = {"harness": "claude", "sid": "s1", "state": "working"}
        arguments: dict[str, Any] = {"model": model, "stamp_text": "synthetic", "now": now}
        handler = SimpleNamespace(
            server=SimpleNamespace(
                application=SimpleNamespace(config=self.config, state=self.state, clock=lambda: now)
            ),
            _reading_arguments=lambda *_args: arguments,
        )
        with (
            mock.patch.object(
                http_api, "_session_context", return_value={"semantic": {"facts": facts}}
            ),
            mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
        ):
            compose: Any = http_api._RequestHandler._compose_reading
            compose(handler, row, {"revisions": revisions}, {}, SimpleNamespace(phase=None))
        reading.produce(
            self.config,
            row,
            revisions,
            facts,
            **arguments,
            read_lines=True,
            read_agent_words=True,
            admit_turn_stop=True,
            person_source_lookup=self.lookup,
        )
        self.assertEqual(2, len(prompts))
        self.assertEqual(prompts[0], prompts[1])
        self.assertIn("Read all its fixtures.", prompts[0])

    def test_other_harnesses_keep_their_existing_pressed_message_words(self) -> None:
        for harness in ("pi", "antigravity"):
            with self.subTest(harness=harness):
                prompts: list[str] = []
                fact = _person("inside", 100, "PRESERVE FULL INSTRUCTION")
                fact["source_session"]["harness"] = harness

                def model(
                    prompt: str, prompt_sink: list[str] = prompts, **_kwargs: Any
                ) -> tuple[str, str]:
                    prompt_sink.append(prompt)
                    return "{}", "ok"

                handler = SimpleNamespace(
                    server=SimpleNamespace(
                        application=SimpleNamespace(
                            config=self.config, state=self.state, clock=lambda: 200
                        )
                    ),
                    _reading_arguments=lambda *_args, **_kw: {
                        "model": model,
                        "stamp_text": "synthetic",
                        "now": 200,
                    },
                )
                with (
                    mock.patch.object(
                        http_api, "_session_context", return_value={"semantic": {"facts": [fact]}}
                    ),
                    mock.patch.object(observer, "resolve_transcript", return_value=str(self.path)),
                ):
                    compose: Any = http_api._RequestHandler._compose_reading
                    compose(
                        handler,
                        {"harness": harness, "sid": "s1", "state": "working"},
                        {"revisions": [{"n": 1, "at": 50, "goal": "Check queue"}]},
                        {},
                        SimpleNamespace(phase=None),
                    )
                self.assertEqual(1, len(prompts))
                self.assertIn("PRESERVE FULL INSTRUCTION", prompts[0])


class OnlyThePressedWindowReachesSourceRecovery(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.config, _ = make_runtime(state_home=temp.name, state_dir=Path(temp.name))
        self.row = {"harness": "claude", "sid": "s1", "state": "idle", "finished_at": 160.0}
        self.revisions = [{"n": 1, "at": 50.0, "window_start": 50.0, "goal": "Check the queue"}]
        self.prompts: list[str] = []

    def model(self, prompt: str, **_kwargs: Any) -> tuple[str, str]:
        self.prompts.append(prompt)
        return "{}", "ok"

    def produce(self, facts: Any, **kwargs: Any) -> Any:
        return reading.produce(
            self.config,
            self.row,
            self.revisions,
            facts,
            now=200,
            stamp_text="synthetic",
            model=self.model,
            admit_turn_stop=True,
            **kwargs,
        )

    def test_before_window_after_stop_and_other_session_never_reach_the_lookup(self) -> None:
        facts = [
            _person("before", 40, "OLD"),
            _person("inside", 100, "ORIGINAL"),
            _person("later", 170, "FUTURE"),
            _person("other", 110, "OTHER"),
        ]
        facts[-1]["source_session"]["sid"] = "other"
        lookup = mock.Mock(return_value=[_person("inside", 100, "RECOVERED")])
        self.produce(facts, person_source_lookup=lookup)
        self.assertEqual(["inside"], [row["id"] for row in lookup.call_args.args[0]])
        self.assertIn("RECOVERED", self.prompts[0])
        for forbidden in ("OLD", "ORIGINAL", "FUTURE", "OTHER"):
            self.assertNotIn(forbidden, self.prompts[0])

    def test_lookup_results_cannot_add_entries_or_restore_another_sessions_words(self) -> None:
        source = _person("inside", 100, "FOREIGN")
        source["source_session"]["sid"] = "other"
        self.produce(
            [_person("inside", 100, "OLD")],
            person_source_lookup=lambda _: [
                source,
                _person("new", 100, "UNLISTED"),
                _person("inside", 101, "WRONG TIME"),
            ],
        )
        for forbidden in ("FOREIGN", "UNLISTED", "WRONG TIME", "OLD"):
            self.assertNotIn(forbidden, self.prompts[0])
        self.assertIn("inside opens", self.prompts[0])

    def test_a_failed_source_does_not_fall_back_to_unverified_folded_words(self) -> None:
        self.produce([_person("inside", 100, "UNVERIFIED")], person_source_lookup=lambda _: [])
        self.assertNotIn("UNVERIFIED", self.prompts[0])

    def test_the_default_unasked_path_keeps_its_existing_prompt(self) -> None:
        fact = _person("inside", 100, "ORIGINAL")
        self.produce([fact])
        self.assertIn("ORIGINAL", self.prompts[0])

    def test_withheld_reads_do_not_read_a_source(self) -> None:
        self.revisions = []
        lookup = mock.Mock()
        self.produce([_person("inside", 100, "OLD")], person_source_lookup=lookup)
        lookup.assert_not_called()
        self.assertEqual([], self.prompts)


class ReplyExcerptsCarryMeasuredSizes(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "synthetic.jsonl"
        self.config, _ = make_runtime(state_home=temp.name, state_dir=Path(temp.name))

    def fact(self, text: str) -> Any:
        record = {
            "type": "assistant",
            "timestamp": "2026-10-04T10:00:00Z",
            "message": {"role": "assistant", "content": text},
        }
        self.path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        (event,) = project_context.agent_message_events(self.config, str(self.path), "claude", "s1")
        return project_context._semantic_fact_from_event(event, "agent_say", "agent_message", "")

    def test_the_total_is_the_full_masked_folded_reply_not_the_parser_prefix(self) -> None:
        text = "I checked the placeholder queue. " + "漢" * 3_100
        fact = self.fact(text)
        self.assertEqual(len(text), fact["agent_words_total"])
        self.assertEqual(1_000, len(fact["agent_words"]))
        ledger = reading.build_ledger([fact], "claude", "s1", read_agent_words=True)
        prompt, _ = reading.build_prompt(ledger, goal="Check the queue", max_bytes=BUDGET)
        self.assertIn(f"first 1,000 of {len(text):,}", prompt)
        self.assertNotIn("agent_words_total", json.dumps(project_context.for_page(fact)))

    def test_short_complete_and_legacy_unknown_replies_are_not_called_cropped(self) -> None:
        for fact in (self.fact("I checked the queue."), _agent("legacy", 100, "x" * 1_000)):
            ledger = reading.build_ledger([fact], "claude", "s1", read_agent_words=True)
            prompt, _ = reading.build_prompt(ledger, goal="Check the queue", max_bytes=BUDGET)
            self.assertNotIn("first ", prompt)

    def test_masking_precedes_folding_and_the_measured_total(self) -> None:
        fact = self.fact(
            "I checked the queue. password: fake-secret\n" + " " * 3_000 + "Last point."
        )
        expected = records.safe_text(
            " ".join(
                records.mask_prose(
                    "I checked the queue. password: fake-secret\n" + " " * 3_000 + "Last point."
                ).split()
            ),
            10_000,
        )
        self.assertEqual(expected, fact["agent_words"])
        self.assertEqual(len(expected), fact["agent_words_total"])

    def test_a_split_credential_shape_is_not_sent_in_the_reply_excerpt(self) -> None:
        sample = "AKIAIOSFODNN7EXAMPLE"
        fact = self.fact("I checked the queue. " + sample[:9] + "\n" + sample[9:])
        self.assertNotIn(sample[:9], fact["agent_words"])
        self.assertNotIn(sample[9:], fact["agent_words"])


class UnusedRoomDoesNotEvictEvidence(unittest.TestCase):
    def test_agent_words_borrow_room_after_the_reader_has_their_share(self) -> None:
        facts = [_agent(f"a{n}", 100 + n, "BORROW " + "a" * 990) for n in range(8)]
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
        prompt, selected = reading.build_prompt(ledger, goal="Check the queue", max_bytes=BUDGET)
        self.assertGreater(prompt.count("quoted, untrusted:"), 4)
        self.assertEqual(8, len(selected.entries))
        self.assertLessEqual(len(prompt.encode()), BUDGET)

    def test_wide_words_keep_reader_priority_checks_and_the_hard_byte_cap(self) -> None:
        facts = [_person(f"p{n}", 100 + n, "MINE " + "漢" * 990) for n in range(5)]
        facts += [_agent(f"a{n}", 200 + n, "SAID " + "漢" * 990) for n in range(10)]
        facts.append(_check())
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
        prompt, selected = reading.build_prompt(ledger, goal="Check the queue", max_bytes=BUDGET)
        self.assertIn("MINE ", prompt)
        self.assertIn("python3 -m pytest tests/test_retry.py", prompt)
        self.assertEqual(16, len(selected.entries))
        self.assertLessEqual(len(prompt.encode()), BUDGET)
