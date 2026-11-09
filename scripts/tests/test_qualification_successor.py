"""A fresh allowance preserves the stopped predecessor on an owned temporary account."""

from __future__ import annotations

import argparse
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
import score_abstention as scorer

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests import test_abstention_claude as native_models
    from tests import test_analyze_campaign as campaign_fixtures
    from tests import test_closure_qualification as native_fixtures
else:
    import test_abstention_claude as native_models
    import test_analyze_campaign as campaign_fixtures
    import test_closure_qualification as native_fixtures


class QualificationSuccessor(unittest.TestCase):
    def setUp(self) -> None:  # noqa: PLR0915 - arrange actual stopped native/shared predecessors
        self.native = native_fixtures.GrantFourAllowance()
        self.addCleanup(self.native.doCleanups)
        self.native.setUp()
        self.account = campaign_fixtures.CampaignReservations()
        self.addCleanup(self.account.doCleanups)
        self.account.setUp()
        self.root = self.account.root
        patch = mock.patch.object(campaigns, "QUALIFICATION_PATH", str(self.native.ledger_path))
        patch.start()
        self.addCleanup(patch.stop)
        slots = [f"{n:016x}:r{r}" for r in range(1, 4) for n in range(1, 11)]
        body = self.account.body
        body["slots"]["qualification"] = slots
        body["batches"]["qualification"] = [slots[:1], slots[1:10], slots[10:20], slots[20:]]
        body["requests"]["qualification"] = dict.fromkeys(slots, "a" * 64)
        body["historical"]["qualification"] = {
            "calls": 28,
            "sha256": self.account.sha(self.native.ledger_path),
            "calls_digest": ledger.digest(ledger.read(str(self.native.ledger_path))["calls"]),
        }
        body["order"] = ["qualification", "replay", "live"]
        body["deferred_slots"] = {
            "qualification": [],
            "replay": body["slots"]["replay"],
            "live": body["slots"]["live"],
        }
        for lane in ("replay", "live"):
            body["requests"][lane] = {}
            for field in ("bindings", "protocols", "evidence"):
                body[field][lane] = None
        self.account.activate()
        self.parent = self.account.campaign()
        self.native.campaign_key = self.parent.binding
        self.native.closure_grant()
        old = self.native.fifth()
        old.campaign = self.parent
        for n, status in ((1, "usable"), (2, "semantic-failed")):
            charge = old.charge(f"{n:016x}", request_binding="a" * 64)
            old.settle(charge, "ok")
            old.finish_exposure(charge, status)
            if n == 1:
                self.parent.accept_batch(
                    "qualification",
                    0,
                    campaign_fixtures.acceptance(self.parent, "qualification", 0),
                )
        self.original = self.parent._state()
        self.native_prefix = ledger.read(str(self.native.ledger_path))["calls"]
        failed = {
            "verdict": "failed",
            "producer": "claude",
            "ledger_chain": ledger.chain_of(str(self.native.ledger_path)),
            "marks_digest": self.native.new_key["marks_digest"],
            "inputs_digest": self.native.new_key["inputs_digest"],
        }
        self.native.result_paths[3].write_text(json.dumps(failed))
        self.next_path = self.root / "successor.json"
        self.handoff_path = self.root / "handoff.json"
        for name, path in (
            ("SUCCESSOR_MANIFEST_PATH", self.next_path),
            ("SUCCESSOR_HANDOFF_PATH", self.handoff_path),
        ):
            patch = mock.patch.object(campaigns, name, str(path), create=True)
            patch.start()
            self.addCleanup(patch.stop)
        self.next_manifest = copy.deepcopy(body)
        self.next_manifest["phase"] = "prepared"
        self.next_manifest.pop("activation_anchor", None)
        self.next_manifest["bindings"]["qualification"] = "b" * 64
        self.next_path.write_text(json.dumps(self.next_manifest))
        self.binding = ledger.digest(
            {k: v for k, v in self.next_manifest.items() if k not in ("phase", "activation_anchor")}
        )
        self.key = {"cases_digest": "b" * 64, "marks_digest": "c" * 64, "inputs_digest": "d" * 64}
        self.grant: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "previous": {
                "ledger_chain": failed["ledger_chain"],
                "marks_digest": failed["marks_digest"],
                "inputs_digest": failed["inputs_digest"],
            },
            "next": self.key,
            "successor_allowance": {
                "previous_calls": 30,
                "additional_calls": 31,
                "repeats": 3,
                "retry_calls": 1,
                "model_binding": self.native.model_key,
                "campaign_binding": self.binding,
            },
        }
        self.native.grant_paths[4].write_text(json.dumps(self.grant))
        self.handoff: dict[str, Any] = {
            "v": 1,
            "verdict": "GO",
            "prepared_by": "synthetic-operator",
            "reviewed_by": "independent-synthetic-reviewer",
            "parent": {
                "manifest_digest": self.parent.binding,
                "activation_anchor": body["activation_anchor"],
                "state_digest": ledger.digest(self.original),
                "calls": 2,
                "calls_digest": ledger.digest(self.original["calls"]),
                "stop_proof": {
                    "kind": "semantic-failed",
                    "classification_digest": ledger.digest(
                        json.loads(
                            (
                                self.parent.receipts
                                / (self.original["calls"][-1]["id"] + "-SETTLED.json")
                            ).read_text()
                        )
                    ),
                    "explicit_stop_digest": None,
                },
                "failed_result_digest": ledger.digest(failed),
                "native_calls": 30,
                "native_calls_digest": ledger.digest(self.native_prefix),
                "native_chain": failed["ledger_chain"],
            },
            "successor": {
                "manifest_digest": self.binding,
                "grant_digest": ledger.digest(self.grant),
                "evidence": self.next_manifest["evidence"]["qualification"],
                "cases_digest": self.key["cases_digest"],
                "inputs_digest": self.key["inputs_digest"],
                "model_binding": self.native.model_key,
                "additional_calls": 31,
                "shared_total": 241,
                "native_total": 61,
            },
        }
        self.write_handoff()

    def write_handoff(self) -> None:
        self.handoff_path.write_text(json.dumps(self.handoff))

    def successor(self) -> Any:
        self.assertTrue(hasattr(campaigns, "SuccessorCampaign"), "successor authority is absent")
        return campaigns.SuccessorCampaign()

    def activate(self) -> Any:
        anchor = self.successor().initialize_successor()
        self.next_manifest.update(phase="sealed", activation_anchor=anchor)
        self.next_path.write_text(json.dumps(self.next_manifest))
        return self.successor()

    def new_native(self, campaign: Any) -> ledger.Ledger:
        return ledger.Ledger(
            str(self.native.ledger_path),
            cap=61,
            producer="claude",
            **self.key,
            model_binding=self.native.model_key,
            campaign=campaign,
        )

    def test_append_keeps_original_stop_and_fresh_opening_review(self) -> None:
        current = self.activate()
        self.assertEqual(
            self.original, {k: v for k, v in self.parent._state().items() if k != "epochs"}
        )
        with self.assertRaisesRegex(ledger.LedgerError, "stopped"):
            self.parent.reserve(
                "qualification", self.account.body["slots"]["qualification"][2], "a" * 64
            )
        self.assertEqual({}, current._state().get("accepted_batches", {}))
        native = self.new_native(current)
        self.assertEqual(61, native.cap)
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        self.assertEqual(31, native.used())
        self.assertEqual(1, len(current._state()["calls"]))
        self.assertEqual(2, len(self.parent._state()["calls"]))
        self.assertEqual(
            self.native_prefix, ledger.read(str(self.native.ledger_path))["calls"][:30]
        )
        native.settle(charge, "ok")
        native.finish_exposure(charge, "usable")
        with self.assertRaises(campaigns.AwaitingReviewError):
            native.charge("0000000000000002", request_binding="a" * 64)
        current.accept_batch(
            "qualification", 0, campaign_fixtures.acceptance(current, "qualification", 0)
        )
        native.charge("0000000000000002", request_binding="a" * 64)

    def test_actual_derived_stop_shape_has_no_invented_stop_receipt(self) -> None:
        self.assertNotIn("stop", self.original)
        self.assertFalse((self.parent.receipts / "STOP.json").exists())
        try:
            current = self.activate()
        except ledger.LedgerError as error:
            self.fail(f"an intact settled semantic failure must be continuable: {error}")
        self.assertEqual([], current._state()["calls"])
        self.assertNotIn("stop", self.parent._state())
        self.assertFalse((self.parent.receipts / "STOP.json").exists())

    def test_already_explicit_stop_is_preserved_and_bound(self) -> None:
        self.parent.stop("semantic-failed")
        self.original = self.parent._state()
        self.handoff["parent"]["state_digest"] = ledger.digest(self.original)
        self.handoff["parent"]["stop_proof"]["explicit_stop_digest"] = ledger.digest(
            json.loads((self.parent.receipts / "STOP.json").read_text())
        )
        self.write_handoff()
        current = self.activate()
        self.assertEqual([], current._state()["calls"])
        self.assertEqual("semantic-failed", self.parent._state()["stop"])

    def test_native_charged_wrapper_and_cli_ceiling_select_successor(self) -> None:
        scorer._runtime()
        from compass_runtime import observer  # noqa: PLC0415 - actual native module admission

        binding = native_models.BINDING
        prompt = "Owned synthetic qualification request; no provider transport."
        request = campaigns.request_digest(
            prompt,
            {k: binding.get(k) for k in scorer.BINDING_KEYS},
            campaigns.runtime_source_digest(Path(observer.__file__).parent),
            8192,
        )
        self.next_manifest["requests"]["qualification"]["0000000000000001:r1"] = request
        self.next_path.write_text(json.dumps(self.next_manifest))
        self.binding = ledger.digest(
            {k: v for k, v in self.next_manifest.items() if k not in ("phase", "activation_anchor")}
        )
        self.grant["successor_allowance"]["campaign_binding"] = self.binding
        self.native.grant_paths[4].write_text(json.dumps(self.grant))
        self.handoff["successor"]["manifest_digest"] = self.binding
        self.handoff["successor"]["grant_digest"] = ledger.digest(self.grant)
        self.write_handoff()
        current = self.activate()
        native = self.new_native(current)
        sends: list[str] = []

        def delegate(text: str, *, output_cap_bytes: int) -> tuple[str, str]:
            self.assertEqual(31, native.used())
            self.assertEqual(1, len(current._state()["calls"]))
            self.assertEqual(8192, output_cap_bytes)
            sends.append(text)
            return "synthetic response", "ok"

        charged = scorer._Charged(native, "0000000000000001", delegate, binding=binding)
        self.assertEqual(("synthetic response", "ok"), charged(prompt, output_cap_bytes=8192))
        self.assertEqual([prompt], sends)
        self.assertIsInstance(campaigns.active_campaign(), campaigns.SuccessorCampaign)
        args = argparse.Namespace(
            score=True,
            probe_argv=False,
            producer="claude",
            max_calls=61,
            resume=False,
            claude_reading_model=None,
        )
        with mock.patch.object(ledger, "home_moved", return_value=False):
            self.assertEqual("", scorer._argument_refusal(args))
            args.max_calls = 62
            self.assertNotEqual("", scorer._argument_refusal(args))

    def test_init_is_explicit_once_and_missing_review_refuses(self) -> None:
        with self.assertRaises(ledger.LedgerError):
            self.successor().reserve("qualification", "0000000000000001:r1", "a" * 64)
        self.handoff_path.unlink()
        with self.assertRaises(ledger.LedgerError):
            self.successor().initialize_successor()
        self.write_handoff()
        current = self.activate()
        with self.assertRaises(ledger.LedgerError):
            current.initialize_successor()

    def test_fresh_failure_and_orphan_stop_without_parent_refund(self) -> None:
        current = self.activate()
        charge = current.reserve("qualification", "0000000000000001:r1", "a" * 64)
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000002:r1", "a" * 64)
        current.settle(charge, "semantic-failed")
        current.stop("semantic-failed")
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000002:r1", "a" * 64)
        self.assertEqual("semantic-failed", self.parent._state()["calls"][-1]["status"])

    def test_parent_projection_native_prefix_and_handoff_tamper_refuse(self) -> None:
        current = self.activate()
        original = self.account.state.read_bytes()
        mutations: tuple[Callable[[dict[str, Any]], None], ...] = (
            lambda b: b.update(unreviewed=True),
            lambda b: b["epochs"].append(copy.deepcopy(b["epochs"][0])),
            lambda b: b["calls"][0].update(at=123.0),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                body = json.loads(original)
                mutate(body)
                self.account.state.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    current.reserve("qualification", "0000000000000001:r1", "a" * 64)
                self.account.state.write_bytes(original)
        self.handoff["reviewed_by"] = "changed-review"
        self.write_handoff()
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)

    def test_wrong_native_allowance_and_old_key_do_not_gain_61(self) -> None:
        current = self.activate()
        self.assertEqual(28, self.native.fourth(cap=61).cap)
        self.assertEqual(59, self.native.fifth().cap)
        with self.assertRaises(ledger.LedgerError):
            self.native.fifth().charge("a" * 16, request_binding="a" * 64)
        self.grant["successor_allowance"]["previous_calls"] = 29
        self.native.grant_paths[4].write_text(json.dumps(self.grant))
        with self.assertRaises(ledger.LedgerError):
            self.new_native(current).charge("0000000000000001", request_binding="a" * 64)

    def test_grant_five_exact_counts_and_generation_are_validated_without_a_campaign(self) -> None:
        original = copy.deepcopy(self.grant)
        for field, wrong in (
            ("previous_calls", 29),
            ("additional_calls", 32),
            ("retry_calls", True),
            ("repeats", 4),
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(original)
                body["successor_allowance"][field] = wrong
                self.native.grant_paths[4].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.native.grant_paths[4].write_text(json.dumps(original))
        prior = json.loads(self.native.grant_paths[3].read_text())
        prior["successor_allowance"] = original["successor_allowance"]
        self.native.grant_paths[3].write_text(json.dumps(prior))
        with self.assertRaises(ledger.LedgerError):
            ledger.continuation()

    def test_reviewed_hashes_cannot_replace_the_actual_native_shared_parent_join(self) -> None:
        body = json.loads(self.native.ledger_path.read_text())
        body["calls"][29]["campaign_charge"] = body["calls"][28]["campaign_charge"]
        self.native.ledger_path.write_text(json.dumps(body))
        self.handoff["parent"]["native_calls_digest"] = ledger.digest(body["calls"])
        self.write_handoff()
        with self.assertRaises(ledger.LedgerError):
            self.successor().initialize_successor()

    def test_actual_31_fresh_charges_and_one_retry_leave_30_prefix_and_held_208(self) -> None:
        current = self.activate()
        native = self.new_native(current)
        slots = self.next_manifest["slots"]["qualification"]
        opening = native.charge(slots[0].split(":")[0], request_binding="a" * 64)
        native.settle(opening, "unavailable")
        for index, group in enumerate(self.next_manifest["batches"]["qualification"]):
            for slot in group:
                cid, repeat = slot.split(":r")
                charge = native.charge(
                    cid, repeat=int(repeat), retry=slot == slots[0], request_binding="a" * 64
                )
                native.settle(charge, "ok")
                native.finish_exposure(charge, "usable")
            current.accept_batch(
                "qualification",
                index,
                campaign_fixtures.acceptance(current, "qualification", index),
            )
        current.accept("qualification", campaign_fixtures.acceptance(current, "qualification"))
        self.assertEqual(61, native.used())
        self.assertEqual(31, len(current._state()["calls"]))
        self.assertEqual(241, 2 + len(current._state()["calls"]) + 190 + 18)
        self.assertEqual(
            self.native_prefix, ledger.read(str(self.native.ledger_path))["calls"][:30]
        )
        with self.assertRaises(ledger.SpendCapError):
            native.charge("0000000000000001", request_binding="a" * 64)
        for lane in ("replay", "live"):
            with self.subTest(lane=lane), self.assertRaises(ledger.LedgerError):
                current.reserve(lane, self.next_manifest["slots"][lane][0], "a" * 64)

    def test_each_mutable_binding_and_stray_epoch_entry_refuses_before_charge(self) -> None:
        current = self.activate()
        parent_manifest = self.account.manifest.read_bytes()
        body = json.loads(parent_manifest)
        body["protocols"]["qualification"] = "changed-source"
        self.account.manifest.write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)
        self.account.manifest.write_bytes(parent_manifest)
        native_bytes = self.native.ledger_path.read_bytes()
        body = json.loads(native_bytes)
        body["calls"][29]["status"] = "failed"
        self.native.ledger_path.write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)
        self.native.ledger_path.write_bytes(native_bytes)
        current.epoch_dir.joinpath("unreviewed.json").write_text("{}")
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)
