"""Copied corrections: a correction the reader copied, recognised when it comes back.

Item 9 of
[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
(DRC-4678). `POST /api/correction/copied` records the digest of the exact text the reader
copied and where the session's transcript ended at that moment; a later Claude Code user message,
written past that point, whose raw text has the same digest is Compass's words, `derived`, for
adoption, rule 7 and the later-direction floor alike. Only digests, positions and fact ids are
stored, never the text.

The digest is computed here by re-reading the transcript from where the copy was made, rather
than inside the collector: the collector's module is frozen with the abstention qualification
(`scripts/mark_abstention.py`, `_PARSER_FILES`), and this read runs only for a session that holds
a copy. Once a message is recognised its fact id is written to the store and published from there,
so what the tail no longer holds stays recognised.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from typing import TYPE_CHECKING, Any, NamedTuple, NotRequired, TypedDict

from compass_runtime.config import (
    remove_state_file,
)

from . import io as runtime_io
from . import observer, project_context, reading, records, transcripts
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .config import RuntimeConfig
    from .state import RuntimeState

SCHEMA_VERSION = 1

# The most a correction may hold, which is the most item 7 of that ruling lets the box compose:
# its lines' own 2,000, and since the owner's ruling of 2026-10-20 room for eight explanations (the
# goal, six outcome lines and a contradicted claim) of 277 each, the label's 36 and a stored
# detail's 240 and its "…", and since the owner's second ruling of that day room for seven quotes
# of the agent's own words (the goal and six outcome lines) of 132 each: 2,000 + 8 * 277 + 7 * 132.
# `correction.py` holds the parts and `test_correction` the sum.
CORRECTION_CAP_CHARS = 5140
# The owner's bound, 2026-09-28: eight per session, the oldest dropped. It counts copies still
# waiting for their message; a recognised message moves to `matches` and leaves this count.
COPIES_PER_SESSION = 8
# Recognised messages kept per session, the oldest dropped, and apart from the waiting copies so a
# ninth copy (or a probe) cannot un-mark one.
MATCHES_PER_SESSION = 32
# How much of a message is read to digest it. A tab stored as four spaces makes the stored text
# longer than what was copied, so four times the cap covers any correction the route accepts; a
# message that reaches this is longer than any of them and is never digested, so a correction
# cannot match the opening of a longer message the reader wrote.
_MESSAGE_READ_CAP = 4 * CORRECTION_CAP_CHARS + 1
# The newest bytes of a transcript read for a match: the bound the semantic history store's
# backfill reads a source to, so a message that store publishes is one this can recognise.
_OPENING_SCAN_CAP_BYTES = project_context.SEMANTIC_BACKFILL_MAX_BYTES
# A store past this reads back as nothing, un-marking every recognised paste at once, so it sits
# well above the full bound. Measured: a copy is about 150 bytes on disk and a match about 93, and
# at their widest (a 64-character sid, 17-digit times, 64-bit inode and offset) 173 and 97, so 256
# sessions of eight copies and 32 matches write 1,180,437 bytes, which overran the old 1 MiB.
_READ_CAP_BYTES = 2 << 20
_KEY_CAP_CHARS = 64
# The copy route's own body bound, derived so no correction the box composes is refused for its
# bytes (review, 2026-10-20): the shared 12,288 refused 4,216 CJK characters, the page still said
# Copied, and the paste then counted as the reader's words. Twelve bytes a character is the widest
# any JSON encoding spells one code point (an escaped surrogate pair), for the text and for both
# identity fields at the widest this store keeps them, with room for the object around them.
COPY_BODY_CAP_BYTES = 12 * (CORRECTION_CAP_CHARS + 2 * _KEY_CAP_CHARS) + 256
_LOCK_WAIT_SECONDS = 10.0
# Only Claude Code's messages are read for a digest, which is what item 9 rules.
HARNESSES = frozenset({"claude"})

OUTCOME_STORED = "stored"
OUTCOME_UNCHANGED = "unchanged"
OUTCOME_REFUSED = "refused"
OUTCOME_UNWRITABLE = "unwritable"

_WRITE_LOCK = threading.Lock()
_DIGEST = re.compile(r"[0-9a-f]{64}")
_FACT_ID = re.compile(r"fact:[0-9a-f]{16}")


class Copy(TypedDict):
    """A copy still waiting for its message: the digest, when, and where the transcript ended."""

    digest: str
    copied_at: float
    ino: int
    offset: int
    # The same text with every run of whitespace folded to one space, so a paste whose only edit
    # was whitespace still comes back as the correction (DRC-4920). Absent on a copy stored before
    # it existed, which keeps matching on `digest` alone.
    folded: NotRequired[str]


class Match(TypedDict):
    """A message recognised as a copy, kept once found: `at` is the message's own time."""

    fact_id: str
    at: float
    copied_at: float


class Held(NamedTuple):
    copies: tuple[Copy, ...]
    matches: tuple[Match, ...]


class _Message(NamedTuple):
    position: int
    fact_id: str
    at: float
    digest: str | None
    folded: str | None
    # What the row's `instruction` and `first_prompt` would carry for this message, each built
    # as its producer builds it, so the row's field can be placed on the message it quotes.
    line: str
    first: str


def normalise(text: str) -> str:
    """The owner's rule, 2026-09-28, applied to both sides.

    Measured on Claude Code 2.1.283 (paste4678): at paste time CRLF and CR become LF and a tab
    becomes exactly four spaces, and a short paste loses its trailing whitespace on submit while
    a long one keeps it. Trimming both ends makes the two agree; nothing else is folded, so any
    edit is a different digest.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").strip()


def digest(text: str) -> str:
    return hashlib.sha256(normalise(text).encode("utf-8", "surrogatepass")).hexdigest()


def folded_digest(text: str) -> str:
    """`digest` after every run of whitespace, inside a line as well as at its ends, is one space.

    A second, looser reading beside the exact one (DRC-4920): the owner's 2026-09-28 normalisation
    stays what `digest` computes, and is what a pasted correction matches first. This one only
    forgives the reader reflowing lines or widening a gap; a changed word, or a space inside a
    word, is still a different text.
    """
    return hashlib.sha256(" ".join(text.split()).encode("utf-8", "surrogatepass")).hexdigest()


def store_path(config: RuntimeConfig) -> str:
    """Beside the annotation store, and not per port, for `annotations.store_path`'s reason."""
    return os.path.join(config.state_home, "compass-copied-corrections.json")


def _lock_path(config: RuntimeConfig) -> str:
    return f"{store_path(config)}.lock"


def _key(harness: Any, sid: Any) -> tuple[str, str]:
    return (
        records.safe_text(harness, _KEY_CAP_CHARS).strip(),
        records.safe_text(sid, _KEY_CAP_CHARS).strip(),
    )


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _copy(value: Any) -> Copy | None:
    if not isinstance(value, dict):
        return None
    found = value.get("digest")
    moment = reading.valid_prompt_time(value.get("copied_at"))
    ino, offset = _count(value.get("ino")), _count(value.get("offset"))
    if not isinstance(found, str) or not _DIGEST.fullmatch(found):
        return None
    if moment is None or ino is None or offset is None:
        return None
    copy: Copy = {"digest": found, "copied_at": moment, "ino": ino, "offset": offset}
    folded = value.get("folded")
    if isinstance(folded, str) and _DIGEST.fullmatch(folded):
        copy["folded"] = folded
    return copy


def _match(value: Any) -> Match | None:
    if not isinstance(value, dict):
        return None
    fact_id = value.get("fact_id")
    at = reading.valid_prompt_time(value.get("at"))
    copied_at = reading.valid_prompt_time(value.get("copied_at"))
    if not isinstance(fact_id, str) or not _FACT_ID.fullmatch(fact_id):
        return None
    if at is None or copied_at is None:
        return None
    return {"fact_id": fact_id, "at": at, "copied_at": copied_at}


def _held(copies: Iterable[Copy], matches: Iterable[Match]) -> Held:
    """Each list in recording order, bounded, the oldest dropped; a fact id kept once."""
    ordered = sorted(copies, key=lambda copy: copy["copied_at"])
    unique: dict[str, Match] = {}
    for match in sorted(matches, key=lambda match: match["copied_at"]):
        unique.setdefault(match["fact_id"], match)
    return Held(
        tuple(ordered[-COPIES_PER_SESSION:]),
        tuple(list(unique.values())[-MATCHES_PER_SESSION:]),
    )


def _read(config: RuntimeConfig) -> dict[tuple[str, str], Held]:
    """Every session's copies and recognised messages on disk. A file that cannot be read holds
    none.

    An unreadable file is written over by the next copy rather than refused, unlike the annotation
    store: what it loses is digests, and a digest lost only makes a pasted correction read as the
    reader's own words, the direction that never hides a real direction.
    """
    try:
        with open(store_path(config), "rb") as handle:
            raw = handle.read(_READ_CAP_BYTES + 1)
    except OSError:
        return {}
    if len(raw) > _READ_CAP_BYTES:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    held: dict[tuple[str, str], Held] = {}
    for value in entries if isinstance(entries, list) else ():
        if not isinstance(value, dict):
            continue
        key = _key(value.get("harness"), value.get("sid"))
        raw_copies, raw_matches = value.get("copies"), value.get("matches")
        if not key[0] or not key[1]:
            continue
        found = _held(
            (c for c in map(_copy, raw_copies if isinstance(raw_copies, list) else ()) if c),
            (m for m in map(_match, raw_matches if isinstance(raw_matches, list) else ()) if m),
        )
        if found.copies or found.matches:
            held[key] = found
    return held


def load(config: RuntimeConfig) -> dict[tuple[str, str], Held]:
    """Every session's copies and recognised messages, or none under `--no-annotations`."""
    return _read(config) if config.annotations_enabled else {}


def _recency(held: Held) -> float:
    return max(entry["copied_at"] for entry in (*held.copies, *held.matches))


def _bounded(held: dict[tuple[str, str], Held], limit: int) -> dict[tuple[str, str], Held]:
    """The `limit` sessions copied from most recently."""
    ordered = sorted(held.items(), key=lambda item: _recency(item[1]))
    return dict(ordered[-limit:]) if limit > 0 else {}


def transcript_position(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str
) -> tuple[int, int] | None:
    """Where this session's transcript ends now, as (inode, size), or None with no transcript."""
    path = observer.resolve_transcript(config, state, harness, sid)
    if not path:
        return None
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_ino, info.st_size)


def _locked_update(config: RuntimeConfig, change: Any, diagnostic_sink: Any) -> str:
    """Apply `change` to the store under both locks and write it; returns an outcome token.

    This process's threads first, then the OS lock another dashboard on this home takes, for the
    order `annotations._locked_store` gives. `change` returns the new store, or None to leave it.
    """
    if not _WRITE_LOCK.acquire(timeout=_LOCK_WAIT_SECONDS):
        return OUTCOME_UNWRITABLE
    try:
        try:
            os.makedirs(config.state_home, mode=0o700, exist_ok=True)
        except OSError:
            return OUTCOME_UNWRITABLE
        with runtime_io.held_file_lock(_lock_path(config), wait=_LOCK_WAIT_SECONDS) as held:
            if held not in (runtime_io.LOCK_HELD, runtime_io.LOCK_UNSUPPORTED):
                return OUTCOME_UNWRITABLE
            stored = change(_read(config))
            if stored is None:
                return OUTCOME_UNCHANGED
            return _write(config, _bounded(stored, config.annotation_max_sessions), diagnostic_sink)
    finally:
        _WRITE_LOCK.release()


def register(
    config: RuntimeConfig,
    harness: Any,
    sid: Any,
    text: Any,
    *,
    now: float,
    position: tuple[int, int] | None,
    diagnostic_sink: Any = print,
) -> str:
    """Record that this text was copied for this session. Returns an outcome token.

    `position` is where the session's transcript ended when the copy was made
    (`transcript_position`); only a message written past it can match, whatever its clock says.
    A digest still waiting for its message answers `unchanged` and keeps its first position, so
    a second registration cannot move where it matches from or earn a second match.
    """
    key = _key(harness, sid)
    moment = reading.valid_prompt_time(now)
    if (
        not config.annotations_enabled
        or key[0] not in HARNESSES
        or not key[1]
        or not isinstance(text, str)
        or len(text) > CORRECTION_CAP_CHARS
        or not normalise(text)
        or moment is None
        or position is None
    ):
        return OUTCOME_REFUSED
    copy: Copy = {
        "digest": digest(text),
        "copied_at": moment,
        "ino": position[0],
        "offset": position[1],
        "folded": folded_digest(text),
    }

    def change(stored: dict[tuple[str, str], Held]) -> dict[tuple[str, str], Held] | None:
        prior = stored.get(key, Held((), ()))
        if any(held["digest"] == copy["digest"] for held in prior.copies):
            return None
        stored[key] = _held((*prior.copies, copy), prior.matches)
        return stored

    return _locked_update(config, change, diagnostic_sink)


def _record(config: RuntimeConfig, key: tuple[str, str], found: list[tuple[str, Match]]) -> None:
    """Move each recognised copy from waiting to recognised, so it is never recomputed away.

    A store another dashboard emptied meanwhile (`--forget`) is left empty. A write that fails
    leaves the copy waiting, and the next collection recognises it again.
    """

    def change(stored: dict[tuple[str, str], Held]) -> dict[tuple[str, str], Held] | None:
        prior = stored.get(key)
        if prior is None:
            return None
        digests = {found_digest for found_digest, _ in found}
        stored[key] = _held(
            (copy for copy in prior.copies if copy["digest"] not in digests),
            (*prior.matches, *(match for _, match in found)),
        )
        return stored

    _locked_update(config, change, lambda _message: None)


def _write(
    config: RuntimeConfig,
    held: dict[tuple[str, str], Held],
    diagnostic_sink: Any,
) -> str:
    payload = {
        "v": SCHEMA_VERSION,
        "entries": [
            {
                "harness": harness,
                "sid": sid,
                "copies": [dict(copy) for copy in entry.copies],
                "matches": [dict(match) for match in entry.matches],
            }
            for (harness, sid), entry in held.items()
        ],
    }
    try:
        target = store_path(config)
        runtime_io.atomic_write_owner_only(target, json.dumps(payload))
    except (OSError, ValueError):
        runtime_io.diag(
            f"Compass: could not write the copied-correction store {store_path(config)}",
            diagnostic_sink,
        )
        return OUTCOME_UNWRITABLE
    return OUTCOME_STORED


def forget(config: RuntimeConfig) -> bool:
    """Delete the store, reporting whether there was one. Independent of the flag, for
    `history.forget`'s reason."""
    return remove_state_file(store_path(config))


def _scan(
    config: RuntimeConfig, path: str, sid: str, start: int, end: int
) -> tuple[list[_Message], int]:
    """Each user message whose record begins in `[start, end)`, and where the scan stopped.

    The fact id is recomputed exactly as `project_context.direction_text` recomputes it. The
    digest is taken from the record's raw content, before the redaction and the clipping every
    published copy of it goes through, and is None for a message too long to be any correction.
    A record `start` falls inside was being written before it, so it is skipped; a last line with
    no newline is still being written, so the scan stops before it and reads it next time.
    """
    out: list[_Message] = []
    # The collector's own spelling, frozen.
    steer = project_context._SEMANTIC_FACT_TYPES["steer"]  # noqa: SLF001
    with open(path, "rb") as handle:
        position = start
        if start > 0:
            handle.seek(start - 1)
            if handle.read(1) != b"\n":
                position += len(handle.readline(max(0, end - start)))
        handle.seek(position)
        while position < end:
            raw = handle.readline(end - position)
            if not raw.endswith(b"\n"):
                break
            here, position = position, position + len(raw)
            if not raw.lstrip().startswith(b"{") or not project_context._could_be_instruction(  # noqa: SLF001
                raw, "claude"
            ):
                continue
            try:
                record = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            event = project_context._instruction_event(config, record, "claude", sid)  # noqa: SLF001
            if event is None:
                continue
            fact = project_context._semantic_fact_from_event(event, "steer", steer, "")  # noqa: SLF001
            text = records.extract_text(
                records.message_dict(record).get("content"), cap=_MESSAGE_READ_CAP
            )
            whole = len(text) < _MESSAGE_READ_CAP
            # What was copied is the correction, and Claude Code wraps a paste in its own tags
            # (DRC-4920), so the digest reads the words between them.
            pasted = records.strip_paste_wrapper(text)
            cap = records.INSTRUCTION_CAP_CHARS
            # `claude_data.latest_instruction`'s line, and `transcripts.first_prompt`'s.
            line = records.instruction_line(
                "asked", transcripts.prompt_title(config, text.strip(), cap), 1.0
            )
            first = transcripts.prompt_title(config, text, cap)
            out.append(
                _Message(
                    here,
                    str(fact["fact_id"]),
                    float(event["at"]),
                    digest(pasted) if whole else None,
                    folded_digest(pasted) if whole else None,
                    str(line["text"]) if line else "",
                    records.safe_text(first, cap + 1) if first else "",
                )
            )
    return out, position


def _opening_messages(
    config: RuntimeConfig,
    path: str,
    sid: str,
    info: os.stat_result,
    cached: dict[str, Any] | None,
    start: int,
    end: int,
    tail_start: int,
) -> list[_Message]:
    """Copied exclusions must cover the same opening sources the prompt menu can offer."""
    if start >= tail_start or start >= end:
        return []
    if (
        cached is not None
        and cached["ino"] == info.st_ino
        and cached.get("opening_start") == start
        and cached.get("opening_end") == end
    ):
        return list(cached.get("opening", ()))
    return _scan(config, path, sid, start, end)[0]


def _messages(
    config: RuntimeConfig, state: RuntimeState, path: str, sid: str, start: int
) -> tuple[list[_Message], int, int]:
    """The user messages from `start` to the end of the transcript, with its inode and size.

    Read incrementally: what an earlier collection scanned is kept in memory and only the bytes
    since are read, so a copy waiting for its message costs one read of the transcript, not one
    per collection. First of a duplicate pair, as `direction_text` keeps it.
    """
    info = os.stat(path)
    opening_start = max(start, 0)
    start = max(start, info.st_size - config.direction_scan_max_bytes, 0)
    cache_key = f"copied-corrections:{sid}:{path}"
    with state.cache_lock:
        cached = state.metadata_cache.get(cache_key)
    if (
        cached is not None
        and cached["ino"] == info.st_ino
        and cached["start"] <= start
        and cached["end"] <= info.st_size
    ):
        more, end = _scan(config, path, sid, max(cached["end"], start), info.st_size)
        found = [m for m in cached["messages"] if m.position >= start] + more
    else:
        found, end = _scan(config, path, sid, start, info.st_size)
    opening_end = min(info.st_size, _OPENING_SCAN_CAP_BYTES)
    opening = _opening_messages(config, path, sid, info, cached, opening_start, opening_end, start)
    found = sorted([*opening, *found], key=lambda message: message.position)
    seen: set[str] = set()
    messages = []
    for message in found:
        if message.fact_id not in seen:
            seen.add(message.fact_id)
            messages.append(message)
    with state.cache_lock:
        runtime_state.bounded_put(
            state.metadata_cache,
            cache_key,
            {
                "ino": info.st_ino,
                "start": start,
                "end": end,
                "messages": tuple(messages),
                "opening_start": opening_start,
                "opening_end": opening_end,
                "opening": tuple(opening),
            },
            limit=config.max_cache_entries,
        )
    return messages, info.st_ino, info.st_size


def _same(message: _Message, copy: Copy) -> bool:
    """Whether this message is the copied text: exactly, or with only its whitespace reflowed."""
    if message.digest is None:
        return False
    folded = copy.get("folded")
    return message.digest == copy["digest"] or (folded is not None and message.folded == folded)


def _recognise(
    config: RuntimeConfig, state: RuntimeState, key: tuple[str, str], held: Held
) -> tuple[tuple[Match, ...], list[_Message]]:
    """This session's recognised messages, the stored ones and any found now, and the messages
    read on the way (the tail, at least), for `attach` to place the row's instruction among."""
    harness, sid = key
    if harness not in HARNESSES:
        return (), []
    path = observer.resolve_transcript(config, state, harness, sid)
    if not path:
        return held.matches, []
    try:
        size = os.stat(path).st_size
        waiting = [copy["offset"] for copy in held.copies]
        start = min([max(0, size - config.tail_bytes), *waiting])
        messages, ino, size = _messages(config, state, path, sid, start)
    except OSError:
        return held.matches, []
    taken = {match["fact_id"] for match in held.matches}
    found: list[tuple[str, Match]] = []
    for copy in held.copies:
        # A replaced transcript (a new inode) or one now shorter than where the copy was made is
        # skipped. One cut short and regrown past that point on the same inode can still match;
        # Claude Code only appends, and the digest must still be exact.
        if copy["ino"] != ino or copy["offset"] > size:
            continue
        for message in messages:
            if (
                message.position >= copy["offset"]
                and _same(message, copy)
                and message.fact_id not in taken
            ):
                taken.add(message.fact_id)
                found.append(
                    (
                        copy["digest"],
                        {
                            "fact_id": message.fact_id,
                            "at": message.at,
                            "copied_at": copy["copied_at"],
                        },
                    )
                )
                break
    if found:
        _record(config, key, found)
    return _held((), (*held.matches, *(match for _, match in found))).matches, messages


def matched(
    config: RuntimeConfig,
    state: RuntimeState,
    harness: str,
    sid: str,
    held: Held | None = None,
) -> tuple[dict[str, Any], ...]:
    """The messages in this session recognised as a copied correction, oldest first.

    Each copy binds the first message written after it whose digest it holds, so a digest is used
    once and matches only past its copy, by position in the transcript rather than by clock. A
    message once recognised stays recognised, up to `MATCHES_PER_SESSION`.
    """
    key = _key(harness, sid)
    entry = held if held is not None else load(config).get(key)
    if entry is None:
        return ()
    found, _ = _recognise(config, state, key, entry)
    return _published(found)


def _published(found: Iterable[Match]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {"fact_id": match["fact_id"], "at": match["at"]}
        for match in sorted(found, key=lambda match: match["at"])
    )


def _quoted_as(
    row: Mapping[str, Any], found: Iterable[Match], messages: list[_Message]
) -> dict[str, list[str]]:
    """For each recognised fact id, which of the row's prompt fields quote it.

    Neither field carries a fact id, so each is placed on the message it quotes: the message with
    the field's time whose own rendering is the field's text, the newest for `instruction` and the
    first for `first_prompt`, as their producers choose. A field quotes a recognised message when
    that message's fact id is one, so a message the reader typed in the same second as a paste
    stays theirs. A field no read message renders to (its message older than what was read) falls
    back to its time, which withholds rather than adopts words not known to be the reader's.
    """
    instruction = records.as_dict(row.get("instruction"))
    fields: tuple[tuple[str, Any, Any, str, int], ...] = (
        ("instruction", instruction.get("text"), instruction.get("at"), "line", -1),
        ("first_prompt", row.get("first_prompt"), row.get("first_prompt_at"), "first", 0),
    )
    recognised = {match["fact_id"]: match["at"] for match in found}
    quoted: dict[str, list[str]] = {fact_id: [] for fact_id in recognised}
    for field, text, raw_at, rendering, pick in fields:
        at = reading.valid_prompt_time(raw_at)
        if at is None or not isinstance(text, str) or not text:
            continue
        same = [m for m in messages if m.at == at and getattr(m, rendering) == text]
        if same:
            ids = [same[pick].fact_id]
        else:
            ids = [fact_id for fact_id, moment in recognised.items() if moment == at]
        for fact_id in ids:
            if fact_id in quoted:
                quoted[fact_id].append(field)
    return quoted


def attach(config: RuntimeConfig, state: RuntimeState, rows: Iterable[dict[str, Any]]) -> None:
    """Put each session's recognised messages on its row, as `[]` where there are none.

    Each entry is `{"fact_id", "at", "quoted_as"}`, the last naming the row's prompt fields that
    quote it (`reading.QUOTED_AS`).
    """
    held = load(config)
    for row in rows:
        key = _key(row.get("harness"), row.get("sid"))
        entry = held.get(key)
        found, messages = _recognise(config, state, key, entry) if entry else ((), [])
        quoted = _quoted_as(row, found, messages) if found else {}
        row[reading.COPIED_PROMPTS] = [
            {**item, reading.QUOTED_AS: quoted.get(item["fact_id"], [])}
            for item in _published(found)
        ]


def mark(context: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The project context with each recognised user message marked `copied`.

    A copy of each marked fact, never the fact itself, so a cached context another caller holds
    is not changed under it.
    """
    wanted = {
        _key(row.get("harness"), row.get("sid")): {
            str(entry.get("fact_id"))
            for entry in row.get(reading.COPIED_PROMPTS) or ()
            if isinstance(entry, dict)
        }
        for row in rows
        if row.get(reading.COPIED_PROMPTS)
    }
    raw = context.get("semantic")
    semantic: dict[str, Any] = raw if isinstance(raw, dict) else {}
    facts = semantic.get("facts")
    if not wanted or not isinstance(facts, list):
        return dict(context)

    def marked(fact: Any) -> Any:
        if not isinstance(fact, dict) or fact.get("type") != "user_message":
            return fact
        session = fact.get("source_session")
        if not isinstance(session, dict):
            return fact
        ids = wanted.get(_key(session.get("harness"), session.get("sid")), set())
        return {**fact, reading.COPIED_FLAG: True} if str(fact.get("fact_id")) in ids else fact

    return {**context, "semantic": {**semantic, "facts": [marked(fact) for fact in facts]}}
