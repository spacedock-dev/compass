"""Explicit current-owner terminal withheld publication; no automatic recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import (
    reading,
    reading_long_cleanup,
    reading_long_control,
    reading_long_diagnostics,
    reading_long_inspection,
    reading_long_markers,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig
    from .state import RuntimeState


@dataclass(frozen=True)
class Finalized:
    acknowledged: bool = False
    retired: bool = False
    receipt_released: bool = False


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
        and checked["outcome"] != "pending"
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
