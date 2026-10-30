"""The one funded retry after a failed tenth: exactly its allowance, and nothing before result 10.

The owner's 2026-10-30 funding allows one corrected retry of at most 31 more calls if the tenth
fails. Its numbers follow from what the tenth spent. With P native calls when result 10 is
recorded, the retry carries 99 - P, renews P - 68, and may reach P + 31 native and
279 + (P - 68) shared. Here the tenth measures its thirty and leaves its retry unused, so P is 98:
ceilings of 129 native and 309 shared. Every test clones one real tenth predecessor.
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
    from tests import test_qualification_tenth as predecessors
else:
    import test_analyze_campaign as fixtures
    import test_qualification_tenth as predecessors

RECEIPTS = predecessors.RECEIPTS
TENTH_STATUSES = ("usable",) * 20 + ("semantic-failed",) * 10


class QualificationRetry(unittest.TestCase):
    template: ClassVar[Any]
    snapshot_dirs: ClassVar[tuple[Path, Path]]
    path_bindings: ClassVar[list[tuple[Any, str, Any]]]
    template_files: ClassVar[dict[str, bytes]]

    @classmethod
    def setUpClass(cls) -> None:
        tenth_class = predecessors.QualificationTenth
        tenth_class.setUpClass()
        cls.addClassCleanup(tenth_class.doClassCleanups)
        cls.template = tenth_class()
        cls.addClassCleanup(cls.template.doCleanups)
        cls.template.setUp()
        tenth = cls.template.activate()
        native = cls.template.native(tenth)
        slots = tenth.manifest["slots"]["qualification"]
        statuses = dict(zip(slots, TENTH_STATUSES, strict=True))
        for index, group in enumerate(tenth.manifest["batches"]["qualification"]):
            for slot in group:
                case, repeat = slot.split(":r")
                charge = native.charge(case, repeat=int(repeat), request_binding="a" * 64)
                native.settle(charge, "ok")
                native.finish_exposure(charge, statuses[slot])
            tenth.review_batch("qualification", index, cls.template.measurement(tenth, index))
        failed = {
            "verdict": "failed",
            "producer": "claude",
            "stopped": False,
            "counts": {"attempts": 30, "unusable_attempts": 0},
            "ledger_chain": ledger.chain_of(native.path),
            "marks_digest": cls.template.key["marks_digest"],
            "inputs_digest": cls.template.key["inputs_digest"],
        }
        cls.template.result_paths[9].write_text(json.dumps(failed))
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
        cls.template_files = cls._files()

    @classmethod
    def _files(cls) -> dict[str, bytes]:
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
        self.next_path = self.root / "retry.json"
        self.handoff_path = self.root / "retry-handoff.json"
        for name, path in (
            ("RETRY_MANIFEST_PATH", self.next_path),
            ("RETRY_HANDOFF_PATH", self.handoff_path),
        ):
            patch = mock.patch.object(campaigns, name, str(path))
            patch.start()
            self.addCleanup(patch.stop)
        self.native_path = Path(str(campaigns.QUALIFICATION_PATH))
        self.statepath = Path(str(campaigns.LEDGER_PATH))
        self.grant_paths = tuple(map(Path, ledger.CONTINUATION_PATHS))
        self.result_paths = tuple(map(Path, ledger.CONTINUATION_SUMMARY_PATHS))
        self.previous = campaigns.TenthCampaign()
        self.old_state = copy.deepcopy(self.previous._state())
        self.failed = json.loads(self.result_paths[9].read_bytes())
        self.manifest = copy.deepcopy(self.previous.manifest)
        self.manifest.update(phase="prepared")
        self.manifest.pop("activation_anchor", None)
        self.manifest["bindings"]["qualification"] = "6" * 64
        self.next_path.write_text(json.dumps(self.manifest))
        self.binding = ledger.digest(
            {k: v for k, v in self.manifest.items() if k not in ("phase", "activation_anchor")}
        )
        self.key = {"cases_digest": "9" * 64, "marks_digest": "8" * 64, "inputs_digest": "7" * 64}
        self.model_key = "5" * 64
        self.grant: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "previous": {
                k: self.failed[k] for k in ("ledger_chain", "marks_digest", "inputs_digest")
            },
            "next": self.key,
            "retry_continuation_allowance": {
                "previous_calls": 98,
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
        self.handoff: dict[str, Any] = {
            "v": 1,
            "verdict": "GO",
            "prepared_by": "synthetic-operator",
            "reviewed_by": "independent-synthetic-reviewer",
            "receipts": copy.deepcopy(RECEIPTS),
            "parent": campaigns.retry_parent_binding(self.previous),
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
                "shared_total": 309,
                "native_total": 129,
            },
        }
        self.write_handoff()

    def tearDown(self) -> None:
        self.assertEqual(self.template_files, self._files(), "a cloned test changed its template")

    def write_grant(self, body: dict[str, Any] | None = None) -> None:
        self.grant_paths[10].write_text(json.dumps(self.grant if body is None else body))

    def write_handoff(self, body: dict[str, Any] | None = None) -> None:
        self.handoff_path.write_text(json.dumps(self.handoff if body is None else body))

    def activate(self) -> Any:
        anchor = campaigns.RetryCampaign().initialize_successor()
        self.manifest.update(phase="sealed", activation_anchor=anchor)
        self.next_path.write_text(json.dumps(self.manifest))
        return campaigns.RetryCampaign()

    def native(self, current: Any) -> ledger.Ledger:
        return ledger.Ledger(
            str(self.native_path),
            cap=130,
            producer="claude",
            **self.key,
            model_binding=self.model_key,
            campaign=current,
        )

    def test_the_retry_admits_exactly_its_allowance(self) -> None:
        current = self.activate()
        self.assertIsInstance(campaigns.active_campaign(), campaigns.RetryCampaign)
        self.assertEqual(7, current.epoch_id)
        native = self.native(current)
        self.assertEqual(129, native.cap)
        self.assertEqual(129, ledger.allowance_cap(ledger.continuation()))
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
                native.finish_exposure(charge, "usable")
            current.review_batch(
                "qualification",
                index,
                self.template.measurement(current, index),
            )
        self.assertEqual(129, native.used())
        with self.assertRaises(ledger.SpendCapError):
            native.charge("0000000000000001", request_binding="a" * 64)
        for lane in ("replay", "live"):
            with self.subTest(lane=lane), self.assertRaises(ledger.LedgerError):
                current.reserve(lane, current.manifest["slots"][lane][0], "a" * 64)
        self.assertEqual(self.old_state, self.previous._state())

    def test_the_tenth_validates_as_an_ancestor_and_its_key_cannot_charge(self) -> None:
        self.activate()
        tenth = campaigns.TenthCampaign()
        self.assertEqual(self.old_state, tenth._state())
        old = ledger.Ledger(
            str(self.native_path),
            cap=130,
            producer="claude",
            **self.template.key,
            model_binding=self.template.model_key,
            campaign=tenth,
        )
        self.assertNotEqual("", old.check())
        with self.assertRaises(ledger.LedgerError):
            old.charge("0000000000000001", request_binding="a" * 64)

    def test_nothing_before_result_10_is_recorded_failed(self) -> None:
        self.result_paths[9].unlink()
        with self.assertRaises(ledger.LedgerError):
            ledger.continuation()
        for field, bad in (
            ("verdict", "passed"),
            ("verdict", "blocked"),
            ("stopped", "no"),
            ("counts", {"attempts": 29, "unusable_attempts": 0}),
            ("counts", {"attempts": 30, "unusable_attempts": 31}),
        ):
            with self.subTest(field=field, bad=bad):
                self.result_paths[9].write_text(json.dumps({**self.failed, field: bad}))
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.result_paths[9].write_text(json.dumps(self.failed))
        self.assertEqual(11, (ledger.continuation() or {}).get("generation"))

    def test_any_other_arithmetic_is_refused(self) -> None:
        for field, bad in (
            ("previous_calls", 99),
            ("carried_calls", 0),
            ("renewed_calls", 31),
            ("additional_calls", 32),
            ("retry_calls", 2),
        ):
            with self.subTest(field=field):
                body = copy.deepcopy(self.grant)
                body["retry_continuation_allowance"][field] = bad
                self.write_grant(body)
                with self.assertRaises(ledger.LedgerError):
                    ledger.continuation()
        self.write_grant()
        for field, bad in (("shared_total", 310), ("native_total", 130), ("carried_calls", 0)):
            with self.subTest(handoff=field):
                body = copy.deepcopy(self.handoff)
                body["successor"][field] = bad
                self.write_handoff(body)
                with self.assertRaises(ledger.LedgerError):
                    campaigns.RetryCampaign()
        self.write_handoff()

    def test_the_retry_allowance_belongs_to_grant_11_alone(self) -> None:
        for generation in (10, 12):
            with self.subTest(generation=generation), self.assertRaises(ledger.LedgerError):
                ledger._retry_allowance(self.grant, generation)
        body = copy.deepcopy(self.grant)
        body["tenth_continuation_allowance"] = body["retry_continuation_allowance"]
        self.write_grant(body)
        with self.assertRaises(ledger.LedgerError):
            ledger.continuation()
        self.write_grant()
        tenth = json.loads(self.grant_paths[9].read_text())
        tenth["retry_continuation_allowance"] = self.grant["retry_continuation_allowance"]
        self.grant_paths[9].write_text(json.dumps(tenth))
        with self.assertRaises(ledger.LedgerError):
            ledger.continuation()

    def test_activation_is_once_and_deleted_authority_never_falls_back(self) -> None:
        current = self.activate()
        with self.assertRaises(ledger.LedgerError):
            current.initialize_successor()
        self.assertEqual(
            [1, 2, 3, 4, 5, 6, 7],
            [e["id"] for e in json.loads(self.statepath.read_bytes())["epochs"]],
        )
        self.next_path.unlink()
        self.handoff_path.unlink()
        with self.assertRaises(ledger.LedgerError):
            campaigns.active_campaign()

    def test_acceptance_of_the_retry_needs_the_full_measured_review(self) -> None:
        current = self.activate()
        with self.assertRaises(ledger.LedgerError):
            current.accept("qualification", fixtures.acceptance(current, "qualification"))


if __name__ == "__main__":
    unittest.main()
