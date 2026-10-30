#!/usr/bin/env python3
"""One explicitly armed native Claude browser press after accepted qualification.

This operator-only sidecar consumes held-live-00, one of the existing18 held
live attempts. It never changes qualification authority or its accounts.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import abstention_ledger as ledger
import analyze_campaign as campaigns

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "docs/drift-replay/closure-claude-route-conditional-priority.json"
HANDOFF_PATH = ROOT / "docs/drift-replay/closure-claude-route-conditional-priority-handoff.json"
OWNER_HOME = Path(ledger.canonical_home() or "/unavailable").resolve()
# The route's account, context and activation live in the study's own fixed home beside its
# other ledgers (`abstention_ledger.STUDY_HOME`), never in the moved default store.
STATE_PATH = (
    OWNER_HOME / ledger.STUDY_HOME / "analyze-closure-route-conditional-priority-spend.json"
)
PRIVATE_DIR = OWNER_HOME / ledger.STUDY_HOME / "claude-route-conditional-priority-verification"
# Independent of both mutable account/receipt history and the startup context.
# A prepared-profile rollback cannot erase this one-time activation evidence.
ACTIVATION_PATH = OWNER_HOME / ledger.STUDY_HOME / "claude-route-live00.ACTIVATED.json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TRANSPORT_KEYS = {"provider", "destination", "model", "effort", "binary_sha256", "argv_digest"}


class RefusalError(ledger.LedgerError):
    """A frozen authority, genuine app binding or durable attempt is absent."""


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(value: Any) -> str:
    return ledger.digest(value)


def profile_binding(body: dict[str, Any]) -> str:
    """Stable preparation identity; public sealing adds an irreversible genesis anchor."""
    return digest({k: v for k, v in body.items() if k not in ("phase", "activation_anchor")})


def source_digest() -> str:
    return sha(Path(__file__).read_bytes())


def _require(value: Any, reason: str) -> None:
    if not value:
        raise RefusalError(reason)


def _hex(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _canonical(path: Path) -> None:
    _require(path.is_absolute() and path.resolve() == path, "route path is aliased")


def _read(path: Path, *, private: bool = False) -> Any:
    path = Path(str(path))
    _canonical(path)
    try:
        value = ledger._review_json(str(path), "route artifact", cap=2 * 1024 * 1024)  # noqa: SLF001 - shared bounded non-symlink reader
        info = path.stat()
    except (OSError, ledger.LedgerError) as error:
        raise RefusalError("route artifact is missing or unreadable") from error
    if private and os.name != "nt":
        _require(
            stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid(),
            "route artifact is not owner-only",
        )
    return value


def _mkdir(path: Path) -> None:
    _canonical(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    _require(stat.S_ISDIR(info.st_mode), "route directory is not regular")
    if os.name != "nt":
        _require(
            stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid(),
            "route directory is not owner-only",
        )


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _persist(path: Path, body: Any) -> None:
    ledger._write(str(path), body)  # noqa: SLF001 - canonical atomic account writer under lock
    _sync_directory(path.parent)


def _exclusive(path: Path, value: Any) -> None:
    _canonical(path)
    try:
        fd = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(fd, "wb") as handle:
            handle.write(json.dumps(value, sort_keys=True).encode() + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(path.parent)
    except OSError as error:
        raise RefusalError("route receipt already exists or cannot be written") from error


def _runtime() -> tuple[Any, Any, Any, Any, Any]:
    skill = str(ROOT / "compass/skills/compass")
    if skill not in sys.path:
        sys.path.insert(0, skill)
    from compass_runtime import (  # noqa: PLC0415 - operator-only runtime admission
        annotations,
        observer,
        reading,
        reading_policy,
        reading_route,
    )

    return annotations, observer, reading, reading_policy, reading_route


def _qualification_snapshot() -> dict[str, Any]:
    """Require the actual fixed ninth campaign's complete independently accepted PASS."""
    current = campaigns.ConditionalPriorityCampaign()
    import score_abstention as scorer  # noqa: PLC0415 - exactly the qualified scorer source

    evidence = current.manifest["evidence"]["qualification"]
    runtime_digest = campaigns.runtime_source_digest(
        ROOT / "compass/skills/compass/compass_runtime"
    )
    _require(
        isinstance(evidence, dict)
        and set(evidence) == {"source", "scorer", "marks"}
        and all(_hex(value) for value in evidence.values())
        and evidence["source"] == runtime_digest
        and evidence["scorer"] == sha(Path(scorer.__file__).read_bytes())
        and current.manifest["protocols"]["qualification"] == "closure-three-repeats",
        "current runtime, scorer or protocol differs from qualified source",
    )
    state = current._state()  # noqa: SLF001 - all immutable ancestors and receipts are revalidated
    calls = state["calls"]
    current._stop(calls)  # noqa: SLF001 - no semantic/coverage/orphan failure may be continued
    _require(
        current.manifest["phase"] == "sealed"
        and not state.get("stop")
        and "qualification" in state.get("accepted", {}),
        "qualification has no independent final acceptance",
    )
    slots = current.manifest["slots"]["qualification"]
    latest = {call["slot"]: call["status"] for call in calls}
    _require(
        len(calls) in (30, 31)
        and len(slots) == 30
        and all(latest.get(slot) == "usable" for slot in slots),
        "qualification does not contain30 usable exposures",
    )
    native = ledger.read(campaigns.QUALIFICATION_PATH)["calls"]
    _require(
        len(native) == 38 + len(calls), "native qualification count differs from shared exposures"
    )
    for n, c in zip(native[38:], calls, strict=True):
        _require(
            n.get("campaign_charge") == c["id"]
            and f"{n['case']}:r{n.get('repeat')}" == c["slot"]
            and n.get("retry") is c["retry"]
            and n["status"] == ("ok" if c["status"] == "usable" else n["status"])
            and n["status"] != "charged",
            "native and shared qualification joins differ",
        )
    summary_path = Path(ledger.result_path(9))
    summary = _read(summary_path)
    _require(
        isinstance(summary, dict)
        and summary.get("verdict") == "passed"
        and summary.get("stopped") is False
        and summary.get("producer") == "claude"
        and summary.get("protocol") == "closure-three-repeats",
        "qualification result is not an actual completed PASS",
    )
    expected = {
        "unique_cases": 10,
        "registered_exposures": 30,
        "attempts": len(calls),
        "unusable_attempts": sum(c["status"] == "unusable" for c in calls),
    }
    _require(
        summary.get("counts") == expected
        and summary.get("ledger_chain") == ledger.chain_of(str(campaigns.QUALIFICATION_PATH)),
        "qualification result has another ledger or repetition count",
    )
    grant = ledger.continuation(generation=9)
    _require(
        grant is not None
        and grant["phase"] == "sealed"
        and grant["conditional_priority_allowance"]["model_binding"]
        == digest({key: summary.get(key) for key in scorer.BINDING_KEYS}),
        "qualification summary model identity differs from the fixed native grant",
    )
    repeats = summary.get("repetitions")
    _require(
        isinstance(repeats, list) and len(repeats) == 3,
        "qualification repetition summaries are missing",
    )
    for number, repeat in enumerate(repeats, 1):
        part = repeat.get("summary", {}) if isinstance(repeat, dict) else {}
        coverage = part.get("coverage", {}).get("claude", {})
        _require(
            repeat.get("repeat") == number
            and part.get("verdict") == "passed"
            and coverage.get("kinds") == 5
            and coverage.get("missing") == []
            and coverage.get("role") == "scored"
            and part.get("counts", {}).get("cases") == 10
            and part.get("counts", {}).get("reached_model") == 10,
            "qualification lacks three complete five-kind recorded passes",
        )
    acceptance = _read(current.receipts / "qualification-ACCEPTED.json")
    _require(
        _hex(acceptance.get("review_digest"))
        and acceptance.get("output_digest") == sha(summary_path.read_bytes()),
        "qualification review is missing or does not bind actual summary bytes",
    )
    root = ledger._review_json(current.path, "shared qualification account", cap=2 * 1024 * 1024)  # noqa: SLF001 - immutable complete shared state
    _require(
        len(root["calls"]) == 2 and len(root["epochs"]) == 5,
        "qualification history is not the fixed reviewed ancestry",
    )
    return {
        "native_calls": len(native),
        "qualification_calls": len(calls),
        "shared_calls": 10 + len(calls),
        "review_digest": acceptance["review_digest"],
        "summary_sha256": sha(summary_path.read_bytes()),
        "state_digest": digest(root),
        "native_digest": digest(native),
        "acceptance_digest": digest(acceptance),
        "manifest_digest": current.binding,
        "handoff_digest": current.handoff_digest,
        "runtime_digest": runtime_digest,
        "operator_source_digest": digest(
            {
                name: sha((ROOT / "scripts" / name).read_bytes())
                for name in (
                    "abstention_ledger.py",
                    "analyze_campaign.py",
                    "score_abstention.py",
                    "mark_abstention.py",
                )
            }
        ),
        "transport": {
            "provider": "claude",
            "destination": summary.get("destination"),
            "model": summary.get("model"),
            "effort": "high",
            "binary_sha256": summary.get("binary_sha256"),
            "argv_digest": summary.get("argv_digest"),
        },
    }


def qualification_snapshot() -> dict[str, Any]:
    """Normalize every missing, changed or incomplete qualification refusal."""
    try:
        return _qualification_snapshot()
    except (ledger.LedgerError, OSError, ValueError, KeyError, TypeError) as error:
        raise RefusalError("accepted ninth qualification is unavailable or changed") from error


class RouteVerification:
    """An independently bound one-attempt sidecar; construction never creates spend."""

    def __init__(self) -> None:
        self.profile = _read(PROFILE_PATH)
        self.handoff = _read(HANDOFF_PATH)
        self.path = STATE_PATH
        self.receipts = Path(str(self.path) + ".receipts")
        self.binding = profile_binding(self.profile)
        self.context = self._validate()
        if any(os.path.lexists(str(path)) for path in (ACTIVATION_PATH, self.path, self.receipts)):
            self._state()

    def _validate(self) -> dict[str, Any]:
        _canonical(OWNER_HOME)
        account_home = OWNER_HOME / ledger.STUDY_HOME
        _require(
            self.path.parent == account_home
            and account_home / "claude-route-live00.ACTIVATED.json" == ACTIVATION_PATH,
            "route account is not in the canonical owner home",
        )
        profile = _read(PROFILE_PATH)
        _require(
            profile == self.profile
            and set(profile)
            == {
                "v",
                "phase",
                "activation_anchor",
                "slot",
                "attempt_cap",
                "retry_cap",
                "held",
                "shared_cap",
                "qualification",
                "context_sha256",
                "wrapper_sha256",
                "transport",
            },
            "route profile changed or has unregistered fields",
        )
        _require(
            type(profile["v"]) is int
            and profile["v"] == 1
            and profile["phase"] in ("prepared", "sealed")
            and (
                profile["activation_anchor"] is None
                if profile["phase"] == "prepared"
                else _hex(profile["activation_anchor"])
            )
            and profile["slot"] == "held-live-00"
            and type(profile["attempt_cap"]) is int
            and profile["attempt_cap"] == 1
            and type(profile["retry_cap"]) is int
            and profile["retry_cap"] == 0
            and profile["held"] == {"live": 17, "replay": 190}
            and type(profile["shared_cap"]) is int
            and profile["shared_cap"] == 249,
            "route allocation is not the single approved held live attempt",
        )
        transport = profile["transport"]
        _require(
            isinstance(transport, dict)
            and set(transport) == _TRANSPORT_KEYS
            and transport["provider"] == "claude"
            and transport["destination"] == "Anthropic"
            and transport["effort"] == "high"
            and _hex(transport["binary_sha256"])
            and _hex(transport["argv_digest"]),
            "route transport is not the qualified Claude provider",
        )
        _, _, _, _, route = _runtime()
        route.runtime_config.validate_claude_reading_model(transport["model"])
        _require(
            profile["wrapper_sha256"] == source_digest()
            and profile["qualification"] == qualification_snapshot()
            and profile["transport"] == profile["qualification"].get("transport"),
            "route wrapper or accepted qualification changed",
        )
        handoff = _read(HANDOFF_PATH)
        _require(
            handoff == self.handoff
            and set(handoff)
            == {
                "v",
                "verdict",
                "prepared_by",
                "reviewed_by",
                "profile_digest",
                "activation_anchor",
                "qualification_review_digest",
            }
            and type(handoff["v"]) is int
            and handoff["v"] == 1
            and handoff["verdict"] == "GO"
            and all(
                isinstance(handoff[k], str) and handoff[k].strip()
                for k in ("prepared_by", "reviewed_by")
            )
            and handoff["prepared_by"] != handoff["reviewed_by"]
            and handoff["profile_digest"] == self.binding
            and handoff["activation_anchor"] == profile["activation_anchor"]
            and handoff["qualification_review_digest"] == profile["qualification"]["review_digest"],
            "route has no bound independent review",
        )
        context_path = Path(str(PRIVATE_DIR / "context.json"))
        context = _read(context_path, private=True)
        _require(
            profile["context_sha256"] == sha(context_path.read_bytes())
            and isinstance(context, dict)
            and set(context)
            == {
                "v",
                "startup",
                "selected",
                "app_binding",
                "prompt_sha256",
                "output_cap_bytes",
                "source_files",
                "ui_before_press_sha256",
            }
            and context["v"] == 1
            and _hex(context["app_binding"])
            and _hex(context["prompt_sha256"])
            and _hex(context["ui_before_press_sha256"])
            and type(context["output_cap_bytes"]) is int
            and context["output_cap_bytes"] == 8192,
            "route private source/app/prompt context is absent",
        )
        startup = context["startup"]
        selected = context["selected"]
        _require(
            isinstance(startup, dict)
            and set(startup) == {"pid", "nonce", "config_digest", "page_sha256"}
            and type(startup["pid"]) is int
            and startup["pid"] > 0
            and isinstance(startup["nonce"], str)
            and re.fullmatch(r"[0-9a-f]{32}", startup["nonce"]) is not None
            and _hex(startup["config_digest"])
            and _hex(startup["page_sha256"])
            and _read(PRIVATE_DIR / "startup.json", private=True) == startup,
            "route startup identity is missing or changed",
        )
        _require(
            isinstance(selected, dict)
            and set(selected) == {"sid", "full_sid"}
            and isinstance(selected["sid"], str)
            and re.fullmatch(r"[0-9a-f]{8}", selected["sid"]) is not None
            and isinstance(selected["full_sid"], str)
            and re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                selected["full_sid"],
            )
            is not None
            and selected["full_sid"].startswith(selected["sid"]),
            "route selected native identity is malformed",
        )
        _require(
            isinstance(context["source_files"], list) and 1 <= len(context["source_files"]) <= 16,
            "route source inventory is missing or exceeds its bound",
        )
        for row in context["source_files"]:
            _require(
                isinstance(row, dict) and set(row) == {"path", "sha256"} and _hex(row["sha256"]),
                "route source binding is malformed",
            )
            path = Path(row["path"])
            _canonical(path)
            _require(
                path.is_file()
                and path.stat().st_size <= 64 * 1024 * 1024
                and sha(path.read_bytes()) == row["sha256"],
                "route frozen source changed",
            )
        _require(
            any(
                row["sha256"] == context["ui_before_press_sha256"]
                for row in context["source_files"]
            ),
            "the before-press UI evidence is not among the frozen actual files",
        )
        return cast("dict[str, Any]", context)

    def _state(self, *, stale_failure: bool = False) -> dict[str, Any]:
        if not stale_failure:
            self._validate()
        body = _read(self.path, private=True)
        _require(
            isinstance(body, dict)
            and set(body) == {"v", "binding", "nonce", "attempt", "settlement", "acceptance"}
            and body["v"] == 1
            and body["binding"] == self.binding
            and isinstance(body["nonce"], str),
            "route account fields changed",
        )
        genesis = {**body, "attempt": None, "settlement": None, "acceptance": None}
        _require(
            _read(ACTIVATION_PATH, private=True)
            == {"v": 1, "binding": self.binding, "genesis_digest": digest(genesis)}
            and _read(self.receipts / "GENESIS.json", private=True) == genesis
            and self.profile["phase"] == "sealed"
            and digest(genesis) == self.profile["activation_anchor"],
            "route genesis is missing, changed or not independently sealed",
        )
        allowed = {"GENESIS.json"}
        if body["attempt"] is not None:
            allowed.add("CHARGED.json")
            _require(
                _read(self.receipts / "CHARGED.json", private=True) == body["attempt"],
                "route charged attempt was lost or rewritten",
            )
            _require(
                set(body["attempt"]) == {"id", "binding", "slot", "request_digest"}
                and body["attempt"]["binding"] == self.binding
                and body["attempt"]["slot"] == "held-live-00",
                "route charged attempt is unregistered",
            )
        if body["settlement"] is not None:
            allowed.add("SETTLED.json")
            _require(
                body["attempt"] is not None
                and _read(self.receipts / "SETTLED.json", private=True) == body["settlement"],
                "route settlement changed",
            )
        if body["acceptance"] is not None:
            allowed.add("ACCEPTED.json")
            _require(
                body["settlement"] is not None
                and _read(self.receipts / "ACCEPTED.json", private=True) == body["acceptance"],
                "route acceptance changed",
            )
        _require(
            {path.name for path in self.receipts.iterdir()} == allowed,
            "route receipt history has missing or unexpected files",
        )
        return cast("dict[str, Any]", body)

    def initialize(self) -> str:
        self._validate()
        _require(
            self.profile["phase"] == "prepared" and self.profile["activation_anchor"] is None,
            "sealed route authority cannot initialize or refund missing history",
        )
        _mkdir(self.path.parent)
        with ledger.locked(str(self.path)):
            _require(
                not any(
                    os.path.lexists(str(path))
                    for path in (ACTIVATION_PATH, self.path, self.receipts)
                ),
                "route cannot be initialized again or refunded",
            )
            body = {
                "v": 1,
                "binding": self.binding,
                "nonce": uuid.uuid4().hex,
                "attempt": None,
                "settlement": None,
                "acceptance": None,
            }
            # Charge authority is never reminted after an interrupted activation.
            # This durable tombstone precedes either deletable history namespace.
            _exclusive(
                ACTIVATION_PATH,
                {"v": 1, "binding": self.binding, "genesis_digest": digest(body)},
            )
            _mkdir(self.receipts)
            _exclusive(self.receipts / "GENESIS.json", body)
            _persist(self.path, body)
            return digest(body)

    def reserve(self, request: dict[str, Any]) -> str:
        with ledger.locked(str(self.path)):
            body = self._state()
            expected = {
                "app_binding": self.context["app_binding"],
                "prompt_sha256": self.context["prompt_sha256"],
                "output_cap_bytes": self.context["output_cap_bytes"],
                "transport": self.profile["transport"],
            }
            _require(
                request == expected and body["attempt"] is None,
                "route request differs or its single attempt was consumed",
            )
            charge = {
                "id": uuid.uuid4().hex,
                "binding": self.binding,
                "slot": "held-live-00",
                "request_digest": digest(request),
            }
            _exclusive(self.receipts / "CHARGED.json", charge)
            body["attempt"] = charge
            _persist(self.path, body)
            return charge["id"]

    def settle_transport(
        self, charge_id: str, status: str, *, output_digest: str, diagnostic_digest: str = ""
    ) -> None:
        _require(
            status in ("ok", "failed", "unavailable", "cancelled", "unstopped", "oversized"),
            "route transport status is unregistered",
        )
        with ledger.locked(str(self.path)):
            # A charged native failure still records its exact terminal reason
            # if evidence/consent moved during execution. Immutable charge,
            # genesis and activation checks remain mandatory; success cannot
            # inherit stale admission.
            body = self._state(stale_failure=status != "ok")
            _require(
                body["attempt"] is not None
                and body["attempt"]["id"] == charge_id
                and body["settlement"] is None
                and _hex(output_digest)
                and (not diagnostic_digest or _hex(diagnostic_digest)),
                "route settlement has no unsettled charged attempt",
            )
            result = {
                "charge_id": charge_id,
                "status": status,
                "output_digest": output_digest,
                "diagnostic_digest": diagnostic_digest,
            }
            _exclusive(self.receipts / "SETTLED.json", result)
            body["settlement"] = result
            _persist(self.path, body)

    def accept_route(self, proof: dict[str, Any]) -> None:
        with ledger.locked(str(self.path)):
            body = self._state()
            _require(
                body["settlement"] is not None
                and body["settlement"]["status"] == "ok"
                and body["acceptance"] is None
                and isinstance(proof, dict)
                and set(proof)
                == {
                    "v",
                    "verdict",
                    "profile_digest",
                    "charge_id",
                    "output_digest",
                    "job_digest",
                    "stored_reading_digest",
                    "ui_result_digest",
                    "reload_digest",
                    "review_digest",
                }
                and proof["v"] == 1
                and proof["verdict"] == "passed"
                and proof["profile_digest"] == self.binding
                and proof["charge_id"] == body["attempt"]["id"]
                and proof["output_digest"] == body["settlement"]["output_digest"]
                and all(
                    _hex(proof[k])
                    for k in (
                        "job_digest",
                        "stored_reading_digest",
                        "ui_result_digest",
                        "reload_digest",
                        "review_digest",
                    )
                ),
                "route acceptance lacks native job/reading/UI/reload and independent review",
            )
            _exclusive(self.receipts / "ACCEPTED.json", proof)
            body["acceptance"] = proof
            _persist(self.path, body)

    def budget_view(self) -> dict[str, Any]:
        body = self._state()
        used = int(body["attempt"] is not None)
        return {
            "route_attempts": used,
            "route_accepted": body["acceptance"] is not None,
            "shared_charged": self.profile["qualification"]["shared_calls"] + used,
            "shared_cap": 249,
            "qualification_retry_held": 31 - self.profile["qualification"]["qualification_calls"],
            "held": {"live": 17, "replay": 190},
        }


def _normalize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(k): _normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    return value


def config_digest(config: Any) -> str:
    return digest(
        {
            field.name: _normalize(getattr(config, field.name))
            for field in dataclasses.fields(config)
        }
    )


def app_binding(application: Any, selected: dict[str, Any]) -> str:
    """Read the actual owned application's native row, source, revision, route and consent."""
    annotations, observer, reading, policy, route = _runtime()
    config = application.config
    _require(
        not config.observer_model_enabled
        and not config.unasked_enabled
        and not config.model_calls_disabled
        and Path(config.home).resolve() == OWNER_HOME
        and config.annotations_enabled,
        "route app configuration is unsafe or belongs to another account",
    )
    _, raw = application.collect_json(show_all=True)
    rows = json.loads(raw)["sessions"]
    chosen = [
        row
        for row in rows
        if row.get("harness") == "claude"
        and row.get("sid") == selected["sid"]
        and row.get("resume_id") == selected["full_sid"]
    ]
    _require(len(chosen) == 1, "route has no unique genuine native Claude session")
    row = chosen[0]
    entry = annotations.find(annotations.load(config), "claude", selected["full_sid"])
    _require(entry is not None and entry.get("revisions"), "route has no saved native intent")
    revisions = entry["revisions"]
    scope, why = reading.eligibility(
        row,
        latest_revision_at=float(revisions[-1]["at"]),
        now=application.clock(),
        settle_sec=config.reading_settle_sec,
        admit_turn_stop=True,
        # Not the idle admission of 2026-10-20: the qualification this press follows was accepted
        # under the earlier rule, which withheld an idle session with no recorded finish.
        admit_idle=False,
    )
    _require(scope and not why, "native Claude session is not eligible")
    transcript = observer.resolve_transcript(config, application.state, "claude", selected["sid"])
    _require(
        transcript and Path(transcript).stem == selected["full_sid"],
        "route native transcript identity differs",
    )
    path = Path(transcript)
    _canonical(path)
    disclosure = route.resolve("claude", config=config)
    _require(
        disclosure["provider"] == "claude"
        and disclosure["words_destination"] == "Anthropic"
        and disclosure["model"] == config.claude_reading_model
        and shutil.which("codex") is None,
        "route provider, model or privatePATH differs",
    )
    consent = policy.status(
        config,
        now=application.clock(),
        provider="claude",
        destinations={"claude": "Anthropic"},
        content=policy.CONTENT_VERSION,
    )
    _require(
        consent["providers"].get("claude") is True and "claude" not in consent["rebind"],
        "native Claude destination/content consent is absent",
    )
    return digest(
        {
            "config": config_digest(config),
            "row": {
                key: row.get(key)
                for key in (
                    "harness",
                    "sid",
                    "resume_id",
                    "state",
                    "finished_at",
                    "ended_at",
                    "acquisition",
                )
            },
            "scope": scope,
            "revisions": _normalize(revisions),
            "transcript_sha256": sha(path.read_bytes()),
            "route": {
                key: disclosure[key] for key in ("provider", "words_destination", "model", "reason")
            },
            "consent": {
                "provider": consent["providers"].get("claude"),
                "tool_output": consent["tool_output"].get("claude", []),
            },
        }
    )


def transport_binding(config: Any, *, claude_executor: Any = None) -> dict[str, Any]:
    _, observer, _, _, route = _runtime()
    import score_abstention as scorer  # noqa: PLC0415 - existing native identity verifier

    with scorer.verify_claude_binary() as verified:
        installed = shutil.which("claude")
        _require(
            installed
            and scorer.file_identity(os.path.realpath(installed))[-1] == verified.identity[-1],
            "native installed Claude differs from its verified bytes",
        )
        return {
            "provider": "claude",
            "destination": route.destination("claude"),
            "model": config.claude_reading_model,
            "effort": observer.CLAUDE_READING_EFFORT,
            "binary_sha256": verified.identity[-1],
            "argv_digest": scorer.argv_digest("claude", config, claude_executor=claude_executor),
        }


@contextlib.contextmanager
def install_native_guard() -> Iterator[dict[str, Any]]:
    """Guard this owned genuine server process; no fake provider or replacement HTTP route."""
    qualification_snapshot()
    _, observer, _, _, _ = _runtime()
    from compass_runtime import cli, supervise  # noqa: PLC0415 - canonical server/runtime seams

    native_exec = observer.claude_exec
    native_codex = observer.codex_exec
    native_builder = cli.build_server
    captured: dict[str, Any] = {}
    _mkdir(PRIVATE_DIR)

    def build_server(*args: Any, **kwargs: Any) -> Any:
        app = args[1]
        _require(not captured, "route launcher admits one genuine application")
        cfg = app.config
        _require(
            not cfg.observer_model_enabled
            and not cfg.unasked_enabled
            and not cfg.model_calls_disabled,
            "route launcher must disable background models without disabling Analyze",
        )
        startup = {
            "pid": os.getpid(),
            "nonce": uuid.uuid4().hex,
            "config_digest": config_digest(cfg),
            "page_sha256": sha(args[2]),
        }
        _exclusive(PRIVATE_DIR / "startup.json", startup)
        captured.update(application=app, startup=startup)
        return native_builder(*args, **kwargs)

    def deny_codex(*_args: Any, **_kwargs: Any) -> Any:
        raise RefusalError("Codex model execution is denied for this route verification")

    def guarded(
        config: Any,
        prompt: str,
        *,
        output_cap_bytes: int,
        runner: Any = supervise.run,
        binary_resolver: Any = shutil.which,
        on_spawn: Any = None,
        on_diagnostic: Any = None,
    ) -> tuple[str, str]:
        _require(
            captured
            and config is captured["application"].config
            and runner is supervise.run
            and binary_resolver is shutil.which,
            "route callback is not the genuine protected native app model",
        )
        current = RouteVerification()
        _require(
            current.context["startup"] == captured["startup"]
            and _read(PRIVATE_DIR / "startup.json", private=True) == captured["startup"],
            "route callback belongs to another launch",
        )
        actual = {
            "app_binding": app_binding(captured["application"], current.context["selected"]),
            "prompt_sha256": sha(prompt.encode()),
            "output_cap_bytes": output_cap_bytes,
            "transport": transport_binding(config, claude_executor=native_exec),
        }
        charge = current.reserve(actual)
        try:
            _require(
                app_binding(captured["application"], current.context["selected"])
                == actual["app_binding"]
                and transport_binding(config, claude_executor=native_exec) == actual["transport"],
                "route binding changed after charge",
            )
            raw, status = native_exec(
                config,
                prompt,
                output_cap_bytes=output_cap_bytes,
                runner=runner,
                binary_resolver=binary_resolver,
                on_spawn=on_spawn,
                on_diagnostic=on_diagnostic,
            )
        except BaseException:
            current.settle_transport(charge, "failed", output_digest=sha(b""))
            raise
        current.settle_transport(charge, status, output_digest=sha(raw.encode()))
        return raw, status

    observer.claude_exec = guarded
    observer.codex_exec = deny_codex
    cli.build_server = build_server
    try:
        yield captured
    finally:
        observer.claude_exec = native_exec
        observer.codex_exec = native_codex
        cli.build_server = native_builder


def run_server(argv: Sequence[str]) -> int:
    _runtime()
    from compass_runtime import cli  # noqa: PLC0415 - genuine normal server entry point

    args = cli.build_parser().parse_args(list(argv))
    _require(
        args.host == "127.0.0.1"
        and not any(
            getattr(args, key, False)
            for key in (
                "daemon",
                "stop",
                "status",
                "diagnose",
                "observer_model",
                "unasked_readings",
                "no_observer_model",
                "no_annotations",
            )
        ),
        "route launcher requires a foreground loopback server with background models off",
    )
    with install_native_guard():
        return int(cli.main(list(argv)) or 0)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--budget", action="store_true")
    parser.add_argument("server_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.initialize:
        print(RouteVerification().initialize())
        return 0
    if args.budget:
        print(json.dumps(RouteVerification().budget_view(), sort_keys=True))
        return 0
    _require(
        args.server_args, "explicit initialization, budget readback or server arguments required"
    )
    return run_server(args.server_args[1:] if args.server_args[0] == "--" else args.server_args)


if __name__ == "__main__":
    raise SystemExit(main())
