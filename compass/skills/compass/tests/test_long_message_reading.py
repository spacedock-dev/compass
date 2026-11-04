"""Later source words reach a bounded producer without becoming new evidence identities."""

from __future__ import annotations

import dataclasses
import json
import re
import tempfile
import unittest
from pathlib import Path

from compass_runtime import (
    http_api,
    project_context,
    reading,
    reading_policy,
    record_pages,
    session_source,
    session_summary,
    summary_store,
)
from compass_runtime.config import build_runtime_config

from .test_session_summary import Replies, entry


class SummaryMessageTextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = build_runtime_config(
            environ={"HOME": "/synthetic"},
            platform_name="linux",
            os_name="posix",
            launcher_path=Path("/synthetic/server.py"),
        )
        self.coverage = session_source.SourceCoverage(True, None, 0, 100, (), "read", "read")

    def test_later_user_and_agent_words_reach_the_summary(self) -> None:
        rows = [
            entry(1, "person", "Review the parser. " + "context " * 200 + "LATE_PERSON 界🙂"),
            entry(2, "agent", "I read parser.py. " + "context " * 200 + "LATE_AGENT 界🙂"),
        ]
        model = Replies()
        result = session_summary.summarize(
            rows, self.coverage, "claude", config=self.config, model=model, clock=lambda: 0
        )
        self.assertEqual("ok", result.state)
        record = model.prompts[0].split("Record:\n", 1)[1]
        self.assertIn("LATE_PERSON 界🙂", record)
        self.assertIn("LATE_AGENT 界🙂", record)

    def test_long_message_fragments_cover_the_original_text_and_cite_one_fact(self) -> None:
        words = "Review parser. " + "界🙂 prose " * 300 + "LATE_FINDING"
        model = Replies()
        result = session_summary.summarize(
            [entry(1, "person", words)],
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, session_summary_window_bytes=800),
            model=model,
            clock=lambda: 0,
        )
        windows = [p.split("Record:\n", 1)[1] for p in model.prompts if "Reply with one" in p]
        self.assertGreater(len(windows), 1)
        fragments: list[str] = []
        for window in windows:
            self.assertLessEqual(len(window.encode()), 800)
            for line in window.splitlines():
                match = re.fullmatch(r"\[1\] asked \(characters (\d+)-(\d+) of (\d+)\): (.*)", line)
                self.assertIsNotNone(match, line)
                assert match is not None
                fragment = json.loads(match[4])
                self.assertEqual(len("".join(fragments)), int(match[1]))
                self.assertEqual(len(fragment), int(match[2]) - int(match[1]))
                self.assertEqual(len(words), int(match[3]))
                fragments.append(fragment)
        self.assertEqual(words, "".join(fragments))
        self.assertEqual(
            {"fact-1"},
            {c for b in result.blocks for p in b.phases for row in p.bullets for c in row.cites},
        )

    def test_stored_fragment_span_survives_decode(self) -> None:
        model = Replies()
        result = session_summary.summarize(
            [entry(1, words="review " * 500)],
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, session_summary_window_bytes=800),
            model=model,
            clock=lambda: 0,
        )
        value = result.as_dict()
        self.assertTrue(summary_store._valid(value, summary_store._SUMMARY))
        restored = summary_store._decode_summary(value)
        self.assertEqual(result.blocks[0].span, restored.blocks[0].span)
        self.assertIsNotNone(restored.blocks[0].span)

    def test_update_resumes_the_unread_remainder_of_an_unchanged_message(self) -> None:
        rows = [entry(1, words="review " * 500 + "LATE_REMAINDER")]
        config = dataclasses.replace(self.config, session_summary_window_bytes=800)
        now = [0.0]

        def after_part(_result: session_summary.Summary, part: int, _parts: int) -> None:
            if part == 1:
                now[0] = 600.0

        first = session_summary.summarize(
            rows,
            self.coverage,
            "claude",
            config=config,
            model=Replies(),
            clock=lambda: now[0],
            on_part=after_part,
        )
        self.assertEqual("partial", first.state)
        model = Replies()
        result = session_summary.update(
            first,
            rows,
            self.coverage,
            session_source.SourceChange("unchanged"),
            config=config,
            model=model,
            clock=lambda: 0,
        )
        self.assertGreater(len(model.prompts), 0)
        self.assertIs(first.blocks[0], result.blocks[0])
        self.assertIn("LATE_REMAINDER", "\n".join(model.prompts))
        span = first.blocks[0].span
        assert span is not None
        self.assertIn(f"characters {span['last_offset']}-", model.prompts[0])
        self.assertEqual("ok", result.state)

    def test_changed_text_version_refuses_offset_reuse(self) -> None:
        rows = [entry(1, words="review " * 500)]
        result = session_summary.summarize(
            rows, self.coverage, "claude", config=self.config, model=Replies(), clock=lambda: 0
        )
        block = result.blocks[0]
        assert block.span is not None
        prior = dataclasses.replace(
            result, blocks=(dataclasses.replace(block, span={**block.span, "text_version": 999}),)
        )
        report = session_summary.change_report(
            prior, rows, session_source.SourceChange("unchanged")
        )
        self.assertEqual("summarize_again", report["action"])


class RequestedMessageTextTest(SummaryMessageTextTest):
    def test_a_missing_source_never_proves_every_agent_word_was_read(self) -> None:
        row: reading.LedgerEntry = {
            "id": "a", "at": 10.0, "type": "agent_message", "by": "agent",
            "author": "agent", "source": "transcript", "summary": "The agent spoke",
            "agent_words": json.dumps("An old excerpt with no source length"),
        }
        _, selection = reading.build_prompt(
            [row], goal="Review parser", max_bytes=16000, message_lookup=lambda _wanted, _cap: []
        )
        self.assertFalse(selection.agent_words_whole)

    def test_budgeted_message_projection_holds_only_the_words_sent(self) -> None:
        row: reading.LedgerEntry = {
            "id": "a", "at": 10.0, "type": "agent_message", "by": "agent",
            "author": "agent", "source": "transcript", "summary": "The agent spoke",
            "agent_words": json.dumps("An old excerpt"),
        }
        prompt, selection = reading.build_prompt(
            [row], goal="Review parser", max_bytes=16000,
            message_lookup=lambda _wanted, _cap: [{
                "id": "a", "at": 10.0, "words": "prose " * 5000 + "UNREAD_END",
                "total": 30010,
            }],
        )
        self.assertLessEqual(len(prompt.encode()), 16000)
        self.assertNotIn("UNREAD_END", prompt)
        self.assertNotIn("UNREAD_END", json.dumps(selection.entries))
        self.assertFalse(selection.agent_words_whole)
        self.assertIn("read only in part", reading.cutoff_text(selection.entries, 1, 20))

    def test_prior_allow_cannot_authorize_wider_message_content(self) -> None:
        for harness, previous in (("claude", 4), ("codex", 1)):
            with self.subTest(harness=harness):
                covered, _ = reading_policy._covered(
                    {"codex": True},
                    {"codex": "OpenAI"},
                    {"codex": "OpenAI"},
                    {"codex": (previous, "OpenAI")},
                    content=http_api._press_content(harness),
                )
                self.assertFalse(covered["codex"])

    def test_older_source_words_reach_only_the_requested_prompt(self) -> None:
        lookup = getattr(project_context, "transcript_message_words", None)
        self.assertTrue(callable(lookup), "A press needs a private, bounded wider-text lookup")
        assert lookup is not None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            records = [
                {
                    "type": role,
                    "uuid": f"u-{n}",
                    "timestamp": f"2026-11-04T00:00:0{n}Z",
                    "message": {
                        "role": role,
                        "content": [
                            {"type": "text", "text": "Review parser. " + "context " * 200 + marker}
                        ],
                    },
                }
                for n, (role, marker) in enumerate(
                    [
                        ("user", "LATE_PERSON 界🙂"),
                        ("assistant", "LATE_OLDER 界🙂"),
                        ("assistant", "LATE_NEWEST 界🙂"),
                    ],
                    1,
                )
            ]
            raw = [json.dumps(row).encode() for row in records]
            path.write_bytes(b"\n".join(raw) + b"\n")
            facts = [record_pages._fact(self.config, line, "claude", "s") for line in raw]
            ledger = reading.build_ledger(
                [fact for fact in facts if fact is not None], "claude", "s", read_agent_words=True
            )
            stamp = project_context.transcript_stamp(str(path))
            prompt, selection = reading.build_prompt(
                ledger,
                goal="Review parser",
                max_bytes=512 * 1024,
                message_lookup=lambda wanted, cap: lookup(
                    self.config,
                    str(path),
                    "claude",
                    "s",
                    wanted,
                    max_bytes=cap,
                    expected_stamp=stamp,
                ),
            )
            for marker in ("LATE_PERSON", "LATE_OLDER", "LATE_NEWEST"):
                self.assertIn(marker, prompt)
            self.assertEqual(
                [row["id"] for row in ledger], [row["id"] for row in selection.entries]
            )
            self.assertTrue(selection.agent_words_whole)
            ordinary, _ = reading.build_prompt(ledger, goal="Review parser", max_bytes=512 * 1024)
            self.assertNotIn("LATE_OLDER", ordinary)
            public = json.dumps(project_context.for_page({"facts": facts}))
            self.assertNotIn("LATE_OLDER", public)

    def test_legacy_clipped_summary_cannot_skip_message_remainders(self) -> None:
        rows = [entry(1, words="review " * 500)]
        result = session_summary.summarize(
            rows, self.coverage, "claude", config=self.config, model=Replies(), clock=lambda: 0
        )
        prior = dataclasses.replace(
            result,
            blocks=tuple(
                dataclasses.replace(
                    block, span=None, fingerprint=session_summary._fingerprint(rows)
                )
                for block in result.blocks
            ),
        )
        report = session_summary.change_report(
            prior, rows, session_source.SourceChange("unchanged")
        )
        self.assertEqual("summarize_again", report["action"])
