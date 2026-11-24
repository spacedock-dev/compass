"""Claude Code collection: task files, subagents, sessions, and Spacedock strips."""

from __future__ import annotations

import fnmatch
import json
import os
import stat
from collections import Counter
from dataclasses import dataclass, field, replace
from itertools import chain
from typing import TYPE_CHECKING, Any

from compass_runtime import claude_data, notifications, project_context, records
from compass_runtime import io as runtime_io
from compass_runtime import quota as runtime_quota
from compass_runtime import sessions as runtime_sessions
from compass_runtime import spacedock as runtime_spacedock
from compass_runtime import transcripts as runtime_transcripts
from compass_runtime import turns as runtime_turns

if TYPE_CHECKING:
    from compass_runtime.config import RuntimeConfig
    from compass_runtime.sessions import Session
    from compass_runtime.state import RuntimeState, SubagentTreeStamp


# The lead's own row in the teams registry. The lead IS the session, so it is
# never reported as a subagent of itself.
TEAM_LEAD_NAME = "team-lead"


def load_team_members(config: RuntimeConfig) -> dict[str, list[dict[str, Any]]]:
    """parent prefix -> the non-lead members registered in the teams registry.

    A dispatched member appears in ``teams/session-<sid>/config.json`` at the
    moment it is spawned, which is before it has written a transcript byte. For
    a healthy agent that window is seconds; for one parked on a startup
    permission prompt it is unbounded, and the registry entry plus an inbox file
    are then its only trace on disk (DRC-4263).

    The registry is a ROSTER, not a heartbeat: one file mtime covers every
    member, and it moves only on a join or a leave, so nothing here can age an
    individual member the way ``load_subagents`` ages a transcript. Callers get
    ``joined`` per member and must bound it themselves.

    It is no longer safe to read as a live-only signal. Pruning on completion was
    measured on two finished sessions here and held until Claude Code 2.1.259,
    which RETAINS a finished member and marks it ``isActive: false`` instead.
    ``active`` carries that flag, and a caller may only ever let it demote a
    member it already believes is running: transcript freshness stays
    authoritative for "running now" (DRC-4229), and whether a hard-killed pane
    clears the flag is unmeasured. ``None`` means the registry did not say —
    which is the case for the in-process lead on every registry measured.

    An older layout keeps ``teams/<uuid>/inboxes/`` with no ``config.json`` at
    all; the glob simply does not match it, and those members are reachable
    through their ``agent-<hex>.jsonl`` transcripts anyway.
    """
    by_prefix: dict[str, list[dict[str, Any]]] = {}
    for fp in runtime_io.glob_stores(config, "claude.teams", "*", "config.json"):
        try:
            with runtime_io.open_harness_text(fp) as f:
                registry = json.load(f)
            registered = os.stat(fp).st_mtime
        except (OSError, ValueError):  # ValueError covers UnicodeDecodeError
            continue
        if not isinstance(registry, dict):
            continue
        prefix = os.path.basename(os.path.dirname(fp)).removeprefix("session-")[:8]
        if not prefix:
            continue
        for member in registry.get("members") or ():
            # Untrusted JSON from a store nothing validates: a member that is not
            # a dict, or carries no id, is skipped rather than published as a row.
            if not isinstance(member, dict):
                continue
            agent_id = member.get("agentId")
            if not isinstance(agent_id, str) or not agent_id:
                continue
            name = member.get("name")
            label = name if isinstance(name, str) and name else agent_id.split("@", 1)[0]
            if label == TEAM_LEAD_NAME:
                continue
            joined = member.get("joinedAt")
            when = registered
            if isinstance(joined, (int, float)) and not isinstance(joined, bool) and joined > 0:
                # Milliseconds on every registry measured. Scaled by magnitude
                # rather than assumed, so a seconds-valued field would read as a
                # stale join (excluded) instead of one 55,000 years in the future.
                when = joined / 1000 if joined > 1e11 else float(joined)
            flag = member.get("isActive")
            by_prefix.setdefault(prefix, []).append(
                {
                    "agent_id": agent_id,
                    "local": agent_id.split("@", 1)[0],
                    # Unbounded on purpose: the roster join and `member_flags`
                    # key on this string, where a clip loses a long name
                    # outright. Each consumer that publishes it bounds its own
                    # copy -- both of them. That is the part that was missed:
                    # "published_agent bounds it" is true of the element and
                    # not of the label, and the state line below went a round
                    # with no bound at all on the strength of it.
                    "label": label,
                    "joined": when,
                    # Untrusted JSON: only a real bool counts, so a string
                    # "false" reads as "the registry did not say" rather than as
                    # a demotion.
                    "active": flag if isinstance(flag, bool) else None,
                }
            )
    return by_prefix


def started_agent_ids(prefix: str, children: list[Teammate], paths: list[str]) -> set[str]:
    """Identifiers of every member of one team that HAS written a transcript.

    The join is on the agent id — ``<name>@session-<parent prefix>``, which is
    what a child transcript's ``agentName`` and ``teamName`` reassemble to — and
    not on the name alone, because a name is unique only inside its own team and
    the registry says nothing about which team a bare name came from.

    The bare local part goes in beside the full id anyway. Everything here is
    already scoped to one parent prefix, so it cannot match a stranger's agent,
    and it is the direction that fails safe: an extra entry can only mark a
    member as started, never invent one that has not.
    """
    started = set()
    for child in children:
        name = child.name
        if name:
            started.add(f"{name}@session-{prefix}")
            started.add(name)
    for path in paths:
        # Legacy members carry a hex id and no name at all; their transcript is
        # `agent-<id>.jsonl` under the session's own subagents/ directory.
        base = os.path.basename(path)
        if base.startswith("agent-") and base.endswith(".jsonl"):
            started.add(base[len("agent-") : -len(".jsonl")])
    return started


def load_tasks(
    config: RuntimeConfig, *, native_ids: bool = False
) -> dict[str, list[dict[str, Any]]]:
    """Task lists by display prefix, or by directory id for identity joins."""
    by_session: dict[str, list[dict[str, Any]]] = {}
    for fp in runtime_io.glob_stores(config, "claude.tasks", "*", "*.json"):
        if os.path.basename(fp).startswith("."):
            continue
        try:
            # Explicit UTF-8: the locale default is cp1252 on Windows, which
            # mojibakes non-ASCII task subjects and raises UnicodeDecodeError on
            # the bytes that code page leaves undefined. That is a ValueError but
            # not a JSONDecodeError, so narrowing the handler below lets it escape
            # and error the whole Claude collector for a pass.
            with runtime_io.open_harness_text(fp) as f:
                task = json.load(f)
            st = os.stat(fp)
        except (OSError, ValueError):
            continue
        if not isinstance(task, dict):
            continue
        sid = os.path.basename(os.path.dirname(fp)).removeprefix("session-")
        if not sid:
            continue
        created = getattr(st, "st_birthtime", st.st_mtime)
        # Field types are unvalidated JSON from disk — coerce non-strings so
        # one malformed record cannot TypeError the whole Claude collector.
        subject = task.get("subject")
        active_form = task.get("activeForm")
        status = task.get("status")
        by_session.setdefault(sid if native_ids else sid[:8], []).append(
            {
                "id": task.get("id"),
                "subject": subject if isinstance(subject, str) and subject else "(untitled)",
                "activeForm": active_form if isinstance(active_form, str) else "",
                "status": status if isinstance(status, str) and status else "pending",
                "created": created,
                "updated": st.st_mtime,
            }
        )
    return by_session


def directory_stamp(path: str) -> tuple[int, int, int, int] | None:
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    if not stat.S_ISDIR(info.st_mode):
        return None
    return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns


def subagent_tree_stamp(sess_dir: str) -> tuple[SubagentTreeStamp | None, list[str]]:
    subagents = os.path.join(sess_dir, "subagents")
    workflows = os.path.join(subagents, "workflows")
    stamp = {path: directory_stamp(path) for path in (sess_dir, subagents, workflows)}
    if stamp[workflows] is None:
        return stamp, []
    # A run can exist before its first worker or point to a target that is
    # still missing. Keep those names so each can change without its container.
    complete = True
    runs: list[str] = []
    with os.scandir(workflows) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_symlink() or entry.is_dir(follow_symlinks=False):
                    stamp[entry.path] = directory_stamp(entry.path)
                    if stamp[entry.path] is not None:
                        runs.append(entry.path)
            except OSError:
                complete = False
    return (stamp if complete else None), sorted(runs)


def worker_paths(directory: str) -> list[str]:
    # glob suppresses scan errors, making a failed walk look like an empty one.
    with os.scandir(directory) as entries:
        names = fnmatch.filter((entry.name for entry in entries), "agent-*.jsonl")
    return [os.path.join(directory, name) for name in sorted(names)]


def agent_transcripts(
    transcript: str | None,
    *,
    config: RuntimeConfig | None = None,
    state: RuntimeState | None = None,
) -> list[tuple[str, float]]:
    """(path, mtime) for every subagent transcript belonging to a session.

    With ``config`` and ``state`` the worker index holds paths and directory
    stamps. An append only moves the file's mtime, so the file stats are fresh
    even on an index hit.
    """
    if not transcript:
        return []
    sess_dir = os.path.join(
        os.path.dirname(transcript), os.path.basename(transcript)[: -len(".jsonl")]
    )
    subagents = os.path.join(sess_dir, "subagents")
    cache = state if config is not None else None
    # Claude can leave a session directory with no worker tree. Check again each
    # refresh so the first worker can bring an archived parent back into view.
    if not os.path.isdir(subagents):
        if cache is not None:
            with cache.cache_lock:
                cache.claude_subagent_index.pop(transcript, None)
        return []
    hit = None
    if cache is not None:
        with cache.cache_lock:
            hit = cache.claude_subagent_index.get(transcript)
    if hit is not None:
        try:
            current = {path: directory_stamp(path) for path in hit[0]}
        except OSError:
            current = None
        if current == hit[0]:
            return stamped(hit[1])
    if not runtime_io.admit_harness_root(subagents, tighten_permissions=False):
        return []
    # Stamped before the listing, never after it. A transcript written while the
    # tree is being walked moves a directory mtime, and a stamp taken afterwards
    # would record that move as already accounted for, pinning the listing that
    # missed the file. Stamping first can only cost one extra glob next time.
    try:
        stamp, runs = subagent_tree_stamp(sess_dir)
    except OSError:
        stamp, runs = None, []
    paths: list[str] = []
    complete = stamp is not None
    for directory in (subagents, *runs):
        try:
            paths.extend(worker_paths(directory))
        except OSError:
            complete = False
    if cache is not None and stamp is not None and complete:
        with cache.cache_lock:
            if cache.claude_subagent_index.get(transcript) is hit:
                cache.claude_subagent_index[transcript] = stamp, paths
    return stamped(paths)


def stamped(paths: list[str]) -> list[tuple[str, float]]:
    """(path, current mtime) per path, dropping any that has since gone.

    Restated on every call, cached listing or not: a subagent writing to its
    transcript moves no directory mtime, so serving a remembered mtime would
    freeze a running agent at the moment it was first seen.
    """
    found: list[tuple[str, float]] = []
    for fp in paths:
        try:
            found.append((fp, os.path.getmtime(fp)))
        except OSError:
            continue  # transcript rotated/deleted between glob and stat
    return found


def child_model(analysis: dict[str, Any] | None) -> str | None:
    """The model a subagent's own transcript reports, or None.

    ``model_sidechain`` first, then ``model``, because ``isSidechain`` inverts
    between a session and its children: a subagent's own assistant records are
    all flagged as sidechains, so its model lands in the sidechain half of
    ``claude_data.analyze_transcript``. Reading both, in that order, is what lets
    one helper serve a legacy ``agent-*.jsonl`` transcript and a modern child
    ``<uuid>.jsonl`` alike.

    Never falls back to the parent's model: an unread child is published as None
    so the page can tell "the same model as its parent" from "not measured".
    """
    if not analysis:
        return None
    value = analysis.get("model_sidechain") or analysis.get("model")
    return value if isinstance(value, str) and value else None


def agent_label(transcript: str) -> str | None:
    """The display name beside a subagent transcript, from its meta sibling."""
    try:
        with runtime_io.open_harness_text(transcript[: -len(".jsonl")] + ".meta.json") as f:
            meta = json.load(f)
    except (OSError, ValueError):  # ValueError covers UnicodeDecodeError
        return None
    # Meta values are untyped JSON: a non-string name must not TypeError the
    # whole Claude collector.
    if not isinstance(meta, dict):
        return None
    for key in ("name", "description", "agentType"):
        value = meta.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def published_agent(
    name: str | None,
    *,
    model: str | None,
    started_at: float | None,
    active: bool | None,
    parent: str | None,
) -> dict[str, Any]:
    """One element of the published ``subagents[]`` list.

    Both new keys are declared for every element rather than added where they
    happen to be known, which is DRC-4223's rule for widening this element:
    always present, null meaning not measured.
    """
    # `redact_clip`, not a slice: both strings are the untrusted `agentName`,
    # and a bare `[:70]` bounds BEFORE the credential sweep runs over the
    # assembled rows, so a cut landing inside a key leaves a run too short to
    # match and publishes it unmarked. Redacting first is the order
    # `records.redact_clip` exists to own, and the callers hand this the full
    # string for that reason. `aggregate._redact_published_text` still sweeps
    # both keys: it covers every harness, and redacting an already-marked
    # string is a no-op.
    return {
        "name": records.redact_clip(name or "subagent", 70),
        "model": model,
        "started_at": started_at,
        "active": active,
        "parent": records.redact_clip(parent, 70) if parent else None,
    }


def load_subagents(
    config: RuntimeConfig,
    transcript: str | None,
    now: float,
    *,
    found: list[tuple[str, float]] | None = None,
    models: dict[str, str | None] | None = None,
    window_sec: float | None = None,
    state: RuntimeState | None = None,
) -> list[dict[str, Any]]:
    """Claude subagents beneath the session directory, each carrying its own
    ``active``; fresh mtime = running. Covers both layouts in ``SUBAGENT_GLOBS``.

    ``found`` lets a caller that has already listed the directory hand the
    listing over, so one session costs one scan. The collector needs the full
    listing anyway for its parked-parent activity check.

    ``models`` is transcript path -> the model that transcript reports, from the
    analysis the caller has already run for the session's rate. A path this
    function is not told about publishes None, which is what a caller with no
    analyses to hand gets for every agent — never a guess at the parent's model.

    ``window_sec`` widens what is RETURNED without widening what reads as
    running: an agent quiet for longer than ``working_threshold_sec`` but inside
    this window comes back with ``active`` false. One list rather than two calls,
    because the meta read and the head read are per file and a caller that wants
    only the running ones filters on ``active``. Without it only running agents
    come back, so every existing caller is unchanged.

    ``state`` memoises the head read behind the start stamp, which starts to
    matter once ``window_sec`` retains a quiet agent: unmemoised, a retained
    roster re-reads a head per agent per collection, the cost
    ``agent_start_cache`` exists for.
    """
    agents: list[dict[str, Any]] = []
    for fp, mtime in agent_transcripts(transcript) if found is None else found:
        live = runtime_sessions.is_fresh(config, now, mtime, config.working_threshold_sec)
        if not live and not (
            window_sec is not None and runtime_sessions.is_fresh(config, now, mtime, window_sec)
        ):
            continue
        label = agent_label(fp)
        agents.append(
            {
                # Bounded by `published_agent`, which redacts first.
                "label": label or "subagent",
                "mtime": mtime,
                "model": (models or {}).get(fp),
                "started_at": claude_data.transcript_started_at(config, fp, state=state),
                "active": live,
            }
        )
    agents.sort(key=lambda a: -a["mtime"])
    return agents


def session_spacedock(
    config: RuntimeConfig,
    state: RuntimeState,
    transcript: str | None,
    subagents: list[dict[str, Any]],
    now: float,
    window_sec: float,
) -> dict[str, Any] | None:
    """Spacedock role and workflow strips for one Claude session, or None.

    Gated on the session declaring a Spacedock ``agentSetting``, so a session
    that has nothing to do with Spacedock costs one cached lookup and opens no
    project file. Only a first officer gets strips: an ensign is a single worker
    whose own stage is already the parent's strip.
    """
    if not transcript:
        return None
    setting = claude_data.agent_setting(config, state, transcript)
    if setting == runtime_spacedock.SPACEDOCK_ENSIGN:
        return {"role": "ensign", "workflows": []}
    if setting != runtime_spacedock.SPACEDOCK_FO:
        return None
    if not config.spacedock_enabled:
        # The switch withdraws the project reads, not the role: the badge comes
        # from the transcript head, which is a store path either way.
        return {"role": "first-officer", "workflows": []}
    boot = runtime_spacedock.transcript_boot(config, state, transcript)
    names = [str(a.get("label") or "") for a in subagents]
    return {
        "role": "first-officer",
        "workflows": runtime_spacedock.session_workflows(
            config, state, boot, names, now, window_sec
        ),
    }


def in_flight_work(
    config: RuntimeConfig,
    now: float,
    info: dict[str, Any] | None,
    waiting_count: int,
    newest_unpaired: float | None,
) -> tuple[float | None, str | None]:
    """Background Stop exception's expiry and independently capped working detail."""
    pending = (info or {}).get("pending_tool")
    cap = config.claude_tool_in_flight_max_sec
    tool_at = pending["ts"] if pending else 0
    tool_live = runtime_sessions.is_fresh(config, now, tool_at or 0, cap)
    background_live = runtime_sessions.is_fresh(config, now, newest_unpaired or 0, cap)
    until = newest_unpaired + cap if background_live and newest_unpaired else None
    if tool_live and pending:
        return until, runtime_sessions.working_detail({"last_tool": pending["name"]}, [])
    if background_live:
        return (
            until,
            f"waiting on {waiting_count} background task{'s' if waiting_count != 1 else ''}",
        )
    return None, None


def transcript_turn_end(
    config: RuntimeConfig,
    info: dict[str, Any] | None,
    transcript: str,
    *,
    work_activity: float,
    blocked: bool,
) -> float | None:
    """The turn stop this session's transcript records, while it still stands, else None.

    Claude Code's own `stop_hook_summary` for this session (owner, 2026-10-02):
    the stop a hook would have reported, read from the tail the analysis already
    read, for a board no hook reaches and for a stop from before a restart. It
    stands only while nothing came after it: no conversation record newer than
    it, no open question, no unstarted or running subagent, and no other work
    newer than it by more than the activity grace. Every collection recomputes
    it, so a new prompt withdraws it. Never written as `finished_at`, which
    stays an observation (`sessions.base_session`).
    """
    if not info or not transcript:
        return None
    stop = info.get("turn_stop_ts") or 0
    if not (
        stop > 0
        and info.get("turn_stop_sid") == os.path.basename(transcript).removesuffix(".jsonl")
        and (info.get("last_conversation_ts") or 0) <= stop
        and not info.get("pending_input_tool")
        and not blocked
        and work_activity <= stop + config.overlay_wait_activity_grace_sec
    ):
        return None
    return float(stop)


def discover(config: RuntimeConfig, state: RuntimeState) -> bool:
    """Whether a Claude projects store is present."""
    found = runtime_io.any_store_dir(config, "claude.projects")
    if not found:
        with state.cache_lock:
            state.claude_subagent_index.clear()
    return found


def usage(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_hours: float,
) -> list[dict[str, Any]]:
    """Claude's quota: the last fetch, merged with what Claude Code's status line reported.

    This provider never touches the network: the fetch runs on its own thread,
    triggered by `/api/data` requests carrying the page's consent, and this
    only publishes whatever that thread last cached. The registry wires it in
    only when the fetch feature is enabled, so `--no-usage` leaves the Claude
    row with no provider at all.

    The window is passed through because the cache reader gates on it: a reading
    older than the dashboard's own activity window is withheld, the same rule the
    Codex disk reader applies to its snapshot.
    """
    fetched = runtime_quota.cached_entries(config, state, "claude", now, window_hours)
    received = runtime_quota.claude_receipt_entries(config, state, now, window_hours)
    return runtime_quota.merge_claude_usage(fetched, received)


@dataclass(frozen=True, slots=True)
class TranscriptCopy:
    path: str
    sid: str
    mtime: float
    plausible_mtime: float
    workers: list[tuple[str, float]]
    worker_mtime: float

    @property
    def activity(self) -> float:
        return max(self.plausible_mtime, self.worker_mtime)

    def rank(self) -> tuple[float, float, float]:
        return self.activity, self.plausible_mtime, self.mtime


def merge_worker_copies(
    config: RuntimeConfig, now: float, copies: list[TranscriptCopy]
) -> list[TranscriptCopy]:
    # Mirrors can contain different workers or different versions of one worker.
    # A newer parent transcript says nothing about which worker files it contains.
    workers: dict[str, tuple[str, float]] = {}
    plausible: dict[str, float] = {}
    for copy in copies:
        directory = copy.path.removesuffix(".jsonl")
        for path, mtime in copy.workers:
            relative = os.path.relpath(path, directory)
            stamp = runtime_sessions.newest_plausible(config, now, (mtime,))
            if relative not in workers or stamp > plausible[relative]:
                workers[relative] = (path, mtime)
                plausible[relative] = stamp
    files = list(workers.values())
    newest = max(plausible.values(), default=0)
    return [replace(copy, workers=files, worker_mtime=newest) for copy in copies]


@dataclass(frozen=True, slots=True)
class Teammate:
    transcript: TranscriptCopy
    name: str
    parent: str | None


@dataclass(slots=True)
class SessionGroup:
    source: TranscriptCopy | None = None
    resumable: bool = True
    children: dict[str, Teammate] = field(default_factory=dict)
    tasks: list[dict[str, Any]] = field(default_factory=list)


def session_groups(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_sec: float,
    show_all: bool,
    paths: list[str],
) -> dict[str, SessionGroup]:
    tasks = load_tasks(config, native_ids=True)
    task_mtimes = {
        sid: runtime_sessions.newest_plausible(config, now, (t["updated"] for t in entries))
        for sid, entries in tasks.items()
    }

    def fresh(stamp: float) -> bool:
        return runtime_sessions.is_fresh(config, now, stamp, window_sec)

    def working(stamp: float) -> bool:
        return runtime_sessions.is_fresh(config, now, stamp, config.working_threshold_sec)

    reachable = {sid[:8] for sid, mtime in task_mtimes.items() if fresh(mtime)}
    native_copies: dict[str, list[TranscriptCopy]] = {}
    for path in paths:
        sid = os.path.basename(path).removesuffix(".jsonl")
        if "-agent-" in sid or sid.startswith("agent-"):
            continue
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        # Worker mtimes can wake an archived transcript without reading its head.
        workers = agent_transcripts(path, config=config, state=state)
        worker_mtime = runtime_sessions.newest_plausible(config, now, (ts for _, ts in workers))
        plausible = runtime_sessions.newest_plausible(config, now, (mtime,))
        copy = TranscriptCopy(path, sid, mtime, plausible, workers, worker_mtime)
        native_copies.setdefault(sid, []).append(copy)
        if fresh(copy.activity):
            reachable.add(sid[:8])

    candidates: dict[str, list[TranscriptCopy]] = {}
    for sid, copies in native_copies.items():
        merged = merge_worker_copies(config, now, copies) if len(copies) > 1 else copies
        candidates.setdefault(sid[:8], []).extend(merged)

    identities: dict[str, tuple[str, str] | None] = {}
    metadata: set[str] = set()

    def identity(copy: TranscriptCopy) -> tuple[str, str] | None:
        if copy.path not in identities:
            is_agent, name, parent = claude_data.agent_identity(config, state, copy.path)
            conversation = (
                True if is_agent else claude_data.has_conversation(config, state, copy.path)
            )
            if conversation is False:
                metadata.add(copy.path)
            identities[copy.path] = (name, parent) if conversation else None
        return identities[copy.path]

    def sole_session(copies: list[TranscriptCopy]) -> TranscriptCopy | None:
        known = [(copy, role) for copy in copies if (role := identity(copy)) is not None]
        if len({copy.sid for copy, _ in known}) == 1:
            # A short copy can end before the record that identifies its team.
            return max(known, key=lambda entry: (bool(entry[1][1]), entry[0].rank()))[0]
        return None

    def find_parent(copy: TranscriptCopy, prefix: str) -> TranscriptCopy | None:
        choices = candidates.get(prefix, [])
        # A newer mirror may live beside an unrelated lead with the same
        # prefix. Keep the evidence from the other copy's folder in the join.
        folders = {os.path.dirname(candidate.path) for candidate in native_copies[copy.sid]}
        local = [candidate for candidate in choices if os.path.dirname(candidate.path) in folders]
        local_source = sole_session(local)
        if local_source is not None:
            # A folder can resolve a prefix collision. The resolved UUID still
            # uses the same representative as the full-history scan.
            choices = [candidate for candidate in choices if candidate.sid == local_source.sid]
        return sole_session(choices)

    groups: dict[str, SessionGroup] = {}
    teammates: dict[str, TranscriptCopy] = {}
    teammate_ids: set[str] = set()
    for prefix, copies in candidates.items():
        if not (show_all or prefix in reachable):
            continue
        for copy in copies:
            role = identity(copy)
            if role is None:
                if copy.path in metadata and working(copy.worker_mtime):
                    # The worker directory can still identify running work
                    # when the parent file contains only title metadata.
                    groups.setdefault(copy.sid, SessionGroup(source=copy, resumable=False))
                continue
            if role[1]:
                teammate_ids.add(copy.sid)
                if fresh(copy.activity):
                    existing = teammates.get(copy.sid)
                    if existing is None or copy.rank() > existing.rank():
                        teammates[copy.sid] = copy
            else:
                group = groups.setdefault(copy.sid, SessionGroup())
                if group.source is None or not group.resumable or copy.rank() > group.source.rank():
                    group.source = copy
                    group.resumable = True
    for sid in teammate_ids:
        groups.pop(sid, None)

    tasks_by_prefix: dict[str, list[str]] = {}
    for sid in tasks:
        tasks_by_prefix.setdefault(sid[:8], []).append(sid)

    def task_owner(sid: str) -> TranscriptCopy | None:
        choices = candidates.get(sid[:8], [])
        if len(sid) > 8:
            choices = [copy for copy in choices if copy.sid == sid]
        return sole_session(choices)

    for sid, mtime in task_mtimes.items():
        if show_all or fresh(mtime):
            owner = task_owner(sid)
            if owner is not None and (role := identity(owner)) is not None and role[1]:
                teammates.setdefault(owner.sid, owner)

    folded_into: dict[str, str] = {}
    reached = set(reachable)
    for seed in teammates.values():
        team: list[tuple[TranscriptCopy, str]] = []
        seen: dict[str, int] = {}
        root: str | None = None
        source: TranscriptCopy | None = None
        resumable = True
        copy = seed
        while (role := identity(copy)) is not None and role[1]:
            name, parent = role
            seen[copy.sid] = len(team)
            team.append((copy, name))
            lead = find_parent(copy, parent)
            if lead is None:
                # A title file cannot own the team. An unreadable conversation
                # or two competing leads still leave its ownership uncertain.
                task_leads = tasks_by_prefix.get(parent, [])
                if len(task_leads) == 1 and all(
                    candidate.path in metadata for candidate in candidates.get(parent, [])
                ):
                    root = task_leads[0]
                    if root == parent:
                        worker_leads = {
                            candidate.sid
                            for candidate in candidates.get(parent, [])
                            if working(candidate.worker_mtime)
                        }
                        if len(worker_leads) == 1:
                            root = next(iter(worker_leads))
                    break
                anchor = copy
            elif lead.sid in seen:
                anchor = min(team[seen[lead.sid] :], key=lambda member: member[0].sid)[0]
            else:
                copy = lead
                continue
            if not fresh(seed.worker_mtime):
                break
            # Keep the work addressable by an observed teammate when the team
            # has no resolvable lead.
            root = anchor.sid
            source = anchor
            resumable = False
            break
        else:
            root = copy.sid
            source = copy

        if root is None:
            continue
        group = groups.setdefault(root, SessionGroup(source=source, resumable=resumable))
        reached.add(root[:8])
        for member, _ in team:
            folded_into[member.sid] = root
        if not fresh(seed.activity):
            continue
        for index, (member, name) in enumerate(team):
            parent_name = (
                team[index + 1][1]
                if index + 1 < len(team) and (resumable or member.sid != root)
                else None
            )
            previous = group.children.get(member.sid)
            if previous is None or member.rank() > previous.transcript.rank():
                group.children[member.sid] = Teammate(member, name, parent_name or None)

    legacy_tasks: dict[str, list[dict[str, Any]]] = {}
    for sid, entries in tasks.items():
        owner = task_owner(sid) if show_all or sid[:8] in reached else None
        if owner is None and len(sid) <= 8:
            # A prefix-only task can keep the existing board row visible even
            # when it cannot establish which teammate owns it.
            legacy_tasks[sid] = entries
            continue
        key = owner.sid if owner is not None else sid
        groups.setdefault(folded_into.get(key, key), SessionGroup()).tasks.extend(entries)

    def group_rank(group: SessionGroup) -> tuple[float, bool, float, float]:
        source_rank = (0.0, 0.0, 0.0)
        if group.source is not None:
            source_rank = (
                group.source.rank() if group.resumable else (group.source.worker_mtime, 0, 0)
            )
        activity = runtime_sessions.newest_plausible(
            config,
            now,
            chain(
                (source_rank[0],),
                (child.transcript.activity for child in group.children.values()),
                (task["updated"] for task in group.tasks),
            ),
        )
        return activity, group.source is not None, source_rank[1], source_rank[2]

    winners: dict[str, str] = {}
    for sid, group in groups.items():
        prefix = sid[:8]
        if prefix not in winners or group_rank(group) > group_rank(groups[winners[prefix]]):
            winners[prefix] = sid
    rows = {prefix: groups[sid] for prefix, sid in winners.items()}
    for sid, group in groups.items():
        prefix = sid[:8]
        winner = winners[prefix]
        if sid == winner:
            continue
        group_workers = chain(
            group.source.workers if group.source is not None else (),
            (worker for child in group.children.values() for worker in child.transcript.workers),
        )
        if any(working(mtime) for _, mtime in group_workers) or any(
            fresh(task["updated"]) for task in group.tasks
        ):
            # Keep the short key for the normal winner when possible. Folding a
            # displaced roster into that row would attribute work to another UUID.
            if sid == prefix:
                rows[winner] = rows[prefix]
            rows[sid] = group
    for prefix, entries in legacy_tasks.items():
        rows.setdefault(prefix, SessionGroup()).tasks.extend(entries)
    return rows


def collect(
    config: RuntimeConfig,
    state: RuntimeState,
    now: float,
    window_hours: float,
    show_all: bool,
) -> list[Session]:
    window_sec = window_hours * 3600
    paths = runtime_io.glob_stores(config, "claude.projects", "*", "*.jsonl")
    with state.cache_lock:
        for removed in state.claude_subagent_index.keys() - paths:
            state.claude_subagent_index.pop(removed, None)
    # The resolver sees these stems before the collector discards archive and metadata rows.
    prefixes = Counter(os.path.basename(path).removesuffix(".jsonl")[:8] for path in paths)
    state.claude_transcript_collisions = frozenset(
        sid for sid, count in prefixes.items() if count > 1
    )
    groups = session_groups(config, state, now, window_sec, show_all, paths)
    team_members = load_team_members(config)

    out: list[Session] = []
    for prefix, group in groups.items():
        source = group.source
        transcript = source.path if group.resumable and source else None
        transcript_mtime = source.mtime if transcript and source else 0
        tasks = sorted(
            group.tasks,
            key=lambda t: int(t["id"]) if str(t["id"]).isdigit() else 0,
        )
        # On an orphan team row the display source is already in the roster.
        agent_files = source.workers if source and source.sid not in group.children else []
        children = list(group.children.values())
        # One analysis per child transcript, read once and shared by everything
        # below that wants it: the session's output rate, and the model published
        # beside each running subagent's label. The two select on different
        # windows — `rate_window_sec` for the rate, `working_threshold_sec` for
        # the pills — so the union of the windows is what keeps this at one read
        # per file whichever of them a given child falls inside. `is_fresh` is
        # monotone in its window, so the wider window *is* the union; this must
        # not become a check against `working_threshold_sec` alone, because
        # nothing enforces that it is the smaller of the two.
        child_files = [*agent_files, *((c.transcript.path, c.transcript.mtime) for c in children)]
        analyses = {
            path: claude_data.analyze_transcript(config, state, path)
            for path, mtime in child_files
            if runtime_sessions.is_fresh(
                config, now, mtime, max(config.rate_window_sec, config.working_threshold_sec)
            )
        }
        models = {path: child_model(analysis) for path, analysis in analyses.items()}
        # One bounded head read per child, shared by the two lists below and
        # cached across passes. The cache is the point, and the first version of
        # this comment defended not having one by answering the wrong question:
        # within a pass the read happens once anyway, while the cost that
        # actually recurs is per COLLECTION. Measured on a store with 8 finished
        # teammates of 20 workers each: 170 head reads and 160 sidecar parses
        # every pass, for a roster 91% of which was inactive. A start stamp is
        # immutable once a file has it, which is the same property
        # `agent_identity` and `agent_setting` already cache on over the same
        # head bytes.
        child_started = {
            c.transcript.path: claude_data.transcript_started_at(
                config, c.transcript.path, state=state
            )
            for c in children
        }
        # Retained inside the display window with `active` per agent, the same
        # rule the children and grandchildren below already follow
        # (captain-ruling 2026-09-03: a lens the LEAD dispatched was still
        # fresh-gated, so it vanished at 90 s while a teammate's did not). The
        # state derivation takes the running ones straight back out, so the two
        # lists retain the measured distinction. See
        # [unchanged-state capture](docs/captures/README.md#files).
        member_flags = {
            key: m["active"]
            for m in team_members.get(prefix, [])
            for key in (m["label"], m["agent_id"], m["local"])
        }
        child_is_live: dict[str, bool] = {}
        for c in children:
            name = c.name
            has_live_grandchild = any(
                runtime_sessions.is_fresh(config, now, gm, config.working_threshold_sec)
                for _, gm in c.transcript.workers
            )
            live = (
                runtime_sessions.is_fresh(
                    config, now, c.transcript.mtime, config.working_threshold_sec
                )
                or has_live_grandchild
            )
            # Demote only. A retained-but-finished member is marked inactive and
            # that is worth believing; the reverse is not, because the flag on a
            # hard-killed pane is unmeasured and DRC-4229 keeps transcript
            # freshness authoritative for "running now".
            if live and member_flags.get(name) is False:
                live = False
            child_is_live[c.transcript.path] = live

        own_agents = load_subagents(
            config,
            transcript,
            now,
            found=agent_files,
            models=models,
            window_sec=window_hours * 3600,
            state=state,
        )
        subagents = [
            *(a for a in own_agents if a["active"]),
            *(
                {
                    "label": c.name or "subagent",
                    "model": models.get(c.transcript.path),
                    "started_at": child_started[c.transcript.path],
                }
                for c in children
                if child_is_live[c.transcript.path]  # fresh = running
            ),
        ]
        # A workflow can park the lead's transcript for hours. Its workers'
        # writes still count after they stop qualifying as running.
        task_and_worker_activity = runtime_sessions.newest_plausible(
            config,
            now,
            chain(
                (task["updated"] for task in tasks),
                (mtime for _, mtime in child_files),
                (mtime for c in children for _, mtime in c.transcript.workers),
            ),
        )
        last_activity = runtime_sessions.newest_plausible(
            config, now, (transcript_mtime, task_and_worker_activity)
        )
        active = runtime_sessions.is_fresh(config, now, last_activity, window_hours * 3600)
        if not (active or show_all):
            continue

        cwd = claude_data.session_cwd(config, state, source.path) if source else ""
        # Registered, joined long enough ago that a healthy agent would have
        # written its first record, and still holding no transcript anywhere.
        # Sandwiched between two windows that already exist rather than a
        # threshold of its own: `working_threshold_sec` below, so a normal
        # fan-out does not flash a red band during the seconds every member
        # takes to start; `window_hours` above, so the roster can never
        # resurrect a row the board would not otherwise be showing. The
        # registry's own mtime cannot do either job -- one stamp covers all
        # members and moves only on a join or a leave.
        started_ids = started_agent_ids(prefix, children, [p for p, _ in agent_files])
        pending_members = [
            m
            for m in team_members.get(prefix, [])
            if m["agent_id"] not in started_ids
            and m["local"] not in started_ids
            and not runtime_sessions.is_fresh(
                config, now, m["joined"], config.working_threshold_sec
            )
            and runtime_sessions.is_fresh(config, now, m["joined"], window_hours * 3600)
        ]
        pending_members.sort(key=lambda m: m["joined"])

        # The published roster is deliberately NOT the list above. Everything
        # that derives state -- the Working pin, `working_detail`, the Spacedock
        # strip -- keeps reading `subagents`, which is gated on
        # `working_threshold_sec` because DRC-4118 settled that a child parked
        # hours ago must not make its parent read "running 1 subagent", and
        # DRC-4263 requires it. A teammate blocked on its own subagents writes
        # nothing for minutes; DRC-4346 absorbs its live grandchild workers'
        # activity into the teammate's liveness and this session's activity,
        # so the teammate reads as active and the lead reads as working while
        # its workers are running.
        roster: list[dict[str, Any]] = [
            published_agent(
                a["label"],
                model=a["model"],
                started_at=a["started_at"],
                active=a["active"],
                parent=None,
            )
            for a in own_agents
        ]
        for c in children:
            name = c.name
            roster.append(
                published_agent(
                    c.name or "subagent",
                    model=models.get(c.transcript.path),
                    started_at=child_started[c.transcript.path],
                    active=child_is_live[c.transcript.path],
                    parent=c.parent,
                )
            )
            # A teammate's own subagents, flattened onto the roster rather than
            # nested under it. Flattening is the rule this codebase already
            # follows -- Antigravity flattens a whole subtree onto the root card,
            # and DRC-4118 chose `rootParentAgentId` because flattening cannot
            # orphan a grandchild into a peer row. They reach the roster only:
            # counting them into `subagents` would make a lead running one
            # teammate read as running eight.
            for gp, gm in c.transcript.workers:
                if not runtime_sessions.is_fresh(config, now, gm, window_hours * 3600):
                    continue
                roster.append(
                    published_agent(
                        agent_label(gp),
                        # Never guessed from the parent: no analysis is run over a
                        # grandchild, so None here means not read.
                        model=None,
                        started_at=claude_data.transcript_started_at(config, gp, state=state),
                        active=runtime_sessions.is_fresh(
                            config, now, gm, config.working_threshold_sec
                        ),
                        parent=name or None,
                    )
                )
        roster += [
            published_agent(
                m["label"], model=None, started_at=m["joined"], active=False, parent=None
            )
            for m in pending_members
        ]

        project = (
            (
                runtime_sessions.project_from_cwd(config, cwd)
                # Lossy fallback: the encoded name cannot be split back into
                # segments, so it is capped at two rather than published whole.
                or runtime_sessions.bounded_project_label(
                    config, os.path.basename(os.path.dirname(source.path))
                )
            )
            if source
            else "unknown"
        )
        # Sampled before analyze_transcript: that scan is the slow part, and a
        # SessionEnd landing during it must invalidate everything derived here.
        seen_generation = notifications.hook_generation(state, prefix)
        info = (
            claude_data.analyze_transcript(config, state, transcript)
            if (transcript and active)
            else None
        )
        session_goal = (
            claude_data.session_goal(config, state, transcript) if info and transcript else None
        )
        entrypoint = (
            claude_data.session_entrypoint(state, transcript).published()
            if info and transcript
            else {}
        )
        delegated, newest_unpaired, waiting_count = project_context.delegated_work_status(
            config,
            transcript if active else None,
            own_activity=(info or {}).get("last_conversation_ts") or 0,
            now=now,
            state=state,
            child_paths=[path for path, _mtime in agent_files],
        )
        work_in_flight_until, in_flight_detail = in_flight_work(
            config,
            now,
            info,
            waiting_count,
            # Only headless parents may wait past Stop for their background tasks.
            newest_unpaired if entrypoint.get("headless") is True else None,
        )

        # A conversation record can distinguish real work from Claude's
        # post-turn transcript writes (DRC-4770). Task and worker writes still
        # retire the stop, as does the transcript mtime when there is no
        # conversation record to go by (DRC-4101).
        work_activity = runtime_sessions.newest_plausible(
            config,
            now,
            (
                (info or {}).get("last_conversation_ts") or transcript_mtime,
                task_and_worker_activity,
            ),
        )
        session_state, state_detail = "idle", "awaiting your message"
        blocked_since = None
        # mtime floor: match the other collectors when the newest write has
        # no parseable timestamp (partial line, untimestamped record)
        parsed_last_event = info["last_event_ts"] if info else 0
        last_event_sources = (parsed_last_event, transcript_mtime)
        hook = (
            notifications.current_hook(
                state, prefix, (info or {}).get("last_user_event"), parsed_last_event
            )
            if active
            else None
        )
        # Whether the standing hook is a prompt this build recognises. Only a
        # recognised one is allowed to outrank a live subagent below.
        actionable_prompt = notifications.hook_is_actionable_prompt(hook)
        if info and info["pending_input_tool"]:
            p = info["pending_input_tool"]
            session_state = "needs_input"
            blocked_since = p["ts"] or last_activity
            waited = (
                runtime_sessions.fmt_duration(runtime_sessions.age(config, now, p["ts"]))
                if p["ts"]
                else "?"
            )
            # The question itself when the record carried it, the tool's name when
            # it did not. Both happen: the record reaches disk on no schedule, so
            # this reads as one or the other rather than appearing and vanishing
            # for the same session. See
            # [N-4](docs/design-needs-input.md#n-4).
            asks = p.get("asks") or ""
            state_detail = (
                f"{asks}, waiting {waited}"
                if asks
                else f"open question ({p['name']}), waiting {waited}"
            )
        # A member that was dispatched and never started outranks Working, and
        # it is deliberately the second test rather than the first: an open
        # AskUserQuestion names the actual question, which is the better line to
        # put in front of the operator when both are true. It outranks Working
        # because the session going on being busy is what hides this -- the
        # observation that opened DRC-4263 was three agents parked on a startup
        # permission prompt for 22 minutes while their lead read as working, and
        # then as idle, and finally as nothing at all.
        elif pending_members:
            session_state = "needs_input"
            blocked_since = pending_members[0]["joined"]
            wait_age = runtime_sessions.age(config, now, blocked_since)
            # joinedAt has millisecond precision, so absorb only float conversion noise.
            waited = runtime_sessions.fmt_duration(
                wait_age + 1e-6 if wait_age is not None else None
            )
            state_detail = (
                # The label arrives unbounded (see `load_team_members`), and
                # this is the one place besides the element where a registry
                # name reaches the payload. `redact_clip` rather than a slice
                # for the reason that function owns: a cut landing inside a
                # credential leaves a run too short for the sweep downstream
                # to match.
                f"{records.redact_clip(pending_members[0]['label'], 70)}"
                f" has not started, waiting {waited}"
                if len(pending_members) == 1
                else f"{len(pending_members)} subagents have not started, waiting {waited}"
            )
        elif in_flight_detail and not hook:
            session_state, state_detail = "working", in_flight_detail
        # Fresh activity in the session's *own* transcript still beats a hook:
        # Claude Code emits "waiting for your input" notifications for sessions
        # that keep running via background tasks and will resume on their own.
        # That window self-clears, because an open prompt leaves the parent
        # transcript quiet, so a genuinely blocked session falls out of the window
        # and surfaces. The quiet does not rest on the tool_use record being
        # written ahead of the prompt: it is written on no schedule at all, and a
        # record that never arrives leaves the file quieter still. See
        # [N-2](docs/design-needs-input.md#n-2).
        #
        # A live subagent is different, and used to be tested here as if it were
        # the same. It never lapses: one running subagent pinned this branch for
        # as long as the workflow ran, so on a fan-out -- the sessions most likely
        # to be holding a prompt -- a recognised prompt could not surface at all.
        # It now yields to one. An unrecognised hook still waits for quiet, so a
        # notification type added upstream cannot invent a red band here.
        elif runtime_sessions.is_fresh(
            config,
            now,
            runtime_sessions.newest_plausible(config, now, last_event_sources),
            config.working_threshold_sec,
        ) or (subagents and not actionable_prompt):
            session_state = "working"
            in_prog = next((t for t in tasks if t["status"] == "in_progress"), None)
            if in_prog:
                state_detail = (in_prog["activeForm"] or in_prog["subject"]) + "…"
            else:
                state_detail = runtime_sessions.working_detail(info, subagents)
        elif hook:
            session_state = "needs_input"
            blocked_since = hook["ts"]
            state_detail = hook["message"] or "waiting for your input"
        if (
            session_state == "needs_input"
            and notifications.hook_generation(state, prefix) != seen_generation
        ):
            # The session exited while this snapshot was being built. Applies to
            # the transcript-detected case too: an unanswered AskUserQuestion in
            # a session the user has quit is moot, not blocking.
            session_state, blocked_since = "idle", None
            state_detail = "awaiting your message"
        turn_end_at = transcript_turn_end(
            config,
            info,
            transcript or "",
            work_activity=work_activity,
            blocked=session_state == "needs_input"
            or bool(pending_members or subagents or work_in_flight_until),
        )
        if turn_end_at is not None:
            # Settled as a hook Stop settles through the idle overlay: the turn
            # finished, so the stop record's own write does not keep the row
            # Working for `working_threshold_sec`. A hook `turn_started` still
            # wins, because overlays apply after this.
            session_state, state_detail = "idle", "awaiting your message"
        elif session_state == "idle":
            # Claude Code records a finished turn itself, so an idle row
            # without one may still be mid-turn: an interruption, an open tool
            # call, a subagent. "Awaiting your message" beside Drift's "last
            # turn isn't recorded as finished" told the reader both (verifier
            # F3). A hook Stop's idle overlay clears this, as it clears any
            # detail, and the row then carries its observed stop.
            state_detail = "last turn not recorded as finished"

        total = len(tasks)
        done = sum(1 for t in tasks if t["status"] == "completed")
        open_count = total - done
        durations = [
            t["updated"] - t["created"]
            for t in tasks
            if t["status"] == "completed" and (t["updated"] - t["created"]) >= 30
        ]
        eta_sec = (
            (sum(durations) / len(durations)) * open_count if durations and open_count else None
        )

        for t in tasks:
            elapsed = (
                (t["updated"] - t["created"])
                if t["status"] == "completed"
                else runtime_sessions.age(config, now, t["created"])
            )
            t["elapsed_h"] = runtime_sessions.fmt_duration(elapsed)
            t["updated_ago"] = (
                runtime_sessions.fmt_duration(runtime_sessions.age(config, now, t["updated"]))
                + " ago"
            )

        # One scan, read twice: the turn estimate and the failure run come out of
        # the same incremental state, and calling the scanner again would advance
        # its position past the records the second reading needs.
        scan = (
            runtime_turns.scan_turns(config, state, transcript, "claude")
            if (info and transcript)
            else None
        )
        published_roster, subagents_omitted = runtime_sessions.cap_subagents_roster(roster)
        s = runtime_sessions.base_session("claude", prefix, project)
        runtime_sessions.apply_project_identity(config, s, cwd)
        s.update(
            {
                # The transcript's own stem is the session id `claude --resume`
                # takes. The usual eight-character board key is too short for
                # the CLI. Use the chosen transcript even when its prefix is
                # shared. A task-only row has no transcript to resume.
                "resume_id": (
                    runtime_sessions.resume_token(
                        os.path.basename(transcript).removesuffix(".jsonl")
                    )
                    if transcript
                    else None
                ),
                "title": (info or {}).get("title"),
                **(
                    runtime_transcripts.first_prompt(config, state, transcript, "claude")
                    if info and transcript
                    else {}
                ),
                # The session's own `/goal`, from its record. Behind the same guard as the
                # prompt above, so a row the transcript was not read for publishes none.
                "session_goal": session_goal,
                **entrypoint,
                # How that goal ended, from the same read of the same cache entry, so after it.
                # Keys of their own, never the goal's: the goal stays None after either, and
                # None here is "not seen", which is not "did not happen".
                "session_goal_cleared": (
                    claude_data.session_goal_cleared(state, transcript)
                    if info and transcript
                    else None
                ),
                "session_goal_gave_up": (
                    claude_data.session_goal_gave_up(state, transcript)
                    if info and transcript
                    else None
                ),
                # Line 1 above is the session's identity — the `ai-title`, fixed
                # before the second prompt on 200 of 204 long sessions — and this
                # is the line that says what it is doing now. Behind the same
                # guard as the analysis, so an unread row reports nothing rather
                # than something old.
                "instruction": (
                    claude_data.session_instruction(config, state, transcript)
                    if (info and transcript)
                    else None
                ),
                # The session's own model, from the non-sidechain half of the
                # analysis: an inactive session is not analyzed at all and
                # publishes None, which is "not read" and not "no model".
                "model": (info or {}).get("model"),
                "last_prompt": records.redact_clip(
                    (info or {}).get("last_prompt") or "", records.LAST_PROMPT_CAP_CHARS
                ),
                "state": session_state,
                "state_detail": state_detail,
                "blocked_since": blocked_since,
                "turn_end_at": turn_end_at,
                "work_in_flight_until": work_in_flight_until,
                **delegated,
                "active": active,
                "last_activity": last_activity,
                "work_activity": work_activity,
                # The parent transcript alone, deliberately excluded from the
                # subagent and task mtimes folded into `last_activity` above:
                # this is what tells a resumed turn from a background agent
                # writing while a permission prompt is still open (DRC-4097).
                #
                # The agent's own records, not the file's mtime, and the
                # difference is the whole point. A parked transcript still
                # receives `queue-operation` and `attachment` records when a
                # background task finishes, so mtime answers "did anything
                # write" when the reducer is asking "did the agent resume".
                # Read as mtime, one background task completing retired a live
                # question for the rest of its life: the row published
                # `working` while the session sat on an open gate, and the
                # Needs-you tile counted zero. A transcript with no assistant
                # record in its tail reports 0, which leaves the wait standing
                # — the safe direction, and the same one an unreported value
                # already takes in the reducer.
                "own_activity": (info or {}).get("last_assistant_ts") or 0,
                "started_at": runtime_turns.started_at(scan),
                # Subagent output lives in the children's own transcripts; fold
                # it in so the session's rate reflects all its work. Read from
                # `analyses` rather than re-analyzing: both layouts are in there
                # already, and a second pass over the same file per refresh is
                # the cost this map exists to avoid.
                "rate_per_min": runtime_sessions.rate_from(info, now, config)
                + sum(
                    runtime_sessions.rate_from(analyses[path], now, config)
                    for path, mtime in child_files
                    if runtime_sessions.is_fresh(config, now, mtime, config.rate_window_sec)
                ),
                "session_output_tokens": (scan.get("session_output_tokens") if scan else None),
                "turn_output_tokens": scan.get("turn_output_tokens") if scan else None,
                "total": total,
                "done": done,
                "open": open_count,
                "progress_pct": round(done * 100 / total) if total else 0,
                "eta_h": runtime_sessions.fmt_duration(eta_sec) if eta_sec else None,
                "turn": runtime_turns.turn_progress(scan, session_state, now, config),
                "loop": runtime_turns.loop_signal(scan, config),
                # Registered-but-unstarted members are published beside the
                # running ones and nowhere else: they carry no mtime that
                # advances, so folding them into `last_activity` or into the
                # Working test would let a roster entry stand in for work that
                # has demonstrably not begun. `started_at` is when the member
                # joined the team, which is the instant the wait began.
                # Capped at SUBAGENTS_ROSTER_CAP with live entries prioritized
                # ahead of finished entries (DRC-4348).
                "subagents": published_roster,
                "subagents_omitted": subagents_omitted,
                "tasks": tasks,
                "spacedock": session_spacedock(
                    config, state, transcript, subagents, now, window_hours * 3600
                ),
            }
        )
        out.append(s)
    return out
