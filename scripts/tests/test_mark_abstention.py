"""What the marking tool must not do to somebody's evening.

Every test here is a defect that shipped. Two versions of this tool reached the
repository owner and both wasted his time, so these are written against the
measured failures rather than against the happy path.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

if TYPE_CHECKING:
    from collections.abc import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abstention_ledger
import mark_abstention

_LEDGER_PATCH: Any = None


def _never(stem: str) -> tuple[str, ...]:
    """Every continuation generation, at a throwaway path no test writes."""
    folder = tempfile.mkdtemp()
    return tuple(str(Path(folder, f"{stem}-{k}.json")) for k in range(abstention_ledger.MAX_GRANTS))


def setUpModule() -> None:
    """Never the real spend ledger: the marker refuses to write once it holds a call."""
    global _LEDGER_PATCH  # noqa: PLW0603
    _LEDGER_PATCH = mock.patch.multiple(
        abstention_ledger,
        LEDGER_PATH=str(Path(tempfile.mkdtemp(), "never-real.json")),
        CLAUDE_SUMMARY_PATH=str(Path(tempfile.mkdtemp(), "never-committed.json")),
        CONTINUATION_PATHS=_never("never-continuation"),
        CONTINUATION_SUMMARY_PATHS=_never("never-continuation-result"),
    )
    _LEDGER_PATCH.start()


def tearDownModule() -> None:
    _LEDGER_PATCH.stop()


def _collect(sink: list[str]) -> Callable[..., None]:
    """A stand-in for print that keeps what was said."""

    def record(*args: Any, **_kwargs: Any) -> None:
        sink.append(" ".join(map(str, args)))

    return record


class CaseIdentityTest(unittest.TestCase):
    """v2 hashed the row's position in the board's session list.

    The board reorders on every state change, so a rebuild re-attached answers
    to different sessions. Measured on the real corpus: four of six ids
    collided with an unrelated session after a single shift.
    """

    def test_the_id_survives_a_reorder(self) -> None:
        first = mark_abstention._case_id("claude", "1b7958bc")
        again = mark_abstention._case_id("claude", "1b7958bc")
        self.assertEqual(first, again)

    def test_two_sessions_never_share_an_id(self) -> None:
        a = mark_abstention._case_id("claude", "1b7958bc")
        b = mark_abstention._case_id("claude", "09f68b92")
        self.assertNotEqual(a, b)

    def test_the_same_sid_on_two_harnesses_is_two_cases(self) -> None:
        self.assertNotEqual(
            mark_abstention._case_id("claude", "abc123"),
            mark_abstention._case_id("codex", "abc123"),
        )

    def test_the_id_carries_no_readable_session_identity(self) -> None:
        # The marks file is the half that gets committed.
        marked = mark_abstention._case_id("claude", "1b7958bc")
        self.assertNotIn("1b7958bc", marked)
        self.assertNotIn("claude", marked)


class FrozenMarksTest(unittest.TestCase):
    def test_minimal_replay_asks_against_both_yardsticks_on_a_work_harness(self) -> None:
        case = {
            "id": "abcd1234abcd1234",
            "harness": "pi",
            "sid": "s1",
            "row_snapshot": {"harness": "pi", "sid": "s1", "state": "working"},
            "producer_facts": [
                {
                    "fact_id": "w1",
                    "type": "work_result",
                    "summary": "wrote out.csv",
                    "at": 90.0,
                    "evidence": {"source": "record", "confidence": "exact"},
                    "source_session": {"harness": "pi", "sid": "s1"},
                }
            ],
        }
        body = {"v": 4, "goal": "FROZEN GOAL", "output": "FROZEN OUTPUT", "cases": [case]}
        with tempfile.TemporaryDirectory() as folder:
            cases = Path(folder, "cases.json")
            marks = Path(folder, "marks.json")
            cases.write_text(json.dumps(body))
            with (
                mock.patch.object(mark_abstention, "CASES_PATH", str(cases)),
                mock.patch.object(mark_abstention, "MARKS_PATH", str(marks)),
                mock.patch.object(mark_abstention, "_ask", side_effect=["judge", "judge"]) as ask,
                mock.patch("builtins.print"),
            ):
                self.assertEqual(0, mark_abstention.mark())
            self.assertEqual(2, ask.call_count)
            self.assertIn("FROZEN GOAL", ask.call_args_list[0].args[0])
            self.assertIn("FROZEN OUTPUT", ask.call_args_list[1].args[0])
            self.assertEqual("judge", json.loads(marks.read_text())["marks"][case["id"]]["output"])

    def test_a_mark_is_bound_to_the_packet_and_the_actual_ledger_is_shown(self) -> None:
        case = {
            "id": "abcd1234abcd1234",
            "harness": "codex",
            "sid": "s1",
            "end_shape": "still running",
            "citable": 1,
            "reached": True,
            "work_results": 0,
            "producer_facts": [
                {
                    "fact_id": "f1",
                    "type": "user_message",
                    "summary": "ACTUAL FROZEN FACT",
                    "evidence": {"source": "transcript", "confidence": "exact"},
                    "source_session": {"harness": "codex", "sid": "s1"},
                    "at": 90.0,
                }
            ],
        }
        body = {"v": 4, "goal": "FROZEN GOAL", "output": "FROZEN OUTPUT", "cases": [case]}
        printed: list[str] = []
        with tempfile.TemporaryDirectory() as folder:
            cases = Path(folder, "cases.json")
            marks = Path(folder, "marks.json")
            cases.write_text(json.dumps(body))
            with (
                mock.patch.object(mark_abstention, "CASES_PATH", str(cases)),
                mock.patch.object(mark_abstention, "MARKS_PATH", str(marks)),
                mock.patch.object(mark_abstention, "_ask", return_value="abstain") as ask,
                mock.patch("builtins.print", side_effect=_collect(printed)),
            ):
                self.assertEqual(0, mark_abstention.mark())
                saved = marks.read_bytes()
                self.assertEqual(
                    mark_abstention.cases_digest(body), json.loads(saved)["cases_digest"]
                )
                self.assertEqual(1, ask.call_count)
                # The same identities with changed evidence must not inherit the key.
                body["goal"] = "CHANGED GOAL"
                cases.write_text(json.dumps(body))
                self.assertEqual(1, mark_abstention.mark())
                self.assertEqual(saved, marks.read_bytes())
                self.assertEqual(1, ask.call_count)
        for text in ("ACTUAL FROZEN FACT", "FROZEN GOAL", "FROZEN OUTPUT"):
            self.assertIn(text, "\n".join(printed))


class EndShapeTest(unittest.TestCase):
    """The three ways a session stops, which a reading treats differently."""

    def test_an_observed_end_wins_over_everything(self) -> None:
        row = {"ended_at": 1.0, "state": "working", "finished_at": 2.0}
        self.assertEqual("session end observed", mark_abstention._end_shape(row))

    def test_a_working_row_is_running_even_with_a_stale_turn_stop(self) -> None:
        # The producer reads it that way, and a display that said "this stopped"
        # above "now working" invited exactly the wrong mark.
        row = {"ended_at": None, "state": "working", "finished_at": 2.0}
        self.assertEqual("still running", mark_abstention._end_shape(row))

    def test_quiet_with_no_end_is_not_an_end(self) -> None:
        row = {"ended_at": None, "state": "idle", "finished_at": None}
        self.assertEqual("went quiet, no end observed", mark_abstention._end_shape(row))


class TheOutputQuestionIsNotAskedWhereTheRulingFixesItTest(unittest.TestCase):
    """Half of v2's prompts asked the marker to transcribe a constant.

    The Expected Output constraint is only put to the model on a harness that
    publishes a demonstrated work result. Asking about a Claude session is not a
    question, and the unanimity guard then punished the correct answer.
    """

    def test_only_a_case_whose_frozen_ledger_shows_work_is_asked(self) -> None:
        def case(harness: str, fact_type: str) -> dict[str, Any]:
            fact = {
                "fact_id": "f1",
                "type": fact_type,
                "subject": "check",
                "result": "passed",
                "summary": "wrote out.csv",
                "at": 90.0,
                "evidence": {"source": "record", "confidence": "exact"},
                "source_session": {"harness": harness, "sid": "s1"},
            }
            return {"harness": harness, "sid": "s1", "producer_facts": [fact]}

        body = {"v": 4, "output": "a CSV"}
        self.assertTrue(mark_abstention._mark_asks_output(body, case("pi", "work_result")))
        self.assertFalse(mark_abstention._mark_asks_output(body, case("pi", "user_message")))
        # This tool never grants tool output, so a Claude Code check is not read.
        self.assertFalse(mark_abstention._mark_asks_output(body, case("claude", "tool_report")))

    def test_the_guard_ignores_a_column_the_corpus_cannot_vary(self) -> None:
        cases = [{"id": f"c{i}", "asks_output": False} for i in range(10)]
        entries = {f"c{i}": {"goal": "judge", "output": "abstain"} for i in range(10)}
        printed: list[str] = []
        with mock.patch("builtins.print", _collect(printed)):
            mark_abstention._warn_if_unanimous(entries, cases)
        joined = "\n".join(printed)
        self.assertIn("on goal", joined)
        self.assertNotIn("on output", joined)

    def test_the_guard_does_not_fire_on_a_handful_of_marks(self) -> None:
        cases = [{"id": "c1", "asks_output": True}, {"id": "c2", "asks_output": True}]
        entries = {k: {"goal": "judge", "output": "judge"} for k in ("c1", "c2")}
        printed: list[str] = []
        with mock.patch("builtins.print", _collect(printed)):
            mark_abstention._warn_if_unanimous(entries, cases)
        self.assertEqual([], printed)


class ReadingAFileAPersonCanBreakTest(unittest.TestCase):
    """v2 raised a traceback on four ordinary file states.

    The network path was careful and the disk path, which holds the artefact,
    was not.
    """

    def _in_temp(self, body: str) -> str:
        handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - must outlive this call
            "w", suffix=".json", delete=False
        )
        handle.write(body)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_a_truncated_file_is_a_message_not_a_traceback(self) -> None:
        with mock.patch("builtins.print"):
            self.assertEqual({}, mark_abstention._load(self._in_temp("{not json")))

    def test_a_json_list_is_refused_rather_than_coerced(self) -> None:
        with mock.patch("builtins.print"):
            self.assertEqual({}, mark_abstention._load(self._in_temp("[1, 2, 3]")))

    def test_an_absent_file_is_simply_empty(self) -> None:
        self.assertEqual({}, mark_abstention._load("/nonexistent/nowhere.json"))

    def test_a_half_written_mark_is_not_a_mark(self) -> None:
        body = {"marks": {"a": {"goal": "judge", "output": "abstain"}, "b": {"goal": "judge"}}}
        self.assertEqual({"a"}, set(mark_abstention._marks(body)))

    def test_marks_that_are_not_a_mapping_are_dropped(self) -> None:
        self.assertEqual({}, mark_abstention._marks({"marks": ["judge"]}))


class WritingIsAtomicTest(unittest.TestCase):
    """v2 truncated in place, so an interrupt lost every mark already given."""

    def test_the_temp_file_is_gone_and_the_mode_is_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "nested", "marks.json")
            mark_abstention._write(path, {"v": 2, "marks": {}})
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(f"{path}.tmp"))
            if os.name != "nt":
                self.assertEqual(0o600, os.stat(path).st_mode & 0o777)

    def test_a_rewrite_replaces_rather_than_appends(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "marks.json")
            mark_abstention._write(path, {"marks": {"a": 1}})
            mark_abstention._write(path, {"marks": {"b": 2}})
            with open(path, encoding="utf-8") as handle:
                self.assertEqual({"b": 2}, json.load(handle)["marks"])


class BuildRefusesToProduceAKeyThatVerifiesNothingTest(unittest.TestCase):
    """v2 reported success three times in a row over an empty corpus."""

    def _build(self, payload: Any, *, marks: dict[str, Any] | None = None) -> tuple[int, str]:
        printed: list[str] = []
        with (
            tempfile.TemporaryDirectory() as root,
            mock.patch.object(mark_abstention, "CASES_PATH", os.path.join(root, "cases.json")),
            mock.patch.object(mark_abstention, "MARKS_PATH", os.path.join(root, "marks.json")),
            mock.patch.object(mark_abstention, "_get", lambda *_a, **_k: payload),
            mock.patch("builtins.print", _collect(printed)),
        ):
            if marks:
                mark_abstention._write(os.path.join(root, "marks.json"), {"marks": marks})
            code = mark_abstention.build(4553)
            wrote = os.path.exists(os.path.join(root, "cases.json"))
        self.assertFalse(wrote and code != 0, "a failed build must write nothing")
        return code, "\n".join(printed)

    def test_an_empty_board_writes_nothing_and_fails(self) -> None:
        code, said = self._build({"sessions": []})
        self.assertEqual(1, code)
        self.assertIn("no sessions", said)

    def test_a_rebuild_that_would_orphan_marks_refuses(self) -> None:
        payload = {"sessions": [{"harness": "claude", "sid": "aaa", "project": "p"}]}
        stale = {"deadbeefdeadbeef": {"goal": "judge", "output": "abstain"}}
        code, said = self._build(payload, marks=stale)
        self.assertEqual(1, code)
        self.assertIn("--force", said)


class ADegenerateCorpusIsCalledOutTest(unittest.TestCase):
    """One case differing from twenty is not variation.

    The first version of this check asked only whether the count was non-zero,
    which a 21 case corpus with a single evidence bearing case passed while
    still being twenty near identical screens.
    """

    def _build(self, rows: list[dict[str, Any]], facts: int) -> str:
        printed: list[str] = []
        with (
            tempfile.TemporaryDirectory() as root,
            mock.patch.object(mark_abstention, "CASES_PATH", os.path.join(root, "cases.json")),
            mock.patch.object(mark_abstention, "MARKS_PATH", os.path.join(root, "marks.json")),
            mock.patch.object(mark_abstention, "_get", lambda *_a, **_k: {"sessions": rows}),
            mock.patch.object(
                mark_abstention,
                "_ledger",
                lambda _p, case: {
                    "facts": facts if case["sid"] == "s0" else 0,
                    "citable": facts if case["sid"] == "s0" else 0,
                    "work_results": 0,
                    "reached": True,
                },
            ),
            mock.patch("builtins.print", _collect(printed)),
        ):
            mark_abstention.build(4553)
        return "\n".join(printed)

    def test_one_case_in_twenty_is_still_called_thin(self) -> None:
        # Two end shapes on purpose, so the shapes branch of the warning cannot
        # fire and only the proportion of evidence bearing cases is under test.
        # Without this the assertion passes against a guard that merely checks
        # the count is non-zero, which is the defect being fixed.
        rows: list[dict[str, Any]] = [
            {"harness": "claude", "sid": f"s{i}", "project": "p", "state": "idle", "ended_at": 1}
            for i in range(21)
        ]
        rows[0] = {"harness": "claude", "sid": "s0", "project": "p", "state": "working"}
        said = self._build(rows, facts=13)
        self.assertIn("does not vary", said)


class TheEvidenceCountIsTheOneTheProducerWouldReadTest(unittest.TestCase):
    """The screen answers "does that ledger hold anything citable" or nothing.

    v3 counted a fact citable on `type` and `summary`, and scoped the list with
    `fact["sid"]` -- a key `project_context` does not write, so the filter
    admitted everything the endpoint returned. The producer needs a named
    evidence source as well and scopes on `source_session`, and the shape with
    a confidence and no source is one `reading.build_ledger`'s own comment
    records seeing. A marker told "1 citable fact" marks a session the producer
    then refuses before the model, and that pair counts for neither side.
    """

    SESSION: ClassVar[dict[str, str]] = {"harness": "claude", "sid": "s1"}

    def _count(self, facts: list[dict[str, Any]]) -> dict[str, Any]:
        with mock.patch.object(
            mark_abstention, "_get", lambda *_a, **_k: {"semantic": {"facts": facts}}
        ):
            return mark_abstention._ledger(4553, {"project_key": "p", **self.SESSION})

    @staticmethod
    def _fact(**over: Any) -> dict[str, Any]:
        fact: dict[str, Any] = {
            "fact_id": "f1",
            "type": "user_message",
            "summary": "did the thing",
            "evidence": {"source": "transcript", "confidence": "exact"},
            "source_session": dict(TheEvidenceCountIsTheOneTheProducerWouldReadTest.SESSION),
        }
        fact.update(over)
        return fact

    def test_a_fact_the_resolver_could_cite_is_counted(self) -> None:
        self.assertEqual(1, self._count([self._fact()])["citable"])

    def test_a_confidence_with_no_named_source_is_not_citable(self) -> None:
        thin = self._fact(evidence={"confidence": "low"})
        self.assertEqual(0, self._count([thin])["citable"])

    def test_another_sessions_fact_is_not_this_sessions_evidence(self) -> None:
        theirs = self._fact(source_session={"harness": "claude", "sid": "s2"})
        self.assertEqual(0, self._count([theirs])["citable"])

    def test_the_count_is_whatever_the_producer_would_read(self) -> None:
        # The binding assertion: the two rules are the same rule, so a change
        # to either side has to move both. Without it the three cases above
        # can be satisfied by a second copy of the producer's rule that then
        # drifts from it.
        reading = mark_abstention._reading()
        facts = [
            self._fact(),
            self._fact(fact_id="f2", evidence={"confidence": "low"}),
            self._fact(fact_id="f3", source_session={"harness": "claude", "sid": "s2"}),
            self._fact(fact_id="f4", type="work_result"),
        ]
        entries = reading.build_ledger(facts, self.SESSION["harness"], self.SESSION["sid"])
        wanted = sum(1 for entry in entries if reading._citable(entry))
        self.assertEqual(wanted, self._count(facts)["citable"])
        self.assertEqual(2, wanted)

    def test_a_work_result_is_counted_only_while_it_stays_citable(self) -> None:
        # The OUTPUT question turns on this number, and a thin work_result is
        # no more citable than a thin user_message.
        # A work result is work on Pi, the harness that publishes one.
        pi = {"harness": "pi", "sid": "s1"}
        thin = self._fact(type="work_result", evidence={"confidence": "low"}, source_session=pi)
        work = self._fact(type="work_result", source_session=pi)
        with mock.patch.object(self, "SESSION", pi):
            self.assertEqual(0, self._count([thin])["work_results"])
            self.assertEqual(1, self._count([work])["work_results"])
        # On Claude Code the same type is not work: its work is a tool report.
        self.assertEqual(0, self._count([self._fact(type="work_result")])["work_results"])


class TheDocstringDoesNotClaimWhatTheCodeLacksTest(unittest.TestCase):
    """This repository's recorded failure mode is a comment that is not so."""

    SOURCE = mark_abstention.__doc__ or ""

    def test_it_does_not_still_claim_the_history_store(self) -> None:
        # v1's source, repudiated by v2's build and left in the module header.
        self.assertNotIn("from the local history store", self.SOURCE)

    def test_the_scorer_contract_is_written_down(self) -> None:
        # A producer handed a session with no stored revision refuses it before
        # reading any evidence, so how a case gets scored cannot be left out.
        self.assertIn("nothing-typed", self.SOURCE)

    def test_no_dead_module_state_survived_the_rewrite(self) -> None:
        for gone in ("HISTORY_PATH", "_entries"):
            self.assertFalse(hasattr(mark_abstention, gone), f"{gone} is dead and still here")


def _built(case_id: str, **fields: Any) -> dict[str, Any]:
    """A case as `--build` writes one, format 3."""
    return {
        "id": case_id,
        "harness": "codex",
        "sid": "s1",
        "end_shape": "still running",
        "facts": 0,
        "citable": 0,
        "work_results": 0,
        "reached": True,
        "asks_output": False,
        **fields,
    }


class _Home(unittest.TestCase):
    """A packet in a home that `~` stands for, and a way to run either mode against it."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        folder = self.home / ".compass" / "abstention-claude-2026-09-27"
        folder.mkdir(parents=True)
        self.cases = folder / "abstention-cases.json"
        self.marks = folder / "abstention-marks.json"

    def run_mode(
        self, body: dict[str, Any], mode: Callable[[], int], *, default_home: bool = False
    ) -> tuple[int, list[str], Any]:
        self.cases.write_text(json.dumps(body))
        printed: list[str] = []
        with (
            mock.patch.object(abstention_ledger, "real_home", return_value=str(self.home)),
            mock.patch.object(mark_abstention, "CASES_PATH", str(self.cases)),
            mock.patch.object(mark_abstention, "MARKS_PATH", str(self.marks)),
            mock.patch.object(mark_abstention, "DEFAULT_HOME", default_home),
            mock.patch.object(mark_abstention, "_ask", return_value=None) as ask,
            mock.patch("builtins.print", side_effect=_collect(printed)),
        ):
            code = mode()
        return code, printed, ask


class ThePacketReadIsNamedFirstTest(_Home):
    """The owner posted a 23 case report from the default home as his marks for a 13 case packet."""

    WANT = "Packet: ~/.compass/abstention-claude-2026-09-27/abstention-cases.json (2 cases)"

    def body(self) -> dict[str, Any]:
        return {"v": 3, "cases": [_built("a" * 16), _built("b" * 16, sid="s2")]}

    def test_the_report_names_the_packet_on_its_first_line(self) -> None:
        code, printed, _ask = self.run_mode(self.body(), mark_abstention.report)
        self.assertEqual(0, code)
        self.assertEqual(self.WANT, printed[0])
        self.assertNotIn("COMPASS_HOME", "\n".join(printed))

    def test_marking_names_the_packet_on_its_first_line(self) -> None:
        _code, printed, _ask = self.run_mode(self.body(), mark_abstention.mark)
        self.assertEqual(self.WANT, printed[0])

    def test_the_default_home_is_called_out_when_compass_home_is_unset(self) -> None:
        for mode in (mark_abstention.report, mark_abstention.mark):
            with self.subTest(mode=mode.__name__):
                _code, printed, _ask = self.run_mode(self.body(), mode, default_home=True)
                self.assertEqual(self.WANT, printed[0])
                self.assertIn("COMPASS_HOME is not set", printed[1])
                self.assertIn("default home", printed[1])

    def test_the_default_home_follows_the_environment_at_import(self) -> None:
        self.assertEqual(not os.environ.get("COMPASS_HOME"), mark_abstention.DEFAULT_HOME)


class AMismatchedPacketIsRefusedBeforeItIsShownTest(_Home):
    """A checkout 24 commits behind died on `KeyError: 'end_shape'` at `_show`."""

    def assert_refused(self, body: dict[str, Any], *named: str) -> None:
        for mode in (mark_abstention.mark, mark_abstention.report):
            with self.subTest(mode=mode.__name__):
                code, printed, ask = self.run_mode(body, mode)
                said = "\n".join(printed)
                self.assertEqual(1, code, said)
                self.assertEqual(0, ask.call_count)
                self.assertTrue(printed[0].startswith("Packet: ~/.compass/"), printed[0])
                self.assertIn("frozen by a different version of these scripts", said)
                self.assertIn("git pull", said)
                self.assertNotIn("=" * 72, said)
                self.assertFalse(self.marks.exists())
                for word in named:
                    self.assertIn(word, said)

    def test_a_built_case_without_its_end_shape_is_refused(self) -> None:
        case = _built("a" * 16)
        del case["end_shape"]
        self.assert_refused({"v": 3, "cases": [case]}, "end_shape", "a" * 16)

    def test_a_format_this_version_does_not_know_is_refused(self) -> None:
        self.assert_refused({"v": 7, "cases": [_built("a" * 16)]}, "format 7")

    def test_a_packet_with_no_format_is_refused(self) -> None:
        self.assert_refused({"cases": [_built("a" * 16)]}, "no case format")

    def test_a_frozen_claude_case_without_its_parser_stamp_is_refused(self) -> None:
        case = {
            "id": "a" * 16,
            "harness": "claude",
            "sid": "s1",
            "origin": "recorded",
            "captured_at": 110.0,
            "row_snapshot": {"harness": "claude", "sid": "s1", "state": "working"},
            "intent": {"goal": "g", "lines": [{"text": "t"}]},
            "producer_facts": [],
            "unconfirmed": [],
            "tool_output": {"tails": {}, "changed_after": []},
        }
        self.assert_refused({"v": 5, "cases": [case]}, "transcript_bytes", "parser")

    def test_a_case_that_is_not_an_object_is_refused(self) -> None:
        self.assert_refused({"v": 3, "cases": [_built("a" * 16), "b"]}, "case 2")

    def test_a_whole_packet_is_still_marked(self) -> None:
        code, _printed, ask = self.run_mode(
            {"v": 3, "cases": [_built("a" * 16)]}, mark_abstention.mark
        )
        self.assertEqual(0, code)
        self.assertEqual(1, ask.call_count)

    def test_the_screen_itself_never_indexes_an_optional_field(self) -> None:
        printed: list[str] = []
        with mock.patch("builtins.print", side_effect=_collect(printed)):
            mark_abstention._show({}, "1/1")
            mark_abstention._show({"reached": True, "citable": 2}, "1/1")
        self.assertIn("2 citable facts, 0 of them showing work done", "\n".join(printed))


if __name__ == "__main__":
    unittest.main()


class IncompleteFrozenCheckTest(unittest.TestCase):
    def test_the_frozen_pair_withholds_a_consistent_without_claiming_a_change(self) -> None:
        case = {
            "harness": "claude",
            "sid": "s1",
            "tool_output": {
                "tails": {},
                "changed_after": [],
                "read_incomplete": [["call-1", "pytest"]],
            },
            "producer_facts": [
                {
                    "fact_id": "c1",
                    "type": "tool_report",
                    "subject": "check",
                    "summary": "pytest",
                    "result": "passed",
                    "result_source": "flag",
                    "at": 95.0,
                    "branch": {"record_id": "call-1"},
                    "source_session": {"harness": "claude", "sid": "s1"},
                    "evidence": {
                        "source": "Claude Bash call and paired result",
                        "confidence": "exact",
                    },
                }
            ],
        }
        (entry,) = mark_abstention.case_ledger({"v": 5}, case)
        reading = mark_abstention._reading()
        self.assertFalse(reading.check_supports(entry, reading.RESULT_CONSISTENT, 50.0))
        self.assertIs(False, entry["changed_after"])
        self.assertIs(True, entry.get("read_incomplete"))
        self.assertIn("work record was not read", entry["summary"])


class APersonsQualificationCoversCompassTurnDetectionTest(unittest.TestCase):
    def test_a_person_cannot_reuse_a_parser_stamp_after_the_compass_turn_guard_changes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder, "compass_runtime")
            runtime.mkdir()
            source = Path(mark_abstention._SKILL, "compass_runtime")
            for name in {*mark_abstention._PARSER_FILES, "compass_turns.py"}:
                (runtime / name).write_bytes((source / name).read_bytes())
            with mock.patch.object(mark_abstention, "_SKILL", folder):
                before = mark_abstention.parser_digest()
                guard = runtime / "compass_turns.py"
                text = guard.read_text()
                changed = text.replace("start <= at", "start < at")
                self.assertNotEqual(text, changed)
                guard.write_text(changed)
                self.assertNotEqual(before, mark_abstention.parser_digest())


class CodexPacketSourceTest(unittest.TestCase):
    """A person's permission cannot substitute for independently recorded sources."""

    def setUp(self) -> None:
        if TYPE_CHECKING:
            from tests import codex_source_support as support  # noqa: PLC0415
        else:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            import codex_source_support as support  # noqa: PLC0415

        self.support = support
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / "codex/sessions"
        self.path = support.rollout(self.root)
        self.config = support.config(self.home)
        self.entry = support.entry(self.root, self.path)

    def freeze(self) -> dict[str, Any]:
        return mark_abstention.freeze_case(
            self.config, self.entry, [], observations=(), ends=(), production_reading=True
        )

    def reasons(self, case: dict[str, Any]) -> list[str]:
        return mark_abstention.provenance(
            case,
            observations=(),
            ends=(),
            index={self.support.SID: str(self.path)},
            config=self.config,
        )

    def test_a_person_can_freeze_and_revalidate_without_a_dashboard_or_model(self) -> None:
        case = self.freeze()
        self.assertEqual(case["origin"], "recorded")
        self.assertEqual(self.reasons(case), [])
        self.assertEqual(case["intent"]["n"], 3)
        self.assertEqual(case["lifecycle_from"], "codex-transcript")
        self.assertEqual(len(case["production_reading"]["prompt_digest"]), 64)
        self.assertEqual(mark_abstention.packet_mismatch({"v": 6, "cases": [case]}), "")
        self.assertTrue(mark_abstention.is_intent_packet({"v": 6}))
        self.assertTrue(mark_abstention.case_checks({"v": 6}, case)[0])

    def test_a_person_can_append_later_work_without_rewriting_the_frozen_past(self) -> None:
        case = self.freeze()
        with self.path.open("a") as f:
            f.write(json.dumps(self.support.command(40, 1)) + "\n")
        self.assertEqual(self.reasons(case), [])

    def test_a_person_cannot_substitute_identity_or_mutate_or_truncate_the_prefix(self) -> None:
        case = self.freeze()
        original = self.path.read_bytes()
        for changed in (
            original.replace(self.support.SID.encode(), self.support.CHILD.encode()),
            original.replace(b"Please repair", b"Please ignore"),
            original[:100],
        ):
            with self.subTest(change=len(changed)):
                self.path.write_bytes(changed)
                self.assertTrue(self.reasons(case))
                self.path.write_bytes(original)

    def test_a_person_cannot_drop_checks_messages_or_change_the_saved_intent(self) -> None:
        case = self.freeze()
        import copy  # noqa: PLC0415

        for field in (
            "producer_facts",
            "tool_output",
            "intent",
            "row_snapshot",
            "sources",
            "parser",
            "production_reading",
        ):
            changed = copy.deepcopy(case)
            if field == "parser":
                changed[field] = "stale"
            elif field == "producer_facts":
                changed[field] = changed[field][1:]
            else:
                changed[field] = {}
            with self.subTest(field=field):
                self.assertTrue(self.reasons(changed))

    def test_a_person_cannot_omit_a_child_or_its_failure(self) -> None:
        child = self.support.rollout(self.root, sid=self.support.CHILD, parent=self.support.SID)
        with self.assertRaisesRegex(mark_abstention.FreezeError, "children"):
            self.freeze()
        self.entry["children"] = [str(child)]
        case = self.freeze()
        self.assertEqual(len(case["sources"]["children"]), 1)
        self.assertEqual(self.reasons(case), [])
        child.write_text(child.read_text().replace('"exit_code": 1', '"exit_code": 0'))
        self.assertTrue(self.reasons(case))

    def test_a_person_sees_why_an_older_message_could_not_be_attributed(self) -> None:
        row = self.support.message(
            "<codex_internal_context>injected</codex_internal_context>", tagged=False, delta=2
        )
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows.insert(3, row)
        self.support.write(self.path, rows)
        case = self.freeze()
        self.assertEqual(case["message_refusals"][0]["reason"], "person-authorship-unconfirmed")
        self.assertNotIn("injected", json.dumps(case))
        self.assertEqual(self.reasons(case), [])

    def test_a_person_cannot_vouch_a_source_outside_the_selected_native_store(self) -> None:
        self.entry["sessions_root"] = str(self.home / "elsewhere")
        with self.assertRaisesRegex(mark_abstention.FreezeError, "source"):
            self.freeze()

    def test_a_person_gets_the_actual_selected_prompt_and_refuses_a_changed_selection(self) -> None:
        case = self.freeze()
        rows = mark_abstention.case_ledger({"v": 6}, case)
        wanted = [row for row in rows if row["type"] == "user_message"]
        lookup = mark_abstention.native_case_person_lookup(
            case, config=self.config, index={self.support.SID: str(self.path)}
        )
        assert lookup is not None
        self.assertTrue(lookup(wanted))
        with self.assertRaisesRegex(mark_abstention.FreezeError, "selection"):
            lookup([])

    def test_a_person_cannot_use_codex_as_a_reviewed_claude_export(self) -> None:
        case = self.freeze()
        case["reviewed_export"] = {}
        self.assertIn("codex-export-unsupported", self.reasons(case))

    def test_a_person_can_run_the_offline_command_with_only_explicit_temporary_sources(
        self,
    ) -> None:
        spec = self.home / "spec.json"
        spec.write_text(json.dumps({"cases": [self.entry]}))
        packet = self.home / "packet/cases.json"
        with (
            mock.patch.object(mark_abstention, "CASES_PATH", str(packet)),
            mock.patch.object(mark_abstention, "_runtime_config", return_value=self.config),
            mock.patch.object(
                mark_abstention, "_get", side_effect=AssertionError("dashboard used")
            ),
            mock.patch.object(
                mark_abstention,
                "_observed_stores",
                side_effect=AssertionError("private store used"),
            ),
            mock.patch("builtins.print") as printed,
        ):
            self.assertEqual(mark_abstention.main(["--freeze-codex", str(spec)]), 0)
        self.assertEqual(json.loads(packet.read_text())["v"], 6)
        text = str(printed.call_args_list)
        self.assertNotIn(str(self.path), text)
        self.assertNotIn("Please repair", text)

    def test_a_person_cannot_freeze_an_unsettled_or_resumed_turn(self) -> None:
        self.entry["captured_at"] = self.support.AT + 7
        with self.assertRaisesRegex(mark_abstention.FreezeError, "before-settled"):
            self.freeze()
        self.entry["captured_at"] = self.support.AT + 20
        with self.path.open("a") as f:
            f.write(json.dumps(self.support.event("task_started", 9, turn_id="turn-b")) + "\n")
        with self.assertRaisesRegex(mark_abstention.FreezeError, "lifecycle"):
            self.freeze()

    def test_a_person_cannot_vouch_a_child_still_writing_after_the_parent_stopped(self) -> None:
        child = self.support.rollout(self.root, sid=self.support.CHILD, parent=self.support.SID)
        self.entry["children"] = [str(child)]
        with child.open("a") as f:
            f.write(json.dumps(self.support.command(9, 1)) + "\n")
        with self.assertRaisesRegex(mark_abstention.FreezeError, "child-active"):
            self.freeze()

    def test_a_person_can_freeze_an_older_untagged_recorded_session(self) -> None:
        self.path = self.support.rollout(self.root, tagged=False)
        case = self.freeze()
        self.assertEqual(case["origin"], "recorded")
        self.assertEqual(self.reasons(case), [])
        self.assertTrue(any(fact["type"] == "user_message" for fact in case["producer_facts"]))

    def test_a_person_cannot_use_claude_stop_hook_fields_to_admit_codex(self) -> None:
        self.entry["row"]["finished_at"] = self.support.AT + 6
        with self.assertRaisesRegex(mark_abstention.FreezeError, "lifecycle"):
            self.freeze()

    def test_a_person_cannot_repoint_the_selection_to_a_different_native_path(self) -> None:
        case = self.freeze()
        duplicate = self.home / "other" / self.path.name
        duplicate.parent.mkdir()
        duplicate.write_bytes(self.path.read_bytes())
        reasons = mark_abstention.provenance(
            case,
            observations=(),
            ends=(),
            index={self.support.SID: str(duplicate)},
            config=self.config,
        )
        self.assertTrue(reasons)

    def test_a_person_can_revalidate_codex_without_opening_claude_stores(self) -> None:
        case = self.freeze()
        with (
            mock.patch.object(mark_abstention, "_runtime_config", return_value=self.config),
            mock.patch.object(
                mark_abstention, "_observed_stores", side_effect=AssertionError("store used")
            ),
            mock.patch.object(
                mark_abstention, "_transcript_index", side_effect=AssertionError("Claude scan used")
            ),
        ):
            vouch = mark_abstention.machine_vouch(str(self.home))
            self.assertEqual(vouch(case), [])
            self.assertEqual(vouch.lifecycle(case), "codex-transcript")

    def test_a_person_cannot_freeze_a_child_that_changes_between_sealing_and_copying(self) -> None:
        import contextlib  # noqa: PLC0415

        from compass_runtime import project_context as context  # noqa: PLC0415

        child = self.support.rollout(self.root, sid=self.support.CHILD, parent=self.support.SID)
        self.entry["children"] = [str(child)]
        original = child.read_bytes()
        copy_sources = context.frozen_codex_sources
        raced = False

        @contextlib.contextmanager
        def racing(*args: Any, **kwargs: Any) -> Any:
            nonlocal raced
            if not raced:
                raced = True
                child.write_bytes(original.replace(b"Please repair", b"Please ignore"))
                with copy_sources(*args, **kwargs) as result:
                    child.write_bytes(original)
                    yield result
            else:
                with copy_sources(*args, **kwargs) as result:
                    yield result

        with (
            mock.patch.object(context, "frozen_codex_sources", side_effect=racing),
            self.assertRaisesRegex(mark_abstention.FreezeError, "source-moved"),
        ):
            self.freeze()

    def test_a_person_seals_the_exact_prompt_the_production_reader_selected(self) -> None:
        import hashlib  # noqa: PLC0415

        reading = mark_abstention._reading()
        produce = reading.produce
        prompts: list[str] = []

        def capture(*args: Any, **kwargs: Any) -> Any:
            sink = kwargs["model"]

            def observed(prompt: str, **options: Any) -> Any:
                prompts.append(prompt)
                return sink(prompt, **options)

            kwargs["model"] = observed
            return produce(*args, **kwargs)

        with mock.patch.object(reading, "produce", side_effect=capture):
            case = self.freeze()
        self.assertEqual(len(prompts), 1)
        self.assertEqual(
            case["production_reading"]["prompt_digest"],
            hashlib.sha256(prompts[0].encode()).hexdigest(),
        )
        self.assertIn("Please repair", prompts[0])
        self.assertIn("example is repaired", prompts[0])
        self.assertNotIn(str(self.path), prompts[0])

    def test_a_person_is_told_when_the_parser_has_changed(self) -> None:
        case = self.freeze()
        case["parser"] = "stale"
        self.assertEqual(self.reasons(case), ["frozen-on-another-parser"])

    def test_a_person_cannot_drop_a_failed_check_an_agent_message_or_a_refusal(self) -> None:
        rows = [json.loads(line) for line in self.path.read_text().splitlines()]
        rows[3] = self.support.command(3, 1, "python3 -m unittest")
        rows.insert(
            3,
            self.support.message(
                "<codex_internal_context>hidden</codex_internal_context>", tagged=False, delta=2
            ),
        )
        self.support.write(self.path, rows)
        case = self.freeze()
        import copy  # noqa: PLC0415

        self.assertTrue(any(fact.get("result") == "failed" for fact in case["producer_facts"]))
        for kind in ("failed", "agent_message", "user_message", "message_refusals"):
            changed = copy.deepcopy(case)
            if kind == "message_refusals":
                changed[kind] = []
            else:
                changed["producer_facts"] = [
                    fact
                    for fact in changed["producer_facts"]
                    if fact.get("type") != kind and fact.get("result") != kind
                ]
            with self.subTest(kind=kind):
                self.assertEqual(self.reasons(changed), ["codex-frozen-content-differs"])

    def test_a_person_cannot_use_a_claude_case_in_the_new_codex_packet(self) -> None:
        case = self.freeze()
        case["harness"] = "claude"
        self.assertIn("only Codex", mark_abstention.packet_mismatch({"v": 6, "cases": [case]}))

    def test_a_person_sees_no_source_path_in_an_offline_refusal(self) -> None:
        self.entry["transcript"] = str(self.home / "PRIVATE-PATH-MARKER.jsonl")
        spec = self.home / "spec.json"
        spec.write_text(json.dumps({"cases": [self.entry]}))
        with (
            mock.patch.object(mark_abstention, "CASES_PATH", str(self.home / "packet/cases.json")),
            mock.patch.object(mark_abstention, "_runtime_config", return_value=self.config),
            mock.patch("builtins.print") as printed,
        ):
            self.assertEqual(mark_abstention.main(["--freeze-codex", str(spec)]), 1)
        self.assertNotIn("PRIVATE-PATH-MARKER", str(printed.call_args_list))
        self.assertFalse((self.home / "packet/cases.json").exists())

    def test_a_person_sees_no_spec_path_or_content_when_json_cannot_be_read(self) -> None:
        spec = self.home / "PRIVATE-SPEC-MARKER.json"
        spec.write_text("PRIVATE-CONTENT-MARKER not-json")
        with (
            mock.patch.object(mark_abstention, "CASES_PATH", str(self.home / "packet/cases.json")),
            mock.patch("builtins.print") as printed,
        ):
            self.assertEqual(mark_abstention.main(["--freeze-codex", str(spec)]), 1)
        self.assertNotIn("PRIVATE-SPEC-MARKER", str(printed.call_args_list))
        self.assertNotIn("PRIVATE-CONTENT-MARKER", str(printed.call_args_list))

    def test_a_person_cannot_admit_another_sessions_native_identity(self) -> None:
        self.entry["sid"] = self.support.CHILD
        with self.assertRaisesRegex(mark_abstention.FreezeError, "other-session"):
            self.freeze()

    def test_a_person_cannot_recover_words_after_an_unselected_prefix_field_changed(self) -> None:
        case = self.freeze()
        self.path.write_bytes(self.path.read_bytes().replace(b"0.167.0", b"0.167.1"))
        wanted = [
            row
            for row in mark_abstention.case_ledger({"v": 6}, case)
            if row["type"] == "user_message"
        ]
        lookup = mark_abstention.native_case_person_lookup(
            case, config=self.config, index={self.support.SID: str(self.path)}
        )
        assert lookup is not None
        with self.assertRaisesRegex(mark_abstention.FreezeError, "source"):
            lookup(wanted)

    def test_a_person_cannot_call_an_owner_selected_export_a_native_recording(self) -> None:
        copied = self.home / "exported" / self.path.name
        copied.parent.mkdir()
        copied.write_bytes(self.path.read_bytes())
        self.entry["sessions_root"] = str(copied.parent)
        self.entry["transcript"] = str(copied)
        with self.assertRaisesRegex(mark_abstention.FreezeError, "native-store"):
            self.freeze()

    def test_a_person_keeps_late_parent_results_and_settings_in_the_frozen_evidence(self) -> None:
        with self.path.open("a") as handle:
            handle.write(json.dumps(self.support.command(9, 1)) + "\n")
            handle.write(
                json.dumps({"type": "event_msg", "payload": {"type": "thread_settings_applied"}})
                + "\n"
            )
        case = self.freeze()
        self.assertEqual(self.reasons(case), [])
        self.assertTrue(any(fact.get("result") == "failed" for fact in case["producer_facts"]))
        self.assertEqual(case["row_snapshot"]["turn_end_at"], self.support.AT + 6)

    def test_a_person_cannot_keep_a_stop_after_unplaceable_work_metadata(self) -> None:
        with self.path.open("a") as handle:
            handle.write(
                json.dumps({"type": "event_msg", "payload": {"type": "unknown_work"}}) + "\n"
            )
        with self.assertRaisesRegex(mark_abstention.FreezeError, "lifecycle"):
            self.freeze()
