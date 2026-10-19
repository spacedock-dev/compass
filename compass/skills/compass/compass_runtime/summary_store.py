"""Versioned, bounded summaries independent of saved intent; no model or job ownership."""

from __future__ import annotations

import contextlib
import json
import math
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import records, session_source, session_summary
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .config import RuntimeConfig
    from .state import RuntimeState

SCHEMA_VERSION = 1
_DISPLAY = (str, {"withheld": {True}, "reason": str})
_COVERAGE = {
    "complete": bool,
    "starts_at": (str, None),
    "start_offset": int,
    "end_offset": int,
    "unread": [{"start_offset": int, "end_offset": int, "reason": str, "stream": str}],
    "agent_replies": str,
    "checks_and_files": str,
    "notes": [str],
}
_BULLET = {
    "text": _DISPLAY,
    "kind": {"did", "asked", "said", "failed"},
    "cites": [str],
    "kind_overridden": bool,
    "cut?": bool,
    "cites_cut?": int,
}
_PHASE = {
    "title": _DISPLAY,
    "bullets": [_BULLET],
    "cut?": {"title": bool, "bullets": int},
}
_BLOCK_FIELDS = {
    "first": str,
    "last": str,
    "entries": int,
    "fingerprint": str,
    "cut?": {"phases": int, "reply": bool},
    "withheld_phases?": {"shape_fault": int},
}
_BLOCK = (
    {**_BLOCK_FIELDS, "phases": [_PHASE]},
    {**_BLOCK_FIELDS, "gap": {True}, "reason": str, "see": {"outline"}},
)
_LEDE = (
    {"text": str, "cites": [str], "cut?": bool, "cites_cut?": int},
    {"withheld": {True}, "reason": str, "cites": [str], "cut?": bool, "cites_cut?": int},
    None,
)
_SUMMARY = {
    "state": {"ok", "partial", "refused", "unsupported", "source_changed"},
    "reason": (str, None),
    "harness": str,
    "starts_at": (str, None),
    "lede": _LEDE,
    "lede_reason": (str, None),
    "blocks": [_BLOCK],
    "spend": {"calls": int, "bytes_sent": int, "bytes_back": int, "seconds": float, "retries": int},
    "coverage": (_COVERAGE, None),
    "change": (str, None),
    "affected_blocks": [int],
}
_SOURCE = {
    "stamp": [int],
    "end_offset": int,
    "boundary_digest": str,
    "entries": [[(str, float)]],
    "subjects": [[str]],
    "message_ids": [str],
    "pending": [{"stream": str, "call_id": str, "fact_ids": [str]}],
}
_RECORD = {
    "harness": str,
    "sid": str,
    "summary": _SUMMARY,
    "source": _SOURCE,
    "made_at": float,
    "model_stamp": str,
    "accessed_at": float,
}
# Serialize threads before the OS lock, which may be process-owned on NFS.
_WRITERS: dict[str, threading.Lock] = {}
_WRITERS_LOCK = threading.Lock()


def _primitive(value: Any, shape: type) -> bool:
    if shape is float:
        return type(value) in {int, float} and math.isfinite(value)
    return type(value) is shape and (not isinstance(value, int) or value >= 0)


def _valid(value: Any, shape: Any) -> bool:
    if isinstance(shape, type):
        return _primitive(value, shape)
    if isinstance(shape, tuple):
        return any(_valid(value, choice) for choice in shape)
    if isinstance(shape, set):
        return any(type(value) is type(choice) and value == choice for choice in shape)
    if isinstance(shape, list):
        return isinstance(value, list) and all(_valid(item, shape[0]) for item in value)
    if shape is None:
        return value is None
    required = {key for key in shape if not key.endswith("?")}
    allowed = {key.removesuffix("?") for key in shape}
    return (
        isinstance(value, dict)
        and required <= value.keys() <= allowed
        and all(
            _valid(value[key.removesuffix("?")], spec)
            for key, spec in shape.items()
            if key.removesuffix("?") in value
        )
    )


# Keys, citations and comparison metadata are matched, not read. Redacting one would store a
# record under a key no lookup or delete can find, and a second save would add a duplicate key
# that makes the whole file unavailable, so a credential-shaped identifier refuses the record.
_IDENTIFIERS = frozenset({"harness", "sid", "cites", "first", "last", "fingerprint", "source"})


def _clean(value: Any, key: str = "") -> Any:
    if isinstance(value, str):
        cleaned = records.redact_secrets(value)
        if key in _IDENTIFIERS and cleaned != value:
            raise ValueError("credential-shaped identifier")
        return cleaned
    if isinstance(value, list):
        return [_clean(item, key) for item in value]
    if isinstance(value, dict):
        return {
            name: _clean(item, key if key in _IDENTIFIERS else name) for name, item in value.items()
        }
    return value


def _bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def _display(value: Any, *, cut: bool = False) -> session_summary.Display:
    if isinstance(value, str):
        return session_summary.Display(value, cut=cut)
    return session_summary.Display(reason=value["reason"], cut=cut)


def _decode_summary(value: dict[str, Any]) -> session_summary.Summary:
    blocks = []
    for block in value["blocks"]:
        phases = []
        for phase in block.get("phases", []):
            bullets = tuple(
                session_summary.Bullet(
                    _display(b["text"], cut=b.get("cut", False)),
                    b["kind"],
                    tuple(b["cites"]),
                    b["kind_overridden"],
                    b.get("cites_cut", 0),
                )
                for b in phase["bullets"]
            )
            cut = phase.get("cut", {})
            phases.append(
                session_summary.Phase(
                    _display(phase["title"], cut=cut.get("title", False)),
                    bullets,
                    cut.get("bullets", 0),
                )
            )
        cut = block.get("cut", {})
        blocks.append(
            session_summary.Block(
                block["first"],
                block["last"],
                block["entries"],
                block["fingerprint"],
                tuple(phases),
                block.get("reason"),
                cut.get("phases", 0),
                block.get("withheld_phases", {}).get("shape_fault", 0),
                cut.get("reply", False),
            )
        )
    lede = value["lede"]
    coverage = value["coverage"]
    return session_summary.Summary(
        state=value["state"],
        reason=value["reason"],
        harness=value["harness"],
        starts_at=value["starts_at"],
        lede=session_summary.Lede(
            _display(lede.get("text", lede), cut=lede.get("cut", False)),
            tuple(lede["cites"]),
            lede.get("cites_cut", 0),
        )
        if lede
        else None,
        blocks=tuple(blocks),
        spend=session_summary.Spend(**value["spend"]),
        lede_reason=value["lede_reason"],
        coverage=session_source.SourceCoverage(
            **{key: item for key, item in coverage.items() if key not in {"unread", "notes"}},
            unread=tuple(session_source.UnreadRegion(**item) for item in coverage["unread"]),
            notes=tuple(coverage["notes"]),
        )
        if coverage
        else None,
        change=value["change"],
        affected_blocks=tuple(value["affected_blocks"]),
    )


def _source(snapshot: session_source.SourceSnapshot) -> dict[str, Any]:
    return {
        "stamp": list(snapshot.stamp),
        "end_offset": snapshot.end_offset,
        "boundary_digest": snapshot.boundary_digest,
        "entries": [list(entry) for entry in snapshot.entries],
        "subjects": [[key, *value] for key, value in snapshot.subjects.items()],
        "message_ids": list(snapshot.message_ids),
        "pending": [
            {"stream": call.stream, "call_id": call.call_id, "fact_ids": list(call.fact_ids)}
            for call in snapshot.cursor.pending
        ],
    }


def _decode_source(value: dict[str, Any]) -> session_source.SourceSnapshot:
    a, b, c, d = value["stamp"]
    pending = tuple(
        session_source.PendingCall(
            call["stream"],
            0.0,
            "",
            call["call_id"],
            "",
            "",
            tuple(call["fact_ids"]),
        )
        for call in value["pending"]
    )
    return session_source.SourceSnapshot(
        (a, b, c, d),
        value["end_offset"],
        value["boundary_digest"],
        tuple((key, fp, at) for key, fp, at in value["entries"]),
        {key: (fact_id, result) for key, fact_id, result in value["subjects"]},
        tuple(call.call_id for call in pending),
        session_source.SourceCursor("", (), pending),
        tuple(value["message_ids"]),
    )


@dataclass(frozen=True)
class StoredSummary:
    harness: str
    sid: str
    summary: session_summary.Summary
    snapshot: session_source.SourceSnapshot
    made_at: float
    model_stamp: str
    accessed_at: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "harness": self.harness,
            "sid": self.sid,
            "summary": self.summary.as_dict(),
            "source": _source(self.snapshot),
            "made_at": self.made_at,
            "model_stamp": self.model_stamp,
            "accessed_at": self.accessed_at,
        }


@dataclass(frozen=True)
class Store:
    state: str
    entries: tuple[StoredSummary, ...] = ()


def store_path(config: RuntimeConfig) -> str:
    return os.path.join(config.state_home, config.summary_store_filename)


def _record(value: Any, config: RuntimeConfig) -> StoredSummary:
    if not _valid(value, _RECORD):
        raise ValueError("unknown summary record shape")
    source = value["source"]
    if (
        len(source["stamp"]) != 4
        or any(
            len(e) != 3
            or not isinstance(e[0], str)
            or not isinstance(e[1], str)
            or type(e[2]) not in {int, float}
            for e in source["entries"]
        )
        or any(len(e) != 3 for e in source["subjects"])
        or not 0 < len(value["harness"]) <= config.summary_store_key_cap_chars
        or not 0 < len(value["sid"]) <= config.summary_store_key_cap_chars
        or len(value["model_stamp"]) > config.summary_store_model_stamp_cap_chars
        or value["summary"]["harness"] != value["harness"]
        or len(_bytes(value["summary"])) > config.session_summary_max_bytes
    ):
        raise ValueError("invalid summary metadata")
    return StoredSummary(
        value["harness"],
        value["sid"],
        _decode_summary(value["summary"]),
        _decode_source(source),
        value["made_at"],
        value["model_stamp"],
        value["accessed_at"],
    )


# The board loads the store on every collection. Parsing, validating and redacting up to 64 MiB
# each time would cost more than the board itself, so a whole answer is reused while the file's
# identity, size and mtime are unchanged. A rewrite goes through a rename, which changes the inode.
_LOADED: dict[str, tuple[tuple[int, int, int, int, int], Store]] = {}
_LOADED_LOCK = threading.Lock()


def load(config: RuntimeConfig) -> Store:
    """Read and redact the whole closed schema, or report unavailable without a partial read."""
    path = store_path(config)
    try:
        with open(path, "rb") as handle:
            info = os.fstat(handle.fileno())
            key = (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                config.summary_store_max_bytes,
            )
            with _LOADED_LOCK:
                cached = _LOADED.get(path)
            if cached is not None and cached[0] == key:
                return cached[1]
            store = _parse(handle, config)
    except FileNotFoundError:
        return Store("ok")
    except OSError:
        return Store("unavailable")
    with _LOADED_LOCK:
        _LOADED[path] = (key, store)
    return store


def _parse(handle: Any, config: RuntimeConfig) -> Store:
    try:
        raw = handle.read(max(0, config.summary_store_max_bytes) + 1)
        if len(raw) > config.summary_store_max_bytes:
            return Store("unavailable")
        value = _clean(json.loads(raw))
        if len(_bytes(value)) > config.summary_store_max_bytes or not _valid(
            value,
            {"v": {SCHEMA_VERSION}, "entries": [_RECORD]},
        ):
            return Store("unavailable")
        entries = tuple(_record(item, config) for item in value["entries"])
        keys = {(item.harness, item.sid) for item in entries}
        if len(keys) != len(entries):
            return Store("unavailable")
        return Store("ok", entries)
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        return Store("unavailable")


@contextlib.contextmanager
def _locked(config: RuntimeConfig) -> Iterator[str]:
    """Yield an `io` lock answer; writers refuse anything but `LOCK_HELD`."""
    path = store_path(config)
    with _WRITERS_LOCK:
        writer = _WRITERS.setdefault(path, threading.Lock())
    wait = max(0.0, config.summary_store_lock_wait_sec)
    deadline = time.monotonic() + wait
    if not writer.acquire(timeout=wait):
        yield runtime_io.LOCK_BUSY
        return
    try:
        try:
            os.makedirs(config.state_home, mode=0o700, exist_ok=True)
        except OSError:
            yield runtime_io.LOCK_UNCREATABLE
            return
        with runtime_io.held_file_lock(
            path + ".lock", wait=max(0.0, deadline - time.monotonic())
        ) as held:
            # Refuse unsupported locks too: a reconstructible summary is not worth a lost write.
            yield held
    finally:
        writer.release()


def _write(config: RuntimeConfig, entries: tuple[StoredSummary, ...], keep: tuple[str, str]) -> str:
    ordered = sorted(entries, key=lambda item: max(item.accessed_at, item.made_at))
    while True:
        raw = _bytes({"v": SCHEMA_VERSION, "entries": [_clean(item.as_dict()) for item in ordered]})
        if len(raw) <= config.summary_store_max_bytes:
            break
        victim = next((item for item in ordered if (item.harness, item.sid) != keep), None)
        if victim is None:
            return "refused"
        ordered.remove(victim)
    try:
        runtime_io.atomic_write_owner_only(store_path(config), raw)
    except OSError:
        return "unwritable"
    return "stored"


def put(
    config: RuntimeConfig,
    harness: str,
    sid: str,
    summary: session_summary.Summary,
    snapshot: session_source.SourceSnapshot,
    *,
    made_at: float,
    model_stamp: str,
) -> str:
    """Save a result: stored, refused, unavailable or unwritable."""
    try:
        entry = _record(
            _clean(
                StoredSummary(
                    harness,
                    sid,
                    summary,
                    snapshot,
                    made_at,
                    model_stamp,
                    made_at,
                ).as_dict()
            ),
            config,
        )
    except (ValueError, TypeError, RecursionError, OverflowError):
        return "refused"
    with _locked(config) as held:
        if held != runtime_io.LOCK_HELD:
            return "unwritable"
        store = load(config)
        if store.state != "ok":
            return "unavailable"
        others = tuple(e for e in store.entries if (e.harness, e.sid) != (harness, sid))
        return _write(config, (*others, entry), (harness, sid))


def _find(store: Store, harness: str, sid: str) -> StoredSummary | None:
    return next((e for e in store.entries if (e.harness, e.sid) == (harness, sid)), None)


def get(
    config: RuntimeConfig, harness: str, sid: str, *, now: float | None = None
) -> StoredSummary | None:
    """Read a record, touching it at most once per interval; a failed touch never hides text."""
    entry = _find(load(config), harness, sid)
    at = time.time() if now is None else now
    if (
        entry is None
        or not math.isfinite(at)
        or at - entry.accessed_at < config.summary_store_touch_interval_sec
    ):
        return entry
    with _locked(config) as held:
        store = load(config)
        entry = _find(store, harness, sid)
        # A concurrent read may have touched it while this one waited; one rewrite is enough.
        if (
            entry is not None
            and held == runtime_io.LOCK_HELD
            and at - entry.accessed_at >= config.summary_store_touch_interval_sec
        ):
            entry = replace(entry, accessed_at=max(entry.accessed_at, at))
            others = tuple(e for e in store.entries if (e.harness, e.sid) != (harness, sid))
            _write(config, (*others, entry), (harness, sid))
        return entry


def delete(config: RuntimeConfig, harness: str, sid: str) -> str:
    """Delete one summary independently of annotations and model switches."""
    if not os.path.lexists(store_path(config)):
        return "absent"
    with _locked(config) as held:
        if held != runtime_io.LOCK_HELD:
            return "unwritable"
        store = load(config)
        if store.state != "ok":
            return "unavailable"
        kept = tuple(e for e in store.entries if (e.harness, e.sid) != (harness, sid))
        if len(kept) == len(store.entries):
            return "absent"
        outcome = _write(config, kept, ("", ""))
        return "deleted" if outcome == "stored" else outcome


def forget(config: RuntimeConfig) -> str:
    """Delete even an unreadable store under its writer lock; retain no cached records."""
    # No state home or lock file is made on a machine that never saved a summary.
    if not os.path.lexists(store_path(config)):
        return "absent"
    with _locked(config) as held:
        # Only a live holder can lose a write to this unlink. An unusable lock refuses saves
        # because summaries can be regenerated; it must not keep model-written text on disk.
        if held == runtime_io.LOCK_BUSY:
            return "unwritable"
        try:
            os.unlink(store_path(config))
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "unwritable"
        return "deleted"


def _identity(entry: StoredSummary) -> tuple[Any, ...]:
    return (entry.made_at, entry.model_stamp, tuple(b.fingerprint for b in entry.summary.blocks))


def last_checked(state: RuntimeState, entry: StoredSummary | None) -> dict[str, Any] | None:
    """The last focused report's kind and reason for this record, reading no transcript."""
    if entry is None:
        return None
    with state.summary_freshness_lock:
        cached = state.summary_freshness.get((entry.harness, entry.sid))
    if cached is None or cached[0][1:] != _identity(entry):
        return None
    return {"kind": cached[1]["kind"], "reason": cached[1]["reason"]}


def published(
    entry: StoredSummary | None,
    *,
    available: bool = True,
    checked: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Board metadata only; freshness needs a focused source read, never a transcript per row."""
    return {
        "summary": {
            "exists": entry is not None,
            "state": "ok" if available else "unavailable",
            "coverage": entry.summary.as_dict()["coverage"] if entry else None,
            "made_at": entry.made_at if entry else None,
            "out_of_date": checked if entry is not None else None,
            "job": None,
        }
    }


def _absent(config: RuntimeConfig) -> dict[str, Any]:
    return {
        "state": "absent" if load(config).state == "ok" else "unavailable",
        "exists": False,
        "job": None,
    }


def _report(entry: StoredSummary, page: session_source.SourcePage | None) -> dict[str, Any]:
    report: dict[str, Any] = {"kind": "unavailable", "reason": "source_unavailable", "action": None}
    if page is not None and page.snapshot is not None:
        try:
            change = session_source.compare(entry.snapshot, page)
            if change.kind in {"truncated", "replaced"} or (
                page.coverage is not None and page.coverage.complete
            ):
                report = session_summary.change_report(entry.summary, page.entries, change)
            else:
                report["reason"] = "source_incomplete"
        except ValueError:
            pass
    return report


def _answer(entry: StoredSummary, report: dict[str, Any]) -> dict[str, Any]:
    return {
        **entry.summary.as_dict(),
        "exists": True,
        "made_at": entry.made_at,
        "model_stamp": entry.model_stamp,
        "out_of_date": report,
        "job": None,
    }


def focused(
    config: RuntimeConfig,
    harness: str,
    sid: str,
    page: session_source.SourcePage | None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Serve stored prose and model-free freshness, excluding comparison metadata."""
    entry = get(config, harness, sid, now=now)
    if entry is None:
        return _absent(config)
    return _answer(entry, _report(entry, page))


def for_session(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str
) -> dict[str, Any]:
    """Resolve and read only an opened session, under the source's bounded read allowance."""
    from . import observer  # noqa: PLC0415 (observer and project context share source dependencies)

    entry = get(config, harness, sid)
    if entry is None:
        return _absent(config)
    path = observer.resolve_transcript(config, state, harness, sid)
    if path is None:
        return _answer(entry, _report(entry, None))
    try:
        stamps = session_source.source_stamps(path, harness)
    except OSError:
        return _answer(entry, _report(entry, None))
    # A finished session is opened again and again; its freshness only changes with the
    # transcript or the stored record, so an unchanged pair costs a stat instead of a full read.
    key = (stamps, *_identity(entry))
    with state.summary_freshness_lock:
        cached = state.summary_freshness.get((harness, sid))
    if cached is not None and cached[0] == key:
        return _answer(entry, cached[1])
    page = session_source.read(config, path, harness, sid)
    report = _report(entry, page)
    try:
        unchanged = session_source.source_stamps(path, harness) == stamps
    except OSError:
        unchanged = False
    # A byte-limited read is cached: the same transcript under the same allowance stops at the
    # same place, and a finished long session would pay that read every poll. A time-limited
    # read is not, because a slow disk or a loaded CPU would pin it for the life of the process.
    clipped = page.coverage is not None and any(
        region.reason == "time" for region in page.coverage.unread
    )
    if unchanged and not clipped and report["reason"] != "source_unavailable":
        with state.summary_freshness_lock:
            # The outline's bound: both hold one answer per recently focused session.
            runtime_state.bounded_put(
                state.summary_freshness,
                (harness, sid),
                (key, report),
                limit=config.session_outline_cache_limit,
            )
    return _answer(entry, report)
