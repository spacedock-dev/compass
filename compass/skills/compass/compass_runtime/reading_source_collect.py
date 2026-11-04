"""Bounded private collection of a fully verified native Claude corpus.

No provisional rows escape this module. Retained-object accounting includes raw
and parsed rows, cursors, containers, ancillary inputs and projection copies.
It is not a peak-RSS guarantee: bounded page/decode/tally scratch is transient.
"""

from __future__ import annotations

import copy
import math
import os
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, is_dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from . import io as runtime_io
from . import project_context as context
from . import (
    project_scripts,
    reader_checks,
    reading_source,
    reading_source_final,
    reading_source_words,
)
from . import reading_source_inventory as inventory_source
from . import reading_source_stream as raw_source
from .config import SESSION_SOURCE_PAGE_MAX_BYTES, SESSION_SOURCE_PAGE_MAX_SECONDS

if TYPE_CHECKING:
    from _thread import LockType
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
    "canonical_limit",
]


@dataclass(frozen=True)
class Limits:
    """Collector defaults/maxima, not an implicit long-reading plan declaration.

    The 256-MiB retained graph admits raw and parsed native corpora beyond 64 MiB
    together with their private proof/word state. It does not cap process RSS.
    Callers may supply smaller ceilings; the other resource bounds are unchanged.
    """

    source_bytes: int = 256 * 1024 * 1024
    prepare_ms: int = 60_000
    retained_bytes: int = 256 * 1024 * 1024
    retained_units: int = 65_536
    source_pages: int = 512

    def __post_init__(self) -> None:
        maxima = (256 * 1024 * 1024, 60_000, 256 * 1024 * 1024, 65_536, 512)
        for value, maximum in zip(vars(self).values(), maxima, strict=True):
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError("invalid collection allowance")


_DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class AncillaryInfo:
    """Private acquisition status/counts, not measured git/kernel byte I/O.

    At most one starting cwd is loaded, with the existing project-script file,
    script and five-second git-family caps and reader listing's 64-KiB cap.
    CI remains explicitly unavailable until the frozen-binding leaf.
    """

    origin: Literal["supplied", "acquired"] = "supplied"
    project_scripts: Literal["supplied", "available", "unavailable", "disabled"] = "supplied"
    ci_binding: Literal["unavailable"] = "unavailable"
    project_loads: int = 0
    reader_loads: int = 0


@dataclass(frozen=True)
class Ancillary:
    """Caller-owned frozen metadata; declarations must cover the complete corpus.

    Explicitly supplied head/declaration acquisition belongs to the caller.
    Omitting Ancillary requests bounded acquisition from retained native rows.
    CI binding is explicitly absent in this leaf; a lazy live _CiBinding
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
class VerifiedStream:
    """Private observed prefix identity, digest and successful verification version."""

    frozen: raw_source.FrozenParent
    baseline_digest: str
    stamp: raw_source.Stamp


@dataclass
class _SnapshotAccount:
    limits: Limits
    usage: Usage
    page_bytes: int
    page_seconds: float
    final_stamp: raw_source.Stamp
    # Reserve the original collection high-water graph while its caller may
    # still hold the returned evidence. Revalidation scratch is metered on top.
    retained_base_bytes: int = 0
    retained_base_units: int = 0
    lock: LockType = field(default_factory=threading.Lock, repr=False, compare=False)


@dataclass(frozen=True)
class Snapshot:
    """Private in-process proof, never a serialized capability or word cache.

    Successors share accounting with their ancestors. Reusing an old handle,
    including after failure, cannot reset consumed preparation or I/O budgets.
    """

    streams: tuple[VerifiedStream, ...]
    account: _SnapshotAccount


@dataclass(frozen=True)
class Revalidation:
    snapshot: Snapshot | None
    reason: Reason
    usage: Usage
    # Source-version validity only, never a new strict-final or all-agent proof.
    final_valid: bool


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
    words: tuple[reading_source_words.MessageWords, ...] | None = None
    final: dict[str, Any] | None = None
    snapshot: Snapshot | None = None
    ancillary_info: AncillaryInfo = AncillaryInfo()


@dataclass(frozen=True)
class _Retained:
    inventory: inventory_source.Inventory
    ancillary: Ancillary | None
    # The collect call still holds its caller-supplied input while the owned
    # snapshot may grow a declaration memo during projection. Charge both.
    supplied_ancillary: Ancillary | None
    rows: tuple[tuple[raw_source.RawRecord, ...], ...]
    cursor: raw_source.Cursor | None = None
    gaps: tuple[KnownGap, ...] = ()
    scan: context._CheckScan | None = None
    evidence: reading_source.CanonicalEvidence | None = None
    words: reading_source_words.Join | None = None
    parent_stamp: raw_source.Stamp | None = None
    final: reading_source_final.Proof | None = None
    proofs: tuple[VerifiedStream, ...] = ()
    snapshot: Snapshot | None = None
    ancillary_info: AncillaryInfo = AncillaryInfo()


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
            candidate = replace(
                self.state,
                rows=tuple(rows),
                cursor=page.next,
                parent_stamp=page.verified_stamp
                if index == 0 and page.state == "verified"
                else self.state.parent_stamp,
            )
            self.accept(candidate, page)
            if page.state == "verified":
                if not page.source_complete or self.state.gaps:
                    raise _StopError("source_gap")
                if page.verified_stamp is None or not cursor.baseline_digest:
                    raise _StopError("source_gap")
                proof = VerifiedStream(cursor.frozen, cursor.baseline_digest, page.verified_stamp)
                self.accept(replace(self.state, proofs=(*self.state.proofs, proof)))
                self.verified += 1
            elif page.next is None:
                raise _StopError("no_progress")

    def reserve_time(self, seconds: float) -> None:
        self.checkpoint()
        if self.deadline - self.clock() < seconds:
            raise _StopError("time")

    def acquire_ancillary(
        self, parent: list[dict[str, Any]], children: list[list[dict[str, Any]]]
    ) -> None:
        self.checkpoint()
        # The whole verified native parent is in physical order: no clipped-tail
        # fallback or head reread is needed to recover its first cwd/stamp.
        began_in = next(
            (row["cwd"] for row in parent if isinstance(row.get("cwd"), str) and row["cwd"]), ""
        )
        if not os.path.isabs(began_in) or "\x00" in began_in:
            began_in = ""
        start = context._oldest_at(parent)  # noqa: SLF001
        info = replace(
            self.state.ancillary_info,
            project_scripts="unavailable" if self.config.git_probe_enabled else "disabled",
        )
        self.accept(replace(self.state, ancillary_info=info, ancillary=Ancillary(began_in)))
        loaded = None
        if self.config.git_probe_enabled and began_in and start is not None:
            self.checkpoint()
            # Reserve the entire existing git-family timeout before invoking it.
            # Cache hits may be cheaper; they do not justify a smaller reservation.
            self.reserve_time(project_scripts.GIT_TIMEOUT_SEC)
            before_load = self.state
            info = replace(info, project_loads=1)
            try:
                self.accept(replace(self.state, ancillary_info=info))
                self.reserve_time(project_scripts.GIT_TIMEOUT_SEC)
            except _StopError:
                # No acquisition started: restore the already measured old graph.
                self.state = before_load
                raise
            loaded = project_scripts.load(began_in, start)
            self.checkpoint()
            self.accept(replace(self.state, ancillary=Ancillary(began_in, loaded)))
            # The shared project cache must not receive projection memo mutations.
            loaded = copy.deepcopy(loaded)
            info = replace(
                info, project_scripts="available" if loaded and loaded.files else "unavailable"
            )
            self.accept(
                replace(self.state, ancillary=Ancillary(began_in, loaded), ancillary_info=info)
            )
        entries: tuple[str, ...] = ()
        if began_in:
            self.checkpoint()
            info = replace(info, reader_loads=1)
            self.accept(replace(self.state, ancillary_info=info))
            entries = reader_checks.for_project(self.config, began_in, context.listed_entry_refusal)
            self.checkpoint()
            self.accept(self.state, entries)
        declared = context._declared_from_inputs(  # noqa: SLF001
            began_in, parent, children, loaded, entries
        )
        self.checkpoint()
        self.accept(replace(self.state, ancillary=Ancillary(began_in, declared)), entries)

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
        if self.state.ancillary is None:
            self.acquire_ancillary(parent, children)
        ancillary = self.state.ancillary
        if ancillary is None:
            raise _StopError("native_incomplete")
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
        # Every projected candidate needs at least one new retained object.
        # This is only a necessary ceiling; the full graph is measured below.
        allowance = max(0, self.limits.retained_units - self.usage.retained_units)
        try:
            evidence = reading_source.from_complete_scan(
                self.config,
                scan,
                frozen.harness,
                frozen.sid,
                listed_cap=allowance,
                require_complete=True,
            )
        except context.ToolReportLimitError as exc:
            raise _StopError("canonical_limit") from exc
        self.checkpoint()
        self.accept(replace(self.state, evidence=evidence))

    def prove_final(self) -> None:
        self.checkpoint()
        evidence = self.state.evidence
        if evidence is None:
            raise _StopError("native_incomplete")
        parent = self.state.inventory.streams[0].cursor.frozen
        proof = reading_source_final.build(
            self.config,
            parent,
            self.state.rows[0],
            evidence.facts,
            stamp=self.state.parent_stamp,
            checkpoint=self.checkpoint,
        )
        self.accept(replace(self.state, final=proof))

    def join_words(self) -> None:
        self.checkpoint()
        evidence = self.state.evidence
        if evidence is None:
            raise _StopError("native_incomplete")
        parent = self.state.inventory.streams[0].cursor.frozen
        join = reading_source_words.Join.begin(
            evidence.facts,
            parent,
            unfit_final=self.state.final.unfit if self.state.final is not None else None,
        )
        self.accept(replace(self.state, words=join))
        rows = self.state.rows[0]
        # G2 observes newest physical records first; queued messages still bind
        # their own typing time rather than the absorption time.
        for position in reversed(range(len(rows))):
            self.checkpoint()
            candidate = join.observe(self.config, rows[position], position)
            self.checkpoint()
            # Ignored rows and identical duplicates retain exactly the same
            # join. Rewalking the whole corpus for them makes this pass quadratic.
            if candidate is not join:
                self.accept(replace(self.state, words=candidate))
                join = candidate
        for key in join.identities:
            self.checkpoint()
            candidate = join.materialize(self.config, key, rows)
            self.accept(replace(self.state, words=candidate))
            join = candidate

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
            self.prove_final()
            self.join_words()
            self.checkpoint()
            if self.state.final is not None:
                parent = self.state.inventory.streams[0].cursor.frozen
                checked = self.state.final.recheck(parent)
                if checked is not self.state.final:
                    self.accept(replace(self.state, final=checked))
            self.checkpoint()
            account = _SnapshotAccount(
                self.limits,
                self.usage,
                self.page_bytes,
                self.page_seconds,
                self.state.proofs[0].stamp,
            )
            self.accept(replace(self.state, snapshot=Snapshot(self.state.proofs, account)))
            account.usage = replace(
                self.usage, prepare_ms=max(0, (self.clock() - self.started) * 1000)
            )
            account.retained_base_bytes = self.usage.retained_bytes
            account.retained_base_units = self.usage.retained_units
            self.checkpoint()
        except _StopError as exc:
            reason = exc.reason
        complete = self.verified == len(self.state.inventory.streams) and bool(self.verified)
        usage = replace(self.usage, prepare_ms=max(0, (self.clock() - self.started) * 1000))
        if not reason and self.state.snapshot is not None:
            self.state.snapshot.account.usage = usage
        return Collection(
            self.state.evidence if not reason else None,
            reason,
            usage,
            complete and self.state.inventory.complete and not self.state.gaps,
            self.verified,
            self.state.gaps,
            self.state.inventory.gaps,
            tuple(range(len(self.state.inventory.streams))) if reason else (),
            self.state.words.results if not reason and self.state.words is not None else None,
            self.state.final.result if not reason and self.state.final is not None else None,
            self.state.snapshot if not reason else None,
            self.state.ancillary_info,
        )


def collect(
    config: RuntimeConfig,
    inventory: inventory_source.Inventory,
    *,
    ancillary: Ancillary | None = None,
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
    Without supplied ancillary inputs, declaration acquisition uses only retained
    native head/rows. Native source_bytes excludes bounded ancillary file/git
    work; ancillary_info records acquisition counts and unavailable CI binding.
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
        _Retained(
            inventory,
            ancillary,
            ancillary,
            tuple(() for _ in inventory.streams),
            ancillary_info=AncillaryInfo(origin="acquired", project_scripts="unavailable")
            if ancillary is None
            else AncillaryInfo(),
        ),
        limits,
        page_bytes,
        page_seconds,
        clock,
        cancelled,
    ).run()


def _snapshot_stamp(proof: VerifiedStream) -> raw_source.Stamp:
    frozen = proof.frozen
    raw_source._check_admission(frozen)  # noqa: SLF001
    info = os.stat(frozen.path, follow_symlinks=frozen.parent_path is None)
    if not raw_source._owned(info, frozen) or info.st_size < proof.stamp[2]:  # noqa: SLF001
        raise OSError("verified source replaced or shortened")
    raw_source._check_admission(frozen)  # noqa: SLF001
    return raw_source._stamp(info)  # noqa: SLF001


class _Revalidation:
    def __init__(
        self, snapshot: Snapshot, clock: Callable[[], float], cancelled: Callable[[], bool]
    ) -> None:
        self.snapshot, self.account = snapshot, snapshot.account
        self.clock, self.cancelled = clock, cancelled
        self.started = clock()
        self.deadline = (
            self.started
            + max(0, self.account.limits.prepare_ms - self.account.usage.prepare_ms) / 1000
        )
        self.proofs: tuple[VerifiedStream, ...] = ()

    def checkpoint(self) -> None:
        if self.cancelled():
            raise _StopError("cancelled")
        if self.clock() >= self.deadline:
            raise _StopError("time")

    def measure(self, temporary: Any = None) -> None:
        account = self.account
        # Conservative reservation of the original accepted collection graph,
        # plus the actual distinct validation objects held during exchange.
        limits = replace(
            account.limits,
            retained_bytes=max(0, account.limits.retained_bytes - account.retained_base_bytes),
            retained_units=max(0, account.limits.retained_units - account.retained_base_units),
        )
        size, units = _measure((self.snapshot, self.proofs, temporary), limits)
        account.usage = replace(
            account.usage,
            retained_bytes=max(account.usage.retained_bytes, account.retained_base_bytes + size),
            retained_units=max(account.usage.retained_units, account.retained_base_units + units),
        )
        self.checkpoint()

    def verify(self, proof: VerifiedStream) -> VerifiedStream:
        cursor = raw_source.Cursor(
            proof.frozen,
            phase="verify",
            baseline_digest=proof.baseline_digest,
            line_start=proof.frozen.end_offset,
        )
        while True:
            self.checkpoint()
            account = self.account
            remaining_bytes, remaining_pages = _remaining(cursor, account.page_bytes)
            if remaining_bytes > account.limits.source_bytes - account.usage.source_bytes:
                raise _StopError("source_bytes")
            if remaining_pages > account.limits.source_pages - account.usage.source_pages:
                raise _StopError("source_pages")
            self.measure(cursor)
            page = raw_source.read(
                cursor,
                max_bytes=min(
                    account.page_bytes, account.limits.source_bytes - account.usage.source_bytes
                ),
                max_seconds=min(account.page_seconds, max(0, self.deadline - self.clock())),
                clock=self.clock,
            )
            account.usage = replace(
                account.usage,
                source_bytes=account.usage.source_bytes + page.bytes_read,
                source_pages=account.usage.source_pages + 1,
            )
            self.checkpoint()
            self.measure((cursor, page))
            if page.state == "stale":
                raise _StopError("source_changed")
            if page.state == "verified":
                if not page.source_complete or page.verified_stamp is None or page.gaps:
                    raise _StopError("source_gap")
                return replace(proof, stamp=page.verified_stamp)
            if (
                page.state != "progress"
                or page.next is None
                or page.next.offset <= cursor.offset
                or page.next.phase != "verify"
                or page.gaps
            ):
                raise _StopError("no_progress")
            cursor = page.next

    def check_versions(self) -> None:
        # Reobserve after the last stream: narrower races, not an atomic snapshot.
        for proof in self.proofs:
            self.checkpoint()
            if _snapshot_stamp(proof) != proof.stamp:
                raise _StopError("source_changed")
            self.checkpoint()

    def run(self) -> Revalidation:
        reason: Reason = ""
        updated = None
        final_valid = False
        try:
            self.checkpoint()
            self.measure()
            for proof in self.snapshot.streams:
                self.checkpoint()
                stamp = _snapshot_stamp(proof)
                self.checkpoint()
                checked = proof if stamp == proof.stamp else self.verify(proof)
                candidate = (*self.proofs, checked)
                self.measure(candidate)
                self.proofs = candidate
            self.check_versions()
            candidate_snapshot = Snapshot(self.proofs, self.account)
            self.measure(candidate_snapshot)
            updated = candidate_snapshot
            final_valid = self.proofs[0].stamp == self.account.final_stamp
            self.checkpoint()
        except OSError:
            reason = "source_changed"
        except _StopError as exc:
            reason = exc.reason
        self.account.usage = replace(
            self.account.usage,
            prepare_ms=self.account.usage.prepare_ms + max(0, (self.clock() - self.started) * 1000),
        )
        if not reason and self.account.usage.prepare_ms >= self.account.limits.prepare_ms:
            reason = "time"
        return Revalidation(
            updated if not reason else None, reason, self.account.usage, final_valid and not reason
        )


def revalidate(
    snapshot: Snapshot,
    *,
    clock: Callable[[], float] = time.monotonic,
    cancelled: Callable[[], bool] = lambda: False,
) -> Revalidation:
    """Check the same frozen inventory, charging its original shared allowance.

    Unchanged admitted versions need no content reads. Metadata movement needs
    one stable old-prefix digest, never a new baseline or three new passes.
    Preparation time accumulates across calls; time spent between calls belongs
    to the caller's separate job deadline. No current-final proof survives a
    parent version change. Concurrent or reentrant calls on one lineage refuse
    through its shared lock.
    """
    if not isinstance(snapshot, Snapshot) or not snapshot.streams:
        raise ValueError("a verified collection snapshot is required")
    if not snapshot.account.lock.acquire(blocking=False):
        raise ValueError("snapshot revalidation is already active")
    try:
        return _Revalidation(snapshot, clock, cancelled).run()
    finally:
        snapshot.account.lock.release()
