"""A shared closure ceiling stays charged across homes, retries and process restarts."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import abstention_ledger as ledger

if TYPE_CHECKING:
    from analyze_campaign import Campaign


def acceptance(campaign: Campaign, lane: str, batch: int | None = None) -> dict[str, Any]:
    slots = (
        campaign.manifest["slots"][lane]
        if batch is None
        else campaign.manifest["batches"][lane][batch]
    )
    own = [
        call
        for call in campaign._state()["calls"]
        if call["lane"] == lane and call["slot"] in slots
    ]
    proof = {
        "v": 1,
        "lane": lane,
        "manifest_digest": campaign.binding,
        "protocol": campaign.manifest["protocols"][lane],
        "binding": campaign.manifest["bindings"][lane],
        "evidence": campaign.manifest["evidence"][lane],
        "slots_digest": ledger.digest(slots),
        "attempts_digest": ledger.digest(own),
        "charged_attempts": len(own),
        "expected_slots": len(slots),
        "usable_slots": len(slots),
        "semantic_failures": 0,
        "coverage_failures": 0,
        "protection_failures": 0,
        "verdict": "passed",
        "output_digest": "c" * 64,
        "review_digest": "d" * 64,
    }
    if batch is not None:
        proof["batch"] = batch
    return proof


def seed_predecessor(campaign: Campaign, lane: str, *, accept: bool = True) -> None:
    """Build only a synthetic completed predecessor, then use real state/acceptance checks.

    Qualification/live tests do not need 190 separate reserve/settle transitions to
    arrange their predecessor. The full lifecycle/cap test still does those transitions.
    No production validation, locking or durable writer is patched by this fixture.
    """
    if not Path(campaign.path).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ledger.LedgerError("predecessor fixtures require an owned temporary account")
    body = campaign._state()
    manifest = campaign.manifest
    slots = manifest["slots"][lane]
    if (
        body.get("stop")
        or any(call["status"] != "usable" or call["lane"] == lane for call in body["calls"])
        or set(slots) & set(manifest.get("deferred_slots", {}).get(lane, []))
        or set(manifest["requests"][lane]) != set(slots)
        or any(
            previous not in body.get("accepted", {})
            for previous in manifest["order"][: manifest["order"].index(lane)]
        )
    ):
        raise ledger.LedgerError("the synthetic predecessor is held, pending or unregistered")
    campaign.receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
    for n, slot in enumerate(slots):
        call = {
            "id": uuid.uuid4().hex,
            "at": time.time(),
            "lane": lane,
            "slot": slot,
            "binding": manifest["requests"][lane][slot],
            "retry": False,
            "availability_attempt": 1 if n == 0 else 0,
            "status": "usable",
        }
        ledger._write(
            str(campaign.receipts / (call["id"] + ".json")),
            {key: value for key, value in call.items() if key != "status"},
        )
        ledger._write(
            str(campaign.receipts / (call["id"] + "-SETTLED.json")),
            {"id": call["id"], "status": "usable", "manifest_digest": campaign.binding},
        )
        body["calls"].append(call)
    ledger._write(campaign.path, body)
    campaign._state()
    for batch in range(len(manifest["batches"][lane])):
        campaign.accept_batch(lane, batch, acceptance(campaign, lane, batch))
    if accept:
        campaign.accept(lane, acceptance(campaign, lane))


class CampaignFixtureIsolation(unittest.TestCase):
    def test_original_fixture_cannot_discover_published_successor_files(self) -> None:
        module = importlib.import_module("analyze_campaign")
        for field in (
            "SUCCESSOR_MANIFEST_PATH",
            "SUCCESSOR_HANDOFF_PATH",
            "LOGIN_RESUME_MANIFEST_PATH",
            "LOGIN_RESUME_HANDOFF_PATH",
            "CLAUSE_CONTINUATION_MANIFEST_PATH",
            "CLAUSE_CONTINUATION_HANDOFF_PATH",
            "CLAUSE_ZERO_RESEAL_PATH",
            "CLAUSE_ISOLATION_MANIFEST_PATH",
            "CLAUSE_ISOLATION_HANDOFF_PATH",
            "CONDITIONAL_PRIORITY_MANIFEST_PATH",
            "CONDITIONAL_PRIORITY_HANDOFF_PATH",
            "TENTH_MANIFEST_PATH",
            "TENTH_HANDOFF_PATH",
            "RETRY_MANIFEST_PATH",
            "RETRY_HANDOFF_PATH",
        ):
            with self.subTest(published=field), tempfile.TemporaryDirectory() as outside:
                published = Path(outside) / "published-successor.json"
                published.write_text("{}")
                with mock.patch.object(module, field, str(published)):
                    fixture = CampaignReservations()
                    try:
                        fixture.setUp()
                        try:
                            active = module.active_campaign()
                        except ledger.LedgerError as error:
                            self.fail(
                                f"the owned original fixture discovered external authority: {error}"
                            )
                        self.assertIs(type(active), module.Campaign)
                        self.assertEqual(str(fixture.state), active.path)
                        self.assertEqual([], active._state()["calls"])
                        self.assertEqual("{}", published.read_text())
                    finally:
                        fixture.doCleanups()

    def test_repeated_fixture_cannot_discover_published_successor_files(self) -> None:
        module = importlib.import_module("analyze_campaign")
        repeated = importlib.import_module("test_closure_qualification")
        for field in (
            "SUCCESSOR_MANIFEST_PATH",
            "SUCCESSOR_HANDOFF_PATH",
            "LOGIN_RESUME_MANIFEST_PATH",
            "LOGIN_RESUME_HANDOFF_PATH",
            "CLAUSE_CONTINUATION_MANIFEST_PATH",
            "CLAUSE_CONTINUATION_HANDOFF_PATH",
            "CLAUSE_ZERO_RESEAL_PATH",
            "CLAUSE_ISOLATION_MANIFEST_PATH",
            "CLAUSE_ISOLATION_HANDOFF_PATH",
            "CONDITIONAL_PRIORITY_MANIFEST_PATH",
            "CONDITIONAL_PRIORITY_HANDOFF_PATH",
            "TENTH_MANIFEST_PATH",
            "TENTH_HANDOFF_PATH",
            "RETRY_MANIFEST_PATH",
            "RETRY_HANDOFF_PATH",
        ):
            with self.subTest(published=field), tempfile.TemporaryDirectory() as outside:
                published = Path(outside) / "published-successor.json"
                published.write_text("{}")
                with mock.patch.object(module, field, str(published)):
                    fixture = repeated.RepeatedQualification()
                    try:
                        fixture.setUp()
                        try:
                            active = module.active_campaign()
                        except ledger.LedgerError as error:
                            self.fail(
                                f"the repeated fixture discovered external authority: {error}"
                            )
                        self.assertIs(type(active), module.Campaign)
                        self.assertTrue(Path(active.path).is_relative_to(fixture.root))
                        self.assertEqual("{}", published.read_text())
                    finally:
                        fixture.doCleanups()


class CampaignReservations(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.module: Any = importlib.import_module("analyze_campaign")
        except ModuleNotFoundError:
            self.module = None
        self.assertIsNotNone(self.module, "shared campaign reservation implementation missing")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.manifest = self.root / "reviewed.json"
        self.state = self.root / "campaign.json"
        self.replay = self.root / "replay.json"
        self.qualification = self.root / "qualification.json"
        self.replay.write_text(json.dumps({"calls": [{} for _ in range(631)]}))
        self.qualification.write_text(json.dumps({"calls": [{} for _ in range(28)]}))
        self.slots = {
            lane: [f"{lane}{n:03}" for n in range(count)]
            for lane, count in (("replay", 190), ("qualification", 30), ("live", 14))
        }
        self.body: dict[str, Any] = {
            "v": 1,
            "phase": "sealed",
            "limits": {"replay": 190, "qualification": 31, "live": 18},
            "retry_limits": {"replay": 0, "qualification": 1, "live": 4},
            "bindings": dict.fromkeys(self.slots, "a" * 64),
            "slots": self.slots,
            "requests": {
                lane: dict.fromkeys(slots, "a" * 64) for lane, slots in self.slots.items()
            },
            "order": ["replay", "qualification", "live"],
            "batches": {
                lane: [
                    slots[n : n + (10 if lane == "qualification" else 25)]
                    for n in range(0, len(slots), 10 if lane == "qualification" else 25)
                ]
                for lane, slots in self.slots.items()
            },
            "protocols": dict.fromkeys(self.slots, "synthetic-test-v1"),
            "evidence": {
                lane: dict.fromkeys(("scorer", "source", "marks"), "e" * 64) for lane in self.slots
            },
            "historical": {
                lane: {
                    "calls": count,
                    "sha256": self.sha(path),
                    "calls_digest": ledger.digest(json.loads(path.read_text())["calls"]),
                }
                for lane, path, count in (
                    ("replay", self.replay, 631),
                    ("qualification", self.qualification, 28),
                )
            },
        }
        for lane, slots in self.slots.items():
            size = 10 if lane == "qualification" else 25
            self.body["batches"][lane] = [
                slots[:1],
                *[slots[n : n + size] for n in range(1, len(slots), size)],
            ]
        self.manifest.write_text(json.dumps(self.body))
        for key, value in (
            ("MANIFEST_PATH", self.manifest),
            ("LEDGER_PATH", self.state),
            ("REPLAY_PATH", self.replay),
            ("QUALIFICATION_PATH", self.qualification),
            # Published successor authority must never select a real account in this fixture.
            ("SUCCESSOR_MANIFEST_PATH", self.root / "successor.json"),
            ("SUCCESSOR_HANDOFF_PATH", self.root / "handoff.json"),
            ("LOGIN_RESUME_MANIFEST_PATH", self.root / "login-resume.json"),
            ("LOGIN_RESUME_HANDOFF_PATH", self.root / "login-handoff.json"),
            ("CLAUSE_CONTINUATION_MANIFEST_PATH", self.root / "clause-continuation.json"),
            ("CLAUSE_CONTINUATION_HANDOFF_PATH", self.root / "clause-handoff.json"),
            ("CLAUSE_ZERO_RESEAL_PATH", self.root / "zero-reseal.json"),
            ("CLAUSE_ISOLATION_MANIFEST_PATH", self.root / "clause-isolation.json"),
            ("CLAUSE_ISOLATION_HANDOFF_PATH", self.root / "clause-isolation-handoff.json"),
            ("CONDITIONAL_PRIORITY_MANIFEST_PATH", self.root / "conditional-priority.json"),
            ("CONDITIONAL_PRIORITY_HANDOFF_PATH", self.root / "conditional-priority-handoff.json"),
            ("TENTH_MANIFEST_PATH", self.root / "tenth.json"),
            ("TENTH_HANDOFF_PATH", self.root / "tenth-handoff.json"),
            ("RETRY_MANIFEST_PATH", self.root / "retry.json"),
            ("RETRY_HANDOFF_PATH", self.root / "retry-handoff.json"),
        ):
            patch = mock.patch.object(self.module, key, str(value))
            patch.start()
            self.addCleanup(patch.stop)
        self.activate()

    def activate(self) -> None:
        if self.state.exists():
            self.assertEqual([], json.loads(self.state.read_text())["calls"])
            self.state.unlink()
        self.body["phase"] = "prepared"
        self.body.pop("activation_anchor", None)
        self.manifest.write_text(json.dumps(self.body))
        anchor = self.module.Campaign().initialize()
        self.body.update(phase="sealed", activation_anchor=anchor)
        self.manifest.write_text(json.dumps(self.body))

    @staticmethod
    def sha(path: Path) -> str:
        import hashlib  # noqa: PLC0415 - isolated digest helper

        return hashlib.sha256(path.read_bytes()).hexdigest()

    def campaign(self) -> Campaign:
        return cast("Campaign", self.module.Campaign())

    def charge(self, lane: str, slot: str, *, retry: bool = False) -> str:
        return self.campaign().reserve(lane, slot, "a" * 64, retry=retry)

    def fill_replay(self, *, accept: bool = True) -> None:
        self.fill_lane("replay", accept=accept)

    def fill_lane(self, lane: str, *, accept: bool = True) -> None:
        for n, group in enumerate(self.body["batches"][lane]):
            for slot in group:
                charge = self.charge(lane, slot)
                self.campaign().settle(charge, "usable")
            campaign = self.campaign()
            campaign.accept_batch(lane, n, acceptance(campaign, lane, n))
        if accept:
            campaign = self.campaign()
            campaign.accept(lane, acceptance(campaign, lane))

    def test_seeded_predecessor_matches_real_190_attempt_lifecycle(self) -> None:
        identities = [uuid.UUID(int=n) for n in range(1, 192)]
        with (
            mock.patch.object(uuid, "uuid4", side_effect=identities),
            mock.patch.object(time, "time", return_value=1000.0),
        ):
            self.activate()
            self.fill_replay()  # actual complete reserve/settle lifecycle
        actual_campaign = self.campaign()
        actual = actual_campaign._state()
        actual_receipts = {
            path.name: json.loads(path.read_text()) for path in actual_campaign.receipts.iterdir()
        }
        fixture = CampaignReservations()
        self.addCleanup(fixture.doCleanups)
        with (
            mock.patch.object(uuid, "uuid4", side_effect=identities),
            mock.patch.object(time, "time", return_value=1000.0),
        ):
            fixture.setUp()
            seed_predecessor(fixture.campaign(), "replay")
        seeded = fixture.campaign()._state()
        self.assertEqual(actual, seeded)
        self.assertEqual(
            actual_receipts,
            {
                path.name: json.loads(path.read_text())
                for path in fixture.campaign().receipts.iterdir()
            },
        )
        self.assertEqual(self.replay.read_bytes(), fixture.replay.read_bytes())
        self.assertEqual(self.qualification.read_bytes(), fixture.qualification.read_bytes())
        self.assertEqual(self.body["activation_anchor"], fixture.body["activation_anchor"])
        self.assertEqual(190, len(seeded["calls"]))
        charge = fixture.charge("qualification", fixture.slots["qualification"][0])
        self.assertEqual(charge, fixture.campaign()._state()["calls"][-1]["id"])

    def test_seeded_predecessor_retains_real_receipt_tamper_refusal(self) -> None:
        for changed in ("reservation", "classification", "missing", "proof", "history", "anchor"):
            with self.subTest(changed=changed):
                fixture = CampaignReservations()
                self.addCleanup(fixture.doCleanups)
                fixture.setUp()
                try:
                    fixture.activate_qualification_first()
                    campaign = fixture.campaign()
                    seed_predecessor(campaign, "qualification")
                    body = campaign._state()
                    call = body["calls"][0]
                    if changed == "reservation":
                        path = campaign.receipts / (call["id"] + ".json")
                        receipt = json.loads(path.read_text())
                        receipt["binding"] = "f" * 64
                        path.write_text(json.dumps(receipt))
                    elif changed == "classification":
                        path = campaign.receipts / (call["id"] + "-SETTLED.json")
                        receipt = json.loads(path.read_text())
                        receipt["status"] = "semantic-failed"
                        path.write_text(json.dumps(receipt))
                    elif changed == "missing":
                        (campaign.receipts / (call["id"] + "-SETTLED.json")).unlink()
                    elif changed == "proof":
                        path = campaign.receipts / "qualification-0-BATCH.json"
                        receipt = json.loads(path.read_text())
                        receipt["attempts_digest"] = "f" * 64
                        path.write_text(json.dumps(receipt))
                        body["accepted_batches"]["qualification:0"] = ledger.digest(receipt)
                        fixture.state.write_text(json.dumps(body))
                    elif changed == "history":
                        prefix = json.loads(fixture.qualification.read_text())
                        prefix["calls"][0]["changed"] = True
                        fixture.qualification.write_text(json.dumps(prefix))
                    else:
                        fixture.body["activation_anchor"] = "f" * 64
                        fixture.manifest.write_text(json.dumps(fixture.body))
                    with self.assertRaises(ledger.LedgerError):
                        fixture.campaign()._state()
                finally:
                    fixture.doCleanups()

    def test_seeded_predecessor_does_not_invent_held_requests(self) -> None:
        self.activate_qualification_first()
        campaign = self.campaign()
        before = self.state.read_bytes()
        with self.assertRaises(ledger.LedgerError):
            seed_predecessor(campaign, "replay")
        self.assertEqual(before, self.state.read_bytes())
        self.assertFalse(campaign.receipts.exists())

    def test_unregistered_or_changed_request_never_creates_a_charge(self) -> None:
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", "unregistered")
        with self.assertRaises(ledger.LedgerError):
            self.campaign().reserve("replay", self.slots["replay"][0], "b" * 64)
        self.assertEqual([], json.loads(self.state.read_text())["calls"])

    def test_only_approved_lane_order_can_be_registered(self) -> None:
        self.body["order"] = ["live", "qualification", "replay"]
        self.manifest.write_text(json.dumps(self.body))
        with self.assertRaises(ledger.LedgerError):
            self.campaign()

    def qualification_first(self) -> None:
        self.body["order"] = ["qualification", "replay", "live"]
        self.body["deferred_slots"] = {
            "qualification": [],
            "replay": self.slots["replay"].copy(),
            "live": self.slots["live"].copy(),
        }
        for lane in ("replay", "live"):
            self.body["requests"][lane] = {}
            for field in ("bindings", "protocols", "evidence"):
                self.body[field][lane] = None

    def activate_qualification_first(self) -> None:
        self.qualification_first()
        try:
            self.activate()
        except ledger.LedgerError as error:
            self.fail(f"reviewed qualification-first preparation refused: {error}")

    def test_qualification_first_reserves_without_replay_acceptance(self) -> None:
        self.activate_qualification_first()
        campaign = self.campaign()
        charge = campaign.reserve("qualification", self.slots["qualification"][0], "a" * 64)
        calls = campaign._state()["calls"]
        self.assertEqual(["qualification"], [call["lane"] for call in calls])
        self.assertEqual(charge, calls[0]["id"])
        self.assertEqual({}, campaign._state().get("accepted", {}))

    def test_qualification_first_held_lanes_cannot_launch_or_accept(self) -> None:
        self.activate_qualification_first()
        campaign = self.campaign()
        originals = (self.replay.read_bytes(), self.qualification.read_bytes())
        for lane in ("replay", "live"):
            with self.subTest(lane=lane):
                with self.assertRaises(ledger.LedgerError):
                    campaign.request_slot(lane, "a" * 64)
                with self.assertRaises(ledger.LedgerError):
                    campaign.reserve(lane, self.slots[lane][0], "a" * 64)
                with self.assertRaises(ledger.LedgerError):
                    campaign.accept(lane, acceptance(campaign, lane))
                with self.assertRaises(ledger.LedgerError):
                    campaign.accept_batch(lane, 0, acceptance(campaign, lane, 0))
        body = campaign._state()
        self.assertEqual([], body["calls"])
        self.assertEqual({}, body.get("accepted", {}))
        self.assertEqual({}, body.get("accepted_batches", {}))
        self.assertFalse(campaign.receipts.exists())
        self.assertEqual(originals, (self.replay.read_bytes(), self.qualification.read_bytes()))

    def test_qualification_first_requires_whole_holds_and_explicit_absence(self) -> None:
        self.qualification_first()
        valid = json.loads(json.dumps(self.body))
        for lane in ("replay", "live"):
            with self.subTest(lane=lane, malformed="partial-hold"):
                self.body = json.loads(json.dumps(valid))
                freed = self.body["deferred_slots"][lane].pop()
                self.body["requests"][lane][freed] = "a" * 64
                self.manifest.write_text(json.dumps(self.body))
                with self.assertRaises(ledger.LedgerError):
                    self.campaign()
            for field in ("bindings", "protocols", "evidence"):
                for mutation in ("missing", "populated"):
                    with self.subTest(lane=lane, field=field, mutation=mutation):
                        self.body = json.loads(json.dumps(valid))
                        if mutation == "missing":
                            del self.body[field][lane]
                        else:
                            self.body[field][lane] = valid[field]["qualification"]
                        self.manifest.write_text(json.dumps(self.body))
                        with self.assertRaises(ledger.LedgerError):
                            self.campaign()

    def test_qualification_first_requires_all_actual_qualification_bindings(self) -> None:
        self.qualification_first()
        valid = json.loads(json.dumps(self.body))
        for field in ("bindings", "protocols", "evidence", "requests"):
            for mutation in ("missing", "null"):
                with self.subTest(field=field, mutation=mutation):
                    self.body = json.loads(json.dumps(valid))
                    if mutation == "missing":
                        del self.body[field]["qualification"]
                    else:
                        self.body[field]["qualification"] = None
                    self.manifest.write_text(json.dumps(self.body))
                    with self.assertRaises(ledger.LedgerError):
                        self.campaign()
        self.body = json.loads(json.dumps(valid))
        first = self.slots["qualification"][0]
        self.body["deferred_slots"]["qualification"] = [first]
        del self.body["requests"]["qualification"][first]
        self.manifest.write_text(json.dumps(self.body))
        with self.assertRaises(ledger.LedgerError):
            self.campaign()

    def test_qualification_first_authority_change_refuses_before_charge(self) -> None:
        self.activate_qualification_first()
        campaign = self.campaign()
        self.body["evidence"]["qualification"]["source"] = "f" * 64
        self.manifest.write_text(json.dumps(self.body))
        with self.assertRaises(ledger.LedgerError):
            campaign.reserve("qualification", self.slots["qualification"][0], "a" * 64)
        self.assertEqual([], json.loads(self.state.read_text())["calls"])

    def test_qualification_first_pending_and_failed_attempts_still_stop_launches(self) -> None:
        self.activate_qualification_first()
        campaign = self.campaign()
        first = campaign.reserve("qualification", self.slots["qualification"][0], "a" * 64)
        with self.assertRaises(ledger.LedgerError):
            campaign.reserve("qualification", self.slots["qualification"][1], "a" * 64)
        campaign.settle(first, "semantic-failed")
        campaign.stop("semantic-failed")
        with self.assertRaises(ledger.LedgerError):
            campaign.reserve("qualification", self.slots["qualification"][1], "a" * 64)
        self.assertEqual(1, len(campaign._state()["calls"]))
        self.assertEqual("semantic-failed", campaign._state()["stop"])

    def test_qualification_first_native_chain_stops_at_31_additional_attempts(self) -> None:  # noqa: PLR0915 - preserve the joined native/shared charging lifecycle
        with mock.patch.object(sys, "path", [str(Path(__file__).parent), *sys.path]):
            fixture = importlib.import_module("test_closure_qualification").GrantFourAllowance()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        old_calls = json.loads(fixture.prefix)["calls"]
        self.assertEqual(28, len(old_calls))
        ids = [f"{n:016x}" for n in range(1, 11)]
        slots = [f"{cid}:r{repeat}" for repeat in (1, 2, 3) for cid in ids]
        self.slots["qualification"] = slots
        self.body["requests"]["qualification"] = dict.fromkeys(slots, "a" * 64)
        self.body["batches"]["qualification"] = [
            slots[:1],
            *[slots[n : n + 10] for n in range(1, len(slots), 10)],
        ]
        self.body["historical"]["qualification"] = {
            "calls": 28,
            "sha256": self.sha(fixture.ledger_path),
            "calls_digest": ledger.digest(old_calls),
        }
        patch = mock.patch.object(self.module, "QUALIFICATION_PATH", str(fixture.ledger_path))
        patch.start()
        self.addCleanup(patch.stop)
        scoring = importlib.import_module("score_abstention")
        scoring._runtime()
        from compass_runtime import observer  # noqa: PLC0415 - admitted synthetic delegate seam

        prompt = "owned synthetic qualification input"
        opening_binding = self.module.request_digest(
            prompt,
            dict.fromkeys(scoring.BINDING_KEYS),
            self.module.runtime_source_digest(Path(observer.__file__).parent),
            1024,
        )
        self.body["requests"]["qualification"][slots[0]] = opening_binding
        self.activate_qualification_first()
        campaign = self.campaign()
        fixture.campaign_key = campaign.binding
        fixture.closure_grant()
        native = fixture.fifth()
        native.campaign = campaign
        delegated: list[str] = []

        def delegate(words: str, *, output_cap_bytes: int) -> tuple[str, str]:
            self.assertEqual(prompt, words)
            self.assertEqual(1024, output_cap_bytes)
            calls = ledger.read(str(fixture.ledger_path))["calls"]
            shared = campaign._state()["calls"]
            self.assertEqual(29, len(calls))
            self.assertEqual(1, len(shared))
            self.assertEqual(shared[0]["id"], calls[-1]["campaign_charge"])
            self.assertEqual({}, campaign._state().get("accepted", {}))
            delegated.append(words)
            return "", "failed"

        charged_model = scoring._Charged(native, ids[0], delegate)
        self.assertEqual(("", "failed"), charged_model(prompt, output_cap_bytes=1024))
        retry = native.charge(ids[0], retry=True, request_binding=opening_binding)
        native.settle(retry, "ok")
        native.finish_exposure(retry, "usable")
        campaign.accept_batch("qualification", 0, acceptance(campaign, "qualification", 0))
        for batch, group in enumerate(self.body["batches"]["qualification"][1:], 1):
            for slot in group:
                cid, repeat = slot.split(":r")
                charged = native.charge(cid, repeat=int(repeat), request_binding="a" * 64)
                native.settle(charged, "ok")
                native.finish_exposure(charged, "usable")
            campaign.accept_batch(
                "qualification", batch, acceptance(campaign, "qualification", batch)
            )
        before = fixture.ledger_path.read_bytes()
        with self.assertRaises(ledger.SpendCapError):
            native.charge(ids[-1], repeat=3, request_binding="a" * 64)
        with self.assertRaises(ledger.SpendCapError):
            scoring._Charged(native, ids[-1], delegate, repeat=3)(prompt, output_cap_bytes=1024)
        self.assertEqual([prompt], delegated)
        self.assertEqual(before, fixture.ledger_path.read_bytes())
        calls = ledger.read(str(fixture.ledger_path))["calls"]
        shared = campaign._state()["calls"]
        self.assertEqual(59, len(calls))
        self.assertEqual(old_calls, calls[:28])
        self.assertEqual(31, len(shared))
        self.assertEqual({"qualification"}, {call["lane"] for call in shared})
        self.assertEqual(
            {call["id"] for call in shared},
            {call["campaign_charge"] for call in calls[28:]},
        )

    def test_a_later_slot_cannot_skip_the_next_fresh_or_unusable_slot(self) -> None:
        campaign = self.campaign()
        campaign.settle(self.charge("replay", self.slots["replay"][0]), "usable")
        campaign.accept_batch("replay", 0, acceptance(campaign, "replay", 0))
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][2])
        campaign.settle(self.charge("replay", self.slots["replay"][1]), "unusable")
        self.assertEqual(self.slots["replay"][1], campaign.request_slot("replay", "a" * 64))
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][2])
        self.assertEqual(2, len(campaign._state()["calls"]))

    def test_unbound_held_live_slots_never_charge_or_accept(self) -> None:
        self.body["deferred_slots"] = {
            "replay": [],
            "qualification": [],
            "live": self.slots["live"],
        }
        self.body["requests"]["live"] = {}
        self.activate()
        seed_predecessor(self.campaign(), "replay")
        seed_predecessor(self.campaign(), "qualification")
        campaign = self.campaign()
        with self.assertRaises(ledger.LedgerError):
            campaign.request_slot("live", "a" * 64)
        with self.assertRaises(ledger.LedgerError):
            self.charge("live", self.slots["live"][0])
        with self.assertRaises(ledger.LedgerError):
            campaign.accept("live", acceptance(campaign, "live"))
        self.assertEqual([], [c for c in campaign._state()["calls"] if c["lane"] == "live"])

    def test_missing_binding_on_nonheld_slot_refuses(self) -> None:
        del self.body["requests"]["live"][self.slots["live"][0]]
        self.manifest.write_text(json.dumps(self.body))
        with self.assertRaises(ledger.LedgerError):
            self.campaign()
        self.assertEqual([], json.loads(self.state.read_text())["calls"])

    def test_opening_unusable_call_allows_only_explicit_same_slot_retry(self) -> None:
        self.body["batches"]["live"] = [[self.slots["live"][0]], self.slots["live"][1:]]
        self.activate()
        seed_predecessor(self.campaign(), "replay")
        seed_predecessor(self.campaign(), "qualification")
        slot = self.slots["live"][0]
        first = self.charge("live", slot)
        self.campaign().settle(first, "unusable")
        with self.assertRaises(ledger.LedgerError):
            self.charge("live", slot)
        with self.assertRaises(ledger.LedgerError):
            self.charge("live", self.slots["live"][1])
        second = self.charge("live", slot, retry=True)
        self.campaign().settle(second, "usable")
        campaign = self.campaign()
        calls = [c for c in campaign._state()["calls"] if c["lane"] == "live"]
        self.assertEqual([1, 2], [call["availability_attempt"] for call in calls])
        campaign.accept_batch("live", 0, acceptance(campaign, "live", 0))
        self.charge("live", self.slots["live"][1])

    def test_bound_batch_can_pass_while_later_held_live_slots_cannot(self) -> None:
        held = self.slots["live"][-4:]
        self.body["deferred_slots"] = {"replay": [], "qualification": [], "live": held}
        for slot in held:
            del self.body["requests"]["live"][slot]
        self.activate()
        seed_predecessor(self.campaign(), "replay")
        seed_predecessor(self.campaign(), "qualification")
        campaign = self.campaign()
        campaign.settle(self.charge("live", self.slots["live"][0]), "usable")
        campaign.accept_batch("live", 0, acceptance(campaign, "live", 0))
        with self.assertRaises(ledger.LedgerError):
            campaign.accept("live", acceptance(campaign, "live"))
        with self.assertRaises(ledger.LedgerError):
            self.charge("live", held[0])

    def test_missing_old_prefix_cannot_initialize_new_authorization(self) -> None:
        self.qualification.unlink()
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][0])
        self.assertEqual([], json.loads(self.state.read_text())["calls"])

    def test_new_process_or_home_cannot_repeat_a_usable_slot(self) -> None:
        campaign = self.campaign()
        c = self.charge("replay", self.slots["replay"][0])
        campaign.settle(c, "usable")
        campaign.accept_batch("replay", 0, acceptance(campaign, "replay", 0))
        slot = self.slots["replay"][1]
        c = self.charge("replay", slot)
        self.campaign().settle(c, "usable")
        with (
            mock.patch.dict("os.environ", {"COMPASS_HOME": str(self.root / "another")}),
            self.assertRaises(ledger.LedgerError),
        ):
            self.charge("replay", slot)
        self.assertEqual(2, len(json.loads(self.state.read_text())["calls"]))

    def test_pending_or_orphan_charge_blocks_all_later_calls(self) -> None:
        campaign = self.campaign()
        c = self.charge("replay", self.slots["replay"][0])
        campaign.settle(c, "usable")
        campaign.accept_batch("replay", 0, acceptance(campaign, "replay", 0))
        self.charge("replay", self.slots["replay"][1])
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][2])
        self.assertEqual(2, len(json.loads(self.state.read_text())["calls"]))

    def test_deleted_ledger_with_reservation_receipt_cannot_reset_budget(self) -> None:
        c = self.charge("replay", self.slots["replay"][0])
        self.campaign().settle(c, "usable")
        self.state.unlink()
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][0])

    def test_semantic_failure_is_persistent_and_stops_every_lane(self) -> None:
        campaign = self.campaign()
        c = self.charge("replay", self.slots["replay"][0])
        campaign.settle(c, "usable")
        campaign.accept_batch("replay", 0, acceptance(campaign, "replay", 0))
        c = self.charge("replay", self.slots["replay"][1])
        self.campaign().settle(c, "protection-failed")
        for lane in self.slots:
            with self.subTest(lane=lane), self.assertRaises(ledger.LedgerError):
                self.charge(lane, self.slots[lane][2])

    def test_two_unusable_calls_stop_across_new_instances(self) -> None:
        seed_predecessor(self.campaign(), "replay")
        seed_predecessor(self.campaign(), "qualification")
        campaign = self.campaign()
        c = self.charge("live", self.slots["live"][0])
        campaign.settle(c, "usable")
        campaign.accept_batch("live", 0, acceptance(campaign, "live", 0))
        slot = self.slots["live"][1]
        for retry in (False, True):
            c = self.charge("live", slot, retry=retry)
            self.campaign().settle(c, "unusable")
        with self.assertRaises(ledger.LedgerError):
            self.charge("live", slot, retry=True)
        calls = json.loads(self.state.read_text())["calls"]
        self.assertEqual(3, len([c for c in calls if c["lane"] == "live"]))

    def test_rewriting_a_settled_failure_cannot_erase_its_stop(self) -> None:
        campaign = self.campaign()
        c = self.charge("replay", self.slots["replay"][0])
        campaign.settle(c, "usable")
        campaign.accept_batch("replay", 0, acceptance(campaign, "replay", 0))
        c = self.charge("replay", self.slots["replay"][1])
        campaign.settle(c, "semantic-failed")
        body = json.loads(self.state.read_text())
        body["calls"][-1]["status"] = "usable"
        self.state.write_text(json.dumps(body))
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][2])

    def test_activated_manifest_cannot_reinitialize_after_all_private_proofs_are_deleted(
        self,
    ) -> None:
        self.state.unlink()
        with self.assertRaises(ledger.LedgerError):
            self.campaign().initialize()
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][0])
        self.assertFalse(self.state.exists())

    def test_restoring_genesis_cannot_ignore_existing_charge_and_classification_receipts(
        self,
    ) -> None:
        genesis = self.state.read_bytes()
        c = self.charge("replay", self.slots["replay"][0])
        self.campaign().settle(c, "usable")
        self.state.write_bytes(genesis)
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][0])

    def test_later_lane_requires_all_predecessor_slots_usable(self) -> None:
        with self.assertRaises(ledger.LedgerError):
            self.charge("qualification", self.slots["qualification"][0])
        seed_predecessor(self.campaign(), "replay")
        c = self.charge("qualification", self.slots["qualification"][0])
        self.assertTrue(c)

    def test_qualification_retry_ceiling_cannot_replace_successes(self) -> None:
        seed_predecessor(self.campaign(), "replay")
        first, second = self.slots["qualification"][:2]
        c = self.charge("qualification", first)
        self.campaign().settle(c, "unusable")
        c = self.charge("qualification", first, retry=True)
        self.campaign().settle(c, "usable")
        campaign = self.campaign()
        campaign.accept_batch("qualification", 0, acceptance(campaign, "qualification", 0))
        c = self.charge("qualification", second)
        self.campaign().settle(c, "unusable")
        with self.assertRaises(ledger.LedgerError):
            self.charge("qualification", second, retry=True)
        with self.assertRaises(ledger.LedgerError):
            self.charge("qualification", first, retry=True)

    def test_lane_and_aggregate_caps_account_all_reserved_attempts(self) -> None:  # noqa: C901 - observe every unchanged native transition and retry
        # This one retains every actual transition; predecessor seeding cannot prove caps.
        reserved: list[str] = []
        settled: list[str] = []
        batches: list[tuple[str, int]] = []
        accepted: list[str] = []
        native_reserve = self.module.Campaign.reserve
        native_settle = self.module.Campaign.settle
        native_batch = self.module.Campaign.accept_batch
        native_accept = self.module.Campaign.accept

        def reserve(*args: Any, **kwargs: Any) -> str:
            charge: str = native_reserve(*args, **kwargs)
            reserved.append(charge)
            return charge

        def settle(*args: Any, **kwargs: Any) -> None:
            native_settle(*args, **kwargs)
            settled.append(args[1])

        def accept_batch(*args: Any, **kwargs: Any) -> None:
            native_batch(*args, **kwargs)
            batches.append((args[1], args[2]))

        def accept_lane(*args: Any, **kwargs: Any) -> None:
            native_accept(*args, **kwargs)
            accepted.append(args[1])

        for name, observed in (
            ("reserve", reserve),
            ("settle", settle),
            ("accept_batch", accept_batch),
            ("accept", accept_lane),
        ):
            self.enterContext(mock.patch.object(self.module.Campaign, name, observed))
        self.fill_replay()  # actual complete reserve/settle lifecycle
        for lane in ("qualification", "live"):
            retry_slots = 1 if lane == "qualification" else 4
            for n, group in enumerate(self.body["batches"][lane]):
                for slot in group:
                    if self.slots[lane].index(slot) < retry_slots:
                        c = self.charge(lane, slot)
                        self.campaign().settle(c, "unusable")
                        c = self.charge(lane, slot, retry=True)
                    else:
                        c = self.charge(lane, slot)
                    self.campaign().settle(c, "usable")
                campaign = self.campaign()
                campaign.accept_batch(lane, n, acceptance(campaign, lane, n))
            campaign = self.campaign()
            campaign.accept(lane, acceptance(campaign, lane))
        calls = json.loads(self.state.read_text())["calls"]
        self.assertEqual(239, len(calls))
        self.assertEqual(31, sum(c["lane"] == "qualification" for c in calls))
        self.assertEqual(18, sum(c["lane"] == "live" for c in calls))
        self.assertEqual(239, len(reserved))
        self.assertEqual(reserved, settled)
        self.assertEqual(
            [
                (lane, batch)
                for lane in self.slots
                for batch in range(len(self.body["batches"][lane]))
            ],
            batches,
        )
        self.assertEqual(["replay", "qualification", "live"], accepted)
        for lane in self.slots:
            with self.subTest(lane=lane), self.assertRaises(ledger.LedgerError):
                self.charge(lane, self.slots[lane][-1], retry=True)

    def test_zero_call_coverage_failure_latches_across_processes(self) -> None:
        self.campaign().stop("coverage-failed")
        self.assertEqual([], json.loads(self.state.read_text())["calls"])
        with self.assertRaises(ledger.LedgerError):
            self.charge("replay", self.slots["replay"][0])

    def test_usable_replay_slots_do_not_authorize_a_later_lane_without_acceptance(self) -> None:
        seed_predecessor(self.campaign(), "replay", accept=False)
        with self.assertRaises(ledger.LedgerError):
            self.charge("qualification", self.slots["qualification"][0])

    def test_review_and_native_output_bindings_are_required_for_acceptance(self) -> None:
        seed_predecessor(self.campaign(), "replay", accept=False)
        for key, value in (
            ("review_digest", ""),
            ("output_digest", ""),
            ("usable_slots", 189),
            ("coverage_failures", False),
            ("attempts_digest", "f" * 64),
        ):
            proof = acceptance(self.campaign(), "replay")
            proof[key] = value
            with self.subTest(key=key), self.assertRaises(ledger.LedgerError):
                self.campaign().accept("replay", proof)

    def test_order_is_explicit_and_not_module_lane_enumeration(self) -> None:
        self.body["order"] = ["qualification", "replay", "live"]
        self.body["batches"]["qualification"] = [
            self.slots["qualification"][:1],
            *[self.slots["qualification"][n : n + 10] for n in range(1, 30, 10)],
        ]
        with self.assertRaises(ledger.LedgerError):
            self.activate()

    def test_deleted_acceptance_receipt_blocks_every_new_process(self) -> None:
        seed_predecessor(self.campaign(), "replay")
        (Path(str(self.state) + ".reservations") / "replay-ACCEPTED.json").unlink()
        with self.assertRaises(ledger.LedgerError):
            self.charge("qualification", self.slots["qualification"][0])

    def test_next_batch_refuses_without_review_even_with_all_usable_outputs(self) -> None:
        self.body["batches"]["replay"] = [
            self.slots["replay"][:1],
            *[self.slots["replay"][n : n + 25] for n in range(1, 190, 25)],
        ]
        self.manifest.write_text(json.dumps(self.body))
        for slot in self.slots["replay"][:1]:
            self.campaign().settle(self.charge("replay", slot), "usable")
        with self.assertRaises(self.module.AwaitingReviewError):
            self.charge("replay", self.slots["replay"][1])
        campaign = self.campaign()
        proof = acceptance(campaign, "replay")
        own = campaign._state()["calls"]
        proof.update(
            batch=0,
            slots_digest=ledger.digest(self.slots["replay"][:1]),
            expected_slots=1,
            usable_slots=1,
            attempts_digest=ledger.digest(own),
        )
        campaign.accept_batch("replay", 0, proof)
        self.assertTrue(self.charge("replay", self.slots["replay"][1]))
