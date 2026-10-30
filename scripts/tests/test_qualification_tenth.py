"""The fixed tenth authority: the completed ninth measurement stays, and one held retry carries.

The ninth continuation measured all thirty registered readings and failed (result 9, not
stopped). The owner funded a tenth of 31 calls on 2026-10-30: the ninth's one unused retry
carried and thirty renewed, so the native ledger may rise from 68 to 99 and the shared one
from 249 to 279. Every test clones one real ninth predecessor and revalidates it with the
production validators; none rebuilds the receipt chain.
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abstention_ledger as ledger
import analyze_campaign as campaigns

if TYPE_CHECKING:
    from tests import test_analyze_campaign as fixtures
    from tests import test_qualification_conditional_priority as predecessors
else:
    import test_analyze_campaign as fixtures
    import test_qualification_conditional_priority as predecessors

# The ninth run's thirty exposures: seven semantic failures among them, as result 9 recorded.
NINTH_STATUSES = ("usable",) * 23 + ("semantic-failed",) * 7


class QualificationTenth(unittest.TestCase):
    template: ClassVar[Any]
    snapshot_dirs: ClassVar[tuple[Path, Path]]
    path_bindings: ClassVar[list[tuple[Any, str, Any]]]
    template_files: ClassVar[dict[str, bytes]]

    @classmethod
    def setUpClass(cls) -> None:
        # The ninth's own class fixture builds its predecessors once; this one builds on it.
        ninth_class = predecessors.QualificationConditionalPriority
        ninth_class.setUpClass()
        cls.addClassCleanup(ninth_class.doClassCleanups)
        cls.template = ninth_class()
        cls.addClassCleanup(cls.template.doCleanups)
        cls.template.setUp()
        ninth = cls.template.activate()
        native = cls.template.native(ninth)
        slots = ninth.manifest["slots"]["qualification"]
        statuses = dict(zip(slots, NINTH_STATUSES, strict=True))
        for index, group in enumerate(ninth.manifest["batches"]["qualification"]):
            for slot in group:
                case, repeat = slot.split(":r")
                charge = native.charge(case, repeat=int(repeat), request_binding="a" * 64)
                native.settle(charge, "ok")
                native.finish_exposure(charge, statuses[slot])
            ninth.review_batch("qualification", index, cls.template.measurement(ninth, index))
        failed = {
            "verdict": "failed",
            "producer": "claude",
            "stopped": False,
            "counts": {"attempts": 30, "unusable_attempts": 0},
            "ledger_chain": ledger.chain_of(native.path),
            "marks_digest": cls.template.key["marks_digest"],
            "inputs_digest": cls.template.key["inputs_digest"],
        }
        cls.template.native_fixture.result_paths[8].write_text(json.dumps(failed))
        cls.snapshot_dirs = (cls.template.root, cls.template.native_root)
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
        cls.template_files = {
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
        self.next_path = self.root / "tenth.json"
        self.handoff_path = self.root / "tenth-handoff.json"
        for name, path in (
            ("TENTH_MANIFEST_PATH", self.next_path),
            ("TENTH_HANDOFF_PATH", self.handoff_path),
        ):
            patch = mock.patch.object(campaigns, name, str(path), create=True)
            patch.start()
            self.addCleanup(patch.stop)
        self.native_path = Path(str(campaigns.QUALIFICATION_PATH))
        self.statepath = Path(str(campaigns.LEDGER_PATH))
        self.grant_paths = tuple(map(Path, ledger.CONTINUATION_PATHS))
        self.result_paths = tuple(map(Path, ledger.CONTINUATION_SUMMARY_PATHS))
        self.previous = campaigns.ConditionalPriorityCampaign()
        self.old_state = copy.deepcopy(self.previous._state())
        self.native_prefix = ledger.read(str(self.native_path))["calls"]
        self.failed = json.loads(self.result_paths[8].read_bytes())
        self.manifest = copy.deepcopy(self.previous.manifest)
        self.manifest.update(phase="prepared")
        self.manifest.pop("activation_anchor", None)
        self.manifest["bindings"]["qualification"] = "7" * 64
        self.next_path.write_text(json.dumps(self.manifest))
        self.binding = ledger.digest(
            {k: v for k, v in self.manifest.items() if k not in ("phase", "activation_anchor")}
        )
        self.key = {"cases_digest": "1" * 64, "marks_digest": "2" * 64, "inputs_digest": "3" * 64}
        self.model_key = "4" * 64
        self.grant: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "previous": {
                k: self.failed[k] for k in ("ledger_chain", "marks_digest", "inputs_digest")
            },
            "next": self.key,
            "tenth_continuation_allowance": {
                "previous_calls": 68,
                "additional_calls": 31,
                "carried_calls": 1,
                "renewed_calls": 30,
                "repeats": 3,
                "retry_calls": 1,
                "model_binding": self.model_key,
                "campaign_binding": self.binding,
            },
        }
        self.write_grant()
        self.assertTrue(
            hasattr(campaigns, "tenth_parent_binding"), "the tenth ancestry helper is absent"
        )
        self.handoff: dict[str, Any] = {
            "v": 1,
            "verdict": "GO",
            "prepared_by": "synthetic-operator",
            "reviewed_by": "independent-synthetic-reviewer",
            "parent": campaigns.tenth_parent_binding(self.previous),
            "successor": {
                "manifest_digest": self.binding,
                "grant_digest": ledger.digest(self.grant),
                "evidence": self.manifest["evidence"]["qualification"],
                "cases_digest": self.key["cases_digest"],
                "inputs_digest": self.key["inputs_digest"],
                "model_binding": self.model_key,
                "additional_calls": 31,
                "carried_calls": 1,
                "renewed_calls": 30,
                "shared_total": 279,
                "native_total": 99,
            },
        }
        self.write_handoff()

    def tearDown(self) -> None:
        current = {
            str(path): path.read_bytes()
            for root in self.snapshot_dirs
            for path in root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(self.template_files, current, "a cloned test changed its template")

    def write_grant(self, body: dict[str, Any] | None = None) -> None:
        self.grant_paths[9].write_text(json.dumps(self.grant if body is None else body))

    def write_handoff(self) -> None:
        self.handoff_path.write_text(json.dumps(self.handoff))

    def current(self) -> Any:
        self.assertTrue(hasattr(campaigns, "TenthCampaign"), "the tenth campaign is absent")
        return campaigns.TenthCampaign()

    def activate(self) -> Any:
        anchor = self.current().initialize_successor()
        self.manifest.update(phase="sealed", activation_anchor=anchor)
        self.next_path.write_text(json.dumps(self.manifest))
        return self.current()

    def native(self, current: Any) -> ledger.Ledger:
        return ledger.Ledger(
            str(self.native_path),
            cap=99,
            producer="claude",
            **self.key,
            model_binding=self.model_key,
            campaign=current,
        )

    def measurement(self, current: Any, batch: int) -> dict[str, Any]:
        return dict(predecessors.QualificationConditionalPriority.measurement(current, batch))

    def test_append_preserves_the_ninth_measurement_and_native_68_prefix(self) -> None:
        current = self.activate()
        native = self.native(current)
        self.assertEqual(99, native.cap)
        self.assertEqual(self.old_state, self.previous._state())
        self.assertEqual(30, len(self.previous._state()["calls"]))
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        self.assertEqual(69, native.used())
        self.assertEqual(self.native_prefix, ledger.read(native.path)["calls"][:68])
        native.settle(charge, "ok")
        native.finish_exposure(charge, "usable")
        with self.assertRaises(campaigns.AwaitingReviewError):
            native.charge("0000000000000002", request_binding="a" * 64)
        self.assertIsInstance(campaigns.active_campaign(), campaigns.TenthCampaign)
        self.assertEqual(6, current.epoch_id)
        self.assertEqual(
            [1, 2, 3, 4, 5, 6], [e["id"] for e in json.loads(self.statepath.read_bytes())["epochs"]]
        )

    def test_the_ninth_class_validates_as_an_ancestor_once_the_tenth_is_active(self) -> None:
        self.activate()
        ninth = campaigns.ConditionalPriorityCampaign()
        self.assertEqual(self.old_state, ninth._state())
        # The ninth's own key keeps its own ceiling and can charge nothing more.
        old = ledger.Ledger(
            str(self.native_path),
            cap=99,
            producer="claude",
            **self.template.key,
            model_binding=self.template.model_key,
            campaign=ninth,
        )
        self.assertNotEqual("", old.check())
        with self.assertRaises(ledger.LedgerError):
            ninth.reserve("qualification", ninth.manifest["slots"]["qualification"][0], "a" * 64)

    def test_thirty_one_attempts_reach_99_and_no_more(self) -> None:
        current = self.activate()
        native = self.native(current)
        slots = current.manifest["slots"]["qualification"]
        first = native.charge(slots[0].split(":")[0], request_binding="a" * 64)
        native.settle(first, "failed")
        for index, group in enumerate(current.manifest["batches"]["qualification"]):
            for slot in group:
                case, repeat = slot.split(":r")
                charge = native.charge(
                    case, repeat=int(repeat), retry=slot == slots[0], request_binding="a" * 64
                )
                native.settle(charge, "ok")
                native.finish_exposure(charge, "semantic-failed")
            current.review_batch("qualification", index, self.measurement(current, index))
        self.assertEqual(99, native.used())
        self.assertEqual(31, len(current._state()["calls"]))
        with self.assertRaises(ledger.SpendCapError):
            native.charge("0000000000000001", request_binding="a" * 64)
        with self.assertRaises(ledger.LedgerError):
            current.accept("qualification", fixtures.acceptance(current, "qualification"))
        for lane in ("replay", "live"):
            with self.subTest(lane=lane), self.assertRaises(ledger.LedgerError):
                current.reserve(lane, current.manifest["slots"][lane][0], "a" * 64)
        self.assertEqual(self.old_state, self.previous._state())

    def test_a_semantic_failure_is_measured_rather_than_stopping(self) -> None:
        current = self.activate()
        self.assertFalse(current.stop_on_semantic_failure)
        native = self.native(current)
        first = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(first, "ok")
        native.finish_exposure(first, "semantic-failed")
        with self.assertRaises(campaigns.AwaitingReviewError):
            native.charge("0000000000000002", request_binding="a" * 64)
        current.review_batch("qualification", 0, self.measurement(current, 0))
        second = native.charge("0000000000000002", request_binding="a" * 64)
        native.settle(second, "ok")
        self.assertEqual(70, native.used())

    def test_an_invalid_allowance_or_prior_result_refuses(self) -> None:
        for field, bad in (
            ("previous_calls", 38),
            ("additional_calls", 32),
            ("carried_calls", 29),
            ("renewed_calls", 2),
            ("retry_calls", True),
            ("repeats", 4),
            ("model_binding", "x"),
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.grant)
                body["tenth_continuation_allowance"][field] = bad
                self.write_grant(body)
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.write_grant()
        for result_field, result_bad in (
            ("verdict", "passed"),
            ("stopped", True),
            ("counts", {"attempts": 29, "unusable_attempts": 0}),
            ("counts", {"attempts": 30, "unusable_attempts": 1}),
        ):
            with self.subTest(field=result_field, bad=result_bad):
                body = copy.deepcopy(self.failed)
                body[result_field] = result_bad
                self.result_paths[8].write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.result_paths[8].write_text(json.dumps(self.failed))
        self.assertEqual(10, (ledger.continuation() or {}).get("generation"))

    def test_the_tenth_allowance_cannot_move_to_another_generation(self) -> None:
        for generation in (9, 11):
            with self.subTest(generation=generation), self.assertRaises(ledger.LedgerError):
                ledger._tenth_allowance(self.grant, generation)
        for field in (
            "closure_allowance",
            "successor_allowance",
            "login_resume_allowance",
            "clause_continuation_allowance",
            "clause_isolation_allowance",
            "conditional_priority_allowance",
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.grant)
                body[field] = body["tenth_continuation_allowance"]
                self.write_grant(body)
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.write_grant()
        body = json.loads(self.grant_paths[8].read_text())
        body["tenth_continuation_allowance"] = self.grant["tenth_continuation_allowance"]
        self.grant_paths[8].write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            ledger.continuation()

    def test_an_eleventh_grant_without_its_own_allowance_admits_no_charge(self) -> None:
        current = self.activate()
        native = self.native(current)
        charge = native.charge("0000000000000001", request_binding="a" * 64)
        native.settle(charge, "ok")
        native.finish_exposure(charge, "semantic-failed")
        current.stop("semantic-failed")
        result = {
            **self.failed,
            "stopped": True,
            "counts": {"attempts": 1, "unusable_attempts": 0},
            "ledger_chain": ledger.chain_of(str(self.native_path)),
            "marks_digest": self.key["marks_digest"],
            "inputs_digest": self.key["inputs_digest"],
        }
        self.result_paths[9].write_text(json.dumps(result))
        eleventh: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "previous": {k: result[k] for k in ("ledger_chain", "marks_digest", "inputs_digest")},
            "next": {"cases_digest": "5" * 64, "marks_digest": "6" * 64, "inputs_digest": "8" * 64},
        }
        self.grant_paths[10].write_text(json.dumps(eleventh))
        self.assertEqual(11, (ledger.continuation() or {}).get("generation"))
        retry = ledger.Ledger(str(self.native_path), cap=130, producer="claude", **eleventh["next"])
        self.assertEqual(ledger.MAX_CALLS, retry.cap)
        with self.assertRaises(ledger.SpendCapError):
            retry.charge("0000000000000001")

    def test_an_incomplete_ninth_measurement_cannot_be_continued(self) -> None:
        original = self.statepath.read_bytes()
        for change in ("drop-call", "drop-batch", "stop"):
            with self.subTest(change=change):
                body = json.loads(original)
                state = body["epochs"][4]["state"]
                if change == "drop-call":
                    state["calls"].pop()
                elif change == "drop-batch":
                    state["accepted_batches"].pop("qualification:3")
                else:
                    state["stop"] = "semantic-failed"
                self.statepath.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    self.current().initialize_successor()
                self.statepath.write_bytes(original)

    def test_duplicate_activation_and_a_modified_epoch_refuse(self) -> None:
        current = self.activate()
        with self.assertRaises(ledger.LedgerError):
            current.initialize_successor()
        original = self.statepath.read_bytes()
        for epoch in range(6):
            with self.subTest(epoch=epoch):
                body = json.loads(original)
                body["epochs"][epoch]["state"]["calls"].clear()
                if epoch == 5:
                    body["epochs"][epoch]["state"]["genesis_nonce"] = "changed"
                self.statepath.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    current.reserve("qualification", "0000000000000001:r1", "a" * 64)
                self.statepath.write_bytes(original)

    def test_the_native_prefix_and_ancestor_handoff_cannot_be_rewritten(self) -> None:
        current = self.activate()
        original = self.native_path.read_bytes()
        for index in (0, 37, 38, 52, 67):
            with self.subTest(index=index):
                body = json.loads(original)
                body["calls"][index]["status"] = "charged"
                self.native_path.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    current.reserve("qualification", "0000000000000001:r1", "a" * 64)
                self.native_path.write_bytes(original)
        self.handoff["parent"]["native_calls"] = 69
        self.write_handoff()
        with self.assertRaises(ledger.LedgerError):
            self.current()

    def test_the_handoff_binds_the_carry_and_both_ceilings(self) -> None:
        for field, bad in (
            ("carried_calls", 0),
            ("renewed_calls", 31),
            ("shared_total", 280),
            ("native_total", 100),
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.handoff)
                body["successor"][field] = bad
                self.handoff_path.write_text(json.dumps(body))
                with self.assertRaises(ledger.LedgerError):
                    self.current()
        self.write_handoff()
        same = {**self.handoff, "reviewed_by": self.handoff["prepared_by"]}
        self.handoff_path.write_text(json.dumps(same))
        with self.assertRaises(ledger.LedgerError):
            self.current()

    def test_partial_or_deleted_authority_never_falls_back_to_the_ninth(self) -> None:
        self.next_path.unlink()
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()
        self.next_path.write_text(json.dumps(self.manifest))
        self.handoff_path.unlink()
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()
        self.write_handoff()
        current = self.activate()
        self.next_path.unlink()
        self.handoff_path.unlink()
        self.assertTrue(current.epoch_dir.is_dir())
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()


if __name__ == "__main__":
    unittest.main()
