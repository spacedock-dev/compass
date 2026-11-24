"""Restart-safe, bounded semantic work history for the project cockpit."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
from typing import TYPE_CHECKING, Any

from . import io as runtime_io
from . import records

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .config import RuntimeConfig
    from .state import RuntimeState

SCHEMA_VERSION = 1
MAX_PROJECTS = 20
MAX_EVENTS_PER_PROJECT = 512
HISTORY_WINDOW_SEC = 24 * 60 * 60
STORE_NAME = "semantic-work-history.json"
# Named, unlike the other bounds in this module, because SECURITY.md quotes
# these two numbers: this store carries the operator's own directive and the
# assistant's answer, so widening either bound widens what a credential could
# survive inside. A literal here and a number in the document can only agree by
# accident, and `SemanticHistoryContractDocumentationTest` is what compares them.
SUMMARY_CAP_CHARS = 240
RESULT_DETAIL_CAP_CHARS = 4096
RESCAN_OVERLAP_BYTES = 64 * 1024
BACKFILL_SCHEMA_VERSION = 6

_RESULT_ALIAS_RE = re.compile(r"\[([a-z0-9][a-z0-9_-]{2,31})\]\([^)]+\)", re.IGNORECASE)
_RESULT_TITLE_RE = re.compile(r"(?m)^- Title:\s*(\S.*)$")
_AUTHORIZATION_REQUIRED_RE = re.compile(
    r"\b(?:separate|explicit) authorization is required\b[^.\n]*(?:push|create)[^.\n]*\bPR\b",
    re.IGNORECASE,
)
_AUTHORIZATION_QUESTION_RE = re.compile(
    r"(?im)^(?:approve|authorize)[^?\n]*\bpush(?:ing)?\b[^?\n]*\bPR\b\?\s*$"
)

_FACT_EVENT_TYPES = {
    "user_message": "operator_direction",
    "observer_snapshot": "observed_goal",
    "prepared_dispatch": "assignment",
    "stage_transition": "stage_transition",
    "work_birth": "assignment",
    "work_result": "progress_head",
    "gate_decision": "gate_decision",
    "decision": "gate_decision",
    "result": "result",
}


_LINEAGE = re.compile(r"[0-9a-f]{32}")
# One past the largest integer a JSON reader in any client holds exactly.
GENERATION_LIMIT = 2**53


def _lineage_of(bucket: Any) -> tuple[str, int] | None:
    """A bucket's lineage and generation, or None when either is absent or malformed."""
    if not isinstance(bucket, dict):
        return None
    lineage, generation = bucket.get("lineage"), bucket.get("generation")
    if (
        isinstance(lineage, str)
        and _LINEAGE.fullmatch(lineage)
        and type(generation) is int
        and 1 <= generation < GENERATION_LIMIT
    ):
        return lineage, generation
    return None


# How a stored check tells "the history it measured against was pruned" from "it was lost":
# [the record of what a check read](docs/design-reading-a-session.md#amended-2026-11-24-a-stored-check-keeps-the-record-of-what-it-read)  # noqa: E501
def _next_lineage(prior: Any) -> dict[str, Any]:
    """The prior bucket's lineage one generation on, or a new lineage at its first generation.

    A prune keeps the bucket and so its lineage; a deletion, an emptied or corrupt file, an eviction
    or a bucket an older build rewrote without these keys starts a new one.
    """
    held = _lineage_of(prior)
    if held is None or held[1] + 1 >= GENERATION_LIMIT:
        return {"lineage": secrets.token_hex(16), "generation": 1}
    return {"lineage": held[0], "generation": held[1] + 1}


def mark_of(payload: Mapping[str, Any], project: str) -> dict[str, Any] | None:
    """The `{key, lineage, generation}` of one project's bucket in a payload, or None."""
    projects = payload.get("projects")
    held = _lineage_of(projects.get(project) if isinstance(projects, dict) else None)
    return {"key": project, "lineage": held[0], "generation": held[1]} if held else None


def mark_for(config: RuntimeConfig, state: RuntimeState, project: str) -> dict[str, Any] | None:
    """One project's bucket mark as the file holds it now, or None when it holds none.

    Memoised on the file's identity, size and modification time, so a caller that asks per request
    parses the file only after a write. A file that cannot be stated has no mark.
    """
    path = store_path(config)
    with state.semantic_history_lock:
        try:
            info = os.stat(path)
        except OSError:
            return None
        stamp = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        memo = state.semantic_history_marks
        if memo.get("stamp") != stamp:
            memo.clear()
            memo["stamp"] = stamp
            memo["payload"] = _read(config)
        payload = memo["payload"]
    return mark_of(payload, project)


def workflow_work_item_id(workflow: str, entity: str) -> str:
    """Return the durable task identity shared by assignments and projections."""
    workflow_digest = hashlib.blake2b(workflow.encode(), digest_size=10).hexdigest()
    return f"workflow:{workflow_digest}:{entity}"


def store_path(config: RuntimeConfig) -> str:
    return os.path.join(config.state_home, STORE_NAME)


def _redact_history(value: Any) -> Any:
    # Nested facts are republished after restart, including records from older writers.
    if isinstance(value, str):
        return records.redact_secrets(value)
    if isinstance(value, list):
        return [_redact_history(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_history(item) for key, item in value.items()}
    return value


def _read(config: RuntimeConfig) -> dict[str, Any]:
    try:
        with os.fdopen(
            runtime_io.open_regular(store_path(config), root=str(config.state_home)), "rb"
        ) as handle:
            raw = handle.read(config.state_read_cap_bytes + 1)
        if len(raw) > config.state_read_cap_bytes:
            return {"v": SCHEMA_VERSION, "projects": {}}
        value = json.loads(raw)
    except (OSError, ValueError, RecursionError):
        return {"v": SCHEMA_VERSION, "projects": {}}
    if not isinstance(value, dict) or not isinstance(value.get("projects"), dict):
        return {"v": SCHEMA_VERSION, "projects": {}}
    redacted = dict(_redact_history(value))
    # A read may be the only event after an upgrade; do not leave recognized
    # credentials at rest until an unrelated history update happens to arrive.
    if redacted != value and not _write(config, redacted):
        logging.getLogger(__name__).warning(
            "Could not persist semantic-history redaction; will retry on the next read"
        )
    return redacted


def read(config: RuntimeConfig, state: RuntimeState, project: str) -> dict[str, Any]:
    """Read one project's evidence, repairing legacy credential redaction on disk."""
    with state.semantic_history_lock:
        payload = _read(config)
    row = payload.get("projects", {}).get(project)
    if not isinstance(row, dict):
        return {
            "events": [],
            "cursors": {},
            "persisted": False,
            "window_sec": HISTORY_WINDOW_SEC,
        }
    events = row.get("events")
    cursors = row.get("cursors")
    return {
        **row,
        "events": events if isinstance(events, list) else [],
        "cursors": cursors if isinstance(cursors, dict) else {},
        "persisted": True,
        "window_sec": row.get("window_sec", HISTORY_WINDOW_SEC),
    }


def reconcile_project(
    config: RuntimeConfig, state: RuntimeState, project: str, aliases: Iterable[str]
) -> None:
    """Join verified display-label buckets into their one canonical project key."""
    aliases = tuple(aliases)
    if not aliases:
        return
    with state.semantic_history_lock:
        payload = _read(config)
        projects = payload["projects"]
        prior = projects.get(project, {})
        existing = prior.get("events", []) if isinstance(prior, dict) else []
        changed = False
        for alias in aliases:
            legacy = projects.pop(alias, None) if alias != project else None
            if isinstance(legacy, dict):
                existing = _merge(existing, legacy.get("events", []))
                changed = True
        if changed:
            # Merged coverage was not measured under this key. Earn it again.
            projects[project] = {
                "events": existing,
                "cursors": {},
                "source_scans": {},
                **_next_lineage(prior),
            }
            _write(config, payload)


def _write(config: RuntimeConfig, payload: dict[str, Any]) -> bool:
    target = store_path(config)
    try:
        runtime_io.atomic_write_owner_only(
            target, json.dumps(payload, separators=(",", ":")), root=str(config.state_home)
        )
    except (OSError, ValueError):
        return False
    return True


def backfill_scan_bytes(
    config: RuntimeConfig,
    state: RuntimeState,
    project: str,
    source_identity: str,
    signature: Mapping[str, Any],
    *,
    full_max_bytes: int,
) -> int:
    """Return a bounded cold/resume scan size for one authoritative source."""
    return backfill_plan(
        config, state, project, source_identity, signature, full_max_bytes=full_max_bytes
    )[0]


def backfill_plan(
    config: RuntimeConfig,
    state: RuntimeState,
    project: str,
    source_identity: str,
    signature: Mapping[str, Any],
    *,
    full_max_bytes: int,
) -> tuple[int, str | None]:
    """The allowance and retained coverage an incremental read must preserve."""
    with state.semantic_history_lock:
        payload = _read(config)
    project_row = payload.get("projects", {}).get(project, {})
    scans = project_row.get("source_scans", {}) if isinstance(project_row, dict) else {}
    prior = scans.get(source_identity) if isinstance(scans, dict) else None
    retained = project_row.get("events", []) if isinstance(project_row, dict) else []
    if not (
        isinstance(prior, dict)
        and prior.get("schema") == BACKFILL_SCHEMA_VERSION
        and prior.get("coverage") == _coverage(retained, source_identity)
    ):
        prior = None
    size = int(signature.get("size") or 0)
    mtime_ns = int(signature.get("mtime_ns") or 0)
    if (
        isinstance(prior, dict)
        and int(prior.get("schema") or 0) == BACKFILL_SCHEMA_VERSION
        and int(prior.get("size") or 0) == size
        and int(prior.get("mtime_ns") or 0) == mtime_ns
    ):
        return 0, str(prior["coverage"])
    prior_size = int(prior.get("size") or 0) if isinstance(prior, dict) else 0
    if prior is not None and prior_size and size >= prior_size:
        return min(full_max_bytes, size - prior_size + RESCAN_OVERLAP_BYTES), str(prior["coverage"])
    return min(full_max_bytes, size), None


def _coverage(events: Iterable[Mapping[str, Any]], source: str) -> str:
    ids = sorted(
        {
            str(row["event_id"])
            for row in events
            if row.get("source_identity") == source and row.get("event_id")
        }
    )
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()


def _retained_scans(
    prior: Mapping[str, Any],
    scanned: Mapping[str, Mapping[str, Any]] | None,
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    retained: list[dict[str, Any]],
) -> dict[str, Any]:
    scans = dict(prior.get("source_scans") or {})
    for source, signature in (scanned or {}).items():
        expected = signature.get("prior_coverage")
        if expected is not None and expected != _coverage(existing, source):
            scans.pop(source, None)
            continue
        scans[source] = {
            "schema": BACKFILL_SCHEMA_VERSION,
            "size": int(signature.get("size") or 0),
            "mtime_ns": int(signature.get("mtime_ns") or 0),
            "coverage": _coverage([*existing, *incoming], source),
        }
    # A file stamp says what was read, not what survived the store's age and
    # project caps. Losing any covered event must earn a fresh bounded scan.
    return {
        source: scan
        for source, scan in scans.items()
        if isinstance(scan, dict)
        and scan.get("schema") == BACKFILL_SCHEMA_VERSION
        and scan.get("coverage") == _coverage(retained, source)
    }


def _source_identity(fact: Mapping[str, Any]) -> str:
    source_session = fact.get("source_session")
    if isinstance(source_session, dict):
        harness = records.safe_text(source_session.get("harness"), 32)
        sid = records.safe_text(source_session.get("sid"), 128)
        if harness and sid:
            return f"{harness}:{sid}"
    branch = fact.get("branch")
    if isinstance(branch, dict):
        harness = records.safe_text(branch.get("harness"), 32)
        sid = records.safe_text(branch.get("sid"), 128)
        if harness and sid:
            return f"{harness}:{sid}"
    evidence = fact.get("evidence")
    source = evidence.get("source") if isinstance(evidence, dict) else ""
    return records.safe_text(source, 160) or "source unavailable"


# Every Pi check fact's source begins with this, and so did the older writer's
# validation fact (DRC-4690).
PI_CHECK_SOURCE_PREFIX = "Pi bash tool call"


def is_check_fact(fact: Mapping[str, Any]) -> bool:
    """A check's result, which this store never keeps
    ([DEC-23](docs/design-reading-a-session.md#dec-23-a-claude-code-sessions-record-of-its-checks-may-show-the-work)
    item 6). The allowlist below drops `subject` and `result`, so a check read
    back from here would be a bare "5 validation checks passed" that no later
    run could supersede and no later change could age."""
    if fact.get("subject") == "check":
        return True
    evidence = fact.get("evidence")
    source = evidence.get("source") if isinstance(evidence, dict) else ""
    return fact.get("type") == "result" and str(source or "").startswith(PI_CHECK_SOURCE_PREFIX)


def _event_from_fact(
    fact: Mapping[str, Any],
    work_items: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    fact_type = str(fact.get("type") or "")
    source_kind = str(fact.get("source_kind") or "")
    event_type = "checkpoint" if source_kind == "checkpoint" else _FACT_EVENT_TYPES.get(fact_type)
    if event_type is None or is_check_fact(fact):
        return None
    fact_id = records.safe_text(fact.get("fact_id"), 160)
    summary = records.safe_text(fact.get("summary"), SUMMARY_CAP_CHARS)
    at = fact.get("at")
    if not fact_id or not summary or not isinstance(at, (int, float)):
        return None
    work_item_id = records.safe_text(fact.get("work_item_id"), 160)
    item = work_items.get(work_item_id, {}) if work_item_id else {}
    branch = fact.get("branch")
    evidence = fact.get("evidence")
    normalized_fact = {
        key: value
        for key, value in fact.items()
        if key
        in {
            "fact_id",
            "at",
            "type",
            "source_kind",
            "summary",
            "scope",
            "actor_claim",
            "work_item_id",
            "stage",
            "decision",
            "by",
            "application_state",
            "target_stage",
            "intent_promoted",
            "assignment",
            "worker_kind",
            "batch_id",
            "workflow_binding",
            "workflow_entity",
            "source_session",
            "parent_session",
            "contributor",
        }
    }
    if isinstance(branch, dict):
        normalized_fact["branch"] = dict(branch)
    if isinstance(evidence, dict):
        normalized_fact["evidence"] = dict(evidence)
    return {
        "event_id": fact_id,
        "event_type": event_type,
        "at": float(at),
        "source_identity": _source_identity(fact),
        "source_ref": fact_id,
        "work_binding": work_item_id or None,
        "summary": summary,
        "fact": normalized_fact,
        "work_item": dict(item) if item else None,
    }


def _final_output_events(sessions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for session in sessions:
        output = session.get("last_output")
        if session.get("state") == "working" or not isinstance(output, str) or not output.strip():
            continue
        harness = records.safe_text(session.get("harness"), 32)
        sid = records.safe_text(session.get("sid"), 128)
        at = session.get("last_activity")
        if not harness or not sid or not isinstance(at, (int, float)):
            continue
        exact = "\n".join(
            records.safe_text(line, RESULT_DETAIL_CAP_CHARS) for line in output.splitlines()
        )[:RESULT_DETAIL_CAP_CHARS]
        summary = records.safe_text(" ".join(exact.split()), 112)
        event_id = f"final:{harness}:{sid}:{float(at):.6f}"
        work_item_id = f"session:{harness}:{sid}"
        fact = {
            "fact_id": event_id,
            "at": float(at),
            "type": "result",
            "summary": summary,
            "scope": "session",
            "actor_claim": "assistant final-answer record",
            "work_item_id": work_item_id,
            "evidence": {
                "source": "assistant final_answer followed by terminal turn state",
                "confidence": "exact",
            },
            "detail": exact,
            "source_session": {"harness": harness, "sid": sid},
        }
        required = _AUTHORIZATION_REQUIRED_RE.search(exact)
        question = _AUTHORIZATION_QUESTION_RE.search(exact)
        if required and question:
            fact["authorization_request"] = {
                "kind": "push_pr",
                "question": records.safe_text(question.group(0), 240),
                "status": "open",
            }
        found.append(
            {
                "event_id": event_id,
                "event_type": "final_output",
                "at": float(at),
                "source_identity": f"{harness}:{sid}",
                "source_ref": event_id,
                "work_binding": work_item_id,
                "summary": summary,
                "fact": fact,
                "work_item": {
                    "work_item_id": work_item_id,
                    "label": records.safe_text(session.get("title"), 112) or "Last output",
                    "kind": "session_result",
                    "source_bindings": [
                        {"source": "session identity", "value": f"{harness}:{sid}"}
                    ],
                    "contributor_refs": [],
                },
            }
        )
    return found


def _bind_final_output_events(events: list[dict[str, Any]]) -> None:
    workflow_events = [
        event
        for event in events
        if isinstance(event, dict) and str(event.get("work_binding") or "").startswith("workflow:")
    ]
    for event in events:
        if event.get("event_type") != "final_output":
            continue
        fact = event.get("fact")
        if not isinstance(fact, dict):
            continue
        detail = str(fact.get("detail") or "")
        title_match = _RESULT_TITLE_RE.search(detail)
        aliases = {match.casefold() for match in _RESULT_ALIAS_RE.findall(detail)}
        if title_match is None or not aliases:
            continue
        title = title_match.group(1).strip()
        source_identity = str(event.get("source_identity") or "")
        candidates: dict[str, dict[str, Any]] = {}
        for candidate in workflow_events:
            binding = str(candidate.get("work_binding") or "")
            item = candidate.get("work_item")
            candidate_fact = candidate.get("fact")
            if not isinstance(item, dict) or str(item.get("label") or "") != title:
                continue
            has_assignment = any(
                row.get("event_type") == "assignment"
                and row.get("work_binding") == binding
                and row.get("source_identity") == source_identity
                for row in workflow_events
            )
            entities = {
                str(row.get("fact", {}).get("workflow_entity") or "").casefold()
                for row in workflow_events
                if row.get("work_binding") == binding and isinstance(row.get("fact"), dict)
            }
            if (
                has_assignment
                and any(entity.startswith(alias) for entity in entities for alias in aliases)
            ) or (
                isinstance(candidate_fact, dict)
                and candidate.get("source_identity") == source_identity
                and str(candidate_fact.get("workflow_entity") or "").casefold() in aliases
            ):
                candidates[binding] = item
        if len(candidates) != 1:
            continue
        binding, item = next(iter(candidates.items()))
        fact["work_item_id"] = binding
        fact["result_binding"] = {
            "confidence": "exact",
            "source": "unique workflow entity alias, exact task title, and session assignment",
        }
        event["work_binding"] = binding
        event["work_item"] = dict(item)


def _assignment_events(
    assignments: Iterable[Mapping[str, Any]], *, observed_at: float
) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for assignment in assignments:
        summary = records.safe_text(assignment.get("assignment"), 240)
        if assignment.get("confidence") != "exact" or not summary:
            continue
        observer_sid = records.safe_text(assignment.get("observer_sid"), 128)
        worker = records.safe_text(assignment.get("name"), 70) or "subagent"
        entity = records.safe_text(assignment.get("workflow_entity"), 112)
        stage = records.safe_text(assignment.get("workflow_stage"), 70)
        workflow = records.safe_text(assignment.get("workflow_binding"), 1024)
        identity = f"{observer_sid}\0{worker}\0{workflow}\0{entity}\0{stage}\0{summary}"
        digest = hashlib.blake2b(identity.encode(), digest_size=12).hexdigest()
        event_id = f"assignment:{digest}"
        work_item_id = (
            workflow_work_item_id(workflow, entity)
            if entity and workflow
            else (f"workflow-unbound:{entity}" if entity else f"assignment:{digest}")
        )
        fact: dict[str, Any] = {
            "fact_id": event_id,
            "at": observed_at,
            "type": "stage_transition" if stage else "assignment",
            "source_kind": "child_assignment",
            "summary": summary,
            "scope": "session",
            "actor_claim": "current structured child assignment",
            "work_item_id": work_item_id,
            "assignment": summary,
            "evidence": {
                "source": records.safe_text(assignment.get("source"), 160),
                "confidence": "exact",
            },
        }
        if observer_sid:
            fact["source_session"] = {"harness": "codex", "sid": observer_sid}
            fact["contributor"] = {
                "harness": "codex",
                "sid": observer_sid,
                "label": worker,
                "verified": True,
            }
        parent_session = assignment.get("parent_session")
        if isinstance(parent_session, dict):
            parent_harness = records.safe_text(parent_session.get("harness"), 32)
            parent_sid = records.safe_text(parent_session.get("sid"), 128)
            if parent_harness and parent_sid:
                fact["parent_session"] = {"harness": parent_harness, "sid": parent_sid}
        if stage:
            fact["stage"] = stage
        if workflow:
            fact["workflow_binding"] = workflow
            fact["workflow_entity"] = entity
        source_identity = f"codex:{observer_sid}" if observer_sid else f"worker:{worker}"
        found.append(
            {
                "event_id": event_id,
                "event_type": "stage_transition" if stage else "assignment",
                "at": observed_at,
                "source_identity": source_identity,
                "source_ref": event_id,
                "work_binding": work_item_id,
                "summary": summary,
                "fact": fact,
                "work_item": {
                    "work_item_id": work_item_id,
                    "label": entity.replace("-", " ").capitalize() if entity else summary,
                    "kind": "workflow_item" if entity else "one_off",
                    "source_bindings": [
                        {
                            "source": "structured child assignment",
                            "value": (
                                f"{workflow}:{entity}" if workflow and entity else entity or summary
                            ),
                        }
                    ],
                    "contributor_refs": [],
                },
            }
        )
    return found


def _merge(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {
        str(event.get("event_id")): event
        for event in existing
        if isinstance(event, dict) and event.get("event_id")
    }
    for event in sorted(incoming, key=lambda row: float(row.get("at") or 0)):
        merged_event = dict(event)
        event_type = merged_event["event_type"]
        source_identity = merged_event["source_identity"]
        work_binding = merged_event.get("work_binding")
        if event_type == "progress_head" and work_binding:
            by_id = {
                key: prior
                for key, prior in by_id.items()
                if not (
                    prior.get("event_type") == "progress_head"
                    and prior.get("work_binding") == work_binding
                )
            }
        if event_type == "assignment" and work_binding:
            fact = merged_event.get("fact")
            entity = fact.get("workflow_entity") if isinstance(fact, dict) else None
            if entity and str(work_binding).startswith("workflow:"):
                legacy_binding = f"workflow:{entity}"
                by_id = {
                    key: prior
                    for key, prior in by_id.items()
                    if not (
                        prior.get("event_type") == "assignment"
                        and prior.get("source_identity") == source_identity
                        and prior.get("work_binding") == legacy_binding
                    )
                }
        if event_type == "observed_goal":
            same_source = [
                prior
                for prior in by_id.values()
                if prior.get("event_type") in {"observed_goal", "goal_shift"}
                and prior.get("source_identity") == source_identity
            ]
            newest = max(same_source, key=lambda row: float(row.get("at") or 0), default=None)
            if newest and newest.get("summary") == event.get("summary"):
                by_id.pop(str(newest.get("event_id")), None)
            elif newest:
                merged_event["event_type"] = "goal_shift"
        by_id[merged_event["event_id"]] = merged_event
    return sorted(by_id.values(), key=lambda row: float(row.get("at") or 0), reverse=True)[
        :MAX_EVENTS_PER_PROJECT
    ]


def _attach_relations(events: list[dict[str, Any]], relations: object) -> list[dict[str, Any]]:
    if not isinstance(relations, list):
        return events
    by_source: dict[str, list[dict[str, Any]]] = {}
    for relation in relations:
        if not isinstance(relation, dict):
            continue
        source = records.safe_text(relation.get("from"), 160)
        target = records.safe_text(relation.get("to"), 160)
        relation_type = records.safe_text(relation.get("type"), 64)
        if not source or not target or not relation_type:
            continue
        evidence_ref = records.safe_text(relation.get("evidence_ref"), 160)
        normalized = {
            "from": source,
            "to": target,
            "type": relation_type,
            "confidence": records.safe_text(relation.get("confidence"), 64),
            "provenance": records.safe_text(relation.get("provenance"), 240),
        }
        if evidence_ref:
            normalized["evidence_ref"] = evidence_ref
        by_source.setdefault(evidence_ref or source, []).append(normalized)
    for event in events:
        supported = by_source.get(str(event.get("source_ref") or ""))
        if supported:
            event["relations"] = supported
    return events


def update(
    config: RuntimeConfig,
    state: RuntimeState,
    project: str,
    semantic: Mapping[str, Any],
    sessions: Iterable[Mapping[str, Any]],
    assignments: Iterable[Mapping[str, Any]] = (),
    *,
    now: float | None = None,
    source_scans: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge current source-backed meaning into the durable bounded history."""
    facts = semantic.get("facts")
    work_rows = semantic.get("work_items")
    work_items = (
        {
            str(row.get("work_item_id")): row
            for row in work_rows
            if isinstance(row, dict) and row.get("work_item_id")
        }
        if isinstance(work_rows, list)
        else {}
    )
    incoming = (
        [
            event
            for event in (
                _event_from_fact(fact, work_items) for fact in facts if isinstance(fact, dict)
            )
            if event is not None
        ]
        if isinstance(facts, list)
        else []
    )
    _attach_relations(incoming, semantic.get("relations"))
    incoming.extend(_final_output_events(sessions))
    if isinstance(now, (int, float)):
        incoming.extend(_assignment_events(assignments, observed_at=float(now)))
    with state.semantic_history_lock:
        payload = _read(config)
        projects = payload["projects"]
        prior = projects.get(project)
        existing = prior.get("events", []) if isinstance(prior, dict) else []
        _bind_final_output_events([*(existing if isinstance(existing, list) else []), *incoming])
        merged = _redact_history(_merge(existing if isinstance(existing, list) else [], incoming))
        if isinstance(now, (int, float)):
            floor = float(now) - HISTORY_WINDOW_SEC
            merged = [event for event in merged if float(event.get("at") or 0) >= floor]
        cursors: dict[str, dict[str, Any]] = {}
        for event in merged:
            source = str(event.get("source_identity") or "source unavailable")
            cursor = cursors.get(source)
            if cursor is None or float(event.get("at") or 0) > float(cursor.get("at") or 0):
                cursors[source] = {
                    "at": event.get("at"),
                    "event_id": event.get("event_id"),
                }
        projects[project] = {
            "events": merged,
            "cursors": cursors,
            "window_sec": HISTORY_WINDOW_SEC,
            "source_scans": _retained_scans(
                prior if isinstance(prior, dict) else {},
                source_scans,
                existing if isinstance(existing, list) else [],
                incoming,
                merged,
            ),
            **_next_lineage(prior),
        }
        if len(projects) > MAX_PROJECTS:
            ranked = sorted(
                projects,
                key=lambda key: max(
                    (float(row.get("at") or 0) for row in projects[key].get("events", [])),
                    default=0,
                ),
                reverse=True,
            )[:MAX_PROJECTS]
            payload["projects"] = {key: projects[key] for key in ranked}
        persisted = _write(config, payload)
        # What is on disk now: none when the write failed or the cap evicted this very bucket.
        mark = mark_of(payload, project) if persisted else None
    return {
        "events": merged,
        "cursors": cursors,
        "persisted": persisted,
        "window_sec": HISTORY_WINDOW_SEC,
        **({"mark": mark} if mark else {}),
    }
