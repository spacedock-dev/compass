"""Bounded, memory-only source collection for a server-owned summary job.

Source pages are scan boundaries, not model windows. Resolve carried calls before merging
the streams and handing one coherent view to the producer. No source words are persisted here.
"""

from __future__ import annotations

import heapq
import sys
import time
from collections.abc import Mapping
from dataclasses import is_dataclass, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from . import session_source as source

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig


def _size(value: Any, seen: set[int] | None = None) -> int:
    """Account shared Python objects once, including cursor fragments and pending inputs."""
    if seen is None:
        seen = set()
    identity = id(value)
    if identity in seen:
        return 0
    seen.add(identity)
    total = sys.getsizeof(value)
    if is_dataclass(value) and not isinstance(value, type):
        return total + _size(vars(value), seen)
    if isinstance(value, Mapping):
        if isinstance(value, MappingProxyType):
            # The proxy's sizeof omits the table it owns through its wrapped dictionary.
            total += sys.getsizeof(dict(value))
        return total + sum(_size(k, seen) + _size(v, seen) for k, v in value.items())
    if isinstance(value, (tuple, list, set, frozenset)):
        return total + sum(_size(item, seen) for item in value)
    return total


class _Collection:
    def __init__(self, harness: str, sid: str) -> None:
        self.harness, self.sid = harness, sid
        self.streams: dict[str, dict[str, source.SourceEntry]] = {}
        self.unread: list[source.UnreadRegion] = []
        self.boundaries: dict[int, str] = {}
        self.result_calls: set[tuple[str, str]] = set()
        self.positions: dict[str, tuple[int, int, int]] = {}
        self.page: source.SourcePage | None = None

    def with_page(self, page: source.SourcePage) -> _Collection:
        candidate = _Collection(self.harness, self.sid)
        candidate.streams = {key: dict(entries) for key, entries in self.streams.items()}
        candidate.unread = list(self.unread)
        candidate.boundaries = dict(self.boundaries)
        candidate.result_calls = set(self.result_calls)
        candidate.positions = dict(self.positions)
        candidate.add(page)
        return candidate

    def add(self, page: source.SourcePage) -> None:
        if page.snapshot is None or page.coverage is None:
            raise ValueError("Collection requires a readable source page")
        current = {entry.fact_id: entry for entry in page.entries}
        self.positions.update(page.positions)
        replaced: set[str] = set()
        replacements = {
            old_id: (old_ids, new_ids)
            for old_ids, new_ids in page.replacements
            for old_id in old_ids
        }
        # One pass over retained entries, even when a page resolves thousands of calls.
        for stream, entries in self.streams.items():
            kept: dict[str, source.SourceEntry] = {}
            handled: set[tuple[str, ...]] = set()
            for fact_id, entry in entries.items():
                replacement = replacements.get(fact_id)
                if replacement is None:
                    kept[fact_id] = entry
                    continue
                old_ids, new_ids = replacement
                if old_ids not in handled:
                    kept.update((fact, current[fact]) for fact in new_ids if fact in current)
                    replaced.update(new_ids)
                    handled.add(old_ids)
            self.streams[stream] = kept
        for entry in page.entries:
            if entry.fact_id in replaced:
                continue
            self.streams.setdefault(entry.stream, {})[entry.fact_id] = entry
        for old_ids, new_ids in page.replacements:
            for fact_id in set(old_ids) - set(new_ids):
                self.positions.pop(fact_id, None)
        # A page's limiting tail is provisional. Only bytes subsequently read may clear it;
        # skipped lines and unknown unread extents remain gaps.
        self.unread = _unread(self.unread, page)
        self.boundaries.update(page.snapshot.boundaries)
        self.result_calls.update(page.snapshot.result_calls)
        self.page = page

    def finish(self, reason: str = "") -> source.SourcePage:
        page = self.page
        if page is None or page.snapshot is None or page.coverage is None:
            return source.SourcePage(
                "unavailable",
                self.harness,
                self.sid,
                coverage=source.SourceCoverage(
                    False,
                    None,
                    0,
                    0,
                    (source.UnreadRegion(0, 0, reason or "source-unavailable"),),
                    "read",
                    "read",
                ),
            )
        order = sorted(self.streams, key=lambda name: (name != "parent", name))
        entries = tuple(
            heapq.merge(
                *(
                    sorted(
                        self.streams[name].values(), key=lambda entry: self.positions[entry.fact_id]
                    )
                    for name in order
                ),
                key=lambda entry: entry.at,
            )
        )
        unread = list(self.unread)
        if reason:
            unread.extend(
                source.UnreadRegion(stream.end_offset, stream.stamp[2], reason, stream.stream)
                for stream in page.snapshot.cursor.streams
            )
        coverage = replace(
            page.coverage,
            complete=not unread,
            starts_at=entries[0].fact_id if entries and unread else None,
            start_offset=0,
            unread=tuple(dict.fromkeys(unread)),
        )
        metadata = tuple((entry.fact_id, entry.fingerprint, entry.at) for entry in entries)
        subjects = {
            entry.subject: (entry.fact_id, entry.result or entry.fingerprint)
            for entry in entries
            if entry.subject
        }
        messages = tuple(entry.fact_id for entry in entries if entry.kind in {"person", "agent"})
        cursor = replace(
            page.snapshot.cursor,
            seen=metadata,
            subjects=tuple((key, *value) for key, value in subjects.items()),
            message_ids=messages,
        )
        snapshot = replace(
            page.snapshot,
            entries=metadata,
            subjects=MappingProxyType(subjects),
            message_ids=messages,
            cursor=cursor,
            boundaries=tuple(self.boundaries.items()),
            result_calls=tuple(sorted(self.result_calls)),
        )
        return replace(
            page,
            entries=entries,
            coverage=coverage,
            snapshot=snapshot,
            next=cursor if page.next is not None else None,
            positions=tuple((entry.fact_id, self.positions[entry.fact_id]) for entry in entries),
        )


def _unread(
    previous: list[source.UnreadRegion], page: source.SourcePage
) -> list[source.UnreadRegion]:
    if page.snapshot is None or page.coverage is None:
        raise ValueError("Coverage requires a readable source page")
    frontiers = {stream.stream: stream for stream in page.snapshot.cursor.streams}
    unread = []
    for region in previous:
        remaining = region
        frontier = frontiers.get(region.stream)
        if region.reason in {"bytes", "time", "unreadable_subagent"} and frontier:
            if region.end_offset > region.start_offset:
                if frontier.end_offset >= region.end_offset:
                    continue
                remaining = replace(
                    region, start_offset=max(region.start_offset, frontier.end_offset)
                )
            elif not any(gap.stream == region.stream for gap in page.coverage.unread):
                continue
        unread.append(remaining)
    return list(dict.fromkeys((*unread, *page.coverage.unread)))


def _limit(
    remaining: int | None, end: float, check: Callable[[], str], clock: Callable[[], float]
) -> str:
    return check() or (
        "source_time"
        if clock() >= end
        else "source_bytes"
        if remaining is not None and remaining <= 0
        else ""
    )


def _head(
    config: RuntimeConfig, path: str, harness: str, end: float
) -> tuple[tuple[str, float | None] | None, source.Stamp | None, int, str]:
    if harness != "claude":
        return None, None, 0, ""
    budget = source._Budget(config.session_summary_source_max_bytes, end, end)  # noqa: SLF001
    try:
        head, stamp, complete = source._summary_head(config, path, budget)  # noqa: SLF001
    except ValueError:
        return None, None, budget.used, "source_changed"
    except OSError:
        return None, None, budget.used, "source-unavailable"
    if not complete:
        return None, None, budget.used, "source_time" if time.monotonic() >= end else "source_bytes"
    if _size((head, stamp)) > config.session_summary_source_max_memory_bytes:
        return None, None, budget.used, "source_memory"
    return head, stamp, budget.used, ""


def _fallback_head(
    head: tuple[str, float | None] | None,
    fallback: tuple[str | None, float | None],
    observed: tuple[str | None, float | None],
) -> tuple[tuple[str | None, float | None], tuple[str, float | None] | None]:
    fallback = (
        fallback[0] if fallback[0] is not None else observed[0],
        fallback[1] if fallback[1] is not None else observed[1],
    )
    return fallback, (
        (head[0] or fallback[0] or "", head[1] if head[1] is not None else fallback[1])
        if head is not None
        else None
    )


def collect(  # noqa: C901, PLR0915 - one job budget owns every restart and admission gate
    config: RuntimeConfig,
    path: str,
    harness: str,
    sid: str,
    *,
    deadline: float,
    check: Callable[[], str],
    progress: Callable[[source.SourcePage, int], None],
    clock: Callable[[], float] = time.monotonic,
) -> tuple[source.SourcePage, str]:
    collection = _Collection(harness, sid)
    after = None
    remaining = config.session_summary_source_max_bytes
    end = min(deadline, clock() + config.session_summary_source_max_seconds)
    reason = _limit(remaining, end, check, clock)
    withdrawals: set[str] = set()
    restart_stamps: tuple[tuple[str, source.Stamp], ...] = ()
    known_head: tuple[str, float | None] | None = None
    head_stamp: source.Stamp | None = None
    if not reason:
        known_head, head_stamp, used, reason = _head(config, path, harness, end)
        remaining -= used
    prefix_head = known_head
    fallback_head: tuple[str | None, float | None] = (None, None)
    while not reason:
        reason = _limit(remaining, end, check, clock)
        if reason:
            break
        observed = set(withdrawals)
        page = source.read(
            config,
            path,
            harness,
            sid,
            after=after,
            max_bytes=min(remaining, config.session_source_page_max_bytes),
            deadline=min(end, clock() + config.session_source_page_max_seconds),
            observed_writes=observed,
            known_head=known_head,
        )
        remaining -= page.bytes_read
        if page.state != "ok" or page.snapshot is None:
            reason = "source_changed" if page.state == "stale" else "source-unavailable"
            break
        stamps = tuple((stream.stream, stream.stamp) for stream in page.snapshot.cursor.streams)
        if (head_stamp is not None and page.snapshot.stamp != head_stamp) or (
            restart_stamps and stamps != restart_stamps
        ):
            reason = "source_changed"
            break
        head_stamp = None
        restart_stamps = ()
        fallback_head, next_head = _fallback_head(prefix_head, fallback_head, page.head_fallback)
        head_changed = next_head != known_head
        known_head = next_head
        if head_changed or (observed != withdrawals and collection.page is not None):
            # A later write can withdraw or restore earlier canonical facts, even in another
            # stream. Discard that classification and replay under the monotone union. Reads,
            # verification and reduction retain this job's remaining allowance and deadline.
            # No obsolete prefix survives a resource/cancellation stop during reconciliation.
            collection = _Collection(harness, sid)
            after = None
            withdrawals = observed
            restart_stamps = stamps
            if _size(
                (withdrawals, restart_stamps, page, known_head, prefix_head, fallback_head)
            ) > (config.session_summary_source_max_memory_bytes):
                reason = "source_memory"
                break
            del page
            continue
        # Build the candidate separately: exceeding retention must not lose the accepted prefix.
        candidate = collection.with_page(page)
        completed = candidate.finish()
        graph = (
            vars(collection),
            vars(candidate),
            completed,
            observed,
            withdrawals,
            known_head,
            prefix_head,
            fallback_head,
        )
        if _size(graph) > config.session_summary_source_max_memory_bytes:
            reason = "source_memory"
            break
        collection = candidate
        withdrawals = observed
        del graph
        reason = _limit(None, end, check, clock)
        if reason:
            break
        progress(completed, config.session_summary_source_max_bytes - remaining)
        if page.next is None:
            return replace(
                completed, bytes_read=config.session_summary_source_max_bytes - remaining
            ), ""
        if after is not None and page.next.streams == after.streams:
            reason = (
                "source_bytes"
                if remaining <= 0
                else "source_time"
                if clock() >= end
                else "source_stalled"
            )
            break
        after = page.next
        del candidate, completed
    return replace(
        collection.finish(reason), bytes_read=config.session_summary_source_max_bytes - remaining
    ), reason
