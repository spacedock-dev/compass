"""One durable stage-entry condition per exact workflow; baselines are ephemeral."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import uuid
from typing import TYPE_CHECKING, Any

from . import deliveries
from . import io as runtime_io

if TYPE_CHECKING:
    from collections.abc import Callable

    from .config import RuntimeConfig
    from .state import RuntimeState

LIMIT = 64
READ_CAP = 262_144
STAGE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
REVISION = re.compile(r"[0-9a-f]{32}\Z")
UNREADABLE = "Saved tripwires could not be read; no stage conditions are being checked."
AMBIGUOUS = (
    "Workflow choice is ambiguous; open one source session or give the workflows distinct names."
)


def store_path(config: RuntimeConfig) -> str:
    return os.path.join(config.state_home, "compass-tripwires.json")


def _stamp(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _text(value: Any, pattern: re.Pattern[str], cap: int) -> bool:
    return isinstance(value, str) and len(value) <= cap and pattern.fullmatch(value) is not None


def _rule(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "id",
        "workflow",
        "stage",
        "revision",
        "state",
        "saved_at",
        "trip",
    }:
        return False
    if not (
        _text(value["id"], DIGEST, 64)
        and _text(value["revision"], REVISION, 32)
        and _text(value["stage"], STAGE, 100)
        and _stamp(value["saved_at"])
    ):
        return False
    name = value["workflow"]
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 120
        or any(ord(c) < 32 or c in "/\\" for c in name)
    ):
        return False
    trip = value["trip"]
    if value["state"] == "armed":
        return trip is None
    if (
        value["state"] != "tripped"
        or not isinstance(trip, dict)
        or set(trip)
        != {
            "slug",
            "before",
            "stage",
            "before_observed_at",
            "observed_at",
            "source_written_at",
        }
    ):
        return False
    return (
        all(_text(trip[k], STAGE, 100) for k in ("slug", "before", "stage"))
        and trip["stage"] == value["stage"]
        and trip["before"] != trip["stage"]
        and all(_stamp(trip[k]) for k in ("before_observed_at", "observed_at", "source_written_at"))
        and trip["before_observed_at"] < trip["observed_at"]
    )


def load(config: RuntimeConfig) -> dict[str, dict[str, Any]] | None:
    try:
        with os.fdopen(
            runtime_io.open_regular(store_path(config), root=str(config.state_home)), "rb"
        ) as handle:
            raw = handle.read(READ_CAP + 1)
    except FileNotFoundError:
        return {}
    except OSError:
        return None
    try:
        data = json.loads(raw) if len(raw) <= READ_CAP else None
    except (ValueError, RecursionError):
        return None
    if (
        not isinstance(data, dict)
        or set(data) != {"v", "rules"}
        or type(data["v"]) is not int
        or data["v"] != 1
    ):
        return None
    rows = data["rules"]
    if not isinstance(rows, list) or len(rows) > LIMIT or not all(_rule(row) for row in rows):
        return None
    result = {row["id"]: row for row in rows}
    return result if len(result) == len(rows) else None


def save(config: RuntimeConfig, rules: dict[str, dict[str, Any]]) -> bool:
    try:
        raw = json.dumps({"v": 1, "rules": list(rules.values())}).encode()
        if (
            len(raw) > READ_CAP
            or len(rules) > LIMIT
            or not all(_rule(row) for row in rules.values())
        ):
            return False
        runtime_io.ensure_owner_dir(str(config.state_home), root=str(config.state_home))
        runtime_io.atomic_write_owner_only(
            store_path(config), raw, sync=True, root=str(config.state_home)
        )
    except (OSError, ValueError, TypeError, RecursionError):
        return False
    return True


def _baseline(source: dict[str, Any], revision: str, now: float) -> dict[str, Any]:
    return {
        "revision": revision,
        "at": now,
        "generation": source["generation"],
        "entities": {row["slug"]: row for row in source["entities"]},
    }


def _crossing(
    rule: dict[str, Any], source: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any] | None:
    for row in source["entities"]:
        before = previous["entities"].get(row["slug"])
        if (
            before
            and before["stage"] != row["stage"] == rule["stage"]
            and before["source_written_at"] < row["source_written_at"]
            and before["observed_at"] < row["observed_at"]
        ):
            return {
                "slug": row["slug"],
                "before": before["stage"],
                "stage": row["stage"],
                "before_observed_at": before["observed_at"],
                "observed_at": row["observed_at"],
                "source_written_at": row["source_written_at"],
            }
    return None


def _evaluate(
    config: RuntimeConfig,
    memory: dict[str, Any],
    rule: dict[str, Any],
    source: dict[str, Any] | None,
    now: float,
) -> tuple[str, dict[str, Any] | None]:
    key = rule["id"]
    previous = memory.setdefault("baselines", {}).get(key)
    if not config.spacedock_enabled:
        memory["baselines"].pop(key, None)
        return "Project reads are off (--no-spacedock); saved condition is suspended.", None
    if rule["state"] == "tripped":
        trip = rule["trip"]
        return f"Observed {trip['slug']} change from {trip['before']} to {trip['stage']}.", None
    if not source or not source["generation"] or rule["stage"] not in source["stages"]:
        memory["baselines"].pop(key, None)
        memory.setdefault("gaps", set()).add(key)
        return "Workflow stage source unavailable; saved condition is suspended.", None
    continuous = (
        previous is not None
        and previous["revision"] == rule["revision"]
        and previous["generation"] == source["generation"]
        and 0 <= now - previous["at"] <= 2 * config.reconcile_interval_sec
    )
    trip = _crossing(rule, source, previous) if continuous else None
    if trip:
        return "", trip
    memory["baselines"][key] = _baseline(source, rule["revision"], now)
    if not continuous and (previous or key in memory.setdefault("gaps", set())):
        memory["gaps"].discard(key)
        return "Observation resumed; baseline reset. Changes during the gap were not checked.", None
    why = f"Baseline recorded; watching for entry into {rule['stage']}."
    if not source["entities"]:
        why = "Saved; waiting for current entity state."
    elif any(row["stage"] == rule["stage"] for row in source["entities"]):
        why = f"Already at {rule['stage']}; entry was not observed."
    return why, None


def _notify(
    config: RuntimeConfig,
    rule: dict[str, Any],
    now: float,
    native: str,
    notifier: Callable[[str, str], str | None],
) -> None:
    trip = rule["trip"]
    outcome = deliveries.OUTCOME_NO_LANE
    if native:
        try:
            outcome = (
                notifier(
                    "Workflow stage condition",
                    f"{rule['workflow']}: observed {trip['slug']} "
                    f"change from {trip['before']} to {trip['stage']}.",
                )
                or ""
            )
        except Exception:  # noqa: BLE001 — a notifier cannot unspend the durable latch
            outcome = deliveries.OUTCOME_NOT_LAUNCHED
    if outcome in deliveries.OUTCOMES:
        deliveries.record(
            config,
            harness="spacedock",
            sid=rule["id"] + ":" + rule["revision"],
            lane="stage-tripwire",
            outcome=outcome,
            now=now,
        )


def _collect(
    config: RuntimeConfig,
    state: RuntimeState,
    sources: list[dict[str, Any]],
    now: float,
    native: str,
    notifier: Callable[[str, str], str | None],
    *,
    notify: bool = True,
) -> dict[str, Any]:
    memory = state.tripwire_memory
    by_id = {source["id"]: source for source in sources}
    memory["sources"] = by_id
    rules = load(config)
    if rules is None:
        memory["baselines"] = {}
        return {
            "enabled": True,
            "source_enabled": config.spacedock_enabled,
            "error": UNREADABLE,
            "sources": sources,
            "rules": [],
        }
    memory["baselines"] = {k: v for k, v in memory.get("baselines", {}).items() if k in rules}
    memory["gaps"] = memory.get("gaps", set()) & rules.keys()
    pending = memory["pending"] = {k: v for k, v in memory.get("pending", {}).items() if k in rules}
    rows = []
    for key in list(rules):
        rule = rules[key]
        source = by_id.get(key)
        why, trip = _evaluate(config, memory, rule, source, now)
        candidate = pending.get(key)
        if candidate and (candidate["revision"] != rule["revision"] or rule["state"] == "tripped"):
            pending.pop(key)
            candidate = None
        if trip and candidate is None and notify:
            candidate = {**rule, "state": "tripped", "trip": trip}
            pending[key] = candidate
        if candidate and notify:
            updated = {**rules, key: candidate}
            if save(config, updated):
                rules = updated
                rule = candidate
                pending.pop(key)
                _notify(config, rule, now, native, notifier)
                why, _ = _evaluate(config, memory, rule, source, now)
            else:
                why = "Could not save the trip; notification was not attempted."
        delivery = (
            deliveries.published(
                deliveries.load(config),
                "spacedock",
                key + ":" + rule["revision"],
                lane="stage-tripwire",
            )
            if rule["trip"]
            else {}
        )
        rows.append(
            {
                **rule,
                "why": why,
                "available": bool(
                    config.spacedock_enabled
                    and source
                    and source["generation"]
                    and rule["stage"] in source["stages"]
                ),
                "evaluated": source["evaluated"] if source else None,
                "partial": source["partial"] if source else True,
                "event_id": key + ":" + rule["revision"] if rule["trip"] else "",
                "delivery_why": delivery.get("delivery_why")
                or ("Notification attempt is unrecorded." if rule["trip"] else ""),
            }
        )
    return {
        "enabled": True,
        "source_enabled": config.spacedock_enabled,
        "error": "",
        "sources": sources,
        "rules": rows,
    }


def sources_from_sessions(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for session in sessions:
        for workflow in (session.get("spacedock") or {}).get("workflows", []):
            source = workflow.get("tripwire_source")
            if not source:
                continue
            source = found.setdefault(source["id"], {**source, "sessions": []})
            source["sessions"].append(
                {
                    "harness": session["harness"],
                    "sid": session["sid"],
                    "label": session.get("title") or session["sid"],
                }
            )
    signatures: dict[str, list[dict[str, Any]]] = {}
    for source in found.values():
        signature = json.dumps(
            [source["workflow"], source["goal"], sorted({s["label"] for s in source["sessions"]})]
        )
        signatures.setdefault(signature, []).append(source)
    for matches in signatures.values():
        for source in matches:
            source["ambiguous"] = len(matches) > 1
    return list(found.values())


def collect(
    config: RuntimeConfig,
    state: RuntimeState,
    sources: list[dict[str, Any]],
    now: float,
    native: str,
    notifier: Callable[[str, str], str | None],
    *,
    notify: bool = True,
) -> dict[str, Any]:
    if not config.tripwires_enabled:
        return {"enabled": False, "error": "", "sources": [], "rules": []}
    with state.tripwire_lock:
        return _collect(config, state, sources, now, native, notifier, notify=notify)


def _edit_refusal(
    config: RuntimeConfig,
    source: dict[str, Any] | None,
    old: dict[str, Any] | None,
    stage: str,
    action: str,
    count: int,
) -> str:
    if (
        not config.spacedock_enabled
        or not source
        or not source["generation"]
        or stage not in source["stages"]
    ):
        return "Workflow stage source unavailable."
    if source.get("ambiguous"):
        return AMBIGUOUS
    if old is None and count >= LIMIT:
        return "64 saved conditions; remove one before saving another."
    if action == "rearm" and (not old or old["stage"] != stage):
        return "Refresh the saved condition before Rearm."
    return ""


def _request_values(request: Any) -> bool:
    if not isinstance(request, dict) or set(request) != {
        "action",
        "id",
        "stage",
        "expected_revision",
    }:
        return False
    key, stage, action, expected = (
        request[k] for k in ("id", "stage", "action", "expected_revision")
    )
    return (
        _text(key, DIGEST, 64)
        and _text(stage, STAGE, 100)
        and isinstance(expected, str)
        and (expected == "" or _text(expected, REVISION, 32))
        and action in ("save", "remove", "rearm")
    )


def _mutate(config: RuntimeConfig, state: RuntimeState, request: Any, now: float) -> dict[str, Any]:
    if not _request_values(request):
        return {"ok": False, "error": "Invalid stage condition request.", "status": 400}
    key, stage, action, expected = (
        request[k] for k in ("id", "stage", "action", "expected_revision")
    )
    rules = load(config)
    if rules is None:
        return {"ok": False, "error": UNREADABLE, "status": 503}
    old = rules.get(key)
    if expected != (old["revision"] if old else ""):
        return {
            "ok": False,
            "error": "This condition changed; refresh before saving.",
            "status": 409,
        }
    if action == "save" and old and old["stage"] == stage:
        return {"ok": True, "error": "", "status": 200, "rule": copy.deepcopy(old)}
    return _store_edit(config, state, request, rules, now)


def _store_edit(
    config: RuntimeConfig,
    state: RuntimeState,
    request: dict[str, Any],
    rules: dict[str, dict[str, Any]],
    now: float,
) -> dict[str, Any]:
    key, stage, action = (request[k] for k in ("id", "stage", "action"))
    old = rules.get(key)
    memory = state.tripwire_memory
    source = memory.get("sources", {}).get(key)
    if action != "remove":
        error = _edit_refusal(config, source, old, stage, action, len(rules))
        if error:
            return {"ok": False, "error": error, "status": 409}
        rules[key] = {
            "id": key,
            "workflow": source["workflow"],
            "stage": stage,
            "revision": uuid.uuid4().hex,
            "state": "armed",
            "saved_at": now,
            "trip": None,
        }
    else:
        rules.pop(key, None)
    if not save(config, rules):
        return {"ok": False, "error": "Could not save the stage condition.", "status": 503}
    memory.setdefault("pending", {}).pop(key, None)
    memory.setdefault("baselines", {}).pop(key, None)
    if action != "remove":
        memory["baselines"][key] = _baseline(source, rules[key]["revision"], now)
    return {"ok": True, "error": "", "status": 200, "rule": copy.deepcopy(rules.get(key))}


def mutate(config: RuntimeConfig, state: RuntimeState, request: Any, now: float) -> dict[str, Any]:
    if not config.tripwires_enabled:
        return {"ok": False, "error": "Stage conditions are disabled.", "status": 503}
    with state.tripwire_lock:
        return _mutate(config, state, request, now)
