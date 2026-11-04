"""Bounded read-only session accounting history; no recovery or discard authority.

Byte totals are reserved prompt/reply allocations, not tokens or network usage.
Missing totals stay null. An empty cold inventory asserts no accounting totals.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal, TypedDict

from . import events
from . import reading_long_inspection as inspection
from . import reading_long_jobs as jobs
from .reading_long_recovery import _inventory, _snapshot

if TYPE_CHECKING:
    from .config import RuntimeConfig

Reason = Literal[
    "",
    "invalid-session",
    "inspection-clock-invalid",
    "inventory-unavailable",
    "inventory-bounded",
    "marker-unavailable",
    "marker-changed",
    "marker-unattributed",
    "accounting-unavailable",
]


class Totals(TypedDict):
    calls: int
    prompt_bytes: int
    reply_bytes: int


class Item(TypedDict):
    job_id: str
    state: str
    started_at: float
    updated_at: float
    terminal_at: float | None
    unsettled: bool | None
    accounting: str
    exact: Totals | None
    minimum: Totals | None
    reason: ItemReason


class History(TypedDict):
    version: int
    items: list[Item]
    incomplete: bool
    reason: Reason


def _totals(value: inspection.Totals | None) -> Totals | None:
    return (
        None
        if value is None
        else {
            "calls": value.calls,
            "prompt_bytes": value.prompt_bytes,
            "reply_bytes": value.reply_bytes,
        }
    )


def _incomplete(result: History, reason: Reason) -> None:
    result["incomplete"] = True
    if not result["reason"]:
        result["reason"] = reason


def read(config: RuntimeConfig, harness: str, sid: str, *, now: float) -> History:
    """Inspect only existing bounded records attributed by validated publication identity.

    This is an advisory read snapshot, not a transaction across markers and SQLite.
    Marker movement observed around inspection withholds the item. No owner liveness,
    restartability, acknowledgement or discard permission is inferred from this view.
    """
    result: History = {"version": 1, "items": [], "incomplete": False, "reason": ""}
    if not sid or len(sid) > 64 or events.normalize_session_id(harness, sid) != sid:
        _incomplete(result, "invalid-session")
        return result
    if type(now) not in (int, float) or not 0 <= now < 2**53 or not math.isfinite(now):
        _incomplete(result, "inspection-clock-invalid")
        return result
    try:
        ids, bounded = _inventory(config)
    except OSError:
        _incomplete(result, "inventory-unavailable")
        return result
    if bounded:
        _incomplete(result, "inventory-bounded")
    for job_id in ids:
        item, reason = _item(config, job_id, harness, sid, now)
        if item is not None:
            result["items"].append(item)
        if reason:
            _incomplete(result, reason)
    return result


def _item(
    config: RuntimeConfig, job_id: str, harness: str, sid: str, now: float
) -> tuple[Item | None, Reason]:
    marker = _snapshot(config, job_id)
    if marker is None:
        return None, "marker-unavailable"
    publication = marker["header"].get("publication")
    if publication is None:
        return None, "marker-unattributed"
    if (publication["harness"], publication["sid"]) != (harness, sid):
        return None, ""
    checked = inspection.inspect(config, job_id, now=now)
    if (
        _snapshot(config, job_id) != marker
        or checked.job_id != job_id
        or checked.marker_state != marker["state"]
        or (
            checked.header_sha256 is not None
            and checked.header_sha256 != jobs.digest(marker["header"])
        )
    ):
        return None, "marker-changed"
    item: Item = {
        "job_id": job_id,
        "state": marker["state"],
        "started_at": marker["header"]["started_at"],
        "updated_at": marker["updated_at"],
        "terminal_at": marker["terminal_at"],
        "unsettled": checked.unsettled,
        "accounting": checked.accounting,
        "exact": _totals(checked.exact),
        "minimum": _totals(checked.minimum),
        "reason": _inspection_reason(checked.reason),
    }
    return item, "" if checked.exact is not None else "accounting-unavailable"


ItemReason = Literal[
    "",
    "inspection-clock-invalid",
    "ledger-identity-unknown",
    "registration-inconsistent",
    "ledger-incomplete",
    "ledger-unavailable",
    "accounting-unavailable",
]


def _inspection_reason(value: str) -> ItemReason:
    # Do not expose arbitrary future diagnostics (which could contain private metadata).
    closed: tuple[ItemReason, ...] = (
        "",
        "inspection-clock-invalid",
        "ledger-identity-unknown",
        "registration-inconsistent",
        "ledger-incomplete",
        "ledger-unavailable",
    )
    return next((reason for reason in closed if value == reason), "accounting-unavailable")
