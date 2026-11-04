"""Private word-free long metrics, separate from the legacy one-invocation envelope.

Source I/O is collector page I/O, retained graph peaks are not RSS, and prompt/reply
allocations are not transmission or provider usage. Observations describe adapter
entry, not execution proof. Only authoritative inspection supplies charge totals.
No integrated final resolver supplies completion proof yet: complete is False for
known gaps/stops and otherwise None. This module cannot certify complete=True.
"""

from __future__ import annotations

import math
from copy import deepcopy
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from . import reading_pass_context, reading_pass_types

if TYPE_CHECKING:
    from .reading_long_inspection import Inspection
    from .reading_map_series import Series
    from .reading_source_collect import Collection
    from .reading_source_inventory import Inventory

MAX_SOURCE_ITEMS = 512
_SOURCE_REASONS = {
    "",
    "inventory",
    "source_bytes",
    "source_pages",
    "retained_bytes",
    "retained_units",
    "time",
    "cancelled",
    "no_progress",
    "source_changed",
    "source_gap",
    "native_incomplete",
    "canonical_limit",
    "message_limit",
}
_MAP_REASONS = {
    "input-limit",
    "context-unfit",
    "prompt-unfit",
    "pass-limit",
    "output-limit",
    "persistence-unresolved",
    "cancelled",
    "job-deadline",
    "factory-refused",
    "factory-failed",
    "unresolved",
    "passes-ended",
}
_GAP_REASONS = {
    "unread",
    "unfinished_line",
    "oversized_line",
    "unreadable_record",
    "source_changed",
}
_INVENTORY_REASONS = {"entries", "streams", "time", "unreadable"}
_USAGE_KEYS = {
    "io_bytes",
    "pages",
    "retained_graph_peak_bytes",
    "retained_graph_peak_units",
    "prepare_ms",
}
_MAP_COUNTS = {
    "planned_passes",
    "planned_primary_ranges",
    "planned_primary_characters",
    "usable_primary_ranges",
    "failed_primary_ranges",
    "unassigned_primary_ranges",
    "planned_prompt_bytes",
    "observed_prompt_bytes",
}


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Invalid long diagnostic metadata")


def _object(value: Any, keys: set[str]) -> None:
    _require(type(value) is dict and value.keys() == keys)


def _count(value: Any, *, nullable: bool = False) -> None:
    _require((nullable and value is None) or (type(value) is int and 0 <= value < 2**53))


def _label(value: Any, labels: set[str], *, nullable: bool = False) -> None:
    _require((nullable and value is None) or (type(value) is str and value in labels))


def _items(value: Any) -> None:
    _require(type(value) is list and len(value) <= MAX_SOURCE_ITEMS)


def _moment(value: Any, *, nullable: bool = False) -> None:
    _require(
        (nullable and value is None)
        or (type(value) in (int, float) and math.isfinite(value) and 0 <= value < 2**53)
    )


def _binding(value: Any) -> None:
    if value is None:
        return
    _object(
        value,
        {
            "revision",
            "revision_at",
            "window_start",
            "window_end",
            "scope",
            "end_kind",
            "open_call_at",
            "job_started_at",
        },
    )
    _count(value["revision"])
    _require(value["revision"] > 0)
    for key in ("revision_at", "window_start", "window_end", "open_call_at", "job_started_at"):
        _moment(value[key], nullable=key in {"window_end", "open_call_at"})
    _require(value["revision_at"] > 0 and value["job_started_at"] > 0)
    _require(value["window_start"] <= value["revision_at"])
    _label(value["scope"], {"final", "last-turn", "mid-flight"})
    _label(
        value["end_kind"], {"session-end", "turn-stop", "running", "unobservable", "idle-unknown"}
    )
    _require(value["window_end"] is None or value["window_end"] >= value["window_start"])
    if value["scope"] != "mid-flight" or value["end_kind"] != "running":
        _require(value["open_call_at"] is None)


def bind_context(context: reading_pass_context.Frozen, *, started_at: float) -> dict[str, Any]:
    """Copy only frozen revision/window scalars, never provenance IDs or user words.

    This projection grants no qualification: a publication owner must separately
    validate the complete Frozen against the locked annotation and resolved packet.
    """
    _require(type(context) is reading_pass_context.Frozen)
    try:
        value = context.value()
        revision, window = value["revision"], value["window"]
        binding = {
            "revision": revision["number"],
            "revision_at": revision["at"],
            "window_start": window["start"],
            "window_end": window["end"],
            "scope": window["scope"],
            "end_kind": window["end_kind"],
            "open_call_at": window["open_call_at"],
            "job_started_at": started_at,
        }
        _binding(binding)
    except (KeyError, TypeError, AttributeError):
        raise ValueError("Invalid diagnostic context binding") from None
    return binding


def _observations(value: Any, plan: dict[str, Any]) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    _require(type(value) is list and len(value) <= plan["max_calls"])
    result: list[dict[str, Any]] = []
    ordinals: set[int] = set()
    for slot in value:
        _object(slot, {"observation", "ended"})
        _require(type(slot["ended"]) is bool)
        checked = reading_pass_types.validate_pass(slot["observation"], plan=plan)
        _require(checked is not None)
        if checked is None:
            raise ValueError("Invalid pass observation")
        _require(checked["ordinal"] not in ordinals)
        ordinals.add(checked["ordinal"])
        result.append({"observation": checked, "ended": slot["ended"]})
    return result


def _source_streams(source: dict[str, Any]) -> None:
    _items(source["streams"])
    _require(len(source["streams"]) + source["streams_omitted"] == source["frozen_streams"])
    for ordinal, stream in enumerate(source["streams"]):
        _object(stream, {"ordinal", "frozen_bytes", "verified_end"})
        _count(stream["ordinal"])
        _require(stream["ordinal"] == ordinal)
        _count(stream["frozen_bytes"])
        _count(stream["verified_end"], nullable=True)
        expected = (
            stream["frozen_bytes"]
            if source["verified_streams"] is not None and ordinal < source["verified_streams"]
            else None
        )
        _require(stream["verified_end"] == expected)
    if not source["streams_omitted"]:
        _require(sum(s["frozen_bytes"] for s in source["streams"]) == source["frozen_bytes"])


def _source_gaps(source: dict[str, Any]) -> None:
    _items(source["gaps"])
    _items(source["inventory_gaps"])
    for gap in source["gaps"]:
        _object(gap, {"stream", "start", "end", "reason", "permanent"})
        for key in ("stream", "start", "end"):
            _count(gap[key])
        _require(gap["stream"] < source["frozen_streams"] and gap["start"] <= gap["end"])
        if gap["stream"] < len(source["streams"]):
            _require(gap["end"] <= source["streams"][gap["stream"]]["frozen_bytes"])
        _label(gap["reason"], _GAP_REASONS)
        _require(type(gap["permanent"]) is bool)
    for reason in source["inventory_gaps"]:
        _label(reason, _INVENTORY_REASONS)
    _require(
        source["unexpanded_extent_unknown"]
        is bool(source["inventory_gaps"] or source["inventory_gaps_omitted"])
    )


def _source(value: Any) -> None:
    if value is None:
        return
    _object(
        value,
        {
            "reason",
            "frozen_streams",
            "frozen_bytes",
            "unexpanded_extent_unknown",
            "streams",
            "streams_omitted",
            "gaps",
            "gaps_omitted",
            "inventory_gaps",
            "inventory_gaps_omitted",
            "usage",
            "source_verified",
            "verified_streams",
            "canonical_fact_count",
            "eligible_entries",
            "retained_whole_message_characters",
            "eligible_message_characters",
        },
    )
    _label(value["reason"], _SOURCE_REASONS, nullable=True)
    for key in (
        "frozen_streams",
        "frozen_bytes",
        "streams_omitted",
        "gaps_omitted",
        "inventory_gaps_omitted",
    ):
        _count(value[key])
    for key in ("verified_streams", "canonical_fact_count", "retained_whole_message_characters"):
        _count(value[key], nullable=True)
    # No current producer establishes the complete eligible canonical/message extent.
    _require(value["eligible_entries"] is None and value["eligible_message_characters"] is None)
    _require(value["source_verified"] is None or type(value["source_verified"]) is bool)
    _require(type(value["unexpanded_extent_unknown"]) is bool)
    if value["verified_streams"] is not None:
        _require(value["verified_streams"] <= value["frozen_streams"])
    if value["usage"] is not None:
        _object(value["usage"], _USAGE_KEYS)
        for count in value["usage"].values():
            _count(count)
    _source_streams(value)
    _source_gaps(value)
    if value["source_verified"] is True:
        _require(value["verified_streams"] == value["frozen_streams"] > 0)
        _require(not (value["gaps"] or value["gaps_omitted"] or value["unexpanded_extent_unknown"]))


def _maps(value: Any, plan: dict[str, Any]) -> None:
    if value is None:
        return
    _object(value, _MAP_COUNTS | {"reason", "candidate_overflow"})
    _label(value["reason"], _MAP_REASONS)
    for key in _MAP_COUNTS:
        _count(value[key], nullable=key == "observed_prompt_bytes")
    _require(type(value["candidate_overflow"]) is bool)
    _require(value["planned_passes"] <= plan["max_evidence_passes"])
    _require(
        value["usable_primary_ranges"] + value["failed_primary_ranges"]
        <= value["planned_primary_ranges"]
    )


def _attempted_job(state: str, totals: dict[str, int] | None) -> int | None:
    if totals is None:
        return None
    return 1 if totals["calls"] > 0 else (0 if state == "exact" else None)


def _accounting(value: Any, plan: dict[str, Any]) -> None:
    _object(value, {"state", "totals", "attempted_job"})
    _label(value["state"], {"unknown", "minimum", "exact"})
    totals = value["totals"]
    if value["state"] == "unknown":
        _require(totals is None)
    else:
        _object(totals, {"calls", "prompt_bytes", "reply_bytes"})
        for count in totals.values():
            _count(count)
        _require(totals["calls"] <= plan["max_calls"])
        _require(totals["prompt_bytes"] <= plan["limits"]["input_bytes"])
        _require(totals["reply_bytes"] <= plan["limits"]["output_bytes"])
        _require(totals["reply_bytes"] == totals["calls"] * plan["limits"]["reply_bytes"])
        if totals["calls"] == 0:
            _require(totals["prompt_bytes"] == totals["reply_bytes"] == 0)
    _count(value["attempted_job"], nullable=True)
    _require(value["attempted_job"] == _attempted_job(value["state"], totals))


def _complete(value: dict[str, Any]) -> bool | None:
    if value["outcome"] not in {"pending", "completed"}:
        return False
    source = value["source"]
    if source is not None and (
        source["reason"]
        or source["unexpanded_extent_unknown"]
        or source["streams_omitted"]
        or source["gaps"]
        or source["gaps_omitted"]
        or source["source_verified"] is False
    ):
        return False
    maps = value["maps"]
    if maps is not None and (
        maps["reason"] != "passes-ended"
        or maps["candidate_overflow"]
        or maps["failed_primary_ranges"]
        or maps["unassigned_primary_ranges"]
    ):
        return False
    return None  # Evidence maps alone do not prove a final conservative resolution.


def validate(value: Any) -> dict[str, Any] | None:
    """Validate the closed v1 long envelope and return independent nested copies."""
    try:
        _object(
            value,
            {
                "version",
                "kind",
                "plan",
                "source",
                "maps",
                "observations",
                "accounting",
                "outcome",
                "complete",
            }
            | ({"binding"} if type(value) is dict and "binding" in value else set()),
        )
        _require(type(value["version"]) is int and value["version"] == 1)
        _require(value["kind"] == "long-analysis")
        plan = reading_pass_types.validate_plan(value["plan"])
        if plan is None:
            return None
        observations = _observations(value["observations"], plan)
        _source(value["source"])
        _maps(value["maps"], plan)
        _accounting(value["accounting"], plan)
        if observations is not None and value["accounting"]["state"] == "exact":
            reserved = sum(
                1
                for slot in observations
                if slot["observation"]["diagnostic"] is not None
                and slot["observation"]["diagnostic"]["input"] is not None
                and slot["observation"]["diagnostic"]["input"]["attempt_reserved"]
            )
            _require(reserved <= value["accounting"]["totals"]["calls"])
        _binding(value.get("binding"))
        _label(value["outcome"], {"pending", "withheld", "cancelled", "interrupted", "completed"})
        _require(value["outcome"] != "completed" or value.get("binding") is not None)
        _require(value["complete"] is _complete(value))
        return {**deepcopy(value), "plan": plan, "observations": observations}
    except (ValueError, TypeError, KeyError):
        return None


def _source_metrics(inventory: Inventory, collected: Collection | None) -> dict[str, Any]:
    verified = collected.verified_streams if collected else None
    gaps = collected.gaps if collected else ()
    inventory_gaps = inventory.gaps
    usage = collected.usage if collected else None
    if usage is not None:
        _require(
            type(usage.prepare_ms) in (int, float)
            and math.isfinite(usage.prepare_ms)
            and usage.prepare_ms >= 0
        )
    return {
        "reason": collected.reason if collected else None,
        "frozen_streams": len(inventory.streams),
        "frozen_bytes": sum(stream.cursor.frozen.end_offset for stream in inventory.streams),
        "unexpanded_extent_unknown": not inventory.complete,
        "streams": [
            {
                "ordinal": i,
                "frozen_bytes": stream.cursor.frozen.end_offset,
                "verified_end": stream.cursor.frozen.end_offset
                if verified is not None and i < verified
                else None,
            }
            for i, stream in enumerate(inventory.streams[:MAX_SOURCE_ITEMS])
        ],
        "streams_omitted": max(0, len(inventory.streams) - MAX_SOURCE_ITEMS),
        "gaps": [
            {
                "stream": item.stream,
                "start": item.gap.start_offset,
                "end": item.gap.end_offset,
                "reason": item.gap.reason,
                "permanent": item.gap.permanent,
            }
            for item in gaps[:MAX_SOURCE_ITEMS]
        ],
        "gaps_omitted": max(0, len(gaps) - MAX_SOURCE_ITEMS),
        "inventory_gaps": [gap.reason for gap in inventory_gaps[:MAX_SOURCE_ITEMS]],
        "inventory_gaps_omitted": max(0, len(inventory_gaps) - MAX_SOURCE_ITEMS),
        "usage": None
        if usage is None
        else {
            "io_bytes": usage.source_bytes,
            "pages": usage.source_pages,
            "retained_graph_peak_bytes": usage.retained_bytes,
            "retained_graph_peak_units": usage.retained_units,
            "prepare_ms": math.ceil(usage.prepare_ms),
        },
        "source_verified": collected.source_verified if collected else None,
        "verified_streams": verified,
        "canonical_fact_count": len(collected.evidence.facts)
        if collected and collected.evidence is not None
        else None,
        "eligible_entries": None,
        "retained_whole_message_characters": sum(
            len(word.words)
            for word in collected.words
            if word.state == "whole" and word.words is not None
        )
        if collected and collected.words is not None
        else None,
        "eligible_message_characters": None,
    }


def _map_metrics(series: Series) -> dict[str, Any]:
    primary = [span for packet in series.plan.packets for span in packet.primary]
    # The producer partitions primary spans. Its covered_characters also includes
    # repeated boundary context, so that field cannot represent unique primary input.
    spans: dict[str, list[tuple[int, int]]] = {}
    for span in primary:
        if span.start is not None and span.end is not None:
            spans.setdefault(span.fact_id, []).append((span.start, span.end))
    for intervals in spans.values():
        intervals.sort()
        _require(all(left[1] <= right[0] for left, right in pairwise(intervals)))
    inputs = [
        slot["observation"]["diagnostic"]["input"]
        if slot["observation"]["diagnostic"] is not None
        else None
        for slot in series.observations
    ]
    failed = set(series.index.unresolved_ordinals)
    return {
        "reason": series.reason,
        "planned_passes": len(series.plan.packets),
        "planned_primary_ranges": len(primary),
        "planned_primary_characters": sum(
            end - start for intervals in spans.values() for start, end in intervals
        ),
        "usable_primary_ranges": sum(
            len(p.packet.primary) for p in series.passes if p.ordinal not in failed
        ),
        "failed_primary_ranges": len(series.failed_primary),
        "unassigned_primary_ranges": len(series.unassigned_primary),
        "planned_prompt_bytes": sum(len(p.prompt.encode("utf-8")) for p in series.plan.packets),
        "observed_prompt_bytes": sum(item["prompt_bytes"] for item in inputs if item is not None)
        if all(item is not None for item in inputs)
        else None,
        "candidate_overflow": series.index.overflow,
    }


def derive(  # noqa: PLR0913 - independent optional producer sections and frozen outcome binding
    *,
    plan: dict[str, Any],
    inventory: Inventory | None = None,
    collection: Collection | None = None,
    series: Series | None = None,
    inspected: Inspection | None = None,
    observations: list[dict[str, Any]] | None = None,
    reconciliation_observations: list[dict[str, Any]] | None = None,
    outcome: str = "pending",
    binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project actual producer metadata; never serialize a producer's words or paths.

    Callers own association of these producer records with the same frozen job. This
    pure helper performs no reads, captures no authority and does not reconcile jobs.
    Eligible canonical counts and partial source frontiers are unavailable today.
    """
    _require(collection is None or inventory is not None)
    _require(series is None or observations is None)
    if series is not None:
        _require(series.final_slot.ordinal == plan.get("max_calls"))
    combined = list(series.observations) if series is not None else observations
    if reconciliation_observations is not None:
        final = _observations(reconciliation_observations, plan)
        _require(final is not None and len(final) <= 1)
        if final is not None:
            _require(all(slot["observation"]["kind"] == "reconciliation" for slot in final))
            combined = [*(combined or ()), *final]
    state = inspected.accounting if inspected else "unknown"
    totals = (inspected.exact or inspected.minimum) if inspected else None
    counted = (
        None
        if totals is None
        else {
            "calls": totals.calls,
            "prompt_bytes": totals.prompt_bytes,
            "reply_bytes": totals.reply_bytes,
        }
    )
    value = {
        "version": 1,
        "kind": "long-analysis",
        "plan": plan,
        "source": _source_metrics(inventory, collection) if inventory is not None else None,
        "maps": _map_metrics(series) if series is not None else None,
        "observations": combined,
        "accounting": {
            "state": state,
            "totals": counted,
            "attempted_job": _attempted_job(state, counted),
        },
        "outcome": outcome,
        **({"binding": binding} if binding is not None else {}),
    }
    value["complete"] = _complete(value)
    checked = validate(value)
    if checked is None:
        raise ValueError("Invalid long diagnostic producer metadata")
    return checked
