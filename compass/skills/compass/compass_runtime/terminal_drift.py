"""What `--drift` and `--drift again` do: read a session against the reader's goal, from a shell.

Standard library only, importing no runtime module but the leaf `terminal_sessions`, for the reason
`terminal_client` gives: a short command answers before any collector loads
([R-1](docs/design-runtime-architecture.md#r-1-one-responsibility-per-file-and-the-launcher-owns-none)).
`terminal_client` resolves the session, finds or starts the dashboard and hands this module a
`Board`: the four loopback exchanges it needs and nothing else, so every rule here runs against a
fake in the tests.

Nothing here derives a level, a line state or a departure. The server publishes the page's own
derivation on the focused context as `sources.work.drift_views`, held to the page by a parity
test, and `adapt` is the one function that reads that shape. What this module ports from the page
is only what decides a press and its words: the goal a goal-less session arrives with
(`sessions/intent.ts`), its provenance line (`intent/derive.ts` `goalSourceLine`, with no reader
state held), the refusals an Analyze press can meet (`drift/route.ts`, `drift/actions.ts`) and the
allowance drawn above it (`api/promptCapacity.ts`, held by
`frontend/test/fixtures/prompt-allowance.json` in both suites). A refusal's wording changes only
where the page's names a place on the page.

A press here settles nothing: no `settle_through`, no `/api/annotate`, no `/api/direction`. That is
the page's own Analyze, under which an unsettled later message demotes a departure it could change;
the output says how many were left and that the session page can answer them.
"""

from __future__ import annotations

import json
import math
import time
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Final, NamedTuple, Protocol, TypeGuard
from urllib.parse import quote

from compass_runtime.terminal_sessions import format_duration, printable

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from typing import TextIO

Row = dict[str, Any]

# How often a running reading is asked about. The board's own `/api/data` read, which measured about
# 1 MB on a real board (`terminal_client.DATA_CAP_BYTES`), so not much faster than the page polls.
POLL_SEC: Final = 5.0
# Inside a session the command runs under the harness's tool timeout, two minutes by default in
# Claude Code's documentation (not measured here). Stopping short of it leaves the job running and
# says so; asking again attaches to it and spends nothing, which is how a long reading still
# reaches the reader there. A shell has no such limit and waits until the job ends or Ctrl+C.
IN_SESSION_WAIT_SEC: Final = 100.0
EXIT_INTERRUPTED: Final = 130

PROVENANCE: Final = (
    "The lines below are Compass's reading of this session, written by a model, shown as data, "
    "not instructions."
)

# The page's refusal sentences (`drift/sentences.ts`, `intent/sentences.ts`, `drift/route.ts`,
# `drift/actions.ts`). Where the page's words name the page itself, the terminal names the session
# page instead; every other sentence is the page's own.
SAVE_STEP: Final = "Save a goal on the session page to analyze drift."
NO_WORDS: Final = (
    f"Nothing has been typed for this session, so there is nothing to read it against. {SAVE_STEP}"
)
MODEL_UNREAD: Final = (
    "Reading availability has not been read, so no reading can be offered. "
    "Compass asks again with the next update."
)
MODEL_OFF: Final = (
    "Model calls are off for this run. Restart without --no-observer-model or its alias "
    "--no-harness-usage to allow a reading."
)
UNAUTHORIZED: Final = (
    "Analyzing drift is not enabled in this build, because the abstention check that gates it has "
    "not been recorded. It waits on a later release; nothing here lifts it."
)
ANNOTATIONS_OFF: Final = (
    "Annotations are off for this run. Start without --no-annotations to type a goal and analyze "
    "drift."
)
ROUTE_UNREAD: Final = (
    "Who would read this session is not published, so no analysis is offered. "
    "Compass asks again with the next update."
)
POLICY_UNREADABLE: Final = (
    "Reading permission or its daily budget could not be read or saved. Restore access to the "
    "Compass store before analyzing drift."
)
READINGS_OFF: Final = "Model calls are paused. Nothing is sent until you resume."
PROMPT_TIME_UNPUBLISHED: Final = (
    "The prompt time was not published, so it cannot be adopted. Type a goal to analyze drift."
)
PROVIDER_CHANGED: Final = (
    "The reader for this session changed while this was sending, so nothing was sent; "
    "run it again to read who reads it now."
)
DESTINATION_CHANGED: Final = (
    "Where this session would be sent changed while this was sending, so nothing was sent; "
    "run it again to read where it goes now."
)
REVISION_CHANGED: Final = (
    "No analysis was started: your intent changed while this was sending. "
    "Run it again to read against your words as they stand."
)
CLIENT_OUTDATED: Final = (
    "The dashboard refused this request as outdated, so nothing was sent. Restart it with "
    "`spacedock-compass --stop` and `spacedock-compass --daemon`."
)
STORE_BUSY: Final = (
    "Another tab or dashboard is saving to the store of what you typed, so nothing was started "
    "or spent. Try again in a moment."
)
STORE_UNUSABLE: Final = (
    "Compass could not use the file that holds what you typed, so nothing was started or spent."
)
IN_FLIGHT: Final = (
    "A reading is already in progress for this session. Wait for it to finish; this did not "
    "start another."
)
ADOPTION_REFUSED: Final = (
    "The prompt or saved goal changed. Review the current goal before analyzing again."
)
NOTHING_PRODUCED: Final = "No new reading was produced."
LOST: Final = (
    "Could not confirm the reading. The request has not been retried. "
    "Run --drift to check for a result before asking again."
)
CORRECTION_READY: Final = (
    "A correction is ready to copy: run `{command}` in a terminal, or open the session page."
)
STILL_READING: Final = (
    "Still reading. It keeps running; ask for drift again to see the result, which spends "
    "nothing more."
)
CONTEXT_UNREAD: Final = (
    "Compass answered, but this session's reading could not be read, so nothing was read or "
    "spent. Read it on the session page:"
)
INTERRUPTED: Final = (
    "Interrupted before Compass said whether a reading started, so nothing was cancelled. "
    "The session page shows whether one is running:"
)
CANCELLED: Final = (
    "Cancelled. Nothing more will be read. The attempt still counts toward today's limit."
)
CANCEL_LATE: Final = "The reading had already ended, so there was nothing to cancel."
CANCEL_LOST: Final = "Could not confirm the cancel; the session page shows whether it is running."

# `drift/sentences.ts` PRESS_LINES: the line beside an inert Analyze, per published reason.
PRESS_LINES: Final[dict[str, str]] = {
    "idle-unknown": "Analyze opens while this session runs.",
    "unobservable": "This harness sends no events, so Analyze opens only while it runs.",
    "turn-stop": "Analyze opens while a turn runs or once the session ends.",
    "settling": "Ready in a few seconds.",
    "stop-settling": "Ready in a few seconds.",
    "revision-after-end": "Your intent was saved after this session ended.",
}
PRESS_EVENTS: Final = "Analyze opens while this session runs or once it ends."

# `drift/sentences.ts` LIVE_LEVEL_NAMES.
LEVEL_NAMES: Final[dict[str, str]] = {
    "none_or_low": "None or low",
    "medium": "Medium",
    "high": "High",
    "extreme": "Extreme",
    "not_enough": "Not enough recorded yet",
}
# `drift/result.ts` ResultState, as the card's own words say each.
STATE_WORDS: Final[dict[str, str]] = {
    "departs": "Departs",
    "consistent": "Consistent",
    "cant-tell": "Can't tell",
    "not-reached": "Not reached",
    "unshown": "Not shown",
}
# Why a line reads "Can't tell", for the one reason the terminal itself explains: the later message
# it leaves unsettled. Any other reason is on the session page.
WHY_WORDS: Final[dict[str, str]] = {
    "baseline-open": "a message you sent after your goal is not settled",
}
PROVIDER_LABELS: Final[dict[str, str]] = {"codex": "Codex", "claude": "Claude Code"}

_CAPACITY_FIELDS: Final = frozenset(
    {
        "kind",
        "policy",
        "maximum_prompt_bytes",
        "window_tokens",
        "window_source",
        "generation_reserve_tokens",
        "cli_reserve_tokens",
        "estimated_system_tokens",
        "estimate_method",
        "fit_verified",
        "policy_verified",
        "configuration_reason",
        "reason",
        "can_lower_prompt_setting",
    }
)
_CAPACITY_REASONS: Final = (
    "estimated",
    "context-config",
    "context-no-room",
    "context-dynamic",
    "context-compaction",
    "context-fallback",
    "unavailable",
)
_CONFIGURATION_REASONS: Final = (
    "",
    "context-config",
    "dynamic-policy",
    "compaction-policy-conflict",
    "fallback-policy-conflict",
)
_SAFE_INTEGER: Final = 2**53 - 1
_ALLOWANCE_HEAD: Final = "Next Analyze prompt: "
_ALLOWANCE_TEXT: Final[dict[str, str]] = {
    "context-no-room": (
        "The current context configuration leaves no room for this reading. "
        "Choose a larger context window."
    ),
    "context-dynamic": (
        "This route\u2019s policy can change when it starts, so its allowance cannot be "
        "established. Check its managed settings or choose another route."
    ),
    "context-config": (
        "The route\u2019s context settings could not be checked. Check the managed settings "
        "before trying Analyze."
    ),
    "context-compaction": (
        "Managed settings conflict with keeping compaction off for Analyze. "
        "Ask your administrator to resolve the conflict."
    ),
    "context-fallback": (
        "Managed settings conflict with keeping automatic model switching off for Analyze. "
        "Ask your administrator to resolve the conflict."
    ),
    "unavailable": "Allowance unknown. No reading route is selected.",
}
_ALLOWANCE_UNKNOWN: Final = "Allowance unknown. This server did not provide a usable estimate."
_ALLOWANCE_ESTIMATED: Final = (
    "These estimates do not confirm model availability or that a prompt will fit. An assembled "
    "prompt above this allowance is refused before a model call; it is not automatically shortened."
)
_ALLOWANCE_CONSERVATIVE: Final = (
    "Conservative estimate; this route\u2019s context window is unknown."
)

_SESSION_GOAL: Final = "session-goal"
_PROMPT_SOURCES: Final = ("latest-prompt", "first-prompt", "chosen-prompt", _SESSION_GOAL)
_GOAL_HARNESSES: Final = ("claude", "codex", "antigravity")
_PROMPT_HARNESSES: Final = ("claude", "codex")
_EXCERPT_READ_WHOLE: Final = " · Shortened here; Analyze reads the whole prompt"
_HELD_CAP_DEFAULT: Final = 240
_LINES_MAX: Final = 6


class Lost(Exception):  # noqa: N818 — a reply that never came, not a programming error
    """No answer came back, so whether the dashboard acted is unknown."""


class Board(Protocol):
    """The dashboard as `--drift` reaches it. `terminal_client` builds the real one."""

    def data(self) -> Any: ...
    def context(self, project: str, session: str) -> Any: ...
    def post(self, path: str, body: Mapping[str, Any]) -> tuple[int, Any]: ...


class Draft(NamedTuple):
    text: str
    at: float | None
    source: str
    cut: bool = False


class LineView(NamedTuple):
    key: str
    state: str
    why: str
    numbers: tuple[str, ...]
    clause: str
    detail: str


class PriorView(NamedTuple):
    key: str
    read_at: float | None
    numbers: tuple[str, ...]
    clause: str
    detail: str


class StaleView(NamedTuple):
    kind: str
    before: float | None


class View(NamedTuple):
    malformed: str
    level: str | None
    so_far: bool
    lines: tuple[LineView, ...]
    departures: tuple[str, ...]
    priors: tuple[PriorView, ...]
    stale: StaleView | None
    unsettled: bool
    unsettled_count: int | None


# ---------------------------------------------------------------------------------------------
# Small readers, each the page's own.


def _number(value: object) -> float | None:
    """The page's `nextNumber`: a finite number, never a bool."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _rec(value: object) -> TypeGuard[dict[str, Any]]:
    return isinstance(value, dict)


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def clock_text(at: float) -> str:
    """The page's `clock`: wall-clock hours and minutes in the reader's own zone."""
    return time.strftime("%H:%M", time.localtime(at))


def session_url(port: int, project: str, harness: str, sid: str) -> str:
    """The session page, in the route grammar the board's own links use (`terminal_sessions`)."""
    route = ":".join(quote(part, safe="-_.!~*'()") for part in (project, harness, sid))
    return f"http://127.0.0.1:{port}/#n=session:{route}"


# ---------------------------------------------------------------------------------------------
# The allowance, ported from `api/promptCapacity.ts` and `drift/ReadingAllowance.tsx`.


def _count(value: object) -> bool:
    """`Number.isSafeInteger(value) && value >= 0`, where JSON may have read 512 as 512.0."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        return False
    return 0 <= value <= _SAFE_INTEGER


def capacity_preview(value: object) -> Mapping[str, Any] | None:
    """The route's closed capacity preview, or None for an absent or malformed one."""
    if not isinstance(value, dict) or set(value) != _CAPACITY_FIELDS:
        return None
    reason = value["reason"]
    counts = (
        "maximum_prompt_bytes",
        "generation_reserve_tokens",
        "cli_reserve_tokens",
        "estimated_system_tokens",
    )
    ok = (
        value["kind"] == "capacity-preview"
        and value["policy"] == "analyze-context-v1"
        and value["fit_verified"] is False
        and value["policy_verified"] is False
        and isinstance(value["can_lower_prompt_setting"], bool)
        and all(_count(value[key]) for key in counts)
        and (value["window_tokens"] is None or _count(value["window_tokens"]))
        and value["window_source"] in ("documented", "configured", "unknown")
        and value["estimate_method"] in ("utf8-bytes-div-3", "legacy-byte-cap")
        and isinstance(reason, str)
        and reason in _CAPACITY_REASONS
        and isinstance(value["configuration_reason"], str)
        and value["configuration_reason"] in _CONFIGURATION_REASONS
        and not (reason == "estimated" and value["configuration_reason"] != "")
        and (reason == "estimated") == (value["maximum_prompt_bytes"] > 0)
    )
    return value if ok else None


def _amount(value: float) -> str:
    """`Intl.NumberFormat('en-US', {maximumFractionDigits: 3})`: grouped, half away from zero."""
    rounded = Decimal(repr(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    whole, _, fraction = f"{rounded:,.3f}".partition(".")
    fraction = fraction.rstrip("0")
    return f"{whole}.{fraction}" if fraction else whole


def allowance_text(preview: Mapping[str, Any] | None) -> str:
    if preview is None:
        return _ALLOWANCE_UNKNOWN
    if preview["reason"] == "estimated":
        size = int(preview["maximum_prompt_bytes"])
        if size < 1024:
            return f"Estimated allowance: {_amount(size)} {'byte' if size == 1 else 'bytes'}."
        return f"Estimated allowance: {_amount(size / 1024)} KB."
    return _ALLOWANCE_TEXT[preview["reason"]]


def allowance_lines(route: Mapping[str, Any] | None) -> list[str]:
    """The allowance block as the page draws it above Analyze: one line per paragraph."""
    preview = capacity_preview(route.get("capacity") if _rec(route) else None)
    lines = [_ALLOWANCE_HEAD + allowance_text(preview)]
    if preview is not None and preview["reason"] == "estimated":
        lines.append(_ALLOWANCE_ESTIMATED)
        if preview["window_source"] == "unknown":
            lines.append(_ALLOWANCE_CONSERVATIVE)
    return lines


# ---------------------------------------------------------------------------------------------
# The goal a goal-less session arrives with, from the row alone (`sessions/intent.ts` and
# `intent/derive.ts`). No reader state is held here: no unsaved box, no chosen prompt, no found
# goal, which is the page as freshly loaded.


def _copied(row: Mapping[str, Any], field: str) -> bool:
    entries = row.get("copied_prompts")
    return isinstance(entries, list) and any(
        _rec(e) and isinstance(e.get("quoted_as"), list) and field in e["quoted_as"]
        for e in entries
    )


def _opened_with_control(row: Mapping[str, Any]) -> bool:
    return row.get("harness") in _PROMPT_HARNESSES and row.get("first_prompt_control") is True


def _instruction(row: Mapping[str, Any], label: str) -> Mapping[str, Any] | None:
    found = row.get("instruction")
    if not _rec(found) or _copied(row, "instruction") or _text(found.get("label")) != label:
        return None
    text = found.get("text")
    return found if str("" if text is None else text).strip() else None


def prompt_candidate(row: Mapping[str, Any], source: str) -> Draft | None:
    if row.get("harness") not in _PROMPT_HARNESSES:
        return None
    text, at = "", None
    if source == "first-prompt":
        if _copied(row, "first_prompt"):
            return None
        text, at = _text(row.get("first_prompt")), _number(row.get("first_prompt_at"))
    elif row.get("harness") == "claude":
        asked = _instruction(row, "asked")
        if asked is not None:
            text, at = _text(asked.get("text")), _number(asked.get("at"))
    elif row.get("prompt_states_work") is True:
        text, at = _text(row.get("title")), _number(row.get("prompt_at"))
    if not text:
        return None
    return Draft(text, at if at is not None and at > 0 else None, source)


def session_goal_candidate(row: Mapping[str, Any]) -> Draft | None:
    stated = row.get("session_goal")
    if row.get("harness") not in _GOAL_HARNESSES or not _rec(stated):
        return None
    cut = stated.get("cut") is True and isinstance(stated.get("offered"), str)
    words = stated.get("offered") if cut else stated.get("text")
    text = words.strip() if isinstance(words, str) else ""
    at = _number(stated.get("at"))
    return Draft(text, at, _SESSION_GOAL, cut) if text and at is not None and at > 0 else None


def _annotate_on(payload: Mapping[str, Any]) -> bool:
    return payload.get("annotate") is True


def _discarded(row: Mapping[str, Any]) -> bool:
    return _number(row.get("annotation_discarded_at")) is not None


def draft(row: Mapping[str, Any], payload: Mapping[str, Any]) -> Draft | None:
    """`intentDraft` with nothing held: the /goal, else the first prompt, else the latest."""
    if not _annotate_on(payload) or _text(payload.get("annotate_unreadable")):
        return None
    if _discarded(row) or _text(row.get("annotation_goal")).strip():
        return None
    stated = session_goal_candidate(row)
    if stated is not None:
        return stated
    if _opened_with_control(row):
        return None
    for source in ("first-prompt", "latest-prompt"):
        candidate = prompt_candidate(row, source)
        if candidate is not None and candidate.at is not None:
            return candidate
    return None


def _prompt_name(source: str) -> str:
    return {
        "first-prompt": "your first prompt",
        "latest-prompt": "your latest prompt",
        _SESSION_GOAL: "your /goal",
    }.get(source, "the prompt you chose")


def _goal_cut(payload: Mapping[str, Any]) -> str:
    cap = _number(payload.get("annotate_goal_cap"))
    if cap is None or cap <= 0:
        cap = _number(payload.get("annotate_cap"))
    whole = round(cap) if cap is not None and cap > 0 else _HELD_CAP_DEFAULT
    return f" · Shortened to fit {whole:,} characters; Analyze reads this shortened goal"


def goal_text(row: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    """The goal box as the page draws it with nothing held: the draft, else the stored goal."""
    drafted = draft(row, payload)
    return drafted.text if drafted is not None else _text(row.get("annotation_goal"))


def goal_source_line(  # noqa: PLR0911 - one return per provenance the page names
    row: Mapping[str, Any], payload: Mapping[str, Any]
) -> str:
    """`goalSourceLine` with nothing held: where the goal came from, and whether it is saved."""
    if _text(payload.get("annotate_unreadable")):
        return ""
    drafted = draft(row, payload)
    discarded = _discarded(row)
    stored = "" if discarded else _text(row.get("annotation_goal"))
    text = drafted.text if drafted is not None else _text(row.get("annotation_goal"))
    if not text.strip():
        return ""
    if drafted is not None:
        if drafted.source == _SESSION_GOAL:
            when = f" at {clock_text(drafted.at)}" if drafted.at else ""
            return f"From your /goal{when} · not saved{_goal_cut(payload) if drafted.cut else ''}"
        clipped = drafted.cut or drafted.text.endswith("…")
        name = _prompt_name(drafted.source)
        return f"Drafted from {name} · not saved{_EXCERPT_READ_WHOLE if clipped else ''}"
    if not stored.strip():
        return ""
    source = _text(row.get("annotation_goal_source"))
    if source in _PROMPT_SOURCES:
        at = _number(row.get("annotation_goal_source_at"))
        if source == _SESSION_GOAL:
            stated = session_goal_candidate(row)
            still_cut = stated is not None and stated.cut and stated.text == stored
            still_cut = still_cut and stated is not None and stated.at == at
            when = f" at {clock_text(at)}" if at is not None and at > 0 else ""
            return f"From your /goal{when} · saved{_goal_cut(payload) if still_cut else ''}"
        excerpt = _EXCERPT_READ_WHOLE if stored.endswith("…") else ""
        return f"From {_prompt_name(source)} · saved{excerpt}"
    saved_at = _number(row.get("annotation_goal_saved_at"))
    if saved_at is None:
        saved_at = _number(row.get("annotation_at"))
    if saved_at is not None and saved_at > 0:
        return f"You typed this · saved at {clock_text(saved_at)}"
    return "You typed this · saved"


# ---------------------------------------------------------------------------------------------
# Whether a press may go (`drift/route.ts` `promptReadingRefusal`, nothing held).


def _route(payload: Mapping[str, Any], harness: str) -> Mapping[str, Any] | None:
    routes = payload.get("reading_routes")
    route = routes.get(harness) if _rec(routes) else None
    return route if _rec(route) else None


def _route_refusal(route: Mapping[str, Any] | None) -> str:
    if route is None:
        return ROUTE_UNREAD
    return "" if route.get("provider") else (_text(route.get("note")) or ROUTE_UNREAD)


def _press_line(row: Mapping[str, Any], held: Mapping[str, Any]) -> str:
    reason = str(held.get("reason"))
    if reason == "idle-unknown" and row.get("acquisition") == "event":
        return PRESS_EVENTS
    return PRESS_LINES.get(reason) or _text(held.get("sentence"))


def _withheld(row: Mapping[str, Any], now: float) -> Mapping[str, Any] | None:
    held = row.get("reading_eligibility")
    if not _rec(held) or held.get("ok") is not False or not isinstance(held.get("reason"), str):
        return None
    until = _number(held.get("until"))
    return None if until is not None and now >= until else held


def cap_reset(retry_at: float, now: float) -> str:
    at, today = time.localtime(retry_at), time.localtime(now)
    same_day = (at.tm_year, at.tm_yday) == (today.tm_year, today.tm_yday)
    return clock_text(retry_at) if same_day else f"{clock_text(retry_at)} tomorrow"


def policy_reason(policy: object, now: float) -> str:  # noqa: PLR0911 - the page's rank order
    if not _rec(policy):
        return MODEL_UNREAD
    reason = policy.get("reason")
    if reason == "run-disabled":
        return MODEL_OFF
    if reason == "store-unavailable":
        return POLICY_UNREADABLE
    if policy.get("off") is True or reason == "model-calls-paused":
        return READINGS_OFF
    if reason == "daily-cap":
        at = _number(policy.get("retry_at"))
        if at is None:
            return "Analysis limit reached. Wait for the next update."
        return f"Analysis limit reached. You can analyze again at {cap_reset(at, now)}."
    return ""


def _lines_of(row: Mapping[str, Any]) -> list[str]:
    found = [_text(row.get(f"annotation_line_{k}")) for k in range(1, _LINES_MAX + 1)]
    return [line for line in found if line.strip()]


def press_refusal(  # noqa: C901, PLR0911, PLR0912 - the page's rank order, one exit per refusal
    payload: Mapping[str, Any], row: Mapping[str, Any], now: float
) -> str:
    """The one reason an Analyze press cannot run, in the page's rank order, or ""."""
    if not _annotate_on(payload):
        return ANNOTATIONS_OFF
    route = _route(payload, _text(row.get("harness")))
    if route is not None and not route.get("provider"):
        return _route_refusal(route)
    held = _withheld(row, now)
    if held is not None:
        return _press_line(row, held)
    goal = _text(row.get("annotation_goal"))
    discarded = _discarded(row)
    if not goal.strip():
        drafted = draft(row, payload)
        candidate = drafted
        if candidate is None and not _opened_with_control(row):
            candidate = prompt_candidate(row, "latest-prompt")
        if candidate is not None and candidate.at is None:
            return PROMPT_TIME_UNPUBLISHED
        if candidate is not None:
            goal, discarded = candidate.text, False
    states = ""
    if discarded:
        said = payload.get("annotate_discard")
        why = _text(said.get("unreadable")).strip() if _rec(said) else ""
        states = f"{why} {SAVE_STEP}" if why else SAVE_STEP
    elif _text(payload.get("annotate_unreadable")):
        states = _text(payload.get("annotate_unreadable"))
    elif not goal.strip() and not _lines_of(row):
        states = NO_WORDS
    else:
        states = policy_reason(payload.get("reading"), now)
    if states:
        return states
    if payload.get("reading_check") not in ("passed", "accepted"):
        return UNAUTHORIZED
    return _route_refusal(route)


def press_body(row: Mapping[str, Any], route: Mapping[str, Any], drafted: Draft | None) -> Row:
    """The page's Analyze press (`drift/actions.ts`), with no `settle_through` and no long mode."""
    provider = str(route.get("provider"))
    body: Row = {
        "harness": row.get("harness"),
        "sid": row.get("sid"),
        "provider": provider,
        "press": True,
        "observer_model": 1,
    }
    if drafted is not None:
        body.update(
            adopt=drafted.source, expected_prompt=drafted.text, expected_prompt_at=drafted.at
        )
    revision = _number(row.get("annotation_revision"))
    body["expected_revision"] = int(revision) if revision is not None else 0
    if provider == "claude":
        body["model"] = str(route.get("model") or "")
    return body


class Pressed(NamedTuple):
    """What a press answered: a job to wait on, or one sentence and nothing started."""

    job: Mapping[str, Any] | None
    notice: Mapping[str, Any] | None
    refusal: str


def press_outcome(  # noqa: C901, PLR0911 - the page's reply order, one exit per answer
    status: int, answer: object, row: Mapping[str, Any], now: float
) -> Pressed:
    """`askForReading`'s reply handling, in its order, as one outcome."""
    body: Mapping[str, Any] = answer if _rec(answer) else {}
    reason = body.get("reason")
    ok = 200 <= status < 300
    if not ok and reason == "annotation-store-busy":
        return Pressed(None, None, STORE_BUSY)
    if not ok and reason == "annotation-store-unavailable":
        return Pressed(None, None, STORE_UNUSABLE)
    if status == 409 and _rec(body.get("job")):
        return Pressed(body["job"], None, "")
    refusals = {
        (409, "provider-changed"): PROVIDER_CHANGED,
        (409, "revision-changed"): REVISION_CHANGED,
        (400, "page-outdated"): CLIENT_OUTDATED,
        (409, "destination-changed"): DESTINATION_CHANGED,
    }
    refused = refusals.get((status, str(reason)))
    if refused is not None:
        return Pressed(None, None, refused)
    if status == 409:
        return Pressed(None, None, IN_FLIGHT)
    route = body.get("route")
    if _rec(route) and not route.get("provider"):
        return Pressed(None, None, _route_refusal(route))
    if reason == "withheld" and isinstance(body.get("withheld"), str):
        held = {"reason": body["withheld"], "sentence": body.get("sentence")}
        return Pressed(None, None, _press_line(row, held))
    if body.get("adoption_refused"):
        return Pressed(None, None, ADOPTION_REFUSED)
    if _rec(body.get("reading")):
        return Pressed(None, None, policy_reason(body["reading"], now) or NOTHING_PRODUCED)
    if not ok:
        return Pressed(None, None, LOST)
    if body.get("ok") is True and _rec(body.get("job")):
        notice = body.get("notice")
        return Pressed(body["job"], notice if _rec(notice) else None, "")
    if body.get("ok") is not True or not isinstance(body.get("produced"), bool):
        return Pressed(None, None, LOST)
    return Pressed(None, None, NOTHING_PRODUCED)


def notice_line(notice: Mapping[str, Any]) -> str:
    """`noticeAnnouncement`: what this request sends, where, as the server recorded it."""
    provider = _text(notice.get("provider"))
    label = PROVIDER_LABELS.get(provider, provider) or "a model"
    destination = printable(notice.get("destination")) or "destination not published"
    parts = [f"Notice: this request sends to {label}.", f"Words go to: {destination}."]
    output = printable(notice.get("tool_output"))
    if output:
        parts.append(f"Tool output goes to: {output}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------
# The one reader of `sources.work.drift_views`. Every key this command reads from the server's
# derivation is read here and nowhere else.


def _work(context: object) -> Mapping[str, Any] | None:
    sources = context.get("sources") if _rec(context) else None
    work = sources.get("work") if _rec(sources) else None
    return work if _rec(work) else None


def view_of(context: object, harness: str, sid: str) -> Mapping[str, Any] | None:
    """This session's row of the focused context's `drift_views`, or None."""
    work = _work(context)
    views = work.get("drift_views") if work is not None else None
    if not isinstance(views, list):
        return None
    for view in views:
        if _rec(view) and view.get("harness") == harness and view.get("sid") == sid:
            return view
    return None


def publishes_views(context: object) -> bool:
    work = _work(context)
    return work is not None and isinstance(work.get("drift_views"), list)


def _numbers(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(printable(n) for n in value if isinstance(n, str))


def adapt(view: Mapping[str, Any]) -> View:
    """The page's derivation for one session, as this command prints it.

    A shape this build does not know is not half-read: an unknown line state, or any value of the
    wrong type, makes the whole view unreadable, and the output sends the reader to the page.
    """
    try:
        lines = tuple(
            LineView(
                key=str(line["key"]),
                state=str(line["state"]),
                why=_text(line.get("why")),
                numbers=_numbers(line.get("numbers")),
                clause=_text(line.get("clause")),
                detail=_text(line.get("detail")),
            )
            for line in view.get("lines") or []
        )
        priors = tuple(
            PriorView(
                key=str(prior["key"]),
                read_at=_number(prior.get("read_at")),
                numbers=_numbers(prior.get("numbers")),
                clause=_text(prior.get("clause")),
                detail=_text(prior.get("detail")),
            )
            for prior in view.get("priors") or []
        )
        stale_raw = view.get("stale")
        stale = (
            StaleView(str(stale_raw["kind"]), _number(stale_raw.get("before")))
            if _rec(stale_raw)
            else None
        )
        analysis, pill = view.get("analysis"), view.get("pill")
        level = analysis.get("level") if _rec(analysis) else None
        count = view.get("unsettled_count")
        departures = tuple(str(key) for key in view.get("departures") or [])
    except (KeyError, TypeError, AttributeError):
        return View("unreadable", None, False, (), (), (), None, False, None)
    malformed = _text(view.get("malformed"))
    unknown = (
        any(line.state not in STATE_WORDS for line in lines)
        or (level is not None and level not in LEVEL_NAMES)
        or (stale is not None and stale.kind not in ("intent", "work"))
    )
    return View(
        malformed=malformed or ("unknown" if unknown else ""),
        level=level if isinstance(level, str) else None,
        so_far=_rec(pill) and pill.get("so_far") is True,
        lines=lines,
        departures=departures,
        priors=priors,
        stale=stale,
        unsettled=view.get("unsettled") is True,
        unsettled_count=count if type(count) is int and count >= 0 else None,
    )


# ---------------------------------------------------------------------------------------------
# What is printed.


def _label(key: str) -> str:
    if key == "goal":
        return "Goal"
    if key == "claims":
        return "What the agent claimed"
    if key == "output":
        return "Output"
    return f"Line {key.removeprefix('line_')}" if key.startswith("line_") else printable(key)


def _line_source(row: Mapping[str, Any], key: str) -> str:
    if not key.startswith("line_"):
        return ""
    return "added from an entry" if row.get(f"annotation_{key}_source") == "entry" else "typed"


def _entries(numbers: Iterable[str]) -> str:
    listed = ", ".join(f"#{n}" for n in numbers if n)
    return f"entries {listed}" if listed else ""


def stale_head(stale: StaleView) -> str:
    """`resultStale`'s head, from the published kind and the first message after the reading."""
    if stale.kind == "intent":
        return "Your intent changed after this analysis."
    if stale.before is not None:
        return (
            f"Read before your message at {clock_text(stale.before)}. New work since this analysis."
        )
    return "New work since this analysis."


def unsettled_line(view: View) -> str:
    if not view.unsettled:
        return ""
    count = view.unsettled_count
    if count == 1:
        return (
            "1 message you sent after your goal was left unsettled, so a departure it could "
            "change reads as not verifiable. The session page can add it as a line or make it "
            "the goal."
        )
    many = f"{count} messages" if count else "Messages"
    return (
        f"{many} you sent after your goal were left unsettled, so a departure they could change "
        "reads as not verifiable. The session page can add them as lines or make one the goal."
    )


def render(  # noqa: C901, PLR0912 - one optional block per field, in the order printed
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
    view: View,
    *,
    adopted: str | None,
    again_hint: str,
) -> list[str]:
    """The reading, one field per line, every value from the board through `printable`."""
    harness, sid = _text(row.get("harness")), _text(row.get("sid"))
    head = f"Drift · {printable(harness)}:{printable(sid)}"
    title = printable(row.get("title"))
    lines = [f"{head} · {title}" if title else head]
    goal = printable(goal_text(row, payload))
    if goal:
        source = goal_source_line(row, payload)
        lines.append(f"Goal ({source}): {goal}" if source else f"Goal: {goal}")
    if adopted:
        name = _prompt_name(adopted)
        lines.append(f"Saved the goal drafted from {name}, so this reading reads against it.")
    assessment = row.get("annotation_assessment")
    read_at = _number(assessment.get("read_at")) if _rec(assessment) else None
    if read_at is not None:
        age = format_duration(max(0.0, (_number(payload.get("generated")) or read_at) - read_at))
        so_far = " · so far" if view.so_far else ""
        lines.append(f"Read at {clock_text(read_at)}, {age} ago{so_far}")
    if view.stale is not None:
        lines.append(f"{stale_head(view.stale)} {again_hint}")
    if said := unsettled_line(view):
        lines.append(said)
    lines.append(PROVENANCE)
    if view.level is not None:
        lines.append(f"Level: {LEVEL_NAMES[view.level]}{' so far' if view.so_far else ''}")
    if view.lines:
        lines.append("Outcome lines:")
        for line in view.lines:
            source = _line_source(row, line.key)
            named = f"{_label(line.key)} ({source})" if source else _label(line.key)
            text = f"- {STATE_WORDS[line.state]} · {named}: {printable(line.clause)}"
            why = WHY_WORDS.get(line.why, "") if line.state == "cant-tell" else ""
            lines.append(f"{text} — {why}" if why else text)
    by_key = {line.key: line for line in view.lines}
    departed = [by_key[key] for key in view.departures if key in by_key]
    if departed:
        lines.append("Departures:")
        for line in departed:
            parts = [f'{_label(line.key)}: "{printable(line.clause)}"', _entries(line.numbers)]
            parts.append(printable(line.detail))
            lines.append("- " + " · ".join(part for part in parts if part))
    if view.priors:
        lines.append("Earlier departures:")
        for prior in view.priors:
            parts = [f'{_label(prior.key)}: "{printable(prior.clause)}"']
            if prior.read_at is not None:
                parts.append(f"read at {clock_text(prior.read_at)}")
            parts.extend([_entries(prior.numbers), printable(prior.detail)])
            lines.append("- " + " · ".join(part for part in parts if part))
    return lines


def correction_text(parts: object) -> str | None:
    """`correctionText`: each text part, a placeholder drawn as nothing; None when unreadable."""
    if not isinstance(parts, list):
        return None
    text = "".join(part for part in parts if isinstance(part, str))
    # Line by line, so the server's line breaks survive and nothing in them steers the terminal.
    return "\n".join(printable(line) for line in text.split("\n"))


# ---------------------------------------------------------------------------------------------
# The run.


def _emit(stream: TextIO, lines: Iterable[str]) -> None:
    text = "".join(f"{line}\n" for line in lines)
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(encoding, "replace").decode(encoding, "replace"))
    stream.flush()


def _row_of(payload: object, harness: str, sid: str) -> Mapping[str, Any] | None:
    rows = payload.get("sessions") if _rec(payload) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if _rec(row) and row.get("harness") == harness and row.get("sid") == sid:
            return row
    return None


def _job_of(payload: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    jobs = payload.get("reading_jobs")
    job = jobs.get(key) if _rec(jobs) else None
    return job if _rec(job) and isinstance(job.get("id"), str) else None


def _project(row: Mapping[str, Any]) -> str:
    return _text(row.get("project_key")) or _text(row.get("project"))


def _assessment(row: Mapping[str, Any]) -> str:
    return json.dumps(row.get("annotation_assessment"), sort_keys=True, default=str)


class _Run:
    """One `--drift`: the board, the streams and the clock, and the session it is about."""

    def __init__(  # noqa: PLR0913 — each is a seam the tests drive
        self,
        harness: str,
        sid: str,
        *,
        again: bool,
        at_shell: bool,
        board: Board,
        port: int,
        out: TextIO,
        err: TextIO,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.harness, self.sid, self.key = harness, sid, f"{harness}:{sid}"
        self.again, self.at_shell, self.board, self.port = again, at_shell, board, port
        self.out, self.err, self.clock, self.sleep = out, err, clock, sleep
        self.page = ""

    def url(self, row: Mapping[str, Any]) -> str:
        self.page = session_url(self.port, _project(row), self.harness, self.sid)
        return self.page

    def interrupted(self) -> int:
        _emit(self.err, [f"{INTERRUPTED} {self.page}".rstrip()])
        return EXIT_INTERRUPTED

    def refuse(self, sentence: str) -> int:
        _emit(self.err, [sentence])
        return 1

    def data(self) -> Mapping[str, Any] | None:
        try:
            payload = self.board.data()
        except Lost:
            return None
        return payload if _rec(payload) and isinstance(payload.get("sessions"), list) else None

    def again_hint(self) -> str:
        if self.at_shell:
            return f"Run `spacedock-compass --drift again --session {self.key}` to check again."
        return "Ask for `drift again` to check again."

    def main(self) -> int:  # noqa: PLR0911 - each exit is one refusal or one answer
        payload = self.data()
        if payload is None:
            return self.refuse(LOST)
        row = _row_of(payload, self.harness, self.sid)
        if row is None:
            return self.refuse(
                f"Compass has no session {printable(self.key)} on the board, so nothing was read."
            )
        self.url(row)
        if self.harness != "claude":
            # The page reads every harness it has a route for; this command reads Claude Code's
            # this milestone. So the reader is sent to the page, and nothing says it cannot read.
            _emit(self.out, [f"Read this session's drift on its page: {self.url(row)}"])
            return 0
        if not _annotate_on(payload):
            return self.refuse(ANNOTATIONS_OFF)
        job = _job_of(payload, self.key)
        if job is not None:
            return self.wait(job, row, adopted=None)
        try:
            context = self.board.context(_project(row), self.key)
        except Lost:
            context = None
        if _work(context) is None:
            return self.refuse(f"{CONTEXT_UNREAD} {self.url(row)}")
        if not publishes_views(context):
            return self.refuse(
                "This dashboard does not publish the reading this command prints, so nothing was "
                f"read. Read the session on its page: {self.url(row)}"
            )
        if _rec(row.get("annotation_assessment")) and not self.again:
            return self.show(payload, row, context, adopted=None)
        return self.press(payload, row)

    def press(self, payload: Mapping[str, Any], row: Mapping[str, Any]) -> int:
        now = self.clock()
        refusal = press_refusal(payload, row, now)
        if refusal:
            return self.refuse(refusal)
        route = _route(payload, self.harness) or {}
        drafted = draft(row, payload)
        _emit(self.out, allowance_lines(route))
        try:
            status, answer = self.board.post("/api/reading", press_body(row, route, drafted))
        except Lost:
            return self.refuse(LOST)
        pressed = press_outcome(status, answer, row, now)
        if pressed.refusal:
            return self.refuse(pressed.refusal)
        if pressed.notice is not None:
            _emit(self.out, [notice_line(pressed.notice)])
        assert pressed.job is not None  # noqa: S101 — `press_outcome` gives one or the other
        started = status == 202 and drafted is not None
        return self.wait(pressed.job, row, adopted=drafted.source if started and drafted else None)

    def wait(self, job: Mapping[str, Any], row: Mapping[str, Any], *, adopted: str | None) -> int:
        """Wait for `job` to leave the board, then show what it stored, or why it stored none."""
        job_id = str(job.get("id"))
        began = self.clock()
        started_at = _number(job.get("started_at"))
        seen = _assessment(row)
        said = ""
        payload: Mapping[str, Any] | None = None
        try:
            while True:
                payload = self.data()
                if payload is None:
                    return self.refuse(LOST)
                running = _job_of(payload, self.key)
                if running is None or running.get("id") != job_id:
                    break
                step = self.step(running)
                if step and step != said:
                    _emit(self.err, [f"Analyzing drift: {step}"])
                    said = step
                if not self.at_shell and self.clock() - began >= IN_SESSION_WAIT_SEC:
                    _emit(self.out, [STILL_READING])
                    return 0
                self.sleep(POLL_SEC)
        except KeyboardInterrupt:
            return self.cancel(job_id)
        row = _row_of(payload, self.harness, self.sid) or row
        withheld = _text(row.get("annotation_reading_withheld"))
        withheld_at = _number(row.get("annotation_reading_withheld_at"))
        if withheld and (started_at is None or (withheld_at or 0) >= started_at):
            return self.refuse(printable(withheld))
        if _assessment(row) == seen or not _rec(row.get("annotation_assessment")):
            return self.refuse(NOTHING_PRODUCED)
        try:
            context = self.board.context(_project(row), self.key)
        except Lost:
            context = None
        return self.show(payload, row, context, adopted=adopted)

    @staticmethod
    def step(job: Mapping[str, Any]) -> str:
        steps = job.get("steps")
        for step in steps if isinstance(steps, list) else []:
            if _rec(step) and step.get("phase") == job.get("phase"):
                return printable(step.get("text"))
        return ""

    def cancel(self, job_id: str) -> int:
        body = {
            "harness": self.harness,
            "sid": self.sid,
            "job": job_id,
            "press": True,
            "observer_model": 1,
        }
        try:
            status, _answer = self.board.post("/api/reading/cancel", body)
        except Lost:
            _emit(self.out, [CANCEL_LOST])
            return EXIT_INTERRUPTED
        _emit(self.out, [CANCELLED if 200 <= status < 300 else CANCEL_LATE])
        return EXIT_INTERRUPTED

    def show(
        self,
        payload: Mapping[str, Any],
        row: Mapping[str, Any],
        context: object,
        *,
        adopted: str | None,
    ) -> int:
        raw = view_of(context, self.harness, self.sid)
        view = adapt(raw) if raw is not None else None
        if view is None or view.malformed:
            return self.refuse(
                f"This build cannot read the stored reading, so it is not shown here. Read it on "
                f"the session page: {self.url(row)}"
            )
        lines = render(row, payload, view, adopted=adopted, again_hint=self.again_hint())
        if view.departures:
            lines.extend(self.correction())
        lines.append(f"Session page: {self.url(row)}")
        _emit(self.out, lines)
        return 0

    def correction(self) -> list[str]:
        """The composed correction from a shell; inside a session, one line that it is ready.

        Printed into a session, the correction would be read by the agent it is addressed to,
        which is delivery without the reader's paste
        ([DEC-25](docs/design-reading-a-session.md#dec-25-a-correction-stays-yours-to-copy)).
        """
        offset = time.localtime().tm_gmtoff // 60
        body = {"harness": self.harness, "sid": self.sid, "utc_offset_minutes": offset}
        try:
            status, answer = self.board.post("/api/correction", body)
        except Lost:
            return []
        reply: Mapping[str, Any] = answer if _rec(answer) else {}
        if not 200 <= status < 300:
            return []
        if reply.get("ok") is not True:
            why = reply.get("why") if reply.get("reason") == "too-long" else None
            return [printable(why)] if isinstance(why, str) and why else []
        text = correction_text(reply.get("parts"))
        if not text:
            return []
        if not self.at_shell:
            command = f"spacedock-compass --drift --session {self.key}"
            return [CORRECTION_READY.format(command=command)]
        return ["Correction to copy:", text]


def run(  # noqa: PLR0913 — the seams `terminal_client` fills and the tests replace
    harness: str,
    sid: str,
    *,
    again: bool,
    at_shell: bool,
    board: Board,
    port: int,
    out: TextIO,
    err: TextIO,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """`--drift`: print the stored reading for free, or spend one and wait for it.

    `at_shell` is whether the session was named with `--session`, which is a person at a shell
    rather than an agent inside the session, and decides only whether the correction is printed.
    """
    drift = _Run(
        harness,
        sid,
        again=again,
        at_shell=at_shell,
        board=board,
        port=port,
        out=out,
        err=err,
        clock=clock,
        sleep=sleep,
    )
    try:
        return drift.main()
    except KeyboardInterrupt:
        # Only outside the wait, which cancels its own job: here no job id is known yet.
        return drift.interrupted()
