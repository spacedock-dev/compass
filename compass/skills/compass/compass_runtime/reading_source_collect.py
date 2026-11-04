"""Bounded private collection of a small, fully verified native Claude corpus.

No provisional rows escape this module. Retained-object accounting includes raw
and parsed rows, cursors, containers, ancillary inputs and projection copies.
It is not a peak-RSS guarantee: bounded page/decode/tally scratch is transient.
"""

from __future__ import annotations

import copy
import math
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, is_dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from . import io as runtime_io
from . import project_context as context
from . import reading_source
from . import reading_source_inventory as inventory_source
from . import reading_source_stream as raw_source
from .config import SESSION_SOURCE_PAGE_MAX_BYTES, SESSION_SOURCE_PAGE_MAX_SECONDS

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig
    from .project_scripts import Declarations

Reason = Literal[
    "",
    "inventory",
    "source_bytes",
    "source_pages",
    "retained_bytes",
    "retained_units",
    "time",
    "cancelled",
    "no_progress",
    "source_changed",
    "source_gap",
    "native_incomplete",
]


@dataclass(frozen=True)
class Limits:
    source_bytes: int = 256 * 1024 * 1024
    prepare_ms: int = 60_000
    retained_bytes: int = 32 * 1024 * 1024
    retained_units: int = 65_536
    source_pages: int = 512

    def __post_init__(self) -> None:
        maxima = (256 * 1024 * 1024, 60_000, 32 * 1024 * 1024, 65_536, 512)
        for value, maximum in zip(vars(self).values(), maxima, strict=True):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError("invalid collection allowance")


_DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Ancillary:
    """Caller-owned frozen metadata; declarations must cover the complete corpus.

    Head/declaration acquisition belongs to the caller's separate accounting.
    CI binding is explicitly absent in this first leaf; a lazy live _CiBinding
    would perform unaccounted reads and is therefore not an accepted input.
    """

    session_dir: str
    declared: Declarations | None = None


@dataclass(frozen=True)
class KnownGap:
    stream: int
    gap: raw_source.Gap


@dataclass(frozen=True)
class Usage:
    source_bytes: int = 0
    source_pages: int = 0
    retained_bytes: int = 0
    # One unit per distinct retained Python object, not per fact or source line.
    retained_units: int = 0
    prepare_ms: float = 0


@dataclass(frozen=True)
class Collection:
    evidence: reading_source.CanonicalEvidence | None
    reason: Reason
    usage: Usage
    source_verified: bool
    verified_streams: int
    gaps: tuple[KnownGap, ...]
    inventory_gaps: tuple[inventory_source.InventoryGap, ...]
    # Whole streams are unavailable if any input/projection cannot be admitted.
    unavailable_streams: tuple[int, ...]


@dataclass(frozen=True)
class _Retained:
    inventory: inventory_source.Inventory
    ancillary: Ancillary
    # The collect call still holds its caller-supplied input while the owned
    # snapshot may grow a declaration memo during projection. Charge both.
    supplied_ancillary: Ancillary
    rows: tuple[tuple[raw_source.RawRecord, ...], ...]
    cursor: raw_source.Cursor | None = None
    gaps: tuple[KnownGap, ...] = ()
    scan: context._CheckScan | None = None
    evidence: reading_source.CanonicalEvidence | None = None


class _StopError(Exception):
    def __init__(self, reason: Reason):
        self.reason = reason


def _measure(value: Any, limits: Limits) -> tuple[int, int]:
    """Count shared retained objects once; stop measuring an inadmissible graph."""
    seen: set[int] = set()
    pending = [value]
    size = 0
    while pending:
        item = pending.pop()
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        size += sys.getsizeof(item)
        if isinstance(item, MappingProxyType):
            size += sys.getsizeof(dict(item))
        if size > limits.retained_bytes:
            raise _StopError("retained_bytes")
        if len(seen) > limits.retained_units:
            raise _StopError("retained_units")
        if is_dataclass(item) and not isinstance(item, type):
            pending.append(vars(item))
        elif isinstance(item, Mapping):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (tuple, list, set, frozenset)):
            pending.extend(item)
    return size, len(seen)


def _remaining(cursor: raw_source.Cursor, page_bytes: int) -> tuple[int, int]:
    phases = {"baseline": 3, "records": 2, "verify": 1}[cursor.phase]
    end = cursor.frozen.end_offset
    rest = end - cursor.offset
    byte_count = rest + (phases - 1) * end
    pages = max(1, math.ceil(rest / page_bytes))
    pages += (phases - 1) * max(1, math.ceil(end / page_bytes))
    return byte_count, pages


class _Collection:
    def __init__(
        self,
        config: RuntimeConfig,
        state: _Retained,
        limits: Limits,
        page_bytes: int,
        page_seconds: float,
        clock: Callable[[], float],
        cancelled: Callable[[], bool],
    ) -> None:
        self.config, self.state, self.limits = config, state, limits
        self.page_bytes, self.page_seconds = page_bytes, page_seconds
        self.clock, self.cancelled = clock, cancelled
        self.started = clock()
        self.deadline = self.started + limits.prepare_ms / 1000
        self.usage = Usage()
        self.verified = 0

    def checkpoint(self) -> None:
        if self.cancelled():
            raise _StopError("cancelled")
        if self.clock() >= self.deadline:
            raise _StopError("time")

    def accept(self, candidate: _Retained, temporary: Any = None) -> None:
        # Stage the new graph before retaining it. Include the still-held old
        # containers and the page/projection while exchanging ownership.
        size, units = _measure((self.state, candidate, temporary), self.limits)
        self.state = candidate
        self.usage = replace(
            self.usage,
            retained_bytes=max(size, self.usage.retained_bytes),
            retained_units=max(units, self.usage.retained_units),
        )
        self.checkpoint()

    def reserve(self, cursors: tuple[raw_source.Cursor, ...]) -> None:
        costs = [_remaining(cursor, self.page_bytes) for cursor in cursors]
        if sum(cost[0] for cost in costs) > self.limits.source_bytes - self.usage.source_bytes:
            raise _StopError("source_bytes")
        if sum(cost[1] for cost in costs) > self.limits.source_pages - self.usage.source_pages:
            raise _StopError("source_pages")

    def read_stream(self, index: int) -> None:
        streams = self.state.inventory.streams
        self.accept(replace(self.state, cursor=streams[index].cursor))
        while self.state.cursor is not None:
            self.checkpoint()
            cursor = self.state.cursor
            self.reserve((cursor, *(stream.cursor for stream in streams[index + 1 :])))
            page = raw_source.read(
                cursor,
                max_bytes=min(self.page_bytes, self.limits.source_bytes - self.usage.source_bytes),
                max_seconds=min(self.page_seconds, max(0, self.deadline - self.clock())),
                clock=self.clock,
            )
            self.usage = replace(
                self.usage,
                source_bytes=self.usage.source_bytes + page.bytes_read,
                source_pages=self.usage.source_pages + 1,
            )
            # Keep measured permanent gaps even when this page cannot supply rows.
            gaps = (*self.state.gaps, *(KnownGap(index, gap) for gap in page.gaps if gap.permanent))
            candidate = replace(self.state, gaps=gaps)
            self.accept(candidate)
            self.checkpoint()
            if page.state == "stale":
                raise _StopError("source_changed")
            if page.state == "limited" or (
                page.next is not None
                and (page.next.phase, page.next.offset) == (cursor.phase, cursor.offset)
            ):
                raise _StopError("no_progress")
            rows = list(self.state.rows)
            rows[index] = (*rows[index], *page.records)
            candidate = replace(self.state, rows=tuple(rows), cursor=page.next)
            self.accept(candidate, page)
            if page.state == "verified":
                if not page.source_complete or self.state.gaps:
                    raise _StopError("source_gap")
                self.verified += 1
            elif page.next is None:
                raise _StopError("no_progress")

    def materialize(self) -> None:
        self.checkpoint()
        streams = self.state.inventory.streams
        rows = self.state.rows
        parent = [row.value for row in rows[0]]
        children = [[row.value for row in child] for child in rows[1:]]
        read_ids = {context._child_id(stream.cursor.frozen.path) for stream in streams[1:]}  # noqa: SLF001
        if any(not child for child in children) or context._named_agent_ids(parent) - read_ids:  # noqa: SLF001
            raise _StopError("native_incomplete")
        reads = tuple(
            (
                stream.cursor.frozen.path,
                runtime_io.TranscriptRead(
                    tuple(row.raw for row in native),
                    stream.cursor.frozen.end_offset,
                    stream.cursor.frozen.end_offset,
                    0,
                    True,
                ),
            )
            for stream, native in zip(streams, rows, strict=True)
        )
        ancillary = self.state.ancillary
        scan = context._CheckScan(  # noqa: SLF001
            parent,
            children,
            0,
            None,
            False,
            False,
            False,
            runtime_io.ReadBudget(self.limits.source_bytes, self.usage.source_bytes),
            reads,
            ancillary.session_dir,
            ancillary.declared,
            None,
        )
        self.accept(replace(self.state, scan=scan))
        self.checkpoint()
        frozen = streams[0].cursor.frozen
        evidence = reading_source.from_complete_scan(self.config, scan, frozen.harness, frozen.sid)
        self.checkpoint()
        self.accept(replace(self.state, evidence=evidence))

    def prepare(self) -> None:
        self.checkpoint()
        self.accept(self.state)
        self.accept(replace(self.state, ancillary=copy.deepcopy(self.state.ancillary)))
        if not self.state.inventory.complete or not self.state.inventory.streams:
            raise _StopError("inventory")
        self.reserve(tuple(stream.cursor for stream in self.state.inventory.streams))

    def run(self) -> Collection:
        reason: Reason = ""
        try:
            self.prepare()
            for index in range(len(self.state.inventory.streams)):
                self.read_stream(index)
            self.materialize()
            self.checkpoint()
        except _StopError as exc:
            reason = exc.reason
        complete = self.verified == len(self.state.inventory.streams) and bool(self.verified)
        return Collection(
            self.state.evidence if not reason else None,
            reason,
            replace(self.usage, prepare_ms=max(0, (self.clock() - self.started) * 1000)),
            complete and self.state.inventory.complete and not self.state.gaps,
            self.verified,
            self.state.gaps,
            self.state.inventory.gaps,
            tuple(range(len(self.state.inventory.streams))) if reason else (),
        )


def collect(
    config: RuntimeConfig,
    inventory: inventory_source.Inventory,
    *,
    ancillary: Ancillary,
    limits: Limits = _DEFAULT_LIMITS,
    page_bytes: int = 1024 * 1024,
    page_seconds: float = 0.25,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
) -> Collection:
    """Collect once, without retries or partial canonical proof.

    Reserve all three passes before I/O and recheck remaining page reservations
    after each slice. Known raw gaps survive; unknown inventory remains unknown.
    Words exist only in this call's private native state and returned evidence.
    """
    if type(page_bytes) is not int or not 0 < page_bytes <= SESSION_SOURCE_PAGE_MAX_BYTES:
        raise ValueError("invalid collection page bytes")
    if (
        isinstance(page_seconds, bool)
        or not math.isfinite(page_seconds)
        or not 0 < page_seconds <= SESSION_SOURCE_PAGE_MAX_SECONDS
    ):
        raise ValueError("invalid collection page seconds")
    return _Collection(
        config,
        _Retained(inventory, ancillary, ancillary, tuple(() for _ in inventory.streams)),
        limits,
        page_bytes,
        page_seconds,
        clock,
        cancelled,
    ).run()
