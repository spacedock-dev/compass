"""Untrusted lifecycle events, normalized before anything can act on them.

Every input here arrives from a hook process Compass does not control, over a
loopback socket that is not a user boundary, in a shape whose adapter may be
older than the server reading it. This module is the whole of the validation: it
decides what an event means, which session it belongs to, and which display
fields it is allowed to influence. Nothing downstream re-checks it.

It is deliberately pure. No locks, no counters, no clock of its own, no
filesystem. `arrival_seq` is assigned by the ingress under its own lock and
passed in; the mutable pending map and overlay ledger live in the coordinator
that owns their bounds. Keeping this layer a set of functions over frozen values
is what makes the ordering rules below testable without a running server.

## Three separate ideas about order

`arrival_seq` is the server's own monotonic counter, assigned after
authentication and validation. It is the only ordering that fences a concurrent
collection, because it is the only one the server mints itself.

`(source_instance_id, source_sequence)` is optional and trusted only when a
native source supplies both. A fresh command-hook process cannot mint a shared
sequence, so most sources supply neither and get at-least-once, possibly
reordered delivery. Reducers are therefore idempotent.

Event timestamps drive displayed timing and plausibility only. They never fence
concurrency. A hook inside a container whose clock runs hours ahead must not be
able to pin a row, so an implausible stamp is replaced by server arrival time
rather than believed or rejected.

## Provenance, not recency

An overlay may patch only the fields in `PATCHABLE`. For everything else the
collector is authoritative: titles, projects, historical turns, tasks, token
rates, parent relationships and subagent reconstruction. That split is what lets
a long generation keep reading Working without letting a hook rewrite metadata
it has no knowledge of.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import irreversible, records
from compass_runtime import sessions as runtime_sessions

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from compass_runtime.config import RuntimeConfig

# The envelope version this build writes. Adapters live in user-owned
# configuration and are not upgraded when Compass is, so the accepted range
# below is a public compatibility surface with an indefinite tail, not an
# internal wire format.
ENVELOPE_VERSION: Final = 1
SUPPORTED_VERSIONS: Final = frozenset({1})

# The normalized vocabulary. Adapters translate native names into these; a name
# outside the set is ignored rather than accepted into state, because an unknown
# name is indistinguishable from a typo in a hook someone wrote by hand.
EVENT_NAMES: Final = frozenset(
    {
        "session_started",
        "session_ended",
        "turn_started",
        "turn_stopped",
        "input_requested",
        "input_resolved",
        "subagent_started",
        "subagent_stopped",
        "tasks_changed",
        "store_changed",
        "reconcile_required",
        "command_shape_reported",
    }
)

# Read from the envelope; everything else in a native payload is discarded
# rather than rejected, so a harness adding a field does not break its adapter.
ALLOWED_FIELDS: Final = frozenset(
    {
        "v",
        "event",
        "session_id",
        "timestamp",
        "source_instance_id",
        "source_sequence",
        "cwd",
        "subagent_id",
        "transcript_path",
        # Terminal identity, gathered by a hook on `session_started` alone and
        # used only to build a focus command. Deliberately NOT in `PATCHABLE`
        # below: every member there is a published display claim, and
        # `SECURITY.md`'s focus section forbids echoing a target.
        "tmux_socket",
        "tmux_pane",
        # The pid of the tmux server that reported the pane. A pane id is an
        # ordinal on one server, so without this a target outlives its server and
        # names whatever pane inherited the id.
        "tmux_server",
        "pattern_id",
        "tool_name",
    }
)

# Fields an overlay may patch. `acquisition` is the provenance marker: a row
# reached by events reads "event", and one reached only by scanning reads
# "scan-only", which is how the latency of a harness with no healthy event
# source gets disclosed instead of hidden.
#
# `finished_at` is the stamp of the stop this session last had observed, and it
# is here rather than derived from `state` because Idle is two different
# situations wearing one word: a turn that ended, and a session still waiting on
# a reply nobody gave (DRC-4035). Only a `turn_stopped` separates them, so the
# distinction cannot be recovered from a collected row.
#
# `dirty` and `changed` are the end-of-session git reading. They are here for the
# same reason `finished_at` is — the coordinator remembers them outside the ledger
# `session_ended` pops — and every branch below restates them, because a reading
# taken when a session ended describes a tree that a resumed session may already
# have changed.
#
# `ended_at` is when the session ID itself was observed to end, and it is a
# separate member rather than a reading of `finished_at` because the two answer
# different questions: a turn stopping leaves a session open and typeable, and
# only an end says the row will never move again (DRC-4036). It is a nullable
# stamp and not a fourth `state` value because three page sites read `state`
# against a closed set and fail toward the wrong answer on an unknown member
# rather than degrading — the Safe-to-close lane silently drops the session, the
# project activity pill blanks, and the coverage note calls it "unknown state".
PATCHABLE: Final = frozenset(
    {
        "state",
        "state_detail",
        "active",
        "blocked_since",
        "wait_unconfirmed",
        "acquisition",
        "finished_at",
        "ended_at",
        "dirty",
        "changed",
    }
)

ACQUISITION_EVENT: Final = "event"
ACQUISITION_SCAN: Final = "scan-only"

# Source classes: repeating status-line renders vs discrete lifecycle hook events.
SOURCE_CLASS_REPEATING: Final = "repeating"
SOURCE_CLASS_DISCRETE: Final = "discrete"

# Rejection reasons. `incompatible` is reported through --diagnose and the
# acquisition strip rather than dropped silently, because an adapter too old for
# this server is a state the user can fix and the unknown-name rule would
# otherwise hide it.
REJECT_INCOMPATIBLE: Final = "incompatible"
REJECT_UNKNOWN_EVENT: Final = "unknown-event"
REJECT_MALFORMED: Final = "malformed"
REJECT_UNKNOWN_HARNESS: Final = "unknown-harness"
REJECT_UNMAPPABLE: Final = "unmappable-id"

# Bounds on the string fields. The ingress caps the whole body; these cap each
# field, so one enormous but legal-looking value cannot be stored or logged.
MAX_ID_LEN: Final = 200
MAX_PATH_LEN: Final = 4096
# The three terminal-identity fields. Bounded here as every other string field is,
# and bounded well above their own grammars, which `focus.py` applies at the
# raise: this cap stops an enormous but legal-looking value being stored, and the
# grammar decides whether a command is ever built.
MAX_TERMINAL_ID_LEN: Final = 128

# Overlay kinds, in the order the design derives them from native events.
OVERLAY_WORKING: Final = "working"
OVERLAY_NEEDS_INPUT: Final = "needs_input"
OVERLAY_IDLE: Final = "idle"
OVERLAY_SUBAGENT: Final = "subagent"

# Kinds whose arrival means the session is not waiting for a person. A needs-input
# overlay older than the newest of these is over, permanently, however long the
# overlay that ended it stays live. `idle` is here for completeness rather than
# necessity: it carries no deadline today, so it already wins forever, and listing
# it means giving it one later cannot quietly reintroduce DRC-4095 by another door.
ENDS_A_WAIT: Final = frozenset({OVERLAY_WORKING, OVERLAY_IDLE})

# Claude's session id is a UUID. Anything outside this alphabet is not one, and a
# forged value with a path separator in it must not reach a prefix lookup.
_UUID_CHARS: Final = frozenset("0123456789abcdefABCDEF-")
# The collector keys on the first eight characters of the transcript filename,
# so a shorter id cannot be mapped to exactly one row.
_CLAUDE_SID_LEN: Final = 8
# Codex and Antigravity both key on the whole 36-character id, dashes included.
_WHOLE_UUID_LEN: Final = 36


@dataclass(frozen=True)
class Event:
    """One validated event, with its harness assigned by the ingress route.

    `sid` is the collector's key, not the native id: Claude's is the
    eight-character transcript prefix, and an overlay keyed on the raw UUID would
    never match its row. `session_id` is retained for diagnostics only.
    """

    harness: str
    event: str
    sid: str
    session_id: str
    timestamp: float
    arrival_seq: int
    source_instance_id: str | None = None
    source_sequence: int | None = None
    cwd: str | None = None
    subagent_id: str | None = None
    transcript_path: str | None = None
    # Set on `session_started` alone, and only by a hook inside tmux. Nothing
    # published carries any of the three; the coordinator holds them for the
    # focus command and the row publishes a boolean saying a target exists.
    tmux_socket: str | None = None
    tmux_pane: str | None = None
    tmux_server: str | None = None
    pattern_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True)
class Rejected:
    """Why an envelope produced no event. One of the REJECT_* reasons."""

    reason: str


@dataclass(frozen=True)
class Overlay:
    """A live semantic claim about one session, ordered by `arrival_seq`.

    `effective_at` is how the Idle dwell is expressed: a stop overlay exists
    immediately but does not apply until the dwell passes, so a user who stops
    and prompts again inside one coalescing window never sees the row flap.

    `expires_at` is set for Working and left None for Needs input. That
    asymmetry is deliberate and load-bearing. A missed stop must not pin Working
    forever, so Working gets a measured deadline. A real permission wait can last
    hours, so retiring Needs input requires positive evidence and never a
    generic timeout.
    """

    harness: str
    sid: str
    arrival_seq: int
    kind: str
    at: float
    detail: str | None = None
    effective_at: float = 0.0
    expires_at: float | None = None
    subagent_id: str | None = None
    event: str = ""
    source_class: str = SOURCE_CLASS_DISCRETE
    source_instance_id: str | None = None
    blocked_since: float | None = None
    lease_sec: float = 300.0

    def applies(self, *, now: float) -> bool:
        if now < self.effective_at:
            return False
        return self.expires_at is None or now < self.expires_at


def _text(payload: Mapping[str, Any], key: str, *, limit: int) -> str | None:
    """An allowlisted string field, or None if absent, wrongly typed or oversized.

    Wrong types are discarded rather than rejected. These fields are optional
    hints; refusing the whole event because a harness started sending a number
    where it used to send a string would take out a working adapter over a field
    nothing depends on.
    """
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit:
        return None
    return value


def _parse_timestamp(raw: str | None, *, config: RuntimeConfig, now: float) -> float:
    """ISO-8601 to epoch seconds, falling back to arrival time.

    Both fallbacks land on `now`: an unparseable stamp and an implausible one are
    the same problem from the display's point of view, and neither may be allowed
    to invent activity. `sessions.age` is the same plausibility filter every
    store timestamp passes through, so a container clock hours ahead cannot pin a
    row here either.

    The parse itself is `records.iso_epoch`, which holds the repo-wide rule that an
    offset-less stamp is UTC. This path had that rule inline and correct already;
    routing it through the shared helper is what keeps the four ISO readers from
    drifting apart again, which is how two of them came to disagree.
    """
    if raw is None:
        return now
    stamp = records.iso_epoch(raw)
    if stamp is None:
        return now
    if runtime_sessions.age(config, now, stamp) is None:
        return now
    return stamp


def _claude_sid(session_id: str) -> str | None:
    """Claude's collector key: the first eight characters of the UUID.

    Rejects anything that is not UUID-shaped, and anything shorter than the
    prefix the collector keys on. A shorter id would match every row sharing its
    prefix, which is an ambiguous mapping rather than a lookup, and the identity
    rule is that ambiguity is refused rather than guessed.
    """
    if len(session_id) < _CLAUDE_SID_LEN:
        return None
    if any(char not in _UUID_CHARS for char in session_id):
        return None
    return session_id[:_CLAUDE_SID_LEN]


def _whole_uuid_sid(session_id: str) -> str | None:
    """The collector key for a harness that keys on the whole id, unchanged.

    Codex, Antigravity, Gemini CLI and Droid all do, and all were measured rather
    than assumed:

    - Codex's hook payload carries its own `session_id`, and that value matched
      the `session_meta` id of the rollout file the same session wrote, which is
      what `collectors/codex.py` keys on.
    - Antigravity's status-line payload carries `session_id` and
      `conversation_id` holding the same value, and that value matched the stem
      of a real `conversations/<id>.db`, which is what `collectors/antigravity.py`
      keys on.
    - Gemini CLI's hook payload carries `session_id`, and in five recorded
      verdicts on 0.53.1 that value equalled the `sessionId` on line 1 of the
      `chats/session-*.jsonl` the same session wrote, which is what
      `collectors/gemini.py` keys on. Five verdicts rather than five sessions:
      `docs/captures/gemini/identity-0.53.1-macos.jsonl` records no session
      marker, so how many sessions wrote them is not something it can say. Note
      the store *filename* carries only the first eight characters; the id
      inside the file is whole, and the collector reads the file rather than the
      name.
    - Droid's hook payload carries `session_id`, and in recorded verdicts on
      0.202.0 that value equalled both the transcript filename stem and the
      `id` on line 1 `session_start` of the transcript the same session wrote,
      which is what `collectors/droid.py` keys on.

    So no truncation, unlike Claude. The shape is still validated: a value that is
    not UUID-shaped is not one of these ids, and must not reach a lookup. The
    length is checked exactly rather than as a floor, because these harnesses write
    36-character ids and a longer string that merely starts like one is not a
    near miss to be tolerated.
    """
    if len(session_id) != _WHOLE_UUID_LEN:
        return None
    if any(char not in _UUID_CHARS for char in session_id):
        return None
    return session_id


def _opencode_sid(session_id: str) -> str | None:
    """Keep the measured ses_ plus 26 ASCII alphanumeric characters whole.

    Current parent permission IDs share an eight-character prefix; truncation
    would join unrelated sessions. Child identity remains outside the promise.
    """
    suffix = session_id[4:]
    if not session_id.startswith("ses_") or len(suffix) != 26:
        return None
    return session_id if suffix.isascii() and suffix.isalnum() else None


def _pi_sid(session_id: str) -> str | None:
    # Pi 0.85.1: context id, persisted header id and collector sid matched whole.
    # Unlike a prefix, each of the five measured UUID groups must be present.
    if _whole_uuid_sid(session_id) is None:
        return None
    return session_id if [len(part) for part in session_id.split("-")] == [8, 4, 4, 4, 12] else None


# One normalizer per harness whose adapter has shipped. A harness absent here is
# refused: the design requires the identity mapping to be established per harness
# before its adapter ships, and a default passthrough would quietly skip that.
IDENTITY_NORMALIZERS: Final[dict[str, Any]] = {
    "claude": _claude_sid,
    "codex": _whole_uuid_sid,
    "antigravity": _whole_uuid_sid,
    "gemini": _whole_uuid_sid,
    "opencode": _opencode_sid,
    "pi": _pi_sid,
    "droid": _whole_uuid_sid,
}


def normalize_session_id(harness: str, session_id: str) -> str | None:
    """The collector key for a native id, or None if it cannot be mapped."""
    normalizer = IDENTITY_NORMALIZERS.get(harness)
    if normalizer is None:
        return None
    result = normalizer(session_id)
    return result if isinstance(result, str) and result else None


def _identify(harness: str, payload: Mapping[str, Any]) -> tuple[str, str, str] | Rejected:
    """Resolve name, native id and collector key, or say why none of them hold.

    Split out of `parse` so the accept path there reads as one construction. The
    checks are ordered, and the order is the contract: version first so an
    adapter too old for this server reports `incompatible` rather than tripping
    over a vocabulary it predates.
    """
    version = payload.get("v")
    # One condition, three ways to fail. `isinstance` comes first because a
    # missing or unhashable `v` would raise on the membership test, and the
    # `bool` clause is there because `bool` is an `int` in Python, so `True`
    # would otherwise read as version 1.
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version not in SUPPORTED_VERSIONS
    ):
        return Rejected(REJECT_INCOMPATIBLE)

    name = payload.get("event")
    if not isinstance(name, str) or name not in EVENT_NAMES:
        return Rejected(REJECT_UNKNOWN_EVENT)

    session_id = _text(payload, "session_id", limit=MAX_ID_LEN)
    if session_id is None:
        return Rejected(REJECT_MALFORMED)

    if harness not in IDENTITY_NORMALIZERS:
        return Rejected(REJECT_UNKNOWN_HARNESS)
    sid = normalize_session_id(harness, session_id)
    if sid is None:
        return Rejected(REJECT_UNMAPPABLE)
    return name, session_id, sid


def parse(
    harness: str,
    payload: Mapping[str, Any],
    *,
    arrival_seq: int,
    config: RuntimeConfig,
    now: float,
) -> Event | Rejected:
    """Validate one envelope. The harness comes from the route, never the body."""
    identified = _identify(harness, payload)
    if isinstance(identified, Rejected):
        return identified
    name, session_id, sid = identified

    if name == "command_shape_reported":
        pattern = payload.get("pattern_id")
        stamp = payload.get("timestamp")
        if (
            set(payload) != irreversible.REPORT_FIELDS
            or harness not in {"claude", "codex"}
            or not isinstance(pattern, str)
            or pattern not in irreversible.PATTERNS
            or payload.get("tool_name") != "Bash"
            or not isinstance(stamp, str)
            or len(stamp) > MAX_ID_LEN
            or records.iso_epoch(stamp) is None
        ):
            return Rejected(REJECT_MALFORMED)
        return Event(
            harness=harness,
            event=name,
            sid=sid,
            session_id=session_id,
            timestamp=_parse_timestamp(stamp, config=config, now=now),
            arrival_seq=arrival_seq,
            pattern_id=pattern,
            tool_name="Bash",
        )

    sequence = payload.get("source_sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        sequence = None
    raw_stamp = _text(payload, "timestamp", limit=MAX_ID_LEN)

    return Event(
        harness=harness,
        event=name,
        sid=sid,
        session_id=session_id,
        timestamp=_parse_timestamp(raw_stamp, config=config, now=now),
        arrival_seq=arrival_seq,
        source_instance_id=_text(payload, "source_instance_id", limit=MAX_ID_LEN),
        source_sequence=sequence,
        cwd=_text(payload, "cwd", limit=MAX_PATH_LEN),
        subagent_id=_text(payload, "subagent_id", limit=MAX_ID_LEN),
        transcript_path=_text(payload, "transcript_path", limit=MAX_PATH_LEN),
        tmux_socket=_text(payload, "tmux_socket", limit=MAX_TERMINAL_ID_LEN),
        tmux_pane=_text(payload, "tmux_pane", limit=MAX_TERMINAL_ID_LEN),
        tmux_server=_text(payload, "tmux_server", limit=MAX_TERMINAL_ID_LEN),
    )


def overlay_rows(overlays: Iterable[Overlay], *, now: float) -> list[dict[str, Any]]:
    """Reportable overlays in `arrival_seq` order, for the ledger and a dispute.

    Sorted here rather than by either caller, because a ledger holds one overlay
    per kind and re-recording a kind leaves it in its original dict slot: a wait
    at seq 2 outranked by a working overlay at seq 3 comes back working-first.
    That is the one case a reader most needs to see in order, since comparing the
    two sequences is how
    [N-5](docs/design-needs-input.md#n-5)'s
    second reading is told from its first.
    """
    return [
        overlay_row(overlay, now=now)
        for overlay in sorted(overlays, key=lambda overlay: overlay.arrival_seq)
    ]


def overlay_row(overlay: Overlay, *, now: float) -> dict[str, Any]:
    """One overlay as reportable fields, for `/api/overlays` and dispute records.

    Here rather than in either caller so the two never drift: a dispute is read
    against the live ledger, and a field that means one thing in one and another
    in the other would be worse than not recording it.

    `time_gate_open` is `applies`, renamed because on the wire `applies` reads as
    "this overlay won", which is a different and later question.
    """
    return {
        "harness": overlay.harness,
        "sid": overlay.sid,
        "kind": overlay.kind,
        "arrival_seq": overlay.arrival_seq,
        "at": overlay.at,
        "effective_at": overlay.effective_at,
        "expires_at": overlay.expires_at,
        "subagent_id": overlay.subagent_id,
        "time_gate_open": overlay.applies(now=now),
    }


def source_class_for(event: Event) -> str:
    """Classify an event's source as repeating (status-line render) or discrete (lifecycle hook).

    Antigravity's statusline is a repeating render that sends frequent heartbeats
    carrying a source_instance_id. All other sources (lifecycle hooks, plugins, extensions)
    are discrete edges.
    """
    if event.harness == "antigravity" and event.source_instance_id is not None:
        return SOURCE_CLASS_REPEATING
    return SOURCE_CLASS_DISCRETE


def overlay_for(event: Event, *, config: RuntimeConfig) -> Overlay | None:
    """The semantic claim an event makes, or None if it only means "look again".

    Five native shapes are stronger than the store: a prompt means Working, an
    explicit permission request means Needs input, a reply or resumed activity
    means Working again, a stop means Idle after a dwell, and a subagent
    transition changes child activity. Everything else here is a hint that the
    store probably moved, and a hint has no business patching a display field.

    `session_started` is deliberately a hint. It says a session exists, which the
    collector already knows better, and it says nothing about whether the agent
    is doing anything.
    """
    source_class = source_class_for(event)
    if event.event in {"turn_started", "input_resolved"}:
        return Overlay(
            harness=event.harness,
            sid=event.sid,
            arrival_seq=event.arrival_seq,
            kind=OVERLAY_WORKING,
            at=event.timestamp,
            expires_at=event.timestamp + config.overlay_working_ttl_sec,
            event=event.event,
            source_class=source_class,
            source_instance_id=event.source_instance_id,
        )
    if event.event == "input_requested":
        return Overlay(
            harness=event.harness,
            sid=event.sid,
            arrival_seq=event.arrival_seq,
            kind=OVERLAY_NEEDS_INPUT,
            at=event.timestamp,
            event=event.event,
            source_class=source_class,
            source_instance_id=event.source_instance_id,
            blocked_since=event.timestamp,
            lease_sec=config.overlay_repeating_wait_lease_sec,
        )
    if event.event == "turn_stopped":
        return Overlay(
            harness=event.harness,
            sid=event.sid,
            arrival_seq=event.arrival_seq,
            kind=OVERLAY_IDLE,
            at=event.timestamp,
            effective_at=event.timestamp + config.overlay_idle_dwell_sec,
            event=event.event,
            source_class=source_class,
            source_instance_id=event.source_instance_id,
        )
    if event.event in {"subagent_started", "subagent_stopped"}:
        return Overlay(
            harness=event.harness,
            sid=event.sid,
            arrival_seq=event.arrival_seq,
            kind=OVERLAY_SUBAGENT,
            at=event.timestamp,
            effective_at=event.timestamp if event.event == "subagent_started" else 0.0,
            subagent_id=event.subagent_id,
            event=event.event,
            source_class=source_class,
            source_instance_id=event.source_instance_id,
        )
    return None


def retires_overlays(event: Event) -> bool:
    """Whether this event ends a session's overlay history.

    `session_ended` is non-destructive: it retires overlays and hook state and
    never removes a row, because only the collector may decide a session is gone.
    Claude fires it on `/clear` as well as on exit, so the very next event may be
    a `turn_started` for the same session inside one coalescing window; the
    retirement is by arrival order, which keeps that sequence coherent.
    """
    return event.event == "session_ended"


def reopens_session(event: Event) -> bool:
    """Whether this event says the session id is in use again.

    `session_started` alone, and it is a predicate here rather than a branch in
    the coordinator so the one event name that lifts an end mark is written down
    beside the one that sets it. It produces no overlay (see `overlay_for`), so
    without an explicit path it would reach neither the ledger nor the mark, and
    `claude --resume <id>` — which reuses the id — would leave the row reading
    ended for the rest of the run.
    """
    return event.event == "session_started"


def requires_reconcile(event: Event) -> bool:
    """Whether this event invalidates caches rather than describing activity.

    Compaction is the case that matters. Neither compaction hook counts as
    activity, and a rewritten transcript is not repaired by replaying overlays.
    """
    return event.event == "reconcile_required"


def _side_channel_patch(
    *,
    finished_at: float,
    ended_at: float,
    session_activity: float,
    activity_grace_sec: float,
    git: tuple[bool, int] | None,
) -> dict[str, Any]:
    """The patch from what the coordinator remembers OUTSIDE the overlay ledger.

    Both readings are here because `session_ended` pops that ledger whole, so
    neither could survive in it. Both are reduced rather than written straight onto
    the row so that they pass the same activity guard an idle overlay does: a mark
    applied outside the reducer would survive a session resuming and reintroduce
    DRC-4101 by another door.

    The git reading rides `finished_at`'s guard because the two answer about the
    same moment — a session that wrote after its stop was observed has a tree the
    probe's reading no longer describes.

    It rides the mark's PRESENCE too, and that half is the correction: `not
    stale` alone is vacuously true whenever `finished_at` is 0.0, which is
    precisely the state `observation._mark_finished` produces when it pops the
    mark on a working or waiting overlay. `session_ended` (reading recorded) then
    `turn_started` left the pair unguarded, and once the working overlay lapsed
    at `overlay_working_ttl_sec` nothing nulled it, so a clean tree republished
    as `dirty: false` over a session that kept working — permanently, because
    `note_rows` keeps the reading while the row is still collected. That is
    null's job done by false, the failure pattern recorded in DRC-4101.
    """
    stale = bool(finished_at) and session_activity > finished_at + activity_grace_sec
    # One condition for both, because both describe the same observed stop and
    # neither is answerable without it.
    fresh = bool(finished_at) and not stale
    patch: dict[str, Any] = {}
    if fresh:
        patch["finished_at"] = finished_at
    if git is not None and fresh:
        patch["dirty"], patch["changed"] = git
    # Deliberately outside that guard, and this is the one place the two marks
    # differ. A stop is a reading of a moment, so later writing in the tree
    # invalidates it; an end is a fact about an id, and the id cannot write again
    # without a `session_started`, which retires the mark at the coordinator. An
    # end also lands AFTER the last write rather than before it — 5.581 s after
    # the final Stop in the a1 arm of
    # docs/captures/claude/session-end-2.1.261-macos.jsonl — so an activity guard
    # here would be reading a normal ending as a contradiction.
    if ended_at:
        patch["ended_at"] = ended_at
    return patch


def _is_wait_superseded(wait: Overlay, ordered: list[Overlay]) -> bool:
    """Whether a needs-input overlay has been permanently retired by a later overlay.

    For repeating sources: ordinary Working and Idle renders (turn_started, turn_stopped)
    do not retire the wait. Only a matching explicit resolution (input_resolved from the
    same harness and source_instance_id) permanently retires it.

    For discrete sources: any later discrete overlay in ENDS_A_WAIT (turn_started, turn_stopped)
    or explicit resolution permanently supersedes the wait.
    """
    if wait.source_class == SOURCE_CLASS_REPEATING:
        return any(
            other.arrival_seq > wait.arrival_seq
            and other.event == "input_resolved"
            and (other.harness, other.source_instance_id) == (wait.harness, wait.source_instance_id)
            for other in ordered
        )
    return any(
        other.arrival_seq > wait.arrival_seq
        and (
            (other.kind in ENDS_A_WAIT and other.source_class != SOURCE_CLASS_REPEATING)
            or other.event == "input_resolved"
        )
        for other in ordered
    )


def _active_repeating_sources(
    ordered: list[Overlay], *, own_activity: float, grace: float
) -> set[tuple[str, str | None]]:
    """Repeating sources with a standing wait that outranks ordinary heartbeats."""
    return {
        (o.harness, o.source_instance_id)
        for o in ordered
        if o.kind == OVERLAY_NEEDS_INPUT
        and o.source_class == SOURCE_CLASS_REPEATING
        and not _is_wait_superseded(o, ordered)
        and not (own_activity > o.at + grace)
    }


def _is_overlay_suppressed(
    overlay: Overlay,
    *,
    ordered: list[Overlay],
    active_repeating: set[tuple[str, str | None]],
    own_activity: float,
    session_activity: float,
    grace: float,
) -> bool:
    """Whether an overlay should be skipped during reduction."""
    if overlay.kind == OVERLAY_NEEDS_INPUT:
        return _is_wait_superseded(overlay, ordered) or own_activity > overlay.at + grace
    if active_repeating:
        active_harnesses = {h for (h, _) in active_repeating}
        if overlay.harness in active_harnesses:
            return True
    if overlay.kind == OVERLAY_IDLE:
        return session_activity > overlay.at + grace
    return False


def _needs_input_patch(overlay: Overlay, ordered: list[Overlay], *, now: float) -> dict[str, Any]:
    """Build the patch for a needs-input overlay, computing wait lease and unconfirmed state."""
    blocked_since = overlay.blocked_since if overlay.blocked_since is not None else overlay.at
    is_unconfirmed = False
    if overlay.source_class == SOURCE_CLASS_REPEATING:
        matching = [
            o
            for o in ordered
            if o.kind == OVERLAY_NEEDS_INPUT
            and o.source_class == SOURCE_CLASS_REPEATING
            and (o.harness, o.source_instance_id) == (overlay.harness, overlay.source_instance_id)
            and not _is_wait_superseded(o, ordered)
        ]
        if matching:
            earliest_start = min(
                o.blocked_since if o.blocked_since is not None else o.at for o in matching
            )
            latest_pos = max(o.at for o in matching)
            lease = max(o.lease_sec for o in matching)
            blocked_since = earliest_start
            is_unconfirmed = now >= latest_pos + lease
    return {
        "state": "needs_input",
        "state_detail": overlay.detail,
        "active": True,
        "blocked_since": blocked_since,
        "wait_unconfirmed": is_unconfirmed,
        "acquisition": ACQUISITION_EVENT,
        "finished_at": None,
        "ended_at": None,
        "dirty": None,
        "changed": None,
    }


def reduce_overlays(  # noqa: PLR0913 - each argument is independently sourced collector evidence
    overlays: Iterable[Overlay],
    *,
    now: float,
    own_activity: float = 0.0,
    session_activity: float = 0.0,
    activity_grace_sec: float = 0.0,
    finished_at: float = 0.0,
    ended_at: float = 0.0,
    work_in_flight_until: float = 0.0,
    git: tuple[bool, int] | None = None,
) -> dict[str, Any]:
    """The field patch a session's live overlays imply, in `arrival_seq` order.

    Last writer wins per field, which is why the sort is by `arrival_seq` and not
    by timestamp: only the server's own counter is trustworthy enough to order
    two hook processes that raced.

    Subagent overlays are recorded but patch nothing here. A child starting or
    stopping does not change what the parent is doing, and the parent's subagent
    list is reconstructed by the collector, which is the only thing that knows
    the whole tree.

    A needs-input overlay is superseded permanently once a later overlay says the
    session is no longer waiting, and the check deliberately ignores whether that
    later overlay is still live. Outranking alone was not enough (DRC-4095): a
    needs-input overlay has no deadline, so when the working overlay that outranked
    it lapsed, the wait applied again carrying its original `blocked_since`, and a
    turn still running past `overlay_working_ttl_sec` reverted to "waiting for you"
    while claiming to have been waiting the whole time. Once a turn has started the
    earlier wait is over as a matter of history, and history does not lapse.

    For repeating sources (e.g. status-line renders), ordinary Working and Idle
    heartbeats neither clear nor renew a standing wait: the wait outranks ordinary
    heartbeats from that same source, preserving its original `blocked_since`
    ([N-14](docs/design-needs-input.md#n-14)).
    After `overlay.lease_sec` (300 seconds) without a fresh positive
    observation, the wait is visibly marked unconfirmed (`wait_unconfirmed: True`).
    Only a matching explicit resolution (`input_resolved`) or session end
    permanently retires it.

    A wait is also over once the session's own transcript has moved on past it.
    Claude has no hook for a permission being *granted* — `UserPromptSubmit` and
    `Stop` are the only overlays that end a wait, and neither fires mid-turn — so
    without this a permission approved thirty seconds in leaves the row in the red
    band for the rest of the turn, counted in the Needs-you tile and popped as a
    notification, while the session generates (DRC-4097). `own_activity` is the
    parent transcript alone and never the subagents below it: a background agent
    writing says nothing about whether the human has answered, and clearing a
    genuine wait is the worse error of the two.

    An idle overlay is superseded the same way, and for the same reason one turn
    later (DRC-4101). `turn_stopped` is the only overlay that says a session
    stopped, and nothing lifts it but a later `turn_started` — which a session
    resumed by anything other than a user prompt never emits. A background task
    completing, a workflow finishing, any harness-driven continuation: the turn
    restarts, no hook fires, and the idle overlay from the previous stop applies
    forever. Without this guard a session writing its transcript at 4,000 tokens
    a minute with a subagent running was published as `state: "idle"`,
    `active: false`, because an overlay with no deadline outranked every
    collected field around it.

    The two guards read *different* activity on purpose, and the difference is
    the point rather than an oversight. A wait ends only when the parent moves,
    because the human answers the parent. Idleness ends when *anything under the
    session* moves, because a running subagent is proof the session is not idle
    even while the parent transcript is parked — which is exactly the shape of a
    long workflow, and the shape that produced the bug. So idle takes
    `session_activity`, the collector's whole-tree reading, where a wait takes
    `own_activity`. Both default to 0 so a collector that reports neither leaves
    its overlays standing, which is the safe direction: it keeps the event path
    authoritative for harnesses whose rows carry no activity stamp.

    `finished_at` is a stop the coordinator remembers *outside* the ledger, and
    it is a separate argument rather than a fifth overlay kind because the ledger
    is popped whole on `session_ended` — which for `claude -p` arrives
    milliseconds after the stop, destroying the mark for precisely the sessions
    that finished and were never read (DRC-4035). It is reduced here, and not
    written onto the row by whoever remembers it, so that it passes through the
    same activity guard the idle overlay does: a mark applied outside this
    function would survive a session resuming and reintroduce DRC-4101 by
    another door. A live overlay still wins over it — a working or waiting row
    clears the mark, and a live stop restates its own stamp.

    `ended_at` is the same kind of side-channel argument and answers a different
    question: not "did a turn stop" but "is this session id over" (DRC-4036). A
    working or waiting overlay clears it for the same reason it clears the stop,
    since a session doing something has not ended. An idle overlay does not, and
    that asymmetry is the deliberate part: every tidy ending has a `turn_stopped`
    in front of it, so nulling here would erase the mark for exactly the sessions
    it exists to distinguish. It also skips the activity guard the stop takes —
    `_side_channel_patch` says why.

    `work_in_flight_until` is the Claude collector's capped outstanding-work
    evidence. While it stands, Idle and remembered turn stops yield, but a
    needs-input overlay keeps its normal precedence and actual activity guard.
    An observed session end disables this exception.
    """
    ordered = sorted(overlays, key=lambda item: item.arrival_seq)
    active_repeating = _active_repeating_sources(
        ordered, own_activity=own_activity, grace=activity_grace_sec
    )
    patch: dict[str, Any] = _side_channel_patch(
        finished_at=finished_at,
        ended_at=ended_at,
        session_activity=session_activity,
        activity_grace_sec=activity_grace_sec,
        git=git,
    )
    # A headless parent's Stop can precede its background task completing. The
    # collector supplies a bounded lease, not activity that could clear a prompt.
    # docs/design-event-driven-observation.md#event-overlays-versus-store-truth
    in_flight = bool(work_in_flight_until) and work_in_flight_until >= now and not ended_at
    if in_flight:
        patch["finished_at"] = None
    for overlay in ordered:
        if in_flight and overlay.kind == OVERLAY_IDLE:
            continue
        if _is_overlay_suppressed(
            overlay,
            ordered=ordered,
            active_repeating=active_repeating,
            own_activity=own_activity,
            session_activity=session_activity,
            grace=activity_grace_sec,
        ):
            continue
        if not overlay.applies(now=now):
            continue
        if overlay.kind == OVERLAY_WORKING:
            patch.update(
                {
                    "state": "working",
                    "state_detail": overlay.detail,
                    "active": True,
                    "blocked_since": None,
                    "wait_unconfirmed": False,
                    "acquisition": ACQUISITION_EVENT,
                    "finished_at": None,
                    # A session doing something has not ended, whatever this
                    # process remembers about an id it saw end.
                    "ended_at": None,
                    # Working again: whatever the probe saw at the last session
                    # end is a reading of a tree this session has since moved on
                    # from, and a stale dirty count is worse than none.
                    "dirty": None,
                    "changed": None,
                }
            )
        elif overlay.kind == OVERLAY_NEEDS_INPUT:
            patch.update(_needs_input_patch(overlay, ordered, now=now))
        elif overlay.kind == OVERLAY_IDLE:
            patch.update(
                {
                    "state": "idle",
                    "state_detail": None,
                    "active": False,
                    "blocked_since": None,
                    "wait_unconfirmed": False,
                    "acquisition": ACQUISITION_EVENT,
                    "finished_at": overlay.at,
                    # `ended_at` is deliberately NOT restated here. A
                    # `turn_stopped` is not evidence a session reopened: every
                    # tidy ending has one in front of it, and delivery is
                    # at-least-once and reorderable, so nulling on idle would
                    # erase the mark for exactly the endings it exists to show.
                    # A turn stop is not a session end, and only a session end
                    # runs the probe. A live idle overlay therefore means a turn
                    # ran after the reading was taken, so it no longer holds.
                    "dirty": None,
                    "changed": None,
                }
            )
    return patch


def apply_patch(session: dict[str, Any], patch: Mapping[str, Any]) -> None:
    """Write a reduced patch onto a collected row, in place.

    Filtered against `PATCHABLE` rather than trusted, so a reducer that grows a
    key by mistake cannot rewrite a title or a token rate. An overlay patches a
    row; it never creates or deletes one, and this signature is what enforces
    that: there is no row to hand it unless a collector produced one.
    """
    session.update({key: value for key, value in patch.items() if key in PATCHABLE})
