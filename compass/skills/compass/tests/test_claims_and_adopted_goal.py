"""An adopted goal is read whole, and what the agent claims is its own constraint.

Owner, 2026-10-04, from the first drift replay run (docs/drift-replay/README.md, "The first
run"): a goal adopted from the reader's prompt kept 240 characters, which dropped the instruction
that mattered in one session and kept only plan-file preamble in another; and most drift the
reader pushed back on was a status claim ("merged", "tests pass") that no intent line speaks to.

So a reading sends the adopted prompt's whole words as the Goal, out of the reader's words share,
and keeps the clip everywhere else; and a reader's press on a Claude Code session that carries the
agent's messages asks a `claims` question beside the intent, whose fourth result, `unsupported`,
is a caution and never a departure (DEC-17 rule 3).

Every message here is placeholder prose.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import correction, levels, observer, reading
from compass_runtime.config import build_runtime_config

REPO = Path(__file__).resolve().parents[4]
SCORER = REPO / "scripts"

SID = {"harness": "claude", "sid": "s1"}
CLIP = "Make the retry queue survive a restart, and before anything else read the plan file " + (
    "and its preamble " * 9
)
CLIP = CLIP[:239] + "…"
POINT = "the one instruction that mattered: never drop a queued event on shutdown"
WHOLE = CLIP[:-1] + " and so on. " + "More plan text. " * 30 + POINT
BUDGET = 16_384


def _person(fact_id: str, at: float, words: str, summary: str = "") -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": "user_message",
        "summary": summary or f"{fact_id} opens",
        reading.WORDS_FIELD: words,
        "at": at,
        "source_session": SID,
        "evidence": {"source": "timestamped non-meta user-role record", "confidence": "exact"},
    }


def _agent(fact_id: str, at: float, title: str) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": reading.AGENT_MESSAGE_TYPE,
        "summary": title,
        reading.AGENT_WORDS_FIELD: f"{title} More words follow the title.",
        "at": at,
        "source_session": SID,
        "evidence": {
            "source": "timestamped top-level assistant text record",
            "confidence": "exact",
        },
    }


def _check(fact_id: str, at: float, result: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "fact_id": fact_id,
        "type": reading.TOOL_REPORT_TYPE,
        "subject": reading.CHECK_SUBJECT,
        "result": result,
        "result_source": "flag",
        "summary": "python3 -m pytest tests/test_retry.py",
        "at": at,
        "evidence": {"source": "Claude Bash call and paired result", "confidence": "exact"},
        "source_session": SID,
        "branch": {**SID, "record_id": f"call-{fact_id}"},
    }
    row.update(extra)
    return row


def _snapshot(fact_id: str, at: float) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "type": "observer_snapshot",
        "summary": "Compass's summary: the retry merged",
        "at": at,
        "source_session": SID,
        "evidence": {"source": "observer snapshot", "confidence": "low"},
    }


class _Producer(unittest.TestCase):
    """One `produce` call, the prompts kept, no model reached."""

    class _Config:
        reading_settle_sec = 8.0
        annotation_text_cap_chars = 240

    def setUp(self) -> None:
        self.prompts: list[str] = []

    def model(self, answer: str = "{}") -> Any:
        def run(prompt: str, **_kw: Any) -> tuple[str, str]:
            self.prompts.append(prompt)
            return answer, "ok"

        return run

    def produce(
        self,
        facts: list[dict[str, Any]],
        *,
        revision: dict[str, Any] | None = None,
        answer: str = "{}",
        read_agent_words: bool = True,
        tool_output: reading.ToolOutput | None = None,
        goal_source_lookup: Any = None,
        row: dict[str, Any] | None = None,
    ) -> Any:
        return reading.produce(
            cast("Any", self._Config()),
            {**SID, "state": "working", "ended_at": None, **(row or {})},
            [revision or {"n": 1, "at": 50.0, "goal": "add retry", "output": "tests pass"}],
            facts,
            now=500.0,
            stamp_text="read at 10:00",
            model=self.model(answer),
            tool_output=tool_output,
            read_lines=True,
            read_agent_words=read_agent_words,
            goal_source_lookup=goal_source_lookup,
        )


ADOPTED = {
    "n": 1,
    "at": 200.0,
    "goal": CLIP,
    "output": "",
    "goal_source": "first-prompt",
    "goal_source_at": 60.0,
}


class APressCanFindItsGoalOutsideTheEvidenceTail(_Producer):
    def test_empty_prefix_keeps_a_source_already_in_the_tail(self) -> None:
        assessment, _, _ = self.produce(
            [_person("p1", 60.0, WHOLE)],
            revision=ADOPTED,
            goal_source_lookup=list,
        )
        self.assertIn(POINT, self.prompts[0])
        self.assertNotIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_a_copy_mark_in_the_tail_also_marks_the_lookup_source(self) -> None:
        source = _person("p1", 60.0, WHOLE)
        assessment, _, _ = self.produce(
            [{**source, reading.COPIED_FLAG: True}, _agent("a1", 90.0, "The queue was written.")],
            revision=ADOPTED,
            goal_source_lookup=lambda: [source],
        )
        self.assertNotIn(POINT, self.prompts[0])
        self.assertIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_a_copy_mark_outside_the_tail_still_refuses_the_source(self) -> None:
        source = _person("p1", 60.0, WHOLE)
        assessment, _, _ = self.produce(
            [_agent("a1", 90.0, "The queue was written.")],
            revision=ADOPTED,
            goal_source_lookup=lambda: [source],
            row={reading.COPIED_PROMPTS: [{"fact_id": "p1", "at": 60.0}]},
        )
        self.assertNotIn(POINT, self.prompts[0])
        self.assertIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_duplicate_source_in_tail_and_lookup_is_not_an_ambiguity(self) -> None:
        source = _person("p1", 60.0, WHOLE)
        self.produce([source], revision=ADOPTED, goal_source_lookup=lambda: [source])
        self.assertIn(POINT, self.prompts[0])

    def test_the_lookup_supplies_only_the_goal_and_never_widens_the_ledger(self) -> None:
        source = _person("old-source", 60.0, WHOLE)
        unrelated = _person("old-unrelated", 70.0, "Never send these other old words.")
        assessment, why, spent = self.produce(
            [_agent("recent", 100.0, "The queue was written.")],
            revision=ADOPTED,
            goal_source_lookup=lambda: [source, unrelated],
        )
        self.assertEqual("", why)
        self.assertTrue(spent)
        self.assertIsNotNone(assessment)
        self.assertIn(POINT, self.prompts[0])
        self.assertNotIn("Never send these other old words.", self.prompts[0])
        self.assertNotIn("old-unrelated", self.prompts[0])
        self.assertNotIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_typed_goals_never_read_the_source_lookup(self) -> None:
        def forbidden() -> Any:
            self.fail("Typed goals must not scan a second transcript source")

        self.produce(
            [_agent("recent", 100.0, "The queue was written.")], goal_source_lookup=forbidden
        )


class AnAdoptedGoalIsReadWholeTest(_Producer):
    def goal_block(self) -> str:
        prompt = self.prompts[0]
        return prompt[prompt.index("<goal>\n") + 7 : prompt.index("\n</goal>")]

    def test_the_whole_prompt_is_the_goal_the_model_reads(self) -> None:
        facts = [_person("p1", 60.0, WHOLE), _agent("a1", 90.0, "I wired the queue.")]
        assessment, why, _ = self.produce(facts, revision=ADOPTED)
        self.assertEqual("", why)
        self.assertIn(POINT, self.goal_block())
        self.assertNotIn("…", self.goal_block())
        self.assertNotIn(reading.GOAL_SOURCE_UNROOMED.strip(), assessment["cutoff"])
        self.assertNotIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_the_stored_reading_keeps_the_clip_and_nothing_new(self) -> None:
        facts = [_person("p1", 60.0, WHOLE)]
        assessment, _, _ = self.produce(facts, revision=ADOPTED)
        self.assertEqual(CLIP, assessment["criteria"]["goal"]["clause"])
        self.assertNotIn(POINT, json.dumps(assessment))
        self.assertLessEqual(set(assessment), set(reading.ASSESSMENT_KEYS))
        self.assertEqual("first-prompt", assessment["goal_source"])
        self.assertNotIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_the_source_row_is_not_sent_whole_a_second_time(self) -> None:
        self.produce([_person("p1", 60.0, WHOLE)], revision=ADOPTED)
        self.assertEqual(1, self.prompts[0].count(POINT))

    def test_with_the_prompt_gone_the_clip_is_read_and_the_cutoff_says_so(self) -> None:
        facts = [_person("p9", 70.0, "a later message"), _agent("a1", 90.0, "I wired it.")]
        assessment, _, _ = self.produce(facts, revision=ADOPTED)
        self.assertEqual(CLIP, self.goal_block())
        self.assertIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_a_prompt_with_no_words_left_reads_as_gone(self) -> None:
        bare = _person("p1", 60.0, "")
        assessment, _, _ = self.produce([bare, _agent("a1", 90.0, "Done.")], revision=ADOPTED)
        self.assertEqual(CLIP, self.goal_block())
        self.assertIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_a_goal_from_the_goal_command_has_no_prompt_to_be_missing(self) -> None:
        stated = {**ADOPTED, "goal_source": reading.SESSION_GOAL}
        assessment, _, _ = self.produce([_agent("a1", 90.0, "I wired it.")], revision=stated)
        self.assertEqual(CLIP, self.goal_block())
        self.assertNotIn("prompt your goal came from", assessment["cutoff"])

    def test_a_typed_goal_is_never_replaced(self) -> None:
        typed = {k: v for k, v in ADOPTED.items() if not k.startswith("goal_source")}
        typed["at"] = 60.0
        assessment, _, _ = self.produce([_person("p1", 60.0, WHOLE)], revision=typed)
        self.assertEqual(CLIP, self.goal_block())
        self.assertNotIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_a_copied_correction_at_that_time_is_never_the_source(self) -> None:
        copied = {**_person("p1", 60.0, WHOLE), reading.COPIED_FLAG: True}
        assessment, _, _ = self.produce([copied, _agent("a1", 90.0, "ok")], revision=ADOPTED)
        self.assertEqual(CLIP, self.goal_block())
        self.assertIn(reading.GOAL_SOURCE_GONE.strip(), assessment["cutoff"])

    def test_two_prompts_at_the_same_moment_are_told_apart_by_their_opening(self) -> None:
        other = _person("p0", 60.0, "an unrelated prompt " * 10)
        self.produce([other, _person("p1", 60.0, WHOLE)], revision=ADOPTED)
        self.assertIn(POINT, self.goal_block())

    def test_each_adopted_source_reads_whole(self) -> None:
        for source in reading.PROMPT_SOURCES:
            with self.subTest(source=source):
                self.prompts.clear()
                self.produce(
                    [_person("p1", 60.0, WHOLE)], revision={**ADOPTED, "goal_source": source}
                )
                self.assertIn(POINT, self.goal_block())

    def test_with_no_room_the_clip_is_read_and_the_cutoff_says_so(self) -> None:
        facts = [_person("p1", 60.0, WHOLE), _agent("a1", 90.0, "I wired it.")]
        with mock.patch.object(observer, "OBSERVER_MODEL_MAX_PROMPT_BYTES", 2_900):
            assessment, why, _ = self.produce(facts, revision=ADOPTED)
        self.assertEqual("", why)
        self.assertEqual(CLIP, self.goal_block())
        self.assertIn(reading.GOAL_SOURCE_UNROOMED.strip(), assessment["cutoff"])


class TheGoalsWordsComeFromTheReadersShareTest(unittest.TestCase):
    """Out of the person-words half, before any message's words, never in place of an entry."""

    def prompt(self, facts: list[dict[str, Any]], max_bytes: int = BUDGET) -> Any:
        ledger = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
        return reading.build_prompt(
            ledger,
            goal=CLIP,
            lines=("the queue survives a restart",),
            max_bytes=max_bytes,
            goal_words=WHOLE,
            goal_fact="p1",
        )

    def test_the_goal_goes_whole_before_the_readers_other_messages(self) -> None:
        people = [_person(f"q{n:02d}", 100.0 + n, f"q{n:02d} MINE " + "m" * 990) for n in range(20)]
        prompt, selection = self.prompt(
            [_person("p1", 60.0, WHOLE), *people, _check("c1", 400.0, "failed")]
        )
        self.assertTrue(selection.goal_whole)
        self.assertIn(POINT, prompt)
        self.assertIn("python3 -m pytest", prompt)
        mine = [line for line in prompt.splitlines() if line.startswith("[") and " MINE " in line]
        goal = prompt[prompt.index("<goal>") : prompt.index("</goal>")]
        # The reader's half holds the goal's words and the messages read whole together.
        spent = sum(len((row + "\n").encode()) for row in mine) + len(goal.encode())
        self.assertLessEqual(spent, BUDGET // reading.WORDS_SHARE_DIVISOR + len(CLIP.encode()))

    def test_the_goals_words_never_cost_an_entry(self) -> None:
        facts = [_person("p1", 60.0, WHOLE), _check("c1", 400.0, "failed")]
        for budget in range(1_800, 6_000, 50):
            with self.subTest(budget=budget):
                plain = reading.build_prompt(
                    reading.build_ledger(facts, "claude", "s1", tool_output={}),
                    goal=CLIP,
                    lines=("the queue survives a restart",),
                    max_bytes=budget,
                )[1]
                whole = self.prompt(facts, budget)[1]
                self.assertEqual(
                    [row["id"] for row in plain.entries], [row["id"] for row in whole.entries]
                )

    def test_without_room_it_keeps_the_clip(self) -> None:
        prompt, selection = self.prompt([_person("p1", 60.0, WHOLE)], max_bytes=2_400)
        self.assertFalse(selection.goal_whole)
        self.assertIn(CLIP, prompt)
        self.assertLessEqual(len(prompt.encode()), 2_400)


class TheClaimsQuestionIsAskedOnlyWithTheAgentsWordsTest(_Producer):
    def test_a_press_carrying_an_agent_message_asks_it_and_stores_it_last(self) -> None:
        facts = [_person("p1", 60.0, "add retry"), _agent("a1", 90.0, "All tests pass.")]
        answer = json.dumps({"claims": {"result": "unsupported", "cites": [2]}})
        assessment, _, _ = self.produce(facts, answer=answer)
        self.assertIn('"claims": A', self.prompts[0])
        self.assertIn(reading.NONFINAL_CLAIMS_RULE.strip(), self.prompts[0])
        self.assertEqual("claims", list(assessment["criteria"])[-1])
        row = assessment["criteria"]["claims"]
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        self.assertEqual(("a1",), row["cites"])
        self.assertEqual("", row["clause"])

    def test_no_agent_message_no_question(self) -> None:
        assessment, _, _ = self.produce([_person("p1", 60.0, "add retry")])
        self.assertNotIn('"claims"', self.prompts[0])
        self.assertNotIn("claims", assessment["criteria"])

    def test_the_unasked_lane_and_the_scorers_never_ask_it(self) -> None:
        facts = [_person("p1", 60.0, "add retry"), _agent("a1", 90.0, "All tests pass.")]
        assessment, _, _ = self.produce(facts, read_agent_words=False)
        self.assertNotIn('"claims"', self.prompts[0])
        self.assertNotIn("All tests pass", self.prompts[0])
        self.assertNotIn("claims", assessment["criteria"])

    def test_a_goal_or_line_answered_unsupported_has_no_result(self) -> None:
        facts = [_person("p1", 60.0, "add retry"), _agent("a1", 90.0, "All tests pass.")]
        answer = json.dumps(
            {
                "goal": {"result": "unsupported", "cites": [2]},
                "line_1": {"result": "unsupported", "cites": [2]},
            }
        )
        assessment, _, _ = self.produce(facts, answer=answer)
        for name in ("goal", "line_1"):
            with self.subTest(name=name):
                self.assertNotIn("result", assessment["criteria"][name])
                self.assertEqual(reading.WHY_UNREADABLE, assessment["criteria"][name]["why"])


def _resolve(token: str, facts: list[dict[str, Any]], cites: list[int], **kw: Any) -> Any:
    entries = reading.build_ledger(facts, "claude", "s1", tool_output={}, read_agent_words=True)
    return reading._resolve_one(
        {"token": token, "cites": cites, "detail": kw.pop("detail", "")},
        dict(enumerate(entries, 1)),
        name=reading.CONSTRAINT_CLAIMS,
        clause="",
        detail_cap_chars=200,
        window_start=50.0,
        **kw,
    )


SAID = _agent("a1", 90.0, "All tests pass.")
RETRY = "python3 -m pytest tests/test_retry.py"
FAILED = _check("c1", 95.0, "failed")
PASSED = _check("c1", 95.0, "passed")


class EachClaimsResultCitesWhatItNeedsTest(unittest.TestCase):
    """Rule 3 for this question, and rule 4's backstop: the cases the resolver keeps."""

    # (case, token, facts in time order, cites, result, why)
    CASES: tuple[tuple[str, str, list[dict[str, Any]], list[int], str, str], ...] = (
        ("contradicted", "departure", [SAID, FAILED], [1, 2], reading.RESULT_DEPARTURE, ""),
        (
            "contradicted on the message alone",
            "departure",
            [SAID],
            [1],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CLAIM_UNCITED,
        ),
        (
            "contradicted with no message",
            "departure",
            [SAID, FAILED],
            [2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CLAIM_UNCITED,
        ),
        (
            "contradicted by a pass",
            "departure",
            [SAID, PASSED],
            [1, 2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CHECK_DOES_NOT_SHOW_IT,
        ),
        ("unshown", "unsupported", [SAID], [1], reading.RESULT_UNSUPPORTED, ""),
        (
            "unshown citing only the reader",
            "unsupported",
            [_person("p1", 80.0, "is it merged?"), SAID],
            [1],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CLAIM_UNCITED,
        ),
        ("shown", "consistent", [SAID, PASSED], [1, 2], reading.RESULT_CONSISTENT, ""),
        (
            "shown by the message alone",
            "consistent",
            [SAID],
            [1],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CLAIM_UNCITED,
        ),
        (
            "shown by a pass a write followed",
            "consistent",
            [SAID, _check("c1", 95.0, "passed", before_last_change=True)],
            [1, 2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CHECK_DOES_NOT_SHOW_IT,
        ),
        (
            "shown by a failure",
            "consistent",
            [SAID, FAILED],
            [1, 2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CHECK_DOES_NOT_SHOW_IT,
        ),
        (
            "shown by Compass's own summary",
            "consistent",
            [SAID, _snapshot("o1", 95.0)],
            [1, 2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_BOARD_QUOTING_ITSELF,
        ),
        (
            "contradicted by Compass's own summary",
            "departure",
            [SAID, _snapshot("o1", 95.0)],
            [1, 2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_BOARD_QUOTING_ITSELF,
        ),
        (
            "shown by a person agreeing",
            "consistent",
            [SAID, _person("p1", 92.0, "yes merged")],
            [1, 2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CLAIM_UNCITED,
        ),
        (
            "contradicted by a message before the claim",
            "departure",
            [_person("p0", 80.0, "it is not merged"), _agent("a1", 90.0, "Merged it.")],
            [1, 2],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_CLAIM_UNCITED,
        ),
        (
            "contradicted by a message after the claim",
            "departure",
            [_agent("a1", 90.0, "Merged it."), _person("p2", 95.0, "it is not merged")],
            [1, 2],
            reading.RESULT_DEPARTURE,
            "",
        ),
        (
            "contradicted by a check run before the claim",
            "departure",
            [_check("c1", 85.0, "failed"), SAID],
            [1, 2],
            reading.RESULT_DEPARTURE,
            "",
        ),
        (
            "a message from before the words",
            "unsupported",
            [_agent("a0", 40.0, "Merged."), SAID],
            [1],
            reading.RESULT_UNVERIFIABLE,
            reading.WHY_UNCITED,
        ),
    )

    def test_each_case(self) -> None:
        for case, token, facts, cites, result, why in self.CASES:
            with self.subTest(case=case):
                row = _resolve(token, facts, cites)
                self.assertEqual(result, row.get("result"))
                self.assertEqual(why, row["why"])
                self.assertIn(row["why"], reading.WHY_TOKENS)

    def test_a_departure_keeps_its_detail_and_an_unsupported_never_does(self) -> None:
        said = "The agent said every test passed and the check at the end failed."
        departed = _resolve("departure", [SAID, FAILED], [1, 2], detail=said)
        self.assertEqual(said, departed["detail"])
        unshown = _resolve("unsupported", [SAID], [1], detail="nothing shows a merge")
        self.assertEqual("", unshown["detail"])

    def test_a_contradicted_or_unshown_claim_may_quote_the_agents_success_words(self) -> None:
        # Review blocker 1: the backstop withdrew exactly the claims it exists for.
        for detail in (
            "The agent said the change works, but the latest check errored.",
            "claimed all tests passed while the check reports a failure.",
        ):
            with self.subTest(detail=detail):
                departed = _resolve("departure", [SAID, FAILED], [1, 2], detail=detail)
                self.assertEqual(reading.RESULT_DEPARTURE, departed["result"])
                self.assertEqual(detail, departed["detail"])
                unshown = _resolve("unsupported", [SAID], [1], detail=detail)
                self.assertEqual(reading.RESULT_UNSUPPORTED, unshown["result"])

    def test_a_stated_verdict_still_withdraws_a_shown_claim(self) -> None:
        row = _resolve("consistent", [SAID, PASSED], [1, 2], detail="it delivered the feature")
        self.assertEqual(reading.WHY_VERDICT_STATED, row["why"])

    def test_a_shown_claim_rests_on_the_work_never_on_a_person(self) -> None:
        row = _resolve("consistent", [SAID, _person("p1", 92.0, "yes merged")], [1, 2])
        self.assertEqual(reading.WHY_CLAIM_UNCITED, row["why"])

    def test_a_contradiction_comes_at_or_after_the_claim_unless_a_check(self) -> None:
        before = _person("p0", 80.0, "it is not merged yet")
        after = _person("p2", 95.0, "it is not merged yet")
        merged = _agent("a1", 90.0, "Merged the branch.")
        self.assertEqual(
            reading.WHY_CLAIM_UNCITED, _resolve("departure", [before, merged], [1, 2])["why"]
        )
        self.assertEqual(reading.WHY_STANDS, _resolve("departure", [merged, after], [1, 2])["why"])
        early = _check("c1", 85.0, "failed")
        self.assertEqual(reading.WHY_STANDS, _resolve("departure", [early, SAID], [1, 2])["why"])

    def test_a_shown_claim_beside_an_unread_failure_is_withdrawn(self) -> None:
        unread = reading.build_ledger(
            [_check("c9", 99.0, "failed")], "claude", "s1", tool_output={}
        )
        row = _resolve("consistent", [SAID, PASSED], [1, 2], unread_failures=unread)
        self.assertEqual(reading.WHY_FAILED_CHECK_UNREAD, row["why"])

    def test_unshown_is_withdrawn_where_the_checks_went_unread(self) -> None:
        row = _resolve("unsupported", [SAID], [1], checks_unread=True)
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])


class UnshownIsWithdrawnWhereTheListingLeftOutAPassOrWriteTest(_Producer):
    """DEC-17, 2026-10-04: a pass or write the prompt did not carry is the record unread."""

    FACTS = (_person("p1", 60.0, "add retry"), _agent("a1", 90.0, "All tests pass."))

    def claims(
        self, press: tuple[tuple[str, str, float], ...], extra: tuple[dict[str, Any], ...] = ()
    ) -> dict[str, Any]:
        facts = sorted([*self.FACTS, *extra], key=lambda fact: fact["at"])
        claim = [fact["fact_id"] for fact in facts].index("a1") + 1
        tool_output = reading.ToolOutput(
            destination="api.example.test", label="the reading model", passes_and_writes=press
        )
        answer = json.dumps({"claims": {"result": "unsupported", "cites": [claim]}})
        assessment, _, _ = self.produce(facts, answer=answer, tool_output=tool_output)
        return cast("dict[str, Any]", assessment["criteria"]["claims"])

    def test_withdrawn_when_a_pass_or_write_not_carried_falls_in_the_window(self) -> None:
        row = self.claims((("call-x", "pytest", 70.0),))
        self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    def test_stands_when_the_left_out_one_is_before_the_window(self) -> None:
        row = self.claims((("call-x", "pytest", 40.0),))
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])

    def test_one_with_no_time_is_counted(self) -> None:
        row = self.claims((("call-x", "pytest", 0.0),))
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, row["why"])

    def test_stands_when_nothing_was_left_out(self) -> None:
        row = self.claims(())
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        self.assertEqual(reading.WHY_STANDS, row["why"])

    def test_one_the_prompt_carried_is_matched_by_record_not_time(self) -> None:
        # Review C4: the press reads again later, so a time can move; the record id cannot.
        carried = _check("c5", 70.0, "passed")
        row = self.claims((("call-c5", RETRY, 75.0),), (carried,))
        self.assertEqual(reading.RESULT_UNSUPPORTED, row["result"])
        moved = self.claims((("call-c6", RETRY, 75.0),), (carried,))
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, moved["why"])
        # Verification 2: a sibling in the same call shares the record id, never the title.
        sibling = self.claims((("call-c5", RETRY, 70.0), ("call-c5", "mypy", 70.0)), (carried,))
        self.assertEqual(reading.WHY_CLAIM_RECORD_UNREAD, sibling["why"])

    def test_never_read_without_a_grant(self) -> None:
        # Unadmitted, the press sends no checks at all and the times are not read.
        tool_output = reading.ToolOutput(
            destination="", label="x", passes_and_writes=(("call-x", "pytest", 70.0),)
        )
        answer = json.dumps({"claims": {"result": "unsupported", "cites": [2]}})
        assessment, _, _ = self.produce(list(self.FACTS), answer=answer, tool_output=tool_output)
        self.assertEqual(reading.RESULT_UNSUPPORTED, assessment["criteria"]["claims"]["result"])


def _run(fact_id: str, at: float, result: str, line: str) -> dict[str, Any]:
    return _check(
        fact_id,
        at,
        result,
        summary=line,
        result_source="flag" if result != "not-recorded" else "",
    )


class AFailureTheAgentRanAgainSinceDoesNotContradictTest(unittest.TestCase):
    """DEC-17, 2026-10-04, as narrowed on verification: a cited failure from before
    the claim does not contradict it when, after it and at or before the claim, the
    same tool ran again without failing, with no earlier failure of its own, naming
    nothing after the tool but flags or `.`."""

    FAILED = _run("c1", 70.0, "failed", RETRY)
    CLAIM = _agent("a1", 90.0, "All tests pass.")

    def departure(self, facts: list[dict[str, Any]]) -> Any:
        ids = [fact["fact_id"] for fact in facts]
        return _resolve("departure", facts, [ids.index("a1") + 1, ids.index("c1") + 1])

    def later(self, failed_line: str, later_line: str, result: str = "passed", **extra: Any) -> Any:
        failed = _run("c1", 70.0, "failed", failed_line)
        later = _run("c2", 80.0, result, later_line)
        later.update(extra)
        return self.departure([failed, later, self.CLAIM])

    def test_withdrawn_by_a_later_whole_suite_run_of_the_same_tool(self) -> None:
        for later_line, result in (
            ("pytest", "not-recorded"),
            ("uv run pytest -q", "passed"),
            ("python -m pytest .", "passed"),
            ("rtk pytest ./ -x", "passed"),
        ):
            with self.subTest(later=later_line):
                row = self.later(RETRY, later_line, result)
                self.assertEqual(reading.RESULT_UNVERIFIABLE, row["result"])
                self.assertEqual(reading.WHY_CHECK_DOES_NOT_SHOW_IT, row["why"])
                self.assertEqual((), row["cites"])

    def test_withdrawn_with_the_later_run_at_the_claims_own_moment(self) -> None:
        later = _run("c2", 90.0, "not-recorded", "pytest")
        row = self.departure([self.FAILED, later, self.CLAIM])
        self.assertEqual(reading.WHY_CHECK_DOES_NOT_SHOW_IT, row["why"])

    def test_stands_when_the_later_run_failed_or_carries_an_earlier_failure(self) -> None:
        self.assertEqual(reading.RESULT_DEPARTURE, self.later(RETRY, "pytest", "failed")["result"])
        row = self.later(RETRY, "pytest", "not-recorded", earlier_failed=True)
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])

    def test_stands_when_the_later_run_names_any_target(self) -> None:
        # The reviewers' cases: narrower, wider, different, a flag's value: none is the whole suite.
        cases = (
            (RETRY, "pytest tests/test_docs.py"),
            ("pytest", "pytest tests/test_one.py::test_x"),
            ("pytest tests/test_retry.py", "pytest tests/test_retry.py -k test_unrelated"),
            ("pytest tests/a.py tests/b.py", "pytest tests/a.py"),
            ("pytest tests/a.py", "pytest tests"),
            ("pytest tests/a.py", "pytest tests/"),
            ("pytest tests.py", "pytest tests"),
            ("pytest tests/a.py::test_x", "pytest tests/a.py --deselect tests/a.py::test_x"),
            ("pytest tests/a.py", "pytest tests --ignore tests/a.py"),
            ("pytest tests/a.py", "pytest -p no:cacheprovider ."),
            ("ruff check src tests", "ruff check src"),
            ("mypy src tests", "mypy src"),
            ("python -m unittest tests.test_a tests.test_b", "python -m unittest tests.test_a"),
            ("python -m unittest tests.test_retry", "python -m unittest discover -s tests"),
            ("python -m unittest tests.test_a.T.test_x", "python -m unittest tests.test_a.T"),
            ("python3 scripts/run_tests.py -s a -t a", "python3 scripts/run_tests.py -s b -t ."),
            ("go test ./pkg/a", "go test ./..."),
            ("dotnet test A.csproj", "dotnet test B.csproj"),
            ("timeout -s KILL 60 pytest", "timeout -s KILL 60 ruff check ."),
            ("docker exec app pytest", "docker exec app ruff check ."),
        )
        for failed_line, later_line in cases:
            with self.subTest(failed=failed_line, later=later_line):
                self.assertEqual(
                    reading.RESULT_DEPARTURE, self.later(failed_line, later_line)["result"]
                )

    def test_stands_with_a_later_run_of_a_different_tool(self) -> None:
        for failed_line, later_line in (
            (RETRY, "mypy"),
            (RETRY, "ruff check ."),
            (RETRY, "python3 scripts/run_tests.py"),
            ("bash scripts/test.sh", "bash scripts/e2e-test.sh"),
            ("bash run_tests.sh", "bash scripts/e2e-test.sh"),
        ):
            with self.subTest(later=later_line):
                self.assertEqual(
                    reading.RESULT_DEPARTURE, self.later(failed_line, later_line)["result"]
                )

    def test_stands_with_a_failure_at_or_after_the_claim(self) -> None:
        for failed_at in (90.0, 95.0):
            with self.subTest(failed_at=failed_at):
                failed = _run("c1", failed_at, "failed", RETRY)
                earlier = _run("c2", 85.0, "not-recorded", "pytest")
                later = _run("c3", 99.0, "not-recorded", "pytest")
                facts = sorted([earlier, self.CLAIM, failed, later], key=lambda f: f["at"])
                row = self.departure(facts)
                self.assertEqual(reading.RESULT_DEPARTURE, row["result"])

    def test_stands_with_no_later_run(self) -> None:
        self.assertEqual(
            reading.RESULT_DEPARTURE, self.departure([self.FAILED, self.CLAIM])["result"]
        )

    def test_stands_when_the_later_run_came_after_the_claim(self) -> None:
        later = _run("c2", 95.0, "passed", "pytest")
        row = self.departure([self.FAILED, self.CLAIM, later])
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])

    def test_stands_when_a_message_after_the_claim_also_contradicts_it(self) -> None:
        later = _run("c2", 80.0, "not-recorded", "pytest")
        said = _person("p2", 95.0, "the tests are still failing")
        facts = [self.FAILED, later, self.CLAIM, said]
        row = _resolve("departure", facts, [3, 1, 4])
        self.assertEqual(reading.RESULT_DEPARTURE, row["result"])


class EachCheckHasOneToolFamilyTest(unittest.TestCase):
    def test_wrappers_and_module_runs_read_as_the_tool(self) -> None:
        cases = {
            "pytest tests/a.py": "pytest",
            "python3 -m pytest -q": "pytest",
            "python -m unittest discover": "unittest",
            "uv run pytest tests": "pytest",
            "rtk pytest": "pytest",
            "rtk proxy pytest": "pytest",
            "npx tsc --noEmit": "tsc",
            "bunx tsc": "tsc",
            "poetry run pytest": "pytest",
            "bundle exec rspec": "rspec",
            "pnpm exec tsc": "tsc",
            "coverage run -m pytest": "pytest",
            "timeout 60 pytest": "pytest",
            "env CI=1 pytest": "pytest",
            "time pytest": "pytest",
            "CI=1 FOO=bar pytest": "pytest",
            "/usr/bin/python3.12 -m mypy src": "mypy",
            "python3 scripts/run_tests.py -j 4": "run_tests.py",
            "./scripts/run_tests.py": "run_tests.py",
            "bash scripts/test.sh": "test.sh",
            "sh run_tests.sh": "run_tests.sh",
            "zsh ci/check.sh": "check.sh",
            "npm test": "npm test",
            "npm run lint -- --fix": "npm run lint",
            "deno task test": "deno task test",
            "go run ./cmd/a": "go run ./cmd/a",
            "ruff check .": "ruff check",
            "ruff format --check .": "ruff format",
            "go test ./...": "go test",
            "make": "make",
        }
        for line, family in cases.items():
            with self.subTest(line=line):
                self.assertEqual(family, reading.check_family(line))

    def test_two_different_tools_are_never_one_family(self) -> None:
        pairs = (
            ("npm test", "npm run lint"),
            ("ruff check .", "ruff format --check ."),
            ("python3 scripts/a_test.py", "python3 scripts/b_test.py"),
            ("python3 -m unittest x", "python3 scripts/run_tests.py"),
            ("pytest", "mypy"),
            ("cargo test", "cargo clippy"),
            ("bash scripts/test.sh", "bash scripts/lint.sh"),
            ("bash run_tests.sh", "bash scripts/e2e-test.sh"),
            ("poetry run pytest", "poetry run mypy ."),
            ("bundle exec rspec", "bundle exec rubocop"),
            ("timeout 60 pytest", "timeout 60 mypy"),
            ("deno task test", "deno task lint"),
            ("go run ./cmd/a", "go run ./cmd/b"),
        )
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                self.assertNotEqual(reading.check_family(first), reading.check_family(second))

    def test_what_cannot_be_told_matches_nothing(self) -> None:
        for line in (
            "",
            "python3 -c 'print(1)'",
            "node --test",
            "bash -c 'pytest'",
            "sh -c 'mypy .'",
            "uv run",
            "uv run --with x pytest",
            "make -C web test",
            "cargo run --bin a",
            "cd web",
            "--version",
        ):
            with self.subTest(line=line):
                self.assertEqual("", reading.check_family(line))


class TheStoreKnowsTheQuestionAndItsResultTest(unittest.TestCase):
    def assessment(self, criteria: dict[str, Any]) -> dict[str, Any]:
        return {
            "revision_read": 1,
            "revision_read_at": 100.0,
            "stamp": "read at 10:00",
            "cutoff": "Read 2 of the 2 entries after your words",
            "scope": reading.SCOPE_FINAL,
            "scope_text": reading.SCOPE_TEXT[reading.SCOPE_FINAL],
            "ended_at_read": 99.0,
            "criteria": criteria,
        }

    @staticmethod
    def row(result: str, cites: tuple[str, ...] = ("a1",), why: str = "") -> dict[str, Any]:
        return {"result": result, "cites": list(cites), "detail": "", "clause": "", "why": why}

    def test_claims_reads_back_last(self) -> None:
        stored = annotation_store._assessment(
            self.assessment(
                {
                    "claims": self.row(reading.RESULT_UNSUPPORTED),
                    "goal": self.row(reading.RESULT_UNVERIFIABLE, ()),
                    "line_1": self.row(reading.RESULT_UNVERIFIABLE, ()),
                }
            ),
            240,
        )
        assert stored is not None
        self.assertEqual(["goal", "line_1", "claims"], list(stored["criteria"]))
        self.assertEqual(reading.RESULT_UNSUPPORTED, stored["criteria"]["claims"]["result"])

    def test_unsupported_anywhere_else_refuses_the_reading_whole(self) -> None:
        for name in ("goal", "line_1"):
            with self.subTest(name=name):
                criteria = {
                    "goal": self.row(reading.RESULT_UNVERIFIABLE, ()),
                    "line_1": self.row(reading.RESULT_UNVERIFIABLE, ()),
                }
                criteria[name] = self.row(reading.RESULT_UNSUPPORTED)
                self.assertIsNone(annotation_store._assessment(self.assessment(criteria), 240))

    def test_a_goal_unclear_reading_is_stored_and_read_back_like_any_other(self) -> None:
        stored = annotation_store._assessment(
            self.assessment({"goal": self.row(reading.RESULT_GOAL_UNCLEAR, ())}), 240
        )
        assert stored is not None
        self.assertEqual(reading.RESULT_GOAL_UNCLEAR, stored["criteria"]["goal"]["result"])

    def test_goal_unclear_anywhere_but_the_goal_refuses_the_reading_whole(self) -> None:
        for name in ("line_1", "claims"):
            with self.subTest(name=name):
                criteria = {
                    "goal": self.row(reading.RESULT_UNVERIFIABLE, ()),
                    "line_1": self.row(reading.RESULT_UNVERIFIABLE, ()),
                }
                criteria[name] = self.row(reading.RESULT_GOAL_UNCLEAR, ())
                self.assertIsNone(annotation_store._assessment(self.assessment(criteria), 240))

    def test_the_new_reason_is_in_the_closed_set(self) -> None:
        criteria = {
            "goal": self.row(reading.RESULT_UNVERIFIABLE, ()),
            "claims": self.row(reading.RESULT_UNVERIFIABLE, (), reading.WHY_CLAIM_UNCITED),
        }
        stored = annotation_store._assessment(self.assessment(criteria), 240)
        assert stored is not None
        self.assertEqual(reading.WHY_CLAIM_UNCITED, stored["criteria"]["claims"]["why"])


class AnOlderBuildRefusesAReadingWithClaimsWholeTest(unittest.TestCase):
    """The downgrade: a build that knows neither the key nor the result refuses the
    reading whole, publishes the refusal and writes it back verbatim."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.config = build_runtime_config(
            environ={"HOME": str(root), "COMPASS_HOME": str(root / "state")},
            platform_name="linux",
            os_name="posix",
            launcher_path=root / "server.py",
        )

    def write(self, assessment: Any) -> dict[str, Any]:
        os.makedirs(self.config.state_home, mode=0o700, exist_ok=True)
        payload = {
            "v": annotation_store.SCHEMA_VERSION,
            "entries": [
                {
                    "harness": "claude",
                    "sid": "s1",
                    "revisions": [{"n": 1, "at": 100.0, "goal": "ship it", "output": ""}],
                    "readings": 1,
                    "assessment": assessment,
                }
            ],
        }
        with open(annotation_store.store_path(self.config), "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        (entry,) = annotation_store.load(self.config)
        return dict(annotation_store.published(entry, binding_why=""))

    def test_refused_whole_kept_verbatim_and_read_again_forward(self) -> None:
        stored = TheStoreKnowsTheQuestionAndItsResultTest().assessment(
            {
                "goal": TheStoreKnowsTheQuestionAndItsResultTest.row(
                    reading.RESULT_UNVERIFIABLE, ()
                ),
                "claims": TheStoreKnowsTheQuestionAndItsResultTest.row(reading.RESULT_UNSUPPORTED),
            }
        )
        older = (
            mock.patch.object(reading, "RESULTS", reading.RESULTS[:3]),
            mock.patch.object(reading, "CONSTRAINT_CLAIMS", "a-key-this-build-never-had"),
        )
        for patch in older:
            with self.subTest(older=str(patch.attribute)), patch:
                row = self.write(stored)
                self.assertIsNone(row["assessment"])
                self.assertTrue(row["reading_refused"])
                entries = annotation_store.load(self.config)
                self.assertTrue(annotation_store.save(self.config, entries, diagnostic_sink=print))
            with open(annotation_store.store_path(self.config), encoding="utf-8") as handle:
                self.assertEqual(stored, json.load(handle)["entries"][0]["assessment"])
            current = self.write(stored)
            self.assertFalse(current["reading_refused"])
            assert current["assessment"] is not None
            self.assertEqual(
                reading.RESULT_UNSUPPORTED, current["assessment"]["criteria"]["claims"]["result"]
            )


def _stored(result: str, cites: list[str], *, lines: int = 1) -> dict[str, Any]:
    criteria: dict[str, Any] = {
        "goal": {
            "result": reading.RESULT_UNVERIFIABLE,
            "cites": [],
            "detail": "",
            "clause": "",
            "why": "",
        },
    }
    for k in range(1, lines + 1):
        criteria[f"line_{k}"] = {
            "result": reading.RESULT_UNVERIFIABLE,
            "cites": [],
            "detail": "",
            "clause": "",
            "why": "",
        }
    criteria["claims"] = {"result": result, "cites": cites, "detail": "", "clause": "", "why": ""}
    return {"read_at": 500.0, "window_start": 50.0, "criteria": criteria}


class TheAnalysisLevelReadsAClaimMediumTest(unittest.TestCase):
    def level(self, result: str, cites: list[str], facts: list[dict[str, Any]]) -> levels.Level:
        evidence = levels.Evidence(tuple(facts), dict.fromkeys(levels.SCAN_KEYS, 0), 0)
        return levels.analysis_level(_stored(result, cites), evidence, outcome_lines=1)

    def test_a_contradicted_claim_reads_medium_with_its_own_reason(self) -> None:
        # A pass, so the failed check's own High is not what decides it.
        facts = [SAID, _person("p1", 92.0, "it is not merged")]
        level = self.level(reading.RESULT_DEPARTURE, ["a1", "p1"], facts)
        self.assertEqual(levels.MEDIUM, level.level)
        self.assertIn(levels.REASON_CLAIM_CONTRADICTED, level.reasons)
        self.assertNotIn(levels.REASON_DEPARTURE, level.reasons)
        self.assertIn("a1", level.cites)

    def test_an_unshown_claim_blocks_low_with_its_own_reason(self) -> None:
        level = self.level(reading.RESULT_UNSUPPORTED, ["a1"], [SAID])
        self.assertEqual(levels.NOT_ENOUGH, level.level)
        self.assertEqual(
            (levels.REASON_CLAIM_NOT_SHOWN, levels.REASON_LINE_NOT_SHOWN), level.reasons
        )
        self.assertEqual(("a1",), level.cites)

    def test_an_unshown_claim_whose_message_left_the_record_reads_nothing(self) -> None:
        level = self.level(reading.RESULT_UNSUPPORTED, ["a1"], [])
        self.assertNotEqual(levels.MEDIUM, level.level)

    def test_a_shown_claim_never_lifts_the_level_to_the_floor(self) -> None:
        level = self.level(reading.RESULT_CONSISTENT, ["a1", "c1"], [SAID, PASSED])
        self.assertEqual(levels.NOT_ENOUGH, level.level)

    def test_a_claims_row_never_holds_the_floor_back(self) -> None:
        # Review blocker 3, the server half: lines shown by a pass reach None or low
        # beside a claims row with nothing to say.
        stored = _stored(reading.RESULT_UNVERIFIABLE, [])
        stored["criteria"]["line_1"] = {
            "result": reading.RESULT_CONSISTENT,
            "cites": ["c1"],
            "detail": "",
            "clause": "",
            "why": "",
        }
        evidence = levels.Evidence(
            (PASSED,), {**dict.fromkeys(levels.SCAN_KEYS, 0), "passed": 1}, 0
        )
        level = levels.analysis_level(stored, evidence, outcome_lines=1)
        self.assertEqual(levels.NONE_OR_LOW, level.level)

    def test_unsupported_on_a_line_is_malformed(self) -> None:
        stored = _stored(reading.RESULT_UNVERIFIABLE, [])
        stored["criteria"]["line_1"]["result"] = reading.RESULT_UNSUPPORTED
        evidence = levels.Evidence((), dict.fromkeys(levels.SCAN_KEYS, 0), 0)
        level = levels.analysis_level(stored, evidence, outcome_lines=1)
        self.assertEqual((levels.REASON_READING_MALFORMED,), level.reasons)


SID_AGENT_PADDED = {**SAID, "fact_id": " a1 "}


class SteerBackSaysWhatTheRecordDoesNotShowTest(unittest.TestCase):
    def compose(
        self,
        result: str,
        cites: list[str],
        facts: list[dict[str, Any]],
        *,
        lines_judged: bool = True,
        **row: Any,
    ) -> str:
        detail = row.pop("detail", "")
        published = {
            **SID,
            "annotation_goal": "Ship the retry",
            "annotation_revision": 2,
            "annotation_window_start": 50.0,
            "annotation_assessment": {
                "revision_read": 2,
                "window_start": 50.0,
                "read_at": 500.0,
                "criteria": {
                    "claims": {"result": result, "cites": cites, "detail": detail, "why": ""},
                },
            },
            **row,
        }
        for k in range(1, 7):
            published.setdefault(f"annotation_line_{k}", "")
        answer = correction.compose(
            published, facts, floor=50.0, lines_judged=lines_judged, clock=lambda at: f"T{int(at)}"
        )
        return "".join(
            part if isinstance(part, str) else "{" + part["entry"] + "}"
            for part in answer.get("parts", [])
        )

    def test_an_unshown_claim_is_said_in_one_line(self) -> None:
        text = self.compose(reading.RESULT_UNSUPPORTED, ["a1"], [SAID])
        self.assertIn('Can you show evidence for "All tests pass" at T90{a1}?', text)
        self.assertTrue(text.startswith("Back to my goal: Ship the retry"))
        self.assertTrue(text.endswith("Please continue from here."))

    def test_a_contradicted_claim_names_what_shows_otherwise(self) -> None:
        text = self.compose(reading.RESULT_DEPARTURE, ["a1", "c1"], [SAID, FAILED])
        self.assertIn(
            'You said "All tests pass" at T90{a1}; the record shows otherwise at T95{c1}.', text
        )
        self.assertNotIn("A check failed", text)

    def test_a_contradicted_claim_carries_its_explanation(self) -> None:
        # Owner, 2026-10-20: a departure carries the reading's explanation, a claim's included.
        why = "The agent said the tests pass; the check after it failed."
        text = self.compose(reading.RESULT_DEPARTURE, ["a1", "c1"], [SAID, FAILED], detail=why)
        self.assertIn(
            "the record shows otherwise at T95{c1}.\n  Why Compass reads this as drift: " + why,
            text,
        )

    def test_an_unshown_claim_is_a_question_and_carries_no_explanation(self) -> None:
        text = self.compose(
            reading.RESULT_UNSUPPORTED, ["a1"], [SAID], detail="Nothing shows the tests ran."
        )
        self.assertNotIn("Why Compass", text)

    def test_a_shown_claim_adds_nothing_and_alone_is_nothing_to_steer_from(self) -> None:
        self.assertEqual("", self.compose(reading.RESULT_CONSISTENT, ["a1", "c1"], [SAID, PASSED]))

    def test_a_claim_the_record_no_longer_holds_adds_nothing(self) -> None:
        self.assertEqual("", self.compose(reading.RESULT_UNSUPPORTED, ["a1"], []))

    def test_an_unsettled_later_direction_never_holds_a_claim_back(self) -> None:
        # Claims are independent of the intent (review, PR C, reversing the first build).
        later = _person("p2", 120.0, "actually, pause the retry work")
        text = self.compose(reading.RESULT_UNSUPPORTED, ["a1"], [SAID, later])
        self.assertIn('Can you show evidence for "All tests pass" at T90{a1}?', text)
        self.assertNotIn("later direction", text)

    def test_where_no_route_can_carry_checks_no_claim_is_said(self) -> None:
        published = {**SID, "annotation_goal": "Ship the retry", "annotation_revision": 2}
        self.assertEqual(
            "",
            self.compose(
                reading.RESULT_UNSUPPORTED, ["a1"], [SAID], lines_judged=False, **published
            ),
        )

    def test_a_cited_id_cleaned_by_the_ledger_still_finds_its_fact(self) -> None:
        padded = {**SID_AGENT_PADDED}
        text = self.compose(reading.RESULT_UNSUPPORTED, ["a1"], [padded])
        self.assertIn('Can you show evidence for "All tests pass"', text)

    def test_only_the_title_is_quoted_never_the_words(self) -> None:
        text = self.compose(reading.RESULT_UNSUPPORTED, ["a1"], [SAID])
        self.assertNotIn("More words follow the title", text)


class TheClaimsResultsAreTheOrdinaryResultsPlusUnsupportedTest(unittest.TestCase):
    def test_the_claims_result_table_adds_only_unsupported(self) -> None:
        self.assertEqual(
            {
                **{k: v for k, v in reading.RESULT_BY_TOKEN.items() if k != "not_reached"},
                "unsupported": reading.RESULT_UNSUPPORTED,
            },
            reading.CLAIMS_RESULT_BY_TOKEN,
        )
        self.assertEqual(
            {**reading.RESULT_BY_TOKEN, "goal_unclear": reading.RESULT_GOAL_UNCLEAR},
            reading.GOAL_RESULT_BY_TOKEN,
        )
        self.assertEqual(6, len(reading.RESULTS))


class TheScorerKnowsTheQuestionTest(unittest.TestCase):
    def test_unsupported_is_its_own_outcome_and_never_a_departure(self) -> None:
        import sys  # noqa: PLC0415

        sys.path.insert(0, str(SCORER))
        try:
            import score_abstention  # noqa: PLC0415
        finally:
            sys.path.remove(str(SCORER))
        self.assertEqual(reading.RESULT_UNSUPPORTED, score_abstention._UNSUPPORTED)
        self.assertEqual(
            score_abstention.OUTCOME_JUDGED_UNSUPPORTED,
            score_abstention.outcome({"result": reading.RESULT_UNSUPPORTED}, ""),
        )
        self.assertEqual(reading.RESULT_BY_TOKEN, score_abstention.RESULT_BY_TOKEN)


if __name__ == "__main__":
    unittest.main()
