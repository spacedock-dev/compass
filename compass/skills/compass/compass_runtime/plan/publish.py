"""Project admitted plan rows onto the loopback response."""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import io, records

from . import grammar, markdown, model, readers, settings

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState

PLAN_FIELDS: Final = (
    "state",
    "goals",
    "lanes",
    "asks",
    "design",
    "tracker",
    "inventory",
    "diagrams",
    "sources",
    "logRejected",
    "limits",
)
# Published plan fields in SECURITY.md own these wire shapes.
PLAN_ITEM_FIELDS: Final = MappingProxyType(
    {
        "goals": frozenset({"id", "title", "doneWhen", "lanes", "proposal"}),
        "lanes": frozenset({"id", "title", "doneWhen", "state", "date", "sessions"}),
        "asks": frozenset({"id", "text", "at", "timeLabel", "source", "lane"}),
        "asks.lane": frozenset({"id", "title"}),
        "design": frozenset({"title", "summary", "decided", "source", "date"}),
        "tracker": frozenset({"title", "group", "source", "date"}),
        "inventory": frozenset({"title", "group", "source", "date"}),
        "diagrams": frozenset({"title", "caption", "kind", "source", "date", "linkHosts", "body"}),
        "date": frozenset({"label", "at"}),
        "sources": frozenset({"label", "kind", "state", "reason"}),
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


def _date(value: model.ItemDate | None) -> dict[str, str | None] | None:
    if value is None:
        return None
    return {"label": value.label, "at": _text(value.value)}


def _source(source: model.Source) -> dict[str, str | None]:
    return {
        "label": _text(source.label),
        "kind": source.display_kind,
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


def _lane_folders(lanes: tuple[model.Lane, ...]) -> dict[tuple[int, int], list[str]]:
    folders: dict[tuple[int, int], list[str]] = defaultdict(list)
    for lane in lanes:
        if lane.folder is not None:
            folders[lane.folder.device, lane.folder.inode].append(lane.slug)
    return folders


def _lane_for_cwd(
    cwd: str, folders: dict[tuple[int, int], list[str]], policy: io.PlanPathPolicy
) -> str | None:
    if not folders:
        return None
    ancestry = io.plan_session_ancestry(cwd, policy)
    if not ancestry:
        return None
    matches = [slug for identity in ancestry for slug in folders.get(identity, ())]
    return matches[0] if len(matches) == 1 else None


def _lane_sessions(
    lanes: tuple[model.Lane, ...],
    config: RuntimeConfig,
    state: RuntimeState,
    policy: io.PlanPathPolicy,
) -> dict[str, list[str]]:
    folders: dict[tuple[int, int], list[str]] = defaultdict(list)
    for lane in lanes:
        if lane.folder is not None:
            folders[lane.folder.device, lane.folder.inode].append(lane.slug)
    published = _published_folders(config, state)
    if published is None or not folders:
        return {}

    matched: dict[str, list[str]] = {slug: [] for slugs in folders.values() for slug in slugs}
    ancestry: dict[str, frozenset[tuple[int, int]] | None] = {}
    for harness, sid, cwd in published:
        if _text(harness) != harness or _text(sid) != sid:
            continue
        if cwd not in ancestry:
            ancestry[cwd] = io.plan_session_ancestry(cwd, policy)
        identities = ancestry[cwd]
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


def _project(plan: model.PlanModel, matched: dict[str, list[str]]) -> dict[str, Any]:
    lanes = tuple(lane for lane in plan.lanes if grammar.is_safe_lane_id(lane.slug))
    lane_titles = {lane.slug: _text(lane.goal) or lane.slug for lane in lanes}
    return {
        "state": "ready",
        "goals": [
            {
                "id": _text(goal.id),
                "title": _text(goal.title),
                "doneWhen": _text(goal.done),
                "lanes": [slug for slug in goal.lanes if grammar.is_safe_lane_id(slug)],
                "proposal": "Proposed, not merged" if goal.origin.source.draft else None,
            }
            for goal in plan.goals
        ],
        "lanes": [
            {
                "id": lane.slug,
                "title": lane_titles[lane.slug],
                "doneWhen": _text(lane.done),
                "state": lane.state if lane.state in LANE_STATES else None,
                "date": _date(lane.date),
                "sessions": matched.get(lane.slug),
            }
            for lane in lanes
        ],
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
        "limits": LIMITS,
    }


def payload(config: RuntimeConfig, state: RuntimeState) -> dict[str, Any]:
    loaded = settings.load(
        config.state_home, enabled=config.plan_enabled, git_enabled=config.git_probe_enabled
    )
    if loaded.settings is None:
        if loaded.reason == settings.NOT_CONFIGURED:
            return {"state": "not-configured"}
        return {"state": "refused", "reason": loaded.reason}

    timeout = config.git_probe_timeout_sec
    plan = readers.read_plan(
        loaded.settings,
        git_timeout_sec=timeout,
        state=state,
        git_deadline=time.monotonic() + timeout,
    ).model
    return _project(plan, _lane_sessions(plan.lanes, config, state, loaded.settings.sources.policy))


_SUMMARY_BYTES: Final = 1500
_SUMMARY_ASKS: Final = 3
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
# An unrecognised status is shown but never counted: it measures nothing about progress.
_MEASURED_STATES: Final = frozenset(settings.BOARD_GROUPS)
_UNMEASURED: Final = "not measured"


def _summary(plan: dict[str, Any], slug: str) -> str:
    lanes = plan["lanes"]
    matching = [lane for lane in lanes if lane["id"] == slug]
    if len(matching) != 1:
        return ""
    lane = matching[0]
    progress = _UNMEASURED
    serving = [goal["lanes"] for goal in plan["goals"] if slug in goal["lanes"]]
    if len(serving) == 1:
        measured = [
            row["state"]
            for row in lanes
            if row["id"] in serving[0]
            and isinstance(row["state"], str)
            and row["state"] in _MEASURED_STATES
        ]
        if measured:
            unit = "lane is" if len(measured) == 1 else "lanes are"
            progress = f"{measured.count('done')} of {len(measured)} {unit} done"
    state = lane["state"]
    lane_state = (
        _STATE_WORDS[state] if isinstance(state, str) and state in _STATE_WORDS else _UNMEASURED
    )
    status_lines = [f"Progress: {progress}", f"Lane state: {lane_state}"]
    asks = [ask["text"] for ask in plan["asks"] if ask["lane"] and ask["lane"]["id"] == slug]
    count = len(asks)
    # Reserve room for the status and omitted-ask lines before fitting whole fields.
    budget = _SUMMARY_BYTES - sum(len(line) + 1 for line in status_lines)
    if count:
        budget -= len(f"More open asks: {count}\n")

    def take(label: str, value: str | None) -> str | None:
        nonlocal budget
        if not value or not grammar.is_line(value):
            return None
        line = f"{label}: {value}"
        size = len(line.encode("utf-8")) + 1
        if size > budget:
            return None
        budget -= size
        return line

    lines = [
        line
        for label, value in (("Goal", lane["title"]), ("Done when", lane["doneWhen"]))
        if (line := take(label, value)) is not None
    ]
    questions = [line for ask in asks[:_SUMMARY_ASKS] if (line := take("Ask", ask)) is not None]
    lines.extend(status_lines)
    lines.extend(questions)
    if remaining := count - len(questions):
        lines.append(f"More open asks: {remaining}")
    # Two brief lines, two status lines, up to three asks and one count fit below the line cap.
    return "\n".join(lines)


def session_summary(home: str, *, lane: str | None, cwd: str | None = None) -> str:
    try:
        if lane is not None and not grammar.is_safe_lane_id(lane):
            return ""
        # Git supplies other board sections and dates. None of the summary fields need it.
        loaded = settings.load(home, git_enabled=False).settings
        if loaded is None or not loaded.summary_enabled:
            return ""
        plan = readers.read_plan(loaded).model
        if lane is None:
            lane = _lane_for_cwd(
                os.getcwd() if cwd is None else cwd,
                _lane_folders(plan.lanes),
                loaded.sources.policy,
            )
        return _summary(_project(plan, {}), lane) if lane is not None else ""
    except Exception:  # noqa: BLE001 - SessionStart must abstain even on an unexpected reader error.
        return ""
