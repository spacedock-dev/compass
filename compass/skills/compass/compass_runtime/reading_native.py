"""Pure native preparation and Assessment formatting; no source I/O or model calls."""

from __future__ import annotations

import time
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import (
    copied_corrections,
    reading,
    reading_final_call,
    reading_route,
    records,
)
from . import reading_passes as passes
from .reading_source_collect import PhysicalOrigin, RecordPosition

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .config import RuntimeConfig
    from .project_context import PressChecks
    from .reading_map_series import Series
    from .reading_pass_context import Frozen
    from .reading_source_collect import AncillaryInfo, Collection, Usage


@dataclass(frozen=True)
class Prepared:
    inputs: reading_final_call.Inputs
    originals: tuple[passes.Original, ...]
    floor: reading.Selection
    context: Frozen
    final: Mapping[str, Any] | None
    scope: str
    stopped: float | None
    left_out: Mapping[str, int]
    uncut: tuple[reading.LedgerEntry, ...]
    superseded: int
    usage: Usage
    ancillary: AncillaryInfo
    ci_read: str


@dataclass(frozen=True)
class Preparation:
    prepared: Prepared | None
    reason: str
    elapsed_ms: float


def _output(press: PressChecks, route: Mapping[str, Any]) -> reading.ToolOutput:
    destination = route["destination"]
    return reading.ToolOutput(
        destination=destination,
        label=route["label"],
        tails=reading_route.tails_for(
            route["provider"], route["harness"], press.tails, press.tier3_calls
        )
        if destination
        else {},
        changed_after=press.changed_after if destination else frozenset(),
        read_incomplete=press.read_incomplete if destination else frozenset(),
        passes_and_writes=press.passes_and_writes if destination else (),
        removals=press.removals,
        masked_values=press.masked_values,
        masked_values_partial=press.masked_values_partial,
        quotable=press.quotable,
    )


def _origin_order(
    facts: Sequence[Mapping[str, Any]],
    scoped: set[tuple[str, float]],
    origins: tuple[PhysicalOrigin, ...] | None,
) -> list[tuple[str, float]]:
    if origins is None or len(origins) != len(facts):
        raise ValueError("original-order-unavailable")
    positioned = []
    for index, fact in enumerate(facts):
        key = (fact["fact_id"], fact["at"])
        if key not in scoped:
            continue  # Unknown placement outside this eligible scope is irrelevant.
        origin = origins[index]
        if (
            type(origin) is not PhysicalOrigin
            or type(origin.canonical_index) is not int
            or origin.canonical_index != index
            or origin.fact_id != key[0]
            or origin.reason
            or type(origin.position) is not RecordPosition
        ):
            raise ValueError("original-order-unavailable")
        position = origin.position
        if (
            any(type(v) is not int or v < 0 for v in vars(position).values())
            or position.end_offset <= position.start_offset
        ):
            raise ValueError("original-order-unavailable")
        positioned.append(((position.stream, position.start_offset, index), key))
    return [key for _, key in sorted(positioned)]


def _ordered(
    inputs: reading_final_call.Inputs,
    floor: reading.Selection,
    origins: tuple[PhysicalOrigin, ...] | None,
    final: Mapping[str, Any] | None,
) -> tuple[passes.Original, ...]:
    rows = {(row["id"], row["at"]): row for row in floor.entries}
    order = _origin_order(inputs.facts, set(rows), origins)
    words = {}
    for admitted in inputs.message_words:
        key = (admitted.fact_id, admitted.at)
        if key in words:
            raise ValueError("message-words-unavailable")
        words[key] = admitted
    originals = []
    for key in order:
        row = rows.get(key)
        if row is None:
            continue
        message = row["type"] in {"user_message", reading.AGENT_MESSAGE_TYPE}
        word = words.get(key)
        if message and (
            word is None
            or word.state != "whole"
            or not word.words
            or word.total != len(word.words)
            or word.type != row["type"]
            or (word.harness, word.sid) != (inputs.row["harness"], inputs.row["sid"])
        ):
            raise ValueError("message-words-unavailable")
        state = None
        if final is not None and row["id"] == final.get("fact_id"):
            state = "whole" if final.get("outcome") == "whole" else "unfit"
        originals.append(passes.Original(row, word.words if message and word else None, state))
    if len(originals) != len(rows):
        raise ValueError("original-order-unavailable")
    return tuple(originals)


def prepare(  # noqa: C901, PLR0911, PLR0913 - ordered preparation refusals before any calls
    config: RuntimeConfig,
    row: Mapping[str, Any],
    revisions: Sequence[Mapping[str, Any]],
    collection: Collection,
    route: Mapping[str, Any],
    *,
    now: float,
    discarded: bool = False,
    settled_through: float | None = None,
    open_call_at: float | None = None,
    recovered_sources: Sequence[Mapping[str, Any]] = (),
) -> Preparation:
    """Prepare retained source data only; the caller owns grants and source revalidation.

    No route resolution, source acquisition, CI read, reservation or transport occurs.
    Physical order comes only from the collection's exact indexed origins. Unknown
    placement on an eligible original refuses; out-of-window origins are not required.
    elapsed_ms measures this preparation separately from the collection's metered usage.
    recovered_sources is existing owner-proved request lineage; absent proof stays unknown.
    Its acquisition/metering belongs to the caller, never a hidden reread here.
    Physical verification alone is not semantic or model completeness. In particular an
    enabled CI read with an unknown/available binding remains an explicit context gap.
    """
    started = time.perf_counter()

    def finish(reason: str, prepared: Prepared | None = None) -> Preparation:
        return Preparation(prepared, reason, (time.perf_counter() - started) * 1000)

    goal, _lines, scope, withheld = reading._readable(  # noqa: SLF001 - existing policy owner
        config,
        row,
        revisions,
        now=now,
        discarded=discarded,
        read_lines=True,
        admit_turn_stop=True,
        admit_idle=True,
    )
    if withheld:
        return finish(withheld)
    if (
        collection.evidence is None
        or collection.reason
        or not collection.source_verified
        or collection.gaps
        or collection.inventory_gaps
        or collection.unavailable_streams
        or collection.words is None
    ):
        return finish("source-incomplete")
    if (
        route.get("harness") != row.get("harness")
        or route.get("provider") not in {"claude", "codex"}
        or any(not isinstance(route.get(key), str) for key in ("destination", "label"))
        or route.get("ci_read") not in {"on", "off", "flag-off"}
    ):
        return finish("invalid-route")
    if collection.final is None or collection.final.get("outcome") not in {
        "whole",
        "none",
        "not-final",
        "too-long",
    }:
        return finish("final-unavailable")
    if collection.final.get("outcome") == "too-long":
        return finish("final-unfit")
    frozen_row, revision = deepcopy((dict(row), dict(revisions[-1])))
    facts = deepcopy(list(collection.evidence.facts))
    facts = copied_corrections.mark({"semantic": {"facts": facts}}, [frozen_row])["semantic"][
        "facts"
    ]
    output = deepcopy(_output(collection.evidence.press, route))
    inputs = reading_final_call.Inputs(
        frozen_row,
        revision,
        tuple(facts),
        output,
        recovered_sources=tuple(deepcopy(recovered_sources)),
        settled_through=settled_through,
        open_call_at=open_call_at,
        message_words=deepcopy(collection.words),
    )
    uncut, superseded = reading._ledger_and_superseded(  # noqa: SLF001
        facts,
        str(row["harness"]),
        str(row["sid"]),
        output.tails if output.destination else None,
        output,
        True,
        False,
        reading.window_start(revision),
    )
    _, stopped, left_out, withheld = reading._ledger_to_read(  # noqa: SLF001
        uncut, row, scope, reading.window_start(revision)
    )
    if withheld:
        return finish(withheld)
    try:
        floor = reading_final_call.scope_floor(inputs, scope=scope)
        originals = _ordered(inputs, floor, collection.origins, collection.final)
        passes._strict_final(originals, collection.final)  # noqa: SLF001 - same proof binding as maps
        gaps = (
            ("context",)
            if route["ci_read"] == "on"
            and collection.ancillary_info.ci_binding in {"available", "unknown", "disabled"}
            else ()
        )
        context = reading_final_call.freeze_context(
            inputs, floor, scope=scope, source_complete=True, gaps=gaps
        )
    except (ValueError, TypeError, KeyError) as error:
        reason = str(error)
        return finish(
            reason
            if reason in {"original-order-unavailable", "message-words-unavailable"}
            else "invalid-context"
        )
    if revision.get("goal_source", "typed") != "typed" and context.goal_proof is None:
        return finish(
            "stated-goal-limited"
            if revision.get("goal_source") == reading.SESSION_GOAL
            else "adopted-goal-unavailable"
        )
    if goal != str(revision.get("goal") or ""):
        return finish("invalid-context")
    return finish(
        "",
        Prepared(
            inputs,
            originals,
            floor,
            context,
            deepcopy(collection.final),
            scope,
            stopped,
            left_out,
            uncut,
            superseded,
            collection.usage,
            collection.ancillary_info,
            route["ci_read"],
        ),
    )


def assessment(
    prepared: Prepared,
    series: Series,
    result: reading_final_call.Result,
    *,
    now: float,
    stamp_text: str,
) -> reading.Assessment | None:
    """Format the actual resolved fresh-menu result; never replay or publish a reading."""
    packet, criteria = result.packet, result.criteria
    resolved = result.state == "resolved" and result.reason == "ok" and not result.unresolved
    partial = (
        result.state == "partial"
        and result.reason == "final-context-partial"
        and set(result.unresolved) == {"agent-words-partial"}
    )
    if (
        packet is None
        or criteria is None
        or not (resolved or partial)
        or packet.frozen_context != prepared.context
        or series.frozen_context != prepared.context
        or series.failed_primary
        or series.unassigned_primary
        or series.index.overflow
        or series.index.unresolved_ordinals
        or (
            partial
            and reading_final_call._qualified_partial(criteria, packet.selection) != criteria  # noqa: SLF001
        )
    ):
        return None
    inputs, selected = prepared.inputs, packet.selection
    revision, row, facts, output = inputs.revision, inputs.row, inputs.facts, inputs.tool_output
    if output is None:
        return None
    harness, sid = str(row["harness"]), str(row["sid"])
    if any(
        cite not in {entry["id"] for entry in selected.entries}
        for criterion in criteria.values()
        for cite in criterion["cites"]
    ):
        return None
    coverage = {
        "tail_truncated": False,
        "tail_start": None,
        "unlisted": len(selected.unlisted),
        "unread_checks": len(selected.unread_checks),
        "goal_source": prepared.context.value()["provenance"]["goal_status"],
    }
    cutoff = (
        f"Native source: {prepared.usage.source_bytes} bytes read from verified streams. "
        f"Evidence prompts: {sum(p.state == 'mapped' for p in series.passes)} usable "
        f"of {len(series.plan.packets)} planned packets. "
        "Final original packet: "
        + reading.cutoff_text(
            selected.entries,
            len(prepared.floor.entries),
            now,
            **prepared.left_out,
            coverage=coverage,
            window_start=reading.window_start(revision),
        )
    )
    if partial:
        cutoff += (
            " Some already-mapped agent text did not fit this final packet; "
            "only original-supported local departures are retained."
        )
    cutoff += "" if reading.outcome_lines(revision) else reading.NO_OUTCOME_LINES_NOTE
    cutoff += reading._FINAL_NOTES.get(selected.newest_final or "", "")  # noqa: SLF001
    cutoff += reading._unsent_checks_note(  # noqa: SLF001
        output,
        facts,
        harness,
        sid,
        bool(output.destination),
        False,
        sent_failure=any(r["type"] == reading.TOOL_REPORT_TYPE for r in prepared.floor.entries),
        superseded=prepared.superseded,
        outside_window=reading._failures_left_out(prepared.uncut, prepared.floor.entries),  # noqa: SLF001
    )
    cutoff += (
        " Pull-request CI was not read (disabled)."
        if prepared.ci_read != "on"
        else " Pull-request CI was not read; no independent CI result is included."
    )
    value: reading.Assessment = {
        "revision_read": revision["n"],
        "revision_read_at": records.norm_epoch(revision.get("at")) or None,
        "window_start": reading.window_start(revision) or None,
        "read_at": now,
        "stamp": stamp_text,
        "cutoff": cutoff,
        "scope": prepared.scope,
        "scope_text": reading._scope_text(prepared.scope, row),  # noqa: SLF001
        "ended_at_read": records.norm_epoch(row.get("ended_at")) or None,
        "evidence_through": reading._newest(facts, harness, sid, until=prepared.stopped),  # noqa: SLF001
        "criteria": deepcopy(criteria),
        "coverage": coverage,
    }
    if revision.get("goal_source") in reading.PROMPT_SOURCES:
        value["goal_source"] = str(revision["goal_source"])
        value["goal_source_at"] = reading.baseline_at(revision)
    reading._attach_verdict_check(value, row, facts, output)  # noqa: SLF001
    return value
