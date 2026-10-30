"""An earlier departure the next reading clears on the agent's word stays listed (owner, 2026-10-30).

The annotation store holds one reading per session and a new one replaces it, so a departure the
reader steered back on vanished the moment the next reading rested that line on what the agent
said. The ruling keeps it: `prior_departures`, beside the reading and never inside it, holds per
Goal or outcome line the newest departure a reading found that the reading after it no longer
finds. [DEC-15b as amended](docs/design-reading-a-session.md) owns the admission, the bounds and
the drop rules these tests hold the store to.

Every message here is placeholder prose.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

from compass_runtime import annotations as annotation_store
from compass_runtime import history, levels, reading, sessions
from compass_runtime.config import build_runtime_config
from compass_runtime.state import build_runtime_state

from .test_sessions import DECLARED_SESSION_FIELDS

if TYPE_CHECKING:
    from collections.abc import Callable

GOAL = "Ship the queue"
LINE_1 = "The queue page lists pending jobs"
LINE_2 = "Leave the stylesheets alone"
FIELD = "prior_departures"


def _row(result: str | None, cites: tuple[str, ...], clause: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"cites": cites, "detail": "", "clause": clause, "why": ""}
    if result is not None:
        row["result"] = result
    row.update(over)
    return row


DEPARTED = _row(
    reading.RESULT_DEPARTURE,
    ("w1",),
    LINE_2,
    detail="A stylesheet was written, which this line rules out.",
    why=reading.WHY_RECORDED_WRITE,
)
ON_THE_AGENTS_WORD = _row(reading.RESULT_CONSISTENT, ("m6",), LINE_2)
GOAL_DEPARTED = _row(reading.RESULT_DEPARTURE, ("w2",), GOAL, detail="It built a different page.")


def _assessment(read_at: float, *, revision: int = 1, **criteria: Any) -> dict[str, Any]:
    rows = {
        "goal": _row(reading.RESULT_UNVERIFIABLE, (), GOAL),
        "line_1": _row(reading.RESULT_UNVERIFIABLE, (), LINE_1),
        "line_2": _row(reading.RESULT_UNVERIFIABLE, (), LINE_2),
        **criteria,
    }
    return {
        "revision_read": revision,
        "read_at": read_at,
        "stamp": "read at 10:00",
        "cutoff": "Read 3 of the 3 entries after your words",
        "scope": reading.SCOPE_MID_FLIGHT,
        "scope_text": reading.SCOPE_TEXT[reading.SCOPE_MID_FLIGHT],
        "ended_at_read": None,
        "criteria": rows,
    }


class _Store(unittest.TestCase):
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
        self.state = build_runtime_state(self.config, started=1.0)
        self.save(lines=[LINE_1, LINE_2], now=10.0)

    def save(self, **kwargs: Any) -> str:
        expected = self.entry()["revisions"][-1]["n"] if self.has_entry() else None
        if "lines" in kwargs and expected is not None:
            kwargs.setdefault("expected_revision", expected)
        return annotation_store.annotate(
            self.config, self.state, "claude", "s1", goal=kwargs.pop("goal", GOAL), **kwargs
        )

    def has_entry(self) -> bool:
        found = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        return found is not None and not annotation_store.is_discarded(found)

    def entry(self) -> Any:
        found = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert found is not None
        return found

    def read(self, read_at: float, **criteria: Any) -> str:
        revision = self.entry()["revisions"][-1]["n"]
        return annotation_store.record_reading(
            self.config,
            self.state,
            "claude",
            "s1",
            assessment=_assessment(read_at, revision=revision, **criteria),  # type: ignore[arg-type]
        )

    def priors(self) -> list[dict[str, Any]]:
        """What a second process reading the file publishes."""
        return list(annotation_store.published(self.entry())[FIELD])

    def keys(self) -> list[tuple[str, float]]:
        return [(item["key"], item["read_at"]) for item in self.priors()]

    def steered(self) -> None:
        """Reading 1 departs on line 2 citing a write; reading 2 rests it on the agent's message."""
        self.read(100.0, line_2=DEPARTED)
        self.read(200.0, line_2=ON_THE_AGENTS_WORD)


class TheReReadingKeepsTheEarlierDepartureTest(_Store):
    def test_a_departure_the_next_reading_no_longer_finds_is_kept_with_its_reading(self) -> None:
        self.read(100.0, line_2=DEPARTED)
        self.assertEqual([], self.priors(), "a departure the standing reading shows is not prior")
        self.read(200.0, line_2=ON_THE_AGENTS_WORD)
        (prior,) = self.priors()
        self.assertEqual("line_2", prior["key"])
        self.assertEqual(100.0, prior["read_at"])
        self.assertEqual(1, prior["revision_read"])
        self.assertEqual(reading.RESULT_DEPARTURE, prior["criterion"]["result"])
        self.assertEqual(("w1",), tuple(prior["criterion"]["cites"]))
        self.assertEqual(DEPARTED["detail"], prior["criterion"]["detail"])
        self.assertEqual(LINE_2, prior["criterion"]["clause"])
        self.assertEqual(reading.WHY_RECORDED_WRITE, prior["criterion"]["why"])

    def test_it_survives_a_restart_and_a_third_reading_that_still_does_not_depart(self) -> None:
        self.steered()
        # A third reading that still rests on the agent's word keeps it.
        self.read(300.0, line_2=ON_THE_AGENTS_WORD)
        self.assertEqual([("line_2", 100.0)], self.keys())
        on_disk = json.loads(Path(annotation_store.store_path(self.config)).read_text("utf-8"))
        entries = on_disk["entries"] if isinstance(on_disk, dict) else on_disk
        self.assertEqual("line_2", entries[0][FIELD][0]["key"])

    def test_a_later_reading_that_departs_there_again_drops_it(self) -> None:
        self.steered()
        self.read(300.0, line_2=DEPARTED)
        self.assertEqual([], self.priors(), "the standing departure card already says it")

    def test_within_a_line_the_newest_departure_wins(self) -> None:
        self.steered()
        self.read(300.0, line_2=DEPARTED)
        self.read(400.0, line_2=ON_THE_AGENTS_WORD)
        self.assertEqual([("line_2", 300.0)], self.keys())

    def test_the_goal_and_each_line_keep_one_each(self) -> None:
        self.read(100.0, goal=GOAL_DEPARTED, line_2=DEPARTED)
        self.read(200.0, line_2=ON_THE_AGENTS_WORD)
        self.assertEqual([("goal", 100.0), ("line_2", 100.0)], self.keys())

    def test_the_claims_question_is_not_kept(self) -> None:
        claims = _row(reading.RESULT_DEPARTURE, ("m1",), "", detail="It claimed a pass.")
        self.read(100.0, claims=claims)
        self.read(200.0)
        self.assertEqual([], self.priors())

    def test_nothing_from_a_reading_the_reader_marked_not_accurate(self) -> None:
        self.read(100.0, line_2=DEPARTED)
        self.assertEqual(
            annotation_store.OUTCOME_STORED,
            annotation_store.mark_not_accurate(
                self.config, self.state, "claude", "s1", read_at=100.0, on=True
            ),
        )
        self.read(200.0, line_2=ON_THE_AGENTS_WORD)
        self.assertEqual([], self.priors(), "the reader disowned the reading that found it")

    def test_a_reading_with_no_time_is_not_a_source(self) -> None:
        # The page names the reading by its time; one it cannot name is not listed.
        revision = self.entry()["revisions"][-1]["n"]
        stored = _assessment(100.0, revision=revision, line_2=DEPARTED)
        stored["read_at"] = None
        annotation_store.record_reading(
            self.config,
            self.state,
            "claude",
            "s1",
            assessment=stored,  # type: ignore[arg-type]
        )
        self.read(200.0, line_2=ON_THE_AGENTS_WORD)
        self.assertEqual([], self.priors())

    def test_a_withheld_press_leaves_it_alone(self) -> None:
        self.steered()
        annotation_store.record_withheld(
            self.config,
            self.state,
            "claude",
            "s1",
            reason=reading.WITHHELD_MODEL_FAILED,
            spent=True,
        )
        self.assertEqual([("line_2", 100.0)], self.keys())


class ItGoesWhenTheWordsItWasAboutGoTest(_Store):
    def test_editing_the_line_drops_it(self) -> None:
        self.steered()
        self.save(lines=[LINE_1, "Leave the stylesheets alone unless the queue needs them"])
        self.assertEqual([], self.priors())

    def test_removing_the_line_drops_it(self) -> None:
        self.steered()
        self.save(lines=[LINE_1])
        self.assertEqual([], self.priors())

    def test_a_save_that_keeps_the_lines_words_keeps_it(self) -> None:
        # A direction appended with Keep mints a revision with the same line 2.
        self.steered()
        self.save(lines=[LINE_1, LINE_2, "The queue page paginates"])
        self.assertEqual([("line_2", 100.0)], self.keys())
        self.assertEqual(2, self.entry()["revisions"][-1]["n"])

    def test_editing_the_goal_drops_the_goals_and_keeps_the_lines(self) -> None:
        self.read(100.0, goal=GOAL_DEPARTED, line_2=DEPARTED)
        self.read(200.0, line_2=ON_THE_AGENTS_WORD)
        self.save(goal="Ship the queue and its tests")
        self.assertEqual([("line_2", 100.0)], self.keys())

    def test_clear_and_discard_take_it_with_the_words(self) -> None:
        self.steered()
        annotation_store.clear(self.config, self.state, "claude", "s1")
        entry = self.entry()
        self.assertNotIn(FIELD, entry)
        self.assertEqual([], annotation_store.published(entry)[FIELD])
        # Words saved again over the discard record start with nothing earlier.
        self.save(lines=[LINE_1, LINE_2], now=500.0)
        self.assertEqual([], self.priors())

    def test_eviction_takes_it_with_the_entry(self) -> None:
        self.steered()
        config = dataclasses.replace(self.config, annotation_max_sessions=1)
        annotation_store.annotate(config, self.state, "claude", "s2", goal="other", now=900.0)
        self.assertIsNone(annotation_store.find(annotation_store.load(config), "claude", "s1"))
        stored = Path(annotation_store.store_path(config)).read_text("utf-8")
        self.assertNotIn(FIELD, stored)


class EverySavePathCarriesItTest(_Store):
    """The data-loss hazard `_carried` exists for: a mutator that rebuilds the entry and forgets
    a field silently discards it, and nothing about the row looks wrong afterwards."""

    def test_each_mutator_that_keeps_the_entry_keeps_it(self) -> None:
        self.steered()
        paths: dict[str, Callable[[], str]] = {
            "settle": lambda: annotation_store.settle(
                self.config, self.state, "claude", "s1", through=250.0, now=260.0
            ),
            "mark not accurate": lambda: annotation_store.mark_not_accurate(
                self.config, self.state, "claude", "s1", read_at=200.0, on=True
            ),
            "remove the mark": lambda: annotation_store.mark_not_accurate(
                self.config, self.state, "claude", "s1", read_at=200.0, on=False
            ),
            "save a new revision": lambda: self.save(
                lines=[LINE_1, LINE_2, "The queue page paginates"], now=270.0
            ),
            "save the same words": lambda: self.save(
                lines=[LINE_1, LINE_2, "The queue page paginates"], now=280.0
            ),
            "save the goal unchanged": lambda: annotation_store.annotate(
                self.config,
                self.state,
                "claude",
                "s1",
                goal=GOAL,
                now=285.0,
            ),
            "withheld press": lambda: annotation_store.record_withheld(
                self.config,
                self.state,
                "claude",
                "s1",
                reason=reading.WITHHELD_TURN_STOP,
                spent=False,
            ),
            "reading that does not depart": lambda: self.read(290.0, line_2=ON_THE_AGENTS_WORD),
        }
        for name, write in paths.items():
            with self.subTest(path=name):
                self.assertIn(
                    write(), (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED)
                )
                self.assertEqual([("line_2", 100.0)], self.keys(), f"{name} dropped it")

    def test_carried_names_every_optional_field_a_mutator_does_not_rebuild(self) -> None:
        # Structural, so a field added to the entry later fails here rather than in a reader's
        # store: every optional key of `Annotation` is either carried or one a mutator sets itself.
        rebuilt = {
            "harness",
            "sid",
            "revisions",
            "refused",
            "refused_raw",
            "discarded",
            "discarded_revision",
            "written",
        }
        source = textwrap.dedent(inspect.getsource(annotation_store._carried))
        # The names the copy loop iterates, and no other string in the function.
        (loop,) = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.For)]
        assert isinstance(loop.iter, ast.Tuple)
        carried = {
            node.value
            for node in loop.iter.elts
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        for name in annotation_store.Annotation.__annotations__:
            if name in rebuilt:
                continue
            with self.subTest(field=name):
                self.assertIn(name, carried)


class ATamperedFileCannotSpeakForTheBoardTest(_Store):
    """Parsed by the reading's own criterion validator, item by item."""

    def rewrite(self, priors: Any) -> None:
        path = Path(annotation_store.store_path(self.config))
        raw = json.loads(path.read_text("utf-8"))
        entries = raw["entries"] if isinstance(raw, dict) else raw
        entries[0][FIELD] = priors
        path.write_text(json.dumps(raw), "utf-8")

    def item(self, **over: Any) -> dict[str, Any]:
        criterion = {**DEPARTED, "cites": list(DEPARTED["cites"]), **over.pop("criterion", {})}
        return {
            "key": "line_2",
            "read_at": 100.0,
            "revision_read": 1,
            "criterion": criterion,
            **over,
        }

    def test_a_well_formed_item_reads_back(self) -> None:
        self.steered()
        self.rewrite([self.item()])
        self.assertEqual([("line_2", 100.0)], self.keys())

    def test_each_bad_item_is_dropped_and_the_rest_stand(self) -> None:
        self.steered()
        bad = [
            self.item(criterion={"why": "a-token-from-the-future"}),
            self.item(criterion={"result": reading.RESULT_CONSISTENT}),
            self.item(criterion={"smuggled": "x"}),
            self.item(key="claims"),
            self.item(key="line_9"),
            self.item(read_at=True),
            self.item(read_at=-1),
            self.item(revision_read=0),
            self.item(revision_read=True),
            self.item(extra="x"),
            "not a mapping",
        ]
        self.rewrite([*bad, self.item(key="goal", criterion={"clause": GOAL})])
        self.assertEqual([("goal", 100.0)], self.keys())

    def test_one_per_line_the_newest_and_seven_at_most(self) -> None:
        self.steered()
        many = [self.item(read_at=float(at)) for at in range(1, 40)]
        self.rewrite(many)
        self.assertEqual([("line_2", 39.0)], self.keys())

    def test_its_prose_is_redacted_and_bounded_on_the_way_in(self) -> None:
        self.steered()
        key = "AKIAIOSFODNN7EXAMPLE"
        long = "word " * 400
        self.rewrite([self.item(criterion={"detail": f"Used {key} \u202e{long}"})])
        (prior,) = self.priors()
        detail = prior["criterion"]["detail"]
        self.assertNotIn(key, detail)
        self.assertNotIn("\u202e", detail)
        self.assertLessEqual(len(detail), self.config.annotation_text_cap_chars + 1)

    def test_words_that_no_longer_match_are_not_read_back(self) -> None:
        self.steered()
        self.rewrite([self.item(criterion={"clause": "Some other words"})])
        self.assertEqual([], self.priors())

    def test_none_beside_no_reading(self) -> None:
        self.steered()
        path = Path(annotation_store.store_path(self.config))
        raw = json.loads(path.read_text("utf-8"))
        entries = raw["entries"] if isinstance(raw, dict) else raw
        del entries[0]["assessment"]
        path.write_text(json.dumps(raw), "utf-8")
        self.assertEqual([], self.priors())

    def test_not_a_list_reads_as_none(self) -> None:
        self.steered()
        for value in ({"line_2": self.item()}, "x", 3, None):
            with self.subTest(value=value):
                self.rewrite(value)
                self.assertEqual([], self.priors())


class PublishedBesideTheReadingAndNowhereElseTest(unittest.TestCase):
    NAME = f"annotation_{FIELD}"

    def test_declared_at_its_absent_value_on_every_row(self) -> None:
        self.assertEqual([], sessions.base_session("claude", "s1", "queue")[self.NAME])
        self.assertIn(self.NAME, DECLARED_SESSION_FIELDS)
        self.assertEqual([], annotation_store.published(None)[FIELD])

    def test_never_admitted_to_session_history(self) -> None:
        self.assertIn(self.NAME, history.PROMPT_DERIVED_CARRIERS)
        self.assertNotIn(self.NAME, history.OBSERVATION_FIELDS)
        self.assertNotIn(self.NAME, history.PROMPT_TEXT_ALLOWLIST)

    def test_it_never_moves_the_drift_level(self) -> None:
        stored = _assessment(200.0, line_2=ON_THE_AGENTS_WORD)
        fact = {
            "fact_id": "m6",
            "type": reading.AGENT_MESSAGE_TYPE,
            "summary": "I kept the stylesheet edit.",
            "at": 150.0,
            "source_session": {"harness": "claude", "sid": "s1"},
        }
        evidence = levels.Evidence((fact,), dict.fromkeys(levels.SCAN_KEYS, 0), 0)
        alone = levels.analysis_level(stored, evidence, outcome_lines=2)
        prior = {"key": "line_2", "read_at": 100.0, "revision_read": 1, "criterion": DEPARTED}
        # The item sits beside the reading, never among its criteria, so nothing the level reads
        # can carry it; a reading handed one anyway is not the shape the level reads.
        beside = levels.analysis_level({**stored, FIELD: [prior]}, evidence, outcome_lines=2)
        self.assertEqual(alone.level, beside.level)
        self.assertNotEqual(levels.MEDIUM, beside.level)


class TwoTurnsOfOneSessionTest(unittest.TestCase):
    """The case the walk found, through the real producer and the store.

    A write outside what line 2 allowed, the reader's pasted correction, and the agent's message
    explaining the edit. The first reading departs on line 2 citing the write; the re-reading rests
    the line on the agent's message. The earlier departure is published on the row.
    """

    START = 1_700_000_000.0

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
        self.state = build_runtime_state(self.config, started=1.0)
        annotation_store.annotate(
            self.config,
            self.state,
            "claude",
            "s1",
            goal=GOAL,
            lines=[LINE_1, LINE_2],
            now=self.START,
        )

    def fact(self, fact_id: str, at: float, **fields: Any) -> dict[str, Any]:
        return {
            "fact_id": fact_id,
            "at": self.START + at,
            "source_session": {"harness": "claude", "sid": "s1"},
            "evidence": {"source": "synthetic placeholder transcript", "confidence": "exact"},
            **fields,
        }

    def produce(self, facts: list[dict[str, Any]], line_2: dict[str, Any], now: float) -> Any:
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        assert entry is not None
        prompts: list[str] = []

        def model(prompt: str, **_kw: Any) -> tuple[str, str]:
            prompts.append(prompt)
            # Cite each fact by the number the prompt gave it.
            numbered = {
                fact_id: number
                for number, fact_id in enumerate(self.listed(prompt, facts), start=1)
            }
            cites = [numbered[fact_id] for fact_id in line_2["cites"]]
            return json.dumps({"line_2": {**line_2, "cites": cites}}), "ok"

        assessment, why, _spent = reading.produce(
            self.config,
            {"harness": "claude", "sid": "s1", "state": "working", "ended_at": None},
            entry["revisions"],
            facts,
            now=self.START + now,
            stamp_text="read",
            model=model,
            tool_output=reading.ToolOutput(destination="Anthropic", label="Claude Code", tails={}),
            read_lines=True,
            read_agent_words=True,
        )
        self.assertEqual("", why, prompts)
        return assessment

    @staticmethod
    def listed(prompt: str, facts: list[dict[str, Any]]) -> list[str]:
        """Each fact in the order its words first appear in the prompt's numbered list."""
        listing = prompt.rsplit("Entries in the observed record:", 1)[-1]

        def words(fact: dict[str, Any]) -> str:
            return str(fact.get("agent_words") or fact.get("reader_words") or fact["summary"])

        found = [(listing.find(words(fact)), fact["fact_id"]) for fact in facts]
        return [fact_id for at, fact_id in sorted(found) if at >= 0]

    def test_the_earlier_departure_is_published_beside_the_re_reading(self) -> None:
        # A recorded write carries a departure only under a folder rule, and that rule would
        # settle the second reading the same way, so the first departure rests on what the agent
        # reported doing: the edit, as the agent said it, which a departure may cite.
        write = self.fact(
            "w1",
            60.0,
            type="tool_report",
            subject="write",
            result="",
            result_source="",
            summary="src/styles/queue.css",
            branch={"harness": "claude", "sid": "s1", "record_id": "call-1"},
        )
        reported = self.fact(
            "m1",
            65.0,
            type=reading.AGENT_MESSAGE_TYPE,
            summary="I also restyled the queue table in src/styles/queue.css.",
            agent_words="I also restyled the queue table in src/styles/queue.css.",
        )
        first = self.produce(
            [write, reported],
            {"result": "departure", "cites": ["m1"], "detail": "A stylesheet was edited."},
            now=100.0,
        )
        self.assertEqual(reading.RESULT_DEPARTURE, first["criteria"]["line_2"]["result"])
        with mock.patch("time.time", return_value=self.START + 101.0):
            annotation_store.record_reading(
                self.config, self.state, "claude", "s1", assessment=first
            )

        pasted = self.fact(
            "p1",
            105.0,
            type="user_message",
            by="person:me",
            summary="Back to my goal: leave the stylesheets alone.",
            reader_words="Back to my goal: Ship the queue, and leave the stylesheets alone.",
        )
        explained = self.fact(
            "m6",
            110.0,
            type=reading.AGENT_MESSAGE_TYPE,
            summary="The stylesheet edit was needed for the queue page.",
            agent_words="The stylesheet edit was needed for the queue page, so I kept it.",
        )
        second = self.produce(
            [write, reported, pasted, explained],
            {"result": "consistent", "cites": ["m6"], "detail": ""},
            now=120.0,
        )
        self.assertEqual(reading.RESULT_CONSISTENT, second["criteria"]["line_2"]["result"])
        self.assertEqual(("m6",), tuple(second["criteria"]["line_2"]["cites"]))
        with mock.patch("time.time", return_value=self.START + 121.0):
            annotation_store.record_reading(
                self.config, self.state, "claude", "s1", assessment=second
            )

        row = sessions.base_session("claude", "s1", "queue")
        entry = annotation_store.find(annotation_store.load(self.config), "claude", "s1")
        for name, value in annotation_store.published(entry).items():
            row[f"annotation_{name}"] = value
        (prior,) = row[f"annotation_{FIELD}"]
        self.assertEqual("line_2", prior["key"])
        self.assertEqual(self.START + 100.0, prior["read_at"])
        self.assertEqual(LINE_2, prior["criterion"]["clause"])
        self.assertEqual(("m1",), tuple(prior["criterion"]["cites"]))
        self.assertEqual(reading.RESULT_DEPARTURE, prior["criterion"]["result"])
        self.assertEqual("A stylesheet was edited.", prior["criterion"]["detail"])
        # The standing reading is the second one, and it departs nowhere.
        self.assertEqual(self.START + 120.0, row["annotation_assessment"]["read_at"])


if __name__ == "__main__":
    unittest.main()
