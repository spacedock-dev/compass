"""What `--sessions` and `--sessions waiting` print, derived from one `/api/data` payload.

Standard library only, and no other runtime module, for the reason `terminal_client` gives: a short
command runs before the collectors load. The reasoning, and what was rejected, is in
[R-1](docs/design-runtime-architecture.md#r-1-one-responsibility-per-file-and-the-launcher-owns-none).

Every rule here is a port of one the board applies in TypeScript: the Sessions screen's two groups
(`observed/model.ts`, `sessions/rows.ts`), its row words (`observed/session.ts`) and the Attention
queue's "Needs you now" (`attention/model.ts`). The board is the oracle. A recorded payload and an
expected file are read by this module's tests and by `terminalParity.test.ts`, so a rule that moves
on one side fails the other. Nothing is composed here that the board does not say, and the drift
level and the word "unread" are never said: readership is not published, and
[DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)
keeps a level off a Sessions row.

A payload is untrusted. Collectors leave control characters in published text on purpose, so every
value that is printed passes through `printable` first.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Mapping
from typing import Any, Final, NamedTuple, TypeGuard
from urllib.parse import quote

Row = Mapping[str, Any]

GOAL_WIDTH: Final = 120

# Spelt as the page spells them (`sessions/intent.ts`) and checked against the vocabulary fixture,
# which the Python producers generate. A reading with a key outside the list is one this build
# cannot read, and a reading half-read is not shown.
READING_ASSESSMENT_KEYS: Final = (
    "goal_source",
    "goal_source_at",
    "revision_read",
    "revision_read_at",
    "window_start",
    "read_at",
    "stamp",
    "cutoff",
    "scope",
    "scope_text",
    "ended_at_read",
    "evidence_through",
    "coverage",
    "goal_verdict",
    "ci",
    "criteria",
)
READING_CLAIMS: Final = "claims"
_OUTCOME_LINE = re.compile(r"line_([1-9][0-9]*)")
_OUTCOME_LINES_MAX = 6
_SESSION_GOAL: Final = "session-goal"
_PROMPT_SOURCES: Final = ("latest-prompt", "first-prompt", "chosen-prompt", _SESSION_GOAL)
_GOAL_HARNESSES: Final = ("claude", "codex", "antigravity")
_STOP_HARNESSES: Final = ("claude", "codex")
_QUIET_LAUNCH_SEC: Final = 1800

_COMMANDS: Final = {"claude": "claude --resume {}", "codex": "codex resume {}"}
# The page's `resumeCommand` grammar, first character included: a `-`-leading token is a flag to
# either CLI, and both have a valueless flag that turns their permission checks off.
_RESUME_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}")
_UUID_CHARS: Final = frozenset("0123456789abcdefABCDEF-")
_CLAUDE_SID_LEN: Final = 8

_ESCAPES = re.compile(
    "\x1b\\][^\x07\x1b\x9c]*(?:\x07|\x1b\\\\|\x9c)?"  # an OSC, up to its terminator
    "|\x1b[PX^_][^\x1b\x9c]*(?:\x1b\\\\|\x9c)?"  # DCS, SOS, PM and APC strings
    "|(?:\x1b\\[|\x9b)[0-?]*[ -/]*[@-~]?"  # a CSI
    "|\x1b[ -/]*[0-~]?"  # any other two-character escape
)
# Bidirectional marks and embeddings, and the two line separators: none is a control character by
# category, and all of them reorder or break what a terminal draws.
_UNSAFE = re.compile(r"[\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SPACES = re.compile(r"[ \t\r\n\f\v\u2028\u2029]+")

_ACTIVE_EMPTY: Final = "No exact session has active evidence right now."
_HISTORY_EMPTY: Final = "No recent-history rows in this payload."
_UNCONFIRMED: Final = "Unconfirmed: no positive observation in 5m; prompt may still be standing"


def printable(value: object) -> str:
    """`value` as one line of text a terminal cannot be steered by.

    Escape sequences are removed whole, so an OSC 52 clipboard write leaves no payload text behind.
    Bidirectional controls and every remaining control character go too, and every run of
    whitespace, line breaks included, becomes one space.
    """
    text = _ESCAPES.sub("", "" if value is None else str(value))
    text = _SPACES.sub(" ", text)
    return _CONTROLS.sub("", _UNSAFE.sub("", text)).strip()


def format_duration(seconds: object) -> str | None:
    """The page's one duration spelling: the two largest units, floored."""
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    whole = math.floor(seconds)
    if whole < 60:
        return f"{whole}s"
    if whole < 3600:
        return f"{whole // 60}m"
    if whole < 86400:
        return f"{whole // 3600}h {whole % 3600 // 60}m"
    return f"{whole // 86400}d {whole % 86400 // 3600}h"


def _rec(value: object) -> bool:
    return isinstance(value, dict)


def _records(value: object) -> list[Any]:
    return [item for item in value if _rec(item)] if isinstance(value, list) else []


def _trimmed(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _identity(value: object) -> str:
    return str(value) if value else ""


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _positive(value: object) -> float:
    number = _num(value)
    return number if number is not None and number > 0 else 0.0


def _integer(value: object) -> TypeGuard[int | float]:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def _age(generated: float | None, stamp: object) -> float | None:
    at = _num(stamp)
    if generated is None or at is None or at <= 0:
        return None
    return max(0.0, generated - at)


def _since(generated: float | None, stamp: object) -> str | None:
    return format_duration(_age(generated, stamp))


def _key(source: Row) -> tuple[str, str]:
    return (_identity(source.get("harness")), _identity(source.get("sid")))


def claude_sid(raw: str) -> str | None:
    """Claude's collector key for a native id: its first eight characters, if it is UUID-shaped.

    `events._claude_sid` is the rule, written out again because the client cannot import it. A test
    holds the two equal.
    """
    if len(raw) < _CLAUDE_SID_LEN or any(char not in _UUID_CHARS for char in raw):
        return None
    return raw[:_CLAUDE_SID_LEN]


def resume_command(harness: str, resume_id: object) -> str:
    """The command the board would copy: two harnesses, and only for a token that passes twice."""
    template = _COMMANDS.get(harness)
    if template is None or not isinstance(resume_id, str):
        return ""
    return template.format(resume_id) if _RESUME_TOKEN.fullmatch(resume_id) else ""


def _gaps(source: Row) -> list[Any]:
    gaps = source.get("source_gaps")
    return gaps if isinstance(gaps, list) else []


def _ended_at(source: Row) -> float | None:
    at = _num(source.get("ended_at"))
    return at if at is not None and at > 0 else None


def _stop(source: Row) -> str | None:
    """The turn stop a row rests on: the hook's, else the transcript's on a harness that has one."""
    if _positive(source.get("finished_at")):
        return "hook"
    recorded = _positive(source.get("turn_end_at"))
    if recorded and _identity(source.get("harness")) in _STOP_HARNESSES:
        return "transcript"
    return None


def _stop_record(source: Row) -> str:
    return "Codex's rollout" if source.get("harness") == "codex" else "Claude Code's transcript"


def _outcome(source: Row, *, ended: bool, state: object) -> tuple[bool, str, str]:
    """Whether a stop or end was observed, its sentence in the board's words, and the git text."""
    stopped = state == "idle" and _positive(source.get("finished_at")) > 0
    recorded = _stop(source) if state == "idle" else None
    transcript = not stopped and recorded == "transcript"
    known = ended or stopped or transcript
    if ended:
        prefix = "Session ended"
    elif stopped:
        prefix = "Stop observed"
    else:
        prefix = f"Turn stop in {_stop_record(source)}"
    dirty = source.get("dirty")
    if dirty is True:
        tail = " with uncommitted work"
    elif dirty is False:
        tail = "; git state clean"
    else:
        tail = "; git state not measured"
    git = ""
    if isinstance(dirty, bool):
        git = "Uncommitted work observed" if dirty else "Git state reported clean"
        changed = source.get("changed")
        if dirty and _integer(changed) and changed >= 0:
            git = f"{int(changed)} changed entries"
    return known, (prefix + tail) if known else "", git or "Git state was not measured"


def _owner(rows: list[Any], ask: Row) -> Row | None:
    """The one session an ask belongs to, matching exactly one row, else nobody's."""
    sid = _identity(ask.get("session_id"))
    if not sid:
        return None
    harness = _identity(ask.get("harness"))
    matches = [
        row
        for row in rows
        if _identity(row.get("sid")) == sid
        and (not harness or _identity(row.get("harness")) == harness)
    ]
    return matches[0] if len(matches) == 1 else None


def _ask_age(ask: Row) -> float | None:
    age = _num(ask.get("age_sec"))
    return age if age is not None and age >= 0 else None


def _delegated_risky(source: Row, generated: float | None) -> bool:
    """An unpaired launch and half an hour of recorded silence (`delegatedWork`)."""
    count, unpaired = source.get("delegated_launches"), source.get("delegated_unpaired")
    if not (_integer(count) and count >= 0 and _integer(unpaired) and unpaired >= 0):
        return False
    quiet = _positive(source.get("delegated_quiet_since"))
    now = generated or 0.0
    age = now - quiet if 0 < quiet <= now else None
    return unpaired > 0 and age is not None and age >= _QUIET_LAUNCH_SEC


def _loop_errors(source: Row) -> int:
    loop = source.get("loop")
    errors = loop.get("errors") if isinstance(loop, dict) else None
    return int(errors) if _integer(errors) and errors > 0 else 0


class Entry(NamedTuple):
    """One session as a reader of the board is told about it, in the board's own words."""

    harness: str
    sid: str
    project: str
    harness_label: str
    title: str
    state: str
    now: str
    block_note: str
    goal_label: str
    goal: str
    outcome: str | None
    git: str | None
    command: str
    ended: str
    drift: str | None
    source: Row


class Waiter(NamedTuple):
    """One thing waiting on the reader: a session, or a question nobody owns."""

    entry: Entry | None
    asks: list[Row]
    reason: str
    note: str
    age: str | None


class Board(NamedTuple):
    active: list[Entry]
    history: list[Entry]
    waiting: list[Waiter]
    coverage: str
    unreported: list[str]
    annotate: bool


class _Seen(NamedTuple):
    source: Row
    ended: bool
    working: bool
    needs: bool
    quiet: bool
    question: str
    outcome_known: bool
    outcome: str
    git: str
    entry: Entry
    block_known: bool

    @property
    def ask_known(self) -> bool:
        return bool(self.question)

    @property
    def active(self) -> bool:
        return self.working or self.needs or self.ask_known


def _now_text(
    source: Row, *, ended: bool, quiet: bool, question: str, generated: float | None
) -> str:
    state = source.get("state")
    if ended:
        return "Session reported its own end"
    if state not in {"working", "needs_input", "idle"}:
        return ""
    doing = next(
        (
            task
            for task in _records(source.get("tasks"))
            if task.get("status") == "in_progress" and _trimmed(task.get("subject"))
        ),
        None,
    )
    if doing is not None:
        return _trimmed(doing.get("subject"))
    if quiet and not question:
        quiet_for = _since(generated, _num(source.get("last_activity")))
        if quiet_for:
            return f"last active {quiet_for} ago"
        return "quiet" if _trimmed(source.get("state_detail")) else ""
    return _trimmed(source.get("state_detail"))


def _block_note(source: Row, *, needs: bool, question: str) -> str:
    if question:
        return question
    if not needs:
        return ""
    if source.get("wait_unconfirmed"):
        return _UNCONFIRMED
    return _trimmed(source.get("state_detail")) or "Block reported"


def _title(source: Row) -> str:
    published = _trimmed(source.get("title"))
    if published:
        return published
    return (
        "No name: the session opened with a command"
        if source.get("first_prompt_control") is True
        else "Title not published"
    )


def _row_state(*, ended: bool, needs: bool, question: str, working: bool, quiet: bool) -> str:
    if ended:
        return "Ended"
    if needs or question:
        return "Waiting on you"
    if working:
        return "Working"
    return "Idle" if quiet else "State not published"


def _reading_names_constraint(key: str) -> bool:
    if key in {"goal", READING_CLAIMS, "output"}:
        return True
    match = _OUTCOME_LINE.fullmatch(key)
    return bool(match and int(match.group(1)) <= _OUTCOME_LINES_MAX)


def _reading_departs(source: Row) -> bool:
    """The stored reading itself departs: a line found a departure and cites what it rests on."""
    raw = source.get("annotation_assessment")
    if not isinstance(raw, dict) or not all(key in READING_ASSESSMENT_KEYS for key in raw):
        return False
    criteria = raw.get("criteria")
    criteria = criteria if isinstance(criteria, dict) else {}
    for key, criterion in criteria.items():
        if not _reading_names_constraint(key) or key == READING_CLAIMS:
            continue
        cites = criterion.get("cites") if isinstance(criterion, dict) else None
        if (
            isinstance(criterion, dict)
            and criterion.get("result") == "departure"
            and isinstance(cites, list)
            and any(isinstance(cite, str) and cite.strip() for cite in cites)
        ):
            return True
    return False


def _departures(source: Row, *, annotate: bool) -> list[float | None]:
    """When each recorded departure was made, `None` where the record kept no time."""
    if not annotate:
        return []
    raised = source.get("departures")
    found = (
        [_num(row.get("at")) for row in raised if isinstance(row, dict)]
        if isinstance(raised, list)
        else []
    )
    raw = source.get("annotation_assessment")
    if isinstance(raw, dict) and _reading_departs(source):
        found.append(_num(raw.get("read_at")))
    return found


def _drift_age(source: Row, *, annotate: bool, generated: float | None) -> str | None:
    found = _departures(source, annotate=annotate)
    if not found:
        return None
    dated = [at for at in found if at is not None and at > 0]
    age = _since(generated, max(dated)) if dated else None
    return "age unknown" if age is None else f"{age} ago"


def _goal(source: Row, *, annotate: bool, unreadable: bool) -> tuple[str, str]:
    """The goal cell the board draws, without a prompt the reader chose in their own browser."""
    if not annotate:
        return "Goal", "Annotations off"
    typed = _text(source.get("annotation_goal")).strip()
    harness = _text(source.get("harness"))
    asked = _asked(source) if harness == "claude" else ""
    codex_prompt = (
        _text(source.get("title")).strip()
        if harness == "codex" and source.get("prompt_states_work") is True
        else ""
    )
    prompt = asked or codex_prompt
    draft = None if typed or unreadable else _draft(source)
    if typed:
        origin = _text(source.get("annotation_goal_source"))
        label = (
            "Goal · from /goal"
            if origin == _SESSION_GOAL
            else "Goal · from your prompt"
            if origin in _PROMPT_SOURCES
            else "Goal · your words"
        )
        return label, typed
    if draft is not None:
        label = {
            "first-prompt": "Goal · your first prompt",
            _SESSION_GOAL: "Goal · your /goal",
        }.get(draft[1], "Goal · your latest prompt")
        return label, draft[0]
    text = "" if _opened_with_control(source) else prompt
    return ("Goal · your latest prompt", text) if text else ("Goal", "")


def _opened_with_control(source: Row) -> bool:
    return (
        source.get("harness") in {"claude", "codex"} and source.get("first_prompt_control") is True
    )


def _copied(source: Row, field: str) -> bool:
    entries = source.get("copied_prompts")
    return isinstance(entries, list) and any(
        isinstance(entry, dict)
        and isinstance(entry.get("quoted_as"), list)
        and field in entry["quoted_as"]
        for entry in entries
    )


def _asked(source: Row) -> str:
    """The Claude instruction the session was asked, unless it quotes a copied correction."""
    instruction = source.get("instruction")
    if not isinstance(instruction, dict) or _copied(source, "instruction"):
        return ""
    if _text(instruction.get("label")) != "asked":
        return ""
    return _text(instruction.get("text")).strip()


def _prompt_candidate(source: Row, which: str) -> tuple[str, str] | None:
    harness = _text(source.get("harness"))
    if harness not in {"claude", "codex"}:
        return None
    text, at = "", None
    if which == "first-prompt":
        if _copied(source, "first_prompt"):
            return None
        text, at = _text(source.get("first_prompt")), _num(source.get("first_prompt_at"))
    elif harness == "claude":
        asked = _asked(source)
        if asked:
            instruction = source["instruction"]
            text, at = _text(instruction.get("text")), _num(instruction.get("at"))
    elif source.get("prompt_states_work") is True:
        text, at = _text(source.get("title")), _num(source.get("prompt_at"))
    return (text, which) if text and at is not None and at > 0 else None


def _draft(source: Row) -> tuple[str, str] | None:
    """The words the session page would draft as this session's goal, and where they came from."""
    stated = source.get("session_goal")
    if _text(source.get("harness")) in _GOAL_HARNESSES and isinstance(stated, dict):
        cut = stated.get("cut") is True and isinstance(stated.get("offered"), str)
        words = stated.get("offered") if cut else stated.get("text")
        text = words.strip() if isinstance(words, str) else ""
        if text and _positive(stated.get("at")):
            return text, _SESSION_GOAL
    if _opened_with_control(source):
        return None
    for which in ("first-prompt", "latest-prompt"):
        candidate = _prompt_candidate(source, which)
        if candidate is not None:
            return candidate
    return None


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.split("\n") if line.strip()), "")


def _cut(text: str) -> str:
    line = printable(_first_line(text))
    return line if len(line) <= GOAL_WIDTH else line[: GOAL_WIDTH - 1].rstrip() + "…"


def _lane_order(sources: list[Any]) -> list[int]:
    """The board's lane order over every row: waits, working, idle by recency, then the rest."""
    index = range(len(sources))
    states = [source.get("state") for source in sources]

    def sid(i: int) -> str:
        return _identity(sources[i].get("sid"))

    def long_turn(i: int) -> int:
        turn = sources[i].get("turn")
        return 1 if isinstance(turn, dict) and turn.get("long") else 2

    gates = [i for i in index if states[i] == "needs_input"]
    working = sorted(
        (i for i in index if states[i] == "working"), key=lambda i: (long_turn(i), sid(i))
    )
    idle = sorted(
        (i for i in index if states[i] == "idle"),
        key=lambda i: (-(_num(sources[i].get("last_activity")) or 0.0), sid(i)),
    )
    other = [i for i in index if _text(states[i] or "") not in {"needs_input", "working", "idle"}]
    return [*gates, *working, *idle, *other]


def _observe(
    source: Row,
    asks: list[Row],
    harness: Row | None,
    labels: Mapping[str, str],
    *,
    generated: float | None,
    annotate: bool,
    unreadable: bool,
) -> _Seen:
    ended = _ended_at(source) is not None
    state = source.get("state")
    working, needs = not ended and state == "working", not ended and state == "needs_input"
    quiet = not ended and state == "idle"
    question = "\n".join(q for q in (_trimmed(ask.get("question")) for ask in asks) if q)
    gaps = _gaps(source)
    reporter = bool(
        harness
        and not harness.get("error")
        and harness.get("reports_needs_input") is True
        and "block state" not in gaps
    )
    known, outcome, git = _outcome(source, ended=ended, state=state)
    note = _block_note(source, needs=needs, question=question)
    goal_label, goal = _goal(source, annotate=annotate, unreadable=unreadable)
    harness_key = _text(source.get("harness"))
    entry = Entry(
        harness=harness_key,
        sid=_text(source.get("sid")),
        project=_text(source.get("project")),
        harness_label=labels.get(harness_key) or harness_key,
        title=_title(source),
        state=_row_state(ended=ended, needs=needs, question=question, working=working, quiet=quiet),
        now=_now_text(source, ended=ended, quiet=quiet, question=question, generated=generated),
        block_note=note,
        goal_label=goal_label,
        goal=goal,
        outcome=outcome if known else None,
        git=git if known else None,
        command=resume_command(harness_key, source.get("resume_id")),
        ended=(
            f"ended {since} ago"
            if ended and (since := _since(generated, _ended_at(source)))
            else ""
        ),
        drift=_drift_age(source, annotate=annotate, generated=generated),
        source=source,
    )
    return _Seen(
        source=source,
        ended=ended,
        working=working,
        needs=needs,
        quiet=quiet,
        question=question,
        outcome_known=known,
        outcome=outcome,
        git=git,
        entry=entry,
        block_known=bool(needs or question or reporter),
    )


def _groups(
    seen: list[_Seen], order: list[int], *, annotate: bool
) -> tuple[list[Entry], list[Entry]]:
    """The Sessions screen's two groups: a held request, a recorded departure, then the rest."""
    ordered = [seen[i] for i in order]
    ordered = [s for s in ordered if s.active] + [s for s in ordered if not s.active]

    def rank(one: _Seen) -> int:
        if one.needs or one.ask_known:
            return 0
        return 1 if _departures(one.source, annotate=annotate) else 2

    active = [s for s in ordered if s.active or rank(s) < 2]
    held = {_key(s.source) for s in active}
    active.sort(key=rank)
    history = [s for s in ordered if _key(s.source) not in held]
    return [s.entry for s in active], [s.entry for s in history]


def _locale_key(value: object) -> tuple[str, str]:
    """Close to `localeCompare(..., 'en')` for the plain labels sessions carry: case-blind first."""
    text = _text(value)
    return (text.casefold(), text.swapcase())


class _Subject(NamedTuple):
    key: tuple[str, ...]
    owner: Row | None
    asks: list[Row]
    at: int


def _subjects(rows: list[Any], asks: list[Any]) -> list[_Subject]:
    """The Attention queue's needs: every worded ask, then each waiting row no ask holds."""
    found: dict[tuple[str, ...], _Subject] = {}
    key: tuple[str, ...]
    for index, ask in enumerate(asks):
        if not _text(ask.get("question")).strip():
            continue
        owner = _owner(rows, ask)
        if owner is None:
            key = ("ask", _text(ask.get("id")) if ask.get("id") is not None else f"index:{index}")
            found[key] = _Subject(key, None, [ask], index)
            continue
        key = ("session", *_key(owner))
        held = found.get(key)
        found[key] = _Subject(
            key, owner, [*(held.asks if held else []), ask], held.at if held else index
        )
    for index, row in enumerate(rows):
        key = ("session", *_key(row))
        if row.get("state") == "needs_input" and key not in found:
            found[key] = _Subject(key, row, [], index)
    return list(found.values())


def _by_ask_age(left: _Subject, right: _Subject) -> int:
    """Older wait first, then the order the asks arrived in, where both are measured."""
    lage = max([a for a in map(_ask_age, left.asks) if a is not None], default=-1.0)
    rage = max([a for a in map(_ask_age, right.asks) if a is not None], default=-1.0)
    if lage != rage:
        return -1 if rage < lage else 1
    return left.at - right.at if lage >= 0 else 0


def _by_blocked_age(left: _Subject, right: _Subject, generated: float | None) -> int:
    """A wait with a stamp ahead of one without, then the older one first."""
    lage = _age(generated, left.owner.get("blocked_since") if left.owner else None)
    rage = _age(generated, right.owner.get("blocked_since") if right.owner else None)
    if (lage is None) != (rage is None):
        return -1 if rage is None else 1
    if lage is not None and rage is not None and lage != rage:
        return -1 if rage < lage else 1
    return 0


def _compare(
    left: _Subject, right: _Subject, *, generated: float | None, order: dict[str, int]
) -> int:
    if bool(left.asks) != bool(right.asks):
        return -1 if left.asks else 1
    ruled = _by_ask_age(left, right) if left.asks else _by_blocked_age(left, right, generated)
    return ruled or _stable(left, right, order)


def _stable(left: _Subject, right: _Subject, order: dict[str, int]) -> int:
    def identity(one: _Subject) -> Row:
        return one.owner or {}

    unplaced = 1 << 53
    lharness = order.get(_identity(identity(left).get("harness")), unplaced)
    rharness = order.get(_identity(identity(right).get("harness")), unplaced)
    if lharness != rharness:
        return lharness - rharness
    for field in ("project", "sid"):
        lkey, rkey = _locale_key(identity(left).get(field)), _locale_key(identity(right).get(field))
        if lkey != rkey:
            return -1 if lkey < rkey else 1
    if left.at != right.at:
        return left.at - right.at
    return -1 if left.key < right.key else (1 if left.key > right.key else 0)


def _hidden_by_a_risk_row(seen: _Seen, generated: float | None) -> bool:
    """Whether the board draws this row as a risk and so leaves it out of "Needs you now".

    Only an ended row can be both waiting and a risk: a live waiting row carries its own category.
    """
    source = seen.source
    if seen.needs or seen.ask_known:
        return False
    if seen.outcome_known and source.get("dirty") is True:
        return True
    return _loop_errors(source) > 0 or _delegated_risky(source, generated)


def _is_caller(source: Row, exclude: str | None) -> bool:
    prefix = claude_sid(exclude) if exclude else None
    if prefix is None or source.get("harness") != "claude":
        return False
    resume = source.get("resume_id")
    if isinstance(resume, str) and resume:
        return resume == exclude
    return _text(source.get("sid")) == prefix


def _waiters(
    subjects: list[_Subject],
    entries: dict[tuple[str, str], _Seen],
    *,
    generated: float | None,
    exclude: str | None,
    order: dict[str, int],
) -> list[Waiter]:
    def compare(left: _Subject, right: _Subject) -> int:
        return _compare(left, right, generated=generated, order=order)

    ordered = sorted(subjects, key=functools.cmp_to_key(compare))
    waiters: list[Waiter] = []
    for subject in ordered:
        seen = entries.get(_key(subject.owner)) if subject.owner else None
        if seen is not None and (
            _is_caller(seen.source, exclude) or _hidden_by_a_risk_row(seen, generated)
        ):
            continue
        waiters.append(_waiter(subject, seen, generated))
    return waiters


def _waiter(subject: _Subject, seen: _Seen | None, generated: float | None) -> Waiter:
    entry = seen.entry if seen else None
    if subject.asks:
        ages = [a for a in map(_ask_age, subject.asks) if a is not None]
        return Waiter(entry, subject.asks, "", "", format_duration(max(ages)) if ages else None)
    source = subject.owner or {}
    detail = _trimmed(source.get("state_detail")) or "Needs-input state reported"
    note = _UNCONFIRMED if source.get("wait_unconfirmed") else ""
    return Waiter(entry, [], detail, note, _since(generated, source.get("blocked_since")))


def _coverage(payload: Mapping[str, Any], seen: list[_Seen]) -> tuple[str, list[str]]:
    """The gap in what can be known, in the board's words: from the rows, never authored."""
    total = len(seen)
    reporting = sum(1 for s in seen if s.block_known)
    ended = sum(1 for s in seen if s.ended)
    noun = "session reports" if total == 1 else "sessions report"
    ends = (
        "ends unobservable"
        if payload.get("ends_observable") is False
        else f"ends observed on {ended} {'session' if ended == 1 else 'sessions'}"
    )
    gates = f"{reporting} of {total} {noun} block state · {total - reporting} unknown · {ends}"
    unreported = []
    for row in _records(payload.get("harnesses")):
        if not row.get("error") and row.get("reports_needs_input") is True:
            continue
        label = _trimmed(row.get("label")) or _text(row.get("key") or "Harness not published")
        reason = (
            "Harness source could not be read"
            if row.get("error")
            else "Harness does not report blocks"
        )
        unreported.append(f"{label}: {reason}")
    return gates, unreported


def board(payload: Mapping[str, Any], *, exclude: str | None = None) -> Board:
    """Everything either command prints, derived from one payload."""
    data = payload if isinstance(payload, dict) else {}
    sources = _records(data.get("sessions"))
    harnesses = _records(data.get("harnesses"))
    by_harness = {_identity(row.get("key")): row for row in harnesses}
    labels = {
        key: _text(row.get("label") or key)
        for row in harnesses
        if (key := _text(row.get("key") or ""))
    }
    generated = _num(data.get("generated"))
    annotate = data.get("annotate") is True
    asks = _records(data.get("asks"))
    held: dict[tuple[str, str], list[Row]] = {}
    if data.get("ask") is True:
        for ask in asks:
            owner = _owner(sources, ask) if _trimmed(ask.get("question")) else None
            if owner is not None:
                held.setdefault(_key(owner), []).append(ask)
    seen = [
        _observe(
            source,
            held.get(_key(source), []),
            by_harness.get(_identity(source.get("harness"))),
            labels,
            generated=generated,
            annotate=annotate,
            unreadable=bool(data.get("annotate_unreadable")),
        )
        for source in sources
    ]
    active, history = _groups(seen, _lane_order(sources), annotate=annotate)
    order: dict[str, int] = {}
    for row in harnesses:
        key = _text(row.get("key") or "")
        if key and key not in order:
            order[key] = len(order)
    waiting = _waiters(
        _subjects(sources, asks),
        {_key(s.source): s for s in reversed(seen)},
        generated=generated,
        exclude=exclude,
        order=order,
    )
    gates, unreported = _coverage(data, seen)
    return Board(active, history, waiting, gates, unreported, annotate)


def _enc(part: str) -> str:
    # `encodeURIComponent` leaves these unescaped, and the page's route grammar is built on it.
    return quote(part, safe="-_.!~*'()")


def _url(port: int, entry: Entry | None) -> str:
    base = f"http://127.0.0.1:{port}/#n="
    if entry is None:
        return f"{base}attention"
    route = ":".join(_enc(part) for part in (entry.project, entry.harness, entry.sid))
    return f"{base}session:{route}&from=attention"


def _entry_lines(entry: Entry) -> list[str]:
    who = (entry.state, entry.harness_label, entry.project)
    lines = ["  ".join(printable(part) for part in who).rstrip()]
    detail = [f"  {printable(entry.title)}"]
    if entry.goal:
        detail.append(f"  {entry.goal_label}: {_cut(entry.goal)}")
    now = printable(entry.now)
    if now or entry.ended:
        detail.append("  Now: " + " · ".join(part for part in (now, entry.ended) if part))
    if entry.block_note and entry.state == "Waiting on you":
        detail.append(f"  Waiting for: {printable(entry.block_note)}")
    if entry.outcome is not None:
        # The board draws the git text beside the sentence. Here it is added only where it says
        # more than the sentence already does, which is the count of changed entries.
        count = entry.git if entry.git and entry.git.endswith(" changed entries") else None
        detail.append(f"  {entry.outcome}" + (f" · {count}" if count else ""))
    if entry.drift is not None:
        detail.append(f"  Drift · {entry.drift}")
    if entry.command:
        detail.append(f"  Resume: {printable(entry.command)}")
    return [*lines, *detail, ""]


def render_sessions(payload: Mapping[str, Any]) -> list[str]:
    """`--sessions`: active sessions first, then recent ones under their own heading."""
    got = board(payload)
    lines: list[str] = []
    for heading, entries, empty in (
        ("Active now", got.active, _ACTIVE_EMPTY),
        ("Recent history", got.history, _HISTORY_EMPTY),
    ):
        lines.append(heading)
        for entry in entries:
            lines.extend(_entry_lines(entry))
        if not entries:
            lines.extend([f"  {empty}", ""])
    return lines[:-1] if lines and not lines[-1] else lines


def _waiter_lines(waiter: Waiter, port: int) -> list[str]:
    entry = waiter.entry
    if entry is not None:
        who = (entry.harness_label, entry.project, entry.title)
        head = "  ".join(printable(part) for part in who)
    else:
        ask = waiter.asks[0]
        head = (
            f"{printable(ask.get('harness') or 'Harness not published')}  "
            f"{printable(ask.get('project'))}  (no session identified)"
        )
    lines = [head.replace("  ", "  ").rstrip()]
    for ask in waiter.asks:
        lines.append(f"  {printable(ask.get('question'))}")
        options = ask.get("options")
        count = len(options) if isinstance(options, list) else 0
        if count:
            lines.append(f"  {count} published options")
    if waiter.reason:
        lines.append(f"  {printable(waiter.reason)}")
    if waiter.note:
        lines.append(f"  {waiter.note}")
    lines.append(f"  Waiting {waiter.age}" if waiter.age else "  Wait duration not published")
    if waiter.asks:
        lines.append(f"  Answer on the board: {_url(port, entry)}")
    if entry is not None and entry.command:
        lines.append(f"  Resume: {printable(entry.command)}")
    return [*lines, ""]


def render_waiting(
    payload: Mapping[str, Any], *, port: int, exclude: str | None, nothing: str
) -> list[str]:
    """`--sessions waiting`: what waits on the reader, then what the board cannot know of waits."""
    got = board(payload, exclude=exclude)
    lines: list[str] = []
    if got.waiting:
        lines.append("Waiting on you")
        for waiter in got.waiting:
            lines.extend(_waiter_lines(waiter, port))
    else:
        lines.extend([nothing, ""])
    lines.append(got.coverage)
    lines.extend(got.unreported)
    return lines
