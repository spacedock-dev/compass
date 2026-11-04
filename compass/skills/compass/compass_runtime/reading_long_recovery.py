"""Explicit bounded startup recovery; terminal metadata never restores execution authority."""

from __future__ import annotations

import math
import os
import re
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import reading
from . import reading_long_inspection as inspection
from . import reading_long_markers as markers

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig


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
