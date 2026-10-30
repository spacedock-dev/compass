"""Fixed eighth authority preserves four stopped campaigns and the original reseal."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abstention_ledger as ledger
import analyze_campaign as campaigns

if TYPE_CHECKING:
    from tests import test_analyze_campaign as fixtures
    from tests import test_qualification_zero_reseal as predecessors
else:
    import test_analyze_campaign as fixtures
    import test_qualification_zero_reseal as predecessors


class QualificationClauseIsolation(unittest.TestCase):
    def setUp(self) -> None:
        self.resealed = predecessors.QualificationZeroReseal()
        self.addCleanup(self.resealed.doCleanups)
        self.resealed.setUp()
        self.previous = self.resealed.complete()
        self.prior = self.resealed.prior
        self.root = self.prior.root
        self.native_fixture = self.prior.native_fixture
        native = self.prior.native(self.previous)
        for index, status in enumerate(("usable", "semantic-failed"), 1):
            charge = native.charge(f"{index:016x}", request_binding="a" * 64)
            native.settle(charge, "ok")
            native.finish_exposure(charge, status)
            if index == 1:
                self.previous.accept_batch(
                    "qualification", 0, fixtures.acceptance(self.previous, "qualification", 0)
                )
        self.old_state = copy.deepcopy(self.previous._state())
        self.native_prefix = ledger.read(str(self.native_fixture.ledger_path))["calls"]
        self.failed = {
            "verdict": "failed",
            "producer": "claude",
            "stopped": True,
            "counts": {"attempts": 2, "unusable_attempts": 0},
            "ledger_chain": ledger.chain_of(str(self.native_fixture.ledger_path)),
            "marks_digest": self.prior.key["marks_digest"],
            "inputs_digest": self.prior.key["inputs_digest"],
        }
        self.native_fixture.result_paths[6].write_text(json.dumps(self.failed))
        self.next_path = self.root / "clause-isolation.json"
        self.handoff_path = self.root / "clause-isolation-handoff.json"
        for name, path in (
            ("CLAUSE_ISOLATION_MANIFEST_PATH", self.next_path),
            ("CLAUSE_ISOLATION_HANDOFF_PATH", self.handoff_path),
        ):
            patch = mock.patch.object(campaigns, name, str(path), create=True)
            patch.start()
            self.addCleanup(patch.stop)
        self.manifest = copy.deepcopy(self.prior.manifest)
        self.manifest.update(phase="prepared")
        self.manifest.pop("activation_anchor", None)
        self.manifest["bindings"]["qualification"] = "8" * 64
        self.next_path.write_text(json.dumps(self.manifest))
        self.binding = ledger.digest(
            {k: v for k, v in self.manifest.items() if k not in ("phase", "activation_anchor")}
        )
        self.key = {"cases_digest": "8" * 64, "marks_digest": "9" * 64, "inputs_digest": "a" * 64}
        self.model_key = "b" * 64
        self.grant: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "previous": {
                k: self.failed[k] for k in ("ledger_chain", "marks_digest", "inputs_digest")
            },
            "next": self.key,
            "clause_isolation_allowance": {
                "previous_calls": 36,
                "additional_calls": 31,
                "carried_calls": 29,
                "renewed_calls": 2,
                "repeats": 3,
                "retry_calls": 1,
                "model_binding": self.model_key,
                "campaign_binding": self.binding,
            },
        }
        self.native_fixture.grant_paths[7].write_text(json.dumps(self.grant))
        self.assertTrue(
            hasattr(campaigns, "clause_isolation_parent_binding"),
            "finite clause ancestry helper is absent",
        )
        self.handoff: dict[str, Any] = {
            "v": 1,
            "verdict": "GO",
            "prepared_by": "synthetic-operator",
            "reviewed_by": "independent-synthetic-reviewer",
            "parent": campaigns.clause_isolation_parent_binding(self.previous),
            "successor": {
                "manifest_digest": self.binding,
                "grant_digest": ledger.digest(self.grant),
                "evidence": self.manifest["evidence"]["qualification"],
                "cases_digest": self.key["cases_digest"],
                "inputs_digest": self.key["inputs_digest"],
                "model_binding": self.model_key,
                "additional_calls": 31,
                "carried_calls": 29,
                "renewed_calls": 2,
                "shared_total": 247,
                "native_total": 67,
            },
        }
        self.write_handoff()

    def write_handoff(self) -> None:
        self.handoff_path.write_text(json.dumps(self.handoff))

    def current(self) -> Any:
        self.assertTrue(
            hasattr(campaigns, "ClauseIsolationCampaign"), "finite fourth successor is absent"
        )
        return campaigns.ClauseIsolationCampaign()

    def activate(self) -> Any:
        anchor = self.current().initialize_successor()
        self.manifest.update(phase="sealed", activation_anchor=anchor)
        self.next_path.write_text(json.dumps(self.manifest))
        return self.current()

    def native(self, current: Any) -> ledger.Ledger:
        return ledger.Ledger(
            str(self.native_fixture.ledger_path),
            cap=67,
            producer="claude",
            **self.key,
            model_binding=self.model_key,
            campaign=current,
        )

    def test_append_preserves_all_old_stops_native_prefix_and_accepted_opening(self) -> None:
        original_transition = self.resealed.transition.read_bytes()
        original_reseal = (self.previous.epoch_dir / "RESEAL.json").read_bytes()
        current = self.activate()
        native = self.native(current)
        self.assertEqual(67, native.cap)
        self.assertEqual(65, self.prior.native(self.previous).cap)
        self.assertEqual(self.old_state, self.previous._state())
        self.assertIn("qualification:0", self.previous._state()["accepted_batches"])
        with self.assertRaisesRegex(ledger.LedgerError, "stopped"):
            self.previous.reserve("qualification", "0000000000000003:r1", "a" * 64)
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        self.assertEqual(37, native.used())
        self.assertEqual(self.native_prefix, ledger.read(native.path)["calls"][:36])
        native.settle(charge, "ok")
        native.finish_exposure(charge, "usable")
        self.assertEqual(original_transition, self.resealed.transition.read_bytes())
        self.assertEqual(original_reseal, (self.previous.epoch_dir / "RESEAL.json").read_bytes())
        self.assertNotIn("RESEAL.json", current._epoch_entries())
        self.assertFalse(hasattr(current, "reseal_zero_charge"))
        with self.assertRaises(campaigns.AwaitingReviewError):
            native.charge("0000000000000002", request_binding="a" * 64)
        self.assertIsInstance(campaigns.active_campaign(), campaigns.ClauseIsolationCampaign)

    def test_current31_attempts_require_one_retry_and_hold_later_lanes(self) -> None:
        current = self.activate()
        native = self.native(current)
        slots = current.manifest["slots"]["qualification"]
        first = native.charge(slots[0].split(":")[0], request_binding="a" * 64)
        native.settle(first, "failed")
        for index, group in enumerate(current.manifest["batches"]["qualification"]):
            for slot in group:
                cid, repeat = slot.split(":r")
                charge = native.charge(
                    cid, repeat=int(repeat), retry=slot == slots[0], request_binding="a" * 64
                )
                native.settle(charge, "ok")
                native.finish_exposure(charge, "usable")
            current.accept_batch(
                "qualification", index, fixtures.acceptance(current, "qualification", index)
            )
        self.assertEqual(67, native.used())
        self.assertEqual(31, len(current._state()["calls"]))
        self.assertEqual(self.old_state, self.previous._state())
        with self.assertRaises(ledger.SpendCapError):
            native.charge("0000000000000001", request_binding="a" * 64)
        for lane in ("replay", "live"):
            with self.subTest(lane=lane), self.assertRaises(ledger.LedgerError):
                current.reserve(lane, current.manifest["slots"][lane][0], "a" * 64)

    def test_invalid_allowance_and_nonsemantic_previous_result_refuse(self) -> None:
        for field, bad in (
            ("previous_calls", 35),
            ("additional_calls", 32),
            ("carried_calls", 30),
            ("renewed_calls", 3),
            ("retry_calls", True),
            ("repeats", 4),
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.grant)
                body["clause_isolation_allowance"][field] = bad
                self.native_fixture.grant_paths[7].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.native_fixture.grant_paths[7].write_text(json.dumps(self.grant))
        for result_field, result_bad in (
            ("verdict", "blocked"),
            ("stopped", False),
            ("counts", {"attempts": 2, "unusable_attempts": 2}),
        ):
            with self.subTest(field=result_field):
                body = copy.deepcopy(self.failed)
                body[result_field] = result_bad
                self.native_fixture.result_paths[6].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.native_fixture.result_paths[6].write_text(json.dumps(self.failed))

    def test_duplicate_activation_missing_handoff_and_modified_epoch_refuse(self) -> None:
        current = self.activate()
        with self.assertRaises(ledger.LedgerError):
            current.initialize_successor()
        statepath = self.prior.prior.prior.account.state
        original = statepath.read_bytes()
        for epoch in range(4):
            with self.subTest(epoch=epoch):
                body = json.loads(original)
                body["epochs"][epoch]["state"]["calls"].clear()
                if epoch == 3:
                    body["epochs"][epoch]["state"]["genesis_nonce"] = "changed"
                statepath.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    current.reserve("qualification", "0000000000000001:r1", "a" * 64)
                statepath.write_bytes(original)
        self.handoff_path.unlink()
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()

    def test_new_semantic_failure_stops_without_refunding_any_epoch(self) -> None:
        current = self.activate()
        native = self.native(current)
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(charge, "ok")
        native.finish_exposure(charge, "semantic-failed")
        with self.assertRaisesRegex(ledger.LedgerError, "stopped"):
            native.charge("0000000000000002", request_binding="a" * 64)
        self.assertEqual(37, native.used())
        self.assertEqual(self.old_state, self.previous._state())

    def test_new_key_and_bound_campaign_required_for67(self) -> None:
        current = self.activate()
        native = self.native(current)
        native.campaign = None
        self.assertEqual(28, native.cap)
        self.grant["clause_isolation_allowance"]["campaign_binding"] = "8" * 64
        self.native_fixture.grant_paths[7].write_text(json.dumps(self.grant))
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)

    def test_eighth_allowance_cannot_move_to_an_arbitrary_generation(self) -> None:
        self.assertEqual(11, ledger.MAX_GRANTS)
        with self.assertRaises(ledger.LedgerError):
            ledger._clause_isolation_allowance(self.grant, 9)
        for field in (
            "closure_allowance",
            "successor_allowance",
            "login_resume_allowance",
            "clause_continuation_allowance",
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.grant)
                body[field] = body["clause_isolation_allowance"]
                self.native_fixture.grant_paths[7].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.native_fixture.grant_paths[7].write_text(json.dumps(self.grant))
        body = json.loads(self.native_fixture.grant_paths[6].read_text())
        body["clause_isolation_allowance"] = self.grant["clause_isolation_allowance"]
        self.native_fixture.grant_paths[6].write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            ledger.continuation()

    def test_native_prefix_and_ancestor_handoff_cannot_be_rewritten(self) -> None:
        current = self.activate()
        path = self.native_fixture.ledger_path
        original = path.read_bytes()
        for index in (0, 29, 31, 33, 35):
            with self.subTest(index=index):
                body = json.loads(original)
                body["calls"][index]["status"] = "charged"
                path.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    current.reserve("qualification", "0000000000000001:r1", "a" * 64)
                path.write_bytes(original)
        self.handoff["parent"]["first_epoch_digest"] = "0" * 64
        self.write_handoff()
        with self.assertRaises(ledger.LedgerError):
            self.current()

    def test_missing_opening_acceptance_is_not_replaced_by_new_authority(self) -> None:
        statepath = self.prior.prior.prior.account.state
        body = json.loads(statepath.read_bytes())
        body["epochs"][2]["state"]["accepted_batches"].clear()
        statepath.write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            self.current().initialize_successor()

    def test_missing_original_zero_reseal_refuses_without_new_charge(self) -> None:
        current = self.activate()
        path = self.previous.epoch_dir / "RESEAL.json"
        path.unlink()
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)
        self.assertEqual(36, len(ledger.read(str(self.native_fixture.ledger_path))["calls"]))

    def test_presence_of_partial_authority_never_falls_back_to_previous_epoch(self) -> None:
        self.next_path.unlink()
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()
        self.handoff_path.unlink()
        self.next_path.write_text(json.dumps(self.manifest))
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()

    def test_epoch_four_receipts_prevent_fallback_when_both_public_files_are_deleted(self) -> None:
        current = self.activate()
        self.next_path.unlink()
        self.handoff_path.unlink()
        self.assertTrue(current.epoch_dir.is_dir())
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()

    def test_two_new_unusable_attempts_stop_without_refunding_old_eight(self) -> None:
        current = self.activate()
        native = self.native(current)
        first = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(first, "failed")
        second = native.charge("0000000000000001", retry=True, request_binding="a" * 64)
        native.settle(second, "failed")
        with self.assertRaisesRegex(ledger.LedgerError, "two consecutive"):
            native.charge("0000000000000002", request_binding="a" * 64)
        self.assertEqual(38, native.used())
        self.assertEqual(self.old_state, self.previous._state())
