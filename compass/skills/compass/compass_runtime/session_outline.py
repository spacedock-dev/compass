"""Compass's deterministic grouping of a focused session's bounded record."""

from __future__ import annotations

import hashlib
import math
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, is_dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from . import observer, session_source, session_summary
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence

    from .config import RuntimeConfig
    from .state import RuntimeState


@dataclass(frozen=True, slots=True)
class _FactLimits:
    bytes: int = 8 * 1024 * 1024
    objects: int = 131_072
    facts: int = 32_768


@dataclass(frozen=True, slots=True)
class _FactObservation:
    """Transient adapter input; authority is (dependency revision, observation offset).

    A retirement has no entry. Replacement adapters retire only old_ids minus new_ids,
    then upsert new_ids, including same-id updates exactly once: a same-authority tombstone
    wins over an upsert. Retirements include ids never emitted. Position is native order.
    """

    fact_id: str
    entry: session_source.SourceEntry | None
    position: tuple[int, int, int]
    authority: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _Fact:
    fact_id: str
    fingerprint: str
    kind: str
    actor: str
    stream: str
    at: float
    title: str
    result: str | None
    path: str | None
    folder: str | None
    subject: str | None
    position: tuple[int, int, int]
    authority: tuple[int, int]


@dataclass(frozen=True, slots=True)
class _FactGraph:
    facts: Mapping[str, _Fact]
    retired: Mapping[str, tuple[int, int]]
    # Caller supplies the combined sanitized checkpoint/answer/plan/identity graph.
    extras: object = None


@dataclass(frozen=True, slots=True)
class _FactAdmission:
    graph: _FactGraph | None
    limited: bool = False
    reason: str | None = None


_FACT_FORBIDDEN_FIELDS = frozenset(
    {"words", "raw", "raw_record", "fragment", "input", "input_json"}
)
_FACT_HASH_TYPE = type(hashlib.sha256())
_FACT_LIMITS = _FactLimits()


def _fact_children(value: object) -> Iterator[object]:
    if isinstance(value, (dict, MappingProxyType)):
        for key, child in value.items():
            yield key
            yield child
    elif isinstance(value, (tuple, list, set, frozenset)):
        yield from value
    elif is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "__dict__"):
            yield vars(value)
        # Mixed dict/slot dataclasses need both stores. Shared values count once.
        for name in value.__dataclass_fields__:
            yield getattr(value, name)


def _fact_storage(item: object) -> int | None:
    if isinstance(
        item,
        (
            session_source.SourceEntry,
            session_source.SourcePage,
            session_source.SourceCursor,
            session_source.SourceSnapshot,
            session_source.PendingCall,
        ),
    ):
        return None
    if isinstance(item, (dict, MappingProxyType)):
        if any(key in item for key in _FACT_FORBIDDEN_FIELDS):
            return None
        return 256 + 96 * len(item) if isinstance(item, MappingProxyType) else 0
    if is_dataclass(item) and not isinstance(item, type):
        return None if _FACT_FORBIDDEN_FIELDS.intersection(item.__dataclass_fields__) else 0
    if isinstance(item, _FACT_HASH_TYPE):
        return 256  # Opaque native SHA context has fixed storage; never inspect inputs.
    return (
        0
        if type(item) in (str, int, float, bool, type(None), tuple, list, set, frozenset)
        else None
    )


def _measure_facts(value: object, limits: _FactLimits) -> tuple[int, int] | None:
    """Bounded unique-object getsizeof accounting, not an RSS measurement.

    Iterator frames avoid an eager copy of wide containers. The traversal's seen ids,
    set table, frames and iterators are charged, with a fixed 1 KiB scalar/frame reserve.
    Proxy backing tables use a conservative 256 + 96/entry charge without copying them.
    Only intentional containers/dataclasses/scalars and fixed opaque SHA state are allowed.
    """
    seen: set[int] = set()
    pending = [iter((value,))]
    frame_bytes = sys.getsizeof(pending[0])
    size = 0
    peak_scratch = 0
    peak_frames = 1
    while pending:
        try:
            item = next(pending[-1])
        except StopIteration:
            frame_bytes -= sys.getsizeof(pending.pop())
            continue
        identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        extra = _fact_storage(item)
        if extra is None:
            return None
        size += sys.getsizeof(item) + extra
        scratch = (
            1024
            + sys.getsizeof(seen)
            + len(seen) * sys.getsizeof(identity)
            + sys.getsizeof(pending)
            + frame_bytes
            + 192 * len(pending)  # Internal child iterators and mapping-item tuples.
        )
        peak_scratch = max(peak_scratch, scratch)
        peak_frames = max(peak_frames, len(pending))
        if (
            size + peak_scratch > limits.bytes
            or 2 * len(seen) + 3 * peak_frames + 8 > limits.objects
        ):
            return None
        frame = _fact_children(item)
        pending.append(frame)
        frame_bytes += sys.getsizeof(frame)
    return size + peak_scratch, 2 * len(seen) + 3 * peak_frames + 8


def _copy_fact(observation: _FactObservation) -> _Fact | None:
    entry = observation.entry
    if entry is None:
        return None
    return _Fact(
        observation.fact_id,
        entry.fingerprint,
        entry.kind,
        entry.actor,
        entry.stream,
        entry.at,
        entry.title,
        entry.result,
        entry.path,
        entry.folder,
        entry.subject,
        observation.position,
        observation.authority,
    )


def _merge_facts(
    previous: _FactGraph | None,
    observations: Iterable[_FactObservation],
    *,
    extras: object = None,
    limits: _FactLimits = _FACT_LIMITS,
) -> _FactAdmission:
    """Admit one bounded candidate atomically; refusal never advances its extras/frontier.

    Admission charges the old graph, new extras, candidate tables and each incoming fact
    before insertion. The incremental ledger deliberately overcounts shared/replaced values;
    this keeps candidate work linear and bounded from the first insertion. Final measurement
    checks the combined retained graph. Retired ids consume the same fact allowance.

    Projection/replay scratch reserves 2 KiB and 32 objects per admitted id (entries,
    sorting, grouping, run sets and counters), capped at four times the retained budgets.
    Caller-owned transient source pages and its already bounded reader are outside this
    helper's accounting. Answers/plans must be supplied in extras before final publication.
    """
    refused = _FactAdmission(previous, limited=True, reason="outline_state_limit")
    measured = _measure_facts((previous, extras), limits)
    if measured is None:
        return refused
    size, units = measured
    count = len(previous.facts) + len(previous.retired) if previous else 0
    # Both mutable candidate tables coexist with the previous immutable graph.
    size += 512 + 192 * count
    units += 2
    if (
        count > limits.facts
        or size > limits.bytes
        or units > limits.objects
        or count * 2048 > limits.bytes * 4
        or count * 32 > limits.objects * 4
    ):
        return refused
    facts = dict(previous.facts) if previous else {}
    retired = dict(previous.retired) if previous else {}
    for observation in observations:
        current = facts.get(observation.fact_id)
        authority = current.authority if current else retired.get(observation.fact_id)
        if authority is not None and (
            observation.authority < authority
            or (
                observation.authority == authority
                and (current is None or observation.entry is not None)
            )
        ):
            continue
        # The source-owned display fields are bounded by admission without slicing or
        # retaining the full-word SourceEntry. No full record is copied into the graph.
        fact = _copy_fact(observation)
        payload = fact if fact is not None else (observation.fact_id, observation.authority)
        measured = _measure_facts(payload, limits)
        if measured is None:
            return refused
        size += measured[0] + 192
        units += measured[1] + 2
        if current is None and observation.fact_id not in retired:
            count += 1
        if (
            count > limits.facts
            or size > limits.bytes
            or units > limits.objects
            or count * 2048 > limits.bytes * 4
            or count * 32 > limits.objects * 4
        ):
            return refused
        if fact is None:
            facts.pop(observation.fact_id, None)
            retired[observation.fact_id] = observation.authority
        else:
            retired.pop(observation.fact_id, None)
            facts[observation.fact_id] = fact
    graph = _FactGraph(MappingProxyType(facts), MappingProxyType(retired), extras)
    if _measure_facts((previous, graph), limits) is None:
        return refused
    return _FactAdmission(graph)


def _ordered_entries(graph: _FactGraph) -> tuple[session_source.SourceEntry, ...]:
    """Project parent facts in physical order; cross-stream replay belongs to integration."""
    return tuple(
        session_source.SourceEntry(
            fact.fact_id,
            fact.fingerprint,
            fact.kind,
            fact.actor,
            fact.stream,
            fact.at,
            fact.title,
            fact.result,
            fact.path,
            fact.folder,
            fact.subject,
        )
        for fact in sorted(graph.facts.values(), key=lambda fact: (fact.stream, fact.position))
    )


@dataclass(frozen=True)
class _Opening:
    """The session's first prompt and the work under it, read from the start of the record."""

    entries: tuple[session_source.SourceEntry, ...]
    # The read stopped before the next prompt, so the counts under the first prompt are a floor.
    partial: bool
    # The head read ended before the window began, so work between them is unread.
    gap: bool = False


def _groups(
    entries: Iterable[session_source.SourceEntry],
) -> list[list[session_source.SourceEntry]]:
    groups: list[list[session_source.SourceEntry]] = []
    for entry in entries:
        if entry.kind == "person" or not groups:
            groups.append([])
        groups[-1].append(entry)
    return groups


@dataclass
class _Runs:
    """How check runs relate across parts, read once over every entry the outline holds.

    A failure is an episode: the failed runs of one check with no pass between them. A part says
    an episode once, in the first part it failed in, so a failure that spans two parts is not
    counted or listed twice, while a failure after a fix is a new episode and is.
    """

    # Failed runs a later passing run of the same check followed: a red test that was fixed.
    fixed: set[str]
    episode: dict[str, str]
    # Episodes already counted fixed, or listed as still failing, by an earlier part.
    counted: set[str]
    listed: set[str]


def _runs(entries: Iterable[session_source.SourceEntry]) -> _Runs:
    ordered = [
        (entry.subject, entry)
        for entry in entries
        if entry.kind == "check" and entry.subject is not None
    ]
    passed: set[str] = set()
    fixed: set[str] = set()
    for subject, entry in reversed(ordered):
        if entry.result == "passed":
            passed.add(subject)
        elif entry.result == "failed" and subject in passed:
            fixed.add(entry.fact_id)
    current: dict[str, str] = {}
    episode: dict[str, str] = {}
    for subject, entry in ordered:
        if entry.result == "passed":
            current.pop(subject, None)
        elif entry.result == "failed":
            episode[entry.fact_id] = current.setdefault(subject, entry.fact_id)
    return _Runs(fixed, episode, set(), set())


def _block(
    entries: Sequence[session_source.SourceEntry],
    highlights: int,
    runs: _Runs,
    *,
    opening: bool = False,
    partial: bool = False,
    unread_after: bool = False,
) -> dict[str, Any]:
    first, last = entries[0], entries[-1]
    checks = [entry for entry in entries if entry.kind == "check"]
    folders = Counter(entry.folder for entry in entries if entry.kind == "file")
    # One row per check, its newest failed run in the part: the same failure listed twice was two
    # runs of one check. A run that a later pass followed is fixed, not failing.
    latest = {entry.subject or entry.fact_id: entry for entry in checks if entry.result == "failed"}
    unfixed = {key: entry for key, entry in latest.items() if entry.fact_id not in runs.fixed}
    # A failure in a part whose own tail or following work was not read may have been fixed there:
    # it is unknown, not failing, and nothing later in the outline can say which.
    unknown = unfixed if unread_after else {}

    # A check still red from an earlier part is the same failure, so only the part it first
    # failed in lists it. An unknown one is not listed, so a later part that fails it again is.
    # What the highlight cap drops was never shown, so it is not marked listed either.
    def episode(entry: session_source.SourceEntry) -> str:
        return runs.episode.get(entry.fact_id, entry.fact_id)

    fresh = [
        entry
        for key, entry in unfixed.items()
        if key not in unknown and episode(entry) not in runs.listed
    ]
    failures = fresh
    shown = failures[-highlights:] if highlights else []
    runs.listed.update(episode(entry) for entry in shown)
    # A failure that spans parts and was then fixed is counted fixed where it first failed.
    mended = [entry for entry in latest.values() if entry.fact_id in runs.fixed]
    new_mended = [entry for entry in mended if episode(entry) not in runs.counted]
    runs.counted.update(episode(entry) for entry in new_mended)

    def check(entry: session_source.SourceEntry) -> dict[str, Any]:
        public = session_source.entry_for_page(entry)
        return {key: public[key] for key in ("fact_id", "title", "result")}

    return {
        "prompt": {"fact_id": first.fact_id, "title": first.title, "at": first.at}
        if first.kind == "person"
        else None,
        "opening": opening,
        "partial": partial,
        "span": {
            "first": first.fact_id,
            "last": last.fact_id,
            "entries": len(entries),
            "from_at": first.at,
            "to_at": last.at,
        },
        "counts": {
            "checks": len(checks),
            "checks_failed": len(failures),
            "checks_fixed": len(new_mended),
            "checks_unknown": len(unknown),
            "files": sum(entry.kind == "file" for entry in entries),
            "agent_messages": sum(entry.kind == "agent" for entry in entries),
            "subagent_entries": sum(entry.actor == "subagent" for entry in entries),
        },
        "failures": [check(entry) for entry in shown],
        "folders": [
            {"folder": folder, "files": count}
            for folder, count in sorted(folders.items(), key=lambda row: (-row[1], row[0] or ""))[
                :highlights
            ]
        ],
        "checks": [check(entry) for entry in checks[-highlights:]] if highlights else [],
    }


def build(
    page: session_source.SourcePage, config: RuntimeConfig, opening: _Opening | None = None
) -> dict[str, Any]:
    """One block per person's message, opening with the session's first one.

    `opening` is the first prompt's part, read from the start when the newest window began after
    it. The first part is always shown; the block cap bounds the newest parts after it. A window
    that began after the start with no `opening` has no first part to show.
    """
    groups = _groups(page.entries)
    head = opening
    # A window that began after byte zero has no known first prompt: when the head read found none
    # (a first line past its budget), the window's first part is an ordinary part, not the opening.
    from_start = page.coverage is None or page.coverage.start_offset == 0
    if head is None and groups and from_start:
        head = _Opening(tuple(groups[0]), partial=False)
        groups = groups[1:]
    cap = max(0, config.session_outline_max_blocks)
    more = max(0, len(groups) - cap) if cap else len(groups) + (head is not None)
    highlights = max(0, config.session_outline_highlights)
    runs = _runs([*(opening.entries if opening else ()), *page.entries])
    blocks = (
        [
            *(
                [
                    _block(
                        head.entries,
                        highlights,
                        runs,
                        opening=True,
                        partial=head.partial,
                        unread_after=head.partial or head.gap,
                    )
                ]
                if head
                else []
            ),
            *(_block(group, highlights, runs) for group in groups[more:]),
        ]
        if cap
        else []
    )
    coverage = asdict(page.coverage) if page.coverage else None
    if coverage is not None:
        coverage["unread"] = list(coverage["unread"])
        coverage["notes"] = list(coverage["notes"])
    return {
        "state": page.state,
        "made_by": "compass",
        "basis": "grouping",
        "reason": "no_paged_record"
        if page.state == "unsupported"
        else None
        if page.state == "ok"
        else page.state,
        "harness": page.harness,
        "coverage": coverage,
        "blocks": blocks,
        "more_blocks": more,
    }


def unmatched(config: RuntimeConfig, harness: str, sid: str) -> dict[str, Any]:
    """The same labelled shape when the focus matches no single row; nothing is read."""
    return {
        **build(session_source.SourcePage("unavailable", harness, sid), config),
        "reason": "session_not_matched",
    }


def _head(
    config: RuntimeConfig, path: str, harness: str, sid: str, window_start: int, deadline: float
) -> tuple[_Opening | None, bool]:
    """The first prompt's part, read from byte zero up to where the newest window begins.

    A busy session passes the window's byte bound in minutes, and the window then starts after its
    own first prompt. The read stops at the window so the two never overlap, and it spends what is
    left of the window's `deadline` rather than a second budget of its own. Returns whether its
    clock clipped it, which keeps the outline from being cached.
    """
    budget = min(max(0, config.session_outline_head_bytes), window_start)
    if budget <= 0:
        return None, False
    page = session_source.read(
        config,
        path,
        harness,
        sid,
        max_bytes=budget,
        deadline=deadline,
    )
    clipped = page.coverage is not None and any(
        region.reason == "time" for region in page.coverage.unread
    )
    if page.state != "ok":
        return None, clipped
    gap = budget < window_start or clipped
    groups = _groups(page.entries)
    for number, group in enumerate(groups):
        if group[0].kind == "person":
            # Later groups the head read held are dropped from the outline, so a pass in one of
            # them cannot be shown: the opening part's failures are then unknown, not failing.
            dropped = number < len(groups) - 1
            return _Opening(tuple(group), number == len(groups) - 1, gap or dropped), clipped
    return None, clipped


def _plan(page: session_source.SourcePage, config: RuntimeConfig) -> dict[str, Any] | None:
    if page.state != "ok" or page.harness != "claude":
        return None
    planned = session_summary.plan(page.entries, page.harness, config=config)
    ceilings = planned["largest_read"]
    parts = int(planned["parts"])
    # The outline reads a newest window; the job reads the whole source. Off a partial read the
    # parts are a floor, so the call count falls back to the whole-job ceiling to stay an upper
    # bound, as [the focused plan](docs/design-session-summary.md#the-focused-plan) records.
    complete = page.coverage is not None and page.coverage.complete
    calls = int(ceilings["calls"])
    if complete:
        calls = min(calls, parts * config.session_summary_attempts_per_part)
    return {
        "reason": planned["reason"],
        "complete": complete,
        "parts": parts,
        "windows": max(0, parts - 1),
        "calls": calls,
        "minutes": math.ceil(min(calls * ceilings["call_timeout"], ceilings["seconds"]) / 60),
        "largest_read": ceilings,
    }


def for_session(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str
) -> dict[str, Any]:
    """The deterministic grouping from the shared focused source pass."""
    return for_session_with_plan(config, state, harness, sid)[0]


def for_session_with_plan(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Cache word-free grouping by transcript stamps; no grants or model seams are involved."""
    if harness not in session_source.HARNESSES:
        return build(session_source.SourcePage("unsupported", harness, sid), config), None
    path = observer.resolve_transcript(config, state, harness, sid)
    if path is None:
        return build(session_source.SourcePage("unavailable", harness, sid), config), None
    key = f"{os.path.abspath(path)}\0{harness}\0{sid}"
    with state.session_outline_lock:
        try:
            stamps = session_source.source_stamps(path, harness)
        except OSError:
            return build(session_source.SourcePage("unavailable", harness, sid), config), None
        bounds = (
            config.session_outline_max_bytes,
            config.session_outline_head_bytes,
            config.session_outline_max_seconds,
            config.session_outline_max_blocks,
            config.session_outline_highlights,
            config.session_summary_window_bytes,
            config.session_summary_max_windows,
            config.session_summary_max_calls,
            config.session_summary_max_bytes_sent,
            config.session_summary_max_seconds,
            config.session_summary_call_timeout,
        )
        cached = state.session_outlines.get(key)
        if cached is not None and cached[0] == (stamps, bounds):
            result: tuple[dict[str, Any], dict[str, Any] | None] = cached[1]
            return result
        deadline = time.monotonic() + config.session_outline_max_seconds
        page = session_source.read(
            config,
            path,
            harness,
            sid,
            newest=True,
            max_bytes=config.session_outline_max_bytes,
            deadline=deadline,
        )
        opening, head_clipped = (
            _head(config, path, harness, sid, page.coverage.start_offset, deadline)
            if page.state == "ok" and page.coverage is not None and page.coverage.start_offset > 0
            else (None, False)
        )
        result = (build(page, config, opening), _plan(page, config))
        try:
            unchanged = session_source.source_stamps(path, harness) == stamps
        except OSError:
            unchanged = False
        if not unchanged:
            return build(session_source.SourcePage("stale", harness, sid), config), None
        clipped = head_clipped or (
            page.coverage is not None
            and any(region.reason == "time" for region in page.coverage.unread)
        )
        # A time-clipped window is short of its newest turns, and a clipped head of its first
        # prompt's part; caching either would serve it until the transcript changed, so the next
        # poll retries instead.
        if page.state == "ok" and not clipped:
            runtime_state.bounded_put(
                state.session_outlines,
                key,
                ((stamps, bounds), result),
                limit=config.session_outline_cache_limit,
            )
        return result
