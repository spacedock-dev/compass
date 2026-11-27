"""Date admitted plan rows using first-parent attribution and local log records."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from compass_runtime import git_status
from compass_runtime.state import bounded_put

from .model import ItemDate

if TYPE_CHECKING:
    from array import array

    from compass_runtime.state import RuntimeState

    from .model import Origin, Source

# At most 32 MiB of line times even if every source byte is a newline.
_CACHE_FILES = 16


def blame_times(
    tree: git_status.PlanTreeReader,
    source: Source,
    line_count: int,
    state: RuntimeState | None,
) -> array[int] | None:
    if source.ref is None or source.commit is None:
        return None
    key = (tree.cwd, source.ref, source.commit, source.path)
    if state is not None:
        with state.cache_lock:
            cached = state.plan_blame_cache.get(key)
        if cached is not None:
            return cached
    try:
        times = tree.blame(source.commit, source.path, line_count=line_count)
    except git_status.PlanGitError:
        return None
    if state is not None:
        with state.cache_lock:
            bounded_put(state.plan_blame_cache, key, times, limit=_CACHE_FILES)
    return times


def _utc_day(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, UTC).date().isoformat()


def changed(origin: Origin, times: array[int] | None) -> ItemDate | None:
    if times is None or origin.line is None:
        return None
    newest = max(times[line - 1] for line in (origin.line, *origin.related_lines))
    return ItemDate("Changed", _utc_day(newest))


def proposed(tree: git_status.PlanTreeReader, tip: str) -> ItemDate:
    try:
        value = _utc_day(tree.commit_times((tip,))[tip])
    except git_status.PlanGitError:
        value = None
    return ItemDate("Proposed, not merged", value)
