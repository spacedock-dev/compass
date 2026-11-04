"""Word-free durable long-job markers; loading never restores execution authority."""

from __future__ import annotations

import contextlib
import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import reading_long_jobs, reading_pass_types, reading_policy, supervise

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from .config import RuntimeConfig

MARKER_DIR = "reading-long-jobs"
MAX_MARKER_BYTES = 131_072
MAX_MARKERS = 128
RETIRE_AFTER_SEC = reading_policy.JOB_LEDGER_SEC
LOCK_WAIT_SEC = 10.0
_LOCK = threading.Lock()
_PROCESS = object()
_TERMINAL = ("completed", "failed", "cancelled", "interrupted")


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


@dataclass(frozen=True)
class MarkerOwner:
    live: reading_long_jobs.LiveJob
    permission: reading_policy.LongPermission
    owner: str
    process: object


@dataclass(frozen=True)
class Permit:
    launch: bool = False
    charged: bool | None = None
    # This invocation committed a fresh charge, even if the subsequent marker
    # write failed. Historical replay's charged=True is not a fresh reservation.
    fresh_charge: bool = False
    reason: str = ""


def marker_path(config: RuntimeConfig, job_id: str) -> Path:
    if not _identifier(job_id):
        raise ValueError("Invalid marker identity")
    return config.state_dir / MARKER_DIR / f"{job_id}.json"


def _moment(value: Any) -> bool:
    return type(value) in (int, float) and 0 < value < 2**53 and math.isfinite(value)


def _slot(value: Any, header: dict[str, Any], job_id: str) -> dict[str, Any] | None:
    if not isinstance(value, dict) or set(value) != {"request", "observation", "state", "charged"}:
        return None
    request = reading_policy.validate_long_request(value["request"], now=header["started_at"])
    observation = reading_pass_types.validate_pass(value["observation"], plan=header["plan"])
    if (
        request is None
        or observation is None
        or not reading_long_jobs.matches(request, header, job_id)
        or (request["ordinal"], request["kind"]) != (observation["ordinal"], observation["kind"])
        or value["state"] not in ("pending", "charged", "settled")
        or (value["charged"] is not None and value["charged"] is not True)
        or (value["state"] == "pending" and value["charged"] is not None)
        or (value["state"] == "charged" and value["charged"] is not True)
    ):
        return None
    return {**value, "request": request, "observation": observation}


def validate(value: Any) -> dict[str, Any] | None:
    """Closed copied metadata, with no liveness, charge-total or authority claim."""
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "version",
            "job_id",
            "header",
            "owner",
            "pid",
            "state",
            "updated_at",
            "terminal_at",
            "passes",
        }
        or type(value["version"]) is not int
        or value["version"] != 1
    ):
        return None
    header = reading_long_jobs.validate_header(value["header"], value["job_id"])
    if (
        header is None
        or not _identifier(value["owner"])
        or type(value["pid"]) is not int
        or not 0 < value["pid"] < 2**31
        or value["state"] not in ("active", *_TERMINAL)
        or not _moment(value["updated_at"])
        or (value["state"] == "active" and value["terminal_at"] is not None)
        or (value["state"] != "active" and not _moment(value["terminal_at"]))
        or not isinstance(value["passes"], list)
        or len(value["passes"]) > header["plan"]["max_calls"]
    ):
        return None
    slots: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw in value["passes"]:
        checked = _slot(raw, header, value["job_id"])
        if checked is None or checked["request"]["ordinal"] in seen:
            return None
        seen.add(checked["request"]["ordinal"])
        slots.append(checked)
    return {**value, "header": header, "passes": slots}


def _read(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or path.parent.is_symlink():
            return None
        with path.open("rb") as handle:
            raw = handle.read(MAX_MARKER_BYTES + 1)
        if len(raw) > MAX_MARKER_BYTES:
            return None
        marker = validate(json.loads(raw))
        return marker if marker is not None and path.name == f"{marker['job_id']}.json" else None
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def load(config: RuntimeConfig, job_id: str) -> dict[str, Any] | None:
    """Read only. None is unavailable/unknown, never zero charges or permission to restart."""
    try:
        return _read(marker_path(config, job_id))
    except ValueError:
        return None


def _sync_directory(path: Path) -> None:
    if hasattr(os, "O_DIRECTORY"):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write(path: Path, marker: dict[str, Any]) -> None:
    checked = validate(marker)
    if checked is None:
        raise ValueError("Invalid marker")
    payload = reading_long_jobs.canonical(checked).encode("utf-8")
    if len(payload) > MAX_MARKER_BYTES:
        raise ValueError("Marker size bound")
    temporary = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # A failed directory sync still withholds execution even after rename.
        _sync_directory(path.parent)
    finally:
        with contextlib.suppress(OSError):
            temporary.unlink()


@contextlib.contextmanager
def _locked(config: RuntimeConfig) -> Iterator[Path]:
    deadline = time.monotonic() + LOCK_WAIT_SEC
    if not _LOCK.acquire(timeout=LOCK_WAIT_SEC):
        raise OSError("Marker writer busy")
    try:
        runtime_io.ensure_owner_dir(str(config.state_dir))
        with runtime_io.held_file_lock(
            config.state_dir / "reading-long-jobs.lock", wait=max(0.0, deadline - time.monotonic())
        ) as held:
            if held != runtime_io.LOCK_HELD:
                raise OSError("Marker lock unavailable")
            root = config.state_dir / MARKER_DIR
            if root.is_symlink():
                raise OSError("Marker directory is a symlink")
            runtime_io.ensure_owner_dir(str(root))
            _sync_directory(config.state_dir)
            yield root
    finally:
        _LOCK.release()


def _room(root: Path, now: float) -> bool:
    paths = []
    with os.scandir(root) as entries:
        for entry in entries:
            paths.append(root / entry.name)
            if len(paths) > MAX_MARKERS:
                return False
    kept = len(paths)
    for path in paths:
        marker = _read(path)
        if (
            marker is not None
            and marker["state"] in _TERMINAL
            and marker["terminal_at"] <= now - RETIRE_AFTER_SEC
            and all(
                slot["state"] == "settled" and slot["charged"] is True for slot in marker["passes"]
            )
        ):
            path.unlink()
            _sync_directory(root)
            kept -= 1
    return kept < MAX_MARKERS


def begin(
    config: RuntimeConfig,
    *,
    permission: reading_policy.LongPermission,
    job: reading_long_jobs.PreparedJob,
    now: float,
) -> MarkerOwner | None:
    header = reading_long_jobs.header(job)
    if header is None or not _moment(now):
        return None
    try:
        with _locked(config) as root:
            path = marker_path(config, job.job_id)
            if path.exists() or not _room(root, now):
                return None
            registered = reading_policy.register_long_job(
                config, permission=permission, job=job, now=now
            )
            if registered.live is None:
                return None
            owner = uuid.uuid4().hex
            marker = {
                "version": 1,
                "job_id": job.job_id,
                "header": header,
                "owner": owner,
                "pid": os.getpid(),
                "state": "active",
                "updated_at": now,
                "terminal_at": None,
                "passes": [],
            }
            _write(path, marker)
            return MarkerOwner(registered.live, permission, owner, _PROCESS)
    except (OSError, ValueError, TypeError, RecursionError):
        return None


def _owned(config: RuntimeConfig, owner: Any) -> dict[str, Any] | None:
    if type(owner) is not MarkerOwner or owner.process is not _PROCESS:
        return None
    header = reading_long_jobs.live_header(owner.live)
    if header is None:
        return None
    marker = load(config, owner.live.prepared.job_id)
    if (
        marker is None
        or marker["owner"] != owner.owner
        or marker["pid"] != os.getpid()
        or reading_long_jobs.canonical(marker["header"]) != owner.live.prepared.binding
    ):
        return None
    return marker


def _request_to_mark(
    marker: dict[str, Any], request: Any, now: float
) -> tuple[dict[str, Any] | None, Permit | None]:
    if marker["state"] != "active":
        return None, Permit(reason="job-sealed")
    checked = reading_policy.validate_long_request(request, now=now)
    if checked is None or not reading_long_jobs.matches(
        checked, marker["header"], marker["job_id"]
    ):
        return None, Permit(reason="invalid-marker-request")
    for slot in marker["passes"]:
        if slot["request"]["ordinal"] == checked["ordinal"]:
            return None, Permit(charged=slot["charged"], reason="pass-already-marked")
    if any(slot["state"] != "settled" for slot in marker["passes"]):
        return None, Permit(reason="pass-unresolved")
    return checked, None


def reserve(config: RuntimeConfig, owner: MarkerOwner, *, request: Any, now: float) -> Permit:
    charged: bool | None = None
    fresh = False
    try:
        with _locked(config):
            marker = _owned(config, owner)
            if marker is None or not _moment(now):
                return Permit(reason="marker-unavailable")
            checked, refusal = _request_to_mark(marker, request, now)
            if checked is None:
                return refusal or Permit(reason="invalid-marker-request")
            observation = {
                "version": 1,
                "ordinal": checked["ordinal"],
                "kind": checked["kind"],
                "diagnostic": None,
            }
            slot: dict[str, Any] = {
                "request": checked,
                "observation": observation,
                "state": "pending",
                "charged": None,
            }
            marker["passes"].append(slot)
            marker["updated_at"] = now
            path = marker_path(config, marker["job_id"])
            _write(path, marker)
            result = reading_policy.reserve_registered_pass(
                config, permission=owner.permission, job=owner.live, request=checked, now=now
            )
            charged, fresh = result.charged, result.launch
            if charged is True:
                slot.update(state="charged", charged=True)
                _write(path, marker)
            if not fresh:
                return Permit(charged=charged, reason=result.status["reason"])
            # The post-charge durability work may block too. Keep a late refusal
            # charged, without granting execution after shutdown or deadline.
            with supervise.admitting() as opened:
                reason = (
                    reading_long_jobs.deadline_reason(
                        owner.live, marker["header"]["plan"]["limits"]["job_ms"]
                    )
                    if opened
                    else "stopping"
                )
            return Permit(not reason, charged, fresh, reason)
    except (OSError, ValueError, TypeError, RecursionError):
        return Permit(charged=charged, fresh_charge=fresh, reason="marker-unwritable")


def _observe(
    config: RuntimeConfig, owner: MarkerOwner, observation: Any, now: float, *, ended: bool
) -> bool:
    try:
        with _locked(config):
            marker = _owned(config, owner)
            if marker is None or marker["state"] != "active" or not _moment(now):
                return False
            checked = reading_pass_types.validate_pass(observation, plan=marker["header"]["plan"])
            if checked is None:
                return False
            slots = marker["passes"]
            if not any(slot["request"]["ordinal"] == checked["ordinal"] for slot in slots):
                return False
            updated = reading_pass_types.update_observations(
                [
                    {"observation": slot["observation"], "ended": slot["state"] == "settled"}
                    for slot in slots
                ],
                checked,
                plan=marker["header"]["plan"],
                ended=ended,
            )
            if updated is None:
                return False
            for slot, item in zip(slots, updated, strict=True):
                slot["observation"] = item["observation"]
                if item["ended"]:
                    slot["state"] = "settled"
            marker["updated_at"] = now
            _write(marker_path(config, marker["job_id"]), marker)
            return True
    except (OSError, ValueError, TypeError, RecursionError):
        return False


def observe(config: RuntimeConfig, owner: MarkerOwner, *, observation: Any, now: float) -> bool:
    return _observe(config, owner, observation, now, ended=False)


def settle(config: RuntimeConfig, owner: MarkerOwner, *, observation: Any, now: float) -> bool:
    """Explicitly end one invocation; this says nothing about successful parsing or coverage."""
    return _observe(config, owner, observation, now, ended=True)


def seal(config: RuntimeConfig, owner: MarkerOwner, *, state: str, now: float) -> bool:
    if state not in _TERMINAL or not _moment(now):
        return False
    try:
        with _locked(config):
            marker = _owned(config, owner)
            if marker is None or marker["state"] != "active":
                return False
            marker.update(state=state, terminal_at=now, updated_at=now)
            _write(marker_path(config, marker["job_id"]), marker)
            return True
    except (OSError, ValueError, TypeError, RecursionError):
        return False
