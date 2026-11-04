"""Explicit bounded startup recovery; terminal metadata never restores execution authority."""

from __future__ import annotations

import math
import os
import re
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import annotations as annotation_store
from . import reading, reading_long_cleanup, reading_long_diagnostics
from . import reading_long_inspection as inspection
from . import reading_long_markers as markers
from .reading_long_finalize import Finalized

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig
    from .state import RuntimeState


@dataclass(frozen=True)
class Item:
    job_id: str
    owner: str
    inspected: inspection.Inspection
    changed: bool = False
    outcome: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class Recovery:
    items: tuple[Item, ...] = ()
    incomplete: bool = False
    reason: str = ""


def _inventory(config: RuntimeConfig) -> tuple[list[str], bool]:
    root = config.state_dir / markers.MARKER_DIR
    try:
        if not stat.S_ISDIR(root.lstat().st_mode):
            raise OSError("Marker directory unavailable")
    except FileNotFoundError:
        return [], False
    ids: list[str] = []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index == markers.MAX_MARKERS:
                return sorted(ids), True
            if re.fullmatch(r"[0-9a-f]{32}\.json", entry.name):
                ids.append(entry.name[:-5])
    return sorted(ids), False


def _snapshot(config: RuntimeConfig, job_id: str) -> dict[str, Any] | None:
    try:
        details = markers.marker_path(config, job_id).lstat()
        if not stat.S_ISREG(details.st_mode) or details.st_size > markers.MAX_MARKER_BYTES:
            return None
    except OSError:
        return None
    return markers.load(config, job_id)


def _current(config: RuntimeConfig, job_id: str) -> bool:
    return any(job["id"] == job_id for job in reading.published_jobs(config).values())


def _owner(
    pid: int,
    alive: Callable[[int], bool | None],
    process_exists: Callable[[int], bool | None],
    startup_before_jobs: bool,
) -> str:
    if pid == os.getpid():
        return "dead" if startup_before_jobs is True else "unknown"
    try:
        dashboard = alive(pid)
        if dashboard is True:
            return "live"
        # dashboard_alive's False can hide an unreadable state directory.
        # An unrelated live/reused PID is also not verified death.
        return "dead" if dashboard is False and process_exists(pid) is False else "unknown"
    except Exception:  # noqa: BLE001 - an injected probe's failure is never evidence of death
        return "unknown"


def _result(
    config: RuntimeConfig,
    job_id: str,
    now: float,
    *,
    owner: str = "unknown",
    changed: bool = False,
    outcome: str | None = None,
    reason: str = "",
) -> Item:
    inspected = (
        inspection.inspect(config, job_id, now=now)
        if _snapshot(config, job_id) is not None
        else inspection.Inspection(job_id, reason="marker-unavailable")
    )
    return Item(job_id, owner, inspected, changed, outcome, reason)


def _recover_one(  # noqa: PLR0911 - each conservative refusal preserves the current marker
    config: RuntimeConfig,
    job_id: str,
    now: float,
    alive: Callable[[int], bool | None],
    process_exists: Callable[[int], bool | None],
    startup_before_jobs: bool,
) -> Item:
    previous = _snapshot(config, job_id)
    if previous is None:
        return _result(config, job_id, now, reason="marker-unavailable")
    try:
        with markers.publication_lock(config):
            marker = _snapshot(config, job_id)
            if marker is None or marker != previous:
                return _result(config, job_id, now, reason="marker-changed")
            if _current(config, job_id):
                return _result(config, job_id, now, owner="current")
            owner = _owner(marker["pid"], alive, process_exists, startup_before_jobs)
            # Probe work may block. Recheck both snapshots before any mutation.
            if _current(config, job_id):
                return _result(config, job_id, now, owner="current")
            if _snapshot(config, job_id) != marker:
                return _result(config, job_id, now, reason="marker-changed")
            if owner != "dead":
                return _result(config, job_id, now, owner=owner)
            changed = marker["state"] == "active"
            if changed:
                if now < marker["updated_at"]:
                    return _result(config, job_id, now, owner=owner, reason="clock-invalid")
                marker.update(state="interrupted", updated_at=now, terminal_at=now)
                markers._write(markers.marker_path(config, job_id), marker)  # noqa: SLF001 - under publication barrier
            return _result(
                config,
                job_id,
                now,
                owner=owner,
                changed=changed,
                outcome="cancelled" if marker["state"] == "cancelled" else "interrupted",
            )
    except (OSError, ValueError, TypeError, RecursionError):
        return _result(config, job_id, now, reason="marker-unwritable")


def recover(
    config: RuntimeConfig,
    *,
    now: float,
    alive: Callable[[int], bool | None],
    process_exists: Callable[[int], bool | None],
    startup_before_jobs: bool = False,
) -> Recovery:
    """Terminalize only verified dead owners, with no publication, cleanup or launch.

    Call explicitly at startup, never GET/poll. Both probes must return actual
    False for a foreign owner to be dead. Same-PID reuse additionally requires
    the caller's explicit startup-before-jobs assertion; any matching current
    UI job still wins. Results are historical snapshots, not publication claims
    or authority: callers must reread under the marker barrier before acting.
    Unknown/minimum accounting remains present and is never coerced to spent.
    """
    if type(now) not in (int, float) or not 0 < now < 2**53 or not math.isfinite(now):
        return Recovery(incomplete=True, reason="clock-invalid")
    try:
        job_ids, incomplete = _inventory(config)
    except OSError:
        return Recovery(incomplete=True, reason="marker-inventory-unavailable")
    return Recovery(
        tuple(
            _recover_one(config, job_id, now, alive, process_exists, startup_before_jobs)
            for job_id in job_ids
        ),
        incomplete,
        "marker-inventory-bounded" if incomplete else "",
    )


def _publish_withheld(
    config: RuntimeConfig,
    state: RuntimeState,
    marker: dict[str, Any],
    inspected: inspection.Inspection,
    diagnostic_sink: Callable[[str], None],
) -> str:
    """Caller holds the marker barrier and proved death; no execution authority."""
    totals = inspected.exact
    if totals is None:
        return annotation_store.OUTCOME_REFUSED
    publication = marker["header"]["publication"]
    cancelled = marker["state"] == "cancelled"
    diagnostic = reading_long_diagnostics.derive(
        plan=marker["header"]["plan"],
        observations=[
            {"observation": slot["observation"], "ended": slot["state"] == "settled"}
            for slot in marker["passes"]
        ],
        inspected=inspected,
        outcome="cancelled" if cancelled else "interrupted",
    )
    reason = (
        (reading.WITHHELD_CANCELLED if totals.calls else reading.WITHHELD_CANCELLED_UNSENT)
        if cancelled
        else reading.WITHHELD_LONG_INTERRUPTED
    )
    return annotation_store.record_withheld(
        config,
        state,
        publication["harness"],
        publication["sid"],
        reason=reason,
        spent=totals.calls > 0,
        job_id=marker["job_id"],
        long_target=annotation_store.LongTarget(
            publication["incarnation"], publication["revision"]
        ),
        long_publication=True,
        long_diagnostic=diagnostic,
        # A current job that appeared while awaiting the annotation lock wins.
        long_publish_guard=lambda _entry: (
            not _current(config, marker["job_id"]) and _snapshot(config, marker["job_id"]) == marker
        ),
        diagnostic_sink=diagnostic_sink,
    )


def publish_terminal(  # noqa: C901, PLR0911 - independent death proofs and ordered closed refusals
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    job_id: str,
    now: float,
    alive: Callable[[int], bool | None],
    process_exists: Callable[[int], bool | None],
    startup_before_jobs: bool = False,
    diagnostic_sink: Callable[[str], None] = print,
) -> Finalized:
    """Explicitly publish one recovered terminal marker, never resume its job.

    recover() must terminalize active work first. Every attempt re-proves death
    and rereads ownership under the marker barrier; an old Item is not authority.
    Probes must independently prove nonexistence, returning None or raising for
    unexpected process-query failures. No permission capture/fence is needed for
    historical withheld accounting after Pause. Exact receipts alone drive counts.
    """
    if type(now) not in (int, float) or not 0 < now < 2**53 or not math.isfinite(now):
        return Finalized(reason="clock-invalid")
    acknowledged = False
    try:
        previous = _snapshot(config, job_id)
        if previous is None:
            return Finalized(reason="marker-unavailable")
        with markers.publication_lock(config):
            marker = _snapshot(config, job_id)
            if marker is None or marker != previous or marker["state"] == "active":
                return Finalized(reason="marker-changed")
            if _current(config, job_id):
                return Finalized(reason="owner-current")
            owner = _owner(marker["pid"], alive, process_exists, startup_before_jobs)
            if owner != "dead" or _current(config, job_id) or _snapshot(config, job_id) != marker:
                return Finalized(reason="owner-unresolved")
            inspected = inspection.inspect(config, job_id, now=now)
            if inspected.exact is None:
                return Finalized(reason="accounting-unknown")
            publication = marker["header"].get("publication")
            if publication is None:
                return Finalized(reason="publication-unattributed")
            acknowledged = annotation_store.long_receipt_acknowledged(
                config,
                state,
                publication["harness"],
                publication["sid"],
                job_id=job_id,
                incarnation=publication["incarnation"],
                diagnostic_sink=diagnostic_sink,
            )
            if not acknowledged:
                outcome = _publish_withheld(config, state, marker, inspected, diagnostic_sink)
                acknowledged = outcome in (
                    annotation_store.OUTCOME_STORED,
                    annotation_store.OUTCOME_UNCHANGED,
                )
                if not acknowledged:
                    return Finalized(reason=f"annotation-{outcome}")
            if _current(config, job_id) or not inspection._retire_locked(  # noqa: SLF001 - marker barrier held
                config, inspected, acknowledged=True, now=now
            ):
                return Finalized(acknowledged=True, reason="retirement-unresolved")
    except Exception:  # noqa: BLE001 - failure never supplies acknowledgment or execution permission
        return Finalized(acknowledged=acknowledged, reason="publication-unavailable")
    released = reading_long_cleanup.release_receipt(
        config,
        state,
        job_id=job_id,
        header=marker["header"],
        diagnostic_sink=diagnostic_sink,
    )
    complete = released in (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED)
    return Finalized(True, True, complete, "" if complete else "receipt-unresolved")


def discard_terminal(  # noqa: C901, PLR0911 - explicit discard gates, never inferred from refusal
    config: RuntimeConfig,
    state: RuntimeState,
    *,
    job_id: str,
    now: float,
    alive: Callable[[int], bool | None],
    process_exists: Callable[[int], bool | None],
    startup_before_jobs: bool = False,
    diagnostic_sink: Callable[[str], None] = print,
) -> Finalized:
    """Explicitly discard only a verified-dead terminal job's superseded target.

    No outcome or counter is written. Exact historical accounting must remain
    available. Marker -> annotation locks keep positive supersession proof held
    through exact marker retirement. Bare Clear lacks incarnation proof and stays
    unresolved; absence, generic refusal and unknown never authorize retirement.
    """
    if type(now) not in (int, float) or not 0 < now < 2**53 or not math.isfinite(now):
        return Finalized(reason="clock-invalid")
    acknowledged = False
    try:
        previous = _snapshot(config, job_id)
        if previous is None:
            return Finalized(reason="marker-unavailable")
        with markers.publication_lock(config):
            marker = _snapshot(config, job_id)
            if marker is None or marker != previous or marker["state"] == "active":
                return Finalized(reason="marker-changed")
            if _current(config, job_id):
                return Finalized(reason="owner-current")
            owner = _owner(marker["pid"], alive, process_exists, startup_before_jobs)
            if owner != "dead" or _current(config, job_id) or _snapshot(config, job_id) != marker:
                return Finalized(reason="owner-unresolved")
            inspected = inspection.inspect(config, job_id, now=now)
            if inspected.exact is None:
                return Finalized(reason="accounting-unknown")
            publication = marker["header"].get("publication")
            if publication is None:
                return Finalized(reason="publication-unattributed")
            with annotation_store.long_target_invalidated(
                config,
                state,
                publication["harness"],
                publication["sid"],
                target=annotation_store.LongTarget(
                    publication["incarnation"], publication["revision"]
                ),
                diagnostic_sink=diagnostic_sink,
            ) as invalidated:
                if invalidated is not True or _current(config, job_id):
                    return Finalized(reason="discard-unproved")
                acknowledged = True
                if not inspection._retire_locked(  # noqa: SLF001 - both proof and marker barriers held
                    config, inspected, acknowledged=True, now=now
                ):
                    return Finalized(acknowledged=True, reason="retirement-unresolved")
    except Exception:  # noqa: BLE001 - failed proof or retirement never fabricates completion
        return Finalized(acknowledged=acknowledged, reason="discard-unavailable")
    released = reading_long_cleanup.release_receipt(
        config,
        state,
        job_id=job_id,
        header=marker["header"],
        diagnostic_sink=diagnostic_sink,
    )
    complete = released in (annotation_store.OUTCOME_STORED, annotation_store.OUTCOME_UNCHANGED)
    return Finalized(True, True, complete, "" if complete else "receipt-unresolved")
