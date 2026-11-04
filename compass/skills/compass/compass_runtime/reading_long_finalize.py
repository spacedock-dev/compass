"""Explicit current-owner terminal withheld publication; no automatic recovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import (
    reading,
    reading_long_cleanup,
    reading_long_control,
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


def withheld(
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    active: reading_long_control.Active,
    reason: str,
    now: float,
    diagnostic_sink: Callable[[str], None] = print,
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
            if inspected.exact is None:
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
