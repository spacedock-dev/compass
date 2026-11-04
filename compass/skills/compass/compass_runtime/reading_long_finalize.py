"""Explicit current-owner terminal outcome publication; no automatic recovery."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import (
    reading,
    reading_final_call,
    reading_long_cleanup,
    reading_long_context,
    reading_long_control,
    reading_long_diagnostics,
    reading_long_inspection,
    reading_long_markers,
    reading_pass_context,
    reading_policy,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from .config import RuntimeConfig
    from .state import RuntimeState


@dataclass(frozen=True)
class Finalized:
    acknowledged: bool = False
    retired: bool = False
    receipt_released: bool = False
    reason: str = ""


def _terminal(config: RuntimeConfig, active: Any) -> dict[str, Any] | None:
    if type(active) is not reading_long_control.Active or type(active.job) is not reading.Job:
        return None
    # The shared marker protocol's ownership validator is used only under its barrier.
    marker = reading_long_markers._owned(config, active.owner)  # noqa: SLF001
    if marker is None or marker["state"] == "active":
        return None
    publication = marker["header"].get("publication")
    key = f"{active.job.harness}:{active.job.sid}"
    if (
        publication is None
        or active.job.id != marker["job_id"]
        or active.job.provider != marker["header"]["provider"]
        or (active.job.harness, active.job.sid) != (publication["harness"], publication["sid"])
        or reading.job(config, key) is not active.job
    ):
        return None
    return marker


def _measurement_matches(
    diagnostic: dict[str, Any] | None,
    marker: dict[str, Any],
    inspected: reading_long_inspection.Inspection,
) -> bool:
    if diagnostic is None:
        return True  # Legacy helper; withheld_measured never permits this case.
    checked = reading_long_diagnostics.validate(diagnostic)
    totals = inspected.exact
    return bool(
        checked is not None
        and totals is not None
        and checked["plan"] == marker["header"]["plan"]
        and checked["accounting"]["state"] == "exact"
        and checked["accounting"]["totals"]
        == {
            "calls": totals.calls,
            "prompt_bytes": totals.prompt_bytes,
            "reply_bytes": totals.reply_bytes,
        }
        and checked["outcome"] in {"withheld", "cancelled", "interrupted"}
    )


def withheld(
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    active: reading_long_control.Active,
    reason: str,
    now: float,
    diagnostic_sink: Callable[[str], None] = print,
    long_diagnostic: dict[str, Any] | None = None,
) -> Finalized:
    """Publish a closed withheld token with exact receipt-derived job spending.

    Hold marker then annotation locks, rereading ownership every time. An old
    context cannot publish after retirement/cleanup. No completed assessment,
    permission authority, owner-death or discard decision is inferred here.
    """
    if not isinstance(reason, str) or reason not in reading.WITHHELD:
        return Finalized()
    acknowledged = False
    try:
        with reading_long_markers.publication_lock(config):
            marker = _terminal(config, active)
            if marker is None:
                return Finalized()
            inspected = reading_long_inspection.inspect(config, marker["job_id"], now=now)
            if inspected.exact is None or not _measurement_matches(
                long_diagnostic, marker, inspected
            ):
                return Finalized()
            publication = marker["header"]["publication"]
            outcome = annotation_store.record_withheld(
                config,
                state,
                publication["harness"],
                publication["sid"],
                reason=reason,
                spent=inspected.exact.calls > 0,
                job_id=marker["job_id"],
                long_target=annotation_store.LongTarget(
                    publication["incarnation"], publication["revision"]
                ),
                long_publication=True,
                long_diagnostic=long_diagnostic,
                diagnostic_sink=diagnostic_sink,
            )
            acknowledged = outcome in (
                annotation_store.OUTCOME_STORED,
                annotation_store.OUTCOME_UNCHANGED,
            )
            # Already under the barrier; public retire() must not reacquire it.
            retired = acknowledged and reading_long_inspection._retire_locked(  # noqa: SLF001
                config, inspected, acknowledged=True, now=now
            )
            if not retired:
                return Finalized(acknowledged=acknowledged)
    except (OSError, ValueError, TypeError):
        return Finalized(acknowledged=acknowledged)
    released = reading_long_cleanup.release_receipt(
        config,
        state,
        job_id=marker["job_id"],
        header=marker["header"],
        diagnostic_sink=diagnostic_sink,
    )
    return Finalized(
        True,
        True,
        released in (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED),
    )


def withheld_measured(
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    active: reading_long_control.Active,
    reason: str,
    now: float,
    long_diagnostic: dict[str, Any] | None,
    diagnostic_sink: Callable[[str], None] = print,
) -> Finalized:
    """Terminal production path: require long metrics before any acknowledgment.

    The legacy withheld helper remains available to older internal callers. New
    measured callers cannot omit metadata or downgrade malformed data to unknown.
    Plan and exact accounting are compared again under the marker barrier.
    """
    checked = reading_long_diagnostics.validate(long_diagnostic)
    if checked is None:
        return Finalized()
    return withheld(
        config,
        state,
        active=active,
        reason=reason,
        now=now,
        long_diagnostic=checked,
        diagnostic_sink=diagnostic_sink,
    )


def _recorded_result(result: reading_final_call.Result, marker: dict[str, Any]) -> bool:
    """The resolved packet and coalesced observations belong to settled receipts."""
    if result.packet is None:
        return False
    prompt = result.packet.prompt.encode("utf-8", errors="strict")
    observations = []
    final = None
    for slot in marker["passes"]:
        if slot["state"] != "settled":
            return False
        observations.append({"observation": slot["observation"], "ended": True})
        if slot["request"]["ordinal"] == marker["header"]["plan"]["max_calls"]:
            final = slot["request"]
    return bool(
        final is not None
        and final["kind"] == "reconciliation"
        and final["prompt_sha256"] == sha256(prompt).hexdigest()
        and final["prompt_bytes"] == len(prompt)
        and observations == list(result.observations)
    )


def _qualified(
    config: RuntimeConfig,
    result: reading_final_call.Result,
    assessment: reading.Assessment,
    frozen: reading_pass_context.Frozen,
    diagnostic: dict[str, Any],
    marker: dict[str, Any],
    inspected: reading_long_inspection.Inspection,
    now: float,
) -> tuple[reading.Assessment, dict[str, Any]] | None:
    """Bind the actual resolved packet and outcome to this frozen registered job."""
    if (
        type(result) is not reading_final_call.Result
        or result.state != "resolved"
        or result.reason != "ok"
        or result.criteria is None
        or result.unresolved
        or result.packet is None
        or type(frozen) is not reading_pass_context.Frozen
        or result.packet.frozen_context != frozen
        or inspected.exact is None
        or inspected.exact.calls <= 0
        or inspected.unsettled
        or not _recorded_result(result, marker)
    ):
        return None
    checked = reading_long_diagnostics.validate(diagnostic)
    kept = annotation_store._assessment(  # noqa: SLF001 - same closed assessment boundary as storage
        deepcopy(assessment), config.annotation_text_cap_chars, config.annotation_goal_cap_chars
    )
    metadata = frozen.value()
    revision, window = metadata["revision"], metadata["window"]
    totals = inspected.exact
    if (
        checked is None
        or kept is None
        or checked["outcome"] != "completed"
        or checked["complete"] is False
        or checked["plan"] != marker["header"]["plan"]
        or checked.get("binding")
        != reading_long_diagnostics.bind_context(frozen, started_at=marker["header"]["started_at"])
        or checked["observations"] != list(result.observations)
        or checked["accounting"]["state"] != "exact"
        or checked["accounting"]["totals"]
        != {
            "calls": totals.calls,
            "prompt_bytes": totals.prompt_bytes,
            "reply_bytes": totals.reply_bytes,
        }
        or kept["criteria"] != result.criteria
        or assessment.get("criteria") != result.criteria
        or kept["revision_read"] != revision["number"]
        or kept["revision_read_at"] != revision["at"]
        or kept["revision_read"] != marker["header"]["publication"]["revision"]
        or kept["window_start"] != window["start"]
        or kept["scope"] != window["scope"]
        or (window["scope"] == reading.SCOPE_FINAL and kept["ended_at_read"] != window["end"])
        or kept["read_at"] != now
    ):
        return None
    return kept, checked


def _locked_intent(entry: annotation_store.Annotation, frozen: reading_pass_context.Frozen) -> bool:
    revision = entry["revisions"][-1]
    metadata = frozen.value()
    if metadata["revision"] != {"number": revision["n"], "at": revision["at"]} or metadata[
        "window"
    ]["start"] != reading.window_start(revision):
        return False
    reading_pass_context.intent(revision.get("goal", ""), reading.outcome_lines(revision), frozen)
    return True


def _write_completed(  # noqa: PLR0913 - one already-locked publication and its validated inputs
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    context: reading_long_context.Context,
    marker: dict[str, Any],
    assessment: reading.Assessment,
    frozen: reading_pass_context.Frozen,
    diagnostic: dict[str, Any],
    on_a_check: frozenset[str],
    source_current: Callable[[], bool],
    diagnostic_sink: Callable[[str], None],
) -> tuple[bool, str]:
    reason = ""

    def guard(entry: annotation_store.Annotation) -> bool:
        nonlocal reason
        reason = reading_long_context.check_publication(config, context)
        if reason:
            return False
        if not _locked_intent(entry, frozen):
            reason = "intent-changed"
            return False
        if source_current() is not True:
            reason = "source-changed"
            return False
        reason = reading_long_context.check_publication(config, context)
        return not reason

    publication = marker["header"]["publication"]
    with reading_policy.long_publication_permission(
        config, context.active.owner.permission
    ) as permission_reason:
        if permission_reason:
            return False, permission_reason
        outcome = annotation_store.record_reading(
            config,
            state,
            publication["harness"],
            publication["sid"],
            assessment=assessment,
            on_a_check=on_a_check,
            job_id=marker["job_id"],
            long_target=annotation_store.LongTarget(
                publication["incarnation"], publication["revision"]
            ),
            long_publication=True,
            long_diagnostic=diagnostic,
            long_publish_guard=guard,
            diagnostic_sink=diagnostic_sink,
        )
    acknowledged = outcome in (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED)
    return acknowledged, "" if acknowledged else (reason or f"annotation-{outcome}")


def completed(  # noqa: PLR0913, PLR0911 - ordered closed publication gates and explicit inputs
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    context: reading_long_context.Context,
    result: reading_final_call.Result,
    assessment: reading.Assessment,
    frozen: reading_pass_context.Frozen,
    long_diagnostic: dict[str, Any],
    source_current: Callable[[], bool],
    now: float,
    on_a_check: Collection[str] = (),
    diagnostic_sink: Callable[[str], None] = print,
) -> Finalized:
    """Publish a qualified completed result, or retire an already-acknowledged one.

    Caller performs expensive source revalidation before this method. source_current
    must be a short read-only stamp/version check: no policy/store writes, model work
    or source scans under marker -> SQL -> annotation locks. The annotation guard
    repeats terminal/intent/source/deadline eligibility after every blocking lock.

    A trusted same-incarnation durable receipt permits cleanup without new authority,
    even after Pause, an intent edit or newer outcomes. No old result is restored.
    No receipt, unreadable state, or generic write refusal is an acknowledgment.
    on_a_check is caller-owned reading.lines_on_a_check output from all frozen
    facts/CI; packet ledger entries are not substituted for those facts.
    """
    acknowledged = False
    try:
        if type(context) is not reading_long_context.Context:
            return Finalized(reason="context-changed")
        with reading_long_markers.publication_lock(config):
            marker = _terminal(config, context.active)
            if marker is None or marker["state"] != "completed":
                return Finalized(reason="context-changed")
            inspected = reading_long_inspection.inspect(config, marker["job_id"], now=now)
            if inspected.exact is None:
                return Finalized(reason="accounting-unknown")
            publication = marker["header"]["publication"]
            acknowledged = annotation_store.long_receipt_acknowledged(
                config,
                state,
                publication["harness"],
                publication["sid"],
                job_id=marker["job_id"],
                incarnation=publication["incarnation"],
                diagnostic_sink=diagnostic_sink,
            )
            if not acknowledged:
                qualified = _qualified(
                    config, result, assessment, frozen, long_diagnostic, marker, inspected, now
                )
                if qualified is None or not callable(source_current):
                    return Finalized(reason="publication-invalid")
                checked_lines = frozenset(on_a_check)
                if not checked_lines.issubset(qualified[0]["criteria"]):
                    return Finalized(reason="publication-invalid")
                acknowledged, reason = _write_completed(
                    config,
                    state,
                    context=context,
                    marker=marker,
                    assessment=qualified[0],
                    frozen=frozen,
                    diagnostic=qualified[1],
                    on_a_check=checked_lines,
                    source_current=source_current,
                    diagnostic_sink=diagnostic_sink,
                )
                if not acknowledged:
                    return Finalized(reason=reason)
            retired = reading_long_inspection._retire_locked(  # noqa: SLF001 - marker barrier held
                config, inspected, acknowledged=True, now=now
            )
            if not retired:
                return Finalized(acknowledged=True, reason="retirement-unresolved")
    except Exception:  # noqa: BLE001 - closed refusal preserves any already-durable acknowledgment
        return Finalized(acknowledged=acknowledged, reason="publication-unavailable")
    released = reading_long_cleanup.release_receipt(
        config,
        state,
        job_id=marker["job_id"],
        header=marker["header"],
        diagnostic_sink=diagnostic_sink,
    )
    complete = released in (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED)
    return Finalized(True, True, complete, "" if complete else "receipt-unresolved")
