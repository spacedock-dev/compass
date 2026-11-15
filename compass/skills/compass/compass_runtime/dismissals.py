"""Dismissals: the sessions the reader has marked handled.

One of the two things Compass writes on the reader's behalf, the other being
the history store (`history`). This one records intent rather than observation,
so it lives outside the per-port state file and outlives the process that wrote
it, and it is bounded by a count where history is bounded by age. See
docs/design-dismissals.md for the keying, the invalidation rule and what a
corrupt or unwritable store does.

A leaf: `config` for the paths and the caps, `records` for the untrusted-input
discipline, `io` for the diagnostic sink. It reads nothing else in the runtime,
which is what lets `aggregate`, `notifications` and `http_api` all consult it.
"""

from __future__ import annotations

import json
import os
import time
from typing import TYPE_CHECKING, Any, TypedDict, cast

from compass_runtime import io as runtime_io
from compass_runtime import records

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState

# The file format version. Read but not enforced: a store written by a newer
# build is still a list of (harness, sid, at, seen_activity) records, and every
# field is re-validated on the way in, so refusing the whole file on an
# unrecognised number would throw away dismissals a downgrade could still honour.
SCHEMA_VERSION = 1

# What a stored key may occupy. Wider than any real session id (Claude publishes
# 8 characters, the longest harness key is 11) and far narrower than the read
# cap, so a hostile file cannot spend its whole budget on one entry.
KEY_CAP_CHARS = 64


class Dismissal(TypedDict):
    """One session the reader marked handled, and when.

    ``seen_activity`` is the watermark: the dismissal holds only while the row's
    ``last_activity`` — the whole subtree, subagents included — stays at or below
    it. It is the *server's* clock at the moment of the dismissal and never a
    value a caller sent, which is why no request can hide a row forever: any
    write after that instant exceeds it.
    """

    harness: str
    sid: str
    at: float
    seen_activity: float


def store_path(config: RuntimeConfig) -> str:
    """Where the dismissals live: beside the state file, but not per port.

    `lifecycle.state_path` is `compass-<port>.json` and is deleted on exit. A
    dismissal is the reader's, not the instance's, so it must survive both a
    restart and a different --port.
    """
    return os.path.join(config.state_home, "compass-dismissals.json")


def is_matchable(harness: str, sid: str) -> bool:
    """Whether (harness, sid) can ever match a published session row.

    Claude Code sessions publish the 8-character transcript prefix as their
    sid, so a 36-character UUID or other non-8-character identifier can never
    match any published Claude row. Admitting an unmatchable key would write a
    permanent junk entry that never expires on activity, consuming one of the
    bounded dismissal slots and eventually evicting a real dismissal (DRC-4179).
    """
    if not harness or not sid:
        return False
    return not (harness == "claude" and len(sid) > 8)


def _entry(value: Any) -> Dismissal | None:
    """One untrusted record as a dismissal, or nothing.

    Same discipline as every other record this product reads: bounded through
    `records.safe_text` because these two strings reach the DOM through
    /api/cleared, and coerced through `records.norm_epoch` so a string or a null
    where a timestamp belongs reads as 0 rather than raising. A 0 watermark is
    the safe direction — it lapses on the session's next write.
    """
    if not isinstance(value, dict):
        return None
    harness = records.safe_text(value.get("harness"), KEY_CAP_CHARS).strip()
    sid = records.safe_text(value.get("sid"), KEY_CAP_CHARS).strip()
    if not is_matchable(harness, sid):
        return None
    return {
        "harness": harness,
        "sid": sid,
        "at": records.norm_epoch(value.get("at")),
        "seen_activity": records.norm_epoch(value.get("seen_activity")),
    }


def _bounded(entries: Iterable[Dismissal], limit: int) -> tuple[Dismissal, ...]:
    """The newest `limit` dismissals, oldest evicted first, in dismissal order.

    A count bound rather than a time-to-live, and that is the whole decision: a
    TTL would re-show a session that never came back and go on hiding one that
    did, which is the failure the invalidation rule exists to avoid. So the file
    is bounded by how many sessions a reader may have marked handled at once, and
    the oldest mark is the one that gives way.
    """
    ordered = sorted(entries, key=lambda entry: entry["at"])
    return tuple(ordered[-limit:]) if limit > 0 else ()


def load(config: RuntimeConfig) -> tuple[Dismissal, ...]:
    """Every dismissal on disk, or none if there is none to trust.

    Read to a cap and with RecursionError caught, for the reason
    `lifecycle.read_state` catches it: deeply nested JSON blows the recursion
    limit rather than raising ValueError, and a corrupt store must degrade to "no
    dismissals" rather than take down a collection. A malformed entry is dropped
    on its own; one bad record does not discard the reader's other marks.
    """
    if not config.dismissals_enabled:
        return ()
    cap = config.dismissal_read_cap_bytes
    try:
        with open(store_path(config), "rb") as handle:
            raw = handle.read(cap + 1)
        if len(raw) > cap:
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
    return _bounded(parsed, config.dismissal_max_entries)


def save(
    config: RuntimeConfig,
    entries: Iterable[Dismissal],
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Write the store, reporting whether it reached disk.

    Temp file plus os.replace, and 0o600 in the `os.open` call rather than a
    chmod afterwards, both copied from `lifecycle.write_state`: a reader mid-write
    sees the old file or the new one, and the file is never briefly
    world-readable. The mode is advisory and Windows ignores it, which SECURITY.md
    records rather than implying isolation.

    False rather than an exception, because the caller's answer to a failed write
    is to say so on the row and carry on with the in-memory list — losing the
    reader's mark at the next restart is survivable, dropping the request is not.
    """
    if not config.dismissals_enabled:
        return False
    payload = {
        "v": SCHEMA_VERSION,
        "entries": [dict(entry) for entry in _bounded(entries, config.dismissal_max_entries)],
    }
    target = store_path(config)
    try:
        runtime_io.atomic_write_owner_only(target, json.dumps(payload), root=str(config.state_home))
    except (OSError, ValueError):
        runtime_io.diag(
            f"Compass: could not write the dismissal store {target}; "
            "cleared sessions will come back at the next restart",
            diagnostic_sink,
        )
        return False
    return True


def refresh(config: RuntimeConfig, state: RuntimeState) -> tuple[Dismissal, ...]:
    """Re-read the store into this process's copy, and return it.

    Called once at the top of a collection, before the harness loop, so the popup
    gate inside a collector and the subtraction after it are answering off the
    same set. Two dashboards can bind on one machine, and the file is the record:
    a mark made in one is picked up by the other on its next collection.
    """
    entries = load(config)
    with state.dismissal_lock:
        state.dismissals = _stored(entries)
    return entries


def _stored(entries: tuple[Dismissal, ...]) -> tuple[dict[str, Any], ...]:
    """The same tuple, spelled the way `state` declares it.

    `state` cannot name `Dismissal`: this module imports `state` and the arrow
    runs one way only. Two casts here are cheaper than a second declaration of
    the shape in a file that owns none of it.
    """
    return cast("tuple[dict[str, Any], ...]", entries)


def active(config: RuntimeConfig, state: RuntimeState) -> tuple[Dismissal, ...]:
    """This process's copy, loading it once if no collection has run yet.

    The hook ingress can fire before the first collection, and an empty list
    there would read as "nothing is cleared" and raise a popup for a session the
    reader had already handled.
    """
    with state.dismissal_lock:
        cached = state.dismissals
    if cached is not None:
        return cast("tuple[Dismissal, ...]", cached)
    return refresh(config, state)


def holds(entries: Iterable[Dismissal], harness: str, sid: str, last_activity: float) -> bool:
    """Whether a dismissal still stands for this row.

    `last_activity` is the whole subtree, not `own_activity`: any movement in the
    tree means the work resumed and the row is news again, and a parked parent
    with a running child is exactly what a dashboard must not hide.
    """
    for entry in entries:
        if entry["harness"] == harness and entry["sid"] == sid:
            return last_activity <= entry["seen_activity"]
    return False


def suppresses(
    config: RuntimeConfig,
    state: RuntimeState,
    harness: str,
    sid: str,
    last_activity: float,
) -> bool:
    """The same question against this process's copy, for the notification path."""
    if not config.dismissals_enabled:
        return False
    return holds(active(config, state), harness, sid, last_activity)


def _key(harness: Any, sid: Any) -> tuple[str, str]:
    return (
        records.safe_text(harness, KEY_CAP_CHARS).strip(),
        records.safe_text(sid, KEY_CAP_CHARS).strip(),
    )


def dismiss(
    config: RuntimeConfig,
    state: RuntimeState,
    harness: Any,
    sid: Any,
    *,
    now: float | None = None,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Mark one session handled. Returns whether the mark reached disk.

    The watermark is `now` — this process's clock — and never anything the caller
    sent. A caller-supplied timestamp is the one input that could hide a row
    forever, because "hide until activity exceeds T" with a large enough T is
    exactly that; a clock the server owns cannot express it.
    """
    if not config.dismissals_enabled:
        return False
    key = _key(harness, sid)
    if not is_matchable(key[0], key[1]):
        return False
    stamp = time.time() if now is None else now
    entry: Dismissal = {
        "harness": key[0],
        "sid": key[1],
        "at": stamp,
        "seen_activity": stamp,
    }
    with state.dismissal_lock:
        # Read from disk under the lock rather than from the cached copy, so a
        # mark made by a second dashboard since this one's last collection is
        # carried forward instead of being written away.
        kept = [e for e in load(config) if (e["harness"], e["sid"]) != key]
        kept.append(entry)
        bounded = _bounded(kept, config.dismissal_max_entries)
        state.dismissals = _stored(bounded)
    return save(config, bounded, diagnostic_sink=diagnostic_sink)


def restore(
    config: RuntimeConfig,
    state: RuntimeState,
    harness: Any,
    sid: Any,
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> bool:
    """Put one session back on the board. Returns whether the store was rewritten."""
    if not config.dismissals_enabled:
        return False
    key = _key(harness, sid)
    if not is_matchable(key[0], key[1]):
        return False
    with state.dismissal_lock:
        bounded = tuple(e for e in load(config) if (e["harness"], e["sid"]) != key)
        state.dismissals = _stored(bounded)
    return save(config, bounded, diagnostic_sink=diagnostic_sink)


def rows(entries: Iterable[Dismissal]) -> list[dict[str, Any]]:
    """The dismissals as the reveal endpoint publishes them, newest first.

    Two identifiers and one timestamp, and nothing else: the store holds no
    title, no prompt and no project, so the reveal cannot leak what the board
    itself was not already showing.
    """
    return [
        {"harness": entry["harness"], "sid": entry["sid"], "at": entry["at"]}
        for entry in sorted(entries, key=lambda entry: entry["at"], reverse=True)
    ]
