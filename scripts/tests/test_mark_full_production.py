"""Prospective native packets freeze the source a production press actually reads."""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mark_abstention

mark_abstention._reading()
from compass_runtime import project_context, reading  # noqa: E402
from compass_runtime.config import build_runtime_config  # noqa: E402


class FullProductionFreezeTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root / "synthetic-session.jsonl"
        self.start = dt.datetime(2026, 9, 24, tzinfo=dt.UTC).timestamp()
        self.config = build_runtime_config(
            environ={"HOME": temp.name, "COMPASS_HOME": temp.name},
            platform_name="linux",
            os_name="posix",
            launcher_path=self.root / "server.py",
        )
        self.rows = [
            self.record("user", 1, "Please preserve keyboard focus."),
            self.record("assistant", 10, "Keyboard focus is preserved. All checks pass."),
        ]
        self.write()
        self.entry: dict[str, Any] = {
            "harness": "claude",
            "sid": "synthetic-session",
            "captured_at": self.start + 30,
            "row": {"state": "idle", "finished_at": self.start + 20},
            "intent": {
                "at": self.start,
                "goal": "Preserve focus",
                "lines": [{"text": "Tab keeps focus"}],
            },
            "transcript": str(self.path),
        }

    def record(self, role: str, seconds: int, text: str) -> dict[str, Any]:
        return {
            "type": role,
            "sessionId": "synthetic-session",
            "uuid": f"source-{seconds}",
            "timestamp": dt.datetime.fromtimestamp(self.start + seconds, dt.UTC).isoformat(),
            "message": {
                "role": role,
                "stop_reason": "end_turn" if role == "assistant" else None,
                "content": [{"type": "text", "text": text}],
            },
        }

    def write(self) -> None:
        self.path.write_text("".join(json.dumps(row) + "\n" for row in self.rows))

    def freeze(self, *, production: bool = True) -> dict[str, Any]:
        seen = [
            {
                "harness": "claude",
                "sid": "synthetic-session",
                "state": "idle",
                "last_activity": self.start + 20,
            }
        ]
        with mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root)):
            return mark_abstention.freeze_case(
                self.config,
                self.entry,
                [],
                observations=seen,
                production_reading=production,
            )

    def test_agent_claims_and_whole_final_are_frozen_only_on_explicit_opt_in(self) -> None:
        legacy = self.freeze(production=False)
        self.assertNotIn("production_reading", legacy)
        self.assertFalse(
            any(
                row["type"] == reading.AGENT_MESSAGE_TYPE
                for row in mark_abstention.case_ledger({"v": 5}, legacy)
            )
        )
        case = self.freeze()
        rows = mark_abstention.case_ledger({"v": 5}, case)
        self.assertTrue(any(row["type"] == reading.AGENT_MESSAGE_TYPE for row in rows))
        source = case["production_reading"]
        self.assertIn("claims", mark_abstention.case_constraints({"v": 5}, case))
        self.assertNotIn("claims", mark_abstention.case_constraints({"v": 5}, legacy))
        self.assertIn("claims", mark_abstention._mark_question({"v": 5}, case, "claims"))
        self.assertEqual("whole", source["newest_final"]["outcome"])
        self.assertNotIn("words", source["newest_final"])
        callback = mark_abstention.native_case_final_lookup(
            case,
            config=self.config,
            index={"syntheti": str(self.path)},
        )
        self.assertIsNotNone(callback)
        assert callback is not None
        self.assertEqual(
            self.rows[1]["message"]["content"][0]["text"], callback(source["final_wanted"])["words"]
        )
        self.assertEqual([], mark_abstention.content_refusal(self.config, case, str(self.path)))

    def test_an_idle_case_with_no_recorded_finish_is_withheld_by_freeze_and_score(self) -> None:
        # The press admits this row since 2026-10-20; the abstention cases keep the earlier rule,
        # and the freeze and the scorer must agree on it, or a frozen prompt is never scored.
        self.entry["row"] = {"state": "idle"}
        with self.assertRaisesRegex(mark_abstention.FreezeError, "production-prompt-unavailable"):
            self.freeze()
        row = {"harness": "claude", "sid": "synthetic-session", "state": "idle"}
        self.assertEqual(
            ("", "idle-unknown"),
            reading.eligibility(
                row,
                latest_revision_at=self.start,
                now=self.start + 30,
                settle_sec=self.config.reading_settle_sec,
                admit_turn_stop=True,
                admit_idle=False,
            ),
        )

    def test_actual_selection_callbacks_refuse_changed_identity_before_model(self) -> None:
        case = self.freeze()
        for helper, key in (
            (mark_abstention.native_case_final_lookup, "final_wanted"),
            (mark_abstention.native_case_person_lookup, "person_wanted"),
        ):
            callback = helper(case, config=self.config, index={"syntheti": str(self.path)})
            self.assertIsNotNone(callback)
            assert callback is not None
            callback(case["production_reading"][key])
            with self.assertRaisesRegex(mark_abstention.FreezeError, "selection-differs"):
                callback([{**case["production_reading"][key][0], "id": "invented"}])
        self.assertIsNone(mark_abstention.native_case_final_lookup(self.freeze(production=False)))

    def test_source_vouch_detects_removed_agent_and_raw_tamper_but_not_future_append(self) -> None:
        case = self.freeze()
        self.rows.append(self.record("assistant", 40, "Later reply"))
        self.write()
        self.assertEqual([], mark_abstention.content_refusal(self.config, case, str(self.path)))
        altered = json.loads(json.dumps(case))
        altered["producer_facts"] = [
            f for f in altered["producer_facts"] if f.get("type") != reading.AGENT_MESSAGE_TYPE
        ]
        self.assertIn(
            "agent-facts-unconfirmed",
            mark_abstention.content_refusal(self.config, altered, str(self.path)),
        )
        self.rows[1]["message"]["content"][0]["text"] += " Changed source."
        self.write()
        self.assertIn(
            "production-source-differs",
            mark_abstention.content_refusal(self.config, case, str(self.path)),
        )

    def test_adopted_or_request_aged_intent_refuses_unimplemented_source_scope(self) -> None:
        self.entry["intent"]["goal_source"] = "first-prompt"
        with self.assertRaisesRegex(
            mark_abstention.FreezeError, "production-intent-source-unsupported"
        ):
            self.freeze()

    def test_source_size_bound_refuses_before_unbounded_prefix_copy(self) -> None:
        with (
            mock.patch.object(project_context, "FINAL_WORDS_SCAN_MAX_BYTES", 1),
            self.assertRaisesRegex(mark_abstention.FreezeError, "production-source-too-large"),
        ):
            self.freeze()

    def test_full_final_suffix_is_memory_only_and_actual_replayed_prompt_is_identical(self) -> None:
        text = "Completed the focus work. " + "short words " * 110 + "unique final suffix."
        self.rows[1]["message"]["content"][0]["text"] = text
        self.write()
        case = self.freeze()
        self.assertNotIn("unique final suffix", json.dumps(case))
        display = io.StringIO()
        with contextlib.redirect_stdout(display):
            mark_abstention._show_intent_case({"v": 5}, case, "synthetic")
        self.assertNotIn("unique final suffix", display.getvalue())
        self.assertIn("NEWEST FINAL SOURCE: whole", display.getvalue())
        self.assertIn("word digest", display.getvalue())
        prompts: list[str] = []

        def sink(prompt: str, **_kwargs: Any) -> tuple[str, str]:
            prompts.append(prompt)
            return "{}", "ok"

        kwargs = {"config": self.config, "index": {"syntheti": str(self.path)}}
        reading.produce(
            self.config,
            case["row_snapshot"],
            [mark_abstention.case_revision(case)],
            case["producer_facts"],
            now=case["captured_at"],
            stamp_text="test",
            model=sink,
            read_lines=True,
            read_agent_words=True,
            admit_turn_stop=True,
            tool_output=reading.ToolOutput(destination="native-dry", label="native dry", tails={}),
            person_source_lookup=mark_abstention.native_case_person_lookup(case, **kwargs),
            final_source_lookup=mark_abstention.native_case_final_lookup(case, **kwargs),
        )
        self.assertEqual(1, len(prompts))
        self.assertIn("unique final suffix", prompts[0])
        self.assertEqual(
            case["production_reading"]["prompt_digest"],
            hashlib.sha256(prompts[0].encode()).hexdigest(),
        )

    def test_full_native_uuid_freeze_and_callback_preserve_the_collectors_identity(self) -> None:
        native = "12345678-1234-4234-8234-123456789abc"
        self.path = self.root / (native + ".jsonl")
        self.entry.update(sid="12345678", transcript=str(self.path))
        for row in self.rows:
            row["sessionId"] = native
        self.rows[1]["message"]["content"][0]["text"] += " detail " * 180 + "private suffix"
        self.write()
        seen = [
            {
                "harness": "claude",
                "sid": "12345678",
                "state": "idle",
                "last_activity": self.start + 20,
            }
        ]
        with mock.patch.object(mark_abstention, "CLAUDE_PROJECTS_ROOT", str(self.root)):
            case = mark_abstention.freeze_case(
                self.config, self.entry, [], observations=seen, production_reading=True
            )
        source = case["production_reading"]
        self.assertEqual("whole", source["newest_final"]["outcome"])
        callback = mark_abstention.native_case_final_lookup(
            case, config=self.config, index={"12345678": str(self.path)}
        )
        assert callback is not None
        self.assertIn("private suffix", callback(source["final_wanted"])["words"])
        self.assertNotIn("private suffix", json.dumps(case))
        self.assertEqual([], mark_abstention.content_refusal(self.config, case, str(self.path)))

    def test_conflicting_final_is_preserved_as_unproven_not_repaired_by_excerpt(self) -> None:
        duplicate = json.loads(json.dumps(self.rows[1]))
        duplicate["message"]["stop_reason"] = "tool_use"
        self.rows.append(duplicate)
        self.write()
        case = self.freeze()
        self.assertEqual("unproven", case["production_reading"]["newest_final"]["outcome"])
        self.assertNotIn("words_digest", case["production_reading"]["newest_final"])
        self.assertEqual([], mark_abstention.content_refusal(self.config, case, str(self.path)))

    def test_forged_private_source_metadata_fails_vouch_and_callbacks(self) -> None:
        case = self.freeze()
        for key in (
            "prefix_digest",
            "person_words_digest",
            "newest_final",
            "prompt_digest",
            "constraints",
        ):
            altered = json.loads(json.dumps(case))
            altered["production_reading"][key] = "invented"
            self.assertIn(
                "production-source-differs",
                mark_abstention.content_refusal(self.config, altered, str(self.path)),
                key,
            )
        altered = json.loads(json.dumps(case))
        altered["production_reading"]["newest_final"]["words_digest"] = "invented"
        lookup = mark_abstention.native_case_final_lookup(
            altered, config=self.config, index={"syntheti": str(self.path)}
        )
        assert lookup is not None
        with self.assertRaisesRegex(mark_abstention.FreezeError, "production-source-differs"):
            lookup(altered["production_reading"]["final_wanted"])

    def test_source_movement_during_owned_prefix_copy_fails_closed(self) -> None:
        case = self.freeze()
        lookup = mark_abstention.native_case_final_lookup(
            case, config=self.config, index={"syntheti": str(self.path)}
        )
        assert lookup is not None
        real_stamp = project_context.transcript_stamp
        calls = 0

        def moved(path: str) -> tuple[int, int, int, int] | None:
            nonlocal calls
            if path == str(self.path):
                calls += 1
                return real_stamp(path) if calls == 1 else None
            return real_stamp(path)

        with (
            mock.patch.object(project_context, "transcript_stamp", side_effect=moved),
            self.assertRaisesRegex(mark_abstention.FreezeError, "production-source-moved"),
        ):
            lookup(case["production_reading"]["final_wanted"])

    def test_raw_source_digest_binds_even_an_inert_same_length_prefix_edit(self) -> None:
        self.rows.insert(0, {"padding": "aa"})
        self.write()
        case = self.freeze()
        self.rows[0]["padding"] = "bb"
        self.write()
        callback = mark_abstention.native_case_final_lookup(
            case,
            config=self.config,
            index={"syntheti": str(self.path)},
        )
        assert callback is not None
        with self.assertRaisesRegex(mark_abstention.FreezeError, "production-source-differs"):
            callback(case["production_reading"]["final_wanted"])

    def test_order_and_count_are_bound_not_only_a_set_of_source_ids(self) -> None:
        self.rows.insert(1, self.record("assistant", 5, "Earlier draft reply."))
        self.write()
        case = self.freeze()
        wanted = case["production_reading"]["final_wanted"]
        self.assertEqual(2, len(wanted))
        lookup = mark_abstention.native_case_final_lookup(
            case, config=self.config, index={"syntheti": str(self.path)}
        )
        assert lookup is not None
        for changed in (wanted[::-1], wanted[:1], wanted + wanted[:1]):
            with self.assertRaisesRegex(
                mark_abstention.FreezeError, "production-selection-differs"
            ):
                lookup(changed)

    def test_prospective_scope_refuses_other_harness_and_sourced_lines(self) -> None:
        self.entry["harness"] = "codex"
        with self.assertRaisesRegex(
            mark_abstention.FreezeError, "production-intent-source-unsupported"
        ):
            self.freeze()
        self.entry["harness"] = "claude"
        self.entry["intent"]["lines"][0]["request"] = {}
        with self.assertRaisesRegex(
            mark_abstention.FreezeError, "production-intent-source-unsupported"
        ):
            self.freeze()

    def test_flag_does_not_silently_change_existing_packet_without_freeze(self) -> None:
        self.assertEqual(2, mark_abstention.main(["--production-reading", "--report"]))

    def test_owned_source_cut_modes_and_exception_cleanup(self) -> None:
        case = self.freeze()
        owned: list[Path] = []
        with (
            self.assertRaisesRegex(RuntimeError, "synthetic refusal"),
            mark_abstention._historical_source(case, str(self.path)) as (path, _digest),
        ):
            source = Path(path)
            owned.append(source)
            if os.name == "posix":
                self.assertEqual(0o600, stat.S_IMODE(source.stat().st_mode))
                self.assertEqual(0o700, stat.S_IMODE(source.parent.stat().st_mode))
            raise RuntimeError("synthetic refusal")
        self.assertFalse(owned[0].exists())
        self.assertFalse(owned[0].parent.exists())

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "platform has no no-follow open")
    def test_source_symlink_substitution_cannot_supply_a_capture(self) -> None:
        case = self.freeze()
        link = self.root / "substituted.jsonl"
        link.symlink_to(self.path)
        with self.assertRaises(OSError), mark_abstention._historical_source(case, str(link)):
            self.fail("symlink source admitted")

    def test_historical_cut_stops_at_future_record_before_huge_later_suffix(self) -> None:
        current = (json.dumps(self.rows[0]) + "\n").encode()
        future = (json.dumps(self.record("assistant", 40, "Future")) + "\n").encode()
        source = io.BytesIO(
            current + future + b"x" * (project_context.FINAL_WORDS_RECORD_MAX_BYTES + 1)
        )
        cut = mark_abstention._bounded_source_cut(source, self.start + 30, len(current))
        self.assertEqual(len(current), cut)
        self.assertEqual(len(current) + len(future), source.tell())

    def test_bounded_cut_rejects_oversized_record_without_reading_all_of_it(self) -> None:
        source = io.BytesIO(b"x" * 10000)
        with (
            mock.patch.object(project_context, "FINAL_WORDS_RECORD_MAX_BYTES", 128),
            self.assertRaisesRegex(
                mark_abstention.FreezeError, "production-source-record-too-large"
            ),
        ):
            mark_abstention._bounded_source_cut(source, self.start + 30, 10000)
        self.assertEqual(129, source.tell())


if __name__ == "__main__":
    unittest.main()
