"""Bounded private evidence passes; no final verdict, source admission or job settlement."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import (
    analyze_diagnostics,
    reading,
    reading_map_call,
    reading_maps,
    reading_pass_context,
    reading_pass_types,
    reading_passes,
    reading_policy,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Sequence

MAX_INDEX_CANDIDATES = 64


@dataclass(frozen=True)
class IndexedCandidate:
    ordinal: int
    candidate: reading_maps.Candidate


@dataclass(frozen=True)
class CandidateIndex:
    entries: tuple[IndexedCandidate, ...] = ()
    unresolved_ordinals: tuple[int, ...] = ()
    overflow: bool = False

    def add(self, ordinal: int, reply: reading_maps.MapReply | None) -> CandidateIndex:
        usable = reply is not None and reply.usable
        candidates = reply.candidates if usable and reply is not None else ()
        overflow = len(self.entries) + len(candidates) > MAX_INDEX_CANDIDATES
        if not usable or overflow:
            return CandidateIndex(
                self.entries, (*self.unresolved_ordinals, ordinal), self.overflow or overflow
            )
        return CandidateIndex(
            (*self.entries, *(IndexedCandidate(ordinal, candidate) for candidate in candidates)),
            self.unresolved_ordinals,
            self.overflow,
        )


@dataclass(frozen=True)
class FinalSlot:
    ordinal: int
    prompt_bytes: int
    reply_bytes: int


@dataclass(frozen=True)
class EvidencePass:
    ordinal: int
    packet: reading_passes.EvidencePacket
    state: str
    reason: str
    snapshots: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class Series:
    reason: str
    plan: reading_passes.PacketPlan
    passes: tuple[EvidencePass, ...]
    index: CandidateIndex
    unassigned_primary: tuple[reading_passes.EvidenceRange, ...]
    failed_primary: tuple[reading_passes.EvidenceRange, ...]
    observations: tuple[dict[str, Any], ...]
    final_slot: FinalSlot
    frozen_context: reading_pass_context.Frozen | None = None


class _Measurements:
    def __init__(self, plan: dict[str, Any], sink: Callable[[dict[str, Any]], bool] | None) -> None:
        self.plan = plan
        self.persistence_failed = False
        self.sink = sink
        self.captures: dict[int, analyze_diagnostics.Capture] = {}
        self.starts: dict[int, float] = {}
        self.snapshots: dict[int, list[dict[str, Any]]] = {}
        self.observations: list[dict[str, Any]] = []

    def observe(self, ordinal: int, diagnostic: dict[str, Any], *, ended: bool = False) -> bool:
        observation = {
            "version": 1,
            "ordinal": ordinal,
            "kind": "evidence",
            "diagnostic": diagnostic,
        }
        if not self.persistence_failed and self.sink is not None:
            try:
                self.persistence_failed = (
                    self.sink(deepcopy({"observation": observation, "ended": ended})) is not True
                )
            except Exception:  # noqa: BLE001 - persistence failure must retain charged evidence
                self.persistence_failed = True
        updated = reading_pass_types.update_observations(
            self.observations,
            observation,
            plan=self.plan,
            ended=ended and not self.persistence_failed,
        )
        if updated is None:
            raise ValueError("Invalid internal evidence observation")
        self.observations = updated
        return not self.persistence_failed

    def prepare(self, ordinal: int, packet: reading_passes.EvidencePacket | None) -> None:
        if packet is None:
            if ordinal in self.captures:
                return
            self.snapshots[ordinal] = []

            def sink(diagnostic: dict[str, Any]) -> None:
                self.snapshots[ordinal].append(deepcopy(diagnostic))
                self.observe(ordinal, diagnostic)

            capture = analyze_diagnostics.Capture(sink)
            self.captures[ordinal] = capture
            self.starts[ordinal] = capture.start()
        else:
            self.captures[ordinal].prepared(
                packet.prompt, packet.selection.diagnostic, self.starts[ordinal]
            )


def _construct_model(
    factory: Callable[[int], Callable[..., tuple[str, str]]], ordinal: int
) -> tuple[Callable[..., tuple[str, str]] | None, str]:
    try:
        return factory(ordinal), ""
    except reading_policy.RefusedError:
        return None, "factory-refused"
    except Exception:  # noqa: BLE001 - construction cannot discard earlier charged passes
        return None, "factory-failed"


def _publish_plan(
    callback: Callable[[reading_passes.PacketPlan], bool] | None,
    packets: reading_passes.PacketPlan,
) -> bool:
    if callback is None:
        return True
    try:
        return callback(deepcopy(packets)) is True
    except Exception:  # noqa: BLE001 - failed plan publication cannot launch calls
        return False


def run(  # noqa: PLR0913 - immutable declaration, original inputs and caller-owned call seams
    originals: Sequence[reading_passes.Original],
    *,
    goal: str,
    lines: Sequence[str],
    clauses: Sequence[str],
    plan: dict[str, Any],
    model_for: Callable[[int], Callable[..., tuple[str, str]]],
    stop_reason: Callable[[], str | None],
    boundary_context: Sequence[str] = (),
    overlap_chars: int = 0,
    boundary_chars: int = 0,
    masked_values: Collection[str] = (),
    scrub_partial: bool = False,
    on_observation: Callable[[dict[str, Any]], bool] | None = None,
    frozen_context: reading_pass_context.Frozen | None = None,
    final: Mapping[str, Any] | None = None,
    on_plan: Callable[[reading_passes.PacketPlan], bool] | None = None,
) -> Series:
    """Plan once, then call each evidence position at most once without automatic resume.

    The frozen declaration reserves one full prompt and reply for its final slot before
    any evidence allocation. Ordinals identify positions, never charges. The factory owns
    per-slot Guard/reservation construction and live quota/deadline enforcement. The stop
    callback supplies cancellation or job-deadline between calls. Preparation occurs once,
    before execution, so later call latency never becomes another packet's build time.
    An observation sink must return True for accepted/staged snapshots. Its ended=True
    event owns per-pass persistence; False or an exception stops further calls while
    preserving charged diagnostics and unresolved ranges. It never seals the whole job.
    on_plan receives the exact completed plan once, before any factory/call. Its explicit
    acceptance is required when supplied; refusal/exception leaves all ranges unassigned.
    """
    declared = reading_pass_types.validate_plan(plan)
    if declared is None or declared["limits"]["reply_bytes"] != reading.REPLY_CAP_BYTES:
        raise ValueError("A frozen long plan with the map reply allocation is required")
    measurements = _Measurements(declared, on_observation)
    measurements.prepare(1, None)
    frozen_lines, frozen_clauses = tuple(lines), tuple(clauses)
    prefix = reading_map_call.protocol_prefix(
        goal, frozen_lines, frozen_clauses
    ) + reading_pass_context.goal_rule(frozen_context)
    limits = declared["limits"]
    final_slot = FinalSlot(declared["max_calls"], limits["prompt_bytes"], limits["reply_bytes"])
    slots = min(
        declared["max_evidence_passes"],
        max(0, limits["output_bytes"] // limits["reply_bytes"] - 1),
    )
    packets = reading_passes.plan_packets(
        originals,
        goal=goal,
        lines=frozen_lines,
        protocol_prefix=prefix,
        max_bytes=limits["prompt_bytes"],
        max_passes=max(1, slots),
        boundary_context=boundary_context,
        overlap_chars=overlap_chars,
        boundary_chars=boundary_chars,
        total_bytes=max(0, limits["input_bytes"] - final_slot.prompt_bytes) if slots else 0,
        on_preparation=measurements.prepare,
        frozen_context=frozen_context,
        final=final,
    )
    index = CandidateIndex()
    passes: list[EvidencePass] = []
    failed: list[reading_passes.EvidenceRange] = []
    reason = packets.reason if slots else "output-limit"
    accepted = _publish_plan(on_plan, packets)
    reason = reason if accepted else "plan-unresolved"
    for ordinal, packet in enumerate(packets.packets if accepted else (), 1):
        if measurements.persistence_failed:
            reason = "persistence-unresolved"
            break
        stopped = stop_reason()
        if stopped is not None:
            if stopped not in {"cancelled", "job-deadline"}:
                raise ValueError("The between-call stop must be cancellation or deadline")
            reason = stopped
            break
        model, factory_failure = _construct_model(model_for, ordinal)
        if model is None:
            reason = factory_failure
            break
        state, outcome, reply = reading_map_call.call_packet(
            packet,
            model=model,
            clauses=frozen_clauses,
            capture=measurements.captures[ordinal],
            masked_values=masked_values,
            scrub_partial=scrub_partial,
        )
        persisted = measurements.observe(ordinal, measurements.captures[ordinal].value, ended=True)
        index = index.add(ordinal, reply if persisted else None)
        if ordinal in index.unresolved_ordinals:
            failed.extend(packet.primary)
        passes.append(
            EvidencePass(ordinal, packet, state, outcome, tuple(measurements.snapshots[ordinal]))
        )
        if not persisted:
            reason = "persistence-unresolved"
            break
    unassigned = (
        *(span for packet in packets.packets[len(passes) :] for span in packet.primary),
        *packets.uncovered_primary,
    )
    if reason == "complete":
        reason = "unresolved" if failed else "passes-ended"
    return Series(
        reason,
        packets,
        tuple(passes),
        index,
        unassigned,
        tuple(failed),
        tuple(measurements.observations),
        final_slot,
        frozen_context,
    )
