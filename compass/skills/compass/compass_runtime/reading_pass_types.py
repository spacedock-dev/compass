"""Closed long-reading declarations; no permission, spend or coverage claims."""

from __future__ import annotations

from typing import Any

from . import analyze_diagnostics

_PLAN_COUNTS = ("version", "max_evidence_passes", "max_reconciliation_passes", "max_calls")
_LIMITS = (
    "prompt_bytes",
    "input_bytes",
    "reply_bytes",
    "output_bytes",
    "source_bytes",
    "prepare_ms",
    "retained_bytes",
    "retained_units",
    "source_pages",
    "job_ms",
)


def _positive_count(value: Any) -> bool:
    return type(value) is int and 0 < value < 2**53


def validate_plan(value: Any) -> dict[str, Any] | None:
    """Copy a closed resource declaration, without admitting any live work."""
    if (
        not isinstance(value, dict)
        or set(value) != {*_PLAN_COUNTS, "mode", "limits"}
        or not all(_positive_count(value[key]) for key in _PLAN_COUNTS)
        or value["version"] != 1
        or value["mode"] != "long"
        or value["max_evidence_passes"] > 16
        or value["max_reconciliation_passes"] != 1
        or value["max_calls"] != value["max_evidence_passes"] + 1
        or not isinstance(value["limits"], dict)
        or set(value["limits"]) != set(_LIMITS)
        or not all(_positive_count(limit) for limit in value["limits"].values())
    ):
        return None
    return {**value, "limits": dict(value["limits"])}


def validate_pass(value: Any, *, plan: Any) -> dict[str, Any] | None:
    """Copy one observation at a reserved plan position, not an attempt count."""
    checked_plan = validate_plan(plan)
    if (
        checked_plan is None
        or not isinstance(value, dict)
        or set(value) != {"version", "ordinal", "kind", "diagnostic"}
        or type(value["version"]) is not int
        or value["version"] != 1
        or not _positive_count(value["ordinal"])
        or value["ordinal"] > checked_plan["max_calls"]
    ):
        return None
    kind = "reconciliation" if value["ordinal"] == checked_plan["max_calls"] else "evidence"
    if value["kind"] != kind:
        return None
    diagnostic = analyze_diagnostics.validate(value["diagnostic"])
    if value["diagnostic"] is not None and diagnostic is None:
        return None
    return {**value, "diagnostic": diagnostic}


def update_observations(
    current: Any, observation: Any, *, plan: Any, ended: Any
) -> list[dict[str, Any]] | None:
    """Replace an open slot, or append a new one, without altering caller data.

    The caller marks an invocation ended; diagnostics cannot establish that it
    ended, parsed successfully or covered its evidence. Ended slots are sealed.
    """
    checked_plan = validate_plan(plan)
    incoming = validate_pass(observation, plan=checked_plan)
    if (
        incoming is None
        or checked_plan is None
        or type(ended) is not bool
        or not isinstance(current, list)
        or len(current) > checked_plan["max_calls"]
    ):
        return None
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    replacement = {"observation": incoming, "ended": ended}
    for slot in current:
        if (
            not isinstance(slot, dict)
            or set(slot) != {"observation", "ended"}
            or type(slot["ended"]) is not bool
        ):
            return None
        checked = validate_pass(slot["observation"], plan=checked_plan)
        if checked is None or checked["ordinal"] in seen:
            return None
        seen.add(checked["ordinal"])
        if checked["ordinal"] == incoming["ordinal"]:
            if slot["ended"]:
                return None
            result.append(replacement)
        else:
            result.append({"observation": checked, "ended": slot["ended"]})
    if incoming["ordinal"] not in seen:
        result.append(replacement)
    return result
