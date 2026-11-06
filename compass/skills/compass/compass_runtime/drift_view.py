"""The Drift card's shape, derived the way the session page derives it (DRC-5102).

Several rules that decide what the card shows are applied only in the page: an unsettled later
direction demotes a departure to "can't tell", a result outside the shape contract is refused, and
an earlier departure stays in view beside a later row that does not answer it. A terminal that
printed only the server's published fields would show a departure the page holds back. This module
is the terminal's port of those rules, held to the page by `tests/test_drift_view.py` against
expected values the page wrote (`frontend/src/drift/terminalParity.test.ts`). It is not a second
opinion: when the page's rules change, the page's expected values change first and this follows.

It operates on the published JSON the page itself receives (the session row as `/api/data` publishes
it, the payload bits the page reads, and the focused context's body), and each function is named for
the page function it ports, so a reviewer can lay the two side by side. The page is taken as freshly
loaded, by the owner's ruling of 2026-11-06: no unsaved typing, the focused context's entries beside
the session record's newest page (which the page loads on opening a session, and which can hold a
message the context's bounded window does not) and no Show-more pages after it. It emits closed
tokens, ids, numbers and the reader's own words, never a sentence of the page's; the terminal words
its own output.

`derive` is the whole answer, including the level and the stale note, and `http_api` publishes it on
the focused context as `sources.work.drift_views`.

The `shape_view` answer is the page's `readingShape` and `priorDepartures` with the model's draft
and numbering around them. The rules it keeps, by the shape contract
([DEC-17](docs/design-reading-a-session.md#dec-17-the-shape-contract)): a result outside the set, a
departure citing nothing the page holds and an outcome verdict on an output limit are demoted to
"not verifiable", which the ruling names as the safe direction. The later-direction demotion is
[DEC-16](docs/design-reading-a-session.md#what-is-detected-and-what-is-not): the page's open set is
the detected superset, and any one unsettled direction demotes.
"""

from __future__ import annotations

import dataclasses
import functools
import math
from typing import Any, TypeGuard

from . import ci_read, levels, reading, records

# The fields a row publishes under `annotation_`, in the order the page reads them
# (`ANNOTATION_FIELDS` in `frontend/src/intent/annotation.ts`). A field missing here is one the page
# would notice arriving and this would not, which the generated parity cases are there to catch.
_ANNOTATION_FIELDS = (
    "goal",
    "goal_why",
    "lines_why",
    *(
        name
        for k in range(1, reading.MAX_OUTCOME_LINES + 1)
        for name in (f"line_{k}", f"line_{k}_source", f"line_{k}_source_id")
    ),
    "revision",
    "revision_count",
    "at",
    "goal_source",
    "goal_source_at",
    "goal_saved_at",
    "window_start",
    "binding_why",
    "settled_at",
    "settled_through",
    "settled_revision",
    "assessment",
    "reading_count",
    "reading_withheld",
    "reading_withheld_at",
    "reading_refused",
    "not_accurate",
    "prior_departures",
    "discarded_at",
    "discarded_why",
)

# The page's own reasons beside the producer's stored tokens. A page rule that lands on a producer
# token uses that token; the two the producer has no name for are spelt here.
WHY_MALFORMED = "malformed"
WHY_BASELINE_OPEN = "baseline-open"
# The producer's `unreadable` is the page's `malformed` sentence, so a stored one reads as that.
_STORED_AS_PAGE = {reading.WHY_UNREADABLE: WHY_MALFORMED}

LIMIT_ROUTE = "route"
LIMIT_NOT_ASKED = "not-asked"

_CLAIMS = reading.CONSTRAINT_CLAIMS
_UNIX_MAX = 253402300799
_OUTCOME_LINES_MAX = reading.MAX_OUTCOME_LINES
_MAX_NUMBER_SAFE = 2**53 - 1

Json = Any

_RESULTS = (
    reading.RESULT_DEPARTURE,
    reading.RESULT_CONSISTENT,
    reading.RESULT_UNVERIFIABLE,
    reading.RESULT_UNSUPPORTED,
    reading.RESULT_NOT_REACHED,
    reading.RESULT_GOAL_UNCLEAR,
)
_STORED_WHY = frozenset(token for token in reading.WHY_TOKENS if token)


# --- JavaScript's reading of a value, which the page's rules are written in -----------------------


def _truthy(value: Json) -> bool:
    """`Boolean(value)`."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0 and not (isinstance(value, float) and math.isnan(value))
    if isinstance(value, str):
        return value != ""
    return True


def _or(value: Json, default: Json) -> Json:
    """`value || default`."""
    return value if _truthy(value) else default


def _str(value: Json) -> str:
    """`String(value)`."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e21:
            return str(int(value))
        return repr(value)
    if isinstance(value, (list, dict)):
        return "[object Object]" if isinstance(value, dict) else ",".join(_str(v) for v in value)
    return str(value)


def _text(value: Json) -> str:
    """`String(value || '')`."""
    return _str(_or(value, ""))


def _number(value: Json) -> float | None:
    """`nextNumber`: a finite number, and nothing that merely coerces to one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def _coerce(value: Json) -> float:
    """`Number(value)`, for the one place the page sorts by a coerced time."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip()) if value.strip() else 0.0
        except ValueError:
            return math.nan
    return math.nan


def _get(row: Json, key: str) -> Json:
    """`row?.[key]` over a published value: a record has fields and nothing else does."""
    return row.get(key) if isinstance(row, dict) else None


def _is_record(value: Json) -> TypeGuard[dict[str, Json]]:
    return isinstance(value, dict)


def _strip(value: str) -> str:
    return value.strip()


# --- entries: what the page holds of the session's observed record --------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    """A `WorkEntry`: the fields of a published fact the shape rules read."""

    id: str
    type: str
    by: str
    at: Json
    result_at: Json
    subject: str
    copied: bool
    work: bool
    result: str
    earlier_failed: bool
    before_last_change: bool
    changed_after: bool
    read_incomplete: bool
    cannot_fail: bool
    ordinal: int | None
    ordinal_sub: int | None
    source: str
    ci_counts: bool = False
    compass_turn: bool = False


def _position(value: Json) -> int | None:
    """A published position: a whole number, 0 or more, or nothing."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value) if value >= 0 else None


def _fact_session_key(fact: Json) -> str:
    source = _get(fact, "source_session")
    source = source if _is_record(source) else {}
    harness = _text(source.get("harness"))
    sid = _text(source.get("sid"))
    return f"{harness}:{sid}" if harness and sid else ""


def _session_key(row: Json) -> str:
    """`compatSessKey`."""
    sid = _str(_or(_get(row, "sid"), _or(_get(row, "session"), "")))
    return f"{_text(_get(row, 'harness'))}:{sid}"


def _order(left: dict[str, Json], right: dict[str, Json]) -> int:
    """Time, then fact id, so two checks with one call time number the same in any payload order."""
    by_time = _coerce(_or(left.get("at"), 0)) - _coerce(_or(right.get("at"), 0))
    if by_time and not math.isnan(by_time):
        return -1 if by_time < 0 else 1
    a, b = _text(left.get("fact_id")), _text(right.get("fact_id"))
    return -1 if a < b else 1 if a > b else 0


def _work_on(harness: Json, kind: Json) -> bool:
    types = reading.WORK_EVIDENCE_BY_HARNESS.get(_text(harness))
    return types is not None and _text(kind) in types


def _evidence_source(fact: dict[str, Json]) -> str:
    evidence = fact.get("evidence")
    evidence = evidence if _is_record(evidence) else {}
    parts = (
        _strip(_str("" if value is None else value))
        for value in (evidence.get("source"), evidence.get("confidence"))
    )
    return " · ".join(part for part in parts if part)


def merged_facts(semantic: Json, record: list[dict[str, Json]] | None) -> Json:
    """`workSource`'s merge of the focused context's facts with the session record's newest page.

    The context carries a bounded window of the session's facts, so a message the reading cites can
    sit outside it and be found only in the record page the page loads when the session opens. The
    record wins a conflict, but a page read while the server's message index was still building
    carries no number, and the context's fixed one is not replaced by none. With no record the
    context's own facts stand, as the page reads them before the record lands.
    """
    if record is None:
        return semantic
    facts = semantic.get("facts") if _is_record(semantic) else None
    merged: dict[str, Json] = {
        _text(fact.get("fact_id")): fact
        for fact in (facts if isinstance(facts, list) else [])
        if _is_record(fact)
    }
    for fact in record:
        held = merged.get(_text(fact.get("fact_id")))
        kept = held.get("ordinal") if held is not None else None
        merged[_text(fact.get("fact_id"))] = (
            {**fact, "ordinal": kept}
            if fact.get("ordinal") is None
            and isinstance(kept, (int, float))
            and not isinstance(kept, bool)
            else fact
        )
    return {"facts": list(merged.values())}


def work_entries(session: dict[str, Json], semantic: Json) -> list[Entry]:
    """`workEntries`: the session's own facts, in the order they happened."""
    key = _session_key(session)
    facts = semantic.get("facts") if _is_record(semantic) else None
    facts = facts if isinstance(facts, list) else []
    mine = [fact for fact in facts if _is_record(fact) and _fact_session_key(fact) == key]
    mine.sort(key=functools.cmp_to_key(_order))
    return [
        Entry(
            id=_text(fact.get("fact_id")),
            type=_text(fact.get("type")),
            by=_text(fact.get("by")),
            at=fact.get("at"),
            result_at=fact.get("result_at"),
            subject=_text(fact.get("subject")),
            copied=fact.get("copied") is True,
            work=_work_on(session.get("harness"), fact.get("type")),
            result=_text(fact.get("result")),
            earlier_failed=fact.get("earlier_failed") is True,
            before_last_change=fact.get("before_last_change") is True,
            changed_after=fact.get("changed_after") is True,
            read_incomplete=fact.get("read_incomplete") is True,
            cannot_fail=fact.get("cannot_fail") is True,
            ordinal=_position(fact.get("ordinal")),
            ordinal_sub=_position(fact.get("ordinal_sub")),
            source=_evidence_source(fact),
            compass_turn=fact.get("compass_turn") is True,
        )
        for fact in mine
    ]


def _work_block(context: Json) -> dict[str, Json]:
    sources = _get(context, "sources")
    work = _get(sources, "work")
    return work if _is_record(work) else {}


def source_state(entries: list[Entry], context: Json, session: dict[str, Json]) -> str:
    """`workSource`'s state for a focused context that loaded: read, empty, or a scan that left it
    out."""
    if entries:
        return "read"
    omitted = _work_block(context).get("omitted")
    key = _session_key(session)
    if isinstance(omitted, list) and any(
        _truthy(row) and _session_key(row) == key for row in omitted
    ):
        return "partial"
    return "empty"


# --- the annotation and the draft -----------------------------------------------------------------


def annotation_of(session: dict[str, Json]) -> dict[str, Json] | None:
    """`annotationOf`: null only for a row that published none of the annotation's fields."""
    known = any(
        (value := session.get(f"annotation_{name}")) is not None
        and value != ""
        and not (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0)
        for name in _ANNOTATION_FIELDS
    )
    if not known:
        return None
    return {name: session.get(f"annotation_{name}") for name in _ANNOTATION_FIELDS}


def annotate_on(payload: Json) -> bool:
    return _is_record(payload) and payload.get("annotate") is True


def _outcome_lines(annotation: Json) -> list[tuple[int, str]]:
    """`annotationLines`: the typed lines in order, a blank slot being no line."""
    lines = []
    for k in range(1, _OUTCOME_LINES_MAX + 1):
        text = _text(_get(annotation, f"line_{k}"))
        if _strip(text):
            lines.append((k, text))
    return lines


def _prompt_copied(session: Json, field: str) -> bool:
    entries = _get(session, "copied_prompts")
    entries = entries if isinstance(entries, list) else []
    return any(
        _is_record(entry)
        and isinstance(entry.get("quoted_as"), list)
        and field in entry["quoted_as"]
        for entry in entries
    )


def _session_instruction(session: Json, label: str) -> dict[str, Json] | None:
    instruction = _get(session, "instruction")
    if not _is_record(instruction) or _prompt_copied(session, "instruction"):
        return None
    if _text(instruction.get("label")) != label:
        return None
    text = instruction.get("text")
    return instruction if _strip(_str("" if text is None else text)) else None


def _prompt_candidate(session: dict[str, Json], source: str) -> dict[str, Json] | None:
    harness = _text(session.get("harness"))
    if harness not in ("claude", "codex"):
        return None
    text = ""
    at: float | None = None
    if source == "first-prompt":
        if _prompt_copied(session, "first_prompt"):
            return None
        text = _text(session.get("first_prompt"))
        at = _number(session.get("first_prompt_at"))
    elif harness == "claude":
        asked = _session_instruction(session, "asked")
        if asked:
            text = _text(asked.get("text"))
            at = _number(asked.get("at"))
    elif session.get("prompt_states_work") is True:
        text = _text(session.get("title"))
        at = _number(session.get("prompt_at"))
    if not text:
        return None
    return {"text": text, "at": at if at is not None and at > 0 else None}


def _session_goal(session: dict[str, Json]) -> dict[str, Json] | None:
    if _text(session.get("harness")) not in records.SESSION_GOAL_HARNESSES:
        return None
    stated = session.get("session_goal")
    if not _is_record(stated):
        return None
    cut = stated.get("cut") is True and isinstance(stated.get("offered"), str)
    words = stated.get("offered") if cut else stated.get("text")
    text = _strip(words) if isinstance(words, str) else ""
    at = _number(stated.get("at"))
    return {"text": text, "at": at} if text and at is not None and at > 0 else None


def _opened_with_control(session: dict[str, Json]) -> bool:
    return (
        _text(session.get("harness")) in ("claude", "codex")
        and session.get("first_prompt_control") is True
    )


def intent_draft(  # noqa: PLR0911 - one early return per way a goal-less session drafts nothing
    payload: dict[str, Json], session: dict[str, Json], annotation: dict[str, Json] | None
) -> dict[str, Json] | None:
    """`intentDraft` with nothing held: the draft a goal-less session arrives with, or null."""
    if not annotate_on(payload) or _text(payload.get("annotate_unreadable")):
        return None
    if _is_record(annotation) and _number(annotation.get("discarded_at")) is not None:
        return None
    saved = annotation.get("goal") if annotation is not None else session.get("annotation_goal")
    if _strip(_text(saved)):
        return None
    stated = _session_goal(session)
    if stated:
        return stated
    if _opened_with_control(session):
        return None
    for source in ("first-prompt", "latest-prompt"):
        candidate = _prompt_candidate(session, source)
        if candidate and candidate["at"] is not None:
            return candidate
    return None


# --- later directions -----------------------------------------------------------------------------


def person_authored(entry: Entry) -> bool:
    """A message the server recognised as a correction copied from Compass is Compass's words."""
    if entry.type == "user_message":
        return not entry.copied
    return entry.type == "gate_decision" and entry.by.startswith("person:")


def baseline_at(
    annotation: dict[str, Json] | None,
    session: dict[str, Json] | None,
    draft: dict[str, Json] | None,
) -> float | None:
    """`baselineAt`: where "later" starts, the same floor `annotations.direction_floor` uses."""
    if annotation is not None and _get(annotation, "goal_source") in records.PROMPT_SOURCES:
        return _number(annotation.get("goal_source_at"))
    if _strip(_text(_get(annotation, "goal"))):
        saved = _number(_get(annotation, "goal_saved_at"))
        return saved if saved is not None else _number(_get(annotation, "at"))
    if session is None:
        return _number(_get(annotation, "at"))
    return draft["at"] if draft else None


def later_directions(
    annotation: dict[str, Json] | None,
    entries: list[Entry],
    session: dict[str, Json] | None,
    draft: dict[str, Json] | None,
) -> list[Entry]:
    typed_at = baseline_at(annotation, session, draft)
    if typed_at is None:
        return []
    return [
        entry
        for entry in entries
        if (at := _number(entry.at)) is not None and at > typed_at and person_authored(entry)
    ]


def conflict_candidates(
    annotation: dict[str, Json] | None,
    entries: list[Entry],
    session: dict[str, Json] | None,
    draft: dict[str, Json] | None,
) -> list[Entry]:
    """The directions still open: later than the baseline and not settled through."""
    settled = _number(_get(annotation, "settled_through"))
    return [
        entry
        for entry in later_directions(annotation, entries, session, draft)
        if settled is None or (_number(entry.at) or 0) > settled
    ]


# --- numbering ------------------------------------------------------------------------------------


def _entry_label(entry: Entry) -> str | None:
    if entry.ordinal is None:
        return None
    return (
        str(entry.ordinal) if entry.ordinal_sub is None else f"{entry.ordinal}.{entry.ordinal_sub}"
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Numbering:
    """`entryNumbering`, reduced to what a terminal reads: each entry's number by id."""

    labels: dict[str, str]
    counted: int
    earlier: int


def entry_numbering(
    session: dict[str, Json], entries: list[Entry], payload: dict[str, Json]
) -> Numbering:
    """The numbers the activity list and a reading's citations share.

    Where the session's own context published fixed numbers each entry is labelled with its own;
    everywhere else it is the entry's place among those held, counted from the oldest. An entry from
    before the intent's window keeps its fixed number as a label and is never counted.
    """
    opened = None
    if payload.get("annotate") is True:
        start = _number(session.get("annotation_window_start"))
        opened = start if start is not None and start > 0 else None
    ordinals = any(entry.ordinal is not None for entry in entries)
    numbered: list[tuple[Entry, str]] = []
    earlier: list[Entry] = []
    for entry in entries:
        at = _number(entry.at)
        if at is None or at <= 0:
            continue
        if opened is not None and at < opened:
            earlier.append(entry)
        elif not ordinals:
            numbered.append((entry, str(len(numbered) + 1)))
        elif (label := _entry_label(entry)) is not None:
            numbered.append((entry, label))
    labels = {entry.id: label for entry, label in numbered}
    for entry in earlier:
        label = _entry_label(entry) if ordinals else None
        if label is not None:
            labels[entry.id] = label
    return Numbering(labels=labels, counted=len({e.id for e, _ in numbered}), earlier=len(earlier))


# --- the reading's limits, requests and shape -----------------------------------------------------


def output_limit(payload: dict[str, Json], harness: str) -> bool:
    """`outputLimit`: whether the reading's route withholds a verdict on an expected output.

    On Claude Code the limit is lifted wherever a reading can be made, because the agent's own
    messages go with the words. Codex's agent messages are not sent, so only a check can carry a
    line's verdict, and only where a reading can carry the checks.
    """
    if harness == "pi":
        return False
    routes = payload.get("reading_routes")
    route = routes.get(harness) if _is_record(routes) else None
    route = route if _is_record(route) else None
    if harness == "codex":
        return not (route and _truthy(route.get("provider")) and _truthy(route.get("destination")))
    if harness != "claude":
        return True
    return not (route and _truthy(route.get("provider")))


def line_request_floors(
    session: dict[str, Json],
    annotation: dict[str, Json] | None,
    entries: list[Entry],
    context: Json,
) -> dict[str, float]:
    """`lineRequestFloors`: the page joins the server's private source binding to the current
    revision."""
    requests = _work_block(context).get("line_requests")
    rows = [
        row
        for row in (requests if isinstance(requests, list) else [])
        if _is_record(row)
        and row.get("harness") == session.get("harness")
        and row.get("sid") == session.get("sid")
    ]
    bound = rows[0] if len(rows) == 1 else None
    if (
        bound is None
        or annotation is None
        or _number(bound.get("revision")) != _number(annotation.get("revision"))
    ):
        return {}
    floors: dict[str, float] = {}
    lines = bound.get("lines")
    lines = lines if _is_record(lines) else {}
    for i in range(1, _OUTCOME_LINES_MAX + 1):
        key = f"line_{i}"
        request = lines.get(key)
        request = request if _is_record(request) else None
        at = _number(_get(request, "at"))
        source_id = _text(_get(request, "source_id"))
        if (
            not (at is not None and at > 0)
            or at > _UNIX_MAX
            or not source_id
            or annotation.get(f"{key}_source") != "entry"
            or annotation.get(f"{key}_source_id") != source_id
        ):
            continue
        parents = [entry for entry in entries if entry.id == source_id]
        if (
            len(parents) == 1
            and parents[0].type == "user_message"
            and not parents[0].copied
            and _number(parents[0].at) == at
        ):
            floors[key] = at
    return floors


def _evidence_at(entry: Entry) -> float | None:
    """`reading.evidence_at`: a check's result time where one was recorded, its call time
    otherwise."""
    result_at = _number(entry.result_at)
    return result_at if result_at is not None and result_at > 0 else _number(entry.at)


def _before_window(entry: Entry, window_start: float | None) -> bool:
    at = _evidence_at(entry) or 0
    start = 0 if window_start is None else window_start
    return at < start or (start > 0 and at <= 0)


def _author(entry: Entry) -> str:
    """Who wrote an evidence entry: a closed set on the person side, Compass's paraphrase a third
    author."""
    if entry.type == "user_message" and not entry.copied:
        return "person"
    if entry.type == "gate_decision" and entry.by.startswith("person:"):
        return "person"
    if entry.type == "user_message" and entry.copied:
        return "derived"
    return "derived" if entry.type == "observer_snapshot" else "agent"


def _agent_message(entry: Entry) -> bool:
    return entry.type == "agent_message"


def _demonstrates_work(entry: Entry) -> bool:
    return entry.work


_RESULT_SUBJECTS = frozenset({"check", "command", "ci_command"})
_PI_CHECK_SOURCE = "Pi bash tool call"


def check_supports(  # noqa: PLR0911 - one return per kind of entry, as the page's has
    entry: Entry,
    result: str,
    window_start: float | None,
    *,
    recorded_write: bool = False,
    recorded_command: bool = False,
) -> bool:
    """`checkSupports`: what a cited entry may carry, by what it is.

    A check carries a verdict only as a run whose result arrived in the window, failed for a
    departure, passed, not before the last change and with no changing command after it for a
    consistent. A written path shows a write and no result, so it carries neither, unless the
    producer stored the row as `recorded-write`. A command that exited 0 is the same under
    `recorded-command`.
    """
    if entry.type == "ci_check":
        at = _evidence_at(entry)
        return (
            entry.ci_counts
            and at is not None
            and at > 0
            and not _before_window(entry, window_start)
            and (
                (result == reading.RESULT_CONSISTENT and entry.result == "passed")
                or (result == reading.RESULT_DEPARTURE and entry.result == "failed")
            )
        )
    report = entry.type == "tool_report"
    if entry.subject in ("command", "ci_command") and (not report or entry.cannot_fail):
        return False
    if not report and entry.subject != "check":
        return not (entry.type == "result" and entry.source.startswith(_PI_CHECK_SOURCE))
    if entry.subject in ("pr", "skill"):
        at = _evidence_at(entry)
        return (
            result == reading.RESULT_CONSISTENT
            and at is not None
            and at > 0
            and not _before_window(entry, window_start)
        )
    if entry.subject not in _RESULT_SUBJECTS:
        at = _evidence_at(entry)
        return (
            recorded_write
            and result == reading.RESULT_DEPARTURE
            and entry.subject == "write"
            and at is not None
            and at > 0
            and not _before_window(entry, window_start)
        )
    at = _evidence_at(entry)
    if at is None or at <= 0 or (window_start is not None and at < window_start):
        return False
    if result == reading.RESULT_DEPARTURE:
        return entry.result == "failed" or (
            recorded_command and report and entry.subject == "command" and entry.result == "passed"
        )
    if result == reading.RESULT_CONSISTENT:
        return (
            entry.result == "passed"
            and not entry.before_last_change
            and not entry.changed_after
            and not entry.read_incomplete
        )
    return False


def _cited(raw: Json, entries: list[Entry]) -> list[Entry]:
    """Rule 3: a citation resolves only to an entry the page holds that has a type and a source."""
    by_id = {entry.id: entry for entry in entries}
    cites = _get(raw, "cites")
    found = (by_id.get(_str(cite)) for cite in (cites if isinstance(cites, list) else []))
    return [
        entry
        for entry in found
        if entry is not None and _strip(entry.type) and _strip(entry.source)
    ]


def _count_unloaded(raw: Json, entries: list[Entry]) -> int:
    held = {entry.id for entry in entries}
    cites = _get(raw, "cites")
    return len({_str(cite) for cite in (cites if isinstance(cites, list) else [])} - held - {""})


def _outcome_line(key: str) -> bool:
    if key == reading.CONSTRAINT_OUTPUT:
        return True
    if not key.startswith("line_") or not key[5:].isascii() or not key[5:].isdigit():
        return False
    digits = key[5:]
    return digits[0] != "0" and int(digits) <= _OUTCOME_LINES_MAX


@dataclasses.dataclass(frozen=True, slots=True)
class Criterion:
    """A row of the reading as the page draws it: the result after every rule, and what it rests
    on."""

    key: str
    clause: str
    clause_known: bool
    result: str
    why: str
    rests_on: str
    limit: str
    detail: str
    cited_ids: tuple[str, ...]
    unloaded: int
    has_record_entry: bool
    partial: bool = False


def _keys_of(raw: Json) -> list[str]:
    """`Object.keys(raw)` for a stored row: an array's keys are its indexes."""
    if isinstance(raw, dict):
        return list(raw)
    if isinstance(raw, list):
        return [str(i) for i in range(len(raw))]
    return []


def criterion(  # noqa: C901, PLR0912, PLR0913, PLR0915 - one arm per rule, as the page's `criterion` has
    key: str,
    clause: str,
    raw: Json,
    entries: list[Entry],
    *,
    limit: bool,
    unsettled: bool,
    window_start: float | None = None,
    scope: str = "",
    request_at: float | None = None,
) -> Criterion:
    """`criterion`: one stored row held to the shape contract, by rule number.

    The result is demoted to "not verifiable" by the first rule it fails, which the ruling names as
    the safe direction. A departure is demoted too under an output limit, which is stricter than the
    letter of rule 5 and the direction the ruling calls safe.
    """
    cited = [
        entry
        for entry in _cited(raw, entries)
        if not _before_window(entry, window_start)
        and (request_at is None or (_number(entry.at) or 0) > request_at)
    ]
    is_object = isinstance(raw, (dict, list))
    declared = _text(_get(raw, "result")) if is_object else ""
    stored = _text(_get(raw, "why")) if is_object else ""
    limit_text = LIMIT_ROUTE if limit else ""
    claims = key == _CLAIMS
    # `unsupported` is the claims row's alone; anywhere else it is a result outside the row's set.
    known = [
        name
        for name in _RESULTS
        if (name != reading.RESULT_NOT_REACHED if claims else name != reading.RESULT_UNSUPPORTED)
        and (name != reading.RESULT_GOAL_UNCLEAR or key == "goal")
    ]
    result = declared if declared in known else reading.RESULT_UNVERIFIABLE
    why = "" if result == declared else WHY_MALFORMED
    if result == reading.RESULT_NOT_REACHED and scope not in ("last-turn", "mid-flight"):
        result = reading.RESULT_UNVERIFIABLE
        why = WHY_MALFORMED
    refused = result == reading.RESULT_GOAL_UNCLEAR
    unverifiable = reading.RESULT_UNVERIFIABLE
    if result != unverifiable and not refused and not cited:
        result, why = unverifiable, reading.WHY_UNCITED
    if result != unverifiable and not refused and limit:
        result, why = unverifiable, ""
    if result != unverifiable and not refused and unsettled and not claims:
        result, why = unverifiable, WHY_BASELINE_OPEN
    if is_object and any(name not in reading.CRITERION_KEYS for name in _keys_of(raw)):
        result, why = unverifiable, WHY_MALFORMED
    if stored and stored not in _STORED_WHY:
        result, why = unverifiable, WHY_MALFORMED
    if result == reading.RESULT_GOAL_UNCLEAR:
        return Criterion(
            key=key,
            clause=clause,
            clause_known=bool(clause),
            result=result,
            why="",
            rests_on="",
            limit="",
            detail="",
            cited_ids=(),
            unloaded=0,
            has_record_entry=False,
        )
    dropped_check = False
    failed_cited = False
    if result != unverifiable:
        failed_cited = any(
            entry.subject in _RESULT_SUBJECTS
            and check_supports(entry, reading.RESULT_DEPARTURE, window_start)
            for entry in cited
        )
        incomplete_pass = result == reading.RESULT_CONSISTENT and any(
            entry.read_incomplete
            and check_supports(
                dataclasses.replace(entry, read_incomplete=False), result, window_start
            )
            for entry in cited
        )
        supporting = [
            entry
            for entry in cited
            if check_supports(
                entry,
                result,
                window_start,
                recorded_write=stored == reading.WHY_RECORDED_WRITE,
                recorded_command=stored == reading.WHY_RECORDED_COMMAND,
            )
        ]
        dropped_check = len(supporting) < len(cited)
        cited = supporting
        if not cited:
            result = unverifiable
            why = (
                reading.WHY_CHECK_READ_INCOMPLETE
                if incomplete_pass
                else reading.WHY_CHECK_DOES_NOT_SHOW_IT
            )
    claim_said = [entry for entry in cited if _agent_message(entry)] if claims else []
    claim_record = [entry for entry in cited if not _agent_message(entry)] if claims else []
    if claims and result != unverifiable:
        token = ""
        unsupported = result == reading.RESULT_UNSUPPORTED
        if not claim_said:
            token = reading.WHY_CLAIM_UNCITED
        elif not unsupported and not claim_record:
            token = (
                reading.WHY_CHECK_DOES_NOT_SHOW_IT if dropped_check else reading.WHY_CLAIM_UNCITED
            )
        elif not unsupported and all(_author(entry) == "derived" for entry in claim_record):
            token = reading.WHY_BOARD_QUOTING_ITSELF
        elif (
            result == reading.RESULT_CONSISTENT
            and not any(
                _demonstrates_work(entry) or entry.type == "tool_report" for entry in claim_record
            )
        ) or (
            result == reading.RESULT_DEPARTURE
            and not any(
                entry.subject == "check"
                or (_number(entry.at) or 0) >= min(_number(said.at) or 0 for said in claim_said)
                for entry in claim_record
            )
        ):
            token = reading.WHY_CLAIM_UNCITED
        if token:
            result, why = unverifiable, token
    shows = [entry for entry in cited if _demonstrates_work(entry)]
    authors = [_author(entry) for entry in cited]
    derived_only = bool(authors) and all(name == "derived" for name in authors)
    agent_said = any(_agent_message(entry) for entry in cited)
    if _outcome_line(key) and result != unverifiable and not shows and not agent_said:
        result = unverifiable
        why = reading.WHY_CHECK_DOES_NOT_SHOW_IT if dropped_check else reading.WHY_NO_WORK_SHOWN
    if result != unverifiable and derived_only:
        result, why = unverifiable, reading.WHY_BOARD_QUOTING_ITSELF
    if result == reading.RESULT_CONSISTENT and not any(
        _author(entry) == "agent" or _demonstrates_work(entry) for entry in cited
    ):
        result = unverifiable
        why = reading.WHY_CHECK_DOES_NOT_SHOW_IT if dropped_check else reading.WHY_UNCORROBORATED
    if result == reading.RESULT_CONSISTENT and failed_cited and not shows:
        result, why = unverifiable, reading.WHY_CHECK_DOES_NOT_SHOW_IT
    if (
        result == reading.RESULT_CONSISTENT
        and (_outcome_line(key) or claims)
        and not shows
        and any(
            entry.subject in _RESULT_SUBJECTS
            and check_supports(entry, reading.RESULT_DEPARTURE, window_start)
            for entry in entries
        )
    ):
        result = unverifiable
        why = (
            reading.WHY_FAILED_CHECK_UNREAD
            if stored == reading.WHY_FAILED_CHECK_UNREAD
            else reading.WHY_FAILED_CHECK_ON_RECORD
        )
    if result == unverifiable and not why and not limit_text and stored in _STORED_WHY:
        if stored == reading.WHY_NOT_ASKED:
            limit_text = LIMIT_NOT_ASKED
        else:
            why = _STORED_AS_PAGE.get(stored, stored)
    tool = None
    if result == reading.RESULT_CONSISTENT:
        tool = next((e for e in cited if e.type == "tool_report" or e.subject == "check"), None)
    accounts = (
        [entry for entry in cited if _author(entry) == "agent"]
        if result == reading.RESULT_CONSISTENT and tool is None
        else []
    )
    said = next((entry for entry in accounts if _agent_message(entry)), None) or (
        accounts[0] if accounts else None
    )
    if tool is not None:
        rests_on = "tool"
    elif said is not None and all(_agent_message(entry) for entry in accounts):
        rests_on = "message"
    elif said is not None:
        rests_on = "agent"
    else:
        rests_on = ""
    return Criterion(
        key=key,
        clause="" if claims else clause,
        clause_known=not claims and bool(clause),
        result=result,
        why=why,
        rests_on=rests_on,
        limit=limit_text,
        detail=(
            _text(_get(raw, "detail"))
            if result in (reading.RESULT_DEPARTURE, reading.RESULT_NOT_REACHED)
            else ""
        ),
        cited_ids=() if limit_text else tuple(entry.id for entry in cited),
        unloaded=_count_unloaded(raw, entries),
        has_record_entry=claims and result != unverifiable and bool(claim_record),
    )


def result_state(row: Criterion) -> str:  # noqa: PLR0911
    """`resultState`: the line's state, as the card draws it."""
    if row.key == _CLAIMS:
        if row.result == reading.RESULT_DEPARTURE:
            return "departs"
        if row.result == reading.RESULT_UNSUPPORTED:
            return "unshown"
        if row.result == reading.RESULT_CONSISTENT and row.has_record_entry:
            return "consistent"
        return "cant-tell"
    if row.result == reading.RESULT_DEPARTURE:
        return "departs"
    if row.result == reading.RESULT_NOT_REACHED:
        return "not-reached"
    if row.result == reading.RESULT_CONSISTENT and row.rests_on:
        return "consistent"
    return "cant-tell"


# --- the stored reading's closed parts ------------------------------------------------------------


def _safe_integer(value: Json) -> TypeGuard[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return (isinstance(value, int) or value.is_integer()) and abs(value) <= _MAX_NUMBER_SAFE


def _integer(value: Json) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isinstance(value, int) or (math.isfinite(value) and value.is_integer())


def _is_number(value: Json) -> bool:
    """`typeof value === 'number'` and finite."""
    return _number(value) is not None


_COVERAGE_COMMAND_KEYS = ("other_commands", "read_only_commands")


def reading_coverage(raw: Json) -> dict[str, Json] | None:  # noqa: PLR0911
    """`readingCoverage`: what the press read, or null for a record this build cannot read."""
    if not _is_record(raw) or any(key not in raw for key in reading.COVERAGE_KEYS):
        return None
    size = len(raw)
    with_counts = len(reading.COVERAGE_KEYS) + len(_COVERAGE_COMMAND_KEYS)
    floored = size == with_counts + 1 and raw.get(reading.COMMANDS_FLOOR_KEY) is True
    counted = size == with_counts or floored
    if size != len(reading.COVERAGE_KEYS) and not counted:
        return None
    if counted:
        other, read_only = (raw.get(key) for key in _COVERAGE_COMMAND_KEYS)
        if (
            not _safe_integer(other)
            or not _safe_integer(read_only)
            or read_only < 0
            or other < read_only
        ):
            return None
    truncated = raw["tail_truncated"]
    if truncated is not None and not isinstance(truncated, bool):
        return None
    start = raw["tail_start"]
    if start is not None and (
        isinstance(start, bool)
        or not isinstance(start, (int, float))
        or not math.isfinite(start)
        or start <= 0
        or start > _UNIX_MAX
    ):
        return None
    if any(not _safe_integer(raw[key]) or raw[key] < 0 for key in ("unlisted", "unread_checks")):
        return None
    return raw if raw["goal_source"] in reading.COVERAGE_GOAL_SOURCES else None


def reading_goal_verdict(raw: Json) -> dict[str, Json] | None:  # noqa: PLR0911  # noqa: PLR0911
    """`readingGoalVerdict`: the harness's goal verdict and Compass's test of it, or null."""
    if not _is_record(raw) or any(key not in raw for key in reading.GOAL_VERDICT_KEYS):
        return None
    extra = [key for key in raw if key not in reading.GOAL_VERDICT_KEYS]
    removal = [key for key in extra if key in reading.GOAL_VERDICT_REMOVAL_KEYS]
    quoted = [key for key in extra if key in reading.GOAL_VERDICT_QUOTED_KEYS]
    if len(removal) + len(quoted) != len(extra):
        return None
    if removal and (
        quoted
        or len(removal) != len(reading.GOAL_VERDICT_REMOVAL_KEYS)
        or raw["why"] not in reading.GOAL_VERDICT_REMOVAL_WHYS
        or not isinstance(raw["path"], str)
        or not raw["path"]
        or not _is_number(raw["changed_at"])
        or raw["changed_at"] <= 0
    ):
        return None
    if quoted and (
        raw["why"] != reading.GOAL_VERDICT_QUOTED
        or not _integer(raw["quoted"])
        or raw["quoted"] < 1
        or raw["quoted"] > reading.MAX_QUOTED_SPANS
    ):
        return None
    if raw["why"] == reading.GOAL_VERDICT_QUOTED and not quoted:
        return None
    cites = raw["cites"]
    if (
        not _is_number(raw["at"])
        or raw["at"] <= 0
        or raw["check"] not in reading.GOAL_VERDICT_CHECKS
        or raw["why"] not in reading.GOAL_VERDICT_WHYS
        or not isinstance(cites, list)
        or any(not isinstance(cite, str) for cite in cites)
    ):
        return None
    return raw


_CI_KEYS = (
    "read_at",
    "error",
    "source",
    "repository",
    "number",
    "head",
    "session_head",
    "head_matches",
    "merged_in",
    "required_only",
    "not_counted",
    "counts",
    "caution",
    "checks",
)
# Keys a stored record may lack: `not_counted` and `merged_in` arrived after the first records.
_CI_OPTIONAL_KEYS = ("not_counted", "merged_in")


def _ci_head(value: Json) -> bool:
    return isinstance(value, str) and (
        value == "" or (len(value) == 40 and all(c in "0123456789abcdef" for c in value))
    )


def reading_ci(raw: Json) -> dict[str, Json] | None:  # noqa: C901, PLR0911
    """`readingCi`: what the press read of the pull request's CI checks, or null.

    Every key is closed: tokens and counts, never a sentence of the CLI's, so a record rewritten to
    say something else is a reading this build cannot read.
    """
    if not _is_record(raw):
        return None
    if any(key not in _CI_KEYS for key in raw):
        return None
    if any(key not in raw and key not in _CI_OPTIONAL_KEYS for key in _CI_KEYS):
        return None
    counts, checks = raw.get("counts"), raw.get("checks")
    if not _is_number(raw.get("read_at")) or raw["read_at"] <= 0:
        return None
    if raw.get("error") != "" and raw.get("error") not in ci_read.ERRORS:
        return None
    if (
        raw.get("source") not in ci_read.SOURCES
        or not isinstance(raw.get("repository"), str)
        or not _integer(raw.get("number"))
        or not _ci_head(raw.get("head"))
        or not _ci_head(raw.get("session_head"))
        or not isinstance(raw.get("head_matches"), bool)
        or not isinstance(raw.get("required_only"), bool)
        or not isinstance(raw.get("caution"), bool)
    ):
        return None
    if "merged_in" in raw and (
        not isinstance(raw["merged_in"], bool)
        or (raw["merged_in"] is True and (raw["head_matches"] is True or not raw["session_head"]))
    ):
        return None
    if "not_counted" in raw and (
        not _integer(raw["not_counted"])
        or raw["not_counted"] < 0
        or (raw["not_counted"] > 0 and raw["required_only"] is not True)
    ):
        return None
    if (
        not _is_record(counts)
        or len(counts) != len(ci_read.BUCKETS)
        or any(not _integer(counts.get(bucket)) or counts[bucket] < 0 for bucket in ci_read.BUCKETS)
    ):
        return None
    if not isinstance(checks, list) or any(
        not _is_record(check)
        or not isinstance(check.get("name"), str)
        or check.get("bucket") not in ci_read.BUCKETS
        or not (check.get("completed_at") is None or _is_number(check.get("completed_at")))
        for check in checks
    ):
        return None
    return raw


_CI_RESULT = {
    "pass": "passed",
    "fail": "failed",
    "pending": "pending",
    "skipping": "skipped",
    "cancel": "cancelled",
}


def ci_entries(ci: dict[str, Json] | None) -> list[Entry]:
    """`ciEntries`: the entries a stored CI read stands for, as the producer numbered them in the
    prompt.

    They join the citations a reading is read against and never the activity list: what GitHub said
    at the press is no event of the session.
    """
    if not ci or ci["error"] or not ci["checks"]:
        return []
    counts = ci["counts"]
    whole = (
        counts.get("pass", 0) > 0
        and not counts.get("fail", 0)
        and not counts.get("pending", 0)
        and not counts.get("cancel", 0)
    )
    gitlab = "." in ci["repository"].split("/")[0]
    settles = ci["head_matches"] or ci.get("merged_in") is True
    source = f"{ci_read.SOURCE_TEXT_GITLAB if gitlab else ci_read.SOURCE_TEXT} · recorded"
    return [
        Entry(
            id=f"ci:{_str(ci['number'])}:{index}",
            type="ci_check",
            by="gitlab" if gitlab else "github",
            at=ci["read_at"],
            result_at=None,
            subject="ci",
            copied=False,
            work=True,
            result=_CI_RESULT.get(check["bucket"], ""),
            earlier_failed=False,
            before_last_change=False,
            changed_after=False,
            read_incomplete=False,
            cannot_fail=False,
            ordinal=None,
            ordinal_sub=None,
            source=source,
            ci_counts=bool(
                settles and ((check["bucket"] == "pass" and whole) or check["bucket"] == "fail")
            ),
        )
        for index, check in enumerate(ci["checks"])
    ]


# --- the reading's shape --------------------------------------------------------------------------


def _names_constraint(key: str) -> bool:
    return key in ("goal", _CLAIMS) or _outcome_line(key)


def _constraint_order(key: str) -> int:
    if key == "goal":
        return 0
    if key == reading.CONSTRAINT_OUTPUT:
        return 1
    if key == _CLAIMS:
        return _OUTCOME_LINES_MAX + 1
    return int(key[5:])


def reading_constraints(rows: Json, annotation: Json, *, current: bool) -> list[str]:
    """The constraints a reading's rows are drawn for, goal first and then each line in order.

    They are the ones the READING read, from its own criteria, and never today's lines: a line typed
    after the reading was never asked. `current` is a reading of the words shown now, where a line
    typed now is one it read, and one it returned no result for is drawn as missing.
    """
    rows = rows if _is_record(rows) else {}
    typed = [f"line_{k}" for k, _ in _outcome_lines(annotation)] if current else []
    keys = dict.fromkeys(
        [
            "goal",
            *(key for key in rows if _names_constraint(key)),
            *(
                key
                for key in typed
                if not (_truthy(rows.get(reading.CONSTRAINT_OUTPUT)) and key == "line_1")
            ),
        ]
    )
    ordered = sorted(keys, key=_constraint_order)
    return [
        key for key in ordered if _truthy(rows.get(key)) or _strip(_text(_get(annotation, key)))
    ]


def _reading_clause(key: str, row: Json, annotation: Json, *, historical: bool) -> str:
    """The words the reading was read against: carried by the producer, else today's while
    current."""
    carried = _strip(_text(_get(row, "clause")))
    if carried:
        return carried
    if historical:
        return ""
    return _strip(_text(_get(annotation, "line_1" if key == reading.CONSTRAINT_OUTPUT else key)))


@dataclasses.dataclass(frozen=True, slots=True)
class Shape:
    """`Shape`: the rows a reading draws, and the departures among them."""

    criteria: tuple[Criterion, ...]
    departures: tuple[Criterion, ...]
    malformed: str
    window_start: float | None
    revision_read: float | None = None
    scope: str = ""


def _window_partial(coverage: dict[str, Json] | None, window_start: float | None) -> bool:
    return bool(
        coverage
        and coverage["tail_truncated"] is True
        and coverage["tail_start"] is not None
        and window_start is not None
        and window_start > 0
        and coverage["tail_start"] > window_start
    )


def reading_shape(
    raw: Json,
    annotation: dict[str, Json] | None,
    entries: list[Entry],
    *,
    limit: bool,
    unsettled: bool,
    line_requests: dict[str, float],
) -> Shape:
    """`readingShape`: a stored reading held to the shape contract, row by row.

    Unknown keys are fatal and missing keys are not: a producer that omits a field renders a reading
    with less in it, which is legible, and one that emits a field this build does not know has
    diverged from the shape.
    """
    source = raw if _is_record(raw) else {}
    unknown = [name for name in source if name not in reading.ASSESSMENT_KEYS]
    coverage = reading_coverage(source.get("coverage"))
    if source.get("coverage") is not None and coverage is None:
        unknown.append("coverage")
    ci = reading_ci(source.get("ci"))
    if "goal_verdict" in source and reading_goal_verdict(source["goal_verdict"]) is None:
        unknown.append("goal_verdict")
    if "ci" in source and ci is None:
        unknown.append("ci")
    if unknown:
        return Shape(
            criteria=(), departures=(), malformed=", ".join(unknown[:4]), window_start=None
        )
    held = [*entries, *ci_entries(ci)] if ci else entries
    rows = source.get("criteria")
    rows = rows if _is_record(rows) else {}
    revision_read = _number(source.get("revision_read"))
    current = _number(_get(annotation, "revision"))
    historical = revision_read is not None and current is not None and revision_read != current
    explicit = _number(source.get("window_start"))
    window_start = (
        explicit
        if explicit is not None
        else _number(
            source.get("goal_source_at")
            if source.get("goal_source") in records.PROMPT_SOURCES
            else source.get("revision_read_at")
        )
    )
    read_at = _number(source.get("read_at"))
    if read_at is not None and read_at > 0 and unsettled:
        unsettled = any(
            (_number(entry.at) or 0) <= read_at
            for entry in conflict_candidates(annotation, entries, None, None)
        )
    keys = reading_constraints(
        rows,
        annotation,
        current=revision_read is not None and current is not None and not historical,
    )
    partial = _window_partial(coverage, window_start)
    criteria = []
    for key in keys:
        row = rows.get(key)
        floor = line_requests.get(key)
        asked = (
            not historical
            and revision_read == current
            and read_at is not None
            and read_at > 0
            and floor is not None
            and 0 < floor <= read_at
        )
        built = criterion(
            key,
            _reading_clause(key, row, annotation, historical=historical),
            row,
            held,
            limit=limit and (_outcome_line(key) or key == _CLAIMS),
            unsettled=unsettled,
            window_start=window_start,
            scope=_str("" if source.get("scope") is None else source["scope"]),
            request_at=floor if asked else None,
        )
        criteria.append(dataclasses.replace(built, partial=partial and key != _CLAIMS))
    return Shape(
        criteria=tuple(criteria),
        # The intent's departures: a contradicted claim is not one, so it is in no count, flag or
        # answer about the intent.
        departures=tuple(
            row for row in criteria if row.result == reading.RESULT_DEPARTURE and row.key != _CLAIMS
        ),
        malformed="",
        window_start=window_start,
        revision_read=revision_read,
        scope=_text(source.get("scope")),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Prior:
    """`PriorDeparture`: an earlier departure the store kept beside the reading that replaced it."""

    key: str
    read_at: float
    row: Criterion
    cites: tuple[str, ...]
    answer: str


def prior_departures(  # noqa: C901 - one continue per rule an earlier departure must pass
    stored: Json, shape: Shape | None, entries: list[Entry]
) -> list[Prior]:
    """`priorDepartures`: which earlier departures the page draws beside the standing reading.

    The store keeps every departure the next reading stopped finding; the page decides which to
    draw, because which entries a line rests on is resolved against the record here and not in the
    producer. A check, a written file or another departure answers the line on the record. A line
    the later reading rests on the agent's message, or cannot tell about or has not reached, answers
    nothing, so the earlier departure stays listed.
    """
    if shape is None or shape.malformed or not isinstance(stored, list):
        return []
    newest: dict[str, Prior] = {}
    for item in stored:
        if not _is_record(item) or not _is_record(item.get("criterion")):
            continue
        key = _str("" if item.get("key") is None else item["key"])
        read_at = _number(item.get("read_at"))
        if (key != "goal" and not _outcome_line(key)) or read_at is None or read_at <= 0:
            continue
        later = next((row for row in shape.criteria if row.key == key), None)
        if later is None or not later.clause_known:
            continue
        state = result_state(later)
        if later.result == reading.RESULT_CONSISTENT and later.rests_on == "message":
            answer = "said"
        elif state in ("cant-tell", "not-reached"):
            answer = state
        else:
            continue
        raw = item["criterion"]
        clause = _strip(_text(raw.get("clause")))
        if not clause or clause != _strip(later.clause):
            continue
        row = criterion(
            key,
            clause,
            raw,
            entries,
            limit=False,
            unsettled=False,
            window_start=shape.window_start,
        )
        # A departure none of whose cited entries the page holds is demoted by the shape, as a
        # reading's own is: a card has to reach at least one number.
        if row.result != reading.RESULT_DEPARTURE:
            continue
        cites = raw.get("cites")
        listed = (
            tuple(dict.fromkeys(c for c in (_str(cite) for cite in cites) if c))
            if isinstance(cites, list)
            else ()
        )
        held = newest.get(key)
        if held is None or read_at > held.read_at:
            newest[key] = Prior(key=key, read_at=read_at, row=row, cites=listed, answer=answer)
    # In the reading's own order: the goal, then each line.
    return [newest[row.key] for row in shape.criteria if row.key in newest]


# --- the view -------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _Parts:
    """What the level and the stale note read beside the shape."""

    annotate: bool
    annotation: dict[str, Json] | None
    entries: list[Entry]
    shape: Shape | None
    drafted: bool
    harness: str


def _read(
    session: dict[str, Json],
    payload: dict[str, Json],
    context: Json,
    record: list[dict[str, Json]] | None = None,
) -> tuple[dict[str, Json], _Parts]:
    """What the Drift card holds for a session on a fresh load, as tokens, numbers and the reader's
    words.

    `session` is the row as `/api/data` publishes it, `payload` is that response's own body (the
    page reads `annotate` and `reading_routes` from it) and `context` the focused project context's
    body. `record` is the session record's newest page, which the page loads on opening the session
    and merges with the context's facts; it is None where that page was not read. The page is taken
    as freshly loaded: no unsaved typing, no Show-more pages beyond that first one
    ([DEC-26](docs/design-reading-a-session.md#dec-26-four-drift-levels-and-a-live-estimate-after-every-turn)
    keeps the level off rows, so this is a view of the focused context only).
    """
    annotate = annotate_on(payload)
    annotation = annotation_of(session) if annotate else None
    entries = work_entries(session, merged_facts(_get(context, "semantic"), record))
    state = source_state(entries, context, session)
    numbering = entry_numbering(session, entries, payload)
    harness = _text(session.get("harness"))
    draft = intent_draft(payload, session, annotation)
    stored = _get(annotation, "assessment")
    limit = output_limit(payload, harness)
    # The same open set gates the question and the reading's demotion, so those two cannot disagree
    # about whether a baseline is settled.
    unsettled = annotate and bool(conflict_candidates(annotation, entries, session, draft))
    shape = (
        reading_shape(
            stored,
            annotation,
            entries,
            limit=limit,
            unsettled=unsettled,
            line_requests=line_request_floors(session, annotation, entries, context),
        )
        if _truthy(stored)
        else None
    )
    priors = (
        prior_departures(session.get("annotation_prior_departures"), shape, entries)
        if annotate
        else []
    )
    read = state in ("read", "empty")

    def numbers(ids: Any) -> list[str]:
        return [numbering.labels.get(entry_id, "") for entry_id in ids]

    view = {
        "harness": harness,
        "sid": _str(session.get("sid")),
        "annotate": annotate,
        "reading": shape is not None,
        "malformed": shape.malformed if shape else "",
        "unsettled": unsettled,
        # The messages the direction question lists: the open set that demotes, counted.
        "unsettled_count": len(conflict_candidates(annotation, entries, session, draft))
        if annotate
        else 0,
        "drafted": draft is not None,
        "limited": limit,
        "entry_count": numbering.counted + numbering.earlier if read else None,
        "window_count": numbering.counted if read and numbering.earlier else None,
        "lines": [
            {
                "key": row.key,
                "state": result_state(row),
                "result": row.result,
                "why": row.why,
                "rests_on": row.rests_on,
                "limit": row.limit,
                "clause": row.clause if row.clause_known else "",
                "detail": row.detail,
                "cites": list(row.cited_ids),
                "numbers": numbers(row.cited_ids),
                "unloaded": row.unloaded,
                "partial": row.partial,
            }
            for row in (shape.criteria if shape else ())
        ],
        "departures": [row.key for row in (shape.departures if shape else ())],
        "cited": sorted(
            {
                entry_id
                for row in (shape.departures if shape else ())
                for entry_id in row.cited_ids
                if entry_id
            }
        ),
        "priors": [
            {
                "key": prior.key,
                "read_at": prior.read_at,
                "answer": prior.answer,
                "cites": list(prior.cites),
                "numbers": numbers(prior.cites),
                "clause": prior.row.clause,
                "detail": prior.row.detail,
            }
            for prior in priors
        ],
    }
    return view, _Parts(
        annotate=annotate,
        annotation=annotation,
        entries=entries,
        shape=shape,
        drafted=draft is not None,
        harness=harness,
    )


def shape_view(
    session: dict[str, Json], payload: dict[str, Json], context: Json
) -> dict[str, Json]:
    """The shape alone: line states, departures and earlier departures, with no level."""
    return _read(session, payload, context)[0]


# --- the level ------------------------------------------------------------------------------------

_LEVELS = (
    levels.NONE_OR_LOW,
    levels.MEDIUM,
    levels.HIGH,
    levels.EXTREME,
    levels.NOT_ENOUGH,
)
# The levels that draw as a level: the page's `LEVEL_SCALE`. "Not enough recorded yet" never does.
_LEVEL_SCALE = (levels.NONE_OR_LOW, levels.MEDIUM, levels.HIGH, levels.EXTREME)
_ABOVE_LOW = (levels.MEDIUM, levels.HIGH, levels.EXTREME)
# The one harness with a live estimate and a monitor: `live_estimate.HARNESSES`,
# `live_lease.HARNESS`.
_LIVE_HARNESS = "claude"
REASON_LINE_NOT_SHOWN = "line-not-shown-by-a-check"
REASON_CLAIM_NOT_SHOWN = "claim-not-shown"


def _work_rows(context: Json, field: str, session: dict[str, Json]) -> dict[str, Json] | None:
    """The first row of `sources.work.<field>` that names this session, as `workOf` reads it."""
    rows = _work_block(context).get(field)
    key = _session_key(session)
    return next(
        (
            row
            for row in (rows if isinstance(rows, list) else [])
            if _truthy(row) and _session_key(row) == key
        ),
        None,
    )


def analysis_shown(shape: Shape) -> bool:
    """Whether every row of the intent stands consistent on what it names.

    The intent's rows only: the claims row is not the intent, and holding it to a consistent made
    None or low unreachable.
    """
    intent = [row for row in shape.criteria if row.key != _CLAIMS]
    return (
        bool(intent)
        and all(row.result == reading.RESULT_CONSISTENT and bool(row.rests_on) for row in intent)
        and not any(
            row.key == _CLAIMS and row.result == reading.RESULT_UNSUPPORTED
            for row in shape.criteria
        )
    )


def analysis_level(
    session: dict[str, Json],
    annotation: dict[str, Json] | None,
    shape: Shape | None,
    context: Json,
) -> dict[str, Json] | None:
    """`analysisLevel`: the server's level for the stored reading, as the page lets it stand.

    It is drawn only for the reading the page shows, only while that reading read the saved
    revision, and only for a reading the shape contract accepted. The page then holds the server's
    level to its own rows: None or low beside a line the card cannot show as consistent would
    reassure past what the rows say, and a level above None or low needs a departure the reading
    carries, because the server also reads Medium from a contradicted claim or a pass followed by a
    change, per the
    [amendment](docs/design-reading-a-session.md#amended-2026-10-21-a-level-needs-a-departure).
    Either holds the level at "not enough recorded yet", which owns the slot and draws no pill.
    """
    raw = _get(annotation, "assessment")
    if (
        not _is_record(raw)
        or shape is None
        or shape.malformed
        or _get(annotation, "not_accurate") is True
    ):
        return None
    read_at = _number(raw.get("read_at"))
    row = _work_rows(context, "analysis_levels", session)
    if (
        read_at is None
        or row is None
        or _number(row.get("read_at")) != read_at
        or _number(row.get("revision_read")) != _number(raw.get("revision_read"))
    ):
        return None
    # A level for words the reader has replaced yields to the live estimate.
    current = _number(_get(annotation, "revision"))
    if current is not None and _number(raw.get("revision_read")) != current:
        return None
    served = _text(row.get("level"))
    if served not in _LEVELS:
        return None
    level = served
    tokens = [
        _str(token) for token in (row["reasons"] if isinstance(row.get("reasons"), list) else [])
    ]
    if level == levels.NONE_OR_LOW and not analysis_shown(shape):
        level = levels.NOT_ENOUGH
        tokens.append(
            REASON_CLAIM_NOT_SHOWN
            if any(
                row.key == _CLAIMS and row.result == reading.RESULT_UNSUPPORTED
                for row in shape.criteria
            )
            else REASON_LINE_NOT_SHOWN
        )
    elif level in _ABOVE_LOW and not shape.departures:
        level = levels.NOT_ENOUGH
    return {"level": level, "reasons": list(dict.fromkeys(tokens)), "withheld": level != served}


def lease_state(context: Json) -> dict[str, Json] | None:
    """`parseLease`: the Live monitor's lease the server holds, or null when none is published."""
    lease = _work_block(context).get("live_monitor")
    return lease if _is_record(lease) and isinstance(lease.get("on"), bool) else None


def monitor_level(lease: dict[str, Json] | None) -> str | None:
    """`monitorLevel`: the level of the last completed Haiku check, only while the lease stands."""
    row = lease.get("level") if lease and lease["on"] else None
    level = _text(row.get("level")) if _is_record(row) else ""
    return level if level in _LEVELS else None


def live_estimate(
    *,
    live_on: bool,
    monitor: str | None,
    harness: str,
    context: Json,
    session: dict[str, Json],
    annotation: dict[str, Json] | None,
) -> dict[str, Json] | None:
    """`liveEstimate`: Claude Code's only, and only while the lease stands.

    The monitor's Haiku level replaces the estimate while it stands. A live row measured against
    another revision is about words the card no longer shows.
    """
    if harness != _LIVE_HARNESS or not live_on:
        return None
    if monitor:
        return {"level": monitor, "source": "monitor"}
    row = _work_rows(context, "live_levels", session)
    if row is None:
        return None
    level = _text(row.get("level"))
    if level == levels.NO_LIVE_LEVEL:
        return {"save": True}
    if level not in _LEVELS or _number(row.get("revision")) != (
        _number(_get(annotation, "revision")) or 0
    ):
        return None
    return {"level": level, "source": "live"}


def result_stale(
    shape: Shape, raw: Json, annotation: dict[str, Json] | None, entries: list[Entry]
) -> dict[str, Json] | None:
    """`resultStale`: the two stale states, from the revision read and the newest entry it saw.

    The words changing is one; new work is any entry after the reading's newest, or after when it
    read where an older row stored no such time. Compass's answer to a command the reader typed is
    not work the reading could have read.
    """
    held = [entry for entry in entries if not entry.compass_turn]
    current = _number(_get(annotation, "revision"))
    superseded = (
        shape.revision_read is not None and current is not None and shape.revision_read != current
    )
    evidence = _number(_get(raw, "evidence_through"))
    through = evidence if evidence is not None else _number(_get(raw, "read_at"))
    newer = (
        not superseded
        and through is not None
        and any((_number(entry.at) or 0) > through for entry in held)
    )
    if not superseded and not newer:
        return None
    read_at = _number(_get(raw, "read_at"))
    after = (
        next(
            (
                entry
                for entry in held
                if person_authored(entry) and (_number(entry.at) or 0) > read_at
            ),
            None,
        )
        if not superseded and read_at is not None
        else None
    )
    return {
        "kind": "intent" if superseded else "work",
        "before": _number(after.at) if after else None,
    }


def derive(
    session: dict[str, Json],
    payload: dict[str, Json],
    context: Json,
    record: list[dict[str, Json]] | None = None,
) -> dict[str, Json]:
    """The Drift card's whole answer for a fresh load: the shape, the level and the stale note.

    The level is the page's precedence
    ([DEC-27](docs/design-reading-a-session.md#amended-2026-10-21-a-level-needs-a-departure)): a
    reading that stands owns the slot, with a level or with none, so the live estimate reads checks
    and paths and never what the intent says, and draws no Medium beside a reading that found no
    departure. A drafted intent draws no pill. The Live monitor counts as on exactly while the
    server's lease stands, since a terminal has no tab to hold the switch.
    """
    view, parts = _read(session, payload, context, record)
    lease = lease_state(context)
    live_on = bool(lease and lease["on"])
    analysis = (
        analysis_level(session, parts.annotation, parts.shape, context) if parts.annotate else None
    )
    estimate = live_estimate(
        live_on=live_on,
        monitor=monitor_level(lease) if live_on else None,
        harness=parts.harness,
        context=context,
        session=session,
        annotation=parts.annotation,
    )
    shown = analysis if analysis is not None else estimate
    pill = None
    if shown and "level" in shown and not parts.drafted and shown["level"] in _LEVEL_SCALE:
        pill = {
            "level": shown["level"],
            "source": "analysis" if analysis is not None else shown["source"],
        }
        state = session.get("state")
        running = isinstance(state, str) and state != "idle" and _ended_at(session) is None
        pill["so_far"] = bool(
            running
            or (
                analysis is not None
                and parts.shape is not None
                and parts.shape.scope == "mid-flight"
            )
        )
    raw = _get(parts.annotation, "assessment")
    stale = (
        result_stale(parts.shape, raw, parts.annotation, parts.entries)
        if parts.annotate
        and parts.shape is not None
        and not parts.shape.malformed
        and _truthy(raw)
        and parts.annotation is not None
        else None
    )
    return {
        **view,
        "live_on": live_on,
        "revision": _number(_get(parts.annotation, "revision")),
        "analysis": analysis,
        "estimate": estimate,
        "pill": pill,
        # The page prefixes the answer with "So far:" on the reading's own scope, whether or not
        # a level pill is drawn (a not_enough reading draws none), so it is published beside the
        # pill, not inside it.
        "so_far": parts.shape is not None and parts.shape.scope == "mid-flight",
        "stale": stale,
    }


def _ended_at(session: dict[str, Json]) -> float | None:
    at = _number(session.get("ended_at"))
    return at if at is not None and at > 0 else None
