"""The session ends this board observed, kept so a restart does not forget them.

DRC-4547. The end mark is set by the very `session_ended` event that pops a
session's overlay ledger, so it was held on the coordinator outside that ledger
and nowhere else. Measured 2026-09-11: three Claude sessions published
`session end observed` on a board that had been up while they ran; the board
was restarted and the same three came back as `went quiet, no end observed`,
with no way to recover the distinction. The end is the one fact
[DEC-15](docs/design-reading-a-session.md#dec-15-the-floor-and-the-overlay)
requires before a reading may call itself final, so on a restarted board no
final reading could be taken on any session that finished before the restart.

Not the history store, for the reason `deliveries` also declined it: its
contract writes only what the board already publishes, and by the time a cold
row is read there is no `ended_at` on it to write. Not the whole overlay
either. An overlay is a live reduction meant to be rebuilt; what has to survive
is one value per session id, with when.

A leaf shaped on `departures`, with its read-modify-write lock:
`config` for the path and caps, `records` for the untrusted-input discipline,
`io` for private atomic publication and the diagnostic sink. It reads nothing
else in the runtime, which is what lets `observation` write it and `aggregate`
read it without an edge between those two inverting.

## What may be said, and what may not

A record is an end THIS BOARD observed, on the event the harness sent. Absence
is NOT OBSERVED and never "did not end": a session that ended while no board
was running, a harness with no event adapter and a run under `--no-events`
all leave the same nothing here, exactly as they do in the coordinator's
memory. Nothing in this module infers an end from anything but a stored one.

The coordinator is the only writer. `--diagnose` builds no coordinator and so
never writes; `--no-events` builds none either, and the collection then reads
nothing back (decisions.md, DRC-4547: Option A), so that flag switches this
store off in both directions the way it already switches off focus. `--forget`
deletes the file, because a durable end is exactly the class of thing that
command removes: the machine's memory of what it observed.
"""

from __future__ import annotations

import json
import os
import threading
from typing import TYPE_CHECKING, Any, Final, TypedDict

from compass_runtime.config import (
    remove_state_file,
)

from . import io as runtime_io
from . import records

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from .config import RuntimeConfig

SCHEMA_VERSION: Final = 1
STORE_FILENAME: Final = "compass-ends.json"

KEY_CAP_CHARS: Final = 200

# Held across the read-modify-write in `record` and `lift`. `deliveries`
# shipped without one and lost a record in 60 of 60 two-writer trials; two
# sessions ending together reach this from two handler threads, which is the
# ordinary case rather than a stress test.
_WRITE_LOCK: Final = threading.Lock()


class End(TypedDict):
    """One observed session end: which id, and when the harness said so."""

    harness: str
    sid: str
    at: float


def store_path(config: RuntimeConfig) -> str:
    """Beside the state file, and not per port, for `deliveries.store_path`'s reason."""
    return os.path.join(config.state_home, STORE_FILENAME)


def _entry(value: Any) -> End | None:
    """One untrusted record, or nothing.

    A stamp that is missing, zero, negative or not a number drops the record:
    0.0 is the coordinator's own spelling of NOT OBSERVED, so a stored zero
    must never be restored as an end.
    """
    if not isinstance(value, dict):
        return None
    harness = records.safe_text(value.get("harness"), KEY_CAP_CHARS)
    sid = records.safe_text(value.get("sid"), KEY_CAP_CHARS)
    at = records.norm_epoch(value.get("at"))
    if not harness or not sid or at <= 0:
        return None
    return {"harness": harness, "sid": sid, "at": at}


def _bounded(entries: Iterable[End], limit: int) -> tuple[End, ...]:
    """One record per session id, latest stamp winning, newest `limit` kept.

    `max` rather than last-writer for `observation._mark_ended`'s reason:
    delivery is at-least-once and possibly reordered, so a redelivered older end
    must not pull the stamp backwards on disk any more than in memory.
    """
    latest: dict[tuple[str, str], End] = {}
    for entry in entries:
        key = (entry["harness"], entry["sid"])
        held = latest.get(key)
        if held is None or entry["at"] > held["at"]:
            latest[key] = entry
    ordered = sorted(latest.values(), key=lambda entry: entry["at"])
    return tuple(ordered[-limit:]) if limit > 0 else ()


def load(config: RuntimeConfig) -> tuple[End, ...]:
    """Every end on disk, or none if there is none to trust.

    A missing, corrupt, truncated or over-cap file is no ends, never an error:
    every row then reads exactly as it did before this store existed.
    """
    try:
        with open(store_path(config), "rb") as handle:
            raw = handle.read(config.end_read_cap_bytes + 1)
        if len(raw) > config.end_read_cap_bytes:
            return ()
        data = json.loads(raw or b"null")
    except (OSError, ValueError, RecursionError):
        return ()
    if not isinstance(data, dict):
        return ()
    entries = data.get("entries")
    if not isinstance(entries, list):
        return ()
    parsed = [entry for entry in (_entry(value) for value in entries) if entry is not None]
    return _bounded(parsed, config.end_max_entries)


def save(
    config: RuntimeConfig,
    entries: Iterable[End],
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Write the store, reporting whether it reached disk."""
    payload = {
        "v": SCHEMA_VERSION,
        "entries": [dict(entry) for entry in _bounded(entries, config.end_max_entries)],
    }
    target = store_path(config)
    try:
        runtime_io.atomic_write_owner_only(target, json.dumps(payload), root=str(config.state_home))
    except (OSError, ValueError, TypeError, RecursionError):
        runtime_io.diag(
            f"Compass: could not write the session-end record {runtime_io.value(target)}; "
            "a session that ended will read as merely quiet after the next restart",
            diagnostic_sink,
        )
        return False
    return True


def record(
    config: RuntimeConfig,
    *,
    harness: str,
    sid: str,
    at: float,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Keep one observed end, and say whether it reached disk."""
    fresh = _entry({"harness": harness, "sid": sid, "at": at})
    if fresh is None:
        return False
    with _WRITE_LOCK:
        return save(config, [*load(config), fresh], diagnostic_sink=diagnostic_sink)


def lift(
    config: RuntimeConfig,
    *,
    harness: str,
    sid: str,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Forget a stored end once its session id is seen in use again.

    True when a record was removed. A lift for an id with no record writes
    nothing and creates nothing: `session_started` fires for every session
    there is, and the file must not come into being on the sessions that never
    ended.
    """
    with _WRITE_LOCK:
        held = load(config)
        kept = [entry for entry in held if (entry["harness"], entry["sid"]) != (harness, sid)]
        if len(kept) == len(held):
            return False
        return save(config, kept, diagnostic_sink=diagnostic_sink)


def restored(entries: Iterable[End]) -> dict[tuple[str, str], float]:
    """The stored ends by session key, as `aggregate` reads them back onto rows."""
    return {(entry["harness"], entry["sid"]): entry["at"] for entry in entries}


def forget(config: RuntimeConfig) -> bool:
    """Delete the store. True when a file was removed."""
    return remove_state_file(store_path(config))
