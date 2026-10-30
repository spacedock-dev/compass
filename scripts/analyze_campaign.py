"""Reviewed closure reservations shared by replay, qualification and live attempts.

Only salted slots, request digests and closed statuses reach this account ledger.
The fixed repository manifest admits 190/31/18 attempts, never 239+31+18.
A reviewed successor preserves the stopped original two calls and admits a fresh
31 qualification attempts, with 190 replay and 18 live held: 241 cumulatively.
One finite login recovery preserves those four spent calls and admits 31
available qualification attempts (29 carried and two renewed): 243 cumulatively.
Fixed clause corrections preserve six, then eight spent attempts and admit
31 available qualification attempts: 245, then 247 cumulatively.
Every charge has an immutable receipt; missing state cannot refund its attempts.
This is an operator evaluation guard, not provider authentication or a token cap.
"""

# ruff: noqa: INP001 - operator scripts intentionally have no package root
from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, cast

import abstention_ledger as authority

MANIFEST_PATH = str(Path(__file__).resolve().parents[1] / "docs/drift-replay/closure-campaign.json")
SUCCESSOR_MANIFEST_PATH = str(Path(MANIFEST_PATH).with_name("closure-campaign-successor.json"))
SUCCESSOR_HANDOFF_PATH = str(Path(MANIFEST_PATH).with_name("closure-successor-handoff.json"))
LOGIN_RESUME_MANIFEST_PATH = str(
    Path(MANIFEST_PATH).with_name("closure-campaign-login-resume.json")
)
LOGIN_RESUME_HANDOFF_PATH = str(Path(MANIFEST_PATH).with_name("closure-login-resume-handoff.json"))
CLAUSE_CONTINUATION_MANIFEST_PATH = str(
    Path(MANIFEST_PATH).with_name("closure-campaign-clause-continuation.json")
)
CLAUSE_CONTINUATION_HANDOFF_PATH = str(
    Path(MANIFEST_PATH).with_name("closure-clause-continuation-handoff.json")
)
CLAUSE_ISOLATION_MANIFEST_PATH = str(
    Path(MANIFEST_PATH).with_name("closure-campaign-clause-isolation.json")
)
CLAUSE_ISOLATION_HANDOFF_PATH = str(
    Path(MANIFEST_PATH).with_name("closure-clause-isolation-handoff.json")
)
CONDITIONAL_PRIORITY_MANIFEST_PATH = str(
    Path(MANIFEST_PATH).with_name("closure-campaign-conditional-priority.json")
)
CONDITIONAL_PRIORITY_HANDOFF_PATH = str(
    Path(MANIFEST_PATH).with_name("closure-conditional-priority-handoff.json")
)
TENTH_MANIFEST_PATH = str(Path(MANIFEST_PATH).with_name("closure-campaign-tenth.json"))
TENTH_HANDOFF_PATH = str(Path(MANIFEST_PATH).with_name("closure-tenth-handoff.json"))
RETRY_MANIFEST_PATH = str(Path(MANIFEST_PATH).with_name("closure-campaign-retry.json"))
RETRY_HANDOFF_PATH = str(Path(MANIFEST_PATH).with_name("closure-retry-handoff.json"))
CLAUSE_ZERO_RESEAL_PATH = str(Path(MANIFEST_PATH).with_name("closure-clause-zero-reseal.json"))
LEDGER_PATH = authority.study_path("analyze-closure-spend.json")
REPLAY_PATH = authority.study_path("drift-replay", "spend.json")
QUALIFICATION_PATH = authority.LEDGER_PATH
LANES = ("replay", "qualification", "live")
LIMITS = {"replay": 190, "qualification": 31, "live": 18}
RETRIES = {"replay": 0, "qualification": 1, "live": 4}
SLOTS = {"replay": 190, "qualification": 30, "live": 14}
STATUSES = (
    "charged",
    "usable",
    "unusable",
    "semantic-failed",
    "coverage-failed",
    "protection-failed",
)
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_SLOT = re.compile(r"^[a-z0-9][a-z0-9:_-]{0,95}$")


class AwaitingReviewError(authority.LedgerError):
    """A completed batch awaits review; no provider attempt failed."""


# Each fixed successor generation past the fifth: the allowance its grant must carry, and the
# native ceiling the chain admits while it is active. Every ancestor epoch reads its bounds
# from here, so a new generation is one row rather than a new branch in five validators.
_SUCCESSORS = {
    6: ("login_resume_allowance", authority.LOGIN_RESUME_CAP),
    7: ("clause_continuation_allowance", authority.CLAUSE_CONTINUATION_CAP),
    8: ("clause_isolation_allowance", authority.CLAUSE_ISOLATION_CAP),
    9: ("conditional_priority_allowance", authority.CONDITIONAL_PRIORITY_CAP),
    10: ("tenth_continuation_allowance", authority.TENTH_CAP),
    # The retry's own ceiling is P + 31; ancestors bound the chain by its largest value.
    11: ("retry_continuation_allowance", authority.RETRY_MAX_CAP),
}


def _successor_generation(active: dict[str, Any] | None) -> int:
    """The active grant's generation when it carries its own fixed allowance, else the fifth."""
    if active:
        entry = _SUCCESSORS.get(active["generation"])
        if entry and active.get(entry[0]):
            return int(active["generation"])
    return 5


def _native_ceiling(generation: int) -> int:
    """How many native charges the chain may hold while `generation` is the active successor."""
    return _SUCCESSORS[generation][1] if generation in _SUCCESSORS else authority.SUCCESSOR_CAP


def active_campaign() -> Campaign | None:  # noqa: PLR0911 - fixed finite generation surfaces refuse independently
    """An existing fixed manifest or account receipt cannot be bypassed by removing one."""
    if (
        os.path.lexists(str(RETRY_MANIFEST_PATH))
        or os.path.lexists(str(RETRY_HANDOFF_PATH))
        or (LEDGER_PATH and os.path.lexists(str(LEDGER_PATH + ".epochs/7")))
    ):
        return RetryCampaign()
    if (
        os.path.lexists(str(TENTH_MANIFEST_PATH))
        or os.path.lexists(str(TENTH_HANDOFF_PATH))
        or (LEDGER_PATH and os.path.lexists(str(LEDGER_PATH + ".epochs/6")))
    ):
        return TenthCampaign()
    if (
        os.path.lexists(str(CONDITIONAL_PRIORITY_MANIFEST_PATH))
        or os.path.lexists(str(CONDITIONAL_PRIORITY_HANDOFF_PATH))
        or (LEDGER_PATH and os.path.lexists(str(LEDGER_PATH + ".epochs/5")))
    ):
        return ConditionalPriorityCampaign()
    if (
        os.path.lexists(str(CLAUSE_ISOLATION_MANIFEST_PATH))
        or os.path.lexists(str(CLAUSE_ISOLATION_HANDOFF_PATH))
        or (LEDGER_PATH and os.path.lexists(str(LEDGER_PATH + ".epochs/4")))
    ):
        return ClauseIsolationCampaign()
    if (
        os.path.lexists(str(CLAUSE_CONTINUATION_MANIFEST_PATH))
        or os.path.lexists(str(CLAUSE_CONTINUATION_HANDOFF_PATH))
        or os.path.lexists(str(CLAUSE_ZERO_RESEAL_PATH))
        or (LEDGER_PATH and os.path.lexists(str(LEDGER_PATH + ".epochs/3")))
    ):
        return ClauseContinuationCampaign()
    if (
        os.path.lexists(str(LOGIN_RESUME_MANIFEST_PATH))
        or os.path.lexists(str(LOGIN_RESUME_HANDOFF_PATH))
        or (LEDGER_PATH and os.path.lexists(str(LEDGER_PATH + ".epochs/2")))
    ):
        return LoginResumeCampaign()
    if (
        os.path.lexists(str(SUCCESSOR_MANIFEST_PATH))
        or os.path.lexists(str(SUCCESSOR_HANDOFF_PATH))
        or (LEDGER_PATH and os.path.lexists(str(LEDGER_PATH + ".epochs")))
    ):
        return SuccessorCampaign()
    if os.path.lexists(str(MANIFEST_PATH)) or (
        LEDGER_PATH
        and (
            os.path.lexists(str(LEDGER_PATH)) or os.path.lexists(str(LEDGER_PATH + ".reservations"))
        )
    ):
        return Campaign()
    return None


def request_digest(
    prompt: str,
    producer: Any,
    source_digest: str,
    output_cap_bytes: int,
    *,
    shim_digest: str = "",
    contract_digest: str = "",
) -> str:
    """Bind actual transport words and fixed runtime source without retaining either."""
    return authority.digest(
        {
            "prompt": hashlib.sha256(prompt.encode()).hexdigest(),
            "producer": producer,
            "source": source_digest,
            "output_cap_bytes": output_cap_bytes,
            "study_shim": shim_digest,
            "study_contract": contract_digest,
        }
    )


def verified_transport_binding(
    config: Any, verified: Any, observer: Any, *, claude_executor: Any = None
) -> dict[str, Any]:
    """Bind the verified CLI and actual argv without launching a provider."""
    import score_abstention  # noqa: PLC0415 - operator CLI verification/capture
    from compass_runtime import reading_route  # noqa: PLC0415 - runtime already admitted

    destination = reading_route.destination("claude")
    if destination != reading_route.VENDORS["claude"]:
        raise authority.LedgerError("the bound transport destination is not Anthropic")
    result = {
        "reading": observer.claude_reading_provenance(config),
        "binary": verified.shown,
        "binary_sha256": verified.identity[-1],
        "cli_version": verified.version,
        "signature": verified.signature,
        "destination": destination,
        "argv_digest": score_abstention.argv_digest(
            "claude", config, claude_executor=claude_executor
        ),
    }
    validate_transport_binding(result)
    return result


def validate_transport_binding(value: Any) -> None:
    from compass_runtime import reading_route  # noqa: PLC0415 - admitted native transport

    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "reading",
            "binary",
            "binary_sha256",
            "cli_version",
            "signature",
            "destination",
            "argv_digest",
        }
        or not isinstance(value["reading"], dict)
        or not value["reading"]
        or value["destination"] != reading_route.VENDORS["claude"]
        or any(
            not isinstance(value[k], str) or not _DIGEST.fullmatch(value[k])
            for k in ("binary_sha256", "argv_digest")
        )
        or any(
            not isinstance(value[k], str) or not 1 <= len(value[k]) <= 2048
            for k in ("binary", "cli_version", "signature")
        )
    ):
        raise authority.LedgerError("the actual verified transport binding is unavailable")


def runtime_source_digest(root: Path) -> str:
    """Hash the shipped Python runtime bytes; source changes cannot inherit old admission."""
    files = sorted(root.rglob("*.py"))
    if not files or len(files) > 256:
        raise authority.LedgerError("the runtime source inventory is unavailable")
    parts = []
    for path in files:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
            raise authority.LedgerError("the runtime source exceeds its bound")
        parts.append((str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()))
    return authority.digest(parts)


def _read(path: str | None, label: str) -> Any:
    if not path:
        raise authority.LedgerError("the account's canonical home is unavailable")
    return authority._review_json(path, label, cap=2 * 1024 * 1024)  # noqa: SLF001 - shared bounded ledger reader


def _manifest(path: str | None = None) -> tuple[dict[str, Any], str]:  # noqa: C901, PLR0912 - each authority field fails closed independently
    body = _read(path or MANIFEST_PATH, "closure campaign manifest")
    if (
        not isinstance(body, dict)
        or type(body.get("v")) is not int
        or body["v"] != 1
        or body.get("phase") not in ("prepared", "sealed")
    ):
        raise authority.LedgerError("the closure campaign is not sealed")
    if body["phase"] == "sealed" and (
        not isinstance(body.get("activation_anchor"), str)
        or not _DIGEST.fullmatch(body["activation_anchor"])
    ):
        raise authority.LedgerError("the reviewed campaign activation anchor is missing")
    if (
        not isinstance(body.get("order"), list)
        or len(body["order"]) != 3
        or any(not isinstance(lane, str) for lane in body["order"])
        or body["order"]
        not in (["replay", "qualification", "live"], ["qualification", "replay", "live"])
    ):
        raise authority.LedgerError("the reviewed study order is missing")
    if any(
        not isinstance(body.get(field), dict)
        for field in (
            "limits",
            "retry_limits",
            "bindings",
            "slots",
            "evidence",
            "protocols",
            "historical",
            "requests",
        )
    ):
        raise authority.LedgerError("the reviewed campaign fields are malformed")
    if (
        body.get("limits") != LIMITS
        or body.get("retry_limits") != RETRIES
        or any(
            type((body.get(field) or {}).get(lane)) is not int
            for field in ("limits", "retry_limits")
            for lane in LANES
        )
    ):
        raise authority.LedgerError("the closure campaign has another allowance")
    held = body.get("deferred_slots", {lane: [] for lane in LANES})
    if not isinstance(held, dict) or set(held) != set(LANES):
        raise authority.LedgerError("the explicitly deferred campaign slots are malformed")
    qualification_first = body["order"] == ["qualification", "replay", "live"]
    for lane in LANES:
        slots = (body.get("slots") or {}).get(lane)
        if (
            not isinstance(slots, list)
            or len(slots) != SLOTS[lane]
            or any(not isinstance(slot, str) or not _SLOT.fullmatch(slot) for slot in slots)
            or len(set(slots)) != len(slots)
        ):
            raise authority.LedgerError("the registered campaign slots are malformed")
        requests = body["requests"].get(lane)
        if (
            not isinstance(held[lane], list)
            or any(not isinstance(slot, str) or slot not in slots for slot in held[lane])
            or len(set(held[lane])) != len(held[lane])
        ):
            raise authority.LedgerError("the deferred campaign slots are unregistered")
        if (
            not isinstance(requests, dict)
            or set(requests) != set(slots) - set(held[lane])
            or any(
                not isinstance(value, str) or not _DIGEST.fullmatch(value)
                for value in requests.values()
            )
        ):
            raise authority.LedgerError("the actual campaign requests are unbound")
        if qualification_first:
            if lane == "qualification":
                if held[lane]:
                    raise authority.LedgerError(
                        "qualification-first requires every qualification slot"
                    )
            else:
                if set(held[lane]) != set(slots) or any(
                    lane not in body[field] or body[field][lane] is not None
                    for field in ("bindings", "protocols", "evidence")
                ):
                    raise authority.LedgerError(
                        "qualification-first requires completely held and unbound later lanes"
                    )
                continue
        evidence = body["evidence"].get(lane)
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"scorer", "source", "marks"}
            or any(
                not isinstance(value, str) or not _DIGEST.fullmatch(value)
                for value in evidence.values()
            )
            or not isinstance(body["protocols"].get(lane), str)
            or not _SLOT.fullmatch(body["protocols"][lane])
        ):
            raise authority.LedgerError("the reviewed measurement protocol is unbound")
        binding = body["bindings"].get(lane)
        if not isinstance(binding, str) or not _DIGEST.fullmatch(binding):
            raise authority.LedgerError("the closure request binding is missing")
    batches = body.get("batches")
    if not isinstance(batches, dict) or set(batches) != set(LANES):
        raise authority.LedgerError("the registered batch boundaries are missing")
    for lane in LANES:
        groups = batches[lane]
        if (
            not isinstance(groups, list)
            or not groups
            or any(
                not isinstance(group, list)
                or not 1 <= len(group) <= (10 if lane == "qualification" else 25)
                for group in groups
            )
            or [slot for group in groups for slot in group] != body["slots"][lane]
        ):
            raise authority.LedgerError("the registered batches do not partition the lane")
        if len(groups[0]) != 1:
            raise authority.LedgerError("each lane's opening batch must be one availability call")
    # Digest normalized reviewed fields; formatting does not change authorization.
    return body, authority.digest(
        {key: value for key, value in body.items() if key not in ("phase", "activation_anchor")}
    )


def _history(manifest: dict[str, Any]) -> None:
    for lane, path, count in (
        ("replay", REPLAY_PATH, 631),
        ("qualification", QUALIFICATION_PATH, 28),
    ):
        expected = (manifest.get("historical") or {}).get(lane)
        if (
            not isinstance(expected, dict)
            or type(expected.get("calls")) is not int
            or expected["calls"] != count
            or not isinstance(expected.get("sha256"), str)
            or not _DIGEST.fullmatch(expected["sha256"])
        ):
            raise authority.LedgerError("the historical campaign prefix is unbound")
        body = _read(path, "historical spend prefix")
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("calls"), list)
            or len(body["calls"]) != count
        ):
            raise authority.LedgerError("the historical campaign prefix has changed")
        if hashlib.sha256(Path(str(path)).read_bytes()).hexdigest() != expected["sha256"]:
            raise authority.LedgerError("the historical campaign prefix has changed")
    _prefixes(manifest)


def _prefixes(manifest: dict[str, Any]) -> None:
    for lane, path, count in (
        ("replay", REPLAY_PATH, 631),
        ("qualification", QUALIFICATION_PATH, 28),
    ):
        expected = manifest["historical"][lane].get("calls_digest")
        body = _read(path, "historical charged prefix")
        if (
            not isinstance(expected, str)
            or not _DIGEST.fullmatch(expected)
            or not isinstance(body, dict)
            or not isinstance(body.get("calls"), list)
            or len(body["calls"]) < count
            or authority.digest(body["calls"][:count]) != expected
        ):
            raise authority.LedgerError("the original charged prefix was altered or removed")


def _receipt(call: dict[str, Any]) -> dict[str, Any]:
    return {
        key: call[key]
        for key in ("id", "at", "lane", "slot", "binding", "retry", "availability_attempt")
    }


def _valid_call(call: Any, manifest: dict[str, Any]) -> bool:
    return (
        isinstance(call, dict)
        and isinstance(call.get("id"), str)
        and re.fullmatch(r"[0-9a-f]{32}", call["id"]) is not None
        and call.get("lane") in LANES
        and call.get("slot") in manifest["slots"][call["lane"]]
        and call["slot"] in manifest["requests"][call["lane"]]
        and call.get("binding") == manifest["requests"][call["lane"]][call["slot"]]
        and type(call.get("retry")) is bool
        and type(call.get("availability_attempt")) is int
        and call["availability_attempt"] in (0, 1, 2)
        and call.get("status") in STATUSES
        and type(call.get("at")) in (float, int)
        and math.isfinite(call["at"])
    )


class Campaign:
    """One immutable manifest and one account-wide, serial, persistent charge stream."""

    stop_on_semantic_failure = True

    def __init__(self) -> None:
        self.manifest, self.binding = _manifest()
        if not LEDGER_PATH:
            raise authority.LedgerError("the account's canonical home is unavailable")
        self.path = LEDGER_PATH
        self.receipts = Path(self.path + ".reservations")

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        return _manifest()

    def _read_state(self) -> dict[str, Any]:
        return cast("dict[str, Any]", _read(self.path, "closure campaign ledger"))

    def _persist(self, body: dict[str, Any]) -> None:
        authority._write(self.path, body)  # noqa: SLF001 - atomic canonical ledger writer

    def initialize(self) -> str:
        """Create a zero-charge genesis for review; activation requires its public digest.

        No activated or existing campaign is initialized again. No provider runs.
        """
        with authority.locked(self.path):
            current, key = self._current_manifest()
            if current != self.manifest or key != self.binding:
                raise authority.LedgerError("the preparation changed before genesis initialization")
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or os.path.lexists(self.path)
                or os.path.lexists(str(self.receipts))
            ):
                raise authority.LedgerError("the campaign genesis cannot be initialized again")
            _history(self.manifest)
            body = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            self._persist(body)
            return authority.digest(body)

    def _state(self) -> dict[str, Any]:  # noqa: C901, PLR0912, PLR0915 - validate the append-only receipt chain before mutation
        if self.receipts.is_symlink():
            raise authority.LedgerError("the campaign receipts are a symlink")
        names = (
            list(itertools.islice(self.receipts.iterdir(), 717)) if self.receipts.exists() else []
        )
        if len(names) > 716:
            raise authority.LedgerError("the campaign receipt directory exceeds its bound")
        stop_path = self.receipts / "STOP.json"
        if not os.path.lexists(self.path):
            raise authority.LedgerError(
                "the initialized campaign ledger is missing; no automatic genesis is allowed"
            )
        body = self._read_state()
        _prefixes(self.manifest)
        if (
            not isinstance(body, dict)
            or type(body.get("v")) is not int
            or body["v"] != 1
            or body.get("manifest_digest") != self.binding
            or not isinstance(body.get("calls"), list)
            or len(body["calls"]) > 239
            or any(not _valid_call(c, self.manifest) for c in body["calls"])
        ):
            raise authority.LedgerError("the campaign ledger has changed")
        nonce = body.get("genesis_nonce")
        genesis: dict[str, Any] = {
            "v": 1,
            "manifest_digest": self.binding,
            "calls": [],
            "genesis_nonce": nonce,
        }
        if (
            not isinstance(nonce, str)
            or not re.fullmatch(r"[0-9a-f]{32}", nonce)
            or self.manifest["phase"] != "sealed"
            or authority.digest(genesis) != self.manifest["activation_anchor"]
        ):
            raise authority.LedgerError("the campaign genesis does not match reviewed activation")
        calls = body["calls"]
        stopped = body.get("stop")
        if stopped is not None:
            if stopped not in ("semantic-failed", "coverage-failed", "protection-failed"):
                raise authority.LedgerError("the campaign stop classification changed")
            if _read(str(stop_path), "campaign stop receipt") != {
                "stop": stopped,
                "manifest_digest": self.binding,
            }:
                raise authority.LedgerError("the campaign stop receipt changed")
        accepted = body.get("accepted", {})
        accepted_batches = body.get("accepted_batches", {})
        if not isinstance(accepted, dict) or any(lane not in LANES for lane in accepted):
            raise authority.LedgerError("the accepted-lane index changed")
        if (
            not isinstance(accepted_batches, dict)
            or len({c["id"] for c in calls}) != len(calls)
            or len(names)
            != len(calls)
            + sum(call["status"] != "charged" for call in calls)
            + len(accepted)
            + len(accepted_batches)
            + int(stopped is not None)
        ):
            raise authority.LedgerError("the campaign receipt chain has changed")
        for call in calls:
            if _read(str(self.receipts / (call["id"] + ".json")), "campaign receipt") != _receipt(
                call
            ):
                raise authority.LedgerError("the campaign reservation was rewritten")
            if call["status"] != "charged":
                receipt = _read(
                    str(self.receipts / (call["id"] + "-SETTLED.json")),
                    "campaign classification receipt",
                )
                if receipt != {
                    "id": call["id"],
                    "status": call["status"],
                    "manifest_digest": self.binding,
                }:
                    raise authority.LedgerError("the settled campaign classification was rewritten")
        for lane in LANES:
            own = [c for c in calls if c["lane"] == lane]
            if len(own) > LIMITS[lane] or sum(c["retry"] for c in own) > RETRIES[lane]:
                raise authority.LedgerError("the campaign allowance was exceeded")
        for lane, proof_digest in accepted.items():
            proof = _read(
                str(self.receipts / (lane + "-ACCEPTED.json")), "accepted measurement receipt"
            )
            if authority.digest(proof) != proof_digest:
                raise authority.LedgerError("the accepted measurement receipt changed")
            self._validate_acceptance(lane, proof, calls)
        for batch, proof_digest in accepted_batches.items():
            if not isinstance(batch, str) or not re.fullmatch(
                r"(?:replay|qualification|live):[0-9]{1,2}", batch
            ):
                raise authority.LedgerError("the accepted batch index changed")
            lane, index = batch.split(":")
            if int(index) >= len(self.manifest["batches"][lane]):
                raise authority.LedgerError("the accepted batch is unregistered")
            proof = _read(
                str(self.receipts / (batch.replace(":", "-") + "-BATCH.json")),
                "accepted batch receipt",
            )
            if authority.digest(proof) != proof_digest:
                raise authority.LedgerError("the accepted batch receipt changed")
            self._validate_acceptance(lane, proof, calls, batch=int(index))
        return body

    def _validate_acceptance(
        self, lane: str, proof: Any, calls: list[dict[str, Any]], *, batch: int | None = None
    ) -> None:
        slots = (
            self.manifest["slots"][lane] if batch is None else self.manifest["batches"][lane][batch]
        )
        if set(slots) & set(self.manifest.get("deferred_slots", {}).get(lane, [])):
            raise authority.LedgerError("an explicitly deferred slot cannot pass")
        own = [call for call in calls if call["lane"] == lane and call["slot"] in slots]
        latest = {call["slot"]: call["status"] for call in own}
        expected: dict[str, Any] = {
            "v": 1,
            "lane": lane,
            "manifest_digest": self.binding,
            "protocol": self.manifest["protocols"][lane],
            "binding": self.manifest["bindings"][lane],
            "evidence": self.manifest["evidence"][lane],
            "slots_digest": authority.digest(slots),
            "attempts_digest": authority.digest(own),
            "charged_attempts": len(own),
            "expected_slots": len(slots),
            "usable_slots": len(slots),
            "semantic_failures": 0,
            "coverage_failures": 0,
            "protection_failures": 0,
            "verdict": "passed",
        }
        if batch is not None:
            expected["batch"] = batch
        if (
            not isinstance(proof, dict)
            or set(proof) != set(expected) | {"output_digest", "review_digest"}
            or any(
                proof.get(key) != value or type(proof.get(key)) is not type(value)
                for key, value in expected.items()
            )
            or any(
                not isinstance(proof.get(key), str) or not _DIGEST.fullmatch(proof[key])
                for key in ("output_digest", "review_digest")
            )
            or any(latest.get(slot) != "usable" for slot in slots)
            or any(
                call["status"].endswith("-failed") or call["status"] == "charged" for call in own
            )
        ):
            raise authority.LedgerError("the measured and reviewed lane acceptance is incomplete")

    def accept(self, lane: str, proof: dict[str, Any]) -> None:
        """Seal independently measured predicates and a review artifact before another lane.

        This validates binding and accounting, not the truth of an operator's review.
        A producer must derive the receipt from the frozen native scoring artifact.
        """
        if lane not in LANES:
            raise authority.LedgerError("the accepted lane is unknown")
        with authority.locked(self.path):
            body = self._state()
            if body.get("stop"):
                raise authority.LedgerError("the stopped campaign cannot accept another study")
            self._stop(body["calls"])
            self._validate_acceptance(lane, proof, body["calls"])
            descriptor = os.open(
                self.receipts / (lane + "-ACCEPTED.json"),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(proof, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            body.setdefault("accepted", {})[lane] = authority.digest(proof)
            self._persist(body)

    def accept_batch(self, lane: str, batch: int, proof: dict[str, Any]) -> None:
        """Seal measured batch predicates and review before the next registered batch."""
        if (
            lane not in LANES
            or type(batch) is not int
            or not 0 <= batch < len(self.manifest["batches"][lane])
        ):
            raise authority.LedgerError("the accepted batch is unregistered")
        with authority.locked(self.path):
            body = self._state()
            if body.get("stop"):
                raise authority.LedgerError("the stopped campaign cannot accept a batch")
            self._stop(body["calls"])
            self._validate_acceptance(lane, proof, body["calls"], batch=batch)
            key = f"{lane}:{batch}"
            self.receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                self.receipts / (key.replace(":", "-") + "-BATCH.json"),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(proof, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            body.setdefault("accepted_batches", {})[key] = authority.digest(proof)
            self._persist(body)

    @staticmethod
    def _stop(calls: list[dict[str, Any]]) -> None:
        if any(c["status"].endswith("-failed") for c in calls):
            raise authority.LedgerError("a semantic or coverage failure stopped the whole campaign")
        if any(c["status"] == "charged" for c in calls):
            raise authority.LedgerError("an unclassified or orphan campaign call blocks launch")
        if len(calls) >= 2 and all(c["status"] == "unusable" for c in calls[-2:]):
            raise authority.LedgerError("two consecutive unusable calls stopped the whole campaign")

    def review_pending(self, lane: str, slot: str) -> bool:
        """Read-only pause at reviewed batch boundaries; never create a charge."""
        with authority.locked(self.path):
            body = self._state()
            self._stop(body["calls"])
            groups = self.manifest["batches"][lane]
            index = next(n for n, group in enumerate(groups) if slot in group)
            return any(f"{lane}:{n}" not in body.get("accepted_batches", {}) for n in range(index))

    def request_slot(self, lane: str, request: str) -> str:
        """Match only the next declared request; matching a later favorable slot cannot skip one."""
        with authority.locked(self.path):
            body = self._state()
            self._stop(body["calls"])
            slot = self._next_slot(lane, body["calls"])
            if (
                slot is None
                or slot in self.manifest.get("deferred_slots", {}).get(lane, [])
                or self.manifest["requests"][lane][slot] != request
            ):
                raise authority.LedgerError(
                    "the actual transport is not the next frozen campaign request"
                )
            return str(slot)

    def _next_slot(self, lane: str, calls: list[dict[str, Any]]) -> str | None:
        latest = {call["slot"]: call["status"] for call in calls if call["lane"] == lane}
        return next(
            (slot for slot in self.manifest["slots"][lane] if latest.get(slot) != "usable"), None
        )

    def reserve(self, lane: str, slot: str, binding: str, *, retry: bool = False) -> str:  # noqa: C901, PLR0912, PLR0915 - serial authority admission, one refusal per invariant
        """Charge before launching; successful, pending and unregistered slots cannot repeat."""
        with authority.locked(self.path):
            # Re-read authority inside the same charge lock, never trusting constructor time.
            current, key = self._current_manifest()
            if current["phase"] != "sealed":
                raise authority.LedgerError(
                    "the campaign genesis has not been reviewed and activated"
                )
            if key != self.binding or current != self.manifest:
                raise authority.LedgerError("the reviewed campaign changed before charge")
            if slot in self.manifest.get("deferred_slots", {}).get(lane, []):
                raise authority.LedgerError("the campaign slot is explicitly deferred and unbound")
            if (
                lane not in LANES
                or slot not in self.manifest["slots"][lane]
                or binding != self.manifest["requests"][lane][slot]
                or type(retry) is not bool
            ):
                raise authority.LedgerError("this is not a registered campaign request")
            body = self._state()
            calls = body["calls"]
            if body.get("stop"):
                raise authority.LedgerError("the whole campaign was explicitly stopped")
            self._stop(calls)
            if slot != self._next_slot(lane, calls):
                raise authority.LedgerError("a prior unresolved campaign slot cannot be skipped")
            own = [c for c in calls if c["lane"] == lane]
            if len(calls) >= 239 or len(own) >= LIMITS[lane]:
                raise authority.SpendCapError("the shared campaign allowance is full")
            order = self.manifest["order"]
            for previous in order[: order.index(lane)]:
                if previous not in body.get("accepted", {}):
                    raise authority.LedgerError(
                        "a predecessor study lacks measured and reviewed acceptance"
                    )
            if lane in body.get("accepted", {}):
                raise authority.LedgerError("the accepted lane cannot launch more attempts")
            groups = self.manifest["batches"][lane]
            index = next(n for n, group in enumerate(groups) if slot in group)
            group_calls = sum(call["slot"] in groups[index] for call in own)
            if group_calls >= (2 if index == 0 and retry else 1 if index == 0 else 25):
                raise authority.SpendCapError("the registered batch has charged 25 actual attempts")
            if any(f"{lane}:{n}" not in body.get("accepted_batches", {}) for n in range(index)):
                raise AwaitingReviewError(
                    "the preceding batch lacks measured and reviewed acceptance"
                )
            if f"{lane}:{index}" in body.get("accepted_batches", {}):
                raise authority.LedgerError("the accepted batch cannot launch more attempts")
            prior = [c for c in own if c["slot"] == slot]
            if retry:
                if (
                    not prior
                    or prior[-1]["status"] != "unusable"
                    or sum(c["retry"] for c in own) >= RETRIES[lane]
                ):
                    raise authority.LedgerError("the registered failed-call retry is unavailable")
            elif prior:
                raise authority.LedgerError("the registered slot is already charged")
            call: dict[str, Any] = {
                "id": uuid.uuid4().hex,
                "at": time.time(),
                "lane": lane,
                "slot": slot,
                "binding": binding,
                "retry": retry,
                "availability_attempt": group_calls + 1 if index == 0 else 0,
                "status": "charged",
            }
            self.receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
            receipt_path = self.receipts / (call["id"] + ".json")
            descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(_receipt(call), handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            calls.append(call)
            self._persist(body)
            return str(call["id"])

    def settle(self, charge_id: str, status: str) -> None:
        """Only a pending charge is classified; settled failures are never erased."""
        if status not in STATUSES or status == "charged":
            raise authority.LedgerError("the campaign classification is invalid")
        with authority.locked(self.path):
            body = self._state()
            found = next((c for c in body["calls"] if c["id"] == charge_id), None)
            if not found or found["status"] != "charged":
                raise authority.LedgerError("the campaign attempt is not pending")
            descriptor = os.open(
                self.receipts / (charge_id + "-SETTLED.json"),
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(
                    {"id": charge_id, "status": status, "manifest_digest": self.binding},
                    handle,
                    sort_keys=True,
                )
                handle.flush()
                os.fsync(handle.fileno())
            found["status"] = status
            self._persist(body)

    def stop(self, reason: str) -> None:
        """Latch an eligibility/coverage failure even when no model could be launched."""
        if reason not in ("semantic-failed", "coverage-failed", "protection-failed"):
            raise authority.LedgerError("the campaign stop reason is invalid")
        with authority.locked(self.path):
            body = self._state()
            if body.get("stop"):
                return
            self.receipts.mkdir(mode=0o700, parents=True, exist_ok=True)
            path = self.receipts / "STOP.json"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"stop": reason, "manifest_digest": self.binding}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            body["stop"] = reason
            self._persist(body)


class SuccessorCampaign(Campaign):
    """One reviewed fresh epoch; the stopped original remains independently inspectable."""

    epoch_id = 1

    def __init__(self) -> None:
        self.parent = Campaign()
        self.path = self.parent.path
        self.manifest, self.binding = self._current_manifest()
        self.epoch_dir = Path(self.path + ".epochs") / "1"
        self.receipts = self.epoch_dir / "reservations"
        self.handoff = _read(SUCCESSOR_HANDOFF_PATH, "successor handoff")
        if (
            not isinstance(self.handoff, dict)
            or set(self.handoff)
            != {"v", "verdict", "prepared_by", "reviewed_by", "parent", "successor"}
            or type(self.handoff["v"]) is not int
            or self.handoff["v"] != 1
            or self.handoff["verdict"] != "GO"
            or any(
                not isinstance(self.handoff[k], str) or not self.handoff[k].strip()
                for k in ("prepared_by", "reviewed_by")
            )
            or self.handoff["prepared_by"] == self.handoff["reviewed_by"]
        ):
            raise authority.LedgerError("the successor requires a bound independent handoff")
        self.handoff_digest = authority.digest(self.handoff)
        self._parent_state()

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        body, key = _manifest(SUCCESSOR_MANIFEST_PATH)
        if (
            body["order"] != ["qualification", "replay", "live"]
            or body.get("deferred_slots", {}).get("qualification") != []
            or any(
                body.get("deferred_slots", {}).get(lane) != body["slots"][lane]
                for lane in ("replay", "live")
            )
        ):
            raise authority.LedgerError(
                "the successor admits only qualification with later lanes held"
            )
        return body, key

    def _parent_state(self) -> dict[str, Any]:
        """Validate every ancestor field and the actual native prefix, before any epoch access."""
        if _manifest() != (
            self.parent.manifest,
            self.parent.binding,
        ) or self._current_manifest() != (self.manifest, self.binding):
            raise authority.LedgerError("the parent or successor manifest changed")
        if (
            authority.digest(_read(SUCCESSOR_HANDOFF_PATH, "successor handoff"))
            != self.handoff_digest
        ):
            raise authority.LedgerError("the successor handoff changed")
        parent = self.parent._state()  # noqa: SLF001 - validate the original receipts unchanged
        projection = {k: v for k, v in parent.items() if k != "epochs"}
        native = authority.read(QUALIFICATION_PATH)["calls"]
        active = authority.continuation()
        grant = authority.continuation(generation=5)
        generation = _successor_generation(active)
        resumed = generation > 5
        bounded_native = native[:32] if resumed else native
        if (
            not grant
            or grant["generation"] != 5
            or grant["phase"] != "sealed"
            or not grant.get("successor_allowance")
            or len(native) < 30
            or len(native) > _native_ceiling(generation)
            or any(c["status"] == "charged" for c in native[:30])
            or not authority.begins_with(QUALIFICATION_PATH, grant["previous"]["ledger_chain"])
            or not authority.follows(
                bounded_native,
                grant,
                (grant["next"]["marks_digest"], grant["next"]["inputs_digest"]),
            )
            or len(parent["calls"]) != 2
            or parent.get("stop") not in (None, "semantic-failed")
            or parent["calls"][-1]["status"] != "semantic-failed"
            or self.manifest["historical"] != self.parent.manifest["historical"]
            or any(
                native_call.get("campaign_charge") != shared_call["id"]
                or shared_call["slot"] != f"{native_call['case']}:r{native_call.get('repeat')}"
                or native_call.get("retry") is not shared_call["retry"]
                or native_call["status"] != "ok"
                for native_call, shared_call in zip(native[28:30], parent["calls"], strict=True)
            )
        ):
            raise authority.LedgerError("the stopped parent or native thirty-call prefix changed")
        prefix = native[:30]
        expected_parent = {
            "manifest_digest": self.parent.binding,
            "activation_anchor": self.parent.manifest["activation_anchor"],
            "state_digest": authority.digest(projection),
            "calls": 2,
            "calls_digest": authority.digest(parent["calls"]),
            "stop_proof": {
                "kind": "semantic-failed",
                "classification_digest": authority.digest(
                    _read(
                        str(self.parent.receipts / (parent["calls"][-1]["id"] + "-SETTLED.json")),
                        "parent failed classification",
                    )
                ),
                "explicit_stop_digest": authority.digest(
                    _read(str(self.parent.receipts / "STOP.json"), "parent stop")
                )
                if parent.get("stop")
                else None,
            },
            "failed_result_digest": authority.digest(
                _read(authority.result_path(4), "failed fourth result")
            ),
            "native_calls": 30,
            "native_calls_digest": authority.digest(prefix),
            "native_chain": {
                "first": prefix[0]["id"],
                "calls": 30,
                "head": authority.chain(prefix),
            },
        }
        expected_successor = {
            "manifest_digest": self.binding,
            "grant_digest": authority.digest(_read(authority.CONTINUATION_PATHS[4], "fifth grant")),
            "evidence": self.manifest["evidence"]["qualification"],
            "cases_digest": grant["next"]["cases_digest"],
            "inputs_digest": grant["next"]["inputs_digest"],
            "model_binding": grant["successor_allowance"]["model_binding"],
            "additional_calls": 31,
            "shared_total": 241,
            "native_total": 61,
        }
        if (
            self.handoff["parent"] != expected_parent
            or self.handoff["successor"] != expected_successor
            or grant["successor_allowance"]["campaign_binding"] != self.binding
        ):
            raise authority.LedgerError(
                "the successor's reviewed source, failure or allowance binding changed"
            )
        return parent

    def initialize(self) -> str:
        raise authority.LedgerError(
            "a successor needs explicit initialize_successor, never a fresh root"
        )

    def initialize_successor(self) -> str:
        """Append a zero-charge epoch once under the original canonical ledger lock."""
        with authority.locked(self.path):
            current, binding = self._current_manifest()
            parent = self._parent_state()
            if (
                current != self.manifest
                or binding != self.binding
                or self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or "epochs" in parent
                or os.path.lexists(str(self.epoch_dir.parent))
                or len(authority.read(QUALIFICATION_PATH)["calls"]) != 30
            ):
                raise authority.LedgerError("the successor epoch cannot be initialized again")
            state = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            epoch = {"id": 1, "handoff_digest": self.handoff_digest, "state": state}
            self.epoch_dir.mkdir(mode=0o700, parents=True)
            self._transition(epoch)
            parent["epochs"] = [epoch]
            authority._write(self.path, parent)  # noqa: SLF001 - append under the canonical root lock
            return authority.digest(state)

    def _transition(self, epoch: dict[str, Any]) -> None:
        descriptor = os.open(
            self.epoch_dir / "TRANSITION.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(epoch, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())

    def _epoch(self, parent: dict[str, Any]) -> dict[str, Any]:
        epochs = parent.get("epochs")
        # Generation g's epoch is g - 4: the fifth grant opened epoch one.
        newest = _successor_generation(authority.continuation()) - 4
        if (
            not isinstance(epochs, list)
            or len(epochs) not in range(1, newest + 1)
            or len(epochs) < self.epoch_id
            or not isinstance(epochs[self.epoch_id - 1], dict)
            or set(epochs[self.epoch_id - 1]) != {"id", "handoff_digest", "state"}
            or type(epochs[self.epoch_id - 1]["id"]) is not int
            or epochs[self.epoch_id - 1]["id"] != self.epoch_id
            or epochs[self.epoch_id - 1]["handoff_digest"] != self.handoff_digest
            or not isinstance(epochs[self.epoch_id - 1]["state"], dict)
            or self.epoch_dir.parent.is_symlink()
            or self.epoch_dir.is_symlink()
            or not self._bounded_entries(
                self.epoch_dir.parent, {str(n) for n in range(1, newest + 1)}
            )
            or not self._bounded_entries(self.epoch_dir, self._epoch_entries())
        ):
            raise authority.LedgerError("the successor epoch or its receipts changed")
        epoch = epochs[self.epoch_id - 1]
        state = epoch["state"]
        if set(state) - {
            "v",
            "manifest_digest",
            "calls",
            "genesis_nonce",
            "stop",
            "accepted",
            "accepted_batches",
        }:
            raise authority.LedgerError("the successor state has unregistered fields")
        genesis = {
            "v": 1,
            "manifest_digest": self.binding,
            "calls": [],
            "genesis_nonce": state.get("genesis_nonce"),
        }
        if self._read_transition() != {
            "id": self.epoch_id,
            "handoff_digest": self.handoff_digest,
            "state": genesis,
        }:
            raise authority.LedgerError("the successor transition changed")
        return cast("dict[str, Any]", epoch)

    def _epoch_entries(self) -> set[str]:
        return {"TRANSITION.json", "reservations"}

    def _read_transition(self) -> Any:
        return _read(str(self.epoch_dir / "TRANSITION.json"), "successor transition")

    @staticmethod
    def _bounded_entries(folder: Path, allowed: set[str]) -> bool:
        try:
            names = {p.name for p in itertools.islice(folder.iterdir(), len(allowed) + 1)}
        except OSError:
            return False
        return not names - allowed

    def _read_state(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._epoch(self._parent_state())["state"])

    def _state(self) -> dict[str, Any]:
        state = super()._state()
        calls = state["calls"]
        if len(calls) > 31 or any(c["lane"] != "qualification" for c in calls):
            raise authority.LedgerError(
                "the fresh qualification epoch exceeds its thirty-one allowance"
            )
        return state

    def _persist(self, body: dict[str, Any]) -> None:
        parent = self._parent_state()
        self._epoch(parent)["state"] = body
        authority._write(self.path, parent)  # noqa: SLF001 - persist only the admitted epoch under the root lock


def login_resume_parent_binding(previous: SuccessorCampaign) -> dict[str, Any]:
    """Derive the review's ancestor proof from validated state, never caller counts."""
    state = previous._state()  # noqa: SLF001 - preserve the settled predecessor's validated receipts
    root = previous.parent._state()  # noqa: SLF001 - independently validated original campaign
    native = authority.read(QUALIFICATION_PATH)["calls"][:32]
    return _login_resume_parent_binding(previous, state, root, native)


def _login_resume_parent_binding(
    previous: SuccessorCampaign,
    state: dict[str, Any],
    root: dict[str, Any],
    native: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble only from the callers freshly validated same-call snapshots."""
    return {
        "manifest_digest": previous.binding,
        "activation_anchor": previous.manifest["activation_anchor"],
        "handoff_digest": previous.handoff_digest,
        "state_digest": authority.digest(state),
        "original_digest": authority.digest({k: v for k, v in root.items() if k != "epochs"}),
        "calls": 2,
        "calls_digest": authority.digest(state["calls"]),
        "stop_proof": {
            "kind": "two-consecutive-unusable",
            "settlements_digest": authority.digest(
                [
                    _read(
                        str(previous.receipts / (c["id"] + "-SETTLED.json")),
                        "prior unusable classification",
                    )
                    for c in state["calls"]
                ]
            ),
        },
        "failed_result_digest": authority.digest(
            _read(authority.result_path(5), "blocked fifth result")
        ),
        "native_calls": 32,
        "native_calls_digest": authority.digest(native),
        "native_chain": {"first": native[0]["id"], "calls": 32, "head": authority.chain(native)},
    }


class LoginResumeCampaign(SuccessorCampaign):
    """The one reviewed login recovery carries 29 held calls forward and adds two."""

    epoch_id = 2

    def __init__(self) -> None:
        self.parent = SuccessorCampaign()
        self.path = self.parent.path
        self.manifest, self.binding = self._current_manifest()
        self.epoch_dir = Path(self.path + ".epochs") / "2"
        self.receipts = self.epoch_dir / "reservations"
        self.handoff = _read(LOGIN_RESUME_HANDOFF_PATH, "login recovery handoff")
        if (
            not isinstance(self.handoff, dict)
            or set(self.handoff)
            != {"v", "verdict", "prepared_by", "reviewed_by", "parent", "successor"}
            or type(self.handoff["v"]) is not int
            or self.handoff["v"] != 1
            or self.handoff["verdict"] != "GO"
            or any(
                not isinstance(self.handoff[k], str) or not self.handoff[k].strip()
                for k in ("prepared_by", "reviewed_by")
            )
            or self.handoff["prepared_by"] == self.handoff["reviewed_by"]
        ):
            raise authority.LedgerError("login recovery needs an independent bound handoff")
        self.handoff_digest = authority.digest(self.handoff)
        self._parent_state()

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        body, key = _manifest(LOGIN_RESUME_MANIFEST_PATH)
        if body["order"] != ["qualification", "replay", "live"]:
            raise authority.LedgerError(
                "login recovery admits only qualification; later lanes stay held"
            )
        return body, key

    def _parent_state(self) -> dict[str, Any]:
        if (
            self._current_manifest() != (self.manifest, self.binding)
            or authority.digest(_read(LOGIN_RESUME_HANDOFF_PATH, "login recovery handoff"))
            != self.handoff_digest
        ):
            raise authority.LedgerError("the login recovery manifest or handoff changed")
        previous_campaign = cast("SuccessorCampaign", self.parent)
        previous = previous_campaign._state()  # noqa: SLF001 - validate every receipt of the stopped epoch
        root = previous_campaign.parent._state()  # noqa: SLF001 - append only to the original canonical ledger
        native = authority.read(QUALIFICATION_PATH)["calls"]
        generation = _successor_generation(authority.continuation())
        extended = generation > 6
        grant = authority.continuation(generation=6)
        calls = previous["calls"]
        if (
            not grant
            or grant["generation"] != 6
            or grant["phase"] != "sealed"
            or not grant.get("login_resume_allowance")
            or len(calls) != 2
            or any(c["status"] != "unusable" for c in calls)
            or calls[0]["slot"] != calls[1]["slot"]
            or calls[0]["retry"]
            or not calls[1]["retry"]
            or previous.get("stop") is not None
            or previous.get("accepted")
            or previous.get("accepted_batches")
            or not 32 <= len(native) <= _native_ceiling(generation)
            or any(c["status"] == "charged" for c in native[:32])
            or not authority.begins_with(QUALIFICATION_PATH, grant["previous"]["ledger_chain"])
            or not authority.follows(
                native[:34] if extended else native,
                grant,
                (grant["next"]["marks_digest"], grant["next"]["inputs_digest"]),
            )
            or self.manifest["historical"] != self.parent.manifest["historical"]
            or any(
                n.get("campaign_charge") != c["id"]
                or c["slot"] != f"{n['case']}:r{n.get('repeat')}"
                or n.get("retry") is not c["retry"]
                or n["status"] not in ("failed", "unavailable")
                for n, c in zip(native[30:32], calls, strict=True)
            )
        ):
            raise authority.LedgerError(
                "login recovery lost the stopped second epoch or native 32-call prefix"
            )
        expected = {
            "manifest_digest": self.binding,
            "grant_digest": authority.digest(_read(authority.CONTINUATION_PATHS[5], "sixth grant")),
            "evidence": self.manifest["evidence"]["qualification"],
            "cases_digest": grant["next"]["cases_digest"],
            "inputs_digest": grant["next"]["inputs_digest"],
            "model_binding": grant["login_resume_allowance"]["model_binding"],
            "additional_calls": 31,
            "carried_calls": 29,
            "renewed_calls": 2,
            "shared_total": 243,
            "native_total": 63,
        }
        if (
            self.handoff["parent"]
            != _login_resume_parent_binding(previous_campaign, previous, root, native[:32])
            or self.handoff["successor"] != expected
            or grant["login_resume_allowance"]["campaign_binding"] != self.binding
        ):
            raise authority.LedgerError("the reviewed login recovery ancestry or allowance changed")
        return root

    def initialize_successor(self) -> str:
        """Append exactly epoch two once, preserving epoch one and its failed calls."""
        with authority.locked(self.path):
            root = self._parent_state()
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or len(root.get("epochs", [])) != 1
                or os.path.lexists(str(self.epoch_dir))
                or len(authority.read(QUALIFICATION_PATH)["calls"]) != 32
            ):
                raise authority.LedgerError("login recovery cannot be initialized again")
            state = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            epoch = {"id": 2, "handoff_digest": self.handoff_digest, "state": state}
            self.epoch_dir.mkdir(mode=0o700)
            self._transition(epoch)
            root["epochs"].append(epoch)
            authority._write(self.path, root)  # noqa: SLF001 - append under the existing canonical lock
            return authority.digest(state)


def clause_continuation_parent_binding(previous: LoginResumeCampaign) -> dict[str, Any]:
    """Bind the real stopped semantic predecessor, including its retained accepted opening."""
    state = previous._state()  # noqa: SLF001 - every receipt and review is validated first
    root = cast("SuccessorCampaign", previous.parent).parent._state()  # noqa: SLF001 - independently validated original account
    native = authority.read(QUALIFICATION_PATH)["calls"][:34]
    return _clause_continuation_parent_binding(previous, state, root, native)


def _clause_continuation_parent_binding(
    previous: LoginResumeCampaign,
    state: dict[str, Any],
    root: dict[str, Any],
    native: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble only from the callers freshly validated same-call snapshots."""
    return {
        "manifest_digest": previous.binding,
        "activation_anchor": previous.manifest["activation_anchor"],
        "handoff_digest": previous.handoff_digest,
        "state_digest": authority.digest(state),
        "original_digest": authority.digest({k: v for k, v in root.items() if k != "epochs"}),
        "first_epoch_digest": authority.digest(root["epochs"][0]["state"]),
        "calls": 2,
        "calls_digest": authority.digest(state["calls"]),
        "stop_proof": {
            "kind": "semantic-failed",
            "classification_digest": authority.digest(
                _read(
                    str(previous.receipts / (state["calls"][-1]["id"] + "-SETTLED.json")),
                    "prior semantic classification",
                )
            ),
            "explicit_stop_digest": authority.digest(
                _read(str(previous.receipts / "STOP.json"), "prior stop")
            )
            if state.get("stop")
            else None,
        },
        "failed_result_digest": authority.digest(
            _read(authority.result_path(6), "failed sixth result")
        ),
        "native_calls": 34,
        "native_calls_digest": authority.digest(native),
        "native_chain": {"first": native[0]["id"], "calls": 34, "head": authority.chain(native)},
    }


class ClauseContinuationCampaign(LoginResumeCampaign):
    """The one reviewed clause correction preserves six spent calls and adds two."""

    epoch_id = 3

    def _epoch_entries(self) -> set[str]:
        if os.path.lexists(str(CLAUSE_ZERO_RESEAL_PATH)) or os.path.lexists(
            str(self.epoch_dir / "RESEAL.json")
        ):
            return super()._epoch_entries() | {"RESEAL.json"}
        return super()._epoch_entries()

    @staticmethod
    def _zero_epoch(value: Any) -> bool:
        if (
            not isinstance(value, dict)
            or set(value) != {"id", "handoff_digest", "state"}
            or type(value["id"]) is not int
            or value["id"] != 3
            or not isinstance(value["handoff_digest"], str)
            or not _DIGEST.fullmatch(value["handoff_digest"])
        ):
            return False
        state = value["state"]
        return (
            isinstance(state, dict)
            and set(state) == {"v", "manifest_digest", "calls", "genesis_nonce"}
            and type(state["v"]) is int
            and state["v"] == 1
            and state["calls"] == []
            and isinstance(state["manifest_digest"], str)
            and bool(_DIGEST.fullmatch(state["manifest_digest"]))
            and isinstance(state["genesis_nonce"], str)
            and bool(re.fullmatch(r"[0-9a-f]{32}", state["genesis_nonce"]))
        )

    def _zero_reseal_review(self) -> dict[str, Any]:
        record = _read(CLAUSE_ZERO_RESEAL_PATH, "reviewed zero-charge reseal")
        if (
            not isinstance(record, dict)
            or set(record)
            != {"v", "verdict", "prepared_by", "reviewed_by", "parent", "before", "after"}
            or type(record["v"]) is not int
            or record["v"] != 1
            or record["verdict"] != "GO"
            or any(
                not isinstance(record[k], str) or not record[k].strip()
                for k in ("prepared_by", "reviewed_by")
            )
            or record["prepared_by"].strip() == record["reviewed_by"].strip()
            or record["parent"] != self.handoff["parent"]
        ):
            raise authority.LedgerError("zero-charge reseal needs independent bound review")
        for label in ("before", "after"):
            part = record[label]
            fields = {
                "manifest_digest",
                "grant_digest",
                "handoff_digest",
                "activation_anchor",
                "epoch",
            }
            if label == "before":
                fields.add("transition_sha256")
            if (
                not isinstance(part, dict)
                or set(part) != fields
                or any(
                    not isinstance(part[k], str) or not _DIGEST.fullmatch(part[k])
                    for k in fields - {"epoch"}
                )
                or not self._zero_epoch(part["epoch"])
                or part["epoch"]["handoff_digest"] != part["handoff_digest"]
                or part["epoch"]["state"]["manifest_digest"] != part["manifest_digest"]
                or authority.digest(part["epoch"]["state"]) != part["activation_anchor"]
            ):
                raise authority.LedgerError("the reviewed zero-charge genesis is invalid")
        before, after = record["before"], record["after"]
        if (
            before["manifest_digest"] == after["manifest_digest"]
            or after["manifest_digest"] != self.binding
            or after["handoff_digest"] != self.handoff_digest
            or after["grant_digest"]
            != authority.digest(_read(authority.CONTINUATION_PATHS[6], "seventh grant"))
            or super()._read_transition() != before["epoch"]
        ):
            raise authority.LedgerError("zero-charge reseal lost original or corrected authority")
        try:
            with Path(str(self.epoch_dir / "TRANSITION.json")).open("rb") as handle:
                original = handle.read(2 * 1024 * 1024 + 1)
        except OSError as error:
            raise authority.LedgerError(
                "the original zero-charge transition cannot be read"
            ) from error
        if (
            len(original) > 2 * 1024 * 1024
            or hashlib.sha256(original).hexdigest() != before["transition_sha256"]
        ):
            raise authority.LedgerError("the original zero-charge transition bytes changed")
        return record

    def _read_transition(self) -> Any:
        if not os.path.lexists(str(CLAUSE_ZERO_RESEAL_PATH)) and not os.path.lexists(
            str(self.epoch_dir / "RESEAL.json")
        ):
            return super()._read_transition()
        record = self._zero_reseal_review()
        receipt = _read(str(self.epoch_dir / "RESEAL.json"), "zero-charge reseal receipt")
        expected = {
            "v": 1,
            "review_digest": authority.digest(record),
            "before": record["before"],
            "after": record["after"],
        }
        if (
            not isinstance(receipt, dict)
            or type(receipt.get("v")) is not int
            or receipt != expected
        ):
            raise authority.LedgerError("the immutable zero-charge reseal receipt changed")
        return record["after"]["epoch"]

    def reseal_zero_charge(self) -> str:
        """Reseal only reviewed epoch three before any attempt; preserve its first transition."""
        with authority.locked(self.path):
            root = self._parent_state()
            record = self._zero_reseal_review()
            epochs = root.get("epochs")
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or not isinstance(epochs, list)
                or len(epochs) != 3
                or epochs[2] != record["before"]["epoch"]
                or len(authority.read(QUALIFICATION_PATH)["calls"]) != 34
                or os.path.lexists(str(self.epoch_dir / "RESEAL.json"))
                or self.epoch_dir.parent.is_symlink()
                or self.epoch_dir.is_symlink()
                or not self._bounded_entries(self.epoch_dir, {"TRANSITION.json", "reservations"})
                or (
                    os.path.lexists(str(self.receipts))
                    and (
                        self.receipts.is_symlink()
                        or not Path(str(self.receipts)).is_dir()
                        or not self._bounded_entries(self.receipts, set())
                    )
                )
            ):
                raise authority.LedgerError(
                    "only the original strictly zero-charge epoch may be resealed once"
                )
            descriptor = os.open(
                self.epoch_dir / "RESEAL.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            receipt = {
                "v": 1,
                "review_digest": authority.digest(record),
                "before": record["before"],
                "after": record["after"],
            }
            with os.fdopen(descriptor, "w") as handle:
                json.dump(receipt, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            epochs[2] = record["after"]["epoch"]
            authority._write(self.path, root)  # noqa: SLF001 - original account lock, zero epoch only, receipt persists first
            return str(record["after"]["activation_anchor"])

    def __init__(self) -> None:
        self.parent = LoginResumeCampaign()
        self.path = self.parent.path
        self.manifest, self.binding = self._current_manifest()
        self.epoch_dir = Path(self.path + ".epochs") / "3"
        self.receipts = self.epoch_dir / "reservations"
        self.handoff = _read(CLAUSE_CONTINUATION_HANDOFF_PATH, "clause continuation handoff")
        if (
            not isinstance(self.handoff, dict)
            or set(self.handoff)
            != {"v", "verdict", "prepared_by", "reviewed_by", "parent", "successor"}
            or type(self.handoff["v"]) is not int
            or self.handoff["v"] != 1
            or self.handoff["verdict"] != "GO"
            or any(
                not isinstance(self.handoff[k], str) or not self.handoff[k].strip()
                for k in ("prepared_by", "reviewed_by")
            )
            or self.handoff["prepared_by"] == self.handoff["reviewed_by"]
        ):
            raise authority.LedgerError("clause continuation needs an independent bound handoff")
        self.handoff_digest = authority.digest(self.handoff)
        self._parent_state()

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        body, key = _manifest(CLAUSE_CONTINUATION_MANIFEST_PATH)
        if body["order"] != ["qualification", "replay", "live"]:
            raise authority.LedgerError(
                "clause continuation admits only qualification; later lanes stay held"
            )
        return body, key

    def _parent_state(self) -> dict[str, Any]:
        if (
            self._current_manifest() != (self.manifest, self.binding)
            or authority.digest(
                _read(CLAUSE_CONTINUATION_HANDOFF_PATH, "clause continuation handoff")
            )
            != self.handoff_digest
        ):
            raise authority.LedgerError("the clause continuation manifest or handoff changed")
        previous_campaign = cast("LoginResumeCampaign", self.parent)
        previous = previous_campaign._state()  # noqa: SLF001 - validate every receipt of the stopped epoch
        root = cast("SuccessorCampaign", previous_campaign.parent).parent._state()  # noqa: SLF001 - append only to the original canonical ledger
        native = authority.read(QUALIFICATION_PATH)["calls"]
        generation = _successor_generation(authority.continuation())
        extended = generation > 7
        grant = authority.continuation(generation=7)
        calls = previous["calls"]
        if (
            not grant
            or grant["generation"] != 7
            or grant["phase"] != "sealed"
            or not grant.get("clause_continuation_allowance")
            or len(calls) != 2
            or [c["status"] for c in calls] != ["usable", "semantic-failed"]
            or [c["slot"] for c in calls] != self.parent.manifest["slots"]["qualification"][:2]
            or any(c["retry"] for c in calls)
            or previous.get("stop") not in (None, "semantic-failed")
            or previous.get("accepted")
            or set(previous.get("accepted_batches", {})) != {"qualification:0"}
            or not 34 <= len(native) <= _native_ceiling(generation)
            or any(c["status"] == "charged" for c in native[:34])
            or not authority.begins_with(QUALIFICATION_PATH, grant["previous"]["ledger_chain"])
            or not authority.follows(
                native[:36] if extended else native,
                grant,
                (grant["next"]["marks_digest"], grant["next"]["inputs_digest"]),
            )
            or self.manifest["historical"] != self.parent.manifest["historical"]
            or any(
                n.get("campaign_charge") != c["id"]
                or c["slot"] != f"{n['case']}:r{n.get('repeat')}"
                or n.get("retry") is not c["retry"]
                or n["status"] != "ok"
                for n, c in zip(native[32:34], calls, strict=True)
            )
        ):
            raise authority.LedgerError(
                "clause continuation lost the stopped login epoch or native 34-call prefix"
            )
        expected = {
            "manifest_digest": self.binding,
            "grant_digest": authority.digest(
                _read(authority.CONTINUATION_PATHS[6], "seventh grant")
            ),
            "evidence": self.manifest["evidence"]["qualification"],
            "cases_digest": grant["next"]["cases_digest"],
            "inputs_digest": grant["next"]["inputs_digest"],
            "model_binding": grant["clause_continuation_allowance"]["model_binding"],
            "additional_calls": 31,
            "carried_calls": 29,
            "renewed_calls": 2,
            "shared_total": 245,
            "native_total": 65,
        }
        if (
            self.handoff["parent"]
            != _clause_continuation_parent_binding(previous_campaign, previous, root, native[:34])
            or self.handoff["successor"] != expected
            or grant["clause_continuation_allowance"]["campaign_binding"] != self.binding
        ):
            raise authority.LedgerError(
                "the reviewed clause continuation ancestry or allowance changed"
            )
        return root

    def initialize_successor(self) -> str:
        """Append exactly epoch three once, preserving all earlier stops and charges."""
        with authority.locked(self.path):
            root = self._parent_state()
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or len(root.get("epochs", [])) != 2
                or os.path.lexists(str(self.epoch_dir))
                or len(authority.read(QUALIFICATION_PATH)["calls"]) != 34
            ):
                raise authority.LedgerError("clause continuation cannot be initialized again")
            state = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            epoch = {"id": 3, "handoff_digest": self.handoff_digest, "state": state}
            self.epoch_dir.mkdir(mode=0o700)
            self._transition(epoch)
            root["epochs"].append(epoch)
            authority._write(self.path, root)  # noqa: SLF001 - append under the existing canonical lock
            return authority.digest(state)


def clause_isolation_parent_binding(previous: ClauseContinuationCampaign) -> dict[str, Any]:
    """Bind the four stopped epochs, exact native36 and immutable original reseal."""
    state = previous._state()  # noqa: SLF001 - independently validated settled predecessor
    root = previous._parent_state()  # noqa: SLF001 - original canonical account and every ancestor
    native = authority.read(QUALIFICATION_PATH)["calls"][:36]
    return _clause_isolation_parent_binding(previous, state, root, native)


def _clause_isolation_parent_binding(
    previous: ClauseContinuationCampaign,
    state: dict[str, Any],
    root: dict[str, Any],
    native: list[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble only from the callers freshly validated same-call snapshots."""
    return {
        "manifest_digest": previous.binding,
        "activation_anchor": previous.manifest["activation_anchor"],
        "handoff_digest": previous.handoff_digest,
        "state_digest": authority.digest(state),
        "original_digest": authority.digest({k: v for k, v in root.items() if k != "epochs"}),
        "first_epoch_digest": authority.digest(root["epochs"][0]["state"]),
        "second_epoch_digest": authority.digest(root["epochs"][1]["state"]),
        "transition_digest": authority.digest(
            _read(str(previous.epoch_dir / "TRANSITION.json"), "original clause transition")
        ),
        "zero_reseal_digest": authority.digest(
            _read(str(previous.epoch_dir / "RESEAL.json"), "immutable clause reseal")
        ),
        "calls": 2,
        "calls_digest": authority.digest(state["calls"]),
        "stop_proof": {
            "kind": "semantic-failed",
            "classification_digest": authority.digest(
                _read(
                    str(previous.receipts / (state["calls"][-1]["id"] + "-SETTLED.json")),
                    "prior semantic classification",
                )
            ),
            "explicit_stop_digest": authority.digest(
                _read(str(previous.receipts / "STOP.json"), "prior stop")
            )
            if state.get("stop")
            else None,
        },
        "failed_result_digest": authority.digest(
            _read(authority.result_path(7), "failed seventh result")
        ),
        "native_calls": 36,
        "native_calls_digest": authority.digest(native),
        "native_chain": {"first": native[0]["id"], "calls": 36, "head": authority.chain(native)},
    }


class ClauseIsolationCampaign(SuccessorCampaign):
    """Fixed fourth epoch: preserve eight spent attempts and carry29+renew2."""

    epoch_id = 4

    def __init__(self) -> None:
        self.parent = ClauseContinuationCampaign()
        self.path = self.parent.path
        self.manifest, self.binding = self._current_manifest()
        self.epoch_dir = Path(self.path + ".epochs") / "4"
        self.receipts = self.epoch_dir / "reservations"
        self.handoff = _read(CLAUSE_ISOLATION_HANDOFF_PATH, "clause isolation handoff")
        if (
            not isinstance(self.handoff, dict)
            or set(self.handoff)
            != {"v", "verdict", "prepared_by", "reviewed_by", "parent", "successor"}
            or type(self.handoff["v"]) is not int
            or self.handoff["v"] != 1
            or self.handoff["verdict"] != "GO"
            or any(
                not isinstance(self.handoff[k], str) or not self.handoff[k].strip()
                for k in ("prepared_by", "reviewed_by")
            )
            or self.handoff["prepared_by"] == self.handoff["reviewed_by"]
        ):
            raise authority.LedgerError("clause isolation needs an independent bound handoff")
        self.handoff_digest = authority.digest(self.handoff)
        self._parent_state()

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        body, key = _manifest(CLAUSE_ISOLATION_MANIFEST_PATH)
        if body["order"] != ["qualification", "replay", "live"]:
            raise authority.LedgerError(
                "clause isolation admits only qualification; later lanes stay held"
            )
        return body, key

    def _parent_state(self) -> dict[str, Any]:
        if (
            self._current_manifest() != (self.manifest, self.binding)
            or authority.digest(_read(CLAUSE_ISOLATION_HANDOFF_PATH, "clause isolation handoff"))
            != self.handoff_digest
        ):
            raise authority.LedgerError("the clause isolation manifest or handoff changed")
        previous_campaign = cast("ClauseContinuationCampaign", self.parent)
        previous = previous_campaign._state()  # noqa: SLF001 - validate every receipt of the stopped epoch
        root = previous_campaign._parent_state()  # noqa: SLF001 - append only to the original canonical ledger
        native = authority.read(QUALIFICATION_PATH)["calls"]
        generation = _successor_generation(authority.continuation())
        extended = generation > 8
        grant = authority.continuation(generation=8)
        calls = previous["calls"]
        if (
            not grant
            or grant["generation"] != 8
            or grant["phase"] != "sealed"
            or not grant.get("clause_isolation_allowance")
            or len(calls) != 2
            or [c["status"] for c in calls] != ["usable", "semantic-failed"]
            or [c["slot"] for c in calls] != self.parent.manifest["slots"]["qualification"][:2]
            or any(c["retry"] for c in calls)
            or previous.get("stop") not in (None, "semantic-failed")
            or previous.get("accepted")
            or set(previous.get("accepted_batches", {})) != {"qualification:0"}
            or not 36 <= len(native) <= _native_ceiling(generation)
            or any(c["status"] == "charged" for c in native[:36])
            or not authority.begins_with(QUALIFICATION_PATH, grant["previous"]["ledger_chain"])
            or not authority.follows(
                native[:38] if extended else native,
                grant,
                (grant["next"]["marks_digest"], grant["next"]["inputs_digest"]),
            )
            or self.manifest["historical"] != self.parent.manifest["historical"]
            or any(
                n.get("campaign_charge") != c["id"]
                or c["slot"] != f"{n['case']}:r{n.get('repeat')}"
                or n.get("retry") is not c["retry"]
                or n["status"] != "ok"
                for n, c in zip(native[34:36], calls, strict=True)
            )
        ):
            raise authority.LedgerError(
                "clause isolation lost the stopped clause epoch or native 36-call prefix"
            )
        expected = {
            "manifest_digest": self.binding,
            "grant_digest": authority.digest(
                _read(authority.CONTINUATION_PATHS[7], "eighth grant")
            ),
            "evidence": self.manifest["evidence"]["qualification"],
            "cases_digest": grant["next"]["cases_digest"],
            "inputs_digest": grant["next"]["inputs_digest"],
            "model_binding": grant["clause_isolation_allowance"]["model_binding"],
            "additional_calls": 31,
            "carried_calls": 29,
            "renewed_calls": 2,
            "shared_total": 247,
            "native_total": 67,
        }
        if (
            self.handoff["parent"]
            != _clause_isolation_parent_binding(previous_campaign, previous, root, native[:36])
            or self.handoff["successor"] != expected
            or grant["clause_isolation_allowance"]["campaign_binding"] != self.binding
        ):
            raise authority.LedgerError(
                "the reviewed clause isolation ancestry or allowance changed"
            )
        return root

    def initialize_successor(self) -> str:
        """Append exactly epoch four once, preserving all earlier stops and charges."""
        with authority.locked(self.path):
            root = self._parent_state()
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or len(root.get("epochs", [])) != 3
                or os.path.lexists(str(self.epoch_dir))
                or len(authority.read(QUALIFICATION_PATH)["calls"]) != 36
            ):
                raise authority.LedgerError("clause isolation cannot be initialized again")
            state = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            epoch = {"id": 4, "handoff_digest": self.handoff_digest, "state": state}
            self.epoch_dir.mkdir(mode=0o700)
            self._transition(epoch)
            root["epochs"].append(epoch)
            authority._write(self.path, root)  # noqa: SLF001 - append under the existing canonical lock
            return authority.digest(state)


def conditional_priority_parent_binding(previous: ClauseIsolationCampaign) -> dict[str, Any]:
    """Bind actual G8 paid STOP, all earlier epochs, native38 and original reseal."""
    state = previous._state()  # noqa: SLF001 - independently validated stopped predecessor
    root = previous._parent_state()  # noqa: SLF001 - every ancestor and receipt is preserved
    native = authority.read(QUALIFICATION_PATH)["calls"][:38]
    return _conditional_parent_binding(previous, state, root, native)


def _conditional_parent_binding(
    previous: ClauseIsolationCampaign,
    state: dict[str, Any],
    root: dict[str, Any],
    native: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure assembly from this admission's freshly validated snapshots; never cached."""
    old_reseal = previous.epoch_dir.parent / "3"
    return {
        "manifest_digest": previous.binding,
        "activation_anchor": previous.manifest["activation_anchor"],
        "handoff_digest": previous.handoff_digest,
        "state_digest": authority.digest(state),
        "original_digest": authority.digest({k: v for k, v in root.items() if k != "epochs"}),
        "ancestor_epochs_digest": authority.digest(root["epochs"][:3]),
        "transition_digest": authority.digest(
            _read(str(old_reseal / "TRANSITION.json"), "original clause transition")
        ),
        "zero_reseal_digest": authority.digest(
            _read(str(old_reseal / "RESEAL.json"), "immutable clause reseal")
        ),
        "calls": 2,
        "calls_digest": authority.digest(state["calls"]),
        "stop_proof": {
            "kind": "semantic-failed",
            "classification_digest": authority.digest(
                _read(
                    str(previous.receipts / (state["calls"][-1]["id"] + "-SETTLED.json")),
                    "prior semantic classification",
                )
            ),
            "explicit_stop_digest": authority.digest(
                _read(str(previous.receipts / "STOP.json"), "prior stop")
            )
            if state.get("stop")
            else None,
        },
        "failed_result_digest": authority.digest(
            _read(authority.result_path(8), "failed eighth result")
        ),
        "native_calls": 38,
        "native_calls_digest": authority.digest(native),
        "native_chain": {"first": native[0]["id"], "calls": 38, "head": authority.chain(native)},
    }


class ConditionalPriorityCampaign(SuccessorCampaign):
    """Fixed fifth epoch: preserve ten spent attempts and carry29+renew2."""

    epoch_id = 5

    stop_on_semantic_failure = False

    @staticmethod
    def _stop(calls: list[dict[str, Any]]) -> None:
        # Preserve technical/protection/orphan stops and two unusable attempts.
        if any(c["status"] in ("coverage-failed", "protection-failed") for c in calls):
            raise authority.LedgerError("a coverage or protection failure stopped the campaign")
        if any(c["status"] == "charged" for c in calls):
            raise authority.LedgerError("an unclassified or orphan campaign call blocks launch")
        if len(calls) >= 2 and all(c["status"] == "unusable" for c in calls[-2:]):
            raise authority.LedgerError("two consecutive unusable calls stopped the campaign")

    def _next_slot(self, lane: str, calls: list[dict[str, Any]]) -> str | None:
        latest = {c["slot"]: c["status"] for c in calls if c["lane"] == lane}
        return next(
            (
                slot
                for slot in self.manifest["slots"][lane]
                if latest.get(slot) not in ("usable", "semantic-failed")
            ),
            None,
        )

    def _validate_acceptance(
        self, lane: str, proof: Any, calls: list[dict[str, Any]], *, batch: int | None = None
    ) -> None:
        if batch is None:
            super()._validate_acceptance(lane, proof, calls, batch=None)
            return
        slots = self.manifest["batches"][lane][batch]
        own = [c for c in calls if c["lane"] == lane and c["slot"] in slots]
        latest = {c["slot"]: c["status"] for c in own}
        expected = {
            "v": 1,
            "lane": lane,
            "batch": batch,
            "manifest_digest": self.binding,
            "protocol": self.manifest["protocols"][lane],
            "binding": self.manifest["bindings"][lane],
            "evidence": self.manifest["evidence"][lane],
            "slots_digest": authority.digest(slots),
            "attempts_digest": authority.digest(own),
            "charged_attempts": len(own),
            "expected_slots": len(slots),
            "measured_slots": len(slots),
            "usable_slots": sum(latest.get(slot) == "usable" for slot in slots),
            "semantic_failures": sum(c["status"] == "semantic-failed" for c in own),
            "coverage_failures": 0,
            "protection_failures": 0,
            "verdict": "measured",
        }
        if (
            lane != "qualification"
            or not isinstance(proof, dict)
            or set(proof) != set(expected) | {"output_digest", "review_digest"}
            or any(
                proof.get(key) != value or type(proof.get(key)) is not type(value)
                for key, value in expected.items()
            )
            or any(
                not isinstance(proof.get(key), str) or not _DIGEST.fullmatch(proof[key])
                for key in ("output_digest", "review_digest")
            )
            or any(latest.get(slot) not in ("usable", "semantic-failed") for slot in slots)
            or any(c["status"] in ("charged", "coverage-failed", "protection-failed") for c in own)
        ):
            raise authority.LedgerError("the measured and reviewed batch is incomplete")

    def review_batch(self, lane: str, batch: int, proof: dict[str, Any]) -> None:
        """Accept a bound measurement review, never qualification of failed answers."""
        super().accept_batch(lane, batch, proof)

    def __init__(self) -> None:
        self.parent = ClauseIsolationCampaign()
        self.path = self.parent.path
        self.manifest, self.binding = self._current_manifest()
        self.epoch_dir = Path(self.path + ".epochs") / "5"
        self.receipts = self.epoch_dir / "reservations"
        self.handoff = _read(CONDITIONAL_PRIORITY_HANDOFF_PATH, "conditional priority handoff")
        if (
            not isinstance(self.handoff, dict)
            or set(self.handoff)
            != {"v", "verdict", "prepared_by", "reviewed_by", "parent", "successor"}
            or type(self.handoff["v"]) is not int
            or self.handoff["v"] != 1
            or self.handoff["verdict"] != "GO"
            or any(
                not isinstance(self.handoff[k], str) or not self.handoff[k].strip()
                for k in ("prepared_by", "reviewed_by")
            )
            or self.handoff["prepared_by"] == self.handoff["reviewed_by"]
        ):
            raise authority.LedgerError("conditional priority needs an independent bound handoff")
        self.handoff_digest = authority.digest(self.handoff)
        self._parent_state()

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        body, key = _manifest(CONDITIONAL_PRIORITY_MANIFEST_PATH)
        if body["order"] != ["qualification", "replay", "live"]:
            raise authority.LedgerError(
                "conditional priority admits only qualification; later lanes stay held"
            )
        return body, key

    def _parent_state(self) -> dict[str, Any]:
        if (
            self._current_manifest() != (self.manifest, self.binding)
            or authority.digest(
                _read(CONDITIONAL_PRIORITY_HANDOFF_PATH, "conditional priority handoff")
            )
            != self.handoff_digest
        ):
            raise authority.LedgerError("the conditional priority manifest or handoff changed")
        previous_campaign = cast("ClauseIsolationCampaign", self.parent)
        previous = previous_campaign._state()  # noqa: SLF001 - validate every receipt of the stopped epoch
        root = previous_campaign._parent_state()  # noqa: SLF001 - append only to the original canonical ledger
        native = authority.read(QUALIFICATION_PATH)["calls"]
        # Selected by number, never as the active grant: once the tenth is active the ninth is
        # an ancestor, and its own thirty charges end at 68.
        generation = _successor_generation(authority.continuation())
        extended = generation > 9
        grant = authority.continuation(generation=9)
        calls = previous["calls"]
        if (
            not grant
            or generation < 9
            or grant["generation"] != 9
            or grant["phase"] != "sealed"
            or not grant.get("conditional_priority_allowance")
            or len(calls) != 2
            or [c["status"] for c in calls] != ["usable", "semantic-failed"]
            or [c["slot"] for c in calls] != self.parent.manifest["slots"]["qualification"][:2]
            or any(c["retry"] for c in calls)
            or previous.get("stop") not in (None, "semantic-failed")
            or previous.get("accepted")
            or set(previous.get("accepted_batches", {})) != {"qualification:0"}
            or not 38 <= len(native) <= _native_ceiling(generation)
            or any(c["status"] == "charged" for c in native[:38])
            or not authority.begins_with(QUALIFICATION_PATH, grant["previous"]["ledger_chain"])
            or not authority.follows(
                native[: authority.TENTH_PREVIOUS_CALLS] if extended else native,
                grant,
                (grant["next"]["marks_digest"], grant["next"]["inputs_digest"]),
            )
            or self.manifest["historical"] != self.parent.manifest["historical"]
            or any(
                n.get("campaign_charge") != c["id"]
                or c["slot"] != f"{n['case']}:r{n.get('repeat')}"
                or n.get("retry") is not c["retry"]
                or n["status"] != "ok"
                for n, c in zip(native[36:38], calls, strict=True)
            )
        ):
            raise authority.LedgerError(
                "conditional priority lost the stopped clause epoch or native 38-call prefix"
            )
        expected = {
            "manifest_digest": self.binding,
            "grant_digest": authority.digest(_read(authority.CONTINUATION_PATHS[8], "ninth grant")),
            "evidence": self.manifest["evidence"]["qualification"],
            "cases_digest": grant["next"]["cases_digest"],
            "inputs_digest": grant["next"]["inputs_digest"],
            "model_binding": grant["conditional_priority_allowance"]["model_binding"],
            "additional_calls": 31,
            "carried_calls": 29,
            "renewed_calls": 2,
            "shared_total": 249,
            "native_total": 69,
        }
        if (
            self.handoff["parent"]
            != _conditional_parent_binding(previous_campaign, previous, root, native[:38])
            or self.handoff["successor"] != expected
            or grant["conditional_priority_allowance"]["campaign_binding"] != self.binding
        ):
            raise authority.LedgerError(
                "the reviewed conditional priority ancestry or allowance changed"
            )
        return root

    def initialize_successor(self) -> str:
        """Append exactly epoch five once, preserving all earlier stops and charges."""
        with authority.locked(self.path):
            root = self._parent_state()
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or len(root.get("epochs", [])) != 4
                or os.path.lexists(str(self.epoch_dir))
                or len(authority.read(QUALIFICATION_PATH)["calls"]) != 38
            ):
                raise authority.LedgerError("conditional priority cannot be initialized again")
            state = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            epoch = {"id": 5, "handoff_digest": self.handoff_digest, "state": state}
            self.epoch_dir.mkdir(mode=0o700)
            self._transition(epoch)
            root["epochs"].append(epoch)
            authority._write(self.path, root)  # noqa: SLF001 - append under the existing canonical lock
            return authority.digest(state)


# The ninth's shared total, 249, plus the tenth's thirty renewed; the carried one was in it.
TENTH_SHARED_TOTAL = 279


# AGENTS.md, "Models for qualification review and marking": the approved AGY variants, each
# with the effort its name selects. From the tenth on, every marking and review receipt names
# one of these, and anything else is refused.
REVIEW_MODELS = {"gemini-3.8-flash-medium": "medium", "gemini-3.8-flash-high": "high"}
HANDOFF_RECEIPTS = ("marking", "kind_review", "handoff_review")


def review_receipt_valid(value: Any) -> bool:
    """Whether a receipt names exactly one approved model and the effort that model is."""
    return (
        isinstance(value, dict)
        and set(value) == {"model", "effort"}
        and isinstance(value["model"], str)
        and REVIEW_MODELS.get(value["model"]) == value["effort"]
    )


def _reviewed_handoff(handoff: Any) -> bool:
    """A GO handoff with a distinct preparer and reviewer and bound receipts, in a fixed shape."""
    return (
        isinstance(handoff, dict)
        and set(handoff)
        == {"v", "verdict", "prepared_by", "reviewed_by", "receipts", "parent", "successor"}
        and isinstance(handoff["receipts"], dict)
        and set(handoff["receipts"]) == set(HANDOFF_RECEIPTS)
        and all(review_receipt_valid(handoff["receipts"][k]) for k in HANDOFF_RECEIPTS)
        and type(handoff["v"]) is int
        and handoff["v"] == 1
        and handoff["verdict"] == "GO"
        and all(
            isinstance(handoff[k], str) and handoff[k].strip()
            for k in ("prepared_by", "reviewed_by")
        )
        and handoff["prepared_by"] != handoff["reviewed_by"]
    )


def tenth_parent_binding(previous: ConditionalPriorityCampaign) -> dict[str, Any]:
    """Bind the completed ninth measurement, every earlier epoch and the native 68."""
    state = previous._state()  # noqa: SLF001 - independently validated completed predecessor
    root = previous._parent_state()  # noqa: SLF001 - every ancestor and receipt is preserved
    native = authority.read(QUALIFICATION_PATH)["calls"][: authority.TENTH_PREVIOUS_CALLS]
    return _tenth_parent_binding(previous, state, root, native)


def _tenth_parent_binding(
    previous: ConditionalPriorityCampaign,
    state: dict[str, Any],
    root: dict[str, Any],
    native: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure assembly from this admission's freshly validated snapshots; never cached."""
    batches = len(previous.manifest["batches"]["qualification"])
    return {
        "manifest_digest": previous.binding,
        "activation_anchor": previous.manifest["activation_anchor"],
        "handoff_digest": previous.handoff_digest,
        "state_digest": authority.digest(state),
        "original_digest": authority.digest({k: v for k, v in root.items() if k != "epochs"}),
        "ancestor_epochs_digest": authority.digest(root["epochs"][:4]),
        "calls": len(state["calls"]),
        "calls_digest": authority.digest(state["calls"]),
        # The ninth was measured to the end, not stopped: its four batch reviews are the proof.
        "batch_reviews_digest": authority.digest(
            [
                _read(
                    str(previous.receipts / f"qualification-{n}-BATCH.json"),
                    "ninth batch review",
                )
                for n in range(batches)
            ]
        ),
        "failed_result_digest": authority.digest(
            _read(authority.result_path(9), "failed ninth result")
        ),
        "native_calls": len(native),
        "native_calls_digest": authority.digest(native),
        "native_chain": {
            "first": native[0]["id"],
            "calls": len(native),
            "head": authority.chain(native),
        },
    }


class TenthCampaign(ConditionalPriorityCampaign):
    """Fixed sixth epoch: the ninth's thirty measured readings stay; carry 1 and renew 30.

    It keeps the ninth's rules: every registered reading is measured, a semantic failure
    awaits its batch review rather than stopping the run, and only an unusable attempt may
    use the one retry.
    """

    epoch_id = 6

    def _validate_acceptance(
        self, lane: str, proof: Any, calls: list[dict[str, Any]], *, batch: int | None = None
    ) -> None:
        if batch is not None:
            if not isinstance(proof, dict) or not review_receipt_valid(proof.get("review")):
                raise authority.LedgerError(
                    "the batch review names no approved reviewer model and effort"
                )
            proof = {k: v for k, v in proof.items() if k != "review"}
        super()._validate_acceptance(lane, proof, calls, batch=batch)

    def __init__(self) -> None:
        self.parent = ConditionalPriorityCampaign()
        self.path = self.parent.path
        self.manifest, self.binding = self._current_manifest()
        self.epoch_dir = Path(self.path + ".epochs") / "6"
        self.receipts = self.epoch_dir / "reservations"
        self.handoff = _read(TENTH_HANDOFF_PATH, "tenth handoff")
        if not _reviewed_handoff(self.handoff):
            raise authority.LedgerError("the tenth needs an independent bound handoff")
        self.handoff_digest = authority.digest(self.handoff)
        self._parent_state()

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        body, key = _manifest(TENTH_MANIFEST_PATH)
        if body["order"] != ["qualification", "replay", "live"]:
            raise authority.LedgerError(
                "the tenth admits only qualification; later lanes stay held"
            )
        return body, key

    def _parent_state(self) -> dict[str, Any]:
        if (
            self._current_manifest() != (self.manifest, self.binding)
            or authority.digest(_read(TENTH_HANDOFF_PATH, "tenth handoff")) != self.handoff_digest
        ):
            raise authority.LedgerError("the tenth manifest or handoff changed")
        previous_campaign = cast("ConditionalPriorityCampaign", self.parent)
        previous = previous_campaign._state()  # noqa: SLF001 - validate every receipt of the measured epoch
        root = previous_campaign._parent_state()  # noqa: SLF001 - append only to the original canonical ledger
        native = authority.read(QUALIFICATION_PATH)["calls"]
        # Selected by number: once the retry is active the tenth is an ancestor, and its own
        # charges end where grant 11's previous chain ends.
        active = authority.continuation()
        generation = _successor_generation(active)
        end = active["previous"]["ledger_chain"]["calls"] if active and generation > 10 else None
        grant = authority.continuation(generation=10)
        calls = previous["calls"]
        slots = self.parent.manifest["slots"]["qualification"]
        prior = authority.TENTH_PREVIOUS_CALLS
        if (
            not grant
            or generation < 10
            or grant["generation"] != 10
            or grant["phase"] != "sealed"
            or not grant.get("tenth_continuation_allowance")
            or len(calls) != len(slots)
            or [c["slot"] for c in calls] != slots
            or any(c["status"] not in ("usable", "semantic-failed") for c in calls)
            or any(c["retry"] for c in calls)
            or previous.get("stop") is not None
            or previous.get("accepted")
            or set(previous.get("accepted_batches", {}))
            != {
                f"qualification:{n}"
                for n in range(len(self.parent.manifest["batches"]["qualification"]))
            }
            or not prior <= len(native) <= _native_ceiling(generation)
            or any(c["status"] == "charged" for c in native[:prior])
            or not authority.begins_with(QUALIFICATION_PATH, grant["previous"]["ledger_chain"])
            or not authority.follows(
                native if end is None else native[:end],
                grant,
                (grant["next"]["marks_digest"], grant["next"]["inputs_digest"]),
            )
            or self.manifest["historical"] != self.parent.manifest["historical"]
            or any(
                n.get("campaign_charge") != c["id"]
                or c["slot"] != f"{n['case']}:r{n.get('repeat')}"
                or n.get("retry") is not c["retry"]
                or n["status"] != "ok"
                for n, c in zip(native[38:prior], calls, strict=True)
            )
        ):
            raise authority.LedgerError(
                "the tenth lost the measured ninth epoch or the native 68-call prefix"
            )
        expected = {
            "manifest_digest": self.binding,
            "grant_digest": authority.digest(_read(authority.CONTINUATION_PATHS[9], "tenth grant")),
            "evidence": self.manifest["evidence"]["qualification"],
            "cases_digest": grant["next"]["cases_digest"],
            "inputs_digest": grant["next"]["inputs_digest"],
            "model_binding": grant["tenth_continuation_allowance"]["model_binding"],
            "additional_calls": authority.CLOSURE_CALLS,
            "carried_calls": authority.TENTH_CARRIED_CALLS,
            "renewed_calls": authority.TENTH_RENEWED_CALLS,
            "shared_total": TENTH_SHARED_TOTAL,
            "native_total": authority.TENTH_CAP,
        }
        if (
            self.handoff["parent"]
            != _tenth_parent_binding(previous_campaign, previous, root, native[:prior])
            or self.handoff["successor"] != expected
            or grant["tenth_continuation_allowance"]["campaign_binding"] != self.binding
        ):
            raise authority.LedgerError("the reviewed tenth ancestry or allowance changed")
        return root

    def initialize_successor(self) -> str:
        """Append exactly epoch six once, preserving every earlier epoch and charge."""
        with authority.locked(self.path):
            root = self._parent_state()
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or len(root.get("epochs", [])) != 5
                or os.path.lexists(str(self.epoch_dir))
                or len(authority.read(QUALIFICATION_PATH)["calls"])
                != authority.TENTH_PREVIOUS_CALLS
            ):
                raise authority.LedgerError("the tenth cannot be initialized again")
            state = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            epoch = {"id": 6, "handoff_digest": self.handoff_digest, "state": state}
            self.epoch_dir.mkdir(mode=0o700)
            self._transition(epoch)
            root["epochs"].append(epoch)
            authority._write(self.path, root)  # noqa: SLF001 - append under the existing canonical lock
            return authority.digest(state)


def retry_parent_binding(previous: TenthCampaign) -> dict[str, Any]:
    """Bind the failed tenth epoch as charged, every earlier epoch and the native prefix."""
    state = previous._state()  # noqa: SLF001 - independently validated failed predecessor
    root = previous._parent_state()  # noqa: SLF001 - every ancestor and receipt is preserved
    grant = authority.continuation(generation=11)
    if not grant or not grant.get("retry_continuation_allowance"):
        raise authority.LedgerError("the retry needs its own bound eleventh grant")
    end = grant["previous"]["ledger_chain"]["calls"]
    native = authority.read(QUALIFICATION_PATH)["calls"][:end]
    return _retry_parent_binding(previous, state, root, native)


def _retry_parent_binding(
    previous: TenthCampaign,
    state: dict[str, Any],
    root: dict[str, Any],
    native: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pure assembly from this admission's freshly validated snapshots; never cached."""
    batches = len(previous.manifest["batches"]["qualification"])
    reviews = [
        previous.receipts / f"qualification-{n}-BATCH.json"
        for n in range(batches)
        if f"qualification:{n}" in state.get("accepted_batches", {})
    ]
    return {
        "manifest_digest": previous.binding,
        "activation_anchor": previous.manifest["activation_anchor"],
        "handoff_digest": previous.handoff_digest,
        "state_digest": authority.digest(state),
        "original_digest": authority.digest({k: v for k, v in root.items() if k != "epochs"}),
        "ancestor_epochs_digest": authority.digest(root["epochs"][:5]),
        "calls": len(state["calls"]),
        "calls_digest": authority.digest(state["calls"]),
        "stop": state.get("stop"),
        "batch_reviews_digest": authority.digest(
            [_read(str(path), "tenth batch review") for path in reviews]
        ),
        "failed_result_digest": authority.digest(
            _read(authority.result_path(10), "failed tenth result")
        ),
        "native_calls": len(native),
        "native_calls_digest": authority.digest(native),
        "native_chain": {
            "first": native[0]["id"],
            "calls": len(native),
            "head": authority.chain(native),
        },
    }


class RetryCampaign(TenthCampaign):
    """Fixed seventh epoch: the one corrected retry after a failed tenth, 31 calls at most.

    It keeps the tenth's measurement rule. Its ceilings follow from what the tenth spent:
    with P native calls when result 10 was recorded, P + 31 native and 279 + (P - 68) shared.
    """

    epoch_id = 7

    def __init__(self) -> None:
        self.parent = TenthCampaign()
        self.path = self.parent.path
        self.manifest, self.binding = self._current_manifest()
        self.epoch_dir = Path(self.path + ".epochs") / "7"
        self.receipts = self.epoch_dir / "reservations"
        self.handoff = _read(RETRY_HANDOFF_PATH, "retry handoff")
        if not _reviewed_handoff(self.handoff):
            raise authority.LedgerError("the retry needs an independent bound handoff")
        self.handoff_digest = authority.digest(self.handoff)
        self._parent_state()

    def _current_manifest(self) -> tuple[dict[str, Any], str]:
        body, key = _manifest(RETRY_MANIFEST_PATH)
        if body["order"] != ["qualification", "replay", "live"]:
            raise authority.LedgerError(
                "the retry admits only qualification; later lanes stay held"
            )
        return body, key

    def _parent_state(self) -> dict[str, Any]:
        if (
            self._current_manifest() != (self.manifest, self.binding)
            or authority.digest(_read(RETRY_HANDOFF_PATH, "retry handoff")) != self.handoff_digest
        ):
            raise authority.LedgerError("the retry manifest or handoff changed")
        previous_campaign = cast("TenthCampaign", self.parent)
        previous = previous_campaign._state()  # noqa: SLF001 - validate every receipt of the failed epoch
        root = previous_campaign._parent_state()  # noqa: SLF001 - append only to the original canonical ledger
        native = authority.read(QUALIFICATION_PATH)["calls"]
        grant = authority.continuation()
        allowance = (grant or {}).get("retry_continuation_allowance") or {}
        prior = allowance.get("previous_calls")
        calls = previous["calls"]
        if (
            not grant
            or grant["generation"] != 11
            or grant["phase"] != "sealed"
            or not allowance
            or type(prior) is not int
            or len(calls) != prior - authority.TENTH_PREVIOUS_CALLS
            or any(c["status"] == "charged" for c in calls)
            or previous.get("accepted")
            or not prior <= len(native) <= prior + authority.CLOSURE_CALLS
            or any(c["status"] == "charged" for c in native[:prior])
            or not authority.begins_with(QUALIFICATION_PATH, grant["previous"]["ledger_chain"])
            or not authority.follows(
                native, grant, (grant["next"]["marks_digest"], grant["next"]["inputs_digest"])
            )
            or self.manifest["historical"] != self.parent.manifest["historical"]
            or any(
                n.get("campaign_charge") != c["id"]
                or c["slot"] != f"{n['case']}:r{n.get('repeat')}"
                or n.get("retry") is not c["retry"]
                # A transport failure is unusable in the campaign and failed natively.
                or (c["status"] == "unusable") != (n["status"] in ("failed", "unavailable"))
                for n, c in zip(native[authority.TENTH_PREVIOUS_CALLS : prior], calls, strict=True)
            )
        ):
            raise authority.LedgerError(
                "the retry lost the failed tenth epoch or the native prefix it charged"
            )
        renewed = prior - authority.TENTH_PREVIOUS_CALLS
        expected = {
            "manifest_digest": self.binding,
            "grant_digest": authority.digest(
                _read(authority.CONTINUATION_PATHS[10], "eleventh grant")
            ),
            "evidence": self.manifest["evidence"]["qualification"],
            "cases_digest": grant["next"]["cases_digest"],
            "inputs_digest": grant["next"]["inputs_digest"],
            "model_binding": allowance["model_binding"],
            "additional_calls": authority.CLOSURE_CALLS,
            "carried_calls": authority.TENTH_CAP - prior,
            "renewed_calls": renewed,
            # The tenth's shared ceiling held its carried attempts; only the renewed ones are new.
            "shared_total": TENTH_SHARED_TOTAL + renewed,
            "native_total": prior + authority.CLOSURE_CALLS,
        }
        if (
            self.handoff["parent"]
            != _retry_parent_binding(previous_campaign, previous, root, native[:prior])
            or self.handoff["successor"] != expected
            or allowance["campaign_binding"] != self.binding
        ):
            raise authority.LedgerError("the reviewed retry ancestry or allowance changed")
        return root

    def initialize_successor(self) -> str:
        """Append exactly epoch seven once, preserving every earlier epoch and charge."""
        with authority.locked(self.path):
            root = self._parent_state()
            grant = authority.continuation() or {}
            prior = grant["retry_continuation_allowance"]["previous_calls"]
            if (
                self.manifest["phase"] != "prepared"
                or self.manifest.get("activation_anchor")
                or len(root.get("epochs", [])) != 6
                or os.path.lexists(str(self.epoch_dir))
                or len(authority.read(QUALIFICATION_PATH)["calls"]) != prior
            ):
                raise authority.LedgerError("the retry cannot be initialized again")
            state = {
                "v": 1,
                "manifest_digest": self.binding,
                "calls": [],
                "genesis_nonce": uuid.uuid4().hex,
            }
            epoch = {"id": 7, "handoff_digest": self.handoff_digest, "state": state}
            self.epoch_dir.mkdir(mode=0o700)
            self._transition(epoch)
            root["epochs"].append(epoch)
            authority._write(self.path, root)  # noqa: SLF001 - append under the existing canonical lock
            return authority.digest(state)
