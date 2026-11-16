"""Bounded launcher claims, retained without renewing any child's working deadline."""

from __future__ import annotations

import json
import math
import os
import threading
from typing import TYPE_CHECKING, Any

from . import events
from . import io as runtime_io
from .config import remove_state_file

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig

Key = tuple[str, str]
Claims = dict[Key, tuple[dict[str, str], float]]
MAX_SESSIONS = 512
MAX_BYTES = 256 * 1024
_WRITE_LOCK = threading.Lock()


def store_path(config: RuntimeConfig) -> str:
    return os.path.join(config.state_home, "declared-parents", "claims.json")


def _read(config: RuntimeConfig, now: float) -> Claims:
    try:
        with os.fdopen(
            runtime_io.open_regular(store_path(config), root=str(config.state_home)), "rb"
        ) as handle:
            raw = handle.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {}
    if len(raw) > MAX_BYTES:
        raise ValueError("declaration store exceeds byte cap")
    body = json.loads(raw)
    if (
        not isinstance(body, dict)
        or set(body) != {"v", "claims"}
        or type(body["v"]) is not int
        or body["v"] != 1
    ):
        raise ValueError("unknown declaration schema")
    entries = body["claims"]
    if not isinstance(entries, list) or len(entries) > min(
        MAX_SESSIONS, config.event_overlay_max_sessions
    ):
        raise ValueError("declaration count exceeds cap")
    claims: Claims = {}
    for entry in entries:
        key, parent, at = _entry(entry, now)
        if key in claims:
            raise ValueError("duplicate declaration identity")
        claims[key] = (parent, at)
    return claims


def _entry(entry: Any, now: float) -> tuple[Key, dict[str, str], float]:
    if not isinstance(entry, dict) or set(entry) != {"harness", "sid", "parent", "at"}:
        raise ValueError("invalid declaration record")
    harness, sid, at = entry["harness"], entry["sid"], entry["at"]
    if not isinstance(harness, str) or not isinstance(sid, str):
        raise TypeError("invalid declaration identity")
    normalized = events.normalize_session_id(harness, sid)
    parent = events.parent_declaration(entry["parent"])
    if normalized is None or normalized.lower() != sid or parent is None:
        raise ValueError("invalid declaration identity")
    if (
        isinstance(at, bool)
        or not isinstance(at, (int, float))
        or not 0 < at <= now
        or not math.isfinite(at)
    ):
        raise ValueError("invalid declaration timestamp")
    return (harness, sid), parent, float(at)


def _body(config: RuntimeConfig, claims: Claims) -> str:
    if len(claims) > min(MAX_SESSIONS, config.event_overlay_max_sessions):
        raise ValueError("declaration count exceeds cap")
    body = json.dumps(
        {
            "v": 1,
            "claims": [
                {"harness": h, "sid": sid, "parent": parent, "at": at}
                for (h, sid), (parent, at) in sorted(claims.items())
            ],
        }
    )
    if len(body.encode("utf-8")) > MAX_BYTES:
        raise ValueError("declaration store exceeds byte cap")
    return body


def _unavailable(config: RuntimeConfig, sink: Callable[[str], None]) -> None:
    runtime_io.diag(
        f"Compass: declaration store {store_path(config)} unavailable; "
        "new parent claims are retained only in memory and may be lost on restart.",
        sink,
    )


def load(config: RuntimeConfig, *, now: float, diagnostic_sink: Callable[[str], None]) -> Claims:
    try:
        # Visibility is not known until collection. Age alone must not drop a live coordinator.
        return _read(config, now)
    except (OSError, ValueError, TypeError, RecursionError):
        _unavailable(config, diagnostic_sink)
        return {}


def change(
    config: RuntimeConfig,
    update: Callable[[Claims], None],
    *,
    now: float,
    diagnostic_sink: Callable[[str], None],
    pending: Claims | None = None,
) -> Claims | None:
    """Merge under a stable lock; refuse unknown data instead of replacing it with memory."""
    path = store_path(config)
    try:
        with _WRITE_LOCK:
            runtime_io.ensure_owner_dir(os.path.dirname(path), root=str(config.state_home))
            with runtime_io.held_file_lock(
                os.path.join(os.path.dirname(path), "claims.lock"), wait=0.2
            ) as held:
                if held != runtime_io.LOCK_HELD:
                    raise OSError("declaration lock unavailable")  # noqa: TRY301 - one diagnostic for every persistence refusal
                claims = _read(config, now)
                before = dict(claims)
                for key, value in (pending or {}).items():
                    if key in claims or len(claims) < min(
                        MAX_SESSIONS, config.event_overlay_max_sessions
                    ):
                        claims[key] = value
                update(claims)
                if claims != before:
                    runtime_io.atomic_write_owner_only(
                        path, _body(config, claims), root=str(config.state_home)
                    )
                return claims
    except (OSError, ValueError, TypeError, RecursionError):
        _unavailable(config, diagnostic_sink)
        return None


def record(
    config: RuntimeConfig,
    key: Key,
    parent: dict[str, str] | None,
    *,
    now: float,
    diagnostic_sink: Callable[[str], None],
    pending: Claims | None = None,
) -> Claims | None:
    def update(claims: Claims) -> None:
        existing = claims.get(key)
        if parent is not None:
            if existing is not None or len(claims) < min(
                MAX_SESSIONS, config.event_overlay_max_sessions
            ):
                claims[key] = (dict(parent), now)
        elif existing is not None:
            claims[key] = (existing[0], now)

    return change(config, update, now=now, diagnostic_sink=diagnostic_sink, pending=pending)


def prune(
    config: RuntimeConfig,
    visible: set[Key],
    *,
    now: float,
    diagnostic_sink: Callable[[str], None],
    pending: Claims | None = None,
) -> Claims | None:
    def update(claims: Claims) -> None:
        for key, (_, at) in list(claims.items()):
            if key not in visible and now - at >= config.focus_target_ttl_sec:
                del claims[key]

    return change(config, update, now=now, diagnostic_sink=diagnostic_sink, pending=pending)


def forget(config: RuntimeConfig) -> bool:
    path = store_path(config)
    try:
        with _WRITE_LOCK:
            runtime_io.ensure_owner_dir(os.path.dirname(path), root=str(config.state_home))
            with runtime_io.held_file_lock(
                os.path.join(os.path.dirname(path), "claims.lock"), wait=0.2
            ) as held:
                if held != runtime_io.LOCK_HELD:
                    return False
                try:
                    os.close(runtime_io.open_regular(path, root=str(config.state_home)))
                except FileNotFoundError:
                    return True
                return remove_state_file(path)
    except OSError:
        return False
