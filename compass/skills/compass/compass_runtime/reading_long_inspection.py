"""Read-only historical accounting and separately acknowledged terminal retirement."""

from __future__ import annotations

import contextlib
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import reading_long_jobs, reading_long_markers, reading_policy

if TYPE_CHECKING:
    from .config import RuntimeConfig

_SQL_ERROR = getattr(runtime_io.sqlite_module, "Error", RuntimeError)


@dataclass(frozen=True)
class Totals:
    """Reserved assembled prompts and captured-reply allocations, not network usage."""

    calls: int
    prompt_bytes: int
    reply_bytes: int


@dataclass(frozen=True)
class Inspection:
    job_id: str
    marker_state: str | None = None
    unsettled: bool | None = None
    exact: Totals | None = None
    minimum: Totals | None = None
    snapshot: str | None = None
    reason: str = ""

    @property
    def accounting(self) -> str:
        return (
            "exact"
            if self.exact is not None
            else "minimum"
            if self.minimum is not None
            else "unknown"
        )


def _number(value: Any) -> bool:
    return type(value) in (int, float) and 0 <= value < 2**53 and math.isfinite(value)


def _connect(config: RuntimeConfig) -> Any:
    path = reading_policy.store_path(config)
    if runtime_io.sqlite_module is None or path.is_symlink() or not path.is_file():
        raise OSError("Reading ledger unavailable")
    return runtime_io.sqlite_module.connect(
        path.absolute().as_uri() + "?mode=ro",
        uri=True,
        timeout=reading_policy.READ_WAIT_SEC,
        isolation_level=None,
    )


def _snapshot(config: RuntimeConfig, job_id: str) -> tuple[Any, Any, list[Any]]:
    with contextlib.closing(_connect(config)) as db:
        # All tables belong to this one read snapshot, even with WAL writers.
        db.execute("BEGIN")
        identity = db.execute(
            "SELECT lineage, epoch, pass_ledger_since, job_ledger_since "
            "FROM long_permission WHERE id=1"
        ).fetchone()
        registration = db.execute(
            "SELECT CASE WHEN length(binding)<=16384 THEN binding END, started_at "
            "FROM long_job_registrations WHERE job=?",
            (job_id,),
        ).fetchone()
        receipts = list(
            db.execute(
                "SELECT ordinal, CASE WHEN length(binding)<=8192 THEN binding END, at "
                "FROM long_pass_reservations WHERE job=? ORDER BY ordinal LIMIT 18",
                (job_id,),
            )
        )
        db.execute("COMMIT")
    return identity, registration, receipts


def _receipt(row: Any, header: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    try:
        ordinal, binding, at = row
        request = reading_policy.validate_long_request(
            json.loads(binding), now=header["started_at"]
        )
    except (ValueError, TypeError, RecursionError):
        return None
    if (
        request is None
        or type(ordinal) is not int
        or ordinal != request["ordinal"]
        or not _number(at)
        or at < header["started_at"]
        or not reading_long_jobs.matches(request, header, job_id)
    ):
        return None
    return request


def _accounting(
    marker: dict[str, Any], rows: tuple[Any, Any, list[Any]], now: float
) -> tuple[Totals | None, Totals | None, str]:
    identity, registration, raw_receipts = rows
    header = marker["header"]
    # Epoch may advance on Pause; historical charges still belong to this lineage.
    if (
        identity is None
        or identity[0] != header["lineage"]
        or type(identity[1]) is not int
        or not header["epoch"] <= identity[1] < 2**63
        or not all(_number(value) for value in identity[2:])
    ):
        return None, None, "ledger-identity-unknown"
    registered = False
    if registration is not None:
        try:
            value = reading_long_jobs.validate_header(json.loads(registration[0]), marker["job_id"])
        except (ValueError, TypeError, RecursionError):
            value = None
        if value != header or registration[1] != header["started_at"]:
            return None, None, "registration-inconsistent"
        registered = True
    complete = registered and header["started_at"] > max(
        *identity[2:], now - reading_policy.JOB_LEDGER_SEC
    )
    complete = complete and len(raw_receipts) <= header["plan"]["max_calls"]
    valid = []
    marked = {slot["request"]["ordinal"]: slot["request"] for slot in marker["passes"]}
    for row in raw_receipts:
        receipt = _receipt(row, header, marker["job_id"])
        if receipt is None:
            complete = False
        else:
            valid.append(receipt)
            if receipt["ordinal"] in marked and marked[receipt["ordinal"]] != receipt:
                complete = False
    totals = Totals(
        len(valid),
        sum(receipt["prompt_bytes"] for receipt in valid),
        len(valid) * header["plan"]["limits"]["reply_bytes"],
    )
    return (
        totals if complete else None,
        totals if complete or valid else None,
        "" if complete else "ledger-incomplete",
    )


def inspect(config: RuntimeConfig, job_id: str, *, now: float) -> Inspection:
    """Inspect without creating, migrating, pruning, capturing authority or resuming work."""
    marker = reading_long_markers.load(config, job_id)
    if marker is None:
        return Inspection("", reason="marker-unavailable")
    state = marker["state"]
    unsettled = state == "active" or any(slot["state"] != "settled" for slot in marker["passes"])
    if not _number(now) or now < marker["header"]["started_at"]:
        return Inspection(job_id, state, unsettled, reason="inspection-clock-invalid")
    try:
        rows = _snapshot(config, job_id)
        exact, minimum, reason = _accounting(marker, rows, now)
        snapshot = (
            reading_long_jobs.digest({"marker": marker, "ledger": rows})
            if exact is not None
            else None
        )
        return Inspection(job_id, state, unsettled, exact, minimum, snapshot, reason)
    except (OSError, ValueError, TypeError, RuntimeError, RecursionError, _SQL_ERROR):
        return Inspection(job_id, state, unsettled, reason="ledger-unavailable")


def _retirable(inspected: Inspection, acknowledged: bool) -> bool:
    return (
        acknowledged is True
        and type(inspected) is Inspection
        and inspected.exact is not None
        and inspected.snapshot is not None
        and inspected.marker_state not in (None, "active")
    )


def _retire_locked(
    config: RuntimeConfig, inspected: Inspection, *, acknowledged: bool, now: float
) -> bool:
    """Retire an unchanged snapshot; caller MUST hold the marker publication barrier."""
    if not _retirable(inspected, acknowledged):
        return False
    current = inspect(config, inspected.job_id, now=now)
    if (
        current.exact is None
        or current.marker_state in (None, "active")
        or current.snapshot != inspected.snapshot
    ):
        return False
    path = reading_long_markers.marker_path(config, inspected.job_id)
    path.unlink()
    reading_long_markers.sync_directory(path.parent)
    return True


def retire(config: RuntimeConfig, inspected: Inspection, *, acknowledged: bool, now: float) -> bool:
    """Explicit final-publication/discard acknowledgment, never a read-side cleanup.

    The controller owns acknowledgment timing. Terminal metadata and exact
    accounting alone do not establish owner death, successful execution or
    publication; an active record is never eligible.
    """
    if not _retirable(inspected, acknowledged):
        return False
    try:
        with reading_long_markers.publication_lock(config):
            return _retire_locked(config, inspected, acknowledged=acknowledged, now=now)
    except (OSError, ValueError, TypeError):
        return False
