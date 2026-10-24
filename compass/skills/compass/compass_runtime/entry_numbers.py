"""Fixed positions for a session's activity entries.

A message's number is its rank among every message in the session, oldest first. A check or file's
is the number of the message it follows plus its place after that message (`41.2`). Both stay put as
the session grows, because a transcript only ever gains records at its end, and neither depends on
how many pages the reader has loaded. Before this the page numbered whatever it held, so a number
moved when a check displaced another, when a check ran again, and when Show more loaded an older
page.

One forward pass over the transcript builds an index of every message's time and id: the same
messages the record pages return, since both read them through `record_pages._fact`. The index is
held per transcript and extended from the bytes appended since, so the pass is paid once. It holds a
float and a hash per message and nothing of what was said.

A message's position is its rank by `(time, fact id)`, the order the page draws them in. A record
written late with an earlier time lands in the middle and moves the ones after it, which a resumed
transcript can do; nothing else does.
"""

from __future__ import annotations

import bisect
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, BinaryIO

from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .config import RuntimeConfig
    from .state import RuntimeState

# A line longer than this is skipped to its delimiter, as a press skips it. The record pages will
# parse one up to their 64 MiB budget, but masking a message that size takes minutes, and this pass
# runs on every collection of the focused session. A message on such a line is listed by a page
# and drawn without a number; no later number depends on it.
# Candidate key prefixes of the two kinds added after numbers were first published, and where
# their places begin: past any count of checks, files and launches one message can hold.
LATE_KINDS = ("pr:", "skill:")
LATE_PLACE_BASE = 1_000
_LINE_CAP = 16 * 1024 * 1024
_SKIP_CHUNK = 1 << 20


@dataclass
class MessageIndex:
    """The time and id of every message in one transcript, in the order the page draws them."""

    harness: str
    sid: str
    identity: tuple[int, int] | None = None
    # Bytes consumed through the last whole line. A line still being written is not consumed.
    end: int = 0
    # True once a pass has read to the end of the file, so a position is only published when exact.
    complete: bool = False
    keys: list[tuple[float, str]] = field(default_factory=list)
    ats: list[float] = field(default_factory=list)
    seen: dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _reset(self) -> None:
        self.end = 0
        self.complete = False
        self.keys.clear()
        self.ats.clear()
        self.seen.clear()

    def _add(self, fact_id: str, at: float) -> None:
        if fact_id in self.seen:
            return
        self.seen[fact_id] = at
        key = (at, fact_id)
        position = bisect.bisect_left(self.keys, key)
        self.keys.insert(position, key)
        self.ats.insert(position, at)

    def extend(self, config: RuntimeConfig, path: str, deadline: float) -> None:
        """Read what the transcript gained since the last call, or stop at the deadline."""
        self.complete = False
        try:
            with open(path, "rb") as source:
                info = os.fstat(source.fileno())
                identity = (info.st_dev, info.st_ino)
                # Replaced or shortened: what was indexed is no longer this file's start.
                if self.identity != identity or info.st_size < self.end:
                    self._reset()
                    self.identity = identity
                source.seek(self.end)
                self.complete = self._consume(config, source, deadline)
        except OSError:
            self._reset()

    def _consume(self, config: RuntimeConfig, source: BinaryIO, deadline: float) -> bool:
        """Read whole lines until the end of the file (True) or the deadline (False)."""
        cap = _LINE_CAP
        while time.monotonic() < deadline:
            line = source.readline(cap + 1)
            if not line:
                return True
            if not line.endswith(b"\n"):
                if len(line) <= cap:
                    # The last line. A page reads it as a record, so a message it completes is
                    # numbered now; it stays unconsumed, and a later pass reads it again whole.
                    self._take(config, line)
                    return True
                skipped = _skip_rest(source, deadline)
                if skipped is None:
                    return False
                if not skipped:
                    return True
                self.end = source.tell()
                continue
            self.end = source.tell()
            self._take(config, line[:-1])
        return False

    def _take(self, config: RuntimeConfig, raw: bytes) -> None:
        # record_pages imports project_context, which imports this module.
        from . import record_pages  # noqa: PLC0415

        # The record pages' own message reader, so the two cannot disagree about what a message is.
        fact = record_pages._fact(config, raw, self.harness, self.sid, title_only=True)  # noqa: SLF001
        if fact is None:
            return
        at = fact.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at):
            return
        self._add(str(fact["fact_id"]), float(at))

    def ordinal(self, fact_id: str) -> int | None:
        """The message's number, 1 for the oldest, or None for an id the index does not hold."""
        with self.lock:
            at = self.seen.get(fact_id)
            if at is None:
                return None
            return bisect.bisect_left(self.keys, (at, fact_id)) + 1

    def anchor(self, at: float) -> int:
        """How many messages are at or before `at`: the number of the message an entry follows."""
        with self.lock:
            return bisect.bisect_right(self.ats, at)


def _skip_rest(source: BinaryIO, deadline: float) -> bool | None:
    """Consume an oversized line through its newline: True when found, False when the file ends
    first, None at the deadline (the line is then read again from its start on the next pass)."""
    while time.monotonic() < deadline:
        chunk = source.readline(_SKIP_CHUNK)
        if not chunk:
            return False
        if chunk.endswith(b"\n"):
            return True
    return None


def message_index(
    config: RuntimeConfig, state: RuntimeState, path: str, harness: str, sid: str
) -> MessageIndex | None:
    """The session's message index read to the end of its transcript, or None before then."""
    key = f"{os.path.abspath(path)}\0{harness}\0{sid}"
    with state.entry_index_lock:
        index = state.entry_indexes.get(key)
        if index is None:
            index = MessageIndex(harness, sid)
            runtime_state.bounded_put(
                state.entry_indexes, key, index, limit=config.entry_index_limit
            )
    with index.lock:
        index.extend(config, path, time.monotonic() + config.entry_index_max_seconds)
        return index if index.complete else None


def with_message_ordinals(
    index: MessageIndex, facts: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Copies of the facts with each message's number added; an unknown one is left unchanged.

    Never mutates its input: the facts a context hands back can be shared with a cache.
    """
    out: list[dict[str, Any]] = []
    for fact in facts:
        number = (
            index.ordinal(str(fact.get("fact_id")))
            if fact.get("type") in {"user_message", "agent_message"}
            else None
        )
        out.append({**fact, "ordinal": number} if number is not None else fact)
    return out


def tool_positions(
    index: MessageIndex, candidates: Iterable[tuple[str, float]]
) -> dict[str, tuple[int, int]]:
    """Each check, file or launch's `(number of the message it follows, place after that message)`.

    `candidates` is every one the transcript read holds, listed or not, as `(key, time of its first
    call)`. Counting the unlisted ones is what keeps a number fixed when the listing of twelve
    evicts one: the evicted entry's number is a gap and nothing after it moves. The place breaks
    ties by key, so two entries that share a time keep the same order on every read.
    """
    groups: dict[int, list[tuple[float, str]]] = {}
    for key, first_at in candidates:
        groups.setdefault(index.anchor(first_at), []).append((first_at, key))
    positions: dict[str, tuple[int, int]] = {}
    for anchor, members in groups.items():
        members.sort()
        # A created pull request or a used skill is counted apart, from `LATE_PLACE_BASE`, so
        # adding the two kinds shifted no check, file or launch already numbered (owner review,
        # 2026-10-23), and a later check cannot take a pull request's place.
        ordinary = [key for _at, key in members if not key.startswith(LATE_KINDS)]
        late = [key for _at, key in members if key.startswith(LATE_KINDS)]
        for place, key in enumerate(ordinary, start=1):
            positions[key] = (anchor, place)
        for place, key in enumerate(late, start=LATE_PLACE_BASE + 1):
            positions[key] = (anchor, place)
    return positions
