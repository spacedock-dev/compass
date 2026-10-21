"""A message typed while the agent works, and an answer to its question, are the reader's direction.

Claude Code hands a message sent mid-turn to the model inside a tool result, so no user turn
carries it. The transcript records it three ways: a `queue-operation` pair (`enqueue`, then
`remove` with `reason: absorbed_mid_turn`) whose time is when it was absorbed, a model-request
blob, and a `queued_command` attachment whose `origin.kind` says who sent it and whose own
timestamp is when the reader typed it. The attachment is the one the reader reads: the same
queue also carries background-task notifications, which are the harness talking and are
two-thirds of the `absorbed_mid_turn` removals measured. The answer to the agent's multiple
choice question is the `toolUseResult.answers` of the question tool's result.

The shapes are in `docs/captures/claude/mid-turn-and-answer-shapes-2.1.305-macos.jsonl`, field
names and type names only. Every message here is placeholder prose.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import correction, observer, project_context, reading

from .test_claude_checks import SHORT, SID, START
from .test_direction_adoption import _row
from .test_slash_command_direction import Board, Session

FIRST = "Add retry with backoff to the webhook handler."
MID_TURN = "Also prune the dead rules from the stylesheets while you are in there."
IMAGE_TEXT = "Match the layout in the screenshot I pasted."
QUESTION = "How should the cross-file half be handled?"
OTHER_QUESTION = "Which stylesheet should be pruned?"
ANSWER = "Defer to a follow-up"
OTHER_ANSWER = "frontend/src/styles/"
NOTE = "the second option, but only after the gate is green"
IMAGE_DATA = "iVBORw0KGgoPLACEHOLDERIMAGEBYTES"
RECOMMENDED = "Same folder in its checkout (Recommended)"
CHOSEN = "Same folder in its checkout"


def stamp(seconds: int) -> str:
    return (START + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class MidTurnSession(Session):
    """`Transcript` with the queue and question shapes of Claude Code 2.1.305."""

    def _base(self, kind: str, seconds: int, **extra: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "type": kind,
            "uuid": f"u{len(self.rows)}",
            "parentUuid": f"u{len(self.rows) - 1}" if self.rows else None,
            "isSidechain": False,
            "sessionId": SID,
            "timestamp": stamp(seconds),
            "userType": "external",
            "entrypoint": "cli",
            "version": "2.1.305",
        }
        row.update(extra)
        self.rows.append(row)
        return row

    def queued(
        self,
        prompt: Any,
        *,
        typed: int,
        absorbed: int,
        origin: dict[str, Any] | None = None,
        mode: str = "prompt",
        queue_text: str | None = None,
    ) -> None:
        """One message in the queue, then taken into the turn at `absorbed`."""
        delivery = f"delivery-{len(self.rows)}"
        origin = origin or {"kind": "human"}
        text = queue_text if queue_text is not None else str(prompt)
        self._base("queue-operation", typed, operation="enqueue", content=text)
        self._base(
            "queue-operation",
            absorbed,
            operation="remove",
            content=text,
            reason="absorbed_mid_turn",
            commandUuid=f"command-{len(self.rows)}",
            deliveryId=delivery,
        )
        attachment: dict[str, Any] = {
            "type": "queued_command",
            "prompt": prompt,
            "source_uuid": f"source-{len(self.rows)}",
            "delivery_id": delivery,
            "commandMode": mode,
            "origin": origin,
            "timestamp": stamp(typed),
        }
        if origin.get("kind") == "human":
            attachment["humanTurn"] = True
        self._base("attachment", typed, attachment=attachment)

    def asked(self, questions: list[dict[str, Any]]) -> str:
        return self.call("AskUserQuestion", {"questions": questions})

    def answered(
        self,
        call_id: str,
        questions: list[dict[str, Any]],
        answers: dict[str, Any],
        annotations: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        self.result(
            call_id,
            "User has answered your questions.",
            tool_use_result={
                "questions": questions,
                "answers": answers,
                "annotations": annotations or {},
                **extra,
            },
        )


def question(text: str, header: str, *labels: str) -> dict[str, Any]:
    return {
        "question": text,
        "header": header,
        "multiSelect": False,
        "options": [{"label": label, "description": "placeholder"} for label in labels],
    }


class _Case(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.board = Board(self.root)
        self.config, self.state = self.board.config, self.board.state
        self.board.session = self.session = MidTurnSession(self.root / "work" / "billing")
        self.session.prompt(FIRST)
        self.session.bash("pytest", "5 passed")

    def events(self) -> list[dict[str, Any]]:
        self.session.save(self.board.path)
        return project_context.instruction_events(
            self.config, str(self.board.path), "claude", SHORT
        )

    def person_facts(self) -> list[dict[str, Any]]:
        return [f for f in self.board.facts() if f.get("type") == "user_message"]


class AMessageAbsorbedMidTurnIsALaterDirectionTest(_Case):
    def test_it_is_a_direction_at_the_moment_the_reader_typed_it(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        (event,) = [e for e in self.events() if e["title"] == MID_TURN]
        # Typed at 100 s and absorbed at 160 s: the reader's own time is the first.
        self.assertEqual(START.timestamp() + 100, event["at"])
        self.assertEqual(MID_TURN, event[project_context.READER_WORDS_FIELD])
        self.assertEqual(observer.MID_TURN_SOURCE, event["source"])

    def test_the_collected_fact_is_the_readers_and_counts_as_a_later_direction(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        facts = self.person_facts()
        (fact,) = [f for f in facts if f["summary"] == MID_TURN]
        self.assertEqual(reading.AUTHOR_PERSON, reading.author_of(fact))
        floor = START.timestamp() + 10
        self.assertEqual(
            1,
            correction.unsettled_directions(_row(), facts, floor=floor),
        )

    def test_it_starts_an_outline_phase_titled_with_its_words(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        self.session.write(str(self.root / "work" / "billing" / "src" / "a.py"))
        self.session.save(self.board.path)
        source = importlib.import_module("compass_runtime.session_source")
        outline = importlib.import_module("compass_runtime.session_outline")
        page = source.read(self.config, str(self.board.path), "claude", SHORT)
        blocks = outline.build(page, self.config)["blocks"]
        self.assertEqual([FIRST, MID_TURN], [b["prompt"]["title"] for b in blocks])

    def test_the_reading_is_given_the_words_as_the_readers(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        ledger = reading.build_ledger(self.person_facts(), "claude", SHORT)
        (row,) = [r for r in ledger if r["summary"] == MID_TURN]
        self.assertEqual(reading.AUTHOR_PERSON, row["author"])
        self.assertEqual(MID_TURN, row["words"])

    def test_a_background_task_notification_is_not_the_readers(self) -> None:
        self.session.queued(
            "<task-notification><task-id>t1</task-id></task-notification>",
            typed=100,
            absorbed=160,
            origin={"kind": "task-notification", "producer": "session-task"},
            mode="task-notification",
        )
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_a_queued_message_nothing_has_delivered_is_not_yet_a_direction(self) -> None:
        self.session.rows.append(
            {
                "type": "queue-operation",
                "operation": "enqueue",
                "timestamp": stamp(100),
                "sessionId": SID,
                "content": MID_TURN,
            }
        )
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_an_attachment_without_its_own_row_time_keeps_the_time_it_carries(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        del self.session.rows[-1]["timestamp"]
        (event,) = [e for e in self.events() if e["title"] == MID_TURN]
        self.assertEqual(START.timestamp() + 100, event["at"])

    def test_a_pasted_image_keeps_its_words_and_leaves_its_bytes(self) -> None:
        blocks = [
            {"type": "text", "text": IMAGE_TEXT},
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": IMAGE_DATA},
            },
        ]
        self.session.queued(blocks, typed=100, absorbed=160, queue_text=IMAGE_TEXT)
        (event,) = [e for e in self.events() if e["title"] == IMAGE_TEXT]
        self.assertEqual(IMAGE_TEXT, event[project_context.READER_WORDS_FIELD])
        self.assertNotIn(IMAGE_DATA, repr(event))

    def test_the_whole_text_of_the_direction_is_readable_for_review(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        self.session.save(self.board.path)
        row = next(r for r in self.session.rows if r["type"] == "attachment")
        self.assertEqual(
            MID_TURN, project_context.whole_message_words(self.config, row, "claude", 4096)
        )
        self.assertEqual(
            MID_TURN, project_context._direction_words(self.config, row, "claude").text
        )

    def test_a_credential_in_the_message_is_masked_as_in_any_other(self) -> None:
        self.session.queued("Use AKIAIOSFODNN7EXAMPLE for the upload.", typed=100, absorbed=160)
        words = [e[project_context.READER_WORDS_FIELD] for e in self.events()]
        self.assertFalse(any("AKIAIOSFODNN7EXAMPLE"[:12] in w for w in words))


class AnAnswerToTheAgentsQuestionIsTheReadersDirectionTest(_Case):
    def answer(self, answers: dict[str, Any], annotations: Any = None, **extra: Any) -> None:
        questions = [question(q, "Provenance", ANSWER, "Per-file sheets") for q in answers]
        call = self.session.asked(questions)
        self.session.answered(call, questions, answers, annotations, **extra)

    def test_the_answer_is_the_readers_words_at_the_time_it_was_given(self) -> None:
        self.answer({QUESTION: ANSWER})
        events = [e for e in self.events() if e["title"] != FIRST]
        (event,) = events
        self.assertEqual(f"Provenance: {ANSWER}", event[project_context.READER_WORDS_FIELD])
        self.assertEqual(observer.ANSWER_SOURCE, event["source"])
        self.assertGreater(event["at"], START.timestamp())

    def test_it_opens_an_outline_phase_titled_with_the_answer_and_not_the_question(self) -> None:
        self.answer({QUESTION: ANSWER})
        self.session.write(str(self.root / "work" / "billing" / "src" / "a.py"))
        self.session.save(self.board.path)
        source = importlib.import_module("compass_runtime.session_source")
        outline = importlib.import_module("compass_runtime.session_outline")
        page = source.read(self.config, str(self.board.path), "claude", SHORT)
        blocks = outline.build(page, self.config)["blocks"]
        self.assertEqual([FIRST, f"Provenance: {ANSWER}"], [b["prompt"]["title"] for b in blocks])
        self.assertNotIn(QUESTION, repr(blocks))

    def test_the_agents_own_question_is_not_put_in_the_readers_mouth(self) -> None:
        self.answer({QUESTION: ANSWER})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        self.assertNotIn(QUESTION, repr(event))

    def test_the_reading_input_carries_the_answer_as_the_readers_words(self) -> None:
        self.answer({QUESTION: ANSWER})
        facts = self.person_facts()
        ledger = reading.build_ledger(facts, "claude", SHORT)
        (row,) = [r for r in ledger if ANSWER in r.get("words", "")]
        self.assertEqual(reading.AUTHOR_PERSON, row["author"])
        prompt, selected = reading.build_prompt(
            ledger, goal="prune the stylesheets", lines=("the gate is stricter",), max_bytes=16384
        )
        self.assertIn(ANSWER, prompt)
        self.assertTrue(selected.entries)

    def test_several_questions_are_each_an_answer_in_one_direction(self) -> None:
        self.answer({OTHER_QUESTION: OTHER_ANSWER, QUESTION: ANSWER})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        words = event[project_context.READER_WORDS_FIELD]
        self.assertIn(OTHER_ANSWER, words)
        self.assertIn(ANSWER, words)

    def test_a_note_the_reader_attached_is_their_words_too(self) -> None:
        self.answer({QUESTION: ANSWER}, {QUESTION: {"notes": NOTE}})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        self.assertIn(NOTE, event[project_context.READER_WORDS_FIELD])

    def test_a_preview_the_agent_wrote_is_not(self) -> None:
        self.answer({QUESTION: ANSWER}, {QUESTION: {"preview": "AGENT-AUTHORED-PREVIEW"}})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        self.assertNotIn("AGENT-AUTHORED-PREVIEW", repr(event))

    def test_an_away_timeout_is_no_answer(self) -> None:
        self.answer({}, afkTimeoutMs=60000)
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_a_declined_question_is_no_answer(self) -> None:
        call = self.session.asked([question(QUESTION, "Provenance", ANSWER, "Other")])
        self.session.result(
            call,
            "The user doesn't want to proceed with this tool use.",
            is_error=True,
            tool_use_result="The user doesn't want to proceed with this tool use.",
        )
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_an_answer_collected_as_the_board_does_is_a_person_fact(self) -> None:
        self.answer({QUESTION: ANSWER})
        facts = self.person_facts()
        (fact,) = [f for f in facts if ANSWER in f.get(project_context.READER_WORDS_FIELD, "")]
        self.assertEqual(reading.AUTHOR_PERSON, reading.author_of(fact))
        self.assertEqual(1, len([f for f in facts if f["summary"] != FIRST]))

    def test_the_agents_recommendation_marker_is_not_the_readers_words(self) -> None:
        # Seen live: `Ruling: (b) Same folder in its checkout (Recommended)`. The marker is the
        # agent's own label on the option it preferred, so quoting it puts the agent's advice in
        # the reader's mouth.
        self.answer({QUESTION: RECOMMENDED})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        self.assertEqual(f"Provenance: {CHOSEN}", event[project_context.READER_WORDS_FIELD])
        self.assertEqual(f"Provenance: {CHOSEN}", event["title"])
        self.assertNotIn("Recommended", repr(event))

    def test_the_marker_goes_from_every_choice_of_a_multiple_choice_answer(self) -> None:
        self.answer({QUESTION: [RECOMMENDED, "Per-file sheets"]})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        self.assertEqual(
            f"Provenance: {CHOSEN}, Per-file sheets", event[project_context.READER_WORDS_FIELD]
        )

    def test_the_marker_goes_from_every_choice_of_a_comma_joined_answer(self) -> None:
        # The tool writes a multiple-choice answer as one comma-joined string, so a marker sits
        # before a comma, not only at the end.
        self.answer({QUESTION: f"{RECOMMENDED}, Per-file sheets (Recommended), Both"})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        self.assertEqual(
            f"Provenance: {CHOSEN}, Per-file sheets, Both",
            event[project_context.READER_WORDS_FIELD],
        )
        self.assertNotIn("Recommended", repr(event))

    def test_a_marker_before_a_comma_is_the_agents_but_the_same_word_in_a_sentence_is_not(
        self,
    ) -> None:
        self.assertEqual("A, B", observer._answer_text("A (Recommended), B"))
        self.assertEqual("", observer._answer_text("(Recommended)"))
        self.assertEqual(
            "Recommended reading first, then",
            observer._answer_text("Recommended reading first, then"),
        )

    def test_only_the_trailing_marker_is_the_agents_and_a_reader_who_typed_it_keeps_the_word(
        self,
    ) -> None:
        self.answer({QUESTION: "Recommended reading first, then the rest"})
        (event,) = [e for e in self.events() if e["title"] != FIRST]
        self.assertIn("Recommended reading first", event[project_context.READER_WORDS_FIELD])

    def test_an_answer_that_was_only_the_marker_is_no_answer(self) -> None:
        self.answer({QUESTION: "(Recommended)"})
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_the_whole_text_read_for_review_has_no_marker_either(self) -> None:
        self.answer({QUESTION: RECOMMENDED})
        self.session.save(self.board.path)
        row = next(r for r in self.session.rows if "answers" in (r.get("toolUseResult") or {}))
        self.assertEqual(
            f"Provenance: {CHOSEN}",
            project_context.whole_message_words(self.config, row, "claude", 4096),
        )

    def test_an_answer_is_not_promoted_to_the_projects_intent_by_itself(self) -> None:
        # It opens its own outline phase, which is the reader's choice shaping the work after it,
        # and the reader may press `Use this as my goal`. What it does not do is stand in the
        # project's recovered direction or its course without a press: "Provenance: Defer to a
        # follow-up" says nothing a later session could act on alone.
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        self.answer({QUESTION: ANSWER})
        facts = {f["evidence"]["source"]: f for f in self.person_facts() if f["summary"] != FIRST}
        self.assertIs(False, facts[observer.ANSWER_SOURCE]["intent_promoted"])
        self.assertIs(True, facts[observer.MID_TURN_SOURCE]["intent_promoted"])

    def test_the_answer_fact_says_what_it_is_not_that_it_was_a_typed_turn(self) -> None:
        self.answer({QUESTION: ANSWER})
        (fact,) = [f for f in self.person_facts() if f["summary"] != FIRST]
        self.assertEqual("question tool result holding the reader's answers", fact["actor_claim"])

    def test_a_giant_answer_is_an_unread_region_as_a_giant_message_is(self) -> None:
        self.answer({QUESTION: "x" * (project_context.PRESS_TEXT_MAX_CHARS + 1)})
        self.session.save(self.board.path)
        row = next(r for r in self.session.rows if "answers" in (r.get("toolUseResult") or {}))
        self.assertGreater(
            project_context._message_text_chars(row),
            project_context.PRESS_TEXT_MAX_CHARS,
        )

    def test_a_note_counts_toward_the_guard_with_the_answer(self) -> None:
        self.answer({QUESTION: ANSWER}, {QUESTION: {"notes": "n" * 50}})
        row = next(r for r in self.session.rows if "answers" in (r.get("toolUseResult") or {}))
        self.assertEqual(
            len(ANSWER) + 50,
            project_context._message_text_chars(row),
        )

    def test_the_tool_results_of_every_other_tool_are_still_not_directions(self) -> None:
        # The measured tool-result shapes carry `toolUseResult` too, and none is the reader's.
        self.session.bash("pytest", "5 passed")
        self.session.write(str(self.root / "work" / "billing" / "a.py"))
        self.assertEqual([FIRST], [e["title"] for e in self.events()])


class OnlyTheQuestionToolsOwnResultIsAnAnswerTest(_Case):
    """A `toolUseResult` with `questions` and `answers` is a direction only from the tool that asked."""

    def qa(self, **answers: str) -> dict[str, Any]:
        asked = [question(QUESTION, "Provenance", ANSWER, "Other")]
        return {"questions": asked, "answers": {QUESTION: ANSWER}, "annotations": {}, **answers}

    def test_a_typed_turn_carrying_the_same_fields_is_read_as_what_it_typed(self) -> None:
        self.session.prompt("Run the migration tests next.")
        self.session.rows[-1]["toolUseResult"] = self.qa()
        row = self.session.rows[-1]
        message = observer.parse_reader_record(row)
        assert message is not None
        self.assertEqual("Run the migration tests next.", message["text"])
        self.assertNotIn("source", message)
        self.assertEqual(
            [FIRST, "Run the migration tests next."], [e["title"] for e in self.events()]
        )

    def test_a_tool_result_whose_answers_name_no_question_it_asked_is_no_direction(self) -> None:
        call = self.session.call("SomeOtherTool", {})
        result = self.qa()
        result["answers"] = {"A question nobody asked": ANSWER}
        self.session.result(call, "done", tool_use_result=result)
        self.assertIsNone(observer.parse_reader_record(self.session.rows[-1]))
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_a_tool_result_whose_questions_offer_no_options_is_no_direction(self) -> None:
        call = self.session.call("SomeOtherTool", {})
        result = self.qa()
        result["questions"] = [{"question": QUESTION, "header": "Provenance"}]
        self.session.result(call, "done", tool_use_result=result)
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_a_record_that_is_not_a_tool_result_at_all_is_no_direction(self) -> None:
        row = {
            "type": "user",
            "uuid": "u-x",
            "timestamp": stamp(50),
            "message": {"role": "user", "content": []},
            "toolUseResult": self.qa(),
        }
        self.assertIsNone(observer.parse_reader_record(row))

    def test_an_errored_tool_result_is_no_direction(self) -> None:
        call = self.session.call("AskUserQuestion", {"questions": []})
        self.session.result(call, "declined", is_error=True, tool_use_result=self.qa())
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_the_real_tools_result_is_still_one(self) -> None:
        questions = [question(QUESTION, "Provenance", ANSWER, "Other")]
        call = self.session.asked(questions)
        self.session.answered(call, questions, {QUESTION: ANSWER})
        self.assertEqual([FIRST, f"Provenance: {ANSWER}"], [e["title"] for e in self.events()])


class AMessageFromAnOlderClaudeCodeIsNotTheReadersTest(_Case):
    """Claude Code 2.1.181 and older: no `origin`, so nothing says who sent the message."""

    def test_an_attachment_with_no_origin_is_not_read_as_the_reader(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        del self.session.rows[-1]["attachment"]["origin"]
        self.assertIsNone(observer.parse_reader_record(self.session.rows[-1]))
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_the_same_message_with_the_field_is_read(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        self.assertEqual([FIRST, MID_TURN], [e["title"] for e in self.events()])

    def test_a_message_from_another_session_is_not_the_readers_either(self) -> None:
        # `origin.kind: peer` measured on 2.1.274: a prompt another agent sent in.
        self.session.queued(MID_TURN, typed=100, absorbed=160, origin={"kind": "peer"})
        self.assertEqual([FIRST], [e["title"] for e in self.events()])

    def test_the_fact_says_it_came_from_a_human_origin(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        (fact,) = [f for f in self.person_facts() if f["summary"] == MID_TURN]
        self.assertEqual("queued-command attachment with a human origin", fact["actor_claim"])


class TheStoryReadsWhatTheCollectorPublishesTest(_Case):
    """`DriftReaderDirections` is driven from this file, not from a reading written by hand.

    The two facts are what the collector publishes (`for_page`: no whole words) for a message
    sent mid-turn and for an answer the agent had marked `(Recommended)`, collected from a
    transcript built above. The story builds its board from them, so a collector that again
    quotes the marker, or again calls an answer a typed turn, changes this file and the story
    asserts against the change. Regenerate with `COMPASS_WRITE_STORY_FIXTURE=1`.
    """

    FIXTURE = (
        Path(__file__).resolve().parents[4] / "frontend/test/fixtures/collected-directions.json"
    )

    def collected(self) -> dict[str, Any]:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        questions = [question(QUESTION, "Ruling", RECOMMENDED, "Per-file sheets")]
        call = self.session.asked(questions)
        self.session.answered(call, questions, {QUESTION: RECOMMENDED})
        facts = {
            f["evidence"]["source"]: project_context.for_page(f)
            for f in self.person_facts()
            if f["summary"] != FIRST
        }
        return {
            "mid_turn": facts[observer.MID_TURN_SOURCE],
            "answer": facts[observer.ANSWER_SOURCE],
        }

    def test_the_committed_facts_are_what_the_collector_publishes_now(self) -> None:
        collected = self.collected()
        if os.environ.get("COMPASS_WRITE_STORY_FIXTURE") == "1":
            self.FIXTURE.write_text(json.dumps(collected, indent=2) + "\n", encoding="utf-8")
        self.assertEqual(json.loads(self.FIXTURE.read_text(encoding="utf-8")), collected)

    def test_the_answer_it_publishes_has_no_marker_and_no_whole_words(self) -> None:
        answer = self.collected()["answer"]
        self.assertEqual(f"Ruling: {CHOSEN}", answer["summary"])
        self.assertNotIn(project_context.READER_WORDS_FIELD, answer)


class AMidTurnMessageNeverMovesTheGoalTest(_Case):
    def test_the_goal_parser_does_not_take_either_shape(self) -> None:
        self.session.queued(MID_TURN, typed=100, absorbed=160)
        call = self.session.asked([question(QUESTION, "Provenance", ANSWER, "Other")])
        self.session.answered(call, [question(QUESTION, "Provenance", ANSWER)], {QUESTION: ANSWER})
        taken = [r for r in self.session.rows if observer.parse_reader_record(r) is not None]
        goal = [r for r in self.session.rows if observer.parse_message_record(r) is not None]
        self.assertEqual(2, len(taken) - len(goal))
        self.assertTrue(all(r["type"] in {"attachment", "user"} for r in taken))


class TheCollectorReadsTheFieldsTheCaptureRecordsTest(unittest.TestCase):
    CAPTURE = (
        Path(__file__).resolve().parents[4]
        / "docs/captures/claude/mid-turn-and-answer-shapes-2.1.305-macos.jsonl"
    )

    def shapes(self) -> dict[str, dict[str, Any]]:
        return {
            row["shape"]: row
            for row in (json.loads(line) for line in self.CAPTURE.read_text().splitlines())
        }

    def test_the_attachment_fields_the_reader_branches_on_are_recorded(self) -> None:
        human = self.shapes()["queued-command-human"]["entry"]["attachment"]
        self.assertEqual("prompt", human["commandMode"])
        self.assertEqual({"kind": "human"}, human["origin"])
        self.assertIn("prompt", human)
        self.assertIn("timestamp", human)
        task = self.shapes()["queued-command-task-notification"]["entry"]["attachment"]
        self.assertEqual("task-notification", task["origin"]["kind"])

    def test_the_answer_fields_the_reader_takes_are_recorded(self) -> None:
        result = self.shapes()["question-answered"]["entry"]["toolUseResult"]
        self.assertEqual({"answers", "annotations", "questions"}, set(result))
        self.assertEqual(
            {"header", "question"}, {"header", "question"} & set(result["questions"][0])
        )
        notes = self.shapes()["question-answered-with-notes"]["entry"]["toolUseResult"]
        self.assertEqual({"notes"}, set(next(iter(notes["annotations"].values()))))
        self.assertEqual(
            {}, self.shapes()["question-timed-out"]["entry"]["toolUseResult"]["answers"]
        )

    def test_an_attachment_from_before_the_origin_field_is_recorded_without_it(self) -> None:
        old = self.shapes()["queued-command-without-origin"]["entry"]["attachment"]
        self.assertNotIn("origin", old)
        self.assertNotIn("timestamp", old)
        counts = self.shapes()["origin-field"]["counts"]
        self.assertEqual("2.1.181", counts["newest_version_of_a_prompt_without_origin"])
        self.assertIn("2026-10-21", self.shapes()["origin-field"]["note"])
