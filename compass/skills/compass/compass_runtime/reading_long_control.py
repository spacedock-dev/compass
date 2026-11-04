"""Private registered shells sharing the ordinary requested-reading slot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import reading, reading_long_jobs, reading_long_markers, reading_policy

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
    ui_job = reading.start_job(
        config, session_key, provider=provider, label=label, now=now, prepared_job_id=job.job_id
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
