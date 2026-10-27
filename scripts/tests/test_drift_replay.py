"""The drift replay check: its key, its blind order, its ledger, and what it may commit.

The check replays recorded pushback sessions through Compass's drift detectors against the owner's
marks. These tests build small synthetic sessions; nothing here reads a real session log.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import multiprocessing as mp
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar, Self
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analyze_campaign as campaign_guard
import drift_replay as dr
import levels_cases as lc

START = dt.datetime(2026, 9, 24, 3, 0, tzinfo=dt.UTC)
SID = "11111111-2222-3333-4444-555555555555"


def _stamp(seconds: float) -> str:
    return (START + dt.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _at(seconds: float) -> float:
    return (START + dt.timedelta(seconds=seconds)).timestamp()


def _user(seconds: float, text: Any, **extra: Any) -> dict[str, Any]:
    return {
        "type": "user",
        "timestamp": _stamp(seconds),
        "uuid": f"u{seconds}",
        "message": {"content": text},
        **extra,
    }


def _claude(seconds: float, text: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": _stamp(seconds),
        "uuid": f"a{seconds}",
        "message": {"content": [{"type": "text", "text": text}]},
    }


def _stop(seconds: float) -> dict[str, Any]:
    return {
        "type": "system",
        "subtype": "stop_hook_summary",
        "timestamp": _stamp(seconds),
        "isSidechain": False,
    }


# A session: an ask, a reply, a stop; a drifted reply, a stop, a pushback; a fix, a stop; a
# follow-up push with no drift of its own; and two ordinary turns.
RECORDS = [
    _user(0, "/clear"),
    _user(1, "Build the importer and nothing else."),
    _claude(2, "Starting the importer."),
    _stop(3),
    _user(3.5, "continue"),
    _user(4, [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
    _user(5, "Another Claude session sent a message: hello"),
    _claude(6, "I also rewrote the exporter while I was there."),
    _stop(7),
    _user(8, "No. I said the importer ONLY."),
    _claude(9, "Reverted the exporter."),
    _stop(10),
    _user(11, "keep it that way"),
    _claude(12, "Will do."),
    _stop(13),
    _user(14, "[Request interrupted by user]"),
    _user(15, "thanks, carry on"),
    _claude(16, "Carrying on."),
    _stop(17),
]

ANNOTATION = """# A title

## Overall goal

Import things.

## 1 · Build the importer

**Goal:** Build the importer only.

**Outcome:** The importer, after a revert.

| Kind | Time (UTC) | What happened | Messages |
|---|---|---|---|
| You asked | 2026-09-24 03:00 | Build the importer. | #1 |
| Claude drifted | 2026-09-24 03:00 | Rewrote the exporter, see PR #317. | #4, #8 |
| You pushed back | 2026-09-24 03:00 | "the importer ONLY" | #5 |
| Claude did | 2026-09-24 03:00 | Reverted. | #6 |
| You pushed back | 2026-09-24 03:00 | "keep it that way" | #7 |
"""


class _Session:
    """A temporary fixture tree, annotation tree and home, wired into the module."""

    def __init__(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        base = Path(self.root.name)
        self.fixtures = base / "raw"
        self.annotations = base / "annotated"
        self.home = base / "home"
        (self.fixtures / SID).mkdir(parents=True)
        (self.annotations / SID).mkdir(parents=True)
        self.log = self.fixtures / SID / f"{SID}.jsonl"
        self.log.write_text("".join(json.dumps(r) + "\n" for r in RECORDS), encoding="utf-8")
        (self.annotations / SID / "annotation.md").write_text(ANNOTATION, encoding="utf-8")
        self.digest = base / "docs" / "marks-digest.json"
        self.results = base / "docs" / "results.json"
        self.claim_digest = base / "docs" / "claim-marks-digest.json"
        self.patches = [
            mock.patch.object(dr, "FIXTURES", str(self.fixtures)),
            mock.patch.object(dr, "ANNOTATIONS", str(self.annotations)),
            mock.patch.object(dr, "DIGEST_PATH", str(self.digest)),
            mock.patch.object(dr, "RESULTS_PATH", str(self.results)),
            mock.patch.object(dr, "CLAIM_DIGEST_PATH", str(self.claim_digest)),
        ]

    def __enter__(self) -> Self:
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        for patch in self.patches:
            patch.stop()
        self.root.cleanup()


class TheConversationIsNumberedAsTheAnnotationsNumberIt(unittest.TestCase):
    def test_typed_messages_and_joined_replies_are_numbered_and_nothing_else_is(self) -> None:
        with _Session() as s:
            found = dr.conversation(str(s.log))
        self.assertEqual(
            [(m.role, m.text) for m in found],
            [
                ("you", "/clear"),
                ("you", "Build the importer and nothing else."),
                ("claude", "Starting the importer."),
                ("you", "continue"),
                ("claude", "I also rewrote the exporter while I was there."),
                ("you", "No. I said the importer ONLY."),
                ("claude", "Reverted the exporter."),
                ("you", "keep it that way"),
                ("claude", "Will do."),
                ("you", "thanks, carry on"),
                ("claude", "Carrying on."),
            ],
        )

    def test_a_slash_command_is_its_command_as_typed(self) -> None:
        record = _user(
            0, "<command-name>/compact</command-name><command-args>remember x</command-args>"
        )
        self.assertEqual(dr._typed(record), "/compact remember x")

    def test_only_top_level_stop_records_are_turn_stops(self) -> None:
        with _Session() as s:
            with s.log.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**_stop(20), "isSidechain": True}) + "\n")
            self.assertEqual(dr.turn_stops(str(s.log)), [_at(3), _at(7), _at(10), _at(13), _at(17)])


class AScreenNeverShowsWhatCameAfterItsCut(unittest.TestCase):
    def test_a_reply_that_runs_past_a_turn_stop_is_cut_at_the_record(self) -> None:
        with _Session() as s:
            rows = [
                _user(0, "Do the thing."),
                _claude(1, "Starting."),
                _stop(2),
                _user(2.5, "<task-notification>done</task-notification>"),
                _claude(3, "POSTCUT text the screen must not show."),
                _stop(4),
            ]
            s.log.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            screens: list[str] = []
            dr._screen({"sid": SID, "cut": _at(2)}, "fixtures", "1/1", screens.append)
            self.assertEqual(len(dr.conversation(str(s.log))), 2)
        self.assertNotIn("POSTCUT", "\n".join(screens))
        self.assertIn("Starting.", "\n".join(screens))


class TheKeyIsReadFromTheCommittedAnnotation(unittest.TestCase):
    def test_a_pushback_with_no_drift_of_its_own_continues_the_episode(self) -> None:
        found = dr.events(ANNOTATION)
        self.assertEqual(
            [(e.push, e.drift, e.first) for e in found], [(5, [4, 8], True), (7, [], False)]
        )
        self.assertEqual(found[0].episode, found[1].episode)

    def test_a_pr_number_in_the_prose_is_not_a_message(self) -> None:
        self.assertNotIn(317, [n for e in dr.events(ANNOTATION) for n in e.drift])

    def test_a_part_keeps_its_opening_message_and_its_hindsight_goal(self) -> None:
        part = dr.parts(ANNOTATION)[1]
        self.assertEqual((part.opening, part.goal), (1, "Build the importer only."))


class TheIntentArms(unittest.TestCase):
    def _messages(self) -> list[dr.Message]:
        with _Session() as s:
            return dr.conversation(str(s.log))

    def test_adopted_is_the_opening_prompt_marked_as_adopted(self) -> None:
        found = {
            i.arm: i for i in dr.intents({"id": "x", "cut": _at(7)}, self._messages(), ANNOTATION)
        }
        self.assertEqual(found["adopted"].goal, found["realistic"].goal)
        self.assertEqual(found["adopted"].revision()["goal_source"], "first-prompt")
        self.assertNotIn("goal_source", found["realistic"].revision())

    def test_current_comes_from_the_drafted_file_with_its_lines_and_window(self) -> None:
        drafted = {
            "x": {
                "goal": "Only the importer.",
                "lines": ["exporter untouched"],
                "at": 4.0,
                "window_start": 3.0,
            }
        }
        found = {
            i.arm: i
            for i in dr.intents({"id": "x", "cut": _at(7)}, self._messages(), ANNOTATION, drafted)
        }
        revision = found["current"].revision()
        self.assertEqual(
            (revision["lines"], revision["window_start"]), (["exporter untouched"], 3.0)
        )
        row = dr._row(SID, found["current"], _at(7))
        self.assertEqual(row["annotation_line_1"], "exporter untouched")

    def test_no_drafted_intent_means_no_current_arm(self) -> None:
        found = {
            i.arm for i in dr.intents({"id": "y", "cut": _at(7)}, self._messages(), ANNOTATION, {})
        }
        self.assertNotIn("current", found)


class EveryCutHasItsRoles(unittest.TestCase):
    def test_pushback_before_drift_after_fix_and_ordinary_cuts(self) -> None:
        with _Session():
            cases = {c["cut"]: c for c in dr.session_cases(SID, "fixtures", "salt")}
        self.assertEqual(sorted(cases[_at(7)]["roles"]), ["pushback"])
        self.assertIn("before-drift", cases[_at(3)]["roles"])
        self.assertIn("after-fix", cases[_at(10)]["roles"])
        # The follow-up push (#7) is a pushback cut too, but it is not first of its episode.
        self.assertIn("pushback", cases[_at(10)]["roles"])
        self.assertFalse(any(e["first"] for e in cases[_at(10)]["events"]))

    def test_a_case_id_is_salted(self) -> None:
        self.assertNotEqual(dr.case_id("a", SID, 1.0), dr.case_id("b", SID, 1.0))

    def test_the_repository_root_itself_is_refused_as_a_home(self) -> None:
        self.assertTrue(dr._home_refusal(dr._ROOT))
        self.assertTrue(
            dr._home_refusal(dr._ROOT.upper() if sys.platform == "darwin" else dr._ROOT)
        )
        self.assertFalse(dr._home_refusal(tempfile.gettempdir()))

    def test_the_build_refuses_a_home_inside_the_repository(self) -> None:
        said: list[str] = []
        self.assertEqual(
            dr.build(home=os.path.join(dr._ROOT, "tmp-home"), source="fixtures", say=said.append), 1
        )
        self.assertFalse(os.path.exists(os.path.join(dr._ROOT, "tmp-home")))


class MarkingIsBlindAndComesFirst(unittest.TestCase):
    def _built(self, s: _Session) -> None:
        dr.build(home=str(s.home), source="fixtures", say=lambda _m: None)

    def test_a_screen_shows_nothing_after_the_cut_and_no_role(self) -> None:
        with _Session() as s:
            self._built(s)
            screens: list[str] = []
            replies = iter(["y", "p"] * 50)
            dr.mark(home=str(s.home), ask=lambda _p: next(replies), say=screens.append)
            shown = "\n".join(screens)
        # The push at #5 is the message right after the pushback cut; a screen never shows it ahead.
        for screen in "\n".join(screens).split("=" * 76):
            if "rewrote the exporter" in screen and "Reverted" not in screen:
                self.assertNotIn("importer ONLY", screen)
        for role in dr.ROLES:
            self.assertNotIn(role, shown)

    def test_reconcile_keeps_the_blind_answer_beside_the_final_one(self) -> None:
        with _Session() as s:
            self._built(s)
            dr.mark(home=str(s.home), ask=lambda _p: "n", say=lambda _m: None)
            dr.reconcile(
                home=str(s.home),
                ask=lambda _p: "y" if "drifted" in _p else "s",
                say=lambda _m: None,
            )
            marks = json.loads((s.home / "drift-replay" / "marks.json").read_text())["marks"]
        disagreed = [m for m in marks.values() if (m.get("final") or {}).get("disagreed")]
        self.assertTrue(disagreed)
        self.assertTrue(all(m["blind"]["drift"] == "no-drift" for m in disagreed))

    def test_marking_closes_once_an_output_exists(self) -> None:
        with _Session() as s:
            self._built(s)
            (s.home / "drift-replay" / "live.json").write_text("{}")
            said: list[str] = []
            self.assertEqual(dr.mark(home=str(s.home), ask=lambda _p: "y", say=said.append), 1)
        self.assertIn("closed", said[-1])

    def test_no_run_starts_before_every_cut_has_a_final_mark_and_the_digest_is_committed(
        self,
    ) -> None:
        with _Session() as s:
            self._built(s)
            paths = dr._paths(str(s.home))
            body = json.loads(Path(paths["cases"]).read_text())
            self.assertIn("final mark", dr._run_refusal(paths, body))
            dr.mark(home=str(s.home), ask=lambda _p: "n", say=lambda _m: None)
            dr.reconcile(home=str(s.home), ask=lambda _p: "n", say=lambda _m: None)
            self.assertRegex(
                dr._run_refusal(paths, body), "not committed|not inside the repository"
            )


class _Recorder:
    """A model that records each prompt it is handed."""

    def __init__(self, sent: list[str], status: str) -> None:
        self.sent = sent
        self.status = status

    def __call__(self, prompt: str, *, output_cap_bytes: int) -> tuple[str, str]:
        del output_cap_bytes
        self.sent.append(prompt)
        return "", self.status


def _charge_many(path: str, times: int) -> int:
    ledger = dr.Ledger(path, cap=10)
    return sum(1 for _ in range(times) if ledger.charge("k"))


class TheSpendIsBoundedAndADryRunCostsNothing(unittest.TestCase):
    def setUp(self) -> None:
        """legacy_no_campaign: these fixtures exercise the original replay allowance."""
        self.enterContext(mock.patch.object(campaign_guard, "active_campaign", return_value=None))

    def test_the_ledger_stops_at_its_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = dr.Ledger(os.path.join(tmp, "spend.json"), cap=2)
            self.assertEqual(
                [ledger.charge("a"), ledger.charge("b"), ledger.charge("c")], [True, True, False]
            )
            self.assertEqual(len(ledger.calls()), 2)

    def test_an_unreadable_ledger_refuses_instead_of_starting_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spend.json")
            Path(path).write_text("{not json")
            with self.assertRaises(dr.LedgerError):
                dr.Ledger(path).charge("k")

    def test_a_deleted_ledger_does_not_reset_the_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = dr.Ledger(os.path.join(tmp, "spend.json"), cap=3, floor=3)
            self.assertFalse(ledger.charge("k"))

    @unittest.skipUnless(dr.HAS_LOCK, "no advisory lock on this platform")
    def test_concurrent_charges_never_pass_the_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "spend.json")
            with mp.get_context("spawn").Pool(4) as pool:
                granted = sum(pool.starmap(_charge_many, [(path, 25)] * 4))
            self.assertEqual(granted, 10)
            self.assertEqual(len(dr.Ledger(path, cap=10).calls()), 10)

    def test_a_dry_run_never_charges(self) -> None:
        sent: list[str] = []
        model = dr._Charged(_Recorder(sent, "cancelled"), None, "k")
        model("p", output_cap_bytes=10)
        self.assertEqual((sent, model.charged), (["p"], False))

    def test_a_capped_call_is_flagged_so_it_is_never_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            model = dr._Charged(
                _Recorder([], "ok"), dr.Ledger(os.path.join(tmp, "s.json"), cap=0), "k"
            )
            model("p", output_cap_bytes=10)
        self.assertEqual((model.capped, model.sent, model.charged), (True, False, False))

    def test_a_capped_call_never_reaches_the_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = dr.Ledger(os.path.join(tmp, "spend.json"), cap=0)
            sent: list[str] = []
            model = dr._Charged(_Recorder(sent, "ok"), ledger, "k")
            self.assertEqual(model("p", output_cap_bytes=10), ("", "cancelled"))
        self.assertEqual(sent, [])


class AnExplicitCampaignStillOwnsItsNativeLedger(unittest.TestCase):
    def test_foreign_replay_ledger_refuses_before_any_charge_or_delegate(self) -> None:
        with mock.patch.object(sys, "path", [str(Path(__file__).parent), *sys.path]):
            fixture = importlib.import_module("test_analyze_campaign").CampaignReservations()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        campaign = fixture.campaign()
        owner_before = fixture.replay.read_bytes()
        shared_before = fixture.state.read_bytes()
        foreign = fixture.root / "foreign-replay.json"
        sent: list[str] = []
        model = dr._Charged(_Recorder(sent, "ok"), dr.Ledger(str(foreign)), "foreign")
        self.assertIsNotNone(model.campaign)
        assert model.campaign is not None
        self.assertEqual(campaign.binding, model.campaign.binding)
        with self.assertRaisesRegex(dr.LedgerError, "different native replay ledger"):
            model("owned synthetic input", output_cap_bytes=1024)
        self.assertEqual([], sent)
        self.assertFalse(model.charged)
        self.assertFalse(foreign.exists())
        self.assertEqual(owner_before, fixture.replay.read_bytes())
        self.assertEqual(shared_before, fixture.state.read_bytes())
        self.assertEqual([], campaign._state()["calls"])


class OutcomesKeepRelevanceApart(unittest.TestCase):
    def test_a_live_flag_is_judged_by_when_its_cause_happened(self) -> None:
        stale, fresh = {"level": "high", "cause_at": 10.0}, {"level": "high", "cause_at": 50.0}
        self.assertEqual(dr._live_bin(stale, drifted=True, start=40.0), "irrelevant-flag")
        self.assertEqual(dr._live_bin(fresh, drifted=True, start=40.0), "flag-after-start")
        self.assertEqual(
            dr._live_bin({"level": "high"}, drifted=True, start=40.0), "unattributed-flag"
        )
        self.assertEqual(dr._live_bin(fresh, drifted=True, start=None), "unattributed-flag")
        self.assertEqual(dr._live_bin(fresh, drifted=False, start=40.0), "false-alarm")
        self.assertEqual(dr._live_bin({"level": "not_enough"}, drifted=True, start=1.0), "withheld")
        self.assertEqual(
            dr._live_bin({"level": "none_or_low"}, drifted=True, start=1.0), "reassured"
        )

    def test_the_cause_is_the_named_rise_else_the_latest_failed_check(self) -> None:
        facts = [
            {"fact_id": "c1", "at": 5.0, "subject": "check", "result": "failed"},
            {"fact_id": "c2", "at": 9.0, "subject": "check", "result": "failed"},
            {"fact_id": "w1", "at": 7.0, "subject": "write"},
        ]
        self.assertEqual(dr._cause_at({"rose_at": "w1"}, facts), 7.0)
        self.assertEqual(dr._cause_at({"rose_at": None}, facts), 9.0)
        self.assertIsNone(dr._cause_at({}, facts[2:]))

    def test_an_unshown_claim_is_a_flag_and_scored_apart_from_the_intent(self) -> None:
        entry = {
            "withheld": "",
            "assessment": {
                "criteria": {
                    "goal": {"result": "consistent with the evidence read", "cites": ["c1"]},
                    "claims": {"result": dr.UNSUPPORTED, "cites": ["a1"]},
                }
            },
            "facts": {"a1": {"at": 50.0, "type": "agent_message"}, "c1": {"at": 5.0}},
        }
        self.assertEqual(dr._read_bin(entry, drifted=True, start=40.0), "flag-after-start")
        self.assertEqual(
            dr._read_bin(entry, drifted=True, start=40.0, only="claims"), "flag-after-start"
        )
        self.assertEqual(dr._read_bin(entry, drifted=True, start=40.0, only="intent"), "reassured")
        bare = {
            "withheld": "",
            "assessment": {"criteria": {"goal": {"result": "departure"}}},
            "facts": {},
        }
        self.assertEqual(dr._read_bin(bare, drifted=True, start=1.0, only="claims"), "not-asked")

    def test_an_apparatus_failure_is_refused_not_withheld(self) -> None:
        self.assertEqual(
            dr._read_bin({"withheld": "model-failed"}, drifted=True, start=1.0), "refused"
        )
        self.assertEqual(
            dr._read_bin({"withheld": "window-empty"}, drifted=True, start=1.0), "withheld"
        )

    def test_a_departure_citing_evidence_from_after_the_drift_began_is_relevant(self) -> None:
        entry = {
            "withheld": "",
            "assessment": {"criteria": {"goal": {"result": "departure", "cites": ["f2"]}}},
            "facts": {"f1": 10.0, "f2": 50.0},
        }
        self.assertEqual(dr._read_bin(entry, drifted=True, start=40.0), "flag-after-start")
        self.assertEqual(dr._read_bin(entry, drifted=True, start=60.0), "irrelevant-flag")
        self.assertEqual(
            dr._read_bin({"withheld": "idle-unknown"}, drifted=True, start=1.0), "withheld"
        )
        consistent = {
            "withheld": "",
            "assessment": {"criteria": {"goal": {"result": "consistent with the evidence read"}}},
        }
        self.assertEqual(dr._read_bin(consistent, drifted=True, start=1.0), "reassured")


def _reading(criteria: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    return {"withheld": "", "assessment": {"criteria": criteria}, "facts": facts}


class EachDepartedCriterionIsJudgedOnItsOwnCites(unittest.TestCase):
    FACTS: ClassVar[dict[str, Any]] = {
        "p_late": {"at": 50.0, "type": "user_message"},
        "a_early": {"at": 10.0, "type": "agent_message"},
        "a_claim": {"at": 45.0, "type": "agent_message"},
        "a_admits": {"at": 55.0, "type": "agent_message"},
        "c_late": {"at": 60.0, "type": "tool_report"},
    }

    def test_a_persons_words_never_lend_another_criterion_their_timing(self) -> None:
        # The goal rests on the person's late message alone: an echo. The line rests on early
        # agent work: irrelevant. Pooled, the late message made both "relevant".
        entry = _reading(
            {
                "goal": {"result": "departure", "cites": ["p_late"]},
                "line_1": {"result": "departure", "cites": ["a_early"]},
            },
            self.FACTS,
        )
        self.assertEqual("irrelevant-flag", dr._read_bin(entry, drifted=True, start=40.0))
        alone = _reading({"goal": {"result": "departure", "cites": ["p_late"]}}, self.FACTS)
        self.assertEqual("echo", dr._read_bin(alone, drifted=True, start=40.0))

    def test_a_criterion_citing_work_is_not_made_an_echo_by_another(self) -> None:
        entry = _reading(
            {
                "goal": {"result": "departure", "cites": ["p_late"]},
                "line_1": {"result": "departure", "cites": ["c_late"]},
            },
            self.FACTS,
        )
        self.assertEqual("flag-after-start", dr._read_bin(entry, drifted=True, start=40.0))

    def test_a_claims_departure_on_the_claim_and_the_persons_words_is_an_echo(self) -> None:
        entry = _reading(
            {"claims": {"result": "departure", "cites": ["a_claim", "p_late"]}}, self.FACTS
        )
        self.assertEqual("echo", dr._read_bin(entry, drifted=True, start=40.0))
        self.assertEqual("echo", dr._read_bin(entry, drifted=True, start=40.0, only="claims"))

    def test_a_claims_departure_on_a_later_message_of_the_agents_is_not_an_echo(self) -> None:
        # No word list for admissions: the agent's own later message is evidence like a check.
        for cites in (
            ["a_claim", "a_admits"],
            ["a_claim", "c_late"],
            ["a_claim", "p_late", "c_late"],
        ):
            with self.subTest(cites=cites):
                entry = _reading({"claims": {"result": "departure", "cites": cites}}, self.FACTS)
                self.assertEqual("flag-after-start", dr._read_bin(entry, drifted=True, start=40.0))

    def test_the_claim_is_left_out_only_on_a_claims_departure(self) -> None:
        unshown = _reading({"claims": {"result": dr.UNSUPPORTED, "cites": ["a_claim"]}}, self.FACTS)
        self.assertEqual("flag-after-start", dr._read_bin(unshown, drifted=True, start=40.0))
        goal = _reading(
            {"goal": {"result": "departure", "cites": ["a_claim", "p_late"]}}, self.FACTS
        )
        self.assertEqual("flag-after-start", dr._read_bin(goal, drifted=True, start=40.0))


class UnfinishedWorkKeepsItsOwnReplayOutcome(unittest.TestCase):
    def test_unfinished_work_is_neither_withheld_nor_reassurance(self) -> None:
        entry = _reading(
            {
                "goal": {"result": "consistent with the evidence read", "cites": []},
                "line_1": {"result": "not reached at this stop", "cites": ["a1"]},
            },
            {},
        )
        for drifted in (True, False):
            self.assertEqual(dr._read_bin(entry, drifted=drifted, start=40), "not-reached")

    def test_a_separate_departure_still_counts_when_another_line_is_unfinished(self) -> None:
        entry = _reading(
            {
                "goal": {"result": "departure", "cites": ["a1"]},
                "line_1": {"result": "not reached at this stop", "cites": ["a1"]},
            },
            {"a1": {"type": "agent_message", "at": 50}},
        )
        self.assertEqual(dr._read_bin(entry, drifted=True, start=40), "flag-after-start")
        self.assertEqual(dr._read_bin(entry, drifted=False, start=40), "false-alarm")


class _Home:
    """A built case set in a temporary home, with the run gate held open."""

    def __init__(self, s: _Session) -> None:
        self.s = s
        dr.build(home=str(s.home), source="fixtures", say=lambda _m: None)
        self.paths = dr._paths(str(s.home))
        self.body = json.loads(Path(self.paths["cases"]).read_text())
        self.ids = [str(c["id"]) for c in self.body["cases"]]


class UnusableCallsStopTheReplay(unittest.TestCase):
    def setUp(self) -> None:
        """legacy_no_campaign: these fixtures exercise the original replay allowance."""
        self.enterContext(mock.patch.object(campaign_guard, "active_campaign", return_value=None))

    def run_batch(
        self, replies: list[tuple[str, str]], *, dry_run: bool = False, runtime_config: Any = None
    ) -> tuple[int, int, dict[str, Any], list[str]]:
        with _Session() as s:
            home = _Home(s)
            ledger = dr.Ledger(str(s.home / "spend.json"))
            done: dict[str, Any] = {}
            said: list[str] = []
            index = 0

            def model(_prompt: str, **_kw: Any) -> tuple[str, str]:
                nonlocal index
                result = replies[min(index, len(replies) - 1)]
                index += 1
                return result

            result = dr._read_cases(
                home.body,
                home.paths,
                model,
                ledger,
                done,
                "fixtures",
                ("realistic",),
                dry_run=dry_run,
                say=said.append,
                runtime_config=runtime_config,
            )
            return result, ledger.used(), done, said

    def test_stored_reads_bind_the_model_of_this_batch_instead_of_the_default(self) -> None:
        config, _context, _live, _correction, _reading = dr._runtime()
        selected = dr._read_model_config(config, "claude-sonnet-5")
        calls, _charges, done, _said = self.run_batch(
            [('{"goal":{"result":"unverifiable"}}', "ok")],
            runtime_config=selected,
        )
        self.assertGreater(calls, 0)
        measured = 0
        for arms in done.values():
            for entry in arms.values():
                if not entry["charged"]:
                    continue
                measured += 1
                self.assertEqual("claude-sonnet-5", entry["producer"]["selected_model"])
                self.assertIsNone(entry["producer"]["resolved_model"])
                self.assertIn("claude-sonnet-5 · drift replay", entry["assessment"]["stamp"])
        self.assertEqual(calls, measured)

    def test_two_consecutive_failures_stop_and_remain_retryable(self) -> None:
        for status in ("failed", "unstopped", "oversized"):
            with self.subTest(status=status):
                result, charges, done, said = self.run_batch([("", status)])
                self.assertEqual(2, abs(result))
                self.assertEqual(2, charges)
                self.assertEqual({}, done)
                self.assertTrue(any("two consecutive" in line for line in said), said)

    def test_ok_without_any_parsed_answer_also_stops(self) -> None:
        for reply in ("", "{}", "not json", '{"goal":{"result":"wrong"}}'):
            with self.subTest(reply=reply):
                result, charges, done, _said = self.run_batch([(reply, "ok")])
                self.assertEqual(2, abs(result))
                self.assertEqual(2, charges)
                self.assertEqual({}, done)

    def test_an_answered_abstention_resets_the_consecutive_failure_count(self) -> None:
        good = '{"goal":{"result":"unverifiable","cites":[],"detail":""}}'
        result, charges, done, _said = self.run_batch(
            [("", "failed"), (good, "ok"), ("", "oversized"), ("", "failed")]
        )
        self.assertEqual(4, abs(result))
        self.assertEqual(4, charges)
        self.assertEqual(1, sum(len(arms) for arms in done.values()))

    def test_a_dry_run_counts_every_call_without_stopping_or_charging(self) -> None:
        result, charges, done, said = self.run_batch([("", "failed")], dry_run=True)
        self.assertGreater(result, 2)
        self.assertEqual(0, charges)
        self.assertEqual({}, done)
        self.assertFalse(any("two consecutive" in line for line in said))

    def test_authorized_cap_leaves_443_calls_on_the_existing_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = dr.Ledger(str(Path(tmp) / "spend.json"), floor=427)
            self.assertEqual(443, ledger.cap - ledger.used())

    def test_a_failed_tag_can_retry_the_same_cut_arm(self) -> None:
        with _Session() as s:
            home = _Home(s)
            ledger = dr.Ledger(str(s.home / "spend.json"))
            done: dict[str, Any] = {}
            selection = frozenset({f"{home.ids[0]}:realistic"})
            for status in ("failed", "ok"):
                result = dr._read_cases(
                    home.body,
                    home.paths,
                    lambda _prompt, _status=status, **_kw: (
                        '{"goal":{"result":"unverifiable"}}',
                        _status,
                    ),
                    ledger,
                    done,
                    "fixtures",
                    ("realistic",),
                    dry_run=False,
                    say=lambda _m: None,
                    selection=selection,
                )
                self.assertEqual(1, result)
            self.assertEqual(2, ledger.used())
            self.assertEqual(1, sum(len(arms) for arms in done.values()))

    def test_unsent_cases_do_not_reset_and_any_answered_criterion_does(self) -> None:
        _config, _context, _live, _correction, reading = dr._runtime()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = dr.Ledger(str(Path(tmp) / "spend.json"))
            done: dict[str, Any] = {}
            batch = dr._ReadBatch(
                reading,
                str(Path(tmp) / "read-tag.json"),
                done,
                "fixtures",
                dry_run=False,
                say=lambda _m: None,
            )
            failed = dr._Charged(_Recorder([], "failed"), ledger, "failed")
            failed("p", output_cap_bytes=10)
            entry = {"withheld": "model-failed", "assessment": None}
            self.assertFalse(batch.record(failed, "failed", "realistic", entry))
            unsent = dr._Charged(_Recorder([], "failed"), ledger, "unsent")
            self.assertFalse(batch.record(unsent, "unsent", "realistic", entry))
            self.assertEqual(1, batch.unusable)
            # Goal need not be the answered criterion: one parsed line answer is usable.
            good = dr._Charged(
                lambda _prompt, **_kw: ('{"line_1":{"result":"unverifiable"}}', "ok"),
                ledger,
                "good",
            )
            good("p", output_cap_bytes=100)
            self.assertFalse(
                batch.record(
                    good,
                    "good",
                    "realistic",
                    {
                        "withheld": "",
                        "assessment": {"criteria": {"goal": {}, "line_1": {}}},
                    },
                )
            )
            self.assertEqual(0, batch.unusable)
            self.assertFalse(batch.record(failed, "failed-2", "realistic", entry))
            self.assertTrue(batch.record(failed, "failed-3", "realistic", entry))
            self.assertNotIn("failed", done)

    def test_a_capped_reply_retains_an_answer_that_arrived_whole(self) -> None:
        _config, _context, _live, _correction, reading = dr._runtime()
        raw = '{"goal":{"result":"unverifiable"},"claims":'
        raw += " " * (reading.REPLY_CAP_BYTES - len(raw))
        result, charges, done, said = self.run_batch([(raw, "ok")])
        self.assertGreater(result, 2)
        self.assertEqual(result, charges)
        self.assertEqual(result, sum(len(arms) for arms in done.values()))
        self.assertFalse(any("two consecutive" in line for line in said))


class ATaggedReadKeepsTheEarlierRunsOutput(unittest.TestCase):
    def test_a_tag_with_legacy_unbound_reads_cannot_receive_a_new_model(self) -> None:
        with (
            _Session() as s,
            mock.patch.object(dr, "_run_refusal", return_value=""),
            mock.patch.object(dr, "LEDGER_PATH", str(s.home / "spend.json")),
        ):
            home = _Home(s)
            out = s.home / "drift-replay" / "read-model.json"
            out.write_text(json.dumps({"cases": {home.ids[0]: {"realistic": {"charged": True}}}}))
            before = out.read_bytes()
            said: list[str] = []
            self.assertEqual(
                1,
                dr.read(
                    home=str(s.home),
                    dry_run=True,
                    tag="model",
                    arms=("realistic",),
                    cases=(home.ids[0],),
                    claude_model="claude-sonnet-5",
                    say=said.append,
                ),
            )
            self.assertTrue(any("new tag" in line for line in said))
            self.assertEqual(before, out.read_bytes())
            self.assertFalse((s.home / "spend.json").exists())

    def test_a_dry_plan_binds_the_selected_model(self) -> None:
        with (
            _Session() as s,
            mock.patch.object(dr, "_run_refusal", return_value=""),
            mock.patch.object(dr, "LEDGER_PATH", str(s.home / "spend.json")),
        ):
            home = _Home(s)
            self.assertEqual(
                0,
                dr.read(
                    home=str(s.home),
                    dry_run=True,
                    tag="model",
                    arms=("realistic",),
                    cases=(home.ids[0],),
                    claude_model="claude-sonnet-5",
                    say=lambda _m: None,
                ),
            )
            plan = lc._load(str(s.home / "drift-replay" / "plan-model.json"))
            self.assertEqual("claude-sonnet-5", plan["producer"]["selected_model"])
            self.assertIsNone(plan["producer"]["resolved_model"])
            self.assertFalse((s.home / "spend.json").exists())

    def test_a_real_run_cannot_change_the_planned_model_before_charging(self) -> None:
        with (
            _Session() as s,
            mock.patch.object(dr, "_run_refusal", return_value=""),
            mock.patch.object(dr, "LEDGER_PATH", str(s.home / "spend.json")),
        ):
            home = _Home(s)
            selected = (home.ids[0],)
            self.assertEqual(
                0,
                dr.read(
                    home=str(s.home),
                    dry_run=True,
                    tag="model",
                    cases=selected,
                    arms=("realistic",),
                    claude_model="claude-sonnet-5",
                    say=lambda _m: None,
                ),
            )
            import score_abstention  # noqa: PLC0415
            from compass_runtime import reading_route  # noqa: PLC0415 - runtime is installed above

            with (
                mock.patch.object(reading_route, "destination", return_value="Anthropic"),
                mock.patch.object(
                    score_abstention,
                    "verify_claude_binary",
                    side_effect=AssertionError("must refuse before launch"),
                ),
            ):
                said: list[str] = []
                self.assertEqual(
                    1,
                    dr.read(
                        home=str(s.home),
                        tag="model",
                        cases=selected,
                        arms=("realistic",),
                        claude_model="claude-sonnet-5-5",
                        say=said.append,
                    ),
                )
            self.assertTrue(any("dry-run" in line for line in said))
            self.assertFalse((s.home / "spend.json").exists())

    def test_dry_run_reports_adopted_source_coverage_without_charging(self) -> None:
        with (
            _Session() as s,
            mock.patch.object(dr, "_run_refusal", return_value=""),
            mock.patch.object(dr, "LEDGER_PATH", str(s.home / "spend.json")),
        ):
            home = _Home(s)
            said: list[str] = []
            code = dr.read(
                home=str(s.home),
                dry_run=True,
                tag="source",
                arms=("adopted",),
                cases=(f"{home.ids[0]}:adopted",),
                say=said.append,
            )
            self.assertEqual(0, code, said)
            self.assertIn("Adopted goal source: found 1 of 1; fallbacks 0.", said)
            self.assertFalse((s.home / "spend.json").exists())

    def test_a_narrowed_read_needs_a_tag_and_a_case_it_can_name(self) -> None:
        with _Session() as s, mock.patch.object(dr, "_run_refusal", return_value=""):
            home = _Home(s)
            said: list[str] = []
            self.assertEqual(
                1, dr.read(home=str(s.home), dry_run=True, cases=(home.ids[0],), say=said.append)
            )
            self.assertIn("--tag", said[-1])
            self.assertEqual(
                1, dr.read(home=str(s.home), dry_run=True, tag="Bad Tag", say=said.append)
            )
            self.assertEqual(
                1,
                dr.read(home=str(s.home), dry_run=True, tag="t", cases=("nope",), say=said.append),
            )
            self.assertIn("names 0 cases", said[-1])
            # Review A2: an arm the read does not cover is refused, not scored as refused later.
            self.assertEqual(
                1,
                dr.read(
                    home=str(s.home),
                    dry_run=True,
                    tag="t",
                    arms=("current",),
                    cases=(f"{home.ids[0]}:adopted",),
                    say=said.append,
                ),
            )
            self.assertIn("not one of the arms read", said[-1])

    def test_a_dry_run_plans_only_the_chosen_cuts_and_arms_beside_read_json(self) -> None:
        with (
            _Session() as s,
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.object(dr, "_run_refusal", return_value=""),
            mock.patch.object(dr, "LEDGER_PATH", os.path.join(tmp, "spend.json")),
        ):
            home = _Home(s)
            Path(home.paths["read"]).write_text('{"v": 1, "cases": {}}')
            before = Path(home.paths["read"]).read_text()
            chosen = f"{home.ids[0][:8]}:realistic"
            said: list[str] = []
            code = dr.read(
                home=str(s.home), dry_run=True, tag="rerun", cases=(chosen,), say=said.append
            )
            self.assertEqual(0, code, said)
            plan = json.loads(
                (Path(home.paths["dir"]) / "plan-rerun.json").read_text(encoding="utf-8")
            )
            self.assertEqual([f"{home.ids[0]}:realistic"], plan["selection"])
            self.assertEqual(1, plan["calls"])
            self.assertEqual(before, Path(home.paths["read"]).read_text())
            self.assertFalse(Path(home.paths["plan"]).exists())
            # The real run must match the plan: a different selection is refused before any call.
            # The destination is pinned, since a runner without the CLI refuses on that first.
            said.clear()
            other = f"{home.ids[-1]}:realistic"
            dr._runtime()  # puts compass_runtime on the path
            from compass_runtime import reading_route  # noqa: PLC0415

            with mock.patch.object(
                reading_route, "destination", return_value=reading_route.VENDORS["claude"]
            ):
                code = dr.read(home=str(s.home), tag="rerun", cases=(other,), say=said.append)
            self.assertEqual(1, code, said)

    def test_a_tagged_score_reads_its_own_file_and_leaves_unchosen_cuts_not_run(self) -> None:
        with _Session() as s:
            home = _Home(s)
            pair = f"{home.ids[0]}:realistic"
            (Path(home.paths["dir"]) / "plan-rerun.json").write_text(
                json.dumps({"arms": ["realistic"], "selection": [pair]})
            )
            (Path(home.paths["dir"]) / "read-rerun.json").write_text(
                json.dumps({"cases": {home.ids[0]: {"realistic": {"withheld": "idle-unknown"}}}})
            )
            readings, planned, out = dr._scored_read(home.paths, "rerun")
        self.assertIn(home.ids[0], readings)
        self.assertTrue(planned(home.ids[0], "realistic"))
        self.assertFalse(planned(home.ids[-1], "realistic"))
        self.assertFalse(planned(home.ids[0], "part"))
        self.assertTrue(out.endswith("results-rerun.json"))

    def test_the_ledger_floor_counts_every_read_file(self) -> None:
        with _Session() as s:
            home = _Home(s)
            (Path(home.paths["dir"]) / "read-a.json").write_text("{}")
            self.assertEqual(
                [home.paths["read"], os.path.join(home.paths["dir"], "read-a.json")],
                dr._read_files(home.paths),
            )


ARMS_AND_RESULTS = ("adopted", "current", "realistic", "departure", "not shown", "unsupported")


class ClaimsAreMarkedTrueOrFalseBlind(unittest.TestCase):
    def _flagged(self, s: _Session) -> _Home:
        home = _Home(s)
        cid = home.ids[0]
        facts = {
            "m1": {"at": _at(6), "type": "agent_message"},
            "u1": {"at": _at(8), "type": "user_message"},
        }
        Path(home.paths["read"]).write_text(
            json.dumps(
                {
                    "cases": {
                        cid: {
                            "adopted": _reading(
                                {"claims": {"result": "departure", "cites": ["m1", "u1"]}}, facts
                            ),
                            "current": _reading(
                                {"claims": {"result": dr.UNSUPPORTED, "cites": ["m1"]}}, facts
                            ),
                        }
                    }
                }
            )
        )
        return home

    def test_one_item_per_cut_and_claim_with_nothing_that_names_what_flagged_it(self) -> None:
        with _Session() as s:
            home = self._flagged(s)
            dr.export_claims(home=str(s.home), say=lambda _m: None)
            body = json.loads(Path(home.paths["claim_items"]).read_text())
        (item,) = body["items"]
        exported = json.dumps(body)
        for word in ARMS_AND_RESULTS:
            self.assertNotIn(word, exported)
        self.assertNotIn(home.ids[0], item["id"])
        # Review A3: the case id keys results.json, so naming it would name the outcome.
        self.assertNotIn(home.ids[0], exported)
        self.assertNotIn("case", item)
        self.assertEqual(4, item["claim_message"])  # the agent's drifted reply, #4

    def test_the_screen_shows_the_claim_and_what_followed_and_no_detector(self) -> None:
        with _Session() as s:
            self._flagged(s)
            dr.export_claims(home=str(s.home), say=lambda _m: None)
            shown: list[str] = []
            replies = iter(["n", "y", "it was reverted later"])
            dr.mark_claims(home=str(s.home), ask=lambda _p: next(replies), say=shown.append)
            marks = json.loads((s.home / "drift-replay" / "claim-marks.json").read_text())
            digest = json.loads(s.claim_digest.read_text())
            raw = (s.home / "drift-replay" / "claim-marks.json").read_bytes()
        screen = "\n".join(shown)
        self.assertIn("rewrote the exporter", screen)
        self.assertIn("Reverted the exporter", screen)
        for word in ARMS_AND_RESULTS:
            self.assertNotIn(word, screen)
        (mark,) = marks["marks"].values()
        self.assertEqual(
            {"true": "no", "visible": "yes", "reason": "it was reverted later"},
            {key: mark[key] for key in ("true", "visible", "reason")},
        )
        self.assertEqual("operator", mark["provenance"]["markers"][0]["marker"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), digest["marks_digest"])

    def test_each_flag_is_scored_on_the_claims_own_marks(self) -> None:
        cases = {
            ("departure", "no", "yes"): "right",
            ("departure", "yes", "no"): "wrong",
            ("departure", "unclear", "no"): "unclear",
            (dr.UNSUPPORTED, "no", "yes"): "right",
            (dr.UNSUPPORTED, "yes", "no"): "right",
            (dr.UNSUPPORTED, "yes", "yes"): "wrong",
            (dr.UNSUPPORTED, "yes", "unclear"): "unclear",
            (dr.UNSUPPORTED, "unclear", "yes"): "unclear",
        }
        for (result, true, visible), outcome in cases.items():
            with self.subTest(result=result, true=true, visible=visible):
                mark = {"true": true, "visible": visible, "reason": ""}
                self.assertEqual(outcome, dr.claim_outcome(result, mark))
        self.assertEqual("unmarked", dr.claim_outcome("departure", None))

    def test_the_score_reads_marks_only_when_they_hash_to_the_committed_digest(self) -> None:
        with _Session() as s, mock.patch.object(dr, "_in_repository", return_value=True):
            home = self._flagged(s)
            dr.export_claims(home=str(s.home), say=lambda _m: None)
            replies = iter(["n", "y", "reverted"])
            dr.mark_claims(home=str(s.home), ask=lambda _p: next(replies), say=lambda _m: None)
            sha = json.loads(s.claim_digest.read_text())["marks_digest"]
            readings = json.loads(Path(home.paths["read"]).read_text())["cases"]
            with mock.patch.object(
                lc, "committed_digest", return_value=lc.Committed(sha, "c", 0.0)
            ):
                truth, why = dr.claims_truth(home.paths, readings)
            with mock.patch.object(
                lc, "committed_digest", return_value=lc.Committed("0" * 64, "c", 0.0)
            ):
                stale, stale_why = dr.claims_truth(home.paths, readings)
            with mock.patch.object(lc, "committed_digest", return_value="not committed"):
                _none, uncommitted = dr.claims_truth(home.paths, readings)
        self.assertEqual("", why)
        self.assertEqual(1, truth["counts"]["adopted"]["departure"]["right"])
        self.assertEqual(1, truth["counts"]["current"][dr.UNSUPPORTED]["right"])
        self.assertEqual(
            ({}, "the local claim marks no longer hash to the committed digest"), (stale, stale_why)
        )
        self.assertTrue(uncommitted)
        committed = json.dumps(truth)
        self.assertNotIn(home.ids[0], committed)
        self.assertNotIn(SID, committed)


class TheScreenFindsAClaimDeepInALongReply(unittest.TestCase):
    """Review A1: a reply's records join into one message; the claim is its own record."""

    def test_a_claim_far_into_a_long_reply_is_shown_with_its_own_time(self) -> None:
        records = [
            _user(1, "Build the importer and nothing else."),
            _claude(10, "Working through the importer. " * 120),
            _claude(70, "ZZCLAIM the importer is built and every test passes."),
            _claude(80, "A closing note."),
            _stop(81),
            _user(90, "Thanks."),
        ]
        with _Session() as s:
            s.log.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
            messages = dr.conversation(str(s.log))
            n = dr._claim_message(messages, _at(70))
            assert n is not None
            self.assertGreater(messages[n].text.index("ZZCLAIM"), dr.CLAIM_TEXT_CHARS)
            shown: list[str] = []
            item = {"id": "x", "sid": SID, "cut": _at(81), "claim_at": _at(70), "claim_message": n}
            dr._claim_screen(item, "fixtures", "1/1", shown.append)
        screen = "\n".join(shown)
        claim = screen.split("THE CLAIM", 1)[1]
        self.assertIn("ZZCLAIM", claim.split("LATER IN THE SAME REPLY", 1)[0])
        self.assertIn(dt.datetime.fromtimestamp(_at(70), dt.UTC).strftime("%H:%M"), claim[:40])
        self.assertIn("A closing note.", screen)
        self.assertIn("EARLIER IN THE SAME REPLY", screen)


class TheReplayScrubsWhatTheRuntimeScrubs(unittest.TestCase):
    """The press hands the producer the values a shell call masked; a replay must as well."""

    SECRET = "FakePass99"  # noqa: S105

    def setUp(self) -> None:
        self.enterContext(mock.patch.object(campaign_guard, "active_campaign", return_value=None))

    def replay(self) -> tuple[list[Any], dict[str, Any]]:
        real_facts_at = dr.facts_at
        seen: list[Any] = []
        _config, _context, _live, _correction, reading = dr._runtime()
        real_produce = reading.produce

        def facts_at(*args: Any, **kwargs: Any) -> Any:
            facts, press = real_facts_at(*args, **kwargs)
            return facts, press._replace(masked_values=frozenset({self.SECRET}))

        def produce(*args: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("tool_output"))
            return real_produce(*args, **kwargs)

        reply = json.dumps(
            {
                "goal": {
                    "result": "not_reached",
                    "cites": [1],
                    "detail": f"The login still needs {self.SECRET} typed in.",
                }
            }
        )
        with (
            _Session() as s,
            mock.patch.object(dr, "facts_at", facts_at),
            mock.patch.object(reading, "produce", produce),
        ):
            home = _Home(s)
            ledger = dr.Ledger(str(s.home / "spend.json"))
            done: dict[str, Any] = {}
            dr._read_cases(
                home.body,
                home.paths,
                lambda _prompt, **_kw: (reply, "ok"),
                ledger,
                done,
                "fixtures",
                ("realistic",),
                dry_run=False,
                say=lambda _line: None,
            )
        return seen, done

    def test_the_press_values_reach_the_producer_the_replay_calls(self) -> None:
        seen, _done = self.replay()
        self.assertTrue(seen)
        for tool_output in seen:
            self.assertEqual(frozenset({self.SECRET}), tool_output.masked_values)

    def test_a_masked_value_in_a_stored_explanation_is_scrubbed(self) -> None:
        _seen, done = self.replay()
        explanations = [
            criterion["detail"]
            for arms in done.values()
            for entry in arms.values()
            for criterion in entry["assessment"]["criteria"].values()
        ]
        # Vacuous if no explanation survived to be scrubbed: the assertion below needs one.
        self.assertTrue(any(explanations), explanations)
        self.assertNotIn(self.SECRET, json.dumps(explanations))


if __name__ == "__main__":
    unittest.main()
