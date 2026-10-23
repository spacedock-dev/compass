"""Explicit immutable configuration for the Compass runtime."""

from __future__ import annotations

import json
import ntpath
import os
import posixpath
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .frontend_dev import DevelopmentFrontend

RECORD_PAGE_MAX_BYTES = 64 * 1024 * 1024
RECORD_PAGE_MAX_SECONDS = 5.0
DIRECTION_SCAN_MAX_BYTES = 64 * 1024 * 1024
DIRECTION_SCAN_MAX_SECONDS = 2.0
# Building a session's message index is one forward pass over its transcript. Measured 2026-10-14:
# 0.25 s for a 29 MB, 6,936-line transcript, so five seconds covers well over a hundred megabytes.
# Past that the build stops, keeps what it read and resumes on the next request, and no position is
# published until it has reached the end of the file.
ENTRY_INDEX_MAX_SECONDS = 5.0
# How many sessions' indexes the runtime keeps. Each holds one time and one id per message.
ENTRY_INDEX_LIMIT = 16
# A summary source may cross the same image-heavy stretches as a press; its time bound is also
# the press's two seconds, with continuation instead of sampling messages out of the middle.
SESSION_SOURCE_PAGE_MAX_BYTES = 64 * 1024 * 1024
SESSION_SOURCE_PAGE_MAX_SECONDS = 2.0
# The share of that time held back from scanning for classifying the calls scanned. A scan that
# spent it all left classification past the deadline, and the page then made no progress.
SESSION_SOURCE_CLASSIFY_SHARE = 0.25
# Reuse the forward index's single-line ceiling: larger records are gaps before any text masking.
SESSION_SOURCE_LINE_MAX_BYTES = 16 * 1024 * 1024
# A focused poll pays much less than a press; a clipped outline names its unread prefix.
SESSION_OUTLINE_MAX_BYTES = 2 * 1024 * 1024
# The head read that keeps a session's first prompt in the outline once the newest window passes it
# (docs/design-session-summary.md#the-outline-always-opens-at-the-first-prompt).
SESSION_OUTLINE_HEAD_BYTES = 256 * 1024
SESSION_OUTLINE_MAX_SECONDS = 0.25
# Keep the focused answer small while retaining several recent turns and three examples per list.
SESSION_OUTLINE_MAX_BLOCKS = 20
SESSION_OUTLINE_HIGHLIGHTS = 3
# Match the message-index cache's session count; only built, word-free outlines are retained.
SESSION_OUTLINE_CACHE_LIMIT = 16

# In docs/design-session-summary.md#proposed-ceilings, thirty windows covered
# the 45 MiB session; 32 leaves room without turning one reader action into an unbounded job.
SESSION_SUMMARY_WINDOW_BYTES = 16_384
SESSION_SUMMARY_MAX_WINDOWS = 32
# The same measurement used 36 calls and 541,407 input bytes; four retries fit beside 32
# windows and a lede, with headroom above the measured maximum prompt and 307-second job.
SESSION_SUMMARY_MAX_CALLS = 37
SESSION_SUMMARY_MAX_BYTES_SENT = 786_432
SESSION_SUMMARY_MAX_SECONDS = 600.0
# Equal to observer.OBSERVER_READING_TIMEOUT_SEC. The job lane wires the timeout; this
# producer passes none to the subprocess path. The slowest measured call took 12.3 seconds.
SESSION_SUMMARY_CALL_TIMEOUT = 180.0
# Separate from Analyze's budget; enforced by the job lane, not the pure producer.
# The proposed ceilings allow about five summaries the size of the largest measured per day.
SESSION_SUMMARY_ROLLING_CAP = 200
# The measurement's output allowance, including complete-phase salvage at a cut reply.
SESSION_SUMMARY_OUTPUT_CAP_BYTES = 64 * 1024
# The measured prompt's closed shape; caps apply independently to each finished block.
SESSION_SUMMARY_MAX_PHASES = 4
SESSION_SUMMARY_MAX_BULLETS = 6
SESSION_SUMMARY_MAX_CITES = 8
SESSION_SUMMARY_TITLE_CHARS = 60
SESSION_SUMMARY_BULLET_CHARS = 200
SESSION_SUMMARY_LEDE_CHARS = 400
# 32 windows x 4 phases x 6 bullets x (200 characters + 8 ordinary fact ids), including
# JSON overhead, fits in 512 KiB at ordinary text widths. A 256 KiB ceiling would cut that
# closed shape even in ASCII; wider text and ids still need whole-block byte gaps.
SESSION_SUMMARY_MAX_BYTES = 512 * 1024

STORE_ENV_VARS = (
    "CLAUDE_CONFIG_DIR",
    "CODEX_HOME",
    "GEMINI_CLI_HOME",
    "COPILOT_HOME",
    "PI_CODING_AGENT_DIR",
    "PI_CODING_AGENT_SESSION_DIR",
)
COMPASS_HOME_ENV = "COMPASS_HOME"


def default_home(home: str, *, windows: bool = False) -> str:
    join = ntpath.join if windows else posixpath.join
    return join(home, ".compass")


def remove_state_file(path: str) -> bool:
    """Remove one state file, True only when it was there and is gone."""
    try:
        os.unlink(path)
    except OSError:
        return False
    return True


CLAUDE_READING_DEFAULT_MODEL: Final = "claude-sonnet-5-5"
CLAUDE_READING_MODEL_POLICY: Final = "sonnet-5-floor-v1"
_CLAUDE_READING_ID = re.compile(
    r"claude-(sonnet|opus)-([1-9][0-9]?)(?:-([1-9][0-9]?))?(?:-([0-9]{8}))?"
)
CLAUDE_READING_FAMILY_RANKS: Final = MappingProxyType({"sonnet": 1, "opus": 2})


def validate_claude_reading_model(value: str) -> str:
    """Admit explicit Sonnet/Opus generation 5 or later, never a floating alias.

    This is the owner's admission policy, not a measured model-quality rank.
    Haiku's generation numbers cannot establish a Sonnet-equivalent tier.
    """
    match = _CLAUDE_READING_ID.fullmatch(value) if isinstance(value, str) else None
    if match is None or int(match[2]) < 5:
        msg = "Choose an explicit Claude Sonnet or Opus generation 5 or later model ID."
        raise ValueError(msg)
    if snapshot := match[4]:
        date.fromisoformat(f"{snapshot[:4]}-{snapshot[4:6]}-{snapshot[6:]}")
    return value


def claude_reading_model_rank(value: str) -> tuple[int, int, int]:
    """Owner-policy generation/minor/family rank; not an accuracy measurement."""
    match = _CLAUDE_READING_ID.fullmatch(validate_claude_reading_model(value))
    if match is None:
        msg = "The model ID has no admitted rank."
        raise ValueError(msg)
    return int(match[2]), int(match[3] or 0), CLAUDE_READING_FAMILY_RANKS[match[1]]


# The Live monitor's own model setting, apart from the reading floor above. The owner pinned an
# explicit Haiku id, defaulting to the newest released one at merge, and the `compass-release`
# pre-flight asks whether a newer Haiku has shipped.
# [DEC-26](docs/design-reading-a-session.md#amended-2026-10-23-owner-the-live-level-comes-from-a-haiku-check)  # noqa: E501
CLAUDE_MONITOR_DEFAULT_MODEL: Final = "claude-haiku-5-5"
CLAUDE_MONITOR_MODEL_POLICY: Final = "haiku-explicit-v1"
_CLAUDE_MONITOR_ID = re.compile(r"claude-haiku-([1-9][0-9]?)(?:-([1-9][0-9]?))?(?:-([0-9]{8}))?")


def validate_claude_monitor_model(value: str) -> str:
    """Admit an explicit Claude Haiku generation 4 or later id, never a floating alias.

    The floor of 4 is the oldest Haiku that is an explicit id of this shape; it is the owner's
    admission policy for a sidecar that never makes a verdict, not a measured quality rank.
    """
    match = _CLAUDE_MONITOR_ID.fullmatch(value) if isinstance(value, str) else None
    if match is None or int(match[1]) < 4:
        msg = "Choose an explicit Claude Haiku model ID, such as claude-haiku-5-5."
        raise ValueError(msg)
    if snapshot := match[3]:
        date.fromisoformat(f"{snapshot[:4]}-{snapshot[4:6]}-{snapshot[6:]}")
    return value


# The history store's two bounds as shipped, and the defaults the two flags that
# override them carry. Named rather than written twice, because `cli.py`'s
# argparse defaults and this module's constructor are the same figure, and
# `SECURITY.md`'s "Retention is 14 days by default, with a size cap, and both
# are configurable" is one assertion about both halves. `spawn_argv` compares
# against these to decide what a daemon respawn has to carry.
HISTORY_RETENTION_DEFAULT_DAYS: Final = 14.0
HISTORY_MAX_BYTES_DEFAULT: Final = 1_048_576
SECONDS_PER_DAY: Final = 24 * 60 * 60
_PATH_TYPE = type(Path())


@dataclass(frozen=True)
class RuntimeConfig:
    home: str
    data_home: str
    store_roots: Mapping[str, tuple[str, ...]]
    platform_name: str
    os_name: str
    state_dir: Path
    # The same location as ``state_dir``, kept verbatim as the user wrote it.
    # A native Path rewrites separators on Windows, so an override of
    # "C:/plugin/state" would come back as "C:\\plugin\\state" — a different
    # string in --status output and in the dirname contract lifecycle relies on.
    state_home: str
    launcher_path: Path
    host: str
    port: int
    frontend_dev: DevelopmentFrontend | None
    window_hours: float
    spacedock_enabled: bool
    tripwires_enabled: bool
    usage_fetch_enabled: bool
    observer_model_enabled: bool
    model_calls_disabled: bool
    claude_reading_model: str
    # Whether the end-of-session git probe runs at all. `--no-git` is the off
    # switch [DEC-3](SECURITY.md#repository-git-reads-the-end-of-session-probe) made part of its
    # ruling, and off means no git command runs and
    # both published fields stay `None` — never a confident clean.
    git_probe_enabled: bool
    # Whether the focus command may run at all. `--no-focus` is the off switch
    # SECURITY.md's focus section made part of the feature, and off means no
    # command runs, no target is recorded, and the page is handed no capability
    # to ask with. `--no-events` turns it off as a side effect, because the
    # capability and the target both come from the observation coordinator, which
    # does not exist under that flag. The session-end store is the second thing
    # `--no-events` switches off, for the same reason and with no flag of its
    # own (decisions.md, DRC-4547): the coordinator is its only writer, so with
    # none it is neither written nor read back (`ends.py`).
    focus_enabled: bool
    irreversible_enabled: bool
    # Whether the dismissal store is read and written at all. `--no-dismiss` is
    # the rollback switch, and off means off in both directions: the file is
    # neither consulted during a collection nor created by a request, so a run
    # that misbehaves leaves no state a later run would honour.
    dismissals_enabled: bool
    # Whether the annotation store is read and written at all. `--no-annotations`
    # is the off switch, and off means off in both directions: the file is
    # neither read during a collection nor created by a request. This one holds
    # prose the reader composed rather than anything a harness published, which
    # is why it gets a switch of its own rather than riding the dismissal one.
    annotations_enabled: bool
    # The unasked reading lane, off by default and the only feature here that
    # spends the reader's model capacity with nobody watching. The ruling that
    # permits it is cited in `unasked.py`, and it gates the lane's DEFAULT on
    # four preconditions rather than its existence: the switch ships off, and
    # the flag is what turns it on.
    unasked_enabled: bool
    # Whether the local history store is read and written at all.
    # `--no-history` is the off switch
    # [DEC-6](SECURITY.md#local-history-the-session-history-store)'s contract made part of the
    # feature, and off means off in both directions: nothing is written and an
    # existing store is not read back, so the board opens with no memory
    # exactly as it did before the store existed. A store still written while
    # the feature is off is a security bug by that contract's own terms.
    history_enabled: bool
    # Whether a session may ask the reader a question and wait for the answer.
    # `--no-ask` is the rollback switch, and off means off in both directions:
    # the routes refuse, and the payload carries no `ask` flag, so the page
    # offers no control rather than one that answers 503.
    ask_enabled: bool
    # Off-machine reach nudges (H2, DRC-4034,
    # [DEC-4](SECURITY.md#off-machine-nudges-reaching-the-operator-away-from-the-desk)).
    # `--no-reach` is the off switch that disables all outbound off-machine nudges for this run.
    reach_enabled: bool
    reach_url: str | None
    reach_cooldown_sec: float
    # Quiet hours notification suppression (DRC-4032).
    # `--no-quiet-hours` is the off switch for this run.
    quiet_hours_enabled: bool
    quiet_hours: str | None
    # The trailing window every published token rate is averaged over. What a
    # row carries is therefore a MEAN and not an instantaneous reading, and at
    # ten minutes it lags a burst by minutes. `sessions.rate_from` divides by it,
    # and the three collectors that sum their own usage events rather than going
    # through it — Codex for a subagent thread, Goose, Antigravity — re-derive the
    # same figure against this same field. The page is told the number rather than
    # having "10 min" written into its markup, so the words on screen and the
    # arithmetic behind them cannot drift apart.
    rate_window_sec: float
    working_threshold_sec: float
    turn_gap_reset_sec: float
    tail_bytes: int
    record_page_max_bytes: int
    record_page_max_seconds: float
    record_page_chunk_bytes: int
    direction_scan_max_bytes: int
    direction_scan_max_seconds: float
    entry_index_max_seconds: float
    entry_index_limit: int
    session_source_page_max_bytes: int
    session_source_page_max_seconds: float
    session_source_classify_share: float
    session_source_line_max_bytes: int
    session_outline_max_bytes: int
    session_outline_head_bytes: int
    session_outline_max_seconds: float
    session_outline_max_blocks: int
    session_outline_highlights: int
    session_outline_cache_limit: int
    session_summary_window_bytes: int
    session_summary_max_windows: int
    session_summary_max_calls: int
    session_summary_max_bytes_sent: int
    session_summary_max_seconds: float
    session_summary_call_timeout: float
    session_summary_rolling_cap: int
    session_summary_output_cap_bytes: int
    session_summary_max_phases: int
    session_summary_max_bullets: int
    session_summary_max_cites: int
    session_summary_title_chars: int
    session_summary_bullet_chars: int
    session_summary_lede_chars: int
    session_summary_max_bytes: int
    # The entry clips the measurement used, not source admission limits; redaction precedes
    # every clip (docs/design-session-summary.md#measurement-and-ceilings).
    session_summary_person_chars: int
    session_summary_agent_chars: int
    session_summary_check_chars: int
    session_summary_path_chars: int
    # One retry for an empty reply; the focused plan's upper bound counts both attempts.
    session_summary_attempts_per_part: int
    # How long a focused freshness answer clipped by the read's time allowance is reused for an
    # unchanged transcript. Re-reading it on every board revision cost about two seconds a poll
    # on 42 and 52 MiB transcripts; never re-reading it would pin a slow-disk answer.
    summary_freshness_retry_sec: float
    # Full UUID session ids fit in 64 characters, as in the annotation store's key contract.
    summary_store_key_cap_chars: int
    # A provider/model identity is tens of characters. The stamp is resent on every focused poll,
    # so an edited file or a buggy caller must not make it kilobytes.
    summary_store_model_stamp_cap_chars: int
    # Match annotation writers: ten seconds bounds one local queue plus the filesystem lock.
    summary_store_lock_wait_sec: float
    summary_store_filename: str
    # 64 summaries x 512 KiB = 32 MiB, plus 32 MiB for comparison metadata and envelopes.
    # Independent of annotations so summary eviction can never remove a reader's saved words.
    summary_store_max_bytes: int
    # Eviction orders by last write or read, so an hour's precision is enough; touching on every
    # focused poll would rewrite a store of up to 64 MiB once per board revision.
    summary_store_touch_interval_sec: float
    popup_cooldown_sec: float
    global_popup_cooldown_sec: float
    popup_repeat_suppress_sec: float
    long_turn_warn_sec: float
    # The ceiling on Pi's tool-in-flight assertion. A `toolUse` leaf is the
    # agent's own in-progress marker and rightly outlives `working_threshold_sec`
    # — recency cannot tell a long `bash` from a parked session. It cannot
    # outlive everything, though: a transcript records that a tool started and
    # can never record that the process died, so a Pi hard-killed mid-tool
    # leaves that marker as the permanent branch tip. Tied to
    # `long_turn_warn_sec` on purpose: past that point the turn already carries
    # the amber long-turn flag, so the two would otherwise disagree about the
    # same request — one calling it worth a human's attention and the other
    # still calling it healthy.
    pi_tool_in_flight_max_sec: float
    loop_error_run_threshold: int
    loop_error_total_threshold: int
    loop_barren_failure_threshold: int
    future_skew_tolerance_sec: float
    sql_message_limit: int
    max_cache_entries: int
    gemini_seen_entries: int
    reverse_chunk_bytes: int
    display_id_len: int
    claude_cwd_scan_lines: int
    claude_cwd_line_bytes: int
    turn_scan_max_bytes: int
    claude_agent_scan_lines: int
    claude_agent_cache_negative_min_bytes: int
    claude_agent_scan_bytes: int
    cursor_meta_rows: int
    # The three bounds on the Cursor model read. It is a hop through
    # content-addressed blobs — the root blob of a chat lists its message blobs
    # in order — so the cost is two indexed lookups, and these are what keep it
    # two rather than "however long the conversation is". `cursor_blob_bytes`
    # caps each blob in SQLite (a tool result runs to tens of kilobytes and the
    # field being looked for is twenty bytes), `cursor_root_children` caps the
    # id list parsed out of the root (its NEWEST ids — the child list runs
    # oldest first), and `cursor_model_probe_blobs` caps how far back the walk
    # goes before giving up.
    #
    # Measured on three live stores, 145 blobs: at most 24 children, and the
    # model was on the first blob tried every time. The probe depth is set by
    # the other end of that measurement — the longest run of consecutive
    # non-assistant children between two assistant messages is 5 (one turn with
    # five tool results in flight), which a 6-deep window clears by exactly
    # nothing: a sixth tool result mid-turn would fill the window and the
    # session would report no model at all. 12 is twice the measured worst case.
    # It is still bounded work under the read budget — at most twelve indexed
    # lookups of at most `cursor_blob_bytes` each, paid only by a store whose
    # mtime moved, since `_meta` memoizes the answer.
    cursor_blob_bytes: int
    cursor_root_children: int
    cursor_model_probe_blobs: int
    antigravity_log_head_bytes: int
    spacedock_boot_scan_bytes: int
    spacedock_readme_bytes: int
    spacedock_entity_bytes: int
    spacedock_max_frontmatter_lines: int
    spacedock_max_stages: int
    spacedock_max_workflows: int
    spacedock_max_entities: int
    spacedock_max_entity_files: int
    spacedock_max_boot_records: int
    spacedock_max_boot_candidates: int
    # The workflow README's frontmatter `title`, published as a strip's goal
    # line. The only project-authored *text* that reaches `/api/data` — every
    # other published value is a grammar-checked slug or a stage name — so it is
    # the one that needs a width of its own. 120 matches the ask lane's option
    # cap, which is the other place a line of somebody else's prose lands on the
    # page, and the README byte cap alone would have allowed a 64 KiB one on
    # every snapshot and every SSE push.
    spacedock_goal_cap_chars: int
    collect_memo_sec: float
    # The SSE stream. The client cap is above the browsers' six-per-origin
    # limit, so the server is not the thing that refuses first: it bounds
    # handler threads, it does not police tabs.
    stream_max_clients: int
    stream_heartbeat_sec: float
    stream_write_timeout_sec: float
    stream_producer_interval_sec: float
    daemon_ready_timeout_sec: float
    stop_release_timeout_sec: float
    state_read_cap_bytes: int
    # The dismissal store. The read cap is the state file's, because the shape of
    # the risk is the same: a file this process wrote, which any local process
    # could have replaced with something enormous or deeply nested. The entry
    # bound is a count and not a time-to-live — see `dismissals._bounded` for why
    # a TTL is the wrong shape — and 256 is set against what a reader can
    # plausibly have marked handled inside one 24-hour window, an order of
    # magnitude above the busiest board measured (31 sessions).
    dismissal_read_cap_bytes: int
    dismissal_max_entries: int
    # The delivery record. Bounded by a count rather than by age, because the
    # review surface reads across sessions and an age bound would empty it
    # exactly when a reader came back from a long absence, which is the case the
    # feature is for. A record is five short scalars, so 1024 of them is well
    # inside the read cap copied from the dismissal store.
    delivery_read_cap_bytes: int
    delivery_max_entries: int
    # `POST /api/lane`'s body cap. Two booleans and a short string, so this is
    # deliberately far smaller than any other body cap here: a route that accepts
    # no session and no text has nothing large that is legal, and the cap is what
    # says so before the body is read.
    lane_body_cap_bytes: int
    # The annotation store. The read cap is NOT the dismissal store's: a
    # dismissal is four scalars; an annotation is prose. 16 MiB, per item 3 of
    # the ruling `reading.MAX_OUTCOME_LINES` cites: measured, 256 sessions at
    # 16 revisions of a goal and six 240-character lines, each with a full
    # seven-criterion reading, serialize to 10.5 to 12.4 MB in ASCII,
    # depending on the length of the fact ids cited. The 2.5 MiB before it was
    # already under the 3.0 MB the two old fields permitted, and a store past
    # the cap was ignored and then overwritten by the next save. No fixed cap
    # clears every case, because
    # `ensure_ascii` writes an astral character as twelve bytes, so a write
    # trims oldest-first until the file fits (`annotations._kept`) and `load`
    # still refuses anything past it. Two count bounds and no time-to-live, again
    # for `dismissals._bounded`'s reason: a TTL would delete the reader's own
    # words while the session they describe is still on the board. 256 sessions
    # matches `dismissal_max_entries` against the same measured board; 16
    # revisions is set against a reader refining one line a handful of times,
    # and the numbering keeps counting past an eviction so a dropped revision
    # reads as dropped. The text cap is 240 characters, the bound the design
    # draws as its live `n/240` counter.
    annotation_read_cap_bytes: int
    annotation_max_sessions: int
    annotation_max_revisions: int
    annotation_text_cap_chars: int
    # The unasked lane's bounds. Per session and per day, separately, because
    # they answer different failures: one session churning, and a whole board
    # quietly spending a day's capacity. Each reading is a `codex` subprocess at
    # `reasoning_effort=max`, so these are capacity numbers rather than taste.
    # Chosen rather than measured, and deliberately low: the ruling cited in
    # `unasked.py` says to measure the real rate on a real board before raising
    # them, and a cap that is too low renders as exhausted, which the board
    # says out loud.
    unasked_session_cap: int
    unasked_daily_cap: int
    # The floor between two unasked readings of the same session, whatever its
    # state does. A session can cross a state boundary repeatedly inside a
    # minute, and the cap is not a rate limit.
    unasked_session_floor_sec: float
    # The store's bounds, copied from the delivery record beside it for its
    # reason: a count rather than an age, because the review surface reads
    # across sessions and an age bound would empty it exactly when a reader came
    # back from a long absence.
    departure_read_cap_bytes: int
    departure_max_entries: int
    # The session-end store's bounds (DRC-4547). The read cap is the dismissal
    # store's rather than the delivery record's, because the shape of a record
    # is the dismissal's: three scalars and no prose, so 512 of them serialize
    # to a few tens of kilobytes and the 65,536 leaves headroom to spare. The
    # entry bound matches `event_overlay_max_sessions`, the cap `_mark_ended`
    # already refuses new keys at, so the store can never restore more ends
    # than the coordinator's memory would have held; a count and not an age,
    # for `dismissals._bounded`'s reason.
    end_read_cap_bytes: int
    end_max_entries: int
    # The history store's two bounds, which apply together: raising either does
    # not stop the other applying. Fourteen days and 1 MiB are the contract's
    # defaults, and `--history-days` and `--history-max-bytes` are what move
    # them: the promoted contract says both are configurable, so they are. The
    # byte cap is the read cap as well — a file larger than it is discarded
    # unread rather than parsed, which is the same posture the state file takes
    # — and 1 MiB holds 7,825 observations at the 132 bytes a Claude record
    # measures over this machine's real board (2,713 rows), or 6,853 at the 151
    # bytes a Codex one does, since a record's size is its identity strings.
    # Both are against the 31-session busiest board measured for
    # `dismissal_max_entries`.
    history_retention_sec: float
    history_max_bytes: int
    # What a dismissal request may declare. Three short fields, so this is far
    # below even the event cap: nothing else is read from the body.
    dismissal_body_cap_bytes: int
    # What an annotation request may declare, per item 3 of the ruling
    # `reading.MAX_OUTCOME_LINES` cites. The widest body the page can send is a
    # paste of control characters, which `JSON.stringify` writes as six bytes
    # each before the store collapses them: a goal and six lines of 240 of them,
    # a 64-character session id and an expected revision measure 10,238 bytes,
    # so 12 KiB holds it and is still far below the event cap. `POST
    # /api/reading` shares it, where it is only generous.
    annotation_body_cap_bytes: int
    prompt_path_collapse_min_length: int
    first_line_json_cap_bytes: int
    notification_body_cap_bytes: int
    # What an open question may occupy on a row. Characters, not bytes: this one
    # is measured where it is read, and a plan's first line is prose rather than
    # a payload.
    input_summary_cap_chars: int
    # The quota fetch (SECURITY.md, "Usage quota reads"): the contract's
    # five-minute floor between requests to one vendor, the request timeout,
    # and the read caps on the credential file and the response body.
    usage_poll_floor_sec: float
    usage_fetch_timeout_sec: float
    usage_credentials_cap_bytes: int
    usage_response_cap_bytes: int
    # A pushed status-line receipt. Larger than the notification cap because
    # the payload carries a whole session-state block, not just a message.
    usage_receipt_cap_bytes: int
    # The end-of-session git probe (SECURITY.md, "Repository git reads"). Ten
    # seconds, mirroring `usage_fetch_timeout_sec` rather than being chosen
    # separately: both bound one external call the board can do without, and the
    # probe already runs off the event thread, so a slow repository costs a late
    # reading rather than a stalled ingress.
    git_probe_timeout_sec: float
    # How many probes may be in flight at once, across every harness. One per
    # session key is enforced separately and is the cheaper half; this is the
    # global ceiling, and it exists because the per-key gate does not bound a
    # caller that varies the session id. Measured: the event budget alone allows
    # 40 burst plus 20/s for the probe's whole 10 s life, so 240 live probe
    # threads per harness and 960 across the four normalizers. 32 is well above
    # any observed number of sessions ending inside one timeout window — the
    # board's own row lists run in the low tens across ten harnesses, and
    # simultaneous ends are rarer than that — and a refused probe costs one row
    # the two scalars it would have published, which is the disclosure `None`
    # already carries for every other refusal on this path.
    git_probe_max_inflight: int
    # The focus command's three bounds. The timeout is well under the git
    # probe's because a tmux command answers over a UNIX socket rather than by
    # walking a tree, and this one runs on the request thread the reader is
    # waiting on rather than off it. The floor and the in-flight gate are the
    # `usage_poll_floor_sec` pair one feature over: a repeated or looped request
    # must not be able to repeat the raise. The body cap matches the dismissal
    # route's, whose body is the same two fields.
    focus_timeout_sec: float
    focus_floor_sec: float
    focus_body_cap_bytes: int
    # How long a recorded focus target outlives the last event for its session.
    # Not a row-set prune the way the completion mark and the git reading are:
    # those are display state that comes back with the row, while a target is
    # gathered once on `session_started` and never again, so a collection that
    # missed the row would kill the control for the session's life. Derived from
    # `window_hours` rather than chosen: a session silent for a whole row window
    # is one whose row is no longer produced, so its target can no longer be
    # clicked either.
    focus_target_ttl_sec: float
    # Event overlays. The Working deadline is tied to `working_threshold_sec`
    # rather than chosen separately: that value is already what the collectors
    # mean by Working, so an overlay that outlived it would be claiming Working
    # for a session the scan would call Idle, which is the disagreement the
    # overlay exists to avoid. The dwell is a chosen constant, set well above the
    # 50 to 150 millisecond coalescing window so a stop followed immediately by a
    # new prompt resolves inside one publish instead of flapping the row.
    # A needs-input overlay has no deadline, because a real permission wait can
    # last hours. What ends it, absent a hook that says so, is the session's own
    # transcript moving again: an open prompt leaves the file quiet, and the
    # tool_result that follows a grant advances it. What that quiet is not is a
    # tool_use record written ahead of the prompt -- Claude Code writes it on no
    # schedule at all, and often not while the gate stands, which leaves the file
    # quieter still. See
    # [N-2](docs/design-needs-input.md#n-2).
    # The grace absorbs the ordering between a hook process and the write that provoked it, and
    # nothing
    # else -- a wait that ends is over within one write, not within a minute.
    overlay_wait_activity_grace_sec: float
    overlay_working_ttl_sec: float
    overlay_idle_dwell_sec: float
    overlay_repeating_wait_lease_sec: float
    # The coordinator. The coalescing window is fixed rather than sliding: a
    # sliding window never closes under a sustained burst, and the board would
    # stop updating entirely. The ledger and pending caps are refusal thresholds,
    # not eviction thresholds, because evicting to make room would drop whichever
    # permission alert happened to be oldest. `reconcile_interval_sec` is the
    # longest a probe-negative tick may keep skipping, which is what bounds the
    # probe's documented false negative.
    event_coalesce_sec: float
    event_overlay_max_sessions: int
    event_pending_max: int
    event_pending_ttl_sec: float
    # How long an observed session end outlives the row it belongs to. Not the
    # row-set prune the completion mark and the git reading use, and the
    # difference is deliberate: those are re-supplied by the next `turn_stopped`,
    # so an over-eager prune self-heals, while `session_ended` fires once per
    # session id and a mark dropped early can never be earned again. Derived from
    # `window_hours` for `focus_target_ttl_sec`'s reason — a row is produced only
    # while its activity is inside that window, and an end is the last thing that
    # happens to an id, so past one window the row cannot come back.
    ended_mark_ttl_sec: float
    reconcile_interval_sec: float
    # How many recent state disputes to keep. A ring, unlike the two caps above,
    # because a dispute is evidence rather than a live alert: losing the oldest
    # costs a sample, and refusing new ones would stop recording exactly when the
    # fault became frequent.
    dispute_log_max: int
    # How many successive quota readings to keep per vendor window, for the
    # recent-pace figure. A ring for the reason `dispute_log_max` is one: the
    # oldest sample is the least useful, and refusing new ones would freeze the
    # pace exactly while it was changing. Twelve at the five-minute fetch floor
    # spans an hour, which is the shortest window's own scale; a vendor read
    # from disk fills it only as fast as it writes.
    usage_samples_max: int
    # Event ingress. The body cap is far below the notification cap because the
    # envelope is fourteen short fields and nothing else is read from it. The rate
    # ceiling is independent of the capability: a looping or compromised adapter
    # holds a valid token by definition, so the token cannot be what bounds it.
    # The burst allows one turn's worth of hooks to arrive together.
    event_body_cap_bytes: int
    event_rate_per_sec: float
    event_burst_max: int
    # The ask lane. The deadline is what retires a question nobody answered, and
    # five minutes is set against the thing on the other end: the asking session
    # is parked in a tool call for the whole wait, so a longer deadline buys a
    # reader nothing and costs an agent a stalled turn. There is no timer thread
    # to enforce it: the sweep rides on `AskRegistry.register` and on the
    # collection the coordinator now runs while any ask is outstanding, which is
    # what makes it independent of anybody watching the page.
    ask_deadline_sec: float
    # How long a resolved ask stays retrievable after the sweep first sees its
    # outcome, so its poller can still collect it. One minute is six poll holds
    # at `ask_poll_timeout_sec`, which is generous against a peer that is either
    # parked in `wait` and gets the answer instantly or is gone for good. Past
    # this the row is dropped; the budget never counted it, because a resolved
    # ask needs no slot.
    ask_retention_sec: float
    # One long-poll hold. Bounded rather than held open for the whole wait, which
    # is what keeps the thread budget, the shutdown decline and a dead peer all
    # ordinary: see docs/design-ask-lane.md.
    ask_poll_timeout_sec: float
    # A hard cap, not a queue: every outstanding ask costs a card on the page and
    # a polling peer, so past this the register route refuses with a 503.
    ask_max_pending: int
    # The register body carries a question and up to `ask_max_options` options,
    # so it is sized like the event envelope rather than like a notification.
    ask_body_cap_bytes: int
    # The answer body carries an id and an integer, and nothing else is read
    # from it.
    ask_answer_body_cap_bytes: int
    # What agent-written text may occupy. Characters, not bytes, because these
    # are bounded through `records.safe_text` at the HTTP ingress -- `asks`
    # imports nothing and cannot reach it -- and that helper counts characters.
    ask_question_cap_chars: int
    ask_option_cap_chars: int
    # A project path is not a label and routinely runs past any label cap: the
    # e2e run that found this had a 122-character cwd, so a 120 cap published a
    # directory that does not exist. Its own knob, and generous.
    ask_project_cap_chars: int
    ask_max_options: int
    # The observer analyzer: a read-only bystander that derives goal + stage +
    # block from a target session's transcript head and its workflow entity dir.
    # The head bound is what it reads from the transcript's opening records; the
    # goal and block caps bound the two derived strings it publishes, and the
    # context cap bounds the one string it hands *out*, to a model callable
    # nothing in the shipped tree supplies. That callable is a parameter rather
    # than a config field precisely so no model id lives here: naming one would
    # imply the analyzer calls it, and it does not.
    observer_head_bytes: int
    observer_goal_cap_chars: int
    observer_block_cap_chars: int
    observer_model_context_chars: int
    # How long after an observed session end a reading may call it final.
    # The measurement is 5.581 s, the slowest clean end recorded after its
    # final `Stop`; the headroom above it is judgement, because event delivery
    # is at-least-once and reorderable and a reading composed on the instant
    # of the end can be contradicted by a `turn_started` already in flight.
    reading_settle_sec: float
    # How old a Claude Code reading's output or stderr file in `state_dir` must be before a starting
    # run removes it as left by a hard kill (review, 2026-10-20). Every call is bounded by its
    # timeout, 180 s for a reading, and a second instance may share the directory mid-call, so the
    # bound is a day: far past any live call, and still short of leaving raw stderr for long.
    reading_scratch_stale_sec: float
    # The Live monitor, one block (the 2026-10-23 amendment cited above): the pinned Haiku id,
    # the floor between two checks of one session, the call's timeout, the prompt and output
    # bounds, the two caps (ticks per session per TTL window, ticks across the board per rolling
    # 24 h) and how many checks may run at once on the board. The window is the banner's 20
    # minutes plus its 10. The 240 board cap is PENDING THE OWNER'S FIGURE: none was given, and
    # 240 is a sixth of a day of once-a-minute checks. The 6,000-character prompt cap holds the
    # recent window a check re-sends beside its new turns.
    claude_monitor_model: str
    live_monitor_interval_sec: float
    live_monitor_timeout_sec: float
    live_monitor_prompt_cap_chars: int
    live_monitor_output_cap_bytes: int
    live_monitor_session_tick_cap: int
    live_monitor_banner_sec: float
    live_monitor_window_sec: float
    live_monitor_daily_cap: int
    live_monitor_in_flight_limit: int


def resolve_store_roots(
    *,
    platform_name: str,
    environ: Mapping[str, str],
    home: str,
    pi_settings: Mapping[str, Any] | None = None,
) -> dict[str, list[str]]:
    """Return candidate locations for every harness store, best first."""
    windows = platform_name == "win32"
    join = ntpath.join if windows else posixpath.join
    is_absolute = ntpath.isabs if windows else posixpath.isabs

    def under_home(*parts: str) -> str:
        return join(home, *parts)

    def env_dir(name: str) -> str | None:
        value = environ.get(name)
        if not isinstance(value, str) or not value.strip():
            return None
        return value

    xdg_data = env_dir("XDG_DATA_HOME") or under_home(".local", "share")
    local_app_data = env_dir("LOCALAPPDATA") if windows else None
    roaming_app_data = env_dir("APPDATA") if windows else None
    claude_home = env_dir("CLAUDE_CONFIG_DIR") or under_home(".claude")
    codex_home = env_dir("CODEX_HOME") or under_home(".codex")
    gemini_root = env_dir("GEMINI_CLI_HOME")
    gemini_home = join(gemini_root, ".gemini") if gemini_root else under_home(".gemini")
    copilot_home = env_dir("COPILOT_HOME") or under_home(".copilot")
    pi_config_dir = env_dir("PI_CODING_AGENT_DIR") or under_home(".pi", "agent")
    pi_session_dir = env_dir("PI_CODING_AGENT_SESSION_DIR")
    session_setting = pi_settings.get("sessionDir") if pi_settings is not None else None
    if pi_session_dir is None and isinstance(session_setting, str) and session_setting.strip():
        if session_setting == "~":
            pi_session_dir = home
        elif len(session_setting) > 1 and session_setting[0] == "~" and session_setting[1] in "/\\":
            pi_session_dir = join(home, session_setting[2:])
        elif is_absolute(session_setting):
            pi_session_dir = session_setting
        else:
            pi_session_dir = join(pi_config_dir, session_setting)
    pi_sessions = pi_session_dir or join(pi_config_dir, "sessions")
    antigravity_home = join(gemini_home, "antigravity-cli")

    def ordered(*candidates: str | None) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate is None:
                continue
            key = ntpath.normcase(candidate) if windows else candidate
            if key not in seen:
                seen.add(key)
                deduped.append(candidate)
        return deduped

    def app_data(root: str | None, *parts: str) -> str | None:
        return join(root, *parts) if root else None

    return {
        "claude.projects": ordered(join(claude_home, "projects")),
        "claude.tasks": ordered(join(claude_home, "tasks")),
        # The teams registry, one directory per lead session. It is the only
        # store that names a dispatched subagent BEFORE that subagent has
        # written a transcript byte, which is the whole on-disk trace of one
        # blocked at a startup gate (DRC-4263).
        "claude.teams": ordered(join(claude_home, "teams")),
        "codex.sessions": ordered(join(codex_home, "sessions")),
        "pi.sessions": ordered(pi_sessions),
        "gemini.tmp": ordered(join(gemini_home, "tmp")),
        "antigravity.root": ordered(antigravity_home),
        "copilot.root": ordered(copilot_home),
        "opencode.data": ordered(
            join(xdg_data, "opencode"),
            app_data(local_app_data, "opencode", "data"),
            app_data(local_app_data, "opencode"),
            under_home(".local", "share", "opencode") if windows else None,
        ),
        "cursor.chats": ordered(under_home(".cursor", "chats")),
        "goose.db": ordered(
            join(xdg_data, "goose", "sessions", "sessions.db"),
            app_data(roaming_app_data, "Block", "goose", "data", "sessions", "sessions.db"),
            app_data(local_app_data, "Block", "goose", "data", "sessions", "sessions.db"),
        ),
        # Droid 0.202.0 writes <home>/.factory/sessions/<slugified-cwd>/<id>.jsonl.
        # Measured 2026-09-02: with `projects` as the only root, three real
        # transcripts discovered nothing (DRC-4331). `projects` stays as the
        # fallback because no measurement says which versions wrote there.
        "droid.projects": ordered(
            under_home(".factory", "sessions"), under_home(".factory", "projects")
        ),
    }


def load_pi_settings(config_dir: str) -> dict[str, Any]:
    try:
        with open(os.path.join(config_dir, "settings.json"), "rb") as source:
            value = json.loads(source.read(1_000_001))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def build_runtime_config(
    *,
    environ: Mapping[str, str],
    platform_name: str,
    os_name: str,
    launcher_path: Path,
    store_root_overrides: Mapping[str, str] | None = None,
    host: str = "127.0.0.1",
    port: int = 4553,
    window_hours: float = 24.0,
    spacedock_enabled: bool = True,
    tripwires_enabled: bool = True,
    usage_fetch_enabled: bool = True,
    observer_model_enabled: bool = True,
    model_calls_disabled: bool = False,
    claude_reading_model: str = CLAUDE_READING_DEFAULT_MODEL,
    claude_monitor_model: str = CLAUDE_MONITOR_DEFAULT_MODEL,
    git_probe_enabled: bool = True,
    focus_enabled: bool = True,
    irreversible_enabled: bool = True,
    dismissals_enabled: bool = True,
    annotations_enabled: bool = True,
    unasked_enabled: bool = False,
    ask_enabled: bool = True,
    reach_enabled: bool = True,
    reach_url: str | None = None,
    reach_cooldown_sec: float = 60.0,
    quiet_hours_enabled: bool = True,
    quiet_hours: str | None = None,
    history_enabled: bool = True,
    history_retention_sec: float = HISTORY_RETENTION_DEFAULT_DAYS * SECONDS_PER_DAY,
    history_max_bytes: int = HISTORY_MAX_BYTES_DEFAULT,
) -> RuntimeConfig:
    """Construct runtime configuration solely from explicit inputs."""
    selected_claude_model = validate_claude_reading_model(claude_reading_model)
    selected_monitor_model = validate_claude_monitor_model(claude_monitor_model)
    windows = platform_name == "win32"
    join = ntpath.join if windows else posixpath.join
    home_key = "USERPROFILE" if windows else "HOME"
    home = environ.get(home_key) or environ.get("HOME") or ""
    data_home = environ.get("XDG_DATA_HOME") or join(home, ".local", "share")
    pi_config_dir = environ.get("PI_CODING_AGENT_DIR")
    if not isinstance(pi_config_dir, str) or not pi_config_dir.strip():
        pi_config_dir = join(home, ".pi", "agent")
    roots = resolve_store_roots(
        platform_name=platform_name,
        environ=environ,
        home=home,
        pi_settings=load_pi_settings(pi_config_dir),
    )
    resolved = {key: tuple(candidates) for key, candidates in roots.items()}
    for key, selected in (store_root_overrides or {}).items():
        resolved[key] = (selected,)
    state_override = environ.get(COMPASS_HOME_ENV)
    state_home = (
        state_override
        if state_override and state_override.strip()
        else default_home(home, windows=windows)
    )
    state_dir = _PATH_TYPE(state_home)
    return RuntimeConfig(
        home=home,
        data_home=data_home,
        store_roots=MappingProxyType(resolved),
        platform_name=platform_name,
        os_name=os_name,
        state_dir=state_dir,
        state_home=state_home,
        launcher_path=launcher_path,
        host=host,
        port=port,
        frontend_dev=None,
        window_hours=window_hours,
        spacedock_enabled=spacedock_enabled,
        tripwires_enabled=tripwires_enabled,
        usage_fetch_enabled=usage_fetch_enabled,
        observer_model_enabled=observer_model_enabled,
        model_calls_disabled=model_calls_disabled,
        claude_reading_model=selected_claude_model,
        git_probe_enabled=git_probe_enabled,
        focus_enabled=focus_enabled,
        irreversible_enabled=irreversible_enabled,
        dismissals_enabled=dismissals_enabled,
        annotations_enabled=annotations_enabled,
        unasked_enabled=unasked_enabled,
        ask_enabled=ask_enabled,
        reach_enabled=reach_enabled,
        reach_url=reach_url,
        reach_cooldown_sec=reach_cooldown_sec,
        quiet_hours_enabled=quiet_hours_enabled,
        quiet_hours=quiet_hours,
        history_enabled=history_enabled,
        # Ten minutes stays. The burn ordering (DRC-4011) wants the fastest
        # session "right now", and this window is the reason it cannot have it:
        # narrowing it would re-scale the summary tile, both sparklines and every
        # rate on the board — `sessions.rate_from` and the three collectors that
        # do that arithmetic themselves — in one edit, for a figure that would then
        # be noisier on every surface that already reads it. So the board keeps the
        # mean and names it — the payload publishes this number and the ledger
        # states the window it ranked on, rather than claiming an immediacy the
        # arithmetic does not have.
        rate_window_sec=600,
        working_threshold_sec=90,
        turn_gap_reset_sec=300,
        tail_bytes=400_000,
        record_page_max_bytes=RECORD_PAGE_MAX_BYTES,
        record_page_max_seconds=RECORD_PAGE_MAX_SECONDS,
        record_page_chunk_bytes=64 * 1024,
        direction_scan_max_bytes=DIRECTION_SCAN_MAX_BYTES,
        direction_scan_max_seconds=DIRECTION_SCAN_MAX_SECONDS,
        entry_index_max_seconds=ENTRY_INDEX_MAX_SECONDS,
        entry_index_limit=ENTRY_INDEX_LIMIT,
        session_source_page_max_bytes=SESSION_SOURCE_PAGE_MAX_BYTES,
        session_source_page_max_seconds=SESSION_SOURCE_PAGE_MAX_SECONDS,
        session_source_classify_share=SESSION_SOURCE_CLASSIFY_SHARE,
        session_source_line_max_bytes=SESSION_SOURCE_LINE_MAX_BYTES,
        session_outline_max_bytes=SESSION_OUTLINE_MAX_BYTES,
        session_outline_head_bytes=SESSION_OUTLINE_HEAD_BYTES,
        session_outline_max_seconds=SESSION_OUTLINE_MAX_SECONDS,
        session_outline_max_blocks=SESSION_OUTLINE_MAX_BLOCKS,
        session_outline_highlights=SESSION_OUTLINE_HIGHLIGHTS,
        session_outline_cache_limit=SESSION_OUTLINE_CACHE_LIMIT,
        session_summary_window_bytes=SESSION_SUMMARY_WINDOW_BYTES,
        session_summary_max_windows=SESSION_SUMMARY_MAX_WINDOWS,
        session_summary_max_calls=SESSION_SUMMARY_MAX_CALLS,
        session_summary_max_bytes_sent=SESSION_SUMMARY_MAX_BYTES_SENT,
        session_summary_max_seconds=SESSION_SUMMARY_MAX_SECONDS,
        session_summary_call_timeout=SESSION_SUMMARY_CALL_TIMEOUT,
        session_summary_rolling_cap=SESSION_SUMMARY_ROLLING_CAP,
        session_summary_output_cap_bytes=SESSION_SUMMARY_OUTPUT_CAP_BYTES,
        session_summary_max_phases=SESSION_SUMMARY_MAX_PHASES,
        session_summary_max_bullets=SESSION_SUMMARY_MAX_BULLETS,
        session_summary_max_cites=SESSION_SUMMARY_MAX_CITES,
        session_summary_title_chars=SESSION_SUMMARY_TITLE_CHARS,
        session_summary_bullet_chars=SESSION_SUMMARY_BULLET_CHARS,
        session_summary_lede_chars=SESSION_SUMMARY_LEDE_CHARS,
        session_summary_max_bytes=SESSION_SUMMARY_MAX_BYTES,
        session_summary_person_chars=1_200,
        session_summary_agent_chars=700,
        session_summary_check_chars=220,
        session_summary_path_chars=220,
        session_summary_attempts_per_part=2,
        summary_freshness_retry_sec=300.0,
        summary_store_key_cap_chars=64,
        summary_store_model_stamp_cap_chars=256,
        summary_store_lock_wait_sec=10.0,
        summary_store_filename="compass-summaries.json",
        summary_store_max_bytes=64 * 1024 * 1024,
        summary_store_touch_interval_sec=3600.0,
        popup_cooldown_sec=60,
        global_popup_cooldown_sec=15,
        popup_repeat_suppress_sec=600,
        long_turn_warn_sec=900,
        pi_tool_in_flight_max_sec=900,
        # Consecutive failed tool calls before a turn is called a loop.
        # Measured, twice, over the 25 most recent local Claude transcripts:
        # run lengths came out {1: 56, 2: 4, 4: 1}, so 3 and 4 both fire in
        # 1 session of 25 and 5 fires in none. 4 buys the same yield as 3 with
        # strictly less exposure to the benign runs the sample was full of — an
        # `ls` that found nothing, a `git` in a deleted worktree. Lower is the
        # expensive direction: the pattern this keys on is also what iterating
        # on a failing test looks like, and a flag a reader learns to ignore
        # costs more than no flag.
        loop_error_run_threshold=4,
        # Higher than the run threshold, deliberately. The run of four is a
        # tight loop; a total is failures however they were spaced, and four
        # scattered failures through a long productive turn is ordinary work
        # rather than a session stuck.
        #
        # Six is not on its own enough, and the first draft of this comment
        # claimed it was. Replaying 60 real Claude transcripts, 3 reached six
        # scattered failures on turns that were plainly healthy, the worst being
        # 7 failures among 198 successes with a longest run of 2. So `loop_signal`
        # pairs this count with a share test: the failures must also outnumber the
        # successes. Raising the number instead does not work, because silencing
        # that worst case needs 8 and the shape the rung exists for has 6.
        loop_error_total_threshold=6,
        # Lower than both, because the reading is different: not how long the
        # run is, but whether anything in this turn has worked at all. The
        # floor exists because every turn is barren for a moment at its start,
        # and a signal that fires on the second call of a healthy turn is the
        # flag a reader learns to ignore.
        loop_barren_failure_threshold=3,
        future_skew_tolerance_sec=120,
        sql_message_limit=400,
        max_cache_entries=8192,
        gemini_seen_entries=2048,
        reverse_chunk_bytes=262_144,
        display_id_len=8,
        claude_cwd_scan_lines=50,
        claude_cwd_line_bytes=200_000,
        turn_scan_max_bytes=8 * 1024 * 1024,
        claude_agent_scan_lines=50,
        claude_agent_cache_negative_min_bytes=16_384,
        claude_agent_scan_bytes=16_384,
        cursor_meta_rows=50,
        cursor_blob_bytes=65_536,
        cursor_root_children=64,
        cursor_model_probe_blobs=12,
        antigravity_log_head_bytes=80_000,
        spacedock_boot_scan_bytes=512_000,
        spacedock_readme_bytes=65_536,
        spacedock_entity_bytes=8_192,
        spacedock_max_frontmatter_lines=400,
        spacedock_max_stages=32,
        spacedock_max_workflows=8,
        spacedock_max_entities=12,
        spacedock_max_entity_files=96,
        spacedock_max_boot_records=16,
        spacedock_max_boot_candidates=64,
        spacedock_goal_cap_chars=120,
        collect_memo_sec=2.5,
        stream_max_clients=8,
        stream_heartbeat_sec=15.0,
        stream_write_timeout_sec=10.0,
        stream_producer_interval_sec=5.0,
        daemon_ready_timeout_sec=10.0,
        stop_release_timeout_sec=5.0,
        state_read_cap_bytes=65_536,
        dismissal_read_cap_bytes=65_536,
        dismissal_max_entries=256,
        delivery_read_cap_bytes=262_144,
        delivery_max_entries=1_024,
        lane_body_cap_bytes=512,
        annotation_read_cap_bytes=16_777_216,
        annotation_max_sessions=256,
        annotation_max_revisions=16,
        annotation_text_cap_chars=240,
        unasked_session_cap=3,
        unasked_daily_cap=12,
        unasked_session_floor_sec=900.0,
        departure_read_cap_bytes=262_144,
        departure_max_entries=512,
        end_read_cap_bytes=65_536,
        end_max_entries=512,
        annotation_body_cap_bytes=12_288,
        dismissal_body_cap_bytes=1_024,
        history_retention_sec=history_retention_sec,
        history_max_bytes=history_max_bytes,
        prompt_path_collapse_min_length=25,
        first_line_json_cap_bytes=200_000,
        notification_body_cap_bytes=65_536,
        input_summary_cap_chars=160,
        usage_poll_floor_sec=300,
        usage_fetch_timeout_sec=10,
        git_probe_timeout_sec=10.0,
        git_probe_max_inflight=32,
        focus_timeout_sec=2.0,
        focus_floor_sec=1.0,
        focus_body_cap_bytes=1_024,
        focus_target_ttl_sec=window_hours * 3_600.0,
        usage_credentials_cap_bytes=65_536,
        usage_response_cap_bytes=262_144,
        usage_receipt_cap_bytes=131_072,
        overlay_wait_activity_grace_sec=10.0,
        overlay_working_ttl_sec=90,
        overlay_idle_dwell_sec=3.0,
        overlay_repeating_wait_lease_sec=300.0,
        event_coalesce_sec=0.1,
        event_overlay_max_sessions=512,
        event_pending_max=256,
        event_pending_ttl_sec=60.0,
        ended_mark_ttl_sec=window_hours * 3_600.0,
        reconcile_interval_sec=30.0,
        dispute_log_max=50,
        usage_samples_max=12,
        event_body_cap_bytes=8_192,
        event_rate_per_sec=20.0,
        event_burst_max=40,
        ask_deadline_sec=300.0,
        ask_retention_sec=60.0,
        ask_poll_timeout_sec=10.0,
        ask_max_pending=16,
        ask_body_cap_bytes=8_192,
        ask_answer_body_cap_bytes=1_024,
        ask_question_cap_chars=500,
        ask_option_cap_chars=120,
        ask_project_cap_chars=512,
        ask_max_options=8,
        observer_head_bytes=65_536,
        observer_goal_cap_chars=200,
        observer_block_cap_chars=200,
        observer_model_context_chars=8_192,
        reading_settle_sec=8.0,
        reading_scratch_stale_sec=86_400.0,
        claude_monitor_model=selected_monitor_model,
        live_monitor_interval_sec=60.0,
        live_monitor_timeout_sec=45.0,
        live_monitor_prompt_cap_chars=6_000,
        live_monitor_output_cap_bytes=2_048,
        live_monitor_session_tick_cap=30,
        live_monitor_banner_sec=1_200.0,
        live_monitor_window_sec=1_800.0,
        live_monitor_daily_cap=240,
        live_monitor_in_flight_limit=1,
    )


def store_roots(config: RuntimeConfig, key: str) -> tuple[str, ...]:
    return config.store_roots.get(key, ())


def primary_store(config: RuntimeConfig, key: str) -> str:
    return store_roots(config, key)[0]
