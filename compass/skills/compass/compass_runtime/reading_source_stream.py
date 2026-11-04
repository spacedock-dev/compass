"""Private, resumable observations of one frozen native Claude prefix.

The endpoint is frozen by stat; its baseline is established by a later bounded
digest pass, not an atomic filesystem snapshot. Rows remain unverified until
the record pass and a final full-prefix digest agree with that baseline.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from . import io as runtime_io
from . import project_context, record_pages
from .config import (
    SESSION_SOURCE_LINE_MAX_BYTES,
    SESSION_SOURCE_PAGE_MAX_BYTES,
    SESSION_SOURCE_PAGE_MAX_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import BinaryIO

Phase = Literal["baseline", "records", "verify"]
Stamp = tuple[int, int, int, int, int]
_CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class FrozenParent:
    path: str
    harness: str
    sid: str
    identity: str
    device: int
    inode: int
    end_offset: int
    line_max_bytes: int
    modified: float = 0
    parent_path: str | None = None


@dataclass(frozen=True)
class Cursor:
    frozen: FrozenParent
    phase: Phase = "baseline"
    offset: int = 0
    digest: Any = field(default_factory=hashlib.sha256, repr=False, compare=False)
    baseline_digest: str = ""
    phase_stamp: Stamp | None = None
    line_start: int = 0
    fragment: bytes = b""
    skipping: bool = False
    has_gaps: bool = False


@dataclass(frozen=True)
class RawRecord:
    start_offset: int
    end_offset: int
    raw: bytes
    value: dict[str, Any]


@dataclass(frozen=True)
class Gap:
    start_offset: int
    end_offset: int
    reason: Literal[
        "unread", "unfinished_line", "oversized_line", "unreadable_record", "source_changed"
    ]
    permanent: bool


@dataclass(frozen=True)
class Page:
    state: Literal["progress", "verified", "limited", "stale"]
    phase: Phase
    bytes_read: int = 0
    records: tuple[RawRecord, ...] = ()
    # New permanent gaps plus the current provisional unread range, not an accumulated manifest.
    gaps: tuple[Gap, ...] = ()
    next: Cursor | None = None
    reason: Literal["", "bytes", "time", "source_changed"] = ""
    source_complete: bool = False
    verified_stamp: Stamp | None = None


def _stamp(info: os.stat_result) -> Stamp:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def freeze(
    path: str,
    harness: str,
    sid: str,
    *,
    line_max_bytes: int = SESSION_SOURCE_LINE_MAX_BYTES,
) -> Cursor:
    """Freeze identity and endpoint only; no content has been read or verified."""
    if harness != "claude" or not sid.strip():
        raise ValueError("frozen parent reading requires a Claude session")
    if type(line_max_bytes) is not int or not 0 < line_max_bytes <= SESSION_SOURCE_LINE_MAX_BYTES:
        raise ValueError("invalid raw line bound")
    path = os.path.abspath(path)
    return _freeze(path, harness, sid, line_max_bytes, None)


def _freeze(
    path: str, harness: str, sid: str, line_max_bytes: int, parent_path: str | None
) -> Cursor:
    info = os.stat(path, follow_symlinks=parent_path is None)
    if not stat.S_ISREG(info.st_mode):
        raise OSError("source is not a regular file")
    return Cursor(
        FrozenParent(
            path,
            harness,
            sid,
            record_pages._identity(path, harness, sid),  # noqa: SLF001
            info.st_dev,
            info.st_ino,
            info.st_size,
            line_max_bytes,
            info.st_mtime,
            parent_path,
        )
    )


def freeze_child(parent: Cursor, path: str) -> Cursor:
    """Freeze an admitted native child without following its final link."""
    frozen = parent.frozen
    path = os.path.abspath(path)
    if frozen.parent_path is not None or not project_context._admitted_subagent_path(  # noqa: SLF001
        frozen.path, path
    ):
        raise ValueError("source is not an admitted native child")
    child = _freeze(path, frozen.harness, frozen.sid, frozen.line_max_bytes, frozen.path)
    _check_admission(child.frozen)
    return child


def _check_admission(frozen: FrozenParent) -> None:
    if frozen.parent_path is not None and not project_context._admitted_subagent_path(  # noqa: SLF001
        frozen.parent_path, frozen.path
    ):
        raise OSError("native child path is no longer admitted")


def _owned(info: os.stat_result, frozen: FrozenParent) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and (info.st_dev, info.st_ino) == (frozen.device, frozen.inode)
        and info.st_size >= frozen.end_offset
    )


def _unread(cursor: Cursor) -> tuple[Gap, ...]:
    start = 0 if cursor.phase == "baseline" else cursor.line_start
    if cursor.phase == "verify" or start >= cursor.frozen.end_offset:
        return ()
    return (Gap(start, cursor.frozen.end_offset, "unread", False),)


def _line(cursor: Cursor, raw: bytes, rows: list[RawRecord], gaps: list[Gap]) -> Cursor:
    oversized = cursor.skipping or len(cursor.fragment) + len(raw) > cursor.frozen.line_max_bytes
    fragment = b"" if oversized else cursor.fragment + raw
    cursor = replace(cursor, fragment=fragment, skipping=oversized)
    if not raw.endswith(b"\n"):
        return cursor
    reason: Literal["oversized_line", "unreadable_record"] | None = (
        "oversized_line" if oversized else None
    )
    if reason is None:
        try:
            value = json.loads(fragment)
        except (ValueError, RecursionError):
            value = None
        if isinstance(value, dict):
            rows.append(RawRecord(cursor.line_start, cursor.offset, fragment, value))
        else:
            reason = "unreadable_record"
    if reason:
        gaps.append(Gap(cursor.line_start, cursor.offset, reason, True))
    return replace(
        cursor,
        line_start=cursor.offset,
        fragment=b"",
        skipping=False,
        has_gaps=cursor.has_gaps or reason is not None,
    )


def _consume(
    source: BinaryIO,
    cursor: Cursor,
    budget: runtime_io.ReadBudget,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[Cursor, list[RawRecord], list[Gap]]:
    rows: list[RawRecord] = []
    gaps: list[Gap] = []
    # A caller can retain/replay its prior cursor; hashing must never mutate it.
    cursor = replace(cursor, digest=cursor.digest.copy())
    source.seek(cursor.offset)
    while cursor.offset < cursor.frozen.end_offset and budget.remaining and clock() < deadline:
        size = min(_CHUNK_BYTES, budget.remaining, cursor.frozen.end_offset - cursor.offset)
        raw = source.readline(size) if cursor.phase == "records" else source.read(size)
        budget.charge(raw)
        if not raw:
            raise OSError("frozen source shortened while reading")
        cursor.digest.update(raw)
        cursor = replace(cursor, offset=cursor.offset + len(raw))
        if cursor.phase == "records":
            cursor = _line(cursor, raw, rows, gaps)
    return cursor, rows, gaps


def _finished(cursor: Cursor, gaps: list[Gap]) -> Cursor | None:
    digest = cursor.digest.hexdigest()
    if cursor.phase == "baseline":
        return replace(
            cursor,
            phase="records",
            offset=0,
            digest=hashlib.sha256(),
            baseline_digest=digest,
            phase_stamp=None,
        )
    if digest != cursor.baseline_digest:
        raise OSError("frozen prefix differs from the observed baseline")
    if cursor.phase == "verify":
        return None
    if cursor.line_start < cursor.frozen.end_offset:
        reason: Literal["oversized_line", "unfinished_line"] = (
            "oversized_line" if cursor.skipping else "unfinished_line"
        )
        gaps.append(Gap(cursor.line_start, cursor.frozen.end_offset, reason, True))
        cursor = replace(cursor, has_gaps=True)
    return replace(
        cursor,
        phase="verify",
        offset=0,
        digest=hashlib.sha256(),
        phase_stamp=None,
        line_start=cursor.frozen.end_offset,
        fragment=b"",
        skipping=False,
    )


def _checked_page(
    cursor: Cursor,
    budget: runtime_io.ReadBudget,
    deadline: float,
    clock: Callable[[], float],
) -> tuple[Cursor, list[RawRecord], list[Gap]]:
    frozen = cursor.frozen
    _check_admission(frozen)
    follow_links = frozen.parent_path is None
    info = os.stat(frozen.path, follow_symlinks=follow_links)
    if not _owned(info, frozen):
        raise OSError("frozen source replaced or truncated")
    # The unbuffered scan opener charges actual content reads without hidden
    # prefetch. Claude's parent follows links, as its existing source reader does.
    with runtime_io._open_scan_binary(frozen.path, follow_links=follow_links) as source:  # noqa: SLF001
        before = os.fstat(source.fileno())
        stamp = _stamp(before)
        if not _owned(before, frozen) or stamp != _stamp(info):
            raise OSError("source changed while opening")
        if cursor.phase != "records":
            if cursor.phase_stamp is not None and cursor.phase_stamp != stamp:
                raise OSError("source moved during digest pass")
            cursor = replace(cursor, phase_stamp=stamp)
        cursor, rows, gaps = _consume(source, cursor, budget, deadline, clock)
        _check_admission(frozen)
        if (
            _stamp(os.fstat(source.fileno())) != stamp
            or _stamp(os.stat(frozen.path, follow_symlinks=follow_links)) != stamp
        ):
            raise OSError("source moved during page read")
    return cursor, rows, gaps


def read(
    cursor: Cursor,
    *,
    max_bytes: int,
    max_seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> Page:
    """Advance one phase, charging every raw byte including both digest passes.

    Baseline and verification require stable metadata across their slices.
    Movement during either pass refuses without retry. Append present before a
    phase starts is outside the endpoint; record pages can observe later append
    between slices, with the final stable digest still required.
    """
    if type(max_bytes) is not int or not 0 <= max_bytes <= SESSION_SOURCE_PAGE_MAX_BYTES:
        raise ValueError("invalid page byte allowance")
    if (
        isinstance(max_seconds, bool)
        or not math.isfinite(max_seconds)
        or not 0 <= max_seconds <= SESSION_SOURCE_PAGE_MAX_SECONDS
    ):
        raise ValueError("invalid page time allowance")
    if not max_bytes or not max_seconds:
        return Page(
            "limited",
            cursor.phase,
            gaps=_unread(cursor),
            reason="bytes" if not max_bytes else "time",
        )
    deadline = clock() + max_seconds
    budget = runtime_io.ReadBudget(max_bytes)
    original = cursor
    frozen = cursor.frozen
    try:
        cursor, rows, gaps = _checked_page(cursor, budget, deadline, clock)
        if cursor.offset == frozen.end_offset:
            next_cursor = _finished(cursor, gaps)
            if next_cursor is None:
                return Page(
                    "verified",
                    cursor.phase,
                    budget.spent,
                    source_complete=not cursor.has_gaps,
                    verified_stamp=cursor.phase_stamp,
                )
            return Page(
                "progress",
                original.phase,
                budget.spent,
                tuple(rows),
                (*gaps, *_unread(next_cursor)),
                next_cursor,
            )
        reason: Literal["bytes", "time"] = "bytes" if not budget.remaining else "time"
        if cursor.offset == original.offset:
            return Page("limited", cursor.phase, budget.spent, gaps=_unread(cursor), reason=reason)
        return Page(
            "progress",
            cursor.phase,
            budget.spent,
            tuple(rows),
            (*gaps, *_unread(cursor)),
            cursor,
            reason,
        )
    except OSError:
        return Page(
            "stale",
            original.phase,
            budget.spent,
            gaps=(Gap(0, frozen.end_offset, "source_changed", True),),
            reason="source_changed",
        )
