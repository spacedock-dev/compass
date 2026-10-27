"""Harness registry, per-harness failure boundary, collection, and the application."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol, TypeAlias

from . import annotations as annotation_store
from . import (
    copied_corrections,
    deliveries,
    departures,
    dismissals,
    notifications,
    observer,
    quota,
    reach,
    reading,
    reading_policy,
    reading_route,
    records,
    sessions,
    summary_jobs,
    summary_store,
    tripwires,
    unasked,
)
from . import ends as runtime_ends
from . import events as runtime_events
from . import io as runtime_io
from . import snapshot as runtime_snapshot
from .web import page as frontend_page

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from .config import RuntimeConfig
    from .events import Overlay
    from .git_status import GitStatus
    from .sessions import Session
    from .state import RuntimeState
    from .unasked import Lane as UnaskedLane


_STATE_RANK: Final = {"needs_input": 0, "working": 1, "idle": 2}


def row_order(session: Session) -> tuple[int, float, str]:
    """Where a row sits in the published payload: state, then wait, then id.

    Session id as the last tiebreaker (not last_activity) so rows don't reshuffle
    on every refresh while sessions are generating.

    The middle key is the gate queue: blocked rows arrive longest-blocked first,
    because session id is an arbitrary order to be stopped in and the gate that
    has held someone up longest is the one still costing something. It ranks on
    the timestamp rather than on the elapsed wait so that the order cannot churn
    as every row in it waits longer.

    `last_activity` stands in where a wait carries no `blocked_since`: only the
    Claude, Copilot and Cursor collectors and the event overlays set that field,
    and a harness without it must still take a place in the queue rather than
    sorting to the front on a zero.
    """
    wait = 0.0
    if session["state"] == "needs_input":
        wait = float(session.get("blocked_since") or session.get("last_activity") or 0)
    return (_STATE_RANK.get(session["state"], 3), wait, str(session["sid"]))


def _keep_wait_detail(session: Session, patch: Mapping[str, Any]) -> Mapping[str, Any]:
    """The patch, minus a `state_detail` that would blank a standing wait.

    No overlay constructor sets `detail`, so every needs-input patch carries
    None, and applying it erased whatever the collector had found. For a Claude
    row that is the open question itself, which is the one thing a person
    stopped at a gate wants to read.

    Narrow on purpose. It applies only when the row was already Needs input and
    stays Needs input, because the overlay is then agreeing about the state and
    disagreeing about nothing. Working and Idle must keep clearing the field, or
    a working detail such as `running Bash` follows the row into a wait, and a
    question that has been answered outlives the overlay that retired it.
    """
    if session.get("state") != "needs_input" or patch.get("state") != "needs_input":
        return patch
    if patch.get("state_detail") is not None or not session.get("state_detail"):
        return patch
    return {key: value for key, value in patch.items() if key != "state_detail"}


def _wait_popup_body(session: Session) -> str:
    """The popup body for a gated row: its project, and what it is waiting on.

    The page's notifier composes the same two fields with the same fallback, and the two
    must agree because either layer may be the one that delivers a given gate.
    The fallback is not decoration: no overlay constructor sets `detail`, so
    every needs-input patch from the event lane carries None, and that lane is
    the whole of how a Codex gate is detected. Composing here also means
    `maybe_popup`'s own default can never fire — an f-string is truthy — so the
    empty case has to be answered before the call.
    """
    return f"[{session.get('project')}] {session.get('state_detail') or 'needs your input'}"


def _subtract_dismissed(
    out_sessions: list[Session],
    cleared_marks: tuple[dismissals.Dismissal, ...],
) -> tuple[list[Session], int]:
    """The rows no standing dismissal covers, and how many it removed.

    Called after the overlays and before the display ids, and both halves
    matter. After, because `_apply_overlays` ends in `note_rows`, which expires
    any overlay whose key was not reported — subtract first and a dismissed
    session that comes back has lost its pending permission overlay. Before
    `assign_display_ids`, so the id widths describe the rows actually on screen.

    A count and not a filtered flag, because a dismissal silences an alert
    through `maybe_popup`'s own gate rather than by hiding the row from it. See
    [D-3](docs/design-dismissals.md#d-3).
    """
    kept = [
        session
        for session in out_sessions
        if not dismissals.holds(
            cleared_marks,
            str(session["harness"]),
            str(session["sid"]),
            float(session.get("last_activity") or 0.0),
        )
    ]
    return kept, len(out_sessions) - len(kept)


class HistoryLane(Protocol):
    """The local history store, as the collection reaches it.

    Declared here rather than imported for the reason `OverlaySource` is: the
    dependency would otherwise run outward from the module that owns collection
    toward one that owns a file. `history` is a leaf over `config` alone, and it
    stays one.

    Injected at assembly rather than reached through `overlays`, because that
    source is None forever under `--no-events` and history's only off switch is
    `--no-history`.
    """

    def record(self, rows: Iterable[Mapping[str, Any]], *, now: float) -> list[dict[str, Any]]: ...

    def notice(self) -> str | None: ...


class OverlaySource(Protocol):
    """The narrow view of the coordinator that a collection needs.

    The first two run the traffic both ways. A collection reads the overlays for
    each row it produced, and then reports back which rows exist at all, which is
    how an overlay for a session no collection has yet seen resolves or expires.
    Stated as a Protocol so `aggregate` stays below `observation` and the
    dependency does not invert.

    `drop_counters` is neither: it is read only when a dispute is recorded, and
    it is here because an envelope that arrived and was dropped leaves no overlay
    to find. Without it a record cannot separate that from one never posted,
    which is two of the four readings in
    [N-5](docs/design-needs-input.md#n-5).

    `finished_at` is separate from `overlays_for` because it deliberately
    outlives the ledger: `session_ended` retires a session's overlays, and a
    `claude -p` run that finished and exited is exactly the row the mark is for.

    `ended_at` outlives it for the stronger version of that reason: the event
    that sets it is the event that pops the ledger, so it could never have lived
    there at all.
    """

    def overlays_for(self, harness: str, sid: str) -> list[Overlay]: ...

    def finished_at(self, harness: str, sid: str) -> float: ...

    def ended_at(self, harness: str, sid: str) -> float: ...

    def git_for(self, harness: str, sid: str) -> GitStatus | None: ...

    def focusable(self, harness: str, sid: str) -> bool: ...

    def note_rows(self, keys: set[tuple[str, str]]) -> None: ...

    def drop_counters(self) -> dict[str, int]: ...

    def command_reports(self) -> list[dict[str, Any]]: ...


Collection: TypeAlias = dict[str, Any]
Discoverer: TypeAlias = Callable[["RuntimeConfig", "RuntimeState"], bool]
Collector: TypeAlias = Callable[
    ["RuntimeConfig", "RuntimeState", float, float, bool],
    "list[Session]",
]
UsageProvider: TypeAlias = Callable[
    ["RuntimeConfig", "RuntimeState", float, float],
    "list[dict[str, Any]]",
]


@dataclass(frozen=True)
class HarnessSpec:
    """One supported harness: how to discover its store and how to read it.

    ``usage`` is the optional quota reader. Most harnesses have none: the
    survey behind [DEC-1](docs/design-usage-quota.md#design-the-usage-quota-surface) found Codex
    alone writing quota to disk, and every other vendor keeping it behind an authenticated API.
    The field is where
    a quota source plugs in without widening the ``Collector`` contract.

    ``usage_is_fetch`` marks a provider whose numbers come from the network
    fetcher rather than from disk. Its presence on a discovered harness is
    what raises the payload's ``usage_fetch`` capability flag, and that flag
    is what wakes the page's first-run disclosure banner — a disk reader like
    Codex's must never raise it.

    ``reports_rate`` says whether this harness's collector can populate
    ``rate_per_min`` at all. Four of the ten cannot: OpenCode, Cursor and Droid
    read no token accounting, and Copilot's store carries only quota receipts.
    Those rows publish null, while a reporting harness sends 0 for a session
    that generated nothing in the window. Declaring the capability here keeps
    collector defaults numeric while the application can still make the wire
    value honest and consumers can rank a real zero.

    ``reports_needs_input`` is the same shape on the field where getting it
    wrong costs more. Four of the ten cannot observe a gate at all, and their
    silence is byte-identical to the silence of one that can when nothing is
    waiting: no row, no count, no band. So a quiet board cannot say whether
    nothing is waiting or nothing could have told you, and the
    [gate inventory](docs/design-needs-input.md#n-1) notes that
    a reader assumes the former because everything else here is harness-agnostic.
    A `reports_rate` false row renders a dash; this one has nothing to draw a
    dash on, which is why the disclosure has to be per harness rather than per
    row.

    ``reports_needs_input_when`` qualifies that capability on a row whose
    mechanism can be switched off, and Codex is the one such row: its gate
    arrives through a permission hook, so an operator running with approvals
    disabled has a harness that reports a gate in principle and never will in
    practice. That is the all-clear reading the flag above exists to prevent,
    reaching the reader as silence rather than as a chip. Declared here rather
    than read off the harness's own config, which was tried and ruled out:
    `approval_policy` is overridable per invocation and per project, so a global
    read cannot say whether a given session will ask, and being wrong publishes
    "no gate observable here" over a session sitting at a prompt. It stays None
    everywhere else, because a condition is a property of a mechanism and the
    other mechanisms have none.

    It answers "can a gate on this harness reach the board", by ANY path -- not
    "can this collector detect one". The distinction is the whole of what the
    first review of this field caught: Codex reports a gate through the event
    overlay and has no collector detection at all, so a flag meaning the second
    thing labelled Codex blind on the same screen where a Codex gate was red.
    That is the inversion this field exists to prevent, shipped by the field
    itself. `tests/test_harness_registry.py` derives the expected set instead of
    listing it: every collector module is parsed for the state it actually
    writes, unioned with every harness whose adapter maps `input_requested` and
    which `events.IDENTITY_NORMALIZERS` will admit, because a hand-set bool
    beside a hand-written literal pinned the bug green. That union used to read
    `EVENTS_BY_HARNESS` alone, which is one adapter shape and not the table the
    server admits on, so it refused a truthful declaration for Antigravity
    (DRC-4440). The same file holds the count in the sentence above to the registry,
    since nothing else does and it has been wrong twice.
    """

    key: str
    label: str
    discover: Discoverer
    collect: Collector
    reports_rate: bool = False
    reports_needs_input: bool = False
    reports_needs_input_when: str | None = None
    reports_turn_bounds: bool = True
    usage: UsageProvider | None = None
    usage_is_fetch: bool = False


def default_harnesses(*, usage_fetch_enabled: bool = True) -> tuple[HarnessSpec, ...]:
    """Every supported harness, in display order.

    No collector notifies. Claude's did until DRC-4192, and this function took
    the popup notifier to bind that one row; the popup decision now belongs to
    `Application`, which is the only place that sees a row's final state, so
    ``Collector`` is one five-argument contract and every row is the collector
    module's own attribute.

    ``usage_fetch_enabled`` is ``--no-usage`` arriving at assembly: with the
    fetch off, no row that depends on the fetch keeps a usage provider, so
    nothing ever reads the fetch cache and the ``usage_fetch`` flag can never
    rise. That covers Claude and Cursor, which fetch, and Antigravity, whose
    quota is pushed rather than fetched but which the flag still drops because
    turning usage off means the whole section.
    """
    from .collectors import (  # noqa: PLC0415 — deferred to keep import order acyclic
        antigravity,
        claude,
        codex,
        copilot,
        cursor,
        droid,
        gemini,
        goose,
        opencode,
        pi,
    )

    return (
        HarnessSpec(
            "claude",
            "Claude",
            claude.discover,
            claude.collect,
            reports_rate=True,
            # Three paths, more than any other row: the bundled hook, an
            # actionable Notification POST, and a pending input tool in the
            # transcript. Codex, Copilot and Cursor have one apiece; the
            # remaining six are tracked per harness in
            # [gate inventory](docs/design-needs-input.md#n-1).
            reports_needs_input=True,
            usage=claude.usage if usage_fetch_enabled else None,
            usage_is_fetch=True,
        ),
        HarnessSpec(
            "codex",
            "Codex",
            codex.discover,
            codex.collect,
            reports_rate=True,
            # Through the event overlay, not the collector: its bundled
            # `PermissionRequest` hook maps to `input_requested`. Measured on
            # 0.149.0 -- the hook fires with the prompt open, and a hook that
            # prints nothing lets that prompt reach the human. A hook on a
            # prompt that never opens never fires, so the same measurement
            # bounds the capability: it holds where the operator asks to be
            # asked, and nowhere else.
            reports_needs_input=True,
            reports_needs_input_when="where approvals are enabled",
            usage=codex.usage,
        ),
        HarnessSpec(
            "pi",
            "Pi",
            pi.discover,
            pi.collect,
            reports_rate=True,
            reports_needs_input=True,
            reports_needs_input_when=(
                "extension UI prompts in persisted sessions; "
                "installed adapter on Pi 0.85.1 required; "
                "excludes startup trust; restart loses standing waits"
            ),
        ),
        # Gemini CLI was retired on 2026-06-18 and Antigravity replaced it.
        # They shared this row while both were Google's current surface; the
        # legacy row stays so a machine that ran Gemini CLI keeps its history.
        HarnessSpec("gemini", "Gemini", gemini.discover, gemini.collect, reports_rate=True),
        # Antigravity's quota arrives as a pushed status-line receipt rather
        # than a fetch, so `usage_is_fetch` stays False: there is no outbound
        # request to disclose, and the first-run banner must not appear for it.
        # `--no-usage` still drops the provider, because a user turning usage
        # off means the whole section, not just the network half.
        HarnessSpec(
            "antigravity",
            "Antigravity",
            antigravity.discover,
            antigravity.collect,
            reports_rate=True,
            usage=antigravity.usage if usage_fetch_enabled else None,
        ),
        # Copilot, OpenCode, Cursor and Droid leave `reports_rate` at False, and
        # it is a reading of their stores rather than a gap in their collectors:
        # OpenCode, Cursor and Droid record no token accounting, and Copilot's
        # store carries AI-Unit quota receipts and no per-message token counts.
        HarnessSpec(
            "copilot",
            "Copilot",
            copilot.discover,
            copilot.collect,
            # The third route, and neither of the other two: its own collector
            # reads the gate off the store. Copilot writes `permission.requested`
            # to `events.jsonl` when the dialog opens and `permission.completed`
            # only when the human answers, joined on `data.requestId`, so an
            # unanswered pair in the tail IS the standing prompt. No hook, no
            # adapter, nothing for the user to install.
            reports_needs_input=True,
            usage=copilot.usage,
        ),
        HarnessSpec(
            "opencode",
            "OpenCode",
            opencode.discover,
            opencode.collect,
            reports_needs_input=True,
            reports_needs_input_when=(
                "for parent sessions where the project adapter is installed and events are enabled"
            ),
        ),
        # Cursor's allowance is money against a monthly billing cycle, fetched
        # from the RPC its own CLI calls, so this is a second `usage_is_fetch`
        # row: the disclosure banner must cover it exactly as it covers Claude.
        HarnessSpec(
            "cursor",
            "Cursor",
            cursor.discover,
            cursor.collect,
            # Copilot's route, on a different store: the collector reads it, no
            # hook and nothing to install. A standing tool-call gate leaves a
            # non-empty `pendingToolExecutionContracts` on the newest blob of the
            # chat's SQLite store, and the answer appends one with the map
            # emptied. The hook surface is a decided negative and stays one:
            # `beforeShellExecution` runs BEFORE the permission decision and
            # feeds into it, so a wait posted from there would paint every Cursor
            # row on its first command.
            reports_needs_input=True,
            reports_turn_bounds=False,
            usage=cursor.usage if usage_fetch_enabled else None,
            usage_is_fetch=True,
        ),
        HarnessSpec("goose", "Goose", goose.discover, goose.collect, reports_rate=True),
        HarnessSpec("droid", "Droid", droid.discover, droid.collect),
    )


# The published fields that never pass through `records.safe_text`, and the
# nested lists that hold more of them. A table rather than a block per field:
# four blocks are what let `state_detail` and `subagents[].name` be forgotten,
# and a line in a list is harder to leave out than a paragraph of loop.
#
# `state_detail` earns its place twice over. It is built by hand from the same
# transcript text — an in-progress task's `activeForm` is copied into it BEFORE
# the sweep runs — and it is read at ten render sites across six web files,
# including notification text, which can leave the page through the native or
# browser notifier.
_RAW_ROW_TEXT: Final = (
    "title",
    "last_prompt",
    "state_detail",
    "project_key",
    "project_name",
    "worktree",
)

# `(the row field holding a list of dicts, the keys inside each one)`.
#
# A task subject is the agent's wording rather than the operator's, so it is not
# prompt-derived in the sense DRC-4267 uses; it is here because a todo written
# from a prompt that held a key can quote it. A subagent name is operator text
# outright on four harnesses: opencode publishes the child session's own TITLE
# there, the same string this sweep redacts when that session is a parent row,
# and goose, codex and claude slice theirs out of the record with no `safe_text`
# in the way.
#
# `parent` is the same string as `name` one key over: DRC-4344 added it from the
# same `agentName` slice and did not add it here, so one key came back redacted
# and the other raw. That is the third field on this element left out on a
# second reading, after `state_detail` and `name`, which is the whole argument
# for the table.
_RAW_NESTED_TEXT: Final = (
    ("tasks", ("subject", "activeForm")),
    ("subagents", ("name", "parent")),
)


def _redact_in_place(holder: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        value = holder.get(key)
        if isinstance(value, str) and value:
            holder[key] = records.redact_secrets(value)


def _harness_row(spec: HarnessSpec, *, found: bool) -> dict[str, Any]:
    """One harness's published row, before its collector has run.

    Lifted out of `collect` rather than inlined there: the coverage fields are
    properties of the store rather than of this pass, so they read better beside
    the spec than in the middle of a loop that is also collecting sessions,
    quota and overlays.
    """
    return {
        "key": spec.key,
        "label": spec.label,
        "discovered": found,
        # Whether a `rate_per_min` from this harness is a measurement at all.
        # Stated per harness because it is a property of the store; the matching
        # session field is null when the answer is no.
        "reports_rate": spec.reports_rate,
        # Whether this harness can report a gate at all, for the same reason
        # `reports_rate` is here: the page cannot derive it, and the absence of a
        # needs-input row is not evidence of quiet.
        "reports_needs_input": spec.reports_needs_input,
        # What that capability depends on, where it depends on anything. Null on
        # every row whose gate mechanism cannot be turned off, which is all but
        # one; the page cannot derive either half.
        "reports_needs_input_when": spec.reports_needs_input_when,
        # Whether this harness can report turn bounds at all. Stated per
        # harness because it is a property of the store and its collector;
        # a non-working row distinguishes "no turn in progress" from a harness
        # that never reports them (DRC-4548).
        "reports_turn_bounds": spec.reports_turn_bounds,
        "error": None,
    }


def _redact_published_text(rows: list[Session]) -> list[Session]:
    """Credential shapes out of the row fields that carry operator text.

    `records.safe_text` redacts on the way through and most published strings
    pass through it, but the fields swept here do not: the collectors build them
    out of the transcript by hand and bound them with a slice. Ten call sites
    would be ten chances for the eleventh harness to be forgotten, which is how
    `last_prompt` came to be published raw in the first place, so the sweep runs
    once over the assembled rows instead. A collector added later is covered
    without being asked.

    Adding a field to the tables above is cheap and leaving one out is not, so
    the bar is "could a collector ever put transcript text in it", not "does one
    today". `state_detail` and `subagents[].name` were both left out on that
    second reading and both were measured publishing a credential run unmarked.

    Placed before the overlays only because it can be: an overlay patches state,
    never a title (see `events`). It is before `_notify_waits` deliberately — a
    native popup is a screen exposure exactly as the card is.

    `redact_secrets` rather than `safe_text`, because these fields are published
    raw by design and this is not the change that starts scrubbing their control
    characters.

    It mutates, and returns the list it was handed so the caller can chain. The
    return value exists for that and nothing else.
    """
    for row in rows:
        _redact_in_place(row, _RAW_ROW_TEXT)
        instruction = row.get("instruction")
        if isinstance(instruction, dict):
            _redact_in_place(instruction, ("text",))
        for field, keys in _RAW_NESTED_TEXT:
            for item in row.get(field) or ():
                if isinstance(item, dict):
                    _redact_in_place(item, keys)
    return rows


# The width `sessions.base_session` truncates a display id to. An identity no
# longer than this is display-length, which is not proof it was truncated but is
# proof it cannot be shown to be unique.
_DISPLAY_ID_FLOOR = annotation_store.DISPLAY_ID_FLOOR


def _withdraw_stale_finality(row: Session, assessment: object) -> None:
    """Retract a `final` reading whose session end is no longer published.

    Derived at publish time rather than stored, so it corrects itself in both
    directions: `events.reduce_overlays` nulls `ended_at` on a working overlay
    by design, and an `ended_at` that comes back restores finality on the next
    collection. A stored flag would have to be un-stored by something, and
    nothing would.

    "Final" is a durable claim about a session id, not a terminal state of the
    page. A reading that called a session finished, on a row that no longer
    says it finished, is the one claim here a reader cannot check for
    themselves.
    """
    if not isinstance(assessment, dict) or assessment.get("scope") != reading.SCOPE_FINAL:
        return
    ended = records.norm_epoch(row.get("ended_at"))
    if ended and ended == records.norm_epoch(assessment.get("ended_at_read")):
        return
    assessment["scope"] = reading.SCOPE_WITHDRAWN
    assessment["scope_text"] = reading.SCOPE_TEXT[reading.SCOPE_WITHDRAWN]


def _identity_is_a_prefix(row: Session) -> bool:
    """Whether this row's `sid` is a truncation rather than a whole identity.

    Two ways an identity fails to be provably unique, and the second is the one
    a length comparison alone missed. `resume_id` is the harness's own full
    identity where it publishes one, and a longer one that starts with the sid
    means the sid is a truncation: `collectors/claude.py` hands `base_session`
    the transcript stem's first eight characters, so every Claude row is this
    case, which is the hazard DRC-4508 named. A Claude row that reached the
    collector loop from the task store has no transcript and therefore no
    `resume_id` at all, while its sid is still the display prefix, so an
    identity at most display-length is the second arm.

    Shared by the annotation and the delivery attach, because both bind stored
    records to a row by the same key and two copies of this rule would drift.
    """
    sid = row.get("sid")
    resume = row.get("resume_id")
    return isinstance(sid, str) and (
        (isinstance(resume, str) and len(resume) > len(sid) and resume.startswith(sid))
        or len(sid) <= _DISPLAY_ID_FLOOR
    )


def _attach_cached_goals(config: RuntimeConfig, rows: list[Session]) -> None:
    # Only published board rows incur a bounded sidecar read. The saved line
    # never participates in annotation history or in a freshness assessment.
    for row in rows:
        row["cached_deterministic_goal"] = observer.cached_deterministic_goal(
            config, row["harness"], row["sid"]
        )


def _attach_annotations(
    rows: list[Session],
    entries: tuple[annotation_store.Annotation, ...],
    *,
    now: float | None = None,
    settle_sec: float = 0.0,
) -> None:
    """Put what the reader typed onto every row, including the rows with none.

    Every row, not only the annotated ones. A missing key renders as
    `undefined`, which is the blank the board's first rule forbids; an absence
    has to arrive as an absence carrying its reason. `annotations.published`
    owns that wording so three surfaces cannot word it three ways.

    Bound on the full `sid` rather than the eight-character `session` prefix
    beside it. Both are on the row, and the prefix can collide.

    `now` also publishes `reading_eligibility`, the press-time withhold the
    reading route would answer with (`reading.press_eligibility`). Here and not
    earlier because it reads `state`, `finished_at` and `ended_at`, which only
    `_apply_overlays` writes, and the entry's revisions, which this pass finds.
    The stop it rests on is `reading.observed_stop`'s, which also reads the
    collector's `turn_end_at`, so the board, the press and the job read one.
    None leaves the declared None: annotations are off and nothing can be read.
    """
    for row in rows:
        # Reported rather than claimed away: every Claude row binds by prefix,
        # which is the hazard DRC-4508 named. `_identity_is_a_prefix` owns the
        # rule and the reason, and the delivery attach reads the same one.
        sid = row.get("sid")
        by_prefix = _identity_is_a_prefix(row)
        entry = annotation_store.find(entries, row.get("harness"), sid)
        if now is not None:
            row["reading_eligibility"] = reading.press_eligibility(
                row, entry["revisions"] if entry else (), now=now, settle_sec=settle_sec
            )
        published = annotation_store.published(
            entry,
            binding_why=(
                annotation_store.BINDING_BY_PREFIX if by_prefix else annotation_store.BINDING_EXACT
            ),
        )
        _withdraw_stale_finality(row, published.get("assessment"))
        # Prefixed and flat rather than nested, for the reason `base_session`
        # declares them that way: the history allowlist admits field names, and
        # a name cannot reach inside a mapping.
        for name, value in published.items():
            row[f"annotation_{name}"] = value


def _work_activity(session: Session) -> float:
    """The activity that retires an observed stop or end: `work_activity`, else `last_activity`.

    Claude's collector publishes `work_activity`, which reads the parent
    transcript by its newest conversation record so a bookkeeping append does
    not retire a stop (DRC-4770). A collector that does not publish it leaves
    None, and the whole-tree `last_activity` stands, as it always did.
    """
    work = session.get("work_activity")
    if isinstance(work, (int, float)) and not isinstance(work, bool):
        return float(work)
    return float(session.get("last_activity") or 0.0)


def _hide_unmeasured_rates(rows: list[Session], harnesses: tuple[HarnessSpec, ...]) -> None:
    """Replace a rate-blind collector's numeric placeholder with wire-level unknown."""
    reporting = {spec.key for spec in harnesses if spec.reports_rate}
    for row in rows:
        if row["harness"] not in reporting:
            row["rate_per_min"] = None


def _reading_permissions(config: RuntimeConfig, rows: list[Session], now: float) -> dict[str, Any]:
    answer = reading_policy.status(config, now=now, destinations=reading_route.destinations())
    routes = reading_route.resolve_all(
        (str(row.get("harness") or "") for row in rows), config=config
    )
    return {
        "reading": answer,
        "reading_routes": {
            harness: {
                **route,
                "notice_due": reading_policy.notice_due(
                    answer,
                    kind="reading",
                    provider=str(route.get("provider") or ""),
                    destination=str(route.get("words_destination") or ""),
                    tool_output=str(route.get("destination") or ""),
                    content=reading_policy.CONTENT_VERSION
                    if harness in reading_route.AGENT_MESSAGE_HARNESSES
                    else reading_policy.WORDS_CONTENT_VERSION,
                ),
            }
            for harness, route in routes.items()
        },
    }


class Application:
    """One dashboard process's collection surface.

    Everything ambient is injected, so two applications can run in one
    interpreter without sharing configuration, caches, notifications or a clock.
    """

    def __init__(  # noqa: PLR0913 — served bytes bind identity before capability injection
        self,
        config: RuntimeConfig,
        state: RuntimeState,
        harnesses: tuple[HarnessSpec, ...],
        *,
        native_notifier: Callable[[str], str],
        popup_notifier: Callable[[str, str], str | None],
        diagnostic_sink: Callable[[str], None],
        clock: Callable[[], float] = time.time,
        overlays: OverlaySource | None = None,
        frontend_page_bytes: bytes | None = None,
    ) -> None:
        self.config = config
        self.frontend_build = (
            ("react-dev-" if config.frontend_dev is not None else "react-")
            + hashlib.sha256(frontend_page_bytes).hexdigest()[:16]
            if frontend_page_bytes is not None
            else frontend_page.build_id()
        )
        self.state = state
        self.harnesses = harnesses
        self.native_notifier = native_notifier
        self.popup_notifier = popup_notifier
        self.diagnostic_sink = diagnostic_sink
        self.clock = clock
        # None until the coordinator is attached, and None forever under
        # --no-events. A collection with no overlay source is exactly the
        # scan-only behaviour that shipped before events existed, which is what
        # makes the rollback switch a one-line assembly change.
        self.overlays = overlays
        # Attached after construction, exactly as `overlays` above is, and for
        # the same reason: the assembly point owns which services exist. None
        # means no lane, which is the behaviour that shipped before history did.
        self.history_lane: HistoryLane | None = None
        # Attached only on the serving path and only with the switch on, for
        # `history_lane`'s reason and a larger one: `--diagnose` runs a
        # collection and must not start a `codex` subprocess while reporting
        # what the stores hold.
        self.unasked_lane: UnaskedLane | None = None
        # Created on the first Live monitor start, so a board nobody monitors holds no table and
        # runs no thread. Never persisted: a restart starts with no lease.
        self.live_leases: Any = None
        # Set when the server closes, so a request that arrives after builds no ticker.
        self.live_leases_closed = False

    def harness_label(self, key: str) -> str:
        """The registry's display label for a harness key, or "" for anything else.

        "" and not the key, unlike the page's session-row fallback: a row's
        harness comes from a collector and is a registry key by construction,
        while an ask's is written by the agent that registered it and `unknown` is
        the shipped default for every client but Claude Code. Echoing the key back
        would title the common case "unknown is asking you".

        Resolved from `self.harnesses`, the same source the payload's `harnesses`
        array is built from, so a popup title and the board cannot disagree about
        what a harness is called.
        """
        return next((spec.label for spec in self.harnesses if spec.key == key), "")

    def _usage_for(
        self,
        spec: HarnessSpec,
        now: float,
        window_hours: float,
    ) -> list[dict[str, Any]]:
        """One harness's quota entries, or none if reading them failed.

        Its own method so the failure boundary is stated once and reads as a
        boundary: a broken quota read is a diagnostic and never a harness error,
        because the session rows for that harness have already collected and one
        unreadable tile must not repaint the whole strip red.
        """
        if spec.usage is None:
            return []
        try:
            return list(spec.usage(self.config, self.state, now, window_hours))
        except Exception as e:  # noqa: BLE001 — same boundary as the collector above
            runtime_io.diag(
                f"[{spec.key}] usage error: {type(e).__name__}: {e}",
                self.diagnostic_sink,
            )
            return []

    def _collect_harnesses(
        self, now: float, window_hours: float, show_all: bool
    ) -> tuple[list[Session], list[dict[str, Any]], list[dict[str, Any]], bool, bool]:
        config, state = self.config, self.state
        out_sessions: list[Session] = []
        harnesses: list[dict[str, Any]] = []
        usage: list[dict[str, Any]] = []
        usage_supported = False
        usage_fetch_active = False
        for spec in self.harnesses:
            try:
                found = bool(spec.discover(config, state))
            except OSError:
                found = False
            harness = _harness_row(spec, found=found)
            harnesses.append(harness)
            if not found:
                continue
            try:
                out_sessions.extend(spec.collect(config, state, now, window_hours, show_all))
            except Exception as e:  # noqa: BLE001 — one broken harness must not take down the rest
                harness["error"] = f"{type(e).__name__}: {e}"
                runtime_io.diag(
                    f"[{spec.key}] collector error: {harness['error']}",
                    self.diagnostic_sink,
                )
            if spec.usage is None:
                continue
            usage_supported = True
            usage_fetch_active = usage_fetch_active or spec.usage_is_fetch
            usage.extend(self._usage_for(spec, now, window_hours))
        return out_sessions, harnesses, usage, usage_supported, usage_fetch_active

    def collect(self, *, show_all: bool, notify: bool = True) -> Collection:
        config, state, window_hours, now = (
            self.config,
            self.state,
            self.config.window_hours,
            self.clock(),
        )
        cleared_marks = dismissals.refresh(config, state)
        # Before the store is read, and never after: a job writes its outcome
        # and only then leaves the registry, so sampled in that same order a
        # collection shows either the job or its outcome, never neither.
        # Sampled after, a job that ended mid-collection was published gone
        # beside the previous outcome and count (the S6 walk, W1).
        reading_jobs = reading.published_jobs(config)
        # Alongside the dismissal refresh and for its reason: two dashboards can
        # bind on one machine and the file is the record, so a save made in the
        # other is picked up here rather than at the next restart.
        annotation_entries = annotation_store.refresh(config, state)
        # Sampled before the harness loop for the reason Claude's collector used
        # to sample it before its transcript scan: a SessionEnd that commits
        # while this collection is in flight must invalidate the popup, and a
        # generation read at decision time would only be compared against itself.
        generations = notifications.hook_generations(state)
        (
            out_sessions,
            harnesses,
            usage,
            usage_supported,
            usage_fetch_active,
        ) = self._collect_harnesses(now, window_hours, show_all)

        # After every producer has reported and before anything is published, so
        # one collection records at most one reading per window and the page sees
        # the same annotation whichever vendor filled the cache. In-memory only:
        # every value it keeps is one this payload already carries.
        quota.observe_windows(config, state, usage)

        out_sessions = _redact_published_text(sessions.dedupe_sessions(out_sessions))
        _hide_unmeasured_rates(out_sessions, self.harnesses)
        self._mark_unreachable_by_events(out_sessions)
        # Between dedupe and the sort, deliberately. Dedupe keys on
        # (harness, sid), which no overlay changes, and the sort ranks on `state`,
        # which an overlay does change: patching after the sort would leave a row
        # ranked by the state it no longer claims. The summary below is counted
        # from the patched rows for the same reason.
        history_fields = self._apply_overlays(out_sessions, now=now)
        stored_summaries = summary_store.load(config)
        summaries_by_key = {(entry.harness, entry.sid): entry for entry in stored_summaries.entries}
        for row in out_sessions:
            stored = summaries_by_key.get((str(row["harness"]), str(row["sid"])))
            row.update(
                summary_store.published(
                    stored,
                    available=stored_summaries.state == "ok",
                    checked=summary_store.last_checked(state, stored),
                )
            )
            row["summary"]["job"] = summary_jobs.published(
                self, str(row["harness"]), str(row["sid"])
            )
        # After dedupe, which keys on (harness, sid) and would otherwise decide
        # between two rows one of which carries the annotation. And AFTER the
        # overlays, which is the half that was wrong: identity is not patchable
        # so the ordering is safe either way, but the retraction inside this
        # pass compares a stored reading's end against `ended_at`, and nothing
        # in the runtime writes that field except `_apply_overlays`. Attaching
        # first meant every row read None and every `final` reading was
        # retracted, on every collection, with a sentence saying the end was no
        # longer published about an end published seconds later.
        _attach_annotations(
            out_sessions,
            annotation_entries,
            now=now if config.annotations_enabled else None,
            settle_sec=config.reading_settle_sec,
        )
        # After the overlays, which is load-bearing: a wait only an event knows
        # about is a wait, and reading the collector's state is what left the
        # overlay lane silent on every harness.
        #
        # Before the subtraction only by convention. `maybe_popup` consults the
        # dismissal store itself and returns before its own bookkeeping, so a
        # dismissed row records nothing under either ordering and nothing
        # observable changes if these two lines swap — measured, not assumed.
        # The order is kept because it is the one that stays correct if the gate
        # ever stops consulting the store.
        # Recorded from the patched rows, so what the store keeps is what the
        # board published rather than what a collector guessed, which is the
        # whole of the provenance rule. Before the subtraction deliberately: a
        # dismissal hides an alert, and an observation that happened still
        # happened — subtracting first would punch gaps in the history of any
        # session the reader ever cleared.
        self._notify_waits(out_sessions, generations, notify=notify)
        in_quiet = notifications.is_quiet_hours(config, now=now)
        stage_conditions = tripwires.collect(
            config,
            state,
            tripwires.sources_from_sessions(out_sessions),
            now,
            self.native_notifier(config.platform_name),
            self.popup_notifier,
            notify=notify and not in_quiet,
        )
        out_sessions, cleared = _subtract_dismissed(out_sessions, cleared_marks)
        if notify and not in_quiet:
            reach.maybe_reach_nudge(config, state, out_sessions, now=now)
        _attach_cached_goals(config, out_sessions)
        sessions.assign_display_ids(config, out_sessions)
        out_sessions.sort(key=row_order)
        active_sessions = [x for x in out_sessions if x["active"]]
        total_tasks = sum(x["total"] for x in out_sessions)
        total_done = sum(x["done"] for x in out_sessions)
        collection: Collection = {
            "tripwires": stage_conditions,
            "generated": now,
            "window_hours": window_hours,
            # The trailing window every `rate_per_min` below is averaged over.
            # Published so a consumer can name the window it is ranking on
            # instead of hardcoding a figure that would go on reading "10 min"
            # the day this configuration changed it.
            "rate_window_sec": config.rate_window_sec,
            "show_all": show_all,
            "spacedock_enabled": config.spacedock_enabled,
            # How many rows this payload dropped because the reader marked them
            # handled. A count and not a flag on the rows: the tab title, the
            # gate queue and calm's idle clip all derive from `sessions`, and a
            # per-row flag is a thing each of them would have to remember.
            "cleared": cleared,
            # Which layer owns needs-input popups. Empty means the page should
            # raise its own; a backend name means the server already did.
            "native_notify": self.native_notifier(config.platform_name),
            "in_quiet_hours": in_quiet,
            "harnesses": harnesses,
            # The summary grant's own block. Not under `summary`, which already names the
            # board's counts, and not behind `annotate`, because the summary store does not
            # depend on the annotation store: docs/design-session-summary.md#job-and-grant-contract.
            "summaries": summary_jobs.board(config, now=now),
            "summary": {
                "needs_input": sum(1 for x in active_sessions if x["state"] == "needs_input"),
                "working": sum(1 for x in active_sessions if x["state"] == "working"),
                "rate_per_min": sum(
                    x["rate_per_min"] for x in active_sessions if x["rate_per_min"] is not None
                ),
                "active_sessions": len(active_sessions),
                "open_tasks": sum(x["open"] for x in out_sessions),
                "progress_pct": round(total_done * 100 / total_tasks) if total_tasks else 0,
                "total_tasks": total_tasks,
                "total_done": total_done,
            },
            "sessions": out_sessions,
            **self._attach_command_reports(out_sessions),
        }
        if config.dismissals_enabled:
            # The capability flag, keyed the way `usage_fetch` is: present exactly
            # when the store is live, so `--no-dismiss` leaves the page with no
            # control to offer rather than one that answers 503.
            collection["dismiss"] = True
        # Folded in rather than branched on here: `collect` sits on ruff's
        # complexity and statement caps, and an inline `if` puts it over both.
        # `annotate` is keyed the way `dismiss` is, and the page needs it because
        # `--no-annotations` promises no field at all rather than a field whose
        # every save answers 503.
        collection.update(
            {
                # The bound rides with the flag rather than being repeated
                # in the bundle: the counter beside each field says how
                # much room is left, and a page guessing that number tells
                # the reader their words fit when the store will clip them.
                **(
                    {
                        "annotate": True,
                        "annotate_cap": config.annotation_text_cap_chars,
                        "reading_check": annotation_store.published_check(),
                        # Who reads each harness's sessions, and the words to
                        # show BEFORE the press, one route per harness on the
                        # board (DRC-4650). Not one board-wide disclosure: a
                        # Claude Code row and a Codex row may have different
                        # receivers, and a sentence naming the wrong one under
                        # a button that sends a reader's words is the failure
                        # the disclosure exists to prevent.
                        **_reading_permissions(config, out_sessions, now),
                        # The reader's running analyses, board-wide rather than
                        # per row so a job is never a session field or history
                        # (DRC-4686). A reload reads the job from here.
                        "reading_jobs": reading_jobs,
                        # The discard control's sentences, published for
                        # `reading_routes`' reason and one more: the
                        # success sentence claims something about the
                        # departure store, which the page never reads, so
                        # the page must not compose it (DRC-4561).
                        "annotate_discard": annotation_store.DISCARD_SENTENCES,
                        # The store's own sentence while it cannot be read, so
                        # no session reads as one nobody typed against.
                        "annotate_unreadable": annotation_store.store_notice(state),
                    }
                    if config.annotations_enabled
                    else {
                        "annotate": False,
                        "reading_check": annotation_store.ABSTENTION_CHECK_NOT_RUN,
                    }
                ),
                **self._ask_cards(now),
                # Called from inside the update rather than beside it because
                # `collect` sits on ruff's statement cap. It reads the store
                # once and both attaches the per-row sentences and returns the
                # board-wide counts.
                **self._delivery_fields(out_sessions),
                **self._copied_fields(out_sessions),
                **self._unasked_fields(out_sessions, annotation_entries, now=now),
                **history_fields,
                # Which page this process serves, so a tab left open across an
                # upgrade says to reload (regressions major 1, ui5).
                "build": self.frontend_build,
            }
        )
        if usage_supported:
            # Present even when empty: the page distinguishes "no quota data
            # yet" (key with no entries) from "nothing here publishes quota"
            # (no key), and only the former draws the band.
            collection["usage"] = sorted(usage, key=lambda u: str(u.get("harness", "")))
        if usage_fetch_active:
            # The fetcher's capability flag: present exactly when a discovered
            # harness's quota comes from the network fetcher. The page's
            # first-run disclosure banner keys on it, so it must never rise for
            # a disk-read provider or with the fetch disabled.
            collection["usage_fetch"] = True
        return collection

    def _delivery_fields(self, rows: list[Session]) -> dict[str, Any]:
        """Attach what became of each session's raises, and count the board's.

        One read of the store for both halves. Called after `_notify_waits`,
        which is what writes this collection's own outcomes: reading first
        would publish a board one raise behind its own notification on the very
        poll that raised it.

        Every row gets the keys, raised or not, for `_attach_annotations`'
        reason: a missing key renders as `undefined`, and an absence has to
        arrive as an absence carrying its own wording. `deliveries.published`
        owns every sentence so three surfaces cannot word it three ways.

        Bound on `(harness, sid)` with the same prefix rule
        `_attach_annotations` uses, and for the harder half of its reason. The
        gate and hook lanes record under the key the collector publishes, so
        those match exactly. The ASK lane records under the session id the
        caller sent, which for Claude is the whole UUID against a row carrying
        the eight-character transcript prefix: matching exactly orphaned every
        ask-lane outcome from the row it was raised about, so a question the
        reader had been alerted to showed no raise at all. A prefix can collide,
        and `deliveries.published` says so on the row rather than claiming it
        away.

        The counts come from the whole store rather than from these rows,
        because a raise whose session has since aged out of the window still
        happened. Two numbers and never one ratio: they answer different
        questions, and neither is a figure about what a person saw.
        """
        entries = deliveries.load(self.config)
        lane_reported_at = self.state.lane_reported_at
        for row in rows:
            harness, sid = str(row.get("harness") or ""), str(row.get("sid") or "")
            by_prefix = _identity_is_a_prefix(row)
            row.update(
                deliveries.published(
                    entries,
                    harness,
                    sid,
                    lane_reported_at=lane_reported_at,
                    by_prefix=by_prefix,
                )
            )
            # The same sentences again, narrowed to the lane that raises a
            # departure, because the flat keys above carry the LATEST raise of
            # ANY lane and four lanes write this store. A surface printing an
            # outcome BESIDE a departure reads this one; the session page's
            # NOTIFICATIONS block, which is about the notifications and not
            # about a departure, keeps the flat keys. One nested carrier rather
            # than seven more flat names, and it never enters session history,
            # so `history.PROMPT_TEXT_ALLOWLIST`'s reason for the flat
            # annotation fields does not reach it.
            row["delivery_departure"] = deliveries.published(
                entries,
                harness,
                sid,
                lane_reported_at=lane_reported_at,
                by_prefix=by_prefix,
                lane=unasked.LANE,
            )
        return {
            "delivery_counts": deliveries.counts(entries),
            # Board-wide, at the top of the payload, because that is what it is:
            # one report for the whole dashboard and never per session. The page
            # reads THIS key to decide whether its own lane has been reported
            # yet, so publishing it only on the rows left the page unable to
            # tell a server that has its report from one that has not, and it
            # posted a fresh report on every payload.
            "browser_lane": lane_reported_at > 0,
            "browser_lane_at": lane_reported_at or None,
        }

    def intent_revision(
        self,
        entries: tuple[annotation_store.Annotation, ...],
        raised: tuple[departures.Check, ...],
        *,
        now: float,
    ) -> str:
        """Identify the captured log inputs, including sessions off the board.

        This is an equality token, not the collection counter: unrelated
        activity must not refetch the reader's words. Both routes pass the
        inputs they already captured, so a concurrent save cannot label old
        rows with a new token. The day-cap boundary is the one time-dependent
        input to the log; the clock itself would invalidate it every render.
        """
        _mine, today = departures.counts(raised, "", "", since=now - departures.DAY_SEC)
        source = {
            "started": self.state.server_started,
            "annotations": entries,
            "departures": raised,
            "session_cap": self.config.unasked_session_cap,
            "daily_cap": self.config.unasked_daily_cap,
            "day_exhausted": today >= self.config.unasked_daily_cap,
        }
        return hashlib.sha256(
            json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def _copied_fields(self, rows: list[Session]) -> dict[str, Any]:
        """Attach each row's messages recognised as a copied correction (DRC-4678).

        Adds no payload key: it is called from inside the update for the reason
        `_delivery_fields` is, `collect`'s statement cap.
        """
        copied_corrections.attach(self.config, self.state, rows)
        return {}

    def _unasked_fields(
        self,
        rows: list[Session],
        entries: tuple[annotation_store.Annotation, ...],
        *,
        now: float,
    ) -> dict[str, Any]:
        """Attach what the unasked lane raised, and start at most one reading.

        Every row gets the keys whether the lane is attached or not, for
        `_delivery_fields`' reason: a missing key renders as `undefined`, and an
        absence has to arrive as an absence carrying its own wording. With the
        lane off the sentence says nothing was checked, which is the honest
        answer and is deliberately not the same sentence as nothing departed.

        `consider` runs here, after the raises and the dismissal subtraction, so
        a session the reader has already marked handled is not read against
        their words behind their back. It does dictionary work and hands any
        reading to a worker.
        """
        stored = departures.load(self.config)
        for row in rows:
            row.update(unasked.published(self.config, stored, row, entries=entries, now=now))
        if self.unasked_lane is not None:
            self.unasked_lane.consider(self.state, rows, entries, now=now)
        # The capability flag, keyed the way `dismiss` and `annotate` are:
        # present exactly when the lane is live, so a page with the switch off
        # draws nothing rather than a panel that never fills.
        return {
            **({"unasked": True} if self.unasked_lane is not None else {}),
            # Who an unasked check of each harness would reach, which is not the
            # Analyze route on a harness with no producer of its own (owner,
            # 2026-10-20). The page shows the Codex toggle from this, never from
            # `reading_routes`, so it asks only where the lane would send.
            **(
                {
                    "unasked_routes": {
                        harness: {**route, "disclosure_parts": reading_route.unasked_parts(route)}
                        for harness, route in reading_route.resolve_all(
                            (str(row.get("harness") or "") for row in rows),
                            config=self.config,
                            unasked=True,
                        ).items()
                    }
                }
                if self.unasked_lane is not None
                else {}
            ),
            "unasked_off_reason": "run-disabled"
            if self.config.model_calls_disabled
            else "not-requested",
            **(
                {"intent_revision": self.intent_revision(entries, stored, now=now)}
                if self.config.annotations_enabled
                else {}
            ),
        }

    def _history_fields(self, out_sessions: list[Session], *, now: float) -> dict[str, Any]:
        """Record this collection's transitions, and the payload keys they earn.

        Both halves here because the recording has to see the rows before the
        dismissal subtraction while the keys are added at payload assembly, and
        splitting them would put the ordering constraint in two places.
        """
        if self.history_lane is None:
            # One shape for both ways of not recording. The key is present
            # exactly when the store is on and a lane is attached, which is the
            # keying `dismiss` already uses: absent means the page draws
            # nothing, rather than an empty series a consumer has to tell apart
            # from a board on which nothing has happened yet. No lane is
            # `--diagnose`, and off is `--no-history`.
            return {}
        fields: dict[str, Any] = {}
        observed = self.history_lane.record(out_sessions, now=now)
        if self.config.history_enabled:
            # The observations this run has on record, oldest first. A payload
            # field rather than a row field: it is a series about sessions, not
            # a property of one, and adding it to the row would put it in every
            # consumer's declared field set for the sake of two panels.
            fields["history"] = observed
        notice = self.history_lane.notice()
        if notice is not None:
            # Which reset this run opened with, so the header can name it. A
            # corruption reset may be the user's disk; a version reset is ours,
            # and one message for both hides the difference.
            fields["history_reset"] = notice
        return fields

    def _ask_cards(self, now: float) -> dict[str, Any]:
        """The ask capability flag and its cards, or nothing at all.

        Keyed the way `dismiss` is, and for the same reason: absent means the
        page draws no control, so `--no-ask` leaves a reader with nothing to
        click rather than a button whose click answers 503.

        `pending` sweeps as it reads, and it returns only unresolved asks, so an
        answered card can never reappear on the board between the click and the
        poller collecting it. The sweep is no longer the only one: `register`
        sweeps too, because a collection is not guaranteed to happen and a
        registration is. What the coordinator does guarantee is that an
        outstanding ask forces collections while it lasts, which is what renders
        the card here with no browser tab open.
        """
        config, state = self.config, self.state
        if not config.ask_enabled:
            return {}
        return {
            "ask": True,
            "asks": [
                {
                    "id": ask.id,
                    "harness": ask.harness,
                    "session_id": ask.session_id,
                    "project": ask.project,
                    "question": ask.question,
                    "options": list(ask.options),
                    "age_sec": round(now - ask.created),
                }
                for ask in state.asks.pending(
                    now=now,
                    deadline=config.ask_deadline_sec,
                    retention=config.ask_retention_sec,
                )
            ],
        }

    def _notify_waits(
        self,
        out_sessions: list[Session],
        generations: dict[str, int],
        *,
        notify: bool = True,
    ) -> None:
        """Raise the native popup for every row that has just started waiting.

        Here rather than in a collector, and that is the amendment DRC-4192
        made to [R-5](docs/design-runtime-architecture.md#r-5). The one-layer rule —
        the server notifies where `native_notifier` names a backend, the browser
        where it does not — rested on the server firing for whatever the browser
        stood down for. It fired for Claude alone, because `maybe_popup` had one
        caller and it was Claude's collector, so on macOS a Codex row at a real
        gate alerted nobody at all. This is also the only place that sees a row's
        FINAL state: `_apply_overlays` runs after every collector has returned,
        so a wait reported by a hook POST and nothing else was silent even on
        Claude.

        The label comes from `self.harnesses`, the same source the payload's
        `harnesses` array is built from, so a popup and the board cannot disagree
        about what a harness is called. `harness_label` answers "" for anything
        the registry does not carry, and a row's harness is a registry key by
        construction; the key is echoed rather than a blank subject shipped, as
        the page's own session-row fallback does.

        Inactive rows are skipped, which is what `show_all` collections rest on:
        `--all` widens what is drawn, never what alerts.
        """
        if not notify:
            return
        for session in out_sessions:
            if not session.get("active"):
                continue
            harness, sid = str(session["harness"]), str(session["sid"])
            state = str(session.get("state") or "")
            notifications.maybe_popup(
                self.config,
                self.state,
                notifications.PopupSubject(
                    harness=harness,
                    label=self.harness_label(harness) or harness,
                    prefix=sid,
                    # The whole-subtree reading, the same field the dismissal
                    # subtraction below compares, so the popup gate and the row
                    # cannot lapse at different moments.
                    activity=float(session.get("last_activity") or 0.0),
                ),
                state,
                _wait_popup_body(session) if state == "needs_input" else None,
                expect_generation=generations.get(sid, 0),
                popup_notifier=self.popup_notifier,
            )

    def _mark_unreachable_by_events(self, out_sessions: list[Session]) -> None:
        """Disclose the rows no event can ever reach, before any overlay lands.

        Four of the ten harnesses are absent from `events.IDENTITY_NORMALIZERS`,
        so `events.parse` refuses their envelopes outright and their rows are read
        off disk and nothing else. That table by name and not "the event
        vocabulary", which is `EVENTS_BY_HARNESS` and holds three: six is right
        for the table this tests and wrong for the other one.

        Their idle rows therefore cannot say whether a turn ended, and without
        this an unmarked row would mean either "did not finish" or "cannot be seen
        from here" — the same collapse the retired `stale` gloss was admitting to.
        Both halves are [N-9](docs/design-needs-input.md#n-9) (DRC-4035): its
        **Marking on the stop itself** rejection is where the gloss was measured
        out, and its **Letting a collector infer completion** rejection is what
        this method implements — a guessed completion renders identically to a
        measured one, so the six disclose `scan-only` instead. The document and
        not the commits behind it, because the reason that decision exists is that a commit
        message and a comment held the measurement and neither is where a reader
        looks.

        Where the disclosure lands is `docs/design-scan-only-rows.md`. From
        39eb6fd (2026-08-21) to DRC-4473 it reached no pixel, which made both
        halves above true of the payload and false of the screen; the page now
        prints it on the row and on the session page.

        A property of the harness, not of this process, so it is stated whether or
        not a coordinator is attached. Written before `_apply_overlays` on
        purpose: an adapter harness's own overlay owns this field, and the two
        must not be able to disagree about one row.
        """
        for session in out_sessions:
            if str(session["harness"]) not in runtime_events.IDENTITY_NORMALIZERS:
                session["acquisition"] = runtime_events.ACQUISITION_SCAN

    def _attach_command_reports(self, out_sessions: list[Session]) -> dict[str, Any]:
        enabled = self.config.irreversible_enabled and self.overlays is not None
        reports = self.overlays.command_reports() if enabled and self.overlays is not None else []
        for session in out_sessions:
            if enabled and session["harness"] in {"claude", "codex"}:
                session["command_reports"] = [
                    report
                    for report in reports
                    if (report["harness"], report["sid"]) == (session["harness"], session["sid"])
                ]
        return {
            "ends_observable": self.overlays is not None,
            "irreversible_enabled": enabled,
            **({"command_reports": reports} if enabled else {}),
        }

    def _apply_overlays(self, out_sessions: list[Session], *, now: float) -> dict[str, Any]:
        """Patch collected rows from the live overlay ledger, if one is attached.

        The row list is walked, not the ledger: an overlay can only ever reach a
        session a collector produced, so there is no path here by which one
        creates or removes a row. `note_rows` then reports the full key set back,
        which is what lets an unmatched overlay wait or expire rather than
        silently doing nothing forever.

        This is also the pass at which the row set becomes final — states
        patched, nothing yet subtracted — which is the only point the history may
        be recorded from. It returns the payload keys that recording earns rather
        than storing them on the instance, so `collect` gains no statement (it
        sits on ruff's statement cap) and no state to get stale.
        """
        # An optional in-process adapter is a capability, not evidence that this
        # session installed it. Only this run's reduced event patch earns a read.
        for session in out_sessions:
            if session["harness"] in {"pi", "opencode"}:
                session["source_gaps"] = [*session["source_gaps"], "block state"]
        source = self.overlays
        if source is None:
            # No ledger to patch from, but the history still records: `overlays`
            # is None forever under --no-events, and a store that went quiet on
            # that flag would be an off switch with a second, undocumented name.
            #
            # The session-end store is deliberately NOT read here, and that is
            # the opposite call from the history store's for a reason that is
            # written down: the coordinator is that store's only writer, so
            # under --no-events it is left alone in both directions and the
            # flag is documented as its off switch (decisions.md, DRC-4547).
            return self._history_fields(out_sessions, now=now)
        # Once per collection, like the delivery record, and after the branch
        # above so --no-events never opens the file.
        stored_ends = runtime_ends.restored(runtime_ends.load(self.config))
        for session in out_sessions:
            harness, sid = str(session["harness"]), str(session["sid"])
            overlays = source.overlays_for(harness, sid)
            finished_at = source.finished_at(harness, sid)
            ended_at = source.ended_at(harness, sid) or self._restored_end(
                session, stored_ends.get((harness, sid), 0.0)
            )
            git = source.git_for(harness, sid)
            # Written straight onto the row rather than reduced through the
            # patch: a target is not a display claim that an overlay could
            # dispute, and it must not become one — `PATCHABLE` is the set an
            # untrusted event may write, and the focus contract forbids echoing
            # a target through any of it.
            session["focusable"] = source.focusable(harness, sid)
            if overlays or finished_at or ended_at or git is not None:
                patch = runtime_events.reduce_overlays(
                    overlays,
                    now=now,
                    # The row's own reading of when the session last wrote,
                    # which is the only evidence that outlives a wait no hook
                    # ever closes. Collectors that do not report it send 0,
                    # and the wait then stands.
                    own_activity=float(session.get("own_activity") or 0.0),
                    # The whole-tree reading, subagents included, which is
                    # what retires a stop no `turn_started` ever follows. A
                    # parked parent with a running child is working, so idle
                    # cannot key on `own_activity` the way a wait does.
                    session_activity=_work_activity(session),
                    activity_grace_sec=self.config.overlay_wait_activity_grace_sec,
                    # Reduced rather than written straight onto the row, so the
                    # mark passes the same activity guard the idle overlay does
                    # even though it outlives the ledger that overlay lives in.
                    finished_at=finished_at,
                    # Reduced rather than written onto the row for the same
                    # reason, and it is a distinct argument rather than a reading
                    # of the one above because a turn stopping and a session id
                    # ending are different facts about a row (DRC-4036).
                    ended_at=ended_at,
                    # Reduced rather than written onto the row for the reason the
                    # mark above is: a reading taken at a session end must still
                    # lose to any overlay saying the session is alive again.
                    git=None if git is None else (git.dirty, git.changed),
                )
                if harness in {"pi", "opencode"} and patch.get("state") == "needs_input":
                    since = patch.get("blocked_since")
                    if isinstance(since, (int, float)):
                        # These adapters intentionally omit native prompt text.
                        # Sessions renders detail, not its separate wait clock.
                        duration = sessions.fmt_duration(max(0, now - since))
                        patch["state_detail"] = f"Waiting for input · {duration}"
                self._note_dispute(session, patch, overlays, now=now)
                runtime_events.apply_patch(session, _keep_wait_detail(session, patch))
                if (
                    harness in {"pi", "opencode"}
                    and patch.get("acquisition") == runtime_events.ACQUISITION_EVENT
                ):
                    session["source_gaps"] = [
                        gap for gap in session["source_gaps"] if gap != "block state"
                    ]
            else:
                # No ledger for this row means nothing can be disagreeing with it.
                self._clear_dispute(harness, sid)
        collected = {(str(s["harness"]), str(s["sid"])) for s in out_sessions}
        source.note_rows(collected)
        # A session that vanishes mid-dispute reaches neither branch above, so
        # its episode would be held open forever, pinning a record the ring has
        # already evicted.
        with self.state.dispute_lock:
            for key in [k for k in self.state.dispute_episodes if k not in collected]:
                del self.state.dispute_episodes[key]
        return self._history_fields(out_sessions, now=now)

    def _restored_end(self, session: Session, stored: float) -> float:
        """A session end an earlier run of this board observed, or 0.0.

        DRC-4547: the coordinator's memory of an end dies with its process, so a
        cold row reads the end back from the store the coordinator wrote through
        to. 0.0 keeps the coordinator's own meaning, NOT OBSERVED, and the value
        then rides `events.reduce_overlays` exactly as a live end does, so a live
        working or needs-input overlay still beats it.

        Guarded on the row's activity where a live end is not, and the
        difference is the point (decisions.md, DRC-4547). A live end is retired
        by `_lift_ended` the moment the id is seen in use again; an id
        `--resume`d while the board was down produced no event this process saw,
        so a write well after the end is the only tell. The grace is the
        reducer's own, because it absorbs the same ordering: a real end lands a
        few seconds after the last write (5.581 s in the a1 arm of
        docs/captures/claude/session-end-2.1.261-macos.jsonl).

        The tell is the row's activity as `_work_activity` reads it, which is
        wider than the parent transcript: on Claude it is the newest of the task
        file, the parent transcript's newest conversation record (DRC-4770), the
        subagent transcripts, the agent files and the child sessions
        (`collectors/claude.py`). So the exposure stated in
        SECURITY.md rather than solved covers all of them: a harness that writes
        any of those more than the grace after `SessionEnd` loses the restored
        end, and the row then reads as it does today, which is honest rather
        than wrong.
        """
        if not stored:
            return 0.0
        activity = _work_activity(session)
        if activity > stored + self.config.overlay_wait_activity_grace_sec:
            return 0.0
        return stored

    def _note_dispute(
        self,
        session: Session,
        patch: Mapping[str, Any],
        overlays: list[Overlay],
        *,
        now: float,
    ) -> None:
        """Record an overlay overruling a collector that had found a wait.

        Only that direction. A collector Idle row an overlay promotes to Working
        is the ordinary path and says nothing, so counting it would bury the case
        this exists to find. See
        [N-6](docs/design-needs-input.md#n-6).

        One record per episode, not per collection. A disagreement stands until
        something changes it, and collections run at the memo floor, so recording
        each one made `dispute_total` count polls and let a single 90-second
        episode fill the ring on its own. An episode keeps its shape while the
        two states and the newest arrival sequence hold; anything else is a new
        fault and gets its own record.

        Records rather than decides: the patch is applied either way. Which side
        is right is not knowable here, and DRC-4095 and DRC-4097 are the same
        disagreement resolved the other way round.
        """
        key = (str(session["harness"]), str(session["sid"]))
        patched = patch.get("state")
        if session.get("state") != "needs_input" or patched not in {"working", "idle"}:
            self._clear_dispute(*key)
            return
        # Subagent overlays are excluded from the shape deliberately. They patch
        # no state, so a child starting or stopping changes the disagreement not
        # at all, but each is remembered under its own slot with a fresh
        # sequence. Counting them split one standing wait into a record per child
        # transition, on fan-outs, which DRC-4121 established are the sessions
        # most likely to be holding a prompt in the first place.
        shape = (
            "needs_input",
            str(patched),
            max(
                (o.arrival_seq for o in overlays if o.kind != runtime_events.OVERLAY_SUBAGENT),
                default=-1,
            ),
        )
        # Read before the lock, not inside it: `drop_counters` takes the
        # coordinator's lock, and nesting one under the other would make an
        # ordering load-bearing that nothing else in the file relies on.
        counters = self.overlays.drop_counters() if self.overlays else {}
        with self.state.dispute_lock:
            open_episode = self.state.dispute_episodes.get(key)
            if open_episode is not None and open_episode[0] == shape:
                record = open_episode[1]
                record["last_seen_at"] = now
                record["repeats"] = int(record["repeats"]) + 1
                return
            record = {
                "at": now,
                "last_seen_at": now,
                "repeats": 0,
                "harness": key[0],
                "sid": key[1],
                "collector_state": "needs_input",
                "overlay_state": patched,
                "own_activity": float(session.get("own_activity") or 0.0),
                "last_activity": float(session.get("last_activity") or 0.0),
                # The guard's own constant, so a record stays readable against a
                # build whose constant has since moved.
                "activity_grace_sec": self.config.overlay_wait_activity_grace_sec,
                "overlays": runtime_events.overlay_rows(overlays, now=now),
                # Reading 3 against reading 4 in
                # [N-5](docs/design-needs-input.md#n-5),
                # an envelope dropped versus never posted, is a counter comparison. The live
                # counters are
                # cumulative, so a record read tomorrow can only bracket itself
                # against its neighbours if it carries its own copy.
                "drop_counters": counters,
            }
            self.state.dispute_total += 1
            self.state.disputes.append(record)
            self.state.dispute_episodes[key] = (shape, record)

    def _clear_dispute(self, harness: str, sid: str) -> None:
        """Close a session's open episode, so the next one is a new record."""
        with self.state.dispute_lock:
            self.state.dispute_episodes.pop((harness, sid), None)

    def request_usage_fetch(self) -> bool:
        """Maybe start a background quota fetch; the gates live in `quota`.

        Called only from `/api/data` handling for requests that carry the
        page's consent — never from `collect`, which `--diagnose` also runs
        and which must stay free of network side effects.
        """
        return quota.request_fetch(
            self.config,
            self.state,
            clock=self.clock,
            diagnostic_sink=self.diagnostic_sink,
        )

    @property
    def snapshot(self) -> runtime_snapshot.Snapshot:
        """The runtime's published responses. Owned by state, not by this object."""
        return self.state.snapshot

    def collect_json(self, *, show_all: bool) -> tuple[runtime_snapshot.Revision, bytes]:
        """The published response for one variant, collecting only if stale.

        Two locks, deliberately. `collect_memo_lock` is still held across
        collection, so ThreadingHTTPServer callers share one filesystem and
        SQLite scan rather than stampeding a cold entry. The snapshot's own lock
        is taken only to read or write the published tuple, so a slow reader can
        never block a collection and a collection can never block a reader.

        The freshness floor is `collect_memo_sec`, unchanged from the memo this
        replaced, so the worst-case staleness a `curl` or headless caller sees is
        exactly what it was before.
        """
        key: runtime_snapshot.SnapshotKey = (self.config.window_hours, show_all)
        published = self._fresh_snapshot(key)
        if published is not None:
            return published
        with self.state.collect_memo_lock:
            # Re-check under the lock: another thread may have collected while
            # this one waited, which is the whole point of holding it.
            published = self._fresh_snapshot(key)
            if published is not None:
                return published
            # Read before collecting: a clear while this collection runs means a
            # write it may have missed, so its body is not kept (DRC-4760).
            generation = self.snapshot.generation()
            body = json.dumps(self.collect(show_all=show_all)).encode()
            revision, kept = self.snapshot.publish(
                key, body, now=self.clock(), generation=generation
            )
            # Only a freshly minted revision that was kept is worth announcing. A
            # warm reuse returns above without reaching this line, so a connected
            # client is never woken for a state it already has; and a body that
            # crossed a clear is never served again, so a tab woken for it would
            # fetch the next collection instead (owner, 2026-10-02: two of one
            # save's four GETs). The next kept collection announces.
            if kept:
                self.state.streams.publish(revision)
            return revision, body

    def _fresh_snapshot(
        self, key: runtime_snapshot.SnapshotKey
    ) -> tuple[runtime_snapshot.Revision, bytes] | None:
        """The published entry for `key` if it is inside the floor, else None."""
        age = self.snapshot.age(key, now=self.clock())
        if age is None or age >= self.config.collect_memo_sec:
            return None
        return self.snapshot.current(key)
