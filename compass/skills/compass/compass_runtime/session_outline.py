"""Compass's deterministic grouping of a focused session's bounded record."""

from __future__ import annotations

import math
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from . import observer, session_source, session_summary
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from .config import RuntimeConfig
    from .state import RuntimeState


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


def _fixed(entries: Iterable[session_source.SourceEntry]) -> set[str]:
    """Failed runs a later passing run of the same check followed: a red test that was fixed."""
    passed: set[str] = set()
    fixed: set[str] = set()
    for entry in reversed(list(entries)):
        if entry.kind != "check" or entry.subject is None:
            continue
        if entry.result == "passed":
            passed.add(entry.subject)
        elif entry.result == "failed" and entry.subject in passed:
            fixed.add(entry.fact_id)
    return fixed


def _block(
    entries: Sequence[session_source.SourceEntry],
    highlights: int,
    fixed: set[str],
    listed: set[str],
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
    unfixed = {key: entry for key, entry in latest.items() if entry.fact_id not in fixed}
    # A failure in a part whose own tail or following work was not read may have been fixed there:
    # it is unknown, not failing, and nothing later in the outline can say which.
    unknown = unfixed if unread_after else {}
    # A check still red from an earlier part is the same failure, so only the part it first
    # failed in lists it. An unknown one is not listed, so a later part that fails it again is.
    failures = [entry for key, entry in unfixed.items() if key not in unknown and key not in listed]
    listed.update(key for key in unfixed if key not in unknown)

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
            "checks_fixed": len(latest) - len(unfixed),
            "checks_unknown": len(unknown),
            "files": sum(entry.kind == "file" for entry in entries),
            "agent_messages": sum(entry.kind == "agent" for entry in entries),
            "subagent_entries": sum(entry.actor == "subagent" for entry in entries),
        },
        "failures": [check(entry) for entry in failures[-highlights:]] if highlights else [],
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
    fixed = _fixed([*(opening.entries if opening else ()), *page.entries])
    listed: set[str] = set()
    blocks = (
        [
            *(
                [
                    _block(
                        head.entries,
                        highlights,
                        fixed,
                        listed,
                        opening=True,
                        partial=head.partial,
                        unread_after=head.partial or head.gap,
                    )
                ]
                if head
                else []
            ),
            *(_block(group, highlights, fixed, listed) for group in groups[more:]),
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
            return _Opening(tuple(group), number == len(groups) - 1, gap), clipped
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
