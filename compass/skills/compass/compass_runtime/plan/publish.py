"""Project admitted plan rows onto the loopback response."""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import cache
from itertools import pairwise
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import io, records

from . import (
    grammar,
    markdown,
    model,
    readers,
    settings,
    summary_states,
    tracker_cli,
    tracker_source,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState

    from .tracker_refresh import Observation, TrackerRefresh
    from .tracker_source import Declaration

PLAN_FIELDS: Final = (
    "state",
    "goals",
    "lanes",
    "asks",
    "trackerAsks",
    "trackerAsksEnabled",
    "trackerAsksFreshForMs",
    "design",
    "tracker",
    "inventory",
    "diagrams",
    "sources",
    "logRejected",
    "trackerRead",
    "limits",
)
# Published plan fields in SECURITY.md own these wire shapes.
PLAN_ITEM_FIELDS: Final = MappingProxyType(
    {
        "goals": frozenset(
            {"id", "title", "doneWhen", "lanes", "proposal", "date", "additionalDates"}
        ),
        "lanes": frozenset(
            {"id", "title", "doneWhen", "state", "date", "additionalDates", "sessions"}
        ),
        "asks": frozenset({"id", "text", "at", "timeLabel", "source", "lane"}),
        "asks.lane": frozenset({"id", "title"}),
        "trackerAsks": frozenset({"title", "linkHost", "source", "lane", "goals"}),
        "design": frozenset({"title", "summary", "decided", "source", "date"}),
        "tracker": frozenset({"title", "group", "source", "date"}),
        "inventory": frozenset({"title", "group", "source", "date"}),
        "diagrams": frozenset({"title", "caption", "kind", "source", "date", "linkHosts", "body"}),
        "trackerRead": frozenset(
            {"freshForMs", "localGoals", "localLanes", "localSources", "updates"}
        ),
        "trackerRead.update": frozenset({"freshForMs", "goals", "lanes", "sources"}),
        "trackerRead.changes": frozenset({"remove", "upsert"}),
        "date": frozenset({"label", "at"}),
        "sources": frozenset({"label", "kind", "fileLabel", "position", "state", "reason"}),
    }
)
# A lane's state is one of these, or null when no single primary tracker row names the lane.
LANE_STATES: Final = (*settings.BOARD_GROUPS, markdown.STATUS_UNKNOWN)
LIMITS: Final = (
    "Compass cannot detect health information or confidential text typed into these sources."
)
_TEXT_CHARS = 512
_DIAGRAM_CHARS = 8192
_DIAGRAM_HOSTS = 32


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = limit - len(records.CUT_MARK)
    marker = records.SECRET_MARKER
    start = text.find(marker, max(0, cut - len(marker) + 1), cut + len(marker) - 1)
    return text[: start if start != -1 else cut] + records.CUT_MARK


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    text, _ = records.hosts_only(records.redact_secrets(value))
    return _cap(text, _TEXT_CHARS)


type _TextProjection = Callable[[str | None], str | None]


def _date(
    value: model.ItemDate | None, text: _TextProjection = _text
) -> dict[str, str | None] | None:
    if value is None:
        return None
    return {"label": value.label, "at": text(value.value)}


def _source(source: model.Source) -> dict[str, str | int | None]:
    return {
        "label": _text(source.label),
        "kind": source.display_kind,
        "fileLabel": _text(source.file_label),
        "position": source.position,
        "state": "ok" if source.reason is None else "refused",
        "reason": source.reason,
    }


def _item(item: model.Item) -> dict[str, Any]:
    return {
        "title": _text(item.title),
        "group": item.status,
        "source": _text(item.origin.source.label),
        "date": _date(item.origin.date),
    }


def _diagram(diagram: model.Diagram) -> dict[str, Any]:
    body, body_hosts = records.hosts_only(records.redact_secrets(diagram.unredacted_body))
    caption, caption_hosts = records.hosts_only(records.redact_secrets(diagram.caption))
    return {
        "title": _cap(caption, _TEXT_CHARS),
        "caption": _cap(caption, _TEXT_CHARS),
        "kind": diagram.kind,
        "source": _text(diagram.origin.source.label),
        "date": _date(diagram.origin.date),
        "linkHosts": list(dict.fromkeys((*caption_hosts, *body_hosts)))[:_DIAGRAM_HOSTS],
        "body": _cap(body, _DIAGRAM_CHARS),
    }


def _published_folders(
    config: RuntimeConfig, state: RuntimeState
) -> tuple[tuple[str, str, str], ...] | None:
    # The folder sidecar is bound to the same snapshot as the board rows.
    published = state.snapshot.session_folders((config.window_hours, False))
    if published is None:
        published = state.snapshot.session_folders((config.window_hours, True))
    return published


def _lane_sessions(
    lanes: tuple[model.Lane, ...],
    published: tuple[tuple[str, str, str], ...] | None,
    ancestry: Callable[[str], frozenset[tuple[int, int]] | None],
) -> dict[str, list[str]]:
    folders: dict[tuple[int, int], list[str]] = defaultdict(list)
    for lane in lanes:
        if lane.folder is not None:
            folders[lane.folder.device, lane.folder.inode].append(lane.slug)
    if published is None or not folders:
        return {}

    matched: dict[str, list[str]] = {slug: [] for slugs in folders.values() for slug in slugs}
    for harness, sid, cwd in published:
        if _text(harness) != harness or _text(sid) != sid:
            continue
        identities = ancestry(cwd)
        if identities is None:
            # An unexamined folder could sit below any lane folder, so no lane's list is complete.
            return {}
        matches = [slug for identity in identities for slug in folders.get(identity, ())]
        if len(matches) == 1:
            # Same wire key as the board's sessionKey helper.
            key = "session:" + json.dumps([harness, sid], ensure_ascii=False, separators=(",", ":"))
            if len(key) <= _TEXT_CHARS:
                matched[matches[0]].append(key)
    return matched


def _goals(goals: tuple[model.Goal, ...], text: _TextProjection = _text) -> list[dict[str, Any]]:
    return [
        {
            "id": text(goal.id),
            "title": text(goal.title),
            "doneWhen": text(goal.done),
            "lanes": [slug for slug in goal.lanes if grammar.is_safe_lane_id(slug)],
            "proposal": "Proposed, not merged" if goal.origin.source.draft else None,
            "date": _date(goal.origin.date, text)
            if goal.origin.date and goal.origin.date.label in ("Due", "Target")
            else None,
            "additionalDates": [_date(date, text) for date in goal.origin.additional_dates],
        }
        for goal in goals
    ]


def _lanes(
    lanes: tuple[model.Lane, ...], matched: dict[str, list[str]], text: _TextProjection = _text
) -> list[dict[str, Any]]:
    return [
        {
            "id": lane.slug,
            "title": text(lane.goal) or lane.slug,
            "doneWhen": text(lane.done),
            "state": lane.state if lane.state in LANE_STATES else None,
            "date": _date(lane.date, text),
            "additionalDates": [_date(date, text) for date in lane.additional_dates],
            "sessions": matched.get(lane.slug),
        }
        for lane in lanes
        if grammar.is_safe_lane_id(lane.slug)
    ]


def _project(plan: model.PlanModel, matched: dict[str, list[str]]) -> dict[str, Any]:
    lanes = _lanes(plan.lanes, matched)
    lane_titles = {row["id"]: row["title"] for row in lanes}
    return {
        "state": "ready",
        "goals": _goals(plan.goals),
        "lanes": lanes,
        "asks": [
            {
                "id": _text(ask.id),
                "text": _text(ask.text),
                "at": _text(ask.timestamp),
                "timeLabel": ask.date.label if ask.date is not None else None,
                "source": _text(ask.source),
                "lane": {"id": ask.lane, "title": lane_titles[ask.lane]}
                if ask.lane is not None and ask.lane in lane_titles
                else None,
            }
            for ask in plan.asks
        ],
        "trackerAsks": None,
        "trackerAsksEnabled": False,
        "trackerAsksFreshForMs": None,
        "design": [
            {
                "title": _text(decision.title),
                "summary": None,
                "decided": decision.decided,
                "source": _text(decision.origin.source.label),
                "date": _date(decision.origin.date),
            }
            for decision in plan.decisions
        ],
        "tracker": [_item(item) for item in plan.tracker],
        "inventory": [_item(item) for item in plan.inventory],
        "diagrams": [_diagram(diagram) for diagram in plan.diagrams],
        "sources": [_source(source) for source in plan.sources],
        "logRejected": plan.log_rejected,
        "trackerRead": None,
        "limits": LIMITS,
    }


def _issue_revision(lane: model.Lane) -> tuple[datetime, str]:
    if lane.date is None or lane.date.label != "Updated" or lane.date.value is None:
        return datetime.min.replace(tzinfo=UTC), ""
    stamp = lane.date.value
    # datetime parses microseconds, while the tracker admits up to nine fractional digits.
    zone_width = 1 if stamp.endswith("Z") else 6
    fraction = stamp[:-zone_width].partition(".")[2]
    return datetime.fromisoformat(stamp), fraction.ljust(9, "0")[6:]


def _issue_dates(
    copies: list[model.Lane],
) -> tuple[model.ItemDate | None, tuple[model.ItemDate, ...]]:
    revisions = [_issue_revision(lane) for lane in copies]
    newest = max(revisions)
    latest = [lane for lane, revision in zip(copies, revisions, strict=True) if revision == newest]
    first = latest[0]
    # A newer revision can clear a date. For equal revisions keep only dates every copy agrees on.
    dates = tuple(
        date
        for date in first.additional_dates
        if all(date in lane.additional_dates for lane in latest[1:])
    )
    primary = min(
        (lane.date for lane in latest if lane.date is not None),
        key=lambda date: date.value or "",
        default=None,
    )
    return primary, dates


def _merge_tracker_rows(
    local: model.PlanModel,
    data: Iterable[model.TrackerData],
    lane_folders: dict[str, str],
    lane_folder: Callable[[str], tuple[model.FolderIdentity | None, str | None]],
) -> model.PlanModel:
    goals = list(local.goals)
    lanes = {lane.slug: lane for lane in local.lanes}
    sources = list(local.sources)
    explicit: dict[str, set[str | None]] = {
        slug: {state} for slug, state in local.file_lane_states.items()
    }
    ordinary: dict[str, set[str | None]] = defaultdict(set)
    remote: dict[str, list[model.Lane]] = defaultdict(list)
    for read in data:
        goals.extend(read.goals)
        for lane in read.lanes:
            remote[lane.slug].append(lane)
            current = lanes.setdefault(lane.slug, lane)
            lanes[lane.slug] = replace(
                current,
                serves=tuple(dict.fromkeys((*current.serves, *lane.serves))),
            )
            if lane.slug in read.project_status_lanes:
                explicit.setdefault(lane.slug, set()).add(lane.state)
            else:
                ordinary[lane.slug].add(lane.state)

    local_lanes = {lane.slug: lane for lane in local.lanes}
    for slug in sorted(remote):
        lane = lanes[slug]
        primary, dates = _issue_dates(remote[slug])
        local_lane = local_lanes.get(slug)
        if local_lane is not None:
            primary = local_lane.date or primary
            local_labels = {date.label for date in local_lane.additional_dates}
            dates = (
                *local_lane.additional_dates,
                *(date for date in dates if date.label not in local_labels),
            )
        states = explicit.get(slug) or ordinary[slug]
        folder = lane_folders.get(slug)
        if folder is not None and lane.folder is None and lane.folder_reason is None:
            identity, reason = lane_folder(folder)
            lane = replace(lane, folder=identity, folder_reason=reason)
            if reason is not None:
                sources.append(model.Source("lane folder", slug, "", reason=reason))
        lanes[slug] = replace(
            lane,
            date=primary,
            additional_dates=dates,
            state=next(iter(states)) if len(states) == 1 else None,
        )

    # Both row types carry membership. Preserve local rows with duplicate goal IDs, which
    # deliberately have their own lane lists, and add any new edges explicitly named by lanes.
    members: dict[str, list[str]] = defaultdict(list)
    for lane in lanes.values():
        for goal_id in lane.serves:
            members[goal_id].append(lane.slug)
    goals = [
        replace(goal, lanes=tuple(dict.fromkeys((*goal.lanes, *members[goal.id]))))
        for goal in goals
    ]
    return replace(local, goals=tuple(goals), lanes=tuple(lanes.values()), sources=tuple(sources))


@dataclass(frozen=True)
class _FreshTrackerRead:
    data: model.TrackerData
    observed_at: float
    fresh_for_ms: int


def _freshest_goals(reads: dict[int, _FreshTrackerRead]) -> dict[str, model.TrackerData]:
    by_goal: dict[str, _FreshTrackerRead] = {}
    for read in reads.values():
        (goal,) = read.data.goals
        previous = by_goal.get(goal.id)
        if previous is None or read.observed_at > previous.observed_at:
            by_goal[goal.id] = read
    # An alias can report an empty goal. Its older membership must not enter the merge.
    return {goal_id: read.data for goal_id, read in by_goal.items()}


def _tracker_projection(
    observations: tuple[Observation, ...], settings: settings.Settings, refresh: TrackerRefresh
) -> tuple[list[dict[str, Any]], dict[int, _FreshTrackerRead], int | None]:
    kinds = Counter((source.provider, source.kind) for source in settings.trackers)
    positions: Counter[tuple[str, str]] = Counter()
    sources = []
    data = {}
    ask_lifetimes = []
    remaining = refresh.remaining_ms(observations)
    for index, (declaration, observation) in enumerate(
        zip(settings.trackers, observations, strict=True)
    ):
        kind = declaration.kind
        provider = declaration.provider
        group = (provider, kind)
        positions[group] += 1
        lifetime = remaining[index]
        reason: str | None = observation.reason or tracker_cli.Reason.CLI_FAILED
        if observation.data is not None and observation.observed_at is not None and lifetime:
            data[index] = _FreshTrackerRead(observation.data, observation.observed_at, lifetime)
            if declaration.ask_labels:
                ask_lifetimes.append(lifetime)
            status = "ok" if observation.data.lanes else "empty"
            reason = None
        elif observation.data is not None:
            status, reason = "expired", "expired"
        else:
            status = "refreshing" if reason == tracker_cli.Reason.REFRESHING else "refused"
        labels = (
            tracker_source.GITHUB_SOURCE_LABELS
            if provider == "github"
            else tracker_source.LINEAR_SOURCE_LABELS
        )
        sources.append(
            {
                "label": labels[kind],
                "kind": f"{provider} {kind}",
                "fileLabel": None,
                "position": positions[group] if kinds[group] > 1 else None,
                "state": status,
                "reason": reason,
            }
        )
    return sources, data, min(ask_lifetimes, default=None)


def _row_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    previous: dict[str, list[dict[str, Any]]] = defaultdict(list)
    current: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in before:
        previous[row["id"]].append(row)
    for row in after:
        current[row["id"]].append(row)
    return {
        "remove": [key for key in previous if key not in current],
        "upsert": [row for row in after if current[row["id"]] != previous.get(row["id"])],
    }


def _expired_sources(sources: list[dict[str, Any]], expired: set[int]) -> list[dict[str, Any]]:
    return [
        {**source, "state": "expired", "reason": "expired"} if index in expired else source
        for index, source in enumerate(sources)
    ]


def _tracker_updates(
    reads: dict[int, _FreshTrackerRead],
    render: Callable[
        [dict[int, _FreshTrackerRead]],
        tuple[model.PlanModel, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]],
    ],
    goals: list[dict[str, Any]],
    lanes: list[dict[str, Any]],
    local_sources: list[dict[str, Any]],
    tracker_sources: list[dict[str, Any]],
) -> list[tuple[float, dict[str, Any]]]:
    deadlines = sorted({read.observed_at for read in reads.values()})
    updates = []
    for at, next_at in pairwise(deadlines):
        expired = {index for index, read in reads.items() if read.observed_at <= at}
        _, next_goals, next_lanes, folder_sources = render(
            {index: read for index, read in reads.items() if index not in expired}
        )
        updates.append(
            (
                next_at,
                {
                    "goals": _row_changes(goals, next_goals),
                    "lanes": _row_changes(lanes, next_lanes),
                    "sources": [
                        *local_sources,
                        *_expired_sources(tracker_sources, expired),
                        *folder_sources,
                    ],
                },
            )
        )
        goals, lanes = next_goals, next_lanes
    return updates


def _ask_revision(lane: model.Lane, source_label: str) -> tuple[datetime, str, str]:
    timestamp = lane.date.value if lane.date else None
    revision = datetime.fromisoformat(timestamp) if timestamp else datetime.min.replace(tzinfo=UTC)
    return revision, lane.goal or "", source_label


type _AskCandidate = tuple[model.TrackerAskIssue, tuple[str, ...], str]


def _tracker_asks(
    declarations: tuple[Declaration, ...],
    reads: dict[int, _FreshTrackerRead],
    sources: list[dict[str, Any]],
    lanes: tuple[model.Lane, ...],
) -> list[dict[str, Any]] | None:
    freshest = _freshest_goals(reads)
    copies: dict[str, list[model.TrackerAskIssue]] = defaultdict(list)
    candidates: dict[str, list[_AskCandidate]] = defaultdict(list)
    account = None
    for index, declaration in enumerate(declarations):
        if not declaration.ask_labels:
            continue
        fresh = reads.get(index)
        if fresh is None or (read := fresh.data.ask_read) is None:
            return None
        (goal,) = fresh.data.goals
        current = freshest[goal.id].ask_read
        if current is None or current.viewer != read.viewer:
            return None
        if account is not None and account != (declaration.provider, read.viewer):
            return None
        account = declaration.provider, read.viewer
        for issue in read.issues:
            copies[issue.lane.slug].append(issue)
        source_label = sources[index]["label"]
        for issue in current.issues:
            candidates[issue.lane.slug].append((issue, declaration.ask_labels, source_label))

    link_host = "linear.app" if account is not None and account[0] == "linear" else "github.com"
    return _publish_tracker_asks(candidates, copies, lanes, link_host)


def _publish_tracker_asks(
    candidates: dict[str, list[_AskCandidate]],
    copies: dict[str, list[model.TrackerAskIssue]],
    lanes: tuple[model.Lane, ...],
    link_host: str,
) -> list[dict[str, Any]] | None:
    asks: dict[str, tuple[model.Lane, str]] = {}
    for slug, rules in candidates.items():
        qualifying = []
        for issue, rule, source_label in rules:
            matches = issue.matches(rule)
            # Only current membership supplies candidates. Enabled observations can still
            # contradict a match, even when an alias no longer supplies the goal's lanes.
            if any(other.matches(rule) != matches for other in copies[slug]):
                return None
            if matches:
                qualifying.append((issue.lane, source_label))
        if qualifying:
            asks[slug] = max(qualifying, key=lambda candidate: _ask_revision(*candidate))
    published = []
    for lane in lanes:
        if (ask := asks.get(lane.slug)) is None:
            continue
        issue_lane, source_label = ask
        published.append(
            {
                "title": _text(issue_lane.goal),
                "linkHost": link_host,
                "source": _text(source_label),
                "lane": lane.slug,
                "goals": [_text(goal_id) for goal_id in lane.serves],
            }
        )
    return published


def payload(config: RuntimeConfig, state: RuntimeState) -> dict[str, Any]:
    trackers = state.plan_trackers
    with trackers.settings_lock:
        loaded = settings.load(
            config.state_home, enabled=config.plan_enabled, git_enabled=config.git_probe_enabled
        )
        if loaded.settings is None:
            trackers.observe("", (), enabled=False)
            if loaded.reason == settings.NOT_CONFIGURED:
                return {"state": "not-configured"}
            return {"state": "refused", "reason": loaded.reason}

        observations = trackers.observe(
            loaded.settings.digest,
            loaded.settings.trackers,
            enabled=config.plan_trackers_enabled,
        )
    timeout = config.git_probe_timeout_sec
    plan = readers.read_plan(
        loaded.settings,
        git_timeout_sec=timeout,
        state=state,
        git_deadline=time.monotonic() + timeout,
    ).model
    policy = loaded.settings.sources.policy
    published = _published_folders(config, state)
    ancestry = cache(lambda cwd: io.plan_session_ancestry(cwd, policy))
    projected = _project(plan, _lane_sessions(plan.lanes, published, ancestry))
    if not loaded.settings.summary_enabled:
        # A file left from before the summary was turned off would describe a tracker no board
        # has read since; withdraw it so turning the summary on again starts unmeasured.
        summary_states.forget(config.state_home)
    elif config.git_probe_enabled:
        # Saved for the SessionStart summary, which cannot read the tracker itself. Without Git
        # the board read no tracker, so it keeps the last file rather than saving nothing over
        # it. A failed write leaves that file to age out; the board's reply does not depend on it.
        with contextlib.suppress(OSError, ValueError):
            summary_states.save(
                config.state_home, projected, now=time.time(), settings=loaded.settings.digest
            )
    return _with_tracker_reads(
        projected, plan, loaded.settings, observations, trackers, published, ancestry
    )


def _with_tracker_reads(
    projected: dict[str, Any],
    plan: model.PlanModel,
    settings: settings.Settings,
    observations: tuple[Observation, ...],
    trackers: TrackerRefresh,
    published: tuple[tuple[str, str, str], ...] | None,
    ancestry: Callable[[str], frozenset[tuple[int, int]] | None],
) -> dict[str, Any]:
    admitted_folder = cache(settings.sources.lane_folder)
    # Shared text passes through the same redaction at every deadline in this reply.
    text = cache(_text)
    lane_folders = settings.tracker_lane_folders()

    def render(
        reads: dict[int, _FreshTrackerRead],
    ) -> tuple[model.PlanModel, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        merged = _merge_tracker_rows(
            plan, _freshest_goals(reads).values(), lane_folders, admitted_folder
        )
        matched = _lane_sessions(merged.lanes, published, ancestry)
        return (
            merged,
            _goals(merged.goals, text),
            _lanes(merged.lanes, matched, text),
            [_source(source) for source in merged.sources[len(plan.sources) :]],
        )

    asks_enabled = any(source.ask_labels for source in settings.trackers)
    projected["trackerAsksEnabled"] = asks_enabled
    tracker_sources, reads, _ = _tracker_projection(observations, settings, trackers)
    local_sources = projected["sources"]
    while reads:
        merged, goals, lanes, folder_sources = render(reads)
        updates = _tracker_updates(reads, render, goals, lanes, local_sources, tracker_sources)
        # Folder admission and the session join can finish after a read's deadline.
        # Rebuild without reads that expired while projecting the board.
        next_sources, still_fresh, next_ask_lifetime = _tracker_projection(
            observations, settings, trackers
        )
        if still_fresh.keys() == reads.keys():
            deadlines = {read.observed_at: read.fresh_for_ms for read in still_fresh.values()}
            projected.update(
                goals=goals,
                lanes=lanes,
                sources=[*local_sources, *tracker_sources, *folder_sources],
                trackerRead={
                    "freshForMs": min(deadlines.values()),
                    "localGoals": projected["goals"],
                    "localLanes": projected["lanes"],
                    "localSources": [
                        *local_sources,
                        *_expired_sources(tracker_sources, set(reads)),
                    ],
                    "updates": [
                        {"freshForMs": deadlines[observed_at], **update}
                        for observed_at, update in updates
                    ],
                },
            )
            if asks_enabled:
                asks = _tracker_asks(settings.trackers, still_fresh, tracker_sources, merged.lanes)
                if asks is not None:
                    projected.update(trackerAsks=asks, trackerAsksFreshForMs=next_ask_lifetime)
            return projected
        tracker_sources, reads = next_sources, still_fresh
    local_sources.extend(tracker_sources)
    return projected


_SUMMARY_BYTES: Final = 1500
_SUMMARY_ASKS: Final = 3
# Each text line is cut to its own byte cap, so every field fits and none is dropped for size:
# 2 * 320 + 3 * 240 for the text, at most 37 for progress (4,096 lanes, the saved-state cap),
# 33 for the widest lane state, 30 for the omitted-ask count and 7 newlines is 1,467 bytes.
_BRIEF_LINE_BYTES: Final = 320
_ASK_LINE_BYTES: Final = 240
# The summary's plain words for each published lane state: a closed table, so no published text
# is echoed as a state. Planned, In progress, Blocked and Done are the Plan page's words; Waiting
# and Dropped are chosen here because the page has no lane word for them.
_STATE_WORDS: Final = MappingProxyType(
    {
        "not_started": "Planned",
        "running": "In progress",
        "waiting": "Waiting",
        "blocked": "Blocked",
        "done": "Done",
        "dropped": "Dropped",
        markdown.STATUS_UNKNOWN: markdown.STATUS_UNKNOWN,
    }
)
# Dropped and unrecognised states are shown but never counted: neither says how far the goal is.
_COUNTED_STATES: Final = frozenset(settings.BOARD_GROUPS) - {"dropped"}
_UNMEASURED: Final = "not measured"


def _fit(label: str, value: str | None, limit: int) -> str | None:
    """`label: value` within `limit` UTF-8 bytes, cut at a character with a redaction marker
    kept whole; None for an empty value or one that is not a single line."""
    if not value or not grammar.is_line(value):
        return None
    line = f"{label}: {value}"
    if len(line.encode("utf-8")) <= limit:
        return line
    room = limit - len(records.CUT_MARK.encode("utf-8"))
    cut = len(line.encode("utf-8")[:room].decode("utf-8", "ignore"))
    marker = records.SECRET_MARKER
    start = line.find(marker, max(0, cut - len(marker) + 1), cut + len(marker) - 1)
    return line[: start if start != -1 else cut] + records.CUT_MARK


def _progress(slug: str, snapshot: summary_states.Snapshot | None) -> str:
    """Done lanes among the measured lanes serving the lane's one goal, worded as the Plan page
    words it. With no lane measured there is no count, so it never reads "0 of 0"."""
    if snapshot is None:
        return _UNMEASURED
    serving = [goal for goal in snapshot.goals if slug in goal]
    if len(serving) != 1:
        return _UNMEASURED
    measured = [
        state
        for lane in serving[0]
        if (state := snapshot.states.get(lane)) is not None and state in _COUNTED_STATES
    ]
    if not measured:
        return _UNMEASURED
    done = measured.count("done")
    unit = "lane is" if len(measured) == 1 else "lanes are"
    return f"{done} of {len(measured)} {unit} done"


def _summary(
    lane: dict[str, Any], asks: list[str | None], snapshot: summary_states.Snapshot | None
) -> str:
    slug = lane["id"]
    state = snapshot.states.get(slug) if snapshot is not None else None
    shown = [line for text in asks if (line := _fit("Ask", text, _ASK_LINE_BYTES)) is not None][
        :_SUMMARY_ASKS
    ]
    lines = [
        line
        for label, value in (("Goal", lane["title"]), ("Done when", lane["doneWhen"]))
        if (line := _fit(label, value, _BRIEF_LINE_BYTES)) is not None
    ]
    lines.append(f"Progress: {_progress(slug, snapshot)}")
    lines.append(f"Lane state: {_STATE_WORDS.get(state, _UNMEASURED) if state else _UNMEASURED}")
    lines.extend(shown)
    if remaining := len(asks) - len(shown):
        lines.append(f"More open asks: {remaining}")
    # At most two brief lines, two status lines, three asks and one count: below the line cap.
    return "\n".join(lines)


def _summary_lane(config: settings.Settings, cwd: str) -> model.Lane | None:
    """The one lane whose declared folder holds `cwd`, among lanes the board would publish.

    The board matches against lanes whose brief it read. Here a declared folder is checked under
    the privacy rules, and its brief read, only when a plain stat puts it in `cwd`'s admitted
    ancestry: the same answer, without walking 200 folders inside the hook's time limit.
    """
    brief = config.briefs
    if brief is None:
        return None
    ancestry = io.plan_session_ancestry(cwd, config.sources.policy)
    if not ancestry:
        return None
    matches: list[model.Lane] = []
    for slug, folder in brief.lane_folders.items():
        try:
            info = os.stat(folder)
        except OSError:
            continue
        identity = (info.st_dev, info.st_ino)
        if identity not in ancestry:
            continue
        matches.extend(
            lane
            for lane in readers.lane_briefs(config, slug)
            if lane.folder is not None and (lane.folder.device, lane.folder.inode) == identity
        )
    return matches[0] if len(matches) == 1 else None


def _states_admitted(config: settings.Settings) -> bool:
    """Whether the settings still admit every tracker and goals file the saved states came from.

    The check is the board's own, by metadata and with no Git: a repository that has since gone
    or become private measures nothing, whatever the file says.
    """
    return all(
        config.sources.declared_tree_source(repo, kind, path).reason is None
        for repo in config.sources.repositories
        for kind, path in repo.files
        if kind in {"tracker", "goals"}
    )


def session_summary(
    home: str, *, lane: str | None, cwd: str | None = None, now: float | None = None
) -> str:
    try:
        if lane is not None and not grammar.is_safe_lane_id(lane):
            return ""
        # The settings are admitted as a board with Git on admits them; that check runs no Git.
        # The summary then reads only the lane's brief and the log, never a repository, so the
        # hook starts no program. Lane state and progress come from what the board last saved
        # (`summary_states`).
        loaded = settings.load(home).settings
        if loaded is None or not loaded.summary_enabled:
            return ""
        if lane is not None:
            briefs = readers.lane_briefs(loaded, lane)
            brief = briefs[0] if len(briefs) == 1 else None
        else:
            brief = _summary_lane(loaded, os.getcwd() if cwd is None else cwd)
        if brief is None:
            return ""
        # Only this lane's fields are projected, through the board's own text filter.
        row = {
            "id": brief.slug,
            "title": _text(brief.goal) or brief.slug,
            "doneWhen": _text(brief.done),
        }
        asks = [_text(ask.text) for ask in readers.lane_asks(loaded, brief.slug)]
        snapshot = (
            summary_states.load(
                home, now=time.time() if now is None else now, settings=loaded.digest
            )
            if _states_admitted(loaded)
            else None
        )
        return _summary(row, asks, snapshot)
    except Exception:  # noqa: BLE001 - SessionStart must abstain even on an unexpected reader error.
        return ""
