"""Read complete GitHub Plan collections through fixed, host-pinned gh queries."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from hashlib import sha256
from typing import TYPE_CHECKING, Literal

from . import grammar, model, tracker_source
from .markdown import STATUS_UNKNOWN
from .tracker_cli import GITHUB_API, GITHUB_GRAPHQL, Reason, TrackerError

if TYPE_CHECKING:
    from collections.abc import Callable

    from .tracker_cli import TrackerCLI

_HOST = "github.com"
_WEB = "https://github.com"
_MAX_ITEMS = 200
_PAGE_SIZE = 50
_MAX_PAGES = 8
_MAX_FIELDS = 100
_MAX_ASK_MEMBERS = 20
_MAX_GRAPHQL_INT = 2**31 - 1
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_LOGIN = re.compile(r"[A-Za-z0-9_-]{1,128}(?:\[bot\])?")
_CLOSED_STATES = {"COMPLETED": "done", "NOT_PLANNED": "dropped", "DUPLICATE": "dropped"}

_CONNECTION = "totalCount pageInfo { hasNextPage endCursor }"
_READ_ASKS = "$readAsks: Boolean!"
_VIEWER = "viewer @include(if: $readAsks) { login }"
_ISSUE = f"""
  id number title url state stateReason updatedAt
  labels(first: {_MAX_ASK_MEMBERS + 1}) @include(if: $readAsks) {{
    {_CONNECTION} nodes {{ name }}
  }}
  assignees(first: {_MAX_ASK_MEMBERS + 1}) @include(if: $readAsks) {{
    {_CONNECTION} nodes {{ login }}
  }}
"""

# The issue-list milestone filter uses search. The milestone connection gives its own
# issue-only count and cursors without conflating pull requests with issues.
MILESTONE_QUERY = f"""
query MilestoneIssues($id: ID!, $cursor: String, {_READ_ASKS}) {{
  {_VIEWER}
  node(id: $id) {{
    ... on Milestone {{
      id number url
      issues(first: {_PAGE_SIZE}, after: $cursor, states: [OPEN, CLOSED]) {{
        {_CONNECTION} nodes {{ {_ISSUE} }}
      }}
    }}
  }}
}}
"""

# gh issue view's nested subIssues has no pageInfo or child stateReason.
PARENT_QUERY = f"""
query SubIssues($owner: String!, $repo: String!, $number: Int!, $cursor: String, {_READ_ASKS}) {{
  {_VIEWER}
  repository(owner: $owner, name: $repo) {{
    issue(number: $number) {{
      id number title url
      subIssues(first: {_PAGE_SIZE}, after: $cursor) {{
        {_CONNECTION} nodes {{ {_ISSUE} }}
      }}
    }}
  }}
}}
"""

PROJECT_FIELDS_QUERY = f"""
query ProjectFields($owner: String!, $number: Int!) {{
  repositoryOwner(login: $owner) {{
    ... on ProjectV2Owner {{
      projectV2(number: $number) {{
        id number title url
        fields(first: {_MAX_FIELDS}) {{
          {_CONNECTION}
          nodes {{ type: __typename ... on ProjectV2FieldCommon {{ id name }} }}
        }}
      }}
    }}
  }}
}}
"""

# item-list flattens field names and omits the issue's state and close reason.
PROJECT_ITEMS_QUERY = f"""
query ProjectIssues($id: ID!, $status: String!, $cursor: String, {_READ_ASKS}) {{
  {_VIEWER}
  node(id: $id) {{
    ... on ProjectV2 {{
      id
      statusField: field(name: $status) {{ ... on ProjectV2SingleSelectField {{ id }} }}
      items(first: {_PAGE_SIZE}, after: $cursor, archivedStates: [ARCHIVED, NOT_ARCHIVED]) {{
        {_CONNECTION}
        nodes {{
          id
          content {{ __typename ... on Issue {{ {_ISSUE} }} }}
          status: fieldValueByName(name: $status) {{
            __typename
            ... on ProjectV2ItemFieldSingleSelectValue {{
              name
              field {{ ... on ProjectV2SingleSelectField {{ id }} }}
            }}
          }}
        }}
      }}
    }}
  }}
}}
"""

type Record = dict[str, object]
type PageReader = Callable[[str | None], tuple[str, Record]]


def _has_graphql_target_data(data: object) -> bool:
    # A failed lookup can still return the query's wrapper objects around a null target.
    # The top-level viewer can resolve independently of that target.
    remaining = (
        [value for key, value in data.items() if key != "viewer"]
        if isinstance(data, dict)
        else [data]
    )
    while remaining:
        value = remaining.pop()
        if isinstance(value, dict):
            remaining.extend(value.values())
        elif value is not None:
            return True
    return False


def _graphql(child: TrackerCLI, query: str, *variables: str, cursor: str | None = None) -> Record:
    args = ("api", GITHUB_GRAPHQL, "--hostname", _HOST, "-f", f"query={query}", *variables)
    if cursor is not None:
        # Raw fields carry opaque cursors without gh's typed-field or file expansion.
        args += ("-f", f"variables[cursor]={cursor}")
    envelope = grammar.dictionary(child.read_json(args))
    if "errors" in envelope:
        errors = envelope["errors"]
        if not isinstance(errors, list):
            raise grammar.SettingsError
        if errors:
            kinds = [grammar.dictionary(error).get("type") for error in errors]
            if _has_graphql_target_data(envelope.get("data")):
                raise TrackerError(Reason.PARTIAL)
            if all(kind in ("NOT_FOUND", "FORBIDDEN", "INSUFFICIENT_SCOPES") for kind in kinds):
                raise TrackerError(Reason.NOT_FOUND)
            if any(kind == "RATE_LIMITED" for kind in kinds):
                raise TrackerError(Reason.RATE_LIMITED)
            raise TrackerError(Reason.CLI_FAILED)
    return grammar.dictionary(envelope["data"])


def _lookup(record: Record, key: str) -> Record:
    value = record[key]
    if value is None:
        raise TrackerError(Reason.NOT_FOUND)
    return grammar.dictionary(value)


def _page(record: Record, *, limit: int, size: int) -> tuple[int, list[Record], str | None]:
    total = record["totalCount"]
    if type(total) is not int or total < 0:
        raise grammar.SettingsError
    if total > limit:
        raise TrackerError(Reason.LIMIT_EXCEEDED)
    values = record["nodes"]
    if not isinstance(values, list):
        raise grammar.SettingsError
    if len(values) > size:
        raise TrackerError(Reason.LIMIT_EXCEEDED)
    if any(item is None for item in values):
        raise TrackerError(Reason.PARTIAL)
    info = grammar.dictionary(record["pageInfo"])
    next_page = grammar.boolean(info["hasNextPage"])
    raw_cursor = info["endCursor"]
    cursor = None if raw_cursor is None else grammar.string(raw_cursor, 1024)
    if next_page and (not cursor or not values):
        raise TrackerError(Reason.PARTIAL)
    return total, [grammar.dictionary(item) for item in values], cursor if next_page else None


def _members(read_page: PageReader, identity: str) -> tuple[Record, ...]:
    total = None
    cursor = None
    cursors: set[str] = set()
    rows: dict[str, Record] = {}
    for _ in range(_MAX_PAGES):
        observed_id, connection = read_page(cursor)
        if observed_id != identity:
            raise TrackerError(Reason.PARTIAL)
        count, nodes, cursor = _page(connection, limit=_MAX_ITEMS, size=_PAGE_SIZE)
        if total is not None and count != total:
            raise TrackerError(Reason.PARTIAL)
        total = count
        for node in nodes:
            node_id = tracker_source.node_id(node["id"])
            if node_id in rows:
                raise TrackerError(Reason.PARTIAL)
            rows[node_id] = node
        if cursor is None and len(rows) == total:
            return tuple(rows.values())
        if cursor is None or cursor in cursors or len(rows) >= total:
            raise TrackerError(Reason.PARTIAL)
        cursors.add(cursor)
    raise TrackerError(Reason.LIMIT_EXCEEDED)


def _slug(kind: str, identity: str) -> str:
    # Node IDs can encode repository details and are not always slug-shaped.
    digest = sha256(identity.encode("ascii")).hexdigest()[:32]
    slug = f"github-{kind}-{digest}"
    if not grammar.is_safe_lane_id(slug):
        raise grammar.SettingsError
    return slug


def _title(raw: object) -> str:
    title = grammar.string(raw, 4096)
    if not title.strip():
        raise grammar.SettingsError
    return title


def _item_date(
    raw: object, label: Literal["Due", "Updated"], *, allow_day: bool = False
) -> model.ItemDate | None:
    if raw is None:
        return None
    value = grammar.string(raw, 35)
    if allow_day and _DAY.fullmatch(value):
        date.fromisoformat(value)
    elif not grammar.is_timestamp(value):
        raise grammar.SettingsError
    return model.ItemDate(label, value)


def _repo_url(raw: object, kind: str, number: int) -> str:
    url = grammar.string(raw, 240)
    prefix = f"{_WEB}/"
    suffix = f"/{kind}/{number}"
    if not url.startswith(prefix) or not url.endswith(suffix):
        raise grammar.SettingsError
    return tracker_source.repository(url[len(prefix) : -len(suffix)])


def _issue_status(issue: Record) -> tuple[str | None, str | None]:
    raw_state = issue.get("state")
    raw_reason = issue.get("stateReason")
    state = None if raw_state in (None, "") else grammar.string(raw_state, 64)
    reason = None if raw_reason in (None, "") else grammar.string(raw_reason, 64)
    if (state == "OPEN" and reason not in (None, "REOPENED")) or (
        state == "CLOSED" and reason == "REOPENED"
    ):
        return None, reason
    return state, reason


def _issue_state(issue: Record) -> str | None:
    state, reason = _issue_status(issue)
    if state is None:
        return None
    if state == "OPEN":
        return "not_started"
    if state == "CLOSED":
        return None if reason is None else _CLOSED_STATES.get(reason, STATUS_UNKNOWN)
    return STATUS_UNKNOWN


def _goal(kind: str, identity: str, title: object, due: model.ItemDate | None = None) -> model.Goal:
    source = model.Source(f"github {kind}", tracker_source.GITHUB_SOURCE_LABELS[kind], _WEB)
    return model.Goal(_slug(kind, identity), _title(title), None, model.Origin(source, date=due))


def _viewer(data: Record) -> str | None:
    viewer = data.get("viewer")
    login = viewer.get("login") if isinstance(viewer, dict) else None
    return login.lower() if isinstance(login, str) and _LOGIN.fullmatch(login) else None


def _ask_variables(source: tracker_source.GitHubDeclaration) -> tuple[str, str]:
    # GitHub rejects an omitted non-null variable even when the query declares a default.
    value = "true" if source.ask_labels else "false"
    return "-F", f"variables[readAsks]={value}"


def _ask_values(issue: Record, field: str, key: str) -> set[str]:
    total, nodes, cursor = _page(
        grammar.dictionary(issue[field]), limit=_MAX_ASK_MEMBERS, size=_MAX_ASK_MEMBERS
    )
    values = {grammar.string(node[key], 128) for node in nodes}
    if key == "login":
        if any(not _LOGIN.fullmatch(login) for login in values):
            raise grammar.SettingsError
        values = {login.lower() for login in values}
    if cursor is not None or total != len(nodes) or len(values) != total:
        raise TrackerError(Reason.PARTIAL)
    if key == "name" and any(not name.strip() for name in values):
        raise grammar.SettingsError
    return values


def _ask_read(
    lanes: dict[str, model.Lane],
    issues: list[tuple[Record, str | None]],
    labels: tuple[str, ...],
    viewers: set[str | None],
) -> model.TrackerAskRead | None:
    if not labels or len(viewers) != 1:
        return None
    login = next(iter(viewers))
    if login is None:
        return None
    observations = []
    try:
        for lane, (issue, _) in zip(lanes.values(), issues, strict=True):
            names = _ask_values(issue, "labels", "name")
            assignees = _ask_values(issue, "assignees", "login")
            state, _ = _issue_status(issue)
            if state not in ("OPEN", "CLOSED"):
                return None
            observations.append(
                model.TrackerAskIssue(
                    lane, state == "OPEN" and login in assignees, frozenset(names)
                )
            )
    except (KeyError, ValueError, TrackerError):
        return None
    return model.TrackerAskRead(login, tuple(observations))


def _rows(
    goal: model.Goal,
    issues: list[tuple[Record, str | None]],
    *,
    repo: str | None = None,
    ask_labels: tuple[str, ...],
    viewers: set[str | None],
) -> model.TrackerData:
    lanes: dict[str, model.Lane] = {}
    coordinates: set[tuple[str, int]] = set()
    project_status_lanes: set[str] = set()
    for issue, project_status in issues:
        number = grammar.integer(issue["number"], _MAX_GRAPHQL_INT)
        issue_repo = _repo_url(issue["url"], "issues", number)
        slug = _slug("issue", tracker_source.node_id(issue["id"]))
        coordinate = (issue_repo, number)
        if slug in lanes or coordinate in coordinates or (repo is not None and issue_repo != repo):
            raise TrackerError(Reason.PARTIAL)
        coordinates.add(coordinate)
        ordinary_state = _issue_state(issue)
        if project_status is not None:
            project_status_lanes.add(slug)
        lanes[slug] = model.Lane(
            slug,
            _title(issue["title"]),
            None,
            (goal.id,),
            goal.origin.source,
            date=_item_date(issue.get("updatedAt"), "Updated"),
            state=project_status if project_status is not None else ordinary_state,
        )
    return model.TrackerData(
        (replace(goal, lanes=tuple(lanes)),),
        tuple(lanes.values()),
        frozenset(project_status_lanes),
        _ask_read(lanes, issues, ask_labels, viewers),
    )


def _check_repository(
    record: Record, source: tracker_source.RepositoryDeclaration, url_kind: str, url_key: str
) -> None:
    number = grammar.integer(record["number"], _MAX_GRAPHQL_INT)
    if number != source.number or _repo_url(record[url_key], url_kind, number) != source.repo:
        raise grammar.SettingsError


def _milestone(
    source: tracker_source.RepositoryDeclaration, child: TrackerCLI
) -> model.TrackerData:
    info = grammar.dictionary(
        child.read_json(
            (
                "api",
                "--hostname",
                _HOST,
                "--method",
                "GET",
                f"{GITHUB_API}/repos/{source.repo}/milestones/{source.number}",
            )
        )
    )
    _check_repository(info, source, "milestone", "html_url")
    rest_id = tracker_source.node_id(info["node_id"])
    due = _item_date(info["due_on"], "Due", allow_day=True)
    viewers: set[str | None] = set()

    def get_milestone(node_id: str, cursor: str | None) -> Record:
        data = _graphql(
            child,
            MILESTONE_QUERY,
            "-f",
            f"variables[id]={node_id}",
            *_ask_variables(source),
            cursor=cursor,
        )
        viewers.add(_viewer(data))
        milestone = _lookup(data, "node")
        _check_repository(milestone, source, "milestone", "url")
        return milestone

    # A legacy REST node ID may resolve to a current GraphQL ID.
    first = get_milestone(rest_id, None)
    identity = tracker_source.node_id(first["id"])
    goal = _goal("milestone", identity, info["title"], due)

    def page(cursor: str | None) -> tuple[str, Record]:
        milestone = first if cursor is None else get_milestone(identity, cursor)
        return tracker_source.node_id(milestone["id"]), grammar.dictionary(milestone["issues"])

    return _rows(
        goal,
        [(issue, None) for issue in _members(page, identity)],
        repo=source.repo,
        ask_labels=source.ask_labels,
        viewers=viewers,
    )


def _parent(source: tracker_source.RepositoryDeclaration, child: TrackerCLI) -> model.TrackerData:
    owner, repo = source.repo.split("/")
    variables = (
        "-f",
        f"variables[owner]={owner}",
        "-f",
        f"variables[repo]={repo}",
        "-F",
        f"variables[number]={source.number}",
        *_ask_variables(source),
    )
    viewers: set[str | None] = set()

    def get_parent(cursor: str | None) -> Record:
        data = _graphql(child, PARENT_QUERY, *variables, cursor=cursor)
        viewers.add(_viewer(data))
        parent = _lookup(_lookup(data, "repository"), "issue")
        _check_repository(parent, source, "issues", "url")
        return parent

    first = get_parent(None)
    identity = tracker_source.node_id(first["id"])
    goal = _goal("parent-issue", identity, first["title"])

    def page(cursor: str | None) -> tuple[str, Record]:
        parent = first if cursor is None else get_parent(cursor)
        return tracker_source.node_id(parent["id"]), grammar.dictionary(parent["subIssues"])

    return _rows(
        goal,
        [(issue, None) for issue in _members(page, identity)],
        ask_labels=source.ask_labels,
        viewers=viewers,
    )


def _project_field(project: Record, wanted: str) -> str:
    total, fields, cursor = _page(
        grammar.dictionary(project["fields"]), limit=_MAX_FIELDS, size=_MAX_FIELDS
    )
    if cursor is not None or total != len(fields):
        raise TrackerError(Reason.PARTIAL)
    by_id: dict[str, tuple[str, str]] = {}
    for field in fields:
        identity = tracker_source.node_id(field["id"])
        if identity in by_id:
            raise TrackerError(Reason.PARTIAL)
        by_id[identity] = grammar.string(field["type"], 64), grammar.string(field["name"], 256)
    kind, name = by_id.get(wanted, ("", ""))
    if kind != "ProjectV2SingleSelectField":
        raise grammar.SettingsError
    if sum(grammar.folded(other) == grammar.folded(name) for _, other in by_id.values()) != 1:
        raise grammar.SettingsError
    return name


def _project_status(item: Record, source: tracker_source.ProjectDeclaration) -> str | None:
    raw = item["status"]
    if raw is None:
        return None
    value = grammar.dictionary(raw)
    if value["__typename"] != "ProjectV2ItemFieldSingleSelectValue":
        raise TrackerError(Reason.PARTIAL)
    field_id = tracker_source.node_id(grammar.dictionary(value["field"])["id"])
    if field_id != source.status_field:
        raise TrackerError(Reason.PARTIAL)
    name = value["name"]
    if name is None:
        return None
    word = grammar.folded(grammar.string(name, 256))
    return source.words.get(word, STATUS_UNKNOWN)


def _project(source: tracker_source.ProjectDeclaration, child: TrackerCLI) -> model.TrackerData:
    data = _graphql(
        child,
        PROJECT_FIELDS_QUERY,
        "-f",
        f"variables[owner]={source.owner}",
        "-F",
        f"variables[number]={source.number}",
    )
    project = _lookup(_lookup(data, "repositoryOwner"), "projectV2")
    number = grammar.integer(project["number"], _MAX_GRAPHQL_INT)
    url = grammar.string(project["url"], 240)
    if (
        not url.isascii()
        or number != source.number
        or url.lower()
        not in (
            f"{_WEB}/orgs/{source.owner}/projects/{number}",
            f"{_WEB}/users/{source.owner}/projects/{number}",
        )
    ):
        raise grammar.SettingsError
    identity = tracker_source.node_id(project["id"])
    goal = _goal("project", identity, project["title"])
    name = _project_field(project, source.status_field)
    viewers: set[str | None] = set()

    def page(cursor: str | None) -> tuple[str, Record]:
        response = _graphql(
            child,
            PROJECT_ITEMS_QUERY,
            "-f",
            f"variables[id]={identity}",
            "-f",
            f"variables[status]={name}",
            *_ask_variables(source),
            cursor=cursor,
        )
        viewers.add(_viewer(response))
        node = _lookup(response, "node")
        field = node["statusField"]
        if field is None or grammar.dictionary(field).get("id") != source.status_field:
            raise TrackerError(Reason.PARTIAL)
        return tracker_source.node_id(node["id"]), grammar.dictionary(node["items"])

    issues: list[tuple[Record, str | None]] = []
    for item in _members(page, identity):
        raw = item["content"]
        # A redacted item could be an issue and must count against membership coverage.
        if raw is None:
            raise TrackerError(Reason.PARTIAL)
        content = grammar.dictionary(raw)
        kind = content["__typename"]
        if kind == "Issue":
            issues.append((content, _project_status(item, source)))
        elif kind not in ("DraftIssue", "PullRequest"):
            raise grammar.SettingsError
    return _rows(goal, issues, ask_labels=source.ask_labels, viewers=viewers)


def read(source: tracker_source.Declaration, child: TrackerCLI) -> model.TrackerData:
    try:
        if isinstance(source, tracker_source.ProjectDeclaration):
            return _project(source, child)
        if not isinstance(source, tracker_source.RepositoryDeclaration):
            raise TrackerError(Reason.UNREADABLE_OUTPUT)
        if source.kind == "milestone":
            return _milestone(source, child)
        return _parent(source, child)
    except (KeyError, ValueError):
        raise TrackerError(Reason.UNREADABLE_OUTPUT) from None
