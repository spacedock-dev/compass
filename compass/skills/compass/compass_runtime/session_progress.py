"""Read-only, versioned publication of the current stored progress check."""

from __future__ import annotations

import copy
import json
import os
import re
import stat
import time
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any, NamedTuple, cast
from urllib.parse import parse_qs

from . import annotations as annotation_store
from . import config as runtime_config
from . import (
    copied_corrections,
    correction,
    drift_view,
    focused_reading,
    git_status,
    levels,
    project_context,
    project_scripts,
    reader_checks,
    reading,
    record_pages,
    semantic_history,
)
from . import io as runtime_io
from . import sessions as runtime_sessions
from . import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .aggregate import Application
    from .config import RuntimeConfig

MAX_ROWS = 32
MAX_INVENTORY = 8192
MAX_SOURCES = 128
MAX_BATCH_BYTES = 48 * 1024 * 1024
MAX_BATCH_SECONDS = 4.0
MAX_WORKSPACE_INPUTS = 256
RULE_VERSION = 1
DEPARTURES = frozenset({levels.MEDIUM, levels.HIGH, levels.EXTREME})
_Identity = tuple[str, str, str]
_Stamp = tuple[int, ...]
_MISSING: _Stamp = ()
_UNAVAILABLE: _Stamp = (-1,)
_SID = re.compile(r"[A-Za-z0-9_-]{1,128}")


class Request(NamedTuple):
    revision: str
    rows: tuple[_Identity, ...]


def parse(query: str, project_cap: int) -> Request:
    fields = parse_qs(query, keep_blank_values=True, max_num_fields=MAX_ROWS + 1)
    revision = fields.get("revision", [])
    if (
        set(fields) != {"row", "revision"}
        or len(revision) != 1
        or re.fullmatch(r"[0-9]{1,20}\.[0-9]{1,20}", revision[0]) is None
    ):
        msg = "a board revision and bounded rows are required"
        raise ValueError(msg)
    rows = tuple(_requested_row(value, project_cap) for value in fields["row"])
    if len(set(rows)) != len(rows):
        msg = "duplicate progress identity"
        raise ValueError(msg)
    return Request(revision[0], rows)


def _requested_row(value: str, project_cap: int) -> _Identity:
    row = json.loads(value)
    if (
        not isinstance(row, list)
        or len(row) != 3
        or not all(isinstance(part, str) for part in row)
        or not _SID.fullmatch(row[0])
        or not _SID.fullmatch(row[1])
        or not 0 < len(row[2]) <= project_cap
    ):
        msg = "expected harness, session id and canonical project"
        raise ValueError(msg)
    return row[0], row[1], row[2]


def identity(row: Mapping[str, Any]) -> _Identity:
    return (
        str(row.get("harness") or ""),
        str(row.get("sid") or ""),
        str(row.get("project_key") or row.get("project") or ""),
    )


def matching(
    rows: Sequence[dict[str, Any]], wanted: tuple[str, str], project: str
) -> dict[str, Any] | None:
    # A project label may resolve focus, but never disambiguates a collision in
    # the annotation key (which is harness + sid).
    hits = [row for row in rows if identity(row)[:2] == wanted]
    if len(hits) != 1:
        return None
    (row,) = hits
    key = identity(row)[2]
    if project == key:
        return row
    if row.get("project") == project and all(
        identity(peer)[2] == key for peer in rows if peer.get("project") == project
    ):
        return row
    return None


def admitted_rows(rows: Sequence[dict[str, Any]]) -> dict[_Identity, dict[str, Any]]:
    """Index matching Claude rows once, excluding any ambiguous annotation key."""
    admitted: dict[tuple[str, str], dict[str, Any] | None] = {}
    for row in rows:
        key = identity(row)[:2]
        if key[0] == "claude":
            admitted[key] = None if key in admitted else row
    return {identity(row): row for row in admitted.values() if row is not None}


def published(value: str | None = None) -> dict[str, Any]:
    return {"stored_progress": value}


def claims_departure(row: Mapping[str, Any]) -> bool:
    assessment = row.get("annotation_assessment")
    criteria = assessment.get("criteria") if isinstance(assessment, dict) else None
    return isinstance(criteria, dict) and any(
        key != reading.CONSTRAINT_CLAIMS
        and isinstance(value, dict)
        and value.get("result") == reading.RESULT_DEPARTURE
        for key, value in criteria.items()
    )


def _stamp(path: str, *, directory: bool = False) -> _Stamp:
    try:
        found = os.lstat(path)
    except FileNotFoundError:
        return _MISSING
    except OSError:
        return _UNAVAILABLE
    valid = stat.S_ISDIR(found.st_mode) if directory else stat.S_ISREG(found.st_mode)
    access = os.R_OK | (os.X_OK if directory else 0)
    if not valid or not os.access(path, access):
        return _UNAVAILABLE
    return (
        found.st_size,
        found.st_dev,
        found.st_ino,
        found.st_mtime_ns,
        found.st_ctime_ns,
        found.st_mode,
        found.st_uid,
        found.st_gid,
        found.st_nlink,
    )


def _state_stamps(config: RuntimeConfig) -> tuple[_Stamp, ...]:
    return tuple(
        _stamp(owner(config))
        for owner in (
            annotation_store.store_path,
            semantic_history.store_path,
            copied_corrections.store_path,
            reader_checks.store_path,
        )
    )


def _inventory(config: RuntimeConfig) -> tuple[str, ...] | None:
    """The native Claude lookup, with a ceiling on entries across store roots."""
    paths: list[str] = []
    remaining = MAX_INVENTORY
    for configured in runtime_config.store_roots(config, "claude.projects"):
        root = os.path.realpath(configured)
        directories = runtime_io.directory_entries(root, remaining)
        if directories is None:
            return None
        remaining -= len(directories)
        for name, is_dir in directories:
            if not is_dir:
                continue
            directory = os.path.join(root, name)
            entries = runtime_io.directory_entries(directory, remaining)
            if entries is None:
                return None
            remaining -= len(entries)
            paths.extend(
                os.path.join(directory, name)
                for name, is_dir in entries
                if not is_dir and name.endswith(".jsonl")
            )
    return tuple(dict.fromkeys(paths))


def _native_path(sid: str, resume_id: object, inventory: tuple[str, ...]) -> str | None:
    # The annotation id is the binding even where the board knows the full
    # resume id. A second occurrence of its prefix makes that binding ambiguous.
    hits = [
        path for path in inventory if os.path.basename(path).removesuffix(".jsonl").startswith(sid)
    ]
    if len(hits) != 1:
        return None
    (path,) = hits
    return path if not resume_id or os.path.basename(path) == f"{resume_id}.jsonl" else None


class _Sources(NamedTuple):
    files: tuple[tuple[str, _Stamp], ...]
    directories: tuple[tuple[str, _Stamp], ...]

    @property
    def size(self) -> int:
        return sum(stamp[0] for _, stamp in self.files)

    def unchanged(self) -> bool:
        return all(_stamp(path) == mark for path, mark in self.files) and all(
            _stamp(path, directory=True) == mark for path, mark in self.directories
        )


def _sources(path: str) -> _Sources | None:
    parent_dir = os.path.dirname(path)
    session_dir = path.removesuffix(".jsonl")
    child_dir = os.path.join(session_dir, "subagents")
    workflow_dir = os.path.join(child_dir, "workflows")
    runs = runtime_io.directory_entries(workflow_dir, MAX_SOURCES)
    if runs is None:
        return None
    run_dirs = [os.path.join(workflow_dir, name) for name, is_dir in runs if is_dir]
    directories = (parent_dir, session_dir, child_dir, workflow_dir, *run_dirs)
    directory_stamps = tuple((name, _stamp(name, directory=True)) for name in directories)
    if any(mark == _UNAVAILABLE for _, mark in directory_stamps):
        return None
    children: list[str] = []
    remaining = MAX_SOURCES - len(runs)
    for directory in (child_dir, *run_dirs):
        entries = runtime_io.directory_entries(directory, remaining)
        if entries is None:
            return None
        remaining -= len(entries)
        children.extend(
            candidate
            for name, is_dir in entries
            if not is_dir
            and project_context.stored_child_path(path, candidate := os.path.join(directory, name))
        )
    files = tuple((name, _stamp(name)) for name in (path, *sorted(children)))
    if any(mark in (_MISSING, _UNAVAILABLE) for _, mark in files):
        return None
    return _Sources(files, directory_stamps)


def _git_markers(folder: str) -> list[tuple[str, bool]]:
    """The nearest checkout marker, also watching for one to appear closer."""
    markers: list[tuple[str, bool]] = []
    current = os.path.realpath(folder)
    while len(markers) < MAX_WORKSPACE_INPUTS:
        candidate = os.path.join(current, ".git")
        markers.append((candidate, os.path.isdir(candidate)))
        parent = os.path.dirname(current)
        if os.path.lexists(candidate) or parent == current:
            break
        current = parent
    return markers


def _reference_inputs(root: str, remaining: int) -> list[tuple[str, bool]] | None:
    inputs = [(root, True)]
    for path, is_dir in inputs:
        if not is_dir:
            continue
        entries = runtime_io.directory_entries(path, remaining - len(inputs))
        if entries is None or len(inputs) + len(entries) > remaining:
            return None
        inputs.extend((os.path.join(path, name), directory) for name, directory in entries)
    return inputs


def _repository_inputs(dot_git: str, remaining: int) -> list[tuple[str, bool]] | None:
    roots = git_status.git_dirs(dot_git)
    if roots is None:
        return None
    result: list[tuple[str, bool]] = []
    for directory in dict.fromkeys(roots):
        root = os.path.realpath(directory)
        # Alternate and promisor object stores can change or trigger a fetch.
        # The progress route abstains before running a Git read in those repositories.
        if any(
            os.path.lexists(os.path.join(root, "objects", "info", name))
            for name in (
                "alternates",
                "http-alternates",
            )
        ):
            return None
        pack = os.path.join(root, "objects", "pack")
        packs = runtime_io.directory_entries(pack, remaining)
        if packs is None or any(name.endswith(".promisor") for name, _ in packs):
            return None
        refs = _reference_inputs(os.path.join(root, "refs"), remaining - len(result))
        if refs is None:
            return None
        result.extend(refs)
        result.extend(
            (os.path.join(root, name), False)
            for name in (
                "HEAD",
                "config",
                "commondir",
                "config.worktree",
                "packed-refs",
                "shallow",
                "info/grafts",
                "objects/info/alternates",
                "objects/info/http-alternates",
            )
        )
        result.append((pack, True))
    top = os.path.dirname(dot_git)
    result.extend((os.path.join(top, name), False) for name in project_scripts.DECLARING_FILES)
    return result if len(result) <= remaining else None


def _workspace(config: RuntimeConfig, folders: tuple[str, ...]) -> _Sources | None:
    if len(folders) > 16:
        return None
    paths: dict[tuple[str, bool], None] = {}
    for directory in folders:
        markers = _git_markers(directory)
        paths.update(dict.fromkeys(markers))
        dot_git, _ = markers[-1]
        if config.git_probe_enabled and os.path.lexists(dot_git):
            dependencies = _repository_inputs(dot_git, MAX_WORKSPACE_INPUTS - len(paths))
            if dependencies is None:
                return None
            paths.update(dict.fromkeys(dependencies))
        if len(paths) > MAX_WORKSPACE_INPUTS:
            return None
    files = tuple((path, _stamp(path)) for path, is_dir in paths if not is_dir)
    dirs = tuple((path, _stamp(path, directory=True)) for path, is_dir in paths if is_dir)
    return (
        None if any(mark == _UNAVAILABLE for _, mark in (*files, *dirs)) else _Sources(files, dirs)
    )


@dataclass(frozen=True)
class Verdict:
    value: str | None = None
    work: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    pill: dict[str, Any] | None = None


_EMPTY = Verdict()


class CachedVerdict(NamedTuple):
    stamp: tuple[Any, ...]
    verdict: Verdict
    workspace: _Sources


def _saved_row(row: dict[str, Any], entry: annotation_store.Annotation | None) -> dict[str, Any]:
    release = {key: value for key, value in row.items() if not key.startswith("annotation_")}
    # The shape reducer reads wire values. Internally the annotation store
    # holds its citations and lines as immutable tuples.
    published_annotation = json.loads(json.dumps(annotation_store.published(entry)))
    release.update({f"annotation_{key}": value for key, value in published_annotation.items()})
    return release


def _row_inputs(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        row.get(name)
        for name in (
            "project",
            "project_key",
            "project_identity_source",
            "resume_id",
            "state",
            "active",
            "acquisition",
            "ended_at",
            "finished_at",
            "turn_end_at",
            "first_prompt_at",
            "first_prompt",
            "prompt_at",
            "copied_prompts",
            "instruction",
            "session_goal",
            "title",
            "prompt_states_work",
            "first_prompt_control",
        )
    )


def _attempt_absence(entry: annotation_store.Annotation | None, row: dict[str, Any]) -> str | None:
    if entry and entry.get("withheld") == reading.WITHHELD[reading.WITHHELD_LEDGER_EMPTY]:
        return "too-early"
    if entry and any(
        entry.get(name)
        for name in (
            "withheld",
            "refused",
            "readings",
            "reading_diagnostic",
            "long_diagnostic",
        )
    ):
        return None
    if not row["annotation_goal"]:
        return "no-goal"
    # A saved revision that has never been written again can prove this. A
    # default or legacy counter at zero says only that no model was counted.
    if entry and entry["revisions"] and entry.get("written") == entry["revisions"][-1]["at"]:
        return "unchecked"
    return None


def _verdict(  # noqa: PLR0911 - each closed result has its own proof
    application: Application,
    payload: dict[str, Any],
    row: dict[str, Any],
    entry: annotation_store.Annotation,
    context: dict[str, Any],
    record: list[dict[str, Any]],
) -> Verdict:
    sources = reading.listed_request_sources(focused_reading.facts_of(context), [])
    work = focused_reading.stored_work(application, context, row, entry, sources=sources)
    context["sources"]["work"].update(work)
    view = drift_view.derive(row, payload, context, record)
    if view["malformed"]:
        return _EMPTY
    if view["stale"]:
        return Verdict("out-of-date", work)
    analysis = view["analysis"]
    if analysis is None:
        return _EMPTY
    if analysis["withheld"] or view["unsettled"]:
        return Verdict(work=work)
    level, reasons = analysis["level"], set(analysis["reasons"])
    if level in DEPARTURES and view["pill"] and view["pill"]["source"] == "analysis":
        return Verdict(level, work, analysis, view["pill"])
    if levels.REASON_GOAL_UNCLEAR in reasons:
        return Verdict("goal-unclear", work)
    if reasons & {
        levels.REASON_FAILED_CHECK,
        levels.REASON_PASS_THEN_WRITE,
        levels.REASON_CLAIM_CONTRADICTED,
        levels.REASON_CLAIM_NOT_SHOWN,
    }:
        return Verdict(work=work)
    if levels.REASON_OUTCOME_NOT_REACHED in reasons:
        return Verdict("too-early", work)
    if reasons == {levels.REASON_LINE_NOT_SHOWN}:
        return Verdict("cant-tell", work)
    return Verdict("checked" if level == levels.NONE_OR_LOW else None, work)


def _superseded(row: Mapping[str, Any], entry: annotation_store.Annotation) -> str | None:
    assessment = entry["assessment"]
    if assessment.get("scope") == reading.SCOPE_WITHDRAWN or (
        assessment.get("scope") == reading.SCOPE_FINAL
        and (not row.get("ended_at") or row["ended_at"] != assessment.get("ended_at_read"))
    ):
        return "out-of-date"
    if assessment.get("revision_read") != row.get("annotation_revision"):
        return "out-of-date"
    return None


def _has_retained_gap(
    retained: dict[str, Any],
    row: dict[str, Any],
    entry: annotation_store.Annotation,
    context: dict[str, Any],
) -> bool:
    project = semantic_history.retained_events(retained, {identity(row)[2], str(row["project"])})
    if project is None:
        return True
    own = {fact.get("fact_id") for fact in focused_reading.facts_of(context)}
    for event in project:
        fact = event.get("fact") if isinstance(event, dict) else None
        if (
            isinstance(fact, dict)
            and fact.get("fact_id") not in own
            and correction.unsettled_directions(
                row,
                [fact],
                floor=annotation_store.direction_floor(entry, row),
                until=entry["assessment"].get("read_at"),
            )
        ):
            return True
    return False


class _Batch:
    def __init__(
        self, application: Application, payload: dict[str, Any], cursor_key: bytes
    ) -> None:
        self.application = application
        self.payload = payload
        self.config = application.config
        self.cursor_key = cursor_key
        self.deadline = time.monotonic() + MAX_BATCH_SECONDS
        self.stamps = _state_stamps(self.config)
        self.inventory = _inventory(self.config)
        self.remaining = MAX_BATCH_BYTES
        self.source_count = MAX_SOURCES
        self.history: tuple[str, dict[str, Any]] | None = None
        self.proofs: dict[_Identity, _Sources] = {}
        self.workspaces: dict[_Identity, _Sources] = {}
        self.jobs = reading.published_jobs(self.config)

    def entries(self) -> dict[tuple[str, str], annotation_store.Annotation | None] | None:
        state = self.application.state
        with annotation_store.progress_read(self.config) as held:
            if not held or self.stamps != _state_stamps(self.config):
                return None
            cached = state.progress_annotations
            if cached is not None and cached[0] == self.stamps[0]:
                return cast("dict[tuple[str, str], annotation_store.Annotation | None]", cached[1])
            entries = annotation_store.progress_entries(self.config)
            if entries is not None and self.stamps == _state_stamps(self.config):
                state.progress_annotations = (self.stamps[0], entries)
                return entries
            return None

    def evaluate(self, row: dict[str, Any], entry: annotation_store.Annotation | None) -> Verdict:
        key = identity(row)
        if time.monotonic() >= self.deadline or key[0] != "claude":
            return _EMPTY
        path = _native_path(key[1], row.get("resume_id"), self.inventory or ())
        sources = _sources(path) if path else None
        if path is None or sources is None:
            return _EMPTY
        self.proofs[key] = sources
        if self._pending(key) or (
            entry is None and (row.get("annotation_goal") or row.get("annotation_assessment"))
        ):
            return _EMPTY
        row = _saved_row(row, entry)
        if entry is None or not entry.get("assessment"):
            return _EMPTY if self._live_only(row) else Verdict(_attempt_absence(entry, row))
        return self._evaluate_reading(key, row, entry, sources)

    def _pending(self, key: _Identity) -> bool:
        return f"{key[0]}:{key[1]}" in self.jobs

    def _evaluate_reading(
        self,
        key: _Identity,
        row: dict[str, Any],
        entry: annotation_store.Annotation,
        sources: _Sources,
    ) -> Verdict:
        if value := _superseded(row, entry):
            return Verdict(value)
        if entry.get("not_accurate") or entry.get("withheld"):
            return _EMPTY

        state = self.application.state
        stamp = (
            RULE_VERSION,
            self.stamps,
            self.payload.get("reading_routes"),
            _row_inputs(row),
            sources,
        )
        cached = state.progress_verdicts.get(key)
        if cached is not None and cached.stamp == stamp and cached.workspace.unchanged():
            self.workspaces[key] = cached.workspace
            return cached.verdict

        if sources.size > self.remaining or len(sources.files) > self.source_count:
            return _EMPTY
        self.remaining -= sources.size
        self.source_count -= len(sources.files)
        verdict = self._derive(row, entry, sources)
        workspace = self.workspaces.get(key)
        if (
            time.monotonic() >= self.deadline
            or not sources.unchanged()
            or (workspace is not None and not workspace.unchanged())
        ):
            return _EMPTY
        if workspace is not None:
            runtime_state.bounded_put(
                state.progress_verdicts,
                key,
                CachedVerdict(stamp, verdict, workspace),
                limit=max(1, min(128, self.config.max_cache_entries)),
            )
        return verdict

    def _live_only(self, row: dict[str, Any]) -> bool:
        leases = self.application.live_leases
        return bool(leases and leases.has_holder("claude", row["sid"]))

    def _admit_workspace(
        self, row: dict[str, Any], began_in: str, folders: tuple[str, ...]
    ) -> bool:
        workspace = _workspace(self.config, tuple(dict.fromkeys((began_in, *folders))))
        if workspace is None:
            return False
        if row.get("project_identity_source") not in (None, "collector project label"):
            verified = copy.copy(row)
            verified["project_key"] = ""
            runtime_sessions.apply_project_identity(self.config, verified, began_in)
            if verified["project_key"] != identity(row)[2]:
                return False
        self.workspaces[identity(row)] = workspace
        return True

    def _derive(
        self, row: dict[str, Any], entry: annotation_store.Annotation, sources: _Sources
    ) -> Verdict:
        path, *children = (name for name, _ in sources.files)
        if self.history is None:
            self.history = semantic_history.read_only(self.config)
        history_status, retained = self.history
        if history_status == "unavailable":
            return _EMPTY

        context = project_context.stored_evidence(
            self.config,
            path,
            row,
            children,
            deadline=self.deadline,
            admit_workspace=partial(self._admit_workspace, row),
        )
        if context is None:
            return _EMPTY
        assessment = entry["assessment"]
        through = reading.valid_prompt_time(assessment.get("evidence_through"))
        if through and through > context["native_through"]:
            return _EMPTY
        if _has_retained_gap(retained, row, entry, context):
            return _EMPTY
        context = copied_corrections.mark(context, [row])
        record = record_pages.read(
            self.config,
            path,
            "claude",
            row["sid"],
            cursor_key=self.cursor_key,
            limit=1,
            before=None,
        )
        if record.get("state") != "ok":
            return _EMPTY
        # The fact builders above already read and marked the native message
        # record end to end. Hand the page shape that version as its context,
        # without letting duplicate, unmarked page entries undo those marks.
        return _verdict(self.application, self.payload, row, entry, context, [])

    def finish(self, results: dict[_Identity, Verdict]) -> dict[_Identity, Verdict]:
        # Check work before the annotation fence, which is also taken for warm
        # hits. A save can complete at any point during evidence reconstruction.
        inventory = _inventory(self.config)
        if inventory is None:
            return {}
        for key, sources in self.proofs.items():
            workspace = self.workspaces.get(key)
            if (
                _native_path(key[1], None, inventory) != sources.files[0][0]
                or _sources(sources.files[0][0]) != sources
                or (workspace is not None and not workspace.unchanged())
            ):
                results.pop(key, None)
        with annotation_store.progress_read(self.config) as held:
            if (
                held
                and self.stamps == _state_stamps(self.config)
                and self.jobs == reading.published_jobs(self.config)
            ):
                return results
        return {}


def evaluate(
    application: Application,
    payload: dict[str, Any],
    rows: Sequence[dict[str, Any]],
    cursor_key: bytes,
) -> dict[_Identity, Verdict]:
    """Coalesce cold work independently of board collection and fence every answer."""
    if not rows or not application.config.annotations_enabled:
        return {}
    lock = application.state.progress_lock
    if not lock.acquire(timeout=1.25):
        return {}
    try:
        batch = _Batch(application, payload, cursor_key)
        if batch.inventory is None or _UNAVAILABLE in batch.stamps:
            return {}
        entries = batch.entries()
        if entries is None:
            return {}
        results = {
            identity(row): batch.evaluate(row, entries.get(identity(row)[:2]))
            for row in rows
            if identity(row)[:2] not in entries or entries[identity(row)[:2]] is not None
        }
        return batch.finish(results)
    finally:
        lock.release()
