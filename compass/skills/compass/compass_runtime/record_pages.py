"""Stateless backward pages of a session's already publishable message titles."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from . import project_context

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import BinaryIO

    from .config import RuntimeConfig

KINDS = ("user_message", "agent_message")
HARNESSES = frozenset({"claude", "codex"})
CURSOR_MAX_CHARS = 1024
# The page loads this many entries on opening a session (`RECORD_PAGE_SIZE` in
# frontend/src/transport/record.ts); the drift view merges the same first page, so the two are one.
PAGE_SIZE = 50
_CURSOR = re.compile(r"[A-Za-z0-9_-]+")


def page_limit(raw: str) -> int:
    """Clamp a query integer without decoding an unbounded integer magnitude."""
    value = raw.strip()
    negative = value.startswith("-")
    digits = value[1:] if value[:1] in {"+", "-"} else value
    if not digits or not digits.isascii() or not digits.isdecimal():
        raise ValueError("limit must be an integer")
    magnitude = digits.lstrip("0") or "0"
    count = PAGE_SIZE if len(magnitude) > 2 else int(magnitude)
    return max(1, min(-count if negative else count, PAGE_SIZE))


def empty(harness: str, sid: str, state: str) -> dict[str, Any]:
    """An unread source cannot establish that the record's start was reached."""
    return {
        "session": {"harness": harness, "sid": sid},
        "entries": [],
        "next": None,
        "reached_start": False,
        "bound": None,
        "scanned_bytes": 0,
        "kinds": list(KINDS),
        "state": state,
    }


def _encode(value: list[Any], key: bytes) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw + hmac.digest(key, raw, "sha256")).decode().rstrip("=")


def _decode(cursor: str, key: bytes) -> list[Any] | None:
    if not cursor or len(cursor) > CURSOR_MAX_CHARS or not _CURSOR.fullmatch(cursor):
        return None
    try:
        packed = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        raw, signature = packed[:-32], packed[-32:]
        if not hmac.compare_digest(signature, hmac.digest(key, raw, "sha256")):
            return None
        value = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    # Refuse alternate encodings as well as unmeasured or negative offsets.
    if not isinstance(value, list) or len(value) != 8 or _encode(value, key) != cursor:
        return None
    if not all(type(n) is int and 0 <= n <= (1 << 64) - 1 for n in value[1:7]):
        return None
    return value if isinstance(value[0], str) and type(value[7]) is bool else None


def _identity(path: str, harness: str, sid: str) -> str:
    return hashlib.sha256(f"{os.path.abspath(path)}\0{harness}\0{sid}".encode()).hexdigest()


def _same_file(info: os.stat_result, device: int, inode: int, size: int, mtime: int) -> bool:
    return (
        (info.st_dev, info.st_ino) == (device, inode)
        and info.st_size >= size
        and (info.st_size > size or info.st_mtime_ns == mtime)
    )


def _fact(
    config: RuntimeConfig, raw: bytes, harness: str, sid: str, *, title_only: bool = False
) -> dict[str, Any] | None:
    """The message fact one line holds, or None.

    `title_only` stops short of masking the whole message text, which only the press reads. The
    fact id hashes the title and never that text, so the id is the same either way, and the
    fixed-number index, which runs on every collection, must not pay for a 256 KiB single-word
    message the way a page may.
    """
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    event = project_context._instruction_event(config, record, harness, sid)  # noqa: SLF001
    kind, fact_type = "steer", "user_message"
    if event is None:
        event = project_context._agent_message_event(  # noqa: SLF001
            config,
            record,
            harness,
            sid,
            **({} if title_only else {"text_cap": len(raw)}),
        )
        kind, fact_type = "agent_say", "agent_message"
    if event is None:
        return None
    return project_context._semantic_fact_from_event(event, kind, fact_type, "")  # noqa: SLF001


@dataclass
class _Scan:
    position: int
    resume: int
    discard: bool
    scanned: int = 0
    bound: str | None = None
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    skipped: bool = False
    # Asked after each visited line, with whether a region has been skipped so far. A press that
    # knows when it has read enough ends the scan; one that cannot trust a gap learns of it here.
    stop: Callable[[bool], bool] | None = None


def _take_lines(
    config: RuntimeConfig,
    scan: _Scan,
    pending: bytes,
    harness: str,
    sid: str,
    limit: int,
    deadline: float,
    visit: Callable[[bytes], None] | None = None,
) -> tuple[bytes, bool]:
    while pending:
        boundary = pending.rfind(b"\n")
        if boundary < 0 and scan.position:
            break
        if time.monotonic() >= deadline:
            scan.bound = "time"
            return pending, True
        start = scan.position + boundary + 1
        raw, pending = pending[boundary + 1 :], pending[: max(boundary, 0)]
        scan.resume = start
        if scan.discard:
            scan.discard = False
        elif visit is not None:
            if raw:
                visit(raw)
                if scan.stop is not None and scan.stop(scan.skipped):
                    return pending, True
        else:
            fact = _fact(config, raw, harness, sid) if raw else None
            if fact is not None:
                scan.entries.setdefault(str(fact["fact_id"]), fact)
        if limit and len(scan.entries) == limit:
            return pending, True
    return pending, False


@dataclass
class _Held:
    """Chunks read before the pending line with no line boundary in them, newest read last.

    Joining each one as it was read re-copied a growing partial line every time, so a single 20 MiB
    line cost 1.8 s and a 65 MiB line spent a 5-second clock at 33 MiB. They are joined once, when a
    boundary or the start arrives. The pending line holds no newline whenever a chunk is read.
    """

    chunks: list[bytes] = field(default_factory=list)
    size: int = 0

    def add(self, chunk: bytes) -> None:
        self.chunks.append(chunk)
        self.size += len(chunk)

    def join(self, chunk: bytes, pending: bytes) -> bytes:
        joined = chunk + b"".join(reversed(self.chunks)) + pending
        self.clear()
        return joined

    def clear(self) -> None:
        self.chunks, self.size = [], 0


def _skip_oversized(
    scan: _Scan, visit: Callable[[bytes], None] | None, held: _Held, pending: bytes
) -> bytes:
    """A press gets a larger total allowance than a page, not an unbounded single JSON line.

    Its remainder is skipped through the next delimiter, and what was held for it is dropped.
    """
    if visit is None or held.size + len(pending) < 16 * 1024 * 1024:
        return pending
    scan.discard = True
    scan.skipped = True
    held.clear()
    return b""


def _read_chunk(source: BinaryIO, scan: _Scan, count: int, held: _Held, pending: bytes) -> bytes:
    """Read the chunk before the scan position; hold it unless it brings a boundary or the start."""
    scan.position -= count
    source.seek(scan.position)
    chunk = source.read(count)
    scan.scanned += len(chunk)
    if len(chunk) != count:
        raise OSError("source changed during record scan")
    if scan.position and b"\n" not in chunk:
        held.add(chunk)
        return pending
    return held.join(chunk, pending)


def _scan(
    config: RuntimeConfig,
    source: BinaryIO,
    scan: _Scan,
    harness: str,
    sid: str,
    limit: int,
    visit: Callable[[bytes], None] | None = None,
    deadline: float | None = None,
) -> None:
    deadline = (
        deadline if deadline is not None else time.monotonic() + config.record_page_max_seconds
    )
    pending = b""
    held = _Held()
    initial_end = scan.position
    while scan.position or pending:
        if time.monotonic() >= deadline:
            scan.bound = "time"
            return
        available = config.record_page_max_bytes - scan.scanned
        if not available and scan.position:
            scan.bound = "bytes"
            # Retry a boundary-straddling record with a fresh allowance. A line
            # larger than a whole allowance must instead be discarded through
            # its next delimiter, or an image would trap Show more forever.
            if scan.resume == initial_end:
                scan.resume = scan.position
                scan.discard = True
            return
        count = min(scan.position, config.record_page_chunk_bytes, available)
        if count:
            pending = _read_chunk(source, scan, count, held, pending)
        if not held.size:
            pending, stopped = _take_lines(
                config, scan, pending, harness, sid, limit, deadline, visit
            )
            if stopped:
                return
        pending = _skip_oversized(scan, visit, held, pending)
        if not scan.position:
            scan.resume = 0
            return


@dataclass(frozen=True)
class SourceScan:
    """Measured coverage of a press-only read, with no retained source words."""

    state: str
    scanned_bytes: int = 0
    reached_start: bool = False
    bound: str | None = None
    stamp: tuple[int, int, int, int] | None = None
    skipped: bool = False
    start: int = 0


def scan_source(
    config: RuntimeConfig,
    path: str,
    visit: Callable[[bytes], None],
    *,
    max_bytes: int,
    deadline: float,
    end: int | None = None,
    expected_stamp: tuple[int, int, int, int] | None = None,
    stop: Callable[[bool], bool] | None = None,
) -> SourceScan:
    """Share page boundaries and chunk reads, but require an unchanged file.

    `stop` is asked after each visited line, with whether a region has been skipped so far, and
    ends the scan early; the caller owns why, since the scan reports only its own bounds.

    Directions inspect the whole allowance after a match, so another copy of
    the identity in that coverage can still refuse it. No cursor or cache.
    """
    scan: _Scan | None = None
    try:
        with open(path, "rb") as source:
            info = os.fstat(source.fileno())
            device, inode, size, mtime, _, _ = _cursor_position(info, None, "")
            stamp = (device, inode, size, mtime)
            if expected_stamp is not None and expected_stamp != stamp:
                return SourceScan("stale")
            position = min(size, end) if end is not None else size
            discard = False
            boundary_bytes = 0
            if position and position < size:
                source.seek(position - 1)
                discard = source.read(1) != b"\n"
                boundary_bytes = 1
            scan = _Scan(position, position, discard, scanned=boundary_bytes, stop=stop)
            bounded = replace(config, record_page_max_bytes=max_bytes)
            _scan(bounded, source, scan, "", "", 0, visit, deadline)
            after = os.stat(path)
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != stamp:
                return SourceScan("stale", scan.scanned)
    except (OSError, ValueError):
        return SourceScan(
            "stale" if scan is not None else "unavailable", scan.scanned if scan else 0
        )
    return SourceScan(
        "ok", scan.scanned, scan.resume == 0, scan.bound, stamp, scan.skipped, scan.resume
    )


def _cursor_position(
    info: os.stat_result, cursor: list[Any] | None, identity: str
) -> tuple[int, int, int, int, int, bool]:
    if not stat.S_ISREG(info.st_mode):
        raise OSError("record source is not a regular file")
    device, inode, size, mtime = info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
    end, discard = size, False
    if cursor is not None:
        owner, device, inode, size, mtime, end, version, discard = cursor
        if (
            owner != identity
            or version != 1
            or end > size
            or not _same_file(info, device, inode, size, mtime)
        ):
            raise ValueError("stale record cursor")
    return device, inode, info.st_size, info.st_mtime_ns, end, discard


def read(
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    *,
    cursor_key: bytes,
    limit: int = 50,
    before: str | None = None,
) -> dict[str, Any]:
    """Read only this page; retain no transcript or page across requests.

    The byte cursor binds a snapshot end, so appends never shift older pages.
    Same-size edits, truncation and replacement require the reader to restart.
    """
    result = empty(harness, sid, "ok")
    if harness not in HARNESSES:
        return {**result, "state": "unsupported"}
    identity = _identity(path, harness, sid)
    cursor = _decode(before, cursor_key) if before is not None else None
    if before is not None and cursor is None:
        return {**result, "state": "stale"}
    scan: _Scan | None = None
    try:
        with open(path, "rb") as source:
            device, inode, size, mtime, end, discard = _cursor_position(
                os.fstat(source.fileno()), cursor, identity
            )
            scan = _Scan(end, end, discard)
            _scan(config, source, scan, harness, sid, max(1, min(limit, 50)))
            after = os.stat(path)
            if not _same_file(after, device, inode, size, mtime):
                return {**result, "state": "stale", "scanned_bytes": scan.scanned}
    except ValueError:
        return {**result, "state": "stale"}
    except OSError:
        return {
            **result,
            "state": "stale" if scan is not None or before is not None else "unavailable",
            "scanned_bytes": scan.scanned if scan is not None else 0,
        }
    reached_start = scan.resume == 0
    entries = sorted(scan.entries.values(), key=lambda fact: (-float(fact["at"]), fact["fact_id"]))
    return dict(
        project_context.for_page(
            {
                **result,
                "entries": entries,
                "reached_start": reached_start,
                "next": None
                if reached_start
                else _encode(
                    [
                        identity,
                        device,
                        inode,
                        after.st_size,
                        after.st_mtime_ns,
                        scan.resume,
                        1,
                        scan.discard,
                    ],
                    cursor_key,
                ),
                "bound": scan.bound if not reached_start and len(entries) < limit else None,
                "scanned_bytes": scan.scanned,
            }
        )
    )
