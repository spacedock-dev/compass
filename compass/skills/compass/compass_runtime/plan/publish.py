"""Project admitted plan rows onto the loopback response."""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections import defaultdict
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import io, records

from . import grammar, markdown, model, readers, settings, summary_states

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


def _date(value: model.ItemDate | None) -> dict[str, str | None] | None:
    if value is None:
        return None
    return {"label": value.label, "at": _text(value.value)}


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
    fetch = state.plan_trackers.begin_fetch()
    loaded = settings.load(
        config.state_home, enabled=config.plan_enabled, git_enabled=config.git_probe_enabled
    )
    if loaded.settings is None:
        state.plan_trackers.observe("", (), enabled=False, fetch=fetch)
        if loaded.reason == settings.NOT_CONFIGURED:
            return {"state": "not-configured"}
        return {"state": "refused", "reason": loaded.reason}

    state.plan_trackers.observe(
        loaded.settings.digest,
        loaded.settings.trackers,
        enabled=config.plan_trackers_enabled,
        fetch=fetch,
    )
    timeout = config.git_probe_timeout_sec
    plan = readers.read_plan(
        loaded.settings,
        git_timeout_sec=timeout,
        state=state,
        git_deadline=time.monotonic() + timeout,
    ).model
    projected = _project(
        plan, _lane_sessions(plan.lanes, config, state, loaded.settings.sources.policy)
    )
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
