"""Read Linear project and milestone membership through the installed Linear CLI."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from compass_runtime import records

from . import grammar, markdown, model, tracker_source
from .tracker_cli import LINEAR_VIEWER_QUERY, Reason, TrackerError

if TYPE_CHECKING:
    from .tracker_cli import TrackerCLI

# The CLI paginates internally for --limit all. Compass bounds its decoded rows as well as bytes.
_ROW_LIMIT = 200
# The CLI flattens the default label page without reporting whether another page exists.
_LABEL_PAGE_SIZE = 50
_WEB = "https://linear.app"
_STATE_TYPES = {
    "backlog": "not_started",
    "triage": "not_started",
    "unstarted": "not_started",
    "started": "running",
    "completed": "done",
    "canceled": "dropped",
    "duplicate": "dropped",
}


def _object(value: object, required: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TrackerError(Reason.UNREADABLE_OUTPUT)
    if value.get("errors") or not set(required.split()) <= value.keys():
        raise TrackerError(Reason.PARTIAL)
    return value


def _rows(value: object) -> list[object]:
    if isinstance(value, dict) and value.get("errors"):
        raise TrackerError(Reason.PARTIAL)
    if not isinstance(value, list):
        raise TrackerError(Reason.UNREADABLE_OUTPUT)
    if len(value) >= _ROW_LIMIT:
        raise TrackerError(Reason.LIMIT_EXCEEDED)
    return value


def _entity_slug(value: object, workspace: str, entity: str) -> str:
    if isinstance(value, str) and grammar.is_line(value) and not any(map(str.isspace, value)):
        url = urlsplit(value)
        parts = url.path.split("/")
        if (
            url.scheme == "https"
            and url.netloc.lower() == "linear.app"
            and parts[:3] == ["", workspace, entity]
            and len(parts) >= 4
            and parts[3]
        ):
            return parts[3]
    raise TrackerError(Reason.PARTIAL)


def _name(value: object) -> str:
    name = grammar.string(value, 2048)
    if not name.strip():
        raise TrackerError(Reason.UNREADABLE_OUTPUT)
    return name


def _title(name: str) -> str:
    return records.hosts_only(records.redact_secrets(name))[0]


def _date(
    label: model.DateLabel, value: object, *, calendar: bool = False, required: bool = False
) -> model.ItemDate | None:
    if value is None and not required:
        return None
    text = grammar.string(value, 35)
    if calendar:
        if date.fromisoformat(text).isoformat() != text:
            raise TrackerError(Reason.UNREADABLE_OUTPUT)
    elif not grammar.is_timestamp(text):
        raise TrackerError(Reason.UNREADABLE_OUTPUT)
    return model.ItemDate(label, text)


def _slug(kind: str, workspace: str, identity: str) -> str:
    digest = hashlib.sha256(f"{workspace}\0{identity}".encode()).hexdigest()[:32]
    return f"linear-{kind}-{digest}"


def _project(
    child: TrackerCLI, root: tuple[str, ...], workspace: str, selector: str
) -> dict[str, object]:
    row = _object(
        child.read_json((*root, "project", "view", selector, "--json", "--no-pager")),
        "id name url targetDate updatedAt completedAt",
    )
    _entity_slug(row["url"], workspace, "project")
    slug_id = row.get("slugId")
    if tracker_source.is_linear_id(selector):
        matches = selector == tracker_source.linear_id(row["id"])
    elif urlsplit(selector).netloc:
        slug = _entity_slug(selector, workspace, "project")
        matches = bool(slug_id) and slug_id in (slug, slug.rsplit("-", 1)[-1])
    else:
        matches = selector in (row["name"], slug_id)
    if not matches:
        raise TrackerError(Reason.PARTIAL)
    return row


def _milestone(
    child: TrackerCLI, root: tuple[str, ...], project_id: str, selector: str
) -> tuple[str, str, model.ItemDate | None]:
    result = child.read_json(
        (*root, "milestone", "list", "--project", project_id, "--limit", "all", "--json")
    )
    matches = []
    seen: set[str] = set()
    by_id = tracker_source.is_linear_id(selector)
    if not by_id:
        selector = grammar.folded(selector)
    for value in _rows(result):
        row = _object(value, "id name project targetDate")
        identity = tracker_source.linear_id(row["id"])
        parent = _object(row["project"], "id")
        if tracker_source.linear_id(parent["id"]) != project_id or identity in seen:
            raise TrackerError(Reason.PARTIAL)
        seen.add(identity)
        name = _name(row["name"])
        target = _date("Target", row["targetDate"], calendar=True)
        if selector == (identity if by_id else grammar.folded(name)):
            matches.append((identity, name, target))
    if len(matches) > 1:
        raise TrackerError(Reason.PARTIAL)
    if not matches:
        raise TrackerError(Reason.NOT_FOUND)
    return matches[0]


def _lane(
    value: object,
    source: tracker_source.LinearDeclaration,
    project_id: str,
    milestone_id: str | None,
    goal_id: str,
) -> model.Lane:
    row = _object(value, "id title url state project updatedAt")
    _entity_slug(row["url"], source.workspace, "issue")
    parent = row["project"]
    if parent is None or tracker_source.linear_id(_object(parent, "id")["id"]) != project_id:
        raise TrackerError(Reason.PARTIAL)
    if milestone_id is not None:
        member = row.get("projectMilestone")
        if member is None or tracker_source.linear_id(_object(member, "id")["id"]) != milestone_id:
            raise TrackerError(Reason.PARTIAL)
    identity = tracker_source.linear_id(row["id"])
    workflow = _object(row["state"], "name type")
    word = grammar.folded(grammar.string(workflow["name"], 128))
    group = grammar.string(workflow["type"], 64)
    return model.Lane(
        _slug("issue", source.workspace, identity),
        _title(_name(row["title"])),
        None,
        (goal_id,),
        model.Source("linear issue", "Linear issue", _WEB),
        date=_date("Updated", row["updatedAt"], required=True),
        state=source.words.get(word, _STATE_TYPES.get(group, markdown.STATUS_UNKNOWN)),
        additional_dates=tuple(
            stamp
            for stamp in (
                _date("Due", row.get("dueDate"), calendar=True),
                _date("Completed", row.get("completedAt")),
            )
            if stamp is not None
        ),
    )


def _ask_issue(value: object, lane: model.Lane, viewer: str) -> model.TrackerAskIssue:
    row = _object(value, "assignee labels state")
    assignee = row["assignee"]
    assigned_id = (
        tracker_source.linear_id(_object(assignee, "id")["id"]) if assignee is not None else None
    )
    label_rows = _rows(row["labels"])
    if len(label_rows) >= _LABEL_PAGE_SIZE:
        raise TrackerError(Reason.PARTIAL)
    labels = frozenset(_name(_object(label, "name")["name"]) for label in label_rows)
    state = grammar.string(_object(row["state"], "type")["type"], 64)
    if state not in _STATE_TYPES:
        raise TrackerError(Reason.PARTIAL)
    # An issue's provider workflow type determines whether it is open, even with a custom lane word.
    is_open = _STATE_TYPES[state] not in ("done", "dropped")
    return model.TrackerAskIssue(lane, is_open and assigned_id == viewer, labels)


def _ask_read(
    source: tracker_source.LinearDeclaration,
    child: TrackerCLI,
    rows: list[object],
    lanes: tuple[model.Lane, ...],
) -> model.TrackerAskRead | None:
    if not source.ask_labels:
        return None
    try:
        response = child.read_json(("--workspace", source.workspace, "api", LINEAR_VIEWER_QUERY))
        data = _object(_object(response, "data")["data"], "viewer")
        viewer = tracker_source.linear_id(_object(data["viewer"], "id")["id"])
        issues = tuple(_ask_issue(row, lane, viewer) for row, lane in zip(rows, lanes, strict=True))
    except (ValueError, TrackerError):
        # Issue membership already passed its own completeness checks.
        return None
    return model.TrackerAskRead(viewer, issues)


def _read(source: tracker_source.LinearDeclaration, child: TrackerCLI) -> model.TrackerData:
    root = ("--workspace", source.workspace, "--no-input")
    project = _project(child, root, source.workspace, source.project)
    project_id = tracker_source.linear_id(project["id"])
    name = _name(project["name"])
    target = _date("Target", project["targetDate"], calendar=True)
    updated = _date("Updated", project["updatedAt"], required=True)
    completed = _date("Completed", project["completedAt"])
    additional_dates = tuple(stamp for stamp in (updated, completed) if stamp is not None)
    milestone_id = None
    milestone_scope: tuple[str, ...] = ()
    if source.milestone is not None:
        milestone_id, name, target = _milestone(child, root, project_id, source.milestone)
        additional_dates = ()
        milestone_scope = ("--milestone", milestone_id)
    goal_id = _slug(source.kind, source.workspace, milestone_id or project_id)
    result = child.read_json(
        (
            *root,
            "issue",
            "query",
            "--project",
            project_id,
            *milestone_scope,
            "--all-teams",
            "--limit",
            "all",
            "--json",
            "--no-pager",
        )
    )
    rows = _rows(result)
    lanes = tuple(_lane(row, source, project_id, milestone_id, goal_id) for row in rows)
    slugs = tuple(lane.slug for lane in lanes)
    if len(set(slugs)) != len(slugs):
        raise TrackerError(Reason.PARTIAL)
    origin = model.Origin(
        model.Source(
            f"linear {source.kind}", tracker_source.LINEAR_SOURCE_LABELS[source.kind], _WEB
        ),
        date=target,
        additional_dates=additional_dates,
    )
    goal = model.Goal(goal_id, _title(name), None, origin, slugs)
    return model.TrackerData((goal,), lanes, ask_read=_ask_read(source, child, rows, lanes))


def read(source: tracker_source.Declaration, child: TrackerCLI) -> model.TrackerData:
    if not isinstance(source, tracker_source.LinearDeclaration):
        raise TrackerError(Reason.UNREADABLE_OUTPUT)
    try:
        return _read(source, child)
    except ValueError:
        raise TrackerError(Reason.UNREADABLE_OUTPUT) from None
