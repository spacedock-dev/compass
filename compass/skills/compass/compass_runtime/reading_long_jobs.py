"""Private long-job binding and allocation checks; policy owns transactions and charges."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import reading_pass_types

if TYPE_CHECKING:
    from collections.abc import Callable

_PROCESS = object()
_FIELDS = frozenset(
    {
        "started_at",
        "plan",
        "scope_sha256",
        "target_sha256",
        "destination_sha256",
        "provider",
        "content",
    }
)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _hex(value: Any, size: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == size
        and all(c in "0123456789abcdef" for c in value)
    )


def _binding(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != _FIELDS:
        return None
    plan = reading_pass_types.validate_plan(value["plan"])
    if (
        plan is None
        or type(value["started_at"]) not in (int, float)
        or not 0 < value["started_at"] < 2**53
        or not math.isfinite(value["started_at"])
        or value["provider"] not in ("claude", "codex")
        or type(value["content"]) is not int
        or value["content"] not in (5, 6)
        or not all(
            _hex(value[field], 64)
            for field in ("scope_sha256", "target_sha256", "destination_sha256")
        )
    ):
        return None
    return {**value, "started_at": float(value["started_at"]), "plan": plan}


@dataclass(frozen=True)
class PreparedJob:
    job_id: str
    binding: str
    started_monotonic: float
    call_timeout_ms: int
    clock: Callable[[], float]
    process: object


@dataclass(frozen=True)
class LiveJob:
    # Created only after fresh durable registration. Replay returns none.
    prepared: PreparedJob
    process: object


def prepare(
    binding: Any, lineage: str, epoch: int, timeout: int, clock: Callable[[], float]
) -> PreparedJob | None:
    checked = _binding(binding)
    if checked is None or type(timeout) is not int or not 0 < timeout < 2**53:
        return None
    started = clock()
    if type(started) not in (int, float) or not math.isfinite(started):
        return None
    header = {
        **checked,
        "version": 1,
        "nonce": uuid.uuid4().hex,
        "lineage": lineage,
        "epoch": epoch,
    }
    return PreparedJob(digest(header)[:32], canonical(header), started, timeout, clock, _PROCESS)


def header(job: Any) -> dict[str, Any] | None:
    if (
        type(job) is not PreparedJob
        or job.process is not _PROCESS
        or not isinstance(job.binding, str)
    ):
        return None
    try:
        value = json.loads(job.binding)
        if (
            not isinstance(value, dict)
            or set(value) != _FIELDS | {"version", "nonce", "lineage", "epoch"}
            or type(value["version"]) is not int
            or value["version"] != 1
            or not _hex(value["nonce"], 32)
            or not _hex(value["lineage"], 32)
            or type(value["epoch"]) is not int
            or not 0 <= value["epoch"] < 2**63
            or _binding({key: value[key] for key in _FIELDS}) is None
            or digest(value)[:32] != job.job_id
            or canonical(value) != job.binding
        ):
            return None
    except (ValueError, TypeError, RecursionError):
        return None
    return value


def live_header(job: Any) -> dict[str, Any] | None:
    return header(job.prepared) if type(job) is LiveJob and job.process is _PROCESS else None


def activate(job: PreparedJob) -> LiveJob:
    return LiveJob(job, _PROCESS)


def deadline_reason(job: LiveJob, job_ms: int) -> str:
    prepared = job.prepared
    now = prepared.clock()
    start = prepared.started_monotonic
    if (
        type(now) not in (int, float)
        or not math.isfinite(now)
        or type(start) not in (int, float)
        or not math.isfinite(start)
        or now < start
        or type(prepared.call_timeout_ms) is not int
        or prepared.call_timeout_ms <= 0
    ):
        return "job-clock-invalid"
    return "job-deadline" if (now - start) * 1000 + prepared.call_timeout_ms > job_ms else ""


def ledger(db: Any, now: float, retention: float) -> float:
    columns = {row[1] for row in db.execute("PRAGMA table_info(long_permission)")}
    if "job_ledger_since" not in columns:
        db.execute("ALTER TABLE long_permission ADD COLUMN job_ledger_since REAL")
    since = db.execute("SELECT job_ledger_since FROM long_permission WHERE id=1").fetchone()[0]
    if since is None:
        db.execute(
            "CREATE TABLE long_job_registrations "
            "(job TEXT PRIMARY KEY, binding TEXT NOT NULL, started_at REAL NOT NULL)"
        )
        db.execute("UPDATE long_permission SET job_ledger_since=0 WHERE id=1")
    elif type(since) not in (int, float) or not math.isfinite(since) or since < 0:
        raise ValueError("Invalid job ledger watermark")
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS long_job_deleted AFTER DELETE ON long_job_registrations "
        "BEGIN UPDATE long_permission SET job_ledger_since=max(job_ledger_since, OLD.started_at) "
        "WHERE id=1; END"
    )
    db.execute("DELETE FROM long_job_registrations WHERE started_at <= ?", (now - retention,))
    db.execute(
        "UPDATE long_permission SET job_ledger_since=max(job_ledger_since, ?) WHERE id=1",
        (now - retention,),
    )
    return float(
        db.execute("SELECT job_ledger_since FROM long_permission WHERE id=1").fetchone()[0]
    )


def register(db: Any, job: PreparedJob, value: dict[str, Any], since: float) -> str:
    if value["started_at"] <= since:
        return "job-ledger-unknown"
    row = db.execute(
        "SELECT binding FROM long_job_registrations WHERE job=?", (job.job_id,)
    ).fetchone()
    if row is not None:
        return "already-registered" if row[0] == job.binding else "registration-conflict"
    if db.execute("SELECT 1 FROM long_pass_reservations WHERE job=?", (job.job_id,)).fetchone():
        return "job-ledger-unknown"
    db.execute(
        "INSERT INTO long_job_registrations VALUES (?, ?, ?)",
        (job.job_id, job.binding, value["started_at"]),
    )
    return "registered"


def matches(request: dict[str, Any], value: dict[str, Any], job_id: str) -> bool:
    return all(
        request[key] == expected
        for key, expected in {
            "job_id": job_id,
            "started_at": value["started_at"],
            "plan_sha256": digest(value["plan"]),
            "max_evidence_passes": value["plan"]["max_evidence_passes"],
            "destination_sha256": value["destination_sha256"],
            "provider": value["provider"],
            "content": value["content"],
        }.items()
    )


def registered(db: Any, job: LiveJob, value: dict[str, Any], since: float) -> str:
    if value["started_at"] <= since:
        return "job-ledger-unknown"
    row = db.execute(
        "SELECT binding FROM long_job_registrations WHERE job=?", (job.prepared.job_id,)
    ).fetchone()
    if row is None:
        return "job-not-registered"
    return "" if row[0] == job.prepared.binding else "job-binding-changed"


def allocations(
    request: dict[str, Any], value: dict[str, Any], receipts: list[dict[str, Any]]
) -> str:
    """Assembled prompt bytes and captured-reply allocations, not measured network usage."""
    plan = value["plan"]
    limits = plan["limits"]
    if request["prompt_bytes"] > limits["prompt_bytes"]:
        return "job-prompt-cap"
    slots = [*receipts, request]
    if len(slots) > plan["max_calls"]:
        return "job-call-cap"
    # A still-unreserved reconciliation needs a full prompt and reply allocation.
    reserved = not any(slot["kind"] == "reconciliation" for slot in slots)
    prompt_bytes = sum(slot["prompt_bytes"] for slot in slots)
    if prompt_bytes + (limits["prompt_bytes"] if reserved else 0) > limits["input_bytes"]:
        return "job-input-cap"
    if (len(slots) + int(reserved)) * limits["reply_bytes"] > limits["output_bytes"]:
        return "job-output-cap"
    return ""
