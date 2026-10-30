"""Fixed ninth authority measures all exposures without changing older semantic stops."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abstention_ledger as ledger
import analyze_campaign as campaigns

if TYPE_CHECKING:
    from tests import test_analyze_campaign as fixtures
    from tests import test_qualification_clause_isolation as predecessors
else:
    import test_analyze_campaign as fixtures
    import test_qualification_clause_isolation as predecessors


class QualificationConditionalPriority(unittest.TestCase):
    template: ClassVar[Any]
    snapshot_dirs: ClassVar[tuple[Path, Path]]
    path_bindings: ClassVar[list[tuple[Any, str, Any]]]
    template_files: ClassVar[dict[str, bytes]]

    @classmethod
    def setUpClass(cls) -> None:
        # Construct the real paid predecessor once; every test clones distinct
        # files and still revalidates all receipts with production validators.
        cls.template = predecessors.QualificationClauseIsolation()
        cls.addClassCleanup(cls.template.doCleanups)
        cls.template.setUp()
        old = cls.template.activate()
        native = cls.template.native(old)
        for index, status in enumerate(("usable", "semantic-failed"), 1):
            charge = native.charge(f"{index:016x}", request_binding="a" * 64)
            native.settle(charge, "ok")
            native.finish_exposure(charge, status)
            if index == 1:
                old.accept_batch("qualification", 0, fixtures.acceptance(old, "qualification", 0))
        failed = {
            "verdict": "failed",
            "producer": "claude",
            "stopped": True,
            "counts": {"attempts": 2, "unusable_attempts": 0},
            "ledger_chain": ledger.chain_of(native.path),
            "marks_digest": cls.template.key["marks_digest"],
            "inputs_digest": cls.template.key["inputs_digest"],
        }
        cls.template.native_fixture.result_paths[7].write_text(json.dumps(failed))
        old._state()
        cls.snapshot_dirs = (cls.template.root, cls.template.native_fixture.root)
        cls.path_bindings = [
            (module, name, getattr(module, name))
            for module, names in (
                (campaigns, [name for name in vars(campaigns) if name.endswith("_PATH")]),
                (
                    ledger,
                    [
                        "LEDGER_PATH",
                        "CLAUDE_SUMMARY_PATH",
                        "CONTINUATION_PATHS",
                        "CONTINUATION_SUMMARY_PATHS",
                    ],
                ),
            )
            for name in names
        ]
        cls.template_files = cls._template_bytes()

    @classmethod
    def _template_bytes(cls) -> dict[str, bytes]:
        return {
            str(path): path.read_bytes()
            for root in cls.snapshot_dirs
            for path in root.rglob("*")
            if path.is_file()
        }

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "account"
        self.native_root = Path(folder.name) / "native"
        for before, after in zip(self.snapshot_dirs, (self.root, self.native_root), strict=True):
            shutil.copytree(before, after)

        def relocated(value: Any) -> Any:
            if isinstance(value, tuple):
                return tuple(relocated(item) for item in value)
            if isinstance(value, str):
                for before, after in zip(
                    self.snapshot_dirs, (self.root, self.native_root), strict=True
                ):
                    value = value.replace(str(before), str(after))
            return value

        for module, name, value in self.path_bindings:
            patch = mock.patch.object(module, name, relocated(value))
            patch.start()
            self.addCleanup(patch.stop)
        self.previous = campaigns.ClauseIsolationCampaign()
        self.old_state = copy.deepcopy(self.previous._state())
        assert isinstance(campaigns.QUALIFICATION_PATH, str)
        assert isinstance(campaigns.LEDGER_PATH, str)
        self.native_path = Path(campaigns.QUALIFICATION_PATH)
        self.statepath = Path(campaigns.LEDGER_PATH)
        self.native_prefix = ledger.read(str(self.native_path))["calls"]
        self.failed = json.loads(Path(ledger.result_path(8)).read_bytes())
        self.native_fixture = SimpleNamespace(
            ledger_path=self.native_path,
            grant_paths=tuple(map(Path, ledger.CONTINUATION_PATHS)),
            result_paths=tuple(map(Path, ledger.CONTINUATION_SUMMARY_PATHS)),
        )
        self.next_path = self.root / "conditional-priority.json"
        self.handoff_path = self.root / "conditional-priority-handoff.json"
        for name, path in (
            ("CONDITIONAL_PRIORITY_MANIFEST_PATH", self.next_path),
            ("CONDITIONAL_PRIORITY_HANDOFF_PATH", self.handoff_path),
        ):
            patch = mock.patch.object(campaigns, name, str(path), create=True)
            patch.start()
            self.addCleanup(patch.stop)
        self.manifest = copy.deepcopy(self.previous.manifest)
        self.manifest.update(phase="prepared")
        self.manifest.pop("activation_anchor", None)
        self.manifest["bindings"]["qualification"] = "c" * 64
        self.next_path.write_text(json.dumps(self.manifest))
        self.binding = ledger.digest(
            {k: v for k, v in self.manifest.items() if k not in ("phase", "activation_anchor")}
        )
        self.key = {"cases_digest": "c" * 64, "marks_digest": "d" * 64, "inputs_digest": "e" * 64}
        self.model_key = "f" * 64
        self.grant: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "previous": {
                k: self.failed[k] for k in ("ledger_chain", "marks_digest", "inputs_digest")
            },
            "next": self.key,
            "conditional_priority_allowance": {
                "previous_calls": 38,
                "additional_calls": 31,
                "carried_calls": 29,
                "renewed_calls": 2,
                "repeats": 3,
                "retry_calls": 1,
                "model_binding": self.model_key,
                "campaign_binding": self.binding,
            },
        }
        self.native_fixture.grant_paths[8].write_text(json.dumps(self.grant))
        self.assertTrue(
            hasattr(campaigns, "conditional_priority_parent_binding"),
            "finite clause ancestry helper is absent",
        )
        self.handoff: dict[str, Any] = {
            "v": 1,
            "verdict": "GO",
            "prepared_by": "synthetic-operator",
            "reviewed_by": "independent-synthetic-reviewer",
            "parent": campaigns.conditional_priority_parent_binding(self.previous),
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
                "shared_total": 249,
                "native_total": 69,
            },
        }
        self.write_handoff()

    def tearDown(self) -> None:
        self.assertEqual(
            self.template_files, self._template_bytes(), "a cloned test changed its shared template"
        )

    @staticmethod
    def measurement(current: Any, batch: int) -> dict[str, Any]:
        proof = fixtures.acceptance(current, "qualification", batch)
        group = current.manifest["batches"]["qualification"][batch]
        own = [c for c in current._state()["calls"] if c["slot"] in group]
        latest = {c["slot"]: c["status"] for c in own}
        proof.update(
            verdict="measured",
            measured_slots=sum(latest.get(slot) in ("usable", "semantic-failed") for slot in group),
            usable_slots=sum(latest.get(slot) == "usable" for slot in group),
            semantic_failures=sum(c["status"] == "semantic-failed" for c in own),
        )
        return proof

    def write_handoff(self) -> None:
        self.handoff_path.write_text(json.dumps(self.handoff))

    def current(self) -> Any:
        self.assertTrue(
            hasattr(campaigns, "ConditionalPriorityCampaign"), "finite fifth successor is absent"
        )
        return campaigns.ConditionalPriorityCampaign()

    def activate(self) -> Any:
        anchor = self.current().initialize_successor()
        self.manifest.update(phase="sealed", activation_anchor=anchor)
        self.next_path.write_text(json.dumps(self.manifest))
        return self.current()

    def native(self, current: Any) -> ledger.Ledger:
        return ledger.Ledger(
            str(self.native_fixture.ledger_path),
            cap=69,
            producer="claude",
            **self.key,
            model_binding=self.model_key,
            campaign=current,
        )

    def test_append_preserves_all_old_stops_native_prefix_and_accepted_opening(self) -> None:
        original_transition = (
            self.previous.epoch_dir.parent / "3" / "TRANSITION.json"
        ).read_bytes()
        original_reseal = (self.previous.epoch_dir.parent / "3" / "RESEAL.json").read_bytes()
        current = self.activate()
        native = self.native(current)
        self.assertEqual(69, native.cap)
        self.assertEqual(
            67,
            ledger.Ledger(
                str(self.native_path),
                cap=69,
                producer="claude",
                **self.template.key,
                model_binding=self.template.model_key,
                campaign=self.previous,
            ).cap,
        )
        self.assertEqual(self.old_state, self.previous._state())
        self.assertIn("qualification:0", self.previous._state()["accepted_batches"])
        with self.assertRaisesRegex(ledger.LedgerError, "stopped"):
            self.previous.reserve("qualification", "0000000000000003:r1", "a" * 64)
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        self.assertEqual(39, native.used())
        self.assertEqual(self.native_prefix, ledger.read(native.path)["calls"][:38])
        native.settle(charge, "ok")
        native.finish_exposure(charge, "usable")
        self.assertEqual(
            original_transition,
            (self.previous.epoch_dir.parent / "3" / "TRANSITION.json").read_bytes(),
        )
        self.assertEqual(
            original_reseal, (self.previous.epoch_dir.parent / "3" / "RESEAL.json").read_bytes()
        )
        self.assertNotIn("RESEAL.json", current._epoch_entries())
        self.assertFalse(hasattr(current, "reseal_zero_charge"))
        with self.assertRaises(campaigns.AwaitingReviewError):
            native.charge("0000000000000002", request_binding="a" * 64)
        self.assertIsInstance(campaigns.active_campaign(), campaigns.ConditionalPriorityCampaign)

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
                native.finish_exposure(charge, "semantic-failed")
            current.review_batch("qualification", index, self.measurement(current, index))
        self.assertEqual(69, native.used())
        self.assertEqual(31, len(current._state()["calls"]))
        self.assertEqual(
            30, sum(c["status"] == "semantic-failed" for c in current._state()["calls"])
        )
        with self.assertRaises(ledger.LedgerError):
            current.accept("qualification", fixtures.acceptance(current, "qualification"))
        self.assertFalse((current.receipts / "qualification-ACCEPTED.json").exists())
        self.assertEqual(self.old_state, self.previous._state())
        with self.assertRaises(ledger.SpendCapError):
            native.charge("0000000000000001", request_binding="a" * 64)
        for lane in ("replay", "live"):
            with self.subTest(lane=lane), self.assertRaises(ledger.LedgerError):
                current.reserve(lane, current.manifest["slots"][lane][0], "a" * 64)

    def test_invalid_allowance_and_nonsemantic_previous_result_refuse(self) -> None:
        for field, bad in (
            ("previous_calls", 37),
            ("additional_calls", 32),
            ("carried_calls", 30),
            ("renewed_calls", 3),
            ("retry_calls", True),
            ("repeats", 4),
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.grant)
                body["conditional_priority_allowance"][field] = bad
                self.native_fixture.grant_paths[8].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.native_fixture.grant_paths[8].write_text(json.dumps(self.grant))
        for result_field, result_bad in (
            ("verdict", "blocked"),
            ("stopped", False),
            ("counts", {"attempts": 2, "unusable_attempts": 2}),
        ):
            with self.subTest(field=result_field):
                body = copy.deepcopy(self.failed)
                body[result_field] = result_bad
                self.native_fixture.result_paths[7].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.native_fixture.result_paths[7].write_text(json.dumps(self.failed))

    def test_duplicate_activation_missing_handoff_and_modified_epoch_refuse(self) -> None:
        current = self.activate()
        with self.assertRaises(ledger.LedgerError):
            current.initialize_successor()
        statepath = self.statepath
        original = statepath.read_bytes()
        for epoch in range(5):
            with self.subTest(epoch=epoch):
                body = json.loads(original)
                body["epochs"][epoch]["state"]["calls"].clear()
                if epoch == 4:
                    body["epochs"][epoch]["state"]["genesis_nonce"] = "changed"
                statepath.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    current.reserve("qualification", "0000000000000001:r1", "a" * 64)
                statepath.write_bytes(original)
        self.handoff_path.unlink()
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()

    def test_semantic_failure_is_measured_without_retry_or_fake_pass(self) -> None:
        current = self.activate()
        native = self.native(current)
        first = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(first, "ok")
        native.finish_exposure(first, "semantic-failed")
        self.assertFalse(current.stop_on_semantic_failure)
        self.assertTrue(self.previous.stop_on_semantic_failure)
        try:
            native.charge("0000000000000002", request_binding="a" * 64)
        except campaigns.AwaitingReviewError:
            pass
        except ledger.LedgerError as error:
            self.fail(f"a semantic grade must await review rather than stop measurement: {error}")
        else:
            self.fail("the next batch launched without its independent measurement review")
        with self.assertRaises(ledger.LedgerError):
            native.charge("0000000000000001", retry=True, request_binding="a" * 64)
        current.review_batch("qualification", 0, self.measurement(current, 0))
        second = native.charge("0000000000000002", request_binding="a" * 64)
        native.settle(second, "ok")
        native.finish_exposure(second, "usable")
        with self.assertRaises(ledger.LedgerError):
            current.accept("qualification", fixtures.acceptance(current, "qualification"))
        self.assertEqual(
            ["semantic-failed", "usable"], [c["status"] for c in current._state()["calls"]]
        )
        self.assertEqual(40, native.used())
        self.assertEqual(self.old_state, self.previous._state())

    def test_measurement_review_must_report_failure_counts_without_pass(self) -> None:
        current = self.activate()
        native = self.native(current)
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(charge, "ok")
        native.finish_exposure(charge, "semantic-failed")
        proof = self.measurement(current, 0)
        self.assertEqual(
            (1, 0, 1), (proof["measured_slots"], proof["usable_slots"], proof["semantic_failures"])
        )
        for field, bad in (
            ("verdict", "passed"),
            ("semantic_failures", 0),
            ("usable_slots", 1),
            ("measured_slots", 0),
            ("review_digest", ""),
        ):
            altered = {**proof, field: bad}
            with self.subTest(field=field), self.assertRaises(ledger.LedgerError):
                current.review_batch("qualification", 0, altered)
        current.review_batch("qualification", 0, proof)
        self.assertEqual(
            "measured",
            json.loads((current.receipts / "qualification-0-BATCH.json").read_bytes())["verdict"],
        )

    def test_technical_protection_latch_refuses_retry_after_paid_unusable_attempt(self) -> None:
        current = self.activate()
        native = self.native(current)
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(charge, "failed")
        current.stop("protection-failed")
        with self.assertRaisesRegex(ledger.LedgerError, "stopped"):
            native.charge("0000000000000001", retry=True, request_binding="a" * 64)
        self.assertEqual(39, native.used())
        self.assertEqual("protection-failed", current._state()["stop"])

    def test_semantic_policy_preserves_actual_technical_sequence(self) -> None:
        for status in ("charged", "coverage-failed", "protection-failed"):
            with self.subTest(status=status), self.assertRaises(ledger.LedgerError):
                campaigns.ConditionalPriorityCampaign._stop([{"status": status}])
        campaigns.ConditionalPriorityCampaign._stop(
            [{"status": "unusable"}, {"status": "semantic-failed"}, {"status": "unusable"}]
        )
        with self.assertRaises(ledger.LedgerError):
            campaigns.ConditionalPriorityCampaign._stop(
                [{"status": "semantic-failed"}, {"status": "unusable"}, {"status": "unusable"}]
            )

    def test_new_key_and_bound_campaign_required_for69(self) -> None:
        current = self.activate()
        native = self.native(current)
        native.campaign = None
        self.assertEqual(28, native.cap)
        self.grant["conditional_priority_allowance"]["campaign_binding"] = "8" * 64
        self.native_fixture.grant_paths[8].write_text(json.dumps(self.grant))
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)

    def test_ninth_allowance_cannot_move_to_an_arbitrary_generation(self) -> None:
        self.assertEqual(11, ledger.MAX_GRANTS)
        with self.assertRaises(ledger.LedgerError):
            ledger._conditional_priority_allowance(self.grant, 10)
        for field in (
            "closure_allowance",
            "successor_allowance",
            "login_resume_allowance",
            "clause_continuation_allowance",
            "clause_isolation_allowance",
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.grant)
                body[field] = body["conditional_priority_allowance"]
                self.native_fixture.grant_paths[8].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.native_fixture.grant_paths[8].write_text(json.dumps(self.grant))
        body = json.loads(self.native_fixture.grant_paths[7].read_text())
        body["conditional_priority_allowance"] = self.grant["conditional_priority_allowance"]
        self.native_fixture.grant_paths[7].write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            ledger.continuation()

    def test_native_prefix_and_ancestor_handoff_cannot_be_rewritten(self) -> None:
        current = self.activate()
        path = self.native_fixture.ledger_path
        original = path.read_bytes()
        for index in (0, 29, 31, 33, 35, 37):
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
        statepath = self.statepath
        body = json.loads(statepath.read_bytes())
        body["epochs"][3]["state"]["accepted_batches"].clear()
        statepath.write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            self.current().initialize_successor()

    def test_missing_original_zero_reseal_refuses_without_new_charge(self) -> None:
        current = self.activate()
        path = self.previous.epoch_dir.parent / "3" / "RESEAL.json"
        path.unlink()
        with self.assertRaises(ledger.LedgerError):
            current.reserve("qualification", "0000000000000001:r1", "a" * 64)
        self.assertEqual(38, len(ledger.read(str(self.native_fixture.ledger_path))["calls"]))

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

    def test_two_new_unusable_attempts_stop_without_refunding_old_ten(self) -> None:
        current = self.activate()
        native = self.native(current)
        first = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(first, "failed")
        second = native.charge("0000000000000001", retry=True, request_binding="a" * 64)
        native.settle(second, "failed")
        with self.assertRaisesRegex(ledger.LedgerError, "two consecutive"):
            native.charge("0000000000000002", request_binding="a" * 64)
        self.assertEqual(40, native.used())
        self.assertEqual(self.old_state, self.previous._state())
