"""Notification classification, hook state, cooldowns and the native notifier."""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from compass_runtime import claude_data, deliveries, dismissals, records
from compass_runtime import io as runtime_io
from compass_runtime import state as runtime_state

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from compass_runtime.config import RuntimeConfig
    from compass_runtime.state import RuntimeState


# Claude Code's Notification matcher values. ``idle_timeout`` is accepted as a
# compatibility alias, while current payloads use ``idle_prompt``.
# These three sets are deliberately not exhaustive: an unrecognised structured
# type stays actionable (see notification_disposition), so a type Claude Code
# adds tomorrow surfaces rather than disappearing.
#
# Four values below are observed rather than documented, and the distinction is
# worth keeping: Claude Code's own hook metadata advertises eight
# ``notification_type`` values, but its callers pass these four as well
# (measured on 2.1.226). Fail-visible treats all four as actionable, which is
# right for exactly one of them, ``worker_permission_prompt``, and wrong for the
# other three: ``computer_use_enter`` and its pair carry "Claude is using your
# computer", a status line rather than a question, and ``push_notification`` is
# the delivery wrapper rather than a prompt of its own. So classifying them
# explicitly is what stops an unknown-type default from deciding a user-facing
# band. Do not prune them back to the advertised list.
IDLE_NOTIFICATION_TYPES = {"idle_prompt", "idle_timeout"}


INFORMATIONAL_NOTIFICATION_TYPES = {
    "agent_completed",
    "auth_success",
    "computer_use_enter",  # observed: "Claude is using your computer"
    "computer_use_exit",  # observed: its pair
    "elicitation_complete",
    "elicitation_response",
    "push_notification",  # observed: the push wrapper, not a question of its own
}


ACTIONABLE_NOTIFICATION_TYPES = {
    "agent_needs_input",
    "elicitation_dialog",
    "permission_prompt",
    # observed: a leader raising a worker's tool or network request. It arrives on
    # the *leader's* session_id, so prefix_is_agent never fires and the parent row
    # is the one that shows it — which is also the row the human answers from.
    # The network half has no PermissionRequest behind it (that hook is
    # tool-scoped), so this is its only signal. See DRC-4121.
    "worker_permission_prompt",
}


# Narrower than "everything informational", on purpose. Clearing retires a
# standing hook, so a type earns a place here only by meaning "the thing that was
# waiting is over" — which is why ``auth_success`` has never been here, and why
# the newly classified informational types are not either. A status line
# ("Claude is using your computer") arriving while a permission prompt stands
# must leave that prompt standing.
CLEARING_NOTIFICATION_TYPES = IDLE_NOTIFICATION_TYPES | {
    "agent_completed",
    "elicitation_complete",
    "elicitation_response",
}


QUIET_HOURS_FILENAME: Final[str] = "quiet_hours"
QUIET_HOURS_ENV: Final[str] = "COMPASS_QUIET_HOURS"
QUIET_HOURS_MAX_BYTES: Final[int] = 128


def parse_quiet_hours(spec: Any) -> tuple[int, int, int, int] | None:
    """Parse a quiet hours window string (e.g. '22:00-08:00') into (start_h, start_m, end_h, end_m).

    Returns None if spec is invalid, empty, or has identical start and end times.
    """
    if not isinstance(spec, str) or "-" not in spec:
        return None
    try:
        start_str, end_str = spec.strip().split("-", 1)
        start_h, start_m = (int(x) for x in start_str.split(":", 1))
        end_h, end_m = (int(x) for x in end_str.split(":", 1))
        valid_time = (
            0 <= start_h <= 23 and 0 <= start_m <= 59 and 0 <= end_h <= 23 and 0 <= end_m <= 59
        )
        if not valid_time or (start_h, start_m) == (end_h, end_m):
            return None
    except (ValueError, AttributeError):
        return None
    else:
        return (start_h, start_m, end_h, end_m)


def resolve_quiet_hours(config: RuntimeConfig) -> tuple[int, int, int, int] | None:
    """Resolve the effective quiet hours window, or None if disabled or unconfigured."""
    if not config.quiet_hours_enabled:
        return None
    candidate = config.quiet_hours
    if not candidate:
        candidate = os.environ.get(QUIET_HOURS_ENV)
    if not candidate:
        quiet_file = os.path.join(config.state_home, QUIET_HOURS_FILENAME)
        if os.path.isfile(quiet_file):
            try:
                with open(quiet_file, encoding="utf-8") as f:
                    candidate = f.read(QUIET_HOURS_MAX_BYTES)
            except OSError:
                candidate = None
    return parse_quiet_hours(candidate)


def is_quiet_hours(config: RuntimeConfig, *, now: float | None = None) -> bool:
    """Return True if the current local time falls within the configured quiet hours window."""
    window = resolve_quiet_hours(config)
    if window is None:
        return False
    start_h, start_m, end_h, end_m = window
    current_ts = now if now is not None else time.time()
    local_tm = time.localtime(current_ts)
    cur_m = local_tm.tm_hour * 60 + local_tm.tm_min
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    if start_minutes < end_minutes:
        return start_minutes <= cur_m < end_minutes
    return cur_m >= start_minutes or cur_m < end_minutes


def normalized_notification_type(value: Any) -> str:
    """Return a normalized structured notification type, if present."""
    return value.strip().lower() if isinstance(value, str) and value.strip() else ""


def notification_disposition(notification_type: Any, message: str) -> tuple[bool, bool]:
    """Return ``(needs_input, popup)`` for a Notification-hook payload.

    Structured Claude Code payloads are authoritative. Text matching remains
    only as a compatibility fallback for older hooks that omitted
    ``notification_type``.
    """
    kind = normalized_notification_type(notification_type)
    if kind in IDLE_NOTIFICATION_TYPES:
        return (False, True)
    if kind in INFORMATIONAL_NOTIFICATION_TYPES:
        return (False, False)
    if kind in ACTIONABLE_NOTIFICATION_TYPES:
        return (True, True)
    if kind:
        return (True, True)  # future/unknown structured prompt: fail visible
    idle_nudge = message.strip().lower().startswith("claude is waiting for your input")
    return (not idle_nudge, True)


def native_notifier(platform_name: str) -> str:
    """Name of the OS-level notification backend for a platform, "" if none.

    Pure in ``platform_name`` so both branches run on every CI runner and mypy
    checks them all, rather than treating the non-host branch as unreachable
    (design decision
    [D-4](docs/design-cross-platform.md#d-4)).

    The page reads this through ``/api/data`` to decide whether to raise its
    own browser notification. Exactly one layer notifies for a given
    transition: the server when it has a backend here, the browser when it does
    not. Linux and Windows have no backend yet (tracked in
    ``docs/plans/native-notifications.md``), so today the browser covers them
    and macOS behavior is unchanged.
    """
    return "osascript" if platform_name == "darwin" else ""


# The AppleScript payload bound, and the reason a composed message has to be
# assembled against it rather than handed over long: `records.safe_text` keeps
# the HEAD, so a message trimmed here loses its tail silently. Named rather than
# inlined below because `ask_popup_detail` composes against this same figure, and
# two copies of it would drift the day one moved.
POPUP_MESSAGE_CAP = 180


def notify_mac(
    config: RuntimeConfig,
    title: Any,
    message: Any,
    *,
    diagnostic_sink: Callable[[str], None] = print,
) -> str:
    """Send one banner, and say what became of it.

    Five outcomes rather than one, and none of them is "seen". It used to return
    `None` on every path, so no caller could tell a platform with no backend
    from a call that timed out, from one the service refused, from one that
    never started at all.
    """
    if not native_notifier(config.platform_name):
        return deliveries.OUTCOME_NO_LANE

    def esc(s: str) -> str:
        return str(s).replace("\\", "\\\\").replace('"', '\\"')

    safe_message = records.safe_text(message, POPUP_MESSAGE_CAP)
    safe_title = records.safe_text(title, 60)
    script = (
        f'display notification "{esc(safe_message)}"'
        f' with title "{esc(safe_title)}" sound name "Glass"'
    )
    try:
        result = subprocess.run(  # noqa: S603 — fixed binary, esc()-sanitized args
            ["/usr/bin/osascript", "-e", script],
            timeout=5,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout or "unknown error").strip()
            runtime_io.diag(
                f"[notify] osascript failed: {runtime_io.value(detail[:300])}", diagnostic_sink
            )
            return deliveries.OUTCOME_REFUSED
    # A timeout is caught here too and is NOT a failure: the call did not
    # return, so whether a banner was drawn is unknown. Folding it into the
    # refused arm is the collapse this whole record exists to refuse one level
    # down, and the two were indistinguishable while this returned None.
    except subprocess.TimeoutExpired as exc:
        runtime_io.diag(
            f"[notify] osascript did not return: {runtime_io.value(exc)}", diagnostic_sink
        )
        return deliveries.OUTCOME_DID_NOT_RETURN
    # Separate from the non-zero return above, not folded into it. These are the
    # call never starting: a missing or unexecutable binary, or an argument the
    # runtime refused. Reporting that as "the notification service returned an
    # error" tells a reader their notification service rejected something it
    # never saw.
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        runtime_io.diag(
            f"[notify] osascript did not start: {type(exc).__name__}: {runtime_io.value(exc)}",
            diagnostic_sink,
        )
        return deliveries.OUTCOME_NOT_LAUNCHED
    return deliveries.OUTCOME_HANDED_OVER


def hook_generation(state: RuntimeState, prefix: str) -> int:
    """The current SessionEnd generation for a session prefix."""
    with state.hook_lock:
        return state.hook_generation.get(prefix, 0)


def hook_generations(state: RuntimeState) -> dict[str, int]:
    """Every session's SessionEnd generation, copied under the lock.

    The popup decision is taken once per collection, over rows every collector
    has already returned, so it cannot sample a generation before the read that
    produced the row it is judging. This is that sample: taken before the
    harness loop, it names the generation each session was collected under, and
    `maybe_popup` re-checks it against the live map under the same lock.

    Copied rather than read live, and the copy is the whole point: reading the
    map at decision time would compare a value against itself and let a
    SessionEnd that committed mid-collection re-create the state it just
    cleared. A session with no entry reads 0 through `dict.get` at both ends, so
    a harness that has no SessionEnd signal at all is judged by the same rule
    Claude is rather than skipping the check.
    """
    with state.hook_lock:
        return dict(state.hook_generation)


def current_hook(
    state: RuntimeState,
    prefix: str,
    last_user_event: str | None,
    last_event_ts: float,
) -> dict[str, Any] | None:
    """Return an uncleared hook notification for a session.

    Hooks with a user-event marker clear when the newest user record changes
    (clock-independent). Hooks without one (payloads lacking transcript_path:
    the documented curl simulation, older Claude Code versions) fall back to
    the parsed-timestamp rule so they cannot stick forever.
    """
    with state.hook_lock:
        hook = state.hook_notifications.get(prefix)
        if not hook:
            return None
        if "user_event" in hook:
            if last_user_event != hook["user_event"]:
                state.hook_notifications.pop(prefix, None)
                return None
        elif last_event_ts > hook["ts"]:
            state.hook_notifications.pop(prefix, None)
            return None
        return hook


def hook_is_actionable_prompt(hook: Mapping[str, Any] | None) -> bool:
    """True when a stored hook is a *recognised* actionable prompt.

    Recognised is the operative word, and it is why this is not simply
    ``needs_input``. Every hook that reaches the collector is already actionable
    as far as the ingress can tell: `notification_disposition` fails an unknown
    structured type visible rather than dropping it, which is right for storing
    and popping. But an unknown type is a claim, not a measurement, and this
    predicate gates a *precedence* decision -- whether a prompt may override a
    session that looks busy. Only a type this module names actionable earns that;
    an unknown one waits for the session to go quiet, exactly as before.

    A hook stored before `kind` was carried through has no `kind` at all, which
    reads as unrecognised and keeps the old behavior. That is the safe direction.
    """
    return hook is not None and hook.get("kind", "") in ACTIONABLE_NOTIFICATION_TYPES


# `/api/notify` is Claude's own hook forwarder: the payload shape is Claude
# Code's `Notification` hook and nothing else posts there. So this label is a
# property of the route rather than something to look up, and a second harness
# gets its own ingress rather than a `harness` field in this body that the server
# would then have to trust.
NOTIFY_HARNESS_LABEL = "Claude"


# One fixed cooldown key for the whole ask lane, rather than one per ask or one
# per asking session. `register` stores an id exactly once and nothing ever
# re-registers it, so there is no repeat to suppress; and `bounded_put` evicts by
# INSERTION order without reordering on re-assignment, so an unbounded id
# namespace would eventually evict the gate lane's `"_global"` and silently reset
# the machine-wide floor.
ASK_POPUP_KEY = "_ask"

# The subject when the registry could not resolve the claimed harness, which is
# the COMMON case rather than an edge: the shipped stdio server reports the
# literal `unknown` for every client but Claude Code. The browser layer hardcodes
# this same sentence, and `test_both_layers_render_the_same_ask_sentence` is what
# holds the two copies together.
ASK_HARNESS_FALLBACK = "An agent"

# What separates the question from the project in the popup body. The question
# comes first: `safe_text` keeps the head, so project-first spends the budget on
# a path and can drop the question entirely.
ASK_DETAIL_SEP = " \u00b7 "


def waiting_title(harness_label: str) -> str:
    """The popup title for a harness that needs the human.

    One function rather than an f-string at each site, because the native
    notifier and the browser both render this sentence and they drifted apart the
    moment there was more than one harness able to raise it. The label is the
    registry's own display label, so a row badged Antigravity cannot produce a
    popup that says Claude.
    """
    return f"{harness_label} is waiting on you"


def departure_title(harness_label: str) -> str:
    """The popup title for an unasked reading that found a departure.

    Its own sentence, for `asking_title`'s reason and a sharper one. A gate and
    a question are both the session asking for you; this is Compass saying
    something about the session, on evidence a model read, and the reader is by
    construction not at the desk. Reading it as "answer me" would send them to
    the wrong place, and reading it as a fact would overclaim what a reading is.

    An empty label yields the generic subject rather than a blank one, exactly
    as the two titles above do.
    """
    return f"{harness_label or ASK_HARNESS_FALLBACK} may be going off track"


def asking_title(harness_label: str) -> str:
    """The popup title for a session that registered a question.

    Its own sentence rather than `waiting_title`'s, because the two alerts are
    answered in different places: a gate in the session's own terminal, a
    question on the board. That is why the ask band has buttons and the gate band
    does not, and a reader who cannot tell the two apart from the banner cannot
    tell where to go.

    An empty label yields the generic subject rather than a blank one. Only a
    label the registry resolved reaches here — never the `harness` string as
    sent, which is agent-authored and up to `ask_option_cap_chars` long. The
    lookup is not verification: a registration that inherits or forges `AI_AGENT`
    still titles the banner with that harness. What it does stop is a 120-char
    value reaching `safe_text(title, 60)`, which keeps the head and so would
    delete the words " is asking you".
    """
    return f"{harness_label or ASK_HARNESS_FALLBACK} is asking you"


@dataclass(frozen=True)
class PopupSubject:
    """Which session a popup would be about, and the readings that gate it.

    One argument rather than four, because they are one fact and were previously
    drifting apart at every call site as the gate grew: the label without the key
    cannot find a dismissal, and the key without the activity reading cannot tell
    a standing one from a lapsed one.

    No defaults, deliberately. ``label`` defaulting to Claude would let a second
    harness's collector wire itself in and silently claim to be Claude, which is
    the failure the harness-neutral title exists to prevent; ``activity``
    defaulting to 0 would make forgetting it look like working code, because 0
    reads as "this session has not moved" and keeps a dismissal in force. The
    compiler cannot catch a wrong string, but it can catch a missing field.

    ``harness`` is the registry key and ``label`` is the display name, kept apart
    because the dismissal store keys on (harness, sid) exactly as
    ``dedupe_sessions`` does — keying on a label would fold two harnesses together
    the day one of them is renamed. ``activity`` is the whole-subtree reading, not
    ``own_activity``: any movement in the tree means the work resumed.
    """

    harness: str
    label: str
    prefix: str
    activity: float


def record_outcome(
    config: RuntimeConfig,
    harness: str,
    sid: str,
    lane: str,
    outcome: str | None,
    now: float,
) -> None:
    """Write what became of one raise, outside every lock.

    Outside deliberately, as the notifier call itself is: `hook_lock` is a plain
    Lock that three lanes contend for, and this write touches a file. A record
    that failed to reach disk is a diagnostic and never a reason to drop the
    raise, so this returns nothing and the caller carries on.

    `outcome` may be `None`, which is a notifier that does not report rather
    than a fifth outcome. Nothing is recorded then, because a record has to say
    what happened and "the notifier declined to say" is not one of the four
    things that can. In this tree only an injected stub does that; the shipped
    notifier always reports.
    """
    if not harness or not sid or outcome is None:
        return
    deliveries.record(config, harness=harness, sid=sid, lane=lane, outcome=outcome, now=now)


def maybe_popup(
    config: RuntimeConfig,
    state: RuntimeState,
    subject: PopupSubject,
    session_state: str,
    detail: str | None,
    *,
    expect_generation: int | None = None,
    popup_notifier: Callable[[str, str], str | None],
) -> None:
    """Popup when a session transitions into a needs-input state.

    Called once per collected row, for every harness, from `Application`. It was
    called from Claude's collector alone until DRC-4192, and that is the whole of
    why a Codex gate on macOS alerted nobody: the browser layer stands down
    wherever `native_notifier` names a backend, on the premise that the server
    already fired, and nothing called this for the other nine.

    ``subject.prefix`` is the key both popup maps are stored under, and it is the
    session id rather than `(harness, sid)` deliberately: `handle_payload` writes
    the same key off Claude's hook ingress, and the two lanes must share it or one
    standing gate pops twice — once when the hook lands and again when the next
    collection sees the transition it caused. Two harnesses publishing a
    byte-identical session id would fold together here; the dismissal store is
    keyed properly and is unaffected, and one suppressed popup is the whole cost.

    ``expect_generation`` is re-checked under the same lock that guards the
    last-session-state map. Checking it in the caller leaves a window in which a
    SessionEnd commits first, and this would then re-create the state it just
    cleared and fire a popup for a session that has already exited.

    A transition the machine-wide floor holds is deferred rather than consumed;
    the comment on that branch has the reason.
    """
    prefix, harness_label = subject.prefix, subject.label
    now = time.time()
    if is_quiet_hours(config, now=now):
        return
    if dismissals.suppresses(config, state, subject.harness, prefix, subject.activity):
        # Returned before the last-session-state write below, deliberately. This
        # call is not evidence about the session, so recording a transition from
        # it would let a dismissal rewrite the history the popup decision after a
        # restore is made against.
        return
    with state.hook_lock:
        if (
            expect_generation is not None
            and state.hook_generation.get(prefix, 0) != expect_generation
        ):
            return
        prev = state.last_session_state.get(prefix)
        entering = session_state == "needs_input" and prev != "needs_input"
        # The machine-wide floor delays a popup; it must not destroy one. Since
        # DRC-4192 every harness reaches this floor, so an unrecorded return here
        # is what stops one harness's gate consuming another's: the transition is
        # recorded ABOVE the gates, and a transition recorded while floored fails
        # the edge test on every later collection, silencing that gate for as
        # long as it stands. `maybe_ask_popup` keys its own floor apart for this
        # same loss, which it calls actively harmful.
        #
        # `popup_cooldown_sec` is deliberately NOT deferred: it is the
        # per-session re-emission floor, and retrying past it would re-pop the
        # same standing gate every minute.
        if (
            entering
            and now - state.last_popup.get(prefix, 0) >= config.popup_cooldown_sec
            and now - state.last_popup.get("_global", 0) < config.global_popup_cooldown_sec
        ):
            return
        runtime_state.bounded_put(
            state.last_session_state, prefix, session_state, limit=config.max_cache_entries
        )
        if not entering:
            return
        if now - state.last_popup.get(prefix, 0) < config.popup_cooldown_sec:
            return
        # Spent here, before the call, and refunded below when the notifier
        # reports there was no lane to attempt. Spending first and refunding
        # rather than deciding first, for two reasons that both point the same
        # way. `popup_notifier` is INJECTED, so a gate on `config.platform_name`
        # would decide for a notifier this function cannot see, and a Linux
        # backend would be skipped by a check about the macOS one. And writing
        # the floor after the call instead reopens the window these writes close
        # under the lock: two collections could both pass the edge test and both
        # raise. A refund keeps the window shut and costs one suppressed raise
        # for the duration of a call that did nothing.
        previous_session = state.last_popup.get(prefix)
        previous_global = state.last_popup.get("_global")
        runtime_state.bounded_put(state.last_popup, prefix, now, limit=config.max_cache_entries)
        runtime_state.bounded_put(state.last_popup, "_global", now, limit=config.max_cache_entries)
    outcome = popup_notifier(
        waiting_title(harness_label), detail or f"Session {prefix} needs your input"
    )
    if outcome == deliveries.OUTCOME_NO_LANE:
        _refund_floor(state, state.last_popup, prefix, now, previous_session)
        _refund_floor(state, state.last_popup, "_global", now, previous_global)
    record_outcome(config, subject.harness, prefix, "gate", outcome, now)


def _refund_floor(
    state: RuntimeState,
    cache: dict[str, Any],
    key: str,
    spent: Any,
    previous: Any,
) -> None:
    """Put one spent suppressor back, unless someone else has moved it since.

    Compare and swap rather than a plain restore. `_global` and the ask lane's
    key are shared across sessions, so a raise that landed between the spend and
    this call has written its own value, and rolling that back would unsilence a
    raise that really was attempted.
    """
    with state.hook_lock:
        if cache.get(key) != spent:
            return
        if previous is None:
            cache.pop(key, None)
        else:
            cache[key] = previous


@dataclass(frozen=True)
class AskSubject:
    """What a popup about a registered question would say.

    No defaults, for `PopupSubject`'s reason: `label` is the field that can lie,
    and `""` is a legal value meaning "the registry does not carry this key". A
    default would make forgetting it look like working code that titles every
    question with someone else's name.

    `project` arrives already tail-trimmed by `_ask_project` and must not be
    re-truncated — see `ask_popup_detail`.
    """

    harness: str
    sid: str
    label: str
    question: str
    project: str


def ask_popup_detail(question: str, project: str) -> str:
    """The popup body: the question, and the project only if it fits whole.

    `notify_mac` bounds the message at `POPUP_MESSAGE_CAP` and `safe_text` keeps
    the head, so composing `question · project` and letting that trim publishes a
    path that is a PREFIX of the real one and reads as a whole directory. That is
    the defect `_ask_project` records measuring one layer up: a 122-character cwd
    against a 120-char cap published `.../e2e/adop` for a directory named
    `adopt2`. The repo's own parallel-work layout puts several sibling worktree
    paths one character apart, so a reader would walk to the wrong session.

    So the path is dropped whole rather than cut, and the question is never
    trimmed here to make room for it. A dropped path is honest and the card on
    the board still carries it; the question is what the reader has to answer,
    and it is the half `notify_mac` may still trim.
    """
    if project and len(question) + len(ASK_DETAIL_SEP) + len(project) <= POPUP_MESSAGE_CAP:
        return f"{question}{ASK_DETAIL_SEP}{project}"
    return question


def maybe_ask_popup(
    config: RuntimeConfig,
    state: RuntimeState,
    subject: AskSubject,
    *,
    now: float,
    popup_notifier: Callable[[str, str], str | None],
) -> None:
    """Popup when a session registers a question, once per ask-lane floor.

    One gate and not six. `maybe_popup`'s others are meaningless here — there is
    no prior state to transition from, no SessionEnd generation to re-check, and
    no re-emitted message to suppress, because `register` stores an id exactly
    once — and two of them would be actively harmful: its `last_session_state`
    write is keyed by 8-char session prefix and only `clear_session` removes an
    entry, so every ask would leak a permanent entry into that map.

    **The floor keys are deliberately asymmetric with the gate lane's.** This
    reads and writes `ASK_POPUP_KEY` only, and never the gate lane's `"_global"`.
    Writing that key would put a question in front of every gate on the machine
    for `global_popup_cooldown_sec`, and the two lanes answer different questions
    on different timetables: a gate re-emits for as long as it stands, while
    nothing ever re-registers a question and the sweep deletes it unanswered at
    `ask_deadline_sec`. (A shared floor used to be worse than a delay — a floored
    gate transition was consumed and never retried — which is the defect
    DRC-4192's popup pass had to fix once every harness reached that floor. The
    asymmetry predates the fix and outlives it.)

    No dismissal is consulted. The card is published regardless — `_ask_cards`
    reads no dismissal store — so suppressing the alert would leave the reader an
    alert and a board that disagree. (A caller *can* send an 8-character
    `session_id` that would match a Claude mark, so this is a decision about the
    board agreeing with itself, not an impossibility.)

    `now` is a parameter rather than a `time.time()` sampled here: it is
    `ask.created`, minted from the application's clock, and it is the reading the
    registry's own sweep and `ask_deadline_sec` measure this ask against.

    `config.ask_enabled` is not re-checked: `_ask` answers 503 before the body is
    read, so a check here would be dead code and a second home for the rollback
    switch.
    """
    with state.hook_lock:
        if now - state.last_popup.get(ASK_POPUP_KEY, 0) < config.global_popup_cooldown_sec:
            return
        previous_ask = state.last_popup.get(ASK_POPUP_KEY)
        runtime_state.bounded_put(
            state.last_popup, ASK_POPUP_KEY, now, limit=config.max_cache_entries
        )
    # Outside the lock, as every other popup site is: `hook_lock` is a plain Lock
    # and osascript has a 5s timeout.
    outcome = popup_notifier(
        asking_title(subject.label), ask_popup_detail(subject.question, subject.project)
    )
    # Refunded on `no-lane` for `maybe_popup`'s reason, and it matters more here:
    # nothing ever re-registers a question, so a floor spent on a raise that was
    # never attempted silences the NEXT question rather than a retry of this one.
    if outcome == deliveries.OUTCOME_NO_LANE:
        _refund_floor(state, state.last_popup, ASK_POPUP_KEY, now, previous_ask)
    record_outcome(config, subject.harness, subject.sid, "ask", outcome, now)


def _refund_hook_floors(
    state: RuntimeState,
    popup_key: str,
    now: float,
    outcome: str | None,
    spent_before: tuple[Any, Any],
) -> None:
    """Put the hook lane's two cooldown floors back when there was no lane.

    The two floors only. `last_popup_message` is not a floor: it suppresses a
    REPEAT of the same message, and Claude re-emits the same notification for as
    long as the session stays blocked. Refunding it was tried and reverted,
    because on a platform with no backend it makes every re-emission a fresh
    raise, and each one writes a record about a banner nobody could have drawn.
    A floor exists so the next real transition is not lost; this one exists so
    the same standing gate is not counted again, and that reason does not change
    with the outcome.

    A separate function only because `handle_payload` sits on ruff's branch cap.
    """
    if outcome != deliveries.OUTCOME_NO_LANE:
        return
    _refund_floor(state, state.last_popup, popup_key, now, spent_before[0])
    _refund_floor(state, state.last_popup, "_global", now, spent_before[1])


def transcript_mtime(path: Any) -> float:
    """When a hook payload's transcript was last written, or 0.

    0 rather than an exception for a missing, unreadable or non-string path: the
    only caller compares it against a dismissal watermark, where 0 reads as "no
    evidence the session moved" and leaves the mark standing.
    """
    if not isinstance(path, str) or not path:
        return 0.0
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def clear_session(state: RuntimeState, config: RuntimeConfig, prefix: str) -> None:
    """Retire a session's standing hook state and bump its generation.

    Only SessionEnd does this, because only SessionEnd says the session reached
    an end at all. A clearing notification ends one alert, not the session.

    Not quite "this session is gone", which is what this said until the a7 arm of
    docs/captures/claude/session-end-2.1.261-macos.jsonl drove `/clear`: the
    SessionEnd fires, the process survives, and it accepts another prompt. What
    saves this path is that the hook state is keyed on the 8-char session prefix
    and the prompt after a `/clear` goes to a NEW session id (measured
    2026-09-06), so the state retired here belongs to the id that really did
    finish. The events path publishes the same fact as `ended_at` (DRC-4036).
    """
    with state.hook_lock:
        state.hook_notifications.pop(prefix, None)
        state.last_session_state.pop(prefix, None)
        runtime_state.bounded_put(
            state.hook_generation,
            prefix,
            state.hook_generation.get(prefix, 0) + 1,
            limit=config.max_cache_entries,
        )


def _payload_response(cleared: bool, in_quiet: bool) -> dict[str, Any]:
    if cleared:
        return {"ok": True, "suppressed": "cleared"}
    if in_quiet:
        return {"ok": True, "suppressed": "quiet_hours"}
    return {"ok": True}


def handle_payload(
    config: RuntimeConfig,
    state: RuntimeState,
    payload: dict[str, Any],
    *,
    now: float,
    popup_notifier: Callable[[str, str], str | None],
) -> dict[str, Any]:
    """Apply one Claude hook payload and return the response object.

    Every ordering rule lives here, not in the HTTP layer: SessionEnd
    retirement, the generation guard around the slow transcript lookups,
    subagent suppression, the clear/needs-input decision, and the three popup
    cooldowns. The caller only encodes the result.
    """
    session_id = payload.get("session_id")
    prefix = session_id[:8] if isinstance(session_id, str) else ""
    hook_event_name = payload.get("hook_event_name")
    if isinstance(hook_event_name, str) and hook_event_name.lower() == "sessionend":
        if prefix:
            clear_session(state, config, prefix)
        return {"ok": True, "cleared": "session_end"}

    raw_message = payload.get("message")
    message = records.safe_text(
        raw_message
        if isinstance(raw_message, str) and raw_message
        else "Claude is waiting for your input",
        500,
    )
    kind = normalized_notification_type(payload.get("notification_type"))
    needs_input, popup = notification_disposition(kind, message)
    # Sampled before the transcript lookups below, which are slow enough for a
    # SessionEnd to land in between and be silently undone.
    generation = hook_generation(state, prefix)
    # Subagent sessions also emit Notification-hook events (permission prompts
    # inside agents). They are not user-facing sessions — a popup about them is
    # noise the human cannot act on from the dashboard.
    if prefix and claude_data.prefix_is_agent(config, state, prefix):
        return {"ok": True, "suppressed": "subagent"}

    # `kind` is carried, not just consumed. The disposition above decides whether
    # to store the hook at all; the collector separately needs to know *what kind*
    # of prompt it is holding, because a recognised prompt outranks a live
    # subagent and an unrecognised one does not. Dropping it here left the
    # collector unable to tell a permission prompt from a status line.
    hook: dict[str, Any] = {"ts": now, "message": message, "kind": kind}
    transcript_path = payload.get("transcript_path")
    if prefix and isinstance(transcript_path, str):
        found, user_event = claude_data.hook_user_event(config, state, transcript_path, prefix)
        if found:
            hook["user_event"] = user_event
    # Read before the hook lock, never inside it: this takes the dismissal lock,
    # and nesting one under the other would make an ordering load-bearing that
    # nothing else in the file relies on. It gates the popup only — the hook is
    # still stored below, so restoring the row brings its standing question back
    # with it rather than a board the ingress had already emptied.
    cleared = bool(prefix) and dismissals.suppresses(
        config,
        state,
        "claude",
        prefix,
        # The transcript's mtime, which is the one activity reading this path has
        # — the collector's `last_activity` folds in subagent and task mtimes, and
        # re-deriving those here would be a transcript scan inside a hook. It is
        # the conservative half of that figure: it can only be older, so this gate
        # lapses no earlier than the collector's and never later.
        transcript_mtime(transcript_path),
    )

    with state.hook_lock:
        if prefix and state.hook_generation.get(prefix, 0) != generation:
            # The session ended while this notification was being processed.
            return {"ok": True, "superseded": True}
        if prefix:
            clears_input = kind in CLEARING_NOTIFICATION_TYPES or (not kind and not needs_input)
            if clears_input:
                state.hook_notifications.pop(prefix, None)
                state.last_session_state.pop(prefix, None)
            elif needs_input:
                runtime_state.bounded_put(
                    state.hook_notifications, prefix, hook, limit=config.max_cache_entries
                )
        popup_key = prefix or "_anonymous"
        session_ready = now - state.last_popup.get(popup_key, 0) >= config.popup_cooldown_sec
        global_ready = now - state.last_popup.get("_global", 0) >= config.global_popup_cooldown_sec
        # Claude re-emits the same idle/permission notification for as long as
        # the session stays blocked; repeating the popup adds no information.
        prev_msg, prev_ts = state.last_popup_message.get(popup_key, ("", 0.0))
        repeat = message == prev_msg and now - prev_ts < config.popup_repeat_suppress_sec
        in_quiet = is_quiet_hours(config, now=now)
        fire = (
            popup and session_ready and global_ready and not repeat and not cleared and not in_quiet
        )
        if fire:
            spent_before = (
                state.last_popup.get(popup_key),
                state.last_popup.get("_global"),
            )
            runtime_state.bounded_put(
                state.last_popup, popup_key, now, limit=config.max_cache_entries
            )
            runtime_state.bounded_put(
                state.last_popup, "_global", now, limit=config.max_cache_entries
            )
            runtime_state.bounded_put(
                state.last_popup_message, popup_key, (message, now), limit=config.max_cache_entries
            )
    if fire:
        outcome = popup_notifier(waiting_title(NOTIFY_HARNESS_LABEL), message)
        _refund_hook_floors(state, popup_key, now, outcome, spent_before)
        # "claude" by the same argument as the label above it: the route is
        # Claude's own hook forwarder and nothing else posts there, so the
        # harness is a property of the route rather than a field to trust.
        record_outcome(config, "claude", prefix, "hook", outcome, now)
    return _payload_response(cleared, in_quiet)
