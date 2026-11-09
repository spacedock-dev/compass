"""A person can trust a frozen Codex source only while its native proof stands."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if TYPE_CHECKING:
    from tests.codex_source_support import AT, SID, command, config, event, message, rollout, write
else:
    from codex_source_support import AT, SID, command, config, event, message, rollout, write
from compass_runtime import (
    project_context as context,
)


class FrozenCodexRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.path = rollout(self.home / "sessions")
        self.config = config(self.home)

    def test_a_person_gets_the_checks_that_existed_before_a_later_failure(self) -> None:
        before, _ = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        with self.path.open("a") as f:
            f.write(json.dumps(command(30, 1)) + "\n")
        after, _ = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        self.assertTrue(before)
        self.assertEqual(before, after)

    def test_a_person_can_use_their_tagged_and_older_untagged_messages(self) -> None:
        for tagged in (True, False):
            with self.subTest(tagged=tagged):
                self.path = rollout(self.home / "sessions", tagged=tagged)
                whole, tail = context.frozen_codex_user_messages(
                    self.config, str(self.path), SID, until=AT + 10
                )
                self.assertEqual(len(whole), 1)
                self.assertEqual(whole, tail)
                self.assertIn("Please repair", whole[0][context.READER_WORDS_FIELD])

    def test_a_person_is_not_credited_with_an_unattributable_older_message(self) -> None:
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows.insert(
            3,
            message(
                "<codex_internal_context>injected</codex_internal_context>", tagged=False, delta=2
            ),
        )
        write(self.path, rows)
        whole, _ = context.frozen_codex_user_messages(
            self.config, str(self.path), SID, until=AT + 10
        )
        self.assertEqual(len(whole), 1)

    def test_a_person_is_not_credited_with_a_tagged_injected_message(self) -> None:
        row = message("Unrecognizable injected prose", delta=2)
        row["payload"]["internal_chat_message_metadata_passthrough"]["content_item_metadata"][0][
            "provenance"
        ]["type"] = "agents_md"
        with self.path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        whole, _ = context.frozen_codex_user_messages(
            self.config, str(self.path), SID, until=AT + 10
        )
        self.assertEqual(len(whole), 1)

    def test_a_person_gets_redaction_before_message_clipping(self) -> None:
        from compass_runtime import observer  # noqa: PLC0415

        secret = "AKIA" + "A" * 16
        for cap in (112, context.READER_WORDS_CAP_CHARS, 2000):
            text = "Fix the observer. " + "x" * (cap - 37) + " " + secret
            row = message(text)
            parsed = observer.parse_reader_record(row, cap=cap)
            assert parsed is not None
            self.assertNotIn(secret[:-2], parsed["text"])
            self.assertIn("REDACTED", parsed["text"])
            rows = [json.loads(line) for line in self.path.read_text().splitlines()]
            rows[2] = row
            write(self.path, rows)
            whole, _ = context.frozen_codex_user_messages(
                self.config, str(self.path), SID, until=AT + 10
            )
            self.assertNotIn(secret[:-2], json.dumps(whole))

    def test_a_person_cannot_freeze_an_unreachable_cutoff(self) -> None:
        from dataclasses import replace  # noqa: PLC0415

        with self.assertRaises(context.FrozenCheckCutoffUnreachableError):
            context.frozen_codex_checks(
                replace(self.config, turn_scan_max_bytes=64), str(self.path), SID, until=AT + 10
            )

    def test_a_person_distinguishes_late_same_turn_results_from_resumed_work(self) -> None:
        with self.path.open("a") as f:
            f.write(json.dumps(command(8, 1)) + "\n")
            f.write(
                json.dumps({"type": "event_msg", "payload": {"type": "thread_settings_applied"}})
                + "\n"
            )
        self.assertFalse(context.codex_activity_between(str(self.path), AT + 6, AT + 10))
        with self.path.open("a") as f:
            f.write(json.dumps(event("task_started", 9, turn_id="turn-b")) + "\n")
        self.assertTrue(context.codex_activity_between(str(self.path), AT + 6, AT + 10))

    def test_a_person_cannot_treat_an_unreadable_command_as_an_empty_check_history(self) -> None:
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows[3]["payload"]["item"]["command"] = ["unrecognized-shell"]
        write(self.path, rows)
        with self.assertRaises(context.FrozenCheckCutoffUnreachableError):
            context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)

    def test_a_person_cannot_lose_a_named_worker_when_its_rollout_is_missing(self) -> None:
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows.insert(
            3,
            {
                "timestamp": rows[2]["timestamp"],
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "call_id": "spawn-a",
                    "name": "spawn_agent",
                    "arguments": "{}",
                },
            },
        )
        write(self.path, rows)
        with self.assertRaises(context.FrozenCheckCutoffUnreachableError):
            context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)

    def test_a_person_keeps_changed_after_as_it_was_before_a_later_write(self) -> None:
        _, press = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        late = event(
            "item_completed",
            30,
            item={
                "type": "FileChange",
                "id": "write-a",
                "status": "completed",
                "changes": {
                    "/synthetic/project/example.py": {
                        "type": "update",
                        "content": "",
                        "unified_diff": "",
                        "move_path": None,
                    }
                },
            },
            completed_at_ms=int((AT + 30) * 1000),
            started_at_ms=int((AT + 29) * 1000),
        )
        with self.path.open("a") as f:
            f.write(json.dumps(late) + "\n")
        _, before = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 10)
        _, after = context.frozen_codex_checks(self.config, str(self.path), SID, until=AT + 40)
        self.assertEqual(before.changed_after, press.changed_after)
        self.assertNotEqual(before.changed_after, after.changed_after)

    def test_a_person_cannot_retain_a_temporary_raw_cut_after_an_exception(self) -> None:
        import os  # noqa: PLC0415

        with (
            self.assertRaisesRegex(ValueError, "synthetic refusal"),
            context.frozen_codex_sources(self.config, str(self.path), until=AT + 10) as (cut, _),
        ):
            self.assertEqual(os.stat(cut).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(Path(cut).parent).st_mode & 0o777, 0o700)
            raise ValueError("synthetic refusal")
        self.assertFalse(Path(cut).exists())

    def test_a_person_cannot_call_a_conflicting_or_nonfinal_reply_whole(self) -> None:
        whole, _ = context.frozen_codex_agent_messages(
            self.config, str(self.path), SID, until=AT + 10
        )
        wanted = [
            {"id": fact["fact_id"], "at": fact["at"], "author": "agent", "type": "agent_message"}
            for fact in whole
        ]
        self.assertEqual(
            context.codex_newest_final_words(self.config, str(self.path), SID, wanted)["outcome"],
            "whole",
        )
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows[5]["payload"]["phase"] = "commentary"
        write(self.path, rows)
        self.assertEqual(
            context.codex_newest_final_words(self.config, str(self.path), SID, wanted)["outcome"],
            "not-final",
        )
        rows.append({**rows[5], "payload": {**rows[5]["payload"], "phase": "final_answer"}})
        write(self.path, rows)
        self.assertEqual(
            context.codex_newest_final_words(self.config, str(self.path), SID, wanted)["outcome"],
            "unproven",
        )
