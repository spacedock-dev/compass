"""Bounded private collection of a fully verified native Claude corpus.

No provisional rows escape this module. Retained-object accounting includes raw
and parsed rows, cursors, containers, ancillary inputs and projection copies.
It is not a peak-RSS guarantee: bounded page/decode/tally scratch is transient.
"""

from __future__ import annotations

import copy
import math
import os
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, is_dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Literal

from . import (
    ci_read,
    project_scripts,
    reader_checks,
    reading_source,
    reading_source_final,
    reading_source_words,
)
from . import io as runtime_io
from . import project_context as context
from . import reading_source_inventory as inventory_source
from . import reading_source_stream as raw_source
from .config import SESSION_SOURCE_PAGE_MAX_BYTES, SESSION_SOURCE_PAGE_MAX_SECONDS

if TYPE_CHECKING:
    from _thread import LockType
    from collections.abc import Callable, Iterator

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
    "message_limit",
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
_CI_BINDING_TYPE = context._CiBinding  # noqa: SLF001 - owned graph type, not a lazy factory


@dataclass(frozen=True)
class AncillaryInfo:
    """Private acquisition status/counts, not measured git/kernel byte I/O.

    At most one starting cwd is loaded, with the existing project-script file,
    script and five-second git-family caps and reader listing's 64-KiB cap.
    Historical CI freezes at most four remote cwd values, each under the
    configured git-probe timeout. Supplied ancillary inputs do not request CI
    probing unless current_ci_goals explicitly opts into acquisition.
    """

    origin: Literal["supplied", "acquired"] = "supplied"
    project_scripts: Literal["supplied", "available", "unavailable", "disabled"] = "supplied"
    ci_binding: Literal["unavailable", "available", "disabled", "unknown"] = "unavailable"
    project_loads: int = 0
    reader_loads: int = 0
    remote_probes: int = 0


@dataclass(frozen=True)
class CurrentCiInputs:
    """Private bounded input to a later authorized CI read, not a CI result.

    The frozen local commit is an acquisition observation, not a claim that
    Git HEAD remains unchanged. Native stream proofs do not revalidate Git.
    """

    state: Literal["ready", "unbound", "no-folder", "no-commit", "disabled", "unknown"]
    goal_texts: tuple[str, ...]
    links: tuple[tuple[str, int], ...]
    pushes: tuple[str, ...]
    folder: str
    session_head: str
    remote: tuple[str, str]
    binding: ci_read.Binding | None
    caution: bool


@dataclass(frozen=True)
class Ancillary:
    """Caller-owned frozen metadata; declarations must cover the complete corpus.

    Explicitly supplied head/declaration acquisition belongs to the caller.
    Omitting Ancillary requests bounded acquisition from retained native rows.
    Supplied inputs retain absent CI binding by default; current_ci_goals can
    explicitly request bounded acquisition. A lazy live _CiBinding would
    perform unaccounted reads and is therefore not an accepted input.
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
class RecordPosition:
    """One verified raw record in frozen parent-first stream order, not clock order."""

    stream: int
    record: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class PhysicalOrigin:
    """Private canonical association; unknown positions must never use a clock fallback.

    One row per unchanged canonical fact. Known rows sort by stream, start_offset
    and canonical_index, preserving existing canonical ties within one raw call.
    No paths, words or native call IDs are carried in this metadata.
    """

    fact_id: str
    canonical_index: int
    position: RecordPosition | None = None
    reason: str = "missing"


_OriginKey = tuple[bool, str, str]  # launch namespace, canonical worker, original call ID


def _origin_key(fact: dict[str, Any]) -> _OriginKey:
    branch = fact.get("branch")
    record_id = branch.get("record_id") if isinstance(branch, dict) else None
    return fact.get("subject") == "launch", str(fact.get("worker_kind") or ""), str(record_id or "")


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
    origins: tuple[PhysicalOrigin, ...] | None = None
    recovered_sources: tuple[Mapping[str, Any], ...] | None = None
    current_ci: CurrentCiInputs | None = None


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
    goal_texts: tuple[str, ...] = ()
    ci_records: tuple[tuple[tuple[str, int], ...], tuple[str, ...]] = ((), ())
    current_ci_goals: tuple[str, ...] | None = None
    ci_session_head: str = ""
    ci_remotes: tuple[tuple[str, tuple[str, str]], ...] = ()
    origin_calls: dict[_OriginKey, RecordPosition | None] = field(default_factory=dict)
    origins: tuple[PhysicalOrigin, ...] | None = None
    recovered_sources: tuple[Mapping[str, Any], ...] | None = None
    current_ci: CurrentCiInputs | None = None


@dataclass(frozen=True, eq=False)
class _RequestProof(Mapping[str, Any]):
    """Recursively immutable mapping; native/final input snapshots can copy it safely."""

    _data: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __deepcopy__(self, _memo: dict[int, Any]) -> _RequestProof:
        return self


def _freeze_request_proof(value: Any) -> Any:
    """Own a deeply immutable copy of the existing JSON-shaped source proof."""
    if isinstance(value, dict):
        return _RequestProof(
            MappingProxyType({key: _freeze_request_proof(item) for key, item in value.items()})
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_request_proof(item) for item in value)
    return value


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
        if isinstance(item, _CI_BINDING_TYPE) or (
            is_dataclass(item) and not isinstance(item, type)
        ):
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
    def __init__(  # noqa: PLR0913 - original resource controls plus the injected Git runner
        self,
        config: RuntimeConfig,
        state: _Retained,
        limits: Limits,
        page_bytes: int,
        page_seconds: float,
        clock: Callable[[], float],
        cancelled: Callable[[], bool],
        ci_remote_limit: int,
        *,
        ci_probe_runner: Callable[..., Any],
    ) -> None:
        self.config, self.state, self.limits = config, state, limits
        self.ci_remote_limit = ci_remote_limit
        self.ci_probe_runner = ci_probe_runner
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

    def ci_rows(self) -> Iterator[dict[str, Any]]:
        rows = self.state.rows[0]
        end = self.state.inventory.streams[0].cursor.frozen.end_offset
        floor = max(0, end - ci_read.SCAN_BYTES)
        for row in reversed(rows):
            self.checkpoint()
            # The legacy reverse window drops its leading carry at a nonzero
            # floor, including a row beginning exactly there.
            if floor and row.start_offset <= floor:
                break
            yield row.value
            self.checkpoint()

    def freeze_ci(self, scan: context._CheckScan) -> context._CheckScan:
        self.checkpoint()
        recorded = ci_read.records_from_rows(self.ci_rows())
        self.accept(replace(self.state, ci_records=recorded))
        info = replace(
            self.state.ancillary_info,
            ci_binding="available" if self.config.git_probe_enabled else "disabled",
        )
        self.accept(replace(self.state, ancillary_info=info))
        if self.config.git_probe_enabled:
            self.acquire_remotes(scan)
        binding = context._CiBinding.frozen(  # noqa: SLF001
            self.config, self.state.goal_texts, recorded, dict(self.state.ci_remotes)
        )
        updated = scan._replace(ci_binding=binding)
        self.accept(replace(self.state, scan=updated))
        return updated

    def ci_directories(self, scan: context._CheckScan) -> Iterator[str]:
        # Canonical placed poll runs include child polls and shell cd/wrapper
        # rules. Temporary tally scratch is bounded by the admitted native input.
        if self.state.current_ci_goals is not None:
            yield scan.session_dir
        tally = context._tally_from_scan(scan)  # noqa: SLF001
        self.checkpoint()
        for history in tally.commands.values():
            for run in history:
                self.checkpoint()
                poll = run.get("ci_poll")
                if poll is None or not poll.valid:
                    continue
                yield scan.session_dir
                if (
                    not poll.repository
                    and run["cwd"]
                    and os.path.normpath(run["cwd"]) != os.path.normpath(scan.session_dir)
                ):
                    yield run["cwd"]

    def acquire_remotes(self, scan: context._CheckScan) -> None:
        directories: list[str] = []
        unknown = False
        for cwd in self.ci_directories(scan):
            if not cwd or not os.path.isabs(cwd) or "\x00" in cwd:
                unknown = True
            elif cwd not in directories:
                if len(directories) >= self.ci_remote_limit:
                    unknown = True
                else:
                    directories.append(cwd)
        self.accept(self.state, directories)
        for cwd in directories:
            # probe_session owns two sequential Git calls (HEAD, then origin).
            seconds = self.config.git_probe_timeout_sec * (
                2 if self.state.current_ci_goals is not None else 1
            )
            self.reserve_time(seconds)
            before_probe = self.state
            info = replace(
                self.state.ancillary_info,
                remote_probes=self.state.ancillary_info.remote_probes + 1,
            )
            try:
                self.accept(replace(self.state, ancillary_info=info), directories)
                self.reserve_time(seconds)
            except _StopError:
                self.state = before_probe
                raise
            session_head = self.state.ci_session_head
            if self.state.current_ci_goals is None:
                remote = ci_read.folder_remote(self.config, cwd)
            else:
                found = ci_read.probe_session(self.config, cwd, runner=self.probe_git)
                if cwd == scan.session_dir:
                    session_head = found.head if found is not None else ""
                remote = (found.host, found.repository) if found is not None else ("", "")
            self.checkpoint()
            unknown |= not bool(remote[1])
            self.accept(
                replace(
                    self.state,
                    ci_remotes=(*self.state.ci_remotes, (cwd, remote)),
                    ci_session_head=session_head,
                ),
                directories,
            )
        if unknown:
            self.accept(
                replace(
                    self.state,
                    ancillary_info=replace(self.state.ancillary_info, ci_binding="unknown"),
                )
            )

    def probe_git(self, *args: Any, **kwargs: Any) -> Any:
        # The existing owner supplies the unchanged finite timeout for each call.
        self.reserve_time(self.config.git_probe_timeout_sec)
        result = self.ci_probe_runner(*args, **kwargs)
        self.checkpoint()
        return result

    def freeze_current_ci(self) -> None:
        goals = self.state.current_ci_goals
        if goals is None:
            return
        self.checkpoint()
        scan, evidence = self.state.scan, self.state.evidence
        if scan is None or evidence is None:
            raise _StopError("native_incomplete")
        folder = scan.session_dir
        session_head = self.state.ci_session_head
        links, pushes = self.state.ci_records
        remote = dict(self.state.ci_remotes).get(folder, ("", ""))
        binding = ci_read.bind(goals, links, pushes, remote)
        state: Literal["ready", "unbound", "no-folder", "no-commit", "disabled", "unknown"]
        if not self.config.git_probe_enabled:
            state = "disabled"
        elif not folder:
            state = "no-folder"
        elif folder not in dict(self.state.ci_remotes):
            state = "unknown"
        elif not session_head:
            state = "no-commit"
        elif binding is None:
            state = "unbound"
        else:
            state = "ready"
        written = (
            str(fact.get("summary") or "")
            for fact in evidence.facts
            if fact.get("type") == "tool_report" and fact.get("subject") == "write"
        )
        inputs = CurrentCiInputs(
            state,
            goals,
            links,
            pushes,
            folder,
            session_head,
            remote,
            binding,
            ci_read.changed_ci_configuration(written),
        )
        self.checkpoint()
        self.accept(replace(self.state, current_ci=inputs))

    def admit_messages(self) -> None:
        # All parent rows are verified, but no message projection or redaction
        # has run. Whole-corpus refusal preserves original canonical identities.
        for row in self.state.rows[0]:
            self.checkpoint()
            oversized = context._ordinary_message_over_limit(row.value)  # noqa: SLF001
            self.checkpoint()
            if oversized:
                raise _StopError("message_limit")

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
        if self.state.supplied_ancillary is None or self.state.current_ci_goals is not None:
            scan = self.freeze_ci(scan)
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

    def locate_origins(self) -> None:
        evidence, words = self.state.evidence, self.state.words
        if evidence is None or words is None:
            raise _StopError("native_incomplete")
        # Temporary inventory is bounded by admitted native inputs and wanted
        # canonical IDs; accept meters it together with raw/projection/word state.
        self.checkpoint()
        wanted = {_origin_key(fact) for fact in evidence.facts if fact.get("branch")}
        self.checkpoint()
        calls: dict[_OriginKey, RecordPosition | None] = {}
        for stream, rows in enumerate(self.state.rows):
            worker = context.SUBAGENT_WORKER if stream else ""
            launch_stream = f"{worker}:{stream - 1}" if stream else ""
            for number, row in enumerate(rows):
                self.checkpoint()
                native = context._claude_tool_uses([row.value], sidechain=bool(stream))  # noqa: SLF001
                for _at, _cwd, call_id, _name, _input, _worker in native:
                    self.checkpoint()
                    qualified = context._launch_record_id(call_id, launch_stream)  # noqa: SLF001
                    for key in ((False, worker, call_id), (True, worker, qualified)):
                        if key in wanted:
                            calls[key] = (
                                None
                                if key in calls
                                else RecordPosition(
                                    stream, number, row.start_offset, row.end_offset
                                )
                            )
                self.checkpoint()
        self.accept(replace(self.state, origin_calls=calls), temporary=wanted)
        origins = []
        for index, fact in enumerate(evidence.facts):
            self.checkpoint()
            origins.append(self.origin_for(fact, index))
            self.checkpoint()
        self.accept(replace(self.state, origins=tuple(origins)), temporary=(wanted, origins))

    def origin_for(self, fact: dict[str, Any], index: int) -> PhysicalOrigin:
        origin = PhysicalOrigin(fact["fact_id"], index)
        parent = self.state.inventory.streams[0].cursor.frozen
        if fact.get("source_session") != {"harness": parent.harness, "sid": parent.sid}:
            return replace(origin, reason="source")
        if fact.get("type") in {"user_message", "agent_message"}:
            return self.message_origin(fact, origin)
        key = _origin_key(fact)
        if key not in self.state.origin_calls:
            return origin
        position = self.state.origin_calls[key]
        return replace(origin, position=position, reason="" if position else "ambiguous")

    def message_origin(self, fact: dict[str, Any], origin: PhysicalOrigin) -> PhysicalOrigin:
        join = self.state.words
        if join is None:
            return origin
        key = fact["fact_id"], fact["at"]
        if key in join.refused:
            return replace(origin, reason=join.refused[key])
        number = join.positions.get(key)
        if number is None:
            return origin
        row = self.state.rows[0][number]
        return replace(
            origin, position=RecordPosition(0, number, row.start_offset, row.end_offset), reason=""
        )

    def recover_requests(self) -> None:
        self.checkpoint()
        parent = self.state.inventory.streams[0].cursor.frozen

        def read(consume: Callable[[bytes], None]) -> None:
            # Match the existing bounded reader's newest physical record first.
            # The owner handles line separators, raw digests, caps and ambiguity.
            for row in reversed(self.state.rows[0]):
                self.checkpoint()
                consume(row.raw)
                self.checkpoint()

        facts = context._transcript_user_scan(  # noqa: SLF001
            self.config, b"", parent.harness, parent.sid, goal_choices=False, read=read
        )
        self.checkpoint()
        frozen = tuple(_freeze_request_proof(fact) for fact in facts)
        self.checkpoint()
        self.accept(replace(self.state, recovered_sources=frozen), temporary=facts)

    def prepare(self) -> None:
        self.checkpoint()
        self.accept(self.state)
        for text in self.state.current_ci_goals or ():
            self.checkpoint()
            if not isinstance(text, str):
                raise TypeError("current CI goals must be a frozen string tuple")
        self.checkpoint()
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
            self.admit_messages()
            self.materialize()
            self.freeze_current_ci()
            self.prove_final()
            self.join_words()
            self.locate_origins()
            self.recover_requests()
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
            self.state.origins if not reason else None,
            self.state.recovered_sources if not reason else None,
            self.state.current_ci if not reason else None,
        )


def collect(  # noqa: PLR0913 - explicit input and whole-job/per-page controls
    config: RuntimeConfig,
    inventory: inventory_source.Inventory,
    *,
    ancillary: Ancillary | None = None,
    goal_texts: tuple[str, ...] = (),
    ci_remote_limit: int = 4,
    current_ci_goals: tuple[str, ...] | None = None,
    ci_probe_runner: Callable[..., Any] = subprocess.run,
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
    work; ancillary_info records acquisition counts and CI binding availability.
    goal_texts must be genuine caller goal/line inputs, never cached readings.
    current_ci_goals separately opts into frozen inputs for a later CI read;
    None requests none. Supply only genuine current goal texts, not goal lines
    or cached readings. Git acquisition is timed/counted, not native byte I/O.
    """
    if current_ci_goals is not None and not isinstance(current_ci_goals, tuple):
        raise TypeError("current CI goals must be a frozen string tuple")
    if type(ci_remote_limit) is not int or not 0 <= ci_remote_limit <= 4:
        raise ValueError("invalid historical CI remote allowance")
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
            goal_texts=goal_texts,
            current_ci_goals=current_ci_goals,
        ),
        limits,
        page_bytes,
        page_seconds,
        clock,
        cancelled,
        ci_remote_limit,
        ci_probe_runner=ci_probe_runner,
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
