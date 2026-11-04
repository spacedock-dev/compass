"""Original-source regressions from the adversarial long-message review; no live model."""

from __future__ import annotations

import dataclasses
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any

from compass_runtime import project_context, reading, record_pages, session_source, session_summary
from compass_runtime.config import build_runtime_config

from .test_session_summary import Replies, entry, phase

if TYPE_CHECKING:
    from collections.abc import Callable


class LongMessageCorrectionsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = build_runtime_config(
            environ={"HOME": "/synthetic"},
            platform_name="linux",
            os_name="posix",
            launcher_path=Path("/synthetic/server.py"),
        )
        self.coverage = session_source.SourceCoverage(True, None, 0, 100, (), "read", "read")
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        self.path = Path(self.home.name) / "s.jsonl"

    def source(
        self, records: list[dict[str, Any]]
    ) -> tuple[list[bytes], tuple[reading.LedgerEntry, ...]]:
        raw = [json.dumps(record).encode() for record in records]
        self.path.write_bytes(b"\n".join(raw) + b"\n")
        facts = [record_pages._fact(self.config, line, "claude", "s") for line in raw]
        return raw, reading.build_ledger(
            [fact for fact in facts if fact is not None], "claude", "s", read_agent_words=True
        )

    def recover(self, wanted: Any, cap: int) -> list[dict[str, Any]]:
        return project_context.transcript_message_words(
            self.config,
            str(self.path),
            "claude",
            "s",
            wanted,
            max_bytes=cap,
            expected_stamp=project_context.transcript_stamp(str(self.path)),
        )

    def test_raw_split_command_credential_never_reaches_either_producer(self) -> None:
        tail = "api03-" + "Q" * 70  # Deliberately fake; the raw newline is the privacy boundary.
        words = (
            "<command-message>review</command-message><command-name>/review</command-name>"
            "<command-args>"
            + "context " * 200
            + "sk-ant-\n"
            + tail
            + " LATE_SAFE_TEXT</command-args>"
        )
        record = {
            "type": "user",
            "uuid": "person-1",
            "timestamp": "2026-11-04T00:00:01Z",
            "message": {"role": "user", "content": words},
        }
        raw, ledger = self.source([record])
        prompt, _ = reading.build_prompt(
            ledger,
            goal="Review parser",
            max_bytes=16000,
            message_lookup=self.recover,
        )
        source = session_source._message(self.config, raw[0], record, "claude", "s")
        assert source is not None
        model = Replies()
        session_summary.summarize(
            [source],
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, session_summary_window_bytes=800),
            model=model,
            clock=lambda: 0,
        )
        for sent in (prompt, "\n".join(model.prompts)):
            with self.subTest(producer="reading" if sent == prompt else "summary"):
                self.assertNotIn(tail, sent)
                self.assertNotIn("sk-ant-", sent)
                self.assertIn("LATE_SAFE_TEXT", sent)
                self.assertIn("review", sent)

    def test_oversized_queued_duplicate_uses_typing_time_in_both_record_orders(self) -> None:
        def queued(words: str) -> dict[str, Any]:
            return {
                "type": "attachment",
                "timestamp": "2026-11-04T00:03:00Z",
                "attachment": {
                    "type": "queued_command",
                    "timestamp": "2026-11-04T00:00:01Z",
                    "commandMode": "prompt",
                    "origin": {"kind": "human"},
                    "prompt": words,
                },
            }

        short = queued("Review parser.")
        oversized = queued("Review parser. " + "x" * project_context.PRESS_TEXT_MAX_CHARS)
        for records in ([short, oversized], [oversized, short]):
            with self.subTest(short_first=records[0] is short):
                _, ledger = self.source(records)
                self.assertEqual(ledger[0]["id"], ledger[1]["id"])
                selected = ledger[:1]
                self.assertEqual([], self.recover(selected, 16000))
                _, selection = reading.build_prompt(
                    selected,
                    goal="Review parser",
                    max_bytes=16000,
                    message_lookup=self.recover,
                )
                self.assertIn(
                    "read only in part",
                    reading.cutoff_text(selection.entries, 1, ledger[0]["at"] + 10),
                )

    def assert_fresh_envelope(
        self, result: session_summary.Summary, rows: list[session_source.SourceEntry]
    ) -> None:
        self.assertNotEqual("refused", result.state)
        self.assertEqual(rows[0].fact_id, result.blocks[0].first)
        self.assertEqual(rows[-1].fact_id, result.blocks[-1].last)
        first, last = result.blocks[0].span, result.blocks[-1].span
        assert first is not None and last is not None
        self.assertEqual(0, first["first_offset"])
        self.assertEqual(len(" ".join((rows[-1].words or "").split())), last["last_offset"])
        self.assertIsNone(
            session_summary.change_report(result, rows, session_source.SourceChange("unchanged"))[
                "reason"
            ]
        )

    @staticmethod
    def publisher(
        values: list[session_summary.Summary],
    ) -> Callable[[session_summary.Summary, int, int], None]:
        def append(value: session_summary.Summary, _part: int, _parts: int) -> None:
            values.append(value)

        return append

    def test_small_output_bound_keeps_discarded_source_and_character_prefixes(self) -> None:
        cases = (
            ([entry(n + 1, words="Review " + "w" * 70) for n in range(10)], 150),
            ([entry(1, words="Review " + "word " * 1200)], 800),
        )
        for rows, window_bytes in cases:
            with self.subTest(window_bytes=window_bytes):
                config = dataclasses.replace(
                    self.config,
                    session_summary_window_bytes=window_bytes,
                    session_summary_max_windows=2,
                    session_summary_max_bytes=2000,
                )
                published: list[session_summary.Summary] = []
                result = session_summary.summarize(
                    rows,
                    self.coverage,
                    "claude",
                    config=config,
                    model=Replies(),
                    clock=lambda: 0,
                    on_part=self.publisher(published),
                )
                self.assertEqual("bytes", result.reason)
                for value in [*published, result]:
                    self.assertLessEqual(session_summary._json_bytes(value), 2000)
                    self.assert_fresh_envelope(value, rows)

    @staticmethod
    def large_reply(prompt: str, **_kwargs: Any) -> tuple[str, str]:
        number = int(re.findall(r"^\[(\d+)\]", prompt, re.MULTILINE)[0])
        if prompt.startswith("Write the opening"):
            return json.dumps({"lede": "The person asked for a review.", "cites": [number]}), "ok"
        part = phase(
            [number], "The person asked for " + "🙂" * 180, "Reviewing the parser", "asked"
        )
        part["bullets"] *= 6
        return json.dumps({"phases": [part] * 4}, ensure_ascii=False), "ok"

    def test_output_bound_keeps_update_prefix_with_original_nonzero_numbers(self) -> None:
        old = [entry(1), entry(2)]
        prior = session_summary.summarize(
            old, self.coverage, "claude", config=self.config, model=Replies(), clock=lambda: 0
        )
        rows = [*old, *(entry(n, words="Review " + "w" * 70) for n in range(3, 13))]
        config = dataclasses.replace(
            self.config,
            session_summary_window_bytes=150,
            session_summary_max_windows=2,
            session_summary_max_bytes=6000,
        )
        published: list[session_summary.Summary] = []
        result = session_summary.update(
            prior,
            rows,
            self.coverage,
            session_source.SourceChange("appended", appended=tuple(e.fact_id for e in rows[2:])),
            config=config,
            model=self.large_reply,
            clock=lambda: 0,
            on_part=self.publisher(published),
        )
        self.assertEqual("bytes", result.reason)
        self.assertIs(prior.blocks[0], result.blocks[0])
        for value in [*published, result]:
            self.assert_fresh_envelope(value, rows)

    def test_output_bound_keeps_prefix_when_resuming_inside_a_message(self) -> None:
        rows = [entry(1, words="Review " + "word " * 1200)]
        config = dataclasses.replace(self.config, session_summary_window_bytes=800)
        now = [0.0]

        def stop_after_first(_value: session_summary.Summary, part: int, _parts: int) -> None:
            if part == 1:
                now[0] = 600.0

        prior = session_summary.summarize(
            rows,
            self.coverage,
            "claude",
            config=config,
            model=Replies(),
            clock=lambda: now[0],
            on_part=stop_after_first,
        )
        config = dataclasses.replace(
            config, session_summary_max_windows=2, session_summary_max_bytes=6000
        )
        published: list[session_summary.Summary] = []
        result = session_summary.update(
            prior,
            rows,
            self.coverage,
            session_source.SourceChange("unchanged"),
            config=config,
            model=self.large_reply,
            clock=lambda: 0,
            on_part=self.publisher(published),
        )
        self.assertEqual("bytes", result.reason)
        self.assertIs(prior.blocks[0], result.blocks[0])
        for value in [*published, result]:
            self.assert_fresh_envelope(value, rows)

    def test_surplus_growth_still_projects_only_the_partial_text_sent(self) -> None:
        words = (
            "I inspected parser. "
            + ("界🙂 " + chr(34) + "quoted" + chr(34) + chr(92)) * 4000
            + "UNREAD_END"
        )
        _, ledger = self.source(
            [
                {
                    "type": "assistant",
                    "uuid": "ordinary",
                    "sessionId": "s",
                    "timestamp": "2026-11-04T00:00:01Z",
                    "message": {"role": "assistant", "content": words, "stop_reason": "tool_use"},
                },
            ]
        )
        prompt, selection = reading.build_prompt(
            ledger,
            goal="Review parser",
            max_bytes=8000,
            message_lookup=self.recover,
        )
        sent = selection.entries[0]
        projected = json.loads(sent["agent_words"])
        self.assertLessEqual(len(prompt.encode()), 8000)
        self.assertIn(sent["agent_words"], prompt)
        self.assertEqual(len(projected), sent["text_read"])
        self.assertEqual(words[: len(projected)], projected)
        self.assertLess(sent["text_read"], sent["text_total"])
        self.assertNotIn("UNREAD_END", prompt)
        self.assertFalse(selection.agent_words_whole)
        self.assertIn(
            "read only in part", reading.cutoff_text(selection.entries, 1, sent["at"] + 10)
        )

    def test_partial_ordinary_agent_row_uses_surplus_after_the_final_reply(self) -> None:
        for repeats, final in (
            (110, "The review is ready." + "done " * 650),
            (625, "The review is ready."),
        ):
            with self.subTest(ordinary_length=repeats):
                originals = [
                    "Review parser.",
                    "I inspected parser. " + "context " * repeats + "LATE_FINDING",
                    final,
                ]
                records = [
                    {
                        "type": role,
                        "uuid": f"m{n}",
                        "sessionId": "s",
                        "timestamp": f"2026-11-04T00:00:0{n + 1}Z",
                        "message": {
                            "role": role,
                            "content": words,
                            "stop_reason": "end_turn" if n == 2 else "tool_use" if n == 1 else None,
                        },
                    }
                    for n, (role, words) in enumerate(
                        zip(("user", "assistant", "assistant"), originals, strict=True)
                    )
                ]
                _, ledger = self.source(records)

                def newest(wanted: Any) -> dict[str, Any]:
                    return project_context.transcript_newest_final_words(
                        self.config,
                        str(self.path),
                        "claude",
                        "s",
                        wanted,
                        expected_stamp=project_context.transcript_stamp(str(self.path)),
                    )

                prompt, selection = reading.build_prompt(
                    ledger,
                    goal="Review parser",
                    max_bytes=16000,
                    message_lookup=self.recover,
                    final_lookup=newest,
                )
                self.assertLessEqual(len(prompt.encode()), 16000)
                self.assertEqual(
                    [row["id"] for row in ledger], [row["id"] for row in selection.entries]
                )
                self.assertIn("LATE_FINDING", prompt)
                self.assertIn(final.strip(), prompt)
                older = selection.entries[1]
                self.assertEqual(older["text_total"], older["text_read"])
