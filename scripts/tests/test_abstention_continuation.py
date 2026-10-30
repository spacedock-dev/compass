"""A fresh qualification may follow a failed one without erasing its spend."""

from __future__ import annotations

import json
import re
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import IO, Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abstention_ledger
import mark_abstention
import score_abstention


class _OneFailedResult(unittest.TestCase):
    """A ledger holding the original packet's 13 charges and its committed failed result."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.ledger_path = self.root / "spend.json"
        self.summary_path = self.root / "failed.json"
        # The repository's own names, in a throwaway directory: the bound and the
        # gap checks read these names, so a fixture under other names hides them.
        self.grant_paths = tuple(
            self.root / ("claude-continuation.json" if k == 1 else f"claude-continuation-{k}.json")
            for k in range(1, abstention_ledger.MAX_GRANTS + 1)
        )
        self.result_paths = tuple(
            self.root
            / (
                "claude-results-continuation.json"
                if k == 1
                else f"claude-results-continuation-{k}.json"
            )
            for k in range(1, abstention_ledger.MAX_GRANTS + 1)
        )
        self.grant_path, self.grant_2_path, self.grant_3_path = self.grant_paths[:3]
        self.new_summary_path, self.third_summary_path, self.fourth_summary_path = (
            self.result_paths[:3]
        )
        self.old_marks = "a" * 64
        self.old_inputs = "b" * 64
        self.new_cases = "c" * 64
        self.new_marks = "d" * 64
        self.new_inputs = "e" * 64
        patches = (
            mock.patch.object(abstention_ledger, "LEDGER_PATH", str(self.ledger_path)),
            mock.patch.object(abstention_ledger, "CLAUDE_SUMMARY_PATH", str(self.summary_path)),
            mock.patch.object(
                abstention_ledger, "CONTINUATION_PATHS", tuple(map(str, self.grant_paths))
            ),
            mock.patch.object(
                abstention_ledger,
                "CONTINUATION_SUMMARY_PATHS",
                tuple(map(str, self.result_paths)),
            ),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        old = abstention_ledger.Ledger(
            str(self.ledger_path),
            cap=19,
            marks_digest=self.old_marks,
            inputs_digest=self.old_inputs,
            producer="claude",
        )
        for _ in range(13):
            old.settle(old.charge("1" * 16), "ok")
        self.prior = abstention_ledger.chain_of(str(self.ledger_path))
        self.summary_path.write_text(
            json.dumps(
                {
                    "verdict": "failed",
                    "producer": "claude",
                    "ledger_chain": self.prior,
                    "marks_digest": self.old_marks,
                    "inputs_digest": self.old_inputs,
                }
            )
        )

    def grant(self, phase: str = "sealed") -> None:
        new = {"cases_digest": self.new_cases}
        if phase == "sealed":
            new.update(marks_digest=self.new_marks, inputs_digest=self.new_inputs)
        self.grant_path.write_text(
            json.dumps(
                {
                    "v": 1,
                    "phase": phase,
                    "previous": {
                        "ledger_chain": self.prior,
                        "marks_digest": self.old_marks,
                        "inputs_digest": self.old_inputs,
                    },
                    "next": new,
                }
            )
        )

    def fresh(self) -> abstention_ledger.Ledger:
        return abstention_ledger.Ledger(
            str(self.ledger_path),
            cap=19,
            marks_digest=self.new_marks,
            inputs_digest=self.new_inputs,
            producer="claude",
            cases_digest=self.new_cases,
        )


class ACommittedPacketIsNamedByItsGrantAndChainedByItsResult(_OneFailedResult):
    """`committed_packet`: the prior-packet vouch's anchor (orchestrator, 2026-10-30)."""

    def test_only_a_sealed_grants_case_set_with_a_chained_result_is_committed(self) -> None:
        self.assertEqual(0, mark_abstention.committed_packet(self.new_cases))
        self.grant("marking")
        self.assertEqual(0, mark_abstention.committed_packet(self.new_cases))
        self.grant("sealed")
        # Sealed, but packet 1 has no committed result yet.
        self.assertEqual(0, mark_abstention.committed_packet(self.new_cases))
        fresh = self.fresh()
        fresh.settle(fresh.charge("2" * 16), "ok")
        chained: dict[str, Any] = {
            "verdict": "failed",
            "producer": "claude",
            "ledger_chain": abstention_ledger.chain_of(str(self.ledger_path)),
            "marks_digest": self.new_marks,
            "inputs_digest": self.new_inputs,
        }
        self.new_summary_path.write_text(json.dumps(chained))
        self.assertEqual(1, mark_abstention.committed_packet(self.new_cases))
        self.assertEqual(0, mark_abstention.committed_packet("f" * 64))
        unchained = {**chained, "ledger_chain": {**chained["ledger_chain"], "head": "0" * 64}}
        self.new_summary_path.write_text(json.dumps(unchained))
        self.assertEqual(0, mark_abstention.committed_packet(self.new_cases))


class AFailedQualificationKeepsItsLedger(_OneFailedResult):
    def test_a_second_packet_needs_a_sealed_grant_before_any_call(self) -> None:
        fresh = self.fresh()
        self.assertNotEqual("", fresh.check())
        self.grant("marking")
        self.assertNotEqual("", fresh.check())
        self.grant("sealed")
        self.assertEqual("", fresh.check())
        fresh.charge("2" * 16)
        self.assertEqual(14, fresh.used())
        self.assertTrue(abstention_ledger.begins_with(str(self.ledger_path), self.prior))

    def test_the_old_prefix_cannot_be_deleted_or_redigested(self) -> None:
        self.grant()
        body = abstention_ledger.read(str(self.ledger_path))
        body["calls"][0]["marks_digest"] = self.new_marks
        self.ledger_path.write_text(json.dumps(body))
        fresh = self.fresh()
        self.assertNotEqual("", fresh.check())
        with self.assertRaises(abstention_ledger.LedgerError):
            fresh.charge("2" * 16)

    def test_a_new_key_cannot_change_after_its_first_charge(self) -> None:
        self.grant()
        fresh = self.fresh()
        fresh.charge("2" * 16)
        self.new_marks = "f" * 64
        self.grant()
        changed = self.fresh()
        self.assertNotEqual("", changed.check())
        with self.assertRaises(abstention_ledger.LedgerError):
            changed.charge("2" * 16)

    def test_the_grant_names_the_case_set_as_well_as_the_scoring_digests(self) -> None:
        self.grant()
        fresh = self.fresh()
        fresh.cases_digest = "f" * 64
        self.assertNotEqual("", fresh.check())
        with self.assertRaises(abstention_ledger.LedgerError):
            fresh.charge("2" * 16)

    def test_the_global_cap_counts_both_packets(self) -> None:
        self.grant()
        fresh = self.fresh()
        for _ in range(6):
            fresh.charge("2" * 16)
        self.assertEqual(19, fresh.used())
        with self.assertRaises(abstention_ledger.SpendCapError):
            fresh.charge("2" * 16)

    def test_marking_is_scoped_to_new_cases_and_stops_after_the_first_call(self) -> None:
        self.grant("marking")
        self.assertFalse(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.new_cases)
        )
        self.assertTrue(mark_abstention._ledger_refusal(continuation=True, cases_digest="f" * 64))
        self.grant("sealed")
        self.fresh().charge("2" * 16)
        self.assertTrue(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.new_cases)
        )

    def test_a_grant_sealed_while_marking_cannot_save_late_answers(self) -> None:
        case = {"id": "2" * 16}
        body = {"v": 5, "cases": [case]}
        cases = self.root / "fresh-cases.json"
        marks = self.root / "fresh-marks.json"
        cases.write_text(json.dumps(body))
        self.new_cases = mark_abstention.cases_digest(body)
        self.grant("marking")

        def seal(*_args: object) -> dict[str, str]:
            self.grant("sealed")
            return {"goal": "abstain"}

        with (
            mock.patch.object(mark_abstention, "CASES_PATH", str(cases)),
            mock.patch.object(mark_abstention, "MARKS_PATH", str(marks)),
            mock.patch.object(mark_abstention, "_refuse_mismatch", return_value=False),
            mock.patch.object(mark_abstention, "_show_mark_case"),
            mock.patch.object(mark_abstention, "_mark_one", side_effect=seal),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(1, mark_abstention.mark(continuation=True))
        self.assertFalse(marks.exists())

    def test_a_new_charge_waits_until_the_final_mark_write_finishes(self) -> None:
        case = {"id": "2" * 16}
        body = {"v": 5, "cases": [case]}
        cases = self.root / "fresh-cases.json"
        marks = self.root / "fresh-marks.json"
        cases.write_text(json.dumps(body))
        self.new_cases = mark_abstention.cases_digest(body)
        self.grant("marking")
        native_write = mark_abstention._write
        native_lock = abstention_ledger._lock_file
        attempted = threading.Event()
        completed = threading.Event()
        errors: list[Exception] = []
        threads: list[threading.Thread] = []
        locks = 0

        def traced_lock(handle: IO[bytes]) -> None:
            nonlocal locks
            locks += 1
            if locks == 2:
                attempted.set()
            native_lock(handle)

        def charge() -> None:
            try:
                self.fresh().charge("2" * 16)
            except Exception as error:  # noqa: BLE001 - surface a worker failure to the test
                errors.append(error)
            finally:
                completed.set()

        def writing(path: str, value: dict[str, object]) -> None:
            self.grant("sealed")
            worker = threading.Thread(target=charge)
            threads.append(worker)
            worker.start()
            self.assertTrue(attempted.wait(1))
            self.assertFalse(completed.is_set())
            native_write(path, value)

        with (
            mock.patch.object(mark_abstention, "CASES_PATH", str(cases)),
            mock.patch.object(mark_abstention, "MARKS_PATH", str(marks)),
            mock.patch.object(mark_abstention, "_refuse_mismatch", return_value=False),
            mock.patch.object(mark_abstention, "_show_mark_case"),
            mock.patch.object(mark_abstention, "_mark_one", return_value={"goal": "abstain"}),
            mock.patch.object(mark_abstention, "_write", side_effect=writing),
            mock.patch.object(abstention_ledger, "_lock_file", side_effect=traced_lock),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(0, mark_abstention.mark(continuation=True))
        for worker in threads:
            # Windows' blocking file lock may retry at one-second intervals.
            worker.join(15)
        self.assertTrue(completed.is_set())
        self.assertEqual([], errors)
        self.assertTrue(marks.exists())

    def test_the_marking_flag_cannot_turn_into_a_freeze_or_reset(self) -> None:
        with mock.patch.object(mark_abstention, "freeze") as frozen, mock.patch("builtins.print"):
            self.assertEqual(
                2, mark_abstention.main(["--continue-mark", "--freeze", str(self.root / "spec")])
            )
            self.assertEqual(2, mark_abstention.main(["--continue-mark", "--reset"]))
        frozen.assert_not_called()

    def test_the_failed_result_cannot_be_overwritten_by_a_continuation(self) -> None:
        self.grant()
        self.assertFalse(score_abstention._chain_holds(self.fresh(), str(self.summary_path)))
        self.assertTrue(score_abstention._chain_holds(self.fresh(), str(self.new_summary_path)))
        alias = self.root / "alias.json"
        alias.symlink_to(self.new_summary_path)
        self.assertFalse(score_abstention._chain_holds(self.fresh(), str(alias)))

    def test_a_symlinked_new_result_still_cannot_overwrite_the_failed_result(self) -> None:
        original = self.summary_path.read_bytes()
        self.new_summary_path.symlink_to(self.summary_path)
        with (
            mock.patch.object(score_abstention, "local_results", return_value={}),
            mock.patch.object(score_abstention, "render", return_value=[]),
            mock.patch("builtins.print"),
        ):
            score_abstention._write_halves(
                {},
                {"verdict": "passed"},
                results_path=str(self.root / "local.json"),
                summary_path=str(self.new_summary_path),
            )
        self.assertEqual(original, self.summary_path.read_bytes())
        self.assertEqual("passed", json.loads(self.new_summary_path.read_text())["verdict"])

    def test_the_failed_result_cannot_alias_the_new_result(self) -> None:
        original = self.summary_path.read_bytes()
        self.new_summary_path.write_bytes(original)
        self.summary_path.unlink()
        self.summary_path.symlink_to(self.new_summary_path)
        self.grant()
        self.assertFalse(score_abstention._chain_holds(self.fresh(), str(self.new_summary_path)))

    def test_a_review_file_that_grows_after_stat_still_has_a_read_bound(self) -> None:
        path = self.root / "growing.json"
        path.write_bytes(b"x" * 100)
        forged = mock.Mock(st_mode=stat.S_IFREG, st_size=0)
        with (
            mock.patch("os.fstat", return_value=forged),
            self.assertRaises(abstention_ledger.LedgerError),
        ):
            abstention_ledger._review_json(str(path), "growing", cap=10)

    def test_both_results_accept_only_the_granted_old_prefix_and_new_suffix(self) -> None:
        self.grant()
        self.fresh().charge("2" * 16)
        old_summary = json.loads(self.summary_path.read_text())
        new_summary = {
            "producer": "claude",
            "marks_digest": self.new_marks,
            "inputs_digest": self.new_inputs,
            "ledger_chain": abstention_ledger.chain_of(str(self.ledger_path)),
        }
        self.assertEqual("", score_abstention._ledger_drift(old_summary))
        self.assertEqual("", score_abstention._ledger_drift(new_summary))
        body = abstention_ledger.read(str(self.ledger_path))
        body["calls"][-1]["marks_digest"] = "f" * 64
        self.ledger_path.write_text(json.dumps(body))
        self.assertNotEqual("", score_abstention._ledger_drift(old_summary))
        self.assertNotEqual("", score_abstention._ledger_drift(new_summary))

    def test_marking_a_new_packet_does_not_make_the_failed_result_stale(self) -> None:
        self.grant("marking")
        old_summary = json.loads(self.summary_path.read_text())
        self.assertEqual("", score_abstention._ledger_drift(old_summary))


class _TwoFailedResults(_OneFailedResult):
    """The original's 13 charges and the first continuation's 5, both committed as failed."""

    def setUp(self) -> None:
        super().setUp()
        self.grant("sealed")
        second = self.fresh()
        for _ in range(5):
            second.settle(second.charge("2" * 16), "ok")
        self.second_chain = abstention_ledger.chain_of(str(self.ledger_path))
        self.new_summary_path.write_text(json.dumps({
            "verdict": "failed", "producer": "claude", "ledger_chain": self.second_chain,
            "marks_digest": self.new_marks, "inputs_digest": self.new_inputs,
        }))  # fmt: skip
        self.third_cases, self.third_marks, self.third_inputs = "1" * 64, "2" * 64, "3" * 64

    def grant_2(self, phase: str = "sealed", **previous: str) -> None:
        nxt = {"cases_digest": self.third_cases}
        if phase == "sealed":
            nxt.update(marks_digest=self.third_marks, inputs_digest=self.third_inputs)
        self.grant_2_path.write_text(json.dumps({
            "v": 1, "phase": phase,
            "previous": {"ledger_chain": self.second_chain, "marks_digest": self.new_marks,
                         "inputs_digest": self.new_inputs, **previous},
            "next": nxt,
        }))  # fmt: skip

    def third(self) -> abstention_ledger.Ledger:
        return abstention_ledger.Ledger(
            str(self.ledger_path), cap=23, marks_digest=self.third_marks,
            inputs_digest=self.third_inputs, producer="claude", cases_digest=self.third_cases,
        )  # fmt: skip


class ASecondFailedContinuationChainsAThirdPacket(_TwoFailedResults):
    """After the first continuation also failed, a second grant may follow it (DRC-4666)."""

    def test_a_third_packet_charges_only_under_a_sealed_second_grant(self) -> None:
        self.assertNotEqual("", self.third().check())
        self.grant_2("marking")
        self.assertNotEqual("", self.third().check())
        self.grant_2("sealed")
        self.assertEqual("", self.third().check())
        self.third().charge("3" * 16)
        self.assertEqual(19, self.third().used())
        self.assertTrue(abstention_ledger.begins_with(str(self.ledger_path), self.second_chain))

    def test_the_cap_counts_all_three_packets(self) -> None:
        self.grant_2()
        third = self.third()
        for _ in range(5):
            third.charge("3" * 16)
        self.assertEqual(23, third.used())
        with self.assertRaises(abstention_ledger.SpendCapError):
            third.charge("3" * 16)

    def test_a_second_grant_needs_the_first_and_must_follow_it(self) -> None:
        self.grant_2()
        self.grant_path.unlink()
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()
        self.grant("sealed")
        self.grant_2(marks_digest="f" * 64)
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_a_second_grant_needs_the_first_sealed(self) -> None:
        self.grant("marking")
        self.grant_2()
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_the_first_grants_next_key_must_be_the_seconds_previous(self) -> None:
        self.grant_2()
        body = json.loads(self.grant_path.read_text())
        body["next"]["marks_digest"] = "f" * 64
        self.grant_path.write_text(json.dumps(body))
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_marking_the_third_packet_leaves_both_failures_unstale_until_a_charge(self) -> None:
        self.grant_2("marking")
        first = json.loads(self.summary_path.read_text())
        second = json.loads(self.new_summary_path.read_text())
        for summary in (first, second):
            self.assertEqual("", score_abstention._ledger_drift(summary))
        stray = abstention_ledger.read(str(self.ledger_path))
        stray["calls"].append({**stray["calls"][-1], "id": "9" * 32})
        self.ledger_path.write_text(json.dumps(stray))
        for summary in (first, second):
            self.assertNotEqual("", score_abstention._ledger_drift(summary))

    def test_each_segment_must_carry_its_own_key(self) -> None:
        # The hash chain catches a re-digested charge; this catches a genuine chain
        # whose charges ran under another packet's key than the grant names.
        a, b, c = ("a" * 64, "b" * 64), ("c" * 64, "d" * 64), ("e" * 64, "f" * 64)
        grant = {"segments": [[2, list(a)], [3, list(b)]]}

        def call(pair: tuple[str, str]) -> dict[str, str]:
            return {"marks_digest": pair[0], "inputs_digest": pair[1]}

        self.assertTrue(abstention_ledger.follows([call(a), call(a), call(b), call(c)], grant, c))
        for calls in ([call(a), call(b), call(b), call(c)],
                      [call(a), call(a), call(a), call(c)],
                      [call(a), call(a), call(b), call(b)]):  # fmt: skip
            with self.subTest(calls=calls):
                self.assertFalse(abstention_ledger.follows(calls, grant, c))

    def test_a_second_grant_needs_the_first_continuation_to_have_failed(self) -> None:
        self.grant_2()
        self.new_summary_path.write_text(json.dumps({
            **json.loads(self.new_summary_path.read_text()), "verdict": "passed"}))  # fmt: skip
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_every_earlier_packet_keeps_its_own_key(self) -> None:
        self.grant_2()
        for index in (0, 15):
            with self.subTest(call=index):
                self.grant_2()
                body = abstention_ledger.read(str(self.ledger_path))
                saved = body["calls"][index]["marks_digest"]
                body["calls"][index]["marks_digest"] = self.third_marks
                self.ledger_path.write_text(json.dumps(body))
                self.assertNotEqual("", self.third().check())
                body["calls"][index]["marks_digest"] = saved
                self.ledger_path.write_text(json.dumps(body))
        self.assertEqual("", self.third().check())

    def test_marking_the_third_packet_is_scoped_and_stops_after_its_first_call(self) -> None:
        self.grant_2("marking")
        self.assertFalse(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.third_cases)
        )
        self.assertTrue(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.new_cases)
        )
        self.grant_2("sealed")
        self.third().charge("3" * 16)
        self.assertTrue(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.third_cases)
        )

    def test_the_third_result_has_its_own_files_and_reads_both_failures(self) -> None:
        self.grant_2()
        with mock.patch.object(score_abstention, "HOME", str(self.root)):
            self.assertEqual(
                str(self.third_summary_path), score_abstention.summary_path_for("claude", None)
            )
            self.assertTrue(
                score_abstention.results_path_for("claude").endswith(
                    "abstention-claude-continuation-2-results.json"
                )
            )
        self.assertFalse(score_abstention._chain_holds(self.third(), str(self.new_summary_path)))
        self.assertTrue(score_abstention._chain_holds(self.third(), str(self.third_summary_path)))
        # Rewriting one of the first continuation's charges breaks its committed chain.
        body = abstention_ledger.read(str(self.ledger_path))
        body["calls"][14]["id"] = "f" * 32
        self.ledger_path.write_text(json.dumps(body))
        self.assertFalse(score_abstention._chain_holds(self.third(), str(self.third_summary_path)))

    def test_every_result_accepts_only_its_granted_segment(self) -> None:
        self.grant_2()
        self.third().charge("3" * 16)
        first = json.loads(self.summary_path.read_text())
        second = json.loads(self.new_summary_path.read_text())
        third = {"producer": "claude", "marks_digest": self.third_marks,
                 "inputs_digest": self.third_inputs,
                 "ledger_chain": abstention_ledger.chain_of(str(self.ledger_path))}  # fmt: skip
        for summary in (first, second, third):
            self.assertEqual("", score_abstention._ledger_drift(summary))
        body = abstention_ledger.read(str(self.ledger_path))
        body["calls"][-1]["marks_digest"] = self.new_marks
        self.ledger_path.write_text(json.dumps(body))
        for summary in (first, second, third):
            self.assertNotEqual("", score_abstention._ledger_drift(summary))


class AThirdFailedContinuationChainsAFourthPacket(_TwoFailedResults):
    """The owner's 2026-10-01 ruling: one more run past the ceiling, as a third grant.

    The world is the repository's: 13, 18 and 23 calls behind three committed
    failed results, and a fourth packet charging under a third grant.
    """

    def setUp(self) -> None:
        super().setUp()
        self.grant_2("sealed")
        third = self.third()
        for _ in range(5):
            third.settle(third.charge("3" * 16), "ok")
        self.third_chain = abstention_ledger.chain_of(str(self.ledger_path))
        self.third_summary_path.write_text(json.dumps({
            "verdict": "failed", "producer": "claude", "ledger_chain": self.third_chain,
            "marks_digest": self.third_marks, "inputs_digest": self.third_inputs,
        }))  # fmt: skip
        self.fourth_cases, self.fourth_marks, self.fourth_inputs = "4" * 64, "5" * 64, "6" * 64

    def grant_3(self, phase: str = "sealed", **previous: str) -> None:
        nxt = {"cases_digest": self.fourth_cases}
        if phase == "sealed":
            nxt.update(marks_digest=self.fourth_marks, inputs_digest=self.fourth_inputs)
        self.grant_3_path.write_text(json.dumps({
            "v": 1, "phase": phase,
            "previous": {"ledger_chain": self.third_chain, "marks_digest": self.third_marks,
                         "inputs_digest": self.third_inputs, **previous},
            "next": nxt,
        }))  # fmt: skip

    def fourth(self, cap: int = 28) -> abstention_ledger.Ledger:
        return abstention_ledger.Ledger(
            str(self.ledger_path), cap=cap, marks_digest=self.fourth_marks,
            inputs_digest=self.fourth_inputs, producer="claude", cases_digest=self.fourth_cases,
        )  # fmt: skip

    def summaries(self) -> list[Any]:
        return [
            json.loads(path.read_text())
            for path in (self.summary_path, self.new_summary_path, self.third_summary_path)
        ]

    def test_the_world_holds_three_failed_chains_of_13_18_and_23(self) -> None:
        chains = [summary["ledger_chain"] for summary in self.summaries()]
        self.assertEqual([13, 18, 23], [chain["calls"] for chain in chains])

    def test_a_fourth_packet_charges_only_under_a_sealed_third_grant(self) -> None:
        self.assertNotEqual("", self.fourth().check())
        self.grant_3("marking")
        self.assertNotEqual("", self.fourth().check())
        self.grant_3("sealed")
        self.assertEqual("", self.fourth().check())
        self.fourth().charge("4" * 16)
        self.assertEqual(24, self.fourth().used())
        grant = abstention_ledger.continuation()
        assert grant is not None
        self.assertEqual([13, 18, 23], [end for end, _pair in grant["segments"]])

    def test_the_cap_of_28_counts_all_four_packets(self) -> None:
        self.assertEqual(28, abstention_ledger.MAX_CALLS)
        self.grant_3()
        fourth = self.fourth(cap=99)
        self.assertEqual(28, fourth.cap)
        for _ in range(5):
            fourth.charge("4" * 16)
        self.assertEqual(28, fourth.used())
        with self.assertRaises(abstention_ledger.SpendCapError):
            fourth.charge("4" * 16)

    def test_a_third_grant_with_the_second_missing_is_refused(self) -> None:
        self.grant_3()
        self.grant_2_path.unlink()
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()
        self.assertNotEqual("", self.fourth().check())

    def test_a_third_grant_needs_the_second_sealed(self) -> None:
        self.grant_2("marking")
        self.grant_3()
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_a_marking_second_grant_carrying_the_handoff_key_is_still_refused(self) -> None:
        # The key comparison alone passes here: only the phase says the owner never sealed it.
        self.grant_2("sealed")
        body = json.loads(self.grant_2_path.read_text())
        body["phase"] = "marking"
        self.grant_2_path.write_text(json.dumps(body))
        self.grant_3()
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_the_second_grants_next_key_must_be_the_thirds_previous(self) -> None:
        self.grant_3()
        body = json.loads(self.grant_2_path.read_text())
        body["next"]["inputs_digest"] = "f" * 64
        self.grant_2_path.write_text(json.dumps(body))
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_a_third_grant_must_bind_the_second_continuations_result(self) -> None:
        self.grant_3(marks_digest="f" * 64)
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_a_gap_in_the_grants_is_refused(self) -> None:
        self.grant_3()
        self.grant_paths[4].write_text(self.grant_3_path.read_text())
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_a_grant_past_the_named_bound_is_refused(self) -> None:
        self.grant_3()
        beyond = self.root / f"claude-continuation-{abstention_ledger.MAX_GRANTS + 1}.json"
        beyond.write_text(self.grant_3_path.read_text())
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation()

    def test_the_chain_names_eleven_grants_and_refuses_a_twelfth(self) -> None:
        # The tenth continuation and its one funded retry (owner, 2026-10-30): eleven
        # names, each the pattern's own, and the twelfth a stray however well formed.
        self.assertEqual(11, abstention_ledger.MAX_GRANTS)
        self.grant_3()
        eleventh = self.root / "claude-continuation-11.json"
        eleventh.write_text(self.grant_3_path.read_text())
        # A name inside the bound is read, so an eleventh after a third is a gap, not a stray.
        with self.assertRaisesRegex(abstention_ledger.LedgerError, "has no grant 4 before it"):
            abstention_ledger.continuation()
        eleventh.unlink()
        twelfth = self.root / "claude-continuation-12.json"
        twelfth.write_text(self.grant_3_path.read_text())
        with self.assertRaisesRegex(abstention_ledger.LedgerError, "claude-continuation-12"):
            abstention_ledger.continuation()
        with self.assertRaises(abstention_ledger.LedgerError):
            abstention_ledger.continuation(generation=12)

    def test_a_grant_under_a_name_the_pattern_never_writes_is_refused(self) -> None:
        # Silently ignored, a misnamed third grant would leave the second active and
        # select an earlier generation's packet without anyone noticing.
        self.grant_3()
        body = self.grant_3_path.read_text()
        self.grant_3_path.unlink()
        for name in ("claude-continuation-0.json", "claude-continuation-1.json",
                     "claude-continuation-02.json", "claude-continuation-3a.json",
                     "claude-continuation-.json", "claude-continuation3.json"):  # fmt: skip
            with self.subTest(name=name):
                stray = self.root / name
                stray.write_text(body)
                with self.assertRaisesRegex(abstention_ledger.LedgerError, re.escape(name)):
                    abstention_ledger.continuation()
                stray.unlink()
        # With every stray gone, the second grant is the active one again.
        grant = abstention_ledger.continuation()
        assert grant is not None
        self.assertEqual([13, 18], [end for end, _pair in grant["segments"]])

    def test_every_earlier_result_reads_not_stale(self) -> None:
        self.grant_3("marking")
        for summary in self.summaries():
            self.assertEqual("", score_abstention._ledger_drift(summary))
        self.grant_3("sealed")
        self.fourth().charge("4" * 16)
        fourth = {"producer": "claude", "marks_digest": self.fourth_marks,
                  "inputs_digest": self.fourth_inputs,
                  "ledger_chain": abstention_ledger.chain_of(str(self.ledger_path))}  # fmt: skip
        for summary in (*self.summaries(), fourth):
            self.assertEqual("", score_abstention._ledger_drift(summary))
        body = abstention_ledger.read(str(self.ledger_path))
        body["calls"][-1]["marks_digest"] = self.third_marks
        self.ledger_path.write_text(json.dumps(body))
        for summary in (*self.summaries(), fourth):
            self.assertNotEqual("", score_abstention._ledger_drift(summary))

    def test_every_earlier_packet_keeps_its_own_key_under_the_third_grant(self) -> None:
        self.grant_3()
        body = abstention_ledger.read(str(self.ledger_path))
        for index in (0, 15, 20):
            with self.subTest(call=index):
                saved = body["calls"][index]["inputs_digest"]
                body["calls"][index]["inputs_digest"] = self.fourth_inputs
                self.ledger_path.write_text(json.dumps(body))
                self.assertNotEqual("", self.fourth().check())
                body["calls"][index]["inputs_digest"] = saved
                self.ledger_path.write_text(json.dumps(body))
        self.assertEqual("", self.fourth().check())

    def test_marking_the_fourth_packet_is_scoped_and_stops_after_its_first_call(self) -> None:
        self.grant_3("marking")
        self.assertFalse(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.fourth_cases)
        )
        self.assertTrue(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.third_cases)
        )
        self.grant_3("sealed")
        self.fourth().charge("4" * 16)
        self.assertTrue(
            mark_abstention._ledger_refusal(continuation=True, cases_digest=self.fourth_cases)
        )

    def test_the_fourth_result_has_its_own_files_and_reads_every_failure(self) -> None:
        self.grant_3()
        with mock.patch.object(score_abstention, "HOME", str(self.root)):
            self.assertEqual(
                str(self.fourth_summary_path), score_abstention.summary_path_for("claude", None)
            )
            self.assertEqual(
                str(self.root / "abstention-claude-continuation-3-results.json"),
                score_abstention.results_path_for("claude"),
            )
        for earlier in (self.summary_path, self.new_summary_path, self.third_summary_path):
            with self.subTest(earlier=earlier.name):
                self.assertFalse(score_abstention._chain_holds(self.fourth(), str(earlier)))
        self.assertTrue(score_abstention._chain_holds(self.fourth(), str(self.fourth_summary_path)))
        # Rewriting one of the second continuation's charges breaks its committed chain.
        body = abstention_ledger.read(str(self.ledger_path))
        body["calls"][20]["id"] = "f" * 32
        self.ledger_path.write_text(json.dumps(body))
        self.assertFalse(
            score_abstention._chain_holds(self.fourth(), str(self.fourth_summary_path))
        )

    def test_a_fresh_fourth_run_never_replaces_a_written_fourth_result(self) -> None:
        self.grant_3()
        self.fourth().charge("4" * 16)
        self.fourth_summary_path.write_text(json.dumps({
            "verdict": "failed", "producer": "claude",
            "ledger_chain": abstention_ledger.chain_of(str(self.ledger_path)),
        }))  # fmt: skip
        with mock.patch("builtins.print"):
            self.assertTrue(
                score_abstention._overwrites(self.fourth(), None, str(self.fourth_summary_path))
            )


class TheGenerationsAreNamedOnePattern(unittest.TestCase):
    """Grant k and its packet's result files, read from the module's own tuples."""

    def test_grant_and_result_names_follow_the_generation(self) -> None:
        grants = [Path(p).name for p in abstention_ledger.CONTINUATION_PATHS]
        results = [Path(p).name for p in abstention_ledger.CONTINUATION_SUMMARY_PATHS]
        self.assertEqual(11, abstention_ledger.MAX_GRANTS)
        self.assertEqual("claude-continuation-11.json", grants[-1])
        self.assertEqual([abstention_ledger.MAX_GRANTS] * 2, [len(grants), len(results)])
        self.assertEqual(
            ["claude-continuation.json", "claude-continuation-2.json",
             "claude-continuation-3.json"], grants[:3],
        )  # fmt: skip
        self.assertEqual(
            ["claude-results-continuation.json", "claude-results-continuation-2.json",
             "claude-results-continuation-3.json"], results[:3],
        )  # fmt: skip
        self.assertEqual("claude-results.json", Path(abstention_ledger.result_path(0)).name)
        self.assertEqual(
            "claude-results-continuation-3.json", Path(abstention_ledger.result_path(3)).name
        )
        with mock.patch.object(score_abstention, "HOME", "/h"):
            self.assertEqual(
                ["abstention-claude-results.json", "abstention-claude-continuation-results.json",
                 "abstention-claude-continuation-3-results.json"],
                [Path(score_abstention.local_results_path(k)).name for k in (0, 1, 3)],
            )  # fmt: skip


if __name__ == "__main__":
    unittest.main()
