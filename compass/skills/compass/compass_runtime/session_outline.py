"""Compass's deterministic grouping of a focused session's bounded record."""

from __future__ import annotations

import math
import os
import time
from collections import Counter
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from . import observer, session_source, session_summary
from . import state as runtime_state

if TYPE_CHECKING:
    from .config import RuntimeConfig
    from .state import RuntimeState


def _block(entries: list[session_source.SourceEntry], highlights: int) -> dict[str, Any]:
    first, last = entries[0], entries[-1]
    checks = [entry for entry in entries if entry.kind == "check"]
    failures = [entry for entry in checks if entry.result == "failed"]
    folders = Counter(entry.folder for entry in entries if entry.kind == "file")

    def check(entry: session_source.SourceEntry) -> dict[str, Any]:
        public = session_source.entry_for_page(entry)
        return {key: public[key] for key in ("fact_id", "title", "result")}

    return {
        "prompt": {"fact_id": first.fact_id, "title": first.title, "at": first.at}
        if first.kind == "person"
        else None,
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


def build(page: session_source.SourcePage, config: RuntimeConfig) -> dict[str, Any]:
    """One block per person's message, including work before the first held prompt."""
    groups: list[list[session_source.SourceEntry]] = []
    for entry in page.entries:
        if entry.kind == "person" or not groups:
            groups.append([])
        groups[-1].append(entry)
    cap = max(0, config.session_outline_max_blocks)
    more = max(0, len(groups) - cap)
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
        "blocks": [
            _block(group, max(0, config.session_outline_highlights)) for group in groups[more:]
        ]
        if cap
        else [],
        "more_blocks": more,
    }


def unmatched(config: RuntimeConfig, harness: str, sid: str) -> dict[str, Any]:
    """The same labelled shape when the focus matches no single row; nothing is read."""
    return {
        **build(session_source.SourcePage("unavailable", harness, sid), config),
        "reason": "session_not_matched",
    }


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
        calls = min(calls, parts * session_summary.ATTEMPTS_PER_PART)
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
        page = session_source.read(
            config,
            path,
            harness,
            sid,
            newest=True,
            max_bytes=config.session_outline_max_bytes,
            deadline=time.monotonic() + config.session_outline_max_seconds,
        )
        result = (build(page, config), _plan(page, config))
        try:
            unchanged = session_source.source_stamps(path, harness) == stamps
        except OSError:
            unchanged = False
        if not unchanged:
            return build(session_source.SourcePage("stale", harness, sid), config), None
        clipped = page.coverage is not None and any(
            region.reason == "time" for region in page.coverage.unread
        )
        # A time-clipped window is short of its newest turns; caching it would serve that
        # clipped outline until the transcript changed, so the next poll retries instead.
        if page.state == "ok" and not clipped:
            runtime_state.bounded_put(
                state.session_outlines,
                key,
                ((stamps, bounds), result),
                limit=config.session_outline_cache_limit,
            )
        return result
