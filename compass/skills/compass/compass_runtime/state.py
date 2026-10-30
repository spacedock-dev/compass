"""Mutable process state owned by one Compass runtime."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict

from compass_runtime import asks as runtime_asks
from compass_runtime import git_status as runtime_git_status
from compass_runtime import snapshot as runtime_snapshot
from compass_runtime import stream as runtime_stream

if TYPE_CHECKING:
    from _thread import LockType

    from compass_runtime.config import RuntimeConfig


class UsageFetchEntry(TypedDict):
    ts: float
    entries: list[dict[str, Any]]


@dataclass
class RuntimeState:
    config: RuntimeConfig
    server_started: float
    # The published responses live here rather than on the Application, exactly
    # where the memo they replace lived. Two applications over one state must
    # share one scan: that single-flight property is what stops concurrent tabs
    # stampeding a cold entry, and it is a property of the runtime, not of the
    # object that happens to serve a request.
    snapshot: runtime_snapshot.Snapshot = field(init=False)
    # Connected SSE clients, owned here for the same reason the snapshot is:
    # they belong to the runtime, not to whichever object serves a request.
    streams: runtime_stream.StreamRegistry = field(init=False)
    # Outstanding questions a session asked, owned here for the reason the
    # streams are: they belong to the runtime, not to whichever object serves a
    # request. No `ask_lock` beside this one -- the registry owns its own, and a
    # second lock at this level would only invite a caller to hold the wrong one.
    asks: runtime_asks.AskRegistry = field(init=False)
    hook_lock: LockType = field(default_factory=threading.Lock)
    reach_lock: LockType = field(default_factory=threading.Lock)
    last_reach_time: float = 0.0
    last_reach_counts: tuple[int, int] | None = None
    cache_lock: LockType = field(default_factory=threading.Lock)
    scanner_lock: LockType = field(default_factory=threading.Lock)
    semantic_history_lock: LockType = field(default_factory=threading.Lock)
    # Named for the memo it used to guard, and still doing that memo's real job:
    # held across collection so concurrent readers share one filesystem and
    # SQLite scan. The published bytes moved to `snapshot`, which has its own
    # lock and never holds it across a collection or a socket write.
    collect_memo_lock: LockType = field(default_factory=threading.Lock)
    hook_notifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    last_popup: dict[str, float] = field(default_factory=dict)
    last_popup_message: dict[str, tuple[str, float]] = field(default_factory=dict)
    last_session_state: dict[str, str] = field(default_factory=dict)
    hook_generation: dict[str, int] = field(default_factory=dict)
    store_errors: dict[str, str] = field(default_factory=dict)
    metadata_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    claude_title_cache: dict[str, tuple[int, int, str | None]] = field(default_factory=dict)
    claude_user_event_cache: dict[str, tuple[int, int, str | None]] = field(default_factory=dict)
    # One message index per transcript (`entry_numbers.MessageIndex`), keyed by its path, harness
    # and session. Typed `Any` because `state` imports no module that could name it without a cycle.
    entry_indexes: dict[str, Any] = field(default_factory=dict)
    entry_index_lock: LockType = field(default_factory=threading.Lock)
    session_outlines: dict[str, Any] = field(default_factory=dict)
    session_outline_lock: LockType = field(default_factory=threading.Lock)
    # "harness:sid" -> the latest summary job this process knows, bounded by max_cache_entries.
    summary_jobs: dict[str, Any] = field(default_factory=dict)
    # (harness, sid) -> (source stamps and stored record identity, out-of-date report).
    summary_freshness: dict[tuple[str, str], Any] = field(default_factory=dict)
    summary_freshness_lock: LockType = field(default_factory=threading.Lock)
    transcript_user_cache: dict[
        tuple[str, str, str], tuple[tuple[int, int, int, int], list[dict[str, Any]]]
    ] = field(default_factory=dict)
    # transcript path -> ((mtime_ns, size), the published instruction reading).
    # Both are `bounded_put` at `config.max_cache_entries`, like every cache
    # above them.
    #
    # What these do NOT do is spare a live session: the key moves on every event,
    # and a live session is the whole point of the field. They pay for the
    # opposite case — an idle or `?all=1` row re-read on each refresh, where the
    # walk is over a file that stopped changing — and that is the population
    # where the walk is long, because it reaches back through a finished turn.
    codex_instruction_cache: dict[str, tuple[int, int, dict[str, Any]]] = field(
        default_factory=dict
    )
    claude_instruction_cache: dict[str, tuple[int, int, dict[str, Any] | None]] = field(
        default_factory=dict
    )
    # Same key and the same reasoning as `codex_instruction_cache` above, and a
    # separate entry rather than a key inside it: the plan walk stops at the
    # newest `update_plan` and the instruction walk at the newest prompt, so one
    # of them reaching its record says nothing about how far the other must go.
    codex_plan_cache: dict[str, tuple[int, int, list[dict[str, Any]]]] = field(default_factory=dict)
    # Same key and lock as the two caches above, for a read duplicated WITHIN
    # one cycle rather than across cycles: `Application.collect` calls
    # `spec.collect` and then `spec.usage` back to back, and Codex's two readers
    # overlap on any rollout that is both active and among the eight newest.
    # Only those files are ever analyzed, so the live entry count is the active
    # sessions plus at most eight and never approaches `max_cache_entries`.
    codex_analysis_cache: dict[str, tuple[int, int, dict[str, Any]]] = field(default_factory=dict)
    # sess_dir -> (directory mtimes, subagent transcript paths). A subagent tree
    # whose directory mtimes have not moved cannot have gained or lost a
    # transcript, so only the glob is memoised; mtimes are restated on every
    # read because appending to a transcript moves no directory. Keying on
    # directory mtimes rather than on a freshness window keeps a parked
    # parent's subagents visible.
    claude_subagent_cache: dict[str, tuple[tuple[float, ...], list[str]]] = field(
        default_factory=dict
    )
    # (rollout path, the bounds a read depends on) -> (stamps of the root and every child, expiry,
    # the read). See `project_context.CODEX_CHECK_CACHE_SEC`; `bounded_put` at its own small limit.
    codex_check_cache: dict[Any, Any] = field(default_factory=dict)
    # (the store directories' mtimes, every child rollout by its root's session id), so a collect
    # and a press list no store per session. See `observer.codex_child_rollouts`.
    codex_child_index: tuple[tuple[Any, ...], dict[str, list[str]]] | None = None
    delegated_work_cache: dict[
        str, tuple[tuple[tuple[str, int, int], ...], list[dict[str, Any]], bool, float]
    ] = field(default_factory=dict)
    # A folder's `origin`, so a session holding a CI poll starts no git on a collect or a live
    # replay that finds its repository unchanged (`ci_read.folder_remote`).
    ci_remotes: runtime_git_status.StampCache = field(default_factory=runtime_git_status.StampCache)
    cwd_cache: dict[str, str] = field(default_factory=dict)
    pi_scan: dict[str, dict[str, Any]] = field(default_factory=dict)
    turn_scan: dict[str, Any] = field(default_factory=dict)
    agent_class_cache: dict[str, tuple[bool, str, str]] = field(default_factory=dict)
    # path -> ((mtime_ns, size), has a conversation). True is final because a
    # transcript only appends; False is re-read once the stat moves (DRC-4645).
    conversation_cache: dict[str, tuple[tuple[int, int], bool]] = field(default_factory=dict)
    spacedock_role_cache: dict[str, str] = field(default_factory=dict)
    # path -> ((mtime_ns, size), the start stamp or None). It joined the two
    # above when DRC-4344 widened the published roster past the freshness gate:
    # the roster then re-read a head per child and per grandchild on every
    # collection, measured at 170 reads a pass for a roster 91% inactive.
    # Stat-keyed rather than path-keyed, unlike `agent_class_cache` beside it,
    # because a start stamp is fixed only once the file HAS one -- a teammate
    # parked before its first turn has none, and that null is exactly the answer
    # worth remembering. Path-keying forced the null to be recomputed forever.
    agent_start_cache: dict[str, tuple[tuple[int, int], float | None]] = field(default_factory=dict)
    spacedock_boot_cache: dict[str, tuple[list[dict[str, Any]], int]] = field(default_factory=dict)
    spacedock_workflow_cache: dict[tuple[str, int, int, int, int, int], dict[str, Any] | None] = (
        field(default_factory=dict)
    )
    # Canonical project root -> (observation time, detached discovery result).
    # The command is bounded, but it is still a subprocess; one project-context
    # poll must not spawn it again while its project declaration has not aged
    # past the short observation floor.
    spacedock_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = field(default_factory=dict)
    spacedock_entity_cache: dict[tuple[str, int, int], str] = field(default_factory=dict)
    cursor_metadata_cache: dict[str, tuple[float, str | None, str]] = field(default_factory=dict)
    # The quota fetch. One cache entry per vendor key, stamped with the fetch
    # time so the five-minute floor is a comparison, and one in-flight marker
    # per vendor so a slow request cannot stack a second behind it. Guarded by
    # usage_fetch_lock, never cache_lock: the fetch thread holds its lock
    # across a cache write only, and must not contend with collectors.
    usage_fetch_lock: LockType = field(default_factory=threading.Lock)
    usage_fetch_cache: dict[str, UsageFetchEntry] = field(default_factory=dict)
    usage_fetch_inflight: set[str] = field(default_factory=set)
    # Receipts pushed in by a harness's own status-line command, keyed the same
    # way and guarded by the same lock: one cache, two ways to fill it. In
    # memory only, so Compass's two written paths are unchanged.
    usage_receipts: dict[str, UsageFetchEntry] = field(default_factory=dict)
    # Successive quota readings per vendor window, keyed "<harness>:<slot>", for
    # the recent-pace figure. One ring per key rather than one shared ring, and
    # that is the load-bearing part: `POST /api/usage` has no rate limit, so a
    # harness pushing receipts in a loop would evict the fetched Claude samples
    # the pace exists to read. Each ring is created with its bound on first
    # append, where `config` is in scope. Guarded by `usage_fetch_lock`, the same
    # lock the two caches these are derived from already use.
    usage_samples: dict[str, deque[tuple[float, int]]] = field(default_factory=dict)
    # State disputes: an overlay overruling a collector that had found a wait.
    # A running total that never resets, so a machine can report "this happened
    # 40 times" long after the ring has turned over, plus the ring itself. The
    # lock is its own for the reason `usage_fetch_lock` is: this is written
    # inside a collection and read by a request handler, and neither should wait
    # on the other's cache work.
    # The sessions the reader marked handled, as this process last read them off
    # disk. `None` means no collection has run yet, which is not the same claim
    # as "nothing is cleared": the notification path can fire first, and an empty
    # tuple there would raise a popup for a session already handled.
    #
    # Its own lock, for the reason `dispute_lock` has one: it is written by a
    # request handler and read inside a collection, and neither should wait on the
    # other's cache work. The file, not this tuple, is the record — a second
    # dashboard's write is picked up by the next `dismissals.refresh`.
    tripwire_lock: LockType = field(default_factory=threading.Lock)
    tripwire_memory: dict[str, Any] = field(default_factory=dict)
    dismissal_lock: LockType = field(default_factory=threading.Lock)
    dismissals: tuple[dict[str, Any], ...] | None = None
    # The reader's typed goal and expected output per session. Its own lock for
    # `dismissal_lock`'s reason, and `None` distinguishes "not loaded yet" from
    # "nobody has annotated anything", which the render treats differently: the
    # first is unknown and the second is an absence with a reason.
    annotation_lock: LockType = field(default_factory=threading.Lock)
    annotations: tuple[dict[str, Any], ...] | None = None
    # Whether the last read of the annotation store could read it whole. False
    # means a file exists this build cannot read, which the board says rather
    # than showing every session as one nobody typed against.
    annotations_trusted: bool = True
    # Moved by every write to `annotations` a save or a locked read makes, so a
    # `refresh` whose read began before one does not put the older copy over it.
    annotation_generation: int = 0
    # When a dashboard tab last reported a working notification lane in itself,
    # under
    # [DEC-19](docs/design-reading-a-session.md#dec-19-the-page-may-report-a-lane-never-a-delivery).
    # One float for the whole board and never a session: the page
    # may report that a lane EXISTS and may never report a delivery, so there is
    # nothing here to key by session.
    #
    # In memory, unlike the delivery record beside it, and the difference is the
    # claim each one makes. A delivery outcome is a fact about a raise that
    # happened and must survive a restart. This is a fact about a tab that was
    # open, and a restarted server has no open tabs it knows of; the page
    # re-reports when the payload disagrees with what it can see, so the truth
    # comes back rather than being remembered wrongly.
    lane_lock: LockType = field(default_factory=threading.Lock)
    lane_reported_at: float = 0.0
    # The unasked reading lane. `unasked_seen` is the last state each row was
    # observed in, which is what makes an evaluation fire on a CHANGE rather
    # than per collection; `unasked_inflight` holds the board's one reading slot;
    # `unasked_last` is the per-session floor a cap is not.
    #
    # In memory and bounded like the caches above, which is right for all three:
    # a restart means the board has observed nothing yet, and the first
    # collection after one must not read as a transition on every row. The
    # DEPARTURES survive a restart, in `departures.py`, because they are what
    # the reader came back for.
    unasked_lock: LockType = field(default_factory=threading.Lock)
    unasked_seen: dict[str, str] = field(default_factory=dict)
    unasked_inflight: set[str] = field(default_factory=set)
    unasked_last: dict[str, float] = field(default_factory=dict)
    dispute_lock: LockType = field(default_factory=threading.Lock)
    dispute_total: int = 0
    disputes: deque[dict[str, Any]] = field(default_factory=deque)
    # The open episode per session: its shape, and the record to update in place
    # while it lasts. Without this a standing disagreement writes one record per
    # collection, so a single 90-second one fills the ring and `dispute_total`
    # counts polls rather than faults.
    dispute_episodes: dict[tuple[str, str], tuple[tuple[str, str, int], dict[str, Any]]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        # Built here rather than by a default_factory because they need fields of
        # this same dataclass: the snapshot needs `server_started`, and the
        # dispute ring needs its bound from `config`.
        self.snapshot = runtime_snapshot.Snapshot(server_started=self.server_started)
        self.streams = runtime_stream.StreamRegistry()
        self.asks = runtime_asks.AskRegistry()
        self.disputes = deque(self.disputes, maxlen=self.config.dispute_log_max)


def build_runtime_state(config: RuntimeConfig, *, started: float) -> RuntimeState:
    return RuntimeState(config=config, server_started=started)


def bounded_put(
    cache: dict[Any, Any],
    key: Any,
    value: Any,
    *,
    limit: int,
) -> None:
    if key not in cache and len(cache) >= limit:
        cache.pop(next(iter(cache)))
    cache[key] = value
