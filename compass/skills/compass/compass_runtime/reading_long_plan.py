"""Production long-reading limits and a pure advisory pre-start descriptor.

Callers supply current owner snapshots. Preview reads no files, discovers no
source, captures no permission/target and reserves no slot or daily allowance.
Actual Start must refresh route, plan, intent, source capability and permission.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Literal

from . import ci_read, reading, reading_pass_types, reading_route, settings
from . import reading_long_jobs as jobs
from . import reading_policy as policy
from . import reading_source_collect as source_collect

MAX_EVIDENCE_PASSES = 16
RECONCILIATION_PASSES = 1
AGGREGATE_INPUT_BYTES = 16 * 1024 * 1024
WHOLE_JOB_MS = 1800 * 1000


@dataclass(frozen=True)
class SourceEstimate:
    """Caller-measured capability/metadata, never a frozen endpoint or corpus proof.

    observed_at is the metadata observation time, not an unread record's time.
    parent_bytes is that parent's physical extent; children and verification I/O
    are separate, and no amount of this metadata proves a complete corpus.
    """

    harness: str
    sid: str
    capability: Literal["native-claude", "unsupported", "unknown"] = "unknown"
    parent_bytes: int | None = None
    observed_at: float | None = None


def _count(value: Any, *, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value < 2**53


def _moment(value: Any) -> float | None:
    return (
        float(value)
        if type(value) in (int, float) and math.isfinite(value) and 0 < value < 2**53
        else None
    )


def _route(route: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if (
        not isinstance(route, Mapping)
        or route.get("harness") != "claude"
        or route.get("provider") not in policy.PROVIDERS
        or any(
            not isinstance(route.get(key), str) or len(route[key]) > 1024
            for key in ("model", "words_destination", "destination")
        )
        or not route.get("model")
        or type(route.get("fallback")) is not bool
        or route.get("reason")
        not in (
            reading_route.REASON_OWN_HARNESS,
            reading_route.REASON_NO_OWN_PRODUCER,
            reading_route.REASON_FALLBACK_MISSING,
            reading_route.REASON_FALLBACK_UNQUALIFIED,
        )
        or route.get("ci_read")
        not in (ci_read.SETTING_OFF, ci_read.SETTING_ON, ci_read.SETTING_FLAG)
    ):
        return None
    return {
        key: route[key]
        for key in (
            "harness",
            "provider",
            "model",
            "words_destination",
            "destination",
            "reason",
            "fallback",
            "ci_read",
        )
    }


def build(route: Mapping[str, Any] | None, preferences: settings.Settings) -> dict[str, Any] | None:
    """Build the actual closed declaration from saved ceiling and resolved route capacity.

    route must be the current reading_route.resolve result, including its
    analyze_capacity.preview. The policy ceiling remains an estimate; final
    assembled prompts still require the real invocation's Admission check.
    """
    capacity = route.get("capacity") if isinstance(route, Mapping) else None
    if (
        _route(route) is None
        or type(preferences) is not settings.Settings
        or any(
            not _count(value, minimum=limit.minimum) or value > limit.maximum
            for value, limit in zip(preferences, settings.LIMITS, strict=True)
        )
        or not isinstance(capacity, dict)
        or capacity.get("kind") != "capacity-preview"
        or capacity.get("policy") != "analyze-context-v1"
        or capacity.get("reason") != "estimated"
        or capacity.get("fit_verified") is not False
        or capacity.get("configuration_reason") not in ("", None)
        or not _count(
            capacity.get("maximum_prompt_bytes"), minimum=settings.ANALYZE_PROMPT_MIN_BYTES
        )
        or capacity["maximum_prompt_bytes"] > settings.LIMITS[0].maximum
    ):
        return None
    max_calls = MAX_EVIDENCE_PASSES + RECONCILIATION_PASSES
    return reading_pass_types.validate_plan(
        {
            "version": 1,
            "mode": "long",
            "max_evidence_passes": MAX_EVIDENCE_PASSES,
            "max_reconciliation_passes": RECONCILIATION_PASSES,
            "max_calls": max_calls,
            "limits": {
                **asdict(source_collect.Limits()),
                "prompt_bytes": min(
                    preferences.analyze_prompt_bytes, capacity["maximum_prompt_bytes"]
                ),
                "input_bytes": AGGREGATE_INPUT_BYTES,
                "reply_bytes": reading.REPLY_CAP_BYTES,
                "output_bytes": max_calls * reading.REPLY_CAP_BYTES,
                "job_ms": WHOLE_JOB_MS,
            },
        }
    )


def _allowance(status: Mapping[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "limit": policy.DAILY_CAP,
        "window_seconds": policy.DAY_SEC,
        "used": None,
        "remaining": None,
        "state": "unknown",
        "reserved": False,
    }
    if not isinstance(status, Mapping):
        return result
    if status.get("reason") in ("run-disabled", "store-unavailable"):
        result["state"] = "run-disabled" if status["reason"] == "run-disabled" else "unavailable"
        return result
    paused = status.get("off") is True or status.get("reason") == "model-calls-paused"
    if (
        status.get("limit") != policy.DAILY_CAP
        or not _count(status.get("used"))
        or type(status.get("off")) is not bool
        or (status.get("consent") is not True and not paused)
        or status.get("reason") not in ("", "daily-cap", "model-calls-paused")
    ):
        return result
    used = status["used"]
    result.update(used=used, remaining=max(0, policy.DAILY_CAP - used))
    result["state"] = (
        "paused"
        if paused
        else "daily-cap"
        if used >= policy.DAILY_CAP or status["reason"] == "daily-cap"
        else "available"
    )
    return result


def _source(row: Mapping[str, Any], estimate: SourceEstimate | None) -> dict[str, Any]:
    capability = "unknown"
    if row.get("harness") != "claude":
        capability = "unsupported"
    elif (
        type(estimate) is SourceEstimate
        and (estimate.harness, estimate.sid) == (row.get("harness"), row.get("sid"))
        and estimate.capability in ("native-claude", "unsupported", "unknown")
    ):
        capability = estimate.capability
    native = capability == "native-claude"
    return {
        "capability": capability,
        "kinds": ["parent", "admitted-subagent"] if native else [],
        "parent_bytes": estimate.parent_bytes
        if native and estimate is not None and _count(estimate.parent_bytes)
        else None,
        "observed_at": _moment(estimate.observed_at) if native and estimate is not None else None,
        "stream_count": None,
        "record_count": None,
        "frozen": False,
    }


def _intent(
    row: Mapping[str, Any], entry: Mapping[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    unknown = {"revision": None, "start_at": None}
    if entry is None or (entry.get("harness"), entry.get("sid")) != (
        row.get("harness"),
        row.get("sid"),
    ):
        return unknown, None
    revisions = entry.get("revisions")
    latest = revisions[-1] if isinstance(revisions, (tuple, list)) and revisions else None
    if (
        not isinstance(latest, dict)
        or not _count(latest.get("n"), minimum=1)
        or _moment(latest.get("at")) is None
        or not (str(latest.get("goal") or "").strip() or reading.outcome_lines(latest))
    ):
        return unknown, None
    start = _moment(reading.window_start(latest))
    return (
        ({"revision": latest["n"], "start_at": start}, latest)
        if start is not None
        else (unknown, None)
    )


def _reason(
    source: dict[str, Any],
    route: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    intent: dict[str, Any] | None,
    eligible: bool,
    allowance: dict[str, Any],
) -> str:
    if source["capability"] != "native-claude":
        return (
            "unsupported-source" if source["capability"] == "unsupported" else "source-unavailable"
        )
    if route is None:
        return "route-unavailable"
    if plan is None:
        return "capacity-unavailable"
    if intent is None:
        return "intent-unavailable"
    if not eligible:
        return "intent-ineligible"
    return "" if allowance["state"] == "available" else "allowance-unavailable"


def describe(
    *,
    row: Mapping[str, Any],
    entry: Mapping[str, Any] | None,
    route: Mapping[str, Any] | None,
    preferences: settings.Settings,
    policy_status: Mapping[str, Any] | None,
    source: SourceEstimate | None,
    now: float,
    settle_sec: float,
) -> dict[str, Any]:
    """Closed, word-free preview. can_start is advisory, never live authority.

    binding covers saved intent/route/settings/plan, not moving allowance or
    endpoint estimates. Actual Start rechecks all owners before any source/model
    work and captures its endpoint then; it cannot treat this digest as a grant.
    """
    selected = _route(route)
    plan = build(route, preferences)
    intent, latest = _intent(row, entry)
    source_info, allowance = _source(row, source), _allowance(policy_status)
    valid_clock = (
        _moment(now) is not None
        and type(settle_sec) in (int, float)
        and math.isfinite(settle_sec)
        and settle_sec >= 0
    )
    eligible = bool(
        latest is not None
        and valid_clock
        and reading.press_eligibility(
            row,
            [latest],
            now=now,
            settle_sec=settle_sec,
        )["ok"]
    )
    binding = None
    if selected is not None and plan is not None and latest is not None:
        try:
            binding = jobs.digest(
                {
                    "version": 1,
                    "harness": row.get("harness"),
                    "sid": row.get("sid"),
                    "route": selected,
                    "plan": plan,
                    "settings": preferences._asdict(),
                    "intent": latest,
                }
            )
        except (TypeError, ValueError, RecursionError):
            latest = None
    reason = _reason(source_info, selected, plan, latest, eligible, allowance)
    return {
        "version": 1,
        "mode": "long",
        "supported": source_info["capability"] == "native-claude",
        "can_start": reason == "",
        "reason": reason,
        "binding": binding,
        "route": selected,
        "intent": intent,
        "source": source_info,
        "allowance": allowance,
        "plan": plan,
        "prompt": {
            "saved_ceiling_bytes": preferences.analyze_prompt_bytes
            if type(preferences) is settings.Settings
            and _count(preferences.analyze_prompt_bytes, minimum=settings.ANALYZE_PROMPT_MIN_BYTES)
            and preferences.analyze_prompt_bytes <= settings.LIMITS[0].maximum
            else None,
            "route_ceiling_bytes": route["capacity"]["maximum_prompt_bytes"]
            if plan is not None and route is not None
            else None,
            "fit_verified": False,
        },
        "measurements": {
            "prompt_bytes": "assembled-input",
            "input_bytes": "aggregate-assembled-input",
            "reply_bytes": "captured-reply-allocation",
            "source_bytes": "native-actual-io",
            "retained_bytes": "retained-object-graph",
            "prepare_ms": "source-and-analysis-preparation",
            "job_ms": "whole-job-elapsed",
        },
    }
