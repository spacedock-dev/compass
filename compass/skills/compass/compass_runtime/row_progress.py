"""In-process Sessions progress, recomputed by the focused page and checked at publication."""

from __future__ import annotations

import contextlib
import errno
import fnmatch
import hashlib
import json
import os
import select
import stat
import sys
import weakref
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


_MISSING_DIRECTORY = {errno.ENOENT, errno.ENOTDIR, errno.ELOOP}
# A vnode filter holds a descriptor per directory. Leave room for the
# dashboard's clients and stores even under macOS's low soft descriptor limit.
_MAX_WATCHED_DIRECTORIES = 128


def _claude_matches(directory: str, sids: frozenset[str]) -> dict[str, str | None]:
    matches: dict[str, str | None] = {}
    try:
        names = os.listdir(directory)
    except OSError as exc:
        # Match the collector's glob when a project or its symlink target is inaccessible.
        if isinstance(exc, PermissionError) or exc.errno in _MISSING_DIRECTORY:
            return matches
        raise
    # An archived name can collide without contributing a board row. Check the held
    # prefixes before applying the glob or allocating a path for a match.
    for length in {len(sid) for sid in sids}:
        for name in names:
            sid = name[:length]
            if (
                sid in sids
                and len(sid) == length
                and len(name) >= length + len(".jsonl")
                and not name.startswith(".")
                and fnmatch.fnmatch(name, "*.jsonl")
            ):
                matches[sid] = None if sid in matches else os.path.join(directory, name)
    return matches


class _Namespace(NamedTuple):
    roots: list[tuple[str, int, int]]
    projects: list[str]
    linked_projects: list[str]


class _NameWatch:
    def __init__(self, queue: select.kqueue, resources: contextlib.ExitStack) -> None:
        self._queue = queue
        self.close = weakref.finalize(self, resources.close)

    @classmethod
    def start(cls, namespace: _Namespace) -> _NameWatch | None:
        if sys.platform != "darwin":
            return None
        root_ids = {path: (device, inode) for path, device, inode in namespace.roots}
        directories = [*root_ids, *namespace.projects]
        if len(directories) > _MAX_WATCHED_DIRECTORIES:
            return None
        try:
            with contextlib.ExitStack() as resources:
                queue = resources.enter_context(contextlib.closing(select.kqueue()))
                root_fds: dict[str, int] = {}
                for path in directories:
                    root_id = root_ids.get(path)
                    parent = root_fds[os.path.dirname(path)] if root_id is None else None
                    # Keep the checked directory descriptor for the vnode filter.
                    fd = runtime_io._directory_fd(  # noqa: SLF001
                        path if parent is None else os.path.basename(path),
                        parent_fd=parent,
                        follow_links=parent is None,
                    )
                    resources.callback(os.close, fd)
                    if root_id is not None:
                        info = os.fstat(fd)
                        if (info.st_dev, info.st_ino) != root_id:
                            return None
                        # Watch children relative to the held root, even if the
                        # configured root path itself is a relocated store link.
                        root_fds[os.path.dirname(os.path.join(path, "."))] = fd
                    queue.control(
                        [
                            select.kevent(
                                fd,
                                filter=select.KQ_FILTER_VNODE,
                                flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                                fflags=(
                                    select.KQ_NOTE_WRITE
                                    | select.KQ_NOTE_RENAME
                                    | select.KQ_NOTE_DELETE
                                    | select.KQ_NOTE_ATTRIB
                                    | select.KQ_NOTE_REVOKE
                                ),
                            )
                        ],
                        0,
                        0,
                    )
                return cls(queue, resources.pop_all())
        except OSError:
            return None

    def unchanged(self) -> bool:
        try:
            return not self._queue.control(None, 1, 0)
        except OSError:
            return False


class _WatchedNames(NamedTuple):
    namespace: _Namespace
    paths: dict[str, str]
    matches: dict[str, str | None]
    watch: _NameWatch


def _project_matches(projects: list[str], sids: frozenset[str]) -> dict[str, str | None]:
    unique: dict[str, str | None] = {}
    for directory in projects:
        for sid, path in _claude_matches(directory, sids).items():
            unique[sid] = None if sid in unique else path
    return unique


def _confirmed_names(
    projects: list[str],
    paths: Mapping[str, str],
    *,
    watched: Mapping[str, str | None] | None = None,
) -> set[str]:
    remaining = frozenset(paths)
    # A second pass catches collisions introduced in an earlier project while
    # a later project was read, even when the directory stamp did not move.
    for _ in range(1 if watched is not None and len(projects) <= 1 else 2):
        unique = _project_matches(projects, remaining)
        if watched is not None:
            for sid, path in watched.items():
                unique[sid] = None if sid in unique else path
        remaining = frozenset(sid for sid in remaining if unique.get(sid) == paths[sid])
        if not remaining:
            break
    return set(remaining)


class ClaudePrefixes:
    """Filename evidence for the footer's Claude rows, serialized by the footer writer."""

    def __init__(self, config: RuntimeConfig) -> None:
        self._roots = config.store_roots.get("claude.projects", ())
        self._names: _WatchedNames | None = None

    def _project_paths(self) -> _Namespace | None:
        roots: list[tuple[str, int, int]] = []
        projects: list[str] = []
        linked_projects: list[str] = []
        for root in self._roots:
            try:
                info = os.stat(root)
            except OSError as exc:
                if exc.errno in _MISSING_DIRECTORY:
                    continue
                raise
            if not stat.S_ISDIR(info.st_mode):
                continue
            # A footer proof must not mutate the configured store on an idle tick.
            if not runtime_io.admit_harness_root(root, tighten_permissions=False):
                return None
            roots.append((root, info.st_dev, info.st_ino))
            with os.scandir(root) as entries:
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    if entry.is_symlink():
                        linked_projects.append(entry.path)
                    elif entry.is_dir(follow_symlinks=False):
                        projects.append(entry.path)
        return _Namespace(roots, sorted(projects), sorted(linked_projects))

    def unambiguous(self, paths: Mapping[str, str]) -> set[str]:
        namespace = self._project_paths() if paths else None
        cached = self._names
        if cached is not None and (
            namespace != cached.namespace or paths != cached.paths or not cached.watch.unchanged()
        ):
            cached.watch.close()
            self._names = None
            cached = None
        if namespace is None:
            return set()

        if cached is None:
            watch = _NameWatch.start(namespace)
            if watch is None:
                remaining = _confirmed_names(
                    sorted(namespace.projects + namespace.linked_projects), paths
                )
                return remaining if remaining and self._project_paths() == namespace else set()
            matches = _project_matches(namespace.projects, frozenset(paths))
            cached = _WatchedNames(namespace, dict(paths), matches, watch)

        # A linked project's target can move through an unwatched ancestor.
        remaining = _confirmed_names(namespace.linked_projects, paths, watched=cached.matches)
        starting_watch = self._names is None
        if (starting_watch and self._project_paths() != namespace) or (
            (starting_watch or namespace.linked_projects) and not cached.watch.unchanged()
        ):
            cached.watch.close()
            self._names = None
            return set()
        self._names = cached
        return remaining


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


@dataclass(frozen=True)
class Validation:
    config: RuntimeConfig
    state: RuntimeState
    clock: Callable[[], float]
    stamp: tuple[int, ...]
    proofs: dict[tuple[str, str], Proof]
    claude_paths: dict[str, str]

    def stores_hold(self) -> bool:
        # A chmod need not change the history parser's cached inode, size or mtime.
        return annotation_stamp(self.config) == self.stamp and os.access(
            semantic_history.store_path(self.config), os.R_OK
        )

    def proofs_hold(self, now: float, owner: tuple[str, str] | None) -> bool:
        selected = self.proofs.values() if owner is None else (self.proofs.get(owner),)
        return all(
            proof is not None and proof.holds(self.config, self.state, now) for proof in selected
        )

    def prepare_snapshot(self, withheld: frozenset[str]) -> Callable[[], bool] | None:
        if not withheld:
            return lambda: self.proofs_hold(self.clock(), None) and self.stores_hold()
        # A proof the footer rejected must neither supply bytes nor expire a memo that omits it.
        retained = []
        for (harness, sid), proof in self.proofs.items():
            if harness == "claude" and sid in withheld and proof.memo.token in DEPARTURES:
                proof.row["stored_progress"] = None
            else:
                retained.append(proof)
        if not retained:
            return None

        def snapshot_holds() -> bool:
            now = self.clock()
            return (
                all(proof.holds(self.config, self.state, now) for proof in retained)
                and self.stores_hold()
            )

        return snapshot_holds


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

    claude_paths = {
        sid: proof.memo.transcript.path
        for (harness, sid), proof in proofs.items()
        if harness == "claude"
    }
    validation = Validation(config, state, clock, stamp, proofs, claude_paths)
    if not proofs or not validation.stores_hold():
        return None
    for proof in proofs.values():
        proof.row.update(published(proof.memo.token))
    return validation
