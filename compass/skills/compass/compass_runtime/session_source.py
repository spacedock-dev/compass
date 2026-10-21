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
from dataclasses import asdict, dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import observer, record_pages, records, transcripts
from . import project_context as context

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import BinaryIO

    from .config import RuntimeConfig


Stamp = tuple[int, int, int, int]
HARNESSES = record_pages.HARNESSES


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


@dataclass(frozen=True)
class SourceChange:
    kind: str
    changed: tuple[tuple[str, str], ...] = ()
    appended: tuple[str, ...] = ()


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

    @property
    def reason(self) -> str | None:
        if time.monotonic() >= self.scan_deadline:
            return "time"
        return "bytes" if self.remaining <= 0 else None

    def line(self, source: BinaryIO, count: int) -> bytes:
        raw = source.readline(min(count, max(0, self.remaining)))
        self.remaining -= len(raw)
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
    """
    if len(title) < cap:
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


def _consume(
    config: RuntimeConfig,
    source: BinaryIO,
    read: _StreamRead,
    budget: _Budget,
    harness: str,
    sid: str,
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


def _rows_of(rows: list[dict[str, Any]], sidechain: bool) -> tuple[dict[str, int], dict[str, int]]:
    """The first row holding each call, and the first row holding each call's result."""
    calls: dict[str, int] = {}
    results: dict[str, int] = {}
    for index, row in enumerate(rows):
        for _at, _cwd, call_id, _name, _input, _worker in context._claude_tool_uses(  # noqa: SLF001
            [row], sidechain=sidechain
        ):
            calls.setdefault(call_id, index)
        for call_id in context._tool_result_blocks([row], sidechain=sidechain):  # noqa: SLF001
            results.setdefault(call_id, index)
    return calls, results


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
) -> list[SourceEntry]:
    stream = read.cursor.stream
    tally = context._ToolReportTally(results, session_dir)  # noqa: SLF001
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
    # own id, and two checks in one call that share a title (`cd a && pytest; cd b && pytest`)
    # derive the same published fact id. The source keeps one run per title in the call on the
    # call id, chosen as the published `_latest` chooses, and gives every other run a segment id,
    # so no two source entries share an id; the run left on a segment id has no published entry.
    foreground = sorted(
        (
            (run["segment"], identity, run)
            for identity, runs in tally.runs.items()
            for run in runs
            if not run["background"]
        ),
        key=lambda item: item[0],
    )
    by_title: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for segment, _identity, run in foreground:
        by_title.setdefault(run["title"], []).append((segment, run))
    kept = {
        history[tally._latest([run for _segment, run in history])][0]  # noqa: SLF001
        for history in by_title.values()
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


def _tools(
    read: _StreamRead,
    previous: tuple[PendingCall, ...],
    sid: str,
    session_dir: str,
    budget: _Budget,
) -> tuple[list[SourceEntry], list[PendingCall]]:
    stream = read.cursor.stream
    sidechain = stream != "parent"
    results = context._tool_result_blocks(read.rows, sidechain=sidechain)  # noqa: SLF001
    calls = {call.call_id: call for call in previous if call.stream == stream}
    calls.update({call.call_id: call for call in _pending_calls(read.rows, stream)})
    positions, result_rows = _rows_of(read.rows, sidechain)
    pending: list[PendingCall] = []
    entries: list[SourceEntry] = []
    groups: dict[int, list[PendingCall]] = {}
    for call in calls.values():
        row = positions.get(call.call_id, result_rows.get(call.call_id))
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
                call
                for later in ordered[number:]
                for call in groups[later]
                if call.call_id not in positions
            )
            break
        for call in groups[row]:
            first_entry = len(entries)
            entries.extend(
                _classify(read, call, results, positions.get(call.call_id, -1), sid, session_dir)
            )
            if call.call_id not in results:
                pending.append(
                    replace(call, fact_ids=tuple(e.fact_id for e in entries[first_entry:]))
                )
    read.result_calls = tuple(call_id for call_id in results if result_rows.get(call_id, 0) < cut)
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


def read(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    *,
    after: SourceCursor | None = None,
    newest: bool = False,
    max_bytes: int | None = None,
    deadline: float | None = None,
) -> SourcePage:
    """Read complete JSONL lines in file order, sharing one allowance across owned streams."""
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
        children, unread = _read_children(config, path, harness, sid, budget, old, newest=newest)
        return _finish(config, path, harness, sid, [parent, *children], unread, after, budget)
    except _SourceChangedError as error:
        return _stale(path, harness, sid, error)
    except OSError:
        return SourcePage("stale" if after else "unavailable", harness, sid)


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
    subagents = os.path.join(path[: -len(".jsonl")], "subagents")
    for child in sorted(children):
        # Admission accepts `subagents/` and `subagents/workflows/<wf>/`, so one agent id can
        # appear twice; the relative path keeps their fact ids and cursors apart.
        stream = os.path.splitext(os.path.relpath(child, subagents))[0].replace(os.sep, "/")
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


def _finish(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    streams: list[_StreamRead],
    unread: list[UnreadRegion],
    after: SourceCursor | None,
    budget: _Budget,
) -> SourcePage:
    parent = streams[0]
    identity = record_pages._identity(path, harness, sid)  # noqa: SLF001
    # The transcript head's directory, as the published tool report resolves written paths, since
    # a newest window may begin after a `cd`. `project_context._session_directory` cites the ruling.
    session_dir = after.session_dir if after else ""
    if not session_dir and harness == "claude":
        session_dir = context._session_directory(config, path, parent.rows)  # noqa: SLF001
    pending: list[PendingCall] = []
    groups = []
    regions: list[UnreadRegion] = []
    for stream_read in streams:
        tools, held = (
            _tools(stream_read, after.pending if after else (), sid, session_dir, budget)
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
    )
    notes = (
        ("codex_agent_words_not_admitted", "codex_checks_and_files_not_admitted")
        if harness == "codex"
        else ()
    )
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
    return SourcePage(
        "ok",
        harness,
        sid,
        entries,
        coverage,
        metadata.cursor if continuation else None,
        metadata,
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
