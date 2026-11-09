"""People approve one exact offline Codex exposure; these tests launch no producer."""

from __future__ import annotations

import copy
import importlib
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abstention_ledger as authority
import analyze_campaign as campaign


@unittest.skipIf(sys.platform == "win32", "Codex account authority currently refuses Windows")
class CodexAuthority(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.grant_path = self.home / "codex-grant.json"
        for patch in (
            mock.patch.object(authority, "real_home", return_value=str(self.home)),
            mock.patch.object(authority, "CODEX_GRANT_PATH", str(self.grant_path), create=True),
            mock.patch.dict(
                os.environ, {"HOME": str(self.home), "COMPASS_HOME": str(self.home / "packet")}
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.transport: dict[str, Any] = {
            "producer": "codex",
            "model": "gpt-5.6-luna",
            "effort": "max",
            "binary": "/fake/codex",
            "binary_sha256": "b" * 64,
            "cli_version": "codex 1.0",
            "argv": [
                "/fake/codex",
                "exec",
                "--model",
                "gpt-5.6-luna",
                "--config",
                "model_reasoning_effort=max",
            ],
            "destination": "OpenAI",
            "runtime_digest": "c" * 64,
        }
        self.inputs = {
            key: authority.digest(key)
            for key in (
                "packet",
                "cases",
                "marks",
                "rubric",
                "source",
                "protocol",
                "runtime",
                "scorer",
            )
        }
        self.inputs["runtime"] = self.transport["runtime_digest"]
        self.request = campaign.request_digest(
            "redacted evidence",
            "codex",
            self.inputs["source"],
            4096,
            codex_transport=self.transport,
        )
        self.slots = [f"r{r}:case{c}" for r in range(1, 4) for c in range(10)]
        self.grant: dict[str, Any] = {
            "v": 1,
            "study": "codex-qualification",
            "phase": "prepared",
            "producer": "codex",
            "bindings": self.inputs,
            "transport": authority.digest(self.transport),
            "allowance": 31,
            "retry_limit": 1,
            "exposures": [
                {
                    "slot": slot,
                    "case": f"case{n % 10}",
                    "repetition": n // 10 + 1,
                    "request_digest": self.request,
                }
                for n, slot in enumerate(self.slots)
            ],
            "activation_anchor": "",
            "genesis_review": "",
        }
        self.write_grant()
        self.launch = mock.Mock(name="fake_producer")

    def write_grant(self) -> None:
        self.grant_path.write_text(json.dumps(self.grant))

    def study(self) -> Any:
        return campaign.CodexCampaign(bindings=self.inputs, transport=self.transport)

    def activate(self) -> Any:
        anchor = self.study().initialize()
        self.grant.update(phase="sealed", activation_anchor=anchor, genesis_review="d" * 64)
        self.write_grant()
        return self.study()

    def approve(self, study: Any, *, slot: str | None = None, retry: bool = False) -> str:
        return str(study.approve_slot(slot or self.slots[0], self.request, retry=retry))

    def reserve(
        self, study: Any, approval: str, *, slot: str | None = None, retry: bool = False
    ) -> str:
        charge = study.reserve(slot or self.slots[0], self.request, approval=approval, retry=retry)
        self.launch()
        return str(charge)

    def test_a_person_without_a_codex_grant_cannot_launch(self) -> None:
        self.grant_path.unlink()
        with self.assertRaises(authority.LedgerError):
            self.reserve(self.study(), "f" * 32)
        self.launch.assert_not_called()

    def test_a_person_with_an_unsealed_grant_cannot_launch(self) -> None:
        study = self.study()
        study.initialize()
        with self.assertRaises(authority.LedgerError):
            self.reserve(study, "f" * 32)
        self.launch.assert_not_called()

    def test_a_person_cannot_use_claude_authority_or_a_copied_claude_approval(self) -> None:
        study = self.activate()
        with self.assertRaises(authority.LedgerError):
            self.reserve(study, "claude-approval")
        self.grant["producer"] = "claude"
        self.write_grant()
        with self.assertRaises(authority.LedgerError):
            self.reserve(self.study(), "f" * 32)
        self.launch.assert_not_called()

    def test_a_person_must_review_zero_charge_genesis_before_activation(self) -> None:
        self.grant.update(phase="sealed", activation_anchor="a" * 64, genesis_review="b" * 64)
        self.write_grant()
        with self.assertRaises(authority.LedgerError):
            self.study().initialize()
        with self.assertRaises(authority.LedgerError):
            self.reserve(self.study(), "f" * 32)
        self.launch.assert_not_called()

    def test_a_person_cannot_change_any_bound_input_before_charge(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        for key in self.inputs:
            with self.subTest(changed=key):
                original = self.inputs[key]
                self.inputs[key] = "f" * 64
                try:
                    with self.assertRaises(authority.LedgerError):
                        self.reserve(study, approval)
                finally:
                    self.inputs[key] = original
        self.assertEqual(0, study.used())
        self.launch.assert_not_called()

    def test_a_person_cannot_change_transport_or_prompt_before_charge(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        for key, value in {
            "model": "another-model",
            "effort": "low",
            "binary_sha256": "f" * 64,
            "cli_version": "codex 2.0",
            "argv": ["/fake/codex", "exec", "--unsafe"],
            "destination": "elsewhere",
            "binary": "/other/codex",
            "runtime_digest": "f" * 64,
        }.items():
            with self.subTest(changed=key):
                original = self.transport[key]
                self.transport[key] = value
                try:
                    with self.assertRaises(authority.LedgerError):
                        self.reserve(study, approval)
                finally:
                    self.transport[key] = original
        changed = campaign.request_digest(
            "different prompt", "codex", self.inputs["source"], 4096, codex_transport=self.transport
        )
        with self.assertRaises(authority.LedgerError):
            study.reserve(self.slots[0], changed, approval=approval)
        self.assertEqual(0, study.used())
        self.launch.assert_not_called()

    def test_a_person_cannot_reuse_approval_for_another_slot_retry_or_invocation(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        for other, slot, retry in (
            (study, self.slots[1], False),
            (study, self.slots[0], True),
            (self.study(), self.slots[0], False),
        ):
            with (
                self.subTest(slot=slot, retry=retry, invocation=other.invocation),
                self.assertRaises(authority.LedgerError),
            ):
                self.reserve(other, approval, slot=slot, retry=retry)
        self.assertEqual(0, study.used())
        self.launch.assert_not_called()
        charge = self.reserve(study, approval)
        study.settle(charge, "unusable")
        with self.assertRaises(authority.LedgerError):
            self.reserve(study, approval, retry=True)
        fresh = self.approve(study, retry=True)
        self.reserve(study, fresh, retry=True)
        self.assertEqual(2, study.used())

    def test_a_person_cannot_reset_allowance_by_moving_a_packet_or_deleting_accounting(
        self,
    ) -> None:
        study = self.activate()
        self.reserve(study, self.approve(study))
        with mock.patch.dict(os.environ, {"COMPASS_HOME": str(self.home / "moved")}):
            self.assertEqual(1, self.study().used())
        Path(study.path).unlink()
        with self.assertRaises(authority.LedgerError):
            self.study().initialize()
        with self.assertRaises(authority.LedgerError):
            self.study().used()

    def test_a_person_cannot_reset_allowance_with_a_moved_home(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        with (
            mock.patch.dict(os.environ, {"HOME": str(self.home / "elsewhere")}),
            self.assertRaises(authority.LedgerError),
        ):
            self.reserve(study, approval)
        self.launch.assert_not_called()

    def test_a_person_cannot_continue_with_missing_receipts_or_an_orphan_reservation(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        before = Path(study.path).read_bytes()
        self.reserve(study, approval)
        charged = Path(study.path).read_bytes()
        Path(study.path).write_bytes(before)
        with self.assertRaises(authority.LedgerError):
            study.used()
        Path(study.path).write_bytes(charged)
        next(study.receipts.glob("charge-*.json")).unlink()
        with self.assertRaises(authority.LedgerError):
            study.used()

    def test_a_person_cannot_skip_an_unresolved_attempt_or_retry_a_semantic_failure(self) -> None:
        study = self.activate()
        charge = self.reserve(study, self.approve(study))
        with self.assertRaises(authority.LedgerError):
            self.approve(study, slot=self.slots[1])
        study.settle(charge, "semantic-failed")
        with self.assertRaises(authority.LedgerError):
            self.approve(study, retry=True)
        self.assertEqual(1, study.used())
        self.approve(study, slot=self.slots[1])

    def test_a_person_gets_thirty_registered_exposures_and_only_one_availability_retry(
        self,
    ) -> None:
        study = self.activate()
        first = self.reserve(study, self.approve(study))
        study.settle(first, "unusable")
        retry = self.reserve(study, self.approve(study, retry=True), retry=True)
        study.settle(retry, "usable")
        for n, slot in enumerate(self.slots[1:], 1):
            if n % 10 == 0:
                with self.assertRaises(authority.LedgerError):
                    self.approve(study, slot=slot)
                study.review_batch(n // 10, "e" * 64)
            charge = self.reserve(study, self.approve(study, slot=slot), slot=slot)
            study.settle(charge, "unusable" if n == 29 else "usable")
        with self.assertRaises(authority.LedgerError):
            self.approve(study, slot=self.slots[-1], retry=True)
        self.assertEqual(31, self.study().used())
        self.assertEqual(31, self.launch.call_count)

    def test_a_person_cannot_rewrite_a_settled_failure_or_reinitialize_genesis(self) -> None:
        study = self.activate()
        charge = self.reserve(study, self.approve(study))
        study.settle(charge, "unusable")
        with self.assertRaises(authority.LedgerError):
            study.settle(charge, "usable")
        with self.assertRaises(authority.LedgerError):
            study.initialize()
        self.assertEqual(1, study.used())

    def test_a_person_cannot_continue_after_the_grant_changes_on_disk(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        self.grant["bindings"] = copy.deepcopy(self.inputs)
        self.grant["bindings"]["marks"] = "f" * 64
        self.write_grant()
        with self.assertRaises(authority.LedgerError):
            self.reserve(study, approval)
        self.launch.assert_not_called()

    def test_a_person_with_sealed_authority_cannot_launch_an_unverified_cli(self) -> None:
        study = self.activate()
        scorer = importlib.import_module("score_abstention")
        corpus = scorer.Corpus({"v": 6, "cases": [{}]}, {}, b"", {})
        with (
            mock.patch.object(scorer, "_load_corpus", return_value=corpus),
            mock.patch.object(
                scorer, "verify_codex_binary", side_effect=scorer.BinaryError("unverified fake CLI")
            ),
            mock.patch.object(scorer, "codex_model", side_effect=AssertionError("producer built")),
            mock.patch("builtins.print") as printed,
        ):
            self.assertEqual(2, scorer.main(["--score", "--producer", "codex"]))
        self.assertIn("unverified fake CLI", str(printed.call_args))
        self.assertEqual(0, study.used())
        self.launch.assert_not_called()

    def test_a_person_cannot_inherit_an_approval_into_a_forked_process(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        with (
            mock.patch.object(os, "getpid", return_value=os.getpid() + 1),
            self.assertRaises(authority.LedgerError),
        ):
            self.reserve(study, approval)
        self.launch.assert_not_called()

    def test_a_person_cannot_consume_one_approval_from_two_concurrent_threads(self) -> None:
        study = self.activate()
        approval = self.approve(study)

        def attempt() -> bool:
            try:
                self.reserve(study, approval)
            except authority.LedgerError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual([False, True], sorted(pool.map(lambda _: attempt(), range(2))))
        self.assertEqual(1, study.used())
        self.launch.assert_called_once()

    def test_a_person_in_another_process_cannot_spend_the_approval(self) -> None:
        import subprocess  # noqa: PLC0415 - a Python child with a fake transport only

        study = self.activate()
        approval = self.approve(study)
        fixture = self.home / "child-input.json"
        fixture.write_text(json.dumps({"bindings": self.inputs, "transport": self.transport}))
        child = """
import json, os, sys
from unittest import mock
import abstention_ledger as authority
import analyze_campaign as campaign
home, grant, fixture, slot, request, approval = sys.argv[1:]
with open(fixture) as handle:
    inputs = json.load(handle)
with mock.patch.object(authority, 'real_home', return_value=home), mock.patch.object(authority, 'CODEX_GRANT_PATH', grant):
    study = campaign.CodexCampaign(**inputs)
    try:
        study.reserve(slot, request, approval=approval)
    except authority.LedgerError:
        print('refused before launch')
    else:
        raise RuntimeError('another process spent the approval')
"""
        observed = subprocess.run(
            [
                sys.executable,
                "-c",
                child,
                str(self.home),
                str(self.grant_path),
                str(fixture),
                self.slots[0],
                self.request,
                approval,
            ],
            cwd=Path(authority.__file__).parent,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, observed.returncode, observed.stderr)
        self.assertEqual("refused before launch", observed.stdout.strip())
        self.assertEqual(0, study.used())
        self.launch.assert_not_called()

    def test_a_person_cannot_continue_after_a_protection_failure(self) -> None:
        self.assert_failure_stops("protection-failed")

    def test_a_person_cannot_continue_after_a_coverage_failure(self) -> None:
        self.assert_failure_stops("coverage-failed")

    def assert_failure_stops(self, status: str) -> None:
        study = self.activate()
        charge = self.reserve(study, self.approve(study))
        study.settle(charge, status)
        with self.assertRaises(authority.LedgerError):
            self.approve(study, slot=self.slots[1])
        self.assertEqual(1, study.used())

    def test_a_person_cannot_retry_a_slot_after_a_later_slot_ran(self) -> None:
        study = self.activate()
        first = self.reserve(study, self.approve(study))
        study.settle(first, "unusable")
        second = self.reserve(study, self.approve(study, slot=self.slots[1]), slot=self.slots[1])
        study.settle(second, "usable")
        with self.assertRaises(authority.LedgerError):
            self.approve(study, slot=self.slots[0], retry=True)
        self.assertEqual(2, study.used())

    def test_a_person_on_windows_gets_no_codex_authority(self) -> None:
        study = self.activate()
        with (
            mock.patch.object(sys, "platform", "win32"),
            self.assertRaises(authority.LedgerError),
        ):
            self.approve(study)
        self.launch.assert_not_called()

    def test_a_person_cannot_redirect_accounting_through_a_symlink(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        real = self.home / "moved-receipts"
        study.receipts.rename(real)
        study.receipts.symlink_to(real, target_is_directory=True)
        with self.assertRaises(authority.LedgerError):
            self.reserve(study, approval)
        self.launch.assert_not_called()

    def test_a_person_cannot_expand_the_grant_or_substitute_registered_cases(self) -> None:
        original = copy.deepcopy(self.grant)
        for key, changed in (
            ("allowance", 32),
            ("retry_limit", 2),
            ("producer", "claude"),
            ("genesis_review", "fake review"),
        ):
            with self.subTest(field=key):
                self.grant = {**original, key: changed}
                self.write_grant()
                with self.assertRaises(authority.LedgerError):
                    self.study()
        self.grant = copy.deepcopy(original)
        self.grant["exposures"][10]["case"] = "substitute"
        self.write_grant()
        with self.assertRaises(authority.LedgerError):
            self.study()
        self.launch.assert_not_called()

    def test_a_person_cannot_activate_a_different_genesis_or_an_unreviewed_one(self) -> None:
        self.activate()
        original = copy.deepcopy(self.grant)
        for field, value in (("activation_anchor", "f" * 64), ("genesis_review", "")):
            with self.subTest(field=field):
                self.grant = {**original, field: value}
                self.write_grant()
                with self.assertRaises(authority.LedgerError):
                    self.approve(self.study())
        self.launch.assert_not_called()

    def test_a_person_cannot_prepare_a_second_zero_charge_genesis(self) -> None:
        study = self.study()
        study.initialize()
        with self.assertRaises(authority.LedgerError):
            self.study().initialize()

    def test_a_person_cannot_rewrite_an_existing_approval_or_settlement_receipt(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        receipt = study.receipts / f"approval-{approval}.json"
        before = receipt.read_bytes()
        body = json.loads(before)
        body["request_digest"] = "f" * 64
        receipt.write_text(json.dumps(body))
        with self.assertRaises(authority.LedgerError):
            self.reserve(study, approval)
        self.launch.assert_not_called()
        receipt.write_bytes(before)
        charge = self.reserve(study, approval)
        study.settle(charge, "unusable")
        receipt = next(study.receipts.glob("settlement-*.json"))
        body = json.loads(receipt.read_text())
        body["status"] = "usable"
        receipt.write_text(json.dumps(body))
        with self.assertRaises(authority.LedgerError):
            study.used()

    def test_a_person_cannot_move_the_fixed_ledger_even_with_all_its_receipts(self) -> None:
        import shutil  # noqa: PLC0415 - relocate synthetic accounting only

        study = self.activate()
        original = Path(study.path)
        moved = self.home / "another-ledger.json"
        shutil.copyfile(original, moved)
        relocated_receipts = self.home / "another-ledger.json.receipts"
        shutil.copytree(study.receipts, relocated_receipts)
        study.path = str(moved)
        study.receipts = relocated_receipts
        with self.assertRaises(authority.LedgerError):
            study.used()

    def test_a_person_cannot_get_a_second_retry_even_when_allowance_remains(self) -> None:
        study = self.activate()
        charge = self.reserve(study, self.approve(study))
        study.settle(charge, "unusable")
        charge = self.reserve(study, self.approve(study, retry=True), retry=True)
        study.settle(charge, "unusable")
        with self.assertRaises(authority.LedgerError):
            self.approve(study, retry=True)
        self.assertEqual(2, study.used())

    def test_a_person_cannot_retry_inside_a_batch_they_already_reviewed(self) -> None:
        study = self.activate()
        for n, slot in enumerate(self.slots[:10]):
            charge = self.reserve(study, self.approve(study, slot=slot), slot=slot)
            study.settle(charge, "unusable" if n == 9 else "usable")
        study.review_batch(1, "e" * 64)
        with self.assertRaises(authority.LedgerError):
            self.approve(study, slot=self.slots[9], retry=True)
        self.assertEqual(10, study.used())

    def test_a_person_cannot_approve_an_unregistered_prompt(self) -> None:
        study = self.activate()
        with self.assertRaises(authority.LedgerError):
            study.approve_slot(self.slots[0], "f" * 64)
        self.assertEqual(0, study.used())
        self.launch.assert_not_called()

    def test_a_person_cannot_refund_a_charge_when_the_index_write_is_interrupted(self) -> None:
        study = self.activate()
        approval = self.approve(study)
        with (
            mock.patch.object(study, "_persist", side_effect=OSError("simulated disk failure")),
            self.assertRaises(OSError),
        ):
            self.reserve(study, approval)
        self.launch.assert_not_called()
        self.assertEqual(1, len(list(study.receipts.glob("charge-*.json"))))
        with self.assertRaises(authority.LedgerError):
            self.study().used()
        with self.assertRaises(authority.LedgerError):
            self.study().initialize()

    def test_a_person_cannot_copy_a_claude_receipt_into_codex_accounting(self) -> None:
        study = self.activate()
        receipt = study.receipts / ("approval-" + "f" * 32 + ".json")
        receipt.write_text(
            json.dumps(
                {
                    "id": "f" * 32,
                    "at": 1234,
                    "lane": "qualification",
                    "slot": self.slots[0],
                    "binding": self.request,
                    "retry": False,
                    "availability_attempt": 1,
                }
            )
        )
        with self.assertRaises(authority.LedgerError):
            self.reserve(study, "f" * 32)
        self.launch.assert_not_called()

    def test_a_person_cannot_put_private_cli_paths_or_argv_in_the_public_grant(self) -> None:
        self.grant["transport"] = self.transport
        self.write_grant()
        with self.assertRaises(authority.LedgerError):
            authority.codex_grant()
        self.launch.assert_not_called()
