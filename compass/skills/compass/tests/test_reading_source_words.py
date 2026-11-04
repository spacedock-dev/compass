"""Ordinary complete words stay private and join verified native parent identities."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import project_context as context
from compass_runtime import reading, reading_source
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory_source

from . import test_reading_source as source_tests
from .test_claude_checks import SHORT, SID, Transcript


class VerifiedOrdinaryWordsTest(source_tests.CompleteReadingSourceFixture):
    def setUp(self) -> None:
        super().setUp()
        self.child_path.unlink()
        self.parent = Transcript(self.root)

    def collect(self, **options: Any) -> collector.Collection:
        self.parent.save(self.path)
        inventory = inventory_source.freeze(
            str(self.path),
            "claude",
            SHORT,
            max_entries=100,
            max_streams=10,
            max_seconds=1,
        )
        result = collector.collect(
            self.config,
            inventory,
            ancillary=collector.Ancillary(str(self.root)),
            **options,
        )
        self.assertTrue(hasattr(result, "words"), "verified parent word join is not implemented")
        return result

    def oracle(self, result: collector.Collection) -> list[dict[str, Any]]:
        assert result.evidence is not None
        return context.transcript_message_words(
            self.config,
            str(self.path),
            "claude",
            SHORT,
            reading.build_ledger(result.evidence.facts, "claude", SHORT, read_agent_words=True),
            max_bytes=32 * 1024 * 1024,
            expected_stamp=context.transcript_stamp(str(self.path)),
        )

    @staticmethod
    def recovered(result: collector.Collection) -> list[dict[str, Any]]:
        assert result.words is not None
        return [
            {"id": row.fact_id, "at": row.at, "words": row.words, "total": row.total}
            for row in result.words
            if row.state == "whole"
        ]

    def test_complete_masked_parent_words_match_g2_without_more_source_io(self) -> None:
        secret_tail = "api03-" + "Q" * 70
        person = (
            "<command-message>review</command-message><command-name>/review</command-name>"
            "<command-args>"
            + "context " * 500
            + "sk-ant-\n"
            + secret_tail
            + ' LATE_PERSON 界🙂 "quoted"</command-args>'
        )
        agent = "I inspected parser. " + '界🙂 "quoted" ' * 500 + "LATE_AGENT_MIDDLE"
        self.parent.prompt(person)
        self.parent._entry("assistant", [{"type": "text", "text": agent}])
        self.parent.bash("pytest tests/check.py", "1 passed")
        self.parent.prompt("The final short direction.")
        with mock.patch.object(
            context, "transcript_message_words", side_effect=AssertionError("no rescan")
        ):
            result = self.collect(page_bytes=512)
        self.assertEqual("", result.reason)
        self.assertEqual(self.oracle(result), self.recovered(result))
        assert result.words is not None
        words = " ".join(row.words or "" for row in result.words)
        self.assertIn("LATE_PERSON 界🙂", words)
        self.assertIn("LATE_AGENT_MIDDLE", words)
        self.assertNotIn(secret_tail, words)
        self.assertNotIn("sk-ant-", words)
        self.assertIn('"quoted"', words)
        self.assertNotIn("\ufffd", words)
        self.assertEqual(3 * self.path.stat().st_size, result.usage.source_bytes)
        for row in result.words:
            assert result.evidence is not None
            fact = next(f for f in result.evidence.facts if f["fact_id"] == row.fact_id)
            self.assertEqual(fact["at"], row.at)
            self.assertEqual(fact["source_session"], {"harness": row.harness, "sid": row.sid})
            self.assertEqual(fact["evidence"]["source"], row.source)
            self.assertEqual("native", row.binding)
            assert row.words is not None
            self.assertEqual(len(row.words), row.total)

    def test_raw_conflict_is_refused_even_when_masking_would_make_words_equal(self) -> None:
        self.parent._entry(
            "assistant",
            [
                {
                    "type": "text",
                    "text": "I reviewed parser. " + "context " * 200 + ' password="FIRST_SECRET"',
                }
            ],
        )
        other = copy.deepcopy(self.parent.rows[0])
        other["message"]["content"][0]["text"] = other["message"]["content"][0]["text"].replace(
            "FIRST_SECRET", "SECOND_SECRET"
        )
        left = context.whole_message_words(self.config, self.parent.rows[0], "claude", 10000)
        right = context.whole_message_words(self.config, other, "claude", 10000)
        self.assertEqual(left, right)
        self.parent.rows.append(other)
        with mock.patch.object(
            context, "whole_message_words", side_effect=AssertionError("conflict before words")
        ):
            result = self.collect()
        self.assertEqual([], self.oracle(result))
        assert result.words is not None
        self.assertEqual(1, len(result.words))
        self.assertEqual(
            ("unavailable", "conflict", None),
            (result.words[0].state, result.words[0].reason, result.words[0].words),
        )

    def test_identical_duplicate_and_missing_native_id_keep_parent_file_binding(self) -> None:
        self.parent.prompt("Review parser. " + "context " * 250 + "LATE_PARENT_FILE")
        self.parent.rows[0].pop("sessionId")
        self.parent.rows.append(copy.deepcopy(self.parent.rows[0]))
        result = self.collect()
        self.assertEqual(self.oracle(result), self.recovered(result))
        assert result.words is not None
        self.assertEqual(1, len(result.words))
        self.assertEqual("parent_file", result.words[0].binding)
        assert result.words[0].words is not None
        self.assertIn("LATE_PARENT_FILE", result.words[0].words)

    def test_oversized_queued_duplicate_refuses_at_typing_time_in_both_orders(self) -> None:
        short: dict[str, Any] = {
            "type": "attachment",
            "sessionId": SID,
            "timestamp": "2026-11-04T00:03:00Z",
            "attachment": {
                "type": "queued_command",
                "timestamp": "2026-11-04T00:00:01Z",
                "commandMode": "prompt",
                "origin": {"kind": "human"},
                "prompt": "Review parser.",
            },
        }
        self.parent.rows = [short]
        bounded = self.collect()
        assert bounded.words is not None
        self.assertEqual(1793750401.0, bounded.words[0].at)
        assert bounded.evidence is not None
        wanted = reading.build_ledger(
            bounded.evidence.facts, "claude", SHORT, read_agent_words=True
        )
        oversized = copy.deepcopy(short)
        oversized["attachment"]["prompt"] += "x" * context.PRESS_TEXT_MAX_CHARS
        for rows in ([short, oversized], [oversized, short]):
            with self.subTest(short_first=rows[0] is short):
                self.parent.rows = rows
                with mock.patch.object(
                    context,
                    "whole_message_words",
                    side_effect=AssertionError("admission before words"),
                ):
                    result = self.collect()
                self.assertEqual("message_limit", result.reason)
                self.assertIsNone(result.evidence)
                self.assertIsNone(result.words)
                self.assertIsNone(result.final)
                self.assertIsNone(result.snapshot)
                # Legacy G2 still refuses the duplicate at its original typing time.
                self.assertEqual(
                    [],
                    context.transcript_message_words(
                        self.config,
                        str(self.path),
                        "claude",
                        SHORT,
                        wanted,
                        max_bytes=32 * 1024 * 1024,
                        expected_stamp=context.transcript_stamp(str(self.path)),
                    ),
                )

    def test_foreign_full_identity_child_markers_and_child_file_never_supply_parent_words(
        self,
    ) -> None:
        self.path = self.root / (SID + ".jsonl")
        self.parent.prompt("Native parent words.")
        foreign = self.parent._entry(
            "assistant", [{"type": "text", "text": "FOREIGN_COLLIDING_PREFIX"}]
        )
        foreign["sessionId"] = SID[:-1] + ("1" if SID[-1] != "1" else "2")
        marked = self.parent._entry("assistant", [{"type": "text", "text": "CHILD_MARKED"}])
        marked["agentId"] = "ab12"
        sidechain = self.parent._entry("assistant", [{"type": "text", "text": "SIDECHAIN_WORDS"}])
        sidechain["isSidechain"] = True
        child = Transcript(self.root)
        child.prompt("CHILD_FILE_WORDS")
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        result = self.collect()
        assert result.words is not None
        self.assertEqual(
            ["Native parent words."], [row.words for row in result.words if row.state == "whole"]
        )
        self.assertTrue(any(row.reason == "source" for row in result.words))
        self.assertTrue(any(row.state == "unknown" for row in result.words))
        self.assertNotIn("CHILD", str(self.recovered(result)))

    def test_word_retention_and_cancellation_refuse_without_publishing_partial_words(self) -> None:
        self.parent.prompt("Review parser. " + "person " * 2000 + "LATE_PERSON")
        self.parent._entry(
            "assistant", [{"type": "text", "text": "I reviewed. " + "agent " * 2000 + "LATE_AGENT"}]
        )
        full = self.collect()
        assert full.words is not None
        assert full.words[-1].words is not None
        allowance = full.usage.retained_bytes - len(full.words[-1].words) // 2
        original = context.whole_message_words
        with mock.patch.object(context, "whole_message_words", wraps=original) as whole:
            limited = self.collect(limits=replace(collector.Limits(), retained_bytes=allowance))
        self.assertTrue(whole.called)
        self.assertEqual("retained_bytes", limited.reason)
        self.assertIsNone(limited.words)
        self.assertIsNone(limited.evidence)
        self.assertLessEqual(limited.usage.retained_bytes, allowance)
        stopped = False

        def cancel(*args: Any, **kwargs: Any) -> str:
            nonlocal stopped
            words = original(*args, **kwargs)
            stopped = True
            return words

        with mock.patch.object(context, "whole_message_words", side_effect=cancel):
            cancelled = self.collect(cancelled=lambda: stopped)
        self.assertEqual("cancelled", cancelled.reason)
        self.assertIsNone(cancelled.words)

    def test_fact_source_time_and_id_must_join_exactly(self) -> None:
        self.parent.prompt("Native words with exact ownership.")
        original = reading_source.from_complete_scan
        cases = (
            ("source_session", {"harness": "claude", "sid": "foreign"}, "unavailable", "source"),
            ("evidence", {"source": "invented source"}, "unavailable", "source"),
            ("fact_id", "foreign-fact-id", "unknown", "missing"),
            ("at", 1.0, "unknown", "missing"),
        )
        for field, value, state, reason in cases:

            def project(*args: Any, _field: str = field, _value: Any = value, **kwargs: Any) -> Any:
                result = original(*args, **kwargs)
                result.facts[0][_field] = _value
                return result

            with (
                self.subTest(field=field),
                mock.patch.object(reading_source, "from_complete_scan", side_effect=project),
                mock.patch.object(
                    context, "whole_message_words", side_effect=AssertionError("no exact join")
                ),
            ):
                result = self.collect()
            assert result.words is not None
            self.assertEqual(
                (state, reason, None),
                (result.words[0].state, result.words[0].reason, result.words[0].words),
            )
