"""The turns the reader's typed Compass command opened in a Claude Code transcript.

A reader who types `/compass:compass sessions` asks Compass a question, and the agent runs Compass
and repeats what it printed. That turn is neither the reader's direction nor the agent's work, so
its records are not evidence: not for a reading, the Live monitor, a summary or the outline. Full
activity still lists what the agent ran and said, because it is what happened.

A turn runs from the typed command record (`records.compass_command_record`) to the first of: the
agent's turn stop (`claude_data.is_turn_stop_record`), any other prompt record, harness-injected
ones such as a finished background task's notice included (`records.claude_prompt_record`), and a
message the reader sent while the turn ran (`observer._queued_attachment`), measured as times. It
is never keyed on the `attributionSkill` field the harness stamps on the agent's records: after a
model-started Skill call that field stays on the agent's later real work in the same turn
(docs/captures/claude/skill-action-shapes-2.1.318-macos.jsonl), and a model-started call is the
agent's own work, so it opens no turn here.

The same turn lookup serves evidence marking and check accounting. It reads incrementally per
file, from where the last read stopped, so neither caller guesses a boundary from attribution.
The abstention parser stamp includes this module because its launcher exemption affects checks.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from . import claude_data, observer, reading, records

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .config import RuntimeConfig
    from .state import RuntimeState

# (start, end): the typed command's time, and the reader's next prompt's, or None while open.
Span = tuple[float, float | None]

# Every typed command line holds the skill's name, so a line without it is not parsed.
_NAME = records.COMPASS_COMMAND.encode()
# While a turn is open, only a line holding one of these can end it or say what came last.
_OPEN_MARKS: Final = (b'"user"', b'"assistant"', b"stop_hook_summary", b"queued_command")
# Bounded like the runtime's other per-file caches; an evicted file is read again from its start.
_CACHE_FILES: Final = 256


@dataclass(frozen=True)
class _Read:
    identity: tuple[int, int]
    offset: int
    closed: tuple[Span, ...]
    open_at: float | None
    # The type of the newest main-thread `user`/`assistant` record since the command: the context
    # `claude_data.is_turn_stop_record` reads a stop in, so a Stop hook that blocks keeps it open.
    after: str | None = None
    skill_dir: str | None = None
    launchers: tuple[tuple[str, str], ...] = ()


_LOCK = threading.Lock()
_CACHE: dict[str, _Read] = {}


def _candidate(raw: bytes, open_at: float | None) -> tuple[dict[str, Any], float] | None:
    """The record on a line that can open, end or precede the end of a turn, with its time."""
    if open_at is None:
        if _NAME not in raw:
            return None
    # A tool result neither ends a turn nor precedes a stop, so it never sets `after`.
    elif b'"toolUseResult"' in raw or not any(mark in raw for mark in _OPEN_MARKS):
        return None
    try:
        record = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(record, dict):
        return None
    at = records.parse_ts(record.get("timestamp") or "")
    return (record, at) if at is not None else None


def _ends(record: dict[str, Any], after: str | None) -> bool:
    """Whether a record ends an open turn: the agent's turn stop, any prompt, or a message the
    reader sent while it ran."""
    return (
        claude_data.is_turn_stop_record(record, after)
        or records.claude_prompt_record(record)
        or observer._queued_attachment(record) is not None  # noqa: SLF001
    )


def _launcher_ids(record: dict[str, Any], directory: str | None) -> tuple[str, ...]:
    """Exact Bash launcher operations in a parent assistant record."""
    content = records.message_dict(record).get("content")
    if record.get("type") != "assistant" or not isinstance(content, list):
        return ()
    return tuple(
        block["id"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name") == "Bash"
        and isinstance(block.get("input"), dict)
        and launcher(block["input"].get("command"), directory)
        and isinstance(block.get("id"), str)
    )


def _advance(path: str, held: _Read) -> _Read:
    closed, open_at, offset, after = list(held.closed), held.open_at, held.offset, held.after
    skill_dir, launchers = held.skill_dir, dict(held.launchers)
    with open(path, "rb") as source:
        source.seek(offset)
        for raw in source:
            if not raw.endswith(b"\n"):
                break  # a line still being written is read whole next time
            offset += len(raw)
            found = _candidate(raw, open_at)
            if found is None:
                continue
            record, at = found
            if records.compass_command_record(record):
                if open_at is not None:
                    closed.append((open_at, at))
                open_at, after, skill_dir = at, None, None
            elif open_at is not None and _ends(record, after):
                closed.append((open_at, at))
                open_at, after, skill_dir = None, None, None
            if open_at is not None and not record.get("isSidechain"):
                content = records.message_dict(record).get("content")
                if (
                    record.get("type") == "user"
                    and record.get("isMeta") is True
                    and record.get("turnCompanion") is True
                    and not record.get("sourceToolUseID")
                ):
                    tags = re.findall(
                        r"<skill-dir>([^<>\r\n]+)</skill-dir>", records.extract_text(content)
                    )
                    # Missing or conflicting publications cannot establish an exemption.
                    skill_dir = tags[0] if len(tags) == 1 and os.path.isabs(tags[0]) else None
                else:
                    launchers.update(
                        (call_id, skill_dir or "") for call_id in _launcher_ids(record, skill_dir)
                    )
            if (
                open_at is not None
                and record.get("type") in ("user", "assistant")
                and not record.get("isSidechain")
            ):
                after = record["type"]
    return _Read(
        held.identity, offset, tuple(closed), open_at, after, skill_dir, tuple(launchers.items())
    )


def _read(path: str) -> _Read | None:
    """The cached turns and positively identified launcher calls."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    identity = (info.st_dev, info.st_ino)
    with _LOCK:
        held = _CACHE.get(path)
    if held is None or held.identity != identity or info.st_size < held.offset:
        held = _Read(identity, 0, (), None)
    if info.st_size > held.offset:
        try:
            held = _advance(path, held)
        except OSError:
            return None
        with _LOCK:
            _CACHE.pop(path, None)
            _CACHE[path] = held
            while len(_CACHE) > _CACHE_FILES:
                _CACHE.pop(next(iter(_CACHE)))
    return held


def spans(path: str) -> tuple[Span, ...]:
    """Each turn a typed Compass command opened in this transcript, oldest first."""
    held = _read(path)
    if held is None:
        return ()
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


_ACTIONS: Final = frozenset(
    {
        ("--summary",),
        ("--summary", "--update"),
        ("--summary", "--again"),
        ("--summaries", "off"),
        ("--goal",),
        ("--project",),
        ("--sessions",),
        ("--sessions", "waiting"),
        ("--drift",),
        ("--drift", "again"),
        ("--monitor",),
        ("--monitor", "--off"),
        ("--pause-model-calls",),
    }
)


def launcher(command: Any, directory: str | None) -> bool:
    """Only the skill's single terminal action, with no shell expansion or extra operation."""
    if not isinstance(command, str) or any(mark in command for mark in "\n\r$`;&|<>()"):
        return False
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if len(words) < 4 or words[0] not in {"python", "python3"}:
        return False
    launch, server = words[1:3]
    return (
        directory is not None
        and launch == os.path.join(directory, "launch.py")
        and server == os.path.join(directory, "server.py")
        and tuple(words[3:]) in _ACTIONS
    )


def launcher_calls(path: str, calls: Iterable[Any]) -> frozenset[str]:
    """Parent launcher calls positively inside typed Compass turns; children remain work."""
    held = _read(path)
    identified = dict(held.launchers) if held else {}
    return frozenset(
        call[2]
        for call in calls
        if not call[5]
        and call[3] == "Bash"
        and call[2] in identified
        and launcher(call[4].get("command"), identified[call[2]])
    )


def accounting_facts(path: str, facts: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Work for check eligibility, including ordinary operations inside a Compass turn.

    Evidence sent to the producer keeps its original turn flags. Only the exact launcher
    identified in the transcript is omitted here; the agent's repeated answer remains omitted
    by the ledger's agent-message rule.
    """
    held = _read(path)
    identified = dict(held.launchers) if held else {}
    return [
        {**fact, reading.COMPASS_TURN_FLAG: False, "read_incomplete": False}
        for fact in facts
        if not (
            fact.get(reading.COMPASS_TURN_FLAG)
            and isinstance(fact.get("branch"), dict)
            and fact["branch"].get("record_id") in identified
            # A hook can substitute an ordinary command while keeping the original call id.
            and launcher(fact.get("summary"), identified[fact["branch"]["record_id"]])
        )
    ]
