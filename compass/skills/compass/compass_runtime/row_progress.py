"""In-process Sessions progress, recomputed by the focused page and checked at publication."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

from . import annotations as annotation_store
from . import declared_sessions, levels, reading_evidence, semantic_history
from .state import bounded_put

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .config import RuntimeConfig
    from .state import RuntimeState

MAX_AGE_SEC = 300
RETRY_SEC = 15
DEPARTURES = frozenset({levels.MEDIUM, levels.HIGH, levels.EXTREME})
OUT_OF_DATE = "out-of-date"
GOAL_UNCLEAR = "goal-unclear"

_SESSION_FIELDS = frozenset(
    {
        "harness",
        "sid",
        "state",
        "ended_at",
        "copied_prompts",
        "instruction",
        "first_prompt",
        "first_prompt_at",
        "prompt_states_work",
        "title",
        "prompt_at",
        "session_goal",
        "first_prompt_control",
    }
)
_INPUT_FIELDS = ("annotate", "annotate_unreadable", "reading_routes")


def derive_inputs(
    row: Mapping[str, Any], payload: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    session = {
        key: value
        for key, value in declared_sessions.model_row(row).items()
        if key.startswith("annotation_") or key in _SESSION_FIELDS
    }
    return session, {key: payload.get(key) for key in _INPUT_FIELDS}


def key(row: Mapping[str, Any], session: dict[str, Any], inputs: dict[str, Any]) -> bytes:
    data = [row.get("project"), reading_evidence.project_key(row), session, inputs]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).digest()


def identity(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("harness") or ""), str(row.get("sid") or "")


def eligible(row: Mapping[str, Any]) -> bool:
    harness, sid = identity(row)
    assessment = row.get("annotation_assessment")
    return (
        bool(harness and sid)
        and harness != "codex"
        and isinstance(assessment, dict)
        and bool(assessment)
        and not row.get("annotation_goal_unreadable")
        and not row.get("annotation_not_accurate")
    )


def published(level: str | None) -> dict[str, str | None]:
    return {"stored_progress": level}


def token(view: Mapping[str, Any]) -> str | None:
    if view.get("stale"):
        return OUT_OF_DATE
    if view.get("latest_check_withheld"):
        return None
    pill = view.get("pill")
    if isinstance(pill, dict) and pill.get("source") == "analysis":
        level = pill.get("level")
        if isinstance(level, str) and level in DEPARTURES:
            return level
    analysis = view.get("analysis")
    reasons = analysis.get("reasons") if isinstance(analysis, dict) else None
    if isinstance(reasons, list) and levels.REASON_GOAL_UNCLEAR in reasons:
        return GOAL_UNCLEAR
    return None


class Transcript(NamedTuple):
    path: str
    device: int
    inode: int
    mode: int
    size: int
    modified_ns: int
    changed_ns: int


def transcript(path: str) -> Transcript | None:
    try:
        info = os.stat(path, follow_symlinks=False)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444:
        return None
    return Transcript(
        path,
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def current_transcript(state: RuntimeState, owner: tuple[str, str], path: str) -> Transcript | None:
    if (owner[0] == "claude" and owner[1] in state.claude_transcript_collisions) or not os.access(
        os.path.dirname(path), os.R_OK | os.X_OK
    ):
        return None
    return transcript(path)


def annotation_stamp(config: RuntimeConfig) -> tuple[int, ...] | None:
    try:
        info = os.stat(annotation_store.store_path(config), follow_symlinks=False)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o444:
        return None
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class Memo:
    key: bytes
    read_at: float
    transcript: Transcript
    token: str | None
    at: float

    def matches(self, row: Mapping[str, Any], row_key: bytes, current: Transcript | None) -> bool:
        assessment = row.get("annotation_assessment")
        return (
            isinstance(assessment, dict)
            and self.read_at == assessment.get("read_at")
            and self.key == row_key
            and self.transcript == current
        )


def make_memo(
    row: Mapping[str, Any], row_key: bytes, seen: Transcript, token: str | None, now: float
) -> Memo | None:
    assessment = row.get("annotation_assessment")
    read_at = assessment.get("read_at") if isinstance(assessment, dict) else None
    if not isinstance(read_at, (int, float)) or transcript(seen.path) != seen:
        return None
    return Memo(row_key, read_at, seen, token, now)


def remember(
    config: RuntimeConfig, state: RuntimeState, owner: tuple[str, str], memo: Memo | None
) -> bool:
    """Whether the published answer might change. The warmer batches snapshot invalidations."""
    with state.row_progress_lock:
        before = state.row_progress.get(owner)
        if memo is None:
            state.row_progress.pop(owner, None)
        else:
            bounded_put(state.row_progress, owner, memo, limit=config.max_cache_entries)
    old = (
        (before.key, before.transcript, before.token)
        if before and before.token and (memo is None or 0 <= memo.at - before.at < MAX_AGE_SEC)
        else None
    )
    new = (memo.key, memo.transcript, memo.token) if memo and memo.token else None
    return old != new


@dataclass(frozen=True)
class Proof:
    row: dict[str, Any]
    entry: annotation_store.Annotation
    memo: Memo
    floor: float | None

    def holds(self, config: RuntimeConfig, state: RuntimeState, now: float) -> bool:
        memo = self.memo
        if not 0 <= now - memo.at < MAX_AGE_SEC:
            return False
        owner = identity(self.row)
        with state.row_progress_lock:
            standing = state.row_progress.get(owner)
        if standing is None or (
            standing.key,
            standing.read_at,
            standing.transcript,
            standing.token,
        ) != (memo.key, memo.read_at, memo.transcript, memo.token):
            return False
        current = current_transcript(state, owner, memo.transcript.path)
        if current is None or current[:4] != memo.transcript[:4]:
            return False
        if current != memo.transcript and (
            memo.token != OUT_OF_DATE or current.size <= memo.transcript.size
        ):
            return False
        try:
            project = reading_evidence.project_key(self.row)
            return reading_evidence.held(
                self.entry,
                self.row,
                mark=semantic_history.mark_for(config, state, project),
                transcript_bytes=current.size,
                floor=self.floor,
            ).ok
        except Exception:  # noqa: BLE001 - uncertainty about one row must not fail the poll
            return False


def _proof(
    row: dict[str, Any],
    collection: Mapping[str, Any],
    entry: annotation_store.Annotation | None,
    memo: Memo,
) -> Proof | None:
    assessment = entry.get("assessment") if entry else None
    if (
        not assessment
        or entry is None
        or entry.get("not_accurate")
        or (
            isinstance(row.get("annotation_assessment"), dict)
            and row["annotation_assessment"].get("scope") == "withdrawn"
            and memo.token != OUT_OF_DATE
        )
        or memo.read_at != assessment.get("read_at")
        or memo.key != key(row, *derive_inputs(row, collection))
    ):
        return None
    return Proof(row, entry, memo, annotation_store.direction_floor(entry, row))


def publish(
    collection: dict[str, Any],
    config: RuntimeConfig,
    state: RuntimeState,
    clock: Callable[[], float],
    stamp: tuple[int, ...] | None,
) -> Callable[[float], bool] | None:
    """Attach only proven tokens after the annotation and SessionEnd overlays.

    Reused snapshot bytes also need their proofs checked. Their row fields are immutable, so
    a cached response only has to recheck the stores and transcript metadata, without hashing
    the row or deserializing the body again.
    """
    if not stamp or not collection.get("annotate") or collection.get("annotate_unreadable"):
        return None
    with state.row_progress_lock:
        memos = state.row_progress.copy()
    if not memos:
        return None
    rows = collection["sessions"]
    counts = Counter(map(identity, rows))
    entries = {
        (entry["harness"], entry["sid"]): entry for entry in annotation_store.active(config, state)
    }
    now = clock()
    proofs = []
    for row in rows:
        owner = identity(row)
        memo = memos.get(owner)
        if not memo or not memo.token or counts[owner] != 1 or not eligible(row):
            continue
        proof = _proof(row, collection, entries.get(owner), memo)
        if proof is not None and proof.holds(config, state, now):
            proofs.append(proof)

    def stores_readable() -> bool:
        # A chmod need not change the history parser's cached inode, size or mtime.
        return annotation_stamp(config) == stamp and os.access(
            semantic_history.store_path(config), os.R_OK
        )

    if not proofs or not stores_readable():
        return None
    for proof in proofs:
        proof.row.update(published(proof.memo.token))

    def valid(now: float) -> bool:
        return all(proof.holds(config, state, now) for proof in proofs) and stores_readable()

    return valid
