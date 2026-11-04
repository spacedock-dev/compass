"""Adopted goals need complete source words in every exact long-reading header."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

from compass_runtime import (
    reading,
    reading_final_call,
    reading_maps,
    reading_pass_context,
    reading_passes,
)

from . import test_reading_final_call as final_tests
from . import test_reading_source_words as word_tests


class RestoredAdoptedGoalTest(unittest.TestCase):
    def setUp(self):
        self.assertIn("message_words", reading_final_call.Inputs.__dataclass_fields__)
        self.source = word_tests.VerifiedOrdinaryWordsTest()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)

    def collected(self, words='Keep the retry safe. Include 界🙂 "quotes" and \\ paths.'):
        self.source.parent.prompt(words)
        self.source.parent.bash("pytest tests/retry.py", "1 passed")
        self.source.parent.prompt("Preserve the original evidence.")
        return self.source.collect()

    def inputs(self, collection):
        facts = collection.evidence.facts
        word = next(
            w
            for w in collection.words
            if w.type == "user_message"
            and w.state == "whole"
            and w.words.startswith("Keep the retry")
        )
        saved = word.words[:20] + "…"
        return reading_final_call.Inputs(
            {
                "harness": word.harness,
                "sid": word.sid,
                "state": "idle",
                "ended_at": max(f["at"] for f in facts) + 10,
            },
            {
                "n": 1,
                "at": word.at + 1,
                "goal": saved,
                "goal_source": "chosen-prompt",
                "goal_source_at": word.at,
                "lines": [{"text": "The tests pass", "source": "typed"}],
            },
            tuple(facts),
            reading.ToolOutput("test", "test"),
            message_words=collection.words,
        ), word

    def test_actual_complete_source_is_in_every_map_header_before_fit(self):
        inputs, word = self.inputs(self.collected())
        floor = reading_final_call.scope_floor(inputs, scope=reading.SCOPE_FINAL)
        context = reading_final_call.freeze_context(
            inputs, floor, scope=reading.SCOPE_FINAL, source_complete=True
        )
        self.assertIsNotNone(context.goal_proof)
        originals = [
            reading_passes.Original(
                row,
                next(
                    (
                        w.words
                        for w in inputs.message_words
                        if (w.fact_id, w.at) == (row["id"], row["at"]) and w.state == "whole"
                    ),
                    None,
                ),
            )
            for row in floor.entries
        ]
        for original in originals:
            packet = reading_passes.plan_packets(
                [original],
                goal=inputs.revision["goal"],
                lines=reading.outcome_lines(inputs.revision),
                protocol_prefix="Map",
                max_bytes=6000,
                max_passes=1,
                frozen_context=context,
            ).packets[0]
            header = json.loads(
                packet.prompt.split(reading_passes.FROZEN_INTENT_BOUNDARY)[-1].split(
                    reading_passes.EVIDENCE_BOUNDARY
                )[0]
            )
            self.assertEqual(inputs.revision["goal"], header["goal"])
            self.assertEqual(word.words, header["restored_goal"]["words"])
            self.assertEqual(word.fact_id, header["restored_goal"]["fact_id"])
            self.assertEqual(word.at, header["restored_goal"]["at"])
            self.assertTrue(packet.selection.goal_whole)
            self.assertLessEqual(len(packet.prompt.encode()), 6000)
            self.assertTrue(
                reading_maps.parse_reply(
                    '{"version":1,"candidates":[]}', packet, clauses=("goal", "line_1")
                ).usable
            )

    def test_complete_goal_reaches_real_final_call_after_three_original_maps(self):
        inputs, word = self.inputs(self.collected())
        fixture = final_tests.FinalCallTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.row, fixture.revision = dict(inputs.row), dict(inputs.revision)
        fixture.facts, fixture.output = list(inputs.facts), inputs.tool_output
        fixture.message_words = inputs.message_words
        fixture.prepare(single_maps=True)
        result = fixture.invoke()
        self.assertEqual("resolved", result.state)
        self.assertIsNotNone(result.criteria)
        self.assertTrue(result.packet.selection.goal_whole)
        self.assertEqual(4, fixture.fixture.fixture.spends())
        for packet in (*fixture.series.plan.packets, result.packet):
            self.assertIn(json.dumps(word.words, ensure_ascii=False), packet.prompt)
            self.assertEqual(word.words, packet.frozen_context.goal_proof.words)

    def test_missing_or_stale_whole_word_join_never_promotes_metadata(self):
        inputs, word = self.inputs(self.collected())
        floor = reading_final_call.scope_floor(inputs, scope=reading.SCOPE_FINAL)
        for changes in (
            {"fact_id": "stale"},
            {"at": word.at + 2},
            {"words": "changed words"},
            {"state": "unavailable"},
        ):
            altered = tuple(replace(w, **changes) if w == word else w for w in inputs.message_words)
            context = reading_final_call.freeze_context(
                replace(inputs, message_words=altered),
                floor,
                scope=reading.SCOPE_FINAL,
                source_complete=True,
                goal_status="whole",
            )
            self.assertIsNone(context.goal_proof)

    def fixture(self, inputs):
        fixture = final_tests.FinalCallTest()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.row, fixture.revision = dict(inputs.row), dict(inputs.revision)
        fixture.facts, fixture.output = list(inputs.facts), inputs.tool_output
        fixture.message_words = inputs.message_words
        return fixture

    def test_unclipped_session_goal_needs_no_person_prompt_but_excerpt_stays_unavailable(self):
        for goal, expected in (
            ("Keep the retry safe.", "resolved"),
            ("Keep the retry…", "unresolved"),
        ):
            inputs, _ = self.inputs(self.collected())
            inputs = replace(
                inputs,
                revision={**inputs.revision, "goal": goal, "goal_source": reading.SESSION_GOAL},
                message_words=(),
            )
            fixture = self.fixture(inputs)
            fixture.prepare()
            result = fixture.invoke()
            self.assertEqual(expected, result.state)
            if expected == "resolved":
                self.assertTrue(result.packet.selection.goal_whole)
                self.assertIsNone(result.packet.frozen_context.goal_proof.fact_id)
                self.assertEqual(goal, result.packet.frozen_context.goal_proof.words)
            else:
                self.assertIsNone(result.criteria)
                self.assertEqual([], fixture.factories)
                self.assertIn("stated-goal-limited", result.unresolved)
                self.assertNotIn("adopted-goal-unavailable", result.unresolved)

    def test_over_existing_goal_word_cap_is_never_promoted_from_owner_clipped_words(self):
        inputs, word = self.inputs(
            self.collected("Keep the retry safe. " + "x" * reading.LEDGER_WORDS_CAP_CHARS)
        )
        fixture = self.fixture(inputs)
        fixture.prepare()
        self.assertGreater(len(word.words), reading.LEDGER_WORDS_CAP_CHARS)
        self.assertIsNone(fixture.context.goal_proof)
        result = fixture.invoke()
        self.assertIsNone(result.criteria)
        self.assertEqual([], fixture.factories)

    def test_ambiguous_same_time_same_opening_prompts_do_not_become_whole_goal(self):
        self.source.parent.prompt("Keep the retry safe. First condition.")
        inputs, _ = self.inputs(self.source.collect())
        self.source.parent.prompt("Keep the retry safe. Different condition.")
        self.source.parent.rows[1]["timestamp"] = self.source.parent.rows[0]["timestamp"]
        collection = self.source.collect()
        inputs = replace(
            inputs, facts=tuple(collection.evidence.facts), message_words=collection.words
        )
        floor = reading_final_call.scope_floor(inputs, scope=reading.SCOPE_FINAL)
        context = reading_final_call.freeze_context(
            inputs, floor, scope=reading.SCOPE_FINAL, source_complete=True
        )
        self.assertIsNone(context.goal_proof)

    def test_secret_shaped_and_unencodable_fake_words_refuse_instead_of_normalizing(self):
        inputs, word = self.inputs(self.collected())
        floor = reading_final_call.scope_floor(inputs, scope=reading.SCOPE_FINAL)
        for text in (
            'Keep the retry safe. password="SHOULD_NOT_LEAK"',
            "Keep the retry safe.\ud800",
        ):
            words = tuple(
                replace(w, words=text, total=len(text)) if w == word else w
                for w in inputs.message_words
            )
            context = reading_final_call.freeze_context(
                replace(inputs, message_words=words),
                floor,
                scope=reading.SCOPE_FINAL,
                source_complete=True,
            )
            self.assertIsNone(context.goal_proof)

    def test_split_secret_owner_disagreement_refuses_proof_and_never_unmasks_g2_words(self):
        secret = "api03-" + "Q" * 70
        inputs, word = self.inputs(
            self.collected("Keep the retry safe. key sk-ant-\n" + secret + " LATE_GOAL 界🙂")
        )
        fixture = self.fixture(inputs)
        fixture.row["annotation_assessment"] = {"detail": "STORED_READING_CANARY"}
        fixture.prepare(single_maps=True)
        result = fixture.invoke()
        self.assertIsNone(result.criteria)
        self.assertIsNone(fixture.context.goal_proof)
        self.assertEqual([], fixture.factories)
        for packet in fixture.series.plan.packets:
            self.assertNotIn(secret, packet.prompt)
            self.assertNotIn("STORED_READING_CANARY", packet.prompt)
            self.assertNotIn("sk-ant-", packet.prompt)
        self.assertTrue(any("LATE_GOAL" in p.prompt for p in fixture.series.plan.packets))
        self.assertIn("LATE_GOAL", word.words)

    def test_complete_unicode_header_byte_overflow_has_no_clipped_goal_fallback(self):
        inputs, _word = self.inputs(self.collected("Keep the retry safe. " + "界🙂" * 350))
        fixture = self.fixture(inputs)
        fixture.prepare()
        self.assertIsNotNone(fixture.context.goal_proof)
        plan = reading_passes.plan_packets(
            fixture.originals,
            goal=inputs.revision["goal"],
            lines=reading.outcome_lines(inputs.revision),
            protocol_prefix="Map",
            max_bytes=1000,
            max_passes=3,
            frozen_context=fixture.context,
        )
        self.assertEqual((), plan.packets)
        self.assertTrue(plan.uncovered_primary)
        fixture.fixture.declared["limits"]["prompt_bytes"] = 1000
        fixture.series = replace(
            fixture.series, final_slot=replace(fixture.series.final_slot, prompt_bytes=1000)
        )
        result = fixture.invoke()
        self.assertEqual("local-unfit", result.state)
        self.assertIsNone(result.criteria)
        self.assertEqual([], fixture.factories)

    def test_stale_proof_or_source_join_after_mapping_refuses_final_without_charge(self):
        inputs, word = self.inputs(self.collected())
        fixture = self.fixture(inputs)
        fixture.prepare()
        original = fixture.inputs
        for changes in ({"fact_id": "stale"}, {"at": word.at + 2}, {"words": "changed"}):
            fixture.inputs = replace(
                original,
                message_words=tuple(
                    replace(w, **changes) if w == word else w for w in original.message_words
                ),
            )
            result = fixture.invoke()
            self.assertEqual("invalid-context", result.reason)
            self.assertIsNone(result.criteria)
            self.assertEqual([], fixture.factories)

    def test_parser_rejects_detached_goal_words_or_binding_from_actual_header(self):
        inputs, _ = self.inputs(self.collected())
        fixture = self.fixture(inputs)
        fixture.prepare()
        packet = fixture.series.plan.packets[0]
        proof = packet.frozen_context.goal_proof
        for changed in (
            replace(proof, words="Changed complete goal."),
            replace(proof, fact_id="foreign"),
            replace(proof, at=proof.at + 2),
        ):
            bad = replace(packet, frozen_context=replace(packet.frozen_context, goal_proof=changed))
            reply = reading_maps.parse_reply(
                '{"version":1,"candidates":[]}', bad, clauses=("goal", "line_1")
            )
            self.assertEqual("invalid-packet", reply.reason)

    def test_nonproof_or_boolean_identity_cannot_enter_an_owned_header(self):
        inputs, _ = self.inputs(self.collected())
        fixture = self.fixture(inputs)
        fixture.prepare()
        for proof in (object(), replace(fixture.context.goal_proof, fact_id=True)):
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                reading_pass_context.intent(
                    inputs.revision["goal"],
                    reading.outcome_lines(inputs.revision),
                    replace(fixture.context, goal_proof=proof),
                )
