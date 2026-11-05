"""Caller-held, bounded forward evidence for one session; no store or model.

Fact ids are identities, never display positions. Cursors and snapshots are server-only Python
values, including unfinished line fragments and the minimal inputs of unresolved tool calls.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import stat
import time
from bisect import bisect_right
from dataclasses import asdict, dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import observer, project_scripts, record_pages, records, transcripts
from . import project_context as context

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from typing import BinaryIO

    from .config import RuntimeConfig


Stamp = tuple[int, int, int, int]
HARNESSES = record_pages.HARNESSES
_CODEX_NOTES = ("codex_agent_words_not_admitted", "codex_checks_and_files_not_admitted")


@dataclass(frozen=True)
class SourceEntry:
    """One masked fact; `words` is complete admitted text for a producer, never for HTTP."""

    fact_id: str
    fingerprint: str
    kind: str
    actor: str
    stream: str
    at: float
    title: str
    result: str | None = None
    path: str | None = None
    folder: str | None = None
    subject: str | None = None
    words: str | None = None


@dataclass(frozen=True)
class UnreadRegion:
    """Byte offsets are local to `stream`; no timestamp is invented for missing bytes."""

    start_offset: int
    end_offset: int
    reason: str
    stream: str = "parent"


@dataclass(frozen=True)
class SourceCoverage:
    complete: bool
    starts_at: str | None
    start_offset: int
    end_offset: int
    unread: tuple[UnreadRegion, ...]
    agent_replies: str
    checks_and_files: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingCall:
    """Only classifier inputs, excluding write contents, held to pair a later result."""

    stream: str
    at: float
    cwd: str
    call_id: str
    name: str
    input_json: str
    fact_ids: tuple[str, ...] = ()
    # Physical line offset and call order within that line, even before a fact is emitted.
    position: tuple[int, int] = (-1, 0)
    # The latest physical input/rewrite row, distinct from the original call's ordering position.
    input_offset: int = -1


@dataclass(frozen=True)
class _LineHash:
    # Copy on every extension keeps the caller's cursor unchanged without retaining skipped bytes.
    state: Any = field(default_factory=hashlib.sha256, repr=False, compare=False)

    def add(self, raw: bytes) -> _LineHash:
        state = self.state.copy()
        state.update(raw)
        return _LineHash(state)

    def digest(self) -> str:
        return str(self.state.hexdigest())


@dataclass(frozen=True)
class StreamCursor:
    """A forward frontier and last whole-line boundary in one owned transcript."""

    stream: str
    stamp: Stamp
    offset: int = 0
    end_offset: int = 0
    boundary_start: int = 0
    boundary_digest: str = ""
    fragment: bytes = b""
    skipping: bool = False
    line_start: int = 0
    line_hash: _LineHash = field(default_factory=_LineHash)


@dataclass(frozen=True)
class SourceCursor:
    """Bind all stream frontiers to a transcript/harness/session identity. Not a wire cursor."""

    identity: str
    streams: tuple[StreamCursor, ...]
    pending: tuple[PendingCall, ...] = ()
    session_dir: str = ""
    seen: tuple[tuple[str, str, float], ...] = ()
    subjects: tuple[tuple[str, str, str], ...] = ()
    message_ids: tuple[str, ...] = ()
    # The names of the files a listing depends on that an earlier page saw the session write. A
    # page holds only its own rows, and no work tree byte comparison covers a listing.
    listing_writes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class SourceSnapshot:
    """Metadata a caller keeps; `cursor` permits another read even at the current end."""

    stamp: Stamp
    end_offset: int
    boundary_digest: str
    entries: tuple[tuple[str, str, float], ...]
    subjects: Mapping[str, tuple[str, str]]
    pending_calls: tuple[str, ...]
    cursor: SourceCursor
    message_ids: tuple[str, ...] = ()
    boundaries: tuple[tuple[int, str], ...] = ()
    verified_boundary: tuple[int, str] | None = None
    result_calls: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SourcePage:
    state: str
    harness: str
    sid: str
    entries: tuple[SourceEntry, ...] = ()
    coverage: SourceCoverage | None = None
    next: SourceCursor | None = None
    snapshot: SourceSnapshot | None = None
    notes: tuple[str, ...] = ()
    bytes_read: int = 0
    # An unresolved call can be renamed or retracted by a later result/hook rewrite.
    replacements: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = ()
    # Fact id -> (physical line offset, call order, fact order); server-only, not identity.
    positions: tuple[tuple[str, tuple[int, int, int]], ...] = ()
    # Latest actual input/result row supporting each fact; offsets are local to its stream.
    observations: tuple[tuple[str, int], ...] = ()
    # Aligned with replacements, including a removal that emits no new fact.
    replacement_observations: tuple[int, ...] = ()
    # Ordinary physical observations stay at zero; isolated dependency replay pages advance it.
    classification_revision: int = 0
    # Opt-in summary observation: canonical body fallback when the bounded head has no field.
    head_fallback: tuple[str | None, float | None] = (None, None)


@dataclass(frozen=True)
class SourceChange:
    kind: str
    changed: tuple[tuple[str, str], ...] = ()
    appended: tuple[str, ...] = ()


@dataclass(frozen=True)
class _OutlineLine:
    start: int
    end: int
    digest: str


@dataclass(frozen=True)
class _OutlineCall:
    call_id: str
    line: _OutlineLine
    rewrite: _OutlineLine | None
    position: tuple[int, int]
    fact_ids: tuple[str, ...]
    result: _OutlineLine | None = None
    revision: int = 0


@dataclass(frozen=True)
class _OutlineFrontier:
    offset: int
    end_offset: int
    boundary_start: int
    boundary_digest: str
    line_start: int
    line_hash: _LineHash = field(default_factory=_LineHash)
    discarding: bool = False


@dataclass(frozen=True)
class OutlineCheckpoint:
    """Bounded stream locators and child inventory, without classifier inputs or generic cursors.

    A caller must keep its transient source page separate from retained outline state.
    """

    identity: str
    stamp: Stamp
    calls: tuple[_OutlineCall, ...]
    frontier: _OutlineFrontier | None = None
    gaps: tuple[UnreadRegion, ...] = ()
    head: tuple[str, float | None] = ("", None)
    listing_writes: tuple[str, ...] = ()
    stopped: bool = False
    head_unknown: bool = False
    accepted: tuple[tuple[int, int], ...] = ()
    stream: str = "parent"
    children: tuple[tuple[str, OutlineCheckpoint], ...] = ()
    inventory: tuple[tuple[str, Stamp | None], ...] = ()
    next_stream: int = 0
    withdrawals: tuple[str, ...] = ()
    dependencies: tuple[_OutlineCall, ...] = ()
    replay: tuple[tuple[str, str], ...] = ()
    classification_revision: int = 0
    dependency_limited: bool = False

    @property
    def parent_complete(self) -> bool:
        return (
            self.frontier is not None
            and self.frontier.end_offset == self.stamp[2]
            and not self.gaps
        )

    @property
    def complete(self) -> bool:
        return (
            not self.replay
            and not self.dependency_limited
            and self.parent_complete
            and all(child.parent_complete for _, child in self.children)
        )

    @property
    def done(self) -> bool:
        return self.dependency_limited or (
            not self.replay
            and all(
                current.stopped
                or (current.frontier is not None and current.frontier.offset == current.stamp[2])
                for current in (self, *(child for _, child in self.children))
            )
        )


_OUTLINE_PENDING_LIMIT = 256
_OUTLINE_CHECKPOINT_BYTES = 8 * 1024 * 1024
_OUTLINE_STREAM_LIMIT = 128
_OUTLINE_INVENTORY_ENTRIES = 4096
_OUTLINE_DEPENDENCY_LIMIT = 4096
_OUTLINE_WITHDRAWAL_LIMIT = 512


def _outline_call_offset(call: _OutlineCall) -> int:
    return max(line.start for line in (call.line, call.rewrite, call.result) if line is not None)


def _outline_merge_dependencies(
    previous: tuple[_OutlineCall, ...],
    incoming: tuple[_OutlineCall, ...],
) -> tuple[_OutlineCall, ...]:
    merged = {call.call_id: call for call in previous}
    for call in incoming:
        old = merged.get(call.call_id)
        if old is None or _outline_call_offset(call) >= _outline_call_offset(old):
            merged[call.call_id] = replace(
                call,
                fact_ids=tuple(dict.fromkeys((*(old.fact_ids if old else ()), *call.fact_ids))),
                revision=max(call.revision, old.revision if old else 0),
            )
    if len(merged) > _OUTLINE_DEPENDENCY_LIMIT:
        raise ValueError("outline_dependency_limit")
    return tuple(merged.values())


def _outline_locator(read: _StreamRead, row: int) -> _OutlineLine:
    start = read.row_cursors[row].line_start
    ends = [end for end, _digest in read.boundaries]
    end, digest = read.boundaries[bisect_right(ends, start)]
    return _OutlineLine(start, end, digest)


def _outline_dependencies(
    read: _StreamRead, after: OutlineCheckpoint | None
) -> tuple[_OutlineCall, ...]:
    positions, _results, rewrites = _rows_of(read.rows, read.cursor.stream != "parent")
    result_rows = {
        call_id: index
        for index, row in enumerate(read.rows)
        for call_id in context._tool_result_blocks([row], sidechain=read.cursor.stream != "parent")  # noqa: SLF001
    }
    previous = {call.call_id: call for call in (*after.calls, *after.dependencies)} if after else {}
    incoming = []
    for call in read.dependency_calls:
        old = previous.get(call.call_id)
        row = positions.get(call.call_id)
        line = _outline_locator(read, row) if row is not None else old.line if old else None
        if line is None:
            raise _SourceChangedError
        rewrite, result = rewrites.get(call.call_id), result_rows.get(call.call_id)
        incoming.append(
            _OutlineCall(
                call.call_id,
                line,
                _outline_locator(read, rewrite)
                if rewrite is not None
                else old.rewrite
                if old
                else None,
                call.position,
                call.fact_ids,
                _outline_locator(read, result)
                if result is not None
                else old.result
                if old
                else None,
                old.revision if old else 0,
            )
        )
    return _outline_merge_dependencies(after.dependencies if after else (), tuple(incoming))


def _outline_checkpoint(
    path: str,
    harness: str,
    sid: str,
    read: _StreamRead,
    pending: tuple[PendingCall, ...],
    after: OutlineCheckpoint | None = None,
) -> OutlineCheckpoint:
    """Discard raw pending inputs while the canonical parser's line boundaries are available."""
    identity = record_pages._identity(path, harness, sid)  # noqa: SLF001
    if (
        after
        and (
            after.identity != identity
            or after.stamp != read.cursor.stamp
            or after.stream != read.cursor.stream
        )
    ) or (
        harness == "codex"
        and (
            pending or (after and (after.calls or after.head != ("", None) or after.listing_writes))
        )
    ):
        raise _SourceChangedError
    if len(pending) > _OUTLINE_PENDING_LIMIT:
        raise ValueError("outline_state_limit")
    if harness == "codex":
        return OutlineCheckpoint(identity, read.cursor.stamp, ())
    calls = {call.call_id: call for call in after.calls} if after else {}
    for call_id in read.result_calls:
        calls.pop(call_id, None)
    previous = {call.call_id: call for call in after.calls} if after else {}
    positions, _results, rewrites = _rows_of(read.rows, read.cursor.stream != "parent")
    for call in pending:
        if call.stream != read.cursor.stream:
            raise _SourceChangedError
        old = previous.get(call.call_id)
        row = positions.get(call.call_id)
        line = _outline_locator(read, row) if row is not None else old.line if old else None
        if line is None:
            raise _SourceChangedError
        rewrite = rewrites.get(call.call_id)
        calls[call.call_id] = _OutlineCall(
            call.call_id,
            line,
            _outline_locator(read, rewrite)
            if rewrite is not None
            else old.rewrite
            if old
            else None,
            call.position,
            call.fact_ids,
        )
    if len(calls) > _OUTLINE_PENDING_LIMIT:
        raise ValueError("outline_state_limit")
    checkpoint = OutlineCheckpoint(
        identity,
        read.cursor.stamp,
        tuple(calls.values()),
        stream=read.cursor.stream,
        dependencies=_outline_dependencies(read, after),
        withdrawals=tuple(sorted(read.withdrawals)),
    )
    _outline_bound(checkpoint)
    return checkpoint


def _outline_metadata(checkpoint: OutlineCheckpoint) -> dict[str, Any]:
    # Hash state is fixed-size and opaque. Never deepcopy/serialize a hashlib object or raw input.
    frontier = checkpoint.frontier
    metadata = asdict(replace(checkpoint, frontier=None, children=()))
    if frontier is not None:
        metadata["frontier"] = {
            "offset": frontier.offset,
            "end_offset": frontier.end_offset,
            "boundary_start": frontier.boundary_start,
            "boundary_digest": frontier.boundary_digest,
            "line_start": frontier.line_start,
            "line_hash": frontier.line_hash.digest(),
            "discarding": frontier.discarding,
        }
    return metadata


def _outline_bound(checkpoint: OutlineCheckpoint) -> None:
    if len(checkpoint.children) + 1 > _OUTLINE_STREAM_LIMIT:
        raise ValueError("outline_stream_limit")
    size = len(json.dumps(_outline_metadata(checkpoint)).encode("utf-8"))
    for path, child in checkpoint.children:
        if child.children or child.inventory:
            raise ValueError("outline_state_limit")
        size += len(json.dumps((path, _outline_metadata(child))).encode("utf-8")) + 2
        if size > _OUTLINE_CHECKPOINT_BYTES:
            raise ValueError("outline_state_limit")
    if size > _OUTLINE_CHECKPOINT_BYTES:
        raise ValueError("outline_state_limit")


def _outline_pending(
    path: str,
    harness: str,
    sid: str,
    checkpoint: OutlineCheckpoint,
    read: _StreamRead,
    budget: _Budget,
) -> tuple[PendingCall, ...] | None:
    """Rehydrate only calls touched by these rows; None means the shared budget cannot fit them.

    Budget exhaustion is retryable, not a permanent input gap. The future row-admission caller
    must reserve room or defer the triggering row, and must not classify it with missing input.
    """
    if (
        checkpoint.identity != record_pages._identity(path, harness, sid)  # noqa: SLF001
        or checkpoint.stamp != read.cursor.stamp
        or read.cursor.stream != checkpoint.stream
    ):
        raise _SourceChangedError
    calls, results, rewrites = _rows_of(read.rows, checkpoint.stream != "parent")
    touched = (results.keys() | rewrites.keys()) - calls.keys()
    available = {call.call_id: call for call in (*checkpoint.calls, *checkpoint.dependencies)}
    selected = [call for call in available.values() if call.call_id in touched]
    if not selected:
        return ()
    lines = dict.fromkeys(
        line for call in selected for line in (call.line, call.rewrite) if line is not None
    )
    if sum(line.end - line.start for line in lines) > budget.available or budget.reason:
        return None
    rows = _outline_rows(
        path, harness, checkpoint.stamp, tuple(lines), budget, stream=checkpoint.stream
    )
    if rows is None:
        return None
    pending = []
    for held in selected:
        source_rows = [rows[held.line]]
        if held.rewrite is not None:
            source_rows.append(rows[held.rewrite])
        parsed = {call.call_id: call for call in _pending_calls(source_rows, checkpoint.stream)}
        if held.call_id not in parsed:
            raise _SourceChangedError
        pending.append(
            replace(
                parsed[held.call_id],
                position=held.position,
                fact_ids=held.fact_ids,
                input_offset=held.rewrite.start if held.rewrite else held.line.start,
            )
        )
    return tuple(pending)


def _outline_rows(
    path: str,
    harness: str,
    stamp: Stamp,
    lines: tuple[_OutlineLine, ...],
    budget: _Budget,
    *,
    stream: str = "parent",
) -> dict[_OutlineLine, dict[str, Any]] | None:
    """Read and verify selected input lines using the caller's remaining allowance."""
    rows: dict[_OutlineLine, dict[str, Any]] = {}
    follow = stream == "parent" and harness not in observer.DIRECTION_HARNESSES
    with runtime_io._open_binary(path, follow_links=follow) as source:  # noqa: SLF001
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or _stamp(info) != stamp:
            raise _SourceChangedError
        for line in lines:
            source.seek(line.start)
            raw = bytearray()
            while len(raw) < line.end - line.start and budget.reason is None:
                chunk = budget.line(source, min(64 * 1024, line.end - line.start - len(raw)))
                if not chunk:
                    raise _SourceChangedError
                raw.extend(chunk)
            if len(raw) != line.end - line.start:
                return None
            if hashlib.sha256(raw).hexdigest() != line.digest:
                raise _SourceChangedError
            try:
                row = json.loads(raw)
            except (ValueError, RecursionError) as error:
                raise _SourceChangedError from error
            if not isinstance(row, dict):
                raise _SourceChangedError
            rows[line] = row
        if _stamp(os.stat(path)) != stamp:
            raise _SourceChangedError
    return rows


def _outline_defer(read: _StreamRead, before: StreamCursor, row: int) -> None:
    if len(read.rows) > row:
        _cut(read, row)
    read.cursor = before
    read.boundaries = [(end, digest) for end, digest in read.boundaries if end <= before.end_offset]
    read.unread = [region for region in read.unread if region.end_offset <= before.end_offset]


def _outline_scan(
    config: RuntimeConfig,
    source: BinaryIO,
    read: _StreamRead,
    checkpoint: OutlineCheckpoint,
    budget: _Budget,
    sid: str,
    harness: str,
) -> tuple[PendingCall, ...]:
    held: dict[str, PendingCall] = {}
    allowance = budget.used + budget.remaining
    while read.cursor.offset < read.cursor.stamp[2]:
        if budget.available <= 0 or time.monotonic() >= budget.scan_deadline:
            break
        before, row = read.cursor, len(read.rows)
        read.unread = [region for region in read.unread if region.reason not in {"bytes", "time"}]
        _consume(config, source, read, budget, harness, sid, one_line=True)
        if read.cursor.fragment:
            if read.cursor.offset == read.cursor.stamp[2]:
                read.cursor = replace(read.cursor, fragment=b"")
            elif (
                before.end_offset == read.start
                and budget.reason == "bytes"
                and read.cursor.offset
                - read.cursor.line_start
                + (before.end_offset - before.boundary_start if before.boundary_digest else 0)
                >= allowance
            ):
                read.cursor = replace(read.cursor, fragment=b"", skipping=True)
            else:
                _outline_defer(read, before, row)
            break
        read.unread = [
            replace(region, reason="outline_line_limit")
            if region.reason == "oversized_line"
            else region
            for region in read.unread
        ]
        if harness == "codex":
            continue
        remaining = replace(
            checkpoint,
            calls=tuple(c for c in checkpoint.calls if c.call_id not in held),
            dependencies=tuple(c for c in checkpoint.dependencies if c.call_id not in held),
        )
        pending = _outline_pending(read.path, harness, sid, remaining, read, budget)
        if pending is None:
            # A fresh poll needs the preceding boundary, this row and its touched source inputs.
            _calls, results, rewrites = _rows_of(read.rows[row:], read.cursor.stream != "parent")
            lines = {
                line
                for call in checkpoint.calls
                if call.call_id in results.keys() | rewrites.keys()
                for line in (call.line, call.rewrite)
                if line is not None
            }
            prior_boundary = (
                before.end_offset - before.boundary_start if before.boundary_digest else 0
            )
            minimum = (
                read.cursor.end_offset
                - before.end_offset
                + prior_boundary
                + sum(line.end - line.start for line in lines)
            )
            if budget.reason == "time" or minimum <= allowance:
                _outline_defer(read, before, row)
                break
            end = read.cursor
            _outline_defer(read, before, row)
            read.cursor = end
            read.unread.append(
                UnreadRegion(
                    before.end_offset, end.end_offset, "outline_input_limit", read.cursor.stream
                )
            )
        else:
            held.update((call.call_id, call) for call in pending)
    return tuple(held.values())


def _outline_parent_page(
    config: RuntimeConfig,
    path: str,
    sid: str,
    checkpoint: OutlineCheckpoint,
    budget: _Budget,
    *,
    newest: bool = False,
    harness: str = "claude",
    parent: tuple[str, OutlineCheckpoint] | None = None,
) -> tuple[SourcePage, OutlineCheckpoint]:
    """Read one native stream; a child supplies its real parent's classification context."""
    frontier = checkpoint.frontier
    old = (
        StreamCursor(checkpoint.stream, checkpoint.stamp)
        if frontier is None
        else StreamCursor(
            checkpoint.stream,
            checkpoint.stamp,
            offset=frontier.offset,
            end_offset=frontier.end_offset,
            boundary_start=frontier.boundary_start,
            boundary_digest=frontier.boundary_digest,
            line_start=frontier.line_start,
            line_hash=frontier.line_hash,
            skipping=frontier.discarding,
        )
    )
    follow = checkpoint.stream == "parent" and harness not in observer.DIRECTION_HARNESSES
    with runtime_io._open_binary(path, follow_links=follow) as source:  # noqa: SLF001
        if _stamp(os.fstat(source.fileno())) != checkpoint.stamp:
            raise _SourceChangedError
        verified: str | None
        if newest:
            read = _StreamRead(StreamCursor(checkpoint.stream, checkpoint.stamp), 0, path)
            _window_start(source, read, budget)
            old = read.cursor
            read.initial = old
            stopped, verified = False, ""
        else:
            boundary_bytes = old.end_offset - old.boundary_start
            allowance = budget.used + budget.remaining
            # Exhausting this poll's remainder is retryable. Refuse only when a whole poll cannot
            # verify the boundary and, while source remains, admit even one new byte.
            stopped = (
                checkpoint.stopped
                or boundary_bytes > allowance
                or (boundary_bytes == allowance and old.offset < old.stamp[2])
            )
            verified = None if stopped else _verify(source, old, budget)
            if verified is not None and verified != old.boundary_digest:
                raise _SourceChangedError
            read = _StreamRead(old, old.end_offset, path, initial=old)
        pending = (
            _outline_scan(config, source, read, checkpoint, budget, sid, harness)
            if verified is not None
            else ()
        )
    if stopped and not checkpoint.stopped:
        read.unread.append(
            UnreadRegion(old.end_offset, old.stamp[2], "outline_boundary_limit", checkpoint.stream)
        )
    head_unknown = (
        checkpoint.head_unknown
        or read.cursor.skipping
        or any(region.reason not in {"bytes", "time"} for region in read.unread)
    )
    first_gap = min(
        (region.start_offset for region in read.unread if region.reason not in {"bytes", "time"}),
        default=read.cursor.line_start if read.cursor.skipping else read.cursor.offset,
    )
    head_rows = [
        row
        for row, cursor in zip(read.rows, read.row_cursors, strict=True)
        if harness == "claude" and not checkpoint.head_unknown and cursor.line_start < first_gap
    ]
    head = (
        checkpoint.head[0]
        or next(
            (row["cwd"] for row in head_rows if isinstance(row.get("cwd"), str) and row["cwd"]), ""
        ),
        checkpoint.head[1]
        if checkpoint.head[1] is not None
        else next(
            (
                stamp
                for row in head_rows
                if (stamp := records.parse_ts(row.get("timestamp"))) is not None
            ),
            None,
        ),
    )
    transient = SourceCursor(
        checkpoint.identity,
        (old,),
        pending,
        head[0],
        listing_writes=frozenset(checkpoint.listing_writes) | frozenset(checkpoint.withdrawals),
    )
    read.known_head = head
    read.dependency_ids = frozenset(call.call_id for call in checkpoint.dependencies)
    if parent is None:
        page = _finish(config, path, harness, sid, [read], [], transient, budget, outline=True)
    else:
        parent_path, parent_checkpoint = parent
        parent_read = _StreamRead(StreamCursor("parent", parent_checkpoint.stamp), 0, parent_path)
        parent_read.known_head = parent_checkpoint.head
        transient = replace(
            transient,
            session_dir=parent_checkpoint.head[0],
            listing_writes=frozenset(parent_checkpoint.listing_writes)
            | frozenset(checkpoint.listing_writes)
            | frozenset(parent_checkpoint.withdrawals),
        )
        page = _finish(
            config,
            parent_path,
            harness,
            sid,
            [parent_read, read],
            [],
            transient,
            budget,
            outline=True,
        )
    snapshot = page.snapshot
    if snapshot is None:
        raise _SourceChangedError
    next_checkpoint = replace(
        _outline_checkpoint(path, harness, sid, read, snapshot.cursor.pending, checkpoint),
        frontier=_OutlineFrontier(
            read.cursor.offset,
            read.cursor.end_offset,
            read.cursor.boundary_start,
            read.cursor.boundary_digest,
            read.cursor.line_start,
            read.cursor.line_hash,
            read.cursor.skipping,
        ),
        gaps=(
            *checkpoint.gaps,
            *(region for region in read.unread if region.reason not in {"bytes", "time"}),
        ),
        head=head,
        listing_writes=tuple(sorted(snapshot.cursor.listing_writes)),
        stopped=stopped,
        head_unknown=head_unknown if harness == "claude" else False,
    )
    _outline_bound(next_checkpoint)
    unread = list(next_checkpoint.gaps)
    if read.cursor.end_offset < checkpoint.stamp[2] and not stopped:
        reason = (
            "outline_line_limit"
            if read.cursor.skipping
            else "partial_line"
            if read.cursor.offset == checkpoint.stamp[2]
            else budget.reason or "bytes"
        )
        unread.append(
            UnreadRegion(read.cursor.end_offset, checkpoint.stamp[2], reason, checkpoint.stream)
        )
    coverage = SourceCoverage(
        False,
        page.entries[0].fact_id if page.entries else None,
        old.end_offset,
        read.cursor.end_offset,
        tuple(unread),
        "read" if harness == "claude" else "not_read",
        "read" if harness == "claude" else "not_admitted",
        ("parent_only",) if harness == "claude" else _CODEX_NOTES,
    )
    return replace(
        page,
        state="limited" if stopped else page.state,
        coverage=coverage,
        snapshot=None,
        next=None,
        bytes_read=budget.used,
    ), next_checkpoint


def _read_outline_parent(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    *,
    after: OutlineCheckpoint | None = None,
    max_bytes: int | None = None,
    deadline: float | None = None,
    budget: _Budget | None = None,
) -> tuple[SourcePage, OutlineCheckpoint | None]:
    """Internal parent-only admission. Full words in the returned page are transient."""
    if harness not in HARNESSES:
        return SourcePage("unsupported", harness, sid), None
    now = time.monotonic()
    end = now + config.session_source_page_max_seconds if deadline is None else deadline
    budget = budget or _Budget(
        max(0, config.session_source_page_max_bytes if max_bytes is None else max_bytes),
        end,
        now + max(0.0, end - now) * (1 - config.session_source_classify_share),
    )
    identity = record_pages._identity(path, harness, sid)  # noqa: SLF001
    size = after.stamp[2] if after else 0
    try:
        info = os.stat(path)
        size = info.st_size
        checkpoint = after or OutlineCheckpoint(identity, _stamp(info), ())
        if (
            not stat.S_ISREG(info.st_mode)
            or checkpoint.identity != identity
            or checkpoint.stamp != _stamp(info)
        ):
            return SourcePage("stale" if after else "unavailable", harness, sid), None
        return _outline_parent_page(config, path, sid, checkpoint, budget, harness=harness)
    except _SourceChangedError:
        return SourcePage("stale", harness, sid, bytes_read=budget.used), None
    except ValueError as error:
        if str(error) != "outline_state_limit":
            raise
        start = after.frontier.offset if after and after.frontier else 0
        coverage = SourceCoverage(
            False,
            None,
            start,
            start,
            (UnreadRegion(start, size, "outline_state_limit"),),
            "read" if harness == "claude" else "not_read",
            "read" if harness == "claude" else "not_admitted",
            ("parent_only",) if harness == "claude" else _CODEX_NOTES,
        )
        return SourcePage("limited", harness, sid, coverage=coverage, bytes_read=budget.used), None
    except OSError:
        return SourcePage(
            "stale" if after else "unavailable", harness, sid, bytes_read=budget.used
        ), None


def _outline_intervals(
    prior: tuple[tuple[int, int], ...],
    pages: list[SourcePage],
    *,
    stream: str = "parent",
) -> tuple[tuple[int, int], ...]:
    intervals = list(prior)
    for page in pages:
        coverage = page.coverage
        if coverage is None:
            continue
        cursor = coverage.start_offset
        for gap in sorted(coverage.unread, key=lambda region: region.start_offset):
            if gap.stream != stream or gap.reason in {"bytes", "time", "before_window"}:
                continue
            start, end = max(cursor, gap.start_offset), min(coverage.end_offset, gap.end_offset)
            if start < end:
                if cursor < start:
                    intervals.append((cursor, start))
                cursor = end
        if cursor < coverage.end_offset:
            intervals.append((cursor, coverage.end_offset))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return tuple(merged)


def _outline_missing(
    accepted: tuple[tuple[int, int], ...],
    size: int,
    gaps: tuple[UnreadRegion, ...],
    reason: str,
    *,
    stream: str = "parent",
) -> list[UnreadRegion]:
    unread = []
    cursor = 0
    for start, end in (*accepted, (size, size)):
        for gap in sorted(gaps, key=lambda region: region.start_offset):
            lower, upper = max(cursor, gap.start_offset), min(start, gap.end_offset)
            if lower < upper:
                if cursor < lower:
                    unread.append(UnreadRegion(cursor, lower, reason, stream))
                unread.append(UnreadRegion(lower, upper, gap.reason, stream))
                cursor = upper
        if cursor < start:
            unread.append(UnreadRegion(cursor, start, reason, stream))
        cursor = end
    return unread


def _outline_preview(
    pages: list[SourcePage],
    checkpoint: OutlineCheckpoint,
    budget: _Budget,
    *,
    complete: bool,
    children: bool,
) -> SourcePage:
    facts: dict[str, SourceEntry] = {}
    positions: dict[str, tuple[int, int, int]] = {}
    observations: dict[str, int] = {}
    for page in pages:
        for old, _new in page.replacements:
            for fact_id in old:
                facts.pop(fact_id, None)
                positions.pop(fact_id, None)
                observations.pop(fact_id, None)
        facts.update((entry.fact_id, entry) for entry in page.entries)
        positions.update(page.positions)
        observations.update(page.observations)
    entries = tuple(sorted(facts.values(), key=lambda entry: positions[entry.fact_id]))
    gaps = tuple(
        region
        for page in pages
        if page.coverage
        for region in page.coverage.unread
        if region.stream == "parent" and region.reason not in {"bytes", "time", "before_window"}
    )
    unread = _outline_missing(
        checkpoint.accepted, checkpoint.stamp[2], gaps, budget.reason or "bytes"
    )
    if children:
        unread.append(UnreadRegion(0, 0, "children_not_read", "children"))
    coverage = SourceCoverage(
        complete,
        entries[0].fact_id if entries and not complete else None,
        checkpoint.accepted[0][0] if checkpoint.accepted else 0,
        checkpoint.accepted[-1][1] if checkpoint.accepted else 0,
        tuple(unread),
        "read" if pages[0].harness == "claude" else "not_read",
        "read" if pages[0].harness == "claude" else "not_admitted",
        (("children_not_read",) if children else ())
        if pages[0].harness == "claude"
        else _CODEX_NOTES,
    )
    return replace(
        pages[0],
        entries=entries,
        coverage=coverage,
        bytes_read=budget.used,
        replacements=tuple(change for page in pages for change in page.replacements),
        positions=tuple((entry.fact_id, positions[entry.fact_id]) for entry in entries),
        observations=tuple((entry.fact_id, observations[entry.fact_id]) for entry in entries),
        replacement_observations=tuple(
            value for page in pages for value in page.replacement_observations
        ),
    )


def _outline_bootstrap(
    config: RuntimeConfig,
    path: str,
    sid: str,
    after: OutlineCheckpoint | None,
    budget: _Budget,
    opening_bytes: int,
    harness: str,
    stamps: tuple[tuple[str, Stamp | None], ...],
) -> tuple[SourcePage, OutlineCheckpoint | None]:
    stamp = stamps[0][1]
    if stamp is None:
        raise OSError("missing parent")
    cold_long = after is None and stamp[2] > budget.remaining
    if cold_long:
        budget.read_limit = budget.used + min(budget.remaining, max(0, opening_bytes))
    try:
        page, checkpoint = _read_outline_parent(
            config, path, harness, sid, after=after, budget=budget
        )
    finally:
        budget.read_limit = None
    if checkpoint is None or page.state != "ok":
        return page, checkpoint
    pages = [page]
    if cold_long and budget.reason is None:
        tail, tail_checkpoint = _outline_parent_page(
            config, path, sid, checkpoint, budget, newest=True, harness=harness
        )
        pages.append(tail)
        checkpoint = replace(
            checkpoint,
            dependencies=_outline_merge_dependencies(
                checkpoint.dependencies, tail_checkpoint.dependencies
            ),
            withdrawals=tuple(
                sorted(set(checkpoint.withdrawals) | set(tail_checkpoint.withdrawals))
            ),
        )
    children = len(stamps) > 1
    checkpoint = replace(
        checkpoint, accepted=_outline_intervals(after.accepted if after else (), pages)
    )
    _outline_bound(checkpoint)
    complete = after is None and len(pages) == 1 and checkpoint.parent_complete and not children
    return _outline_preview(
        pages, checkpoint, budget, complete=complete, children=children
    ), checkpoint


def _outline_candidates(path: str) -> Iterator[str]:
    """Stream the two admitted layouts without glob's eager directory match list."""
    directory = os.path.join(path[: -len(".jsonl")], "subagents")
    if not path.endswith(".jsonl") or os.path.islink(directory) or not os.path.isdir(directory):
        return
    with os.scandir(directory) as entries:
        for entry in entries:
            yield entry.path
            if entry.name != "workflows" or not entry.is_dir(follow_symlinks=False):
                continue
            with os.scandir(entry.path) as workflows:
                for workflow in workflows:
                    yield workflow.path
                    if not workflow.is_dir(follow_symlinks=False):
                        continue
                    with os.scandir(workflow.path) as children:
                        for child in children:
                            yield child.path


def _outline_stamps(
    path: str, harness: str, *, deadline: float
) -> tuple[tuple[str, Stamp | None], ...]:
    """Bounded cache/source inventory; refusal raises ValueError with the coverage reason."""
    inventory: list[tuple[str, Stamp | None]] = [(path, _stamp(os.stat(path)))]
    if harness != "claude":
        return tuple(inventory)
    for count, candidate in enumerate(_outline_candidates(path), 1):
        if time.monotonic() >= deadline:
            raise ValueError("time")
        if count > _OUTLINE_INVENTORY_ENTRIES:
            raise ValueError("outline_stream_limit")
        if not context._admitted_subagent_paths(path, (candidate,)):  # noqa: SLF001
            continue
        if len(inventory) >= _OUTLINE_STREAM_LIMIT:
            raise ValueError("outline_stream_limit")
        try:
            stamp = _stamp(os.stat(candidate, follow_symlinks=False))
        except OSError:
            stamp = None
        inventory.append((candidate, stamp))
    return (inventory[0], *sorted(inventory[1:]))


def _outline_child(path: str, child: str, stamp: Stamp | None, sid: str) -> OutlineCheckpoint:
    stream = _child_stream(path, child)
    return OutlineCheckpoint(
        record_pages._identity(child, "claude", sid),  # noqa: SLF001
        stamp or (0, 0, 0, 0),
        (),
        stream=stream,
        gaps=() if stamp else (UnreadRegion(0, 0, "unreadable_subagent", stream),),
        stopped=stamp is None,
    )


def _outline_unread(checkpoint: OutlineCheckpoint, reason: str) -> tuple[UnreadRegion, ...]:
    regions = []
    for current in (checkpoint, *(child for _, child in checkpoint.children)):
        frontier = current.frontier
        missing_reason = (
            "children_not_read"
            if current.stream != "parent" and frontier is None
            else "outline_line_limit"
            if frontier is not None and frontier.discarding
            else "partial_line"
            if frontier is not None
            and frontier.offset == current.stamp[2]
            and frontier.end_offset < frontier.offset
            else reason
        )
        regions.extend(
            _outline_missing(
                current.accepted,
                current.stamp[2],
                current.gaps,
                missing_reason,
                stream=current.stream,
            )
        )
        regions.extend(gap for gap in current.gaps if gap.start_offset == gap.end_offset)
    if checkpoint.replay:
        regions.append(UnreadRegion(0, 0, "classification_pending", "classification"))
    return tuple(regions)


def _outline_dependency_map(
    checkpoint: OutlineCheckpoint | None,
) -> dict[tuple[str, str], _OutlineCall]:
    if checkpoint is None:
        return {}
    return {
        (current.stream, call.call_id): call
        for current in (checkpoint, *(child for _, child in checkpoint.children))
        for call in current.dependencies
    }


def _outline_reconcile(
    previous: OutlineCheckpoint | None,
    current: OutlineCheckpoint,
    *,
    initial_complete: bool = False,
) -> OutlineCheckpoint:
    known = set(previous.withdrawals if previous else ())
    written = known | set(current.withdrawals)
    for _, child in current.children:
        written.update(child.withdrawals)
    if len(written) > _OUTLINE_WITHDRAWAL_LIMIT:
        raise ValueError("outline_dependency_limit")
    old, new = _outline_dependency_map(previous), _outline_dependency_map(current)
    if len(new) > _OUTLINE_DEPENDENCY_LIMIT:
        raise ValueError("outline_dependency_limit")
    changed = (
        list(new)
        if written != known and not initial_complete
        else [
            key
            for key, call in new.items()
            if key in old
            and old[key].revision
            and _outline_call_offset(call) > _outline_call_offset(old[key])
        ]
    )
    revision = max(
        current.classification_revision, previous.classification_revision if previous else 0
    )
    return replace(
        current,
        withdrawals=tuple(sorted(written)),
        replay=tuple(dict.fromkeys((*current.replay, *changed))),
        classification_revision=revision + bool(changed),
    )


def _outline_replay(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    checkpoint: OutlineCheckpoint,
    budget: _Budget,
) -> tuple[SourcePage, OutlineCheckpoint]:
    stream, call_id = checkpoint.replay[0]
    owner_path, owner = next(
        (p, state)
        for p, state in ((path, checkpoint), *checkpoint.children)
        if state.stream == stream
    )
    held = next(call for call in owner.dependencies if call.call_id == call_id)
    lines = tuple(
        dict.fromkeys(line for line in (held.line, held.rewrite, held.result) if line is not None)
    )
    required = sum(line.end - line.start for line in lines)
    if required > budget.used + budget.remaining:
        raise ValueError("outline_dependency_limit")
    if required > budget.available or budget.reason:
        return SourcePage("ok", harness, sid), checkpoint
    source = _outline_rows(owner_path, harness, owner.stamp, lines, budget, stream=stream)
    if source is None or time.monotonic() >= budget.deadline:
        return SourcePage("ok", harness, sid), checkpoint
    rows = [source[line] for line in sorted(lines, key=lambda line: line.start)]
    call = next((call for call in _pending_calls(rows, stream) if call.call_id == call_id), None)
    if call is None:
        raise _SourceChangedError
    call = replace(call, position=held.position, fact_ids=held.fact_ids)
    declared = context._declared_scripts(  # noqa: SLF001
        config,
        path,
        checkpoint.head[0],
        rows if stream == "parent" else [],
        [] if stream == "parent" else [rows],
        prior_writes=frozenset(checkpoint.withdrawals),
        known_start=(checkpoint.head[1],),
    )
    if time.monotonic() >= budget.deadline:
        return SourcePage("ok", harness, sid), checkpoint
    read = _StreamRead(StreamCursor(stream, owner.stamp), 0, owner_path)
    entries = tuple(
        _classify(
            read,
            call,
            context._tool_result_blocks(rows, sidechain=stream != "parent"),  # noqa: SLF001
            -1,
            sid,
            checkpoint.head[0],
            declared,
        )
    )
    if time.monotonic() >= budget.deadline:
        return SourcePage("ok", harness, sid), checkpoint
    revision = checkpoint.classification_revision
    ids = tuple(entry.fact_id for entry in entries)
    updated = replace(held, fact_ids=ids, revision=revision)
    owner = replace(
        owner,
        dependencies=tuple(
            updated if item.call_id == call_id else item for item in owner.dependencies
        ),
    )
    checkpoint = (
        replace(checkpoint, dependencies=owner.dependencies)
        if stream == "parent"
        else replace(
            checkpoint,
            children=tuple(
                (p, owner if state.stream == stream else state) for p, state in checkpoint.children
            ),
        )
    )
    offset = _outline_call_offset(held)
    page = SourcePage(
        "ok",
        harness,
        sid,
        entries=entries,
        positions=tuple(
            (entry.fact_id, (*held.position, index)) for index, entry in enumerate(entries)
        ),
        observations=tuple((entry.fact_id, offset) for entry in entries),
        replacements=((held.fact_ids, ids),),
        replacement_observations=(offset,),
        classification_revision=revision,
    )
    return page, replace(checkpoint, replay=checkpoint.replay[1:])


def _outline_advance(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    checkpoint: OutlineCheckpoint,
    budget: _Budget,
) -> tuple[SourcePage, OutlineCheckpoint | None]:
    streams = [(path, checkpoint), *checkpoint.children]
    # One stream gets the poll's full allowance; round-robin avoids both starvation and
    # a per-stream quota too small to fit a verified boundary plus one classifier input.
    index = None
    for step in range(len(streams)):
        candidate = (checkpoint.next_stream + step) % len(streams)
        current = streams[candidate][1]
        if not current.stopped and (
            current.frontier is None or current.frontier.offset < current.stamp[2]
        ):
            index = candidate
            break
    if index is None:
        return SourcePage("ok", harness, sid), checkpoint
    stream_path, current = streams[index]
    if index == 0:
        page, advanced = _read_outline_parent(
            config,
            path,
            harness,
            sid,
            after=current,
            budget=budget,
        )
    else:
        try:
            page, advanced = _outline_parent_page(
                config,
                stream_path,
                sid,
                current,
                budget,
                harness=harness,
                parent=(path, checkpoint),
            )
        except OSError:
            advanced = replace(
                current,
                stopped=True,
                gaps=(
                    *current.gaps,
                    UnreadRegion(
                        current.frontier.end_offset if current.frontier else 0,
                        current.stamp[2],
                        "unreadable_subagent",
                        current.stream,
                    ),
                ),
            )
            page = SourcePage("limited", harness, sid)
    if advanced is None or page.state not in {"ok", "limited"}:
        return page, None
    advanced = replace(
        advanced, accepted=_outline_intervals(current.accepted, [page], stream=current.stream)
    )
    if index == 0:
        checkpoint = replace(advanced, children=checkpoint.children, inventory=checkpoint.inventory)
    else:
        children = list(checkpoint.children)
        children[index - 1] = (stream_path, advanced)
        checkpoint = replace(checkpoint, children=tuple(children))
    return page, replace(checkpoint, next_stream=(index + 1) % len(streams))


def _outline_streams(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    after: OutlineCheckpoint | None,
    budget: _Budget,
    opening_bytes: int,
) -> tuple[SourcePage, OutlineCheckpoint | None]:
    inventory = _outline_stamps(path, harness, deadline=budget.deadline)
    checkpoint: OutlineCheckpoint | None
    if after is not None and (
        after.inventory != inventory
        or after.identity != record_pages._identity(path, harness, sid)  # noqa: SLF001
        or after.stream != "parent"
    ):
        raise _SourceChangedError
    if after is not None and after.dependency_limited:
        page, checkpoint = SourcePage("limited", harness, sid), after
    elif after is not None and after.replay:
        page, checkpoint = _outline_replay(config, path, harness, sid, after, budget)
    elif after is None:
        page, checkpoint = _outline_bootstrap(
            config, path, sid, None, budget, opening_bytes, harness, inventory
        )
        if checkpoint is not None:
            checkpoint = replace(
                checkpoint,
                inventory=inventory,
                next_stream=1 if len(inventory) > 1 else 0,
                children=tuple(
                    (child, _outline_child(path, child, stamp, sid))
                    for child, stamp in inventory[1:]
                ),
            )
    else:
        page, checkpoint = _outline_advance(config, path, harness, sid, after, budget)
    if checkpoint is None:
        return page, None
    checkpoint = _outline_reconcile(
        after,
        checkpoint,
        initial_complete=bool(after is None and page.coverage and page.coverage.complete),
    )
    _outline_bound(checkpoint)
    if _outline_stamps(path, harness, deadline=budget.deadline) != inventory:
        raise _SourceChangedError
    previous = page.coverage
    coverage = SourceCoverage(
        bool(after is None and checkpoint.complete and previous and previous.complete),
        previous.starts_at if previous else None,
        checkpoint.accepted[0][0] if checkpoint.accepted else 0,
        checkpoint.accepted[-1][1] if checkpoint.accepted else 0,
        _outline_unread(checkpoint, budget.reason or "bytes"),
        "read" if harness == "claude" else "not_read",
        "read" if harness == "claude" else "not_admitted",
        (
            ("children_not_read",)
            if any(not child.parent_complete for _, child in checkpoint.children)
            else ()
        )
        if harness == "claude"
        else _CODEX_NOTES,
    )
    return replace(page, coverage=coverage, bytes_read=budget.used), checkpoint


def _read_outline(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    *,
    after: OutlineCheckpoint | None = None,
    max_bytes: int | None = None,
    opening_bytes: int | None = None,
    deadline: float | None = None,
) -> tuple[SourcePage, OutlineCheckpoint | None]:
    """Cold parent opening/tail preview, then fair bounded stream pages; no retained words."""
    if harness not in HARNESSES:
        return read(config, path, harness, sid, max_bytes=max_bytes, deadline=deadline), None
    now = time.monotonic()
    end = now + config.session_outline_max_seconds if deadline is None else deadline
    budget = _Budget(
        max(0, config.session_outline_max_bytes if max_bytes is None else max_bytes),
        end,
        now + max(0.0, end - now) * (1 - config.session_source_classify_share),
    )
    try:
        return _outline_streams(
            config,
            path,
            harness,
            sid,
            after,
            budget,
            config.session_outline_head_bytes if opening_bytes is None else opening_bytes,
        )
    except _SourceChangedError:
        return SourcePage("stale", harness, sid, bytes_read=budget.used), None
    except OSError:
        return SourcePage(
            "stale" if after else "unavailable", harness, sid, bytes_read=budget.used
        ), None
    except ValueError as error:
        if str(error) not in {
            "outline_state_limit",
            "outline_stream_limit",
            "outline_dependency_limit",
            "time",
        }:
            raise
        coverage = SourceCoverage(
            False,
            None,
            0,
            0,
            (UnreadRegion(0, 0, str(error), "children"),),
            "read" if harness == "claude" else "not_read",
            "read" if harness == "claude" else "not_admitted",
            () if harness == "claude" else _CODEX_NOTES,
        )
        stopped = None
        if str(error) == "outline_dependency_limit":
            inventory = _outline_stamps(path, harness, deadline=budget.deadline)
            stopped = after or OutlineCheckpoint(
                record_pages._identity(path, harness, sid),  # noqa: SLF001
                _stamp(os.stat(path)),
                (),
                inventory=inventory,
            )
            stopped = replace(
                stopped,
                dependency_limited=True,
                replay=(),
                gaps=(
                    *stopped.gaps,
                    UnreadRegion(0, 0, "outline_dependency_limit", "classification"),
                ),
            )
        return SourcePage(
            "limited",
            harness,
            sid,
            notes=(str(error),),
            bytes_read=budget.used,
            coverage=coverage,
        ), stopped


class _SourceChangedError(ValueError):
    def __init__(self, verified: tuple[int, str] | None = None) -> None:
        super().__init__("source changed")
        self.verified = verified


def entry_for_page(entry: SourceEntry) -> dict[str, Any]:
    """Publish an explicit word-free copy, including no caller-held cursor state."""
    return {key: value for key, value in asdict(entry).items() if key != "words"}


def _stamp(info: os.stat_result) -> Stamp:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def source_stamps(path: str, harness: str) -> tuple[tuple[str, Stamp | None], ...]:
    """A child can gain results without a parent append, so its stamp belongs in the cache key."""
    paths = (
        [path, *sorted(context._admitted_subagent_paths(path, None))]  # noqa: SLF001
        if harness == "claude"
        else [path]
    )
    result: list[tuple[str, Stamp | None]] = [(path, _stamp(os.stat(path)))]
    for child in paths[1:]:
        try:
            result.append((child, _stamp(os.stat(child))))
        except OSError:
            result.append((child, None))
    return tuple(result)


def _digest(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True).encode()).hexdigest()[:32]


@dataclass
class _Budget:
    remaining: int
    deadline: float
    # Scanning stops here so classifying what was scanned can finish by `deadline`.
    scan_deadline: float
    used: int = 0
    # Optional absolute spent-byte ceiling for one phase; it never replaces the poll allowance.
    read_limit: int | None = None

    @property
    def available(self) -> int:
        return (
            self.remaining
            if self.read_limit is None
            else min(self.remaining, max(0, self.read_limit - self.used))
        )

    @property
    def reason(self) -> str | None:
        if time.monotonic() >= self.scan_deadline:
            return "time"
        return "bytes" if self.available <= 0 else None

    def line(self, source: BinaryIO, count: int) -> bytes:
        raw = source.readline(min(count, max(0, self.available)))
        self.remaining -= len(raw)
        self.used += len(raw)
        return raw


@dataclass
class _StreamRead:
    cursor: StreamCursor
    start: int
    path: str = ""
    initial: StreamCursor | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    # The resumable frontier just before each row, so classification can stop between rows.
    row_cursors: list[StreamCursor] = field(default_factory=list)
    messages: list[SourceEntry] = field(default_factory=list)
    message_order: dict[str, int] = field(default_factory=dict)
    tool_order: dict[str, int] = field(default_factory=dict)
    result_calls: tuple[str, ...] = ()
    unread: list[UnreadRegion] = field(default_factory=list)
    boundaries: list[tuple[int, str]] = field(default_factory=list)
    verified: tuple[int, str] | None = None
    replacements: list[tuple[tuple[str, ...], tuple[str, ...]]] = field(default_factory=list)
    fact_positions: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    fact_observations: dict[str, int] = field(default_factory=dict)
    replacement_observations: list[int] = field(default_factory=list)
    known_head: tuple[str, float | None] | None = None
    outline: bool = False
    withdrawals: frozenset[str] = frozenset()
    dependency_ids: frozenset[str] = frozenset()
    dependency_calls: list[PendingCall] = field(default_factory=list)


def _verify(source: BinaryIO, old: StreamCursor, budget: _Budget) -> str | None:
    if not old.end_offset:
        return ""
    source.seek(old.boundary_start)
    digest = hashlib.sha256()
    left = old.end_offset - old.boundary_start
    while left and budget.reason is None:
        raw = budget.line(source, min(left, 64 * 1024))
        if not raw:
            return ""
        digest.update(raw)
        left -= len(raw)
    return digest.hexdigest() if not left else None


def _whole_words(title: str, cap: int) -> str:
    """A title the producer cut at its character cap, cut back to a word with an ellipsis.

    `_semantic_line` bounds a prompt's title at `cap` wherever that lands, inside a word, and says
    nothing of the cut; the outline's page cannot tell and drew "…after Tu" whole. A title shorter
    than the cap was not cut. The fact id and digest keep the producer's text, so the cut changes
    only what a reader sees.

    A title of exactly `cap` ending in sentence punctuation is a whole sentence the cap happened to
    fit, since the producer keeps one sentence; clipping it dropped its last word and added an
    ellipsis to a title nothing had cut. One that ends without punctuation at exactly `cap` still
    cannot be told from a cut, and is clipped.
    """
    if len(title) < cap or (len(title) == cap and title.endswith((".", "!", "?"))):
        return title
    return transcripts.clip(title, cap - 1)


def _message(
    config: RuntimeConfig, raw: bytes, record: dict[str, Any], harness: str, sid: str
) -> SourceEntry | None:
    fact = record_pages._fact(config, raw, harness, sid)  # noqa: SLF001
    if fact is None:
        return _relayed(raw, record, harness, sid)
    # The pages' ids remain canonical, but their reading-specific word caps are not a source cap.
    words = context.whole_message_words(config, record, harness, len(raw))
    title = str(fact["summary"])
    kind = "person" if fact["type"] == "user_message" else "agent"
    return SourceEntry(
        str(fact["fact_id"]),
        _digest(title, words),
        kind,
        "parent",
        "parent",
        float(fact["at"]),
        _whole_words(title, min(context.MAX_SEMANTIC_LINE, config.observer_goal_cap_chars))
        if kind == "person"
        else title,
        words=words,
    )


RELAYED_TITLE = "Text relayed in a person turn"


def _relayed(raw: bytes, record: dict[str, Any], harness: str, sid: str) -> SourceEntry | None:
    """Text the harness put in a person turn: another agent's message, a resumed summary.

    The message parser refuses it so it never stands in for the person's goal. The summary
    admits it under its own kind, so it is labelled `relayed` rather than the person's words,
    and is never a message id (docs/design-session-summary.md#menu-windows-and-prompts).
    """
    if harness != "claude" or record.get("type") != "user":
        return None
    if record.get("isSidechain") or record.get("isMeta"):
        return None
    message = records.message_dict(record)
    content = message.get("content")
    if (message.get("role") or "user") != "user" or observer._blocks_carry_tool_result(content):  # noqa: SLF001
        return None
    text = records.extract_text(
        observer._redacted_message_content(content),  # noqa: SLF001
        cap=len(raw),
    ).strip()
    at = records.parse_ts(record.get("timestamp") or "")
    if (
        at is None
        or not records.strip_prompt_wrappers(text)
        or not records.injected_prompt(text, harness)
    ):
        return None
    words = records.safe_text(" ".join(records.mask_prose(text).split()), len(raw))
    if not words:
        return None
    event: dict[str, Any] = {"at": at, "title": RELAYED_TITLE, "harness": harness, "sid": sid}
    if isinstance(record.get("uuid"), str) and record["uuid"]:
        event["record_id"] = record["uuid"]
    fact = context._semantic_fact_from_event(event, "relayed", "relayed_text", "")  # noqa: SLF001
    return SourceEntry(
        str(fact["fact_id"]),
        _digest(RELAYED_TITLE, words),
        "relayed",
        "parent",
        "parent",
        float(at),
        RELAYED_TITLE,
        words=words,
    )


def _take(
    config: RuntimeConfig,
    read: _StreamRead,
    raw: bytes,
    harness: str,
    sid: str,
    before: StreamCursor,
) -> None:
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError):
        read.unread.append(
            UnreadRegion(
                read.cursor.line_start,
                read.cursor.end_offset,
                "unreadable_record",
                read.cursor.stream,
            )
        )
        return
    if not isinstance(record, dict):
        return
    # Codex puts its content in payload rather than message. Count text before calling a masker.
    payload = record.get("payload")
    shape = {"message": payload} if harness == "codex" and isinstance(payload, dict) else record
    if context._message_text_chars(shape) > context.PRESS_TEXT_MAX_CHARS:  # noqa: SLF001
        read.unread.append(
            UnreadRegion(
                read.cursor.line_start, read.cursor.end_offset, "oversized_line", read.cursor.stream
            )
        )
        return
    read.rows.append(record)
    read.row_cursors.append(before)
    if read.cursor.stream == "parent":
        entry = _message(config, raw, record, harness, sid)
        if entry is not None:
            read.messages.append(entry)
            read.message_order[entry.fact_id] = len(read.rows) - 1
            read.fact_positions[entry.fact_id] = (before.line_start, -1, 0)
            read.fact_observations[entry.fact_id] = before.line_start


def _consume(
    config: RuntimeConfig,
    source: BinaryIO,
    read: _StreamRead,
    budget: _Budget,
    harness: str,
    sid: str,
    *,
    one_line: bool = False,
) -> None:
    cursor = read.cursor
    source.seek(cursor.offset)
    chunks = [cursor.fragment] if cursor.fragment else []
    length = len(cursor.fragment)
    clean = cursor
    while cursor.offset < cursor.stamp[2] and budget.reason is None:
        raw = budget.line(
            source, min(config.record_page_chunk_bytes, cursor.stamp[2] - cursor.offset)
        )
        if not raw:
            raise OSError("source shortened while reading")
        cursor = replace(
            cursor, offset=cursor.offset + len(raw), line_hash=cursor.line_hash.add(raw)
        )
        length += len(raw)
        skipping = cursor.skipping or length > config.session_source_line_max_bytes
        if skipping:
            chunks.clear()
        else:
            chunks.append(raw)
        cursor = replace(cursor, skipping=skipping)
        if not raw.endswith(b"\n"):
            continue
        whole = b"".join(chunks)
        digest = cursor.line_hash.digest()
        read.boundaries.append((cursor.offset, digest))
        cursor = replace(
            cursor,
            end_offset=cursor.offset,
            boundary_start=cursor.line_start,
            boundary_digest=digest,
            fragment=b"",
        )
        read.cursor = cursor
        if skipping:
            read.unread.append(
                UnreadRegion(cursor.line_start, cursor.offset, "oversized_line", cursor.stream)
            )
        else:
            _take(config, read, whole, harness, sid, clean)
        cursor = replace(cursor, line_start=cursor.offset, skipping=False, line_hash=_LineHash())
        clean = cursor
        chunks, length = [], 0
        if one_line:
            break
    read.cursor = replace(cursor, fragment=b"".join(chunks))
    if cursor.offset < cursor.stamp[2]:
        read.unread.append(
            UnreadRegion(
                cursor.end_offset, cursor.stamp[2], budget.reason or "bytes", cursor.stream
            )
        )


def _read_stream(
    config: RuntimeConfig,
    path: str,
    stream: str,
    harness: str,
    sid: str,
    budget: _Budget,
    old: StreamCursor | None,
    *,
    newest: bool,
) -> _StreamRead:
    # Children were admitted link-free, so a link swapped in since is refused, as the tool report's
    # child reads do; the parent follows exactly where `project_context`'s transcript read does.
    follow = stream == "parent" and harness not in observer.DIRECTION_HARNESSES
    with runtime_io._open_binary(path, follow_links=follow) as source:  # noqa: SLF001
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise OSError("source is not a regular file")
        stamp = _stamp(info)
        if old and (stamp[:2] != old.stamp[:2] or stamp[2] < old.stamp[2]):
            raise _SourceChangedError
        verified = _verify(source, old, budget) if old else None
        if old and verified is not None and verified != old.boundary_digest:
            raise _SourceChangedError((old.end_offset, verified))
        cursor = replace(old, stamp=stamp) if old else StreamCursor(stream, stamp)
        read = _StreamRead(cursor, cursor.end_offset, path)
        read.verified = (old.end_offset, verified) if old and verified is not None else None
        if old and verified is None:
            read.unread.append(
                UnreadRegion(cursor.end_offset, stamp[2], budget.reason or "bytes", stream)
            )
        else:
            if newest and old is None:
                _window_start(source, read, budget)
            read.initial = read.cursor
            _consume(config, source, read, budget, harness, sid)
        if _stamp(os.stat(path)) != stamp:
            raise _SourceChangedError
        return read


def _window_start(source: BinaryIO, read: _StreamRead, budget: _Budget) -> None:
    if budget.reason is not None:
        return
    size = read.cursor.stamp[2]
    # The boundary probe is part of the allowance too; reserve it so the newest newline fits.
    start = max(0, size - max(0, budget.remaining - 1)) if size > budget.remaining else 0
    if start:
        source.seek(start - 1)
        budget.remaining -= 1
        budget.used += 1
        if source.read(1) != b"\n":
            source.seek(start)
            while budget.reason is None:
                raw = budget.line(source, 64 * 1024)
                start += len(raw)
                if not raw or raw.endswith(b"\n"):
                    break
        read.unread.append(UnreadRegion(0, start, "before_window", read.cursor.stream))
    read.start = start
    read.cursor = replace(read.cursor, offset=start, end_offset=start, line_start=start)


def _pending_calls(rows: list[dict[str, Any]], stream: str) -> list[PendingCall]:
    return [
        PendingCall(
            stream,
            at,
            cwd,
            call_id,
            name,
            json.dumps(
                {
                    key: value
                    for key, value in tool_input.items()
                    if key in {"command", "file_path", "notebook_path", "run_in_background"}
                }
            ),
        )
        for at, cwd, call_id, name, tool_input, _worker in context._claude_tool_uses(  # noqa: SLF001
            rows, sidechain=stream != "parent"
        )
    ]


def _rows_of(
    rows: list[dict[str, Any]], sidechain: bool
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """The first call/result rows and each call's last command-rewrite row."""
    calls: dict[str, int] = {}
    results: dict[str, int] = {}
    rewrites: dict[str, int] = {}
    for index, row in enumerate(rows):
        for _at, _cwd, call_id, _name, _input, _worker in context._claude_tool_uses(  # noqa: SLF001
            [row], sidechain=sidechain
        ):
            calls.setdefault(call_id, index)
        for call_id in context._tool_result_blocks([row], sidechain=sidechain):  # noqa: SLF001
            results.setdefault(call_id, index)
        rewrites.update((call_id, index) for call_id in context._hook_rewritten_commands([row]))  # noqa: SLF001
    return calls, results, rewrites


def _cut(read: _StreamRead, row: int) -> None:
    """Move the frontier back to just before `row`; everything from there is read again."""
    frontier = replace(read.row_cursors[row], stamp=read.cursor.stamp)
    kept = {fact_id for fact_id, index in read.message_order.items() if index < row}
    read.messages = [message for message in read.messages if message.fact_id in kept]
    del read.rows[row:], read.row_cursors[row:]
    read.unread = [region for region in read.unread if region.end_offset <= frontier.end_offset]
    read.unread.append(
        UnreadRegion(frontier.end_offset, frontier.stamp[2], "time", frontier.stream)
    )
    read.cursor = frontier


def _classify(
    read: _StreamRead,
    call: PendingCall,
    results: dict[str, Any],
    position: int,
    sid: str,
    session_dir: str,
    declared: project_scripts.Declarations | None = None,
) -> list[SourceEntry]:
    stream = read.cursor.stream
    tally = context._ToolReportTally(results, session_dir, declared)  # noqa: SLF001
    tally.add(
        call.at,
        call.cwd,
        call.call_id,
        call.name,
        json.loads(call.input_json),
        "" if stream == "parent" else stream,
    )
    actor = "parent" if stream == "parent" else "subagent"
    entries: list[SourceEntry] = []
    # The published report keeps one entry per check, its newest foreground run, under the call's
    # own id. Two checks in one call that share a title in different places
    # (`cd a && pytest; cd b && pytest`) are two published entries with ids apart, but one check
    # run twice in one place (`pytest; pytest`) derives one. The source keeps one run per check
    # in the call on the call id, chosen as the published `_latest` chooses, and gives every other
    # run a segment id, so no two source entries share an id; the run left on a segment id has no
    # published entry.
    foreground = sorted(
        (
            (run["segment"], identity, run)
            for identity, runs in tally.runs.items()
            for run in runs
            if not run["background"]
        ),
        key=lambda item: item[0],
    )
    by_check: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for segment, identity, run in foreground:
        by_check.setdefault(identity, []).append((segment, run))
    kept = {
        history[tally._latest([run for _segment, run in history])][0]  # noqa: SLF001
        for history in by_check.values()
    }
    for segment, identity, run in foreground:
        entry = tally._check_entry([run])  # noqa: SLF001
        if segment not in kept:
            entry["record_id"] = f"{call.call_id}:segment:{segment}"
        fact = context._semantic_fact_from_event(  # noqa: SLF001
            {**entry, "harness": "claude", "sid": sid}, "check_run", "tool_report", ""
        )
        fact_id = str(fact["fact_id"])
        read.tool_order[fact_id] = position
        entries.append(
            SourceEntry(
                fact_id,
                _digest(
                    entry["title"],
                    entry["result"],
                    entry.get("result_source"),
                    run["recorded"],
                ),
                "check",
                actor,
                stream,
                call.at,
                str(entry["title"]),
                result=str(entry["result"]),
                subject=context._semantic_id("check", identity),  # noqa: SLF001
            )
        )
    # Two paths written in one call whose clipped titles match derive one published fact id; the
    # first keeps the call id and each later one takes a write id, so source ids stay unique.
    titles: set[str] = set()
    for number, (path, write) in enumerate(tally.writes.items()):
        event = tally._write_entry(path, write)  # noqa: SLF001
        display = str(event["title"])
        if display in titles:
            event["record_id"] = f"{call.call_id}:write:{number}"
        titles.add(display)
        fact = context._semantic_fact_from_event(  # noqa: SLF001
            {**event, "harness": "claude", "sid": sid}, "path_written", "tool_report", ""
        )
        fact_id = str(fact["fact_id"])
        read.tool_order[fact_id] = position
        entries.append(
            SourceEntry(
                fact_id,
                _digest(display, call.call_id),
                "file",
                actor,
                stream,
                call.at,
                display,
                path=display,
                folder=os.path.dirname(display) or ".",
                subject=context._semantic_id("file", path),  # noqa: SLF001
            )
        )
    return entries


def _without_dependencies(
    declared: project_scripts.Declarations | None,
    *,
    steering: bool,
) -> project_scripts.Declarations:
    # A counterfactual using the same classifier, including future script-shell withdrawal.
    steered = frozenset(
        project_scripts.SCRIPT_SHELL_PREFIX + manager
        for managers in project_scripts.SCRIPT_SETTING_FILES.values()
        for manager in managers
    )
    empty = declared or project_scripts.Declarations("", "", {}, {}, {})
    return replace(
        empty.without(frozenset(project_scripts.DECLARING_FILES), withdraw_listing=True),
        listing_writes=empty.listing_writes | (steered if steering else frozenset()),
        memo={},
    )


def _outline_track_call(
    read: _StreamRead,
    call: PendingCall,
    entries: list[SourceEntry],
    results: dict[str, Any],
    position: int,
    sid: str,
    session_dir: str,
    declared: project_scripts.Declarations | None,
) -> None:
    if not read.outline:
        return
    if call.call_id in read.dependency_ids or any(
        entries
        != _classify(
            _StreamRead(read.cursor, read.start, read.path),
            call,
            results,
            position,
            sid,
            session_dir,
            _without_dependencies(declared, steering=steering),
        )
        for steering in (False, True)
    ):
        read.dependency_calls.append(
            replace(call, fact_ids=tuple(entry.fact_id for entry in entries))
        )


def _tools(
    read: _StreamRead,
    previous: tuple[PendingCall, ...],
    sid: str,
    session_dir: str,
    budget: _Budget,
    declared: project_scripts.Declarations | None = None,
) -> tuple[list[SourceEntry], list[PendingCall]]:
    stream = read.cursor.stream
    sidechain = stream != "parent"
    results = context._tool_result_blocks(read.rows, sidechain=sidechain)  # noqa: SLF001
    calls = {call.call_id: call for call in previous if call.stream == stream}
    carried = dict(calls)
    # A hook's rewrite arrives after the call it rewrites, so on a later page than a carried call.
    rewrites = context._hook_rewritten_commands(read.rows)  # noqa: SLF001
    # The carried call's facts were published from the typed command, and a rewrite can change the
    # check's title and so its fact id. The whole-file read has only the rewritten fact, so a call
    # whose command changed here is reported with the resolved calls, which makes `compare` name its
    # earlier facts as changed and send the reader back to a full read.
    rewritten: list[str] = []
    positions, result_rows, rewrite_rows = _rows_of(read.rows, sidechain)
    # Classification uses the last result block, while scheduling deliberately uses its first row.
    result_offsets = {
        call_id: read.row_cursors[index].line_start
        for index, row in enumerate(read.rows)
        for call_id in context._tool_result_blocks([row], sidechain=sidechain)  # noqa: SLF001
    }
    for call_id, call in calls.items():
        if call.name == "Bash" and call_id in rewrites:
            input_data = json.loads(call.input_json)
            if input_data.get("command") != rewrites[call_id]:
                rewritten.append(call_id)
            calls[call_id] = replace(
                call,
                input_json=json.dumps({**input_data, "command": rewrites[call_id]}),
                input_offset=read.row_cursors[rewrite_rows[call_id]].line_start,
            )
    calls.update(
        {
            call.call_id: replace(
                call,
                position=(read.row_cursors[positions[call.call_id]].line_start, number),
                input_offset=read.row_cursors[
                    rewrite_rows.get(call.call_id, positions[call.call_id])
                ].line_start,
            )
            for number, call in enumerate(_pending_calls(read.rows, stream))
        }
    )
    pending: list[PendingCall] = []
    entries: list[SourceEntry] = []
    groups: dict[int, list[PendingCall]] = {}
    for call in calls.values():
        row = positions.get(
            call.call_id, result_rows.get(call.call_id, rewrite_rows.get(call.call_id))
        )
        if row is None:
            pending.append(call)
        else:
            groups.setdefault(row, []).append(call)
    ordered = sorted(groups)
    cut = len(read.rows)
    for number, row in enumerate(ordered):
        # Classification shares the read's clock. The first row always classifies so every page
        # moves forward; at a later row the frontier moves back before it, so its call and any
        # result already read are read again rather than lost. An earlier page's call is carried.
        if number and time.monotonic() >= budget.deadline:
            cut = row
            _cut(read, row)
            pending.extend(
                carried.get(call.call_id, call)
                for later in ordered[number:]
                for call in groups[later]
                if call.call_id not in positions
            )
            break
        for call in groups[row]:
            first_entry = len(entries)
            entries.extend(
                _classify(
                    read, call, results, positions.get(call.call_id, -1), sid, session_dir, declared
                )
            )
            _outline_track_call(
                read,
                call,
                entries[first_entry:],
                results,
                positions.get(call.call_id, -1),
                sid,
                session_dir,
                declared,
            )
            read.replacements.append(
                (call.fact_ids, tuple(e.fact_id for e in entries[first_entry:]))
            )
            observed = max(
                call.input_offset, call.position[0], result_offsets.get(call.call_id, -1)
            )
            read.replacement_observations.append(observed)
            read.fact_observations.update(
                (entry.fact_id, observed) for entry in entries[first_entry:]
            )
            read.fact_positions.update(
                (entry.fact_id, (*call.position, index))
                for index, entry in enumerate(entries[first_entry:])
            )
            if call.call_id not in results:
                pending.append(
                    replace(call, fact_ids=tuple(e.fact_id for e in entries[first_entry:]))
                )
    read.result_calls = tuple(
        dict.fromkeys(
            (
                *(call_id for call_id in results if result_rows.get(call_id, 0) < cut),
                *(
                    call_id
                    for call_id in rewritten
                    if call_id not in results and rewrite_rows[call_id] < cut
                ),
            )
        )
    )
    return entries, pending


def _metadata(
    cursor: SourceCursor,
    entries: tuple[SourceEntry, ...],
    parent: _StreamRead,
    result_calls: tuple[tuple[str, str], ...] = (),
) -> SourceSnapshot:
    subjects = {subject: (fact_id, value) for subject, fact_id, value in cursor.subjects}
    subjects.update(
        {e.subject: (e.fact_id, e.result or e.fingerprint) for e in entries if e.subject}
    )
    seen = {fact_id: (fingerprint, at) for fact_id, fingerprint, at in cursor.seen}
    seen.update({e.fact_id: (e.fingerprint, e.at) for e in entries})
    all_entries = tuple((fact_id, *value) for fact_id, value in seen.items())
    messages = tuple(
        dict.fromkeys(
            (*cursor.message_ids, *(e.fact_id for e in entries if e.kind in {"person", "agent"}))
        )
    )
    cursor = replace(
        cursor,
        seen=all_entries,
        subjects=tuple((subject, *value) for subject, value in subjects.items()),
        message_ids=messages,
    )
    return SourceSnapshot(
        parent.cursor.stamp,
        parent.cursor.end_offset,
        parent.cursor.boundary_digest,
        all_entries,
        MappingProxyType(subjects),
        tuple(call.call_id for call in cursor.pending),
        cursor,
        messages,
        tuple(parent.boundaries),
        parent.verified,
        result_calls,
    )


def _stale(path: str, harness: str, sid: str, error: _SourceChangedError) -> SourcePage:
    # A refused cursor still returns enough metadata for compare to distinguish shrink/replacement.
    try:
        stamp = _stamp(os.stat(path))
    except OSError:
        return SourcePage("stale", harness, sid)
    cursor = SourceCursor(
        record_pages._identity(path, harness, sid),  # noqa: SLF001
        (StreamCursor("parent", stamp),),
    )
    parent = _StreamRead(cursor.streams[0], 0)
    parent.verified = error.verified
    return SourcePage("stale", harness, sid, snapshot=_metadata(cursor, (), parent))


def _summary_head(
    config: RuntimeConfig, path: str, budget: _Budget
) -> tuple[tuple[str, float | None], Stamp, bool]:
    """The canonical head fields, using one job-metered pass over the same bounded chunks.

    Unlike the ordinary head helpers, a clipped allowance cannot certify missing metadata.
    No source record escapes this scan; the caller retains only directory, time and version.
    """
    cwd, start = "", None
    with runtime_io._open_binary(path, follow_links=True) as handle:  # noqa: SLF001
        stamp = _stamp(os.fstat(handle.fileno()))
        for _ in range(config.claude_cwd_scan_lines):
            if budget.reason is not None:
                return (cwd, start), stamp, False
            raw = budget.line(handle, config.claude_cwd_line_bytes)
            if not raw:
                break
            if (
                len(raw) < config.claude_cwd_line_bytes
                and not raw.endswith(b"\n")
                and handle.tell() < stamp[2]
            ):
                return (cwd, start), stamp, False
            try:
                row = records.as_dict(json.loads(raw.decode("utf-8", "replace")))
            except ValueError:
                continue
            if not cwd and isinstance(row.get("cwd"), str):
                cwd = row["cwd"]
            if start is None:
                start = records.parse_ts(row.get("timestamp"))
            if cwd and start is not None:
                break
        if _stamp(os.stat(path)) != stamp:
            raise _SourceChangedError
    return (cwd, start), stamp, True


def read(  # noqa: PLR0913 - existing reader inputs plus opt-in summary classification context
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    *,
    after: SourceCursor | None = None,
    newest: bool = False,
    max_bytes: int | None = None,
    deadline: float | None = None,
    observed_writes: set[str] | None = None,
    known_head: tuple[str, float | None] | None = None,
) -> SourcePage:
    """Read owned streams in one allowance; optionally carry canonical withdrawal names.

    The opt-in set is both prior classification context and an observation sink. A collecting
    caller must reconcile its earlier facts when it grows; an ordinary cursor is unchanged.
    """
    if harness not in record_pages.HARNESSES:
        return SourcePage("unsupported", harness, sid, notes=("no paged record for this harness",))
    now = time.monotonic()
    end = now + config.session_source_page_max_seconds if deadline is None else deadline
    budget = _Budget(
        max(0, config.session_source_page_max_bytes if max_bytes is None else max_bytes),
        end,
        now + max(0.0, end - now) * (1 - config.session_source_classify_share),
    )
    identity = record_pages._identity(path, harness, sid)  # noqa: SLF001
    if after and (after.identity != identity or not after.streams):
        return SourcePage("stale", harness, sid)
    old = {stream.stream: stream for stream in after.streams} if after else {}
    try:
        parent = _read_stream(
            config, path, "parent", harness, sid, budget, old.get("parent"), newest=newest
        )
        parent.known_head = known_head
        children, unread = _read_children(config, path, harness, sid, budget, old, newest=newest)
        return replace(
            _finish(
                config,
                path,
                harness,
                sid,
                [parent, *children],
                unread,
                after,
                budget,
                observed_writes=observed_writes,
            ),
            bytes_read=budget.used,
        )
    except _SourceChangedError as error:
        return replace(_stale(path, harness, sid, error), bytes_read=budget.used)
    except OSError:
        return SourcePage("stale" if after else "unavailable", harness, sid, bytes_read=budget.used)


def _child_stream(path: str, child: str) -> str:
    subagents = os.path.join(path[: -len(".jsonl")], "subagents")
    return os.path.splitext(os.path.relpath(child, subagents))[0].replace(os.sep, "/")


def _read_children(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    budget: _Budget,
    old: dict[str, StreamCursor],
    *,
    newest: bool,
) -> tuple[list[_StreamRead], list[UnreadRegion]]:
    streams: list[_StreamRead] = []
    unread: list[UnreadRegion] = []
    children = context._admitted_subagent_paths(path, None) if harness == "claude" else []  # noqa: SLF001
    for child in sorted(children):
        # Admission accepts `subagents/` and `subagents/workflows/<wf>/`, so one agent id can
        # appear twice; the relative path keeps their fact ids and cursors apart.
        stream = _child_stream(path, child)
        try:
            child_read = _read_stream(
                config, child, stream, harness, sid, budget, old.get(stream), newest=newest
            )
            streams.append(child_read)
            if not child_read.rows and child_read.cursor.end_offset < child_read.cursor.stamp[2]:
                unread.append(
                    UnreadRegion(
                        child_read.start,
                        child_read.cursor.stamp[2],
                        "unreadable_subagent",
                        stream,
                    )
                )
        except OSError:
            unread.append(UnreadRegion(0, 0, "unreadable_subagent", stream))
    return streams, unread


def _assert_unchanged(streams: list[_StreamRead]) -> None:
    for stream in streams:
        if _stamp(os.stat(stream.path)) != stream.cursor.stamp:
            raise _SourceChangedError


def _finish(  # noqa: PLR0913 - existing reader inputs plus opt-in outline tracking
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    streams: list[_StreamRead],
    unread: list[UnreadRegion],
    after: SourceCursor | None,
    budget: _Budget,
    *,
    outline: bool = False,
    observed_writes: set[str] | None = None,
) -> SourcePage:
    parent = streams[0]
    known_head = parent.known_head
    identity = record_pages._identity(path, harness, sid)  # noqa: SLF001
    # The transcript head's directory, as the published tool report resolves written paths, since
    # a newest window may begin after a `cd`. `project_context._session_directory` cites the ruling.
    session_dir = after.session_dir if after else ""
    if known_head is not None:
        session_dir = known_head[0]
    elif not session_dir and harness == "claude":
        session_dir = context._session_directory(config, path, parent.rows)  # noqa: SLF001
    pending: list[PendingCall] = []
    groups = []
    regions: list[UnreadRegion] = []
    # The project's own check scripts, from the same read a published fact uses. A page holds only
    # its own rows, so a write on an earlier page is seen by the work tree's bytes alone.
    if outline:
        observed_writes = set()
    declared = (
        context._declared_scripts(  # noqa: SLF001
            config,
            path,
            session_dir,
            parent.rows,
            [stream.rows for stream in streams[1:]],
            prior_writes=(after.listing_writes if after else frozenset())
            | frozenset(observed_writes or ()),
            known_start=(known_head[1],) if known_head is not None else None,
            observed_writes=observed_writes,
        )
        if harness == "claude"
        else None
    )
    for stream_read in streams:
        stream_read.outline = outline
        stream_read.withdrawals = frozenset(observed_writes or ())
        tools, held = (
            _tools(stream_read, after.pending if after else (), sid, session_dir, budget, declared)
            if harness == "claude"
            else ([], [])
        )
        regions.extend(stream_read.unread)
        pending.extend(held)
        # Preserve a stream's physical order, even when its clock goes backwards. Only the
        # inter-stream merge uses call time, with the parent's next entry first at a tie.
        if stream_read.cursor.stream == "parent":
            groups.append(_in_file_order(stream_read, tools))
        else:
            groups.append(tools)
    retained_streams = {stream.cursor.stream for stream in streams}
    if after and any(stream.stream not in retained_streams for stream in after.streams):
        raise _SourceChangedError
    pending.extend(
        call for call in (after.pending if after else ()) if call.stream not in retained_streams
    )
    unread = [*regions, *unread]
    entries = tuple(heapq.merge(*groups, key=lambda entry: entry.at))
    cursor = SourceCursor(
        identity,
        tuple(s.cursor for s in streams),
        tuple(pending),
        session_dir,
        after.seen if after else (),
        after.subjects if after else (),
        after.message_ids if after else (),
        (declared.listing_writes if declared else frozenset())
        | (after.listing_writes if after else frozenset()),
    )
    notes = _CODEX_NOTES if harness == "codex" else ()
    coverage = SourceCoverage(
        not unread and all(stream.start == 0 for stream in streams),
        entries[0].fact_id if entries and (unread or parent.start) else None,
        parent.start,
        parent.cursor.end_offset,
        tuple(unread),
        "read" if harness == "claude" else "not_read",
        "read" if harness == "claude" else "not_admitted",
        notes,
    )
    # A held partial line at the end is not more to read now; `snapshot.cursor` resumes it.
    continuation = any(s.cursor.offset < s.cursor.stamp[2] for s in streams)
    _assert_unchanged(streams)
    metadata = _metadata(
        cursor,
        entries,
        parent,
        tuple(
            (stream.cursor.stream, call_id) for stream in streams for call_id in stream.result_calls
        ),
    )
    entry_ids = {entry.fact_id for entry in entries}
    return SourcePage(
        "ok",
        harness,
        sid,
        entries,
        coverage,
        metadata.cursor if continuation else None,
        metadata,
        replacements=tuple(
            replacement
            for stream in streams
            for replacement in stream.replacements
            if replacement[0]
        ),
        positions=tuple(
            (fact_id, position)
            for stream in streams
            for fact_id, position in stream.fact_positions.items()
            if fact_id in entry_ids
        ),
        observations=tuple(
            (fact_id, observed)
            for stream in streams
            for fact_id, observed in stream.fact_observations.items()
            if fact_id in entry_ids
        ),
        replacement_observations=tuple(
            observed
            for stream in streams
            for replacement, observed in zip(
                stream.replacements, stream.replacement_observations, strict=True
            )
            if replacement[0]
        ),
        head_fallback=(
            next((row["cwd"] for row in parent.rows if isinstance(row.get("cwd"), str)), None),
            context._oldest_at(parent.rows),  # noqa: SLF001
        )
        if observed_writes is not None and not outline
        else (None, None),
    )


def _in_file_order(read: _StreamRead, tools: list[SourceEntry]) -> list[SourceEntry]:
    # Timestamps can tie or run backwards; the record's physical position orders its facts.
    order = {**read.message_order, **read.tool_order}
    return sorted([*read.messages, *tools], key=lambda entry: order.get(entry.fact_id, -1))


def snapshot(page: SourcePage) -> SourceSnapshot | None:
    return page.snapshot


def _physical_change(previous: SourceSnapshot, current: SourceSnapshot) -> str | None:
    if current.stamp[:2] != previous.stamp[:2]:
        return "replaced"
    if current.stamp[2] < previous.end_offset:
        return "truncated"
    boundary = dict(current.boundaries).get(previous.end_offset)
    if current.verified_boundary and current.verified_boundary[0] == previous.end_offset:
        boundary = current.verified_boundary[1]
    if boundary is not None and boundary != previous.boundary_digest:
        return "replaced"
    return None


def compare(previous: SourceSnapshot, page: SourcePage) -> SourceChange:
    """Compare a full re-read or just its continuation, without treating display ranks as keys."""
    current = page.snapshot
    if current is None:
        raise ValueError("comparison requires a readable source snapshot")
    physical = _physical_change(previous, current)
    if physical is not None:
        return SourceChange(physical)
    if page.state != "ok":
        raise ValueError("restart a stale source before comparing its content")
    return _content_change(previous, page, current)


def _content_change(
    previous: SourceSnapshot, page: SourcePage, current: SourceSnapshot
) -> SourceChange:
    known = {fact_id: (fingerprint, at) for fact_id, fingerprint, at in previous.entries}
    newest_message = max(
        (at for fact_id, _fp, at in previous.entries if fact_id in previous.message_ids),
        default=float("-inf"),
    )
    resolved = set(current.result_calls)
    pending_ids = {fact_id for call in previous.cursor.pending for fact_id in call.fact_ids}
    changed: list[tuple[str, str]] = [
        (fact_id, "check_result")
        for call in previous.cursor.pending
        if (call.stream, call.call_id) in resolved
        for fact_id in call.fact_ids
    ]
    if page.coverage is not None and page.coverage.complete:
        # A whole read lists every check the call yields now. A carried call's fact that is not
        # among them was read from a command a hook has since rewritten to another title.
        listed = {entry.fact_id for entry in page.entries}
        changed.extend(
            (fact_id, "check_result")
            for call in previous.cursor.pending
            for fact_id in call.fact_ids
            if fact_id not in listed
        )
    appended = []
    for entry in page.entries:
        old = known.get(entry.fact_id)
        if old is not None and old[0] != entry.fingerprint:
            changed.append(
                (entry.fact_id, "check_result" if entry.fact_id in pending_ids else "content")
            )
        if old is not None:
            continue
        appended.append(entry.fact_id)
        subject = previous.subjects.get(entry.subject or "")
        if subject and subject[0] != entry.fact_id:
            if entry.kind == "file":
                changed.append((subject[0], "file_rewritten"))
            elif entry.result != subject[1]:
                changed.append((subject[0], "check_result"))
        if entry.kind in {"person", "agent"} and entry.at < newest_message:
            changed.append((entry.fact_id, "reordered"))
    return SourceChange(
        "changed_earlier" if changed else "appended" if appended else "unchanged",
        tuple(dict.fromkeys(changed)),
        tuple(appended),
    )
