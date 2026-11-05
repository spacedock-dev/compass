"""The turns the reader's typed Compass command opened in a Claude Code transcript.

A reader who types `/compass:compass sessions` asks Compass a question, and the agent runs Compass
and repeats what it printed. That turn is neither the reader's direction nor the agent's work, so
its records are not evidence: not for a reading, the Live monitor, a summary or the outline. Full
activity still lists what the agent ran and said, because it is what happened.

A turn runs from the typed command record (`records.compass_command_record`) to the reader's next
prompt (`records.person_prompt_record`), measured as times. It is never keyed on the
`attributionSkill` field the harness stamps on the agent's records: after a model-started Skill
call that field stays on the agent's later real work in the same turn
(docs/captures/claude/skill-action-shapes-2.1.318-macos.jsonl), and a model-started call is the
agent's own work, so it opens no turn here.

This module reads the transcript itself, rather than the collector doing it, for the reason
`copied_corrections` gives: the collector's modules are frozen with the abstention qualification.
The read is incremental per file, from where the last one stopped, so a growing transcript is read
once.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from . import observer, reading, records

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .config import RuntimeConfig
    from .state import RuntimeState

# (start, end): the typed command's time, and the reader's next prompt's, or None while open.
Span = tuple[float, float | None]

# Every typed command line holds the skill's name, so a line without it is not parsed.
_NAME = records.COMPASS_COMMAND.encode()
# Bounded like the runtime's other per-file caches; an evicted file is read again from its start.
_CACHE_FILES: Final = 256


@dataclass(frozen=True)
class _Read:
    identity: tuple[int, int]
    offset: int
    closed: tuple[Span, ...]
    open_at: float | None


_LOCK = threading.Lock()
_CACHE: dict[str, _Read] = {}


def _advance(path: str, held: _Read) -> _Read:
    closed, open_at, offset = list(held.closed), held.open_at, held.offset
    with open(path, "rb") as source:
        source.seek(offset)
        for raw in source:
            if not raw.endswith(b"\n"):
                break  # a line still being written is read whole next time
            offset += len(raw)
            if open_at is None:
                if _NAME not in raw:
                    continue
            elif b'"user"' not in raw or b'"toolUseResult"' in raw:
                continue
            try:
                record = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            at = (
                records.parse_ts(record.get("timestamp") or "")
                if isinstance(record, dict)
                else None
            )
            if at is None:
                continue
            if records.compass_command_record(record):
                open_at = at if open_at is None else open_at
            elif open_at is not None and records.person_prompt_record(record):
                closed.append((open_at, at))
                open_at = None
    return _Read(held.identity, offset, tuple(closed), open_at)


def spans(path: str) -> tuple[Span, ...]:
    """Each turn a typed Compass command opened in this transcript, oldest first."""
    try:
        info = os.stat(path)
    except OSError:
        return ()
    identity = (info.st_dev, info.st_ino)
    with _LOCK:
        held = _CACHE.get(path)
    if held is None or held.identity != identity or info.st_size < held.offset:
        held = _Read(identity, 0, (), None)
    if info.st_size > held.offset:
        try:
            held = _advance(path, held)
        except OSError:
            return ()
        with _LOCK:
            _CACHE.pop(path, None)
            _CACHE[path] = held
            while len(_CACHE) > _CACHE_FILES:
                _CACHE.pop(next(iter(_CACHE)))
    return (*held.closed, (held.open_at, None)) if held.open_at is not None else held.closed


def within(turns: Iterable[Span], at: Any) -> bool:
    """Whether a time falls inside one of the turns."""
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        return False
    return any(start <= at and (end is None or at < end) for start, end in turns)


def mark_facts(facts: Iterable[Any], harness: str, sid: str, turns: tuple[Span, ...]) -> list[Any]:
    """The facts with each of the agent's facts inside a turn marked, as copies.

    Only the agent's: a message the reader sent mid-turn is still theirs.
    """
    wanted = {"harness": harness, "sid": sid}

    def marked(fact: Any) -> Any:
        if (
            not turns
            or not isinstance(fact, dict)
            or fact.get("source_session") != wanted
            or reading.author_of(fact) != reading.AUTHOR_AGENT
            or not within(turns, fact.get("at"))
        ):
            return fact
        return {**fact, reading.COMPASS_TURN_FLAG: True}

    return [marked(fact) for fact in facts]


def mark(
    config: RuntimeConfig,
    state: RuntimeState,
    context: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """The project context with the agent's facts inside each Claude row's Compass turns marked.

    Applied where `copied_corrections.mark` is, on what the reading route, the Live monitor and
    the unasked lane read; a copy, so a cached context another caller holds is not changed.
    """
    raw = context.get("semantic")
    semantic: dict[str, Any] = raw if isinstance(raw, dict) else {}
    facts = semantic.get("facts")
    if not isinstance(facts, list):
        return dict(context)
    for row in rows:
        if row.get("harness") != "claude":
            continue
        sid = str(row.get("sid") or "")
        path = observer.resolve_transcript(config, state, "claude", sid)
        turns = spans(path) if path else ()
        if turns:
            facts = mark_facts(facts, "claude", sid, turns)
    return {**context, "semantic": {**semantic, "facts": facts}}
