"""Typed Codex actions use the real exec capture's two ordinary user-message shapes.

Only text and timestamps are filled in below; field sets and native vocabulary come from
the shape-only recording. Placeholder prose stands in for the captured negative control.
"""

from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from compass_runtime import annotations as annotation_store
from compass_runtime import observer, project_context, records, transcripts

from . import test_transcripts
from .support import make_runtime

REPO = Path(__file__).resolve().parents[4]
CAPTURE = REPO / "docs/captures/codex/skill-action-shapes-0.167.0-macos.jsonl"
IMAGE_CAPTURE = REPO / "docs/captures/codex/skill-action-image-shapes-0.167.0-macos.jsonl"
FIRST = "Build the placeholder parser and test every token type."
MENTION = "Finish the placeholder parser, then use $compass sessions waiting to inspect it."
NOW = 1794139200.0


def captured_messages(text: str, *, command: bool = True, second: int = 10) -> list[dict[str, Any]]:
    """Replay both captured user shapes with placeholder values in the free-text slots."""
    result = []
    for line in CAPTURE.read_text(encoding="utf-8").splitlines():
        record = copy.deepcopy(json.loads(line)["record"])
        payload = record["payload"]
        content = payload.get("content") or payload.get("item", {}).get("content")
        if not content or not isinstance(content[0].get("text"), dict):
            continue
        if content[0]["text"]["whole_message"] != command:
            continue
        content[0]["text"] = text
        record["timestamp"] = f"2026-11-08T12:00:{second:02d}Z"
        result.append(record)
    if len(result) != 2:
        raise AssertionError("capture must supply response_item and item_completed user shapes")
    return result


def actions() -> list[str]:
    table = (
        (REPO / "compass/skills/compass/SKILL.md").read_text().split("## Terminal actions", 1)[1]
    )
    return re.findall(r"^\| `([^`]+)` \|", table.split("`summary` prints", 1)[0], re.MULTILINE)


def captured_image_messages(text: str = "$compass sessions waiting") -> list[dict[str, Any]]:
    """Fill the real image capture's value slots without storing image bytes or paths."""
    result = []
    for line in IMAGE_CAPTURE.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)["record"]
        payload = record["payload"]
        content = payload.get("content") or payload.get("item", {}).get("content")
        if not content or not any(b["type"] in ("input_image", "local_image") for b in content):
            continue
        for block in content:
            if isinstance(block.get("text"), dict):
                form = block["text"]["text_form"]
                block["text"] = {
                    "<image name=[Image #N] path=...>": '<image name=[Image #1] path="placeholder.png">',
                    "</image>": "</image>",
                    "$compass <closed action>": text,
                }[form]
        record["timestamp"] = "2026-11-08T12:00:20Z"
        result.append(record)
    if len(result) != 2:
        raise AssertionError("image capture must supply both Codex user shapes")
    return result


class APersonsCodexCompassActionTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config, self.state = make_runtime(
            state_home=str(self.root), state_dir=self.root / "state"
        )
        self.path = self.root / "rollout.jsonl"

    def save(self, rows: list[dict[str, Any]]) -> str:
        self.path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return str(self.path)

    def candidates(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        path = self.save(rows)
        return {
            "harness": "codex",
            "sid": "placeholder-session",
            **transcripts.first_prompt(self.config, self.state, path, "codex"),
            **transcripts.codex_instruction(self.config, self.state, path),
        }

    def test_a_persons_captured_action_is_not_published_as_their_message(self) -> None:
        for record in captured_messages("$compass sessions waiting"):
            with self.subTest(shape=record["type"]):
                self.assertIsNone(observer.parse_message_record(record))

    def test_a_person_can_type_each_closed_action_in_any_case_and_whitespace(self) -> None:
        self.assertEqual(13, len(actions()))
        for action in actions():
            text = " \t$CoMpAsS\n" + " \t".join(action.upper().split()) + "\n"
            with self.subTest(action=action):
                pair = captured_messages(text)
                self.assertIsNone(observer.parse_message_record(pair[0]))
                for record in pair:
                    self.assertIsNone(transcripts._first_prompt_record(record, "codex"))
                row = self.candidates(pair)
                self.assertEqual("", row["last_prompt"])
                self.assertEqual(
                    ("", None), annotation_store.prompt_candidate(row, "latest-prompt")
                )

    def test_a_persons_action_is_not_a_later_direction_or_a_derived_goal(self) -> None:
        rows = captured_messages(FIRST, command=False) + captured_messages(
            "$compass sessions waiting", second=20
        )
        path = self.save(rows)
        events = project_context.instruction_events(self.config, path, "codex", "placeholder")
        self.assertEqual([FIRST], [event["title"] for event in events])
        self.assertEqual(
            FIRST,
            observer.analyze(self.config, self.state, path, now=NOW + 60, window_sec=86400)["goal"],
        )

    def test_a_persons_action_alone_offers_no_goal_to_draft_or_adopt(self) -> None:
        # Exercise the prompt ladder on each shape alone as well as the duplicate pair.
        pair = captured_messages("$compass sessions waiting")
        for rows in ([pair[0]], [pair[1]], pair):
            with self.subTest(shape=rows[0]["type"], count=len(rows)):
                row = self.candidates(rows)
                self.assertEqual("", row["first_prompt"])
                self.assertEqual("", row["last_prompt"])
                self.assertIsNone(row["instruction"])
                for source in ("first-prompt", "latest-prompt"):
                    self.assertEqual(("", None), annotation_store.prompt_candidate(row, source))
                    outcome = annotation_store.adopt(
                        self.config,
                        self.state,
                        row,
                        source=source,
                        expected_text="$compass sessions waiting",
                        expected_at=NOW + 10,
                        now=NOW + 60,
                    )
                    self.assertNotEqual(annotation_store.OUTCOME_STORED, outcome)
                self.assertFalse(annotation_store.load(self.config))
                self.assertEqual(
                    observer.NO_GOAL,
                    observer.analyze(
                        self.config, self.state, str(self.path), now=NOW + 60, window_sec=86400
                    )["goal"],
                )

    def test_a_persons_previous_prompt_still_supplies_the_latest_goal_offer(self) -> None:
        row = self.candidates(
            captured_messages(FIRST, command=False)
            + captured_messages("$compass sessions waiting", second=20)
        )
        self.assertEqual(FIRST, row["last_prompt"])
        for source in ("first-prompt", "latest-prompt"):
            self.assertEqual((FIRST, NOW + 10), annotation_store.prompt_candidate(row, source))

    def test_a_persons_next_work_prompt_supplies_the_draft_after_an_opening_action(self) -> None:
        row = self.candidates(
            captured_messages("$compass goal") + captured_messages(FIRST, command=False, second=20)
        )
        self.assertEqual((FIRST, NOW + 20), annotation_store.prompt_candidate(row, "first-prompt"))

    def test_a_persons_prose_mentioning_compass_stays_a_direction_and_a_goal(self) -> None:
        rows = captured_messages(MENTION, command=False)
        self.assertEqual({"role": "user", "text": MENTION}, observer.parse_message_record(rows[0]))
        row = self.candidates(rows)
        events = project_context.instruction_events(
            self.config, str(self.path), "codex", "placeholder"
        )
        self.assertEqual([MENTION], [event["title"] for event in events])
        for source in ("first-prompt", "latest-prompt"):
            self.assertEqual((MENTION, NOW + 10), annotation_store.prompt_candidate(row, source))
        self.assertEqual(
            MENTION,
            observer.analyze(
                self.config, self.state, str(self.path), now=NOW + 60, window_sec=86400
            )["goal"],
        )
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.adopt(
                self.config,
                self.state,
                row,
                source="latest-prompt",
                expected_text=MENTION,
                expected_at=NOW + 10,
                now=NOW + 60,
            ),
        )
        saved = annotation_store.find(annotation_store.load(self.config), "codex", row["sid"])
        assert saved is not None
        self.assertEqual(MENTION, saved["revisions"][-1]["goal"])

    def test_a_persons_other_words_and_other_harnesses_are_not_codex_actions(self) -> None:
        for text in (
            "$compass",
            "$compass sessions waiting please",
            "$compass sessions; fix parser",
            "Please run $compass goal",
            "$other sessions",
            "$compass summarize",
            "`$compass goal`",
            "$compass sessions\nNow fix the parser.",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    {"role": "user", "text": text},
                    observer.parse_message_record(captured_messages(text, command=False)[0]),
                )
        for harness in ("claude", "pi", "droid"):
            self.assertEqual(
                {"role": "user", "text": "$compass goal"},
                observer._message_from("user", "$compass goal", harness, 2000),
            )

    def test_a_person_still_reads_codex_agent_output_after_the_action(self) -> None:
        # No Codex turn boundary has been captured: assistant text is still admitted.
        self.assertEqual(
            {"role": "assistant", "text": "$compass sessions waiting"},
            observer._message_from("assistant", "$compass sessions waiting", "codex", 2000),
        )
        for record in (
            test_transcripts.CodexInstructionTest._commentary_old(10, "$compass goal"),
            test_transcripts.CodexInstructionTest._commentary_item(10, "$compass goal"),
        ):
            self.assertEqual(
                ("commentary", "$compass goal"), transcripts._codex_scan_record(record)[:2]
            )

    def test_a_persons_unknown_content_block_is_not_assumed_to_be_a_typed_action(self) -> None:
        contents: tuple[Any, ...] = (
            None,
            {},
            [],
            ["$compass goal"],
            [{"type": "image", "text": "$compass goal"}],
            [{"type": "input_text", "text": 42}],
        )
        for content in contents:
            with self.subTest(content=content):
                self.assertFalse(records.codex_compass_command(content))

    def test_a_persons_prose_beyond_the_excerpt_does_not_turn_into_an_action(self) -> None:
        text = "$compass goal" + " " * 3000 + "then finish the parser"
        row = self.candidates(captured_messages(text, command=False))
        self.assertTrue(row["first_prompt"])
        self.assertTrue(row["last_prompt"])
        self.assertIsNotNone(
            observer.parse_message_record(captured_messages(text, command=False)[0])
        )

    def test_a_persons_action_with_an_image_offers_no_direction_or_goal(self) -> None:
        # Rejecting either captured image block (or retaining its markers) leaks an action.
        for record in captured_image_messages():
            with self.subTest(shape=record["type"]):
                self.assertIsNone(observer.parse_message_record(record))
                row = self.candidates([record])
                self.assertEqual("", row["first_prompt"])
                self.assertEqual("", row["last_prompt"])
                self.assertIsNone(row["instruction"])
                self.assertEqual(
                    [],
                    project_context.instruction_events(self.config, str(self.path), "codex", "p"),
                )
                for source in ("first-prompt", "latest-prompt"):
                    self.assertEqual(("", None), annotation_store.prompt_candidate(row, source))
                    self.assertNotEqual(
                        annotation_store.OUTCOME_STORED,
                        annotation_store.adopt(
                            self.config,
                            self.state,
                            row,
                            source=source,
                            expected_text="$compass sessions waiting",
                            expected_at=NOW + 20,
                            now=NOW + 60,
                        ),
                    )
                self.assertEqual(
                    observer.NO_GOAL,
                    observer.analyze(
                        self.config, self.state, str(self.path), now=NOW + 60, window_sec=86400
                    )["goal"],
                )

    def test_a_persons_image_action_keeps_their_previous_work_as_the_latest_goal_offer(
        self,
    ) -> None:
        for record in captured_image_messages():
            with self.subTest(shape=record["type"]):
                previous = next(
                    r
                    for r in captured_messages(FIRST, command=False)
                    if r["type"] == record["type"]
                )
                row = self.candidates([previous, record])
                self.assertEqual(FIRST, row["last_prompt"])
                self.assertEqual(
                    (FIRST, NOW + 10), annotation_store.prompt_candidate(row, "latest-prompt")
                )
                self.assertEqual("", transcripts._codex_scan_record(record)[0])
                if record["type"] == "response_item":
                    self.assertEqual(
                        [FIRST],
                        [
                            e["title"]
                            for e in project_context.instruction_events(
                                self.config, str(self.path), "codex", "p"
                            )
                        ],
                    )
                    self.assertEqual(
                        FIRST,
                        observer.analyze(
                            self.config, self.state, str(self.path), now=NOW + 60, window_sec=86400
                        )["goal"],
                    )

    def test_a_persons_words_beside_an_image_stay_a_direction_and_goal_offer(self) -> None:
        # An overbroad action prefix or discarded extra text would hide the person's work.
        for text in (FIRST, "$compass sessions and fix it"):
            for record in captured_image_messages(text):
                with self.subTest(text=text, shape=record["type"]):
                    self.assert_image_direction(record, text)
                    if record["type"] == "response_item":
                        self.assertTrue(
                            project_context.instruction_events(
                                self.config, str(self.path), "codex", "p"
                            )
                        )

    def assert_image_direction(self, record: dict[str, Any], text: str) -> None:
        self.assertEqual("prompt", transcripts._codex_scan_record(record)[0])
        row = self.candidates([record])
        self.assertIn(text, row["first_prompt"])
        self.assertIn(text, row["last_prompt"])
        for source in ("first-prompt", "latest-prompt"):
            candidate, at = annotation_store.prompt_candidate(row, source)
            self.assertIn(text, candidate)
            self.assertEqual(NOW + 20, at)
        if record["type"] == "response_item":
            self.assertIsNotNone(observer.parse_message_record(record))

    def test_a_persons_second_text_block_beside_an_image_stays_a_direction(self) -> None:
        for text, extra_text in (
            ("$compass", "sessions waiting"),
            ("$compass sessions waiting", FIRST),
            ("$compass sessions waiting", ""),
        ):
            for record in captured_image_messages(text):
                content = record["payload"].get("content") or record["payload"]["item"]["content"]
                extra = copy.deepcopy(content[-1])
                extra["text"] = extra_text
                content.append(extra)
                with self.subTest(text=text, extra=extra_text, shape=record["type"]):
                    self.assert_image_direction(record, text)

    def test_a_persons_unrecognised_block_beside_an_image_keeps_their_direction(self) -> None:
        for extra in (None, {"type": "audio"}, {"type": "input_text", "text": 42}):
            for record in captured_image_messages():
                content = record["payload"].get("content") or record["payload"]["item"]["content"]
                content.append(extra)
                with self.subTest(extra=extra, shape=record["type"]):
                    self.assert_image_direction(record, "$compass sessions waiting")

    def test_a_persons_text_that_resembles_an_image_marker_stays_a_direction(self) -> None:
        # Prefix searches, case folding or whitespace trimming must not swallow real text.
        for marker in (
            '<image name=[Image #1] path="placeholder.png"> please fix it',
            ' <image name=[Image #1] path="placeholder.png">',
            '<image name=[Image #0] path="placeholder.png">',
            "<image name=[Image #1] path=placeholder.png>",
            '<Image name=[Image #1] path="placeholder.png">',
            '<image name=[Image #1] path="placeholder.png">\n',
            "</image> please fix it",
            " </image>",
            "</IMAGE>",
            "</image>\n",
        ):
            for record in captured_image_messages():
                content = record["payload"].get("content") or record["payload"]["item"]["content"]
                extra = copy.deepcopy(content[-1])
                extra["text"] = marker
                content.insert(0, extra)
                with self.subTest(marker=marker, shape=record["type"]):
                    self.assert_image_direction(record, "$compass")


if __name__ == "__main__":
    unittest.main()
