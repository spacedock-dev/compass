"""Assemble the plan from a fresh set of independently admitted sources."""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from compass_runtime import git_status

from . import grammar, markdown, model, sources

if TYPE_CHECKING:
    from . import settings

MAX_REPO_FILE_BYTES = 256 * 1024


@dataclass
class _RepoRows:
    goals: list[tuple[model.Goal, tuple[str, ...]]] = field(default_factory=list)
    decisions: list[model.Decision] = field(default_factory=list)
    inventory: list[model.Item] = field(default_factory=list)
    tracker: list[model.Item] = field(default_factory=list)
    diagrams: list[model.Diagram] = field(default_factory=list)
    unknown_statuses: list[model.UnknownStatus] = field(default_factory=list)

    def append(self, text: str, source: model.Source, config: settings.Settings) -> None:
        match source.kind:
            case "goals":
                self.goals.extend(markdown.goals(text, config.goals, config.briefs, source))
            case "decisions":
                self.decisions.extend(markdown.decisions(text, config.decisions, source))
            case "inventory":
                rows, unknown = markdown.inventory(text, config.inventory, source)
                self.inventory.extend(rows)
                self.unknown_statuses.extend(unknown)
            case "tracker":
                rows, unknown = markdown.tracker(text, config.tracker, source)
                self.tracker.extend(rows)
                self.unknown_statuses.extend(unknown)
            case "diagrams":
                self.diagrams.extend(markdown.diagrams(text, config.diagrams, source))


def _repo_sources(
    repo: sources.Repository, config: settings.Settings, rows: _RepoRows, timeout_sec: float
) -> list[model.Source]:
    states = []
    tree = None
    tip = None
    tip_failure = None
    for kind, path in repo.files:
        checked = config.sources.tree_source(repo.label, repo.ref, path, kind=kind)
        source = model.Source(kind, repo.label, path, repo.ref, reason=checked.reason)
        try:
            if source.reason is None and tree is None:
                tree = git_status.plan_reader(repo.path, timeout_sec=timeout_sec)
                try:
                    tip = tree.tip(repo.ref)
                except git_status.PlanGitError as exc:
                    tip_failure = exc.reason
            if source.reason is None:
                source = replace(source, commit=tip, reason=tip_failure)
                if tree is not None and tip is not None:
                    data = tree.tree_file(tip, path, max_bytes=MAX_REPO_FILE_BYTES)
                    rows.append(markdown.decode(data), source, config)
        except (git_status.PlanGitError, markdown.ParseError) as exc:
            source = replace(source, reason=exc.reason)
        states.append(source)
    return states


def _read_brief(name: str, config: settings.Settings) -> tuple[model.Source, model.Lane | None]:
    declaration = config.sources.brief_source(name)
    fields = config.briefs.filename.match(unicodedata.normalize("NFC", name))
    if fields is None:
        return model.Source(declaration.kind, "", declaration.path, reason=sources.NOT_NAMED), None
    slug = fields["lane"]
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


def _ask_lane(fields: dict[str, str], spec: settings.Log) -> str | None:
    lane = None
    if spec.lane.source == "field":
        lane = fields.get("lane")
    elif spec.lane.separator is not None and spec.lane.part is not None:
        parts = fields["id"].split(spec.lane.separator)
        if len(parts) > 1 and spec.lane.part < len(parts):
            lane = parts[spec.lane.part]
    return lane if lane is not None and grammar.is_slug(lane) else None


def _event_fields(raw: bytes, spec: settings.Log) -> dict[str, str] | None:
    if len(raw) > spec.max_line_bytes:
        return None
    try:
        return spec.match(raw.decode("utf-8"))
    except UnicodeDecodeError:
        return None


def _read_log(config: settings.Settings) -> tuple[model.Source, tuple[model.Ask, ...], int | None]:
    result = config.sources.read_log()
    declared = config.sources.events
    spec = config.log
    source = model.Source(declared.kind, spec.label, declared.path, reason=result.reason)
    if result.data is None:
        return source, (), None

    seen: set[str] = set()
    pending: dict[str, model.Ask] = {}
    rejected = 0
    # A CR or an invalid byte poisons its physical LF record, including text after that byte.
    for raw in result.data.removesuffix(b"\n").split(b"\n") if result.data else ():
        fields = _event_fields(raw, spec)
        if fields is None:
            rejected += 1
            continue
        key = fields[spec.answer_key]
        role = spec.verbs[fields["verb"]].role
        if role == "ask":
            if key in seen:
                rejected += 1
                continue
            pending[key] = model.Ask(
                fields["id"],
                fields.get("text"),
                fields.get("ts"),
                source.label,
                _ask_lane(fields, spec),
            )
            seen.add(key)
        elif role == "answer" and pending.pop(key, None) is None:
            rejected += 1
    return source, tuple(pending.values()), rejected


def _link_goals(
    rows: list[tuple[model.Goal, tuple[str, ...]]],
    lanes: tuple[model.Lane, ...],
) -> tuple[tuple[model.Goal, ...], tuple[model.Lane, ...], int]:
    counts = Counter(goal.id for goal, _ in rows)
    links: dict[str, list[str]] = defaultdict(list)
    linked_lanes = []
    for lane in lanes:
        serves = tuple(goal for goal in lane.serves if counts[goal] == 1)
        linked_lanes.append(replace(lane, serves=serves))
        for goal_id in serves:
            links[goal_id].append(lane.slug)
    goals = []
    mismatches = 0
    for goal, declared in rows:
        actual = tuple(links[goal.id])
        goals.append(replace(goal, lanes=actual))
        mismatches += len(set(actual).symmetric_difference(declared))
    return tuple(goals), tuple(linked_lanes), mismatches


def read_plan(config: settings.Settings, *, git_timeout_sec: float = 5.0) -> model.PlanResult:
    rows = _RepoRows()
    states = [
        source
        for repo in config.sources.repositories
        for source in _repo_sources(repo, config, rows, git_timeout_sec)
    ]
    brief_states, lanes = _read_briefs(config)
    log_source, asks, rejected = _read_log(config)
    goals, lanes, mismatches = _link_goals(rows.goals, lanes)
    compared = (
        config.goals.lanes_label is not None
        and bool(rows.goals)
        and all(
            source.reason is None
            for source in (*[s for s in states if s.kind == "goals"], *brief_states)
        )
    )
    return model.PlanResult(
        model.PlanModel(
            goals,
            tuple(rows.decisions),
            tuple(rows.inventory),
            tuple(rows.tracker),
            tuple(rows.diagrams),
            lanes,
            asks,
            (*states, *brief_states, log_source),
            rejected,
        ),
        model.PlanDiagnostics(tuple(rows.unknown_statuses), mismatches if compared else None),
    )
