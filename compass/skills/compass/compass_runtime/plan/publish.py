"""Project admitted plan rows onto the loopback response."""

from __future__ import annotations

import json
import os
import stat
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import records

from . import model, readers, settings

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
LIMITS: Final = (
    "Compass cannot detect health information or confidential text typed into these sources."
)
_TEXT_CHARS = 512
_DIAGRAM_CHARS = 8192
_DIAGRAM_HOSTS = 32


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + records.CUT_MARK


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
        "kind": source.kind,
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


def _ancestry(cwd: str) -> frozenset[tuple[int, int]]:
    if not os.path.isabs(cwd):
        return frozenset()
    try:
        folder = Path(os.path.realpath(cwd, strict=True))
        identities = set()
        for parent in (folder, *folder.parents):
            info = parent.stat()
            if not stat.S_ISDIR(info.st_mode) or not info.st_ino:
                return frozenset()
            identities.add((info.st_dev, info.st_ino))
        return frozenset(identities)
    except (OSError, ValueError):
        return frozenset()


def _lane_sessions(
    lanes: tuple[model.Lane, ...], config: RuntimeConfig, state: RuntimeState
) -> dict[str, list[str]]:
    folders: dict[tuple[int, int], list[str]] = defaultdict(list)
    for lane in lanes:
        if lane.folder is not None:
            folders[lane.folder.device, lane.folder.inode].append(lane.slug)
    matched: dict[str, list[str]] = defaultdict(list)
    if not folders:
        return matched

    # The folder sidecar is bound to the same snapshot as the board rows.
    published = state.snapshot.session_folders((config.window_hours, False))
    if published is None:
        published = state.snapshot.session_folders((config.window_hours, True))

    ancestry: dict[str, frozenset[tuple[int, int]]] = {}
    for harness, sid, cwd in published or ():
        if _text(harness) != harness or _text(sid) != sid:
            continue
        if cwd not in ancestry:
            ancestry[cwd] = _ancestry(cwd)
        matches = [slug for identity in ancestry[cwd] for slug in folders.get(identity, ())]
        if len(matches) == 1:
            # Same wire key as the board's sessionKey helper.
            key = "session:" + json.dumps([harness, sid], ensure_ascii=False, separators=(",", ":"))
            if len(key) <= _TEXT_CHARS:
                matched[matches[0]].append(key)
    return matched


def _project(plan: model.PlanModel, matched: dict[str, list[str]]) -> dict[str, Any]:
    lane_titles = {lane.slug: _text(lane.goal) or lane.slug for lane in plan.lanes}
    return {
        "state": "ready",
        "goals": [
            {
                "id": _text(goal.id),
                "title": _text(goal.title),
                "doneWhen": _text(goal.done),
                "lanes": list(goal.lanes),
            }
            for goal in plan.goals
        ],
        "lanes": [
            {
                "id": lane.slug,
                "title": lane_titles[lane.slug],
                "doneWhen": _text(lane.done),
                "state": None,
                "date": _date(lane.date),
                "sessions": matched.get(lane.slug, []),
            }
            for lane in plan.lanes
        ],
        "asks": [
            {
                "id": _text(ask.id),
                "text": _text(ask.text),
                "at": _text(ask.timestamp),
                "timeLabel": "from the log",
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
    loaded = settings.load(config.state_home, git_enabled=config.git_probe_enabled)
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
    return _project(plan, _lane_sessions(plan.lanes, config, state))
