"""In-process Sessions progress, recomputed by the focused page and checked at publication."""

from __future__ import annotations

import errno
import fnmatch
import hashlib
import json
import os
import stat
import time
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple

from . import annotations as annotation_store
from . import declared_sessions, levels, reading_evidence, semantic_history
from . import io as runtime_io
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


class _DirectoryStamp(NamedTuple):
    device: int
    inode: int
    mode: int
    size: int
    links: int
    modified_ns: int
    changed_ns: int

    def settled(self, now_ns: int) -> bool:
        # HFS+ can retain the whole stamp across a same-second insertion. FAT mtime can
        # have a two-second tick, so reuse starts with a listing made outside that window.
        return now_ns - max(self.modified_ns, self.changed_ns) >= 2_000_000_000


class _ProjectNames(NamedTuple):
    stamp: _DirectoryStamp | None
    matches: dict[str, str | None]
    reusable: bool


def _directory_stamp(path: str) -> _DirectoryStamp | None:
    try:
        info = os.stat(path)
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}:
            return None
        raise
    if not stat.S_ISDIR(info.st_mode):
        return None
    return _DirectoryStamp(
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_nlink,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _claude_matches(directory: str, sids: frozenset[str]) -> dict[str, str | None] | None:
    matches: dict[str, str | None] = {}
    lengths = {len(sid) for sid in sids}
    try:
        listing = os.scandir(directory)
    except PermissionError:
        # The board's glob skips a project it cannot open. Retry if access is restored,
        # since an ancestor can grant it without changing this project's metadata.
        return None
    # Archived names can make a prefix ambiguous even when the board omits their rows.
    with listing as entries:
        for entry in entries:
            if entry.name.startswith(".") or not fnmatch.fnmatch(entry.name, "*.jsonl"):
                continue
            stem = entry.name.removesuffix(".jsonl")
            for length in lengths:
                sid = stem[:length]
                if len(sid) == length and sid in sids:
                    matches[sid] = None if sid in matches else entry.path
    return matches


class ClaudePrefixes:
    """Filename evidence for the footer's Claude rows, serialized by the footer writer."""

    def __init__(self, config: RuntimeConfig) -> None:
        self._roots = config.store_roots.get("claude.projects", ())
        self._root_stamps: dict[str, _DirectoryStamp | None] | None = None
        self._projects: dict[str, _ProjectNames] = {}
        self._sids: frozenset[str] = frozenset()

    def _sample_roots(self) -> dict[str, _DirectoryStamp | None]:
        return {root: _directory_stamp(root) for root in self._roots}

    def _project_paths(
        self, roots: Mapping[str, _DirectoryStamp | None], *, settled: bool
    ) -> list[str] | None:
        if settled and roots == self._root_stamps:
            return list(self._projects)
        directories: list[str] = []
        for root, stamp in roots.items():
            if stamp is None:
                continue
            # Tightening here changes the very metadata the validation brackets.
            if not runtime_io.admit_harness_root(root, tighten_permissions=False):
                return None
            with os.scandir(root) as entries:
                directories.extend(
                    entry.path
                    for entry in entries
                    if not entry.name.startswith(".")
                    and (entry.is_symlink() or entry.is_dir(follow_symlinks=False))
                )
        return directories

    def unambiguous(self, paths: Mapping[str, str]) -> set[str]:
        if not paths:
            return set()
        now_ns = time.time_ns()
        roots = self._sample_roots()
        roots_settled = all(stamp is None or stamp.settled(now_ns) for stamp in roots.values())
        directories = self._project_paths(roots, settled=roots_settled)
        if directories is None:
            return set()
        sids = frozenset(paths)
        projects = {}
        unique: dict[str, str | None] = {}
        # An append does not change the namespace. A settled listing can carry its name
        # evidence across touches, while a listing made inside the timestamp tick cannot.
        for directory in directories:
            stamp = _directory_stamp(directory)
            settled = stamp is None or stamp.settled(now_ns)
            cached = self._projects.get(directory)
            if (
                settled
                and cached is not None
                and cached.reusable
                and cached.stamp == stamp
                and sids == self._sids
            ):
                project = cached
            else:
                matches = _claude_matches(directory, sids) if stamp is not None else {}
                project = _ProjectNames(stamp, matches or {}, settled and matches is not None)
            projects[directory] = project
            for sid, path in project.matches.items():
                unique[sid] = None if sid in unique else path
        # A later project can take long enough for an earlier one's cached proof to change.
        if any(
            _directory_stamp(directory) != project.stamp for directory, project in projects.items()
        ):
            return set()
        if self._sample_roots() != roots:
            return set()
        self._root_stamps = roots if roots_settled else None
        self._projects, self._sids = projects, sids
        return {sid for sid, path in paths.items() if unique.get(sid) == path}


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


class Validation(NamedTuple):
    proofs_hold: Callable[[float, tuple[str, str] | None], bool]
    stores_hold: Callable[[], bool]
    claude_paths: dict[str, str]


def publish(
    collection: dict[str, Any],
    config: RuntimeConfig,
    state: RuntimeState,
    clock: Callable[[], float],
    stamp: tuple[int, ...] | None,
) -> Validation | None:
    """Attach only proven tokens after the annotation and SessionEnd overlays.

    Reused snapshot bytes also need their proofs checked. Their row fields are immutable, so
    a cached response only has to recheck the stores and transcript metadata, without hashing
    the row or deserializing the body again. A footer reuses only its own row's proof.
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
    proofs = {}
    for row in rows:
        owner = identity(row)
        memo = memos.get(owner)
        if not memo or not memo.token or counts[owner] != 1 or not eligible(row):
            continue
        proof = _proof(row, collection, entries.get(owner), memo)
        if proof is not None and proof.holds(config, state, now):
            proofs[owner] = proof

    def stores_hold() -> bool:
        # A chmod need not change the history parser's cached inode, size or mtime.
        return annotation_stamp(config) == stamp and os.access(
            semantic_history.store_path(config), os.R_OK
        )

    if not proofs or not stores_hold():
        return None
    for proof in proofs.values():
        proof.row.update(published(proof.memo.token))

    def proofs_hold(now: float, owner: tuple[str, str] | None) -> bool:
        selected = proofs.values() if owner is None else (proofs.get(owner),)
        return all(proof is not None and proof.holds(config, state, now) for proof in selected)

    claude_paths = {
        sid: proof.memo.transcript.path
        for (harness, sid), proof in proofs.items()
        if harness == "claude"
    }
    return Validation(proofs_hold, stores_hold, claude_paths)
