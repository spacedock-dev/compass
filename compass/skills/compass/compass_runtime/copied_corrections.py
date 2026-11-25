"""Copied corrections: a correction the reader copied, recognised when it comes back.

Item 9 of
[DEC-24](docs/design-reading-a-session.md#dec-24-your-intent-is-a-drafted-goal-and-a-checklist-and-a-correction-is-yours-to-copy)
(DRC-4678). `POST /api/correction/copied` records the digest of the exact text the reader
copied and where the session's transcript ended at that moment. A later Claude Code or Codex
user message past that point with the same text digest is Compass's words, `derived`, for
adoption, rule 7 and the later-direction floor alike. Only digests, positions and fact ids are
stored, never the text.

The board verifies Codex prompt occurrences and renders their fields from the
same read. It uses the qualified collector and fact builders without changing
their parser stamp. Claude Code keeps its own transcript recognition path.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import threading
from typing import TYPE_CHECKING, Any, NamedTuple, NotRequired, Self, TypedDict

from compass_runtime.config import (
    remove_state_file,
)

from . import io as runtime_io
from . import observer, project_context, reading, records, transcripts
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from typing import BinaryIO

    from .config import RuntimeConfig
    from .state import RuntimeState

SCHEMA_VERSION = 1

# The most a correction may hold, which is the most item 7 of that ruling lets the box compose:
# its lines' own 2,000, and since the owner's ruling of 2026-10-20 room for eight explanations (the
# goal, six outcome lines and a contradicted claim) of 277 each, the label's 36 and a stored
# detail's 240 and its "…", and since the owner's second ruling of that day room for seven quotes
# of the agent's own words (the goal and six outcome lines) of 132 each. The lines' 2,000 became
# 2,760 when the goal's cap rose to 1,000 (owner, 2026-10-27), then 6,560, re-measured when the
# lines rose to 800 (owner, 2026-11-12; `correction.LINES_CAP_CHARS` has the measurement):
# 6,560 + 8 * 277 + 7 * 132 = 9,700.
# `correction.py` holds the parts and `test_correction` the sum.
CORRECTION_CAP_CHARS = 9700
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
# A store past this reads back as nothing, un-marking every recognised paste at once.
# Keep a quarter spare after adding the in-flight fragment proof and the
# inode on each recognised occurrence. The full-bound store test holds that margin.
_READ_CAP_BYTES = 4 << 20
_KEY_CAP_CHARS = 64
# The copy route's own body bound, derived so no correction the box composes is refused for its
# bytes (review, 2026-10-20): the shared 12,288 refused 4,216 CJK characters, the page still said
# Copied, and the paste then counted as the reader's words. Twelve bytes a character is the widest
# any JSON encoding spells one code point (an escaped surrogate pair), for the text and for both
# identity fields at the widest this store keeps them, with room for the object around them:
# 12 * (9,700 + 2 * 64) + 256 = 118,192 bytes.
COPY_BODY_CAP_BYTES = 12 * (CORRECTION_CAP_CHARS + 2 * _KEY_CAP_CHARS) + 256
_LOCK_WAIT_SECONDS = 10.0
HARNESSES = frozenset({"claude", "codex"})

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
    prefix_count: NotRequired[int]
    prefix_digest: NotRequired[str]
    fragment_start: NotRequired[int]
    fragment_digest: NotRequired[str]


class Match(TypedDict):
    """A message recognised as a copy, kept once found: `at` is the message's own time."""

    fact_id: str
    at: float
    copied_at: float
    record_digest: NotRequired[str]
    ino: NotRequired[int]


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
    count, prefix = _count(value.get("prefix_count")), value.get("prefix_digest")
    if count and isinstance(prefix, str) and _DIGEST.fullmatch(prefix):
        copy["prefix_count"] = count
        copy["prefix_digest"] = prefix
    start, fragment = _count(value.get("fragment_start")), value.get("fragment_digest")
    if "fragment_start" in value or "fragment_digest" in value:
        if (
            start is None
            or start >= offset
            or not isinstance(fragment, str)
            or not _DIGEST.fullmatch(fragment)
        ):
            return None
        copy["fragment_start"], copy["fragment_digest"] = start, fragment
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
    match: Match = {"fact_id": fact_id, "at": at, "copied_at": copied_at}
    record_digest = value.get("record_digest")
    if isinstance(record_digest, str) and _DIGEST.fullmatch(record_digest):
        match["record_digest"] = record_digest
    ino = _count(value.get("ino"))
    if ino is not None:
        match["ino"] = ino
    return match


def _held(copies: Iterable[Copy], matches: Iterable[Match]) -> Held:
    """Each list in recording order, bounded, the oldest dropped; a fact id kept once."""
    ordered = sorted(copies, key=lambda copy: copy["copied_at"])
    unique: dict[str, Match] = {}
    for match in sorted(matches, key=lambda match: match["copied_at"]):
        unique.setdefault(match.get("record_digest") or match["fact_id"], match)
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
        with os.fdopen(
            runtime_io.open_regular(store_path(config), root=str(config.state_home)), "rb"
        ) as handle:
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
            (
                c
                for c in map(_copy, raw_copies if isinstance(raw_copies, list) else ())
                if c and (key[0] != "codex" or "prefix_digest" in c)
            ),
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


class _CodexPosition(NamedTuple):
    ino: int
    offset: int
    prefix_count: int
    digest: str
    fragment: tuple[int, str] | None
    prior: tuple[Copy, ...]
    verified: tuple[int, ...]


_Position = tuple[int, int] | _CodexPosition


class _CodexRecord(NamedTuple):
    offset: int
    raw: bytes
    record: dict[str, Any]
    occurrence: str
    prefix_count: int


def _file_stamp(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _codex_prompt_content(record: dict[str, Any]) -> tuple[str, Any]:
    payload = records.as_dict(record.get("payload"))
    if record.get("type") == "response_item":
        if payload.get("type") == "message" and payload.get("role") == "user":
            return "response", payload.get("content")
    elif record.get("type") == "event_msg":
        if payload.get("type") == "user_message":
            return "legacy", payload.get("message")
        item = records.as_dict(payload.get("item"))
        if payload.get("type") == "item_completed" and item.get("type") == "UserMessage":
            return "completion", item.get("content")
    return "", None


def _codex_prefixes(handle: BinaryIO, size: int) -> Iterable[_CodexRecord]:
    """Order prompt occurrences by a canonical hash chain, even when their JSON is rewritten."""
    proof = hashlib.sha256(b"compass-codex-copy-v2\0")
    count = offset = 0
    markers = (*transcripts._CODEX_SCAN_MARKERS, b'"session_meta"', b"\\u", b"task_complete")  # noqa: SLF001
    while offset < size:
        raw = handle.readline(size - offset)
        if not raw:
            break
        record: dict[str, Any] = {}
        occurrence = ""
        if raw.endswith(b"\n") and any(marker in raw for marker in markers):
            canonical = b""
            with contextlib.suppress(ValueError, RecursionError):
                record = records.as_dict(json.loads(raw))
                if record.get("type") == "session_meta" or _codex_prompt_content(record)[0]:
                    canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
            if canonical:
                proof.update(canonical)
                proof.update(b"\0")
                count += 1
                occurrence = proof.hexdigest()
        yield _CodexRecord(offset, raw, record, occurrence, count)
        offset += len(raw)


def _stable_extent(handle: BinaryIO, before: os.stat_result, proof: str) -> bool:
    after = os.fstat(handle.fileno())
    if _file_stamp(before) == _file_stamp(after):
        return True
    if after.st_size <= before.st_size:
        return False
    # An append may change the stamp during either read. Verify the bytes the
    # scan could have observed, stopping at its original extent.
    handle.seek(0)
    remaining = before.st_size
    check = hashlib.sha256()
    while remaining:
        chunk = handle.read(min(remaining, 1 << 20))
        if not chunk:
            return False
        check.update(chunk)
        remaining -= len(chunk)
    return check.hexdigest() == proof and os.fstat(handle.fileno()).st_size >= after.st_size


class _CodexBoundaries:
    def __init__(self, info: os.stat_result, waiting: tuple[Copy, ...]) -> None:
        self.waiting = waiting
        self.ino = info.st_ino
        self.prefixes: dict[tuple[int, str], int] = {}
        self.boundaries: dict[int, int] = {}
        self.fragments: dict[int, list[int]] = {}
        self.wanted = {
            (copy.get("prefix_count", 0), copy.get("prefix_digest", ""))
            for copy in waiting
            if copy["ino"] == info.st_ino
        }
        for index, copy in enumerate(waiting):
            if copy["ino"] == info.st_ino and "fragment_digest" in copy:
                self.fragments.setdefault(copy["fragment_start"], []).append(index)

    def observe(self, item: _CodexRecord) -> None:
        end = item.offset + len(item.raw)
        key = (item.prefix_count, item.occurrence)
        if key in self.wanted:
            self.prefixes[key] = end
            for index, copy in enumerate(self.waiting):
                if (
                    copy["ino"] == self.ino
                    and "fragment_digest" not in copy
                    and self.prefix(copy) == end
                ):
                    self.boundaries[index] = end
        for index in self.fragments.get(item.offset, []):
            copy = self.waiting[index]
            width = copy["offset"] - item.offset
            if (
                0 < width <= len(item.raw)
                and self.prefix(copy) is not None
                and hashlib.sha256(item.raw[:width]).hexdigest() == copy["fragment_digest"]
            ):
                self.boundaries[index] = end

    def prefix(self, copy: Copy) -> int | None:
        return self.prefixes.get((copy.get("prefix_count", 0), copy.get("prefix_digest", "")))


def _codex_position(path: str, prior: tuple[Copy, ...]) -> _CodexPosition | None:
    with os.fdopen(runtime_io.open_harness(path), "rb") as handle:
        info = os.fstat(handle.fileno())
        boundaries = _CodexBoundaries(info, prior)
        raw_proof = hashlib.sha256()
        count, occurrence, fragment = 0, "", None
        for item in _codex_prefixes(handle, info.st_size):
            if item.occurrence:
                count, occurrence = item.prefix_count, item.occurrence
            if not item.raw.endswith(b"\n"):
                fragment = (item.offset, hashlib.sha256(item.raw).hexdigest())
            boundaries.observe(item)
            raw_proof.update(item.raw)
        if (
            occurrence
            and handle.tell() == info.st_size
            and _stable_extent(handle, info, raw_proof.hexdigest())
        ):
            return _CodexPosition(
                info.st_ino,
                info.st_size,
                count,
                occurrence,
                fragment,
                prior,
                tuple(boundaries.boundaries),
            )
    return None


def transcript_position(
    config: RuntimeConfig, state: RuntimeState, harness: str, sid: str
) -> _Position | None:
    """Snapshot the end of the transcript when the copy arrives."""
    path = observer.resolve_transcript(config, state, harness, sid)
    if not path:
        return None
    try:
        if harness == "codex":
            prior = load(config).get(_key(harness, sid), Held((), ()))
            return _codex_position(path, prior.copies)
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
            runtime_io.ensure_owner_dir(str(config.state_home), root=str(config.state_home))
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
    position: _Position | None,
    diagnostic_sink: Any = print,
) -> str:
    """Record that this text was copied for this session. Returns an outcome token.

    `position` is where the session's transcript ended when the copy was made
    (`transcript_position`); only a message written past it can match, whatever its clock says.
    A second press preserves a waiting copy when its first boundary still verifies.
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
        or (key[0] == "codex" and not isinstance(position, _CodexPosition))
    ):
        return OUTCOME_REFUSED
    copy: Copy = {
        "digest": digest(text),
        "copied_at": moment,
        "ino": position[0],
        "offset": position[1],
        "folded": folded_digest(text),
    }
    if isinstance(position, _CodexPosition):
        copy["prefix_count"], copy["prefix_digest"] = position.prefix_count, position.digest
        if position.fragment:
            copy["fragment_start"], copy["fragment_digest"] = position.fragment

    def change(stored: dict[tuple[str, str], Held]) -> dict[tuple[str, str], Held] | None:
        prior = stored.get(key, Held((), ()))
        same = next((item for item in prior.copies if item["digest"] == copy["digest"]), None)
        if same is not None and (
            not isinstance(position, _CodexPosition)
            or same not in position.prior
            or position.prior.index(same) in position.verified
        ):
            return None
        remaining = tuple(item for item in prior.copies if item != same)
        stored[key] = _held((*remaining, copy), prior.matches)
        return stored

    return _locked_update(config, change, diagnostic_sink)


def _record(config: RuntimeConfig, key: tuple[str, str], found: list[tuple[Copy, Match]]) -> None:
    """Move each recognised copy from waiting to recognised, so it is never recomputed away.

    A store another dashboard emptied meanwhile (`--forget`) is left empty. A write that fails
    leaves the copy waiting, and the next collection recognises it again.
    """

    def change(stored: dict[tuple[str, str], Held]) -> dict[tuple[str, str], Held] | None:
        prior = stored.get(key)
        if prior is None:
            return None
        current = [(copy, match) for copy, match in found if copy in prior.copies]
        if not current:
            return None
        stored[key] = _held(
            (copy for copy in prior.copies if all(copy != used for used, _ in current)),
            (*prior.matches, *(match for _, match in current)),
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
        runtime_io.atomic_write_owner_only(target, json.dumps(payload), root=str(config.state_home))
    except (OSError, ValueError):
        runtime_io.diag(
            f"Compass: could not write the copied-correction store "
            f"{runtime_io.value(store_path(config))}",
            diagnostic_sink,
        )
        return OUTCOME_UNWRITABLE
    return OUTCOME_STORED


def forget(config: RuntimeConfig) -> bool:
    """Delete the store, reporting whether there was one. Independent of the flag, for
    `history.forget`'s reason."""
    return remove_state_file(store_path(config))


def _scan(
    config: RuntimeConfig, path: str, key: tuple[str, str], start: int, end: int
) -> tuple[list[_Message], int]:
    """Each user message whose record begins in `[start, end)`, and where the scan stopped.

    The fact id is recomputed exactly as `project_context.direction_text` recomputes it. The
    digest is taken from the record's raw content, before the redaction and the clipping every
    published copy of it goes through, and is None for a message too long to be any correction.
    A record `start` falls inside was being written before it, so it is skipped; a last line with
    no newline is still being written, so the scan stops before it and reads it next time.
    """
    harness, sid = key
    out: list[_Message] = []
    # The collector's own spelling, frozen.
    steer = project_context._SEMANTIC_FACT_TYPES["steer"]  # noqa: SLF001
    with os.fdopen(runtime_io.open_harness(path), "rb") as handle:
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
                raw, harness
            ):
                continue
            try:
                record = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            event = project_context._instruction_event(config, record, harness, sid)  # noqa: SLF001
            if event is None:
                continue
            fact = project_context._semantic_fact_from_event(event, "steer", steer, "")  # noqa: SLF001
            text = records.extract_text(
                records.message_dict(record).get("content"), cap=_MESSAGE_READ_CAP
            )
            whole = len(text) < _MESSAGE_READ_CAP
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
    key: tuple[str, str],
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
    return _scan(config, path, key, start, end)[0]


def _messages(
    config: RuntimeConfig, state: RuntimeState, path: str, key: tuple[str, str], start: int
) -> tuple[list[_Message], int, int]:
    """The user messages from `start` to the end of the transcript, with its inode and size.

    Read incrementally: what an earlier collection scanned is kept in memory and only the bytes
    since are read, so a copy waiting for its message costs one read of the transcript, not one
    per collection. First of a duplicate pair, as `direction_text` keeps it.
    """
    info = os.stat(path)
    opening_start = max(start, 0)
    start = max(start, info.st_size - config.direction_scan_max_bytes, 0)
    harness, sid = key
    cache_key = f"copied-corrections:{harness}:{sid}:{path}"
    with state.cache_lock:
        cached = state.metadata_cache.get(cache_key)
    if (
        cached is not None
        and cached["ino"] == info.st_ino
        and cached["start"] <= start
        and cached["end"] <= info.st_size
    ):
        more, end = _scan(config, path, key, max(cached["end"], start), info.st_size)
        found = [m for m in cached["messages"] if m.position >= start] + more
    else:
        found, end = _scan(config, path, key, start, info.st_size)
    opening_end = min(info.st_size, _OPENING_SCAN_CAP_BYTES)
    opening = _opening_messages(config, path, key, info, cached, opening_start, opening_end, start)
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


class _Prompt(NamedTuple):
    text: str
    at: float
    occurrence: str
    offset: int

    @property
    def words(self) -> tuple[str, float]:
        return self.text, self.at


class _CodexPrompts:
    def __init__(self) -> None:
        self.first: _Prompt | None = None
        self.latest: _Prompt | None = None
        self.earlier: _Prompt | None = None
        self.work: _Prompt | None = None
        self.floor = -1
        self.preamble: tuple[str, float] | None = None
        self.response: tuple[str, str] | None = None

    def observe(self, config: RuntimeConfig, item: _CodexRecord) -> None:
        kind, text, at = transcripts._codex_scan_record(item.record)  # noqa: SLF001
        if kind == "floor":
            self.floor, self.preamble, self.response = item.offset, None, None
        elif kind == "compaction":
            self.work, self.response = None, None
        elif kind == "commentary" and text.strip():
            if self.preamble is None:
                self.preamble = (text, at)
            self.response = None
        elif kind == "prompt":
            self._prompt(config, item, text, at)
        elif records.as_dict(item.record.get("payload")).get("type") == "task_complete":
            self.response = None

    def _prompt(self, config: RuntimeConfig, item: _CodexRecord, text: str, at: float) -> None:
        body = text.strip()
        if not body or records.injected_prompt(body, "codex"):
            self.response = None
            return
        shape, content = _codex_prompt_content(item.record)
        full = records.extract_text(content, cap=_MESSAGE_READ_CAP)
        occurrence = item.occurrence
        # Both Codex companions can carry the board's timestamp. Whole text
        # and the preceding response in this turn establish which words they quote.
        pair = self.response if shape in {"legacy", "completion"} else None
        if pair is not None and pair[0] == full:
            occurrence = pair[1]
        self.response = (
            (full, item.occurrence)
            if shape == "response" and 0 < len(full) < _MESSAGE_READ_CAP
            else None
        )
        first = (
            self.first is None
            and item.offset + len(item.raw) <= 2 * 1024 * 1024
            and not records.compass_command(text)
        )
        if first:
            self.first = _Prompt(text, at, occurrence, item.offset)
        prompt = _Prompt(body, at, occurrence, item.offset)
        self.latest, self.earlier, self.preamble = prompt, self.work, None
        if transcripts.states_work(config, body):
            self.work = prompt

    def fields(self, config: RuntimeConfig) -> tuple[dict[str, Any], dict[str, str]]:
        first, latest, earlier = self.first, self.latest, self.earlier
        cap = records.INSTRUCTION_CAP_CHARS
        opening = transcripts.prompt_title(config, first.text, cap) if first else ""
        title_cap = records.PROMPT_TITLE_CAP_CHARS
        title = transcripts.prompt_title(config, latest.text, title_cap) if latest else ""
        # The backward ladder accepts preamble only if it reaches a turn floor
        # before stopping at the earlier work. Preserve that rule in this forward scan.
        reached_floor = self.floor > (earlier.offset if earlier else -1)
        instruction = transcripts.instruction_from(
            config,
            latest.words if latest else None,
            self.preamble if reached_floor else None,
            earlier.words if earlier else None,
            title_is_prompt=True,
        )
        fields = {
            "first_prompt": records.safe_text(opening, cap + 1),
            "first_prompt_at": first.at if first and first.at > 0 else None,
            "first_prompt_control": bool(
                first and transcripts.harness_control_prompt(config, first.text)
            ),
            "title": records.safe_text(title, title_cap + 1).strip() or None,
            "prompt_at": latest.at if latest and latest.at > 0 else None,
            "prompt_states_work": bool(latest and transcripts.states_work(config, latest.text)),
            "last_prompt": records.safe_text(
                latest.text if latest else "", records.LAST_PROMPT_CAP_CHARS
            ),
            "instruction": instruction,
        }
        sources = {
            "title": latest.occurrence if latest else "",
            "first_prompt": first.occurrence if first else "",
            "instruction": earlier.occurrence
            if earlier and instruction and instruction.get("label") == "earlier"
            else "",
        }
        return fields, sources


class _FactProof(NamedTuple):
    source: str
    words: str
    complete: str


class _Published(list[dict[str, Any]]):
    """Keep proofs beside the snapshot for server consumers. JSON emits only the list entries."""

    def __init__(
        self,
        items: Iterable[dict[str, Any]],
        proofs: dict[str, _FactProof],
        path: str,
        stamp: tuple[int, int, int, int, int],
    ) -> None:
        super().__init__(items)
        self.proofs, self.path, self.stamp = proofs, path, stamp

    def source_unchanged(self) -> bool:
        try:
            return _file_stamp(os.stat(self.path)) == self.stamp
        except OSError:
            return False


class _BoardBody(bytes):
    sources: dict[tuple[str, str], _Published]

    def __new__(cls, body: bytes, sources: dict[tuple[str, str], _Published]) -> Self:
        result = super().__new__(cls, body)
        result.sources = sources
        return result


def bind_board_sources(body: bytes, rows: Iterable[Mapping[str, Any]]) -> bytes:
    # The shared snapshot caches these exact bytes. A parallel refresh cannot
    # pick a different set of witnesses for an older body's prompt fields.
    sources = {}
    for row in rows:
        entries = row.get(reading.COPIED_PROMPTS)
        if isinstance(entries, _Published) and entries.proofs:
            sources[_key(row.get("harness"), row.get("sid"))] = entries
    return _BoardBody(body, sources) if sources else body


def restore_board_sources(body: bytes, rows: Iterable[dict[str, Any]]) -> None:
    if isinstance(body, _BoardBody):
        for row in rows:
            entries = body.sources.get(_key(row.get("harness"), row.get("sid")))
            if entries is not None:
                row[reading.COPIED_PROMPTS] = _Published(
                    row[reading.COPIED_PROMPTS], entries.proofs, entries.path, entries.stamp
                )


class _CodexSnapshot(NamedTuple):
    fields: dict[str, Any]
    matches: tuple[Match, ...]
    sources: dict[str, str]
    facts: dict[str, _FactProof]
    stamp: tuple[int, int, int, int, int]


class _CodexRecognition:
    def __init__(self, info: os.stat_result, held: Held) -> None:
        self.boundaries = _CodexBoundaries(info, held.copies)
        self.ino = info.st_ino
        self.waiting = held.copies
        self.stored = {
            match["record_digest"]: match
            for match in held.matches
            if match.get("ino") == self.ino and "record_digest" in match
        }
        self.new: dict[int, Match] = {}
        self.matches: list[Match] = []
        self.facts: dict[str, _FactProof] = {}
        self.seen: set[str] = set()

    def observe(self, config: RuntimeConfig, sid: str, item: _CodexRecord) -> None:
        self.boundaries.observe(item)
        shape, content = _codex_prompt_content(item.record)
        if shape != "response":
            return
        event = project_context._instruction_event(config, item.record, "codex", sid)  # noqa: SLF001
        if event is None:
            return
        fact = project_context._semantic_fact_from_event(  # noqa: SLF001
            event, "steer", "user_message", ""
        )
        fact_id = str(fact["fact_id"])
        match = self.stored.get(item.occurrence)
        if match is None:
            match = self._new_match(item, content, fact_id, float(event["at"]))
        if fact_id in self.seen:
            self.facts.pop(fact_id, None)
        elif match is not None:
            self.facts[fact_id] = _FactProof(
                hashlib.sha256(item.raw.rstrip(b"\r\n")).hexdigest(),
                digest(fact[project_context.READER_WORDS_FIELD])
                if fact.get(project_context.READER_WORDS_FIELD)
                else "",
                project_context._complete_request_digest(  # noqa: SLF001
                    project_context._direction_words(config, item.record, "codex"),  # noqa: SLF001
                ),
            )
        self.seen.add(fact_id)
        if match is not None:
            self.matches.append(match)

    def _new_match(self, item: _CodexRecord, content: Any, fact_id: str, at: float) -> Match | None:
        eligible = [
            index
            for index, offset in self.boundaries.boundaries.items()
            if item.offset >= offset and index not in self.new
        ]
        if not eligible:
            return None
        blocks = [
            block["text"]
            for block in records.as_list(content)
            if isinstance(block, dict)
            and block.get("type") == "input_text"
            and isinstance(block.get("text"), str)
        ]
        text = records.extract_text(blocks, cap=_MESSAGE_READ_CAP)
        if len(text) >= _MESSAGE_READ_CAP:
            return None
        exact, folded = digest(text), folded_digest(text)
        for index in eligible:
            copy = self.waiting[index]
            if exact == copy["digest"] or folded == copy.get("folded"):
                match: Match = {
                    "fact_id": fact_id,
                    "at": at,
                    "copied_at": copy["copied_at"],
                    "record_digest": item.occurrence,
                    "ino": self.ino,
                }
                self.new[index] = match
                return match
        return None


def _codex_snapshot(
    config: RuntimeConfig, state: RuntimeState, path: str, sid: str, held: Held
) -> _CodexSnapshot | None:
    cache_key = f"codex-copied-snapshot:{sid}:{path}"
    try:
        with os.fdopen(runtime_io.open_harness(path), "rb") as handle:
            info = os.fstat(handle.fileno())
            stamp = _file_stamp(info)
            with state.cache_lock:
                cached = state.metadata_cache.get(cache_key)
            if cached is not None and cached["stamp"] == stamp and cached["held"] == held:
                snapshot = cached.get("snapshot")
                if isinstance(snapshot, _CodexSnapshot):
                    return snapshot
            recognition, prompts = _CodexRecognition(info, held), _CodexPrompts()
            raw_proof = hashlib.sha256()
            for item in _codex_prefixes(handle, info.st_size):
                raw_proof.update(item.raw)
                recognition.observe(config, sid, item)
                if item.record:
                    prompts.observe(config, item)
            if handle.tell() != info.st_size or not _stable_extent(
                handle, info, raw_proof.hexdigest()
            ):
                return None
    except OSError:
        return None
    found = [(held.copies[index], match) for index, match in recognition.new.items()]
    if found:
        _record(config, ("codex", sid), found)
    fields, sources = prompts.fields(config)
    matches = _held((), recognition.matches).matches
    snapshot = _CodexSnapshot(fields, matches, sources, recognition.facts, stamp)
    with state.cache_lock:
        runtime_state.bounded_put(
            state.metadata_cache,
            cache_key,
            {"stamp": stamp, "held": held, "snapshot": snapshot},
            limit=config.max_cache_entries,
        )
    return snapshot


def _codex_paths(config: RuntimeConfig, state: RuntimeState, wanted: set[str]) -> dict[str, str]:
    # Keep the board collector's root selection and tie order without asking the
    # single-session observer to walk every rollout once per held session.
    latest: dict[str, tuple[float, str]] = {}
    for path in runtime_io.glob_stores(config, "codex.sessions", "*", "*", "*", "rollout-*.jsonl"):
        meta = transcripts.codex_meta(config, state, path)
        sid = meta.get("session_id") or os.path.basename(path).removesuffix(".jsonl")[-36:]
        if sid not in wanted or meta.get("subagent"):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if sid not in latest or mtime > latest[sid][0]:
            latest[sid] = (mtime, path)
    return {sid: path for sid, (_, path) in latest.items()}


def collect_codex_prompts(
    config: RuntimeConfig, state: RuntimeState, rows: list[dict[str, Any]]
) -> None:
    held = load(config)
    wanted = {row["sid"] for row in rows if ("codex", row["sid"]) in held}
    if not wanted:
        return
    paths = _codex_paths(config, state, wanted)
    for row in rows:
        sid = row["sid"]
        if sid not in paths:
            continue
        snapshot = _codex_snapshot(config, state, paths[sid], sid, held[("codex", sid)])
        if snapshot is None:
            continue
        active = bool(row.get("active"))
        if active:
            row.update(snapshot.fields)
            if not row["title"] and (goal := row.get("session_goal")):
                row["title"] = transcripts.prompt_title(config, goal["text"])
        row[reading.COPIED_PROMPTS] = _codex_published(snapshot, paths[sid], active=active)


def _codex_published(snapshot: _CodexSnapshot, path: str, *, active: bool) -> _Published:
    return _Published(
        (
            {
                "fact_id": match["fact_id"],
                "at": match["at"],
                reading.QUOTED_AS: [
                    field
                    for field, source in snapshot.sources.items()
                    if active and source == match["record_digest"]
                ],
            }
            for match in sorted(snapshot.matches, key=lambda match: match["at"])
        ),
        snapshot.facts,
        path,
        snapshot.stamp,
    )


def _recognise(
    config: RuntimeConfig, state: RuntimeState, key: tuple[str, str], held: Held, path: str | None
) -> tuple[tuple[Match, ...], list[_Message]]:
    """This session's recognised messages, the stored ones and any found now, and the messages
    read on the way (the tail, at least), for `attach` to place the row's instruction among."""
    harness, _ = key
    if harness not in HARNESSES:
        return (), []
    if not path:
        return held.matches, []
    try:
        info = os.stat(path)
        # Keep the opening range for provenance even when Claude's saved offset
        # no longer points into the current file.
        waiting = [copy["offset"] for copy in held.copies]
        start = min([max(0, info.st_size - config.tail_bytes), *waiting])
        messages, ino, size = _messages(config, state, path, key, start)
    except OSError:
        return held.matches, []
    taken = {match["fact_id"] for match in held.matches}
    found: list[tuple[Copy, Match]] = []
    for copy in held.copies:
        offset = copy["offset"]
        if copy["ino"] != ino or offset > size:
            continue
        for message in messages:
            if message.position >= offset and _same(message, copy) and message.fact_id not in taken:
                taken.add(message.fact_id)
                match: Match = {
                    "fact_id": message.fact_id,
                    "at": message.at,
                    "copied_at": copy["copied_at"],
                }
                found.append((copy, match))
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
    path = observer.resolve_transcript(config, state, *key)
    if key[0] == "codex":
        snapshot = _codex_snapshot(config, state, path, key[1], entry) if path else None
        return _published(snapshot.matches) if snapshot else ()
    found, _ = _recognise(config, state, key, entry, path)
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

    Claude's fields carry no record id, so each is placed on the message it quotes: the message with
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
    quoted: dict[str, list[str]] = {match["fact_id"]: [] for match in found}
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
        harness, sid = key
        if harness == "codex":
            row.setdefault(reading.COPIED_PROMPTS, [])
            continue
        entry = held.get(key)
        if entry is None:
            row[reading.COPIED_PROMPTS] = []
            continue
        path = observer.resolve_transcript(config, state, harness, sid)
        found, messages = _recognise(config, state, key, entry, path)
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
        _key(row.get("harness"), row.get("sid")): row[reading.COPIED_PROMPTS]
        for row in rows
        if row.get(reading.COPIED_PROMPTS)
    }
    raw = context.get("semantic")
    semantic: dict[str, Any] = raw if isinstance(raw, dict) else {}
    facts = semantic.get("facts")
    if not wanted or not isinstance(facts, list):
        return dict(context)

    unchanged: dict[str, bool] = {}

    def marked(fact: Any) -> Any:
        if not isinstance(fact, dict) or fact.get("type") != "user_message":
            return fact
        session = fact.get("source_session")
        if not isinstance(session, dict):
            return fact
        key = _key(session.get("harness"), session.get("sid"))
        entries = wanted.get(key, ())
        fact_id = str(fact.get("fact_id"))
        if isinstance(entries, _Published):
            if not _matches_fact_proof(fact, entries, unchanged):
                return fact
        elif session.get("harness") == "codex" or not any(
            isinstance(entry, dict) and entry.get("fact_id") == fact_id for entry in entries
        ):
            return fact
        return {**fact, reading.COPIED_FLAG: True}

    return {**context, "semantic": {**semantic, "facts": [marked(fact) for fact in facts]}}


def mark_direction(
    fact: dict[str, Any], row: Mapping[str, Any], words: project_context.DirectionText
) -> dict[str, Any]:
    if row.get("harness") == "codex":
        fact = {**fact, "request_words_digest": project_context._complete_request_digest(words)}  # noqa: SLF001
    marked: dict[str, Any] = mark({"semantic": {"facts": [fact]}}, [row])["semantic"]["facts"][0]
    return marked


def _matches_fact_proof(
    fact: Mapping[str, Any], entries: _Published, unchanged: dict[str, bool]
) -> bool:
    proof = entries.proofs.get(str(fact.get("fact_id")))
    if proof is None:
        return False
    if "request_source_digest" in fact:
        return bool(fact["request_source_digest"] == proof.source)
    # A projected or redacted fact alone cannot distinguish a rewrite from
    # the collected occurrence. Direct source proofs can.
    if entries.path not in unchanged:
        unchanged[entries.path] = entries.source_unchanged()
    if not unchanged[entries.path]:
        return False
    if "request_words_digest" in fact:
        return bool(proof.complete and fact["request_words_digest"] == proof.complete)
    words = fact.get(project_context.READER_WORDS_FIELD)
    return bool(isinstance(words, str) and words and digest(words) == proof.words)
