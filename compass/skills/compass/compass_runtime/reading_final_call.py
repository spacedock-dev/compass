"""One reserved final invocation over originals; no publication, admission or job settlement."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from . import (
    analyze_diagnostics,
    reading,
    reading_goal_proof,
    reading_map_series,
    reading_pass_context,
    reading_pass_types,
    reading_passes,
    reading_policy,
    reading_reconcile_packet,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from .reading_source_words import MessageWords


@dataclass(frozen=True)
class Inputs:
    """Caller-frozen source scope, in physical order; never a menu or a model assertion.

    Admission/permission and completeness remain caller-owned. All facts (including
    unselected/uncitable evidence) and the actual ToolOutput must survive to resolution.
    The runner copies these inputs before preparing or calling any external seam.
    """

    row: Mapping[str, Any]
    revision: Mapping[str, Any]
    facts: tuple[Mapping[str, Any], ...]
    tool_output: reading.ToolOutput | None
    recovered_sources: tuple[Mapping[str, Any], ...] = ()
    settled_through: float | None = None
    open_call_at: float | None = None
    message_words: tuple[MessageWords, ...] = ()


def _request_data(inputs: Inputs) -> tuple[dict[str, float], frozenset[str], float | None]:
    harness, sid = str(inputs.row["harness"]), str(inputs.row["sid"])
    sources = reading.listed_request_sources(inputs.facts, inputs.recovered_sources)
    floors = reading.line_request_floors(inputs.revision, sources, harness, sid)
    through = (
        max(
            reading.valid_prompt_time(inputs.settled_through) or 0.0,
            reading.valid_prompt_time(inputs.row.get("annotation_settled_through")) or 0.0,
        )
        or None
    )
    uncitable = reading.settled_reader_words(
        inputs.facts,
        harness,
        sid,
        floor=reading._later_direction_floor(inputs.revision),  # noqa: SLF001 - same policy as produce
        settled_through=through,
    )
    return floors, uncitable, through


def _window(inputs: Inputs, scope: str) -> dict[str, Any]:
    kind = reading.end_kind(inputs.row)
    allowed = {
        reading.SCOPE_FINAL: {"session-end"},
        reading.SCOPE_LAST_TURN: {"turn-stop"},
        reading.SCOPE_MID_FLIGHT: {"running", *reading.IDLE_PRESS_KINDS},
    }
    if kind not in allowed.get(scope, set()):
        raise ValueError("Frozen scope differs from observed ending")
    stop = reading.observed_stop(inputs.row)
    return {
        "start": reading.window_start(inputs.revision),
        "end": reading.valid_prompt_time(inputs.row.get("ended_at"))
        if scope == reading.SCOPE_FINAL
        else stop[0]
        if scope == reading.SCOPE_LAST_TURN and stop
        else None,
        "scope": scope,
        "end_kind": kind,
        "open_call_at": inputs.open_call_at
        if scope == reading.SCOPE_MID_FLIGHT and kind == "running"
        else None,
    }


def scope_floor(inputs: Inputs, *, scope: str) -> reading.Selection:
    """The existing producer's full ledger/window and unsent-report guards, without a prompt.

    Source admission and physical Original order are still caller-owned. This derives
    the global safety floor from all frozen facts and the actual press ToolOutput.
    """
    harness, sid = str(inputs.row["harness"]), str(inputs.row["sid"])
    output = inputs.tool_output
    tails = output.tails if output is not None and output.destination else None
    opened = reading.window_start(inputs.revision)
    ledger, _ = reading._ledger_and_superseded(  # noqa: SLF001 - reuse produce's policy unchanged
        list(inputs.facts), harness, sid, tails, output, True, False, opened
    )
    ledger, stopped, _, withheld = reading._ledger_to_read(  # noqa: SLF001
        ledger, inputs.row, scope, opened
    )
    if withheld:
        raise ValueError("Frozen scope has no eligible evidence")
    return reading.Selection(
        ledger,
        record_failed=reading._failed_on_record(  # noqa: SLF001
            () if tails is not None else inputs.facts, harness, sid, opened
        ),
        checks_unsent=reading._has_unsent_reports(  # noqa: SLF001
            inputs.facts, harness, sid, ledger, tails is not None, False
        ),
        unlisted=reading._left_out(  # noqa: SLF001
            output, inputs.facts, ledger, opened, until=stopped
        )
        if output is not None and tails is not None
        else (),
    )


def _require_scope(inputs: Inputs, floor: reading.Selection, scope: str) -> None:
    expected = scope_floor(inputs, scope=scope)
    # Whole-source/final proof is independent of the ledger and never inferred here.
    expected = replace(
        expected,
        newest_final=floor.newest_final,
        agent_words_whole=floor.agent_words_whole,
        goal_whole=floor.goal_whole,
    )
    if reading_pass_context.safety_floor(expected) != reading_pass_context.safety_floor(floor):
        raise ValueError("Frozen safety differs from the complete fact scope")
    if {row["id"] for row in expected.entries} != {row["id"] for row in floor.entries}:
        raise ValueError("Frozen scope omits an eligible original")
    expected_rows = {row["id"]: _metadata(row) for row in expected.entries}
    if any(_metadata(row) != expected_rows[row["id"]] for row in floor.entries):
        raise ValueError("Frozen scope changes original metadata")


def _metadata(row: reading.LedgerEntry) -> dict[str, Any]:
    # Complete admitted message words travel alongside their original canonical row.
    return {key: value for key, value in row.items() if key not in {"agent_words", "reader_words"}}


def _stopped(stop_reason: Callable[[], str | None]) -> str | None:
    stopped = stop_reason()
    if stopped is not None and stopped not in {"cancelled", "job-deadline", "paused"}:
        raise ValueError("Invalid between-call stop")
    return stopped


def _line_sources(revision: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = revision.get("lines")
    values = raw if isinstance(raw, (list, tuple)) else [revision.get("output")]
    rows: list[Mapping[str, Any]] = []
    for value in values:
        row = value if isinstance(value, dict) else {"text": value}
        text = row.get("text")
        if isinstance(text, str) and text.strip():
            rows.append(row)
    return rows[: reading.MAX_OUTCOME_LINES]


def freeze_context(
    inputs: Inputs,
    scope_floor: reading.Selection,
    *,
    scope: str,
    source_complete: bool | None,
    gaps: Sequence[str] = (),
    goal_status: str | None = None,
) -> reading_pass_context.Frozen:
    """Derive request metadata using current reading owners before any map allocation.

    This helper does not grant source access or certify completeness. The caller supplies
    its full-scope Selection and measured coverage. Adopted goals stay unknown by default.
    """
    revision = inputs.revision
    _require_scope(inputs, scope_floor, scope)
    goal, lines = str(revision.get("goal") or ""), reading.outcome_lines(revision)
    floors, uncitable, through = _request_data(inputs)
    source = revision.get("goal_source") or "typed"
    proof = reading_goal_proof.restore(inputs.row, revision, inputs.facts, inputs.message_words)
    raw_lines = _line_sources(revision)
    provenance = [
        {
            "id": reading.outcome_line(index),
            "source": line.get("source") or "typed",
            "source_id": line.get("source_id"),
            "requested_at": floors.get(reading.outcome_line(index)),
        }
        for index, line in enumerate(raw_lines, 1)
    ]
    return reading_pass_context.freeze(
        goal,
        lines,
        {
            "revision": {"number": revision.get("n"), "at": revision.get("at")},
            "provenance": {
                "goal_source": source,
                "goal_source_at": reading.valid_prompt_time(revision.get("goal_source_at")),
                "goal_saved_at": reading.valid_prompt_time(revision.get("goal_saved_at")),
                "goal_status": "whole"
                if proof is not None
                else goal_status or ("typed" if source == "typed" else "unknown"),
                "lines": provenance,
            },
            "window": _window(inputs, scope),
            "settlement": {"through": through, "uncitable": sorted(uncitable)},
            "safety": {
                **reading_pass_context.safety_floor(scope_floor),
                "source_complete": source_complete,
                "gaps": list(gaps),
            },
        },
        goal_proof=proof,
    )


@dataclass(frozen=True)
class Result:
    state: str
    reason: str
    criteria: dict[str, reading.Criterion] | None
    packet: reading_passes.EvidencePacket | None
    unresolved: tuple[str, ...]
    final_state: str | None
    snapshots: tuple[dict[str, Any], ...]
    observations: tuple[dict[str, Any], ...]


class _Measurements:
    def __init__(
        self,
        plan: dict[str, Any],
        prior: Sequence[dict[str, Any]],
        sink: Callable[[dict[str, Any]], bool] | None,
    ) -> None:
        self.plan, self.sink = plan, sink
        self.observations = deepcopy(list(prior))
        self.snapshots: list[dict[str, Any]] = []
        self.failed = False
        self.capture = analyze_diagnostics.Capture(self.publish)

    def observe(self, diagnostic: dict[str, Any], *, ended: bool = False) -> bool:
        observation = {
            "version": 1,
            "ordinal": self.plan["max_calls"],
            "kind": "reconciliation",
            "diagnostic": diagnostic,
        }
        if not self.failed and self.sink is not None:
            try:
                self.failed = (
                    self.sink(deepcopy({"observation": observation, "ended": ended})) is not True
                )
            except Exception:  # noqa: BLE001 - a charged pass must survive failed persistence
                self.failed = True
        updated = reading_pass_types.update_observations(
            self.observations, observation, plan=self.plan, ended=ended and not self.failed
        )
        if updated is None:
            raise ValueError("Invalid final observation sequence")
        self.observations = updated
        return not self.failed

    def publish(self, diagnostic: dict[str, Any]) -> None:
        self.snapshots.append(deepcopy(diagnostic))
        self.observe(diagnostic)


def _bind(
    inputs: Inputs, series: reading_map_series.Series, floor: reading.Selection
) -> dict[str, Any]:
    context = series.frozen_context
    if context is None:
        raise ValueError("Missing frozen context")
    value = context.value()
    expected = freeze_context(
        inputs,
        floor,
        scope=value["window"]["scope"],
        source_complete=value["safety"]["source_complete"],
        gaps=value["safety"]["gaps"],
        goal_status=value["provenance"]["goal_status"],
    )
    if expected != context:
        raise ValueError("Frozen context differs from resolver inputs")
    return value


def _resolve(
    raw: Any,
    packet: reading_passes.EvidencePacket,
    inputs: Inputs,
    context: dict[str, Any],
    detail_cap_chars: int,
    goal_cap_chars: int | None,
) -> tuple[dict[str, reading.Criterion] | None, str]:
    if not isinstance(raw, str):
        return None, "invalid-reply"
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeError:
        return None, "invalid-reply"
    if size > reading.REPLY_CAP_BYTES:
        return None, "oversized-reply"
    selected = packet.selection
    parsed = reading.parse_reply(
        raw,
        reading.constraints_for(selected.lines, claims=selected.asked_claims),
        salvage=size >= reading.REPLY_CAP_BYTES - reading.REPLY_CUT_SLACK_BYTES,
    )
    if not any(row["token"] for row in parsed.values()):
        return None, "invalid-reply"
    floors, uncitable, _ = _request_data(inputs)
    output = inputs.tool_output
    return reading.resolve(
        parsed,
        selected,
        goal=str(inputs.revision.get("goal") or ""),
        lines=selected.lines,
        detail_cap_chars=detail_cap_chars,
        goal_cap_chars=goal_cap_chars,
        window_start=reading.window_start(inputs.revision),
        scope=context["window"]["scope"],
        line_requests=floors,
        uncitable=uncitable,
        recorded=reading.recorded_from(
            inputs.facts, str(inputs.row["harness"]), str(inputs.row["sid"]), tool_output=output
        ),
        open_call_at=context["window"]["open_call_at"],
        masked_values=output.masked_values if output is not None else (),
        scrub_partial=output.masked_values_partial if output is not None else False,
    ), "ok"


def run(  # noqa: C901, PLR0911, PLR0912, PLR0913 - ordered prepare/call/persistence gates
    originals: Sequence[reading_passes.Original],
    series: reading_map_series.Series,
    *,
    inputs: Inputs,
    scope_floor: reading.Selection,
    final: Mapping[str, Any] | None,
    plan: dict[str, Any],
    model_for: Callable[[int], Callable[..., tuple[str, str]]],
    stop_reason: Callable[[], str | None],
    detail_cap_chars: int,
    goal_cap_chars: int | None = None,
    on_observation: Callable[[dict[str, Any]], bool] | None = None,
) -> Result:
    """Build the reserved exact final packet and call once, without publishing an assessment.

    The caller stages pre-reservation observations and durably settles an individual
    pass on ended=True; no event settles the whole job. Gaps return criteria=None even
    for a valid reply, not a fabricated unreadable-model reason or a global verdict.
    """
    declared = reading_pass_types.validate_plan(plan)
    slot = series.final_slot
    if (
        declared is None
        or slot
        != reading_map_series.FinalSlot(
            declared["max_calls"],
            declared["limits"]["prompt_bytes"],
            declared["limits"]["reply_bytes"],
        )
        or slot.reply_bytes != reading.REPLY_CAP_BYTES
    ):
        raise ValueError("Final slot differs from the frozen plan")
    measures = _Measurements(declared, series.observations, on_observation)
    started = measures.capture.start()
    built: reading_reconcile_packet.Reconciliation | None = None

    def result(
        state: str, reason: str, criteria: dict[str, reading.Criterion] | None = None
    ) -> Result:
        return Result(
            state,
            reason,
            criteria,
            built.packet if built else None,
            built.unresolved if built else (reason,),
            built.final_state if built else None,
            tuple(measures.snapshots),
            tuple(measures.observations),
        )

    inputs, originals, scope_floor = deepcopy((inputs, originals, scope_floor))
    try:
        context = _bind(inputs, series, scope_floor)
        if {row["id"] for row in scope_floor.entries} != {o.row["id"] for o in originals}:
            return result("local-unfit", "original-unavailable")
        expected = {row["id"]: _metadata(row) for row in scope_floor.entries}
        if any(_metadata(o.row) != expected[o.row["id"]] for o in originals):
            return result("local-unfit", "invalid-original")
        built = reading_reconcile_packet.build(
            originals,
            series,
            goal=str(inputs.revision.get("goal") or ""),
            lines=reading.outcome_lines(inputs.revision),
            scope=context["window"]["scope"],
            scope_floor=scope_floor,
            final=final,
        )
    except (ValueError, TypeError, KeyError, AttributeError):
        return result("local-unfit", "invalid-context")
    if built.packet is None:
        return result("local-unfit", built.reason)
    packet = built.packet
    measures.capture.prepared(packet.prompt, packet.selection.diagnostic, started)
    if measures.failed:
        return result("persistence-unresolved", "persistence-unresolved")
    if context["provenance"]["goal_source"] != "typed" and not packet.selection.goal_whole:
        # Metadata alone cannot establish complete adopted words or an unclipped /goal.
        gap = (
            "stated-goal-limited"
            if context["provenance"]["goal_source"] == reading.SESSION_GOAL
            else "adopted-goal-unavailable"
        )
        built = replace(built, unresolved=tuple(dict.fromkeys((*built.unresolved, gap))))
        return result("unresolved", gap)
    stopped = _stopped(stop_reason)
    if stopped is not None:
        return result(stopped, stopped)
    model, failure = reading_map_series._construct_model(model_for, slot.ordinal)  # noqa: SLF001
    if model is None:
        return result(failure, failure)
    if (stopped := _stopped(stop_reason)) is not None:
        return result(stopped, stopped)
    refusal = False
    try:
        raw, status = model(packet.prompt, output_cap_bytes=slot.reply_bytes)
    except reading_policy.RefusedError:
        raw, status, refusal = "", "refused", True
    except Exception:  # noqa: BLE001 - no raw transport text or automatic retry
        raw, status = "", "error"
    finally:
        measures.capture.called(model)
    persisted = measures.observe(measures.capture.value, ended=True)
    if not persisted:
        return result("persistence-unresolved", "persistence-unresolved")
    if (stopped := _stopped(stop_reason)) is not None:
        return result(stopped, stopped)
    if refusal:
        return result("refused", "refused")
    if status != "ok":
        return result(
            "model-failed", status if status in analyze_diagnostics.INPUT_OUTCOMES else "error"
        )
    criteria, reason = _resolve(raw, packet, inputs, context, detail_cap_chars, goal_cap_chars)
    if criteria is None:
        return result("parse-failed", reason)
    if built.unresolved:
        return result("unresolved", "coverage-incomplete")
    return result("resolved", "ok", criteria)
