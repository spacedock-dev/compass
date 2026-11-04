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

from .test_agent_words import _agent, _check, _person
from .test_session_summary import Replies, entry, phase


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
        change = session_source.SourceChange("unchanged")
        self.assertEqual("update", session_summary.change_report(first, rows, change)["action"])
        planned = session_summary.plan(rows, "claude", config=config, prior=first, change=change)
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
        self.assertEqual(planned["parts"], len(model.prompts))
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

    def test_lede_does_not_recover_an_unread_fragment_from_a_cited_fact(self) -> None:
        model = Replies(
            {"phases": [phase([1], "The person asked for a parser review.", kind="asked")]},
            ("", "failed"),
            ("", "failed"),
            {"lede": "The person asked for a parser review.", "cites": [1]},
        )
        result = session_summary.summarize(
            [entry(1, words="Review parser. " + "x" * 850 + "UNREAD_LATE")],
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, session_summary_window_bytes=700),
            model=model,
            clock=lambda: 0,
        )
        self.assertEqual("no_output", result.blocks[1].reason)
        self.assertTrue(model.prompts[-1].startswith("Write the opening"))
        self.assertNotIn("UNREAD_LATE", model.prompts[-1])

    def test_masking_happens_before_fragment_boundaries(self) -> None:
        secret = "sample-PrivateValue-0123456789" * 30
        words = 'Review parser. password="' + secret + '" ' + "界🙂 " * 300 + "LATE_PUBLIC"
        model = Replies()
        result = session_summary.summarize(
            [entry(1, words=words)],
            self.coverage,
            "claude",
            config=dataclasses.replace(self.config, session_summary_window_bytes=700),
            model=model,
            clock=lambda: 0,
        )
        sent = "\n".join(model.prompts)
        self.assertNotIn("PrivateValue", sent)
        self.assertIn("LATE_PUBLIC", sent)
        self.assertNotIn("LATE_PUBLIC", json.dumps(result.as_dict()))
        self.assertNotIn("\ufffd", sent)

    def test_changed_canonical_late_text_invalidates_a_saved_range(self) -> None:
        rows = [entry(1, words="review " * 500)]
        prior = session_summary.summarize(
            rows, self.coverage, "claude", config=self.config, model=Replies(), clock=lambda: 0
        )
        changed = [dataclasses.replace(rows[0], words="review " * 499 + "changed")]
        report = session_summary.change_report(
            prior, changed, session_source.SourceChange("unchanged")
        )
        self.assertEqual("summarize_again", report["action"])


class RequestedMessageTextTest(SummaryMessageTextTest):
    def test_private_lookup_masks_before_retention_and_refuses_source_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            secret = "Private-test-value-0123456789" * 20
            record = {
                "type": "user",
                "uuid": "u",
                "timestamp": "2026-11-04T00:00:01Z",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": 'Review parser. password="' + secret + '" ' + "界🙂 " * 500,
                        }
                    ],
                },
            }
            raw = json.dumps(record).encode()
            path.write_bytes(raw + b"\n")
            fact = record_pages._fact(self.config, raw, "claude", "s")
            assert fact is not None
            wanted = reading.build_ledger([fact], "claude", "s")
            stamp = project_context.transcript_stamp(str(path))
            result = project_context.transcript_message_words(
                self.config,
                str(path),
                "claude",
                "s",
                wanted,
                max_bytes=120,
                expected_stamp=stamp,
            )
            self.assertEqual(1, len(result))
            self.assertLessEqual(sum(len(row["words"].encode()) for row in result), 120)
            self.assertGreater(result[0]["total"], len(result[0]["words"]))
            self.assertNotIn("Private-test-value", json.dumps(result))
            path.write_bytes(raw + b"\n\n")
            self.assertEqual(
                [],
                project_context.transcript_message_words(
                    self.config,
                    str(path),
                    "claude",
                    "s",
                    wanted,
                    max_bytes=120,
                    expected_stamp=stamp,
                ),
            )

    def test_conflicting_duplicate_cannot_restore_later_words(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"

            def source(suffix: str) -> bytes:
                return json.dumps(
                    {
                        "type": "assistant",
                        "uuid": "same",
                        "timestamp": "2026-11-04T00:00:01Z",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "I reviewed parser. " + "context " * 200 + suffix,
                                }
                            ],
                        },
                    }
                ).encode()

            raw = source("FIRST_LATE")
            path.write_bytes(raw + b"\n" + source("CONFLICTING_LATE") + b"\n")
            fact = record_pages._fact(self.config, raw, "claude", "s")
            assert fact is not None
            wanted = reading.build_ledger([fact], "claude", "s", read_agent_words=True)
            self.assertEqual(
                [],
                project_context.transcript_message_words(
                    self.config,
                    str(path),
                    "claude",
                    "s",
                    wanted,
                    max_bytes=16000,
                    expected_stamp=project_context.transcript_stamp(str(path)),
                ),
            )

    def test_oversized_duplicate_cannot_make_an_older_excerpt_look_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            record = {
                "type": "assistant",
                "uuid": "same",
                "timestamp": "2026-11-04T00:00:01Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Review parser."}],
                },
            }
            raw = json.dumps(record).encode()
            fact = record_pages._fact(self.config, raw, "claude", "s")
            assert fact is not None
            record["message"] = {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Review parser." + " context" * 40000,
                    }
                ],
            }
            path.write_bytes(raw + b"\n" + json.dumps(record).encode() + b"\n")
            self.assertEqual(
                [],
                project_context.transcript_message_words(
                    self.config,
                    str(path),
                    "claude",
                    "s",
                    reading.build_ledger([fact], "claude", "s", read_agent_words=True),
                    max_bytes=16000,
                    expected_stamp=project_context.transcript_stamp(str(path)),
                ),
            )

    def test_adopted_goal_excerpt_does_not_suppress_later_source_words(self) -> None:
        words = "Review parser. " + "context " * 300 + "LATE_CONSTRAINT"
        row: reading.LedgerEntry = {
            "id": "p",
            "at": 10.0,
            "type": "user_message",
            "by": "person",
            "author": "person",
            "source": "transcript",
            "summary": "Review parser.",
            "words": words[:1000],
        }
        prompt, _ = reading.build_prompt(
            [row],
            goal="Review parser.",
            goal_words=words[:1000],
            goal_fact="p",
            max_bytes=16000,
            message_lookup=lambda _wanted, _cap: [
                {
                    "id": "p",
                    "at": 10.0,
                    "words": words,
                    "total": len(words),
                }
            ],
        )
        self.assertIn("LATE_CONSTRAINT", prompt)

    def test_a_missing_source_never_proves_every_agent_word_was_read(self) -> None:
        row: reading.LedgerEntry = {
            "id": "a",
            "at": 10.0,
            "type": "agent_message",
            "by": "agent",
            "author": "agent",
            "source": "transcript",
            "summary": "The agent spoke",
            "agent_words": json.dumps("An old excerpt with no source length"),
        }
        _, selection = reading.build_prompt(
            [row], goal="Review parser", max_bytes=16000, message_lookup=lambda _wanted, _cap: []
        )
        self.assertFalse(selection.agent_words_whole)

    def test_budgeted_message_projection_holds_only_the_words_sent(self) -> None:
        row: reading.LedgerEntry = {
            "id": "a",
            "at": 10.0,
            "type": "agent_message",
            "by": "agent",
            "author": "agent",
            "source": "transcript",
            "summary": "The agent spoke",
            "agent_words": json.dumps("An old excerpt"),
        }
        prompt, selection = reading.build_prompt(
            [row],
            goal="Review parser",
            max_bytes=16000,
            message_lookup=lambda _wanted, _cap: [
                {
                    "id": "a",
                    "at": 10.0,
                    "words": "prose " * 5000 + "UNREAD_END",
                    "total": 30010,
                }
            ],
        )
        self.assertLessEqual(len(prompt.encode()), 16000)
        self.assertNotIn("UNREAD_END", prompt)
        self.assertNotIn("UNREAD_END", json.dumps(selection.entries))
        self.assertFalse(selection.agent_words_whole)
        self.assertIn("read only in part", reading.cutoff_text(selection.entries, 1, 20))

    def test_wider_words_keep_failed_checks_and_do_not_count_checks_as_partial_messages(
        self,
    ) -> None:
        facts = [_person("p", 10, "Review parser"), _check(at=20)]
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={})
        prompt, selection = reading.build_prompt(
            ledger,
            goal="Review parser",
            max_bytes=16000,
            message_lookup=lambda _wanted, _cap: [
                {"id": "p", "at": 10, "words": "context " * 5000, "total": 40000}
            ],
        )
        self.assertLessEqual(len(prompt.encode()), 16000)
        self.assertEqual({"p", "check-1"}, {row["id"] for row in selection.entries})
        self.assertIn("failed", prompt)
        self.assertFalse(selection.unread_failures)
        self.assertIn(
            "1 message was read only in part", reading.cutoff_text(selection.entries, 2, 30)
        )

    def test_wider_older_words_leave_the_newest_final_its_whole_reply_priority(self) -> None:
        facts = [_agent("old", 10, "old excerpt"), _agent("final", 20, "final excerpt")]
        ledger = reading.build_ledger(facts, "claude", "s1", read_agent_words=True)
        final = "Final recorded reply. " * 90 + "FINAL_END"
        prompt, selection = reading.build_prompt(
            ledger,
            goal="Review parser",
            max_bytes=16000,
            final_lookup=lambda _wanted: {
                "outcome": "whole",
                "fact_id": "final",
                "at": 20,
                "words": final,
            },
            message_lookup=lambda _wanted, _cap: [
                {"id": "old", "at": 10, "words": "older " * 5000, "total": 30000},
                {"id": "final", "at": 20, "words": "wrong alternative", "total": 17},
            ],
        )
        self.assertLessEqual(len(prompt.encode()), 16000)
        self.assertIn("FINAL_END", prompt)
        self.assertNotIn("wrong alternative", prompt)
        self.assertEqual("whole", selection.newest_final)
        self.assertFalse(selection.agent_words_whole)

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

    def test_codex_requested_person_message_recovers_words_past_the_shared_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rollout.jsonl"
            words = "Review parser. " + "context " * 200 + "CODEX_LATE"
            raw = json.dumps(
                {
                    "timestamp": "2026-11-04T00:00:01Z",
                    "type": "response_item",
                    "payload": {"type": "message", "role": "user", "content": words},
                }
            ).encode()
            path.write_bytes(raw + b"\n")
            fact = record_pages._fact(self.config, raw, "codex", "s")
            assert fact is not None
            ledger = reading.build_ledger([fact], "codex", "s")
            recovered = project_context.transcript_message_words(
                self.config,
                str(path),
                "codex",
                "s",
                ledger,
                max_bytes=16000,
                expected_stamp=project_context.transcript_stamp(str(path)),
            )
            self.assertEqual(words, recovered[0]["words"])
            prompt, _ = reading.build_prompt(
                ledger,
                goal="Review parser",
                max_bytes=16000,
                message_lookup=lambda _wanted, _cap: recovered,
            )
            self.assertIn("CODEX_LATE", prompt)
            self.assertNotIn("CODEX_LATE", json.dumps(project_context.for_page({"facts": [fact]})))

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
