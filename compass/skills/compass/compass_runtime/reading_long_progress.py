"""Closed word-free progress snapshots; no I/O, source proof or execution authority."""

from __future__ import annotations

from typing import Any

from . import reading_pass_types

STAGES = ("source", "evidence", "reconciliation", "publication")
_RECONCILIATION = ("not-started", "running", "ended")
_SOURCE = ("streams_total", "streams_verified", "bytes_read", "pages_read")


def _object(value: Any, keys: tuple[str, ...]) -> bool:
    return isinstance(value, dict) and set(value) == set(keys)


def _count(value: Any, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum and value < 2**53


def initial(plan: Any) -> dict[str, Any]:
    declared = reading_pass_types.validate_plan(plan)
    if declared is None:
        raise ValueError("Invalid long progress plan")
    return {
        "version": 1,
        "stage": "source",
        "source": dict.fromkeys(_SOURCE),
        "evidence": {"planned": None, "ended": 0, "current": None},
        "reconciliation": {"ordinal": declared["max_calls"], "state": "not-started"},
        "accounting": {"state": "unknown", "totals": None},
    }


def _totals(accounting: dict[str, Any], declared: dict[str, Any]) -> bool:
    totals = accounting["totals"]
    limits = declared["limits"]
    if accounting["state"] == "unknown":
        if totals is not None:
            return False
    elif (
        not _object(totals, ("calls", "prompt_bytes", "reply_bytes"))
        or not _count(totals["calls"], declared["max_calls"])
        or not _count(totals["prompt_bytes"], limits["input_bytes"])
        or not _count(totals["reply_bytes"], limits["output_bytes"])
        or totals["reply_bytes"] != totals["calls"] * limits["reply_bytes"]
        or totals["prompt_bytes"] > totals["calls"] * limits["prompt_bytes"]
    ):
        return False
    return True


def validate(value: Any, *, plan: Any) -> dict[str, Any] | None:
    """Copy only bounded metadata. Ended passes are not successful or charged calls.

    Source bytes/pages measure actual native reads, including verification;
    verified streams do not establish canonical evidence completeness. Receipt
    totals measure reserved assembled input and captured-reply allocations,
    never network usage. Accounting is an as-of snapshot, not launch authority.
    """
    declared = reading_pass_types.validate_plan(plan)
    if (
        declared is None
        or not _object(
            value, ("version", "stage", "source", "evidence", "reconciliation", "accounting")
        )
        or type(value["version"]) is not int
        or value["version"] != 1
        or value["stage"] not in STAGES
    ):
        return None
    source, evidence = value["source"], value["evidence"]
    reconciliation, accounting = value["reconciliation"], value["accounting"]
    limits = declared["limits"]
    if (
        not _object(source, _SOURCE)
        or not _object(evidence, ("planned", "ended", "current"))
        or not _object(reconciliation, ("ordinal", "state"))
        or not _object(accounting, ("state", "totals"))
    ):
        return None
    maxima = (512, 512, limits["source_bytes"], limits["source_pages"])
    if any(
        source[key] is not None and not _count(source[key], bound)
        for key, bound in zip(_SOURCE, maxima, strict=True)
    ) or (
        source["streams_total"] is not None
        and source["streams_verified"] is not None
        and source["streams_verified"] > source["streams_total"]
    ):
        return None
    planned, ended, current = evidence["planned"], evidence["ended"], evidence["current"]
    if (
        (planned is not None and not _count(planned, declared["max_evidence_passes"]))
        or not _count(ended, declared["max_evidence_passes"])
        or (planned is None and (ended != 0 or current is not None))
        or (planned is not None and ended > planned)
        or (
            current is not None
            and (
                not _count(current, planned or 0)
                or current == 0
                or current != ended + 1
                or value["stage"] != "evidence"
            )
        )
        or (value["stage"] in ("evidence", "reconciliation") and planned is None)
        or type(reconciliation["ordinal"]) is not int
        or reconciliation["ordinal"] != declared["max_calls"]
        or reconciliation["state"] not in _RECONCILIATION
        or (
            reconciliation["state"] != "not-started"
            and STAGES.index(value["stage"]) < STAGES.index("reconciliation")
        )
        or accounting["state"] not in ("unknown", "minimum", "exact")
    ):
        return None
    if not _totals(accounting, declared):
        return None
    totals = accounting["totals"]
    return {
        "version": 1,
        "stage": value["stage"],
        "source": dict(source),
        "evidence": dict(evidence),
        "reconciliation": dict(reconciliation),
        "accounting": {
            "state": accounting["state"],
            "totals": dict(totals) if totals is not None else None,
        },
    }


def follows(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """For validated snapshots only: a planned evidence set never changes mid-job."""
    old, new = before["evidence"], after["evidence"]
    return (
        STAGES.index(after["stage"]) >= STAGES.index(before["stage"])
        and (old["planned"] is None or new["planned"] == old["planned"])
        and new["ended"] >= old["ended"]
        and _RECONCILIATION.index(after["reconciliation"]["state"])
        >= _RECONCILIATION.index(before["reconciliation"]["state"])
    )
