"""Local display metadata resolved against this board, never session source input.

Decisions: docs/design-declared-sessions.md. No row discovery or source access occurs here.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING, Any

from compass_runtime import events

if TYPE_CHECKING:
    from collections.abc import Mapping

    from compass_runtime.config import RuntimeConfig

Key = tuple[str, str]


def published() -> dict[str, Any]:
    return {
        "declared_parent": None,
        "declared_parent_state": None,
        "waiting_on_child": None,
        "group": None,
        "group_source": None,
    }


def model_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Display declarations cannot create an automatic reading or change its inputs."""
    native = dict(row)
    if native.get("waiting_on_child") is not None:
        native.update(state="idle", active=False, state_detail=None)
    for name in published():
        native.pop(name, None)
    return native


def _identity(key: Key) -> dict[str, str]:
    return {"harness": key[0], "sid": key[1]}


def _acyclic(parents: dict[Key, Key]) -> dict[Key, Key]:
    done: set[Key] = set()
    cycles: set[Key] = set()
    for start in parents:
        path: dict[Key, int] = {}
        current = start
        while current in parents and current not in done:
            if current in path:
                cycles.update(list(path)[path[current] :])
                break
            path[current] = len(path)
            current = parents[current]
        done.update(path)
    return {child: parent for child, parent in parents.items() if child not in cycles}


def _activity(row: Mapping[str, Any]) -> float:
    return max(float(row.get("own_activity") or 0.0), float(row.get("last_activity") or 0.0))


def _deadline(row: Mapping[str, Any], config: RuntimeConfig) -> float:
    if row.get("state") != "working" or row.get("ended_at") or row.get("finished_at"):
        return 0.0
    ceiling = {
        "claude": config.claude_tool_in_flight_max_sec,
        "codex": config.codex_tool_in_flight_max_sec,
    }.get(
        str(row["harness"]),
        min(config.claude_tool_in_flight_max_sec, config.codex_tool_in_flight_max_sec),
    )
    return _activity(row) + ceiling


def attach(
    rows: list[dict[str, Any]],
    declarations: Mapping[Key, dict[str, str]],
    *,
    config: RuntimeConfig,
    now: float,
) -> None:
    by_key = {(str(row["harness"]), str(row["sid"])): row for row in rows}
    parents: dict[Key, Key] = {}
    for key, row in by_key.items():
        own_group = row.get("group") if row.get("group_source") == "set" else None
        row.update(published())
        if own_group:
            row.update(group=own_group, group_source="set")
        claim = declarations.get(key)
        if claim is None:
            continue
        row["declared_parent_state"] = "not_linked"
        harness, sid = claim["harness"], claim["sid"]
        normalized = events.normalize_session_id(harness, sid)
        parent = (harness, normalized or sid)
        if normalized is not None and parent in by_key and parent != key:
            parents[key] = parent
    parents = _acyclic(parents)
    children: dict[Key, list[Key]] = defaultdict(list)
    for child, parent in parents.items():
        by_key[child].update(declared_parent=_identity(parent), declared_parent_state="linked")
        children[parent].append(child)
    # Leaves first avoids recursive walks on a hostile chain at the session cap.
    pending = {key: len(children[key]) for key in by_key}
    ready = deque(key for key in by_key if pending[key] == 0)
    order: list[Key] = []
    deadlines = {key: _deadline(row, config) for key, row in by_key.items()}
    while ready:
        key = ready.popleft()
        order.append(key)
        row = by_key[key]
        eligible = [
            child
            for child in children[key]
            if deadlines[child] > now and not by_key[child].get("finished_at")
        ]
        if eligible and row["state"] == "idle" and not row.get("ended_at"):
            child = min(eligible, key=lambda c: (-_activity(by_key[c]), c))
            row.update(
                state="working",
                active=True,
                waiting_on_child=_identity(child),
                state_detail=f"waiting on {child[0]}:{child[1]}",
            )
            deadlines[key] = max(deadlines[c] for c in eligible)
        ancestor = parents.get(key)
        if ancestor is not None:
            pending[ancestor] -= 1
            if pending[ancestor] == 0:
                ready.append(ancestor)
    _inherit_groups(by_key, parents, order)


def _inherit_groups(
    by_key: dict[Key, dict[str, Any]], parents: dict[Key, Key], order: list[Key]
) -> None:
    for key in reversed(order):
        ancestor = parents.get(key)
        row = by_key[key]
        if ancestor is not None and not row["group"] and by_key[ancestor]["group"]:
            row.update(group=by_key[ancestor]["group"], group_source="parent")
