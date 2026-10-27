"""Codex rollout collection."""

from __future__ import annotations

import heapq
import json
import math
import os
import re
import shlex
from typing import TYPE_CHECKING, Any

# Absolute on the canonical top-level package: a sub-package cannot use
# parent-relative imports without tripping the repository's own TID252 rule.
from compass_runtime import claude_data, records, sessions, spacedock, transcripts, turns
from compass_runtime import io as runtime_io

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig
    from compass_runtime.sessions import Session
    from compass_runtime.state import RuntimeState


def discover(config: RuntimeConfig, _state: RuntimeState) -> bool:
    """Whether a Codex sessions store is present."""
    return runtime_io.any_store_dir(config, "codex.sessions")


# Rollout tails examined for a quota snapshot, newest mtime first. Token
# events are frequent, so the snapshot is almost always in the newest file;
# the rest of the budget covers a file that was only just created.
_USAGE_FILE_CAP = 8
_CHILD_LIFECYCLE_FILE_CAP = 24
_CHILD_LIFECYCLE_BYTES = 128 * 1024
_CHILD_LIFECYCLE_EVENT_CAP = 12
_CHILD_ASSIGNMENT_CAP = 140
_ENSIGN_AGENT_PATH_RE = re.compile(
    r"^/root/spacedock_ensign_([a-z0-9][a-z0-9_]*?)(?:_cycle[0-9]+)?$"
)
_DISPATCH_DIRECTORY = "/tmp/spacedock-dispatch"  # noqa: S108


def _dispatch_workflow_dir(line: str) -> str:
    """Return only an absolute workflow directory explicitly named by a dispatch."""
    if "--workflow-dir" not in line:
        return ""
    try:
        parts = shlex.split(line)
    except ValueError:
        return ""
    if "--workflow-dir" not in parts:
        return ""
    index = parts.index("--workflow-dir") + 1
    if index >= len(parts) or not os.path.isabs(parts[index]):
        return ""
    return records.safe_text(os.path.realpath(parts[index]), 1024)


def _usage_window(now: float, raw: Any) -> tuple[str, dict[str, Any]] | None:
    """One rate_limits window mapped onto the payload contract, or nothing."""
    win = records.as_dict(raw)
    pct = win.get("used_percent")
    minutes = win.get("window_minutes")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        return None
    if (
        not isinstance(minutes, (int, float))
        or isinstance(minutes, bool)
        or not math.isfinite(minutes)
    ):
        return None
    # Codex names no windows, only durations: 300 minutes is the 5-hour
    # window, 10080 the weekly. Classify by length so a plan that carries
    # only one of them (prolite writes just the weekly) still maps.
    key = "fiveH" if minutes < 1440 else "week"
    # The duration, published rather than left to the slot name. Codex is the one
    # producer that states a real length, and the slot it lands in cannot carry
    # it: anything under a day files into `fiveH`, so a 180-minute window drawn
    # against a five-hour constant would put the page's elapsed tick at 60% of
    # the bar with the window fully spent. Publishing the measurement is what
    # keeps that from being a silent error on this vendor alone.
    shaped: dict[str, Any] = {"pct": max(0, min(100, round(pct)))}
    # Published only when it is a real, positive duration. A zero or negative
    # `window_minutes` is not a measurement, and publishing one would put a
    # divide-by-zero behind the page's elapsed figure; omitting it drops the row
    # into the "no stated length" branch the page already has.
    if minutes > 0:
        shaped["windowSec"] = int(minutes * 60)
    resets = win.get("resets_at")
    if isinstance(resets, (int, float)) and not isinstance(resets, bool) and resets > 0:
        shaped.update(sessions.reset_fields(now, resets))
    return key, shaped


def usage(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_hours: float,
) -> list[dict[str, Any]]:
    """The newest quota snapshot Codex left on disk, as one usage entry.

    Codex writes ``rate_limits`` beside every token count, so this is a read
    of what is already there: no network, no credential, and a snapshot only
    as fresh as the last active turn, which is why the entry carries ``asOf``.
    One entry for the whole store — the CLI reports account quota, not
    per-session quota.
    """
    files: list[tuple[float, str]] = []
    for fp in runtime_io.glob_stores(
        config,
        "codex.sessions",
        "*",
        "*",
        "*",
        "rollout-*.jsonl",
    ):
        try:
            files.append((os.path.getmtime(fp), fp))
        except OSError:
            continue
    best: tuple[float, dict[str, Any]] | None = None
    for _, fp in heapq.nlargest(_USAGE_FILE_CAP, files):
        snap = transcripts.codex_analysis(config, state, fp)["rate_limits"]
        if snap and (best is None or snap[0] > best[0]):
            best = snap
    # A snapshot older than the dashboard's own activity window describes
    # quota windows that have themselves reset; the band's empty state is
    # more honest than a number that old.
    if not best or not sessions.is_fresh(config, now, best[0], window_hours * 3600):
        return []
    epoch, limits = best
    entry: dict[str, Any] = {"harness": "codex", "state": "ok", "asOf": int(epoch)}
    for raw in (limits.get("primary"), limits.get("secondary")):
        mapped = _usage_window(now, raw)
        if mapped:
            entry.setdefault(mapped[0], mapped[1])
    if "fiveH" not in entry and "week" not in entry:
        return []
    return [entry]


def _subagent_rate(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    now: float,
    scan: dict[str, Any] | None,
) -> int:
    """Recent Codex subagent output after its own task_started boundary.

    Takes the scan rather than making it: the caller needs the same scan for
    the child's model, and one child file must not be walked twice in a pass.
    """
    start = scan.get("last_start") if scan else None
    if not start:
        return 0
    info = transcripts.codex_analysis(config, state, path)
    recent: float = sum(
        tokens
        for epoch, tokens in info["usage_events"]
        if epoch >= start and sessions.is_fresh(config, now, epoch, config.rate_window_sec)
    )
    return round(recent / (config.rate_window_sec / 60))


def _child_lineage(
    sid: str,
    parent_sid: str,
    top_level: dict[str, tuple[float, str]],
    meta_by_sid: dict[str, dict[str, Any]],
) -> tuple[str, int, str | None]:
    """Resolve a child root, depth, and immediate named parent from recorded links."""
    immediate_parent = parent_sid
    depth = 1
    seen = {sid}
    while parent_sid not in top_level:
        parent_meta = meta_by_sid.get(parent_sid)
        next_parent = parent_meta.get("parent_session_id") if parent_meta is not None else None
        if not next_parent or next_parent in seen:
            break
        seen.add(parent_sid)
        parent_sid = next_parent
        depth += 1
    immediate_meta = meta_by_sid.get(immediate_parent)
    parent_name = (
        records.safe_text(immediate_meta.get("agent_label") or "subagent", 70)
        if depth > 1 and immediate_meta is not None
        else None
    )
    return parent_sid, depth, parent_name


def _child_lifecycle(
    config: RuntimeConfig,
    path: str,
    name: str,
    model: Any,
    depth: int,
    parent_name: str | None,
) -> list[dict[str, Any]]:
    """Bounded lifecycle signals written by one real Codex child rollout."""
    kinds = {
        "task_started": "subagent_task_started",
        "task_complete": "subagent_complete",
        "turn_aborted": "subagent_interrupted",
    }
    events: list[dict[str, Any]] = []
    for raw in runtime_io.reverse_lines(
        config,
        path,
        max_bytes=_CHILD_LIFECYCLE_BYTES,
        contains=b'"type"',
    ):
        try:
            row = records.as_dict(json.loads(raw))
        except (UnicodeDecodeError, ValueError):
            continue
        payload = records.as_dict(row.get("payload"))
        payload_type = payload.get("type")
        kind = (
            kinds.get(payload_type)
            if row.get("type") == "event_msg" and isinstance(payload_type, str)
            else None
        )
        at = records.parse_ts(row.get("timestamp"))
        if kind is None or at is None:
            continue
        events.append(
            {
                "at": at,
                "kind": kind,
                "name": name,
                "model": model,
                "depth": depth,
                "parent_name": parent_name,
                "source": "Codex child rollout lifecycle",
            }
        )
        if len(events) >= _CHILD_LIFECYCLE_EVENT_CAP:
            break
    return list(reversed(events))


def _assignment_summary(message: str) -> str:
    for raw in message.splitlines():
        line = raw.strip().lstrip("#*- ").strip()
        if not line or line.startswith(("<", "```", "Message Type:", "Task name:", "Sender:")):
            continue
        sentence = line.split(". ", 1)[0].strip().rstrip(".")
        return records.safe_text(sentence, _CHILD_ASSIGNMENT_CAP)
    return ""


def _ensign_dispatch_metadata(agent_path: str) -> tuple[str, str, str, str]:
    """Human title plus exact workflow/entity/stage identity from one ensign artifact."""
    match = _ENSIGN_AGENT_PATH_RE.fullmatch(agent_path)
    if match is None or not match.group(1):
        return "", "", "", ""
    slug = match.group(1).replace("_", "-")
    artifact = f"{_DISPATCH_DIRECTORY}/spacedock-ensign-{slug}.md"
    title = ""
    stage = ""
    workflow = ""
    for raw in runtime_io.iter_bounded_text_lines(
        artifact,
        max_lines=40,
        per_line_bytes=2048,
    ):
        line = raw.strip()
        if line.startswith("You are working on:"):
            title = records.safe_text(
                line[len("You are working on:") :].strip(),
                _CHILD_ASSIGNMENT_CAP,
            )
        elif line.startswith("Stage:"):
            candidate = line[len("Stage:") :].strip()
            if re.fullmatch(r"[a-z0-9][a-z0-9-]*", candidate):
                stage = candidate
        workflow = workflow or _dispatch_workflow_dir(line)
        if title and stage and workflow:
            break
    suffix = f"-{stage}" if stage else ""
    entity = slug[: -len(suffix)] if suffix and slug.endswith(suffix) else ""
    return title, entity, stage, workflow


def _child_assignment(
    config: RuntimeConfig,
    parent_path: str,
    agent_path: str,
) -> tuple[str | None, str, str, str, str]:
    """Latest exact plaintext parent assignment for one child path."""
    if not agent_path:
        return None, "unavailable", "", "", ""
    artifact_assignment, workflow_entity, workflow_stage, workflow_binding = (
        _ensign_dispatch_metadata(agent_path)
    )
    task_name = agent_path.rstrip("/").rsplit("/", 1)[-1]
    latest: str | None = None
    for raw in runtime_io.read_tail(config, parent_path) if parent_path else ():
        try:
            row = records.as_dict(json.loads(raw))
        except (ValueError, json.JSONDecodeError):
            continue
        payload = records.as_dict(row.get("payload"))
        if row.get("type") != "response_item" or payload.get("type") != "function_call":
            continue
        name = payload.get("name")
        arguments = payload.get("arguments")
        try:
            args = records.as_dict(json.loads(arguments)) if isinstance(arguments, str) else {}
        except (ValueError, json.JSONDecodeError):
            continue
        matches = (name == "spawn_agent" and args.get("task_name") == task_name) or (
            name == "followup_task" and args.get("target") == agent_path
        )
        if not matches:
            continue
        message = args.get("message")
        if not isinstance(message, str) or message.startswith("gAAAA"):
            latest = None
            continue
        latest = _assignment_summary(message) or None
    if latest:
        return latest, "exact parent dispatch", workflow_entity, workflow_stage, workflow_binding
    if artifact_assignment:
        return (
            artifact_assignment,
            "structured dispatch artifact",
            workflow_entity,
            workflow_stage,
            workflow_binding,
        )
    return None, "unavailable", "", "", ""


def _rollouts(
    config: RuntimeConfig,
    state: RuntimeState,
) -> tuple[
    dict[str, tuple[float, str]],
    list[tuple[str, float, str, dict[str, Any]]],
    dict[str, dict[str, Any]],
]:
    """Read Codex rollout identity once and separate dashboard roots."""
    found: dict[str, tuple[float, str]] = {}
    rollouts: list[tuple[str, float, str, dict[str, Any]]] = []
    meta_by_sid: dict[str, dict[str, Any]] = {}
    for fp in runtime_io.glob_stores(
        config,
        "codex.sessions",
        "*",
        "*",
        "*",
        "rollout-*.jsonl",
    ):
        try:
            mtime = os.path.getmtime(fp)
        except OSError:
            continue
        meta = transcripts.codex_meta(config, state, fp)
        session_sid = meta.get("session_id") or os.path.basename(fp)[: -len(".jsonl")][-36:]
        sid = (meta.get("thread_id") or session_sid) if meta.get("subagent") else session_sid
        rollouts.append((sid, mtime, fp, meta))
        meta_by_sid[sid] = meta
        if not meta.get("subagent") and (session_sid not in found or mtime > found[session_sid][0]):
            found[session_sid] = (mtime, fp)
    return found, rollouts, meta_by_sid


def _session_state(
    info: dict[str, Any] | None,
    scan: dict[str, Any] | None,
    tasks: list[dict[str, Any]],
    subagents: list[dict[str, Any]],
    *,
    working: bool,
) -> tuple[str, str]:
    """Current state and detail from the root event stream and its plan."""
    if not working or not ((scan and scan.get("turn_start") is not None) or subagents):
        return "idle", "awaiting your message"
    in_progress = next((task for task in tasks if task["status"] == "in_progress"), None)
    detail = sessions.working_detail(info, subagents)
    if in_progress:
        detail = in_progress["subject"] + "…"
    return "working", detail


def session_spacedock(
    config: RuntimeConfig,
    state: RuntimeState,
    path: str,
    subagents: list[dict[str, Any]],
    now: float,
    window: float,
) -> dict[str, Any] | None:
    boot = spacedock.transcript_boot(config, state, path) if config.spacedock_enabled else []
    if not boot:
        return None
    return {
        "role": "first-officer",
        "workflows": spacedock.session_workflows(
            config, state, boot, [str(a["name"]) for a in subagents], now, window
        ),
    }


def collect(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_hours: float,
    show_all: bool,
) -> list[Session]:
    # Resumes and subagent threads each write their own rollout file, so group
    # by the session_meta session_id rather than by file.
    # parent session_id -> running agents, recent child activity, and rate
    agent_data: dict[str, dict[str, Any]] = {}
    found, rollouts, meta_by_sid = _rollouts(config, state)
    path_by_sid = {sid: fp for sid, _, fp, _ in rollouts}
    assignment_cache: dict[tuple[str, str], tuple[str | None, str, str, str, str]] = {}
    lifecycle_paths = set(
        [
            fp
            for _, _, fp, meta in sorted(rollouts, key=lambda row: -row[1])
            if meta.get("subagent")
        ][:_CHILD_LIFECYCLE_FILE_CAP]
    )

    for sid, mtime, fp, meta in rollouts:
        if meta.get("subagent"):
            immediate_parent_sid = meta.get("parent_session_id") or sid
            parent_sid = immediate_parent_sid
            # Codex nests worker threads. Only top-level sessions are dashboard
            # rows, so walk the recorded parent links and attach each descendant
            # to the real row that owns it. The previous direct-parent lookup
            # orphaned depth-2 rollouts even though both links were on disk.
            parent_sid, depth, parent_name = _child_lineage(
                sid,
                parent_sid,
                found,
                meta_by_sid,
            )
            data = agent_data.setdefault(
                parent_sid,
                {"agents": [], "activity": [], "rate": 0, "lifecycle": []},
            )
            # One scan, above both branches. The rate window is wider than the
            # working window today, so the rate branch happens to have scanned
            # every child the second branch renders — but that is two config
            # numbers agreeing, not an invariant, and a child's model must not
            # rest on it. Still gated on a child being inside one window or the
            # other, so a store full of finished threads is not re-walked.
            charged = sessions.is_fresh(config, now, mtime, config.rate_window_sec)
            rendered = sessions.is_fresh(config, now, mtime, config.working_threshold_sec)
            scan = turns.scan_turns(config, state, fp, "codex") if charged or rendered else None
            name = records.safe_text(meta.get("agent_label") or "subagent", 70)
            data["activity"].extend(
                [mtime] if sessions.is_fresh(config, now, mtime, window_hours * 3600) else []
            )
            if fp in lifecycle_paths and sessions.is_fresh(
                config,
                now,
                mtime,
                window_hours * 3600,
            ):
                data["lifecycle"].extend(
                    _child_lifecycle(
                        config,
                        fp,
                        name,
                        (scan or {}).get("model"),
                        depth,
                        parent_name,
                    )
                )
            if charged:
                data["rate"] += _subagent_rate(config, state, fp, now, scan)
            if rendered and scan and scan.get("turn_start") is not None:
                # The child's own rollout declares its own model; the page, not
                # the collector, decides whether it differs from the parent's.
                # Membership is present lifecycle, not mtime inference: Codex
                # writes task_complete/turn_aborted and scan_turns retires the
                # active turn on either boundary.
                assignment_key = (
                    path_by_sid.get(immediate_parent_sid, ""),
                    str(meta.get("agent_path") or ""),
                )
                if assignment_key not in assignment_cache:
                    assignment_cache[assignment_key] = _child_assignment(config, *assignment_key)
                assignment = assignment_cache[assignment_key]
                data["agents"].append(
                    (
                        name,
                        mtime,
                        (scan or {}).get("model"),
                        turns.started_at(scan),
                        depth,
                        parent_name,
                        assignment[0],
                        assignment[1],
                        assignment[2],
                        assignment[3],
                        assignment[4],
                        sid,
                    )
                )
            continue

    out: list[Session] = []
    for sid, (mtime, fp) in found.items():
        data = agent_data.get(sid) or {
            "agents": [],
            "activity": [],
            "rate": 0,
            "lifecycle": [],
        }
        agents = sorted(data["agents"], key=lambda a: -a[1])
        activity_sources = (mtime, *data["activity"])
        last_activity = sessions.newest_plausible(config, now, activity_sources)
        active = sessions.is_fresh(config, now, last_activity, window_hours * 3600)
        if not (active or show_all):
            continue
        info = transcripts.codex_analysis(config, state, fp) if active else None
        # The prompt and the instruction line come from a backward walk rather
        # than from `info`, whose tail read misses the newest prompt on 62% of
        # the rollouts that have one (DRC-4264). Behind the same `active` gate as
        # the analysis: a stale `?all=1` row pays for no read and reports no
        # title, which is "not read" rather than "no prompt".
        asked = (
            transcripts.codex_instruction(config, state, fp)
            if active
            else {"title": None, "last_prompt": "", "instruction": None}
        )
        # Hoisted above `subagents` because the model is published beside them,
        # and kept behind the `if info` guard so a stale `?all=1` row still pays
        # for no scan. Such a row reports no model rather than an old one: the
        # collector has not read it this pass, and that is the honest reading.
        scan = turns.scan_turns(config, state, fp, "codex") if info else None
        subagents = [
            {
                "name": label,
                "model": model,
                "started_at": started_at,
                "active": None,
                "parent": None,
            }
            for label, _, model, started_at, *_ in agents
        ]
        hierarchy = [
            {
                "name": label,
                "model": model,
                "started_at": started_at,
                "depth": depth,
                "parent_name": parent_name,
                "assignment": assignment,
                "assignment_status": assignment_status,
                "observer_sid": observer_sid,
                **(
                    {
                        "workflow_entity": workflow_entity,
                        "workflow_stage": workflow_stage,
                        "workflow_binding": workflow_binding,
                    }
                    if workflow_entity and workflow_stage
                    else {}
                ),
            }
            for (
                label,
                _,
                model,
                started_at,
                depth,
                parent_name,
                assignment,
                assignment_status,
                workflow_entity,
                workflow_stage,
                workflow_binding,
                observer_sid,
            ) in sorted(
                agents,
                key=lambda agent: (agent[4], -agent[1], agent[0]),
            )
        ]
        lifecycle = sorted(data["lifecycle"], key=lambda event: event["at"])[-48:]
        # Behind the same `active` gate as the rest of the reads: a stale
        # `?all=1` row pays for no walk and reports no plan, which is "not read"
        # rather than a plan that has since moved on.
        tasks = transcripts.codex_plan(config, state, fp) if active else []
        done = sum(1 for t in tasks if t["status"] == "completed")
        last_event_sources = ((info or {}).get("last_event_ts") or 0, *activity_sources)
        session_state, state_detail = _session_state(
            info,
            scan,
            tasks,
            subagents,
            working=sessions.is_fresh(
                config,
                now,
                sessions.newest_plausible(config, now, last_event_sources),
                config.working_threshold_sec,
            ),
        )

        cwd = transcripts.codex_meta(config, state, fp).get("cwd") or ""
        # The session's own `/goal`, behind the same guard as the first prompt below, so a row
        # the rollout was not read for publishes none. Read before the clear, which comes from
        # the same cache entry.
        goal = claude_data.session_goal(config, state, fp, "codex") if info else None
        s = sessions.base_session(
            "codex",
            sid,
            sessions.project_from_cwd(config, cwd) or "codex",
        )
        sessions.apply_project_identity(config, s, cwd)
        s.update(
            {
                # Codex publishes the whole rollout id as `sid`, and that is the id
                # `codex resume <SESSION_ID>` takes. Repeated into its own field
                # rather than left for the page to infer from the harness key: the
                # page's rule is "no token, no control", and a harness whose `sid`
                # happens to be resumable is a fact this collector knows and the
                # page does not.
                "spacedock": session_spacedock(
                    config, state, fp, subagents, now, window_hours * 3600
                )
                if active
                else None,
                "resume_id": sessions.resume_token(s["sid"]),
                # A session started with `/goal` and never prompted since has no prompt to name
                # it, because the goal's own message is Codex's wrapper; its goal names it.
                "title": asked["title"]
                or (transcripts.prompt_title(config, goal["text"]) if goal else None),
                "prompt_states_work": asked.get("prompt_states_work", False),
                "prompt_at": asked.get("prompt_at"),
                **(transcripts.first_prompt(config, state, fp, "codex") if info else {}),
                "session_goal": goal,
                "session_goal_cleared": (
                    claude_data.session_goal_cleared(state, fp) if info else None
                ),
                "last_prompt": asked["last_prompt"],
                "instruction": asked["instruction"],
                "last_output": (info or {}).get("last_output"),
                "state": session_state,
                "state_detail": state_detail,
                "active": active,
                "last_activity": last_activity,
                # What retires a gate this session already answered. Codex reports
                # a gate through the event overlay, and the reducer only lets a
                # wait lapse when the session's OWN activity outruns it -- so
                # without this the row stayed red from the approval to the turn's
                # `Stop`, which is DRC-4097 on a second harness.
                #
                # The rollout's own newest record, not its mtime and not
                # `last_activity`: the latter folds in subagent files, and a child
                # writing says nothing about whether the human answered. Measured
                # on 0.149.0 rather than assumed, because the whole value of the
                # signal is that it stays put while a person is being asked: with
                # a real approval prompt standing open the rollout held at 13
                # lines and one timestamp across 25 seconds, then advanced to 27
                # once the gate was answered. A tail with no timestamp reports 0,
                # which leaves the wait standing -- the safe direction, and the
                # one an unreported value already takes in the reducer.
                "own_activity": (info or {}).get("last_event_ts") or 0,
                "started_at": turns.started_at(scan),
                "rate_per_min": sessions.rate_from(info, now, config) + data["rate"],
                "session_output_tokens": (scan.get("session_output_tokens") if scan else None),
                "turn_output_tokens": scan.get("turn_output_tokens") if scan else None,
                "turn": turns.turn_progress(scan, session_state, now, config),
                # `provider` stays None: no Codex record carries one, and
                # reading "openai" off the harness name would be inference.
                "model": scan.get("model") if scan else None,
                "subagents": subagents,
                "subagent_hierarchy": hierarchy,
                "subagent_events": lifecycle,
                "tasks": tasks,
                "total": len(tasks),
                "done": done,
                "open": len(tasks) - done,
                "progress_pct": round(done * 100 / len(tasks)) if tasks else 0,
                # `eta_h` stays at its default. Claude derives one from per-task
                # timestamps; a Codex plan step carries none, and the completion
                # times are only recoverable by walking every `update_plan` in
                # the file forward. An estimate renders identically to a measured
                # one, so no number is the honest reading until that walk exists.
            }
        )
        out.append(s)
    return out
