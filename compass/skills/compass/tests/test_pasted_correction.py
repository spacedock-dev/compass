"""A pasted Steer back correction is Compass's own words, whatever wraps it (DRC-4920).

Claude Code 2.1.305 stores a paste as the string `\\n\\n<pasted_content id="N">\\nTEXT\\n</pasted_content>\\n`
(a user record whose `message.content` is that string, with `origin.kind` `human`), so the digest of a
pasted correction never equalled the digest of the text the reader copied. The reader's next reading then
counted the correction as a new direction, offered it as a goal, quoted the wrapper, cited it under a
departure and dated the departure to the steer. These tests hold the five places that went wrong: the
strip itself, the digest match, what the page is shown, what a departure may cite, and the correction
Compass builds from a reading.

Every text here is placeholder prose; the shape is the one the recorded paste has.
"""

from __future__ import annotations

import json
import unittest
from typing import Any, ClassVar, cast

from compass_runtime import copied_corrections as copies
from compass_runtime import correction, project_context, reading, records

from .test_claims_and_adopted_goal import SID, _agent, _person, _Producer
from .test_claude_checks import SHORT, START
from .test_copied_corrections import COPIED, OWN, STORED, _App, _paste, _Store
from .test_correction import DEPARTED, GOAL, fact, row_of, session_row
from .test_correction import reading as stored_reading

TAG_OPEN = '<pasted_content id="3">'
TAG_CLOSE = "</pasted_content>"


def wrapped(text: str, *, before: str = "", after: str = "") -> str:
    """What Claude Code 2.1.305 writes for a paste, with any text typed around it."""
    return f"{before}\n\n{TAG_OPEN}\n{text}\n{TAG_CLOSE}\n{after}"


class StripPasteWrapperTest(unittest.TestCase):
    def test_the_wrapper_comes_off_and_the_paste_stays(self) -> None:
        self.assertEqual(
            "Back to my goal: ship it.",
            records.strip_paste_wrapper(wrapped("Back to my goal: ship it.")),
        )

    def test_a_paste_beside_typed_words_keeps_both(self) -> None:
        text = records.strip_paste_wrapper(wrapped("pasted words", before="see this:"))
        self.assertEqual("see this:\n\n\npasted words", text)

    def test_any_id_and_more_than_one_paste_are_read(self) -> None:
        two = f'a <pasted_content id="12">\none\n{TAG_CLOSE} b <pasted_content id="13" name="x">\ntwo\n{TAG_CLOSE}'
        self.assertEqual("a \none\n b \ntwo", records.strip_paste_wrapper(two))

    def test_text_with_no_wrapper_is_returned_trimmed_and_otherwise_unchanged(self) -> None:
        self.assertEqual("plain words", records.strip_paste_wrapper("  plain words \n"))

    def test_another_tag_is_never_touched(self) -> None:
        other = "<pasted_contents>x</pasted_contents> and <pasted_content_x>y</pasted_content_x>"
        self.assertEqual(other, records.strip_paste_wrapper(other))


class TheDigestSeesThroughTheWrapperTest(_Store):
    def register_and_paste(self, message: str) -> list[float]:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        at = _paste(self.session, message)
        self.session.save(self.path)
        return [at]

    def test_a_correction_pasted_through_the_wrapper_is_recognised(self) -> None:
        at = self.register_and_paste(wrapped(STORED))
        self.assertEqual(at, [entry["at"] for entry in self.matched()])

    def test_the_copy_that_carries_crlf_and_a_tab_is_recognised_through_the_wrapper(self) -> None:
        # The wrapper does not change what the input box did to the paste (paste4678).
        self.register(COPIED, now=START.timestamp() + self.session.seconds + 1)
        at = _paste(self.session, wrapped(STORED))
        self.session.save(self.path)
        self.assertEqual([at], [entry["at"] for entry in self.matched()])

    def test_words_typed_around_the_paste_make_it_the_readers_own(self) -> None:
        self.register_and_paste(wrapped(STORED, before="Do this:"))
        self.assertEqual((), self.matched())
        self.register_and_paste(wrapped(STORED, after="and then stop."))
        self.assertEqual((), self.matched())

    def test_a_wrapped_edit_is_still_the_readers_own_words(self) -> None:
        self.register_and_paste(wrapped(STORED + " now"))
        self.assertEqual((), self.matched())

    def test_the_published_fact_never_carries_the_wrapper(self) -> None:
        self.register_and_paste(wrapped(STORED))
        found = [f for f in self.user_facts() if "pasted_content" in json.dumps(f)]
        self.assertEqual([], found)


class AWhitespaceOnlyEditIsStillTheCorrectionTest(_Store):
    def paste(self, text: str) -> list[float]:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        at = _paste(self.session, text)
        self.session.save(self.path)
        return [at]

    def test_lines_joined_or_runs_of_spaces_widened_still_match(self) -> None:
        for label, edited in (
            ("joined", STORED.replace("\n", " ")),
            ("widened", STORED.replace(" ", "  ")),
            ("blank lines added", STORED.replace("\n", "\n\n")),
        ):
            with self.subTest(case=label):
                self.setUp()
                at = self.paste(wrapped(edited))
                self.assertEqual(at, [entry["at"] for entry in self.matched()])

    def test_a_changed_word_is_not_a_whitespace_edit(self) -> None:
        self.paste(wrapped(STORED.replace("lexer", "parser")))
        self.assertEqual((), self.matched())

    def test_whitespace_inside_a_word_is_a_different_word(self) -> None:
        self.paste(wrapped(STORED.replace("placeholder", "place holder")))
        self.assertEqual((), self.matched())

    def test_a_copy_stored_before_this_field_existed_still_matches_exactly(self) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        stored = json.loads(self.config_store())
        for entry in stored["entries"]:
            for copy in entry["copies"]:
                del copy["folded"]
        self.write_store(stored)
        at = _paste(self.session, wrapped(STORED))
        self.session.save(self.path)
        self.assertEqual([at], [entry["at"] for entry in self.matched()])

    def config_store(self) -> str:
        with open(copies.store_path(self.config), encoding="utf-8") as handle:
            return handle.read()

    def write_store(self, payload: Any) -> None:
        with open(copies.store_path(self.config), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)


class WhatThePageIsShownIsTheCorrectionNotTheWrapperTest(_App):
    def test_the_direction_text_the_page_opens_has_no_wrapper(self) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        at = _paste(self.session, wrapped(OWN, before="Also:"))
        self.session.save(self.path)
        fact_row = next(f for f in self.user_facts() if float(f["at"]) == at)
        opened = project_context.direction_text(
            self.config, self.state, "claude", SHORT, str(fact_row["fact_id"])
        )
        self.assertIn(OWN, opened.text)
        self.assertNotIn("pasted_content", opened.text)
        self.assertNotIn("pasted_content", json.dumps(fact_row))

    def test_a_recognised_paste_is_not_a_later_direction_and_the_row_names_it(self) -> None:
        self.register(now=START.timestamp() + self.session.seconds + 1)
        at = _paste(self.session, wrapped(STORED))
        self.session.save(self.path)
        row = self.app().collect(show_all=True)["sessions"][0]
        self.assertEqual([at], [entry["at"] for entry in row["copied_prompts"]])
        self.assertEqual(
            "derived",
            reading.author_of(
                {**next(f for f in self.user_facts() if float(f["at"]) == at), "copied": True}
            ),
        )


SETTLED = 95.0
FLOOR = 50.0


def _kept(fact_id: str, at: float, words: str) -> dict[str, Any]:
    return _person(fact_id, at, words)


class ADepartureNeverCitesTheReadersKeptDirectionOrACorrectionTest(_Producer):
    """The reading guard: the reader's words that settled nothing are no evidence of a departure."""

    REVISION: ClassVar[dict[str, Any]] = {"n": 1, "at": FLOOR, "goal": "add retry", "output": ""}

    def departure(self, cites: list[int]) -> str:
        return json.dumps(
            {"goal": {"result": "departure", "cites": cites, "detail": "it changed course"}}
        )

    def produce_cited(
        self, facts: list[dict[str, Any]], cites: list[int], *, settled: float | None = SETTLED
    ) -> dict[str, Any]:
        assessment, why, _ = self.produce(
            facts,
            revision=self.REVISION,
            answer=self.departure(cites),
            row={reading.COPIED_PROMPTS: [], "annotation_settled_through": settled},
        )
        self.assertEqual("", why)
        return cast("dict[str, Any]", assessment["criteria"]["goal"])

    def agent_after(self) -> dict[str, Any]:
        return _agent("a1", 120.0, "Pruned the stylesheets.")

    def test_a_kept_direction_is_not_cited_under_a_departure(self) -> None:
        facts = [_kept("k1", 90.0, "Also prune the stylesheets."), self.agent_after()]
        criterion = self.produce_cited(facts, [1])
        self.assertNotEqual(reading.RESULT_DEPARTURE, criterion.get("result"))
        self.assertEqual((), tuple(criterion["cites"]))

    def test_a_copied_correction_is_not_cited_under_a_departure(self) -> None:
        correction_fact = {**_person("c1", 100.0, STORED), reading.COPIED_FLAG: True}
        criterion = self.produce_cited([correction_fact, self.agent_after()], [1], settled=None)
        self.assertNotEqual(reading.RESULT_DEPARTURE, criterion.get("result"))

    def test_the_agents_own_work_beside_it_still_carries_the_departure(self) -> None:
        facts = [_kept("k1", 90.0, "Also prune the stylesheets."), self.agent_after()]
        criterion = self.produce_cited(facts, [1, 2])
        self.assertEqual(reading.RESULT_DEPARTURE, criterion["result"])
        self.assertEqual(("a1",), tuple(criterion["cites"]))

    def test_a_direction_the_reader_has_not_settled_is_still_citable(self) -> None:
        facts = [_kept("u1", 110.0, "Also prune the stylesheets."), self.agent_after()]
        criterion = self.produce_cited(facts, [1, 2])
        self.assertEqual(reading.RESULT_DEPARTURE, criterion["result"])
        self.assertEqual(("u1", "a1"), tuple(criterion["cites"]))

    def test_the_helper_names_exactly_the_kept_and_the_copied(self) -> None:
        facts = [
            _kept("first", 20.0, "Add retry."),
            _kept("kept", 90.0, "Also prune."),
            _kept("open", 110.0, "Now stop."),
            {**_person("copy", 100.0, STORED), reading.COPIED_FLAG: True},
            self.agent_after(),
        ]
        found = reading.settled_reader_words(
            facts, SID["harness"], SID["sid"], floor=FLOOR, settled_through=SETTLED
        )
        self.assertEqual(frozenset({"kept", "copy"}), found)


class ACorrectionDoesNotDateADepartureToTheSteerTest(unittest.TestCase):
    """Steer back rebuilt after a steer starts from the agent's work, never from the pasted words."""

    FACTS = (
        fact("agent1", 130.0, "assistant_message", summary="Pruned."),
        {**fact("paste", 112.0, "user_message", summary="Back to my goal"), "copied": True},
        fact("kept", 104.0, "user_message", summary="Also prune the stylesheets"),
    )

    def composed(self, cites: tuple[str, ...], **over: Any) -> str:
        criteria = stored_reading(goal=row_of(DEPARTED, cites, clause=GOAL))
        row = session_row(
            annotation_assessment=criteria,
            annotation_line_1="",
            annotation_line_2="",
            annotation_line_3="",
            annotation_settled_through=106.0,
            **over,
        )
        result = correction.compose(
            row, self.FACTS, floor=100.0, lines_judged=True, clock=lambda at: f"T{int(at)}"
        )
        self.assertTrue(result["ok"], result)
        return "".join(
            part if isinstance(part, str) else "{" + part["entry"] + "}" for part in result["parts"]
        )

    def test_the_date_is_the_agents_work_not_the_pasted_correction(self) -> None:
        text = self.composed(("paste", "agent1"))
        self.assertIn("departed from my goal at T130{agent1}", text)
        self.assertNotIn("{paste}", text)

    def test_a_kept_direction_does_not_date_it_either(self) -> None:
        text = self.composed(("kept", "agent1"))
        self.assertIn("departed from my goal at T130{agent1}", text)

    def test_a_departure_resting_only_on_those_words_names_no_moment(self) -> None:
        # Nothing the reader did not say stands behind it, so there is no departure to date.
        criteria = stored_reading(goal=row_of(DEPARTED, ("paste", "kept"), clause=GOAL))
        row = session_row(
            annotation_assessment=criteria,
            annotation_line_1="",
            annotation_line_2="",
            annotation_line_3="",
            annotation_settled_through=106.0,
        )
        result = correction.compose(
            row, self.FACTS, floor=100.0, lines_judged=True, clock=lambda at: f"T{int(at)}"
        )
        text = "".join(
            p if isinstance(p, str) else "{" + p["entry"] + "}" for p in result.get("parts", [])
        )
        self.assertNotIn("departed from my goal", text)


if __name__ == "__main__":
    unittest.main()
