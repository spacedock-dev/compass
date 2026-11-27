"""Assemble the plan from a fresh set of independently admitted sources."""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from compass_runtime import git_status, io

from . import dates, grammar, markdown, model, sources

if TYPE_CHECKING:
    from compass_runtime.state import RuntimeState

    from . import settings

MAX_REPO_FILE_BYTES = 256 * 1024
RepoRow = model.Goal | model.Decision | model.Item | model.Diagram


@dataclass(frozen=True)
class _FileRows:
    source: model.Source
    rows: tuple[RepoRow, ...] = ()
    unknown: tuple[model.UnknownStatus, ...] = ()
    line_count: int = 0


def _parse_file(text: str, source: model.Source, config: settings.Settings) -> _FileRows:
    rows: tuple[RepoRow, ...]
    unknown: tuple[model.UnknownStatus, ...] = ()
    match source.kind:
        case "goals":
            rows = tuple(
                replace(goal, lanes=declared)
                for goal, declared in markdown.goals(text, config.goals, config.briefs, source)
            )
        case "decisions":
            rows = markdown.decisions(text, config.decisions, source)
        case "inventory":
            rows, unknown = markdown.inventory(text, config.inventory, source)
        case "tracker":
            rows, unknown = markdown.tracker(text, config.tracker, source)
        case "diagrams":
            rows = markdown.diagrams(text, config.diagrams, source)
        case _:
            rows = ()
    return _FileRows(
        source, rows, unknown, text.count("\n") + bool(text and not text.endswith("\n"))
    )


def _tree_source(
    repo: sources.Repository,
    config: settings.Settings,
    ref: str,
    kind: str,
    path: str,
    directory: int | None,
) -> model.Source:
    checked = config.sources.tree_source(repo.label, ref, path, kind=kind, directory=directory)
    return model.Source(kind, repo.label, path, ref, reason=checked.reason, draft=ref != repo.ref)


def _read_file(
    tree: git_status.PlanTreeReader, tip: str, source: model.Source, config: settings.Settings
) -> _FileRows:
    if source.reason is not None:
        return _FileRows(source)
    checked = config.sources.tree_source(
        source.label, source.ref or "", source.path, kind=source.kind, directory=tree.directory
    )
    if checked.reason is not None:
        return _FileRows(replace(source, reason=checked.reason))
    source = replace(source, commit=tip)
    try:
        tree.check_markers(tip, source.path, config.sources.policy.marker_files)
        data = tree.tree_file(tip, source.path, max_bytes=MAX_REPO_FILE_BYTES)
        return _parse_file(markdown.decode(data), source, config)
    except (git_status.PlanGitError, markdown.ParseError) as exc:
        return _FileRows(replace(source, reason=exc.reason))


def _with_date(row: RepoRow, date: model.ItemDate | None) -> RepoRow:
    return replace(row, origin=replace(row.origin, date=date))


def _row_key(row: RepoRow) -> tuple[str, ...]:
    kind = row.origin.source.kind
    if isinstance(row, model.Goal):
        return kind, row.id
    if isinstance(row, model.Diagram):
        return kind, row.kind, row.caption
    return kind, row.title


def _draft_files(
    tree: git_status.PlanTreeReader,
    repo: sources.Repository,
    config: settings.Settings,
    primary: list[_FileRows],
    directory: int,
) -> list[_FileRows]:
    if repo.draft_ref is None:
        return []
    # A failed primary read cannot establish that the branch lacks an item.
    comparable = [
        _tree_source(repo, config, repo.draft_ref, file.source.kind, file.source.path, directory)
        for file in primary
        if file.source.reason in (None, "not in branch")
    ]
    if not any(source.reason is None for source in comparable):
        return [_FileRows(source) for source in comparable]
    try:
        tip = tree.tip(repo.draft_ref)
    except git_status.PlanGitError as exc:
        return [
            _FileRows(replace(source, reason=source.reason or exc.reason)) for source in comparable
        ]
    merged = {_row_key(row) for file in primary for row in file.rows}
    proposed = None
    result = []
    for source in comparable:
        file = _read_file(tree, tip, source, config)
        new_rows = tuple(row for row in file.rows if _row_key(row) not in merged)
        if new_rows and proposed is None:
            proposed = dates.proposed(tree, tip)
        origins = {row.origin for row in new_rows}
        result.append(
            replace(
                file,
                rows=tuple(_with_date(row, proposed) for row in new_rows),
                unknown=tuple(item for item in file.unknown if item.origin in origins),
            )
        )
    return result


def _repo_files(
    repo: sources.Repository,
    config: settings.Settings,
    timeout_sec: float,
    state: RuntimeState | None,
    git_deadline: float | None,
) -> list[_FileRows]:
    declared = [
        model.Source(
            kind,
            repo.label,
            path,
            repo.ref,
            reason=config.sources.declared_tree_source(repo, kind, path).reason,
        )
        for kind, path in repo.files
    ]
    if not any(source.reason is None for source in declared):
        return [_FileRows(source) for source in declared]
    try:
        with config.sources.hold_repository(repo) as directory:
            return _read_repository(repo, config, timeout_sec, state, git_deadline, directory)
    except io.PlanReadError as exc:
        return [
            _FileRows(replace(source, reason=source.reason or exc.reason)) for source in declared
        ]


def _read_repository(
    repo: sources.Repository,
    config: settings.Settings,
    timeout_sec: float,
    state: RuntimeState | None,
    git_deadline: float | None,
    directory: int,
) -> list[_FileRows]:
    declared = [
        _tree_source(repo, config, repo.ref, kind, path, directory) for kind, path in repo.files
    ]
    if not any(source.reason is None for source in declared):
        return [_FileRows(source) for source in declared]

    def verify_cwd() -> None:
        try:
            config.sources.verify_repository(repo, directory)
        except io.PlanReadError as exc:
            raise git_status.PlanGitError(exc.reason) from None

    tree = replace(
        git_status.plan_reader(repo.path, timeout_sec=timeout_sec),
        request_deadline=git_deadline,
        directory=directory,
        verify_cwd=verify_cwd,
    )
    try:
        tip = tree.tip(repo.ref)
    except git_status.PlanGitError as exc:
        return [
            _FileRows(replace(source, reason=exc.reason) if source.reason is None else source)
            for source in declared
        ]
    primary = []
    for source in declared:
        file = _read_file(tree, tip, source, config)
        if any(row.origin.line is not None for row in file.rows):
            times = dates.blame_times(tree, file.source, file.line_count, state)
            file = replace(
                file,
                rows=tuple(_with_date(row, dates.changed(row.origin, times)) for row in file.rows),
            )
        primary.append(file)
    return [*primary, *_draft_files(tree, repo, config, primary, directory)]


def _read_brief(name: str, config: settings.Settings) -> tuple[model.Source, model.Lane | None]:
    declaration = config.sources.brief_source(name)
    fields = config.briefs.filename.match(unicodedata.normalize("NFC", name))
    if fields is None:
        return model.Source(declaration.kind, "", declaration.path, reason=sources.NOT_NAMED), None
    slug = fields["lane"]
    if not grammar.is_safe_lane_id(slug):
        return model.Source(
            declaration.kind, "", declaration.path, reason="unsafe lane identifier"
        ), None
    source = model.Source(declaration.kind, slug, declaration.path)
    result = config.sources.read_brief(name)
    if result.data is None:
        return replace(source, reason=result.reason), None
    try:
        goal, done, serves = markdown.brief(markdown.decode(result.data), config.briefs)
    except markdown.ParseError as exc:
        return replace(source, reason=exc.reason), None
    folder = config.briefs.lane_folders.get(slug)
    identity, reason = config.sources.lane_folder(folder) if folder is not None else (None, None)
    return source, model.Lane(slug, goal, done, serves, source, identity, reason)


def _read_briefs(config: settings.Settings) -> tuple[list[model.Source], tuple[model.Lane, ...]]:
    names = config.sources.brief_names()
    folder = config.sources.brief_folder
    states = [model.Source(folder.kind, "Lane briefs", folder.path, reason=names.reason)]
    lanes: list[model.Lane] = []
    # Two raw filenames can normalise to the same declared lane. Refuse both before opening either.
    normalised = Counter(unicodedata.normalize("NFC", name) for name in names.names)
    for name in names.names:
        if normalised[unicodedata.normalize("NFC", name)] > 1:
            declaration = config.sources.brief_source(name)
            states.append(
                model.Source(declaration.kind, "", declaration.path, reason=markdown.MALFORMED)
            )
            continue
        source, lane = _read_brief(name, config)
        states.append(source)
        if lane is not None:
            lanes.append(lane)
    return states, tuple(lanes)


def _log_lane(fields: dict[str, str], spec: settings.Log) -> str | None:
    lane = None
    if spec.lane.source == "field":
        lane = fields.get("lane")
    elif spec.lane.separator is not None and spec.lane.part is not None:
        parts = fields["id"].split(spec.lane.separator)
        if len(parts) > 1 and spec.lane.part < len(parts):
            lane = parts[spec.lane.part]
    return lane if lane is not None and grammar.is_safe_lane_id(lane) else None


def _event_fields(raw: bytes, spec: settings.Log) -> dict[str, str] | None:
    if len(raw) > spec.max_line_bytes:
        return None
    try:
        return spec.match(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def _read_log(
    config: settings.Settings, lane_names: set[str]
) -> tuple[model.Source, tuple[model.Ask, ...], dict[str, model.ItemDate], int | None]:
    result = config.sources.read_log()
    declared = config.sources.events
    spec = config.log
    source = model.Source(declared.kind, spec.label, declared.path, reason=result.reason)
    if result.data is None:
        return source, (), {}, None

    seen: set[str] = set()
    pending: dict[str, model.Ask] = {}
    lane_dates: dict[str, model.ItemDate] = {}
    rejected = 0
    # A CR or an invalid byte poisons its physical LF record, including text after that byte.
    for raw in result.data.removesuffix(b"\n").split(b"\n") if result.data else ():
        fields = _event_fields(raw, spec)
        if fields is None:
            rejected += 1
            continue
        key = fields[spec.answer_key]
        role = spec.verbs[fields["verb"]].role
        lane = _log_lane(fields, spec)
        timestamp = fields.get("ts")
        if role == "ask":
            if key in seen:
                rejected += 1
                continue
            pending[key] = model.Ask(
                fields["id"],
                fields.get("text"),
                timestamp,
                source.label,
                lane,
            )
            seen.add(key)
        elif role == "answer" and pending.pop(key, None) is None:
            rejected += 1
            continue
        if lane is not None and lane in lane_names:
            if timestamp is None:
                lane_dates.pop(lane, None)
            else:
                lane_dates[lane] = model.ItemDate("from the log", timestamp)
    return source, tuple(pending.values()), lane_dates, rejected


def _link_goals(
    rows: tuple[model.Goal, ...],
    lanes: tuple[model.Lane, ...],
    lane_dates: dict[str, model.ItemDate],
) -> tuple[tuple[model.Goal, ...], tuple[model.Lane, ...], int]:
    counts = Counter(goal.id for goal in rows)
    links: dict[str, list[str]] = defaultdict(list)
    linked_lanes = []
    mismatches = 0
    for lane in lanes:
        serves = tuple(goal for goal in lane.serves if counts[goal] == 1)
        mismatches += sum(counts[goal] == 0 for goal in lane.serves)
        linked_lanes.append(replace(lane, serves=serves, date=lane_dates.get(lane.slug)))
        for goal_id in serves:
            links[goal_id].append(lane.slug)
    goals = []
    for goal in rows:
        actual = tuple(links[goal.id])
        goals.append(replace(goal, lanes=actual))
        mismatches += len(set(actual).symmetric_difference(goal.lanes))
    return tuple(goals), tuple(linked_lanes), mismatches


def _lane_states(files: list[_FileRows], config: settings.Settings) -> dict[str, str]:
    """Each lane's group from the one primary tracker row that names it."""
    trackers = [file for file in files if file.source.kind == "tracker" and not file.source.draft]
    # An unread tracker file could hold a second row for any lane, so nothing is measured.
    if (
        config.tracker.lane_column is None
        or not trackers
        or any(file.source.reason is not None for file in trackers)
    ):
        return {}
    named: dict[str, list[str]] = defaultdict(list)
    mentioned: set[str] = set()
    for file in trackers:
        for row in file.rows:
            if isinstance(row, model.Item):
                if row.lane is not None:
                    named[row.lane].append(row.status)
                mentioned.update(row.mentions)
    return {
        lane: groups[0]
        for lane, groups in named.items()
        if len(groups) == 1 and lane not in mentioned
    }


def read_plan(
    config: settings.Settings,
    *,
    git_timeout_sec: float = 5.0,
    state: RuntimeState | None = None,
    git_deadline: float | None = None,
) -> model.PlanResult:
    files = [
        file
        for repo in config.sources.repositories
        for file in _repo_files(repo, config, git_timeout_sec, state, git_deadline)
    ]
    states = [file.source for file in files]
    rows = [row for file in files for row in file.rows]
    brief_states, lanes = _read_briefs(config)
    log_source, asks, lane_dates, rejected = _read_log(config, {lane.slug for lane in lanes})
    goals, lanes, mismatches = _link_goals(
        tuple(row for row in rows if isinstance(row, model.Goal)), lanes, lane_dates
    )
    lane_states = _lane_states(files, config)
    lanes = tuple(replace(lane, state=lane_states.get(lane.slug)) for lane in lanes)
    compared = (
        config.goals.lanes_label is not None
        and any(s.kind == "goals" and not s.draft for s in states)
        and all(
            source.reason is None
            for source in (*[s for s in states if s.kind == "goals" and not s.draft], *brief_states)
        )
    )
    refused_folders = tuple(
        model.Source("lane folder", lane.slug, "", reason=lane.folder_reason)
        for lane in lanes
        if lane.folder_reason is not None
    )
    return model.PlanResult(
        model.PlanModel(
            goals,
            tuple(row for row in rows if isinstance(row, model.Decision)),
            tuple(
                row
                for row in rows
                if isinstance(row, model.Item) and row.origin.source.kind == "inventory"
            ),
            tuple(
                row
                for row in rows
                if isinstance(row, model.Item) and row.origin.source.kind == "tracker"
            ),
            tuple(row for row in rows if isinstance(row, model.Diagram)),
            lanes,
            asks,
            (*states, *brief_states, *refused_folders, log_source),
            rejected,
        ),
        model.PlanDiagnostics(
            tuple(item for file in files for item in file.unknown), mismatches if compared else None
        ),
    )
