"""Ordinary raw text admission precedes every canonical message redactor."""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any
from unittest import mock

from compass_runtime import (
    claude_data,
    reading_source,
    records,
    transcripts,
)
from compass_runtime import (
    project_context as context,
)
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory

from . import test_reading_source as sources
from .test_claude_checks import SHORT, Transcript


class EarlyMessageAdmissionTest(sources.CompleteReadingSourceFixture):
    def setUp(self) -> None:
        super().setUp()
        self.child_path.unlink()
        self.parent = Transcript(self.root)

    def collect(self, **options: Any) -> collector.Collection:
        self.parent.save(self.path)
        frozen = inventory.freeze(
            str(self.path), "claude", SHORT, max_entries=100, max_streams=10, max_seconds=1
        )
        return collector.collect(
            self.config,
            frozen,
            ancillary=collector.Ancillary(str(self.root)),
            clock=options.pop("clock", lambda: 0.0),
            **options,
        )

    def assert_refused(self, result: Any) -> None:
        self.assertEqual("message_limit", result.reason)
        self.assertTrue(result.source_verified)
        self.assertEqual(3 * self.path.stat().st_size, result.usage.source_bytes)
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.words)
        self.assertIsNone(result.final)
        self.assertIsNone(result.snapshot)

    def test_parent_user_and_agent_multiblock_unicode_refuse_before_any_masking(self) -> None:
        for role in ("user", "assistant"):
            with self.subTest(role=role):
                self.parent.rows = []
                self.parent._entry(
                    role,
                    [
                        {"type": "text", "text": "界" * (context.PRESS_TEXT_MAX_CHARS // 2)},
                        {"type": "text", "text": "字" * (context.PRESS_TEXT_MAX_CHARS // 2 + 1)},
                    ],
                )
                with (
                    mock.patch.object(
                        records, "mask_prose", side_effect=AssertionError("oversized mask")
                    ),
                    mock.patch.object(
                        transcripts,
                        "redact_command_framing",
                        side_effect=AssertionError("oversized extraction"),
                    ),
                    mock.patch.object(
                        reading_source,
                        "from_complete_scan",
                        side_effect=AssertionError("oversized projection"),
                    ),
                ):
                    result = self.collect()
                self.assert_refused(result)

    def test_boundary_raw_character_admission_preserves_exact_canonical_ids(self) -> None:
        self.parent.prompt("Review " + "界" * (context.PRESS_TEXT_MAX_CHARS - len("Review ")))
        self.parent._entry("assistant", [{"type": "text", "text": 'I checked "quoted" text.'}])
        self.parent.save(self.path)
        scan = context._live_check_scan(self.config, str(self.path))
        expected = reading_source.from_complete_scan(self.config, scan, "claude", SHORT)
        original = records.mask_prose

        def bounded(text: str) -> str:
            self.assertLessEqual(len(text), context.PRESS_TEXT_MAX_CHARS)
            return original(text)

        framing = transcripts.redact_command_framing

        def bounded_framing(text: str) -> str:
            self.assertLessEqual(len(text), context.PRESS_TEXT_MAX_CHARS)
            return framing(text)

        with (
            mock.patch.object(records, "mask_prose", side_effect=bounded),
            mock.patch.object(transcripts, "redact_command_framing", side_effect=bounded_framing),
        ):
            result = self.collect()
        self.assertEqual("", result.reason)
        assert result.evidence is not None
        self.assertEqual(expected.facts, result.evidence.facts)
        self.assertEqual(expected.press, result.evidence.press)
        assert result.words is not None
        self.assertTrue(all(row.state == "whole" for row in result.words))
        totals = []
        for row in result.words:
            assert row.total is not None
            totals.append(row.total)
        self.assertEqual(context.PRESS_TEXT_MAX_CHARS, max(totals))

    def test_oversized_excluded_shapes_and_child_prose_do_not_become_messages(self) -> None:
        large = "IGNORED" * (context.PRESS_TEXT_MAX_CHARS // 7 + 1)
        self.parent.prompt("Keep the native direction.")
        for flags in ({"isMeta": True}, {"isSidechain": True}):
            self.parent._entry("user", [{"type": "text", "text": large}], **flags)
        synthetic = self.parent._entry("assistant", [{"type": "text", "text": large}])
        synthetic["message"]["model"] = claude_data.SYNTHETIC_MODEL
        self.parent._entry("assistant", [{"type": "thinking", "thinking": large}])
        self.parent._entry(
            "assistant",
            [{"type": "tool_use", "id": "tool-only", "name": "Read", "input": {"data": large}}],
        )
        self.parent._entry(
            "user", [{"type": "tool_result", "tool_use_id": "tool-only", "content": large}]
        )
        self.parent.rows.append({"type": "progress", "message": {"role": "user", "content": large}})
        child = Transcript(self.root)
        child.prompt(large)
        child.save(self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl")
        original = records.mask_prose

        def bounded(text: str) -> str:
            if "IGNORED" in text:
                self.assertLessEqual(len(text), context.PRESS_TEXT_MAX_CHARS)
            return original(text)

        framing = transcripts.redact_command_framing

        def bounded_framing(text: str) -> str:
            self.assertLessEqual(len(text), context.PRESS_TEXT_MAX_CHARS)
            return framing(text)

        with (
            mock.patch.object(records, "mask_prose", side_effect=bounded),
            mock.patch.object(transcripts, "redact_command_framing", side_effect=bounded_framing),
        ):
            result = self.collect()
        self.assertEqual("", result.reason)
        assert result.evidence is not None
        messages = [
            f for f in result.evidence.facts if f["type"] in ("user_message", "agent_message")
        ]
        self.assertEqual(1, len(messages))
        self.assertNotIn("IGNORED", str(result.words))

    def test_queued_human_direction_and_slash_arguments_are_raw_admission_candidates(self) -> None:
        queued: dict[str, Any] = {
            "type": "attachment",
            "timestamp": "2026-11-04T00:03:00Z",
            "attachment": {
                "type": "queued_command",
                "timestamp": "2026-11-04T00:00:01Z",
                "commandMode": "prompt",
                "origin": {"kind": "human"},
                "prompt": "Read " + "x" * context.PRESS_TEXT_MAX_CHARS,
            },
        }
        self.parent.rows = [queued]
        with (
            mock.patch.object(records, "mask_prose", side_effect=AssertionError("queued mask")),
            mock.patch.object(
                transcripts,
                "redact_command_framing",
                side_effect=AssertionError("queued extraction"),
            ),
        ):
            self.assert_refused(self.collect())
        self.parent.rows = []
        self.parent.prompt(
            "<command-name>/review</command-name><command-args>"
            + "x" * context.PRESS_TEXT_MAX_CHARS
            + "</command-args>"
        )
        with (
            mock.patch.object(records, "mask_prose", side_effect=AssertionError("slash mask")),
            mock.patch.object(
                transcripts,
                "redact_command_framing",
                side_effect=AssertionError("slash extraction"),
            ),
        ):
            self.assert_refused(self.collect())
        notification = copy.deepcopy(queued)
        notification["attachment"]["origin"]["kind"] = "task-notification"
        self.parent.rows = [notification]
        result = self.collect()
        self.assertEqual("", result.reason)
        self.assertEqual((), result.words)

    def test_question_tool_answers_use_existing_answer_admission(self) -> None:
        self.parent._entry(
            "user", [{"type": "tool_result", "tool_use_id": "ask", "content": "Answered."}]
        )
        self.parent.rows[-1]["toolUseResult"] = {
            "questions": [{"question": "Which path?", "header": "Path", "options": []}],
            "answers": {"Which path?": "界" * (context.PRESS_TEXT_MAX_CHARS + 1)},
        }
        with mock.patch.object(
            transcripts, "redact_command_framing", side_effect=AssertionError("answer extraction")
        ):
            self.assert_refused(self.collect())
        # The same fields on an unsuccessful tool result are not reader words.
        self.parent.rows[-1]["message"]["content"][0]["is_error"] = True
        result = self.collect()
        self.assertEqual("", result.reason)
        self.assertEqual((), result.words)

    def test_admission_checkpoints_and_existing_retention_withhold_all_proof(self) -> None:
        self.parent.prompt("Review the bounded message.")
        original = context._message_text_chars
        stopped = False

        def counted(record: Any) -> int:
            nonlocal stopped
            count = original(record)
            stopped = True
            return count

        with mock.patch.object(context, "_message_text_chars", side_effect=counted):
            result = self.collect(cancelled=lambda: stopped)
        self.assertEqual("cancelled", result.reason)
        self.assertTrue(result.source_verified)
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.snapshot)
        stopped = False
        with mock.patch.object(context, "_message_text_chars", side_effect=counted):
            result = self.collect(clock=lambda: 61.0 if stopped else 0.0)
        self.assertEqual("time", result.reason)
        self.assertTrue(result.source_verified)
        self.assertIsNone(result.evidence)
        self.assertIsNone(result.words)
        self.assertIsNone(result.final)
        self.assertIsNone(result.snapshot)
        with mock.patch.object(
            reading_source, "from_complete_scan", side_effect=AssertionError("unadmitted graph")
        ):
            result = self.collect(limits=replace(collector.Limits(), retained_units=1))
        self.assertEqual("retained_units", result.reason)
        self.assertEqual(0, result.usage.source_bytes)
