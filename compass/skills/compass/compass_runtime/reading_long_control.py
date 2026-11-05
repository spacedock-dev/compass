"""Private registered shells sharing the ordinary requested-reading slot."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import (
    reading,
    reading_long_inspection,
    reading_long_jobs,
    reading_long_markers,
    reading_policy,
)

if TYPE_CHECKING:
    from .config import RuntimeConfig


@dataclass(frozen=True)
class Active:
    job: reading.Job
    owner: reading_long_markers.MarkerOwner


def admit(
    config: RuntimeConfig,
    session_key: str,
    *,
    provider: str,
    label: str,
    job: reading_long_jobs.PreparedJob,
    permission: reading_policy.LongPermission,
    now: float,
) -> Active | None:
    """Claim the slot and freshly register; return no context on refusal.

    The caller owns scope, intent and destination validation before preparing
    this job and before future passes. This shell establishes none of those
    claims and permits no source read or model call. Each pass still needs its
    own fresh marker permit. Reads cannot reconstruct an Active context.
    """
    header = reading_long_jobs.header(job)
    if (
        header is None
        or header["provider"] != provider
        or type(permission) is not reading_policy.LongPermission
        or (header["lineage"], header["epoch"]) != (permission.lineage, permission.epoch)
    ):
        return None
    publication = header.get("publication")
    if publication is not None and session_key != f"{publication['harness']}:{publication['sid']}":
        return None
    ui_job = reading._start_long_job(  # noqa: SLF001 - only long admission sets long mode
        config,
        session_key,
        provider=provider,
        label=label,
        now=now,
        prepared_job_id=job.job_id,
        plan=header["plan"],
    )
    if ui_job is None:
        return None
    owner = None
    try:
        owner = reading_long_markers.begin(config, permission=permission, job=job, now=now)
        return Active(ui_job, owner) if owner is not None else None
    finally:
        if owner is None:
            reading.end_job(config, session_key, expected_job=ui_job)


def publish_progress(
    config: RuntimeConfig,
    active: Active,
    value: Any,
    *,
    inspected: reading_long_inspection.Inspection | None = None,
) -> bool:
    """Publish caller measurements and receipt accounting without reading any store.

    The caller supplies a fresh authoritative inspection when available; an
    absent inspection remains unknown. The private header digest binds known
    totals to this immutable job header;
    snapshot/header hashes never enter progress. This is association checking,
    not a claim that arbitrary Python objects cannot be forged. Neither this
    mutation nor its reads grant authority.
    """
    if type(active) is not Active or not isinstance(value, dict):
        return False
    header = reading_long_jobs.header(active.owner.live.prepared)
    identity = active.owner.live.prepared.job_id
    if (
        header is None
        or identity != active.job.id
        or header["provider"] != active.job.provider
        or (
            inspected is not None
            and (
                type(inspected) is not reading_long_inspection.Inspection
                or inspected.job_id != identity
            )
        )
    ):
        return False
    totals = (inspected.exact or inspected.minimum) if inspected is not None else None
    if inspected is not None and (
        (totals is not None and inspected.header_sha256 != reading_long_jobs.digest(header))
        or (inspected.exact is not None and inspected.snapshot is None)
        or (
            inspected.snapshot is not None
            and (
                not isinstance(inspected.snapshot, str)
                or re.fullmatch(r"[0-9a-f]{64}", inspected.snapshot) is None
            )
        )
    ):
        return False
    accounting = {
        "state": inspected.accounting if inspected is not None else "unknown",
        "totals": {
            "calls": totals.calls,
            "prompt_bytes": totals.prompt_bytes,
            "reply_bytes": totals.reply_bytes,
        }
        if totals is not None
        else None,
    }
    return reading.update_long_progress(
        config,
        f"{active.job.harness}:{active.job.sid}",
        active.job,
        {**value, "accounting": accounting},
        job_id=identity,
        plan=header["plan"],
    )
