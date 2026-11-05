"""Private request lineage reuses the raw-source owner over verified retained rows."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import project_context as context
from compass_runtime import (
    reading,
    reading_final_call,
    reading_native,
    reading_source,
    record_pages,
)
from compass_runtime import reading_source_collect as collector
from compass_runtime import reading_source_inventory as inventory
from compass_runtime.config import build_runtime_config

from .test_claude_checks import SHORT, SID, Transcript


class RecoveredRequestSourcesTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "session.jsonl"
        self.child_path = self.path.with_suffix("") / "subagents" / "agent-ab12.jsonl"
        self.config = build_runtime_config(
            environ={"HOME": str(self.root), "COMPASS_HOME": str(self.root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.parent = Transcript(self.root)

    def collect(self, **options: Any) -> collector.Collection:
        raw = options.pop("raw", None)
        if raw is None:
            self.parent.save(self.path)
        else:
            self.path.write_bytes(raw)
        frozen = inventory.freeze(
            str(self.path), "claude", SHORT, max_entries=100, max_streams=10, max_seconds=1
        )
        result = collector.collect(
            self.config,
            frozen,
            ancillary=collector.Ancillary(str(self.root)),
            clock=options.pop("clock", lambda: 0.0),
            **options,
        )
        self.assertTrue(
            hasattr(result, "recovered_sources"), "retained request-source proofs are missing"
        )
        return result

    def oracle(self) -> list[dict[str, Any]]:
        self.parent.save(self.path)
        stamp = context.transcript_stamp(str(self.path))
        assert stamp is not None
        result = context._read_user_sources(
            self.config,
            str(self.path),
            "claude",
            SHORT,
            stamp,
            False,
            None,
        )
        assert result is not None
        return result

    def test_complete_small_corpus_matches_raw_owner_with_no_rescan_or_canonical_mutation(
        self,
    ) -> None:
        self.parent.prompt("Write JSON.")
        self.parent.bash("pytest", "1 passed")
        self.parent.prompt(
            "<command-message>review</command-message><command-name>/review</command-name><command-args>Inspect 界 carefully.</command-args>"
        )
        self.parent.rows.append(
            {
                "type": "attachment",
                "timestamp": "2026-11-05T02:00:00Z",
                "attachment": {
                    "type": "queued_command",
                    "timestamp": "2026-11-05T01:00:00Z",
                    "commandMode": "prompt",
                    "origin": {"kind": "human"},
                    "prompt": "Keep the queued direction.",
                },
            }
        )
        question = self.parent._entry(
            "user", [{"type": "tool_result", "tool_use_id": "ask", "content": "Answered."}]
        )
        question["toolUseResult"] = {
            "questions": [{"question": "Format?", "header": "Format", "options": []}],
            "answers": {"Format?": "JSON"},
            "annotations": {"Format?": {"notes": "Keep Unicode."}},
        }
        for flags in ({"isMeta": True}, {"isSidechain": True}):
            self.parent._entry("user", [{"type": "text", "text": "NOT PARENT"}], **flags)
        child = Transcript(self.root)
        child.prompt("CHILD REQUEST")
        for row in child.rows:
            row["isSidechain"] = True
        child.save(self.child_path)
        expected = self.oracle()
        canonical = reading_source.from_complete_scan(
            self.config, context._live_check_scan(self.config, str(self.path)), "claude", SHORT
        )
        with (
            mock.patch.object(
                context, "transcript_user_facts", side_effect=AssertionError("legacy lookup")
            ),
            mock.patch.object(
                context, "_read_user_sources", side_effect=AssertionError("legacy read")
            ),
            mock.patch.object(
                record_pages, "scan_source", side_effect=AssertionError("source rescan")
            ),
        ):
            result = self.collect(page_bytes=127)
        self.assertEqual("", result.reason)
        assert result.recovered_sources is not None
        assert result.evidence is not None
        self.assertEqual(tuple(expected), result.recovered_sources)
        self.assertEqual(canonical, result.evidence)
        self.assertEqual(4, len(result.recovered_sources))
        self.assertTrue(all("request_source_digest" not in fact for fact in result.evidence.facts))
        self.assertNotIn("CHILD REQUEST", str(result.recovered_sources))
        total = self.path.stat().st_size + self.child_path.stat().st_size
        self.assertEqual(3 * total, result.usage.source_bytes)
        first = result.recovered_sources[0]
        with self.assertRaises(TypeError):
            # Deliberately attempt an invalid write through the public Mapping API.
            cast("Any", first)["request_source_digest"] = "invented"
        with self.assertRaises(TypeError):
            first["source_session"]["sid"] = "foreign"
        with self.assertRaises(TypeError):
            first["evidence"]["source"] = "invented"

    def test_immutable_owner_proof_is_accepted_only_for_exact_unique_person_and_saved_binding(
        self,
    ) -> None:
        self.parent.prompt("Write JSON")
        result = self.collect()
        assert result.recovered_sources is not None
        assert result.evidence is not None
        assert result.words is not None
        source = result.recovered_sources[0]
        available = reading.listed_request_sources(result.evidence.facts, result.recovered_sources)
        self.assertEqual([source], available)
        binding = reading.line_request_binding(
            available,
            source_id=source["fact_id"],
            text="Write JSON",
            harness="claude",
            sid=SHORT,
            now=source["at"] + 10,
        )
        self.assertIsNotNone(binding)
        revision = {
            "at": source["at"] + 10,
            "lines": [
                {
                    "text": "Write JSON",
                    "source": "entry",
                    "source_id": source["fact_id"],
                    "request": binding,
                }
            ],
        }
        self.assertEqual(
            {"line_1": source["at"]},
            reading.line_request_floors(revision, available, "claude", SHORT),
        )
        for patch in (
            {"request_source_digest": ""},
            {"request_words_digest": "0" * 64},
            {"source_session": {"harness": "claude", "sid": "foreign"}},
            {reading.COPIED_FLAG: True},
        ):
            with self.subTest(patch=patch):
                self.assertEqual(
                    {},
                    reading.line_request_floors(revision, [{**source, **patch}], "claude", SHORT),
                )
        copied = [{**fact, reading.COPIED_FLAG: True} for fact in result.evidence.facts]
        self.assertEqual([], reading.listed_request_sources(copied, result.recovered_sources))
        self.assertEqual(
            [],
            reading.listed_request_sources(
                result.evidence.facts, (*result.recovered_sources, *result.recovered_sources)
            ),
        )

    def test_raw_serialization_change_invalidates_saved_source_without_changing_canonical_words(
        self,
    ) -> None:
        self.parent.prompt("Write JSON")
        self.parent.rows[0]["source_marker"] = "FIRST"
        first = self.collect()
        assert first.recovered_sources is not None
        before = first.recovered_sources[0]
        raw = self.path.read_bytes().splitlines()[0]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), before["request_source_digest"])
        self.parent.rows[0]["source_marker"] = "OTHER"
        second = self.collect()
        assert second.recovered_sources is not None
        after = second.recovered_sources[0]
        self.assertEqual(first.evidence, second.evidence)
        self.assertEqual(before["fact_id"], after["fact_id"])
        self.assertEqual(before["request_words_digest"], after["request_words_digest"])
        self.assertNotEqual(before["request_source_digest"], after["request_source_digest"])
        binding = reading.line_request_binding(
            first.recovered_sources,
            source_id=before["fact_id"],
            text="Write JSON",
            harness="claude",
            sid=SHORT,
            now=before["at"] + 10,
        )
        line = {
            "text": "Write JSON",
            "source": "entry",
            "source_id": before["fact_id"],
            "request": binding,
        }
        self.assertIsNone(
            reading.line_request_at(
                line, second.recovered_sources, "claude", SHORT, until=before["at"] + 10
            )
        )

    def test_duplicate_and_same_time_sources_remain_ambiguous_even_after_owner_cap(self) -> None:
        for duplicate in (True, False):
            with self.subTest(duplicate=duplicate):
                self.parent.rows = []
                self.parent.prompt("First request.")
                first = copy.deepcopy(self.parent.rows[0])
                self.parent.prompt("Newest request.")
                if not duplicate:
                    first["message"]["content"][0]["text"] = "Conflicting same-time request."
                self.parent.rows.append(first)
                with mock.patch.object(context, "TRANSCRIPT_USER_FACTS_MAX", 2):
                    expected = self.oracle()
                    result = self.collect()
                assert result.recovered_sources is not None
                assert result.words is not None
                self.assertEqual(tuple(expected), result.recovered_sources)
                self.assertTrue(
                    any(f["request_source_digest"] == "" for f in result.recovered_sources)
                )
                self.assertLessEqual(len(result.recovered_sources), 2)

    def test_complete_ordinary_words_do_not_reconstruct_a_clipped_request_digest(self) -> None:
        self.parent.prompt("Write JSON. " + "context " * 300)
        result = self.collect()
        assert result.recovered_sources is not None
        assert result.evidence is not None
        assert result.words is not None
        self.assertEqual("whole", result.words[0].state)
        assert result.words[0].words is not None
        source = result.recovered_sources[0]
        self.assertEqual("", source["request_words_digest"])
        self.assertIsNone(
            reading.line_request_binding(
                result.recovered_sources,
                source_id=source["fact_id"],
                text=result.words[0].words,
                harness="claude",
                sid=SHORT,
                now=source["at"] + 10,
            )
        )

    def test_cancellation_deadline_and_retention_withhold_request_proofs(self) -> None:
        self.parent.prompt("Keep the request proof bounded.")
        original = context._direction_words
        stopped = False

        def stopping(*args: Any, **kwargs: Any) -> Any:
            nonlocal stopped
            result = original(*args, **kwargs)
            stopped = True
            return result

        def cancelled() -> bool:
            return stopped

        def clock() -> float:
            return 61.0 if stopped else 0.0

        for reason in ("cancelled", "time"):
            stopped = False
            options = {"cancelled": cancelled} if reason == "cancelled" else {"clock": clock}
            with mock.patch.object(context, "_direction_words", side_effect=stopping):
                result = self.collect(**options)
            self.assertEqual(reason, result.reason)
            self.assertTrue(result.source_verified)
            for field in ("evidence", "words", "final", "snapshot", "origins", "recovered_sources"):
                self.assertIsNone(getattr(result, field))
        full = self.collect()
        assert full.snapshot is not None
        self.assertEqual(full.usage, full.snapshot.account.usage)
        limited = self.collect(
            limits=replace(collector.Limits(), retained_bytes=full.usage.retained_bytes // 2)
        )
        self.assertEqual("retained_bytes", limited.reason)
        self.assertIsNone(limited.recovered_sources)
        self.assertIsNone(limited.snapshot)

    def test_lf_crlf_and_native_unicode_match_historical_raw_line_digests(self) -> None:
        self.parent.prompt("Write 界🙂 JSON.")
        line = json.dumps(self.parent.rows[0], ensure_ascii=False).encode("utf-8")
        digests = []
        for newline in (b"\n", b"\r\n"):
            with self.subTest(newline=newline):
                raw = line + newline
                expected = context._transcript_user_scan(self.config, raw, "claude", SHORT)
                result = self.collect(raw=raw, page_bytes=71)
                assert result.recovered_sources is not None
                self.assertEqual(tuple(expected), result.recovered_sources)
                source = result.recovered_sources[0]
                self.assertEqual(hashlib.sha256(line).hexdigest(), source["request_source_digest"])
                digests.append(source["request_source_digest"])
        self.assertEqual(digests[0], digests[1])

    def test_queued_identical_and_raw_conflicting_duplicates_never_prove_request_age(self) -> None:
        queued: dict[str, Any] = {
            "type": "attachment",
            "timestamp": "2026-11-05T02:00:00Z",
            "attachment": {
                "type": "queued_command",
                "timestamp": "2026-11-05T01:00:00Z",
                "commandMode": "prompt",
                "origin": {"kind": "human"},
                "prompt": 'Review parser. password="FIRST_SECRET"',
            },
        }
        for conflict in (False, True):
            with self.subTest(conflict=conflict):
                other = copy.deepcopy(queued)
                if conflict:
                    other["attachment"]["prompt"] = other["attachment"]["prompt"].replace(
                        "FIRST_SECRET", "OTHER_SECRET"
                    )
                self.parent.rows = [queued, other]
                expected = self.oracle()
                result = self.collect()
                assert result.recovered_sources is not None
                assert result.words is not None
                self.assertEqual(tuple(expected), result.recovered_sources)
                self.assertEqual(1, len(result.recovered_sources))
                self.assertEqual("", result.recovered_sources[0]["request_source_digest"])
                self.assertEqual("unavailable" if conflict else "whole", result.words[0].state)

    def test_real_native_preparation_and_final_freeze_keep_immutable_request_proof(self) -> None:
        self.path = self.root / (SID + ".jsonl")
        self.parent.prompt("Write JSON")
        final = self.parent._entry("assistant", [{"type": "text", "text": "I will preserve JSON."}])
        final["message"]["stop_reason"] = "end_turn"
        collection = self.collect()
        assert collection.recovered_sources is not None
        source = collection.recovered_sources[0]
        saved = source["at"] + 1
        binding = reading.line_request_binding(
            collection.recovered_sources,
            source_id=source["fact_id"],
            text="Write JSON",
            harness="claude",
            sid=SHORT,
            now=saved,
        )
        revision = {
            "n": 1,
            "at": saved,
            "window_start": source["at"],
            "goal": "Preserve the export.",
            "lines": [
                {
                    "text": "Write JSON",
                    "source": "entry",
                    "source_id": source["fact_id"],
                    "request": binding,
                }
            ],
        }
        row = {"harness": "claude", "sid": SHORT, "state": "idle", "ended_at": saved + 60}
        preparation = reading_native.prepare(
            self.config,
            row,
            [revision],
            collection,
            {
                "harness": "claude",
                "provider": "codex",
                "destination": "test",
                "label": "test",
                "ci_read": "off",
            },
            now=saved + 120,
            recovered_sources=collection.recovered_sources,
        )
        self.assertEqual("", preparation.reason)
        prepared = preparation.prepared
        assert prepared is not None
        # The final runner independently copies Inputs before its own context freeze.
        copied = copy.deepcopy(prepared.inputs)
        frozen = reading_final_call.freeze_context(
            copied,
            prepared.floor,
            scope=prepared.scope,
            source_complete=True,
        )
        self.assertEqual(source["at"], frozen.value()["provenance"]["lines"][0]["requested_at"])
        self.assertEqual(prepared.context, frozen)
        with self.assertRaises(TypeError):
            copied.recovered_sources[0]["source_session"]["sid"] = "foreign"
