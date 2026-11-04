"""Strict final proof over verified retained bytes must keep legacy source guards."""

from __future__ import annotations

import copy
import json
from typing import Any
from unittest import mock

from compass_runtime import project_context as context
from compass_runtime import reading
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory_source

from . import test_reading_source as source_tests
from .test_claude_checks import SHORT, SID, Transcript


class RetainedStrictFinalTest(source_tests.CompleteReadingSourceFixture):
    def setUp(self) -> None:
        super().setUp()
        self.child_path.unlink()
        self.path = self.root / (SID + ".jsonl")
        self.parent = Transcript(self.root)
        self.parent.prompt("Finish the requested change.")

    def say(self, text: str, stop: Any = "end_turn") -> dict[str, Any]:
        row = self.parent._entry("assistant", [{"type": "text", "text": text}])
        row["message"]["stop_reason"] = stop
        return row

    def freeze(self) -> inventory_source.Inventory:
        self.parent.save(self.path)
        return inventory_source.freeze(
            str(self.path), "claude", SHORT, max_entries=100, max_streams=10, max_seconds=1
        )

    def collect(
        self, inventory: inventory_source.Inventory | None = None, **kwargs: Any
    ) -> collector.Collection:
        result = collector.collect(
            self.config,
            inventory or self.freeze(),
            ancillary=collector.Ancillary(str(self.root)),
            **kwargs,
        )
        self.assertTrue(hasattr(result, "final"), "retained strict-final proof is not implemented")
        return result

    def oracle(self, result: collector.Collection) -> dict[str, Any]:
        assert result.evidence is not None
        wanted = reading.build_ledger(result.evidence.facts, "claude", SHORT, read_agent_words=True)
        return context.transcript_newest_final_words(
            self.config,
            str(self.path),
            "claude",
            SHORT,
            wanted,
            expected_stamp=context.transcript_stamp(str(self.path)),
        )

    def test_small_corpus_matches_strict_oracle_without_a_content_rescan(self) -> None:
        self.say("Finished. " + "evidence " * 300 + "WHOLE_FINAL_END")
        self.say("Now using another tool.", "tool_use")
        with mock.patch.object(
            context, "transcript_newest_final_words", side_effect=AssertionError("no rescan")
        ):
            result = self.collect(page_bytes=193)
        self.assertEqual(self.oracle(result), result.final)
        assert result.final is not None
        self.assertEqual("whole", result.final["outcome"])
        self.assertIn("WHOLE_FINAL_END", result.final["words"])
        assert result.evidence is not None
        fact = next(f for f in result.evidence.facts if f["fact_id"] == result.final["fact_id"])
        self.assertEqual(fact["at"], result.final["at"])
        self.assertEqual(3 * self.path.stat().st_size, result.usage.source_bytes)
        self.assertTrue(result.source_verified)

    def test_native_identity_and_ambiguous_raw_sources_cannot_prove_a_final(self) -> None:
        cases = ("missing", "foreign_prefix", "duplicate", "missing_stop", "tied")
        for case in cases:
            with self.subTest(case=case):
                self.parent = Transcript(self.root)
                row = self.say("Finished. " + "context " * 150 + "TAIL")
                if case == "missing":
                    row.pop("sessionId")
                elif case == "foreign_prefix":
                    row["sessionId"] = SID[:-1] + ("1" if SID[-1] != "1" else "2")
                elif case == "duplicate":
                    other = copy.deepcopy(row)
                    other["message"]["stop_reason"] = "tool_use"
                    self.parent.rows.append(other)
                elif case == "missing_stop":
                    row["message"].pop("stop_reason")
                else:
                    other = copy.deepcopy(row)
                    other["uuid"] = "different"
                    self.parent.rows.append(other)
                result = self.collect()
                self.assertEqual(self.oracle(result), result.final)
                assert result.final is not None
                self.assertEqual(
                    "ambiguous" if case == "tied" else "unproven", result.final["outcome"]
                )
                self.assertNotIn("words", result.final)

    def test_named_unfit_final_is_blocked_before_ordinary_whole_extraction(self) -> None:
        self.say("Finished. " + "x" * context.FINAL_WORDS_MAX_CHARS + "UNFIT_TAIL")
        original = context.whole_message_words

        def only_person(config: Any, record: Any, harness: str, cap: int) -> str:
            self.assertNotEqual(
                "assistant", record.get("type"), "named unfit final reached ordinary fallback"
            )
            return original(config, record, harness, cap)

        with mock.patch.object(context, "whole_message_words", side_effect=only_person):
            result = self.collect()
        self.assertEqual(self.oracle(result), result.final)
        assert result.final is not None
        self.assertEqual("too-long", result.final["outcome"])
        assert result.words is not None
        word = next(row for row in result.words if row.fact_id == result.final["fact_id"])
        self.assertEqual(
            ("unavailable", "final_unfit", None, None),
            (word.state, word.reason, word.words, word.total),
        )
        self.assertTrue(result.source_verified)
        self.assertNotIn("UNFIT_TAIL", str(result.words))

    def test_raw_record_file_and_uuid_bounds_still_refuse(self) -> None:
        self.say("Finished.")
        for bound in (
            "FINAL_WORDS_RECORD_MAX_BYTES",
            "FINAL_WORDS_SCAN_MAX_BYTES",
            "FINAL_WORDS_UUIDS_MAX",
        ):
            with self.subTest(bound=bound), mock.patch.object(context, bound, 0):
                result = self.collect()
                self.assertEqual(self.oracle(result), result.final)
                assert result.final is not None
                self.assertEqual(
                    "oversized" if "RECORD" in bound else "scan-limit", result.final["outcome"]
                )
                self.assertNotIn("words", result.final)
        self.parent.rows[-1]["padding"] = "x" * context.FINAL_WORDS_RECORD_MAX_BYTES
        result = self.collect()
        self.assertEqual(self.oracle(result), result.final)
        assert result.final is not None
        self.assertEqual("oversized", result.final["outcome"])

    def test_append_outside_snapshot_keeps_ordinary_words_but_withholds_strict_final(self) -> None:
        self.say("Finished the frozen work.")
        inventory = self.freeze()
        with self.path.open("ab") as source:
            source.write(b'{"type":"progress","later":true}\n')
        result = self.collect(inventory)
        self.assertEqual({"outcome": "source-moved"}, result.final)
        self.assertTrue(result.source_verified)
        assert result.words is not None
        self.assertTrue(
            any(
                row.state == "whole" and row.words == "Finished the frozen work."
                for row in result.words
            )
        )
        self.assertEqual(
            3 * inventory.streams[0].cursor.frozen.end_offset, result.usage.source_bytes
        )

    def test_movement_during_proof_refuses_without_reading_new_content(self) -> None:
        self.say("Finished the frozen work.")
        original = context._agent_whole_words

        def changed(record: Any, size: int) -> Any:
            result = original(record, size)
            replacement = self.root / "replacement.jsonl"
            replacement.write_bytes(self.path.read_bytes())
            replacement.replace(self.path)
            return result

        with mock.patch.object(context, "_agent_whole_words", side_effect=changed):
            result = self.collect()
        self.assertEqual({"outcome": "source-moved"}, result.final)
        self.assertTrue(result.source_verified)

    def test_proof_does_not_depend_on_prompt_json_serialization_size(self) -> None:
        words = "Finished. " + '界🙂"\\' * 2000
        self.assertLess(len(words), context.FINAL_WORDS_MAX_CHARS)
        self.assertGreater(len(json.dumps(words).encode()), context.FINAL_WORDS_MAX_CHARS)
        self.say(words)
        result = self.collect()
        self.assertEqual(self.oracle(result), result.final)
        assert result.final is not None
        self.assertEqual("whole", result.final["outcome"])
        self.assertEqual(words, result.final["words"])

    def test_cancellation_and_deadline_after_proof_work_publish_no_partial_result(self) -> None:
        self.say("Finished the frozen work.")
        original = context._agent_whole_words
        stopped, now = False, 0.0

        def clock() -> float:
            return now

        def cancelled() -> bool:
            return stopped

        for mode in ("cancelled", "time"):
            stopped, now = False, 0.0

            def stop(record: Any, size: int, _mode: str = mode) -> Any:
                nonlocal stopped, now
                words = original(record, size)
                if _mode == "cancelled":
                    stopped = True
                else:
                    now = 61.0
                return words

            with (
                self.subTest(mode=mode),
                mock.patch.object(context, "_agent_whole_words", side_effect=stop),
            ):
                result = self.collect(clock=clock, cancelled=cancelled)
            self.assertEqual(mode, result.reason)
            self.assertTrue(result.source_verified)
            self.assertIsNone(result.final)
            self.assertIsNone(result.words)
            self.assertIsNone(result.evidence)

    def test_append_after_proof_during_word_join_withdraws_the_final(self) -> None:
        self.say("Finished the frozen work.")
        original = context.whole_message_words
        appended = False

        def append(config: Any, record: Any, harness: str, cap: int) -> str:
            nonlocal appended
            words = original(config, record, harness, cap)
            if not appended:
                with self.path.open("ab") as target:
                    target.write(b'{"type":"progress"}\n')
                appended = True
            return words

        with mock.patch.object(context, "whole_message_words", side_effect=append):
            result = self.collect()
        self.assertEqual({"outcome": "source-moved"}, result.final)
        self.assertTrue(result.source_verified)
        assert result.words is not None
        self.assertTrue(any(word.state == "whole" for word in result.words))
